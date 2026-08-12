#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Azure Speech 正式 TTS 适配器（需 API 密钥，免费层 50 万字符/月）。

用法：from tts_azure import synthesize; synthesize(text, out_wav)
环境变量（可放项目根 .env，已 gitignore）：
  AZURE_SPEECH_KEY   必填，Azure Speech 资源 Key1/Key2
  AZURE_REGION       区域，如 eastasia（缺省时从 REST_API_URL 解析）
  AZURE_VOICE        声音名，默认 zh-CN-YunyangNeural
注意：免费层 F0 输出格式限 mp3；本适配器输出 mp3 后由 ffmpeg 转 wav。
"""

import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_VOICE = "zh-CN-YunyangNeural"
OUTPUT_FORMAT = "audio-16khz-128kbitrate-mono-mp3"


def _dotenv():
    """读取项目根 .env 的键值（仅内存使用，绝不打印值）。"""
    vals = {}
    path = os.path.join(ROOT, ".env")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals


def _cfg(key, default=""):
    """环境变量优先，其次 .env。"""
    return os.environ.get(key) or _dotenv().get(key) or default


def _region():
    r = _cfg("AZURE_REGION").strip()
    if r:
        return r
    url = _cfg("REST_API_URL", "")
    m = re.search(r"https?://([^.]+)\.api\.cognitive", url)
    return m.group(1) if m else ""


def _escape(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;")
            .replace("'", "&apos;"))


def synthesize(text, out_wav):
    """用配置的 voice_name 合成语音到 wav（44100 单声道）。"""
    key = _cfg("AZURE_SPEECH_KEY")
    if not key:
        print("缺少 Azure Speech 密钥：请在环境变量或项目根 .env 配置 "
              "AZURE_SPEECH_KEY。")
        sys.exit(2)
    region = _region()
    if not region:
        print("缺少 Azure 区域：请配置 AZURE_REGION（或 REST_API_URL）。")
        sys.exit(2)
    voice = _cfg("AZURE_VOICE", DEFAULT_VOICE)
    endpoint = (f"https://{region}.tts.speech.microsoft.com"
                f"/cognitiveservices/v1")
    ssml = (f"<speak version='1.0' xml:lang='zh-CN'>"
            f"<voice name='{voice}'>{_escape(text)}</voice></speak>")
    req = urllib.request.Request(
        endpoint,
        data=ssml.encode("utf-8"),
        headers={
            "Ocp-Apim-Subscription-Key": key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": OUTPUT_FORMAT,
            "User-Agent": "videoMaker",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            mp3 = resp.read()
    except urllib.error.HTTPError as e:
        print(f"Azure 请求失败（{e.code}）："
              f"{e.read().decode('utf-8', 'ignore')[:300]}")
        sys.exit(3)
    except Exception as e:
        print(f"Azure 网络请求失败：{e}")
        sys.exit(3)
    tmp_mp3 = out_wav + ".azure.mp3"
    with open(tmp_mp3, "wb") as f:
        f.write(mp3)
    subprocess.run(
        ["ffmpeg", "-y", "-i", tmp_mp3, "-ar", "44100", "-ac", "1", out_wav],
        check=True)
    os.remove(tmp_mp3)
