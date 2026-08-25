#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""长视频画面元素库：书卡、阶段徽章、数据图形、装饰层、字幕、卡片模板。"""

import math
import os
import random
import re

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1920, 1080
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_TITLE = "/System/Library/Fonts/STHeiti Medium.ttc"
FONT_BODY = "/System/Library/Fonts/Hiragino Sans GB.ttc"
FONT_SUB_HEAVY = os.path.join(ROOT, "assets", "fonts",
                              "SourceHanSansCN-Heavy.otf")
FONT_SUB_FALLBACK = "/System/Library/Fonts/Hiragino Sans GB.ttc"
ACCENT = (232, 182, 76)
INK = (245, 235, 220)
PARCH_INK = (70, 58, 42)
SUB_WHITE = (255, 255, 255, 255)
SUB_YELLOW = (255, 210, 63, 255)
BOOK_DEFAULT = "《金钱的艺术》"
AUTHOR_DEFAULT = "Morgan Housel"
HOOK_DEFAULT = "为什么你越花钱，越焦虑？"

AMOUNT_RE = re.compile(r"[¥￥]?\d[\d,]*(?:\.\d+)?\s*(?:元|万|千|块|亿|%)?")
EMO_TURN_WORDS = [
    "焦虑", "空虚", "迷茫", "疲惫", "恐惧", "开心", "幸福",
    "但是", "可是", "其实", "然而", "真相", "反而",
    "没钱", "负债", "存款", "余额", "翻倍",
]


def font(path, size):
    return ImageFont.truetype(path, size)


def sub_font(size):
    """字幕粗体：优先思源黑体 Heavy，失败回退系统 Hiragino W6。"""
    try:
        return ImageFont.truetype(FONT_SUB_HEAVY, size)
    except Exception:
        return ImageFont.truetype(FONT_SUB_FALLBACK, size, index=2)


def wrap(d, text, f, max_w):
    out, cur = [], ""
    for ch in text:
        if d.textlength(cur + ch, font=f) > max_w and cur:
            out.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out


def draw_book_card(d, book="《金钱的艺术》", author="Morgan Housel",
                   sub="为什么你越花钱，越焦虑？"):
    x0, y0, x1, y1 = W - 560, 30, W - 30, 164
    d.rounded_rectangle((x0, y0, x1, y1), radius=20,
                        fill=(244, 235, 220, 238),
                        outline=(232, 182, 76), width=3)
    # 封面占位
    d.rounded_rectangle((x0 + 18, y0 + 20, x0 + 108, y1 - 20), radius=10,
                        fill=(120, 90, 50), outline=(70, 50, 25), width=2)
    d.text((x0 + 63, y0 + 52), "钱", font=font(FONT_TITLE, 40),
           fill=(244, 235, 220), anchor="mm")
    d.text((x0 + 63, y0 + 92), "术", font=font(FONT_TITLE, 40),
           fill=(244, 235, 220), anchor="mm")
    d.text((x0 + 128, y0 + 30), book, font=font(FONT_TITLE, 38),
           fill=(60, 50, 38), anchor="lm")
    d.text((x0 + 128, y0 + 82), author, font=font(FONT_BODY, 28),
           fill=(120, 105, 85), anchor="lm")
    d.text((x0 + 128, y0 + 118), sub, font=font(FONT_BODY, 24),
           fill=(150, 130, 100), anchor="lm")


def draw_phase_badge(d, phase, idx):
    """左上角阶段徽章：序号圆 + 阶段名。"""
    num = phase_num(phase) or str(idx)
    name = phase_name(phase)
    x0, y0 = 48, 44
    d.ellipse((x0, y0, x0 + 64, y0 + 64), fill=ACCENT)
    d.text((x0 + 32, y0 + 32), num, font=font(FONT_TITLE, 30),
           fill=(40, 30, 20), anchor="mm")
    if name:
        d.text((x0 + 84, y0 + 34), name, font=font(FONT_TITLE, 36),
               fill=(245, 235, 220), anchor="lm")


def draw_progress(d, idx, total):
    """只画进度条底轨；填充部分由动态图层 crop 控制。"""
    x0, x1, y = 48, W - 48, H - 38
    d.rounded_rectangle((x0, y, x1, y + 6), radius=3, fill=(255, 255, 255, 40))


