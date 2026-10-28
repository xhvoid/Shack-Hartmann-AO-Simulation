# Tests verify the 8-scenario error-budget matrix produces finite ScenarioResult rows with OPD RMS, J/H/K Strehl, EE50/EE80, command, saturation, and centroid-validity metrics.

from dataclasses import replace

import numpy as np
import pytest

from ao_diagnostics import top_hat_bandpass
from ao_error_budget import (
    AOErrorBudgetError,
    REQUIRED_SCENARIO_NAMES,
    ScenarioConfig,
    build_control_space_phase_sequence,
    default_error_budget_scenarios,
    run_error_budget_scenarios,
    scenario_results_as_dicts,
)
from dm_model import DMConfig, build_dm_model
from interaction_matrix import PokeMatrixConfig, build_detector_dm_poke_matrix
from synthetic_instrument_data import DetectorConfig, ShwfsGeometryConfig, build_detector_shwfs_calibration


@pytest.fixture(scope="module")
def error_budget_system():
    geometry = ShwfsGeometryConfig(
        telescope_diameter_m=2.0,
        n_pupil_pixels=52,
        n_lenslets=5,
        min_fill_fraction=0.35,
        pad_factor=3,
        detector_window_px=18,
        threshold_fraction=0.0,
        source_class="synthetic_assumed",
        source_note="Fast error-budget unit-test geometry.",
    )
    calibration = build_detector_shwfs_calibration(
        geometry=geometry,
        detector=DetectorConfig(
            photons_per_subap_frame=8000.0,
            read_noise_e=1.0,
            qe=1.0,
            source_class="synthetic_assumed",
            source_note="Fast detector-noise unit-test configuration.",
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
            source_note="Fast synthetic Gaussian DM model.",
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
            source_note="Fast central-difference poke configuration.",
        ),
    )
    return calibration, dm_model, poke


@pytest.fixture(scope="module")
def error_budget_rows(error_budget_system):
    calibration, dm_model, poke = error_budget_system
    bandpasses = (
        top_hat_bandpass("J", 1.10e-6, 1.40e-6, source_note="Test synthetic J fallback."),
        top_hat_bandpass("H", 1.50e-6, 1.80e-6, source_note="Test synthetic H fallback."),
        top_hat_bandpass("K", 2.00e-6, 2.35e-6, source_note="Test synthetic K fallback."),
    )
    scenarios = default_error_budget_scenarios(n_steps=12, phase_amplitude_nm=260.0)
    return run_error_budget_scenarios(
        calibration,
        dm_model,
        poke,
        scenarios=scenarios,
        bandpasses=bandpasses,
        telescope_diameter_m=2.0,
        pad_factor=3,
    )


def test_default_scenario_matrix_names_and_count():
    scenarios = default_error_budget_scenarios(n_steps=12, phase_amplitude_nm=260.0)

    assert len(scenarios) == 8
    assert tuple(config.scenario_name for config in scenarios) == REQUIRED_SCENARIO_NAMES
    assert scenarios[-1].scenario_name == "all_effects"
    assert "detector_noise" in scenarios[-1].enabled_effects
    assert "science_path_ncpa" in scenarios[-1].enabled_effects


def test_scenario_time_axis_and_random_domains_are_independent(error_budget_system):
    calibration, dm_model, poke = error_budget_system
    scenario = ScenarioConfig(
        "seed_isolation",
        ("multi_component_dynamic_phase",),
        n_steps=8,
        frame_rate_hz=400.0,
        tau0_s=0.004,
        turbulence_speed_m_s=10.0,
        seed=3,
        phase_seed=41,
        detector_noise_seed=43,
        ncpa_seed=47,
        source_note="Seed-domain and physical-time regression scenario.",
    )
    changed_nontruth_seeds = replace(scenario, detector_noise_seed=101, ncpa_seed=103)

    truth = build_control_space_phase_sequence(calibration, dm_model, poke, scenario)
    same_truth = build_control_space_phase_sequence(calibration, dm_model, poke, changed_nontruth_seeds)

    assert scenario.time_s == pytest.approx(np.arange(8, dtype=float) / 400.0)
    assert scenario.resolved_phase_seed == 41
    assert scenario.resolved_detector_noise_seed == 43
    assert scenario.resolved_ncpa_seed == 47
    assert np.allclose(truth, same_truth, equal_nan=True)


