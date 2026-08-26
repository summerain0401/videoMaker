#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Provider-neutral long-video production workflow."""

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import proj as PJ
from providers import IMAGE_PROVIDERS, LLM_PROVIDERS, make_image, make_llm
from workflow_contracts import (
    ALL_STAGES, APPROVAL_STAGES, STAGE_STATES, build_image_tasks,
    normalize_providers,
    read_json, safe_project_suffix, selected_topic,
    validate_copy, validate_providers, validate_script, validate_storyboard,
    validate_topic, write_json,
)
from publishing_contracts import (PLATFORMS, TITLE_LIMITS, source_hashes,
                                   validate_brand, validate_package, validate_svg_text)


STATE_VERSION = 2
DEPENDENCIES = {
    "topic": [], "copy": ["topic"], "script": ["copy"],
    "storyboard": ["script"], "images": ["storyboard"],
    "voice": ["script"], "render": ["images", "voice"],
    "qa": ["render"],
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
        "images": os.path.join(project, "assets", "scenes", "candidates", run_id),
        "image_tasks": os.path.join(run_dir, "image_tasks.json"),
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
    return paths, read_json(paths["state"])


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


def cmd_create(args):
    PJ.CURRENT_ID = args.project
    PJ._CACHE.clear()
    project = PJ.project_dir(args.project, title="新项目", author="")
    meta_path = os.path.join(project, "project.json")
    meta = read_json(meta_path)
    proposed = normalize_providers({
        "llm": {"name": args.llm, "model": args.llm_model},
        "image": {"name": args.image, "model": args.image_model},
        "speech": {"name": "azure", "voice": args.azure_voice},
    })
    problems = validate_providers(proposed, LLM_PROVIDERS, IMAGE_PROVIDERS)
    if problems:
        raise ValueError("；".join(problems))
    existing_states = []
    workflow_root = os.path.join(project, "workflow", "runs")
    if os.path.isdir(workflow_root):
        for name in os.listdir(workflow_root):
            state_file = os.path.join(workflow_root, name, "state.json")
            if os.path.exists(state_file):
                existing_states.append(read_json(state_file))
    if any(s.get("stages", {}).get("qa", {}).get("status") != "promoted"
           for s in existing_states):
        raise RuntimeError("项目存在活动 run，禁止修改 provider 配置")
    meta["providers"] = proposed
    write_json(meta_path, meta)
    request = os.path.join(project, "input", "topic_request.md")
    if not os.path.exists(request):
        os.makedirs(os.path.dirname(request), exist_ok=True)
        with open(request, "w", encoding="utf-8") as f:
            f.write("# 选题需求\n\n## 频道定位\n\n## 目标受众\n\n"
                    "## 希望解决的问题\n\n## 排除方向\n\n"
                    "## 候选书池（可选）\n\n")
    print(json.dumps({"project": project, "providers": proposed,
                      "topic_request": request}, ensure_ascii=False, indent=2))


def cmd_init(args):
    project = set_project(args.project)
    meta = project_meta(project)
    configured = meta.get("providers") or {}
    problems = validate_providers(configured, LLM_PROVIDERS, IMAGE_PROVIDERS)
    if problems:
        raise ValueError("；".join(problems))
    providers = normalize_providers(configured)
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
        "current_stage": "topic", "stages": statuses,
    }
    save_state(paths, state)
    print(json.dumps({"run_id": run_id, "state": paths["state"],
                      "providers": providers}, ensure_ascii=False, indent=2))


