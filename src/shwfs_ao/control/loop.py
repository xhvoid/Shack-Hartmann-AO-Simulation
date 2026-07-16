"""Backend-independent adaptive-optics closed-loop orchestration.

This module deliberately contains only sequencing, identity validation, and
telemetry.  Numerical WFS, reconstructor, and DM implementations remain behind
their repository-owned protocols.
"""

from __future__ import annotations

from collections.abc import Mapping
import math
from numbers import Integral
from typing import Any, Protocol, cast, runtime_checkable

import numpy as np

from ..calibration.interaction import InteractionMatrix
from ..core.hashing import component_config_hash
from ..core.protocols import (
    AtmosphereModel,
    CommandProjector,
    Controller,
    DeformableMirrorModel,
    RandomStreams,
    Reconstructor,
    WavefrontSensor,
)
from ..core.random import DEFAULT_RANDOM_DOMAINS
from ..core.types import (
    DmCommandVector,
    DmSynthesisResult,
    ReconstructionEstimate,
    WfsMeasurement,
)
from ..core.wavefront import masked_rms
from .config import LoopConfig
from .history import (
    LoopHistory,
    _COMMAND_SIGN_CONVENTION,
    _FIELD_UNITS,
    _RESIDUAL_SIGN_CONVENTION,
)


__all__ = (
    "ControlLoopError",
    "validate_closed_loop_components",
    "run_closed_loop",
)


_COMMAND_UNIT = "m_opd_equivalent"


class ControlLoopError(ValueError):
    """Raised when loop components or per-frame results disagree."""


@runtime_checkable
class _LoopControllerTelemetry(Protocol):
    """AO-REF-009 extension needed for fixed released-delta telemetry."""

    @property
    def gain(self) -> float:
        ...

    @property
    def leak(self) -> float:
        ...

    @property
    def latency_frames(self) -> int:
        ...

    @property
    def last_released_delta(self) -> DmCommandVector:
        ...


@runtime_checkable
class _ConfigIdentifiedReconstructor(Protocol):
    """AO-REF-009 extension needed to hash reconstruction policy."""

    @property
    def config_hash(self) -> str:
        ...


@runtime_checkable
class _TargetDmBoundProjector(Protocol):
    """AO-REF-009 extension binding a modal command map to its target DM."""

    @property
    def target_dm_hash(self) -> str:
        ...


