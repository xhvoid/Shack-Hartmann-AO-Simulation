"""Contracts for the registered HCIPy SCAO component factory.

Every test requires the optional HCIPy dependency and carries the ``hcipy``
marker so native CI selections never execute it.  The module is part of the
portable wheel-smoke bundle, so it imports only the installed package.
"""

from __future__ import annotations

from dataclasses import replace
import warnings

import numpy as np
import pytest


hcipy = pytest.importorskip("hcipy")

from shwfs_ao.backends.hcipy.factory import (
    HCIPY_SCAO_COMPONENT_FACTORY,
    HcipyScaoComponentFactory,
    HcipyScaoFactoryError,
)
from shwfs_ao.backends.native.factory import (
    NATIVE_SCAO_COMPONENT_FACTORY,
    NativeScaoFactoryError,
)
from shwfs_ao.control.loop import ControlLoopWarning
from shwfs_ao.core.provenance import Provenance
from shwfs_ao.core.random import NamedRandomStreams
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
    load_system_profile,
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


def test_native_layered_profiles_are_refused_rather_than_flattened() -> None:
    """``native_layered`` names the native generator; HCIPy never builds it."""

    config = replace(
        load_system_profile("eso_turbulence_2m_detector", 1), backend="hcipy"
    )
    with pytest.raises(HcipyScaoFactoryError, match="native_layered"):
        scao.build_scao_system(config)


def _eso_atmosphere_inputs() -> tuple[object, dict[str, object]]:
    config = load_system_profile("eso_turbulence_2m_detector", 1)
    geometry = HCIPY_SCAO_COMPONENT_FACTORY.build_geometry(
        telescope_diameter_m=config.telescope_diameter_m,
        pupil_pixels=config.pupil_pixels,
        lenslets_across=config.lenslets_across,
        min_fill_fraction=config.wfs.min_fill_fraction,
        central_obstruction_ratio=config.wfs.central_obstruction_ratio,
        spider_width_m=config.wfs.spider_width_m,
    )
    atmosphere = config.atmosphere
    return atmosphere, dict(
        geometry=geometry,
        random_streams=NamedRandomStreams(config.random.root_seed),
        r0_m=atmosphere.r0_m,
        outer_scale_m=atmosphere.outer_scale_m,
        phase_reference_wavelength_m=atmosphere.r0_reference_wavelength_m,
        wind_m_per_s=atmosphere.wind_m_per_s,
        target_rms_rad=None,
        normalize_rms=False,
        static_opd_rms_m=0.0,
    )


def test_hcipy_layered_builds_one_hcipy_layer_per_profile_layer() -> None:
    """Each layer keeps its Cn2 share, wind and altitude; r0_i = r0 f_i^(-3/5)."""

    atmosphere, common = _eso_atmosphere_inputs()
    model = HCIPY_SCAO_COMPONENT_FACTORY.build_atmosphere(
        model="hcipy_layered", layers=atmosphere.layers, **common
    )

    metadata = model.metadata
    assert model.backend_name == "hcipy"
    assert metadata["n_layers"] == len(atmosphere.layers) == 10
    assert metadata["total_r0_m"] == pytest.approx(atmosphere.r0_m, rel=1.0e-12)
    assert metadata["r0_reference_wavelength_m"] == atmosphere.r0_reference_wavelength_m
    cn_squared = [entry["integrated_cn_squared_m_1_3"] for entry in metadata["layers"]]
    np.testing.assert_allclose(
        np.asarray(cn_squared) / sum(cn_squared),
        [layer.cn2_fraction for layer in atmosphere.layers],
        rtol=1.0e-12,
    )
    for entry, layer in zip(metadata["layers"], atmosphere.layers):
        assert entry["kind"] == "infinite"
        assert entry["r0_m"] == pytest.approx(
            atmosphere.r0_m * layer.cn2_fraction ** (-3.0 / 5.0), rel=1.0e-15
        )
        assert entry["wind_m_per_s"] == layer.wind_m_per_s
        assert entry["altitude_m"] == layer.altitude_m
        assert entry["outer_scale_m"] == atmosphere.outer_scale_m
    assert len(set(metadata["layer_random_stream_ids"])) == 10

    opd = model.opd_at(0.0)
    pupil = common["geometry"].pupil_mask
    assert np.all(np.isfinite(opd[pupil])) and np.all(np.isnan(opd[~pupil]))
    assert abs(float(np.mean(opd[pupil]))) < 1.0e-15


def test_layer_and_model_pairings_fail_closed() -> None:
    atmosphere, common = _eso_atmosphere_inputs()
    factory = HCIPY_SCAO_COMPONENT_FACTORY
    with pytest.raises(HcipyScaoFactoryError, match="exactly the 'hcipy_layered'"):
        factory.build_atmosphere(model="hcipy", layers=atmosphere.layers, **common)
    with pytest.raises(HcipyScaoFactoryError, match="exactly the 'hcipy_layered'"):
        factory.build_atmosphere(model="hcipy_layered", **common)
    with pytest.raises(HcipyScaoFactoryError, match="must sum to 1"):
        factory.build_atmosphere(
            model="hcipy_layered", layers=atmosphere.layers[:-1], **common
        )
    with pytest.raises(HcipyScaoFactoryError, match="winds per layer"):
        factory.build_atmosphere(
            model="hcipy_layered",
            layers=atmosphere.layers,
            **{**common, "wind_m_per_s": (10.0, 0.0)},
        )
    with pytest.raises(HcipyScaoFactoryError, match="no RMS normalization"):
        factory.build_atmosphere(
            model="hcipy_layered",
            layers=atmosphere.layers,
            **{**common, "normalize_rms": True},
        )
    # The native factory names the backend that does build it.
    with pytest.raises(NativeScaoFactoryError, match="backend='hcipy'"):
        NATIVE_SCAO_COMPONENT_FACTORY.build_atmosphere(
            model="hcipy_layered", layers=atmosphere.layers, **common
        )


def test_an_eso_profile_runs_through_the_hcipy_backend() -> None:
    """``hcipy_layered`` is a distinct observing condition the loop can run.

    The HCIPy lenslet model needs whole block windows, which 72 px over 7
    lenslets are not, so the all-HCIPy run uses 70 px and 10 px windows.  The
    narrower window clips a few open-loop spots, so the run accepts 80 %
    valid lenslets.  Every atmosphere value is the published one.
    """

    published = load_system_profile("eso_turbulence_2m_detector", 1)
    config = replace(
        published,
        backend="hcipy",
        atmosphere_model="hcipy_layered",
        pupil_pixels=70,
        wfs=replace(published.wfs, detector_window_px=10),
        reconstructor=replace(published.reconstructor, min_valid_fraction=0.8),
        controller=replace(published.controller, n_steps=4),
    )
    assert config.atmosphere == published.atmosphere
    assert config.observing_conditions_hash != published.observing_conditions_hash

    system = scao.build_scao_system(config)
    assert system.atmosphere.metadata["n_layers"] == 10
    with warnings.catch_warnings():
        warnings.simplefilter("error", ControlLoopWarning)
        history = scao.run_closed_loop(config, system=system)
    assert history.metadata["backend_names"] == {
        "atmosphere": "hcipy",
        "wfs": "hcipy",
        "dm": "hcipy",
    }
    assert np.all(np.isfinite(history.post_update_residual_opd_rms_m))
    assert np.any(history.applied_command_history_opd_m[-1] != 0.0)
