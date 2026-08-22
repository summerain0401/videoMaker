#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Codex 原生制作任务的本地状态、校验与候选资产接口。

本脚本不调用模型、不读取任何 API 密钥，也不访问网络。它只为 Codex skill
提供可恢复的任务状态、候选文件路径、离线校验及人工确认后的提升操作。

典型流程：
  1. init 创建 run_id 与候选路径；Codex 把文案写入 draft_codex_<run_id>.txt。
  2. verify-copy 校验文案；人工确认后 promote copy 定稿。
  3. Codex 把叙事分镜写入 input/candidates/<run_id>/；verify / promote storyboard。
  4. Codex 再生成最终输出分镜 storyboard_output.json，补齐角色、情绪和
     final_image_prompt；verify / promote output 后才可进入默认图片阶段。
  5. image-targets 输出逐拍图片任务；Codex ImageGen 把候选图写入
     assets/scenes/candidates/<run_id>/；verify-images / promote images。

所有提升操作默认拒绝覆盖现有正式资产。确有意替换时必须显式传 --replace。
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proj as PJ


STATE_VERSION = 1
RUN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$")


def sha256_file(path):
    """返回文件 SHA-256；调用方先保证文件存在。"""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def now_run_id():
    return "codex_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def require_run_id(run_id):
    if not RUN_RE.fullmatch(run_id or ""):
        raise ValueError("run_id 只能含字母、数字、下划线和连字符，长度 3-64。")
    return run_id


def project_paths(run_id):
    """返回此 run 的绝对路径；只在 init 时创建目录。"""
    project = PJ.project_dir()
    candidate_dir = os.path.join(project, "input", "candidates", run_id)
    images_dir = os.path.join(project, "assets", "scenes", "candidates", run_id)
    run_dir = os.path.join(project, "output", "codex_jobs", run_id)
    return {
        "project": project,
        "run_dir": run_dir,
        "state": os.path.join(run_dir, "state.json"),
        "summary": os.path.join(run_dir, "summary.md"),
        "draft": os.path.join(project, "input", f"draft_{run_id}.txt"),
        "storyboard": os.path.join(candidate_dir, "storyboard_narrative.json"),
        "chibi": os.path.join(candidate_dir, "storyboard_output.json"),
        "candidate_dir": candidate_dir,
        "images_dir": images_dir,
        "script": os.path.join(project, "input", "script.txt"),
        "active_storyboard": os.path.join(project, "input", "storyboard_narrative.json"),
        "active_chibi": os.path.join(project, "input", "storyboard_output.json"),
        "active_images": os.path.join(project, "assets", "scenes"),
    }


def relative_paths(paths):
    return {k: os.path.relpath(v, ROOT) if k != "project" else
            os.path.relpath(v, ROOT) for k, v in paths.items()}


def load_state(run_id):
    paths = project_paths(run_id)
    if not os.path.exists(paths["state"]):
        raise FileNotFoundError(f"未找到 Codex run：{paths['state']}")
    with open(paths["state"], encoding="utf-8") as f:
        state = json.load(f)
    if state.get("version") != STATE_VERSION or state.get("run_id") != run_id:
        raise ValueError("任务状态版本或 run_id 不匹配。")
    return paths, state


