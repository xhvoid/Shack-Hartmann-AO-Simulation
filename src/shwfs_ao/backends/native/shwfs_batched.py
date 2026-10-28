"""Batched native Shack--Hartmann optics on a compact lenslet geometry.

:class:`BatchedNativeShackHartmannOptics` reproduces the arithmetic of
:class:`~.shwfs.NativeShackHartmannOptics` lenslet by lenslet -- local piston
removal over the lenslet's illuminated samples, the illuminated bounding box
centred in a ``pad_factor`` times nominal-canvas array, the centred FFT, unit
normalization over the full canvas, the centred detector window, and the
window capture fraction -- but transforms lenslets in bounded batches and reads
each lenslet's samples from its cell bounds instead of a full-pupil mask.

Every lenslet's spot depends only on the residual OPD inside that lenslet's
own samples (``measurement_locality``).  Batch size is an execution setting:
it is not part of the backend identity and does not change any lenslet's
result, because each lenslet is transformed and normalized on its own.
"""

from __future__ import annotations

import math
from numbers import Integral, Real
from typing import Final

import numpy as np

from ...core.hashing import component_config_hash
from ...core.types import DetectorPlaneSampling, SpotIntensityResult
from ...core.wavefront import opd_to_phase
from ...wfs.shack_hartmann.compact_geometry import CompactShackHartmannGeometry
from ...wfs.shack_hartmann.optics import (
    make_detector_plane_sampling,
    validate_spot_intensity_result,
)
from .shwfs import NativeShackHartmannError, nominal_lenslet_sampling_shape


__all__ = (
    "DEFAULT_LENSLET_BATCH_SIZE",
    "MEASUREMENT_LOCALITY",
    "BatchedNativeShackHartmannOptics",
)


DEFAULT_LENSLET_BATCH_SIZE: Final = 512
MEASUREMENT_LOCALITY: Final = "lenslet_pixels_v1"
_BACKEND_NAME: Final = "native"
_FFT_CONVENTION: Final = "fftshift_fft2_ifftshift_centered-v1"
_SCRATCH_LIMIT_BYTES: Final = 64 * 1024**2


