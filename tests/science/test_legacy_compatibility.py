"""Numerical compatibility checks for the frozen science facades."""

from __future__ import annotations

import numpy as np
import pytest

from shwfs_ao.legacy.ao_diagnostics import science_psf_metrics_from_opd
from shwfs_ao.legacy.psf_tools import compute_psf_from_phase
from shwfs_ao.science.metrics import _encircled_energy_radius_from_discrete_flux


def _historical_pixel_metrics(
    psf: np.ndarray,
    *,
    halo_inner_radius_px: float,
) -> tuple[float, float, float, float]:
    peak_y, peak_x = np.unravel_index(int(np.argmax(psf)), psf.shape)
    y, x = np.indices(psf.shape)
    radius = np.sqrt((x - peak_x) ** 2 + (y - peak_y) ** 2)

    radial_bin = np.floor(radius).astype(int)
    counts = np.bincount(radial_bin.ravel())
    sums = np.bincount(radial_bin.ravel(), weights=psf.ravel())
    profile = np.divide(
        sums,
        counts,
        out=np.zeros_like(sums, dtype=float),
        where=counts > 0,
    )
    half = 0.5 * float(profile[0])
    crossing = int(np.flatnonzero(profile <= half)[0])
    x0 = float(crossing - 1)
    x1 = float(crossing)
    y0 = float(profile[crossing - 1])
    y1 = float(profile[crossing])
    radius_half = x1 if y1 == y0 else x0 + (half - y0) * (x1 - x0) / (y1 - y0)

    def encircled(fraction: float) -> float:
        flat_radius = radius.ravel()
        # Freeze the historical scalar quicksort tie order on all CPUs.
        order = np.argsort(flat_radius.astype(object), kind="quicksort")
        sorted_radius = flat_radius[order]
        cumulative = np.cumsum(psf.ravel()[order])
        cumulative /= cumulative[-1]
        index = int(np.searchsorted(cumulative, fraction, side="left"))
        c0 = float(cumulative[index - 1])
        c1 = float(cumulative[index])
        r0 = float(sorted_radius[index - 1])
        r1 = float(sorted_radius[index])
        return r1 if c1 == c0 else r0 + (fraction - c0) * (r1 - r0) / (c1 - c0)

    halo = float(np.sum(psf[radius >= halo_inner_radius_px]) / np.sum(psf))
    return 2.0 * radius_half, encircled(0.50), encircled(0.80), halo


def test_legacy_metric_facade_preserves_historical_pixel_conventions() -> None:
    size = 48
    pad_factor = 3
    wavelength_m = 1.65e-6
    telescope_diameter_m = 2.0
    coordinates = np.linspace(-1.0, 1.0, size)
    x, y = np.meshgrid(coordinates, coordinates)
    pupil = x**2 + y**2 <= 1.0
    opd_nm = np.where(
        pupil,
        83.0 * (x**2 - 0.7 * y**2) + 31.0 * x * y + 19.0 * x,
        np.nan,
    )
    phase_rad = 2.0 * np.pi * opd_nm * 1.0e-9 / wavelength_m
    psf = compute_psf_from_phase(phase_rad, pupil, pad_factor=pad_factor)
    expected = _historical_pixel_metrics(
        psf,
        halo_inner_radius_px=3.0 * pad_factor,
    )

    actual = science_psf_metrics_from_opd(
        opd_nm,
        pupil,
        wavelength_m=wavelength_m,
        telescope_diameter_m=telescope_diameter_m,
        pad_factor=pad_factor,
        halo_inner_lambda_over_d=3.0,
    )

    assert actual.fwhm_px == pytest.approx(expected[0], abs=2.0e-12)
    assert actual.ee50_px == pytest.approx(expected[1], abs=2.0e-12)
    assert actual.ee80_px == pytest.approx(expected[2], abs=2.0e-12)
    assert actual.halo_fraction == pytest.approx(expected[3], abs=2.0e-15)
    assert actual.fwhm_lambda_over_d == pytest.approx(actual.fwhm_px / pad_factor)
    assert actual.ee50_lambda_over_d == pytest.approx(actual.ee50_px / pad_factor)
    assert actual.ee80_lambda_over_d == pytest.approx(actual.ee80_px / pad_factor)


@pytest.mark.parametrize("spacing", [0.25, 1.0, 2.0])
@pytest.mark.parametrize(
    ("fraction", "historical_radius", "stable_radius"),
    [
        (0.17, 1.7236289627606403, 1.9888421630928212),
        (0.53, 3.113594362117866, 3.1622776601683795),
        (0.93, 4.342538627255414, 4.47213595499958),
    ],
)
def test_legacy_encircled_energy_freezes_equal_radius_tie_order(
    spacing: float,
    fraction: float,
    historical_radius: float,
    stable_radius: float,
) -> None:
    """A crossing between rings exposes CPU-dependent quicksort permutations."""
    flux = np.arange(1.0, 65.0).reshape(8, 8)
    axis = spacing * (np.arange(8, dtype=float) - 4.0)
    historical = _encircled_energy_radius_from_discrete_flux(
        flux, axis, axis, fraction,
        center_angle_rad=(0.0, 0.0), sort_kind="legacy_quicksort",
    )
    stable = _encircled_energy_radius_from_discrete_flux(
        flux, axis, axis, fraction,
        center_angle_rad=(0.0, 0.0), sort_kind="stable",
    )
    assert historical == pytest.approx(spacing * historical_radius, rel=2.0e-14)
    assert stable == pytest.approx(spacing * stable_radius, rel=2.0e-14)
