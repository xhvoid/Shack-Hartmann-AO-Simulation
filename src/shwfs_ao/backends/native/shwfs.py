"""Native diffraction backend for canonical Shack--Hartmann optics.

The low-level phase helper deliberately preserves the repository's frozen
local-piston, padding, and centered-FFT arithmetic.  The backend boundary is
unit explicit: callers provide residual optical path difference in metres and
the configured WFS wavelength converts it to phase.
"""

from __future__ import annotations

import math
from numbers import Integral, Real

import numpy as np

from ...core.hashing import component_config_hash
from ...core.types import DetectorPlaneSampling, SpotIntensityResult
from ...wfs.shack_hartmann.geometry import ShackHartmannGeometry
from ...wfs.shack_hartmann.optics import (
    make_detector_plane_sampling,
    validate_spot_intensity_result,
)


__all__ = (
    "NativeShackHartmannError",
    "NativeShackHartmannOptics",
    "NativeShackHartmannOpticsBackend",
    "nominal_lenslet_sampling_shape",
    "lenslet_spot_from_phase",
    "lenslet_spot_from_opd",
    "crop_center",
)


_BACKEND_NAME = "native"
_FFT_CONVENTION = "fftshift_fft2_ifftshift_centered-v1"


class NativeShackHartmannError(ValueError):
    """Raised when native lenslet propagation inputs are inconsistent."""


