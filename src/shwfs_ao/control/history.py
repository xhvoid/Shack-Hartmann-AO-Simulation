"""Immutable fixed-length telemetry for canonical adaptive-optics loops."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Any

import numpy as np


__all__ = ("LoopHistoryError", "LoopHistory")


_FIELD_UNITS: Mapping[str, str] = MappingProxyType(
    {
        "time_s": "s",
        "open_loop_opd_rms_m": "m_opd_rms",
        "pre_update_residual_opd_rms_m": "m_opd_rms",
        "post_update_residual_opd_rms_m": "m_opd_rms",
        "command_norm_m": "m_opd_equivalent_l2_norm",
        "delta_command_norm_m": "m_opd_equivalent_l2_norm",
        "released_delta_norm_m": "m_opd_equivalent_l2_norm",
        "requested_command_history_opd_m": "m_opd_equivalent",
        "applied_command_history_opd_m": "m_opd_equivalent",
        "saturation_fraction": "fraction",
        "valid_measurement_fraction": "fraction",
        "valid_subaperture_fraction": "fraction",
        "reconstruction_usable": "boolean",
        "measurement_row_masks": "boolean",
    }
)
_RESIDUAL_SIGN_CONVENTION = "atmosphere_opd_m - dm_correction_opd_m"
_COMMAND_SIGN_CONVENTION = "positive_command_produces_positive_correction_opd"

_REQUIRED_METADATA = frozenset(
    {
        "field_units",
        "residual_sign_convention",
        "command_sign_convention",
        "actuator_ids",
        "row_ids",
        "calibration_valid_rows",
        "backend_names",
        "component_hashes",
        "frame_rate_hz",
        "root_seed",
        "random_derivation_scheme_id",
        "random_stream_ids",
        "include_noise",
        "realization_index",
    }
)


class LoopHistoryError(ValueError):
    """Raised when canonical loop telemetry is inconsistent or mutable."""


@dataclass(frozen=True)
class LoopHistory:
    time_s: np.ndarray
    open_loop_opd_rms_m: np.ndarray
    pre_update_residual_opd_rms_m: np.ndarray
    post_update_residual_opd_rms_m: np.ndarray
    command_norm_m: np.ndarray
    delta_command_norm_m: np.ndarray
    released_delta_norm_m: np.ndarray
    requested_command_history_opd_m: np.ndarray
    applied_command_history_opd_m: np.ndarray
    saturation_fraction: np.ndarray
    valid_measurement_fraction: np.ndarray
    valid_subaperture_fraction: np.ndarray
    reconstruction_usable: np.ndarray
    measurement_row_masks: np.ndarray
    config_hash: str
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        time_s = _float_vector(self.time_s, label="time_s")
        n_steps = int(time_s.size)
        if n_steps < 1:
            raise LoopHistoryError("time_s must contain at least one frame.")
        metadata = _metadata(self.metadata)
        missing = sorted(_REQUIRED_METADATA - set(metadata))
        if missing:
            raise LoopHistoryError(
                f"metadata is missing required fields: {missing}."
            )
        _validate_metadata_schema(metadata)
        frame_rate_hz = _positive_float(
            metadata["frame_rate_hz"],
            label="metadata.frame_rate_hz",
        )
        expected_time = np.arange(n_steps, dtype=float) / frame_rate_hz
        if not np.array_equal(time_s, expected_time):
            raise LoopHistoryError(
                "time_s must equal arange(n_steps) / metadata.frame_rate_hz."
            )

        vector_names = (
            "open_loop_opd_rms_m",
            "pre_update_residual_opd_rms_m",
            "post_update_residual_opd_rms_m",
            "command_norm_m",
            "delta_command_norm_m",
            "released_delta_norm_m",
            "saturation_fraction",
            "valid_measurement_fraction",
            "valid_subaperture_fraction",
        )
        vectors = {
            name: _float_vector(getattr(self, name), label=name, length=n_steps)
            for name in vector_names
        }
        for name in (
            "open_loop_opd_rms_m",
            "pre_update_residual_opd_rms_m",
            "post_update_residual_opd_rms_m",
            "command_norm_m",
            "delta_command_norm_m",
            "released_delta_norm_m",
        ):
            if np.any(vectors[name] < 0.0):
                raise LoopHistoryError(f"{name} must be non-negative.")
        for name in (
            "saturation_fraction",
            "valid_measurement_fraction",
            "valid_subaperture_fraction",
        ):
            if np.any((vectors[name] < 0.0) | (vectors[name] > 1.0)):
                raise LoopHistoryError(f"{name} must stay within [0, 1].")

        requested = _float_matrix(
            self.requested_command_history_opd_m,
            label="requested_command_history_opd_m",
            rows=n_steps,
        )
        applied = _float_matrix(
            self.applied_command_history_opd_m,
            label="applied_command_history_opd_m",
            rows=n_steps,
        )
        if requested.shape != applied.shape or requested.shape[1] < 1:
            raise LoopHistoryError(
                "requested and applied command histories must have the same "
                "positive actuator-column count."
            )
        actuator_ids = _metadata_ids(metadata["actuator_ids"], label="actuator_ids")
        if len(actuator_ids) != requested.shape[1]:
            raise LoopHistoryError(
                "metadata actuator_ids length must match command-history columns."
            )

        reconstruction_usable = _bool_vector(
            self.reconstruction_usable,
            label="reconstruction_usable",
            length=n_steps,
        )
        row_masks = _bool_matrix(
            self.measurement_row_masks,
            label="measurement_row_masks",
            rows=n_steps,
        )
        if row_masks.shape[1] < 1:
            raise LoopHistoryError(
                "measurement_row_masks must contain at least one row column."
            )
        row_ids = _metadata_ids(metadata["row_ids"], label="row_ids")
        if len(row_ids) != row_masks.shape[1]:
            raise LoopHistoryError(
                "metadata row_ids length must match measurement-row columns."
            )
        calibration_valid = _metadata_bool_vector(
            metadata["calibration_valid_rows"],
            length=row_masks.shape[1],
            label="metadata.calibration_valid_rows",
        )
        denominator = int(np.count_nonzero(calibration_valid))
        if denominator < 1:
            raise LoopHistoryError(
                "metadata.calibration_valid_rows must contain a valid row."
            )
        if np.any(row_masks & ~calibration_valid[None, :]):
            raise LoopHistoryError(
                "measurement_row_masks cannot use calibration-invalid rows."
            )
        expected_valid_fraction = np.count_nonzero(row_masks, axis=1) / denominator
        if not np.allclose(
            vectors["valid_measurement_fraction"],
            expected_valid_fraction,
            rtol=0.0,
            atol=1.0e-15,
        ):
            raise LoopHistoryError(
                "valid_measurement_fraction must use the stored effective row "
                "mask and calibration-valid denominator."
            )

        expected_command_norm = _row_l2_norm(applied)
        if not np.allclose(
            vectors["command_norm_m"],
            expected_command_norm,
            rtol=1.0e-13,
            atol=0.0,
        ):
            raise LoopHistoryError(
                "command_norm_m must equal the applied command-history L2 norm."
            )
        config_hash = _sha256(self.config_hash, label="config_hash")

        object.__setattr__(self, "time_s", time_s)
        for name, value in vectors.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "requested_command_history_opd_m", requested)
        object.__setattr__(self, "applied_command_history_opd_m", applied)
        object.__setattr__(self, "reconstruction_usable", reconstruction_usable)
        object.__setattr__(self, "measurement_row_masks", row_masks)
        object.__setattr__(self, "config_hash", config_hash)
        object.__setattr__(self, "metadata", metadata)

    @property
    def n_steps(self) -> int:
        return int(self.time_s.size)

    @property
    def n_actuators(self) -> int:
        return int(self.applied_command_history_opd_m.shape[1])

    @property
    def n_measurement_rows(self) -> int:
        return int(self.measurement_row_masks.shape[1])


def _float_vector(
    value: object,
    *,
    label: str,
    length: int | None = None,
) -> np.ndarray:
    array = _numeric_array(value, label=label, ndim=1)
    if length is not None and array.shape != (length,):
        raise LoopHistoryError(f"{label} must have shape ({length},).")
    return _immutable_array(array, dtype=float)


def _float_matrix(value: object, *, label: str, rows: int) -> np.ndarray:
    array = _numeric_array(value, label=label, ndim=2)
    if array.shape[0] != rows:
        raise LoopHistoryError(f"{label} must have {rows} rows.")
    return _immutable_array(array, dtype=float)


def _numeric_array(value: object, *, label: str, ndim: int) -> np.ndarray:
    if not isinstance(value, np.ndarray):
        raise LoopHistoryError(f"{label} must be a numpy.ndarray.")
    if (
        value.ndim != ndim
        or np.issubdtype(value.dtype, np.bool_)
        or not np.issubdtype(value.dtype, np.number)
        or np.issubdtype(value.dtype, np.complexfloating)
    ):
        raise LoopHistoryError(f"{label} must be a {ndim}-D real numeric array.")
    array = np.asarray(value, dtype=float)
    if not np.all(np.isfinite(array)):
        raise LoopHistoryError(f"{label} must contain only finite values.")
    return array


def _bool_vector(value: object, *, label: str, length: int) -> np.ndarray:
    if (
        not isinstance(value, np.ndarray)
        or value.dtype != np.dtype(bool)
        or value.shape != (length,)
    ):
        raise LoopHistoryError(f"{label} must be a ({length},) boolean array.")
    return _immutable_array(value, dtype=bool)


def _bool_matrix(value: object, *, label: str, rows: int) -> np.ndarray:
    if (
        not isinstance(value, np.ndarray)
        or value.dtype != np.dtype(bool)
        or value.ndim != 2
        or value.shape[0] != rows
    ):
        raise LoopHistoryError(f"{label} must be a {rows}-row boolean matrix.")
    return _immutable_array(value, dtype=bool)


def _metadata(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LoopHistoryError("metadata must be a mapping.")
    return _freeze_mapping(value, label="metadata")


def _validate_metadata_schema(metadata: Mapping[str, Any]) -> None:
    field_units = metadata["field_units"]
    if not isinstance(field_units, Mapping) or dict(field_units) != dict(_FIELD_UNITS):
        raise LoopHistoryError(
            "metadata.field_units must exactly match the LoopHistory field schema."
        )
    if metadata["residual_sign_convention"] != _RESIDUAL_SIGN_CONVENTION:
        raise LoopHistoryError(
            "metadata.residual_sign_convention does not match the canonical sign."
        )
    if metadata["command_sign_convention"] != _COMMAND_SIGN_CONVENTION:
        raise LoopHistoryError(
            "metadata.command_sign_convention does not match the canonical sign."
        )
    _nonnegative_integer(metadata["root_seed"], label="metadata.root_seed")
    _nonnegative_integer(
        metadata["realization_index"],
        label="metadata.realization_index",
    )
    if type(metadata["include_noise"]) is not bool:
        raise LoopHistoryError("metadata.include_noise must be a boolean.")
    _nonempty_string(
        metadata["random_derivation_scheme_id"],
        label="metadata.random_derivation_scheme_id",
    )
    _string_mapping(
        metadata["backend_names"],
        label="metadata.backend_names",
        required_keys=("atmosphere", "wfs", "dm"),
    )
    _string_mapping(
        metadata["component_hashes"],
        label="metadata.component_hashes",
    )
    _string_mapping(
        metadata["random_stream_ids"],
        label="metadata.random_stream_ids",
    )


def _freeze_mapping(value: Mapping[object, object], *, label: str) -> Mapping[str, Any]:
    result: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise LoopHistoryError(f"{label} keys must be non-empty strings.")
        result[key] = _freeze_json(item, label=f"{label}.{key}")
    return MappingProxyType(result)


def _freeze_json(value: object, *, label: str) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (float, np.floating)):
        result = float(value)
        if not math.isfinite(result):
            raise LoopHistoryError(f"{label} must be finite.")
        return result
    if isinstance(value, Mapping):
        return _freeze_mapping(value, label=label)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(
            _freeze_json(item, label=f"{label}[{index}]")
            for index, item in enumerate(value)
        )
    raise LoopHistoryError(
        f"{label} contains unsupported metadata type {type(value).__name__}."
    )


def _metadata_ids(value: object, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, tuple) or not value:
        raise LoopHistoryError(f"metadata.{label} must be a non-empty ID sequence.")
    if any(not isinstance(item, str) or not item for item in value):
        raise LoopHistoryError(f"metadata.{label} must contain non-empty strings.")
    if len(value) != len(set(value)):
        raise LoopHistoryError(f"metadata.{label} must not contain duplicates.")
    return value


def _metadata_bool_vector(
    value: object,
    *,
    length: int,
    label: str,
) -> np.ndarray:
    if not isinstance(value, tuple) or len(value) != length:
        raise LoopHistoryError(f"{label} must contain {length} booleans.")
    if any(type(item) is not bool for item in value):
        raise LoopHistoryError(f"{label} must contain only booleans.")
    return np.asarray(value, dtype=bool)


def _row_l2_norm(values: np.ndarray) -> np.ndarray:
    scale = np.max(np.abs(values), axis=1)
    result = np.zeros(values.shape[0], dtype=float)
    nonzero = scale > 0.0
    scaled = values[nonzero] / scale[nonzero, None]
    result[nonzero] = scale[nonzero] * np.sqrt(np.sum(scaled * scaled, axis=1))
    return result


def _positive_float(value: object, *, label: str) -> float:
    if isinstance(value, bool):
        raise LoopHistoryError(f"{label} must be a positive finite number.")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise LoopHistoryError(f"{label} must be a positive finite number.") from exc
    if not math.isfinite(result) or result <= 0.0:
        raise LoopHistoryError(f"{label} must be a positive finite number.")
    return result


def _nonnegative_integer(value: object, *, label: str) -> int:
    if type(value) is not int or value < 0:
        raise LoopHistoryError(f"{label} must be a non-negative integer.")
    return value


def _nonempty_string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LoopHistoryError(f"{label} must be a non-empty string.")
    return value


def _string_mapping(
    value: object,
    *,
    label: str,
    required_keys: tuple[str, ...] = (),
) -> Mapping[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise LoopHistoryError(f"{label} must be a non-empty string mapping.")
    missing = tuple(key for key in required_keys if key not in value)
    if missing:
        raise LoopHistoryError(f"{label} is missing required keys {missing}.")
    for key, item in value.items():
        if (
            not isinstance(key, str)
            or not key.strip()
            or not isinstance(item, str)
            or not item.strip()
        ):
            raise LoopHistoryError(
                f"{label} must contain only non-empty string keys and values."
            )
    return value


def _sha256(value: object, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise LoopHistoryError(f"{label} must be a lowercase SHA-256 hex digest.")
    return value


def _immutable_array(value: object, *, dtype: object) -> np.ndarray:
    contiguous = np.ascontiguousarray(np.array(value, dtype=dtype, copy=True))
    immutable = np.frombuffer(
        contiguous.tobytes(order="C"),
        dtype=contiguous.dtype,
    )
    return immutable.reshape(contiguous.shape)
