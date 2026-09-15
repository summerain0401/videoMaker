#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V4 split publishing workflow and cover-template regression tests."""

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from PIL import Image

import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                "pipeline"))

import cover_templates
import workflow


class PublishingV4Tests(unittest.TestCase):
    def setUp(self):
        self.old_root = workflow.ROOT
        self.old_projects = workflow.PJ.PROJECTS_DIR
        self.old_cache = workflow.PJ._CACHE
        self.temp = tempfile.TemporaryDirectory()
        workflow.ROOT = self.temp.name
        workflow.PJ.PROJECTS_DIR = os.path.join(self.temp.name, "projects")
        workflow.PJ._CACHE = {}
        self.project = workflow.PJ.project_dir("001", title="测试", author="")
        self.topic = {"id": "topic_1",
                      "book_title": "富人的逻辑如何创造财富如何保有财富",
                      "author": "雷纳·齐特尔曼", "angle": "两套财富能力"}
        formal = workflow._formal_source_paths(self.project)
        workflow.write_json(formal["topic"], self.topic)
        workflow.write_json(formal["copy"], {"claims": ["财富有两套能力"]})
        with open(formal["script"], "w", encoding="utf-8") as handle:
            handle.write("财富有两套能力。证据原文。")
        workflow.write_json(formal["storyboard"], {"version": 1, "blocks": []})
        video = os.path.join(self.project, "output", "long_001_v2.mp4")
        os.makedirs(os.path.dirname(video), exist_ok=True)
        with open(video, "wb") as handle:
            handle.write(b"video")
        run = "run_video"
        run_paths = workflow.state_paths(self.project, run)
        workflow.write_json(run_paths["state"], {
            "run_id": run, "project_id": "001",
            "providers": workflow.normalize_providers(), "updated_at": "",
            "stages": {"qa": {"status": "promoted"},
                       "render": {"status": "promoted", "revision": "v2",
                                  "artifact": video}}})
        brand_path = workflow._brand_paths(self.project, "main", "unused")["brand"]
        workflow.write_json(brand_path, {
            "channel_name": "认知生财", "cta": "关注频道",
            "visual": {"palette": {"background": "#172033",
                                    "foreground": "#EDF4FF",
                                    "accent": "#58C4D8"}}})
        self.args = SimpleNamespace(project="001", channel="main",
                                    video_run_id=run, publish_id="pub_v4",
                                    revision="v2")
        workflow.cmd_publish_init(self.args)
        self.paths = workflow._publish_paths(self.project, run, "v2", "pub_v4")

    def tearDown(self):
        workflow.ROOT = self.old_root
        workflow.PJ.PROJECTS_DIR = self.old_projects
        workflow.PJ._CACHE = self.old_cache
        self.temp.cleanup()

    def _copy_candidate(self):
        keyword = "财富逻辑"
        strategies = ("pain_point", "counter_intuitive", "number_solution",
                      "seo", "emotional_story")
        titles = []
        for index, strategy in enumerate(strategies):
            prefix = keyword + f"{index}"
            title = prefix + "看懂创造与保有财富背后的两套能力系统以及普通人的行动方法"
            title = (title + "深度解读与实用指南" * 5)[:55]
            titles.append({"id": f"title_{index}", "strategy": strategy,
                           "title": title})
        return {
            "version": 1, "publish_id": "pub_v4", "channel_id": "main",
            "source": {"project_id": "001", "video_run_id": "run_video",
                       "revision": "v2",
                       "video_artifact": workflow.read_json(
                           self.paths["state"])["video_artifact"],
                       "hashes": workflow.read_json(self.paths["state"])["source_hashes"]},
            "fact_core": {"summary": "财富有两套能力",
                          "claim_refs": [0],
                          "script_evidence": ["证据原文。"]},
            "platforms": {"youtube": {
                "keywords": [keyword], "titles": titles,
                "selected_title_id": None,
                "description": {"lead": "理解财富的两套能力。",
                                "highlights": ["创造", "保有", "行动"],
                                "timestamps": [
                                    {"time": "00:00", "title": "开场"},
                                    {"time": "01:00", "title": "创造"},
                                    {"time": "02:00", "title": "保有"},
                                    {"time": "03:00", "title": "行动"}],
                                "cta": "关注频道", "resources": "书目见置顶",
                                "hashtags": ["#财富", "#认知", "#读书"]}}}}

    def _write_style_references(self):
        scenes = os.path.join(self.project, "assets", "scenes")
        os.makedirs(scenes, exist_ok=True)
        for index, color in enumerate(("#B66A3C", "#D39A51", "#355B6D")):
            Image.new("RGB", (1920, 1080), color).save(
                os.path.join(scenes, f"00_{index}.png"))

    def _select_and_verify_plan(self):
        self._write_style_references()
        select = SimpleNamespace(**vars(self.args),
                                 template_id="book_title_author_v2",
                                 recommended="reference_006_v1",
                                 reason="用户选择与正片一致的叙事出版海报")
        workflow.cmd_publish_cover_select_template(select)
        workflow.cmd_publish_cover_plan(self.args)
        state = workflow.read_json(self.paths["state"])
        workflow.write_json(self.paths["cover_plan"], {
            "version": 1, "publish_id": "pub_v4",
            "source_hashes": state["source_hashes"],
            "template_id": "book_title_author_v2",
            "candidates": [
                {"id": "cover_a", "concept": "双轨财富系统",
                 "hook": "会赚钱却守不住",
                 "subtitle": "理解财富的两种能力",
                 "hook_type": "pain_point",
                 "visual_metaphor": "金币从破裂的保险箱中流失",
                 "environment": "暖光书房延伸至城市橱窗",
                 "character_ids": []},
                {"id": "cover_b", "concept": "创造与守护",
                 "hook": "财富靠两种能力",
                 "subtitle": "",
                 "hook_type": "counter_intuitive",
                 "visual_metaphor": "创造火花撞上环形护盾",
                 "environment": "夕阳桌面形成前中后三层空间",
                 "character_ids": []},
            ]})
        workflow.cmd_publish_cover_verify_plan(self.args)

    def _finish_generated_bases(self):
        workflow.cmd_publish_cover_generate(self.args)
        packet = workflow.read_json(self.paths["cover_image_tasks"])
        first, second = packet["tasks"]
        self.assertEqual(len(first["reference_images"]), 3)
        self.assertEqual(first["character_ids"], [])
        self.assertNotIn(", person", first["negative_prompt"])
        Image.new("RGB", (1920, 1080), "#C8C8C8").save(first["output_path"])
        workflow.cmd_publish_cover_generate(self.args)
        Image.new("RGB", (1920, 1080), "#D8D8D8").save(second["output_path"])
        workflow.cmd_publish_cover_generate(self.args)

    def test_registry_is_versioned_hashed_and_auto_enumerated(self):
        first = cover_templates.cover_template_snapshot("book_title_author_v2")
        second = cover_templates.cover_template_snapshot("book_title_author_v2")
        self.assertEqual(first, second)
        self.assertEqual(first["spec"]["version"], 2)
        self.assertEqual(first["spec"]["layout"],
                         "cinematic_stacked_hook_poster")
        self.assertTrue(first["spec"]["requires_style_anchor"])
        self.assertFalse(first["spec"]["requires_character_ids"])
        self.assertTrue(first["spec"]["allows_people"])
        self.assertFalse(first["spec"]["shows_author"])
        with self.assertRaisesRegex(ValueError, "未知封面模板"):
            cover_templates.cover_template_snapshot("retired_template_v1")
        original = dict(cover_templates._TEMPLATES)
        try:
            cover_templates._TEMPLATES["future_v1"] = dict(
                first["spec"], id="future_v1", display_name="未来模板")
            self.assertIn("future_v1", {x["id"] for x in
                                        cover_templates.cover_template_catalog()})
        finally:
            cover_templates._TEMPLATES.clear()
            cover_templates._TEMPLATES.update(original)

    def test_template_must_be_selected_and_recommendation_may_differ(self):
        with self.assertRaisesRegex(RuntimeError, "人工选择"):
            workflow.cmd_publish_cover_plan(self.args)
        self._select_and_verify_plan()
        state = workflow.read_json(self.paths["cover_state"])
        selection = state["template_selection"]
        self.assertEqual(selection["recommended_template_id"],
                         "reference_006_v1")
        self.assertEqual(selection["selected_template_id"],
                         "book_title_author_v2")
        with self.assertRaisesRegex(RuntimeError, "不可变更"):
            workflow.cmd_publish_cover_select_template(SimpleNamespace(
                **vars(self.args), template_id="reference_006_v1",
                recommended="reference_006_v1", reason="change"))

    def test_reference_template_keeps_scene_anchor_and_character(self):
        scenes = os.path.join(self.project, "assets", "scenes")
        os.makedirs(scenes, exist_ok=True)
        Image.new("RGB", (1920, 1080), "navy").save(
            os.path.join(scenes, "00_0.png"))
        workflow.write_json(os.path.join(workflow.ROOT, "assets", "characters.json"),
                            {"young_pro": {"prompt": "chibi worker"}})
        selection = SimpleNamespace(
            **vars(self.args), template_id="reference_006_v1",
            recommended="reference_006_v1", reason="观点冲突更适合钩子")
        workflow.cmd_publish_cover_select_template(selection)
        workflow.cmd_publish_cover_plan(self.args)
        parent = workflow.read_json(self.paths["state"])
        workflow.write_json(self.paths["cover_plan"], {
            "version": 1, "publish_id": "pub_v4",
            "source_hashes": parent["source_hashes"],
            "template_id": "reference_006_v1",
            "candidates": [
                {"id": "cover_a", "concept": "财富双系统",
                 "subject": "焦虑的职场人", "composition": "左文右人",
                 "title_lines": ["会赚钱", "却守不住"], "subtitle": "两套能力",
                 "character_ids": ["young_pro"]},
                {"id": "cover_b", "concept": "创造与防守",
                 "subject": "思考的职场人", "composition": "左文右人",
                 "title_lines": ["创造财富", "保有财富"], "subtitle": "别用错方法",
                 "character_ids": ["young_pro"]}]})
        workflow.cmd_publish_cover_verify_plan(self.args)
        state = workflow.read_json(self.paths["cover_state"])
        _, source, _ = workflow._publish_sources(self.project, "main")
        tasks = workflow._cover_image_tasks(self.project, self.paths, state, source)
        self.assertTrue(all(task["reference_images"] for task in tasks))
        self.assertTrue(all(task["character_ids"] == ["young_pro"]
                            for task in tasks))

    def test_narrative_poster_uses_video_style_and_optional_character(self):
        self._write_style_references()
        workflow.write_json(os.path.join(workflow.ROOT, "assets", "characters.json"),
                            {"young_pro": {"prompt": "chibi worker",
                                           "anchor": "same round glasses"}})
        selection = SimpleNamespace(
            **vars(self.args), template_id="book_title_author_v2",
            recommended="book_title_author_v2",
            reason="正片是暖色手绘叙事风格，需要具象环境延续视觉语言")
        workflow.cmd_publish_cover_select_template(selection)
        workflow.cmd_publish_cover_plan(self.args)
        planning_task = workflow.read_json(self.paths["cover_task"])
        self.assertEqual(len(planning_task["source"]["style_references"]), 3)
        parent = workflow.read_json(self.paths["state"])
        workflow.write_json(self.paths["cover_plan"], {
            "version": 1, "publish_id": "pub_v4",
            "source_hashes": parent["source_hashes"],
            "template_id": "book_title_author_v2",
            "candidates": [
                {"id": "cover_a", "concept": "从众漩涡",
                 "hook": "越抢越亏？",
                 "subtitle": "失控消费心理学解析",
                 "hook_type": "pain_point",
                 "visual_metaphor": "巨大折扣漩涡吸走钱包",
                 "environment": "暖光书房桌面延伸到夜色商店橱窗",
                 "character_ids": ["young_pro"]},
                {"id": "cover_b", "concept": "稀缺牢笼",
                 "hook": "聪明人也会追高",
                 "subtitle": "理性如何失守",
                 "hook_type": "counter_intuitive",
                 "visual_metaphor": "倒计时钟面合拢成牢笼",
                 "environment": "夕阳城市橱窗形成前中后三层空间",
                 "character_ids": []},
            ]})
        workflow.cmd_publish_cover_verify_plan(self.args)
        state = workflow.read_json(self.paths["cover_state"])
        _, source, _ = workflow._publish_sources(self.project, "main")
        tasks = workflow._cover_image_tasks(self.project, self.paths,
                                            state, source)
        self.assertTrue(all(len(task["reference_images"]) == 3
                            for task in tasks))
        self.assertEqual(tasks[0]["character_ids"], ["young_pro"])
        self.assertEqual(tasks[1]["character_ids"], [])
        self.assertIn("same round glasses", tasks[0]["prompt"])
        self.assertTrue(all("polished colorful 2D chibi animation" in task["prompt"]
                            for task in tasks))
        self.assertTrue(all("duration badge" in task["prompt"] for task in tasks))
        self.assertTrue(all("complete scene" not in task["negative_prompt"]
                            for task in tasks))

    def test_imagegen_tasks_cannot_be_claimed_outside_codex(self):
        self._select_and_verify_plan()
        with mock.patch.dict(os.environ, {"CODEX_SESSION_ID": ""}):
            with self.assertRaisesRegex(RuntimeError, "不是 Codex 会话"):
                workflow.cmd_publish_cover_generate(self.args)
        state = workflow.read_json(self.paths["cover_state"])
        self.assertEqual(state["status"], "plan_verified")
        self.assertIsNone(state["generation"])

    def test_both_template_compositors_are_deterministic(self):
        font = workflow._cover_font_path()
        base = Image.new("RGB", (1920, 1080), "#8899AA")
        reference = {"text": {"title_lines": ["看懂财富", "守住财富"],
                              "subtitle": "两套不同能力",
                              "book_title": "富人的逻辑", "author": "作者"}}
        first = os.path.join(self.temp.name, "reference_1.png")
        second = os.path.join(self.temp.name, "reference_2.png")
        workflow._compose_reference_cover(base, first, reference, font)
        workflow._compose_reference_cover(base, second, reference, font)
        self.assertEqual(workflow._sha256(first), workflow._sha256(second))

        poster = {"text": {"book_title": self.topic["book_title"],
                           "hook": "会赚钱却守不住",
                           "hook_lines": ["会赚钱却守不住"]}}
        third = os.path.join(self.temp.name, "story_poster_1.png")
        fourth = os.path.join(self.temp.name, "story_poster_2.png")
        palette = {"background": "#172033", "foreground": "#EDF4FF",
                   "accent": "#58C4D8"}
        lines = workflow._compose_book_story_poster(
            base, third, poster, palette, font)
        workflow._compose_book_story_poster(
            base, fourth, poster, palette, font)
        self.assertEqual(workflow._sha256(third), workflow._sha256(fourth))
        self.assertEqual("".join(lines), poster["text"]["hook"])
        self.assertLessEqual(len(lines), 2)
        with Image.open(third) as image:
            self.assertEqual(image.size, (1920, 1080))
            thumbnail = image.resize((320, 180))
            self.assertGreater(len(thumbnail.getcolors(maxcolors=320 * 180)), 2)

    def test_poster_preserves_subject_area_and_fits_long_text(self):
        spec = cover_templates.get_cover_template("book_title_author_v2")
        typography = spec["typography"]
        base = Image.new("RGB", (1920, 1080), "#8899AA")
        draw = workflow.ImageDraw.Draw(base)
        font_path = workflow._cover_font_path()
        for hook in ("越抢越亏？", "聪明人为什么也总是掉进消费的陷阱"):
            box = typography["hook_box"]
            lines, font, bounds, height, gap = workflow._poster_text_layout(
                draw, hook, font_path, box, 196, 56,
                padding=(7, 9), stroke=6)
            self.assertEqual("".join(lines), hook)
            self.assertLessEqual(max(b[2] - b[0] for b in bounds) + 26,
                                 box[2] - box[0])
            self.assertLessEqual(height + 30, box[3] - box[1])
        destination = os.path.join(self.temp.name, "preserve_subject.png")
        workflow._compose_book_story_poster(
            base, destination, {"text": {"book_title": self.topic["book_title"],
                                        "hook": "越抢越亏？"}}, {}, font_path)
        with Image.open(destination) as rendered:
            self.assertEqual(rendered.crop((0, 530, 1920, 1080)).tobytes(),
                             base.crop((0, 530, 1920, 1080)).tobytes())

    def test_centered_subtitle_boundaries_and_plan_validation(self):
        self._select_and_verify_plan()
        plan = workflow.read_json(self.paths["cover_plan"])
        snapshot = cover_templates.cover_template_snapshot("book_title_author_v2")
        base = Image.new("RGB", (1920, 1080), "#8899AA")
        output_hashes = []
        for index, subtitle in enumerate(("", "解" * 14)):
            plan["candidates"][0]["subtitle"] = subtitle
            self.assertEqual(workflow.validate_cover_plan(
                plan, snapshot, self.topic, "pub_v4", plan["source_hashes"]), [])
            destination = os.path.join(self.temp.name, f"subtitle_{index}.png")
            workflow._compose_book_story_poster(
                base, destination, {"text": {"book_title": "影响力",
                                            "hook": "越抢越亏？",
                                            "subtitle": subtitle}}, {},
                workflow._cover_font_path())
            output_hashes.append(workflow._sha256(destination))
            with Image.open(destination) as rendered:
                self.assertEqual(rendered.crop((0, 530, 1920, 1080)).tobytes(),
                                 base.crop((0, 530, 1920, 1080)).tobytes())
        self.assertNotEqual(*output_hashes)
        for subtitle in ("解" * 15, "分析\n消费"):
            plan["candidates"][0]["subtitle"] = subtitle
            self.assertIn("封面解释副标题必须为0-14字单行文字",
                          workflow.validate_cover_plan(
                              plan, snapshot, self.topic, "pub_v4",
                              plan["source_hashes"]))

    def test_finalize_rejects_promoted_child_hash_drift(self):
        os.makedirs(self.paths["approved_root"], exist_ok=True)
        workflow.write_json(self.paths["approved_copy"], {"before": True})
        workflow.write_json(self.paths["approved_cover"], {"before": True})
        Image.new("RGB", (1920, 1080), "black").save(
            self.paths["approved_cover_image"])
        copy_state = workflow.read_json(self.paths["copy_state"])
        copy_state.update(status="promoted",
                          promoted_hash=workflow._sha256(self.paths["approved_copy"]))
        workflow.write_json(self.paths["copy_state"], copy_state)
        cover_state = workflow.read_json(self.paths["cover_state"])
        cover_state.update(
            status="promoted",
            promoted_hash=workflow._sha256(self.paths["approved_cover"]),
            promoted_image_hash=workflow._sha256(self.paths["approved_cover_image"]))
        workflow.write_json(self.paths["cover_state"], cover_state)
        workflow.write_json(self.paths["approved_copy"], {"after": True})
        with self.assertRaisesRegex(RuntimeError, "hash 已变化"):
            workflow.cmd_publish_finalize(self.args)

    def test_centered_poster_render_and_split_finalize(self):
        # 文案可以在封面尚未完成时独立提升。
        workflow.cmd_publish_copy_run(self.args)
        workflow.write_json(self.paths["copy_candidate"], self._copy_candidate())
        workflow.cmd_publish_copy_select(SimpleNamespace(
            **vars(self.args), title_id="title_0"))
        workflow.cmd_publish_copy_verify(self.args)
        workflow.cmd_publish_copy_promote(self.args)
        self.assertEqual(workflow.read_json(self.paths["copy_state"])["status"],
                         "promoted")
        with self.assertRaisesRegex(RuntimeError, "分别提升"):
            workflow.cmd_publish_finalize(self.args)

        self._select_and_verify_plan()
        self._finish_generated_bases()
        workflow.cmd_publish_cover_compose(self.args)
        cover = workflow.read_json(self.paths["cover_candidate"])
        self.assertEqual(len(cover["candidates"]), 2)
        for candidate in cover["candidates"]:
            self.assertEqual(candidate["text"]["book_title"],
                             self.topic["book_title"])
            self.assertEqual("".join(candidate["text"]["hook_lines"]),
                             candidate["hook"])
            self.assertNotIn("author", candidate["text"])
            with Image.open(os.path.join(self.project, candidate["final_path"])) as image:
                self.assertEqual(image.size, (1920, 1080))
        dimensions = cover["template"]["spec"]["review_dimensions"]
        workflow.cmd_publish_cover_review(SimpleNamespace(
            **vars(self.args), cover_id="cover_a", result="pass",
            failed_check=[]))
        workflow.cmd_publish_cover_review(SimpleNamespace(
            **vars(self.args), cover_id="cover_b", result="fail",
            failed_check=[dimensions[0]]))
        workflow.cmd_publish_cover_select(SimpleNamespace(
            **vars(self.args), cover_id="cover_a"))
        workflow.cmd_publish_cover_verify(self.args)
        workflow.cmd_publish_cover_promote(self.args)
        workflow.cmd_publish_finalize(self.args)
        package = workflow.read_json(self.paths["release"])
        self.assertEqual(package["version"], 4)
        self.assertEqual(package["cover"]["template"]["id"],
                         "book_title_author_v2")
        for path in (self.paths["release_copy"], self.paths["release_cover"],
                     self.paths["release_cover_image"], self.paths["upload"]):
            self.assertTrue(os.path.isfile(path))


if __name__ == "__main__":
    unittest.main()