def run_closed_loop(
    config: LoopConfig,
    *,
    random_streams: RandomStreams,
    atmosphere: AtmosphereModel,
    wfs: WavefrontSensor,
    dm: DeformableMirrorModel,
    interaction_matrix: InteractionMatrix,
    reconstructor: Reconstructor,
    command_projector: CommandProjector,
    controller: Controller,
    include_noise: bool,
    realization_index: int = 0,
) -> LoopHistory:
    """Run one deterministic, fixed-length canonical AO control sequence.

    Frame ``k`` samples the atmosphere exactly once at
    ``k / config.frame_rate_hz``.  Both residual metrics for that frame use
    that same sample.  The controller is the only component that delays
    reconstructed command increments.
    """

    validate_closed_loop_components(
        config=config,
        random_streams=random_streams,
        atmosphere=atmosphere,
        wfs=wfs,
        dm=dm,
        interaction_matrix=interaction_matrix,
        reconstructor=reconstructor,
        command_projector=command_projector,
        controller=controller,
        include_noise=include_noise,
        realization_index=realization_index,
    )
    include_noise = bool(include_noise)
    realization_index = int(realization_index)
    component_hashes = _component_hashes(
        config=config,
        atmosphere=atmosphere,
        wfs=wfs,
        dm=dm,
        interaction_matrix=interaction_matrix,
        reconstructor=reconstructor,
        command_projector=command_projector,
        controller=controller,
    )
    random_derivation_scheme_id = _nonempty_text(
        random_streams.derivation_scheme_id,
        label="random_streams.derivation_scheme_id",
    )
    random_stream_ids = {
        domain: _nonempty_text(
            random_streams.stream_id(domain),
            label=f"random_streams.stream_id({domain!r})",
        )
        for domain in DEFAULT_RANDOM_DOMAINS
    }
    atmosphere_backend_name = _nonempty_text(
        atmosphere.backend_name,
        label="atmosphere.backend_name",
    )
    dm_backend_name = _component_name(dm, preferred_attribute="backend_name")
    retained_subaperture_ids = _optional_ids(
        getattr(wfs, "subaperture_ids", None),
        label="wfs.subaperture_ids",
    )
    expected_subaperture_count = (
        None
        if retained_subaperture_ids is None
        else len(retained_subaperture_ids)
    )

    actuator_ids = dm.actuator_ids
    row_ids = interaction_matrix.row_ids
    calibration_valid = np.asarray(interaction_matrix.row_valid, dtype=bool)
    calibration_valid_count = int(np.count_nonzero(calibration_valid))
    n_steps = config.n_steps
    n_actuators = len(actuator_ids)
    n_rows = len(row_ids)

    random_streams.reset()
    atmosphere.reset(realization_index=realization_index)
    atmosphere_realization_stream_id = _atmosphere_reset_identity(
        atmosphere,
        realization_index=realization_index,
    )
    if atmosphere_realization_stream_id is not None:
        random_stream_ids["atmosphere"] = atmosphere_realization_stream_id
    controller.reset()

    initial_request = DmCommandVector(
        values_opd_m=np.zeros(n_actuators, dtype=float),
        actuator_ids=actuator_ids,
        command_unit=_COMMAND_UNIT,
    )
    initial_synthesis = _synthesize(
        dm,
        initial_request,
        expected_actuator_ids=actuator_ids,
        label="initial DM synthesis",
    )
    controller.accept_applied_commands(_applied_command(initial_synthesis))
    current_correction = np.asarray(initial_synthesis.correction_opd_m, dtype=float)

    time_s = np.arange(n_steps, dtype=float) / config.frame_rate_hz
    open_loop_rms = np.empty(n_steps, dtype=float)
    pre_update_rms = np.empty(n_steps, dtype=float)
    post_update_rms = np.empty(n_steps, dtype=float)
    command_norm = np.empty(n_steps, dtype=float)
    delta_command_norm = np.empty(n_steps, dtype=float)
    released_delta_norm = np.empty(n_steps, dtype=float)
    requested_history = np.empty((n_steps, n_actuators), dtype=float)
    applied_history = np.empty((n_steps, n_actuators), dtype=float)
    saturation_fraction = np.empty(n_steps, dtype=float)
    valid_measurement_fraction = np.empty(n_steps, dtype=float)
    valid_subaperture_fraction = np.empty(n_steps, dtype=float)
    reconstruction_usable = np.empty(n_steps, dtype=bool)
    measurement_row_masks = np.empty((n_steps, n_rows), dtype=bool)

    sampled_shape: tuple[int, int] | None = None
    pupil_mask: np.ndarray | None = None
    wfs_backend_fallback = _component_name(wfs)
    reported_wfs_backend_name: str | None = None

    for frame_index, frame_time_s in enumerate(time_s):
        atmospheric_opd = _atmospheric_opd(
            atmosphere.opd_at(float(frame_time_s)),
            expected_shape=sampled_shape,
        )
        if sampled_shape is None:
            sampled_shape = atmospheric_opd.shape
            if current_correction.shape != sampled_shape:
                raise ControlLoopError(
                    "initial DM correction shape must match atmospheric OPD shape."
                )
            pupil_mask = np.isfinite(atmospheric_opd)
            if not np.any(pupil_mask):
                raise ControlLoopError(
                    "atmospheric OPD must contain at least one finite pupil sample."
                )
        elif not np.array_equal(np.isfinite(atmospheric_opd), pupil_mask):
            raise ControlLoopError(
                "atmospheric finite-pupil support must remain constant across frames."
            )

        assert pupil_mask is not None
        residual_before = atmospheric_opd - current_correction
        measurement = _measurement(
            wfs.measure(
                residual_before,
                random_streams=random_streams,
                include_noise=include_noise,
            ),
            row_ids=row_ids,
            measurement_unit=interaction_matrix.measurement_unit,
        )
        measurement_backend_name = _measurement_backend_name(measurement.metadata)
        if measurement_backend_name is not None:
            if reported_wfs_backend_name is None:
                reported_wfs_backend_name = measurement_backend_name
            elif measurement_backend_name != reported_wfs_backend_name:
                raise ControlLoopError(
                    "WFS backend identity must remain constant across frames."
                )
        vector = measurement.vector
        effective_rows = (
            calibration_valid
            & np.asarray(vector.valid_rows, dtype=bool)
            & np.isfinite(np.asarray(vector.values, dtype=float))
        )
        subaperture_valid = measurement.valid_subapertures
        if subaperture_valid is None or subaperture_valid.size == 0:
            raise ControlLoopError(
                "Shack-Hartmann loop measurements must provide a non-empty "
                "valid_subapertures mask."
            )
        subaperture_count = int(subaperture_valid.size)
        if expected_subaperture_count is None:
            expected_subaperture_count = subaperture_count
        elif subaperture_count != expected_subaperture_count:
            raise ControlLoopError(
                "valid_subapertures length must match the retained WFS layout "
                "and remain constant across frames."
            )
        detector_telemetry = measurement.detector_telemetry
        if (
            retained_subaperture_ids is not None
            and detector_telemetry is not None
            and detector_telemetry.subaperture_ids != retained_subaperture_ids
        ):
            raise ControlLoopError(
                "detector telemetry subaperture IDs must exactly match the WFS "
                "retained layout."
            )

        estimate = reconstructor.reconstruct(vector)
        if estimate is None:
            projected_delta = None
            delta_norm = 0.0
            usable = False
        else:
            _estimate(
                estimate,
                interaction_matrix=interaction_matrix,
                effective_rows=effective_rows,
            )
            projected_delta = command_projector.project(estimate)
            _command(
                projected_delta,
                expected_actuator_ids=actuator_ids,
                label="projected command increment",
            )
            delta_norm = _l2_norm(projected_delta.values_opd_m)
            usable = True

        requested = controller.update(projected_delta)
        _command(
            requested,
            expected_actuator_ids=actuator_ids,
            label="controller requested command",
        )
        released = _released_delta(controller, expected_actuator_ids=actuator_ids)
        synthesis = _synthesize(
            dm,
            requested,
            expected_actuator_ids=actuator_ids,
            label=f"frame {frame_index} DM synthesis",
        )
        applied = _applied_command(synthesis)
        controller.accept_applied_commands(applied)
        next_correction = np.asarray(synthesis.correction_opd_m, dtype=float)
        if next_correction.shape != sampled_shape:
            raise ControlLoopError(
                "DM correction shape changed or does not match atmospheric OPD."
            )
        residual_after = atmospheric_opd - next_correction

        open_loop_rms[frame_index] = masked_rms(atmospheric_opd, pupil_mask)
        pre_update_rms[frame_index] = masked_rms(residual_before, pupil_mask)
        post_update_rms[frame_index] = masked_rms(residual_after, pupil_mask)
        command_norm[frame_index] = _l2_norm(synthesis.applied_commands_opd_m)
        delta_command_norm[frame_index] = delta_norm
        released_delta_norm[frame_index] = _l2_norm(released.values_opd_m)
        requested_history[frame_index] = synthesis.requested_commands_opd_m
        applied_history[frame_index] = synthesis.applied_commands_opd_m
        saturation_fraction[frame_index] = synthesis.saturation_fraction
        valid_measurement_fraction[frame_index] = (
            float(np.count_nonzero(effective_rows)) / calibration_valid_count
        )
        valid_subaperture_fraction[frame_index] = float(
            np.mean(np.asarray(subaperture_valid, dtype=bool))
        )
        reconstruction_usable[frame_index] = usable
        measurement_row_masks[frame_index] = effective_rows
        current_correction = next_correction

    assert expected_subaperture_count is not None
    wfs_backend_name = reported_wfs_backend_name or wfs_backend_fallback
    loop_hash = component_config_hash(
        "control.closed_loop_run",
        {
            "component_hashes": component_hashes,
            "random_derivation_scheme_id": random_derivation_scheme_id,
            "random_stream_ids": random_stream_ids,
            "include_noise": include_noise,
            "realization_index": realization_index,
            "residual_sign_convention": _RESIDUAL_SIGN_CONVENTION,
            "command_sign_convention": _COMMAND_SIGN_CONVENTION,
            "frame_sequence": "shwfs_ao.control.run_closed_loop.v1",
        },
    )
    metadata: dict[str, Any] = {
        "field_units": dict(_FIELD_UNITS),
        "residual_sign_convention": _RESIDUAL_SIGN_CONVENTION,
        "command_sign_convention": _COMMAND_SIGN_CONVENTION,
        "actuator_ids": actuator_ids,
        "row_ids": row_ids,
        "calibration_valid_rows": tuple(bool(value) for value in calibration_valid),
        "backend_names": {
            "atmosphere": atmosphere_backend_name,
            "wfs": wfs_backend_name,
            "dm": dm_backend_name,
        },
        "component_hashes": component_hashes,
        "calibration_sensor_config_hash": interaction_matrix.sensor_config_hash,
        "calibration_sensor_identity_policy": (
            "exact_rows_and_units_with_explicit_operating_point_variation"
        ),
        "frame_rate_hz": config.frame_rate_hz,
        "root_seed": config.root_seed,
        "random_derivation_scheme_id": random_derivation_scheme_id,
        "random_stream_ids": random_stream_ids,
        "include_noise": include_noise,
        "realization_index": realization_index,
        "retained_subaperture_count": expected_subaperture_count,
        "rms_policy": "piston_removed_statistic_without_residual_map_mutation",
    }
    if retained_subaperture_ids is not None:
        metadata["subaperture_ids"] = retained_subaperture_ids
    if atmosphere_realization_stream_id is not None:
        metadata["atmosphere_realization_stream_id"] = (
            atmosphere_realization_stream_id
        )
    return LoopHistory(
        time_s=time_s,
        open_loop_opd_rms_m=open_loop_rms,
        pre_update_residual_opd_rms_m=pre_update_rms,
        post_update_residual_opd_rms_m=post_update_rms,
        command_norm_m=command_norm,
        delta_command_norm_m=delta_command_norm,
        released_delta_norm_m=released_delta_norm,
        requested_command_history_opd_m=requested_history,
        applied_command_history_opd_m=applied_history,
        saturation_fraction=saturation_fraction,
        valid_measurement_fraction=valid_measurement_fraction,
        valid_subaperture_fraction=valid_subaperture_fraction,
        reconstruction_usable=reconstruction_usable,
        measurement_row_masks=measurement_row_masks,
        config_hash=loop_hash,
        metadata=metadata,
    )


