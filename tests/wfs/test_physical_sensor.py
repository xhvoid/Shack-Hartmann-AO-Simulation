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
    without_sky_master,
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
    # With the ADC on, read noise dithers the reference quantizer and moves
    # the response identity (review R1); with the ADC off it moves only the
    # noisy response.
    read_noise, _ = build(physical(camera(read_noise_e=6.0), proc=oracle))
    assert read_noise.response_hash != base.response_hash
    assert read_noise.camera_maps.realization_hash == base.camera_maps.realization_hash
    assert read_noise.noisy_response_hash != base.noisy_response_hash
    analog, _ = build(physical(camera(adc_bits=None), proc=oracle))
    analog_read_noise, _ = build(physical(camera(adc_bits=None, read_noise_e=6.0), proc=oracle))
    assert analog_read_noise.response_hash == analog.response_hash
    assert analog_read_noise.noisy_response_hash != analog.noisy_response_hash
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



# -- Review 2026-10-16: R1 (response identity) and R3 (calibration source sky) --


def _tilt_response(sensor: PhysicalShackHartmannSensor, streams) -> np.ndarray:
    tilt = np.where(sensor.geometry.pupil_mask, 1.0e-7 * sensor.geometry.x_m, 0.0)
    telemetry = sensor.measure(tilt, random_streams=streams, include_noise=False).detector_telemetry
    return telemetry.centroids_xy_px - telemetry.reference_centroids_xy_px


@pytest.mark.parametrize("adc_bits", [12, None], ids=["adc_on", "adc_off"])
def test_equal_response_identities_mean_equal_reference_responses(adc_bits: int | None) -> None:
    # Fixed maps and products; only the read noise differs.  With the ADC on
    # the dithered reference quantizer changes, and so must the identity; with
    # the ADC off neither changes (review R1).
    cam = camera(
        adc_bits=adc_bits, read_noise_e=0.0, dark_e_per_s=0.0, hot_pixel_fraction=0.0,
        hot_pixel_dark_e_per_s=0.0, prnu_rms=0.0, dead_pixel_fraction=0.0,
        conversion_gain_e_per_adu=100.0, bias_adu=100.0, offset_map_rms_adu=0.0,
    )
    base = physical(cam, proc=processing("oracle"), magnitude=6.0, sky=None)
    quiet, streams = build(base)
    noisy, noisy_streams = build(
        replace(base, camera=replace(cam, read_noise_e=100.0)), products=quiet.calibration_products
    )
    zero = np.zeros(quiet.geometry.pupil_shape)
    raw = [
        np.stack([f.raw_image for f in s.measure(zero, random_streams=r, include_noise=False).detector_telemetry.detector_frames])
        for s, r in ((quiet, streams), (noisy, noisy_streams))
    ]
    responses = [_tilt_response(quiet, streams), _tilt_response(noisy, noisy_streams)]
    if adc_bits is None:
        assert quiet.response_hash == noisy.response_hash
        np.testing.assert_array_equal(raw[0], raw[1])
        np.testing.assert_array_equal(responses[0], responses[1])
    else:
        assert quiet.response_hash != noisy.response_hash
        assert float(np.max(np.abs(raw[0] - raw[1]))) > 0.1
        assert float(np.max(np.abs(responses[0] - responses[1]))) > 0.01


def test_a_calibration_source_reference_subtracts_bias_and_dark_but_no_sky() -> None:
    # The internal source is observed without sky, so its frames must not have
    # the operating sky master subtracted (review R3): a linear, noiseless,
    # oracle camera returns exactly the source.
    linear = camera(
        adc_bits=None, read_noise_e=0.0, full_well_e=1.0e9, dark_e_per_s=0.0, hot_pixel_fraction=0.0,
        hot_pixel_dark_e_per_s=0.0, prnu_rms=0.0, dead_pixel_fraction=0.0,
        conversion_gain_e_per_adu=1.0, bias_adu=0.0, offset_map_rms_adu=0.0,
    )
    config = replace(
        physical(linear, proc=processing("oracle"), magnitude=6.0, sky=12.0),
        calibration_source_detected_e_per_full_subap_frame=5.0e4,
    )
    sensor, streams = build(config)
    assert float(np.min(sensor.sky_e_per_pixel)) > 0.1
    zero = np.zeros(sensor.geometry.pupil_shape)
    reference = sensor.measure(zero, random_streams=streams, include_noise=False)
    for frame in reference.detector_telemetry.detector_frames:
        np.testing.assert_allclose(frame.image_e, frame.expected_source_e, rtol=0.0, atol=1e-9)
        assert frame.calibration_products_hash != sensor.calibration_products.content_hash
    # Operating frames observe star and sky and still subtract the sky master.
    operating = sensor.measure(zero, random_streams=streams, include_noise=True)
    frame = operating.detector_telemetry.detector_frames[4]
    assert frame.calibration_products_hash == sensor.calibration_products.content_hash
    residual = frame.image_e - frame.expected_source_e
    assert abs(float(np.mean(residual))) < 3.0 * math.sqrt(float(np.mean(frame.expected_pre_poisson_e)) / residual.size)


