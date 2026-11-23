import numpy as np
from scipy.optimize import linear_sum_assignment

try:
    import lap
except ImportError:
    lap = None

try:
    from cython_bbox import bbox_overlaps as bbox_ious
except ImportError:
    bbox_ious = None


def linear_assignment(cost_matrix, thresh):
    if cost_matrix.size == 0:
        return np.empty((0, 2), dtype=int), tuple(range(cost_matrix.shape[0])), tuple(range(cost_matrix.shape[1]))
    if lap is None:
        row_count, column_count = cost_matrix.shape
        allowed = np.where(cost_matrix <= thresh, cost_matrix, np.inf)
        unmatched_cost = np.nextafter(thresh, np.inf)
        padded = np.concatenate((allowed, np.full((row_count, row_count), unmatched_cost)), axis=1)
        rows, columns = linear_sum_assignment(padded)
        matched = columns < column_count
        matched_rows, matched_columns = rows[matched], columns[matched]
        return (np.column_stack((matched_rows, matched_columns)), rows[~matched],
                np.setdiff1d(np.arange(column_count), matched_columns))
    _, row_matches, column_matches = lap.lapjv(cost_matrix, extend_cost=True, cost_limit=thresh)
    matched_rows = np.flatnonzero(row_matches >= 0)
    return (np.column_stack((matched_rows, row_matches[matched_rows])),
            np.flatnonzero(row_matches < 0), np.flatnonzero(column_matches < 0))


def ious(atlbrs, btlbrs):
    """
    Compute cost based on IoU
    :type atlbrs: list[tlbr] | np.ndarray
    :type atlbrs: list[tlbr] | np.ndarray

    :rtype ious np.ndarray
    """
    ious = np.zeros((len(atlbrs), len(btlbrs)), dtype=np.float64)
    if ious.size == 0:
        return ious

    if bbox_ious is not None:
        ious = bbox_ious(
            np.ascontiguousarray(atlbrs, dtype=np.float64),
            np.ascontiguousarray(btlbrs, dtype=np.float64)
        )
        return ious

    atlbrs = np.ascontiguousarray(atlbrs, dtype=np.float64)
    btlbrs = np.ascontiguousarray(btlbrs, dtype=np.float64)
    area_a = np.maximum(0.0, atlbrs[:, 2] - atlbrs[:, 0]) * np.maximum(0.0, atlbrs[:, 3] - atlbrs[:, 1])
    area_b = np.maximum(0.0, btlbrs[:, 2] - btlbrs[:, 0]) * np.maximum(0.0, btlbrs[:, 3] - btlbrs[:, 1])

    for i, a in enumerate(atlbrs):
        xx1 = np.maximum(a[0], btlbrs[:, 0])
        yy1 = np.maximum(a[1], btlbrs[:, 1])
        xx2 = np.minimum(a[2], btlbrs[:, 2])
        yy2 = np.minimum(a[3], btlbrs[:, 3])
        inter_w = np.maximum(0.0, xx2 - xx1)
        inter_h = np.maximum(0.0, yy2 - yy1)
        inter = inter_w * inter_h
        union = area_a[i] + area_b - inter
        valid = union > 0
        ious[i, valid] = inter[valid] / union[valid]

    return ious


def iou_distance(atracks, btracks):
    """
    Compute cost based on IoU
    :type atracks: list[STrack]
    :type btracks: list[STrack]

    :rtype cost_matrix np.ndarray
    """

    if (len(atracks)>0 and isinstance(atracks[0], np.ndarray)) or (len(btracks) > 0 and isinstance(btracks[0], np.ndarray)):
        atlbrs = atracks
        btlbrs = btracks
    else:
        atlbrs = [track.tlbr for track in atracks]
        btlbrs = [track.tlbr for track in btracks]
    _ious = ious(atlbrs, btlbrs)
    cost_matrix = 1 - _ious

    return cost_matrix
