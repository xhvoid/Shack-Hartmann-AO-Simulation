"""AO-REF-016 contracts for the HCIPy Shack-Hartmann optical backend.

Every test requires the optional HCIPy dependency and carries the ``hcipy``
marker so native CI selections never execute it.  The module is part of the
portable wheel-smoke bundle, so it imports only the installed package.
"""

from __future__ import annotations

import json

import numpy as np
import pytest


hcipy = pytest.importorskip("hcipy")

from shwfs_ao.backends.hcipy.dm import build_hcipy_deformable_mirror
from shwfs_ao.backends.hcipy.shwfs import (
    HcipyShackHartmannError,
    HcipyShackHartmannOptics,
)
from shwfs_ao.backends.native.shwfs import NativeShackHartmannOptics
from shwfs_ao.core.protocols import ShackHartmannOpticsBackend, WavefrontSensor
from shwfs_ao.core.random import NamedRandomStreams
from shwfs_ao.core.types import SpotIntensityResult, WfsMeasurement
from shwfs_ao.detector.config import DetectorConfig
from shwfs_ao.dm import DMConfig
from shwfs_ao.wfs.shack_hartmann.geometry import (
    build_shack_hartmann_geometry,
    lenslet_indices_from_id,
    subaperture_id,
)
from shwfs_ao.wfs.shack_hartmann.measurement import (
    build_detector_shack_hartmann_sensor,
)
from shwfs_ao.wfs.shack_hartmann.optics import (
    ShackHartmannOpticsError,
    validate_spot_intensity_result,
)


pytestmark = pytest.mark.hcipy


WAVELENGTH_M = 700.0e-9
DIAMETER_M = 1.0
PUPIL_PIXELS = 64
LENSLETS_ACROSS = 4
SPOT_SAMPLING_PX = 4.0


def _geometry(
    pupil_pixels: int = PUPIL_PIXELS,
    lenslets_across: int = LENSLETS_ACROSS,
):
    return build_shack_hartmann_geometry(
        telescope_diameter_m=DIAMETER_M,
        pupil_shape=(pupil_pixels, pupil_pixels),
        n_lenslets_across=lenslets_across,
        min_fill_fraction=0.3,
    )


def _f_number(geometry, spot_sampling_px: float = SPOT_SAMPLING_PX) -> float:
    pixel_pitch_m = float(geometry.x_m[0, 1] - geometry.x_m[0, 0])
    return spot_sampling_px * pixel_pitch_m / WAVELENGTH_M


def _optics(geometry=None, **changes) -> HcipyShackHartmannOptics:
    resolved = _geometry() if geometry is None else geometry
    values = {"f_number": _f_number(resolved)}
    values.update(changes)
    return HcipyShackHartmannOptics(resolved, WAVELENGTH_M, **values)


def _interior_index(geometry) -> int:
    return geometry.subaperture_ids.index(subaperture_id(1, 1))


def _cog_xy_px(spot: np.ndarray) -> tuple[float, float]:
    rows, columns = spot.shape
    yy, xx = np.mgrid[0:rows, 0:columns]
    total = float(np.sum(spot))
    return (
        float(np.sum(xx * spot)) / total,
        float(np.sum(yy * spot)) / total,
    )


def _ee50_radius_rad(spot: np.ndarray, pixel_scale_rad) -> float:
    center_x, center_y = _cog_xy_px(spot)
    rows, columns = spot.shape
    yy, xx = np.mgrid[0:rows, 0:columns]
    radii = np.hypot(
        (xx - center_x) * pixel_scale_rad[0],
        (yy - center_y) * pixel_scale_rad[1],
    ).ravel()
    order = np.argsort(radii)
    cumulative = np.cumsum(spot.ravel()[order]) / float(np.sum(spot))
    return float(radii[order][np.searchsorted(cumulative, 0.5)])


