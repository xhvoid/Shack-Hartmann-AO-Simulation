"""Backend-neutral sampled-pupil geometry.

The coordinate convention used throughout the repository is explicit here:
array axis 0 is physical ``y`` (increasing row number) and array axis 1 is
physical ``x`` (increasing column number).  Geometry arrays are copied into
immutable byte-backed storage so a calibration hash cannot be invalidated by
later mutation.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Integral, Real
from typing import ClassVar

import numpy as np

from .hashing import geometry_hash as _geometry_hash


__all__ = (
    "GeometryError",
    "PupilGeometry",
    "build_pupil_geometry",
)


class GeometryError(ValueError):
    """Raised when a sampled physical geometry is inconsistent."""


@dataclass(frozen=True)
class PupilGeometry:
    """Immutable Cartesian pupil sampling in metres.

    ``x_m`` varies along columns and ``y_m`` varies along rows.  The sampled
    outer diameter spans both coordinate axes; central obstructions and spider
    vanes are represented solely by ``pupil_mask``.
    """

    telescope_diameter_m: float
    pupil_shape: tuple[int, int]
    pupil_mask: np.ndarray
    x_m: np.ndarray
    y_m: np.ndarray

    __hash_schema_id__: ClassVar[str] = "shwfs_ao.pupil_geometry.v1"

    def __post_init__(self) -> None:
        diameter = _positive_float(
            self.telescope_diameter_m,
            label="telescope_diameter_m",
        )
        shape = _shape_pair(self.pupil_shape, label="pupil_shape")
        x_m = _float_array(self.x_m, shape=shape, label="x_m")
        y_m = _float_array(self.y_m, shape=shape, label="y_m")
        mask = _bool_array(self.pupil_mask, shape=shape, label="pupil_mask")

        _validate_cartesian_grid(x_m, y_m, diameter)
        if not np.any(mask):
            raise GeometryError("pupil_mask must contain illuminated samples.")
        radius_m = np.hypot(x_m, y_m)
        tolerance = max(diameter, 1.0) * 1.0e-12
        if np.any(mask & (radius_m > 0.5 * diameter + tolerance)):
            raise GeometryError(
                "pupil_mask contains samples outside telescope_diameter_m."
            )

        object.__setattr__(self, "telescope_diameter_m", diameter)
        object.__setattr__(self, "pupil_shape", shape)
        object.__setattr__(self, "pupil_mask", _readonly_array(mask, dtype=bool))
        object.__setattr__(self, "x_m", _readonly_array(x_m, dtype=float))
        object.__setattr__(self, "y_m", _readonly_array(y_m, dtype=float))

    @property
    def geometry_hash(self) -> str:
        """Content hash covering coordinates, mask, shape, and diameter."""

        return _geometry_hash(self)

    @property
    def config_hash(self) -> str:
        """Protocol-friendly alias for :attr:`geometry_hash`."""

        return self.geometry_hash

    @property
    def pixel_spacing_xy_m(self) -> tuple[float, float]:
        """Return positive ``(x, y)`` grid spacings in metres."""

        return (
            float(self.x_m[0, 1] - self.x_m[0, 0]),
            float(self.y_m[1, 0] - self.y_m[0, 0]),
        )


def build_pupil_geometry(
    *,
    telescope_diameter_m: float,
    pupil_shape: tuple[int, int],
    central_obstruction_ratio: float = 0.0,
    spider_width_m: float = 0.0,
) -> PupilGeometry:
    """Build a circular sampled pupil with optional obstruction and cross spider.

    ``central_obstruction_ratio`` is the obscured diameter divided by the
    telescope diameter.  ``spider_width_m`` is the full width of both the
    horizontal and vertical vane.
    """

    diameter = _positive_float(telescope_diameter_m, label="telescope_diameter_m")
    shape = _shape_pair(pupil_shape, label="pupil_shape")
    obstruction = _finite_float(
        central_obstruction_ratio,
        label="central_obstruction_ratio",
    )
    if not 0.0 <= obstruction < 1.0:
        raise GeometryError("central_obstruction_ratio must be in [0, 1).")
    spider = _finite_float(spider_width_m, label="spider_width_m")
    if spider < 0.0:
        raise GeometryError("spider_width_m must be non-negative.")

    rows, columns = shape
    x_axis_m = np.linspace(-0.5 * diameter, 0.5 * diameter, columns)
    y_axis_m = np.linspace(-0.5 * diameter, 0.5 * diameter, rows)
    x_m, y_m = np.meshgrid(x_axis_m, y_axis_m, indexing="xy")
    radius_m = np.hypot(x_m, y_m)
    mask = radius_m <= 0.5 * diameter
    if obstruction > 0.0:
        mask &= radius_m >= 0.5 * diameter * obstruction
    if spider > 0.0:
        half_width_m = 0.5 * spider
        mask &= ~(
            (np.abs(x_m) <= half_width_m)
            | (np.abs(y_m) <= half_width_m)
        )
    if not np.any(mask):
        raise GeometryError(
            "central obstruction and spider settings remove the entire pupil."
        )
    return PupilGeometry(
        telescope_diameter_m=diameter,
        pupil_shape=shape,
        pupil_mask=mask,
        x_m=x_m,
        y_m=y_m,
    )


def _shape_pair(value: object, *, label: str) -> tuple[int, int]:
    if not isinstance(value, tuple) or len(value) != 2:
        raise GeometryError(f"{label} must be a two-item tuple.")
    result: list[int] = []
    for index, item in enumerate(value):
        if not isinstance(item, Integral) or isinstance(item, (bool, np.bool_)):
            raise GeometryError(f"{label}[{index}] must be an integer.")
        number = int(item)
        if number < 2:
            raise GeometryError(f"{label}[{index}] must be at least 2.")
        result.append(number)
    return result[0], result[1]


def _finite_float(value: object, *, label: str) -> float:
    if not isinstance(value, Real) or isinstance(value, (bool, np.bool_)):
        raise GeometryError(f"{label} must be a finite real number.")
    result = float(value)
    if not math.isfinite(result):
        raise GeometryError(f"{label} must be a finite real number.")
    return result


def _positive_float(value: object, *, label: str) -> float:
    result = _finite_float(value, label=label)
    if result <= 0.0:
        raise GeometryError(f"{label} must be positive.")
    return result


def _float_array(
    value: object,
    *,
    shape: tuple[int, int],
    label: str,
) -> np.ndarray:
    try:
        array = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise GeometryError(f"{label} must be a finite numeric array.") from exc
    if array.shape != shape:
        raise GeometryError(f"{label} shape {array.shape} does not match {shape}.")
    if not np.all(np.isfinite(array)):
        raise GeometryError(f"{label} must contain only finite values.")
    return array


def _bool_array(
    value: object,
    *,
    shape: tuple[int, int],
    label: str,
) -> np.ndarray:
    array = np.asarray(value)
    if array.dtype.kind != "b":
        raise GeometryError(f"{label} must be a boolean array.")
    if array.shape != shape:
        raise GeometryError(f"{label} shape {array.shape} does not match {shape}.")
    return array.astype(bool, copy=False)


def _validate_cartesian_grid(
    x_m: np.ndarray,
    y_m: np.ndarray,
    diameter_m: float,
) -> None:
    if not np.allclose(x_m, x_m[0:1, :], rtol=0.0, atol=0.0):
        raise GeometryError("x_m must vary only along detector columns.")
    if not np.allclose(y_m, y_m[:, 0:1], rtol=0.0, atol=0.0):
        raise GeometryError("y_m must vary only along detector rows.")
    if np.any(np.diff(x_m[0]) <= 0.0):
        raise GeometryError("x_m column coordinates must be strictly increasing.")
    if np.any(np.diff(y_m[:, 0]) <= 0.0):
        raise GeometryError("y_m row coordinates must be strictly increasing.")
    x_steps = np.diff(x_m[0])
    y_steps = np.diff(y_m[:, 0])
    spacing_tolerance = max(diameter_m, 1.0) * 1.0e-14
    if not np.allclose(
        x_steps,
        x_steps[0],
        rtol=1.0e-12,
        atol=spacing_tolerance,
    ):
        raise GeometryError("x_m column coordinates must be uniformly spaced.")
    if not np.allclose(
        y_steps,
        y_steps[0],
        rtol=1.0e-12,
        atol=spacing_tolerance,
    ):
        raise GeometryError("y_m row coordinates must be uniformly spaced.")
    expected = (-0.5 * diameter_m, 0.5 * diameter_m)
    actual_x = (float(x_m[0, 0]), float(x_m[0, -1]))
    actual_y = (float(y_m[0, 0]), float(y_m[-1, 0]))
    tolerance = max(diameter_m, 1.0) * 1.0e-12
    if not np.allclose(actual_x, expected, rtol=0.0, atol=tolerance):
        raise GeometryError("x_m axis must span telescope_diameter_m.")
    if not np.allclose(actual_y, expected, rtol=0.0, atol=tolerance):
        raise GeometryError("y_m axis must span telescope_diameter_m.")


def _readonly_array(values: object, *, dtype: object) -> np.ndarray:
    """Return a truly immutable C-contiguous array backed by ``bytes``."""

    contiguous = np.ascontiguousarray(values, dtype=dtype)
    return np.frombuffer(contiguous.tobytes(order="C"), dtype=contiguous.dtype).reshape(
        contiguous.shape
    )
