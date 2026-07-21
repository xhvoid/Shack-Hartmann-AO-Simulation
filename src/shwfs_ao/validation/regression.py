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
import re
from numbers import Real
from typing import Any, Mapping

from ..io.resources import read_text_resource


CROSS_BACKEND_REPORT_SCHEMA_NAME = "shwfs_ao.cross_backend_report"
CROSS_BACKEND_BASELINE_SCHEMA_NAME = "shwfs_ao.cross_backend_baseline"
CROSS_BACKEND_BASELINE_SCHEMA_VERSION = 1
CROSS_BACKEND_BASELINE_RESOURCE = (
    "reference_metrics/cross_backend/cross_backend_baseline.json"
)
CROSS_BACKEND_BASELINE_SCHEMA_RESOURCE = (
    "schemas/cross_backend_baseline.schema.json"
)

COMPARISON_LEVELS = (
    "exact",
    "tight_numerical",
    "physical_tolerance",
    "informational",
)
REQUIRED_COMPARISON_KINDS = (
    "pupil_mask_and_throughput",
    "zernike_modes",
    "atmosphere_statistics",
    "wfs_tip_tilt_response",
    "lenslet_spot_morphology",
    "dm_single_actuator_influence",
    "dm_static_fitting",
    "interaction_matrix_identity",
    "normalized_singular_spectrum",
    "psf_normalization",
    "strehl_ratio",
    "closed_loop_residual",
    "runtime_and_memory",
)
_CRITERION_TYPES = ("equals", "abs_tolerance", "range", "informational")
_CONTENT_HASH_64 = re.compile(r"[0-9a-f]{64}")
_SOURCE_COMMIT_40 = re.compile(r"[0-9a-f]{40}")

REQUIRED_COMPONENT_HASH_KEYS = (
    "dm_actuator_ids",
    "hcipy_dm",
    "hcipy_science",
    "hcipy_wfs_optics",
    "native_dm",
    "native_science",
    "native_wfs_optics",
    "pupil_geometry",
    "shack_hartmann_geometry",
    "wfs_row_ids",
)
REQUIRED_FIXTURE_HASH_KEYS = (
    "atmosphere_opd_cube_m",
    "command_fixture_opd_m",
    "static_opd_m",
    "tilt_x_opd_m",
    "tilt_y_opd_m",
    "time_grid_s",
)
_REQUIRED_HASH_KEYS: Mapping[str, tuple[str, ...]] = {
    "component_hashes": REQUIRED_COMPONENT_HASH_KEYS,
    "fixture_hashes": REQUIRED_FIXTURE_HASH_KEYS,
}