class TestBackendContract:
    def test_backend_implements_the_optics_protocol(self):
        optics = _optics()
        assert isinstance(optics, ShackHartmannOpticsBackend)
        assert optics.backend_name == "hcipy"
        assert len(optics.config_hash) == 64
        assert optics.wfs_wavelength_m == WAVELENGTH_M
        assert optics.detector_sampling is optics.sampling

    def test_zero_phase_result_satisfies_the_canonical_contract(self):
        geometry = _geometry()
        optics = _optics(geometry)
        result = optics.spot_intensities(np.zeros(geometry.pupil_shape))

        assert isinstance(result, SpotIntensityResult)
        assert result.subaperture_ids == geometry.subaperture_ids
        assert result.normalization == "unit_sum_per_subaperture"
        assert result.sampling.window_shape_px == (16, 16)
        assert result.sampling.reference_pixel_xy == (7.5, 7.5)
        for spot in result.unit_sum_spots:
            assert type(spot) is np.ndarray
            assert not isinstance(spot, hcipy.Field)
            assert np.all(np.isfinite(spot))
            assert np.all(spot >= 0.0)
            assert float(np.sum(spot)) == pytest.approx(1.0, abs=1.0e-12)
        validate_spot_intensity_result(result, geometry, sampling=optics.sampling)

    def test_detector_sampling_reports_the_focal_plane_geometry(self):
        geometry = _geometry()
        optics = _optics(geometry)
        pixel_pitch_m = float(geometry.x_m[0, 1] - geometry.x_m[0, 0])
        expected_scale = pixel_pitch_m / optics.focal_length_m
        assert optics.sampling.pixel_scale_rad[0] == pytest.approx(
            expected_scale,
            rel=1.0e-12,
        )
        assert optics.focal_length_m == pytest.approx(
            optics.f_number * DIAMETER_M / LENSLETS_ACROSS,
            rel=1.0e-12,
        )

    def test_propagation_is_memoryless_and_deterministic(self):
        geometry = _geometry()
        optics = _optics(geometry)
        tilt = 1.0e-7 * geometry.x_m
        first = optics.spot_intensities(tilt)
        optics.spot_intensities(-2.0 * tilt)
        second = optics.spot_intensities(tilt)
        for one, two in zip(first.unit_sum_spots, second.unit_sum_spots):
            assert np.array_equal(one, two)

    def test_nan_outside_the_pupil_is_accepted(self):
        geometry = _geometry()
        optics = _optics(geometry)
        residual = np.where(geometry.pupil_mask, 0.0, np.nan)
        result = optics.spot_intensities(residual)
        reference = optics.spot_intensities(np.zeros(geometry.pupil_shape))
        for one, two in zip(result.unit_sum_spots, reference.unit_sum_spots):
            assert np.array_equal(one, two)


class TestGeometricSignConvention:
    @pytest.mark.parametrize("direction", (1.0, -1.0))
    def test_pure_x_tilt_moves_the_spot_along_detector_columns(self, direction):
        geometry = _geometry()
        optics = _optics(geometry)
        index = _interior_index(geometry)
        scale = optics.sampling.pixel_scale_rad[0]
        zero = optics.spot_intensities(np.zeros(geometry.pupil_shape))
        tilted = optics.spot_intensities(direction * 0.8 * scale * geometry.x_m)

        shift_x = (
            _cog_xy_px(tilted.unit_sum_spots[index])[0]
            - _cog_xy_px(zero.unit_sum_spots[index])[0]
        )
        shift_y = (
            _cog_xy_px(tilted.unit_sum_spots[index])[1]
            - _cog_xy_px(zero.unit_sum_spots[index])[1]
        )
        assert np.sign(shift_x) == np.sign(direction)
        assert abs(shift_x) == pytest.approx(0.8, rel=0.25)
        assert abs(shift_y) < 0.05

    @pytest.mark.parametrize("direction", (1.0, -1.0))
    def test_pure_y_tilt_moves_the_spot_along_detector_rows(self, direction):
        geometry = _geometry()
        optics = _optics(geometry)
        index = _interior_index(geometry)
        scale = optics.sampling.pixel_scale_rad[1]
        zero = optics.spot_intensities(np.zeros(geometry.pupil_shape))
        tilted = optics.spot_intensities(direction * 0.8 * scale * geometry.y_m)

        shift_x = (
            _cog_xy_px(tilted.unit_sum_spots[index])[0]
            - _cog_xy_px(zero.unit_sum_spots[index])[0]
        )
        shift_y = (
            _cog_xy_px(tilted.unit_sum_spots[index])[1]
            - _cog_xy_px(zero.unit_sum_spots[index])[1]
        )
        assert np.sign(shift_y) == np.sign(direction)
        assert abs(shift_y) == pytest.approx(0.8, rel=0.25)
        assert abs(shift_x) < 0.05

    def test_centroid_response_is_linear_for_small_tilts(self):
        geometry = _geometry()
        optics = _optics(geometry)
        index = _interior_index(geometry)
        scale = optics.sampling.pixel_scale_rad[0]
        zero_x = _cog_xy_px(
            optics.spot_intensities(
                np.zeros(geometry.pupil_shape)
            ).unit_sum_spots[index]
        )[0]

        def measured_shift_px(applied_px: float) -> float:
            spots = optics.spot_intensities(
                applied_px * scale * geometry.x_m
            )
            return _cog_xy_px(spots.unit_sum_spots[index])[0] - zero_x

        small = measured_shift_px(0.2)
        doubled = measured_shift_px(0.4)
        assert doubled / small == pytest.approx(2.0, rel=0.05)
        assert small / 0.2 == pytest.approx(0.92, abs=0.08)


