"""Contracts for installed, explicitly versioned SCAO system profiles."""

from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError, replace
import inspect
import math

import pytest

from shwfs_ao.core.provenance import Provenance
from shwfs_ao.io.configs import (
    PROFILE_SCHEMA_NAME,
    PROFILE_SCHEMA_VERSION,
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
    SystemConfigError,
    WfsConfig,
    available_system_profiles,
    load_system_profile,
    system_config_from_mapping,
    system_config_to_mapping,
)


# Every published profile version stays packaged and loadable: a result
# labelled with a v1 profile must remain exactly reproducible after the v2
# review, so v2 supersedes v1 as the recommended profile without retiring it.
EXPECTED_PROFILES = (
    ("fast_2m_detector", 1),
    ("fast_2m_detector", 2),
    ("portfolio_2m_detector", 1),
    ("portfolio_2m_detector", 2),
    ("research_2m_detector", 1),
    ("research_2m_detector", 2),
    ("high_order_10m_geometric", 1),
    ("high_order_10m_geometric", 2),
    ("high_order_10m_hcipy", 1),
    ("high_order_10m_hcipy", 2),
)
CURRENT_2M_PROFILES = (
    ("fast_2m_detector", 2),
    ("portfolio_2m_detector", 2),
    ("research_2m_detector", 2),
)


