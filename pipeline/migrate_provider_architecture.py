#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-time migration of V5 projects to provider-neutral formal contracts."""

import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import proj as PJ
from workflow_contracts import (
    DEFAULT_PROVIDERS, parse_script, read_json, validate_copy,
    validate_storyboard, write_json,
)


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _brief_values(text):
    values, current = {}, None
    for raw in text.splitlines():
        if raw.startswith("## "):
            current = raw[3:].split("（", 1)[0].strip()
            values[current] = []
        elif current and raw.strip() and not raw.startswith("#"):
            values[current].append(raw.strip().lstrip("- "))
    return {key: "".join(value).strip() for key, value in values.items()}


def _topic(meta, brief, script_blocks):
    values = _brief_values(brief)
    title_block = script_blocks[0] if script_blocks else {"lines": []}
    lines = title_block.get("lines") or []
    book = values.get("书目") or meta.get("title") or (lines[0] if lines else "")
    book = book.strip("《》")
    video_title = values.get("视频标题") or (lines[1] if len(lines) > 1 else book)
    angle = values.get("核心痛点") or video_title
    audience = values.get("目标受众") or "希望获得可执行认知升级的中文观众"
    return {
        "id": "migration-1", "book_title": book,
        "author": values.get("作者") or meta.get("author") or "",
        "angle": angle, "audience_promise": audience,
        "video_title": video_title,
        "rationale": "由 V5 brief 与正式剧本确定性回填，未重新调用 LLM。",
        "source": "migration",
    }


def _copy(topic, blocks):
    sections, current = [], None
    claims = []
    for block in blocks:
        if block["type"] == "PHASE":
            current = {"name": block["head"], "objective": "",
                       "key_points": [], "examples": [], "action": ""}
            sections.append(current)
            continue
        if current is None:
            continue
        points = [x for x in block.get("lines", []) if x]
        if not points and block.get("head"):
            points = [block["head"]]
        current["key_points"].extend(points)
        claims.extend(points)
        if block["type"] == "STEPS" and points:
            current["action"] = "；".join(points)
    for section in sections:
        if not section["key_points"]:
            section["key_points"] = [section["name"]]
        section["objective"] = section["key_points"][0]
        if not section["action"]:
            section["action"] = "把本阶段认知转化为一个可执行选择。"
    data = {
        "thesis": topic["angle"],
        "audience_promise": topic["audience_promise"],
        "claims": claims or [topic["angle"]],
        "sections": sections,
        "source": "migration",
    }
    problems = validate_copy(data)
    if problems:
        raise ValueError("copy 迁移失败：" + "；".join(problems))
    return data


def _segment_for(block_idx, blocks):
    phase = 0
    for index, block in enumerate(blocks):
        if index > block_idx:
            break
        if block["type"] == "PHASE":
            phase += 1
    if phase <= 1:
        return "hook"
    if phase <= 3:
        return "insight"
    return "action"


def _fill_descriptions(storyboard):
    """为旧 PHASE/END 空拍补确定性语义描述，不生成模型 Prompt。"""
    for block in storyboard.get("blocks", []):
        for beat in block.get("beats", []):
            if str(beat.get("visual_description") or "").strip():
                continue
            if block.get("type") == "PHASE":
                beat["visual_description"] = (
                    f"章节过渡画面：{block.get('head', '')}，以环境和光线变化承接前后叙事。")
            elif block.get("type") == "END":
                beat["visual_description"] = "全片收束画面，人物走向开阔远景，留下思考余韵。"
            else:
                beat["visual_description"] = (
                    f"围绕“{block.get('head', '')}”呈现清晰的叙事场景。")
    return storyboard


def _storyboard(narrative, output, script_blocks):
    output_map = {}
    for block in (output or {}).get("blocks", []):
        for beat in block.get("beats", []):
            output_map[(block.get("block_idx"), beat.get("beat_idx"))] = beat
    migrated = {"version": 1, "source": "migration", "blocks": []}
    for block in narrative.get("blocks", []):
        block_idx = block["block_idx"]
        beats = []
        for beat in block.get("beats", []):
            enriched = output_map.get((block_idx, beat.get("beat_idx")), {})
            char_ids = enriched.get("character_ids") or beat.get("character_ids")
            if not char_ids:
                single = enriched.get("character_id") or beat.get("character_id")
                char_ids = [single] if single else []
            beats.append({
                "beat_idx": len(beats),
                "shot": enriched.get("shot") or beat.get("shot") or "medium",
                "visual_description": (
                    enriched.get("visual_description") or
                    enriched.get("original_cn") or
                    beat.get("visual_description") or beat.get("prompt") or ""
                ),
                "sentence_ids": beat.get("sentence_ids") or [],
                "start_char": int(beat.get("start_char") or 0),
                "end_char": int(beat.get("end_char") or 0),
                "character_ids": char_ids,
                "emotion": enriched.get("emotion") or beat.get("emotion") or "neutral",
                "segment": enriched.get("segment") or beat.get("segment") or
                _segment_for(block_idx, script_blocks),
            })
        migrated["blocks"].append({
            "block_idx": block_idx,
            "type": block.get("type") or script_blocks[block_idx]["type"],
            "head": block.get("head") or script_blocks[block_idx]["head"],
            "voice_chars": int(block.get("voice_chars") or 0),
            "subtitles": block.get("subtitles") or [],
            "beats": beats,
        })
    _fill_descriptions(migrated)
    # 旧项目迁移保持原有镜头键与内容；新生成/校验的分镜执行镜头密度契约。
    problems = validate_storyboard(
        migrated, script_blocks, enforce_density=False,
        enforce_visual_diversity=False)
    if problems:
        raise ValueError("storyboard 迁移失败：" + "；".join(problems[:20]))
    return migrated


