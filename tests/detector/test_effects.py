"""AO-REF-004 detector expectation, response, and temporal-noise tests."""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from shwfs_ao.core.random import NamedRandomStreams
from shwfs_ao.detector.config import DetectorConfig
from shwfs_ao.detector.effects import (
    DetectorEffectsError,
    apply_detector_effects,
    apply_legacy_detector_effects,
)
from shwfs_ao.detector.random import DetectorRealization


ROOT = Path(__file__).resolve().parents[2]


class _TrackingStreams:
    def __init__(self, root_seed: int) -> None:
        self.provider = NamedRandomStreams(root_seed)
        self.calls: list[tuple[str, str]] = []

    @property
    def root_seed(self) -> int:
        return self.provider.root_seed

    def generator(self, domain: str):
        self.calls.append(("generator", domain))
        return self.provider.generator(domain)

    def keyed_generator(self, domain: str, *, key):
        self.calls.append(("keyed_generator", domain))
        return self.provider.keyed_generator(domain, key=key)

    def stream_id(self, domain: str, *, key=()):
        self.calls.append(("stream_id", domain))
        return self.provider.stream_id(domain, key=key)


def _detector_state(
    config: DetectorConfig,
    shape: tuple[int, int],
    *,
    root_seed: int = 2026,
):
    streams = NamedRandomStreams(root_seed)
    realization = DetectorRealization.create(
        config,
        shape,
        random_streams=streams,
    )
    return streams, realization


def test_per_frame_legacy_exact_frozen_prnu_poisson_read_fixture():
    intensity = np.array([[0.1, 0.2], [0.3, 0.4]])
    bad_pixels = np.array([[False, True], [False, False]])
    config = DetectorConfig(
        photons_per_subap_frame=100.0,
        read_noise_e=1.25,
        dark_e_per_s=2.0,
        background_e_per_pixel_frame=0.75,
        full_well_e=25.0,
        qe=0.8,
        bad_pixel_mask=bad_pixels,
        prnu_rms=0.1,
        exposure_s=0.5,
        prnu_mode="per_frame_legacy",
    )
    streams, realization = _detector_state(config, intensity.shape)

    frame = apply_detector_effects(
        intensity,
        config,
        realization,
        random_streams=streams,
        legacy_seed=123,
    )

    np.testing.assert_array_equal(
        frame.expected_source_e,
        [[8.0, 16.0], [24.0, 32.0]],
    )
    np.testing.assert_array_equal(
        frame.expected_background_e,
        [[1.75, 1.75], [1.75, 1.75]],
    )
    np.testing.assert_array_equal(
        frame.prnu_response,
        [
            [0.9010878649652149, 0.9632213348532117],
            [1.128792526128925, 1.0193974419132614],
        ],
    )
    np.testing.assert_array_equal(
        frame.expected_pre_poisson_e,
        [
            [8.785606683410846, 17.09717869364451],
            [29.066407547819814, 34.404663664572574],
        ],
    )
    np.testing.assert_array_equal(
        frame.image_e,
        [[13.943462055390313, 0.0], [25.0, 25.0]],
    )
    np.testing.assert_array_equal(
        frame.saturated_mask,
        [[False, False], [True, True]],
    )
    np.testing.assert_array_equal(frame.bad_pixel_mask, bad_pixels)
    assert not np.any(frame.negative_clipped_mask)
    assert set(frame.random_stream_ids) == {
        "detector.prnu",
        "detector.shot_noise",
        "detector.read_noise",
    }
    assert all(
        "per_frame_legacy:numpy.default_rng(seed=123)" == stream_id
        for stream_id in frame.random_stream_ids.values()
    )


