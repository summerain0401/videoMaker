#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""长视频 AI 插画生成（阿里云百炼 wan2.7-image）。

项目制路径：默认读写 projects/001_金钱的艺术/（环境变量 PROJECT 可换项目，
--project 参数可覆盖）：
  --story      按项目 input/storyboard_narrative.json 生成卡点画面到
               项目 assets/scenes/{块}_{拍}.png
  普通模式     生成 项目 assets/art/{TITLE,END,S1..S5}.png 与
               （art/ 为历史底图存档，渲染不再引用）
  --tone-check 扫描项目 scenes/ 输出阴郁风险报告到 output/tone_report.md

基调控制：提示词 = 拍提示词 + WARM_BASE（不变底线）+ 项目 visual_style
变体（防视频间雷同）+ 负面清单；--force 重绘时自动追加提亮暖化指令。

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
  python3 pipeline/write_image_art.py --tone-check

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
import tone


def P(*parts):
    return os.path.join(ROOT, *parts)


def PROJ(*parts):
    """当前项目内路径（input/assets/audio/output）。"""
    return PJ.PROJ(*parts)


SLOTS = ["TITLE", "END", "S1", "S2", "S3", "S4", "S5"]
DEFAULT_BASE = "https://dashscope.aliyuncs.com"
DEFAULT_MODEL = "wan2.7-image"

STYLE = ("暖色调温馨明亮的抽象知识感数字插画，奶油色与暖黄为主，柔和阳光"
         "与暖色光晕、细腻颗粒质感、微光几何线条，画面干净通透不阴暗，"
         "电影感柔光布光，16:9 横构图，画面中央与左侧预留大面积留白空间"
         "以便叠加文字卡片，画面中不要出现任何文字、字母、人脸或人物。")

# 不变底线：所有项目/所有拍共同遵守，优先于拍提示词中的氛围描述
WARM_BASE = ("插画叙事风格：手绘电影感插画，人物形象自然、动作与情绪真实，"
             "场景有故事感。画面基调必须温暖温馨、明亮通透，以暖黄、奶油色、"
             "蜜色光为主色调，柔和阳光或暖色灯光为光源，画面干净明亮；"
             "不允许冷色调、灰暗天空、昏暗房间或大面积暗部；即使表达疲惫、"
             "焦虑或对比情绪，人物与环境也必须被暖色光线包裹，"
             "保持治愈而不压抑。电影感构图与柔光布光，16:9 横构图，"
             "画面中不要出现任何文字、字母、图表、标语或水印，"
             "底部 15% 区域保持简洁以预留给字幕。")

# 负面清单：显式排除，兜底模型理解
NEGATIVE = ("画面中禁止出现：冷色调、灰暗天空、昏暗房间、大面积阴影、"
            "阴郁压抑氛围、恐怖惊悚元素、雨雪阴天、哭泣绝望等消极画面；"
            "所有场景必须以暖色光照明亮呈现。")

# 重绘暖化指令：--force 重绘时自动追加
WARM_BOOST = ("请把画面整体提亮，以暖色灯光与阳光为主要光源，"
              "消除所有冷色、灰暗与大面积暗部，让情绪即使紧张也被暖光包裹。")

# 项目风格变体表：共同底线不变，变体不同（防视频间雷同）
VARIANT_STYLES = {
    "奶油暖金·手绘电影感": "主色奶油色与暖金黄，蜜色柔光，"
                             "手绘电影感插画质感，细腻颗粒与柔光光晕",
    "焦糖蜜橙·水彩": "主色焦糖棕与蜜橙，暖橙阳光，水彩晕染质感，通透淡雅",
    "蜜桃粉·扁平治愈": "主色蜜桃粉与奶白，柔和粉金光线，"
                         "扁平治愈系插画质感，简洁明快",
    "燕麦米·油画质感": "主色燕麦米与亚麻棕，暖黄烛光氛围，"
                         "厚涂油画质感，沉稳温暖",
    "琥珀棕·复古版画": "主色琥珀棕与赭石，暖黄灯影，"
                         "复古版画线条质感，故事感强",
}
DEFAULT_VARIANT = "奶油暖金·手绘电影感"

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
}


