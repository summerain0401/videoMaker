#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Versioned, immutable cover-template registry."""

import hashlib
import json


_TEMPLATES = {
    "reference_006_v1": {
        "id": "reference_006_v1",
        "version": 1,
        "display_name": "观点钩子封面",
        "description": "左侧两行观点钩子、右侧主题人物的既有频道封面。",
        "layout": "hook_left_character_right",
        "canvas": [1920, 1080],
        "candidate_count": 2,
        "requires_style_anchor": True,
        "requires_character_ids": True,
        "allows_people": True,
        "subtitle_max_chars": 28,
        "review_dimensions": [
            "style", "character", "semantic", "layout",
            "thumbnail_legibility",
        ],
        "generation_policy": (
            "以正式场景作为风格锚点，保留必要角色；底图禁止可读文字、"
            "标题、标识和水印。"
        ),
    },
    "book_title_author_v2": {
        "id": "book_title_author_v2",
        "version": 2,
        "display_name": "书名作者叙事海报",
        "description": (
            "居中书名作者结构，使用与正片一致的暖色手绘场景语言和主题物件，"
            "不依赖人物角色。"
        ),
        "layout": "centered_illustrated_editorial_poster",
        "canvas": [1920, 1080],
        "candidate_count": 2,
        "requires_style_anchor": True,
        "style_reference_count": 3,
        "requires_character_ids": False,
        "allows_people": False,
        "subtitle_max_chars": 14,
        "title_line_range": [1, 3],
        "review_dimensions": [
            "video_style_consistency", "illustrated_depth",
            "thematic_object_semantic", "brand_palette", "text_accuracy",
            "centered_layout", "no_model_text", "thumbnail_legibility",
        ],
        "generation_policy": (
            "以正式场景参考图锁定正片的手绘动画质感、暖色照明、材质与景深。"
            "使用与选题相关的具象叙事物件和完整空间层次，画面必须包含前景、中景"
            "与背景，细节丰富但中央文字区保持安静。品牌深蓝和青色作为局部阴影、"
            "描边或小面积强调色，不得把画面退化成纯色科技背景。禁止人物、角色、"
            "模型生成文字、标识和水印。"
        ),
    },
}

COVER_TEMPLATE_IDS = tuple(_TEMPLATES)


def _stable_hash(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def get_cover_template(template_id):
    """Return a detached template definition."""
    if template_id not in _TEMPLATES:
        raise ValueError(f"未知封面模板：{template_id}")
    return json.loads(json.dumps(_TEMPLATES[template_id], ensure_ascii=False))


def cover_template_snapshot(template_id):
    """Return a versioned template snapshot bound to a stable hash."""
    spec = get_cover_template(template_id)
    return {"id": spec["id"], "version": spec["version"],
            "sha256": _stable_hash(spec), "spec": spec}


def cover_template_catalog():
    """Enumerate every registered template without maintaining a second list."""
    return [cover_template_snapshot(template_id)
            for template_id in _TEMPLATES]


def validate_cover_template_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        return ["封面模板快照必须是对象"]
    try:
        expected = cover_template_snapshot(snapshot.get("id"))
    except ValueError as exc:
        return [str(exc)]
    return [] if snapshot == expected else ["封面模板快照版本或 hash 不匹配"]