def test_estimated_products_with_a_calibration_source_keep_the_sky_out_of_the_reference() -> None:
    # Estimated masters: the reference image equals the source plus only the
    # bias and dark master errors, never minus the sky level.
    config = replace(
        physical(proc=processing("estimated"), magnitude=6.0, sky=12.0),
        calibration_source_detected_e_per_full_subap_frame=5.0e4,
    )
    sensor, streams = build(config)
    products = sensor.calibration_products
    assert products.sky_raw is not None
    frame = sensor.measure(
        np.zeros(sensor.geometry.pupil_shape), random_streams=streams, include_noise=False
    ).detector_telemetry.detector_frames[4]
    without_sky = without_sky_master(products)
    block = np.array([4])
    expected = process_frames(frame.raw_image[None], without_sky, config.processing, indices=block)[0]
    np.testing.assert_array_equal(frame.image_e, expected)
    assert frame.calibration_products_hash == without_sky.content_hash
    # Against the operating products, the only difference on live pixels is
    # the sky master, which the reference no longer loses.
    with_sky = process_frames(frame.raw_image[None], products, config.processing, indices=block)[0]
    live = ~frame.bad_pixel_mask
    sky_master_e = products.sky_raw[4] * products.conversion_input_e_per_raw[4] / products.flat[4]
    np.testing.assert_allclose((frame.image_e - with_sky)[live], sky_master_e[live], rtol=0.0, atol=1e-9)


def test_the_operating_expectation_observes_the_star_not_the_calibration_source() -> None:
    # measure(include_noise=False) is the calibration observation (the
    # internal source); the operating expectation is the noiseless star.
    config = replace(
        physical(proc=processing("estimated"), magnitude=6.0, sky=12.0),
        calibration_source_detected_e_per_full_subap_frame=5.0e4,
    )
    sensor, streams = build(config)
    zero = np.zeros(sensor.geometry.pupil_shape)
    noisy = sensor.measure(zero, random_streams=streams, include_noise=True).detector_telemetry
    calibration = sensor.measure(zero, random_streams=streams, include_noise=False).detector_telemetry
    expectation = sensor.measure_operating_expectation((zero,), random_streams=streams).detector_telemetry
    star = np.array([frame.expected_source_e.sum() for frame in noisy.detector_frames])
    np.testing.assert_allclose([frame.expected_source_e.sum() for frame in expectation.detector_frames], star, rtol=1e-12)
    assert not np.allclose([frame.expected_source_e.sum() for frame in calibration.detector_frames], star)
    for frame in expectation.detector_frames:
        assert frame.calibration_products_hash == sensor.calibration_products.content_hash
    # Noiseless: the same exposure twice is identical, whatever the streams.
    again = sensor.measure_operating_expectation((zero,), random_streams=streams).detector_telemetry
    np.testing.assert_array_equal(again.centroids_xy_px, expectation.centroids_xy_px)


# -- S4 traced telemetry (T1, 2026-10-20): per-axis model sigma and expected centroids --


def _independent_cog(windows: np.ndarray) -> np.ndarray:
    """A plain centre of gravity written apart from the sensor's helper."""

    result = np.full((windows.shape[0], 2), math.nan)
    for index, window in enumerate(windows):
        total = float(np.sum(window))
        if not total > 0.0:
            continue
        rows, columns = np.indices(window.shape)
        result[index, 0] = float(np.sum(window * columns)) / total
        result[index, 1] = float(np.sum(window * rows)) / total
    return result


def test_expected_centroids_are_the_plain_cog_of_the_expected_processed_window() -> None:
    sensor, streams = build(physical())
    geometry_ = sensor.geometry
    tilt = np.where(np.asarray(geometry_.pupil_mask), 3.0e-7 * np.asarray(geometry_.x_m), 0.0)
    measurement = sensor.measure(tilt, random_streams=streams, include_noise=True)
    telemetry = measurement.detector_telemetry
    assert telemetry.expected_centroids_xy_px is not None and telemetry.centroid_sigma_xy_px is not None
    # The gates' expected frame, computed apart from the measurement path.
    quality = sensor.noise_model(tilt)
    rows, cols = sensor.layout.window_slice
    expected = _independent_cog(np.asarray(quality.expected_processed_e)[:, rows, cols])
    np.testing.assert_allclose(telemetry.expected_centroids_xy_px, expected, rtol=0.0, atol=1.0e-12)
    # The per-axis model sigma is the gates' own, NaN where the model does not
    # support the lenslet; the scalar sigma keeps its undefined-sentinel rule.
    supported = np.asarray(quality.supported, dtype=bool)
    assert np.all(supported == telemetry.uncertainty_supported)
    np.testing.assert_array_equal(
        telemetry.centroid_sigma_xy_px[supported], np.asarray(quality.centroid_sigma_xy_px)[supported]
    )
    assert np.all(np.isnan(telemetry.centroid_sigma_xy_px[~supported]))
    assert np.all(np.isfinite(telemetry.centroid_sigma_xy_px[supported]))
    # Same window coordinates as the measured centroid: the noiseless operating
    # expectation measures the expected frame itself, so its centroid equals
    # the expected centroid up to the ADC quantization of the noiseless frame.
    expectation = sensor.measure_operating_expectation((tilt,), random_streams=streams).detector_telemetry
    valid = expectation.valid_subapertures
    assert np.any(valid)
    np.testing.assert_allclose(
        expectation.centroids_xy_px[valid], expectation.expected_centroids_xy_px[valid], rtol=0.0, atol=0.01
    )
    # The noisy centroid residual is of the order of the model sigma, not of
    # the centroid itself (a coordinate-convention mismatch would be pixels).
    residual = telemetry.centroids_xy_px[valid] - telemetry.expected_centroids_xy_px[valid]
    assert np.all(np.abs(residual) < 8.0 * telemetry.centroid_sigma_xy_px[valid])


