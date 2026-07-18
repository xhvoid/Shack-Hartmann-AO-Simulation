"""Deprecated compatibility shim for :mod:`shwfs_ao.legacy.ao_conditions`.

Importing this root-level module emits a DeprecationWarning built from
the packaged AO-REF-021 clock and inventory metadata; the re-exported
objects stay identical to the shwfs_ao implementations throughout the
compatibility window.
"""

import warnings as _warnings

import shwfs_ao._deprecation as _deprecation

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

_warnings.warn(
    _deprecation.root_shim_deprecation_message('ao_conditions'),
    DeprecationWarning,
    stacklevel=2,
)

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
