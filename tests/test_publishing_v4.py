#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V4 split publishing and reference cover regression tests."""

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
        Image.new("RGB", (1920, 1080), "#355B6D").save(
            os.path.join(scenes, "00_0.png"))
        workflow.write_json(
            os.path.join(workflow.ROOT, "assets", "characters.json"),
            {"young_pro": {"prompt": "chibi worker"}})

    def _select_and_verify_plan(self):
        self._write_style_references()
        workflow.cmd_publish_cover_select_template(SimpleNamespace(
            **vars(self.args), template_id="reference_006_v1",
            recommended="reference_006_v1", reason="沿用频道观点钩子结构"))
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

    def _finish_generated_bases(self):
        with mock.patch.dict(os.environ, {"CODEX_SESSION_ID": "unit-test"}):
            workflow.cmd_publish_cover_generate(self.args)
            tasks = workflow.read_json(self.paths["cover_image_tasks"])["tasks"]
            self.assertEqual(len(tasks), 2)
            for index, task in enumerate(tasks):
                self.assertEqual(len(task["reference_images"]), 1)
                self.assertEqual(task["character_ids"], ["young_pro"])
                Image.new("RGB", (1920, 1080),
                          (120 + index * 20, 140, 160)).save(task["output_path"])
                workflow.cmd_publish_cover_generate(self.args)

    def _write_verified_v3_cover(self):
        source_id = "pub_legacy_verified"
        old_root = os.path.join(self.project, "publishing", "candidates",
                                "run_video_v2")
        images = os.path.join(old_root, "covers")
        os.makedirs(images, exist_ok=True)
        candidates = []
        for index, cover_id in enumerate(("cover_priority", "cover_choice")):
            base = os.path.join(images, f"{cover_id}_v3_base.png")
            final = os.path.join(images, f"{cover_id}_v3.png")
            Image.new("RGB", (1920, 1080),
                      (80 + index * 30, 110, 140)).save(base)
            Image.new("RGB", (1920, 1080),
                      (120 + index * 30, 150, 170)).save(final)
            digest = workflow._sha256(final)
            candidates.append({
                "id": cover_id, "layout_id": "reference_006_v1",
                "text": {"title_lines": ["把时间留给", "重要的事"],
                         "subtitle": "旧版已审核文字", "book_title": "富人的逻辑",
                         "author": self.topic["author"]},
                "base_path": os.path.relpath(base, self.project),
                "base_sha256": workflow._sha256(base),
                "final_path": os.path.relpath(final, self.project),
                "sha256": digest,
                "visual_review": {
                    "status": "passed", "asset_sha256": digest,
                    **{key: True for key in cover_templates.get_cover_template(
                        "reference_006_v1")["review_dimensions"]}},
            })
        parent = workflow.read_json(self.paths["state"])
        package_path = os.path.join(old_root, "package.json")
        workflow.write_json(package_path, {
            "version": 3, "publish_id": source_id,
            "source": {"project_id": "001", "video_run_id": "run_video",
                       "revision": "v2",
                       "video_artifact": parent["video_artifact"],
                       "hashes": parent["source_hashes"]},
            "cover": {"selected_cover_id": "cover_priority",
                      "candidates": candidates},
        })
        source_state = os.path.join(
            self.project, "workflow", "runs", "run_video", "publish",
            source_id, "state.json")
        workflow.write_json(source_state, {
            "version": 3, "status": "verified",
            "verified_hash": workflow._sha256(package_path),
        })
        return source_id, candidates[0]["final_path"]

    def test_registry_has_only_reference_template(self):
        first = cover_templates.cover_template_snapshot("reference_006_v1")
        self.assertEqual(first,
                         cover_templates.cover_template_snapshot("reference_006_v1"))
        self.assertEqual([item["id"] for item in
                          cover_templates.cover_template_catalog()],
                         ["reference_006_v1"])
        self.assertEqual(first["spec"]["layout"], "hook_left_character_right")
        with self.assertRaisesRegex(ValueError, "未知封面模板"):
            cover_templates.cover_template_snapshot("book_title_author_v2")
        self.assertIn("publish-cover-select-template", workflow.parser().format_help())
        self.assertNotIn("cover-lab-freeze", workflow.parser().format_help())

    def test_template_selection_remains_explicit_and_locked(self):
        with self.assertRaisesRegex(RuntimeError, "人工选择"):
            workflow.cmd_publish_cover_plan(self.args)
        with self.assertRaisesRegex(RuntimeError, "未知封面模板"):
            workflow.cmd_publish_cover_select_template(SimpleNamespace(
                **vars(self.args), template_id="book_title_author_v2",
                recommended="reference_006_v1", reason="removed"))
        self._select_and_verify_plan()
        state = workflow.read_json(self.paths["cover_state"])
        self.assertEqual(state["template_selection"]["selected_template_id"],
                         "reference_006_v1")
        self.assertNotIn("frozen_design", state)
        with self.assertRaisesRegex(RuntimeError, "不可变更"):
            workflow.cmd_publish_cover_select_template(SimpleNamespace(
                **vars(self.args), template_id="reference_006_v1",
                recommended="reference_006_v1", reason="change"))

    def test_reference_plan_uses_scene_and_character(self):
        self._select_and_verify_plan()
        state = workflow.read_json(self.paths["cover_state"])
        _, source, _ = workflow._publish_sources(self.project, "main")
        tasks = workflow._cover_image_tasks(self.project, self.paths, state, source)
        self.assertEqual(len(tasks), 2)
        self.assertTrue(all(len(task["reference_images"]) == 1 for task in tasks))
        self.assertTrue(all(task["character_ids"] == ["young_pro"]
                            for task in tasks))
        self.assertTrue(all("left hook area" in task["prompt"] for task in tasks))

    def test_imagegen_requires_codex_session(self):
        self._select_and_verify_plan()
        with mock.patch.dict(os.environ, {"CODEX_SESSION_ID": ""}):
            with self.assertRaisesRegex(RuntimeError, "不是 Codex 会话"):
                workflow.cmd_publish_cover_generate(self.args)
        state = workflow.read_json(self.paths["cover_state"])
        self.assertEqual(state["status"], "plan_verified")
        self.assertIsNone(state["generation"])

    def test_reference_compositor_is_deterministic(self):
        font = workflow._cover_font_path()
        base = Image.new("RGB", (1920, 1080), "#8899AA")
        candidate = {"text": {"title_lines": ["看懂财富", "守住财富"],
                              "subtitle": "两套不同能力",
                              "book_title": "富人的逻辑", "author": "作者"}}
        first = os.path.join(self.temp.name, "cover_1.png")
        second = os.path.join(self.temp.name, "cover_2.png")
        workflow._compose_reference_cover(base, first, candidate, font)
        workflow._compose_reference_cover(base, second, candidate, font)
        self.assertEqual(workflow._sha256(first), workflow._sha256(second))
        with Image.open(first) as image:
            self.assertEqual(image.size, (1920, 1080))

    def test_reuse_verified_v3_cover_preserves_original_image(self):
        source_id, original = self._write_verified_v3_cover()
        workflow.cmd_publish_cover_reuse_verified(SimpleNamespace(
            **vars(self.args), source_publish_id=source_id,
            cover_id="cover_priority", filename="cover_priority_v3.png"))
        candidate = workflow.read_json(self.paths["cover_candidate"])
        self.assertEqual(candidate["reuse_provenance"]["kind"], "verified_v3")
        self.assertEqual(candidate["selected_cover_id"], "cover_priority")
        self.assertNotEqual(candidate["candidates"][0]["text"]["book_title"],
                            self.topic["book_title"])
        workflow.cmd_publish_cover_verify(self.args)
        workflow.cmd_publish_cover_promote(self.args)
        self.assertEqual(workflow._sha256(self.paths["approved_cover_image"]),
                         workflow._sha256(os.path.join(self.project, original)))
        self.assertEqual(workflow.read_json(self.paths["cover_state"])["status"],
                         "promoted")
        workflow.cmd_publish_copy_run(self.args)
        workflow.write_json(self.paths["copy_candidate"], self._copy_candidate())
        workflow.cmd_publish_copy_select(SimpleNamespace(
            **vars(self.args), title_id="title_0"))
        workflow.cmd_publish_copy_verify(self.args)
        workflow.cmd_publish_copy_promote(self.args)
        workflow.cmd_publish_finalize(self.args)
        release = workflow.read_json(self.paths["release"])
        self.assertEqual(release["cover"]["selected_cover_id"], "cover_priority")
        self.assertEqual(workflow._sha256(self.paths["release_cover_image"]),
                         workflow._sha256(os.path.join(self.project, original)))

    def test_reuse_rejects_changed_legacy_image(self):
        source_id, original = self._write_verified_v3_cover()
        workflow.cmd_publish_cover_reuse_verified(SimpleNamespace(
            **vars(self.args), source_publish_id=source_id,
            cover_id="cover_priority", filename="cover_priority_v3.png"))
        Image.new("RGB", (1920, 1080), "red").save(
            os.path.join(self.project, original))
        with self.assertRaisesRegex(RuntimeError, "hash 无效"):
            workflow.cmd_publish_cover_verify(self.args)

    def test_reuse_rechecks_legacy_image_at_promotion(self):
        source_id, original = self._write_verified_v3_cover()
        workflow.cmd_publish_cover_reuse_verified(SimpleNamespace(
            **vars(self.args), source_publish_id=source_id,
            cover_id="cover_priority", filename="cover_priority_v3.png"))
        workflow.cmd_publish_cover_verify(self.args)
        Image.new("RGB", (1920, 1080), "red").save(
            os.path.join(self.project, original))
        with self.assertRaisesRegex(RuntimeError, "hash 无效"):
            workflow.cmd_publish_cover_promote(self.args)
        self.assertFalse(os.path.exists(self.paths["approved_cover_image"]))

    def test_finalize_rejects_promoted_child_hash_drift(self):
        workflow.cmd_publish_cover_select_template(SimpleNamespace(
            **vars(self.args), template_id="reference_006_v1",
            recommended="reference_006_v1", reason="频道既有版式"))
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

    def test_reference_cover_and_split_finalize(self):
        workflow.cmd_publish_copy_run(self.args)
        workflow.write_json(self.paths["copy_candidate"], self._copy_candidate())
        workflow.cmd_publish_copy_select(SimpleNamespace(
            **vars(self.args), title_id="title_0"))
        workflow.cmd_publish_copy_verify(self.args)
        workflow.cmd_publish_copy_promote(self.args)
        draft = workflow.read_json(self.paths["release_draft"])
        self.assertEqual(draft["status"], "incomplete")
        self.assertEqual(list(draft["artifacts"]), ["copy"])
        self.assertTrue(os.path.isfile(self.paths["release_copy"]))
        self.assertFalse(os.path.exists(self.paths["release_cover"]))
        self.assertFalse(os.path.exists(self.paths["release"]))
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
            self.assertEqual(candidate["text"]["author"], self.topic["author"])
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
        draft = workflow.read_json(self.paths["release_draft"])
        self.assertEqual(draft["status"], "ready_to_finalize")
        self.assertEqual(set(draft["artifacts"]), {"copy", "cover"})
        workflow.cmd_publish_finalize(self.args)
        package = workflow.read_json(self.paths["release"])
        self.assertEqual(package["version"], 4)
        self.assertEqual(package["cover"]["template"]["id"],
                         "reference_006_v1")
        for artifact in (self.paths["release_copy"], self.paths["release_cover"],
                         self.paths["release_cover_image"], self.paths["upload"]):
            self.assertTrue(os.path.isfile(artifact))
        self.assertFalse(os.path.exists(self.paths["release_draft"]))

    def test_cover_can_enter_release_before_copy(self):
        source_id, _ = self._write_verified_v3_cover()
        workflow.cmd_publish_cover_reuse_verified(SimpleNamespace(
            **vars(self.args), source_publish_id=source_id,
            cover_id="cover_priority", filename="cover_priority_v3.png"))
        workflow.cmd_publish_cover_verify(self.args)
        workflow.cmd_publish_cover_promote(self.args)
        draft = workflow.read_json(self.paths["release_draft"])
        self.assertEqual(draft["status"], "incomplete")
        self.assertEqual(list(draft["artifacts"]), ["cover"])
        self.assertTrue(os.path.isfile(self.paths["release_cover_image"]))
        self.assertFalse(os.path.exists(self.paths["release_copy"]))
        workflow.cmd_publish_copy_run(self.args)
        workflow.write_json(self.paths["copy_candidate"], self._copy_candidate())
        workflow.cmd_publish_copy_select(SimpleNamespace(
            **vars(self.args), title_id="title_0"))
        workflow.cmd_publish_copy_verify(self.args)
        workflow.cmd_publish_copy_promote(self.args)
        # 兼容变更前已提升、但尚未把文件汇入 release 的 V4 任务。
        for key in ("release_copy", "release_cover", "release_cover_image",
                    "release_draft"):
            os.remove(self.paths[key])
        workflow.cmd_publish_finalize(self.args)
        self.assertTrue(os.path.isfile(self.paths["release"]))
        self.assertTrue(os.path.isfile(self.paths["release_cover_image"]))

    def test_finalize_rejects_changed_release_component(self):
        source_id, _ = self._write_verified_v3_cover()
        workflow.cmd_publish_cover_reuse_verified(SimpleNamespace(
            **vars(self.args), source_publish_id=source_id,
            cover_id="cover_priority", filename="cover_priority_v3.png"))
        workflow.cmd_publish_cover_verify(self.args)
        workflow.cmd_publish_cover_promote(self.args)
        workflow.cmd_publish_copy_run(self.args)
        workflow.write_json(self.paths["copy_candidate"], self._copy_candidate())
        workflow.cmd_publish_copy_select(SimpleNamespace(
            **vars(self.args), title_id="title_0"))
        workflow.cmd_publish_copy_verify(self.args)
        workflow.cmd_publish_copy_promote(self.args)
        Image.new("RGB", (1920, 1080), "red").save(
            self.paths["release_cover_image"])
        with self.assertRaisesRegex(RuntimeError, "发布包内封面 hash 已变化"):
            workflow.cmd_publish_finalize(self.args)

    def test_historical_cover_state_is_readable(self):
        state = workflow.read_json(self.paths["cover_state"])
        state["status"] = "template_selected"
        state["template_selection"] = {"selected_template_id":
                                       "book_title_author_v2"}
        state["template"] = {"id": "book_title_author_v2", "version": 2,
                             "sha256": "historical", "spec": {}}
        workflow.write_json(self.paths["cover_state"], state)
        with mock.patch("sys.stdout") as output:
            workflow.cmd_publish_status(self.args)
        self.assertTrue(output.write.called)
        with self.assertRaisesRegex(RuntimeError, "已停用"):
            workflow.cmd_publish_cover_plan(self.args)


if __name__ == "__main__":
    unittest.main()
