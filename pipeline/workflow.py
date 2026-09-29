#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Provider-neutral long-video production workflow."""

import argparse
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter

from PIL import Image, ImageStat, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import proj as PJ
from content_templates import (
    CONTENT_TEMPLATE_IDS, get_template, template_catalog, template_snapshot,
)
from cover_templates import (
    COVER_TEMPLATE_IDS, cover_template_catalog, cover_template_snapshot,
    validate_cover_template_snapshot,
)
from providers import IMAGE_PROVIDERS, LLM_PROVIDERS, make_image, make_llm
from workflow_contracts import (
    ALL_STAGES, APPROVAL_STAGES, STAGE_STATES, build_image_tasks,
    normalize_providers,
    read_json, safe_project_suffix, selected_topic,
    validate_copy, validate_image_task_prompt, validate_providers,
    validate_script, validate_storyboard,
    validate_topic, write_json, compile_image_generation_request,
    build_image_prompt,
)
from publishing_contracts import (PLATFORMS, TITLE_LIMITS, source_hashes,
                                   validate_brand, validate_cover_plan,
                                   validate_package, validate_publish_copy,
                                   validate_publish_cover,
                                   validate_publish_release_v4,
                                   validate_svg_text)


STATE_VERSION = 5
CONTENT_METHOD_LABELS = {
    "codex": "Codex 当前会话",
    "deepseek": "DeepSeek API",
    "antigravity": "Antigravity 当前会话",
}
IMAGE_METHOD_LABELS = {
    "imagegen": "Codex 内置 ImageGen",
    "wanxiang": "万相 API",
    "antigravity": "Antigravity 内置生图",
}
DEPENDENCIES = {
    "topic": [], "copy": ["topic"], "script": ["copy"],
    "storyboard": ["script"], "storyboard-review": ["script"],
    "images": ["storyboard", "storyboard-review"],
    "image-review": ["storyboard-review"],
    "voice": ["script"], "render": ["images", "voice"],
    "qa": ["render"],
}


def generation_method_summary(providers):
    """生成面向使用者的执行说明，底层 provider 值保持不变。"""
    llm = providers["llm"]["name"]
    image = providers["image"]["name"]
    handoff = None
    if llm == "antigravity" and image == "imagegen":
        handoff = (
            "内容阶段在 Antigravity 当前会话完成；"
            "图片阶段需切换到 Codex，由内置 ImageGen 执行密封任务。")
    elif llm == "codex" and image == "antigravity":
        handoff = (
            "内容阶段在 Codex 当前会话完成；"
            "图片阶段需切换到 Antigravity，使用平台内置生图。")
    elif llm == "deepseek" and image == "imagegen":
        handoff = "内容由 DeepSeek API 生成；图片阶段需在 Codex 中使用内置 ImageGen。"
    elif llm == "deepseek" and image == "antigravity":
        handoff = "内容由 DeepSeek API 生成；图片阶段需在 Antigravity 中使用内置生图。"
    return {
        "content_generation": {
            "value": llm,
            "label": CONTENT_METHOD_LABELS[llm],
        },
        "image_generation": {
            "value": image,
            "label": IMAGE_METHOD_LABELS[image],
        },
        "agent_handoff": handoff,
    }


def _interactive_image_execution_route(image_config):
    """Describe and enforce the Agent environment that owns native image tools."""
    provider_name = image_config.get("name")
    required = {"imagegen": "codex", "antigravity": "antigravity"}.get(
        provider_name, "api")
    return {
        "image_provider": provider_name,
        "required_agent_environment": required,
        "handoff_required": required in ("codex", "antigravity"),
        "instruction": (
            "内容 Agent 只写候选 JSON 后立即停止；不得生成、导入或伪造图片。"
            f"图片任务只能由 {required} 环境领取并执行。"
        ),
    }


def _require_native_image_executor(image_config):
    """Prevent Antigravity or a plain shell from claiming Codex ImageGen work."""
    route = _interactive_image_execution_route(image_config)
    if route["required_agent_environment"] == "codex" and not os.environ.get(
            "CODEX_SESSION_ID"):
        raise RuntimeError(
            "图片生成方式为 Codex ImageGen：当前不是 Codex 会话，禁止签发或确认图片；"
            "请停止当前 Agent，并在 Codex 中继续该图片阶段")
    return route


def _configured_template_id(meta):
    """读取项目模板；缺少字段的旧项目继续兼容历史默认值。"""
    if "content_template" not in meta:
        return get_template()["id"]
    value = meta.get("content_template")
    return get_template(value)["id"] if value else None


def _template_snapshot_or_none(value):
    return template_snapshot(value) if value else None


def _template_options(topic=None):
    return {
        "topic": topic,
        "options": template_catalog(),
        "instruction": (
            "由 Sol 根据已选选题推荐合适模板并说明理由；"
            "向用户展示全部选项，只有用户明确选择后才能执行 select-template。"
        ),
    }


def now_run_id():
    return "run_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def set_project(pid):
    PJ.CURRENT_ID = pid
    PJ._CACHE.clear()
    return PJ.project_dir(pid)


def project_for_id(pid):
    prefix = str(pid) + "_"
    if not os.path.isdir(PJ.PROJECTS_DIR):
        raise RuntimeError("projects 目录不存在")
    matches = [os.path.join(PJ.PROJECTS_DIR, name)
               for name in os.listdir(PJ.PROJECTS_DIR)
               if name.startswith(prefix) and
               os.path.isdir(os.path.join(PJ.PROJECTS_DIR, name))]
    if len(matches) != 1:
        raise RuntimeError(f"PROJECT={pid} 应匹配一个项目，实际 {len(matches)}")
    return matches[0]


def project_meta(project):
    return read_json(os.path.join(project, "project.json"))


def state_paths(project, run_id):
    run_dir = os.path.join(project, "workflow", "runs", run_id)
    candidates = os.path.join(project, "input", "candidates", run_id)
    return {
        "project": project,
        "run_dir": run_dir,
        "state": os.path.join(run_dir, "state.json"),
        "tasks": os.path.join(run_dir, "tasks"),
        "topic": os.path.join(candidates, "topic", "topic_candidates.json"),
        "copy": os.path.join(candidates, "copy", "copy.json"),
        "script": os.path.join(candidates, "script", "script.txt"),
        "storyboard": os.path.join(candidates, "storyboard", "storyboard.json"),
        "storyboard-review": os.path.join(run_dir, "storyboard-review.json"),
        "images": os.path.join(project, "assets", "scenes", "candidates", run_id),
        "image_tasks": os.path.join(run_dir, "image_tasks.json"),
        "image-review": os.path.join(run_dir, "image-review.json"),
        "qa": os.path.join(run_dir, "qa.json"),
    }


def formal_paths(project):
    return {
        "topic": os.path.join(project, "input", "topic.json"),
        "copy": os.path.join(project, "input", "copy.json"),
        "script": os.path.join(project, "input", "script.txt"),
        "storyboard": os.path.join(project, "input", "storyboard.json"),
        "images": os.path.join(project, "assets", "scenes"),
    }


def _style_anchor(project):
    """解析项目内视觉锚点；锚点必须是现有图片且哈希可追溯。"""
    configured = (project_meta(project).get("visual_style") or {}).get("style_anchor")
    candidates = []
    if isinstance(configured, dict) and configured.get("path"):
        candidates.append(configured["path"])
    candidates.extend((os.path.join(project, "assets", "scenes", name)
                       for name in ("00_1.png", "00_0.png")))
    for path in candidates:
        path = os.path.realpath(path)
        if os.path.isfile(path):
            return {"path": path, "sha256": _sha256(path)}
    return None


def _run_style_anchor(state, project):
    """优先使用本 run 已确认的首图锚点，避免项目配置回写影响候选包。"""
    anchor = state.get("image_anchor")
    if isinstance(anchor, dict) and anchor.get("path") and anchor.get("sha256"):
        path = os.path.realpath(anchor["path"])
        if os.path.isfile(path) and _sha256(path) == anchor["sha256"]:
            return {"path": path, "sha256": anchor["sha256"]}
    return _style_anchor(project)


def _bootstrap_key(storyboard, project, characters, images_dir):
    tasks = build_image_tasks(storyboard, project_meta(project), characters,
                              images_dir)
    if not tasks:
        raise RuntimeError("正式分镜没有可生成的图片任务")
    return tasks[0]["key"]


def _task_image_path(paths, task):
    return os.path.join(paths["images"], task["key"] + ".png")


def _image_execution_policy(provider_name="imagegen"):
    """交互式图片任务必须逐张签发，不能由调用方自行并发。"""
    return {
        "mode": "serial",
        "provider": provider_name,
        "unit": "single_task",
        "completion": "上一张候选图片可读取且为 16:9 后，才可签发下一张",
    }


def _image_file_problem(task):
    """返回单图能否解锁下一任务的确定性检查结果。"""
    path = task.get("output_path")
    if not path or not os.path.isfile(path):
        return "候选图片尚未落盘"
    try:
        with Image.open(path) as image:
            if image.format != "PNG":
                return "候选图片必须是 PNG"
            image.load()
            width, height = image.size
        if abs(width / height - 16 / 9) > 0.02:
            return f"候选图片比例不是 16:9：{width}x{height}"
    except OSError as exc:
        return f"候选图片无法读取：{exc}"
    return None


@contextlib.contextmanager
def _image_generation_lock(paths):
    """短临界区锁：只保护签发/状态落盘，绝不包住外部生图。"""
    lock_path = paths["state"] + ".images.lock"
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _new_image_generation(packet, state):
    """仅把已明确选择且哈希匹配的视觉锚点迁入已完成列表。"""
    completed = []
    completed_sha256 = {}
    anchor = state.get("image_anchor")
    by_key = {task.get("key"): task for task in packet.get("tasks", [])}
    if isinstance(anchor, dict) and anchor.get("key") in by_key:
        task = by_key[anchor["key"]]
        path = task.get("output_path")
        if (not _image_file_problem(task) and anchor.get("sha256") and
                os.path.realpath(path) == os.path.realpath(anchor.get("path", "")) and
                _sha256(path) == anchor["sha256"]):
            completed.append(anchor["key"])
            completed_sha256[anchor["key"]] = anchor["sha256"]
    return {
        "version": 1,
        "manifest_sha256": _sha256_current(packet),
        "active_key": None,
        "completed_keys": completed,
        "completed_sha256": completed_sha256,
        "active_request": None,
    }


def _sha256_current(data):
    """与 write_json 的确定性序列化保持一致，不依赖临时文件。"""
    encoded = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def locate_run(run_id, pid=None):
    projects = [project_for_id(pid)] if pid else [
        p for p in (os.path.join(PJ.PROJECTS_DIR, name)
                    for name in os.listdir(PJ.PROJECTS_DIR)) if os.path.isdir(p)]
    found = []
    for project in projects:
        path = state_paths(project, run_id)["state"]
        if os.path.exists(path):
            found.append(project)
    if len(found) != 1:
        raise RuntimeError(f"run_id={run_id} 应匹配一个任务，实际 {len(found)}")
    project = found[0]
    paths = state_paths(project, run_id)
    state = read_json(paths["state"])
    _upgrade_state_schema(paths, state)
    return paths, state


def _upgrade_state_schema(paths, state):
    """为质量门禁引入前的历史 run 补齐兼容阶段。"""
    stages = state.setdefault("stages", {})
    changed = False
    if "content_template" not in state:
        state["content_template"] = template_snapshot(
            _configured_template_id(project_meta(paths["project"])))
        changed = True
    image_review = stages.get("image-review", {})
    if (image_review.get("status") == "promoted" and
            image_review.get("note") == "自动图片质量门禁通过" and
            os.path.exists(paths["image-review"]) and
            read_json(paths["image-review"]).get("manual_exception")):
        image_review["note"] = "人工审核例外已确认并提升"
        changed = True
    # V3 将分镜审核前移到正式提升前。历史 run 没有可证明的候选
    # 审核记录时，不得将其静默视为通过；应通过 revision 重建该证据链。
    if state.get("version", 1) < 3:
        review = stages.get("storyboard-review")
        storyboard_status = stages.get("storyboard", {}).get("status")
        if storyboard_status == "promoted" and review:
            candidate_storyboard = paths["storyboard"]
            formal_storyboard = formal_paths(paths["project"])["storyboard"]
            matching_assets = (
                os.path.exists(candidate_storyboard) and
                os.path.exists(formal_storyboard) and
                _sha256(candidate_storyboard) == _sha256(formal_storyboard))
            if review.get("status") == "promoted":
                report_path = paths["storyboard-review"]
                valid_record = (
                    os.path.exists(report_path) and matching_assets and
                    read_json(report_path).get("source_sha256") == _sha256(formal_storyboard) and
                    read_json(report_path).get("verdict") == "pass")
                if not valid_record:
                    stages["storyboard-review"] = {
                        "status": "blocked",
                        "note": "历史 run 缺少可追溯的候选分镜审核；请创建 storyboard revision",
                        "artifact": None,
                    }
            elif matching_assets:
                state["legacy_storyboard_review"] = {
                    "source_sha256": _sha256(candidate_storyboard),
                    "note": "正式分镜与候选一致，允许补做一次历史衔接审核",
                }
                stages["storyboard-review"] = {
                    "status": "pending",
                    "note": "历史分镜待补做审核；不需重做候选",
                    "artifact": None,
                }
            else:
                stages["storyboard-review"] = {
                    "status": "blocked",
                    "note": "历史正式分镜与候选不一致；请创建 storyboard revision",
                    "artifact": None,
                }
        state["version"] = 3
        changed = True
    # V4 将 ImageGen 的交互式整批任务改为状态机逐张签发。历史 run 仅可
    # 承认用户已经显式确认且哈希绑定的首图锚点；目录里的其他残留图不能绕过队列。
    if state.get("version", 1) < 4:
        if (state.get("providers", {}).get("image", {}).get("name") == "imagegen" and
                os.path.exists(paths["image_tasks"])):
            packet = read_json(paths["image_tasks"])
            if isinstance(packet, dict) and isinstance(packet.get("tasks"), list):
                if "execution_policy" not in packet:
                    packet["execution_policy"] = _image_execution_policy("imagegen")
                    write_json(paths["image_tasks"], packet)
                if "image_generation" not in state:
                    state["image_generation"] = _new_image_generation(packet, state)
        state["version"] = STATE_VERSION
        changed = True
    if state.get("version", 1) < 5:
        state["version"] = STATE_VERSION
        changed = True
    for stage in ALL_STAGES:
        if stage in stages:
            continue
        if stage == "image-review" and stages.get("images", {}).get("status") == "promoted":
            stages[stage] = {"status": "promoted", "note": "历史图片在 image-review 门禁引入前已完成", "artifact": None}
        elif stage == "storyboard-review" and stages.get("storyboard", {}).get("status") == "promoted":
            stages[stage] = {"status": "blocked", "note": "历史分镜缺少可追溯审核；请创建 storyboard revision", "artifact": None}
        else:
            stages[stage] = {"status": "blocked", "note": "新增质量门禁待执行", "artifact": None}
        changed = True
    if changed:
        save_state(paths, state)


