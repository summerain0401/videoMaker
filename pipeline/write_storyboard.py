#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""长视频叙事分镜生成：DeepSeek 把每块口播切成 3-5 个卡点并写画面提示词。

项目制路径：默认读写 projects/001_金钱的艺术/input/（环境变量 PROJECT
可换项目，--project 参数可覆盖）。流程：项目 input/script.txt ->
DeepSeek 对每个配音块切卡点/写提示词 -> 程序化拼装
input/storyboard_narrative.json（含 beats 与逐句字幕表）
-> pipeline/write_image_art.py --story 生成卡点画面
-> pipeline/build_long.py 进入叙事渲染模式。

输出 JSON 结构（每个配音块）：
  beats:      [{beat_idx, shot(wide|medium|close), prompt(画面提示词),
                sentence_ids, start_char, end_char}]  // 3-5 拍，覆盖全部句子
  subtitles:  [{id, text, start_char, end_char}]      // 逐句字幕表

密钥：环境变量 DEEPSEEK_API_KEY 或项目根 .env（已 gitignore）。
"""

import argparse
import json
import os
import re
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


PROVIDERS = {
    "deepseek": {
        "base": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
        "key_envs": ["DEEPSEEK_API_KEY"],
    },
}
SHOTS = ("wide", "medium", "close")
MIN_BEATS, MAX_BEATS = 3, 14
MAX_RETRY = 2

SYSTEM_PROMPT = """你是影视级「画面叙事」分镜师。根据用户提供的一个配音块口播，把它切成 3-5 个卡点（beat），并为每个卡点写一条中文画面提示词，用于 AI 生成插画叙事画面。

【画面要求】
- 画面以人物和故事为主，用场景讲内容，绝不用文字、图表、标语。
- 提示词必须与口播语义严格对应：讲到什么内容，画面就呈现什么。例如讲「有钱人 vs 富裕的人」，要切到两个对比场景——有钱人：深夜写字楼里疲惫加班的身影；富裕的人：海边清晨从容散步的身影。
- 每个提示词包含：人物（动作/状态）、场景、情绪氛围、景别（wide 远景 / medium 中景 / close 特写）。
- 画面中不要出现任何文字、字母、水印；底部预留字幕安全区。

【输出格式（只输出该块的 JSON，不要解释，不要 Markdown 代码块）】
{
  "block_idx": 0,
  "beats": [
    {"beat_idx": 0, "shot": "wide", "prompt": "人物+动作+场景+情绪，30-80 字", "sentence_ids": [0, 1]},
    {"beat_idx": 1, "shot": "medium", "prompt": "...", "sentence_ids": [2, 3]}
  ]
}

【硬性规则】
- 该块 3-5 拍。
- 每块的 sentence_ids 必须恰好覆盖该块全部句子一次，不得遗漏或重复；每拍 1-4 句。
- 卡点顺序即句子顺序，拍与拍之间的句子 id 必须连续递增。"""

REFINE_SYSTEM_PROMPT = """你是影视级「画面叙事」分镜师。用户会给出一拍口播的句子和上一拍的画面提示词，请为这一半内容写一条新的画面提示词，用于 AI 生成插画叙事画面。

【要求】
- 与给出的口播句子语义严格对应：人物+动作+场景+情绪+景别。
- 与上一拍画面自然衔接（同一个人物继续同一场景或自然过渡），保持暖色温馨明亮的插画叙事风格。
- 画面中不要出现任何文字、字母、图表、标语或水印；底部预留字幕安全区。

【输出格式（只输出 JSON，不要解释）】
{"shot": "wide|medium|close", "prompt": "30-80 字"}"""

WARM_REWRITE_SYSTEM = """你是影视级「画面叙事」分镜师。用户会给出一条画面提示词
（可能含有深夜、加班、焦虑、压抑、灰暗等阴郁元素），请把它重写为
「暖色温馨、明亮通透」的版本。

【要求】
- 保持原提示词的语义对应：人物、动作、场景与故事结构不变，景别不变。
- 把场景转为暖光环境：深夜/夜晚 → 傍晚或清晨的暖光；昏暗/灰暗 → 暖色灯光
  与阳光；冷色调 → 暖色调。负面情绪（疲惫、焦虑、对比）可以保留，
  但人物与环境必须被暖色光线包裹，画面不阴沉、不压抑、不绝望。
