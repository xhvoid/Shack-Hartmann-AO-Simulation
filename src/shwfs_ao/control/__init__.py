"""Backend-independent adaptive-optics control and telemetry."""

from .config import LoopConfig, LoopConfigError
from .command_mapping import (
    CommandMappingError,
    ControlledSubsetCommandProjector,
    IdentityCommandProjector,
    ModalToActuatorCommandProjector,
)
from .controller import ControllerError, LeakyIntegratorController
from .history import LoopHistory, LoopHistoryError
from .loop import (
    ControlLoopError,
    run_closed_loop,
    validate_closed_loop_components,
)
from .sweeps import (
    ControlSweepError,
    gain_delay_stability_map,
    gain_scan,
    latency_scan,
    photon_scan,
    read_noise_scan,
)


__all__ = (
    "LoopConfigError",
    "LoopConfig",
    "CommandMappingError",
    "IdentityCommandProjector",
    "ControlledSubsetCommandProjector",
    "ModalToActuatorCommandProjector",
    "ControllerError",
    "LeakyIntegratorController",
    "LoopHistoryError",
    "LoopHistory",
    "ControlLoopError",
    "validate_closed_loop_components",
    "run_closed_loop",
    "ControlSweepError",
    "gain_scan",
    "latency_scan",
    "photon_scan",
    "read_noise_scan",
    "gain_delay_stability_map",
)
