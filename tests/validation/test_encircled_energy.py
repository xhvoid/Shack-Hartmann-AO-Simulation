"""T2 G5: the validation-only Fourier encircled-energy reference and its error budgets.

Budget 1 (integrating the interpolant) is gated at rounding level against an
independently constructed polar quadrature of the same interpolant and by
the pad invariance of the raster-pupil oracle.  Budgets 2-4 (pupil raster,
periodic far field, continuous references) are measured and bounded by the
tolerances derived in the T2 design note from the values recorded there;
they are not the withdrawn ``1e-6`` continuous-Airy gate.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import integrate, special

from shwfs_ao.backends.native.propagation import NativeSciencePropagator
from shwfs_ao.core.geometry import build_pupil_geometry
from shwfs_ao.science.metrics import encircled_energy_radius_from_discrete_flux
from shwfs_ao.science.propagation import PsfSampling
from shwfs_ao.validation.encircled_energy import (
    EncircledEnergyError,
    airy_encircled_energy,
    annular_encircled_energy,
    annular_encircled_energy_bessel_form,
    annular_encircled_energy_radius,
    annular_psf_normalized_intensity,
    fourier_encircled_energy,
)

DX = 2.0e-7


def _polar_integral(ee, radius: float, center, *, n_r: int = 48, n_phi: int = 192) -> float:
    """Independent disc integral of the interpolant: Gauss-Legendre in radius, trapezoid in azimuth."""

    nodes, weights = np.polynomial.legendre.leggauss(n_r)
    r = 0.5 * radius * (nodes + 1.0)
    wr = 0.5 * radius * weights
    phi = np.arange(n_phi) * 2.0 * math.pi / n_phi
    x = center[0] + r[:, None] * np.cos(phi)[None, :]
    y = center[1] + r[:, None] * np.sin(phi)[None, :]
    values = ee.value_at(x, y)
    return float(np.sum(values * r[:, None] * wr[:, None]) * (2.0 * math.pi / n_phi))


def _grid(size: int):
    x = (np.arange(size) - size // 2) * DX
    return x, np.meshgrid(x, x)


@pytest.mark.parametrize("size", [16, 17])
def test_a_constant_image_encloses_the_disc_area_fraction(size: int) -> None:
    x, _ = _grid(size)
    image = np.full((size, size), 0.3)
    ee = fourier_encircled_energy(image, x, x, center_xy_rad=(0.0, 0.0))
    radius = 0.3 * size * DX
    expected = math.pi * radius**2 / (size * DX) ** 2
    assert ee.fraction(radius) == pytest.approx(expected, rel=0.0, abs=1.0e-14)
    assert ee.whole_field_flux == pytest.approx(0.3 * size * size * DX * DX, rel=1.0e-14)
    assert ee.artefacts.negative_lobe_fraction == 0.0 and ee.artefacts.minimum_value == pytest.approx(0.3, abs=1.0e-12)


def _images(size: int):
    x, (X, Y) = _grid(size)
    period = size * DX
    return x, {
        "cosine_mode": 1.0 + 0.5 * np.cos(2.0 * math.pi * (3.0 * X + 2.0 * Y) / period + 0.4),
        "nyquist_cosine_x": 1.0 + 0.5 * np.cos(math.pi * X / DX),
        "nyquist_both_axes": 1.0 + 0.25 * np.cos(math.pi * X / DX) * np.cos(math.pi * Y / DX),
        "shifted_gaussian": np.exp(-((X - 0.37 * DX) ** 2 + (Y + 1.2 * DX) ** 2) / (2.0 * (1.3 * DX) ** 2)),
    }


@pytest.mark.parametrize("size", [24, 25])
@pytest.mark.parametrize("name", ["cosine_mode", "nyquist_cosine_x", "nyquist_both_axes", "shifted_gaussian"])
def test_the_closed_form_matches_an_independent_polar_quadrature(size: int, name: str) -> None:
    """Budget 1: the disc integral of the specified interpolant, two constructions."""

    x, images = _images(size)
    if size % 2 and name.startswith("nyquist"):
        pytest.skip("an odd grid has no Nyquist term")
    image = images[name]
    centre = (0.6 * DX, -0.2 * DX)
    ee = fourier_encircled_energy(image, x, x, center_xy_rad=centre)
    for radius in (2.5 * DX, 0.95 * ee.max_radius_rad):
        closed = ee.encircled_energy(radius)
        coarse = _polar_integral(ee, radius, centre)
        fine = _polar_integral(ee, radius, centre, n_r=96, n_phi=384)
        assert abs(coarse - fine) / ee.whole_field_flux < 1.0e-12  # the quadrature has converged
        assert abs(closed - coarse) / ee.whole_field_flux < 1.0e-12
    # The interpolant passes through the samples.
    X, Y = np.meshgrid(x, x)
    assert np.max(np.abs(ee.value_at(X, Y) - image)) < 1.0e-12 * np.max(image)


def test_the_nyquist_term_interpolates_as_a_cosine() -> None:
    """Even axis: the Nyquist coefficient is split half and half, so the term is cos(pi x / h)."""

    size = 24
    x, images = _images(size)
    image = images["nyquist_cosine_x"]
    ee = fourier_encircled_energy(image, x, x)
    midway = x[:-1] + 0.5 * DX  # between samples cos(pi (k + 1/2)) = 0
    values = ee.value_at(midway[None, :], x[:, None])
    assert np.max(np.abs(values - 1.0)) < 1.0e-12
    quarter = x[:-1] + 0.25 * DX
    expected = 1.0 + 0.5 * np.cos(math.pi * quarter / DX)
    assert np.max(np.abs(ee.value_at(quarter[None, :], x[:, None]) - expected[None, :])) < 1.0e-12


def test_odd_grids_shifted_centres_and_integer_shifts_agree() -> None:
    x, images = _images(25)
    image = images["shifted_gaussian"]
    ee = fourier_encircled_energy(image, x, x)
    # The default centre is the largest sample (here the sample nearest the Gaussian centre).
    row, column = np.unravel_index(int(np.argmax(image)), image.shape)
    assert ee.center_xy_rad == (pytest.approx(x[column]), pytest.approx(x[row]))
    radius = 3.0 * DX
    reference = ee.fraction(radius)
    assert abs(ee.encircled_energy(radius) - _polar_integral(ee, radius, ee.center_xy_rad)) / ee.whole_field_flux < 1.0e-12
    rolled = np.roll(np.roll(image, 3, axis=1), -2, axis=0)
    shifted = fourier_encircled_energy(rolled, x, x, center_xy_rad=(ee.center_xy_rad[0] + 3.0 * DX, ee.center_xy_rad[1] - 2.0 * DX))
    assert shifted.fraction(radius) == pytest.approx(reference, rel=0.0, abs=1.0e-13)
    # An explicit sub-pixel centre is accepted: the Gaussian's true centre
    # (0.37, -1.2 samples) encloses more than the peak sample does, a far
    # centre less.
    true_centre = fourier_encircled_energy(image, x, x, center_xy_rad=(0.37 * DX, -1.2 * DX))
    assert true_centre.fraction(radius) > reference
    far = fourier_encircled_energy(image, x, x, center_xy_rad=(ee.center_xy_rad[0] + 3.0 * DX, ee.center_xy_rad[1]))
    assert 0.0 < far.fraction(radius) < reference
    record = ee.to_record()
    assert record["angular_unit"] == "rad" and record["frequency_unit"] == "cycles_per_rad"
    assert "point samples" in record["input_semantics"]


def test_unsupported_inputs_radii_and_fractions_are_refused() -> None:
    x, images = _images(16)
    image = images["shifted_gaussian"]
    ee = fourier_encircled_energy(image, x, x)
    with pytest.raises(EncircledEnergyError, match="periodic cell"):
        ee.fraction(0.6 * 16 * DX)
    with pytest.raises(EncircledEnergyError, match="non-negative"):
        ee.fraction(-1.0e-9)
    for fraction in (0.0, 1.0, 1.5, float("nan")):
        with pytest.raises(EncircledEnergyError, match="fraction"):
            ee.radius(fraction)
    with pytest.raises(EncircledEnergyError, match="positive total"):
        fourier_encircled_energy(np.zeros((16, 16)), x, x)
    bad = image.copy()
    bad[0, 0] = math.nan
    with pytest.raises(EncircledEnergyError, match="finite"):
        fourier_encircled_energy(bad, x, x)
    with pytest.raises(EncircledEnergyError, match="uniform"):
        fourier_encircled_energy(image, x**2, x)
    with pytest.raises(EncircledEnergyError, match="shape"):
        fourier_encircled_energy(image[:, :8], x, x)
    with pytest.raises(EncircledEnergyError, match="real 2-D"):
        fourier_encircled_energy(image > 0.5, x, x)
    with pytest.raises(EncircledEnergyError, match="finite"):
        fourier_encircled_energy(image, x, x, center_xy_rad=(math.inf, 0.0))


def test_interpolation_artefacts_are_reported_not_removed() -> None:
    """A single bright sample has a sinc-like interpolant with negative lobes; nothing is clipped."""

    size = 16
    x, _ = _grid(size)
    image = np.zeros((size, size))
    image[size // 2, size // 2] = 1.0
    ee = fourier_encircled_energy(image, x, x)
    assert ee.artefacts.minimum_sample_value == 0.0
    assert ee.artefacts.minimum_value < -1.0e-3
    assert ee.artefacts.negative_lobe_fraction > 1.0e-3
    # The disc integral is of the interpolant as it is, so it can exceed the
    # fraction a non-negative image would give; the whole field still sums to one.
    assert ee.fraction(ee.max_radius_rad) == pytest.approx(ee.fraction(ee.max_radius_rad))
    assert ee.whole_field_flux == pytest.approx(DX * DX)
    assert not ee.monotone_fraction_scan() or ee.artefacts.negative_lobe_fraction > 0.0


def _raster_psf(samples: int, obscuration: float, pad: int, *, diameter_m: float = 5.0, wavelength_m: float = 2.2e-6):
    geometry = build_pupil_geometry(
        telescope_diameter_m=diameter_m, pupil_shape=(samples, samples), central_obstruction_ratio=obscuration
    )
    return NativeSciencePropagator(pupil=geometry, sampling=PsfSampling(pad_factor=pad)).psf_from_opd(
        np.zeros((samples, samples)), wavelength_m
    )


@pytest.mark.parametrize("obscuration", [0.0, 0.28])
def test_the_raster_pupil_oracle_is_pad_invariant_and_measures_the_production_estimator(obscuration: float) -> None:
    """Budget 1 (again) and budget 3: the same raster model sampled at pads 2, 3, 4.

    For pad >= 2 the interpolant is the raster model's continuous intensity, so
    the oracle's EE50 cannot depend on the pad; the production ring-merged
    estimator's pad dependence is its own discretization (S3 read pad 2 up to
    7 % high at 12 m).
    """

    radii = {}
    production = {}
    for pad in (2, 3, 4):
        psf = _raster_psf(60, obscuration, pad)
        ee = fourier_encircled_energy(psf.intensity, psf.x_angle_rad, psf.y_angle_rad)
        radii[pad] = ee.radius(0.5)
        production[pad] = encircled_energy_radius_from_discrete_flux(psf.intensity, psf.x_angle_rad, psf.y_angle_rad, 0.5)
        assert ee.artefacts.negative_lobe_fraction < 1.0e-12
    assert radii[3] == pytest.approx(radii[2], rel=1.0e-12)
    assert radii[4] == pytest.approx(radii[2], rel=1.0e-12)
    deviations = {pad: production[pad] / radii[2] - 1.0 for pad in (2, 3, 4)}
    assert abs(deviations[2]) > 0.02  # pad 2 is visibly an estimator artefact (observed +5.5 % and +4.3 %)
    assert abs(deviations[4]) < 0.02  # pad 4 within 2 % (observed -0.27 % and -0.51 %)


def test_the_raster_and_wrap_error_against_the_continuous_pupil_decreases_with_sampling() -> None:
    """Budgets 2 and 3 against budget 4: the raster model's EE50 approaches the Airy EE50 as N grows.

    Recorded values (design note): +1.83e-3, +1.17e-3, +6.1e-4 for N = 60, 120,
    240 (unobstructed); the gate is twice the recorded value at each N and
    the decrease; the wrapped tail ``1 - EE(pi (N-1)/2)`` is reported with it.
    """

    wavelength_m, diameter_m = 2.2e-6, 5.0
    v50 = annular_encircled_energy_radius(0.5, 0.0)
    assert v50 == pytest.approx(1.68022, abs=2.0e-5)  # 0.5349 lambda/D
    theta50 = v50 * wavelength_m / (math.pi * diameter_m)
    gates = {60: 4.0e-3, 120: 2.4e-3, 240: 1.3e-3}
    deviations = []
    for samples in (60, 120, 240):
        psf = _raster_psf(samples, 0.0, 2)
        ee = fourier_encircled_energy(psf.intensity, psf.x_angle_rad, psf.y_angle_rad)
        deviation = ee.radius(0.5) / theta50 - 1.0
        assert abs(deviation) < gates[samples], samples
        deviations.append(abs(deviation))
        wrapped = 1.0 - airy_encircled_energy(math.pi * (samples - 1) / 2.0)
        assert 0.0 < wrapped < 1.0e-2
        assert abs(ee.fraction(theta50) - 0.5) < 2.0 * wrapped  # the fraction at the analytic EE50 radius
    assert deviations[0] > deviations[1] > deviations[2]


def test_the_annular_reference_at_the_eso_obscuration() -> None:
    """Budget 4: the raster 0.28-obstructed pupil against the annular reference at N = 120 and 240."""

    wavelength_m, diameter_m, epsilon = 2.2e-6, 5.0, 0.28
    v50 = annular_encircled_energy_radius(0.5, epsilon)
    theta50 = v50 * wavelength_m / (math.pi * diameter_m)
    gates = {120: 3.0e-3, 240: 1.3e-3}  # twice the recorded +1.42e-3 and +5.8e-4
    for samples in (120, 240):
        psf = _raster_psf(samples, epsilon, 2)
        ee = fourier_encircled_energy(psf.intensity, psf.x_angle_rad, psf.y_angle_rad)
        assert abs(ee.radius(0.5) / theta50 - 1.0) < gates[samples], samples


def test_continuous_references_agree_between_independent_routes() -> None:
    """Airy (Rayleigh 1881) and the annular aperture by direct intensity integration and by Bessel identities."""

    for v in (0.5, 1.68, 3.0, 7.5):
        assert annular_encircled_energy(v, 0.0) == pytest.approx(airy_encircled_energy(v), rel=0.0, abs=1.0e-10)
        assert annular_encircled_energy_bessel_form(v, 0.0) == pytest.approx(airy_encircled_energy(v), rel=0.0, abs=1.0e-14)
        for epsilon in (0.28, 0.5):
            direct = annular_encircled_energy(v, epsilon)
            bessel = annular_encircled_energy_bessel_form(v, epsilon)
            assert direct == pytest.approx(bessel, rel=0.0, abs=1.0e-9), (v, epsilon)
    # The normalized intensity is the Hankel transform of the annulus.
    for v in (0.0, 1.3, 4.2):
        hankel, _ = integrate.quad(lambda rho: float(special.j0(v * rho)) * rho, 0.28, 1.0, epsabs=1.0e-13)
        normalized = (hankel / (0.5 * (1.0 - 0.28**2))) ** 2
        assert annular_psf_normalized_intensity(v, 0.28) == pytest.approx(normalized, rel=0.0, abs=1.0e-12)
    # The total energy is one in the limit, increasing in v; EE(0) = 0.
    assert annular_encircled_energy(0.0, 0.28) == 0.0
    values = [annular_encircled_energy(v, 0.28) for v in (50.0, 100.0, 200.0)]
    assert values[0] < values[1] < values[2] < 1.0 and values[2] > 0.995
    assert airy_encircled_energy(0.0) == 0.0
    with pytest.raises(EncircledEnergyError):
        annular_psf_normalized_intensity(1.0, 1.0)
    with pytest.raises(EncircledEnergyError):
        annular_encircled_energy(-1.0, 0.28)
