#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Strict contracts for isolated brand and publishing artifacts."""
import hashlib
import re
import os
try:
    from PIL import Image
except ImportError:  # 纯契约校验环境可无 Pillow
    Image = None

PLATFORMS = ("youtube", "bilibili", "douyin", "wechat")
YOUTUBE_ONLY = ("youtube",)
TITLE_LIMITS = {"youtube": 100, "bilibili": 80, "douyin": 55, "wechat": 64}
FORBIDDEN = re.compile(r"稳赚|暴富|躺赚|必赚|保本|保证收益|无风险收益")
PROMISE = re.compile(r"(?:收入|年化|收益率|回报率|回报|yield|annualized|income|return|multiplier)\s*[:：=]?\s*\d+(?:\.\d+)?\s*%?", re.I)
TIMESTAMP = re.compile(r"^(\d{2}):(\d{2})(?::(\d{2}))?$")

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""): h.update(chunk)
    return h.hexdigest()

def source_hashes(paths): return {k: sha256(v) for k, v in paths.items()}


def _timestamp_seconds(value):
    match = TIMESTAMP.fullmatch(str(value or ""))
    if not match:
        return None
    first, second, third = (int(part or 0) for part in match.groups())
    if second >= 60 or third >= 60:
        return None
    return first * 3600 + second * 60 + third if match.group(3) else first * 60 + second

def _strings(v):
    if isinstance(v, str): return [v]
    if isinstance(v, dict): return sum((_strings(x) for x in v.values()), [])
    if isinstance(v, list): return sum((_strings(x) for x in v), [])
    return []

def scan_compliance(value):
    errors = []
    for text in _strings(value):
        if FORBIDDEN.search(text): errors.append("包含收益承诺禁用词")
        if PROMISE.search(text): errors.append("包含数字收益承诺")
    return sorted(set(errors))

def validate_svg_text(text):
    if not isinstance(text, str) or not re.search(r'<svg\b[^>]*viewBox=["\']0 0 1024 1024["\']', text): return ["SVG 必须使用 viewBox 0 0 1024 1024"]
    sanitized = text.replace('xmlns="http://www.w3.org/2000/svg"', '').replace("xmlns='http://www.w3.org/2000/svg'", "")
    if re.search(r'<(text|script|image|foreignObject)\b|https?://|\b(?:href|src|xlink:href|style)\s*=|\bon\w+\s*=|url\s*\(', sanitized, re.I): return ["SVG 含有不安全元素或外部引用"]
    return []

def validate_brand(data):
    errors = []
    required = {"version", "candidates", "visual_directions", "profiles", "tone", "cta", "selected_name_id", "selected_visual_id"}
    if not required <= set(data): errors.append("brand 顶层字段不完整")
    names = data.get("candidates", [])
    if len(names) != 5: errors.append("brand 必须恰好包含 5 个名称候选")
    if len({x.get("id") for x in names}) != len(names): errors.append("名称候选 id 必须唯一")
    for x in names:
        if not {"id", "name", "benefit_hook", "rationale"} <= set(x): errors.append("名称候选字段不完整")
    visual = data.get("visual_directions", [])
    if len(visual) != 3: errors.append("brand 必须恰好包含 3 个视觉方向候选")
    for x in visual:
        if not {"id", "label", "concept", "symbol", "palette", "avatar_svg"} <= set(x): errors.append("视觉候选字段不完整")
        if not {"background", "foreground", "accent"} <= set(x.get("palette", {})): errors.append("视觉 palette 字段不完整")
        errors += validate_svg_text(x.get("avatar_svg"))
    profiles = data.get("profiles", {})
    if set(profiles) != set(PLATFORMS): errors.append("profiles 必须恰好包含四个平台")
    for p in PLATFORMS:
        template = profiles.get(p, {}).get("description_template", "")
        if not template or "{{channel_name}}" not in template or re.search(r"{{(?!channel_name}})[^}]+}}", template): errors.append("profile template 必须只使用 {{channel_name}}")
    if not data.get("tone") or not data.get("cta"): errors.append("tone/cta 不能为空")
    if data.get("selected_name_id") not in {x.get("id") for x in names}: errors.append("selected_name_id 无效")
    if data.get("selected_visual_id") not in {x.get("id") for x in visual}: errors.append("selected_visual_id 无效")
    return sorted(set(errors))

