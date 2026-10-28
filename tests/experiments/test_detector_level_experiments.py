"""Review 2026-10-16: controlled E6 photometry (R5) and isolated detector noise.

Configuration-only checks and short 2 m loops; no 12 m system is built.
"""

from __future__ import annotations

import numpy as np
import pytest

from shwfs_ao.detector.physical_config import BandpassConfig, physical_budget
from shwfs_ao.experiments.detector_level import (
    paired_noise_run,
    science_run,
    with_matched_photometry,
    with_physics,
)
from shwfs_ao.experiments.scao import physical_detector_config
from shwfs_ao.io.configs import load_system_profile


def _budget(config):
    return physical_budget(
        physical_detector_config(config),
        wfs_wavelength_m=config.wfs_wavelength_m,
        full_subaperture_area_m2=1.0,
        pixel_solid_angle_sr=1.0e-12,
    )


def test_matched_photometry_changes_the_optics_band_but_not_the_electrons() -> None:
    base = load_system_profile("det_emccd_12m_medium_derived", 3)
    mono = with_physics(base, bandpass=BandpassConfig(kind="monochromatic", band_min_m=5.5e-7, band_max_m=8.5e-7))
    # The plain 550-850 nm arm detects 5.7 % more source and sky electrons.
    assert _budget(mono).detected_e_full_subap / _budget(base).detected_e_full_subap == pytest.approx(1.056988833, rel=1e-9)
    matched = with_matched_photometry(mono, base)
    assert matched.detector_physics.bandpass == mono.detector_physics.bandpass
    assert _budget(matched).detected_e_full_subap == pytest.approx(_budget(base).detected_e_full_subap, rel=1e-12)
    assert _budget(matched).sky_e_per_pixel_full_subap == pytest.approx(_budget(base).sky_e_per_pixel_full_subap, rel=1e-12)


def test_the_paired_noise_run_isolates_the_temporal_detector_noise() -> None:
    config = load_system_profile("det_emccd_2m_synthetic", 1)
    paired = paired_noise_run(config, root_seed=7, n_steps=40, burn_in_frames=10, block_frames=10)
    # The noise-on arm is the canonical noise-on run, bit for bit.
    reference = science_run(config, root_seed=7, n_steps=40, burn_in_frames=10)
    assert paired["arms"]["noise_on"]["post_update_rms_m"] == reference["post_update_rms_m"]
    assert paired["arms"]["noise_on"]["post_update_mean_square_m2"] == reference["post_update_mean_square_m2"]
    twin = paired["arms"]["operating_expectation"]
    assert twin["valid_measurement_fraction"] == 1.0 and not twin["lost_lock"]
    assert paired["mean_square_difference_m2"] == pytest.approx(
        paired["arms"]["noise_on"]["post_update_mean_square_m2"] - twin["post_update_mean_square_m2"]
    )
    # The residual-map difference is positive and needs no cross term.
    assert paired["noise_variance_m2"] > 0.0
    assert np.isfinite(paired["noise_variance_standard_error_m2"])
    assert paired["predicted_centroid_variance_px2"] > 0.0


# -- S4 traced paired experiment and the mask-locked arm (ticket T1, 2026-10-20) --


from shwfs_ao.core.types import DetectorTelemetry, MeasurementVector, WfsMeasurement  # noqa: E402
from shwfs_ao.experiments.detector_level import (  # noqa: E402
    MASK_LOCKED_NOISE_ARMS,
    PAIRED_NOISE_ARMS,
    TRACE_SCHEMA,
    MaskLockError,
    _MaskLockedSensor,
    paired_noise_run_mask_locked,
    paired_noise_run_traced,
)

SMALL = dict(root_seed=7, n_steps=40, burn_in_frames=10, block_frames=10)


def _scalars(result: dict) -> dict:
    """Every JSON scalar of a paired-run result except timing."""

    out = {}
    for key, value in result.items():
        if key in ("wall_s", "trace", "operating_state", "trace_summary", "lock", "mask_lock_protocol"):
            continue
        if isinstance(value, dict):
            for inner, item in value.items():
                if isinstance(item, dict):
                    for name, number in item.items():
                        out[f"{key}/{inner}/{name}"] = number
                else:
                    out[f"{key}/{inner}"] = item
        else:
            out[key] = value
    return out


