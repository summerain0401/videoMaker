#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""2D Q 版插画分镜生成流水线（docs/插画Prompts.md 三层架构）。

流程：项目 input/storyboard_narrative.json（中文拍）→ DeepSeek 按块批量
解析为 character_id + action_props_en → 装配引擎按「全局 2D 底模 + 暖色
底线/项目变体 + 角色预设 + 动作 + 景别 + 16:9」拼装英文 final_image_prompt
→ 写入项目 input/storyboard_output.json → pipeline/write_image_art.py
--chibi 生成卡点画面。

角色库：全局 assets/characters.json（默认）+ 项目 input/characters.json
（可选，覆盖/追加，项目优先）。角色定义仅含外观服装标志物，不含动作情绪。

用法：
  python3 pipeline/write_chibi_prompts.py            # 全量解析 + 装配
  python3 pipeline/write_chibi_prompts.py --blocks 0 # 只解析块 0（试点）
  python3 pipeline/write_chibi_prompts.py --beats 00_0 00_1
  python3 pipeline/write_chibi_prompts.py --check    # 离线校验
  python3 pipeline/write_chibi_prompts.py --assemble-only  # 改变体后重装配

密钥：环境变量 DEEPSEEK_API_KEY 或项目根 .env（已 gitignore）。
"""

import argparse
import datetime
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proj as PJ
from write_image_art import (GLOBAL_2D_STYLE_PREFIX, BRIGHT_BASE_EN,
                             variant_en)
import tone

STYLE_ID = "2D_CHIBI_VECTOR_FINANCE"
SHOT_EN = {"wide": "wide shot", "medium": "medium shot",
           "close": "close-up shot"}
CLEAN_NO_TEXT_EN = "clean composition, no text, no UI, no stickers"
COMPOSITION_SAFE_EN = ("full-bleed artwork fills the entire frame, "
                       "continue illustration to the bottom edge, "
                       "no solid color band, no empty strip, "
                       "no bottom bar, no letterbox")
FULL_BLEED_EN = ("full-bleed edge-to-edge composition, "
                 "no frame, no border, no margin")
LINEART_EN = ("uniform bold clean line-art, consistent outline thickness, "
              "same art style across all characters")
TWO_PERSON_EN = ("exactly two people, strict two-way split composition, "
                 "one person on the left, one on the right, "
                 "no third person, no crowd, no bystanders")
THEME_BG_EN = {
    "cool": ("pale cool gray-blue background, muted cyan-gray tones, "
             "calm desaturated cool palette, bright but cool"),
    "warm": ("warm apricot and light golden background, "
             "soft golden sunlight, bright cozy warm palette"),
    "neutral": ("soft cream and light beige background, "
                "gentle neutral warm palette"),
}
MAX_RETRY = 2
MAX_ACTION = 200
CTA_WORDS = ["咱们开始", "准备好了吗", "关注", "点赞", "收藏", "谢谢大家"]
FALLBACK_CHAR = "young_pro"

# 情绪矛盾检测：口播含消极语义但动作/情绪积极 → 判定冲突（回喂重试）
DARK_NARR = ["空虚", "没钱", "焦虑", "负债", "余额见底", "见底", "恐慌", "穷"]
BRIGHT_ACT = ["relaxed", "happy", "smil", "comfortable", "high balance",
              "content", "calm confident", "joyful", "satisfied"]

PROVIDERS = {
    "deepseek": {
        "base": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
        "key_envs": ["DEEPSEEK_API_KEY"],
    },
}

SYSTEM_PROMPT = """你是财商视频分镜翻译与角色指派引擎。用户会给出一段中文
叙事分镜（一个块的若干拍，含每拍对应的口播句子），请把每一拍转换为结构化的
英文动作描述、角色绑定与情绪标签。

【执行规则】
1. 角色分配：根据分镜上下文与主题一致性，从候选角色列表中为每一拍选取唯一的
   character_id；纯概念/道具/无人物的拍用 "none"。
2. 动作提炼：提取为纯动作、面部表情、交互金融道具（如 empty wallet, piggy bank,
   credit card, k-line chart, savings account）；禁止包含画风、渲染、材质、
   景别、背景修饰词汇。
3. 画面无文字：画面中禁止出现任何文字、数字标签、贴纸、气泡框、弹幕、图表与
   UI；手机界面、账单、招牌等道具保持空白或简洁剪影，所有文字与数据由后期叠加。
