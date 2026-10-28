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
from .recovery import ClosedLoopRecoveryPolicy, RecoveryPolicyError
from .observation import (
    OBSERVABLE_FIELDS,
    OBSERVATION_POINT,
    FrameObservation,
    FrameObservationError,
    FrameObserver,
)
from .loop import (
    EXPOSURE_SAMPLE_RULES,
    ControlLoopError,
    ControlLoopWarning,
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
    "RecoveryPolicyError",
    "ClosedLoopRecoveryPolicy",
    "OBSERVABLE_FIELDS",
    "OBSERVATION_POINT",
    "FrameObservation",
    "FrameObservationError",
    "FrameObserver",
    "EXPOSURE_SAMPLE_RULES",
    "ControlLoopError",
    "ControlLoopWarning",
    "validate_closed_loop_components",
    "run_closed_loop",
    "ControlSweepError",
    "gain_scan",
    "latency_scan",
    "photon_scan",
    "read_noise_scan",
    "gain_delay_stability_map",
)
