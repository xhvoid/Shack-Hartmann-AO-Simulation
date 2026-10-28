"""Canonical import surface for the legacy-shape scenario instrument.

The error-budget and validation scenario engines consume a frozen
legacy-shape synthetic instrument: nm-unit detector Shack-Hartmann
calibration, DM model, and poke-matrix construction.  This module is the
canonical import path for building that instrument; the configuration types
here are the scenario-shaped ones, distinct from the canonical
:mod:`shwfs_ao.detector` and :mod:`shwfs_ao.dm` configurations.
"""

from __future__ import annotations

# AO-REF-021 Phase A: this canonical surface re-exports the retained
# legacy-shape instrument builders.  The exact allowlist is pinned by the
# packaged deprecation inventory and tests/compat/test_phase_a_isolation.py;
# Phase B relocates or removes the adapters together with this dependency.
from ..legacy.dm_model import DMConfig, DMModel, build_dm_model
from ..legacy.interaction_matrix import (
    DEFAULT_POKE_AMPLITUDE_GRID_NM,
    InteractionMatrixError,
    PokeMatrixConfig,
    PokeMtxResult,
    build_detector_dm_poke_matrix,
    poke_amplitude_scan,
    poke_matrix_summary,
)
from ..legacy.synthetic_instrument_data import (
    DetectorConfig,
    DetectorShwfsCalibration,
    ShwfsGeometryConfig,
    build_detector_shwfs_calibration,
)


__all__ = (
    "DEFAULT_POKE_AMPLITUDE_GRID_NM",
    "DMConfig",
    "DMModel",
    "DetectorConfig",
    "DetectorShwfsCalibration",
    "InteractionMatrixError",
    "PokeMatrixConfig",
    "PokeMtxResult",
    "ShwfsGeometryConfig",
    "build_detector_dm_poke_matrix",
    "build_detector_shwfs_calibration",
    "build_dm_model",
    "poke_amplitude_scan",
    "poke_matrix_summary",
)
