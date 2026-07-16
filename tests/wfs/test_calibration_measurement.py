from __future__ import annotations

import ast
from dataclasses import fields, replace
from pathlib import Path

import numpy as np
import pytest

from shwfs_ao.backends.native.shwfs import NativeShackHartmannOptics
from shwfs_ao.core.hashing import stable_hash
from shwfs_ao.core.protocols import WavefrontSensor
from shwfs_ao.core.random import NamedRandomStreams
from shwfs_ao.core.types import SpotIntensityResult
from shwfs_ao.detector.centroid import CentroidConfig
from shwfs_ao.detector.config import DetectorConfig
from shwfs_ao.detector.random import DetectorRealization
from shwfs_ao.detector.validity import CentroidValidityConfig
from shwfs_ao.legacy.reconstruction import numerical_gradient as legacy_gradient
from shwfs_ao.wfs.shack_hartmann.calibration import (
    ShackHartmannCalibration,
    ShackHartmannCalibrationError,
    calibrate_zero_phase_reference,
    shack_hartmann_calibration_hash,
)
from shwfs_ao.wfs.shack_hartmann.geometric import (
    GeometricShackHartmannCalibration,
    NativeGeometricShackHartmannSensor,
    mean_subaperture_slopes,
    numerical_gradient,
)
from shwfs_ao.wfs.shack_hartmann.geometry import (
    ShackHartmannGeometry,
    build_shack_hartmann_geometry,
)
from shwfs_ao.wfs.shack_hartmann.measurement import (
    DetectorShackHartmannSensor,
    ShackHartmannMeasurementError,
)
from shwfs_ao.wfs.shack_hartmann.optics import make_detector_plane_sampling


WAVELENGTH_M = 700.0e-9


@pytest.fixture(scope="module")
def geometry() -> ShackHartmannGeometry:
    return build_shack_hartmann_geometry(
        telescope_diameter_m=1.0,
        pupil_shape=(32, 32),
        n_lenslets_across=4,
        min_fill_fraction=0.4,
    )


@pytest.fixture()
def native_backend(geometry: ShackHartmannGeometry) -> NativeShackHartmannOptics:
    return NativeShackHartmannOptics(
        geometry,
        WAVELENGTH_M,
        pad_factor=4,
        detector_window_px=14,
    )


def _validity(**overrides: float) -> CentroidValidityConfig:
    values = {
        "min_flux_e": 0.0,
        "min_peak_snr": 0.0,
        "max_centroid_sigma_px": 1.0e6,
        "max_window_clipping_fraction": 1.0,
    }
    values.update(overrides)
    return CentroidValidityConfig(**values)


class AlternateBackend:
    """Contract-conforming backend double with controllable boundary faults."""

    backend_name = "alternate-test-double"

    def __init__(
        self,
        wrapped: NativeShackHartmannOptics,
        *,
        capture_fraction: float | None = None,
    ) -> None:
        self.geometry = wrapped.geometry
        self.wfs_wavelength_m = wrapped.wfs_wavelength_m
        self._wrapped = wrapped
        self.capture_fraction = capture_fraction
        self.mode = "valid"
        self._config_hash = stable_hash(
            {
                "wrapped": wrapped.config_hash,
                "capture_fraction": capture_fraction,
            },
            namespace="alternate_shwfs_backend",
        )

    @property
    def config_hash(self) -> str:
        return self._config_hash

    def spot_intensities(self, residual_opd_m: np.ndarray) -> SpotIntensityResult:
        result = self._wrapped.spot_intensities(residual_opd_m)
        if self.capture_fraction is not None:
            result = replace(
                result,
                relative_throughput=np.full(
                    len(result.subaperture_ids),
                    self.capture_fraction,
                ),
            )
        if self.mode == "missing":
            return SpotIntensityResult(
                unit_sum_spots=result.unit_sum_spots[:-1],
                subaperture_ids=result.subaperture_ids[:-1],
                relative_throughput=result.relative_throughput[:-1],
                x_px=result.x_px[:-1],
                y_px=result.y_px[:-1],
                sampling=result.sampling,
                normalization=result.normalization,
            )
        if self.mode == "reordered":
            order = tuple(reversed(range(len(result.subaperture_ids))))
            return SpotIntensityResult(
                unit_sum_spots=tuple(result.unit_sum_spots[i] for i in order),
                subaperture_ids=tuple(result.subaperture_ids[i] for i in order),
                relative_throughput=result.relative_throughput[list(order)],
                x_px=tuple(result.x_px[i] for i in order),
                y_px=tuple(result.y_px[i] for i in order),
                sampling=result.sampling,
                normalization=result.normalization,
            )
        if self.mode == "sampling":
            # Build a same-shape sampling with a distinct physical scale/hash.
            altered = make_detector_plane_sampling(
                window_shape_px=result.sampling.window_shape_px,
                pixel_scale_rad=(
                    2.0 * result.sampling.pixel_scale_rad[0],
                    result.sampling.pixel_scale_rad[1],
                ),
                reference_pixel_xy=result.sampling.reference_pixel_xy,
            )
            return replace(result, sampling=altered)
        return result


