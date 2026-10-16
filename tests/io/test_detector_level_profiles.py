"""DET-01/DET-09: schema-v7 detector-level profiles.

Every malformed or unsupported record must be rejected while it is parsed,
before any optics, map, calibration product or loop is constructed.
"""

from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from shwfs_ao.io.camera_presets import CameraPresetError, available_camera_presets, load_camera_preset
from shwfs_ao.io.configs import (
    PROFILE_SCHEMA_VERSION,
    SystemConfigError,
    available_system_profiles,
    load_system_profile,
    system_config_from_mapping,
    system_config_to_mapping,
)


DETECTOR_LEVEL_PROFILES = (
    ("det_ccd_2m_synthetic", 1),
    ("det_emccd_2m_synthetic", 1),
    ("det_cmos_2m_synthetic", 1),
    ("det_emccd_2m_plane_synthetic", 1),
    ("det_emccd_12m_medium_derived", 1),
    ("det_ccd_42m_r3band_derived", 1),
    ("det_emccd_12m_medium_derived", 2),
    ("det_emccd_12m_medium_derived", 3),
)


def _record(name: str = "det_ccd_2m_synthetic") -> dict:
    return copy.deepcopy(system_config_to_mapping(load_system_profile(name, 1)))


def test_schema_seven_is_current_and_every_new_profile_round_trips() -> None:
    assert PROFILE_SCHEMA_VERSION == 7
    for key in DETECTOR_LEVEL_PROFILES:
        assert key in available_system_profiles()
        config = load_system_profile(*key)
        assert config.record_schema_version == 7
        assert config.detector_physics is not None
        assert config.controller.include_noise is True
        again = system_config_from_mapping(system_config_to_mapping(config))
        assert again == config and again.config_hash == config.config_hash
        assert "detector_physics" in config.component_config_hashes


def test_older_records_keep_their_identity_maps() -> None:
    for name, version in available_system_profiles():
        config = load_system_profile(name, version)
        if config.record_schema_version < 7:
            assert config.detector_physics is None
            assert "detector_physics" not in config.component_config_hashes


def test_packaged_camera_presets_are_versioned_and_synthetic() -> None:
    presets = available_camera_presets()
    assert {name for name, _ in presets} >= {"synthetic_ccd", "synthetic_emccd", "synthetic_cmos"}
    for key in presets:
        camera = load_camera_preset(*key)
        assert camera.source_class == "synthetic_assumed"
        assert camera.preset_name.startswith("synthetic_")
    with pytest.raises(CameraPresetError, match="unknown"):
        load_camera_preset("synthetic_ccd", 2)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda r: r["config"]["detector_physics"]["camera"].update(preset_name="no_such_camera"), "unknown camera preset"),
        (lambda r: r["config"]["detector_physics"]["camera"].update(extra=1), "fields mismatch"),
        (lambda r: r["config"]["detector_physics"]["camera"].pop("preset_version"), "fields mismatch"),
        (lambda r: r["config"]["detector_physics"]["processing"].update(mode="magic"), "mode must be one of"),
        (lambda r: r["config"]["detector_physics"]["source"].update(detected_e_per_full_subap_frame=10.0), "exactly one source quantity"),
        (lambda r: r["config"]["detector"].update(exposure_s=0.0015), "exceeds the frame period"),
        (lambda r: r["config"]["wfs"].update(detector_window_px=24), "odd"),
        (lambda r: r["config"]["detector"].update(photons_per_subap_frame=1000.0), "photons_per_subap_frame=null"),
        (lambda r: r["config"]["detector"].update(read_noise_e=2.0), "read_noise_e=0"),
        (lambda r: r["config"]["detector"].update(qe=0.8), "qe=1"),
        (lambda r: (r["config"].update(backend="hcipy"), r["config"]["wfs"].update(lenslet_axis="pixel_block_center")), "HCIPy fails closed"),
        (lambda r: r["config"]["detector_physics"]["bandpass"].update(kind="gauss_legendre", n_samples=3), "mft_pixel_integrated"),
    ],
)
def test_malformed_or_unsupported_records_are_rejected_while_parsing(mutation, message: str) -> None:
    record = _record()
    mutation(record)
    with pytest.raises((SystemConfigError, ValueError), match=message):
        system_config_from_mapping(record)


