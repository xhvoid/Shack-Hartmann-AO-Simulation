"""Opt-in closed-loop recovery when the reconstructor rejects frames.

Without a policy, a frame whose usable fraction is below the reconstructor's
``min_valid_fraction`` gives the controller ``None``; the controller enqueues
an exact zero, so with zero leak the DM holds its last shape for as long as
frames keep being rejected.  If that held shape keeps the spots outside the
validity domain, the loop never recovers (the detector-level E3 latch-up at
m_AB = 11).  :class:`ClosedLoopRecoveryPolicy` is a loop supervisor with three
independent knobs, each off unless set:

* **decay** -- after ``rejected_frames_before_decay`` consecutive frames with
  no usable increment, every further such frame multiplies the requested DM
  command by ``1 - decay_per_rejected_frame`` (``1`` resets it to flat).  The
  controller then synchronizes to the command the DM applied, as it always
  does, so its state follows the decay.
* **fallback** -- a rejected frame is reconstructed from its usable rows alone
  when their fraction is at least ``fallback_min_valid_fraction``, optionally
  guarded by ``fallback_min_actuator_coverage`` (only actuators that the
  usable rows still see are solved for; the rest hold).
* **gain schedule** -- every used increment is scaled by
  ``min(1, valid_fraction / gain_full_valid_fraction)``.

The policy is passed to :func:`shwfs_ao.control.run_closed_loop` explicitly;
a loop without one is unchanged in behaviour and identity.
"""

from __future__ import annotations

from collections.abc import Mapping
import math
from numbers import Integral, Real
from types import MappingProxyType
from typing import Protocol, runtime_checkable

import numpy as np

from ..core.hashing import component_config_hash
from ..core.types import DmCommandVector, MeasurementVector, ReconstructionEstimate


__all__ = (
    "ClosedLoopRecoveryPolicy",
    "RecoveryPolicyError",
    "SubsetReconstructor",
)


class RecoveryPolicyError(ValueError):
    """Raised when a recovery policy setting or its fallback is invalid."""


@runtime_checkable
class SubsetReconstructor(Protocol):
    """A reconstructor that can solve from a frame's usable rows alone."""

    @property
    def config_hash(self) -> str:
        ...

    @property
    def matrix_hash(self) -> str:
        ...

    def reconstruct_subset(
        self,
        measurement: MeasurementVector,
        *,
        min_valid_fraction: float,
        min_actuator_coverage: float | None = None,
    ) -> ReconstructionEstimate | None:
        ...


