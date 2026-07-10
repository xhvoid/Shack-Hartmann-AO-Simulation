"""Geometric Shack-Hartmann WFS and modal reconstruction utilities."""

from __future__ import annotations

import numpy as np


def numerical_gradient(W: np.ndarray, dx: float) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute numerical gradient of a wavefront map.

    ``np.gradient`` returns d/daxis0 and d/daxis1. Since axis 0 corresponds
    to y and axis 1 corresponds to x, the returned order is (dW/dx, dW/dy).
    """
    if dx <= 0:
        raise ValueError("dx must be positive.")
    W0 = np.nan_to_num(W, nan=0.0)
    dW_dy, dW_dx = np.gradient(W0, dx, dx)
    return dW_dx, dW_dy


def subaperture_masks(
    X: np.ndarray,
    Y: np.ndarray,
    pupil_mask: np.ndarray,
    n_lenslets: int = 12,
    min_fill: float = 0.5,
) -> tuple[np.ndarray, list[np.ndarray]]:
    """
    Divide the pupil into square Shack-Hartmann sub-apertures.

    Returns valid sub-aperture centers and boolean masks. A sub-aperture is
    retained if at least ``min_fill`` of its pixels lie inside the pupil.
    """
    if n_lenslets < 1:
        raise ValueError("n_lenslets must be >= 1.")
    if not (0.0 <= min_fill <= 1.0):
        raise ValueError("min_fill must be between 0 and 1.")

    x_min, x_max = np.nanmin(X), np.nanmax(X)
    y_min, y_max = np.nanmin(Y), np.nanmax(Y)

    x_edges = np.linspace(x_min, x_max, n_lenslets + 1)
    y_edges = np.linspace(y_min, y_max, n_lenslets + 1)

    masks: list[np.ndarray] = []
    centers: list[list[float]] = []

    for ix in range(n_lenslets):
        for iy in range(n_lenslets):
            cell = (
                (X >= x_edges[ix])
                & (X < x_edges[ix + 1])
                & (Y >= y_edges[iy])
                & (Y < y_edges[iy + 1])
            )
            valid = cell & pupil_mask
            fill = valid.sum() / max(cell.sum(), 1)

            if fill >= min_fill:
                masks.append(valid)
                centers.append(
                    [
                        0.5 * (x_edges[ix] + x_edges[ix + 1]),
                        0.5 * (y_edges[iy] + y_edges[iy + 1]),
                    ]
                )

    return np.asarray(centers, dtype=float), masks


def measure_slopes(
    W: np.ndarray,
    pupil_mask: np.ndarray,
    X: np.ndarray,
    Y: np.ndarray,
    n_lenslets: int = 12,
    min_fill: float = 0.5,
    noise_std: float = 0.0,
    seed: int | None = 1,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Measure mean local wavefront slopes in every valid sub-aperture.

    This is an ideal geometric Shack-Hartmann model:

        sx = <dW/dx>,  sy = <dW/dy>

    A detector-level model should instead form lenslet spots and centroid them.
    """
    if noise_std < 0:
        raise ValueError("noise_std must be non-negative.")

    dx = float(X[0, 1] - X[0, 0])
    dWdx, dWdy = numerical_gradient(W, abs(dx))

    centers, masks = subaperture_masks(
        X,
        Y,
        pupil_mask,
        n_lenslets=n_lenslets,
        min_fill=min_fill,
    )

    slopes = []
    for m in masks:
        sx = np.nanmean(dWdx[m])
        sy = np.nanmean(dWdy[m])
        slopes.append([sx, sy])

    slopes_arr = np.asarray(slopes, dtype=float)

    if noise_std > 0:
        rng = np.random.default_rng(seed)
        slopes_arr = slopes_arr + rng.normal(scale=noise_std, size=slopes_arr.shape)

    return centers, slopes_arr


def measure_geometric_slopes(*args, **kwargs):
    """Alias for ``measure_slopes`` to make the model assumption explicit."""
    return measure_slopes(*args, **kwargs)


def build_response_matrix(
    modes: dict[str, np.ndarray],
    pupil_mask: np.ndarray,
    X: np.ndarray,
    Y: np.ndarray,
    n_lenslets: int = 12,
    min_fill: float = 0.5,
) -> tuple[np.ndarray, list[str], np.ndarray]:
    """Build a geometric SH-WFS modal slope response matrix."""
    names = list(modes.keys())
    columns = []
    reference_centers = None

    for name in names:
        centers, slopes = measure_slopes(
            modes[name],
            pupil_mask,
            X,
            Y,
            n_lenslets=n_lenslets,
            min_fill=min_fill,
            noise_std=0.0,
        )

        if reference_centers is None:
            reference_centers = centers
        elif centers.shape != reference_centers.shape or not np.allclose(centers, reference_centers):
            raise RuntimeError("Sub-aperture geometry changed between modes.")

        columns.append(slopes.reshape(-1))

    A = np.column_stack(columns) if columns else np.empty((0, 0))
    return A, names, reference_centers


