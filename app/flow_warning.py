"""Adapter for YOLOTracker's independent, offline flow-warning workflow."""

import csv
import hashlib
import importlib
import json
import logging
import sys
import threading
import time
import uuid
from collections import Counter
from pathlib import Path

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.analysis import save_plot
from app.config import DATA, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, local_path
from app.storage import ToolError
from app.yolo_adapter import adapter as yolo


logger = logging.getLogger(__name__)
STATE_LABELS = {"normal": "正常", "attention": "关注", "warning": "预警", "insufficient": "数据不足"}
GROUP_LABELS = {"appearance": "气泡出现量", "size": "大气泡变化", "motion": "运动状态"}
METRICS = {"area_ratio": "面积占比 (%)", "large_fraction": "大气泡比例 (0–1)", "d90": "D90 (mm)",
           "rise_median": "向上速度中位数 (mm/s)", "velocity_iqr": "速度四分位距 (mm/s)", "down_fraction": "下行比例 (0–1)"}


class FlowSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    baseline_path: str = Field(min_length=1)
    input_path: str = Field(min_length=1)
    fps: float = Field(gt=0, le=100000)
    mm_per_pixel: float = Field(gt=0)
    window_seconds: float = Field(default=0.5, gt=0, le=3600)
    min_samples: int = Field(default=10, ge=1, le=100000)
    trigger_windows: int = Field(default=2, ge=1, le=1000)
    recovery_windows: int = Field(default=2, ge=1, le=1000)
    threshold: float = Field(default=3, gt=0, le=100)
    roi_x: int = Field(default=0, ge=0)
    roi_y: int = Field(default=0, ge=0)
    roi_width: int = Field(default=0, ge=0)
    roi_height: int = Field(default=0, ge=0)
    min_area: int = Field(default=10, ge=1)
    max_distance: float = Field(default=40, gt=0)
    acquisition_confirmed: bool = False
    normal_baseline_confirmed: bool = False

    @model_validator(mode="after")
    def check_confirmation(self):
        if not self.acquisition_confirmed or not self.normal_baseline_confirmed:
            raise ValueError("请确认基线属于正常工况，且两段数据使用相同的真实采集帧率、连续时间口径、标定和 ROI。")
        if self.fps * self.window_seconds < 2:
            raise ValueError("每个时间窗口至少需要两帧。")
        return self


def resolve_source(session, value):
    path = local_path(value)
    path = session.resolve(str(path), folder=path.is_dir())
    if path.is_file() and path.suffix.lower() not in VIDEO_EXTENSIONS:
        raise ToolError("流态监测需要连续图片文件夹或 MP4/AVI/MOV/MKV 视频，不接受单张图片。")
    if path.is_dir():
        images = [item for item in path.rglob("*") if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS]
        if not images:
            raise ToolError("文件夹中没有支持的图片。")
        for image in images:
            session.resolve(str(image))
    return path


def save_flow_config(session, request, settings):
    baseline = resolve_source(session, request.baseline_path)
    source = resolve_source(session, request.input_path)
    if baseline == source or baseline in source.parents or source in baseline.parents:
        raise ToolError("正常基线与待测来源必须独立，不能相同或互相包含。")
    frames_per_window = max(1, round(request.fps * request.window_seconds))
    if baseline.is_dir():
        count = sum(item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS for item in baseline.rglob("*"))
        if count < frames_per_window * 3:
            raise ToolError(f"正常基线至少需要 {frames_per_window * 3} 帧（三个完整窗口），当前只有 {count} 帧。")
    config = request.model_dump()
    config.update(config_id=uuid.uuid4().hex[:12], baseline_path=str(baseline), input_path=str(source),
                  model_path=str(local_path(settings.yolo_model_path)), tracker_path=str(local_path(settings.yolo_tracker_path)),
                  confidence=settings.confidence, device=settings.yolo_device, frames_per_window=frames_per_window)
    session.flow_configs[config["config_id"]] = config
    return config


