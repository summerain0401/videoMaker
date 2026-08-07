#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""长视频文案 AI 起草（五段式标记格式 -> 人工定稿）。

流程：copy/long/brief.md 需求单 -> DeepSeek 起草完整脚本到
      copy/long/draft_*.txt -> 结构校验（失败自动回喂重试）-> 人工审阅修改
      -> --accept 严格校验后定稿到 copy/long/script.txt（旧稿备份 .bak）
      -> pipeline/build_long.py 出片。

脚本格式与 build_long.parse_script 严格一致：
  # TITLE           片头页：## 《书名》、## 钩子句 + voice：整段口播
  # PHASE nn · 名称 阶段页（5 个，无 voice）
  # CARD 标题       文字卡：1-4 条 ## 要点 + voice：
  # QUOTE           金句卡：恰 1 条 ## 金句 + voice：
  # TABLE 左 | 右   对比表：2-4 行 "## 左 | 右" + voice：
  # STEPS 标题      阶梯图：4-6 条 ## 步骤 + voice：
  # END             结尾页（可带 ## 灵魂提问/引导与收尾 voice，可选）

密钥读取：优先环境变量 DEEPSEEK_API_KEY，其次项目根 .env（仅取该键，
绝不打印值，.env 已被 .gitignore 排除，不会进入仓库）。
"""

import argparse
import datetime
import json
import os
import shutil
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def P(*parts):
    return os.path.join(ROOT, *parts)


PHASE_HEADS = [
    "PHASE 01 · 开场共情",
    "PHASE 02 · 底层病灶",
    "PHASE 03 · 核心模型",
    "PHASE 04 · 实战工具",
    "PHASE 05 · 哲学升华",
]
VOICE_TARGET = (3800, 4500)   # 口播总字数理想区间（警告）
VOICE_LIMIT = (1000, 8000)    # 明显异常区间（报错）
MAX_RETRY = 2                 # 结构校验失败后的回喂重试次数

PROVIDERS = {
    "deepseek": {
        "base": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
        "key_envs": ["DEEPSEEK_API_KEY"],
    },
}

SYSTEM_PROMPT = """你是资深中文「听书解读」长视频口播文案专家，对标 YouTube 频道《认知书页》的工业化脚本水准。你的任务是根据需求单，为一本书写一段可直接用于配音的完整视频脚本。

【内容结构：五段式，顺序与名称固定】
- PHASE 01 · 开场共情（约占 10%）：标志性提问 + 连续排比痛点拷问，给出书名与作者背书，明确承诺「今天会用十几分钟把书里最有用的思维框架拆给你」。
- PHASE 02 · 底层病灶（约占 25%）：解剖「为什么会陷入困境」的心理与制度原因；引用反常识数据或社会比较陷阱；用二元对立概念划清边界（例：有钱 vs 富裕、地位消费 vs 效用消费）。
- PHASE 03 · 核心模型（约占 30%）：建立新的认知坐标系，把书的核心模型转译成大白话，强调自主与控制权。
- PHASE 04 · 实战工具（约占 25%）：交付 4-6 个即插即用的行动工具，清点式编号，每个都能一句话落地。
- PHASE 05 · 哲学升华（约占 10%）：总结哲学金句，抛出一个开放式「灵魂提问」引导留言互动。

【文风铁律】
1. 口语化短句，适合朗读，约 230-250 字/分钟；避免书面语、长从句、生僻词。
2. 以「痛点引导」组织内容，绝不按书的章节顺序讲；让观众觉得是在解决自己的问题，而不是在听读书报告。
3. 大量使用反义词二元对立（如「买的是地位，不是效用」）制造豁然开朗感。
4. 每 3-4 分钟必须出现一句可以截图转发金句，用 # QUOTE 卡呈现。
5. 原创解读，不照搬原文；涉及书中观点时用通俗转述。

【脚本格式（严格遵守，只输出脚本本身，不要解释，不要 Markdown 代码块）】
# TITLE
## 《书名》
## 一句话钩子标题
voice：开场整段口播（约 250-400 字）

# PHASE 01 · 开场共情

# CARD 本阶段小标题
## 要点一（可单独截图的短句）
## 要点二
## 要点三（可选，共 1-4 条）
voice：本块完整口播段落