def test_frame_rate_tau0_and_wind_change_dynamic_truth(error_budget_system):
    calibration, dm_model, poke = error_budget_system
    base = ScenarioConfig(
        "physical_time_inputs",
        ("multi_component_dynamic_phase",),
        n_steps=8,
        frame_rate_hz=500.0,
        tau0_s=0.004,
        turbulence_speed_m_s=10.0,
        phase_seed=53,
        source_note="Temporal-input sensitivity regression scenario.",
    )
    base_truth = build_control_space_phase_sequence(calibration, dm_model, poke, base)

    variants = (
        replace(base, frame_rate_hz=1000.0),
        replace(base, tau0_s=0.008),
        replace(base, turbulence_speed_m_s=25.0),
    )

    for variant in variants:
        variant_truth = build_control_space_phase_sequence(calibration, dm_model, poke, variant)
        assert not np.allclose(base_truth, variant_truth, equal_nan=True)


def test_default_dynamic_effect_rows_share_one_atmospheric_truth(error_budget_system):
    calibration, dm_model, poke = error_budget_system
    scenarios = default_error_budget_scenarios(n_steps=8, phase_amplitude_nm=260.0)
    dynamic_scenarios = scenarios[1:]
    reference_truth = build_control_space_phase_sequence(calibration, dm_model, poke, dynamic_scenarios[0])

    assert len({scenario.resolved_phase_seed for scenario in dynamic_scenarios}) == 1
    for scenario in dynamic_scenarios[1:]:
        effect_truth = build_control_space_phase_sequence(calibration, dm_model, poke, scenario)
        assert np.allclose(reference_truth, effect_truth, equal_nan=True)


def test_all_8_scenarios_produce_finite_error_budget_metrics(error_budget_rows):
    rows = error_budget_rows

    assert len(rows) == 8
    assert tuple(row.scenario_name for row in rows) == REQUIRED_SCENARIO_NAMES
    for row in rows:
        values = [
            row.open_rms_nm,
            row.closed_rms_nm,
            row.strehl_J,
            row.strehl_H,
            row.strehl_K,
            row.ee50_J,
            row.ee50_H,
            row.ee50_K,
            row.ee80_J,
            row.ee80_H,
            row.ee80_K,
            row.command_rms_nm,
            row.command_peak_nm,
            row.saturated_actuator_frac,
            row.valid_centroid_frac,
        ]
        assert np.all(np.isfinite(values))
        assert row.closed_rms_nm >= 0.0
        assert 0.0 <= row.strehl_H <= 1.5
        assert row.ee50_H < row.ee80_H
        assert 0.0 <= row.valid_centroid_frac <= 1.0
        assert len(row.config_hash) == 64


def test_error_budget_table_dicts_include_required_contract_fields(error_budget_rows):
    table = scenario_results_as_dicts(error_budget_rows)
    required = {
        "scenario_name",
        "enabled_effects",
        "open_rms_nm",
        "closed_rms_nm",
        "strehl_J",
        "strehl_H",
        "strehl_K",
        "ee50_J",
        "ee50_H",
        "ee50_K",
        "source_class",
    }

    assert len(table) == 8
    assert required.issubset(table[0])
    assert all(row["source_class"] == "synthetic_assumed" for row in table)
    assert table[-1]["scenario_name"] == "all_effects"


def test_all_effects_and_ncpa_degrade_relative_to_ideal_static(error_budget_rows):
    by_name = {row.scenario_name: row for row in error_budget_rows}

    assert by_name["ideal_static"].closed_rms_nm < by_name["dynamic_multilayer_proxy"].closed_rms_nm
    assert by_name["all_effects"].closed_rms_nm > by_name["ideal_static"].closed_rms_nm
    assert by_name["all_effects"].strehl_H < by_name["ideal_static"].strehl_H
    assert by_name["ncpa"].closed_rms_nm > by_name["dynamic_multilayer_proxy"].closed_rms_nm
    assert by_name["stroke_limit"].saturated_actuator_frac > 0.0


def test_rejects_non_eight_scenario_matrix():
    bad_scenarios = (
        ScenarioConfig(
            "ideal_static",
            ("static_phase",),
            n_steps=4,
            source_note="Invalid short scenario matrix.",
        ),
    )

    with pytest.raises(AOErrorBudgetError, match="8"):
        run_error_budget_scenarios(
            calibration=None,  # type: ignore[arg-type]
            dm_model=None,  # type: ignore[arg-type]
            poke_result=None,  # type: ignore[arg-type]
            scenarios=bad_scenarios,
        )


def test_scenario_rejects_fractional_frame_counts_and_latency():
    with pytest.raises(AOErrorBudgetError, match="n_steps must be an integer"):
        ScenarioConfig(
            "fractional_steps",
            ("invalid",),
            n_steps=4.0,  # type: ignore[arg-type]
        )
    with pytest.raises(AOErrorBudgetError, match="latency_frames must be an integer"):
        ScenarioConfig(
            "fractional_latency",
            ("invalid",),
            latency_frames=1.5,  # type: ignore[arg-type]
        )