# The complete AO-REF-018 metric inventory, per comparison kind.  Validation
# requires exactly this set, so a required row-identity, shared-input, or
# scientific gate cannot disappear — and an unreviewed extra metric cannot
# appear — without a deliberate change here and in the packaged JSON Schema.
REQUIRED_METRIC_NAMES: Mapping[str, frozenset[str]] = {
    "pupil_mask_and_throughput": frozenset(
        (
            "mask_round_trip_identical",
            "illuminated_sample_count",
            "native_mean_window_capture",
            "hcipy_mean_window_capture",
        )
    ),
    "zernike_modes": frozenset(
        (
            "tip_x_alignment_defect",
            "tip_x_relative_sign",
            "tip_y_alignment_defect",
            "tip_y_relative_sign",
            "defocus_alignment_defect",
            "defocus_relative_sign",
            "astig_45_alignment_defect",
            "astig_45_relative_sign",
            "astig_0_alignment_defect",
            "astig_0_relative_sign",
        )
    ),
    "atmosphere_statistics": frozenset(
        (
            "rms_ratio_hcipy_over_native",
            "native_structure_function_lag_ratio",
            "hcipy_structure_function_lag_ratio",
            "rms_ratio_standard_error",
            "native_structure_function_ratio_standard_error",
            "hcipy_structure_function_ratio_standard_error",
        )
    ),
    "wfs_tip_tilt_response": frozenset(
        (
            "native_x_response_sign",
            "hcipy_x_response_sign",
            "native_cross_axis_fraction",
            "hcipy_cross_axis_fraction",
            "native_tilt_gain",
            "hcipy_tilt_gain",
            "tilt_gain_ratio_hcipy_over_native",
            "y_gain_ratio_hcipy_over_native",
        )
    ),
    "lenslet_spot_morphology": frozenset(
        (
            "native_ee50_over_diffraction",
            "hcipy_ee50_over_diffraction",
            "ee50_ratio_hcipy_over_native",
            "centroid_gain_ratio_hcipy_over_native",
        )
    ),
    "dm_single_actuator_influence": frozenset(
        (
            "actuator_ids_identical",
            "max_in_pupil_influence_abs_diff",
            "max_in_pupil_command_surface_abs_diff_m",
        )
    ),
    "dm_static_fitting": frozenset(
        (
            "native_fitting_residual_fraction",
            "fitting_residual_relative_difference",
        )
    ),
    "interaction_matrix_identity": frozenset(
        (
            "matrix_shapes_identical",
            "row_ids_identical",
            "coordinate_ids_identical",
            "rank_difference",
        )
    ),
    "normalized_singular_spectrum": frozenset(
        (
            "spectrum_length_difference",
            "max_normalized_sigma_abs_diff",
        )
    ),
    "psf_normalization": frozenset(
        (
            "native_total_flux_error",
            "hcipy_total_flux_error",
        )
    ),
    "strehl_ratio": frozenset(
        (
            "native_strehl",
            "hcipy_strehl",
            "strehl_abs_difference",
        )
    ),
    "closed_loop_residual": frozenset(
        (
            "executed_time_grid_matches_shared_fixture",
            "both_loops_consumed_shared_opd_cube",
            "native_backend_name",
            "hcipy_backend_name",
            "native_correction_effect",
            "hcipy_correction_effect",
            "mean_residual_ratio_hcipy_over_native",
        )
    ),
    "runtime_and_memory": frozenset(
        (
            "native_wfs_propagation_s",
            "hcipy_wfs_propagation_s",
            "native_psf_propagation_s",
            "hcipy_psf_propagation_s",
            "comparison_peak_traced_memory_mb",
        )
    ),
}

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
    "CROSS_BACKEND_BASELINE_SCHEMA_RESOURCE",
    "COMPARISON_LEVELS",
    "REQUIRED_COMPARISON_KINDS",
    "REQUIRED_COMPONENT_HASH_KEYS",
    "REQUIRED_FIXTURE_HASH_KEYS",
    "REQUIRED_METRIC_NAMES",
    "BaselineContractError",
    "validate_cross_backend_report",
    "validate_cross_backend_baseline",
    "validate_baseline_against_schema",
    "baseline_from_report",
    "load_cross_backend_baseline",
    "evaluate_report_against_baseline",
    "format_metric_failure",
)


class BaselineContractError(ValueError):
    """Raised when a report or baseline document violates the contract."""