- 与前后拍画面自然衔接；不改变该拍对应的句子分配与字符区间。
- 画面中不要出现文字、字母、图表或水印；底部预留字幕安全区。

【输出格式（只输出 JSON，不要解释，不要 Markdown 代码块）】
{"prompt": "重写后的 30-100 字画面提示词"}"""


def split_sentences(text):
    """按句末标点拆句，返回带字符偏移的句子列表。"""
    parts = re.split(r"(?<=[。！？!?])", text)
    out, pos = [], 0
    for p in parts:
        if not p:
            continue
        out.append({"id": len(out), "text": p,
                    "start_char": pos, "end_char": pos + len(p)})
        pos += len(p)
    return out


def build_block_view(b, bi):
    """单个配音块的模型输入视图。"""
    sents = split_sentences(b["voice"])
    lines = [f"块 {bi}（{b['type']}）口播："]
    for s in sents:
        lines.append(f"句 {s['id']}：{s['text']}")
    lines.append("请把该块切成 3-5 拍，输出 beats JSON。")
    return "\n".join(lines)


def load_api_key(conf):
    for k in conf["key_envs"]:
        if os.environ.get(k):
            return os.environ[k]
    env_path = P(".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if "=" in line and line.split("=", 1)[0].strip() == \
                        "DEEPSEEK_API_KEY":
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def call_api(provider, user_prompt, model, repair="", system=SYSTEM_PROMPT):
    conf = PROVIDERS[provider]
    key = load_api_key(conf)
    if not key:
        print(f"缺少 API 密钥：请配置环境变量或 .env 中的 "
              f"{conf['key_envs'][0]}。")
        sys.exit(2)
    base = os.environ.get("COPY_BASE_URL", conf["base"]).rstrip("/")
    model = model or os.environ.get("COPY_MODEL", conf["model"])
    if repair:
        system += "\n\n【上一版存在以下问题，请修正后重新输出完整 JSON】\n" + repair
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
    """从模型输出中提取 JSON（容忍代码块包裹）。"""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("模型输出中没有 JSON")
    return json.loads(m.group(0))


def validate_block_output(blocks, bi, raw):
    """校验单块模型输出，返回 (问题列表, beats 或 None)。"""
    problems = []
    try:
        data = extract_json(raw)
    except Exception as e:
        return [f"块 {bi} JSON 解析失败：{e}"], None
    if data.get("block_idx") != bi:
        problems.append(f"块 {bi} 的 block_idx 不匹配：{data.get('block_idx')}")
    beats = data.get("beats", [])
    n = len(beats)
    if not (MIN_BEATS <= n <= MAX_BEATS):
        problems.append(f"块 {bi} 应为 {MIN_BEATS}-{MAX_BEATS} 拍，实际 {n}")
    seen, prev = set(), -1
    for be in beats:
        if be.get("shot") not in SHOTS:
            problems.append(f"块 {bi} 拍 {be.get('beat_idx')} 的 shot 非法："
                            f"{be.get('shot')}")
        if not be.get("prompt") or len(be["prompt"]) > 300:
            problems.append(f"块 {bi} 拍 {be.get('beat_idx')} 的 prompt "
                            f"缺失或超长")
        for sid in be.get("sentence_ids", []):
            if sid in seen:
                problems.append(f"块 {bi} 句子 {sid} 重复分配")
            seen.add(sid)
            if sid <= prev:
                problems.append(f"块 {bi} 句子 id 不连续递增")
            prev = sid
    total = len(split_sentences(blocks[bi]["voice"]))
    if sorted(seen) != list(range(total)):
        problems.append(f"块 {bi} 句子未全覆盖："
                        f"{sorted(seen)} != {list(range(total))}")
    return problems, beats if not problems else None


def assemble(blocks, groups):
    """拼装最终分镜 JSON（含字符偏移与逐句字幕表）。"""
    out_blocks = []
    for i, b in enumerate(blocks):
        sents = split_sentences(b["voice"] or "")
        beats = []
        if b["voice"]:
            for be in groups[i]:
                ids = be["sentence_ids"]
                lo = sents[ids[0]]["start_char"] if ids else 0
                hi = sents[ids[-1]]["end_char"] if ids else 0
                beats.append({
                    "beat_idx": be["beat_idx"],
                    "shot": be["shot"],
                    "prompt": be["prompt"].strip(),
                    "sentence_ids": ids,
                    "start_char": lo,
                    "end_char": hi,
                })
        else:
            beats = [{"beat_idx": 0, "shot": "wide", "prompt": "",
                      "sentence_ids": [], "start_char": 0, "end_char": 0}]
        out_blocks.append({
            "block_idx": i,
            "type": b["type"],
            "head": b["head"],
            "voice_chars": len(b["voice"] or ""),
            "beats": beats,
            "subtitles": [{"id": s["id"], "text": s["text"],
                           "start_char": s["start_char"],
                           "end_char": s["end_char"]} for s in sents],
        })
    return {"style": "插画叙事", "blocks": out_blocks}


def validate_final(story, blocks):
    """离线复检最终 JSON，返回问题列表。"""
    problems = []
    sbs = {b["block_idx"]: b for b in story.get("blocks", [])}
    if len(sbs) != len(blocks):
        return [f"分镜块数 {len(sbs)} 与脚本 {len(blocks)} 不一致"]
    for i, b in enumerate(blocks):
        sb = sbs.get(i)
        if not sb:
            problems.append(f"块 {i} 缺失")
            continue
        beats, subs = sb["beats"], sb["subtitles"]
        if not b["voice"]:
            if len(beats) != 1:
                problems.append(f"块 {i}（无配音）应 1 拍，实际 {len(beats)}")
            continue
        n = len(beats)
        if not (MIN_BEATS <= n <= MAX_BEATS):
            problems.append(f"块 {i} 应为 {MIN_BEATS}-{MAX_BEATS} 拍，实际 {n}")
        lo, hi = 0, len(b["voice"])
        for be in beats:
            if not (be["start_char"] <= be["end_char"]):
                problems.append(f"块 {i} 拍 {be['beat_idx']} 字符区间非法")
        first, last = beats[0]["start_char"], beats[-1]["end_char"]
        if first != 0 or last != hi:
            problems.append(f"块 {i} 拍区间未覆盖全文（{first}..{last}，应 0..{hi}）")
        for k in range(1, n):
            if beats[k]["start_char"] != beats[k - 1]["end_char"]:
                problems.append(f"块 {i} 拍 {k} 与上一拍字符区间不连续")
        for s in subs:
            if not s["text"] or not (0 <= s["start_char"] < s["end_char"] <= hi):
                problems.append(f"块 {i} 字幕 {s['id']} 区间非法")
        if subs and (subs[0]["start_char"] != 0 or subs[-1]["end_char"] != hi):
            problems.append(f"块 {i} 字幕未覆盖全文")
    return problems


def save(story, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(story, f, ensure_ascii=False, indent=2)
    return path


def refine_story(old_story, blocks, max_sec=12.0):
    """把单拍估算 > max_sec 且 ≥2 句的拍拆成两半（按字符均衡）。"""
    new_blocks = []
    scenes_dir = PROJ("assets", "scenes")
    for sb in old_story["blocks"]:
        b = blocks[sb["block_idx"]]
        sub_map = {s["id"]: s for s in sb["subtitles"]}
        out = []
        for be in sb["beats"]:
            ids = list(be["sentence_ids"])
            est = (be["end_char"] - be["start_char"]) / 4.0
            has_img = os.path.exists(os.path.join(
                scenes_dir, f"{sb['block_idx']:02d}_{be['beat_idx']}.png"))
            if has_img and est > max_sec and len(ids) >= 2:
                total = sum(sub_map[i]["end_char"] - sub_map[i]["start_char"]
                            for i in ids)
                acc, cut = 0, 1
                for cut in range(1, len(ids)):
                    acc += sub_map[ids[cut - 1]]["end_char"] - \
                           sub_map[ids[cut - 1]]["start_char"]
                    if acc >= total / 2:
                        break
                a, c = ids[:cut], ids[cut:]
                out.append({
                    "beat_idx": None, "shot": be["shot"],
                    "prompt": be["prompt"],
                    "sentence_ids": a,
                    "start_char": sub_map[a[0]]["start_char"],
                    "end_char": sub_map[a[-1]]["end_char"],
                    "src_idx": be["beat_idx"], "new_prompt": True})
                out.append({
                    "beat_idx": None, "shot": None, "prompt": None,
                    "sentence_ids": c,
                    "start_char": sub_map[c[0]]["start_char"],
                    "end_char": sub_map[c[-1]]["end_char"],
                    "src_idx": None, "new_prompt": True})
            else:
                out.append({
                    "beat_idx": None, "shot": be["shot"],
                    "prompt": be["prompt"],
                    "sentence_ids": ids,
                    "start_char": be["start_char"],
                    "end_char": be["end_char"],
                    "src_idx": be["beat_idx"] if has_img else None,
                    "new_prompt": False})
        for k, be in enumerate(out):
            be["beat_idx"] = k
        new_blocks.append({**sb, "beats": out})
    return {"style": old_story.get("style", "插画叙事"),
            "blocks": new_blocks}


def build_refine_view(b, sb, ids, parent_prompt):
    sub_map = {s["id"]: s["text"] for s in sb["subtitles"]}
    lines = [f"块 {b['type']}（{b['head']}）口播句子："]
    for i in ids:
        lines.append(f"句 {i}：{sub_map[i]}")
    lines.append(f"上一拍画面（请保持衔接）：{parent_prompt}")
    lines.append("请为这半拍写新画面提示词。")
    return "\n".join(lines)


def validate_refine(raw):
    try:
        data = extract_json(raw)
    except Exception as e:
        return [f"JSON 解析失败：{e}"], None
    problems = []
    if data.get("shot") not in SHOTS:
        problems.append(f"shot 非法：{data.get('shot')}")
    p = data.get("prompt", "")
    if not p or len(p) > 300:
        problems.append("prompt 缺失或超长")
    return problems, (data.get("shot"), p) if not problems else None


def validate_warm(raw):
    """校验暖化重写输出，返回 (问题列表, 新 prompt 或 None)。"""
    try:
        data = extract_json(raw)
    except Exception as e:
        return [f"JSON 解析失败：{e}"], None
    p = (data.get("prompt") or "").strip()
    problems = []
    if not p:
        problems.append("prompt 缺失")
    if len(p) > 300:
        problems.append(f"prompt 超长（{len(p)} 字）")
    return problems, p if not problems else None


def warm_rewrite(story, provider, model, want):
    """把命中阴郁词典（或 --beats 指定）的拍提示词重写为暖光版本。"""
    changed, failed = 0, 0
    for sb in story["blocks"]:
        for be in sb["beats"]:
            key = f"{sb['block_idx']:02d}_{int(be['beat_idx'])}"
            prompt = (be.get("prompt") or "").strip()
            hits = tone.prompt_risks(prompt)
            if want and key not in want:
                continue
            if not want and not hits:
                continue
            if not prompt:
                continue
            view = (f"原画面提示词：{prompt}\n"
                    f"命中的阴郁词：{'、'.join(hits) if hits else '人工指定'}\n"
                    f"请按规则重写为暖光版本。")
            result = None
            problems = []
            for attempt in range(MAX_RETRY + 1):
                repair = ""
                if attempt:
                    repair = "\n".join(f"- {p}" for p in problems[:8])
                text = call_api(provider, view, model, repair,
                                system=WARM_REWRITE_SYSTEM)
                problems, result = validate_warm(text)
                if not problems:
                    break
            if result:
                be["prompt"] = result
                changed += 1
                print(f"已暖化 块{sb['block_idx']:02d} "
                      f"拍{be['beat_idx']}：{result[:50]}…")
            else:
                print(f"块{sb['block_idx']} 拍{be['beat_idx']} 暖化失败")
                failed += 1
    return changed, failed


def migrate_scene_files(new_story):
    """按 src_idx 把未拆拍/前半拍原图改名到新拍号，返回改名数。"""
    scenes = PROJ("assets", "scenes")
    os.makedirs(scenes, exist_ok=True)
    staged = []
    for sb in new_story["blocks"]:
        for be in sb["beats"]:
            src = be.get("src_idx")
            if src is None:
                continue
            old_fn = os.path.join(scenes,
                                  f"{sb['block_idx']:02d}_{src}.png")
            tmp_fn = os.path.join(scenes,
                                  f".t_{sb['block_idx']:02d}_{src}.png")
            if os.path.exists(old_fn):
                os.replace(old_fn, tmp_fn)
                staged.append((tmp_fn, os.path.join(
                    scenes, f"{sb['block_idx']:02d}_{be['beat_idx']}.png")))
    for tmp_fn, new_fn in staged:
        os.replace(tmp_fn, new_fn)
    return len(staged)


def missing_beats(story):
    """返回需要生成画面的拍（有 prompt 且无对应文件）。"""
    have = set(os.listdir(PROJ("assets", "scenes")))
    out = []
    for sb in story["blocks"]:
        for be in sb["beats"]:
            if be.get("prompt") and \
                    f"{sb['block_idx']:02d}_{be['beat_idx']}.png" not in have:
                out.append(f"{sb['block_idx']:02d}_{be['beat_idx']}")
    return out


def main():
    ap = argparse.ArgumentParser(description="长视频叙事分镜生成（DeepSeek）")
    ap.add_argument("--project", default=None,
                    help="项目 id（默认取环境变量 PROJECT，缺省 001）")
    ap.add_argument("--provider", choices=list(PROVIDERS), default="deepseek")
    ap.add_argument("--model", default=None, help="覆盖默认模型名")
    ap.add_argument("--out", default=None,
                    help="输出 JSON 路径")
    ap.add_argument("--check", nargs="?", const="auto", metavar="FILE",
                    help="离线复检分镜 JSON（--warm --check 只列阴郁风险拍）")
    ap.add_argument("--warm", action="store_true",
                    help="暖化：把命中阴郁词典的拍提示词重写为暖光版本")
    ap.add_argument("--beats", nargs="+", default=None,
                    help="--warm 只暖化指定拍，如 00_2 02_0")
    ap.add_argument("--refine", action="store_true",
                    help="细化：把单拍 >12s 的拍拆成两半（新半拍由 AI 写提示词）")
    ap.add_argument("--max-sec", type=float, default=12.0,
                    help="--refine 的单拍上限秒数（默认 12）")
    args = ap.parse_args()

    if args.project:
        PJ.CURRENT_ID = args.project
    out_path = args.out or PROJ("input", "storyboard_narrative.json")

    sys.path.insert(0, P("pipeline"))
    import build_long as B
    blocks = B.parse_script()

    if args.warm:
        import shutil
        with open(out_path, encoding="utf-8") as f:
            story = json.load(f)
        if args.check is not None:
            hits = []
            for sb in story["blocks"]:
                for be in sb["beats"]:
                    pw = tone.prompt_risks(be.get("prompt", ""))
                    if pw:
                        hits.append((f"{sb['block_idx']:02d}_"
                                     f"{int(be['beat_idx'])}", pw))
            print(f"阴郁风险拍 {len(hits)} 个（未调用 API）：")
            for key, pw in hits:
                print(f" - {key}：{'、'.join(pw)}")
            return
        want = set(args.beats or [])
        changed, failed = warm_rewrite(story, args.provider, args.model, want)
        if failed:
            print(f"{failed} 个拍暖化失败，中止。")
            sys.exit(4)
        problems = validate_final(story, blocks)
        if problems:
            print("暖化后校验未通过：")
            for p in problems:
                print(" -", p)
            sys.exit(4)
        if os.path.exists(out_path):
            shutil.copy2(out_path, out_path + ".bak")
        save(story, out_path)
        print(f"暖化完成：{changed} 个拍已重写。分镜已保存：{out_path}")
        return

    if args.refine:
        import shutil
        with open(out_path, encoding="utf-8") as f:
            old_story = json.load(f)
        story = refine_story(old_story, blocks, max_sec=args.max_sec)
        old_beats = sum(len(b["beats"]) for b in old_story["blocks"])
        new_beats = sum(len(b["beats"]) for b in story["blocks"])
        # 为拆出的新半拍补写提示词
        failed = 0
        for sb in story["blocks"]:
            b = blocks[sb["block_idx"]]
            parent = None
            for be in sb["beats"]:
                if be.get("new_prompt") and be["prompt"]:
                    parent = be["prompt"]
                    continue
                if be.get("new_prompt") and not be["prompt"]:
                    view = build_refine_view(b, sb, be["sentence_ids"], parent)
                    result = None
                    for attempt in range(MAX_RETRY + 1):
                        repair = ""
                        if attempt:
                            repair = "\n".join(
                                f"- {p}" for p in problems[:8])
                        text = call_api(args.provider, view, args.model,
                                        repair, system=REFINE_SYSTEM_PROMPT)
                        problems, result = validate_refine(text)
                        if not problems:
                            break
                    if result:
                        be["shot"], be["prompt"] = result
                    else:
                        print(f"块 {sb['block_idx']} 拍 "
                              f"{be['beat_idx']} 提示词生成失败")
                        failed += 1
        if failed:
            print(f"{failed} 个新拍提示词失败，中止。")
            sys.exit(4)
        # 清理内部字段
        for sb in story["blocks"]:
            for be in sb["beats"]:
                be.pop("new_prompt", None)
                be.pop("src_idx", None)
        problems = validate_final(story, blocks)
        if problems:
            print("细化后校验未通过：")
            for p in problems:
                print(" -", p)
            sys.exit(4)
        # 备份 + 迁移原图 + 保存
        shutil.copy2(out_path, out_path + ".bak")
        # 迁移需要在清除 src_idx 前做；重新构建带 src 的副本
        story_with_src = refine_story(old_story, blocks, max_sec=args.max_sec)
        renamed = migrate_scene_files(story_with_src)
        save(story, out_path)
        missing = missing_beats(story)
        print(f"细化完成：{old_beats} 拍 -> {new_beats} 拍，"
              f"原图改名复用 {renamed} 张。")
        if missing:
            print(f"需生成 {len(missing)} 张新图，运行：")
            print("  python3 pipeline/write_image_art.py --story"
                  f" --beats {' '.join(missing)}")
        else:
            print("无新增拍，无需补图。")
        return

    if args.check:
        check_path = args.check if args.check != "auto" else out_path
        with open(check_path, encoding="utf-8") as f:
            story = json.load(f)
        problems = validate_final(story, blocks)
        if problems:
            print("分镜校验未通过：")
            for p in problems:
                print(" -", p)
            sys.exit(1)
        total_beats = sum(len(b["beats"]) for b in story["blocks"])
        print(f"分镜校验通过：{len(story['blocks'])} 块，"
              f"共 {total_beats} 拍。")
        return

    voiced = [i for i, b in enumerate(blocks) if b["voice"]]
    groups = {}
    fail = False
    for bi in voiced:
        view = build_block_view(blocks[bi], bi)
        text = call_api(args.provider, view, args.model)
        problems, beats = validate_block_output(blocks, bi, text)
        for attempt in range(MAX_RETRY):
            if not problems:
                break
            print(f"块 {bi} 第 {attempt + 1} 次未通过校验"
                  f"（{len(problems)} 个问题），回喂重试…")
            for p in problems:
                print(" -", p)
            repair = "\n".join(f"- {p}" for p in problems[:8])
            text = call_api(args.provider, view, args.model, repair)
            problems, beats = validate_block_output(blocks, bi, text)
        else:
            print(f"块 {bi} 多次重试仍失败，中止。")
            for p in problems:
                print(" -", p)
            fail = True
        if beats is not None:
            groups[bi] = beats
    if fail or len(groups) != len(voiced):
        sys.exit(4)

    story = assemble(blocks, groups)
    problems = validate_final(story, blocks)
    if problems:
        print("拼装后校验未通过：")
        for p in problems:
            print(" -", p)
        sys.exit(4)
    path = save(story, out_path)
    total_beats = sum(len(b["beats"]) for b in story["blocks"])
    print(f"分镜已保存：{path}")
    print(f"共 {len(story['blocks'])} 块，{total_beats} 拍，"
          f"预计生成 {total_beats} 张画面。")
    print("下一步：人工抽查卡点与提示词，确认后运行 "
          "write_image_art.py --story 生成画面。")


if __name__ == "__main__":
    main()
