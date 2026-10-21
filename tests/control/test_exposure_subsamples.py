"""DET-08: finite-exposure integration over atmosphere sub-samples."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from shwfs_ao.control.loop import ControlLoopError, run_closed_loop as component_loop
from shwfs_ao.experiments import scao
from shwfs_ao.io.configs import load_system_profile


def _count_calls(monkeypatch, atmosphere) -> list[float]:
    """Record every ``opd_at`` time on the instance itself."""

    times: list[float] = []
    original = atmosphere.opd_at

    def counting(time_s):
        times.append(float(time_s))
        return original(time_s)

    monkeypatch.setattr(atmosphere, "opd_at", counting)
    return times


def _loop(system, config, *, atmosphere=None, wfs=None, **keywords):
    return component_loop(
        scao._loop_config(config),
        random_streams=system.random_streams,
        atmosphere=system.atmosphere if atmosphere is None else atmosphere,
        wfs=system.wfs if wfs is None else wfs,
        dm=system.dm,
        interaction_matrix=system.interaction_matrix,
        reconstructor=system.reconstructor,
        command_projector=system.command_projector,
        controller=system.controller,
        include_noise=config.controller.include_noise,
        **keywords,
    )


def _config(n_steps: int = 6):
    config = load_system_profile("det_ccd_2m_synthetic", 1)
    return replace(config, controller=replace(config.controller, n_steps=n_steps))


def test_one_subsample_is_bit_identical_with_one_atmosphere_call_per_frame(monkeypatch) -> None:
    config = _config()
    system = scao.build_scao_system(config)
    reference = _loop(system, config)
    times = _count_calls(monkeypatch, system.atmosphere)
    explicit = _loop(system, config, exposure_subsamples=1, exposure_s=1.0e-3)
    for name in ("open_loop_opd_rms_m", "post_update_residual_opd_rms_m", "applied_command_opd_m"):
        if hasattr(reference, name):
            assert np.array_equal(getattr(reference, name), getattr(explicit, name)), name
    assert times == [k / config.controller.frame_rate_hz for k in range(config.controller.n_steps)]


def test_subsamples_sample_within_the_exposure(monkeypatch) -> None:
    config = _config(n_steps=3)
    system = scao.build_scao_system(config)
    times = _count_calls(monkeypatch, system.atmosphere)
    _loop(system, config, exposure_subsamples=4, exposure_s=1.0e-3)
    expected = [k * 1.0e-3 + j * 2.5e-4 for k in range(3) for j in range(4)]
    assert np.allclose(times, expected, rtol=0, atol=1e-15)


def test_a_static_atmosphere_gives_the_same_frames_for_any_subsample_count() -> None:
    config = _config(n_steps=4)
    system = scao.build_scao_system(config)
    residual = np.asarray(system.atmosphere.opd_at(0.0))
    residual = np.where(np.isfinite(residual), residual, 0.0)
    single = system.wfs.measure(residual, random_streams=system.random_streams, include_noise=False)
    triple = system.wfs.measure_exposure([residual] * 3, random_streams=system.random_streams, include_noise=False)
    np.testing.assert_allclose(triple.vector.values, single.vector.values, rtol=1e-12, atol=1e-12)


def test_opposite_tilts_within_one_exposure_broaden_rather_than_cancel() -> None:
    config = _config(n_steps=2)
    system = scao.build_scao_system(config)
    geometry = system.wfs.geometry
    tilt = np.where(np.asarray(geometry.pupil_mask), 4.0e-7 * np.asarray(geometry.x_m), 0.0)
    flat = np.zeros(geometry.pupil_shape)

    def width(measurement) -> float:
        frame = measurement.detector_telemetry.detector_frames[6]
        image = np.clip(frame.expected_source_e, 0.0, None)
        x = np.arange(image.shape[1])
        profile = image.sum(axis=0)
        mean = float(np.sum(profile * x) / profile.sum())
        return float(np.sum(profile * (x - mean) ** 2) / profile.sum())

    streams = system.random_streams
    still = system.wfs.measure_exposure([flat, flat], random_streams=streams, include_noise=False)
    one_way = system.wfs.measure(tilt, random_streams=streams, include_noise=False)
    split = system.wfs.measure_exposure([tilt, -tilt], random_streams=streams, include_noise=False)
    shift = float(one_way.vector.values[12])
    assert abs(shift) > 0.5
    assert abs(split.vector.values[12]) < 0.05 * abs(shift)  # the mean centroid stays put
    # Two equal copies displaced by +-s add s^2 to the profile variance.
    assert width(split) - width(still) == pytest.approx(shift**2, rel=0.1)


def test_subsamples_need_an_exposure_and_a_capable_wfs() -> None:
    config = _config(n_steps=2)
    system = scao.build_scao_system(config)
    with pytest.raises(ControlLoopError, match="exposure_s"):
        _loop(system, config, exposure_subsamples=2)
    with pytest.raises(ControlLoopError, match="frame period"):
        _loop(system, config, exposure_subsamples=2, exposure_s=2.0e-3)


# -- GPT pre-refactor audit F-02 (2026-10-18): the effective quadrature is identity --

# A single-sample run must keep exactly the identity it had before the change
# (2312502): the run payload without any exposure entry.  Its digest binds
# numerically computed inputs (probe influences, calibration products) whose
# last bits differ between CPUs and NumPy builds, so pinning one host's value
# (02cc0257... on the producing macOS arm64 machine) fails on every CI runner.
# The test rebuilds that pre-change payload from the run's own record instead.
def _pre_change_identity(history) -> str:
    from shwfs_ao.core.hashing import component_config_hash

    metadata = history.metadata
    return component_config_hash(
        "control.closed_loop_run",
        {
            "component_hashes": metadata["component_hashes"],
            "random_derivation_scheme_id": metadata["random_derivation_scheme_id"],
            "random_stream_ids": metadata["random_stream_ids"],
            "include_noise": metadata["include_noise"],
            "realization_index": metadata["realization_index"],
            "residual_sign_convention": metadata["residual_sign_convention"],
            "command_sign_convention": metadata["command_sign_convention"],
            "frame_sequence": "shwfs_ao.control.run_closed_loop.v1",
        },
    )


def _DeclaredExposureWfs(wfs, configured):
    """A shallow copy of the system's WFS that reports another configured count."""

    import copy

    class Declared(type(wfs)):  # type: ignore[misc, valid-type]
        @property
        def exposure_subsamples(self):
            return configured

    clone = copy.copy(wfs)
    clone.__class__ = Declared
    return clone


