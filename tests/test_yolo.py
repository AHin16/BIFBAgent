import json
import os
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
from fastapi.testclient import TestClient

from app.config import DATA, ROOT, Settings, load_settings, save_settings
from app.flow_warning import FlowWarningAdapter
from app.registry import ToolRegistry
from app.storage import Session, ToolContext, ToolError
from app.vision import image_io
from app.yolo_adapter import YoloAdapter, register_vision_tools


class BuiltinYoloTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=DATA, prefix="yolo_test_")
        self.root = Path(self.temp.name)
        self.weights = self.root / "test.pt"
        self.weights.touch()
        self.settings = Settings(yolo_model_path=str(self.weights), yolo_device="cpu", mm_per_pixel=0.1)

    def tearDown(self):
        self.temp.cleanup()

    def test_legacy_configuration_preserves_weights_and_drops_project_path(self):
        config = self.root / "config.local.json"
        config.write_text(json.dumps({"yolo_tracker_path": "Z:/missing/YOLOTracker",
            "yolo_model_path": str(self.weights), "llm_api_key": "test-only-key", "mm_per_pixel": 0.02}), encoding="utf-8")
        (self.root / ".env").write_text("YOLO_TRACKER_PATH=Z:/also-missing\n", encoding="utf-8")
        with patch("app.config.ROOT", self.root), patch("app.config.CONFIG_PATH", config), patch.dict(os.environ, {}, clear=True):
            settings = load_settings()
            self.assertEqual(settings.yolo_model_path, str(self.weights))
            self.assertEqual(settings.mm_per_pixel, 0.02)
            self.assertTrue(settings.public()["model_exists"])
            self.assertNotIn("yolo_tracker_path", settings.public())
            self.assertNotIn("tracker_exists", settings.public())
            save_settings(settings)
        saved = json.loads(config.read_text(encoding="utf-8"))
        self.assertNotIn("yolo_tracker_path", saved)
        self.assertEqual(saved["llm_api_key"], "test-only-key")

    def test_missing_weights_have_actionable_error(self):
        settings = self.settings.model_copy(update={"yolo_model_path": str(self.root / "missing.pt")})
        with self.assertRaisesRegex(ToolError, "选择气泡模型权重"):
            YoloAdapter().load(settings)

    def test_builtin_flow_imports_preserve_other_loaded_packages(self):
        sentinel = types.ModuleType("flow_warning")
        initial_path = list(sys.path)
        with patch.dict(sys.modules, {"flow_warning": sentinel}):
            workflow, rules = FlowWarningAdapter().load()
            self.assertIs(sys.modules["flow_warning"], sentinel)
        self.assertEqual(sys.path, initial_path)
        self.assertTrue(Path(workflow.__file__).is_relative_to(ROOT / "app/vision"))
        self.assertTrue(Path(rules.__file__).is_relative_to(ROOT / "app/vision"))

    def test_detection_and_partial_batch_use_builtin_backend(self):
        folder = self.root / "实验"
        for group in ("low", "high"):
            (folder / group).mkdir(parents=True)
            image_io.write_image(str(folder / group / "气泡.png"), np.zeros((32, 32, 3), dtype=np.uint8))
        (folder / "bad.png").write_bytes(b"not an image")
        predictor = Mock()
        predictor.model.names = {0: "bubble"}
        mask = np.zeros((32, 32), dtype=np.uint8)
        mask[10:16, 10:16] = 1
        detections = Mock()
        detections.detach.return_value.cpu.return_value.numpy.return_value = np.array([[10, 10, 16, 16, 0.9, 0]])
        predictor.predict.return_value = (detections, {"mask_arrays": [mask]})
        registry = ToolRegistry()
        register_vision_tools(registry)
        session = Session()
        session.grant(folder)
        context = ToolContext(session, self.settings, "yolo_" + self.root.name, stop_event=threading.Event())
        backend = YoloAdapter()
        with patch("app.vision.predictor.PredictorYolo11", return_value=predictor), patch("app.yolo_adapter.adapter", backend):
            single = registry.execute("detect_bubbles", {"image_path": str(folder / "low/气泡.png")}, context)
            self.assertEqual(single["status"], "success", single)
            self.assertEqual(single["bubble_count"], 1)
            self.assertEqual(single["backend"], "app.vision.PredictorYolo11")
            self.assertEqual(single["measurements"][0]["area_px2"], 36)
            self.assertAlmostEqual(single["statistics"]["mean"], 2 * np.sqrt(36 / np.pi) * 0.1)
            batch = registry.execute("batch_detect_bubbles", {"folder_path": str(folder)}, context)
        self.assertEqual(batch["status"], "partial", batch)
        self.assertEqual(batch["processed_count"], 2)
        self.assertEqual(batch["failed_count"], 1)
        self.assertEqual(batch["bubble_count"], 2)
        self.assertEqual({item["group"] for item in batch["groups"]}, {"low", "high"})
        self.assertTrue(any(item["title"] == "逐气泡测量 · CSV" for item in batch["artifacts"]))

    def test_settings_api_and_examples_need_no_project_path(self):
        from app.main import app, sessions
        with patch("app.main.settings", self.settings), patch("app.main.save_settings") as save, TestClient(app) as client:
            payload = {"llm_base_url": "http://localhost:1234/v1", "llm_model": "local",
                "yolo_model_path": str(self.weights), "yolo_device": "cpu", "confidence": 0.3}
            response = client.post("/api/settings", json=payload)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()["model_exists"])
            self.assertNotIn("yolo_tracker_path", response.json())
            save.assert_called_once()
            session_id = client.post("/api/sessions").json()["session_id"]
            try:
                for kind in ("image", "folder"):
                    response = client.post(f"/api/sessions/{session_id}/examples/{kind}")
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertTrue(Path(response.json()["path"]).is_relative_to(ROOT / "examples/images"))
            finally:
                sessions.pop(session_id, None)

    def test_holdup_page_runs_without_llm_and_can_query_later_frames(self):
        from app.main import app, registry, runs, sessions

        folder = self.root / "batch"
        folder.mkdir()
        image = np.zeros((32, 32, 3), dtype=np.uint8)
        for index in range(1, 14):
            image_io.write_image(str(folder / f"{index:02}.png"), image)
        mask = np.zeros(image.shape[:2], dtype=np.uint8)
        mask[10:16, 10:16] = 1
        predictor = Mock(task="segment")
        predictor.predict.return_value = (np.array([[10, 10, 16, 16, 0.9, 0]]), {"mask_arrays": [mask]})
        self.assertFalse(self.settings.llm_ready)

        with patch("app.main.settings", self.settings), patch("app.sequence_analysis.yolo") as backend, TestClient(app) as client:
            backend.predictor = predictor
            session_id = client.post("/api/sessions").json()["session_id"]
            path = f"/api/sessions/{session_id}"
            run_id = None
            try:
                self.assertEqual(client.post(f"{path}/paths", json={"path": str(folder), "image_only": True}).status_code, 200)
                payload = {"source_path": str(folder), "view_depth_mm": 10}
                invalid = client.post(f"{path}/holdup", json={**payload, "view_depth_mm": 0})
                self.assertEqual(invalid.status_code, 422)
                response = client.post(f"{path}/holdup", json=payload)
                self.assertEqual(response.status_code, 200, response.text)
                run_id = response.json()["run_id"]
                stream = client.get(f"/api/runs/{run_id}/events")
                events = [json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: ")]
                self.assertTrue(events[-1]["success"], events)
                self.assertTrue(any(event["type"] == "progress" for event in events))
                result = client.get(path).json()["holdup_result"]
                self.assertEqual(result["valid_frames"], 13)
                self.assertNotIn("raw_rows", result)
                self.assertFalse(any(row["frame"] == 13 for row in result["frames"]))

                context = ToolContext(sessions[session_id], self.settings, run_id)
                evidence = registry.execute("inspect_gas_holdup_frame", {"result_id": result["result_id"], "frame": 13}, context)
                self.assertEqual(evidence["frame_metrics"]["frame"], 13)
                self.assertGreater(evidence["frame_metrics"]["gas_holdup_percent"], 0)
            finally:
                sessions.pop(session_id, None)
                if run_id:
                    runs.pop(run_id, None)


if __name__ == "__main__":
    unittest.main()
