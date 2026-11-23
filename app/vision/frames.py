from pathlib import Path

import cv2
import numpy as np

from .image_io import get_image_list, read_image


class FrameSource:
    def __init__(self, path, image_only=False):
        self.path = Path(path)
        self.images = get_image_list(str(path)) if image_only or self.path.is_dir() else None
        self.video_fps = None
        self.total = len(self.images) if self.images is not None else 0
        if self.images is not None and not self.images:
            raise ValueError(f"没有找到图像：{path}")

    def __iter__(self):
        if self.images is not None:
            for frame_id, path in enumerate(self.images, 1):
                try:
                    frame = read_image(path)
                except (OSError, ValueError, cv2.error):
                    frame = None
                yield frame_id, str(path), frame
            return
        capture = cv2.VideoCapture(str(self.path))
        if not capture.isOpened():
            capture.release()
            raise ValueError(f"无法打开视频：{self.path}")
        self.video_fps = capture.get(cv2.CAP_PROP_FPS)
        self.total = max(0, int(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
        try:
            frame_id = 1
            while True:
                ok, frame = capture.read()
                if not ok:
                    if self.total and frame_id <= self.total:
                        raise ValueError(f"视频在第 {frame_id} 帧提前解码失败，请检查输入文件。")
                    break
                yield frame_id, f"{self.path}#{frame_id}", frame
                frame_id += 1
        finally:
            capture.release()


def read_segmentation(detections, info, shape):
    expected = len(detections) if detections is not None else len(info.get("mask_boxes", ()))
    masks = list(info.get("mask_arrays", ()))
    if not masks:
        for polygon in info.get("mask_polygons", ()):
            mask = np.zeros(shape[:2], dtype=np.uint8)
            if polygon is not None and len(polygon) >= 3:
                points = np.rint(polygon).astype(np.int32).reshape((-1, 1, 2))
                cv2.fillPoly(mask, [points], 1)
            masks.append(mask)
    if (detections is not None and len(masks) != expected) or expected > len(masks):
        return [], "missing_segmentation_masks"
    if any(np.shape(mask) != shape[:2] for mask in masks):
        return [], "invalid_mask_shape"
    if any(not np.any(mask) for mask in masks):
        return [], "missing_segmentation_masks"
    return [np.asarray(mask, dtype=np.uint8) for mask in masks], ""
