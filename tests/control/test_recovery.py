"""Opt-in closed-loop recovery policy: settings, identity and per-frame rules."""

from __future__ import annotations

import numpy as np
import pytest

from shwfs_ao.control.recovery import (
    ClosedLoopRecoveryPolicy,
    RecoveryPolicyError,
    SubsetReconstructor,
)
from shwfs_ao.core.types import DmCommandVector


IDS = ("A0", "A1")


def _command(*values: float) -> DmCommandVector:
    return DmCommandVector(
        values_opd_m=np.asarray(values, dtype=float),
        actuator_ids=IDS,
        command_unit="m_opd_equivalent",
    )


class _Subset:
    config_hash = "subset-hash"
    matrix_hash = "matrix-hash"

    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[tuple[float, float | None]] = []

    def reconstruct_subset(self, measurement, *, min_valid_fraction, min_actuator_coverage=None):
        self.calls.append((min_valid_fraction, min_actuator_coverage))
        return self.result


def test_settings_are_validated():
    subset = _Subset(None)
    assert isinstance(subset, SubsetReconstructor)
    with pytest.raises(RecoveryPolicyError, match="at least one knob"):
        ClosedLoopRecoveryPolicy()
    with pytest.raises(RecoveryPolicyError, match="together"):
        ClosedLoopRecoveryPolicy(rejected_frames_before_decay=3)
    with pytest.raises(RecoveryPolicyError, match="together"):
        ClosedLoopRecoveryPolicy(fallback_min_valid_fraction=0.2)
    with pytest.raises(RecoveryPolicyError, match="together"):
        ClosedLoopRecoveryPolicy(gain_full_valid_fraction=0.9, fallback_reconstructor=subset)
    with pytest.raises(RecoveryPolicyError, match="needs fallback_min_valid_fraction"):
        ClosedLoopRecoveryPolicy(gain_full_valid_fraction=0.9, fallback_min_actuator_coverage=0.5)
    with pytest.raises(RecoveryPolicyError, match="non-negative"):
        ClosedLoopRecoveryPolicy(rejected_frames_before_decay=-1, decay_per_rejected_frame=1.0)
    with pytest.raises(RecoveryPolicyError, match="integer"):
        ClosedLoopRecoveryPolicy(rejected_frames_before_decay=True, decay_per_rejected_frame=1.0)
    for bad in (0.0, 1.5, float("nan")):
        with pytest.raises(RecoveryPolicyError, match=r"\(0, 1\]"):
            ClosedLoopRecoveryPolicy(gain_full_valid_fraction=bad)
    with pytest.raises(RecoveryPolicyError, match="reconstruct_subset"):
        ClosedLoopRecoveryPolicy(fallback_min_valid_fraction=0.2, fallback_reconstructor=object())  # type: ignore[arg-type]


def test_identity_covers_every_setting_and_the_fallback_reconstructor():
    first = ClosedLoopRecoveryPolicy(rejected_frames_before_decay=4, decay_per_rejected_frame=1.0)
    assert first.config_hash == ClosedLoopRecoveryPolicy(
        rejected_frames_before_decay=4, decay_per_rejected_frame=1.0
    ).config_hash
    others = {
        ClosedLoopRecoveryPolicy(rejected_frames_before_decay=5, decay_per_rejected_frame=1.0).config_hash,
        ClosedLoopRecoveryPolicy(rejected_frames_before_decay=4, decay_per_rejected_frame=0.5).config_hash,
        ClosedLoopRecoveryPolicy(gain_full_valid_fraction=0.9).config_hash,
        ClosedLoopRecoveryPolicy(
            fallback_min_valid_fraction=0.2, fallback_reconstructor=_Subset(None)
        ).config_hash,
        ClosedLoopRecoveryPolicy(
            fallback_min_valid_fraction=0.2,
            fallback_min_actuator_coverage=0.5,
            fallback_reconstructor=_Subset(None),
        ).config_hash,
    }
    assert first.config_hash not in others and len(others) == 5
    assert first.metadata["config_hash"] == first.config_hash


def test_decay_counts_consecutive_unused_frames_and_resets_on_a_used_one():
    policy = ClosedLoopRecoveryPolicy(rejected_frames_before_decay=2, decay_per_rejected_frame=0.25)
    request = _command(4.0, -8.0)
    assert policy.supervised_request(request, increment_used=True) is request
    assert policy.supervised_request(request, increment_used=False) is request
    assert policy.supervised_request(request, increment_used=False) is request
    decayed = policy.supervised_request(request, increment_used=False)
    np.testing.assert_array_equal(decayed.values_opd_m, [3.0, -6.0])
    assert decayed.actuator_ids == IDS
    assert policy.statistics["decayed_frames"] == 1
    assert policy.supervised_request(request, increment_used=True) is request
    assert policy.supervised_request(request, increment_used=False) is request
    policy.reset()
    assert dict(policy.statistics) == {"fallback_frames": 0, "decayed_frames": 0}


def test_gain_schedule_scales_below_the_full_gain_fraction_only():
    policy = ClosedLoopRecoveryPolicy(gain_full_valid_fraction=0.8)
    increment = _command(1.0, -2.0)
    assert policy.scaled_increment(increment, valid_fraction=0.9) is increment
    assert policy.scaled_increment(increment, valid_fraction=0.8) is increment
    np.testing.assert_allclose(
        policy.scaled_increment(increment, valid_fraction=0.2).values_opd_m, [0.25, -0.5]
    )
    unscheduled = ClosedLoopRecoveryPolicy(rejected_frames_before_decay=0, decay_per_rejected_frame=1.0)
    assert unscheduled.scaled_increment(increment, valid_fraction=0.1) is increment
    assert unscheduled.fallback(object()) is None  # type: ignore[arg-type]


def test_fallback_passes_its_threshold_and_guard_and_counts_used_frames():
    estimate = object()
    subset = _Subset(estimate)
    policy = ClosedLoopRecoveryPolicy(
        fallback_min_valid_fraction=0.2,
        fallback_min_actuator_coverage=0.5,
        fallback_reconstructor=subset,
    )
    assert policy.fallback(object()) is estimate  # type: ignore[arg-type]
    assert subset.calls == [(0.2, 0.5)]
    subset.result = None
    assert policy.fallback(object()) is None  # type: ignore[arg-type]
    assert policy.statistics["fallback_frames"] == 1
