"""DET-02: source and sky photometry with QE applied exactly once.

Oracles are independent closed forms.  For a spectrum flat in f_nu, constant
throughput T and QE q over [a, b],

    N_e = A t f_nu T q ln(b / a) / h,

because ``f_lambda lambda / (h c) = f_nu / (h lambda)``.  Gauss--Legendre
quadrature integrates ``1/lambda`` spectrally fast; 12 nodes reach 1e-14 on
the R3 band, so the fixture tolerance rtol 1e-12 is a quadrature-convergence
margin, not a fit.  Wavelength-dependent fixtures use scipy.integrate.quad
(its own error estimate is below 1e-12 relative) and a declared quadrature
tolerance of 1e-9 at 12 nodes.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.integrate import quad

from shwfs_ao.core.spectral import (
    gauss_legendre_quadrature,
    midpoint_quadrature,
    monochromatic_quadrature,
)
from shwfs_ao.detector.photometry import (
    AB_ZERO_POINT_FNU_W_M2_HZ,
    ARCSEC_RAD,
    PLANCK_J_S,
    SPEED_OF_LIGHT_M_S,
    ab_magnitude_to_fnu,
    flat_fnu_flambda,
    scale_incident_photons,
    sky_electrons_per_pixel,
    source_electron_budget,
)


BAND = (6.0e-7, 9.0e-7)


def _flat_budget(magnitude=10.0, area=0.25, exposure=2.0e-3, throughput=0.5, qe=0.8, nodes=12):
    quadrature = gauss_legendre_quadrature(*BAND, nodes)
    return source_electron_budget(
        quadrature,
        flambda_w_m2_m=flat_fnu_flambda(ab_magnitude_to_fnu(magnitude), quadrature.wavelength_m),
        throughput=throughput,
        quantum_efficiency=qe,
        area_m2=area,
        exposure_s=exposure,
    )


def test_ab_zero_point_follows_oke_gunn() -> None:
    # m_AB = -2.5 log10(f_nu / erg s^-1 cm^-2 Hz^-1) - 48.60: 3630.78 Jy.
    assert math.isclose(AB_ZERO_POINT_FNU_W_M2_HZ / 1.0e-26, 3630.780547701003, rel_tol=1e-12)
    assert math.isclose(ab_magnitude_to_fnu(0.0) / 1.0e-26, 3631.0, rel_tol=1e-4)


def test_flat_fnu_top_hat_matches_the_analytic_integral() -> None:
    budget = _flat_budget()
    fnu = ab_magnitude_to_fnu(10.0)
    log_ratio = math.log(BAND[1] / BAND[0])
    detected = 0.25 * 2.0e-3 * fnu * 0.5 * 0.8 * log_ratio / PLANCK_J_S
    incident = detected / 0.8
    assert math.isclose(budget.detected_e, detected, rel_tol=1e-12)
    assert math.isclose(budget.incident_photons, incident, rel_tol=1e-12)


def test_budgets_scale_as_declared() -> None:
    base = _flat_budget()
    assert math.isclose(_flat_budget(magnitude=12.5).detected_e, base.detected_e * 10 ** (-0.4 * 2.5), rel_tol=1e-12)
    for keyword, factor in (("area", 3.0), ("exposure", 0.5), ("throughput", 0.6)):
        reference = {"area": 0.25, "exposure": 2.0e-3, "throughput": 0.5}[keyword]
        scaled = _flat_budget(**{keyword: reference * factor})
        assert math.isclose(scaled.detected_e, base.detected_e * factor, rel_tol=1e-12)
        assert math.isclose(scaled.incident_photons, base.incident_photons * factor, rel_tol=1e-12)
    half_qe = _flat_budget(qe=0.4)
    assert math.isclose(half_qe.detected_e, base.detected_e / 2.0, rel_tol=1e-12)
    # QE moves only the detected electrons, never the incident photons.
    assert half_qe.incident_photons == base.incident_photons


def test_wavelength_dependent_qe_matches_an_independent_integral() -> None:
    def qe(wavelength: np.ndarray) -> np.ndarray:
        return 0.9 - 0.5 * (np.asarray(wavelength) - BAND[0]) / (BAND[1] - BAND[0])

    def throughput(wavelength: np.ndarray) -> np.ndarray:
        return 0.3 + 0.2 * np.sin(np.asarray(wavelength) * 1.0e7)

    fnu = ab_magnitude_to_fnu(9.0)
    quadrature = gauss_legendre_quadrature(*BAND, 12)
    budget = source_electron_budget(
        quadrature,
        flambda_w_m2_m=flat_fnu_flambda(fnu, quadrature.wavelength_m),
        throughput=throughput(quadrature.wavelength_m),
        quantum_efficiency=qe(quadrature.wavelength_m),
        area_m2=0.16,
        exposure_s=1.0e-3,
    )

    def integrand(wavelength: float) -> float:
        return float(fnu * throughput(wavelength) * qe(wavelength) / (PLANCK_J_S * wavelength))

    expected, _ = quad(integrand, *BAND, epsabs=0.0, epsrel=1e-13)
    expected *= 0.16 * 1.0e-3
    assert math.isclose(budget.detected_e, expected, rel_tol=1e-9)
    # Spectral weights: each node's detected contribution, normalized.
    weights = quadrature.weight_m * throughput(quadrature.wavelength_m) * qe(quadrature.wavelength_m) / quadrature.wavelength_m
    assert np.allclose(budget.spectral_weights, weights / weights.sum(), rtol=1e-12, atol=0)
    assert math.isclose(float(np.sum(budget.spectral_weights)), 1.0, rel_tol=1e-14)


def test_narrow_band_limit_reduces_to_the_monochromatic_formula() -> None:
    centre, width = 7.0e-7, 1.0e-10
    fnu = ab_magnitude_to_fnu(8.0)
    flambda = float(flat_fnu_flambda(fnu, np.array([centre]))[0])
    mono = source_electron_budget(
        monochromatic_quadrature(centre, width),
        flambda_w_m2_m=np.array([flambda]),
        throughput=0.4,
        quantum_efficiency=0.9,
        area_m2=0.2,
        exposure_s=1.0e-3,
    )
    formula = 0.2 * 1.0e-3 * flambda * 0.4 * 0.9 * centre * width / (PLANCK_J_S * SPEED_OF_LIGHT_M_S)
    assert math.isclose(mono.detected_e, formula, rel_tol=1e-14)
    band = gauss_legendre_quadrature(centre - width / 2, centre + width / 2, 5)
    narrow = source_electron_budget(
        band,
        flambda_w_m2_m=flat_fnu_flambda(fnu, band.wavelength_m),
        throughput=0.4,
        quantum_efficiency=0.9,
        area_m2=0.2,
        exposure_s=1.0e-3,
    )
    assert math.isclose(narrow.detected_e, formula, rel_tol=1e-7)


def test_sky_electrons_scale_with_pixel_solid_angle_and_match_a_hand_calculation() -> None:
    quadrature = gauss_legendre_quadrature(*BAND, 12)
    pixel = 0.15 * ARCSEC_RAD
    sky = sky_electrons_per_pixel(
        quadrature,
        surface_brightness_ab_mag_arcsec2=20.0,
        pixel_solid_angle_sr=pixel**2,
        throughput=0.5,
        quantum_efficiency=0.8,
        area_m2=0.25,
        exposure_s=2.0e-3,
    )
    fnu = AB_ZERO_POINT_FNU_W_M2_HZ * 10 ** (-0.4 * 20.0) * 0.15**2
    hand = 0.25 * 2.0e-3 * fnu * 0.5 * 0.8 * math.log(BAND[1] / BAND[0]) / PLANCK_J_S
    assert math.isclose(sky, hand, rel_tol=1e-12)
    doubled = sky_electrons_per_pixel(
        quadrature,
        surface_brightness_ab_mag_arcsec2=20.0,
        pixel_solid_angle_sr=2.0 * pixel**2,
        throughput=0.5,
        quantum_efficiency=0.8,
        area_m2=0.25,
        exposure_s=2.0e-3,
    )
    assert math.isclose(doubled, 2.0 * sky, rel_tol=1e-14)


def test_direct_incident_photon_budget_applies_qe_once() -> None:
    assert scale_incident_photons(1.0e5, 0.5) == 5.0e4


def test_quadrature_rules_converge_to_the_band_integral() -> None:
    exact = math.log(BAND[1] / BAND[0])
    errors = {}
    for count in (1, 3, 5, 7):
        for rule in (gauss_legendre_quadrature, midpoint_quadrature):
            quadrature = rule(*BAND, count)
            value = quadrature.integrate(1.0 / quadrature.wavelength_m)
            errors[(rule.__name__, count)] = abs(value / exact - 1.0)
    assert errors[("gauss_legendre_quadrature", 7)] < 1e-9
    assert errors[("gauss_legendre_quadrature", 3)] < errors[("gauss_legendre_quadrature", 1)]
    assert errors[("midpoint_quadrature", 7)] < errors[("midpoint_quadrature", 1)]


def test_invalid_photometric_inputs_are_rejected() -> None:
    quadrature = gauss_legendre_quadrature(*BAND, 3)
    with pytest.raises(ValueError):
        source_electron_budget(quadrature, flambda_w_m2_m=np.ones(3), throughput=1.2, quantum_efficiency=0.5, area_m2=1.0, exposure_s=1.0)
    with pytest.raises(ValueError):
        source_electron_budget(quadrature, flambda_w_m2_m=np.ones(2), throughput=0.5, quantum_efficiency=0.5, area_m2=1.0, exposure_s=1.0)
    with pytest.raises(ValueError):
        scale_incident_photons(1.0, 1.5)
