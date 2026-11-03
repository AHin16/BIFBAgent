import hashlib
import importlib.util
import math
import os
import shutil
import sys
import threading

import cv2
import numpy as np
import pandas as pd

from app.analysis import describe, distribution
from app.config import DATA, IMAGE_EXTENSIONS, local_path
from app.storage import ToolError


class YoloAdapter:
    def __init__(self):
        self.lock = threading.Lock()
        self.predictor = None
        self.key = None
        self.source_hash = None
        self.image_io = None

    def load_module(self, name, source, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        spec = importlib.util.spec_from_file_location(name, destination)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    def load(self, settings):
        root = local_path(settings.yolo_tracker_path)
        weights = local_path(settings.yolo_model_path)
        predictor_source = root / "detector_head/yolo11/predictor_yolo11.py"
        image_source = root / "bubble_analyzer/image_io.py"
        if not predictor_source.is_file() or not image_source.is_file():
            raise ToolError("未找到 YOLOTracker 推理模块，请在设置中填写原项目目录。")
        if not weights.is_file():
            raise ToolError("YOLO 权重不存在，请在设置中选择气泡模型，例如 YOLOTracker/3900.pt。")
        source_hash = hashlib.sha256(predictor_source.read_bytes() + image_source.read_bytes()).hexdigest()[:16]
        key = (str(root), str(weights), weights.stat().st_mtime_ns, source_hash,
               settings.yolo_device, settings.confidence)
        if key == self.key:
            return
        runtime = DATA / "backend" / source_hash
        os.environ["YOLO_CONFIG_DIR"] = str(DATA / "ultralytics")
        predictor_module = self.load_module("bifb_predictor_" + source_hash, predictor_source,
                                            runtime / "detector_head/yolo11/predictor_yolo11.py")
        self.image_io = self.load_module("bifb_image_io_" + source_hash, image_source,
                                        runtime / "bubble_analyzer/image_io.py")
        self.predictor = predictor_module.PredictorYolo11(
            model_path=str(weights), input_size=(640, 640), conf_threshold=settings.confidence,
            iou_threshold=0.45, device=settings.yolo_device, high_quality_segmentation=True)
        self.key = key
        self.source_hash = source_hash

    def detect(self, context, path, group="default"):
        with self.lock:
            self.load(context.settings)
            image = self.image_io.read_image(str(path))
            if image is None:
                raise ToolError(f"无法读取图片：{path.name}，请检查文件是否损坏。")
            detections, info = self.predictor.predict(image)
            rows = detections.detach().cpu().numpy() if detections is not None else np.empty((0, 6))
            masks = info.get("mask_arrays", [])
            names = dict(self.predictor.model.names)
            backend_hash = self.source_hash
        scale = context.settings.mm_per_pixel
        unit = "mm" if scale is not None else "px"
        measurements = []
        overlay = image.copy()
        methods = set()
        for index, detection in enumerate(rows):
            left, top, right, bottom = map(float, detection[:4])
            confidence = float(detection[4])
            class_id = int(detection[5])
            width, height = max(0, right - left), max(0, bottom - top)
            if index < len(masks) and np.any(masks[index]):
                mask = masks[index].astype(bool)
                area = float(np.count_nonzero(mask))
                method = "segmentation_mask_equivalent_circle"
                color = np.array([136, 185, 38], dtype=np.uint8)
                overlay[mask] = (overlay[mask] * 0.7 + color * 0.3).astype(np.uint8)
                contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                cv2.drawContours(overlay, contours, -1, (120, 205, 50), 1)
            else:
                area = width * height
                method = "bounding_box_area_equivalent_circle_estimate"
            methods.add(method)
            diameter_px = 2 * math.sqrt(area / math.pi)
            measurements.append({"image": path.name, "source": str(path), "group": group,
                                 "bubble_id": index + 1, "class_id": class_id,
                                 "class_name": names.get(class_id, str(class_id)), "confidence": confidence,
                                 "bbox_xyxy": [left, top, right, bottom], "width_px": width, "height_px": height,
                                 "area_px2": area, "diameter_px": diameter_px,
                                 "diameter": diameter_px * (scale if scale is not None else 1),
                                 "unit": unit, "method": method})
            cv2.rectangle(overlay, (int(left), int(top)), (int(right), int(bottom)), (130, 190, 45), 1)
            cv2.putText(overlay, f"{index + 1} {confidence:.2f}", (int(left), max(14, int(top) - 3)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, (70, 135, 20), 1, cv2.LINE_AA)
        output_path = context.output(path.stem + "_detected.png")
        preview_path = context.output(path.stem + "_original.png")
        self.image_io.write_image(str(output_path), overlay)
        self.image_io.write_image(str(preview_path), image)
        return {"source": str(path), "bubble_count": len(measurements), "unit": unit,
                "mean_confidence": float(np.mean([row["confidence"] for row in measurements])) if measurements else None,
                "statistics": describe([row["diameter"] for row in measurements]),
                "measurement_method": sorted(methods), "measurements": measurements,
                "model": str(local_path(context.settings.yolo_model_path)), "model_classes": names,
                "backend": "YOLOTracker.PredictorYolo11", "backend_source_hash": backend_hash,
                "confidence_threshold": context.settings.confidence, "mm_per_pixel": scale,
                "artifacts": [context.artifact(preview_path, path.name + " · 原图", "image"),
                              context.artifact(output_path, path.name + " · 检测结果", "image")],
                "limitations": ["尺寸为二维等效圆直径；掩膜缺失时使用检测框面积估计，详见 method。",
                                "边缘截断、重叠及分割误差会影响测量；未剔除边缘气泡。",
                                "未设置长度标定，仅报告 px。" if scale is None else f"使用用户标定 {scale} mm/px。",
                                "跨帧汇总为检测次数，不是去重后的独立气泡数。"]}


adapter = YoloAdapter()


def export_measurements(context, result):
    path = context.output("bubble_measurements.csv")
    columns = ["image", "source", "group", "bubble_id", "class_id", "class_name", "confidence",
               "bbox_xyxy", "width_px", "height_px", "area_px2", "diameter_px", "diameter", "unit", "method"]
    pd.DataFrame(result["measurements"], columns=columns).to_csv(path, index=False, encoding="utf-8-sig")
    result["artifacts"].append(context.artifact(path, "逐气泡测量 · CSV"))
    charts, histogram = distribution(context, [row["diameter"] for row in result["measurements"]], result["unit"])
    result["artifacts"].extend(charts)
    result["distribution"] = histogram
    return result


def register_vision_tools(registry):
    @registry.register("对已添加的单张气泡图像调用真实 YOLOTracker 模型，输出分割检测图、数量、置信度、等效直径、分布图和 CSV。物理尺寸仅使用设置中的用户标定；未标定用 px。")
    def detect_bubbles(context, image_path: str):
        path = context.session.resolve(image_path)
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            raise ToolError("单图检测需要图片文件。")
        return export_measurements(context, adapter.detect(context, path))

    @registry.register("递归检测已添加的图片文件夹，按相对父目录识别实验组，输出逐图/逐气泡 CSV、尺寸分布和分组统计。总数是跨帧检测次数，不是独立气泡数。最多 500 张，超限会提示拆分。")
    def batch_detect_bubbles(context, folder_path: str):
        folder = context.session.resolve(folder_path, folder=True)
        paths = []
        for path in folder.rglob("*"):
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS and not path.resolve().is_relative_to(DATA / "outputs"):
                paths.append(path)
                if len(paths) > 500:
                    raise ToolError("文件夹超过 500 张图片，请拆分批次后分析。")
        paths.sort()
        if not paths:
            raise ToolError("文件夹中没有支持的图片。")
        records, measurements, artifacts, errors = [], [], [], []
        methods = set()
        for index, path in enumerate(paths):
            context.emit("progress", {"message": f"YOLO 正在处理 {index + 1}/{len(paths)} · {path.name}",
                                      "completed": index, "total": len(paths)})
            try:
                context.session.resolve(str(path))
                group = str(path.parent.relative_to(folder))
                result = adapter.detect(context, path, group if group != "." else "default")
                measurements.extend(result["measurements"])
                methods.update(result["measurement_method"])
                records.append({"image": str(path.relative_to(folder)), "group": group,
                                "bubble_count": result["bubble_count"], "mean_confidence": result["mean_confidence"],
                                "mean_diameter": result["statistics"]["mean"], "unit": result["unit"]})
                if len(records) <= 6:
                    artifacts.extend(result["artifacts"])
            except ToolError as error:
                errors.append({"image": str(path), "message": str(error)})
        if not records:
            raise ToolError("全部图片处理失败。" + (errors[0]["message"] if errors else "请查看日志。"))
        summary_path = context.output("per_image.csv")
        pd.DataFrame(records).to_csv(summary_path, index=False, encoding="utf-8-sig")
        artifacts.append(context.artifact(summary_path, "逐图片统计 · CSV"))
        unit = "mm" if context.settings.mm_per_pixel is not None else "px"
        groups = []
        if measurements:
            frame = pd.DataFrame(measurements)
            for group, subset in frame.groupby("group"):
                groups.append({"group": group, "statistics": describe(subset["diameter"])})
        return export_measurements(context, {
            "status": "partial" if errors else "success", "source": str(folder), "image_count": len(paths),
            "processed_count": len(records), "failed_count": len(errors), "errors": errors,
            "bubble_count": len(measurements), "unit": unit, "measurements": measurements,
            "statistics": describe([row["diameter"] for row in measurements]), "groups": groups,
            "mean_confidence": float(np.mean([row["confidence"] for row in measurements])) if measurements else None,
            "per_image": records, "measurement_method": sorted(methods), "artifacts": artifacts,
            "mm_per_pixel": context.settings.mm_per_pixel, "model": context.settings.yolo_model_path,
            "confidence_threshold": context.settings.confidence, "backend_source_hash": adapter.source_hash,
            "limitations": ["按相对父目录分组，未从文件名猜测气速；无子目录时视为同一组。",
                            "跨帧总数是检测次数，未做跟踪去重；二维等效圆直径不等同三维直径。",
                            "未设置长度标定，仅报告 px。" if unit == "px" else "物理尺寸依赖用户标定。",
                            "页面展示前 6 张预览；全部检测图保存在本次 data/outputs 目录。"]})

    @registry.register("列出已添加文件夹中的图片和 CSV，了解实验目录结构；不读取未授权的数据源。")
    def list_files(context, folder_path: str):
        folder = context.session.resolve(folder_path, folder=True)
        files = []
        for path in folder.rglob("*"):
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS | {".csv"}:
                files.append({"path": str(path), "relative_path": str(path.relative_to(folder)),
                              "kind": "csv" if path.suffix.lower() == ".csv" else "image"})
                if len(files) >= 200:
                    return {"files": files, "truncated": True, "message": "仅列出前 200 个文件。"}
        return {"files": files, "truncated": False}
