"""两种项目生图模式的配置隔离和真实请求构造回归（不访问网络）。"""

import base64
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import proj as PJ
import workflow
from providers.image import WanxiangProvider
from workflow_contracts import read_json, write_json


def png_bytes(size=(640, 360), color="red"):
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    return output.getvalue()


class ProjectImageModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.patch = mock.patch.object(PJ, "PROJECTS_DIR", self.tmp.name)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.old_id = PJ.CURRENT_ID
        self.addCleanup(setattr, PJ, "CURRENT_ID", self.old_id)
        PJ._CACHE.clear()
        self.addCleanup(PJ._CACHE.clear)

    def command(self, *argv):
        args = workflow.parser().parse_args(argv)
        with redirect_stdout(io.StringIO()):
            args.func(args)

    def test_new_projects_choose_independently_and_snapshot_mode(self):
        for pid, mode in (("801", "imagegen"), ("802", "wanxiang")):
            self.command("create", "--project", pid, "--image", mode)
            self.command("init", "--project", pid, "--run-id", "run_a")
            project = workflow.project_for_id(pid)
            meta = workflow.project_meta(project)
            state = read_json(workflow.state_paths(project, "run_a")["state"])
            self.assertEqual(meta["providers"]["image"]["name"], mode)
            self.assertEqual(state["providers"], meta["providers"])

    def test_repeated_create_preserves_all_settings_and_existing_run(self):
        self.command("create", "--project", "803", "--image", "wanxiang",
                     "--image-model", "wan2.7-image", "--llm", "deepseek",
                     "--llm-model", "deepseek-chat", "--azure-voice", "voice-B",
                     "--content-template", "story_journey_v1")
        self.command("init", "--project", "803", "--run-id", "run_a")
        project = Path(workflow.project_for_id("803"))
        before = (project / "project.json").read_bytes()
        self.command("create", "--project", "803")
        self.command("create", "--project", "803", "--image", "wanxiang")
        self.assertEqual((project / "project.json").read_bytes(), before)

    def test_mode_cannot_change_before_or_after_completed_run(self):
        self.command("create", "--project", "804", "--image", "imagegen")
        project = workflow.project_for_id("804")
        before = workflow.project_meta(project)
        for completed in (False, True):
            if completed:
                self.command("init", "--project", "804", "--run-id", "run_a")
                paths = workflow.state_paths(project, "run_a")
                state = read_json(paths["state"])
                state["stages"]["qa"]["status"] = "promoted"
                write_json(paths["state"], state)
            with self.assertRaisesRegex(RuntimeError, "provider 已固定"):
                self.command("create", "--project", "804", "--image", "wanxiang")
            self.assertEqual(workflow.project_meta(project), before)
        state["superseded_by"] = "run_later"
        state["stages"]["qa"]["status"] = "blocked"
        write_json(paths["state"], state)
        self.command("create", "--project", "804")
        with self.assertRaisesRegex(RuntimeError, "provider 已固定"):
            self.command("create", "--project", "804", "--image-model", "other-model")

    def test_init_rejects_metadata_drift_without_creating_run(self):
        self.command("create", "--project", "805", "--image", "imagegen")
        self.command("init", "--project", "805", "--run-id", "run_a")
        project = workflow.project_for_id("805")
        meta = workflow.project_meta(project)
        meta["providers"]["image"]["name"] = "wanxiang"
        write_json(os.path.join(project, "project.json"), meta)
        with self.assertRaisesRegex(RuntimeError, "历史 run 快照不一致"):
            self.command("init", "--project", "805", "--run-id", "run_b")
        self.assertFalse(os.path.exists(workflow.state_paths(project, "run_b")["state"]))

    def test_both_modes_share_bootstrap_verification_and_review(self):
        # 只模拟外部出图，实际执行两种 provider 的路由、锚点和审核状态机。
        for pid, mode in (("806", "imagegen"), ("807", "wanxiang")):
            with self.subTest(mode=mode):
                self.command("create", "--project", pid, "--image", mode)
                self.command("init", "--project", pid, "--run-id", "run_images")
                project = workflow.project_for_id(pid)
                paths = workflow.state_paths(project, "run_images")
                story = {"version": 1, "blocks": [{"block_idx": 0, "type": "CARD",
                         "beats": [{"beat_idx": i, "visual_description": "test scene",
                                    "character_ids": [], "shot": "wide",
                                    "emotion": "neutral", "segment": "hook"}
                                   for i in range(2)]}]}
                formal = workflow.formal_paths(project)["storyboard"]
                write_json(formal, story)
                write_json(paths["storyboard-review"], {
                    "verdict": "pass", "source_sha256": workflow._sha256(formal)})
                state = read_json(paths["state"])
                for stage in ("storyboard", "storyboard-review"):
                    state["stages"][stage]["status"] = "promoted"
                workflow.unlock(state)
                workflow.save_state(paths, state)
                requests = []

                def api_reply(request, **kwargs):
                    self.assertEqual(mode, "wanxiang")
                    if isinstance(request, str):
                        return io.BytesIO(png_bytes(color="red" if request.endswith("1") else "blue"))
                    requests.append(json.loads(request.data))
                    result = {"output": {"choices": [{"message": {"content": [
                        {"image": f"https://example.test/{len(requests)}"}]}}]}}
                    return io.BytesIO(json.dumps(result).encode())

                with mock.patch.object(WanxiangProvider, "_config",
                                       return_value=("k", "https://example.test", "wan2.7-image")), \
                        mock.patch("providers.image.urllib.request.urlopen", side_effect=api_reply):
                    self.command("run", "run_images", "images", "--project", pid)
                    packet = read_json(paths["image_tasks"])
                    self.assertEqual(packet["mode"], "bootstrap")
                    self.assertEqual(len(packet["tasks"]), 1)
                    first = packet["tasks"][0]
                    self.assertEqual(first["reference_images"], [])
                    if mode == "imagegen":
                        Path(first["output_path"]).parent.mkdir(parents=True, exist_ok=True)
                        Path(first["output_path"]).write_bytes(png_bytes())
                    self.command("select-image-anchor", "run_images", first["key"], "--project", pid)
                    for _ in range(4):
                        self.command("run", "run_images", "images", "--project", pid)
                        state = read_json(paths["state"])
                        if state["stages"]["images"]["status"] == "generated":
                            break
                        self.assertEqual(mode, "imagegen")
                        active = state["image_generation"]["active_key"]
                        Path(paths["images"], active + ".png").write_bytes(png_bytes(color="blue"))
                    self.assertEqual(state["stages"]["images"]["status"], "generated")
                    self.command("verify", "run_images", "images", "--project", pid)
                    self.command("run", "run_images", "image-review", "--project", pid)
                report = read_json(paths["image-review"])
                self.assertEqual(report["verdict"], "pending_visual_review")
                self.assertEqual(report["issues"], [])
                self.assertFalse(Path(project, "assets/scenes/00_0.png").exists())
                if mode == "wanxiang":
                    self.assertEqual(len(requests), 2)
                    self.assertIn("image", requests[1]["input"]["messages"][0]["content"][0])


class WanxiangCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name) / "candidate.png"
        self.task = {"key": "00_0", "prompt": "原始画面描述",
                     "negative_prompt": "原始负向约束", "size": [1920, 1080],
                     "reference_images": [], "output_path": str(self.output)}
        self.provider = WanxiangProvider({}, self.tmp.name)

    def generate(self, image=None):
        response = {"output": {"choices": [{"message": {"content": [
            {"text": "result"}, {"image": "https://example.test/result.png"}]}}]}}
        responses = [io.BytesIO(json.dumps(response).encode()),
                     io.BytesIO(image if image is not None else png_bytes())]
        with mock.patch("providers.image.urllib.request.urlopen", side_effect=responses) as opened:
            self.provider._generate_one(self.task, "test-key", "https://example.test/api/v1",
                                        "wan2.7-image")
        return json.loads(opened.call_args_list[0].args[0].data)

    def test_text_only_bootstrap_preserves_contract(self):
        body = self.generate()
        self.assertEqual(body["input"]["messages"][0]["content"],
                         [{"text": self.task["prompt"]}])
        self.assertEqual(body["parameters"]["negative_prompt"], self.task["negative_prompt"])
        self.assertTrue(body["parameters"]["thinking_mode"])
        self.assertEqual(body["parameters"]["size"], "1920*1080")
        self.assertEqual(self.output.read_bytes(), png_bytes())

    def test_anchor_is_transmitted_without_changing_prompt(self):
        reference = Path(self.tmp.name) / "anchor.png"
        data = png_bytes()
        reference.write_bytes(data)
        self.task["reference_images"] = [str(reference)]
        self.task["style_anchor"] = {"path": str(reference),
                                     "sha256": hashlib.sha256(data).hexdigest()}
        body = self.generate()
        items = body["input"]["messages"][0]["content"]
        self.assertEqual(base64.b64decode(items[0]["image"].split(",", 1)[1]), data)
        self.assertEqual(items[1], {"text": self.task["prompt"]})
        self.assertNotIn("thinking_mode", body["parameters"])

    def test_rgba_anchor_is_flattened_in_memory_without_changing_source(self):
        reference = Path(self.tmp.name) / "anchor_rgba.png"
        buffer = io.BytesIO()
        Image.new("RGBA", (640, 360), (20, 40, 60, 252)).save(
            buffer, format="PNG")
        original = buffer.getvalue()
        reference.write_bytes(original)
        self.task["reference_images"] = [str(reference)]
        self.task["style_anchor"] = {
            "path": str(reference),
            "sha256": hashlib.sha256(original).hexdigest(),
        }
        body = self.generate()
        uploaded = base64.b64decode(
            body["input"]["messages"][0]["content"][0]["image"].split(",", 1)[1])
        with Image.open(io.BytesIO(uploaded)) as image:
            self.assertEqual(image.mode, "RGB")
            self.assertEqual(image.size, (640, 360))
        self.assertEqual(reference.read_bytes(), original)

    def test_changed_anchor_fails_before_network_request(self):
        reference = Path(self.tmp.name) / "anchor.png"
        reference.write_bytes(png_bytes())
        self.task["reference_images"] = [str(reference)]
        self.task["style_anchor"] = {"path": str(reference), "sha256": "stale"}
        with mock.patch("providers.image.urllib.request.urlopen") as opened:
            with self.assertRaisesRegex(ValueError, "锚点哈希"):
                self.provider._generate_one(self.task, "k", "https://example.test", "m")
            opened.assert_not_called()

    def test_missing_reference_does_not_fall_back_to_text_only(self):
        self.task["reference_images"] = [str(Path(self.tmp.name) / "missing.png")]
        with mock.patch("providers.image.urllib.request.urlopen") as opened:
            with self.assertRaises(FileNotFoundError):
                self.provider._generate_one(self.task, "k", "https://example.test", "m")
            opened.assert_not_called()

    def test_corrupt_candidate_is_retried_but_valid_candidate_is_skipped(self):
        self.output.write_bytes(png_bytes()[:50])
        self.assertIsNotNone(workflow._image_file_problem(self.task))
        with mock.patch.object(self.provider, "_config", return_value=("k", "u", "m")), \
                mock.patch.object(self.provider, "_generate_one") as generate:
            self.provider.generate([self.task])
            generate.assert_called_once()
            generate.reset_mock()
            self.output.write_bytes(png_bytes())
            result = self.provider.generate([self.task])
            self.assertEqual(result["skipped"], ["00_0"])
            generate.assert_not_called()

    def test_bad_download_does_not_overwrite_candidate(self):
        for data in (b"\x89PNGbroken", png_bytes(size=(360, 360))):
            with self.subTest(data_length=len(data)):
                original = png_bytes(color="blue")
                self.output.write_bytes(original)
                with self.assertRaises((OSError, ValueError)):
                    self.generate(data)
                self.assertEqual(self.output.read_bytes(), original)
                self.assertEqual(list(Path(self.tmp.name).glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
