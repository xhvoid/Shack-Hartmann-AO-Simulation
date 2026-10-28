"""Deprecated compatibility shim for :mod:`shwfs_ao.legacy.ao_diagnostics`.

Importing this root-level module emits a DeprecationWarning built from
the packaged AO-REF-021 clock and inventory metadata; the re-exported
objects stay identical to the shwfs_ao implementations throughout the
compatibility window.
"""

import warnings as _warnings

import shwfs_ao._deprecation as _deprecation

from shwfs_ao.legacy import ao_diagnostics as _implementation
from shwfs_ao.legacy.ao_diagnostics import (
    ALLOWED_SOURCE_CLASSES,
    AODiagnosticsError,
    ARCSEC_PER_RAD,
    Any,
    DEFAULT_DIAGNOSTIC_SOURCE_CLASS,
    DEFAULT_DIAGNOSTIC_SOURCE_NOTE,
    DMModel,
    FilterCurve,
    Mapping,
    NM_PER_M,
    NM_TO_M,
    PHASE_TWO_PI,
    ScienceBandpass,
    SciencePsfMetrics,
    Sequence,
    band_averaged_psf_metrics_from_opd,
    bandpass_from_filter_curve,
    compute_psf_from_phase,
    dataclass,
    marechal_strehl,
    math,
    monochromatic_bandpass,
    np,
    phase_for_science_wavelength,
    phase_rad_to_opd_nm,
    remove_piston_opd_nm,
    residual_opd_nm_from_command,
    science_case_metrics_table,
    science_metrics_as_dicts,
    science_psf_metrics_from_opd,
    synthesize_dm_phase_rad,
    top_hat_bandpass,
)

if hasattr(_implementation, "annotations"):
    annotations = _implementation.annotations

_warnings.warn(
    _deprecation.root_shim_deprecation_message('ao_diagnostics'),
    DeprecationWarning,
    stacklevel=2,
)

__all__ = (
    "ALLOWED_SOURCE_CLASSES",
    "AODiagnosticsError",
    "ARCSEC_PER_RAD",
    "Any",
    "DEFAULT_DIAGNOSTIC_SOURCE_CLASS",
    "DEFAULT_DIAGNOSTIC_SOURCE_NOTE",
    "DMModel",
    "FilterCurve",
    "Mapping",
    "NM_PER_M",
    "NM_TO_M",
    "PHASE_TWO_PI",
    "ScienceBandpass",
    "SciencePsfMetrics",
    "Sequence",
    *(("annotations",) if hasattr(_implementation, "annotations") else ()),
    "band_averaged_psf_metrics_from_opd",
    "bandpass_from_filter_curve",
    "compute_psf_from_phase",
    "dataclass",
    "marechal_strehl",
    "math",
    "monochromatic_bandpass",
    "np",
    "phase_for_science_wavelength",
    "phase_rad_to_opd_nm",
    "remove_piston_opd_nm",
    "residual_opd_nm_from_command",
    "science_case_metrics_table",
    "science_metrics_as_dicts",
    "science_psf_metrics_from_opd",
    "synthesize_dm_phase_rad",
    "top_hat_bandpass",
)
