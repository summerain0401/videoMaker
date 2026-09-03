#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for isolated brand and publishing contracts."""
import os
import tempfile
import unittest
from types import SimpleNamespace

from PIL import Image

import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "pipeline"))

import workflow
from publishing_contracts import (PLATFORMS, scan_compliance, source_hashes,
                                   validate_brand, validate_package)


class PublishingContractTests(unittest.TestCase):
    def test_brand_paths_and_default_brief_are_channel_level(self):
        paths = workflow._brand_paths("/tmp/project", "main", "brand_test")
        self.assertIn(os.path.join("channels", "main"), paths["candidate"])
        for phrase in ("中文普通人", "理解财富机制", "消费、职业与商业判断", "YouTube、B站、抖音、视频号", "抽象符号头像", "稳赚", "无风险收益"):
            self.assertIn(phrase, workflow.DEFAULT_BRAND_REQUEST)

    def test_brand_init_uses_documented_run_id_option(self):
        args = workflow.parser().parse_args([
            "brand-init", "--project", "001", "--channel", "main",
            "--run-id", "brand_20260825_main"])
        self.assertEqual(args.run_id, "brand_20260825_main")

    def test_cover_composer_accepts_reference_information_layers(self):
        args = workflow.parser().parse_args([
            "publish-compose-cover", "run", "pub", "--project", "001",
            "--cover-id", "cover_0", "--variant", "layout_v2"])
        self.assertFalse(hasattr(args, "title"))
        self.assertFalse(hasattr(args, "subtitle"))
        self.assertFalse(hasattr(args, "bookline"))
        self.assertEqual(args.variant, "layout_v2")

    def brand(self):
        svg = '<svg viewBox="0 0 1024 1024"><circle cx="512" cy="512" r="400"/></svg>'
        return {
            "version": 1,
            "candidates": [{"id": f"name_{i}", "name": f"频道{i}", "benefit_hook": "看懂机制", "rationale": "清晰"
                            }
                           for i in range(5)],
            "visual_directions": [{"id": f"visual_{i}", "label": "抽象符号", "concept": "机制", "symbol": "圆环", "palette": {"background": "#000", "foreground": "#fff", "accent": "#f00"}, "avatar_svg": svg}
                                   for i in range(3)],
            "profiles": {p: {"description_template": "{{channel_name}} 理解财富机制"} for p in PLATFORMS},
            "tone": ["清晰"], "cta": "欢迎讨论。",
            "selected_name_id": "name_0", "selected_visual_id": "visual_0",
        }

    def package(self, hashes):
        item = {"primary_title": "理解价格背后的机制", "alternate_titles": ["价格为何这样定", "看懂价格信号"],
                "description": "理解财富机制。", "tags": ["财富", "价格", "认知"], "cta": "欢迎讨论。"}
        return {"version": 1, "publish_id": "pub", "channel_id": "main", "source": {"project_id": "001", "video_run_id": "run", "revision": "v2", "video_artifact": "long.mp4", "hashes": hashes}, "fact_core": {"summary": "价格是认知的结果。", "claim_refs": [0], "script_evidence": ["价格是认知的结果。"]},
                "cover": {"aspect_ratio": "16:9", "copy_lines": ["看懂价格"], "concept": "价格与认知",
                          "subject": "人物", "composition": "左右对比", "contrast": "标价与感知",
                          "brand_anchor": "圆形符号", "safe_zone": "中央", "forbidden_elements": ["收益承诺"],
                          "style_references": [{"path": "assets/scenes/00_0.png", "sha256": "scene-hash"}],
                          "style_requirements": "与正式成片视觉风格、角色、线条、色彩和光影一致。"},
                "platforms": {p: dict(item) for p in PLATFORMS}}

    def youtube_v2_package(self, hashes, root):
        covers = os.path.join(root, "publishing", "candidates", "run_v2", "covers")
        os.makedirs(covers, exist_ok=True)
        candidates = []
        for index in range(2):
            final = os.path.join(covers, f"cover_{index}.png")
            Image.new("RGB", (1920, 1080), (20 + index, 40, 80)).save(final)
            candidates.append({"id": f"cover_{index}",
                               "base_path": f"publishing/candidates/run_v2/covers/cover_{index}_base.png",
                               "base_sha256": "base",
                               "final_path": os.path.relpath(final, root),
                               "sha256": workflow._sha256(final),
                               "concept": "左侧钩子、右侧主题主体的高对比封面"})
        strategies = ("pain_point", "counter_intuitive", "number_solution", "seo", "emotional_story")
        titles = [{"id": f"title_{i}", "strategy": strategy,
                   "title": "决策方法" + "测" * 54}
                  for i, strategy in enumerate(strategies)]
        return {"version": 2, "publish_id": "pub", "channel_id": "main",
                "source": {"project_id": "001", "video_run_id": "run", "revision": "v2",
                           "video_artifact": "long.mp4", "hashes": hashes},
                "fact_core": {"summary": "价格是认知的结果。", "claim_refs": [0],
                              "script_evidence": ["价格是认知的结果。"]},
                "cover": {"aspect_ratio": "16:9", "copy_lines": ["看懂价格"],
                          "concept": "价格与认知", "subject": "人物", "composition": "左右对比",
                          "contrast": "标价与感知", "brand_anchor": "编辑插画", "safe_zone": "左侧",
                          "forbidden_elements": ["收益承诺"],
                          "style_references": [{"path": "assets/scenes/00_0.png", "sha256": "scene-hash"}],
                          "style_requirements": "高对比的信息层级，视觉服务当前内容。",
                          "candidates": candidates, "selected_cover_id": "cover_0"},
                "platforms": {"youtube": {"keywords": ["决策方法"], "titles": titles,
                    "selected_title_id": "title_0", "description": {
                        "lead": "用决策方法处理信息不足时最难下的选择。",
                        "highlights": ["🧭 看点一", "📌 看点二", "💡 看点三"],
                        "timestamps": [{"time": "00:00", "title": "开场"}, {"time": "01:00", "title": "问题"},
                                       {"time": "02:00", "title": "方法"}, {"time": "03:00", "title": "行动"}],
                        "cta": "欢迎留言讨论。", "resources": "[工具链接]", "hashtags": ["#决策", "#认知", "#选择"]}}}}

    def test_brand_requires_exact_counts_and_selection(self):
        data = self.brand()
        self.assertEqual(validate_brand(data), [])
        data["candidates"].pop()
        self.assertTrue(validate_brand(data))

    def test_svg_and_provider_neutral_template_constraints_are_scannable(self):
        self.assertEqual(scan_compliance("理解财富机制"), [])
        self.assertTrue(scan_compliance("保证收益 20%"))
        self.assertIn("{{channel_name}}", self.brand()["profiles"]["youtube"]["description_template"])

    def test_svg_security_allows_standard_xmlns_only(self):
        valid = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024"><circle/></svg>'
        self.assertEqual(workflow.validate_svg_text(valid), [])
        for bad in ('<svg viewBox="0 0 1024 1024"><a href="https://evil.test"/></svg>',
                    '<svg viewBox="0 0 1024 1024" onload="bad()"><circle/></svg>'):
            self.assertTrue(workflow.validate_svg_text(bad))

    def test_package_platforms_cover_alternates_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = {}
            for name, content in (("topic", "{}"), ("copy", "{}"), ("script", "价格是认知的结果。"), ("storyboard", "{}")):
                path = os.path.join(tmp, name + (".txt" if name == "script" else ".json"))
                with open(path, "w", encoding="utf-8") as f: f.write(content)
                paths[name] = path
            hashes = source_hashes(paths)
            self.assertEqual(validate_package(self.package(hashes), hashes, "价格是认知的结果。", {"claims": ["claim"]}), [])
            bad = self.package(hashes)
            bad["platforms"]["youtube"]["alternate_titles"] = []
            self.assertTrue(validate_package(bad, hashes, "价格是认知的结果。", {"claims": ["claim"]}))
            stale = dict(hashes); stale["script"] = "stale"
            self.assertTrue(validate_package(self.package(stale), hashes, "价格是认知的结果。", {"claims": ["claim"]}))

    def test_youtube_v2_contract_requires_selected_candidates_and_complete_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            scenes = os.path.join(tmp, "assets", "scenes"); os.makedirs(scenes)
            scene = os.path.join(scenes, "00_0.png")
            Image.new("RGB", (16, 9), "black").save(scene)
            paths = {}
            for name, content in (("topic", "{}"), ("copy", "{}"), ("script", "价格是认知的结果。"), ("storyboard", "{}")):
                path = os.path.join(tmp, name + (".txt" if name == "script" else ".json"))
                with open(path, "w", encoding="utf-8") as handle: handle.write(content)
                paths[name] = path
            package = self.youtube_v2_package(source_hashes(paths), tmp)
            package["cover"]["style_references"][0]["sha256"] = workflow._sha256(scene)
            self.assertEqual(validate_package(package, source_hashes(paths), "价格是认知的结果。",
                                              {"claims": ["claim"]}, project_root=tmp), [])
            package["platforms"]["youtube"]["selected_title_id"] = None
            self.assertIn("必须先选择标题候选", validate_package(
                package, source_hashes(paths), "价格是认知的结果。", {"claims": ["claim"]}, project_root=tmp))

    def test_cover_style_reference_selection_is_numeric_and_strict(self):
        with tempfile.TemporaryDirectory() as tmp:
            scenes = os.path.join(tmp, "assets", "scenes"); os.makedirs(os.path.join(scenes, "candidates"))
            for name in ("00_10.png", "00_2.png", "01_0.png", "phase_01.png", "block_01.png", "candidates/02_0.png"):
                with open(os.path.join(scenes, name), "wb") as handle: handle.write(name.encode())
            refs = workflow._cover_style_references(tmp)
            self.assertEqual([x["path"] for x in refs], ["assets/scenes/00_2.png", "assets/scenes/00_10.png", "assets/scenes/01_0.png"])

    def test_cover_style_reference_validation_rejects_empty_external_stale_and_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            scenes = os.path.join(tmp, "assets", "scenes"); os.makedirs(scenes)
            scene = os.path.join(scenes, "00_0.png")
            with open(scene, "wb") as handle: handle.write(b"scene")
            ref = {"path": "assets/scenes/00_0.png", "sha256": workflow._sha256(scene), "purpose": "style"}
            base = self.package({"topic": "a", "copy": "b", "script": "c", "storyboard": "d"})
            base["cover"]["style_references"] = [ref]
            self.assertFalse([e for e in validate_package(base, cover_style_references=[ref], project_root=tmp) if "style_reference" in e])
            for bad in ([], [{"path": "assets/scenes/candidates/x.png", "sha256": ref["sha256"]}], [{"path": "/tmp/out.png", "sha256": ref["sha256"]}], [{"path": ref["path"], "sha256": "stale"}]):
                candidate = self.package({"topic": "a", "copy": "b", "script": "c", "storyboard": "d"}); candidate["cover"]["style_references"] = bad
                self.assertTrue(validate_package(candidate, cover_style_references=[ref], project_root=tmp))
            candidate = self.package({"topic": "a", "copy": "b", "script": "c", "storyboard": "d"})
            candidate["cover"]["style_references"] = [ref]
            self.assertTrue(validate_package(candidate, cover_style_references=[] , project_root=tmp))

    def test_publish_run_blocks_without_regular_scenes(self):
        with tempfile.TemporaryDirectory() as tmp:
            workflow.ROOT = tmp; workflow.PJ.PROJECTS_DIR = os.path.join(tmp, "projects"); workflow.PJ._CACHE = {}
            project = workflow.PJ.project_dir("001", title="测试", author="")
            os.makedirs(os.path.join(project, "assets", "scenes"), exist_ok=True)
            with self.assertRaisesRegex(RuntimeError, "正式常规场景"):
                workflow._cover_style_references(project)

    def test_cli_lifecycle_isolated_and_preserves_video(self):
        old_root, old_projects, old_cache = workflow.ROOT, workflow.PJ.PROJECTS_DIR, workflow.PJ._CACHE
        with tempfile.TemporaryDirectory() as tmp:
            workflow.ROOT = tmp; workflow.PJ.PROJECTS_DIR = os.path.join(tmp, "projects"); workflow.PJ._CACHE = {}
            project = workflow.PJ.project_dir("001", title="测试", author="")
            formal = workflow._formal_source_paths(project)
            for name, content in (("topic", "{}"), ("copy", '{"claims":["claim"]}'), ("script", "证据原文。"), ("storyboard", "{}")):
                with open(formal[name], "w", encoding="utf-8") as f: f.write(content)
            video = os.path.join(project, "output", "long_001_v2.mp4")
            with open(video, "wb") as f: f.write(b"video-bytes")
            scenes = os.path.join(project, "assets", "scenes"); os.makedirs(scenes, exist_ok=True)
            with open(os.path.join(scenes, "00_0.png"), "wb") as f: f.write(b"scene")
            run_id = "run_video"; run_paths = workflow.state_paths(project, run_id)
            os.makedirs(os.path.dirname(run_paths["state"]), exist_ok=True)
            state = {"run_id": run_id, "project_id": "001", "providers": workflow.normalize_providers(), "updated_at": "", "stages": {"qa": {"status": "promoted"}, "render": {"status": "promoted", "revision": "v2", "artifact": video}}}
            workflow.write_json(run_paths["state"], state)
            bargs = SimpleNamespace(project="001", channel="main", run_id="brand_test")
            workflow.cmd_brand_init(bargs); workflow.cmd_brand_run(bargs)
            bp = workflow._brand_paths(project, "main", "brand_test")
            workflow.write_json(bp["candidate"], self.brand())
            workflow.cmd_brand_select(SimpleNamespace(project="001", channel="main", run_id="brand_test", name_id="name_0", visual_id="visual_0"))
            workflow.cmd_brand_verify(bargs); workflow.cmd_brand_promote(bargs)
            self.assertTrue(os.path.exists(bp["avatar"])); self.assertTrue(os.path.exists(bp["profile"])); self.assertEqual(workflow.read_json(bp["state"])["status"], "promoted")
            pargs = SimpleNamespace(project="001", channel="main", video_run_id=run_id, publish_id="pub_test", revision="v2")
            workflow.cmd_publish_init(pargs); pp = workflow._publish_paths(project, run_id, "v2", "pub_test")
            hashes = source_hashes({**formal, "brand": bp["brand"]}); package = self.package(hashes); package["publish_id"] = "pub_test"; package["channel_id"] = "main"; package["source"]["video_run_id"] = run_id; package["fact_core"]["script_evidence"] = ["证据原文。"]
            package["cover"]["style_references"][0]["sha256"] = workflow._sha256(os.path.join(scenes, "00_0.png"))
            workflow.write_json(pp["task"], {"cover_style_references": package["cover"]["style_references"]})
            workflow.write_json(pp["candidate"], package)
            workflow.cmd_publish_verify(SimpleNamespace(project="001", channel="main", video_run_id=run_id, publish_id="pub_test", revision="v2")); workflow.cmd_publish_promote(pargs)
            with open(video, "rb") as handle:
                self.assertEqual(handle.read(), b"video-bytes")
            with open(pp["upload"], encoding="utf-8") as handle:
                upload = handle.read()
            for heading in ("统一事实核心", "封面文案与视觉任务", "YouTube", "上传前人工检查"): self.assertIn(heading, upload)
        workflow.ROOT, workflow.PJ.PROJECTS_DIR, workflow.PJ._CACHE = old_root, old_projects, old_cache


if __name__ == "__main__":
    unittest.main()
