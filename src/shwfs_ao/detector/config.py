"""Canonical detector configuration and quality presets.

The first eleven :class:`DetectorConfig` fields and all historical preset
arguments retain their legacy order.  Canonical persistent PRNU and deferred
bad-pixel generation are opt-in trailing configuration, so structural
extraction does not silently change the frozen per-frame detector model.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal, cast

import numpy as np

from ..core.hashing import component_config_hash
from ..core.provenance import ALLOWED_SOURCE_CLASSES, Provenance, SourceClass


DEFAULT_SOURCE_CLASS = "synthetic_assumed"
PrnuMode = Literal["per_frame_legacy", "persistent"]
_PRNU_MODES = frozenset({"per_frame_legacy", "persistent"})


class SyntheticInstrumentError(ValueError):
    """Raised when detector configuration or preset data is invalid."""


# Canonical code can use the domain-specific name while legacy callers retain
# the historical exception identity and message behavior.
DetectorConfigError = SyntheticInstrumentError


@dataclass(frozen=True)
class DetectorConfig:
    """Detector noise configuration with explicit realization policy."""

    __hash_schema_id__ = "shwfs_ao.detector.DetectorConfig.v1"

    # Historical field order is a compatibility contract.
    photons_per_subap_frame: float | None = None
    read_noise_e: float = 0.0
    dark_e_per_s: float = 0.0
    background_e_per_pixel_frame: float = 0.0
    full_well_e: float | None = None
    qe: float = 1.0
    bad_pixel_mask: np.ndarray | None = None
    prnu_rms: float = 0.0
    exposure_s: float = 1.0e-3
    source_class: str = DEFAULT_SOURCE_CLASS
    source_note: str = (
        "Synthetic detector settings for unit tests and fast-mode demos."
    )
    # New behavior is trailing and opt-in.
    prnu_mode: PrnuMode = "per_frame_legacy"
    bad_pixel_fraction: float = 0.0

    def __post_init__(self) -> None:
        provenance = _instrument_provenance(self.source_class, self.source_note)
        photons_per_subap_frame = _optional_nonnegative(
            "photons_per_subap_frame",
            self.photons_per_subap_frame,
        )
        read_noise_e = _nonnegative("read_noise_e", self.read_noise_e)
        dark_e_per_s = _nonnegative("dark_e_per_s", self.dark_e_per_s)
        background_e_per_pixel_frame = _nonnegative(
            "background_e_per_pixel_frame",
            self.background_e_per_pixel_frame,
        )
        full_well_e = _optional_positive("full_well_e", self.full_well_e)
        qe = _positive("qe", self.qe)
        prnu_rms = _nonnegative("prnu_rms", self.prnu_rms)
        exposure_s = _positive("exposure_s", self.exposure_s)
        bad_pixel_fraction = _fraction(
            "bad_pixel_fraction",
            self.bad_pixel_fraction,
        )
        if self.prnu_mode not in _PRNU_MODES:
            raise SyntheticInstrumentError(
                f"prnu_mode must be one of {sorted(_PRNU_MODES)}; "
                f"got {self.prnu_mode!r}."
            )
        prnu_mode = cast(PrnuMode, self.prnu_mode)
        bad_pixel_mask = _immutable_optional_mask(self.bad_pixel_mask)

        object.__setattr__(self, "photons_per_subap_frame", photons_per_subap_frame)
        object.__setattr__(self, "read_noise_e", read_noise_e)
        object.__setattr__(self, "dark_e_per_s", dark_e_per_s)
        object.__setattr__(
            self,
            "background_e_per_pixel_frame",
            background_e_per_pixel_frame,
        )
        object.__setattr__(self, "full_well_e", full_well_e)
        object.__setattr__(self, "qe", qe)
        object.__setattr__(self, "bad_pixel_mask", bad_pixel_mask)
        object.__setattr__(self, "prnu_rms", prnu_rms)
        object.__setattr__(self, "exposure_s", exposure_s)
        object.__setattr__(self, "source_class", provenance.source_class)
        object.__setattr__(self, "source_note", provenance.source_note)
        object.__setattr__(self, "prnu_mode", prnu_mode)
        object.__setattr__(self, "bad_pixel_fraction", bad_pixel_fraction)

    @property
    def provenance(self) -> Provenance:
        """Return canonical provenance for this detector configuration."""

        return _instrument_provenance(
            self.source_class,
            self.source_note,
            references=(f"detector_prnu_mode={self.prnu_mode}",),
        )

    @property
    def config_hash(self) -> str:
        """Return a canonical content hash including fixed detector maps."""

        return component_config_hash("detector", self)

    @property
    def realization_config_hash(self) -> str:
        """Hash only settings that determine persistent physical maps.

        Photon budget, quantum efficiency, temporal noise, saturation,
        exposure, and provenance do not change the identity of a realized PRNU
        or defect map. Per-frame legacy PRNU is likewise excluded because it
        is drawn by the effects call rather than stored in the realization.
        """

        return component_config_hash(
            "detector_realization",
            {
                "prnu_mode": self.prnu_mode,
                "persistent_prnu_rms": (
                    self.prnu_rms if self.prnu_mode == "persistent" else 0.0
                ),
                "bad_pixel_mask": self.bad_pixel_mask,
                "bad_pixel_fraction": self.bad_pixel_fraction,
            },
        )


@dataclass(frozen=True)
class DetectorPreset:
    """Named synthetic detector-quality preset for the visible SH-WFS."""

    __hash_schema_id__ = "shwfs_ao.detector.DetectorPreset.v1"

    # Historical field order is a compatibility contract.
    preset_name: str
    read_noise_e: float
    dark_e_per_s: float
    background_e_per_pixel_frame: float
    full_well_e: float | None
    prnu_rms: float
    bad_pixel_fraction: float
    exposure_s: float = 1.0e-3
    source_class: str = "synthetic_assumed"
    source_note: str = (
        "Synthetic visible SH-WFS detector-quality preset; not a measured "
        "detector calibration."
    )

    def __post_init__(self) -> None:
        if not isinstance(self.preset_name, str) or not self.preset_name.strip():
            raise SyntheticInstrumentError("preset_name must be a non-empty string.")
        read_noise_e = _nonnegative("read_noise_e", self.read_noise_e)
        dark_e_per_s = _nonnegative("dark_e_per_s", self.dark_e_per_s)
        background_e_per_pixel_frame = _nonnegative(
            "background_e_per_pixel_frame",
            self.background_e_per_pixel_frame,
        )
        full_well_e = _optional_positive("full_well_e", self.full_well_e)
        prnu_rms = _nonnegative("prnu_rms", self.prnu_rms)
        bad_pixel_fraction = _fraction(
            "bad_pixel_fraction",
            self.bad_pixel_fraction,
        )
        exposure_s = _positive("exposure_s", self.exposure_s)
        provenance = _instrument_provenance(self.source_class, self.source_note)

        object.__setattr__(self, "read_noise_e", read_noise_e)
        object.__setattr__(self, "dark_e_per_s", dark_e_per_s)
        object.__setattr__(
            self,
            "background_e_per_pixel_frame",
            background_e_per_pixel_frame,
        )
        object.__setattr__(self, "full_well_e", full_well_e)
        object.__setattr__(self, "prnu_rms", prnu_rms)
        object.__setattr__(self, "bad_pixel_fraction", bad_pixel_fraction)
        object.__setattr__(self, "exposure_s", exposure_s)
        object.__setattr__(self, "source_class", provenance.source_class)
        object.__setattr__(self, "source_note", provenance.source_note)

    @property
    def provenance(self) -> Provenance:
        """Return canonical provenance for this detector preset."""

        return _instrument_provenance(self.source_class, self.source_note)

    @property
    def config_hash(self) -> str:
        """Return the canonical preset content hash."""

        return component_config_hash("detector_preset", self)

    def to_detector_config(
        self,
        photons_per_subap_frame: float | None,
        *,
        window_px: int | None = None,
        seed: int | None = None,
        qe: float = 1.0,
    ) -> "DetectorConfig":
        """Build a detector config with the frozen historical signature."""

        bad_pixel_mask = None
        if (
            self.bad_pixel_fraction > 0.0
            and window_px is not None
            and seed is not None
        ):
            bad_pixel_mask = make_bad_pixel_mask(
                int(window_px),
                float(self.bad_pixel_fraction),
                seed=int(seed),
            )
        return DetectorConfig(
            photons_per_subap_frame=photons_per_subap_frame,
            read_noise_e=self.read_noise_e,
            dark_e_per_s=self.dark_e_per_s,
            background_e_per_pixel_frame=self.background_e_per_pixel_frame,
            full_well_e=self.full_well_e,
            qe=qe,
            bad_pixel_mask=bad_pixel_mask,
            prnu_rms=self.prnu_rms,
            exposure_s=self.exposure_s,
            source_class=self.source_class,
            source_note=f"{self.source_note} (preset={self.preset_name})",
        )


def make_bad_pixel_mask(
    window_px: int,
    bad_pixel_fraction: float,
    *,
    seed: int,
) -> np.ndarray:
    """Return the frozen-algorithm seeded square bad-pixel mask."""

    if window_px < 1:
        raise SyntheticInstrumentError(
            "window_px must be >= 1 for a bad-pixel mask; "
            f"got {window_px!r}."
        )
    if not 0.0 <= bad_pixel_fraction <= 1.0:
        raise SyntheticInstrumentError(
            "bad_pixel_fraction must be between 0 and 1; "
            f"got {bad_pixel_fraction!r}."
        )
    rng = np.random.default_rng(seed)
    return rng.random((window_px, window_px)) < bad_pixel_fraction


def _instrument_provenance(
    source_class: object,
    source_note: object,
    *,
    references: tuple[str, ...] = (),
) -> Provenance:
    try:
        return Provenance(
            source_class=cast(SourceClass, source_class),
            source_note=cast(str, source_note),
            references=references,
        )
    except (TypeError, ValueError) as exc:
        if source_class not in ALLOWED_SOURCE_CLASSES:
            raise SyntheticInstrumentError(
                f"source_class={source_class!r} is not in the permitted taxonomy "
                f"{sorted(ALLOWED_SOURCE_CLASSES)}."
            ) from exc
        raise SyntheticInstrumentError(
            "source_note must be a non-empty string."
        ) from exc


def _immutable_optional_mask(value: object) -> np.ndarray | None:
    if value is None:
        return None
    array = np.asarray(value, dtype=bool)
    if array.ndim != 2:
        raise SyntheticInstrumentError(
            f"bad_pixel_mask must be two-dimensional; got shape {array.shape}."
        )
    contiguous = np.ascontiguousarray(np.array(array, dtype=bool, copy=True))
    immutable = np.frombuffer(
        contiguous.tobytes(order="C"),
        dtype=contiguous.dtype,
    )
    return immutable.reshape(contiguous.shape)


def _finite(field_name: str, value: object) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise SyntheticInstrumentError(
            f"{field_name} must be finite; got {value!r}."
        ) from exc
    if not math.isfinite(result):
        raise SyntheticInstrumentError(
            f"{field_name} must be finite; got {value!r}."
        )
    return result


def _nonnegative(field_name: str, value: object) -> float:
    result = _finite(field_name, value)
    if result < 0.0:
        raise SyntheticInstrumentError(
            f"{field_name} must be non-negative; got {value!r}."
        )
    return result


def _positive(field_name: str, value: object) -> float:
    result = _finite(field_name, value)
    if result <= 0.0:
        raise SyntheticInstrumentError(
            f"{field_name} must be positive; got {value!r}."
        )
    return result


def _optional_nonnegative(field_name: str, value: object) -> float | None:
    if value is None:
        return None
    return _nonnegative(field_name, value)


def _optional_positive(field_name: str, value: object) -> float | None:
    if value is None:
        return None
    return _positive(field_name, value)


def _fraction(field_name: str, value: object) -> float:
    result = _finite(field_name, value)
    if not 0.0 <= result <= 1.0:
        raise SyntheticInstrumentError(
            f"{field_name} must be between 0 and 1; got {value!r}."
        )
    return result


# Keep the frozen historical names and values.  Presets describe synthetic
# visible-WFS detector quality, not measured calibration data.
DETECTOR_PRESETS: dict[str, DetectorPreset] = {
    "ideal": DetectorPreset(
        preset_name="ideal",
        read_noise_e=0.0,
        dark_e_per_s=0.0,
        background_e_per_pixel_frame=0.0,
        full_well_e=None,
        prnu_rms=0.0,
        bad_pixel_fraction=0.0,
        source_note=(
            "Ideal noise-free visible SH-WFS detector reference; no "
            "read/dark/background/PRNU/saturation."
        ),
    ),
    "low_noise_sCMOS_like": DetectorPreset(
        preset_name="low_noise_sCMOS_like",
        read_noise_e=1.0,
        dark_e_per_s=5.0,
        background_e_per_pixel_frame=0.5,
        full_well_e=50000.0,
        prnu_rms=0.01,
        bad_pixel_fraction=0.001,
        source_note=(
            "Low-noise scientific-CMOS-like visible WFS detector engineering "
            "preset; synthetic, no datasheet cited."
        ),
    ),
    "noisy_visible_wfs": DetectorPreset(
        preset_name="noisy_visible_wfs",
        read_noise_e=10.0,
        dark_e_per_s=50.0,
        background_e_per_pixel_frame=3.0,
        full_well_e=30000.0,
        prnu_rms=0.02,
        bad_pixel_fraction=0.005,
        source_note=(
            "Noisy visible SH-WFS detector engineering preset; elevated read "
            "noise/dark/background."
        ),
    ),
    "stress_saturated_window": DetectorPreset(
        preset_name="stress_saturated_window",
        read_noise_e=12.0,
        dark_e_per_s=80.0,
        background_e_per_pixel_frame=5.0,
        full_well_e=2000.0,
        prnu_rms=0.03,
        bad_pixel_fraction=0.01,
        source_note=(
            "Stress preset: low full well saturates/clips the spot, plus "
            "elevated noise and dead pixels."
        ),
    ),
}


def detector_preset(name: str) -> DetectorPreset:
    """Return a named visible SH-WFS detector-quality preset."""

    try:
        return DETECTOR_PRESETS[name]
    except KeyError as exc:
        raise SyntheticInstrumentError(
            f"Unknown detector preset {name!r}; "
            f"choose from {sorted(DETECTOR_PRESETS)}."
        ) from exc


__all__ = (
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
