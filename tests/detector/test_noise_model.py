"""DET-07: the ``detector_covariance_v1`` centroid-noise model against Monte Carlo.

Tolerances.  The standard deviation of ``N`` trials has relative standard
error ``1/sqrt(2 (N - 1))``: 0.7 % at 10^4 trials, 3.5 % at 400 calibration
realizations, 2.2 % at 1000 trials.  The first-order model is low by about
``4 / SNR_T**2`` (E1); at the fixtures' ``SNR_T >= 10`` that is below 4 %.  The
acceptance band is therefore 10 % for 10^4-trial points (prompt DET-07), 15 %
for the fast 1000-trial variants and 400-realization calibration ensembles
(five standard errors plus the linearization error).

Monte-Carlo tests with more than 10^5 draws carry the ``slow`` marker; fast
variants with at most 10^5 draws run in the default selection.
"""

from __future__ import annotations

from dataclasses import replace
import math

import numpy as np
import pytest

from shwfs_ao.detector.camera import CameraConfig
from shwfs_ao.detector.centroid import CentroidConfig
from shwfs_ao.detector.noise_model import MIN_DENOMINATOR_SNR
from shwfs_ao.detector.processing import PixelProcessingConfig
from shwfs_ao.experiments.detector_noise import (
    NoiseFixture,
    calibration_trials,
    fixture_products,
    gaussian_spot,
    model_prediction,
    summarize_trials,
    temporal_trials,
)


def camera(**overrides: object) -> CameraConfig:
    values: dict[str, object] = dict(
        model="ccd", preset_name="t", preset_version=1, quantum_efficiency=0.9,
        full_well_e=1.0e6, dark_e_per_s=50.0, hot_pixel_fraction=0.0, hot_pixel_dark_e_per_s=0.0,
        prnu_rms=0.01, dead_pixel_fraction=0.0, read_noise_e=3.0, conversion_gain_e_per_adu=1.0,
        bias_adu=200.0, offset_map_rms_adu=1.0, adc_bits=16,
    )
    values.update(overrides)
    return CameraConfig(**values)  # type: ignore[arg-type]


ESTIMATED = PixelProcessingConfig(
    mode="estimated", n_bias_frames=16, n_dark_frames=16, n_sky_frames=16, n_flat_frames=16,
    flat_level_e=3000.0, hot_pixel_threshold_e=50.0,
)
ORACLE = PixelProcessingConfig(mode="oracle", flat_level_e=3000.0, hot_pixel_threshold_e=1.0e9)

# Camera type -> (photon-limited, read-noise-limited) fixtures; SNR_T >= 10.
CASES = {
    "ccd": (
        (camera(read_noise_e=1.0), 2.0e4),
        (camera(read_noise_e=8.0), 1500.0),
    ),
    "emccd": (
        (camera(model="emccd", em_gain=300.0, register_full_well_e=1.0e9, read_noise_e=50.0, conversion_gain_e_per_adu=20.0, cic_e_per_pixel_read=0.01), 600.0),
        (camera(model="emccd", em_gain=100.0, register_full_well_e=1.0e9, read_noise_e=2000.0, conversion_gain_e_per_adu=200.0), 3000.0),
    ),
    "cmos": (
        (camera(model="cmos", read_noise_e=1.5, conversion_gain_e_per_adu=0.5, cmos_gain_map_rms=0.03, cmos_read_noise_lognormal_sigma=0.3, offset_map_rms_adu=3.0), 1.0e4),
        (camera(model="cmos", read_noise_e=6.0, conversion_gain_e_per_adu=0.5, cmos_gain_map_rms=0.03, cmos_read_noise_lognormal_sigma=0.3, offset_map_rms_adu=3.0), 1500.0),
    ),
}


def fixture(cam: CameraConfig, flux: float, *, window: int = 13, guard: int = 0, processing=ESTIMATED, sky: float = 0.5, seed: int = 1) -> NoiseFixture:
    return NoiseFixture(
        camera=cam, processing=processing,
        source_e=gaussian_spot(window + 2 * guard, flux, 1.2),
        window_px=window, guard_px=guard, sky_e_per_pixel=sky, seed=seed,
    )


def _ratio(fix: NoiseFixture, trials: int) -> tuple[np.ndarray, object]:
    quality = model_prediction(fix)
    summary = summarize_trials(temporal_trials(fix, trials)["centroids_px"])
    observed = np.array([summary["std_x_px"], summary["std_y_px"]])
    return observed / quality.centroid_sigma_xy_px[0], quality


@pytest.mark.parametrize("camera_type", sorted(CASES))
@pytest.mark.parametrize("regime", [0, 1], ids=["photon_limited", "read_limited"])
def test_temporal_scatter_matches_the_model_fast(camera_type: str, regime: int) -> None:
    cam, flux = CASES[camera_type][regime]
    fix = fixture(cam, flux, window=7)  # 49 px x 1000 trials < 1e5 draws
    ratio, quality = _ratio(fix, 1000)
    assert quality.supported[0] and quality.total_snr[0] >= MIN_DENOMINATOR_SNR
    assert np.all(np.abs(ratio - 1.0) < 0.15), ratio


