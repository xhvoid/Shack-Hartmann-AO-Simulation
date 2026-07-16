"""Contracts for canonical detector configuration and realized state."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
import inspect

import numpy as np
import pytest

from shwfs_ao.core.random import NamedRandomStreams
import shwfs_ao.detector.config as config_module
import shwfs_ao.detector.random as detector_random
from shwfs_ao.detector.config import (
    DETECTOR_PRESETS,
    DetectorConfig,
    DetectorConfigError,
    DetectorPreset,
    PrnuMode,
    SyntheticInstrumentError,
    detector_preset,
    make_bad_pixel_mask,
)
from shwfs_ao.detector.random import (
    DetectorRealization,
    DetectorRealizationError,
)


class _TrackingStreams:
    def __init__(self, root_seed: int) -> None:
        self.provider = NamedRandomStreams(root_seed)
        self.calls: list[tuple[str, str, tuple[str | int, ...]]] = []

    @property
    def root_seed(self) -> int:
        return self.provider.root_seed

    def keyed_generator(self, domain: str, *, key: tuple[str | int, ...]):
        self.calls.append(("keyed_generator", domain, key))
        return self.provider.keyed_generator(domain, key=key)

    def stream_id(self, domain: str, *, key: tuple[str | int, ...] = ()) -> str:
        self.calls.append(("stream_id", domain, key))
        return self.provider.stream_id(domain, key=key)


def _noisy_config(**overrides) -> DetectorConfig:
    values = {
        "photons_per_subap_frame": 1000.0,
        "read_noise_e": 1.5,
        "dark_e_per_s": 3.0,
        "background_e_per_pixel_frame": 0.25,
        "full_well_e": 50000.0,
        "qe": 0.9,
        "bad_pixel_mask": None,
        "prnu_rms": 0.05,
        "exposure_s": 1.0e-3,
        "source_class": "synthetic_assumed",
        "source_note": "Canonical detector contract fixture.",
        "prnu_mode": "per_frame_legacy",
        "bad_pixel_fraction": 0.0,
    }
    values.update(overrides)
    return DetectorConfig(**values)


def test_module_exports_configuration_and_realization_surfaces() -> None:
    assert config_module.__all__ == (
        "DEFAULT_SOURCE_CLASS",
        "PrnuMode",
        "SyntheticInstrumentError",
        "DetectorConfigError",
        "DetectorConfig",
        "DetectorPreset",
        "DETECTOR_PRESETS",
        "detector_preset",
        "make_bad_pixel_mask",
    )
    assert detector_random.__all__ == (
        "DetectorRealizationError",
        "DetectorRealization",
    )
    assert DetectorConfigError is SyntheticInstrumentError
    assert set(PrnuMode.__args__) == {"per_frame_legacy", "persistent"}


def test_detector_config_preserves_historical_field_order_then_trailing_policy() -> None:
    assert tuple(item.name for item in fields(DetectorConfig)) == (
        "photons_per_subap_frame",
        "read_noise_e",
        "dark_e_per_s",
        "background_e_per_pixel_frame",
        "full_well_e",
        "qe",
        "bad_pixel_mask",
        "prnu_rms",
        "exposure_s",
        "source_class",
        "source_note",
        "prnu_mode",
        "bad_pixel_fraction",
    )
    signature = inspect.signature(DetectorConfig)
    assert tuple(signature.parameters) == tuple(
        item.name for item in fields(DetectorConfig)
    )
    assert signature.parameters["prnu_mode"].default == "per_frame_legacy"
    assert signature.parameters["bad_pixel_fraction"].default == 0.0


def test_first_eleven_detector_config_arguments_remain_positional() -> None:
    config = DetectorConfig(
        200.0,
        2.0,
        3.0,
        4.0,
        5000.0,
        0.8,
        None,
        0.01,
        0.002,
        "synthetic_assumed",
        "Historical positional construction.",
    )

    assert config.photons_per_subap_frame == pytest.approx(200.0)
    assert config.read_noise_e == pytest.approx(2.0)
    assert config.prnu_mode == "per_frame_legacy"
    assert config.bad_pixel_fraction == pytest.approx(0.0)


def test_detector_config_defensively_copies_and_freezes_fixed_mask() -> None:
    mask = np.array([[False, True], [False, False]])
    config = _noisy_config(bad_pixel_mask=mask)
    mask[0, 0] = True

    assert config.bad_pixel_mask is not None
    assert config.bad_pixel_mask.tolist() == [[False, True], [False, False]]
    assert not config.bad_pixel_mask.flags.writeable
    with pytest.raises(ValueError):
        config.bad_pixel_mask[0, 0] = True
    with pytest.raises(ValueError):
        config.bad_pixel_mask.setflags(write=True)
    with pytest.raises(FrozenInstanceError):
        config.prnu_mode = "persistent"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("photons_per_subap_frame", -1.0),
        ("read_noise_e", -1.0),
        ("dark_e_per_s", np.nan),
        ("background_e_per_pixel_frame", np.inf),
        ("full_well_e", 0.0),
        ("qe", 0.0),
        ("prnu_rms", -0.1),
        ("exposure_s", 0.0),
        ("bad_pixel_fraction", -0.1),
        ("bad_pixel_fraction", 1.1),
    ],
)
def test_detector_config_rejects_invalid_physical_scalars(
    field_name: str,
    value: object,
) -> None:
    with pytest.raises(SyntheticInstrumentError, match=field_name):
        _noisy_config(**{field_name: value})


def test_detector_config_rejects_invalid_mode_mask_and_provenance() -> None:
    with pytest.raises(SyntheticInstrumentError, match="prnu_mode"):
        _noisy_config(prnu_mode="per_exposure")
    with pytest.raises(SyntheticInstrumentError, match="two-dimensional"):
        _noisy_config(bad_pixel_mask=np.array([True, False]))
    with pytest.raises(SyntheticInstrumentError, match="taxonomy"):
        _noisy_config(source_class="private_data")
    with pytest.raises(SyntheticInstrumentError, match="source_note"):
        _noisy_config(source_note=" ")


@pytest.mark.parametrize(
    "effect",
    [
        {"read_noise_e": 1.0},
        {"dark_e_per_s": 1.0},
        {"background_e_per_pixel_frame": 1.0},
        {"full_well_e": 100.0},
        {"prnu_rms": 0.01},
        {"bad_pixel_mask": np.array([[True]])},
        {"bad_pixel_fraction": 0.1},
    ],
)
def test_none_photon_budget_retains_historical_effect_configuration(effect) -> None:
    config = DetectorConfig(photons_per_subap_frame=None, **effect)
    field, expected = next(iter(effect.items()))
    actual = getattr(config, field)
    if isinstance(expected, np.ndarray):
        np.testing.assert_array_equal(actual, expected)
    else:
        assert actual == expected


def test_persistent_zero_effect_mode_is_explicit_but_still_ideal() -> None:
    config = DetectorConfig(
        photons_per_subap_frame=None,
        prnu_mode="persistent",
    )
    assert config.prnu_mode == "persistent"
    assert config.prnu_rms == 0.0


def test_detector_config_provenance_records_mode_without_changing_note() -> None:
    source_note = "A mode-explicit detector configuration."
    legacy = _noisy_config(source_note=source_note)
    persistent = replace(legacy, prnu_mode="persistent")

    assert legacy.provenance.source_note == persistent.provenance.source_note == source_note
    assert legacy.provenance.references == (
        "detector_prnu_mode=per_frame_legacy",
    )
    assert persistent.provenance.references == ("detector_prnu_mode=persistent",)


def test_detector_config_hash_is_stable_and_covers_mode_maps_and_fraction() -> None:
    base = _noisy_config()
    same = _noisy_config()
    persistent = replace(base, prnu_mode="persistent")
    fraction = replace(base, bad_pixel_fraction=0.1)
    fixed = replace(base, bad_pixel_mask=np.array([[False, True]]))

    assert base.config_hash == same.config_hash
    assert len(base.config_hash) == 64
    assert len({
        base.config_hash,
        persistent.config_hash,
        fraction.config_hash,
        fixed.config_hash,
    }) == 4


def test_realization_config_hash_excludes_temporal_and_provenance_settings() -> None:
    base = _noisy_config(prnu_mode="persistent")
    temporal_variants = (
        replace(base, photons_per_subap_frame=2500.0),
        replace(base, read_noise_e=8.0),
        replace(base, exposure_s=0.02),
        replace(base, full_well_e=9000.0),
        replace(base, qe=0.7),
        replace(base, source_note="Different provenance; same physical pixels."),
    )

    assert all(item.config_hash != base.config_hash for item in temporal_variants)
    assert all(
        item.realization_config_hash == base.realization_config_hash
        for item in temporal_variants
    )
    assert replace(base, prnu_rms=0.2).realization_config_hash != (
        base.realization_config_hash
    )
    assert replace(base, bad_pixel_fraction=0.1).realization_config_hash != (
        base.realization_config_hash
    )


def test_detector_preset_signature_and_registry_remain_compatible() -> None:
    signature = inspect.signature(DetectorPreset.to_detector_config)
    assert tuple(signature.parameters) == (
        "self",
        "photons_per_subap_frame",
        "window_px",
        "seed",
        "qe",
    )
    assert signature.parameters["window_px"].kind is inspect.Parameter.KEYWORD_ONLY
    assert str(signature.return_annotation) == "'DetectorConfig'"
    assert set(DETECTOR_PRESETS) == {
        "ideal",
        "low_noise_sCMOS_like",
        "noisy_visible_wfs",
        "stress_saturated_window",
    }
    assert all(
        detector_preset(name).preset_name == name
        for name in DETECTOR_PRESETS
    )


def test_detector_preset_unknown_name_uses_compatible_error() -> None:
    with pytest.raises(SyntheticInstrumentError, match="Unknown detector preset"):
        detector_preset("nir_science_camera")


def test_preset_to_config_keeps_seeded_fixed_mask_and_noise_values() -> None:
    preset = detector_preset("stress_saturated_window")
    config = preset.to_detector_config(
        1500.0,
        window_px=20,
        seed=17,
        qe=0.7,
    )
    expected_mask = np.random.default_rng(17).random((20, 20)) < 0.01

    assert config.read_noise_e == preset.read_noise_e
    assert config.dark_e_per_s == preset.dark_e_per_s
    assert config.background_e_per_pixel_frame == preset.background_e_per_pixel_frame
    assert config.full_well_e == preset.full_well_e
    assert config.prnu_rms == preset.prnu_rms
    assert config.exposure_s == preset.exposure_s
    assert config.qe == pytest.approx(0.7)
    assert np.array_equal(config.bad_pixel_mask, expected_mask)
    assert config.bad_pixel_fraction == 0.0
    assert config.prnu_mode == "per_frame_legacy"
    assert config.source_note.endswith("(preset=stress_saturated_window)")


def test_preset_without_both_legacy_mask_arguments_does_not_defer_silently() -> None:
    preset = detector_preset("stress_saturated_window")

    no_arguments = preset.to_detector_config(1000.0)
    only_window = preset.to_detector_config(1000.0, window_px=12)
    only_seed = preset.to_detector_config(1000.0, seed=3)

    for config in (no_arguments, only_window, only_seed):
        assert config.bad_pixel_mask is None
        assert config.bad_pixel_fraction == 0.0


def test_make_bad_pixel_mask_matches_frozen_default_rng_algorithm() -> None:
    expected = np.random.default_rng(3).random((40, 40)) < 0.05
    actual = make_bad_pixel_mask(40, 0.05, seed=3)

    assert actual.dtype == np.dtype(bool)
    assert np.array_equal(actual, expected)
    assert np.array_equal(actual, make_bad_pixel_mask(40, 0.05, seed=3))
    assert not np.any(make_bad_pixel_mask(4, 0.0, seed=1))
    assert np.all(make_bad_pixel_mask(4, 1.0, seed=1))


def test_make_bad_pixel_mask_rejects_invalid_window_or_fraction() -> None:
    with pytest.raises(SyntheticInstrumentError, match="window_px"):
        make_bad_pixel_mask(0, 0.1, seed=1)
    with pytest.raises(SyntheticInstrumentError, match="bad_pixel_fraction"):
        make_bad_pixel_mask(4, 1.1, seed=1)


def test_realization_factory_signature_is_explicit() -> None:
    signature = inspect.signature(DetectorRealization.create)
    assert tuple(signature.parameters) == (
        "config",
        "window_shape_px",
        "random_streams",
        "realization_index",
    )
    assert signature.parameters["random_streams"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["realization_index"].default == 0


def test_per_frame_legacy_realization_uses_unity_prnu_without_stream_draw() -> None:
    streams = _TrackingStreams(11)
    config = _noisy_config(prnu_mode="per_frame_legacy", prnu_rms=0.2)

    realization = DetectorRealization.create(
        config,
        (5, 6),
        random_streams=streams,
    )

    assert np.array_equal(realization.prnu_response, np.ones((5, 6)))
    assert not np.any(realization.bad_pixel_mask)
    assert realization.stream_id is None
    assert streams.calls == []


def test_fixed_bad_pixel_map_is_copied_without_consuming_stream() -> None:
    mask = np.array([[False, True], [True, False]])
    config = _noisy_config(bad_pixel_mask=mask)
    streams = _TrackingStreams(12)

    realization = DetectorRealization.create(
        config,
        (2, 2),
        random_streams=streams,
    )
    mask[:] = False

    assert realization.bad_pixel_mask.tolist() == [[False, True], [True, False]]
    assert streams.calls == []


def test_persistent_realization_is_replayable_and_nonnegative() -> None:
    config = _noisy_config(
        prnu_mode="persistent",
        prnu_rms=0.3,
        bad_pixel_fraction=0.15,
    )
    first = DetectorRealization.create(
        config,
        (8, 9),
        random_streams=NamedRandomStreams(123),
        realization_index=4,
    )
    second = DetectorRealization.create(
        config,
        (8, 9),
        random_streams=NamedRandomStreams(123),
        realization_index=4,
    )

    assert np.array_equal(first.prnu_response, second.prnu_response)
    assert np.array_equal(first.bad_pixel_mask, second.bad_pixel_mask)
    assert first.stream_id == second.stream_id
    assert first.realization_hash == second.realization_hash
    assert np.all(first.prnu_response >= 0.0)
    assert np.any(first.prnu_response != 1.0)


def test_different_seed_or_realization_index_changes_generated_state() -> None:
    config = _noisy_config(
        prnu_mode="persistent",
        prnu_rms=0.1,
        bad_pixel_fraction=0.2,
    )
    baseline = DetectorRealization.create(
        config,
        (10, 10),
        random_streams=NamedRandomStreams(1),
    )
    different_seed = DetectorRealization.create(
        config,
        (10, 10),
        random_streams=NamedRandomStreams(2),
    )
    different_index = DetectorRealization.create(
        config,
        (10, 10),
        random_streams=NamedRandomStreams(1),
        realization_index=1,
    )

    assert not np.array_equal(baseline.prnu_response, different_seed.prnu_response)
    assert not np.array_equal(baseline.prnu_response, different_index.prnu_response)
    assert len({
        baseline.realization_hash,
        different_seed.realization_hash,
        different_index.realization_hash,
    }) == 3


def test_shot_and_read_stream_draws_do_not_perturb_realization() -> None:
    config = _noisy_config(prnu_mode="persistent", bad_pixel_fraction=0.2)
    streams = NamedRandomStreams(91)
    baseline = DetectorRealization.create(config, (8, 8), random_streams=streams)

    streams.generator("detector.shot_noise").random(500)
    streams.generator("detector.read_noise").normal(size=500)
    replay = DetectorRealization.create(config, (8, 8), random_streams=streams)

    assert np.array_equal(baseline.prnu_response, replay.prnu_response)
    assert np.array_equal(baseline.bad_pixel_mask, replay.bad_pixel_mask)
    assert baseline.realization_hash == replay.realization_hash


def test_realization_consumes_only_detector_realization_domain() -> None:
    streams = _TrackingStreams(21)
    config = _noisy_config(prnu_mode="persistent", bad_pixel_fraction=0.1)

    DetectorRealization.create(config, (4, 4), random_streams=streams)

    assert [call[0] for call in streams.calls] == [
        "keyed_generator",
        "stream_id",
    ]
    assert {call[1] for call in streams.calls} == {"detector.realization"}
    assert streams.calls[0][2] == streams.calls[1][2]


def test_generated_bad_pixels_or_combine_with_explicit_fixed_mask() -> None:
    fixed = np.zeros((12, 12), dtype=bool)
    fixed[0, 0] = True
    config = _noisy_config(
        bad_pixel_mask=fixed,
        bad_pixel_fraction=0.25,
    )
    realization = DetectorRealization.create(
        config,
        (12, 12),
        random_streams=NamedRandomStreams(8),
    )

    assert realization.bad_pixel_mask[0, 0]
    assert np.count_nonzero(realization.bad_pixel_mask) > 1


def test_realization_arrays_are_defensive_read_only_and_hashes_are_recorded() -> None:
    config = _noisy_config(prnu_mode="persistent", prnu_rms=0.1)
    realization = DetectorRealization.create(
        config,
        (3, 4),
        random_streams=NamedRandomStreams(5),
    )

    assert realization.root_seed == 5
    assert realization.config_hash == config.realization_config_hash
    assert len(realization.realization_hash) == 64
    assert realization.window_shape_px == (3, 4)
    assert not realization.prnu_response.flags.writeable
    assert not realization.bad_pixel_mask.flags.writeable
    with pytest.raises(ValueError):
        realization.prnu_response[0, 0] = 1.0
    with pytest.raises(ValueError):
        realization.bad_pixel_mask[0, 0] = True
    with pytest.raises(ValueError):
        realization.prnu_response.setflags(write=True)
    with pytest.raises(ValueError):
        realization.bad_pixel_mask.setflags(write=True)


def test_realization_rejects_config_mask_shape_mismatch_before_use() -> None:
    config = _noisy_config(bad_pixel_mask=np.zeros((2, 2), dtype=bool))
    with pytest.raises(DetectorRealizationError, match="does not match"):
        DetectorRealization.create(
            config,
            (3, 3),
            random_streams=NamedRandomStreams(1),
        )


@pytest.mark.parametrize(
    "shape",
    [(0, 2), (2, -1), (2,), [2, 2]],
)
def test_realization_rejects_invalid_requested_shapes(shape: object) -> None:
    with pytest.raises(DetectorRealizationError, match="window_shape_px"):
        DetectorRealization.create(
            _noisy_config(),
            shape,  # type: ignore[arg-type]
            random_streams=NamedRandomStreams(1),
        )


def test_direct_realization_validation_copies_maps_and_rejects_invalid_state() -> None:
    template = DetectorRealization.create(
        _noisy_config(),
        (2, 2),
        random_streams=NamedRandomStreams(0),
    )
    prnu = template.prnu_response.copy()
    bad = template.bad_pixel_mask.copy()
    realization = DetectorRealization(
        prnu,
        bad,
        template.root_seed,
        template.stream_id,
        template.config_hash,
        template.realization_hash,
    )
    prnu[0, 0] = 2.0
    bad[0, 0] = True

    assert realization.prnu_response[0, 0] == 1.0
    assert not realization.bad_pixel_mask[0, 0]
    with pytest.raises(DetectorRealizationError, match="non-negative"):
        DetectorRealization(
            np.array([[-1.0]]),
            np.zeros((1, 1), dtype=bool),
            0,
            None,
            "config",
            "realization",
        )
    with pytest.raises(DetectorRealizationError, match="boolean"):
        DetectorRealization(
            np.ones((1, 1)),
            np.zeros((1, 1), dtype=int),
            0,
            None,
            "config",
            "realization",
        )
    with pytest.raises(DetectorRealizationError, match="same shape"):
        DetectorRealization(
            np.ones((1, 2)),
            np.zeros((1, 1), dtype=bool),
            0,
            None,
            "config",
            "realization",
        )


def test_direct_realization_rejects_a_tampered_public_hash() -> None:
    realization = DetectorRealization.create(
        _noisy_config(prnu_mode="persistent"),
        (2, 2),
        random_streams=NamedRandomStreams(7),
    )

    with pytest.raises(DetectorRealizationError, match="realization_hash"):
        replace(realization, realization_hash="0" * 64)


def test_temporal_config_changes_reuse_the_same_persistent_realization() -> None:
    base = _noisy_config(prnu_mode="persistent", bad_pixel_fraction=0.2)
    changed = replace(
        base,
        photons_per_subap_frame=2000.0,
        read_noise_e=9.0,
        source_note="Runtime settings changed without replacing the detector.",
    )
    streams = NamedRandomStreams(55)
    realization = DetectorRealization.create(
        base,
        (8, 8),
        random_streams=streams,
    )
    replay = DetectorRealization.create(
        changed,
        (8, 8),
        random_streams=NamedRandomStreams(55),
    )

    assert np.array_equal(realization.prnu_response, replay.prnu_response)
    assert np.array_equal(realization.bad_pixel_mask, replay.bad_pixel_mask)
    assert realization.realization_hash == replay.realization_hash
