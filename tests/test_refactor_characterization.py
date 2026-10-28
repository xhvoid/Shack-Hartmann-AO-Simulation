"""Portable seeded component checks captured by AO-REF-000.

Byte-level array hashes in the manifest are forensic observations only.  The
checks here use explicit scalar/array tolerances so the Python 3.10 and 3.14
NumPy constraint sets can exercise the same physical ordering and sign rules.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ao_closed_loop import DetectorLoopConfig, run_detector_integrator_loop
from dm_model import DMConfig, build_dm_model, synthesize_dm_opd_nm, synthesize_dm_phase_rad
from interaction_matrix import (
    PokeMatrixConfig,
    PokeMtxResult,
    build_detector_dm_poke_matrix,
    expand_controlled_commands,
    tsvd_reconstruct_commands,
)
from phase_screen import fourier_phase_screen, rms
from psf_tools import compute_psf_from_phase, strehl_ratio
from synthetic_instrument_data import (
    DetectorConfig,
    ShwfsGeometryConfig,
    add_configured_detector_noise,
    build_detector_shwfs_calibration,
    make_bad_pixel_mask,
    measure_detector_shwfs,
    phase_tilt_map_rad,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads(
    (
        ROOT
        / "src/shwfs_ao/resources/reference_metrics/refactor_contract_manifest.json"
    ).read_text(encoding="utf-8")
)
FIXTURES = MANIFEST["component_characterization"]["fixtures"]


def _assert_scalar(actual: float, target: dict) -> None:
    assert np.isclose(
        actual,
        target["value"],
        atol=target["abs_tolerance"],
        rtol=target["rel_tolerance"],
    )


@pytest.fixture(scope="module")
def compact_system():
    geometry_values = dict(FIXTURES["shack_hartmann"]["inputs"]["geometry_exact"])
    detector_values = dict(FIXTURES["shack_hartmann"]["inputs"]["calibration_detector_exact"])
    geometry = ShwfsGeometryConfig(**geometry_values)
    detector = DetectorConfig(**detector_values)
    calibration = build_detector_shwfs_calibration(geometry=geometry, detector=detector)

    dm_values = dict(FIXTURES["deformable_mirror"]["inputs"]["config_exact"])
    dm_values["dead_actuator_indices"] = tuple(dm_values["dead_actuator_indices"])
    dm_values["stuck_actuator_indices"] = tuple(dm_values["stuck_actuator_indices"])
    dm_model = build_dm_model(
        calibration.x_m,
        calibration.y_m,
        calibration.pupil_mask,
        DMConfig(**dm_values),
    )

    poke_values = dict(FIXTURES["detector_dm_poke_matrix"]["inputs"]["poke_config_exact"])
    poke_values["rcond_scan_grid"] = tuple(poke_values["rcond_scan_grid"])
    if poke_values["controlled_actuator_indices"] is not None:
        poke_values["controlled_actuator_indices"] = tuple(poke_values["controlled_actuator_indices"])
    poke = build_detector_dm_poke_matrix(
        calibration,
        dm_model,
        PokeMatrixConfig(**poke_values),
    )
    return calibration, dm_model, poke


def test_seeded_phase_screen_rms_piston_mask_and_samples():
    fixture = FIXTURES["phase_screen"]
    values = fixture["inputs"]
    phase, _x_m, _y_m, mask = fourier_phase_screen(
        N=values["N"],
        delta=values["delta_m"],
        r0=values["r0_m"],
        L0=values["outer_scale_L0_m"],
        diameter=values["diameter_m"],
        wavelength=values["wavelength_m"],
        seed=values["seed"],
        target_rms_rad=values["target_rms_rad"],
        normalize_rms=values["normalize_rms"],
        mask_output=values["mask_output"],
    )
    targets = fixture["targets"]

    assert list(phase.shape) == targets["shape"]
    assert int(np.sum(mask)) == targets["illuminated_pixel_count"]
    assert bool(np.all(np.isfinite(phase[mask]))) == targets["finite_inside"]
    assert bool(np.all(np.isnan(phase[~mask]))) == targets["nan_outside"]
    _assert_scalar(rms(phase, mask), targets["pupil_rms_rad"])
    _assert_scalar(float(np.mean(phase[mask])), targets["pupil_piston_rad"])
    for sample in targets["selected_samples_rad"]:
        y_index, x_index = sample["index_yx"]
        assert np.isclose(
            phase[y_index, x_index],
            sample["value"],
            atol=sample["abs_tolerance"],
            rtol=sample["rel_tolerance"],
        )


def test_detector_prnu_poisson_read_order_and_fixed_defect_mask():
    fixture = FIXTURES["detector_draw_order_and_defects"]
    values = fixture["inputs"]
    coords = np.arange(5, dtype=float) - 2.0
    spot_x, spot_y = np.meshgrid(coords, coords)
    spot = np.exp(-((spot_x - 0.35) ** 2 + (spot_y + 0.20) ** 2) / (2.0 * 1.1**2))
    spot /= np.sum(spot)
    detector_values = dict(values["detector_config_exact"])
    detector = DetectorConfig(**detector_values)
    image = add_configured_detector_noise(
        spot,
        detector,
        seed=values["seed"],
        clip_negative=values["clip_negative"],
    )

    rng = np.random.default_rng(values["seed"])
    flat = rng.normal(loc=1.0, scale=detector.prnu_rms, size=spot.shape)
    expected = detector.photons_per_subap_frame * detector.qe * spot
    expected += detector.dark_e_per_s * detector.exposure_s
    expected += detector.background_e_per_pixel_frame
    expected *= np.maximum(flat, 0.0)
    manual = rng.poisson(expected).astype(float)
    manual += rng.normal(scale=detector.read_noise_e, size=spot.shape)
    manual = np.minimum(manual, detector.full_well_e)
    manual = np.maximum(manual, 0.0)

    assert values["draw_order"] == ["PRNU normal", "Poisson shot", "Gaussian read"]
    assert np.array_equal(image, manual)
    assert np.array_equal(image, add_configured_detector_noise(spot, detector, seed=values["seed"]))
    assert not np.array_equal(image, add_configured_detector_noise(spot, detector, seed=values["seed"] + 1))
    for name, target in fixture["portable_scalar_targets"].items():
        actual = {
            "spot_sum": np.sum(spot),
            "image_sum_e": np.sum(image),
            "image_min_e": np.min(image),
            "image_max_e": np.max(image),
        }[name]
        _assert_scalar(float(actual), target)

    defect = fixture["fixed_bad_pixel_mask"]
    mask = make_bad_pixel_mask(**defect["inputs"])
    rows = ["".join("1" if value else "0" for value in row) for row in mask]
    assert rows == defect["rows_as_0_1_strings"]
    assert int(np.sum(mask)) == defect["bad_pixel_count"]
    _assert_scalar(float(np.mean(mask)), defect["bad_pixel_fraction_realized"])


def test_shack_hartmann_subaperture_and_xy_row_ordering_and_sign(compact_system):
    calibration, _dm_model, _poke = compact_system
    fixture = FIXTURES["shack_hartmann"]
    targets = fixture["targets"]
    amplitude = fixture["inputs"]["tilt_amplitude_rad_per_m"]

    x_measurement = measure_detector_shwfs(
        phase_tilt_map_rad(calibration, tilt_x_rad_per_m=amplitude),
        calibration,
        include_noise=False,
    )
    y_measurement = measure_detector_shwfs(
        phase_tilt_map_rad(calibration, tilt_y_rad_per_m=amplitude),
        calibration,
        include_noise=False,
    )

    assert calibration.n_valid_subapertures == targets["n_valid_subapertures"] == 12
    assert np.array_equal(calibration.centers_m, targets["retained_centers_m_in_current_order"])
    assert np.allclose(
        x_measurement.shifts_px.reshape(-1),
        targets["positive_x_tilt_rows_current"],
        atol=2e-8,
        rtol=2e-7,
    )
    assert np.allclose(
        y_measurement.shifts_px.reshape(-1),
        targets["positive_y_tilt_rows_current"],
        atol=2e-8,
        rtol=2e-7,
    )
    _assert_scalar(float(np.mean(x_measurement.shifts_px[:, 0])), targets["mean_positive_x_shift_px"])
    _assert_scalar(float(np.mean(y_measurement.shifts_px[:, 1])), targets["mean_positive_y_shift_px"])
    assert int(np.sign(np.mean(x_measurement.shifts_px[:, 0]))) == 1
    assert int(np.sign(np.mean(y_measurement.shifts_px[:, 1]))) == -1
    assert targets["flattening_contract"].startswith("C order")
    assert targets["row_labels"][:4] == ["subap_000:x", "subap_000:y", "subap_001:x", "subap_001:y"]


def test_dm_actuator_order_and_positive_command_opd_sign(compact_system):
    _calibration, dm_model, _poke = compact_system
    fixture = FIXTURES["deformable_mirror"]
    values = fixture["inputs"]
    targets = fixture["targets"]

    commands = np.zeros(dm_model.n_actuators)
    commands[values["positive_command_index"]] = values["positive_command_nm_opd_equivalent"]
    raw = synthesize_dm_opd_nm(commands, dm_model, remove_piston=False)
    piston_removed = synthesize_dm_opd_nm(commands, dm_model, remove_piston=True)
    y_index, x_index = targets["nearest_actuator_sample"]["index_yx"]

    assert dm_model.n_actuators == targets["n_actuators"] == 13
    assert np.array_equal(dm_model.actuator_centers_m, targets["actuator_centers_m_in_command_order"])
    _assert_scalar(dm_model.actuator_pitch_m, targets["actuator_pitch_m"])
    _assert_scalar(float(np.nanmax(raw.opd_nm)), targets["raw_opd_max_inside_nm"])
    _assert_scalar(float(raw.opd_nm[y_index, x_index]), targets["nearest_actuator_sample"]["opd_nm"])
    assert raw.opd_nm[y_index, x_index] > 0.0
    _assert_scalar(
        float(np.nanmean(piston_removed.opd_nm[dm_model.pupil_mask])),
        targets["piston_removed_mean_inside_nm"],
    )


def test_detector_dm_poke_matrix_shape_rank_order_and_spectrum(compact_system):
    _calibration, _dm_model, poke = compact_system
    targets = FIXTURES["detector_dm_poke_matrix"]["targets"]

    assert list(poke.poke_matrix.shape) == targets["matrix_shape"] == [24, 13]
    assert poke.rank == targets["rank"] == 13
    assert poke.n_valid_lenslets == targets["n_valid_lenslets"] == 12
    assert poke.n_controlled_actuators == targets["n_controlled_actuators"] == 13
    assert poke.kept_modes == targets["kept_modes"]
    assert poke.rcond == targets["selected_rcond"]
    assert np.array_equal(poke.controlled_actuator_indices, np.arange(13))
    probe = targets["ordering_and_sign_probe"]
    assert np.allclose(
        poke.poke_matrix @ np.asarray(probe["commands_nm"]),
        probe["signal_px_in_interleaved_row_order"],
        atol=probe["absolute_tolerance_px"],
        rtol=probe["relative_tolerance"],
    )
    _assert_scalar(float(poke.singular_values[0]), targets["largest_singular_value_px_per_nm"])
    _assert_scalar(float(poke.singular_values[-1]), targets["smallest_singular_value_px_per_nm"])


def test_analytic_tsvd_command_round_trip():
    fixture = FIXTURES["analytic_tsvd_round_trip"]
    values = fixture["inputs"]
    matrix = np.asarray(values["matrix_px_per_nm"], dtype=float)
    signal = np.asarray(values["measurement_px"], dtype=float)
    singular_values = np.linalg.svd(matrix, compute_uv=False)
    poke = PokeMtxResult(
        poke_matrix=matrix,
        singular_values=singular_values,
        kept_modes=2,
        rcond=values["rcond"],
        source_class="synthetic_assumed",
        rank=2,
        calibration_amplitude_nm=1.0,
        controlled_actuator_indices=np.asarray([0, 1]),
        valid_subaperture_mask=np.asarray([True, True]),
        row_valid=np.ones(4, dtype=bool),
        condition_proxy=float(singular_values[0] / singular_values[-1]),
        config_hash="analytic-tsvd-round-trip",
        calibration_settings={"kind": "analytic_fixture"},
        rcond_grid=(values["rcond"],),
        rcond_scan_summary=({"rcond": values["rcond"], "kept_modes": 2},),
        source_note="AO-REF-000 analytic TSVD fixture.",
    )
    result = tsvd_reconstruct_commands(signal, poke)
    targets = fixture["targets"]

    assert np.allclose(result.commands_nm, targets["reconstructed_commands_nm"], atol=2e-14, rtol=0.0)
    assert result.kept_modes == targets["kept_modes"]
    _assert_scalar(
        float(np.max(np.abs(result.commands_nm - values["true_commands_nm"]))),
        targets["command_max_abs_error_nm"],
    )
    _assert_scalar(result.residual_norm_px, targets["residual_norm_px"])


def test_latency_two_applies_first_increment_on_zero_based_frame_two(compact_system):
    calibration, dm_model, poke = compact_system
    fixture = FIXTURES["latency_two_frames"]
    values = fixture["inputs"]
    controlled = np.asarray(values["truth_controlled_commands_nm"], dtype=float)
    full = expand_controlled_commands(controlled, poke, dm_model)
    truth_phase, _ = synthesize_dm_phase_rad(
        full,
        dm_model,
        wavelength_m=calibration.geometry.wfs_wavelength_m,
        remove_piston=True,
    )
    config = DetectorLoopConfig(**values["loop_config_exact"])
    history = run_detector_integrator_loop(truth_phase, calibration, dm_model, poke, config)
    targets = fixture["targets"]
    nonzero = np.flatnonzero(history.applied_delta_norm_nm > 1e-12)

    assert int(nonzero[0]) == targets["first_nonzero_applied_delta_frame_zero_based"] == 2
    assert np.allclose(history.command_l2_norm_nm[:2], 0.0, atol=1e-12)
    assert np.allclose(
        history.applied_delta_norm_nm,
        targets["applied_delta_norm_nm_current"],
        atol=2e-8,
        rtol=2e-7,
    )
    assert np.allclose(
        history.command_l2_norm_nm,
        targets["command_l2_norm_nm_current"],
        atol=2e-8,
        rtol=2e-7,
    )
    _assert_scalar(history.latency_ms, targets["latency_ms"])
    _assert_scalar(history.applied_delta_norm_nm[2], targets["first_applied_delta_norm_nm"])


def test_psf_sampling_normalization_peak_and_strehl():
    fixture = FIXTURES["psf"]
    values = fixture["inputs"]
    coords = np.linspace(
        values["coordinate_extent"][0],
        values["coordinate_extent"][1],
        values["n_pupil_pixels"],
    )
    x_grid, y_grid = np.meshgrid(coords, coords)
    mask = x_grid**2 + y_grid**2 <= 1.0
    phase = 0.20 * x_grid + 0.10 * (x_grid**2 - y_grid**2)
    psf = compute_psf_from_phase(phase, mask, pad_factor=values["pad_factor"])
    targets = fixture["targets"]

    assert list(psf.shape) == targets["shape"] == [64, 64]
    assert np.all(psf >= 0.0)
    assert list(np.unravel_index(int(np.argmax(psf)), psf.shape)) == targets["peak_index_yx"]
    _assert_scalar(float(np.sum(psf)), targets["sum"])
    _assert_scalar(float(np.max(psf)), targets["peak"])
    _assert_scalar(strehl_ratio(phase, mask, pad_factor=values["pad_factor"]), targets["strehl_peak_ratio"])