class NativeShackHartmannOptics:
    """Fixed-padding native SH-WFS diffraction backend.

    Parameters are deliberately not inferred from a science wavelength or an
    external backend.  ``wfs_wavelength_m`` converts OPD to phase, and
    ``detector_window_px`` selects the centered square window returned for
    every retained lenslet.
    """

    def __init__(
        self,
        geometry: ShackHartmannGeometry,
        wfs_wavelength_m: float,
        *,
        pad_factor: int = 8,
        detector_window_px: int | None = None,
    ) -> None:
        if not isinstance(geometry, ShackHartmannGeometry):
            raise NativeShackHartmannError(
                "geometry must be a ShackHartmannGeometry."
            )
        wavelength_m = _positive_float(
            wfs_wavelength_m,
            label="wfs_wavelength_m",
        )
        padding = _positive_integer(pad_factor, label="pad_factor")
        window = _optional_positive_integer(
            detector_window_px,
            label="detector_window_px",
        )

        sampling_shape = nominal_lenslet_sampling_shape(
            geometry.pupil_shape,
            geometry.n_lenslets_across,
        )
        padded_shape = (
            padding * sampling_shape[0],
            padding * sampling_shape[1],
        )
        y_slice, x_slice = _center_slices(padded_shape, window)
        window_shape = (
            int(y_slice.stop - y_slice.start),
            int(x_slice.stop - x_slice.start),
        )
        reference_pixel_xy = (
            float(padded_shape[1] // 2 - x_slice.start),
            float(padded_shape[0] // 2 - y_slice.start),
        )
        dx_m = float(geometry.x_m[0, 1] - geometry.x_m[0, 0])
        dy_m = float(geometry.y_m[1, 0] - geometry.y_m[0, 0])
        pixel_scale_rad = (
            wavelength_m / (padded_shape[1] * dx_m),
            wavelength_m / (padded_shape[0] * dy_m),
        )
        sampling = make_detector_plane_sampling(
            window_shape_px=window_shape,
            pixel_scale_rad=pixel_scale_rad,
            reference_pixel_xy=reference_pixel_xy,
        )

        self._geometry = geometry
        self._wfs_wavelength_m = wavelength_m
        self._pad_factor = padding
        self._detector_window_px = window
        self._sampling_shape = sampling_shape
        self._padded_shape = padded_shape
        self._window_slices = (y_slice, x_slice)
        self._sampling = sampling
        self._pupil_relative_throughput = _readonly_float_array(
            _relative_lenslet_throughput(geometry)
        )
        self._config_hash = component_config_hash(
            "native.shack_hartmann_optics",
            {
                "geometry_hash": geometry.geometry_hash,
                "wfs_wavelength_m": wavelength_m,
                "pad_factor": padding,
                "detector_window_px": window,
                "nominal_lenslet_sampling_shape": sampling_shape,
                "padded_fft_shape": padded_shape,
                "window_origin_yx": (y_slice.start, x_slice.start),
                "detector_sampling_hash": sampling.sampling_hash,
                "fft_convention": _FFT_CONVENTION,
                "remove_local_piston": True,
                "relative_throughput_semantics": "detector_window_capture_fraction",
            },
        )

    @property
    def backend_name(self) -> str:
        return _BACKEND_NAME

    @property
    def config_hash(self) -> str:
        return self._config_hash

    @property
    def geometry(self) -> ShackHartmannGeometry:
        return self._geometry

    @property
    def geometry_hash(self) -> str:
        """Hash of the full mask, coordinates, lenslet masks, IDs, and order."""

        return self._geometry.geometry_hash

    @property
    def wfs_wavelength_m(self) -> float:
        return self._wfs_wavelength_m

    @property
    def pad_factor(self) -> int:
        return self._pad_factor

    @property
    def detector_window_px(self) -> int | None:
        return self._detector_window_px

    @property
    def sampling(self) -> DetectorPlaneSampling:
        return self._sampling

    @property
    def detector_sampling(self) -> DetectorPlaneSampling:
        """Calibration-facing alias for :attr:`sampling`."""

        return self._sampling

    @property
    def subaperture_ids(self) -> tuple[str, ...]:
        return self._geometry.subaperture_ids

    @property
    def pupil_relative_throughput(self) -> np.ndarray:
        """Static illuminated-area throughput, normalized to the fullest lenslet.

        This diagnostic is deliberately distinct from
        ``SpotIntensityResult.relative_throughput``, whose backend-neutral
        meaning is detector-window capture fraction.
        """

        return self._pupil_relative_throughput

    def spot_intensities(self, residual_opd_m: np.ndarray) -> SpotIntensityResult:
        """Return one unit-sum noiseless detector-window spot per lenslet."""

        opd_m = _validated_residual_opd(residual_opd_m, self._geometry)
        phase_rad = 2.0 * np.pi * opd_m / self._wfs_wavelength_m
        y_slice, x_slice = self._window_slices
        spots: list[np.ndarray] = []
        capture_fractions: list[float] = []
        for index, mask in enumerate(self._geometry.subaperture_masks):
            full_spot = lenslet_spot_from_phase(
                phase_rad,
                mask,
                pad_factor=self._pad_factor,
                remove_local_piston=True,
                sampling_shape=self._sampling_shape,
            )
            window_spot = np.asarray(full_spot[y_slice, x_slice], dtype=float)
            total = float(np.sum(window_spot, dtype=np.float64))
            if not math.isfinite(total) or total <= 0.0:
                raise NativeShackHartmannError(
                    f"Lenslet {self._geometry.subaperture_ids[index]!r} has no "
                    "finite intensity inside the configured detector window."
                )
            capture_fractions.append(float(np.clip(total, 0.0, 1.0)))
            spots.append(window_spot / total)

        rows, columns = self._sampling.window_shape_px
        reference_x, reference_y = self._sampling.reference_pixel_xy
        x_axis = np.arange(columns, dtype=float) - reference_x
        y_axis = np.arange(rows, dtype=float) - reference_y
        result = SpotIntensityResult(
            unit_sum_spots=tuple(spots),
            subaperture_ids=self._geometry.subaperture_ids,
            relative_throughput=np.asarray(capture_fractions, dtype=float),
            x_px=tuple(x_axis for _ in spots),
            y_px=tuple(y_axis for _ in spots),
            sampling=self._sampling,
            normalization="unit_sum_per_subaperture",
        )
        return validate_spot_intensity_result(
            result,
            self._geometry,
            sampling=self._sampling,
        )


# Both readable spellings identify the same concrete protocol implementation.
NativeShackHartmannOpticsBackend = NativeShackHartmannOptics


def nominal_lenslet_sampling_shape(
    image_shape: tuple[int, int],
    n_lenslets: int,
) -> tuple[int, int]:
    """Return the fixed pupil-sample canvas used by every nominal lenslet."""

    if not isinstance(image_shape, tuple) or len(image_shape) != 2:
        raise NativeShackHartmannError(
            "image_shape must contain two positive dimensions."
        )
    dimensions = tuple(
        _positive_integer(value, label=f"image_shape[{index}]")
        for index, value in enumerate(image_shape)
    )
    count = _positive_integer(n_lenslets, label="n_lenslets")
    return (
        (dimensions[0] + count - 1) // count,
        (dimensions[1] + count - 1) // count,
    )


def lenslet_spot_from_phase(
    phase_rad: np.ndarray,
    lenslet_mask: np.ndarray,
    pad_factor: int = 8,
    remove_local_piston: bool = True,
    sampling_shape: tuple[int, int] | None = None,
) -> np.ndarray:
    """Preserve the frozen native centered-FFT lenslet intensity arithmetic."""

    padding = _positive_integer(pad_factor, label="pad_factor")
    if not isinstance(remove_local_piston, (bool, np.bool_)):
        raise NativeShackHartmannError("remove_local_piston must be a bool.")
    try:
        phase = np.asarray(phase_rad, dtype=float)
    except (TypeError, ValueError) as exc:
        raise NativeShackHartmannError("phase_rad must be a numeric array.") from exc
    mask = np.asarray(lenslet_mask)
    if mask.dtype.kind != "b":
        raise NativeShackHartmannError("lenslet_mask must be a boolean array.")
    if phase.ndim != 2 or mask.shape != phase.shape:
        raise NativeShackHartmannError(
            "phase_rad and lenslet_mask must be 2-D arrays with the same shape."
        )
    if not np.any(mask):
        raise NativeShackHartmannError(
            "Cannot form a lenslet spot from an empty mask."
        )
    if not np.all(np.isfinite(phase[mask])):
        raise NativeShackHartmannError(
            "phase_rad must be finite inside lenslet_mask."
        )

    y_slice, x_slice = _bounding_box(mask)
    local_mask = mask[y_slice, x_slice]
    local_phase = np.nan_to_num(phase[y_slice, x_slice], nan=0.0).astype(float)
    if remove_local_piston:
        local_phase = local_phase.copy()
        local_phase[local_mask] -= np.mean(local_phase[local_mask])

    local_field = np.zeros(local_phase.shape, dtype=complex)
    local_field[local_mask] = np.exp(1j * local_phase[local_mask])
    local_rows, local_columns = local_field.shape
    if sampling_shape is None:
        sample_rows, sample_columns = local_rows, local_columns
    else:
        if not isinstance(sampling_shape, tuple) or len(sampling_shape) != 2:
            raise NativeShackHartmannError(
                "sampling_shape must contain two dimensions."
            )
        sample_rows = _positive_integer(
            sampling_shape[0],
            label="sampling_shape[0]",
        )
        sample_columns = _positive_integer(
            sampling_shape[1],
            label="sampling_shape[1]",
        )
        if sample_rows < local_rows or sample_columns < local_columns:
            raise NativeShackHartmannError(
                "sampling_shape must be at least as large as the illuminated "
                "lenslet bounding box."
            )

    padded_rows = padding * sample_rows
    padded_columns = padding * sample_columns
    padded = np.zeros((padded_rows, padded_columns), dtype=complex)
    y_start = (padded_rows - local_rows) // 2
    x_start = (padded_columns - local_columns) // 2
    padded[
        y_start : y_start + local_rows,
        x_start : x_start + local_columns,
    ] = local_field
    focal_field = np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(padded)))
    spot = np.abs(focal_field) ** 2
    total = float(np.sum(spot, dtype=np.float64))
    if total > 0.0:
        spot = spot / total
    return spot


