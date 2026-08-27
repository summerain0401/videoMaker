#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Provider-neutral workflow contracts, validation, and image-task assembly."""

import json
import os
import re


CONTENT_STAGES = ("topic", "copy", "script", "storyboard")
APPROVAL_STAGES = CONTENT_STAGES + ("images",)
ALL_STAGES = APPROVAL_STAGES + ("voice", "render", "qa")
STAGE_STATES = {
    "pending", "awaiting_external", "generated", "verified",
    "promoted", "failed", "blocked",
}
SEGMENTS = {"hook", "insight", "action"}
SHOTS = {"wide", "medium", "close"}
FORBIDDEN_STORYBOARD_FIELDS = {
    "provider", "model", "final_image_prompt", "negative_prompt",
    "prompt_en", "api_request",
}
DEFAULT_PROVIDERS = {
    "llm": {"name": "codex", "model": None},
    "image": {"name": "imagegen", "model": None},
    "speech": {
        "name": "azure",
        "voice": "zh-CN-Xiaochen:DragonHDFlashLatestNeural",
    },
}
NEGATIVE_PROMPT = (
    "dense text, multiple sentences, paragraphs, long captions, subtitles, "
    "crowded labels, dense UI, dense chart, text-heavy infographic, "
    "illegible or gibberish text, logo, watermark, sticker, speech bubble, "
    "frame, border, bottom bar, letterbox, extra fingers, malformed hands, "
    "duplicated person"
)


def phase_identity(block):
    """解析 PHASE 编号和标题；普通块返回 (None, None)。"""
    if block.get("type") != "PHASE":
        return None, None
    match = re.fullmatch(
        r"PHASE\s+(\d{1,2})\s*(?:·|\-|—)?\s*(.+)",
        str(block.get("head") or "").strip())
    if not match:
        raise ValueError(f"无法解析 PHASE 标题：{block.get('head')}")
    return int(match.group(1)), match.group(2).strip()


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def normalize_providers(raw=None):
    raw = raw or {}
    if not isinstance(raw, dict):
        raw = {}
    out = json.loads(json.dumps(DEFAULT_PROVIDERS))
    for group in out:
        value = raw.get(group)
        if isinstance(value, dict):
            out[group].update(value)
    return out


def validate_providers(providers, llm_names, image_names):
    problems = []
    raw = providers or {}
    if not isinstance(raw, dict):
        return ["providers 必须是 JSON object"]
    allowed_groups = {"llm", "image", "speech"}
    unknown_groups = set(raw) - allowed_groups
    if unknown_groups:
        problems.append("providers 含未知分组：" + ", ".join(sorted(unknown_groups)))
    allowed_fields = {
        "llm": {"name", "model"},
        "image": {"name", "model"},
        "speech": {"name", "voice"},
    }
    for group, fields in allowed_fields.items():
        value = raw.get(group)
        if isinstance(value, dict):
            unknown = set(value) - fields
            if unknown:
                problems.append(
                    f"providers.{group} 禁止阶段覆盖/未知字段："
                    + ", ".join(sorted(unknown)))
    providers = normalize_providers(providers)
    if providers["llm"].get("name") not in llm_names:
        problems.append(f"未知 LLM provider：{providers['llm'].get('name')}")
    if providers["image"].get("name") not in image_names:
        problems.append(f"未知图片 provider：{providers['image'].get('name')}")
    if providers["speech"].get("name") != "azure":
        problems.append("speech provider 必须为 azure")
    if not isinstance(providers["speech"].get("voice"), str) or \
            not providers["speech"]["voice"].strip():
        problems.append("Azure voice 不能为空")
    for group in ("llm", "image"):
        model = providers[group].get("model")
        if model is not None and not isinstance(model, str):
            problems.append(f"providers.{group}.model 必须为字符串或 null")
    return problems


