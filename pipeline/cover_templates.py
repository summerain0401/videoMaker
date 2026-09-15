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
        "display_name": "书名观点叙事封面",
        "description": (
            "全画幅电影海报式封面，以完整书名和一个痛点或反常识观点形成点击钩子。"
        ),
        "layout": "cinematic_stacked_hook_poster",
        "canvas": [1920, 1080],
        "candidate_count": 2,
        "requires_style_anchor": True,
        "style_reference_count": 3,
        "requires_character_ids": False,
        "allows_people": True,
        "hook_char_range": [4, 16],
        "hook_line_range": [1, 2],
        "subtitle_max_chars": 14,
        "shows_author": False,
        "design_reference": "docs/references/book_title_author_v2_centered.png",
        "design_reference_sha256": (
            "1b00fb23625441a1c63cb0cf298f40cd65b35ea59a039256df091c9499cedc23"
        ),
        "typography": {
            "book_tag_box": [470, 58, 1450, 178],
            "book_font_size": 78,
            "book_padding": [42, 24],
            "hook_box": [200, 194, 1720, 410],
            "hook_font_size": 232,
            "hook_min_font_size": 56,
            "hook_color": "#E7B650",
            "hook_gradient": ["#FFF2B3", "#E7B650", "#A96A24"],
            "stroke_width": 6,
            "shadow_offset": [7, 10],
            "subtitle_box": [330, 426, 1590, 504],
            "subtitle_font_size": 76,
            "subject_top": 530,
        },
        "scene_policy": (
            "Continuous full-frame cinematic scene, dynamic diagonal perspective. "
            "Keep the upper text area y=0..510 of the 1920x1080 canvas calm and "
            "low contrast; complete head silhouette and essential action below "
            "y=530. Primary subject lower center-left; one core narrative object "
            "center-right, connected by a readable gesture or causal trajectory. "
            "Use at most three supporting objects; avoid foreground clutter. "
            "Keep the bottom-right x=1632..1920, y=950..1080 free of critical "
            "details for a platform duration badge, without drawing the badge. "
            "Keep faces, hands and core object sharp; naturally softer peripheral "
            "detail, restrained background contrast, cinematic warm/cool lighting. "
            "No heavy black vignette, artificial glow rings, arrows, title panels "
            "or model-generated text. Choose objects and action from this topic, "
            "never copy the shopping vortex or wallet merely from the example."
        ),
        "review_dimensions": [
            "click_hook_strength", "topic_traceability",
            "video_style_consistency", "emotional_tension", "brand_palette",
            "text_accuracy", "stacked_layout", "no_model_text",
            "thumbnail_legibility",
            "subject_object_hierarchy", "duration_safe_area",
        ],
        "generation_policy": (
            "以正式场景参考图锁定正片画风。采用全画幅电影海报式单场景，允许使用"
            "正式角色或强叙事物件制造冲突和情绪，主体完整位于标题下方。"
            "上半部为居中书名铭牌、金色立体观点大字和白色单行解释副标题。"
            "铭牌有克制的书页轮廓与金属包边，文字全部本地合成。副标题最多14字，"
            "可为空；两侧仅使用短分隔线。不使用左右分栏。"
            "背景以自然景深和明暗对比弱化，禁止重暗角和固定坐标光圈。品牌深蓝和青色"
            "只作局部强调。禁止作者信息、多个观点、模型生成"
            "文字、标识和水印。"
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
