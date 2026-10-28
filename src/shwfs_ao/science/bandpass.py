"""Immutable science bandpasses and wavelength-quadrature helpers.

This module owns spectral sampling only.  It deliberately does not generate,
resample, or coadd PSFs: the normalized weights exposed by
``ScienceBandpass`` are for scalar band averages over wavelength.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from numbers import Integral, Real
from typing import Protocol

import numpy as np

from ..core.hashing import component_config_hash
from ..core.provenance import ALLOWED_SOURCE_CLASSES, Provenance


__all__ = (
    "BandpassError",
    "ScienceBandpass",
    "monochromatic_bandpass",
    "top_hat_bandpass",
    "bandpass_from_filter_curve",
)


# These historical names remain available for the installed compatibility
# module, but are intentionally omitted from the canonical public surface.
DEFAULT_DIAGNOSTIC_SOURCE_CLASS = "synthetic_assumed"
DEFAULT_DIAGNOSTIC_SOURCE_NOTE = (
    "Synthetic science diagnostic settings for the 2 m AO demonstrator; "
    "bandpass fallback is not an on-sky calibration."
)


class AODiagnosticsError(ValueError):
    """Historical error identity retained by the diagnostics facade."""


# Canonical domain-specific spelling.  Keeping the historical class object
# means construction through the frozen facade raises its documented error.
BandpassError = AODiagnosticsError


class FilterCurve(Protocol):
    """Structural canonical-unit input accepted by SVO curve conversion."""

    filter_id: str
    wavelength_m: Sequence[float] | np.ndarray
    transmission: Sequence[float] | np.ndarray
    units: Mapping[str, str]
    provenance: Provenance


class _BandpassArray(np.ndarray):
    """Immutable ndarray carrying provenance through ``dataclasses.replace``."""

    _bandpass_provenance: Provenance | None

    def __array_finalize__(self, source: object) -> None:
        object.__setattr__(
            self,
            "_bandpass_provenance",
            getattr(source, "_bandpass_provenance", None),
        )


class _ProvenanceNote(str):
    """String-compatible carrier preserving rich provenance across replace."""

    _bandpass_provenance: Provenance

    def __new__(
        cls,
        value: str,
        provenance: Provenance | None = None,
    ) -> _ProvenanceNote:
        instance = super().__new__(cls, value)
        if provenance is not None:
            object.__setattr__(instance, "_bandpass_provenance", provenance)
        return instance


@dataclass(frozen=True)
class ScienceBandpass:
    """Spectral samples and throughput for scalar science-metric averaging.

    ``wavelength_m`` is a strictly increasing one-dimensional physical axis
    in metres.  ``weights`` uses composite-trapezoid wavelength widths times
    transmission and is normalized to a discrete sum of one.  A one-sample
    bandpass has unit weight.

    The arrays are copied into byte-backed read-only storage at construction;
    mutating an input array later cannot alter the bandpass or its hash.
    These weights do not authorize same-index broadband PSF coaddition.
    """

    __hash_schema_id__ = "shwfs_ao.science.ScienceBandpass.v1"

    # AO-REF-000 freezes these fields, their order, and their defaults.
    name: str
    wavelength_m: np.ndarray
    transmission: np.ndarray
    source_class: str = DEFAULT_DIAGNOSTIC_SOURCE_CLASS
    source_note: str = DEFAULT_DIAGNOSTIC_SOURCE_NOTE
    filter_id: str | None = None

    def __post_init__(self) -> None:
        array_provenance = _array_provenance(
            self.wavelength_m,
            self.transmission,
        )
        note_provenance = getattr(
            self.source_note,
            "_bandpass_provenance",
            None,
        )
        if (
            isinstance(note_provenance, Provenance)
            and array_provenance is not None
            and note_provenance != array_provenance
        ):
            raise BandpassError(
                "source note and sample arrays carry inconsistent provenance."
            )
        inherited_provenance = (
            note_provenance
            if isinstance(note_provenance, Provenance)
            else array_provenance
        )
        _nonempty_string(self.name, label="ScienceBandpass name")
        wavelengths = _float_vector(
            self.wavelength_m,
            label="bandpass wavelengths",
        )
        transmission = _float_vector(
            self.transmission,
            label="bandpass transmission",
        )
        if wavelengths.shape != transmission.shape:
            raise BandpassError(
                "wavelength_m and transmission must have the same shape."
            )
        if wavelengths.size == 0:
            raise BandpassError(
                "ScienceBandpass must contain at least one wavelength sample."
            )
        if np.any(wavelengths <= 0.0):
            raise BandpassError("bandpass wavelengths must be positive.")
        if wavelengths.size > 1 and np.any(np.diff(wavelengths) <= 0.0):
            raise BandpassError(
                "bandpass wavelengths must be strictly increasing."
            )
        if np.any(transmission < 0.0):
            raise BandpassError("bandpass transmission must be non-negative.")
        if not np.any(transmission > 0.0):
            raise BandpassError(
                "bandpass transmission must have positive total weight."
            )

        provenance = _science_bandpass_provenance(
            self.source_class,
            self.source_note,
        )
        if inherited_provenance is not None:
            if (
                inherited_provenance.source_class == self.source_class
                and inherited_provenance.source_note == self.source_note
            ):
                provenance = inherited_provenance
        filter_id = self.filter_id
        if filter_id is not None:
            _nonempty_string(filter_id, label="filter_id")

        weights = _quadrature_weights(wavelengths, transmission)
        object.__setattr__(
            self,
            "wavelength_m",
            _immutable_array(wavelengths, provenance=provenance),
        )
        object.__setattr__(
            self,
            "transmission",
            _immutable_array(transmission, provenance=provenance),
        )
        object.__setattr__(
            self,
            "source_note",
            _ProvenanceNote(str(self.source_note), provenance),
        )
        object.__setattr__(self, "_weights", _immutable_array(weights))
        object.__setattr__(self, "_provenance", provenance)

    @property
    def provenance(self) -> Provenance:
        """Return the full validated provenance record.

        The six declared dataclass fields remain the frozen legacy transport
        shape.  Callers serializing with ``dataclasses.asdict`` must therefore
        serialize this property separately when full provenance is required.
        """

        return self._provenance

    @property
    def weights(self) -> np.ndarray:
        """Return immutable normalized scalar-quadrature weights."""

        return self._weights

    @property
    def effective_wavelength_m(self) -> float:
        """Return the quadrature-weighted wavelength in metres."""

        return float(np.sum(self.wavelength_m * self.weights))

    @property
    def config_hash(self) -> str:
        """Return a stable hash of samples, throughput, and provenance."""

        return component_config_hash(
            "science.bandpass",
            {
                "schema_id": self.__hash_schema_id__,
                "name": self.name,
                "wavelength_m": self.wavelength_m,
                "transmission": self.transmission,
                "provenance": self.provenance,
                "filter_id": self.filter_id,
                "quadrature": "composite_trapezoid_transmission_times_dlambda_v1",
            },
        )


def monochromatic_bandpass(
    name: str,
    wavelength_m: float,
    source_class: str = DEFAULT_DIAGNOSTIC_SOURCE_CLASS,
    source_note: str = DEFAULT_DIAGNOSTIC_SOURCE_NOTE,
) -> ScienceBandpass:
    """Create a one-sample science bandpass."""

    wavelength = _positive_float(wavelength_m, label="wavelength_m")
    return ScienceBandpass(
        name=name,
        wavelength_m=np.asarray([wavelength], dtype=float),
        transmission=np.asarray([1.0], dtype=float),
        source_class=source_class,
        source_note=source_note,
        filter_id=name,
    )


def top_hat_bandpass(
    name: str,
    wavelength_min_m: float,
    wavelength_max_m: float,
    n_samples: int = 9,
    source_class: str = DEFAULT_DIAGNOSTIC_SOURCE_CLASS,
    source_note: str = DEFAULT_DIAGNOSTIC_SOURCE_NOTE,
) -> ScienceBandpass:
    """Create an evenly sampled documented top-hat fallback bandpass."""

    wavelength_min = _positive_float(
        wavelength_min_m,
        label="wavelength_min_m",
    )
    wavelength_max = _positive_float(
        wavelength_max_m,
        label="wavelength_max_m",
    )
    if wavelength_max <= wavelength_min:
        raise BandpassError("wavelength_max_m must exceed wavelength_min_m.")
    sample_count = _positive_integer(n_samples, label="n_samples")
    if sample_count < 2:
        raise BandpassError(
            "n_samples must be at least 2 for a finite-width top-hat bandpass."
        )
    wavelengths = np.linspace(wavelength_min, wavelength_max, sample_count)
    return ScienceBandpass(
        name=name,
        wavelength_m=wavelengths,
        transmission=np.ones_like(wavelengths),
        source_class=source_class,
        source_note=source_note,
        filter_id=f"{name}.top_hat",
    )


def bandpass_from_filter_curve(
    curve: FilterCurve,
    name: str | None = None,
) -> ScienceBandpass:
    """Convert a structurally compatible canonical-unit SVO filter curve.

    The converter intentionally depends on a structural record rather than
    the public-data loader's concrete class.  Inputs must nevertheless state
    canonical metre and dimensionless units so an unconverted SVO wavelength
    column cannot be silently interpreted as metres.
    """

    filter_id = _curve_attribute(curve, "filter_id")
    _nonempty_string(filter_id, label="filter curve filter_id")
    units = _curve_attribute(curve, "units")
    if not isinstance(units, Mapping):
        raise BandpassError("filter curve units must be a mapping.")
    _canonical_curve_unit(units, "wavelength_m", expected="m")
    _canonical_curve_unit(units, "transmission", expected="dimensionless")

    provenance = _curve_attribute(curve, "provenance")
    if not isinstance(provenance, Provenance):
        raise BandpassError(
            "filter curve provenance must be a canonical Provenance record."
        )
    band_name = filter_id if name is None else name
    copied_provenance = Provenance(
        source_class=provenance.source_class,
        source_note=provenance.source_note,
        source_id=provenance.source_id,
        url=provenance.url,
        access_time=provenance.access_time,
        fallback_used=provenance.fallback_used,
        references=provenance.references,
    )
    wavelengths = _float_vector(
        _curve_attribute(curve, "wavelength_m"),
        label="bandpass wavelengths",
    )
    transmission = _float_vector(
        _curve_attribute(curve, "transmission"),
        label="bandpass transmission",
    )
    return ScienceBandpass(
        name=band_name,
        wavelength_m=_immutable_array(
            wavelengths,
            provenance=copied_provenance,
        ),
        transmission=_immutable_array(
            transmission,
            provenance=copied_provenance,
        ),
        source_class=copied_provenance.source_class,
        source_note=copied_provenance.source_note,
        filter_id=filter_id,
    )


def _quadrature_weights(
    wavelengths: np.ndarray,
    transmission: np.ndarray,
) -> np.ndarray:
    if wavelengths.size == 1:
        return np.ones(1, dtype=float)
    intervals = np.diff(wavelengths)
    quadrature_width = np.empty_like(wavelengths)
    quadrature_width[0] = 0.5 * intervals[0]
    quadrature_width[-1] = 0.5 * intervals[-1]
    quadrature_width[1:-1] = 0.5 * (intervals[:-1] + intervals[1:])
    with np.errstate(over="ignore", invalid="ignore"):
        raw = transmission * quadrature_width
        total = float(np.sum(raw))
    if not math.isfinite(total) or total <= 0.0 or not np.all(np.isfinite(raw)):
        raise BandpassError(
            "bandpass wavelength quadrature must have positive finite total weight."
        )
    weights = raw / total
    if not np.all(np.isfinite(weights)):
        raise BandpassError("bandpass weights must be finite.")
    return weights


def _float_vector(value: object, *, label: str) -> np.ndarray:
    try:
        array = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise BandpassError(f"{label} must be a one-dimensional numeric array.") from exc
    if array.ndim != 1:
        raise BandpassError(f"{label} must be one-dimensional; got shape {array.shape}.")
    if not np.all(np.isfinite(array)):
        finite_fraction = float(np.mean(np.isfinite(array))) if array.size else 0.0
        raise BandpassError(
            f"Non-finite values in {label}; finite_frac={finite_fraction:.3f}."
        )
    return np.array(array, dtype=float, copy=True, order="C")


def _immutable_array(
    value: np.ndarray,
    *,
    provenance: Provenance | None = None,
) -> np.ndarray:
    contiguous = np.ascontiguousarray(value, dtype=float)
    immutable = np.frombuffer(contiguous.tobytes(order="C"), dtype=float).reshape(
        contiguous.shape
    )
    if provenance is None:
        return immutable
    carried = immutable.view(_BandpassArray)
    object.__setattr__(carried, "_bandpass_provenance", provenance)
    return carried


def _array_provenance(
    wavelength_m: object,
    transmission: object,
) -> Provenance | None:
    wavelength_provenance = getattr(wavelength_m, "_bandpass_provenance", None)
    transmission_provenance = getattr(
        transmission,
        "_bandpass_provenance",
        None,
    )
    if wavelength_provenance is None and transmission_provenance is None:
        return None
    if wavelength_provenance is None:
        return (
            transmission_provenance
            if isinstance(transmission_provenance, Provenance)
            else None
        )
    if transmission_provenance is None:
        return (
            wavelength_provenance
            if isinstance(wavelength_provenance, Provenance)
            else None
        )
    if not isinstance(wavelength_provenance, Provenance) or (
        wavelength_provenance != transmission_provenance
    ):
        raise BandpassError(
            "wavelength and transmission arrays carry inconsistent provenance."
        )
    return wavelength_provenance


def _science_bandpass_provenance(
    source_class: object,
    source_note: object,
) -> Provenance:
    try:
        return Provenance(source_class=source_class, source_note=source_note)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        if (
            not isinstance(source_class, str)
            or source_class not in ALLOWED_SOURCE_CLASSES
        ):
            raise BandpassError(
                f"source_class={source_class!r} is not in the permitted taxonomy "
                f"{sorted(ALLOWED_SOURCE_CLASSES)}."
            ) from exc
        raise BandpassError(
            "ScienceBandpass source_note must be non-empty."
        ) from exc


def _nonempty_string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BandpassError(f"{label} must be non-empty.")
    return value


def _positive_float(value: object, *, label: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise BandpassError(f"{label} must be a finite real number.")
    result = float(value)
    if not math.isfinite(result):
        raise BandpassError(f"{label} must be finite.")
    if result <= 0.0:
        raise BandpassError(f"{label} must be positive; got {value!r}.")
    return result


def _positive_integer(value: object, *, label: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise BandpassError(f"{label} must be an integer.")
    result = int(value)
    if result < 1:
        raise BandpassError(f"{label} must be >= 1.")
    return result


def _curve_attribute(curve: object, name: str) -> object:
    try:
        return getattr(curve, name)
    except (AttributeError, TypeError) as exc:
        raise BandpassError(
            f"filter curve is missing required attribute {name!r}."
        ) from exc


def _canonical_curve_unit(
    units: Mapping[object, object],
    field_name: str,
    *,
    expected: str,
) -> None:
    actual = units.get(field_name)
    if actual != expected:
        raise BandpassError(
            f"filter curve unit for {field_name!r} must be {expected!r}; "
            f"got {actual!r}."
        )
