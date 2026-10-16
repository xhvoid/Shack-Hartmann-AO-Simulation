"""Opt-in ``controller.recovery`` block (schema v7): identity, parsing, pairing."""

from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from shwfs_ao.io.configs import (
    RecoveryPolicyConfig,
    SystemConfigError,
    load_system_profile,
    system_config_from_mapping,
    system_config_to_mapping,
)


# det_emccd_12m_medium_derived@2's controller identity before the block existed.
PUBLISHED_CONTROLLER_HASH = "5813570627e4b75e588081cf0ddc119f8467bc5af488342ccfe245468670da3a"


def _policy(**fields: object) -> RecoveryPolicyConfig:
    values: dict[str, object] = {
        "rejected_frames_before_decay": None,
        "decay_per_rejected_frame": None,
        "fallback_min_valid_fraction": None,
        "fallback_min_actuator_coverage": None,
        "gain_full_valid_fraction": None,
    }
    values.update(fields)
    return RecoveryPolicyConfig(**values)  # type: ignore[arg-type]


def _with_recovery(config, policy):
    return replace(config, controller=replace(config.controller, recovery=policy))


def test_a_controller_without_recovery_keeps_its_published_identity() -> None:
    config = load_system_profile("det_emccd_12m_medium_derived", 2)
    assert config.controller.recovery is None
    assert config.controller.config_hash == PUBLISHED_CONTROLLER_HASH
    assert config.component_config_hashes["controller"] == PUBLISHED_CONTROLLER_HASH
    assert "recovery" not in system_config_to_mapping(config)["config"]["controller"]


def test_a_recovery_block_round_trips_and_changes_the_identity() -> None:
    config = load_system_profile("det_emccd_12m_medium_derived", 2)
    policies = (
        _policy(rejected_frames_before_decay=4, decay_per_rejected_frame=1.0),
        _policy(fallback_min_valid_fraction=0.1, fallback_min_actuator_coverage=0.5),
        _policy(fallback_min_valid_fraction=0.1, gain_full_valid_fraction=0.9),
    )
    hashes = set()
    for policy in policies:
        recovered = _with_recovery(config, policy)
        record = system_config_to_mapping(recovered)
        assert set(record["config"]["controller"]["recovery"]) == {
            "rejected_frames_before_decay",
            "decay_per_rejected_frame",
            "fallback_min_valid_fraction",
            "fallback_min_actuator_coverage",
            "gain_full_valid_fraction",
        }
        again = system_config_from_mapping(copy.deepcopy(record))
        assert again == recovered and again.config_hash == recovered.config_hash
        assert recovered.component_config_hashes["controller"] != PUBLISHED_CONTROLLER_HASH
        hashes.add(recovered.config_hash)
    assert config.config_hash not in hashes and len(hashes) == len(policies)


def test_older_records_cannot_carry_the_block() -> None:
    policy = _policy(rejected_frames_before_decay=4, decay_per_rejected_frame=1.0)
    older_config = load_system_profile("fast_2m_detector", 1)
    assert older_config.record_schema_version < 7
    with pytest.raises(SystemConfigError, match="cannot express controller.recovery"):
        _with_recovery(older_config, policy)
    config = _with_recovery(load_system_profile("det_emccd_12m_medium_derived", 2), policy)
    older = copy.deepcopy(system_config_to_mapping(older_config))
    older["config"]["controller"]["recovery"] = system_config_to_mapping(config)["config"]["controller"]["recovery"]
    with pytest.raises(SystemConfigError, match="fields mismatch"):
        system_config_from_mapping(older)


@pytest.mark.parametrize(
    ("fields", "message"),
    (
        ({}, "sets no policy"),
        ({"rejected_frames_before_decay": 3}, "together or not at all"),
        ({"decay_per_rejected_frame": 0.5}, "together or not at all"),
        ({"rejected_frames_before_decay": 3, "decay_per_rejected_frame": 1.5}, "at most 1"),
        ({"rejected_frames_before_decay": 3, "decay_per_rejected_frame": 0.0}, "positive"),
        ({"rejected_frames_before_decay": -1, "decay_per_rejected_frame": 1.0}, ">= 0"),
        ({"fallback_min_actuator_coverage": 0.5, "gain_full_valid_fraction": 0.9}, "needs recovery.fallback_min_valid_fraction"),
        ({"fallback_min_valid_fraction": 1.2}, "at most 1"),
        ({"gain_full_valid_fraction": 0.0}, "positive"),
    ),
)
def test_malformed_policies_are_rejected(fields: dict[str, object], message: str) -> None:
    with pytest.raises(SystemConfigError, match=message):
        _policy(**fields)


def test_the_fallback_pairs_with_the_sparse_solver_below_its_threshold() -> None:
    sparse = load_system_profile("det_emccd_12m_medium_derived", 2)
    with pytest.raises(SystemConfigError, match="below reconstructor.min_valid_fraction"):
        _with_recovery(sparse, _policy(fallback_min_valid_fraction=0.5))
    dense = load_system_profile("det_ccd_2m_synthetic", 1)
    assert dense.reconstructor.kind != "sparse_lsmr_tikhonov"
    with pytest.raises(SystemConfigError, match="sparse_lsmr_tikhonov"):
        _with_recovery(dense, _policy(fallback_min_valid_fraction=0.1))
    # Decay and the gain schedule alone need no fallback and pair with any solver.
    _with_recovery(dense, _policy(rejected_frames_before_decay=2, decay_per_rejected_frame=0.5))
    _with_recovery(dense, _policy(gain_full_valid_fraction=0.9))
    record = copy.deepcopy(system_config_to_mapping(_with_recovery(sparse, _policy(gain_full_valid_fraction=0.9))))
    record["config"]["controller"]["recovery"]["unknown"] = 1
    with pytest.raises(SystemConfigError, match="fields mismatch"):
        system_config_from_mapping(record)