class FlowWarningAdapter:
    def __init__(self, predictor_factory=None):
        self.predictor_factory = predictor_factory
        self.load_lock = threading.Lock()
        self.modules = None
        self.source_hash = None

    def load(self, tracker_path):
        root = local_path(tracker_path)
        files = ["flow_warning/__init__.py", "flow_warning/workflow.py", "flow_warning/measurements.py", "flow_warning/rules.py",
                 "bubble_analyzer/__init__.py", "bubble_analyzer/gas_holdup.py", "bubble_analyzer/image_io.py", "bubble_analyzer/inference.py"]
        try:
            contents = {name: (root / name).read_bytes() for name in files}
        except OSError as error:
            raise ToolError("未找到 YOLOTracker 的 flow_warning 模块，请确认原项目已更新。") from error
        digest = hashlib.sha256(b"".join(contents.values())).hexdigest()[:16]
        with self.load_lock:
            if self.modules is not None and self.source_hash == digest:
                return self.modules
            runtime = DATA / "backend" / ("flow_" + digest)
            for name, content in contents.items():
                target = runtime / name
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    target.write_bytes(content)
            for name in list(sys.modules):
                if name in {"flow_warning", "bubble_analyzer"} or name.startswith(("flow_warning.", "bubble_analyzer.")):
                    del sys.modules[name]
            sys.path.insert(0, str(runtime))
            try:
                workflow = importlib.import_module("flow_warning.workflow")
                rules = importlib.import_module("flow_warning.rules")
                self.modules = (workflow, rules)
                self.source_hash = digest
            finally:
                sys.path.remove(str(runtime))
            return self.modules

    def run(self, context, config):
        workflow, rules = self.load(config["tracker_path"])
        resolve_source(context.session, config["baseline_path"])
        resolve_source(context.session, config["input_path"])
        upstream_settings = rules.WarningSettings(fps=config["fps"], pixel_scale=config["mm_per_pixel"],
            **{key: config[key] for key in ("window_seconds", "min_samples", "trigger_windows", "recovery_windows", "threshold")})
        upstream_config = workflow.FlowWarningConfig(
            model_path=config["model_path"], baseline_path=config["baseline_path"], input_path=config["input_path"],
            output_dir=str(context.output_dir / "flow_warning"), settings=upstream_settings,
            roi=workflow.ROI(*(config[key] for key in ("roi_x", "roi_y", "roi_width", "roi_height"))),
            min_area=config["min_area"], max_distance=config["max_distance"], predict_conf=config["confidence"],
            device=config["device"], distance_unit="mm")
        windows = []
        last_progress = 0

        def progress(payload):
            nonlocal last_progress
            phase = payload["phase"]
            now = time.monotonic()
            if payload.get("window"):
                window = payload["window"]
                windows.append(window)
                context.emit("flow_window", {"window": window, "phase": phase,
                    "message": f"{window['start_time']:.2f}–{window['end_time']:.2f} s · {STATE_LABELS[window['state']]}"})
            if phase == "baseline_ready":
                context.emit("progress", {"message": "正常基线已固定，开始待测序列分析", "phase": phase,
                                           "baseline_limits": payload["baseline"]["limits"]})
            elif now - last_progress >= 0.5 or payload.get("window"):
                label = "建立正常基线" if phase == "baseline" else "分析待测序列"
                context.emit("progress", {"message": f"{label} · {payload.get('frame_id', 0)}/{payload.get('total_frames') or '?'} 帧",
                                           "phase": phase})
                last_progress = now

        try:
            if self.predictor_factory:
                summary = workflow.run_flow_warning(upstream_config, progress, context.stop_event, self.predictor_factory)
            else:
                runtime_settings = context.settings.model_copy(update={"yolo_tracker_path": config["tracker_path"],
                    "yolo_model_path": config["model_path"], "confidence": config["confidence"], "yolo_device": config["device"]})
                with yolo.lock:
                    yolo.load(runtime_settings)
                    summary = workflow.run_flow_warning(upstream_config, progress, context.stop_event, lambda _: yolo.predictor)
        except (ValueError, OSError) as error:
            raise ToolError(str(error)) from error
        return self.summarize(context, config, summary, windows)

    def summarize(self, context, config, summary, windows):
        output = Path(summary["output_dir"])
        baseline = summary.get("baseline") or {}
        limits = baseline.get("limits", {})
        state_counts = dict(Counter(window["state"] for window in windows))
        latest = windows[-1] if windows else None
        group_summaries = {}
        for group, label in GROUP_LABELS.items():
            counts = dict(Counter(window["groups"][group]["state"] for window in windows))
            group_summaries[group] = {"label": label, "window_counts": counts,
                "latest_state": latest["groups"][group]["state"] if latest else "insufficient",
                "latest_reason": latest["groups"][group]["reason"] if latest else "未形成完整窗口"}
        quality = {}
        with (output / "frames.csv").open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                phase = quality.setdefault(row["phase"], {"frames": 0, "valid_frames": 0, "invalid_reasons": {}})
                phase["frames"] += 1
                if row["valid"] == "True":
                    phase["valid_frames"] += 1
                else:
                    reasons = phase["invalid_reasons"]
                    reasons[row["reason"]] = reasons.get(row["reason"], 0) + 1
        for phase in quality.values():
            phase["valid_fraction"] = phase["valid_frames"] / phase["frames"] if phase["frames"] else 0
        artifacts = []
        for name, title in (("baseline.json", "正常基线与阈值 · JSON"), ("frames.csv", "逐帧质量 · CSV"),
                            ("tracks.csv", "运动与关联 · CSV"), ("windows.csv", "窗口指标 · CSV"),
                            ("events.json", "预警事件 · JSON"), ("events.csv", "预警事件 · CSV")):
            if (output / name).is_file():
                artifacts.append(context.artifact(output / name, title))
        for metric in ("area_ratio", "d90", "rise_median"):
            if not windows:
                continue
            def draw(axes, metric=metric):
                axes.plot([window["end_time"] for window in windows],
                          [np.nan if window["metrics"][metric] is None else window["metrics"][metric] for window in windows],
                          color="#bd2030", marker="o", markersize=3, label="待测窗口")
                limit = limits.get(metric)
                if limit:
                    axes.axhline(limit["upper"], color="#d5a661", linestyle="--", label="正常上界")
                    if limit["two_sided"]:
                        axes.axhline(limit["lower"], color="#d5a661", linestyle="--", label="正常下界")
                    axes.axhline(limit["center"], color="#769d90", alpha=0.7, label="基线中心")
                axes.set_xlabel("采集时间 (s)")
                axes.set_ylabel(METRICS[metric])
                axes.legend(fontsize=8)
            artifacts.append(save_plot(context, METRICS[metric] + " · 基线比较", draw))
        events = []
        for event in summary["events"]:
            item = dict(event)
            evidence = Path(item.pop("evidence_path", ""))
            if evidence.is_file() and evidence.resolve().is_relative_to(context.output_dir.resolve()):
                item["evidence"] = context.artifact(evidence, f"事件 {item['id']} · 触发证据", "image")
            item["group_label"] = GROUP_LABELS.get(item["group"], item["group"])
            events.append(item)
        previews = [event["evidence"] for event in events[:4] if "evidence" in event]
        if not previews:
            paths = sorted((output / "overlays").glob("*.png"))
            if paths:
                previews = [context.artifact(paths[-1], "待测序列 · 最后一帧覆盖图", "image")]
        artifacts.extend(previews)
        metric_summaries = {}
        for metric in METRICS:
            values = [window["metrics"][metric] for window in windows if window["metrics"][metric] is not None]
            metric_summaries[metric] = {"label": METRICS[metric], "valid_windows": len(values),
                "min": min(values) if values else None, "max": max(values) if values else None,
                "median": float(np.median(values)) if values else None, "baseline": limits.get(metric)}
        return {"status": "partial" if summary["stopped"] else "success", "kind": "flow_warning",
            "config_id": config["config_id"], "config": config, "backend_source_hash": self.source_hash,
            "baseline_frames": summary["baseline_frames"], "processed_frames": summary["processed_frames"],
            "stopped": summary["stopped"], "event_count": len(events), "events": events,
            "latest_state": latest["state"] if latest else "insufficient", "groups": group_summaries,
            "window_count": len(windows), "window_state_counts": state_counts,
            "window_duration_seconds_by_state": {state: sum(window["end_time"] - window["start_time"] for window in windows if window["state"] == state) for state in STATE_LABELS},
            "baseline_limits": limits, "baseline_window_count": baseline.get("window_count", 0),
            "diameter_cutoff_mm": baseline.get("diameter_cutoff"), "metric_summaries": metric_summaries,
            "latest_window": latest, "quality": quality, "artifacts": artifacts,
            "limitations": ["相对正常基线的离线异常监测，阈值未经当前实验危险性验证，不代表流型分类或危险等级。",
                "LLM 仅依据指标和事件做简单状态解释，本次未向模型提供画面，不得声称看到图像。",
                "面积占比为二维 ROI 掩膜比例；重复帧是时间观测，不是独立气泡生成次数。",
                "没有事件不等于正常；数据不足、末尾不完整窗口、停止及序列结束均不等于恢复。",
                "比例 large_fraction/down_fraction 为 0–1，area_ratio 为百分数；向上速度为正。"]}


