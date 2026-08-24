#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for provider-neutral workflow contracts and migration."""

import io
import os
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest import mock

import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPELINE = os.path.join(ROOT, "pipeline")
sys.path.insert(0, PIPELINE)

import proj as PJ
import build_long
import migrate_provider_architecture as migration
import tts_azure
import workflow
from providers import IMAGE_PROVIDERS, LLM_PROVIDERS
from providers.image import ImageGenProvider, WanxiangProvider
from workflow_contracts import (
    build_image_tasks, normalize_providers, read_json,
    validate_providers, validate_script, validate_storyboard, write_json,
)


def sample_storyboard():
    return {
        "version": 1,
        "blocks": [{
            "block_idx": 0, "type": "TITLE", "head": "TITLE",
            "voice_chars": 4,
            "subtitles": [
                {"id": 0, "text": "甲乙", "start_char": 0, "end_char": 2},
                {"id": 1, "text": "丙丁", "start_char": 2, "end_char": 4},
            ],
            "beats": [
                {"beat_idx": 0, "shot": "wide", "visual_description": "晨光中启程",
                 "sentence_ids": [0], "start_char": 0, "end_char": 2,
                 "character_ids": ["hero"], "emotion": "hopeful",
                 "segment": "hook"},
                {"beat_idx": 1, "shot": "close", "visual_description": "坚定的眼神",
                 "sentence_ids": [1], "start_char": 2, "end_char": 4,
                 "character_ids": ["hero"], "emotion": "determined",
                 "segment": "insight"},
            ],
        }],
    }


class ContractTests(unittest.TestCase):
    def test_provider_registry_and_no_stage_override(self):
        self.assertEqual(set(LLM_PROVIDERS), {"codex", "deepseek"})
        self.assertEqual(set(IMAGE_PROVIDERS), {"imagegen", "wanxiang"})
        self.assertEqual(validate_providers(
            normalize_providers(), LLM_PROVIDERS, IMAGE_PROVIDERS), [])
        bad = normalize_providers({"speech": {"name": "edge"}})
        self.assertIn("speech provider 必须为 azure",
                      validate_providers(bad, LLM_PROVIDERS, IMAGE_PROVIDERS))
        overridden = normalize_providers()
        overridden["llm"]["stages"] = {"script": "deepseek"}
        self.assertTrue(any("禁止阶段覆盖" in error for error in
                            validate_providers(overridden, LLM_PROVIDERS,
                                               IMAGE_PROVIDERS)))
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            workflow.parser().parse_args(
                ["run", "run_x", "script", "--llm", "deepseek"])

    def test_storyboard_schema_and_exact_sentence_coverage(self):
        data = sample_storyboard()
        self.assertEqual(validate_storyboard(data, known_character_ids={"hero"}), [])
        data["blocks"][0]["beats"][1]["sentence_ids"] = [0]
        errors = validate_storyboard(data, known_character_ids={"hero"})
        self.assertTrue(any("恰好覆盖" in error for error in errors))

    def test_storyboard_rejects_provider_fields_and_unknown_characters(self):
        data = sample_storyboard()
        data["blocks"][0]["beats"][0]["negative_prompt"] = "bad"
        errors = validate_storyboard(data, known_character_ids={"someone_else"})
        self.assertTrue(any("模型专用字段" in error for error in errors))
        self.assertTrue(any("未知角色" in error for error in errors))

    def test_image_tasks_are_provider_neutral_and_keep_character_anchor(self):
        with tempfile.TemporaryDirectory() as tmp:
            chars = {"hero": {"prompt": "same person", "anchor": "red scarf"}}
            tasks = build_image_tasks(sample_storyboard(), {}, chars, tmp)
            self.assertEqual([x["key"] for x in tasks], ["00_0", "00_1"])
            self.assertTrue(all(x["output_path"].startswith(tmp) for x in tasks))
            self.assertIn("red scarf", tasks[0]["prompt"])
            self.assertIn("one short headline or key phrase",
                          tasks[0]["prompt"])
            self.assertIn("normally no more than about 6 short groups",
                          tasks[0]["prompt"])
            self.assertIn("under 20 percent of the frame",
                          tasks[0]["prompt"])
            self.assertNotIn("at most 3 short label-or-number groups",
                             tasks[0]["prompt"])
            self.assertNotIn("no text or watermark", tasks[0]["prompt"])
            self.assertIn("dense text", tasks[0]["negative_prompt"])
            self.assertNotIn("full sentences", tasks[0]["negative_prompt"])
            self.assertNotIn("text, letters, numbers",
                             tasks[0]["negative_prompt"])
            self.assertEqual(ImageGenProvider({}, ROOT).generate(tasks)["tasks"], tasks)
            provider = WanxiangProvider({}, ROOT)
            with mock.patch.object(provider, "_config", return_value=("k", "u", "m")), \
                    mock.patch.object(provider, "_generate_one") as generate:
                provider.generate(tasks)
            self.assertEqual(generate.call_count, 2)


class WorkflowStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_projects = PJ.PROJECTS_DIR
        PJ.PROJECTS_DIR = os.path.join(self.tmp.name, "projects")
        PJ._CACHE.clear()

    def tearDown(self):
        PJ.PROJECTS_DIR = self.old_projects
        PJ._CACHE.clear()
        self.tmp.cleanup()

    def test_project_provider_snapshot_and_parallel_unlock(self):
        create_args = SimpleNamespace(
            project="003", llm="deepseek", llm_model="deepseek-chat",
            image="wanxiang", image_model="wan2.7-image",
            azure_voice="voice-A")
        with redirect_stdout(io.StringIO()):
            workflow.cmd_create(create_args)
            workflow.cmd_init(SimpleNamespace(project="003", run_id="run_test"))
        project = workflow.project_for_id("003")
        paths = workflow.state_paths(project, "run_test")
        state = read_json(paths["state"])
        self.assertEqual(state["providers"]["llm"]["name"], "deepseek")
        meta = read_json(os.path.join(project, "project.json"))
        meta["providers"]["llm"]["name"] = "codex"
        write_json(os.path.join(project, "project.json"), meta)
        self.assertEqual(read_json(paths["state"])["providers"]["llm"]["name"],
                         "deepseek")
        for stage in ("topic", "copy"):
            state["stages"][stage]["status"] = "promoted"
        state["stages"]["script"]["status"] = "promoted"
        workflow.unlock(state)
        self.assertEqual(state["stages"]["voice"]["status"], "pending")
        self.assertEqual(state["stages"]["storyboard"]["status"], "pending")

    def test_provider_change_rejected_while_run_active(self):
        args = SimpleNamespace(project="004", llm="codex", llm_model=None,
                               image="imagegen", image_model=None,
                               azure_voice="voice-A")
        with redirect_stdout(io.StringIO()):
            workflow.cmd_create(args)
            workflow.cmd_init(SimpleNamespace(project="004", run_id="run_active"))
        args.llm = "deepseek"
        with self.assertRaises(RuntimeError):
            with redirect_stdout(io.StringIO()):
                workflow.cmd_create(args)

    def test_interactive_topic_verify_promote_and_safe_rename(self):
        create = SimpleNamespace(project="005", llm="codex", llm_model=None,
                                 image="imagegen", image_model=None,
                                 azure_voice="voice-A")
        with redirect_stdout(io.StringIO()):
            workflow.cmd_create(create)
            workflow.cmd_init(SimpleNamespace(project="005", run_id="run_topic"))
            workflow.cmd_run(SimpleNamespace(run_id="run_topic", stage="topic",
                                              project="005", beats=None))
        paths, state = workflow.locate_run("run_topic", "005")
        self.assertEqual(state["stages"]["topic"]["status"], "awaiting_external")
        write_json(paths["topic"], {
            "candidates": [{
                "id": "t1", "book_title": "测试书", "author": "作者",
                "angle": "角度", "audience_promise": "承诺",
                "video_title": "标题", "rationale": "理由",
            }],
            "selected_id": None,
        })
        with redirect_stdout(io.StringIO()):
            workflow.cmd_select_topic(SimpleNamespace(
                run_id="run_topic", project="005", candidate_id="t1"))
            workflow.cmd_verify(SimpleNamespace(
                run_id="run_topic", project="005", stage="topic"))
            workflow.cmd_promote(SimpleNamespace(
                run_id="run_topic", project="005", stage="topic",
                replace=False))
        renamed = workflow.project_for_id("005")
        self.assertTrue(renamed.endswith("005_测试书"))
        _, state = workflow.locate_run("run_topic", "005")
        self.assertEqual(state["stages"]["topic"]["status"], "promoted")
        self.assertEqual(state["stages"]["copy"]["status"], "pending")


