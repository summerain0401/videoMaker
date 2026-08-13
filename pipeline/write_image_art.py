#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""长视频 AI 插画生成（阿里云百炼 wan2.7-image）。

项目制路径：默认读写 projects/001_金钱的艺术/（环境变量 PROJECT 可换项目，
--project 参数可覆盖）：
  --story    按项目 input/storyboard_narrative.json 生成卡点画面到
             项目 assets/scenes/{块}_{拍}.png
  普通模式   生成 项目 assets/art/{TITLE,END,S1..S5}.png 与
             项目 assets/cover.png（art/ 为历史底图存档，渲染不再引用）

环境变量（均可放项目根 .env，已 gitignore）：
  DASHSCOPE_API_KEY   必填，百炼 API Key
  DASHSCOPE_BASE_URL  默认 https://dashscope.aliyuncs.com
  IMAGE_MODEL         默认 wan2.7-image（经济版；质量优先可用 wan2.7-image-pro）
  IMAGE_THINKING      默认 1（开启思考模式提升质量）；设 0 关闭

用法：
  python3 pipeline/write_image_art.py              # 补齐缺失槽位
  python3 pipeline/write_image_art.py --force      # 全部重新生成
  python3 pipeline/write_image_art.py --only S1    # 只生成指定槽位
  python3 pipeline/write_image_art.py --story --beats 00_0 02_1
  python3 pipeline/write_image_art.py --force --only COVER

失败不影响渲染：某张缺失时引擎自动回退程序化底图。
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proj as PJ


def P(*parts):
    return os.path.join(ROOT, *parts)


def PROJ(*parts):
    """当前项目内路径（input/assets/audio/output）。"""
    return PJ.PROJ(*parts)


SLOTS = ["TITLE", "END", "S1", "S2", "S3", "S4", "S5", "COVER"]
DEFAULT_BASE = "https://dashscope.aliyuncs.com"
DEFAULT_MODEL = "wan2.7-image"

STYLE = ("暖色调温馨明亮的抽象知识感数字插画，奶油色与暖黄为主，柔和阳光"
         "与暖色光晕、细腻颗粒质感、微光几何线条，画面干净通透不阴暗，"
         "电影感柔光布光，16:9 横构图，画面中央与左侧预留大面积留白空间"
         "以便叠加文字卡片，画面中不要出现任何文字、字母、人脸或人物。")

STORY_STYLE = ("插画叙事风格：手绘电影感插画，人物形象自然、动作与情绪真实，"
               "场景有故事感，整体氛围温暖温馨、明亮通透，暖色调为主"
               "（暖黄、奶油色、柔和阳光与灯光），画面干净明亮、不阴暗不压抑，"
               "电影感构图与柔光布光，16:9 横构图，画面中不要出现任何文字、"
               "字母、图表、标语或水印，底部 15% 区域保持简洁以预留给字幕。")

PROMPTS = {
    "TITLE": "一本微微发光的书放在暖色书桌上，金色光点与环形钟表齿轮的"
             "柔和轮廓环绕，窗外透进温暖的午后阳光，象征时间与财富的积累，"
             "顶部与中央留白。",
    "END": "暖色台灯照亮一张整洁的书桌，桌上放着一本合上的书，窗外是"
           "温暖的金色黄昏，安静而留有余韵，中央留白。",
    "S1": "暖色调客厅里，手机屏幕的柔光与窗边暮色交织，购物袋与信用卡的"
          "柔和剪影轻轻漂浮，温馨中带一点若有所思，中央留白。",
    "S2": "暖色街角两条岔路延伸，一侧是明亮的橱窗，一侧是朴素温暖的小店"
          "灯光，象征比较与两种人生，阳光和煦，中央留白。",
    "S3": "一条金色指数曲线在柔和日光中从左侧缓缓升起，光点沿曲线上升，"
          "暖色背景中的时间刻度与钟表齿轮若隐若现，象征复利与时间，"
          "中央留白。",
    "S4": "五枚暖金色的几何阶梯状模块沐浴在晨光中逐级升高，柔和的暖色光晕，"
          "象征可操作的工具与步骤，画面明亮通透，中央留白。",
    "S5": "开阔的暖色天际，晨光从云隙洒下，金色光尘缓缓飘落，温暖宁静"
          "自由，画面明亮通透，中央留白。",
    "COVER": "暖色书籍主题封面：一本厚书立在暖色桌面上，金色晨光洒落，"
             "书页微微发光，四周暖色光晕与几何光点环绕，正面构图，"
             "顶部与中央预留大面积留白以便叠加标题文字，温暖积极充满希望。",
}


