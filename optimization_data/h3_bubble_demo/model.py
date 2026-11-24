"""Single-salinity bubble diameter prediction for the standalone H3 demo."""

import csv
from dataclasses import asdict, dataclass
from math import isclose, isfinite
from pathlib import Path
from statistics import linear_regression, mean


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/h3_confirmed/continuous_height/conditions.csv"
HEIGHT_M, LOADING_FRACTION, SALINITY_WT_PCT = 1.2, .10, .5
FLOW_LEVELS = (1.5, 1.8, 2.0, 2.3)


def validate_flow(q, label):
    if not isfinite(q) or not FLOW_LEVELS[0] <= q <= FLOW_LEVELS[-1]:
        raise ValueError(f"{label}气量须在 1.5–2.3 m³/h。")


@dataclass(frozen=True)
class Measurement:
    q_m3_h: float
    d50_px: float
    valid_images: int
    source: str


def load_measurements(path=SOURCE):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        measurements = [
            Measurement(float(row["Q_m3_h"]), float(row["mean_d50_px"]),
                        int(row["valid_images"]), row["source"])
            for row in csv.DictReader(stream)
            if isclose(float(row["height_m"]), HEIGHT_M)
            and isclose(float(row["PL_fraction"]), LOADING_FRACTION)
            and isclose(float(row["salinity_wt_pct"]), SALINITY_WT_PCT)
        ]
    measurements.sort(key=lambda measurement: measurement.q_m3_h)
    if tuple(m.q_m3_h for m in measurements) != FLOW_LEVELS:
        raise ValueError("需要四档唯一的 H3、PL 10%、盐度 0.5 wt% 工况。")
    if any(not isfinite(m.d50_px) or m.d50_px <= 0 or m.valid_images <= 0 for m in measurements):
        raise ValueError("工况测量值或有效图片数无效。")
    return measurements


@dataclass(frozen=True)
class FlowLine:
    slope: float
    intercept: float

    @classmethod
    def fit(cls, measurements):
        regression = linear_regression([m.q_m3_h for m in measurements],
                                       [m.d50_px for m in measurements])
        return cls(regression.slope, regression.intercept)

    def estimate(self, q_m3_h):
        return self.intercept + self.slope * q_m3_h


class BubbleDemo:
    def __init__(self, measurements):
        self.measurements = {m.q_m3_h: m for m in measurements}
        self.line = FlowLine.fit(measurements)

    def predict(self, current_q, target_q):
        validate_flow(current_q, "当前")
        validate_flow(target_q, "目标")
        current_measurement = self.measurements.get(current_q)
        current = current_measurement.d50_px if current_measurement else self.line.estimate(current_q)
        target_measurement = self.measurements.get(target_q)
        target = current if current_q == target_q else self.line.estimate(target_q)
        return {
            "current_d50_px": current,
            "current_is_measured": current_measurement is not None,
            "estimated_d50_px": target,
            "estimated_change_px": target - current,
            "observed_d50_px": target_measurement.d50_px if target_measurement else None,
            "observed_change_px": (
                target_measurement.d50_px - current if target_measurement and current_measurement else None
            ),
        }

    def validation(self, group_key):
        rows = []
        for target in self.measurements.values():
            train = [m for m in self.measurements.values()
                     if getattr(m, group_key) != getattr(target, group_key)]
            fit = FlowLine.fit(train)
            prediction = fit.estimate(target.q_m3_h)
            rows.append({
                "q_m3_h": target.q_m3_h, "prediction_px": prediction, "observed_px": target.d50_px,
                "error_px": abs(prediction - target.d50_px), "training_q": [m.q_m3_h for m in train],
            })
        return {"mae_px": mean(row["error_px"] for row in rows), "rows": rows}

    def ui_data(self):
        return {
            "line": asdict(self.line),
            "measurements": [asdict(m) for m in self.measurements.values()],
            "leave_q_out": self.validation("q_m3_h"),
            "leave_source_out": self.validation("source"),
        }
