"""Canonical import surface for the retained 2 m integration engine.

The notebook-11 fast integration is a frozen, seeded AO-REF-011 engine whose
outputs back the accepted fast regression baselines, so its numerics stay
byte-stable behind this module.  Examples and applications import it from
here; the installed ``shwfs_ao.legacy.ao_integration`` module remains the
identity-preserving compatibility surface during the AO-REF-021 Phase A
window and never warns on import.
"""

from __future__ import annotations

# AO-REF-021 Phase A: this canonical surface re-exports the retained
# legacy-shape integration engine.  The exact allowlist is pinned by the
# packaged deprecation inventory and tests/compat/test_phase_a_isolation.py;
# Phase B relocates or removes the adapter together with this dependency.
from ..legacy.ao_integration import (
    AOIntegrationError,
    IntegrationConfig,
    IntegrationRunResult,
    build_integration_system,
    build_jhk_bandpasses,
    load_reference_metrics,
    run_fast_integration,
    run_integration,
)


__all__ = (
    "AOIntegrationError",
    "IntegrationConfig",
    "IntegrationRunResult",
    "build_integration_system",
    "build_jhk_bandpasses",
    "load_reference_metrics",
    "run_fast_integration",
    "run_integration",
)
