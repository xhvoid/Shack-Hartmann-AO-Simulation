"""Typed reconstruction-coordinate to full-DM command mappings."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal

import numpy as np

from ..core.hashing import component_config_hash
from ..core.types import DmCommandVector, ReconstructionEstimate


__all__ = (
    "CommandMappingError",
    "IdentityCommandProjector",
    "ControlledSubsetCommandProjector",
    "ModalToActuatorCommandProjector",
)


_COMMAND_UNIT = "m_opd_equivalent"
_MODAL_UNIT = "m_opd_rms"
_MAPPING_UNIT = "m_opd_equivalent_per_m_opd_rms"
_MAPPING_SIGN = "positive_modal_aberration_maps_to_positive_dm_correction"


class CommandMappingError(ValueError):
    """Raised when reconstruction coordinates cannot be mapped safely."""


class IdentityCommandProjector:
    """Map an exact full actuator-coordinate layout without numerical change."""

    def __init__(self, actuator_ids: tuple[str, ...]) -> None:
        identifiers = _ids(actuator_ids, label="actuator_ids")
        self._input_coordinate_ids = identifiers
        self._output_actuator_ids = identifiers
        self._config_hash = component_config_hash(
            "control.identity_command_projector",
            {
                "input_coordinate_ids": identifiers,
                "input_coordinate_kind": "dm_command_opd",
                "input_coordinate_unit": _COMMAND_UNIT,
                "output_actuator_ids": identifiers,
                "output_command_unit": _COMMAND_UNIT,
            },
        )
        self._metadata: Mapping[str, object] = MappingProxyType(
            {
                "mapping_kind": "identity",
                "input_coordinate_ids": identifiers,
                "output_actuator_ids": identifiers,
                "command_unit": _COMMAND_UNIT,
                "config_hash": self._config_hash,
            }
        )

    @property
    def config_hash(self) -> str:
        return self._config_hash

    @property
    def input_coordinate_ids(self) -> tuple[str, ...]:
        return self._input_coordinate_ids

    @property
    def input_coordinate_kind(self) -> Literal["dm_command_opd"]:
        return "dm_command_opd"

    @property
    def input_coordinate_unit(self) -> Literal["m_opd_equivalent"]:
        return _COMMAND_UNIT

    @property
    def output_actuator_ids(self) -> tuple[str, ...]:
        return self._output_actuator_ids

    @property
    def metadata(self) -> Mapping[str, object]:
        return self._metadata

    def project(self, estimate: ReconstructionEstimate) -> DmCommandVector:
        _validate_estimate(self, estimate)
        return DmCommandVector(
            values_opd_m=np.asarray(estimate.delta_coordinates_opd_m),
            actuator_ids=self._output_actuator_ids,
            command_unit=_COMMAND_UNIT,
        )


class ControlledSubsetCommandProjector:
    """Expand controlled actuator increments into a complete layout by ID."""

    def __init__(
        self,
        input_coordinate_ids: tuple[str, ...],
        output_actuator_ids: tuple[str, ...],
    ) -> None:
        inputs = _ids(input_coordinate_ids, label="input_coordinate_ids")
        outputs = _ids(output_actuator_ids, label="output_actuator_ids")
        missing = tuple(identifier for identifier in inputs if identifier not in outputs)
        if missing:
            raise CommandMappingError(
                "input_coordinate_ids must be a subset of output_actuator_ids; "
                f"missing={list(missing)}."
            )
        output_index = {identifier: index for index, identifier in enumerate(outputs)}
        indices = np.asarray([output_index[identifier] for identifier in inputs], dtype=int)
        self._input_coordinate_ids = inputs
        self._output_actuator_ids = outputs
        self._output_indices = _immutable_array(indices, dtype=int)
        self._config_hash = component_config_hash(
            "control.controlled_subset_command_projector",
            {
                "input_coordinate_ids": inputs,
                "input_coordinate_kind": "dm_command_opd",
                "input_coordinate_unit": _COMMAND_UNIT,
                "output_actuator_ids": outputs,
                "output_command_unit": _COMMAND_UNIT,
                "output_indices": indices,
                "excluded_increment_policy": "insert_exact_zero_by_actuator_id",
            },
        )
        self._metadata: Mapping[str, object] = MappingProxyType(
            {
                "mapping_kind": "controlled_subset",
                "input_coordinate_ids": inputs,
                "output_actuator_ids": outputs,
                "excluded_actuator_ids": tuple(
                    identifier for identifier in outputs if identifier not in inputs
                ),
                "command_unit": _COMMAND_UNIT,
                "config_hash": self._config_hash,
            }
        )

    @property
    def config_hash(self) -> str:
        return self._config_hash

    @property
    def input_coordinate_ids(self) -> tuple[str, ...]:
        return self._input_coordinate_ids

    @property
    def input_coordinate_kind(self) -> Literal["dm_command_opd"]:
        return "dm_command_opd"

    @property
    def input_coordinate_unit(self) -> Literal["m_opd_equivalent"]:
        return _COMMAND_UNIT

    @property
    def output_actuator_ids(self) -> tuple[str, ...]:
        return self._output_actuator_ids

    @property
    def metadata(self) -> Mapping[str, object]:
        return self._metadata

    def project(self, estimate: ReconstructionEstimate) -> DmCommandVector:
        _validate_estimate(self, estimate)
        output = np.zeros(len(self._output_actuator_ids), dtype=float)
        output[np.asarray(self._output_indices)] = estimate.delta_coordinates_opd_m
        return DmCommandVector(
            values_opd_m=output,
            actuator_ids=self._output_actuator_ids,
            command_unit=_COMMAND_UNIT,
        )


class ModalToActuatorCommandProjector:
    """Apply an explicit calibrated modal-to-full-actuator linear mapping."""

    def __init__(
        self,
        modal_to_actuator_matrix: np.ndarray,
        *,
        input_coordinate_ids: tuple[str, ...],
        output_actuator_ids: tuple[str, ...],
        target_dm_hash: str,
    ) -> None:
        inputs = _ids(input_coordinate_ids, label="input_coordinate_ids")
        outputs = _ids(output_actuator_ids, label="output_actuator_ids")
        dm_hash = _nonempty_string(target_dm_hash, label="target_dm_hash")
        matrix = _matrix(
            modal_to_actuator_matrix,
            expected_shape=(len(outputs), len(inputs)),
        )
        immutable_matrix = _immutable_array(matrix, dtype=float)
        mapping_hash = component_config_hash(
            "control.modal_to_actuator_mapping",
            {
                "modal_to_actuator_matrix": matrix,
                "matrix_unit": _MAPPING_UNIT,
                "input_coordinate_ids": inputs,
                "input_coordinate_kind": "modal_opd",
                "input_coordinate_unit": _MODAL_UNIT,
                "output_actuator_ids": outputs,
                "output_command_unit": _COMMAND_UNIT,
                "target_dm_hash": dm_hash,
                "mapping_sign_convention": _MAPPING_SIGN,
            },
        )
        self._input_coordinate_ids = inputs
        self._output_actuator_ids = outputs
        self._modal_to_actuator_matrix = immutable_matrix
        self._mapping_hash = mapping_hash
        self._target_dm_hash = dm_hash
        self._config_hash = component_config_hash(
            "control.modal_to_actuator_command_projector",
            {"mapping_hash": mapping_hash},
        )
        self._metadata: Mapping[str, object] = MappingProxyType(
            {
                "mapping_kind": "modal_to_actuator",
                "matrix_unit": _MAPPING_UNIT,
                "mapping_sign_convention": _MAPPING_SIGN,
                "mapping_hash": mapping_hash,
                "target_dm_hash": dm_hash,
                "config_hash": self._config_hash,
                "input_coordinate_ids": inputs,
                "output_actuator_ids": outputs,
            }
        )

    @property
    def config_hash(self) -> str:
        return self._config_hash

    @property
    def mapping_hash(self) -> str:
        return self._mapping_hash

    @property
    def target_dm_hash(self) -> str:
        return self._target_dm_hash

    @property
    def matrix_unit(self) -> str:
        return _MAPPING_UNIT

    @property
    def mapping_unit(self) -> str:
        return _MAPPING_UNIT

    @property
    def modal_to_actuator_matrix(self) -> np.ndarray:
        return _immutable_array(self._modal_to_actuator_matrix, dtype=float)

    @property
    def input_coordinate_ids(self) -> tuple[str, ...]:
        return self._input_coordinate_ids

    @property
    def input_coordinate_kind(self) -> Literal["modal_opd"]:
        return "modal_opd"

    @property
    def input_coordinate_unit(self) -> Literal["m_opd_rms"]:
        return _MODAL_UNIT

    @property
    def output_actuator_ids(self) -> tuple[str, ...]:
        return self._output_actuator_ids

    @property
    def metadata(self) -> Mapping[str, object]:
        return self._metadata

    def project(self, estimate: ReconstructionEstimate) -> DmCommandVector:
        _validate_estimate(self, estimate)
        output = self._modal_to_actuator_matrix @ estimate.delta_coordinates_opd_m
        if not np.all(np.isfinite(output)):
            raise CommandMappingError(
                "modal-to-actuator projection produced non-finite commands."
            )
        return DmCommandVector(
            values_opd_m=np.asarray(output, dtype=float),
            actuator_ids=self._output_actuator_ids,
            command_unit=_COMMAND_UNIT,
        )


def _validate_estimate(projector: object, estimate: object) -> None:
    if not isinstance(estimate, ReconstructionEstimate):
        raise CommandMappingError("estimate must be a ReconstructionEstimate.")
    if estimate.coordinate_ids != projector.input_coordinate_ids:
        raise CommandMappingError(
            "estimate.coordinate_ids must exactly match the projector input IDs "
            "and ordering."
        )
    if estimate.coordinate_kind != projector.input_coordinate_kind:
        raise CommandMappingError(
            "estimate.coordinate_kind must match the projector input kind."
        )
    if estimate.coordinate_unit != projector.input_coordinate_unit:
        raise CommandMappingError(
            "estimate.coordinate_unit must match the projector input unit."
        )


def _ids(value: object, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, tuple) or not value:
        raise CommandMappingError(f"{label} must be a non-empty tuple of IDs.")
    if any(not isinstance(item, str) or not item for item in value):
        raise CommandMappingError(f"{label} must contain non-empty strings.")
    if len(value) != len(set(value)):
        raise CommandMappingError(f"{label} must not contain duplicate IDs.")
    return value


def _matrix(value: object, *, expected_shape: tuple[int, int]) -> np.ndarray:
    if not isinstance(value, np.ndarray):
        raise CommandMappingError(
            "modal_to_actuator_matrix must be a numpy.ndarray."
        )
    if (
        value.ndim != 2
        or value.shape != expected_shape
        or np.issubdtype(value.dtype, np.bool_)
        or not np.issubdtype(value.dtype, np.number)
        or np.issubdtype(value.dtype, np.complexfloating)
    ):
        raise CommandMappingError(
            "modal_to_actuator_matrix must be a real numeric array with shape "
            f"{expected_shape}."
        )
    matrix = np.asarray(value, dtype=float)
    if not np.all(np.isfinite(matrix)):
        raise CommandMappingError(
            "modal_to_actuator_matrix must contain only finite values."
        )
    return matrix


def _nonempty_string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CommandMappingError(f"{label} must be a non-empty string.")
    return value


def _immutable_array(value: object, *, dtype: object) -> np.ndarray:
    contiguous = np.ascontiguousarray(np.array(value, dtype=dtype, copy=True))
    immutable = np.frombuffer(
        contiguous.tobytes(order="C"),
        dtype=contiguous.dtype,
    )
    return immutable.reshape(contiguous.shape)
