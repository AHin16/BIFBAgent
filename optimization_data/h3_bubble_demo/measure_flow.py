"""Measure H3 bubble motion and interfacial area in indexed continuous frames."""

import argparse
import csv
import json
from collections import Counter, defaultdict
from hashlib import sha256
from math import pi, sqrt
from pathlib import Path
from statistics import mean, median
from types import SimpleNamespace

import cv2
import numpy as np

from app.config import load_settings
from app.vision.frames import read_segmentation
from app.vision.gas_holdup import analyze_masks
from app.vision.image_io import read_image
from app.vision.tracking import SEQUENCE_CONFIDENCE, TRACKER_SOURCES
from app.vision.tracking.bubble_matching import BubbleBoTSORT, detection_rows
from app.vision.tracking.motion import MotionAnalyzer
from app.vision.tracking.workflow import frame_observations
from app.vision import source_hash
from app.yolo_adapter import YoloAdapter
from .model import FLOW_LEVELS, HEIGHT_M, LOADING_FRACTION, ROOT, SALINITY_WT_PCT
from .transport import MEASUREMENTS


INDEX = ROOT / "data/h3_confirmed/model/image_statistics.csv"
OUTPUT = MEASUREMENTS.parent
GEOMETRY_CONFIDENCE = 0.25
REFERENCE_DEPTH_MM = 1.0
FRAME_SHAPE = (1016, 1264)


def read_sequences(index):
    by_flow = defaultdict(list)
    with index.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if (float(row["height_m"]), float(row["salinity_wt_pct"]), float(row["PL_fraction"])) == (
                HEIGHT_M, SALINITY_WT_PCT, LOADING_FRACTION
            ):
                by_flow[float(row["Q_m3_h"])].append(row)
    if tuple(sorted(by_flow)) != FLOW_LEVELS:
        raise ValueError("需要四档完整的 H3 采集序列。")
    for rows in by_flow.values():
        if len({row["sequence_id"] for row in rows}) != 1 or len({Path(row["image_path"]).parent for row in rows}) != 1:
            raise ValueError("每档气量需对应一个已确认的采集目录。")
        rows.sort(key=lambda row: int(Path(row["image_path"]).stem))
        numbers = [int(Path(row["image_path"]).stem) for row in rows]
        if numbers != list(range(numbers[0], numbers[0] + len(numbers))):
            raise ValueError("序列中存在编号缺口或重复。")
    return by_flow


def select_windows(rows, frames_per_window):
    if len(rows) < 5 * frames_per_window:
        raise ValueError("序列太短，无法选择三个分开的连续帧窗口。")
    for fraction in (0.15, 0.50, 0.85):
        start = round(fraction * (len(rows) - 1)) - frames_per_window // 2
        yield rows[start:start + frames_per_window]


