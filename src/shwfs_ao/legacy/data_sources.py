"""Explicit compatibility facade for :mod:`shwfs_ao.io.public_data`."""

from __future__ import annotations

from shwfs_ao.io import public_data as _implementation
from shwfs_ao.io.public_data import (
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
