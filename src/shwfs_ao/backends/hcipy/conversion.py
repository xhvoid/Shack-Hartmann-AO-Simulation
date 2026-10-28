"""Conversions between repository arrays and HCIPy grids, fields, and wavefronts.

Repository conventions are authoritative on both sides of every conversion:

- 2-D arrays use axis 0 as physical ``y`` (rows) and axis 1 as physical ``x``
  (columns), with both coordinates strictly increasing and uniformly spaced.
- Samples outside the boolean pupil mask may be NaN; samples inside it must be
  finite.  Interior NaN or Inf is a caller error and fails *before* HCIPy is
  imported or called.
- HCIPy fields are one-dimensional with ``x`` varying fastest, which is exactly
  the C-order ravel of a ``(rows, columns)`` array.  ``FLATTENING_ORDER``
  records this contract.
- Conversions back to repository data return plain ``numpy.ndarray`` objects
  (never HCIPy ``Field`` subclasses), restore the pupil mask, and fill
  outside-pupil samples with the caller's requested fill value.  Only
  outside-pupil samples are ever replaced; there is deliberately no blanket
  ``nan_to_num`` anywhere in this module.

Every public function validates repository-side inputs first and only then
resolves the optional dependency, so invalid physical input raises
:class:`HcipyConversionError` even on installations without HCIPy.
"""

from __future__ import annotations

import math
from numbers import Real
from typing import Any

import numpy as np

from ...core.geometry import PupilGeometry
from ...core.wavefront import validate_masked_finite
from . import require_hcipy


FLATTENING_ORDER = "c_order_row_major_x_fastest"
"""Flattening contract: ``field[row * columns + column] == array[row, column]``."""

OUTSIDE_PUPIL_FILL_CONVENTION = "nan_outside_pupil"
"""Repository arrays default to NaN outside the pupil; HCIPy fields use zero."""

_COORDINATE_RTOL = 1.0e-12

__all__ = (
    "FLATTENING_ORDER",
    "OUTSIDE_PUPIL_FILL_CONVENTION",
    "HcipyConversionError",
    "hcipy_grid_from_coordinates",
    "hcipy_grid_from_geometry",
    "coordinates_from_hcipy_grid",
    "aperture_field_from_mask",
    "mask_from_aperture_field",
    "field_from_masked_array",
    "masked_array_from_field",
    "wavefront_from_opd",
    "opd_m_from_wavefront",
)


class HcipyConversionError(ValueError):
    """Raised when a repository/HCIPy conversion input is invalid."""


def hcipy_grid_from_coordinates(x_m: np.ndarray, y_m: np.ndarray) -> Any:
    """Build a regular HCIPy Cartesian grid from repository meshgrids.

    ``x_m`` must vary only along columns and ``y_m`` only along rows, both
    strictly increasing and uniformly spaced.  The returned grid reproduces
    the exact first-sample origin and spacing rather than re-centering.
    """

    x_axis, y_axis = _validated_axes(x_m, y_m)
    delta = [
        _uniform_spacing(x_axis, label="x_m"),
        _uniform_spacing(y_axis, label="y_m"),
    ]
    dims = [int(x_axis.size), int(y_axis.size)]
    zero = [float(x_axis[0]), float(y_axis[0])]
    hcipy = require_hcipy()
    return hcipy.CartesianGrid(hcipy.RegularCoords(delta, dims, zero))


def hcipy_grid_from_geometry(geometry: PupilGeometry) -> Any:
    """Build the HCIPy grid matching a validated repository pupil geometry."""

    if not isinstance(geometry, PupilGeometry):
        raise HcipyConversionError("geometry must be a PupilGeometry.")
    return hcipy_grid_from_coordinates(geometry.x_m, geometry.y_m)


def coordinates_from_hcipy_grid(grid: Any) -> tuple[np.ndarray, np.ndarray]:
    """Return repository ``(x_m, y_m)`` meshgrids for a regular HCIPy grid."""

    hcipy = require_hcipy()
    _validated_grid(grid, hcipy=hcipy)
    x_axis, y_axis = (np.asarray(axis, dtype=float) for axis in grid.separated_coords)
    x_m, y_m = np.meshgrid(x_axis, y_axis, indexing="xy")
    return (
        np.array(x_m, dtype=float, copy=True),
        np.array(y_m, dtype=float, copy=True),
    )