def test_the_effective_quadrature_is_part_of_the_run_identity() -> None:
    import json

    config = _config(n_steps=3)
    system = scao.build_scao_system(config)
    single = [_loop(system, config), _loop(system, config, exposure_subsamples=1, exposure_s=1.0e-3),
              _loop(system, config, exposure_subsamples=1, exposure_s=5.0e-4)]
    # exposure_s has no effect on one sample, so it changes nothing.
    single_hash = _pre_change_identity(single[0])
    assert {history.config_hash for history in single} == {single_hash}
    assert all(_pre_change_identity(history) == single_hash for history in single)
    assert all("wfs_exposure" not in history.metadata for history in single)
    multi = {
        (2, 1.0e-3): _loop(system, config, exposure_subsamples=2, exposure_s=1.0e-3),
        (2, 5.0e-4): _loop(system, config, exposure_subsamples=2, exposure_s=5.0e-4),
        (4, 1.0e-3): _loop(system, config, exposure_subsamples=4, exposure_s=1.0e-3),
    }
    hashes = {key: history.config_hash for key, history in multi.items()}
    assert len(set(hashes.values()) | {single_hash}) == 4
    # A multi-sample run leaves the pre-change form: its quadrature enters.
    assert all(history.config_hash != _pre_change_identity(history) for history in multi.values())
    assert _loop(system, config, exposure_subsamples=2, exposure_s=1.0e-3).config_hash == hashes[(2, 1.0e-3)]
    for (count, duration), history in multi.items():
        record = dict(history.metadata["wfs_exposure"])
        assert record == {
            "scheme": "left_point_uniform_held_dm.v1", "subsamples": count, "duration_s": duration,
            "source": "run_closed_loop arguments", "wfs_configured_subsamples": 1,
        }
        assert json.loads(json.dumps(record)) == record  # survives serialization


