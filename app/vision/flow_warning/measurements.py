from dataclasses import dataclass, field
import math

import numpy as np

from ..tracking.bubble_matching import BubbleBoTSORT, detection_rows


@dataclass
class FrameMeasurement:
    frame_id: int
    timestamp: object
    valid: bool = True
    reason: str = ""
    bubble_count: object = None
    area_ratio: object = None
    complete_count: int = 0
    diameters: list = field(default_factory=list)
    velocities: list = field(default_factory=list)
    samples: list = field(default_factory=list)
    source: str = ""


class FrameMeasurer:
    def __init__(self, roi, scale=0.01, min_area=10, max_distance=40, tracker_settings=None):
        self.roi = roi
        self.scale = scale
        self.min_area = min_area
        self.max_distance = max_distance
        config = tracker_settings
        self.tracker = BubbleBoTSORT(
            high=config.track_high_thresh if config else 0.6,
            low=config.track_low_thresh if config else 0.1,
            new=config.new_track_thresh if config else 0.7,
            match=config.match_thresh if config else 0.8,
            max_lost_frames=config.bubble_max_lost_frames if config else 3,
            ambiguity_margin=0.05,
        )
        self.observations = {}
        self.previous_frame = None
        self.previous_timestamp = None

    def measure(self, masks, shape, frame_id, timestamp, error="", detections=None):
        result = FrameMeasurement(frame_id, timestamp, valid=not bool(error), reason=error)
        if error:
            self._reset_association()
            self.previous_frame = frame_id
            self.previous_timestamp = None
            return result
        if detections is not None:
            detections = detection_rows(detections)
            if (detections.ndim != 2 or detections.shape[0] != len(masks)
                    or detections.shape[1] not in (6, 7) or not np.isfinite(detections).all()
                    or np.any(detections[:, 2:4] <= detections[:, :2])):
                return self.measure([], shape, frame_id, timestamp, error="invalid_detections")
        height, width = shape[:2]
        x1, y1, x2, y2 = self.roi.resolve(shape)
        union = np.zeros((y2 - y1, x2 - x1), dtype=bool)
        tracking_detections = []
        for source_index, source_mask in enumerate(masks):
            mask = np.asarray(source_mask, dtype=bool)
            if mask.ndim != 2 or mask.shape != (height, width):
                return self.measure([], shape, frame_id, timestamp, error="invalid_mask_shape")
            clipped = mask[y1:y2, x1:x2]
            area = int(clipped.sum())
            if area < max(1, self.min_area):
                continue
            union |= clipped
            coordinates_y, coordinates_x = np.nonzero(clipped)
            center = (float(coordinates_x.mean() + x1), float(coordinates_y.mean() + y1))
            touches_edge = bool(
                clipped[0].any() or clipped[-1].any()
                or clipped[:, 0].any() or clipped[:, -1].any()
            )
            sample = {
                "frame": frame_id, "time": timestamp, "track_id": None,
                "x": center[0], "y": center[1], "area_px": area,
                "diameter": None, "rise_velocity": None, "vx": None,
                "turn_angle": None, "reason": "roi_or_image_edge" if touches_edge else "",
            }
            result.samples.append(sample)
            if detections is None:
                full_y, full_x = np.nonzero(mask)
                tracking_detections.append([full_x.min(), full_y.min(), full_x.max()+1, full_y.max()+1, 1, 0])
            else:
                tracking_detections.append(detections[source_index])
            if not touches_edge:
                sample["diameter"] = 2 * math.sqrt(area / math.pi) * self.scale
                result.diameters.append(sample["diameter"])
        result.bubble_count = len(result.samples)
        result.area_ratio = float(union.sum()) / union.size * 100
        result.complete_count = len(result.diameters)
        self._measure_motion(result, tracking_detections, shape, frame_id, timestamp)
        return result

    def _reset_association(self):
        self.tracker.reset()
        self.observations.clear()

    def _measure_motion(self, result, detections, shape, frame_id, timestamp):
        has_time = timestamp is not None and math.isfinite(timestamp)
        gap = self.previous_frame is not None and frame_id != self.previous_frame + 1
        invalid_time = (has_time and self.previous_timestamp is not None
                        and timestamp <= self.previous_timestamp)
        if not has_time or gap or invalid_time:
            self._reset_association()
        self.previous_frame = frame_id
        self.previous_timestamp = timestamp if has_time else None
        if not has_time or invalid_time:
            for sample in result.samples:
                if not sample["reason"]:
                    sample["reason"] = "missing_time" if not has_time else "invalid_time"
            return
        self.tracker.frame_id = frame_id - 1
        frame = np.broadcast_to(np.uint8(0), (*shape[:2], 3))
        values = np.asarray(detections, dtype=np.float32) if detections else np.empty((0, 6), np.float32)
        tracks = {track.bubble_detection_index: track for track in self.tracker.update(values, frame)}
        for sample_index, sample in enumerate(result.samples):
            track = tracks.get(sample_index)
            if track is None:
                if not sample["reason"]:
                    sample["reason"] = "unmatched_or_confidence"
                continue
            track_id = int(track.track_id)
            sample["track_id"] = track_id
            if sample["reason"]:
                self.observations.pop(track_id, None)
                continue
            prior = self.observations.get(track_id)
            if gap:
                sample["reason"] = "frame_gap"
            elif track.bubble_ambiguous_match:
                sample["reason"] = "ambiguous_match"
            elif prior is None:
                sample["reason"] = "new_track"
            else:
                elapsed = timestamp - prior["time"]
                delta = np.array([sample["x"] - prior["x"], sample["y"] - prior["y"]])
                frame_gap = frame_id - prior["frame"]
                if (np.linalg.norm(delta) > self.max_distance * frame_gap
                        or not 0.5 <= sample["area_px"] / prior["area_px"] <= 2):
                    sample["reason"] = "unmatched_or_distance"
                else:
                    sample["vx"] = float(delta[0] * self.scale / elapsed)
                    sample["rise_velocity"] = float(-delta[1] * self.scale / elapsed)
                    previous_delta = prior.get("delta")
                    if previous_delta is not None:
                        denominator = np.linalg.norm(previous_delta) * np.linalg.norm(delta)
                        if denominator > 1e-8:
                            cosine = np.clip(np.dot(previous_delta, delta) / denominator, -1, 1)
                            sample["turn_angle"] = float(np.degrees(np.arccos(cosine)))
                    sample["delta"] = delta
                    result.velocities.append(sample["rise_velocity"])
            self.observations[track_id] = dict(sample)
        max_gap = self.tracker.max_time_lost
        self.observations = {key: sample for key, sample in self.observations.items()
                             if frame_id - sample["frame"] <= max_gap}
