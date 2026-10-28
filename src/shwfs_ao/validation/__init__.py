"""Backend validation: physical estimators, baselines, and cross-backend suite.

``physical`` owns backend-neutral numerical estimators, ``regression`` owns
the baseline document contract and its evaluation, and ``cross_backend``
owns the native-versus-HCIPy comparison suite.  Importing this package never
imports the optional HCIPy dependency; only executing the cross-backend
suite resolves it.

Ticket T2 (2026-10-21) adds three validation-only modules, none of which is
used by production code: ``encircled_energy`` (the Fourier encircled-energy
reference and the continuous Airy/annular references), ``richardson`` (the
Richardson analysis of a refinement scan) and ``atmosphere_pairing`` (the
physical-coordinate checks of the paired layered-atmosphere input).
"""

from __future__ import annotations

from .atmosphere_pairing import (
    DilationReport,
    PairingError,
    band_edge_power_fraction,
    band_field_on_coordinates,
    common_band_power_fraction,
    compare_paired_band_fields,
    physical_frequency_dilation,
)
from .encircled_energy import (
    EncircledEnergyError,
    FourierEncircledEnergy,
    InterpolantArtefacts,
    airy_encircled_energy,
    annular_encircled_energy,
    annular_encircled_energy_bessel_form,
    annular_encircled_energy_radius,
    annular_psf_normalized_intensity,
    fourier_encircled_energy,
)
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
from .richardson import (
    RichardsonError,
    RichardsonResult,
    change_table,
    richardson_estimate,
)


__all__ = (
    "DilationReport",
    "PairingError",
    "band_edge_power_fraction",
    "band_field_on_coordinates",
    "common_band_power_fraction",
    "compare_paired_band_fields",
    "physical_frequency_dilation",
    "EncircledEnergyError",
    "FourierEncircledEnergy",
    "InterpolantArtefacts",
    "airy_encircled_energy",
    "annular_encircled_energy",
    "annular_encircled_energy_bessel_form",
    "annular_encircled_energy_radius",
    "annular_psf_normalized_intensity",
    "fourier_encircled_energy",
    "RichardsonError",
    "RichardsonResult",
    "change_table",
    "richardson_estimate",
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
