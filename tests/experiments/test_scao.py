"""AO-REF-011 system-factory and shared-runner contract tests."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

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
    system_config_from_mapping,
    system_config_to_mapping,
)


_COMPONENT_HASH_KEYS = {
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


def _tiny_system_config(wfs_model: str = "geometric") -> SystemConfig:
    detector_level = wfs_model == "detector_level"
    profile_name = "tiny_detector" if detector_level else "tiny_geometric"
    return SystemConfig(
        backend="native",
        wfs_model=wfs_model,  # type: ignore[arg-type]
        atmosphere_model="static",
        telescope_diameter_m=1.0,
        pupil_pixels=16,
        lenslets_across=3,
        actuators_across=3,
        wfs_wavelength_m=700.0e-9,
        science_wavelengths_m=(1.25e-6, 1.65e-6),
        atmosphere=AtmosphereConfig(
            r0_m=0.15,
            r0_reference_wavelength_m=500.0e-9,
            outer_scale_m=25.0,
            wind_m_per_s=(10.0, 0.0),
            target_rms_opd_m=30.0e-9,
            normalize_rms=False,
        ),
        detector=DetectorSystemConfig(
            enabled=detector_level,
            photons_per_subap_frame=1.0e6 if detector_level else None,
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
            pad_factor=2 if detector_level else None,
            detector_window_px=8 if detector_level else None,
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
            profile_name=profile_name,
            profile_version=1,
            baseline_rationale=(
                "Tiny deterministic AO-REF-011 orchestration test profile."
            ),
            provenance=Provenance(
                source_class="synthetic_assumed",
                source_note="Synthetic values used only for factory tests.",
                source_id=(
                    f"shwfs_ao.system_profile.{profile_name}.v1"
                ),
            ),
        ),
    )


@pytest.mark.parametrize(
    ("wfs_model", "expected_wfs_backend"),
    (("geometric", "native_geometric"), ("detector_level", "native")),
)
def test_one_experiment_runner_executes_tiny_geometric_and_detector_systems(
    wfs_model: str,
    expected_wfs_backend: str,
) -> None:
    config = _tiny_system_config(wfs_model)

    history = scao.run_closed_loop(config)

    assert history.n_steps == config.controller.n_steps
    assert history.metadata["backend_names"] == {
        "atmosphere": "native",
        "wfs": expected_wfs_backend,
        "dm": "native",
    }
    assert np.all(np.isfinite(history.post_update_residual_opd_rms_m))
    assert history.post_update_residual_opd_rms_m[-1] < (
        history.pre_update_residual_opd_rms_m[0]
    )


def test_serialized_config_and_constructed_component_hashes_are_deterministic() -> None:
    config = _tiny_system_config()
    restored = system_config_from_mapping(system_config_to_mapping(config))

    assert restored == config
    assert restored.config_hash == config.config_hash
    assert dict(restored.component_config_hashes) == dict(
        config.component_config_hashes
    )
    assert all(
        len(value) == 64 for value in config.component_config_hashes.values()
    )

    first = scao.build_scao_system(config)
    second = scao.build_scao_system(restored)
    assert first.config_hash == second.config_hash == config.config_hash
    assert set(first.component_hashes) == _COMPONENT_HASH_KEYS
    assert dict(first.component_hashes) == dict(second.component_hashes)
    assert all(len(value) == 64 for value in first.component_hashes.values())

    first_history = scao.run_closed_loop(config, system=first)
    second_history = scao.run_closed_loop(restored, system=second)
    assert first_history.config_hash == second_history.config_hash
    np.testing.assert_array_equal(
        first_history.post_update_residual_opd_rms_m,
        second_history.post_update_residual_opd_rms_m,
    )
    np.testing.assert_array_equal(
        first_history.applied_command_history_opd_m,
        second_history.applied_command_history_opd_m,
    )


def test_calibration_sources_are_explicit_and_never_fall_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_config = _tiny_system_config()
    built = scao.build_scao_system(build_config)
    matrix = built.interaction_matrix
    assert matrix.provenance.fallback_used is False
    assert "random_scope=calibration" in matrix.provenance.references
    assert "method=central" in matrix.provenance.references

    supplied_config = replace(
        build_config,
        calibration=replace(build_config.calibration, source="supplied"),
    )
    with pytest.raises(
        scao.ScaoConstructionError,
        match="source='supplied' requires interaction_matrix",
    ):
        scao.build_scao_system(supplied_config)
    supplied = scao.build_scao_system(
        supplied_config,
        interaction_matrix=matrix,
    )
    assert supplied.interaction_matrix is matrix
    assert supplied.interaction_matrix.provenance == matrix.provenance

    def unexpected_recalibration(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("calibration fallback was invoked")

    with monkeypatch.context() as patch:
        patch.setattr(
            scao,
            "calibrate_interaction_matrix",
            unexpected_recalibration,
        )
        with pytest.raises(
            scao.ScaoConstructionError,
            match="may only be supplied.*source='supplied'",
        ):
            scao.build_scao_system(
                build_config,
                interaction_matrix=matrix,
            )

    resource_config = replace(
        build_config,
        calibration=replace(
            build_config.calibration,
            source="resource",
            resource_name="synthetic_presets/test_interaction_matrix.json",
        ),
    )
    requested_resources: list[str] = []

    def interaction_resource(name: str) -> dict[str, object]:
        requested_resources.append(name)
        return matrix.to_record()

    with monkeypatch.context() as patch:
        patch.setattr(
            scao,
            "calibrate_interaction_matrix",
            unexpected_recalibration,
        )
        patch.setattr(scao, "_json_resource", interaction_resource)
        loaded = scao.build_scao_system(resource_config)
    assert requested_resources == [resource_config.calibration.resource_name]
    assert loaded.interaction_matrix is not matrix
    assert loaded.interaction_matrix.matrix_hash == matrix.matrix_hash
    assert loaded.interaction_matrix.provenance == matrix.provenance

    missing_resource_config = replace(
        resource_config,
        calibration=replace(
            resource_config.calibration,
            resource_name=(
                "synthetic_presets/does_not_exist_ao_ref_011.json"
            ),
        ),
    )
    with monkeypatch.context() as patch:
        patch.setattr(
            scao,
            "calibrate_interaction_matrix",
            unexpected_recalibration,
        )
        with pytest.raises(
            scao.ScaoConstructionError,
            match="absent; no recalibration fallback is permitted",
        ):
            scao.build_scao_system(missing_resource_config)


def test_unregistered_hcipy_backend_never_falls_back_to_native(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = replace(
        _tiny_system_config(),
        backend="hcipy",
        atmosphere_model="hcipy",
    )

    def unexpected_native_loader() -> object:
        raise AssertionError("native fallback was invoked")

    monkeypatch.setattr(scao, "_FACTORIES", {})
    monkeypatch.setattr(
        scao,
        "_BUILTIN_FACTORY_LOADERS",
        {"native": unexpected_native_loader},
    )
    with pytest.raises(
        scao.ScaoConstructionError,
        match="optional backends never fall back to native",
    ):
        scao.build_scao_system(config)


def test_numerical_scale_is_hashed_separately_from_observing_conditions() -> None:
    config = _tiny_system_config()
    scaled = replace(
        config,
        pupil_pixels=20,
        lenslets_across=4,
        actuators_across=4,
        controller=replace(config.controller, n_steps=3),
    )
    stronger_atmosphere = replace(
        config,
        atmosphere=replace(
            config.atmosphere,
            target_rms_opd_m=60.0e-9,
        ),
    )

    assert scaled.config_hash != config.config_hash
    assert scaled.observing_conditions_hash == config.observing_conditions_hash
    assert stronger_atmosphere.config_hash != config.config_hash
    assert (
        stronger_atmosphere.observing_conditions_hash
        != config.observing_conditions_hash
    )
    assert (
        stronger_atmosphere.component_config_hashes["atmosphere"]
        != config.component_config_hashes["atmosphere"]
    )


def test_component_identity_mismatch_fails_during_construction_preflight() -> None:
    config = _tiny_system_config()
    built = scao.build_scao_system(config)
    incompatible = replace(
        config,
        dm=replace(config.dm, coupling_width_pitch=0.5),
        calibration=replace(config.calibration, source="supplied"),
    )

    with pytest.raises(
        scao.ScaoConstructionError,
        match=(
            "constructed SCAO component identities are inconsistent:.*"
            "interaction_matrix.dm_hash must equal dm.config_hash"
        ),
    ):
        scao.build_scao_system(
            incompatible,
            interaction_matrix=built.interaction_matrix,
        )
