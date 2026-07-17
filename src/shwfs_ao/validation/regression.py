"""Cross-backend baseline documents: contract, loading, and evaluation.

A *report* is what one execution of the cross-backend suite produces.  A
*baseline* is a reviewed report plus generator and acceptance provenance,
committed as a packaged resource.  Tests and examples only ever read
baselines; the candidate-generation script writes candidates to an explicit
external directory, and acceptance is a separate explicit command.

Evaluation semantics: the baseline's per-metric pass criteria are the
tolerance contract.  Exact-level metrics require equality with the baseline
value; ``tight_numerical`` and ``physical_tolerance`` metrics require the
freshly observed value to satisfy the criterion recorded in the baseline
(absolute tolerance around the expected value, or an explicit range);
``informational`` metrics are reported but never gate.  Fixture and
configuration hashes must match exactly before any metric is compared, so a
tolerance can never paper over changed inputs.
"""

from __future__ import annotations

import json
import math
from numbers import Real
from typing import Any, Mapping

from ..io.resources import read_text_resource


CROSS_BACKEND_REPORT_SCHEMA_NAME = "shwfs_ao.cross_backend_report"
CROSS_BACKEND_BASELINE_SCHEMA_NAME = "shwfs_ao.cross_backend_baseline"
CROSS_BACKEND_BASELINE_SCHEMA_VERSION = 1
CROSS_BACKEND_BASELINE_RESOURCE = (
    "reference_metrics/cross_backend/cross_backend_baseline.json"
)

COMPARISON_LEVELS = (
    "exact",
    "tight_numerical",
    "physical_tolerance",
    "informational",
)
_CRITERION_TYPES = ("equals", "abs_tolerance", "range", "informational")

_REQUIRED_ENVIRONMENT_FIELDS = (
    "python_version",
    "numpy_version",
    "shwfs_ao_version",
    "hcipy_version",
    "platform",
    "dependency_constraint_file",
    "dependency_constraint_sha256",
)
_REQUIRED_GENERATOR_FIELDS = ("generator_name", "generator_version", "source_commit")
_REQUIRED_ACCEPTANCE_FIELDS = ("reason", "review_reference", "accepted_at_utc")
_REQUIRED_HASH_GROUPS = ("component_hashes", "fixture_hashes")
_REQUIRED_CONVENTION_FIELDS = (
    "command_unit",
    "residual_sign_convention",
    "measurement_unit",
)

__all__ = (
    "CROSS_BACKEND_REPORT_SCHEMA_NAME",
    "CROSS_BACKEND_BASELINE_SCHEMA_NAME",
    "CROSS_BACKEND_BASELINE_SCHEMA_VERSION",
    "CROSS_BACKEND_BASELINE_RESOURCE",
    "COMPARISON_LEVELS",
    "BaselineContractError",
    "validate_cross_backend_report",
    "validate_cross_backend_baseline",
    "baseline_from_report",
    "load_cross_backend_baseline",
    "evaluate_report_against_baseline",
    "format_metric_failure",
)


class BaselineContractError(ValueError):
    """Raised when a report or baseline document violates the contract."""


