"""Canonical deformable-mirror configuration and repository policy."""

from .config import (
    DEFAULT_ACTUATOR_MARGIN_FRACTION,
    DEFAULT_DM_SOURCE_CLASS,
    DEFAULT_DM_SOURCE_NOTE,
    MIN_ACTUATORS_ACROSS,
    NM_TO_M,
    VALID_INFLUENCE_MODELS,
    DMConfig,
    DMConfigError,
    DMModelError,
    DmConfig,
    actuator_id,
    actuator_ids_from_grid_indices,
)
from .model import (
    COMMAND_UNIT,
    DeformableMirror,
    DeformableMirrorError,
    DmBackend,
    build_deformable_mirror,
    build_native_deformable_mirror,
)


__all__ = (
    "DEFAULT_ACTUATOR_MARGIN_FRACTION",
    "DEFAULT_DM_SOURCE_CLASS",
    "DEFAULT_DM_SOURCE_NOTE",
    "MIN_ACTUATORS_ACROSS",
    "NM_TO_M",
    "VALID_INFLUENCE_MODELS",
    "DMModelError",
    "DMConfigError",
    "DMConfig",
    "DmConfig",
    "actuator_id",
    "actuator_ids_from_grid_indices",
    "COMMAND_UNIT",
    "DmBackend",
    "DeformableMirrorError",
    "DeformableMirror",
    "build_native_deformable_mirror",
    "build_deformable_mirror",
)
