#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ImageGen interactive and Wanxiang API image providers."""

import json
import os
import urllib.error
import urllib.request


def _dotenv(root):
    values = {}
    path = os.path.join(root, ".env")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    values[key.strip()] = value.strip().strip('"').strip("'")
    return values


class ImageGenProvider:
    mode = "interactive"

    def __init__(self, config, root):
        self.config = config
        self.root = root

    def generate(self, tasks):
        return {"mode": self.mode, "tasks": tasks}


class WanxiangProvider:
    mode = "api"
    default_model = "wan2.7-image"

    def __init__(self, config, root):
        self.config = config
        self.root = root

    def _config(self):
        values = _dotenv(self.root)
        key = os.environ.get("DASHSCOPE_API_KEY") or values.get("DASHSCOPE_API_KEY")
        if not key:
            raise RuntimeError("缺少 DASHSCOPE_API_KEY")
        base = os.environ.get("DASHSCOPE_BASE_URL") or \
            values.get("DASHSCOPE_BASE_URL") or "https://dashscope.aliyuncs.com"
        model = self.config.get("model") or self.default_model
        return key, base.rstrip("/"), model

    def generate(self, tasks):
        key, base, model = self._config()
        made, skipped, failed = [], [], []
        for task in tasks:
            output = task["output_path"]
            if os.path.exists(output):
                with open(output, "rb") as handle:
                    if handle.read(8) == b"\x89PNG\r\n\x1a\n":
                        skipped.append(task["key"])
                        continue
            try:
                self._generate_one(task, key, base, model)
                made.append(task["key"])
            except Exception as exc:
                failed.append({"key": task["key"], "error": str(exc)})
        if failed:
            raise RuntimeError(json.dumps({"made": made, "skipped": skipped,
                                           "failed": failed},
                                          ensure_ascii=False))
        return {"mode": self.mode, "made": made, "skipped": skipped}

    def _generate_one(self, task, key, base, model):
        body = {
            "model": model,
            "input": {"messages": [{"role": "user", "content": [
                {"text": task["prompt"]}]}]},
            "parameters": {"size": "1920*1080", "n": 1,
                           "watermark": False, "thinking_mode": True,
                           "negative_prompt": task["negative_prompt"]},
        }
        if base.endswith("/api/v1"):
            base = base[:-7]
        req = urllib.request.Request(
            base + "/api/v1/services/aigc/multimodal-generation/generation",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {key}"})
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            url = data["output"]["choices"][0]["message"]["content"][0]["image"]
            with urllib.request.urlopen(url, timeout=600) as resp:
                content = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "ignore")[:400]
            raise RuntimeError(f"万相请求失败 {exc.code}：{detail}") from exc
        if not content.startswith(b"\x89PNG"):
            raise RuntimeError("万相返回内容不是 PNG")
        os.makedirs(os.path.dirname(task["output_path"]), exist_ok=True)
        with open(task["output_path"], "wb") as f:
            f.write(content)
