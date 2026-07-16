"""PSF and Strehl utilities for compact AO simulations."""

from __future__ import annotations

import numpy as np

from ..core import wavefront as _wavefront
from ..science.metrics import (
    _peak_strehl_from_discrete_flux_arrays as _canonical_peak_strehl,
    marechal_strehl_from_opd as _marechal_strehl_from_opd,
)
from ..backends.native.propagation import (
    _normalized_fft_psf_from_phase as _canonical_fft_psf_from_phase,
)


def compute_psf_from_phase(
    phase_rad: np.ndarray,
    mask: np.ndarray,
    pad_factor: int = 4,
) -> np.ndarray:
    """Compute a normalized focal-plane PSF from pupil-plane phase.

    Phase must be finite at every illuminated pupil sample. Non-finite values
    outside ``mask`` are ignored, which supports the repository's NaN-outside
    pupil convention without silently turning an invalid interior sample into
    ideal zero phase.
    """
    if pad_factor < 1:
        raise ValueError("pad_factor must be >= 1.")

    phase_rad = np.asarray(phase_rad, dtype=float)
    mask = np.asarray(mask, dtype=bool)
    if phase_rad.ndim != 2:
        raise ValueError("phase_rad must be a 2-D array.")
    if mask.shape != phase_rad.shape:
        raise ValueError(f"mask shape {mask.shape} != phase shape {phase_rad.shape}.")
    if phase_rad.shape[0] != phase_rad.shape[1]:
        raise ValueError("phase_rad must be sampled on a square grid.")
    if not np.any(mask):
        raise ValueError("mask must contain at least one illuminated pupil sample.")
    _wavefront.validate_masked_finite(phase_rad, mask, "phase_rad")
    return _canonical_fft_psf_from_phase(
        phase_rad,
        mask,
        pad_factor=pad_factor,
    )


def strehl_ratio(
    phase_rad: np.ndarray,
    mask: np.ndarray,
    pad_factor: int = 4,
) -> float:
    """Compute approximate Strehl ratio from PSF peak ratio."""
    psf_aberrated = compute_psf_from_phase(phase_rad, mask, pad_factor=pad_factor)
    psf_ideal = compute_psf_from_phase(np.zeros_like(phase_rad), mask, pad_factor=pad_factor)
    return _canonical_peak_strehl(psf_aberrated, psf_ideal)


def radial_profile(psf: np.ndarray, center: tuple[float, float] | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Compute azimuthally averaged PSF radial profile."""
    psf = np.asarray(psf, dtype=float)
    ny, nx = psf.shape

    if center is None:
        center = (nx // 2, ny // 2)

    x = np.arange(nx)
    y = np.arange(ny)
    X, Y = np.meshgrid(x, y)

    r = np.sqrt((X - center[0]) ** 2 + (Y - center[1]) ** 2)
    r_int = r.astype(int)

    counts = np.bincount(r_int.ravel())
    sums = np.bincount(r_int.ravel(), weights=psf.ravel())
    profile = np.divide(sums, counts, out=np.zeros_like(sums, dtype=float), where=counts > 0)
    radius = np.arange(len(profile))

    return radius, profile


def marechal_strehl(phase_rad: np.ndarray, mask: np.ndarray) -> float:
    """Marechal approximation: S ~= exp(-sigma_phi^2)."""
    phase = np.asarray(phase_rad, dtype=float)
    pupil = np.asarray(mask, dtype=bool)
    if phase.shape != pupil.shape:
        raise ValueError(f"mask shape {pupil.shape} != phase shape {phase.shape}.")
    vals = phase[pupil]
    if vals.size == 0:
        return float("nan")
    # Choosing wavelength 2*pi maps the historical phase array numerically
    # onto OPD while delegating the piston-removed RMS/Marechal calculation to
    # the canonical SI implementation: phase = 2*pi*opd/wavelength = opd.
    return _marechal_strehl_from_opd(phase, pupil, 2.0 * np.pi)


def phase_for_science_wavelength(opd_m: np.ndarray, wavelength_sci: float) -> np.ndarray:
    """
    Convert OPD to phase at science wavelength.

    Useful when WFS wavelength and science wavelength differ.
    """
    return _wavefront.opd_to_phase(opd_m, wavelength_sci)
