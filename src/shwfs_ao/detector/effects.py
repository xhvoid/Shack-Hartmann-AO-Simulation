"""Canonical detector expectation and temporal-noise pipeline.

The canonical path keeps persistent detector response maps in a
``DetectorRealization`` and temporal shot/read noise in distinct named random
domains.  ``per_frame_legacy`` is an explicit compatibility mode whose single
NumPy generator preserves the historical PRNU → Poisson → read-noise sequence.
"""

from __future__ import annotations

import numpy as np

from ..core.protocols import RandomStreams
from ..core.types import DetectorFrame
from .config import DetectorConfig
from .random import DetectorRealization


class DetectorEffectsError(ValueError):
    """Raised when detector-effect inputs are inconsistent."""


def apply_detector_effects(
    normalized_intensity: np.ndarray,
    config: DetectorConfig,
    realization: DetectorRealization,
    *,
    random_streams: RandomStreams,
    include_noise: bool = True,
    clip_negative: bool = True,
    legacy_seed: int | None = None,
) -> DetectorFrame:
    """Apply detector response and noise in the normative physical order.

    ``include_noise=False`` disables Poisson and read-noise draws but retains
    the configured PRNU response, saturation, and bad-pixel behavior.  The
    historical configured-detector ``photons_per_subap_frame=None`` path is
    the one compatibility-mode exception: it skips photon conversion,
    background, PRNU, and Poisson sampling while retaining read noise and
    post-read effects. Explicit persistent mode still applies background and
    its fixed pixel response, but omits shot noise without a photon budget.
    Callers that need order-independent keyed frame replay pass a
    ``random_streams.scoped("frame", key=(...))`` view; recorded stream IDs are
    taken from that scoped provider.
    """

    intensity = _normalized_image(normalized_intensity)
    _validate_boolean(include_noise, label="include_noise")
    _validate_boolean(clip_negative, label="clip_negative")
    seed = _validate_legacy_seed(legacy_seed)
    _validate_realization(config, realization, random_streams, intensity.shape)

    unity_response = np.ones(intensity.shape, dtype=float)
    stream_ids: dict[str, str] = {}
    if realization.stream_id is not None:
        stream_ids["detector.realization"] = realization.stream_id

    photons = config.photons_per_subap_frame
    if photons is None:
        return _apply_configured_photonless_effects(
            intensity,
            config,
            realization,
            random_streams=random_streams,
            include_noise=include_noise,
            clip_negative=clip_negative,
            legacy_seed=seed,
            random_stream_ids=stream_ids,
        )

    expected_source_e = float(photons) * float(config.qe) * intensity
    background_per_pixel_e = (
        float(config.dark_e_per_s) * float(config.exposure_s)
        + float(config.background_e_per_pixel_frame)
    )
    expected_background_e = np.full(
        intensity.shape,
        background_per_pixel_e,
        dtype=float,
    )

    if config.prnu_mode == "persistent":
        if seed is not None:
            raise DetectorEffectsError(
                "legacy_seed is only valid with prnu_mode='per_frame_legacy'."
            )
        prnu_response = np.asarray(realization.prnu_response, dtype=float)
        expected_pre_poisson_e = (
            expected_source_e + expected_background_e
        ) * prnu_response
        if include_noise:
            shot_rng = random_streams.generator("detector.shot_noise")
            image_e = shot_rng.poisson(expected_pre_poisson_e).astype(float)
            stream_ids["detector.shot_noise"] = random_streams.stream_id(
                "detector.shot_noise"
            )
        else:
            image_e = expected_pre_poisson_e.copy()

        if include_noise and float(config.read_noise_e) > 0.0:
            read_rng = random_streams.generator("detector.read_noise")
            image_e = image_e + read_rng.normal(
                scale=float(config.read_noise_e),
                size=intensity.shape,
            )
            stream_ids["detector.read_noise"] = random_streams.stream_id(
                "detector.read_noise"
            )
    elif config.prnu_mode == "per_frame_legacy":
        needs_legacy_rng = bool(float(config.prnu_rms) > 0.0 or include_noise)
        legacy_rng: np.random.Generator | None = None
        legacy_stream_id: str | None = None
        if needs_legacy_rng:
            legacy_rng, legacy_stream_id = _legacy_generator(
                seed,
            )

        if float(config.prnu_rms) > 0.0:
            assert legacy_rng is not None and legacy_stream_id is not None
            prnu_response = np.maximum(
                legacy_rng.normal(
                    loc=1.0,
                    scale=float(config.prnu_rms),
                    size=intensity.shape,
                ),
                0.0,
            )
            stream_ids["detector.prnu"] = legacy_stream_id
        else:
            prnu_response = unity_response

        expected_pre_poisson_e = (
            expected_source_e + expected_background_e
        ) * prnu_response
        if include_noise:
            assert legacy_rng is not None and legacy_stream_id is not None
            image_e = legacy_rng.poisson(expected_pre_poisson_e).astype(float)
            stream_ids["detector.shot_noise"] = legacy_stream_id
            if float(config.read_noise_e) > 0.0:
                image_e = image_e + legacy_rng.normal(
                    scale=float(config.read_noise_e),
                    size=intensity.shape,
                )
                stream_ids["detector.read_noise"] = legacy_stream_id
        else:
            image_e = expected_pre_poisson_e.copy()
    else:  # Defensive guard if a noncanonical config object bypasses validation.
        raise DetectorEffectsError(
            "config.prnu_mode must be 'per_frame_legacy' or 'persistent'; "
            f"got {config.prnu_mode!r}."
        )

    return _finalize_detector_frame(
        image_e=image_e,
        expected_source_e=expected_source_e,
        expected_background_e=expected_background_e,
        expected_pre_poisson_e=expected_pre_poisson_e,
        prnu_response=prnu_response,
        config=config,
        realization=realization,
        clip_negative=clip_negative,
        random_stream_ids=stream_ids,
    )


