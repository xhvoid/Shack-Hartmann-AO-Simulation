"""Strict loaders for the ESO SCAO source and assumption ledgers.

The ledgers are packaged JSON resources under ``benchmarks/``.  The source
ledger names every external source (R1-R4) with its locator, role and
limitations; the assumption ledger closes every executable value of the
benchmark profiles with either a normative source or an explicit assumption.

:func:`validate_benchmark_profiles` is the executable form of that promise:
it fails when a profile value is not covered by any row, when a row's stated
value disagrees with a profile, when a non-normative source is used as
authority, or when the frame clock and detector exposure field disagree.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import math
from typing import Any, Final

from .configs import SystemConfig, system_config_to_mapping
from .resources import read_text_resource


__all__ = (
    "SOURCE_LEDGER_RESOURCE",
    "ASSUMPTION_LEDGER_RESOURCE",
    "ASSUMPTION_LEDGER_V1_RESOURCE",
    "LedgerError",
    "load_source_ledger",
    "load_assumption_ledger",
    "validate_assumption_ledger",
    "profile_value_paths",
    "validate_benchmark_profiles",
)


SOURCE_LEDGER_RESOURCE: Final = "benchmarks/eso_scao_source_ledger.v1.json"
ASSUMPTION_LEDGER_RESOURCE: Final = "benchmarks/eso_drm_42m_scao_derived.assumptions.v2.json"
ASSUMPTION_LEDGER_V1_RESOURCE: Final = "benchmarks/eso_drm_42m_scao_derived.assumptions.v1.json"
_SOURCE_FIELDS: Final = {
    "id", "title", "url", "locator", "content_date", "accessed", "role",
    "supports", "limitations",
}
_ROLES: Final = {"normative", "contextual_reference_case"}
_ROW_FIELDS: Final = {
    "id", "title", "classification", "applies_to", "unit", "authority_sources",
    "locator", "rationale", "transformation", "limitation", "consuming_tests",
}
_ROW_OPTIONAL: Final = {"values", "values_by_profile", "context_sources", "implicit_model_property"}
_SOURCED: Final = {"source_derived", "source_scale_adapted"}
_DERIVED_PREFIX: Final = "derived:"


class LedgerError(ValueError):
    """Raised when a ledger is malformed or does not close a profile."""


def _json(name: str) -> dict[str, Any]:
    try:
        value = json.loads(read_text_resource(name))
    except (OSError, json.JSONDecodeError) as exc:
        raise LedgerError(f"cannot read ledger {name!r}: {exc}") from exc
    if not isinstance(value, dict):
        raise LedgerError(f"ledger {name!r} must be a JSON object.")
    return value


def load_source_ledger(name: str = SOURCE_LEDGER_RESOURCE) -> dict[str, Any]:
    record = _json(name)
    if record.get("schema_name") != "shwfs_ao.source_ledger":
        raise LedgerError("source ledger schema_name mismatch.")
    validate_source_ledger(record)
    return record


def validate_source_ledger(record: Mapping[str, Any]) -> None:
    sources = record.get("sources")
    if not isinstance(sources, list) or not sources:
        raise LedgerError("source ledger must list sources.")
    seen: set[str] = set()
    for source in sources:
        if not isinstance(source, Mapping) or set(source) != _SOURCE_FIELDS:
            raise LedgerError(f"source entry fields differ: {source!r}.")
        identifier = source["id"]
        if identifier in seen:
            raise LedgerError(f"duplicate source id {identifier!r}.")
        seen.add(identifier)
        if source["role"] not in _ROLES:
            raise LedgerError(f"source {identifier} has unknown role {source['role']!r}.")
        if not str(source["url"]).startswith("https://"):
            raise LedgerError(f"source {identifier} needs a direct https URL.")
        for field in ("locator", "content_date", "accessed", "title"):
            if not isinstance(source[field], str) or not source[field].strip():
                raise LedgerError(f"source {identifier} needs a non-empty {field}.")
        if not source["supports"] or not source["limitations"]:
            raise LedgerError(f"source {identifier} needs supported claims and limitations.")
    for case in record.get("reference_cases", []):
        if case.get("status") != "documented_not_runnable":
            raise LedgerError("reference cases are documented records, not runnable claims.")
        if not set(case.get("source_ids", ())) <= seen:
            raise LedgerError(f"reference case {case.get('case_id')} cites unknown sources.")


def _source_roles(source_ledger: Mapping[str, Any]) -> dict[str, str]:
    return {source["id"]: source["role"] for source in source_ledger["sources"]}


def load_assumption_ledger(
    name: str = ASSUMPTION_LEDGER_RESOURCE,
    *,
    source_ledger: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    record = _json(name)
    sources = load_source_ledger() if source_ledger is None else source_ledger
    validate_assumption_ledger(record, sources)
    return record


def validate_assumption_ledger(
    record: Mapping[str, Any],
    source_ledger: Mapping[str, Any],
) -> None:
    """Row structure and source-authority rules, independent of any profile."""

    if record.get("schema_name") != "shwfs_ao.assumption_ledger":
        raise LedgerError("assumption ledger schema_name mismatch.")
    classifications = record.get("classifications")
    if not isinstance(classifications, Mapping) or not classifications:
        raise LedgerError("assumption ledger must define its classifications.")
    roles = _source_roles(source_ledger)
    normative = {key for key, role in roles.items() if role == "normative"}
    rows = record.get("rows")
    if not isinstance(rows, list) or not rows:
        raise LedgerError("assumption ledger must contain rows.")
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise LedgerError("each assumption row must be an object.")
        keys = set(row)
        if not _ROW_FIELDS <= keys <= _ROW_FIELDS | _ROW_OPTIONAL:
            raise LedgerError(
                f"row {row.get('id')!r} fields differ: missing="
                f"{sorted(_ROW_FIELDS - keys)} extra={sorted(keys - _ROW_FIELDS - _ROW_OPTIONAL)}."
            )
        identifier = row["id"]
        if identifier in seen:
            raise LedgerError(f"duplicate assumption id {identifier!r}.")
        seen.add(identifier)
        classification = row["classification"]
        if classification not in classifications:
            raise LedgerError(f"row {identifier} has unknown classification {classification!r}.")
        authority = list(row["authority_sources"])
        if classification in _SOURCED:
            if not authority or not set(authority) <= normative:
                raise LedgerError(
                    f"row {identifier} is {classification} and must cite normative "
                    f"sources {sorted(normative)} as authority."
                )
            if not str(row["locator"]).strip():
                raise LedgerError(f"row {identifier} needs a source locator.")
        elif authority:
            raise LedgerError(
                f"row {identifier} is {classification}; it may name sources only as "
                "context_sources, not as authority."
            )
        if not set(row.get("context_sources", ())) <= set(roles):
            raise LedgerError(f"row {identifier} cites unknown context sources.")
        if not str(row["rationale"]).strip():
            raise LedgerError(f"row {identifier} needs a rationale.")
        tests = row["consuming_tests"]
        if not isinstance(tests, list) or not tests or not all(isinstance(t, str) for t in tests):
            raise LedgerError(f"row {identifier} must name its consuming tests.")
        has_values = bool(row.get("values")) or bool(row.get("values_by_profile"))
        if not has_values and not row.get("implicit_model_property", False):
            raise LedgerError(
                f"row {identifier} states no executable value and is not marked "
                "as an implicit model property."
            )


def profile_value_paths(config: SystemConfig) -> dict[str, Any]:
    """Leaf paths of a profile's ``config`` block (layers as ``layers[*]``)."""

    mapping = system_config_to_mapping(config)["config"]
    assert isinstance(mapping, Mapping)
    paths: dict[str, Any] = {}

    def walk(prefix: str, value: Any) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                walk(f"{prefix}.{key}" if prefix else key, item)
        elif (
            isinstance(value, list)
            and value
            and all(isinstance(item, Mapping) for item in value)
        ):
            for item in value:
                for key, inner in item.items():
                    paths.setdefault(f"{prefix}[*].{key}", []).append(inner)
        else:
            paths[prefix] = value

    walk("", mapping)
    return paths


