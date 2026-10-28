"""Deprecated compatibility shim for :mod:`shwfs_ao.legacy.ao_error_budget`.

Importing this root-level module emits a DeprecationWarning built from
the packaged AO-REF-021 clock and inventory metadata; the re-exported
objects stay identical to the shwfs_ao implementations throughout the
compatibility window.
"""

import warnings as _warnings

import shwfs_ao._deprecation as _deprecation

from shwfs_ao.legacy import ao_error_budget as _implementation
from shwfs_ao.legacy.ao_error_budget import (
    ALLOWED_SOURCE_CLASSES,
    AOErrorBudgetError,
    Any,
    DEFAULT_H_BAND,
    DEFAULT_J_BAND,
    DEFAULT_K_BAND,
    DEFAULT_SCENARIO_SOURCE_CLASS,
    DEFAULT_SCENARIO_SOURCE_NOTE,
    DMConfig,
    DMModel,
    DetectorLoopConfig,
    DetectorShwfsCalibration,
    LoopHistory,
    Mapping,
    NM_PER_M,
    PHASE_TWO_PI,
    PokeMtxResult,
    REQUIRED_SCENARIO_NAMES,
    ScenarioConfig,
    ScenarioResult,
    ScienceBandpass,
    Sequence,
    band_averaged_psf_metrics_from_opd,
    build_control_space_phase_sequence,
    dataclass,
    default_error_budget_scenarios,
    default_jhk_bandpasses,
    expand_controlled_commands,
    hashlib,
    json,
    math,
    ndimage,
    np,
    phase_rad_to_opd_nm,
    remove_piston_opd_nm,
    replace,
    residual_opd_nm_from_command,
    run_detector_integrator_loop,
    run_error_budget_scenario,
    run_error_budget_scenarios,
    scenario_results_as_dicts,
    stable_array_descriptor,
    summarize_scenario,
    synthesize_dm_phase_rad,
    top_hat_bandpass,
)

if hasattr(_implementation, "annotations"):
    annotations = _implementation.annotations

_warnings.warn(
    _deprecation.root_shim_deprecation_message('ao_error_budget'),
    DeprecationWarning,
    stacklevel=2,
)

__all__ = (
    "ALLOWED_SOURCE_CLASSES",
    "AOErrorBudgetError",
    "Any",
    "DEFAULT_H_BAND",
    "DEFAULT_J_BAND",
    "DEFAULT_K_BAND",
    "DEFAULT_SCENARIO_SOURCE_CLASS",
    "DEFAULT_SCENARIO_SOURCE_NOTE",
    "DMConfig",
    "DMModel",
    "DetectorLoopConfig",
    "DetectorShwfsCalibration",
    "LoopHistory",
    "Mapping",
    "NM_PER_M",
    "PHASE_TWO_PI",
    "PokeMtxResult",
    "REQUIRED_SCENARIO_NAMES",
    "ScenarioConfig",
    "ScenarioResult",
    "ScienceBandpass",
    "Sequence",
    *(("annotations",) if hasattr(_implementation, "annotations") else ()),
    "band_averaged_psf_metrics_from_opd",
    "build_control_space_phase_sequence",
    "dataclass",
    "default_error_budget_scenarios",
    "default_jhk_bandpasses",
    "expand_controlled_commands",
    "hashlib",
    "json",
    "math",
    "ndimage",
    "np",
    "phase_rad_to_opd_nm",
    "remove_piston_opd_nm",
    "replace",
    "residual_opd_nm_from_command",
    "run_detector_integrator_loop",
    "run_error_budget_scenario",
    "run_error_budget_scenarios",
    "scenario_results_as_dicts",
    "stable_array_descriptor",
    "summarize_scenario",
    "synthesize_dm_phase_rad",
    "top_hat_bandpass",
)
