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

# Canonical bytes are digested in blocks of leading-axis slices, so hashing a
# large array never holds a full canonical copy plus its ``bytes`` alongside
# the input.  The block size changes only memory, never the digest.
_HASH_BLOCK_BYTES = 16 * 1024**2

# Array kind -> (descriptor dtype name, canonical little-endian dtype).
_CANONICAL_DTYPES: dict[str, tuple[str, np.dtype[Any]]] = {
    "b": ("bool", np.dtype(np.uint8)),
    "i": ("int64", np.dtype("<i8")),
    "u": ("uint64", np.dtype("<u8")),
    "f": ("float64", np.dtype("<f8")),
    "c": ("complex128", np.dtype("<c16")),
}


class HashingError(ValueError):
    """Raised when a value cannot be represented by the hash schema."""


def stable_array_descriptor(values: Any) -> dict[str, Any]:
    """Return a platform-stable shape/dtype/SHA-256 array descriptor.

    The descriptor is the frozen historical representation used by the
    compatibility layer.  Numeric values use explicit little-endian storage;
    floating NaNs and signed zero are normalized before hashing.

    The digest covers the C-order canonical bytes of the whole array.  They
    are produced and hashed one block of leading-axis slices at a time; the
    concatenated blocks are byte-for-byte the historical single buffer.
    """

    array = np.asarray(values)
    kind = array.dtype.kind
    if kind not in _CANONICAL_DTYPES:
        raise TypeError(f"Unsupported array dtype for stable hashing: {array.dtype}.")
    dtype_name, canonical_dtype = _CANONICAL_DTYPES[kind]

    if array.ndim == 0 or array.size == 0:
        whole = _canonical_block(array, kind)
        shape = whole.shape
        blocks: Any = (whole,)
    else:
        shape = array.shape
        row_bytes = canonical_dtype.itemsize * (array.size // array.shape[0])
        rows = max(1, _HASH_BLOCK_BYTES // max(1, row_bytes))
        blocks = (
            _canonical_block(array[start:start + rows], kind)
            for start in range(0, array.shape[0], rows)
        )

    header = json.dumps(
        {"dtype": dtype_name, "shape": [int(v) for v in shape]},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    hasher = hashlib.sha256(header + b"\0")
    for block in blocks:
        hasher.update(block.tobytes(order="C"))
    return {
        "shape": [int(v) for v in shape],
        "dtype": dtype_name,
        "sha256": hasher.hexdigest(),
    }


class ArrayDescriptor:
    """A precomputed :func:`stable_array_descriptor` that hashes like its array.

    :func:`canonicalize_for_hash` turns it into exactly the ``{"$array": ...}``
    node of the array it describes, so a hash payload can carry a large
    array's digest without holding the array.
    """

    __slots__ = ("_shape", "_dtype", "_sha256")

    def __init__(self, *, shape: Sequence[int], dtype: str, sha256: str) -> None:
        names = {name for name, _ in _CANONICAL_DTYPES.values()}
        if dtype not in names:
            raise HashingError(f"Unsupported descriptor dtype {dtype!r}.")
        if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
            raise HashingError("sha256 must be a lowercase 64-digit hex digest.")
        self._shape = tuple(int(v) for v in shape)
        self._dtype = dtype
        self._sha256 = sha256

    def as_mapping(self) -> dict[str, Any]:
        """The same mapping :func:`stable_array_descriptor` returns."""

        return {"shape": list(self._shape), "dtype": self._dtype, "sha256": self._sha256}


class StackedArrayDigest:
    """``stable_array_descriptor(np.stack(items))`` built one item at a time.

    It digests the stacked array's header and canonical C-order bytes item by
    item, so only one item is ever held.  Exactly ``count`` items must be
    added, all with the first item's shape and dtype (stacking would not have
    promoted anything).
    """

    def __init__(self, count: int) -> None:
        if isinstance(count, bool) or int(count) != count or int(count) < 1:
            raise HashingError("count must be a positive integer.")
        self._count = int(count)
        self._added = 0
        self._hasher: Any = None
        self._item_shape: tuple[int, ...] = ()
        self._item_dtype: np.dtype | None = None
        self._kind = ""
        self._dtype_name = ""

    def add(self, item: Any) -> None:
        array = np.asarray(item)
        if self._added >= self._count:
            raise HashingError(f"more than the declared {self._count} items were added.")
        if self._hasher is None:
            kind = array.dtype.kind
            if kind not in _CANONICAL_DTYPES:
                raise TypeError(
                    f"Unsupported array dtype for stable hashing: {array.dtype}."
                )
            self._kind = kind
            self._dtype_name = _CANONICAL_DTYPES[kind][0]
            self._item_shape = tuple(int(v) for v in array.shape)
            self._item_dtype = array.dtype
            header = json.dumps(
                {
                    "dtype": self._dtype_name,
                    "shape": [self._count, *self._item_shape],
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            self._hasher = hashlib.sha256(header + b"\0")
        elif array.shape != self._item_shape or array.dtype != self._item_dtype:
            raise HashingError("stacked items must all share one shape and dtype.")
        self._hasher.update(_canonical_block(array, self._kind).tobytes(order="C"))
        self._added += 1

    def descriptor(self) -> ArrayDescriptor:
        if self._added != self._count:
            raise HashingError(
                f"{self._added} of the declared {self._count} items were added."
            )
        return ArrayDescriptor(
            shape=(self._count, *self._item_shape),
            dtype=self._dtype_name,
            sha256=self._hasher.hexdigest(),
        )


def _canonical_block(array: np.ndarray, kind: str) -> np.ndarray:
    """Canonical contiguous values of ``array``: the historical conversion."""

    if kind == "b":
        canonical = array.astype(np.uint8, copy=True)
    elif kind == "i":
        canonical = array.astype(np.dtype("<i8"), copy=True)
    elif kind == "u":
        canonical = array.astype(np.dtype("<u8"), copy=True)
    elif kind == "f":
        canonical = array.astype(np.dtype("<f8"), copy=True)
        canonical[canonical == 0.0] = 0.0
        canonical[np.isnan(canonical)] = np.nan
    else:
        canonical = array.astype(np.dtype("<c16"), copy=True)
        real = canonical.real
        imag = canonical.imag
        real[real == 0.0] = 0.0
        imag[imag == 0.0] = 0.0
        real[np.isnan(real)] = np.nan
        imag[np.isnan(imag)] = np.nan
    return np.ascontiguousarray(canonical)


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
        complex_number = complex(value)
        return {
            "$complex": [
                canonicalize_for_hash(complex_number.real),
                canonicalize_for_hash(complex_number.imag),
            ]
        }
    if isinstance(value, np.ndarray):
        return {"$array": stable_array_descriptor(value)}
    if isinstance(value, ArrayDescriptor):
        return {"$array": value.as_mapping()}
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
