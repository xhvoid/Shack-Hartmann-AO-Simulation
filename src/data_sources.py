# Data-source loaders return structured objects with units and source_class provenance; no notebook-only parsing is required.

"""Data-source interfaces for the realistic 2 m SCAO demonstrator.

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


ALLOWED_SOURCE_CLASSES = frozenset(
    {
        "direct_public_data",
        "literature_derived",
        "synthetic_literature_inspired",
        "synthetic_assumed",
        "package_reference",
    }
)

CSV_COMMENT_PREFIX = "#"
CSV_METADATA_SEPARATOR = "="
REQUIRED_CSV_METADATA = ("data_kind", "source_class", "source_note")
NORMALIZED_WEIGHT_ABS_TOL = 1.0e-9


class DataSourceError(ValueError):
    """Raised when a local data-source fixture is malformed or ambiguous."""


@dataclass(frozen=True)
class Provenance:
    """Source metadata attached to every loaded data object.

    Args:
        source_class: Provenance class from the documented source-class taxonomy.
        source_note: Human-readable source description, citation, or fallback
            warning.
        source_id: Optional stable local identifier for the source.
        url: Optional public URL when the record came from public data.
        access_time: Optional access timestamp for downloaded public data.
        fallback_used: Whether this record is a local fallback rather than a
            fresh public-data query.

    Returns:
        Immutable provenance metadata.

    Raises:
        DataSourceError: If ``source_class`` is outside the permitted taxonomy
            or if the source note is empty.

    Physics note:
        Provenance is not a physical quantity, but it defines whether a later
        AO metric should be read as direct public data, literature-derived,
        package-computed, or synthetic.
    """

    source_class: str
    source_note: str
    source_id: str | None = None
    url: str | None = None
    access_time: str | None = None
    fallback_used: bool = False

    def __post_init__(self) -> None:
        if self.source_class not in ALLOWED_SOURCE_CLASSES:
            raise DataSourceError(
                f"Invalid source_class={self.source_class!r}; expected one of "
                f"{sorted(ALLOWED_SOURCE_CLASSES)}."
            )
        if not str(self.source_note).strip():
            raise DataSourceError("source_note must be a non-empty string.")


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
    measurements = {
        key: _as_finite_float(value, key)
        for key, value in measurements_raw.items()
    }
    _require_units(units, measurements.keys(), path)
    return EsoAsmSnapshot(
        measurements=measurements,
        units={key: str(units[key]) for key in measurements},
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

    summary = {
        key: _as_finite_float(value, key)
        for key, value in summary_raw.items()
    }
    _require_units(units, summary.keys(), path)

    layers = tuple(
        AtmosphereLayer(
            height_m=_as_finite_float(layer.get("height_m"), "height_m"),
            cn2_weight=_as_finite_float(layer.get("cn2_weight"), "cn2_weight"),
            wind_ms=_as_finite_float(layer.get("wind_ms"), "wind_ms"),
            wind_dir_deg=_as_finite_float(layer.get("wind_dir_deg"), "wind_dir_deg"),
        )
        for layer in layers_raw
    )
    _require_units(
        units,
        ("height_m", "cn2_weight", "wind_ms", "wind_dir_deg"),
        path,
    )
    total_weight = sum(layer.cn2_weight for layer in layers)
    if not math.isclose(total_weight, 1.0, rel_tol=0.0, abs_tol=NORMALIZED_WEIGHT_ABS_TOL):
        raise DataSourceError(
            f"{path}: Cn2 layer weights must sum to 1.0; got {total_weight:.12g}."
        )

    return LiteratureAtmosphereProfile(
        name=str(payload.get("name", Path(path).stem)),
        summary=summary,
        layers=layers,
        units={key: str(value) for key, value in units.items()},
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
    wavelengths = tuple(_as_finite_float(row["wavelength_m"], "wavelength_m") for row in rows)
    transmissions = tuple(_as_finite_float(row["transmission"], "transmission") for row in rows)
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
            "wavelength_m": metadata.get("wavelength_unit", "m"),
            "transmission": metadata.get("transmission_unit", "dimensionless"),
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

    magnitudes = {
        key: _as_finite_float(row[key], key)
        for key in magnitude_columns
    }
    units = {
        "ra_deg": metadata.get("ra_unit", "deg"),
        "dec_deg": metadata.get("dec_unit", "deg"),
    }
    units.update({key: metadata.get("magnitude_unit", "mag") for key in magnitudes})

    return TargetPhotometry(
        target_id=str(row["target_id"]),
        ra_deg=_as_finite_float(row["ra_deg"], "ra_deg"),
        dec_deg=_as_finite_float(row["dec_deg"], "dec_deg"),
        magnitudes=magnitudes,
        units=units,
        provenance=_provenance_from_mapping(metadata),
    )


def _load_json_payload(path: str | Path, expected_kind: str) -> dict[str, Any]:
    path = Path(path)
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise DataSourceError(f"{path}: top-level JSON value must be an object.")
    kind = payload.get("data_kind")
    if kind != expected_kind:
        raise DataSourceError(f"{path}: expected data_kind={expected_kind!r}, got {kind!r}.")
    return payload


def _read_commented_csv(path: str | Path) -> tuple[dict[str, str], list[dict[str, str]]]:
    path = Path(path)
    metadata: dict[str, str] = {}
    data_lines: list[str] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
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
    return Provenance(
        source_class=str(mapping.get("source_class", "")),
        source_note=str(mapping.get("source_note", "")),
        source_id=_optional_str(mapping.get("source_id")),
        url=_optional_str(mapping.get("url")),
        access_time=_optional_str(mapping.get("access_time")),
        fallback_used=_as_bool(mapping.get("fallback_used", False)),
    )


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


def _require_units(units: dict[str, Any], fields: Any, path: str | Path) -> None:
    missing = [field for field in fields if not str(units.get(field, "")).strip()]
    if missing:
        raise DataSourceError(f"{path}: missing unit entries for {missing}.")


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
