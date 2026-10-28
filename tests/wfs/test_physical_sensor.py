"""DET-01/02/06: the physical Shack-Hartmann sensor end to end.

Fixtures are a 1 m, 30-sample, 3x3-lenslet geometry with the frozen FFT
optics (pad 2), so every test builds in well under a second.
"""

from __future__ import annotations

from dataclasses import replace
import math

import numpy as np
import pytest

from shwfs_ao.backends.native.shwfs import NativeShackHartmannOptics
from shwfs_ao.core.random import NamedRandomStreams, with_detector_physics_domains
from shwfs_ao.detector.camera import CameraConfig
from shwfs_ao.detector.camera_maps import CameraMaps
from shwfs_ao.detector.layout import DetectorLayout
from shwfs_ao.detector.physical import apply_physical_camera
from shwfs_ao.detector.physical_config import (
    BandpassConfig,
    DetectorPlaneSamplingConfig,
    PhysicalDetectorConfig,
    SourceBudgetConfig,
)
from shwfs_ao.detector.processing import (
    PixelProcessingConfig,
    build_calibration_products,
    process_frames,
)
from shwfs_ao.wfs.shack_hartmann.geometry import build_shack_hartmann_geometry
from shwfs_ao.wfs.shack_hartmann.physical_measurement import (
    PhysicalShackHartmannError,
    PhysicalShackHartmannSensor,
)


WAVELENGTH = 7.0e-7


def geometry(obstruction: float = 0.0):
    return build_shack_hartmann_geometry(
        telescope_diameter_m=1.0,
        pupil_shape=(30, 30),
        n_lenslets_across=3,
        min_fill_fraction=0.3,
        central_obstruction_ratio=obstruction,
        spider_width_m=0.0,
    )


def camera(**overrides: object) -> CameraConfig:
    values: dict[str, object] = dict(
        model="ccd",
        preset_name="test",
        preset_version=1,
        quantum_efficiency=0.8,
        full_well_e=1.0e6,
        dark_e_per_s=10.0,
        hot_pixel_fraction=0.01,
        hot_pixel_dark_e_per_s=2000.0,
        prnu_rms=0.02,
        dead_pixel_fraction=0.005,
        read_noise_e=3.0,
        conversion_gain_e_per_adu=1.5,
        bias_adu=500.0,
        offset_map_rms_adu=1.0,
        adc_bits=16,
    )
    values.update(overrides)
    return CameraConfig(**values)  # type: ignore[arg-type]


def processing(mode: str = "estimated", **overrides: object) -> PixelProcessingConfig:
    values: dict[str, object] = dict(
        mode=mode,
        n_bias_frames=8 if mode == "estimated" else 0,
        n_dark_frames=8 if mode == "estimated" else 0,
        n_sky_frames=8 if mode == "estimated" else 0,
        n_flat_frames=8 if mode == "estimated" else 0,
        flat_level_e=2000.0,
        hot_pixel_threshold_e=5.0,
    )
    values.update(overrides)
    return PixelProcessingConfig(**values)  # type: ignore[arg-type]


def physical(cam: CameraConfig | None = None, *, proc: PixelProcessingConfig | None = None, guard: int = 0, magnitude: float = 6.0, sky: float | None = 19.0) -> PhysicalDetectorConfig:
    return PhysicalDetectorConfig(
        camera=camera() if cam is None else cam,
        layout_scheme="isolated_lenslet_blocks.v1",
        guard_px=guard,
        source=SourceBudgetConfig(kind="ab_flat_fnu", ab_magnitude=magnitude, throughput_excluding_qe=0.5, sky_ab_mag_per_arcsec2=sky),
        bandpass=BandpassConfig(kind="monochromatic", band_min_m=5.5e-7, band_max_m=8.5e-7),
        sampling=DetectorPlaneSamplingConfig(kind="legacy_fft"),
        processing=processing() if proc is None else proc,
        exposure_s=1.0e-3,
    )


