"""Seeded integration helper for the older fast demonstration.

This module re-exports the retained implementation to preserve its API and
numerical behaviour. New detector-level runs use experiments.scao."""

from __future__ import annotations

# This module re-exports the retained
# legacy-shape integration engine.  The exact allowlist is pinned by the
# packaged deprecation inventory and tests/compat/test_phase_a_isolation.py;
# A later migration may relocate or remove the adapter together with this dependency.
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
