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


class _DelegatingNativeFactory:
    """A registered ``native`` factory that is as mutable as any real one.

    A backend factory is an ordinary object, so what a registry key builds can
    change without the object under that key changing: ``static_scale`` here
    stands for any parameter a factory closes over, and rebinding one of the
    ``build_*`` methods would do the same.  At ``static_scale == 1.0`` it builds
    exactly what the native factory builds, which is what makes a
    behavior-identical replacement expressible in a test at all.
    """

    backend_name = "native"

    def __init__(self, delegate: object, *, static_scale: float = 1.0) -> None:
        self._delegate = delegate
        self.static_scale = static_scale

    def build_geometry(self, **kwargs: object) -> object:
        return self._delegate.build_geometry(**kwargs)  # type: ignore[attr-defined]

    def build_dm(self, **kwargs: object) -> object:
        return self._delegate.build_dm(**kwargs)  # type: ignore[attr-defined]

    def build_wfs(self, **kwargs: object) -> object:
        return self._delegate.build_wfs(**kwargs)  # type: ignore[attr-defined]

    def build_science_propagator(self, **kwargs: object) -> object:
        return self._delegate.build_science_propagator(**kwargs)  # type: ignore[attr-defined]

    def build_atmosphere(self, **kwargs: object) -> object:
        kwargs["static_opd_rms_m"] = (
            kwargs["static_opd_rms_m"] * self.static_scale  # type: ignore[operator]
        )
        return self._delegate.build_atmosphere(**kwargs)  # type: ignore[attr-defined]


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

    # The evidence travels with the system, so nothing a *later* build does can
    # take it away.  Building many other configurations in between used to evict
    # this system's entry from a bounded process-wide memo and charge its next
    # run a second calibration.
    for index in range(80):
        scao.build_scao_system(
            replace(config, controller=replace(config.controller, n_steps=2 + index))
        )
    calibrations.clear()
    scao.run_closed_loop(config, system=system)
    assert calibrations == []

    # A system this process did not build carries no evidence, so it is still
    # verified — by building its configuration.  The attestation is an
    # optimization, never the trust boundary.
    other_config = replace(
        config,
        atmosphere=replace(config.atmosphere, target_rms_opd_m=45.0e-9),
    )
    other = scao.build_scao_system(other_config)
    calibrations.clear()
    scao.run_closed_loop(other_config, system=replace(other, build_attestation=None))
    assert len(calibrations) == 1  # the unattested rebuild

    # And a forged system is rejected on that unattested path exactly as on the
    # attested one: the rebuild remains the authority when nothing is attested.
    stronger = scao.build_scao_system(
        replace(config, atmosphere=replace(config.atmosphere, target_rms_opd_m=60.0e-9))
    )
    forged_hashes = dict(system.component_hashes)
    forged_hashes["atmosphere"] = stronger.component_hashes["atmosphere"]
    forged = replace(
        system,
        atmosphere=stronger.atmosphere,
        component_hashes=forged_hashes,
        build_attestation=None,
    )
    with pytest.raises(
        scao.ScaoConstructionError,
        match="do not match the components its source configuration rebuilds",
    ):
        scao.run_closed_loop(config, system=forged)