def save_state(paths, state):
    state["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    write_json(paths["state"], state)


def transition(state, stage, status, note="", artifact=None):
    if status not in STAGE_STATES:
        raise ValueError(f"未知阶段状态：{status}")
    item = state["stages"][stage]
    item.update({"status": status, "note": note})
    if artifact:
        item["artifact"] = artifact
    state["current_stage"] = stage


def require_dependencies(state, stage):
    missing = [dep for dep in DEPENDENCIES[stage]
               if state["stages"][dep]["status"] != "promoted"]
    if missing:
        raise RuntimeError(f"阶段 {stage} 被阻断，需先提升：{', '.join(missing)}")
    if stage == "copy" and not state.get("content_template"):
        raise RuntimeError(
            "copy 被阻断：请先根据已提升选题推荐内容模板，"
            "由用户明确选择后执行 select-template")


def _require_reviewed_storyboard(paths, state, source_path):
    """确认图片将消费与已审核候选完全相同的正式分镜。"""
    if state["stages"]["storyboard-review"]["status"] != "promoted":
        raise RuntimeError("images 必须在 storyboard-review 通过后运行")
    if not os.path.exists(paths["storyboard-review"]):
        raise RuntimeError("缺少 storyboard-review 审核记录")
    report = read_json(paths["storyboard-review"])
    if report.get("verdict") != "pass":
        raise RuntimeError("storyboard-review 未通过")
    if report.get("source_sha256") != _sha256(source_path):
        raise RuntimeError("正式分镜与已通过的 storyboard-review 哈希不一致")


def _storyboard_review(paths, project, content_template=None):
    """生成可追溯的确定性分镜审核结果。"""
    story = read_json(paths["storyboard"])
    script_path = formal_paths(project)["script"]
    with open(script_path, encoding="utf-8") as handle:
        script_problems, _, blocks = validate_script(
            handle.read(), content_template=content_template)
    issues = []
    quality_problems = validate_storyboard(
        story, blocks, project_meta=project_meta(project),
        enforce_visual_quality=True)
    for block in story.get("blocks", []):
        source = blocks[block.get("block_idx", -1)] if isinstance(block.get("block_idx"), int) and block.get("block_idx", -1) < len(blocks) else {}
        voice = source.get("voice") or ""
        for beat in block.get("beats", []):
            desc = str(beat.get("visual_description") or "")
            beat_issues = []
            if len(desc) < 18: beat_issues.append("具体性不足")
            if beat.get("character_ids") == [] and any(x in voice for x in ("人物", "主角", "他", "她")):
                beat_issues.append("角色信息缺失")
            issues.append({"block_idx": block.get("block_idx"), "beat_idx": beat.get("beat_idx"),
                           "verdict": "fail" if beat_issues else "pass", "issues": beat_issues,
                           "suggestion": "补充与字幕对应的场景、主体、动作和关键物件" if beat_issues else ""})
    if quality_problems:
        issues.append({"block_idx": None, "beat_idx": None, "verdict": "fail",
                       "issues": quality_problems,
                       "suggestion": "按分镜质量契约重做场景、动作和情绪分布"})
    report = {"version": 1, "source_sha256": _sha256(paths["storyboard"]),
              "script_sha256": _sha256(script_path), "beats": issues,
              "verdict": "fail" if script_problems or quality_problems or any(x["verdict"] == "fail" for x in issues) else "pass",
              "script_issues": script_problems}
    write_json(paths["storyboard-review"], report)
    return report


def ensure_active_run(state, action):
    if state.get("superseded_by"):
        raise RuntimeError(f"源 run 已被 {state['superseded_by']} supersede，不能执行 {action}，仅允许 status")


def cmd_revise(args):
    if args.stage != "storyboard":
        raise ValueError("revise 目前只支持 storyboard")
    source_paths, source = locate_run(args.source_run_id, args.project)
    ensure_active_run(source, "revision")
    if source["stages"]["script"]["status"] != "promoted":
        raise RuntimeError("源 run 的 script 必须已提升")
    run_id = args.run_id or now_run_id()
    paths = state_paths(source_paths["project"], run_id)
    if os.path.exists(paths["state"]):
        raise FileExistsError(f"run 已存在：{run_id}")
    formal = formal_paths(source_paths["project"])
    stages = {}
    for stage in ALL_STAGES:
        stages[stage] = {"status": "blocked", "note": "由 storyboard revision 阻断", "artifact": None}
    for stage in ("topic", "copy", "script"):
        stages[stage] = {"status": "promoted", "note": "继承源 run 正式资产", "artifact": os.path.abspath(formal[stage])}
    stages["storyboard"] = {"status": "pending", "note": "等待重新生成", "artifact": None}
    stages["voice"] = {"status": "pending", "note": "继承 script 后可继续", "artifact": None}
    state = {"version": STATE_VERSION, "run_id": run_id, "project_id": str(args.project),
             "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             "updated_at": "", "providers": source["providers"], "current_stage": "storyboard",
             "content_template": source.get("content_template", get_template()),
             "lineage": {"source_run": args.source_run_id, "restart_stage": "storyboard",
                         "inherited_assets": {stage: {"path": os.path.abspath(formal[stage]),
                             "sha256": _sha256(formal[stage])} for stage in ("topic", "copy", "script")}},
             "stages": stages}
    os.makedirs(paths["tasks"], exist_ok=True)
    os.makedirs(os.path.dirname(paths["storyboard"]), exist_ok=True)
    save_state(paths, state)
    source["superseded_by"] = run_id
    save_state(source_paths, source)
    print(json.dumps({"run_id": run_id, "source_run": args.source_run_id,
                      "state": paths["state"]}, ensure_ascii=False, indent=2))


def _check_provider_history(project, providers):
    """所有历史 run 必须保持项目 LLM 与图片配置，不改写旧快照。"""
    states = []
    runs_root = os.path.join(project, "workflow", "runs")
    if not os.path.isdir(runs_root):
        return states
    for name in os.listdir(runs_root):
        state_path = os.path.join(runs_root, name, "state.json")
        if os.path.isfile(state_path):
            state = read_json(state_path)
            for group, label in (("llm", "LLM"), ("image", "图片")):
                previous = state.get("providers", {}).get(group)
                if not isinstance(previous, dict) or "name" not in previous:
                    raise RuntimeError(
                        f"历史 run 缺少 {label} provider 快照，需先核查历史配置")
                previous = normalize_providers({group: previous})[group]
                if previous != providers[group]:
                    raise RuntimeError(
                        f"项目 {label} provider 与历史 run 快照不一致；"
                        "请恢复项目配置，或新建项目")
            states.append(state)
    return states


def cmd_create(args):
    PJ.CURRENT_ID = args.project
    PJ._CACHE.clear()
    existed = PJ._find_dir(args.project) is not None
    if not existed:
        missing = [option for option in ("llm", "image")
                   if getattr(args, option, None) is None]
        if missing:
            flags = "、".join("--" + option for option in missing)
            raise ValueError(
                f"新项目必须显式指定 {flags}；"
                "内容生成方式可选 "
                "codex=Codex 当前会话、deepseek=DeepSeek API、"
                "antigravity=Antigravity 当前会话；"
                "图片生成方式可选 "
                "imagegen=Codex 内置 ImageGen、wanxiang=万相 API、"
                "antigravity=Antigravity 内置生图")
    if getattr(args, "llm", None) == "antigravity" and \
            getattr(args, "llm_model", None) is not None:
        raise ValueError("Antigravity LLM 跟随当前会话模型，禁止指定 --llm-model")
    if getattr(args, "image", None) == "antigravity" and \
            getattr(args, "image_model", None) is not None:
        raise ValueError("Antigravity 使用平台内置生图模型，禁止指定 --image-model")
    project = PJ.project_dir(args.project, title="新项目", author="")
    meta_path = os.path.join(project, "project.json")
    meta = read_json(meta_path)
    # 已有项目未指定的参数沿用原配置；新项目已在创建目录前强制显式选择。
    current = normalize_providers(meta.get("providers"))
    proposed = normalize_providers(meta.get("providers"))
    for group, field, option in (
            ("llm", "name", "llm"), ("llm", "model", "llm_model"),
            ("image", "name", "image"), ("image", "model", "image_model"),
            ("speech", "voice", "azure_voice")):
        value = getattr(args, option, None)
        if value is not None:
            if field == "name" and proposed[group][field] != value:
                proposed[group]["model"] = None
            proposed[group][field] = value
    problems = validate_providers(proposed, LLM_PROVIDERS, IMAGE_PROVIDERS)
    if problems:
        raise ValueError("；".join(problems))
    requested_template = getattr(args, "content_template", None)
    stored_template = _configured_template_id(meta) if existed else None
    template_id = (get_template(requested_template)["id"]
                   if requested_template else stored_template)
    changed = (proposed != normalize_providers(meta.get("providers")) or
               template_id != stored_template)
    if existed:
        if any(proposed[group] != current[group] for group in ("llm", "image")):
            raise RuntimeError(
                "项目 LLM 与图片 provider/model 已固定，禁止切换；"
                "请使用新项目 id 重新选择")
        states = _check_provider_history(project, proposed)
        if changed and any(state.get("stages", {}).get("qa", {}).get("status")
                           != "promoted" for state in states):
            raise RuntimeError("项目存在活动 run，禁止修改其他 provider 或内容模板配置")
    if not existed or changed:
        meta["providers"] = proposed
        meta["content_template"] = template_id
        write_json(meta_path, meta)
    request = os.path.join(project, "input", "topic_request.md")
    if not os.path.exists(request):
        os.makedirs(os.path.dirname(request), exist_ok=True)
        with open(request, "w", encoding="utf-8") as f:
            f.write("# 选题需求\n\n## 频道定位\n\n## 目标受众\n\n"
                    "## 希望解决的问题\n\n## 排除方向\n\n"
                    "## 候选书池（可选）\n\n")
    print(json.dumps({"project": project, "providers": proposed,
                      "generation_methods": generation_method_summary(proposed),
                      "content_template": template_id,
                      "template_selection_required": template_id is None,
                      "topic_request": request}, ensure_ascii=False, indent=2))


def cmd_init(args):
    if PJ._find_dir(args.project) is None:
        raise RuntimeError(
            f"PROJECT={args.project} 尚未创建；"
            "请先使用 create 并显式选择 --llm 与 --image")
    project = set_project(args.project)
    meta = project_meta(project)
    configured = meta.get("providers") or {}
    problems = validate_providers(configured, LLM_PROVIDERS, IMAGE_PROVIDERS)
    if problems:
        raise ValueError("；".join(problems))
    providers = normalize_providers(configured)
    _check_provider_history(project, providers)
    template_id = _configured_template_id(meta)
    content_template = _template_snapshot_or_none(template_id)
    run_id = args.run_id or now_run_id()
    paths = state_paths(project, run_id)
    if os.path.exists(paths["state"]):
        raise FileExistsError(f"run 已存在：{run_id}")
    statuses = {}
    for stage in ALL_STAGES:
        statuses[stage] = {"status": "pending" if not DEPENDENCIES[stage]
                           else "blocked", "note": "", "artifact": None}
    state = {
        "version": STATE_VERSION, "run_id": run_id,
        "project_id": str(args.project),
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": "", "providers": providers,
        "content_template": content_template,
        "template_selection": {
            "status": "selected" if content_template else "awaiting_topic",
            "selected_id": content_template["id"] if content_template else None,
            "source": "create" if content_template else None,
        },
        "current_stage": "topic", "stages": statuses,
    }
    save_state(paths, state)
    print(json.dumps({"run_id": run_id, "state": paths["state"],
                      "providers": providers,
                      "content_template": (content_template["id"]
                                           if content_template else None),
                      "template_selection_required": content_template is None},
                     ensure_ascii=False, indent=2))


def build_task(paths, state, stage):
    project = paths["project"]
    formal = formal_paths(project)
    content_template = _template_snapshot_or_none(state.get("content_template"))
    names = ([x["name"] for x in content_template["stages"]]
             if content_template else [])
    if stage == "topic":
        request = os.path.join(project, "input", "topic_request.md")
        with open(request, encoding="utf-8") as handle:
            request_text = handle.read()
        return {"stage": stage, "topic_request": request_text,
                "candidate_path": paths[stage],
                "content_template": content_template,
                "output_contract": {
                    "type": "json",
                    "top_level": ["candidates", "selected_id"],
                    "candidate_fields": [
                        "id", "book_title", "author", "angle",
                        "audience_promise", "video_title", "rationale",
                    ],
                    "requirements": "输出 3 个候选；id 唯一；selected_id 初始为 null",
                }}
    if content_template is None:
        raise RuntimeError(
            f"{stage} 被阻断：内容模板尚未由用户明确选择")
    if stage == "copy":
        return {"stage": stage, "topic": read_json(formal["topic"]),
                "candidate_path": paths[stage],
                "content_template": content_template, "output_contract": {
                    "type": "json",
                    "fields": ["thesis", "audience_promise", "claims", "sections"],
                    "requirements": "sections 恰好五段，阶段名依次为" + "、".join(names) + "，每段含 name/objective/"
                                    "key_points/examples/action",
                }}
    if stage == "script":
        return {"stage": stage, "topic": read_json(formal["topic"]),
                "copy": read_json(formal["copy"]),
                "candidate_path": paths[stage],
                "content_template": content_template, "output_contract": {
                    "type": "text", "voice_chars": [3800, 4500],
                    "requirements": "# TITLE；五个 # PHASE nn · " + "、".join(names) + "；内容块用"
                                    " # CARD/# QUOTE/# TABLE/# STEPS；以 # END 结束；"
                                    "所有非 PHASE/END 内容块必须含 voice：",
                }}
    if stage == "storyboard":
        with open(formal["script"], encoding="utf-8") as f:
            script = f.read()
        phase_transition = (project_meta(project).get("visual_style") or {}).get(
            "phase_transition", "card")
        return {"stage": stage, "script_text": script, "content_template": content_template,
                "characters_path": os.path.join(ROOT, "assets", "characters.json"),
                "candidate_path": paths[stage],
                "phase_transition": phase_transition,
                "output_contract": {
                    "type": "json", "top_level": ["version", "blocks"],
                    "block_fields": ["block_idx", "type", "head", "voice_chars",
                                     "subtitles", "beats"],
                    "beat_fields": ["beat_idx", "shot", "visual_description",
                                    "sentence_ids", "start_char", "end_char",
                                    "character_ids", "emotion", "segment"],
                    "requirements": "逐块对应剧本；每句按顺序恰好覆盖一次；" +
                                    ("PHASE 必须为 0 beat；" if phase_transition == "direct"
                                     else "PHASE 只能 1 beat；") +
                                    "非 PHASE 有口播块按字数至少"
                                    " 1+ceil((voice_chars-120)/100) 拍（不超过 120 字/拍、"
                                    "每拍 1-4 句）；shot=wide/medium/close；"
                                    "segment=hook/insight/action；visual_description 必须严格使用"
                                    "场景：…；主体：…；动作：…；关键物件：…；动作/情绪需有分布，"
                                    "连续不得 4 拍完全相同；明确地点时画面必须落地；不得使用占位式描述",
                    "forbidden_fields": ["provider", "model", "final_image_prompt",
                                         "negative_prompt", "api_request"],
                }}
    raise ValueError(stage)


def _run_serial_interactive_images(paths, state, tasks, mode, bootstrap_key,
                                   args):
    """签发交互式 provider 的唯一下一张图片任务并确认落盘。"""
    with _image_generation_lock(paths):
        # 领取锁后重新读取，避免两个调用者各自从旧 state 签发不同图片。
        state = read_json(paths["state"])
        provider_name = state["providers"]["image"]["name"]
        _require_native_image_executor(state["providers"]["image"])
        execution_policy = _image_execution_policy(provider_name)
        packet = None
        if os.path.exists(paths["image_tasks"]):
            packet = read_json(paths["image_tasks"])
        generation = state.get("image_generation")
        if generation:
            if not isinstance(packet, dict) or \
                    packet.get("execution_policy") != execution_policy:
                raise RuntimeError(
                    f"{provider_name} 串行任务包缺少或篡改 execution_policy")
            if _image_task_packet_problems(tasks, packet.get("tasks", [])):
                raise RuntimeError("图片任务包与正式分镜不一致，禁止变更串行队列")
            if generation.get("manifest_sha256") != _sha256(paths["image_tasks"]):
                raise RuntimeError(
                    f"{provider_name} 串行任务清单已变化，禁止继续；请创建新的 run")
        else:
            packet = {
                "tasks": tasks,
                "mode": mode,
                "bootstrap_key": bootstrap_key,
                "execution_policy": execution_policy,
            }
            write_json(paths["image_tasks"], packet)
            generation = _new_image_generation(packet, state)
            state["image_generation"] = generation

        by_key = {task["key"]: task for task in tasks}
        completed = list(generation.get("completed_keys", []))
        completed_hashes = dict(generation.get("completed_sha256", {}))
        if len(completed) != len(set(completed)) or any(key not in by_key for key in completed):
            raise RuntimeError(f"{provider_name} 串行状态的 completed_keys 无效")
        for key in completed:
            task = by_key[key]
            problem = _image_file_problem(task)
            if problem:
                raise RuntimeError(f"已完成候选图片已失效：{key}：{problem}")
            if completed_hashes.get(key) != _sha256(task["output_path"]):
                raise RuntimeError(f"已完成候选图片哈希已变化：{key}")

        active_key = generation.get("active_key")
        if active_key:
            if active_key not in by_key or active_key in completed:
                raise RuntimeError(f"{provider_name} 串行状态的 active_key 无效")
            active = by_key[active_key]
            # 历史 active_key 允许补齐密封请求；如果图片尚未落盘，它会以
            # 相同哈希重签，不会把旧的自由附加提示带入后续执行。
            try:
                request = compile_image_generation_request(active)
            except ValueError as exc:
                raise RuntimeError(
                    f"{provider_name} 提示契约门禁失败：{exc}") from exc
            recorded = generation.get("active_request")
            if recorded and (recorded.get("semantic_sha256") != request["semantic_sha256"] or
                             recorded.get("request_sha256") != request["request_sha256"]):
                raise RuntimeError(
                    f"{provider_name} 当前任务的密封请求哈希不一致，禁止完成或重签")
            if not recorded:
                generation["active_request"] = request
            problem = _image_file_problem(active)
            if problem:
                transition(state, "images", "awaiting_external",
                           f"等待当前 {provider_name} 候选落盘："
                           f"{active_key}（{problem}）",
                           paths["image_tasks"])
                save_state(paths, state)
                signed_task = dict(active, generation_request=request)
                print(json.dumps({"state": state["stages"]["images"],
                                  "tasks": [signed_task], "all_task_count": len(tasks),
                                  "serial": {"active_key": active_key,
                                             "completed": len(completed)}},
                                 ensure_ascii=False, indent=2))
                return
            completed.append(active_key)
            completed_hashes[active_key] = _sha256(active["output_path"])
            generation["active_key"] = None
            generation["active_request"] = None
            generation["completed_keys"] = completed
            generation["completed_sha256"] = completed_hashes

        next_task = next((task for task in tasks if task["key"] not in completed), None)
        if not next_task:
            transition(state, "images", "generated",
                       f"全部 {provider_name} 候选已逐张校验落盘",
                       paths["image_tasks"])
            save_state(paths, state)
            print(json.dumps({"state": state["stages"]["images"], "tasks": [],
                              "all_task_count": len(tasks),
                              "serial": {"completed": len(completed)}},
                             ensure_ascii=False, indent=2))
            return
        wanted = set(getattr(args, "beats", None) or [])
        if wanted and wanted != {next_task["key"]}:
            raise RuntimeError(
                f"{provider_name} 串行模式只能签发当前下一张：{next_task['key']}")
        # 先编译并验证密封请求，失败时绝不占用 active_key。
        try:
            request = compile_image_generation_request(next_task)
        except ValueError as exc:
            raise RuntimeError(
                f"{provider_name} 提示契约门禁失败：{exc}") from exc
        generation["active_key"] = next_task["key"]
        generation["active_request"] = request
        state["image_generation"] = generation
        provider = make_image(state["providers"]["image"], ROOT)
        try:
            result = provider.generate([next_task])
        except Exception as exc:
            transition(state, "images", "failed", str(exc), paths["image_tasks"])
            save_state(paths, state)
            raise
        if result.get("mode") != "interactive":
            raise RuntimeError(f"{provider_name} 必须使用交互式逐张生成模式")
        transition(state, "images", "awaiting_external",
                   f"已签发 {provider_name} 单图：{next_task['key']}；"
                   "落盘并通过 16:9 检查后再运行 images",
                   paths["image_tasks"])
        save_state(paths, state)
        signed_task = dict(next_task, generation_request=request)
        print(json.dumps({"state": state["stages"]["images"],
                          "tasks": [signed_task], "all_task_count": len(tasks),
                          "serial": {"active_key": next_task["key"],
                                     "completed": len(completed)}},
                         ensure_ascii=False, indent=2))


def cmd_run(args):
    paths, state = locate_run(args.run_id, args.project)
    ensure_active_run(state, "run")
    stage = args.stage
    review_render = stage == "render" and bool(getattr(args, "review_id", None))
    revision_render = stage == "render" and bool(getattr(args, "revision", None))
    if stage != "render" and any((getattr(args, "review_id", None),
                                  getattr(args, "revision", None),
                                  getattr(args, "blocks", None),
                                  getattr(args, "clip_durations", None),
                                  getattr(args, "phase_images_dir", None),
                                  getattr(args, "image_overrides_dir", None),
                                  getattr(args, "reuse_segments_dir", None),
                                  getattr(args, "rerender_blocks", None))):
        raise ValueError("review/revision/blocks 参数只允许用于 render 阶段")
    if review_render and not getattr(args, "blocks", None):
        raise ValueError("review render 必须显式指定 --blocks")
    if state["stages"][stage]["status"] in ("verified", "promoted") and not (
            review_render or revision_render):
        raise RuntimeError(f"阶段 {stage} 已校验或完成，不能在同一 run 内重新生成")
    require_dependencies(state, stage)
    project = paths["project"]
    if stage == "storyboard-review":
        storyboard_status = state["stages"]["storyboard"]["status"]
        legacy = state.get("legacy_storyboard_review")
        is_legacy_bridge = (
            storyboard_status == "promoted" and isinstance(legacy, dict) and
            legacy.get("source_sha256") == _sha256(paths["storyboard"]) and
            legacy.get("source_sha256") == _sha256(formal_paths(project)["storyboard"]))
        if storyboard_status != "verified" and not is_legacy_bridge:
            raise RuntimeError("storyboard-review 必须在 storyboard 候选校验通过后运行")
        report = _storyboard_review(paths, project, state.get("content_template"))
        transition(state, stage, "generated", "自动分镜质量审核已生成", paths["storyboard-review"])
        save_state(paths, state)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    if stage == "image-review":
        report = _image_review(paths, project, state)
        transition(state, stage, "generated", "自动图片风格与安全审核已生成", paths["image-review"])
        save_state(paths, state)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    if stage in ("topic", "copy", "script", "storyboard"):
        task = build_task(paths, state, stage)
        task_path = os.path.join(paths["tasks"], stage + ".json")
        write_json(task_path, task)
        provider_config = state["providers"]["llm"]
        provider_name = provider_config["name"]
        provider = make_llm(provider_config, ROOT)
        try:
            result = provider.generate(stage, task, paths[stage])
        except Exception as exc:
            transition(state, stage, "failed", str(exc))
            save_state(paths, state)
            raise
        if result["mode"] == "interactive":
            transition(state, stage, "awaiting_external",
                       f"等待外部 {provider_name} 写入候选：{paths[stage]}",
                       task_path)
        else:
            transition(state, stage, "generated",
                       f"{provider_name} 候选已生成",
                       paths[stage])
        save_state(paths, state)
        print(json.dumps({"state": state["stages"][stage],
                          "task": task_path, "candidate": paths[stage]},
                         ensure_ascii=False, indent=2))
        return
    if stage == "images":
        formal_storyboard = formal_paths(project)["storyboard"]
        _require_reviewed_storyboard(paths, state, formal_storyboard)
        storyboard = read_json(formal_storyboard)
        chars_path = os.path.join(ROOT, "assets", "characters.json")
        characters = read_json(chars_path) if os.path.exists(chars_path) else {}
        anchor = _run_style_anchor(state, project)
        bootstrap_key = None
        if not anchor:
            bootstrap_key = _bootstrap_key(storyboard, project, characters,
                                           paths["images"])
        tasks = build_image_tasks(storyboard, project_meta(project), characters,
                                  paths["images"], anchor,
                                  bootstrap_anchor_key=bootstrap_key)
        # 新项目没有锚点时，只生成首张可审核候选。选定后才生成其余图片，
        # 防止在风格尚未确认前消耗整批图片额度。
        if bootstrap_key:
            selected_tasks = [task for task in tasks if task["key"] == bootstrap_key]
            packet_mode = "bootstrap"
        else:
            selected_tasks = [task for task in tasks if _image_file_problem(task)]
            packet_mode = "full"
        provider = make_image(state["providers"]["image"], ROOT)
        if provider.mode == "interactive":
            # selected_tasks 仅保留给 API provider；交互式完整清单逐张签发。
            serial_tasks = selected_tasks if bootstrap_key else tasks
            _run_serial_interactive_images(
                paths, state, serial_tasks, packet_mode,
                bootstrap_key or state.get("image_anchor", {}).get("key"), args)
            return
        write_json(paths["image_tasks"], {"tasks": (selected_tasks if bootstrap_key else tasks),
                                          "mode": packet_mode,
                                          "bootstrap_key": bootstrap_key or state.get("image_anchor", {}).get("key")})
        if args.beats:
            wanted = set(args.beats)
            unknown = wanted - {task["key"] for task in tasks}
            if unknown:
                raise ValueError("未知图片任务：" + ", ".join(sorted(unknown)))
            if bootstrap_key and wanted != {bootstrap_key}:
                raise RuntimeError("尚未确认首图锚点；首次只能生成 " + bootstrap_key)
            selected_tasks = [task for task in tasks if task["key"] in wanted]
        try:
            result = provider.generate(selected_tasks)
        except Exception as exc:
            transition(state, stage, "failed", str(exc), paths["image_tasks"])
            save_state(paths, state)
            raise
        status = "awaiting_external" if result["mode"] == "interactive" else "generated"
        provider_name = state["providers"]["image"]["name"]
        transition(state, stage, status,
                   f"等待 {provider_name} 写入候选图片"
                   if status == "awaiting_external"
                   else f"已生成 {len(selected_tasks)} 张候选图片", paths["image_tasks"])
        save_state(paths, state)
        print(json.dumps({"state": state["stages"][stage],
                          "tasks": selected_tasks,
                          "all_task_count": len(tasks)},
                         ensure_ascii=False, indent=2))
        return
    if stage == "voice":
        _run_voice(paths, state)
    elif stage == "render":
        _run_render(paths, state, args)
    elif stage == "qa":
        _run_qa(paths, state)
    else:
        raise ValueError(stage)


def cmd_select_topic(args):
    paths, state = locate_run(args.run_id, args.project)
    ensure_active_run(state, "select-topic")
    if state["stages"]["topic"]["status"] not in {
            "awaiting_external", "generated", "failed"}:
        raise RuntimeError("topic 尚未生成或已经提升，不能选择候选")
    data = read_json(paths["topic"])
    ids = {x.get("id") for x in data.get("candidates", [])}
    if args.candidate_id not in ids:
        raise ValueError(f"未知 topic candidate：{args.candidate_id}")
    data["selected_id"] = args.candidate_id
    write_json(paths["topic"], data)
    transition(state, "topic", "generated", f"已选择 {args.candidate_id}",
               paths["topic"])
    save_state(paths, state)
    print(f"已选择 topic：{args.candidate_id}")


def cmd_template_options(args):
    """输出已选正式选题与动态模板目录，供 Sol 推荐和用户比较。"""
    paths, state = locate_run(args.run_id, args.project)
    ensure_active_run(state, "template-options")
    if state["stages"]["topic"]["status"] != "promoted":
        raise RuntimeError("内容模板推荐必须在 topic 选择、校验并提升后进行")
    topic_path = formal_paths(paths["project"])["topic"]
    result = _template_options(read_json(topic_path))
    result["selection"] = state.get("template_selection")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_select_template(args):
    """记录推荐依据和用户最终选择，并解锁 copy。"""
    paths, state = locate_run(args.run_id, args.project)
    ensure_active_run(state, "select-template")
    if state["stages"]["topic"]["status"] != "promoted":
        raise RuntimeError("必须先选择、校验并提升 topic，才能选择内容模板")
    if state.get("content_template"):
        raise RuntimeError("当前 run 的内容模板已经选定，禁止更改")
    if state["stages"]["copy"]["status"] not in {"blocked", "pending"}:
        raise RuntimeError("copy 已开始，禁止更改内容模板")
    reason = str(args.reason or "").strip()
    if not reason:
        raise ValueError("模板推荐理由不能为空")
    selected = get_template(args.template_id)
    recommended = get_template(args.recommended)
    topic_path = formal_paths(paths["project"])["topic"]
    meta_path = os.path.join(paths["project"], "project.json")
    meta = read_json(meta_path)
    project_template = _configured_template_id(meta)
    if project_template and project_template != selected["id"]:
        raise RuntimeError(
            "项目已被另一 run 锁定为不同内容模板，禁止覆盖；请核对活动 run")
    state["content_template"] = selected
    state["template_selection"] = {
        "status": "selected",
        "recommended_id": recommended["id"],
        "recommendation_reason": reason,
        "selected_id": selected["id"],
        "manual_confirmation": True,
        "topic_sha256": _sha256(topic_path),
        "selected_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    meta["content_template"] = selected["id"]
    write_json(meta_path, meta)
    unlock(state)
    save_state(paths, state)
    print(json.dumps(state["template_selection"], ensure_ascii=False, indent=2))


def cmd_select_image_anchor(args):
    """确认首张候选为 run 级视觉锚点；不自动提升任何正式图片。"""
    paths, state = locate_run(args.run_id, args.project)
    ensure_active_run(state, "select-image-anchor")
    packet = read_json(paths["image_tasks"])
    if packet.get("mode") != "bootstrap":
        raise RuntimeError("当前 run 不处于首图锚点选择阶段")
    task = next((item for item in packet.get("tasks", [])
                 if item.get("key") == args.key), None)
    if not task or args.key != packet.get("bootstrap_key"):
        raise ValueError("只能选择当前 bootstrap 图片作为视觉锚点")
    path = _task_image_path(paths, task)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"首图候选不存在：{path}")
    try:
        with Image.open(path) as image:
            if abs(image.width / image.height - 16 / 9) > 0.02:
                raise RuntimeError("首图候选比例不是 16:9")
    except OSError as exc:
        raise RuntimeError(f"首图候选无法读取：{exc}") from exc
    state["image_anchor"] = {"key": args.key, "path": os.path.realpath(path),
                             "sha256": _sha256(path), "selected_at":
                             datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                             "mode": "bootstrap_candidate"}
    # bootstrap 的单图清单不能与确认锚点后的全量串行清单混用。
    state.pop("image_generation", None)
    transition(state, "images", "pending",
               f"已选择首图锚点 {args.key}；请重新运行 images 生成剩余图片",
               paths["image_tasks"])
    save_state(paths, state)
    print(json.dumps(state["image_anchor"], ensure_ascii=False, indent=2))


def _valid_manual_image_exception(paths):
    """仅在任务包和每张候选图未变时，人工例外才继续有效。"""
    if not os.path.exists(paths["image-review"]):
        return None
    report = read_json(paths["image-review"])
    approval = report.get("manual_exception")
    if report.get("verdict") != "pass" or not isinstance(approval, dict):
        return None
    if report.get("source_sha256") != _sha256(paths["image_tasks"]):
        return None
    image_hashes = report.get("image_sha256") or {}
    if not image_hashes:
        return None
    for key, expected in image_hashes.items():
        path = os.path.join(paths["images"], key + ".png")
        if not os.path.isfile(path) or _sha256(path) != expected:
            return None
    return report


def _verify_images(paths, project, state=None):
    story = read_json(formal_paths(project)["storyboard"])
    chars_path = os.path.join(ROOT, "assets", "characters.json")
    characters = read_json(chars_path) if os.path.exists(chars_path) else {}
    anchor = _run_style_anchor(state or {}, project)
    # 首图已确认后，完整包不再是 bootstrap；否则重建会把已冻结的完整
    # 任务错误标成 bootstrap 并改变 style_anchor 的语义。
    bootstrap_key = None if anchor else _bootstrap_key(
        story, project, characters, paths["images"])
    tasks = build_image_tasks(story, project_meta(project), characters,
                              paths["images"], anchor,
                              bootstrap_anchor_key=bootstrap_key)
    problems = []
    generation = (state or {}).get("image_generation")
    image_config = (state or {}).get("providers", {}).get("image", {})
    interactive = (image_config.get("name") in IMAGE_PROVIDERS and
                   make_image(image_config, ROOT).mode == "interactive")
    if interactive:
        provider_name = image_config["name"]
        if not isinstance(generation, dict):
            problems.append(f"缺少 {provider_name} 串行生成状态")
        elif generation.get("manifest_sha256") != _sha256(paths["image_tasks"]):
            problems.append(f"{provider_name} 串行任务清单哈希不一致")
        elif generation.get("active_key"):
            problems.append(
                f"{provider_name} 仍有未确认落盘的当前任务："
                + generation["active_key"])
        elif set(generation.get("completed_keys", [])) != {task["key"] for task in tasks}:
            problems.append(f"{provider_name} 串行队列尚未全部完成")
    exception = _valid_manual_image_exception(paths)
    if not anchor and not exception:
        problems.append("缺少项目视觉锚点图片，禁止图片审核和提升")
    packet = read_json(paths["image_tasks"]) if os.path.exists(
        paths["image_tasks"]) else {"tasks": tasks}
    packet_tasks = packet.get("tasks") if isinstance(packet, dict) else None
    if not isinstance(packet_tasks, list):
        return ["图片任务包无效：tasks 必须是数组"]
    packet_problems = _image_task_packet_problems(tasks, packet_tasks)
    if exception:
        # 例外只能豁免历史首批图与后来锚点配置之间的来源差异；提示词、尺寸、
        # 文件完整性和重复性检查仍保持强制。
        packet_problems = [item for item in packet_problems
                           if not item.startswith("图片任务被改写：")]
    problems.extend(packet_problems)
    task_by_key = {task.get("key"): task for task in packet_tasks
                   if isinstance(task, dict)}
    fingerprints = []
    for task in tasks:
        packet_task = task_by_key.get(task["key"])
        if not packet_task:
            continue
        problems.extend(validate_image_task_prompt(packet_task))
        path = task["output_path"]
        if not os.path.exists(path):
            problems.append(f"缺少图片：{task['key']}")
            continue
        try:
            with Image.open(path) as image:
                width, height = image.size
                fingerprint = _image_fingerprint(image)
            if abs(width / height - 16 / 9) > 0.02:
                problems.append(f"图片比例不是 16:9：{task['key']} {width}x{height}")
            else:
                fingerprints.append((task["key"], fingerprint))
        except Exception as exc:
            problems.append(f"图片损坏：{task['key']} {exc}")
    problems.extend(_duplicate_image_problems(fingerprints))
    return problems


def _image_review(paths, project, state=None):
    """Deterministic image review contract; provider-neutral and hash-bound."""
    packet = read_json(paths["image_tasks"])
    anchor = _run_style_anchor(state or {}, project)
    if not anchor:
        report = {"version": 1, "source_sha256": _sha256(paths["image_tasks"]),
                  "reviewer_required": True, "verdict": "fail",
                  "contract": {"writer": "visual_reviewer", "required_fields": [
                      "style_verdict", "character_verdict", "semantic_verdict",
                      "safety_verdict"]}, "issues": ["缺少项目视觉锚点图片"]}
        write_json(paths["image-review"], report)
        return report
    tasks = packet.get("tasks", [])
    beats = []
    failures = []
    for task in tasks:
        path = os.path.join(paths["images"], task["key"] + ".png")
        issues = []
        anchor = task.get("style_anchor") or task.get("rule_manifest", {}).get("style_anchor")
        if not anchor or not anchor.get("sha256"):
            issues.append("缺少 style anchor")
        if not os.path.exists(path):
            issues.append("候选图片不存在")
        else:
            try:
                with Image.open(path) as image:
                    if abs(image.width / image.height - 16 / 9) > 0.02:
                        issues.append("画面比例不符合 16:9")
            except Exception as exc:
                issues.append(f"图片无法读取：{exc}")
        verdict = "fail" if issues else "pass"
        if issues:
            failures.extend(f"{task.get('key')}: {x}" for x in issues)
        beats.append({"key": task.get("key"), "verdict": verdict,
                      "issues": issues, "suggestion": "重新生成并保持 Q 版2D 风格锚点" if issues else ""})
    report = {"version": 1, "source_sha256": _sha256(paths["image_tasks"]),
              "style_anchor": anchor, "reviewer_required": True,
              "contract": {"writer": "visual_reviewer", "required_fields": [
                  "style_verdict", "character_verdict", "semantic_verdict",
                  "safety_verdict"]},
              "image_sha256": {t["key"]: _sha256(os.path.join(paths["images"], t["key"] + ".png"))
                               for t in tasks if os.path.exists(os.path.join(paths["images"], t["key"] + ".png"))},
              "beats": beats, "verdict": "fail" if failures else "pending_visual_review",
              "issues": failures}
    write_json(paths["image-review"], report)
    return report


def cmd_image_review_exception(args):
    """记录用户已完成的人工图片审核，且将审批严格绑定到候选文件。"""
    paths, state = locate_run(args.run_id, args.project)
    ensure_active_run(state, "image-review-exception")
    if not args.reason or not args.reason.strip():
        raise ValueError("人工审核例外必须说明 --reason")
    if not os.path.exists(paths["image_tasks"]):
        raise RuntimeError("缺少 image_tasks.json，无法建立可追溯例外")
    packet = read_json(paths["image_tasks"])
    tasks = packet.get("tasks") if isinstance(packet, dict) else None
    if not isinstance(tasks, list) or not tasks:
        raise RuntimeError("图片任务包无效，无法建立可追溯例外")
    hashes = {}
    beats = []
    for task in tasks:
        key = task.get("key")
        if not key:
            raise RuntimeError("图片任务缺少 key")
        path = _task_image_path(paths, task)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"候选图片不存在：{path}")
        try:
            with Image.open(path) as image:
                if abs(image.width / image.height - 16 / 9) > 0.02:
                    raise RuntimeError(f"候选图片比例不是 16:9：{key}")
        except OSError as exc:
            raise RuntimeError(f"候选图片无法读取：{key}: {exc}") from exc
        hashes[key] = _sha256(path)
        beats.append({"key": key, "verdict": "pass", "issues": [],
                      "style_verdict": "manual_pass",
                      "character_verdict": "manual_pass",
                      "semantic_verdict": "manual_pass",
                      "safety_verdict": "manual_pass"})
    report = {
        "version": 2,
        "source_sha256": _sha256(paths["image_tasks"]),
        "image_sha256": hashes,
        "reviewer_required": True,
        "verdict": "pass",
        "contract": {"writer": "manual_reviewer", "required_fields": [
            "style_verdict", "character_verdict", "semantic_verdict",
            "safety_verdict"]},
        "manual_exception": {
            "reason": args.reason.strip(),
            "approved_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "waived_checks": ["project_visual_anchor_missing_at_generation",
                              "image_task_anchor_provenance"],
            "scope": "仅豁免锚点生成时序；不豁免任务包哈希、图片哈希、比例、可读性或重复性检查",
        },
        "beats": beats,
        "issues": [],
    }
    write_json(paths["image-review"], report)
    transition(state, "image-review", "generated", "已记录人工审核例外", paths["image-review"])
    save_state(paths, state)
    print(json.dumps(report["manual_exception"], ensure_ascii=False, indent=2))


