"""Canonical detector-plane centroid estimators.

Coordinates in this module are absolute array coordinates: ``x`` increases
with column index and ``y`` increases with row index.  Compatibility wrappers
are responsible for translating these coordinates to any historical centred
or upward-positive convention.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal, Protocol, runtime_checkable

import numpy as np


CentroidMethod = Literal[
    "center_of_gravity",
    "thresholded_center_of_gravity",
]

__all__ = (
    "CentroidMethod",
    "CentroidConfig",
    "CentroidEstimate",
    "CentroidEstimator",
    "CenterOfGravityEstimator",
    "ThresholdedCenterOfGravityEstimator",
    "make_centroid_estimator",
    "estimate_centroid",
)

_CENTROID_METHODS = frozenset(
    {
        "center_of_gravity",
        "thresholded_center_of_gravity",
    }
)


@dataclass(frozen=True)
class CentroidConfig:
    """Serializable configuration selecting a centroid estimator.

    ``threshold_fraction`` is a fraction of the processed image maximum.  It
    is used only by ``"thresholded_center_of_gravity"``.  Values greater than
    one are deliberately permitted: the legacy estimator accepted them and
    they deterministically produce a zero-flux estimate.
    """

    __hash_schema_id__ = "shwfs_ao.detector.CentroidConfig.v1"

    estimator: CentroidMethod = "center_of_gravity"
    threshold_fraction: float = 0.0
    subtract_minimum: bool = False

    def __post_init__(self) -> None:
        estimator = str(self.estimator)
        if estimator not in _CENTROID_METHODS:
            allowed = ", ".join(sorted(_CENTROID_METHODS))
            raise ValueError(
                f"estimator must be one of {allowed}; got {self.estimator!r}."
            )
        threshold_fraction = _finite_nonnegative(
            self.threshold_fraction,
            label="threshold_fraction",
        )
        subtract_minimum = _boolean(
            self.subtract_minimum,
            label="subtract_minimum",
        )
        if estimator == "center_of_gravity" and threshold_fraction != 0.0:
            raise ValueError(
                "threshold_fraction must be zero when estimator is "
                "'center_of_gravity'."
            )

        object.__setattr__(self, "estimator", estimator)
        object.__setattr__(self, "threshold_fraction", threshold_fraction)
        object.__setattr__(self, "subtract_minimum", subtract_minimum)


@dataclass(frozen=True)
class CentroidEstimate:
    """One detector-plane centroid and its post-processing flux."""

    x_px: float
    y_px: float
    total_flux_e: float
    finite: bool

    def __post_init__(self) -> None:
        x_px = _float(self.x_px, label="x_px")
        y_px = _float(self.y_px, label="y_px")
        total_flux_e = _finite_float(self.total_flux_e, label="total_flux_e")
        finite = _boolean(self.finite, label="finite")

        coordinates_are_finite = math.isfinite(x_px) and math.isfinite(y_px)
        coordinates_are_nan = math.isnan(x_px) and math.isnan(y_px)
        if finite:
            if not coordinates_are_finite:
                raise ValueError("finite centroid coordinates must be finite.")
            if total_flux_e <= 0.0:
                raise ValueError(
                    "a finite centroid must have positive total_flux_e."
                )
        elif not coordinates_are_nan:
            raise ValueError(
                "a non-finite centroid must use NaN for both x_px and y_px."
            )

        object.__setattr__(self, "x_px", x_px)
        object.__setattr__(self, "y_px", y_px)
        object.__setattr__(self, "total_flux_e", total_flux_e)
        object.__setattr__(self, "finite", finite)


@runtime_checkable
class CentroidEstimator(Protocol):
    """Structural interface for a detector-plane centroid estimator."""

    def estimate(self, image_e: np.ndarray) -> CentroidEstimate:
        ...


@dataclass(frozen=True)
class CenterOfGravityEstimator:
    """Center-of-gravity estimator with optional minimum subtraction."""

    subtract_minimum: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "subtract_minimum",
            _boolean(self.subtract_minimum, label="subtract_minimum"),
        )

    def estimate(self, image_e: np.ndarray) -> CentroidEstimate:
        image = _validated_image(image_e)
        processed = _subtract_minimum(image) if self.subtract_minimum else image
        return _center_of_gravity(processed)


@dataclass(frozen=True)
class ThresholdedCenterOfGravityEstimator:
    """Center-of-gravity estimator after fractional peak thresholding."""

    threshold_fraction: float
    subtract_minimum: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "threshold_fraction",
            _finite_nonnegative(
                self.threshold_fraction,
                label="threshold_fraction",
            ),
        )
        object.__setattr__(
            self,
            "subtract_minimum",
            _boolean(self.subtract_minimum, label="subtract_minimum"),
        )

    def estimate(self, image_e: np.ndarray) -> CentroidEstimate:
        image = _validated_image(image_e)
        if self.subtract_minimum:
            image = _subtract_minimum(image)
        processed = _threshold(image, self.threshold_fraction)
        return _center_of_gravity(processed)


def make_centroid_estimator(config: CentroidConfig) -> CentroidEstimator:
    """Build the concrete estimator selected by ``config``."""

    if not isinstance(config, CentroidConfig):
        raise TypeError(
            f"config must be a CentroidConfig; got {type(config).__name__}."
        )
    if config.estimator == "center_of_gravity":
        return CenterOfGravityEstimator(
            subtract_minimum=config.subtract_minimum,
        )
    return ThresholdedCenterOfGravityEstimator(
        threshold_fraction=config.threshold_fraction,
        subtract_minimum=config.subtract_minimum,
    )


def estimate_centroid(
    image_e: np.ndarray,
    config: CentroidConfig | None = None,
) -> CentroidEstimate:
    """Estimate a centroid using ``config`` or the canonical default."""

    resolved = CentroidConfig() if config is None else config
    return make_centroid_estimator(resolved).estimate(image_e)


def _validated_image(image_e: np.ndarray) -> np.ndarray:
    raw = np.asarray(image_e)
    if raw.ndim != 2:
        raise ValueError(
            f"image_e must be two-dimensional; got shape {raw.shape}."
        )
    if np.iscomplexobj(raw):
        raise ValueError("image_e must contain real electron values.")
    try:
        image = np.array(raw, dtype=float, copy=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("image_e must contain real electron values.") from exc
    if not np.all(np.isfinite(image)):
        raise ValueError("image_e must contain only finite pixels.")
    return image


def _subtract_minimum(image: np.ndarray) -> np.ndarray:
    if image.size == 0:
        return image
    result = image - float(np.min(image))
    # Guard against a negative round-off residue after subtraction.
    np.maximum(result, 0.0, out=result)
    return result


def _threshold(image: np.ndarray, threshold_fraction: float) -> np.ndarray:
    if threshold_fraction <= 0.0 or image.size == 0:
        return image
    threshold = threshold_fraction * float(np.max(image))
    result = image.copy()
    result[result < threshold] = 0.0
    return result


def _center_of_gravity(image: np.ndarray) -> CentroidEstimate:
    with np.errstate(over="ignore", invalid="ignore"):
        total_flux_e = float(np.sum(image, dtype=np.float64))
    if not math.isfinite(total_flux_e):
        raise ValueError("processed image flux must be finite.")
    if total_flux_e <= 0.0:
        return CentroidEstimate(
            x_px=math.nan,
            y_px=math.nan,
            total_flux_e=total_flux_e,
            finite=False,
        )

    rows, columns = image.shape
    x_px = np.arange(columns, dtype=float)[None, :]
    y_px = np.arange(rows, dtype=float)[:, None]
    with np.errstate(over="ignore", invalid="ignore"):
        weights = image / total_flux_e
        centroid_x = float(np.sum(weights * x_px, dtype=np.float64))
        centroid_y = float(np.sum(weights * y_px, dtype=np.float64))
    if not (math.isfinite(centroid_x) and math.isfinite(centroid_y)):
        return CentroidEstimate(
            x_px=math.nan,
            y_px=math.nan,
            total_flux_e=total_flux_e,
            finite=False,
        )
    return CentroidEstimate(
        x_px=centroid_x,
        y_px=centroid_y,
        total_flux_e=total_flux_e,
        finite=True,
    )


def _float(value: object, *, label: str) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{label} must be a real scalar, not a boolean.")
    array = np.asarray(value)
    if array.shape != () or np.iscomplexobj(array):
        raise ValueError(f"{label} must be a real scalar; got {value!r}.")
    try:
        return float(array)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a real scalar; got {value!r}.") from exc


def _finite_float(value: object, *, label: str) -> float:
    result = _float(value, label=label)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite; got {value!r}.")
    return result


def _finite_nonnegative(value: object, *, label: str) -> float:
    result = _finite_float(value, label=label)
    if result < 0.0:
        raise ValueError(f"{label} must be non-negative; got {value!r}.")
    return result


def _boolean(value: object, *, label: str) -> bool:
    if not isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{label} must be a boolean; got {value!r}.")
    return bool(value)