def test_persistent_temporal_streams_reset_to_exact_first_and_second_frames():
    intensity = np.full((4, 4), 1.0 / 16.0)
    config = DetectorConfig(
        photons_per_subap_frame=2000.0,
        read_noise_e=2.5,
        prnu_rms=0.08,
        prnu_mode="persistent",
    )
    streams, realization = _detector_state(config, intensity.shape, root_seed=88)

    first = apply_detector_effects(
        intensity, config, realization, random_streams=streams
    )
    second = apply_detector_effects(
        intensity, config, realization, random_streams=streams
    )
    assert not np.array_equal(first.image_e, second.image_e)
    assert first.random_stream_ids["detector.shot_noise"] != first.random_stream_ids[
        "detector.read_noise"
    ]

    streams.reset()
    replay_first = apply_detector_effects(
        intensity, config, realization, random_streams=streams
    )
    replay_second = apply_detector_effects(
        intensity, config, realization, random_streams=streams
    )
    np.testing.assert_array_equal(replay_first.image_e, first.image_e)
    np.testing.assert_array_equal(replay_second.image_e, second.image_e)


def test_persistent_effects_consume_only_named_shot_and_read_domains() -> None:
    config = DetectorConfig(
        photons_per_subap_frame=100.0,
        read_noise_e=2.0,
        prnu_mode="persistent",
    )
    tracking = _TrackingStreams(19)
    realization = DetectorRealization.create(
        config,
        (2, 2),
        random_streams=tracking,
    )
    tracking.calls.clear()

    frame = apply_detector_effects(
        np.full((2, 2), 0.25),
        config,
        realization,
        random_streams=tracking,
    )

    assert tracking.calls == [
        ("generator", "detector.shot_noise"),
        ("stream_id", "detector.shot_noise"),
        ("generator", "detector.read_noise"),
        ("stream_id", "detector.read_noise"),
    ]
    assert set(frame.random_stream_ids) == {
        "detector.shot_noise",
        "detector.read_noise",
    }


def test_legacy_without_explicit_seed_uses_only_labeled_local_rng() -> None:
    config = DetectorConfig(
        photons_per_subap_frame=100.0,
        read_noise_e=1.0,
        prnu_rms=0.1,
        prnu_mode="per_frame_legacy",
    )
    tracking = _TrackingStreams(91)
    realization = DetectorRealization.create(
        config,
        (2, 2),
        random_streams=tracking,
    )
    tracking.calls.clear()

    frame = apply_detector_effects(
        np.full((2, 2), 0.25),
        config,
        realization,
        random_streams=tracking,
    )

    assert tracking.calls == []
    assert set(frame.random_stream_ids) == {
        "detector.prnu",
        "detector.shot_noise",
        "detector.read_noise",
    }
    assert set(frame.random_stream_ids.values()) == {
        "per_frame_legacy:numpy.default_rng(seed=None)"
    }


def test_persistent_prnu_is_fixed_and_independent_of_temporal_noise_draws():
    shape = (12, 10)
    config = DetectorConfig(
        photons_per_subap_frame=500.0,
        read_noise_e=1.0,
        prnu_rms=0.15,
        prnu_mode="persistent",
    )
    advanced_streams = NamedRandomStreams(712)
    advanced_streams.generator("detector.shot_noise").random(20_000)
    advanced_streams.generator("detector.read_noise").random(20_000)
    advanced_realization = DetectorRealization.create(
        config,
        shape,
        random_streams=advanced_streams,
    )
    clean_streams = NamedRandomStreams(712)
    clean_realization = DetectorRealization.create(
        config,
        shape,
        random_streams=clean_streams,
    )

    np.testing.assert_array_equal(
        advanced_realization.prnu_response,
        clean_realization.prnu_response,
    )
    np.testing.assert_array_equal(
        advanced_realization.bad_pixel_mask,
        clean_realization.bad_pixel_mask,
    )

    intensity = np.full(shape, 1.0 / np.prod(shape))
    frame_a = apply_detector_effects(
        intensity,
        config,
        clean_realization,
        random_streams=clean_streams,
    )
    frame_b = apply_detector_effects(
        intensity,
        config,
        clean_realization,
        random_streams=clean_streams,
    )
    np.testing.assert_array_equal(frame_a.prnu_response, frame_b.prnu_response)
    np.testing.assert_array_equal(frame_a.prnu_response, clean_realization.prnu_response)
    assert not np.array_equal(frame_a.image_e, frame_b.image_e)


