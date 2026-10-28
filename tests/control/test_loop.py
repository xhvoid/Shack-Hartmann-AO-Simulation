"""Backend-independent AO-REF-009 loop ordering, masking, and replay tests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType

import numpy as np
import pytest

from shwfs_ao.calibration import InteractionMatrix, calibrate_interaction_matrix
from shwfs_ao.control.command_mapping import IdentityCommandProjector
from shwfs_ao.control.config import LoopConfig
from shwfs_ao.control.controller import LeakyIntegratorController
from shwfs_ao.control.loop import ControlLoopError, run_closed_loop
from shwfs_ao.core.protocols import (
    AtmosphereModel,
    CommandProjector,
    Controller,
    DeformableMirrorModel,
    Reconstructor,
    WavefrontSensor,
)
from shwfs_ao.core.random import NamedRandomStreams
from shwfs_ao.core.types import (
    DmCommandVector,
    DmSynthesisResult,
    MeasurementVector,
    ReconstructionEstimate,
    WfsMeasurement,
)


ACTUATOR_IDS = ("A0",)
ROW_IDS = ("R0", "R1", "R2-calibration-invalid")


class _ScalarDmProbeBasis:
    size = 1
    coordinate_ids = ACTUATOR_IDS
    coordinate_kind = "dm_command_opd"
    coordinate_unit = "m_opd_equivalent"
    max_abs_amplitude_m = np.asarray([np.inf])
    config_hash = "scalar-dm-probe-v1"
    dm_hash = "test-dm-hash"

    def opd_m_for_coordinate(self, index: int, amplitude_m: float) -> np.ndarray:
        assert index == 0
        return np.asarray([[amplitude_m, -amplitude_m]], dtype=float)


class _CalibrationSensor:
    config_hash = "test-calibration-sensor-v1"
    row_ids = ROW_IDS

    def measure(
        self,
        residual_opd_m: np.ndarray,
        *,
        random_streams,
        include_noise: bool,
    ) -> WfsMeasurement:
        del random_streams, include_noise
        amplitude = float(np.asarray(residual_opd_m)[0, 0])
        return WfsMeasurement(
            vector=MeasurementVector(
                values=np.asarray([amplitude, 2.0 * amplitude, np.nan]),
                valid_rows=np.asarray([True, True, False]),
                row_ids=ROW_IDS,
                measurement_unit="pixel",
            ),
            valid_subapertures=np.asarray([True, True]),
        )


@pytest.fixture(scope="module")
def interaction_matrix() -> InteractionMatrix:
    return calibrate_interaction_matrix(
        _ScalarDmProbeBasis(),
        _CalibrationSensor(),
        1.0e-9,
        random_streams=NamedRandomStreams(3),
    )


class _Atmosphere:
    backend_name = "test-atmosphere"
    config_hash = "test-atmosphere-hash"

    def __init__(self, value_opd_m: float, events: list[str]) -> None:
        self.value_opd_m = float(value_opd_m)
        self.events = events
        self.times: list[float] = []
        self.realization_index = -1

    @property
    def metadata(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "backend_name": self.backend_name,
                "root_seed": 7,
                "realization_index": self.realization_index,
                "random_stream_id": (
                    f"test-atmosphere-realization:{self.realization_index}"
                ),
            }
        )

    def reset(self, *, realization_index: int = 0) -> None:
        self.events.append("atmosphere.reset")
        self.times.clear()
        self.realization_index = realization_index

    def opd_at(self, time_s: float) -> np.ndarray:
        self.events.append(f"atmosphere.opd:{len(self.times)}")
        self.times.append(float(time_s))
        return np.asarray([[self.value_opd_m, -self.value_opd_m]], dtype=float)


class _RuntimeWfs:
    config_hash = "test-runtime-wfs-hash"
    backend_name = "test-wfs"
    row_ids = ROW_IDS

    def __init__(
        self,
        events: list[str],
        *,
        valid_rows: tuple[np.ndarray, ...] | None = None,
        valid_subapertures: tuple[np.ndarray, ...] | None = None,
        extra_shot_draws: int = 0,
    ) -> None:
        self.events = events
        self.valid_rows = valid_rows
        self.valid_subapertures = valid_subapertures
        self.extra_shot_draws = extra_shot_draws
        self.residual_inputs: list[np.ndarray] = []
        self.measurements: list[MeasurementVector] = []

    def measure(
        self,
        residual_opd_m: np.ndarray,
        *,
        random_streams,
        include_noise: bool,
    ) -> WfsMeasurement:
        index = len(self.residual_inputs)
        self.events.append(f"wfs.measure:{index}")
        residual = np.asarray(residual_opd_m, dtype=float).copy()
        self.residual_inputs.append(residual)
        if self.extra_shot_draws:
            random_streams.generator("detector.shot_noise").normal(
                size=self.extra_shot_draws
            )
        mask = (
            np.asarray([True, True, True], dtype=bool)
            if self.valid_rows is None
            else np.asarray(self.valid_rows[index], dtype=bool)
        )
        value = float(residual[0, 0])
        values = np.asarray([value, 2.0 * value, 123.0e-9])
        values[~mask] = np.nan
        vector = MeasurementVector(values, mask, self.row_ids, "pixel")
        self.measurements.append(vector)
        subapertures = (
            np.asarray([True, True], dtype=bool)
            if self.valid_subapertures is None
            else np.asarray(self.valid_subapertures[index], dtype=bool)
        )
        return WfsMeasurement(
            vector=vector,
            valid_subapertures=subapertures,
            metadata={
                "sensor_backend_name": self.backend_name,
                "sensor_config_hash": self.config_hash,
                "random_root_seed": random_streams.root_seed,
                "include_noise": bool(include_noise),
            },
        )


class _ChangingBackendWfs(_RuntimeWfs):
    @property
    def backend_name(self) -> str:
        return (
            "test-wfs-first"
            if len(self.residual_inputs) <= 1
            else "test-wfs-second"
        )


class _Reconstructor:
    config_hash = "test-reconstructor-hash"

    def __init__(
        self,
        interaction: InteractionMatrix,
        events: list[str],
        *,
        none_frames: frozenset[int] = frozenset(),
    ) -> None:
        self.interaction = interaction
        self.events = events
        self.none_frames = none_frames
        self.measurements: list[MeasurementVector] = []

    @property
    def matrix_hash(self) -> str:
        return self.interaction.calibration_hash

    def reconstruct(
        self,
        measurement: MeasurementVector,
    ) -> ReconstructionEstimate | None:
        index = len(self.measurements)
        self.events.append(f"reconstructor.reconstruct:{index}")
        self.measurements.append(measurement)
        usable = (
            np.asarray(self.interaction.row_valid, dtype=bool)
            & np.asarray(measurement.valid_rows, dtype=bool)
            & np.isfinite(measurement.values)
        )
        if index in self.none_frames:
            return None
        coordinate = float(measurement.values[0])
        reconstructed = np.full(len(ROW_IDS), np.nan)
        residual = np.full(len(ROW_IDS), np.nan)
        reconstructed[usable] = measurement.values[usable]
        residual[usable] = 0.0
        return ReconstructionEstimate(
            delta_coordinates_opd_m=np.asarray([coordinate]),
            coordinate_ids=ACTUATOR_IDS,
            coordinate_kind="dm_command_opd",
            coordinate_unit="m_opd_equivalent",
            measurement_unit="pixel",
            usable_rows=usable,
            reconstructed_signal=reconstructed,
            residual_signal=residual,
            coordinate_norm_m=abs(coordinate),
            residual_norm=0.0,
            kept_modes=1,
            singular_values=np.asarray([1.0]),
            matrix_hash=self.matrix_hash,
        )


class _Projector:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.inner = IdentityCommandProjector(ACTUATOR_IDS)
        self.call_count = 0

    @property
    def config_hash(self) -> str:
        return self.inner.config_hash

    @property
    def input_coordinate_ids(self) -> tuple[str, ...]:
        return self.inner.input_coordinate_ids

    @property
    def input_coordinate_kind(self) -> str:
        return self.inner.input_coordinate_kind

    @property
    def input_coordinate_unit(self) -> str:
        return self.inner.input_coordinate_unit

    @property
    def output_actuator_ids(self) -> tuple[str, ...]:
        return self.inner.output_actuator_ids

    def project(self, estimate: ReconstructionEstimate) -> DmCommandVector:
        self.events.append(f"projector.project:{self.call_count}")
        self.call_count += 1
        return self.inner.project(estimate)


class _Controller:
    def __init__(
        self,
        events: list[str],
        *,
        gain: float,
        leak: float,
        latency_frames: int,
    ) -> None:
        self.events = events
        self.inner = LeakyIntegratorController(
            ACTUATOR_IDS,
            gain=gain,
            leak=leak,
            latency_frames=latency_frames,
        )
        self.update_count = 0
        self.accept_count = 0

    @property
    def config_hash(self) -> str:
        return self.inner.config_hash

    @property
    def actuator_ids(self) -> tuple[str, ...]:
        return self.inner.actuator_ids

    @property
    def gain(self) -> float:
        return self.inner.gain

    @property
    def leak(self) -> float:
        return self.inner.leak

    @property
    def latency_frames(self) -> int:
        return self.inner.latency_frames

    @property
    def last_released_delta(self) -> DmCommandVector:
        return self.inner.last_released_delta

    @property
    def last_applied_commands(self) -> DmCommandVector:
        return self.inner.last_applied_commands

    def reset(self) -> None:
        self.events.append("controller.reset")
        self.inner.reset()
        self.update_count = 0
        self.accept_count = 0

    def update(
        self,
        reconstructed_delta: DmCommandVector | None,
    ) -> DmCommandVector:
        self.events.append(f"controller.update:{self.update_count}")
        self.update_count += 1
        return self.inner.update(reconstructed_delta)

    def accept_applied_commands(self, commands: DmCommandVector) -> None:
        self.events.append(f"controller.accept:{self.accept_count}")
        self.accept_count += 1
        self.inner.accept_applied_commands(commands)


class _Dm:
    backend_name = "test-dm"
    config_hash = "test-dm-hash"
    actuator_ids = ACTUATOR_IDS
    controllable_actuator_ids = ACTUATOR_IDS
    n_actuators = 1

    def __init__(self, events: list[str], *, stroke_limit_m: float) -> None:
        self.events = events
        self.stroke_limit_m = float(stroke_limit_m)
        self.requested: list[np.ndarray] = []

    def opd_from_commands(self, commands: DmCommandVector) -> DmSynthesisResult:
        self.events.append(f"dm.opd:{len(self.requested)}")
        requested = np.asarray(commands.values_opd_m, dtype=float)
        self.requested.append(requested.copy())
        saturated = np.abs(requested) > self.stroke_limit_m
        applied = np.clip(requested, -self.stroke_limit_m, self.stroke_limit_m)
        return DmSynthesisResult(
            correction_opd_m=np.asarray([[applied[0], -applied[0]]]),
            requested_commands_opd_m=requested,
            applied_commands_opd_m=applied,
            actuator_ids=self.actuator_ids,
            saturated_mask=saturated,
            saturation_fraction=float(np.mean(saturated)),
            command_unit="m_opd_equivalent",
            config_hash=self.config_hash,
        )


def _config(**overrides: object) -> LoopConfig:
    values: dict[str, object] = {
        "n_steps": 2,
        "gain": 1.0,
        "leak": 0.0,
        "latency_frames": 0,
        "frame_rate_hz": 2.0,
        "root_seed": 7,
    }
    values.update(overrides)
    return LoopConfig(**values)  # type: ignore[arg-type]


def _components(
    interaction: InteractionMatrix,
    config: LoopConfig,
    *,
    value_opd_m: float = 4.0e-9,
    stroke_limit_m: float = 100.0e-9,
    valid_rows: tuple[np.ndarray, ...] | None = None,
    valid_subapertures: tuple[np.ndarray, ...] | None = None,
    none_frames: frozenset[int] = frozenset(),
    extra_shot_draws: int = 0,
):
    events: list[str] = []
    atmosphere = _Atmosphere(value_opd_m, events)
    wfs = _RuntimeWfs(
        events,
        valid_rows=valid_rows,
        valid_subapertures=valid_subapertures,
        extra_shot_draws=extra_shot_draws,
    )
    reconstructor = _Reconstructor(
        interaction,
        events,
        none_frames=none_frames,
    )
    projector = _Projector(events)
    controller = _Controller(
        events,
        gain=config.gain,
        leak=config.leak,
        latency_frames=config.latency_frames,
    )
    dm = _Dm(events, stroke_limit_m=stroke_limit_m)
    assert isinstance(atmosphere, AtmosphereModel)
    assert isinstance(wfs, WavefrontSensor)
    assert isinstance(reconstructor, Reconstructor)
    assert isinstance(projector, CommandProjector)
    assert isinstance(controller, Controller)
    assert isinstance(dm, DeformableMirrorModel)
    return events, atmosphere, wfs, reconstructor, projector, controller, dm


def _run(
    config: LoopConfig,
    interaction: InteractionMatrix,
    components,
    *,
    streams: NamedRandomStreams | None = None,
):
    events, atmosphere, wfs, reconstructor, projector, controller, dm = components
    history = run_closed_loop(
        config,
        random_streams=(NamedRandomStreams(config.root_seed) if streams is None else streams),
        atmosphere=atmosphere,
        wfs=wfs,
        dm=dm,
        interaction_matrix=interaction,
        reconstructor=reconstructor,
        command_projector=projector,
        controller=controller,
        include_noise=True,
        realization_index=0,
    )
    return history


def test_loop_uses_the_canonical_order_same_truth_sample_and_applied_acknowledgement(
    interaction_matrix: InteractionMatrix,
) -> None:
    config = _config()
    components = _components(
        interaction_matrix,
        config,
        stroke_limit_m=2.0e-9,
        valid_rows=(
            np.asarray([True, False, True]),
            np.asarray([True, True, True]),
        ),
        valid_subapertures=(
            np.asarray([True, False]),
            np.asarray([True, True]),
        ),
    )
    events, atmosphere, wfs, _, projector, _, dm = components

    history = _run(config, interaction_matrix, components)

    assert atmosphere.times == [0.0, 0.5]
    first_frame = events.index("atmosphere.opd:0")
    assert events[first_frame : first_frame + 7] == [
        "atmosphere.opd:0",
        "wfs.measure:0",
        "reconstructor.reconstruct:0",
        "projector.project:0",
        "controller.update:0",
        "dm.opd:1",  # dm.opd:0 establishes the initial current DM correction.
        "controller.accept:1",
    ]
    second_frame = events.index("atmosphere.opd:1")
    assert events[second_frame : second_frame + 7] == [
        "atmosphere.opd:1",
        "wfs.measure:1",
        "reconstructor.reconstruct:1",
        "projector.project:1",
        "controller.update:1",
        "dm.opd:2",
        "controller.accept:2",
    ]
    assert projector.call_count == 2
    np.testing.assert_allclose(wfs.residual_inputs[0], [[4.0e-9, -4.0e-9]])
    np.testing.assert_allclose(wfs.residual_inputs[1], [[2.0e-9, -2.0e-9]])
    # The first request clips from 4 nm to 2 nm.  The next request must be
    # 2 nm applied state + 2 nm new delta = 4 nm, not 6 nm from the unclipped
    # prior request.
    np.testing.assert_allclose(np.asarray(dm.requested).reshape(-1), [0.0, 4e-9, 4e-9])

    np.testing.assert_allclose(history.time_s, [0.0, 0.5])
    np.testing.assert_allclose(history.open_loop_opd_rms_m, [4e-9, 4e-9])
    np.testing.assert_allclose(history.pre_update_residual_opd_rms_m, [4e-9, 2e-9])
    np.testing.assert_allclose(history.post_update_residual_opd_rms_m, [2e-9, 2e-9])
    np.testing.assert_allclose(history.delta_command_norm_m, [4e-9, 2e-9])
    np.testing.assert_allclose(history.released_delta_norm_m, [4e-9, 2e-9])
    np.testing.assert_allclose(history.requested_command_history_opd_m[:, 0], [4e-9, 4e-9])
    np.testing.assert_allclose(history.applied_command_history_opd_m[:, 0], [2e-9, 2e-9])
    np.testing.assert_allclose(history.command_norm_m, [2e-9, 2e-9])
    np.testing.assert_allclose(history.saturation_fraction, [1.0, 1.0])
    np.testing.assert_array_equal(
        history.measurement_row_masks,
        [[True, False, False], [True, True, False]],
    )
    # Denominator is the two calibration-valid rows, not all three nominal rows.
    np.testing.assert_allclose(history.valid_measurement_fraction, [0.5, 1.0])
    np.testing.assert_allclose(history.valid_subaperture_fraction, [0.5, 1.0])
    np.testing.assert_array_equal(history.reconstruction_usable, [True, True])
    assert history.metadata["random_stream_ids"]["atmosphere"] == (
        "test-atmosphere-realization:0"
    )


def test_none_is_not_zero_filled_and_old_queue_entries_and_leak_continue(
    interaction_matrix: InteractionMatrix,
) -> None:
    config = _config(n_steps=3, latency_frames=1, leak=0.25)
    components = _components(
        interaction_matrix,
        config,
        valid_rows=(
            np.asarray([True, True, True]),
            np.asarray([False, False, False]),
            np.asarray([False, False, False]),
        ),
        valid_subapertures=(
            np.asarray([True, True]),
            np.asarray([False, False]),
            np.asarray([False, False]),
        ),
        none_frames=frozenset({1, 2}),
    )
    _, _, _, reconstructor, projector, _, _ = components

    history = _run(config, interaction_matrix, components)

    assert projector.call_count == 1
    assert np.all(np.isnan(reconstructor.measurements[1].values))
    assert np.all(np.isnan(reconstructor.measurements[2].values))
    np.testing.assert_array_equal(
        history.reconstruction_usable,
        [True, False, False],
    )
    np.testing.assert_allclose(history.released_delta_norm_m, [0.0, 4e-9, 0.0])
    np.testing.assert_allclose(
        history.applied_command_history_opd_m[:, 0],
        [0.0, 4e-9, 3e-9],
    )
    np.testing.assert_allclose(
        history.post_update_residual_opd_rms_m,
        [4e-9, 0.0, 1e-9],
        atol=1.0e-24,
    )
    np.testing.assert_allclose(history.valid_measurement_fraction, [1.0, 0.0, 0.0])


def test_root_seed_mismatch_fails_before_any_component_side_effect(
    interaction_matrix: InteractionMatrix,
) -> None:
    config = _config()
    components = _components(interaction_matrix, config)
    events = components[0]

    with pytest.raises(ControlLoopError, match="root_seed"):
        _run(
            config,
            interaction_matrix,
            components,
            streams=NamedRandomStreams(config.root_seed + 1),
        )

    assert events == []


def test_stochastic_atmosphere_root_seed_must_match_before_side_effects(
    interaction_matrix: InteractionMatrix,
) -> None:
    config = _config(root_seed=8)
    components = _components(interaction_matrix, config)
    events = components[0]

    with pytest.raises(ControlLoopError, match="atmosphere root seed"):
        _run(config, interaction_matrix, components)

    assert events == []


def test_retained_subaperture_layout_and_backend_identity_cannot_change(
    interaction_matrix: InteractionMatrix,
) -> None:
    config = _config(n_steps=2)
    changing_lengths = _components(
        interaction_matrix,
        config,
        valid_subapertures=(
            np.asarray([True, True]),
            np.asarray([True, True, True]),
        ),
    )
    with pytest.raises(ControlLoopError, match="valid_subapertures length"):
        _run(config, interaction_matrix, changing_lengths)

    components = list(_components(interaction_matrix, config))
    components[2] = _ChangingBackendWfs(components[0])
    with pytest.raises(ControlLoopError, match="backend identity"):
        _run(config, interaction_matrix, tuple(components))


def test_extra_draws_in_shot_noise_do_not_change_other_domains_or_loop_truth(
    interaction_matrix: InteractionMatrix,
) -> None:
    config = _config()
    baseline_streams = NamedRandomStreams(config.root_seed)
    extra_streams = NamedRandomStreams(config.root_seed)
    baseline_components = _components(interaction_matrix, config)
    extra_components = _components(
        interaction_matrix,
        config,
        extra_shot_draws=37,
    )

    baseline = _run(
        config,
        interaction_matrix,
        baseline_components,
        streams=baseline_streams,
    )
    extra = _run(
        config,
        interaction_matrix,
        extra_components,
        streams=extra_streams,
    )

    np.testing.assert_array_equal(
        baseline.post_update_residual_opd_rms_m,
        extra.post_update_residual_opd_rms_m,
    )
    np.testing.assert_array_equal(
        baseline_streams.generator("detector.read_noise").integers(0, 2**32, 8),
        extra_streams.generator("detector.read_noise").integers(0, 2**32, 8),
    )


def test_replaying_parameter_points_in_reverse_order_is_pointwise_identical(
    interaction_matrix: InteractionMatrix,
) -> None:
    base = _config(n_steps=3)

    def sweep(gains: tuple[float, ...]) -> dict[float, np.ndarray]:
        streams = NamedRandomStreams(base.root_seed)
        results: dict[float, np.ndarray] = {}
        for gain in gains:
            config = replace(base, gain=gain)
            components = _components(interaction_matrix, config)
            history = _run(
                config,
                interaction_matrix,
                components,
                streams=streams,
            )
            results[gain] = np.asarray(history.post_update_residual_opd_rms_m)
        return results

    forward = sweep((0.2, 0.5, 0.8))
    reverse = sweep((0.8, 0.5, 0.2))

    assert forward.keys() == reverse.keys()
    for gain in forward:
        np.testing.assert_array_equal(forward[gain], reverse[gain])