def phase_num(phase_head):
    """阶段头 'PHASE 01 · 开场共情' -> '01'；解析失败返回 ''。"""
    parts = (phase_head or "").split()
    if len(parts) >= 2 and parts[0] == "PHASE":
        return parts[1]
    return parts[0] if parts else ""


def phase_name(phase_head):
    """阶段头 -> '开场共情'。"""
    num = phase_num(phase_head)
    if num and phase_head and num in phase_head:
        return phase_head.split(num, 1)[1].strip(" ·")
    return phase_head or ""


def draw_centered(img, lines, y_center, size, ink, accent_last=True,
                  spacing=1.32, max_w=1500):
    d = ImageDraw.Draw(img)
    f = font(FONT_TITLE, size)
    wrapped = []
    for ln in lines:
        wrapped += wrap(d, ln, f, max_w)
    total_h = len(wrapped) * int(size * spacing)
    y = y_center - total_h / 2
    for i, line in enumerate(wrapped):
        col = ACCENT if (accent_last and i == len(wrapped) - 1) else ink
        d.text((W / 2, y + size / 2), line, font=f, fill=col, anchor="mm")
        y += size * spacing


def curve_graphics(img):
    """复利曲线：指数增长曲线 + 面积填充。"""
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = 260, 250, 1660, 470
    d.rounded_rectangle((x0 - 20, y0 - 20, x1 + 20, y1 + 30), radius=24,
                        fill=(0, 0, 0, 90), outline=(232, 182, 76, 110), width=2)
    d.text((x0, y0 - 8), "复利曲线 · 前慢后快", font=font(FONT_TITLE, 30),
           fill=ACCENT, anchor="lm")
    pts = []
    for i in range(201):
        t = i / 200
        x = x0 + (x1 - x0) * t
        y = y1 - (y1 - y0) * (math.exp(5 * t) - 1) / (math.exp(5) - 1)
        pts.append((x, y))
    d.line(pts, fill=(245, 235, 220, 220), width=5, joint="curve")
    poly = pts + [(x1, y1), (x0, y1)]
    d.polygon(poly, fill=(232, 182, 76, 45))
    d.line((x0, y1, x1, y1), fill=(255, 255, 255, 70), width=2)
    d.text((x1, y1 + 18), "时间 →", font=font(FONT_BODY, 26),
           fill=(245, 235, 220, 180), anchor="rm")
    d.text((x0, y0 + 24), "收益", font=font(FONT_BODY, 26),
           fill=(245, 235, 220, 180), anchor="lm")


def donut_graphics(img, cx, cy, r=52):
    """占比环形示意：地位/效用两类消费。"""
    d = ImageDraw.Draw(img)
    d.pieslice((cx - r, cy - r, cx + r, cy + r), 180, 360,
               fill=(232, 182, 76, 210))
    d.pieslice((cx - r, cy - r, cx + r, cy + r), 0, 180,
               fill=(255, 255, 255, 170))
    d.ellipse((cx - 22, cy - 22, cx + 22, cy + 22),
              fill=(24, 20, 16, 255))
    d.text((cx, cy + r + 26), "地位 / 效用", font=font(FONT_BODY, 26),
           fill=(245, 235, 220, 210), anchor="mm")


def make_progress_fill():
    """进度条前景填充层（全宽金色条），渲染时用 crop 控制宽度。"""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((48, H - 38, W - 48, H - 32), radius=3, fill=ACCENT)
    return img


def _subtitle_spans(text):
    """把字幕文本切成着色段：金额/数字、情绪词、转折词统一明黄，其余白。"""
    col = {}
    for m in AMOUNT_RE.finditer(text):
        for i in range(m.start(), m.end()):
            col[i] = SUB_YELLOW
    for w in EMO_TURN_WORDS:
        i = text.find(w)
        while i != -1:
            for j in range(i, i + len(w)):
                col[j] = SUB_YELLOW
            i = text.find(w, i + len(w))
    segs, cur, start = [], None, 0
    for idx, ch in enumerate(text):
        c = col.get(idx, SUB_WHITE)
        if c is not cur:
            if cur is not None:
                segs.append((text[start:idx], cur, start))
            cur, start = c, idx
    if cur is not None:
        segs.append((text[start:], cur, start))
    return segs