def validate_topic(data, require_selection=True):
    problems = []
    if not isinstance(data, dict):
        return ["topic 必须是 JSON object"]
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ["topic.candidates 必须是非空数组"]
    ids = set()
    required = ("id", "book_title", "author", "angle", "audience_promise",
                "video_title", "rationale")
    for i, item in enumerate(candidates):
        if not isinstance(item, dict):
            problems.append(f"候选 {i} 不是 object")
            continue
        for key in required:
            if not str(item.get(key) or "").strip():
                problems.append(f"候选 {i} 缺少 {key}")
        cid = item.get("id")
        if not isinstance(cid, str):
            problems.append(f"候选 {i} id 必须是字符串")
            continue
        if cid in ids:
            problems.append(f"候选 id 重复：{cid}")
        ids.add(cid)
    selected = data.get("selected_id")
    if require_selection and selected not in ids:
        problems.append("selected_id 必须指向一个候选")
    return problems


def selected_topic(data):
    selected = data.get("selected_id")
    return next((x for x in data.get("candidates", [])
                 if x.get("id") == selected), None)


def validate_copy(data):
    problems = []
    if not isinstance(data, dict):
        return ["copy 必须是 JSON object"]
    for key in ("thesis", "audience_promise"):
        if not str(data.get(key) or "").strip():
            problems.append(f"copy 缺少 {key}")
    claims = data.get("claims")
    if not isinstance(claims, list) or not claims:
        problems.append("copy.claims 必须是非空数组")
    sections = data.get("sections")
    if not isinstance(sections, list) or len(sections) != 5:
        problems.append("copy.sections 必须恰好包含五个阶段")
    else:
        for i, section in enumerate(sections):
            if not isinstance(section, dict):
                problems.append(f"copy.sections[{i}] 必须是 object")
                continue
            if not str(section.get("name") or "").strip():
                problems.append(f"copy.sections[{i}] 缺少 name")
            if not str(section.get("objective") or "").strip():
                problems.append(f"copy.sections[{i}] 缺少 objective")
            if not isinstance(section.get("key_points"), list) or \
                    not section["key_points"]:
                problems.append(f"copy.sections[{i}] 缺少 key_points")
            if not isinstance(section.get("examples"), list):
                problems.append(f"copy.sections[{i}].examples 必须是数组")
            if not str(section.get("action") or "").strip():
                problems.append(f"copy.sections[{i}] 缺少 action")
    return problems


