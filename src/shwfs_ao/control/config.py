"""Configuration for backend-independent adaptive-optics control loops."""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real

import numpy as np

from ..core.hashing import component_config_hash


__all__ = ("LoopConfigError", "LoopConfig")


class LoopConfigError(ValueError):
    """Raised when a canonical control-loop setting is invalid."""


@dataclass(frozen=True)
class LoopConfig:
    """Immutable timing, controller, and replay settings for one loop run."""

    n_steps: int
    gain: float
    leak: float
    latency_frames: int
    frame_rate_hz: float
    root_seed: int

    def __post_init__(self) -> None:
        n_steps = _integer(self.n_steps, label="n_steps", minimum=1)
        gain = _finite(self.gain, label="gain")
        if gain < 0.0:
            raise LoopConfigError("gain must be non-negative.")
        leak = _finite(self.leak, label="leak")
        if not 0.0 <= leak < 1.0:
            raise LoopConfigError("leak must satisfy 0 <= leak < 1.")
        latency_frames = _integer(
            self.latency_frames,
            label="latency_frames",
            minimum=0,
        )
        frame_rate_hz = _finite(self.frame_rate_hz, label="frame_rate_hz")
        if frame_rate_hz <= 0.0:
            raise LoopConfigError("frame_rate_hz must be positive.")
        root_seed = _integer(self.root_seed, label="root_seed", minimum=0)

        object.__setattr__(self, "n_steps", n_steps)
        object.__setattr__(self, "gain", gain)
        object.__setattr__(self, "leak", leak)
        object.__setattr__(self, "latency_frames", latency_frames)
        object.__setattr__(self, "frame_rate_hz", frame_rate_hz)
        object.__setattr__(self, "root_seed", root_seed)

    @property
    def config_hash(self) -> str:
        """Return a deterministic hash of every serialized loop setting."""

        return component_config_hash("control.loop_config", self)

    @property
    def frame_period_s(self) -> float:
        return 1.0 / self.frame_rate_hz

    @property
    def latency_s(self) -> float:
        return self.latency_frames / self.frame_rate_hz


def _integer(value: object, *, label: str, minimum: int) -> int:
    if type(value) is not int:
        raise LoopConfigError(f"{label} must be an integer.")
    if value < minimum:
        raise LoopConfigError(f"{label} must be at least {minimum}.")
    return value


def _finite(value: object, *, label: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise LoopConfigError(f"{label} must be a finite real number.")
    result = float(value)
    if not math.isfinite(result):
        raise LoopConfigError(f"{label} must be finite.")
    return result