class TestOrderingAndFlux:
    def test_lenslet_count_and_ordering_follow_the_geometry(self):
        geometry = _geometry()
        result = _optics(geometry).spot_intensities(
            np.zeros(geometry.pupil_shape)
        )
        assert len(result.unit_sum_spots) == len(geometry.subaperture_ids)
        assert result.subaperture_ids == geometry.subaperture_ids
        rows, columns = zip(
            *(
                lenslet_indices_from_id(identifier)
                for identifier in result.subaperture_ids
            )
        )
        assert max(rows) < LENSLETS_ACROSS
        assert max(columns) < LENSLETS_ACROSS

    def test_flux_conservation_within_the_defined_normalization(self):
        geometry = _geometry()
        optics = _optics(geometry)
        result = optics.spot_intensities(np.zeros(geometry.pupil_shape))

        throughput = result.relative_throughput
        assert np.all(throughput > 0.0)
        assert np.all(throughput <= 1.0)
        largest = max(
            int(np.count_nonzero(mask)) for mask in geometry.subaperture_masks
        )
        for index, mask in enumerate(geometry.subaperture_masks):
            if int(np.count_nonzero(mask)) == largest:
                assert 0.9 < throughput[index] <= 1.0

    def test_zero_phase_spots_sit_on_the_nominal_lenslet_axes(self):
        geometry = _geometry()
        optics = _optics(geometry)
        result = optics.spot_intensities(np.zeros(geometry.pupil_shape))
        pixels_per_lenslet = (PUPIL_PIXELS - 1) / LENSLETS_ACROSS
        window = PUPIL_PIXELS // LENSLETS_ACROSS
        for index, identifier in enumerate(result.subaperture_ids):
            row, column = lenslet_indices_from_id(identifier)
            if row in (0, LENSLETS_ACROSS - 1) or column in (
                0,
                LENSLETS_ACROSS - 1,
            ):
                continue  # pupil-edge truncation biases the plain CoG
            expected_x = (column + 0.5) * pixels_per_lenslet - column * window
            expected_y = (row + 0.5) * pixels_per_lenslet - row * window
            measured_x, measured_y = _cog_xy_px(result.unit_sum_spots[index])
            assert measured_x == pytest.approx(expected_x, abs=0.15)
            assert measured_y == pytest.approx(expected_y, abs=0.15)