def test_calibration_has_exact_rows_hash_inputs_and_immutable_reference(
    geometry: ShackHartmannGeometry,
    native_backend: NativeShackHartmannOptics,
) -> None:
    streams = NamedRandomStreams(81)
    detector = DetectorConfig(
        photons_per_subap_frame=2_000.0,
        prnu_mode="persistent",
        prnu_rms=0.02,
    )
    sensor = DetectorShackHartmannSensor.calibrate(
        geometry,
        native_backend,
        detector,
        wfs_wavelength_m=WAVELENGTH_M,
        random_streams=streams,
        centroid_config=CentroidConfig(),
        validity_config=_validity(),
    )
    calibration = sensor.calibration

    assert tuple(item.name for item in fields(ShackHartmannCalibration)) == (
        "geometry",
        "reference_centroids_px",
        "wfs_wavelength_m",
        "subaperture_ids",
        "row_ids",
        "measurement_unit",
        "detector_sampling",
        "detector_config",
        "centroid_config",
        "detector_realization_hash",
        "config_hash",
        "provenance",
    )
    assert calibration.subaperture_ids == geometry.subaperture_ids
    assert calibration.row_ids == geometry.row_ids
    assert calibration.measurement_unit == "pixel"
    assert calibration.detector_realization_hash == (
        sensor.detector_realization.realization_hash
    )
    assert not calibration.reference_centroids_px.flags.writeable
    with pytest.raises(ValueError):
        calibration.reference_centroids_px.setflags(write=True)
    with pytest.raises(ShackHartmannCalibrationError, match="config_hash"):
        replace(calibration, wfs_wavelength_m=1.01 * WAVELENGTH_M)


def test_calibration_hash_covers_every_ticket_identity_input(
    geometry: ShackHartmannGeometry,
    native_backend: NativeShackHartmannOptics,
) -> None:
    streams = NamedRandomStreams(810)
    sensor = DetectorShackHartmannSensor.calibrate(
        geometry,
        native_backend,
        DetectorConfig(
            photons_per_subap_frame=1_000.0,
            prnu_mode="persistent",
            prnu_rms=0.01,
        ),
        wfs_wavelength_m=WAVELENGTH_M,
        random_streams=streams,
        validity_config=_validity(),
    )
    calibration = sensor.calibration
    common = {
        "geometry": calibration.geometry,
        "reference_centroids_px": calibration.reference_centroids_px,
        "wfs_wavelength_m": calibration.wfs_wavelength_m,
        "subaperture_ids": calibration.subaperture_ids,
        "row_ids": calibration.row_ids,
        "detector_sampling": calibration.detector_sampling,
        "detector_config": calibration.detector_config,
        "centroid_config": calibration.centroid_config,
        "detector_realization_hash": calibration.detector_realization_hash,
        "provenance": calibration.provenance,
    }
    altered_geometry = build_shack_hartmann_geometry(
        telescope_diameter_m=1.1,
        pupil_shape=geometry.pupil_shape,
        n_lenslets_across=geometry.n_lenslets_across,
        min_fill_fraction=0.4,
    )
    assert altered_geometry.subaperture_ids == geometry.subaperture_ids
    altered_sampling = make_detector_plane_sampling(
        window_shape_px=calibration.detector_sampling.window_shape_px,
        pixel_scale_rad=(
            1.01 * calibration.detector_sampling.pixel_scale_rad[0],
            calibration.detector_sampling.pixel_scale_rad[1],
        ),
        reference_pixel_xy=calibration.detector_sampling.reference_pixel_xy,
    )
    altered_reference = np.array(calibration.reference_centroids_px, copy=True)
    altered_reference[0, 0] += 0.125
    altered_rows = list(calibration.row_ids)
    altered_rows[0], altered_rows[1] = altered_rows[1], altered_rows[0]

    perturbations = (
        {"geometry": altered_geometry},
        {"detector_sampling": altered_sampling},
        {"wfs_wavelength_m": 1.01 * calibration.wfs_wavelength_m},
        {"row_ids": tuple(altered_rows)},
        {
            "detector_realization_hash": (
                calibration.detector_realization_hash + "-altered"
            )
        },
        {"reference_centroids_px": altered_reference},
    )
    baseline = shack_hartmann_calibration_hash(**common)
    assert baseline == calibration.config_hash
    for perturbation in perturbations:
        assert shack_hartmann_calibration_hash(
            **(common | perturbation)
        ) != baseline


