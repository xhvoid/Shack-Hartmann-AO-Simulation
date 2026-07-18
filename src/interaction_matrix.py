"""Deprecated compatibility shim for :mod:`shwfs_ao.legacy.interaction_matrix`.

Importing this root-level module emits a DeprecationWarning built from
the packaged AO-REF-021 clock and inventory metadata; the re-exported
objects stay identical to the shwfs_ao implementations throughout the
compatibility window.
"""

import warnings as _warnings

import shwfs_ao._deprecation as _deprecation

from shwfs_ao.legacy import interaction_matrix as _implementation
from shwfs_ao.legacy.interaction_matrix import (
    ALLOWED_SOURCE_CLASSES,
    Any,
    DEFAULT_CENTROID_VALIDITY,
    DEFAULT_NUMERIC_RANK_RTOL,
    DEFAULT_POKE_AMPLITUDE_GRID_NM,
    DEFAULT_POKE_SOURCE_CLASS,
    DEFAULT_POKE_SOURCE_NOTE,
    DEFAULT_RCOND_SCAN_GRID,
    DEFAULT_TARGET_KEPT_FRACTION,
    DMModel,
    DetectorMeasurement,
    DetectorShwfsCalibration,
    InteractionMatrixError,
    PokeMatrixConfig,
    PokeMtxResult,
    RcondScanResult,
    Sequence,
    TSVDReconstructionResult,
    TikhonovReconstructionResult,
    build_detector_dm_poke_matrix,
    choose_rcond_from_singular_values,
    dataclass,
    expand_controlled_commands,
    hashlib,
    json,
    kept_modes_for_rcond,
    math,
    measure_detector_shwfs,
    noise_amplification_proxy,
    np,
    poke_amplitude_scan,
    poke_matrix_summary,
    replace,
    scan_tsvd_rcond,
    stable_array_descriptor,
    synthesize_dm_phase_rad,
    tikhonov_reconstruct_commands,
    tsvd_reconstruct_commands,
    vectorize_detector_measurement,
)

if hasattr(_implementation, "annotations"):
    annotations = _implementation.annotations

_warnings.warn(
    _deprecation.root_shim_deprecation_message('interaction_matrix'),
    DeprecationWarning,
    stacklevel=2,
)

__all__ = (
    "ALLOWED_SOURCE_CLASSES",
    "Any",
    "DEFAULT_CENTROID_VALIDITY",
    "DEFAULT_NUMERIC_RANK_RTOL",
    "DEFAULT_POKE_AMPLITUDE_GRID_NM",
    "DEFAULT_POKE_SOURCE_CLASS",
    "DEFAULT_POKE_SOURCE_NOTE",
    "DEFAULT_RCOND_SCAN_GRID",
    "DEFAULT_TARGET_KEPT_FRACTION",
    "DMModel",
    "DetectorMeasurement",
    "DetectorShwfsCalibration",
    "InteractionMatrixError",
    "PokeMatrixConfig",
    "PokeMtxResult",
    "RcondScanResult",
    "Sequence",
    "TSVDReconstructionResult",
    "TikhonovReconstructionResult",
    *(("annotations",) if hasattr(_implementation, "annotations") else ()),
    "build_detector_dm_poke_matrix",
    "choose_rcond_from_singular_values",
    "dataclass",
    "expand_controlled_commands",
    "hashlib",
    "json",
    "kept_modes_for_rcond",
    "math",
    "measure_detector_shwfs",
    "noise_amplification_proxy",
    "np",
    "poke_amplitude_scan",
    "poke_matrix_summary",
    "replace",
    "scan_tsvd_rcond",
    "stable_array_descriptor",
    "synthesize_dm_phase_rad",
    "tikhonov_reconstruct_commands",
    "tsvd_reconstruct_commands",
    "vectorize_detector_measurement",
)
