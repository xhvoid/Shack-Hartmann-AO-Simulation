"""ESO-05: compact lenslet geometry and batched native SH optics.

The dense :class:`ShackHartmannGeometry` and :class:`NativeShackHartmannOptics`
are the numerical oracle; the compact/batched path must reproduce their
partition, spots, captured fractions, centroids, slopes and validity.
"""

from __future__ import annotations

import numpy as np
import pytest

from shwfs_ao.backends.native.shwfs import NativeShackHartmannOptics
from shwfs_ao.backends.native.shwfs_batched import (
    MEASUREMENT_LOCALITY,
    BatchedNativeShackHartmannOptics,
)
from shwfs_ao.core.random import NamedRandomStreams
from shwfs_ao.detector import CentroidConfig, CentroidValidityConfig, DetectorConfig
from shwfs_ao.wfs.shack_hartmann import compact_geometry as compact_module
from shwfs_ao.wfs.shack_hartmann.compact_geometry import (
    CompactShackHartmannGeometry,
    build_compact_shack_hartmann_geometry,
)
from shwfs_ao.wfs.shack_hartmann.geometry import (
    ShackHartmannGeometryError,
    build_shack_hartmann_geometry,
)
from shwfs_ao.wfs.shack_hartmann.measurement import DetectorShackHartmannSensor

WAVELENGTH = 7.0e-7
CASES = (
    # pupil samples, lenslets, obstruction, fill cut
    (120, 10, 0.28, 0.5),  # divisible, the CI tier sampling (12 samples/lenslet)
    (122, 10, 0.28, 0.5),  # nondivisible: cells of 12 and 13 samples
    (121, 10, 0.0, 0.35),  # odd grid
    (64, 7, 0.28, 0.0),  # every illuminated cell retained, partial edges
    (66, 11, 0.4, 0.6),  # large obstruction, strict fill cut
)


def _pair(n, lenslets, obstruction, fill):
    keywords = dict(
        telescope_diameter_m=5.0,
        pupil_shape=(n, n),
        n_lenslets_across=lenslets,
        min_fill_fraction=fill,
        central_obstruction_ratio=obstruction,
    )
    return build_shack_hartmann_geometry(**keywords), build_compact_shack_hartmann_geometry(
        **keywords
    )


def _smooth_opd(n, seed=0, scale=2e-7):
    rng = np.random.default_rng(seed)
    noise = rng.normal(size=(n, n))
    smooth = np.cumsum(np.cumsum(noise, axis=0), axis=1)
    smooth -= smooth.mean()
    return scale * smooth / smooth.std()


def _tilt(geometry, x_waves_per_d=0.0, y_waves_per_d=0.0, piston=0.0):
    d = geometry.telescope_diameter_m
    return (
        WAVELENGTH * (x_waves_per_d * geometry.x_m + y_waves_per_d * geometry.y_m) / d
        + piston
    )


@pytest.mark.parametrize("case", CASES)
def test_compact_partition_equals_the_dense_partition(case):
    dense, compact = _pair(*case)
    assert compact.subaperture_ids == dense.subaperture_ids
    assert compact.row_ids == dense.row_ids
    np.testing.assert_array_equal(compact.subaperture_centers_m, dense.subaperture_centers_m)
    for dense_mask, compact_mask in zip(
        dense.subaperture_masks, compact.dense_subaperture_masks(), strict=True
    ):
        np.testing.assert_array_equal(dense_mask, compact_mask)
    assert compact.pupil_shape == (case[0], case[0])  # never rounded
    labels = compact.lenslet_label_map()
    for index, mask in enumerate(dense.subaperture_masks):
        assert np.all(labels[mask] == index)
    assert np.all(labels[~np.any(np.stack(dense.subaperture_masks), axis=0)] == -1)