def test_a_build_attestation_cannot_be_minted_or_retargeted_by_a_caller() -> None:
    """The attestation is evidence of a build, not a licence to skip one.

    Three forgeries have to fail for it to be safe to trust: constructing one
    for component identities no build produced, deriving one from a genuine
    attestation with the hashes restated, and moving a genuine one onto a system
    whose components it does not describe.  None of them raises — each simply
    produces something this process never minted, so verification falls back to
    the rebuild that was always the authority.
    """

    config = _tiny_system_config()
    system = scao.build_scao_system(config)
    stronger = scao.build_scao_system(
        replace(config, atmosphere=replace(config.atmosphere, target_rms_opd_m=60.0e-9))
    )

    # Constructed by a caller rather than minted by a build.
    handmade = scao._BuildAttestation(
        factory_backend=config.backend,
        factory_epoch=scao._factory_epoch(config.backend),
        source_config=config,
        supplied_matrix_identity=None,
        component_hashes=dict(system.component_hashes),
    )
    assert handmade not in scao._MINTED_ATTESTATIONS
    assert scao._attested_build_identity(
        replace(system, build_attestation=handmade), None
    ) is None

    # Derived from a genuine one with dataclasses.replace: a new object, so the
    # minted set has never seen it, however faithfully it copies the original.
    assert system.build_attestation is not None
    derived = replace(system.build_attestation)
    assert derived not in scao._MINTED_ATTESTATIONS
    assert scao._attested_build_identity(
        replace(system, build_attestation=derived), None
    ) is None
    # The honest system is unaffected and still spends its own attestation.
    assert scao._attested_build_identity(system, None) == dict(system.component_hashes)

    # A genuine attestation carried by a system whose components it does not
    # describe is unusable, so verification falls back to the rebuild and the
    # swap is caught there.
    forged_hashes = dict(system.component_hashes)
    forged_hashes["atmosphere"] = stronger.component_hashes["atmosphere"]
    forged = replace(
        system,
        atmosphere=stronger.atmosphere,
        component_hashes=forged_hashes,
    )
    assert forged.build_attestation is system.build_attestation
    assert scao._attested_build_identity(forged, None) is None
    with pytest.raises(
        scao.ScaoConstructionError,
        match="do not match the components its source configuration rebuilds",
    ):
        scao.run_closed_loop(config, system=forged)

    # The complete forgery: swap the component, restate the hashes, and restate
    # the attestation to agree with them, so every self-consistency check inside
    # the system passes.  It is still not a build that happened.
    restated = replace(
        forged,
        build_attestation=replace(
            system.build_attestation, component_hashes=forged_hashes
        ),
    )
    with pytest.raises(
        scao.ScaoConstructionError,
        match="do not match the components its source configuration rebuilds",
    ):
        scao.run_closed_loop(config, system=restated)

    # A ScaoSystem never accepts a foreign object in the attestation slot.
    with pytest.raises(scao.ScaoConstructionError, match="must be a BuildAttestation"):
        replace(system, build_attestation="trust me")


def test_a_supplied_interaction_matrix_is_part_of_the_attested_identity() -> None:
    """A supplied matrix is an input to the build, not a product of it.

    Two systems can share a configuration and differ only in the matrix handed
    to them, so an attested identity is only reusable for the same matrix —
    otherwise it would answer for a build that never happened.
    """

    build_config = _tiny_system_config()
    first_matrix = scao.build_scao_system(build_config).interaction_matrix
    other_matrix = scao.build_scao_system(
        replace(
            build_config,
            calibration=replace(build_config.calibration, amplitude_m=2.0e-8),
        )
    ).interaction_matrix
    assert first_matrix.matrix_hash != other_matrix.matrix_hash

    supplied_config = replace(
        build_config,
        calibration=replace(build_config.calibration, source="supplied"),
    )
    first = scao.build_scao_system(supplied_config, interaction_matrix=first_matrix)
    second = scao.build_scao_system(supplied_config, interaction_matrix=other_matrix)

    # Same configuration, different supplied matrix, therefore different
    # attested identities that answer only for their own matrix.
    assert scao._attested_build_identity(first, first_matrix) == dict(
        first.component_hashes
    )
    assert scao._attested_build_identity(second, other_matrix) == dict(
        second.component_hashes
    )
    assert scao._attested_build_identity(first, other_matrix) is None
    assert scao._attested_build_identity(first, None) is None
    assert first.component_hashes["interaction_matrix"] != (
        second.component_hashes["interaction_matrix"]
    )

    # And both verify against their own matrix rather than each other's.
    scao.run_closed_loop(supplied_config, system=first)
    scao.run_closed_loop(supplied_config, system=second)


