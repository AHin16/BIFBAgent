from itertools import count

import numpy as np

from . import matching
from .basetrack import TrackState
from .kalman_filter import KalmanFilter
from .track import STrack


class _BubbleTrack(STrack):
    def __init__(self, tlwh, score, ids):
        super().__init__(tlwh, score)
        self.ids = ids

    def next_id(self):
        return next(self.ids)


class BubbleBoTSORT:
    """Associate deforming bubbles using observed image motion and box shape."""

    def __init__(self, high=0.6, low=0.1, new=0.7, match=0.8, max_lost_frames=3, ambiguity_margin=0.0):
        self.track_high_thresh = high
        self.track_low_thresh = low
        self.new_track_thresh = new
        self.match_thresh = match
        self.max_time_lost = max_lost_frames
        self.ambiguity_margin = ambiguity_margin
        self.kalman_filter = KalmanFilter()
        self.ids = count(1)
        self.frame_id = 0
        self.reset()

    def reset(self):
        self.tracked_stracks = []
        self.lost_stracks = []

    def _observe(self, track, detection):
        box = detection.tlwh.copy()
        observation = STrack.tlwh_to_xywh(box)
        prior = getattr(track, "bubble_observation", None)
        velocity = getattr(track, "bubble_velocity", None)
        if prior is not None:
            elapsed = max(self.frame_id - track.bubble_frame, 1)
            measured = (observation[:2] - prior[:2]) / elapsed
            limits = [self.frame_shape[1], self.frame_shape[0]]
            for axis, limit in enumerate(limits):
                prior_edges = prior[axis] + np.array([-.5, .5]) * prior[axis+2]
                current_edges = observation[axis] + np.array([-.5, .5]) * observation[axis+2]
                if min(prior_edges[0], current_edges[0]) <= 1:
                    measured[axis] = (current_edges[1] - prior_edges[1]) / elapsed
                elif max(prior_edges[1], current_edges[1]) >= limit-1:
                    measured[axis] = (current_edges[0] - prior_edges[0]) / elapsed
            velocity = measured if velocity is None else .7 * measured + .3 * velocity
        track.bubble_observation = observation
        track.bubble_velocity = velocity
        track.bubble_frame = self.frame_id
        track.bubble_detection_index = detection.bubble_detection_index
        track.bubble_ambiguous_match = getattr(detection, "bubble_ambiguous_match", False)
        track.mean[:4] = observation
        track.mean[4:6] = velocity if velocity is not None else 0
        track.mean[6:] = 0

    def _predict(self, tracks):
        STrack.multi_predict(tracks)
        for track in tracks:
            observation = track.bubble_observation
            elapsed = self.frame_id - track.bubble_frame
            track.mean[:4] = observation
            if track.bubble_velocity is not None:
                track.mean[:2] += track.bubble_velocity * elapsed
            track.mean[6:] = 0

    def _distances(self, tracks, detections):
        costs = matching.iou_distance(tracks, detections)
        for track_index, track in enumerate(tracks):
            prior = track.mean[:4].copy()
            height, width = self.frame_shape
            top_left = np.maximum(prior[:2] - prior[2:] / 2, 0)
            bottom_right = np.minimum(prior[:2] + prior[2:] / 2, [width, height])
            prior[:2] = (top_left + bottom_right) / 2
            prior[2:] = np.maximum(bottom_right - top_left, 1.)
            normalizer = max(float(np.sqrt(prior[2] * prior[3])), 1.)
            known_velocity = track.bubble_velocity is not None
            for detection_index, detection in enumerate(detections):
                observed = STrack.tlwh_to_xywh(detection.tlwh)
                ratios = observed[2:] / np.maximum(prior[2:], 1.)
                motion = float(np.linalg.norm(observed[:2] - prior[:2])) / normalizer
                shape = float(np.abs(np.log(np.maximum(ratios, 1e-6))).sum())
                if (ratios.min() < .4 or ratios.max() > 2.5
                        or motion > (.8 if known_velocity else 1.25)):
                    costs[track_index, detection_index] = 1e6
                else:
                    costs[track_index, detection_index] = (
                        .5 * motion + .4 * min(shape, 1.5)
                        + .1 * costs[track_index, detection_index]
                    )
        return costs

    def _associate(self, tracks, detections, threshold):
        costs = self._distances(tracks, detections)
        pairs, unmatched_tracks, unmatched_detections = matching.linear_assignment(costs, threshold)
        for track_index, detection_index in pairs:
            track = tracks[track_index]
            detection = detections[detection_index]
            margin = self.ambiguity_margin
            if margin > 0:
                alternatives = np.concatenate((np.delete(costs[track_index], detection_index),
                                               np.delete(costs[:, detection_index], track_index)))
                detection.bubble_ambiguous_match = bool(np.any(
                    alternatives <= min(costs[track_index, detection_index] + margin, threshold)))
            if track.state == TrackState.Lost:
                track.re_activate(detection, self.frame_id, new_id=False)
            else:
                track.update(detection, self.frame_id)
            self._observe(track, detection)
        return ([tracks[index] for index in unmatched_tracks],
                [detections[index] for index in unmatched_detections])

    def update(self, output_results, img):
        self.frame_id += 1
        self.frame_shape = img.shape[:2]
        values = detection_rows(output_results)
        high, low = [], []
        for detection_index, detection in enumerate(values):
            score = float(detection[4] * detection[5] if len(detection) == 7 else detection[4])
            if score <= self.track_low_thresh:
                continue
            candidate = _BubbleTrack(STrack.tlbr_to_tlwh(detection[:4]), score, self.ids)
            candidate.bubble_detection_index = detection_index
            (high if score >= self.track_high_thresh else low).append(candidate)

        unconfirmed = [track for track in self.tracked_stracks if not track.is_activated]
        active = [track for track in self.tracked_stracks if track.is_activated]
        lost = []
        for track in self.lost_stracks:
            if self.frame_id - track.end_frame > self.max_time_lost:
                track.mark_removed()
            else:
                lost.append(track)
        pool = active + lost
        self._predict(pool + unconfirmed)
        unmatched, remaining = self._associate(pool, high, self.match_thresh)
        unmatched, _ = self._associate(unmatched, low, min(self.match_thresh, .5))
        pending, remaining = self._associate(unconfirmed, remaining, self.match_thresh)
        for track in pending:
            track.mark_removed()

        for track in unmatched:
            track.mark_lost()
        born = []
        for detection in remaining:
            if detection.score >= self.new_track_thresh:
                detection.activate(self.kalman_filter, self.frame_id)
                self._observe(detection, detection)
                born.append(detection)
        self.tracked_stracks = [track for track in pool + unconfirmed if track.state == TrackState.Tracked] + born
        self.lost_stracks = [track for track in pool if track.state == TrackState.Lost]
        return self.tracked_stracks


def detection_rows(values):
    if values is None:
        return np.empty((0, 6), dtype=np.float32)
    if hasattr(values, "cpu"):
        values = values.cpu().numpy()
    return np.asarray(values, dtype=np.float32)
