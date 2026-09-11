"""项目 provider 配置隔离与图片请求构造回归（不访问真实网络）。"""

import base64
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from contextlib import redirect_stdout
from unittest import mock

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import proj as PJ
import workflow
from providers.image import AntigravityImageProvider, WanxiangProvider
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
        index = 0
        for llm in ("codex", "deepseek", "antigravity"):
            for image in ("imagegen", "wanxiang", "antigravity"):
                with self.subTest(llm=llm, image=image):
                    pid = str(801 + index)
                    index += 1
                    self.command("create", "--project", pid,
                                 "--llm", llm, "--image", image)
                    self.command("init", "--project", pid,
                                 "--run-id", "run_a")
                    project = workflow.project_for_id(pid)
                    meta = workflow.project_meta(project)
                    state = read_json(
                        workflow.state_paths(project, "run_a")["state"])
                    self.assertEqual(meta["providers"]["llm"]["name"], llm)
                    self.assertEqual(meta["providers"]["image"]["name"], image)
                    self.assertEqual(state["providers"], meta["providers"])

    def test_new_project_requires_both_providers_before_creating_directory(self):
        for pid, args in (("820", ()),
                          ("821", ("--llm", "codex")),
                          ("822", ("--image", "imagegen"))):
            with self.subTest(args=args), self.assertRaisesRegex(
                    ValueError, "必须显式指定"):
                self.command("create", "--project", pid, *args)
            self.assertIsNone(PJ._find_dir(pid))

    def test_init_cannot_implicitly_create_project(self):
        with self.assertRaisesRegex(RuntimeError, "请先使用 create"):
            self.command("init", "--project", "823", "--run-id", "run_a")
        self.assertIsNone(PJ._find_dir("823"))

    def test_antigravity_rejects_model_overrides_before_creation(self):
        with self.assertRaisesRegex(ValueError, "禁止指定 --llm-model"):
            self.command("create", "--project", "824", "--llm",
                         "antigravity", "--llm-model", "gemini-any",
                         "--image", "imagegen")
        with self.assertRaisesRegex(ValueError, "禁止指定 --image-model"):
            self.command("create", "--project", "825", "--llm", "codex",
                         "--image", "antigravity", "--image-model", "nano")
        self.assertIsNone(PJ._find_dir("824"))
        self.assertIsNone(PJ._find_dir("825"))

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
        self.command("create", "--project", "804", "--llm", "codex",
                     "--image", "imagegen")
        project = workflow.project_for_id("804")
        before = workflow.project_meta(project)
        for completed in (False, True):
            if completed:
                self.command("init", "--project", "804", "--run-id", "run_a")
                paths = workflow.state_paths(project, "run_a")
                state = read_json(paths["state"])
                state["stages"]["qa"]["status"] = "promoted"
                write_json(paths["state"], state)
            with self.assertRaisesRegex(RuntimeError, "provider/model 已固定"):
                self.command("create", "--project", "804", "--image", "wanxiang")
            self.assertEqual(workflow.project_meta(project), before)
        state["superseded_by"] = "run_later"
        state["stages"]["qa"]["status"] = "blocked"
        write_json(paths["state"], state)
        self.command("create", "--project", "804")
        with self.assertRaisesRegex(RuntimeError, "provider/model 已固定"):
            self.command("create", "--project", "804", "--image-model", "other-model")
        with self.assertRaisesRegex(RuntimeError, "provider/model 已固定"):
            self.command("create", "--project", "804", "--llm", "deepseek")

    def test_init_rejects_metadata_drift_without_creating_run(self):
        self.command("create", "--project", "805", "--llm", "codex",
                     "--image", "imagegen")
        self.command("init", "--project", "805", "--run-id", "run_a")
        project = workflow.project_for_id("805")
        meta = workflow.project_meta(project)
        meta["providers"]["image"]["name"] = "wanxiang"
        write_json(os.path.join(project, "project.json"), meta)
        with self.assertRaisesRegex(RuntimeError, "历史 run 快照不一致"):
            self.command("init", "--project", "805", "--run-id", "run_b")
        self.assertFalse(os.path.exists(workflow.state_paths(project, "run_b")["state"]))

    def test_init_rejects_llm_metadata_drift(self):
        self.command("create", "--project", "826", "--llm", "codex",
                     "--image", "imagegen")
        self.command("init", "--project", "826", "--run-id", "run_a")
        project = workflow.project_for_id("826")
        meta = workflow.project_meta(project)
        meta["providers"]["llm"]["name"] = "deepseek"
        write_json(os.path.join(project, "project.json"), meta)
        with self.assertRaisesRegex(RuntimeError, "历史 run 快照不一致"):
            self.command("init", "--project", "826", "--run-id", "run_b")

    def test_all_image_modes_share_bootstrap_verification_and_review(self):
        # 只模拟外部出图，实际执行三种 provider 的路由、锚点和审核状态机。
        for pid, mode in (("830", "imagegen"), ("831", "wanxiang"),
                          ("832", "antigravity")):
            with self.subTest(mode=mode):
                self.command("create", "--project", pid, "--llm", "codex",
                             "--image", mode)
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
                    if mode in ("imagegen", "antigravity"):
                        self.assertEqual(
                            packet["execution_policy"]["provider"], mode)
                    first = packet["tasks"][0]
                    self.assertEqual(first["reference_images"], [])
                    if mode in ("imagegen", "antigravity"):
                        Path(first["output_path"]).parent.mkdir(parents=True, exist_ok=True)
                        Path(first["output_path"]).write_bytes(png_bytes())
                    self.command("select-image-anchor", "run_images", first["key"], "--project", pid)
                    for _ in range(4):
                        self.command("run", "run_images", "images", "--project", pid)
                        state = read_json(paths["state"])
                        if state["stages"]["images"]["status"] == "generated":
                            break
                        self.assertIn(mode, ("imagegen", "antigravity"))
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

    def test_antigravity_llm_writes_task_packet_and_waits_for_agent(self):
        self.command("create", "--project", "833", "--llm", "antigravity",
                     "--image", "imagegen")
        self.command("init", "--project", "833", "--run-id", "run_topic")
        self.command("run", "run_topic", "topic", "--project", "833")
        project = workflow.project_for_id("833")
        paths = workflow.state_paths(project, "run_topic")
        state = read_json(paths["state"])
        task = read_json(os.path.join(paths["tasks"], "topic.json"))
        self.assertEqual(state["stages"]["topic"]["status"],
                         "awaiting_external")
        self.assertIn("antigravity", state["stages"]["topic"]["note"])
        self.assertEqual(task["candidate_path"], paths["topic"])

    def test_antigravity_image_provider_is_interactive(self):
        tasks = [{"key": "00_0", "output_path": "/tmp/00_0.png"}]
        self.assertEqual(AntigravityImageProvider({}, ROOT).generate(tasks),
                         {"mode": "interactive", "tasks": tasks})


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

    def test_generate_uses_bounded_parallelism_and_keeps_task_order(self):
        tasks = []
        for index in range(8):
            task = dict(self.task)
            task["key"] = f"00_{index}"
            task["output_path"] = str(Path(self.tmp.name) / f"{index}.png")
            tasks.append(task)
        lock = threading.Lock()
        active = 0
        maximum = 0

        def generate_one(task, *_args):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.02)
            with lock:
                active -= 1

        with mock.patch.object(self.provider, "_config",
                               return_value=("k", "u", "m")), \
                mock.patch.object(self.provider, "_generate_one",
                                  side_effect=generate_one):
            result = self.provider.generate(tasks)
        self.assertGreater(maximum, 1)
        self.assertLessEqual(maximum, 5)
        self.assertEqual(result["made"], [task["key"] for task in tasks])

    def test_generate_aggregates_parallel_failures_in_task_order(self):
        tasks = []
        for index in range(3):
            task = dict(self.task)
            task["key"] = f"00_{index}"
            task["output_path"] = str(Path(self.tmp.name) / f"{index}.png")
            tasks.append(task)

        def generate_one(task, *_args):
            if task["key"] != "00_1":
                return
            raise RuntimeError("boom")

        with mock.patch.object(self.provider, "_config",
                               return_value=("k", "u", "m")), \
                mock.patch.object(self.provider, "_generate_one",
                                  side_effect=generate_one):
            with self.assertRaises(RuntimeError) as raised:
                self.provider.generate(tasks)
        result = json.loads(str(raised.exception))
        self.assertEqual(result["made"], ["00_0", "00_2"])
        self.assertEqual(result["failed"], [{"key": "00_1", "error": "boom"}])

    def test_transient_rate_limit_is_retried(self):
        limited = urllib.error.HTTPError(
            "https://example.test", 429, "rate limited",
            {"Retry-After": "0"}, io.BytesIO(b"try later"))
        with mock.patch("providers.image.urllib.request.urlopen",
                        side_effect=[limited, io.BytesIO(b"ok")]) as opened, \
                mock.patch("providers.image.time.sleep") as sleep:
            result = self.provider._read_with_retry("https://example.test")
        self.assertEqual(result, b"ok")
        self.assertEqual(opened.call_count, 2)
        sleep.assert_called_once_with(0.0)

    def test_connection_reset_is_retried(self):
        with mock.patch("providers.image.urllib.request.urlopen",
                        side_effect=[ConnectionResetError("reset"),
                                     io.BytesIO(b"ok")]) as opened, \
                mock.patch("providers.image.time.sleep") as sleep:
            result = self.provider._read_with_retry("https://example.test")
        self.assertEqual(result, b"ok")
        self.assertEqual(opened.call_count, 2)
        sleep.assert_called_once_with(0.5)

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