def validate_package(data, sources=None, script_text=None, copy_data=None, project_id=None, video_run_id=None, revision=None, artifact=None, brand_hash=None, cover_style_references=None, project_root=None):
    errors = []
    required = {"version", "publish_id", "channel_id", "source", "fact_core", "cover", "platforms"}
    if set(data) != required: errors.append("发布包顶层字段必须严格匹配 canonical contract")
    v2 = data.get("version") == 2
    source = data.get("source", {})
    for key in ("project_id", "video_run_id", "revision", "video_artifact", "hashes"):
        if key not in source: errors.append("source 字段不完整")
    if sources and source.get("hashes") != sources: errors.append("source hashes 不匹配")
    if brand_hash and source.get("hashes", {}).get("brand") != brand_hash: errors.append("brand hash 不匹配")
    if project_id is not None and source.get("project_id") != project_id: errors.append("project_id 不匹配")
    if video_run_id is not None and source.get("video_run_id") != video_run_id: errors.append("video_run_id 不匹配")
    if revision is not None and source.get("revision") != revision: errors.append("revision 不匹配")
    fact = data.get("fact_core", {})
    if not isinstance(fact, dict) or not {"summary", "claim_refs", "script_evidence"} <= set(fact): errors.append("fact_core 字段不完整")
    claims = (copy_data or {}).get("claims", [])
    for ref in fact.get("claim_refs", []):
        if not isinstance(ref, int) or ref < 0 or ref >= len(claims): errors.append("claim_refs 越界或非整数")
    if script_text:
        for evidence in fact.get("script_evidence", []):
            if not isinstance(evidence, str) or evidence not in script_text: errors.append("script_evidence 不是 script 原文子串")
    cover = data.get("cover", {})
    for key in ("aspect_ratio", "copy_lines", "concept", "subject", "composition", "contrast", "brand_anchor", "safe_zone", "forbidden_elements", "style_references", "style_requirements"):
        if key not in cover: errors.append("cover 字段不完整")
    refs = cover.get("style_references", [])
    if not isinstance(refs, list) or not refs: errors.append("封面 style_references 不能为空")
    if not isinstance(cover.get("style_requirements"), str) or not cover.get("style_requirements"): errors.append("封面 style_requirements 不能为空")
    if cover_style_references is not None and refs != cover_style_references: errors.append("封面 style_references 与任务参考不一致")
    if project_root is not None:
        scenes = os.path.realpath(os.path.join(project_root, "assets", "scenes"))
        for ref in refs if isinstance(refs, list) else []:
            path = ref.get("path") if isinstance(ref, dict) else None
            digest = ref.get("sha256") if isinstance(ref, dict) else None
            if not path or not digest: errors.append("封面 style_reference 字段不完整"); continue
            full = os.path.realpath(path if os.path.isabs(path) else os.path.join(project_root, path))
            if os.path.commonpath((scenes, full)) != scenes or not os.path.isfile(full): errors.append("封面 style_reference 必须来自正式 scenes"); continue
            if sha256(full) != digest: errors.append("封面 style_reference hash 不匹配")
    lines = cover.get("copy_lines", [])
    if cover.get("aspect_ratio") != "16:9" or not 1 <= len(lines) <= 2 or sum(len(x) for x in lines) > 12 or any(len(x) > 8 for x in lines): errors.append("封面文案或比例不符合限制")
    platforms = data.get("platforms", {})
    expected_platforms = YOUTUBE_ONLY if v2 else PLATFORMS
    if set(platforms) != set(expected_platforms): errors.append("platforms 必须为 YouTube-only 嵌套对象" if v2 else "platforms 必须为四平台嵌套对象")
    for p in expected_platforms:
        item = platforms.get(p, {})
        if v2:
            titles = item.get("titles", item.get("alternate_titles", []))
            keywords = item.get("keywords", [])
            if len(titles) != 5: errors.append("youtube 必须有 5 个标题候选")
            if not keywords or not all(isinstance(keyword, str) and keyword for keyword in keywords): errors.append("youtube 必须提供核心关键词")
            strategies = {"pain_point", "counter_intuitive", "number_solution", "seo", "emotional_story"}
            if {x.get("strategy") for x in titles if isinstance(x, dict)} != strategies: errors.append("标题策略必须完整")
            for x in titles:
                text = x.get("title", "") if isinstance(x, dict) else x
                if not 50 <= len(text) <= 60: errors.append("标题长度必须为 50-60 字符")
                if keywords and not any(k and k in text[:30] for k in keywords): errors.append("核心关键词必须出现在标题前30字符")
            desc = item.get("description", {})
            if not isinstance(desc, dict) or not all(desc.get(k) for k in ("lead", "highlights", "timestamps", "cta", "resources", "hashtags")): errors.append("youtube 简介结构不完整")
            if isinstance(desc, dict):
                if len(desc.get("lead", "")) > 100: errors.append("折叠线前导语不得超过100字")
                if not 3 <= len(desc.get("highlights", [])) <= 4: errors.append("核心看点必须为3-4项")
                ts = desc.get("timestamps", [])
                if not ts or not str(ts[0].get("time", "")).startswith("00:00"): errors.append("章节必须从00:00开始")
                if not 4 <= len(ts) <= 6: errors.append("章节必须为4-6段")
                parsed = [_timestamp_seconds(entry.get("time")) if isinstance(entry, dict) else None for entry in ts]
                if any(value is None for value in parsed) or parsed != sorted(parsed) or len(set(parsed)) != len(parsed): errors.append("章节时间戳必须为递增的 MM:SS 或 HH:MM:SS")
                if not 3 <= len(desc.get("hashtags", [])) <= 5: errors.append("hashtags必须为3-5个")
                elif not all(isinstance(tag, str) and tag.startswith("#") for tag in desc.get("hashtags", [])): errors.append("hashtags必须以#开头")
            if item.get("selected_title_id") not in {x.get("id") for x in titles if isinstance(x, dict)}: errors.append("必须先选择标题候选")
        else:
            if len(item.get("primary_title", "")) > TITLE_LIMITS[p]: errors.append(f"{p} 主标题超长")
            if len(item.get("alternate_titles", [])) != 2: errors.append(f"{p} 必须有 2 个备选标题")
            if not 3 <= len(item.get("tags", [])) <= 8: errors.append(f"{p} 标签必须 3-8 个")
            if not all(item.get(k) for k in ("primary_title", "description", "cta")): errors.append(f"{p} 发布字段不完整")
    if v2:
        cover = data.get("cover", {})
        candidates = cover.get("candidates", [])
        if len(candidates) != 2: errors.append("封面必须有2个候选")
        if cover.get("selected_cover_id") not in {x.get("id") for x in candidates if isinstance(x, dict)}: errors.append("必须先选择封面候选")
        for candidate in candidates:
            if not isinstance(candidate, dict): continue
            path = candidate.get("final_path") or candidate.get("path")
            if not candidate.get("id") or not candidate.get("base_path") or not path or not candidate.get("sha256") or not candidate.get("concept"):
                errors.append("封面候选缺少底图、成品或哈希")
            if path and project_root and Image is not None:
                full = path if os.path.isabs(path) else os.path.join(project_root, path)
                try:
                    with Image.open(full) as image:
                        if image.size != (1920, 1080): errors.append("封面必须为1920x1080")
                    if sha256(full) != candidate.get("sha256"):
                        errors.append("封面成品 hash 不匹配")
                except Exception: errors.append("封面文件无效")
    errors += scan_compliance(data)
    return sorted(set(errors))
