#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Provider-neutral workflow contracts, validation, and image-task assembly."""

import json
import os
import re
import hashlib
import unicodedata
from collections import Counter
from content_templates import ALLOWED_BLOCK_TYPES, template_names


CONTENT_STAGES = ("topic", "copy", "script", "storyboard")
APPROVAL_STAGES = CONTENT_STAGES + ("storyboard-review", "images", "image-review")
ALL_STAGES = APPROVAL_STAGES + ("voice", "render", "qa")
STAGE_STATES = {
    "pending", "awaiting_external", "generated", "verified",
    "promoted", "failed", "blocked",
}
SEGMENTS = {"hook", "insight", "action"}
SCRIPT_VOICE_CHAR_RANGE = (3800, 4500)
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
    "bottom text, bottom caption, lower-third text, crowded labels, dense UI, "
    "dense chart, text-heavy infographic, "
    "illegible or gibberish text, logo, watermark, sticker, speech bubble, "
    "frame, border, bottom bar, letterbox, extra fingers, malformed hands, "
    "duplicated person"
)

DEFAULT_VISUAL_STYLE = {
    "variant": "Q版2D",
    "art_direction": "cute 2D chibi illustration, oversized head, small body, bold clean outlines, matte flat colors, simple readable shapes",
    "forbidden": "no photorealism, no semi-realistic anatomy, no painterly realism, no 3D render, no glossy anime realism",
    "palette": "warm high-contrast flat colors with soft simple shading",
}


def _normalize_visual_description(value):
    """用于阻断完全相同的视觉描述，保留语义而不做激进 NLP 改写。"""
    return re.sub(r"\s+", "", str(value or "")).strip().lower()


_VISUAL_INDEX_RE = re.compile(r"(?:第\d+块第\d+拍|第\d+拍|块\d+拍|画面\d+|镜头\d+)")
_VISUAL_PLACEHOLDER_RE = re.compile(
    r"(?:标题专属构图|独特场景展示|过渡画面|专属构图|场景展示|画面\d+|"
    r"第\d+块第\d+拍|第\d+号位置|镜头\d+|独特纹理|会议室/驾校/跑道/考场)")
_VISUAL_FORMAT_RE = re.compile(
    r"^场景：(?P<scene>[^；]+)；主体：(?P<subject>[^；]+)；"
    r"动作：(?P<action>[^；]+)；关键物件：(?P<object>[^；]+)$")
_LOCATION_HINTS = {
    "驾校": ("驾校", "教练", "驾驶", "方向盘", "学车"),
    "跑步": ("跑步", "跑道", "操场", "慢跑", "运动"),
    "会议": ("会议", "会议室", "汇报", "投影", "同事"),
    "考试": ("考试", "考场", "试卷", "答题", "考卷"),
    "家中": ("家", "客厅", "卧室", "厨房", "餐桌"),
}
_ACTION_FAMILIES = (
    ("移动", ("走", "跑", "奔", "进入", "离开", "骑", "驾驶", "踩", "迈步")),
    ("操作", ("拿", "握", "翻", "写", "按", "打开", "整理", "操作", "指向", "放", "拉", "擦", "改写")),
    ("交流", ("说", "对话", "交谈", "倾听", "看向", "拥抱", "握手")),
    ("观察", ("看", "凝视", "观察", "阅读", "检查", "注视")),
    ("情绪反应", ("笑", "哭", "叹气", "犹豫", "后退", "停顿", "沉思")),
)


def _action_family(action):
    action = str(action or "")
    for family, words in _ACTION_FAMILIES:
        if any(word in action for word in words):
            return family
    return None


def _visual_content_key(value):
    """移除编号和模板词，用于发现伪造的多样性。"""
    text = _normalize_visual_description(value)
    return _VISUAL_INDEX_RE.sub("", text)


def _visual_similarity_key(value):
    """比较结构化描述的业务内容，排除固定字段标签造成的误报。"""
    text = str(value or "").strip()
    match = _VISUAL_FORMAT_RE.fullmatch(text)
    if match:
        return "|".join(_normalize_visual_description(part)
                        for part in match.groupdict().values())
    return _normalize_visual_description(text)


def _visual_description_problems(value):
    text = str(value or "").strip()
    if not text:
        return ["缺少 visual_description"]
    if _VISUAL_PLACEHOLDER_RE.search(text):
        return ["visual_description 含占位/编号模板"]
    if len(text) < 18:
        return ["visual_description 过短，必须描述可执行画面"]
    match = _VISUAL_FORMAT_RE.fullmatch(text)
    if not match:
        return ["visual_description 必须使用场景：…；主体：…；动作：…；关键物件：…格式"]
    if any(not part.strip() for part in match.groupdict().values()):
        return ["visual_description 四个结构字段均不能为空"]
    return []


