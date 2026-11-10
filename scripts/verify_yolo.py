"""Check built-in YOLO with real weights and blocked legacy source directories.

No LLM requests are made. Optionally select a separately installed official
Ultralytics package with --ultralytics-path and block other source checkouts
with repeated --block-path arguments. The active Python environment is unchanged.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import uuid


ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ultralytics-path", type=Path, help="Directory containing an isolated ultralytics package")
    parser.add_argument("--block-path", action="append", type=Path, default=[], help="Additional source directory to deny")
    arguments = parser.parse_args()
    blocked_roots = [(ROOT.parent / "YOLOTracker").resolve(), *(path.resolve() for path in arguments.block_path)]
    blocked_accesses = []

    def in_blocked_source(path):
        if not isinstance(path, (str, bytes, os.PathLike)):
            return False
        resolved = Path(os.fsdecode(path)).resolve()
        return any(resolved.is_relative_to(root) for root in blocked_roots)

    def audit(event, values):
        if event in {"open", "os.listdir", "os.scandir"} and values and in_blocked_source(values[0]):
            blocked_accesses.append(str(values[0]))
            raise PermissionError("Validation forbids legacy source access: " + str(values[0]))

    sys.path[:] = [path for path in sys.path if not in_blocked_source(path)]
    sys.path.insert(0, str(ROOT))
    if arguments.ultralytics_path:
        package_root = arguments.ultralytics_path.resolve()
        if not (package_root / "ultralytics/__init__.py").is_file():
            parser.error("--ultralytics-path must contain ultralytics/__init__.py")
        sys.path.insert(0, str(package_root))
    sys.addaudithook(audit)

    from app.config import DATA, load_settings
    from app.registry import ToolRegistry
    from app.storage import Session, ToolContext
    from app.yolo_adapter import register_vision_tools

    settings = load_settings()
    identifier = "yolo_smoke_" + uuid.uuid4().hex[:12]
    destination = DATA / "validation" / identifier
    fixture = destination / "images"
    for group in ("low", "high"):
        folder = fixture / group
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "examples/images/0228.tif", folder / "气泡.tif")
    (fixture / "bad.png").write_bytes(b"invalid-image-fixture")
    session = Session()
    session.grant(fixture)
    registry = ToolRegistry()
    register_vision_tools(registry)
    context = ToolContext(session, settings, identifier)
    report = {"validation_id": identifier, "passed": False,
              "blocked_source_paths": [str(path) for path in blocked_roots],
              "fixture_note": "Two copies of the shipped image and one corrupt file; integration check only. No LLM API calls."}
    try:
        single = registry.execute("detect_bubbles", {"image_path": str(fixture / "low/气泡.tif")}, context)
        report["single"] = {key: single.get(key) for key in ("status", "message", "bubble_count", "mean_confidence", "statistics", "backend", "measurement_method", "artifacts")}
        assert single["status"] == "success", single
        assert single["backend"] == "app.vision.PredictorYolo11", single
        assert single["bubble_count"] > 0, single
        assert single["statistics"]["count"] == single["bubble_count"], single
        assert 0 < single["mean_confidence"] <= 1, single
        assert single["measurement_method"] == ["segmentation_mask_equivalent_circle"], single
        batch = registry.execute("batch_detect_bubbles", {"folder_path": str(fixture)}, context)
        report["batch"] = {key: batch.get(key) for key in ("status", "message", "image_count", "processed_count", "failed_count", "bubble_count", "groups", "errors", "artifacts")}
        assert batch["status"] == "partial", batch
        assert (batch["image_count"], batch["processed_count"], batch["failed_count"]) == (3, 2, 1), batch
        assert batch["bubble_count"] == 2 * single["bubble_count"], batch
        assert {group["group"] for group in batch["groups"]} == {"low", "high"}, batch
        assert "逐图片统计 · CSV" in {artifact["title"] for artifact in batch["artifacts"]}, batch
        assert "逐气泡测量 · CSV" in {artifact["title"] for artifact in batch["artifacts"]}, batch
        import ultralytics
        report["ultralytics"] = {"version": ultralytics.__version__, "module_path": ultralytics.__file__}
        if arguments.ultralytics_path:
            assert Path(ultralytics.__file__).is_relative_to(package_root), ultralytics.__file__
        external_modules = [module.__file__ for module in list(sys.modules.values())
                            if getattr(module, "__file__", None) and in_blocked_source(module.__file__)]
        assert not external_modules, external_modules
        assert not blocked_accesses, blocked_accesses
        report["passed"] = True
    finally:
        report["blocked_access_attempts"] = blocked_accesses
        report_path = destination / "smoke_result.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
        print("Report:", report_path, flush=True)


if __name__ == "__main__":
    main()
