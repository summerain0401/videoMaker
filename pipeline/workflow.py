#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Provider-neutral long-video production workflow."""

import argparse
import datetime
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
                                    "shot=wide/medium/close；"
                                    "segment=hook/insight/action",
                    "forbidden_fields": ["provider", "model", "final_image_prompt",
                                         "negative_prompt", "api_request"],
                }}
    raise ValueError(stage)


def cmd_run(args):
    paths, state = locate_run(args.run_id, args.project)
    stage = args.stage
    if state["stages"][stage]["status"] in ("verified", "promoted"):
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
        _run_render(paths, state)
    elif stage == "qa":
        _run_qa(paths, state)
    else:
        raise ValueError(stage)


def cmd_select_topic(args):
    paths, state = locate_run(args.run_id, args.project)
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


def _run_render(paths, state):
    pid = state["project_id"]
    cmd = [sys.executable, os.path.join(ROOT, "pipeline", "build_long.py"),
           "--project", pid, "--workflow-run", state["run_id"]]
    output = os.path.join(paths["project"], "output", f"long_{pid}.mp4")
    try:
        subprocess.run(cmd, check=True)
        if not os.path.exists(output):
            raise FileNotFoundError(f"渲染命令未生成成片：{output}")
    except Exception as exc:
        transition(state, "render", "failed", str(exc))
        save_state(paths, state)
        raise
    transition(state, "render", "promoted", "渲染完成", output)
    unlock(state)
    save_state(paths, state)
    print(f"渲染完成：{output}")


def _run_qa(paths, state):
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
        report = {
            "video": video, "ffprobe": probe, "decode": "ok",
            "mean_volume_db": mean_volume,
            "checked_at": datetime.datetime.now().isoformat(),
        }
        write_json(paths["qa"], report)
    except Exception as exc:
        transition(state, "qa", "failed", str(exc))
        save_state(paths, state)
        raise
    transition(state, "qa", "promoted", "1080p、响度与完整解码通过", paths["qa"])
    save_state(paths, state)
    print(f"QA 通过：{paths['qa']}")


def cmd_status(args):
    paths, state = locate_run(args.run_id, args.project)
    relative = {key: os.path.relpath(value, ROOT) for key, value in paths.items()
                if isinstance(value, str)}
    print(json.dumps({"state": state, "paths": relative},
                     ensure_ascii=False, indent=2))


def parser():
    ap = argparse.ArgumentParser(description="可插拔长视频生产工作流")
    ap.add_argument("--project", default=None, help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="command", required=True)
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
