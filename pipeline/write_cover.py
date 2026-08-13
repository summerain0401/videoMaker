#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""封面生产线：暖色底图 + AI 标题公式文案（人工定稿）+ Pillow 双规格排版。

项目制路径：默认读写 projects/001_金钱的艺术/（环境变量 PROJECT 可换项目，
--project 参数可覆盖）。

流程：
  --generate  读项目 input/script.txt 的 TITLE 块（书名/钩子/作者），
              DeepSeek 按标题公式（时间承诺 + 书名标识 + 震撼转折）
              输出封面文案到 input/cover_draft.json
  --accept    人工审阅后定稿到 input/cover_copy.json（旧版备份 .bak）
  --render    用项目 assets/cover.png 底图排版，输出
              assets/cover_final_16x9.png（1280x720）与
              assets/cover_final_9x16.png（720x1280）
  --all       生成 → 定稿 → 渲染（一条命令）

密钥：环境变量 DEEPSEEK_API_KEY 或项目根 .env（已 gitignore）。
"""

import argparse
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proj as PJ

FONT_TITLE = "/System/Library/Fonts/STHeiti Medium.ttc"
FONT_BODY = "/System/Library/Fonts/Hiragino Sans GB.ttc"
CREAM = (252, 243, 226)
SHADOW = (58, 36, 18)

PROVIDERS = {
    "deepseek": {
        "base": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
        "key_envs": ["DEEPSEEK_API_KEY"],
    },
}

COVER_SYSTEM = """你是资深短视频封面标题专家。根据用户提供的一本书的信息，
按「标题公式」生成封面文案，让封面一眼被点击。

标题公式（三条缺一不可，融入文案）：
1. 时间承诺：如「15分钟读懂」「3个方法」——让用户知道投入小、收获确定；
2. 书名标识：书名必须出现在封面上，建立内容信任；
3. 震撼转折：打破常识的反转或痛点拷问，让人想点开。

【硬性规则】
- main：主标题，≤12 个汉字，口语化、有冲击力，可含时间承诺或震撼转折。
- sub：副标题，≤20 个汉字，一句话钩子，补充主标题的信息缺口。
- book：书名（带书名号）。
- author：作者名。
- tag：频道/期号角标（如「认知书页」「第 01 期」），未提供则为空字符串。
- 只输出 JSON，不要解释，不要 Markdown 代码块。