def test_existing_realization_accepts_changed_temporal_frame_configuration() -> None:
    intensity = np.full((2, 2), 0.25)
    base = DetectorConfig(
        photons_per_subap_frame=100.0,
        read_noise_e=1.0,
        prnu_rms=0.1,
        prnu_mode="persistent",
    )
    changed = replace(
        base,
        photons_per_subap_frame=400.0,
        read_noise_e=8.0,
        source_note="Same realized detector with a changed runtime frame.",
    )
    streams, realization = _detector_state(base, intensity.shape, root_seed=31)

    frame = apply_detector_effects(
        intensity,
        changed,
        realization,
        random_streams=streams,
        include_noise=False,
    )

    np.testing.assert_array_equal(
        frame.expected_source_e,
        np.full((2, 2), 100.0),
    )
    np.testing.assert_array_equal(frame.prnu_response, realization.prnu_response)


def test_photon_and_read_noise_variance_follow_expected_trends():
    intensity = np.ones((1, 1))

    def photon_samples(photons: float) -> np.ndarray:
        config = DetectorConfig(
            photons_per_subap_frame=photons,
            read_noise_e=0.0,
            prnu_mode="persistent",
        )
        streams, realization = _detector_state(config, intensity.shape, root_seed=33)
        return np.array(
            [
                apply_detector_effects(
                    intensity,
                    config,
                    realization,
                    random_streams=streams,
                    clip_negative=False,
                ).image_e[0, 0]
                for _ in range(800)
            ]
        )

    low_photon = photon_samples(30.0)
    high_photon = photon_samples(3000.0)
    assert np.var(low_photon, ddof=1) == pytest.approx(np.mean(low_photon), rel=0.2)
    assert np.var(high_photon, ddof=1) == pytest.approx(
        np.mean(high_photon), rel=0.2
    )
    assert np.var(high_photon / np.mean(high_photon)) < 0.02 * np.var(
        low_photon / np.mean(low_photon)
    )

    def read_samples(read_noise_e: float) -> np.ndarray:
        config = DetectorConfig(
            photons_per_subap_frame=0.0,
            read_noise_e=read_noise_e,
            prnu_mode="persistent",
        )
        streams, realization = _detector_state(config, intensity.shape, root_seed=44)
        return np.array(
            [
                apply_detector_effects(
                    intensity,
                    config,
                    realization,
                    random_streams=streams,
                    clip_negative=False,
                ).image_e[0, 0]
                for _ in range(800)
            ]
        )

    low_read = read_samples(1.0)
    high_read = read_samples(8.0)
    assert np.var(high_read, ddof=1) > 40.0 * np.var(low_read, ddof=1)


def test_saturation_bad_pixels_and_negative_clipping_masks_are_exact():
    intensity = np.array([[0.1, 0.2], [0.3, 0.4]])
    bad_pixels = np.array([[False, True], [False, False]])
    saturation_config = DetectorConfig(
        photons_per_subap_frame=1000.0,
        read_noise_e=0.0,
        full_well_e=250.0,
        bad_pixel_mask=bad_pixels,
        prnu_mode="persistent",
    )
    streams, realization = _detector_state(saturation_config, intensity.shape)
    saturated = apply_detector_effects(
        intensity,
        saturation_config,
        realization,
        random_streams=streams,
        include_noise=False,
    )

    np.testing.assert_array_equal(
        saturated.saturated_mask,
        [[False, False], [True, True]],
    )
    np.testing.assert_array_equal(saturated.bad_pixel_mask, bad_pixels)
    np.testing.assert_array_equal(
        saturated.image_e,
        [[100.0, 0.0], [250.0, 250.0]],
    )

    negative_config = DetectorConfig(
        photons_per_subap_frame=0.0,
        read_noise_e=5.0,
        prnu_mode="per_frame_legacy",
    )
    negative_streams, negative_realization = _detector_state(
        negative_config, (2, 3)
    )
    unclipped = apply_detector_effects(
        np.zeros((2, 3)),
        negative_config,
        negative_realization,
        random_streams=negative_streams,
        clip_negative=False,
        legacy_seed=1,
    )
    clipped = apply_detector_effects(
        np.zeros((2, 3)),
        negative_config,
        negative_realization,
        random_streams=negative_streams,
        clip_negative=True,
        legacy_seed=1,
    )
    expected_clipped = unclipped.image_e < 0.0
    assert np.any(expected_clipped)
    assert not np.any(unclipped.negative_clipped_mask)
    np.testing.assert_array_equal(clipped.negative_clipped_mask, expected_clipped)
    assert np.all(clipped.image_e[expected_clipped] == 0.0)
    np.testing.assert_array_equal(
        clipped.image_e[~expected_clipped],
        unclipped.image_e[~expected_clipped],
    )


