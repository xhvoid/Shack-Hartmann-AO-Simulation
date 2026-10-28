"""DET-03/DET-04: MFT detector-plane sampling, pixel integration, diffusion,
polychromatic sensing.

Oracles:
* the frozen FFT optics (``k = 1`` point sampling, rtol 1e-12 on float64
  normalized intensities: both are the same finite DFT sum, so only roundoff,
  ~1e-15, separates them);
* erf pixel integrals of an analytic Gaussian (the Gauss--Legendre pixel
  quadrature reaches 1e-6 by k = 4; k = 2, 4, 8, 16 are reported);
* the closed-form Dirichlet kernel ``sin^2(pi N u) / sin^2(pi u)`` of a fully
  illuminated square lenslet, integrated per pixel with scipy.integrate.quad;
* the exact Fraunhofer scaling ``I_lambda2(theta) ~ I_lambda1(theta lambda1/lambda2)``.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.integrate import quad

from shwfs_ao.backends.native.shwfs import NativeShackHartmannError, NativeShackHartmannOptics
from shwfs_ao.backends.native.shwfs_batched import BatchedNativeShackHartmannOptics
from shwfs_ao.backends.native.shwfs_mft import (
    MftShackHartmannOptics,
    gauss_legendre_pixel_nodes,
    pixel_response_matrix,
)
from shwfs_ao.wfs.shack_hartmann.compact_geometry import build_compact_shack_hartmann_geometry
from shwfs_ao.wfs.shack_hartmann.geometry import build_shack_hartmann_geometry


def dense(pupil=52, lenslets=5, obstruction=0.0):
    return build_shack_hartmann_geometry(
        telescope_diameter_m=2.0, pupil_shape=(pupil, pupil), n_lenslets_across=lenslets,
        min_fill_fraction=0.35, central_obstruction_ratio=obstruction, spider_width_m=0.0,
    )


def compact(pupil=52, lenslets=5):
    return build_compact_shack_hartmann_geometry(
        telescope_diameter_m=2.0, pupil_shape=(pupil, pupil), n_lenslets_across=lenslets,
        min_fill_fraction=0.35, central_obstruction_ratio=0.0, spider_width_m=0.0,
    )


@pytest.mark.parametrize("block", [15, 21])
@pytest.mark.parametrize("pad", [2, 3])
def test_k1_mft_reproduces_the_frozen_fft_spots(block: int, pad: int) -> None:
    geometry = dense(obstruction=0.2)
    fft = NativeShackHartmannOptics(geometry, 7.0e-7, pad_factor=pad, detector_window_px=block)
    mft = MftShackHartmannOptics(
        geometry, wavelengths_m=(7.0e-7,), spectral_weights=(1.0,),
        pixel_scale_rad=fft.sampling.pixel_scale_rad, block_px=block, oversampling=1,
    ) if block < pad * 11 else None
    if mft is None:
        pytest.skip("block exceeds the far-field period at this pad")
    rng = np.random.default_rng(pad * 100 + block)
    for _ in range(3):
        opd = rng.normal(0.0, 80.0e-9, geometry.pupil_shape)
        expected = fft.spot_intensities(opd)
        actual = mft.spot_intensities(opd)
        for a, b in zip(expected.unit_sum_spots, actual.unit_sum_spots):
            np.testing.assert_allclose(b, a, rtol=1e-12, atol=1e-12 * float(np.max(a)))
        np.testing.assert_allclose(actual.relative_throughput, expected.relative_throughput, rtol=1e-12)


def test_k1_mft_reproduces_the_batched_fft_on_the_compact_geometry() -> None:
    geometry = compact()
    fft = BatchedNativeShackHartmannOptics(geometry, 7.0e-7, pad_factor=3, detector_window_px=25)
    mft = MftShackHartmannOptics(
        geometry, wavelengths_m=(7.0e-7,), spectral_weights=(1.0,),
        pixel_scale_rad=fft.sampling.pixel_scale_rad, block_px=25, oversampling=1, batch_size=4,
    )
    opd = np.random.default_rng(1).normal(0.0, 60.0e-9, geometry.pupil_shape)
    for a, b in zip(fft.spot_intensities(opd).unit_sum_spots, mft.spot_intensities(opd).unit_sum_spots):
        np.testing.assert_allclose(b, a, rtol=1e-12, atol=1e-12 * float(np.max(a)))
    assert mft.measurement_locality == "lenslet_pixels_v1"


def _gaussian_pixels(sigma: float, centre: float, pixels: int) -> np.ndarray:
    edges = np.arange(pixels + 1, dtype=float) - 0.5
    cdf = 0.5 * (1.0 + np.vectorize(math.erf)((edges - centre) / (math.sqrt(2.0) * sigma)))
    return np.diff(cdf)


def test_pixel_integration_matches_erf_integrals_and_converges() -> None:
    pixels, sigma, centre = 15, 0.9, 7.3
    exact = np.outer(_gaussian_pixels(sigma, centre, pixels), _gaussian_pixels(sigma, centre, pixels))
    errors = {}
    for k in (2, 4, 8, 16):
        offsets, weights = gauss_legendre_pixel_nodes(k)
        nodes = (np.arange(pixels, dtype=float)[:, None] + offsets[None, :]).ravel()
        node_weights = np.tile(weights, pixels)
        response = pixel_response_matrix(np.arange(pixels, dtype=float), nodes, node_weights, 0.0)
        density = np.exp(-0.5 * ((nodes - centre) / sigma) ** 2) / (math.sqrt(2.0 * math.pi) * sigma)
        image = response @ np.outer(density, density) @ response.T
        errors[k] = float(np.max(np.abs(image - exact)) / np.max(exact))
    assert errors[4] <= 1e-6, errors
    assert errors[16] <= errors[8] <= errors[4] <= errors[2] or errors[8] < 1e-13


def test_square_lenslet_matches_an_independent_dirichlet_quadrature() -> None:
    # The central lenslet of a 5x5 grid on 60 samples is a fully illuminated
    # 12x12-sample square: its spot is a separable Dirichlet kernel.
    geometry = build_shack_hartmann_geometry(
        telescope_diameter_m=1.0, pupil_shape=(60, 60), n_lenslets_across=5,
        min_fill_fraction=0.5, central_obstruction_ratio=0.0, spider_width_m=0.0,
    )
    centre_index = geometry.subaperture_ids.index("lenslet-r0002-c0002")
    assert int(np.count_nonzero(geometry.subaperture_masks[centre_index])) == 144
    samples = 12
    dx = float(geometry.x_m[0, 1] - geometry.x_m[0, 0])
    wavelength = 7.0e-7
    pixel = wavelength / (2.5 * samples * dx)
    block = 9
    optics = MftShackHartmannOptics(
        geometry, wavelengths_m=(wavelength,), spectral_weights=(1.0,),
        pixel_scale_rad=pixel, block_px=block, oversampling=8,
    )
    result, _ = optics.spot_intensities_with_diagnostics(np.zeros(geometry.pupil_shape))
    image = result.unit_sum_spots[centre_index] * result.relative_throughput[centre_index]

    def kernel(u: float) -> float:
        # Fraction of flux per unit u (u = theta dx / lambda), normalized to one per period.
        if abs(math.sin(math.pi * u)) < 1e-15:
            return float(samples)
        return math.sin(math.pi * samples * u) ** 2 / (samples * math.sin(math.pi * u) ** 2)

    scale = pixel * dx / wavelength
    one_d = []
    for index in range(block):
        low = (index - (block - 1) / 2 - 0.5) * scale
        value, _ = quad(kernel, low, low + scale, limit=200, epsabs=1e-15, epsrel=1e-13)
        one_d.append(value)
    expected = np.outer(one_d, one_d)
    np.testing.assert_allclose(image, expected, rtol=1e-9, atol=1e-12)


@pytest.mark.parametrize("sigma", [0.0, 0.2, 0.5])
def test_pixel_responses_form_a_partition_of_unity(sigma: float) -> None:
    offsets, weights = gauss_legendre_pixel_nodes(4)
    nodes = (np.arange(-3, 12, dtype=float)[:, None] + offsets[None, :]).ravel()
    unit = np.ones_like(nodes)
    # Every pixel within reach of the nodes, so nothing is lost at an edge.
    response = pixel_response_matrix(np.arange(-8, 17, dtype=float), nodes, unit, sigma)
    np.testing.assert_allclose(response.sum(axis=0), 1.0, rtol=0, atol=1e-12)
    if sigma == 0.0:
        assert set(np.unique(response)) <= {0.0, 1.0}


def test_flux_is_conserved_and_losses_are_reported_separately() -> None:
    geometry = dense()
    optics = MftShackHartmannOptics(
        geometry, wavelengths_m=(7.0e-7,), spectral_weights=(1.0,), pixel_scale_rad=5.409e-7,
        block_px=21, oversampling=4, diffusion_sigma_px=0.0,
    )
    result, diagnostics = optics.spot_intensities_with_diagnostics(np.zeros(geometry.pupil_shape))
    # No diffusion and no margin: block sum equals the represented optical flux.
    np.testing.assert_allclose(diagnostics["block_fraction"], diagnostics["represented_fraction"], rtol=0, atol=1e-12)
    assert np.all(diagnostics["optical_field_loss"] > 0.0)
    diffused = MftShackHartmannOptics(
        geometry, wavelengths_m=(7.0e-7,), spectral_weights=(1.0,), pixel_scale_rad=5.409e-7,
        block_px=21, oversampling=4, diffusion_sigma_px=0.5,
    )
    _, with_diffusion = diffused.spot_intensities_with_diagnostics(np.zeros(geometry.pupil_shape))
    np.testing.assert_allclose(
        with_diffusion["block_fraction"] + with_diffusion["diffusion_outflow"],
        with_diffusion["represented_fraction"], rtol=0, atol=1e-12,
    )
    assert np.all(with_diffusion["diffusion_outflow"] > 0.0)
    # Unit-sum normalization does not hide the losses: throughput carries them.
    assert np.all(result.relative_throughput < 1.0)


@pytest.mark.parametrize("diffusion", [0.2, 0.4, 0.7])
def test_diffusion_adds_its_variance_to_the_spot(diffusion: float) -> None:
    pixels, sigma, centre = 31, 1.0, 15.0
    offsets, weights = gauss_legendre_pixel_nodes(16)
    nodes = (np.arange(-6, pixels + 6, dtype=float)[:, None] + offsets[None, :]).ravel()
    node_weights = np.tile(weights, pixels + 12)
    density = np.exp(-0.5 * ((nodes - centre) / sigma) ** 2) / (math.sqrt(2.0 * math.pi) * sigma)
    axis = np.arange(pixels, dtype=float)

    def variance(kernel_sigma: float) -> float:
        profile = pixel_response_matrix(axis, nodes, node_weights, kernel_sigma) @ density
        mean = float(np.sum(profile * axis) / np.sum(profile))
        return float(np.sum(profile * (axis - mean) ** 2) / np.sum(profile))

    # Pixel sampling adds 1/12; diffusion adds sigma_d^2 (truncation at 5 sigma: < 2e-5 relative).
    assert math.isclose(variance(diffusion) - variance(0.0), diffusion**2, rel_tol=1e-4)


def test_spots_scale_with_wavelength_as_diffraction_predicts() -> None:
    geometry = dense()
    base_scale = 5.0e-7
    images = []
    for wavelength in (6.0e-7, 9.0e-7):
        optics = MftShackHartmannOptics(
            geometry, wavelengths_m=(wavelength,), spectral_weights=(1.0,),
            pixel_scale_rad=base_scale * wavelength / 6.0e-7, block_px=15, oversampling=1,
        )
        images.append(optics.spot_intensities(np.zeros(geometry.pupil_shape)).unit_sum_spots)
    for a, b in zip(*images):
        np.testing.assert_allclose(b, a, rtol=1e-12, atol=1e-14)


def test_one_sample_bandpass_equals_the_monochromatic_model() -> None:
    geometry = dense()
    opd = np.random.default_rng(4).normal(0.0, 50.0e-9, geometry.pupil_shape)
    kwargs = dict(pixel_scale_rad=5.4e-7, block_px=21, oversampling=4, diffusion_sigma_px=0.25)
    mono = MftShackHartmannOptics(geometry, wavelengths_m=(7.0e-7,), spectral_weights=(1.0,), **kwargs)
    one = MftShackHartmannOptics(geometry, wavelengths_m=(7.0e-7,), spectral_weights=(1.0,), reference_wavelength_m=7.0e-7, **kwargs)
    for a, b in zip(mono.spot_intensities(opd).unit_sum_spots, one.spot_intensities(opd).unit_sum_spots):
        assert np.array_equal(a, b)


def test_quadrature_convergence_of_slopes_and_centroid_gain() -> None:
    """Predeclared tolerance: n = 5 and n = 7 agree to 2e-3 px in every slope."""

    from shwfs_ao.core.spectral import gauss_legendre_quadrature

    geometry = dense()
    opd = np.random.default_rng(9).normal(0.0, 40.0e-9, geometry.pupil_shape)
    tilt = np.where(np.asarray(geometry.pupil_mask), 3.0e-7 * np.asarray(geometry.x_m), 0.0)
    slopes = {}
    for count in (1, 3, 5, 7):
        quadrature = gauss_legendre_quadrature(6.0e-7, 9.0e-7, count)
        weights = quadrature.weight_m / quadrature.wavelength_m
        weights = weights / weights.sum()
        optics = MftShackHartmannOptics(
            geometry, wavelengths_m=tuple(quadrature.wavelength_m), spectral_weights=tuple(weights),
            pixel_scale_rad=5.4e-7, block_px=21, oversampling=2,
        )
        values = []
        for field in (opd, opd + tilt):
            spots = optics.spot_intensities(field)
            values.append([float(np.sum(s * np.arange(21)[None, :])) for s in spots.unit_sum_spots])
        slopes[count] = np.asarray(values[1]) - np.asarray(values[0])
    assert np.max(np.abs(slopes[7] - slopes[5])) < 2.0e-3
    assert np.max(np.abs(slopes[7] - slopes[3])) < np.max(np.abs(slopes[7] - slopes[1]))


def test_a_field_reaching_the_far_field_period_fails_closed() -> None:
    geometry = dense()
    with pytest.raises(NativeShackHartmannError, match="alias"):
        MftShackHartmannOptics(
            geometry, wavelengths_m=(6.0e-7, 9.0e-7), spectral_weights=(0.5, 0.5),
            pixel_scale_rad=5.4e-7, block_px=29, oversampling=2, diffusion_sigma_px=0.4,
        )
    with pytest.raises(NativeShackHartmannError, match="odd"):
        MftShackHartmannOptics(geometry, wavelengths_m=(7.0e-7,), spectral_weights=(1.0,), pixel_scale_rad=5.4e-7, block_px=20)