def _walk_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def validate_storyboard(data, script_blocks=None, known_character_ids=None,
                        enforce_density=True):
    problems = []
    if not isinstance(data, dict):
        return ["storyboard 必须是 JSON object"]
    forbidden = FORBIDDEN_STORYBOARD_FIELDS.intersection(_walk_keys(data))
    if forbidden:
        problems.append("语义分镜含模型专用字段：" + ", ".join(sorted(forbidden)))
    blocks = data.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        return problems + ["storyboard.blocks 必须是非空数组"]
    indexes = [b.get("block_idx") for b in blocks if isinstance(b, dict)]
    if not all(isinstance(value, int) for value in indexes):
        problems.append("block_idx 必须是整数")
    valid_indexes = [value for value in indexes if isinstance(value, int)]
    if len(valid_indexes) != len(set(valid_indexes)):
        problems.append("block_idx 重复")
    if script_blocks is not None and len(blocks) != len(script_blocks):
        problems.append(
            f"分镜块数 {len(blocks)} 与剧本块数 {len(script_blocks)} 不一致")
    for pos, block in enumerate(blocks):
        if not isinstance(block, dict):
            problems.append(f"块 {pos} 不是 object")
            continue
        bi = block.get("block_idx")
        if bi != pos:
            problems.append(f"块 {pos} 的 block_idx 应为 {pos}，实际 {bi}")
        subtitles = block.get("subtitles") or []
        beats = block.get("beats") or []
        if not isinstance(subtitles, list):
            problems.append(f"块 {pos} subtitles 必须是数组")
            subtitles = []
        if not isinstance(beats, list):
            problems.append(f"块 {pos} beats 必须是数组")
            beats = []
        raw_voice_chars = block.get("voice_chars", 0)
        if not isinstance(raw_voice_chars, int) or raw_voice_chars < 0:
            problems.append(f"块 {pos} voice_chars 必须是非负整数")
            voice_chars = 0
        else:
            voice_chars = raw_voice_chars
        script_voice = None
        if script_blocks is not None and pos < len(script_blocks):
            expected = script_blocks[pos]
            script_voice = expected.get("voice") or ""
            if block.get("type") != expected.get("type"):
                problems.append(f"块 {pos} type 与剧本不一致")
            if block.get("head") != expected.get("head"):
                problems.append(f"块 {pos} head 与剧本不一致")
            if voice_chars != len(script_voice):
                problems.append(f"块 {pos} voice_chars 与剧本不一致")
        if not beats:
            problems.append(f"块 {pos} 必须至少包含一拍")
        if block.get("type") == "PHASE" and len(beats) != 1:
            problems.append(f"块 {pos} PHASE 必须且只能包含一拍")
        if enforce_density and block.get("type") != "PHASE" and voice_chars > 0:
            minimum = 1 if voice_chars <= 120 else 1 + ((voice_chars - 120 + 99) // 100)
            if len(beats) < minimum:
                problems.append(f"块 {pos} 口播 {voice_chars} 字至少需要 {minimum} 拍")
            # 图片任务一拍对应一张候选图。允许多一拍处理真实的语义转折，
            # 但不能把每个短句机械拆成一张图，避免生成成本随句号失控。
            maximum = minimum + 1
            if len(beats) > maximum:
                problems.append(
                    f"块 {pos} 口播 {voice_chars} 字至多允许 {maximum} 拍；"
                    "请合并连续语义，避免逐句一图")
        if voice_chars and not subtitles:
            problems.append(f"块 {pos} 有口播但无 subtitles")
        if not all(isinstance(s, dict) for s in subtitles):
            problems.append(f"块 {pos} subtitles 含非 object 项")
            subtitles = [s for s in subtitles if isinstance(s, dict)]
        subtitle_ids = [s.get("id") for s in subtitles]
        if not all(isinstance(value, int) for value in subtitle_ids):
            problems.append(f"块 {pos} subtitle id 必须是整数")
        sub_ids = {value for value in subtitle_ids if isinstance(value, int)}
        if subtitle_ids != list(range(len(subtitles))):
            problems.append(f"块 {pos} subtitle id 必须从 0 连续编号")
        if subtitles:
            if subtitles[0].get("start_char") != 0 or \
                    subtitles[-1].get("end_char") != voice_chars:
                problems.append(f"块 {pos} 字幕未覆盖全文")
            for i in range(1, len(subtitles)):
                if subtitles[i].get("start_char") != \
                        subtitles[i - 1].get("end_char"):
                    problems.append(f"块 {pos} 字幕区间不连续")
                    break
            for subtitle in subtitles:
                start = subtitle.get("start_char")
                end = subtitle.get("end_char")
                text = subtitle.get("text")
                if not isinstance(text, str) or not isinstance(start, int) or \
                        not isinstance(end, int) or end - start != len(text):
                    problems.append(f"块 {pos} 字幕 {subtitle.get('id')} 文本与区间不符")
            if script_voice is not None and \
                    "".join(s.get("text") or "" for s in subtitles) != script_voice:
                problems.append(f"块 {pos} 字幕文本与剧本口播不一致")
        beat_ids = []
        covered_sentence_ids = []
        for beat in beats:
            if not isinstance(beat, dict):
                problems.append(f"块 {pos} beats 含非 object 项")
                continue
            beat_ids.append(beat.get("beat_idx"))
            if not str(beat.get("visual_description") or "").strip():
                problems.append(
                    f"块 {pos} 拍 {beat.get('beat_idx')} 缺少 visual_description")
            if beat.get("shot") not in SHOTS:
                problems.append(f"块 {pos} 拍 {beat.get('beat_idx')} shot 非法")
            if beat.get("segment") not in SEGMENTS:
                problems.append(f"块 {pos} 拍 {beat.get('beat_idx')} segment 非法")
            character_ids = beat.get("character_ids")
            if not isinstance(character_ids, list) or not all(
                    isinstance(value, str) for value in character_ids):
                problems.append(
                    f"块 {pos} 拍 {beat.get('beat_idx')} character_ids 必须是字符串数组")
            elif known_character_ids is not None:
                unknown = set(character_ids) - set(known_character_ids)
                unknown.discard("none")
                if unknown:
                    problems.append(
                        f"块 {pos} 拍 {beat.get('beat_idx')} 未知角色："
                        + ", ".join(sorted(unknown)))
            ids = beat.get("sentence_ids") or []
            if not isinstance(ids, list) or not all(
                    isinstance(value, int) for value in ids):
                problems.append(
                    f"块 {pos} 拍 {beat.get('beat_idx')} sentence_ids 非整数数组")
                ids = []
            if enforce_density and voice_chars and block.get("type") != "PHASE" and not ids:
                problems.append(f"块 {pos} 拍 {beat.get('beat_idx')} 至少覆盖一句字幕")
            if enforce_density and voice_chars and block.get("type") != "PHASE" and len(ids) > 4:
                problems.append(f"块 {pos} 拍 {beat.get('beat_idx')} 最多覆盖 4 句字幕")
            covered_sentence_ids.extend(ids)
            if not set(ids).issubset(sub_ids):
                problems.append(f"块 {pos} 拍 {beat.get('beat_idx')} 引用了未知句子")
            elif ids:
                first = subtitles[ids[0]]
                last = subtitles[ids[-1]]
                if beat.get("start_char") != first.get("start_char") or \
                        beat.get("end_char") != last.get("end_char"):
                    problems.append(
                        f"块 {pos} 拍 {beat.get('beat_idx')} 区间与句子覆盖不一致")
                if enforce_density and beat.get("end_char", 0) - beat.get("start_char", 0) > 120:
                    problems.append(f"块 {pos} 拍 {beat.get('beat_idx')} 覆盖口播超过 120 字")
        if beat_ids != list(range(len(beats))):
            problems.append(f"块 {pos} beat_idx 必须从 0 连续编号")
        if voice_chars and beats:
            expected_ids = [s.get("id") for s in subtitles]
            if covered_sentence_ids != expected_ids:
                problems.append(f"块 {pos} 的拍必须按顺序且恰好覆盖每个句子一次")
            if beats[0].get("start_char") != 0 or \
                    beats[-1].get("end_char") != voice_chars:
                problems.append(f"块 {pos} 拍未覆盖全文")
            for i in range(1, len(beats)):
                if beats[i].get("start_char") != beats[i - 1].get("end_char"):
                    problems.append(f"块 {pos} 拍区间不连续")
                    break
    return problems


def parse_script(text):
    blocks, current = [], None
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("# "):
            head = line[2:].strip()
            current = {"type": head.split()[0], "head": head,
                       "lines": [], "voice": None, "author": None}
            blocks.append(current)
        elif current is not None and line.startswith("## "):
            current["lines"].append(line[3:].strip())
        elif current is not None and line.startswith("voice："):
            current["voice"] = line[len("voice："):].strip()
        elif current is not None and line.startswith("author："):
            current["author"] = line[len("author："):].strip()
    return blocks


def validate_script(text):
    blocks = parse_script(text)
    problems = []
    if not blocks or blocks[0]["type"] != "TITLE":
        problems.append("剧本必须以 # TITLE 开始")
    if not blocks or blocks[-1]["type"] != "END":
        problems.append("剧本必须以 # END 结束")
    phases = [b for b in blocks if b["type"] == "PHASE"]
    if len(phases) != 5:
        problems.append(f"剧本必须包含 5 个 PHASE，实际 {len(phases)}")
    for i, block in enumerate(blocks):
        if block["type"] not in ("PHASE", "END") and not block.get("voice"):
            problems.append(f"块 {i} {block['type']} 缺少 voice：")
    voice_chars = sum(len(b.get("voice") or "") for b in blocks)
    if not 1000 <= voice_chars <= 8000:
        problems.append(f"口播总字数异常：{voice_chars}")
    return problems, voice_chars, blocks


def build_image_tasks(storyboard, project_meta, characters, images_dir):
    visual = project_meta.get("visual_style") or {}
    raw_characters = characters.get("characters", characters)
    if isinstance(raw_characters, list):
        char_map = {c["id"]: c for c in raw_characters}
    else:
        char_map = raw_characters
    style = visual.get("art_direction") or visual.get("variant") or \
        "clear narrative 2D illustration"
    palette = visual.get("palette") or "colors follow the narrative emotion"
    tasks = []
    for block in storyboard.get("blocks", []):
        phase_number, phase_title = phase_identity(block)
        if phase_number is not None and len(block.get("beats", [])) != 1:
            raise ValueError(
                f"PHASE {phase_number:02d} 必须且只能包含一个图片任务")
        for beat in block.get("beats", []):
            description = (beat.get("visual_description") or "").strip()
            if not description:
                continue
            is_phase = phase_number is not None
            key = (f"phase_{phase_number:02d}" if is_phase else
                   f"{int(block['block_idx']):02d}_{int(beat['beat_idx'])}")
            char_bits = []
            for char_id in beat.get("character_ids", []):
                if char_id == "none":
                    continue
                char = char_map.get(char_id)
                if not char:
                    raise ValueError(f"ImageTask 引用了未知角色：{char_id}")
                identity = char.get("prompt") or char.get("description") or char_id
                anchor = char.get("anchor") or ""
                char_bits.append(", ".join(x for x in (identity, anchor) if x))
            text_policy = (
                f'chapter-opening image; render the exact simplified-Chinese '
                f'title "{phase_title}" verbatim as a prominent physical part '
                "of the depicted world—such as lettering engraved, painted, "
                "printed or mounted on the most semantically natural object or "
                "architectural surface; make the lettering follow that object's "
                "perspective, material, lighting and contact shadows; the title "
                "must be immediately legible and contain no missing, incorrect "
                "or extra characters; do not write PHASE or add other readable "
                "text; never use a floating overlay, generic title card, separate "
                "banner, lower-third, subtitle, UI panel or watermark"
                if is_phase else
                "semantically useful in-scene text is allowed when it helps the "
                "viewer: one short headline or key phrase plus a few concise "
                "labels, prices or numbers; keep text easy to scan and visually "
                "secondary, normally no more than about 6 short groups and under "
                "20 percent of the frame; avoid paragraphs or dense text layouts"
            )
            prompt = ", ".join(x for x in [
                style, palette, description,
                "characters: " + "; ".join(char_bits) if char_bits else "",
                f"{beat.get('shot', 'medium')} shot",
                f"emotion: {beat.get('emotion', 'neutral')}",
                text_policy,
                "16:9 horizontal, 1920x1080, full-bleed, clean readable subject; "
                "compose as a continuous full-frame scene with no reserved caption "
                "panel or empty bottom band; keep critical faces and indispensable "
                "semantic details away from the bottom-center subtitle line while "
                "allowing natural scenery and texture to continue to every edge; "
                "no logo or watermark",
            ] if x)
            tasks.append({
                "key": key,
                "kind": "phase_title" if is_phase else "scene",
                "title_text": phase_title if is_phase else None,
                "block_idx": block["block_idx"],
                "beat_idx": beat["beat_idx"],
                "prompt": prompt,
                "negative_prompt": NEGATIVE_PROMPT,
                "size": [1920, 1080],
                "output_path": os.path.join(images_dir, key + ".png"),
                "reference_images": [],
            })
    return tasks


def safe_project_suffix(title):
    value = re.sub(r"[\\/:*?\"<>|]", "", str(title or "")).strip()
    return value[:48] or "新项目"
