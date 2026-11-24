"""Agent tools for calibrated holdup and time-resolved bubble tracking."""

import time
from typing import Annotated, Literal
from zipfile import ZipFile

from pydantic import Field

from app.analysis import describe, save_plot
from app.config import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, local_path
from app.storage import ToolError
from app.vision import source_hash
from app.vision.gas_holdup import ROI
from app.vision.tracking import SEQUENCE_CONFIDENCE, TRACKER_SOURCES
from app.yolo_adapter import adapter as yolo


Positive = Annotated[float, Field(gt=0)]
Pixels = Annotated[int, Field(ge=0)]
AcquisitionFps = Annotated[float, Field(gt=0, le=100000)]


def resolve_source(context, source_path, extensions):
    path = local_path(source_path)
    path = context.session.resolve(str(path), folder=path.is_dir())
    if path.is_file() and path.suffix.lower() not in extensions:
        raise ToolError("输入类型不匹配，请添加支持的图片、视频或对应实验文件夹。")
    if path.is_dir():
        if context.output_dir.resolve().is_relative_to(path):
            raise ToolError("请选择具体的实验数据目录，分析输出须位于输入目录之外。")
        images = [item for item in path.rglob("*") if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS]
        if not images:
            raise ToolError("文件夹中没有支持的图片。")
        for image in images:
            context.session.resolve(str(image))
    return path


def progress_reporter(context, label):
    last = 0.0

    def emit(index, total):
        nonlocal last
        now = time.monotonic()
        if index == total or now - last >= 0.5:
            context.emit("progress", {"message": f"{label} · {index}/{total or '?'} 帧",
                                      "processed": index, "total": total or None})
            last = now

    return emit