4. 情绪-画面映射（情绪以对应口播为准，画面提示词的氛围描述仅供场景参考；
   若提示词情绪与口播冲突，以口播为准，并把提示词中的矛盾情绪视为错误描述）：
   - 空虚/没钱/焦虑/负债/余额见底 → anxious expression, empty wallet,
     near-zero balance，紧张但不绝望（仍处暖光环境）；严禁出现 relaxed、
     happy、smiling、高额存款等矛盾情绪与道具
   - 存款/富足/稳定 → comfortable savings, calm confident expression
   - 对比 → 暖光 split 构图，两侧人物/场景情绪分明
   - 觉醒/希望/转机 → hopeful expression, sunrise or warm breakthrough light
5. 主题一致性：本片为职场青年/都市成人财商主题；禁止出现儿童、小学生、学生背包、
   卡通动物等年龄或身份不符形象；同一角色在连续拍中的外观由角色库保证一致。
   对比拍（口播含「对比/两套人生/挣得少却变富/年薪百万」等）必须输出两个不同角色：
   character_id 为左侧/主体，secondary_character_id 为右侧/对比方
   （如左 frugal_girl 休闲喝茶、右 stressed_worker 豪车前焦虑），两角色不得相同；
   对比画面只允许左右两人，禁止第三人、人群、背景路人。
6. 语种规范：action_props 与 emotion 必须为紧凑英文，action_props ≤200 字符、
    emotion ≤60 字符，越简洁越好。
7. 输出的 beats 数组必须覆盖该块全部拍（beat_idx 与输入一一对应），
   不得遗漏、不得新增、不得重复。
8. 背景色跟随情绪（action_props 中不要写死背景颜色，交给装配层决定）：
   - 焦虑/困境/反思 → 冷灰蓝/淡青灰背景，明亮但不压抑；
   - 认知/启发/希望 → 暖杏色/淡金黄背景；
   - 其余 → 中性奶油/米色背景。
9. CTA 收尾拍（口播含「咱们开始/准备好了吗/关注/点赞/收藏/谢谢大家」）必须
   积极自信、蓄势待发：confident smile, determined look, clenching fist
   with enthusiasm, ready to take action。

候选角色列表：
{character_list}

