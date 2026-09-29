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
    "book_spotlight_v2": {
        "id": "book_spotlight_v2",
        "version": 2,
        "display_name": "书籍主视觉封面（混合文字）",
        "description": (
            "左侧书封与书脊原生呈现书名，右侧确定性合成两行观点钩子的"
            "深色编辑插画封面。"
        ),
        "layout": "book_left_hook_right_hybrid",
        "canvas": [1920, 1080],
        "candidate_count": 2,
        "requires_style_anchor": True,
        "requires_character_ids": False,
        "allows_people": False,
        "title_line_max_chars": 9,
        "subtitle_max_chars": 16,
        "book_text_mode": "generated_exact",
        "right_text_mode": "local_deterministic",
        "review_dimensions": [
            "style", "book_recognition", "book_text_accuracy", "semantic",
            "layout", "thumbnail_legibility",
        ],
        "generation_policy": (
            "以正式场景作为画风锚点，左侧立体书籍的书封与书脊必须原生生成"
            "准确书名，书封原生生成准确作者名；右侧保留自然形成的深蓝低细节"
            "文字区且不得生成可读文字。右侧书目信息、两行观点钩子与副标题"
            "由本地确定性合成，不使用覆盖书籍的硬边整块遮罩；底图禁止人物、"
            "额外可读文字、标识和水印。"
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
