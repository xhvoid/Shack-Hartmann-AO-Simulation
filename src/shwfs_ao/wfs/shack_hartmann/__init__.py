"""Canonical Shack--Hartmann geometry, calibration, and sensors."""

from .calibration import (
    ShackHartmannCalibration,
    ShackHartmannCalibrationError,
    calibrate_zero_phase_reference,
    legacy_calibration_seeds,
    row_ids_for_subapertures,
    shack_hartmann_calibration_hash,
)
from .geometric import (
    GeometricShackHartmannCalibration,
    GeometricShackHartmannError,
    GeometricShackHartmannSensor,
    NativeGeometricShackHartmannSensor,
    mean_subaperture_slopes,
    numerical_gradient,
)
from .geometry import (
    DEFAULT_WFS_WAVELENGTH_M,
    ShackHartmannGeometry,
    ShackHartmannGeometryError,
    ShwfsGeometryConfig,
    build_shack_hartmann_geometry,
    lenslet_indices_from_id,
    partition_pupil_geometry,
    subaperture_id,
)
from .measurement import (
    DetectorLevelShackHartmannSensor,
    DetectorShackHartmannSensor,
    ShackHartmannMeasurementError,
    build_detector_shack_hartmann_sensor,
)
from .optics import (
    ShackHartmannOpticsError,
    make_detector_plane_sampling,
    validate_optics_backend_result,
    validate_spot_intensity_result,
)


__all__ = (
    "DEFAULT_WFS_WAVELENGTH_M",
    "ShwfsGeometryConfig",
    "ShackHartmannGeometryError",
    "ShackHartmannGeometry",
    "build_shack_hartmann_geometry",
    "partition_pupil_geometry",
    "subaperture_id",
    "lenslet_indices_from_id",
    "ShackHartmannOpticsError",
    "make_detector_plane_sampling",
    "validate_spot_intensity_result",
    "validate_optics_backend_result",
    "ShackHartmannCalibrationError",
    "ShackHartmannCalibration",
    "row_ids_for_subapertures",
    "calibrate_zero_phase_reference",
    "shack_hartmann_calibration_hash",
    "legacy_calibration_seeds",
    "ShackHartmannMeasurementError",
    "DetectorShackHartmannSensor",
    "DetectorLevelShackHartmannSensor",
    "build_detector_shack_hartmann_sensor",
    "GeometricShackHartmannError",
    "GeometricShackHartmannCalibration",
    "NativeGeometricShackHartmannSensor",
    "GeometricShackHartmannSensor",
    "numerical_gradient",
    "mean_subaperture_slopes",
)