【输出格式（只输出 JSON，不要解释，不要 Markdown 代码块）】
{"beats": [{"beat_idx": 0, "character_id": "young_pro",
  "action_props": "looking at empty wallet on desk with anxious expression",
  "emotion": "anxious, empty wallet",
  "secondary_character_id": ""}]}"""


def P(*parts):
    return os.path.join(ROOT, *parts)


def PROJ(*parts):
    """当前项目内路径（input/assets/audio/output）。"""
    return PJ.PROJ(*parts)


def load_characters():
    """合并全局与项目角色库（项目优先覆盖/追加）。"""
    chars = {}
    g = P("assets", "characters.json")
    if os.path.exists(g):
        with open(g, encoding="utf-8") as f:
            chars.update(json.load(f))
    pj = PROJ("input", "characters.json")
    if os.path.exists(pj):
        with open(pj, encoding="utf-8") as f:
            chars.update(json.load(f))
    if not chars:
        print("未找到角色库（assets/characters.json）。")
        sys.exit(1)
    return chars


def load_story():
    path = PROJ("input", "storyboard_narrative.json")
    if not os.path.exists(path):
        print(f"未找到分镜 JSON：{path}")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_api_key(conf):
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


def call_api(user_prompt, model, repair="", char_list=""):
    conf = PROVIDERS["deepseek"]
    key = load_api_key(conf)
    if not key:
        print(f"缺少 API 密钥：请设置环境变量 {conf['key_envs'][0]}，"
              f"或在项目根 .env 中填写（已 gitignore）。")
        sys.exit(2)
    base = os.environ.get("COPY_BASE_URL", conf["base"]).rstrip("/")
    model = model or os.environ.get("COPY_MODEL", conf["model"])
    system = SYSTEM_PROMPT.replace("{character_list}", char_list)
    if repair:
        system += ("\n\n【上一版存在以下问题，请逐条修正后重新输出该块完整 JSON】\n"
                   + repair)
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user_prompt}],
        "temperature": 0.5,
        "max_tokens": 4000,
        "thinking": {"type": "disabled"},
    }
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
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


def build_block_view(sb, beats):
    sub_map = {s["id"]: s["text"] for s in sb.get("subtitles", [])}
    lines = [f"块 {sb['block_idx']}（{sb['head']}）分镜拍："]
    for be in beats:
        sents = [sub_map[i] for i in be.get("sentence_ids", [])
                 if i in sub_map]
        line = f"拍 {be['beat_idx']}（{be.get('shot', 'medium')}）"
        if sents:
            line += "　对应口播：" + " ｜ ".join(sents)
        line += "　画面提示词：" + be["prompt"]
        lines.append(line)
    lines.append("请根据对应口播判断情绪，输出该块全部拍的 beats JSON。")
    return "\n".join(lines)


def validate_parse(raw, expected, char_ids, narrations=None):
    """校验单块 LLM 输出，返回 (问题列表, {beat_idx: (char_id, action)} 或 None)。"""
    problems = []
    try:
        data = extract_json(raw)
    except Exception as e:
        return [f"JSON 解析失败：{e}"], None
    beats = data.get("beats", [])
    got = {b.get("beat_idx") for b in beats}
    if got != set(expected):
        problems.append(f"拍号不匹配：期望 {sorted(expected)}，"
                        f"实际 {sorted(got)}")
    out = {}
    for b in beats:
        idx = b.get("beat_idx")
        cid = b.get("character_id")
        act = (b.get("action_props") or "").strip()
        emo = (b.get("emotion") or "").strip()
        sec = (b.get("secondary_character_id") or "").strip() or None
        if cid not in char_ids:
            problems.append(f"拍 {idx} character_id 非法：{cid}")
        if sec is not None and sec not in char_ids:
            problems.append(f"拍 {idx} secondary_character_id 非法：{sec}")
        if not act:
            problems.append(f"拍 {idx} action_props 缺失")
        elif len(act) > MAX_ACTION:
            problems.append(f"拍 {idx} action_props 超长（{len(act)}）")
        elif re.search(r"[\u4e00-\u9fff]", act):
            problems.append(f"拍 {idx} action_props 含中文，必须全英文")
        if not emo:
            problems.append(f"拍 {idx} emotion 缺失")
        elif len(emo) > 60:
            problems.append(f"拍 {idx} emotion 超长（{len(emo)}）")
        elif re.search(r"[\u4e00-\u9fff]", emo):
            problems.append(f"拍 {idx} emotion 含中文，必须全英文")
        nar = (narrations or {}).get(idx, "")
        if any(w in nar for w in DARK_NARR) and \
                not any(k in act.lower()
                        for k in ("split", "contrast", "compare")) and \
                any(w in act.lower() for w in BRIGHT_ACT):
            problems.append(f"拍 {idx} 情绪与口播冲突：口播含消极语义，"
                            f"但动作含积极表达（{act[:40]}）")
        out[idx] = (cid, act, emo, sec)
    return problems, out if not problems else None


def assemble_prompt(be, char_prompt, meta, chars=None):
    """装配公式：全局 2D 底模 + 暖色底线 + 项目变体 + 角色 + 动作 + 景别 + 16:9。"""
    theme = tone.theme_for(be.get("emotion", ""))
    sec = be.get("secondary_character_id")
    char_section = char_prompt
    if sec and chars and sec != be.get("character_id"):
        sec_meta = chars.get(sec) or {}
        sec_prompt = sec_meta.get("prompt", "")
        sec_anchor = sec_meta.get("anchor", "")
        if sec_anchor:
            sec_prompt += "，" + sec_anchor
        if be.get("character_id"):
            pri_meta = chars.get(be["character_id"]) or {}
            pri_anchor = pri_meta.get("anchor", "")
            if pri_anchor:
                char_prompt += "，" + pri_anchor
        char_section = (f"split composition, left side: {char_prompt}, "
                        f"right side: {sec_prompt}")
    elif chars and be.get("character_id"):
        anchor = (chars.get(be["character_id"]) or {}).get("anchor", "")
        if anchor:
            char_section += "，" + anchor
    parts = [GLOBAL_2D_STYLE_PREFIX, BRIGHT_BASE_EN, variant_en(meta),
             FULL_BLEED_EN, LINEART_EN, THEME_BG_EN[theme],
             CLEAN_NO_TEXT_EN, COMPOSITION_SAFE_EN]
    if char_section:
        parts.append(char_section)
    if sec and chars and sec != be.get("character_id"):
        parts.append(TWO_PERSON_EN)
    parts.append(be["action_props"])
    parts.append(SHOT_EN.get(be["shot"], "medium shot"))
    return ", ".join(parts) + ", --ar 16:9"


def assign_character_safety_guard(parsed_beat, narration="",
                                  fallback_char=FALLBACK_CHAR):
    """收尾/未识别分镜强制绑定主角，防止随机生成无关角色。
    检查画面提示词 + 对应口播文本中的 CTA 词。"""
    raw_text = ((parsed_beat.get("original_cn") or "") + " " +
                (narration or ""))
    char_id = parsed_beat.get("character_id", "none")
    if any(cta in raw_text for cta in CTA_WORDS):
        return fallback_char
    if char_id == "none" and any(k in raw_text for k in ["我", "你", "咱们"]):
        return fallback_char
    return char_id


def parse_blocks(args, story, chars, meta, out_path):
    """按块批量解析 + 装配，返回输出 JSON。"""
    char_ids = list(chars.keys())
    block_sel = set(int(x) for x in args.blocks.split(",")
                    if x.strip()) if args.blocks else None
    beat_sel = set(args.beats or [])
    output_blocks = []
    total_beats = 0
    for sb in story["blocks"]:
        bi = sb["block_idx"]
        if block_sel is not None and bi not in block_sel:
            continue
        beats = [be for be in sb["beats"]
                 if (be.get("prompt") or "").strip()]
        if beat_sel:
            beats = [be for be in beats
                     if f"{bi:02d}_{int(be['beat_idx'])}" in beat_sel]
        if not beats:
            continue
        view = build_block_view(sb, beats)
        expected = [int(be["beat_idx"]) for be in beats]
        sub_map = {s["id"]: s["text"] for s in sb.get("subtitles", [])}
        narrations = {}
        for be in beats:
            narrations[int(be["beat_idx"])] = " ｜ ".join(
                sub_map[i] for i in be.get("sentence_ids", [])
                if i in sub_map)
        result = None
        problems = []
        for attempt in range(MAX_RETRY + 1):
            repair = ""
            if attempt:
                repair = "\n".join(f"- {p}" for p in problems[:8])
            char_list = "\n".join(
                f"- {cid}：{c.get('role_name', '')}"
                for cid, c in chars.items())
            text = call_api(view, args.model, repair, char_list)
            problems, result = validate_parse(
                text, expected, char_ids, narrations)
            if not problems:
                break
        if result is None:
            print(f"块 {bi} 多次重试仍失败，中止。")
            for p in problems:
                print(" -", p)
            sys.exit(4)
        out_beats = []
        for be in beats:
            idx = int(be["beat_idx"])
            cid, act, emo, sec = result[idx]
            entry = {
                "beat_idx": idx,
                "shot": be.get("shot", "medium"),
                "original_cn": be["prompt"].strip(),
                "character_id": cid,
                "action_props": act,
                "emotion": emo,
            }
            narration = narrations.get(idx, "")
            entry["character_id"] = assign_character_safety_guard(
                entry, narration)
            if any(cta in (entry.get("original_cn", "") + " " + narration)
                   for cta in CTA_WORDS):
                entry["action_props"] = (
                    "confident smile, determined look, "
                    "clenching fist with enthusiasm, ready to take action")
                entry["emotion"] = "confident, ready, hopeful"
            if sec and sec != entry["character_id"]:
                entry["secondary_character_id"] = sec
            char_prompt = (chars.get(entry["character_id"]) or {}).get(
                "prompt", "")
            entry["final_image_prompt"] = assemble_prompt(
                entry, char_prompt, meta, chars)
            out_beats.append(entry)
            total_beats += 1
        print(f"块 {bi}：{len(out_beats)} 拍已解析装配。")
        output_blocks.append({"block_idx": bi, "head": sb["head"],
                              "beats": out_beats})
    return {"style_id": STYLE_ID,
            "generated_at": datetime.datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"),
            "blocks": output_blocks}


def validate_final(output, story, chars, full=True):
    """离线校验 storyboard_output.json，返回问题列表。

    full=True 时还要求所有有提示词的块都已覆盖（全量生成）；受限解析
    （--blocks/--beats）时只校验输出中已有的块。
    """
    problems = []
    char_ids = set(chars.keys())
    out_by_block = {b["block_idx"]: b for b in output.get("blocks", [])}
    total = 0
    for sb in story["blocks"]:
        bi = sb["block_idx"]
        expected = [(int(be["beat_idx"]), be.get("shot", "medium"),
                     (be.get("prompt") or "").strip())
                    for be in sb["beats"] if (be.get("prompt") or "").strip()]
        ob = out_by_block.get(bi)
        if not expected:
            continue
        if not ob:
            if full:
                problems.append(f"块 {bi} 缺失（期望 {len(expected)} 拍）")
            continue
        ob_beats = {int(be["beat_idx"]): be for be in ob["beats"]}
        if set(ob_beats) != {e[0] for e in expected}:
            problems.append(f"块 {bi} 拍号集合不匹配")
            continue
        for idx, shot, cn in expected:
            be = ob_beats[idx]
            total += 1
            if be.get("shot") != shot:
                problems.append(f"块 {bi} 拍 {idx} shot 不一致")
            if be.get("original_cn") != cn:
                problems.append(f"块 {bi} 拍 {idx} original_cn 与分镜不一致")
            if be.get("character_id") not in char_ids:
                problems.append(f"块 {bi} 拍 {idx} character_id 非法")
            if not (be.get("action_props") or "").strip():
                problems.append(f"块 {bi} 拍 {idx} action_props 缺失")
            if not (be.get("emotion") or "").strip():
                problems.append(f"块 {bi} 拍 {idx} emotion 缺失")
            elif len(be["emotion"]) > 60:
                problems.append(f"块 {bi} 拍 {idx} emotion 超长")
            sec = be.get("secondary_character_id")
            if sec:
                if sec not in char_ids:
                    problems.append(
                        f"块 {bi} 拍 {idx} secondary_character_id 非法")
                if sec == be.get("character_id"):
                    problems.append(
                        f"块 {bi} 拍 {idx} secondary 与主角色相同")
            if not (be.get("final_image_prompt") or "").strip():
                problems.append(f"块 {bi} 拍 {idx} final_image_prompt 缺失")
    print(f"共校验 {total} 拍。")
    return problems


def save(output, out_path):
    if os.path.exists(out_path):
        shutil.copy2(out_path, out_path + ".bak")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    return out_path


def reassemble(args, chars, meta, out_path):
    """不动 LLM，仅按当前常量重装配 final_image_prompt。"""
    if not os.path.exists(out_path):
        print(f"未找到 {out_path}，请先运行解析。")
        sys.exit(1)
    with open(out_path, encoding="utf-8") as f:
        output = json.load(f)
    for sb in output.get("blocks", []):
        for be in sb.get("beats", []):
            char_prompt = (chars.get(be.get("character_id")) or {}).get(
                "prompt", "")
            be["final_image_prompt"] = assemble_prompt(
                be, char_prompt, meta, chars)
    save(output, out_path)
    print(f"重装配完成：{out_path}")


def main():
    ap = argparse.ArgumentParser(description="2D Q 版分镜 Prompt 生成（LLM 解析 + 装配）")
    ap.add_argument("--project", default=None,
                    help="项目 id（默认取环境变量 PROJECT，缺省 001）")
    ap.add_argument("--blocks", default=None,
                    help="只解析指定块（逗号分隔），如 0,1")
    ap.add_argument("--beats", nargs="+", default=None,
                    help="只解析指定拍，如 00_0 00_1")
    ap.add_argument("--check", nargs="?", const="auto", metavar="FILE",
                    help="离线校验 storyboard_output.json（默认项目 input/）")
    ap.add_argument("--assemble-only", action="store_true",
                    help="仅按当前常量重装配 final prompt（不调 LLM）")
    ap.add_argument("--out", default=None, help="输出 JSON 路径")
    ap.add_argument("--model", default=None, help="覆盖默认模型名")
    args = ap.parse_args()

    if args.project:
        PJ.CURRENT_ID = args.project
    out_path = args.out or PROJ("input", "storyboard_output.json")
    chars = load_characters()
    meta = PJ.read_meta()

    if args.check is not None:
        path = args.check if args.check != "auto" else out_path
        if not os.path.exists(path):
            print(f"未找到 {path}，请先运行解析。")
            sys.exit(1)
        with open(path, encoding="utf-8") as f:
            output = json.load(f)
        story = load_story()
        problems = validate_final(output, story, chars)
        if problems:
            print("校验未通过：")
            for p in problems:
                print(" -", p)
            sys.exit(1)
        print(f"校验通过：{path}（style_id={output.get('style_id')}）")
        return

    if args.assemble_only:
        reassemble(args, chars, meta, out_path)
        return

    story = load_story()
    output = parse_blocks(args, story, chars, meta, out_path)
    limited = bool(args.blocks or args.beats)
    problems = validate_final(output, story, chars, full=not limited)
    if problems:
        print("拼装后校验未通过：")
        for p in problems:
            print(" -", p)
        sys.exit(4)
    path = save(output, out_path)
    total = sum(len(b["beats"]) for b in output["blocks"])
    print(f"2D Q 版分镜已保存：{path}")
    print(f"共 {len(output['blocks'])} 块、{total} 拍；"
          f"下一步运行 python3 pipeline/write_image_art.py --chibi。")


if __name__ == "__main__":
    main()