class TestNativeComparison:
    """Spot morphology agreement between the native and HCIPy backends."""

    @staticmethod
    def _matched_native(geometry, optics) -> NativeShackHartmannOptics:
        """Native backend cropped to the same angular field as one window."""

        probe = NativeShackHartmannOptics(geometry, WAVELENGTH_M, pad_factor=8)
        window_px = optics.sampling.window_shape_px[1]
        angular_extent_rad = window_px * optics.sampling.pixel_scale_rad[0]
        native_window_px = int(
            round(angular_extent_rad / probe.sampling.pixel_scale_rad[0])
        )
        return NativeShackHartmannOptics(
            geometry,
            WAVELENGTH_M,
            pad_factor=8,
            detector_window_px=native_window_px,
        )

    def test_zero_phase_spot_size_matches_native(self):
        geometry = _geometry()
        optics = _optics(geometry)
        native = self._matched_native(geometry, optics)
        index = _interior_index(geometry)

        zero = np.zeros(geometry.pupil_shape)
        ee50_hcipy = _ee50_radius_rad(
            optics.spot_intensities(zero).unit_sum_spots[index],
            optics.sampling.pixel_scale_rad,
        )
        ee50_native = _ee50_radius_rad(
            native.spot_intensities(zero).unit_sum_spots[index],
            native.sampling.pixel_scale_rad,
        )
        assert ee50_hcipy / ee50_native == pytest.approx(1.0, abs=0.2)
        # Both stay near the diffraction scale of one lenslet.
        lenslet_diameter_m = DIAMETER_M / LENSLETS_ACROSS
        diffraction_rad = WAVELENGTH_M / lenslet_diameter_m
        assert 0.2 < ee50_hcipy / diffraction_rad < 1.0

    def test_small_tilt_gain_matches_native_on_the_same_angular_window(self):
        geometry = _geometry()
        optics = _optics(geometry)
        native = self._matched_native(geometry, optics)
        index = _interior_index(geometry)
        slope_rad = 1.5 * optics.sampling.pixel_scale_rad[0]
        tilt_opd_m = slope_rad * geometry.x_m
        zero = np.zeros(geometry.pupil_shape)

        def gain(backend) -> float:
            reference = _cog_xy_px(
                backend.spot_intensities(zero).unit_sum_spots[index]
            )[0]
            displaced = _cog_xy_px(
                backend.spot_intensities(tilt_opd_m).unit_sum_spots[index]
            )[0]
            return (
                (displaced - reference)
                * backend.sampling.pixel_scale_rad[0]
                / slope_rad
            )

        gain_hcipy = gain(optics)
        gain_native = gain(native)
        assert 0.7 < gain_hcipy <= 1.05
        assert 0.7 < gain_native <= 1.05
        assert abs(gain_hcipy - gain_native) < 0.2