def apply_legacy_detector_effects(
    normalized_intensity: np.ndarray,
    config: DetectorConfig,
    realization: DetectorRealization,
    *,
    random_streams: RandomStreams,
    clip_negative: bool = True,
    legacy_seed: int | None = None,
) -> DetectorFrame:
    """Preserve the installed low-level ``add_detector_noise`` semantics.

    That historical helper has one behavior distinct from the configured
    detector model: with ``photons_per_subap_frame=None`` it keeps the input
    intensity as source signal, adds the configured per-pixel background, and
    applies seeded read noise without a Poisson draw.  Keeping this branch in
    the canonical detector layer lets the installed adapter remain draw-free.
    Finite photon budgets use :func:`apply_detector_effects` unchanged.
    """

    if not isinstance(config, DetectorConfig):
        raise DetectorEffectsError("config must be a DetectorConfig.")
    if config.photons_per_subap_frame is not None:
        return apply_detector_effects(
            normalized_intensity,
            config,
            realization,
            random_streams=random_streams,
            clip_negative=clip_negative,
            legacy_seed=legacy_seed,
        )
    if config.prnu_mode != "per_frame_legacy":
        raise DetectorEffectsError(
            "apply_legacy_detector_effects requires "
            "prnu_mode='per_frame_legacy' when photons are None."
        )

    intensity = _normalized_image(normalized_intensity)
    _validate_boolean(clip_negative, label="clip_negative")
    seed = _validate_legacy_seed(legacy_seed)
    _validate_realization(config, realization, random_streams, intensity.shape)

    background_per_pixel_e = (
        float(config.dark_e_per_s) * float(config.exposure_s)
        + float(config.background_e_per_pixel_frame)
    )
    expected_background_e = np.full(
        intensity.shape,
        background_per_pixel_e,
        dtype=float,
    )
    expected_pre_poisson_e = intensity + expected_background_e
    image_e = expected_pre_poisson_e.copy()
    stream_ids: dict[str, str] = {}
    if realization.stream_id is not None:
        stream_ids["detector.realization"] = realization.stream_id
    if float(config.read_noise_e) > 0.0:
        legacy_rng, legacy_stream_id = _legacy_generator(seed)
        image_e = image_e + legacy_rng.normal(
            scale=float(config.read_noise_e),
            size=intensity.shape,
        )
        stream_ids["detector.read_noise"] = legacy_stream_id

    return _finalize_detector_frame(
        image_e=image_e,
        expected_source_e=intensity,
        expected_background_e=expected_background_e,
        expected_pre_poisson_e=expected_pre_poisson_e,
        prnu_response=np.ones(intensity.shape, dtype=float),
        config=config,
        realization=realization,
        clip_negative=clip_negative,
        random_stream_ids=stream_ids,
    )


