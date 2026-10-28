"""Deterministic artifact serialization for AO experiment results.

This module is the only layer that turns integration results into files.  The
experiment packages intentionally return ordinary in-memory objects; callers
choose an output directory and invoke the writers explicitly.

Schema version 2 preserves the historical fast-integration JSON and CSV bytes.
Schema version 3 adds governed metadata, CSV sidecars, and a content-addressed
manifest.  It never grants baseline authority implicitly: candidate and
accepted-baseline records require caller-supplied evidence.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
import csv
import json
import math
from pathlib import Path
import re
from typing import Any, Literal, Protocol, cast, runtime_checkable

import numpy as np

from ..core.provenance import Provenance
from .resources import open_text_resource


__all__ = (
    "ArtifactError",
    "ArtifactConfig",
    "SCENARIO_V2_HEADER",
    "VALIDATION_V2_HEADER",
    "RUNTIME_V2_HEADER",
    "SCHEMA_V3_TABLE_COLUMNS",
    "read_v2",
    "read_v3",
    "read_scenario_table",
    "read_validation_table",
    "read_runtime_table",
    "upgrade_v2_to_v3",
    "write_csv_rows",
    "write_json_record",
    "write_runtime_artifacts",
    "write_integration_artifacts",
    "validate_required_artifacts",
)


ArtifactKind = Literal[
    "run_result",
    "baseline_candidate",
    "accepted_regression_baseline",
]

FAST_REFERENCE_SCHEMA_NAME = "shwfs_ao.fast_reference_metrics"
SCENARIO_SIDECAR_SCHEMA_NAME = "shwfs_ao.scenario_table_sidecar"
VALIDATION_SIDECAR_SCHEMA_NAME = "shwfs_ao.validation_table_sidecar"
RUNTIME_SIDECAR_SCHEMA_NAME = "shwfs_ao.runtime_table_sidecar"
MANIFEST_SCHEMA_NAME = "shwfs_ao.artifact_manifest"

SCENARIO_V2_HEADER = (
    "scenario_name",
    "enabled_effects",
    "open_rms_nm",
    "closed_rms_nm",
    "closed_over_open_rms",
    "strehl_J",
    "strehl_H",
    "strehl_K",
    "open_strehl_H",
    "ee50_J",
    "ee50_H",
    "ee50_K",
    "ee80_J",
    "ee80_H",
    "ee80_K",
    "command_rms_nm",
    "command_peak_nm",
    "saturated_actuator_frac",
    "valid_centroid_frac",
    "source_class",
    "source_note",
    "config_hash",
)

VALIDATION_V2_HEADER = (
    "check_name",
    "passed",
    "metric_value",
    "tolerance",
    "message",
    "source_class",
    "source_note",
    "detail_strehl_peak",
    "detail_strehl_marechal",
    "detail_min_marechal_strehl",
    "detail_fwhm_min_lambda_over_d",
    "detail_fwhm_max_lambda_over_d",
    "detail_range_distance",
    "detail_ideal_strehl",
    "x_value",
    "x_unit",
    "metric_unit",
    "detail_max_relative_difference",
    "detail_n_rows",
)

RUNTIME_V2_HEADER = (
    "script",
    "run_started_utc",
    "run_finished_utc",
    "runtime_seconds",
    "runtime_minutes",
    "runtime_limit_minutes",
    "within_runtime_limit",
    "output_artifacts",
    "source_note",
)

SCHEMA_V3_TABLE_COLUMNS = (
    "artifact_schema_version",
    "artifact_kind",
    "backend",
    "system_profile",
)

_INTEGRATION_RUNTIME_V2_HEADER = (
    "workflow",
    "preset",
    "runtime_seconds",
    "runtime_band",
    "source_class",
    "config_hash",
)

_REFERENCE_V2_REQUIRED = (
    "schema_version",
    "workflow",
    "preset",
    "source_class",
    "source_note",
    "config_hash",
    "scenario_count",
    "scenario_names",
    "reference_scenario",
    "open_rms_nm",
    "closed_rms_nm",
    "h_strehl",
    "valid_centroid_fraction",
    "kept_modes",
    "runtime_band",
    "runtime_note",
    "validation_pass_count",
    "validation_check_count",
    "tolerances",
)

_TOLERANCE_KEYS = (
    "closed_rms_nm_abs",
    "h_strehl_abs",
    "kept_modes_abs",
    "open_rms_nm_abs",
    "runtime_s_reference_max",
    "valid_centroid_fraction_abs",
)

_TOLERANCE_UNIT_KIND = {
    "closed_rms_nm_abs": ("nm_opd_rms", "absolute", True),
    "h_strehl_abs": ("dimensionless", "absolute", True),
    "kept_modes_abs": ("count", "absolute", True),
    "open_rms_nm_abs": ("nm_opd_rms", "absolute", True),
    "runtime_s_reference_max": ("s", "reference_upper_bound", False),
    "valid_centroid_fraction_abs": ("dimensionless", "absolute", True),
}

_COMPONENT_HASH_KEYS = (
    "geometry",
    "detector",
    "wfs_calibration",
    "dm",
    "interaction_matrix",
    "command_projector",
    "controller",
    "science_sampling",
)

_LAYOUT_HASH_KEYS = ("measurement_rows", "actuator_commands")
_CONVENTION_KEYS = (
    "wavefront_unit",
    "command_unit",
    "residual_definition",
    "measurement_unit",
)
_REPRODUCIBILITY_KEYS = (
    "root_seed",
    "rng_derivation_scheme_id",
    "random_stream_ids",
    "python_version",
    "numpy_version",
    "shwfs_ao_version",
    "backend_version",
    "constraints_sha256",
    "generator_version",
    "source_commit",
    "source_tree_clean",
    "source_patch_sha256",
    "generated_at_utc",
)

_SAFE_PREFIX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SHA256 = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")


class ArtifactError(ValueError):
    """Raised when an artifact request violates its serialization contract."""


@runtime_checkable
class IntegrationArtifactResult(Protocol):
    """Structural input accepted by :func:`write_integration_artifacts`."""

    mode: str
    scenario_results: Sequence[object]
    validation_results: Sequence[object]
    reference_metrics: Mapping[str, Any]
    runtime_s: float
    source_class: str
    config_hash: str


@dataclass(frozen=True)
class ArtifactConfig:
    """Caller-owned output policy for one integration result.

    Version 2 writes the frozen compatibility artifacts.  Version 3 requires
    every scientific and reproducibility mapping below; those values are not
    recoverable safely from a generic result object.
    """

    output_dir: Path | str
    reference_metrics_path: Path | str | None = None
    prefix: str | None = None
    write_figures: bool = True
    write_reference_metrics: bool = True
    write_runtime: bool = False
    runtime_formats: tuple[str, ...] = ("json", "csv")
    schema_version: int = 2
    artifact_kind: ArtifactKind = "run_result"
    backend: str | None = None
    system_profile: str | None = None
    provenance: Provenance | Mapping[str, Any] | None = None
    component_hashes: Mapping[str, str] | None = None
    layout_hashes: Mapping[str, str] | None = None
    conventions: Mapping[str, str] | None = None
    reproducibility: Mapping[str, Any] | None = None
    tolerance_metadata: Mapping[str, Mapping[str, Any]] | None = None
    candidate_metadata: Mapping[str, Any] | None = None
    diff_metadata: Mapping[str, Any] | None = None
    acceptance: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_dir", Path(self.output_dir))
        if self.reference_metrics_path is not None:
            object.__setattr__(
                self,
                "reference_metrics_path",
                Path(self.reference_metrics_path),
            )
        if self.prefix is not None:
            _validate_prefix(self.prefix)
        if type(self.write_figures) is not bool:
            raise ArtifactError("write_figures must be a bool.")
        if type(self.write_reference_metrics) is not bool:
            raise ArtifactError("write_reference_metrics must be a bool.")
        if type(self.write_runtime) is not bool:
            raise ArtifactError("write_runtime must be a bool.")
        if self.schema_version not in {2, 3}:
            raise ArtifactError("schema_version must be 2 or 3.")
        if self.artifact_kind not in {
            "run_result",
            "baseline_candidate",
            "accepted_regression_baseline",
        }:
            raise ArtifactError(f"Unsupported artifact_kind={self.artifact_kind!r}.")
        formats = _validate_runtime_formats(self.runtime_formats)
        object.__setattr__(self, "runtime_formats", formats)
        if self.schema_version == 2 and self.artifact_kind != "run_result":
            raise ArtifactError("Schema-v2 output cannot claim candidate or accepted-baseline authority.")


def write_csv_rows(
    path: Path | str,
    rows: Iterable[Mapping[str, Any]],
    *,
    fieldnames: Sequence[str] | None = None,
) -> Path:
    """Write non-empty mapping rows with deterministic header order."""

    destination = Path(path)
    materialized = tuple(dict(row) for row in rows)
    if not materialized:
        raise ArtifactError(f"Cannot write empty CSV table: {destination}.")
    header = (
        tuple(str(name) for name in fieldnames)
        if fieldnames is not None
        else _ordered_header(materialized)
    )
    if not header or len(set(header)) != len(header):
        raise ArtifactError("CSV fieldnames must be non-empty and unique.")
    unknown = sorted({str(key) for row in materialized for key in row}.difference(header))
    if unknown:
        raise ArtifactError(f"CSV rows contain fields absent from fieldnames: {unknown}.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(header),
            lineterminator="\n",
            extrasaction="raise",
        )
        writer.writeheader()
        writer.writerows(materialized)
    return destination


def write_json_record(path: Path | str, record: Mapping[str, Any]) -> Path:
    """Write one JSON mapping with the frozen sorted/indented representation."""

    destination = Path(path)
    payload = _json_mapping(record, label="JSON record")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return destination


def write_runtime_artifacts(
    record: Mapping[str, Any],
    *,
    output_dir: Path | str,
    prefix: str,
    formats: Sequence[str] = ("json", "csv"),
    fieldnames: Sequence[str] | None = None,
) -> tuple[Path, ...]:
    """Write a reusable runtime record as deterministic JSON and/or CSV.

    The record is not augmented with timestamps or host details: callers own
    those observations.  Passing the historical public-data runtime fields
    therefore remains byte/column compatible.
    """

    _validate_prefix(prefix)
    selected = _validate_runtime_formats(formats)
    directory = Path(output_dir)
    payload = _json_mapping(record, label="runtime record")
    written: list[Path] = []
    for format_name in selected:
        path = directory / f"{prefix}_runtime.{format_name}"
        if format_name == "json":
            written.append(write_json_record(path, payload))
        else:
            written.append(write_csv_rows(path, (payload,), fieldnames=fieldnames))
    return tuple(written)


def write_integration_artifacts(
    result: IntegrationArtifactResult,
    artifact_config: ArtifactConfig,
) -> tuple[Path, ...]:
    """Serialize one completed integration result into caller-owned paths.

    Version-2 return order is the historical order: scenario CSV, scenario
    figure (when enabled), validation CSV, validation figure (when enabled),
    reference JSON (when enabled).  Additional version-3 files follow that
    prefix in deterministic runtime/sidecar/manifest order.
    """

    _validate_integration_result(result)
    config = artifact_config
    prefix = str(result.mode) if config.prefix is None else config.prefix
    _validate_prefix(prefix)
    output_dir = Path(config.output_dir)
    metadata = _v3_metadata(config) if config.schema_version == 3 else None

    scenario_rows = _scenario_rows(result.scenario_results)
    validation_rows = _validation_rows(result.validation_results)
    scenario_header = _ordered_header(scenario_rows)
    validation_header = _ordered_header(validation_rows)
    _validate_table_header(scenario_header, SCENARIO_V2_HEADER, "scenario")
    _validate_table_header(validation_header, VALIDATION_V2_HEADER, "validation")
    if metadata is not None:
        scenario_rows = _append_v3_table_metadata(scenario_rows, metadata)
        validation_rows = _append_v3_table_metadata(validation_rows, metadata)
        scenario_header = _ordered_header(scenario_rows)
        validation_header = _ordered_header(validation_rows)

    scenario_csv = output_dir / f"{prefix}_error_budget.csv"
    validation_csv = output_dir / f"{prefix}_validation.csv"
    scenario_png = output_dir / f"{prefix}_error_budget.png"
    validation_png = output_dir / f"{prefix}_validation.png"
    reference_path = _reference_path(config, prefix)

    reference_payload: dict[str, Any] | None = None
    if config.write_reference_metrics:
        reference_payload = (
            read_v2(result.reference_metrics)
            if config.schema_version == 2
            else _upgrade_for_config(result.reference_metrics, config)
        )

    runtime_record: dict[str, Any] | None = None
    if config.write_runtime:
        runtime_record = _integration_runtime_record(result)
        if metadata is not None:
            runtime_record.update(_v3_table_columns(metadata))

    destinations = [scenario_csv, validation_csv]
    if config.write_figures:
        destinations.extend((scenario_png, validation_png))
    if reference_payload is not None:
        destinations.append(reference_path)
    if runtime_record is not None:
        destinations.extend(
            output_dir / f"{prefix}_runtime.{format_name}"
            for format_name in config.runtime_formats
        )
    if metadata is not None:
        destinations.extend(
            (
                scenario_csv.with_suffix(".sidecar.json"),
                validation_csv.with_suffix(".sidecar.json"),
                output_dir / f"{prefix}_artifact_manifest.json",
            )
        )
        if runtime_record is not None and "csv" in config.runtime_formats:
            destinations.append((output_dir / f"{prefix}_runtime.csv").with_suffix(".sidecar.json"))
    _preflight_destinations(destinations)
    output_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    write_csv_rows(scenario_csv, scenario_rows, fieldnames=scenario_header)
    written.append(scenario_csv)
    if config.write_figures:
        _plot_scenario_summary(scenario_png, scenario_rows)
        written.append(scenario_png)
    write_csv_rows(validation_csv, validation_rows, fieldnames=validation_header)
    written.append(validation_csv)
    if config.write_figures:
        _plot_validation_summary(validation_png, result.validation_results)
        written.append(validation_png)

    if reference_payload is not None:
        write_json_record(reference_path, reference_payload)
        written.append(reference_path)

    runtime_paths: tuple[Path, ...] = ()
    if runtime_record is not None:
        runtime_paths = write_runtime_artifacts(
            runtime_record,
            output_dir=output_dir,
            prefix=prefix,
            formats=config.runtime_formats,
        )
        written.extend(runtime_paths)

    if metadata is not None:
        sidecars: list[Path] = []
        sidecars.append(
            _write_table_sidecar(
                scenario_csv,
                scenario_rows,
                schema_name=SCENARIO_SIDECAR_SCHEMA_NAME,
                order_key="scenario_name",
                field_units=_scenario_field_units(scenario_header),
                metadata=metadata,
            )
        )
        sidecars.append(
            _write_table_sidecar(
                validation_csv,
                validation_rows,
                schema_name=VALIDATION_SIDECAR_SCHEMA_NAME,
                order_key="check_name",
                field_units=_validation_field_units(validation_header),
                metadata=metadata,
            )
        )
        for runtime_path in runtime_paths:
            if runtime_path.suffix == ".csv" and runtime_record is not None:
                sidecars.append(
                    _write_table_sidecar(
                        runtime_path,
                        (runtime_record,),
                        schema_name=RUNTIME_SIDECAR_SCHEMA_NAME,
                        order_key="workflow",
                        field_units=_runtime_field_units(tuple(runtime_record)),
                        metadata=metadata,
                    )
                )
        written.extend(sidecars)
        manifest = _write_manifest(
            output_dir / f"{prefix}_artifact_manifest.json",
            written,
            reference_path=reference_path if reference_payload is not None else None,
            metadata=metadata,
        )
        written.append(manifest)

    return validate_required_artifacts(written, config, prefix=prefix)


def validate_required_artifacts(
    paths: Sequence[Path | str],
    config: ArtifactConfig,
    *,
    prefix: str | None = None,
) -> tuple[Path, ...]:
    """Validate presence, uniqueness, and non-empty content for one write set."""

    actual = tuple(Path(path) for path in paths)
    names = [path.name for path in actual]
    if len(names) != len(set(names)):
        raise ArtifactError(f"Artifact filenames must be unique; got {names}.")
    chosen_prefix = prefix or config.prefix
    if chosen_prefix is None:
        raise ArtifactError("prefix is required when validating artifacts independently.")
    _validate_prefix(chosen_prefix)

    expected = {
        f"{chosen_prefix}_error_budget.csv",
        f"{chosen_prefix}_validation.csv",
    }
    if config.write_figures:
        expected.update(
            {
                f"{chosen_prefix}_error_budget.png",
                f"{chosen_prefix}_validation.png",
            }
        )
    if config.write_reference_metrics:
        expected.add(_reference_path(config, chosen_prefix).name)
    if config.write_runtime:
        expected.update(f"{chosen_prefix}_runtime.{item}" for item in config.runtime_formats)
    if config.schema_version == 3:
        expected.update(
            {
                f"{chosen_prefix}_error_budget.sidecar.json",
                f"{chosen_prefix}_validation.sidecar.json",
                f"{chosen_prefix}_artifact_manifest.json",
            }
        )
        if config.write_runtime and "csv" in config.runtime_formats:
            expected.add(f"{chosen_prefix}_runtime.sidecar.json")
    missing = sorted(expected.difference(names))
    if missing:
        raise ArtifactError(f"Missing required artifacts: {missing}.")
    for path in actual:
        if not path.is_file() or path.stat().st_size <= 0:
            raise ArtifactError(f"Required artifact is absent or empty: {path}.")
    return actual


def read_v2(source: Path | str | Mapping[str, Any]) -> dict[str, Any]:
    """Read and validate one frozen schema-v2 reference-metrics record."""

    payload = _read_record(source)
    if payload.get("schema_version") != 2:
        raise ArtifactError("Schema-v2 reference metrics must have schema_version=2.")
    if "schema_name" in payload and payload["schema_name"] != FAST_REFERENCE_SCHEMA_NAME:
        raise ArtifactError(
            f"schema_name must be {FAST_REFERENCE_SCHEMA_NAME!r} when present."
        )
    missing = [key for key in _REFERENCE_V2_REQUIRED if key not in payload]
    if missing:
        raise ArtifactError(f"Schema-v2 reference metrics missing fields: {missing}.")
    _validate_reference_common(payload)
    return payload


def read_v3(source: Path | str | Mapping[str, Any]) -> dict[str, Any]:
    """Read and validate one schema-v3 reference-metrics record."""

    payload = _read_record(source)
    if payload.get("schema_name") != FAST_REFERENCE_SCHEMA_NAME:
        raise ArtifactError(f"schema_name must be {FAST_REFERENCE_SCHEMA_NAME!r}.")
    if payload.get("schema_version") != 3:
        raise ArtifactError("Schema-v3 reference metrics must have schema_version=3.")
    missing = [key for key in _REFERENCE_V2_REQUIRED if key not in payload]
    missing.extend(
        key
        for key in (
            "artifact_kind",
            "backend",
            "system_profile",
            "provenance",
            "component_hashes",
            "layout_hashes",
            "conventions",
            "reproducibility",
            "tolerance_metadata",
        )
        if key not in payload
    )
    if missing:
        raise ArtifactError(f"Schema-v3 reference metrics missing fields: {missing}.")
    _validate_reference_common(payload)
    _validate_v3_record(payload)
    return payload


def read_scenario_table(path: Path | str) -> tuple[dict[str, str], ...]:
    """Read a scenario CSV with an explicitly supported v2 or additive-v3 header."""

    return _read_csv_table(
        path,
        allowed_headers=(SCENARIO_V2_HEADER, SCENARIO_V2_HEADER + SCHEMA_V3_TABLE_COLUMNS),
        label="scenario",
    )


def read_validation_table(path: Path | str) -> tuple[dict[str, str], ...]:
    """Read a validation CSV with an explicitly supported v2 or additive-v3 header."""

    return _read_csv_table(
        path,
        allowed_headers=(VALIDATION_V2_HEADER, VALIDATION_V2_HEADER + SCHEMA_V3_TABLE_COLUMNS),
        label="validation",
    )


def read_runtime_table(path: Path | str) -> tuple[dict[str, str], ...]:
    """Read a historical public-data or integration runtime CSV explicitly."""

    return _read_csv_table(
        path,
        allowed_headers=(
            RUNTIME_V2_HEADER,
            RUNTIME_V2_HEADER + SCHEMA_V3_TABLE_COLUMNS,
            _INTEGRATION_RUNTIME_V2_HEADER,
            _INTEGRATION_RUNTIME_V2_HEADER + SCHEMA_V3_TABLE_COLUMNS,
        ),
        label="runtime",
    )


def upgrade_v2_to_v3(
    source: Path | str | Mapping[str, Any],
    *,
    artifact_kind: ArtifactKind,
    backend: str,
    system_profile: str,
    provenance: Provenance | Mapping[str, Any],
    component_hashes: Mapping[str, str],
    layout_hashes: Mapping[str, str],
    conventions: Mapping[str, str],
    reproducibility: Mapping[str, Any],
    tolerance_metadata: Mapping[str, Mapping[str, Any]],
    candidate_metadata: Mapping[str, Any] | None = None,
    diff_metadata: Mapping[str, Any] | None = None,
    acceptance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Upgrade a v2 record without inventing non-inferable metadata.

    Every v2 value except the enclosing ``schema_version`` is retained exactly,
    including the legacy bare-hex ``config_hash``.  Conflicting pre-existing
    schema-v3 fields are rejected.
    """

    v2 = read_v2(source)
    additions = {
        "schema_name": FAST_REFERENCE_SCHEMA_NAME,
        "artifact_kind": artifact_kind,
        "backend": _nonempty_text(backend, "backend"),
        "system_profile": _nonempty_text(system_profile, "system_profile"),
        "provenance": _provenance_record(provenance),
        "component_hashes": _json_mapping(component_hashes, label="component_hashes"),
        "layout_hashes": _json_mapping(layout_hashes, label="layout_hashes"),
        "conventions": _json_mapping(conventions, label="conventions"),
        "reproducibility": _json_mapping(reproducibility, label="reproducibility"),
        "tolerance_metadata": _json_mapping(
            tolerance_metadata,
            label="tolerance_metadata",
        ),
    }
    if candidate_metadata is not None:
        additions["candidate"] = _json_mapping(candidate_metadata, label="candidate_metadata")
    if diff_metadata is not None:
        additions["diff"] = _json_mapping(diff_metadata, label="diff_metadata")
    if acceptance is not None:
        additions["acceptance"] = _json_mapping(acceptance, label="acceptance")

    for key, value in additions.items():
        if key in v2 and v2[key] != value:
            raise ArtifactError(f"Schema-v2 input conflicts with caller-supplied {key!r} metadata.")

    upgraded = dict(v2)
    upgraded["schema_name"] = FAST_REFERENCE_SCHEMA_NAME
    upgraded["schema_version"] = 3
    for key, value in additions.items():
        upgraded[key] = value
    validated = read_v3(upgraded)
    for key, value in v2.items():
        if key != "schema_version" and validated[key] != value:
            raise ArtifactError(f"Upgrade changed schema-v2 field {key!r}.")
    return validated