def first_highlight_span(text):
    """返回首个高亮 span 的 (start, end) 字符区间；无高亮返回 None。"""
    for seg, color, start in _subtitle_spans(text):
        if color != SUB_WHITE:
            return start, start + len(seg)
    return None


def _subtitle_layout(d, text, f):
    """计算各 span 的累计 x 中心与总宽。"""
    segs = _subtitle_spans(text)
    widths = [d.textlength(s, font=f) for s, _, _ in segs]
    total = sum(widths)
    x = W / 2 - total / 2
    centers = []
    for w in widths:
        centers.append(x + w / 2)
        x += w
    return segs, centers


def make_subtitle_layer(text, max_w=1500, size=48):
    """全屏沉浸字幕：48px 粗体白字 + 描边微投影 + 关键词高亮，无底条。"""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = sub_font(size)
    line_h = int(size * 1.35)
    y_center = H - 56 - line_h / 2  # 底边距画面底部约 56px
    segs, centers = _subtitle_layout(d, text, f)
    outline = (20, 18, 16, 235)
    shadow = (0, 0, 0, 150)
    for (s, _c, _i), cx in zip(segs, centers):
        d.text((cx + 2, y_center + 3), s, font=f, fill=shadow, anchor="mm")
    for (s, _c, _i), cx in zip(segs, centers):
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                if dx or dy:
                    d.text((cx + dx, y_center + dy), s, font=f,
                           fill=outline, anchor="mm")
    for (s, c, _i), cx in zip(segs, centers):
        d.text((cx, y_center), s, font=f, fill=c, anchor="mm")
    return img


def make_subtitle_highlight_layer(text, size=48):
    """渲染首个高亮 span 到全屏透明层（居中绘制），供缩放弹跳 overlay。
    返回 (img, center_x, center_y)。"""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = sub_font(size)
    line_h = int(size * 1.35)
    y_center = H - 56 - line_h / 2
    segs, centers = _subtitle_layout(d, text, f)
    outline = (20, 18, 16, 235)
    shadow = (0, 0, 0, 150)
    for (s, color, _i), cx in zip(segs, centers):
        if color == SUB_WHITE:
            continue
        d.text((W / 2 + 2, H / 2 + 3), s, font=f, fill=shadow, anchor="mm")
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                if dx or dy:
                    d.text((W / 2 + dx, H / 2 + dy), s, font=f,
                           fill=outline, anchor="mm")
        d.text((W / 2, H / 2), s, font=f, fill=color, anchor="mm")
        return img, cx, y_center
    return img, W / 2, y_center


def make_bottom_gradient(h_ratio=0.15, peak_alpha=102):
    """底部半透明线性渐变遮罩：下缘 alpha≈0.4，向上渐隐到 0。"""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    gh = int(H * h_ratio)
    for y in range(H - gh, H):
        t = (y - (H - gh)) / max(1, gh - 1)
        d.line([(0, y), (W, y)], fill=(0, 0, 0, int(peak_alpha * t)))
    return img


def make_phase_title_layer(phase_head):
    """全屏章节页标题层：只做局部柔和压暗，不绘制卡片或字幕底栏。"""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    center_y = int(H * 0.48)
    spread = H * 0.24
    for y in range(H):
        distance = (y - center_y) / spread
        alpha = int(94 * math.exp(-(distance * distance)))
        if alpha:
            d.line((0, y, W, y), fill=(8, 10, 14, alpha))

    num = phase_num(phase_head) or "01"
    name = phase_name(phase_head)
    d.text((W / 2, center_y - 118), f"PHASE {num}",
           font=font(FONT_BODY, 34), fill=(232, 182, 76, 235), anchor="mm")
    d.rounded_rectangle((W / 2 - 105, center_y - 74,
                         W / 2 + 105, center_y - 68),
                        radius=3, fill=(232, 182, 76, 220))
    title_font = font(FONT_TITLE, 86)
    lines = wrap(d, name, title_font, 1380)
    start_y = center_y + 22 - (len(lines) - 1) * 54
    for index, line in enumerate(lines):
        y = start_y + index * 108
        d.text((W / 2 + 3, y + 4), line, font=title_font,
               fill=(0, 0, 0, 155), anchor="mm")
        d.text((W / 2, y), line, font=title_font,
               fill=(250, 244, 232, 255), anchor="mm")
    return img