def validate_closed_loop_components(
    config: LoopConfig,
    *,
    random_streams: RandomStreams,
    atmosphere: AtmosphereModel,
    wfs: WavefrontSensor,
    dm: DeformableMirrorModel,
    interaction_matrix: InteractionMatrix,
    reconstructor: Reconstructor,
    command_projector: CommandProjector,
    controller: Controller,
    include_noise: bool,
    realization_index: int = 0,
) -> None:
    """Validate a complete loop assembly without sampling or mutating it.

    System factories call this guard before returning a constructed system;
    :func:`run_closed_loop` calls the same guard again at the runtime boundary.
    Keeping one validator makes coordinate identities, calibration hashes, and
    full-DM command layouts construction-time invariants rather than failures
    discovered partway through the first frame.
    """

    _preflight(
        config=config,
        random_streams=random_streams,
        atmosphere=atmosphere,
        wfs=wfs,
        dm=dm,
        interaction_matrix=interaction_matrix,
        reconstructor=reconstructor,
        command_projector=command_projector,
        controller=controller,
        include_noise=include_noise,
        realization_index=realization_index,
    )


def _preflight(
    *,
    config: object,
    random_streams: object,
    atmosphere: object,
    wfs: object,
    dm: object,
    interaction_matrix: object,
    reconstructor: object,
    command_projector: object,
    controller: object,
    include_noise: object,
    realization_index: object,
) -> None:
    if not isinstance(config, LoopConfig):
        raise ControlLoopError("config must be a LoopConfig.")
    for value, protocol, label in (
        (random_streams, RandomStreams, "random_streams"),
        (atmosphere, AtmosphereModel, "atmosphere"),
        (wfs, WavefrontSensor, "wfs"),
        (dm, DeformableMirrorModel, "dm"),
        (reconstructor, Reconstructor, "reconstructor"),
        (command_projector, CommandProjector, "command_projector"),
        (controller, Controller, "controller"),
    ):
        if not isinstance(value, protocol):
            raise ControlLoopError(f"{label} does not implement its canonical protocol.")
    if not isinstance(interaction_matrix, InteractionMatrix):
        raise ControlLoopError("interaction_matrix must be an InteractionMatrix.")
    if not isinstance(include_noise, (bool, np.bool_)):
        raise ControlLoopError("include_noise must be a boolean.")
    if (
        isinstance(realization_index, (bool, np.bool_))
        or not isinstance(realization_index, Integral)
        or int(realization_index) < 0
    ):
        raise ControlLoopError("realization_index must be a non-negative integer.")
    if random_streams.root_seed != config.root_seed:
        raise ControlLoopError(
            "random_streams.root_seed must equal config.root_seed."
        )
    _validate_atmosphere_seed(
        cast(AtmosphereModel, atmosphere),
        expected_root_seed=config.root_seed,
    )
    if reconstructor.matrix_hash != interaction_matrix.matrix_hash:
        raise ControlLoopError(
            "reconstructor.matrix_hash must equal interaction_matrix.matrix_hash."
        )
    if not isinstance(reconstructor, _ConfigIdentifiedReconstructor):
        raise ControlLoopError(
            "AO-REF-009 reproducible history requires reconstructor.config_hash "
            "in addition to the minimal Reconstructor protocol."
        )
    if wfs.row_ids != interaction_matrix.row_ids:
        raise ControlLoopError(
            "wfs.row_ids must exactly match interaction-matrix row IDs and ordering."
        )
    if command_projector.input_coordinate_ids != interaction_matrix.coordinate_ids:
        raise ControlLoopError(
            "projector input IDs must exactly match interaction-matrix coordinates."
        )
    if command_projector.input_coordinate_kind != interaction_matrix.coordinate_kind:
        raise ControlLoopError(
            "projector input coordinate kind must match the interaction matrix."
        )
    if command_projector.input_coordinate_unit != interaction_matrix.coordinate_unit:
        raise ControlLoopError(
            "projector input coordinate unit must match the interaction matrix."
        )
    actuator_ids = dm.actuator_ids
    if len(actuator_ids) != dm.n_actuators:
        raise ControlLoopError("dm.n_actuators must match dm.actuator_ids length.")
    if (
        interaction_matrix.coordinate_kind == "dm_command_opd"
        and interaction_matrix.dm_hash != dm.config_hash
    ):
        raise ControlLoopError(
            "actuator-space interaction_matrix.dm_hash must equal dm.config_hash."
        )
    if interaction_matrix.coordinate_kind == "modal_opd":
        if not isinstance(command_projector, _TargetDmBoundProjector):
            raise ControlLoopError(
                "modal command projectors must expose target_dm_hash."
            )
        if command_projector.target_dm_hash != dm.config_hash:
            raise ControlLoopError(
                "modal projector target_dm_hash must equal dm.config_hash."
            )
    if command_projector.output_actuator_ids != actuator_ids:
        raise ControlLoopError(
            "projector output actuator IDs must exactly match the full DM layout."
        )
    if controller.actuator_ids != actuator_ids:
        raise ControlLoopError(
            "controller actuator IDs must exactly match the full DM layout."
        )
    if not isinstance(controller, _LoopControllerTelemetry):
        raise ControlLoopError(
            "AO-REF-009 fixed telemetry requires controller gain, leak, "
            "latency_frames, and last_released_delta in addition to the "
            "minimal Controller protocol."
        )
    for attribute, expected in (
        ("gain", config.gain),
        ("leak", config.leak),
        ("latency_frames", config.latency_frames),
    ):
        actual = getattr(controller, attribute, None)
        if actual != expected:
            raise ControlLoopError(
                f"controller.{attribute} must exactly match config.{attribute}."
            )


