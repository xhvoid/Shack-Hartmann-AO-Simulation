"""Deprecated compatibility shim for :mod:`shwfs_ao.legacy.pwfs_forward`.

Importing this root-level module emits a DeprecationWarning built from
the packaged AO-REF-021 clock and inventory metadata; the re-exported
objects stay identical to the shwfs_ao implementations throughout the
compatibility window.
"""

import warnings as _warnings

import shwfs_ao._deprecation as _deprecation

from shwfs_ao.legacy import pwfs_forward as _implementation
from shwfs_ao.legacy.pwfs_forward import (
    add_detector_noise,
    add_tilt_phase,
    aligned_pupil_images,
    calibrate_pwfs_interaction_matrix,
    check_pwfs_geometry,
    extract_cutout,
    fft2c,
    ifft2c,
    make_aligned_pupil_mask,
    make_modulation_points,
    make_pwfs_grid,
    np,
    pupil_image_centers,
    pwfs_detector_measurement_from_phase,
    pwfs_detector_signal_from_phase,
    pwfs_intensity,
    pwfs_measurement_from_phase,
    pwfs_reference_signal,
    pwfs_signal_from_intensity,
    pwfs_signal_from_phase,
    pwfs_signal_maps_from_intensity,
    pyramid_phase_mask,
)

_warnings.warn(
    _deprecation.root_shim_deprecation_message('pwfs_forward'),
    DeprecationWarning,
    stacklevel=2,
)

__all__ = (
    "add_detector_noise",
    "add_tilt_phase",
    "aligned_pupil_images",
    "calibrate_pwfs_interaction_matrix",
    "check_pwfs_geometry",
    "extract_cutout",
    "fft2c",
    "ifft2c",
    "make_aligned_pupil_mask",
    "make_modulation_points",
    "make_pwfs_grid",
    "np",
    "pupil_image_centers",
    "pwfs_detector_measurement_from_phase",
    "pwfs_detector_signal_from_phase",
    "pwfs_intensity",
    "pwfs_measurement_from_phase",
    "pwfs_reference_signal",
    "pwfs_signal_from_intensity",
    "pwfs_signal_from_phase",
    "pwfs_signal_maps_from_intensity",
    "pyramid_phase_mask",
)
