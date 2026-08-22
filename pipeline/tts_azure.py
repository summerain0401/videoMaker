#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Azure Speech 唯一正式 TTS 适配器。

用法：from tts_azure import synthesize; synthesize(text, out_wav, project_voice)
环境变量（可放项目根 .env，已 gitignore）：
  AZURE_SPEECH_KEY   必填，Azure Speech 资源 Key1/Key2
  AZURE_REGION       区域，如 eastasia（缺省时从 REST_API_URL 解析）
音色由调用方从 project.json 传入，环境变量不能覆盖项目音色。
注意：免费层 F0 输出格式限 mp3；本适配器输出 mp3 后由 ffmpeg 转 wav。
"""

import os
import re
import subprocess
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OUTPUT_FORMAT = "audio-16khz-128kbitrate-mono-mp3"
RETRY_DELAYS = (2, 5, 10)


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


def _request_audio(request, opener=urllib.request.urlopen, sleeper=time.sleep):
    """网络/限流/服务端失败最多重试 3 次，不切换服务。"""
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            with opener(request, timeout=180) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            retryable = exc.code == 429 or 500 <= exc.code < 600
            detail = exc.read().decode("utf-8", "ignore")[:300]
            error = RuntimeError(f"Azure 请求失败（{exc.code}）：{detail}")
            if not retryable or attempt == len(RETRY_DELAYS):
                raise error from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            error = RuntimeError(f"Azure 网络请求失败：{exc}")
            if attempt == len(RETRY_DELAYS):
                raise error from exc
        sleeper(RETRY_DELAYS[attempt])
    raise RuntimeError("Azure 请求失败")  # pragma: no cover


def synthesize(text, out_wav, voice=None):
    """用显式指定的项目音色合成 wav（44100Hz 单声道）。"""
    key = _cfg("AZURE_SPEECH_KEY")
    if not key:
        raise RuntimeError(
            "缺少 Azure Speech 密钥：请在环境变量或项目根 .env 配置 "
            "AZURE_SPEECH_KEY")
    region = _region()
    if not region:
        raise RuntimeError("缺少 Azure 区域：请配置 AZURE_REGION（或 REST_API_URL）")
    if not isinstance(voice, str) or not voice.strip():
        raise RuntimeError("Azure voice 必须由 project.json 或 run 快照显式提供")
    voice = voice.strip()
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
    mp3 = _request_audio(req)
    tmp_mp3 = out_wav + ".azure.mp3"
    try:
        with open(tmp_mp3, "wb") as f:
            f.write(mp3)
        subprocess.run(
            ["ffmpeg", "-y", "-i", tmp_mp3, "-ar", "44100", "-ac", "1",
             out_wav], check=True)
    finally:
        if os.path.exists(tmp_mp3):
            os.remove(tmp_mp3)