def test_the_traced_run_reproduces_the_untraced_scalars_bit_for_bit_and_declares_its_arrays() -> None:
    config = load_system_profile("det_emccd_2m_synthetic", 1)
    untraced = paired_noise_run(config, **SMALL)
    traced = paired_noise_run_traced(config, **SMALL)
    assert _scalars(traced) == _scalars(untraced)
    trace = traced["trace"]
    assert trace["schema"] == TRACE_SCHEMA
    assert trace["arm_order"] == list(PAIRED_NOISE_ARMS) and trace["noisy_arm"] == "noise_on"
    n_steps, burn_in, n_rows, n_lenslets = 40, 10, 42, 21
    assert trace["frame_index"].dtype == np.int64 and trace["frame_index"].shape == (n_steps,)
    np.testing.assert_array_equal(trace["analysed_frame_index"], np.arange(burn_in, n_steps))
    for name in ("delta_v_m2", "mean_square_difference_m2", "cross_term_m2"):
        assert trace[name].dtype == np.float64 and trace[name].shape == (n_steps - burn_in,)
    # The legacy scalar is the frame mean of the traced series, exactly.
    assert float(np.mean(trace["delta_v_m2"])) == untraced["noise_variance_m2"]
    assert float(np.mean(trace["mean_square_difference_m2"])) == untraced["mean_square_difference_m2"]
    np.testing.assert_array_equal(
        trace["cross_term_m2"], trace["mean_square_difference_m2"] - trace["delta_v_m2"]
    )
    assert trace["calibration_valid_rows"].dtype == np.dtype(bool) and len(trace["row_ids"]) == n_rows
    for arm in PAIRED_NOISE_ARMS:
        entry = trace["arms"][arm]
        assert entry["measurement_row_masks"].dtype == np.dtype(bool)
        assert entry["measurement_row_masks"].shape == (n_steps, n_rows)
        assert entry["reconstruction_usable"].dtype == np.dtype(bool)
        assert entry["saturation_fraction"].shape == (n_steps,)
        telemetry = entry["telemetry"]
        assert entry["telemetry_frames"] == n_steps and entry["telemetry_unavailable"] == []
        for name in ("centroids_xy_px", "expected_centroids_xy_px", "centroid_sigma_xy_px"):
            assert telemetry[name].dtype == np.float64 and telemetry[name].shape == (n_steps, n_lenslets, 2)
        for name in ("valid_subapertures", "uncertainty_supported", "valid_by_snr"):
            assert telemetry[name].dtype == np.dtype(bool) and telemetry[name].shape == (n_steps, n_lenslets)
        assert telemetry["total_snr"].shape == (n_steps, n_lenslets)
        assert len(entry["subaperture_ids"]) == n_lenslets
        # Lenslet validity repeated over x and y, within the calibration-valid
        # rows, is the effective row mask of the same frame.
        np.testing.assert_array_equal(
            entry["measurement_row_masks"],
            np.repeat(telemetry["valid_subapertures"], 2, axis=1) & trace["calibration_valid_rows"][None, :],
        )
    # The twin measures the expected frame itself, so its centroids equal the
    # expected centroids up to the ADC quantization of a noiseless frame: the
    # two centroid fields share one coordinate convention.
    twin = trace["arms"]["operating_expectation"]["telemetry"]
    valid = twin["valid_subapertures"]
    difference = (twin["centroids_xy_px"] - twin["expected_centroids_xy_px"])[valid]
    assert np.all(np.abs(difference) < 0.01)
    # The noisy arm's residual is of the order of its model sigma.
    noisy = trace["arms"]["noise_on"]["telemetry"]
    support = noisy["valid_subapertures"] & noisy["uncertainty_supported"]
    residual = (noisy["centroids_xy_px"] - noisy["expected_centroids_xy_px"])[support]
    model = noisy["centroid_sigma_xy_px"][support] ** 2
    pooled = float(np.mean(residual**2) / np.mean(model))
    assert 0.5 < pooled < 2.0, pooled
    weights = trace["propagation_weights"]
    assert weights["available"] and weights["weights_m2_per_px2"].shape == (n_rows,)
    assert np.all(weights["weights_m2_per_px2"] > 0.0) and weights["saturated_probe_rows"] == 0
    operating = traced["operating_state"]
    assert operating["available"] and operating["support_lenslets"] == n_lenslets
    assert operating["equal_weight"]["realized_variance_px2"] > 0.0
    assert operating["propagation_weighted"]["ratio_variance_over_model"] > 0.0
    summary = traced["trace_summary"]
    assert summary["mask_disagreement_frames"] == 0 and summary["gate_quiet"] is True
    assert traced["predicted_centroid_variance_px2"] == untraced["predicted_centroid_variance_px2"]