def aperture_field_from_mask(pupil_mask: np.ndarray, grid: Any) -> Any:
    """Return a float 1.0/0.0 HCIPy aperture field for a boolean pupil mask."""

    mask = _validated_mask(pupil_mask)
    hcipy = require_hcipy()
    _validated_grid_for_mask(grid, mask, hcipy=hcipy)
    return hcipy.Field(mask.astype(float).ravel(order="C"), grid)


def mask_from_aperture_field(
    aperture_field: Any,
    *,
    threshold: float = 0.5,
) -> np.ndarray:
    """Return the boolean 2-D pupil mask encoded by an aperture field."""

    limit = _validated_threshold(threshold)
    hcipy = require_hcipy()
    values, shape = _validated_field(aperture_field, hcipy=hcipy)
    if not np.all(np.isfinite(values)):
        raise HcipyConversionError(
            "aperture_field must contain only finite values."
        )
    return np.array(
        values.reshape(shape) > limit,
        dtype=bool,
        copy=True,
    )


def field_from_masked_array(
    values: np.ndarray,
    pupil_mask: np.ndarray,
    grid: Any,
) -> Any:
    """Convert a repository masked 2-D array to an HCIPy field.

    In-pupil samples must be finite and are copied exactly.  Outside-pupil
    samples (which may be NaN under the repository convention) are replaced by
    zero — and only those samples — so downstream HCIPy arithmetic never sees
    a NaN.
    """

    array, mask = _validated_masked_array(values, pupil_mask, label="values")
    hcipy = require_hcipy()
    _validated_grid_for_mask(grid, mask, hcipy=hcipy)
    filled = np.zeros(array.shape, dtype=float)
    filled[mask] = array[mask]
    return hcipy.Field(filled.ravel(order="C"), grid)


def masked_array_from_field(
    field: Any,
    pupil_mask: np.ndarray,
    *,
    outside_fill: float = np.nan,
) -> np.ndarray:
    """Convert an HCIPy field back to a repository masked 2-D array.

    In-pupil samples are copied exactly and must be finite.  Every
    outside-pupil sample is set to ``outside_fill`` (NaN by default),
    restoring the repository convention regardless of what the HCIPy
    computation left there.
    """

    mask = _validated_mask(pupil_mask)
    fill = _validated_fill(outside_fill)
    hcipy = require_hcipy()
    values, shape = _validated_field(field, hcipy=hcipy)
    if shape != mask.shape:
        raise HcipyConversionError(
            f"field grid shape {shape} does not match pupil_mask shape "
            f"{mask.shape}."
        )
    array = values.reshape(shape)
    result = np.full(mask.shape, fill, dtype=float)
    result[mask] = array[mask]
    try:
        validate_masked_finite(result, mask, "field")
    except ValueError as exc:
        raise HcipyConversionError(str(exc)) from exc
    return result


def wavefront_from_opd(
    opd_m: np.ndarray,
    pupil_mask: np.ndarray,
    grid: Any,
    *,
    wavelength_m: float,
) -> Any:
    """Build an HCIPy wavefront from repository OPD metres at one wavelength.

    The electric field is ``exp(1j * 2π * opd_m / wavelength_m)`` inside the
    pupil and exactly zero outside it.  The wavelength is explicit; there is
    no default.
    """

    array, mask = _validated_masked_array(opd_m, pupil_mask, label="opd_m")
    wavelength = _validated_wavelength(wavelength_m)
    hcipy = require_hcipy()
    _validated_grid_for_mask(grid, mask, hcipy=hcipy)

    phase_rad = np.zeros(array.shape, dtype=float)
    phase_rad[mask] = array[mask] * (2.0 * math.pi / wavelength)
    electric_field = np.zeros(array.shape, dtype=complex)
    electric_field[mask] = np.exp(1j * phase_rad[mask])
    field = hcipy.Field(electric_field.ravel(order="C"), grid)
    return hcipy.Wavefront(field, wavelength=wavelength)


