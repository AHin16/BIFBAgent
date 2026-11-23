import csv

import cv2
import numpy as np

from .frames import FrameSource, read_segmentation
from .gas_holdup import GasHoldupResult, analyze_masks
from .image_io import write_image


def render_gas_holdup_overlay(
    frame,
    result: GasHoldupResult,
    average_diameter,
    distance_unit,
    view_depth,
):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    rendered = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    palette = (
        (36, 181, 255),
        (255, 151, 64),
        (96, 220, 128),
        (214, 120, 255),
        (255, 214, 92),
    )

    for index, mask in enumerate(result.accepted_masks):
        color = np.asarray(palette[index % len(palette)], dtype=np.float32)
        selected = mask.astype(bool)
        rendered[selected] = (
            rendered[selected].astype(np.float32) * 0.45 + color * 0.55
        ).astype(np.uint8)
        contours, _ = cv2.findContours(
            mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        cv2.drawContours(rendered, contours, -1, tuple(int(value) for value in color), 1)

    x1, y1, x2, y2 = result.roi_bounds
    cv2.rectangle(rendered, (x1, y1), (max(x2 - 1, x1), max(y2 - 1, y1)), (255, 255, 255), 1)
    lines = (
        f"Gas Holdup : {result.gas_holdup:.2f} %",
        f"Bubble Volume : {result.bubble_volume:.6g} {distance_unit}^3",
        f"ROI Volume : {result.roi_volume:.6g} {distance_unit}^3",
        f"View Depth : {view_depth:.6g} {distance_unit}",
        f"Bubble Count : {result.bubble_count}",
        f"Projected Area : {result.bubble_area_ratio:.2f} %",
        f"Average Diameter : {average_diameter:.4f} {distance_unit}",
        f"Pixel Diameter : {result.average_diameter:.2f} px",
    )
    text_height = 22 * len(lines) + 12
    panel_width = min(max(frame.shape[1] - 12, 1), 390)
    cv2.rectangle(rendered, (6, 6), (panel_width, min(text_height, frame.shape[0] - 1)), (0, 0, 0), -1)
    for index, line in enumerate(lines):
        cv2.putText(
            rendered,
            line,
            (14, 28 + index * 22),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
    return rendered


def run_gas_holdup(source, output, predictor, scale, depth, roi, edge_policy, min_area, stop, progress):
    if predictor.task != "segment":
        raise ValueError("等效球气含率需要气泡实例分割模型。")
    frames = FrameSource(source, image_only=True)
    overlays = output / "overlays"
    overlays.mkdir(parents=True)
    csv_path = output / "gas_holdup.csv"
    samples = []
    errors = []
    previews = []
    stopped = False
    fields = ("frame", "source", "status", "reason", "bubble_count", "bubble_area_px2", "roi_area_px2",
              "bubble_area_ratio_percent", "gas_holdup_percent", "mean_diameter_mm",
              "mm_per_pixel", "view_depth_mm", "bubble_volume_mm3", "roi_volume_mm3")
    with csv_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for index, path, image in frames:
            if stop and stop.is_set():
                stopped = True
                break
            row = {"frame": index, "source": path, "status": "valid",
                   "mm_per_pixel": scale, "view_depth_mm": depth}
            reason = "unreadable_image" if image is None else ""
            if image is not None:
                try:
                    roi.resolve(image.shape)
                except ValueError:
                    reason = "invalid_roi"
            if not reason:
                detections, info = predictor.predict(image)
                masks, reason = read_segmentation(detections, info, image.shape)
            if reason:
                row.update(status="invalid", reason=reason)
                errors.append(row)
            else:
                value = analyze_masks(masks, image.shape, min_bubble_area=min_area, roi=roi, edge_policy=edge_policy,
                                      real_units_per_pixel=scale, view_depth=depth)
                diameter = value.average_diameter * scale if value.bubble_count else None
                row.update(bubble_count=value.bubble_count, bubble_area_px2=value.bubble_area,
                           roi_area_px2=value.roi_area, bubble_area_ratio_percent=value.bubble_area_ratio,
                           gas_holdup_percent=value.gas_holdup, mean_diameter_mm=diameter,
                           bubble_volume_mm3=value.bubble_volume, roi_volume_mm3=value.roi_volume)
                samples.append(row)
                overlay = render_gas_holdup_overlay(image, value, diameter or 0.0, "mm", depth)
                preview = overlays / f"{index:06d}.png"
                if not write_image(str(preview), overlay):
                    raise OSError(f"无法写入气含率覆盖图：{preview}")
                if len(previews) < 3:
                    previews.append(preview)
            writer.writerow(row)
            progress(index, frames.total)
    return samples, errors, previews, csv_path, stopped, frames.total
