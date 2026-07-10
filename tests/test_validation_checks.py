# Tests verify parameter monotonicity, reproducibility, Marechal tolerance, diffraction scale, and DM fitting trend validation checks.

import numpy as np
import pytest

from ao_closed_loop import DetectorLoopConfig
from ao_error_budget import (
    ScenarioConfig,
    build_control_space_phase_sequence,
    default_jhk_bandpasses,
    run_error_budget_scenario,
)
from ao_validation import (
    AOValidationError,
    check_centroid_noise_photon_monotonicity,
    check_diffraction_scale,
    check_dm_fitting_trend,
    check_latency_residual_monotonicity,
    check_marechal_consistency,
    check_scenario_reproducibility,
    validation_results_as_dicts,
)
from dm_model import DMConfig, build_dm_model
from interaction_matrix import PokeMatrixConfig, build_detector_dm_poke_matrix
from synthetic_instrument_data import DetectorConfig, ShwfsGeometryConfig, build_detector_shwfs_calibration


@pytest.fixture(scope="module")
def validation_system():
    geometry = ShwfsGeometryConfig(
        telescope_diameter_m=2.0,
        n_pupil_pixels=52,
        n_lenslets=5,
        min_fill_fraction=0.35,
        pad_factor=3,
        detector_window_px=18,
        threshold_fraction=0.0,
        source_class="synthetic_assumed",
        source_note="Validation unit-test geometry.",
    )
    calibration = build_detector_shwfs_calibration(
        geometry=geometry,
        detector=DetectorConfig(
            photons_per_subap_frame=8000.0,
            read_noise_e=1.0,
            qe=1.0,
            source_class="synthetic_assumed",
            source_note="Validation detector configuration.",
        ),
    )
    dm_model = build_dm_model(
        calibration.x_m,
        calibration.y_m,
        calibration.pupil_mask,
        DMConfig(
            telescope_diameter_m=2.0,
            n_actuators_across=5,
            influence_model="gaussian",
            coupling_width_pitch=0.40,
            stroke_limit_nm=1000.0,
            source_class="synthetic_literature_inspired",
            source_note="Validation synthetic Gaussian DM model.",
        ),
    )
    poke = build_detector_dm_poke_matrix(
        calibration,
        dm_model,
        PokeMatrixConfig(
            calibration_amplitude_nm=10.0,
            rcond_scan_grid=(1.0e-8, 1.0e-6, 1.0e-4, 1.0e-3),
            target_kept_mode_fraction=1.0,
            source_class="synthetic_assumed",
            source_note="Validation central-difference poke configuration.",
        ),
    )
    return calibration, dm_model, poke


def _gaussian_spot(size: int = 17, sigma_px: float = 2.0) -> np.ndarray:
    coords = np.arange(size) - (size - 1) / 2.0
    x, y = np.meshgrid(coords, coords)
    spot = np.exp(-(x**2 + y**2) / (2.0 * sigma_px**2))
    return spot / np.sum(spot)


def test_marechal_consistency_and_diffraction_scale_checks_pass():
    n = 80
    coords = np.linspace(-1.0, 1.0, n)
    x, y = np.meshgrid(coords, coords)
    mask = x**2 + y**2 <= 1.0
    small_opd_nm = np.where(mask, 45.0 * (x**2 - y**2), np.nan)

    marechal = check_marechal_consistency(
        small_opd_nm,
        mask,
        wavelength_m=1.65e-6,
        telescope_diameter_m=2.0,
        tolerance_abs=0.03,
    )
    diffraction = check_diffraction_scale(mask, wavelength_m=1.65e-6, telescope_diameter_m=2.0)

    assert marechal.passed
    assert marechal.metric_value < marechal.tolerance
    assert diffraction.passed
    assert 0.75 < diffraction.metric_value < 1.15


def test_photon_count_monotonicity_check_passes_for_same_seed_ensemble():
    result = check_centroid_noise_photon_monotonicity(
        _gaussian_spot(),
        photon_counts=(200.0, 1000.0, 5000.0, 20000.0),
        detector_template=DetectorConfig(
            read_noise_e=0.0,
            qe=1.0,
            source_class="synthetic_assumed",
            source_note="Photon monotonicity detector template.",
        ),
        n_trials=160,
        seed=3,
        relative_tolerance=0.05,
    )

    assert result.passed
    assert np.all(np.diff(result.metric_values) < 0.0)


