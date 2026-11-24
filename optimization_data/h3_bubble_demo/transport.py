"""Predict local H3 rise speed and compare an oxygen-transfer proxy."""

import json
from math import isclose, isfinite, sqrt
from statistics import linear_regression, mean

from .model import FLOW_LEVELS, ROOT, validate_flow


MEASUREMENTS = ROOT / "data/variation_evaluation/h3_pl10/transport_sequence_96/measurements.json"
FEATURES = ("rise_mm_s", "d32_mm", "interfacial_area_times_depth")


def interpolate(q, points):
    """Evaluate a line between neighboring measured flow levels."""
    for (left, low), (right, high) in zip(points, points[1:]):
        if left <= q <= right:
            return low + (high - low) * (q - left) / (right - left)
    raise ValueError("预测气量超出数据范围。")


def oxygen_proxy(row, q):
    # Constants and the unknown viewing depth cancel in ratios for the same setup.
    return row["interfacial_area_times_depth"] * sqrt(row["rise_mm_s"] / row["d32_mm"]) / q


class TransportModel:
    def __init__(self, measurements):
        self.fps = measurements["fps"]
        self.mm_per_pixel = measurements["mm_per_pixel"]
        if any(not isfinite(value) or value <= 0 for value in (self.fps, self.mm_per_pixel)):
            raise ValueError("采集帧率或空间标定无效。")
        self.conditions = {}
        windows = measurements["windows"]
        for q in FLOW_LEVELS:
            group = [row for row in windows if row["q_m3_h"] == q]
            if {row["window"] for row in group} != {1, 2, 3} or len(group) != 3 or len({row["sequence_id"] for row in group}) != 1:
                raise ValueError(f"Q={q:g} 缺少完整的三个追踪窗口。")
            stats = {key: mean(row[key] for row in group) for key in FEATURES}
            if any(not isfinite(value) or value <= 0 for value in stats.values()):
                raise ValueError(f"Q={q:g} 的测量结果无效。")
            stats["valid_frames"] = sum(row["valid_frames"] for row in group)
            stats["rising_tracks"] = sum(row["rising_tracks"] for row in group)
            stats["window_rise_mm_s"] = [row["rise_mm_s"] for row in group]
            self.conditions[q] = stats

    @classmethod
    def load(cls, path=None):
        with (path or MEASUREMENTS).open(encoding="utf-8") as stream:
            return cls(json.load(stream))

    def validation(self):
        rows = []
        for q in FLOW_LEVELS:
            train = [(flow, row["rise_mm_s"]) for flow, row in self.conditions.items() if flow != q]
            measured = self.conditions[q]["rise_mm_s"]
            is_interior = train[0][0] < q < train[-1][0]
            fit = linear_regression([flow for flow, _ in train], [speed for _, speed in train])
            rows.append({
                "q_m3_h": q,
                "coverage": "interpolation" if is_interior else "extrapolation",
                "measured_mm_s": measured,
                "linear_mm_s": fit.intercept + fit.slope * q,
                "neighbor_mm_s": interpolate(q, train) if is_interior else None,
                "mean_mm_s": mean(speed for _, speed in train),
            })
        interior = [row for row in rows if row["coverage"] == "interpolation"]
        return {
            "folds": rows,
            "interior_mae_mm_s": {
                label: mean(abs(row[f"{label}_mm_s"] - row["measured_mm_s"]) for row in interior)
                for label in ("linear", "neighbor", "mean")
            },
        }

    def predict(self, current_q, target_q):
        validate_flow(current_q, "当前")
        validate_flow(target_q, "目标")

        def at_flow(q):
            estimates = {
                key: interpolate(q, [(flow, row[key]) for flow, row in self.conditions.items()])
                for key in FEATURES
            }
            return {**estimates, "is_measured_flow": q in self.conditions}

        current, target = at_flow(current_q), at_flow(target_q)
        velocity_change = target["rise_mm_s"] - current["rise_mm_s"]
        oxygen_ratio = oxygen_proxy(target, target_q) / oxygen_proxy(current, current_q)
        validation = self.validation()
        comparison = None
        if target["is_measured_flow"]:
            fold = next(row for row in validation["folds"] if row["q_m3_h"] == target_q)
            estimate = fold["neighbor_mm_s"]
            method = "neighbor_interpolation"
            if estimate is None:
                estimate = fold["linear_mm_s"]
                method = "linear_extrapolation"
            comparison = {
                "method": method,
                "prediction_mm_s": estimate,
                "observed_mm_s": fold["measured_mm_s"],
                "absolute_error_mm_s": abs(estimate - fold["measured_mm_s"]),
                "valid_frames": self.conditions[target_q]["valid_frames"],
            }
        return {
            "current": current,
            "target": target,
            "target_rise_comparison": comparison,
            "rise_change_mm_s": velocity_change,
            "rise_change_percent": 100 * velocity_change / current["rise_mm_s"],
            "relative_oxygen_efficiency_percent": 100 * oxygen_ratio,
            "oxygen_efficiency_change_percent": 100 * (oxygen_ratio - 1),
            "same_flow": isclose(current_q, target_q, rel_tol=0, abs_tol=1e-12),
            "fps": self.fps,
            "mm_per_pixel": self.mm_per_pixel,
            "validation": validation,
            "small_interpolated_change": (
                not (current["is_measured_flow"] and target["is_measured_flow"])
                and abs(velocity_change) <= validation["interior_mae_mm_s"]["neighbor"]
            ),
            "measured_levels": [{**row, "q_m3_h": q} for q, row in self.conditions.items()],
            "limitations": [
                "速度是固定视野内上升轨迹的竖直速度，每个工况统计同一序列的三个窗口。未采集的气量使用相邻档位线性插值。",
                "相对传氧效率以当前工况为 100%，用局部估算的 KLa/Q 比值表示，假设视野深度和氧浓度驱动力可比，并以上升速度近似滑移速度。",
                "该指标用于筛选工况，实际装置氧传递效率仍需溶解氧或尾气数据验证。",
            ],
        }


if __name__ == "__main__":
    model = TransportModel.load()
    output = MEASUREMENTS.with_name("model_report.json")
    output.write_text(json.dumps(model.predict(1.5, 2.0), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(output)
