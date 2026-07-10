# Tests verify the 8-scenario error-budget matrix produces finite ScenarioResult rows with OPD RMS, J/H/K Strehl, EE50/EE80, command, saturation, and centroid-validity metrics.

import numpy as np
import pytest

from ao_diagnostics import top_hat_bandpass
from ao_error_budget import (
    AOErrorBudgetError,
    REQUIRED_SCENARIO_NAMES,
    ScenarioConfig,
    default_error_budget_scenarios,
    run_error_budget_scenarios,
    scenario_results_as_dicts,
)
from dm_model import DMConfig, build_dm_model
from interaction_matrix import PokeMatrixConfig, build_detector_dm_poke_matrix
from synthetic_instrument_data import DetectorConfig, ShwfsGeometryConfig, build_detector_shwfs_calibration


@pytest.fixture(scope="module")
def error_budget_rows():
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
