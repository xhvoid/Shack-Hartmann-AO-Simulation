"""Host-portable keying of canonical Shack--Hartmann runtime noise.

The calibration hash binds realized reference centroids, whose low bits
depend on the FFT and libm implementation.  Runtime shot/read-noise streams
are keyed by the declared sensor identity instead, so one seed selects the
same noise streams on every host while the calibration hash keeps recording
the realized content as provenance.  The perturbations below stand in for a
second host: a one-ULP shift of every reference centroid and a reference
calibrated through ``scipy.fft`` instead of ``numpy.fft``.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np
import pytest
import scipy.fft

from shwfs_ao.backends.native.shwfs import NativeShackHartmannOptics
from shwfs_ao.core.random import NamedRandomStreams
from shwfs_ao.core.types import SpotIntensityResult, WfsMeasurement
from shwfs_ao.detector.centroid import CentroidConfig
from shwfs_ao.detector.config import DetectorConfig
from shwfs_ao.detector.random import DetectorRealization, _realization_hash
from shwfs_ao.detector.validity import CentroidValidityConfig
from shwfs_ao.wfs.shack_hartmann.calibration import (
    NOISE_STREAM_IDENTITY_SCHEMA,
    ShackHartmannCalibrationError,
    shack_hartmann_calibration_hash,
    shack_hartmann_noise_stream_identity,
)
from shwfs_ao.wfs.shack_hartmann.geometry import (
    ShackHartmannGeometry,
    build_shack_hartmann_geometry,
)
from shwfs_ao.wfs.shack_hartmann.measurement import DetectorShackHartmannSensor


WAVELENGTH_M = 700.0e-9
SEED = 4242
VALIDITY = CentroidValidityConfig(
    min_flux_e=0.0,
    min_peak_snr=0.0,
    max_centroid_sigma_px=1.0e6,
    max_window_clipping_fraction=1.0,
)
PERSISTENT = DetectorConfig(
    photons_per_subap_frame=800.0,
    read_noise_e=1.5,
    background_e_per_pixel_frame=0.2,
    prnu_mode="persistent",
    prnu_rms=0.02,
)
PER_FRAME_LEGACY = DetectorConfig(
    photons_per_subap_frame=800.0,
    read_noise_e=1.5,
    prnu_mode="per_frame_legacy",
    prnu_rms=0.02,
)
DETECTORS = pytest.mark.parametrize(
    "detector",
    [PERSISTENT, PER_FRAME_LEGACY],
    ids=["persistent", "per_frame_legacy"],
)


@pytest.fixture(scope="module")
def geometry() -> ShackHartmannGeometry:
    return build_shack_hartmann_geometry(
        telescope_diameter_m=1.0,
        pupil_shape=(32, 32),
        n_lenslets_across=4,
        min_fill_fraction=0.4,
    )


@pytest.fixture(scope="module")
def native_backend(geometry: ShackHartmannGeometry) -> NativeShackHartmannOptics:
    return NativeShackHartmannOptics(
        geometry,
        WAVELENGTH_M,
        pad_factor=4,
        detector_window_px=14,
    )


class _DeclaredBackend:
    """Native optics under an explicitly declared name and configuration hash.

    The native configuration hash already binds geometry, wavelength, and
    sampling, and native sampling scales with wavelength.  A fixed declared
    hash and an optionally declared wavelength isolate each identity field,
    as for an alternate backend whose hash or pixel scale does not depend on
    them.
    """

    def __init__(
        self,
        wrapped: NativeShackHartmannOptics,
        *,
        backend_name: str = "declared-native-test-double",
        config_hash: str = "declared-backend-config-v1",
        wfs_wavelength_m: float | None = None,
    ) -> None:
        self.backend_name = backend_name
        self.config_hash = config_hash
        self.geometry = wrapped.geometry
        self.wfs_wavelength_m = (
            wrapped.wfs_wavelength_m
            if wfs_wavelength_m is None
            else wfs_wavelength_m
        )
        self.detector_sampling = wrapped.detector_sampling
        self._wrapped = wrapped

    def spot_intensities(self, residual_opd_m: np.ndarray) -> SpotIntensityResult:
        return self._wrapped.spot_intensities(residual_opd_m)


def _calibrated(
    geometry: ShackHartmannGeometry,
    backend: Any,
    detector: DetectorConfig = PERSISTENT,
    *,
    seed: int = SEED,
    **kwargs: Any,
) -> DetectorShackHartmannSensor:
    return DetectorShackHartmannSensor.calibrate(
        geometry,
        backend,
        detector,
        wfs_wavelength_m=float(backend.wfs_wavelength_m),
        random_streams=NamedRandomStreams(seed),
        validity_config=VALIDITY,
        **kwargs,
    )


def _with_reference_ulp_shift(
    sensor: DetectorShackHartmannSensor,
) -> DetectorShackHartmannSensor:
    """Rebuild the sensor with every reference centroid one ULP larger."""

    calibration = sensor.calibration
    reference = np.nextafter(calibration.reference_centroids_px, np.inf)
    config_hash = shack_hartmann_calibration_hash(
        geometry=calibration.geometry,
        reference_centroids_px=reference,
        wfs_wavelength_m=calibration.wfs_wavelength_m,
        subaperture_ids=calibration.subaperture_ids,
        row_ids=calibration.row_ids,
        detector_sampling=calibration.detector_sampling,
        detector_config=calibration.detector_config,
        centroid_config=calibration.centroid_config,
        detector_realization_hash=calibration.detector_realization_hash,
        provenance=calibration.provenance,
        photon_allocation=calibration.photon_allocation,
    )
    return DetectorShackHartmannSensor(
        sensor.optics_backend,
        replace(
            calibration,
            reference_centroids_px=reference,
            config_hash=config_hash,
        ),
        sensor.detector_realization,
        validity_config=sensor.validity_config,
    )


def _noisy(
    sensor: DetectorShackHartmannSensor,
    residual_opd_m: np.ndarray,
    *,
    seed: int = SEED,
) -> WfsMeasurement:
    return sensor.measure(
        residual_opd_m,
        random_streams=NamedRandomStreams(seed),
        include_noise=True,
    )


def _frames(measurement: WfsMeasurement) -> tuple:
    telemetry = measurement.detector_telemetry
    assert telemetry is not None
    frames = telemetry.detector_frames
    assert frames is not None
    return frames


def _assert_same_noise_draws(first: WfsMeasurement, second: WfsMeasurement) -> None:
    assert first.metadata["noise_stream_identity"] == (
        second.metadata["noise_stream_identity"]
    )
    assert first.metadata["legacy_runtime_stream_ids"] == (
        second.metadata["legacy_runtime_stream_ids"]
    )
    for left, right in zip(_frames(first), _frames(second), strict=True):
        assert dict(left.random_stream_ids) == dict(right.random_stream_ids)
        # Noise was drawn, so equal images mean equal Poisson and read draws.
        assert not np.array_equal(left.image_e, left.expected_pre_poisson_e)
        np.testing.assert_array_equal(left.image_e, right.image_e)


@DETECTORS
def test_one_ulp_reference_shift_keeps_runtime_noise_streams_and_draws(
    geometry: ShackHartmannGeometry,
    native_backend: NativeShackHartmannOptics,
    detector: DetectorConfig,
) -> None:
    sensor = _calibrated(geometry, native_backend, detector)
    shifted = _with_reference_ulp_shift(sensor)

    # The calibration hash records the realized references as provenance.
    assert shifted.calibration.config_hash != sensor.calibration.config_hash
    assert shifted.calibration.provenance == sensor.calibration.provenance
    assert shifted.noise_stream_identity == sensor.noise_stream_identity

    residual = 1.5e-7 * geometry.x_m - 0.8e-7 * geometry.y_m
    first = _noisy(sensor, residual)
    second = _noisy(shifted, residual)
    _assert_same_noise_draws(first, second)
    first_telemetry = first.detector_telemetry
    second_telemetry = second.detector_telemetry
    assert first_telemetry is not None and second_telemetry is not None
    np.testing.assert_array_equal(
        first_telemetry.centroids_xy_px,
        second_telemetry.centroids_xy_px,
    )
    np.testing.assert_allclose(
        second.vector.values,
        first.vector.values,
        rtol=0.0,
        atol=1.0e-14,
    )


def test_scipy_fft_calibration_keeps_noise_streams_and_draws(
    geometry: ShackHartmannGeometry,
    native_backend: NativeShackHartmannOptics,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    residual = 1.5e-7 * geometry.x_m - 0.8e-7 * geometry.y_m
    numpy_sensor = _calibrated(geometry, native_backend)
    numpy_measurement = _noisy(numpy_sensor, residual)
    with monkeypatch.context() as patch:
        patch.setattr(np.fft, "fft2", scipy.fft.fft2)
        scipy_sensor = _calibrated(geometry, native_backend)
        scipy_measurement = _noisy(scipy_sensor, residual)

    if scipy_sensor.calibration.config_hash == numpy_sensor.calibration.config_hash:
        pytest.skip("scipy.fft and numpy.fft agree bitwise on this host")
    assert scipy_sensor.noise_stream_identity == numpy_sensor.noise_stream_identity
    _assert_same_noise_draws(numpy_measurement, scipy_measurement)
    for left, right in zip(
        _frames(numpy_measurement),
        _frames(scipy_measurement),
        strict=True,
    ):
        # The deterministic signal differs only by FFT roundoff.
        np.testing.assert_allclose(
            right.expected_pre_poisson_e,
            left.expected_pre_poisson_e,
            rtol=1.0e-12,
            atol=1.0e-12,
        )


@DETECTORS
def test_runtime_scope_is_keyed_by_identity_not_calibration_hash(
    geometry: ShackHartmannGeometry,
    native_backend: NativeShackHartmannOptics,
    detector: DetectorConfig,
) -> None:
    sensor = _calibrated(geometry, native_backend, detector)
    measured = _noisy(sensor, np.zeros(geometry.pupil_shape))

    assert measured.metadata["noise_stream_identity"] == sensor.noise_stream_identity
    assert measured.metadata["noise_stream_identity_schema"] == (
        NOISE_STREAM_IDENTITY_SCHEMA
    )
    assert measured.metadata["calibration_config_hash"] == (
        sensor.calibration.config_hash
    )
    expected_ids = [
        NamedRandomStreams(SEED)
        .scoped(
            "shack_hartmann.measurement",
            key=(sensor.noise_stream_identity, subaperture_id),
        )
        .stream_id("detector.shot_noise")
        for subaperture_id in sensor.subaperture_ids
    ]
    if detector.prnu_mode == "persistent":
        recorded = [
            frame.random_stream_ids["detector.shot_noise"]
            for frame in _frames(measured)
        ]
    else:
        recorded = list(measured.metadata["legacy_runtime_stream_ids"])
    assert recorded == expected_ids


def test_noise_stream_identity_changes_with_every_declared_input(
    geometry: ShackHartmannGeometry,
    native_backend: NativeShackHartmannOptics,
) -> None:
    declared = _DeclaredBackend(native_backend)
    base = _calibrated(geometry, declared)
    # Same IDs and pupil sampling, different pupil mask.
    obstructed = build_shack_hartmann_geometry(
        telescope_diameter_m=1.0,
        pupil_shape=geometry.pupil_shape,
        n_lenslets_across=geometry.n_lenslets_across,
        min_fill_fraction=0.4,
        central_obstruction_ratio=0.2,
    )
    assert obstructed.subaperture_ids == geometry.subaperture_ids
    assert obstructed.geometry_hash != geometry.geometry_hash
    fewer = build_shack_hartmann_geometry(
        telescope_diameter_m=1.0,
        pupil_shape=geometry.pupil_shape,
        n_lenslets_across=geometry.n_lenslets_across,
        min_fill_fraction=0.9,
    )
    assert fewer.subaperture_ids != geometry.subaperture_ids

    def backend(
        layout: ShackHartmannGeometry = geometry,
        *,
        pad_factor: int = 4,
    ) -> _DeclaredBackend:
        return _DeclaredBackend(
            NativeShackHartmannOptics(
                layout,
                WAVELENGTH_M,
                pad_factor=pad_factor,
                detector_window_px=14,
            )
        )

    resampled = backend(pad_factor=3)
    assert resampled.detector_sampling.window_shape_px == (
        native_backend.detector_sampling.window_shape_px
    )
    assert resampled.detector_sampling.sampling_hash != (
        native_backend.detector_sampling.sampling_hash
    )

    variants = {
        "root_seed": _calibrated(geometry, declared, seed=SEED + 1),
        "realization_index": _calibrated(
            geometry,
            declared,
            realization_index=1,
        ),
        "detector_config": _calibrated(
            geometry,
            declared,
            replace(PERSISTENT, read_noise_e=2.0),
        ),
        "centroid_config": _calibrated(
            geometry,
            declared,
            centroid_config=CentroidConfig(subtract_minimum=True),
        ),
        "photon_allocation": _calibrated(
            geometry,
            declared,
            photon_allocation="unit_sum",
        ),
        "geometry": _calibrated(obstructed, backend(obstructed)),
        "subaperture_ids": _calibrated(fewer, backend(fewer)),
        "wfs_wavelength": _calibrated(
            geometry,
            _DeclaredBackend(native_backend, wfs_wavelength_m=800.0e-9),
        ),
        "detector_sampling": _calibrated(geometry, resampled),
        "optics_backend_name": _calibrated(
            geometry,
            _DeclaredBackend(native_backend, backend_name="renamed-test-double"),
        ),
        "optics_backend_config": _calibrated(
            geometry,
            _DeclaredBackend(native_backend, config_hash="other-config-v1"),
        ),
    }
    identities = {
        name: sensor.noise_stream_identity for name, sensor in variants.items()
    }
    for name, identity in identities.items():
        assert identity != base.noise_stream_identity, name
    assert len(set(identities.values())) == len(identities)


def test_drawn_realization_is_named_by_derivation_and_declared_maps_by_content(
    geometry: ShackHartmannGeometry,
    native_backend: NativeShackHartmannOptics,
) -> None:
    base = _calibrated(geometry, native_backend)
    drawn = base.detector_realization
    assert drawn.stream_id is not None

    # A drawn PRNU map passes through libm in NumPy's normal sampler; a
    # one-ULP change of it must not move the noise streams.
    shifted_prnu = np.nextafter(drawn.prnu_response, np.inf)
    shifted = DetectorRealization(
        shifted_prnu,
        drawn.bad_pixel_mask,
        drawn.root_seed,
        drawn.stream_id,
        drawn.config_hash,
        _realization_hash(
            prnu_response=shifted_prnu,
            bad_pixel_mask=drawn.bad_pixel_mask,
            root_seed=drawn.root_seed,
            stream_id=drawn.stream_id,
            config_hash=drawn.config_hash,
        ),
    )
    remapped = _calibrated(
        geometry,
        native_backend,
        detector_realization=shifted,
    )
    assert remapped.calibration.config_hash != base.calibration.config_hash
    assert remapped.noise_stream_identity == base.noise_stream_identity

    # Without a drawn stream the maps are declared content and stay keyed.
    flat = DetectorConfig(photons_per_subap_frame=800.0, prnu_mode="persistent")
    declared = DetectorRealization.create(
        flat,
        native_backend.detector_sampling.window_shape_px,
        random_streams=NamedRandomStreams(SEED),
    )
    assert declared.stream_id is None
    edited_prnu = np.array(declared.prnu_response, copy=True)
    edited_prnu[0, 0] = 0.5
    edited = DetectorRealization(
        edited_prnu,
        declared.bad_pixel_mask,
        declared.root_seed,
        None,
        declared.config_hash,
        _realization_hash(
            prnu_response=edited_prnu,
            bad_pixel_mask=declared.bad_pixel_mask,
            root_seed=declared.root_seed,
            stream_id=None,
            config_hash=declared.config_hash,
        ),
    )
    first = _calibrated(
        geometry,
        native_backend,
        flat,
        detector_realization=declared,
    )
    second = _calibrated(
        geometry,
        native_backend,
        flat,
        detector_realization=edited,
    )
    assert first.noise_stream_identity != second.noise_stream_identity


def test_noise_stream_identity_rejects_a_foreign_realization_or_backend(
    geometry: ShackHartmannGeometry,
    native_backend: NativeShackHartmannOptics,
) -> None:
    sensor = _calibrated(geometry, native_backend)
    other = _calibrated(geometry, native_backend, seed=SEED + 1)

    assert shack_hartmann_noise_stream_identity(
        sensor.calibration,
        sensor.detector_realization,
        optics_backend=native_backend,
    ) == sensor.noise_stream_identity
    with pytest.raises(ShackHartmannCalibrationError, match="realization"):
        shack_hartmann_noise_stream_identity(
            sensor.calibration,
            other.detector_realization,
            optics_backend=native_backend,
        )
    with pytest.raises(ShackHartmannCalibrationError, match="backend"):
        shack_hartmann_noise_stream_identity(
            sensor.calibration,
            sensor.detector_realization,
            optics_backend=_DeclaredBackend(native_backend),
        )


@pytest.mark.parametrize(
    "detector",
    [replace(PERSISTENT, background_e_per_pixel_frame=0.0), PER_FRAME_LEGACY],
    ids=["persistent", "per_frame_legacy"],
)
def test_unlit_pixel_roundoff_keeps_every_frame_of_a_stream(
    geometry: ShackHartmannGeometry,
    detector: DetectorConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # With no background, block-lenslet spots have exactly unlit pixels on one
    # host and roundoff residues on another.  A tiny additive FFT residue
    # stands in for that host: it turns exact zeros into positive
    # expectations without changing any lit pixel.  Several frames share one
    # provider, so a shifted persistent stream would show in later frames.
    backend = NativeShackHartmannOptics(geometry, WAVELENGTH_M, pad_factor=4)
    residuals = (
        1.5e-7 * geometry.x_m - 0.8e-7 * geometry.y_m,
        4.0e-7 * (geometry.x_m**2 - geometry.y_m**2),
        -1.0e-7 * geometry.y_m,
    )

    def run() -> list[WfsMeasurement]:
        sensor = _calibrated(geometry, backend, detector)
        streams = NamedRandomStreams(SEED)
        return [
            sensor.measure(residual, random_streams=streams, include_noise=True)
            for residual in residuals
        ]

    exact = run()
    numpy_fft2 = np.fft.fft2
    with monkeypatch.context() as patch:
        patch.setattr(
            np.fft, "fft2", lambda *args, **kwargs: numpy_fft2(*args, **kwargs) + 1.0e-30
        )
        residue = run()

    exact_zeros = sum(
        np.count_nonzero(frame.expected_pre_poisson_e == 0.0)
        for measurement in exact
        for frame in _frames(measurement)
    )
    residue_zeros = sum(
        np.count_nonzero(frame.expected_pre_poisson_e == 0.0)
        for measurement in residue
        for frame in _frames(measurement)
    )
    assert exact_zeros > residue_zeros
    for first, second in zip(exact, residue, strict=True):
        for left, right in zip(_frames(first), _frames(second), strict=True):
            np.testing.assert_array_equal(right.image_e, left.image_e)