def test_no_temporal_draw_paths_record_only_streams_that_were_used() -> None:
    intensity = np.full((2, 2), 0.25)
    persistent = DetectorConfig(
        photons_per_subap_frame=100.0,
        read_noise_e=0.0,
        prnu_rms=0.1,
        prnu_mode="persistent",
    )
    streams, realization = _detector_state(persistent, intensity.shape)

    expectation = apply_detector_effects(
        intensity,
        persistent,
        realization,
        random_streams=streams,
        include_noise=False,
    )
    assert expectation.random_stream_ids == {
        "detector.realization": realization.stream_id
    }

    noisy = apply_detector_effects(
        intensity,
        persistent,
        realization,
        random_streams=streams,
    )
    assert set(noisy.random_stream_ids) == {
        "detector.realization",
        "detector.shot_noise",
    }


def test_ideal_none_photon_path_returns_normalized_immutable_frame():
    intensity = np.array([[0.2, 0.3], [0.1, 0.4]])
    config = DetectorConfig(photons_per_subap_frame=None)
    streams, realization = _detector_state(config, intensity.shape)

    frame = apply_detector_effects(
        intensity,
        config,
        realization,
        random_streams=streams,
    )

    np.testing.assert_array_equal(frame.image_e, intensity)
    np.testing.assert_array_equal(frame.expected_source_e, intensity)
    np.testing.assert_array_equal(frame.expected_pre_poisson_e, intensity)
    assert not np.any(frame.expected_background_e)
    assert np.all(frame.prnu_response == 1.0)
    assert frame.random_stream_ids == {}
    for values in (
        frame.image_e,
        frame.expected_source_e,
        frame.expected_background_e,
        frame.expected_pre_poisson_e,
        frame.prnu_response,
        frame.saturated_mask,
        frame.bad_pixel_mask,
        frame.negative_clipped_mask,
    ):
        assert values.flags.writeable is False
    with pytest.raises(TypeError):
        frame.random_stream_ids["new"] = "not-allowed"


def test_configured_none_photon_path_preserves_read_and_post_read_effects():
    intensity = np.array([[0.2, 0.3], [0.1, 0.4]])
    bad_pixels = np.array([[False, True], [False, False]])
    config = DetectorConfig(
        photons_per_subap_frame=None,
        read_noise_e=0.25,
        dark_e_per_s=5.0,
        background_e_per_pixel_frame=2.0,
        full_well_e=0.35,
        bad_pixel_mask=bad_pixels,
        prnu_rms=0.5,
    )
    streams, realization = _detector_state(config, intensity.shape)

    frame = apply_detector_effects(
        intensity,
        config,
        realization,
        random_streams=streams,
        clip_negative=False,
        legacy_seed=17,
    )

    manual = intensity + np.random.default_rng(17).normal(
        scale=0.25,
        size=intensity.shape,
    )
    manual = np.minimum(manual, 0.35)
    manual[bad_pixels] = 0.0
    np.testing.assert_array_equal(frame.image_e, manual)
    np.testing.assert_array_equal(frame.expected_source_e, intensity)
    assert not np.any(frame.expected_background_e)
    np.testing.assert_array_equal(frame.expected_pre_poisson_e, intensity)
    assert np.all(frame.prnu_response == 1.0)
    assert set(frame.random_stream_ids) == {"detector.read_noise"}


