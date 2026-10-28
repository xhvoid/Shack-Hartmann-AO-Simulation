from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

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
