"""Small real-component smoke tests for the canonical AO-REF-009 runner."""

from __future__ import annotations

import numpy as np

from shwfs_ao.backends.native.atmosphere import StaticOpdAtmosphere
from shwfs_ao.backends.native.shwfs import NativeShackHartmannOptics
from shwfs_ao.calibration import (
    DmActuatorProbeBasis,
    LeastSquaresReconstructor,
    calibrate_interaction_matrix,
)
from shwfs_ao.control import (
    IdentityCommandProjector,
    LeakyIntegratorController,
    LoopConfig,
    run_closed_loop,
)
from shwfs_ao.core.protocols import (
    AtmosphereModel,
    DeformableMirrorModel,
    Reconstructor,
    WavefrontSensor,
)
from shwfs_ao.core.random import NamedRandomStreams
from shwfs_ao.core.types import DmCommandVector
from shwfs_ao.detector.centroid import CentroidConfig
from shwfs_ao.detector.config import DetectorConfig
from shwfs_ao.detector.validity import CentroidValidityConfig
from shwfs_ao.dm import DMConfig, build_native_deformable_mirror
from shwfs_ao.wfs.shack_hartmann.geometric import (
    NativeGeometricShackHartmannSensor,
)
from shwfs_ao.wfs.shack_hartmann.geometry import (
    build_shack_hartmann_geometry,
)
from shwfs_ao.wfs.shack_hartmann.measurement import (
    DetectorShackHartmannSensor,
)


def test_actual_native_geometric_sensor_dm_calibration_and_control_loop() -> None:
    """Exercise every canonical production boundary without optical FFT cost."""

    geometry = build_shack_hartmann_geometry(
        telescope_diameter_m=1.0,
        pupil_shape=(20, 20),
        n_lenslets_across=4,
        min_fill_fraction=0.35,
    )
    dm = build_native_deformable_mirror(
        geometry.x_m,
        geometry.y_m,
        geometry.pupil_mask,
        DMConfig(
            telescope_diameter_m=1.0,
            n_actuators_across=3,
            stroke_limit_nm=250.0,
        ),
    )
    wfs = NativeGeometricShackHartmannSensor(geometry)
    streams = NamedRandomStreams(41)
    interaction = calibrate_interaction_matrix(
        DmActuatorProbeBasis(dm),
        wfs,
        10.0e-9,
        random_streams=streams,
    )
    reconstructor = LeastSquaresReconstructor(
        interaction,
        min_valid_fraction=1.0,
        min_rank=1,
    )
    projector = IdentityCommandProjector(dm.actuator_ids)
    config = LoopConfig(
        n_steps=4,
        gain=0.5,
        leak=0.0,
        latency_frames=0,
        frame_rate_hz=500.0,
        root_seed=41,
    )
    controller = LeakyIntegratorController.from_loop_config(
        dm.actuator_ids,
        config,
    )

    truth_commands = np.linspace(
        -35.0e-9,
        35.0e-9,
        dm.n_actuators,
    )
    truth = dm.opd_from_commands(
        DmCommandVector(
            truth_commands,
            dm.actuator_ids,
            "m_opd_equivalent",
        )
    )
    atmosphere = StaticOpdAtmosphere(
        truth.correction_opd_m,
        geometry.pupil_mask,
        root_seed=config.root_seed,
    )

    history = run_closed_loop(
        config,
        random_streams=streams,
        atmosphere=atmosphere,
        wfs=wfs,
        dm=dm,
        interaction_matrix=interaction,
        reconstructor=reconstructor,
        command_projector=projector,
        controller=controller,
        include_noise=False,
    )

    assert isinstance(atmosphere, AtmosphereModel)
    assert isinstance(wfs, WavefrontSensor)
    assert isinstance(dm, DeformableMirrorModel)
    assert isinstance(reconstructor, Reconstructor)
    assert interaction.coordinate_ids == dm.actuator_ids
    assert interaction.rank >= 1
    np.testing.assert_array_equal(
        history.measurement_row_masks,
        np.broadcast_to(interaction.row_valid, history.measurement_row_masks.shape),
    )
    np.testing.assert_array_equal(history.reconstruction_usable, True)
    np.testing.assert_allclose(history.valid_measurement_fraction, 1.0)
    np.testing.assert_allclose(history.valid_subaperture_fraction, 1.0)
    assert history.post_update_residual_opd_rms_m[0] < (
        history.pre_update_residual_opd_rms_m[0]
    )
    assert history.post_update_residual_opd_rms_m[-1] < (
        0.2 * history.pre_update_residual_opd_rms_m[0]
    )
    np.testing.assert_allclose(history.saturation_fraction, 0.0)
    assert history.metadata["backend_names"]["atmosphere"] == "native"
    assert history.metadata["backend_names"]["wfs"] == "native_geometric"
    assert history.metadata["backend_names"]["dm"] == "native"


