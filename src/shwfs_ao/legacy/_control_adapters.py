"""Private compatibility adapters for the canonical control-loop runner.

The installed detector-loop API predates the repository's typed metre-based
component contracts.  It accepts phase radians, a pixels-per-nanometre poke
matrix, and an integer child-seed sequence.  This module performs only that
boundary conversion.  Gain, leak, command state, latency, and frame sequencing
remain owned by :mod:`shwfs_ao.control`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from types import MappingProxyType

import numpy as np

from ..calibration.diagnostics import interaction_diagnostics
from ..calibration.interaction import (
    InteractionMatrix,
    _interaction_matrix_hash_from_values,
)
from ..control import (
    ControlledSubsetCommandProjector,
    LeakyIntegratorController,
    LoopConfig,
    run_closed_loop,
)
from ..core.hashing import component_config_hash
from ..core.provenance import Provenance
from ..core.random import NamedRandomStreams
from ..core.types import (
    DmCommandVector,
    DmSynthesisResult,
    MeasurementVector,
    ReconstructionEstimate,
    WfsMeasurement,
)
from ._reconstruction_adapters import _legacy_tsvd_reconstructor
from .dm_model import (
    DMModel,
    _canonical_model,
    _legacy_applied_commands_nm,
)
from .interaction_matrix import PokeMtxResult
from .synthetic_instrument_data import (
    DEFAULT_CENTROID_VALIDITY,
    DetectorShwfsCalibration,
    _canonical_sensor_for_legacy_calibration,
    measure_detector_shwfs,
)


_NM_PER_M = 1.0e9
_PHASE_TWO_PI = 2.0 * np.pi
_COMMAND_UNIT = "m_opd_equivalent"


@dataclass(frozen=True)
class _LegacyDetectorControlRun:
    """Canonical telemetry plus the exact legacy phase sequence it consumed."""

    history: object
    phase_sequence_rad: np.ndarray


class _LegacyPhaseSequenceAtmosphere:
    """Present a frozen legacy phase cube through ``AtmosphereModel``."""

    def __init__(
        self,
        phase_sequence_rad: np.ndarray,
        pupil_mask: np.ndarray,
        *,
        wavelength_m: float,
        frame_rate_hz: float,
    ) -> None:
        phases = np.asarray(phase_sequence_rad, dtype=float)
        pupil = np.asarray(pupil_mask, dtype=bool)
        if phases.ndim != 3 or phases.shape[1:] != pupil.shape:
            raise ValueError(
                "phase_sequence_rad must have shape (n_steps, ny, nx)."
            )
        if not np.any(pupil) or not np.all(np.isfinite(phases[:, pupil])):
            raise ValueError(
                "phase_sequence_rad must be finite on a non-empty pupil."
            )
        wavelength = _positive(wavelength_m, label="wavelength_m")
        frame_rate = _positive(frame_rate_hz, label="frame_rate_hz")

        # AtmosphereModel promises piston-removed OPD.  Removing each legacy
        # phase piston here is algebraically identical to the historical
        # residual-side removal because the DM adapter below does the same for
        # its correction.
        centered = np.array(phases, dtype=float, copy=True)
        centered[:, pupil] -= np.mean(centered[:, pupil], axis=1)[:, None]
        centered[:, ~pupil] = np.nan
        opd = centered * wavelength / _PHASE_TWO_PI

        self._phase_sequence_rad = _readonly(phases, dtype=float)
        self._opd_sequence_m = _readonly(opd, dtype=float)
        self._pupil_mask = _readonly(pupil, dtype=bool)
        self._frame_rate_hz = frame_rate
        self._next_frame = 0
        self._realization_index = 0
        self._config_hash = component_config_hash(
            "legacy.detector_loop_phase_sequence_atmosphere",
            {
                "phase_sequence_rad": phases,
                "pupil_mask": pupil,
                "wavelength_m": wavelength,
                "frame_rate_hz": frame_rate,
                "conversion": "opd_m=phase_rad*wavelength_m/(2*pi)",
                "piston_policy": "remove_per_frame_on_pupil",
            },
        )
        self._metadata: Mapping[str, object] = MappingProxyType(
            {
                "backend_name": self.backend_name,
                "model_kind": "legacy_phase_sequence_adapter",
                "opd_unit": "m",
                "config_hash": self._config_hash,
            }
        )

    @property
    def backend_name(self) -> str:
        return "legacy_phase_sequence"

    @property
    def config_hash(self) -> str:
        return self._config_hash

    @property
    def metadata(self) -> Mapping[str, object]:
        return self._metadata

    def reset(self, *, realization_index: int = 0) -> None:
        if type(realization_index) is not int or realization_index < 0:
            raise ValueError("realization_index must be a non-negative integer.")
        # A caller-supplied phase cube is deliberately realization invariant.
        self._realization_index = realization_index
        self._next_frame = 0

    def opd_at(self, time_s: float) -> np.ndarray:
        time_value = _nonnegative(time_s, label="time_s")
        expected_time = self._next_frame / self._frame_rate_hz
        if not math.isclose(time_value, expected_time, rel_tol=0.0, abs_tol=1.0e-15):
            raise ValueError(
                "legacy phase-sequence atmosphere must be sampled in exact "
                "frame order."
            )
        if self._next_frame >= self._opd_sequence_m.shape[0]:
            raise ValueError("legacy phase-sequence atmosphere is exhausted.")
        result = np.array(
            self._opd_sequence_m[self._next_frame],
            dtype=float,
            copy=True,
        )
        result.setflags(write=False)
        self._next_frame += 1
        return result


class _LegacyPistonRemovedDm:
    """Wrap the canonical legacy DM while retaining its old piston policy."""

    def __init__(self, model: DMModel) -> None:
        self._legacy_model = model
        self._canonical = _canonical_model(model)
        self._pupil_mask = np.asarray(model.pupil_mask, dtype=bool)
        self._config_hash = component_config_hash(
            "legacy.detector_loop_dm_adapter",
            {
                "canonical_dm_hash": self._canonical.config_hash,
                "pupil_mask": self._pupil_mask,
                "correction_policy": "remove_piston_inside_pupil_zero_outside",
            },
        )

    @property
    def backend_name(self) -> str:
        return self._canonical.backend_name

    @property
    def config_hash(self) -> str:
        return self._config_hash

    @property
    def n_actuators(self) -> int:
        return self._canonical.n_actuators

    @property
    def actuator_ids(self) -> tuple[str, ...]:
        return self._canonical.actuator_ids

    @property
    def controllable_actuator_ids(self) -> tuple[str, ...]:
        return self._canonical.controllable_actuator_ids

    def opd_from_commands(self, commands: DmCommandVector) -> DmSynthesisResult:
        raw = self._canonical.opd_from_commands(commands)

        # Reproduce the legacy operation order: convert raw correction to nm,
        # remove its pupil piston in that unit, then cross the SI boundary.
        raw_nm = np.asarray(raw.correction_opd_m, dtype=float) * _NM_PER_M
        correction_nm = np.zeros(raw_nm.shape, dtype=float)
        correction_nm[self._pupil_mask] = raw_nm[self._pupil_mask]
        correction_nm[self._pupil_mask] -= np.mean(
            correction_nm[self._pupil_mask]
        )
        applied_nm = _legacy_applied_commands_nm(
            np.asarray(commands.values_opd_m, dtype=float) * _NM_PER_M,
            self._legacy_model,
            raw,
        )
        return DmSynthesisResult(
            correction_opd_m=correction_nm / _NM_PER_M,
            requested_commands_opd_m=np.asarray(
                commands.values_opd_m,
                dtype=float,
            ),
            applied_commands_opd_m=applied_nm / _NM_PER_M,
            actuator_ids=self.actuator_ids,
            saturated_mask=np.asarray(raw.saturated_mask, dtype=bool),
            saturation_fraction=float(raw.saturation_fraction),
            command_unit=_COMMAND_UNIT,
            config_hash=self._config_hash,
        )


class _LegacyDetectorWfs:
    """Emit poke-retained legacy y-up centroid rows as a typed WFS result."""

    def __init__(
        self,
        calibration: DetectorShwfsCalibration,
        poke_result: PokeMtxResult,
        *,
        frame_seeds: Sequence[int],
        expected_root_seed: int,
    ) -> None:
        sensor = _canonical_sensor_for_legacy_calibration(
            calibration,
            DEFAULT_CENTROID_VALIDITY,
        )
        retained = np.asarray(poke_result.valid_subaperture_mask, dtype=bool)
        if retained.shape != (calibration.n_valid_subapertures,):
            raise ValueError(
                "poke_result valid-subaperture mask does not match calibration."
            )
        full_row_ids = np.asarray(sensor.row_ids, dtype=object).reshape(-1, 2)
        if full_row_ids.shape[0] != retained.size:
            raise ValueError(
                "canonical sensor row layout does not match legacy calibration."
            )
        full_subaperture_ids = tuple(sensor.subaperture_ids)
        if len(full_subaperture_ids) != retained.size:
            raise ValueError(
                "canonical sensor subaperture layout does not match legacy "
                "calibration."
            )
        seeds = tuple(int(value) for value in frame_seeds)
        if any(value < 0 for value in seeds):
            raise ValueError("frame_seeds must be non-negative integers.")
        self._calibration = calibration
        self._retained = _readonly(retained, dtype=bool)
        self._subaperture_ids = tuple(
            identifier
            for identifier, keep in zip(
                full_subaperture_ids,
                retained,
                strict=True,
            )
            if bool(keep)
        )
        self._row_ids = tuple(full_row_ids[retained].reshape(-1).tolist())
        self._frame_seeds = seeds
        self._expected_root_seed = int(expected_root_seed)
        self._next_frame = 0
        self._config_hash = component_config_hash(
            "legacy.detector_loop_wfs_adapter",
            {
                "canonical_sensor_hash": sensor.config_hash,
                "poke_config_hash": poke_result.config_hash,
                "retained_subapertures": retained,
                "subaperture_ids": self._subaperture_ids,
                "row_ids": self._row_ids,
                "measurement_unit": "pixel",
                "legacy_y_axis": "centered_y_up",
            },
        )

    @property
    def config_hash(self) -> str:
        return self._config_hash

    @property
    def row_ids(self) -> tuple[str, ...]:
        return self._row_ids

    @property
    def subaperture_ids(self) -> tuple[str, ...]:
        return self._subaperture_ids

    def measure(
        self,
        residual_opd_m: np.ndarray,
        *,
        random_streams,
        include_noise: bool,
    ) -> WfsMeasurement:
        if random_streams.root_seed != self._expected_root_seed:
            raise ValueError(
                "legacy WFS adapter random root seed does not match loop config."
            )
        if self._next_frame >= len(self._frame_seeds):
            raise ValueError("legacy detector WFS frame-seed schedule is exhausted.")
        residual = np.asarray(residual_opd_m, dtype=float)
        pupil = np.asarray(self._calibration.pupil_mask, dtype=bool)
        if residual.shape != pupil.shape or not np.all(np.isfinite(residual[pupil])):
            raise ValueError("residual_opd_m is invalid on the legacy WFS pupil.")
        phase = np.full(residual.shape, np.nan, dtype=float)
        wavelength = self._calibration.geometry.wfs_wavelength_m
        phase[pupil] = residual[pupil] * _PHASE_TWO_PI / wavelength
        seed = self._frame_seeds[self._next_frame]
        self._next_frame += 1
        measured = measure_detector_shwfs(
            phase,
            self._calibration,
            include_noise=bool(include_noise),
            seed=seed,
        )
        retained = np.asarray(self._retained, dtype=bool)
        values = np.asarray(measured.shifts_px, dtype=float)[retained].reshape(-1)
        valid_subapertures = np.asarray(measured.valid, dtype=bool)[retained]
        valid_rows = np.repeat(valid_subapertures, 2) & np.isfinite(values)
        values = np.array(values, dtype=float, copy=True)
        values[~valid_rows] = np.nan
        vector = MeasurementVector(
            values=values,
            valid_rows=valid_rows,
            row_ids=self._row_ids,
            measurement_unit="pixel",
        )
        return WfsMeasurement(
            vector=vector,
            valid_subapertures=valid_subapertures,
            metadata={
                "sensor_backend_name": "legacy_detector_compatibility",
                "sensor_config_hash": self._config_hash,
                "random_root_seed": int(random_streams.root_seed),
                "random_derivation_scheme_id": (
                    random_streams.derivation_scheme_id
                ),
                "legacy_frame_seed": seed,
                "include_noise": bool(include_noise),
            },
        )


class _LegacyTypedTsvdReconstructor:
    """Retain frozen px/nm arithmetic behind the typed Reconstructor protocol."""

    def __init__(
        self,
        poke_result: PokeMtxResult,
        interaction_matrix: InteractionMatrix,
    ) -> None:
        self._interaction_matrix = interaction_matrix
        self._numeric = _legacy_tsvd_reconstructor(
            poke_result.poke_matrix,
            poke_result.rcond,
            matrix_error="response_matrix must be 2-D.",
            length_error=(
                "Measurement vector length does not match response-matrix "
                "row count."
            ),
            no_rows_error="No finite rows are available for reconstruction.",
        )
        self._config_hash = component_config_hash(
            "legacy.detector_loop_tsvd_reconstructor",
            {
                "interaction_matrix_hash": interaction_matrix.matrix_hash,
                "legacy_poke_config_hash": poke_result.config_hash,
                "rcond": float(poke_result.rcond),
                "solver": "legacy_masked_tsvd",
                "unusable_measurement_policy": "return_none_when_no_finite_rows",
                "coordinate_conversion": "nm_opd_equivalent_to_m_opd_equivalent",
            },
        )

    @property
    def matrix_hash(self) -> str:
        return self._interaction_matrix.matrix_hash

    @property
    def config_hash(self) -> str:
        return self._config_hash

    def reconstruct(
        self,
        measurement: MeasurementVector,
    ) -> ReconstructionEstimate | None:
        matrix = self._interaction_matrix
        if not isinstance(measurement, MeasurementVector):
            raise ValueError("measurement must be a MeasurementVector.")
        if measurement.row_ids != matrix.row_ids:
            raise ValueError("measurement row IDs do not match the poke matrix.")
        if measurement.measurement_unit != matrix.measurement_unit:
            raise ValueError("measurement unit does not match the poke matrix.")
        values = np.array(measurement.values, dtype=float, copy=True)
        usable = (
            np.asarray(matrix.row_valid, dtype=bool)
            & np.asarray(measurement.valid_rows, dtype=bool)
            & np.isfinite(values)
        )
        if not np.any(usable):
            return None
        values[~usable] = np.nan
        numeric = self._numeric.reconstruct(values)
        coordinates_m = np.asarray(numeric.coordinates, dtype=float) / _NM_PER_M
        return ReconstructionEstimate(
            delta_coordinates_opd_m=coordinates_m,
            coordinate_ids=matrix.coordinate_ids,
            coordinate_kind="dm_command_opd",
            coordinate_unit=_COMMAND_UNIT,
            measurement_unit="pixel",
            usable_rows=np.asarray(numeric.usable_rows, dtype=bool),
            reconstructed_signal=np.asarray(
                numeric.reconstructed_signal,
                dtype=float,
            ),
            residual_signal=np.asarray(numeric.residual_signal, dtype=float),
            coordinate_norm_m=float(numeric.coordinate_norm) / _NM_PER_M,
            residual_norm=float(numeric.residual_norm),
            kept_modes=numeric.kept_modes,
            singular_values=(
                np.asarray(numeric.singular_values, dtype=float) * _NM_PER_M
            ),
            matrix_hash=matrix.matrix_hash,
        )


def _run_legacy_detector_integrator(
    phase_sequence_rad: np.ndarray,
    calibration: DetectorShwfsCalibration,
    dm_model: DMModel,
    poke_result: PokeMtxResult,
    *,
    n_steps: int,
    gain: float,
    leak: float,
    latency_frames: int,
    frame_rate_hz: float,
    root_seed: int,
    include_detector_noise: bool,
    frame_seeds: Sequence[int],
) -> _LegacyDetectorControlRun:
    """Run the installed detector profile through the sole production loop."""

    loop_config = LoopConfig(
        n_steps=n_steps,
        gain=gain,
        leak=leak,
        latency_frames=latency_frames,
        frame_rate_hz=frame_rate_hz,
        root_seed=root_seed,
    )
    streams = NamedRandomStreams(root_seed)
    atmosphere = _LegacyPhaseSequenceAtmosphere(
        phase_sequence_rad,
        calibration.pupil_mask,
        wavelength_m=calibration.geometry.wfs_wavelength_m,
        frame_rate_hz=frame_rate_hz,
    )
    dm = _LegacyPistonRemovedDm(dm_model)
    wfs = _LegacyDetectorWfs(
        calibration,
        poke_result,
        frame_seeds=frame_seeds,
        expected_root_seed=root_seed,
    )
    interaction = _legacy_interaction_matrix(
        calibration,
        dm,
        wfs,
        poke_result,
    )
    reconstructor = _LegacyTypedTsvdReconstructor(poke_result, interaction)
    coordinate_ids = interaction.coordinate_ids
    projector = ControlledSubsetCommandProjector(
        coordinate_ids,
        dm.actuator_ids,
    )
    controller = LeakyIntegratorController.from_loop_config(
        dm.actuator_ids,
        loop_config,
    )
    history = run_closed_loop(
        loop_config,
        random_streams=streams,
        atmosphere=atmosphere,
        wfs=wfs,
        dm=dm,
        interaction_matrix=interaction,
        reconstructor=reconstructor,
        command_projector=projector,
        controller=controller,
        include_noise=bool(include_detector_noise),
    )
    return _LegacyDetectorControlRun(
        history=history,
        phase_sequence_rad=_readonly(phase_sequence_rad, dtype=float),
    )


def _legacy_interaction_matrix(
    calibration: DetectorShwfsCalibration,
    dm: _LegacyPistonRemovedDm,
    wfs: _LegacyDetectorWfs,
    poke_result: PokeMtxResult,
) -> InteractionMatrix:
    matrix = np.asarray(poke_result.poke_matrix, dtype=float) * _NM_PER_M
    row_valid = np.asarray(poke_result.row_valid, dtype=bool)
    matrix = np.array(matrix, dtype=float, copy=True)
    matrix[~row_valid] = np.nan
    diagnostics = interaction_diagnostics(matrix, row_valid)
    controlled_indices = np.asarray(
        poke_result.controlled_actuator_indices,
        dtype=int,
    )
    coordinate_ids = tuple(dm.actuator_ids[int(index)] for index in controlled_indices)
    provenance = Provenance(
        source_class=poke_result.source_class,
        source_note=poke_result.source_note,
        references=(
            "legacy pixels-per-nm poke matrix adapted to canonical pixels-per-metre",
        ),
    )
    geometry_hash = component_config_hash(
        "legacy.detector_loop_geometry",
        {
            "x_m": calibration.x_m,
            "y_m": calibration.y_m,
            "pupil_mask": calibration.pupil_mask,
            "centers_m": calibration.centers_m,
            "subaperture_masks": calibration.subaperture_masks,
        },
    )
    detector_hash = component_config_hash(
        "legacy.detector_loop_detector",
        {
            "detector": calibration.detector,
            "reference_centroids_px": calibration.reference_centroids_px,
        },
    )
    values = {
        "matrix": matrix,
        "row_valid": row_valid,
        "row_ids": wfs.row_ids,
        "coordinate_ids": coordinate_ids,
        "coordinate_kind": "dm_command_opd",
        "calibration_amplitude_m": (
            float(poke_result.calibration_amplitude_nm) / _NM_PER_M
        ),
        "measurement_unit": "pixel",
        "coordinate_unit": _COMMAND_UNIT,
        "matrix_unit": "pixel / m_opd_equivalent",
        "singular_values": diagnostics.singular_values,
        "rank": diagnostics.rank,
        "condition_proxy": diagnostics.condition_proxy,
        "method": "central",
        "include_noise": False,
        "repeat_count": 1,
        "matrix_standard_error": None,
        "sensor_config_hash": wfs.config_hash,
        "geometry_hash": geometry_hash,
        "detector_hash": detector_hash,
        "dm_hash": dm.config_hash,
        "provenance": provenance,
    }
    calibration_hash = _interaction_matrix_hash_from_values(**values)
    return InteractionMatrix(
        **values,
        calibration_hash=calibration_hash,
    )


def _readonly(value: object, *, dtype: object) -> np.ndarray:
    contiguous = np.ascontiguousarray(np.array(value, dtype=dtype, copy=True))
    immutable = np.frombuffer(
        contiguous.tobytes(order="C"),
        dtype=contiguous.dtype,
    )
    return immutable.reshape(contiguous.shape)


def _positive(value: object, *, label: str) -> float:
    result = _nonnegative(value, label=label)
    if result <= 0.0:
        raise ValueError(f"{label} must be positive.")
    return result


def _nonnegative(value: object, *, label: str) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{label} must be a finite number.")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite number.") from exc
    if not math.isfinite(result) or result < 0.0:
        raise ValueError(f"{label} must be a non-negative finite number.")
    return result


__all__: tuple[str, ...] = ()
