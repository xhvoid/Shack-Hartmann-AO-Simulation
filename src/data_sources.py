"""Deprecated compatibility shim for :mod:`shwfs_ao.legacy.data_sources`.

Importing this root-level module emits a DeprecationWarning built from
the packaged AO-REF-021 clock and inventory metadata; the re-exported
objects stay identical to the shwfs_ao implementations throughout the
compatibility window.
"""

import warnings as _warnings

import shwfs_ao._deprecation as _deprecation

from shwfs_ao.legacy import data_sources as _implementation
from shwfs_ao.legacy.data_sources import (
    ALLOWED_SOURCE_CLASSES,
    ARCSEC_PER_RADIAN,
    ATMOSPHERE_LAYER_UNITS,
    Any,
    AtmosphereLayer,
    CSV_COMMENT_PREFIX,
    CSV_METADATA_SEPARATOR,
    DataSourceError,
    ESO_MEASUREMENT_UNITS,
    EsoAsmSnapshot,
    FilterCurve,
    LITERATURE_SUMMARY_UNITS,
    LiteratureAtmosphereProfile,
    NORMALIZED_WEIGHT_ABS_TOL,
    Path,
    Provenance,
    REQUIRED_CSV_METADATA,
    TargetPhotometry,
    csv,
    dataclass,
    json,
    load_eso_asm_snapshot,
    load_literature_atmosphere_profile,
    load_svo_filter_curve,
    load_target_photometry,
    math,
    open_text_resource,
)

if hasattr(_implementation, "annotations"):
    annotations = _implementation.annotations

_warnings.warn(
    _deprecation.root_shim_deprecation_message('data_sources'),
    DeprecationWarning,
    stacklevel=2,
)

__all__ = (
    "ALLOWED_SOURCE_CLASSES",
    "ARCSEC_PER_RADIAN",
    "ATMOSPHERE_LAYER_UNITS",
    "Any",
    "AtmosphereLayer",
    "CSV_COMMENT_PREFIX",
    "CSV_METADATA_SEPARATOR",
    "DataSourceError",
    "ESO_MEASUREMENT_UNITS",
    "EsoAsmSnapshot",
    "FilterCurve",
    "LITERATURE_SUMMARY_UNITS",
    "LiteratureAtmosphereProfile",
    "NORMALIZED_WEIGHT_ABS_TOL",
    "Path",
    "Provenance",
    "REQUIRED_CSV_METADATA",
    "TargetPhotometry",
    *(("annotations",) if hasattr(_implementation, "annotations") else ()),
    "csv",
    "dataclass",
    "json",
    "load_eso_asm_snapshot",
    "load_literature_atmosphere_profile",
    "load_svo_filter_curve",
    "load_target_photometry",
    "math",
    "open_text_resource",
)
