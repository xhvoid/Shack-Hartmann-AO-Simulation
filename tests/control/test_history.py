"""Typed fixed-length AO-REF-009 loop-history invariants."""

from __future__ import annotations

from dataclasses import fields
from types import MappingProxyType

import numpy as np
import pytest

from shwfs_ao.control.history import LoopHistory, LoopHistoryError
from shwfs_ao.core.random import DERIVATION_SCHEME_ID


EXPECTED_FIELDS = (
    "time_s",
    "open_loop_opd_rms_m",
    "pre_update_residual_opd_rms_m",
    "post_update_residual_opd_rms_m",
    "command_norm_m",
    "delta_command_norm_m",
    "released_delta_norm_m",
    "requested_command_history_opd_m",
    "applied_command_history_opd_m",
    "saturation_fraction",
    "valid_measurement_fraction",
    "valid_subaperture_fraction",
    "reconstruction_usable",
    "measurement_row_masks",
    "config_hash",
    "metadata",
)


def _metadata() -> dict[str, object]:
    return {
        "field_units": {
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
        },
        "command_sign_convention": "positive_command_produces_positive_correction_opd",
        "residual_sign_convention": "atmosphere_opd_m - dm_correction_opd_m",
        "actuator_ids": ("A0", "A1"),
        "row_ids": ("R0", "R1", "R2"),
        "calibration_valid_rows": (True, True, False),
        "backend_names": {
            "atmosphere": "test-atmosphere",
            "wfs": "test-wfs",
            "dm": "test-dm",
        },
        "component_hashes": {
            "atmosphere": "atmosphere-hash",
            "wfs": "wfs-hash",
            "dm": "dm-hash",
            "interaction_matrix": "matrix-hash",
            "reconstructor": "matrix-hash",
            "command_projector": "projector-hash",
            "controller": "controller-hash",
        },
        "root_seed": 7,
        "frame_rate_hz": 10.0,
        "include_noise": True,
        "realization_index": 0,
        "random_derivation_scheme_id": DERIVATION_SCHEME_ID,
        "random_stream_ids": {
            "atmosphere": "atmosphere-stream-id",
            "detector.shot_noise": "shot-stream-id",
        },
    }


def _history(**overrides: object) -> LoopHistory:
    values: dict[str, object] = {
        "time_s": np.asarray([0.0, 0.1]),
        "open_loop_opd_rms_m": np.asarray([3.0, 3.0]),
        "pre_update_residual_opd_rms_m": np.asarray([3.0, 2.0]),
        "post_update_residual_opd_rms_m": np.asarray([2.0, 1.0]),
        "command_norm_m": np.asarray([0.0, np.sqrt(5.0)]),
        "delta_command_norm_m": np.asarray([1.0, 2.0]),
        "released_delta_norm_m": np.asarray([0.0, 1.0]),
        "requested_command_history_opd_m": np.asarray(
            [[0.0, 0.0], [1.0, 2.0]]
        ),
        "applied_command_history_opd_m": np.asarray(
            [[0.0, 0.0], [1.0, 2.0]]
        ),
        "saturation_fraction": np.asarray([0.0, 0.0]),
        "valid_measurement_fraction": np.asarray([0.5, 1.0]),
        "valid_subaperture_fraction": np.asarray([0.5, 1.0]),
        "reconstruction_usable": np.asarray([False, True], dtype=bool),
        "measurement_row_masks": np.asarray(
            [[True, False, False], [True, True, False]],
            dtype=bool,
        ),
        "config_hash": "a" * 64,
        "metadata": _metadata(),
    }
    values.update(overrides)
    return LoopHistory(**values)  # type: ignore[arg-type]


