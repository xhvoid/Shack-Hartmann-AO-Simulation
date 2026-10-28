"""Deprecated compatibility shim for :mod:`shwfs_ao.legacy.reconstruction`.

Importing this root-level module emits a DeprecationWarning built from
the packaged AO-REF-021 clock and inventory metadata; the re-exported
objects stay identical to the shwfs_ao implementations throughout the
compatibility window.
"""

import warnings as _warnings

import shwfs_ao._deprecation as _deprecation

from shwfs_ao.legacy import reconstruction as _implementation
from shwfs_ao.legacy.reconstruction import (
    build_response_matrix,
    measure_geometric_slopes,
    measure_slopes,
    np,
    numerical_gradient,
    reconstruct_modal_coefficients,
    reconstruct_tikhonov,
    reconstruct_tsvd,
    reconstruct_wavefront,
    remove_piston,
    residual_wavefront,
    rms,
    subaperture_masks,
    synthesize_from_coefficients,
)

if hasattr(_implementation, "annotations"):
    annotations = _implementation.annotations

_warnings.warn(
    _deprecation.root_shim_deprecation_message('reconstruction'),
    DeprecationWarning,
    stacklevel=2,
)

__all__ = (
    *(("annotations",) if hasattr(_implementation, "annotations") else ()),
    "build_response_matrix",
    "measure_geometric_slopes",
    "measure_slopes",
    "np",
    "numerical_gradient",
    "reconstruct_modal_coefficients",
    "reconstruct_tikhonov",
    "reconstruct_tsvd",
    "reconstruct_wavefront",
    "remove_piston",
    "residual_wavefront",
    "rms",
    "subaperture_masks",
    "synthesize_from_coefficients",
)
