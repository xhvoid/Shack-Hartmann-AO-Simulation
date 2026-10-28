"""Backend-neutral physical estimators for validation comparisons.

These helpers consume plain arrays and repository result objects only; they
never import a backend library.  Canonical wavefront statistics stay in
``core.wavefront`` and canonical science metrics in ``science.metrics`` —
this module adds only the small estimators the cross-backend suite needs on
top of them.
"""

from __future__ import annotations

import math
from numbers import Integral, Real

import numpy as np


__all__ = (
    "PhysicalEstimatorError",
    "centroid_xy_px",
    "encircled_energy_radius_rad",
    "mean_square_column_difference",
    "normalized_singular_spectrum",
)


class PhysicalEstimatorError(ValueError):
    """Raised when a physical-estimator input is inconsistent."""


def centroid_xy_px(spot: np.ndarray) -> tuple[float, float]:
    """Return the first-moment ``(x, y)`` centroid of one spot in pixels."""

    values = _finite_2d(spot, label="spot")
    total = float(np.sum(values, dtype=np.float64))
    if total <= 0.0:
        raise PhysicalEstimatorError("spot must carry positive total flux.")
    rows, columns = values.shape
    row_grid, column_grid = np.mgrid[0:rows, 0:columns]
    return (
        float(np.sum(column_grid * values)) / total,
        float(np.sum(row_grid * values)) / total,
    )


def encircled_energy_radius_rad(
    spot: np.ndarray,
    pixel_scale_xy_rad: tuple[float, float],
    fraction: float = 0.5,
) -> float:
    """Return the radius containing ``fraction`` of the flux, from the CoG."""

    values = _finite_2d(spot, label="spot")
    scale_x = _positive("pixel_scale_xy_rad[0]", pixel_scale_xy_rad[0])
    scale_y = _positive("pixel_scale_xy_rad[1]", pixel_scale_xy_rad[1])
    if (
        isinstance(fraction, (bool, np.bool_))
        or not isinstance(fraction, Real)
        or not 0.0 < float(fraction) < 1.0
    ):
        raise PhysicalEstimatorError("fraction must lie strictly in (0, 1).")
    center_x, center_y = centroid_xy_px(values)
    rows, columns = values.shape
    row_grid, column_grid = np.mgrid[0:rows, 0:columns]
    radii = np.hypot(
        (column_grid - center_x) * scale_x,
        (row_grid - center_y) * scale_y,
    ).ravel()
    order = np.argsort(radii, kind="stable")
    cumulative = np.cumsum(values.ravel()[order])
    cumulative /= cumulative[-1]
    return float(radii[order][int(np.searchsorted(cumulative, float(fraction)))])


def mean_square_column_difference(values: np.ndarray, lag_px: int) -> float:
    """Return ``mean((v[:, lag:] - v[:, :-lag])**2)`` as a structure estimate.

    NaN samples (outside-pupil convention) are ignored; at least one finite
    pair is required.
    """

    array = np.asarray(values, dtype=float)
    if array.ndim != 2:
        raise PhysicalEstimatorError("values must be a 2-D array.")
    if (
        isinstance(lag_px, (bool, np.bool_))
        or not isinstance(lag_px, Integral)
        or int(lag_px) < 1
        or int(lag_px) >= array.shape[1]
    ):
        raise PhysicalEstimatorError(
            "lag_px must be an integer in [1, columns)."
        )
    lag = int(lag_px)
    differences = array[:, lag:] - array[:, :-lag]
    finite = np.isfinite(differences)
    if not np.any(finite):
        raise PhysicalEstimatorError(
            "values must contain at least one finite sample pair at lag_px."
        )
    return float(np.mean(differences[finite] ** 2))


def normalized_singular_spectrum(matrix: np.ndarray) -> np.ndarray:
    """Return singular values divided by the largest one."""

    array = np.asarray(matrix, dtype=float)
    if array.ndim != 2 or array.shape[0] < 1 or array.shape[1] < 1:
        raise PhysicalEstimatorError("matrix must be a non-empty 2-D array.")
    if not np.all(np.isfinite(array)):
        raise PhysicalEstimatorError("matrix must contain only finite values.")
    spectrum = np.linalg.svd(array, compute_uv=False)
    peak = float(spectrum[0])
    if not math.isfinite(peak) or peak <= 0.0:
        raise PhysicalEstimatorError("matrix must have a positive largest singular value.")
    return np.asarray(spectrum / peak, dtype=float)


def _finite_2d(values: object, *, label: str) -> np.ndarray:
    try:
        array = np.asarray(values, dtype=float)
    except (TypeError, ValueError) as exc:
        raise PhysicalEstimatorError(f"{label} must be a numeric array.") from exc
    if array.ndim != 2:
        raise PhysicalEstimatorError(f"{label} must be a 2-D array.")
    if not np.all(np.isfinite(array)):
        raise PhysicalEstimatorError(f"{label} must contain only finite values.")
    if np.any(array < 0.0):
        raise PhysicalEstimatorError(f"{label} must be non-negative.")
    return array


def _positive(label: str, value: object) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise PhysicalEstimatorError(f"{label} must be a positive finite scalar.")
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise PhysicalEstimatorError(f"{label} must be a positive finite scalar.")
    return number