def _upgrade_for_config(
    source: Mapping[str, Any],
    config: ArtifactConfig,
) -> dict[str, Any]:
    metadata = _v3_metadata(config)
    return upgrade_v2_to_v3(
        source,
        artifact_kind=config.artifact_kind,
        backend=cast(str, config.backend),
        system_profile=cast(str, config.system_profile),
        provenance=cast(Provenance | Mapping[str, Any], config.provenance),
        component_hashes=cast(Mapping[str, str], config.component_hashes),
        layout_hashes=cast(Mapping[str, str], config.layout_hashes),
        conventions=cast(Mapping[str, str], config.conventions),
        reproducibility=cast(Mapping[str, Any], config.reproducibility),
        tolerance_metadata=cast(
            Mapping[str, Mapping[str, Any]],
            config.tolerance_metadata,
        ),
        candidate_metadata=cast(Mapping[str, Any] | None, metadata.get("candidate")),
        diff_metadata=cast(Mapping[str, Any] | None, metadata.get("diff")),
        acceptance=cast(Mapping[str, Any] | None, metadata.get("acceptance")),
    )


def _v3_metadata(config: ArtifactConfig) -> dict[str, Any]:
    required = {
        "backend": config.backend,
        "system_profile": config.system_profile,
        "provenance": config.provenance,
        "component_hashes": config.component_hashes,
        "layout_hashes": config.layout_hashes,
        "conventions": config.conventions,
        "reproducibility": config.reproducibility,
        "tolerance_metadata": config.tolerance_metadata,
    }
    missing = [key for key, value in required.items() if value is None]
    if missing:
        raise ArtifactError(f"Schema-v3 output requires caller-supplied metadata: {missing}.")
    metadata: dict[str, Any] = {
        "artifact_kind": config.artifact_kind,
        "backend": config.backend,
        "system_profile": config.system_profile,
        "provenance": _provenance_record(
            cast(Provenance | Mapping[str, Any], config.provenance)
        ),
        "component_hashes": _json_mapping(
            cast(Mapping[str, Any], config.component_hashes),
            label="component_hashes",
        ),
        "layout_hashes": _json_mapping(
            cast(Mapping[str, Any], config.layout_hashes),
            label="layout_hashes",
        ),
        "conventions": _json_mapping(
            cast(Mapping[str, Any], config.conventions),
            label="conventions",
        ),
        "reproducibility": _json_mapping(
            cast(Mapping[str, Any], config.reproducibility),
            label="reproducibility",
        ),
        "tolerance_metadata": _json_mapping(
            cast(Mapping[str, Any], config.tolerance_metadata),
            label="tolerance_metadata",
        ),
    }
    if config.candidate_metadata is not None:
        metadata["candidate"] = _json_mapping(config.candidate_metadata, label="candidate_metadata")
    if config.diff_metadata is not None:
        metadata["diff"] = _json_mapping(config.diff_metadata, label="diff_metadata")
    if config.acceptance is not None:
        metadata["acceptance"] = _json_mapping(config.acceptance, label="acceptance")
    probe = dict(_minimal_reference_probe())
    probe.update(metadata)
    probe["source_class"] = metadata["provenance"]["source_class"]
    probe["source_note"] = metadata["provenance"]["note"]
    probe["schema_name"] = FAST_REFERENCE_SCHEMA_NAME
    probe["schema_version"] = 3
    _validate_v3_record(probe)
    return metadata


