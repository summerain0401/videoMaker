#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Piper 本地神经 TTS 适配器（中文男声 zh_CN-chaowen-medium）。

用法：from tts_piper import synthesize; synthesize(text, out_wav, length_scale)
"""

import os
import wave

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = os.path.join(ROOT, "assets", "piper", "zh_CN-chaowen-medium.onnx")

_voice = None


def _get_voice():
    global _voice
    if _voice is None:
        from piper import PiperVoice
        _voice = PiperVoice.load(
            MODEL, download_dir=os.path.join(ROOT, "assets", "piper"))
    return _voice


def synthesize(text, out_wav, length_scale=1.0):
    """合成中文语音到 wav（16bit 单声道，22050Hz），返回时长（秒）。"""
    from piper.config import SynthesisConfig
    voice = _get_voice()
    chunks = list(voice.synthesize(
        text, SynthesisConfig(length_scale=length_scale)))
    arr = np.concatenate([c.audio_int16_array for c in chunks])
    sr = voice.config.sample_rate
    with wave.open(out_wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(arr.astype(np.int16).tobytes())
    return len(arr) / sr