def test_persistent_none_photon_path_applies_fixed_response_without_shot_noise():
    intensity = np.array([[0.2, 0.3], [0.1, 0.4]])
    config = DetectorConfig(
        photons_per_subap_frame=None,
        dark_e_per_s=2.0,
        exposure_s=0.5,
        background_e_per_pixel_frame=1.0,
        prnu_rms=0.2,
        prnu_mode="persistent",
    )
    streams, realization = _detector_state(config, intensity.shape, root_seed=73)

    frame = apply_detector_effects(
        intensity,
        config,
        realization,
        random_streams=streams,
        include_noise=False,
    )

    expected_background = np.full(intensity.shape, 2.0)
    expected_pre_poisson = (
        intensity + expected_background
    ) * realization.prnu_response
    np.testing.assert_array_equal(frame.image_e, expected_pre_poisson)
    np.testing.assert_array_equal(
        frame.expected_background_e,
        expected_background,
    )
    np.testing.assert_array_equal(
        frame.expected_pre_poisson_e,
        expected_pre_poisson,
    )
    np.testing.assert_array_equal(
        frame.prnu_response,
        realization.prnu_response,
    )
    assert set(frame.random_stream_ids) == {"detector.realization"}


def test_legacy_none_photon_compatibility_adds_background_without_poisson():
    intensity = np.array([[0.2, 0.3], [0.1, 0.4]])
    config = DetectorConfig(
        photons_per_subap_frame=None,
        read_noise_e=0.25,
        background_e_per_pixel_frame=2.0,
    )
    streams, realization = _detector_state(config, intensity.shape)

    frame = apply_legacy_detector_effects(
        intensity,
        config,
        realization,
        random_streams=streams,
        legacy_seed=17,
    )

    manual = intensity + 2.0 + np.random.default_rng(17).normal(
        scale=0.25,
        size=intensity.shape,
    )
    np.testing.assert_array_equal(frame.image_e, manual)
    np.testing.assert_array_equal(frame.expected_source_e, intensity)
    np.testing.assert_array_equal(frame.expected_background_e, 2.0)
    np.testing.assert_array_equal(
        frame.expected_pre_poisson_e,
        intensity + 2.0,
    )
    assert set(frame.random_stream_ids) == {"detector.read_noise"}


def test_effects_reject_bad_input_shape_realization_and_root_seed():
    config = DetectorConfig(
        photons_per_subap_frame=100.0,
        prnu_mode="persistent",
    )
    streams, realization = _detector_state(config, (2, 2), root_seed=1)

    with pytest.raises(DetectorEffectsError, match="non-empty 2-D"):
        apply_detector_effects(
            np.ones(3), config, realization, random_streams=streams
        )
    with pytest.raises(DetectorEffectsError, match="non-negative"):
        apply_detector_effects(
            np.array([[1.0, -1.0], [0.0, 1.0]]),
            config,
            realization,
            random_streams=streams,
        )
    with pytest.raises(DetectorEffectsError, match="prnu_response shape"):
        apply_detector_effects(
            np.ones((3, 3)), config, realization, random_streams=streams
        )
    with pytest.raises(DetectorEffectsError, match="root_seed"):
        apply_detector_effects(
            np.full((2, 2), 0.25),
            config,
            realization,
            random_streams=NamedRandomStreams(2),
        )


def test_effects_module_has_no_control_wfs_or_legacy_imports():
    path = ROOT / "src" / "shwfs_ao" / "detector" / "effects.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    forbidden = {"control", "wfs", "legacy"}
    imported_parts: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_parts.update(
                part for alias in node.names for part in alias.name.split(".")
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_parts.update(node.module.split("."))
    assert imported_parts.isdisjoint(forbidden)
