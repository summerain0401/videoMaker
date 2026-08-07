#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""调用 DeepSeek / Kimi 起草短视频口播文案。

流程：brief 需求单 -> AI 起草到 copy/draft_*.txt -> 人工修改 ->
      --accept 定稿到 copy/voiceover.txt -> pipeline/build.py 出片。
"""

import argparse
import datetime
import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def P(*parts):
    return os.path.join(ROOT, *parts)


PROVIDERS = {
    "deepseek": {
        "base": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
        "key_envs": ["DEEPSEEK_API_KEY"],
    },
    "kimi": {
        "base": "https://api.moonshot.cn/v1",
        "model": "kimi-latest",
        "key_envs": ["KIMI_API_KEY", "MOONSHOT_API_KEY"],
    },
}

SYSTEM_PROMPT = """你是资深中文短视频口播文案专家，尤其擅长 AI 知识类、教育类和实战干货类内容。你的任务是根据需求单写一段可以直接用于配音的短视频口播稿。

写作要求：
1. 输出必须是口语化的中文短句，适合朗读；避免书面语、长从句和生僻词。
2. 内容要具体、有画面感、有信息增量，反对空话和套话。
3. 开头钩子要让人有继续看下去的欲望（提问、反常识、利益点皆可）。
4. 中间按步骤展开，每步给出可执行的做法。
5. 结尾用一句金句收尾，并自然引导关注。
6. 全文总口播时长控制在 40 秒左右，每句约 3-6 秒。

输出格式（严格遵守，只输出口播稿本身，不要任何解释，不要用 Markdown 代码块）：
# S1 开场钩子
第一句口播。
第二句口播。

# S2 第一步
第一句口播。
第二句口播。

# S3 第二步
第一句口播。
第二句口播。

# S4 第三步
第一句口播。
第二句口播。

# S5 结尾
第一句口播。
第二句口播。"""


def read_brief(topic, brief_file):
    if topic:
        return topic
    path = brief_file or P("copy", "brief.md")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    print("请提供主题参数 --topic，或在 copy/brief.md 中填写需求单。")
    sys.exit(1)


def call_api(provider, user_prompt, model):
    conf = PROVIDERS[provider]
    key = next((os.environ.get(k) for k in conf["key_envs"]
                if os.environ.get(k)), None)
    if not key:
        print(f"缺少 API 密钥：请设置环境变量 {conf['key_envs'][0]}。")
        sys.exit(2)
    base = os.environ.get("COPY_BASE_URL", conf["base"]).rstrip("/")
    model = model or os.environ.get("COPY_MODEL", conf["model"])

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.8,
        "max_tokens": 2000,
    }
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"API 请求失败（{e.code}）：{e.read().decode('utf-8')[:300]}")
        sys.exit(3)
    except Exception as e:
        print(f"网络请求失败：{e}")
        sys.exit(3)
    return data["choices"][0]["message"]["content"].strip()


def validate(text):
    scenes, cur, counts = [], None, {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            sid = line[1:].strip().split()[0]
            scenes.append(sid)
            cur = sid
            counts[sid] = 0
        elif cur:
            counts[cur] += 1
    problems = []
    if len(scenes) != 5:
        problems.append(f"应有 5 幕，实际 {len(scenes)} 幕")
    for sid, n in counts.items():
        if n != 2:
            problems.append(f"场景 {sid} 口播句数应为 2，实际 {n}")
    return problems


def estimate_seconds(text):
    chars = sum(len(line.strip()) for line in text.splitlines()
                if line.strip() and not line.strip().startswith("#"))
    return round(chars / 4.2)


def save_draft(text):
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = P("copy", f"draft_{stamp}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    return path


def accept(path):
    target = P("copy", "voiceover.txt")
    problems = validate(open(path, encoding="utf-8").read())
    if problems:
        print("定稿未通过结构检查：")
        for p in problems:
            print(" -", p)
        sys.exit(4)
    if os.path.exists(target):
        os.replace(target, target + ".bak")
    import shutil
    shutil.copy2(path, target)
    print(f"已定稿到 {target}（旧版备份为 voiceover.txt.bak）")


def main():
    ap = argparse.ArgumentParser(description="AI 起草短视频口播文案")
    ap.add_argument("--topic", help="一句话主题，例如：AI 提效的三个习惯")
    ap.add_argument("--brief-file", help="需求单文件路径，默认 copy/brief.md")
    ap.add_argument("--provider", choices=list(PROVIDERS), default=None,
                    help="选择模型平台：deepseek 或 kimi（也可用环境变量 COPY_PROVIDER）")
    ap.add_argument("--model", help="覆盖默认模型名")
    ap.add_argument("--accept", action="store_true",
                    help="把已修改好的最新 draft 定稿到 voiceover.txt")
    args = ap.parse_args()

    provider = args.provider or os.environ.get("COPY_PROVIDER")
    if not provider:
        print("请用 --provider deepseek|kimi 选择平台。")
        sys.exit(2)

    if args.accept:
        drafts = sorted(
            f for f in os.listdir(P("copy"))
            if f.startswith("draft_") and f.endswith(".txt"))
        if not drafts:
            print("没有找到 draft 文件，请先起草。")
            sys.exit(4)
        accept(P("copy", drafts[-1]))
        return

    user_prompt = read_brief(args.topic, args.brief_file)
    text = call_api(provider, user_prompt, args.model)
    path = save_draft(text)
    print("=" * 40)
    print(text)
    print("=" * 40)
    print(f"草稿已保存：{path}")
    print(f"估算口播时长：约 {estimate_seconds(text)} 秒")
    for p in validate(text):
        print("格式提示：", p)
    print("下一步：人工修改草稿，确认后运行 --accept 定稿。")


if __name__ == "__main__":
    main()