def test_an_attested_identity_is_only_reused_for_an_equal_configuration() -> None:
    """The attestation names a configuration, and that name is checked.

    A system whose ``source_config`` was replaced after the build carries
    evidence about a different configuration, so the evidence must not be
    spent on it; verification falls back to the rebuild instead.
    """

    config = _tiny_system_config()
    system = scao.build_scao_system(config)
    assert scao._attested_build_identity(system, None) == dict(system.component_hashes)

    stranger = replace(
        config,
        atmosphere=replace(config.atmosphere, target_rms_opd_m=90.0e-9),
    )
    # Same components and same recorded hashes, a different claimed source.
    retargeted = replace(
        system,
        source_config=stranger,
        config_hash=stranger.config_hash,
    )
    assert scao._attested_build_identity(retargeted, None) is None

    # The fallback rebuild is the authority, and it refuses the retargeted
    # system because that configuration builds a different atmosphere.
    with pytest.raises(
        scao.ScaoConstructionError,
        match="do not match the components its source configuration rebuilds",
    ):
        scao.run_closed_loop(stranger, system=retargeted)

    # The honest system still runs.
    scao.run_closed_loop(config, system=system)


def test_replacing_a_backend_factory_invalidates_every_build_attestation() -> None:
    """The factory registry is an input to what a configuration builds.

    It is not named by an attestation, so attested identities outlive the
    factory set that produced them.  Serving one afterwards answers verification
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

    # Registering a backend for the FIRST time invalidates nothing: no
    # configuration could have been built against a backend that was not yet
    # registered, and retiring attestations there would put back the
    # rebuild-and-recalibrate cost they exist to avoid.
    epoch = scao._factory_epoch("native")
    scao._factory_for("hcipy")
    assert scao._factory_epoch("native") == epoch
    assert scao._attested_build_identity(system, None) == dict(system.component_hashes)

    try:
        scao.register_scao_backend_factory("native", StrongerAberration(), replace=True)
        assert scao._factory_epoch("native") != epoch
        # The system on hand is no longer what this registry builds, so its
        # attestation is retired and it must be refused by the rebuild.
        assert scao._attested_build_identity(system, None) is None
        with pytest.raises(
            scao.ScaoConstructionError,
            match="do not match the components its source configuration rebuilds",
        ):
            scao.run_closed_loop(config, system=system)

        # And the converse: an attestation minted under the replaced factory
        # must not outlive it and reject an honest system afterwards.
        scao.build_scao_system(config)
        scao.register_scao_backend_factory("native", honest_factory, replace=True)
        scao.run_closed_loop(config, system=system)
    finally:
        scao.register_scao_backend_factory("native", honest_factory, replace=True)


def test_re_registering_a_mutated_factory_object_retires_its_attestations() -> None:
    """Object identity is no evidence that a key still builds the same thing.

    Registering the same object again is the case an identity comparison would
    dismiss as a no-op, and it is exactly the case that must not be dismissed:
    the object may have been mutated in between, so the key now builds
    something the attestations minted against it never described.  An explicit
    ``replace=True`` is the caller's claim that the registry changed, and it is
    the only claim available here — nothing about a factory object can be
    hashed into an identity this module could compare instead.
    """

    config = _tiny_system_config()
    honest_factory = scao._factory_for("native")
    mutable = _DelegatingNativeFactory(honest_factory)

    try:
        scao.register_scao_backend_factory("native", mutable, replace=True)
        system = scao.build_scao_system(config)
        # Unmutated, the factory builds what the system records, so it runs.
        scao.run_closed_loop(config, system=system)

        mutable.static_scale = 3.0
        scao.register_scao_backend_factory("native", mutable, replace=True)
        assert scao._FACTORIES["native"] is mutable
        assert (
            scao.build_scao_system(config).component_hashes["atmosphere"]
            != system.component_hashes["atmosphere"]
        )

        assert scao._attested_build_identity(system, None) is None
        with pytest.raises(
            scao.ScaoConstructionError,
            match="do not match the components its source configuration rebuilds",
        ):
            scao.run_closed_loop(config, system=system)

        # And it stays refused.  The rebuild that rejected it disagreed with
        # what the system records, so it has nothing to attest about this
        # system and must leave it carrying no usable evidence.
        assert scao._attested_build_identity(system, None) is None
        with pytest.raises(
            scao.ScaoConstructionError,
            match="do not match the components its source configuration rebuilds",
        ):
            scao.run_closed_loop(config, system=system)
    finally:
        scao.register_scao_backend_factory("native", honest_factory, replace=True)


def test_a_first_lazy_registration_leaves_its_backend_epoch_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Loading a built-in backend on first use must not cost anything.

    ``_factory_for`` registers a built-in the first time a configuration asks
    for it, with ``replace`` left false.  Nothing could have been built against
    a key that held no factory, so there is nothing to retire, and moving the
    epoch there would charge every system on hand a rebuild and a
    recalibration for a backend it does not even use.
    """

    monkeypatch.delitem(scao._FACTORIES, "hcipy", raising=False)
    before = scao._factory_epoch("hcipy")

    assert scao._factory_for("hcipy").backend_name == "hcipy"

    assert scao._factory_epoch("hcipy") == before