def _visual_similarity(left, right):
    """用字符二元组捕捉几乎同一句的改写，短描述不参与近似判断。"""
    if min(len(left), len(right)) < 8:
        return 0.0
    left_pairs = {left[i:i + 2] for i in range(len(left) - 1)}
    right_pairs = {right[i:i + 2] for i in range(len(right) - 1)}
    union = left_pairs | right_pairs
    return len(left_pairs & right_pairs) / len(union) if union else 0.0


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
        if providers[group].get("name") == "antigravity" and model is not None:
            problems.append(
                f"providers.{group} 选择 antigravity 时 model 必须为 null")
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


def validate_copy(data, content_template=None):
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
            elif content_template is not None and section["name"] != template_names(content_template)[i]:
                problems.append(f"copy.sections[{i}] 阶段标题不符合模板")
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
                        enforce_density=True, project_meta=None,
                        enforce_visual_diversity=True, enforce_visual_quality=True):
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
    direct_phase = (project_meta or {}).get("visual_style", {}).get(
        "phase_transition") == "direct"
    seen_visuals = {}
    narrative_beats = []
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
        if not beats and not (block.get("type") == "PHASE" and direct_phase):
            problems.append(f"块 {pos} 必须至少包含一拍")
        if block.get("type") == "PHASE" and direct_phase and beats:
            problems.append(f"块 {pos} direct 阶段不得包含图片拍")
        if block.get("type") == "PHASE" and not direct_phase and len(beats) != 1:
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
            visual = beat.get("visual_description")
            visual_problems = _visual_description_problems(visual) if script_blocks is not None and enforce_visual_quality else ([] if str(visual or "").strip() else ["缺少 visual_description"])
            for issue in visual_problems:
                problems.append(f"块 {pos} 拍 {beat.get('beat_idx')} {issue}")
            if script_blocks is not None and enforce_visual_quality:
                match = _VISUAL_FORMAT_RE.fullmatch(str(visual or "").strip())
                covered_text = "".join(
                    (subtitles[i].get("text") or "") for i in (beat.get("sentence_ids") or [])
                    if isinstance(i, int) and i < len(subtitles))
                if match:
                    scene = match.group("scene").strip()
                    action = match.group("action").strip()
                    emotion = str(beat.get("emotion") or "neutral").strip().lower()
                    family = _action_family(action)
                    if family is None:
                        problems.append(f"块 {pos} 拍 {beat.get('beat_idx')} 动作必须是可见动作")
                    else:
                        narrative_beats.append((pos, block.get("type"), scene,
                                                family, emotion, covered_text))
            visual_key = _normalize_visual_description(beat.get("visual_description"))
            if visual_key:
                content_key = _visual_content_key(visual_key)
                if script_blocks is not None and enforce_visual_quality and content_key in seen_visuals:
                    problems.append(f"视觉描述去除编号后重复：块 {pos} 拍 {beat.get('beat_idx')} 与 {seen_visuals[content_key]} 相同")
                if visual_key in seen_visuals:
                    problems.append(
                        f"视觉描述重复：块 {pos} 拍 {beat.get('beat_idx')} 与"
                        f" {seen_visuals[visual_key]} 相同")
                else:
                    near = (next(
                        (location for prior, location in seen_visuals.items()
                         if _visual_similarity(_visual_similarity_key(visual_key),
                                               _visual_similarity_key(prior)) >= 0.78),
                        None) if enforce_visual_diversity and enforce_density else None)
                    if near:
                        problems.append(
                            f"视觉描述高度相似：块 {pos} 拍 {beat.get('beat_idx')} 与"
                            f" {near} 相似，必须改为不同场景、动作或关键物件")
                    seen_visuals[visual_key] = f"块 {pos} 拍 {beat.get('beat_idx')}"
                    if script_blocks is not None:
                        seen_visuals.setdefault(content_key, f"块 {pos} 拍 {beat.get('beat_idx')}")
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
    if enforce_visual_quality and script_blocks is not None:
        count = len(narrative_beats)
        if count >= 10:
            families = Counter(x[3] for x in narrative_beats)
            emotions = Counter(x[4] for x in narrative_beats)
            family_min, family_max = ((4, .55) if count >= 20 else (3, .65))
            emotion_min, emotion_max = ((3, .70) if count >= 20 else (2, .80))
            if len(families) < family_min:
                problems.append(f"动作族分布不足：{count} 拍至少需要 {family_min} 类可见动作")
            if families and max(families.values()) / count > family_max:
                problems.append(f"动作族过度集中：最高占比不得超过 {family_max:.0%}")
            if len(emotions) < emotion_min:
                problems.append(f"情绪分布不足：{count} 拍至少需要 {emotion_min} 种情绪")
            if emotions and max(emotions.values()) / count > emotion_max:
                problems.append(f"情绪过度集中：最高占比不得超过 {emotion_max:.0%}")
        # 同一场景/动作族/情绪连续四拍，通常意味着模板化复用。
        for i in range(3, len(narrative_beats)):
            window = narrative_beats[i - 3:i + 1]
            if len({x[2] for x in window}) == 1 and len({x[3] for x in window}) == 1 and len({x[4] for x in window}) == 1:
                problems.append(f"视觉叙事连续模板化：块 {window[-1][0]} 拍连续 4 拍场景/动作/情绪相同")
                break
        # 口播明确地点时，画面场景必须包含对应地点语义。
        for pos, kind, scene, _action, _emotion, covered in narrative_beats:
            if kind == "TITLE":
                continue
            grounded_text = covered.replace("像考试", "").replace(
                "不是考试", "")
            matched = [(label, hints) for label, hints in _LOCATION_HINTS.items()
                       if any(h in grounded_text for h in hints)]
            if matched and not any(any(h in scene for h in hints)
                                   for _label, hints in matched):
                labels = "、".join(label for label, _hints in matched)
                problems.append(f"块 {pos} 拍地点错配：口播涉及{labels}，场景未落地")
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
            if current["voice"] is None:
                current["voice"] = line[len("voice："):].strip()
            else:
                current.setdefault("voice_count", 1)
                current["voice_count"] += 1
        elif current is not None and line.startswith("author："):
            current["author"] = line[len("author："):].strip()
    return blocks


