"""Science bandpasses, propagation, and physical scalar PSF metrics."""

from .bandpass import (
    BandpassError,
    ScienceBandpass,
    bandpass_from_filter_curve,
    monochromatic_bandpass,
    top_hat_bandpass,
)
from .propagation import (
    PsfSampling,
    SciencePropagationError,
    monochromatic_psf,
)
from .metrics import (
    PsfScalarMetrics,
    ScienceMetricsError,
    band_average_scalar_metrics,
    discrete_flux_to_angular_surface_brightness,
    encircled_energy_radius_from_discrete_flux,
    fwhm_diameter_from_angular_surface_brightness,
    halo_fraction_from_discrete_flux,
    lambda_over_d_rad,
    marechal_strehl_from_opd,
    peak_strehl_from_discrete_flux,
    psf_scalar_metrics,
    radians_to_arcsec,
    radians_to_lambda_over_d,
)


__all__ = (
    "BandpassError",
    "ScienceBandpass",
    "monochromatic_bandpass",
    "top_hat_bandpass",
    "bandpass_from_filter_curve",
    "SciencePropagationError",
    "PsfSampling",
    "monochromatic_psf",
    "ScienceMetricsError",
    "PsfScalarMetrics",
    "discrete_flux_to_angular_surface_brightness",
    "peak_strehl_from_discrete_flux",
    "marechal_strehl_from_opd",
    "fwhm_diameter_from_angular_surface_brightness",
    "encircled_energy_radius_from_discrete_flux",
    "halo_fraction_from_discrete_flux",
    "psf_scalar_metrics",
    "band_average_scalar_metrics",
    "lambda_over_d_rad",
    "radians_to_lambda_over_d",
    "radians_to_arcsec",
)