def _atmospheric_opd(
    value: object,
    *,
    expected_shape: tuple[int, int] | None,
) -> np.ndarray:
    if not isinstance(value, np.ndarray):
        raise ControlLoopError("atmosphere.opd_at() must return a numpy.ndarray.")
    if (
        value.ndim != 2
        or np.issubdtype(value.dtype, np.bool_)
        or not np.issubdtype(value.dtype, np.number)
        or np.issubdtype(value.dtype, np.complexfloating)
        or np.any(np.isinf(value))
    ):
        raise ControlLoopError(
            "atmospheric OPD must be a 2-D real numeric array without infinities."
        )
    result = np.asarray(value, dtype=float)
    if expected_shape is not None and result.shape != expected_shape:
        raise ControlLoopError("atmospheric OPD shape must remain constant.")
    return result


def _measurement(
    value: object,
    *,
    row_ids: tuple[str, ...],
    measurement_unit: str,
) -> WfsMeasurement:
    if not isinstance(value, WfsMeasurement):
        raise ControlLoopError("wfs.measure() must return a WfsMeasurement.")
    vector = value.vector
    if vector.row_ids != row_ids:
        raise ControlLoopError(
            "measurement row IDs must exactly match interaction-matrix row IDs."
        )
    if vector.measurement_unit != measurement_unit:
        raise ControlLoopError(
            "measurement unit must match the interaction-matrix measurement unit."
        )
    return value