def test_persistent_zero_reference_reuses_fixed_response_and_capture_once(
    geometry: ShackHartmannGeometry,
    native_backend: NativeShackHartmannOptics,
) -> None:
    streams = NamedRandomStreams(14)
    detector = DetectorConfig(
        photons_per_subap_frame=1_000.0,
        qe=0.8,
        prnu_mode="persistent",
        prnu_rms=0.03,
    )
    sensor = DetectorShackHartmannSensor.calibrate(
        geometry,
        native_backend,
        detector,
        wfs_wavelength_m=WAVELENGTH_M,
        random_streams=streams,
        validity_config=_validity(),
    )
    measured = sensor.measure(
        np.zeros(geometry.pupil_shape),
        random_streams=streams,
        include_noise=False,
    )
    telemetry = measured.detector_telemetry
    assert telemetry is not None
    assert np.all(measured.vector.valid_rows)
    assert np.allclose(measured.vector.values, 0.0, atol=1.0e-14)
    for index, frame in enumerate(telemetry.detector_frames or ()):
        capture = telemetry.optical_spots.relative_throughput[index]
        assert np.sum(frame.expected_source_e) == pytest.approx(
            detector.photons_per_subap_frame * detector.qe * capture
        )
        assert np.array_equal(
            frame.prnu_response,
            sensor.detector_realization.prnu_response,
        )
        assert telemetry.clipping_fraction[index] == pytest.approx(1.0 - capture)


def test_legacy_calibration_is_keyed_and_does_not_advance_runtime_domains(
    geometry: ShackHartmannGeometry,
    native_backend: NativeShackHartmannOptics,
) -> None:
    streams = NamedRandomStreams(92)
    control = NamedRandomStreams(92)
    detector = DetectorConfig(
        photons_per_subap_frame=2_000.0,
        prnu_mode="per_frame_legacy",
        prnu_rms=0.04,
    )
    sensor = DetectorShackHartmannSensor.calibrate(
        geometry,
        native_backend,
        detector,
        wfs_wavelength_m=WAVELENGTH_M,
        random_streams=streams,
        validity_config=_validity(),
    )

    assert streams.generator("detector.shot_noise").integers(0, 2**31) == (
        control.generator("detector.shot_noise").integers(0, 2**31)
    )
    references = sensor.calibration.provenance.references
    assert any(item.startswith("calibration_random_scope=") for item in references)
    assert sum(
        item.startswith("calibration_random_stream_id=") for item in references
    ) == len(geometry.subaperture_ids)

    measured = sensor.measure(
        np.zeros(geometry.pupil_shape),
        random_streams=streams,
        include_noise=False,
    )
    assert np.allclose(measured.vector.values, 0.0, atol=1.0e-14)


def test_zero_prnu_legacy_calibration_has_no_random_scope_metadata(
    geometry: ShackHartmannGeometry,
    native_backend: NativeShackHartmannOptics,
) -> None:
    sensor = DetectorShackHartmannSensor.calibrate(
        geometry,
        native_backend,
        DetectorConfig(
            photons_per_subap_frame=500.0,
            prnu_mode="per_frame_legacy",
            prnu_rms=0.0,
        ),
        wfs_wavelength_m=WAVELENGTH_M,
        random_streams=NamedRandomStreams(93),
        validity_config=_validity(),
    )
    references = sensor.calibration.provenance.references
    assert not any(item.startswith("calibration_random_") for item in references)
    assert not any(item.startswith("calibration_legacy_seed=") for item in references)