def test_a_behavior_identical_replacement_costs_one_rebuild_not_one_per_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rebuild that clears a retired attestation must be remembered.

    A replacement retires every attestation for its key, including those of
    systems the new factory builds identically.  The first run after it pays a
    rebuild to re-establish that agreement, which is the price of the registry
    having changed; paying it again on every later run of the same system is
    not, and for a profile that calibrates on build each of those runs is a
    full interaction-matrix calibration.
    """

    calibrations: list[None] = []
    real_calibrate = scao.calibrate_interaction_matrix

    def counting_calibrate(*args: object, **kwargs: object) -> object:
        calibrations.append(None)
        return real_calibrate(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(scao, "calibrate_interaction_matrix", counting_calibrate)

    config = _tiny_system_config()
    assert config.calibration.source == "build"
    honest_factory = scao._factory_for("native")
    system = scao.build_scao_system(config)
    assert len(calibrations) == 1

    try:
        scao.register_scao_backend_factory(
            "native",
            _DelegatingNativeFactory(honest_factory),
            replace=True,
        )
        calibrations.clear()
        scao.run_closed_loop(config, system=system)
        scao.run_closed_loop(config, system=system)
        scao.run_closed_loop(config, system=system)
        assert len(calibrations) == 1
    finally:
        scao.register_scao_backend_factory("native", honest_factory, replace=True)


def test_replacing_one_backend_leaves_the_other_backends_attested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalidation is scoped to the registry key that actually changed.

    A configuration resolves exactly one backend, so replacing the HCIPy
    factory says nothing about what a native configuration builds.  Retiring
    native attestations there would make installing or swapping an optional
    backend recalibrate every native system in the session.
    """

    calibrations: list[None] = []
    real_calibrate = scao.calibrate_interaction_matrix

    def counting_calibrate(*args: object, **kwargs: object) -> object:
        calibrations.append(None)
        return real_calibrate(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(scao, "calibrate_interaction_matrix", counting_calibrate)

    config = _tiny_system_config()
    assert config.backend == "native"
    system = scao.build_scao_system(config)
    hcipy_factory = scao._factory_for("hcipy")

    class _InertHcipyFactory:
        """Registered under 'hcipy' and never called by a native profile."""

        backend_name = "hcipy"

        def build_geometry(self, **kwargs: object) -> object:
            raise AssertionError("a native profile resolved the hcipy factory")

        def build_atmosphere(self, **kwargs: object) -> object:
            raise AssertionError("a native profile resolved the hcipy factory")

        def build_wfs(self, **kwargs: object) -> object:
            raise AssertionError("a native profile resolved the hcipy factory")

        def build_dm(self, **kwargs: object) -> object:
            raise AssertionError("a native profile resolved the hcipy factory")

        def build_science_propagator(self, **kwargs: object) -> object:
            raise AssertionError("a native profile resolved the hcipy factory")

    try:
        scao.register_scao_backend_factory(
            "hcipy", _InertHcipyFactory(), replace=True
        )
        assert scao._attested_build_identity(system, None) == dict(
            system.component_hashes
        )
        calibrations.clear()
        scao.run_closed_loop(config, system=system)
        assert calibrations == []
    finally:
        scao.register_scao_backend_factory("hcipy", hcipy_factory, replace=True)


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
