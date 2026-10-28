"""Deprecated compatibility shim for :mod:`shwfs_ao.legacy.psf_tools`.

Importing this root-level module emits a DeprecationWarning built from
the packaged AO-REF-021 clock and inventory metadata; the re-exported
objects stay identical to the shwfs_ao implementations throughout the
compatibility window.
"""

import warnings as _warnings

import shwfs_ao._deprecation as _deprecation

from shwfs_ao.legacy import psf_tools as _implementation
from shwfs_ao.legacy.psf_tools import (
    compute_psf_from_phase,
    marechal_strehl,
    np,
    phase_for_science_wavelength,
    radial_profile,
    strehl_ratio,
)

if hasattr(_implementation, "annotations"):
    annotations = _implementation.annotations

_warnings.warn(
    _deprecation.root_shim_deprecation_message('psf_tools'),
    DeprecationWarning,
    stacklevel=2,
)

__all__ = (
    *(("annotations",) if hasattr(_implementation, "annotations") else ()),
    "compute_psf_from_phase",
    "marechal_strehl",
    "np",
    "phase_for_science_wavelength",
    "radial_profile",
    "strehl_ratio",
)
