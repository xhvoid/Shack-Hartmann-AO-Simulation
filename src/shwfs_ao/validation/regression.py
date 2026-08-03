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
from typing import Any, Mapping, cast

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
# The atmosphere comparison is the estimated one: its ratios are averages over
# independent realizations, so its recorded values mean nothing without the
# estimator and uncertainty definition behind them.  The packaged JSON Schema
# requires that prose; the application validator must require it too, or the
# acceptance workflow — the only writer of a baseline — could drop it and still
# satisfy every custom check.
COMPARISONS_REQUIRING_STATISTICAL_DEFINITION = frozenset({"atmosphere_statistics"})
# Metrics whose recorded value is a measured magnitude, so a negative one is
# not a small error but a value of a kind the metric cannot take.  These are all
# informational, which is precisely why the rule is needed: their values are
# never gated, so nothing else would notice a standard error of -1.0 sitting
# under the ratios it is supposed to qualify.
NONNEGATIVE_METRIC_VALUES: Mapping[str, frozenset[str]] = {
    "atmosphere_statistics": frozenset(
        (
            "rms_ratio_standard_error",
            "native_structure_function_ratio_standard_error",
            "hcipy_structure_function_ratio_standard_error",
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

# Sentinel: this metric's criterion expectation is a reviewed physical value or
# a configuration-derived count that legitimately differs between baselines, so
# only its level, units, and criterion type are pinned; the numeric expectation
# is checked against the accepted baseline itself, not against a universal.
_BASELINE_SPECIFIC = object()

# The canonical scientific meaning of every metric, pinned independently of any
# single baseline document.  Enforcing (level, units, criterion type) forbids a
# gate from being silently demoted (an exact identity recorded as a wide range,
# a correctness gate recorded as informational, or a runtime measurement
# promoted into a gate), and pinning the expectation of the universal-constant
# equality metrics (booleans, +1 signs, backend identifiers, structural zeros)
# forbids gating on the wrong side of an identity — e.g. accepting
# ``both_loops_consumed_shared_opd_cube`` with expected ``False``.  The JSON
# Schema mirrors these constraints for defence in depth.
METRIC_CONTRACT: Mapping[str, Mapping[str, tuple[str, str, str, object]]] = {
    'pupil_mask_and_throughput': {
        'mask_round_trip_identical': ('exact', 'boolean', 'equals', True),
        'illuminated_sample_count': ('exact', 'samples', 'equals', _BASELINE_SPECIFIC),
        'native_mean_window_capture': ('tight_numerical', 'fraction', 'abs_tolerance', _BASELINE_SPECIFIC),
        'hcipy_mean_window_capture': ('physical_tolerance', 'fraction', 'range', _BASELINE_SPECIFIC),
    },
    'zernike_modes': {
        'tip_x_alignment_defect': ('tight_numerical', '1 - |correlation|', 'abs_tolerance', _BASELINE_SPECIFIC),
        'tip_x_relative_sign': ('exact', 'sign', 'equals', 1),
        'tip_y_alignment_defect': ('tight_numerical', '1 - |correlation|', 'abs_tolerance', _BASELINE_SPECIFIC),
        'tip_y_relative_sign': ('exact', 'sign', 'equals', 1),
        'defocus_alignment_defect': ('tight_numerical', '1 - |correlation|', 'abs_tolerance', _BASELINE_SPECIFIC),
        'defocus_relative_sign': ('exact', 'sign', 'equals', 1),
        'astig_45_alignment_defect': ('tight_numerical', '1 - |correlation|', 'abs_tolerance', _BASELINE_SPECIFIC),
        'astig_45_relative_sign': ('exact', 'sign', 'equals', 1),
        'astig_0_alignment_defect': ('tight_numerical', '1 - |correlation|', 'abs_tolerance', _BASELINE_SPECIFIC),
        'astig_0_relative_sign': ('exact', 'sign', 'equals', 1),
    },
    'atmosphere_statistics': {
        'rms_ratio_hcipy_over_native': ('physical_tolerance', 'ratio', 'range', _BASELINE_SPECIFIC),
        'native_structure_function_lag_ratio': ('physical_tolerance', 'ratio', 'range', _BASELINE_SPECIFIC),
        'hcipy_structure_function_lag_ratio': ('physical_tolerance', 'ratio', 'range', _BASELINE_SPECIFIC),
        'rms_ratio_standard_error': ('informational', 'ratio', 'informational', _BASELINE_SPECIFIC),
        'native_structure_function_ratio_standard_error': ('informational', 'ratio', 'informational', _BASELINE_SPECIFIC),
        'hcipy_structure_function_ratio_standard_error': ('informational', 'ratio', 'informational', _BASELINE_SPECIFIC),
    },
    'wfs_tip_tilt_response': {
        'native_x_response_sign': ('tight_numerical', 'sign', 'equals', 1),
        'hcipy_x_response_sign': ('tight_numerical', 'sign', 'equals', 1),
        'native_cross_axis_fraction': ('tight_numerical', 'fraction of applied tilt', 'abs_tolerance', _BASELINE_SPECIFIC),
        'hcipy_cross_axis_fraction': ('tight_numerical', 'fraction of applied tilt', 'abs_tolerance', _BASELINE_SPECIFIC),
        'native_tilt_gain': ('physical_tolerance', 'measured over applied angular displacement', 'range', _BASELINE_SPECIFIC),
        'hcipy_tilt_gain': ('physical_tolerance', 'measured over applied angular displacement', 'range', _BASELINE_SPECIFIC),
        'tilt_gain_ratio_hcipy_over_native': ('physical_tolerance', 'ratio', 'range', _BASELINE_SPECIFIC),
        'y_gain_ratio_hcipy_over_native': ('physical_tolerance', 'ratio', 'range', _BASELINE_SPECIFIC),
    },
    'lenslet_spot_morphology': {
        'native_ee50_over_diffraction': ('physical_tolerance', 'ratio of lambda/d', 'range', _BASELINE_SPECIFIC),
        'hcipy_ee50_over_diffraction': ('physical_tolerance', 'ratio of lambda/d', 'range', _BASELINE_SPECIFIC),
        'ee50_ratio_hcipy_over_native': ('physical_tolerance', 'ratio', 'range', _BASELINE_SPECIFIC),
        'centroid_gain_ratio_hcipy_over_native': ('physical_tolerance', 'ratio', 'range', _BASELINE_SPECIFIC),
    },
    'dm_single_actuator_influence': {
        'actuator_ids_identical': ('exact', 'boolean', 'equals', True),
        'max_in_pupil_influence_abs_diff': ('tight_numerical', 'unit-peak influence', 'abs_tolerance', _BASELINE_SPECIFIC),
        'max_in_pupil_command_surface_abs_diff_m': ('tight_numerical', 'm_opd', 'abs_tolerance', _BASELINE_SPECIFIC),
    },
    'dm_static_fitting': {
        'native_fitting_residual_fraction': ('physical_tolerance', 'residual rms / target rms', 'range', _BASELINE_SPECIFIC),
        'fitting_residual_relative_difference': ('tight_numerical', 'relative difference', 'abs_tolerance', _BASELINE_SPECIFIC),
    },
    'interaction_matrix_identity': {
        'matrix_shapes_identical': ('exact', 'boolean', 'equals', True),
        'row_ids_identical': ('exact', 'boolean', 'equals', True),
        'coordinate_ids_identical': ('exact', 'boolean', 'equals', True),
        'rank_difference': ('exact', 'rank', 'equals', 0),
    },
    'normalized_singular_spectrum': {
        'spectrum_length_difference': ('exact', 'count', 'equals', 0),
        'max_normalized_sigma_abs_diff': ('physical_tolerance', 'normalized sigma', 'abs_tolerance', _BASELINE_SPECIFIC),
    },
    'psf_normalization': {
        'native_total_flux_error': ('tight_numerical', 'flux', 'abs_tolerance', _BASELINE_SPECIFIC),
        'hcipy_total_flux_error': ('tight_numerical', 'flux', 'abs_tolerance', _BASELINE_SPECIFIC),
    },
    'strehl_ratio': {
        'native_strehl': ('physical_tolerance', 'Strehl', 'abs_tolerance', _BASELINE_SPECIFIC),
        'hcipy_strehl': ('physical_tolerance', 'Strehl', 'abs_tolerance', _BASELINE_SPECIFIC),
        'strehl_abs_difference': ('physical_tolerance', 'Strehl', 'abs_tolerance', _BASELINE_SPECIFIC),
    },
    'closed_loop_residual': {
        'executed_time_grid_matches_shared_fixture': ('exact', 'boolean', 'equals', True),
        'both_loops_consumed_shared_opd_cube': ('exact', 'boolean', 'equals', True),
        'native_backend_name': ('exact', 'identifier', 'equals', 'native'),
        'hcipy_backend_name': ('exact', 'identifier', 'equals', 'hcipy'),
        'native_correction_effect': ('physical_tolerance', 'mean corrected over uncorrected rms', 'range', _BASELINE_SPECIFIC),
        'hcipy_correction_effect': ('physical_tolerance', 'mean corrected over uncorrected rms', 'range', _BASELINE_SPECIFIC),
        'mean_residual_ratio_hcipy_over_native': ('physical_tolerance', 'ratio', 'range', _BASELINE_SPECIFIC),
    },
    'runtime_and_memory': {
        'native_wfs_propagation_s': ('informational', 'seconds', 'informational', _BASELINE_SPECIFIC),
        'hcipy_wfs_propagation_s': ('informational', 'seconds', 'informational', _BASELINE_SPECIFIC),
        'native_psf_propagation_s': ('informational', 'seconds', 'informational', _BASELINE_SPECIFIC),
        'hcipy_psf_propagation_s': ('informational', 'seconds', 'informational', _BASELINE_SPECIFIC),
        'comparison_peak_traced_memory_mb': ('informational', 'mebibytes', 'informational', _BASELINE_SPECIFIC),
    },
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
    "COMPARISONS_REQUIRING_STATISTICAL_DEFINITION",
    "NONNEGATIVE_METRIC_VALUES",
    "METRIC_CONTRACT",
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


def _validate_report_structure(
    document: Mapping[str, Any],
) -> tuple[list[Any], list[str]]:
    """Validate the shared report body: identity, hashes, and metric shape.

    This enforces everything except inventory completeness (which comparison
    kinds and metric names appear).  Every present metric must satisfy its
    structural contract and its pinned scientific meaning
    (:data:`METRIC_CONTRACT`), every gating criterion must carry finite numerics
    — a non-negative absolute tolerance or an ordered range — so a malformed
    tolerance can never widen into an always-passing gate, and every hash and
    convention field must be well formed.  It is shared by
    :func:`validate_cross_backend_report`, which additionally requires the
    complete inventory, and by :func:`evaluate_report_against_baseline`, which
    must surface a report missing a gate as a rich per-metric failure rather
    than a terse inventory rejection.  Returns ``(comparisons, kinds)``.
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
    # ``type`` rather than ``==`` alone: ``True`` equals 1 in Python, so a
    # document whose version field is a boolean would otherwise be read as
    # version 1 and validated against a contract it never declared.
    if (
        type(document["artifact_schema_version"]) is not int
        or document["artifact_schema_version"]
        != CROSS_BACKEND_BASELINE_SCHEMA_VERSION
    ):
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
    return comparisons, kinds


def validate_cross_backend_report(document: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate the shared report body and require the complete inventory.

    In addition to the structural contract enforced by
    :func:`_validate_report_structure`, a full report must cover every kind in
    :data:`REQUIRED_COMPARISON_KINDS` exactly once, in canonical order, and each
    comparison must record exactly its complete metric inventory: one run of the
    suite always produces the full AO-REF-018 inventory, and an accepted
    baseline that silently dropped a comparison would stop gating it.
    """

    comparisons, kinds = _validate_report_structure(document)
    if tuple(kinds) != REQUIRED_COMPARISON_KINDS:
        missing = [kind for kind in REQUIRED_COMPARISON_KINDS if kind not in kinds]
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
    # Provenance must be verifiable, not forgeable.  The commit must be a real
    # 40-character hash — its existence is verified at generation time, which is
    # the only place the source repository is available; the installed package
    # that runs this validator has no repository to re-check against.  The
    # clean-state flag must be present, and — closing the dirty-tree hole — a
    # tree recorded as dirty must carry the source_patch_sha256 evidence hash of
    # exactly what diverged from the commit (tracked diff plus sorted untracked
    # scientific inputs), so a dirty baseline cannot masquerade as reproducible.
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
    source_patch = document["generator"].get("source_patch_sha256")
    if document["generator"]["source_tree_clean"] is False:
        if not isinstance(source_patch, str) or not _CONTENT_HASH_64.fullmatch(
            source_patch
        ):
            raise BaselineContractError(
                "generator.source_patch_sha256 must be the 64-character content "
                "hash of the working-tree divergence when source_tree_clean is "
                "false; a dirty baseline requires patch evidence."
            )
    elif source_patch is not None:
        # A clean tree has nothing that diverged from the recorded commit, so
        # there is no divergence to hash.  Recording both says the baseline was
        # generated from an unmodified checkout *and* from something else; one
        # of the two claims is false and the document cannot say which, so the
        # combination is rejected rather than silently believed.
        raise BaselineContractError(
            "generator.source_patch_sha256 must be null or absent when "
            f"source_tree_clean is true; got {source_patch!r}. A clean tree "
            "has no working-tree divergence to record."
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
            # so the two must agree in kind as well as in value; otherwise the
            # baseline could record one value and gate on another, or record a
            # boolean flag where the gate expects a count.
            if criterion_type == "equals" and not _same_value(
                criterion["expected"], metric["value"]
            ):
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

    An empty tuple means every gating criterion passed *and* every metric the
    baseline records is present in the report — including the informational
    ones, whose values never gate but whose absence would quietly remove the
    evidence the gated values are read against.  Every failure names the
    observed value, the expected value or range, the tolerance with its units,
    and the compared configuration/fixture hashes.
    """

    # The baseline is fully validated (it is the authority), but the report is
    # only validated structurally: a fresh run that is missing a gated metric
    # must surface as a rich per-metric failure below, not as a terse inventory
    # rejection here.  Every present report metric still has to satisfy its
    # pinned structural contract, so a mutated level/units/criterion is still
    # rejected.
    _validate_report_structure(report)
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
    # The measurement conventions and the root seed are part of the comparison
    # basis just as much as the hashes: a report measured under a different
    # command/residual/detector-sign convention, or from a different seed, is
    # not comparable to the baseline even when its config_hash and metric values
    # coincide, so its tolerances do not apply.
    baseline_conventions = baseline["conventions"]
    report_conventions = report.get("conventions")
    if not isinstance(report_conventions, Mapping):
        report_conventions = {}
    for field in sorted(baseline_conventions):
        observed = report_conventions.get(field)
        expected = baseline_conventions[field]
        if observed != expected:
            failures.append(
                f"conventions[{field!r}] mismatch: observed={observed!r} "
                f"expected={expected!r}; the comparison basis differs, so "
                "metric tolerances do not apply."
            )
    if report.get("root_seed") != baseline.get("root_seed"):
        failures.append(
            f"root_seed mismatch: observed={report.get('root_seed')!r} "
            f"expected={baseline.get('root_seed')!r}; a different seed yields a "
            "different realization, so metric tolerances do not apply."
        )
    # An estimated comparison reports averages over realizations, so its numbers
    # only mean what its estimator and uncertainty definition say they mean.  A
    # report that estimated them differently is not comparable to the baseline
    # even when every value lands inside the recorded range: the ranges were
    # reviewed against one definition, and nothing else in this document would
    # reveal that the fresh run used another.
    reported_kinds = {
        comparison["comparison_kind"] for comparison in report["comparisons"]
    }
    for comparison in baseline["comparisons"]:
        kind = comparison["comparison_kind"]
        if kind not in COMPARISONS_REQUIRING_STATISTICAL_DEFINITION:
            continue
        # A comparison the report does not contain at all is reported below,
        # metric by metric, with the full context of what is missing.  Failing
        # here on its absent definition would short-circuit that and leave the
        # reader with one terse line instead.
        if kind not in reported_kinds:
            continue
        expected = comparison.get("statistical_definition")
        observed = _statistical_definition(report, kind)
        if observed != expected:
            failures.append(
                f"comparisons[{kind!r}].statistical_definition mismatch: "
                f"observed={observed!r} expected={expected!r}; the estimator or "
                "its uncertainty changed, so the reviewed tolerances were not "
                "set against these numbers."
            )
    if failures:
        return tuple(failures)

    report_metrics = _metric_index(report)
    for comparison in baseline["comparisons"]:
        kind = comparison["comparison_kind"]
        for metric in comparison["metrics"]:
            name = metric["name"]
            criterion = metric["pass_criterion"]
            observed_entry = report_metrics.get((kind, name))
            # Presence is checked before the criterion type, because an
            # informational metric is required *evidence* even though its value
            # never gates: the standard errors that qualify the atmosphere
            # ratios, and the runtime and memory measurements, are the reason a
            # reader can interpret the gated numbers at all.  Skipping them
            # first would let a report drop every informational metric — or the
            # whole runtime comparison — and still evaluate clean.
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
            if criterion["type"] == "informational":
                continue
            failure = _evaluate_metric(
                kind,
                metric,
                observed_entry["value"],
                hash_context=hash_context,
            )
            if failure is not None:
                failures.append(failure)
    failures.extend(_inventory_failures(report, baseline))
    return tuple(failures)


def _statistical_definition(document: Mapping[str, Any], kind: str) -> Any:
    for comparison in document["comparisons"]:
        if comparison["comparison_kind"] == kind:
            return comparison.get("statistical_definition")
    return None


def _inventory_failures(
    report: Mapping[str, Any],
    baseline: Mapping[str, Any],
) -> list[str]:
    """Failures for evidence the baseline does not account for.

    The per-metric loop above walks the *baseline's* inventory, so on its own it
    only ever notices what a report is missing.  Everything a report adds — an
    extra comparison, an extra metric, or the same comparisons in a different
    order — passes it untouched, which is how an unreviewed measurement, or a
    report assembled from a different suite, can evaluate clean.  A baseline
    gates what it was reviewed against, so anything else in the document is
    reported here rather than silently ignored.

    Order is part of it: the canonical order is what
    :func:`validate_cross_backend_report` requires of both documents, so a
    report whose comparisons are shuffled did not come from a run of this suite.

    Absence is deliberately *not* reported here.  Every metric the baseline
    records is already surfaced above with its full expected value, tolerance,
    units, and hashes, and repeating it as a terse inventory line would only
    bury that.
    """

    failures: list[str] = []
    baseline_kinds = [
        comparison["comparison_kind"] for comparison in baseline["comparisons"]
    ]
    report_kinds = [
        comparison["comparison_kind"] for comparison in report["comparisons"]
    ]
    unexpected_kinds = [kind for kind in report_kinds if kind not in set(baseline_kinds)]
    if unexpected_kinds:
        failures.append(
            f"comparisons the baseline does not record: {unexpected_kinds}. An "
            "unreviewed comparison cannot be presented as covered by an "
            "accepted baseline."
        )
    shared_report_order = [kind for kind in report_kinds if kind in set(baseline_kinds)]
    shared_baseline_order = [
        kind for kind in baseline_kinds if kind in set(report_kinds)
    ]
    if shared_report_order != shared_baseline_order:
        failures.append(
            f"comparisons are out of canonical order: observed="
            f"{shared_report_order} expected={shared_baseline_order}; one run "
            "of the suite always emits them in the order the baseline records."
        )
    baseline_metrics = {
        comparison["comparison_kind"]: {
            metric["name"] for metric in comparison["metrics"]
        }
        for comparison in baseline["comparisons"]
    }
    for comparison in report["comparisons"]:
        kind = comparison["comparison_kind"]
        reviewed = baseline_metrics.get(kind)
        if reviewed is None:
            continue
        unexpected = sorted(
            {metric["name"] for metric in comparison["metrics"]} - reviewed
        )
        if unexpected:
            failures.append(
                f"comparison {kind!r} reports metrics the baseline does not "
                f"record: {unexpected}. An unreviewed measurement cannot be "
                "presented as covered by an accepted baseline."
            )
    return failures


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
    # A numeric gate must see a number.  ``bool`` is a Python ``Real``, so an
    # observation reported as ``True`` would otherwise be measured as 1.0 and
    # could satisfy a Strehl or residual tolerance it never met.
    if kind == "equals":
        if _same_value(observed, criterion["expected"]):
            return None
    elif kind == "abs_tolerance":
        if (
            _finite_number(observed)
            and abs(float(cast(float, observed)) - float(criterion["expected"]))
            <= float(criterion["tolerance"])
        ):
            return None
    elif kind == "range":
        if (
            _finite_number(observed)
            and float(criterion["low"])
            <= float(cast(float, observed))
            <= float(criterion["high"])
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
    if comparison["comparison_kind"] in COMPARISONS_REQUIRING_STATISTICAL_DEFINITION:
        definition = comparison.get("statistical_definition")
        if not isinstance(definition, str) or not definition.strip():
            raise BaselineContractError(
                f"comparison {comparison['comparison_kind']!r} is estimated "
                "from repeated realizations, so it must record its "
                "statistical_definition: the estimator and the uncertainty "
                "behind every value it reports."
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
        # An informational metric's value never gates, but it is still a
        # measurement: a runtime in seconds, a peak memory, a standard error.
        # Requiring it to be a finite number is what makes it evidence rather
        # than a slot that can be filled with prose — and it is what the
        # packaged JSON Schema already requires of it.
        if criterion["type"] == "informational" and not _finite_number(metric["value"]):
            raise BaselineContractError(
                f"metric {metric['name']!r} is informational, so its recorded "
                "value must still be a finite number: it is the measurement "
                f"the gated values are read against, not a label. Got "
                f"{metric['value']!r}."
            )
        # An exact metric must gate on equality, never on a tolerance or a
        # range that a later edit could widen into an always-passing check.
        if metric["level"] == "exact" and criterion["type"] != "equals":
            raise BaselineContractError(
                f"metric {metric['name']!r} is exact, so its pass_criterion "
                f"must be 'equals', not {criterion['type']!r}."
            )
        if metric["name"] in NONNEGATIVE_METRIC_VALUES.get(
            comparison["comparison_kind"], frozenset()
        ) and (not _finite_number(metric["value"]) or float(metric["value"]) < 0.0):
            raise BaselineContractError(
                f"metric {metric['name']!r} in comparison "
                f"{comparison['comparison_kind']!r} records a measured "
                "magnitude, so its value must be a finite non-negative number; "
                f"got {metric['value']!r}."
            )
        if metric["name"] in seen_names:
            raise BaselineContractError(
                f"duplicate metric name {metric['name']!r} in comparison "
                f"{comparison['comparison_kind']!r}."
            )
        seen_names.add(metric["name"])
        _enforce_metric_contract(comparison["comparison_kind"], metric)


def _enforce_metric_contract(kind: str, metric: Mapping[str, Any]) -> None:
    """Pin a present metric's scientific meaning to :data:`METRIC_CONTRACT`.

    Unknown ``(kind, name)`` pairs are left to the inventory check in
    :func:`validate_cross_backend_report`; this guards only the meaning of the
    metrics the contract knows about, so no gate can be silently demoted, no
    runtime measurement promoted, and no identity gated on the wrong value.
    """

    contract = METRIC_CONTRACT.get(kind, {}).get(metric["name"])
    if contract is None:
        return
    level, units, criterion_type, expected = contract
    name = metric["name"]
    if metric["level"] != level:
        raise BaselineContractError(
            f"metric {name!r} in comparison {kind!r} must be recorded at its "
            f"pinned level {level!r}, not {metric['level']!r}."
        )
    if metric.get("units") != units:
        raise BaselineContractError(
            f"metric {name!r} in comparison {kind!r} must record its pinned "
            f"units {units!r}, not {metric.get('units')!r}."
        )
    criterion = metric["pass_criterion"]
    if criterion.get("type") != criterion_type:
        raise BaselineContractError(
            f"metric {name!r} in comparison {kind!r} must gate with its pinned "
            f"{criterion_type!r} criterion, not {criterion.get('type')!r}."
        )
    if expected is not _BASELINE_SPECIFIC:
        actual = criterion.get("expected")
        # ``type`` distinguishes True from 1 and False from 0 so a boolean gate
        # cannot be silently satisfied by an integer expectation or vice versa.
        if type(actual) is not type(expected) or actual != expected:
            raise BaselineContractError(
                f"metric {name!r} in comparison {kind!r} must gate on its "
                f"canonical expectation {expected!r}, not {actual!r}."
            )


def _finite_number(value: object) -> bool:
    return (
        isinstance(value, Real)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _value_kind(value: object) -> str | None:
    """Classify a metric value, or ``None`` if it is not a comparable scalar.

    Testing ``isinstance(value, bool)`` is not enough to recognise a flag:
    NumPy's ``bool_`` is *not* a Python ``bool``, yet it compares equal to 0 and
    1, so it would satisfy a numeric gate while failing a boolean one — the
    kind check exactly inverted.  A NumPy scalar advertises its kind through
    ``dtype.kind``, which is ``'b'`` for booleans, so it is read here rather
    than importing NumPy into a module that does not otherwise need it.
    """

    if isinstance(value, bool) or getattr(getattr(value, "dtype", None), "kind", None) == "b":
        return "flag"
    if isinstance(value, Real):
        return "number"
    if isinstance(value, str):
        return "text"
    return None


def _same_value(left: object, right: object) -> bool:
    """Equality that never lets a flag stand in for a number, or the reverse.

    ``bool`` is a subclass of ``int``, so plain ``==`` accepts ``False`` where a
    baseline expects ``0`` and ``1`` where it expects ``True``.  A metric's kind
    is part of its meaning here — ``rank_difference`` is a count, and a
    shared-cube consumption flag is a flag — so the two must agree in kind
    before they can agree in value.  Widths stay interchangeable within a kind:
    an integer-valued measurement serialized as ``4.0`` still equals ``4``, and
    a NumPy scalar is the same kind of thing as the Python scalar it wraps.
    A value of no recognised kind never compares equal, so an object with a
    permissive ``__eq__`` cannot satisfy a gate by asserting that it does.
    """

    kind = _value_kind(left)
    if kind is None or kind != _value_kind(right):
        return False
    return bool(left == right)


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