def build_task(paths, state, stage):
    project = paths["project"]
    formal = formal_paths(project)
    if stage == "topic":
        request = os.path.join(project, "input", "topic_request.md")
        with open(request, encoding="utf-8") as handle:
            request_text = handle.read()
        return {"stage": stage, "topic_request": request_text,
                "candidate_path": paths[stage],
                "output_contract": {
                    "type": "json",
                    "top_level": ["candidates", "selected_id"],
                    "candidate_fields": [
                        "id", "book_title", "author", "angle",
                        "audience_promise", "video_title", "rationale",
                    ],
                    "requirements": "输出 3 个候选；id 唯一；selected_id 初始为 null",
                }}
    if stage == "copy":
        return {"stage": stage, "topic": read_json(formal["topic"]),
                "candidate_path": paths[stage],
                "output_contract": {
                    "type": "json",
                    "fields": ["thesis", "audience_promise", "claims", "sections"],
                    "requirements": "sections 恰好五段，每段含 name/objective/"
                                    "key_points/examples/action",
                }}
    if stage == "script":
        return {"stage": stage, "topic": read_json(formal["topic"]),
                "copy": read_json(formal["copy"]),
                "candidate_path": paths[stage],
                "output_contract": {
                    "type": "text", "voice_chars": [3800, 4500],
                    "requirements": "# TITLE；五个 # PHASE nn · 名称；内容块用"
                                    " # CARD/# QUOTE/# TABLE/# STEPS；以 # END 结束；"
                                    "所有非 PHASE/END 内容块必须含 voice：",
                }}
    if stage == "storyboard":
        with open(formal["script"], encoding="utf-8") as f:
            script = f.read()
        return {"stage": stage, "script_text": script,
                "characters_path": os.path.join(ROOT, "assets", "characters.json"),
                "candidate_path": paths[stage],
                "output_contract": {
                    "type": "json", "top_level": ["version", "blocks"],
                    "block_fields": ["block_idx", "type", "head", "voice_chars",
                                     "subtitles", "beats"],
                    "beat_fields": ["beat_idx", "shot", "visual_description",
                                    "sentence_ids", "start_char", "end_char",
                                    "character_ids", "emotion", "segment"],
                    "requirements": "逐块对应剧本；每句按顺序恰好覆盖一次；"
                                    "PHASE 只能 1 beat；非 PHASE 有口播块按字数至少"
                                    " 1+ceil((voice_chars-120)/100) 拍（不超过 120 字/拍、"
                                    "每拍 1-4 句）；shot=wide/medium/close；"
                                    "segment=hook/insight/action",
                    "forbidden_fields": ["provider", "model", "final_image_prompt",
                                         "negative_prompt", "api_request"],
                }}
    raise ValueError(stage)


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
                                  getattr(args, "phase_images_dir", None))):
        raise ValueError("review/revision/blocks 参数只允许用于 render 阶段")
    if review_render and not getattr(args, "blocks", None):
        raise ValueError("review render 必须显式指定 --blocks")
    if state["stages"][stage]["status"] in ("verified", "promoted") and not (
            review_render or revision_render):
        raise RuntimeError(f"阶段 {stage} 已校验或完成，不能在同一 run 内重新生成")
    require_dependencies(state, stage)
    project = paths["project"]
    if stage in ("topic", "copy", "script", "storyboard"):
        task = build_task(paths, state, stage)
        task_path = os.path.join(paths["tasks"], stage + ".json")
        write_json(task_path, task)
        provider = make_llm(state["providers"]["llm"], ROOT)
        try:
            result = provider.generate(stage, task, paths[stage])
        except Exception as exc:
            transition(state, stage, "failed", str(exc))
            save_state(paths, state)
            raise
        if result["mode"] == "interactive":
            transition(state, stage, "awaiting_external",
                       f"等待外部 Codex 写入候选：{paths[stage]}", task_path)
        else:
            transition(state, stage, "generated", "DeepSeek 候选已生成",
                       paths[stage])
        save_state(paths, state)
        print(json.dumps({"state": state["stages"][stage],
                          "task": task_path, "candidate": paths[stage]},
                         ensure_ascii=False, indent=2))
        return
    if stage == "images":
        storyboard = read_json(formal_paths(project)["storyboard"])
        chars_path = os.path.join(ROOT, "assets", "characters.json")
        characters = read_json(chars_path) if os.path.exists(chars_path) else {}
        tasks = build_image_tasks(storyboard, project_meta(project), characters,
                                  paths["images"])
        selected_tasks = tasks
        if args.beats:
            wanted = set(args.beats)
            unknown = wanted - {task["key"] for task in tasks}
            if unknown:
                raise ValueError("未知图片任务：" + ", ".join(sorted(unknown)))
            selected_tasks = [task for task in tasks if task["key"] in wanted]
        write_json(paths["image_tasks"], {"tasks": tasks})
        provider = make_image(state["providers"]["image"], ROOT)
        try:
            result = provider.generate(selected_tasks)
        except Exception as exc:
            transition(state, stage, "failed", str(exc), paths["image_tasks"])
            save_state(paths, state)
            raise
        status = "awaiting_external" if result["mode"] == "interactive" else "generated"
        transition(state, stage, status,
                   "等待 ImageGen 写入候选图片" if status == "awaiting_external"
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


def _verify_images(paths, project):
    story = read_json(formal_paths(project)["storyboard"])
    chars_path = os.path.join(ROOT, "assets", "characters.json")
    characters = read_json(chars_path) if os.path.exists(chars_path) else {}
    tasks = build_image_tasks(story, project_meta(project), characters, paths["images"])
    problems = []
    for task in tasks:
        path = task["output_path"]
        if not os.path.exists(path):
            problems.append(f"缺少图片：{task['key']}")
            continue
        try:
            with Image.open(path) as image:
                width, height = image.size
            if abs(width / height - 16 / 9) > 0.02:
                problems.append(f"图片比例不是 16:9：{task['key']} {width}x{height}")
        except Exception as exc:
            problems.append(f"图片损坏：{task['key']} {exc}")
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
        problems = validate_copy(read_json(paths[stage]))
    elif stage == "script":
        with open(paths[stage], encoding="utf-8") as f:
            problems, _, _ = validate_script(f.read())
    elif stage == "storyboard":
        with open(formal_paths(project)["script"], encoding="utf-8") as f:
            _, _, blocks = validate_script(f.read())
        chars_path = os.path.join(ROOT, "assets", "characters.json")
        characters = read_json(chars_path) if os.path.exists(chars_path) else {}
        raw_characters = characters.get("characters", characters)
        known_ids = ([x["id"] for x in raw_characters]
                     if isinstance(raw_characters, list) else raw_characters.keys())
        problems = validate_storyboard(read_json(paths[stage]), blocks, known_ids)
    elif stage == "images":
        problems = _verify_images(paths, project)
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
            state["stages"][stage]["status"] = "pending"


def cmd_promote(args):
    paths, state = locate_run(args.run_id, args.project)
    ensure_active_run(state, "promote")
    stage = args.stage
    if state["stages"][stage]["status"] != "verified":
        raise RuntimeError(f"{stage} 尚未 verified，禁止提升")
    project = paths["project"]
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
    elif stage in ("copy", "script", "storyboard"):
        backup_and_copy(paths[stage], formal[stage], args.run_id, args.replace)
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
    else:
        raise ValueError(stage)
    transition(state, stage, "promoted", "已人工确认并提升")
    unlock(state)
    save_state(paths, state)
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
    if phase_images_dir:
        phase_images_dir = os.path.realpath(phase_images_dir)
        project_root = os.path.realpath(paths["project"])
        if os.path.commonpath((project_root, phase_images_dir)) != project_root:
            raise ValueError("阶段候选图目录必须位于当前项目内")
        if not (review_id or revision):
            raise ValueError("阶段候选图只允许用于 review/revision")
        cmd += ["--phase-images-dir", phase_images_dir]
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
    try:
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
    candidate = os.path.join(root, "candidates", f"{video_run}_{revision}", "package.json")
    release = os.path.join(root, "releases", publish_id)
    run = os.path.join(project, "workflow", "runs", video_run, "publish", publish_id)
    return {"candidate": candidate, "release": os.path.join(release, "package.json"),
            "upload": os.path.join(release, "upload.md"), "run": run,
            "state": os.path.join(run, "state.json"), "task": os.path.join(run, "task.json")}


def _formal_source_paths(project):
    return {x: os.path.join(project, "input", f"{x}.{'txt' if x == 'script' else 'json'}")
            for x in ("topic", "copy", "script", "storyboard")}


def _cover_style_references(project):
    """选择正式常规场景作为封面风格参考，不接受候选或 phase 素材。"""
    root = os.path.join(project, "assets", "scenes")
    files = []
    regular_name = re.compile(r"^\d{2}_\d+\.png$")
    if os.path.isdir(root):
        for base, _, names in os.walk(root):
            for name in names:
                if not regular_name.match(name):
                    continue
                full = os.path.join(base, name)
                if "candidates" in os.path.realpath(full).split(os.sep):
                    continue
                files.append(full)
    files.sort(key=lambda path: tuple(int(part) for part in re.match(r"^(\d{2})_(\d+)\.png$", os.path.basename(path)).groups()))
    if not files:
        raise RuntimeError("publish-run 阻断：项目没有正式常规场景 PNG，无法建立封面风格参考")
    return [{"path": os.path.relpath(path, project), "sha256": _sha256(path),
             "purpose": "正式成片风格与角色身份参考"} for path in files[:3]]


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
    state = {"version": 1, "publish_id": pid, "video_run_id": args.video_run_id, "revision": revision, "status": "pending", "providers": video["providers"], "artifact": video["stages"]["render"]["artifact"], "updated_at": ""}
    write_json(p["state"], state); print(json.dumps({"publish_id": pid, "state": p["state"]}, ensure_ascii=False))


def cmd_publish_run(args):
    project = set_project(args.project); p = _publish_paths(project, args.video_run_id, args.revision, args.publish_id); state = read_json(p["state"]); formal = _formal_source_paths(project); brand = _brand_paths(project, args.channel, "unused")["brand"]
    source = {k: read_json(v) if k != "script" else open(v, encoding="utf-8").read() for k, v in formal.items()}
    style_refs = _cover_style_references(project)
    hashes = source_hashes({**formal, "brand": brand})
    task = {"stage": "publish", "source": {"topic": source["topic"], "copy": source["copy"], "script": source["script"], "storyboard": source["storyboard"], "brand": read_json(brand)}, "source_hashes": hashes, "cover_style_references": style_refs, "cover_visual_policy": "封面必须以 cover_style_references 中正式场景作为 style + character identity references，保持同一画风、角色设定、比例、线条、色彩与光影；禁止 photorealism、painterly realism、不同角色身份及与成片不一致的写实/极简/3D视觉。实际生成必须将这些文件作为 input references。", "candidate_path": p["candidate"], "output_contract": {"version": 1, "publish_id": "string", "channel_id": args.channel, "source": {"hashes": hashes}, "fact_core": {"summary": "string", "claim_refs": "copy.claims indexes", "script_evidence": "literal script substrings"}, "cover": {"aspect_ratio": "16:9", "style_references": "与任务参考完整一致", "style_requirements": "正式视觉一致性要求"}, "platforms": {p: {"primary_title": "string", "alternate_titles": 2, "description": "string", "tags": "3-8", "cta": "string"} for p in PLATFORMS}}}
    write_json(p["task"], task); provider = make_llm(state["providers"]["llm"], ROOT); result = provider.generate("publish", task, p["candidate"]); state["status"] = "awaiting_external" if result["mode"] == "interactive" else "generated"; save_state({"state": p["state"]}, state)


def cmd_publish_verify(args):
    project = set_project(args.project); p = _publish_paths(project, args.video_run_id, args.revision, args.publish_id); data = read_json(p["candidate"]); formal = _formal_source_paths(project); brand = _brand_paths(project, args.channel, "unused")["brand"]; hashes = source_hashes({**formal, "brand": brand})
    with open(formal["script"], encoding="utf-8") as handle:
        script = handle.read()
    copy_data = read_json(formal["copy"]); task = read_json(p["task"]); errors = validate_package(data, hashes, script, copy_data, str(args.project), args.video_run_id, args.revision, brand_hash=hashes["brand"], cover_style_references=task.get("cover_style_references"), project_root=project)
    if errors: raise RuntimeError("；".join(errors))
    state = read_json(p["state"]); state["status"] = "verified"; save_state({"state": p["state"]}, state); print("publish 校验通过")


def cmd_publish_promote(args):
    project = set_project(args.project); p = _publish_paths(project, args.video_run_id, args.revision, args.publish_id); state = read_json(p["state"])
    if state.get("status") != "verified": raise RuntimeError("publish 尚未 verified")
    data = read_json(p["candidate"]); os.makedirs(os.path.dirname(p["release"]), exist_ok=True); write_json(p["release"], data)
    with open(p["upload"], "w", encoding="utf-8") as f:
        f.write("# 上传清单\n\n## 统一事实核心\n" + str(data.get("fact_core", {}).get("summary", "")) + "\n\n## 封面文案与视觉任务\n" + data.get("cover", {}).get("concept", "") + "\n")
        labels = {"youtube": "YouTube", "bilibili": "B站", "douyin": "抖音", "wechat": "视频号"}
        for platform in PLATFORMS: f.write(f"\n## {labels[platform]}\n{data.get('platforms', {}).get(platform, {}).get('primary_title', '')}\n")
        f.write("\n## 上传前人工检查\n- 人工上传\n- 检查标题与封面\n- 检查封面与正式场景的风格/角色一致性\n")
    state["status"] = "promoted"; save_state({"state": p["state"]}, state); print("publish 已提升")


def cmd_publish_status(args):
    p = _publish_paths(set_project(args.project), args.video_run_id, args.revision, args.publish_id); print(json.dumps(read_json(p["state"]), ensure_ascii=False, indent=2))


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
    create = sub.add_parser("create", help="创建项目并固定 provider")
    create.add_argument("--project", required=True)
    create.add_argument("--llm", choices=sorted(LLM_PROVIDERS), default="codex")
    create.add_argument("--image", choices=sorted(IMAGE_PROVIDERS), default="imagegen")
    create.add_argument("--llm-model")
    create.add_argument("--image-model")
    create.add_argument("--azure-voice",
                        default="zh-CN-Xiaochen:DragonHDFlashLatestNeural")
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
    run.set_defaults(func=cmd_run)
    select = sub.add_parser("select-topic", help="选择选题候选")
    select.add_argument("run_id")
    select.add_argument("candidate_id")
    select.add_argument("--project")
    select.set_defaults(func=cmd_select_topic)
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
    for name, func in (("publish-init", cmd_publish_init), ("publish-run", cmd_publish_run),
                       ("publish-verify", cmd_publish_verify), ("publish-promote", cmd_publish_promote),
                       ("publish-status", cmd_publish_status)):
        p = sub.add_parser(name); p.add_argument("video_run_id"); p.add_argument("--project", required=True); p.add_argument("--channel", default="main")
        p.add_argument("--revision", default="v2"); p.add_argument("--publish-id", default=None)
        if name != "publish-init": p.add_argument("publish_id")
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
