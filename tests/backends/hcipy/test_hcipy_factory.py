"""Contracts for the registered HCIPy SCAO component factory.

Every test requires the optional HCIPy dependency and carries the ``hcipy``
marker so native CI selections never execute it.  The module is part of the
portable wheel-smoke bundle, so it imports only the installed package.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest


hcipy = pytest.importorskip("hcipy")

from shwfs_ao.backends.hcipy.factory import (
    HCIPY_SCAO_COMPONENT_FACTORY,
    HcipyScaoComponentFactory,
)
from shwfs_ao.core.provenance import Provenance
from shwfs_ao.experiments import scao
from shwfs_ao.io.configs import (
    AtmosphereConfig,
    CalibrationConfig,
    CommandProjectorConfig,
    ControllerConfig,
    DetectorSystemConfig,
    DmSystemConfig,
    ProfileProvenance,
    RandomSeedConfig,
    ReconstructorConfig,
    ScienceConfig,
    SystemConfig,
    WfsConfig,
)


pytestmark = pytest.mark.hcipy


def _tiny_hcipy_system_config() -> SystemConfig:
    """A minimal all-HCIPy profile: 18 px pupil, 3 lenslets, 6 px windows."""

    return SystemConfig(
        backend="hcipy",
        wfs_model="detector_level",
        atmosphere_model="hcipy",
        telescope_diameter_m=1.0,
        pupil_pixels=18,
        lenslets_across=3,
        actuators_across=3,
        wfs_wavelength_m=700.0e-9,
        science_wavelengths_m=(1.25e-6, 1.65e-6),
        atmosphere=AtmosphereConfig(
            r0_m=0.15,
            r0_reference_wavelength_m=500.0e-9,
            outer_scale_m=25.0,
            wind_m_per_s=(10.0, 0.0),
            target_rms_opd_m=None,
            normalize_rms=False,
        ),
        detector=DetectorSystemConfig(
            enabled=True,
            photons_per_subap_frame=1.0e6,
            read_noise_e=0.0,
            dark_e_per_s=0.0,
            background_e_per_pixel_frame=0.0,
            full_well_e=None,
            qe=1.0,
            prnu_rms=0.0,
            exposure_s=1.0e-3,
            prnu_mode="persistent",
            bad_pixel_fraction=0.0,
        ),
        wfs=WfsConfig(
            min_fill_fraction=0.3,
            pad_factor=2,
            detector_window_px=6,
            centroid_estimator="center_of_gravity",
            threshold_fraction=0.0,
            subtract_minimum=False,
            min_flux_e=0.0,
            min_peak_snr=0.0,
            max_centroid_sigma_px=1.0e6,
            max_window_clipping_fraction=1.0,
            central_obstruction_ratio=0.0,
            spider_width_m=0.0,
        ),
        dm=DmSystemConfig(
            influence_model="gaussian",
            coupling_width_pitch=0.35,
            stroke_limit_opd_m=250.0e-9,
            include_edge_actuators=True,
            actuator_margin_fraction=0.0,
            dead_actuator_indices=(),
            stuck_actuator_indices=(),
            stuck_command_opd_m=0.0,
        ),
        calibration=CalibrationConfig(
            source="build",
            method="central",
            probe_kind="dm_actuator",
            amplitude_m=10.0e-9,
            include_noise=False,
            repeats=1,
            resource_name=None,
        ),
        reconstructor=ReconstructorConfig(
            kind="least_squares",
            rcond=None,
            alpha=None,
            min_valid_fraction=0.5,
            min_rank=1,
            max_cached_masks=4,
        ),
        command_projector=CommandProjectorConfig(
            kind="identity",
            mapping_resource=None,
        ),
        controller=ControllerConfig(
            n_steps=2,
            gain=0.5,
            leak=0.0,
            latency_frames=0,
            frame_rate_hz=500.0,
            include_noise=False,
        ),
        science=ScienceConfig(psf_pad_factor=2),
        random=RandomSeedConfig(root_seed=23),
        profile=ProfileProvenance(
            profile_name="tiny_hcipy",
            profile_version=1,
            baseline_rationale=(
                "Tiny deterministic all-HCIPy factory contract profile."
            ),
            provenance=Provenance(
                source_class="synthetic_assumed",
                source_note="Synthetic values used only for factory tests.",
                source_id="shwfs_ao.system_profile.tiny_hcipy.v1",
            ),
        ),
    )


def test_shipped_factory_is_a_protocol_conforming_frozen_singleton() -> None:
    assert isinstance(
        HCIPY_SCAO_COMPONENT_FACTORY,
        scao.ScaoBackendComponentFactory,
    )
    assert HCIPY_SCAO_COMPONENT_FACTORY.backend_name == "hcipy"
    assert isinstance(HCIPY_SCAO_COMPONENT_FACTORY, HcipyScaoComponentFactory)
    assert scao._factory_for("hcipy") is HCIPY_SCAO_COMPONENT_FACTORY


def test_experiment_runner_executes_a_tiny_all_hcipy_system() -> None:
    config = _tiny_hcipy_system_config()

    system = scao.build_scao_system(config)
    assert set(system.component_hashes) == {
        "random_streams",
        "pupil_geometry",
        "atmosphere",
        "wfs",
        "dm",
        "interaction_matrix",
        "reconstructor",
        "command_projector",
        "controller",
        "science_propagator",
    }
    assert all(len(value) == 64 for value in system.component_hashes.values())

    history = scao.run_closed_loop(config, system=system)
    assert history.n_steps == config.controller.n_steps
    assert history.metadata["backend_names"] == {
        "atmosphere": "hcipy",
        "wfs": "hcipy",
        "dm": "hcipy",
    }
    assert np.all(np.isfinite(history.post_update_residual_opd_rms_m))

    rerun = scao.run_closed_loop(config)
    np.testing.assert_array_equal(
        history.post_update_residual_opd_rms_m,
        rerun.post_update_residual_opd_rms_m,
    )
    np.testing.assert_array_equal(
        history.applied_command_history_opd_m,
        rerun.applied_command_history_opd_m,
    )

    rebuilt = scao.build_scao_system(config)
    assert dict(rebuilt.component_hashes) == dict(system.component_hashes)


def test_wfs_pad_factor_realizes_the_cross_backend_spot_sampling() -> None:
    # The serialized ``wfs.pad_factor`` keeps one meaning across backends:
    # spot sampling in detector pixels per lambda/d.  The HCIPy adapter
    # realizes it through the equivalent lenslet f-number, exactly the
    # accepted cross-backend baseline derivation.
    config = _tiny_hcipy_system_config()
    system = scao.build_scao_system(config)

    geometry = system.wfs.geometry
    pixel_pitch_m = float(geometry.x_m[0, 1] - geometry.x_m[0, 0])
    expected_f_number = (
        config.wfs.pad_factor * pixel_pitch_m / config.wfs_wavelength_m
    )
    assert system.wfs.optics_backend.f_number == pytest.approx(
        expected_f_number
    )


def test_stronger_seeing_changes_measurements_but_not_identities() -> None:
    config = _tiny_hcipy_system_config()
    stronger = replace(
        config,
        atmosphere=replace(config.atmosphere, r0_m=0.075),
    )

    baseline = scao.run_closed_loop(config)
    perturbed = scao.run_closed_loop(stronger)
    assert not np.array_equal(
        baseline.post_update_residual_opd_rms_m,
        perturbed.post_update_residual_opd_rms_m,
    )
    assert baseline.config_hash != perturbed.config_hash
