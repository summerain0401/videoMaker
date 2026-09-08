#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ImageGen interactive and Wanxiang API image providers."""

import base64
import hashlib
import io
import json
import os
import tempfile
import urllib.error
import urllib.request

from PIL import Image


def _validate_candidate(content):
    """完整解码候选，避免损坏文件进入缓存或阻断续跑。"""
    with Image.open(io.BytesIO(content)) as image:
        if image.format != "PNG":
            raise ValueError("万相返回内容不是 PNG")
        image.load()
        if abs(image.width / image.height - 16 / 9) > 0.02:
            raise ValueError("万相候选图片比例不是 16:9")


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
                try:
                    with open(output, "rb") as handle:
                        _validate_candidate(handle.read())
                except (OSError, ValueError):
                    pass
                else:
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
        # 与 ImageGen 共用任务中的参考图；本地图片通过 Base64 直接传给 API。
        references = task.get("reference_images") or []
        if len(references) > 9:
            raise ValueError("万相最多支持 9 张参考图")
        content_items = []
        anchor = task.get("style_anchor") or {}
        for path in references:
            with open(path, "rb") as handle:
                reference = handle.read()
            if len(reference) > 20 * 1024 * 1024:
                raise ValueError("万相参考图超过 20MB")
            if (anchor.get("path") and
                    os.path.realpath(path) == os.path.realpath(anchor["path"]) and
                    anchor.get("sha256") != hashlib.sha256(reference).hexdigest()):
                raise ValueError("万相参考图与冻结锚点哈希不一致")
            with Image.open(io.BytesIO(reference)) as image:
                image.load()
                if image.format not in {"PNG", "JPEG", "BMP", "WEBP"}:
                    raise ValueError("万相参考图格式不受支持")
                if (not 240 <= image.width <= 8000 or
                        not 240 <= image.height <= 8000 or
                        not 1 / 8 <= image.width / image.height <= 8):
                    raise ValueError("万相参考图尺寸超出支持范围")
                if "A" in image.getbands() or "transparency" in image.info:
                    rgba = image.convert("RGBA")
                    flattened = Image.new("RGB", rgba.size, "white")
                    flattened.paste(rgba, mask=rgba.getchannel("A"))
                    output = io.BytesIO()
                    flattened.save(output, format="PNG")
                    reference = output.getvalue()
                    mime = "image/png"
                else:
                    mime = Image.MIME[image.format]
            if len(reference) > 20 * 1024 * 1024:
                raise ValueError("万相归一化参考图超过 20MB")
            encoded = base64.b64encode(reference).decode("ascii")
            content_items.append({"image": f"data:{mime};base64,{encoded}"})
        content_items.append({"text": task["prompt"]})
        width, height = task.get("size", [1920, 1080])
        body = {
            "model": model,
            "input": {"messages": [{"role": "user", "content": content_items}]},
            "parameters": {"size": f"{width}*{height}", "n": 1,
                           "watermark": False,
                           "negative_prompt": task["negative_prompt"]},
        }
        if not references:
            body["parameters"]["thinking_mode"] = True
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
            try:
                items = data["output"]["choices"][0]["message"]["content"]
                url = next(item["image"] for item in items if item.get("image"))
            except (KeyError, IndexError, TypeError, StopIteration) as exc:
                raise RuntimeError("万相响应未包含生成图片地址") from exc
            with urllib.request.urlopen(url, timeout=600) as resp:
                content = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "ignore")[:400]
            raise RuntimeError(f"万相请求失败 {exc.code}：{detail}") from exc
        _validate_candidate(content)
        directory = os.path.dirname(task["output_path"])
        os.makedirs(directory, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=directory, suffix=".tmp",
                                             delete=False) as handle:
                temporary = handle.name
                handle.write(content)
            os.replace(temporary, task["output_path"])
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