def _estimate(
    value: object,
    *,
    interaction_matrix: InteractionMatrix,
    effective_rows: np.ndarray,
) -> ReconstructionEstimate:
    if not isinstance(value, ReconstructionEstimate):
        raise ControlLoopError(
            "reconstructor must return ReconstructionEstimate or None."
        )
    if value.matrix_hash != interaction_matrix.matrix_hash:
        raise ControlLoopError(
            "reconstruction estimate matrix hash must match the interaction matrix."
        )
    if value.coordinate_ids != interaction_matrix.coordinate_ids:
        raise ControlLoopError(
            "reconstruction coordinate IDs must match the interaction matrix."
        )
    if value.coordinate_kind != interaction_matrix.coordinate_kind:
        raise ControlLoopError(
            "reconstruction coordinate kind must match the interaction matrix."
        )
    if value.coordinate_unit != interaction_matrix.coordinate_unit:
        raise ControlLoopError(
            "reconstruction coordinate unit must match the interaction matrix."
        )
    if value.measurement_unit != interaction_matrix.measurement_unit:
        raise ControlLoopError(
            "reconstruction measurement unit must match the interaction matrix."
        )
    if value.usable_rows.shape != effective_rows.shape:
        raise ControlLoopError(
            "reconstruction usable-row mask must match the measurement row layout."
        )
    if not np.array_equal(
        np.asarray(value.usable_rows, dtype=bool),
        effective_rows,
    ):
        raise ControlLoopError(
            "reconstruction usable_rows must exactly equal the calibration-valid, "
            "runtime-valid, finite measurement-row mask."
        )
    return value