def test_the_traced_run_can_retain_the_residual_maps_the_legacy_recorder_saw() -> None:
    config = load_system_profile("det_emccd_2m_synthetic", 1)
    traced = paired_noise_run_traced(config, retain_residual_maps=True, **{**SMALL, "n_steps": 16, "burn_in_frames": 4})
    maps = traced["trace"]["residual_maps"]
    assert maps is not None and maps["pupil_mask"].dtype == np.dtype(bool)
    samples = int(np.count_nonzero(maps["pupil_mask"]))
    for arm in PAIRED_NOISE_ARMS:
        assert maps[arm].dtype == np.float32 and maps[arm].shape == (12, samples)
    # The traced series is the estimator applied to these very maps.
    delta = maps["noise_on"].astype(float) - maps["operating_expectation"].astype(float)
    delta -= delta.mean(axis=1, keepdims=True)
    np.testing.assert_array_equal(np.mean(delta**2, axis=1), traced["trace"]["delta_v_m2"])


def test_the_mask_locked_run_has_its_own_order_identity_and_an_exact_lock_on_the_fixture() -> None:
    config = load_system_profile("det_emccd_2m_synthetic", 1)
    locked = paired_noise_run_mask_locked(config, **SMALL)
    traced = paired_noise_run_traced(config, **SMALL)
    assert tuple(locked["mask_lock_protocol"]["arm_order"]) == MASK_LOCKED_NOISE_ARMS == ("operating_expectation", "noise_on_mask_locked")
    assert locked["mask_lock_protocol"]["forced_row_policy"] == "refuse_nonfinite_forced_rows"
    assert set(locked["arms"]) == set(MASK_LOCKED_NOISE_ARMS)
    lock = locked["lock"]
    assert lock["exact"] is True and lock["frames_measured"] == 40 == lock["frames_planned"]
    assert lock["rows_unaddable_total"] == 0 and lock["mismatched_frames"] == 0
    arms = locked["trace"]["arms"]
    # The twin arm is the same loop as the traced run's twin; the locked arm is
    # another component (its own wrapper hash), so another loop identity.
    assert arms["operating_expectation"]["history_config_hash"] == traced["trace"]["arms"]["operating_expectation"]["history_config_hash"]
    assert arms["noise_on_mask_locked"]["history_config_hash"] != traced["trace"]["arms"]["noise_on"]["history_config_hash"]
    assert arms["noise_on_mask_locked"]["component_hashes"]["wfs"] == lock["wrapper_config_hash"]
    assert lock["wrapper_config_hash"] != traced["trace"]["arms"]["noise_on"]["component_hashes"]["wfs"]
    np.testing.assert_array_equal(
        arms["noise_on_mask_locked"]["measurement_row_masks"], arms["operating_expectation"]["measurement_row_masks"]
    )
    # On this fixture the arms never disagree, so the lock changes no row and
    # the locked arm reproduces the plain noisy arm; the lock arrays say so.
    assert lock["rows_removed_total"] == 0 and lock["rows_added_total"] == 0
    assert locked["noise_variance_m2"] == traced["noise_variance_m2"]
    assert locked["trace"]["mask_lock"]["own_valid_subapertures"].shape == (40, 21)
    assert locked["config_hash"] == traced["config_hash"]