def opd_m_from_wavefront(
    wavefront: Any,
    pupil_mask: np.ndarray,
    *,
    outside_fill: float = np.nan,
) -> np.ndarray:
    """Return the in-pupil OPD metres encoded by an HCIPy wavefront.

    The phase is read with ``numpy.angle`` and converted at the wavefront's
    own explicit wavelength, so the result is only unambiguous while the
    wrapped phase stays inside ``(-π, π]``.  Larger optical paths alias; this
    helper exists for conversion checks and small-signal fixtures, not for
    reconstructing arbitrary accumulated OPD.
    """

    mask = _validated_mask(pupil_mask)
    fill = _validated_fill(outside_fill)
    hcipy = require_hcipy()
    if not isinstance(wavefront, hcipy.Wavefront):
        raise HcipyConversionError("wavefront must be an hcipy.Wavefront.")
    wavelength = _validated_wavelength(wavefront.wavelength)
    values, shape = _validated_field(
        wavefront.electric_field,
        hcipy=hcipy,
        allow_complex=True,
    )
    if shape != mask.shape:
        raise HcipyConversionError(
            f"wavefront grid shape {shape} does not match pupil_mask shape "
            f"{mask.shape}."
        )
    electric_field = values.reshape(shape)
    if not np.all(np.isfinite(electric_field[mask])):
        raise HcipyConversionError(
            "wavefront must be finite inside the pupil mask."
        )
    phase_rad = np.angle(electric_field[mask])
    result = np.full(mask.shape, fill, dtype=float)
    result[mask] = phase_rad * (wavelength / (2.0 * math.pi))
    return result


def _validated_axes(x_m: object, y_m: object) -> tuple[np.ndarray, np.ndarray]:
    x_grid = _coerced_float_2d(x_m, label="x_m")
    y_grid = _coerced_float_2d(y_m, label="y_m")
    if x_grid.shape != y_grid.shape:
        raise HcipyConversionError(
            f"x_m shape {x_grid.shape} does not match y_m shape {y_grid.shape}."
        )
    if not np.all(np.isfinite(x_grid)) or not np.all(np.isfinite(y_grid)):
        raise HcipyConversionError("x_m and y_m must contain only finite values.")
    if not np.array_equal(x_grid, np.broadcast_to(x_grid[0:1, :], x_grid.shape)):
        raise HcipyConversionError("x_m must vary only along columns.")
    if not np.array_equal(y_grid, np.broadcast_to(y_grid[:, 0:1], y_grid.shape)):
        raise HcipyConversionError("y_m must vary only along rows.")
    x_axis = np.array(x_grid[0, :], dtype=float, copy=True)
    y_axis = np.array(y_grid[:, 0], dtype=float, copy=True)
    for axis, label in ((x_axis, "x_m"), (y_axis, "y_m")):
        if axis.size < 2:
            raise HcipyConversionError(
                f"{label} must sample at least two points per axis."
            )
        if np.any(np.diff(axis) <= 0.0):
            raise HcipyConversionError(
                f"{label} coordinates must be strictly increasing."
            )
    return x_axis, y_axis


def _uniform_spacing(axis: np.ndarray, *, label: str) -> float:
    steps = np.diff(axis)
    spacing = float(steps[0])
    scale = max(abs(float(axis[0])), abs(float(axis[-1])), 1.0)
    if not np.allclose(
        steps,
        spacing,
        rtol=_COORDINATE_RTOL,
        atol=scale * _COORDINATE_RTOL,
    ):
        raise HcipyConversionError(
            f"{label} coordinates must be uniformly spaced for a regular "
            "HCIPy grid."
        )
    return spacing


def _validated_grid(grid: Any, *, hcipy: Any) -> tuple[int, int]:
    """Validate a regular separated Cartesian grid; return (rows, columns)."""

    if not isinstance(grid, hcipy.Grid):
        raise HcipyConversionError("grid must be an hcipy Cartesian grid.")
    if getattr(grid, "ndim", None) != 2:
        raise HcipyConversionError("grid must be two-dimensional.")
    if not (grid.is_regular and grid.is_separated):
        raise HcipyConversionError(
            "grid must be regular and separated to map onto repository arrays."
        )
    columns, rows = (int(value) for value in grid.dims)
    return rows, columns


