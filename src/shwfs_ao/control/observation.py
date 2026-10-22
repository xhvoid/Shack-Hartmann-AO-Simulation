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

``measurement_row_mask``
    The frame's effective measurement rows (boolean, one entry per
    interaction-matrix row, the row the history stores in
    ``measurement_row_masks``): calibration-valid, runtime-valid and finite.
``detector_telemetry``
    The :class:`~shwfs_ao.core.types.DetectorTelemetry` the sensor produced
    for frame ``k``, as a detached, deeply immutable snapshot (every nested
    array is bytes-backed and read-only, every mapping a read-only proxy), or
    ``None`` when the sensor produced none.  Availability is the sensor's:
    a geometric sensor never provides it.

Only the fields named in an observer's ``requested_fields`` are copied, and a
field is copied once per frame however many observers request it.  Each
snapshot is a read-only array backed by an immutable buffer, so neither the
observer nor anything it retains can be changed by later frames.  The two
fields added for the S4 traced experiment (T1, 2026-10-20) are observed at
the same point and under the same passivity contract: they are copies of
what the loop already computed for the frame, no component is reached, no
draw is made and no identity moves.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass, replace
import math
from numbers import Integral, Real
from types import MappingProxyType
from typing import Final, Protocol, runtime_checkable

import numpy as np

from ..core.types import DetectorTelemetry, is_immutable_buffer_array


__all__ = (
    "OBSERVABLE_FIELDS",
    "OBSERVABLE_MAP_FIELDS",
    "OBSERVATION_POINT",
    "FrameObservationError",
    "FrameObservation",
    "FrameObserver",
    "validate_frame_observers",
    "immutable_snapshot",
    "immutable_mask_snapshot",
    "immutable_detector_telemetry",
)


# The three OPD maps (float64, NaN outside the pupil).
OBSERVABLE_MAP_FIELDS: Final = (
    "atmosphere_opd_m",
    "pre_update_residual_opd_m",
    "post_update_residual_opd_m",
)
OBSERVABLE_FIELDS: Final = (
    *OBSERVABLE_MAP_FIELDS,
    "measurement_row_mask",
    "detector_telemetry",
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


def immutable_mask_snapshot(values: np.ndarray) -> np.ndarray:
    """Return a boolean copy whose buffer can never be made writeable.

    The input must already be boolean: a mask is never cast from numbers.
    """

    if not isinstance(values, np.ndarray) or values.dtype != np.dtype(bool):
        raise FrameObservationError("a row mask snapshot needs a boolean array.")
    contiguous = np.ascontiguousarray(values)
    return np.frombuffer(contiguous.tobytes(order="C"), dtype=bool).reshape(
        contiguous.shape
    )


def immutable_detector_telemetry(value: DetectorTelemetry) -> DetectorTelemetry:
    """Return a detached, deeply immutable copy of a sensor's telemetry.

    Every array is copied once onto a fresh bytes-backed, read-only buffer
    (the result-type validators do that on construction), every nested
    frame and spot record is rebuilt the same way, and every mapping becomes
    a read-only proxy over a private copy.  The copy is then checked with
    :func:`_require_deeply_immutable`, so a telemetry type that grew a
    mutable field would be refused here rather than handed to an observer.
    """

    if not isinstance(value, DetectorTelemetry):
        raise FrameObservationError("detector telemetry must be a DetectorTelemetry.")
    frames = value.detector_frames
    if frames is not None:
        frames = tuple(
            replace(
                frame,
                random_stream_ids=MappingProxyType(dict(frame.random_stream_ids)),
            )
            for frame in frames
        )
    spots = value.optical_spots
    if spots is not None:
        spots = replace(spots)
    snapshot = replace(value, detector_frames=frames, optical_spots=spots)
    _require_deeply_immutable(snapshot, label="detector_telemetry")
    return snapshot


def _require_deeply_immutable(value: object, *, label: str) -> None:
    """Raise unless ``value`` holds only immutable leaves, arrays included."""

    if value is None or isinstance(value, (str, bytes, bool, int, float)):
        return
    if isinstance(value, np.ndarray):
        if not is_immutable_buffer_array(value, dtype=value.dtype):
            raise FrameObservationError(
                f"{label} must be a read-only, bytes-backed array snapshot."
            )
        return
    if isinstance(value, np.generic):
        return
    if isinstance(value, tuple):
        for index, item in enumerate(value):
            _require_deeply_immutable(item, label=f"{label}[{index}]")
        return
    if isinstance(value, Mapping):
        if not isinstance(value, MappingProxyType):
            raise FrameObservationError(f"{label} must be a read-only mapping.")
        for key, item in value.items():
            _require_deeply_immutable(item, label=f"{label}[{key!r}]")
        return
    if is_dataclass(value) and not isinstance(value, type):
        params = getattr(type(value), "__dataclass_params__", None)
        if params is None or not params.frozen:
            raise FrameObservationError(f"{label} must be a frozen dataclass.")
        for field in fields(value):
            _require_deeply_immutable(
                getattr(value, field.name), label=f"{label}.{field.name}"
            )
        return
    raise FrameObservationError(
        f"{label} holds a {type(value).__name__}, which cannot be shown immutable."
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


def _optional_mask(value: object, *, label: str) -> np.ndarray | None:
    if value is None:
        return None
    if not isinstance(value, np.ndarray) or value.ndim != 1:
        raise FrameObservationError(f"{label} must be a 1-D array or None.")
    if value.dtype != np.dtype(bool):
        raise FrameObservationError(f"{label} must be boolean.")
    if value.flags.writeable:
        raise FrameObservationError(f"{label} must be a read-only snapshot.")
    return value


def _optional_telemetry(value: object, *, label: str) -> DetectorTelemetry | None:
    if value is None:
        return None
    if not isinstance(value, DetectorTelemetry):
        raise FrameObservationError(f"{label} must be a DetectorTelemetry or None.")
    _require_deeply_immutable(value, label=label)
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
    # S4 traced experiment (T1): the frame's effective row mask (boolean,
    # read-only) and the sensor's telemetry of the frame (a detached, deeply
    # immutable snapshot); each only when requested, else None.
    measurement_row_mask: np.ndarray | None = None
    detector_telemetry: DetectorTelemetry | None = None

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
            _optional_map(getattr(self, name), label=name)
            for name in OBSERVABLE_MAP_FIELDS
        ]
        shapes = {item.shape for item in maps if item is not None}
        if len(shapes) > 1:
            raise FrameObservationError("observed maps must share one shape.")
        _optional_mask(self.measurement_row_mask, label="measurement_row_mask")
        _optional_telemetry(self.detector_telemetry, label="detector_telemetry")
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