def test_photonless_ideal_telemetry_preserves_not_applicable_snr(
    geometry: ShackHartmannGeometry,
    native_backend: NativeShackHartmannOptics,
) -> None:
    streams = NamedRandomStreams(94)
    sensor = DetectorShackHartmannSensor.calibrate(
        geometry,
        native_backend,
        DetectorConfig(
            photons_per_subap_frame=None,
            prnu_mode="persistent",
        ),
        wfs_wavelength_m=WAVELENGTH_M,
        random_streams=streams,
        validity_config=_validity(),
    )
    measured = sensor.measure(
        np.zeros(geometry.pupil_shape),
        random_streams=streams,
        include_noise=False,
    )
    telemetry = measured.detector_telemetry
    assert telemetry is not None
    assert np.all(telemetry.valid_by_snr)
    assert np.all(np.isnan(telemetry.peak_snr))
    assert np.all(np.isnan(telemetry.total_snr))
    assert np.all(measured.vector.valid_rows)


def test_alternate_backend_is_consumed_and_applies_capture_fraction(
    geometry: ShackHartmannGeometry,
    native_backend: NativeShackHartmannOptics,
) -> None:
    alternate = AlternateBackend(native_backend, capture_fraction=0.5)
    streams = NamedRandomStreams(9)
    detector = DetectorConfig(
        photons_per_subap_frame=200.0,
        qe=0.8,
        prnu_mode="persistent",
    )
    sensor = DetectorShackHartmannSensor.calibrate(
        geometry,
        alternate,
        detector,
        wfs_wavelength_m=WAVELENGTH_M,
        random_streams=streams,
        validity_config=_validity(),
    )
    measured = sensor.measure(
        np.zeros(geometry.pupil_shape),
        random_streams=streams,
        include_noise=False,
    )
    frame = measured.detector_telemetry.detector_frames[0]
    assert np.sum(frame.expected_source_e) == pytest.approx(80.0)
    assert isinstance(sensor, WavefrontSensor)


@pytest.mark.parametrize("mode", ["missing", "reordered"])
def test_alternate_backend_bad_ids_fail_at_calibration_boundary(
    mode: str,
    geometry: ShackHartmannGeometry,
    native_backend: NativeShackHartmannOptics,
) -> None:
    alternate = AlternateBackend(native_backend)
    alternate.mode = mode
    with pytest.raises(ShackHartmannMeasurementError, match="optics result"):
        DetectorShackHartmannSensor.calibrate(
            geometry,
            alternate,
            DetectorConfig(photons_per_subap_frame=100.0),
            wfs_wavelength_m=WAVELENGTH_M,
            random_streams=NamedRandomStreams(2),
        )


def test_runtime_sampling_change_fails_at_backend_boundary(
    geometry: ShackHartmannGeometry,
    native_backend: NativeShackHartmannOptics,
) -> None:
    alternate = AlternateBackend(native_backend)
    streams = NamedRandomStreams(5)
    sensor = DetectorShackHartmannSensor.calibrate(
        geometry,
        alternate,
        DetectorConfig(photons_per_subap_frame=1_000.0),
        wfs_wavelength_m=WAVELENGTH_M,
        random_streams=streams,
        validity_config=_validity(),
    )
    alternate.mode = "sampling"
    with pytest.raises(ShackHartmannMeasurementError, match="sampling"):
        sensor.measure(
            np.zeros(geometry.pupil_shape),
            random_streams=streams,
            include_noise=False,
        )


def test_injected_zero_phase_spots_must_match_declared_backend_sampling(
    geometry: ShackHartmannGeometry,
    native_backend: NativeShackHartmannOptics,
) -> None:
    streams = NamedRandomStreams(501)
    detector = DetectorConfig(photons_per_subap_frame=500.0)
    realization = DetectorRealization.create(
        detector,
        native_backend.detector_sampling.window_shape_px,
        random_streams=streams,
    )
    spots = native_backend.spot_intensities(
        np.zeros(geometry.pupil_shape, dtype=float)
    )
    altered_sampling = make_detector_plane_sampling(
        window_shape_px=spots.sampling.window_shape_px,
        pixel_scale_rad=(
            1.1 * spots.sampling.pixel_scale_rad[0],
            spots.sampling.pixel_scale_rad[1],
        ),
        reference_pixel_xy=spots.sampling.reference_pixel_xy,
    )
    with pytest.raises(ShackHartmannCalibrationError, match="sampling"):
        calibrate_zero_phase_reference(
            geometry,
            native_backend,
            detector,
            CentroidConfig(),
            realization,
            wfs_wavelength_m=WAVELENGTH_M,
            random_streams=streams,
            zero_phase_spots=replace(spots, sampling=altered_sampling),
        )


