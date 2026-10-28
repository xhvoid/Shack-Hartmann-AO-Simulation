from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

import numpy as np
import pytest

from shwfs_ao.core import hashing as hashing_module
from shwfs_ao.core.hashing import (
    HashingError,
    calibration_rows_hash,
    canonical_json_bytes,
    command_coordinates_hash,
    component_config_hash,
    geometry_hash,
    stable_array_descriptor,
    stable_hash,
)
from shwfs_ao.legacy.config_hashing import stable_array_descriptor as legacy_descriptor


def test_legacy_array_descriptor_is_the_canonical_function_and_stays_compatible() -> None:
    values = np.array([[0.0, -0.0], [np.nan, 3.5]], dtype=np.float32)
    equivalent = np.asfortranarray(
        np.array([[0.0, 0.0], [np.nan, 3.5]], dtype=np.float64)
    )

    assert legacy_descriptor is stable_array_descriptor
    assert stable_array_descriptor(values) == stable_array_descriptor(equivalent)
    assert stable_array_descriptor(values) == {
        "shape": [2, 2],
        "dtype": "float64",
        "sha256": "5abe4a295be66013242ff070e574317e3ccce1bb2f15d0c1e37efddc472c71ff",
    }


@dataclass(frozen=True)
class _Config:
    gain: float
    layout: np.ndarray


@dataclass(frozen=True)
class _OtherConfig:
    gain: float
    layout: np.ndarray


def test_canonical_hash_uses_declared_data_not_mapping_order_or_array_layout() -> None:
    first = {
        "config": _Config(0.4, np.arange(6, dtype=np.int16).reshape(2, 3)),
        "name": "sensor",
    }
    second = {
        "name": "sensor",
        "config": _Config(0.4, np.asfortranarray(np.arange(6).reshape(2, 3))),
    }

    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert stable_hash(first) == stable_hash(second)
    assert stable_hash({"value": -0.0}) == stable_hash({"value": 0.0})
    assert component_config_hash("sensor", first["config"]) != component_config_hash(
        "sensor",
        _OtherConfig(0.4, np.arange(6).reshape(2, 3)),
    )


def test_semantic_hash_namespaces_and_ordered_id_layouts_are_distinct() -> None:
    payload = {"diameter_m": 1.0, "shape": (32, 32)}
    assert geometry_hash(payload) != component_config_hash("geometry", payload)
    assert calibration_rows_hash(("s0:x", "s0:y")) != calibration_rows_hash(
        ("s0:y", "s0:x")
    )
    assert command_coordinates_hash(
        ("a0", "a1"),
        coordinate_kind="dm_command_opd",
        coordinate_unit="m_opd_equivalent",
    ) != command_coordinates_hash(
        ("a1", "a0"),
        coordinate_kind="dm_command_opd",
        coordinate_unit="m_opd_equivalent",
    )


def test_identity_helpers_reject_ambiguous_or_invalid_data() -> None:
    with pytest.raises(HashingError, match="duplicate"):
        calibration_rows_hash(("same", "same"))
    with pytest.raises(HashingError, match="valid_rows"):
        calibration_rows_hash(("x", "y"), valid_rows=np.array([True]))
    with pytest.raises(HashingError, match="coordinate_kind"):
        command_coordinates_hash(
            ("x",), coordinate_kind="meters", coordinate_unit="m_opd_rms"
        )
    with pytest.raises(HashingError, match="string keys"):
        stable_hash({1: "not canonical"})
    with pytest.raises(HashingError, match="Unsupported value"):
        stable_hash(object())
    with pytest.raises(HashingError, match="sets"):
        stable_hash({"unordered"})


def _historical_array_descriptor(values) -> dict:
    """Frozen copy of the single-buffer descriptor used before streaming."""

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
    else:
        canonical = array.astype(np.dtype("<c16"), copy=True)
        real = canonical.real
        imag = canonical.imag
        real[real == 0.0] = 0.0
        imag[imag == 0.0] = 0.0
        real[np.isnan(real)] = np.nan
        imag[np.isnan(imag)] = np.nan
        dtype_name = "complex128"
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


