"""RTC pixel processing with estimated calibration products (DET-06).

Calibration frames are produced by the same physical camera chain
(:func:`~shwfs_ao.detector.physical.apply_physical_camera`), layout, maps,
gain and readout as measurements, with temporal noise drawn from the
registered ``detector.calibration_frames`` domain keyed by
``(product, frame, block row, block column, stage domain)``.  Products are in
the raw readout unit (ADU, or ``output_e_equivalent`` with the ADC off):

* ``B`` (master bias): mean of ``n_bias`` shuttered zero-exposure frames.  It
  contains the per-read pre-register CIC mean.
* ``D`` (master dark): mean of ``n_dark`` shuttered frames at the operating
  exposure, minus ``B``.
* ``S`` (master sky, optional): mean of ``n_sky`` source-off sky frames at the
  operating exposure, minus ``B`` and ``D``.
* flat: mean of ``n_flat`` uniformly illuminated frames at the operating
  exposure (no sky), minus ``B`` and ``D``, converted to input electrons by the
  same conversion as measurements, then normalized to unit mean over the
  valid pixels of all retained blocks.

Processing subtracts ``B + D + S`` once.  That sum telescopes to the mean of
the sky frames (or of the dark frames without sky frames), so no component is
subtracted twice and the shared-frame covariance follows from the algebra:
the subtracted background has the variance of one sky (dark) frame divided by
its frame count, and the flat shares the dark frames' mean.

The processed, input-referred image of a block is

    Y = P[ (X - (B + D + S)) * c / F ]

with ``c`` the declared raw-to-input-electron conversion (known gain:
``g * m_i / G`` with the ADC on and the CMOS gain map applied as known
per-pixel conversion gain; ``g / G`` when the flat absorbs the gain map; with
the ADC off the scalar ``g`` is already folded into the analog readout), ``F``
the normalized flat, and ``P`` the bad-pixel policy (zero weight, or the mean
of the valid 4-neighbours).  Negative clipping, when declared, follows the
background subtraction.  The relative gain map is corrected once: either by
``c`` or by the flat, never both.

``oracle`` mode replaces the estimates by the deterministic reference
background (a source-off frame of the reference path) and the normalized
deterministic uniform-illumination response.  It does not invert coupling,
non-linearity or saturation.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from numbers import Integral, Real
from typing import Any, Literal

import numpy as np

from ..core.hashing import component_config_hash
from ..core.protocols import RandomStreams
from .camera import CameraConfig
from .camera_maps import CameraMaps
from .layout import lenslet_block_indices
from .physical import POISSON_ROUNDOFF_FLOOR, apply_physical_camera


__all__ = (
    "PROCESSING_MODES",
    "PixelProcessingError",
    "PixelProcessingConfig",
    "CalibrationProducts",
    "raw_to_input_e",
    "build_calibration_products",
    "process_frames",
    "interpolation_matrix_rows",
)


ProcessingMode = Literal["estimated", "oracle", "raw_readout"]
PROCESSING_MODES: tuple[str, ...] = ("estimated", "oracle", "raw_readout")
_CALIBRATION_DOMAIN = "detector.calibration_frames"


class PixelProcessingError(ValueError):
    """Raised when processing settings or calibration products are invalid."""


@dataclass(frozen=True)
class PixelProcessingConfig:
    """Declared RTC pixel processing and calibration-frame protocol (B08/B09)."""

    __hash_schema_id__ = "shwfs_ao.detector.PixelProcessingConfig.v1"

    mode: ProcessingMode
    n_bias_frames: int = 0
    n_dark_frames: int = 0
    n_sky_frames: int = 0
    n_flat_frames: int = 0
    flat_level_e: float = 0.0
    hot_pixel_threshold_e: float = 0.0
    flat_low_threshold: float = 0.5
    flat_high_threshold: float = 1.5
    bad_pixel_policy: Literal["zero_weight", "interpolate_mean4"] = "zero_weight"
    gain_treatment: Literal["known_per_pixel", "flat_absorbs_gain_map"] = "known_per_pixel"
    clip_negative: bool = False

    def __post_init__(self) -> None:
        if self.mode not in PROCESSING_MODES:
            raise PixelProcessingError(
                f"mode must be one of {list(PROCESSING_MODES)}; got {self.mode!r}."
            )
        for name in ("n_bias_frames", "n_dark_frames", "n_sky_frames", "n_flat_frames"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, Integral) or int(value) < 0:
                raise PixelProcessingError(f"{name} must be a non-negative integer.")
            object.__setattr__(self, name, int(value))
        for name in ("flat_level_e", "hot_pixel_threshold_e", "flat_low_threshold", "flat_high_threshold"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)) or value < 0.0:
                raise PixelProcessingError(f"{name} must be finite and non-negative.")
            object.__setattr__(self, name, float(value))
        if self.bad_pixel_policy not in ("zero_weight", "interpolate_mean4"):
            raise PixelProcessingError("unknown bad_pixel_policy.")
        if self.gain_treatment not in ("known_per_pixel", "flat_absorbs_gain_map"):
            raise PixelProcessingError("unknown gain_treatment.")
        if not isinstance(self.clip_negative, bool):
            raise PixelProcessingError("clip_negative must be a boolean.")
        if self.mode == "estimated":
            if min(self.n_bias_frames, self.n_dark_frames, self.n_flat_frames) < 1:
                raise PixelProcessingError(
                    "estimated processing needs at least one bias, dark and flat frame."
                )
            if self.flat_level_e <= 0.0:
                raise PixelProcessingError("estimated processing needs flat_level_e > 0.")
        elif self.mode == "oracle":
            if self.flat_level_e <= 0.0:
                raise PixelProcessingError(
                    "oracle processing needs flat_level_e > 0 for its reference flat."
                )
        if not self.flat_low_threshold < 1.0 < self.flat_high_threshold:
            raise PixelProcessingError(
                "flat thresholds must bracket one: low < 1 < high."
            )
        if self.hot_pixel_threshold_e <= 0.0 and self.mode != "raw_readout":
            raise PixelProcessingError("hot_pixel_threshold_e must be positive.")

    @property
    def config_hash(self) -> str:
        return component_config_hash("pixel_processing", self)


@dataclass(frozen=True)
class CalibrationProducts:
    """Fixed products of one calibration realization, in the raw unit."""

    mode: str
    raw_unit: str
    background_raw: np.ndarray
    bias_raw: np.ndarray
    dark_raw: np.ndarray
    sky_raw: np.ndarray | None
    flat: np.ndarray
    bad: np.ndarray
    conversion_input_e_per_raw: np.ndarray
    frame_counts: tuple[tuple[str, int], ...]
    saturated_calibration_pixels: int
    content_sha256: str

    @property
    def content_hash(self) -> str:
        return self.content_sha256

    @property
    def masked_fraction(self) -> float:
        return float(np.mean(self.bad))


def raw_to_input_e(
    camera: CameraConfig,
    maps: CameraMaps,
    config: PixelProcessingConfig,
) -> np.ndarray:
    """Per-pixel input electrons per raw unit, the declared known gain."""

    shape = maps.shape
    relative = np.ones(shape) if maps.gain_multiplier is None else np.asarray(maps.gain_multiplier)
    per_pixel = config.gain_treatment == "known_per_pixel"
    if camera.adc_bits is not None:
        factor = float(camera.conversion_gain_e_per_adu) * (relative if per_pixel else np.ones(shape))
    else:
        factor = relative if per_pixel else np.ones(shape)
    return np.asarray(factor, dtype=float) / float(camera.em_gain)


def interpolation_matrix_rows(bad_block: np.ndarray) -> list[tuple[int, list[int], float]]:
    """Linear rows of the 4-neighbour mean for every bad pixel of one block.

    Each entry is ``(pixel_flat_index, neighbour_flat_indices, weight)``; the
    bad pixel becomes ``weight * sum(neighbours)``.  A bad pixel without a
    valid neighbour gets no entry and stays zero.
    """

    rows, columns = bad_block.shape
    entries = []
    for r, c in zip(*np.nonzero(bad_block)):
        neighbours = []
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            rr, cc = r + dr, c + dc
            if 0 <= rr < rows and 0 <= cc < columns and not bad_block[rr, cc]:
                neighbours.append(rr * columns + cc)
        if neighbours:
            entries.append((int(r * columns + c), neighbours, 1.0 / len(neighbours)))
    return entries


def _calibration_generators(
    random_streams: RandomStreams,
    product: str,
    frame: int,
    subaperture_ids: tuple[str, ...],
) -> Any:
    blocks = [lenslet_block_indices(identifier) for identifier in subaperture_ids]

    def provider(index: int, domain: str) -> np.random.Generator:
        row, column = blocks[index]
        return random_streams.keyed_generator(
            _CALIBRATION_DOMAIN, key=(product, frame, row, column, domain)
        )

    return provider


def build_calibration_products(
    camera: CameraConfig,
    maps: CameraMaps,
    config: PixelProcessingConfig,
    *,
    exposure_s: float,
    sky_e_per_pixel: np.ndarray | float,
    random_streams: RandomStreams | None,
    include_noise: bool = True,
) -> CalibrationProducts:
    """Generate and reduce calibration frames, or form oracle products.

    ``include_noise=False`` generates every calibration frame on the
    deterministic reference path; the masters then equal the oracle
    background up to the CIC handling, which is the noiseless fixture of the
    DET-06 acceptance.
    """

    if config.mode == "raw_readout":
        raise PixelProcessingError("raw_readout processing uses no calibration products.")
    shape = maps.shape
    n = shape[0]
    sky = np.asarray(sky_e_per_pixel, dtype=float)
    sky = np.full(n, float(sky)) if sky.ndim == 0 else sky
    map_arrays = maps.subset(np.arange(n))
    conversion = raw_to_input_e(camera, maps, config)
    zeros = np.zeros(shape)
    saturated = 0

    def frames(product: str, count: int, *, source: np.ndarray, sky_level: np.ndarray, exposure: float) -> np.ndarray:
        nonlocal saturated
        if include_noise and random_streams is None:
            raise PixelProcessingError("noisy calibration frames need random_streams.")
        total = np.zeros(shape)
        floor = POISSON_ROUNDOFF_FLOOR * (float(np.max(source, initial=0.0)) + float(np.max(sky_level, initial=0.0)) + 1.0)
        for frame in range(count):
            batch = apply_physical_camera(
                source,
                sky_level,
                camera,
                map_arrays,
                exposure_s=exposure,
                include_noise=include_noise,
                generators=(
                    None
                    if not include_noise
                    else _calibration_generators(
                        random_streams,  # type: ignore[arg-type]  # checked above
                        product,
                        frame,
                        maps.subaperture_ids,
                    )
                ),
                poisson_floor_e=floor,
            )
            flagged = batch.pixel_saturated | batch.register_saturated | batch.digital_saturated
            saturated_mask[...] |= flagged
            total += batch.raw
        return total / count

    saturated_mask = np.zeros(shape, dtype=bool)
    if include_noise and random_streams is None and config.mode == "estimated":
        raise PixelProcessingError("noisy calibration frames need random_streams.")
    if config.mode == "estimated":
        bias = frames("bias", config.n_bias_frames, source=zeros, sky_level=np.zeros(n), exposure=0.0)
        dark_mean = frames("dark", config.n_dark_frames, source=zeros, sky_level=np.zeros(n), exposure=exposure_s)
        dark = dark_mean - bias
        if config.n_sky_frames > 0:
            sky_mean = frames("sky", config.n_sky_frames, source=zeros, sky_level=sky, exposure=exposure_s)
            sky_raw: np.ndarray | None = sky_mean - bias - dark
            background = bias + dark + sky_raw
        else:
            sky_raw = None
            background = bias + dark
        flat_mean = frames(
            "flat",
            config.n_flat_frames,
            source=np.full(shape, config.flat_level_e),
            sky_level=np.zeros(n),
            exposure=exposure_s,
        )
        flat_raw = flat_mean - bias - dark
    else:  # oracle: deterministic reference products, no calibration noise.
        def reference(source: np.ndarray, sky_level: np.ndarray, exposure: float) -> np.ndarray:
            batch = apply_physical_camera(
                source, sky_level, camera, map_arrays,
                exposure_s=exposure, include_noise=False, generators=None, poisson_floor_e=0.0,
            )
            saturated_mask[...] |= batch.pixel_saturated | batch.register_saturated | batch.digital_saturated
            return batch.raw

        bias = reference(zeros, np.zeros(n), 0.0)
        dark = reference(zeros, np.zeros(n), exposure_s) - bias
        sky_raw = reference(zeros, sky, exposure_s) - bias - dark
        background = bias + dark + sky_raw
        flat_raw = reference(np.full(shape, config.flat_level_e), np.zeros(n), exposure_s) - bias - dark

    flat_e = flat_raw * conversion
    dark_e = dark * conversion
    preliminary_valid = ~saturated_mask & (flat_e > 0.0)
    if not np.any(preliminary_valid):
        raise PixelProcessingError("no valid flat-field pixel remains.")
    flat = flat_e / float(np.mean(flat_e[preliminary_valid]))
    bad = (
        saturated_mask
        | (flat < config.flat_low_threshold)
        | (flat > config.flat_high_threshold)
        | (dark_e > config.hot_pixel_threshold_e)
    )
    valid = ~bad
    if not np.any(valid):
        raise PixelProcessingError("every pixel was flagged bad.")
    # Renormalize over the final valid set so the declared normalization holds.
    flat = flat_e / float(np.mean(flat_e[valid]))
    flat = np.where(valid, flat, 1.0)
    saturated = int(np.count_nonzero(saturated_mask))

    digest = hashlib.sha256()
    for name, array in (
        ("background", background),
        ("bias", bias),
        ("dark", dark),
        ("sky", sky_raw),
        ("flat", flat),
        ("bad", bad),
        ("conversion", conversion),
    ):
        digest.update(name.encode("ascii"))
        if array is None:
            digest.update(b"none")
        else:
            contiguous = np.ascontiguousarray(array)
            digest.update(str(contiguous.dtype).encode("ascii"))
            digest.update(str(contiguous.shape).encode("ascii"))
            digest.update(contiguous.tobytes(order="C"))
    digest.update(config.config_hash.encode("ascii"))
    counts = (
        ("bias", config.n_bias_frames if config.mode == "estimated" else 0),
        ("dark", config.n_dark_frames if config.mode == "estimated" else 0),
        ("sky", config.n_sky_frames if config.mode == "estimated" else 0),
        ("flat", config.n_flat_frames if config.mode == "estimated" else 0),
    )
    return CalibrationProducts(
        mode=config.mode,
        raw_unit=camera.raw_unit,
        background_raw=_readonly(background),
        bias_raw=_readonly(bias),
        dark_raw=_readonly(dark),
        sky_raw=None if sky_raw is None else _readonly(sky_raw),
        flat=_readonly(flat),
        bad=_readonly(bad),
        conversion_input_e_per_raw=_readonly(conversion),
        frame_counts=counts,
        saturated_calibration_pixels=saturated,
        content_sha256=digest.hexdigest(),
    )


def process_frames(
    raw: np.ndarray,
    products: CalibrationProducts | None,
    config: PixelProcessingConfig,
    *,
    indices: np.ndarray | None = None,
) -> np.ndarray:
    """Processed input-referred images of a batch of blocks.

    ``indices`` selects the retained blocks of ``products`` the batch
    corresponds to (default: all, in order).  ``raw_readout`` returns the raw
    readout unchanged, as a float array.
    """

    values = np.asarray(raw, dtype=float)
    if config.mode == "raw_readout":
        return values.copy()
    if products is None:
        raise PixelProcessingError(f"{config.mode} processing needs calibration products.")
    select = slice(None) if indices is None else indices
    background = products.background_raw[select]
    conversion = products.conversion_input_e_per_raw[select]
    flat = products.flat[select]
    bad = products.bad[select]
    processed = (values - background) * conversion / flat
    if config.bad_pixel_policy == "zero_weight":
        processed[bad] = 0.0
    else:
        processed = _interpolate_mean4(processed, bad)
    if config.clip_negative:
        np.maximum(processed, 0.0, out=processed)
    return processed


def _interpolate_mean4(values: np.ndarray, bad: np.ndarray) -> np.ndarray:
    result = values.copy()
    result[bad] = 0.0
    valid = (~bad).astype(float)
    padded_values = np.pad(np.where(bad, 0.0, values), ((0, 0), (1, 1), (1, 1)))
    padded_valid = np.pad(valid, ((0, 0), (1, 1), (1, 1)))
    rows, columns = values.shape[1:]
    total = np.zeros_like(values)
    count = np.zeros_like(values)
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        total += padded_values[:, 1 + dr : 1 + dr + rows, 1 + dc : 1 + dc + columns]
        count += padded_valid[:, 1 + dr : 1 + dr + rows, 1 + dc : 1 + dc + columns]
    fill = np.divide(total, count, out=np.zeros_like(total), where=count > 0)
    result[bad] = fill[bad]
    return result


def _readonly(values: np.ndarray) -> np.ndarray:
    result = np.array(values, copy=True)
    result.flags.writeable = False
    return result
