"""Silent compatibility shim for :mod:`shwfs_ao.legacy.reconstruction`."""

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