def test_an_override_of_the_configured_exposure_is_recorded() -> None:
    config = _config(n_steps=3)
    system = scao.build_scao_system(config)
    # A WFS configured for two samples, run on one: the effective single
    # sample keeps the single-sample identity, and the metadata says so.
    declared = _loop(system, config, atmosphere=None, wfs=_DeclaredExposureWfs(system.wfs, 2))
    single_hash = _loop(system, config).config_hash
    assert declared.config_hash == single_hash == _pre_change_identity(declared)
    assert dict(declared.metadata["wfs_exposure"]) == {
        "scheme": "single_sample_at_frame_time.v1", "subsamples": 1, "duration_s": None,
        "source": "run_closed_loop arguments", "wfs_configured_subsamples": 2,
    }
    # Any integer type is a count (recorded as an int); other types are not.
    numpy_count = _loop(system, config, atmosphere=None, wfs=_DeclaredExposureWfs(system.wfs, np.int64(2)))
    assert numpy_count.config_hash == single_hash
    assert dict(numpy_count.metadata["wfs_exposure"]) == dict(declared.metadata["wfs_exposure"])
    assert type(numpy_count.metadata["wfs_exposure"]["wfs_configured_subsamples"]) is int
    for invalid in (0, np.int64(0), True, np.True_, 2.0):
        with pytest.raises(ControlLoopError, match="positive integer"):
            _loop(system, config, wfs=_DeclaredExposureWfs(system.wfs, invalid))


def test_a_profile_quadrature_reaches_the_run_identity() -> None:
    from shwfs_ao.experiments.detector_level import with_physics

    config = with_physics(_config(n_steps=3), exposure_subsamples=2)
    history = scao.run_closed_loop(config)
    assert dict(history.metadata["wfs_exposure"]) == {
        "scheme": "left_point_uniform_held_dm.v1", "subsamples": 2,
        "duration_s": float(config.detector.exposure_s),
        "source": "run_closed_loop arguments", "wfs_configured_subsamples": 2,
    }


# -- T2 G2 (2026-10-21): the midpoint exposure rule ---------------------------------

import math  # noqa: E402
from typing import Any  # noqa: E402

from shwfs_ao.backends.native.atmosphere import StaticOpdAtmosphere  # noqa: E402
from shwfs_ao.control.loop import EXPOSURE_SAMPLE_RULES  # noqa: E402
from shwfs_ao.core.hashing import component_config_hash  # noqa: E402
from shwfs_ao.experiments._component_configs import (  # noqa: E402
    ExposureOverride,
    ExposureOverrideError,
    exposure_keywords,
)

TAU = 1.0e-3  # the 2 m profile's exposure and frame period


class _DriftingTilt:
    """A tilt growing linearly in time, ``OPD = slope * t * x``: an ``AtmosphereModel`` fixture."""

    backend_name = "test-drifting-tilt"

    def __init__(self, geometry: Any, slope_per_s: float) -> None:
        self._x = np.asarray(geometry.x_m, dtype=float)
        self._mask = np.asarray(geometry.pupil_mask, dtype=bool)
        self._slope = float(slope_per_s)
        self.times: list[float] = []
        self.config_hash = component_config_hash("test.drifting_tilt", {"slope_per_s": self._slope})
        self.metadata = {"realization_invariant": True}

    def reset(self, *, realization_index: int = 0) -> None:
        self.times.clear()

    def tilt(self, time_s: float) -> np.ndarray:
        opd = self._slope * float(time_s) * self._x
        opd = opd - np.mean(opd[self._mask])
        opd[~self._mask] = np.nan
        return opd

    def opd_at(self, time_s: float) -> np.ndarray:
        self.times.append(float(time_s))
        return self.tilt(time_s)