def test_latency_monotonicity_check_passes_for_dynamic_sequence(validation_system):
    calibration, dm_model, poke = validation_system
    scenario = ScenarioConfig(
        "latency_validation",
        ("multi_component_dynamic_phase",),
        n_steps=12,
        phase_amplitude_nm=260.0,
        source_note="Latency monotonicity validation scenario.",
    )
    phase_sequence = build_control_space_phase_sequence(calibration, dm_model, poke, scenario)

    result = check_latency_residual_monotonicity(
        phase_sequence,
        calibration,
        dm_model,
        poke,
        latency_frames=(0, 1, 2),
        base_loop_config=DetectorLoopConfig(
            n_steps=12,
            gain=0.32,
            leak=0.02,
            include_detector_noise=False,
            source_note="Latency validation loop config.",
        ),
        relative_tolerance=0.05,
    )

    assert result.passed
    assert np.all(np.diff(result.metric_values) > 0.0)


def test_scenario_reproducibility_check_passes_with_same_seed(validation_system):
    calibration, dm_model, poke = validation_system
    scenario = ScenarioConfig(
        "detector_noise_reproducibility",
        ("multi_component_dynamic_phase", "detector_noise"),
        n_steps=10,
        phase_amplitude_nm=240.0,
        include_detector_noise=True,
        seed=31,
        source_note="Reproducibility validation scenario.",
    )
    bandpasses = default_jhk_bandpasses()

    first = run_error_budget_scenario(calibration, dm_model, poke, scenario, bandpasses, pad_factor=3)
    second = run_error_budget_scenario(calibration, dm_model, poke, scenario, bandpasses, pad_factor=3)
    result = check_scenario_reproducibility((first,), (second,), atol=1.0e-12, rtol=1.0e-12)

    assert result.passed
    assert result.metric_value == pytest.approx(0.0, abs=1.0e-12)


def test_dm_fitting_trend_check_passes_for_increasing_actuator_count(validation_system):
    calibration, _, _ = validation_system
    x = calibration.x_m
    y = calibration.y_m
    mask = calibration.pupil_mask
    target = np.where(
        mask,
        120.0 * (x**2 - y**2) + 70.0 * x * y + 35.0 * np.sin(3.0 * np.pi * x / 2.0) * np.cos(2.0 * np.pi * y / 2.0),
        np.nan,
    )

    result = check_dm_fitting_trend(
        target,
        x,
        y,
        mask,
        actuator_counts=(4, 6, 8),
        dm_config_template=DMConfig(
            telescope_diameter_m=2.0,
            influence_model="gaussian",
            coupling_width_pitch=0.45,
            stroke_limit_nm=1000.0,
            source_class="synthetic_literature_inspired",
            source_note="Fitting trend synthetic Gaussian DM template.",
        ),
        relative_tolerance=0.05,
    )

    assert result.passed
    assert result.metric_values[-1] < result.metric_values[0]


def test_validation_results_are_table_friendly():
    result = check_centroid_noise_photon_monotonicity(
        _gaussian_spot(),
        photon_counts=(500.0, 5000.0),
        detector_template=DetectorConfig(
            read_noise_e=0.0,
            source_class="synthetic_assumed",
            source_note="Table conversion detector template.",
        ),
        n_trials=32,
        seed=4,
    )
    rows = validation_results_as_dicts((result,))

    assert len(rows) == 2
    assert rows[0]["check_name"] == "photon_centroid_noise_monotonicity"
    assert "metric_value" in rows[0]
    assert rows[0]["source_class"] == "synthetic_assumed"


def test_validation_rejects_bad_photon_scan_inputs():
    with pytest.raises(AOValidationError, match="strictly increasing"):
        check_centroid_noise_photon_monotonicity(_gaussian_spot(), photon_counts=(1000.0, 500.0))