def _command(
    value: object,
    *,
    expected_actuator_ids: tuple[str, ...],
    label: str,
) -> DmCommandVector:
    if not isinstance(value, DmCommandVector):
        raise ControlLoopError(f"{label} must be a DmCommandVector.")
    if value.actuator_ids != expected_actuator_ids:
        raise ControlLoopError(
            f"{label} actuator IDs must exactly match the full DM layout."
        )
    if value.command_unit != _COMMAND_UNIT:
        raise ControlLoopError(f"{label} must use {_COMMAND_UNIT!r}.")
    return value


def _released_delta(
    controller: Controller,
    *,
    expected_actuator_ids: tuple[str, ...],
) -> DmCommandVector:
    try:
        value = cast(
            _LoopControllerTelemetry,
            controller,
        ).last_released_delta
    except Exception as exc:
        raise ControlLoopError(
            "controller failed to expose its last released increment."
        ) from exc
    return _command(
        value,
        expected_actuator_ids=expected_actuator_ids,
        label="controller released command increment",
    )


def _synthesize(
    dm: DeformableMirrorModel,
    request: DmCommandVector,
    *,
    expected_actuator_ids: tuple[str, ...],
    label: str,
) -> DmSynthesisResult:
    value = dm.opd_from_commands(request)
    if not isinstance(value, DmSynthesisResult):
        raise ControlLoopError(f"{label} must return a DmSynthesisResult.")
    if value.actuator_ids != expected_actuator_ids:
        raise ControlLoopError(f"{label} actuator IDs do not match the DM layout.")
    if value.command_unit != _COMMAND_UNIT:
        raise ControlLoopError(f"{label} must use {_COMMAND_UNIT!r}.")
    if value.config_hash != dm.config_hash:
        raise ControlLoopError(f"{label} config hash does not match the DM.")
    if not np.array_equal(
        value.requested_commands_opd_m,
        request.values_opd_m,
    ):
        raise ControlLoopError(
            f"{label} requested-command acknowledgement differs from its input."
        )
    return value