def validate_script(text, enforce_length=True, content_template=None):
    blocks = parse_script(text)
    problems = []
    if not blocks or blocks[0]["type"] != "TITLE":
        problems.append("剧本必须以 # TITLE 开始")
    if not blocks or blocks[-1]["type"] != "END":
        problems.append("剧本必须以 # END 结束")
    phases = [b for b in blocks if b["type"] == "PHASE"]
    if len(phases) != 5:
        problems.append(f"剧本必须包含 5 个 PHASE，实际 {len(phases)}")
    if content_template is not None:
        expected = template_names(content_template)
        for i, block in enumerate(phases[:5]):
            try:
                number, title = phase_identity(block)
            except ValueError as exc:
                problems.append(str(exc))
                continue
            if number != i + 1 or title != expected[i]:
                problems.append(f"PHASE {i+1:02d} 阶段标题不符合模板")
    for i, block in enumerate(blocks):
        if block.get("voice_count", 0) > 1:
            problems.append(f"块 {i} 含多条 voice：，必须合并为一条")
        if block["type"] not in ("PHASE", "END") and not block.get("voice"):
            problems.append(f"块 {i} {block['type']} 缺少 voice：")
        if content_template is not None and block["type"] not in (
                "TITLE", "PHASE", "END", *ALLOWED_BLOCK_TYPES):
            problems.append(f"块 {i} {block['type']} 不被内容模板支持")
    voice_chars = sum(len(b.get("voice") or "") for b in blocks)
    if enforce_length and not SCRIPT_VOICE_CHAR_RANGE[0] <= voice_chars <= SCRIPT_VOICE_CHAR_RANGE[1]:
        problems.append(f"口播总字数异常：{voice_chars}")
    return problems, voice_chars, blocks


def _build_image_prompt(style, palette, description, char_bits, shot,
                        emotion, text_policy):
    return ", ".join(x for x in [
        style, palette, description,
        "characters: " + "; ".join(char_bits) if char_bits else "",
        f"{shot} shot", f"emotion: {emotion}", text_policy,
        "16:9 horizontal, 1920x1080, full-bleed, clean readable subject; "
        "compose as a continuous full-frame scene with no reserved caption "
        "panel or empty bottom band; never place readable text, titles, labels, "
        "captions or typography in the bottom-center subtitle area; keep "
        "critical faces and indispensable semantic details away from that area while "
        "allowing natural scenery and texture to continue to every edge; "
        "no logo or watermark",
    ] if x)


