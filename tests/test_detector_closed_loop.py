# Tests verify detector-level static loop convergence, finite command norm after 50 iterations, latency handling, and fixed-length LoopHistory units.

import numpy as np
import pytest

from ao_closed_loop import (
    ClosedLoopError,
    DetectorLoopConfig,
    loop_history_summary,
    run_detector_integrator_loop,
)
from dm_model import DMConfig, build_dm_model, synthesize_dm_phase_rad
from interaction_matrix import PokeMatrixConfig, build_detector_dm_poke_matrix, expand_controlled_commands
from synthetic_instrument_data import DetectorConfig, ShwfsGeometryConfig, build_detector_shwfs_calibration


@pytest.fixture(scope="module")
def closed_loop_case():
    geometry = ShwfsGeometryConfig(
        telescope_diameter_m=2.0,
        n_pupil_pixels=64,
        n_lenslets=6,
        min_fill_fraction=0.35,
        pad_factor=3,
        detector_window_px=20,
        threshold_fraction=0.0,
        source_class="synthetic_assumed",
        source_note="Closed-loop unit-test geometry.",
    )
    calibration = build_detector_shwfs_calibration(
        geometry=geometry,
        detector=DetectorConfig(
            photons_per_subap_frame=50000.0,
            read_noise_e=0.2,
            qe=1.0,
            source_class="synthetic_assumed",
            source_note="Closed-loop unit-test detector noise settings.",
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
            stroke_limit_nm=500.0,
            source_class="synthetic_literature_inspired",
            source_note="Unit-test synthetic Gaussian DM model.",
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
            source_note="Unit-test central-difference poke configuration.",
        ),
    )
    return calibration, dm_model, poke