class AzureTests(unittest.TestCase):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return b"audio"

    def test_network_retry_stays_inside_azure(self):
        outcomes = [urllib.error.URLError("n1"), urllib.error.URLError("n2"),
                    urllib.error.URLError("n3"), self.Response()]
        sleeps = []

        def opener(*_args, **_kwargs):
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        result = tts_azure._request_audio(object(), opener=opener,
                                          sleeper=sleeps.append)
        self.assertEqual(result, b"audio")
        self.assertEqual(sleeps, [2, 5, 10])

    def test_missing_key_raises_instead_of_fallback(self):
        with mock.patch.object(tts_azure, "_cfg", return_value=""):
            with self.assertRaisesRegex(RuntimeError, "AZURE_SPEECH_KEY"):
                tts_azure.synthesize("测试", "/tmp/never-created.wav", "voice")

    def test_voice_must_come_from_project_or_run_snapshot(self):
        with mock.patch.object(tts_azure, "_cfg", return_value="key"), \
                mock.patch.object(tts_azure, "_region", return_value="eastasia"):
            with self.assertRaisesRegex(RuntimeError, "显式提供"):
                tts_azure.synthesize("测试", "/tmp/never-created.wav")

    def test_cache_key_contains_project_voice_and_text_hash(self):
        meta = {"providers": {"speech": {"name": "azure", "voice": "zh:Voice"}}}
        build_long.RUN_AZURE_VOICE = None
        with mock.patch.object(build_long.PJ, "read_meta", return_value=meta):
            first = build_long.voice_stem(1, "甲")
            again = build_long.voice_stem(1, "甲")
            changed = build_long.voice_stem(1, "乙")
        self.assertEqual(first, again)
        self.assertNotEqual(first, changed)
        self.assertIn("azurezh-Voice", first)
        self.assertNotIn(":", first)

    def test_run_voice_snapshot_precedes_later_project_config(self):
        meta = {"providers": {"speech": {"name": "azure", "voice": "new"}}}
        build_long.RUN_AZURE_VOICE = "snapshotted"
        try:
            with mock.patch.object(build_long.PJ, "read_meta", return_value=meta):
                self.assertEqual(build_long.azure_voice(), "snapshotted")
        finally:
            build_long.RUN_AZURE_VOICE = None

    def test_legacy_tts_implementations_are_absent(self):
        self.assertFalse(os.path.exists(os.path.join(PIPELINE, "tts_edge.py")))
        self.assertFalse(os.path.exists(os.path.join(PIPELINE, "tts_piper.py")))
        with open(os.path.join(PIPELINE, "build_long.py"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("TTS_SOURCE", source)
        self.assertNotIn('sh("say"', source)


class MigrationRegressionTests(unittest.TestCase):
    def _legacy_project(self, root, pid):
        project = os.path.join(root, f"{pid}_旧项目")
        input_dir = os.path.join(project, "input")
        scenes_dir = os.path.join(project, "assets", "scenes")
        os.makedirs(input_dir)
        os.makedirs(scenes_dir)
        write_json(os.path.join(project, "project.json"), {
            "id": pid, "title": "旧项目", "author": "测试作者",
        })
        brief = (
            "# 旧选题\n\n## 书目\n测试书\n\n## 作者\n测试作者\n\n"
            "## 视频标题\n迁移测试\n\n## 核心痛点\n保持内容一致\n\n"
            "## 目标受众\n普通观众\n"
        )
        with open(os.path.join(input_dir, "brief.md"), "w",
                  encoding="utf-8") as handle:
            handle.write(brief)

        parts = [
            "# TITLE\n## 迁移测试\nvoice：" + "旧剧本标题内容。" * 20,
        ]
        for index in range(1, 6):
            parts.extend([
                f"# PHASE {index:02d} · 阶段{index}",
                f"# CARD\n## 阶段{index}要点\nvoice：" +
                f"这是第{index}阶段的旧剧本内容，用于验证迁移前后文本完全一致。" * 12,
            ])
        parts.append("# END")
        script_text = "\n\n".join(parts) + "\n"
        script_path = os.path.join(input_dir, "script.txt")
        with open(script_path, "w", encoding="utf-8") as handle:
            handle.write(script_text)
        errors, _, blocks = validate_script(script_text)
        self.assertEqual(errors, [])

        narrative = {"version": 1, "blocks": []}
        for block_idx, block in enumerate(blocks):
            voice = block.get("voice") or ""
            subtitles = ([{
                "id": 0, "text": voice,
                "start_char": 0, "end_char": len(voice),
            }] if voice else [])
            narrative["blocks"].append({
                "block_idx": block_idx,
                "type": block["type"],
                "head": block["head"],
                "voice_chars": len(voice),
                "subtitles": subtitles,
                "beats": [{
                    "beat_idx": 0,
                    "shot": "medium",
                    "visual_description": (
                        f"阶段 {block_idx} 的旧语义画面" if voice else ""),
                    "sentence_ids": [0] if voice else [],
                    "start_char": 0,
                    "end_char": len(voice),
                    "character_ids": ["none"],
                    "emotion": "neutral",
                }],
            })
        write_json(os.path.join(input_dir, "storyboard_narrative.json"),
                   narrative)
        for key in ("00_0", "02_0"):
            with open(os.path.join(scenes_dir, key + ".png"), "wb") as handle:
                handle.write(b"fixture")
        return project

    def test_migration_preserves_script_blocks_beats_and_image_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            for pid in ("001", "002"):
                project = self._legacy_project(tmp, pid)
                result = migration.migrate_project(project)
                manifest = result["manifest"]
                self.assertEqual(manifest["script_sha256_before"],
                                 manifest["script_sha256_after"])
                self.assertEqual(manifest["blocks_before"],
                                 manifest["blocks_after"])
                self.assertEqual(manifest["beats_before"],
                                 manifest["beats_after"])
                with open(os.path.join(project, "input", "script.txt"),
                          encoding="utf-8") as handle:
                    errors, _, blocks = validate_script(handle.read())
                self.assertEqual(errors, [])
                storyboard = read_json(
                    os.path.join(project, "input", "storyboard.json"))
                self.assertEqual(validate_storyboard(storyboard, blocks), [])
                current_keys = sorted(
                    os.path.splitext(name)[0]
                    for name in os.listdir(
                        os.path.join(project, "assets", "scenes"))
                    if name.endswith(".png") and name[0:2].isdigit())
                self.assertEqual(manifest["image_keys"], current_keys)


if __name__ == "__main__":
    unittest.main()