class _RecordingWfs:
    """Pass-through sensor wrapper that records every measurement call."""

    def __init__(self, wfs: Any) -> None:
        self._wfs = wfs
        self.calls: list[tuple[str, list[np.ndarray], Any]] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wfs, name)

    @property
    def config_hash(self) -> str:
        return self._wfs.config_hash

    @property
    def row_ids(self) -> tuple[str, ...]:
        return tuple(self._wfs.row_ids)

    def measure(self, residual_opd_m, *, random_streams, include_noise):
        result = self._wfs.measure(residual_opd_m, random_streams=random_streams, include_noise=include_noise)
        self.calls.append(("measure", [np.array(residual_opd_m)], result))
        return result

    def measure_exposure(self, residual_opd_samples, *, random_streams, include_noise):
        samples = [np.array(sample) for sample in residual_opd_samples]
        result = self._wfs.measure_exposure(samples, random_streams=random_streams, include_noise=include_noise)
        self.calls.append(("measure_exposure", samples, result))
        return result


class _NoExposureWfs(_RecordingWfs):
    """A sensor without ``measure_exposure`` (the geometric sensors' situation)."""

    def __getattr__(self, name: str) -> Any:
        if name == "measure_exposure":
            raise AttributeError(name)
        return getattr(self._wfs, name)

    measure_exposure = property(lambda self: (_ for _ in ()).throw(AttributeError("measure_exposure")))  # type: ignore[assignment]


def _mean_x_centroid(measurement) -> float:
    values = np.asarray(measurement.vector.values, dtype=float)
    valid = np.asarray(measurement.vector.valid_rows, dtype=bool)
    return float(np.mean(values[0::2][valid[0::2]]))


def test_midpoint_samples_lie_at_the_sub_interval_centres_after_the_frame_start_sample(monkeypatch) -> None:
    config = _config(n_steps=3)
    system = scao.build_scao_system(config)
    times = _count_calls(monkeypatch, system.atmosphere)
    period = 1.0 / config.controller.frame_rate_hz
    for count in (1, 2, 4):
        times.clear()
        _loop(system, config, exposure_subsamples=count, exposure_s=TAU, exposure_sample_rule="midpoint")
        expected = [
            k * period + offset
            for k in range(3)
            for offset in [0.0, *((j + 0.5) * TAU / count for j in range(count))]
        ]
        assert np.allclose(times, expected, rtol=0.0, atol=1.0e-15), count
        assert all(later >= earlier for earlier, later in zip(times, times[1:]))  # never retreats
    # The legacy rule is untouched: n = 1 makes one call at t, n = 2 adds t + tau/2.
    times.clear()
    _loop(system, config, exposure_subsamples=2, exposure_s=TAU, exposure_sample_rule="left_point")
    assert np.allclose(times, [k * period + j * TAU / 2 for k in range(3) for j in range(2)], rtol=0.0, atol=1.0e-15)
    assert EXPOSURE_SAMPLE_RULES == ("left_point", "midpoint")