class _StubSensor:
    """A sensor stand-in: scripted centroids and validity, counted calls, no physics."""

    config_hash = "stub-sensor"
    subaperture_ids = ("L0", "L1", "L2")
    row_ids = ("L0:x", "L0:y", "L1:x", "L1:y", "L2:x", "L2:y")

    def __init__(self, frames: list[tuple[np.ndarray, np.ndarray]]) -> None:
        self._frames = frames
        self.calls = 0
        self.model_calls = 0

    def noise_model(self, residual):
        self.model_calls += 1
        return "model"

    def measure(self, residual_opd_m, *, random_streams, include_noise):
        centroids, valid = self._frames[self.calls]
        self.calls += 1
        count = len(self.subaperture_ids)
        shifts = centroids - 7.0
        telemetry = DetectorTelemetry(
            subaperture_ids=self.subaperture_ids,
            centroids_xy_px=centroids,
            reference_centroids_xy_px=np.full((count, 2), 7.0),
            fluxes_e=np.full(count, 500.0),
            valid_subapertures=valid,
            valid_by_flux=np.ones(count, dtype=bool),
            valid_by_snr=valid,
            valid_by_uncertainty=np.ones(count, dtype=bool),
            valid_by_clipping=np.ones(count, dtype=bool),
            peak_snr=np.full(count, 10.0),
            total_snr=np.full(count, 30.0),
            centroid_sigma_px=np.full(count, 0.05),
            clipping_fraction=np.zeros(count),
            telemetry_level="summary",
            uncertainty_supported=np.ones(count, dtype=bool),
            centroid_sigma_xy_px=np.full((count, 2), 0.05),
            expected_centroids_xy_px=np.where(np.isfinite(centroids), 7.0, np.nan),
        )
        return WfsMeasurement(
            vector=MeasurementVector(
                values=np.where(valid[:, None], shifts, np.nan).reshape(-1),
                valid_rows=np.repeat(valid, 2),
                row_ids=self.row_ids,
                measurement_unit="pixel",
            ),
            valid_subapertures=valid,
            metadata={"sensor_backend_name": "stub"},
            detector_telemetry=telemetry,
        )


def _finite_centroids(*rows: tuple[float, float]) -> np.ndarray:
    return np.array(rows, dtype=float)


def test_the_mask_locked_wrapper_replays_rows_at_the_right_frame_and_refuses_what_it_cannot_lock() -> None:
    all_valid = np.array([True, True, True])
    frames = [
        (_finite_centroids((7.1, 7.0), (6.9, 7.2), (7.0, 7.0)), all_valid),                       # frame 0: remove L1
        (_finite_centroids((7.1, 7.0), (6.9, 7.2), (7.0, 7.0)), np.array([True, False, True])),   # frame 1: add L1 (finite)
        (_finite_centroids((7.1, 7.0), (np.nan, np.nan), (7.0, 7.0)), np.array([True, False, True])),  # frame 2: L1 not finite
    ]
    schedule = np.array(
        [
            [True, True, False, False, True, True],
            [True, True, True, True, True, True],
            [True, True, True, True, True, True],
        ]
    )
    sensor = _StubSensor(frames)
    wrapper = _MaskLockedSensor(sensor, schedule=schedule, row_ids=sensor.row_ids, schedule_source="test twin")
    assert wrapper.config_hash != sensor.config_hash
    assert wrapper.row_ids == sensor.row_ids and wrapper.n_frames == 3
    # Calls that bypass the lock never advance the frame counter.
    assert wrapper.noise_model(None) == "model" and sensor.model_calls == 1 and wrapper.frames_measured == 0
    first = wrapper.measure(None, random_streams=None, include_noise=True)
    np.testing.assert_array_equal(first.vector.valid_rows, schedule[0])
    assert np.all(np.isnan(first.vector.values[2:4])) and np.all(np.isfinite(first.vector.values[schedule[0]]))
    np.testing.assert_array_equal(first.valid_subapertures, [True, False, True])
    np.testing.assert_array_equal(first.detector_telemetry.valid_subapertures, [True, False, True])
    assert first.metadata["mask_lock"] == {
        "schema": "shwfs_ao.experiments.detector_level.mask_locked_replay.v1",
        "frame_index": 0, "rows_removed": 2, "rows_added": 0, "rows_unaddable": 0,
    }
    second = wrapper.measure(None, random_streams=None, include_noise=True)
    np.testing.assert_array_equal(second.vector.valid_rows, schedule[1])
    # The forced lenslet carries its raw noisy shift, and the telemetry is made
    # consistent: its validity and the gate it failed are raised together,
    # while the sensor's own decision is kept by the wrapper.
    np.testing.assert_allclose(second.vector.values[2:4], [-0.1, 0.2])
    assert second.detector_telemetry.valid_subapertures[1] and second.detector_telemetry.valid_by_snr[1]
    assert second.metadata["mask_lock"]["rows_added"] == 2 and second.metadata["mask_lock"]["rows_removed"] == 0
    np.testing.assert_array_equal(wrapper.own_valid_subapertures[1], [True, False, True])
    assert wrapper.frames_measured == 2
    with pytest.raises(MaskLockError, match="not finite"):
        wrapper.measure(None, random_streams=None, include_noise=True)
    # A partial lock keeps the unaddable rows invalid and counts them; it is
    # never reported as exact by its owner.
    partial = _MaskLockedSensor(
        _StubSensor(frames), schedule=schedule, row_ids=sensor.row_ids, schedule_source="test twin", allow_partial_lock=True
    )
    assert partial.config_hash != wrapper.config_hash
    for _ in range(2):
        partial.measure(None, random_streams=None, include_noise=True)
    third = partial.measure(None, random_streams=None, include_noise=True)
    np.testing.assert_array_equal(third.valid_subapertures, [True, False, True])
    assert partial.rows_unaddable[2] == 2 and partial.frames_measured == 3
    with pytest.raises(MaskLockError, match="no row mask to replay"):
        partial.measure(None, random_streams=None, include_noise=True)


