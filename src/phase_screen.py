"""
Atmospheric phase-screen utilities for compact AO simulations.

The generator below uses a Fourier-domain von Karman / Kolmogorov-like
phase power spectrum. By default, the generated phase screen is RMS-normalized
inside the pupil so that it is robust for controlled reconstruction tests.

For physically interpreted runs, use seeing_to_r0/r0 wavelength scaling and
validate the generated screens with structure-function/PSF checks before
claiming calibrated AO performance.
"""

from __future__ import annotations

import numpy as np


def circular_mask_from_grid(X: np.ndarray, Y: np.ndarray, diameter: float) -> np.ndarray:
    """Create a circular pupil mask from coordinate grids."""
    R = np.sqrt(X**2 + Y**2)
    return R <= diameter / 2.0


def remove_piston(screen: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Remove piston inside the aperture and set values outside to NaN."""
    out = np.array(screen, dtype=float, copy=True)
    finite = mask & np.isfinite(out)
    if np.any(finite):
        out[finite] -= np.mean(out[finite])
    out[~mask] = np.nan
    return out


def rms(screen: np.ndarray, mask: np.ndarray) -> float:
    """RMS inside the pupil after mean removal."""
    vals = np.asarray(screen, dtype=float)[mask]
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return float("nan")
    vals = vals - np.mean(vals)
    return float(np.sqrt(np.mean(vals**2)))


def r0_from_seeing(seeing_arcsec: float, wavelength: float = 500e-9) -> float:
    """
    Convert seeing FWHM to Fried parameter r0.

    Parameters
    ----------
    seeing_arcsec:
        Seeing FWHM in arcseconds.
    wavelength:
        Wavelength in meters at which the seeing is quoted.
    """
    if seeing_arcsec <= 0:
        raise ValueError("seeing_arcsec must be positive.")
    if wavelength <= 0:
        raise ValueError("wavelength must be positive.")

    seeing_rad = seeing_arcsec / 206265.0
    return float(0.98 * wavelength / seeing_rad)


def scale_r0_with_wavelength(
    r0_ref: float,
    wavelength: float,
    wavelength_ref: float = 500e-9,
) -> float:
    """
    Scale Fried parameter with wavelength.

        r0(lambda) = r0(lambda_ref) * (lambda/lambda_ref)^(6/5)
    """
    if r0_ref <= 0:
        raise ValueError("r0_ref must be positive.")
    if wavelength <= 0 or wavelength_ref <= 0:
        raise ValueError("wavelength and wavelength_ref must be positive.")

    return float(r0_ref * (wavelength / wavelength_ref) ** (6.0 / 5.0))


def fourier_phase_screen(
    N: int = 256,
    delta: float = 0.01,
    r0: float = 0.15,
    L0: float | None = 25.0,
    diameter: float = 1.0,
    wavelength: float = 500e-9,
    seed: int | None = 1,
    target_rms_rad: float | None = None,
    normalize_rms: bool = True,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Generate a demo von Karman / Kolmogorov-like atmospheric phase screen.

    Parameters
    ----------
    N:
        Grid size.
    delta:
        Grid spacing in meters.
    r0:
        Fried parameter in meters, at the phase-screen wavelength.
    L0:
        Outer scale in meters. Use ``np.inf`` or ``None`` for a pure
        Kolmogorov-like low-frequency spectrum.
    diameter:
        Pupil diameter in meters.
    wavelength:
        Wavelength in meters. Kept for parameter bookkeeping; the returned
        screen is phase in radians at this wavelength.
    seed:
        Random seed.
    target_rms_rad:
        Target RMS phase in radians inside the pupil. Used only if
        ``normalize_rms=True``. If ``None``, an approximate atmospheric RMS
        scaling sqrt(1.03 * (D/r0)^(5/3)) is used.
    normalize_rms:
        If True, rescale the generated screen to a target pupil RMS. This is
        recommended for controlled learning/reconstruction tests. If False,
        the raw Fourier realization is returned after piston removal; validate
        its structure function before using it as a calibrated atmosphere.

    Returns
    -------
    phase:
        Atmospheric phase screen in radians, with NaN outside the pupil.
    X, Y:
        Coordinate grids in meters.
    mask:
        Circular pupil mask.

    Notes
    -----
    The spectral shape follows the usual atmospheric phase PSD form:

        PSD_phi(f) ~ 0.023 r0^(-5/3) (f^2 + f0^2)^(-11/6)

    with f0 = 1/L0. This is a compact learning simulator, not a replacement
    for a calibrated AO propagation code.
    """
    if N <= 0:
        raise ValueError("N must be positive.")
    if delta <= 0:
        raise ValueError("delta must be positive.")
    if r0 <= 0:
        raise ValueError("r0 must be positive.")
    if diameter <= 0:
        raise ValueError("diameter must be positive.")
    if wavelength <= 0:
        raise ValueError("wavelength must be positive.")

    rng = np.random.default_rng(seed)

    fx = np.fft.fftfreq(N, d=delta)
    fy = np.fft.fftfreq(N, d=delta)
    FX, FY = np.meshgrid(fx, fy)
    f = np.sqrt(FX**2 + FY**2)

    if L0 is None or np.isinf(L0):
        f0 = 0.0
    else:
        if L0 <= 0:
            raise ValueError("L0 must be positive, np.inf, or None.")
        f0 = 1.0 / L0

    with np.errstate(divide="ignore", invalid="ignore"):
        psd = 0.023 * r0 ** (-5.0 / 3.0) * (f**2 + f0**2) ** (-11.0 / 6.0)
    psd[0, 0] = 0.0
    psd[~np.isfinite(psd)] = 0.0

    random_complex = rng.normal(size=(N, N)) + 1j * rng.normal(size=(N, N))
    fourier_coeff = random_complex * np.sqrt(psd)
    phase = np.fft.ifft2(fourier_coeff).real

    x = (np.arange(N) - N // 2) * delta
    X, Y = np.meshgrid(x, x)
    mask = circular_mask_from_grid(X, Y, diameter)

    phase = remove_piston(phase, mask)

    if normalize_rms:
        if target_rms_rad is None:
            target_rms_rad = np.sqrt(1.03 * (diameter / r0) ** (5.0 / 3.0))
        if target_rms_rad < 0:
            raise ValueError("target_rms_rad must be non-negative.")

        current = rms(phase, mask)
        if np.isfinite(current) and current > 0:
            phase = phase * (target_rms_rad / current)
            phase = remove_piston(phase, mask)

    return phase, X, Y, mask


def phase_to_opd(phase_rad: np.ndarray, wavelength: float) -> np.ndarray:
    """Convert phase in radians to optical path difference in meters."""
    if wavelength <= 0:
        raise ValueError("wavelength must be positive.")
    return np.asarray(phase_rad, dtype=float) * wavelength / (2.0 * np.pi)


def opd_to_phase(opd_m: np.ndarray, wavelength: float) -> np.ndarray:
    """Convert optical path difference in meters to phase in radians."""
    if wavelength <= 0:
        raise ValueError("wavelength must be positive.")
    return 2.0 * np.pi * np.asarray(opd_m, dtype=float) / wavelength


def frozen_flow_shift(
    screen: np.ndarray,
    shift_x_pix: int = 0,
    shift_y_pix: int = 0,
    mask: np.ndarray | None = None,
    remove_mean: bool = True,
) -> np.ndarray:
    """
    Shift a phase screen with periodic boundary conditions.

    This is useful for a toy frozen-flow atmosphere model.
    """
    shifted = np.roll(
        np.roll(np.nan_to_num(screen, nan=0.0), int(shift_y_pix), axis=0),
        int(shift_x_pix),
        axis=1,
    )

    if mask is not None:
        shifted = np.where(mask, shifted, np.nan)
        if remove_mean:
            shifted = remove_piston(shifted, mask)

    return shifted


def frozen_flow_shift_physical(
    screen: np.ndarray,
    vx: float,
    vy: float,
    dt: float,
    delta: float,
    mask: np.ndarray | None = None,
    remove_mean: bool = True,
) -> np.ndarray:
    """
    Shift a phase screen using physical wind velocity.

    Parameters
    ----------
    vx, vy:
        Wind velocity in m/s.
    dt:
        Time in seconds relative to the initial phase screen.
    delta:
        Phase-screen sampling in m/pixel.
    mask:
        Optional pupil mask. If given, the shifted screen is re-masked and
        piston is removed inside the pupil.
    """
    if delta <= 0:
        raise ValueError("delta must be positive.")

    shift_x_pix = int(np.round(vx * dt / delta))
    shift_y_pix = int(np.round(vy * dt / delta))

    return frozen_flow_shift(
        screen,
        shift_x_pix=shift_x_pix,
        shift_y_pix=shift_y_pix,
        mask=mask,
        remove_mean=remove_mean,
    )