def test_for_a_linear_drift_the_midpoint_rule_leads_the_left_rule_by_half_a_sub_interval() -> None:
    """K1: left mean ``t + tau (n-1)/(2n)``, midpoint mean ``t + tau/2``; the gap is ``v tau / (2n)``, ``n = 1`` included."""

    config = _config(n_steps=2)
    system = scao.build_scao_system(config)
    drift = _DriftingTilt(system.wfs.geometry, slope_per_s=1.0e-7 / TAU)  # one 1e-7 m/m tilt per exposure
    streams = system.random_streams

    def centroid_at(time_s: float) -> float:
        sample = np.nan_to_num(drift.tilt(time_s))
        return _mean_x_centroid(system.wfs.measure(sample, random_streams=streams, include_noise=False))

    gain = (centroid_at(TAU) - centroid_at(0.0)) / (1.0e-7)  # px per (m of OPD per m)
    assert abs(gain) > 1.0e4
    for count in (1, 2, 4):
        left_times = [j * TAU / count for j in range(count)]
        mid_times = [(j + 0.5) * TAU / count for j in range(count)]
        left = _mean_x_centroid(
            system.wfs.measure_exposure([np.nan_to_num(drift.tilt(t)) for t in left_times], random_streams=streams, include_noise=False)
        )
        mid = _mean_x_centroid(
            system.wfs.measure_exposure([np.nan_to_num(drift.tilt(t)) for t in mid_times], random_streams=streams, include_noise=False)
        )
        # The centre of gravity is linear in the averaged image, so the exposure
        # centroid is the flux-weighted mean of the sample centroids; the window
        # capture moves by about 1e-5 with the tilt, hence the tolerance.
        assert left == pytest.approx(np.mean([centroid_at(t) for t in left_times]), rel=1.0e-4)
        assert mid == pytest.approx(np.mean([centroid_at(t) for t in mid_times]), rel=1.0e-4)
        slope_px_per_s = gain * drift._slope
        assert (mid - left) == pytest.approx(slope_px_per_s * TAU / (2 * count), rel=2.0e-2), count
        assert left - centroid_at(0.0) == pytest.approx(slope_px_per_s * TAU * (count - 1) / (2 * count), rel=2.0e-2, abs=1.0e-9)
        assert mid - centroid_at(0.0) == pytest.approx(slope_px_per_s * TAU / 2, rel=2.0e-2)


def test_the_loop_hands_each_rule_s_samples_to_one_exposure_measurement_per_frame() -> None:
    config = _config(n_steps=2)
    system = scao.build_scao_system(config)
    period = 1.0 / config.controller.frame_rate_hz
    for rule, count, offsets in (
        ("midpoint", 1, [0.5 * TAU]),
        ("midpoint", 2, [0.25 * TAU, 0.75 * TAU]),
        ("left_point", 2, [0.0, 0.5 * TAU]),
    ):
        drift = _DriftingTilt(system.wfs.geometry, slope_per_s=1.0e-7 / TAU)
        recording = _RecordingWfs(system.wfs)
        _loop(system, config, atmosphere=drift, wfs=recording, exposure_subsamples=count, exposure_s=TAU, exposure_sample_rule=rule)
        assert [name for name, _, _ in recording.calls] == ["measure_exposure"] * config.controller.n_steps
        for frame, (_, samples, _) in enumerate(recording.calls):
            assert len(samples) == count
            # Each sample is the residual at its own time (the DM is held), so the
            # pupil mean slope of sample j minus sample 0 is the drift between their times.
            mask = np.asarray(system.wfs.geometry.pupil_mask, dtype=bool)
            x = np.asarray(system.wfs.geometry.x_m, dtype=float)[mask]
            for j, sample in enumerate(samples):
                difference = (np.asarray(sample)[mask] - np.asarray(samples[0])[mask])
                slope = float(np.polyfit(x, difference, 1)[0])
                assert slope == pytest.approx(drift._slope * (offsets[j] - offsets[0]), abs=1.0e-15)
        # The frame-start sample is taken first for every frame.
        starts = [t for t in drift.times if any(abs(t - k * period) < 1.0e-15 for k in range(config.controller.n_steps))]
        assert len(starts) == config.controller.n_steps


def test_camera_noise_is_applied_once_per_midpoint_frame() -> None:
    config = _config(n_steps=1)
    system = scao.build_scao_system(config)
    recording = _RecordingWfs(system.wfs)
    _loop(system, config, wfs=recording, exposure_subsamples=2, exposure_s=TAU, exposure_sample_rule="midpoint")
    (name, samples, measurement), = recording.calls
    assert name == "measure_exposure" and len(samples) == 2
    fresh = scao.build_scao_system(config)
    replay = fresh.wfs.measure_exposure(samples, random_streams=fresh.random_streams, include_noise=True)
    np.testing.assert_array_equal(replay.vector.values, measurement.vector.values)
    assert measurement.detector_telemetry is not None


