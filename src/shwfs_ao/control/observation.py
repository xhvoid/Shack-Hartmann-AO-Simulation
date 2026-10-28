"""Passive per-frame observation of the canonical closed loop.

An observer receives, once per frame, immutable snapshots of maps the loop has
already computed for that frame.  It cannot reach the live atmosphere, random
streams, WFS, controller, or DM, and it cannot change what the loop does: the
loop's telemetry and run hash are identical with no observer, a no-op
observer, or any number of observers.

Observation point
-----------------
For frame ``k`` (sampled once at ``time_s = k / frame_rate_hz``) the loop
calls every observer after the DM has applied the frame's update and the
frame's telemetry has been recorded, before frame ``k + 1`` samples the
atmosphere.  At that point:

``atmosphere_opd_m``
    The single atmospheric OPD sample of frame ``k`` (metres, NaN outside the
    pupil).
``pre_update_residual_opd_m``
    ``atmosphere_opd_m`` minus the DM correction that was applied while frame
    ``k`` was measured, i.e. the residual the WFS saw.
``post_update_residual_opd_m``
    ``atmosphere_opd_m`` minus the correction after frame ``k``'s update was
    applied (after stroke clipping and actuator faults).  It is the same
    atmospheric sample with a newer correction, a same-sample diagnostic, not
    a later exposure.

Only the fields named in an observer's ``requested_fields`` are copied, and a
field is copied once per frame however many observers request it.  Each
snapshot is a read-only array backed by an immutable buffer, so neither the
observer nor anything it retains can be changed by later frames.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import math
from numbers import Integral, Real
from typing import Final, Protocol, runtime_checkable

import numpy as np


__all__ = (
    "OBSERVABLE_FIELDS",
    "OBSERVATION_POINT",
    "FrameObservationError",
    "FrameObservation",
    "FrameObserver",
    "validate_frame_observers",
    "immutable_snapshot",
)


OBSERVABLE_FIELDS: Final = (
    "atmosphere_opd_m",
    "pre_update_residual_opd_m",
    "post_update_residual_opd_m",
)
OBSERVATION_POINT: Final = (
    "after_frame_dm_update_and_telemetry_before_next_atmosphere_sample"
)


class FrameObservationError(ValueError):
    """Raised for an invalid observer or a malformed frame observation."""


def immutable_snapshot(values: np.ndarray) -> np.ndarray:
    """Return a float64 copy whose buffer can never be made writeable."""

    contiguous = np.ascontiguousarray(np.asarray(values, dtype=float))
    return np.frombuffer(contiguous.tobytes(order="C"), dtype=float).reshape(
        contiguous.shape
    )


def _optional_map(value: object, *, label: str) -> np.ndarray | None:
    if value is None:
        return None
    if not isinstance(value, np.ndarray) or value.ndim != 2:
        raise FrameObservationError(f"{label} must be a 2-D array or None.")
    if value.dtype != np.dtype(float):
        raise FrameObservationError(f"{label} must be float64.")
    if value.flags.writeable:
        raise FrameObservationError(f"{label} must be a read-only snapshot.")
    return value


@dataclass(frozen=True)
class FrameObservation:
    """Immutable maps and scalars of one completed loop frame.

    ``latency_frames`` is the controller's queue length.  A reconstruction
    from frame ``k`` is first applied in the update of frame ``k +
    latency_frames`` and first seen by the WFS at frame ``k + latency_frames
    + 1``.  ``reconstruction_usable`` is false when the reconstructor failed
    closed on this frame; ``saturation_fraction`` is the applied command's
    clipped-actuator fraction.
    """

    frame_index: int
    time_s: float
    frame_period_s: float
    latency_frames: int
    reconstruction_usable: bool
    saturation_fraction: float
    atmosphere_opd_m: np.ndarray | None = None
    pre_update_residual_opd_m: np.ndarray | None = None
    post_update_residual_opd_m: np.ndarray | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.frame_index, bool)
            or not isinstance(self.frame_index, Integral)
            or int(self.frame_index) < 0
        ):
            raise FrameObservationError("frame_index must be a non-negative integer.")
        for label, value, positive in (
            ("time_s", self.time_s, False),
            ("frame_period_s", self.frame_period_s, True),
            ("saturation_fraction", self.saturation_fraction, False),
        ):
            if isinstance(value, bool) or not isinstance(value, Real):
                raise FrameObservationError(f"{label} must be a real number.")
            number = float(value)
            if not math.isfinite(number) or number < 0.0 or (positive and number == 0.0):
                raise FrameObservationError(f"{label} must be finite and non-negative.")
        if (
            isinstance(self.latency_frames, bool)
            or not isinstance(self.latency_frames, Integral)
            or int(self.latency_frames) < 0
        ):
            raise FrameObservationError("latency_frames must be a non-negative integer.")
        if not isinstance(self.reconstruction_usable, (bool, np.bool_)):
            raise FrameObservationError("reconstruction_usable must be a boolean.")
        maps = [
            _optional_map(getattr(self, name), label=name) for name in OBSERVABLE_FIELDS
        ]
        shapes = {item.shape for item in maps if item is not None}
        if len(shapes) > 1:
            raise FrameObservationError("observed maps must share one shape.")
        object.__setattr__(self, "frame_index", int(self.frame_index))
        object.__setattr__(self, "time_s", float(self.time_s))
        object.__setattr__(self, "frame_period_s", float(self.frame_period_s))
        object.__setattr__(self, "latency_frames", int(self.latency_frames))
        object.__setattr__(self, "reconstruction_usable", bool(self.reconstruction_usable))
        object.__setattr__(self, "saturation_fraction", float(self.saturation_fraction))


@runtime_checkable
class FrameObserver(Protocol):
    """A passive consumer of :class:`FrameObservation` events."""

    @property
    def requested_fields(self) -> frozenset[str]:
        """Names from :data:`OBSERVABLE_FIELDS` this observer needs."""

    def observe(self, observation: FrameObservation) -> None:
        """Consume one frame; raising aborts the run with frame context."""


def validate_frame_observers(
    observers: Sequence[FrameObserver],
) -> tuple[tuple[FrameObserver, ...], frozenset[str]]:
    """Validate observers before a run and return the union of requested fields."""

    if isinstance(observers, (str, bytes)) or not isinstance(observers, Sequence):
        raise FrameObservationError("observers must be a sequence of FrameObserver.")
    resolved: list[FrameObserver] = []
    requested: set[str] = set()
    for index, observer in enumerate(observers):
        if not isinstance(observer, FrameObserver):
            raise FrameObservationError(
                f"observers[{index}] does not implement FrameObserver."
            )
        fields = observer.requested_fields
        if not isinstance(fields, frozenset) or any(
            not isinstance(name, str) for name in fields
        ):
            raise FrameObservationError(
                f"observers[{index}].requested_fields must be a frozenset of names."
            )
        unknown = sorted(set(fields) - set(OBSERVABLE_FIELDS))
        if unknown:
            raise FrameObservationError(
                f"observers[{index}] requests unknown fields {unknown}; "
                f"observable fields are {list(OBSERVABLE_FIELDS)}."
            )
        requested |= fields
        resolved.append(observer)
    return tuple(resolved), frozenset(requested)
