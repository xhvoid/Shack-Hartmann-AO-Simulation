"""Canonical detector configuration, realization, effects, and centroiding."""

from .centroid import (
    CenterOfGravityEstimator,
    CentroidConfig,
    CentroidEstimate,
    CentroidEstimator,
    CentroidMethod,
    ThresholdedCenterOfGravityEstimator,
    estimate_centroid,
    make_centroid_estimator,
)
from .config import (
    DEFAULT_SOURCE_CLASS,
    DETECTOR_PRESETS,
    DetectorConfig,
    DetectorConfigError,
    DetectorPreset,
    PrnuMode,
    SyntheticInstrumentError,
    detector_preset,
    make_bad_pixel_mask,
)
from .effects import (
    DetectorEffectsError,
    apply_detector_effects,
    apply_legacy_detector_effects,
)
from .random import DetectorRealization, DetectorRealizationError
from .validity import (
    DEFAULT_CENTROID_VALIDITY,
    UNDEFINED_CENTROID_SIGMA_PX,
    CentroidQuality,
    CentroidValidity,
    CentroidValidityConfig,
    centroid_quality,
    evaluate_centroid_validity,
)

__all__ = (
    "DEFAULT_SOURCE_CLASS",
    "DETECTOR_PRESETS",
    "PrnuMode",
    "SyntheticInstrumentError",
    "DetectorConfigError",
    "DetectorConfig",
    "DetectorPreset",
    "detector_preset",
    "make_bad_pixel_mask",
    "DetectorRealizationError",
    "DetectorRealization",
    "DetectorEffectsError",
    "apply_detector_effects",
    "apply_legacy_detector_effects",
    "CentroidMethod",
    "CentroidConfig",
    "CentroidEstimate",
    "CentroidEstimator",
    "CenterOfGravityEstimator",
    "ThresholdedCenterOfGravityEstimator",
    "make_centroid_estimator",
    "estimate_centroid",
    "CentroidValidityConfig",
    "CentroidQuality",
    "CentroidValidity",
    "DEFAULT_CENTROID_VALIDITY",
    "UNDEFINED_CENTROID_SIGMA_PX",
    "centroid_quality",
    "evaluate_centroid_validity",
)
