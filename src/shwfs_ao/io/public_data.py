# Data-source loaders return structured objects with units and source_class provenance; no notebook-only parsing is required.

"""Canonical public-data interfaces for the realistic 2 m SCAO demonstrator.

The loaders in this module are deliberately small and offline-first. They
parse local JSON/CSV fixtures or cache files into typed records that carry
units and provenance, so notebook 11 can consume data without ad hoc parsing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import json
import math
from typing import Any

from ..core.provenance import ALLOWED_SOURCE_CLASSES, Provenance
from .resources import open_text_resource


CSV_COMMENT_PREFIX = "#"
CSV_METADATA_SEPARATOR = "="
REQUIRED_CSV_METADATA = ("data_kind", "source_class", "source_note")
NORMALIZED_WEIGHT_ABS_TOL = 1.0e-9
ARCSEC_PER_RADIAN = 180.0 * 3600.0 / math.pi

# Field names describe the in-memory contract, not necessarily the units used
# by an input file. Every loader converts supported source units to these
# canonical units before constructing its public return object.
ESO_MEASUREMENT_UNITS = {
    "mjd": "day",
    "unix_time_median_ms": "ms",
    "seeing_arcsec_500nm": "arcsec",
    "r0_500_m": "m",
    "tau0_s": "s",
    "theta0_arcsec": "arcsec",
    "wind_speed_ms": "m/s",
    "turbulence_speed_ms": "m/s",
    "wind_dir_deg": "deg",
    "sample_count": "count",
}
LITERATURE_SUMMARY_UNITS = {
    "seeing_arcsec_500nm": "arcsec",
    "r0_500_m": "m",
    "outer_scale_L0_m": "m",
    "tau0_s": "s",
    "theta0_arcsec": "arcsec",
}
ATMOSPHERE_LAYER_UNITS = {
    "height_m": "m",
    "cn2_weight": "fraction",
    "wind_ms": "m/s",
    "wind_dir_deg": "deg",
}

_UNIT_SCALE_TO_CANONICAL = {
    "m": {
        "m": 1.0,
        "meter": 1.0,
        "metre": 1.0,
        "km": 1.0e3,
        "cm": 1.0e-2,
        "mm": 1.0e-3,
        "um": 1.0e-6,
        "nm": 1.0e-9,
        "angstrom": 1.0e-10,
    },
    "s": {
        "s": 1.0,
        "sec": 1.0,
        "second": 1.0,
        "ms": 1.0e-3,
        "us": 1.0e-6,
    },
    "ms": {
        "ms": 1.0,
        "millisecond": 1.0,
        "s": 1.0e3,
        "sec": 1.0e3,
        "second": 1.0e3,
    },
    "day": {
        "day": 1.0,
        "d": 1.0,
        "s": 1.0 / 86400.0,
        "sec": 1.0 / 86400.0,
    },
    "arcsec": {
        "arcsec": 1.0,
        "arcsecond": 1.0,
        "mas": 1.0e-3,
        "deg": 3600.0,
        "degree": 3600.0,
        "rad": ARCSEC_PER_RADIAN,
        "radian": ARCSEC_PER_RADIAN,
    },
    "deg": {
        "deg": 1.0,
        "degree": 1.0,
        "rad": 180.0 / math.pi,
        "radian": 180.0 / math.pi,
    },
    "m/s": {
        "m/s": 1.0,
        "meter/second": 1.0,
        "metre/second": 1.0,
        "km/h": 1.0 / 3.6,
        "km/s": 1.0e3,
    },
    "dimensionless": {
        "dimensionless": 1.0,
        "unitless": 1.0,
        "fraction": 1.0,
        "1": 1.0,
        "%": 1.0e-2,
        "percent": 1.0e-2,
    },
    "fraction": {
        "fraction": 1.0,
        "dimensionless": 1.0,
        "unitless": 1.0,
        "1": 1.0,
        "%": 1.0e-2,
        "percent": 1.0e-2,
    },
    "count": {
        "count": 1.0,
        "dimensionless": 1.0,
        "1": 1.0,
    },
    "mag": {
        "mag": 1.0,
        "magnitude": 1.0,
    },
}


class DataSourceError(ValueError):
    """Raised when a local data-source fixture is malformed or ambiguous."""


@dataclass(frozen=True)
class EsoAsmSnapshot:
    """Structured ESO ASM-style atmosphere snapshot.

    Args:
        measurements: Mapping of scalar atmosphere measurements.
        units: Unit string for each measurement key.
        provenance: Source metadata for the snapshot.

    Returns:
        Immutable atmosphere snapshot with explicit units.

    Raises:
        DataSourceError: If required fields, units, or finite scalar values are
            missing.

    Physics note:
        The object stores seeing/r0/tau0/theta0-style atmosphere descriptors.
        converts these descriptors into normalized phase-screen strength
        and layer weights; this loader only preserves values and units.
    """

    measurements: dict[str, float]
    units: dict[str, str]
    provenance: Provenance

    @property
    def source_class(self) -> str:
        return self.provenance.source_class


@dataclass(frozen=True)
class AtmosphereLayer:
    """One Cn2-weighted frozen-flow layer from a literature/profile fixture.

    Args:
        height_m: Layer altitude in metres.
        cn2_weight: Fractional layer turbulence strength.
        wind_ms: Wind speed in metres per second.
        wind_dir_deg: Wind direction in degrees.

    Returns:
        Immutable atmosphere-layer record.

    Raises:
        DataSourceError: If any scalar is non-finite or if ``cn2_weight`` is
            negative.

    Physics note:
        ``cn2_weight`` is dimensionless and should sum to one across layers
        before uses it to distribute the target r0 over frozen-flow layers.
    """

    height_m: float
    cn2_weight: float
    wind_ms: float
    wind_dir_deg: float

    def __post_init__(self) -> None:
        _require_finite("height_m", self.height_m)
        _require_finite("cn2_weight", self.cn2_weight)
        _require_finite("wind_ms", self.wind_ms)
        _require_finite("wind_dir_deg", self.wind_dir_deg)
        if self.cn2_weight < 0:
            raise DataSourceError("cn2_weight must be non-negative.")


@dataclass(frozen=True)
class LiteratureAtmosphereProfile:
    """Structured multi-layer atmosphere profile from a local JSON file.

    Args:
        name: Profile name.
        summary: Scalar seeing/r0/tau0/theta0 summary values.
        layers: Ordered atmosphere layers.
        units: Unit string for every summary and layer field.
        provenance: Source metadata for the profile.

    Returns:
        Immutable atmosphere-profile record.

    Raises:
        DataSourceError: If required units are missing, layer weights are not
            finite, or normalized layer weights do not sum to one.

    Physics note:
        This object separates data ingestion from physical phase generation.
        is responsible for turning the summary r0 and normalized Cn2
        weights into phase screens.
    """

    name: str
    summary: dict[str, float]
    layers: tuple[AtmosphereLayer, ...]
    units: dict[str, str]
    provenance: Provenance

    @property
    def source_class(self) -> str:
        return self.provenance.source_class


@dataclass(frozen=True)
class FilterCurve:
    """Bandpass/filter transmission curve loaded from a local CSV fixture.

    Args:
        filter_id: Stable filter identifier, such as ``2MASS.H``.
        wavelength_m: Wavelength samples in metres.
        transmission: Dimensionless throughput samples.
        units: Unit strings for wavelength and transmission.
        provenance: Source metadata for the filter curve.

    Returns:
        Immutable filter curve with monotonically increasing wavelengths.

    Raises:
        DataSourceError: If arrays have mismatched length, non-finite values,
            or non-increasing wavelengths.

    Physics note:
        can use this curve for band-aware PSF metrics. The loader does
        not integrate spectra; it only guarantees that wavelength and
        transmission samples are explicit and finite.
    """

    filter_id: str
    wavelength_m: tuple[float, ...]
    transmission: tuple[float, ...]
    units: dict[str, str]
    provenance: Provenance

    @property
    def source_class(self) -> str:
        return self.provenance.source_class


@dataclass(frozen=True)
class TargetPhotometry:
    """Guide-star/source photometry from a local Gaia/2MASS-style CSV file.

    Args:
        target_id: Local target identifier.
        ra_deg: Right ascension in degrees.
        dec_deg: Declination in degrees.
        magnitudes: Magnitudes keyed by catalog/filter column.
        units: Unit strings for coordinates and magnitudes.
        provenance: Source metadata for the table row.

    Returns:
        Immutable target-photometry record.

    Raises:
        DataSourceError: If coordinates or magnitudes are missing or non-finite.

    Physics note:
        can convert the magnitudes into a WFS photon budget. This loader
        only preserves catalog-like photometry and does not choose zero points.
    """

    target_id: str
    ra_deg: float
    dec_deg: float
    magnitudes: dict[str, float]
    units: dict[str, str]
    provenance: Provenance

    @property
    def source_class(self) -> str:
        return self.provenance.source_class


def load_eso_asm_snapshot(path: str | Path) -> EsoAsmSnapshot:
    """Load an ESO ASM-style atmosphere snapshot from local JSON.

    Args:
        path: JSON fixture or cache path with ``data_kind=eso_asm_snapshot``.

    Returns:
        An :class:`EsoAsmSnapshot` with scalar measurements, units, and
        provenance.

    Raises:
        DataSourceError: If the file has the wrong kind, missing fields, or
            non-finite scalar values.

    Physics note:
        The snapshot is an ingestion object for seeing/r0/tau0/theta0-style
        atmosphere metadata. Phase normalization is intentionally deferred to
        the atmosphere profile builder.
    """

    payload = _load_json_payload(path, expected_kind="eso_asm_snapshot")
    units = _require_mapping(payload, "units")
    measurements_raw = _require_mapping(payload, "measurements")
    parsed_measurements = {
        key: _as_finite_float(value, key)
        for key, value in measurements_raw.items()
    }
    measurements, canonical_units = _canonicalize_mapping(
        parsed_measurements,
        units,
        ESO_MEASUREMENT_UNITS,
        path,
    )
    return EsoAsmSnapshot(
        measurements=measurements,
        units=canonical_units,
        provenance=_provenance_from_mapping(payload),
    )


def load_literature_atmosphere_profile(path: str | Path) -> LiteratureAtmosphereProfile:
    """Load a multi-layer literature or literature-inspired atmosphere profile.

    Args:
        path: JSON fixture path with
            ``data_kind=literature_atmosphere_profile``.

    Returns:
        A :class:`LiteratureAtmosphereProfile` with normalized layer weights,
        units, and provenance.

    Raises:
        DataSourceError: If required fields are absent, non-finite, or if Cn2
            weights do not sum to one.

    Physics note:
        Layer weights represent fractional turbulence strength. They must sum
        to one so can distribute the target r0 without silently changing
        total turbulence strength.
    """

    payload = _load_json_payload(
        path,
        expected_kind="literature_atmosphere_profile",
    )
    units = _require_mapping(payload, "units")
    summary_raw = _require_mapping(payload, "summary")
    layers_raw = payload.get("layers")
    if not isinstance(layers_raw, list) or not layers_raw:
        raise DataSourceError(f"{path}: layers must be a non-empty list.")

    parsed_summary = {
        key: _as_finite_float(value, key)
        for key, value in summary_raw.items()
    }
    summary, canonical_summary_units = _canonicalize_mapping(
        parsed_summary,
        units,
        LITERATURE_SUMMARY_UNITS,
        path,
    )

    canonical_layers: list[AtmosphereLayer] = []
    for index, layer in enumerate(layers_raw):
        if not isinstance(layer, dict):
            raise DataSourceError(f"{path}: layer {index} must be an object.")
        parsed_layer = {
            key: _as_finite_float(layer.get(key), key)
            for key in ATMOSPHERE_LAYER_UNITS
        }
        converted_layer, _ = _canonicalize_mapping(
            parsed_layer,
            units,
            ATMOSPHERE_LAYER_UNITS,
            path,
        )
        canonical_layers.append(AtmosphereLayer(**converted_layer))
    layers = tuple(canonical_layers)
    total_weight = sum(layer.cn2_weight for layer in layers)
    if not math.isclose(total_weight, 1.0, rel_tol=0.0, abs_tol=NORMALIZED_WEIGHT_ABS_TOL):
        raise DataSourceError(
            f"{path}: Cn2 layer weights must sum to 1.0; got {total_weight:.12g}."
        )

    return LiteratureAtmosphereProfile(
        name=str(payload.get("name", Path(path).stem)),
        summary=summary,
        layers=layers,
        units={**canonical_summary_units, **ATMOSPHERE_LAYER_UNITS},
        provenance=_provenance_from_mapping(payload),
    )


def load_svo_filter_curve(path: str | Path) -> FilterCurve:
    """Load a local SVO-style filter transmission CSV.

    Args:
        path: CSV file with metadata comments and columns
            ``wavelength_m,transmission``.

    Returns:
        A :class:`FilterCurve` with explicit units and provenance.

    Raises:
        DataSourceError: If metadata is missing, values are non-finite, or
            wavelengths are not strictly increasing.

    Physics note:
        Wavelengths are stored in metres and transmissions are dimensionless.
        Later science-PSF code may integrate over this curve, but this loader
        performs only ingestion and validation.
    """

    metadata, rows = _read_commented_csv(path)
    _require_csv_kind(metadata, path, "svo_filter_curve")
    wavelength_unit = _require_metadata_unit(metadata, "wavelength_unit", path)
    transmission_unit = _require_metadata_unit(metadata, "transmission_unit", path)
    wavelengths = tuple(
        _convert_value_to_canonical(
            _as_finite_float(row["wavelength_m"], "wavelength_m"),
            wavelength_unit,
            "m",
            "wavelength_m",
            path,
        )
        for row in rows
    )
    transmissions = tuple(
        _convert_value_to_canonical(
            _as_finite_float(row["transmission"], "transmission"),
            transmission_unit,
            "dimensionless",
            "transmission",
            path,
        )
        for row in rows
    )
    _validate_equal_length("wavelength_m", wavelengths, "transmission", transmissions, path)
    _validate_strictly_increasing("wavelength_m", wavelengths, path)
    for value in transmissions:
        if value < 0:
            raise DataSourceError(f"{path}: transmission must be non-negative.")
    return FilterCurve(
        filter_id=metadata.get("filter_id", Path(path).stem),
        wavelength_m=wavelengths,
        transmission=transmissions,
        units={
            "wavelength_m": "m",
            "transmission": "dimensionless",
        },
        provenance=_provenance_from_mapping(metadata),
    )


def load_target_photometry(path: str | Path, target_id: str | None = None) -> TargetPhotometry:
    """Load one target row from a Gaia/2MASS-style photometry CSV.

    Args:
        path: CSV file with metadata comments and target photometry rows.
        target_id: Optional target identifier. If omitted, the file must
            contain exactly one row.

    Returns:
        A :class:`TargetPhotometry` record with coordinates, magnitudes, units,
        and provenance.

    Raises:
        DataSourceError: If the requested target is absent, ambiguous, or has
            non-finite coordinate/photometry values.

    Physics note:
        Magnitudes are source descriptors, not fluxes. must choose catalog
        zero points and throughput before converting these values into WFS
        photons per subaperture per frame.
    """

    metadata, rows = _read_commented_csv(path)
    _require_csv_kind(metadata, path, "target_photometry")
    if target_id is None:
        if len(rows) != 1:
            raise DataSourceError(
                f"{path}: target_id is required when a photometry file has "
                f"{len(rows)} rows."
            )
        row = rows[0]
    else:
        matches = [row for row in rows if row.get("target_id") == target_id]
        if not matches:
            raise DataSourceError(f"{path}: target_id={target_id!r} was not found.")
        if len(matches) > 1:
            raise DataSourceError(f"{path}: target_id={target_id!r} is duplicated.")
        row = matches[0]

    magnitude_columns = [
        key
        for key in row
        if key.endswith("_mag") and row.get(key, "").strip() != ""
    ]
    if not magnitude_columns:
        raise DataSourceError(f"{path}: no magnitude columns were populated.")

    ra_unit = _require_metadata_unit(metadata, "ra_unit", path)
    dec_unit = _require_metadata_unit(metadata, "dec_unit", path)
    magnitude_unit = _require_metadata_unit(metadata, "magnitude_unit", path)
    magnitudes = {
        key: _convert_value_to_canonical(
            _as_finite_float(row[key], key),
            magnitude_unit,
            "mag",
            key,
            path,
        )
        for key in magnitude_columns
    }
    units = {"ra_deg": "deg", "dec_deg": "deg"}
    units.update({key: "mag" for key in magnitudes})

    return TargetPhotometry(
        target_id=str(row["target_id"]),
        ra_deg=_convert_value_to_canonical(
            _as_finite_float(row["ra_deg"], "ra_deg"),
            ra_unit,
            "deg",
            "ra_deg",
            path,
        ),
        dec_deg=_convert_value_to_canonical(
            _as_finite_float(row["dec_deg"], "dec_deg"),
            dec_unit,
            "deg",
            "dec_deg",
            path,
        ),
        magnitudes=magnitudes,
        units=units,
        provenance=_provenance_from_mapping(metadata),
    )


def _load_json_payload(path: str | Path, expected_kind: str) -> dict[str, Any]:
    with open_text_resource(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise DataSourceError(f"{path}: top-level JSON value must be an object.")
    kind = payload.get("data_kind")
    if kind != expected_kind:
        raise DataSourceError(f"{path}: expected data_kind={expected_kind!r}, got {kind!r}.")
    return payload


def _read_commented_csv(path: str | Path) -> tuple[dict[str, str], list[dict[str, str]]]:
    metadata: dict[str, str] = {}
    data_lines: list[str] = []
    with open_text_resource(path, encoding="utf-8", newline="") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(CSV_COMMENT_PREFIX):
                body = stripped[len(CSV_COMMENT_PREFIX) :].strip()
                if CSV_METADATA_SEPARATOR in body:
                    key, value = body.split(CSV_METADATA_SEPARATOR, 1)
                    metadata[key.strip()] = value.strip()
                continue
            data_lines.append(line)
    missing = [key for key in REQUIRED_CSV_METADATA if key not in metadata]
    if missing:
        raise DataSourceError(f"{path}: missing CSV metadata fields {missing}.")
    if not data_lines:
        raise DataSourceError(f"{path}: CSV file has no table rows.")
    reader = csv.DictReader(data_lines)
    rows = list(reader)
    if not rows:
        raise DataSourceError(f"{path}: CSV table is empty.")
    return metadata, rows


def _require_csv_kind(metadata: dict[str, str], path: str | Path, expected_kind: str) -> None:
    kind = metadata.get("data_kind")
    if kind != expected_kind:
        raise DataSourceError(f"{path}: expected data_kind={expected_kind!r}, got {kind!r}.")


def _provenance_from_mapping(mapping: dict[str, Any]) -> Provenance:
    legacy_fields = dict(mapping)
    legacy_fields["source_class"] = str(mapping.get("source_class", ""))
    legacy_fields["source_note"] = str(mapping.get("source_note", ""))
    legacy_fields["source_id"] = _optional_str(mapping.get("source_id"))
    legacy_fields["url"] = _optional_str(mapping.get("url"))
    legacy_fields["access_time"] = _optional_str(mapping.get("access_time"))
    legacy_fields["fallback_used"] = _as_bool(mapping.get("fallback_used", False))
    try:
        return Provenance.from_legacy_fields(legacy_fields)
    except ValueError as exc:
        # ``DataSourceError`` remains the stable loader-boundary exception,
        # while the canonical provenance model stays independent of I/O.
        raise DataSourceError(str(exc)) from exc


def _optional_str(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def _require_mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise DataSourceError(f"JSON field {key!r} must be an object.")
    return value


def _as_finite_float(value: Any, field_name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise DataSourceError(f"{field_name} must be convertible to float; got {value!r}.") from exc
    if not math.isfinite(out):
        raise DataSourceError(f"{field_name} must be finite; got {out!r}.")
    return out


def _require_finite(field_name: str, value: float) -> None:
    if not math.isfinite(float(value)):
        raise DataSourceError(f"{field_name} must be finite; got {value!r}.")


def _canonicalize_mapping(
    values: dict[str, float],
    source_units: dict[str, Any],
    canonical_units: dict[str, str],
    path: str | Path,
) -> tuple[dict[str, float], dict[str, str]]:
    """Convert a scalar mapping to its loader's explicit unit contract."""

    unsupported_fields = sorted(set(values) - set(canonical_units))
    if unsupported_fields:
        raise DataSourceError(
            f"{path}: no canonical-unit contract for fields {unsupported_fields}."
        )

    converted: dict[str, float] = {}
    returned_units: dict[str, str] = {}
    for field, value in values.items():
        source_unit = str(source_units.get(field, "")).strip()
        if not source_unit:
            raise DataSourceError(f"{path}: missing unit entry for {field!r}.")
        canonical_unit = canonical_units[field]
        converted[field] = _convert_value_to_canonical(
            value,
            source_unit,
            canonical_unit,
            field,
            path,
        )
        returned_units[field] = canonical_unit
    return converted, returned_units


