"""Deprecated compatibility shim for :mod:`shwfs_ao.legacy.atmosphere_profiles`.

Importing this root-level module emits a DeprecationWarning built from
the packaged AO-REF-021 clock and inventory metadata; the re-exported
objects stay identical to the shwfs_ao implementations throughout the
compatibility window.
"""

import warnings as _warnings

import shwfs_ao._deprecation as _deprecation

from shwfs_ao.legacy import atmosphere_profiles as _implementation
from shwfs_ao.legacy.atmosphere_profiles import (
    ALLOWED_SOURCE_CLASSES,
    ARCSEC_PER_RAD,
    AtmosphereConfig,
    AtmosphereLayerConfig,
    AtmospherePhaseCube,
    AtmosphereProfileError,
    EsoAsmSnapshot,
    FRIED_SEEING_COEFFICIENT,
    FULL_SCREEN_COVER_FACTOR,
    LAYER_WEIGHT_ABS_TOL,
    LiteratureAtmosphereProfile,
    PHASE_RMS_COEFFICIENT,
    PHASE_RMS_REL_TOL,
    R0_REFERENCE_WAVELENGTH_M,
    R0_STRENGTH_EXPONENT,
    R0_WAVELENGTH_EXPONENT,
    Sequence,
    atmosphere_config_from_eso_asm_snapshot,
    atmosphere_config_from_literature_profile,
    circular_mask_from_grid,
    dataclass,
    equivalent_r0_500_m,
    expected_phase_rms_rad,
    fourier_phase_screen,
    generate_multilayer_phase_cube,
    math,
    normalize_layers,
    np,
    r0_at_wavelength_m,
    rms,
    seeing_to_r0_m,
    shift_full_phase_pixels,
    wind_components_ms,
)

if hasattr(_implementation, "annotations"):
    annotations = _implementation.annotations

_warnings.warn(
    _deprecation.root_shim_deprecation_message('atmosphere_profiles'),
    DeprecationWarning,
    stacklevel=2,
)

__all__ = (
    "ALLOWED_SOURCE_CLASSES",
    "ARCSEC_PER_RAD",
    "AtmosphereConfig",
    "AtmosphereLayerConfig",
    "AtmospherePhaseCube",
    "AtmosphereProfileError",
    "EsoAsmSnapshot",
    "FRIED_SEEING_COEFFICIENT",
    "FULL_SCREEN_COVER_FACTOR",
    "LAYER_WEIGHT_ABS_TOL",
    "LiteratureAtmosphereProfile",
    "PHASE_RMS_COEFFICIENT",
    "PHASE_RMS_REL_TOL",
    "R0_REFERENCE_WAVELENGTH_M",
    "R0_STRENGTH_EXPONENT",
    "R0_WAVELENGTH_EXPONENT",
    "Sequence",
    *(("annotations",) if hasattr(_implementation, "annotations") else ()),
    "atmosphere_config_from_eso_asm_snapshot",
    "atmosphere_config_from_literature_profile",
    "circular_mask_from_grid",
    "dataclass",
    "equivalent_r0_500_m",
    "expected_phase_rms_rad",
    "fourier_phase_screen",
    "generate_multilayer_phase_cube",
    "math",
    "normalize_layers",
    "np",
    "r0_at_wavelength_m",
    "rms",
    "seeing_to_r0_m",
    "shift_full_phase_pixels",
    "wind_components_ms",
)