class TestSharedDetectorChain:
    """The repository detector, centroid, and validity modules are reused."""

    @staticmethod
    def _sensor(geometry, optics, *, photons: float = 2.0e4, seed: int = 11):
        return build_detector_shack_hartmann_sensor(
            geometry,
            optics,
            DetectorConfig(photons_per_subap_frame=photons),
            wfs_wavelength_m=WAVELENGTH_M,
            random_streams=NamedRandomStreams(seed),
        )

    def test_detector_level_calibration_works_with_the_hcipy_backend(self):
        geometry = _geometry()
        optics = _optics(geometry)
        sensor = self._sensor(geometry, optics)
        assert isinstance(sensor, WavefrontSensor)

        measurement = sensor.measure(
            np.zeros(geometry.pupil_shape),
            random_streams=NamedRandomStreams(11),
            include_noise=False,
        )
        assert isinstance(measurement, WfsMeasurement)
        # Zero residual OPD reproduces the zero-phase reference exactly in
        # the noiseless path.
        assert np.all(np.abs(measurement.vector.values) < 1.0e-9)
        assert np.all(measurement.vector.valid_rows)

    def test_matched_sampling_and_photon_allocation_through_the_chain(self):
        geometry = _geometry()
        optics = _optics(geometry)
        photons = 2.0e4
        sensor = self._sensor(geometry, optics, photons=photons)
        measurement = sensor.measure(
            0.5 * optics.sampling.pixel_scale_rad[0] * geometry.x_m,
            random_streams=NamedRandomStreams(11),
            include_noise=True,
        )

        telemetry = measurement.detector_telemetry
        assert telemetry is not None
        count = len(geometry.subaperture_ids)
        assert telemetry.subaperture_ids == geometry.subaperture_ids
        assert telemetry.centroids_xy_px.shape == (count, 2)
        assert np.all(np.isfinite(telemetry.fluxes_e))
        # Photon allocation happens per subaperture after throughput scaling;
        # detected electrons stay near the configured budget.
        assert np.all(telemetry.fluxes_e > 0.2 * photons)
        assert np.all(telemetry.fluxes_e < 1.5 * photons)
        assert np.all(telemetry.valid_subapertures)

    def test_noiseless_measurement_tracks_the_applied_tilt(self):
        geometry = _geometry()
        optics = _optics(geometry)
        sensor = self._sensor(geometry, optics)
        applied_px = 0.6
        measurement = sensor.measure(
            applied_px * optics.sampling.pixel_scale_rad[0] * geometry.x_m,
            random_streams=NamedRandomStreams(11),
            include_noise=False,
        )
        values = measurement.vector.values
        x_rows = values[0::2]
        y_rows = values[1::2]
        assert np.all(x_rows > 0.3 * applied_px)
        assert np.all(np.abs(y_rows) < 0.1)

    def test_no_hcipy_object_leaks_into_the_measurement(self):
        geometry = _geometry()
        optics = _optics(geometry)
        sensor = self._sensor(geometry, optics)
        measurement = sensor.measure(
            np.zeros(geometry.pupil_shape),
            random_streams=NamedRandomStreams(11),
            include_noise=True,
        )
        assert type(measurement.vector.values) is np.ndarray
        telemetry = measurement.detector_telemetry
        assert type(telemetry.centroids_xy_px) is np.ndarray
        assert not isinstance(telemetry.centroids_xy_px, hcipy.Field)
        json.dumps(_plain_json(measurement.metadata))

    def test_interaction_matrix_calibrates_an_all_hcipy_dm_wfs_pair(self):
        from shwfs_ao.calibration import (
            DmActuatorProbeBasis,
            calibrate_interaction_matrix,
        )

        geometry = _geometry(pupil_pixels=48, lenslets_across=3)
        optics = _optics(geometry)
        sensor = self._sensor(geometry, optics, photons=1.0e5, seed=23)
        dm = build_hcipy_deformable_mirror(
            geometry.x_m,
            geometry.y_m,
            geometry.pupil_mask,
            DMConfig(
                telescope_diameter_m=DIAMETER_M,
                n_actuators_across=3,
                coupling_width_pitch=0.35,
                stroke_limit_nm=800.0,
            ),
        )
        interaction = calibrate_interaction_matrix(
            DmActuatorProbeBasis(dm),
            sensor,
            amplitude_m=25.0e-9,
            random_streams=NamedRandomStreams(23).scoped("calibration-probe"),
            include_noise=False,
        )
        assert interaction.coordinate_ids == dm.controllable_actuator_ids
        assert interaction.matrix.shape == (
            len(sensor.row_ids),
            dm.n_actuators,
        )
        assert interaction.dm_hash == dm.config_hash
        assert np.all(np.isfinite(interaction.matrix[interaction.row_valid]))
        assert float(np.max(np.abs(interaction.matrix))) > 0.0


class TestOptionalHcipyEstimator:
    def test_estimator_comparison_agrees_with_the_window_centroids(self):
        geometry = _geometry()
        optics = _optics(geometry)
        index = _interior_index(geometry)
        slope_rad = 0.8 * optics.sampling.pixel_scale_rad[0]
        zero_opd = np.zeros(geometry.pupil_shape)
        tilt_opd = slope_rad * geometry.x_m

        estimator_shift_px = (
            optics.hcipy_estimator_centroids_px(tilt_opd)[index, 0]
            - optics.hcipy_estimator_centroids_px(zero_opd)[index, 0]
        )
        spots_zero = optics.spot_intensities(zero_opd)
        spots_tilt = optics.spot_intensities(tilt_opd)
        window_shift_px = (
            _cog_xy_px(spots_tilt.unit_sum_spots[index])[0]
            - _cog_xy_px(spots_zero.unit_sum_spots[index])[0]
        )
        # Same pixels, same first-moment arithmetic: the HCIPy estimator and
        # the repository window centroid must agree to numerical precision.
        assert estimator_shift_px == pytest.approx(window_shift_px, abs=1.0e-9)

    def test_estimator_output_is_diagnostics_only_plain_data(self):
        geometry = _geometry()
        optics = _optics(geometry)
        centroids = optics.hcipy_estimator_centroids_px(
            np.zeros(geometry.pupil_shape)
        )
        assert type(centroids) is np.ndarray
        assert not isinstance(centroids, hcipy.Field)
        assert centroids.shape == (len(geometry.subaperture_ids), 2)
        assert not centroids.flags.writeable
        assert np.all(np.isfinite(centroids))