def _dm_generated_phase(closed_loop_case, command_scale_nm: float = 1.0):
    calibration, dm_model, poke = closed_loop_case
    commands = np.zeros(poke.n_controlled_actuators)
    commands[0] = 8.0 * command_scale_nm
    commands[poke.n_controlled_actuators // 2] = 4.0 * command_scale_nm
    commands[-1] = -5.0 * command_scale_nm
    full_commands = expand_controlled_commands(commands, poke, dm_model)
    phase_rad, _ = synthesize_dm_phase_rad(
        full_commands,
        dm_model,
        wavelength_m=calibration.geometry.wfs_wavelength_m,
        remove_piston=True,
    )
    return phase_rad


def test_static_detector_loop_converges_and_command_norm_is_finite_after_50_steps(closed_loop_case):
    calibration, dm_model, poke = closed_loop_case
    static_phase = _dm_generated_phase(closed_loop_case)

    history = run_detector_integrator_loop(
        static_phase,
        calibration,
        dm_model,
        poke,
        DetectorLoopConfig(
            n_steps=50,
            gain=0.35,
            leak=0.0,
            latency_frames=0,
            include_detector_noise=False,
            source_note="Static deterministic loop configuration.",
        ),
    )

    tail = history.residual_opd_rms[-10:]
    assert history.residual_opd_rms.shape == (50,)
    assert history.command_norm.shape == (50,)
    assert history.command_rms_nm.shape == (50,)
    assert history.command_l2_norm_nm.shape == (50,)
    assert history.valid_centroid_frac.shape == (50,)
    assert history.command_history_nm.shape == (50, dm_model.n_actuators)
    assert history.residual_opd_rms[10] < history.residual_opd_rms[0]
    assert history.residual_opd_rms[-1] < 0.05 * history.residual_opd_rms[0]
    assert np.std(tail) < 1.0e-4 * history.residual_opd_rms[0]
    assert np.isfinite(history.command_norm[-1])
    assert history.command_rms_nm == pytest.approx(
        np.sqrt(np.mean(history.command_history_nm**2, axis=1))
    )
    assert history.command_l2_norm_nm == pytest.approx(
        np.linalg.norm(history.command_history_nm, axis=1)
    )
    assert history.command_l2_norm_nm == pytest.approx(
        np.sqrt(dm_model.n_actuators) * history.command_rms_nm
    )
    assert np.all(history.valid_centroid_frac == pytest.approx(1.0))


def test_loop_history_summary_and_units_are_reported(closed_loop_case):
    calibration, dm_model, poke = closed_loop_case
    static_phase = _dm_generated_phase(closed_loop_case, command_scale_nm=0.5)

    history = run_detector_integrator_loop(
        static_phase,
        calibration,
        dm_model,
        poke,
        DetectorLoopConfig(
            n_steps=12,
            gain=0.3,
            frame_rate_hz=1000.0,
            source_note="History metadata unit-test configuration.",
        ),
    )
    summary = loop_history_summary(history)

    assert summary["n_steps"] == 12
    assert summary["source_class"] == "synthetic_assumed"
    assert len(summary["config_hash"]) == 64
    assert history.units["residual_opd_rms"] == "nm_OPD_RMS"
    assert history.units["command_rms_nm"] == "nm_OPD_equivalent_RMS_across_actuators"
    assert history.units["command_l2_norm_nm"] == "nm_OPD_equivalent_L2_norm"
    assert history.units["command_norm"] == "nm_OPD_equivalent_L2_norm_compatibility_alias"
    assert history.units["valid_centroid_frac"] == "fraction"


def test_loop_hash_tracks_phase_truth_content_not_only_shape(closed_loop_case):
    calibration, dm_model, poke = closed_loop_case
    static_phase = _dm_generated_phase(closed_loop_case, command_scale_nm=0.5)
    config = DetectorLoopConfig(
        n_steps=4,
        gain=0.3,
        include_detector_noise=False,
        source_note="Loop hash truth-content regression configuration.",
    )

    first = run_detector_integrator_loop(static_phase, calibration, dm_model, poke, config)
    identical = run_detector_integrator_loop(static_phase.copy(), calibration, dm_model, poke, config)
    changed = run_detector_integrator_loop(1.01 * static_phase, calibration, dm_model, poke, config)

    assert first.config_hash == identical.config_hash
    assert first.config_hash != changed.config_hash


def test_dynamic_loop_with_noise_and_latency_has_finite_histories(closed_loop_case):
    calibration, dm_model, poke = closed_loop_case
    phase_maps = []
    for step in range(18):
        scale = 0.65 + 0.25 * np.sin(2.0 * np.pi * step / 9.0)
        phase_maps.append(_dm_generated_phase(closed_loop_case, command_scale_nm=scale))
    phase_sequence = np.asarray(phase_maps)

    history = run_detector_integrator_loop(
        phase_sequence,
        calibration,
        dm_model,
        poke,
        DetectorLoopConfig(
            n_steps=18,
            gain=0.25,
            leak=0.02,
            latency_frames=2,
            frame_rate_hz=500.0,
            include_detector_noise=True,
            seed=23,
            source_note="Noisy dynamic latency unit-test configuration.",
        ),
    )

    assert history.latency_frames == 2
    assert history.latency_ms == pytest.approx(4.0)
    assert history.command_norm[0] == pytest.approx(0.0)
    assert history.command_norm[1] == pytest.approx(0.0)
    assert np.all(np.isfinite(history.residual_opd_rms))
    assert np.all(np.isfinite(history.command_norm))
    assert np.all(np.isfinite(history.valid_centroid_frac))
    assert np.min(history.valid_centroid_frac) > 0.9


def test_loop_config_rejects_invalid_controller_settings():
    with pytest.raises(ClosedLoopError, match="leak"):
        DetectorLoopConfig(leak=1.0)
    with pytest.raises(ClosedLoopError, match="latency_frames"):
        DetectorLoopConfig(latency_frames=-1)
    with pytest.raises(ClosedLoopError, match="frame_rate_hz"):
        DetectorLoopConfig(frame_rate_hz=0.0)
    with pytest.raises(ClosedLoopError, match="latency_frames must be an integer"):
        DetectorLoopConfig(latency_frames=1.5)  # type: ignore[arg-type]
    with pytest.raises(ClosedLoopError, match="n_steps must be an integer"):
        DetectorLoopConfig(n_steps=4.0)  # type: ignore[arg-type]