def _positive_int(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or int(value) < 1:
        raise NativeShackHartmannError(f"{label} must be a positive integer.")
    return int(value)


def _center_slice(length: int, window: int | None) -> slice:
    if window is None or window >= length:
        return slice(0, length)
    half = window // 2
    center = length // 2
    if window % 2 == 0:
        return slice(center - half, center + half)
    return slice(center - half, center + half + 1)


class BatchedNativeShackHartmannOptics:
    """Native lenslet diffraction for a :class:`CompactShackHartmannGeometry`."""

    _geometry: CompactShackHartmannGeometry
    _wavelength_m: float
    _pad_factor: int
    _detector_window_px: int | None
    _batch_size: int
    _sampling_shape: tuple[int, int]
    _padded_shape: tuple[int, int]
    _window_slices: tuple[slice, slice]
    _sampling: DetectorPlaneSampling
    _boxes: tuple[tuple[int, int, int, int], ...]
    _local_masks: tuple[np.ndarray, ...]
    _offsets: tuple[tuple[int, int], ...]
    _pupil_relative_throughput: np.ndarray
    _config_hash: str

    def __init__(
        self,
        geometry: CompactShackHartmannGeometry,
        wfs_wavelength_m: float,
        *,
        pad_factor: int = 8,
        detector_window_px: int | None = None,
        batch_size: int = DEFAULT_LENSLET_BATCH_SIZE,
    ) -> None:
        if not isinstance(geometry, CompactShackHartmannGeometry):
            raise NativeShackHartmannError(
                "geometry must be a CompactShackHartmannGeometry."
            )
        if isinstance(wfs_wavelength_m, bool) or not isinstance(wfs_wavelength_m, Real):
            raise NativeShackHartmannError("wfs_wavelength_m must be a real number.")
        wavelength = float(wfs_wavelength_m)
        if not math.isfinite(wavelength) or wavelength <= 0.0:
            raise NativeShackHartmannError("wfs_wavelength_m must be positive.")
        padding = _positive_int(pad_factor, label="pad_factor")
        window = (
            None
            if detector_window_px is None
            else _positive_int(detector_window_px, label="detector_window_px")
        )
        self._batch_size = _positive_int(batch_size, label="batch_size")
        sampling_shape = nominal_lenslet_sampling_shape(
            geometry.pupil_shape, geometry.n_lenslets_across
        )
        padded_shape = (padding * sampling_shape[0], padding * sampling_shape[1])
        y_slice = _center_slice(padded_shape[0], window)
        x_slice = _center_slice(padded_shape[1], window)
        window_shape = (y_slice.stop - y_slice.start, x_slice.stop - x_slice.start)
        reference_pixel_xy = (
            float(padded_shape[1] // 2 - x_slice.start),
            float(padded_shape[0] // 2 - y_slice.start),
        )
        dx_m = float(geometry.x_m[0, 1] - geometry.x_m[0, 0])
        dy_m = float(geometry.y_m[1, 0] - geometry.y_m[0, 0])
        sampling = make_detector_plane_sampling(
            window_shape_px=window_shape,
            pixel_scale_rad=(
                wavelength / (padded_shape[1] * dx_m),
                wavelength / (padded_shape[0] * dy_m),
            ),
            reference_pixel_xy=reference_pixel_xy,
        )
        # Per-lenslet illuminated bounding boxes, local masks within them, and
        # canvas offsets: exactly what the dense path derives per frame from a
        # full-pupil mask, computed once from the compact cells.
        boxes = []
        local_masks = []
        offsets = []
        for mask, (r0, _r1, c0, _c1) in zip(geometry.lenslet_masks, geometry.lenslet_bounds_rc):
            rows, columns = np.nonzero(mask)
            br0, br1 = int(rows.min()), int(rows.max()) + 1
            bc0, bc1 = int(columns.min()), int(columns.max()) + 1
            local = np.array(mask[br0:br1, bc0:bc1], dtype=bool)
            if local.shape[0] > sampling_shape[0] or local.shape[1] > sampling_shape[1]:
                raise NativeShackHartmannError(
                    "a lenslet's illuminated box exceeds the nominal sampling canvas."
                )
            boxes.append((int(r0) + br0, int(r0) + br1, int(c0) + bc0, int(c0) + bc1))
            local_masks.append(local)
            offsets.append(
                (
                    (padded_shape[0] - local.shape[0]) // 2,
                    (padded_shape[1] - local.shape[1]) // 2,
                )
            )
        illuminated = geometry.illuminated_counts.astype(float)
        self._geometry = geometry
        self._wavelength_m = wavelength
        self._pad_factor = padding
        self._detector_window_px = window
        self._sampling_shape = sampling_shape
        self._padded_shape = padded_shape
        self._window_slices = (y_slice, x_slice)
        self._sampling = sampling
        self._boxes = tuple(boxes)
        self._local_masks = tuple(local_masks)
        self._offsets = tuple(offsets)
        throughput = illuminated / float(np.max(illuminated))
        throughput.flags.writeable = False
        self._pupil_relative_throughput = throughput
        self._config_hash = component_config_hash(
            "native.shack_hartmann_optics.compact_batched",
            {
                "geometry_hash": geometry.geometry_hash,
                "wfs_wavelength_m": wavelength,
                "pad_factor": padding,
                "detector_window_px": window,
                "nominal_lenslet_sampling_shape": sampling_shape,
                "padded_fft_shape": padded_shape,
                "window_origin_yx": (y_slice.start, x_slice.start),
                "detector_sampling_hash": sampling.sampling_hash,
                "fft_convention": _FFT_CONVENTION,
                "remove_local_piston": True,
                "relative_throughput_semantics": "detector_window_capture_fraction",
                "measurement_locality": MEASUREMENT_LOCALITY,
            },
        )

    @property
    def backend_name(self) -> str:
        return _BACKEND_NAME

    @property
    def config_hash(self) -> str:
        return self._config_hash

    @property
    def geometry(self) -> CompactShackHartmannGeometry:
        return self._geometry

    @property
    def geometry_hash(self) -> str:
        return self._geometry.geometry_hash

    @property
    def wfs_wavelength_m(self) -> float:
        return self._wavelength_m

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
        return self._sampling

    @property
    def subaperture_ids(self) -> tuple[str, ...]:
        return self._geometry.subaperture_ids

    @property
    def pupil_relative_throughput(self) -> np.ndarray:
        return self._pupil_relative_throughput

    @property
    def measurement_locality(self) -> str:
        """Each lenslet's result depends only on its own pupil samples."""

        return MEASUREMENT_LOCALITY

    @property
    def batch_size(self) -> int:
        return self._batch_size

    @property
    def batch_scratch_bytes(self) -> int:
        """Peak scratch of one batch: complex canvas, FFT output, intensity."""

        canvas = self._padded_shape[0] * self._padded_shape[1]
        return int(self._batch_size * canvas * (16 + 16 + 16 + 8))

    def spot_intensities(self, residual_opd_m: np.ndarray) -> SpotIntensityResult:
        """Unit-sum detector-window spots for every retained lenslet."""

        opd_m = np.asarray(residual_opd_m, dtype=float)
        geometry = self._geometry
        if opd_m.shape != geometry.pupil_shape:
            raise NativeShackHartmannError(
                f"residual_opd_m shape {opd_m.shape} does not match "
                f"{geometry.pupil_shape}."
            )
        if np.any(np.isinf(opd_m)):
            raise NativeShackHartmannError("residual_opd_m must not be infinite.")
        if not np.all(np.isfinite(opd_m[geometry.pupil_mask])):
            raise NativeShackHartmannError(
                "residual_opd_m must be finite throughout the illuminated pupil."
            )
        phase_rad = opd_to_phase(opd_m, self._wavelength_m)
        y_slice, x_slice = self._window_slices
        count = geometry.n_subapertures
        spots: list[np.ndarray] = [np.empty(0)] * count
        capture = np.empty(count, dtype=float)
        rows, columns = self._padded_shape
        batch = max(1, min(self._batch_size, _SCRATCH_LIMIT_BYTES // max(1, rows * columns * 56)))
        for start in range(0, count, batch):
            stop = min(count, start + batch)
            canvas = np.zeros((stop - start, rows, columns), dtype=complex)
            for local_index, index in enumerate(range(start, stop)):
                br0, br1, bc0, bc1 = self._boxes[index]
                mask = self._local_masks[index]
                local_phase = np.nan_to_num(phase_rad[br0:br1, bc0:bc1], nan=0.0).astype(
                    float
                )
                local_phase = local_phase.copy()
                local_phase[mask] -= np.mean(local_phase[mask])
                y0, x0 = self._offsets[index]
                block = canvas[local_index, y0 : y0 + mask.shape[0], x0 : x0 + mask.shape[1]]
                block[mask] = np.exp(1j * local_phase[mask])
            focal = np.fft.fftshift(
                np.fft.fft2(np.fft.ifftshift(canvas, axes=(-2, -1)), axes=(-2, -1)),
                axes=(-2, -1),
            )
            intensity = np.abs(focal) ** 2
            del focal, canvas
            for local_index, index in enumerate(range(start, stop)):
                spot = intensity[local_index]
                total = float(np.sum(spot, dtype=np.float64))
                if total > 0.0:
                    spot = spot / total
                window_spot = np.asarray(spot[y_slice, x_slice], dtype=float)
                window_total = float(np.sum(window_spot, dtype=np.float64))
                if not math.isfinite(window_total) or window_total <= 0.0:
                    raise NativeShackHartmannError(
                        f"Lenslet {geometry.subaperture_ids[index]!r} has no finite "
                        "intensity inside the configured detector window."
                    )
                capture[index] = float(np.clip(window_total, 0.0, 1.0))
                spots[index] = window_spot / window_total
        window_rows, window_columns = self._sampling.window_shape_px
        reference_x, reference_y = self._sampling.reference_pixel_xy
        x_axis = np.arange(window_columns, dtype=float) - reference_x
        y_axis = np.arange(window_rows, dtype=float) - reference_y
        result = SpotIntensityResult(
            unit_sum_spots=tuple(spots),
            subaperture_ids=geometry.subaperture_ids,
            relative_throughput=capture,
            x_px=tuple(x_axis for _ in spots),
            y_px=tuple(y_axis for _ in spots),
            sampling=self._sampling,
            normalization="unit_sum_per_subaperture",
        )
        return validate_spot_intensity_result(result, geometry, sampling=self._sampling)