def _image_task_packet_problems(expected_tasks, packet_tasks):
    """候选图片必须使用正式分镜重新构建出的原始任务，不接受人工改写。"""
    expected_keys = [task["key"] for task in expected_tasks]
    actual_keys = [task.get("key") for task in packet_tasks
                   if isinstance(task, dict)]
    if actual_keys != expected_keys:
        return ["图片任务包与正式分镜不一致，禁止使用未溯源任务"]
    actual_by_key = {task["key"] for task in packet_tasks if isinstance(task, dict)}
    problems = []
    for expected, actual in zip(expected_tasks, packet_tasks):
        # V5 新增了结构化 text_policy；已冻结的历史任务包保持只读，
        # 读取时从 text_mode 推导即可，不能为了升级重写 009 的任务包。
        comparable_expected = json.loads(json.dumps(expected))
        comparable_actual = json.loads(json.dumps(actual))
        actual_manifest = comparable_actual.get("rule_manifest", {})
        if (isinstance(actual_manifest, dict) and
                "text_policy" not in actual_manifest):
            expected_manifest = comparable_expected.get("rule_manifest", {})
            if isinstance(expected_manifest, dict):
                expected_manifest.pop("text_policy", None)
        if expected["key"] not in actual_by_key or comparable_actual != comparable_expected:
            problems.append(
                f"图片任务被改写：{expected['key']} 必须使用由正式分镜生成的原始规则")
    return problems


def _image_fingerprint(image):
    """轻量感知指纹：差分哈希与平均 RGB 同时避免单色误报。"""
    rgb = image.convert("RGB")
    means = tuple(round(value, 1) for value in ImageStat.Stat(rgb).mean)
    gray = rgb.convert("L").resize((17, 16), Image.Resampling.LANCZOS)
    pixels = list(gray.get_flattened_data())
    bits = 0
    for y in range(16):
        row = pixels[y * 17:(y + 1) * 17]
        for x in range(16):
            bits = (bits << 1) | int(row[x] > row[x + 1])
    return bits, means


def _duplicate_image_problems(fingerprints, max_hamming=8, max_mean_delta=18):
    """阻断肉眼近似的候选，阈值保守以免不同场景误伤。"""
    problems = []
    for index, (key, (bits, means)) in enumerate(fingerprints):
        for other_key, (other_bits, other_means) in fingerprints[:index]:
            hamming = (bits ^ other_bits).bit_count()
            mean_delta = sum(abs(a - b) for a, b in zip(means, other_means)) / 3
            if hamming <= max_hamming and mean_delta <= max_mean_delta:
                problems.append(
                    f"候选图片高相似：{other_key} / {key} "
                    f"(感知差异 {hamming}, 色彩差异 {mean_delta:.1f})")
    return problems


def cmd_verify(args):
    paths, state = locate_run(args.run_id, args.project)
    ensure_active_run(state, "verify")
    stage = args.stage
    if state["stages"][stage]["status"] == "promoted":
        raise RuntimeError(f"{stage} 已提升，无需重复校验")
    if state["stages"][stage]["status"] not in {
            "awaiting_external", "generated", "failed"}:
        raise RuntimeError(f"{stage} 尚未生成，不能校验")
    project = paths["project"]
    if stage == "topic":
        problems = validate_topic(read_json(paths[stage]), require_selection=True)
    elif stage == "copy":
        problems = validate_copy(read_json(paths[stage]), state.get("content_template"))
    elif stage == "script":
        with open(paths[stage], encoding="utf-8") as f:
            problems, _, _ = validate_script(f.read(), content_template=state.get("content_template"))
    elif stage == "storyboard":
        with open(formal_paths(project)["script"], encoding="utf-8") as f:
            script_problems, _, blocks = validate_script(f.read(), content_template=state.get("content_template"))
        chars_path = os.path.join(ROOT, "assets", "characters.json")
        characters = read_json(chars_path) if os.path.exists(chars_path) else {}
        raw_characters = characters.get("characters", characters)
        known_ids = ([x["id"] for x in raw_characters]
                     if isinstance(raw_characters, list) else raw_characters.keys())
        problems = list(script_problems)
        problems.extend(validate_storyboard(read_json(paths[stage]), blocks, known_ids,
                                            project_meta=project_meta(project)))
    elif stage == "storyboard-review":
        report = read_json(paths[stage])
        story_path = paths["storyboard"]
        if report.get("source_sha256") != _sha256(story_path):
            problems = ["storyboard-review 源分镜已变化，审核结果失效"]
        elif report.get("verdict") != "pass":
            problems = ["storyboard-review 未通过"] + [x for beat in report.get("beats", []) for x in beat.get("issues", [])]
        else:
            problems = []
    elif stage == "image-review":
        report = read_json(paths[stage])
        if report.get("source_sha256") != _sha256(paths["image_tasks"]):
            problems = ["image-review 图片任务源已变化，审核结果失效"]
        elif report.get("verdict") != "pass":
            problems = ["image-review 尚未由视觉审核者写入 pass 结果"]
        else:
            current = {}
            for key, path in ((k, os.path.join(paths["images"], k + ".png"))
                              for k in report.get("image_sha256", {})):
                if not os.path.exists(path) or _sha256(path) != report["image_sha256"][key]:
                    problems = [f"image-review 图片源已变化，审核结果失效：{key}"]
                    break
            else:
                problems = []
                required = set(report.get("contract", {}).get("required_fields", []))
                for beat in report.get("beats", []):
                    if not required.issubset(beat):
                        problems.append(f"{beat.get('key')}: 视觉审核契约字段不完整")
    elif stage == "images":
        problems = _verify_images(paths, project, state)
    else:
        raise ValueError("只有需人工确认的阶段支持 verify")
    if problems:
        transition(state, stage, "failed", "；".join(problems[:20]))
        save_state(paths, state)
        for problem in problems:
            print("-", problem)
        raise RuntimeError(f"{stage} 校验失败（{len(problems)} 项）")
    artifact = paths[stage]
    transition(state, stage, "verified", "校验通过", artifact)
    save_state(paths, state)
    print(f"{stage} 校验通过：{artifact}")


