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


def test_component_hashes_are_bound_to_the_live_components() -> None:
    config = _tiny_system_config()
    system = scao.build_scao_system(config)

    class _ForeignAtmosphere:
        backend_name = "native"
        config_hash = "f" * 64

    # Swapping a component while retaining the recorded hashes must not
    # construct: the identity record would describe an atmosphere that is
    # not the one the system holds.
    with pytest.raises(
        scao.ScaoConstructionError,
        match="recomputed from the live components",
    ):
        replace(system, atmosphere=_ForeignAtmosphere())

    # Tampering with the recorded identity itself is rejected the same way.
    forged = dict(system.component_hashes)
    forged["atmosphere"] = "f" * 64
    with pytest.raises(scao.ScaoConstructionError, match="atmosphere"):
        replace(system, component_hashes=forged)

    # Dropping a required identity entry is a construction error, not a
    # silently narrower record.
    partial = dict(system.component_hashes)
    del partial["controller"]
    with pytest.raises(scao.ScaoConstructionError, match="controller"):
        replace(system, component_hashes=partial)

    # An honest replace that keeps the same components reconstructs cleanly.
    rebuilt = replace(system, component_hashes=dict(system.component_hashes))
    assert dict(rebuilt.component_hashes) == dict(system.component_hashes)


def test_supplied_system_components_must_match_its_source_configuration() -> None:
    # Reproduces the review's 30 nm -> 90 nm swap: a valid stronger atmosphere
    # carrying its own correct component hash is spliced into a system whose
    # retained config_hash/source_config still name the weaker profile.  The
    # frozen dataclass accepts the internally self-consistent record, but the
    # run must refuse to execute components the recorded configuration did not
    # build.
    config = _tiny_system_config()
    stronger_config = replace(
        config,
        atmosphere=replace(config.atmosphere, target_rms_opd_m=60.0e-9),
    )
    system = scao.build_scao_system(config)
    stronger = scao.build_scao_system(stronger_config)
    assert (
        stronger.component_hashes["atmosphere"]
        != system.component_hashes["atmosphere"]
    )

    forged_hashes = dict(system.component_hashes)
    forged_hashes["atmosphere"] = stronger.component_hashes["atmosphere"]
    # Internally self-consistent (live atmosphere matches its recorded hash),
    # so the frozen dataclass still constructs, and the retained identity keeps
    # naming the weaker profile.
    forged = replace(
        system,
        atmosphere=stronger.atmosphere,
        component_hashes=forged_hashes,
    )
    assert forged.config_hash == config.config_hash
    assert forged.source_config == config

    with pytest.raises(
        scao.ScaoConstructionError,
        match="do not match the components its source configuration rebuilds",
    ):
        scao.run_closed_loop(config, system=forged)

    # The honest system still runs against the same configuration and matches a
    # freshly built run.
    history = scao.run_closed_loop(config, system=system)
    fresh = scao.run_closed_loop(config)
    np.testing.assert_array_equal(
        history.post_update_residual_opd_rms_m,
        fresh.post_update_residual_opd_rms_m,
    )


