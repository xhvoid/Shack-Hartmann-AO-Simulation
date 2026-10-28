"""Silent compatibility shim for :mod:`shwfs_ao.legacy.ao_conditions`."""

from shwfs_ao.legacy import ao_conditions as _implementation
from shwfs_ao.legacy.ao_conditions import (
    ALLOWED_SOURCE_CLASSES,
    AOConditionError,
    ARCSEC_PER_RAD,
    EsoAsmSnapshot,
    ObservingConditionConfig,
    REFERENCE_PHASE_AMPLITUDE_NM,
    REFERENCE_SEEING_ARCSEC,
    Sequence,
    condition_rows,
    dataclass,
    default_observing_conditions,
    math,
    phase_amplitude_from_seeing,
    r0_from_seeing_arcsec,
    theta0_rad_from_arcsec,
)

if hasattr(_implementation, "annotations"):
    annotations = _implementation.annotations

__all__ = (
    "ALLOWED_SOURCE_CLASSES",
    "AOConditionError",
    "ARCSEC_PER_RAD",
    "EsoAsmSnapshot",
    "ObservingConditionConfig",
    "REFERENCE_PHASE_AMPLITUDE_NM",
    "REFERENCE_SEEING_ARCSEC",
    "Sequence",
    *(("annotations",) if hasattr(_implementation, "annotations") else ()),
    "condition_rows",
    "dataclass",
    "default_observing_conditions",
    "math",
    "phase_amplitude_from_seeing",
    "r0_from_seeing_arcsec",
    "theta0_rad_from_arcsec",
)