def test_nondivisible_pupils_keep_unequal_cells():
    _, compact = _pair(122, 10, 0.0, 0.0)
    heights = {int(r1 - r0) for r0, r1, _, _ in compact.lenslet_bounds_rc}
    assert heights == {12, 13}


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("batch_size", (1, 7, 10_000))
def test_batched_spots_equal_the_dense_backend(case, batch_size):
    dense, compact = _pair(*case)
    reference = NativeShackHartmannOptics(dense, WAVELENGTH, pad_factor=2, detector_window_px=20)
    batched = BatchedNativeShackHartmannOptics(
        compact, WAVELENGTH, pad_factor=2, detector_window_px=20, batch_size=batch_size
    )
    assert batched.sampling.sampling_hash == reference.sampling.sampling_hash
    assert batched.measurement_locality == MEASUREMENT_LOCALITY
    n = case[0]
    for opd in (
        np.zeros((n, n)),
        _tilt(dense, x_waves_per_d=3.0),
        _tilt(dense, y_waves_per_d=-2.0),
        _tilt(dense, piston=3.0e-7),
        _smooth_opd(n),
    ):
        expected = reference.spot_intensities(opd)
        actual = batched.spot_intensities(opd)
        assert actual.subaperture_ids == expected.subaperture_ids
        np.testing.assert_allclose(
            actual.relative_throughput, expected.relative_throughput, rtol=1e-11, atol=1e-14
        )
        for left, right, lx, rx in zip(
            actual.unit_sum_spots, expected.unit_sum_spots, actual.x_px, expected.x_px,
            strict=True,
        ):
            np.testing.assert_allclose(left, right, rtol=1e-11, atol=1e-14)
            np.testing.assert_array_equal(lx, rx)
    np.testing.assert_allclose(
        batched.pupil_relative_throughput, reference.pupil_relative_throughput, rtol=1e-15
    )


def _detector_config():
    return DetectorConfig(
        photons_per_subap_frame=1.0e5,
        read_noise_e=0.5,
        qe=1.0,
        prnu_rms=0.0,
        exposure_s=0.002,
        prnu_mode="persistent",
        source_class="synthetic_assumed",
        source_note="ESO-05 compact-geometry equivalence fixture",
    )


def _sensor(geometry, optics, seed=11):
    return DetectorShackHartmannSensor.calibrate(
        geometry,
        optics,
        _detector_config(),
        wfs_wavelength_m=WAVELENGTH,
        random_streams=NamedRandomStreams(seed).scoped("sensor"),
        centroid_config=CentroidConfig(),
        validity_config=CentroidValidityConfig(
            min_flux_e=100.0,
            min_peak_snr=3.0,
            max_centroid_sigma_px=0.5,
            max_window_clipping_fraction=0.15,
        ),
    )


@pytest.mark.parametrize("case", CASES[:3])
def test_detector_sensor_slopes_and_validity_match_the_dense_sensor(case):
    dense, compact = _pair(*case)
    dense_sensor = _sensor(dense, NativeShackHartmannOptics(dense, WAVELENGTH, pad_factor=2, detector_window_px=24))
    compact_sensor = _sensor(
        compact, BatchedNativeShackHartmannOptics(compact, WAVELENGTH, pad_factor=2, detector_window_px=24)
    )
    np.testing.assert_allclose(
        compact_sensor.calibration.reference_centroids_px,
        dense_sensor.calibration.reference_centroids_px,
        rtol=0.0,
        atol=1e-12,
    )
    streams = NamedRandomStreams(11)
    for opd in (_tilt(dense, x_waves_per_d=2.0), _smooth_opd(case[0], seed=3)):
        expected = dense_sensor.measure(opd, random_streams=streams, include_noise=False)
        actual = compact_sensor.measure(opd, random_streams=streams, include_noise=False)
        assert actual.vector.row_ids == expected.vector.row_ids
        np.testing.assert_array_equal(actual.vector.valid_rows, expected.vector.valid_rows)
        np.testing.assert_array_equal(actual.valid_subapertures, expected.valid_subapertures)
        # Centroid differences in detector pixels.
        np.testing.assert_allclose(
            actual.vector.values, expected.vector.values, rtol=0.0, atol=1e-11
        )