def style_suffix(meta):
    """按项目 visual_style 组装风格后缀（不变底线 + 变体 + 负面清单）。"""
    vs = (meta or {}).get("visual_style") or {}
    variant = vs.get("variant") or DEFAULT_VARIANT
    desc = VARIANT_STYLES.get(variant, VARIANT_STYLES[DEFAULT_VARIANT])
    return " " + WARM_BASE + " " + desc + " " + NEGATIVE


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
    meta = PJ.read_meta()
    suffix = style_suffix(meta)
    boost = WARM_BOOST if args.force else ""
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
            full_prompt = prompt + suffix + (" " + boost if boost else "")
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


def tone_check():
    """扫描项目 scenes/ 与分镜提示词，输出阴郁风险报告（不调 API）。"""
    scenes_dir = PROJ("assets", "scenes")
    if not os.path.isdir(scenes_dir):
        print(f"未找到卡点画面目录：{scenes_dir}")
        sys.exit(1)
    prompt_map = {}
    story_path = PROJ("input", "storyboard_narrative.json")
    if os.path.exists(story_path):
        try:
            with open(story_path, encoding="utf-8") as f:
                story = json.load(f)
            for sb in story.get("blocks", []):
                for be in sb.get("beats", []):
                    key = f"{sb['block_idx']:02d}_{int(be['beat_idx'])}"
                    prompt_map[key] = be.get("prompt", "")
        except Exception as e:
            print(f"警告：分镜读取失败（{e}），报告仅含图像指标。")
    rows = []
    for fn in sorted(os.listdir(scenes_dir)):
        if not fn.endswith(".png"):
            continue
        key = fn[:-4]
        stat = tone.analyze_image(os.path.join(scenes_dir, fn))
        reasons = tone.risk_reasons(stat)
        pw = tone.prompt_risks(prompt_map.get(key, ""))
        if pw:
            reasons.append(f"提示词含阴郁词：{'/'.join(pw)}")
        rows.append({"file": fn, "stat": stat, "reasons": reasons})
    risk_rows = [r for r in rows if r["reasons"]]
    out = PROJ("output", "tone_report.md")
    lines = ["# 色调风险报告", "",
             f"阈值：亮度 <{tone.THRESH_LUM:.0f} / "
             f"暖度 <{tone.THRESH_WARM:.0f} / "
             f"暗部占比 >{tone.THRESH_DARK * 100:.0f}%",
             "", f"共 {len(rows)} 张，风险 {len(risk_rows)} 张。", "",
             "| 文件 | 亮度 | 暖度 | 暗部占比 | 风险原因 |", "|---|---|---|---|---|"]
    for r in rows:
        st = r["stat"] or {}
        lines.append(f"| {r['file']} | {st.get('luminance', '-')} | "
                     f"{st.get('warmth', '-')} | {st.get('dark_ratio', '-')} | "
                     f"{'；'.join(r['reasons']) or '达标'} |")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"色调检查完成：{len(rows)} 张，风险 {len(risk_rows)} 张。"
          f"报告：{out}")
    if risk_rows:
        print("风险图（建议暖化重绘）：")
        for r in risk_rows:
            print(" -", r["file"], "；".join(r["reasons"]))
    return risk_rows


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
    ap.add_argument("--tone-check", action="store_true",
                    help="扫描项目 scenes/ 输出阴郁风险报告（不调 API）")
    ap.add_argument("--model", default=None, help="覆盖 IMAGE_MODEL")
    ap.add_argument("--base", default=None, help="覆盖 DASHSCOPE_BASE_URL")
    args = ap.parse_args()

    if args.project:
        PJ.CURRENT_ID = args.project
    PJ.project_dir()

    model = args.model or os.environ.get("IMAGE_MODEL", DEFAULT_MODEL)
    base = args.base or os.environ.get("DASHSCOPE_BASE_URL", DEFAULT_BASE)
    thinking = os.environ.get("IMAGE_THINKING", "1") != "0"
    if args.tone_check:
        tone_check()
        return
    if args.story is not None:
        run_story(args, model, base, thinking)
        return
    slots = args.only or SLOTS
    failed = 0
    for slot in slots:
        path = PROJ("assets", "art", f"{slot}.png")
        if os.path.exists(path) and not args.force:
            print(f"跳过（已存在）：{slot}")
            continue
        print(f"生成 {slot}（{model}，thinking={thinking}）…")
        out = generate_image(slot, model, base, thinking)
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