【输出格式】
{"main": "...", "sub": "...", "book": "《书名》", "author": "作者", "tag": ""}"""


def P(*parts):
    return os.path.join(ROOT, *parts)


def PROJ(*parts):
    """当前项目内路径（input/assets/audio/output）。"""
    return PJ.PROJ(*parts)


def load_api_key(conf):
    """密钥：环境变量优先，其次项目根 .env（绝不打印值）。"""
    for k in conf["key_envs"]:
        if os.environ.get(k):
            return os.environ[k]
    env_path = P(".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                if key.strip() in conf["key_envs"]:
                    return val.strip().strip('"').strip("'")
    return None


def call_api(user_prompt, model, repair=""):
    conf = PROVIDERS["deepseek"]
    key = load_api_key(conf)
    if not key:
        print(f"缺少 API 密钥：请设置环境变量 {conf['key_envs'][0]}，"
              f"或在项目根 .env 中填写（已 gitignore，不会进入仓库）。")
        sys.exit(2)
    base = os.environ.get("COPY_BASE_URL", conf["base"]).rstrip("/")
    model = model or os.environ.get("COPY_MODEL", conf["model"])
    system = COVER_SYSTEM
    if repair:
        system += ("\n\n【上一版存在以下问题，请逐条修正后重新输出】\n"
                   + repair)
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user_prompt}],
        "temperature": 0.7,
        "max_tokens": 1000,
    }
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"API 请求失败（{e.code}）：{e.read().decode('utf-8')[:300]}")
        sys.exit(3)
    except Exception as e:
        print(f"网络请求失败：{e}")
        sys.exit(3)
    return data["choices"][0]["message"]["content"].strip()


def extract_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("模型输出中没有 JSON")
    return json.loads(m.group(0))


def validate_copy(data):
    """校验封面文案，返回 (问题列表, 规范化 dict)。"""
    problems = []
    main = (data.get("main") or "").strip()
    sub = (data.get("sub") or "").strip()
    book = (data.get("book") or "").strip()
    author = (data.get("author") or "").strip()
    tag = (data.get("tag") or "").strip()
    if not main:
        problems.append("main 主标题缺失")
    elif len(main) > 14:
        problems.append(f"main 超长（{len(main)} 字，建议 ≤12）")
    if not sub:
        problems.append("sub 副标题缺失")
    elif len(sub) > 24:
        problems.append(f"sub 超长（{len(sub)} 字，建议 ≤20）")
    if not book:
        problems.append("book 书名缺失")
    if not author:
        problems.append("author 作者缺失")
    return problems, {"main": main, "sub": sub, "book": book,
                      "author": author, "tag": tag}


def book_info():
    """从项目 input/script.txt 提取书名/钩子/作者。"""
    sys.path.insert(0, P("pipeline"))
    import build_long as B
    blocks = B.parse_script()
    book, hook, author = B.book_meta(blocks)
    return book, hook, author


def generate(args, model):
    book, hook, author = book_info()
    if args.book:
        book = args.book
    if args.author:
        author = args.author
    meta = PJ.read_meta()
    title = meta.get("title") or ""
    lines = [f"书名：{book}", f"作者：{author}",
             f"钩子句（脚本 TITLE 第二行）：{hook or '（无）'}",
             f"项目名：{title}",
             f"角标：{args.tag or '（未提供，可留空）'}",
             "请按标题公式生成封面文案 JSON。"]
    user_prompt = "\n".join(lines)
    text = call_api(user_prompt, model)
    try:
        data = extract_json(text)
    except Exception as e:
        print(f"封面文案 JSON 解析失败：{e}")
        sys.exit(4)
    problems, copy = validate_copy(data)
    if problems:
        print("生成结果未通过校验：")
        for p in problems:
            print(" -", p)
        print("原文：", text[:300])
        sys.exit(4)
    if not copy["tag"] and args.tag:
        copy["tag"] = args.tag
    draft = PROJ("input", "cover_draft.json")
    os.makedirs(os.path.dirname(draft), exist_ok=True)
    with open(draft, "w", encoding="utf-8") as f:
        json.dump(copy, f, ensure_ascii=False, indent=2)
    print("封面文案草稿：")
    print("  主标题：", copy["main"])
    print("  副标题：", copy["sub"])
    print("  书名：", copy["book"], "｜ 作者：", copy["author"])
    print("  角标：", copy["tag"] or "（无）")
    print(f"已保存草稿：{draft}")
    print("请人工审阅后运行 --accept 定稿。")


def accept():
    draft = PROJ("input", "cover_draft.json")
    if not os.path.exists(draft):
        print(f"未找到草稿 {draft}，请先运行 --generate。")
        sys.exit(4)
    with open(draft, encoding="utf-8") as f:
        data = json.load(f)
    problems, copy = validate_copy(data)
    if problems:
        print("草稿未通过校验：")
        for p in problems:
            print(" -", p)
        sys.exit(4)
    target = PROJ("input", "cover_copy.json")
    if os.path.exists(target):
        shutil.copy2(target, target + ".bak")
    with open(target, "w", encoding="utf-8") as f:
        json.dump(copy, f, ensure_ascii=False, indent=2)
    print(f"已定稿封面文案：{target}（旧版备份 cover_copy.json.bak）")


def _font(path, size):
    return ImageFont.truetype(path, size)


def _wrap(d, text, f, max_w):
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


def _gradient(size, peak_alpha, start_ratio, end_ratio, color):
    """竖向暖色半透明渐变遮罩（上或下缘），color 为不含 alpha 的 RGB。"""
    w, h = size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for y in range(int(h * start_ratio), int(h * end_ratio)):
        t = (y - h * start_ratio) / max(1.0, h * (end_ratio - start_ratio))
        alpha = int(peak_alpha * (1 - t))
        d.line([(0, y), (w, y)], fill=color + (alpha,))
    return layer


def _draw_texts(base, copy, sizes):
    """在底图上排版：主标题/副标题居中偏上，书名作者左下，角标右下。"""
    w, h = base.size
    top = _gradient((w, h), 130, 0.0, 0.55, (74, 50, 30))
    bot = _gradient((w, h), 110, 0.72, 1.0, (74, 50, 30))
    img = Image.alpha_composite(base.convert("RGBA"), top)
    img = Image.alpha_composite(img, bot)
    d = ImageDraw.Draw(img)
    f_main = _font(FONT_TITLE, sizes["main"])
    f_sub = _font(FONT_BODY, sizes["sub"])
    f_small = _font(FONT_BODY, sizes["small"])
    # 主标题（≤2 行）
    lines = _wrap(d, copy["main"], f_main, int(w * 0.78))
    line_h = int(sizes["main"] * 1.25)
    y = int(h * 0.20)
    for ln in lines[:2]:
        for dx, dy in ((2, 3), (0, 0)):
            d.text((w / 2 + dx, y + dy), ln, font=f_main,
                   fill=SHADOW if dy else CREAM, anchor="mm")
        y += line_h
    # 副标题
    y += int(sizes["main"] * 0.15)
    d.text((w / 2, y), copy["sub"], font=f_sub, fill=CREAM, anchor="mm")
    # 书名 + 作者（左下）
    d.text((int(w * 0.05), h - int(h * 0.10)),
           f"{copy['book']} ｜ {copy['author']}", font=f_small,
           fill=CREAM, anchor="lm")
    # 角标（右下）
    if copy.get("tag"):
        d.text((int(w * 0.95), h - int(h * 0.10)), copy["tag"],
               font=f_small, fill=CREAM, anchor="rm")
    return img


def render():
    base_path = PROJ("assets", "cover.png")
    if not os.path.exists(base_path):
        print(f"未找到封面底图 {base_path}，请先运行 "
              f"write_image_art.py --force --only COVER。")
        sys.exit(1)
    target = PROJ("input", "cover_copy.json")
    draft = PROJ("input", "cover_draft.json")
    if os.path.exists(target):
        with open(target, encoding="utf-8") as f:
            data = json.load(f)
    elif os.path.exists(draft):
        print("提示：尚未 --accept 定稿，渲染使用草稿。")
        with open(draft, encoding="utf-8") as f:
            data = json.load(f)
    else:
        print(f"未找到封面文案（{target} / {draft}），请先 --generate。")
        sys.exit(1)
    problems, copy = validate_copy(data)
    if problems:
        print("封面文案未通过校验：")
        for p in problems:
            print(" -", p)
        sys.exit(4)
    cover = Image.open(base_path).convert("RGB")
    # 16:9 主封面（1280x720）
    h16 = cover.resize((1280, 720), Image.LANCZOS)
    img16 = _draw_texts(h16, copy,
                        {"main": 84, "sub": 34, "small": 26})
    out16 = PROJ("assets", "cover_final_16x9.png")
    img16.convert("RGB").save(out16)
    # 9:16 竖版（720x1280）：放大铺满后居中裁切
    scale = 1280 / cover.height
    v = cover.resize((int(cover.width * scale), 1280), Image.LANCZOS)
    x0 = (v.width - 720) // 2
    v = v.crop((x0, 0, x0 + 720, 1280))
    img9 = _draw_texts(v, copy,
                       {"main": 64, "sub": 30, "small": 24})
    out9 = PROJ("assets", "cover_final_9x16.png")
    img9.convert("RGB").save(out9)
    print(f"封面渲染完成：\n  16:9 → {out16}\n  9:16 → {out9}")


def main():
    ap = argparse.ArgumentParser(description="封面生产线（AI 标题公式 + 双规格排版）")
    ap.add_argument("--project", default=None,
                    help="项目 id（默认取环境变量 PROJECT，缺省 001）")
    ap.add_argument("--generate", action="store_true",
                    help="DeepSeek 按标题公式生成封面文案草稿")
    ap.add_argument("--accept", action="store_true",
                    help="人工审阅后定稿封面文案")
    ap.add_argument("--render", action="store_true",
                    help="用 cover.png 底图渲染 16:9 与 9:16 双规格封面")
    ap.add_argument("--all", action="store_true",
                    help="一键：生成 → 定稿 → 渲染")
    ap.add_argument("--model", default=None, help="覆盖默认模型名")
    ap.add_argument("--book", default=None, help="书名（覆盖脚本 TITLE）")
    ap.add_argument("--author", default=None, help="作者（覆盖脚本 TITLE）")
    ap.add_argument("--tag", default="", help="角标文案，如「认知书页」")
    args = ap.parse_args()

    if args.project:
        PJ.CURRENT_ID = args.project
    PJ.project_dir()

    if args.all:
        generate(args, args.model)
        accept()
        render()
        return
    if args.generate:
        generate(args, args.model)
    if args.accept:
        accept()
    if args.render:
        render()
    if not (args.generate or args.accept or args.render):
        ap.print_help()


if __name__ == "__main__":
    main()