def _validate_v3_record(payload: Mapping[str, Any]) -> None:
    kind = payload.get("artifact_kind")
    if kind not in {"run_result", "baseline_candidate", "accepted_regression_baseline"}:
        raise ArtifactError(f"Unsupported artifact_kind={kind!r}.")
    provenance = _provenance_record(cast(Mapping[str, Any], payload["provenance"]))
    if payload.get("source_class") != provenance["source_class"]:
        raise ArtifactError("source_class conflicts with provenance.source_class.")
    if payload.get("source_note") != provenance["note"]:
        raise ArtifactError("source_note conflicts with provenance.note.")

    _require_key_set(payload["component_hashes"], _COMPONENT_HASH_KEYS, "component_hashes", hash_values=True)
    _require_key_set(payload["layout_hashes"], _LAYOUT_HASH_KEYS, "layout_hashes", hash_values=True)
    _require_key_set(payload["conventions"], _CONVENTION_KEYS, "conventions")
    reproducibility = _validate_reproducibility(payload["reproducibility"])

    tolerances = cast(Mapping[str, Any], payload["tolerances"])
    metadata = _require_key_set(
        payload["tolerance_metadata"],
        tuple(tolerances),
        "tolerance_metadata",
        exact=True,
    )
    for key, record in metadata.items():
        if not isinstance(record, Mapping):
            raise ArtifactError(f"tolerance_metadata[{key!r}] must be a mapping.")
        for required in ("unit", "kind", "enforced", "rationale"):
            if required not in record:
                raise ArtifactError(f"tolerance_metadata[{key!r}] missing {required!r}.")
        if type(record["enforced"]) is not bool:
            raise ArtifactError(f"tolerance_metadata[{key!r}].enforced must be a bool.")
        expected = _TOLERANCE_UNIT_KIND[key]
        actual = (record["unit"], record["kind"], record["enforced"])
        if actual != expected:
            raise ArtifactError(
                f"tolerance_metadata[{key!r}] unit/kind/enforced must be {expected}; "
                f"got {actual}."
            )
        if not isinstance(record["rationale"], str) or not record["rationale"].strip():
            raise ArtifactError(f"tolerance_metadata[{key!r}].rationale must be non-empty.")

    _validate_authority_metadata(payload, reproducibility)