def test_a_static_atmosphere_gives_the_same_frames_for_either_rule_and_any_count() -> None:
    config = _config(n_steps=3)
    config = replace(config, controller=replace(config.controller, include_noise=False))
    system = scao.build_scao_system(config)
    opd = np.asarray(system.atmosphere.opd_at(0.0), dtype=float)
    static = StaticOpdAtmosphere(np.where(np.isfinite(opd), 0.3 * opd, 0.0), np.isfinite(opd), root_seed=config.random.root_seed)
    reference = _loop(system, config, atmosphere=static)
    for rule, count in (("left_point", 3), ("midpoint", 1), ("midpoint", 3)):
        history = _loop(system, config, atmosphere=static, exposure_subsamples=count, exposure_s=TAU, exposure_sample_rule=rule)
        np.testing.assert_allclose(history.post_update_residual_opd_rms_m, reference.post_update_residual_opd_rms_m, rtol=1.0e-12, atol=0.0)
        np.testing.assert_allclose(history.applied_command_history_opd_m, reference.applied_command_history_opd_m, rtol=1.0e-12, atol=1.0e-18)


def test_the_midpoint_rule_validates_its_duration_rule_and_sensor() -> None:
    config = _config(n_steps=2)
    system = scao.build_scao_system(config)
    with pytest.raises(ControlLoopError, match="exposure_s"):
        _loop(system, config, exposure_subsamples=1, exposure_sample_rule="midpoint")
    with pytest.raises(ControlLoopError, match="frame period"):
        _loop(system, config, exposure_subsamples=1, exposure_s=2.0e-3, exposure_sample_rule="midpoint")
    with pytest.raises(ControlLoopError, match="exposure_s"):
        _loop(system, config, exposure_subsamples=1, exposure_s=math.inf, exposure_sample_rule="midpoint")
    with pytest.raises(ControlLoopError, match="exposure_sample_rule"):
        _loop(system, config, exposure_subsamples=1, exposure_s=TAU, exposure_sample_rule="centred")
    with pytest.raises(ControlLoopError, match="exposure_sample_rule"):
        _loop(system, config, exposure_subsamples=1, exposure_s=TAU, exposure_sample_rule=None)
    with pytest.raises(ControlLoopError, match="measure_exposure"):
        _loop(system, config, wfs=_NoExposureWfs(system.wfs), exposure_subsamples=1, exposure_s=TAU, exposure_sample_rule="midpoint")
    # The frame-start single sample needs none of it.
    _loop(system, config, wfs=_NoExposureWfs(system.wfs))