def test_invalid_subaperture_marks_both_measurement_rows_invalid(
    geometry: ShackHartmannGeometry,
    native_backend: NativeShackHartmannOptics,
) -> None:
    streams = NamedRandomStreams(27)
    sensor = DetectorShackHartmannSensor.calibrate(
        geometry,
        native_backend,
        DetectorConfig(photons_per_subap_frame=200.0, prnu_mode="persistent"),
        wfs_wavelength_m=WAVELENGTH_M,
        random_streams=streams,
        validity_config=_validity(min_flux_e=1.0e12),
    )
    measured = sensor.measure(
        np.zeros(geometry.pupil_shape),
        random_streams=streams,
        include_noise=True,
    )
    assert not np.any(measured.valid_subapertures)
    assert not np.any(measured.vector.valid_rows)
    assert np.all(np.isnan(measured.vector.values))
    assert np.array_equal(
        measured.vector.valid_rows[0::2],
        measured.vector.valid_rows[1::2],
    )


def test_runtime_requires_realization_root_and_backend_identity(
    geometry: ShackHartmannGeometry,
    native_backend: NativeShackHartmannOptics,
) -> None:
    streams = NamedRandomStreams(33)
    alternate = AlternateBackend(native_backend)
    sensor = DetectorShackHartmannSensor.calibrate(
        geometry,
        alternate,
        DetectorConfig(photons_per_subap_frame=100.0, prnu_mode="persistent"),
        wfs_wavelength_m=WAVELENGTH_M,
        random_streams=streams,
        validity_config=_validity(),
    )
    with pytest.raises(ShackHartmannMeasurementError, match="root seed"):
        sensor.measure(
            np.zeros(geometry.pupil_shape),
            random_streams=NamedRandomStreams(34),
            include_noise=False,
        )
    alternate.backend_name = "mutated-name"
    with pytest.raises(ShackHartmannMeasurementError, match="name changed"):
        sensor.measure(
            np.zeros(geometry.pupil_shape),
            random_streams=streams,
            include_noise=False,
        )


def test_constructor_rejects_backend_name_and_calibration_seed_tampering(
    geometry: ShackHartmannGeometry,
    native_backend: NativeShackHartmannOptics,
) -> None:
    streams = NamedRandomStreams(502)
    detector = DetectorConfig(
        photons_per_subap_frame=500.0,
        prnu_mode="per_frame_legacy",
        prnu_rms=0.03,
    )
    sensor = DetectorShackHartmannSensor.calibrate(
        geometry,
        native_backend,
        detector,
        wfs_wavelength_m=WAVELENGTH_M,
        random_streams=streams,
        validity_config=_validity(),
    )
    renamed = AlternateBackend(native_backend)
    renamed._config_hash = native_backend.config_hash
    with pytest.raises(ShackHartmannMeasurementError, match="backend name"):
        DetectorShackHartmannSensor(
            renamed,
            sensor.calibration,
            sensor.detector_realization,
            validity_config=_validity(),
        )
    with pytest.raises(ShackHartmannMeasurementError, match="legacy seeds"):
        DetectorShackHartmannSensor(
            native_backend,
            sensor.calibration,
            sensor.detector_realization,
            validity_config=_validity(),
            calibration_legacy_seeds=(0,) * len(geometry.subaperture_ids),
        )


def test_noiseless_finite_photon_measurement_still_applies_quality_validity(
    geometry: ShackHartmannGeometry,
    native_backend: NativeShackHartmannOptics,
) -> None:
    streams = NamedRandomStreams(503)
    sensor = DetectorShackHartmannSensor.calibrate(
        geometry,
        native_backend,
        DetectorConfig(
            photons_per_subap_frame=0.1,
            prnu_mode="persistent",
        ),
        wfs_wavelength_m=WAVELENGTH_M,
        random_streams=streams,
        validity_config=_validity(min_peak_snr=1.0),
    )
    measured = sensor.measure(
        np.zeros(geometry.pupil_shape),
        random_streams=streams,
        include_noise=False,
    )
    telemetry = measured.detector_telemetry
    assert telemetry is not None
    assert not np.any(telemetry.valid_by_snr)
    assert not np.any(measured.valid_subapertures)
    assert not np.any(measured.vector.valid_rows)


