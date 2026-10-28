"""Small numerical regressions for the supplemental TIPTOP notebook adapter.

The notebook itself executes the all-direction P3/PSF convergence checks. These
checks independently protect infinite fitting-tail power, smooth FWHM and crop
normalization without requiring a full MCAO model evaluation in ordinary tests.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import numpy as np
import pytest
from scipy.integrate import quad
from scipy.special import gamma, j0, kv

_PATH = Path(__file__).resolve().parents[2] / "notebooks/studies/tiptop_support.py"
_SPEC = importlib.util.spec_from_file_location("tiptop_notebook_support", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
support = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = support
_SPEC.loader.exec_module(support)


class _Atmosphere:
    r0 = 0.4836042123575544
    L0 = 25.0
    coefficient = (24 * gamma(6 / 5) / 5) ** (5 / 6) * gamma(11 / 6) ** 2 / (2 * np.pi ** (11 / 3))

    def spectrum(self, frequency):
        return self.coefficient * self.r0 ** (-5 / 3) * (frequency**2 + self.L0**-2) ** (-11 / 6)

    def structureFunction(self, separation):
        r = np.asarray(separation)
        c = (24 * gamma(6 / 5) / 5) ** (5 / 6)
        var = c * gamma(11 / 6) * gamma(5 / 6) / (2 * np.pi ** (8 / 3)) * (self.L0 / self.r0) ** (5 / 3)
        covariance = np.full_like(r, var)
        nonzero = r != 0
        u = 2 * np.pi * r[nonzero] / self.L0
        covariance[nonzero] = c * gamma(11 / 6) / (2 ** (5 / 6) * np.pi ** (8 / 3)) * (self.L0 / self.r0) ** (5 / 3) * u ** (5 / 6) * kv(5 / 6, u)
        return 2 * (var - covariance)


def test_fitting_tail_matches_independent_infinite_integral():
    atmosphere = _Atmosphere()
    cutoff = 1 / (2 * 0.22)
    integrated, _ = quad(lambda f: 2 * np.pi * f * atmosphere.spectrum(f), cutoff, np.inf, epsabs=1e-11)
    analytic = support.fitting_variance(atmosphere, cutoff)
    assert analytic == pytest.approx(integrated, rel=2e-10)
    rms_nm = np.sqrt(analytic) * 1650 / (2 * np.pi)
    assert rms_nm == pytest.approx(71.3003482559, abs=1e-8)
    # The original finite-grid 47.9 nm must never pass as complete fitting power.
    assert rms_nm > 1.4 * 47.8954760989


def test_fitting_structure_function_converges_without_origin_discontinuity():
    atmosphere = _Atmosphere()
    rho = np.linspace(0, 8, 121)
    coarse = support.fitting_structure_function(atmosphere, 1 / 0.44, rho, nodes=256)
    fine = support.fitting_structure_function(atmosphere, 1 / 0.44, rho, nodes=512)
    assert fine[0] == 0
    assert np.all(fine >= 0)
    np.testing.assert_allclose(coarse, fine, atol=1e-10, rtol=1e-9)
    # Numerical integration directly above the cutoff is a different route.
    reference, _ = quad(lambda f: 4 * np.pi * f * atmosphere.spectrum(f)
                        * (1 - j0(2 * np.pi * f * 0.5)),
                        1 / 0.44, 1000, epsabs=1e-8, limit=600)
    # Beyond1000/m the remaining non-oscillating tail is analytic; its
    # oscillatory covariance is below the tolerance at this separation.
    reference += 2 * support.fitting_variance(atmosphere, 1000)
    actual = support.fitting_structure_function(atmosphere, 1 / 0.44, np.array([0.5]))[0]
    assert actual == pytest.approx(reference, abs=2e-8)


def test_contour_fwhm_resolves_subpixel_broadening():
    y, x = np.indices((61, 61))
    radius2 = (x - 30) ** 2 + (y - 30) ** 2
    sigmas = np.array([4.0, 4.01, 4.02])
    widths = [support.fwhm_contour(np.exp(-radius2 / (2 * sigma**2)), 1) for sigma in sigmas]
    assert np.all(np.diff(widths) > 0.01)
    np.testing.assert_allclose(widths, 2 * np.sqrt(2 * np.log(2)) * sigmas, rtol=0.005)
    # Pixel-area counting cannot distinguish this broadening.
    counts = [np.count_nonzero(np.exp(-radius2 / (2 * s**2)) >= 0.5) for s in sigmas]
    assert len(set(counts)) == 1


def test_crop_preserves_aperture_energy_without_renormalizing():
    y, x = np.indices((101, 101))
    image = np.exp(-((x - 50)**2 + (y - 50)**2) / (2 * 12**2))
    image /= image.sum()
    crop = support.centered_crop(image, 41)
    assert crop.sum() < 0.9
    assert support.encircled_energy_at(crop, 1, 8) == pytest.approx(
        support.encircled_energy_at(image, 1, 8), abs=1e-14)
    with pytest.raises(ValueError, match="Crop"):
        support.centered_crop(image, 200)


def test_generated_pupil_diffraction_matches_independent_annular_airy():
    """Protect P3's inclusive pupil spacing and the unclipped OTF support."""
    pytest.importorskip("mastsel")
    from types import SimpleNamespace
    from scipy.special import j1

    diameter, wavelength, obscuration = 8.0, 1650e-9, 0.14
    coordinates = np.linspace(-diameter / 2, diameter / 2, 128)
    radius = np.hypot(coordinates[:, None], coordinates[None, :])
    pupil = ((radius <= diameter / 2) & (radius >= obscuration * diameter / 2)).astype(float)
    telescope = SimpleNamespace(D=diameter, pupil=pupil, opdMap_on=None)
    ao = SimpleNamespace(
        tel=telescope, atm=_Atmosphere(), dms=SimpleNamespace(AoArea="circle"),
        src=SimpleNamespace(wvl=np.array([wavelength])), my_data_map={},
    )
    df = 5 / (wavelength * support.RAD_TO_MAS)
    cutoff = 1 / 0.44
    fao = SimpleNamespace(
        ao=ao, freq=SimpleNamespace(nOtf=400, PSDstep=df, wvlRef=wavelength,
                                   kcMax_=cutoff, resAO=round(2 * cutoff / df)),
        PSD=np.zeros((400, 400, 1)), fittingPSD=lambda: np.zeros((400, 400)),
        wfeTot=0.0,
    )
    for attribute in support.BUDGET_ATTRIBUTES.values():
        setattr(fao, attribute, 0.0)
    result = support.complete_psfs(fao)
    angle = (np.arange(101) - 50) * 5
    argument = np.pi * np.hypot(angle[:, None], angle[None, :]) / (
        wavelength / diameter * support.RAD_TO_MAS
    )
    safe = np.where(argument == 0, 1, argument)
    airy = (2 * (j1(safe) - obscuration * j1(obscuration * safe))
            / (safe * (1 - obscuration**2)))**2
    airy[argument == 0] = 1
    reference = support.fwhm_contour(airy, 5)
    actual = support.fwhm_contour(result.diffraction, 5)
    # Includes raster-pupil error; D/N instead of D/(N-1) misses by ~0.85%.
    assert actual == pytest.approx(reference, rel=0.002)
    assert np.min(result.diffraction) >= 0