def build_image_prompt(style, palette, description, char_bits=None,
                       shot="medium", emotion="neutral", text_policy=""):
    """Public deterministic prompt builder for non-storyboard ImageTasks."""
    return _build_image_prompt(style, palette, description, char_bits or [],
                               shot, emotion, text_policy)


def validate_image_task_prompt(task):
    """验证任务 prompt 只能由其结构化来源确定性构造。"""
    manifest = task.get("rule_manifest")
    sources = manifest.get("prompt_sources") if isinstance(manifest, dict) else None
    if not isinstance(sources, dict):
        return ["ImageTask 缺少 rule_manifest.prompt_sources"]
    expected = _build_image_prompt(
        sources.get("style", ""), sources.get("palette", ""),
        sources.get("description", ""), sources.get("char_bits", []),
        sources.get("shot", "medium"), sources.get("emotion", "neutral"),
        sources.get("text_policy", ""))
    problems = []
    if task.get("prompt") != expected:
        problems.append(
            f"ImageTask {task.get('key')} prompt 与 rule_manifest 溯源不一致")
    if manifest.get("negative_prompt") != task.get("negative_prompt"):
        problems.append(
            f"ImageTask {task.get('key')} negative_prompt 与 rule_manifest 溯源不一致")
    structured_policy = manifest.get("text_policy")
    if structured_policy is not None:
        if not isinstance(structured_policy, dict) or structured_policy.get("mode") not in {
                "useful_in_scene", "required_exact", "forbidden"}:
            problems.append(f"ImageTask {task.get('key')} text_policy.mode 无效")
        elif (structured_policy["mode"] == "required_exact" and
              not str(structured_policy.get("exact_text") or "").strip()):
            problems.append(f"ImageTask {task.get('key')} required_exact 缺少 exact_text")
    problems.extend(_image_text_policy_problems(task))
    return problems


_TEXT_BLOCKING_PHRASES = (
    "notext", "withouttext", "novisiblewords", "无文字", "不含文字",
    "不要出现文字", "去除所有文字",
)


def _normalized_prompt_text(value):
    """冲突检查采用 NFKC、小写及空白规整，避免用全角或断词绕过。"""
    value = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(r"\s+", "", value)


def image_text_policy(task):
    """读取结构化文字策略，并兼容尚未带新字段的历史任务包。"""
    manifest = task.get("rule_manifest") if isinstance(task, dict) else {}
    manifest = manifest if isinstance(manifest, dict) else {}
    policy = manifest.get("text_policy")
    if isinstance(policy, dict) and policy.get("mode") in {
            "useful_in_scene", "required_exact", "forbidden"}:
        return dict(policy)
    legacy = manifest.get("text_mode")
    if legacy == "exact_title":
        return {"mode": "required_exact", "exact_text": manifest.get("title_text")}
    if legacy == "forbidden":
        return {"mode": "forbidden"}
    return {"mode": "useful_in_scene"}