def write_summary(paths, state):
    stages = state["stages"]
    lines = [
        "# Codex 制作任务摘要",
        "",
        f"- run_id: `{state['run_id']}`",
        f"- 创建时间: {state['created_at']}",
        f"- 图片模式: {state['image_mode']}",
        f"- 当前阶段: {state['current_stage']}",
        "",
        "| 阶段 | 状态 | 备注 |",
        "|---|---|---|",
    ]
    for name in ("copy", "storyboard", "chibi", "images"):
        item = stages[name]
        lines.append(f"| {name} | {item['status']} | {item.get('note', '')} |")
    lines += [
        "",
        "## 候选路径",
        "",
        f"- 文案：`{os.path.relpath(paths['draft'], ROOT)}`",
        f"- 分镜：`{os.path.relpath(paths['storyboard'], ROOT)}`",
        f"- 最终输出分镜：`{os.path.relpath(paths['chibi'], ROOT)}`",
        f"- 候选图片：`{os.path.relpath(paths['images_dir'], ROOT)}`",
    ]
    with open(paths["summary"], "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def save_state(paths, state):
    state["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(paths["state"], "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")
    write_summary(paths, state)


def mark(state, stage, status, note=""):
    state["stages"][stage]["status"] = status
    state["stages"][stage]["note"] = note
    state["current_stage"] = stage


def init_run(args):
    run_id = require_run_id(args.run_id or now_run_id())
    paths = project_paths(run_id)
    if os.path.exists(paths["state"]):
        raise FileExistsError(f"run_id 已存在：{run_id}")
    for key in ("run_dir", "candidate_dir", "images_dir"):
        os.makedirs(paths[key], exist_ok=True)
    state = {
        "version": STATE_VERSION,
        "run_id": run_id,
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": "",
        "image_mode": args.image_mode,
        "current_stage": "copy",
        "script_sha256": None,
        "copy_sha256": None,
        "storyboard_sha256": None,
        "chibi_sha256": None,
        "image_keys": [],
        "image_sha256": {},
        "stages": {
            "copy": {"status": "pending", "note": "等待 Codex 写入候选文案"},
            "storyboard": {"status": "blocked", "note": "文案定稿后可生成"},
            "chibi": {"status": "blocked", "note": "叙事分镜确认后可生成最终输出分镜"},
            "images": {"status": "blocked", "note": "最终输出分镜确认后可生成"},
        },
    }
    save_state(paths, state)
    print(json.dumps({"run_id": run_id, "paths": relative_paths(paths)},
                     ensure_ascii=False, indent=2))


def show_status(args):
    paths, state = load_state(args.run_id)
    print(json.dumps({"state": state, "paths": relative_paths(paths)},
                     ensure_ascii=False, indent=2))


def verify_copy(args):
    paths, state = load_state(args.run_id)
    path = args.file or paths["draft"]
    if not os.path.exists(path):
        raise FileNotFoundError(f"未找到候选文案：{path}")
    import write_long_copy as copy
    with open(path, encoding="utf-8") as f:
        text = f.read()
    problems, chars, blocks = copy.validate(text)
    if problems:
        for problem in problems:
            print("-", problem)
        raise ValueError(f"文案校验失败（{len(problems)} 项）。")
    warnings = copy.warnings_for(blocks, chars)
    state["copy_sha256"] = sha256_file(path)
    mark(state, "copy", "verified", f"{chars} 字，{len(blocks)} 块")
    save_state(paths, state)
    print(f"文案校验通过：{path}（{chars} 字，{len(blocks)} 块）")
    for warning in warnings:
        print("提示：", warning)


def require_current_script(paths, state):
    if not state.get("script_sha256"):
        raise ValueError("尚未确认文案；请先人工确认并执行 promote copy。")
    if not os.path.exists(paths["script"]):
        raise FileNotFoundError("正式 script.txt 不存在。")
    actual = sha256_file(paths["script"])
    if actual != state["script_sha256"]:
        raise ValueError("正式 script.txt 已变化；此 run 的候选分镜不能提升。")


def verify_storyboard(args):
    paths, state = load_state(args.run_id)
    require_current_script(paths, state)
    path = args.file or paths["storyboard"]
    if not os.path.exists(path):
        raise FileNotFoundError(f"未找到候选分镜：{path}")
    import build_long as build
    import write_storyboard as storyboard
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    problems = storyboard.validate_final(data, build.parse_script())
    if problems:
        for problem in problems:
            print("-", problem)
        raise ValueError(f"分镜校验失败（{len(problems)} 项）。")
    count = sum(len(item.get("beats", [])) for item in data.get("blocks", []))
    state["storyboard_sha256"] = sha256_file(path)
    mark(state, "storyboard", "verified", f"{count} 拍，绑定 script.txt 哈希")
    save_state(paths, state)
    print(f"分镜校验通过：{path}（{count} 拍）")


def verify_chibi(args):
    paths, state = load_state(args.run_id)
    require_current_script(paths, state)
    require_current_storyboard(paths, state)
    path = args.file or paths["chibi"]
    if not os.path.exists(path):
        raise FileNotFoundError(f"未找到候选最终输出分镜：{path}")
    import write_chibi_prompts as chibi
    with open(paths["active_storyboard"], encoding="utf-8") as f:
        story = json.load(f)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    problems = chibi.validate_final(data, story, chibi.load_characters())
    if problems:
        for problem in problems:
            print("-", problem)
        raise ValueError(f"最终输出分镜校验失败（{len(problems)} 项）。")
    count = sum(len(item.get("beats", [])) for item in data.get("blocks", []))
    state["chibi_sha256"] = sha256_file(path)
    mark(state, "chibi", "verified", f"最终输出分镜 {count} 拍")
    save_state(paths, state)
    print(f"最终输出分镜校验通过：{path}（{count} 拍）")


def set_image_mode(args):
    """切换候选图片所读的正式分镜，保留已有候选文件但使其失效。"""
    paths, state = load_state(args.run_id)
    if state["stages"]["images"]["status"] == "promoted":
        raise ValueError("正式图片已提升，不能切换图片模式；请创建新 run。")
    mode = args.image_mode
    state["image_mode"] = mode
    state["image_keys"] = []
    state["image_sha256"] = {}
    if mode == "chibi":
        if state["stages"]["chibi"]["status"] == "promoted":
            mark(state, "images", "pending", "已切换为最终输出分镜，待列出候选图片任务")
        else:
            mark(state, "images", "blocked", "待确认并提升 storyboard_output.json")
    elif state["stages"]["storyboard"]["status"] == "promoted":
        mark(state, "images", "pending", "兼容叙事分镜图片模式，待列出候选图片任务")
    else:
        mark(state, "images", "blocked", "待确认叙事分镜")
    save_state(paths, state)
    print(f"图片模式已切换为 {mode}；既有候选图片保留但不再属于当前待提升集合。")


def invalidate_output(args):
    """因视觉规则或角色计划改变，使已提升的最终输出分镜失效。"""
    paths, state = load_state(args.run_id)
    if state["stages"]["images"]["status"] == "promoted":
        raise ValueError("正式图片已提升，不能使最终分镜失效；请创建新 run。")
    state["chibi_sha256"] = None
    state["image_keys"] = []
    state["image_sha256"] = {}
    mark(state, "chibi", "pending", "视觉规则已变化，待重新生成并确认 storyboard_output.json")
    mark(state, "images", "blocked", "待重新确认 storyboard_output.json")
    save_state(paths, state)
    print("最终输出分镜已标记失效；既有候选图片保留但不能提升。")


def image_source(paths, state):
    if state["image_mode"] == "chibi":
        require_current_chibi(paths, state)
        return paths["active_chibi"]
    require_current_storyboard(paths, state)
    return paths["active_storyboard"]


def require_current_storyboard(paths, state):
    if state["stages"]["storyboard"]["status"] != "promoted":
        raise ValueError("请先确认并提升正式叙事分镜，再继续。")
    require_verified_file(state, "storyboard_sha256", paths["active_storyboard"],
                          "正式分镜")


def require_current_chibi(paths, state):
    if state["stages"]["chibi"]["status"] != "promoted":
        raise ValueError("请先确认并提升正式 Q 版分镜，再生成候选图片。")
    require_verified_file(state, "chibi_sha256", paths["active_chibi"],
                          "正式 Q 版分镜")


def load_image_targets(paths, state, requested=None):
    source = image_source(paths, state)
    if not os.path.exists(source):
        raise FileNotFoundError("请先确认并提升图片对应的正式分镜。")
    with open(source, encoding="utf-8") as f:
        data = json.load(f)
    wanted = set(requested or [])
    targets = []
    for block in data.get("blocks", []):
        bi = int(block["block_idx"])
        for beat in block.get("beats", []):
            idx = int(beat["beat_idx"])
            key = f"{bi:02d}_{idx}"
            prompt = (beat.get("final_image_prompt") if
                      state["image_mode"] == "chibi" else beat.get("prompt"))
            if not (prompt or "").strip() or (wanted and key not in wanted):
                continue
            if state["image_mode"] == "story":
                # 与万相后备路径共用项目视觉底线与风格变体，避免 Codex 图片
                # 仅拿到原始分镜短提示词而丢失暖色、无文字和字幕安全区约束。
                from write_image_art import style_suffix
                prompt = prompt.strip() + style_suffix(PJ.read_meta())
            targets.append({
                "key": key,
                "prompt": prompt.strip(),
                "shot": beat.get("shot", "medium"),
                "output": os.path.join(paths["images_dir"], key + ".png"),
            })
    if wanted:
        missing = sorted(wanted - {target["key"] for target in targets})
        if missing:
            raise ValueError("分镜中不存在可生成的拍：" + " ".join(missing))
    return targets


def list_image_targets(args):
    paths, state = load_state(args.run_id)
    targets = load_image_targets(paths, state, args.beats)
    state["image_keys"] = [target["key"] for target in targets]
    state["image_sha256"] = {}
    mark(state, "images", "pending", f"待生成 {len(targets)} 张候选图片")
    save_state(paths, state)
    print(json.dumps({"run_id": args.run_id, "image_mode": state["image_mode"],
                      "targets": targets}, ensure_ascii=False, indent=2))


def verify_images(args):
    paths, state = load_state(args.run_id)
    expected = state.get("image_keys") or [target["key"] for target in
                                              load_image_targets(paths, state)]
    if not expected:
        raise ValueError("没有待验收图片；请先运行 image-targets。")
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("图片校验需要 Pillow。") from exc
    errors = []
    hashes = {}
    for key in expected:
        path = os.path.join(paths["images_dir"], key + ".png")
        if not os.path.exists(path):
            errors.append(f"缺少 {key}.png")
            continue
        try:
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                width, height = image.size
        except Exception as exc:
            errors.append(f"{key}.png 无法解码：{exc}")
            continue
        if not width or not height or abs(width / height - 16 / 9) > 0.025:
            errors.append(f"{key}.png 不是 16:9（{width}x{height}）")
            continue
        hashes[key] = sha256_file(path)
    if errors:
        for error in errors:
            print("-", error)
        raise ValueError(f"候选图片校验失败（{len(errors)} 项）。")
    state["image_sha256"] = hashes
    mark(state, "images", "verified", f"{len(expected)} 张均可解码且为 16:9")
    save_state(paths, state)
    print(f"候选图片校验通过：{len(expected)} 张。")
    print("下一步：运行 write_image_art.py --tone-check 进行正式目录的色调检查，"
          "或人工审阅候选图后 promote images。")


def safe_copy(source, target, replace, run_id):
    if os.path.exists(target):
        if not replace:
            raise FileExistsError(f"正式资产已存在，拒绝覆盖：{target}（需 --replace）")
        backup = target + f".bak.{run_id}"
        shutil.copy2(target, backup)
        print(f"已备份：{backup}")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.copy2(source, target)


def require_verified_file(state, field, path, label):
    expected = state.get(field)
    if not expected or not os.path.exists(path) or sha256_file(path) != expected:
        raise ValueError(f"{label} 在校验后发生变化，请重新校验再提升。")


def promote(args):
    paths, state = load_state(args.run_id)
    kind = "chibi" if args.stage == "output" else args.stage
    if state["stages"][kind]["status"] != "verified":
        raise ValueError(f"{kind} 尚未通过离线校验，不能提升。")
    if kind == "copy":
        require_verified_file(state, "copy_sha256", paths["draft"], "候选文案")
        import write_long_copy as copy
        copy.accept(paths["draft"])
        state["script_sha256"] = sha256_file(paths["script"])
        mark(state, "copy", "promoted", "已人工确认并定稿 script.txt")
        mark(state, "storyboard", "pending", "可生成候选分镜")
    elif kind == "storyboard":
        require_current_script(paths, state)
        require_verified_file(state, "storyboard_sha256", paths["storyboard"],
                              "候选分镜")
        safe_copy(paths["storyboard"], paths["active_storyboard"],
                  args.replace, args.run_id)
        mark(state, "storyboard", "promoted", "已人工确认并提升正式分镜")
        mark(state, "chibi", "pending", "可生成候选最终输出分镜 storyboard_output.json")
        if state["image_mode"] == "chibi":
            mark(state, "images", "blocked", "待确认并提升 storyboard_output.json")
        else:
            mark(state, "images", "pending", "兼容叙事分镜图片模式，可生成候选图片")
    elif kind == "chibi":
        require_current_storyboard(paths, state)
        require_verified_file(state, "chibi_sha256", paths["chibi"],
                              "候选 Q 版分镜")
        safe_copy(paths["chibi"], paths["active_chibi"], args.replace, args.run_id)
        mark(state, "chibi", "promoted", "已人工确认并提升正式 storyboard_output.json")
        if state["image_mode"] == "chibi":
            mark(state, "images", "pending", "可基于最终输出分镜生成候选图片")
    else:
        expected = state.get("image_keys")
        if not expected:
            raise ValueError("请先运行 image-targets，再提升图片。")
        for key in expected:
            source = os.path.join(paths["images_dir"], key + ".png")
            if state.get("image_sha256", {}).get(key) != sha256_file(source):
                raise ValueError(f"候选图片 {key}.png 在校验后发生变化，请重新校验。")
            safe_copy(source,
                      os.path.join(paths["active_images"], key + ".png"),
                      args.replace, args.run_id)
        mark(state, "images", "promoted", f"已提升 {len(expected)} 张正式图片")
    save_state(paths, state)
    print(f"已提升 {kind}。任务摘要：{paths['summary']}")


def main():
    parser = argparse.ArgumentParser(description="Codex 原生制作任务接口（纯本地）")
    parser.add_argument("--project", help="项目 id，默认取 PROJECT 或 001")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="创建可恢复的 Codex run")
    init.add_argument("--run-id")
    init.add_argument("--image-mode", choices=("story", "chibi"), default="chibi")
    init.set_defaults(func=init_run)

    status = sub.add_parser("status", help="显示 run 状态与候选路径")
    status.add_argument("run_id")
    status.set_defaults(func=show_status)

    copy = sub.add_parser("verify-copy", help="校验候选文案")
    copy.add_argument("run_id")
    copy.add_argument("--file")
    copy.set_defaults(func=verify_copy)

    story = sub.add_parser("verify-storyboard", help="校验候选叙事分镜")
    story.add_argument("run_id")
    story.add_argument("--file")
    story.set_defaults(func=verify_storyboard)

    chibi = sub.add_parser("verify-chibi", help="校验候选 Q 版分镜")
    chibi.add_argument("run_id")
    chibi.add_argument("--file")
    chibi.set_defaults(func=verify_chibi)

    output = sub.add_parser("verify-output", help="校验候选最终输出分镜 storyboard_output.json")
    output.add_argument("run_id")
    output.add_argument("--file")
    output.set_defaults(func=verify_chibi)

    mode = sub.add_parser("set-image-mode", help="切换图片读取的正式分镜，不删除候选图片")
    mode.add_argument("run_id")
    mode.add_argument("image_mode", choices=("story", "chibi"))
    mode.set_defaults(func=set_image_mode)

    invalidate = sub.add_parser("invalidate-output", help="视觉规则变化后使最终输出分镜失效")
    invalidate.add_argument("run_id")
    invalidate.set_defaults(func=invalidate_output)

    targets = sub.add_parser("image-targets", help="列出逐拍候选生图任务")
    targets.add_argument("run_id")
    targets.add_argument("--beats", nargs="+", help="试点拍，如 00_0 00_1")
    targets.set_defaults(func=list_image_targets)

    images = sub.add_parser("verify-images", help="校验候选图片的完整性和比例")
    images.add_argument("run_id")
    images.set_defaults(func=verify_images)

    promote_parser = sub.add_parser("promote", help="人工确认后提升候选资产")
    promote_parser.add_argument("run_id")
    promote_parser.add_argument("stage", choices=("copy", "storyboard", "chibi", "output", "images"))
    promote_parser.add_argument("--replace", action="store_true",
                                help="允许覆盖正式资产，并先创建 .bak.<run_id> 备份")
    promote_parser.set_defaults(func=promote)

    args = parser.parse_args()
    if args.project:
        PJ.CURRENT_ID = args.project
    try:
        args.func(args)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
