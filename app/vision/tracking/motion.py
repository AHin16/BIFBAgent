from collections import defaultdict, deque
import csv
import math
import re
from typing import Any, Dict, List

import numpy as np


def compute_turn_angle_deg(point_a, point_b, point_c, min_segment_distance_px=0.0):
    vector_ab = np.asarray(point_b, dtype=np.float32) - np.asarray(point_a, dtype=np.float32)
    vector_bc = np.asarray(point_c, dtype=np.float32) - np.asarray(point_b, dtype=np.float32)

    length_ab = float(np.linalg.norm(vector_ab))
    length_bc = float(np.linalg.norm(vector_bc))
    if length_ab <= min_segment_distance_px or length_bc <= min_segment_distance_px:
        return None

    cosine = float(np.dot(vector_ab, vector_bc) / max(length_ab * length_bc, 1e-6))
    cosine = float(np.clip(cosine, -1.0, 1.0))
    return float(math.degrees(math.acos(cosine)))


class MotionAnalyzer:
    def __init__(self, args):
        self.frame_interval_seconds = max(float(getattr(args, "frame_interval_seconds", 1.0 / 30.0)), 1e-6)
        self.pixel_to_real_scale = max(float(getattr(args, "pixel_to_real_scale", 1.0)), 0.0)
        self.distance_unit = getattr(args, "distance_unit", "mm") or "unit"
        self.speed_frame_gap = max(int(getattr(args, "speed_frame_gap", 1)), 1)
        self.trail_length = max(int(getattr(args, "trail_length", 24)), 2)
        self.min_track_frames = max(int(getattr(args, "min_track_frames", 5)), 1)
        self.max_turn_angle_deg = float(getattr(args, "max_turn_angle_deg", 120.0))
        self.turn_min_segment_px = max(float(getattr(args, "turn_min_segment_px", 3.0)), 0.0)
        self.edge_exclusion_margin_px = max(float(getattr(args, "edge_exclusion_margin_px", 0.0)), 0.0)
        self.max_history_gap = max(int(getattr(args, "max_history_gap", 10)), 1)
        self.history_size = self.trail_length + self.speed_frame_gap
        self.max_stale_frames = max(self.history_size * 3, 12)
        self.track_states = defaultdict(
            lambda: {
                "history": deque(maxlen=self.history_size),
                "seen_frames": 0,
                "invalid": False,
                "invalid_reason": "",
                "last_turn_angle_deg": None,
                "anchor_center": None,
                "sample_count": 0,
                "speed_sum": 0.0,
                "vx_sum": 0.0,
                "vy_sum": 0.0,
                "rise_speed_sum": 0.0,
            }
        )
        self.csv_rows: List[Dict[str, Any]] = []
        self.accepted_track_ids = set()
        self.area_column_name = self._build_area_column_name()
        self.task_observation_count = 0
        self.task_speed_sum = 0.0
        self.task_area_sum = 0.0
        self.task_max_speed = 0.0

    def update(self, frame_id, frame_tracks):
        for track in frame_tracks:
            track_id = int(track["track_id"])
            center = tuple(float(value) for value in track["center"])
            state = self.track_states[track_id]
            history = state["history"]
            state["invalid"] = False
            state["invalid_reason"] = ""

            if len(history) > 0 and (frame_id - history[-1]["frame_id"]) > self.max_history_gap:
                history.clear()
                state["seen_frames"] = 0
                state["anchor_center"] = None
                state["sample_count"] = 0
                state["speed_sum"] = 0.0
                state["vx_sum"] = 0.0
                state["vy_sum"] = 0.0
                state["rise_speed_sum"] = 0.0
                state["last_turn_angle_deg"] = None

            history.append({"frame_id": frame_id, "center": center})
            state["seen_frames"] += 1

            turn_angle_deg = self._compute_recent_turn_angle(history)
            if turn_angle_deg is not None:
                state["last_turn_angle_deg"] = turn_angle_deg
                if turn_angle_deg > self.max_turn_angle_deg:
                    state["invalid"] = True
                    state["invalid_reason"] = "turn_angle"
                    history.clear()
                    history.append({"frame_id": frame_id, "center": center})
                    state["seen_frames"] = 1
                    state["anchor_center"] = None
                    state["sample_count"] = 0
                    state["speed_sum"] = 0.0
                    state["vx_sum"] = 0.0
                    state["vy_sum"] = 0.0
                    state["rise_speed_sum"] = 0.0

            displacement_px = 0.0
            displacement_real = 0.0
            speed_real = 0.0
            delta_x_real = 0.0
            delta_y_real = 0.0
            velocity_x_real = 0.0
            velocity_y_real = 0.0
            rise_displacement = 0.0
            rise_speed = 0.0
            cumulative_dx_real = 0.0
            cumulative_dy_real = 0.0
            is_mature = state["seen_frames"] >= self.min_track_frames
            is_valid = not state["invalid"]
            is_visible = is_mature and is_valid
            edge_margin_px = float(track.get("edge_margin_px", 0.0))
            passes_edge_filter = bool(
                track.get("passes_edge_filter", edge_margin_px >= self.edge_exclusion_margin_px)
            )
            trajectory = [item["center"] for item in list(history)[-self.trail_length:]] if is_valid else []

            if is_visible and state["anchor_center"] is None:
                state["anchor_center"] = center

            if is_visible and len(history) > self.speed_frame_gap:
                reference = history[-1 - self.speed_frame_gap]
                frame_gap = max(frame_id - reference["frame_id"], 1)
                delta_x_px = center[0] - reference["center"][0]
                delta_y_px = center[1] - reference["center"][1]
                delta_x_real = delta_x_px * self.pixel_to_real_scale
                delta_y_real = delta_y_px * self.pixel_to_real_scale
                displacement_px = math.hypot(delta_x_px, delta_y_px)
                displacement_real = displacement_px * self.pixel_to_real_scale
                elapsed_seconds = max(frame_gap * self.frame_interval_seconds, 1e-6)
                speed_real = displacement_real / elapsed_seconds
                velocity_x_real = delta_x_real / elapsed_seconds
                velocity_y_real = delta_y_real / elapsed_seconds
                rise_displacement = max(-delta_y_real, 0.0)
                rise_speed = max(-velocity_y_real, 0.0)

                anchor_center = state["anchor_center"] if state["anchor_center"] is not None else center
                cumulative_dx_real = (center[0] - anchor_center[0]) * self.pixel_to_real_scale
                cumulative_dy_real = (center[1] - anchor_center[1]) * self.pixel_to_real_scale

            track["age_frames"] = state["seen_frames"]
            track["is_mature"] = is_mature
            track["is_valid"] = is_valid
            track["is_visible"] = is_visible
            track["is_drawable"] = True
            track["filter_reason"] = state["invalid_reason"]
            track["turn_angle_deg"] = state["last_turn_angle_deg"]
            track["trajectory"] = trajectory
            track["edge_margin_px"] = edge_margin_px
            track["passes_edge_filter"] = passes_edge_filter
            track["displacement_px"] = displacement_px
            track["displacement_real"] = displacement_real
            track["speed_real_per_s"] = speed_real
            track["delta_x_real"] = delta_x_real
            track["delta_y_real"] = delta_y_real
            track["velocity_x_real_per_s"] = velocity_x_real
            track["velocity_y_real_per_s"] = velocity_y_real
            track["rise_displacement"] = rise_displacement
            track["rise_speed_per_s"] = rise_speed
            track["cumulative_dx_real"] = cumulative_dx_real
            track["cumulative_dy_real"] = cumulative_dy_real

            is_csv_sample = is_visible and passes_edge_filter and len(history) > self.speed_frame_gap
            track["is_csv_sample"] = is_csv_sample

            if is_visible:
                self.accepted_track_ids.add(track_id)
            if is_csv_sample:
                area_real = float(track.get("area_px", 0.0)) * (self.pixel_to_real_scale ** 2)
                equivalent_diameter = compute_equivalent_diameter(area_real)
                state["sample_count"] += 1
                state["speed_sum"] += speed_real
                state["vx_sum"] += velocity_x_real
                state["vy_sum"] += velocity_y_real
                state["rise_speed_sum"] += rise_speed
                sample_count = max(state["sample_count"], 1)
                self.csv_rows.append(
                    {
                        "frame": frame_id,
                        "id": track_id,
                        "x": round(center[0], 3),
                        "y": round(center[1], 3),
                        "speed": round(speed_real, 6),
                        "avg_speed": round(state["speed_sum"] / sample_count, 6),
                        self.area_column_name: round(area_real, 6),
                        "equivalent_diameter": round(equivalent_diameter, 9),
                        "vx": round(velocity_x_real, 6),
                        "vy": round(velocity_y_real, 6),
                        "vx_avg": round(state["vx_sum"] / sample_count, 6),
                        "vy_avg": round(state["vy_sum"] / sample_count, 6),
                        "dx_total": round(cumulative_dx_real, 6),
                        "dy_total": round(cumulative_dy_real, 6),
                        "rise_displacement": round(rise_displacement, 6),
                        "rise_speed": round(rise_speed, 6),
                        "rise_speed_avg": round(state["rise_speed_sum"] / sample_count, 6),
                        "rise_total": round(max(-cumulative_dy_real, 0.0), 6),
                        "vertical_speed_abs": round(abs(velocity_y_real), 6),
                        "edge_margin_px": round(edge_margin_px, 3),
                    }
                )

        self._prune_history(frame_id)
        return self._build_metrics(frame_id, frame_tracks)

    def _compute_recent_turn_angle(self, history):
        if len(history) < 3:
            return None

        point_a = history[-3]["center"]
        point_b = history[-2]["center"]
        point_c = history[-1]["center"]
        return compute_turn_angle_deg(
            point_a,
            point_b,
            point_c,
            min_segment_distance_px=self.turn_min_segment_px,
        )

    def _prune_history(self, current_frame_id):
        stale_ids = []
        for track_id, state in self.track_states.items():
            history = state["history"]
            if not history:
                stale_ids.append(track_id)
                continue
            if current_frame_id - history[-1]["frame_id"] > self.max_stale_frames:
                stale_ids.append(track_id)

        for track_id in stale_ids:
            self.track_states.pop(track_id, None)

    def _build_metrics(self, frame_id, frame_tracks):
        visible_tracks = [track for track in frame_tracks if track.get("is_visible", True)]
        # Accumulate every processed frame, independently of the preview stride.
        for track in visible_tracks:
            speed = float(track.get("speed_real_per_s", 0.0))
            self.task_observation_count += 1
            self.task_speed_sum += speed
            self.task_area_sum += float(track.get("area_px", 0.0))
            self.task_max_speed = max(self.task_max_speed, speed)

        return {
            "frame_id": frame_id,
            "tracked_count": len(visible_tracks),
            **self._task_metrics(),
            "distance_unit": self.distance_unit,
            "samples_written": len(self.csv_rows),
            "unique_tracks": len(self.accepted_track_ids),
        }

    def _task_metrics(self):
        count = self.task_observation_count
        return {
            "avg_speed": self.task_speed_sum / count if count else 0.0,
            "max_speed": self.task_max_speed,
            "avg_area_px": self.task_area_sum / count if count else 0.0,
        }

    def _build_area_column_name(self):
        normalized_unit = re.sub(r"[^0-9A-Za-z]+", "_", str(self.distance_unit).strip()).strip("_").lower()
        return f"area_{normalized_unit}2" if normalized_unit else "area_real2"

    def write_csv(self, csv_path):
        fieldnames = [
            "frame",
            "id",
            "x",
            "y",
            "speed",
            "avg_speed",
            self.area_column_name,
            "equivalent_diameter",
            "vx",
            "vy",
            "vx_avg",
            "vy_avg",
            "dx_total",
            "dy_total",
            "rise_displacement",
            "rise_speed",
            "rise_speed_avg",
            "rise_total",
            "vertical_speed_abs",
            "edge_margin_px",
        ]

        with open(csv_path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(self.csv_rows)

    def summary(self):
        return {
            **self._task_metrics(),
            "motion_samples": len(self.csv_rows),
            "unique_tracks": len(self.accepted_track_ids),
            "distance_unit": self.distance_unit,
        }


def compute_equivalent_diameter(area):
    return math.sqrt(4 * max(area, 0) / math.pi)