def make_sweep_layer():
    """阶段页金色斜向光带（透明底），渲染时从左向右扫过。"""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = (int(W * 0.4), int(H * 0.5))
    a = math.radians(18)
    ux, uy = math.cos(a), math.sin(a)
    px, py = -math.sin(a), math.cos(a)
    L = 2400
    p0 = (c[0] - ux * L / 2, c[1] - uy * L / 2)
    p1 = (c[0] + ux * L / 2, c[1] + uy * L / 2)
    for half, fill in ((260, (232, 182, 76, 55)), (100, (255, 224, 150, 75))):
        poly = [(p0[0] + px * half, p0[1] + py * half),
                (p1[0] + px * half, p1[1] + py * half),
                (p1[0] - px * half, p1[1] - py * half),
                (p0[0] - px * half, p0[1] - py * half)]
        d.polygon(poly, fill=fill)
    return img.filter(ImageFilter.GaussianBlur(36))


def _hex(s):
    s = s.strip().lstrip("0x").lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def procedural_bg(c0, c1, c2, w, h):
    """无插画时的质感底图：渐变 + 径向光晕 + 细噪点（低分辨率生成后放大）。"""
    gw, gh = max(960, w // 4), max(540, h // 4)
    c0, c1, c2 = _hex(c0), _hex(c1), _hex(c2)
    img = Image.new("RGB", (gw, gh))
    d = ImageDraw.Draw(img)
    for y in range(gh):
        t = y / max(gh - 1, 1)
        r = int(c0[0] + (c2[0] - c0[0]) * t)
        g = int(c0[1] + (c2[1] - c0[1]) * t)
        b = int(c0[2] + (c2[2] - c0[2]) * t)
        d.line((0, y, gw, y), fill=(r, g, b))
    # 径向光晕
    glow = Image.new("RGBA", (gw, gh), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    rnd = random.Random(7)
    for _ in range(4):
        x = rnd.uniform(0, gw)
        y = rnd.uniform(0, gh)
        r = rnd.uniform(gw * 0.12, gw * 0.28)
        col = rnd.choice([(232, 182, 76), (150, 200, 220), (255, 255, 255)])
        gd.ellipse((x - r, y - r, x + r, y + r), fill=col + (18,))
    glow = glow.filter(ImageFilter.GaussianBlur(90))
    img = Image.alpha_composite(img.convert("RGBA"), glow)
    # 细噪点
    noise = Image.effect_noise((gw, gh), 12).convert("L")
    noise = noise.point(lambda p: int(p * 0.35))
    noise_rgb = Image.merge("RGB", (noise, noise, noise)).convert("RGBA")
    img = Image.blend(img, noise_rgb, 0.06)
    return img.convert("RGB").resize((w, h), Image.LANCZOS)


def split_words(text):
    """把一行文字按 2-4 字分组（空格断开），用于逐词浮现。"""
    out, cur = [], ""
    for ch in text:
        if ch in " \t":
            if cur:
                out.append(cur)
                cur = ""
            continue
        cur += ch
        if len(cur) >= 4:
            out.append(cur)
            cur = ""
    if cur:
        out.append(cur)
    return out


def make_title_word_layers(block):
    """TITLE 页标题逐词浮现：每个词组一层，交错淡入。"""
    layers = []
    tmp = Image.new("RGBA", (10, 10))
    d = ImageDraw.Draw(tmp)
    f = font(FONT_TITLE, 112)
    lines = []
    for ln in block["lines"]:
        lines += wrap(d, ln, f, 1500)
    total_h = len(lines) * int(112 * 1.32)
    y = 520 - total_h / 2
    for li, line in enumerate(lines):
        groups = split_words(line)
        widths = [d.textlength(g, font=f) for g in groups]
        x = (W - sum(widths)) / 2
        col = ACCENT if li == len(lines) - 1 else INK
        for g, gw in zip(groups, widths):
            img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            dd = ImageDraw.Draw(img)
            dd.text((x, y + 56), g, font=f, fill=col, anchor="lm")
            layers.append(img)
            x += gw
        y += 112 * 1.32
    return layers


def make_quote_layers(block):
    """QUOTE 金句层：淡入上滑（底座只留引号框）。"""
    layers = []
    for _ in block["lines"]:
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw_centered(img, block["lines"], 540, 66, PARCH_INK, max_w=1500)
        layers.append(img)
    return layers


def make_base(block, idx, total, meta=None):
    """按块类型绘制基底层（书卡、徽章、进度、容器、图形）。"""
    btype = block["type"]
    parchment = btype == "QUOTE"
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    book, hook, author = BOOK_DEFAULT, HOOK_DEFAULT, AUTHOR_DEFAULT
    if meta:
        book, hook, author = meta
    draw_book_card(d, book=book, author=author, sub=hook or HOOK_DEFAULT)
    draw_progress(d, idx, total)
    if block["phase"] and btype not in ("TITLE", "PHASE", "END"):
        draw_phase_badge(d, block["phase"], idx)
    ink = PARCH_INK if parchment else INK

    if btype == "TITLE":
        d.rounded_rectangle((W / 2 - 120, 770, W / 2 + 120, 776),
                            radius=3, fill=ACCENT)
        d.text((W / 2, 900), "原创解读 · 非书籍原文", font=font(FONT_BODY, 26),
               fill=(245, 235, 220, 150), anchor="mm")
    elif btype == "PHASE":
        num = phase_num(block["head"]) or "01"
        name = phase_name(block["head"])
        draw_centered(img, [num], 400, 150, (232, 182, 76))
        draw_centered(img, [name], 560, 96, ink)
        d.rounded_rectangle((W / 2 - 160, 660, W / 2 + 160, 666),
                            radius=3, fill=(232, 182, 76, 160))
    elif btype == "QUOTE":
        d.text((W / 2 - 610, 320), "「", font=font(FONT_TITLE, 130),
               fill=(190, 140, 60), anchor="mm")
        d.text((W / 2 + 610, 780), "」", font=font(FONT_TITLE, 130),
               fill=(190, 140, 60), anchor="mm")
    elif btype == "END":
        draw_centered(img, block["lines"], 500, 82, ink)
        d.rounded_rectangle((W / 2 - 300, 760, W / 2 + 300, 850), radius=24,
                            fill=(0, 0, 0, 90), outline=(232, 182, 76, 120),
                            width=2)
        d.text((W / 2, 805), "点赞 · 关注 · 下一本书见",
               font=font(FONT_TITLE, 38), fill=ACCENT, anchor="mm")
    elif btype == "CARD":
        n = len(block["lines"])
        card_h = 130 + 112 * n
        y0 = int((H - card_h) / 2) + 20
        if "复利" in block["head"]:
            curve_graphics(img)
            y0 = 560
        d.rounded_rectangle((160, y0, W - 160, y0 + card_h), radius=36,
                            fill=(0, 0, 0, 118), outline=(232, 182, 76, 110),
                            width=2)
        d.text((W / 2, y0 - 46), block["head"], font=font(FONT_TITLE, 44),
               fill=ACCENT, anchor="mm")
    elif btype == "TABLE":
        cols = [c.strip() for c in block["head"][len("TABLE"):].split("|")]
        rows = [ln.split("|") for ln in block["lines"]]
        card_w, card_h = 1480, 250 + len(rows) * 116
        x0, y0 = (W - card_w) / 2, (H - card_h) / 2
        donut_graphics(img, x0 + 150, y0 - 120)
        d.rounded_rectangle((x0, y0, x0 + card_w, y0 + card_h), radius=30,
                            fill=(0, 0, 0, 122), outline=(232, 182, 76, 110),
                            width=2)
        midx = x0 + card_w / 2
        d.line((midx, y0 + 20, midx, y0 + card_h - 20),
               fill=(255, 255, 255, 55), width=2)
        d.text((x0 + card_w / 4, y0 + 62), cols[0], font=font(FONT_TITLE, 50),
               fill=ACCENT, anchor="mm")
        d.text((x0 + card_w * 3 / 4, y0 + 62), cols[1],
               font=font(FONT_TITLE, 50), fill=ACCENT, anchor="mm")
        for i, (a, bb) in enumerate(rows):
            yy = y0 + 250 + i * 116
            if i % 2 == 0:
                d.rounded_rectangle((x0 + 24, yy - 34, x0 + card_w - 24,
                                     yy + 34), radius=16,
                                    fill=(255, 255, 255, 14))
            d.text((x0 + card_w / 4, yy), a.strip(),
                   font=font(FONT_BODY, 44), fill=INK, anchor="mm")
            d.text((x0 + card_w * 3 / 4, yy), bb.strip(),
                   font=font(FONT_BODY, 44), fill=INK, anchor="mm")
    elif btype == "STEPS":
        d.text((W / 2, 130), block["head"], font=font(FONT_TITLE, 52),
               fill=ACCENT, anchor="mm")
    return img


def make_line_layers(block, idx):
    """逐条点亮：每条内容单独一层，渲染时按时间窗口淡入。"""
    layers = []
    btype = block["type"]
    if btype == "TITLE":
        return make_title_word_layers(block)
    if btype == "QUOTE":
        return make_quote_layers(block)
    if btype not in ("CARD", "STEPS", "TABLE"):
        return layers
    n = len(block["lines"])
    for k in range(n):
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        if btype == "CARD":
            card_h = 130 + 112 * n
            y0 = int((H - card_h) / 2) + 20
            if "复利" in block["head"]:
                y0 = 560
            y = y0 + 130 + k * 112
            d.text((W / 2, y + 56), block["lines"][k],
                   font=font(FONT_BODY, 56), fill=INK, anchor="mm")
        elif btype == "TABLE":
            rows = [ln.split("|") for ln in block["lines"]]
            card_w, card_h = 1480, 250 + len(rows) * 116
            x0, y0 = (W - card_w) / 2, (H - card_h) / 2
            yy = y0 + 250 + k * 116
            a, bb = rows[k]
            d.text((x0 + card_w / 4, yy), a.strip(),
                   font=font(FONT_BODY, 44), fill=INK, anchor="mm")
            d.text((x0 + card_w * 3 / 4, yy), bb.strip(),
                   font=font(FONT_BODY, 44), fill=INK, anchor="mm")
        elif btype == "STEPS":
            # 阶梯图：5 级台阶从下往上
            sx = 220 + k * 300
            sy = 770 - k * 105
            d.rounded_rectangle((sx, sy, sx + 270, sy + 130), radius=20,
                                fill=(0, 0, 0, 118),
                                outline=(232, 182, 76, 170), width=3)
            d.ellipse((sx + 24, sy + 34, sx + 84, sy + 94), fill=ACCENT)
            d.text((sx + 54, sy + 64), f"{k + 1}", font=font(FONT_TITLE, 32),
                   fill=(40, 30, 20), anchor="mm")
            lbl = block["lines"][k]
            f = font(FONT_BODY, 30)
            for li, ln in enumerate(wrap(d, lbl, f, 190)):
                d.text((sx + 110, sy + 46 + li * 38), ln, font=f,
                       fill=INK, anchor="lm")
        layers.append(img)
    return layers


def make_deco_layer(seed):
    """浮动光斑装饰层（配合视差）。"""
    rnd = random.Random(seed)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for _ in range(12):
        x = rnd.uniform(0, W)
        y = rnd.uniform(80, H - 120)
        r = rnd.uniform(40, 170)
        alpha = rnd.randint(8, 30)
        col = rnd.choice([(232, 182, 76), (255, 255, 255), (150, 200, 220)])
        d.ellipse((x - r, y - r, x + r, y + r), fill=col + (alpha,))
    for _ in range(6):
        x = rnd.uniform(0, W)
        y = rnd.uniform(100, H - 100)
        d.line((x, y, x + rnd.uniform(60, 160), y),
               fill=(255, 255, 255, rnd.randint(20, 45)), width=2)
    img = img.filter(ImageFilter.GaussianBlur(30))
    return img