def backup_and_copy(source, target, run_id, replace=False):
    if os.path.exists(target):
        if not replace:
            raise FileExistsError(f"正式资产已存在；明确替换时使用 --replace：{target}")
        shutil.copy2(target, target + ".bak." + run_id)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.copy2(source, target)


def unlock(state):
    for stage, deps in DEPENDENCIES.items():
        if state["stages"][stage]["status"] == "blocked" and \
                all(state["stages"][dep]["status"] == "promoted" for dep in deps):
            if stage == "copy" and not state.get("content_template"):
                state["stages"][stage]["note"] = (
                    "等待 Sol 根据选题推荐内容模板并由用户明确选择")
                continue
            state["stages"][stage]["status"] = "pending"


def cmd_promote(args):
    paths, state = locate_run(args.run_id, args.project)
    ensure_active_run(state, "promote")
    stage = args.stage
    if state["stages"][stage]["status"] != "verified":
        raise RuntimeError(f"{stage} 尚未 verified，禁止提升")
    project = paths["project"]
    if stage == "images" and state["stages"]["image-review"]["status"] != "promoted":
        raise RuntimeError("images 必须在 image-review 通过后提升")
    if stage == "storyboard-review":
        legacy = state.get("legacy_storyboard_review")
        if not isinstance(legacy, dict):
            raise RuntimeError("storyboard-review 通过后，请由用户确认并提升 storyboard")
        formal_storyboard = formal_paths(project)["storyboard"]
        report = read_json(paths[stage])
        source_sha256 = legacy.get("source_sha256")
        if (report.get("verdict") != "pass" or
                report.get("source_sha256") != source_sha256 or
                source_sha256 != _sha256(paths["storyboard"]) or
                source_sha256 != _sha256(formal_storyboard)):
            raise RuntimeError("历史 storyboard-review 与候选或正式分镜哈希不一致")
        transition(state, stage, "promoted", "历史分镜审核补录通过", paths[stage])
        state.pop("legacy_storyboard_review", None)
        unlock(state); save_state(paths, state); print(f"{stage} 已提升"); return
    if stage == "image-review":
        report = read_json(paths[stage])
        if report.get("source_sha256") != _sha256(paths["image_tasks"]):
            raise RuntimeError("image-review 源任务已变化，禁止提升")
        if report.get("verdict") != "pass":
            raise RuntimeError("image-review 未通过，禁止提升")
        note = ("人工审核例外已确认并提升" if report.get("manual_exception")
                else "自动图片质量门禁通过")
        transition(state, stage, "promoted", note, paths[stage])
        unlock(state); save_state(paths, state); print(f"{stage} 已提升"); return
    formal = formal_paths(project)
    if stage == "topic":
        candidates = read_json(paths["topic"])
        topic = selected_topic(candidates)
        if not topic:
            raise RuntimeError("topic 未选择")
        canonical = dict(topic)
        canonical["source_candidates"] = [x["id"] for x in candidates["candidates"]]
        target = os.path.join(
            PJ.PROJECTS_DIR,
            f"{state['project_id']}_{safe_project_suffix(topic['book_title'])}")
        if os.path.abspath(project) != os.path.abspath(target) and \
                os.path.exists(target):
            raise FileExistsError(f"目标项目目录已存在：{target}")
        if os.path.exists(formal["topic"]):
            if not args.replace:
                raise FileExistsError(
                    "正式 topic 已存在；明确替换时使用 --replace")
            shutil.copy2(formal["topic"],
                         formal["topic"] + ".bak." + args.run_id)
        write_json(formal["topic"], canonical)
        meta = project_meta(project)
        meta.update({"title": topic["book_title"], "author": topic["author"]})
        write_json(os.path.join(project, "project.json"), meta)
        old_project = project
        if os.path.abspath(old_project) != os.path.abspath(target):
            os.rename(old_project, target)
            project = target
            PJ._CACHE.clear()
            paths = state_paths(project, args.run_id)
        if not state.get("content_template"):
            state["template_selection"] = {
                "status": "awaiting_user",
                "selected_id": None,
                "source": None,
            }
    elif stage in ("copy", "script"):
        backup_and_copy(paths[stage], formal[stage], args.run_id, args.replace)
    elif stage == "storyboard":
        review = state["stages"]["storyboard-review"]
        if review["status"] != "verified":
            raise RuntimeError("storyboard 必须先通过 storyboard-review")
        if not os.path.exists(paths["storyboard-review"]):
            raise RuntimeError("缺少 storyboard-review 审核记录")
        report = read_json(paths["storyboard-review"])
        if report.get("verdict") != "pass":
            raise RuntimeError("storyboard-review 未通过，禁止提升 storyboard")
        if report.get("source_sha256") != _sha256(paths["storyboard"]):
            raise RuntimeError("storyboard 候选已变化，审核结果失效")
        backup_and_copy(paths[stage], formal[stage], args.run_id, args.replace)
        if _sha256(formal[stage]) != report["source_sha256"]:
            raise RuntimeError("正式 storyboard 写入后哈希校验失败")
        transition(state, "storyboard-review", "promoted",
                   "分镜质量门禁通过，随 storyboard 人工确认锁定",
                   paths["storyboard-review"])
    elif stage == "images":
        os.makedirs(formal["images"], exist_ok=True)
        tasks = read_json(paths["image_tasks"])["tasks"]
        sources_targets = []
        for task in tasks:
            source = os.path.join(paths["images"], task["key"] + ".png")
            target = os.path.join(formal["images"], task["key"] + ".png")
            if not os.path.exists(source):
                raise FileNotFoundError(f"缺少候选图片：{source}")
            sources_targets.append((source, target))
        existing = [target for _, target in sources_targets
                    if os.path.exists(target)]
        if existing and not args.replace:
            raise FileExistsError(
                f"{len(existing)} 张正式图片已存在；明确替换时使用 --replace")
        for source, target in sources_targets:
            backup_and_copy(source, target, args.run_id, args.replace)
        anchor_key = state.get("image_anchor", {}).get("key") or tasks[0]["key"]
        anchor_path = os.path.join(formal["images"], anchor_key + ".png")
        if os.path.isfile(anchor_path):
            meta = project_meta(project)
            visual = dict(meta.get("visual_style") or {})
            visual["style_anchor"] = {
                "path": os.path.realpath(anchor_path),
                "purpose": "已提升的项目视觉锚点",
            }
            meta["visual_style"] = visual
            write_json(os.path.join(project, "project.json"), meta)
    else:
        raise ValueError(stage)
    transition(state, stage, "promoted", "已人工确认并提升")
    unlock(state)
    save_state(paths, state)
    if stage == "topic" and not state.get("content_template"):
        print(json.dumps({
            "stage": "topic",
            "status": "promoted",
            "next_action": "运行 template-options，由 Sol 推荐并等待用户选择",
            "copy_status": state["stages"]["copy"]["status"],
        }, ensure_ascii=False, indent=2))
    else:
        print(f"{stage} 已提升")


def _run_voice(paths, state):
    set_project(state["project_id"])
    import build_long
    build_long.RUN_AZURE_VOICE = state["providers"]["speech"]["voice"]
    blocks = build_long.parse_script()
    for i, block in enumerate(blocks):
        block["_source_idx"] = i
    try:
        build_long.make_audio(blocks)
    except Exception as exc:
        transition(state, "voice", "failed", str(exc))
        save_state(paths, state)
        raise
    manifest = {"voice": state["providers"]["speech"]["voice"],
                "files": [build_long.voice_stem(i, b.get("voice") or "") + ".wav"
                          for i, b in enumerate(blocks) if b.get("voice")]}
    manifest_path = os.path.join(paths["run_dir"], "voice_manifest.json")
    write_json(manifest_path, manifest)
    transition(state, "voice", "promoted", "Azure 配音完成", manifest_path)
    unlock(state)
    save_state(paths, state)
    print(f"Azure 配音完成：{manifest_path}")


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_render(paths, state, args):
    pid = state["project_id"]
    cmd = [sys.executable, os.path.join(ROOT, "pipeline", "build_long.py"),
           "--project", pid, "--workflow-run", state["run_id"]]
    review_id = getattr(args, "review_id", None)
    revision = getattr(args, "revision", None)
    blocks = getattr(args, "blocks", None)
    clip_durations = getattr(args, "clip_durations", None)
    phase_images_dir = getattr(args, "phase_images_dir", None)
    image_overrides_dir = getattr(args, "image_overrides_dir", None)
    reuse_segments_dir = getattr(args, "reuse_segments_dir", None)
    rerender_blocks = getattr(args, "rerender_blocks", None)
    if phase_images_dir:
        phase_images_dir = os.path.realpath(phase_images_dir)
        project_root = os.path.realpath(paths["project"])
        if os.path.commonpath((project_root, phase_images_dir)) != project_root:
            raise ValueError("阶段候选图目录必须位于当前项目内")
        if not (review_id or revision):
            raise ValueError("阶段候选图只允许用于 review/revision")
        cmd += ["--phase-images-dir", phase_images_dir]
    if image_overrides_dir:
        cmd += ["--image-overrides-dir", os.path.realpath(image_overrides_dir)]
    if reuse_segments_dir:
        cmd += ["--reuse-segments-dir", os.path.realpath(reuse_segments_dir)]
    if rerender_blocks:
        cmd += ["--rerender-blocks", ",".join(str(x) for x in rerender_blocks)]
    if review_id:
        cmd += ["--review-id", review_id,
                "--blocks", ",".join(str(x) for x in blocks)]
        if clip_durations:
            if len(clip_durations) != len(blocks):
                raise ValueError("--clip-durations 必须与 --blocks 等长")
            cmd += ["--clip-durations",
                    ",".join(str(x) for x in clip_durations)]
        output = os.path.join(paths["project"], "output", "reviews",
                              review_id, "review.mp4")
    elif revision:
        cmd += ["--revision", revision]
        output = os.path.join(paths["project"], "output",
                              f"long_{pid}_{revision}.mp4")
    else:
        output = os.path.join(paths["project"], "output", f"long_{pid}.mp4")
    # 外层终端在 build_long 已完成后被中断时，revision 成片可能已存在而
    # state 尚未写回。只要 ffprobe 能读取该隔离版本，即恢复状态，不重复渲染。
    reusable_revision = False
    if revision and os.path.exists(output):
        try:
            subprocess.check_output([
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "csv=p=0", output
            ], text=True)
            reusable_revision = True
        except subprocess.CalledProcessError:
            pass
    try:
        if reusable_revision:
            print(f"复用已完成的 revision 成片：{output}")
        else:
            subprocess.run(cmd, check=True)
        if not os.path.exists(output):
            raise FileNotFoundError(f"渲染命令未生成成片：{output}")
    except Exception as exc:
        if not (review_id or revision):
            transition(state, "render", "failed", str(exc))
            save_state(paths, state)
        raise
    if review_id:
        formal = formal_paths(paths["project"])
        manifest = {
            "review_id": review_id,
            "profile": "immersive_v2",
            "video": output,
            "blocks": blocks,
            "clip_durations": clip_durations,
            "phase_images_dir": phase_images_dir,
            "phase_image_sha256": {
                f"phase_{number:02d}.png": _sha256(os.path.join(
                    phase_images_dir, f"phase_{number:02d}.png"))
                for number in range(1, 6)
            } if phase_images_dir else {},
            "created_at": datetime.datetime.now().isoformat(),
            "sources": {
                "script_sha256": _sha256(formal["script"]),
                "storyboard_sha256": _sha256(formal["storyboard"]),
            },
        }
        manifest_path = os.path.join(paths["project"], "output", "reviews",
                                     review_id, "manifest.json")
        write_json(manifest_path, manifest)
        print(f"review 渲染完成：{output}")
        return
    if revision:
        previous = state["stages"]["render"].get("artifact")
        previous_qa = state["stages"]["qa"].get("artifact")
        state.setdefault("render_history", []).append({
            "artifact": previous,
            "qa_artifact": previous_qa,
            "archived_at": datetime.datetime.now().isoformat(),
        })
    transition(state, "render", "promoted",
               f"渲染完成{f'（{revision}）' if revision else ''}", output)
    state["stages"]["render"]["revision"] = revision
    if revision:
        state["stages"]["qa"] = {
            "status": "pending", "note": "新 render revision 待 QA",
            "artifact": None,
        }
    unlock(state)
    save_state(paths, state)
    print(f"渲染完成：{output}")


def _run_qa(paths, state):
    revision = state["stages"]["render"].get("revision")
    qa_path = (os.path.join(paths["run_dir"], f"qa_{revision}.json")
               if revision else paths["qa"])
    try:
        video = state["stages"]["render"].get("artifact")
        if not video or not os.path.exists(video):
            raise FileNotFoundError("未找到正式成片")
        probe_text = subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate",
            "-of", "json", video], text=True)
        probe = json.loads(probe_text)
        streams = probe.get("streams", [])
        video_streams = [x for x in streams if x.get("codec_type") == "video"]
        audio_streams = [x for x in streams if x.get("codec_type") == "audio"]
        if not video_streams or (video_streams[0].get("width"),
                                 video_streams[0].get("height")) != (1920, 1080):
            raise RuntimeError("成片必须包含 1920x1080 视频流")
        if not audio_streams:
            raise RuntimeError("成片缺少音频流")
        subprocess.run(["ffmpeg", "-v", "error", "-i", video,
                        "-f", "null", "-"], check=True)
        volume = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", video, "-af", "volumedetect",
             "-f", "null", "-"], text=True, capture_output=True, check=True)
        match = re.search(r"mean_volume:\s*(-?[\d.]+) dB", volume.stderr)
        mean_volume = float(match.group(1)) if match else None
        if mean_volume is None or not -16.5 <= mean_volume <= -11.5:
            raise RuntimeError(f"平均响度不在 -14 dB 目标容差内：{mean_volume}")
        loudness = subprocess.run(
            ["ffmpeg", "-hide_banner", "-i", video, "-af",
             "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
             "-f", "null", "-"], text=True, capture_output=True, check=True)
        matches = re.findall(r"\{\s*\"input_i\".*?\}",
                             loudness.stderr, flags=re.S)
        metrics = json.loads(matches[-1]) if matches else {}
        integrated_lufs = float(metrics.get("input_i", "nan"))
        true_peak_db = float(metrics.get("input_tp", "nan"))
        if not -15.5 <= integrated_lufs <= -12.5:
            raise RuntimeError(
                f"综合响度不在 -14 LUFS 目标容差内：{integrated_lufs}")
        if true_peak_db > -0.8:
            raise RuntimeError(f"True Peak 过高：{true_peak_db} dBTP")
        report = {
            "video": video, "ffprobe": probe, "decode": "ok",
            "mean_volume_db": mean_volume,
            "integrated_lufs": integrated_lufs,
            "true_peak_db": true_peak_db,
            "checked_at": datetime.datetime.now().isoformat(),
        }
        report["render_revision"] = revision
        write_json(qa_path, report)
    except Exception as exc:
        transition(state, "qa", "failed", str(exc))
        save_state(paths, state)
        raise
    transition(state, "qa", "promoted", "1080p、响度与完整解码通过", qa_path)
    save_state(paths, state)
    print(f"QA 通过：{qa_path}")


def cmd_status(args):
    paths, state = locate_run(args.run_id, args.project)
    relative = {key: os.path.relpath(value, ROOT) for key, value in paths.items()
                if isinstance(value, str)}
    print(json.dumps({"state": state, "paths": relative},
                     ensure_ascii=False, indent=2))


# 后置品牌/分发流程：使用独立目录和 state，不进入旧 content stages。
def _channel_dir(project, channel):
    return os.path.join(ROOT, "channels", channel)


def _brand_paths(project, channel, run_id):
    root = _channel_dir(project, channel)
    run = os.path.join(root, "workflow", "runs", run_id)
    return {"root": root, "request": os.path.join(root, "brand_request.md"),
            "brand": os.path.join(root, "brand.json"),
            "avatar": os.path.join(root, "avatar.svg"),
            "profile": os.path.join(root, "profile.md"),
            "candidate": os.path.join(root, "candidates", run_id, "brand_candidates.json"),
            "run": run, "state": os.path.join(run, "state.json"),
            "task": os.path.join(run, "tasks", "brand.json")}


DEFAULT_BRAND_REQUEST = """# 频道品牌需求

面向中文普通人，帮助观众理解财富机制，改善消费、职业与商业判断。
采用强利益钩子吸引点击，但不承诺收益。
分发平台：YouTube、B站、抖音、视频号。
头像方向：抽象符号头像，需适合圆形裁切和小尺寸显示。
禁止表达：稳赚、暴富、躺赚、必赚、保本、保证收益、无风险收益。
"""


def _publish_root(project):
    return os.path.join(project, "publishing")


def _publish_paths(project, video_run, revision, publish_id):
    root = _publish_root(project)
    legacy_root = os.path.join(root, "candidates", f"{video_run}_{revision}")
    candidate = os.path.join(legacy_root, "package.json")
    candidate_root = os.path.join(legacy_root, publish_id or "unknown")
    release = os.path.join(root, "releases", publish_id)
    approved = os.path.join(root, "approved", publish_id)
    run = os.path.join(project, "workflow", "runs", video_run, "publish", publish_id)
    return {"candidate": candidate, "release": os.path.join(release, "package.json"),
            "release_draft": os.path.join(release, "draft.json"),
            "upload": os.path.join(release, "upload.md"), "run": run,
            "state": os.path.join(run, "state.json"),
            "task": os.path.join(run, "task.json"),
            "copy_state": os.path.join(run, "copy", "state.json"),
            "cover_state": os.path.join(run, "cover", "state.json"),
            "copy_task": os.path.join(run, "copy", "task.json"),
            "cover_task": os.path.join(run, "cover", "task.json"),
            "cover_image_tasks": os.path.join(run, "cover", "image_tasks.json"),
            "candidate_root": candidate_root,
            "copy_candidate": os.path.join(candidate_root, "copy.json"),
            "cover_plan": os.path.join(candidate_root, "cover_plan.json"),
            "cover_candidate": os.path.join(candidate_root, "cover.json"),
            "covers_dir": os.path.join(candidate_root, "covers"),
            "approved_root": approved,
            "approved_copy": os.path.join(approved, "copy.json"),
            "approved_cover": os.path.join(approved, "cover.json"),
            "approved_cover_image": os.path.join(approved, "cover.png"),
            "release_root": release,
            "release_copy": os.path.join(release, "copy.json"),
            "release_cover": os.path.join(release, "cover.json"),
            "release_cover_image": os.path.join(release, "cover.png")}


def _formal_source_paths(project):
    return {x: os.path.join(project, "input", f"{x}.{'txt' if x == 'script' else 'json'}")
            for x in ("topic", "copy", "script", "storyboard")}


def _cover_style_references(project):
    """选择正式常规场景作为封面风格参考，不接受候选或 phase 素材。"""
    root = os.path.join(project, "assets", "scenes")
    files = []
    regular_name = re.compile(r"^\d{2}_\d+\.png$")
    if os.path.isdir(root):
        for name in os.listdir(root):
            if regular_name.match(name):
                files.append(os.path.join(root, name))
    files.sort(key=lambda path: tuple(int(part) for part in re.match(r"^(\d{2})_(\d+)\.png$", os.path.basename(path)).groups()))
    if not files:
        raise RuntimeError("publish-run 阻断：项目没有正式常规场景 PNG，无法建立封面风格参考")
    return [{"id": os.path.splitext(os.path.basename(path))[0],
             "path": os.path.relpath(path, project), "sha256": _sha256(path),
             "purpose": "正式成片风格与角色身份参考"} for path in files[:3]]


def _character_library_hash(project):
    path = os.path.join(ROOT, "assets", "characters.json")
    return _sha256(path) if os.path.isfile(path) else "missing"


