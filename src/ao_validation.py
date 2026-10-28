"""Deprecated compatibility shim for :mod:`shwfs_ao.legacy.ao_validation`.

Importing this root-level module emits a DeprecationWarning built from
the packaged AO-REF-021 clock and inventory metadata; the re-exported
objects stay identical to the shwfs_ao implementations throughout the
compatibility window.
"""

import warnings as _warnings

import shwfs_ao._deprecation as _deprecation

from shwfs_ao.legacy import ao_validation as _implementation
from shwfs_ao.legacy.ao_validation import (
    ALLOWED_SOURCE_CLASSES,
    AOValidationError,
    Any,
    DEFAULT_VALIDATION_SOURCE_CLASS,
    DEFAULT_VALIDATION_SOURCE_NOTE,
    DMConfig,
    DetectorConfig,
    DetectorLoopConfig,
    DetectorShwfsCalibration,
    PokeMtxResult,
    ScenarioResult,
    Sequence,
    ValidationCheckResult,
    ValidationScanResult,
    build_dm_model,
    check_centroid_noise_photon_monotonicity,
    check_diffraction_scale,
    check_dm_fitting_trend,
    check_latency_residual_monotonicity,
    check_marechal_consistency,
    check_scenario_reproducibility,
    dataclass,
    fit_static_opd_with_dm,
    math,
    np,
    replace,
    run_detector_integrator_loop,
    sample_centroid_noise,
    science_psf_metrics_from_opd,
    validation_results_as_dicts,
)

if hasattr(_implementation, "annotations"):
    annotations = _implementation.annotations

_warnings.warn(
    _deprecation.root_shim_deprecation_message('ao_validation'),
    DeprecationWarning,
    stacklevel=2,
)

__all__ = (
    "ALLOWED_SOURCE_CLASSES",
    "AOValidationError",
    "Any",
    "DEFAULT_VALIDATION_SOURCE_CLASS",
    "DEFAULT_VALIDATION_SOURCE_NOTE",
    "DMConfig",
    "DetectorConfig",
    "DetectorLoopConfig",
    "DetectorShwfsCalibration",
    "PokeMtxResult",
    "ScenarioResult",
    "Sequence",
    "ValidationCheckResult",
    "ValidationScanResult",
    *(("annotations",) if hasattr(_implementation, "annotations") else ()),
    "build_dm_model",
    "check_centroid_noise_photon_monotonicity",
    "check_diffraction_scale",
    "check_dm_fitting_trend",
    "check_latency_residual_monotonicity",
    "check_marechal_consistency",
    "check_scenario_reproducibility",
    "dataclass",
    "fit_static_opd_with_dm",
    "math",
    "np",
    "replace",
    "run_detector_integrator_loop",
    "sample_centroid_noise",
    "science_psf_metrics_from_opd",
    "validation_results_as_dicts",
)
