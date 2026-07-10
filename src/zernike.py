"""Zernike-mode utilities for compact AO/WFS simulations."""

from __future__ import annotations

import math
import numpy as np


def make_pupil_grid(N: int = 256, diameter: float = 1.0):
    """Create a circular pupil grid."""
    if N < 2:
        raise ValueError("N must be >= 2.")
    if diameter <= 0:
        raise ValueError("diameter must be positive.")

    x = np.linspace(-diameter / 2.0, diameter / 2.0, N)
    X, Y = np.meshgrid(x, x)

    R = np.sqrt(X**2 + Y**2)
    rho = R / (diameter / 2.0)
    theta = np.arctan2(Y, X)

    mask = rho <= 1.0
    dx = float(x[1] - x[0])
    return X, Y, rho, theta, mask, dx


def remove_piston(W: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Remove piston inside the pupil."""
    W2 = np.array(W, dtype=float, copy=True)
    finite = mask & np.isfinite(W2)
    if np.any(finite):
        W2[finite] -= np.nanmean(W2[finite])
    W2[~mask] = np.nan
    return W2


def rms(W: np.ndarray, mask: np.ndarray) -> float:
    """RMS of a wavefront inside the pupil after piston removal."""
    vals = np.asarray(W, dtype=float)[mask]
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return float("nan")
    vals = vals - np.mean(vals)
    return float(np.sqrt(np.mean(vals**2)))


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
    x = rho * np.cos(theta)
    y = rho * np.sin(theta)
    r2 = rho**2

    if normalized:
        modes = {
            "piston": np.ones_like(rho),
            "tip_x": 2.0 * x,
            "tip_y": 2.0 * y,
            "defocus": np.sqrt(3.0) * (2.0 * r2 - 1.0),
            "astig_45": np.sqrt(6.0) * 2.0 * x * y,
            "astig_0": np.sqrt(6.0) * (x**2 - y**2),
            "coma_x": np.sqrt(8.0) * (3.0 * r2 - 2.0) * x,
            "coma_y": np.sqrt(8.0) * (3.0 * r2 - 2.0) * y,
            "trefoil_x": np.sqrt(8.0) * (x**3 - 3.0 * x * y**2),
            "trefoil_y": np.sqrt(8.0) * (3.0 * x**2 * y - y**3),
            "spherical": np.sqrt(5.0) * (6.0 * r2**2 - 6.0 * r2 + 1.0),
        }
    else:
        modes = {
            "piston": np.ones_like(rho),
            "tip_x": x,
            "tip_y": y,
            "defocus": 2.0 * r2 - 1.0,
            "astig_45": 2.0 * x * y,
            "astig_0": x**2 - y**2,
            "coma_x": (3.0 * r2 - 2.0) * x,
            "coma_y": (3.0 * r2 - 2.0) * y,
            "trefoil_x": x**3 - 3.0 * x * y**2,
            "trefoil_y": 3.0 * x**2 * y - y**3,
            "spherical": 6.0 * r2**2 - 6.0 * r2 + 1.0,
        }

    if not include_piston:
        modes.pop("piston")

    for key in list(modes.keys()):
        modes[key] = np.where(mask, np.asarray(modes[key], dtype=float), np.nan)

    return modes


def synthesize_wavefront(
    modes: dict[str, np.ndarray],
    coeffs: dict[str, float],
    mask: np.ndarray,
    remove_mean: bool = True,
) -> np.ndarray:
    """Synthesize a wavefront from modal coefficients."""
    first_mode = next(iter(modes.values()))
    W = np.zeros_like(first_mode, dtype=float)

    for name, coeff in coeffs.items():
        if name not in modes:
            raise KeyError(f"Mode '{name}' is not available. Available modes: {list(modes)}")
        W += float(coeff) * np.nan_to_num(modes[name], nan=0.0)

    W = np.where(mask, W, np.nan)
    if remove_mean:
        W = remove_piston(W, mask)
    return W


def zernike_radial(n: int, m: int, rho: np.ndarray) -> np.ndarray:
    """Radial part of the Zernike polynomial R_n^m(rho)."""
    if n < 0:
        raise ValueError("n must be non-negative.")
    m = abs(int(m))
    n = int(n)

    if n < m:
        raise ValueError("Zernike mode requires n >= |m|.")
    if (n - m) % 2 != 0:
        raise ValueError("Zernike mode requires n - |m| to be even.")

    R = np.zeros_like(rho, dtype=float)
    max_k = (n - m) // 2

    for k in range(max_k + 1):
        numerator = (-1) ** k * math.factorial(n - k)
        denominator = (
            math.factorial(k)
            * math.factorial((n + m) // 2 - k)
            * math.factorial((n - m) // 2 - k)
        )
        R += numerator / denominator * rho ** (n - 2 * k)

    return R


def zernike_nm(
    n: int,
    m: int,
    rho: np.ndarray,
    theta: np.ndarray,
    mask: np.ndarray,
    normalization: bool = True,
) -> np.ndarray:
    """Generate one real-valued Zernike mode on the pupil."""
    abs_m = abs(int(m))
    R = zernike_radial(int(n), abs_m, rho)

    if m == 0:
        Z = R
        if normalization:
            Z = Z * np.sqrt(n + 1.0)
    elif m > 0:
        Z = R * np.cos(abs_m * theta)
        if normalization:
            Z = Z * np.sqrt(2.0 * (n + 1.0))
    else:
        Z = R * np.sin(abs_m * theta)
        if normalization:
            Z = Z * np.sqrt(2.0 * (n + 1.0))

    return np.where(mask, Z, np.nan)


def generate_zernike_modes(
    rho: np.ndarray,
    theta: np.ndarray,
    mask: np.ndarray,
    max_radial_order: int = 6,
    include_piston: bool = False,
    normalization: bool = True,
) -> dict[str, np.ndarray]:
    """Generate real-valued Zernike modes up to a given radial order."""
    if max_radial_order < 0:
        raise ValueError("max_radial_order must be non-negative.")

    modes: dict[str, np.ndarray] = {}
    for n in range(max_radial_order + 1):
        for m_abs in range(n + 1):
            if (n - m_abs) % 2 != 0:
                continue

            if n == 0 and m_abs == 0:
                if include_piston:
                    modes["Z0_+0"] = zernike_nm(n, 0, rho, theta, mask, normalization=normalization)
                continue

            if m_abs == 0:
                modes[f"Z{n}_+0"] = zernike_nm(n, 0, rho, theta, mask, normalization=normalization)
            else:
                modes[f"Z{n}_+{m_abs}"] = zernike_nm(n, +m_abs, rho, theta, mask, normalization=normalization)
                modes[f"Z{n}_-{m_abs}"] = zernike_nm(n, -m_abs, rho, theta, mask, normalization=normalization)

    return modes


def number_of_zernike_modes(max_radial_order: int, include_piston: bool = False) -> int:
    """Return the number of Zernike modes up to radial order n."""
    if max_radial_order < 0:
        raise ValueError("max_radial_order must be non-negative.")
    total = (max_radial_order + 1) * (max_radial_order + 2) // 2
    if not include_piston:
        total -= 1
    return int(total)


def zernike_inner_product(Z1: np.ndarray, Z2: np.ndarray, mask: np.ndarray) -> float:
    """Discrete mean inner product of two Zernike maps over the pupil."""
    vals = np.asarray(Z1, dtype=float)[mask] * np.asarray(Z2, dtype=float)[mask]
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return float("nan")
    return float(np.mean(vals))


def zernike_gram_matrix(modes: dict[str, np.ndarray], mask: np.ndarray) -> tuple[np.ndarray, list[str]]:
    """Compute a discrete Gram matrix for a dictionary of Zernike modes."""
    names = list(modes.keys())
    G = np.zeros((len(names), len(names)), dtype=float)

    for i, ni in enumerate(names):
        for j, nj in enumerate(names):
            G[i, j] = zernike_inner_product(modes[ni], modes[nj], mask)

    return G, names