def test_required_profiles_are_explicit_versions_and_load_outside_checkout(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert available_system_profiles() == EXPECTED_PROFILES
    assert inspect.signature(load_system_profile).parameters["version"].default is inspect.Parameter.empty

    for name, version in EXPECTED_PROFILES:
        config = load_system_profile(name, version)
        assert isinstance(config, SystemConfig)
        assert config.profile.profile_id == f"{name}@{version}"
        assert isinstance(config.profile.provenance, Provenance)
        assert config.profile.provenance.source_id == (
            f"shwfs_ao.system_profile.{name}.v{version}"
        )
        assert len(config.config_hash) == 64
        assert all(len(value) == 64 for value in config.component_config_hashes.values())


def test_profile_loader_has_no_latest_alias() -> None:
    with pytest.raises(TypeError):
        load_system_profile("fast_2m_detector")  # type: ignore[call-arg]
    # A never-published version is unknown: there is no implicit "latest" and no
    # silent fall-through to an adjacent version in either direction.
    with pytest.raises(SystemConfigError, match="unknown system profile"):
        load_system_profile("high_order_10m_hcipy", 3)
    with pytest.raises(SystemConfigError, match="unknown system profile"):
        load_system_profile("fast_2m_geometric", 2)


def test_v1_profiles_stay_loadable_beside_their_v2_successors() -> None:
    """A published profile version stays reproducible after it is superseded.

    Each v1 profile keeps its own identity (``…@1``, its own config hash) while
    describing the same physics as its v2 successor: the v2 review made
    ``photon_allocation`` explicit at the value v1 already ran with, so every
    physical component hash is unchanged and only the profile provenance moves.
    """

    for name, _ in CURRENT_2M_PROFILES + (
        ("high_order_10m_geometric", 2),
        ("high_order_10m_hcipy", 2),
    ):
        v1 = load_system_profile(name, 1)
        v2 = load_system_profile(name, 2)

        assert v1.profile.profile_id == f"{name}@1"
        assert v1.profile.provenance.source_id == f"shwfs_ao.system_profile.{name}.v1"
        # v1 predates the explicit field and takes the allocation it was
        # reviewed and published under, not a silently different one.
        assert v1.wfs.photon_allocation == v2.wfs.photon_allocation == "throughput_scaled"

        physics = dict(v1.component_config_hashes)
        successor = dict(v2.component_config_hashes)
        assert physics.pop("profile") != successor.pop("profile")
        assert physics == successor
        # Distinct published identities never collide.
        assert v1.config_hash != v2.config_hash

        # A v1 profile re-serializes into the current record schema and parses
        # back equal, still identifying itself as version 1.
        record = system_config_to_mapping(v1)
        assert record["schema_version"] == PROFILE_SCHEMA_VERSION
        assert record["profile_version"] == 1
        assert system_config_from_mapping(record) == v1


def test_each_record_schema_version_has_an_exact_field_set() -> None:
    """Neither schema version may borrow the other's WFS field set."""

    v1_record = copy.deepcopy(system_config_to_mapping(load_system_profile("fast_2m_detector", 1)))
    v1_record["schema_version"] = 1
    # A v1 record carrying the v2 field is neither: it is rejected, not upgraded.
    with pytest.raises(SystemConfigError, match="unknown=\\['photon_allocation'\\]"):
        system_config_from_mapping(v1_record)

    del v1_record["config"]["wfs"]["photon_allocation"]
    parsed = system_config_from_mapping(v1_record)
    assert parsed.wfs.photon_allocation == "throughput_scaled"

    # An unsupported record schema version is refused with the supported set.
    v1_record["schema_version"] = 3
    with pytest.raises(SystemConfigError, match="unsupported profile schema_version"):
        system_config_from_mapping(v1_record)


def test_a_schema_v1_record_cannot_claim_a_later_profile_identity() -> None:
    """The two version axes are independent, but not every pairing is coherent.

    Schema v1 omits ``wfs.photon_allocation``, so a record claiming a profile
    version from the v2 review would present a *defaulted* allocation as the
    reviewed explicit one — the ambiguity schema v2 exists to remove, wearing
    the identity that says it was removed.
    """

    record = copy.deepcopy(
        system_config_to_mapping(load_system_profile("fast_2m_detector", 1))
    )
    record["schema_version"] = 1
    del record["config"]["wfs"]["photon_allocation"]
    assert system_config_from_mapping(record).profile.profile_id == "fast_2m_detector@1"

    record["profile_version"] = 2
    record["provenance"]["source_id"] = "shwfs_ao.system_profile.fast_2m_detector.v2"
    with pytest.raises(
        SystemConfigError, match="cannot be recorded under schema version 1"
    ):
        system_config_from_mapping(record)

    # The converse is legitimate and must stay accepted: it is exactly what the
    # serializer emits for a version-1 profile.
    v1 = load_system_profile("fast_2m_detector", 1)
    current = system_config_to_mapping(v1)
    assert (current["schema_version"], current["profile_version"]) == (
        PROFILE_SCHEMA_VERSION,
        1,
    )
    assert system_config_from_mapping(current) == v1


def test_every_packaged_profile_identity_is_pinned() -> None:
    """A profile's identity must not move without being noticed.

    ``config_hash`` is the hash of the canonical serialization, so it covers
    more than the physics: ``baseline_rationale`` and the provenance note are in
    it, and so is ``schema_version``.  An edit to a profile's *prose*, or a bump
    of the record schema, therefore relabels every result that cites the
    profile.  These hashes are the tripwire.

    They are the *current* identities, not the originally published ones. The
    ``@1`` identities have already moved twice without a version bump — once
    when AO-REF-019 rewrote a notebook path inside the provenance references,
    and once when the record schema went to v2 — so a result labelled ``@1`` by
    an older checkout will not reproduce the hash recorded here. That history is
    the reason this test exists; it cannot undo it. Changing a value below is
    only ever correct alongside a deliberate profile-version bump.
    """

    expected = {
        ("fast_2m_detector", 1): "52f295fe19e74c80ea01576979c9a03c3698ceb5cea4478e03b1a149d3ed482f",
        ("fast_2m_detector", 2): "7f225305b5d6e1e1b56ceff73cad945856c13a2b2c4f9d81b725a287d090626b",
        ("portfolio_2m_detector", 1): "0a104b02ba3d1368c8f5732d12c95f6e993a36e8675318e74edec90a545ce5f6",
        ("portfolio_2m_detector", 2): "ff9d43c343dccb9e22364fa04fc69bedeae96be0578cd5d0e3713dd25946b06e",
        ("research_2m_detector", 1): "192112852cf6874410f1c7e1a32c041cf5f519a3159a1f8bedf647e06a540ec7",
        ("research_2m_detector", 2): "38fc980bddaf60543eb46bb3ac48d9b6b0432e3e978922f8369ec7b607932dcc",
        ("high_order_10m_geometric", 1): "248b27246b1023235abf96a719dfa49e9d4c22562ce8bde17c5e8fc2db5f375b",
        ("high_order_10m_geometric", 2): "f8b6f9da7b42ab42b4ead3d1e17da385dece3b568c196d5251d261e6ae2a4ad2",
        ("high_order_10m_hcipy", 1): "2a51940f5945e882789e0613172e64470cb760ab39cb9816ce993c235b22f23f",
        ("high_order_10m_hcipy", 2): "50a1f9ea0a2abb4a07c7e9a151f76d366e64369f99df7f61c894217c2dd80d4a",
    }
    observed = {
        key: load_system_profile(*key).config_hash for key in available_system_profiles()
    }
    assert set(observed) == set(expected)
    assert observed == expected


def test_profile_round_trip_is_exact_and_deterministic() -> None:
    first = load_system_profile("fast_2m_detector", 2)
    second = load_system_profile("fast_2m_detector", 2)
    record = system_config_to_mapping(first)

    assert record["schema_name"] == PROFILE_SCHEMA_NAME
    assert record["schema_version"] == PROFILE_SCHEMA_VERSION
    assert system_config_from_mapping(record) == first == second
    assert first.config_hash == second.config_hash
    assert dict(first.component_config_hashes) == dict(second.component_config_hashes)

    with pytest.raises(FrozenInstanceError):
        first.pupil_pixels = 64  # type: ignore[misc]


def test_wfs_photon_allocation_is_required_serialized_and_hashed() -> None:
    profile = load_system_profile("fast_2m_detector", 2)
    # The reviewed v2 profiles record the allocation policy explicitly.
    assert profile.wfs.photon_allocation == "throughput_scaled"

    # The choice is a serialized, round-tripping part of the WFS block.
    record = system_config_to_mapping(profile)
    assert record["config"]["wfs"]["photon_allocation"] == "throughput_scaled"
    assert system_config_from_mapping(record) == profile

    # Schema v2 requires the field: a record that omits it is rejected rather
    # than silently defaulted, so a profile's identity is never ambiguous.
    missing = copy.deepcopy(record)
    del missing["config"]["wfs"]["photon_allocation"]
    with pytest.raises(SystemConfigError, match="wfs"):
        system_config_from_mapping(missing)

    # Switching the policy is a real configuration change: it round-trips and
    # moves the WFS component hash (which keys the seeded RNG scope).
    unit_sum = replace(
        profile, wfs=replace(profile.wfs, photon_allocation="unit_sum")
    )
    assert unit_sum.wfs.photon_allocation == "unit_sum"
    assert (
        unit_sum.component_config_hashes["wfs"]
        != profile.component_config_hashes["wfs"]
    )
    assert system_config_from_mapping(system_config_to_mapping(unit_sum)) == unit_sum

    # Unknown policies are rejected at construction.
    with pytest.raises(SystemConfigError, match="photon_allocation"):
        replace(profile.wfs, photon_allocation="per_lenslet")  # type: ignore[arg-type]


def test_2m_profiles_change_scale_without_changing_observing_conditions() -> None:
    profiles = [load_system_profile(name, version) for name, version in CURRENT_2M_PROFILES]
    assert [(p.pupil_pixels, p.lenslets_across, p.actuators_across) for p in profiles] == [
        (52, 5, 5),
        (72, 7, 7),
        (96, 9, 9),
    ]
    assert [p.wfs.detector_window_px for p in profiles] == [18, 20, 22]
    assert [p.controller.n_steps for p in profiles] == [12, 18, 30]
    assert len({p.observing_conditions_hash for p in profiles}) == 1
    assert all(p.detector.photons_per_subap_frame == 8000.0 for p in profiles)
    assert all(p.detector.read_noise_e == 1.0 for p in profiles)
    assert all(p.atmosphere.r0_m == profiles[0].atmosphere.r0_m for p in profiles)


def test_high_order_profile_matches_notebook_09_extreme_mode_in_si_units() -> None:
    config = load_system_profile("high_order_10m_geometric", 2)
    assert config.backend == "native"
    assert config.wfs_model == "geometric"
    assert config.telescope_diameter_m == 10.0
    assert (config.pupil_pixels, config.lenslets_across, config.actuators_across) == (
        384,
        48,
        49,
    )
    assert config.wfs_wavelength_m == 750.0e-9
    assert config.wfs.min_fill_fraction == 0.45
    assert config.wfs.pad_factor is None
    assert not config.detector.enabled
    assert config.dm.coupling_width_pitch == 0.70
    assert config.dm.actuator_margin_fraction == 0.12
    assert config.controller.n_steps == 160
    assert config.controller.frame_rate_hz == 500.0
    assert config.controller.gain == 0.65
    assert config.reconstructor.rcond == 0.02
    assert config.calibration.amplitude_m == pytest.approx(
        750.0e-9 / (2.0 * math.pi)
    )
    assert config.dm.stroke_limit_opd_m == pytest.approx(
        180.0 * 750.0e-9 / (2.0 * math.pi)
    )


def test_high_order_hcipy_profile_pairs_the_geometric_scale_through_hcipy() -> None:
    config = load_system_profile("high_order_10m_hcipy", 2)
    geometric = load_system_profile("high_order_10m_geometric", 2)

    assert config.backend == "hcipy"
    assert config.wfs_model == "detector_level"
    assert config.atmosphere_model == "hcipy"

    # Same observing target and numerical scale as the geometric profile.
    assert config.telescope_diameter_m == geometric.telescope_diameter_m
    assert (config.pupil_pixels, config.lenslets_across, config.actuators_across) == (
        geometric.pupil_pixels,
        geometric.lenslets_across,
        geometric.actuators_across,
    )
    assert config.wfs_wavelength_m == geometric.wfs_wavelength_m
    assert config.science_wavelengths_m == geometric.science_wavelengths_m
    assert config.atmosphere.r0_m == geometric.atmosphere.r0_m
    assert (
        config.atmosphere.r0_reference_wavelength_m
        == geometric.atmosphere.r0_reference_wavelength_m
    )
    assert config.atmosphere.outer_scale_m == geometric.atmosphere.outer_scale_m
    assert config.atmosphere.wind_m_per_s == geometric.atmosphere.wind_m_per_s
    assert config.dm == geometric.dm
    assert config.calibration == geometric.calibration
    assert config.controller == geometric.controller
    assert config.science == geometric.science
    assert config.random == geometric.random

    # The HCIPy atmosphere adapter has no RMS normalization, so this is the
    # one deliberate observing-condition difference from the geometric pair.
    assert config.atmosphere.normalize_rms is False
    assert config.atmosphere.target_rms_opd_m is None
    assert geometric.atmosphere.normalize_rms is True
    assert (
        config.observing_conditions_hash != geometric.observing_conditions_hash
    )

    # Detector-level sensing on the fixed HCIPy block window with the
    # established cross-backend spot sampling of 4 px per lambda/d.
    assert config.wfs.detector_window_px == (
        config.pupil_pixels // config.lenslets_across
    )
    assert config.wfs.detector_window_px == 8
    assert config.wfs.pad_factor == 4
    assert config.detector.enabled
    assert config.detector.photons_per_subap_frame == 8000.0
    assert config.detector.read_noise_e == 1.0
    assert config.detector.exposure_s == pytest.approx(
        1.0 / config.controller.frame_rate_hz
    )

    # The small block windows legitimately clip strongly displaced open-loop
    # spots, so the validity floor sits below the measured open-loop
    # fraction (0.82-0.84) instead of the geometric profile's 1.0.
    assert config.reconstructor.min_valid_fraction == 0.75
    assert config.wfs.max_window_clipping_fraction == 0.15


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda record: record.update(extra=True), "fields mismatch"),
        (lambda record: record.update(schema_version=99), "unsupported profile"),
        (
            lambda record: record["config"]["atmosphere"].update(extra=True),
            "fields mismatch",
        ),
        (
            lambda record: record["config"].update(science_wavelengths_m=[1.0e-6, 0.9e-6]),
            "strictly increasing",
        ),
        (
            lambda record: record["provenance"].update(schema_version=1),
            "provenance",
        ),
    ],
)
def test_mapping_parser_rejects_unknown_or_inconsistent_records(mutation, message) -> None:
    record = copy.deepcopy(
        system_config_to_mapping(load_system_profile("fast_2m_detector", 2))
    )
    mutation(record)
    with pytest.raises(SystemConfigError, match=message):
        system_config_from_mapping(record)