def test_actual_native_detector_level_sensor_runs_through_the_same_loop() -> None:
    """Keep a small FFT/detector smoke case without reproducing detector logic."""

    wavelength_m = 700.0e-9
    geometry = build_shack_hartmann_geometry(
        telescope_diameter_m=1.0,
        pupil_shape=(16, 16),
        n_lenslets_across=3,
        min_fill_fraction=0.3,
    )
    optics = NativeShackHartmannOptics(
        geometry,
        wavelength_m,
        pad_factor=2,
        detector_window_px=8,
    )
    dm = build_native_deformable_mirror(
        geometry.x_m,
        geometry.y_m,
        geometry.pupil_mask,
        DMConfig(
            telescope_diameter_m=1.0,
            n_actuators_across=3,
            stroke_limit_nm=250.0,
        ),
    )
    streams = NamedRandomStreams(53)
    sensor = DetectorShackHartmannSensor.calibrate(
        geometry,
        optics,
        DetectorConfig(
            photons_per_subap_frame=1.0e6,
            read_noise_e=0.0,
            prnu_rms=0.0,
            prnu_mode="persistent",
        ),
        wfs_wavelength_m=wavelength_m,
        random_streams=streams,
        centroid_config=CentroidConfig(),
        validity_config=CentroidValidityConfig(
            min_flux_e=0.0,
            min_peak_snr=0.0,
            max_centroid_sigma_px=1.0e6,
            max_window_clipping_fraction=1.0,
        ),
    )
    interaction = calibrate_interaction_matrix(
        DmActuatorProbeBasis(dm),
        sensor,
        10.0e-9,
        random_streams=streams,
    )
    reconstructor = LeastSquaresReconstructor(
        interaction,
        min_valid_fraction=1.0,
        min_rank=1,
    )
    projector = IdentityCommandProjector(dm.actuator_ids)
    config = LoopConfig(
        n_steps=2,
        gain=0.5,
        leak=0.0,
        latency_frames=0,
        frame_rate_hz=500.0,
        root_seed=streams.root_seed,
    )
    controller = LeakyIntegratorController.from_loop_config(
        dm.actuator_ids,
        config,
    )
    commands = np.linspace(-20.0e-9, 20.0e-9, dm.n_actuators)
    truth = dm.opd_from_commands(
        DmCommandVector(commands, dm.actuator_ids, "m_opd_equivalent")
    )
    atmosphere = StaticOpdAtmosphere(
        truth.correction_opd_m,
        geometry.pupil_mask,
        root_seed=config.root_seed,
    )

    history = run_closed_loop(
        config,
        random_streams=streams,
        atmosphere=atmosphere,
        wfs=sensor,
        dm=dm,
        interaction_matrix=interaction,
        reconstructor=reconstructor,
        command_projector=projector,
        controller=controller,
        include_noise=False,
    )

    assert isinstance(sensor, WavefrontSensor)
    assert interaction.measurement_unit == "pixel"
    assert interaction.rank >= 1
    np.testing.assert_array_equal(history.reconstruction_usable, True)
    np.testing.assert_allclose(history.valid_measurement_fraction, 1.0)
    np.testing.assert_allclose(history.valid_subaperture_fraction, 1.0)
    assert history.post_update_residual_opd_rms_m[-1] < (
        history.pre_update_residual_opd_rms_m[0]
    )
    assert history.metadata["backend_names"]["wfs"] == "native"