# QUOTE
## 可直接截图转发的金句
voice：金句口播（可先重复金句，再补一句解读）

# TABLE 左列名 | 右列名
## 左边内容 | 右边内容
## 左边内容 | 右边内容
## 左边内容 | 右边内容（共 2-4 行）
voice：本块完整口播段落

# STEPS 步骤区标题
## 第一步：一句话做法
## 第二步：一句话做法
## 第三步：一句话做法
## 第四步：一句话做法
## 第五步：一句话做法（共 4-6 条）
voice：本块完整口播段落

# END
## 灵魂提问或关注引导（可选，1-3 条）
voice：收尾口播（可选，如：灵魂提问 + 点赞关注引导）

……（PHASE 02 / 03 / 04 / 05 依次展开；每个阶段内 CARD / QUOTE / TABLE / STEPS 按内容需要编排，至少包含 1 个内容块）……

【硬性规则】
- 五个 # PHASE 行必须按上面顺序各出现一次，名称一字不差。
- 每个内容块（# CARD / # QUOTE / # TABLE / # STEPS）下面必须紧跟一段完整口播 voice：……；# PHASE 不得带 voice；# END 可带 ## 灵魂提问与收尾 voice（可选）。
- voice：后写整段口播（一段话），不要每句一个 voice。
- # QUOTE 的 ## 行只能有 1 条；# TABLE 的 ## 行必须含「|」分隔左右两列；# CARD 的 ## 1-4 条；# STEPS 的 ## 4-6 条。
- 全书口播总字数（所有 voice：段落合计）控制在 3800-4500 字，不含 ## 标题行与 # 标记行。"""


def parse_blocks(text):
    """与 build_long.parse_script 相同的解析规则（忽略其他行）。"""
    blocks, cur = [], None
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if line.startswith("# "):
            head = line[2:].strip()
            cur = {"type": head.split()[0] if head else "", "head": head,
                   "lines": [], "voice": None}
            blocks.append(cur)
        elif line.startswith("## ") and cur is not None:
            cur["lines"].append(line[3:].strip())
        elif line.startswith("voice：") and cur is not None:
            cur["voice"] = line[len("voice："):].strip()
    return blocks


def validate(text):
    """结构校验，返回 (问题列表, 口播总字数, 块列表)。"""
    blocks = parse_blocks(text)
    problems = []
    types = [b["type"] for b in blocks]

    if not blocks or blocks[0]["type"] != "TITLE":
        problems.append("首个块必须是 # TITLE")
    if types.count("TITLE") != 1:
        problems.append(f"应有 1 个 # TITLE，实际 {types.count('TITLE')} 个")
    if types.count("PHASE") != 5:
        problems.append(f"应有 5 个 # PHASE，实际 {types.count('PHASE')} 个")
    if types.count("END") != 1:
        problems.append(f"应有 1 个 # END，实际 {types.count('END')} 个（输出可能被截断）")
    if blocks and blocks[-1]["type"] != "END":
        problems.append("# END 必须是最后一个块")

    phases = [b["head"] for b in blocks if b["type"] == "PHASE"]
    for i, expect in enumerate(PHASE_HEADS):
        got = phases[i] if i < len(phases) else "缺失"
        if got != expect:
            problems.append(f"PHASE 顺序/名称错误：第 {i + 1} 个应为「{expect}」，实际「{got}」")

    for i, b in enumerate(blocks):
        tag = f"第 {i + 1} 块（{b['head'] or '无标题'}）"
        if b["type"] in ("TITLE", "CARD", "QUOTE", "TABLE", "STEPS") and not b["voice"]:
            problems.append(f"{tag} 缺少 voice：口播")
        if b["type"] == "PHASE" and b["voice"]:
            problems.append(f"{tag} 不应带 voice：")
        if b["type"] == "TITLE" and len(b["lines"]) < 2:
            problems.append(f"{tag} 至少需要 2 行 ##（书名 + 钩子句）")
        if b["type"] == "END" and len(b["lines"]) > 4:
            problems.append(f"{tag} 的 ## 行数应不超过 4，实际 {len(b['lines'])}")
        if b["type"] == "CARD" and not (1 <= len(b["lines"]) <= 4):
            problems.append(f"{tag} 的 ## 行数应为 1-4，实际 {len(b['lines'])}")
        if b["type"] == "QUOTE" and len(b["lines"]) != 1:
            problems.append(f"{tag} 的 ## 行数应恰为 1，实际 {len(b['lines'])}")
        if b["type"] == "STEPS" and not (4 <= len(b["lines"]) <= 6):
            problems.append(f"{tag} 的 ## 行数应为 4-6，实际 {len(b['lines'])}")
        if b["type"] == "TABLE":
            cols = b["head"].split("|")
            if len(cols) != 2 or not all(c.strip() for c in cols):
                problems.append(f"{tag} 表头格式应为「# TABLE 左列 | 右列」")
            if not (2 <= len(b["lines"]) <= 4):
                problems.append(f"{tag} 的 ## 行数应为 2-4，实际 {len(b['lines'])}")
            for ln in b["lines"]:
                parts = ln.split("|")
                if len(parts) != 2 or not all(p.strip() for p in parts):
                    problems.append(f"{tag} 的 ## 行「{ln}」必须含且仅含一个 | 分隔左右两列")

    voice_chars = sum(len(b["voice"]) for b in blocks if b["voice"])
    if voice_chars < VOICE_LIMIT[0] or voice_chars > VOICE_LIMIT[1]:
        problems.append(f"口播总字数 {voice_chars} 超出合理范围"
                        f"（{VOICE_LIMIT[0]}-{VOICE_LIMIT[1]} 字）")
    return problems, voice_chars, blocks


