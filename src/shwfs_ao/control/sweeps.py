"""Replay-safe parameter sweeps built on the canonical control-loop runner."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
import math
from numbers import Integral, Real

import numpy as np

from ..calibration.interaction import InteractionMatrix
from ..core.protocols import (
    AtmosphereModel,
    CommandProjector,
    DeformableMirrorModel,
    RandomStreams,
    Reconstructor,
    WavefrontSensor,
)
from .config import LoopConfig
from .controller import LeakyIntegratorController
from .history import LoopHistory
from .loop import run_closed_loop


__all__ = (
    "ControlSweepError",
    "gain_scan",
    "latency_scan",
    "photon_scan",
    "read_noise_scan",
    "gain_delay_stability_map",
)


class ControlSweepError(ValueError):
    """Raised when a canonical control-sweep axis is invalid."""


def gain_scan(
    gains: Sequence[float],
    base_config: LoopConfig,
    *,
    random_streams: RandomStreams,
    atmosphere: AtmosphereModel,
    wfs: WavefrontSensor,
    dm: DeformableMirrorModel,
    interaction_matrix: InteractionMatrix,
    reconstructor: Reconstructor,
    command_projector: CommandProjector,
    include_noise: bool,
    realization_index: int = 0,
) -> dict[float, LoopHistory]:
    """Run each non-negative gain against the same reset realization."""

    base = _base_config(base_config)
    axis = _float_axis(gains, label="gains", positive=False)
    return {
        gain: _run_point(
            replace(base, gain=gain),
            random_streams=random_streams,
            atmosphere=atmosphere,
            wfs=wfs,
            dm=dm,
            interaction_matrix=interaction_matrix,
            reconstructor=reconstructor,
            command_projector=command_projector,
            include_noise=include_noise,
            realization_index=realization_index,
        )
        for gain in sorted(axis)
    }


def latency_scan(
    latency_frames: Sequence[int],
    base_config: LoopConfig,
    *,
    random_streams: RandomStreams,
    atmosphere: AtmosphereModel,
    wfs: WavefrontSensor,
    dm: DeformableMirrorModel,
    interaction_matrix: InteractionMatrix,
    reconstructor: Reconstructor,
    command_projector: CommandProjector,
    include_noise: bool,
    realization_index: int = 0,
) -> dict[int, LoopHistory]:
    """Run each integer frame latency against the same reset realization."""

    base = _base_config(base_config)
    axis = _integer_axis(latency_frames, label="latency_frames")
    return {
        latency: _run_point(
            replace(base, latency_frames=latency),
            random_streams=random_streams,
            atmosphere=atmosphere,
            wfs=wfs,
            dm=dm,
            interaction_matrix=interaction_matrix,
            reconstructor=reconstructor,
            command_projector=command_projector,
            include_noise=include_noise,
            realization_index=realization_index,
        )
        for latency in sorted(axis)
    }


def photon_scan(
    photon_levels: Sequence[float],
    base_config: LoopConfig,
    *,
    wfs_factory: Callable[[float], WavefrontSensor],
    random_streams: RandomStreams,
    atmosphere: AtmosphereModel,
    dm: DeformableMirrorModel,
    interaction_matrix: InteractionMatrix,
    reconstructor: Reconstructor,
    command_projector: CommandProjector,
    include_noise: bool,
    realization_index: int = 0,
) -> dict[float, LoopHistory]:
    """Run positive photon levels using a fresh WFS built for every point."""

    base = _base_config(base_config)
    axis = _float_axis(photon_levels, label="photon_levels", positive=True)
    factory = _factory(wfs_factory, label="wfs_factory")
    return {
        photons: _run_point(
            base,
            random_streams=random_streams,
            atmosphere=atmosphere,
            wfs=factory(photons),
            dm=dm,
            interaction_matrix=interaction_matrix,
            reconstructor=reconstructor,
            command_projector=command_projector,
            include_noise=include_noise,
            realization_index=realization_index,
        )
        for photons in sorted(axis)
    }


def read_noise_scan(
    read_noise_levels_e: Sequence[float],
    base_config: LoopConfig,
    *,
    wfs_factory: Callable[[float], WavefrontSensor],
    random_streams: RandomStreams,
    atmosphere: AtmosphereModel,
    dm: DeformableMirrorModel,
    interaction_matrix: InteractionMatrix,
    reconstructor: Reconstructor,
    command_projector: CommandProjector,
    include_noise: bool,
    realization_index: int = 0,
) -> dict[float, LoopHistory]:
    """Run non-negative read-noise levels with a fresh WFS per point."""

    base = _base_config(base_config)
    axis = _float_axis(
        read_noise_levels_e,
        label="read_noise_levels_e",
        positive=False,
    )
    factory = _factory(wfs_factory, label="wfs_factory")
    return {
        read_noise_e: _run_point(
            base,
            random_streams=random_streams,
            atmosphere=atmosphere,
            wfs=factory(read_noise_e),
            dm=dm,
            interaction_matrix=interaction_matrix,
            reconstructor=reconstructor,
            command_projector=command_projector,
            include_noise=include_noise,
            realization_index=realization_index,
        )
        for read_noise_e in sorted(axis)
    }


def gain_delay_stability_map(
    gains: Sequence[float],
    latency_frames: Sequence[int],
    base_config: LoopConfig,
    *,
    random_streams: RandomStreams,
    atmosphere: AtmosphereModel,
    wfs: WavefrontSensor,
    dm: DeformableMirrorModel,
    interaction_matrix: InteractionMatrix,
    reconstructor: Reconstructor,
    command_projector: CommandProjector,
    include_noise: bool,
    realization_index: int = 0,
) -> dict[tuple[float, int], LoopHistory]:
    """Run the Cartesian gain/latency grid in a canonical point order."""

    base = _base_config(base_config)
    gain_axis = _float_axis(gains, label="gains", positive=False)
    latency_axis = _integer_axis(latency_frames, label="latency_frames")
    points = sorted(
        (gain, latency)
        for gain in gain_axis
        for latency in latency_axis
    )
    return {
        point: _run_point(
            replace(base, gain=point[0], latency_frames=point[1]),
            random_streams=random_streams,
            atmosphere=atmosphere,
            wfs=wfs,
            dm=dm,
            interaction_matrix=interaction_matrix,
            reconstructor=reconstructor,
            command_projector=command_projector,
            include_noise=include_noise,
            realization_index=realization_index,
        )
        for point in points
    }


def _run_point(
    config: LoopConfig,
    *,
    random_streams: RandomStreams,
    atmosphere: AtmosphereModel,
    wfs: WavefrontSensor,
    dm: DeformableMirrorModel,
    interaction_matrix: InteractionMatrix,
    reconstructor: Reconstructor,
    command_projector: CommandProjector,
    include_noise: bool,
    realization_index: int,
) -> LoopHistory:
    if not isinstance(config, LoopConfig):
        raise ControlSweepError("base_config must be a LoopConfig.")
    controller = LeakyIntegratorController.from_loop_config(
        dm.actuator_ids,
        config,
    )
    return run_closed_loop(
        config,
        random_streams=random_streams,
        atmosphere=atmosphere,
        wfs=wfs,
        dm=dm,
        interaction_matrix=interaction_matrix,
        reconstructor=reconstructor,
        command_projector=command_projector,
        controller=controller,
        include_noise=include_noise,
        realization_index=realization_index,
    )


def _base_config(value: object) -> LoopConfig:
    if not isinstance(value, LoopConfig):
        raise ControlSweepError("base_config must be a LoopConfig.")
    return value


def _float_axis(
    values: object,
    *,
    label: str,
    positive: bool,
) -> tuple[float, ...]:
    candidates = _sequence(values, label=label)
    axis: list[float] = []
    for index, value in enumerate(candidates):
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
            raise ControlSweepError(f"{label}[{index}] must be a finite real number.")
        number = float(value)
        if not math.isfinite(number) or (number <= 0.0 if positive else number < 0.0):
            qualifier = "positive" if positive else "non-negative"
            raise ControlSweepError(
                f"{label}[{index}] must be a finite {qualifier} number."
            )
        axis.append(number)
    if len(axis) != len(set(axis)):
        raise ControlSweepError(f"{label} must not contain duplicate points.")
    return tuple(axis)


def _integer_axis(values: object, *, label: str) -> tuple[int, ...]:
    candidates = _sequence(values, label=label)
    axis: list[int] = []
    for index, value in enumerate(candidates):
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
            raise ControlSweepError(
                f"{label}[{index}] must be a non-negative integer."
            )
        number = int(value)
        if number < 0:
            raise ControlSweepError(
                f"{label}[{index}] must be a non-negative integer."
            )
        axis.append(number)
    if len(axis) != len(set(axis)):
        raise ControlSweepError(f"{label} must not contain duplicate points.")
    return tuple(axis)


def _sequence(value: object, *, label: str) -> tuple[object, ...]:
    if isinstance(value, (str, bytes)):
        raise ControlSweepError(f"{label} must be a non-empty sequence.")
    try:
        result = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ControlSweepError(f"{label} must be a non-empty sequence.") from exc
    if not result:
        raise ControlSweepError(f"{label} must be a non-empty sequence.")
    return result


def _factory(value: object, *, label: str) -> Callable[[float], WavefrontSensor]:
    if not callable(value):
        raise ControlSweepError(f"{label} must be callable.")
    return value  # type: ignore[return-value]