def test_profile_identity_and_numerical_content_both_affect_config_hash() -> None:
    original = load_system_profile("fast_2m_detector", 2)
    changed = replace(original, pupil_pixels=54)
    assert changed.config_hash != original.config_hash

    source = original.profile.provenance
    v3_source = replace(
        source,
        source_id="shwfs_ao.system_profile.fast_2m_detector.v3",
    )
    v3_profile = replace(
        original.profile,
        profile_version=3,
        provenance=v3_source,
        baseline_rationale="Reviewed numerical change for a hypothetical v3.",
    )
    versioned = replace(original, profile=v3_profile)
    assert versioned.config_hash != original.config_hash


def test_nested_public_configuration_types_and_source_policies() -> None:
    config = load_system_profile("fast_2m_detector", 2)
    assert isinstance(config.profile, ProfileProvenance)
    assert isinstance(config.atmosphere, AtmosphereConfig)
    assert isinstance(config.detector, DetectorSystemConfig)
    assert isinstance(config.wfs, WfsConfig)
    assert isinstance(config.dm, DmSystemConfig)
    assert isinstance(config.calibration, CalibrationConfig)
    assert isinstance(config.reconstructor, ReconstructorConfig)
    assert isinstance(config.command_projector, CommandProjectorConfig)
    assert isinstance(config.controller, ControllerConfig)
    assert isinstance(config.science, ScienceConfig)
    assert isinstance(config.random, RandomSeedConfig)

    with pytest.raises(SystemConfigError, match="resource calibration requires"):
        replace(config.calibration, source="resource")
    with pytest.raises(SystemConfigError, match="modal projector requires"):
        CommandProjectorConfig(kind="modal", mapping_resource=None)


def test_static_model_has_no_implicit_file_or_generated_profile_lookup() -> None:
    config = load_system_profile("fast_2m_detector", 2)
    static = replace(config, atmosphere_model="static")
    record = system_config_to_mapping(static)
    atmosphere = record["config"]["atmosphere"]
    assert set(atmosphere) == {
        "r0_m",
        "r0_reference_wavelength_m",
        "outer_scale_m",
        "wind_m_per_s",
        "target_rms_opd_m",
        "normalize_rms",
    }
    assert not any("path" in key or "resource" in key for key in atmosphere)
