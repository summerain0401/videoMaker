#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for provider-neutral workflow contracts and migration."""

import copy
import inspect
import io
import os
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest import mock

from PIL import Image

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
from content_templates import CONTENT_TEMPLATE_IDS, get_template
from workflow_contracts import (
    build_image_tasks, normalize_providers, read_json,
    validate_copy, validate_image_task_prompt,
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
    def test_content_templates_are_versioned_and_define_five_valid_stages(self):
        self.assertEqual(set(CONTENT_TEMPLATE_IDS), {
            "classic_insight_v1", "story_journey_v1", "practical_workshop_v1"})
        snapshots = [get_template(name) for name in CONTENT_TEMPLATE_IDS]
        self.assertEqual(len({(x["id"], x["version"]) for x in snapshots}), 3)
        self.assertTrue(all(len(x["stages"]) == 5 and x["sha256"] for x in snapshots))
        self.assertTrue(all(stage["segment"] in {"hook", "insight", "action"}
                            for item in snapshots for stage in item["stages"]))

    def test_content_template_validates_copy_and_script_phase_names(self):
        template = get_template("story_journey_v1")
        sections = [{"name": stage["name"], "objective": "目标",
                     "key_points": ["要点"], "examples": [], "action": "行动"}
                    for stage in template["stages"]]
        copy_data = {"thesis": "论点", "audience_promise": "承诺",
                     "claims": ["事实"], "sections": sections}
        self.assertEqual(validate_copy(copy_data, template), [])
        copy_data["sections"][1]["name"] = "错误标题"
        self.assertTrue(validate_copy(copy_data, template))
        phases = "".join(
            f"# PHASE {stage['index']:02d} · {stage['name']}\n# CARD\nvoice：" +
            "甲" * 800 + "\n" for stage in template["stages"])
        script = "# TITLE\nvoice：标题\n" + phases + "# END\n"
        self.assertEqual(validate_script(script, content_template=template)[0], [])
        self.assertTrue(validate_script(
            script.replace("人物处境", "错误标题", 1),
            content_template=template)[0])

    @staticmethod
    def _density_story(chars, beat_sizes=None, block_type="CARD", sentence_count=None):
        sizes = beat_sizes or [chars]
        if sentence_count is None:
            sentence_count = len(sizes)
        subtitles = []
        cursor = 0
        for idx in range(sentence_count):
            size = sizes[idx] if idx < len(sizes) else 1
            subtitles.append({"id": idx, "text": "甲" * size,
                              "start_char": cursor, "end_char": cursor + size})
            cursor += size
        beats = []
        cursor = 0
        for idx, size in enumerate(sizes):
            beats.append({"beat_idx": idx, "shot": "medium",
                          "visual_description": f"画面{idx}",
                          "sentence_ids": [idx] if idx < sentence_count else [],
                          "start_char": cursor, "end_char": cursor + size,
                          "character_ids": ["hero"], "emotion": "neutral",
                          "segment": "insight"})
            cursor += size
        return {"version": 1, "blocks": [{"block_idx": 0, "type": block_type,
            "head": block_type, "voice_chars": chars, "subtitles": subtitles,
            "beats": beats}]}

    def test_storyboard_density_boundaries(self):
        for chars, minimum in ((120, 1), (121, 2), (220, 2),
                               (221, 3), (320, 3), (321, 4)):
            base, remainder = divmod(chars, minimum)
            sizes = [base + (1 if i < remainder else 0) for i in range(minimum)]
            self.assertEqual(validate_storyboard(
                self._density_story(chars, sizes), known_character_ids={"hero"}), [], chars)

    def test_storyboard_density_rejects_overlong_five_sentence_and_phase(self):
        errors = validate_storyboard(self._density_story(121, [121]), known_character_ids={"hero"})
        self.assertTrue(any("至少需要 2 拍" in error for error in errors))
        five = self._density_story(50, [50], sentence_count=5)
        five["blocks"][0]["subtitles"] = [
            {"id": i, "text": "甲" * 10, "start_char": i * 10, "end_char": (i + 1) * 10}
            for i in range(5)]
        five["blocks"][0]["beats"][0]["sentence_ids"] = list(range(5))
        errors = validate_storyboard(five, known_character_ids={"hero"})
        self.assertTrue(any("最多覆盖 4 句" in error for error in errors))
        phase = self._density_story(0, [0, 0], block_type="PHASE", sentence_count=0)
        self.assertTrue(any("PHASE 必须且只能包含一拍" in error
                            for error in validate_storyboard(phase)))

    def test_storyboard_density_rejects_sentence_per_image_over_split(self):
        story = self._density_story(121, [31, 30, 30, 30])
        errors = validate_storyboard(story, known_character_ids={"hero"})
        self.assertTrue(any("避免逐句一图" in error for error in errors))

    def test_long_narrative_beats_use_one_continuous_zoompan(self):
        source = inspect.getsource(build_long.render_scene_narrative)
        self.assertIn("每个 beat 始终使用一条完整 zoompan 轨迹", source)
        self.assertNotIn("split=2", source)
        self.assertNotIn("concat=n=2:v=1:a=0", source)
        # 第二个 zoompan 属于独立的 deco 视差层，不是 beat 图片轨迹。
        beat_section = source.split("# 块内卡点硬切", 1)[0]
        self.assertEqual(beat_section.count("zoompan=z='"), 1)

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
            self.assertIn("no reserved caption panel or empty bottom band",
                          tasks[0]["prompt"])
            self.assertIn("natural scenery and texture to continue to every edge",
                          tasks[0]["prompt"])
            self.assertNotIn("bottom 15 percent", tasks[0]["prompt"])
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

    def test_style_anchor_is_not_overwritten_by_character_anchor(self):
        with tempfile.TemporaryDirectory() as tmp:
            anchor = {"path": "/tmp/style.png", "sha256": "style-hash"}
            tasks = build_image_tasks(
                sample_storyboard(), {},
                {"hero": {"prompt": "same person", "anchor": "red scarf"}},
                tmp, anchor)
        self.assertEqual(tasks[0]["style_anchor"]["sha256"], "style-hash")
        self.assertIn("red scarf", tasks[0]["rule_manifest"]["prompt_sources"]["char_bits"][0])

    def test_bootstrap_anchor_keeps_first_task_reference_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            anchor = {"path": "/tmp/style.png", "sha256": "style-hash"}
            tasks = build_image_tasks(sample_storyboard(), {},
                                      {"hero": {"prompt": "same person"}},
                                      tmp, anchor, bootstrap_anchor_key="00_0")
        self.assertEqual(tasks[0]["reference_images"], [])
        self.assertEqual(tasks[0]["style_anchor"]["mode"], "bootstrap")
        self.assertEqual(tasks[1]["reference_images"], ["/tmp/style.png"])

    def test_phase_image_task_integrates_exact_title_and_uses_stable_key(self):
        storyboard = {
            "blocks": [{
                "block_idx": 4,
                "type": "PHASE",
                "head": "PHASE 02 · 锚点怎样改变价值感",
                "subtitles": [],
                "beats": [{
                    "beat_idx": 0,
                    "shot": "wide",
                    "visual_description": "雾中岔路与被路灯照亮的路牌",
                    "sentence_ids": [],
                    "start_char": 0,
                    "end_char": 0,
                    "character_ids": ["none"],
                    "emotion": "analytical",
                    "segment": "insight",
                }],
            }],
        }
        with tempfile.TemporaryDirectory() as tmp:
            task = build_image_tasks(storyboard, {}, {"none": {}}, tmp)[0]
        self.assertEqual(task["key"], "phase_02")
        self.assertEqual(task["kind"], "phase_title")
        self.assertEqual(task["title_text"], "锚点怎样改变价值感")
        self.assertTrue(task["output_path"].endswith("phase_02.png"))
        self.assertIn('"锚点怎样改变价值感"', task["prompt"])
        self.assertIn("physical part of the depicted world", task["prompt"])
        self.assertIn("never use a floating overlay", task["prompt"])
        self.assertIn("no reserved caption panel or empty bottom band",
                      task["prompt"])
        second_beat = copy.deepcopy(storyboard["blocks"][0]["beats"][0])
        second_beat["beat_idx"] = 1
        storyboard["blocks"][0]["beats"].append(second_beat)
        self.assertTrue(any("PHASE 必须且只能包含一拍" in error for error in
                            validate_storyboard(storyboard)))

    def test_direct_phase_skips_phase_tasks_and_allows_empty_phase(self):
        storyboard = {"blocks": [
            {"block_idx": 0, "type": "PHASE", "head": "PHASE 01 · 开始",
             "voice_chars": 0, "subtitles": [], "beats": []},
            {"block_idx": 1, "type": "TITLE", "head": "TITLE",
             "voice_chars": 1, "subtitles": [{"id": 0, "text": "甲",
             "start_char": 0, "end_char": 1}], "beats": [{
                 "beat_idx": 0, "shot": "wide", "visual_description": "独特场景",
                 "sentence_ids": [0], "start_char": 0, "end_char": 1,
                 "character_ids": ["hero"], "emotion": "neutral", "segment": "hook"}]}]}
        meta = {"visual_style": {"phase_transition": "direct"}}
        self.assertEqual(validate_storyboard(storyboard, project_meta=meta), [])
        with tempfile.TemporaryDirectory() as tmp:
            tasks = build_image_tasks(storyboard, meta,
                                      {"hero": {"prompt": "a hero"}}, tmp)
        self.assertEqual([task["key"] for task in tasks], ["01_0"])

    def test_direct_phase_rejects_image_beat(self):
        story = {"blocks": [{
            "block_idx": 0, "type": "PHASE", "head": "PHASE 01 · 开始",
            "voice_chars": 0, "subtitles": [], "beats": [{
                "beat_idx": 0, "shot": "wide", "visual_description": "过渡画面",
                "sentence_ids": [], "start_char": 0, "end_char": 0,
                "character_ids": [], "emotion": "neutral", "segment": "hook"}]}]}
        errors = validate_storyboard(
            story, project_meta={"visual_style": {"phase_transition": "direct"}})
        self.assertTrue(any("direct 阶段不得包含图片拍" in error for error in errors))

    def test_storyboard_rejects_duplicate_visual_descriptions(self):
        story = self._density_story(2, [1, 1], sentence_count=2)
        story["blocks"][0]["beats"][1]["visual_description"] = "画面0"
        errors = validate_storyboard(story, known_character_ids={"hero"})
        self.assertTrue(any("视觉描述重复" in error for error in errors))

    def test_storyboard_rejects_near_duplicate_visual_descriptions(self):
        story = self._density_story(60, [30, 30], sentence_count=2)
        first = "深夜厨房里女孩拧紧漏水阀门，接水盘接住冷青色水滴"
        story["blocks"][0]["beats"][0]["visual_description"] = first
        story["blocks"][0]["beats"][1]["visual_description"] = (
            "深夜厨房中女孩拧紧漏水阀门，接水盘接住冷青色水滴")
        errors = validate_storyboard(story, known_character_ids={"hero"})
        self.assertTrue(any("视觉描述高度相似" in error for error in errors))

    def test_script_rejects_multiple_voice_lines(self):
        text = "# TITLE\nvoice：" + "甲" * 1000 + "\nvoice：乙\n# END\n"
        errors, _, _ = validate_script(text)
        self.assertTrue(any("多条 voice" in error for error in errors))

    def test_image_prompt_rule_manifest_detects_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            tasks = build_image_tasks(sample_storyboard(), {},
                                      {"hero": {"prompt": "same person"}}, tmp)
        self.assertEqual(validate_image_task_prompt(tasks[0]), [])
        tasks[0]["prompt"] += ", no text"
        self.assertTrue(validate_image_task_prompt(tasks[0]))
        tasks[0]["prompt"] = tasks[0]["rule_manifest"]["prompt_sources"]["style"]
        tasks[0]["negative_prompt"] = "no text"
        self.assertTrue(validate_image_task_prompt(tasks[0]))

    def test_image_task_packet_rejects_coordinated_prompt_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            expected = build_image_tasks(sample_storyboard(), {},
                                         {"hero": {"prompt": "same person"}}, tmp)
        actual = copy.deepcopy(expected)
        actual[0]["rule_manifest"]["prompt_sources"]["text_policy"] += ", no text"
        actual[0]["prompt"] = actual[0]["prompt"] + ", no text"
        self.assertTrue(workflow._image_task_packet_problems(expected, actual))


class RenderRegressionTests(unittest.TestCase):
    def test_direct_phase_transition_removes_phase_render_blocks(self):
        blocks = [{"type": "PHASE", "_source_idx": 1},
                  {"type": "CARD", "_source_idx": 2}]
        story = {"blocks": [{"block_idx": 1, "type": "PHASE"},
                             {"block_idx": 2, "type": "CARD"}]}
        kept_blocks, kept_story = build_long.remove_direct_phase_blocks(
            blocks, story)
        self.assertEqual([item["type"] for item in kept_blocks], ["CARD"])
        self.assertEqual([item["type"] for item in kept_story["blocks"]],
                         ["CARD"])

    def test_highly_similar_images_are_blocked(self):
        image = Image.new("RGB", (160, 90), (50, 80, 120))
        first = workflow._image_fingerprint(image)
        second = workflow._image_fingerprint(image.copy())
        problems = workflow._duplicate_image_problems(
            [("00_0", first), ("01_0", second)])
        self.assertTrue(any("候选图片高相似" in problem for problem in problems))

    def test_distinct_color_images_are_not_a_similarity_false_positive(self):
        first = workflow._image_fingerprint(
            Image.new("RGB", (160, 90), (20, 30, 220)))
        second = workflow._image_fingerprint(
            Image.new("RGB", (160, 90), (220, 210, 20)))
        self.assertEqual(workflow._duplicate_image_problems(
            [("00_0", first), ("01_0", second)]), [])

    def test_phase_title_layer_and_duration(self):
        layer = build_long.V.make_phase_title_layer(
            "PHASE 03 · 生活中的三类价格锚")
        self.assertEqual(layer.size, (1920, 1080))
        self.assertIsNotNone(layer.getchannel("A").getbbox())
        self.assertEqual(build_long.PHASE_DUR, 2.5)

    def test_integrated_phase_art_disables_overlay_fallback(self):
        old_dir = build_long.PHASE_ART_DIR
        try:
            with tempfile.TemporaryDirectory() as tmp:
                phase_path = os.path.join(tmp, "phase_03.png")
                with open(phase_path, "wb") as handle:
                    handle.write(b"candidate")
                build_long.PHASE_ART_DIR = tmp
                block = {"head": "PHASE 03 · 生活中的三类价格锚"}
                self.assertEqual(
                    build_long.integrated_phase_art_path(block), phase_path)
        finally:
            build_long.PHASE_ART_DIR = old_dir

    def test_motion_profiles_change_by_shot_and_are_deterministic(self):
        wide = build_long.motion_exprs(3, 300, "wide", "alert", "hook")
        medium = build_long.motion_exprs(
            3, 300, "medium", "alert", "hook")
        close = build_long.motion_exprs(3, 300, "close", "alert", "hook")
        self.assertEqual(
            wide, build_long.motion_exprs(3, 300, "wide", "alert", "hook"))
        self.assertNotEqual(wide, medium)
        self.assertNotEqual(medium, close)
        self.assertTrue(all("iw-iw/zoom" in item for item in
                            (wide[1], medium[1], close[1])))

    def test_motion_v2_uses_smoothstep_and_explicit_direction(self):
        forward = build_long.motion_exprs(3, 120, "medium", "alert", "hook",
                                           direction=1)
        backward = build_long.motion_exprs(99, 120, "medium", "alert", "hook",
                                            direction=-1)
        self.assertIn("min(1,max(0,on/119.000))", forward[0])
        self.assertNotEqual(forward[1], backward[1])
        self.assertIn("0.140", forward[0])
        calm_a = build_long.motion_exprs(3, 120, "medium", "calm", "hook",
                                         direction=1)
        calm_b = build_long.motion_exprs(3, 120, "medium", "calm", "hook",
                                         direction=1)
        self.assertEqual(calm_a, calm_b)
        self.assertIn("0.140", calm_a[0])

    def test_motion_long_beats_use_five_second_multiaxis_legs(self):
        short = build_long.motion_exprs(1, 150, "medium", "alert", "hook")
        long = build_long.motion_exprs(1, 750, "medium", "alert", "hook")
        self.assertNotIn("gte(on,", short[0])
        self.assertIn("gte(on,149.800)", long[1])
        self.assertIn("gte(on,299.600)", long[1])
        self.assertNotIn("gte(on,", long[0])
        self.assertGreaterEqual(long[1].count("if(gte(on,"), 3)
        self.assertNotIn("sin", long[0] + long[1] + long[2])
        self.assertEqual(long, build_long.motion_exprs(
            1, 750, "medium", "alert", "hook", direction=1))
        mirrored = build_long.motion_exprs(
            1, 750, "medium", "alert", "hook", direction=-1)
        self.assertNotEqual(long[1], mirrored[1])
        self.assertEqual(long[2], mirrored[2])

    def test_subtitle_keeps_source_ranges_and_never_splits_book_title(self):
        text = ("今天我们用威廉·庞德斯通的《无价》，拆开价格背后的锚定效应。"
                "你会买吗？")
        chunks = build_long.subtitle_chunk_events(
            text, protected_words=build_long.subtitle_protected_terms(
                ("《无价》", "锚定", "威廉·庞德斯通")))
        self.assertEqual("".join(x["source_text"] for x in chunks), text)
        self.assertEqual(chunks[0]["source_start"], 0)
        self.assertEqual(chunks[-1]["source_end"], len(text))
        title_chunks = [x for x in chunks if "《" in x["source_text"]]
        self.assertEqual(len(title_chunks), 1)
        self.assertIn("《无价》", title_chunks[0]["source_text"])
        self.assertTrue(all(not x["display_text"].endswith(tuple("，。；、"))
                            for x in chunks))
        self.assertTrue(any(x["display_text"].endswith("？") for x in chunks))

    def test_sfx_mix_disables_amix_normalization(self):
        with mock.patch.object(build_long, "synth_sfx",
                               return_value="/tmp/fake.wav"), \
                mock.patch.object(build_long, "sh") as sh:
            build_long.mix_sfx(
                "/tmp/voice.wav", [("reveal", 1000)], "/tmp/out.wav")
        command = sh.call_args.args
        graph = command[command.index("-filter_complex") + 1]
        self.assertIn("normalize=0", graph)
        self.assertIn("volume=0.160", graph)
        self.assertNotIn("volume=0.35", graph)


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
            azure_voice="voice-A", content_template="story_journey_v1")
        with redirect_stdout(io.StringIO()):
            workflow.cmd_create(create_args)
            workflow.cmd_init(SimpleNamespace(project="003", run_id="run_test"))
        project = workflow.project_for_id("003")
        paths = workflow.state_paths(project, "run_test")
        state = read_json(paths["state"])
        self.assertEqual(state["providers"]["llm"]["name"], "deepseek")
        self.assertEqual(state["content_template"]["id"], "story_journey_v1")
        meta = read_json(os.path.join(project, "project.json"))
        meta["providers"]["llm"]["name"] = "codex"
        meta["content_template"] = "practical_workshop_v1"
        write_json(os.path.join(project, "project.json"), meta)
        self.assertEqual(read_json(paths["state"])["providers"]["llm"]["name"],
                         "deepseek")
        task = workflow.build_task(paths, state, "topic")
        self.assertEqual(task["content_template"]["id"], "story_journey_v1")
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

    def test_storyboard_revision_inherits_hashes_and_supersedes_source(self):
        create = SimpleNamespace(project="007", llm="codex", llm_model=None,
                                 image="imagegen", image_model=None,
                                 azure_voice="voice-A",
                                 content_template="practical_workshop_v1")
        with redirect_stdout(io.StringIO()):
            workflow.cmd_create(create)
            workflow.cmd_init(SimpleNamespace(project="007", run_id="run_source"))
        project = workflow.project_for_id("007")
        paths = workflow.state_paths(project, "run_source")
        formal = workflow.formal_paths(project)
        os.makedirs(os.path.dirname(formal["topic"]), exist_ok=True)
        write_json(formal["topic"], {"book_title": "测试书"})
        write_json(formal["copy"], {"thesis": "测试"})
        with open(formal["script"], "w", encoding="utf-8") as handle:
            handle.write("# TITLE\n## 测试\nvoice：测试正文。\n# END\n")
        os.makedirs(os.path.join(project, "assets", "scenes"), exist_ok=True)
        with open(os.path.join(project, "assets", "scenes", "00_0.png"), "wb") as handle:
            handle.write(b"source-scene")
        state = read_json(paths["state"])
        for stage in ("topic", "copy", "script"):
            state["stages"][stage]["status"] = "promoted"
        workflow.save_state(paths, state)
        with redirect_stdout(io.StringIO()):
            workflow.cmd_revise(SimpleNamespace(source_run_id="run_source",
                                                stage="storyboard", project="007",
                                                run_id="run_revision"))
        new_paths, new_state = workflow.locate_run("run_revision", "007")
        self.assertEqual(new_state["lineage"]["source_run"], "run_source")
        self.assertEqual(new_state["content_template"]["id"],
                         "practical_workshop_v1")
        for stage in ("topic", "copy", "script"):
            inherited = new_state["lineage"]["inherited_assets"][stage]
            self.assertEqual(inherited["sha256"], workflow._sha256(formal[stage]))
            self.assertEqual(new_state["stages"][stage]["status"], "promoted")
        self.assertNotEqual(new_paths["storyboard"], paths["storyboard"])
        self.assertTrue(os.path.exists(os.path.join(project, "assets", "scenes", "00_0.png")))
        source_state = read_json(paths["state"])
        self.assertEqual(source_state["superseded_by"], "run_revision")
        for func, args in ((workflow.cmd_run, SimpleNamespace(run_id="run_source", project="007", stage="storyboard")),
                           (workflow.cmd_verify, SimpleNamespace(run_id="run_source", project="007", stage="storyboard")),
                           (workflow.cmd_promote, SimpleNamespace(run_id="run_source", project="007", stage="storyboard", replace=False))):
            with self.assertRaises(RuntimeError), redirect_stderr(io.StringIO()):
                func(args)

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

    def test_review_is_isolated_and_revision_preserves_previous_render(self):
        create = SimpleNamespace(
            project="006", llm="codex", llm_model=None,
            image="imagegen", image_model=None, azure_voice="voice-A")
        with redirect_stdout(io.StringIO()):
            workflow.cmd_create(create)
            workflow.cmd_init(SimpleNamespace(project="006", run_id="run_render"))
        project = workflow.project_for_id("006")
        paths = workflow.state_paths(project, "run_render")
        formal = workflow.formal_paths(project)
        os.makedirs(os.path.dirname(formal["script"]), exist_ok=True)
        with open(formal["script"], "w", encoding="utf-8") as handle:
            handle.write("# TITLE\n## 测试\nvoice：测试正文。\n# END\n")
        write_json(formal["storyboard"], {"version": 1, "blocks": []})
        old_video = os.path.join(project, "output", "long_006.mp4")
        os.makedirs(os.path.dirname(old_video), exist_ok=True)
        with open(old_video, "wb") as handle:
            handle.write(b"old")
        old_qa = os.path.join(paths["run_dir"], "qa.json")
        write_json(old_qa, {"video": old_video})
        state = read_json(paths["state"])
        for stage in ("images", "voice", "render", "qa"):
            state["stages"][stage]["status"] = "promoted"
        state["stages"]["render"]["artifact"] = old_video
        state["stages"]["qa"]["artifact"] = old_qa
        workflow.save_state(paths, state)

        def fake_render(command, check):
            self.assertTrue(check)
            if "--review-id" in command:
                target = os.path.join(
                    project, "output", "reviews", "immersive_v2", "review.mp4")
            else:
                target = os.path.join(project, "output", "long_006_v2.mp4")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as handle:
                handle.write(b"new")

        before = copy.deepcopy(state)
        review_args = SimpleNamespace(
            review_id="immersive_v2", revision=None, blocks=[1, 2],
            clip_durations=[2.5, 12.0])
        with mock.patch.object(workflow.subprocess, "run", side_effect=fake_render), \
                redirect_stdout(io.StringIO()):
            workflow._run_render(paths, state, review_args)
        self.assertEqual(state, before)
        self.assertTrue(os.path.exists(os.path.join(
            project, "output", "reviews", "immersive_v2", "manifest.json")))
        with open(old_video, "rb") as handle:
            self.assertEqual(handle.read(), b"old")

        revision_args = SimpleNamespace(
            review_id=None, revision="v2", blocks=None, clip_durations=None)
        with mock.patch.object(workflow.subprocess, "run", side_effect=fake_render), \
                redirect_stdout(io.StringIO()):
            workflow._run_render(paths, state, revision_args)
        self.assertEqual(state["stages"]["render"]["revision"], "v2")
        self.assertTrue(state["stages"]["render"]["artifact"].endswith(
            "long_006_v2.mp4"))
        self.assertEqual(state["stages"]["qa"]["status"], "pending")
        self.assertEqual(state["render_history"][0]["artifact"], old_video)
        with open(old_video, "rb") as handle:
            self.assertEqual(handle.read(), b"old")


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
        # 迁移旧项目只需解析结构，生产新 run 才执行 3800-4500 字门禁。
        errors, _, blocks = validate_script(script_text, enforce_length=False)
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
                    errors, _, blocks = validate_script(handle.read(), enforce_length=False)
                self.assertEqual(errors, [])
                storyboard = read_json(
                    os.path.join(project, "input", "storyboard.json"))
                self.assertEqual(validate_storyboard(storyboard, blocks,
                                                     enforce_density=False,
                                                     enforce_visual_quality=False), [])
                current_keys = sorted(
                    os.path.splitext(name)[0]
                    for name in os.listdir(
                        os.path.join(project, "assets", "scenes"))
                    if name.endswith(".png") and name[0:2].isdigit())
            self.assertEqual(manifest["image_keys"], current_keys)


