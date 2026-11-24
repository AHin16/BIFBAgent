"""Predict local H3 rise speed and compare an oxygen-transfer proxy."""

import json
from math import isclose, isfinite, sqrt
from statistics import linear_regression, mean

from .model import FLOW_LEVELS, ROOT, validate_flow


MEASUREMENTS = ROOT / "data/variation_evaluation/h3_pl10/transport_sequence_96/measurements.json"
FEATURES = ("rise_mm_s", "d32_mm", "interfacial_area_times_depth")
H3_VIEW_DEPTH_MM = 8.0


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
            window_holdup = [
                100 * row["gas_volume_per_view_area_mm"] / H3_VIEW_DEPTH_MM for row in group
            ]
            if any(not isfinite(value) or not 0 <= value <= 100 for value in window_holdup):
                raise ValueError(f"Q={q:g} 的照片气含率超出物理范围。")
            stats["gas_holdup_percent"] = mean(window_holdup)
            self.conditions[q] = stats

    @classmethod
    def load(cls, path=None):
        with (path or MEASUREMENTS).open(encoding="utf-8") as stream:
            return cls(json.load(stream))

    def validation(self, feature="rise_mm_s", value_unit="mm_s", error_unit="mm_s"):
        rows = []
        for q in FLOW_LEVELS:
            train = [(flow, row[feature]) for flow, row in self.conditions.items() if flow != q]
            measured = self.conditions[q][feature]
            is_interior = train[0][0] < q < train[-1][0]
            fit = linear_regression([flow for flow, _ in train], [speed for _, speed in train])
            rows.append({
                "q_m3_h": q,
                "coverage": "interpolation" if is_interior else "extrapolation",
                f"measured_{value_unit}": measured,
                f"linear_{value_unit}": fit.intercept + fit.slope * q,
                f"neighbor_{value_unit}": interpolate(q, train) if is_interior else None,
                f"mean_{value_unit}": mean(value for _, value in train),
            })
        interior = [row for row in rows if row["coverage"] == "interpolation"]
        return {
            "folds": rows,
            f"interior_mae_{error_unit}": {
                label: mean(abs(row[f"{label}_{value_unit}"] - row[f"measured_{value_unit}"]) for row in interior)
                for label in ("linear", "neighbor", "mean")
            },
        }

    def target_comparison(self, target_q, validation, value_unit, error_unit):
        if target_q not in self.conditions:
            return None
        fold = next(row for row in validation["folds"] if row["q_m3_h"] == target_q)
        estimate = fold[f"neighbor_{value_unit}"]
        method = "neighbor_interpolation"
        if estimate is None:
            estimate = fold[f"linear_{value_unit}"]
            method = "linear_extrapolation"
        observed = fold[f"measured_{value_unit}"]
        return {
            "method": method,
            f"prediction_{value_unit}": estimate,
            f"observed_{value_unit}": observed,
            f"absolute_error_{error_unit}": abs(estimate - observed),
            "valid_frames": self.conditions[target_q]["valid_frames"],
        }

    def predict(self, current_q, target_q):
        validate_flow(current_q, "当前")
        validate_flow(target_q, "目标")

        def at_flow(q):
            estimates = {
                key: interpolate(q, [(flow, row[key]) for flow, row in self.conditions.items()])
                for key in (*FEATURES, "gas_holdup_percent")
            }
            return {**estimates, "is_measured_flow": q in self.conditions}

        current, target = at_flow(current_q), at_flow(target_q)
        velocity_change = target["rise_mm_s"] - current["rise_mm_s"]
        oxygen_ratio = oxygen_proxy(target, target_q) / oxygen_proxy(current, current_q)
        validation = self.validation()
        holdup_validation = self.validation("gas_holdup_percent", "percent", "pp")
        return {
            "current": current,
            "target": target,
            "target_rise_comparison": self.target_comparison(target_q, validation, "mm_s", "mm_s"),
            "target_holdup_comparison": self.target_comparison(target_q, holdup_validation, "percent", "pp"),
            "gas_holdup_change_pp": target["gas_holdup_percent"] - current["gas_holdup_percent"],
            "view_depth_mm": H3_VIEW_DEPTH_MM,
            "holdup_validation": holdup_validation,
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
                "体积气含率采用 H3 确认的 8 mm 视野深度，由照片分割和等效球体积估算，表示局部视野内的气相体积分数。",
            ],
        }


if __name__ == "__main__":
    model = TransportModel.load()
    output = MEASUREMENTS.with_name("model_report.json")
    output.write_text(json.dumps(model.predict(1.5, 2.0), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(output)
