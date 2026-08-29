#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Codex interactive and DeepSeek API LLM providers."""

import json
import os
import urllib.error
import urllib.request

from workflow_contracts import parse_script, write_json


PHASE_NAMES = ["开场共情", "底层病灶", "核心模型", "实战工具", "哲学升华"]


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


def _extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    start_obj, start_arr = text.find("{"), text.find("[")
    starts = [x for x in (start_obj, start_arr) if x >= 0]
    if not starts:
        raise ValueError("模型响应中没有 JSON")
    start = min(starts)
    end = max(text.rfind("}"), text.rfind("]"))
    return json.loads(text[start:end + 1])


class CodexProvider:
    mode = "interactive"
    stages = {"topic", "copy", "script", "storyboard", "brand", "publish"}

    def __init__(self, config, root):
        self.config = config
        self.root = root

    def generate(self, stage, task, destination):
        return {"mode": self.mode, "task": task, "destination": destination}


class DeepSeekProvider:
    mode = "api"
    stages = {"topic", "copy", "script", "storyboard", "brand", "publish"}
    default_model = "deepseek-v4-flash"

    def __init__(self, config, root):
        self.config = config
        self.root = root

    def _call(self, system, user):
        values = _dotenv(self.root)
        key = os.environ.get("DEEPSEEK_API_KEY") or values.get("DEEPSEEK_API_KEY")
        if not key:
            raise RuntimeError("缺少 DEEPSEEK_API_KEY")
        base = os.environ.get("DEEPSEEK_BASE_URL") or \
            values.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com/v1"
        model = self.config.get("model") or self.default_model
        body = {"model": model, "temperature": 0.5,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}]}
        req = urllib.request.Request(
            base.rstrip("/") + "/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {key}"})
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "ignore")[:400]
            raise RuntimeError(f"DeepSeek 请求失败 {exc.code}：{detail}") from exc
        return data["choices"][0]["message"]["content"]

    def generate(self, stage, task, destination):
        if stage == "topic":
            data = self._topic(task)
            write_json(destination, data)
        elif stage == "copy":
            data = self._copy(task)
            write_json(destination, data)
        elif stage == "script":
            text = self._script(task)
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            with open(destination, "w", encoding="utf-8") as f:
                f.write(text.rstrip() + "\n")
        elif stage == "storyboard":
            write_json(destination, self._storyboard(task))
        elif stage in ("brand", "publish"):
            write_json(destination, self._generic(stage, task))
        else:
            raise ValueError(f"DeepSeek 不支持阶段：{stage}")
        return {"mode": self.mode, "destination": destination}

    def _generic(self, stage, task):
        contract = task.get("output_contract", {})
        system = ("你是中文频道发布编辑。只输出符合任务 output_contract 的 JSON，"
                  "不得添加解释、代码块或额外字段。")
        return _extract_json(self._call(system, json.dumps({
            "stage": stage, "contract": contract, "source": task.get("source", task)
        }, ensure_ascii=False)))

    def _topic(self, task):
        system = ("你是中文听书视频选题编辑。只输出 JSON。给出 3 个候选，字段为 "
                  "id,book_title,author,angle,audience_promise,video_title,rationale。"
                  "顶层字段 candidates 和 selected_id，selected_id 必须为 null。")
        return _extract_json(self._call(system, task.get("topic_request", "")))

    def _copy(self, task):
        system = ("你是听书解读内容策划。只输出 JSON：thesis, audience_promise, "
                  "claims(array), sections(array exactly 5)。每个 section 含 name, "
                  "objective, key_points(array), examples(array), action。五段依次为："
                  + "、".join(PHASE_NAMES))
        return _extract_json(self._call(
            system, json.dumps(task["topic"], ensure_ascii=False)))

    def _script(self, task):
        system = ("你是中文听书长视频编剧。输出纯文本，不用代码块。严格使用 # TITLE、"
                  "五个 # PHASE nn · 名称、# CARD/# QUOTE/# TABLE/# STEPS 和 # END；"
                  "非 PHASE 块必须有 voice：。总口播 3800-4500 字。")
        return self._call(system, json.dumps({"topic": task["topic"],
                                               "copy": task["copy"]},
                                              ensure_ascii=False))

    def _storyboard(self, task):
        text = task["script_text"]
        blocks = parse_script(text)
        direct_phase = task.get("phase_transition") == "direct"
        result = {"version": 1, "style": "provider-neutral semantic storyboard",
                  "blocks": []}
        phase = "hook"
        for bi, block in enumerate(blocks):
            if block["type"] in ("PHASE", "END"):
                if block["type"] == "PHASE":
                    if "02" in block["head"] or "03" in block["head"]:
                        phase = "insight"
                    elif "04" in block["head"] or "05" in block["head"]:
                        phase = "action"
                    description = (
                        f"章节过渡画面：{block['head']}，以环境和光线变化承接叙事。")
                else:
                    phase = "action"
                    description = "全片收束画面，人物走向开阔远景，留下思考余韵。"
                phase_beats = [] if block["type"] == "PHASE" and direct_phase else [{
                    "beat_idx": 0, "shot": "wide",
                    "visual_description": description,
                    "sentence_ids": [],
                    "start_char": 0, "end_char": 0,
                    "character_ids": [], "emotion": "neutral",
                    "segment": phase,
                }]
                result["blocks"].append({
                    "block_idx": bi, "type": block["type"], "head": block["head"],
                    "voice_chars": 0, "subtitles": [],
                    "beats": phase_beats})
                continue
            voice = block.get("voice") or ""
            sentences = _sentences(voice)
            prompt = {"block_idx": bi, "type": block["type"],
                      "head": block["head"], "sentences": sentences,
                      "required_segment": phase}
            system = ("你是语义分镜师。只输出 JSON 数组，每项含 shot(wide/medium/close), "
                      "visual_description, sentence_ids(array), character_ids(array), "
                      "emotion, segment(hook/insight/action)。用 3-5 拍连续覆盖所有句子，"
                      "每个句子只能出现一次；不得输出图片模型 Prompt 或 provider 字段。")
            beats_raw = _extract_json(self._call(
                system, json.dumps(prompt, ensure_ascii=False)))
            beats_raw = beats_raw.get("beats", []) if isinstance(beats_raw, dict) \
                else beats_raw
            subtitles, offset = [], 0
            for i, sentence in enumerate(sentences):
                subtitles.append({"id": i, "text": sentence,
                                  "start_char": offset,
                                  "end_char": offset + len(sentence)})
                offset += len(sentence)
            sub_map = {x["id"]: x for x in subtitles}
            beats = []
            for i, beat in enumerate(beats_raw):
                ids = beat.get("sentence_ids") or []
                if not ids:
                    continue
                beats.append({
                    "beat_idx": len(beats), "shot": beat.get("shot", "medium"),
                    "visual_description": beat.get("visual_description", ""),
                    "sentence_ids": ids,
                    "start_char": sub_map[ids[0]]["start_char"],
                    "end_char": sub_map[ids[-1]]["end_char"],
                    "character_ids": beat.get("character_ids") or [],
                    "emotion": beat.get("emotion") or "neutral",
                    "segment": beat.get("segment") or phase,
                })
            result["blocks"].append({
                "block_idx": bi, "type": block["type"], "head": block["head"],
                "voice_chars": len(voice), "subtitles": subtitles, "beats": beats})
        return result


def _sentences(text):
    out, current = [], ""
    for char in text:
        current += char
        if char in "。！？；":
            out.append(current)
            current = ""
    if current:
        out.append(current)
    return out
