import numpy as np
import pytest

from reconstruction import (
    build_response_matrix,
    measure_slopes,
    numerical_gradient,
    reconstruct_modal_coefficients,
    reconstruct_tsvd,
    residual_wavefront,
    rms,
    subaperture_masks,
)
from zernike import make_pupil_grid, synthesize_wavefront, zernike_named_modes


def test_numerical_gradient_of_linear_wavefront():
    x, y, *_ = make_pupil_grid(N=32, diameter=2.0)
    wavefront = 2.0 * x - 3.0 * y
    dx = float(x[0, 1] - x[0, 0])

    dwdx, dwdy = numerical_gradient(wavefront, dx)

    assert np.allclose(dwdx[1:-1, 1:-1], 2.0)
    assert np.allclose(dwdy[1:-1, 1:-1], -3.0)


def test_subaperture_masks_return_matching_centers_and_masks():
    x, y, _, _, mask, _ = make_pupil_grid(N=40, diameter=1.0)

    centers, masks = subaperture_masks(x, y, mask, n_lenslets=5, min_fill=0.25)

    assert len(masks) == len(centers)
    assert len(masks) > 0
    assert all(m.dtype == bool for m in masks)


def test_reconstruct_modal_coefficients_solves_finite_rows():
    response = np.array(
        [
            [1.0, 0.0],
            [0.0, 1.0],
            [np.nan, 1.0],
        ]
    )
    signal = np.array([0.25, -0.5, 99.0])

    coeffs, _, rank, singular_values = reconstruct_modal_coefficients(signal, response)

    assert np.allclose(coeffs, [0.25, -0.5])
    assert rank == 2
    assert singular_values.size == 2


def test_tsvd_reconstruction_matches_full_rank_solution_for_identity():
    signal = np.array([1.0, -2.0, 0.5])
    response = np.eye(3)

    coeffs, singular_values = reconstruct_tsvd(signal, response, k=3)

    assert np.allclose(coeffs, signal)
    assert np.allclose(singular_values, 1.0)


def test_geometric_modal_reconstruction_reduces_wavefront_rms():
    x, y, rho, theta, mask, _ = make_pupil_grid(N=72, diameter=1.0)
    modes_all = zernike_named_modes(rho, theta, mask)
    modes = {name: modes_all[name] for name in ["tip_x", "tip_y", "defocus", "astig_0"]}
    coeffs_true = {"tip_x": 0.08, "tip_y": -0.05, "defocus": 0.12, "astig_0": 0.07}
    wavefront = synthesize_wavefront(modes, coeffs_true, mask)

    response, names, _ = build_response_matrix(modes, mask, x, y, n_lenslets=8, min_fill=0.4)
    _, slopes = measure_slopes(wavefront, mask, x, y, n_lenslets=8, min_fill=0.4)
    coeffs, *_ = reconstruct_modal_coefficients(slopes, response, rcond=1e-6)
    reconstructed = synthesize_wavefront(dict(zip(names, modes.values())), dict(zip(names, coeffs)), mask)
    residual = residual_wavefront(wavefront, reconstructed, mask)

    assert rms(residual, mask) < 0.1 * rms(wavefront, mask)