def validate_cross_backend_report(document: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate the shared report body: identity, hashes, and metrics.

    A valid document covers every kind in :data:`REQUIRED_COMPARISON_KINDS`
    exactly once, in canonical order: one run of the comparison suite always
    produces the complete AO-REF-018 inventory, and an accepted baseline that
    silently dropped a comparison would stop gating it.  Every gating
    criterion must carry finite numerics — a non-negative absolute tolerance
    or an ordered range — so a malformed tolerance can never widen into an
    always-passing gate.
    """

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
            if not isinstance(value, str) or not _CONTENT_HASH_64.fullmatch(value):
                raise BaselineContractError(
                    f"{group}[{key!r}] must be a 64-character lowercase "
                    "hexadecimal content hash."
                )
        # A required row-identity, actuator-identity, or shared-input hash
        # cannot silently disappear, and an unreviewed extra one cannot
        # appear: the recorded keys must be exactly the AO-REF-018 inventory.
        required_keys = _REQUIRED_HASH_KEYS[group]
        if set(hashes) != set(required_keys):
            missing = sorted(set(required_keys) - set(hashes))
            unexpected = sorted(set(hashes) - set(required_keys))
            raise BaselineContractError(
                f"{group} must record exactly the required keys; "
                f"missing={missing}, unexpected={unexpected}."
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
    kinds: list[str] = []
    for comparison in comparisons:
        _validate_comparison(comparison)
        kind = comparison["comparison_kind"]
        if kind in seen_kinds:
            raise BaselineContractError(
                f"duplicate comparison_kind {kind!r} in document."
            )
        seen_kinds.add(kind)
        kinds.append(kind)
    if tuple(kinds) != REQUIRED_COMPARISON_KINDS:
        missing = [kind for kind in REQUIRED_COMPARISON_KINDS if kind not in seen_kinds]
        unexpected = [kind for kind in kinds if kind not in REQUIRED_COMPARISON_KINDS]
        raise BaselineContractError(
            "comparisons must cover the required comparison kinds in "
            f"canonical order; missing={missing}, unexpected={unexpected}, "
            f"observed={kinds}."
        )
    # Each comparison must record exactly its complete metric inventory, so a
    # scientific gate cannot be dropped and an unreviewed metric cannot appear
    # without a deliberate change to REQUIRED_METRIC_NAMES and the schema.
    for comparison in comparisons:
        kind = comparison["comparison_kind"]
        names = {metric["name"] for metric in comparison["metrics"]}
        required_names = REQUIRED_METRIC_NAMES[kind]
        if names != required_names:
            missing = sorted(required_names - names)
            unexpected = sorted(names - required_names)
            raise BaselineContractError(
                f"comparison {kind!r} must record exactly its required "
                f"metrics; missing={missing}, unexpected={unexpected}."
            )
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
    # Provenance must be verifiable, not forgeable: a failed or "unknown"
    # commit lookup is rejected, and the clean-state field must be present so
    # a dirty-tree baseline cannot masquerade as a reproducible one.
    source_commit = document["generator"]["source_commit"]
    if not _SOURCE_COMMIT_40.fullmatch(str(source_commit)):
        raise BaselineContractError(
            "generator.source_commit must be a 40-character lowercase git "
            f"commit hash; got {source_commit!r}."
        )
    if not isinstance(document["generator"].get("source_tree_clean"), bool):
        raise BaselineContractError(
            "generator.source_tree_clean must be recorded as a boolean."
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
            criterion = metric["pass_criterion"]
            criterion_type = criterion["type"]
            if criterion_type in ("abs_tolerance", "range") and not (
                _finite_number(metric["value"])
            ):
                raise BaselineContractError(
                    f"baseline metric {metric['name']!r} in comparison "
                    f"{comparison['comparison_kind']!r} carries a numeric "
                    "criterion, so its recorded value must be a finite "
                    "number."
                )
            # An exact metric's recorded value is the expectation it gates on,
            # so the two must agree; otherwise the baseline could record one
            # value and gate on another.
            if criterion_type == "equals" and criterion["expected"] != metric["value"]:
                raise BaselineContractError(
                    f"baseline metric {metric['name']!r} in comparison "
                    f"{comparison['comparison_kind']!r} gates on equality, so "
                    "its recorded value must equal the criterion expectation."
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


def validate_baseline_against_schema(document: Mapping[str, Any]) -> None:
    """Validate a document against the packaged JSON Schema.

    The custom validators enforce the semantic contract; the JSON Schema is
    the independent structural gate the acceptance workflow must also pass, so
    a required field, hash key, or metric cannot disappear without a
    deliberate, versioned schema change.  ``jsonschema`` is a development and
    validation dependency, imported lazily so importing this module never
    requires it.
    """

    try:
        import jsonschema
    except ModuleNotFoundError as exc:  # pragma: no cover - dev dependency
        raise BaselineContractError(
            "jsonschema is required to validate against the packaged schema; "
            "install the test or validation dependency profile."
        ) from exc
    try:
        schema_text = read_text_resource(CROSS_BACKEND_BASELINE_SCHEMA_RESOURCE)
    except (FileNotFoundError, KeyError, ValueError) as exc:
        raise BaselineContractError(
            f"cannot load packaged schema "
            f"{CROSS_BACKEND_BASELINE_SCHEMA_RESOURCE!r}: {exc}"
        ) from exc
    schema = json.loads(schema_text)
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        location = "/".join(str(part) for part in first.path) or "<root>"
        raise BaselineContractError(
            f"document violates the packaged JSON Schema at {location}: "
            f"{first.message}"
        )


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
                # Report the same complete context a value violation would —
                # the expected value or range, tolerance, units, and hashes —
                # so a missing gate is as debuggable as a failed one.
                failures.append(
                    format_metric_failure(
                        kind,
                        metric,
                        "<absent: missing from the fresh report>",
                        hash_context=hash_context,
                    )
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
        if criterion["type"] == "abs_tolerance":
            if "expected" not in criterion or "tolerance" not in criterion:
                raise BaselineContractError(
                    f"metric {metric['name']!r} abs_tolerance criterion needs "
                    "expected and tolerance."
                )
            if not _finite_number(criterion["expected"]):
                raise BaselineContractError(
                    f"metric {metric['name']!r} abs_tolerance expected value "
                    "must be a finite number."
                )
            if (
                not _finite_number(criterion["tolerance"])
                or float(criterion["tolerance"]) < 0.0
            ):
                raise BaselineContractError(
                    f"metric {metric['name']!r} tolerance must be a finite "
                    "non-negative number."
                )
        if criterion["type"] == "range":
            if "low" not in criterion or "high" not in criterion:
                raise BaselineContractError(
                    f"metric {metric['name']!r} range criterion needs low and "
                    "high."
                )
            if not _finite_number(criterion["low"]) or not _finite_number(
                criterion["high"]
            ):
                raise BaselineContractError(
                    f"metric {metric['name']!r} range bounds must be finite "
                    "numbers."
                )
            if float(criterion["low"]) > float(criterion["high"]):
                raise BaselineContractError(
                    f"metric {metric['name']!r} range low must not exceed "
                    "high."
                )
        if criterion["type"] == "equals":
            if "expected" not in criterion:
                raise BaselineContractError(
                    f"metric {metric['name']!r} equals criterion needs "
                    "expected."
                )
            expected = criterion["expected"]
            if (
                isinstance(expected, Real)
                and not isinstance(expected, bool)
                and not math.isfinite(float(expected))
            ):
                raise BaselineContractError(
                    f"metric {metric['name']!r} equals expectation must be "
                    "finite."
                )
        if (metric["level"] == "informational") != (
            criterion["type"] == "informational"
        ):
            raise BaselineContractError(
                f"metric {metric['name']!r} level and criterion type must "
                "agree on informational status."
            )
        # An exact metric must gate on equality, never on a tolerance or a
        # range that a later edit could widen into an always-passing check.
        if metric["level"] == "exact" and criterion["type"] != "equals":
            raise BaselineContractError(
                f"metric {metric['name']!r} is exact, so its pass_criterion "
                f"must be 'equals', not {criterion['type']!r}."
            )
        if metric["name"] in seen_names:
            raise BaselineContractError(
                f"duplicate metric name {metric['name']!r} in comparison "
                f"{comparison['comparison_kind']!r}."
            )
        seen_names.add(metric["name"])


def _finite_number(value: object) -> bool:
    return (
        isinstance(value, Real)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _metric_index(
    report: Mapping[str, Any],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    index: dict[tuple[str, str], Mapping[str, Any]] = {}
    for comparison in report["comparisons"]:
        for metric in comparison["metrics"]:
            index[(comparison["comparison_kind"], metric["name"])] = metric
    return index


def _hash_context(document: Mapping[str, Any]) -> str:
    # Full, untruncated hashes for every compared input and component: a
    # failure message must let a reader confirm exactly which configuration,
    # shared fixtures, and component identities the comparison ran against.
    config_hash = str(document["comparison_config"]["config_hash"])

    def _render(group: str) -> str:
        return ",".join(
            f"{key}={value}" for key, value in sorted(document[group].items())
        )

    return (
        f"config_hash={config_hash} "
        f"components[{_render('component_hashes')}] "
        f"fixtures[{_render('fixture_hashes')}]"
    )


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