def test_expected_centroids_are_none_for_a_thresholded_estimator_and_nan_for_a_zero_window() -> None:
    from shwfs_ao.detector.centroid import CentroidConfig
    from shwfs_ao.wfs.shack_hartmann.physical_measurement import _window_centroids

    thresholded = CentroidConfig(estimator="thresholded_center_of_gravity", threshold_fraction=0.2)
    sensor, streams = build(physical(), centroid_config=thresholded)
    zero = np.zeros(sensor.geometry.pupil_shape)
    telemetry = sensor.measure(zero, random_streams=streams, include_noise=True).detector_telemetry
    assert telemetry.expected_centroids_xy_px is None  # explicitly unavailable, never a fabricated value
    # The model does not support a thresholded estimator: every per-axis sigma is NaN.
    assert telemetry.centroid_sigma_xy_px is not None
    assert not np.any(telemetry.uncertainty_supported)
    assert np.all(np.isnan(telemetry.centroid_sigma_xy_px))
    # A zero-total window has no centroid.
    windows = np.zeros((2, 5, 5))
    windows[1, 2, 3] = 4.0
    result = _window_centroids(windows, CentroidConfig())
    assert np.all(np.isnan(result[0]))
    np.testing.assert_allclose(result[1], [3.0, 2.0])


def test_an_undefined_expected_centroid_never_refuses_a_measurement() -> None:
    """Independent review T1-01 (2026-10-20): the reviewer's zero-expectation fixture.

    A zero detected operating source with a positive internal calibration
    source, no background, read noise 1 e, ADC off, oracle processing and
    permissive gates: the expected processed windows total zero (no
    expected centroid) while the noisy realization has finite centroids that
    the gates keep.  The measurement must return as it did before the
    diagnostic existed, with NaN expectations where none is defined, both
    directly and through the observer snapshot the loop hands out.
    """

    from shwfs_ao.control.observation import immutable_detector_telemetry
    from shwfs_ao.detector.physical_config import SourceBudgetConfig
    from shwfs_ao.detector.validity import CentroidValidityConfig

    config = physical(
        camera(
            adc_bits=None, read_noise_e=1.0, dark_e_per_s=0.0, hot_pixel_fraction=0.0,
            hot_pixel_dark_e_per_s=0.0, prnu_rms=0.0, dead_pixel_fraction=0.0, offset_map_rms_adu=0.0,
        ),
        proc=processing("oracle"),
        sky=None,
    )
    config = replace(
        config,
        source=SourceBudgetConfig(kind="detected_electrons", detected_e_per_full_subap_frame=0.0),
        calibration_source_detected_e_per_full_subap_frame=10000.0,
    )
    permissive = CentroidValidityConfig(
        min_flux_e=0.0, min_peak_snr=0.0, max_centroid_sigma_px=1.0e6, max_window_clipping_fraction=1.0
    )
    sensor, streams = build(config, seed=4, validity_config=permissive)
    zero = np.zeros(sensor.geometry.pupil_shape)
    quality = sensor.noise_model(zero)
    assert np.all(np.asarray(quality.total_flux_e) == 0.0) and not np.any(quality.supported)
    measurement = sensor.measure(zero, random_streams=streams, include_noise=True)
    telemetry = measurement.detector_telemetry
    valid = np.asarray(measurement.valid_subapertures, dtype=bool)
    assert np.count_nonzero(valid) == 5 and np.count_nonzero(measurement.vector.valid_rows) == 10
    assert np.all(np.isfinite(measurement.vector.values[measurement.vector.valid_rows]))
    # The diagnostics say "undefined" on their own terms and gate nothing.
    assert np.all(np.isnan(telemetry.expected_centroids_xy_px))
    assert np.all(np.isnan(telemetry.centroid_sigma_xy_px))
    np.testing.assert_array_equal(telemetry.valid_subapertures, valid)
    snapshot = immutable_detector_telemetry(telemetry)  # the active-observer path
    assert np.all(np.isnan(snapshot.expected_centroids_xy_px)) and snapshot.valid_subapertures.sum() == 5