def test_midpoint_runs_carry_their_own_identity_and_labelled_metadata() -> None:
    import json

    config = _config(n_steps=3)
    system = scao.build_scao_system(config)
    default = _loop(system, config)
    left_two = _loop(system, config, exposure_subsamples=2, exposure_s=TAU)
    mid_one = _loop(system, config, exposure_subsamples=1, exposure_s=TAU, exposure_sample_rule="midpoint")
    mid_two = _loop(system, config, exposure_subsamples=2, exposure_s=TAU, exposure_sample_rule="midpoint")
    hashes = [history.config_hash for history in (default, left_two, mid_one, mid_two)]
    assert len(set(hashes)) == 4
    assert _loop(system, config, exposure_subsamples=1, exposure_s=TAU, exposure_sample_rule="midpoint").config_hash == mid_one.config_hash
    # The explicit left-point rule is the default: same identity and no metadata entry.
    assert _loop(system, config, exposure_sample_rule="left_point").config_hash == default.config_hash
    assert "wfs_exposure" not in _loop(system, config, exposure_sample_rule="left_point").metadata
    # Left-point payloads stay exactly the legacy ones (witnessed), midpoint ones are labelled.
    assert dict(left_two.metadata["wfs_exposure"]) == {
        "scheme": "left_point_uniform_held_dm.v1", "subsamples": 2, "duration_s": TAU,
        "source": "run_closed_loop arguments", "wfs_configured_subsamples": 1,
    }
    for count, history in ((1, mid_one), (2, mid_two)):
        record = dict(history.metadata["wfs_exposure"])
        assert record["scheme"] == "midpoint_uniform_held_dm.v1"
        assert record["sample_rule"] == "midpoint" and record["subsamples"] == count
        assert record["duration_s"] == TAU and record["wfs_configured_subsamples"] == 1
        assert record["sample_time_offsets_s"] == tuple((j + 0.5) * TAU / count for j in range(count))
        assert record["mean_sample_time_offset_s"] == 0.5 * TAU
        assert record["residual_metric_time"] == "frame_start"
        assert json.loads(json.dumps(record))["sample_time_offsets_s"] == list(record["sample_time_offsets_s"])
    # The midpoint identity is the legacy payload plus the midpoint quadrature entry.
    metadata = mid_one.metadata
    expected = component_config_hash(
        "control.closed_loop_run",
        {
            "component_hashes": metadata["component_hashes"],
            "random_derivation_scheme_id": metadata["random_derivation_scheme_id"],
            "random_stream_ids": metadata["random_stream_ids"],
            "include_noise": metadata["include_noise"],
            "realization_index": metadata["realization_index"],
            "residual_sign_convention": metadata["residual_sign_convention"],
            "command_sign_convention": metadata["command_sign_convention"],
            "frame_sequence": "shwfs_ao.control.run_closed_loop.v1",
            "wfs_exposure": {"scheme": "midpoint_uniform_held_dm.v1", "subsamples": 1, "duration_s": TAU, "sample_rule": "midpoint"},
        },
    )
    assert mid_one.config_hash == expected
    # Frame-start metrics do not move with the sample rule (same atmosphere sample at t).
    np.testing.assert_array_equal(mid_one.open_loop_opd_rms_m, default.open_loop_opd_rms_m)


def test_exposure_overrides_reach_the_loop_through_the_experiment_boundaries() -> None:
    from shwfs_ao.experiments.detector_level import with_physics

    config = _config(n_steps=3)
    assert exposure_keywords(config) == {}
    assert exposure_keywords(with_physics(config, exposure_subsamples=2)) == {"exposure_subsamples": 2, "exposure_s": TAU}
    assert exposure_keywords(config, ExposureOverride()) == {}
    assert exposure_keywords(config, ExposureOverride(sample_rule="left_point", subsamples=1)) == {}
    assert exposure_keywords(config, ExposureOverride(subsamples=2)) == {"exposure_subsamples": 2, "exposure_s": TAU}
    assert exposure_keywords(config, ExposureOverride(sample_rule="midpoint")) == {
        "exposure_subsamples": 1, "exposure_s": TAU, "exposure_sample_rule": "midpoint",
    }
    assert exposure_keywords(with_physics(config, exposure_subsamples=4), ExposureOverride(subsamples=2, sample_rule="midpoint")) == {
        "exposure_subsamples": 2, "exposure_s": TAU, "exposure_sample_rule": "midpoint",
    }
    assert ExposureOverride().is_default and not ExposureOverride(sample_rule="midpoint").is_default
    for invalid in ({"subsamples": 0}, {"subsamples": True}, {"subsamples": 2.0}, {"sample_rule": "centred"}, {"sample_rule": 1}):
        with pytest.raises(ExposureOverrideError):
            ExposureOverride(**invalid)
    with pytest.raises(ExposureOverrideError):
        exposure_keywords(config, {"sample_rule": "midpoint"})  # type: ignore[arg-type]
    history = scao.run_closed_loop(config, exposure=ExposureOverride(sample_rule="midpoint", subsamples=2))
    record = dict(history.metadata["wfs_exposure"])
    assert record["scheme"] == "midpoint_uniform_held_dm.v1" and record["subsamples"] == 2
    assert record["wfs_configured_subsamples"] == 1 and record["sample_rule"] == "midpoint"
    assert scao.run_closed_loop(config, exposure=ExposureOverride()).config_hash == scao.run_closed_loop(config).config_hash
