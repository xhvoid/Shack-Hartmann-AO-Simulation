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

from ..core import wavefront as _wavefront


def circular_mask_from_grid(X: np.ndarray, Y: np.ndarray, diameter: float) -> np.ndarray:
    """Create a circular pupil mask from coordinate grids."""
    R = np.sqrt(X**2 + Y**2)
    return R <= diameter / 2.0


def remove_piston(screen: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Remove piston with legacy non-finite handling and mask the exterior."""
    out = np.array(screen, dtype=float, copy=True)
    finite = mask & np.isfinite(out)
    if np.any(finite):
        centered = _wavefront.remove_piston(out, finite)
        out[finite] = centered[finite]
    out[~mask] = np.nan
    return out


def rms(screen: np.ndarray, mask: np.ndarray) -> float:
    """RMS inside the pupil, ignoring legacy non-finite samples."""
    vals = np.asarray(screen, dtype=float)[mask]
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return float("nan")
    return _wavefront.masked_rms(vals, np.ones(vals.shape, dtype=bool))


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
    mask_output: bool = True,
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
    mask_output:
        If True, set samples outside the pupil to NaN. If False, return the
        complete finite periodic screen after removing the pupil piston. Use a
        full output for frozen-flow translation and apply the pupil mask only
        after shifting.

    Returns
    -------
    phase:
        Atmospheric phase screen in radians. Values outside the pupil are NaN
        when ``mask_output=True`` and finite when ``mask_output=False``.
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

    phase -= _wavefront.masked_mean(phase, mask)

    if normalize_rms:
        if target_rms_rad is None:
            target_rms_rad = np.sqrt(1.03 * (diameter / r0) ** (5.0 / 3.0))
        if target_rms_rad < 0:
            raise ValueError("target_rms_rad must be non-negative.")

        current = _wavefront.masked_rms(phase, mask)
        if np.isfinite(current) and current > 0:
            phase = phase * (target_rms_rad / current)
            phase -= _wavefront.masked_mean(phase, mask)

    if mask_output:
        phase = np.where(mask, phase, np.nan)

    return phase, X, Y, mask


def phase_to_opd(phase_rad: np.ndarray, wavelength: float) -> np.ndarray:
    """Convert phase in radians to optical path difference in meters."""
    return _wavefront.phase_to_opd(phase_rad, wavelength)


def opd_to_phase(opd_m: np.ndarray, wavelength: float) -> np.ndarray:
    """Convert optical path difference in meters to phase in radians."""
    return _wavefront.opd_to_phase(opd_m, wavelength)


def frozen_flow_shift(
    screen: np.ndarray,
    shift_x_pix: int = 0,
    shift_y_pix: int = 0,
    mask: np.ndarray | None = None,
    remove_mean: bool = True,
) -> np.ndarray:
    """
    Shift a complete finite phase screen with periodic boundary conditions.

    The input must be finite everywhere. A pupil-masked screen does not contain
    the exterior atmospheric phase needed after translation, so NaN/Inf inputs
    are rejected instead of being interpreted as zero phase. Generate a full
    screen with ``fourier_phase_screen(..., mask_output=False)`` and supply the
    pupil mask here to mask and remove piston after the shift.
    """
    full = np.asarray(screen, dtype=float)
    if full.ndim != 2:
        raise ValueError("screen must be a 2-D phase map.")
    if not np.all(np.isfinite(full)):
        raise ValueError(
            "screen must be finite everywhere for frozen flow; generate a full "
            "screen with fourier_phase_screen(..., mask_output=False)."
        )

    shifted = np.roll(
        np.roll(full, int(shift_y_pix), axis=0),
        int(shift_x_pix),
        axis=1,
    )

    if mask is not None:
        pupil = np.asarray(mask, dtype=bool)
        if pupil.shape != shifted.shape:
            raise ValueError("mask must have the same shape as screen.")
        shifted = np.where(pupil, shifted, np.nan)
        if remove_mean:
            shifted = remove_piston(shifted, pupil)

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
    if not np.isfinite(delta) or delta <= 0:
        raise ValueError("delta must be positive.")
    if not np.all(np.isfinite([vx, vy, dt])):
        raise ValueError("vx, vy, and dt must be finite.")

    shift_x_pix = int(np.round(vx * dt / delta))
    shift_y_pix = int(np.round(vy * dt / delta))

    return frozen_flow_shift(
        screen,
        shift_x_pix=shift_x_pix,
        shift_y_pix=shift_y_pix,
        mask=mask,
        remove_mean=remove_mean,
    )