class StoryboardQualityGateTests(unittest.TestCase):
    def test_script_length_production_boundaries(self):
        def script(n):
            head = "# TITLE\nvoice：标题\n"
            each, remainder = divmod(n - 2, 5)
            phases = "".join(f"# PHASE {i:02d} · 阶段{i}\n# CARD\nvoice：" + "甲" * (each + (i <= remainder)) + "\n" for i in range(1, 6))
            return head + phases + "# END\n"
        self.assertTrue(validate_script(script(2003))[0])
        self.assertFalse(validate_script(script(3800))[0])
        self.assertFalse(validate_script(script(4500))[0])

    def test_visual_placeholder_and_deindexed_duplicate_fail(self):
        data = sample_storyboard()
        data["blocks"][0]["beats"][0]["visual_description"] = "标题专属构图0价格牌人物动作"
        errors = validate_storyboard(data, [{"type": "TITLE", "head": "TITLE", "voice": "abc"}, {"type": "END", "head": "END", "voice": ""}], enforce_density=False)
        self.assertTrue(any("占位" in x for x in errors))

    def test_visual_short_description_rejected_with_script_blocks(self):
        data = sample_storyboard()
        blocks = [{"type": "TITLE", "head": "TITLE", "voice": "abc"}, {"type": "END", "head": "END", "voice": ""}]
        self.assertTrue(any("过短" in x for x in validate_storyboard(data, blocks, enforce_density=False)))


class StoryboardReviewWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_projects = PJ.PROJECTS_DIR
        PJ.PROJECTS_DIR = os.path.join(self.tmp.name, "projects")
        PJ._CACHE.clear()

    def tearDown(self):
        PJ.PROJECTS_DIR = self.old_projects; PJ._CACHE.clear(); self.tmp.cleanup()

    def _fixture(self):
        with redirect_stdout(io.StringIO()):
            workflow.cmd_create(SimpleNamespace(project="900", llm="codex", llm_model=None, image="imagegen", image_model=None, azure_voice="v"))
            workflow.cmd_init(SimpleNamespace(project="900", run_id="run_review"))
        project = workflow.project_for_id("900"); paths = workflow.state_paths(project, "run_review")
        os.makedirs(os.path.dirname(workflow.formal_paths(project)["script"]), exist_ok=True)
        script = "# TITLE\nvoice：标题\n" + "".join(f"# PHASE {i:02d} · 阶段{i}\n# CARD\nvoice：" + "甲" * 760 + "\n" for i in range(1, 6)) + "# END\n"
        with open(workflow.formal_paths(project)["script"], "w", encoding="utf-8") as h: h.write(script)
        story = {"blocks": [{"block_idx": 0, "type": "TITLE", "head": "TITLE", "subtitles": [{"id": 0, "text": "完全无关字幕", "start_char": 0, "end_char": 6}], "beats": [{"beat_idx": 0, "sentence_ids": [0], "visual_description": "海边人物站立，手持书本凝视远方", "character_ids": []}]}]}
        write_json(paths["storyboard"], story)
        state = read_json(paths["state"]); state["stages"]["storyboard"]["status"] = "promoted"; save = workflow.save_state; save(paths, state)
        return project, paths

    def test_review_uses_covered_subtitles_and_fails_unrelated_beat(self):
        project, paths = self._fixture(); report = workflow._storyboard_review(paths, project)
        self.assertEqual(report["verdict"], "fail"); self.assertTrue(any("语义关联" in x for x in report["beats"][0]["issues"]))

    def test_review_hash_change_rejects_verify_and_promote(self):
        project, paths = self._fixture(); report = workflow._storyboard_review(paths, project)
        report["verdict"] = "pass"; report["beats"][0]["verdict"] = "pass"; write_json(paths["storyboard-review"], report)
        with open(paths["storyboard"], "a", encoding="utf-8") as h: h.write(" ")
        state = read_json(paths["state"]); state["stages"]["storyboard-review"]["status"] = "generated"; workflow.save_state(paths, state)
        with self.assertRaises(RuntimeError): workflow.cmd_verify(SimpleNamespace(run_id="run_review", project="900", stage="storyboard-review"))
        with self.assertRaises(RuntimeError): workflow.cmd_promote(SimpleNamespace(run_id="run_review", project="900", stage="storyboard-review", replace=False))

    def test_images_blocked_until_review_promoted(self):
        project, paths = self._fixture(); state = read_json(paths["state"]); state["stages"]["storyboard-review"]["status"] = "generated"; workflow.save_state(paths, state)
        with self.assertRaises(RuntimeError): workflow.cmd_run(SimpleNamespace(run_id="run_review", project="900", stage="images", beats=None, review_id=None, revision=None, blocks=None, clip_durations=None, phase_images_dir=None))


if __name__ == "__main__":
    unittest.main()
