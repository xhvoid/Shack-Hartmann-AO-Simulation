"""Persistent detector maps derived from the shared named-stream provider."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.hashing import stable_hash
from ..core.protocols import RandomStreams
from .config import DetectorConfig


_REALIZATION_DOMAIN = "detector.realization"


class DetectorRealizationError(ValueError):
    """Raised when detector realization inputs or stored maps are invalid."""


@dataclass(frozen=True)
class DetectorRealization:
    """Immutable persistent PRNU and bad-pixel state for one detector.

    ``stream_id`` is ``None`` when construction requires no random draw.  In
    particular, a ``per_frame_legacy`` config with only an explicit fixed mask
    does not touch ``detector.realization``.  Persistent-mode shot and read
    noise remain responsibilities of their separately named domains; the
    explicit compatibility mode retains its historical single local generator.
    """

    __hash_schema_id__ = "shwfs_ao.detector.DetectorRealization.v1"

    prnu_response: np.ndarray
    bad_pixel_mask: np.ndarray
    root_seed: int
    stream_id: str | None
    config_hash: str
    realization_hash: str

    def __post_init__(self) -> None:
        prnu_response = _immutable_prnu(self.prnu_response)
        bad_pixel_mask = _immutable_bad_pixels(self.bad_pixel_mask)
        if prnu_response.shape != bad_pixel_mask.shape:
            raise DetectorRealizationError(
                "prnu_response and bad_pixel_mask must have the same shape; "
                f"got {prnu_response.shape} and {bad_pixel_mask.shape}."
            )
        root_seed = _root_seed(self.root_seed)
        stream_id = self.stream_id
        if stream_id is not None and (
            not isinstance(stream_id, str) or not stream_id.strip()
        ):
            raise DetectorRealizationError(
                "stream_id must be a non-empty string or None."
            )
        config_hash = _nonempty_string(self.config_hash, label="config_hash")
        realization_hash = _nonempty_string(
            self.realization_hash,
            label="realization_hash",
        )
        expected_realization_hash = _realization_hash(
            prnu_response=prnu_response,
            bad_pixel_mask=bad_pixel_mask,
            root_seed=root_seed,
            stream_id=stream_id,
            config_hash=config_hash,
        )
        if realization_hash != expected_realization_hash:
            raise DetectorRealizationError(
                "realization_hash does not match the persistent maps, root "
                "seed, stream ID, and realization configuration."
            )

        object.__setattr__(self, "prnu_response", prnu_response)
        object.__setattr__(self, "bad_pixel_mask", bad_pixel_mask)
        object.__setattr__(self, "root_seed", root_seed)
        object.__setattr__(self, "stream_id", stream_id)
        object.__setattr__(self, "config_hash", config_hash)
        object.__setattr__(self, "realization_hash", realization_hash)

    @property
    def window_shape_px(self) -> tuple[int, int]:
        """Return the immutable detector-map shape in ``(rows, columns)``."""

        return self.prnu_response.shape

    @classmethod
    def create(
        cls,
        config: DetectorConfig,
        window_shape_px: tuple[int, int],
        *,
        random_streams: RandomStreams,
        realization_index: int = 0,
    ) -> DetectorRealization:
        """Create one replayable realization using only its named domain."""

        if not isinstance(config, DetectorConfig):
            raise DetectorRealizationError("config must be a DetectorConfig.")
        shape = _window_shape(window_shape_px)
        if type(realization_index) is not int or realization_index < 0:
            raise DetectorRealizationError(
                "realization_index must be a non-negative integer."
            )
        try:
            root_seed = _root_seed(random_streams.root_seed)
        except AttributeError as exc:
            raise DetectorRealizationError(
                "random_streams must implement the Section 4 RandomStreams contract."
            ) from exc

        fixed_bad_pixels = np.zeros(shape, dtype=bool)
        if config.bad_pixel_mask is not None:
            if config.bad_pixel_mask.shape != shape:
                raise DetectorRealizationError(
                    "config.bad_pixel_mask shape "
                    f"{config.bad_pixel_mask.shape} does not match requested "
                    f"window_shape_px {shape}."
                )
            fixed_bad_pixels = np.array(config.bad_pixel_mask, dtype=bool, copy=True)

        needs_persistent_prnu = (
            config.prnu_mode == "persistent" and config.prnu_rms > 0.0
        )
        needs_generated_bad_pixels = config.bad_pixel_fraction > 0.0
        needs_stream = needs_persistent_prnu or needs_generated_bad_pixels
        config_hash = config.realization_config_hash
        stream_id: str | None = None
        generator = None
        if needs_stream:
            key = (
                "DetectorRealization",
                config_hash,
                shape[0],
                shape[1],
                realization_index,
            )
            try:
                generator = random_streams.keyed_generator(
                    _REALIZATION_DOMAIN,
                    key=key,
                )
                stream_id = random_streams.stream_id(
                    _REALIZATION_DOMAIN,
                    key=key,
                )
            except (AttributeError, TypeError, ValueError) as exc:
                raise DetectorRealizationError(
                    "random_streams could not derive detector.realization."
                ) from exc

        if needs_persistent_prnu:
            assert generator is not None
            prnu_response = generator.normal(
                loc=1.0,
                scale=config.prnu_rms,
                size=shape,
            )
            prnu_response = np.maximum(prnu_response, 0.0)
        else:
            prnu_response = np.ones(shape, dtype=float)

        if needs_generated_bad_pixels:
            assert generator is not None
            generated_bad_pixels = (
                generator.random(shape) < config.bad_pixel_fraction
            )
            bad_pixel_mask = fixed_bad_pixels | generated_bad_pixels
        else:
            bad_pixel_mask = fixed_bad_pixels

        realization_hash = _realization_hash(
            prnu_response=prnu_response,
            bad_pixel_mask=bad_pixel_mask,
            root_seed=root_seed,
            stream_id=stream_id,
            config_hash=config_hash,
        )
        return cls(
            prnu_response=prnu_response,
            bad_pixel_mask=bad_pixel_mask,
            root_seed=root_seed,
            stream_id=stream_id,
            config_hash=config_hash,
            realization_hash=realization_hash,
        )


def _immutable_prnu(value: object) -> np.ndarray:
    if not isinstance(value, np.ndarray):
        raise DetectorRealizationError("prnu_response must be a numpy.ndarray.")
    result = np.array(value, dtype=float, copy=True)
    if result.ndim != 2 or not result.size:
        raise DetectorRealizationError(
            "prnu_response must be a non-empty two-dimensional array."
        )
    if not np.all(np.isfinite(result)) or np.any(result < 0.0):
        raise DetectorRealizationError(
            "prnu_response must contain finite non-negative values."
        )
    return _immutable_array(result)


def _immutable_bad_pixels(value: object) -> np.ndarray:
    if not isinstance(value, np.ndarray) or value.dtype != np.dtype(bool):
        raise DetectorRealizationError(
            "bad_pixel_mask must be a boolean numpy.ndarray."
        )
    result = np.array(value, dtype=bool, copy=True)
    if result.ndim != 2 or not result.size:
        raise DetectorRealizationError(
            "bad_pixel_mask must be a non-empty two-dimensional array."
        )
    return _immutable_array(result)


def _immutable_array(value: np.ndarray) -> np.ndarray:
    contiguous = np.ascontiguousarray(value)
    immutable = np.frombuffer(
        contiguous.tobytes(order="C"),
        dtype=contiguous.dtype,
    )
    return immutable.reshape(contiguous.shape)


def _realization_hash(
    *,
    prnu_response: np.ndarray,
    bad_pixel_mask: np.ndarray,
    root_seed: int,
    stream_id: str | None,
    config_hash: str,
) -> str:
    return stable_hash(
        {
            "bad_pixel_mask": bad_pixel_mask,
            "config_hash": config_hash,
            "prnu_response": prnu_response,
            "root_seed": root_seed,
            "stream_id": stream_id,
            "window_shape_px": prnu_response.shape,
        },
        namespace="detector_realization",
    )


def _window_shape(value: object) -> tuple[int, int]:
    if not isinstance(value, tuple) or len(value) != 2:
        raise DetectorRealizationError(
            "window_shape_px must be a two-item tuple of positive integers."
        )
    rows, columns = value
    if any(
        isinstance(item, bool) or not isinstance(item, int) or item <= 0
        for item in value
    ):
        raise DetectorRealizationError(
            "window_shape_px must be a two-item tuple of positive integers."
        )
    return (rows, columns)


def _root_seed(value: object) -> int:
    if type(value) is not int or value < 0:
        raise DetectorRealizationError(
            "root_seed must be a non-negative integer."
        )
    return value


def _nonempty_string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DetectorRealizationError(f"{label} must be a non-empty string.")
    return value


__all__ = (
    "DetectorRealizationError",
    "DetectorRealization",
)