def test_the_mask_locked_wrapper_refuses_incompatible_layouts_and_binds_its_schedule() -> None:
    sensor = _StubSensor([])
    good = np.ones((2, 6), dtype=bool)
    with pytest.raises(MaskLockError, match="row IDs"):
        _MaskLockedSensor(sensor, schedule=good, row_ids=("a",) * 6, schedule_source="s")
    with pytest.raises(MaskLockError, match="boolean matrix"):
        _MaskLockedSensor(sensor, schedule=np.ones((2, 5), dtype=bool), row_ids=sensor.row_ids, schedule_source="s")
    with pytest.raises(MaskLockError, match="boolean matrix"):
        _MaskLockedSensor(sensor, schedule=np.ones((2, 6)), row_ids=sensor.row_ids, schedule_source="s")
    with pytest.raises(MaskLockError, match="separates the x and y rows"):
        _MaskLockedSensor(
            sensor, schedule=np.array([[True, False, True, True, True, True]]), row_ids=sensor.row_ids, schedule_source="s"
        )
    one = _MaskLockedSensor(sensor, schedule=good, row_ids=sensor.row_ids, schedule_source="twin A")
    same = _MaskLockedSensor(sensor, schedule=good.copy(), row_ids=sensor.row_ids, schedule_source="twin A")
    other_schedule = good.copy()
    other_schedule[1, 2:4] = False
    different = _MaskLockedSensor(sensor, schedule=other_schedule, row_ids=sensor.row_ids, schedule_source="twin A")
    other_source = _MaskLockedSensor(sensor, schedule=good, row_ids=sensor.row_ids, schedule_source="twin B")
    assert one.config_hash == same.config_hash
    assert len({one.config_hash, different.config_hash, other_source.config_hash}) == 3
    assert not one.schedule.flags.writeable


def test_the_mask_lock_adds_a_row_whose_expected_centroid_is_undefined() -> None:
    # Independent review T1-01: the expected centroid is a diagnostic and no
    # condition of the lock; only the noisy centroid must be finite.
    from dataclasses import replace

    sensor = _StubSensor([(_finite_centroids((7.1, 7.0), (6.9, 7.2), (7.0, 7.0)), np.array([True, False, True]))])
    original_measure = sensor.measure

    def measure_with_undefined_expectation(residual, *, random_streams, include_noise):
        measurement = original_measure(residual, random_streams=random_streams, include_noise=include_noise)
        telemetry = replace(measurement.detector_telemetry, expected_centroids_xy_px=np.full((3, 2), np.nan))
        return WfsMeasurement(vector=measurement.vector, valid_subapertures=measurement.valid_subapertures, metadata=measurement.metadata, detector_telemetry=telemetry)

    sensor.measure = measure_with_undefined_expectation  # type: ignore[method-assign]
    wrapper = _MaskLockedSensor(sensor, schedule=np.ones((1, 6), dtype=bool), row_ids=sensor.row_ids, schedule_source="twin")
    locked = wrapper.measure(None, random_streams=None, include_noise=True)
    np.testing.assert_array_equal(locked.valid_subapertures, [True, True, True])
    assert np.all(np.isnan(locked.detector_telemetry.expected_centroids_xy_px)) and wrapper.rows_added[0] == 2