def lenslet_spot_from_opd(
    residual_opd_m: np.ndarray,
    lenslet_mask: np.ndarray,
    *,
    wfs_wavelength_m: float,
    pad_factor: int = 8,
    remove_local_piston: bool = True,
    sampling_shape: tuple[int, int] | None = None,
) -> np.ndarray:
    """Form one native spot after explicit OPD-to-phase conversion."""

    wavelength_m = _positive_float(wfs_wavelength_m, label="wfs_wavelength_m")
    try:
        opd_m = np.asarray(residual_opd_m, dtype=float)
    except (TypeError, ValueError) as exc:
        raise NativeShackHartmannError(
            "residual_opd_m must be a numeric array."
        ) from exc
    phase_rad = 2.0 * np.pi * opd_m / wavelength_m
    return lenslet_spot_from_phase(
        phase_rad,
        lenslet_mask,
        pad_factor=pad_factor,
        remove_local_piston=remove_local_piston,
        sampling_shape=sampling_shape,
    )


def crop_center(image: np.ndarray, window_size: int | None = None) -> np.ndarray:
    """Preserve the historical centered square detector-window crop."""

    image_array = np.asarray(image)
    if image_array.ndim != 2:
        raise NativeShackHartmannError("image must be a 2-D array.")
    window = _optional_positive_integer(window_size, label="window_size")
    y_slice, x_slice = _center_slices(image_array.shape, window)
    return image_array[y_slice, x_slice]