def test_history_has_exact_fields_cross_validates_masks_and_is_deeply_immutable() -> None:
    assert tuple(field.name for field in fields(LoopHistory)) == EXPECTED_FIELDS
    source = np.asarray([[0.0, 0.0], [1.0, 2.0]])
    history = _history(applied_command_history_opd_m=source)
    source[1, 0] = 999.0

    np.testing.assert_array_equal(
        history.applied_command_history_opd_m,
        [[0.0, 0.0], [1.0, 2.0]],
    )
    np.testing.assert_array_equal(history.valid_measurement_fraction, [0.5, 1.0])
    assert isinstance(history.metadata, MappingProxyType)
    assert isinstance(history.metadata["component_hashes"], MappingProxyType)
    with pytest.raises(TypeError):
        history.metadata["root_seed"] = 8  # type: ignore[index]

    for field_name in EXPECTED_FIELDS[:-2]:
        value = getattr(history, field_name)
        if isinstance(value, np.ndarray):
            assert not value.flags.writeable, field_name
            with pytest.raises(ValueError):
                value.setflags(write=True)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("time_s", np.asarray([0.0])),
        ("time_s", np.asarray([0.0, 0.2])),
        ("open_loop_opd_rms_m", np.asarray([1.0, np.nan])),
        ("post_update_residual_opd_rms_m", np.asarray([-1.0, 1.0])),
        ("command_norm_m", np.asarray([0.0, 0.0])),
        ("requested_command_history_opd_m", np.zeros((2, 3))),
        ("applied_command_history_opd_m", np.zeros((1, 2))),
        ("saturation_fraction", np.asarray([0.0, 1.1])),
        ("valid_measurement_fraction", np.asarray([0.0, 1.0])),
        ("valid_subaperture_fraction", np.asarray([-0.1, 1.0])),
        ("reconstruction_usable", np.asarray([0, 1], dtype=int)),
        ("measurement_row_masks", np.ones((2, 2), dtype=bool)),
        ("measurement_row_masks", np.ones((2, 3), dtype=int)),
        ("config_hash", "not-a-canonical-hash"),
    ],
)
def test_history_rejects_wrong_lengths_values_dtypes_or_derived_invariants(
    field_name: str,
    value: object,
) -> None:
    with pytest.raises(LoopHistoryError):
        _history(**{field_name: value})


def test_history_valid_measurement_denominator_is_calibration_valid_rows() -> None:
    # Nominal row count is three, but only two calibration rows are valid.
    # One usable row is therefore 1/2, not 1/3.
    with pytest.raises(LoopHistoryError, match="valid_measurement_fraction"):
        _history(valid_measurement_fraction=np.asarray([1.0 / 3.0, 2.0 / 3.0]))


@pytest.mark.parametrize(
    "missing_key",
    [
        "field_units",
        "command_sign_convention",
        "residual_sign_convention",
        "actuator_ids",
        "row_ids",
        "calibration_valid_rows",
        "backend_names",
        "component_hashes",
        "root_seed",
        "frame_rate_hz",
        "include_noise",
        "realization_index",
        "random_derivation_scheme_id",
        "random_stream_ids",
    ],
)
def test_history_metadata_requires_auditable_units_identity_hashes_and_streams(
    missing_key: str,
) -> None:
    metadata = _metadata()
    del metadata[missing_key]
    with pytest.raises(LoopHistoryError, match=missing_key):
        _history(metadata=metadata)


def test_history_metadata_identity_lengths_must_match_array_axes() -> None:
    wrong_actuators = _metadata()
    wrong_actuators["actuator_ids"] = ("A0",)
    with pytest.raises(LoopHistoryError, match="actuator_ids"):
        _history(metadata=wrong_actuators)

    wrong_rows = _metadata()
    wrong_rows["row_ids"] = ("R0", "R1")
    with pytest.raises(LoopHistoryError, match="row_ids"):
        _history(metadata=wrong_rows)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("field_units", {"time_s": "milliseconds"}),
        ("residual_sign_convention", "dm_correction_opd_m - atmosphere_opd_m"),
        ("command_sign_convention", "positive_command_is_negative_correction"),
        ("root_seed", True),
        ("root_seed", -1),
        ("realization_index", -1),
        ("include_noise", 1),
        ("random_derivation_scheme_id", ""),
        ("backend_names", {}),
        ("component_hashes", {}),
        ("random_stream_ids", {}),
    ],
)
def test_history_rejects_semantically_false_metadata(
    key: str,
    value: object,
) -> None:
    metadata = _metadata()
    metadata[key] = value
    with pytest.raises(LoopHistoryError, match=key):
        _history(metadata=metadata)
