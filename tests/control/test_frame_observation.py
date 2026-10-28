"""ESO-02: passive frame observation of the canonical loop.

The event maps are checked against a hand-written recursion of the controller
equation, independent of ``run_closed_loop``: with a static atmosphere ``v``
on a two-sample pupil ``[[v, -v]]``, a 1:1 WFS/reconstructor and a one-actuator
DM ``[[c, -c]]``, the requested command of frame ``k`` is
``(1 - leak) * applied[k-1] + gain * delta[k - latency]`` with
``delta[j] = pre_residual[j]`` (or 0 when frame ``j`` fails closed), and the
applied command is that request clipped to the stroke.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType

import numpy as np
import pytest

from shwfs_ao.calibration import InteractionMatrix, calibrate_interaction_matrix
from shwfs_ao.control import (
    OBSERVABLE_FIELDS,
    FrameObservation,
    FrameObservationError,
    FrameObserver,
)
from shwfs_ao.control.command_mapping import IdentityCommandProjector
from shwfs_ao.control.config import LoopConfig
from shwfs_ao.control.controller import LeakyIntegratorController
from shwfs_ao.control.loop import ControlLoopError, run_closed_loop
from shwfs_ao.core.random import NamedRandomStreams
from shwfs_ao.core.types import (
    DmCommandVector,
    DmSynthesisResult,
    MeasurementVector,
    ReconstructionEstimate,
    WfsMeasurement,
)
from shwfs_ao.experiments import scao
from shwfs_ao.io.configs import load_system_profile


ACTUATOR_IDS = ("A0",)
ROW_IDS = ("R0", "R1")


class _ProbeBasis:
    size = 1
    coordinate_ids = ACTUATOR_IDS
    coordinate_kind = "dm_command_opd"
    coordinate_unit = "m_opd_equivalent"
    max_abs_amplitude_m = np.asarray([np.inf])
    config_hash = "observation-probe-v1"
    dm_hash = "observation-dm"

    def opd_m_for_coordinate(self, index: int, amplitude_m: float) -> np.ndarray:
        return np.asarray([[amplitude_m, -amplitude_m]], dtype=float)


class _Wfs:
    config_hash = "observation-wfs"
    row_ids = ROW_IDS

    def measure(self, residual_opd_m, *, random_streams, include_noise):
        value = float(np.asarray(residual_opd_m)[0, 0])
        return WfsMeasurement(
            vector=MeasurementVector(
                values=np.asarray([value, 2.0 * value]),
                valid_rows=np.asarray([True, True]),
                row_ids=ROW_IDS,
                measurement_unit="pixel",
            ),
            valid_subapertures=np.asarray([True]),
        )


@pytest.fixture(scope="module")
def matrix() -> InteractionMatrix:
    return calibrate_interaction_matrix(
        _ProbeBasis(), _Wfs(), 1.0e-9, random_streams=NamedRandomStreams(3)
    )


class _Atmosphere:
    backend_name = "observation-atmosphere"
    config_hash = "observation-atmosphere"

    def __init__(self, value_m: float) -> None:
        self.value_m = value_m
        self.times: list[float] = []

    @property
    def metadata(self) -> Mapping[str, object]:
        return MappingProxyType({"backend_name": self.backend_name})

    def reset(self, *, realization_index: int = 0) -> None:
        self.times.clear()

    def opd_at(self, time_s: float) -> np.ndarray:
        self.times.append(float(time_s))
        return np.asarray([[self.value_m, -self.value_m]], dtype=float)


class _Reconstructor:
    config_hash = "observation-reconstructor"

    def __init__(self, matrix: InteractionMatrix, none_frames: frozenset[int]) -> None:
        self.matrix = matrix
        self.none_frames = none_frames
        self.calls = 0

    @property
    def matrix_hash(self) -> str:
        return self.matrix.calibration_hash

    def reconstruct(self, measurement: MeasurementVector):
        index = self.calls
        self.calls += 1
        if index in self.none_frames:
            return None
        usable = np.asarray(measurement.valid_rows, dtype=bool)
        return ReconstructionEstimate(
            delta_coordinates_opd_m=np.asarray([measurement.values[0]]),
            coordinate_ids=ACTUATOR_IDS,
            coordinate_kind="dm_command_opd",
            coordinate_unit="m_opd_equivalent",
            measurement_unit="pixel",
            usable_rows=usable,
            reconstructed_signal=np.asarray(measurement.values, dtype=float),
            residual_signal=np.zeros(2),
            coordinate_norm_m=abs(float(measurement.values[0])),
            residual_norm=0.0,
            kept_modes=1,
            singular_values=np.asarray([1.0]),
            matrix_hash=self.matrix_hash,
        )


class _Dm:
    backend_name = "observation-dm"
    config_hash = "observation-dm"
    actuator_ids = ACTUATOR_IDS
    controllable_actuator_ids = ACTUATOR_IDS
    n_actuators = 1

    def __init__(self, stroke_m: float) -> None:
        self.stroke_m = stroke_m

    def opd_from_commands(self, commands: DmCommandVector) -> DmSynthesisResult:
        requested = np.asarray(commands.values_opd_m, dtype=float)
        applied = np.clip(requested, -self.stroke_m, self.stroke_m)
        saturated = np.abs(requested) > self.stroke_m
        return DmSynthesisResult(
            correction_opd_m=np.asarray([[applied[0], -applied[0]]]),
            requested_commands_opd_m=requested,
            applied_commands_opd_m=applied,
            actuator_ids=ACTUATOR_IDS,
            saturated_mask=saturated,
            saturation_fraction=float(np.mean(saturated)),
            command_unit="m_opd_equivalent",
            config_hash=self.config_hash,
        )


class _Recorder:
    def __init__(self, fields=frozenset(OBSERVABLE_FIELDS)) -> None:
        self.requested_fields = frozenset(fields)
        self.events: list[FrameObservation] = []
        self.copies: list[dict[str, np.ndarray]] = []

    def observe(self, observation: FrameObservation) -> None:
        self.events.append(observation)
        self.copies.append(
            {
                name: np.array(getattr(observation, name), copy=True)
                for name in OBSERVABLE_FIELDS
                if getattr(observation, name) is not None
            }
        )


def _run(matrix, *, latency, gain, leak, stroke, none_frames, n_steps, observers=()):
    config = LoopConfig(
        n_steps=n_steps,
        gain=gain,
        leak=leak,
        latency_frames=latency,
        frame_rate_hz=500.0,
        root_seed=7,
    )
    atmosphere = _Atmosphere(4.0e-9)
    history = run_closed_loop(
        config,
        random_streams=NamedRandomStreams(7),
        atmosphere=atmosphere,
        wfs=_Wfs(),
        dm=_Dm(stroke),
        interaction_matrix=matrix,
        reconstructor=_Reconstructor(matrix, none_frames),
        command_projector=IdentityCommandProjector(ACTUATOR_IDS),
        controller=LeakyIntegratorController(
            ACTUATOR_IDS, gain=gain, leak=leak, latency_frames=latency
        ),
        include_noise=False,
        observers=observers,
    )
    return history, atmosphere


def _hand_recursion(*, value, latency, gain, leak, stroke, none_frames, n_steps):
    """Independent recursion of the controller and DM equations."""

    applied = 0.0
    deltas: list[float] = []
    pre, post, requested_out = [], [], []
    for frame in range(n_steps):
        pre_residual = value - applied
        deltas.append(0.0 if frame in none_frames else pre_residual)
        released = deltas[frame - latency] if frame >= latency else 0.0
        requested = (1.0 - leak) * applied + gain * released
        applied = min(max(requested, -stroke), stroke)
        pre.append(pre_residual)
        post.append(value - applied)
        requested_out.append(requested)
    return np.asarray(pre), np.asarray(post), np.asarray(requested_out)


@pytest.mark.parametrize(
    ("latency", "gain", "leak", "stroke", "none_frames"),
    (
        (2, 0.5, 0.0, 1.0, frozenset()),
        (1, 0.6, 0.05, 1.0, frozenset({1, 4})),
        # Stroke smaller than the atmosphere: the applied command saturates and
        # the post-update map must use the clipped command, not the request.
        (1, 0.9, 0.0, 2.5e-9, frozenset()),
        (0, 1.0, 0.0, 1.0, frozenset({0})),
    ),
)
def test_event_maps_match_a_hand_recursion_with_latency_faults_and_dropouts(
    matrix, latency, gain, leak, stroke, none_frames
):
    recorder = _Recorder()
    n_steps = 7
    history, _ = _run(
        matrix,
        latency=latency,
        gain=gain,
        leak=leak,
        stroke=stroke,
        none_frames=none_frames,
        n_steps=n_steps,
        observers=(recorder,),
    )
    pre, post, requested = _hand_recursion(
        value=4.0e-9,
        latency=latency,
        gain=gain,
        leak=leak,
        stroke=stroke,
        none_frames=none_frames,
        n_steps=n_steps,
    )
    assert [event.frame_index for event in recorder.events] == list(range(n_steps))
    for frame, event in enumerate(recorder.events):
        assert event.time_s == frame / 500.0
        assert event.frame_period_s == 1.0 / 500.0
        assert event.latency_frames == latency
        assert event.reconstruction_usable == (frame not in none_frames)
        np.testing.assert_allclose(
            event.atmosphere_opd_m, [[4.0e-9, -4.0e-9]], rtol=0.0, atol=1.0e-24
        )
        np.testing.assert_allclose(
            event.pre_update_residual_opd_m,
            [[pre[frame], -pre[frame]]],
            rtol=1.0e-12,
            atol=1.0e-24,
        )
        np.testing.assert_allclose(
            event.post_update_residual_opd_m,
            [[post[frame], -post[frame]]],
            rtol=1.0e-12,
            atol=1.0e-24,
        )
    np.testing.assert_allclose(
        history.requested_command_history_opd_m[:, 0], requested, rtol=1e-12, atol=1e-24
    )
    if stroke < 4.0e-9:
        saturated = [event.saturation_fraction for event in recorder.events]
        assert max(saturated) == 1.0


def test_latency_two_correction_is_first_seen_three_frames_after_its_measurement(
    matrix,
):
    """The documented delay mapping: L = 2 gives a three-interval delay."""

    recorder = _Recorder()
    _run(
        matrix,
        latency=2,
        gain=1.0,
        leak=0.0,
        stroke=1.0,
        none_frames=frozenset(),
        n_steps=5,
        observers=(recorder,),
    )
    pre = [event.pre_update_residual_opd_m[0, 0] for event in recorder.events]
    # Frame 0's measurement is applied in frame 2's update and is first seen by
    # the WFS in frame 3.
    assert pre[:3] == [4.0e-9, 4.0e-9, 4.0e-9]
    assert pre[3] == pytest.approx(0.0, abs=1e-24)


def test_disabled_and_no_op_observation_are_identical(matrix):
    baseline, atmosphere_a = _run(
        matrix, latency=2, gain=0.5, leak=0.01, stroke=1.0,
        none_frames=frozenset({3}), n_steps=9,
    )
    recorder = _Recorder()
    observed, atmosphere_b = _run(
        matrix, latency=2, gain=0.5, leak=0.01, stroke=1.0,
        none_frames=frozenset({3}), n_steps=9, observers=(recorder, _Recorder()),
    )
    assert observed.config_hash == baseline.config_hash
    assert atmosphere_a.times == atmosphere_b.times
    assert len(atmosphere_b.times) == 9
    for name in (
        "pre_update_residual_opd_rms_m",
        "post_update_residual_opd_rms_m",
        "requested_command_history_opd_m",
        "applied_command_history_opd_m",
        "measurement_row_masks",
        "reconstruction_usable",
    ):
        np.testing.assert_array_equal(getattr(observed, name), getattr(baseline, name))
    assert dict(observed.metadata["random_stream_ids"]) == dict(
        baseline.metadata["random_stream_ids"]
    )


def test_snapshots_are_immutable_and_retained_events_never_change(matrix):
    class _Tamperer(_Recorder):
        def observe(self, observation):
            super().observe(observation)
            snapshot = observation.pre_update_residual_opd_m
            with pytest.raises(ValueError):
                snapshot[0, 0] = 1.0
            with pytest.raises(ValueError):
                snapshot.flags.writeable = True
            with pytest.raises(AttributeError):
                observation.frame_index = 99  # type: ignore[misc]

    tamperer = _Tamperer()
    baseline, _ = _run(
        matrix, latency=1, gain=0.5, leak=0.0, stroke=1.0,
        none_frames=frozenset(), n_steps=6,
    )
    observed, _ = _run(
        matrix, latency=1, gain=0.5, leak=0.0, stroke=1.0,
        none_frames=frozenset(), n_steps=6, observers=(tamperer,),
    )
    np.testing.assert_array_equal(
        observed.post_update_residual_opd_rms_m, baseline.post_update_residual_opd_rms_m
    )
    for event, copy in zip(tamperer.events, tamperer.copies, strict=True):
        for name, values in copy.items():
            np.testing.assert_array_equal(getattr(event, name), values)
    assert len({id(event.pre_update_residual_opd_m) for event in tamperer.events}) == 6


def test_only_requested_fields_are_materialized(matrix):
    pre_only = _Recorder(frozenset({"pre_update_residual_opd_m"}))
    _run(
        matrix, latency=0, gain=0.5, leak=0.0, stroke=1.0,
        none_frames=frozenset(), n_steps=3, observers=(pre_only,),
    )
    for event in pre_only.events:
        assert event.pre_update_residual_opd_m is not None
        assert event.atmosphere_opd_m is None
        assert event.post_update_residual_opd_m is None


def test_observer_failures_carry_frame_context(matrix):
    class _Failing(_Recorder):
        def observe(self, observation):
            if observation.frame_index == 2:
                raise RuntimeError("boom")

    with pytest.raises(ControlLoopError, match=r"failed at frame 2 \(t = 0\.004 s\): boom"):
        _run(
            matrix, latency=0, gain=0.5, leak=0.0, stroke=1.0,
            none_frames=frozenset(), n_steps=4, observers=(_Failing(),),
        )


@pytest.mark.parametrize(
    "observers",
    (
        (object(),),
        "not-a-sequence",
        (_Recorder(frozenset({"atmosphere_opd_m", "live_dm_handle"})),),
    ),
)
def test_invalid_observers_are_rejected_before_any_frame(matrix, observers):
    atmosphere_calls: list[float] = []
    with pytest.raises(ControlLoopError):
        history, atmosphere = _run(
            matrix, latency=0, gain=0.5, leak=0.0, stroke=1.0,
            none_frames=frozenset(), n_steps=2, observers=observers,
        )
        atmosphere_calls.extend(atmosphere.times)
    assert not atmosphere_calls


def test_frame_observation_rejects_writable_or_mismatched_maps():
    writable = np.zeros((2, 2))
    with pytest.raises(FrameObservationError, match="read-only"):
        FrameObservation(
            frame_index=0, time_s=0.0, frame_period_s=0.002, latency_frames=0,
            reconstruction_usable=True, saturation_fraction=0.0,
            atmosphere_opd_m=writable,
        )
    a = np.frombuffer(np.zeros(4).tobytes()).reshape(2, 2)
    b = np.frombuffer(np.zeros(6).tobytes()).reshape(2, 3)
    with pytest.raises(FrameObservationError, match="one shape"):
        FrameObservation(
            frame_index=0, time_s=0.0, frame_period_s=0.002, latency_frames=0,
            reconstruction_usable=True, saturation_fraction=0.0,
            atmosphere_opd_m=a, post_update_residual_opd_m=b,
        )
    assert isinstance(_Recorder(), FrameObserver)


def test_canonical_scao_runner_forwards_observers_without_changing_control():
    config = load_system_profile("eso_turbulence_2m_detector", 1)
    config = replace(config, controller=replace(config.controller, n_steps=12))
    system = scao.build_scao_system(config)
    baseline = scao.run_closed_loop(config, system=system)
    recorder = _Recorder()
    observed = scao.run_closed_loop(config, system=system, observers=(recorder,))
    assert observed.config_hash == baseline.config_hash
    np.testing.assert_array_equal(
        observed.applied_command_history_opd_m, baseline.applied_command_history_opd_m
    )
    np.testing.assert_array_equal(
        observed.post_update_residual_opd_rms_m, baseline.post_update_residual_opd_rms_m
    )
    assert len(recorder.events) == 12
    pupil = np.isfinite(recorder.events[0].atmosphere_opd_m)
    for frame, event in enumerate(recorder.events):
        residual = event.pre_update_residual_opd_m[pupil]
        rms = float(np.sqrt(np.mean((residual - residual.mean()) ** 2)))
        assert rms == pytest.approx(baseline.pre_update_residual_opd_rms_m[frame], rel=1e-12)
