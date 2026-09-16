#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Contracts for exploratory cover design packages.

Cover Lab is deliberately outside publishing state.  It may iterate freely,
but only an explicitly frozen package can be imported by the V4 publishing
workflow.
"""

import hashlib
import json
import os
import re


LAB_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
HOOK_TYPES = {"pain_point", "counter_intuitive", "warning"}
VARIANT_CONTROL_KEYS = {"shot_scale", "composition", "subject_pose", "lighting"}


def stable_json_hash(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def cover_lab_paths(project_root, lab_id):
    if not isinstance(lab_id, str) or not LAB_ID_RE.fullmatch(lab_id):
        raise ValueError("Cover Lab ID 只能包含字母、数字、下划线或短横线")
    root = os.path.join(project_root, "experiments", "cover_templates", lab_id)
    return {
        "root": root,
        "draft": os.path.join(root, "design.json"),
        "frozen": os.path.join(root, "frozen_design.json"),
    }


def _validate_string_list(value, label, errors):
    if not isinstance(value, list) or not all(
            isinstance(item, str) and item.strip() for item in value):
        errors.append(f"{label} 必须是非空字符串数组")


def _validate_variant_controls(value, errors):
    if not isinstance(value, dict) or set(value) != VARIANT_CONTROL_KEYS:
        errors.append("受控变体必须包含景别、构图、主体姿态和光线")
        return
    if any(not isinstance(value[key], str) or not value[key].strip()
           for key in VARIANT_CONTROL_KEYS):
        errors.append("受控变体字段必须是非空字符串")


def validate_cover_lab_design(data, project_id, video_run_id, topic_sha256,
                              template_snapshot, project_root,
                              require_frozen=False):
    """Validate a draft or frozen Cover Lab design package."""
    errors = []
    required = {
        "version", "lab_id", "project_id", "video_run_id", "topic_sha256",
        "template_id", "status", "direction", "variants",
        "title_context", "feedback_history", "references", "frozen_at",
        "draft_sha256",
    }
    if not isinstance(data, dict) or set(data) != required:
        return ["Cover Lab 设计包顶层字段不符合契约"]
    if data.get("version") != 1:
        errors.append("Cover Lab 设计包版本必须为1")
    try:
        cover_lab_paths(project_root, data.get("lab_id"))
    except ValueError as exc:
        errors.append(str(exc))
    if data.get("project_id") != str(project_id):
        errors.append("Cover Lab project_id 不匹配")
    if data.get("video_run_id") != video_run_id:
        errors.append("Cover Lab video_run_id 不匹配")
    if data.get("topic_sha256") != topic_sha256:
        errors.append("Cover Lab 正式 topic hash 不匹配")
    if data.get("template_id") != template_snapshot.get("id"):
        errors.append("Cover Lab 模板与正式选择不匹配")
    if template_snapshot.get("id") != "book_title_author_v2":
        errors.append("Cover Lab V1 仅支持 book_title_author_v2 模板")
    status = data.get("status")
    if status not in {"draft", "frozen"}:
        errors.append("Cover Lab 状态必须为 draft 或 frozen")
    if require_frozen and status != "frozen":
        errors.append("只能导入已冻结的 Cover Lab 设计包")
    if status == "frozen":
        if not isinstance(data.get("frozen_at"), str) or not data["frozen_at"]:
            errors.append("冻结设计包缺少 frozen_at")
        if not isinstance(data.get("draft_sha256"), str) or \
                not re.fullmatch(r"[0-9a-f]{64}", data["draft_sha256"]):
            errors.append("冻结设计包缺少有效 draft_sha256")
    elif data.get("frozen_at") is not None or data.get("draft_sha256") is not None:
        errors.append("草稿不得预填冻结信息")

    title_context = data.get("title_context")
    title_keys = {"working_title", "relationship", "status", "checked_at"}
    if not isinstance(title_context, dict) or set(title_context) != title_keys:
        errors.append("Cover Lab 标题协同字段不符合契约")
    else:
        if not isinstance(title_context.get("working_title"), str) or \
                not title_context["working_title"].strip():
            errors.append("Cover Lab 必须记录用于协同设计的暂定标题")
        if not isinstance(title_context.get("relationship"), str) or \
                not title_context["relationship"].strip():
            errors.append("Cover Lab 必须说明标题与封面钩子的悬念关系")
        if title_context.get("status") not in {"provisional", "confirmed"}:
            errors.append("Cover Lab 标题协同状态无效")
        if title_context.get("status") == "confirmed" and \
                (not isinstance(title_context.get("checked_at"), str) or
                 not title_context["checked_at"]):
            errors.append("已确认的标题协同记录缺少 checked_at")
        if title_context.get("status") == "provisional" and \
                title_context.get("checked_at") is not None:
            errors.append("暂定标题协同记录不得预填 checked_at")

    direction = data.get("direction")
    direction_keys = {
        "concept", "hook", "hook_type", "subtitle", "visual_metaphor",
        "environment", "character_ids", "preserve", "avoid",
    }
    if not isinstance(direction, dict) or set(direction) != direction_keys:
        errors.append("Cover Lab 冻结方向字段不符合契约")
        direction = {}
    for key in ("concept", "hook", "visual_metaphor", "environment"):
        if not isinstance(direction.get(key), str) or not direction.get(key, "").strip():
            errors.append(f"Cover Lab direction.{key} 不能为空")
    if direction.get("hook_type") not in HOOK_TYPES:
        errors.append("Cover Lab hook_type 无效")
    hook = direction.get("hook")
    if not isinstance(hook, str) or not 4 <= len(hook) <= 16:
        errors.append("Cover Lab 点击钩子必须为4-16个字符")
    subtitle = direction.get("subtitle")
    if not isinstance(subtitle, str) or len(subtitle) > 14 or \
            any(char in subtitle for char in "\n\r\t"):
        errors.append("Cover Lab 解释副标题必须为0-14字单行文字")
    character_ids = direction.get("character_ids")
    if not isinstance(character_ids, list) or len(character_ids) > 1 or \
            not all(isinstance(item, str) and item for item in character_ids):
        errors.append("Cover Lab 最多绑定一个有效角色 ID")
    _validate_string_list(direction.get("preserve"), "preserve", errors)
    _validate_string_list(direction.get("avoid"), "avoid", errors)

    variants = data.get("variants")
    expected_count = template_snapshot.get("spec", {}).get("candidate_count", 2)
    if not isinstance(variants, list) or not variants:
        errors.append("Cover Lab 必须包含至少一个变体")
        variants = []
    if require_frozen and len(variants) != expected_count:
        errors.append(f"冻结设计包必须包含{expected_count}个受控变体")
    ids = [item.get("id") for item in variants if isinstance(item, dict)]
    if len(ids) != len(variants) or any(not item for item in ids) or \
            len(ids) != len(set(ids)):
        errors.append("Cover Lab 变体 ID 必须非空且唯一")
    controls = []
    candidate_keys = {
        "id", "concept", "hook", "hook_type", "subtitle",
        "visual_metaphor", "environment", "character_ids",
        "variant_controls",
    }
    locked_keys = {
        "concept", "hook", "hook_type", "subtitle", "visual_metaphor",
        "environment", "character_ids",
    }
    for variant in variants:
        if not isinstance(variant, dict) or set(variant) != candidate_keys:
            errors.append("Cover Lab 受控变体字段不符合契约")
            continue
        for key in locked_keys:
            if variant.get(key) != direction.get(key):
                errors.append(f"Cover Lab 变体不得改写冻结方向字段 {key}")
        _validate_variant_controls(variant.get("variant_controls"), errors)
        controls.append(variant.get("variant_controls"))
    if require_frozen and len({stable_json_hash(item) for item in controls}) != \
            len(controls):
        errors.append("冻结设计包的受控变体必须有不同执行参数")

    history = data.get("feedback_history")
    if not isinstance(history, list):
        errors.append("feedback_history 必须为数组")
    else:
        feedback_keys = {"round", "liked", "rejected", "next_iteration"}
        for item in history:
            if not isinstance(item, dict) or set(item) != feedback_keys or \
                    not isinstance(item.get("round"), int) or item["round"] < 1:
                errors.append("Cover Lab 反馈记录字段无效")
                continue
            for key in ("liked", "rejected", "next_iteration"):
                _validate_string_list(item.get(key), f"feedback.{key}", errors)

    references = data.get("references")
    if not isinstance(references, list):
        errors.append("Cover Lab references 必须为数组")
    else:
        reference_keys = {"id", "path", "sha256", "purpose"}
        project_real = os.path.realpath(project_root)
        for item in references:
            if not isinstance(item, dict) or set(item) != reference_keys:
                errors.append("Cover Lab 参考图字段无效")
                continue
            full = os.path.realpath(os.path.join(project_root, item.get("path", "")))
            try:
                inside = os.path.commonpath((project_real, full)) == project_real
            except ValueError:
                inside = False
            if not inside or not os.path.isfile(full):
                errors.append("Cover Lab 参考图必须位于项目目录且真实存在")
                continue
            with open(full, "rb") as handle:
                digest = hashlib.sha256(handle.read()).hexdigest()
            if digest != item.get("sha256"):
                errors.append("Cover Lab 参考图 hash 不匹配")
    return sorted(set(errors))


def cover_plan_from_frozen(data, publish_id, source_hashes):
    """Build the canonical publish cover plan without creative rewriting."""
    return {
        "version": 1,
        "publish_id": publish_id,
        "source_hashes": source_hashes,
        "template_id": data["template_id"],
        "candidates": data["variants"],
    }
