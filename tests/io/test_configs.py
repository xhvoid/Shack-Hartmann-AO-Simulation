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


EXPECTED_PROFILES = (
    ("fast_2m_detector", 1),
    ("portfolio_2m_detector", 1),
    ("research_2m_detector", 1),
    ("high_order_10m_geometric", 1),
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
    with pytest.raises(SystemConfigError, match="unknown system profile"):
        load_system_profile("fast_2m_detector", 2)
    with pytest.raises(SystemConfigError, match="unknown system profile"):
        load_system_profile("high_order_10m_hcipy", 1)


def test_profile_round_trip_is_exact_and_deterministic() -> None:
    first = load_system_profile("fast_2m_detector", 1)
    second = load_system_profile("fast_2m_detector", 1)
    record = system_config_to_mapping(first)

    assert record["schema_name"] == PROFILE_SCHEMA_NAME
    assert record["schema_version"] == PROFILE_SCHEMA_VERSION
    assert system_config_from_mapping(record) == first == second
    assert first.config_hash == second.config_hash
    assert dict(first.component_config_hashes) == dict(second.component_config_hashes)

    with pytest.raises(FrozenInstanceError):
        first.pupil_pixels = 64  # type: ignore[misc]


def test_2m_profiles_change_scale_without_changing_observing_conditions() -> None:
    profiles = [load_system_profile(name, 1) for name, _ in EXPECTED_PROFILES[:3]]
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
    config = load_system_profile("high_order_10m_geometric", 1)
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
        system_config_to_mapping(load_system_profile("fast_2m_detector", 1))
    )
    mutation(record)
    with pytest.raises(SystemConfigError, match=message):
        system_config_from_mapping(record)


def test_profile_identity_and_numerical_content_both_affect_config_hash() -> None:
    original = load_system_profile("fast_2m_detector", 1)
    changed = replace(original, pupil_pixels=54)
    assert changed.config_hash != original.config_hash

    source = original.profile.provenance
    v2_source = replace(
        source,
        source_id="shwfs_ao.system_profile.fast_2m_detector.v2",
    )
    v2_profile = replace(
        original.profile,
        profile_version=2,
        provenance=v2_source,
        baseline_rationale="Reviewed numerical change for a hypothetical v2.",
    )
    versioned = replace(original, profile=v2_profile)
    assert versioned.config_hash != original.config_hash


def test_nested_public_configuration_types_and_source_policies() -> None:
    config = load_system_profile("fast_2m_detector", 1)
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
    config = load_system_profile("fast_2m_detector", 1)
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
