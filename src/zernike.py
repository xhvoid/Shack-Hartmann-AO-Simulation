"""Silent compatibility shim for :mod:`shwfs_ao.legacy.zernike`."""

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