def test_running_a_supplied_system_never_rebuilds_or_recalibrates_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verification must cost a comparison, not a second calibration.

    Every packaged profile calibrates on build, including the 384-pixel ones, so
    a verification that rebuilt the system would make each closed loop pay for a
    full interaction-matrix calibration it already has.
    """

    calibrations: list[None] = []
    real_calibrate = scao.calibrate_interaction_matrix

    def counting_calibrate(*args: object, **kwargs: object) -> object:
        calibrations.append(None)
        return real_calibrate(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(scao, "calibrate_interaction_matrix", counting_calibrate)

    config = _tiny_system_config()
    assert config.calibration.source == "build"
    system = scao.build_scao_system(config)
    assert len(calibrations) == 1

    scao.run_closed_loop(config, system=system)
    scao.run_closed_loop(config, system=system)
    assert len(calibrations) == 1

    # A configuration this process has never built is still verified — by
    # building it — so the memo is an optimization, never the trust boundary.
    other_config = replace(
        config,
        atmosphere=replace(config.atmosphere, target_rms_opd_m=45.0e-9),
    )
    other = scao.build_scao_system(other_config)
    monkeypatch.setattr(scao, "_BUILD_IDENTITY_MEMO", {})
    scao.run_closed_loop(other_config, system=other)
    assert len(calibrations) == 3  # the build above, plus one cold-memo rebuild

    # And a forged system is rejected on that cold path exactly as on the warm
    # one: the rebuild remains the authority when nothing is remembered.
    stronger = scao.build_scao_system(
        replace(config, atmosphere=replace(config.atmosphere, target_rms_opd_m=60.0e-9))
    )
    forged_hashes = dict(system.component_hashes)
    forged_hashes["atmosphere"] = stronger.component_hashes["atmosphere"]
    forged = replace(
        system,
        atmosphere=stronger.atmosphere,
        component_hashes=forged_hashes,
    )
    monkeypatch.setattr(scao, "_BUILD_IDENTITY_MEMO", {})
    with pytest.raises(
        scao.ScaoConstructionError,
        match="do not match the components its source configuration rebuilds",
    ):
        scao.run_closed_loop(config, system=forged)


def test_replacing_a_backend_factory_invalidates_the_build_identity_memo() -> None:
    """The factory registry is an input to what a configuration builds.

    It is not part of the memo key, so a remembered identity outlives the
    factory set that produced it.  Serving it afterwards answers verification
    from a build that can no longer happen — in both directions: accepting a
    system this registry would not build, and rejecting one it would.
    """

    config = _tiny_system_config()
    honest_factory = scao._factory_for("native")
    system = scao.build_scao_system(config)
    scao.run_closed_loop(config, system=system)

    class StrongerAberration:
        """A registered factory that builds a materially different atmosphere."""

        backend_name = "native"

        def build_geometry(self, **kwargs: object) -> object:
            return honest_factory.build_geometry(**kwargs)  # type: ignore[arg-type]

        def build_dm(self, **kwargs: object) -> object:
            return honest_factory.build_dm(**kwargs)  # type: ignore[arg-type]

        def build_wfs(self, **kwargs: object) -> object:
            return honest_factory.build_wfs(**kwargs)  # type: ignore[arg-type]

        def build_science_propagator(self, **kwargs: object) -> object:
            return honest_factory.build_science_propagator(**kwargs)  # type: ignore[arg-type]

        def build_atmosphere(self, **kwargs: object) -> object:
            # Three times the static aberration this profile asked for.
            kwargs["static_opd_rms_m"] = kwargs["static_opd_rms_m"] * 3.0  # type: ignore[operator]
            return honest_factory.build_atmosphere(**kwargs)  # type: ignore[arg-type]

    try:
        scao.register_scao_backend_factory("native", StrongerAberration(), replace=True)
        # The system on hand is no longer what this registry builds, so it must
        # be refused rather than accepted from the pre-replacement memory.
        with pytest.raises(
            scao.ScaoConstructionError,
            match="do not match the components its source configuration rebuilds",
        ):
            scao.run_closed_loop(config, system=system)

        # And the converse: an identity remembered under the replaced factory
        # must not outlive it and reject an honest system afterwards.
        scao.build_scao_system(config)
        scao.register_scao_backend_factory("native", honest_factory, replace=True)
        scao.run_closed_loop(config, system=system)
    finally:
        scao.register_scao_backend_factory("native", honest_factory, replace=True)


def test_supplied_system_is_rejected_when_a_live_component_drifts_after_build() -> None:
    """A hash-covered identity mutated after construction must not run.

    ``ScaoSystem`` binds ``component_hashes`` to its components at construction,
    so a later mutation leaves the record describing components that no longer
    exist.  Registering a further random-stream domain changes the recorded
    stream identity — and therefore which seeded streams the loop can draw —
    without touching any config, so it is exactly the drift the run must catch.
    """

    config = _tiny_system_config()
    system = scao.build_scao_system(config)
    # Honest first: the unmutated system runs.
    scao.run_closed_loop(config, system=system)

    before = system.random_streams.registered_domains
    system.random_streams.register_domain("post_build_extra")
    assert system.random_streams.registered_domains != before

    with pytest.raises(
        scao.ScaoConstructionError,
        match="no longer carry the identity it records",
    ):
        scao.run_closed_loop(config, system=system)


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


def test_hcipy_backend_resolves_through_the_shipped_registry_fail_closed() -> None:
    # The registry entry itself is dependency-free: resolving the factory and
    # rejecting profiles the HCIPy backend cannot represent must work whether
    # or not the optional dependency is installed.
    assert set(scao._BUILTIN_FACTORY_LOADERS) == {"native", "hcipy"}
    factory = scao._factory_for("hcipy")
    assert factory.backend_name == "hcipy"
    assert isinstance(factory, scao.ScaoBackendComponentFactory)

    from shwfs_ao.backends.hcipy.factory import HcipyScaoFactoryError

    base = _tiny_system_config("detector_level")
    native_atmosphere_on_hcipy = replace(base, backend="hcipy")
    with pytest.raises(HcipyScaoFactoryError, match="builds only 'hcipy'"):
        scao.build_scao_system(native_atmosphere_on_hcipy)

    normalized_hcipy = replace(
        base,
        backend="hcipy",
        atmosphere_model="hcipy",
    )
    with pytest.raises(HcipyScaoFactoryError, match="no RMS normalization"):
        scao.build_scao_system(normalized_hcipy)

    # The detector-window contract is checked before any optical
    # construction: the HCIPy lenslet model measures on fixed block windows
    # of pupil_pixels // lenslets_across.
    geometry = factory.build_geometry(
        telescope_diameter_m=base.telescope_diameter_m,
        pupil_pixels=base.pupil_pixels,
        lenslets_across=base.lenslets_across,
        min_fill_fraction=base.wfs.min_fill_fraction,
        central_obstruction_ratio=base.wfs.central_obstruction_ratio,
        spider_width_m=base.wfs.spider_width_m,
    )
    with pytest.raises(HcipyScaoFactoryError, match="fixed block windows"):
        factory.build_wfs(
            model="detector_level",
            geometry=geometry,
            wfs_wavelength_m=base.wfs_wavelength_m,
            pad_factor=2,
            detector_window_px=8,
            detector_config=None,
            centroid_config=None,
            validity_config=None,
            random_streams=scao.NamedRandomStreams(base.random.root_seed),
        )
    with pytest.raises(HcipyScaoFactoryError, match="geometric"):
        factory.build_wfs(
            model="geometric",
            geometry=geometry,
            wfs_wavelength_m=base.wfs_wavelength_m,
            pad_factor=None,
            detector_window_px=None,
            detector_config=None,
            centroid_config=None,
            validity_config=None,
            random_streams=scao.NamedRandomStreams(base.random.root_seed),
        )


def test_wfs_photon_allocation_threads_from_config_through_the_factory() -> None:
    base = _tiny_system_config("detector_level")
    assert base.wfs.photon_allocation == "throughput_scaled"

    default_system = scao.build_scao_system(base)
    # The assembled sensor carries the config's allocation policy verbatim.
    assert default_system.wfs.calibration.photon_allocation == "throughput_scaled"

    unit_sum_config = replace(
        base, wfs=replace(base.wfs, photon_allocation="unit_sum")
    )
    unit_sum_system = scao.build_scao_system(unit_sum_config)
    assert unit_sum_system.wfs.calibration.photon_allocation == "unit_sum"

    # The choice reaches the calibrated realization, so the live WFS component
    # identity — not just the config — differs from the throughput default.
    assert (
        unit_sum_system.wfs.calibration.config_hash
        != default_system.wfs.calibration.config_hash
    )
    assert (
        unit_sum_system.component_hashes["wfs"]
        != default_system.component_hashes["wfs"]
    )


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
