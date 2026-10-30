"""Scenario-level diagnostic helpers retained for older examples.

The implementation is re-exported from the compatibility module so existing
callers use the same functions and result conventions."""

from __future__ import annotations

# This module re-exports the retained
# legacy-shape validation checks and the loop configuration they scan over.
# The exact allowlist is pinned by the packaged deprecation inventory and
# tests/compat/test_phase_a_isolation.py; A later migration may relocate or remove the
# adapters together with this dependency.
from ..legacy.ao_closed_loop import DetectorLoopConfig
from ..legacy.ao_validation import (
    AOValidationError,
    ValidationCheckResult,
    ValidationScanResult,
    check_centroid_noise_photon_monotonicity,
    check_diffraction_scale,
    check_dm_fitting_trend,
    check_latency_residual_monotonicity,
    check_marechal_consistency,
    check_scenario_reproducibility,
    validation_results_as_dicts,
)


__all__ = (
    "AOValidationError",
    "DetectorLoopConfig",
    "ValidationCheckResult",
    "ValidationScanResult",
    "check_centroid_noise_photon_monotonicity",
    "check_diffraction_scale",
    "check_dm_fitting_trend",
    "check_latency_residual_monotonicity",
    "check_marechal_consistency",
    "check_scenario_reproducibility",
    "validation_results_as_dicts",
)
