"""Deprecated compatibility shim for :mod:`shwfs_ao.legacy.ao_closed_loop`.

Importing this root-level module emits a DeprecationWarning built from
the packaged AO-REF-021 clock and inventory metadata; the re-exported
objects stay identical to the shwfs_ao implementations throughout the
compatibility window.
"""

import warnings as _warnings

import shwfs_ao._deprecation as _deprecation

from shwfs_ao.legacy import ao_closed_loop as _implementation
from shwfs_ao.legacy.ao_closed_loop import (
    ALLOWED_SOURCE_CLASSES,
    Any,
    ClosedLoopError,
    DEFAULT_CENTROID_VALIDITY,
    DEFAULT_LOOP_SOURCE_CLASS,
    DEFAULT_LOOP_SOURCE_NOTE,
    DMModel,
    DetectorLoopConfig,
    DetectorShwfsCalibration,
    LoopHistory,
    NM_PER_M,
    PHASE_TWO_PI,
    PokeMtxResult,
    actuator_centers_on_pupil,
    build_detector_dm_poke_matrix_from_calibration,
    build_dm_detector_response_matrix,
    build_dm_wfs_response_matrix,
    dataclass,
    expand_controlled_commands,
    frozen_flow_shift,
    frozen_flow_shift_physical,
    gain_scan,
    gaussian_influence_functions,
    hashlib,
    json,
    loop_history_summary,
    math,
    measure_centroid_shifts,
    measure_detector_shwfs,
    measure_slopes,
    np,
    reconstruct_dm_delta,
    reference_centroids,
    rms,
    run_closed_loop_ao,
    run_closed_loop_ao_detector,
    run_detector_integrator_loop,
    shifted_atmosphere,
    stable_array_descriptor,
    strehl_ratio,
    synthesize_dm_phase,
    synthesize_dm_phase_rad,
    tsvd_reconstruct_commands,
    vectorize_detector_measurement,
)

if hasattr(_implementation, "annotations"):
    annotations = _implementation.annotations

_warnings.warn(
    _deprecation.root_shim_deprecation_message('ao_closed_loop'),
    DeprecationWarning,
    stacklevel=2,
)

__all__ = (
    "ALLOWED_SOURCE_CLASSES",
    "Any",
    "ClosedLoopError",
    "DEFAULT_CENTROID_VALIDITY",
    "DEFAULT_LOOP_SOURCE_CLASS",
    "DEFAULT_LOOP_SOURCE_NOTE",
    "DMModel",
    "DetectorLoopConfig",
    "DetectorShwfsCalibration",
    "LoopHistory",
    "NM_PER_M",
    "PHASE_TWO_PI",
    "PokeMtxResult",
    "actuator_centers_on_pupil",
    *(("annotations",) if hasattr(_implementation, "annotations") else ()),
    "build_detector_dm_poke_matrix_from_calibration",
    "build_dm_detector_response_matrix",
    "build_dm_wfs_response_matrix",
    "dataclass",
    "expand_controlled_commands",
    "frozen_flow_shift",
    "frozen_flow_shift_physical",
    "gain_scan",
    "gaussian_influence_functions",
    "hashlib",
    "json",
    "loop_history_summary",
    "math",
    "measure_centroid_shifts",
    "measure_detector_shwfs",
    "measure_slopes",
    "np",
    "reconstruct_dm_delta",
    "reference_centroids",
    "rms",
    "run_closed_loop_ao",
    "run_closed_loop_ao_detector",
    "run_detector_integrator_loop",
    "shifted_atmosphere",
    "stable_array_descriptor",
    "strehl_ratio",
    "synthesize_dm_phase",
    "synthesize_dm_phase_rad",
    "tsvd_reconstruct_commands",
    "vectorize_detector_measurement",
)