def warnings_for(blocks, voice_chars):
    """非阻断性提示（字数目标、阶段占比）。"""
    warns = []
    if not (VOICE_TARGET[0] <= voice_chars <= VOICE_TARGET[1]):
        warns.append(f"口播总字数 {voice_chars}，目标区间 "
                     f"{VOICE_TARGET[0]}-{VOICE_TARGET[1]} 字")
    cur = None
    per = {h: 0 for h in PHASE_HEADS}
    for b in blocks:
        if b["type"] == "PHASE":
            cur = b["head"]
        elif b["type"] != "TITLE" and b["voice"] and cur:
            per[cur] += len(b["voice"])
    total = sum(per.values()) or 1
    ratio = {h.split()[1]: round(v / total * 100) for h, v in per.items()}
    if ratio.get("03", 0) < 20:
        warns.append(f"核心模型（PHASE 03）口播占比约 {ratio.get('03', 0)}%，建议 ≥ 25%")
    if ratio.get("04", 0) < 15:
        warns.append(f"实战工具（PHASE 04）口播占比约 {ratio.get('04', 0)}%，建议 ≥ 20%")
    return warns


def estimate_seconds(voice_chars, blocks):
    """粗估成片时长：口播 4 字/秒 + 阶段页 + 首尾留白 - 转场重叠。"""
    dur = voice_chars / 4.0
    dur += len([b for b in blocks if b["type"] == "PHASE"]) * 4.0
    dur += len([b for b in blocks if b["voice"]]) * 1.0
    dur -= max(0, len(blocks) - 1) * 0.5
    return round(dur, 1)


def load_api_key(conf):
    """密钥：环境变量优先，其次项目根 .env（只读指定键，绝不打印值）。"""
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


def call_api(provider, user_prompt, model, repair=""):
    conf = PROVIDERS[provider]
    key = load_api_key(conf)
    if not key:
        print(f"缺少 API 密钥：请设置环境变量 {conf['key_envs'][0]}，"
              f"或在项目根 .env 中填写（已 gitignore，不会进入仓库）。")
        sys.exit(2)
    base = os.environ.get("COPY_BASE_URL", conf["base"]).rstrip("/")
    model = model or os.environ.get("COPY_MODEL", conf["model"])
    system = SYSTEM_PROMPT
    if repair:
        system += ("\n\n【上一版脚本存在以下结构问题，请逐条修正后"
                   "重新输出完整脚本】\n" + repair)
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.8,
        "max_tokens": 16000,
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