def _apply_configured_photonless_effects(
    intensity: np.ndarray,
    config: DetectorConfig,
    realization: DetectorRealization,
    *,
    random_streams: RandomStreams,
    include_noise: bool,
    clip_negative: bool,
    legacy_seed: int | None,
    random_stream_ids: dict[str, str],
) -> DetectorFrame:
    """Apply the mode-specific configured-detector photonless branch."""

    if legacy_seed is not None and config.prnu_mode != "per_frame_legacy":
        raise DetectorEffectsError(
            "legacy_seed is only valid with prnu_mode='per_frame_legacy'."
        )

    if config.prnu_mode == "persistent":
        background_per_pixel_e = (
            float(config.dark_e_per_s) * float(config.exposure_s)
            + float(config.background_e_per_pixel_frame)
        )
        expected_background_e = np.full(
            intensity.shape,
            background_per_pixel_e,
            dtype=float,
        )
        prnu_response = np.asarray(realization.prnu_response, dtype=float)
        expected_pre_poisson_e = (
            intensity + expected_background_e
        ) * prnu_response
        image_e = expected_pre_poisson_e.copy()
        if include_noise and float(config.read_noise_e) > 0.0:
            read_rng = random_streams.generator("detector.read_noise")
            image_e = image_e + read_rng.normal(
                scale=float(config.read_noise_e),
                size=intensity.shape,
            )
            random_stream_ids["detector.read_noise"] = random_streams.stream_id(
                "detector.read_noise"
            )
        return _finalize_detector_frame(
            image_e=image_e,
            expected_source_e=intensity,
            expected_background_e=expected_background_e,
            expected_pre_poisson_e=expected_pre_poisson_e,
            prnu_response=prnu_response,
            config=config,
            realization=realization,
            clip_negative=clip_negative,
            random_stream_ids=random_stream_ids,
        )

    # The default compatibility mode preserves the configured-detector branch
    # exactly: no background, PRNU, or Poisson stage without a photon budget.
    image_e = intensity.copy()
    if include_noise and float(config.read_noise_e) > 0.0:
        read_rng, read_stream_id = _legacy_generator(legacy_seed)
        image_e = image_e + read_rng.normal(
            scale=float(config.read_noise_e),
            size=intensity.shape,
        )
        random_stream_ids["detector.read_noise"] = read_stream_id

    zero_background = np.zeros(intensity.shape, dtype=float)
    return _finalize_detector_frame(
        image_e=image_e,
        expected_source_e=intensity,
        expected_background_e=zero_background,
        expected_pre_poisson_e=intensity,
        prnu_response=np.ones(intensity.shape, dtype=float),
        config=config,
        realization=realization,
        clip_negative=clip_negative,
        random_stream_ids=random_stream_ids,
    )