def build(config: PhysicalDetectorConfig, *, window: int = 15, seed: int = 4, geo=None, **keywords):
    geo = geometry() if geo is None else geo
    optics = NativeShackHartmannOptics(geo, WAVELENGTH, pad_factor=2, detector_window_px=window + 2 * config.guard_px)
    streams = with_detector_physics_domains(NamedRandomStreams(seed))
    sensor = PhysicalShackHartmannSensor.calibrate(
        geo, optics, config, wfs_wavelength_m=WAVELENGTH, random_streams=streams, **keywords
    )
    return sensor, streams


# -- DET-02 integration -------------------------------------------------------------


def test_half_qe_gives_half_the_source_electrons_not_a_quarter() -> None:
    full, streams = build(physical(camera(quantum_efficiency=1.0)))
    half, _ = build(physical(camera(quantum_efficiency=0.5)))
    assert np.allclose(half.detected_e_per_subap, 0.5 * full.detected_e_per_subap, rtol=1e-14)
    zero = np.zeros(full.geometry.pupil_shape)
    frame_full = full.measure(zero, random_streams=streams, include_noise=False).detector_telemetry.detector_frames[0]
    frame_half = half.measure(zero, random_streams=streams, include_noise=False).detector_telemetry.detector_frames[0]
    response = frame_full.prnu_response
    ratio = np.sum(frame_half.expected_source_e) / np.sum(frame_full.expected_source_e)
    assert math.isclose(ratio, 0.5, rel_tol=1e-12)
    assert np.allclose(frame_full.prnu_response, response)


def test_budgets_follow_partial_illumination_and_capture_is_applied_once() -> None:
    geo = geometry(obstruction=0.3)
    sensor, streams = build(physical(), geo=geo)
    counts = np.array([np.count_nonzero(mask) for mask in geo.subaperture_masks], dtype=float)
    dx = float(geo.x_m[0, 1] - geo.x_m[0, 0])
    area_fraction = counts * dx * dx / (1.0 / 3.0) ** 2
    ratio = sensor.detected_e_per_subap / area_fraction
    assert np.allclose(ratio, ratio[0], rtol=1e-13)
    assert len(set(np.round(area_fraction, 12))) > 1  # obstruction makes them differ
    measurement = sensor.measure(np.zeros(geo.pupil_shape), random_streams=streams, include_noise=False)
    spots = sensor.optics_backend.spot_intensities(np.zeros(geo.pupil_shape))
    for index, frame in enumerate(measurement.detector_telemetry.detector_frames):
        source_before_response = frame.expected_source_e / np.where(frame.prnu_response > 0, frame.prnu_response, 1.0)
        live = frame.prnu_response > 0
        expected = sensor.detected_e_per_subap[index] * spots.relative_throughput[index] * spots.unit_sum_spots[index]
        assert np.allclose(source_before_response[live], expected[live], rtol=1e-12)


# -- DET-01 identities ------------------------------------------------------------------


def test_identity_rules_of_the_physical_sensor() -> None:
    oracle = processing("oracle")
    base, _ = build(physical(proc=oracle))
    summary = base.with_telemetry_level("summary")
    for name in ("config_hash", "response_hash", "noisy_response_hash", "detector_hash", "noise_stream_identity"):
        assert getattr(summary, name) == getattr(base, name)
    read_noise, _ = build(physical(camera(read_noise_e=6.0), proc=oracle))
    assert read_noise.response_hash == base.response_hash
    assert read_noise.camera_maps.realization_hash == base.camera_maps.realization_hash
    assert read_noise.noisy_response_hash != base.noisy_response_hash
    adc, _ = build(physical(camera(adc_bits=12), proc=oracle))
    assert adc.response_hash != base.response_hash
    guard, _ = build(physical(proc=oracle, guard=1))
    assert guard.response_hash != base.response_hash
    assert guard.layout.layout_hash != base.layout.layout_hash
    # Regenerated (estimated) calibration products move the conditioned response.
    estimated0, _ = build(physical())
    estimated1, _ = build(physical(), calibration_realization_index=1)
    assert estimated0.calibration_products.content_hash != estimated1.calibration_products.content_hash
    assert estimated0.response_hash != estimated1.response_hash
    assert estimated0.camera_maps.realization_hash == estimated1.camera_maps.realization_hash


