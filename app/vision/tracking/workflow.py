import csv
import math
from collections import Counter
from contextlib import closing
from types import SimpleNamespace

import cv2
import numpy as np

from ..frames import FrameSource, read_segmentation
from ..image_io import write_image
from .bubble_matching import BubbleBoTSORT, detection_rows
from .motion import MotionAnalyzer
from .render import plot_tracking


def frame_observations(tracks, masks, edge_margin):
    observations = []
    for item in tracks:
        mask = masks[item.bubble_detection_index]
        ys, xs = np.nonzero(mask)
        height, width = mask.shape
        margin = int(min(xs.min(), ys.min(), width - 1 - xs.max(), height - 1 - ys.max()))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        polygon = max(contours, key=cv2.contourArea).reshape(-1, 2)
        observations.append({
            "track_id": item.track_id, "score": item.score, "tlwh": item.tlwh,
            "polygon": polygon, "center": (float(xs.mean()), float(ys.mean())),
            "area_px": len(xs), "edge_margin_px": margin,
            "passes_edge_filter": margin >= max(1, edge_margin),
        })
    return observations


def tracking_overlay(image, observations, frame, unit):
    return plot_tracking(
        image, [item["tlwh"] for item in observations], [item["track_id"] for item in observations],
        frame_id=frame, mask_polygons=[item["polygon"] for item in observations],
        trajectories=[item["trajectory"] for item in observations],
        centers=[item["center"] for item in observations],
        speeds=[item["speed_real_per_s"] if item["is_csv_sample"] else None for item in observations],
        show_speed_text=True, speed_unit=unit,
        sample_validity=[item["is_csv_sample"] for item in observations],
    )


def run_tracking(source, output, predictor, fps, scale, min_track_frames, edge_margin, stop, progress):
    if predictor.task != "segment":
        raise ValueError("气泡追踪需要气泡实例分割模型。")
    frames = FrameSource(source)
    if frames.images is not None and fps is None:
        raise ValueError("请提供图像序列的实际采集帧率。")
    unit = "mm" if scale is not None else "px"
    tracker = BubbleBoTSORT()
    analyzer = None
    video = None
    shape = None
    stopped = False
    processed = 0
    invalid = Counter()
    unique_ids = set()
    output.mkdir(parents=True)
    video_path = output / "bubble_tracks.mp4"
    motion_path = output / "bubble_motion.csv"
    track_path = output / "bubble_tracks.csv"
    preview_path = output / "bubble_tracks.png"
    fps_source = "provided" if fps is not None else "video_metadata"
    fields = ("frame", "time_seconds", "source", "status", "reason", "track_id", "x_px", "y_px",
              "confidence", "area_px2", "motion_sample")
    preview_quality = -1
    try:
        with closing(iter(frames)) as iterator, track_path.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for frame_id, path, image in iterator:
                if stop and stop.is_set():
                    stopped = True
                    break
                if analyzer is None:
                    fps = fps if fps is not None else frames.video_fps
                    if fps is None or not math.isfinite(fps) or fps <= 0:
                        raise ValueError("视频没有可用帧率，请提供实际采集帧率。")
                    analyzer = MotionAnalyzer(SimpleNamespace(
                        frame_interval_seconds=1 / fps, pixel_to_real_scale=scale if scale is not None else 1,
                        distance_unit=unit, min_track_frames=min_track_frames, edge_exclusion_margin_px=edge_margin,
                    ))
                row = {"frame": frame_id, "time_seconds": (frame_id - 1) / fps, "source": path}
                reason = "unreadable_image" if image is None else ""
                if image is not None and shape is None:
                    shape = image.shape[:2]
                    height, width = shape
                    video = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), fps,
                                            (width + width % 2, height + height % 2))
                    if not video.isOpened():
                        raise OSError("无法创建标注 MP4。")
                    for _ in range(processed):
                        video.write(np.zeros((height + height % 2, width + width % 2, 3), np.uint8))
                if image is not None and image.shape[:2] != shape:
                    reason = "frame_shape_changed"
                if not reason:
                    detections, info = predictor.predict(image)
                    masks, reason = read_segmentation(detections, info, image.shape)
                    rows = detection_rows(detections)
                    if not reason and (rows.ndim != 2 or rows.shape[1] not in (6, 7)
                                       or len(rows) != len(masks) or not np.isfinite(rows).all()
                                       or np.any(rows[:, 2:4] <= rows[:, :2])):
                        reason = "invalid_detections"
                if reason:
                    tracker.reset()
                    invalid[reason] += 1
                    writer.writerow(dict(row, status="invalid", reason=reason))
                    overlay = np.zeros((*shape, 3), np.uint8) if shape else None
                    if overlay is not None:
                        cv2.putText(overlay, reason, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
                else:
                    observations = frame_observations(tracker.update(rows, image), masks, edge_margin)
                    analyzer.update(frame_id, observations)
                    unique_ids.update(item["track_id"] for item in observations)
                    for item in observations:
                        writer.writerow(dict(row, status="tracked", track_id=item["track_id"],
                                             x_px=item["center"][0], y_px=item["center"][1],
                                             confidence=item["score"], area_px2=item["area_px"],
                                             motion_sample=item["is_csv_sample"]))
                    if not observations:
                        writer.writerow(dict(row, status="unmatched" if len(rows) else "empty"))
                    overlay = tracking_overlay(image, observations, frame_id, unit)
                    quality = 2 if any(item["is_csv_sample"] for item in observations) else int(bool(observations))
                    if quality > preview_quality:
                        if not write_image(str(preview_path), overlay):
                            raise OSError("无法保存追踪预览。")
                        preview_quality = quality
                if overlay is not None:
                    height, width = shape
                    video.write(cv2.copyMakeBorder(overlay, 0, height % 2, 0, width % 2, cv2.BORDER_CONSTANT))
                processed += 1
                progress(frame_id, frames.total)
    finally:
        if video is not None:
            video.release()
        if analyzer is not None:
            analyzer.write_csv(motion_path)
    if not processed and not stopped:
        raise ValueError("没有可解码的帧。")
    velocities = [item["speed"] for item in analyzer.csv_rows] if analyzer else []
    result = {
        "processed_frames": processed, "valid_frames": processed - sum(invalid.values()),
        "invalid_frames": dict(invalid), "stopped": stopped, "track_id_count": len(unique_ids),
        "fps": fps, "fps_source": fps_source, "speed_unit": f"{unit}/s",
        "motion_samples": len(velocities),
        "mean_speed": sum(velocities) / len(velocities) if velocities else None,
        "max_speed": max(velocities, default=None),
    }
    return result, (track_path, motion_path, preview_path, video_path)
