"""Numerical compatibility checks for the frozen science facades."""

from __future__ import annotations

from typing import Any, Iterator

import numpy as np
import pytest

from shwfs_ao.legacy.ao_diagnostics import science_psf_metrics_from_opd
from shwfs_ao.legacy.psf_tools import compute_psf_from_phase
from shwfs_ao.science.metrics import (
    _cached_legacy_quicksort_order,
    _encircled_energy_radius_from_discrete_flux,
    _legacy_quicksort_order,
)


@pytest.fixture
def empty_legacy_order_cache() -> Iterator[None]:
    _cached_legacy_quicksort_order.cache_clear()
    yield
    _cached_legacy_quicksort_order.cache_clear()


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


def _per_call_object_quicksort_radius(
    flux: np.ndarray,
    radius: np.ndarray,
    fraction: float,
) -> float:
    """Historical estimator: object quicksort of the given radii on every call."""
    order = np.argsort(radius.astype(object), kind="quicksort")
    sorted_radius = radius[order]
    cumulative = np.cumsum(flux.ravel()[order])
    cumulative /= cumulative[-1]
    index = int(np.searchsorted(cumulative, fraction, side="left"))
    c0 = float(cumulative[index - 1])
    c1 = float(cumulative[index])
    r0 = float(sorted_radius[index - 1])
    r1 = float(sorted_radius[index])
    return r1 if c1 == c0 else r0 + (fraction - c0) / (c1 - c0) * (r1 - r0)


def _one_ulp_high_hypot(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """A libm-style hypot that is one ULP high whenever ``|x| > |y|``.

    Mirror offsets such as (4, 3) and (3, 4) then stop comparing equal, the
    tie-class split a non-correctly-rounded platform hypot can produce.
    """
    exact = np.sqrt(np.square(x) + np.square(y))
    return np.where(np.abs(x) > np.abs(y), np.nextafter(exact, np.inf), exact)


@pytest.mark.parametrize("spacing", [0.25, 1.0, 2.0])
def test_legacy_encircled_energy_is_independent_of_platform_hypot(
    monkeypatch: pytest.MonkeyPatch,
    empty_legacy_order_cache: None,
    spacing: float,
) -> None:
    flux = np.arange(1.0, 65.0).reshape(8, 8)
    axis = spacing * (np.arange(8, dtype=float) - 4.0)
    offsets = np.arange(8, dtype=float) - 4.0
    y_grid, x_grid = np.meshgrid(offsets, offsets, indexing="ij")
    fractions = (0.17, 0.5, 0.53, 0.8, 0.93)

    def legacy() -> list[float]:
        return [
            _encircled_energy_radius_from_discrete_flux(
                flux, axis, axis, fraction,
                center_angle_rad=(0.0, 0.0), sort_kind="legacy_quicksort",
            )
            for fraction in fractions
        ]

    expected = legacy()
    exact_radius = (np.sqrt(x_grid * x_grid + y_grid * y_grid) * spacing).ravel()
    split_radius = (_one_ulp_high_hypot(x_grid, y_grid) * spacing).ravel()
    assert expected == [
        _per_call_object_quicksort_radius(flux, exact_radius, fraction)
        for fraction in fractions
    ]
    # The perturbed radii change every one of these legacy values when they
    # are sorted and interpolated directly, as the a66db3d hypot path did.
    for fraction, value in zip(fractions, expected):
        assert _per_call_object_quicksort_radius(flux, split_radius, fraction) != value

    _cached_legacy_quicksort_order.cache_clear()
    monkeypatch.setattr(np, "hypot", _one_ulp_high_hypot)
    assert legacy() == expected


@pytest.mark.parametrize(
    ("shape", "spacing", "center_px"),
    [
        ((16, 16), 1.0, (8.0, 8.0)),
        ((17, 23), 0.37, (15.0, 3.0)),
        ((31, 24), 3.1e-7, (12.4, 9.5)),
        ((32, 32), 2.5, (0.0, 31.0)),
        ((29, 29), 4.7e-6, (14.5, 13.49)),
        ((96, 96), 7.3e-8, (47.0, 50.6)),
    ],
)
def test_cached_legacy_order_matches_a_per_call_object_quicksort(
    empty_legacy_order_cache: None,
    shape: tuple[int, int],
    spacing: float,
    center_px: tuple[float, float],
) -> None:
    rows, columns = shape
    x_axis = spacing * (np.arange(columns, dtype=float) - columns // 2)
    y_axis = spacing * (np.arange(rows, dtype=float) - rows // 2)
    center_x = float(x_axis[0] + center_px[0] * spacing)
    center_y = float(y_axis[0] + center_px[1] * spacing)
    x_spacing = float(np.median(np.diff(x_axis)))
    y_spacing = float(np.median(np.diff(y_axis)))
    x_offsets = np.rint((x_axis - center_x) / x_spacing)
    y_offsets = np.rint((y_axis - center_y) / y_spacing)
    y_grid, x_grid = np.meshgrid(y_offsets, x_offsets, indexing="ij")
    radius = (np.sqrt(x_grid * x_grid + y_grid * y_grid) * x_spacing).ravel()

    cached = _legacy_quicksort_order(x_offsets, y_offsets)

    assert np.array_equal(cached, np.argsort(radius.astype(object), kind="quicksort"))
    assert not cached.flags.writeable
    flux = np.random.default_rng(rows * columns).random(shape)
    for fraction in (0.1, 0.5, 0.8, 0.95):
        assert _encircled_energy_radius_from_discrete_flux(
            flux, x_axis, y_axis, fraction,
            center_angle_rad=(center_x, center_y), sort_kind="legacy_quicksort",
        ) == _per_call_object_quicksort_radius(flux, radius, fraction)


def test_legacy_object_quicksort_runs_once_per_offset_grid(
    monkeypatch: pytest.MonkeyPatch,
    empty_legacy_order_cache: None,
) -> None:
    object_sorts: list[tuple[int, ...]] = []
    numpy_argsort = np.argsort

    def counting_argsort(values: Any, *args: Any, **kwargs: Any) -> np.ndarray:
        if np.asarray(values).dtype == object:
            object_sorts.append(np.shape(values))
        return numpy_argsort(values, *args, **kwargs)

    monkeypatch.setattr(np, "argsort", counting_argsort)
    rng = np.random.default_rng(7)
    size = 40
    # Same integer offsets at three angular spacings, two fractions each.
    for spacing in (1.0, 0.37, 2.9e-7):
        axis = spacing * (np.arange(size, dtype=float) - size // 2)
        for fraction in (0.5, 0.8):
            _encircled_energy_radius_from_discrete_flux(
                rng.random((size, size)), axis, axis, fraction,
                center_angle_rad=(0.0, 0.0), sort_kind="legacy_quicksort",
            )
    assert object_sorts == [(size * size,)]
    info = _cached_legacy_quicksort_order.cache_info()
    assert (info.misses, info.hits) == (1, 5)

    # A different peak pixel is a different offset grid and sorts once more.
    _encircled_energy_radius_from_discrete_flux(
        rng.random((size, size)), axis, axis, 0.5,
        center_angle_rad=(float(axis[3]), float(axis[5])), sort_kind="legacy_quicksort",
    )
    assert len(object_sorts) == 2