def test_mft_sampling_rejects_a_legacy_pad_factor() -> None:
    record = _record("det_emccd_2m_plane_synthetic")
    record["config"]["wfs"]["pad_factor"] = 3
    with pytest.raises(SystemConfigError, match="pad_factor must be null"):
        system_config_from_mapping(record)


def test_coupled_cameras_need_a_guard_ring() -> None:
    record = _record("det_emccd_2m_plane_synthetic")
    record["config"]["detector_physics"]["layout"]["guard_px"] = 0
    with pytest.raises(SystemConfigError, match="guard_px"):
        system_config_from_mapping(record)


def test_an_older_record_cannot_carry_the_physics_block() -> None:
    record = _record()
    record["schema_version"] = 6
    with pytest.raises(SystemConfigError, match="fields mismatch"):
        system_config_from_mapping(record)
    config = load_system_profile("det_ccd_2m_synthetic", 1)
    with pytest.raises(SystemConfigError, match="cannot express the detector_physics block"):
        replace(config, record_schema_version=6)


def test_observing_conditions_bind_the_physical_budget_only_for_v7() -> None:
    config = load_system_profile("det_ccd_2m_synthetic", 1)
    brighter = replace(
        config,
        detector_physics=replace(
            config.detector_physics,
            source=replace(config.detector_physics.source, ab_magnitude=4.0),
        ),
    )
    assert brighter.observing_conditions_hash != config.observing_conditions_hash
    assert brighter.config_hash != config.config_hash


def test_a_calibration_source_is_optional_positive_and_hash_neutral_when_absent() -> None:
    record = _record("det_emccd_12m_medium_derived")
    assert "calibration_source_detected_e_per_full_subap_frame" not in record["config"]["detector_physics"]
    version_2 = load_system_profile("det_emccd_12m_medium_derived", 2)
    physics = version_2.detector_physics
    assert physics.calibration_source_detected_e_per_full_subap_frame == 2500.0
    assert version_2.wfs.min_peak_snr == 0.0
    record["config"]["detector_physics"]["calibration_source_detected_e_per_full_subap_frame"] = -1.0
    with pytest.raises(SystemConfigError, match="positive"):
        system_config_from_mapping(record)


def test_version_3_is_version_2_with_damping_and_the_reset_policy() -> None:
    """@3 changes exactly the reconstructor damping and adds the reset policy."""

    version_2 = load_system_profile("det_emccd_12m_medium_derived", 2)
    version_3 = load_system_profile("det_emccd_12m_medium_derived", 3)
    assert version_2.reconstructor.alpha == 0.001
    assert version_3.reconstructor.alpha == 0.1
    assert version_2.controller.recovery is None
    recovery = version_3.controller.recovery
    assert recovery is not None
    assert (recovery.rejected_frames_before_decay, recovery.decay_per_rejected_frame) == (2, 1.0)
    assert recovery.fallback_min_valid_fraction is None
    assert recovery.fallback_min_actuator_coverage is None
    assert recovery.gain_full_valid_fraction is None
    restored = replace(
        version_3,
        reconstructor=replace(version_3.reconstructor, alpha=version_2.reconstructor.alpha),
        controller=replace(version_3.controller, recovery=None),
        profile=version_2.profile,
    )
    assert restored == version_2
    changed = {
        key
        for key, value in version_3.component_config_hashes.items()
        if version_2.component_config_hashes[key] != value
    }
    assert changed == {"profile", "reconstructor", "controller"}
