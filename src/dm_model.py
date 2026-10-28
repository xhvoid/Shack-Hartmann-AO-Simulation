"""Deprecated compatibility shim for :mod:`shwfs_ao.legacy.dm_model`.

Importing this root-level module emits a DeprecationWarning built from
the packaged AO-REF-021 clock and inventory metadata; the re-exported
objects stay identical to the shwfs_ao implementations throughout the
compatibility window.
"""

import warnings as _warnings

import shwfs_ao._deprecation as _deprecation

from shwfs_ao.legacy import dm_model as _implementation
from shwfs_ao.legacy.dm_model import (
    ALLOWED_SOURCE_CLASSES,
    Any,
    DEFAULT_ACTUATOR_MARGIN_FRACTION,
    DEFAULT_DM_SOURCE_CLASS,
    DEFAULT_DM_SOURCE_NOTE,
    DMConfig,
    DMFitResult,
    DMModel,
    DMModelError,
    DMSynthesisResult,
    MIN_ACTUATORS_ACROSS,
    NM_TO_M,
    PHASE_TWO_PI,
    Path,
    Sequence,
    VALID_INFLUENCE_MODELS,
    actuator_centers_on_pupil,
    actuator_metadata,
    build_dm_model,
    clip_commands_nm,
    dataclass,
    fit_static_opd_with_dm,
    json,
    load_dm_config_from_json,
    math,
    np,
    open_text_resource,
    optimize,
    synthesize_dm_opd_nm,
    synthesize_dm_phase_rad,
)

if hasattr(_implementation, "annotations"):
    annotations = _implementation.annotations

_warnings.warn(
    _deprecation.root_shim_deprecation_message('dm_model'),
    DeprecationWarning,
    stacklevel=2,
)

__all__ = (
    "ALLOWED_SOURCE_CLASSES",
    "Any",
    "DEFAULT_ACTUATOR_MARGIN_FRACTION",
    "DEFAULT_DM_SOURCE_CLASS",
    "DEFAULT_DM_SOURCE_NOTE",
    "DMConfig",
    "DMFitResult",
    "DMModel",
    "DMModelError",
    "DMSynthesisResult",
    "MIN_ACTUATORS_ACROSS",
    "NM_TO_M",
    "PHASE_TWO_PI",
    "Path",
    "Sequence",
    "VALID_INFLUENCE_MODELS",
    "actuator_centers_on_pupil",
    "actuator_metadata",
    *(("annotations",) if hasattr(_implementation, "annotations") else ()),
    "build_dm_model",
    "clip_commands_nm",
    "dataclass",
    "fit_static_opd_with_dm",
    "json",
    "load_dm_config_from_json",
    "math",
    "np",
    "open_text_resource",
    "optimize",
    "synthesize_dm_opd_nm",
    "synthesize_dm_phase_rad",
)