def _require_metadata_unit(
    metadata: dict[str, str],
    key: str,
    path: str | Path,
) -> str:
    unit = str(metadata.get(key, "")).strip()
    if not unit:
        raise DataSourceError(f"{path}: missing CSV unit metadata {key!r}.")
    return unit


def _convert_value_to_canonical(
    value: float,
    source_unit: str,
    canonical_unit: str,
    field: str,
    path: str | Path,
) -> float:
    source_key = _normalize_unit(source_unit)
    factors = _UNIT_SCALE_TO_CANONICAL.get(canonical_unit)
    if factors is None:  # Defensive guard for future schema edits.
        raise DataSourceError(
            f"{path}: internal error: unsupported canonical unit {canonical_unit!r}."
        )
    factor = factors.get(source_key)
    if factor is None:
        supported = ", ".join(sorted(factors))
        raise DataSourceError(
            f"{path}: unsupported unit {source_unit!r} for {field!r}; "
            f"expected a unit convertible to {canonical_unit!r} "
            f"(supported: {supported})."
        )
    converted = float(value) * factor
    _require_finite(field, converted)
    return converted


def _normalize_unit(unit: str) -> str:
    normalized = (
        str(unit)
        .strip()
        .lower()
        .replace("µ", "u")
        .replace("μ", "u")
        .replace("å", "angstrom")
    )
    normalized = "".join(normalized.split())
    aliases = {
        "meters": "meter",
        "metres": "metre",
        "seconds": "second",
        "milliseconds": "millisecond",
        "arcseconds": "arcsecond",
        "degrees": "degree",
        "radians": "radian",
        "meters/second": "meter/second",
        "metres/second": "metre/second",
        "m/s^-1": "m/s",
        "ms^-1": "m/s",
        "m*s^-1": "m/s",
    }
    return aliases.get(normalized, normalized)


def _validate_equal_length(
    name_a: str,
    values_a: tuple[float, ...],
    name_b: str,
    values_b: tuple[float, ...],
    path: str | Path,
) -> None:
    if len(values_a) != len(values_b):
        raise DataSourceError(
            f"{path}: {name_a} length {len(values_a)} != {name_b} length {len(values_b)}."
        )


def _validate_strictly_increasing(name: str, values: tuple[float, ...], path: str | Path) -> None:
    if len(values) < 2:
        raise DataSourceError(f"{path}: {name} must contain at least two samples.")
    for previous, current in zip(values[:-1], values[1:]):
        if current <= previous:
            raise DataSourceError(f"{path}: {name} must be strictly increasing.")


__all__ = (
    "ALLOWED_SOURCE_CLASSES",
    "AtmosphereLayer",
    "DataSourceError",
    "EsoAsmSnapshot",
    "FilterCurve",
    "LiteratureAtmosphereProfile",
    "Provenance",
    "TargetPhotometry",
    "load_eso_asm_snapshot",
    "load_literature_atmosphere_profile",
    "load_svo_filter_curve",
    "load_target_photometry",
)
