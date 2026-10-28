"""Deprecated compatibility shim for :mod:`shwfs_ao.legacy.zernike`.

Importing this root-level module emits a DeprecationWarning built from
the packaged AO-REF-021 clock and inventory metadata; the re-exported
objects stay identical to the shwfs_ao implementations throughout the
compatibility window.
"""

import warnings as _warnings

import shwfs_ao._deprecation as _deprecation

from shwfs_ao.legacy import zernike as _implementation
from shwfs_ao.legacy.zernike import (
    eval_jacobi,
    generate_zernike_modes,
    make_pupil_grid,
    np,
    number_of_zernike_modes,
    remove_piston,
    rms,
    synthesize_wavefront,
    zernike_gram_matrix,
    zernike_inner_product,
    zernike_named_modes,
    zernike_nm,
    zernike_radial,
)

if hasattr(_implementation, "annotations"):
    annotations = _implementation.annotations

_warnings.warn(
    _deprecation.root_shim_deprecation_message('zernike'),
    DeprecationWarning,
    stacklevel=2,
)

__all__ = (
    *(("annotations",) if hasattr(_implementation, "annotations") else ()),
    "eval_jacobi",
    "generate_zernike_modes",
    "make_pupil_grid",
    "np",
    "number_of_zernike_modes",
    "remove_piston",
    "rms",
    "synthesize_wavefront",
    "zernike_gram_matrix",
    "zernike_inner_product",
    "zernike_named_modes",
    "zernike_nm",
    "zernike_radial",
)