class TestValidation:
    def test_construction_rejects_invalid_repository_inputs(self):
        geometry = _geometry()
        with pytest.raises(HcipyShackHartmannError, match="ShackHartmannGeometry"):
            HcipyShackHartmannOptics(object(), WAVELENGTH_M, f_number=100.0)
        with pytest.raises(HcipyShackHartmannError, match="wfs_wavelength_m"):
            HcipyShackHartmannOptics(geometry, 0.0, f_number=100.0)
        with pytest.raises(HcipyShackHartmannError, match="f_number"):
            HcipyShackHartmannOptics(geometry, WAVELENGTH_M, f_number=-1.0)

    def test_non_divisible_pupil_sampling_is_rejected(self):
        geometry = _geometry(pupil_pixels=66, lenslets_across=4)
        with pytest.raises(HcipyShackHartmannError, match="integer multiple"):
            _optics(geometry)

    def test_residual_opd_is_validated(self):
        geometry = _geometry()
        optics = _optics(geometry)
        with pytest.raises(HcipyShackHartmannError, match="shape"):
            optics.spot_intensities(np.zeros((16, 16)))
        with pytest.raises(HcipyShackHartmannError, match="infinite"):
            optics.spot_intensities(
                np.full(geometry.pupil_shape, np.inf)
            )
        bad = np.zeros(geometry.pupil_shape)
        bad[geometry.pupil_mask] = np.nan
        with pytest.raises(HcipyShackHartmannError, match="finite"):
            optics.spot_intensities(bad)

    def test_boundary_validation_rejects_missing_and_reordered_ids(self):
        geometry = _geometry()
        optics = _optics(geometry)
        result = optics.spot_intensities(np.zeros(geometry.pupil_shape))

        reordered = SpotIntensityResult(
            unit_sum_spots=tuple(reversed(result.unit_sum_spots)),
            subaperture_ids=tuple(reversed(result.subaperture_ids)),
            relative_throughput=result.relative_throughput[::-1],
            x_px=result.x_px,
            y_px=result.y_px,
            sampling=result.sampling,
            normalization=result.normalization,
        )
        with pytest.raises(ShackHartmannOpticsError, match="reordered"):
            validate_spot_intensity_result(reordered, geometry)

        missing = SpotIntensityResult(
            unit_sum_spots=result.unit_sum_spots[:-1],
            subaperture_ids=result.subaperture_ids[:-1],
            relative_throughput=result.relative_throughput[:-1],
            x_px=result.x_px[:-1],
            y_px=result.y_px[:-1],
            sampling=result.sampling,
            normalization=result.normalization,
        )
        with pytest.raises(ShackHartmannOpticsError, match="missing"):
            validate_spot_intensity_result(missing, geometry)

    def test_duplicate_ids_and_wrong_window_shapes_cannot_be_constructed(self):
        geometry = _geometry()
        optics = _optics(geometry)
        result = optics.spot_intensities(np.zeros(geometry.pupil_shape))

        duplicate_ids = (result.subaperture_ids[0],) + result.subaperture_ids[1:]
        duplicate_ids = duplicate_ids[:-1] + (result.subaperture_ids[0],)
        with pytest.raises(ValueError, match="duplicate"):
            SpotIntensityResult(
                unit_sum_spots=result.unit_sum_spots,
                subaperture_ids=duplicate_ids,
                relative_throughput=result.relative_throughput,
                x_px=result.x_px,
                y_px=result.y_px,
                sampling=result.sampling,
                normalization=result.normalization,
            )

        cropped = tuple(
            spot[:-1, :] / float(np.sum(spot[:-1, :]))
            for spot in result.unit_sum_spots
        )
        with pytest.raises(ValueError, match="unit_sum_spots"):
            SpotIntensityResult(
                unit_sum_spots=cropped,
                subaperture_ids=result.subaperture_ids,
                relative_throughput=result.relative_throughput,
                x_px=result.x_px,
                y_px=result.y_px,
                sampling=result.sampling,
                normalization=result.normalization,
            )


def _plain_json(value):
    """Recursively convert immutable mappings/tuples to JSON-native types."""

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "keys"):
        return {str(key): _plain_json(value[key]) for key in value.keys()}
    if isinstance(value, (tuple, list)):
        return [_plain_json(item) for item in value]
    raise AssertionError(
        f"metadata contains a non-JSON-serializable value of type {type(value)!r}"
    )
