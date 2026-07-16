"""Canonical, serialization-defined hashes for adaptive-optics configuration.

The helpers in this module deliberately accept only repository-owned data
shapes.  In particular, arbitrary objects are not hashed through ``repr`` or
``__dict__`` because either representation can vary with process state,
implementation details, or dictionary insertion order.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
import hashlib
import json
import math
from typing import Any

import numpy as np


HASH_SCHEMA_ID = "shwfs_ao.canonical_sha256.v1"
"""Identifier for the canonical payload and digest algorithm."""


class HashingError(ValueError):
    """Raised when a value cannot be represented by the hash schema."""


def stable_array_descriptor(values: Any) -> dict[str, Any]:
    """Return a platform-stable shape/dtype/SHA-256 array descriptor.

    The descriptor is the frozen historical representation used by the
    compatibility layer.  Numeric values use explicit little-endian storage;
    floating NaNs and signed zero are normalized before hashing.
    """

    array = np.asarray(values)
    kind = array.dtype.kind
    if kind == "b":
        canonical = array.astype(np.uint8, copy=True)
        dtype_name = "bool"
    elif kind == "i":
        canonical = array.astype(np.dtype("<i8"), copy=True)
        dtype_name = "int64"
    elif kind == "u":
        canonical = array.astype(np.dtype("<u8"), copy=True)
        dtype_name = "uint64"
    elif kind == "f":
        canonical = array.astype(np.dtype("<f8"), copy=True)
        canonical[canonical == 0.0] = 0.0
        canonical[np.isnan(canonical)] = np.nan
        dtype_name = "float64"
    elif kind == "c":
        canonical = array.astype(np.dtype("<c16"), copy=True)
        real = canonical.real
        imag = canonical.imag
        real[real == 0.0] = 0.0
        imag[imag == 0.0] = 0.0
        real[np.isnan(real)] = np.nan
        imag[np.isnan(imag)] = np.nan
        dtype_name = "complex128"
    else:
        raise TypeError(f"Unsupported array dtype for stable hashing: {array.dtype}.")

    canonical = np.ascontiguousarray(canonical)
    header = json.dumps(
        {"dtype": dtype_name, "shape": [int(v) for v in canonical.shape]},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(header + b"\0" + canonical.tobytes(order="C")).hexdigest()
    return {
        "shape": [int(v) for v in canonical.shape],
        "dtype": dtype_name,
        "sha256": digest,
    }


def canonicalize_for_hash(value: Any) -> Any:
    """Convert supported repository values to the canonical JSON data model.

    Mapping keys must be strings.  Dataclasses are traversed through declared
    fields, not incidental instance dictionaries.  Unordered containers and
    arbitrary objects are rejected rather than assigned unstable identities.
    """

    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, (int, np.integer)) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if math.isnan(number):
            return {"$float": "nan"}
        if math.isinf(number):
            return {"$float": "+inf" if number > 0.0 else "-inf"}
        return 0.0 if number == 0.0 else number
    if isinstance(value, (complex, np.complexfloating)):
        number = complex(value)
        return {
            "$complex": [
                canonicalize_for_hash(number.real),
                canonicalize_for_hash(number.imag),
            ]
        }
    if isinstance(value, np.ndarray):
        return {"$array": stable_array_descriptor(value)}
    if is_dataclass(value) and not isinstance(value, type):
        value_type = type(value)
        explicit_schema = getattr(value_type, "__hash_schema_id__", None)
        if explicit_schema is not None:
            if not isinstance(explicit_schema, str) or not explicit_schema.strip():
                raise HashingError(
                    "dataclass __hash_schema_id__ must be a non-empty string."
                )
            schema_id = explicit_schema
        else:
            schema_id = f"{value_type.__module__}.{value_type.__qualname__}"
        return {
            "$dataclass": {
                "schema_id": schema_id,
                "fields": [
                    [field.name, canonicalize_for_hash(getattr(value, field.name))]
                    for field in fields(value)
                ],
            }
        }
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise HashingError(
                    "Canonical hash mappings require string keys; "
                    f"got {type(key).__name__}."
                )
            if key in normalized:
                raise HashingError(f"Duplicate canonical mapping key {key!r}.")
            normalized[key] = canonicalize_for_hash(item)
        return {
            "$mapping": [
                [key, normalized[key]]
                for key in sorted(normalized)
            ]
        }
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray, memoryview)
    ):
        return {"$sequence": [canonicalize_for_hash(item) for item in value]}
    if isinstance(value, (bytes, bytearray, memoryview)):
        payload = bytes(value)
        return {
            "$bytes": {
                "length": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        }
    if isinstance(value, (set, frozenset)):
        raise HashingError("Unordered sets are not supported by the canonical hash schema.")
    raise HashingError(
        "Unsupported value for canonical hashing: "
        f"{type(value).__module__}.{type(value).__qualname__}."
    )


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize a supported value to deterministic UTF-8 JSON bytes."""

    return json.dumps(
        canonicalize_for_hash(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def stable_hash(value: Any, *, namespace: str = "generic") -> str:
    """Return a namespace-separated SHA-256 digest for ``value``."""

    if not isinstance(namespace, str) or not namespace.strip():
        raise HashingError("namespace must be a non-empty string.")
    envelope = {
        "hash_schema": HASH_SCHEMA_ID,
        "namespace": namespace,
        "value": value,
    }
    return hashlib.sha256(canonical_json_bytes(envelope)).hexdigest()


def geometry_hash(geometry: Any) -> str:
    """Hash a geometry/sampling description in its own semantic namespace."""

    return stable_hash(geometry, namespace="geometry")


def detector_plane_sampling_hash(
    *,
    window_shape_px: Sequence[int],
    pixel_scale_rad: Sequence[float],
    reference_pixel_xy: Sequence[float],
) -> str:
    """Hash the complete detector-plane geometry used by spot results."""

    return geometry_hash(
        {
            "geometry_kind": "detector_plane_sampling",
            "window_shape_px": tuple(int(value) for value in window_shape_px),
            "pixel_scale_rad": tuple(float(value) for value in pixel_scale_rad),
            "reference_pixel_xy": tuple(
                float(value) for value in reference_pixel_xy
            ),
        }
    )


def calibration_rows_hash(
    row_ids: Sequence[str],
    *,
    valid_rows: Sequence[bool] | np.ndarray | None = None,
) -> str:
    """Hash an ordered calibration-row layout and optional validity policy."""

    ids = _validated_ids(row_ids, label="row_ids")
    payload: dict[str, Any] = {"row_ids": ids}
    if valid_rows is not None:
        validity = np.asarray(valid_rows)
        if validity.dtype.kind != "b" or validity.shape != (len(ids),):
            raise HashingError(
                "valid_rows must be a one-dimensional boolean array matching row_ids."
            )
        payload["valid_rows"] = validity
    return stable_hash(payload, namespace="calibration_rows")


def command_coordinates_hash(
    coordinate_ids: Sequence[str],
    *,
    coordinate_kind: str,
    coordinate_unit: str,
) -> str:
    """Hash ordered command coordinates with explicit physical semantics."""

    ids = _validated_ids(coordinate_ids, label="coordinate_ids")
    if coordinate_kind not in {"modal_opd", "dm_command_opd"}:
        raise HashingError(f"Unsupported coordinate_kind {coordinate_kind!r}.")
    if coordinate_unit not in {"m_opd_rms", "m_opd_equivalent"}:
        raise HashingError(f"Unsupported coordinate_unit {coordinate_unit!r}.")
    return stable_hash(
        {
            "coordinate_ids": ids,
            "coordinate_kind": coordinate_kind,
            "coordinate_unit": coordinate_unit,
        },
        namespace="command_coordinates",
    )


def component_config_hash(component_name: str, config: Any) -> str:
    """Hash a component's repository-owned, serializable configuration."""

    if not isinstance(component_name, str) or not component_name.strip():
        raise HashingError("component_name must be a non-empty string.")
    return stable_hash(
        {"component_name": component_name, "config": config},
        namespace="component_config",
    )


def _validated_ids(values: Sequence[str], *, label: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise HashingError(f"{label} must be an ordered sequence of identifiers.")
    ids = tuple(values)
    if any(not isinstance(value, str) or not value for value in ids):
        raise HashingError(f"{label} must contain only non-empty strings.")
    if len(ids) != len(set(ids)):
        raise HashingError(f"{label} must not contain duplicate identifiers.")
    return ids


# Readable verb-first aliases support call sites that group identity helpers.
hash_geometry = geometry_hash
hash_calibration_rows = calibration_rows_hash
hash_command_coordinates = command_coordinates_hash
hash_component_config = component_config_hash


__all__ = (
    "HASH_SCHEMA_ID",
    "HashingError",
    "stable_array_descriptor",
    "canonicalize_for_hash",
    "canonical_json_bytes",
    "stable_hash",
    "geometry_hash",
    "detector_plane_sampling_hash",
    "calibration_rows_hash",
    "command_coordinates_hash",
    "component_config_hash",
    "hash_geometry",
    "hash_calibration_rows",
    "hash_command_coordinates",
    "hash_component_config",
)