def load_api_key():
    """密钥：环境变量优先，其次项目根 .env（绝不打印值）。"""
    if os.environ.get("DASHSCOPE_API_KEY"):
        return os.environ["DASHSCOPE_API_KEY"]
    env_path = P(".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if "=" in line and line.split("=", 1)[0].strip() == \
                        "DASHSCOPE_API_KEY":
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def generate_image(slot, model, base, thinking, prompt=None, ref_images=None,
                   out_path=None):
    key = load_api_key()
    if not key:
        print("缺少 DASHSCOPE_API_KEY：请配置环境变量或项目根 .env。")
        sys.exit(2)
    if prompt is None:
        prompt = PROMPTS[slot] + STYLE
    content = []
    if ref_images:
        # 预留参考图接口（同一主角一致性，本轮不启用）
        import base64
        for rp in ref_images:
            with open(rp, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            content.append({"image": f"data:image/png;base64,{b64}"})
    content.append({"text": prompt})
    body = {
        "model": model,
        "input": {"messages": [{"role": "user", "content": content}]},
        "parameters": {"size": "1920*1080", "n": 1,
                       "watermark": False, "thinking_mode": thinking},
    }
    base = base.rstrip("/")
    if base.endswith("/api/v1"):
        base = base[: -len("/api/v1")]
    url = base + "/api/v1/services/aigc/multimodal-generation/generation"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"API 请求失败（{e.code}）：{e.read().decode('utf-8')[:300]}")
        return None
    except Exception as e:
        print(f"网络请求失败：{e}")
        return None
    try:
        img_url = data["output"]["choices"][0]["message"]["content"][0]["image"]
    except (KeyError, IndexError, TypeError):
        print(f"响应格式异常：{json.dumps(data, ensure_ascii=False)[:300]}")
        return None
    try:
        with urllib.request.urlopen(img_url, timeout=600) as resp:
            png = resp.read()
    except Exception as e:
        print(f"图片下载失败：{e}")
        return None
    if not png.startswith(b"\x89PNG"):
        print(f"警告：{slot} 下载内容不是 PNG（{len(png)} 字节），仍写入文件。")
    path = out_path or os.path.join(PROJ("assets", "art"),
                                    f"{slot}.png")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(png)
    return path


def run_story(args, model, base, thinking):
    """叙事模式：按分镜 JSON 生成每块每拍画面。"""
    story_path = args.story if args.story != "auto" \
        else PROJ("input", "storyboard_narrative.json")
    if not os.path.exists(story_path):
        print(f"未找到分镜 JSON：{story_path}")
        sys.exit(1)
    with open(story_path, encoding="utf-8") as f:
        story = json.load(f)
    want = set(args.beats or [])
    failed = 0
    for sb in story["blocks"]:
        bi = sb["block_idx"]
        for be in sb["beats"]:
            prompt = be.get("prompt", "").strip()
            if not prompt:
                continue  # 无配音块（阶段页/首尾页）用现有 S1-S5/TITLE/END
            key = f"{bi:02d}_{int(be['beat_idx'])}"
            if want and key not in want:
                continue
            out = PROJ("assets", "scenes", f"{key}.png")
            if os.path.exists(out) and not args.force:
                print(f"跳过（已存在）：{out}")
                continue
            full_prompt = prompt + STORY_STYLE
            print(f"生成 块{bi} 拍{be['beat_idx']}（{be.get('shot', 'medium')}）…")
            path = generate_image("story", model, base, thinking,
                                  prompt=full_prompt, out_path=out)
            if path:
                print(f"已保存：{path}")
            else:
                failed += 1
    if failed:
        print(f"完成，{failed} 张失败；渲染时会回退到阶段主图或程序化底图。")
        sys.exit(1)
    print("卡点画面全部完成。")


def main():
    ap = argparse.ArgumentParser(description="长视频 AI 插画底图生成（通义万相）")
    ap.add_argument("--project", default=None,
                    help="项目 id（默认取环境变量 PROJECT，缺省 001）")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的图片")
    ap.add_argument("--only", nargs="+", choices=SLOTS,
                    help="只生成指定槽位，如 --only TITLE S1")
    ap.add_argument("--story", nargs="?", const="auto", default=None,
                    help="叙事模式：按分镜 JSON 生成卡点画面"
                         "（默认 auto 读项目 input/storyboard_narrative.json）")
    ap.add_argument("--beats", nargs="+", default=None,
                    help="--story 模式下只生成指定拍，如 00_0 02_1")
    ap.add_argument("--model", default=None, help="覆盖 IMAGE_MODEL")
    ap.add_argument("--base", default=None, help="覆盖 DASHSCOPE_BASE_URL")
    args = ap.parse_args()

    if args.project:
        PJ.CURRENT_ID = args.project
    PJ.project_dir()

    model = args.model or os.environ.get("IMAGE_MODEL", DEFAULT_MODEL)
    base = args.base or os.environ.get("DASHSCOPE_BASE_URL", DEFAULT_BASE)
    thinking = os.environ.get("IMAGE_THINKING", "1") != "0"
    if args.story is not None:
        run_story(args, model, base, thinking)
        return
    slots = args.only or SLOTS
    failed = 0
    for slot in slots:
        out_path = PROJ("assets", "cover.png") if slot == "COVER" \
            else None
        path = out_path or PROJ("assets", "art", f"{slot}.png")
        if os.path.exists(path) and not args.force:
            print(f"跳过（已存在）：{slot}")
            continue
        print(f"生成 {slot}（{model}，thinking={thinking}）…")
        out = generate_image(slot, model, base, thinking, out_path=out_path)
        if out:
            print(f"已保存：{out}")
        else:
            failed += 1
    if failed:
        print(f"完成，{failed} 张失败；缺失时渲染会自动回退程序化底图。")
        sys.exit(1)
    print("全部完成。")


if __name__ == "__main__":
    main()
