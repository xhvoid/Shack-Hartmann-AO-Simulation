"""PSF and Strehl utilities for compact AO simulations."""

from __future__ import annotations

import numpy as np


def compute_psf_from_phase(
    phase_rad: np.ndarray,
    mask: np.ndarray,
    pad_factor: int = 4,
) -> np.ndarray:
    """Compute focal-plane PSF from pupil-plane phase."""
    if pad_factor < 1:
        raise ValueError("pad_factor must be >= 1.")

    phase_rad = np.asarray(phase_rad, dtype=float)
    mask = np.asarray(mask, dtype=bool)
    N = phase_rad.shape[0]

    pupil_field = np.zeros_like(phase_rad, dtype=complex)
    phase_clean = np.nan_to_num(phase_rad, nan=0.0)
    pupil_field[mask] = np.exp(1j * phase_clean[mask])

    pad_N = int(pad_factor * N)
    padded = np.zeros((pad_N, pad_N), dtype=complex)

    start = (pad_N - N) // 2
    end = start + N
    padded[start:end, start:end] = pupil_field

    focal_field = np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(padded)))
    psf = np.abs(focal_field) ** 2
    total = np.sum(psf)
    if total > 0:
        psf /= total

    return psf


def strehl_ratio(
    phase_rad: np.ndarray,
    mask: np.ndarray,
    pad_factor: int = 4,
) -> float:
    """Compute approximate Strehl ratio from PSF peak ratio."""
    psf_aberrated = compute_psf_from_phase(phase_rad, mask, pad_factor=pad_factor)
    psf_ideal = compute_psf_from_phase(np.zeros_like(phase_rad), mask, pad_factor=pad_factor)
    peak_ideal = np.max(psf_ideal)
    if peak_ideal <= 0:
        return float("nan")
    return float(np.max(psf_aberrated) / peak_ideal)


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
    vals = np.asarray(phase_rad, dtype=float)[mask]
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return float("nan")
    vals = vals - np.mean(vals)
    sigma2 = np.mean(vals**2)
    return float(np.exp(-sigma2))


def phase_for_science_wavelength(opd_m: np.ndarray, wavelength_sci: float) -> np.ndarray:
    """
    Convert OPD to phase at science wavelength.

    Useful when WFS wavelength and science wavelength differ.
    """
    if wavelength_sci <= 0:
        raise ValueError("wavelength_sci must be positive.")
    return 2.0 * np.pi * np.asarray(opd_m, dtype=float) / wavelength_sci
