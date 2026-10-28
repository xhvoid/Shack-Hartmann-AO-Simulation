"""Canonical import surface for the retained physical validation checks.

The scenario-level validation checks are frozen AO-REF-011 diagnostics whose
outputs back the accepted fast validation regression baseline, so their
numerics stay byte-stable behind this module.  Examples and applications
import them from here; ``shwfs_ao.legacy.ao_validation`` remains the
identity-preserving compatibility surface during the AO-REF-021 Phase A
window and never warns on import.
"""

from __future__ import annotations

# AO-REF-021 Phase A: this canonical surface re-exports the retained
# legacy-shape validation checks and the loop configuration they scan over.
# The exact allowlist is pinned by the packaged deprecation inventory and
# tests/compat/test_phase_a_isolation.py; Phase B relocates or removes the
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
