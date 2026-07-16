"""Transparent NumPy science-PSF propagation backend.

This module owns the centered, zero-padded native FFT implementation.  The
backend-independent construction helper and sampling contract live in
``shwfs_ao.science.propagation``.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real

import numpy as np

from ...core.geometry import PupilGeometry
from ...core.hashing import component_config_hash
from ...core.types import PsfResult
from ...science.propagation import PsfSampling, SciencePropagationError


__all__ = ("NativeSciencePropagator",)


_BACKEND_NAME = "native"
_FFT_CONVENTION = "fftshift_fft2_ifftshift_centered-v1"
_NORMALIZATION = "unit_total_flux"


@dataclass(frozen=True, slots=True)
class NativeSciencePropagator:
    """Fixed-pupil NumPy implementation of the science propagator protocol."""

    pupil: PupilGeometry
    sampling: PsfSampling

    def __post_init__(self) -> None:
        if not isinstance(self.pupil, PupilGeometry):
            raise SciencePropagationError("pupil must be a PupilGeometry.")
        if not isinstance(self.sampling, PsfSampling):
            raise SciencePropagationError("sampling must be a PsfSampling.")

    @property
    def backend_name(self) -> str:
        """Repository backend identifier stored in every PSF result."""

        return _BACKEND_NAME

    @property
    def config_hash(self) -> str:
        """Stable identity of the bound pupil, sampling, and FFT policy."""

        return component_config_hash(
            "native.science_propagator",
            {
                "backend_name": _BACKEND_NAME,
                "pupil_geometry_hash": self.pupil.geometry_hash,
                "sampling": self.sampling,
                "fft_convention": _FFT_CONVENTION,
                "cropping": "none",
                "interpolation": "none",
                "normalization": _NORMALIZATION,
            },
        )

    def psf_from_opd(
        self,
        opd_m: np.ndarray,
        wavelength_m: float,
    ) -> PsfResult:
        """Propagate a pupil OPD map to a unit-total-flux science PSF."""

        wavelength = _positive_float(wavelength_m, label="wavelength_m")
        opd = _validated_opd(opd_m, self.pupil)

        phase_rad = opd.copy()
        with np.errstate(over="ignore", invalid="ignore"):
            phase_rad *= 2.0 * np.pi
            phase_rad /= wavelength
        if not np.all(np.isfinite(phase_rad[self.pupil.pupil_mask])):
            raise SciencePropagationError(
                "opd_m and wavelength_m must produce finite phase inside the pupil."
            )

        intensity = _normalized_fft_psf_from_phase(
            phase_rad,
            self.pupil.pupil_mask,
            pad_factor=self.sampling.pad_factor,
            require_square=False,
        )
        padded_shape = intensity.shape
        dx_m, dy_m = self.pupil.pixel_spacing_xy_m
        x_angle_rad = wavelength * np.fft.fftshift(
            np.fft.fftfreq(padded_shape[1], d=dx_m)
        )
        y_angle_rad = wavelength * np.fft.fftshift(
            np.fft.fftfreq(padded_shape[0], d=dy_m)
        )
        focal_scale_xy_rad = (
            wavelength / (padded_shape[1] * dx_m),
            wavelength / (padded_shape[0] * dy_m),
        )

        rows, columns = self.pupil.pupil_shape
        pad_rows = padded_shape[0] - rows
        pad_columns = padded_shape[1] - columns
        sampling_metadata = {
            "schema_id": "shwfs_ao.science.psf_result_sampling.v1",
            "pupil_geometry_hash": self.pupil.geometry_hash,
            "pupil_shape_px": self.pupil.pupil_shape,
            "pupil_pixel_spacing_xy_m": (dx_m, dy_m),
            "padded_fft_shape_px": padded_shape,
            "output_shape_px": padded_shape,
            "pad_factor": self.sampling.pad_factor,
            "padding_before_yx_px": (pad_rows // 2, pad_columns // 2),
            "padding_after_yx_px": (
                pad_rows - pad_rows // 2,
                pad_columns - pad_columns // 2,
            ),
            "focal_pixel_scale_xy_rad": focal_scale_xy_rad,
            "axis_layout": "x_columns_y_rows",
            "fft_convention": _FFT_CONVENTION,
            "cropping": "none",
            "interpolation": "none",
            "normalization": _NORMALIZATION,
        }
        return PsfResult(
            intensity=intensity,
            x_angle_rad=x_angle_rad,
            y_angle_rad=y_angle_rad,
            wavelength_m=wavelength,
            normalization=_NORMALIZATION,
            backend_name=_BACKEND_NAME,
            sampling_metadata=sampling_metadata,
        )


def _normalized_fft_psf_from_phase(
    phase_rad: np.ndarray,
    pupil: np.ndarray,
    pad_factor: int = 4,
    *,
    require_square: bool = True,
) -> np.ndarray:
    """Return the frozen native centered-FFT PSF for a phase and pupil mask.

    ``require_square=True`` retains the historical compatibility policy.
    Canonical OPD propagation sets it to false and pads rows and columns
    independently for rectangular physical pupils.
    """

    if pad_factor < 1:
        raise ValueError("pad_factor must be >= 1.")
    phase = np.asarray(phase_rad, dtype=float)
    mask = np.asarray(pupil, dtype=bool)
    if phase.ndim != 2:
        raise ValueError("phase_rad must be a 2-D array.")
    if mask.shape != phase.shape:
        raise ValueError(
            f"mask shape {mask.shape} != phase shape {phase.shape}."
        )
    if require_square and phase.shape[0] != phase.shape[1]:
        raise ValueError("phase_rad must be sampled on a square grid.")
    if not np.any(mask):
        raise ValueError("mask must contain at least one illuminated pupil sample.")
    if not np.all(np.isfinite(phase[mask])):
        raise ValueError("phase_rad must be finite inside the pupil.")

    pupil_field = np.zeros_like(phase, dtype=complex)
    pupil_field[mask] = np.exp(1j * phase[mask])

    rows, columns = phase.shape
    padded_rows = int(pad_factor * rows)
    padded_columns = int(pad_factor * columns)
    padded = np.zeros((padded_rows, padded_columns), dtype=complex)

    start_row = (padded_rows - rows) // 2
    start_column = (padded_columns - columns) // 2
    padded[
        start_row : start_row + rows,
        start_column : start_column + columns,
    ] = pupil_field

    focal_field = np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(padded)))
    psf = np.abs(focal_field) ** 2
    total = np.sum(psf)
    if total > 0:
        psf /= total
    return psf


def _validated_opd(value: object, pupil: PupilGeometry) -> np.ndarray:
    if not isinstance(value, np.ndarray):
        raise SciencePropagationError("opd_m must be a numpy.ndarray.")
    if value.dtype.kind in {"b", "c", "O", "S", "U", "V"}:
        raise SciencePropagationError("opd_m must contain real numeric values.")
    try:
        opd_m = np.array(value, dtype=float, copy=True)
    except (TypeError, ValueError) as exc:
        raise SciencePropagationError(
            "opd_m must contain real numeric values."
        ) from exc
    if opd_m.ndim != 2 or opd_m.shape != pupil.pupil_shape:
        raise SciencePropagationError(
            f"opd_m shape {opd_m.shape} must match pupil shape {pupil.pupil_shape}."
        )
    if np.any(np.isinf(opd_m)):
        raise SciencePropagationError("opd_m must not contain infinite values.")
    if not np.all(np.isfinite(opd_m[pupil.pupil_mask])):
        raise SciencePropagationError(
            "opd_m must be finite throughout the illuminated pupil."
        )
    return opd_m


def _positive_float(value: object, *, label: str) -> float:
    if not isinstance(value, Real) or isinstance(value, (bool, np.bool_)):
        raise SciencePropagationError(
            f"{label} must be a positive finite real number."
        )
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise SciencePropagationError(
            f"{label} must be a positive finite real number."
        )
    return result

