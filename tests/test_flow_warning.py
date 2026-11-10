import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from pydantic import ValidationError

from app.agent import Run, run_agent
from app.config import ROOT, Settings
from app.flow_warning import FlowSettings, FlowWarningAdapter, register_flow_tools, save_flow_config
from app.registry import ToolRegistry
from app.storage import Session, ToolContext, ToolError


class MovingPredictor:
    task = "segment"

    def predict(self, image):
        if int(image[0, 0, 2]):
            return np.ones((1, 6)), {"mask_boxes": np.ones((1, 4))}
        mask = np.zeros(image.shape[:2], dtype=np.uint8)
        top = 30 - int(image[0, 0, 0])
        size = 8 if image[0, 0, 1] else 4
        mask[top:top + size, 20:20 + size] = 1
        return None, {"mask_arrays": [mask]}


class FlowIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "data", prefix="flow_test_")
        self.root = Path(self.temp.name)
        self.baseline = self.root / "baseline"
        self.source = self.root / "analysis"
        self.baseline.mkdir()
        self.source.mkdir()
        for index in range(20):
            image = np.zeros((60, 60, 3), np.uint8)
            image[0, 0, 0] = index
            cv2.imwrite(str(self.baseline / f"frame{index:03d}.png"), image)
            image[0, 0, 1] = 1
            cv2.imwrite(str(self.source / f"frame{index:03d}.png"), image)
        weights = self.root / "test.pt"
        weights.touch()
        self.settings = Settings(yolo_model_path=str(weights))
        self.session = Session()
        self.session.grant(self.baseline)
        self.session.grant(self.source)
        self.request = FlowSettings(baseline_path=str(self.baseline), input_path=str(self.source), fps=10,
            mm_per_pixel=0.01, window_seconds=0.5, min_samples=3, min_area=1,
            acquisition_confirmed=True, normal_baseline_confirmed=True)
        self.config = save_flow_config(self.session, self.request, self.settings)
        self.backend = FlowWarningAdapter(predictor_factory=lambda _: MovingPredictor())
        self.registry = ToolRegistry()
        register_flow_tools(self.registry, self.backend)
        self.events = []
        self.run_id = "flow_test_" + self.root.name
        self.stop = threading.Event()
        self.context = ToolContext(self.session, self.settings, self.run_id,
            lambda kind, payload: self.events.append((kind, payload)), self.stop)

    def tearDown(self):
        self.temp.cleanup()

    def execute(self):
        result = self.registry.execute("analyze_flow_warning", {"config_id": self.config["config_id"]}, self.context)
        self.assertNotEqual(result["status"], "error", result)
        return result

    def test_pipeline_preserves_upstream_events_quality_and_artifacts(self):
        result = self.execute()
        self.assertEqual(result["processed_frames"], 20)
        self.assertEqual(result["baseline_frames"], 20)
        self.assertEqual(result["window_count"], 4)
        self.assertGreater(result["event_count"], 0)
        self.assertTrue(all(event["end_reason"] == "end_of_sequence" for event in result["events"]))
        self.assertEqual(result["quality"]["analysis"]["valid_fraction"], 1)
        self.assertTrue(result["baseline_limits"])
        self.assertTrue(any(artifact["title"] == "窗口指标 · CSV" for artifact in result["artifacts"]))
        self.assertEqual(sum(kind == "flow_window" for kind, _ in self.events), 4)
        inspected = self.registry.execute("inspect_flow_event", {"result_id": result["result_id"], "event_id": result["events"][0]["id"]}, self.context)
        self.assertEqual(inspected["status"], "success")
        self.assertTrue(inspected["artifacts"][0]["url"].startswith("/artifacts/"))

    def test_missing_masks_are_insufficient_not_zero_or_normal(self):
        for image_path in self.source.glob("*.png"):
            image = cv2.imread(str(image_path))
            image[0, 0, 2] = 1
            cv2.imwrite(str(image_path), image)
        result = self.execute()
        self.assertEqual(result["event_count"], 0)
        self.assertEqual(result["latest_state"], "insufficient")
        self.assertEqual(result["quality"]["analysis"]["invalid_reasons"]["missing_segmentation_masks"], 20)
        self.assertIsNone(result["metric_summaries"]["area_ratio"]["median"])

    def test_partial_tail_cannot_be_reported_as_normal(self):
        for image_path in sorted(self.source.glob("*.png"))[17:]:
            image_path.unlink()
        result = self.execute()
        self.assertEqual(result["latest_state"], "insufficient")
        self.assertFalse(result["latest_window"]["complete"])
        self.assertEqual(result["window_state_counts"]["insufficient"], 1)

    def test_stop_saves_partial_outputs(self):
        def progress(kind, payload):
            self.events.append((kind, payload))
            if kind == "flow_window":
                self.stop.set()
        self.context.emit = progress
        result = self.execute()
        self.assertTrue(result["stopped"])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["processed_frames"], 5)
        self.assertTrue(result["artifacts"])

    def test_unconfirmed_or_nested_sources_are_rejected(self):
        values = self.request.model_dump()
        values["acquisition_confirmed"] = False
        with self.assertRaises(ValidationError):
            FlowSettings(**values)
        request = self.request.model_copy(update={"baseline_path": str(self.root)})
        self.session.grant(self.root)
        with self.assertRaises(ToolError):
            save_flow_config(self.session, request, self.settings)
        request = self.request.model_copy(update={"fps": 1000})
        with self.assertRaises(ToolError):
            save_flow_config(self.session, request, self.settings)

    def test_llm_receives_real_results_before_final_explanation(self):
        captured = []
        config_id = self.config["config_id"]
        def capture(messages, tools):
            captured.append(json.loads(json.dumps(messages)))
            tool_results = [json.loads(message["content"]) for message in messages if message["role"] == "tool"]
            if not tool_results:
                return {"role": "assistant", "content": "", "tool_calls": [{"id": "flow-call", "type": "function", "function": {
                    "name": "analyze_flow_warning", "arguments": json.dumps({"config_id": config_id})}}]}
            result = tool_results[-1]
            return {"role": "assistant", "content": "指标显示存在相对基线的持续异常，依据 [" + result["result_id"] + "]；未查看画面，不能判断具体流型。"}
        class LocalModel:
            async def complete(self, messages, tools=None):
                return capture(messages, tools)
        run = Run(self.session.id)
        self.session.busy = True
        with patch("app.agent.LLMClient", return_value=LocalModel()):
            asyncio.run(run_agent(run, self.session, self.settings, self.registry, "简单分析流动状态", config_id))
        self.assertEqual(len(captured), 2)
        observation = next(message for message in captured[-1] if message["role"] == "tool")
        self.assertIn("metric_summaries", observation["content"])
        self.assertIn("baseline_limits", observation["content"])
        self.assertTrue(any(event["type"] == "final" and "指标显示" in event["message"] for event in run.events))
        self.assertFalse(self.session.busy)

    def test_no_unsupported_final_if_model_skips_required_tool(self):
        class SkippingModel:
            async def complete(self, messages, tools=None):
                return {"role": "assistant", "content": "流动正常。"}
        run = Run(self.session.id)
        with patch("app.agent.LLMClient", return_value=SkippingModel()):
            asyncio.run(run_agent(run, self.session, self.settings, self.registry, "流态监测", self.config["config_id"]))
        self.assertFalse(any(event["type"] == "final" for event in run.events))
        self.assertTrue(any(event["type"] == "error" for event in run.events))

    def test_api_registers_local_sources_and_rejects_unconfirmed_config(self):
        from fastapi.testclient import TestClient
        from app.main import app, sessions
        with TestClient(app) as client:
            session_id = client.post("/api/sessions").json()["session_id"]
            try:
                invalid = self.request.model_dump()
                invalid["normal_baseline_confirmed"] = False
                self.assertEqual(client.post(f"/api/sessions/{session_id}/flow-config", json=invalid).status_code, 422)
                response = client.post(f"/api/sessions/{session_id}/flow-config", json=self.request.model_dump())
                self.assertEqual(response.status_code, 200, response.text)
                saved = response.json()
                self.assertEqual(len(saved["assets"]), 2)
                self.assertEqual(saved["flow_config"]["frames_per_window"], 5)
                restored = client.get(f"/api/sessions/{session_id}").json()
                self.assertEqual(restored["flow_config"]["config_id"], saved["flow_config"]["config_id"])
            finally:
                sessions.pop(session_id, None)

    def test_waiting_for_model_can_be_stopped_without_calling_tools(self):
        class SlowModel:
            async def complete(self, messages, tools=None):
                await asyncio.sleep(5)
                return {"role": "assistant", "content": "unused"}
        run = Run(self.session.id)
        async def scenario():
            asyncio.get_running_loop().call_later(0.05, run.stop_event.set)
            await run_agent(run, self.session, self.settings, self.registry, "分析")
        with patch("app.agent.LLMClient", return_value=SlowModel()):
            asyncio.run(scenario())
        self.assertTrue(run.done)
        self.assertTrue(any(event["type"] == "final" and "已停止" in event["message"] for event in run.events))
        self.assertFalse(any(event["type"] == "tool_start" for event in run.events))


if __name__ == "__main__":
    unittest.main()
