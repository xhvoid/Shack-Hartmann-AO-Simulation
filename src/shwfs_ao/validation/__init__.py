"""Backend validation: physical estimators, baselines, and cross-backend suite.

``physical`` owns backend-neutral numerical estimators, ``regression`` owns
the baseline document contract and its evaluation, and ``cross_backend``
owns the native-versus-HCIPy comparison suite.  Importing this package never
imports the optional HCIPy dependency; only executing the cross-backend
suite resolves it.
"""

from __future__ import annotations

from .physical import (
    PhysicalEstimatorError,
    centroid_xy_px,
    encircled_energy_radius_rad,
    mean_square_column_difference,
    normalized_singular_spectrum,
)
from .regression import (
    CROSS_BACKEND_BASELINE_SCHEMA_NAME,
    CROSS_BACKEND_BASELINE_SCHEMA_VERSION,
    CROSS_BACKEND_REPORT_SCHEMA_NAME,
    BaselineContractError,
    evaluate_report_against_baseline,
    load_cross_backend_baseline,
    validate_cross_backend_baseline,
    validate_cross_backend_report,
)


__all__ = (
    "PhysicalEstimatorError",
    "centroid_xy_px",
    "encircled_energy_radius_rad",
    "mean_square_column_difference",
    "normalized_singular_spectrum",
    "CROSS_BACKEND_BASELINE_SCHEMA_NAME",
    "CROSS_BACKEND_BASELINE_SCHEMA_VERSION",
    "CROSS_BACKEND_REPORT_SCHEMA_NAME",
    "BaselineContractError",
    "evaluate_report_against_baseline",
    "load_cross_backend_baseline",
    "validate_cross_backend_baseline",
    "validate_cross_backend_report",
)