def _string_leaves(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _string_leaves(item)
    elif isinstance(value, list):
        for item in value:
            yield from _string_leaves(item)
    elif isinstance(value, str):
        yield value


def _image_text_policy_problems(task):
    """文字允许/必需时，正式任务字段不得含“完全无文字”的相反指令。"""
    policy = image_text_policy(task)
    if policy["mode"] == "forbidden":
        return []
    official = [task.get("prompt", ""), task.get("negative_prompt", ""),
                task.get("rule_manifest", {})]
    normalized = "\n".join(_normalized_prompt_text(item)
                           for value in official for item in _string_leaves(value))
    found = [phrase for phrase in _TEXT_BLOCKING_PHRASES if phrase in normalized]
    if not found:
        return []
    return [f"ImageTask {task.get('key')} 的正式文字策略为 {policy['mode']}，"
            f"却含冲突禁令：{', '.join(found)}"]


def _stable_hash(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def compile_image_generation_request(task):
    """把唯一正式语义源编译成不可追加提示的交互式单图请求。"""
    problems = validate_image_task_prompt(task)
    if problems:
        raise ValueError("；".join(problems))
    semantic = {
        "prompt": task.get("prompt"),
        "negative_prompt": task.get("negative_prompt"),
        "rule_manifest": task.get("rule_manifest"),
    }
    semantic_sha256 = _stable_hash(semantic)
    request = {
        "key": task.get("key"), "prompt": semantic["prompt"],
        "negative_prompt": semantic["negative_prompt"],
        "size": task.get("size"), "reference_images": task.get("reference_images", []),
        "semantic_sha256": semantic_sha256,
        "additional_prompt": None,
        "additional_prompt_allowed": False,
    }
    request["request_sha256"] = _stable_hash(request)
    return request


def build_image_tasks(storyboard, project_meta, characters, images_dir,
                      style_anchor=None, bootstrap_anchor_key=None):
    visual = dict(DEFAULT_VISUAL_STYLE)
    visual.update(project_meta.get("visual_style") or {})
    raw_characters = characters.get("characters", characters)
    if isinstance(raw_characters, list):
        char_map = {c["id"]: c for c in raw_characters}
    else:
        char_map = raw_characters
    style = ", ".join(x for x in (
        visual.get("variant"), visual.get("art_direction"),
        visual.get("forbidden")) if x)
    palette = visual.get("palette") or "colors follow the narrative emotion"
    direct_phase = visual.get("phase_transition") == "direct"
    tasks = []
    anchor_path = style_anchor.get("path") if isinstance(style_anchor, dict) else None
    anchor_sha = style_anchor.get("sha256") if isinstance(style_anchor, dict) else None
    style_anchor_record = {"path": anchor_path, "sha256": anchor_sha,
                           "variant": visual.get("variant"),
                           "requirements": style}
    for block in storyboard.get("blocks", []):
        phase_number, phase_title = phase_identity(block)
        if phase_number is not None and direct_phase:
            continue
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
            is_bootstrap_anchor = key == bootstrap_anchor_key
            char_bits = []
            for char_id in beat.get("character_ids", []):
                if char_id == "none":
                    continue
                char = char_map.get(char_id)
                if not char:
                    raise ValueError(f"ImageTask 引用了未知角色：{char_id}")
                identity = char.get("prompt") or char.get("description") or char_id
                character_anchor = char.get("anchor") or ""
                char_bits.append(", ".join(x for x in (identity, character_anchor)
                                           if x))
            if is_phase:
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
                )
            elif is_bootstrap_anchor:
                text_policy = (
                    "style-anchor image; limited semantically useful in-scene text, "
                    "numbers or currency symbols are allowed when naturally part of "
                    "the setting; keep them sparse, immediately scannable and visually "
                    "secondary; never create subtitles, long passages, dense text, "
                    "gibberish or watermarks, and keep readable elements away from the "
                    "bottom-center subtitle area"
                )
            else:
                text_policy = (
                    "semantically useful in-scene text is allowed when it helps the "
                    "viewer: one short headline or key phrase plus a few concise "
                    "labels, prices or numbers; keep text easy to scan and visually "
                    "secondary, normally no more than about 6 short groups and under "
                    "20 percent of the frame; avoid paragraphs or dense text layouts"
                )
            sources = {"style": style, "palette": palette,
                       "description": description, "char_bits": char_bits,
                       "shot": beat.get("shot", "medium"),
                       "emotion": beat.get("emotion", "neutral"),
                       "text_policy": text_policy}
            prompt = _build_image_prompt(**sources)
            task_anchor = (dict(style_anchor_record, mode="bootstrap")
                           if is_bootstrap_anchor else style_anchor_record)
            negative_prompt = NEGATIVE_PROMPT
            task = {
                "key": key,
                "kind": "phase_title" if is_phase else "scene",
                "title_text": phase_title if is_phase else None,
                "block_idx": block["block_idx"],
                "beat_idx": beat["beat_idx"],
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "size": [1920, 1080],
                "output_path": os.path.join(images_dir, key + ".png"),
                "reference_images": ([] if is_bootstrap_anchor else
                                     [anchor_path] if anchor_path else []),
                "style_anchor": task_anchor,
                "rule_manifest": {
                    "text_mode": ("exact_title" if is_phase else
                                  "useful_in_scene"),
                    "text_policy": (
                        {"mode": "required_exact", "exact_text": phase_title}
                        if is_phase else {"mode": "useful_in_scene"}),
                    "title_text": phase_title if is_phase else None,
                    "max_text_density": ("title_only" if is_phase else
                                         "6_groups_20_percent"),
                    "forbidden_text_types": [
                        "paragraph", "subtitle", "watermark", "gibberish"],
                    "negative_prompt": negative_prompt,
                    "prompt_sources": sources,
                    "style_anchor": task_anchor,
                },
            }
            tasks.append(task)
    return tasks


def safe_project_suffix(title):
    value = re.sub(r"[\\/:*?\"<>|]", "", str(title or "")).strip()
    return value[:48] or "新项目"