def _applied_command(value: DmSynthesisResult) -> DmCommandVector:
    return DmCommandVector(
        values_opd_m=np.asarray(value.applied_commands_opd_m, dtype=float),
        actuator_ids=value.actuator_ids,
        command_unit=_COMMAND_UNIT,
    )


def _l2_norm(values: np.ndarray) -> float:
    array = np.asarray(values, dtype=float).reshape(-1)
    if array.size == 0 or not np.all(np.isfinite(array)):
        raise ControlLoopError("norm inputs must be non-empty and finite.")
    scale = float(np.max(np.abs(array)))
    if scale == 0.0:
        return 0.0
    scaled = array / scale
    return scale * math.sqrt(float(np.sum(scaled * scaled)))


def _component_hashes(
    *,
    config: LoopConfig,
    atmosphere: AtmosphereModel,
    wfs: WavefrontSensor,
    dm: DeformableMirrorModel,
    interaction_matrix: InteractionMatrix,
    reconstructor: Reconstructor,
    command_projector: CommandProjector,
    controller: Controller,
) -> dict[str, str]:
    reconstructor_hash = cast(
        _ConfigIdentifiedReconstructor,
        reconstructor,
    ).config_hash
    return {
        "loop_config": _nonempty_text(config.config_hash, label="config.config_hash"),
        "atmosphere": _nonempty_text(
            atmosphere.config_hash,
            label="atmosphere.config_hash",
        ),
        "wfs": _nonempty_text(wfs.config_hash, label="wfs.config_hash"),
        "dm": _nonempty_text(dm.config_hash, label="dm.config_hash"),
        "interaction_matrix": _nonempty_text(
            interaction_matrix.matrix_hash,
            label="interaction_matrix.matrix_hash",
        ),
        "reconstructor": _nonempty_text(
            reconstructor_hash,
            label="reconstructor.config_hash",
        ),
        "command_projector": _nonempty_text(
            command_projector.config_hash,
            label="command_projector.config_hash",
        ),
        "controller": _nonempty_text(
            controller.config_hash,
            label="controller.config_hash",
        ),
    }


def _component_name(
    component: object,
    *,
    preferred_attribute: str | None = None,
) -> str:
    if preferred_attribute is not None:
        candidate = getattr(component, preferred_attribute, None)
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return f"{type(component).__module__}.{type(component).__qualname__}"


def _nonempty_text(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ControlLoopError(f"{label} must be a non-empty string.")
    return value


def _optional_ids(value: object, *, label: str) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, tuple) or not value:
        raise ControlLoopError(f"{label} must be a non-empty tuple of IDs.")
    if any(not isinstance(item, str) or not item for item in value):
        raise ControlLoopError(f"{label} must contain non-empty strings.")
    if len(value) != len(set(value)):
        raise ControlLoopError(f"{label} must not contain duplicate IDs.")
    return value


def _validate_atmosphere_seed(
    atmosphere: AtmosphereModel,
    *,
    expected_root_seed: int,
) -> None:
    metadata = _atmosphere_metadata(atmosphere)
    candidate = getattr(atmosphere, "root_seed", metadata.get("root_seed"))
    if candidate is None or metadata.get("realization_invariant") is True:
        return
    if type(candidate) is not int or candidate != expected_root_seed:
        raise ControlLoopError(
            "stochastic atmosphere root seed must equal config.root_seed."
        )


def _atmosphere_reset_identity(
    atmosphere: AtmosphereModel,
    *,
    realization_index: int,
) -> str | None:
    metadata = _atmosphere_metadata(atmosphere)
    recorded_index = metadata.get("realization_index")
    if recorded_index is not None and (
        type(recorded_index) is not int or recorded_index != realization_index
    ):
        raise ControlLoopError(
            "atmosphere metadata realization_index must match the requested index."
        )
    stream_id = metadata.get("random_stream_id")
    if stream_id is None:
        return None
    return _nonempty_text(
        stream_id,
        label="atmosphere.metadata.random_stream_id",
    )


def _atmosphere_metadata(
    atmosphere: AtmosphereModel,
) -> Mapping[str, Any]:
    metadata = atmosphere.metadata
    if not isinstance(metadata, Mapping):
        raise ControlLoopError("atmosphere.metadata must be a mapping.")
    return metadata


def _measurement_backend_name(
    metadata: Mapping[str, Any],
) -> str | None:
    for key in ("sensor_backend_name", "optics_backend_name", "backend_name"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None