def _visual_snapshot(project):
    config = project_meta(project).get("visual_style", {})
    raw = json.dumps(config, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {"config": config, "sha256": hashlib.sha256(raw).hexdigest()}


def _invalidate_publish_state(path):
    state = read_json(path["state"])
    if state.get("status") == "verified":
        state["status"] = "generated"
        state["verified_hash"] = None
        save_state({"state": path["state"]}, state)


def _load_video_run(project, run_id):
    path = state_paths(project, run_id)["state"]
    if not os.path.exists(path): raise FileNotFoundError(path)
    return read_json(path)


def cmd_brand_init(args):
    project = set_project(args.project); paths = _brand_paths(project, args.channel, args.run_id or now_run_id())
    if os.path.exists(paths["state"]): raise FileExistsError(paths["state"])
    os.makedirs(os.path.dirname(paths["request"]), exist_ok=True)
    if not os.path.exists(paths["request"]):
        with open(paths["request"], "w", encoding="utf-8") as f: f.write(DEFAULT_BRAND_REQUEST)
    meta = project_meta(project); providers = normalize_providers(meta.get("providers") or {})
    state = {"version": 1, "run_id": os.path.basename(paths["run"]), "channel": args.channel,
             "project_id": str(args.project), "providers": providers, "updated_at": "",
             "status": "pending", "artifact": paths["candidate"]}
    os.makedirs(os.path.dirname(paths["state"]), exist_ok=True); save_state({"state": paths["state"]}, state)
    print(json.dumps({"run_id": state["run_id"], "state": paths["state"]}, ensure_ascii=False))


def cmd_brand_run(args):
    project = set_project(args.project); run_id = args.run_id; paths = _brand_paths(project, args.channel, run_id)
    state = read_json(paths["state"])
    with open(paths["request"], encoding="utf-8") as handle:
        brand_request = handle.read()
    task = {"stage": "brand", "brand_request": brand_request,
        "candidate_path": paths["candidate"], "output_contract": {"candidates": 5, "visual_directions": 3,
        "profiles": list(PLATFORMS), "templates": ["{{channel_name}}"]}}
    write_json(paths["task"], task); provider = make_llm(state["providers"]["llm"], ROOT)
    result = provider.generate("brand", task, paths["candidate"])
    state["status"] = "awaiting_external" if result["mode"] == "interactive" else "generated"; save_state({"state": paths["state"]}, state)


def cmd_brand_select(args):
    project = set_project(args.project); p = _brand_paths(project, args.channel, args.run_id); data = read_json(p["candidate"])
    if args.name_id not in {x.get("id") for x in data.get("candidates", [])} or args.visual_id not in {x.get("id") for x in data.get("visual_directions", [])}: raise RuntimeError("品牌候选 ID 无效")
    data["selected_name_id"], data["selected_visual_id"] = args.name_id, args.visual_id; write_json(p["candidate"], data)
    state = read_json(p["state"])
    if state.get("status") not in ("awaiting_external", "generated", "failed"): raise RuntimeError("品牌当前状态不可选择")
    state["status"] = "generated"; save_state({"state": p["state"]}, state)
    print("品牌候选已选择")


def _valid_svg(path):
    if not os.path.exists(path): return False
    text = open(path, encoding="utf-8").read()
    return (re.search(r'<svg[^>]*viewBox=["\']0 0 1024 1024["\']', text) is not None and
            not re.search(r'<(text|script|image|foreignObject)\b|(?:https?://| on\w+=)', text, re.I))


def cmd_brand_verify(args):
    project = set_project(args.project); p = _brand_paths(project, args.channel, args.run_id); data = read_json(p["candidate"])
    errors = validate_brand(data)
    if not data.get("selected_name_id") or not data.get("selected_visual_id"): errors.append("必须先选择名称和视觉方向")
    state = read_json(p["state"])
    if state.get("status") != "generated": errors.append("品牌必须先生成并选择候选")
    if errors: raise RuntimeError("；".join(sorted(set(errors))))
    state["status"] = "verified"; save_state({"state": p["state"]}, state); print("brand 校验通过")


def cmd_brand_promote(args):
    project = set_project(args.project); p = _brand_paths(project, args.channel, args.run_id)
    if os.path.exists(p["brand"]): raise FileExistsError("正式 brand.json 已存在")
    state = read_json(p["state"])
    if state.get("status") != "verified": raise RuntimeError("品牌尚未 verified")
    data = read_json(p["candidate"]); errors = validate_brand(data)
    if errors or not data.get("selected_name_id") or not data.get("selected_visual_id"): raise RuntimeError("品牌尚未通过校验")
    name = next(x for x in data["candidates"] if x["id"] == data["selected_name_id"])
    visual = next(x for x in data["visual_directions"] if x["id"] == data["selected_visual_id"])
    svg_errors = validate_svg_text(visual.get("avatar_svg"));
    if svg_errors: raise RuntimeError("；".join(svg_errors))
    os.makedirs(os.path.dirname(p["avatar"]), exist_ok=True)
    with open(p["avatar"], "w", encoding="utf-8") as f: f.write(visual["avatar_svg"])
    profiles = {platform: {"description": data["profiles"][platform]["description_template"].replace("{{channel_name}}", name["name"])} for platform in PLATFORMS}
    write_json(p["brand"], {"channel_name": name["name"], "positioning": "理解财富机制", "audience": "中文普通人", "promise": "帮助理解消费、职业与商业判断", "tone": data["tone"], "cta": data["cta"], "platforms": profiles, "content_policy": {"no_profit_promises": True, "forbidden": ["稳赚", "暴富", "躺赚", "必赚", "保本", "保证收益", "无风险收益"]}, "visual": {k: v for k, v in visual.items() if k != "avatar_svg"}, "avatar": "avatar.svg", "source_run": state["run_id"], "providers": state["providers"], "promoted_at": datetime.datetime.now().isoformat()})
    with open(p["profile"], "w", encoding="utf-8") as f:
        f.write("# " + name["name"] + "\n\n" + "\n\n".join(f"## {p}\n{profiles[p]['description']}" for p in PLATFORMS) + "\n")
    state["status"] = "promoted"; save_state({"state": p["state"]}, state); print("brand 已提升")


def cmd_brand_status(args):
    p = _brand_paths(set_project(args.project), args.channel, args.run_id); print(json.dumps(read_json(p["state"]), ensure_ascii=False, indent=2))


def cmd_publish_init(args):
    project = set_project(args.project); video = _load_video_run(project, args.video_run_id)
    if video.get("stages", {}).get("qa", {}).get("status") != "promoted": raise RuntimeError("视频 run QA 尚未 promoted")
    bp = _brand_paths(project, args.channel, "unused")
    if not os.path.exists(bp["brand"]): raise RuntimeError("频道 brand 尚未 promoted")
    revision = video.get("stages", {}).get("render", {}).get("revision") or "original"; pid = args.publish_id or now_run_id().replace("run_", "pub_")
    p = _publish_paths(project, args.video_run_id, revision, pid); os.makedirs(p["run"], exist_ok=True)
    state = {"version": 3, "publish_id": pid, "video_run_id": args.video_run_id, "revision": revision, "status": "pending", "providers": video["providers"], "artifact": video["stages"]["render"]["artifact"], "updated_at": ""}
    write_json(p["state"], state); print(json.dumps({"publish_id": pid, "state": p["state"]}, ensure_ascii=False))


def cmd_publish_run(args):
    project = set_project(args.project); p = _publish_paths(project, args.video_run_id, args.revision, args.publish_id); state = read_json(p["state"]); formal = _formal_source_paths(project); brand = _brand_paths(project, args.channel, "unused")["brand"]
    source = {k: read_json(v) if k != "script" else open(v, encoding="utf-8").read() for k, v in formal.items()}
    style_refs = _cover_style_references(project)
    hashes = source_hashes({**formal, "brand": brand})
    task = {"stage": "publish", "source": {"topic": source["topic"], "copy": source["copy"], "script": source["script"], "storyboard": source["storyboard"], "brand": read_json(brand)}, "source_hashes": hashes, "cover_style_references": style_refs, "cover_visual_policy": "封面必须使用唯一风格锚点和角色库；生成两张16:9无关键文字底图，再以固定 reference_006_v1 版式合成文字。主题概念不得覆盖角色、画风、排版安全区或禁止项。", "candidate_path": p["candidate"], "output_contract": {"version": 3, "publish_id": "string", "channel_id": args.channel, "visual_snapshot": "task.visual_snapshot", "character_library_hash": "task.character_library_hash", "style_anchor": "task.style_anchor", "source": {"hashes": hashes}, "fact_core": {"summary": "string", "claim_refs": "copy.claims indexes", "script_evidence": "literal script substrings"}, "cover": {"aspect_ratio": "16:9", "candidates": 2, "selected_cover_id": "string", "candidate_required": {"layout_id": "reference_006_v1", "text": {"title_lines": 2, "subtitle": "string", "book_title": "project.title", "author": "project.author"}, "cover_task": {"reference_images": ["style_anchor.path"], "character_ids": ["assets/characters.json id"], "task_sha256": "string", "prompt_sha256": "string"}}}, "platforms": {"youtube": {"keywords": ["string"], "titles": [{"id": "string", "strategy": "pain_point|counter_intuitive|number_solution|seo|emotional_story", "title": "50-60 chars"}], "selected_title_id": "string", "description": {"lead": "<=100 chars", "highlights": "3-4 emoji items", "timestamps": "4-6 from 00:00", "cta": "string", "resources": "placeholders", "hashtags": "3-5"}}}}}
    task["visual_snapshot"] = _visual_snapshot(project)
    task["character_library_hash"] = _character_library_hash(project)
    task["style_anchor"] = style_refs[0]
    task["cover_style_references"] = [style_refs[0]]
    task["output_contract"]["version"] = 3
    write_json(p["task"], task); provider = make_llm(state["providers"]["llm"], ROOT); result = provider.generate("publish", task, p["candidate"]); state["status"] = "awaiting_external" if result["mode"] == "interactive" else "generated"; save_state({"state": p["state"]}, state)


def cmd_publish_verify(args):
    project = set_project(args.project); p = _publish_paths(project, args.video_run_id, args.revision, args.publish_id); data = read_json(p["candidate"]); formal = _formal_source_paths(project); brand = _brand_paths(project, args.channel, "unused")["brand"]; hashes = source_hashes({**formal, "brand": brand})
    with open(formal["script"], encoding="utf-8") as handle:
        script = handle.read()
    copy_data = read_json(formal["copy"]); task = read_json(p["task"]); errors = validate_package(data, hashes, script, copy_data, str(args.project), args.video_run_id, args.revision, brand_hash=hashes["brand"], cover_style_references=task.get("cover_style_references"), project_root=project)
    if errors: raise RuntimeError("；".join(errors))
    state = read_json(p["state"]); state["status"] = "verified"; state["verified_hash"] = _sha256(p["candidate"]); save_state({"state": p["state"]}, state); print("publish 校验通过")


def cmd_publish_select(args):
    """记录人工选择的 YouTube 标题与封面候选。"""
    project = set_project(args.project); p = _publish_paths(project, args.video_run_id, args.revision, args.publish_id)
    data = read_json(p["candidate"]); item = data.get("platforms", {}).get("youtube", {})
    title_ids = {x.get("id") for x in item.get("titles", []) if isinstance(x, dict)}
    cover_ids = {x.get("id") for x in data.get("cover", {}).get("candidates", []) if isinstance(x, dict)}
    if args.title_id not in title_ids or args.cover_id not in cover_ids:
        raise RuntimeError("标题或封面候选 ID 无效")
    state = read_json(p["state"])
    if state.get("status") not in ("generated", "awaiting_external", "failed", "verified"):
        raise RuntimeError("发布当前状态不可选择")
    item["selected_title_id"] = args.title_id; data["platforms"]["youtube"] = item
    data["cover"]["selected_cover_id"] = args.cover_id
    write_json(p["candidate"], data)
    _invalidate_publish_state(p)
    state = read_json(p["state"]); state["status"] = "generated"
    state["verified_hash"] = None
    save_state({"state": p["state"]}, state); print("发布候选已选择")


def cmd_publish_import_cover(args):
    """安全导入封面底图到本次发布候选目录。"""
    project = set_project(args.project); p = _publish_paths(project, args.video_run_id, args.revision, args.publish_id)
    data = read_json(p["candidate"])
    item = next((x for x in data.get("cover", {}).get("candidates", [])
                 if x.get("id") == args.cover_id), None)
    if item is None:
        raise RuntimeError("封面候选 ID 无效")
    if item.get("base_path") and not args.variant:
        raise RuntimeError("封面底图已导入，禁止重复导入")
    if args.variant and not re.fullmatch(r"[a-zA-Z0-9_-]+", args.variant):
        raise RuntimeError("封面 variant 只能包含字母、数字、下划线或短横线")
    with Image.open(args.input) as image:
        if abs(image.width / image.height - 16 / 9) > 0.02:
            raise RuntimeError("封面底图必须为16:9")
        if image.width < 640: raise RuntimeError("封面底图分辨率过低")
        outdir = os.path.join(os.path.dirname(p["candidate"]), "covers"); os.makedirs(outdir, exist_ok=True)
        suffix = f"_{args.variant}" if args.variant else ""
        dest = os.path.join(outdir, f"{args.cover_id}{suffix}_base.png")
        if os.path.exists(dest):
            raise RuntimeError("目标封面底图文件已存在，请使用新的 variant")
        image.convert("RGB").save(dest, "PNG")
    item["base_path"], item["base_sha256"] = os.path.relpath(dest, project), _sha256(dest)
    write_json(p["candidate"], data)
    _invalidate_publish_state(p)
    print(dest)


def cmd_publish_review_cover(args):
    """写入 hash 绑定的人工视觉审核报告；未通过不得验证或提升。"""
    project = set_project(args.project); p = _publish_paths(project, args.video_run_id, args.revision, args.publish_id)
    data = read_json(p["candidate"])
    item = next((x for x in data.get("cover", {}).get("candidates", []) if x.get("id") == args.cover_id), None)
    if not item or not item.get("sha256"):
        raise RuntimeError("封面必须先合成并生成 hash")
    passed = all(getattr(args, key) == "pass" for key in ("style", "character", "semantic", "layout", "thumbnail_legibility"))
    item["visual_review"] = {"status": "passed" if passed else "failed", "asset_sha256": item["sha256"],
                              **{key: getattr(args, key) == "pass" for key in ("style", "character", "semantic", "layout", "thumbnail_legibility")}}
    write_json(p["candidate"], data); _invalidate_publish_state(p)
    print("封面视觉审核通过" if passed else "封面视觉审核未通过")


def cmd_publish_compose_cover(args):
    """使用 Pillow 将封面文案按频道既定信息层级确定性合成。"""
    project = set_project(args.project); p = _publish_paths(project, args.video_run_id, args.revision, args.publish_id)
    data = read_json(p["candidate"])
    item = next((x for x in data.get("cover", {}).get("candidates", [])
                 if x.get("id") == args.cover_id), None)
    if item is None or not item.get("base_path"):
        raise RuntimeError("请先导入该候选封面的底图")
    if item.get("final_path") and not args.variant:
        raise RuntimeError("封面已合成，禁止重复合成")
    if args.variant and not re.fullmatch(r"[a-zA-Z0-9_-]+", args.variant):
        raise RuntimeError("封面 variant 只能包含字母、数字、下划线或短横线")
    base = os.path.join(project, item["base_path"])
    outdir = os.path.join(os.path.dirname(p["candidate"]), "covers"); os.makedirs(outdir, exist_ok=True)
    with Image.open(base) as image:
        image = image.convert("RGB").resize((1920, 1080), Image.Resampling.LANCZOS)
        draw = ImageDraw.Draw(image)
        font_path = os.path.join(ROOT, "assets", "fonts", "SourceHanSansCN-Heavy.otf")
        if not os.path.exists(font_path):
            font_path = "/System/Library/Fonts/PingFang.ttc"
        if not os.path.exists(font_path):
            raise RuntimeError("未找到可用的中文封面字体")
        text_spec = item.get("text", {})
        lines = text_spec.get("title_lines", [])
        if len(lines) != 2 or not all(lines):
            raise RuntimeError("封面标题必须严格为两行非空文字，以换行分隔")

        def cover_font(text, maximum, initial):
            size = initial
            while size > 56:
                font = ImageFont.truetype(font_path, size)
                if draw.textbbox((0, 0), text, font=font)[2] <= maximum:
                    return font
                size -= 2
            return ImageFont.truetype(font_path, size)

        # 与频道认可的 006 封面一致：左侧两行大钩子、解释句、分隔线和书籍信息。
        # 底图没有关键文字，保证这些中文信息由本地字体稳定、可复现地输出。
        primary = cover_font(lines[0], 900, 180)
        secondary = cover_font(lines[1], 900, 180)
        ink = (248, 246, 238)
        gold = (246, 183, 76)
        shadow = (5, 12, 24)
        for text, y, font, fill in ((lines[0], 112, primary, ink),
                                    (lines[1], 336, secondary, gold)):
            draw.text((88, y), text, fill=shadow, font=font, stroke_width=4,
                      stroke_fill=shadow)
            draw.text((80, y - 8), text, fill=fill, font=font)
        if text_spec.get("subtitle"):
            subtitle = cover_font(text_spec["subtitle"], 900, 46)
            draw.text((82, 674), text_spec["subtitle"], fill=ink, font=subtitle,
                      stroke_width=2, stroke_fill=shadow)
        bookline_text = f'《{text_spec.get("book_title", "")}》｜{text_spec.get("author", "")}'
        if text_spec.get("book_title") and text_spec.get("author"):
            bookline = cover_font(bookline_text, 900, 50)
            draw.line((96, 784, 900, 784), fill=gold, width=3)
            draw.ellipse((202, 775, 220, 793), fill=gold, outline=shadow, width=2)
            draw.text((82, 822), bookline_text, fill=gold, font=bookline,
                      stroke_width=2, stroke_fill=shadow)
        suffix = f"_{args.variant}" if args.variant else ""
        dest = os.path.join(outdir, f"{args.cover_id}{suffix}.png")
        if os.path.exists(dest):
            raise RuntimeError("目标封面文件已存在，请使用新的 variant")
        image.save(dest, "PNG")
    item["final_path"], item["sha256"] = os.path.relpath(dest, project), _sha256(dest)
    write_json(p["candidate"], data)
    _invalidate_publish_state(p)
    print(dest)


def cmd_publish_promote(args):
    project = set_project(args.project); p = _publish_paths(project, args.video_run_id, args.revision, args.publish_id); state = read_json(p["state"])
    if state.get("status") != "verified": raise RuntimeError("publish 尚未 verified")
    if state.get("verified_hash") != _sha256(p["candidate"]): raise RuntimeError("发布包已变化，必须重新校验")
    data = read_json(p["candidate"]); os.makedirs(os.path.dirname(p["release"]), exist_ok=True)
    if data.get("version") in (2, 3):
        selected_cover = next(x for x in data["cover"]["candidates"]
                              if x["id"] == data["cover"]["selected_cover_id"])
        shutil.copy2(os.path.join(project, selected_cover["final_path"]),
                     os.path.join(os.path.dirname(p["release"]), "cover.png"))
    write_json(p["release"], data)
    with open(p["upload"], "w", encoding="utf-8") as f:
        f.write("# 上传清单\n\n## 统一事实核心\n" + str(data.get("fact_core", {}).get("summary", "")) + "\n\n## 封面文案与视觉任务\n" + data.get("cover", {}).get("concept", "") + "\n")
        item = data.get('platforms', {}).get('youtube', {})
        if data.get("version") in (2, 3):
            title = next(x["title"] for x in item["titles"] if x["id"] == item["selected_title_id"])
            desc = item["description"]
            f.write(f"\n## YouTube\n{title}\n\n{desc['lead']}\n\n" +
                    "\n".join(desc["highlights"]) + "\n\n" +
                    "\n".join(f"{x['time']} {x['title']}" for x in desc["timestamps"]) +
                    f"\n\n{desc['cta']}\n{desc['resources']}\n" +
                    " ".join(desc["hashtags"]) + "\n")
        else:
            f.write(f"\n## YouTube\n{item.get('primary_title', '')}\n")
        f.write("\n## 上传前人工检查\n- 人工上传\n- 检查标题与封面\n- 检查封面与正式场景的风格/角色一致性\n")
    state["status"] = "promoted"; save_state({"state": p["state"]}, state); print("publish 已提升")


def cmd_publish_status(args):
    p = _publish_paths(set_project(args.project), args.video_run_id, args.revision, args.publish_id); print(json.dumps(read_json(p["state"]), ensure_ascii=False, indent=2))


# V4 发布流程：文案与封面独立推进，最终只汇总已提升且未过期的子产物。
def _stable_json_hash(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _publish_sources(project, channel):
    formal = _formal_source_paths(project)
    brand = _brand_paths(project, channel, "unused")["brand"]
    paths = {**formal, "brand": brand}
    if any(not os.path.isfile(path) for path in paths.values()):
        missing = [name for name, path in paths.items() if not os.path.isfile(path)]
        raise RuntimeError("发布正式输入缺失：" + "、".join(missing))
    values = {name: read_json(path) for name, path in paths.items()
              if name != "script"}
    with open(paths["script"], encoding="utf-8") as handle:
        values["script"] = handle.read()
    return paths, values, source_hashes(paths)


def _publish_v4_context(args):
    project = set_project(args.project)
    probe = _publish_paths(project, args.video_run_id,
                           getattr(args, "revision", "unused"), args.publish_id)
    if not os.path.isfile(probe["state"]):
        raise FileNotFoundError(probe["state"])
    parent = read_json(probe["state"])
    if parent.get("version") != 4:
        raise RuntimeError("历史 V1–V3 发布流程只读；请用 publish-init 创建新的 V4 publish ID")
    if parent.get("video_run_id") != args.video_run_id:
        raise RuntimeError("publish ID 与 video run 不匹配")
    paths = _publish_paths(project, args.video_run_id, parent["revision"],
                           args.publish_id)
    source_paths_value, source, hashes = _publish_sources(
        project, parent["channel_id"])
    if hashes != parent.get("source_hashes"):
        raise RuntimeError("正式发布输入 hash 已变化；请创建新的 V4 publish ID")
    return project, paths, parent, source_paths_value, source, hashes


def _save_publish_parent(paths, state):
    state["updated_at"] = datetime.datetime.now().isoformat()
    write_json(paths["state"], state)


def _save_publish_child(path, state):
    state["updated_at"] = datetime.datetime.now().isoformat()
    write_json(path, state)


def _sync_publish_release_draft(paths, parent):
    """将已提升的子产物分别汇入发布目录，保留最终包的独立门禁。"""
    if os.path.exists(paths["release"]):
        raise RuntimeError("V4 发布包已经汇总，禁止覆盖")
    copy_state = read_json(paths["copy_state"])
    cover_state = read_json(paths["cover_state"])
    parts = {}
    for name, state, files in (
        ("copy", copy_state, (("approved_copy", "release_copy", "promoted_hash"),)),
        ("cover", cover_state, (("approved_cover", "release_cover", "promoted_hash"),
                                ("approved_cover_image", "release_cover_image",
                                 "promoted_image_hash"))),
    ):
        if state.get("status") != "promoted":
            continue
        label = "发布文案" if name == "copy" else "封面"
        hashes = {}
        for source_key, target_key, hash_key in files:
            actual = _sha256(paths[source_key])
            if actual != state.get(hash_key):
                raise RuntimeError(f"已提升{label} hash 已变化，禁止汇入发布包")
            target = paths[target_key]
            if os.path.exists(target) and _sha256(target) != actual:
                raise RuntimeError(f"发布包内{label} hash 已变化，禁止覆盖")
            hashes[os.path.basename(target)] = actual
        for source_key, target_key, _ in files:
            if not os.path.exists(paths[target_key]):
                os.makedirs(paths["release_root"], exist_ok=True)
                shutil.copy2(paths[source_key], paths[target_key])
        parts[name] = hashes
    write_json(paths["release_draft"], {
        "version": 4, "publish_id": parent["publish_id"],
        "status": "ready_to_finalize" if len(parts) == 2 else "incomplete",
        "source_hashes": parent["source_hashes"], "artifacts": parts,
    })


def cmd_publish_init(args):
    project = set_project(args.project)
    video = _load_video_run(project, args.video_run_id)
    if video.get("stages", {}).get("qa", {}).get("status") != "promoted":
        raise RuntimeError("视频 run QA 尚未 promoted")
    brand = _brand_paths(project, args.channel, "unused")["brand"]
    if not os.path.isfile(brand):
        raise RuntimeError("频道 brand 尚未 promoted")
    revision = video.get("stages", {}).get("render", {}).get("revision") or "original"
    publish_id = args.publish_id or now_run_id().replace("run_", "pub_")
    paths = _publish_paths(project, args.video_run_id, revision, publish_id)
    if os.path.exists(paths["state"]):
        raise FileExistsError(paths["state"])
    _, _, hashes = _publish_sources(project, args.channel)
    parent = {
        "version": 4, "publish_id": publish_id,
        "project_id": str(args.project), "channel_id": args.channel,
        "video_run_id": args.video_run_id, "revision": revision,
        "status": "active", "providers": video["providers"],
        "video_artifact": video["stages"]["render"]["artifact"],
        "source_hashes": hashes, "children": {
            "copy": "pending", "cover": "awaiting_template"},
        "updated_at": "",
    }
    copy_state = {"version": 1, "publish_id": publish_id,
                  "status": "pending", "verified_hash": None,
                  "promoted_hash": None, "updated_at": ""}
    cover_state = {"version": 1, "publish_id": publish_id,
                   "status": "awaiting_template", "template_selection": None,
                   "template": None, "verified_plan_hash": None,
                   "verified_hash": None, "promoted_hash": None,
                   "generation": None,
                   "updated_at": ""}
    for path in (paths["state"], paths["copy_state"], paths["cover_state"]):
        os.makedirs(os.path.dirname(path), exist_ok=True)
    _save_publish_parent(paths, parent)
    _save_publish_child(paths["copy_state"], copy_state)
    _save_publish_child(paths["cover_state"], cover_state)
    print(json.dumps({"publish_id": publish_id, "state": paths["state"],
                      "copy_state": paths["copy_state"],
                      "cover_state": paths["cover_state"]},
                     ensure_ascii=False, indent=2))


def _copy_contract(parent, hashes):
    return {
        "version": 1, "publish_id": parent["publish_id"],
        "channel_id": parent["channel_id"],
        "source": {"project_id": parent["project_id"],
                   "video_run_id": parent["video_run_id"],
                   "revision": parent["revision"],
                   "video_artifact": parent["video_artifact"],
                   "hashes": hashes},
        "fact_core": {"summary": "string", "claim_refs": "copy.claims indexes",
                      "script_evidence": "literal script substrings"},
        "platforms": {"youtube": {
            "keywords": ["string"],
            "titles": [{"id": "string", "strategy":
                        "pain_point|counter_intuitive|number_solution|seo|emotional_story",
                        "title": "50-60 chars"}],
            "selected_title_id": None,
            "description": {"lead": "<=100 chars", "highlights": "3-4 items",
                            "timestamps": "4-6 increasing entries from 00:00",
                            "cta": "string", "resources": "string",
                            "hashtags": "3-5"}}},
    }


def cmd_publish_copy_run(args):
    project, paths, parent, _, source, hashes = _publish_v4_context(args)
    state = read_json(paths["copy_state"])
    if state.get("status") not in ("pending", "awaiting_external", "generated",
                                   "failed"):
        raise RuntimeError("发布文案已经选择、验证或提升，不能重新生成")
    image_route = _interactive_image_execution_route(
        parent["providers"]["image"])
    task = {"stage": "publish-copy", "source": source,
            "source_hashes": hashes, "candidate_path": paths["copy_candidate"],
            "output_contract": _copy_contract(parent, hashes),
            "execution_boundary": {
                "allowed_in_this_task": ["write_copy_candidate_json"],
                "must_stop_after_candidate": True,
                "forbidden": ["select_title", "verify", "promote", "finalize",
                              "plan_cover", "generate_image", "compose_cover"],
                "next_image_stage": image_route,
            },
            "instruction": ("只生成发布文案，不得输出任何封面、视觉或图片字段；"
                            "标题不得预选。写入 candidate_path 后必须立即停止，"
                            "不得继续封面规划、生图、审核、选择、提升或最终汇总。")}
    write_json(paths["copy_task"], task)
    provider = make_llm(parent["providers"]["llm"], ROOT)
    result = provider.generate("publish-copy", task, paths["copy_candidate"])
    state["status"] = "awaiting_external" if result["mode"] == "interactive" else "generated"
    _save_publish_child(paths["copy_state"], state)
    parent["children"]["copy"] = state["status"]
    _save_publish_parent(paths, parent)
    print(json.dumps({"task": paths["copy_task"],
                      "candidate": paths["copy_candidate"],
                      "state": state["status"]}, ensure_ascii=False, indent=2))


def cmd_publish_copy_select(args):
    _, paths, parent, _, source, hashes = _publish_v4_context(args)
    state = read_json(paths["copy_state"])
    if state.get("status") not in ("generated", "awaiting_external"):
        raise RuntimeError("发布文案当前状态不可选择标题")
    data = read_json(paths["copy_candidate"])
    errors = validate_publish_copy(data, hashes, source["script"], source["copy"],
                                   parent["project_id"], parent["video_run_id"],
                                   parent["revision"], require_selection=False)
    if errors:
        raise RuntimeError("；".join(errors))
    youtube = data["platforms"]["youtube"]
    if args.title_id not in {x["id"] for x in youtube["titles"]}:
        raise RuntimeError("标题候选 ID 无效")
    youtube["selected_title_id"] = args.title_id
    write_json(paths["copy_candidate"], data)
    state.update(status="selected", verified_hash=None)
    _save_publish_child(paths["copy_state"], state)
    parent["children"]["copy"] = "selected"
    _save_publish_parent(paths, parent)
    print("发布标题已人工选择")


def cmd_publish_copy_verify(args):
    _, paths, parent, _, source, hashes = _publish_v4_context(args)
    state = read_json(paths["copy_state"])
    if state.get("status") != "selected":
        raise RuntimeError("发布标题必须先由用户人工选择")
    data = read_json(paths["copy_candidate"])
    errors = validate_publish_copy(data, hashes, source["script"], source["copy"],
                                   parent["project_id"], parent["video_run_id"],
                                   parent["revision"], require_selection=True)
    if errors:
        raise RuntimeError("；".join(errors))
    state.update(status="verified", verified_hash=_sha256(paths["copy_candidate"]))
    _save_publish_child(paths["copy_state"], state)
    parent["children"]["copy"] = "verified"
    _save_publish_parent(paths, parent)
    print("发布文案校验通过")


def cmd_publish_copy_promote(args):
    _, paths, parent, _, _, _ = _publish_v4_context(args)
    state = read_json(paths["copy_state"])
    if state.get("status") != "verified" or state.get("verified_hash") != \
            _sha256(paths["copy_candidate"]):
        raise RuntimeError("发布文案未验证或验证 hash 已过期")
    if os.path.exists(paths["approved_copy"]):
        raise RuntimeError("已存在提升后的发布文案，禁止覆盖")
    os.makedirs(paths["approved_root"], exist_ok=True)
    shutil.copy2(paths["copy_candidate"], paths["approved_copy"])
    state.update(status="promoted", promoted_hash=_sha256(paths["approved_copy"]))
    _save_publish_child(paths["copy_state"], state)
    parent["children"]["copy"] = "promoted"
    _save_publish_parent(paths, parent)
    _sync_publish_release_draft(paths, parent)
    print("发布文案已独立提升并汇入发布目录")


def cmd_publish_copy_status(args):
    _, paths, _, _, _, _ = _publish_v4_context(args)
    print(json.dumps(read_json(paths["copy_state"]), ensure_ascii=False, indent=2))


def cmd_publish_cover_template_options(args):
    _, paths, _, _, source, _ = _publish_v4_context(args)
    state = read_json(paths["cover_state"])
    print(json.dumps({"topic": source["topic"],
                      "options": cover_template_catalog(),
                      "selection": state.get("template_selection"),
                      "requires_user_reply": True,
                      "next_command_locked": "publish-cover-select-template",
                      "instruction": ("Sol 只能推荐并展示选项，随后必须停止等待用户回复。"
                                      "用户笼统要求执行流程不等于选择模板；只有用户明确说出"
                                      "模板 ID 后，Agent 才能调用选择命令。")},
                     ensure_ascii=False, indent=2))


def cmd_publish_cover_select_template(args):
    _, paths, parent, _, _, hashes = _publish_v4_context(args)
    state = read_json(paths["cover_state"])
    if state.get("template_selection"):
        raise RuntimeError("封面模板已经锁定，不可变更；如需更换请创建新的 publish ID")
    if args.recommended not in COVER_TEMPLATE_IDS or args.template_id not in COVER_TEMPLATE_IDS:
        raise RuntimeError("未知封面模板")
    selection = {"recommended_template_id": args.recommended,
                 "recommendation_reason": args.reason.strip(),
                 "selected_template_id": args.template_id,
                 "topic_sha256": hashes["topic"],
                 "selected_at": datetime.datetime.now().isoformat()}
    if not selection["recommendation_reason"]:
        raise RuntimeError("必须记录推荐理由")
    state.update(status="template_selected", template_selection=selection,
                 template=cover_template_snapshot(args.template_id))
    _save_publish_child(paths["cover_state"], state)
    parent["children"]["cover"] = "template_selected"
    _save_publish_parent(paths, parent)
    print(json.dumps(selection, ensure_ascii=False, indent=2))


def _require_active_cover_template(state):
    errors = validate_cover_template_snapshot(state.get("template"))
    if errors:
        raise RuntimeError("封面模板已停用或快照无效：" + "；".join(errors))


def _verified_v3_cover_reuse_errors(project, parent, cover):
    """核对旧 V3 已验证封面，禁止把复用图片记作本次新生成。"""
    record = cover.get("reuse_provenance")
    required = {"kind", "source_publish_id", "source_package_path",
                "source_package_sha256", "source_state_path"}
    if not isinstance(record, dict) or set(record) != required or \
            record.get("kind") != "verified_v3":
        return ["旧封面复用来源记录无效"]
    source_id = record.get("source_publish_id")
    if not isinstance(source_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", source_id):
        return ["旧封面 publish ID 无效"]
    candidate_dir = os.path.join(
        "publishing", "candidates",
        f"{parent['video_run_id']}_{parent['revision']}")
    expected_package = os.path.join(candidate_dir, "package.json")
    expected_state = os.path.join(
        "workflow", "runs", parent["video_run_id"], "publish",
        source_id, "state.json")
    if record.get("source_package_path") != expected_package or \
            record.get("source_state_path") != expected_state:
        return ["旧封面来源路径与本次视频 run 不匹配"]
    package_path = os.path.join(project, expected_package)
    state_path = os.path.join(project, expected_state)
    if not os.path.isfile(package_path) or not os.path.isfile(state_path):
        return ["旧封面来源包或验证状态缺失"]
    package_hash = _sha256(package_path)
    if record.get("source_package_sha256") != package_hash:
        return ["旧封面来源包 hash 已变化"]
    legacy = read_json(package_path)
    legacy_state = read_json(state_path)
    source = legacy.get("source", {})
    errors = []
    if legacy.get("version") != 3 or legacy.get("publish_id") != source_id or \
            legacy_state.get("version") != 3 or \
            legacy_state.get("status") not in ("verified", "promoted") or \
            legacy_state.get("verified_hash") != package_hash:
        errors.append("旧 V3 发布包未通过哈希绑定的验证")
    if source.get("project_id") != parent["project_id"] or \
            source.get("video_run_id") != parent["video_run_id"] or \
            source.get("revision") != parent["revision"] or \
            source.get("video_artifact") != parent["video_artifact"] or \
            source.get("hashes") != parent["source_hashes"]:
        errors.append("旧封面与本次正式输入或视频版本不匹配")
    old_cover = legacy.get("cover", {})
    if old_cover.get("selected_cover_id") != cover.get("selected_cover_id") or \
            old_cover.get("candidates") != cover.get("candidates"):
        errors.append("旧封面候选或用户选中的图片与来源包不一致")
    candidates_root = os.path.realpath(os.path.join(project, candidate_dir))
    for candidate in cover.get("candidates", []):
        if not isinstance(candidate, dict) or \
                candidate.get("layout_id") != cover.get("template", {}).get("id"):
            errors.append("旧封面不是当前唯一正式模板")
            continue
        for key in ("base_path", "final_path"):
            full = os.path.realpath(os.path.join(project, candidate.get(key) or ""))
            if os.path.commonpath((candidates_root, full)) != candidates_root:
                errors.append("旧封面图片不在本视频的候选目录")
    return sorted(set(errors))


def cmd_publish_cover_reuse_verified(args):
    """将用户明确指定的已验证 V3 原图接入 V4 封面子状态。"""
    project, paths, parent, _, source, hashes = _publish_v4_context(args)
    state = read_json(paths["cover_state"])
    if state.get("status") != "awaiting_template" or \
            state.get("template_selection") or \
            os.path.exists(paths["cover_candidate"]) or \
            os.path.exists(paths["approved_cover"]):
        raise RuntimeError("本次封面已开始处理或已有正式资产，不能导入旧封面")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.source_publish_id):
        raise RuntimeError("旧封面 publish ID 无效")
    candidate_dir = os.path.join(
        "publishing", "candidates",
        f"{parent['video_run_id']}_{parent['revision']}")
    package_rel = os.path.join(candidate_dir, "package.json")
    package_path = os.path.join(project, package_rel)
    legacy = read_json(package_path)
    selected = next((item for item in legacy.get("cover", {}).get("candidates", [])
                     if item.get("id") == args.cover_id), None)
    if selected is None or legacy.get("cover", {}).get("selected_cover_id") != args.cover_id:
        raise RuntimeError("指定图片不是旧 V3 发布包中已选择的封面")
    if os.path.basename(selected.get("final_path", "")) != args.filename:
        raise RuntimeError("指定文件名与旧 V3 封面候选不一致")
    template = cover_template_snapshot(selected.get("layout_id"))
    selection = {
        "recommended_template_id": template["id"],
        "recommendation_reason": "沿用用户明确指定且已验证的 V3 正式封面",
        "selected_template_id": template["id"],
        "topic_sha256": hashes["topic"],
        "selected_at": datetime.datetime.now().isoformat(),
    }
    cover = {
        "version": 1, "publish_id": parent["publish_id"],
        "source_hashes": hashes, "template_selection": selection,
        "template": template,
        "candidates": legacy["cover"]["candidates"],
        "selected_cover_id": args.cover_id,
        "reuse_provenance": {
            "kind": "verified_v3",
            "source_publish_id": args.source_publish_id,
            "source_package_path": package_rel,
            "source_package_sha256": _sha256(package_path),
            "source_state_path": os.path.join(
                "workflow", "runs", parent["video_run_id"], "publish",
                args.source_publish_id, "state.json"),
        },
    }
    errors = validate_publish_cover(
        cover, template, source["topic"], project, hashes)
    errors += _verified_v3_cover_reuse_errors(project, parent, cover)
    if errors:
        raise RuntimeError("；".join(sorted(set(errors))))
    write_json(paths["cover_candidate"], cover)
    state.update(status="selected", template_selection=selection,
                 template=template, generation={"mode": "reused_verified_v3",
                                                "source_publish_id": args.source_publish_id},
                 verified_hash=None)
    _save_publish_child(paths["cover_state"], state)
    parent["children"]["cover"] = "selected"
    _save_publish_parent(paths, parent)
    print("旧 V3 已验证封面已按原图接入 V4，等待独立校验")


def _cover_planning_source(project, state, source):
    """Build the source snapshot for a cover plan."""
    spec = state["template"]["spec"]
    context = {"topic": source["topic"], "brand": source["brand"]}
    if spec["requires_style_anchor"]:
        style_references = _cover_style_references(project)
        count = spec.get("style_reference_count", 1)
        context["style_anchor"] = style_references[0]
        context["style_references"] = style_references[:count]
        if spec["requires_character_ids"] or spec["allows_people"]:
            chars_path = os.path.join(ROOT, "assets", "characters.json")
            context["characters"] = (read_json(chars_path)
                                     if os.path.isfile(chars_path) else {})
    return context


def _cover_plan_contract(parent, state, hashes):
    template_id = state["template"]["id"]
    spec = state["template"]["spec"]
    character_ids = (["registered id"]
                     if spec["requires_character_ids"] else [])
    candidate = {"id": "string", "concept": "string", "subject": "string",
                 "composition": "string", "title_lines": "exactly 2 strings",
                 "subtitle": "string", "character_ids": character_ids}
    return {"version": 1, "publish_id": parent["publish_id"],
            "source_hashes": hashes, "template_id": template_id,
            "candidates": [candidate, candidate]}


def cmd_publish_cover_plan(args):
    project, paths, parent, _, source, hashes = _publish_v4_context(args)
    state = read_json(paths["cover_state"])
    if not state.get("template_selection") or not state.get("template"):
        raise RuntimeError("必须先由用户人工选择并锁定封面模板")
    _require_active_cover_template(state)
    if state.get("status") in ("plan_verified", "generated", "composed", "selected",
                               "verified", "promoted"):
        raise RuntimeError("封面方案已冻结或进入后续阶段")
    context = _cover_planning_source(project, state, source)
    spec = state["template"]["spec"]
    image_route = _interactive_image_execution_route(
        parent["providers"]["image"])
    character_instruction = (
        "并提供正式角色 ID；"
        if spec["requires_character_ids"] else
        "且 character_ids 必须为空列表，不得规划人物；"
    )
    typography_instruction = (
        "书名与作者将在后续图片任务中作为书籍原生文字注入，右侧文字由本地合成。"
        if spec.get("book_text_mode") == "generated_exact" else
        "书名和作者由本地合成注入。"
    )
    task = {"stage": "publish-cover", "source": context,
            "source_hashes": hashes, "template": state["template"],
            "template_selection": state["template_selection"],
            "execution_boundary": {
                "allowed_in_this_task": ["write_cover_plan_json"],
                "must_stop_after_candidate": True,
                "forbidden": ["generate_image", "import_image", "compose_cover",
                              "review_cover", "select_cover", "promote", "finalize"],
                "next_image_stage": image_route,
            },
            "instruction": ("只输出两个不同的语义方案，不得输出 provider、model、"
                            "最终 prompt、negative prompt、图片路径或 hash。"
                            "每个方案提供两行观点标题、解释副标题"
                            f"{character_instruction}"
                            f"{typography_instruction}写入 candidate_path "
                            "后必须立即停止；"
                            f"后续图片只能在 {image_route['required_agent_environment']} "
                            "环境执行，当前内容 Agent 不得代替。"),
            "candidate_path": paths["cover_plan"],
            "output_contract": _cover_plan_contract(parent, state, hashes)}
    write_json(paths["cover_task"], task)
    provider = make_llm(parent["providers"]["llm"], ROOT)
    result = provider.generate("publish-cover", task, paths["cover_plan"])
    state["status"] = "awaiting_external" if result["mode"] == "interactive" else "plan_generated"
    _save_publish_child(paths["cover_state"], state)
    parent["children"]["cover"] = state["status"]
    _save_publish_parent(paths, parent)
    print(json.dumps({"task": paths["cover_task"], "candidate": paths["cover_plan"],
                      "state": state["status"]}, ensure_ascii=False, indent=2))


def cmd_publish_cover_verify_plan(args):
    project, paths, parent, _, source, hashes = _publish_v4_context(args)
    state = read_json(paths["cover_state"])
    if not state.get("template"):
        raise RuntimeError("尚未人工选择封面模板")
    if state.get("status") not in ("awaiting_external", "plan_generated"):
        raise RuntimeError("封面方案当前状态不可校验")
    errors = validate_cover_template_snapshot(state["template"])
    errors += validate_cover_plan(read_json(paths["cover_plan"]), state["template"],
                                  source["topic"], parent["publish_id"], hashes)
    if state["template"]["spec"]["requires_character_ids"] or \
            state["template"]["spec"]["allows_people"]:
        task = read_json(paths["cover_task"])
        raw_characters = task.get("source", {}).get("characters", {}).get(
            "characters", task.get("source", {}).get("characters", {}))
        if isinstance(raw_characters, list):
            valid_ids = {item.get("id") for item in raw_characters}
        elif isinstance(raw_characters, dict):
            valid_ids = set(raw_characters)
        else:
            valid_ids = set()
        for candidate in read_json(paths["cover_plan"]).get("candidates", []):
            if not set(candidate.get("character_ids", [])) <= valid_ids:
                errors.append("封面方案包含未知角色 ID")
    if errors:
        raise RuntimeError("；".join(sorted(set(errors))))
    state.update(status="plan_verified",
                 verified_plan_hash=_sha256(paths["cover_plan"]))
    _save_publish_child(paths["cover_state"], state)
    parent["children"]["cover"] = "plan_verified"
    _save_publish_parent(paths, parent)
    print("封面语义方案校验通过")


def _cover_image_tasks(project, paths, state, source):
    plan = read_json(paths["cover_plan"])
    spec = state["template"]["spec"]
    palette = source["brand"].get("visual", {}).get("palette", {})
    palette_text = ", ".join(f"{key} {value}" for key, value in palette.items())
    anchors = []
    source_context = {}
    if spec["requires_style_anchor"]:
        planning_task = read_json(paths["cover_task"])
        source_context = planning_task.get("source", {})
        anchors = source_context.get("style_references") or [
            source_context.get("style_anchor")]
        expected_count = spec.get("style_reference_count", 1)
        if len(anchors) < expected_count:
            raise RuntimeError("封面缺少规划阶段冻结的正式场景风格参考")
        scenes = os.path.realpath(os.path.join(project, "assets", "scenes"))
        for anchor in anchors[:expected_count]:
            if not isinstance(anchor, dict) or not anchor.get("path") or \
                    not anchor.get("sha256"):
                raise RuntimeError("封面风格参考记录无效")
            anchor_path = os.path.realpath(os.path.join(project, anchor["path"]))
            if os.path.commonpath((scenes, anchor_path)) != scenes or \
                    not os.path.isfile(anchor_path) or \
                    _sha256(anchor_path) != anchor["sha256"]:
                raise RuntimeError("封面风格参考路径或 hash 已变化")
        anchors = anchors[:expected_count]
    tasks = []
    book_title = source["topic"]["book_title"]
    author = source["topic"].get("author", "")
    for candidate in plan["candidates"]:
        if spec["layout"] == "book_left_hook_right_hybrid":
            author_instruction = (
                f" and render the exact author name {author!r} on the front cover"
                if author else ""
            )
            description = (
                f"cover background concept: {candidate['concept']}; subject: "
                f"{candidate['subject']}; composition: {candidate['composition']}; "
                "place one upright three-dimensional hardback book entirely within "
                "the left 44 percent; integrate the exact simplified-Chinese book "
                f"title {book_title!r} naturally into both the front cover and spine"
                f"{author_instruction}; preserve correct glyphs, reading order, "
                "perspective, print texture, and lighting; keep the right 52 percent "
                "as a naturally dark navy, low-detail, high-contrast field without "
                "any generated captions or display copy"
            )
        else:
            description = (
                f"cover background concept: {candidate['concept']}; subject: "
                f"{candidate['subject']}; composition: {candidate['composition']}; "
                "leave readable left hook area and character emphasis on right"
            )
        character_ids = candidate["character_ids"]
        char_bits = character_ids
        references = [os.path.realpath(os.path.join(project, anchors[0]["path"]))]
        style = "match the supplied official scene style anchor"
        forbidden_subject = ("" if spec["layout"] ==
                             "book_left_hook_right_hybrid"
                             else ", book mockup")
        if spec["layout"] == "book_left_hook_right_hybrid":
            negative = (
                "incorrect book title, misspelled Chinese characters, duplicated "
                "glyphs, extra readable text outside the book, captions, logo, "
                "watermark, photorealistic corporate stock art, flat vector "
                "technology wallpaper, person, people, character"
            )
            exact_text = book_title
            if author:
                exact_text += f"；{author}"
            text_policy = (
                f"required exact book text: title {book_title!r} on the front cover "
                f"and spine"
                + (f", author {author!r} on the front cover" if author else "")
                + "; local compositor adds all right-side typography"
            )
            manifest_text_policy = {
                "mode": "required_exact", "exact_text": exact_text,
            }
        else:
            negative = (
                "readable text, letters, words, title, captions, logo, watermark, "
                "photorealistic corporate stock art, flat vector technology "
                f"wallpaper{forbidden_subject}"
                + (", person, people, character"
                   if not spec["allows_people"] else "")
            )
            text_policy = "no readable text; local compositor adds all typography"
            manifest_text_policy = {"mode": "forbidden"}
        sources = {"style": style, "palette": palette_text,
                   "description": description, "char_bits": char_bits,
                   "shot": "wide",
                   "emotion": "neutral",
                   "text_policy": text_policy}
        prompt = build_image_prompt(**sources)
        task = {"key": candidate["id"], "prompt": prompt,
                "negative_prompt": negative, "size": [1920, 1080],
                "reference_images": references,
                "output_path": os.path.join(paths["covers_dir"],
                                             candidate["id"] + "_base.png"),
                "character_ids": character_ids,
                "style_anchor": (anchors[0] if anchors else None),
                "rule_manifest": {"prompt_sources": sources,
                                  "negative_prompt": negative,
                                  "text_policy": manifest_text_policy,
                                  "template_sha256": state["template"]["sha256"]}}
        task["task_sha256"] = _stable_json_hash(task)
        tasks.append(task)
    return tasks


def _initialize_cover_candidate(paths, state, source, hashes):
    plan = read_json(paths["cover_plan"])
    topic = source["topic"]
    candidates = []
    for item in plan["candidates"]:
        candidate = dict(item)
        text = {"title_lines": item["title_lines"],
                "subtitle": item["subtitle"],
                "book_title": topic["book_title"],
                "author": topic["author"]}
        candidate.update({"text": text,
                          "base_path": None, "base_sha256": None,
                          "final_path": None, "sha256": None,
                          "cover_task": None, "visual_review": None})
        candidates.append(candidate)
    data = {"version": 1, "publish_id": state["publish_id"],
            "source_hashes": hashes,
            "template_selection": state["template_selection"],
            "template": state["template"], "candidates": candidates,
            "selected_cover_id": None}
    write_json(paths["cover_candidate"], data)


def cmd_publish_cover_generate(args):
    project, paths, parent, _, source, hashes = _publish_v4_context(args)
    state = read_json(paths["cover_state"])
    _require_active_cover_template(state)
    if state.get("status") not in ("plan_verified", "awaiting_images", "generated"):
        raise RuntimeError("封面方案必须先校验，才能生成底图")
    if state.get("verified_plan_hash") != _sha256(paths["cover_plan"]):
        raise RuntimeError("封面方案 hash 已变化，必须重新校验")
    execution_route = _require_native_image_executor(
        parent["providers"]["image"])
    tasks = _cover_image_tasks(project, paths, state, source)
    os.makedirs(paths["covers_dir"], exist_ok=True)
    if not os.path.exists(paths["cover_candidate"]):
        _initialize_cover_candidate(paths, state, source, hashes)
    write_json(paths["cover_image_tasks"], {
        "version": 2, "execution_route": execution_route, "tasks": tasks})
    provider = make_image(parent["providers"]["image"], ROOT)
    if provider.mode != "interactive":
        provider.generate(tasks)
        for task in tasks:
            problem = _image_file_problem(task)
            if problem:
                raise RuntimeError(f"封面底图 {task['key']} 无效：{problem}")
        state.update(status="generated", generation={
            "mode": "api", "provider": parent["providers"]["image"]["name"],
            "execution_environment": execution_route["required_agent_environment"],
            "manifest_sha256": _sha256(paths["cover_image_tasks"]),
            "completed_keys": [x["key"] for x in tasks]})
    else:
        generation = state.get("generation") or {
            "mode": "serial", "provider": parent["providers"]["image"]["name"],
            "execution_environment": execution_route["required_agent_environment"],
            "manifest_sha256": _sha256(paths["cover_image_tasks"]),
            "active_key": None, "active_request": None,
            "completed_keys": [], "completed_sha256": {}}
        if generation["manifest_sha256"] != _sha256(paths["cover_image_tasks"]):
            raise RuntimeError("封面图片任务清单 hash 已变化")
        active_key = generation.get("active_key")
        if active_key:
            active = next(x for x in tasks if x["key"] == active_key)
            problem = _image_file_problem(active)
            if problem:
                signed = dict(active,
                              generation_request=generation["active_request"])
                print(json.dumps({"state": "awaiting_external", "tasks": [signed]},
                                 ensure_ascii=False, indent=2))
                return
            generation["completed_keys"].append(active_key)
            generation["completed_sha256"][active_key] = _sha256(active["output_path"])
            generation["active_key"] = None
            generation["active_request"] = None
        next_task = next((x for x in tasks
                          if x["key"] not in generation["completed_keys"]), None)
        if next_task:
            request = compile_image_generation_request(next_task)
            result = provider.generate([next_task])
            if result.get("mode") != "interactive":
                raise RuntimeError("交互式封面图片 provider 返回模式异常")
            generation["active_key"] = next_task["key"]
            generation["active_request"] = request
            state.update(status="awaiting_images", generation=generation)
            _save_publish_child(paths["cover_state"], state)
            signed = dict(next_task, generation_request=request)
            print(json.dumps({"state": "awaiting_external", "tasks": [signed],
                              "serial": {"completed": len(generation["completed_keys"]),
                                         "active_key": next_task["key"]}},
                             ensure_ascii=False, indent=2))
            return
        state.update(status="generated", generation=generation)
    data = read_json(paths["cover_candidate"])
    task_map = {x["key"]: x for x in tasks}
    for candidate in data["candidates"]:
        task = task_map[candidate["id"]]
        candidate["base_path"] = os.path.relpath(task["output_path"], project)
        candidate["base_sha256"] = _sha256(task["output_path"])
        candidate["cover_task"] = {
            "task_sha256": task["task_sha256"],
            "prompt_sha256": hashlib.sha256(task["prompt"].encode("utf-8")).hexdigest(),
            "reference_images": task["reference_images"],
            "character_ids": task["character_ids"]}
    write_json(paths["cover_candidate"], data)
    _save_publish_child(paths["cover_state"], state)
    parent["children"]["cover"] = "generated"
    _save_publish_parent(paths, parent)
    print("两个封面底图均已生成并校验")


def _cover_font(draw, font_path, text, max_width, start, minimum=36):
    size = start
    while size >= minimum:
        font = ImageFont.truetype(font_path, size)
        box = draw.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= max_width:
            return font
        size -= 2
    raise RuntimeError("封面文字无法在安全区内排版")


def _cover_font_path():
    candidates = [
        os.path.join(ROOT, "assets", "fonts", "SourceHanSansCN-Heavy.otf"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "assets", "fonts", "SourceHanSansCN-Heavy.otf"),
        "/System/Library/Fonts/PingFang.ttc",
    ]
    return next((path for path in candidates if os.path.exists(path)), None)


def _compose_reference_cover(base, destination, candidate, font_path):
    image = base.convert("RGB").resize((1920, 1080), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(image)
    lines = candidate["text"]["title_lines"]
    if len(lines) != 2 or not all(lines):
        raise RuntimeError("观点钩子封面必须严格为两行标题")
    ink, gold, shadow = (248, 246, 238), (246, 183, 76), (5, 12, 24)
    for text_value, y, color in ((lines[0], 112, ink), (lines[1], 336, gold)):
        font = _cover_font(draw, font_path, text_value, 900, 180, 56)
        draw.text((88, y), text_value, fill=shadow, font=font,
                  stroke_width=4, stroke_fill=shadow)
        draw.text((80, y - 8), text_value, fill=color, font=font)
    subtitle = candidate["text"].get("subtitle", "")
    if subtitle:
        font = _cover_font(draw, font_path, subtitle, 900, 46, minimum=28)
        draw.text((82, 674), subtitle, fill=ink, font=font,
                  stroke_width=2, stroke_fill=shadow)
    bookline = f"《{candidate['text']['book_title']}》｜{candidate['text']['author']}"
    font = _cover_font(draw, font_path, bookline, 900, 50, minimum=22)
    draw.line((96, 784, 900, 784), fill=gold, width=3)
    draw.text((82, 822), bookline, fill=gold, font=font,
              stroke_width=2, stroke_fill=shadow)
    image.save(destination, "PNG")
    return lines


def _compose_book_spotlight_hybrid_cover(
        base, destination, candidate, font_path):
    """Compose only the right-side copy; preserve generated book typography."""
    image = base.convert("RGB").resize((1920, 1080), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(image)
    lines = candidate["text"]["title_lines"]
    if len(lines) != 2 or not all(lines):
        raise RuntimeError("书籍主视觉封面必须严格为两行标题")

    ink = (237, 244, 255)
    gold = (246, 183, 76)
    cyan = (88, 196, 216)
    shadow = (5, 12, 24)
    book_title = candidate["text"]["book_title"]
    author = candidate["text"]["author"]

    bookline = f"《{book_title}》｜{author}"
    font = _cover_font(draw, font_path, bookline, 920, 50, minimum=24)
    draw.text((880, 132), bookline, fill=ink, font=font,
              stroke_width=2, stroke_fill=shadow)
    draw.line((880, 224, 1800, 224), fill=cyan, width=5)

    for text_value, y, color in ((lines[0], 278, ink),
                                 (lines[1], 508, gold)):
        font = _cover_font(draw, font_path, text_value, 920, 168, minimum=64)
        draw.text((890, y + 8), text_value, fill=shadow, font=font,
                  stroke_width=5, stroke_fill=shadow)
        draw.text((880, y), text_value, fill=color, font=font)

    subtitle = candidate["text"].get("subtitle", "")
    if subtitle:
        font = _cover_font(draw, font_path, subtitle, 920, 52, minimum=32)
        draw.text((882, 822), subtitle, fill=ink, font=font,
                  stroke_width=2, stroke_fill=shadow)
    draw.line((882, 936, 984, 936), fill=cyan, width=8)
    image.save(destination, "PNG")
    return lines


def cmd_publish_cover_compose(args):
    project, paths, parent, _, _, _ = _publish_v4_context(args)
    state = read_json(paths["cover_state"])
    _require_active_cover_template(state)
    if state.get("status") not in ("generated", "composed"):
        raise RuntimeError("两个封面底图必须先完成生成")
    data = read_json(paths["cover_candidate"])
    font_path = _cover_font_path()
    if not font_path:
        raise RuntimeError("未找到可用中文字体")
    composers = {
        "hook_left_character_right": _compose_reference_cover,
        "book_left_hook_right_hybrid": _compose_book_spotlight_hybrid_cover,
    }
    layout = state["template"]["spec"]["layout"]
    composer = composers.get(layout)
    if composer is None:
        raise RuntimeError(f"封面模板缺少合成器：{layout}")
    for candidate in data["candidates"]:
        base_path = os.path.join(project, candidate["base_path"])
        if _sha256(base_path) != candidate["base_sha256"]:
            raise RuntimeError("封面底图 hash 已变化")
        destination = os.path.join(paths["covers_dir"], candidate["id"] + ".png")
        with Image.open(base_path) as base:
            composer(base, destination, candidate, font_path)
        candidate["final_path"] = os.path.relpath(destination, project)
        candidate["sha256"] = _sha256(destination)
        candidate["visual_review"] = None
    write_json(paths["cover_candidate"], data)
    state.update(status="composed", verified_hash=None)
    _save_publish_child(paths["cover_state"], state)
    parent["children"]["cover"] = "composed"
    _save_publish_parent(paths, parent)
    print("两个封面候选已完成确定性文字合成")


def cmd_publish_cover_review(args):
    _, paths, parent, _, _, _ = _publish_v4_context(args)
    state = read_json(paths["cover_state"])
    _require_active_cover_template(state)
    if state.get("status") not in ("composed", "reviewed"):
        raise RuntimeError("封面当前状态不可写入视觉审核")
    data = read_json(paths["cover_candidate"])
    candidate = next((x for x in data["candidates"] if x["id"] == args.cover_id), None)
    if not candidate or not candidate.get("sha256"):
        raise RuntimeError("封面候选尚未完成合成")
    dimensions = state["template"]["spec"]["review_dimensions"]
    failed = set(args.failed_check or [])
    unknown = failed - set(dimensions)
    if unknown:
        raise RuntimeError("不属于当前模板的审核维度：" + "、".join(sorted(unknown)))
    if args.result == "pass" and failed:
        raise RuntimeError("审核通过时不得提供 --failed-check")
    if args.result == "fail" and not failed:
        raise RuntimeError("审核不通过时至少提供一个 --failed-check")
    review = {key: key not in failed for key in dimensions}
    review.update(status=args.result + "ed" if args.result == "pass" else "failed",
                  asset_sha256=candidate["sha256"],
                  reviewed_at=datetime.datetime.now().isoformat())
    candidate["visual_review"] = review
    write_json(paths["cover_candidate"], data)
    state.update(status="reviewed", verified_hash=None)
    _save_publish_child(paths["cover_state"], state)
    parent["children"]["cover"] = "reviewed"
    _save_publish_parent(paths, parent)
    print("封面视觉审核记录已写入")


def cmd_publish_cover_select(args):
    _, paths, parent, _, _, _ = _publish_v4_context(args)
    state = read_json(paths["cover_state"])
    _require_active_cover_template(state)
    if state.get("status") != "reviewed":
        raise RuntimeError("两个封面候选必须先完成视觉审核")
    data = read_json(paths["cover_candidate"])
    if any(not isinstance(x.get("visual_review"), dict) for x in data["candidates"]):
        raise RuntimeError("两个封面候选都必须先留下视觉审核记录")
    candidate = next((x for x in data["candidates"] if x["id"] == args.cover_id), None)
    if not candidate or candidate["visual_review"].get("status") != "passed":
        raise RuntimeError("只能人工选择审核通过的封面候选")
    data["selected_cover_id"] = args.cover_id
    write_json(paths["cover_candidate"], data)
    state.update(status="selected", verified_hash=None)
    _save_publish_child(paths["cover_state"], state)
    parent["children"]["cover"] = "selected"
    _save_publish_parent(paths, parent)
    print("最终封面已人工选择")


def _cover_image_task_problems(project, paths, parent, state, cover):
    problems = []
    if not os.path.isfile(paths["cover_image_tasks"]):
        return ["缺少封面图片任务清单"]
    packet = read_json(paths["cover_image_tasks"])
    tasks = packet.get("tasks", []) if isinstance(packet, dict) else []
    expected_route = _interactive_image_execution_route(
        parent["providers"]["image"])
    if packet.get("version") != 2 or packet.get("execution_route") != expected_route:
        problems.append("封面图片任务缺少正确的 Agent 执行路由")
    task_map = {task.get("key"): task for task in tasks if isinstance(task, dict)}
    if set(task_map) != {candidate.get("id") for candidate in cover["candidates"]}:
        problems.append("封面图片任务与候选 ID 不一致")
    generation = state.get("generation") or {}
    provider_name = parent["providers"]["image"]["name"]
    if generation.get("provider") != provider_name:
        problems.append("封面图片生成方式与视频 run 快照不一致")
    if generation.get("execution_environment") != \
            expected_route["required_agent_environment"]:
        problems.append("封面图片缺少匹配 provider 的执行环境证明")
    if generation.get("manifest_sha256") != _sha256(paths["cover_image_tasks"]):
        problems.append("封面图片任务清单 hash 已变化")
    if set(generation.get("completed_keys", [])) != set(task_map):
        problems.append("封面图片任务尚未全部完成")
    for candidate in cover["candidates"]:
        task = task_map.get(candidate.get("id"))
        if not task:
            continue
        unsigned = {key: value for key, value in task.items()
                    if key != "task_sha256"}
        if task.get("task_sha256") != _stable_json_hash(unsigned):
            problems.append("封面 ImageTask hash 无效")
        try:
            prompt_errors = validate_image_task_prompt(task)
        except Exception as exc:
            prompt_errors = [str(exc)]
        problems.extend(prompt_errors)
        summary = candidate.get("cover_task") or {}
        expected_prompt_hash = hashlib.sha256(
            task.get("prompt", "").encode("utf-8")).hexdigest()
        if summary.get("task_sha256") != task.get("task_sha256") or \
                summary.get("prompt_sha256") != expected_prompt_hash or \
                summary.get("character_ids") != task.get("character_ids") or \
                summary.get("reference_images") != task.get("reference_images"):
            problems.append("封面候选的 ImageTask 追溯信息不匹配")
        output = os.path.realpath(task.get("output_path") or "")
        expected_root = os.path.realpath(paths["covers_dir"])
        if os.path.commonpath((expected_root, output)) != expected_root or \
                not os.path.isfile(output):
            problems.append("封面底图不在本次候选目录")
        elif candidate.get("base_sha256") != _sha256(output):
            problems.append("封面底图 hash 与 ImageTask 输出不匹配")
        candidate_base = os.path.realpath(os.path.join(
            project, candidate.get("base_path") or ""))
        candidate_final = os.path.realpath(os.path.join(
            project, candidate.get("final_path") or ""))
        expected_final = os.path.realpath(os.path.join(
            paths["covers_dir"], str(candidate.get("id")) + ".png"))
        if candidate_base != output or candidate_final != expected_final:
            problems.append("封面候选底图或成品路径不属于本次确定性任务")
    return problems


def cmd_publish_cover_verify(args):
    project, paths, parent, _, source, hashes = _publish_v4_context(args)
    state = read_json(paths["cover_state"])
    if state.get("status") != "selected":
        raise RuntimeError("必须先人工选择最终封面")
    errors = validate_cover_template_snapshot(state.get("template"))
    cover = read_json(paths["cover_candidate"])
    errors += validate_publish_cover(cover,
                                     state.get("template") or {}, source["topic"],
                                     project, hashes, require_selection=True)
    if "reuse_provenance" in cover:
        errors += _verified_v3_cover_reuse_errors(project, parent, cover)
    else:
        errors += _cover_image_task_problems(project, paths, parent, state, cover)
    if errors:
        raise RuntimeError("；".join(sorted(set(errors))))
    state.update(status="verified", verified_hash=_sha256(paths["cover_candidate"]))
    _save_publish_child(paths["cover_state"], state)
    parent["children"]["cover"] = "verified"
    _save_publish_parent(paths, parent)
    print("封面校验通过")


def cmd_publish_cover_promote(args):
    project, paths, parent, _, source, hashes = _publish_v4_context(args)
    state = read_json(paths["cover_state"])
    _require_active_cover_template(state)
    if state.get("status") != "verified" or state.get("verified_hash") != \
            _sha256(paths["cover_candidate"]):
        raise RuntimeError("封面未验证或验证 hash 已过期")
    if os.path.exists(paths["approved_cover"]):
        raise RuntimeError("已存在提升后的封面，禁止覆盖")
    data = read_json(paths["cover_candidate"])
    if "reuse_provenance" in data:
        errors = validate_publish_cover(data, state["template"], source["topic"],
                                        project, hashes)
        errors += _verified_v3_cover_reuse_errors(project, parent, data)
        if errors:
            raise RuntimeError("；".join(sorted(set(errors))))
    selected = next(x for x in data["candidates"]
                    if x["id"] == data["selected_cover_id"])
    os.makedirs(paths["approved_root"], exist_ok=True)
    shutil.copy2(paths["cover_candidate"], paths["approved_cover"])
    shutil.copy2(os.path.join(project, selected["final_path"]),
                 paths["approved_cover_image"])
    state.update(status="promoted", promoted_hash=_sha256(paths["approved_cover"]),
                 promoted_image_hash=_sha256(paths["approved_cover_image"]))
    _save_publish_child(paths["cover_state"], state)
    parent["children"]["cover"] = "promoted"
    _save_publish_parent(paths, parent)
    _sync_publish_release_draft(paths, parent)
    print("封面已独立提升并汇入发布目录")


def cmd_publish_cover_status(args):
    _, paths, _, _, _, _ = _publish_v4_context(args)
    print(json.dumps(read_json(paths["cover_state"]), ensure_ascii=False, indent=2))


def cmd_publish_finalize(args):
    _, paths, parent, _, _, hashes = _publish_v4_context(args)
    copy_state = read_json(paths["copy_state"])
    cover_state = read_json(paths["cover_state"])
    if copy_state.get("status") != "promoted" or cover_state.get("status") != "promoted":
        raise RuntimeError("发布文案与封面必须分别提升后才能最终汇总")
    _require_active_cover_template(cover_state)
    actual_copy = _sha256(paths["approved_copy"])
    actual_cover = _sha256(paths["approved_cover"])
    actual_image = _sha256(paths["approved_cover_image"])
    if actual_copy != copy_state.get("promoted_hash") or \
            actual_cover != cover_state.get("promoted_hash") or \
            actual_image != cover_state.get("promoted_image_hash"):
        raise RuntimeError("已提升子产物 hash 已变化，禁止最终汇总")
    if os.path.exists(paths["release"]):
        raise RuntimeError("V4 发布包已经汇总，禁止覆盖")
    copy_data = read_json(paths["approved_copy"])
    cover_data = read_json(paths["approved_cover"])
    selected = next(x for x in cover_data["candidates"]
                    if x["id"] == cover_data["selected_cover_id"])
    package = {"version": 4, "publish_id": parent["publish_id"],
               "source_hashes": hashes,
               "copy": {"selected_title_id": copy_data["platforms"]["youtube"]["selected_title_id"],
                        "platforms": copy_data["platforms"],
                        "fact_core": copy_data["fact_core"]},
               "cover": {"selected_cover_id": cover_data["selected_cover_id"],
                         "template_selection": cover_data["template_selection"],
                         "template": cover_data["template"],
                         "selected": selected},
               "artifacts": {"copy_sha256": actual_copy,
                             "cover_sha256": actual_cover,
                             "cover_image_sha256": actual_image}}
    errors = validate_publish_release_v4(package, actual_copy, actual_cover,
                                         actual_image, parent["publish_id"], hashes)
    if errors:
        raise RuntimeError("；".join(errors))
    _sync_publish_release_draft(paths, parent)
    write_json(paths["release"], package)
    youtube = copy_data["platforms"]["youtube"]
    title = next(x["title"] for x in youtube["titles"]
                 if x["id"] == youtube["selected_title_id"])
    description = youtube["description"]
    with open(paths["upload"], "w", encoding="utf-8") as handle:
        handle.write("# 上传清单\n\n## YouTube 标题\n" + title +
                     "\n\n## 简介\n" + description["lead"] + "\n\n" +
                     "\n".join(description["highlights"]) + "\n\n" +
                     "\n".join(f"{x['time']} {x.get('title') or x.get('label', '')}"
                                 for x in description["timestamps"]) +
                     f"\n\n{description['cta']}\n{description['resources']}\n" +
                     " ".join(description["hashtags"]) +
                     "\n\n## 封面\ncover.png\n模板：" +
                     cover_data["template"]["id"] +
                     "\n\n## 上传前人工检查\n- 人工上传\n- 检查标题、简介与封面\n")
    parent.update(status="finalized", release_sha256=_sha256(paths["release"]))
    _save_publish_parent(paths, parent)
    os.remove(paths["release_draft"])
    print("V4 发布包已汇总；未执行平台上传")


def _legacy_publish_mutation(args):
    raise RuntimeError("历史 V1–V3 发布包只读；请用 publish-init 创建新的 V4 publish ID，"
                       "再使用 publish-copy-* 与 publish-cover-* 命令")


# 保留旧命令名作为明确的只读边界，不再写入历史包。
cmd_publish_run = _legacy_publish_mutation
cmd_publish_select = _legacy_publish_mutation
cmd_publish_import_cover = _legacy_publish_mutation
cmd_publish_compose_cover = _legacy_publish_mutation
cmd_publish_review_cover = _legacy_publish_mutation
cmd_publish_verify = _legacy_publish_mutation
cmd_publish_promote = _legacy_publish_mutation


def cmd_publish_status(args):
    project = set_project(args.project)
    paths = _publish_paths(project, args.video_run_id, args.revision, args.publish_id)
    state = read_json(paths["state"])
    result = {"parent": state}
    if state.get("version") == 4:
        result["copy"] = read_json(paths["copy_state"])
        result["cover"] = read_json(paths["cover_state"])
    else:
        result["read_only"] = True
    print(json.dumps(result, ensure_ascii=False, indent=2))


def parser():
    ap = argparse.ArgumentParser(description="可插拔长视频生产工作流")
    ap.add_argument("--project", default=None, help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="command", required=True)
    revise = sub.add_parser("revise", help="从现有 run 重新启动单一内容阶段")
    revise.add_argument("source_run_id")
    revise.add_argument("stage", choices=["storyboard"])
    revise.add_argument("--project", required=True)
    revise.add_argument("--run-id", default=None)
    revise.set_defaults(func=cmd_revise)
    create = sub.add_parser("create", help="新项目选择并固定内容与图片生成方式")
    create.add_argument("--project", required=True)
    create.add_argument("--llm", choices=sorted(LLM_PROVIDERS),
                        metavar="CONTENT_METHOD",
                        help=("内容生成方式：codex=Codex 当前会话；"
                              "deepseek=DeepSeek API；"
                              "antigravity=Antigravity 当前会话"))
    create.add_argument("--image", choices=sorted(IMAGE_PROVIDERS),
                        metavar="IMAGE_METHOD",
                        help=("图片生成方式：imagegen=Codex 内置 ImageGen；"
                              "wanxiang=万相 API；"
                              "antigravity=Antigravity 内置生图"))
    create.add_argument("--llm-model", help="仅 API 内容生成方式可指定模型")
    create.add_argument("--image-model", help="仅 API 图片生成方式可指定模型")
    create.add_argument("--azure-voice")
    create.add_argument("--content-template", choices=CONTENT_TEMPLATE_IDS,
                        default=None)
    create.set_defaults(func=cmd_create)
    init = sub.add_parser("init", help="创建可恢复 run")
    init.add_argument("--project", required=True)
    init.add_argument("--run-id")
    init.set_defaults(func=cmd_init)
    run = sub.add_parser("run", help="运行或准备一个阶段")
    run.add_argument("run_id")
    run.add_argument("stage", choices=ALL_STAGES)
    run.add_argument("--project")
    run.add_argument("--beats", nargs="*")
    run.add_argument("--review-id")
    run.add_argument("--revision")
    run.add_argument("--blocks", nargs="*", type=int)
    run.add_argument("--clip-durations", nargs="*", type=float)
    run.add_argument("--phase-images-dir")
    run.add_argument("--image-overrides-dir")
    run.add_argument("--reuse-segments-dir")
    run.add_argument("--rerender-blocks", nargs="*", type=int)
    run.set_defaults(func=cmd_run)
    select = sub.add_parser("select-topic", help="选择选题候选")
    select.add_argument("run_id")
    select.add_argument("candidate_id")
    select.add_argument("--project")
    select.set_defaults(func=cmd_select_topic)
    template_options = sub.add_parser(
        "template-options", help="列出已选题对应的内容模板选项，供 Sol 推荐")
    template_options.add_argument("run_id")
    template_options.add_argument("--project")
    template_options.set_defaults(func=cmd_template_options)
    select_template = sub.add_parser(
        "select-template", help="记录推荐并按用户明确选择锁定内容模板")
    select_template.add_argument("run_id")
    select_template.add_argument("template_id", choices=CONTENT_TEMPLATE_IDS)
    select_template.add_argument("--recommended", choices=CONTENT_TEMPLATE_IDS,
                                 required=True)
    select_template.add_argument("--reason", required=True)
    select_template.add_argument("--project")
    select_template.set_defaults(func=cmd_select_template)
    select_anchor = sub.add_parser("select-image-anchor",
                                   help="确认首张候选为本 run 视觉锚点")
    select_anchor.add_argument("run_id")
    select_anchor.add_argument("key")
    select_anchor.add_argument("--project")
    select_anchor.set_defaults(func=cmd_select_image_anchor)
    image_exception = sub.add_parser(
        "image-review-exception",
        help="记录哈希绑定的人工图片审核例外（不自动提升）")
    image_exception.add_argument("run_id")
    image_exception.add_argument("--project")
    image_exception.add_argument("--reason", required=True)
    image_exception.set_defaults(func=cmd_image_review_exception)
    verify = sub.add_parser("verify", help="校验候选阶段")
    verify.add_argument("run_id")
    verify.add_argument("stage", choices=APPROVAL_STAGES)
    verify.add_argument("--project")
    verify.set_defaults(func=cmd_verify)
    promote = sub.add_parser("promote", help="人工确认后提升候选")
    promote.add_argument("run_id")
    promote.add_argument("stage", choices=APPROVAL_STAGES)
    promote.add_argument("--project")
    promote.add_argument("--replace", action="store_true")
    promote.set_defaults(func=cmd_promote)
    status = sub.add_parser("status", help="查看 run 状态")
    status.add_argument("run_id")
    status.add_argument("--project")
    status.set_defaults(func=cmd_status)
    for name, func in (("brand-init", cmd_brand_init), ("brand-run", cmd_brand_run),
                       ("brand-select", cmd_brand_select), ("brand-verify", cmd_brand_verify),
                       ("brand-promote", cmd_brand_promote), ("brand-status", cmd_brand_status)):
        p = sub.add_parser(name); p.add_argument("--run-id", required=True); p.add_argument("--project", required=True); p.add_argument("--channel", default="main")
        if name == "brand-select": p.add_argument("--name-id", required=True); p.add_argument("--visual-id", required=True)
        p.set_defaults(func=func)
    for name, func in (("publish-init", cmd_publish_init),
                       ("publish-run", cmd_publish_run),
                       ("publish-select", cmd_publish_select),
                       ("publish-review-cover", cmd_publish_review_cover),
                       ("publish-import-cover", cmd_publish_import_cover),
                       ("publish-compose-cover", cmd_publish_compose_cover),
                       ("publish-verify", cmd_publish_verify),
                       ("publish-promote", cmd_publish_promote),
                       ("publish-status", cmd_publish_status)):
        p = sub.add_parser(name); p.add_argument("video_run_id"); p.add_argument("--project", required=True); p.add_argument("--channel", default="main")
        p.add_argument("--revision", default="v2"); p.add_argument("--publish-id", default=None)
        if name != "publish-init": p.add_argument("publish_id")
        if name == "publish-select": p.add_argument("--title-id", required=True); p.add_argument("--cover-id", required=True)
        if name == "publish-review-cover":
            p.add_argument("--cover-id", required=True)
            for field in ("style", "character", "semantic", "layout", "thumbnail_legibility"):
                p.add_argument(f"--{field}", choices=("pass", "fail"), required=True)
        if name == "publish-import-cover":
            p.add_argument("--cover-id", required=True); p.add_argument("--input", required=True); p.add_argument("--variant")
        if name == "publish-compose-cover":
            p.add_argument("--cover-id", required=True); p.add_argument("--variant")
        p.set_defaults(func=func)
    publish_v4 = (
        ("publish-copy-run", cmd_publish_copy_run),
        ("publish-copy-select", cmd_publish_copy_select),
        ("publish-copy-verify", cmd_publish_copy_verify),
        ("publish-copy-promote", cmd_publish_copy_promote),
        ("publish-copy-status", cmd_publish_copy_status),
        ("publish-cover-template-options", cmd_publish_cover_template_options),
        ("publish-cover-select-template", cmd_publish_cover_select_template),
        ("publish-cover-reuse-verified", cmd_publish_cover_reuse_verified),
        ("publish-cover-plan", cmd_publish_cover_plan),
        ("publish-cover-verify-plan", cmd_publish_cover_verify_plan),
        ("publish-cover-generate", cmd_publish_cover_generate),
        ("publish-cover-compose", cmd_publish_cover_compose),
        ("publish-cover-review", cmd_publish_cover_review),
        ("publish-cover-select", cmd_publish_cover_select),
        ("publish-cover-verify", cmd_publish_cover_verify),
        ("publish-cover-promote", cmd_publish_cover_promote),
        ("publish-cover-status", cmd_publish_cover_status),
        ("publish-finalize", cmd_publish_finalize),
    )
    for name, func in publish_v4:
        p = sub.add_parser(name)
        p.add_argument("video_run_id")
        p.add_argument("publish_id")
        p.add_argument("--project", required=True)
        p.add_argument("--revision", default="v2", help=argparse.SUPPRESS)
        if name == "publish-copy-select":
            p.add_argument("--title-id", required=True)
        elif name == "publish-cover-select-template":
            p.add_argument("template_id", choices=COVER_TEMPLATE_IDS)
            p.add_argument("--recommended", choices=COVER_TEMPLATE_IDS,
                           required=True)
            p.add_argument("--reason", required=True)
        elif name == "publish-cover-reuse-verified":
            p.add_argument("--source-publish-id", required=True)
            p.add_argument("--cover-id", required=True)
            p.add_argument("--filename", required=True)
        elif name == "publish-cover-review":
            p.add_argument("--cover-id", required=True)
            p.add_argument("--result", choices=("pass", "fail"), required=True)
            p.add_argument("--failed-check", action="append",
                           choices=sorted({dimension
                                          for template in cover_template_catalog()
                                          for dimension in template["spec"]["review_dimensions"]}))
        elif name == "publish-cover-select":
            p.add_argument("--cover-id", required=True)
        p.set_defaults(func=func)
    return ap


def main():
    args = parser().parse_args()
    try:
        args.func(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
