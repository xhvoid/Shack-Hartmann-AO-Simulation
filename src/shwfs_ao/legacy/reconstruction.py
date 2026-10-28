"""Geometric Shack-Hartmann WFS and modal reconstruction utilities."""

from __future__ import annotations

import numpy as np

from ..core.geometry import PupilGeometry as _PupilGeometry
from ..core.random import NamedRandomStreams as _NamedRandomStreams
from ..core import wavefront as _wavefront
from ..wfs.shack_hartmann.geometric import (
    NativeGeometricShackHartmannSensor as _NativeGeometricShackHartmannSensor,
    numerical_gradient as _canonical_numerical_gradient,
)
from ..wfs.shack_hartmann.geometry import (
    ShackHartmannGeometry as _ShackHartmannGeometry,
    partition_pupil_geometry as _partition_pupil_geometry,
)
from ._interaction_adapters import (
    calibrate_legacy_modal_columns as _calibrate_legacy_modal_columns,
    legacy_streams as _legacy_calibration_streams,
)
from ._reconstruction_adapters import (
    _legacy_fixed_modes_tsvd_reconstructor,
    _legacy_least_squares_reconstructor,
    _legacy_lstsq_payload,
    _legacy_tikhonov_reconstructor,
)


def numerical_gradient(
    W: np.ndarray,
    dx: float,
    mask: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute a finite-difference gradient without crossing invalid pupil edges.

    Central differences are used where both neighbours are valid. At a mask
    boundary, a second-order one-sided difference is used when two samples are
    available, with a first-order fallback for a single neighbour. Values with
    no valid neighbour along an axis remain NaN for that derivative.

    Since axis 0 corresponds to y and axis 1 corresponds to x, the returned
    order is ``(dW/dx, dW/dy)``.
    """
    return _canonical_numerical_gradient(W, dx, mask=mask)


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
    geometry = _legacy_shack_hartmann_geometry(
        X,
        Y,
        pupil_mask,
        n_lenslets=n_lenslets,
        min_fill=min_fill,
    )
    return (
        np.array(geometry.subaperture_centers_m, dtype=float, copy=True),
        [np.array(mask, dtype=bool, copy=True) for mask in geometry.subaperture_masks],
    )


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

    geometry = _legacy_shack_hartmann_geometry(
        X,
        Y,
        pupil_mask,
        n_lenslets=n_lenslets,
        min_fill=min_fill,
    )
    root_seed = (
        int(np.random.SeedSequence().entropy)
        if seed is None
        else int(seed)
    )
    sensor = _NativeGeometricShackHartmannSensor(geometry)
    measurement = sensor.measure(
        np.asarray(W, dtype=float),
        random_streams=_NamedRandomStreams(root_seed),
        include_noise=False,
    )
    slopes_arr = np.array(
        measurement.vector.values.reshape(-1, 2),
        dtype=float,
        copy=True,
    )

    if noise_std > 0:
        rng = np.random.default_rng(seed)
        slopes_arr = slopes_arr + rng.normal(scale=noise_std, size=slopes_arr.shape)

    return (
        np.array(geometry.subaperture_centers_m, dtype=float, copy=True),
        slopes_arr,
    )


def _legacy_shack_hartmann_geometry(
    X: np.ndarray,
    Y: np.ndarray,
    pupil_mask: np.ndarray,
    *,
    n_lenslets: int,
    min_fill: float,
) -> _ShackHartmannGeometry:
    """Adapt the historical sampled-grid arguments to canonical geometry."""

    x_m = np.asarray(X, dtype=float)
    y_m = np.asarray(Y, dtype=float)
    pupil = np.asarray(pupil_mask, dtype=bool)
    if x_m.ndim != 2 or y_m.shape != x_m.shape or pupil.shape != x_m.shape:
        raise ValueError("X, Y, and pupil_mask must be matching 2-D arrays.")
    if x_m.shape[0] < 2 or x_m.shape[1] < 2:
        raise ValueError("X and Y must contain at least two samples per axis.")
    diameter_x = float(np.nanmax(x_m) - np.nanmin(x_m))
    diameter_y = float(np.nanmax(y_m) - np.nanmin(y_m))
    if not np.isclose(diameter_x, diameter_y, rtol=1.0e-12, atol=1.0e-15):
        raise ValueError("X and Y must span the same pupil diameter.")
    sampled_pupil = _PupilGeometry(
        telescope_diameter_m=diameter_x,
        pupil_shape=tuple(int(value) for value in x_m.shape),
        pupil_mask=pupil,
        x_m=x_m,
        y_m=y_m,
    )
    return _partition_pupil_geometry(
        sampled_pupil,
        n_lenslets_across=n_lenslets,
        min_fill_fraction=min_fill,
    )


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
    """Build a geometric SH-WFS modal slope response matrix.

    The historical maps and return scaling are retained, while the actual
    response calibration is owned by the generic canonical calibrator.
    """

    names = list(modes.keys())
    if not names:
        # Historical behavior does not build lenslet geometry for an empty
        # dictionary and therefore returns ``None`` for the centers.
        return np.empty((0, 0)), names, None

    geometry = _legacy_shack_hartmann_geometry(
        X,
        Y,
        pupil_mask,
        n_lenslets=n_lenslets,
        min_fill=min_fill,
    )
    sensor = _NativeGeometricShackHartmannSensor(geometry)
    response, calibrated_names = _calibrate_legacy_modal_columns(
        modes,
        pupil_mask,
        sensor,
        coefficient_amplitude=1.0,
        opd_m_per_raw_unit=1.0,
        method="forward",
        random_streams=_legacy_calibration_streams(1),
    )
    return (
        np.array(response, dtype=float, copy=True),
        list(calibrated_names),
        np.array(geometry.subaperture_centers_m, dtype=float, copy=True),
    )


def reconstruct_modal_coefficients(
    slopes: np.ndarray,
    response_matrix: np.ndarray,
    rcond: float = 1e-4,
) -> tuple[np.ndarray, np.ndarray, int, np.ndarray]:
    """Least-squares modal reconstruction from slope-like measurements."""
    reconstructor = _legacy_least_squares_reconstructor(
        response_matrix,
        rcond,
        matrix_error="response_matrix must be 2-D.",
        length_error="signal length must match response_matrix row count.",
        no_rows_error="No finite measurements are available for reconstruction.",
    )
    result = reconstructor.reconstruct(slopes)
    return _legacy_lstsq_payload(
        result,
        coordinate_count=reconstructor.coordinate_count,
    )


def remove_piston(W: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Remove piston inside the pupil with legacy non-finite handling."""
    out = np.array(W, dtype=float, copy=True)
    finite = mask & np.isfinite(out)
    if np.any(finite):
        centered = _wavefront.remove_piston(out, finite)
        out[finite] = centered[finite]
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
    """RMS inside the pupil, ignoring legacy non-finite samples."""
    vals = np.asarray(W, dtype=float)[mask]
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        return float("nan")
    return _wavefront.masked_rms(vals, np.ones(vals.shape, dtype=bool))


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
    reconstructor = _legacy_fixed_modes_tsvd_reconstructor(
        response_matrix,
        int(k),
        matrix_error="response_matrix must be 2-D.",
        length_error="signal length must match response_matrix row count.",
        no_rows_error="No finite measurements are available for reconstruction.",
    )
    result = reconstructor.reconstruct(signal)
    return (
        np.array(result.coordinates, dtype=float, copy=True),
        np.array(result.singular_values, dtype=float, copy=True),
    )


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
    reconstructor = _legacy_tikhonov_reconstructor(
        response_matrix,
        float(alpha),
        matrix_error="response_matrix must be 2-D.",
        length_error="signal length must match response_matrix row count.",
        no_rows_error="No finite measurements are available for reconstruction.",
    )
    result = reconstructor.reconstruct(signal)
    return np.array(result.coordinates, dtype=float, copy=True)