def _validate_reproducibility(value: object) -> dict[str, Any]:
    reproducibility = _require_key_set(
        value,
        _REPRODUCIBILITY_KEYS,
        "reproducibility",
    )
    _require_hash(reproducibility["constraints_sha256"], "constraints_sha256")
    patch = reproducibility["source_patch_sha256"]
    if patch is not None:
        _require_hash(patch, "source_patch_sha256")
    if type(reproducibility["root_seed"]) is not int:
        raise ArtifactError("reproducibility.root_seed must be an integer.")
    if reproducibility["source_tree_clean"] is not None and type(
        reproducibility["source_tree_clean"]
    ) is not bool:
        raise ArtifactError("reproducibility.source_tree_clean must be a bool or None.")
    if not isinstance(reproducibility["random_stream_ids"], Mapping):
        raise ArtifactError("reproducibility.random_stream_ids must be a mapping.")
    for key in (
        "rng_derivation_scheme_id",
        "python_version",
        "numpy_version",
        "shwfs_ao_version",
        "backend_version",
        "generator_version",
        "generated_at_utc",
    ):
        _nonempty_text(reproducibility[key], f"reproducibility.{key}")
    if not str(reproducibility["generated_at_utc"]).endswith("Z"):
        raise ArtifactError("reproducibility.generated_at_utc must be an explicit UTC timestamp ending in 'Z'.")
    source_commit = reproducibility["source_commit"]
    if source_commit is not None and (
        not isinstance(source_commit, str) or not source_commit.strip()
    ):
        raise ArtifactError("reproducibility.source_commit must be non-empty or None.")
    return reproducibility