def test_summary_telemetry_keeps_only_per_lenslet_scalars() -> None:
    sensor, streams = build(physical())
    summary = sensor.with_telemetry_level("summary")
    zero = np.zeros(sensor.geometry.pupil_shape)
    full_measurement = sensor.measure(zero, random_streams=streams, include_noise=True)
    summary_measurement = summary.measure(zero, random_streams=streams, include_noise=True)
    telemetry = summary_measurement.detector_telemetry
    assert telemetry.telemetry_level == "summary"
    assert telemetry.detector_frames is None and telemetry.optical_spots is None
    count = len(sensor.subaperture_ids)
    for name in ("fluxes_e", "peak_snr", "centroid_sigma_px", "centroid_calibration_sigma_px", "masked_pixel_fraction", "saturated_pixel_count"):
        assert np.asarray(getattr(telemetry, name)).shape == (count,)
    assert full_measurement.detector_telemetry.detector_frames is not None
    assert full_measurement.detector_telemetry.detector_frames[0].raw_unit == "adu"


def test_maps_and_products_are_persistent_across_frames() -> None:
    sensor, streams = build(physical())
    zero = np.zeros(sensor.geometry.pupil_shape)
    first = sensor.measure(zero, random_streams=streams, include_noise=True).detector_telemetry.detector_frames
    second = sensor.measure(zero, random_streams=streams, include_noise=True).detector_telemetry.detector_frames
    for a, b in zip(first, second):
        assert np.array_equal(a.prnu_response, b.prnu_response)
        assert np.array_equal(a.bad_pixel_mask, b.bad_pixel_mask)
        assert a.calibration_products_hash == b.calibration_products_hash
        assert not np.array_equal(a.raw_image, b.raw_image)  # temporal noise moves


def test_the_physical_sensor_requires_registered_domains_and_odd_windows() -> None:
    geo = geometry()
    optics = NativeShackHartmannOptics(geo, WAVELENGTH, pad_factor=2, detector_window_px=15)
    with pytest.raises(PhysicalShackHartmannError, match="register"):
        PhysicalShackHartmannSensor.calibrate(geo, optics, physical(), wfs_wavelength_m=WAVELENGTH, random_streams=NamedRandomStreams(1))
    even = NativeShackHartmannOptics(geo, WAVELENGTH, pad_factor=2, detector_window_px=14)
    with pytest.raises(PhysicalShackHartmannError, match="odd"):
        PhysicalShackHartmannSensor.calibrate(geo, even, physical(), wfs_wavelength_m=WAVELENGTH, random_streams=with_detector_physics_domains(NamedRandomStreams(1)))


# -- DET-06 pixel processing ------------------------------------------------------------


def _single_block(cam: CameraConfig, *, window: int = 15, seed: int = 3):
    lay = DetectorLayout("isolated_lenslet_blocks.v1", 1, window, 0)
    streams = with_detector_physics_domains(NamedRandomStreams(seed))
    maps = CameraMaps.create(cam, lay, ("lenslet-r0000-c0000",), random_streams=streams)
    return maps, streams


def test_noiseless_linear_fixture_recovers_the_input_electron_signal() -> None:
    cam = camera(
        model="emccd",
        em_gain=300.0,
        register_full_well_e=1.0e12,
        adc_bits=None,
        hot_pixel_fraction=0.0,
        dead_pixel_fraction=0.0,
        prnu_rms=0.05,
        dark_e_per_s=1000.0,
        read_noise_e=50.0,
    )
    maps, streams = _single_block(cam)
    proc = processing(hot_pixel_threshold_e=1.0e9)
    products = build_calibration_products(cam, maps, proc, exposure_s=1.0e-3, sky_e_per_pixel=2.0, random_streams=None, include_noise=False)
    rng = np.random.default_rng(0)
    source = rng.uniform(0.0, 200.0, size=maps.shape)
    batch = apply_physical_camera(source, 2.0, cam, maps.subset(np.arange(1)), exposure_s=1.0e-3, include_noise=False, generators=None, poisson_floor_e=0.0)
    processed = process_frames(batch.raw, products, proc)
    response = np.asarray(maps.prnu)
    expected = source * float(np.mean(response))  # flat normalized to unit mean
    assert np.allclose(processed, expected, rtol=1e-10, atol=1e-9)


