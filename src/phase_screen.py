"""Deprecated compatibility shim for :mod:`shwfs_ao.legacy.phase_screen`.

Importing this root-level module emits a DeprecationWarning built from
the packaged AO-REF-021 clock and inventory metadata; the re-exported
objects stay identical to the shwfs_ao implementations throughout the
compatibility window.
"""

import warnings as _warnings

import shwfs_ao._deprecation as _deprecation

from shwfs_ao.legacy import phase_screen as _implementation
from shwfs_ao.legacy.phase_screen import (
    circular_mask_from_grid,
    fourier_phase_screen,
    frozen_flow_shift,
    frozen_flow_shift_physical,
    np,
    opd_to_phase,
    phase_to_opd,
    r0_from_seeing,
    remove_piston,
    rms,
    scale_r0_with_wavelength,
)

if hasattr(_implementation, "annotations"):
    annotations = _implementation.annotations

_warnings.warn(
    _deprecation.root_shim_deprecation_message('phase_screen'),
    DeprecationWarning,
    stacklevel=2,
)

__all__ = (
    *(("annotations",) if hasattr(_implementation, "annotations") else ()),
    "circular_mask_from_grid",
    "fourier_phase_screen",
    "frozen_flow_shift",
    "frozen_flow_shift_physical",
    "np",
    "opd_to_phase",
    "phase_to_opd",
    "r0_from_seeing",
    "remove_piston",
    "rms",
    "scale_r0_with_wavelength",
)