def _descriptor_cases() -> dict[str, np.ndarray]:
    rng = np.random.default_rng(20261015)
    floats = rng.normal(size=(5, 7, 3))
    floats[0, 0, 0] = -0.0
    floats[1, 2, 1] = 0.0
    floats[2, 3, 2] = np.nan
    floats[3, 4, 0] = np.inf
    floats[4, 6, 1] = -np.inf
    # A NaN with a non-default payload must canonicalize like any other NaN.
    floats[4, 5, 2] = np.frombuffer(np.uint64(0x7FF8000000000123).tobytes(), dtype=np.float64)[0]
    wide = rng.normal(size=(12, 9))
    complex_values = (rng.normal(size=(5, 3)) + 1j * rng.normal(size=(5, 3))).astype(np.complex128)
    complex_values[0, 0] = complex(-0.0, -0.0)
    complex_values[1, 1] = complex(np.nan, 1.0)
    complex_values[2, 2] = complex(2.0, np.nan)
    return {
        "float64_3d_specials": floats,
        "float32_fortran": np.asfortranarray(rng.normal(size=(6, 4)).astype(np.float32)),
        "float64_strided_view": wide[::2, 1::3],
        "float64_transposed": wide.T,
        "float64_big_endian": rng.normal(size=(4, 5)).astype(">f8"),
        "bool_2d": rng.random(size=(9, 2)) > 0.5,
        "int32_1d": rng.integers(-50, 50, size=7, dtype=np.int32),
        "uint16_3d": rng.integers(0, 1000, size=(3, 4, 2), dtype=np.uint16),
        "complex128_specials": complex_values,
        "float64_scalar": np.asarray(-0.0),
        "float64_empty": np.zeros((0, 3)),
        "float64_single": np.asarray([1.25]),
        "dense_stack_like": rng.random(size=(17, 6, 6)),
    }


@pytest.mark.parametrize("block_bytes", (1, 64, 1000, 16 * 1024**2))
@pytest.mark.parametrize("case", sorted(_descriptor_cases()))
def test_streamed_array_descriptor_matches_the_historical_single_buffer(
    monkeypatch, case, block_bytes
) -> None:
    """Hashing in leading-axis blocks digests exactly the historical bytes.

    A tiny block size forces one row per block; the default hashes every case
    in one block.  Either way the descriptor, digest included, is unchanged.
    """

    values = _descriptor_cases()[case]
    monkeypatch.setattr(hashing_module, "_HASH_BLOCK_BYTES", block_bytes)
    assert stable_array_descriptor(values) == _historical_array_descriptor(values)


def test_streamed_array_descriptor_still_refuses_unsupported_dtypes() -> None:
    with pytest.raises(TypeError, match="Unsupported array dtype"):
        stable_array_descriptor(np.array(["text"]))


def _stacked_item_sets() -> dict[str, list[np.ndarray]]:
    rng = np.random.default_rng(42)
    maps = [rng.normal(size=(4, 5)) for _ in range(6)]
    maps[1][0, 0] = -0.0
    maps[3][2, 2] = np.nan
    return {
        "float64_maps_with_specials": maps,
        "float32_big_endian": [rng.normal(size=(3, 3)).astype(">f4") for _ in range(4)],
        "bool_masks": [rng.random(size=(2, 7)) > 0.5 for _ in range(3)],
        "complex_vectors": [rng.normal(size=5) + 1j * rng.normal(size=5) for _ in range(3)],
        "scalars": [np.asarray(value) for value in (1.0, -0.0, np.nan)],
        "single_item": [rng.normal(size=(2, 2))],
    }


@pytest.mark.parametrize("case", sorted(_stacked_item_sets()))
def test_stacked_digest_hashes_exactly_like_the_stacked_array(case) -> None:
    from shwfs_ao.core.hashing import StackedArrayDigest

    items = _stacked_item_sets()[case]
    digest = StackedArrayDigest(len(items))
    for item in items:
        digest.add(item)
    descriptor = digest.descriptor()
    stacked = np.stack(items, axis=0)
    assert descriptor.as_mapping() == stable_array_descriptor(stacked)
    assert component_config_hash("stacked", {"maps": descriptor, "gain": 0.4}) == (
        component_config_hash("stacked", {"maps": stacked, "gain": 0.4})
    )


def test_stacked_digest_refuses_inconsistent_or_incomplete_stacks() -> None:
    from shwfs_ao.core.hashing import ArrayDescriptor, StackedArrayDigest

    with pytest.raises(HashingError, match="positive integer"):
        StackedArrayDigest(0)
    digest = StackedArrayDigest(2)
    digest.add(np.zeros((2, 2)))
    with pytest.raises(HashingError, match="shape and dtype"):
        digest.add(np.zeros((2, 3)))
    with pytest.raises(HashingError, match="shape and dtype"):
        digest.add(np.zeros((2, 2), dtype=np.float32))
    with pytest.raises(HashingError, match="1 of the declared 2"):
        digest.descriptor()
    digest.add(np.ones((2, 2)))
    with pytest.raises(HashingError, match="more than the declared"):
        digest.add(np.ones((2, 2)))
    with pytest.raises(TypeError, match="Unsupported array dtype"):
        StackedArrayDigest(1).add(np.array(["text"]))
    with pytest.raises(HashingError, match="dtype"):
        ArrayDescriptor(shape=(1,), dtype="float16", sha256="0" * 64)
    with pytest.raises(HashingError, match="sha256"):
        ArrayDescriptor(shape=(1,), dtype="float64", sha256="not-a-digest")