def migrate_project(project):
    input_dir = os.path.join(project, "input")
    meta_path = os.path.join(project, "project.json")
    script_path = os.path.join(input_dir, "script.txt")
    narrative_path = os.path.join(input_dir, "storyboard_narrative.json")
    formal_story = os.path.join(input_dir, "storyboard.json")
    archive = os.path.join(project, "archive", "pre_provider_refactor")
    request_path = os.path.join(input_dir, "topic_request.md")
    brief_path = os.path.join(input_dir, "brief.md")
    if not os.path.exists(request_path) and os.path.exists(brief_path):
        brief_text = _read(brief_path)
        brief_text = re.sub(r"^# .*?$", "# 选题需求", brief_text,
                            count=1, flags=re.MULTILINE)
        brief_text = re.sub(
            r"\n在这里填写.*?临时覆盖。\n", "\n", brief_text,
            count=1, flags=re.DOTALL)
        with open(request_path, "w", encoding="utf-8") as handle:
            handle.write(brief_text.rstrip() + "\n")
    if os.path.exists(formal_story) and not os.path.exists(narrative_path):
        storyboard = _fill_descriptions(read_json(formal_story))
        write_json(formal_story, storyboard)
        return {"project": project, "status": "already_migrated"}
    if not os.path.exists(narrative_path):
        raise FileNotFoundError(f"缺少旧叙事分镜：{narrative_path}")

    meta = read_json(meta_path)
    script_text = _read(script_path)
    blocks = parse_script(script_text)
    narrative = read_json(narrative_path)
    output_path = os.path.join(input_dir, "storyboard_output.json")
    output = read_json(output_path) if os.path.exists(output_path) else None

    topic = _topic(meta, _read(brief_path), blocks)
    copy = _copy(topic, blocks)
    storyboard = _storyboard(narrative, output, blocks)
    old_beat_count = sum(len(x.get("beats", []))
                         for x in narrative.get("blocks", []))
    new_beat_count = sum(len(x.get("beats", []))
                         for x in storyboard.get("blocks", []))
    image_keys = sorted(
        os.path.splitext(os.path.basename(path))[0]
        for path in glob.glob(os.path.join(project, "assets", "scenes", "*.png"))
        if re.fullmatch(r"\d{2}_\d+", os.path.splitext(os.path.basename(path))[0])
    )

    os.makedirs(archive, exist_ok=True)
    archived = []
    for pattern in ("storyboard_narrative.json*", "storyboard_output.json*"):
        for source in sorted(glob.glob(os.path.join(input_dir, pattern))):
            target = os.path.join(archive, os.path.basename(source))
            if not os.path.exists(target):
                shutil.copy2(source, target)
            os.remove(source)
            archived.append(os.path.basename(source))

    write_json(os.path.join(input_dir, "topic.json"), topic)
    write_json(os.path.join(input_dir, "copy.json"), copy)
    write_json(formal_story, storyboard)
    meta["providers"] = json.loads(json.dumps(DEFAULT_PROVIDERS))
    write_json(meta_path, meta)
    manifest = {
        "version": 1, "source": "migration", "project_id": meta.get("id"),
        "script_sha256_before": _sha256_text(script_text),
        "script_sha256_after": _sha256_text(_read(script_path)),
        "blocks_before": len(narrative.get("blocks", [])),
        "blocks_after": len(storyboard.get("blocks", [])),
        "beats_before": old_beat_count, "beats_after": new_beat_count,
        "image_keys": image_keys, "archived": archived,
    }
    write_json(os.path.join(archive, "migration_manifest.json"), manifest)
    return {"project": project, "status": "migrated", "manifest": manifest}


def main():
    parser = argparse.ArgumentParser(description="迁移 V5 项目到可插拔架构")
    parser.add_argument("--project", action="append", required=True,
                        help="项目 id；可重复指定")
    args = parser.parse_args()
    results = []
    for pid in args.project:
        matches = glob.glob(os.path.join(PJ.PROJECTS_DIR, str(pid) + "_*"))
        if len(matches) != 1:
            raise RuntimeError(f"PROJECT={pid} 应匹配一个目录，实际 {len(matches)}")
        results.append(migrate_project(matches[0]))
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