@pytest.mark.slow
@pytest.mark.parametrize("camera_type", sorted(CASES))
@pytest.mark.parametrize("regime", [0, 1], ids=["photon_limited", "read_limited"])
def test_temporal_scatter_matches_the_model_within_ten_percent(camera_type: str, regime: int) -> None:
    cam, flux = CASES[camera_type][regime]
    ratio, quality = _ratio(fixture(cam, flux), 10_000)
    assert quality.total_snr[0] >= 10.0
    assert np.all(np.abs(ratio - 1.0) < 0.10), ratio


@pytest.mark.slow
@pytest.mark.parametrize("sky_frames", [16, 0], ids=["sky_frames", "shared_dark_frames"])
def test_calibration_ensemble_matches_the_model(sky_frames: int) -> None:
    processing = PixelProcessingConfig(
        mode="estimated", n_bias_frames=4, n_dark_frames=4, n_sky_frames=sky_frames, n_flat_frames=4,
        flat_level_e=300.0, hot_pixel_threshold_e=1.0e9,
    )
    cam = camera(read_noise_e=8.0, dark_e_per_s=2000.0, prnu_rms=0.02)
    fix = fixture(cam, 2.0e4, processing=processing, sky=3.0)
    quality = model_prediction(fix)
    centroids = calibration_trials(fix, 400)["centroids_px"]
    ratio = centroids.std(axis=0, ddof=1) / quality.calibration_sigma_xy_px[0]
    assert np.all(np.abs(ratio - 1.0) < 0.15), ratio


@pytest.mark.slow
def test_calibration_contribution_falls_with_master_frame_count() -> None:
    sigmas = []
    for count in (2, 8, 32):
        processing = PixelProcessingConfig(
            mode="estimated", n_bias_frames=count, n_dark_frames=count, n_sky_frames=count, n_flat_frames=count,
            flat_level_e=300.0, hot_pixel_threshold_e=1.0e9,
        )
        fix = fixture(camera(read_noise_e=8.0, dark_e_per_s=2000.0), 2.0e4, processing=processing, sky=3.0)
        predicted = model_prediction(fix).calibration_sigma_xy_px[0, 0]
        measured = calibration_trials(fix, 200)["centroids_px"][:, 0].std(ddof=1)
        assert abs(measured / predicted - 1.0) < 0.2
        sigmas.append(predicted)
    # Equal frame counts: every master error falls as 1/sqrt(N).
    assert math.isclose(sigmas[0] / sigmas[1], 2.0, rel_tol=0.02)
    assert math.isclose(sigmas[1] / sigmas[2], 2.0, rel_tol=0.02)


def test_a_fixed_master_is_not_fresh_frame_noise() -> None:
    fix = fixture(camera(read_noise_e=8.0), 3000.0, window=7)
    products = fixture_products(fix)
    first = temporal_trials(fix, 300, products=products)["centroids_px"]
    second = temporal_trials(replace(fix, seed=fix.seed), 300, products=products)["centroids_px"]
    # Identical masters and identical streams reproduce identical frames.
    assert np.array_equal(first, second)
    other = fixture_products(fix, realization=5)
    assert other.content_hash != products.content_hash


def _explicit_coupling_matrix(rows: int, columns: int, kernel: np.ndarray) -> np.ndarray:
    """Dense K, written independently of ``apply_coupling``: y = K q."""

    size = rows * columns
    matrix = np.zeros((size, size))
    for r in range(rows):
        for c in range(columns):
            source = r * columns + c
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    rr, cc = r + dr, c + dc
                    if 0 <= rr < rows and 0 <= cc < columns:
                        matrix[rr * columns + cc, source] += kernel[1 + dr, 1 + dc]
    return matrix


@pytest.mark.slow
@pytest.mark.parametrize("case", ["flat_field", "localized_source"])
def test_coupled_readout_covariance_is_k_diag_mu_k_transpose_plus_read(case: str) -> None:
    from shwfs_ao.core.random import NamedRandomStreams
    from shwfs_ao.detector.physical import apply_physical_camera

    cam = camera(read_noise_e=2.0, adc_bits=None, prnu_rms=0.0, dark_e_per_s=0.0, offset_map_rms_adu=0.0, bias_adu=0.0,
                 coupling_nearest=0.06, coupling_diagonal=0.015)
    size = 5
    mu = np.full((size, size), 40.0) if case == "flat_field" else gaussian_spot(size, 400.0, 0.8) + 1.0
    trials = 40_000
    generator = NamedRandomStreams(3).generator("detector.shot_noise")
    read = NamedRandomStreams(4).generator("detector.read_noise")
    maps = {"prnu": None, "dead": None, "hot": None, "offset_adu": None, "gain_multiplier": None, "read_noise_multiplier": None}
    samples = []
    for start in range(0, trials, 10_000):
        batch = apply_physical_camera(
            np.repeat(mu[None], 10_000, axis=0), 0.0, cam, maps, exposure_s=1.0e-3, include_noise=True,
            generators=lambda index, domain: read if domain == "detector.read_noise" else generator, poisson_floor_e=0.0,
        )
        samples.append(batch.raw.reshape(10_000, -1))
    data = np.concatenate(samples)
    measured = np.cov(data, rowvar=False)
    matrix = _explicit_coupling_matrix(size, size, cam.coupling_kernel)
    predicted = matrix @ np.diag(mu.ravel()) @ matrix.T + 4.0 * np.eye(size * size)
    # Element-wise standard error of a sample covariance: sqrt((S_ii S_jj + S_ij^2) / N).
    diag = np.diag(predicted)
    se = np.sqrt((np.outer(diag, diag) + predicted**2) / trials)
    assert np.all(np.abs(measured - predicted) < 5.0 * se)
    neighbour = predicted[12, 13]
    assert neighbour > 10.0 * se[12, 13]  # off-diagonal terms are resolved, not noise