def test_native_detector_measurement_has_positive_x_and_y_sign(
    geometry: ShackHartmannGeometry,
) -> None:
    backend = NativeShackHartmannOptics(
        geometry,
        WAVELENGTH_M,
        pad_factor=6,
        detector_window_px=20,
    )
    streams = NamedRandomStreams(18)
    sensor = DetectorShackHartmannSensor.calibrate(
        geometry,
        backend,
        DetectorConfig(photons_per_subap_frame=10_000.0, prnu_mode="persistent"),
        wfs_wavelength_m=WAVELENGTH_M,
        random_streams=streams,
        validity_config=_validity(),
    )
    x_measurement = sensor.measure(
        1.0e-6 * geometry.x_m,
        random_streams=streams,
        include_noise=False,
    )
    y_measurement = sensor.measure(
        1.0e-6 * geometry.y_m,
        random_streams=streams,
        include_noise=False,
    )
    assert np.nanmedian(x_measurement.vector.values[0::2]) > 0.0
    assert abs(np.nanmedian(x_measurement.vector.values[1::2])) < 1.0e-10
    assert np.nanmedian(y_measurement.vector.values[1::2]) > 0.0
    assert abs(np.nanmedian(y_measurement.vector.values[0::2])) < 1.0e-10


def test_geometric_sensor_preserves_masked_gradient_baseline_and_reference(
    geometry: ShackHartmannGeometry,
) -> None:
    wavefront = (
        1.5 * geometry.x_m**2
        - 0.5 * geometry.y_m**2
        + 0.25 * geometry.x_m * geometry.y_m
    )
    wavefront = np.where(geometry.pupil_mask, wavefront, np.nan)
    dx = abs(float(geometry.x_m[0, 1] - geometry.x_m[0, 0]))
    expected_x, expected_y = legacy_gradient(
        wavefront,
        dx,
        mask=geometry.pupil_mask,
    )
    actual_x, actual_y = numerical_gradient(
        wavefront,
        dx,
        mask=geometry.pupil_mask,
    )
    assert np.allclose(actual_x, expected_x, equal_nan=True)
    assert np.allclose(actual_y, expected_y, equal_nan=True)

    expected_slopes = np.asarray(
        [
            (np.nanmean(expected_x[mask]), np.nanmean(expected_y[mask]))
            for mask in geometry.subaperture_masks
        ]
    )
    assert np.allclose(
        mean_subaperture_slopes(
            actual_x,
            actual_y,
            geometry.subaperture_masks,
        ),
        expected_slopes,
    )
    reference = GeometricShackHartmannCalibration.from_reference(
        geometry,
        expected_slopes,
    )
    sensor = NativeGeometricShackHartmannSensor(reference)
    measured = sensor.measure(
        wavefront,
        random_streams=NamedRandomStreams(1),
        include_noise=False,
    )
    assert measured.vector.measurement_unit == "rad_wavefront_slope"
    assert measured.vector.row_ids == geometry.row_ids
    assert np.all(measured.vector.valid_rows)
    assert np.allclose(measured.vector.values, 0.0, atol=1.0e-13)
    assert measured.detector_telemetry is None


def test_geometric_sensor_positive_sign_and_no_camera_module_import(
    geometry: ShackHartmannGeometry,
) -> None:
    sensor = NativeGeometricShackHartmannSensor(geometry)
    measured = sensor.measure(
        2.0e-6 * geometry.x_m + 3.0e-6 * geometry.y_m,
        random_streams=NamedRandomStreams(6),
        include_noise=True,
    )
    assert np.allclose(measured.vector.values[0::2], 2.0e-6, atol=1.0e-16)
    assert np.allclose(measured.vector.values[1::2], 3.0e-6, atol=1.0e-16)

    source_path = Path(
        NativeGeometricShackHartmannSensor.__module__.replace(".", "/") + ".py"
    )
    repository_source = Path(__file__).parents[2] / "src" / source_path
    tree = ast.parse(repository_source.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    )
    assert not any("detector" in module for module in imported)


def test_geometric_sensor_supports_rectangular_pupil_sampling() -> None:
    geometry = build_shack_hartmann_geometry(
        telescope_diameter_m=1.0,
        pupil_shape=(24, 32),
        n_lenslets_across=4,
        min_fill_fraction=0.4,
    )
    sensor = NativeGeometricShackHartmannSensor(geometry)
    measured = sensor.measure(
        2.0e-6 * geometry.x_m + 3.0e-6 * geometry.y_m,
        random_streams=NamedRandomStreams(504),
        include_noise=False,
    )
    assert np.allclose(measured.vector.values[0::2], 2.0e-6, atol=1.0e-16)
    assert np.allclose(measured.vector.values[1::2], 3.0e-6, atol=1.0e-16)
