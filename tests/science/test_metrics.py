"""Physical-grid contract tests for canonical scalar science metrics."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import math

import numpy as np
import pytest

from shwfs_ao.core import PsfResult
from shwfs_ao.backends.native.propagation import NativeSciencePropagator
from shwfs_ao.core.geometry import build_pupil_geometry
from shwfs_ao.science.metrics import (
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
from shwfs_ao.science.propagation import PsfSampling


def _cell_widths(axis: np.ndarray) -> np.ndarray:
    boundaries = np.empty(axis.size + 1, dtype=float)
    boundaries[1:-1] = 0.5 * (axis[:-1] + axis[1:])
    boundaries[0] = axis[0] - 0.5 * (axis[1] - axis[0])
    boundaries[-1] = axis[-1] + 0.5 * (axis[-1] - axis[-2])
    return np.diff(boundaries)


def _gaussian_grid() -> tuple[
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    float,
]:
    """Return surface brightness and flux on an irregular rectangular grid."""

    sigma_rad = 1.0e-6
    x_uniform = np.linspace(-6.0, 6.0, 161)
    y_uniform = np.linspace(-6.0, 6.0, 121)
    x_angle_rad = sigma_rad * (x_uniform + 0.008 * x_uniform**3)
    y_angle_rad = sigma_rad * (y_uniform + 0.006 * y_uniform**3)
    y_grid, x_grid = np.meshgrid(y_angle_rad, x_angle_rad, indexing="ij")
    surface_brightness = np.exp(
        -(x_grid**2 + y_grid**2) / (2.0 * sigma_rad**2)
    )
    solid_angle = np.multiply.outer(
        _cell_widths(y_angle_rad),
        _cell_widths(x_angle_rad),
    )
    discrete_flux = surface_brightness * solid_angle
    discrete_flux /= np.sum(discrete_flux)
    return (
        x_angle_rad,
        y_angle_rad,
        surface_brightness,
        discrete_flux,
        sigma_rad,
    )


def _psf(
    intensity: np.ndarray,
    x_angle_rad: np.ndarray,
    y_angle_rad: np.ndarray,
    *,
    wavelength_m: float = 1.0e-6,
    backend_name: str = "analytic_test",
    sampling_metadata: dict[str, object] | None = None,
) -> PsfResult:
    return PsfResult(
        intensity=np.asarray(intensity, dtype=float),
        x_angle_rad=np.asarray(x_angle_rad, dtype=float),
        y_angle_rad=np.asarray(y_angle_rad, dtype=float),
        wavelength_m=wavelength_m,
        normalization="unit_total_flux",
        backend_name=backend_name,
        sampling_metadata=(
            {"grid": "irregular_rectangular"}
            if sampling_metadata is None
            else sampling_metadata
        ),
    )


def _metric_row(*, wavelength_m: float = 1.0e-6) -> PsfScalarMetrics:
    diameter_m = 2.0
    lod_rad = wavelength_m / diameter_m
    return PsfScalarMetrics(
        wavelength_m=wavelength_m,
        telescope_diameter_m=diameter_m,
        opd_rms_m=20.0e-9,
        peak_strehl=0.90,
        marechal_strehl=0.88,
        marechal_abs_difference=0.02,
        fwhm_rad=lod_rad,
        fwhm_lambda_over_d=1.0,
        fwhm_arcsec=radians_to_arcsec(lod_rad),
        ee50_rad=0.6 * lod_rad,
        ee50_lambda_over_d=0.6,
        ee50_arcsec=radians_to_arcsec(0.6 * lod_rad),
        ee80_rad=1.5 * lod_rad,
        ee80_lambda_over_d=1.5,
        ee80_arcsec=radians_to_arcsec(1.5 * lod_rad),
        halo_fraction=0.12,
        halo_inner_radius_rad=3.0 * lod_rad,
        halo_inner_lambda_over_d=3.0,
    )


def test_irregular_rectangular_gaussian_has_analytic_physical_metrics() -> None:
    x_axis, y_axis, brightness, flux, sigma_rad = _gaussian_grid()

    fwhm_rad = fwhm_diameter_from_angular_surface_brightness(
        brightness,
        x_axis,
        y_axis,
        center_angle_rad=(0.0, 0.0),
    )
    ee50_rad = encircled_energy_radius_from_discrete_flux(
        flux,
        x_axis,
        y_axis,
        0.50,
        center_angle_rad=(0.0, 0.0),
    )
    ee80_rad = encircled_energy_radius_from_discrete_flux(
        flux,
        x_axis,
        y_axis,
        0.80,
        center_angle_rad=(0.0, 0.0),
    )
    halo = halo_fraction_from_discrete_flux(
        flux,
        x_axis,
        y_axis,
        2.0 * sigma_rad,
        center_angle_rad=(0.0, 0.0),
    )

    assert fwhm_rad == pytest.approx(
        2.0 * math.sqrt(2.0 * math.log(2.0)) * sigma_rad,
        rel=0.04,
    )
    assert ee50_rad == pytest.approx(
        sigma_rad * math.sqrt(2.0 * math.log(2.0)),
        rel=0.02,
    )
    assert ee80_rad == pytest.approx(
        sigma_rad * math.sqrt(-2.0 * math.log(0.20)),
        rel=0.02,
    )
    assert halo == pytest.approx(math.exp(-2.0), rel=0.02)


def test_discrete_flux_conversion_uses_irregular_pixel_solid_angle() -> None:
    x_axis, y_axis, brightness, flux, _ = _gaussian_grid()
    psf = _psf(flux, x_axis, y_axis)

    recovered = discrete_flux_to_angular_surface_brightness(psf)

    expected = brightness / np.sum(
        brightness
        * np.multiply.outer(_cell_widths(y_axis), _cell_widths(x_axis))
    )
    assert np.allclose(recovered, expected, rtol=2.0e-15, atol=0.0)
    assert not recovered.flags.writeable
    with pytest.raises(ValueError):
        recovered.setflags(write=True)


@pytest.mark.parametrize(
    ("x_axis", "y_axis", "message"),
    (
        (
            np.asarray([-1.0, 0.0, 0.0]),
            np.asarray([-1.0, 0.0]),
            "strictly increasing",
        ),
        (
            np.asarray([-1.0, 0.0, 1.0]),
            np.asarray([-1.0, np.nan]),
            "must be finite",
        ),
        (
            np.asarray([-1.0, 1.0]),
            np.asarray([-1.0, 0.0]),
            "does not match grid dimension",
        ),
    ),
)
def test_raw_metrics_reject_malformed_physical_axes(
    x_axis: np.ndarray,
    y_axis: np.ndarray,
    message: str,
) -> None:
    flux = np.ones((2, 3), dtype=float)

    with pytest.raises(ScienceMetricsError, match=message):
        encircled_energy_radius_from_discrete_flux(
            flux,
            x_axis,
            y_axis,
            0.50,
        )


def test_peak_strehl_requires_one_exact_discrete_flux_grid() -> None:
    x_axis, y_axis, _, flux, _ = _gaussian_grid()
    science = _psf(flux, x_axis, y_axis)
    ideal = _psf(flux, x_axis, y_axis)

    assert peak_strehl_from_discrete_flux(science, ideal) == pytest.approx(1.0)

    shifted_x = x_axis.copy()
    shifted_x += 1.0e-12
    mismatched = _psf(flux, shifted_x, y_axis)
    with pytest.raises(ScienceMetricsError, match="identical physical angular axes"):
        peak_strehl_from_discrete_flux(science, mismatched)

    mismatched_backend = _psf(
        flux,
        x_axis,
        y_axis,
        backend_name="another_backend",
    )
    with pytest.raises(ScienceMetricsError, match="same propagation backend"):
        peak_strehl_from_discrete_flux(science, mismatched_backend)

    mismatched_sampling = _psf(
        flux,
        x_axis,
        y_axis,
        sampling_metadata={"grid": "same_axes_different_sampling"},
    )
    with pytest.raises(ScienceMetricsError, match="pupil and sampling metadata"):
        peak_strehl_from_discrete_flux(science, mismatched_sampling)


def test_irregular_grid_peak_and_default_center_use_surface_brightness() -> None:
    x_axis = np.asarray([0.0, 1.0e-6, 10.0e-6])
    y_axis = np.asarray([0.0, 1.0e-6, 2.0e-6])
    science_flux = np.asarray(
        [
            [0.18, 0.01, 0.35],
            [0.16, 0.01, 0.10],
            [0.15, 0.01, 0.03],
        ]
    )
    science_flux /= np.sum(science_flux)
    ideal_flux = np.asarray(
        [
            [0.24, 0.02, 0.30],
            [0.18, 0.02, 0.10],
            [0.10, 0.02, 0.02],
        ]
    )
    ideal_flux /= np.sum(ideal_flux)
    science = _psf(science_flux, x_axis, y_axis)
    ideal = _psf(ideal_flux, x_axis, y_axis)
    solid_angle = np.multiply.outer(
        _cell_widths(y_axis),
        _cell_widths(x_axis),
    )

    expected_strehl = np.max(science_flux / solid_angle) / np.max(
        ideal_flux / solid_angle
    )
    raw_flux_peak_ratio = np.max(science_flux) / np.max(ideal_flux)
    assert peak_strehl_from_discrete_flux(science, ideal) == pytest.approx(
        expected_strehl
    )
    assert expected_strehl != pytest.approx(raw_flux_peak_ratio)

    ee_default = encircled_energy_radius_from_discrete_flux(
        science_flux,
        x_axis,
        y_axis,
        0.50,
    )
    ee_surface_brightness_center = encircled_energy_radius_from_discrete_flux(
        science_flux,
        x_axis,
        y_axis,
        0.50,
        center_angle_rad=(x_axis[0], y_axis[0]),
    )
    halo_default = halo_fraction_from_discrete_flux(
        science_flux,
        x_axis,
        y_axis,
        1.5e-6,
    )
    halo_surface_brightness_center = halo_fraction_from_discrete_flux(
        science_flux,
        x_axis,
        y_axis,
        1.5e-6,
        center_angle_rad=(x_axis[0], y_axis[0]),
    )
    assert ee_default == ee_surface_brightness_center
    assert halo_default == halo_surface_brightness_center


@pytest.mark.parametrize(
    "metric",
    (encircled_energy_radius_from_discrete_flux, halo_fraction_from_discrete_flux),
)
def test_flux_metrics_reject_surface_brightness_overflow(metric: object) -> None:
    flux = np.full((2, 2), 0.25)
    x_axis = np.asarray([0.0, 1.0e-200])
    y_axis = np.asarray([0.0, 1.0e-120])
    with pytest.raises(ScienceMetricsError, match="finite surface brightness"):
        if metric is encircled_energy_radius_from_discrete_flux:
            metric(flux, x_axis, y_axis, 0.50)  # type: ignore[operator]
        else:
            metric(flux, x_axis, y_axis, 0.0)  # type: ignore[operator]


def test_marechal_uses_residual_opd_metres_at_science_wavelength() -> None:
    sigma_opd_m = 45.0e-9
    opd_m = np.asarray(
        [[-sigma_opd_m, sigma_opd_m], [-sigma_opd_m, sigma_opd_m]]
    )
    pupil = np.ones((2, 2), dtype=bool)

    one_micron = marechal_strehl_from_opd(opd_m, pupil, 1.0e-6)
    two_micron = marechal_strehl_from_opd(opd_m, pupil, 2.0e-6)

    expected = math.exp(-((2.0 * math.pi * sigma_opd_m / 1.0e-6) ** 2))
    assert one_micron == pytest.approx(expected)
    assert two_micron > one_micron


def test_high_level_metrics_preserve_si_angular_conversions_and_semantics() -> None:
    x_axis, y_axis, _, flux, _ = _gaussian_grid()
    psf = _psf(flux, x_axis, y_axis, wavelength_m=1.25e-6)
    pupil = np.ones((4, 5), dtype=bool)
    residual_opd_m = np.zeros(pupil.shape, dtype=float)

    result = psf_scalar_metrics(
        psf,
        psf,
        residual_opd_m,
        pupil,
        telescope_diameter_m=2.5,
        halo_inner_lambda_over_d=2.0,
    )

    lod_rad = lambda_over_d_rad(1.25e-6, 2.5)
    assert result.peak_strehl == pytest.approx(1.0)
    assert result.marechal_strehl == pytest.approx(1.0)
    assert result.marechal_abs_difference == pytest.approx(0.0)
    assert result.fwhm_lambda_over_d == pytest.approx(result.fwhm_rad / lod_rad)
    assert result.ee50_lambda_over_d == pytest.approx(result.ee50_rad / lod_rad)
    assert result.ee80_lambda_over_d == pytest.approx(result.ee80_rad / lod_rad)
    assert result.fwhm_arcsec == pytest.approx(radians_to_arcsec(result.fwhm_rad))
    assert result.halo_inner_radius_rad == pytest.approx(2.0 * lod_rad)
    assert result.flux_semantics == "discrete_pixel_flux"
    assert result.fwhm_semantics == "angular_surface_brightness_per_sr"
    assert result.aggregation == "monochromatic"


def test_high_level_reports_marechal_absolute_difference() -> None:
    x_axis, y_axis, _, flux, _ = _gaussian_grid()
    psf = _psf(flux, x_axis, y_axis, wavelength_m=1.0e-6)
    residual_opd_m = np.asarray([[-50.0e-9, 50.0e-9], [-50.0e-9, 50.0e-9]])
    pupil = np.ones(residual_opd_m.shape, dtype=bool)

    result = psf_scalar_metrics(
        psf,
        psf,
        residual_opd_m,
        pupil,
        telescope_diameter_m=2.0,
    )

    assert result.peak_strehl == pytest.approx(1.0)
    assert result.marechal_strehl < result.peak_strehl
    assert result.marechal_abs_difference == pytest.approx(
        abs(result.peak_strehl - result.marechal_strehl)
    )


def test_native_diffraction_metrics_scale_with_science_wavelength() -> None:
    pupil = build_pupil_geometry(
        telescope_diameter_m=2.0,
        pupil_shape=(48, 48),
    )
    opd_m = np.where(pupil.pupil_mask, 0.0, np.nan)
    propagator = NativeSciencePropagator(pupil, PsfSampling(6))
    short_psf = propagator.psf_from_opd(opd_m, 1.0e-6)
    long_psf = propagator.psf_from_opd(opd_m, 2.0e-6)

    short = psf_scalar_metrics(
        short_psf,
        short_psf,
        opd_m,
        pupil,
        telescope_diameter_m=2.0,
    )
    long = psf_scalar_metrics(
        long_psf,
        long_psf,
        opd_m,
        pupil,
        telescope_diameter_m=2.0,
    )

    assert 0.75 < short.fwhm_lambda_over_d < 1.15
    assert long.fwhm_lambda_over_d == pytest.approx(
        short.fwhm_lambda_over_d,
        rel=1.0e-12,
    )
    assert long.fwhm_rad == pytest.approx(2.0 * short.fwhm_rad, rel=1.0e-12)
    assert long.ee50_rad == pytest.approx(2.0 * short.ee50_rad, rel=1.0e-12)
    assert long.ee80_rad == pytest.approx(2.0 * short.ee80_rad, rel=1.0e-12)
    assert short.peak_strehl == long.peak_strehl == pytest.approx(1.0)


def test_native_metrics_bind_ideal_and_residual_to_exact_pupil_identity() -> None:
    clear = build_pupil_geometry(
        telescope_diameter_m=2.0,
        pupil_shape=(32, 32),
    )
    obstructed = build_pupil_geometry(
        telescope_diameter_m=2.0,
        pupil_shape=(32, 32),
        central_obstruction_ratio=0.5,
    )
    sampling = PsfSampling(3)
    clear_opd = np.where(clear.pupil_mask, 0.0, np.nan)
    obstructed_opd = np.where(obstructed.pupil_mask, 0.0, np.nan)
    clear_psf = NativeSciencePropagator(clear, sampling).psf_from_opd(
        clear_opd,
        1.0e-6,
    )
    obstructed_psf = NativeSciencePropagator(obstructed, sampling).psf_from_opd(
        obstructed_opd,
        1.0e-6,
    )

    with pytest.raises(ScienceMetricsError, match="pupil and sampling metadata"):
        peak_strehl_from_discrete_flux(obstructed_psf, clear_psf)
    with pytest.raises(ScienceMetricsError, match="must be the PupilGeometry"):
        psf_scalar_metrics(
            clear_psf,
            clear_psf,
            clear_opd,
            clear.pupil_mask,
            telescope_diameter_m=2.0,
        )
    with pytest.raises(ScienceMetricsError, match="does not match psf"):
        psf_scalar_metrics(
            clear_psf,
            clear_psf,
            obstructed_opd,
            obstructed,
            telescope_diameter_m=2.0,
        )


def test_scalar_result_is_frozen_and_validates_semantic_literals() -> None:
    result = _metric_row()

    with pytest.raises(FrozenInstanceError):
        result.peak_strehl = 0.5  # type: ignore[misc]
    with pytest.raises(ScienceMetricsError, match="flux_semantics"):
        replace(result, flux_semantics="surface_brightness")  # type: ignore[arg-type]
    with pytest.raises(ScienceMetricsError, match="ee50_rad"):
        replace(result, ee50_rad=result.ee80_rad + 1.0)
    with pytest.raises(ScienceMetricsError, match="fwhm_arcsec"):
        replace(result, fwhm_arcsec=999.0)
    with pytest.raises(ScienceMetricsError, match="fwhm_lambda_over_d"):
        replace(result, fwhm_lambda_over_d=999.0)
    with pytest.raises(ScienceMetricsError, match="marechal_abs_difference"):
        replace(result, marechal_abs_difference=0.5)


def test_band_average_is_normalized_scalar_only_summary() -> None:
    short = _metric_row(wavelength_m=1.0e-6)
    long = replace(
        _metric_row(wavelength_m=2.0e-6),
        peak_strehl=0.70,
        marechal_strehl=0.75,
        marechal_abs_difference=0.05,
        halo_fraction=0.20,
    )

    result = band_average_scalar_metrics((short, long), (1.0, 3.0))

    assert result.aggregation == "weighted_scalar_average"
    assert result.wavelength_m == pytest.approx(1.75e-6)
    assert result.peak_strehl == pytest.approx(0.75)
    assert result.marechal_abs_difference == pytest.approx(0.0425)
    assert result.halo_fraction == pytest.approx(0.18)
    assert result.fwhm_lambda_over_d == pytest.approx(1.0)
    assert result.fwhm_rad == pytest.approx(
        0.25 * short.fwhm_rad + 0.75 * long.fwhm_rad
    )


@pytest.mark.parametrize(
    ("rows", "weights", "message"),
    (
        ((_metric_row(),), (0.0,), "positive total"),
        ((_metric_row(),), (np.nan,), "finite and non-negative"),
        (
            (
                _metric_row(),
                replace(
                    _metric_row(),
                    telescope_diameter_m=3.0,
                    fwhm_lambda_over_d=1.5,
                    ee50_lambda_over_d=0.9,
                    ee80_lambda_over_d=2.25,
                    halo_inner_radius_rad=1.0e-6,
                ),
            ),
            (1.0, 1.0),
            "one telescope_diameter_m",
        ),
        (
            (
                _metric_row(),
                replace(
                    _metric_row(),
                    halo_inner_lambda_over_d=4.0,
                    halo_inner_radius_rad=2.0e-6,
                ),
            ),
            (1.0, 1.0),
            "one halo_inner_lambda_over_d",
        ),
        (
            (
                _metric_row(),
                replace(_metric_row(), aggregation="weighted_scalar_average"),
            ),
            (1.0, 1.0),
            "monochromatic scalar inputs",
        ),
    ),
)
def test_band_average_rejects_invalid_or_incompatible_inputs(
    rows: tuple[PsfScalarMetrics, ...],
    weights: tuple[float, ...],
    message: str,
) -> None:
    with pytest.raises(ScienceMetricsError, match=message):
        band_average_scalar_metrics(rows, weights)


def test_band_average_rejects_mixed_semantics_even_if_instance_is_tampered() -> None:
    valid = _metric_row()
    tampered = _metric_row(wavelength_m=1.1e-6)
    object.__setattr__(tampered, "fwhm_semantics", "pixel_flux")

    with pytest.raises(ScienceMetricsError, match="mixed FWHM semantics"):
        band_average_scalar_metrics((valid, tampered), (1.0, 1.0))


def test_unit_helpers_reject_nonphysical_scales() -> None:
    assert lambda_over_d_rad(1.65e-6, 2.0) == pytest.approx(0.825e-6)
    assert radians_to_lambda_over_d(1.65e-6, 1.65e-6, 2.0) == pytest.approx(2.0)
    assert radians_to_arcsec(1.0) == pytest.approx(206264.80624709636)
    with pytest.raises(ScienceMetricsError, match="wavelength_m must be positive"):
        lambda_over_d_rad(0.0, 2.0)
    with pytest.raises(ScienceMetricsError, match="angle_rad must be finite"):
        radians_to_arcsec(np.inf)