@pytest.mark.slow
def test_coupled_centroid_needs_the_off_diagonal_covariance() -> None:
    cam = camera(read_noise_e=1.0, coupling_nearest=0.08, coupling_diagonal=0.02, prnu_rms=0.0)
    fix = fixture(cam, 2.0e4, guard=1, processing=ORACLE, sky=0.0)
    quality = model_prediction(fix)
    summary = summarize_trials(temporal_trials(fix, 10_000)["centroids_px"])
    full = quality.centroid_sigma_xy_px[0, 0]
    assert abs(summary["std_x_px"] / full - 1.0) < 0.10
    # Diagonal approximation: keep Var(y_k) but drop Cov(y_k, y_l).
    source = fix.source_e
    window = fix.window()
    block = fix.block_px
    rows, cols = window
    j = np.zeros((block, block))
    sub = source[rows, cols]
    total = sub.sum()
    cx = (sub * np.arange(sub.shape[1])[None, :]).sum() / total
    j[rows, cols] = (np.arange(sub.shape[1])[None, :] - cx) / total
    kernel = cam.coupling_kernel
    matrix = _explicit_coupling_matrix(block, block, kernel)
    mu = source.ravel() + 50.0e-3  # dark current x exposure
    var_y = (matrix**2) @ mu + 1.0 + 1.0 / 12.0
    diagonal = math.sqrt(float(np.sum(j.ravel() ** 2 * var_y)))
    assert abs(summary["std_x_px"] / diagonal - 1.0) > 0.3


@pytest.mark.slow
def test_interpolated_bad_pixels_follow_the_jacobian_oracle() -> None:
    processing = replace(ORACLE, bad_pixel_policy="interpolate_mean4")
    fix = fixture(camera(read_noise_e=4.0, prnu_rms=0.0), 5000.0, processing=processing, sky=1.0)
    products = fixture_products(fix)
    bad = np.array(products.bad)
    bad[0, 5, 7] = True
    bad[0, 7, 6] = True
    products = replace(products, bad=bad)
    quality = model_prediction(fix, products=products)
    result = temporal_trials(fix, 10_000, products=products, return_processed=True)
    summary = summarize_trials(result["centroids_px"])
    observed = np.array([summary["std_x_px"], summary["std_y_px"]])
    assert np.all(np.abs(observed / quality.centroid_sigma_xy_px[0] - 1.0) < 0.10)
    processed = result["processed"][:, 5, 6:9]  # bad pixel (5, 7) and its row neighbours
    covariance = np.cov(processed, rowvar=False)
    # Y_bad = mean of its 4 valid neighbours: Cov(Y_bad, Y_n) = Var(Y_n) / 4.
    assert abs(covariance[1, 0] / (covariance[0, 0] / 4.0) - 1.0) < 0.1


def test_regimes_outside_the_first_order_domain_are_flagged() -> None:
    base = fixture(camera(read_noise_e=3.0), 5000.0, window=7)
    assert model_prediction(base).supported[0]
    thresholded = replace(base, centroid=CentroidConfig(estimator="thresholded_center_of_gravity", threshold_fraction=0.2))
    assert not model_prediction(thresholded).supported[0]
    clipped = replace(base, processing=replace(ESTIMATED, clip_negative=True))
    assert not model_prediction(clipped).supported[0]
    saturated = fixture(camera(read_noise_e=3.0, full_well_e=500.0), 5000.0, window=7, processing=replace(ESTIMATED, flat_level_e=200.0))
    assert not model_prediction(saturated).supported[0]
    coarse = fixture(camera(read_noise_e=0.2), 5000.0, window=7)
    assert not model_prediction(coarse).supported[0]
    nonlinear = fixture(camera(read_noise_e=3.0, full_well_e=1.0e4, nonlinearity_coefficients=(-1.0e-6,)), 5000.0, window=7)
    assert not model_prediction(nonlinear).supported[0]
    faint = fixture(camera(read_noise_e=8.0), 150.0, window=7)
    quality = model_prediction(faint)
    assert quality.total_snr[0] < MIN_DENOMINATOR_SNR and not quality.supported[0]
