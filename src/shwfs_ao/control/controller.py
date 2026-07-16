"""Stateful latency-aware leaky-integrator controller."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
import math
from numbers import Integral, Real
from types import MappingProxyType

import numpy as np

from ..core.hashing import component_config_hash
from ..core.types import DmCommandVector
from .config import LoopConfig


__all__ = ("ControllerError", "LeakyIntegratorController")


_COMMAND_UNIT = "m_opd_equivalent"


class ControllerError(ValueError):
    """Raised when controller configuration, identity, or state is invalid."""


class LeakyIntegratorController:
    """Apply gain, leak, and exact frame latency to full-layout increments."""

    def __init__(
        self,
        actuator_ids: tuple[str, ...],
        *,
        gain: float,
        leak: float,
        latency_frames: int,
    ) -> None:
        identifiers = _ids(actuator_ids)
        gain_value = _finite(gain, label="gain")
        if gain_value < 0.0:
            raise ControllerError("gain must be non-negative.")
        leak_value = _finite(leak, label="leak")
        if not 0.0 <= leak_value < 1.0:
            raise ControllerError("leak must satisfy 0 <= leak < 1.")
        latency = _integer(latency_frames, label="latency_frames", minimum=0)
        self._actuator_ids = identifiers
        self._gain = gain_value
        self._leak = leak_value
        self._latency_frames = latency
        self._config_hash = component_config_hash(
            "control.leaky_integrator_controller",
            {
                "actuator_ids": identifiers,
                "command_unit": _COMMAND_UNIT,
                "gain": gain_value,
                "leak": leak_value,
                "latency_frames": latency,
                "none_policy": "enqueue_exact_zero_and_advance",
                "state_policy": "start_each_update_from_last_dm_applied_command",
            },
        )
        self._metadata: Mapping[str, object] = MappingProxyType(
            {
                "controller_kind": "leaky_integrator",
                "actuator_ids": identifiers,
                "command_unit": _COMMAND_UNIT,
                "gain": gain_value,
                "leak": leak_value,
                "latency_frames": latency,
                "config_hash": self._config_hash,
            }
        )
        self._delay_queue: deque[np.ndarray] = deque()
        self._last_applied = np.empty(0, dtype=float)
        self._last_released = np.empty(0, dtype=float)
        self._last_requested = np.empty(0, dtype=float)
        self._step_index = 0
        self._awaiting_applied_acknowledgement = False
        self.reset()

    @classmethod
    def from_loop_config(
        cls,
        actuator_ids: tuple[str, ...],
        config: LoopConfig,
    ) -> LeakyIntegratorController:
        if not isinstance(config, LoopConfig):
            raise ControllerError("config must be a LoopConfig.")
        return cls(
            actuator_ids,
            gain=config.gain,
            leak=config.leak,
            latency_frames=config.latency_frames,
        )

    @property
    def config_hash(self) -> str:
        return self._config_hash

    @property
    def actuator_ids(self) -> tuple[str, ...]:
        return self._actuator_ids

    @property
    def gain(self) -> float:
        return self._gain

    @property
    def leak(self) -> float:
        return self._leak

    @property
    def latency_frames(self) -> int:
        return self._latency_frames

    @property
    def step_index(self) -> int:
        return self._step_index

    @property
    def metadata(self) -> Mapping[str, object]:
        return self._metadata

    @property
    def last_applied_commands(self) -> DmCommandVector:
        return self._command(self._last_applied)

    @property
    def last_released_delta(self) -> DmCommandVector:
        return self._command(self._last_released)

    @property
    def last_requested_commands(self) -> DmCommandVector:
        return self._command(self._last_requested)

    def reset(self) -> None:
        """Clear queue and command state to exact full-layout zeros."""

        zero = self._zero()
        self._delay_queue = deque(
            self._readonly(zero) for _ in range(self._latency_frames)
        )
        self._last_applied = self._readonly(zero)
        self._last_released = self._readonly(zero)
        self._last_requested = self._readonly(zero)
        self._step_index = 0
        self._awaiting_applied_acknowledgement = False

    def update(
        self,
        reconstructed_delta: DmCommandVector | None,
    ) -> DmCommandVector:
        """Advance one frame and return the requested full DM command."""

        if self._awaiting_applied_acknowledgement:
            raise ControllerError(
                "accept_applied_commands() must acknowledge the prior request "
                "before the next update."
            )
        if reconstructed_delta is None:
            enqueued = self._zero()
        else:
            enqueued = self._validated_values(
                reconstructed_delta,
                label="reconstructed_delta",
            )
        self._delay_queue.append(self._readonly(enqueued))
        released = np.asarray(self._delay_queue.popleft(), dtype=float)
        requested = (
            (1.0 - self._leak) * np.asarray(self._last_applied)
            + self._gain * released
        )
        if not np.all(np.isfinite(requested)):
            raise ControllerError("controller update produced non-finite commands.")
        self._last_released = self._readonly(released)
        self._last_requested = self._readonly(requested)
        self._step_index += 1
        self._awaiting_applied_acknowledgement = True
        return self._command(requested)

    def accept_applied_commands(self, commands: DmCommandVector) -> None:
        """Synchronize the next update to the command actually applied by the DM."""

        values = self._validated_values(commands, label="commands")
        self._last_applied = self._readonly(values)
        self._awaiting_applied_acknowledgement = False

    def _validated_values(
        self,
        command: object,
        *,
        label: str,
    ) -> np.ndarray:
        if not isinstance(command, DmCommandVector):
            raise ControllerError(f"{label} must be a DmCommandVector.")
        if command.actuator_ids != self._actuator_ids:
            raise ControllerError(
                f"{label}.actuator_ids must exactly match the controller IDs "
                "and ordering."
            )
        if command.command_unit != _COMMAND_UNIT:
            raise ControllerError(
                f"{label}.command_unit must be {_COMMAND_UNIT!r}."
            )
        return np.asarray(command.values_opd_m, dtype=float)

    def _command(self, values: np.ndarray) -> DmCommandVector:
        return DmCommandVector(
            values_opd_m=np.asarray(values, dtype=float),
            actuator_ids=self._actuator_ids,
            command_unit=_COMMAND_UNIT,
        )

    def _zero(self) -> np.ndarray:
        return np.zeros(len(self._actuator_ids), dtype=float)

    @staticmethod
    def _readonly(values: np.ndarray) -> np.ndarray:
        contiguous = np.ascontiguousarray(np.array(values, dtype=float, copy=True))
        immutable = np.frombuffer(contiguous.tobytes(order="C"), dtype=float)
        return immutable.reshape(contiguous.shape)


def _ids(value: object) -> tuple[str, ...]:
    if not isinstance(value, tuple) or not value:
        raise ControllerError("actuator_ids must be a non-empty tuple of IDs.")
    if any(not isinstance(identifier, str) or not identifier for identifier in value):
        raise ControllerError("actuator_ids must contain non-empty strings.")
    if len(value) != len(set(value)):
        raise ControllerError("actuator_ids must not contain duplicate IDs.")
    return value


def _integer(value: object, *, label: str, minimum: int) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise ControllerError(f"{label} must be an integer.")
    result = int(value)
    if result < minimum:
        raise ControllerError(f"{label} must be at least {minimum}.")
    return result


def _finite(value: object, *, label: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise ControllerError(f"{label} must be a finite real number.")
    result = float(value)
    if not math.isfinite(result):
        raise ControllerError(f"{label} must be finite.")
    return result