def _validated_grid_for_mask(
    grid: Any,
    mask: np.ndarray,
    *,
    hcipy: Any,
) -> None:
    rows, columns = _validated_grid(grid, hcipy=hcipy)
    if (rows, columns) != mask.shape:
        raise HcipyConversionError(
            f"grid shape {(rows, columns)} does not match pupil_mask shape "
            f"{mask.shape}."
        )


def _validated_field(
    field: Any,
    *,
    hcipy: Any,
    allow_complex: bool = False,
) -> tuple[np.ndarray, tuple[int, int]]:
    """Return C-order field values and the (rows, columns) grid shape."""

    if not isinstance(field, hcipy.Field):
        raise HcipyConversionError("field must be an hcipy.Field.")
    rows, columns = _validated_grid(field.grid, hcipy=hcipy)
    if field.ndim != 1 or field.size != rows * columns:
        raise HcipyConversionError(
            "field must be a scalar field with one value per grid point."
        )
    if allow_complex:
        values = np.array(field, dtype=complex, copy=True, subok=False)
    else:
        if np.iscomplexobj(field):
            raise HcipyConversionError("field must contain real values.")
        values = np.array(field, dtype=float, copy=True, subok=False)
    return values, (rows, columns)


def _validated_mask(pupil_mask: object) -> np.ndarray:
    mask = np.asarray(pupil_mask)
    if mask.dtype.kind != "b":
        raise HcipyConversionError("pupil_mask must be a boolean array.")
    if mask.ndim != 2:
        raise HcipyConversionError("pupil_mask must be two-dimensional.")
    if not np.any(mask):
        raise HcipyConversionError(
            "pupil_mask must contain at least one pupil sample."
        )
    return np.array(mask, dtype=bool, copy=True)


def _validated_masked_array(
    values: object,
    pupil_mask: object,
    *,
    label: str,
) -> tuple[np.ndarray, np.ndarray]:
    mask = _validated_mask(pupil_mask)
    try:
        array = np.asarray(values, dtype=float)
    except (TypeError, ValueError) as exc:
        raise HcipyConversionError(f"{label} must be a real numeric array.") from exc
    if array.shape != mask.shape:
        raise HcipyConversionError(
            f"{label} shape {array.shape} does not match pupil_mask shape "
            f"{mask.shape}."
        )
    try:
        validate_masked_finite(array, mask, label)
    except ValueError as exc:
        raise HcipyConversionError(str(exc)) from exc
    return np.array(array, dtype=float, copy=True), mask


def _validated_threshold(threshold: object) -> float:
    if isinstance(threshold, (bool, np.bool_)) or not isinstance(threshold, Real):
        raise HcipyConversionError("threshold must be a real number in (0, 1).")
    limit = float(threshold)
    if not math.isfinite(limit) or not 0.0 < limit < 1.0:
        raise HcipyConversionError("threshold must be a real number in (0, 1).")
    return limit


def _validated_fill(outside_fill: object) -> float:
    if isinstance(outside_fill, (bool, np.bool_)) or not isinstance(
        outside_fill, Real
    ):
        raise HcipyConversionError("outside_fill must be a real scalar (NaN allowed).")
    return float(outside_fill)


def _validated_wavelength(wavelength_m: object) -> float:
    if isinstance(wavelength_m, (bool, np.bool_)) or not isinstance(
        wavelength_m, Real
    ):
        raise HcipyConversionError("wavelength_m must be a positive finite scalar.")
    wavelength = float(wavelength_m)
    if not math.isfinite(wavelength) or wavelength <= 0.0:
        raise HcipyConversionError("wavelength_m must be a positive finite scalar.")
    return wavelength


def _coerced_float_2d(values: object, *, label: str) -> np.ndarray:
    try:
        array = np.asarray(values, dtype=float)
    except (TypeError, ValueError) as exc:
        raise HcipyConversionError(f"{label} must be a real numeric array.") from exc
    if array.ndim != 2:
        raise HcipyConversionError(f"{label} must be a two-dimensional array.")
    return array
