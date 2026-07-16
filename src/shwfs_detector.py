"""Silent compatibility shim for :mod:`shwfs_ao.legacy.shwfs_detector`."""

from shwfs_ao.legacy import shwfs_detector as _implementation
from shwfs_ao.legacy.shwfs_detector import (
    add_detector_noise,
    build_detector_response_matrix,
    centroid,
    centroid_noise_scan,
    crop_center,
    lenslet_spot_from_phase,
    measure_centroid_shifts,
    nominal_lenslet_sampling_shape,
    np,
    reconstruct_from_centroid_shifts,
    reference_centroids,
    subaperture_masks,
)

if hasattr(_implementation, "annotations"):
    annotations = _implementation.annotations

__all__ = (
    "add_detector_noise",
    *(("annotations",) if hasattr(_implementation, "annotations") else ()),
    "build_detector_response_matrix",
    "centroid",
    "centroid_noise_scan",
    "crop_center",
    "lenslet_spot_from_phase",
    "measure_centroid_shifts",
    "nominal_lenslet_sampling_shape",
    "np",
    "reconstruct_from_centroid_shifts",
    "reference_centroids",
    "subaperture_masks",
)
