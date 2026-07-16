"""Silent compatibility shim for :mod:`shwfs_ao.legacy.psf_tools`."""

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

__all__ = (
    *(("annotations",) if hasattr(_implementation, "annotations") else ()),
    "compute_psf_from_phase",
    "marechal_strehl",
    "np",
    "phase_for_science_wavelength",
    "radial_profile",
    "strehl_ratio",
)