def test_pre_register_cic_mean_is_subtracted_once() -> None:
    cam = camera(model="emccd", em_gain=200.0, register_full_well_e=1.0e12, cic_e_per_pixel_read=0.05, adc_bits=None,
                 hot_pixel_fraction=0.0, dead_pixel_fraction=0.0, prnu_rms=0.0, dark_e_per_s=0.0, read_noise_e=0.0, offset_map_rms_adu=0.0)
    maps, _ = _single_block(cam)
    proc = processing(hot_pixel_threshold_e=1.0e9)
    products = build_calibration_products(cam, maps, proc, exposure_s=1.0e-3, sky_e_per_pixel=0.0, random_streams=None, include_noise=False)
    assert np.allclose(products.bias_raw, 200.0 * 0.05 + 500.0 * 1.5)
    assert np.allclose(products.dark_raw, 0.0, atol=1e-10)
    batch = apply_physical_camera(np.full(maps.shape, 7.0), 0.0, cam, maps.subset(np.arange(1)), exposure_s=1.0e-3, include_noise=False, generators=None, poisson_floor_e=0.0)
    assert np.allclose(process_frames(batch.raw, products, proc), 7.0, rtol=1e-12)


def test_master_variance_scales_as_one_over_n_with_shared_frame_covariance() -> None:
    cam = camera(hot_pixel_fraction=0.0, dead_pixel_fraction=0.0, prnu_rms=0.0, adc_bits=None, read_noise_e=10.0, dark_e_per_s=0.0, offset_map_rms_adu=0.0)
    maps, _ = _single_block(cam, window=9)
    variances = {}
    for count in (4, 16):
        proc = processing(n_bias_frames=count, n_dark_frames=count, n_sky_frames=0, n_flat_frames=count, hot_pixel_threshold_e=1.0e9)
        backgrounds = []
        flats = []
        for realization in range(60):
            provider = with_detector_physics_domains(NamedRandomStreams(1000 + realization))
            products = build_calibration_products(cam, maps, proc, exposure_s=1.0e-3, sky_e_per_pixel=0.0, random_streams=provider)
            backgrounds.append(products.background_raw.ravel())
            flats.append((products.flat * 1.0).ravel())
        backgrounds = np.array(backgrounds)
        variances[count] = float(np.mean(np.var(backgrounds, axis=0, ddof=1)))
    # Background = mean of the dark frames (no sky frames): sigma^2 / N in raw units.
    read_raw = 10.0 * 1.0  # ADC off: output_e_equivalent
    for count, observed in variances.items():
        expected = read_raw**2 / count
        # 60 realizations x 81 pixels: relative SE of the mean variance ~ sqrt(2/59/81) = 2 %.
        assert abs(observed / expected - 1.0) < 0.1, (count, observed, expected)
    assert abs(variances[4] / variances[16] - 4.0) < 0.5


def test_a_fixed_master_is_reused_identically_over_a_temporal_sequence() -> None:
    sensor, streams = build(physical())
    products = sensor.calibration_products
    zero = np.zeros(sensor.geometry.pupil_shape)
    for _ in range(3):
        sensor.measure(zero, random_streams=streams, include_noise=True)
    assert sensor.calibration_products is products
    assert np.array_equal(sensor.calibration_products.background_raw, products.background_raw)


def test_background_subtraction_removes_the_pedestal_gain_loss() -> None:
    bright_sky = 14.0  # a strong pedestal in every pixel
    oracle, streams = build(physical(proc=processing("oracle"), sky=bright_sky))
    raw, _ = build(physical(proc=processing("raw_readout"), sky=bright_sky))
    no_sky, _ = build(physical(proc=processing("oracle"), sky=None))
    geo = oracle.geometry
    tilt = 2.0e-7 * np.asarray(geo.x_m) / 1.0
    tilt = np.where(np.asarray(geo.pupil_mask), tilt, 0.0)

    def response(sensor) -> np.ndarray:
        return np.nan_to_num(sensor.measure(tilt, random_streams=streams, include_noise=False).vector.values[0::2])

    background_free = response(no_sky)
    assert np.allclose(response(oracle), background_free, rtol=1e-6, atol=1e-9)
    # The raw readout keeps the pedestal and its centre of gravity shrinks.
    assert np.all(np.abs(response(raw)) < 0.9 * np.abs(background_free))