def _equal(expected: Any, actual: Any) -> bool:
    if isinstance(expected, float) and isinstance(actual, (int, float)) and not isinstance(actual, bool):
        return math.isclose(expected, float(actual), rel_tol=1e-15, abs_tol=0.0)
    return expected == actual


def validate_benchmark_profiles(
    ledger: Mapping[str, Any],
    configs: Mapping[str, SystemConfig],
) -> dict[str, list[str]]:
    """Check coverage, stated values, and the frame clock of every profile.

    Returns, per profile, the row IDs covering each path; raises
    :class:`LedgerError` listing every uncovered path, mismatched value, or
    clock inconsistency.
    """

    declared = set(ledger.get("profiles", ()))
    if set(configs) != declared:
        raise LedgerError(
            f"ledger profiles {sorted(declared)} differ from those checked {sorted(configs)}."
        )
    problems: list[str] = []
    coverage: dict[str, list[str]] = {}
    for profile_id, config in configs.items():
        if config.profile.provenance.source_class != "synthetic_assumed":
            problems.append(
                f"{profile_id}: the derived configuration must disclose its synthetic "
                "assumptions (source_class 'synthetic_assumed')."
            )
        period = 1.0 / config.controller.frame_rate_hz
        if not math.isclose(config.detector.exposure_s, period, rel_tol=1e-12):
            problems.append(
                f"{profile_id}: detector.exposure_s {config.detector.exposure_s} != frame "
                f"period {period} (A10 clock)."
            )
        paths = profile_value_paths(config)
        covered: dict[str, list[str]] = {path: [] for path in paths}
        for row in ledger["rows"]:
            applies = row["applies_to"]
            if applies != "all" and profile_id not in applies:
                continue
            stated = dict(row.get("values", {}))
            stated.update(row.get("values_by_profile", {}).get(profile_id, {}))
            for path, value in stated.items():
                if path not in paths:
                    problems.append(f"{profile_id}: row {row['id']} names unknown path {path!r}.")
                    continue
                covered[path].append(row["id"])
                if isinstance(value, str) and value.startswith(_DERIVED_PREFIX):
                    continue
                if not _equal(value, paths[path]):
                    problems.append(
                        f"{profile_id}: row {row['id']} states {path}={value!r} but the "
                        f"profile has {paths[path]!r}."
                    )
        uncovered = sorted(path for path, rows in covered.items() if not rows)
        if uncovered:
            problems.append(f"{profile_id}: values without a ledger row: {uncovered}.")
        coverage[profile_id] = sorted({row for rows in covered.values() for row in rows})
    if problems:
        raise LedgerError("; ".join(problems))
    return coverage


def benchmark_profile_ids(ledger: Mapping[str, Any]) -> Sequence[str]:
    return tuple(ledger["profiles"])