class ClosedLoopRecoveryPolicy:
    """Stateful loop supervisor for frames the reconstructor rejects."""

    def __init__(
        self,
        *,
        rejected_frames_before_decay: int | None = None,
        decay_per_rejected_frame: float | None = None,
        fallback_min_valid_fraction: float | None = None,
        fallback_min_actuator_coverage: float | None = None,
        gain_full_valid_fraction: float | None = None,
        fallback_reconstructor: SubsetReconstructor | None = None,
    ) -> None:
        if (rejected_frames_before_decay is None) != (decay_per_rejected_frame is None):
            raise RecoveryPolicyError(
                "rejected_frames_before_decay and decay_per_rejected_frame are "
                "set together or not at all."
            )
        hold = (
            None
            if rejected_frames_before_decay is None
            else _integer(rejected_frames_before_decay, label="rejected_frames_before_decay")
        )
        decay = (
            None
            if decay_per_rejected_frame is None
            else _unit_interval(decay_per_rejected_frame, label="decay_per_rejected_frame")
        )
        fallback = (
            None
            if fallback_min_valid_fraction is None
            else _unit_interval(fallback_min_valid_fraction, label="fallback_min_valid_fraction")
        )
        coverage = (
            None
            if fallback_min_actuator_coverage is None
            else _unit_interval(fallback_min_actuator_coverage, label="fallback_min_actuator_coverage")
        )
        full_gain = (
            None
            if gain_full_valid_fraction is None
            else _unit_interval(gain_full_valid_fraction, label="gain_full_valid_fraction")
        )
        if coverage is not None and fallback is None:
            raise RecoveryPolicyError(
                "fallback_min_actuator_coverage needs fallback_min_valid_fraction."
            )
        if (fallback is None) != (fallback_reconstructor is None):
            raise RecoveryPolicyError(
                "fallback_min_valid_fraction and fallback_reconstructor are set "
                "together or not at all."
            )
        if fallback_reconstructor is not None and not isinstance(
            fallback_reconstructor, SubsetReconstructor
        ):
            raise RecoveryPolicyError(
                "fallback_reconstructor must provide reconstruct_subset()."
            )
        if hold is None and fallback is None and full_gain is None:
            raise RecoveryPolicyError("a recovery policy needs at least one knob set.")
        self._hold = hold
        self._decay = decay
        self._fallback = fallback
        self._coverage = coverage
        self._full_gain = full_gain
        self._fallback_reconstructor = fallback_reconstructor
        settings: dict[str, object] = {
            "rejected_frames_before_decay": hold,
            "decay_per_rejected_frame": decay,
            "fallback_min_valid_fraction": fallback,
            "fallback_min_actuator_coverage": coverage,
            "gain_full_valid_fraction": full_gain,
            "fallback_reconstructor_hash": (
                None if fallback_reconstructor is None else fallback_reconstructor.config_hash
            ),
            "decay_policy": "scale_requested_command_after_consecutive_unused_frames",
            "gain_schedule": "min_1_valid_fraction_over_full_gain_fraction",
        }
        self._config_hash = component_config_hash(
            "control.closed_loop_recovery_policy", settings
        )
        self._metadata: Mapping[str, object] = MappingProxyType(
            {**settings, "config_hash": self._config_hash}
        )
        self._unused_streak = 0
        self._fallback_frames = 0
        self._decayed_frames = 0

    @property
    def config_hash(self) -> str:
        return self._config_hash

    @property
    def metadata(self) -> Mapping[str, object]:
        return self._metadata

    @property
    def fallback_reconstructor(self) -> SubsetReconstructor | None:
        return self._fallback_reconstructor

    @property
    def statistics(self) -> Mapping[str, int]:
        """Frames of the current run that used the fallback or decayed."""

        return MappingProxyType(
            {
                "fallback_frames": self._fallback_frames,
                "decayed_frames": self._decayed_frames,
            }
        )

    def reset(self) -> None:
        self._unused_streak = 0
        self._fallback_frames = 0
        self._decayed_frames = 0

    def fallback(self, measurement: MeasurementVector) -> ReconstructionEstimate | None:
        """Reconstruct a frame the reconstructor rejected, if the policy allows."""

        if self._fallback_reconstructor is None or self._fallback is None:
            return None
        estimate = self._fallback_reconstructor.reconstruct_subset(
            measurement,
            min_valid_fraction=self._fallback,
            min_actuator_coverage=self._coverage,
        )
        if estimate is not None:
            self._fallback_frames += 1
        return estimate

    def scaled_increment(
        self,
        increment: DmCommandVector,
        *,
        valid_fraction: float,
    ) -> DmCommandVector:
        """Apply the gain schedule to a used increment."""

        if self._full_gain is None:
            return increment
        scale = min(1.0, float(valid_fraction) / self._full_gain)
        if scale == 1.0:
            return increment
        return DmCommandVector(
            values_opd_m=scale * np.asarray(increment.values_opd_m, dtype=float),
            actuator_ids=increment.actuator_ids,
            command_unit=increment.command_unit,
        )

    def supervised_request(
        self,
        requested: DmCommandVector,
        *,
        increment_used: bool,
    ) -> DmCommandVector:
        """Return the command to send the DM after this frame's controller update."""

        if increment_used:
            self._unused_streak = 0
            return requested
        self._unused_streak += 1
        if self._hold is None or self._decay is None or self._unused_streak <= self._hold:
            return requested
        self._decayed_frames += 1
        return DmCommandVector(
            values_opd_m=(1.0 - self._decay) * np.asarray(requested.values_opd_m, dtype=float),
            actuator_ids=requested.actuator_ids,
            command_unit=requested.command_unit,
        )


def _integer(value: object, *, label: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise RecoveryPolicyError(f"{label} must be an integer.")
    result = int(value)
    if result < 0:
        raise RecoveryPolicyError(f"{label} must be non-negative.")
    return result


def _unit_interval(value: object, *, label: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise RecoveryPolicyError(f"{label} must be a real number.")
    result = float(value)
    if not math.isfinite(result) or not 0.0 < result <= 1.0:
        raise RecoveryPolicyError(f"{label} must be in (0, 1].")
    return result
