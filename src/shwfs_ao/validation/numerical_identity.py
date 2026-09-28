"""Full-array witnesses for portable cross-backend input identity.

Raw component/fixture hashes remain evidence of the bytes used in a run.
Transcendentals, reductions and FFTs need not produce identical low bits on
different platforms.  Comparing the complete arrays avoids both mistaking
roundoff for changed physics and the bin-edge failures of rounded hashes.
The fixed tolerances here concern input reproduction, not metric acceptance.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
from typing import Any, Mapping
import zlib

import numpy as np

from ..core.hashing import HASH_SCHEMA_ID, stable_array_descriptor, stable_hash


ENCODING = "zlib_base64_float64_le_c_v1"
# Relative tolerance plus a small absolute floor in the declared units.
# OPD: 1e-20 m = 1e-11 nm.  Influence: correction OPD / command OPD.
NUMERICAL_INPUTS = {
    "atmosphere_opd_cube_m": ("fixture_hashes", "m_opd", 1e-12, 1e-20),
    "command_fixture_opd_m": ("fixture_hashes", "m_opd", 1e-12, 1e-20),
    "static_opd_m": ("fixture_hashes", "m_opd", 1e-12, 1e-20),
    "tilt_x_opd_m": ("fixture_hashes", "m_opd", 1e-12, 1e-20),
    "tilt_y_opd_m": ("fixture_hashes", "m_opd", 1e-12, 1e-20),
    "time_grid_s": ("fixture_hashes", "seconds", 1e-12, 1e-15),
    "native_dm": ("component_hashes", "dimensionless", 1e-12, 1e-14),
    "hcipy_dm": ("component_hashes", "dimensionless", 1e-12, 1e-14),
}
_FIELDS = {
    "encoding", "shape", "data", "values_sha256", "source_hash",
    "configuration_hash",
    "source_payload",
    "backend_source_payload",
}
_MAX_VALUES = 16_000_000


def numerical_input_record(
    values: np.ndarray, *, source_hash: str, configuration_hash: str,
    source_payload: str | None = None,
    backend_source_payload: str | None = None,
) -> dict[str, Any]:
    """Losslessly encode the actual values, their bytes and semantic identity."""
    array = np.ascontiguousarray(values, dtype="<f8")
    if np.any(np.isinf(array)) or not np.any(np.isfinite(array)):
        raise ValueError("numerical inputs require finite samples and no infinities")
    raw = array.tobytes()
    return {
        "encoding": ENCODING,
        "shape": list(array.shape),
        "data": base64.b64encode(zlib.compress(raw)).decode("ascii"),
        "values_sha256": hashlib.sha256(raw).hexdigest(),
        "source_hash": source_hash,
        "configuration_hash": configuration_hash,
        "source_payload": source_payload,
        "backend_source_payload": backend_source_payload,
    }


def numerical_input_values(record: Mapping[str, Any]) -> np.ndarray:
    """Decode a bounded array (with optional NaN mask) and verify its hash."""
    if not isinstance(record, Mapping) or set(record) != _FIELDS:
        raise ValueError("numerical input must have exactly the required fields")
    if record["encoding"] != ENCODING:
        raise ValueError("unsupported numerical input encoding")
    for key in ("source_payload", "backend_source_payload"):
        if record[key] is not None and not isinstance(record[key], str):
            raise ValueError(f"numerical input {key} must be a string or null")
    shape = record["shape"]
    if (
        not isinstance(shape, list) or not shape
        or any(type(n) is not int or n < 1 for n in shape)
        or math.prod(shape) > _MAX_VALUES
    ):
        raise ValueError("numerical input shape must be bounded positive integers")
    for key in ("values_sha256", "source_hash", "configuration_hash"):
        value = record[key]
        if (
            not isinstance(value, str) or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)
        ):
            raise ValueError(f"numerical input {key} must be a 64-character hash")
    size_bytes = math.prod(shape) * 8
    try:
        compressed = base64.b64decode(record["data"], validate=True)
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, size_bytes + 1)
    except (TypeError, ValueError, binascii.Error, zlib.error) as exc:
        raise ValueError("invalid compressed numerical input") from exc
    if len(raw) != size_bytes or not decoder.eof or decoder.unused_data:
        raise ValueError("numerical input data length does not match its shape")
    if hashlib.sha256(raw).hexdigest() != record["values_sha256"]:
        raise ValueError("numerical input values_sha256 does not match its data")
    array = np.frombuffer(raw, dtype="<f8").reshape(shape)
    if np.any(np.isinf(array)) or not np.any(np.isfinite(array)):
        raise ValueError("numerical input requires finite samples and no infinities")
    return array


def dm_semantic_hash(source_payload: str, backend_source_payload: str) -> str:
    """Bind every canonical DM input except the evaluated influence bytes.

    The backend hash also includes those bytes. Its full inner configuration,
    including reflective factors and synthesis conventions, is bound too.
    """
    config = _dm_payload_config(source_payload)
    semantic = {
        key: value for key, value in config.items()
        if key not in {"influence_functions", "backend_config_hash"}
    }
    backend = _decode_source_payload(
        backend_source_payload, f"{config['backend_name']}.dm_spatial_backend",
    )
    backend_semantic = {
        key: value for key, value in backend.items() if key != "influence_functions"
    }
    return stable_hash(
        {"model": semantic, "backend": backend_semantic},
        namespace="cross_backend_dm_semantics_v1",
    )


def _require_canonical_mapping_order(value: Any) -> None:
    if isinstance(value, dict):
        if "$mapping" in value:
            if set(value) != {"$mapping"}:
                raise ValueError("canonical mapping wrappers have no sibling keys")
            pairs = value["$mapping"]
            if not isinstance(pairs, list) or any(
                not isinstance(pair, list) or len(pair) != 2
                or not isinstance(pair[0], str) for pair in pairs
            ):
                raise ValueError("invalid canonical mapping")
            keys = [pair[0] for pair in pairs]
            if keys != sorted(set(keys)):
                raise ValueError("canonical mappings require unique sorted keys")
        for child in value.values():
            _require_canonical_mapping_order(child)
    elif isinstance(value, list):
        for child in value:
            _require_canonical_mapping_order(child)


def _decode_source_payload(
    source_payload: str, expected_component: str,
) -> dict[str, Any]:
    try:
        parsed = json.loads(source_payload)
        if json.dumps(
            parsed, ensure_ascii=False, allow_nan=False,
            sort_keys=True, separators=(",", ":"),
        ) != source_payload:
            raise ValueError("source payload is not canonical JSON")
        _require_canonical_mapping_order(parsed)
        envelope = dict(parsed["$mapping"])
        value = dict(envelope["value"]["$mapping"])
        if (
            set(envelope) != {"hash_schema", "namespace", "value"}
            or envelope["hash_schema"] != HASH_SCHEMA_ID
            or envelope["namespace"] != "component_config"
            or set(value) != {"component_name", "config"}
            or value["component_name"] != expected_component
        ):
            raise ValueError("unexpected DM hash envelope")
        return dict(value["config"]["$mapping"])
    except (TypeError, KeyError, ValueError) as exc:
        raise ValueError("invalid canonical DM source_payload") from exc


def _dm_payload_config(source_payload: str) -> dict[str, Any]:
    try:
        config = _decode_source_payload(source_payload, "deformable_mirror")
        if set(config) != {
            "config", "sampled_x_m", "sampled_y_m", "pupil_mask",
            "actuator_ids", "actuator_centers_m", "actuator_pitch_m",
            "dead_actuator_mask", "stuck_actuator_mask", "command_unit",
            "command_convention", "synthesis_convention", "backend_identity",
            "backend_name", "backend_config_hash", "influence_functions",
        }:
            raise ValueError("unexpected DM configuration fields")
        return config
    except (TypeError, KeyError, ValueError) as exc:
        raise ValueError("invalid canonical DM source_payload") from exc


def dm_source_failure(name: str, record: Mapping[str, Any]) -> str | None:
    """Verify the real DM hash payload, its influence bytes and semantics."""
    payload = record["source_payload"]
    if not isinstance(payload, str):
        return "missing canonical DM source_payload"
    if hashlib.sha256(payload.encode("utf-8")).hexdigest() != record["source_hash"]:
        return "raw DM hash does not match source_payload"
    try:
        config = _dm_payload_config(payload)
        backend_name = name.removesuffix("_dm")
        expected_class = (
            "shwfs_ao.backends.native.dm.NativeDmBackend"
            if backend_name == "native" else
            "shwfs_ao.backends.hcipy.dm.HcipyDmBackend"
        )
        if config["backend_name"] != backend_name or config["backend_identity"] != expected_class:
            return "DM source_payload does not match its named backend"
        descriptor = {"$array": stable_array_descriptor(numerical_input_values(record))}
        if config["influence_functions"] != descriptor:
            return "DM source_payload does not bind the witnessed influence array"
        backend_payload = record["backend_source_payload"]
        if not isinstance(backend_payload, str) or hashlib.sha256(
            backend_payload.encode("utf-8")
        ).hexdigest() != config["backend_config_hash"]:
            return "DM backend_config_hash does not match backend_source_payload"
        if _decode_source_payload(
            backend_payload, f"{backend_name}.dm_spatial_backend",
        ).get("influence_functions") != descriptor:
            return "DM backend source_payload does not bind the witnessed influence array"
        if dm_semantic_hash(payload, backend_payload) != record["configuration_hash"]:
            return "DM configuration_hash does not bind its semantic inputs"
    except ValueError as exc:
        return str(exc)
    return None


def numerical_input_failure(
    name: str, observed: Mapping[str, Any], expected: Mapping[str, Any],
) -> str | None:
    """Return an exact semantic or strict full-array reproduction failure."""
    if observed["configuration_hash"] != expected["configuration_hash"]:
        return "numerical input configuration_hash differs"
    actual = numerical_input_values(observed)
    reference = numerical_input_values(expected)
    if actual.shape != reference.shape:
        return f"shape observed={actual.shape} expected={reference.shape}"
    if not np.array_equal(np.isnan(actual), np.isnan(reference)):
        return "non-finite pupil-mask locations differ"
    _, units, rtol, atol = NUMERICAL_INPUTS[name]
    difference = np.where(np.isnan(reference), 0.0, np.abs(actual - reference))
    allowed = atol + rtol * np.nan_to_num(np.abs(reference))
    if np.any(difference > allowed):
        index = np.unravel_index(int(np.argmax(difference / allowed)), actual.shape)
        return (
            f"sample {index}: observed={actual[index]:.17g} "
            f"expected={reference[index]:.17g}; abs difference="
            f"{difference[index]:.6g} {units}, tolerance="
            f"{atol:g} {units} + {rtol:g} * abs(expected)"
        )
    return None
