"""Zernike-mode utilities for compact AO/WFS simulations."""

from __future__ import annotations

import numpy as np
from scipy.special import eval_jacobi

from ..backends.native.modes import (
    generate_zernike_modes as _native_generate_zernike_modes,
    mode_inner_product as _native_mode_inner_product,
    number_of_zernike_modes as _native_number_of_zernike_modes,
    polar_pupil_coordinates as _native_polar_pupil_coordinates,
    synthesize_modes as _native_synthesize_modes,
    zernike_named_modes as _native_zernike_named_modes,
    zernike_nm as _native_zernike_nm,
    zernike_radial as _native_zernike_radial,
)
from ..core import wavefront as _wavefront


def make_pupil_grid(N: int = 256, diameter: float = 1.0):
    """Create a writable legacy circular pupil grid."""
    if N < 2:
        raise ValueError("N must be >= 2.")
    if diameter <= 0:
        raise ValueError("diameter must be positive.")

    x = np.linspace(-diameter / 2.0, diameter / 2.0, N)
    X, Y = np.meshgrid(x, x)
    rho, theta = _native_polar_pupil_coordinates(X, Y, diameter)
    mask = rho <= 1.0
    dx = float(x[1] - x[0])
    return (
        X,
        Y,
        np.array(rho, dtype=float, copy=True),
        np.array(theta, dtype=float, copy=True),
        np.array(mask, dtype=bool, copy=True),
        dx,
    )


def remove_piston(W: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Remove piston inside the pupil with legacy non-finite handling."""
    W2 = np.array(W, dtype=float, copy=True)
    finite = mask & np.isfinite(W2)
    if np.any(finite):
        centered = _wavefront.remove_piston(W2, finite)
        W2[finite] = centered[finite]
    W2[~mask] = np.nan
    return W2


def rms(W: np.ndarray, mask: np.ndarray) -> float:
    """RMS inside the pupil, ignoring legacy non-finite samples."""
    vals = np.asarray(W, dtype=float)[mask]
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return float("nan")
    return _wavefront.masked_rms(vals, np.ones(vals.shape, dtype=bool))


def zernike_named_modes(
    rho: np.ndarray,
    theta: np.ndarray,
    mask: np.ndarray,
    include_piston: bool = False,
    normalized: bool = True,
) -> dict[str, np.ndarray]:
    """
    Generate a small set of practical low-order Zernike-like modes.

    For high-precision AO modeling, use the general ``zernike_nm`` generator or
    a rigorously normalized external Zernike package.
    """
    pupil = np.asarray(mask, dtype=bool)
    modes = _native_zernike_named_modes(
        rho,
        theta,
        pupil,
        include_piston=include_piston,
        normalized=normalized,
    )
    return _legacy_nan_masked_modes(modes, pupil)


def synthesize_wavefront(
    modes: dict[str, np.ndarray],
    coeffs: dict[str, float],
    mask: np.ndarray,
    remove_mean: bool = True,
) -> np.ndarray:
    """Synthesize a wavefront from modal coefficients."""
    # Preserve the historical empty-mapping ``StopIteration`` behavior and
    # error wording while delegating the numerical sum to the native owner.
    first_mode = next(iter(modes.values()))
    for name, coeff in coeffs.items():
        if name not in modes:
            raise KeyError(f"Mode '{name}' is not available. Available modes: {list(modes)}")
    clean_modes = {
        name: np.nan_to_num(np.asarray(mode, dtype=float), nan=0.0)
        for name, mode in modes.items()
    }
    # ``first_mode`` is intentionally read above for compatibility; native
    # validation owns the actual common sampled shape.
    del first_mode
    W = np.array(
        _native_synthesize_modes(
            clean_modes,
            coeffs,
            np.asarray(mask, dtype=bool),
            remove_piston=False,
        ),
        dtype=float,
        copy=True,
    )
    W = np.where(mask, W, np.nan)
    if remove_mean:
        W = remove_piston(W, mask)
    return W


def zernike_radial(n: int, m: int, rho: np.ndarray) -> np.ndarray:
    """Radial part of the Zernike polynomial ``R_n^m(rho)``.

    Uses the Jacobi-polynomial identity instead of alternating factorial
    coefficients, avoiding catastrophic cancellation at high radial order.
    """
    return np.array(
        _native_zernike_radial(n, m, rho),
        dtype=float,
        copy=True,
    )


def zernike_nm(
    n: int,
    m: int,
    rho: np.ndarray,
    theta: np.ndarray,
    mask: np.ndarray,
    normalization: bool = True,
) -> np.ndarray:
    """Generate one real-valued Zernike mode on the pupil."""
    pupil_mask = np.asarray(mask, dtype=bool)
    mode = _native_zernike_nm(
        n,
        m,
        rho,
        theta,
        pupil_mask,
        normalization=normalization,
    )
    return np.where(pupil_mask, mode, np.nan)


def generate_zernike_modes(
    rho: np.ndarray,
    theta: np.ndarray,
    mask: np.ndarray,
    max_radial_order: int = 6,
    include_piston: bool = False,
    normalization: bool = True,
) -> dict[str, np.ndarray]:
    """Generate real-valued Zernike modes up to a given radial order."""
    pupil = np.asarray(mask, dtype=bool)
    modes = _native_generate_zernike_modes(
        rho,
        theta,
        pupil,
        max_radial_order=max_radial_order,
        include_piston=include_piston,
        normalization=normalization,
    )
    return _legacy_nan_masked_modes(modes, pupil)


def number_of_zernike_modes(max_radial_order: int, include_piston: bool = False) -> int:
    """Return the number of Zernike modes up to radial order n."""
    return _native_number_of_zernike_modes(
        max_radial_order,
        include_piston=include_piston,
    )


def zernike_inner_product(Z1: np.ndarray, Z2: np.ndarray, mask: np.ndarray) -> float:
    """Discrete mean inner product of two Zernike maps over the pupil."""
    values = (
        np.asarray(Z1, dtype=float)[mask]
        * np.asarray(Z2, dtype=float)[mask]
    )
    values = values[np.isfinite(values)]
    if values.size == 0:
        return float("nan")
    vector = values.reshape(1, -1)
    return _native_mode_inner_product(
        vector,
        np.ones(vector.shape, dtype=float),
        np.ones(vector.shape, dtype=bool),
    )


def zernike_gram_matrix(modes: dict[str, np.ndarray], mask: np.ndarray) -> tuple[np.ndarray, list[str]]:
    """Compute a discrete Gram matrix for a dictionary of Zernike modes."""
    names = list(modes.keys())
    G = np.zeros((len(names), len(names)), dtype=float)

    for i, ni in enumerate(names):
        for j, nj in enumerate(names):
            G[i, j] = zernike_inner_product(modes[ni], modes[nj], mask)

    return G, names


def _legacy_nan_masked_modes(
    modes: dict[str, np.ndarray],
    mask: np.ndarray,
) -> dict[str, np.ndarray]:
    """Restore writable NaN-outside arrays for installed legacy callers."""

    return {
        name: np.where(mask, np.asarray(mode, dtype=float), np.nan)
        for name, mode in modes.items()
    }
