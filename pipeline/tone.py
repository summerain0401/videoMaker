#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""画面可读性检测：阴郁词典 + 图像亮度/暗部指标。

供 write_image_art.py（--tone-check / 重绘清晰度）与
write_storyboard.py（--warm 提示词暖化）共用。

阈值（默认）：
  THRESH_LUM   平均亮度 < 150       视为偏暗
  THRESH_DARK  暗部(lum<60)占比 >25% 视为大面积暗部
"""

from PIL import Image, ImageStat

THRESH_LUM = 150.0
THRESH_DARK = 0.25

# 情绪主题背景：可按情绪使用冷色、明亮色或中性色；不构成暖色限制。
COOL_EMO_KEYS = [
    "anxious", "empty", "numb", "confused", "doubt", "lost", "distress",
    "dazed", "trapped", "stressed", "frustrat", "detached", "struggl",
    "reflect", "sad", "overconfident",
]
BRIGHT_EMO_KEYS = [
    "happy", "hopeful", "confident", "calm", "salary", "content", "realiz",
    "reveal", "ready", "inspired", "authoritative", "wise", "awaken",
    "relieved", "comfortable",
]


def theme_for(emotion):
    """按 emotion 关键词返回背景主题：cool / bright / neutral。"""
    e = (emotion or "").lower()
    if any(k in e for k in COOL_EMO_KEYS):
        return "cool"
    if any(k in e for k in BRIGHT_EMO_KEYS):
        return "bright"
    return "neutral"

# 阴郁/消极词典（命中即提示风险，重写时优先处理）
DARK_WORDS = [
    "深夜", "凌晨", "加班", "焦虑", "疲惫", "崩溃", "恐慌", "压抑",
    "灰暗", "昏暗", "阴沉", "阴郁", "冷色", "冷色调", "阴天", "暴雨",
    "黑暗", "阴影", "孤独", "失眠", "痛苦", "眼泪", "绝望", "麻木",
    "茫然", "迷茫", "烦躁", "账单", "债务", "破产", "哭", "恐惧",
    "忧郁", "死气", "荒凉",
]

# Q 版模式下的绝对负面词（仅画面观感问题，情绪词如焦虑/疲惫不算）
ABSOLUTE_NEG = [
    "压抑", "阴暗", "绝望", "昏暗", "阴沉", "黑暗", "恐怖", "恐惧",
    "死气", "荒凉",
]


def analyze_image(path):
    """返回 {luminance, dark_ratio}；读取失败返回 None。"""
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
    return {"luminance": round(lum, 1), "dark_ratio": round(dark / len(px), 3)}


def risk_reasons(stat):
    """按阈值判定风险，返回原因列表（空 = 达标）。"""
    if stat is None:
        return ["无法读取图片"]
    reasons = []
    if stat["luminance"] < THRESH_LUM:
        reasons.append(f"亮度偏低 {stat['luminance']}（<{THRESH_LUM:.0f}）")
    if stat["dark_ratio"] > THRESH_DARK:
        reasons.append(f"暗部占比 {stat['dark_ratio'] * 100:.0f}%"
                       f"（>{THRESH_DARK * 100:.0f}%）")
    return reasons


def prompt_risks(prompt, words=None):
    """返回提示词中命中的阴郁词列表。"""
    words = words if words is not None else DARK_WORDS
    return [w for w in words if w in (prompt or "")]