def _validate_authority_metadata(
    payload: Mapping[str, Any],
    reproducibility: Mapping[str, Any],
) -> None:
    kind = payload.get("artifact_kind")
    if kind not in {"run_result", "baseline_candidate", "accepted_regression_baseline"}:
        raise ArtifactError(f"Unsupported artifact_kind={kind!r}.")
    has_candidate = "candidate" in payload
    has_diff = "diff" in payload
    has_acceptance = "acceptance" in payload
    if kind == "run_result":
        if has_candidate or has_diff or has_acceptance:
            raise ArtifactError("run_result forbids candidate, diff, and acceptance metadata.")
    elif kind == "baseline_candidate":
        if not has_candidate or not has_diff or has_acceptance:
            raise ArtifactError("baseline_candidate requires candidate and diff metadata and forbids acceptance.")
        for key in ("candidate", "diff"):
            if not isinstance(payload[key], Mapping) or not payload[key]:
                raise ArtifactError(f"baseline_candidate {key} metadata must be a non-empty mapping.")
        _validate_source_evidence(reproducibility)
    else:
        if has_candidate or has_diff or not has_acceptance:
            raise ArtifactError("accepted_regression_baseline requires acceptance and forbids candidate/diff metadata.")
        acceptance = payload["acceptance"]
        if not isinstance(acceptance, Mapping):
            raise ArtifactError("acceptance must be a mapping.")
        for key in ("reason", "review_reference"):
            if key not in acceptance or not str(acceptance[key]).strip():
                raise ArtifactError(f"acceptance.{key} must be non-empty.")
        _validate_source_evidence(reproducibility)


def _validate_source_evidence(reproducibility: Mapping[str, Any]) -> None:
    if not isinstance(reproducibility.get("source_commit"), str) or not str(
        reproducibility["source_commit"]
    ).strip():
        raise ArtifactError("Candidate/baseline source_commit must be non-empty.")
    if reproducibility.get("source_patch_sha256") is None:
        raise ArtifactError("Candidate/baseline source_patch_sha256 evidence is required.")
    if type(reproducibility.get("source_tree_clean")) is not bool:
        raise ArtifactError("Candidate/baseline source_tree_clean must be a bool.")


def _validate_reference_common(payload: Mapping[str, Any]) -> None:
    for key in ("open_rms_nm", "closed_rms_nm", "h_strehl", "valid_centroid_fraction"):
        _finite(payload[key], key)
    if type(payload["kept_modes"]) is not int or payload["kept_modes"] < 1:
        raise ArtifactError("kept_modes must be an integer >= 1.")
    if not isinstance(payload["scenario_names"], list):
        raise ArtifactError("scenario_names must be a JSON list.")
    if not payload["scenario_names"] or any(
        not isinstance(name, str) or not name.strip() for name in payload["scenario_names"]
    ):
        raise ArtifactError("scenario_names must contain non-empty strings.")
    if type(payload["scenario_count"]) is not int or payload["scenario_count"] != len(
        payload["scenario_names"]
    ):
        raise ArtifactError("scenario_count must equal len(scenario_names).")
    if type(payload["validation_pass_count"]) is not int or type(
        payload["validation_check_count"]
    ) is not int:
        raise ArtifactError("validation counts must be integers.")
    if payload["validation_pass_count"] < 0 or payload["validation_check_count"] < 0:
        raise ArtifactError("validation counts must be non-negative.")
    if payload["validation_pass_count"] > payload["validation_check_count"]:
        raise ArtifactError("validation_pass_count cannot exceed validation_check_count.")
    if not _SHA256.fullmatch(str(payload["config_hash"])):
        raise ArtifactError("config_hash must be a SHA-256 digest, with an optional sha256: prefix.")
    tolerances = payload["tolerances"]
    if not isinstance(tolerances, Mapping):
        raise ArtifactError("tolerances must be a mapping.")
    if set(tolerances) != set(_TOLERANCE_KEYS):
        raise ArtifactError(f"tolerances keys must exactly match {list(_TOLERANCE_KEYS)}.")
    for key, value in tolerances.items():
        _finite(value, f"tolerances.{key}")
        if float(value) < 0.0:
            raise ArtifactError(f"tolerances.{key} must be non-negative.")