def validate_cross_backend_report(document: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate the shared report body: identity, hashes, and metrics."""

    if not isinstance(document, Mapping):
        raise BaselineContractError("document must be a JSON object mapping.")
    _require_fields(
        document,
        (
            "artifact_schema_name",
            "artifact_schema_version",
            "comparison_config",
            "root_seed",
            "conventions",
            "component_hashes",
            "fixture_hashes",
            "environment",
            "comparisons",
        ),
        label="report",
    )
    if document["artifact_schema_name"] not in (
        CROSS_BACKEND_REPORT_SCHEMA_NAME,
        CROSS_BACKEND_BASELINE_SCHEMA_NAME,
    ):
        raise BaselineContractError(
            f"unexpected artifact_schema_name "
            f"{document['artifact_schema_name']!r}."
        )
    if document["artifact_schema_version"] != CROSS_BACKEND_BASELINE_SCHEMA_VERSION:
        raise BaselineContractError(
            "unsupported artifact_schema_version "
            f"{document['artifact_schema_version']!r}."
        )
    config = document["comparison_config"]
    if not isinstance(config, Mapping) or "config_hash" not in config:
        raise BaselineContractError(
            "comparison_config must be a mapping with a config_hash."
        )
    _require_fields(
        document["conventions"],
        _REQUIRED_CONVENTION_FIELDS,
        label="conventions",
    )
    for group in _REQUIRED_HASH_GROUPS:
        hashes = document[group]
        if not isinstance(hashes, Mapping) or not hashes:
            raise BaselineContractError(f"{group} must be a non-empty mapping.")
        for key, value in hashes.items():
            if not isinstance(value, str) or len(value) != 64:
                raise BaselineContractError(
                    f"{group}[{key!r}] must be a 64-character content hash."
                )
    _require_fields(
        document["environment"],
        _REQUIRED_ENVIRONMENT_FIELDS,
        label="environment",
    )
    comparisons = document["comparisons"]
    if not isinstance(comparisons, list) or not comparisons:
        raise BaselineContractError("comparisons must be a non-empty list.")
    seen_kinds: set[str] = set()
    for comparison in comparisons:
        _validate_comparison(comparison)
        kind = comparison["comparison_kind"]
        if kind in seen_kinds:
            raise BaselineContractError(
                f"duplicate comparison_kind {kind!r} in document."
            )
        seen_kinds.add(kind)
    return document


def validate_cross_backend_baseline(document: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate the complete committed-baseline contract.

    Beyond the shared report body, a baseline must carry generator identity
    and explicit human acceptance; continuous integration rejects a baseline
    whose generator or rationale fields are absent.
    """

    validate_cross_backend_report(document)
    if document["artifact_schema_name"] != CROSS_BACKEND_BASELINE_SCHEMA_NAME:
        raise BaselineContractError(
            "baseline artifact_schema_name must be "
            f"{CROSS_BACKEND_BASELINE_SCHEMA_NAME!r}."
        )
    _require_fields(document, ("generator", "acceptance"), label="baseline")
    _require_fields(
        document["generator"],
        _REQUIRED_GENERATOR_FIELDS,
        label="generator",
    )
    _require_fields(
        document["acceptance"],
        _REQUIRED_ACCEPTANCE_FIELDS,
        label="acceptance",
    )
    for comparison in document["comparisons"]:
        for metric in comparison["metrics"]:
            rationale = metric.get("rationale")
            if not isinstance(rationale, str) or not rationale.strip():
                raise BaselineContractError(
                    f"baseline metric {metric.get('name')!r} in comparison "
                    f"{comparison['comparison_kind']!r} is missing its "
                    "scientific rationale."
                )
    return document


def baseline_from_report(
    report: Mapping[str, Any],
    *,
    generator: Mapping[str, Any],
    acceptance: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a baseline document from a validated report plus provenance."""

    validate_cross_backend_report(report)
    document = json.loads(json.dumps(dict(report)))
    document["artifact_schema_name"] = CROSS_BACKEND_BASELINE_SCHEMA_NAME
    document["generator"] = dict(generator)
    document["acceptance"] = dict(acceptance)
    return validate_cross_backend_baseline(document)  # type: ignore[return-value]


def load_cross_backend_baseline() -> Mapping[str, Any]:
    """Load and validate the packaged cross-backend baseline resource."""

    try:
        text = read_text_resource(CROSS_BACKEND_BASELINE_RESOURCE)
    except (FileNotFoundError, KeyError, ValueError) as exc:
        raise BaselineContractError(
            f"cannot load packaged baseline "
            f"{CROSS_BACKEND_BASELINE_RESOURCE!r}: {exc}"
        ) from exc
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BaselineContractError(
            f"packaged baseline is not valid JSON: {exc}"
        ) from exc
    return validate_cross_backend_baseline(document)


def evaluate_report_against_baseline(
    report: Mapping[str, Any],
    baseline: Mapping[str, Any],
) -> tuple[str, ...]:
    """Return failure messages from checking a fresh report against a baseline.

    An empty tuple means every gating criterion passed.  Every failure names
    the observed value, the expected value or range, the tolerance with its
    units, and the compared configuration/fixture hashes.
    """

    validate_cross_backend_report(report)
    validate_cross_backend_baseline(baseline)
    failures: list[str] = []

    hash_context = _hash_context(baseline)
    baseline_config_hash = baseline["comparison_config"]["config_hash"]
    report_config_hash = report["comparison_config"]["config_hash"]
    if report_config_hash != baseline_config_hash:
        failures.append(
            "comparison_config.config_hash mismatch: observed="
            f"{report_config_hash} expected={baseline_config_hash}; the "
            "comparison inputs are not the baseline inputs."
        )
        return tuple(failures)
    for group in _REQUIRED_HASH_GROUPS:
        for key, expected in baseline[group].items():
            observed = report[group].get(key)
            if observed != expected:
                failures.append(
                    f"{group}[{key!r}] mismatch: observed={observed} "
                    f"expected={expected}; shared inputs drifted, so metric "
                    "tolerances do not apply."
                )
    if failures:
        return tuple(failures)

    report_metrics = _metric_index(report)
    for comparison in baseline["comparisons"]:
        kind = comparison["comparison_kind"]
        for metric in comparison["metrics"]:
            name = metric["name"]
            criterion = metric["pass_criterion"]
            if criterion["type"] == "informational":
                continue
            observed_entry = report_metrics.get((kind, name))
            if observed_entry is None:
                failures.append(
                    f"comparison={kind} metric={name}: missing from the "
                    f"fresh report; {hash_context}"
                )
                continue
            failure = _evaluate_metric(
                kind,
                metric,
                observed_entry["value"],
                hash_context=hash_context,
            )
            if failure is not None:
                failures.append(failure)
    return tuple(failures)


def format_metric_failure(
    comparison_kind: str,
    metric: Mapping[str, Any],
    observed: Any,
    *,
    hash_context: str,
) -> str:
    """Render one complete failure message for a metric criterion."""

    criterion = metric["pass_criterion"]
    units = metric.get("units", "dimensionless")
    if criterion["type"] == "equals":
        expected_text = f"expected={criterion['expected']!r} tolerance=exact"
    elif criterion["type"] == "abs_tolerance":
        expected_text = (
            f"expected={criterion['expected']!r} "
            f"tolerance=±{criterion['tolerance']!r} {units}"
        )
    elif criterion["type"] == "range":
        expected_text = (
            f"expected-range=[{criterion['low']!r}, {criterion['high']!r}] "
            f"{units}"
        )
    else:
        expected_text = "informational"
    return (
        f"comparison={comparison_kind} metric={metric['name']}: "
        f"observed={observed!r} {units}; {expected_text}; "
        f"level={metric['level']}; {hash_context}"
    )


def _evaluate_metric(
    comparison_kind: str,
    metric: Mapping[str, Any],
    observed: Any,
    *,
    hash_context: str,
) -> str | None:
    criterion = metric["pass_criterion"]
    kind = criterion["type"]
    if kind == "equals":
        if observed == criterion["expected"]:
            return None
    elif kind == "abs_tolerance":
        if (
            isinstance(observed, Real)
            and math.isfinite(float(observed))
            and abs(float(observed) - float(criterion["expected"]))
            <= float(criterion["tolerance"])
        ):
            return None
    elif kind == "range":
        if (
            isinstance(observed, Real)
            and math.isfinite(float(observed))
            and float(criterion["low"]) <= float(observed) <= float(criterion["high"])
        ):
            return None
    else:  # pragma: no cover - validated earlier
        return None
    return format_metric_failure(
        comparison_kind,
        metric,
        observed,
        hash_context=hash_context,
    )


def _validate_comparison(comparison: object) -> None:
    if not isinstance(comparison, Mapping):
        raise BaselineContractError("each comparison must be a mapping.")
    _require_fields(
        comparison,
        ("comparison_kind", "attribution", "metrics"),
        label="comparison",
    )
    metrics = comparison["metrics"]
    if not isinstance(metrics, list) or not metrics:
        raise BaselineContractError(
            f"comparison {comparison['comparison_kind']!r} must contain "
            "metrics."
        )
    seen_names: set[str] = set()
    for metric in metrics:
        if not isinstance(metric, Mapping):
            raise BaselineContractError("each metric must be a mapping.")
        _require_fields(
            metric,
            ("name", "level", "units", "value", "pass_criterion"),
            label="metric",
        )
        if metric["level"] not in COMPARISON_LEVELS:
            raise BaselineContractError(
                f"metric {metric['name']!r} has unknown level "
                f"{metric['level']!r}."
            )
        criterion = metric["pass_criterion"]
        if (
            not isinstance(criterion, Mapping)
            or criterion.get("type") not in _CRITERION_TYPES
        ):
            raise BaselineContractError(
                f"metric {metric['name']!r} has an invalid pass_criterion."
            )
        if criterion["type"] == "abs_tolerance" and (
            "expected" not in criterion or "tolerance" not in criterion
        ):
            raise BaselineContractError(
                f"metric {metric['name']!r} abs_tolerance criterion needs "
                "expected and tolerance."
            )
        if criterion["type"] == "range" and (
            "low" not in criterion or "high" not in criterion
        ):
            raise BaselineContractError(
                f"metric {metric['name']!r} range criterion needs low and "
                "high."
            )
        if criterion["type"] == "equals" and "expected" not in criterion:
            raise BaselineContractError(
                f"metric {metric['name']!r} equals criterion needs expected."
            )
        if (metric["level"] == "informational") != (
            criterion["type"] == "informational"
        ):
            raise BaselineContractError(
                f"metric {metric['name']!r} level and criterion type must "
                "agree on informational status."
            )
        if metric["name"] in seen_names:
            raise BaselineContractError(
                f"duplicate metric name {metric['name']!r} in comparison "
                f"{comparison['comparison_kind']!r}."
            )
        seen_names.add(metric["name"])


def _metric_index(
    report: Mapping[str, Any],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    index: dict[tuple[str, str], Mapping[str, Any]] = {}
    for comparison in report["comparisons"]:
        for metric in comparison["metrics"]:
            index[(comparison["comparison_kind"], metric["name"])] = metric
    return index


def _hash_context(document: Mapping[str, Any]) -> str:
    config_hash = str(document["comparison_config"]["config_hash"])
    fixture_hashes = document["fixture_hashes"]
    fixture_text = ",".join(
        f"{key}={str(value)[:8]}" for key, value in sorted(fixture_hashes.items())
    )
    return f"config_hash={config_hash[:8]} fixtures[{fixture_text}]"


def _require_fields(
    mapping: object,
    fields: tuple[str, ...],
    *,
    label: str,
) -> None:
    if not isinstance(mapping, Mapping):
        raise BaselineContractError(f"{label} must be a mapping.")
    missing = [field for field in fields if field not in mapping]
    if missing:
        raise BaselineContractError(
            f"{label} is missing required fields: {missing}."
        )
    for field in fields:
        value = mapping[field]
        if value is None or (isinstance(value, str) and not value.strip()):
            raise BaselineContractError(
                f"{label}.{field} must be present and non-empty."
            )