def read_brief(book, author, brief_file):
    parts = []
    path = brief_file or P("copy", "long", "brief.md")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            parts.append(f.read().strip())
    else:
        parts.append("（未提供需求单，请基于书名组织内容）")
    if book:
        parts.append(f"\n本次书目（覆盖需求单）：{book}")
    if author:
        parts.append(f"作者（覆盖需求单）：{author}")
    return "\n".join(parts)


def save_draft(text):
    os.makedirs(P("copy", "long"), exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = P("copy", "long", f"draft_{stamp}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    return path


def accept(path):
    target = P("copy", "long", "script.txt")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    problems, vc, blocks = validate(text)
    if problems:
        print("定稿未通过结构检查：")
        for p in problems:
            print(" -", p)
        sys.exit(4)
    if os.path.exists(target):
        os.replace(target, target + ".bak")
    shutil.copy2(path, target)
    print(f"已定稿到 {target}（旧版备份为 script.txt.bak）")
    print(f"口播总字数 {vc}，共 {len(blocks)} 个块，"
          f"预估成片约 {estimate_seconds(vc, blocks)} 秒")
    for w in warnings_for(blocks, vc):
        print("提示：", w)


def main():
    ap = argparse.ArgumentParser(description="长视频文案 AI 起草（五段式标记格式）")
    ap.add_argument("--provider", choices=list(PROVIDERS), default="deepseek",
                    help="模型平台（默认 deepseek）")
    ap.add_argument("--book", help="书名，覆盖需求单")
    ap.add_argument("--author", help="作者，覆盖需求单")
    ap.add_argument("--brief-file", help="需求单路径，默认 copy/long/brief.md")
    ap.add_argument("--model", help="覆盖默认模型名")
    ap.add_argument("--accept", action="store_true",
                    help="把最新草稿定稿到 copy/long/script.txt")
    ap.add_argument("--check", metavar="FILE",
                    help="离线结构校验指定文案文件，不调 API")
    args = ap.parse_args()

    if args.check:
        try:
            with open(args.check, encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            print(f"无法读取文件：{e}")
            sys.exit(1)
        problems, vc, blocks = validate(text)
        if problems:
            print("校验未通过：")
            for p in problems:
                print(" -", p)
            sys.exit(1)
        print(f"校验通过：共 {len(blocks)} 个块，口播 {vc} 字，"
              f"预估成片约 {estimate_seconds(vc, blocks)} 秒")
        for w in warnings_for(blocks, vc):
            print("提示：", w)
        return

    if args.accept:
        drafts = sorted(f for f in os.listdir(P("copy", "long"))
                        if f.startswith("draft_") and f.endswith(".txt"))
        if not drafts:
            print("copy/long/ 下没有草稿，请先运行起草。")
            sys.exit(4)
        accept(P("copy", "long", drafts[-1]))
        return

    user_prompt = read_brief(args.book, args.author, args.brief_file)
    text = call_api(args.provider, user_prompt, args.model)
    problems, vc, blocks = validate(text)
    for attempt in range(MAX_RETRY):
        if not problems:
            break
        repair = "\n".join(f"- {p}" for p in problems[:12])
        print(f"第 {attempt + 1} 次生成未通过校验"
              f"（{len(problems)} 个问题），回喂模型重试…")
        text = call_api(args.provider, user_prompt, args.model, repair)
        problems, vc, blocks = validate(text)
    else:
        if problems:
            print("多次重试后仍有结构问题，草稿仍会保存，"
                  "请人工修正后 --check / --accept：")
            for p in problems:
                print(" -", p)

    path = save_draft(text)
    print("=" * 40)
    print(text)
    print("=" * 40)
    print(f"草稿已保存：{path}")
    print(f"口播总字数：{vc}（目标 {VOICE_TARGET[0]}-{VOICE_TARGET[1]} 字）")
    print(f"预估成片时长：约 {estimate_seconds(vc, blocks)} 秒")
    if problems:
        print("待修复问题：")
        for p in problems:
            print(" -", p)
    for w in warnings_for(blocks, vc):
        print("提示：", w)
    print("下一步：人工审阅修改草稿，确认后运行 --accept 定稿。")


if __name__ == "__main__":
    main()