flow_adapter = FlowWarningAdapter()


def register_flow_tools(registry, backend=None):
    backend = backend or flow_adapter

    @registry.register("使用用户已经确认的 config_id 执行流态监测：正常基线与待测序列的真实 YOLO 分割、窗口指标、持续异常与恢复判定。只接受会话中的流态配置编号；不可猜测基线、帧率或标定。工具返回事件、质量、阈值及图表；完成后解释简单流动状态，不做流型/因果断言。")
    def analyze_flow_warning(context, config_id: str):
        config = context.session.flow_configs.get(config_id)
        if config is None:
            raise ToolError("请先在流态监测页面添加并确认正常基线、待测来源和采集参数。")
        return backend.run(context, config)

    @registry.register("查询已完成流态监测中的某个事件，返回时间、原因、关联指标及证据图链接。只读取已生成的专业结果，不执行视觉大模型复核。")
    def inspect_flow_event(context, result_id: str, event_id: int):
        result = context.result(result_id)
        if result.get("kind") != "flow_warning":
            raise ToolError("该结果不是流态监测结果。")
        event = next((item for item in result["events"] if item["id"] == event_id), None)
        if event is None:
            raise ToolError("找不到该预警事件编号。")
        return {"source_result_id": result_id, "event": event, "metric_summaries": result["metric_summaries"],
                "metric_summary_scope": "whole_sequence（全序列摘要，不能当作仅此事件的统计）",
                "baseline_limits": result["baseline_limits"], "limitations": result["limitations"],
                "artifacts": [event["evidence"]] if event.get("evidence") else []}
