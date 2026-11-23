import cv2
import numpy as np


def get_color(idx):
    idx = idx * 3
    color = ((37 * idx) % 255, (17 * idx) % 255, (29 * idx) % 255)

    return color


def _get_track_color(track_id):
    hue = (abs(int(track_id)) * 0.618033988749895) % 1.0
    hsv = np.uint8([[[int(hue * 179), 220, 255]]])
    bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0, 0]
    return tuple(int(channel) for channel in bgr)


def _draw_bubble_shape(canvas, tlwh, polygon=None, color=255, thickness=-1):
    if polygon is not None and len(polygon) >= 3:
        points = np.round(np.asarray(polygon, dtype=np.float32)).astype(np.int32).reshape(-1, 1, 2)
        if thickness < 0:
            cv2.fillPoly(canvas, [points], color, lineType=cv2.LINE_AA)
        else:
            cv2.polylines(canvas, [points], True, color, thickness=thickness, lineType=cv2.LINE_AA)
        return

    x1, y1, w, h = tlwh
    center = (int(round(x1 + w / 2.0)), int(round(y1 + h / 2.0)))
    axes = (max(1, int(round(w / 2.0))), max(1, int(round(h / 2.0))))
    cv2.ellipse(canvas, center, axes, 0, 0, 360, color, thickness, lineType=cv2.LINE_AA)


def _draw_trajectory(result, trajectory, color, thickness):
    if trajectory is None or len(trajectory) < 2:
        return

    points = np.round(np.asarray(trajectory, dtype=np.float32)).astype(np.int32).reshape(-1, 1, 2)
    cv2.polylines(
        result,
        [points],
        False,
        (255, 255, 255),
        thickness=max(thickness + 2, 2),
        lineType=cv2.LINE_AA,
    )
    cv2.polylines(
        result,
        [points],
        False,
        color,
        thickness=thickness,
        lineType=cv2.LINE_AA,
    )


