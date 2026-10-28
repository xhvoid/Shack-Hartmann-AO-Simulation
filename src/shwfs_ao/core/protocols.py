"""Backend-neutral component contracts for adaptive-optics systems.

The protocols in this module deliberately depend only on NumPy and canonical
core result types.  Physical components and optional backends implement these
interfaces structurally; no runtime inheritance is required.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, Protocol, runtime_checkable

import numpy as np

from .types import (
    DmCommandVector,
    DmSynthesisResult,
    MeasurementVector,
    PsfResult,
    ReconstructionEstimate,
    SpotIntensityResult,
    WfsMeasurement,
)


@runtime_checkable
class RandomStreams(Protocol):
    """Stable named random-stream provider."""

    @property
    def root_seed(self) -> int:
        ...

    @property
    def derivation_scheme_id(self) -> str:
        ...

    def reset(self) -> None:
        """Recreate every persistent domain generator from the root seed."""

    def generator(self, domain: str) -> np.random.Generator:
        """Return the persistent generator for a registered domain."""

    def keyed_generator(
        self,
        domain: str,
        *,
        key: tuple[str | int, ...],
    ) -> np.random.Generator:
        """Return a fresh deterministic child generator for a stable key."""

    def stream_id(
        self,
        domain: str,
        *,
        key: tuple[str | int, ...] = (),
    ) -> str:
        ...

    def scoped(
        self,
        scope: str,
        *,
        key: tuple[str | int, ...] = (),
    ) -> RandomStreams:
        """Derive all domain requests beneath a stable scope and key."""


@runtime_checkable
class AtmosphereModel(Protocol):
    @property
    def backend_name(self) -> str:
        ...

    @property
    def config_hash(self) -> str:
        ...

    @property
    def metadata(self) -> Mapping[str, Any]:
        ...

    def reset(self, *, realization_index: int = 0) -> None:
        """Reset to t=0; the same index reproduces the same realization."""

    def opd_at(self, time_s: float) -> np.ndarray:
        """Return piston-removed atmospheric OPD in metres."""


@runtime_checkable
class ShackHartmannOpticsBackend(Protocol):
    @property
    def backend_name(self) -> str:
        ...

    @property
    def config_hash(self) -> str:
        ...

    def spot_intensities(self, residual_opd_m: np.ndarray) -> SpotIntensityResult:
        ...


@runtime_checkable
class WavefrontSensor(Protocol):
    @property
    def config_hash(self) -> str:
        ...

    @property
    def row_ids(self) -> tuple[str, ...]:
        ...

    def measure(
        self,
        residual_opd_m: np.ndarray,
        *,
        random_streams: RandomStreams,
        include_noise: bool,
    ) -> WfsMeasurement:
        ...


@runtime_checkable
class DeformableMirrorModel(Protocol):
    @property
    def config_hash(self) -> str:
        ...

    @property
    def n_actuators(self) -> int:
        ...

    @property
    def actuator_ids(self) -> tuple[str, ...]:
        ...

    @property
    def controllable_actuator_ids(self) -> tuple[str, ...]:
        ...

    def opd_from_commands(self, commands: DmCommandVector) -> DmSynthesisResult:
        ...


@runtime_checkable
class Reconstructor(Protocol):
    @property
    def matrix_hash(self) -> str:
        ...

    def reconstruct(
        self,
        measurement: MeasurementVector,
    ) -> ReconstructionEstimate | None:
        """Return None when usable coverage or rank is below policy."""


@runtime_checkable
class CommandProjector(Protocol):
    @property
    def config_hash(self) -> str:
        ...

    @property
    def input_coordinate_ids(self) -> tuple[str, ...]:
        ...

    @property
    def input_coordinate_kind(self) -> Literal["modal_opd", "dm_command_opd"]:
        ...

    @property
    def input_coordinate_unit(self) -> Literal["m_opd_rms", "m_opd_equivalent"]:
        ...

    @property
    def output_actuator_ids(self) -> tuple[str, ...]:
        ...

    def project(self, estimate: ReconstructionEstimate) -> DmCommandVector:
        """Validate coordinates and map them to a full DM increment."""


@runtime_checkable
class Controller(Protocol):
    @property
    def config_hash(self) -> str:
        ...

    @property
    def actuator_ids(self) -> tuple[str, ...]:
        ...

    def reset(self) -> None:
        ...

    def update(
        self,
        reconstructed_delta: DmCommandVector | None,
    ) -> DmCommandVector:
        """Return requested commands; ``None`` still advances controller time."""

    def accept_applied_commands(self, commands: DmCommandVector) -> None:
        """Synchronize controller state to the command applied by the DM."""


@runtime_checkable
class SciencePropagator(Protocol):
    @property
    def backend_name(self) -> str:
        ...

    @property
    def config_hash(self) -> str:
        ...

    def psf_from_opd(
        self,
        opd_m: np.ndarray,
        wavelength_m: float,
    ) -> PsfResult:
        ...


__all__ = (
    "RandomStreams",
    "AtmosphereModel",
    "ShackHartmannOpticsBackend",
    "WavefrontSensor",
    "DeformableMirrorModel",
    "Reconstructor",
    "CommandProjector",
    "Controller",
    "SciencePropagator",
)