def _finalize_detector_frame(
    *,
    image_e: np.ndarray,
    expected_source_e: np.ndarray,
    expected_background_e: np.ndarray,
    expected_pre_poisson_e: np.ndarray,
    prnu_response: np.ndarray,
    config: DetectorConfig,
    realization: DetectorRealization,
    clip_negative: bool,
    random_stream_ids: dict[str, str],
) -> DetectorFrame:
    saturated_mask = np.zeros(image_e.shape, dtype=bool)
    if config.full_well_e is not None:
        full_well_e = float(config.full_well_e)
        saturated_mask = image_e > full_well_e
        image_e = np.minimum(image_e, full_well_e)

    bad_pixel_mask = np.asarray(realization.bad_pixel_mask, dtype=bool)
    if np.any(bad_pixel_mask):
        image_e = image_e.copy()
        image_e[bad_pixel_mask] = 0.0

    if clip_negative:
        negative_clipped_mask = image_e < 0.0
        image_e = np.maximum(image_e, 0.0)
    else:
        negative_clipped_mask = np.zeros(image_e.shape, dtype=bool)

    if not np.all(np.isfinite(image_e)):
        raise DetectorEffectsError("detector image after effects must be finite.")

    return DetectorFrame(
        image_e=image_e,
        expected_source_e=expected_source_e,
        expected_background_e=expected_background_e,
        expected_pre_poisson_e=expected_pre_poisson_e,
        prnu_response=prnu_response,
        saturated_mask=saturated_mask,
        bad_pixel_mask=bad_pixel_mask,
        negative_clipped_mask=negative_clipped_mask,
        random_stream_ids=random_stream_ids,
    )


def _normalized_image(values: object) -> np.ndarray:
    image = np.asarray(values, dtype=float)
    if image.ndim != 2 or image.size == 0:
        raise DetectorEffectsError("normalized_intensity must be a non-empty 2-D array.")
    if not np.all(np.isfinite(image)):
        raise DetectorEffectsError("normalized_intensity must contain only finite values.")
    if np.any(image < 0.0):
        raise DetectorEffectsError("normalized_intensity must be non-negative.")
    return image.copy()


def _validate_realization(
    config: DetectorConfig,
    realization: DetectorRealization,
    random_streams: RandomStreams,
    shape: tuple[int, int],
) -> None:
    if not isinstance(config, DetectorConfig):
        raise DetectorEffectsError("config must be a DetectorConfig.")
    if not isinstance(realization, DetectorRealization):
        raise DetectorEffectsError("realization must be a DetectorRealization.")
    prnu_response = np.asarray(realization.prnu_response, dtype=float)
    bad_pixel_mask = np.asarray(realization.bad_pixel_mask, dtype=bool)
    if prnu_response.shape != shape:
        raise DetectorEffectsError(
            f"realization.prnu_response shape {prnu_response.shape} does not "
            f"match normalized_intensity shape {shape}."
        )
    if bad_pixel_mask.shape != shape:
        raise DetectorEffectsError(
            f"realization.bad_pixel_mask shape {bad_pixel_mask.shape} does not "
            f"match normalized_intensity shape {shape}."
        )
    if not np.all(np.isfinite(prnu_response)) or np.any(prnu_response < 0.0):
        raise DetectorEffectsError(
            "realization.prnu_response must be finite and non-negative."
        )
    if str(realization.config_hash) != str(config.realization_config_hash):
        raise DetectorEffectsError(
            "realization.config_hash does not match the detector's persistent "
            "realization configuration."
        )
    try:
        stream_root_seed = random_streams.root_seed
    except AttributeError as exc:
        raise DetectorEffectsError(
            "random_streams must implement the Section 4 RandomStreams contract."
        ) from exc
    if realization.root_seed != stream_root_seed:
        raise DetectorEffectsError(
            "realization.root_seed does not match random_streams.root_seed."
        )


def _legacy_generator(
    legacy_seed: int | None,
) -> tuple[np.random.Generator, str]:
    return (
        np.random.default_rng(legacy_seed),
        f"per_frame_legacy:numpy.default_rng(seed={legacy_seed})",
    )


def _validate_boolean(value: object, *, label: str) -> None:
    if not isinstance(value, (bool, np.bool_)):
        raise DetectorEffectsError(f"{label} must be a bool; got {value!r}.")


def _validate_legacy_seed(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise DetectorEffectsError(
            f"legacy_seed must be a non-negative integer or None; got {value!r}."
        )
    return value


__all__ = (
    "DetectorEffectsError",
    "apply_detector_effects",
    "apply_legacy_detector_effects",
)