def _valid_lstsq_system(signal: np.ndarray, response_matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Remove rows with non-finite signal or response-matrix entries."""
    s = np.asarray(signal, dtype=float).reshape(-1)
    A = np.asarray(response_matrix, dtype=float)

    if A.ndim != 2:
        raise ValueError("response_matrix must be 2-D.")
    if A.shape[0] != s.size:
        raise ValueError("signal length must match response_matrix row count.")

    valid = np.isfinite(s) & np.all(np.isfinite(A), axis=1)
    if not np.any(valid):
        raise ValueError("No finite measurements are available for reconstruction.")

    return s[valid], A[valid]


def reconstruct_modal_coefficients(
    slopes: np.ndarray,
    response_matrix: np.ndarray,
    rcond: float = 1e-4,
) -> tuple[np.ndarray, np.ndarray, int, np.ndarray]:
    """Least-squares modal reconstruction from slope-like measurements."""
    s, A = _valid_lstsq_system(slopes, response_matrix)
    coeffs, residuals, rank, singular_values = np.linalg.lstsq(A, s, rcond=rcond)
    return coeffs, residuals, rank, singular_values


def remove_piston(W: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Remove piston inside the pupil."""
    out = np.array(W, dtype=float, copy=True)
    finite = mask & np.isfinite(out)
    if np.any(finite):
        out[finite] -= np.nanmean(out[finite])
    out[~mask] = np.nan
    return out


def synthesize_from_coefficients(
    coeffs: np.ndarray,
    modes: dict[str, np.ndarray],
    names: list[str],
    pupil_mask: np.ndarray,
    remove_mean: bool = True,
) -> np.ndarray:
    """Reconstruct a wavefront map from modal coefficients."""
    if len(coeffs) != len(names):
        raise ValueError("coeffs and names must have the same length.")

    W = np.zeros_like(next(iter(modes.values())), dtype=float)
    for c, name in zip(coeffs, names):
        W += float(c) * np.nan_to_num(modes[name], nan=0.0)

    W = np.where(pupil_mask, W, np.nan)
    if remove_mean:
        W = remove_piston(W, pupil_mask)
    return W


def reconstruct_wavefront(
    slopes: np.ndarray,
    response_matrix: np.ndarray,
    modes: dict[str, np.ndarray],
    names: list[str],
    pupil_mask: np.ndarray,
    rcond: float = 1e-4,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int, np.ndarray]:
    """Full modal wavefront reconstruction from SH-WFS measurements."""
    coeffs, residuals, rank, singular_values = reconstruct_modal_coefficients(
        slopes,
        response_matrix,
        rcond=rcond,
    )
    W_rec = synthesize_from_coefficients(coeffs, modes, names, pupil_mask, remove_mean=True)
    return coeffs, W_rec, residuals, rank, singular_values


def rms(W: np.ndarray, mask: np.ndarray) -> float:
    """RMS inside the pupil after mean subtraction."""
    vals = np.asarray(W, dtype=float)[mask]
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return float("nan")
    vals = vals - np.mean(vals)
    return float(np.sqrt(np.mean(vals**2)))


def residual_wavefront(W_true: np.ndarray, W_rec: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Compute residual wavefront after removing piston."""
    res = np.asarray(W_true, dtype=float) - np.asarray(W_rec, dtype=float)
    return remove_piston(res, mask)


def reconstruct_tsvd(
    signal: np.ndarray,
    response_matrix: np.ndarray,
    k: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Truncated-SVD reconstruction."""
    if k < 1:
        raise ValueError("k must be >= 1.")

    s, A = _valid_lstsq_system(signal, response_matrix)
    U, S, Vt = np.linalg.svd(A, full_matrices=False)

    k_eff = min(int(k), len(S))
    Sinv = np.zeros_like(S)
    positive = S[:k_eff] > 0
    Sinv[:k_eff][positive] = 1.0 / S[:k_eff][positive]

    coeffs = Vt.T @ (Sinv * (U.T @ s))
    return coeffs, S


def reconstruct_tikhonov(
    signal: np.ndarray,
    response_matrix: np.ndarray,
    alpha: float,
) -> np.ndarray:
    """
    Tikhonov-regularized reconstruction:

        argmin ||A x - s||^2 + alpha^2 ||x||^2
    """
    if alpha < 0:
        raise ValueError("alpha must be non-negative.")

    s, A = _valid_lstsq_system(signal, response_matrix)
    ATA = A.T @ A
    rhs = A.T @ s
    coeffs = np.linalg.solve(ATA + alpha**2 * np.eye(ATA.shape[0]), rhs)
    return coeffs