def plot_tracking(
    image,
    tlwhs,
    obj_ids,
    scores=None,
    frame_id=0,
    fps=0.,
    ids2=None,
    mask_polygons=None,
    trajectories=None,
    centers=None,
    speeds=None,
    show_speed_text=False,
    speed_unit="unit",
    mode="mask",
    sample_validity=None,
):
    if mode == "box":
        im = np.ascontiguousarray(np.copy(image))
        text_scale = 2
        text_thickness = 2
        line_thickness = 3

        cv2.putText(
            im,
            "frame: %d fps: %.2f num: %d" % (frame_id, fps, len(tlwhs)),
            (0, int(15 * text_scale)),
            cv2.FONT_HERSHEY_PLAIN,
            2,
            (0, 0, 255),
            thickness=2,
        )

        for i, tlwh in enumerate(tlwhs):
            x1, y1, w, h = tlwh
            intbox = tuple(map(int, (x1, y1, x1 + w, y1 + h)))
            obj_id = int(obj_ids[i])
            id_text = "{}".format(int(obj_id))
            if ids2 is not None:
                id_text = id_text + ", {}".format(int(ids2[i]))
            color = get_color(abs(obj_id))
            cv2.rectangle(im, intbox[0:2], intbox[2:4], color=color, thickness=line_thickness)
            cv2.putText(
                im,
                id_text,
                (intbox[0], intbox[1]),
                cv2.FONT_HERSHEY_PLAIN,
                text_scale,
                (0, 0, 255),
                thickness=text_thickness,
            )
        return im

    mask_polygons = mask_polygons or []
    trajectories = trajectories or []
    centers = centers or []
    speeds = speeds or []
    sample_validity = [True] * len(tlwhs) if sample_validity is None else sample_validity
    filtered_indices = [index for index in range(len(tlwhs))
                        if index < len(sample_validity) and not sample_validity[index]]
    fill_alpha = 0.18
    outline_thickness = max(2, int(round(min(image.shape[:2]) / 320.0)))
    trajectory_thickness = max(2, outline_thickness)
    background = np.ascontiguousarray(np.copy(image))
    if filtered_indices:
        muted = background.copy()
        gray = (160, 160, 160)
        for index in filtered_indices:
            polygon = mask_polygons[index] if index < len(mask_polygons) else None
            bubble_mask = np.zeros(image.shape[:2], dtype=np.uint8)
            _draw_bubble_shape(bubble_mask, tlwhs[index], polygon=polygon)
            mask = bubble_mask > 0
            muted[mask] = muted[mask] * .76 + np.asarray(gray) * .24
            _draw_bubble_shape(muted, tlwhs[index], polygon=polygon, color=gray,
                               thickness=outline_thickness)
            trajectory = trajectories[index] if index < len(trajectories) else None
            if trajectory is not None and len(trajectory) >= 2:
                points = np.round(np.asarray(trajectory, dtype=np.float32)).astype(np.int32).reshape(-1, 1, 2)
                cv2.polylines(muted, [points], False, gray, trajectory_thickness, cv2.LINE_AA)
            center = centers[index] if index < len(centers) else None
            if center is not None:
                center_point = tuple(int(round(value)) for value in center)
                cv2.circle(muted, center_point, max(trajectory_thickness, 2), gray, -1, cv2.LINE_AA)
                if show_speed_text:
                    obj_id = int(obj_ids[index]) if index < len(obj_ids) else index + 1
                    cv2.putText(muted, f"ID {obj_id}",
                                (center_point[0] + 8, max(center_point[1] - 8, 18)),
                                cv2.FONT_HERSHEY_SIMPLEX, .5, gray, 1, cv2.LINE_AA)
        background = cv2.addWeighted(background, .75, muted, .25, 0)
    im = background.astype(np.float32)
    outline = np.zeros_like(image, dtype=np.uint8)

    for i, tlwh in enumerate(tlwhs):
        if i < len(sample_validity) and not sample_validity[i]:
            continue
        obj_id = int(obj_ids[i]) if i < len(obj_ids) else i + 1
        color = np.array(_get_track_color(obj_id), dtype=np.float32)
        polygon = mask_polygons[i] if i < len(mask_polygons) else None
        bubble_mask = np.zeros(image.shape[:2], dtype=np.uint8)

        _draw_bubble_shape(bubble_mask, tlwh, polygon=polygon, color=255, thickness=-1)
        if not np.any(bubble_mask):
            continue

        mask = bubble_mask > 0
        im[mask] = im[mask] * (1.0 - fill_alpha) + color * fill_alpha
        _draw_bubble_shape(
            outline,
            tlwh,
            polygon=polygon,
            color=tuple(int(channel) for channel in color),
            thickness=outline_thickness,
        )

    result = np.clip(im, 0, 255).astype(np.uint8)
    outline_mask = np.any(outline > 0, axis=2)
    result[outline_mask] = outline[outline_mask]

    for i, _ in enumerate(tlwhs):
        if i < len(sample_validity) and not sample_validity[i]:
            continue
        obj_id = int(obj_ids[i]) if i < len(obj_ids) else i + 1
        color = _get_track_color(obj_id)
        trajectory = trajectories[i] if i < len(trajectories) else None
        center = centers[i] if i < len(centers) else None
        speed = speeds[i] if i < len(speeds) else 0.0

        _draw_trajectory(result, trajectory, color, trajectory_thickness)

        if center is not None:
            center_point = tuple(int(round(value)) for value in center)
            cv2.circle(
                result,
                center_point,
                max(trajectory_thickness + 2, 4),
                (255, 255, 255),
                thickness=-1,
                lineType=cv2.LINE_AA,
            )
            cv2.circle(
                result,
                center_point,
                max(trajectory_thickness, 2),
                color,
                thickness=-1,
                lineType=cv2.LINE_AA,
            )

            if show_speed_text:
                text = f"ID {obj_id}"
                if speed is not None:
                    text += f"  {speed:.2f} {speed_unit}/s"
                text_origin = (center_point[0] + 8, max(center_point[1] - 8, 18))
                cv2.putText(
                    result,
                    text,
                    text_origin,
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 255, 255),
                    thickness=2,
                    lineType=cv2.LINE_AA,
                )
                cv2.putText(
                    result,
                    text,
                    text_origin,
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    color,
                    thickness=1,
                    lineType=cv2.LINE_AA,
                )

    return result
