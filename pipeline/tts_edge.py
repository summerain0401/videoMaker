#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""微软 Edge 在线 TTS 适配器（免费、无需 API 密钥）。

用法：from tts_edge import synthesize; synthesize(text, out_wav)
环境变量：
  AZURE_VOICE   默认 zh-CN-XiaoxiaoNeural（晓晓女声）；可换 zh-CN-XiaoyiNeural
  EDGE_RATE     语速，如 +0%、-10%（默认 +0%）
注意：edge-tts 走微软 Edge 网页同款接口（非官方 API），若服务变更导致失败，
可回退 Piper（本地）或 Azure 正式语音 API。
"""

import asyncio
import os
import subprocess

VOICE = os.environ.get("AZURE_VOICE", "zh-CN-YunyangNeural")
RATE = os.environ.get("EDGE_RATE", "+0%")


def synthesize(text, out_wav):
    """合成语音到 wav（44100 单声道），edge-tts 输出 mp3 后转码。"""
    import edge_tts
    mp3 = out_wav + ".edge.mp3"
    asyncio.run(edge_tts.Communicate(text, VOICE, rate=RATE).save(mp3))
    subprocess.run(
        ["ffmpeg", "-y", "-i", mp3, "-ar", "44100", "-ac", "1", out_wav],
        check=True)
    os.remove(mp3)
