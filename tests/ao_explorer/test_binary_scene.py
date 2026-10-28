"""Origin, orientation, flux and identity oracles of the synthetic binary observation.

Every oracle here is independent of ``binary_scene.linear_convolution_full``:
SciPy's direct ``convolve2d(mode="full")``, an FFT on explicitly padded
arrays, and hand-placed shifted kernels.  The grids reproduce the native
propagator's even-length ``fftshift(fftfreq)`` axes, whose zero sample is
not the array midpoint convention a library ``same`` crop assumes.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.signal import convolve2d

import binary_scene
import protocol


ATOL = protocol.TOLERANCES["convolution"]["atol"]
FLUX_ATOL = protocol.TOLERANCES["convolution_flux"]["atol"]


def even_axis(n=24, step=0.5e-7):
    return np.fft.fftshift(np.fft.fftfreq(n, d=1.0 / (n * step)))


def asymmetric_kernel(n, *, seed=7):
    rng = np.random.default_rng(seed)
    kernel = rng.random((n, n)) ** 4
    kernel[n // 2, n // 2 + 1] += 3.0  # an off-centre bright cell breaks symmetry
    return kernel / kernel.sum()


def scene_on(axis, *, wavelength=1.65e-6, diameter=2.0):
    return binary_scene.build_scene(axis, axis, wavelength_m=wavelength, telescope_diameter_m=diameter)


def test_zero_index_comes_from_the_axis_not_the_shape():
    axis = even_axis(24)
    assert axis[12] == 0.0 and binary_scene.zero_index(axis, label="x") == 12
    with pytest.raises(binary_scene.BinarySceneError):
        binary_scene.zero_index(axis + 1e-9, label="shifted")


def test_scene_geometry_weights_and_flux():
    axis = even_axis(24)
    bundle = scene_on(axis)
    record = bundle["record"]
    primary, secondary = record["sources"]
    assert primary["angle_xy_rad"] == [0.0, 0.0]
    assert secondary["index_yx"] == [12, 18] and secondary["angle_xy_rad"][1] == 0.0
    assert secondary["angle_xy_rad"][0] == pytest.approx(6 * (axis[1] - axis[0]), rel=1e-14)
    assert record["total_flux"] == pytest.approx(1.0, abs=1e-15)
    assert primary["weight"] == pytest.approx(2.0 / 3.0) and secondary["weight"] == pytest.approx(1.0 / 3.0)
    assert np.count_nonzero(bundle["scene"]) == 2


def test_centered_delta_reproduces_the_located_kernel():
    axis = even_axis(24)
    kernel = asymmetric_kernel(24)
    delta = np.zeros((24, 24))
    delta[12, 12] = 1.0
    bundle = {"scene": delta, "record": scene_on(axis)["record"]}
    result = binary_scene.observe(bundle, kernel, axis, axis)
    np.testing.assert_allclose(result["image"], kernel, rtol=0.0, atol=ATOL)


def test_binary_equals_an_independent_weighted_sum_of_shifted_kernels():
    axis = even_axis(24)
    kernel = asymmetric_kernel(24)
    bundle = scene_on(axis)
    result = binary_scene.observe(bundle, kernel, axis, axis)
    expected = (2.0 / 3.0) * kernel
    shifted = np.zeros_like(kernel)
    shifted[:, 6:] = kernel[:, :-6]  # +x is increasing column; zeros enter, nothing wraps
    expected = expected + (1.0 / 3.0) * shifted
    np.testing.assert_allclose(result["image"], expected, rtol=0.0, atol=ATOL)
    # Wrong conventions are distinguishable: reversed x, a one-column offset, a wrap.
    for wrong in (
        (2.0 / 3.0) * kernel + (1.0 / 3.0) * np.roll(kernel, -6, axis=1),
        (2.0 / 3.0) * kernel + (1.0 / 3.0) * np.roll(kernel, 7, axis=1),
        (2.0 / 3.0) * kernel + (1.0 / 3.0) * np.roll(kernel, 6, axis=1),
    ):
        assert np.max(np.abs(wrong - result["image"])) > 1e-6


def test_full_convolution_matches_scipy_direct_and_padded_fft():
    axis = even_axis(20)
    kernel = asymmetric_kernel(20, seed=3)
    scene = scene_on(axis)["scene"]
    ours = binary_scene.linear_convolution_full(scene, kernel)
    direct = convolve2d(scene, kernel, mode="full")
    shape = (scene.shape[0] + kernel.shape[0] - 1, scene.shape[1] + kernel.shape[1] - 1)
    fft = np.real(np.fft.ifft2(np.fft.fft2(scene, shape) * np.fft.fft2(kernel, shape)))
    np.testing.assert_allclose(ours, direct, rtol=0.0, atol=ATOL)
    np.testing.assert_allclose(ours, fft, rtol=0.0, atol=1e-14)


def test_edge_source_loses_flux_to_the_crop_without_wrapping_or_renormalizing():
    axis = even_axis(24)
    kernel = asymmetric_kernel(24, seed=11)
    edge = np.zeros((24, 24))
    edge[12, 23] = 1.0  # last x column: half the kernel leaves the native window
    bundle = {"scene": edge, "record": scene_on(axis)["record"]}
    result = binary_scene.observe(bundle, kernel, axis, axis)
    assert result["full_flux"] == pytest.approx(result["expected_full_flux"], abs=FLUX_ATOL)
    assert result["cropped_flux"] < result["full_flux"]
    assert result["retained_fraction"] == pytest.approx(result["cropped_flux"] / result["full_flux"], rel=1e-15)
    # Columns left of the source's footprint hold no wrapped-around flux.
    assert np.all(result["image"][:, : 23 - 12] == 0.0)
    expected = np.zeros_like(kernel)
    expected[:, 11:] = kernel[:, :13]
    np.testing.assert_allclose(result["image"], expected, rtol=0.0, atol=ATOL)


def test_asymmetric_y_source_catches_reversed_rows():
    axis = even_axis(24)
    kernel = asymmetric_kernel(24, seed=5)
    scene = np.zeros((24, 24))
    scene[15, 12] = 1.0  # +3 rows: positive y
    bundle = {"scene": scene, "record": scene_on(axis)["record"]}
    result = binary_scene.observe(bundle, kernel, axis, axis)
    expected = np.zeros_like(kernel)
    expected[3:, :] = kernel[:-3, :]
    np.testing.assert_allclose(result["image"], expected, rtol=0.0, atol=ATOL)


def test_convolution_of_the_mean_equals_the_mean_of_convolutions():
    axis = even_axis(24)
    bundle = scene_on(axis)
    kernels = [asymmetric_kernel(24, seed=seed) for seed in range(5)]
    mean_kernel = sum(kernels) / len(kernels)
    of_mean = binary_scene.observe(bundle, mean_kernel, axis, axis)["image"]
    mean_of = sum(binary_scene.observe(bundle, k, axis, axis)["image"] for k in kernels) / len(kernels)
    np.testing.assert_allclose(of_mean, mean_of, rtol=0.0, atol=ATOL)


def test_flux_bookkeeping_and_no_renormalization():
    axis = even_axis(24)
    bundle = scene_on(axis)
    kernel = asymmetric_kernel(24) * 0.5  # a sub-unit kernel stays sub-unit
    result = binary_scene.observe(bundle, kernel, axis, axis)
    assert result["full_flux"] == pytest.approx(0.5, abs=FLUX_ATOL)
    assert result["expected_full_flux"] == pytest.approx(0.5, abs=FLUX_ATOL)
    assert result["cropped_flux"] <= result["full_flux"]


def test_mismatched_parent_grid_shape_or_values_refuse():
    axis = even_axis(24)
    bundle = scene_on(axis)
    kernel = asymmetric_kernel(24)
    with pytest.raises(binary_scene.BinarySceneError):
        binary_scene.observe(bundle, kernel, axis * 1.0000001, axis)
    with pytest.raises(binary_scene.BinarySceneError):
        binary_scene.observe(bundle, kernel[:-1, :-1], axis, axis)
    bad = kernel.copy()
    bad[0, 0] = np.nan
    with pytest.raises(binary_scene.BinarySceneError):
        binary_scene.observe(bundle, bad, axis, axis)
    bad = kernel.copy()
    bad[0, 0] = -1e-3
    with pytest.raises(binary_scene.BinarySceneError):
        binary_scene.observe(bundle, bad, axis, axis)