def _write_table_sidecar(
    csv_path: Path,
    rows: Sequence[Mapping[str, Any]],
    *,
    schema_name: str,
    order_key: str,
    field_units: Mapping[str, str],
    metadata: Mapping[str, Any],
) -> Path:
    header = _ordered_header(rows)
    if order_key not in header:
        raise ArtifactError(f"Table order key {order_key!r} is absent from {csv_path.name}.")
    payload: dict[str, Any] = {
        "schema_name": schema_name,
        "schema_version": 3,
        "artifact_kind": metadata["artifact_kind"],
        "csv_filename": csv_path.name,
        "csv_sha256": _content_hash(csv_path),
        "header": list(header),
        "row_count": len(rows),
        "row_order_key": order_key,
        "row_order": [str(row[order_key]) for row in rows],
        "field_units": dict(field_units),
        "backend": metadata["backend"],
        "system_profile": metadata["system_profile"],
        "component_hashes": metadata["component_hashes"],
        "layout_hashes": metadata["layout_hashes"],
        "provenance": metadata["provenance"],
        "reproducibility": metadata["reproducibility"],
    }
    for key in ("candidate", "diff", "acceptance"):
        if key in metadata:
            payload[key] = metadata[key]
    sidecar = csv_path.with_suffix(".sidecar.json")
    _validate_sidecar(payload, csv_path)
    write_json_record(sidecar, payload)
    return sidecar


def _validate_sidecar(payload: Mapping[str, Any], csv_path: Path) -> None:
    expected_schema = {
        "_error_budget.csv": SCENARIO_SIDECAR_SCHEMA_NAME,
        "_validation.csv": VALIDATION_SIDECAR_SCHEMA_NAME,
        "_runtime.csv": RUNTIME_SIDECAR_SCHEMA_NAME,
    }
    matches = [value for suffix, value in expected_schema.items() if csv_path.name.endswith(suffix)]
    if len(matches) != 1 or payload.get("schema_name") != matches[0]:
        raise ArtifactError(f"Sidecar schema_name does not match {csv_path.name}.")
    if payload.get("schema_version") != 3:
        raise ArtifactError("Table sidecars must have schema_version=3.")
    if payload.get("csv_filename") != csv_path.name:
        raise ArtifactError(f"Sidecar csv_filename does not match {csv_path.name}.")
    _nonempty_text(payload.get("backend"), "sidecar.backend")
    _nonempty_text(payload.get("system_profile"), "sidecar.system_profile")
    _provenance_record(cast(Mapping[str, Any], payload.get("provenance")))
    _require_key_set(
        payload.get("component_hashes"),
        _COMPONENT_HASH_KEYS,
        "sidecar.component_hashes",
        hash_values=True,
    )
    _require_key_set(
        payload.get("layout_hashes"),
        _LAYOUT_HASH_KEYS,
        "sidecar.layout_hashes",
        hash_values=True,
    )
    reproducibility = _validate_reproducibility(payload.get("reproducibility"))
    _validate_authority_metadata(payload, reproducibility)
    if payload["csv_sha256"] != _content_hash(csv_path):
        raise ArtifactError(f"CSV hash mismatch for {csv_path}.")
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    if list(payload["header"]) != list(reader.fieldnames or ()):
        raise ArtifactError(f"Sidecar header mismatch for {csv_path}.")
    if int(payload["row_count"]) != len(rows):
        raise ArtifactError(f"Sidecar row-count mismatch for {csv_path}.")
    order_key = payload.get("row_order_key")
    if not isinstance(order_key, str) or order_key not in (reader.fieldnames or ()):
        raise ArtifactError(f"Sidecar row_order_key is absent from {csv_path}.")
    if list(payload.get("row_order", ())) != [row[order_key] for row in rows]:
        raise ArtifactError(f"Sidecar row order does not match {csv_path}.")
    if set(payload["field_units"]) != set(payload["header"]):
        raise ArtifactError(f"Sidecar field_units must cover every column in {csv_path}.")


def _write_manifest(
    path: Path,
    members: Sequence[Path],
    *,
    reference_path: Path | None,
    metadata: Mapping[str, Any],
) -> Path:
    records = []
    for member in sorted(members, key=lambda item: item.name):
        schema_name, schema_version = _member_schema(member, reference_path)
        records.append(
            {
                "filename": member.name,
                "schema_name": schema_name,
                "schema_version": schema_version,
                "content_sha256": _content_hash(member),
                "size_bytes": member.stat().st_size,
            }
        )
    payload: dict[str, Any] = {
        "schema_name": MANIFEST_SCHEMA_NAME,
        "schema_version": 3,
        "artifact_kind": metadata["artifact_kind"],
        "backend": metadata["backend"],
        "system_profile": metadata["system_profile"],
        "provenance": metadata["provenance"],
        "reproducibility": metadata["reproducibility"],
        "members": records,
    }
    for key in ("candidate", "diff", "acceptance"):
        if key in metadata:
            payload[key] = metadata[key]
    _validate_manifest(payload, members)
    return write_json_record(path, payload)


def _validate_manifest(payload: Mapping[str, Any], members: Sequence[Path]) -> None:
    if payload.get("schema_name") != MANIFEST_SCHEMA_NAME or payload.get("schema_version") != 3:
        raise ArtifactError("Artifact manifest has an invalid schema discriminator.")
    _nonempty_text(payload.get("backend"), "manifest.backend")
    _nonempty_text(payload.get("system_profile"), "manifest.system_profile")
    _provenance_record(cast(Mapping[str, Any], payload.get("provenance")))
    reproducibility = _validate_reproducibility(payload.get("reproducibility"))
    _validate_authority_metadata(payload, reproducibility)
    records = payload.get("members")
    if not isinstance(records, list) or not records:
        raise ArtifactError("Artifact manifest members must be a non-empty list.")
    filenames = [record.get("filename") for record in records if isinstance(record, Mapping)]
    if len(filenames) != len(records) or filenames != sorted(filenames) or len(set(filenames)) != len(filenames):
        raise ArtifactError("Artifact manifest member filenames must be unique and sorted.")
    by_name = {path.name: path for path in members}
    if set(filenames) != set(by_name):
        raise ArtifactError("Artifact manifest members do not match the generated file list.")
    for record in records:
        path = by_name[record["filename"]]
        if record.get("content_sha256") != _content_hash(path):
            raise ArtifactError(f"Artifact manifest hash mismatch for {path.name}.")
        if record.get("size_bytes") != path.stat().st_size:
            raise ArtifactError(f"Artifact manifest size mismatch for {path.name}.")
        _nonempty_text(record.get("schema_name"), f"manifest member {path.name} schema_name")
        if type(record.get("schema_version")) is not int or record["schema_version"] < 1:
            raise ArtifactError(f"Manifest member {path.name} has an invalid schema_version.")


def _member_schema(member: Path, reference_path: Path | None) -> tuple[str, int]:
    if reference_path is not None and member == reference_path:
        return FAST_REFERENCE_SCHEMA_NAME, 3
    if member.name.endswith("_error_budget.csv"):
        return "shwfs_ao.scenario_table", 3
    if member.name.endswith("_validation.csv"):
        return "shwfs_ao.validation_table", 3
    if member.name.endswith("_runtime.csv"):
        return "shwfs_ao.runtime_table", 3
    if member.name.endswith("_error_budget.sidecar.json"):
        return SCENARIO_SIDECAR_SCHEMA_NAME, 3
    if member.name.endswith("_validation.sidecar.json"):
        return VALIDATION_SIDECAR_SCHEMA_NAME, 3
    if member.name.endswith("_runtime.sidecar.json"):
        return RUNTIME_SIDECAR_SCHEMA_NAME, 3
    if member.suffix == ".png":
        return "image/png", 1
    if member.name.endswith("_runtime.json"):
        return "shwfs_ao.runtime_record", 2
    return "application/octet-stream", 1


