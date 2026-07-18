"""Deprecated compatibility shim for :mod:`shwfs_ao.legacy.shwfs_detector`.

Importing this root-level module emits a DeprecationWarning built from
the packaged AO-REF-021 clock and inventory metadata; the re-exported
objects stay identical to the shwfs_ao implementations throughout the
compatibility window.
"""

import warnings as _warnings

import shwfs_ao._deprecation as _deprecation

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

_warnings.warn(
    _deprecation.root_shim_deprecation_message('shwfs_detector'),
    DeprecationWarning,
    stacklevel=2,
)

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
