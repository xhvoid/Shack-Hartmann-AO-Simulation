"""Installed compatibility facade for :mod:`shwfs_ao.experiments.error_budget`.

AO-REF-011 moved the physical scenario implementation to the experiments
package.  Every historical non-private runtime name remains an explicit
identity re-export so editable and wheel installations keep the frozen
compatibility surface.
"""

from __future__ import annotations

from ..core.provenance import (
    ALLOWED_SOURCE_CLASSES,
    Provenance as _Provenance,
)
from ..experiments import error_budget as _implementation
from ..experiments.error_budget import (
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
