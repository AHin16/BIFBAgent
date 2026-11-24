"""Smooth regression for condition-level bubble diameter measurements."""

import numpy as np

FEATURES = ("Q_m3_h", "height_m", "salinity_wt_pct", "PL_fraction")
REGULARIZATION = .018


def normalize(points):
    points = np.atleast_2d(np.asarray(points, dtype=float)).copy()
    points[:, 2] = np.log(points[:, 2])
    return (points - [1.9, 1.2, 0., .1]) / [.8, 1.6, np.log(5), .1]


def covariance(left, right, kernel):
    def component(columns, scale):
        distance = np.linalg.norm(
            left[:, None, columns] - right[None, :, columns], axis=-1
        ) / scale
        if kernel == "RBF":
            return np.exp(-.5 * distance ** 2)
        if kernel == "Matern":
            distance *= np.sqrt(3)
            return (1 + distance) * np.exp(-distance)
        raise ValueError(f"Unknown bubble diameter kernel: {kernel}")

    return (component([2], .40) + .20 * component([1], .70)
            + .12 * component([3], .65) + .10 * component(slice(None), .55))


def fit_kernel(points, diameters, kernel, sample_weights=None):
    normalized = normalize(points)
    labels = np.log(diameters)
    weights = np.ones(len(normalized)) if sample_weights is None else np.asarray(sample_weights, dtype=float)
    if weights.shape != (len(normalized),) or not np.isfinite(weights).all() or (weights <= 0).any():
        raise ValueError("Each training condition must have a finite positive weight.")
    weights = weights / weights.mean()
    center = float(np.average(labels, weights=weights))
    matrix = covariance(normalized, normalized, kernel)
    coefficients = np.linalg.solve(matrix + REGULARIZATION * np.diag(1 / weights), labels - center)
    return {"kernel": kernel, "normalized_points": normalized.tolist(),
            "log_center": center, "coefficients": coefficients.tolist()}


def predict_kernel(model, points):
    weights = covariance(normalize(points), np.asarray(model["normalized_points"]), model["kernel"])
    return np.exp(model["log_center"] + weights @ model["coefficients"])