def test_bad_pixels_mask_without_losing_a_usable_centroid_and_invalid_when_all_masked() -> None:
    sensor, streams = build(physical(camera(dead_pixel_fraction=0.05)))
    measurement = sensor.measure(np.zeros(sensor.geometry.pupil_shape), random_streams=streams, include_noise=False)
    telemetry = measurement.detector_telemetry
    assert np.all(telemetry.masked_pixel_fraction > 0.0)
    assert np.all(np.isfinite(telemetry.centroids_xy_px))
    interpolated, streams2 = build(physical(camera(dead_pixel_fraction=0.05), proc=processing(bad_pixel_policy="interpolate_mean4")))
    values = interpolated.measure(np.zeros(sensor.geometry.pupil_shape), random_streams=streams2, include_noise=False).vector.values
    assert np.all(np.isfinite(values))
    # A block whose window is entirely masked gives an explicit invalid row.
    products = sensor.calibration_products
    bad = np.array(products.bad)
    bad[0] = True
    masked = replace(products, bad=bad)
    blind = PhysicalShackHartmannSensor(
        optics_backend=sensor.optics_backend,
        geometry=sensor.geometry,
        config=sensor.physical_config,
        wfs_wavelength_m=WAVELENGTH,
        layout=sensor.layout,
        maps=sensor.camera_maps,
        products=masked,
        detected_e_per_subap=sensor.detected_e_per_subap,
        sky_e_per_pixel=sensor.sky_e_per_pixel,
        reference_centroids_px=sensor.reference_centroids_px,
        centroid_config=sensor.centroid_config,
        validity_config=sensor.validity_config,
        calibration_realization_index=0,
    )
    result = blind.measure(np.zeros(sensor.geometry.pupil_shape), random_streams=streams, include_noise=False)
    assert not result.valid_subapertures[0]
    assert np.all(np.isnan(result.vector.values[:2]))
    assert np.all(result.valid_subapertures[1:])
    assert result.detector_telemetry.masked_pixel_fraction[0] == 1.0


def test_every_pixel_dead_fails_closed_at_calibration() -> None:
    with pytest.raises(ValueError):
        build(physical(camera(dead_pixel_fraction=1.0)))


def test_a_faint_lenslet_reports_a_non_negative_expected_flux() -> None:
    # At a few electrons the measured processed window sum is often negative.
    sensor, streams = build(physical(proc=processing("oracle"), magnitude=15.0, sky=None))
    zero = np.zeros(sensor.geometry.pupil_shape)
    for _ in range(20):
        telemetry = sensor.measure(zero, random_streams=streams, include_noise=True).detector_telemetry
        assert np.all(telemetry.fluxes_e >= 0.0)


def test_a_calibration_source_decouples_calibration_from_the_operating_flux() -> None:
    source = 5.0e4

    def with_source(magnitude: float) -> PhysicalDetectorConfig:
        config = physical(proc=processing("oracle"), magnitude=magnitude, sky=None)
        return replace(config, calibration_source_detected_e_per_full_subap_frame=source)

    bright, streams = build(with_source(6.0))
    faint, _ = build(with_source(12.0))
    # The reference path observes the internal source, not the star.
    np.testing.assert_allclose(bright.reference_centroids_px, faint.reference_centroids_px, rtol=0, atol=1e-12)
    assert bright.response_hash == faint.response_hash
    assert bright.noisy_response_hash != faint.noisy_response_hash
    # Noisy frames still see the operating budgets.
    zero = np.zeros(bright.geometry.pupil_shape)
    expected = [
        sensor.measure(zero, random_streams=streams, include_noise=True).detector_telemetry.detector_frames[4].expected_source_e.sum()
        for sensor in (bright, faint)
    ]
    assert expected[0] / expected[1] == pytest.approx(10 ** (0.4 * 6.0), rel=1e-12)
    # Without a source, the reference follows the operating flux.
    plain, _ = build(physical(proc=processing("oracle"), magnitude=6.0, sky=None))
    assert plain.response_hash != bright.response_hash
