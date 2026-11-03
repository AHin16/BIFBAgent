"""Local-only smoke check: real YOLOTracker workflow, real weights, no LLM API.

Uses repeated copies of a shipped image to check integration, not experimental validity.
"""

import json
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import DATA, load_settings, local_path
from app.flow_warning import FlowSettings, register_flow_tools, save_flow_config
from app.registry import ToolRegistry
from app.storage import Session, ToolContext


def main():
    settings = load_settings()
    source = local_path(settings.yolo_tracker_path) / "data/dataset/test_images/0228.tif"
    identifier = "flow_smoke_" + uuid.uuid4().hex[:12]
    fixture = DATA / "validation" / identifier
    baseline = fixture / "baseline"
    measured = fixture / "analysis"
    for folder in (baseline, measured):
        folder.mkdir(parents=True, exist_ok=True)
        for frame in range(8):
            shutil.copyfile(source, folder / f"frame{frame:03d}.tif")
    session = Session()
    session.grant(baseline)
    session.grant(measured)
    config = save_flow_config(session, FlowSettings(baseline_path=str(baseline), input_path=str(measured),
        fps=10, mm_per_pixel=0.01, window_seconds=0.2, min_samples=3,
        acquisition_confirmed=True, normal_baseline_confirmed=True), settings)
    registry = ToolRegistry()
    register_flow_tools(registry)
    result = registry.execute("analyze_flow_warning", {"config_id": config["config_id"]}, ToolContext(session, settings, identifier))
    summary = {key: result.get(key) for key in ("status", "message", "result_id", "baseline_frames", "processed_frames", "window_count", "event_count", "latest_state", "quality")}
    summary["fixture_note"] = "重复示例图片，仅验证集成，不代表真实连续采集实验。未调用 LLM API。"
    (fixture / "smoke_result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    if result["status"] != "success" or result["processed_frames"] != 8 or result["baseline_frames"] != 8:
        raise RuntimeError("真实 YOLO 流态集成验证未通过。")


if __name__ == "__main__":
    main()