def _scenario_rows(results: Sequence[object]) -> tuple[dict[str, Any], ...]:
    rows = []
    for result in results:
        method = getattr(result, "as_dict", None)
        if not callable(method):
            raise ArtifactError(f"Scenario result {type(result)!r} does not provide as_dict().")
        row = method()
        if not isinstance(row, Mapping):
            raise ArtifactError("Scenario as_dict() must return a mapping.")
        rows.append(dict(row))
    if not rows:
        raise ArtifactError("Integration result contains no scenario rows.")
    return tuple(rows)


def _validation_rows(results: Sequence[object]) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for result in results:
        as_dict = getattr(result, "as_dict", None)
        as_rows = getattr(result, "as_rows", None)
        if callable(as_dict):
            row = as_dict()
            if not isinstance(row, Mapping):
                raise ArtifactError("Validation as_dict() must return a mapping.")
            rows.append(dict(row))
        elif callable(as_rows):
            expanded = as_rows()
            for row in expanded:
                if not isinstance(row, Mapping):
                    raise ArtifactError("Validation as_rows() entries must be mappings.")
                rows.append(dict(row))
        else:
            raise ArtifactError(
                f"Validation result {type(result)!r} provides neither as_dict() nor as_rows()."
            )
    if not rows:
        raise ArtifactError("Integration result contains no validation rows.")
    return tuple(rows)


def _validate_table_header(
    actual: Sequence[str],
    frozen: Sequence[str],
    label: str,
) -> None:
    if tuple(actual) != tuple(frozen):
        raise ArtifactError(
            f"{label} CSV header must exactly match the frozen compatibility schema; "
            f"got {list(actual)}."
        )


def _validate_integration_result(result: object) -> None:
    required = (
        "mode",
        "scenario_results",
        "validation_results",
        "reference_metrics",
        "runtime_s",
        "source_class",
        "config_hash",
    )
    missing = [key for key in required if not hasattr(result, key)]
    if missing:
        raise ArtifactError(f"Integration result missing attributes: {missing}.")
    _validate_prefix(str(getattr(result, "mode")))
    _finite(getattr(result, "runtime_s"), "runtime_s")
    if float(getattr(result, "runtime_s")) < 0.0:
        raise ArtifactError("runtime_s must be non-negative.")
    if not isinstance(getattr(result, "reference_metrics"), Mapping):
        raise ArtifactError("reference_metrics must be a mapping.")
    if str(getattr(result, "config_hash")) != str(
        getattr(result, "reference_metrics").get("config_hash")
    ):
        raise ArtifactError("Result config_hash conflicts with reference_metrics.config_hash.")


def _integration_runtime_record(result: IntegrationArtifactResult) -> dict[str, Any]:
    return {
        "workflow": str(result.reference_metrics.get("workflow", "integration")),
        "preset": str(result.mode),
        "runtime_seconds": float(result.runtime_s),
        "runtime_band": str(result.reference_metrics.get("runtime_band", "informational")),
        "source_class": str(result.source_class),
        "config_hash": str(result.config_hash),
    }


def _reference_path(config: ArtifactConfig, prefix: str) -> Path:
    if config.reference_metrics_path is not None:
        return Path(config.reference_metrics_path)
    return Path(config.output_dir) / f"{prefix}_reference_metrics.json"


