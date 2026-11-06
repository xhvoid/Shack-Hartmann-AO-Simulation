"""Background over-subtraction invalidates one lenslet, not the whole frame.

The fixture is a 1 m, 30-sample, 3x3-lenslet geometry with the frozen FFT
optics (pad 2), so the sensor calibrates in well under a second.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from shwfs_ao.backends.native.shwfs import NativeShackHartmannOptics
from shwfs_ao.core.random import NamedRandomStreams, with_detector_physics_domains
from shwfs_ao.detector.camera import CameraConfig
from shwfs_ao.detector.physical_config import (
    BandpassConfig,
    DetectorPlaneSamplingConfig,
    PhysicalDetectorConfig,
    SourceBudgetConfig,
)
from shwfs_ao.detector.processing import PixelProcessingConfig
from shwfs_ao.wfs.shack_hartmann.geometry import build_shack_hartmann_geometry
from shwfs_ao.wfs.shack_hartmann.physical_measurement import PhysicalShackHartmannSensor


WAVELENGTH = 7.0e-7


def _geometry():
    return build_shack_hartmann_geometry(
        telescope_diameter_m=1.0,
        pupil_shape=(30, 30),
        n_lenslets_across=3,
        min_fill_fraction=0.3,
        central_obstruction_ratio=0.0,
        spider_width_m=0.0,
    )


def _camera() -> CameraConfig:
    return CameraConfig(
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


def _physical() -> PhysicalDetectorConfig:
    return PhysicalDetectorConfig(
        camera=_camera(),
        layout_scheme="isolated_lenslet_blocks.v1",
        guard_px=0,
        source=SourceBudgetConfig(
            kind="ab_flat_fnu", ab_magnitude=6.0, throughput_excluding_qe=0.5,
            sky_ab_mag_per_arcsec2=19.0,
        ),
        bandpass=BandpassConfig(kind="monochromatic", band_min_m=5.5e-7, band_max_m=8.5e-7),
        sampling=DetectorPlaneSamplingConfig(kind="legacy_fft"),
        processing=PixelProcessingConfig(
            mode="estimated", n_bias_frames=8, n_dark_frames=8, n_sky_frames=8,
            n_flat_frames=8, flat_level_e=2000.0, hot_pixel_threshold_e=5.0,
        ),
        exposure_s=1.0e-3,
    )


def _build(config: PhysicalDetectorConfig, *, window: int = 15, seed: int = 4):
    geometry = _geometry()
    optics = NativeShackHartmannOptics(
        geometry, WAVELENGTH, pad_factor=2, detector_window_px=window + 2 * config.guard_px
    )
    streams = with_detector_physics_domains(NamedRandomStreams(seed))
    sensor = PhysicalShackHartmannSensor.calibrate(
        geometry, optics, config, wfs_wavelength_m=WAVELENGTH, random_streams=streams
    )
    return sensor, streams


def test_background_oversubtraction_invalidates_only_the_affected_lenslet() -> None:
    sensor, streams = _build(_physical())
    zero = np.zeros(sensor.geometry.pupil_shape)
    reference = sensor.measure(zero, random_streams=streams, include_noise=False)
    products = sensor.calibration_products
    background = np.array(products.background_raw)
    # A biased background master exceeds the source in one window. The other
    # windows and all physical camera/noise parameters are unchanged.
    background[0] += (
        2.0 * np.max(sensor.detected_e_per_subap)
        / np.min(products.conversion_input_e_per_raw)
    )
    oversubtracted = PhysicalShackHartmannSensor(
        optics_backend=sensor.optics_backend,
        geometry=sensor.geometry,
        config=sensor.physical_config,
        wfs_wavelength_m=WAVELENGTH,
        layout=sensor.layout,
        maps=sensor.camera_maps,
        products=replace(products, background_raw=background),
        detected_e_per_subap=sensor.detected_e_per_subap,
        sky_e_per_pixel=sensor.sky_e_per_pixel,
        reference_centroids_px=sensor.reference_centroids_px,
        centroid_config=sensor.centroid_config,
        validity_config=sensor.validity_config,
        calibration_realization_index=0,
    )
    result = oversubtracted.measure(zero, random_streams=streams, include_noise=False)
    telemetry = result.detector_telemetry
    assert not result.valid_subapertures[0]
    assert not telemetry.valid_by_flux[0]
    assert not telemetry.uncertainty_supported[0]
    assert telemetry.fluxes_e[0] == 0.0
    assert telemetry.total_snr[0] == 0.0
    assert np.all(np.isnan(result.vector.values[:2]))
    np.testing.assert_array_equal(result.vector.valid_rows[2:], reference.vector.valid_rows[2:])
    np.testing.assert_array_equal(result.vector.values[2:], reference.vector.values[2:])
    np.testing.assert_array_equal(
        telemetry.total_snr[1:], reference.detector_telemetry.total_snr[1:]
    )
