#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""暖色基调检测：阴郁词典 + 图像亮度/暖度/暗部指标。

供 write_image_art.py（--tone-check / 重绘暖化）与
write_storyboard.py（--warm 提示词暖化）共用。

阈值（默认）：
  THRESH_LUM   平均亮度 < 150       视为偏暗
  THRESH_WARM  暖度(R-B) < 10       视为偏冷
  THRESH_DARK  暗部(lum<60)占比 >25% 视为大面积暗部
"""

from PIL import Image, ImageStat

THRESH_LUM = 150.0
THRESH_WARM = 10.0
THRESH_DARK = 0.25

# 阴郁/消极词典（命中即提示风险，重写时优先处理）
DARK_WORDS = [
    "深夜", "凌晨", "加班", "焦虑", "疲惫", "崩溃", "恐慌", "压抑",
    "灰暗", "昏暗", "阴沉", "阴郁", "冷色", "冷色调", "阴天", "暴雨",
    "黑暗", "阴影", "孤独", "失眠", "痛苦", "眼泪", "绝望", "麻木",
    "茫然", "迷茫", "烦躁", "账单", "债务", "破产", "哭", "恐惧",
    "忧郁", "死气", "荒凉",
]


def analyze_image(path):
    """返回 {luminance, warmth, dark_ratio}；读取失败返回 None。"""
    try:
        im = Image.open(path).convert("RGB").resize((160, 90))
        s = ImageStat.Stat(im)
        r, g, b = s.mean
    except Exception:
        return None
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    px = list(im.getdata())
    dark = sum(1 for p in px
               if 0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2] < 60)
    return {"luminance": round(lum, 1), "warmth": round(r - b, 1),
            "dark_ratio": round(dark / len(px), 3)}


def risk_reasons(stat):
    """按阈值判定风险，返回原因列表（空 = 达标）。"""
    if stat is None:
        return ["无法读取图片"]
    reasons = []
    if stat["luminance"] < THRESH_LUM:
        reasons.append(f"亮度偏低 {stat['luminance']}（<{THRESH_LUM:.0f}）")
    if stat["warmth"] < THRESH_WARM:
        reasons.append(f"暖度不足 {stat['warmth']:+.0f}（<{THRESH_WARM:.0f}）")
    if stat["dark_ratio"] > THRESH_DARK:
        reasons.append(f"暗部占比 {stat['dark_ratio'] * 100:.0f}%"
                       f"（>{THRESH_DARK * 100:.0f}%）")
    return reasons


def prompt_risks(prompt):
    """返回提示词中命中的阴郁词列表。"""
    return [w for w in DARK_WORDS if w in (prompt or "")]