def _read_record(source: Path | str | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(source, Mapping):
        return _json_mapping(source, label="artifact record")
    path = Path(source)
    try:
        with open_text_resource(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ArtifactError(f"Could not read JSON artifact {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ArtifactError(f"JSON artifact {path} must contain an object.")
    return payload


def _read_csv_table(
    path: Path | str,
    *,
    allowed_headers: Sequence[Sequence[str]],
    label: str,
) -> tuple[dict[str, str], ...]:
    source = Path(path)
    try:
        with open_text_resource(source, encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            header = tuple(reader.fieldnames or ())
            rows = tuple(dict(row) for row in reader)
    except OSError as exc:
        raise ArtifactError(f"Could not read {label} CSV {source}: {exc}") from exc
    supported = tuple(tuple(item) for item in allowed_headers)
    if header not in supported:
        raise ArtifactError(
            f"Unsupported {label} CSV header {list(header)}; schema guessing is disabled."
        )
    if not rows:
        raise ArtifactError(f"{label.capitalize()} CSV {source} contains no rows.")
    if header[-len(SCHEMA_V3_TABLE_COLUMNS) :] == SCHEMA_V3_TABLE_COLUMNS:
        for index, row in enumerate(rows):
            if row["artifact_schema_version"] != "3":
                raise ArtifactError(f"{label} CSV row {index} has an invalid schema version.")
            if row["artifact_kind"] not in {
                "run_result",
                "baseline_candidate",
                "accepted_regression_baseline",
            }:
                raise ArtifactError(f"{label} CSV row {index} has an invalid artifact kind.")
    return rows


def _append_v3_table_metadata(
    rows: Sequence[Mapping[str, Any]],
    metadata: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    additions = _v3_table_columns(metadata)
    updated: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        conflicts = sorted(set(row).intersection(additions))
        if conflicts:
            raise ArtifactError(
                f"Schema-v3 table row {index} already defines reserved columns: {conflicts}."
            )
        updated.append({**row, **additions})
    return tuple(updated)


def _v3_table_columns(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact_schema_version": 3,
        "artifact_kind": metadata["artifact_kind"],
        "backend": metadata["backend"],
        "system_profile": metadata["system_profile"],
    }


def _preflight_destinations(paths: Sequence[Path]) -> None:
    normalized = [path.absolute() for path in paths]
    duplicates = sorted(
        {str(path) for path in normalized if normalized.count(path) > 1}
    )
    names = [path.name for path in paths]
    duplicate_names = sorted({name for name in names if names.count(name) > 1})
    if duplicates or duplicate_names:
        raise ArtifactError(
            "Artifact destinations must be unique before writing; "
            f"duplicate_paths={duplicates}, duplicate_names={duplicate_names}."
        )


def _json_mapping(value: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ArtifactError(f"{label} must be a mapping.")
    try:
        encoded = json.dumps(dict(value), allow_nan=False)
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ArtifactError(f"{label} must contain only finite JSON values: {exc}") from exc
    if not isinstance(decoded, dict):
        raise ArtifactError(f"{label} must encode as a JSON object.")
    return decoded


def _provenance_record(value: Provenance | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(value, Provenance):
        return value.to_record()
    record = _json_mapping(value, label="provenance")
    try:
        return Provenance.from_record(record).to_record()
    except ValueError as exc:
        raise ArtifactError(f"Invalid provenance record: {exc}") from exc


def _require_key_set(
    value: object,
    keys: Sequence[str],
    label: str,
    *,
    exact: bool = False,
    hash_values: bool = False,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ArtifactError(f"{label} must be a mapping.")
    record = dict(value)
    missing = [key for key in keys if key not in record]
    if missing:
        raise ArtifactError(f"{label} missing fields: {missing}.")
    if exact and set(record) != set(keys):
        raise ArtifactError(f"{label} keys must exactly match {list(keys)}.")
    if hash_values:
        for key in keys:
            _require_hash(record[key], f"{label}.{key}")
    return record


def _require_hash(value: object, label: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ArtifactError(f"{label} must be a SHA-256 digest, optionally prefixed by 'sha256:'.")


def _content_hash(path: Path) -> str:
    return f"sha256:{sha256(path.read_bytes()).hexdigest()}"


def _ordered_header(rows: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    fields: list[str] = []
    for row in rows:
        for key in row:
            text = str(key)
            if text not in fields:
                fields.append(text)
    return tuple(fields)


def _validate_prefix(value: str) -> None:
    if not isinstance(value, str) or not _SAFE_PREFIX.fullmatch(value):
        raise ArtifactError(
            "Artifact prefix must be a filename-safe non-empty token containing only "
            "letters, digits, '.', '_', or '-'."
        )


def _validate_runtime_formats(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, str):
        raise ArtifactError("runtime formats must be a sequence, not one string.")
    formats = tuple(str(item).lower() for item in values)
    if not formats or len(formats) != len(set(formats)):
        raise ArtifactError("runtime formats must be non-empty and unique.")
    unsupported = sorted(set(formats).difference({"json", "csv"}))
    if unsupported:
        raise ArtifactError(f"Unsupported runtime formats: {unsupported}.")
    return formats


def _nonempty_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ArtifactError(f"{label} must be a non-empty string.")
    return value


def _finite(value: object, label: str) -> None:
    try:
        finite = math.isfinite(float(value))
    except (TypeError, ValueError) as exc:
        raise ArtifactError(f"{label} must be finite; got {value!r}.") from exc
    if not finite:
        raise ArtifactError(f"{label} must be finite; got {value!r}.")


def _scenario_field_units(header: Sequence[str]) -> dict[str, str]:
    units = {key: "dimensionless" for key in header}
    for key in ("scenario_name", "enabled_effects", "source_class", "source_note", "config_hash"):
        if key in units:
            units[key] = "text"
    for key in ("open_rms_nm", "closed_rms_nm", "command_rms_nm", "command_peak_nm"):
        if key in units:
            units[key] = "nm_opd"
    return units


def _validation_field_units(header: Sequence[str]) -> dict[str, str]:
    units = {key: "record_defined" for key in header}
    for key in ("check_name", "message", "source_class", "source_note", "x_unit", "metric_unit"):
        if key in units:
            units[key] = "text"
    if "passed" in units:
        units["passed"] = "boolean"
    return units


def _runtime_field_units(header: Sequence[str]) -> dict[str, str]:
    units = {key: "text" for key in header}
    if "runtime_seconds" in units:
        units["runtime_seconds"] = "s"
    if "runtime_minutes" in units:
        units["runtime_minutes"] = "min"
    if "runtime_limit_minutes" in units:
        units["runtime_limit_minutes"] = "min"
    if "within_runtime_limit" in units:
        units["within_runtime_limit"] = "boolean"
    return units


def _plot_scenario_summary(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = [str(row["scenario_name"]) for row in rows]
    open_rms = np.asarray([float(row["open_rms_nm"]) for row in rows], dtype=float)
    closed_rms = np.asarray([float(row["closed_rms_nm"]) for row in rows], dtype=float)
    strehl_h = np.asarray([float(row["strehl_H"]) for row in rows], dtype=float)
    x = np.arange(len(names))
    fig, ax1 = plt.subplots(figsize=(9.0, 4.8), constrained_layout=True)
    ax1.bar(x - 0.18, open_rms, width=0.35, color="#8d99ae", label="open RMS")
    ax1.bar(x + 0.18, closed_rms, width=0.35, color="#2a9d8f", label="closed RMS")
    ax1.set_ylabel("OPD RMS [nm]")
    ax1.set_xticks(x)
    ax1.set_xticklabels(names, rotation=35, ha="right")
    ax1.grid(axis="y", alpha=0.25)
    ax2 = ax1.twinx()
    ax2.plot(x, strehl_h, color="#e76f51", marker="o", linewidth=1.8, label="closed H Strehl")
    ax2.set_ylim(0.0, 1.05)
    ax2.set_ylabel("H-band Strehl")
    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(handles1 + handles2, labels1 + labels2, loc="upper left")
    ax1.set_title("Fast 2 m detector-level SCAO scenarios")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=140, pil_kwargs={"optimize": True})
    plt.close(fig)


def _plot_validation_summary(path: Path, results: Sequence[object]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    scans = [
        result
        for result in results
        if hasattr(result, "x_values") and hasattr(result, "metric_values")
    ]
    if len(scans) < 3:
        raise ArtifactError("Validation summary figure requires photon, latency, and fitting scans.")
    fig, axes = plt.subplots(1, 3, figsize=(11.0, 3.6), constrained_layout=True)
    axes[0].loglog(scans[0].x_values, scans[0].metric_values, marker="o", color="#1982c4")
    axes[0].set_xlabel("photons/subap/frame")
    axes[0].set_ylabel("centroid RMS [px]")
    axes[0].set_title("Photon monotonicity")
    axes[0].grid(True, which="both", alpha=0.25)
    axes[1].plot(scans[1].x_values, scans[1].metric_values, marker="o", color="#e76f51")
    axes[1].set_xlabel("latency [frames]")
    axes[1].set_ylabel("median residual [nm]")
    axes[1].set_title("Latency penalty")
    axes[1].grid(True, alpha=0.25)
    axes[2].plot(scans[2].x_values, scans[2].metric_values, marker="o", color="#2a9d8f")
    axes[2].set_xlabel("actuators across")
    axes[2].set_ylabel("fit residual [nm]")
    axes[2].set_title("DM fitting trend")
    axes[2].grid(True, alpha=0.25)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=140, pil_kwargs={"optimize": True})
    plt.close(fig)


def _minimal_reference_probe() -> dict[str, Any]:
    """Internal shape used only to validate ArtifactConfig authority rules."""

    return {
        "workflow": "probe",
        "preset": "probe",
        "source_class": "synthetic_assumed",
        "source_note": "Schema validation probe.",
        "config_hash": "0" * 64,
        "scenario_count": 1,
        "scenario_names": ["probe"],
        "reference_scenario": "probe",
        "open_rms_nm": 0.0,
        "closed_rms_nm": 0.0,
        "h_strehl": 0.0,
        "valid_centroid_fraction": 0.0,
        "kept_modes": 1,
        "runtime_band": "informational",
        "runtime_note": "probe",
        "validation_pass_count": 1,
        "validation_check_count": 1,
        "tolerances": {key: 0.0 for key in _TOLERANCE_KEYS},
    }
