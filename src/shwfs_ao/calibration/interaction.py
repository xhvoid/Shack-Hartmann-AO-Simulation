"""Canonical interaction-matrix calibration.

The calibration sign is deliberately independent of closed-loop bookkeeping:
every column is the wavefront-sensor response to a *positive residual*
aberration OPD map.  A deformable-mirror basis therefore presents each
positive correction influence to the sensor as a positive synthetic residual.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from numbers import Integral, Real
from typing import Any, Literal, Protocol, cast, runtime_checkable

import numpy as np

from ..backends.native.modes import normalize_mode_to_unit_pupil_rms
from ..core.hashing import (
    calibration_rows_hash,
    command_coordinates_hash,
    component_config_hash,
    stable_hash,
)
from ..core.protocols import RandomStreams, WavefrontSensor
from ..core.provenance import Provenance
from ..core.types import MeasurementUnit, WfsMeasurement
from ..dm.model import DeformableMirror
from .diagnostics import (
    InteractionDiagnosticsError,
    all_zero_columns,
    interaction_diagnostics,
)


CoordinateKind = Literal["modal_opd", "dm_command_opd"]
CoordinateUnit = Literal["m_opd_rms", "m_opd_equivalent"]
CalibrationMethod = Literal["forward", "central"]

INTERACTION_SIGN_CONVENTION = "positive_residual_aberration_opd"
INTERACTION_MATRIX_SCHEMA_ID = "shwfs_ao.calibration.InteractionMatrix.v1"

_MEASUREMENT_UNITS = frozenset({"pixel", "rad_wavefront_slope"})
_COORDINATE_KINDS = frozenset({"modal_opd", "dm_command_opd"})
_COORDINATE_UNITS = frozenset({"m_opd_rms", "m_opd_equivalent"})
_METHODS = frozenset({"forward", "central"})
_KIND_UNIT_PAIRS = {
    "modal_opd": "m_opd_rms",
    "dm_command_opd": "m_opd_equivalent",
}


class InteractionMatrixError(ValueError):
    """Raised when a basis, calibration sample, or result is inconsistent."""


# Descriptive alias for callers that prefer an operation-oriented error name.
InteractionCalibrationError = InteractionMatrixError


@runtime_checkable
class ProbeBasis(Protocol):
    """Ordered OPD perturbations with explicit coordinate semantics."""

    @property
    def size(self) -> int:
        ...

    @property
    def coordinate_ids(self) -> tuple[str, ...]:
        ...

    @property
    def coordinate_kind(self) -> CoordinateKind:
        ...

    @property
    def coordinate_unit(self) -> CoordinateUnit:
        ...

    @property
    def max_abs_amplitude_m(self) -> np.ndarray:
        ...

    def opd_m_for_coordinate(
        self,
        index: int,
        amplitude_m: float,
    ) -> np.ndarray:
        ...


class ModalProbeBasis:
    """Ordered, piston-free modal OPD maps normalized to unit pupil RMS.

    ``modes`` is an insertion-ordered mapping from stable coordinate ID to a
    sampled two-dimensional mode.  Input values may use any common scale;
    amplitudes passed to :meth:`opd_m_for_coordinate` are always metres of
    pupil RMS OPD.
    """

    def __init__(
        self,
        modes: Mapping[str, np.ndarray],
        pupil_mask: np.ndarray,
        *,
        max_abs_amplitude_m: float | np.ndarray = np.inf,
    ) -> None:
        if not isinstance(modes, Mapping) or not modes:
            raise InteractionMatrixError(
                "modes must be a non-empty ordered mapping of IDs to 2-D arrays."
            )
        coordinate_ids = _validated_ids(tuple(modes.keys()), label="mode IDs")
        mask = _immutable_bool_array(pupil_mask, label="pupil_mask", ndim=2)
        if not np.any(mask):
            raise InteractionMatrixError("pupil_mask must contain at least one pixel.")

        normalized: list[np.ndarray] = []
        scales: list[float] = []
        for coordinate_id in coordinate_ids:
            raw = modes[coordinate_id]
            if not isinstance(raw, np.ndarray):
                raise InteractionMatrixError(
                    f"mode {coordinate_id!r} must be a numpy.ndarray."
                )
            if raw.shape != mask.shape:
                raise InteractionMatrixError(
                    f"mode {coordinate_id!r} shape {raw.shape} does not match "
                    f"pupil_mask shape {mask.shape}."
                )
            try:
                unit_mode, raw_rms = normalize_mode_to_unit_pupil_rms(
                    raw,
                    mask,
                    remove_piston=True,
                    return_scale=True,
                )
            except (TypeError, ValueError) as exc:
                raise InteractionMatrixError(
                    f"mode {coordinate_id!r} cannot be normalized: {exc}"
                ) from exc
            normalized.append(
                _immutable_float_array(
                    unit_mode,
                    label=f"normalized mode {coordinate_id!r}",
                    ndim=2,
                    finite=True,
                )
            )
            scales.append(float(raw_rms))

        bounds = _validated_bounds(max_abs_amplitude_m, len(coordinate_ids))
        stack = _immutable_float_array(
            np.stack(normalized, axis=0),
            label="normalized_modes",
            ndim=3,
            finite=True,
        )
        scale_array = _immutable_float_array(
            np.asarray(scales, dtype=float),
            label="normalization_scales",
            ndim=1,
            finite=True,
        )
        self._coordinate_ids = coordinate_ids
        self._pupil_mask = mask
        self._normalized_modes = stack
        self._normalization_scales = scale_array
        self._max_abs_amplitude_m = bounds
        self._config_hash = component_config_hash(
            "modal_probe_basis",
            {
                "coordinate_ids": coordinate_ids,
                "coordinate_kind": "modal_opd",
                "coordinate_unit": "m_opd_rms",
                "pupil_mask": mask,
                "normalized_modes": stack,
                "normalization_scales": scale_array,
                "max_abs_amplitude_m": bounds,
            },
        )

    @property
    def size(self) -> int:
        return len(self._coordinate_ids)

    @property
    def coordinate_ids(self) -> tuple[str, ...]:
        return self._coordinate_ids

    @property
    def names(self) -> tuple[str, ...]:
        """Compatibility-friendly alias for the ordered coordinate IDs."""

        return self._coordinate_ids

    @property
    def coordinate_kind(self) -> Literal["modal_opd"]:
        return "modal_opd"

    @property
    def coordinate_unit(self) -> Literal["m_opd_rms"]:
        return "m_opd_rms"

    @property
    def max_abs_amplitude_m(self) -> np.ndarray:
        return _immutable_float_array(
            self._max_abs_amplitude_m,
            label="max_abs_amplitude_m",
            ndim=1,
        )

    @property
    def modes(self) -> np.ndarray:
        """Return the ordered unit-pupil-RMS mode stack."""

        return _immutable_float_array(
            self._normalized_modes,
            label="modes",
            ndim=3,
        )

    @property
    def normalized_modes(self) -> np.ndarray:
        return self.modes

    @property
    def normalization_scales(self) -> np.ndarray:
        """Raw piston-removed RMS of each input mode."""

        return _immutable_float_array(
            self._normalization_scales,
            label="normalization_scales",
            ndim=1,
        )

    @property
    def pupil_mask(self) -> np.ndarray:
        return _immutable_bool_array(self._pupil_mask, label="pupil_mask", ndim=2)

    @property
    def config_hash(self) -> str:
        return self._config_hash

    def opd_m_for_coordinate(
        self,
        index: int,
        amplitude_m: float,
    ) -> np.ndarray:
        coordinate_index = _validated_index(index, self.size)
        amplitude = _finite_float(amplitude_m, label="amplitude_m")
        if abs(amplitude) > float(self._max_abs_amplitude_m[coordinate_index]):
            raise InteractionMatrixError(
                f"|amplitude_m| exceeds the bound for coordinate "
                f"{self._coordinate_ids[coordinate_index]!r}."
            )
        return _immutable_float_array(
            np.asarray(self._normalized_modes[coordinate_index]) * amplitude,
            label="modal perturbation OPD",
            ndim=2,
            finite=True,
        )


class DmActuatorProbeBasis:
    """Positive correction influences for controllable canonical DM actuators."""

    def __init__(
        self,
        dm: DeformableMirror,
        *,
        coordinate_ids: tuple[str, ...] | None = None,
    ) -> None:
        if not isinstance(dm, DeformableMirror):
            raise InteractionMatrixError(
                "dm must be the canonical shwfs_ao.dm.DeformableMirror."
            )
        controllable = dm.controllable_actuator_ids
        if not controllable:
            raise InteractionMatrixError(
                "dm has no controllable actuators available for calibration."
            )
        selected = controllable if coordinate_ids is None else _validated_ids(
            coordinate_ids,
            label="coordinate_ids",
        )
        if not selected:
            raise InteractionMatrixError("coordinate_ids must not be empty.")
        selected_set = set(selected)
        if any(identifier not in controllable for identifier in selected):
            raise InteractionMatrixError(
                "coordinate_ids must contain only controllable DM actuator IDs."
            )
        canonical_subset = tuple(
            identifier for identifier in controllable if identifier in selected_set
        )
        if selected != canonical_subset:
            raise InteractionMatrixError(
                "coordinate_ids must preserve the canonical controllable-actuator "
                "ordering."
            )

        full_index = {identifier: index for index, identifier in enumerate(dm.actuator_ids)}
        indices = np.asarray([full_index[identifier] for identifier in selected], dtype=int)
        influences = np.asarray(dm.influence_functions, dtype=float)[indices]
        if influences.ndim != 3 or not np.all(np.isfinite(influences)):
            raise InteractionMatrixError(
                "selected DM influence functions must be finite 2-D maps."
            )
        if np.any(np.all(influences == 0.0, axis=(1, 2))):
            bad = [
                identifier
                for identifier, influence in zip(selected, influences, strict=True)
                if np.all(influence == 0.0)
            ]
            raise InteractionMatrixError(
                f"controllable DM influence functions are all-zero for {bad}."
            )

        bounds = np.full(len(selected), dm.stroke_limit_opd_m, dtype=float)
        self._dm = dm
        self._coordinate_ids = selected
        self._full_actuator_indices = _immutable_int_array(
            indices,
            label="full_actuator_indices",
            ndim=1,
        )
        self._influences = _immutable_float_array(
            influences,
            label="influence_functions",
            ndim=3,
            finite=True,
        )
        self._max_abs_amplitude_m = _immutable_float_array(
            bounds,
            label="max_abs_amplitude_m",
            ndim=1,
            finite=True,
        )
        self._config_hash = component_config_hash(
            "dm_actuator_probe_basis",
            {
                "dm_hash": dm.config_hash,
                "coordinate_ids": selected,
                "coordinate_kind": "dm_command_opd",
                "coordinate_unit": "m_opd_equivalent",
                "full_actuator_indices": indices,
                "positive_correction_influences": influences,
                "max_abs_amplitude_m": bounds,
                "sign_convention": INTERACTION_SIGN_CONVENTION,
            },
        )

    @property
    def size(self) -> int:
        return len(self._coordinate_ids)

    @property
    def coordinate_ids(self) -> tuple[str, ...]:
        return self._coordinate_ids

    @property
    def names(self) -> tuple[str, ...]:
        return self._coordinate_ids

    @property
    def coordinate_kind(self) -> Literal["dm_command_opd"]:
        return "dm_command_opd"

    @property
    def coordinate_unit(self) -> Literal["m_opd_equivalent"]:
        return "m_opd_equivalent"

    @property
    def max_abs_amplitude_m(self) -> np.ndarray:
        return _immutable_float_array(
            self._max_abs_amplitude_m,
            label="max_abs_amplitude_m",
            ndim=1,
        )

    @property
    def dm(self) -> DeformableMirror:
        return self._dm

    @property
    def dm_hash(self) -> str:
        return self._dm.config_hash

    @property
    def config_hash(self) -> str:
        return self._config_hash

    @property
    def full_actuator_indices(self) -> np.ndarray:
        return _immutable_int_array(
            self._full_actuator_indices,
            label="full_actuator_indices",
            ndim=1,
        )

    @property
    def influence_functions(self) -> np.ndarray:
        return _immutable_float_array(
            self._influences,
            label="influence_functions",
            ndim=3,
        )

    def opd_m_for_coordinate(
        self,
        index: int,
        amplitude_m: float,
    ) -> np.ndarray:
        coordinate_index = _validated_index(index, self.size)
        amplitude = _finite_float(amplitude_m, label="amplitude_m")
        if abs(amplitude) > float(self._max_abs_amplitude_m[coordinate_index]):
            raise InteractionMatrixError(
                f"|amplitude_m| exceeds the DM stroke for actuator "
                f"{self._coordinate_ids[coordinate_index]!r}."
            )
        return _immutable_float_array(
            np.asarray(self._influences[coordinate_index]) * amplitude,
            label="DM actuator perturbation OPD",
            ndim=2,
            finite=True,
        )


@dataclass(frozen=True)
class InteractionMatrix:
    """Full-layout, unit-explicit calibrated wavefront-sensor response."""

    __hash_schema_id__ = INTERACTION_MATRIX_SCHEMA_ID

    matrix: np.ndarray
    row_valid: np.ndarray
    row_ids: tuple[str, ...]
    coordinate_ids: tuple[str, ...]
    coordinate_kind: CoordinateKind
    calibration_amplitude_m: float
    measurement_unit: MeasurementUnit
    coordinate_unit: CoordinateUnit
    matrix_unit: str
    singular_values: np.ndarray
    rank: int
    condition_proxy: float
    method: CalibrationMethod
    include_noise: bool
    repeat_count: int
    matrix_standard_error: np.ndarray | None
    sensor_config_hash: str
    geometry_hash: str
    detector_hash: str | None
    dm_hash: str | None
    calibration_hash: str
    provenance: Provenance

    def __post_init__(self) -> None:
        row_ids = _validated_ids(self.row_ids, label="row_ids")
        coordinate_ids = _validated_ids(
            self.coordinate_ids,
            label="coordinate_ids",
        )
        matrix = _immutable_float_array(
            self.matrix,
            label="matrix",
            ndim=2,
        )
        expected_shape = (len(row_ids), len(coordinate_ids))
        if matrix.shape != expected_shape:
            raise InteractionMatrixError(
                f"matrix shape {matrix.shape} does not match row/coordinate "
                f"layout {expected_shape}."
            )
        row_valid = _immutable_bool_array(
            self.row_valid,
            label="row_valid",
            ndim=1,
        )
        if row_valid.shape != (len(row_ids),):
            raise InteractionMatrixError(
                "row_valid length must match row_ids."
            )
        if not np.any(row_valid):
            raise InteractionMatrixError(
                "interaction matrix has no calibration-valid rows."
            )
        if not np.all(np.isfinite(matrix[row_valid])):
            raise InteractionMatrixError(
                "calibration-valid matrix rows must be finite."
            )
        if np.any(~np.isnan(matrix[~row_valid])):
            raise InteractionMatrixError(
                "every calibration-invalid matrix row must be entirely NaN."
            )
        if np.any(np.isinf(matrix)):
            raise InteractionMatrixError("matrix must not contain infinities.")

        coordinate_kind = cast(
            CoordinateKind,
            _literal(self.coordinate_kind, _COORDINATE_KINDS, "coordinate_kind"),
        )
        coordinate_unit = cast(
            CoordinateUnit,
            _literal(self.coordinate_unit, _COORDINATE_UNITS, "coordinate_unit"),
        )
        expected_coordinate_unit = _KIND_UNIT_PAIRS[coordinate_kind]
        if coordinate_unit != expected_coordinate_unit:
            raise InteractionMatrixError(
                f"coordinate_kind {coordinate_kind!r} requires coordinate_unit "
                f"{expected_coordinate_unit!r}."
            )
        measurement_unit = cast(
            MeasurementUnit,
            _literal(self.measurement_unit, _MEASUREMENT_UNITS, "measurement_unit"),
        )
        expected_matrix_unit = _matrix_unit(measurement_unit, coordinate_unit)
        if self.matrix_unit != expected_matrix_unit:
            raise InteractionMatrixError(
                f"matrix_unit must be {expected_matrix_unit!r}."
            )
        amplitude = _positive_finite_float(
            self.calibration_amplitude_m,
            label="calibration_amplitude_m",
        )
        method = cast(
            CalibrationMethod,
            _literal(self.method, _METHODS, "method"),
        )
        if not isinstance(self.include_noise, (bool, np.bool_)):
            raise InteractionMatrixError("include_noise must be a boolean.")
        include_noise = bool(self.include_noise)
        repeat_count = _positive_integer(self.repeat_count, label="repeat_count")
        standard_error = self.matrix_standard_error
        if include_noise:
            if repeat_count < 2:
                raise InteractionMatrixError(
                    "noisy calibration requires repeat_count >= 2."
                )
            if standard_error is None:
                raise InteractionMatrixError(
                    "noisy calibration requires matrix_standard_error."
                )
            standard_error = _immutable_float_array(
                standard_error,
                label="matrix_standard_error",
                ndim=2,
            )
            if standard_error.shape != matrix.shape:
                raise InteractionMatrixError(
                    "matrix_standard_error must have the same shape as matrix."
                )
            if (
                not np.all(np.isfinite(standard_error[row_valid]))
                or np.any(standard_error[row_valid] < 0.0)
            ):
                raise InteractionMatrixError(
                    "valid-row standard errors must be finite and non-negative."
                )
            if np.any(~np.isnan(standard_error[~row_valid])):
                raise InteractionMatrixError(
                    "invalid-row standard errors must be entirely NaN."
                )
            if np.any(np.isinf(standard_error)):
                raise InteractionMatrixError(
                    "matrix_standard_error must not contain infinities."
                )
        else:
            if repeat_count != 1:
                raise InteractionMatrixError(
                    "deterministic calibration requires repeat_count == 1."
                )
            if standard_error is not None:
                raise InteractionMatrixError(
                    "deterministic calibration must not store matrix_standard_error."
                )

        try:
            zero_columns = all_zero_columns(matrix, row_valid)
            diagnostics = interaction_diagnostics(matrix, row_valid)
        except InteractionDiagnosticsError as exc:
            raise InteractionMatrixError(str(exc)) from exc
        if np.any(zero_columns):
            identifiers = [
                identifier
                for identifier, is_zero in zip(
                    coordinate_ids,
                    zero_columns,
                    strict=True,
                )
                if is_zero
            ]
            raise InteractionMatrixError(
                f"interaction matrix contains all-zero columns: {identifiers}."
            )
        singular_values = _immutable_float_array(
            self.singular_values,
            label="singular_values",
            ndim=1,
            finite=True,
        )
        if singular_values.shape != diagnostics.singular_values.shape or not np.allclose(
            singular_values,
            diagnostics.singular_values,
            rtol=1.0e-12,
            atol=0.0,
        ):
            raise InteractionMatrixError(
                "singular_values do not match the calibration-valid matrix."
            )
        rank = _nonnegative_integer(self.rank, label="rank")
        if rank != diagnostics.rank:
            raise InteractionMatrixError(
                "rank does not match the calibration-valid matrix."
            )
        condition = _condition_float(self.condition_proxy)
        if not _same_condition(condition, diagnostics.condition_proxy):
            raise InteractionMatrixError(
                "condition_proxy does not match the calibration-valid matrix."
            )

        sensor_hash = _nonempty_string(
            self.sensor_config_hash,
            label="sensor_config_hash",
        )
        geometry_hash = _nonempty_string(self.geometry_hash, label="geometry_hash")
        detector_hash = _optional_hash(self.detector_hash, label="detector_hash")
        dm_hash = _optional_hash(self.dm_hash, label="dm_hash")
        if coordinate_kind == "dm_command_opd" and dm_hash is None:
            raise InteractionMatrixError(
                "dm_command_opd interaction matrices require dm_hash."
            )
        if not isinstance(self.provenance, Provenance):
            raise InteractionMatrixError("provenance must be a Provenance.")
        calibration_hash = _nonempty_string(
            self.calibration_hash,
            label="calibration_hash",
        )
        expected_hash = _interaction_matrix_hash_from_values(
            matrix=matrix,
            row_valid=row_valid,
            row_ids=row_ids,
            coordinate_ids=coordinate_ids,
            coordinate_kind=coordinate_kind,
            calibration_amplitude_m=amplitude,
            measurement_unit=measurement_unit,
            coordinate_unit=coordinate_unit,
            matrix_unit=expected_matrix_unit,
            singular_values=singular_values,
            rank=rank,
            condition_proxy=condition,
            method=method,
            include_noise=include_noise,
            repeat_count=repeat_count,
            matrix_standard_error=standard_error,
            sensor_config_hash=sensor_hash,
            geometry_hash=geometry_hash,
            detector_hash=detector_hash,
            dm_hash=dm_hash,
            provenance=self.provenance,
        )
        if calibration_hash != expected_hash:
            raise InteractionMatrixError(
                "calibration_hash does not match interaction-matrix content."
            )

        object.__setattr__(self, "matrix", matrix)
        object.__setattr__(self, "row_valid", row_valid)
        object.__setattr__(self, "row_ids", row_ids)
        object.__setattr__(self, "coordinate_ids", coordinate_ids)
        object.__setattr__(self, "coordinate_kind", coordinate_kind)
        object.__setattr__(self, "calibration_amplitude_m", amplitude)
        object.__setattr__(self, "measurement_unit", measurement_unit)
        object.__setattr__(self, "coordinate_unit", coordinate_unit)
        object.__setattr__(self, "matrix_unit", expected_matrix_unit)
        object.__setattr__(self, "singular_values", singular_values)
        object.__setattr__(self, "rank", rank)
        object.__setattr__(self, "condition_proxy", condition)
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "include_noise", include_noise)
        object.__setattr__(self, "repeat_count", repeat_count)
        object.__setattr__(self, "matrix_standard_error", standard_error)
        object.__setattr__(self, "sensor_config_hash", sensor_hash)
        object.__setattr__(self, "geometry_hash", geometry_hash)
        object.__setattr__(self, "detector_hash", detector_hash)
        object.__setattr__(self, "dm_hash", dm_hash)
        object.__setattr__(self, "calibration_hash", calibration_hash)

    @property
    def config_hash(self) -> str:
        return self.calibration_hash

    @property
    def matrix_hash(self) -> str:
        return self.calibration_hash

    def to_record(self) -> dict[str, object]:
        """Serialize every typed field into a deterministic plain record."""

        return {
            "schema_id": INTERACTION_MATRIX_SCHEMA_ID,
            "matrix": self.matrix.tolist(),
            "row_valid": self.row_valid.tolist(),
            "row_ids": list(self.row_ids),
            "coordinate_ids": list(self.coordinate_ids),
            "coordinate_kind": self.coordinate_kind,
            "calibration_amplitude_m": self.calibration_amplitude_m,
            "measurement_unit": self.measurement_unit,
            "coordinate_unit": self.coordinate_unit,
            "matrix_unit": self.matrix_unit,
            "singular_values": self.singular_values.tolist(),
            "rank": self.rank,
            "condition_proxy": self.condition_proxy,
            "method": self.method,
            "include_noise": self.include_noise,
            "repeat_count": self.repeat_count,
            "matrix_standard_error": (
                None
                if self.matrix_standard_error is None
                else self.matrix_standard_error.tolist()
            ),
            "sensor_config_hash": self.sensor_config_hash,
            "geometry_hash": self.geometry_hash,
            "detector_hash": self.detector_hash,
            "dm_hash": self.dm_hash,
            "calibration_hash": self.calibration_hash,
            "provenance": self.provenance.to_record(),
        }

    @classmethod
    def from_record(cls, record: Mapping[str, object]) -> InteractionMatrix:
        """Deserialize a record and revalidate all identities and diagnostics."""

        if not isinstance(record, Mapping):
            raise InteractionMatrixError("record must be a mapping.")
        expected_fields = {
            "schema_id",
            "matrix",
            "row_valid",
            "row_ids",
            "coordinate_ids",
            "coordinate_kind",
            "calibration_amplitude_m",
            "measurement_unit",
            "coordinate_unit",
            "matrix_unit",
            "singular_values",
            "rank",
            "condition_proxy",
            "method",
            "include_noise",
            "repeat_count",
            "matrix_standard_error",
            "sensor_config_hash",
            "geometry_hash",
            "detector_hash",
            "dm_hash",
            "calibration_hash",
            "provenance",
        }
        if set(record) != expected_fields:
            missing = sorted(expected_fields - set(record))
            extra = sorted(set(record) - expected_fields)
            raise InteractionMatrixError(
                f"interaction-matrix record fields differ: missing={missing}, "
                f"extra={extra}."
            )
        if record["schema_id"] != INTERACTION_MATRIX_SCHEMA_ID:
            raise InteractionMatrixError("unsupported interaction-matrix schema_id.")
        stderr_record = record["matrix_standard_error"]
        provenance_record = record["provenance"]
        try:
            provenance = Provenance.from_record(cast(Mapping[str, object], provenance_record))
        except (TypeError, ValueError) as exc:
            raise InteractionMatrixError(f"invalid provenance record: {exc}") from exc
        try:
            return cls(
                matrix=np.asarray(record["matrix"], dtype=float),
                row_valid=_record_boolean_vector(
                    record["row_valid"],
                    label="row_valid",
                ),
                row_ids=tuple(cast(Sequence[str], record["row_ids"])),
                coordinate_ids=tuple(
                    cast(Sequence[str], record["coordinate_ids"])
                ),
                coordinate_kind=cast(CoordinateKind, record["coordinate_kind"]),
                calibration_amplitude_m=cast(float, record["calibration_amplitude_m"]),
                measurement_unit=cast(MeasurementUnit, record["measurement_unit"]),
                coordinate_unit=cast(CoordinateUnit, record["coordinate_unit"]),
                matrix_unit=cast(str, record["matrix_unit"]),
                singular_values=np.asarray(record["singular_values"], dtype=float),
                rank=cast(int, record["rank"]),
                condition_proxy=cast(float, record["condition_proxy"]),
                method=cast(CalibrationMethod, record["method"]),
                include_noise=cast(bool, record["include_noise"]),
                repeat_count=cast(int, record["repeat_count"]),
                matrix_standard_error=(
                    None
                    if stderr_record is None
                    else np.asarray(stderr_record, dtype=float)
                ),
                sensor_config_hash=cast(str, record["sensor_config_hash"]),
                geometry_hash=cast(str, record["geometry_hash"]),
                detector_hash=cast(str | None, record["detector_hash"]),
                dm_hash=cast(str | None, record["dm_hash"]),
                calibration_hash=cast(str, record["calibration_hash"]),
                provenance=provenance,
            )
        except (TypeError, ValueError) as exc:
            if isinstance(exc, InteractionMatrixError):
                raise
            raise InteractionMatrixError(
                f"invalid interaction-matrix record: {exc}"
            ) from exc


def calibrate_interaction_matrix(
    probe_basis: ProbeBasis,
    sensor: WavefrontSensor,
    amplitude_m: float,
    *,
    random_streams: RandomStreams,
    method: CalibrationMethod = "central",
    include_noise: bool = False,
    repeats: int = 1,
) -> InteractionMatrix:
    """Calibrate one full-layout interaction matrix through a shared WFS API."""

    basis_contract = _validated_probe_basis(probe_basis)
    amplitude = _positive_finite_float(amplitude_m, label="amplitude_m")
    if np.any(amplitude > basis_contract.max_abs_amplitude_m):
        offenders = [
            identifier
            for identifier, bound in zip(
                basis_contract.coordinate_ids,
                basis_contract.max_abs_amplitude_m,
                strict=True,
            )
            if amplitude > bound
        ]
        raise InteractionMatrixError(
            f"amplitude_m exceeds the probe-basis bound for {offenders}."
        )
    resolved_method = cast(
        CalibrationMethod,
        _literal(method, _METHODS, "method"),
    )
    if not isinstance(include_noise, (bool, np.bool_)):
        raise InteractionMatrixError("include_noise must be a boolean.")
    noisy = bool(include_noise)
    repeat_count = _positive_integer(repeats, label="repeats")
    if noisy and repeat_count < 2:
        raise InteractionMatrixError(
            "include_noise=True requires repeats >= 2."
        )
    if not noisy and repeat_count != 1:
        raise InteractionMatrixError(
            "include_noise=False requires repeats == 1."
        )

    sensor_config_hash, row_ids = _validated_sensor_contract(sensor)
    root_seed, derivation_scheme = _validated_random_streams(random_streams)

    # Every bound and spatial perturbation is materialized before the first
    # sensor call.  Bad amplitudes or basis maps therefore fail atomically.
    positive_maps: list[np.ndarray] = []
    negative_maps: list[np.ndarray] = []
    probe_shape: tuple[int, int] | None = None
    for index, coordinate_id in enumerate(basis_contract.coordinate_ids):
        positive = _probe_map(
            probe_basis,
            index,
            amplitude,
            coordinate_id=coordinate_id,
        )
        if probe_shape is None:
            probe_shape = cast(tuple[int, int], positive.shape)
        elif positive.shape != probe_shape:
            raise InteractionMatrixError(
                "all probe-basis OPD maps must have the same shape."
            )
        positive_maps.append(positive)
        if resolved_method == "central":
            negative = _probe_map(
                probe_basis,
                index,
                -amplitude,
                coordinate_id=coordinate_id,
            )
            if negative.shape != probe_shape:
                raise InteractionMatrixError(
                    "positive and negative probe maps must have matching shapes."
                )
            negative_maps.append(negative)
    if probe_shape is None:  # pragma: no cover - nonempty basis validated above
        raise InteractionMatrixError("probe_basis must contain at least one coordinate.")

    probe_hash = _probe_basis_hash(
        probe_basis,
        basis_contract,
        positive_maps,
        amplitude,
    )
    geometry_hash = _sensor_geometry_hash(
        sensor,
        sensor_config_hash=sensor_config_hash,
        row_ids=row_ids,
        probe_shape=probe_shape,
    )
    detector_hash = _sensor_detector_hash(sensor)
    dm_hash = _basis_dm_hash(
        probe_basis,
        basis_contract.coordinate_kind,
        probe_basis_hash=probe_hash,
    )
    context_hash = component_config_hash(
        "interaction_matrix_calibration_context",
        {
            "probe_basis_hash": probe_hash,
            "sensor_config_hash": sensor_config_hash,
            "geometry_hash": geometry_hash,
            "detector_hash": detector_hash,
            "dm_hash": dm_hash,
            "amplitude_m": amplitude,
            "method": resolved_method,
            "include_noise": noisy,
            "repeat_count": repeat_count,
            "sign_convention": INTERACTION_SIGN_CONVENTION,
        },
    )

    row_count = len(row_ids)
    column_count = basis_contract.size
    derivative_samples = np.full(
        (repeat_count, row_count, column_count),
        np.nan,
        dtype=float,
    )
    sample_valid = np.zeros(
        (repeat_count, row_count, column_count),
        dtype=bool,
    )
    measurement_unit: MeasurementUnit | None = None
    stream_references: list[str] = []

    reference_values: np.ndarray | None = None
    reference_valid: np.ndarray | None = None
    if resolved_method == "forward":
        reference_key = (
            "interaction_matrix",
            context_hash,
            "reference",
            0,
        )
        reference_streams = _scoped_streams(random_streams, reference_key)
        stream_references.append(_scope_stream_reference(reference_streams))
        reference = _measure(
            sensor,
            np.zeros(probe_shape, dtype=float),
            random_streams=reference_streams,
            include_noise=False,
            row_ids=row_ids,
            expected_sensor_hash=sensor_config_hash,
            expected_unit=None,
            sample_label="noise-free forward reference",
        )
        measurement_unit = reference.vector.measurement_unit
        reference_values = np.asarray(reference.vector.values, dtype=float)
        reference_valid = (
            np.asarray(reference.vector.valid_rows, dtype=bool)
            & np.isfinite(reference_values)
        )

    for repeat_index in range(repeat_count):
        for column_index, coordinate_id in enumerate(
            basis_contract.coordinate_ids
        ):
            plus_key = (
                "interaction_matrix",
                context_hash,
                coordinate_id,
                "plus",
                repeat_index,
            )
            plus_streams = _scoped_streams(random_streams, plus_key)
            stream_references.append(_scope_stream_reference(plus_streams))
            plus = _measure(
                sensor,
                positive_maps[column_index],
                random_streams=plus_streams,
                include_noise=noisy,
                row_ids=row_ids,
                expected_sensor_hash=sensor_config_hash,
                expected_unit=measurement_unit,
                sample_label=(
                    f"coordinate {coordinate_id!r} plus, repeat {repeat_index}"
                ),
            )
            if measurement_unit is None:
                measurement_unit = plus.vector.measurement_unit
            plus_values = np.asarray(plus.vector.values, dtype=float)
            plus_valid = (
                np.asarray(plus.vector.valid_rows, dtype=bool)
                & np.isfinite(plus_values)
            )

            if resolved_method == "central":
                minus_key = (
                    "interaction_matrix",
                    context_hash,
                    coordinate_id,
                    "minus",
                    repeat_index,
                )
                minus_streams = _scoped_streams(random_streams, minus_key)
                stream_references.append(_scope_stream_reference(minus_streams))
                minus = _measure(
                    sensor,
                    negative_maps[column_index],
                    random_streams=minus_streams,
                    include_noise=noisy,
                    row_ids=row_ids,
                    expected_sensor_hash=sensor_config_hash,
                    expected_unit=measurement_unit,
                    sample_label=(
                        f"coordinate {coordinate_id!r} minus, repeat "
                        f"{repeat_index}"
                    ),
                )
                minus_values = np.asarray(minus.vector.values, dtype=float)
                minus_valid = (
                    np.asarray(minus.vector.valid_rows, dtype=bool)
                    & np.isfinite(minus_values)
                )
                valid = plus_valid & minus_valid
                values = (plus_values - minus_values) / (2.0 * amplitude)
            else:
                assert reference_values is not None
                assert reference_valid is not None
                valid = plus_valid & reference_valid
                values = (plus_values - reference_values) / amplitude
            values = np.asarray(values, dtype=float)
            valid &= np.isfinite(values)
            derivative_samples[repeat_index, valid, column_index] = values[valid]
            sample_valid[repeat_index, :, column_index] = valid

    if measurement_unit is None:  # pragma: no cover - at least one sample exists
        raise InteractionMatrixError("sensor returned no measurement unit.")
    row_valid = np.all(sample_valid, axis=(0, 2))
    if not np.any(row_valid):
        raise InteractionMatrixError(
            "calibration produced no rows valid across every probe sample."
        )
    matrix = np.full((row_count, column_count), np.nan, dtype=float)
    matrix[row_valid] = np.mean(derivative_samples[:, row_valid, :], axis=0)
    standard_error: np.ndarray | None = None
    if noisy:
        standard_error = np.full_like(matrix, np.nan)
        standard_error[row_valid] = (
            np.std(
                derivative_samples[:, row_valid, :],
                axis=0,
                ddof=1,
            )
            / math.sqrt(repeat_count)
        )
    try:
        zero_columns = all_zero_columns(matrix, row_valid)
        diagnostics = interaction_diagnostics(matrix, row_valid)
    except InteractionDiagnosticsError as exc:
        raise InteractionMatrixError(str(exc)) from exc
    if np.any(zero_columns):
        zero_ids = [
            identifier
            for identifier, is_zero in zip(
                basis_contract.coordinate_ids,
                zero_columns,
                strict=True,
            )
            if is_zero
        ]
        raise InteractionMatrixError(
            f"calibration produced all-zero response columns: {zero_ids}."
        )

    provenance = Provenance(
        source_class="synthetic_assumed",
        source_note=(
            "Interaction matrix calibrated from positive residual-aberration "
            "OPD probes with explicit scoped random streams."
        ),
        references=tuple(
            [
                f"sign_convention={INTERACTION_SIGN_CONVENTION}",
                f"probe_basis_hash={probe_hash}",
                f"sensor_config_hash={sensor_config_hash}",
                f"geometry_hash={geometry_hash}",
                f"detector_hash={detector_hash}",
                f"dm_hash={dm_hash}",
                f"random_root_seed={root_seed}",
                f"random_derivation_scheme_id={derivation_scheme}",
                "random_scope=calibration",
                f"method={resolved_method}",
                f"include_noise={noisy}",
                f"repeat_count={repeat_count}",
            ]
            + stream_references
        ),
    )
    matrix_unit = _matrix_unit(measurement_unit, basis_contract.coordinate_unit)
    calibration_hash = _interaction_matrix_hash_from_values(
        matrix=matrix,
        row_valid=row_valid,
        row_ids=row_ids,
        coordinate_ids=basis_contract.coordinate_ids,
        coordinate_kind=basis_contract.coordinate_kind,
        calibration_amplitude_m=amplitude,
        measurement_unit=measurement_unit,
        coordinate_unit=basis_contract.coordinate_unit,
        matrix_unit=matrix_unit,
        singular_values=diagnostics.singular_values,
        rank=diagnostics.rank,
        condition_proxy=diagnostics.condition_proxy,
        method=resolved_method,
        include_noise=noisy,
        repeat_count=repeat_count,
        matrix_standard_error=standard_error,
        sensor_config_hash=sensor_config_hash,
        geometry_hash=geometry_hash,
        detector_hash=detector_hash,
        dm_hash=dm_hash,
        provenance=provenance,
    )
    return InteractionMatrix(
        matrix=matrix,
        row_valid=row_valid,
        row_ids=row_ids,
        coordinate_ids=basis_contract.coordinate_ids,
        coordinate_kind=basis_contract.coordinate_kind,
        calibration_amplitude_m=amplitude,
        measurement_unit=measurement_unit,
        coordinate_unit=basis_contract.coordinate_unit,
        matrix_unit=matrix_unit,
        singular_values=diagnostics.singular_values,
        rank=diagnostics.rank,
        condition_proxy=diagnostics.condition_proxy,
        method=resolved_method,
        include_noise=noisy,
        repeat_count=repeat_count,
        matrix_standard_error=standard_error,
        sensor_config_hash=sensor_config_hash,
        geometry_hash=geometry_hash,
        detector_hash=detector_hash,
        dm_hash=dm_hash,
        calibration_hash=calibration_hash,
        provenance=provenance,
    )


def interaction_matrix_hash(interaction_matrix: InteractionMatrix) -> str:
    """Recompute the canonical content hash for an interaction matrix."""

    if not isinstance(interaction_matrix, InteractionMatrix):
        raise InteractionMatrixError(
            "interaction_matrix must be an InteractionMatrix."
        )
    return _interaction_matrix_hash_from_values(
        matrix=interaction_matrix.matrix,
        row_valid=interaction_matrix.row_valid,
        row_ids=interaction_matrix.row_ids,
        coordinate_ids=interaction_matrix.coordinate_ids,
        coordinate_kind=interaction_matrix.coordinate_kind,
        calibration_amplitude_m=interaction_matrix.calibration_amplitude_m,
        measurement_unit=interaction_matrix.measurement_unit,
        coordinate_unit=interaction_matrix.coordinate_unit,
        matrix_unit=interaction_matrix.matrix_unit,
        singular_values=interaction_matrix.singular_values,
        rank=interaction_matrix.rank,
        condition_proxy=interaction_matrix.condition_proxy,
        method=interaction_matrix.method,
        include_noise=interaction_matrix.include_noise,
        repeat_count=interaction_matrix.repeat_count,
        matrix_standard_error=interaction_matrix.matrix_standard_error,
        sensor_config_hash=interaction_matrix.sensor_config_hash,
        geometry_hash=interaction_matrix.geometry_hash,
        detector_hash=interaction_matrix.detector_hash,
        dm_hash=interaction_matrix.dm_hash,
        provenance=interaction_matrix.provenance,
    )


@dataclass(frozen=True)
class _BasisContract:
    size: int
    coordinate_ids: tuple[str, ...]
    coordinate_kind: CoordinateKind
    coordinate_unit: CoordinateUnit
    max_abs_amplitude_m: np.ndarray


def _validated_probe_basis(probe_basis: object) -> _BasisContract:
    required = (
        "size",
        "coordinate_ids",
        "coordinate_kind",
        "coordinate_unit",
        "max_abs_amplitude_m",
        "opd_m_for_coordinate",
    )
    missing = [name for name in required if not hasattr(probe_basis, name)]
    if missing:
        raise InteractionMatrixError(
            f"probe_basis does not implement required members: {missing}."
        )
    size = _positive_integer(getattr(probe_basis, "size"), label="probe_basis.size")
    coordinate_ids = _validated_ids(
        getattr(probe_basis, "coordinate_ids"),
        label="probe_basis.coordinate_ids",
    )
    if len(coordinate_ids) != size:
        raise InteractionMatrixError(
            "probe_basis.size must equal the coordinate ID count."
        )
    coordinate_kind = cast(
        CoordinateKind,
        _literal(
            getattr(probe_basis, "coordinate_kind"),
            _COORDINATE_KINDS,
            "probe_basis.coordinate_kind",
        ),
    )
    coordinate_unit = cast(
        CoordinateUnit,
        _literal(
            getattr(probe_basis, "coordinate_unit"),
            _COORDINATE_UNITS,
            "probe_basis.coordinate_unit",
        ),
    )
    if _KIND_UNIT_PAIRS[coordinate_kind] != coordinate_unit:
        raise InteractionMatrixError(
            "probe_basis coordinate kind and unit are inconsistent."
        )
    raw_bounds = getattr(probe_basis, "max_abs_amplitude_m")
    if not isinstance(raw_bounds, np.ndarray):
        raise InteractionMatrixError(
            "probe_basis.max_abs_amplitude_m must be a numpy.ndarray."
        )
    bounds = _validated_bounds(raw_bounds, size)
    if not callable(getattr(probe_basis, "opd_m_for_coordinate")):
        raise InteractionMatrixError(
            "probe_basis.opd_m_for_coordinate must be callable."
        )
    return _BasisContract(
        size=size,
        coordinate_ids=coordinate_ids,
        coordinate_kind=coordinate_kind,
        coordinate_unit=coordinate_unit,
        max_abs_amplitude_m=bounds,
    )


def _probe_map(
    probe_basis: ProbeBasis,
    index: int,
    amplitude_m: float,
    *,
    coordinate_id: str,
) -> np.ndarray:
    try:
        value = probe_basis.opd_m_for_coordinate(index, amplitude_m)
    except Exception as exc:
        if isinstance(exc, InteractionMatrixError):
            raise
        raise InteractionMatrixError(
            f"probe {coordinate_id!r} failed to produce OPD: {exc}"
        ) from exc
    result = _immutable_float_array(
        value,
        label=f"probe OPD for {coordinate_id!r}",
        ndim=2,
        finite=True,
    )
    return result


def _validated_sensor_contract(sensor: object) -> tuple[str, tuple[str, ...]]:
    if not callable(getattr(sensor, "measure", None)):
        raise InteractionMatrixError("sensor must implement measure().")
    sensor_hash = _nonempty_string(
        getattr(sensor, "config_hash", None),
        label="sensor.config_hash",
    )
    row_ids = _validated_ids(
        getattr(sensor, "row_ids", ()),
        label="sensor.row_ids",
    )
    return sensor_hash, row_ids


def _validated_random_streams(random_streams: object) -> tuple[int, str]:
    if random_streams is None:
        raise InteractionMatrixError("random_streams is required.")
    root_seed = getattr(random_streams, "root_seed", None)
    if type(root_seed) is not int or root_seed < 0:
        raise InteractionMatrixError(
            "random_streams.root_seed must be a non-negative integer."
        )
    scheme = _nonempty_string(
        getattr(random_streams, "derivation_scheme_id", None),
        label="random_streams.derivation_scheme_id",
    )
    for name in ("scoped", "stream_id"):
        if not callable(getattr(random_streams, name, None)):
            raise InteractionMatrixError(
                f"random_streams must implement {name}()."
            )
    return root_seed, scheme


def _scoped_streams(
    random_streams: RandomStreams,
    key: tuple[str | int, ...],
) -> RandomStreams:
    try:
        scoped = random_streams.scoped("calibration", key=key)
    except Exception as exc:
        raise InteractionMatrixError(
            f"random_streams could not create calibration scope: {exc}"
        ) from exc
    _validated_random_streams(scoped)
    return scoped


def _scope_stream_reference(random_streams: RandomStreams) -> str:
    try:
        identifier = random_streams.stream_id("calibration")
    except Exception as exc:
        raise InteractionMatrixError(
            f"calibration scope could not identify its stream: {exc}"
        ) from exc
    return f"calibration_stream_id={_nonempty_string(identifier, label='stream ID')}"


def _measure(
    sensor: WavefrontSensor,
    opd_m: np.ndarray,
    *,
    random_streams: RandomStreams,
    include_noise: bool,
    row_ids: tuple[str, ...],
    expected_sensor_hash: str,
    expected_unit: MeasurementUnit | None,
    sample_label: str,
) -> WfsMeasurement:
    try:
        measurement = sensor.measure(
            opd_m,
            random_streams=random_streams,
            include_noise=include_noise,
        )
    except Exception as exc:
        raise InteractionMatrixError(
            f"sensor measurement failed for {sample_label}: {exc}"
        ) from exc
    if not isinstance(measurement, WfsMeasurement):
        raise InteractionMatrixError(
            f"sensor returned a non-WfsMeasurement for {sample_label}."
        )
    current_hash = _nonempty_string(
        getattr(sensor, "config_hash", None),
        label="sensor.config_hash",
    )
    if current_hash != expected_sensor_hash:
        raise InteractionMatrixError(
            "sensor.config_hash changed during interaction-matrix calibration."
        )
    current_row_ids = _validated_ids(
        getattr(sensor, "row_ids", ()),
        label="sensor.row_ids",
    )
    if current_row_ids != row_ids:
        raise InteractionMatrixError(
            "sensor.row_ids changed during interaction-matrix calibration."
        )
    vector = measurement.vector
    if vector.row_ids != row_ids:
        raise InteractionMatrixError(
            f"measurement row IDs changed or were reordered for {sample_label}."
        )
    if vector.values.shape != (len(row_ids),) or vector.valid_rows.shape != (
        len(row_ids),
    ):
        raise InteractionMatrixError(
            f"measurement row shape is inconsistent for {sample_label}."
        )
    if expected_unit is not None and vector.measurement_unit != expected_unit:
        raise InteractionMatrixError(
            f"measurement unit changed for {sample_label}."
        )
    return measurement


def _probe_basis_hash(
    probe_basis: ProbeBasis,
    contract: _BasisContract,
    positive_maps: list[np.ndarray],
    amplitude_m: float,
) -> str:
    declared = getattr(probe_basis, "config_hash", None)
    declared_hash = (
        _nonempty_string(declared, label="probe_basis.config_hash")
        if declared is not None
        else None
    )
    return component_config_hash(
        "calibration_probe_basis_content",
        {
            "declared_config_hash": declared_hash,
            "coordinate_ids": contract.coordinate_ids,
            "coordinate_kind": contract.coordinate_kind,
            "coordinate_unit": contract.coordinate_unit,
            "max_abs_amplitude_m": contract.max_abs_amplitude_m,
            "positive_probe_maps_at_amplitude": np.stack(positive_maps, axis=0),
            "amplitude_m": amplitude_m,
        },
    )


def _sensor_geometry_hash(
    sensor: object,
    *,
    sensor_config_hash: str,
    row_ids: tuple[str, ...],
    probe_shape: tuple[int, int],
) -> str:
    direct = getattr(sensor, "geometry_hash", None)
    if direct is not None:
        return _nonempty_string(direct, label="sensor.geometry_hash")
    geometry = getattr(sensor, "geometry", None)
    if geometry is not None:
        value = getattr(geometry, "geometry_hash", None)
        if value is not None:
            return _nonempty_string(value, label="sensor.geometry.geometry_hash")
    calibration = getattr(sensor, "calibration", None)
    if calibration is not None:
        calibration_geometry = getattr(calibration, "geometry", None)
        value = getattr(calibration_geometry, "geometry_hash", None)
        if value is not None:
            return _nonempty_string(
                value,
                label="sensor.calibration.geometry.geometry_hash",
            )
    return stable_hash(
        {
            "context": "structural_sensor_row_geometry_fallback",
            "sensor_config_hash": sensor_config_hash,
            "row_ids": row_ids,
            "probe_shape": probe_shape,
        },
        namespace="wavefront_sensor_geometry_context",
    )


def _sensor_detector_hash(sensor: object) -> str | None:
    direct = getattr(sensor, "detector_hash", None)
    if direct is not None:
        return _nonempty_string(direct, label="sensor.detector_hash")
    realization = getattr(sensor, "detector_realization", None)
    calibration = getattr(sensor, "calibration", None)
    if realization is None and not _looks_detector_calibration(calibration):
        return None
    payload: dict[str, object] = {}
    if realization is not None:
        for source_name, payload_name in (
            ("realization_hash", "realization_hash"),
            ("config_hash", "realization_config_hash"),
        ):
            value = getattr(realization, source_name, None)
            if value is not None:
                payload[payload_name] = _nonempty_string(
                    value,
                    label=f"sensor.detector_realization.{source_name}",
                )
    if calibration is not None:
        for source_name, payload_name in (
            ("detector_realization_hash", "calibration_realization_hash"),
            ("config_hash", "sensor_calibration_hash"),
        ):
            value = getattr(calibration, source_name, None)
            if value is not None:
                payload[payload_name] = _nonempty_string(
                    value,
                    label=f"sensor.calibration.{source_name}",
                )
        detector_config = getattr(calibration, "detector_config", None)
        if detector_config is not None:
            payload["detector_config"] = detector_config
        detector_sampling = getattr(calibration, "detector_sampling", None)
        sampling_hash = getattr(detector_sampling, "sampling_hash", None)
        if sampling_hash is not None:
            payload["detector_sampling_hash"] = _nonempty_string(
                sampling_hash,
                label="sensor.calibration.detector_sampling.sampling_hash",
            )
    return component_config_hash("wavefront_sensor_detector_context", payload)


def _looks_detector_calibration(calibration: object) -> bool:
    if calibration is None:
        return False
    return any(
        hasattr(calibration, name)
        for name in (
            "detector_realization_hash",
            "detector_config",
            "detector_sampling",
        )
    )


def _basis_dm_hash(
    probe_basis: object,
    coordinate_kind: CoordinateKind,
    *,
    probe_basis_hash: str,
) -> str | None:
    value = getattr(probe_basis, "dm_hash", None)
    if coordinate_kind == "dm_command_opd":
        if value is not None:
            return _nonempty_string(value, label="probe_basis.dm_hash")
        # ``dm_hash`` is deliberately not an extra member of the public
        # ProbeBasis protocol.  A structural implementation can therefore
        # still calibrate DM-command coordinates; its complete, map-bearing
        # basis hash becomes an explicitly namespaced DM-probe context hash.
        return component_config_hash(
            "structural_dm_probe_context",
            {"probe_basis_hash": probe_basis_hash},
        )
    if value is not None:
        raise InteractionMatrixError(
            "modal probe_basis must not declare a dm_hash."
        )
    return None


def _interaction_matrix_hash_from_values(
    *,
    matrix: np.ndarray,
    row_valid: np.ndarray,
    row_ids: tuple[str, ...],
    coordinate_ids: tuple[str, ...],
    coordinate_kind: CoordinateKind,
    calibration_amplitude_m: float,
    measurement_unit: MeasurementUnit,
    coordinate_unit: CoordinateUnit,
    matrix_unit: str,
    singular_values: np.ndarray,
    rank: int,
    condition_proxy: float,
    method: CalibrationMethod,
    include_noise: bool,
    repeat_count: int,
    matrix_standard_error: np.ndarray | None,
    sensor_config_hash: str,
    geometry_hash: str,
    detector_hash: str | None,
    dm_hash: str | None,
    provenance: Provenance,
) -> str:
    return component_config_hash(
        "interaction_matrix_calibration",
        {
            "schema_id": INTERACTION_MATRIX_SCHEMA_ID,
            "sign_convention": INTERACTION_SIGN_CONVENTION,
            "matrix": matrix,
            "row_valid": row_valid,
            "row_ids": row_ids,
            "row_layout_hash": calibration_rows_hash(
                row_ids,
                valid_rows=row_valid,
            ),
            "coordinate_ids": coordinate_ids,
            "coordinate_kind": coordinate_kind,
            "coordinate_unit": coordinate_unit,
            "coordinate_layout_hash": command_coordinates_hash(
                coordinate_ids,
                coordinate_kind=coordinate_kind,
                coordinate_unit=coordinate_unit,
            ),
            "calibration_amplitude_m": calibration_amplitude_m,
            "measurement_unit": measurement_unit,
            "matrix_unit": matrix_unit,
            "singular_values": singular_values,
            "rank": rank,
            "condition_proxy": condition_proxy,
            "method": method,
            "include_noise": include_noise,
            "repeat_count": repeat_count,
            "matrix_standard_error": matrix_standard_error,
            "sensor_config_hash": sensor_config_hash,
            "geometry_hash": geometry_hash,
            "detector_hash": detector_hash,
            "dm_hash": dm_hash,
            "provenance": provenance,
        },
    )


def _matrix_unit(measurement_unit: str, coordinate_unit: str) -> str:
    return f"{measurement_unit} / {coordinate_unit}"


def _validated_bounds(value: object, size: int) -> np.ndarray:
    if isinstance(value, np.ndarray):
        if (
            value.ndim != 1
            or np.issubdtype(value.dtype, np.bool_)
            or not np.issubdtype(value.dtype, np.number)
            or np.issubdtype(value.dtype, np.complexfloating)
        ):
            raise InteractionMatrixError(
                "max_abs_amplitude_m must be a one-dimensional real array."
            )
        bounds = np.asarray(value, dtype=float)
        if bounds.shape != (size,):
            raise InteractionMatrixError(
                "max_abs_amplitude_m length must match the basis size."
            )
    else:
        bound = _positive_float_allow_infinity(
            value,
            label="max_abs_amplitude_m",
        )
        bounds = np.full(size, bound, dtype=float)
    if np.any(np.isnan(bounds)) or np.any(bounds <= 0.0) or np.any(np.isneginf(bounds)):
        raise InteractionMatrixError(
            "every max_abs_amplitude_m bound must be positive and not NaN."
        )
    return _immutable_float_array(
        bounds,
        label="max_abs_amplitude_m",
        ndim=1,
    )


def _validated_ids(value: object, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise InteractionMatrixError(f"{label} must be a tuple of identifiers.")
    result = value
    if not result:
        raise InteractionMatrixError(f"{label} must not be empty.")
    if any(
        not isinstance(identifier, str)
        or not identifier
        or identifier.strip() != identifier
        for identifier in result
    ):
        raise InteractionMatrixError(
            f"{label} must contain non-empty strings without surrounding whitespace."
        )
    if len(result) != len(set(result)):
        raise InteractionMatrixError(f"{label} must not contain duplicates.")
    return result


def _record_boolean_vector(value: object, *, label: str) -> np.ndarray:
    """Decode a JSON-shaped boolean vector without truth-value coercion."""

    if not isinstance(value, list) or any(type(item) is not bool for item in value):
        raise InteractionMatrixError(
            f"serialized {label} must be a list containing only booleans."
        )
    return np.asarray(value, dtype=bool)


def _validated_index(value: object, size: int) -> int:
    if not isinstance(value, Integral) or isinstance(value, (bool, np.bool_)):
        raise InteractionMatrixError("coordinate index must be an integer.")
    result = int(value)
    if not 0 <= result < size:
        raise InteractionMatrixError(
            f"coordinate index {result} is outside [0, {size})."
        )
    return result


def _literal(value: object, allowed: frozenset[str], label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise InteractionMatrixError(
            f"{label} must be one of {sorted(allowed)}; got {value!r}."
        )
    return value


def _positive_integer(value: object, *, label: str) -> int:
    result = _nonnegative_integer(value, label=label)
    if result <= 0:
        raise InteractionMatrixError(f"{label} must be positive.")
    return result


def _nonnegative_integer(value: object, *, label: str) -> int:
    if not isinstance(value, Integral) or isinstance(value, (bool, np.bool_)):
        raise InteractionMatrixError(f"{label} must be an integer.")
    result = int(value)
    if result < 0:
        raise InteractionMatrixError(f"{label} must be non-negative.")
    return result


def _finite_float(value: object, *, label: str) -> float:
    if not isinstance(value, Real) or isinstance(value, (bool, np.bool_)):
        raise InteractionMatrixError(f"{label} must be a finite real number.")
    result = float(value)
    if not math.isfinite(result):
        raise InteractionMatrixError(f"{label} must be a finite real number.")
    return result


def _positive_finite_float(value: object, *, label: str) -> float:
    result = _finite_float(value, label=label)
    if result <= 0.0:
        raise InteractionMatrixError(f"{label} must be strictly positive.")
    return result


def _positive_float_allow_infinity(value: object, *, label: str) -> float:
    if not isinstance(value, Real) or isinstance(value, (bool, np.bool_)):
        raise InteractionMatrixError(f"{label} must be positive.")
    result = float(value)
    if math.isnan(result) or result <= 0.0:
        raise InteractionMatrixError(f"{label} must be positive and not NaN.")
    return result


def _condition_float(value: object) -> float:
    if not isinstance(value, Real) or isinstance(value, (bool, np.bool_)):
        raise InteractionMatrixError(
            "condition_proxy must be a real number or positive infinity."
        )
    result = float(value)
    if math.isnan(result) or result < 1.0:
        raise InteractionMatrixError(
            "condition_proxy must be at least one or positive infinity."
        )
    return result


def _same_condition(left: float, right: float) -> bool:
    if math.isinf(left) or math.isinf(right):
        return left == right
    return math.isclose(left, right, rel_tol=1.0e-12, abs_tol=0.0)


def _nonempty_string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise InteractionMatrixError(f"{label} must be a non-empty string.")
    return value


def _optional_hash(value: object, *, label: str) -> str | None:
    if value is None:
        return None
    return _nonempty_string(value, label=label)


def _immutable_float_array(
    value: object,
    *,
    label: str,
    ndim: int,
    finite: bool = False,
) -> np.ndarray:
    if not isinstance(value, np.ndarray):
        raise InteractionMatrixError(f"{label} must be a numpy.ndarray.")
    if (
        np.issubdtype(value.dtype, np.bool_)
        or not np.issubdtype(value.dtype, np.number)
        or np.issubdtype(value.dtype, np.complexfloating)
    ):
        raise InteractionMatrixError(f"{label} must contain real numbers.")
    result = _immutable_array(value, dtype=float)
    if result.ndim != ndim:
        raise InteractionMatrixError(
            f"{label} must be {ndim}-dimensional; got shape {result.shape}."
        )
    if finite and not np.all(np.isfinite(result)):
        raise InteractionMatrixError(f"{label} must contain only finite values.")
    return result


def _immutable_bool_array(value: object, *, label: str, ndim: int) -> np.ndarray:
    if not isinstance(value, np.ndarray) or value.dtype != np.dtype(bool):
        raise InteractionMatrixError(
            f"{label} must be a boolean numpy.ndarray."
        )
    result = _immutable_array(value, dtype=bool)
    if result.ndim != ndim:
        raise InteractionMatrixError(
            f"{label} must be {ndim}-dimensional; got shape {result.shape}."
        )
    return result


def _immutable_int_array(value: object, *, label: str, ndim: int) -> np.ndarray:
    if not isinstance(value, np.ndarray) or not np.issubdtype(
        value.dtype,
        np.integer,
    ):
        raise InteractionMatrixError(f"{label} must be an integer numpy.ndarray.")
    result = _immutable_array(value, dtype=np.int64)
    if result.ndim != ndim:
        raise InteractionMatrixError(
            f"{label} must be {ndim}-dimensional; got shape {result.shape}."
        )
    return result


def _immutable_array(value: object, *, dtype: Any) -> np.ndarray:
    contiguous = np.ascontiguousarray(np.array(value, dtype=dtype, copy=True))
    immutable = np.frombuffer(contiguous.tobytes(order="C"), dtype=contiguous.dtype)
    return immutable.reshape(contiguous.shape)


__all__ = (
    "CoordinateKind",
    "CoordinateUnit",
    "CalibrationMethod",
    "INTERACTION_SIGN_CONVENTION",
    "INTERACTION_MATRIX_SCHEMA_ID",
    "InteractionMatrixError",
    "InteractionCalibrationError",
    "ProbeBasis",
    "ModalProbeBasis",
    "DmActuatorProbeBasis",
    "InteractionMatrix",
    "calibrate_interaction_matrix",
    "interaction_matrix_hash",
)