def measure_window(rows, predictor, fps, mm_per_pixel, motion_path):
    tracker = BubbleBoTSORT()
    options = SimpleNamespace(frame_interval_seconds=1 / fps, pixel_to_real_scale=mm_per_pixel,
                              distance_unit="mm", min_track_frames=5)
    motion = MotionAnalyzer(options)
    frame_areas, gas_depths = [], []
    diameters = []
    errors = Counter()
    for frame_id, row in enumerate(rows, 1):
        try:
            frame = read_image(row["image_path"])
        except (OSError, ValueError, cv2.error):
            frame = None
        if frame is None or frame.shape[:2] != FRAME_SHAPE:
            errors["unreadable_image" if frame is None else "frame_shape_changed"] += 1
            tracker.reset()
            continue
        detections, info = predictor.predict(frame)
        masks, reason = read_segmentation(detections, info, frame.shape)
        boxes = detection_rows(detections)
        if reason or len(boxes) != len(masks) or not np.isfinite(boxes).all():
            errors[reason or "invalid_detections"] += 1
            tracker.reset()
            continue
        observations = frame_observations(tracker.update(boxes, frame), masks, 0)
        motion.update(frame_id, observations)

        geometry_masks = [mask for mask, box in zip(masks, boxes) if box[4] >= GEOMETRY_CONFIDENCE]
        # Retain the gas volume per projected area. The reference depth cancels
        # here and never becomes an assumed experimental viewing depth.
        geometry = analyze_masks(geometry_masks, frame.shape, edge_policy="exclude",
                                 real_units_per_pixel=mm_per_pixel, view_depth=REFERENCE_DEPTH_MM)
        mask_areas = [int(np.count_nonzero(mask)) for mask in geometry.accepted_masks]
        frame_areas.append(4 * sum(mask_areas) / geometry.roi_area)
        gas_depths.append(geometry.bubble_volume / geometry.roi_volume * REFERENCE_DEPTH_MM)
        diameters.extend(2 * sqrt(area / pi) * mm_per_pixel for area in mask_areas)

    motion.write_csv(motion_path)
    by_track = defaultdict(list)
    for sample in motion.csv_rows:
        by_track[sample["id"]].append(-sample["vy"])
    signed_tracks = [median(values) for values in by_track.values() if len(values) >= 3]
    rising_tracks = [value for value in signed_tracks if value > 0]
    if len(frame_areas) < 0.9 * len(rows) or not diameters or len(rising_tracks) < 5:
        raise ValueError(f"窗口数据不足：{motion_path.name}，有效帧 {len(frame_areas)}，上升轨迹 {len(rising_tracks)}，坏帧 {dict(errors)}")
    return {
        "valid_frames": len(frame_areas),
        "invalid_frames": dict(errors),
        "motion_samples": len(motion.csv_rows),
        "rising_tracks": len(rising_tracks),
        "qualified_tracks": len(signed_tracks),
        "rise_mm_s": median(rising_tracks),
        "d32_mm": sum(d ** 3 for d in diameters) / sum(d ** 2 for d in diameters),
        "interfacial_area_times_depth": mean(frame_areas),
        "gas_volume_per_view_area_mm": mean(gas_depths),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=INDEX)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--frames-per-window", type=int, default=96)
    parser.add_argument("--fps", type=float, default=173)
    parser.add_argument("--pixels-per-mm", type=float, default=104.28)
    args = parser.parse_args()
    if args.frames_per_window < 12 or not np.isfinite([args.fps, args.pixels_per_mm]).all() or min(args.fps, args.pixels_per_mm) <= 0:
        parser.error("需要有效帧率、空间标定和至少 12 帧的窗口。")
    sequences = read_sequences(args.index)
    args.output.mkdir(parents=True, exist_ok=True)
    weights = ROOT / "models/3900.pt"
    settings = load_settings().model_copy(update={
        "yolo_model_path": str(weights),
        "confidence": SEQUENCE_CONFIDENCE,
    })
    adapter = YoloAdapter()
    adapter.load(settings)
    if adapter.predictor.task != "segment":
        raise ValueError("需要气泡实例分割权重。")
    windows = []
    for q in FLOW_LEVELS:
        for window, rows in enumerate(select_windows(sequences[q], args.frames_per_window), 1):
            path = args.output / f"q{q:g}_window{window}_motion.csv"
            result = measure_window(rows, adapter.predictor, args.fps, 1 / args.pixels_per_mm, path)
            result.update(q_m3_h=q, window=window, sequence_id=rows[0]["sequence_id"], source=rows[0]["source"],
                          indexed_frames=len(rows), first_image=rows[0]["image_path"], last_image=rows[-1]["image_path"],
                          motion_csv=path.name)
            windows.append(result)
            print(f"Q={q:g} window={window}: {result['valid_frames']} frames, "
                  f"{result['rising_tracks']} rising tracks, {result['rise_mm_s']:.2f} mm/s", flush=True)
    report = {
        "fps": args.fps,
        "fps_source": "experiment_nominal",
        "mm_per_pixel": 1 / args.pixels_per_mm,
        "geometry_confidence": GEOMETRY_CONFIDENCE,
        "tracking_confidence": SEQUENCE_CONFIDENCE,
        "weights_sha256": sha256(weights.read_bytes()).hexdigest(),
        "tracking_source_hash": source_hash(*TRACKER_SOURCES, "tracking/motion.py", "tracking/workflow.py"),
        "geometry_source_hash": source_hash("gas_holdup.py", "frames.py", "predictor.py"),
        "device": str(adapter.predictor.model.device),
        "windows": windows,
    }
    temporary = args.output / "measurements.json.tmp"
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(args.output / "measurements.json")


if __name__ == "__main__":
    main()