def register_sequence_tools(registry):
    @registry.register("用分割掩膜和等效球模型估算体积气含率，支持已添加的单图或图片目录。必须提供用户确认的视野深度 view_depth_mm；空间标定可使用运行设置中的 mm_per_pixel，缺失时询问。输出分别包含二维掩膜面积占比及三维体积分数，单位均为百分数。")
    def estimate_gas_holdup(context, source_path: str, view_depth_mm: Positive, mm_per_pixel: Positive | None = None,
                            roi_x: Pixels = 0, roi_y: Pixels = 0, roi_width: Pixels = 0, roi_height: Pixels = 0,
                            edge_policy: Literal["include", "exclude", "weighted"] = "include", min_area: Pixels = 10):
        from app.vision.gas_holdup_workflow import run_gas_holdup

        scale = mm_per_pixel if mm_per_pixel is not None else context.settings.mm_per_pixel
        if scale is None:
            raise ToolError("请提供实际空间标定（mm/px），或在运行设置中保存标定。")
        path = resolve_source(context, source_path, IMAGE_EXTENSIONS)
        roi = ROI(roi_x, roi_y, roi_width, roi_height)
        output = context.output("gas_holdup")
        try:
            with yolo.lock:
                yolo.load(context.settings)
                samples, errors, previews, csv_file, stopped, total = run_gas_holdup(
                    path, output, yolo.predictor, scale, view_depth_mm, roi, edge_policy, min_area,
                    context.stop_event, progress_reporter(context, "测算气含率"),
                )
                backend_source_hash = source_hash("gas_holdup.py", "gas_holdup_workflow.py",
                                                  "frames.py", "predictor.py", "image_io.py")
        except (ValueError, OSError) as error:
            raise ToolError(str(error)) from error
        artifacts = [context.artifact(csv_file, "逐帧气含率 · CSV")]
        artifacts.extend(context.artifact(preview, f"第 {int(preview.stem)} 帧 · 分割覆盖图", "image") for preview in previews)
        if len(samples) > len(previews):
            archive = output / "overlays.zip"
            with ZipFile(archive, "w") as package:
                for row in samples:
                    filename = f"{row['frame']:06d}.png"
                    package.write(output / "overlays" / filename, filename)
            artifacts.append(context.artifact(archive, "全部分割覆盖图 · ZIP"))
        if len(samples) > 1:
            def draw(axes):
                for key, label in (("gas_holdup_percent", "等效球体积气含率"), ("bubble_area_ratio_percent", "二维面积占比")):
                    by_frame = {row["frame"]: row[key] for row in samples}
                    indexes = range(1, len(samples) + len(errors) + 1)
                    axes.plot(indexes, [by_frame.get(index, float("nan")) for index in indexes], marker=".", label=label)
                axes.set_xlabel("输入顺序")
                axes.set_ylabel("%")
                axes.legend()
            artifacts.append(save_plot(context, "逐帧气含率与二维面积占比", draw))
        status = "partial" if stopped or errors else "success"
        return {
            "status": status, "kind": "gas_holdup", "source": str(path), "stopped": stopped,
            "total_frames": total, "valid_frames": len(samples), "invalid_frames": len(errors),
            "invalid_examples": errors[:12], "mm_per_pixel": scale, "view_depth_mm": view_depth_mm,
            "roi": {"x": roi_x, "y": roi_y, "width": roi_width, "height": roi_height},
            "edge_policy": edge_policy, "min_mask_area_px2": min_area, "confidence_threshold": context.settings.confidence,
            "model": str(local_path(context.settings.yolo_model_path)),
            "backend_source_hash": backend_source_hash, "method": "equivalent_sphere_volume",
            "gas_holdup_percent": describe([row["gas_holdup_percent"] for row in samples]),
            "bubble_area_ratio_percent": describe([row["bubble_area_ratio_percent"] for row in samples]),
            "frames": samples[:12], "raw_rows": samples + errors, "artifacts": artifacts,
            "limitations": ["体积基于等效球假设，视野深度、标定、遮挡和截断都会影响估算。",
                            "二维面积按 ROI 掩膜并集计算，体积对每个有效实例求和。汇总均值按有效帧等权。",
                            "weighted 与 include 均按 ROI 内可见面积计算。缺失掩膜或无效帧从统计中排除。"],
        }

    @registry.register("查看已有气含率结果中指定编号的原始帧数据，包括体积、二维占比、气泡数量、直径和无效原因。无需重跑 YOLO。")
    def inspect_gas_holdup_frame(context, result_id: str, frame: Annotated[int, Field(ge=1)]):
        result = context.result(result_id)
        if result.get("kind") != "gas_holdup":
            raise ToolError("请选择气含率估算结果。")
        rows = result.get("raw_rows", result["frames"] + result["invalid_examples"])
        row = next((item for item in rows if item["frame"] == frame), None)
        if row is None:
            raise ToolError(f"气含率结果中没有第 {frame} 帧的数据。")
        return {"source_result_id": result_id, "frame_metrics": row, "series_summary": result["gas_holdup_percent"],
                "limitations": result["limitations"][:2]}

    @registry.register("对会话中已添加的连续图像文件夹或本地视频进行气泡追踪，导出轨迹、运动 CSV、标注 MP4 和预览。图像目录必须提供用户给出的实际采集帧率 fps；视频优先使用用户给出的帧率，否则读取文件帧率。未标定时报告 px/s。")
    def track_bubbles(context, source_path: str, fps: AcquisitionFps | None = None,
                      mm_per_pixel: Positive | None = None, min_track_frames: Annotated[int, Field(ge=2)] = 5,
                      edge_margin_px: Pixels = 0):
        from app.vision.tracking.workflow import run_tracking

        path = resolve_source(context, source_path, VIDEO_EXTENSIONS)
        if path.is_dir() and fps is None:
            raise ToolError("请提供图像序列的实际采集帧率。")
        scale = mm_per_pixel if mm_per_pixel is not None else context.settings.mm_per_pixel
        settings = context.settings.model_copy(update={"confidence": SEQUENCE_CONFIDENCE})
        try:
            with yolo.lock:
                yolo.load(settings)
                summary, paths = run_tracking(
                    path, context.output("tracking"), yolo.predictor, fps, scale, min_track_frames, edge_margin_px,
                    context.stop_event, progress_reporter(context, "追踪连续气泡"),
                )
        except (ValueError, OSError) as error:
            raise ToolError(str(error)) from error
        artifacts = []
        for path_file, title, kind in zip(paths, ("逐帧轨迹 · CSV", "气泡运动 · CSV", "追踪预览", "标注视频 · MP4"),
                                          ("file", "file", "image", "file")):
            if path_file.is_file():
                artifacts.append(context.artifact(path_file, title, kind))
        return {
            **summary, "status": "partial" if summary["stopped"] or summary["invalid_frames"] else "success",
            "kind": "bubble_tracking", "source": str(path), "mm_per_pixel": scale,
            "min_track_frames": min_track_frames, "edge_margin_px": edge_margin_px,
            "confidence_threshold": SEQUENCE_CONFIDENCE, "tracking_method": "BubbleBoTSORT",
            "model": str(local_path(settings.yolo_model_path)),
            "backend_source_hash": source_hash(*TRACKER_SOURCES, "tracking/workflow.py", "tracking/motion.py",
                                              "tracking/render.py", "frames.py", "predictor.py", "image_io.py"),
            "artifacts": artifacts,
            "limitations": ["追踪适用于固定相机和等间隔连续采集。请按实际采集或抽帧后的帧率解释速度。",
                            "轨迹 ID 数可能受漏检、重连和边界影响。运动统计使用通过成熟度、边缘和转角筛选的逐帧观测。",
                            "向上运动的 vy 为负，rise_speed 以向上为正且下行记为零。"],
        }