def test_noise_draws_and_validity_do_not_depend_on_batch_size():
    _, compact = _pair(120, 10, 0.28, 0.5)
    opd = _smooth_opd(120, seed=5)
    results = []
    for batch_size in (1, 7, 10_000):
        optics = BatchedNativeShackHartmannOptics(
            compact, WAVELENGTH, pad_factor=2, detector_window_px=24, batch_size=batch_size
        )
        sensor = _sensor(compact, optics)
        results.append(
            sensor.measure(opd, random_streams=NamedRandomStreams(11), include_noise=True)
        )
    for other in results[1:]:
        np.testing.assert_array_equal(other.vector.values, results[0].vector.values)
        np.testing.assert_array_equal(other.vector.valid_rows, results[0].vector.valid_rows)


def test_full_path_never_builds_dense_masks_or_rehashes_geometry_per_frame(monkeypatch):
    _, compact = _pair(120, 10, 0.28, 0.5)

    def _refuse(self, *, max_bytes=0):
        raise AssertionError("dense lenslet masks requested")

    monkeypatch.setattr(CompactShackHartmannGeometry, "dense_subaperture_masks", _refuse)
    sensor = _sensor(
        compact, BatchedNativeShackHartmannOptics(compact, WAVELENGTH, pad_factor=2, detector_window_px=24)
    )
    calls = []
    real_hash = compact_module._geometry_hash

    def _counting(value):
        calls.append(type(value).__name__)
        return real_hash(value)

    monkeypatch.setattr(compact_module, "_geometry_hash", _counting)
    streams = NamedRandomStreams(11)
    for _ in range(3):
        sensor.measure(_smooth_opd(120), random_streams=streams, include_noise=False)
    assert calls == []
    assert compact.dense_mask_bytes > 10 * sum(mask.nbytes for mask in compact.lenslet_masks)


def test_dense_mask_view_is_size_guarded():
    _, compact = _pair(120, 10, 0.28, 0.5)
    with pytest.raises(ShackHartmannGeometryError, match="refused"):
        compact.dense_subaperture_masks(max_bytes=1000)


def test_compact_identity_is_cached_content_and_rejects_bad_records():
    _, first = _pair(120, 10, 0.28, 0.5)
    _, second = _pair(120, 10, 0.28, 0.5)
    _, other = _pair(120, 10, 0.30, 0.5)
    assert first.geometry_hash == second.geometry_hash == first.config_hash
    assert first == second and first != other
    with pytest.raises(ValueError):
        first.lenslet_masks[0][0, 0] = True
    bad_masks = list(first.lenslet_masks)
    bad_masks[0] = np.ones((3, 3), dtype=bool)
    from dataclasses import replace

    with pytest.raises(ShackHartmannGeometryError):
        replace(first, lenslet_masks=tuple(bad_masks))


def _geometry_only_estimate_bytes(n, lenslets):
    pupil_and_axes = n * n * (1 + 8 + 8)
    labels = n * n * 4
    cells = lenslets * lenslets * ((n // lenslets + 1) ** 2 + 64)
    return 2 * (pupil_and_axes + labels + cells)  # 2x margin; < 100 MiB at 1024


@pytest.mark.elt_scale
@pytest.mark.parametrize("pupil_samples", (1008, 1024))
def test_nominal_84_across_partition_at_1008_and_1024_samples(pupil_samples, request):
    """Geometry-only target-size check (audited estimate < 100 MiB)."""

    if not request.config.getoption("--enable-elt-scale", default=False):
        pytest.skip("elt_scale test needs --enable-elt-scale")

    assert _geometry_only_estimate_bytes(pupil_samples, 84) < 100 * 1024**2
    compact = build_compact_shack_hartmann_geometry(
        telescope_diameter_m=42.0,
        pupil_shape=(pupil_samples, pupil_samples),
        n_lenslets_across=84,
        min_fill_fraction=0.5,
        central_obstruction_ratio=0.28,
    )
    assert compact.pupil_shape == (pupil_samples, pupil_samples)
    sizes = {int(r1 - r0) for r0, r1, _, _ in compact.lenslet_bounds_rc}
    assert sizes == ({12} if pupil_samples == 1008 else {12, 13})
    assert 4000 < compact.n_subapertures < 84 * 84
    assert compact.dense_mask_bytes > 4 * 1024**3