def _validated_residual_opd(
    value: object,
    geometry: ShackHartmannGeometry,
) -> np.ndarray:
    try:
        opd_m = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise NativeShackHartmannError(
            "residual_opd_m must be a numeric array."
        ) from exc
    if opd_m.shape != geometry.pupil_shape:
        raise NativeShackHartmannError(
            f"residual_opd_m shape {opd_m.shape} does not match geometry "
            f"pupil_shape {geometry.pupil_shape}."
        )
    if np.any(np.isinf(opd_m)):
        raise NativeShackHartmannError(
            "residual_opd_m must not contain infinite values."
        )
    if not np.all(np.isfinite(opd_m[geometry.pupil_mask])):
        raise NativeShackHartmannError(
            "residual_opd_m must be finite throughout the illuminated pupil."
        )
    return opd_m


def _relative_lenslet_throughput(geometry: ShackHartmannGeometry) -> np.ndarray:
    illuminated = np.asarray(
        [np.count_nonzero(mask) for mask in geometry.subaperture_masks],
        dtype=float,
    )
    maximum = float(np.max(illuminated))
    if maximum <= 0.0:
        raise NativeShackHartmannError(
            "Geometry has no illuminated lenslet throughput."
        )
    return illuminated / maximum


def _bounding_box(mask: np.ndarray) -> tuple[slice, slice]:
    row_indices, column_indices = np.where(mask)
    if row_indices.size == 0:
        raise NativeShackHartmannError(
            "Cannot build a bounding box for an empty mask."
        )
    return (
        slice(int(row_indices.min()), int(row_indices.max()) + 1),
        slice(int(column_indices.min()), int(column_indices.max()) + 1),
    )


def _center_slices(
    image_shape: tuple[int, int],
    window_size: int | None,
) -> tuple[slice, slice]:
    rows, columns = (int(value) for value in image_shape)
    if window_size is None or window_size >= min(rows, columns):
        return slice(0, rows), slice(0, columns)
    half = window_size // 2
    center_y = rows // 2
    center_x = columns // 2
    if window_size % 2 == 0:
        return (
            slice(center_y - half, center_y + half),
            slice(center_x - half, center_x + half),
        )
    return (
        slice(center_y - half, center_y + half + 1),
        slice(center_x - half, center_x + half + 1),
    )


def _positive_integer(value: object, *, label: str) -> int:
    if not isinstance(value, Integral) or isinstance(value, (bool, np.bool_)):
        raise NativeShackHartmannError(f"{label} must be an integer.")
    result = int(value)
    if result < 1:
        raise NativeShackHartmannError(f"{label} must be at least 1.")
    return result


def _optional_positive_integer(value: object, *, label: str) -> int | None:
    if value is None:
        return None
    return _positive_integer(value, label=label)


def _positive_float(value: object, *, label: str) -> float:
    if not isinstance(value, Real) or isinstance(value, (bool, np.bool_)):
        raise NativeShackHartmannError(f"{label} must be a positive finite number.")
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise NativeShackHartmannError(f"{label} must be a positive finite number.")
    return result


def _readonly_float_array(values: object) -> np.ndarray:
    contiguous = np.ascontiguousarray(values, dtype=float)
    return np.frombuffer(contiguous.tobytes(order="C"), dtype=contiguous.dtype).reshape(
        contiguous.shape
    )
