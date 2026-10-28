"""AO-REF-018 contracts for the cross-backend validation package.

These tests are deliberately unmarked: they run in the native CI selection
and need no optional dependency.  They pin the backend-neutral physical
estimators, the report/baseline document contract, the integrity of the
packaged baseline, the evaluation semantics, and the completeness of every
failure message (observed value, expected value or range, tolerance with
units, and the compared hashes).  The ``hcipy`` marker stays reserved for
tests that execute the suite itself.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from shwfs_ao.backends.hcipy import (
    OptionalDependencyError,
    hcipy_installed,
)
from shwfs_ao.validation.cross_backend import (
    CrossBackendConfig,
    CrossBackendError,
    run_cross_backend_report,
)
from shwfs_ao.validation.physical import (
    PhysicalEstimatorError,
    centroid_xy_px,
    encircled_energy_radius_rad,
    mean_square_column_difference,
    normalized_singular_spectrum,
)
from shwfs_ao.validation.regression import (
    CROSS_BACKEND_BASELINE_SCHEMA_NAME,
    CROSS_BACKEND_BASELINE_SCHEMA_VERSION,
    CROSS_BACKEND_REPORT_SCHEMA_NAME,
    CROSS_BACKEND_BASELINE_SCHEMA_RESOURCE,
    COMPARISONS_REQUIRING_STATISTICAL_DEFINITION,
    METRIC_CONTRACT,
    REQUIRED_COMPARISON_KINDS,
    REQUIRED_COMPONENT_HASH_KEYS,
    REQUIRED_FIXTURE_HASH_KEYS,
    REQUIRED_METRIC_NAMES,
    BaselineContractError,
    baseline_from_report,
    evaluate_report_against_baseline,
    load_cross_backend_baseline,
    validate_baseline_against_schema,
    validate_cross_backend_baseline,
    validate_cross_backend_report,
)
from shwfs_ao.io.resources import read_text_resource


HCIPY_INSTALLED = hcipy_installed()

TICKET_COMPARISON_KINDS = (
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

# The library is the single source of truth for the required inventory; the
# packaged baseline and every synthetic contract fixture reuse it.
SHARED_FIXTURE_HASH_KEYS = set(REQUIRED_FIXTURE_HASH_KEYS)

COMPONENT_HASH_KEYS = set(REQUIRED_COMPONENT_HASH_KEYS)


def _hash64(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _probe_metric(kind: str, name: str) -> dict:
    # Shape each probe metric to satisfy its pinned METRIC_CONTRACT (level,
    # units, criterion type, and canonical expectation), so the synthetic report
    # is a valid document under the scientific-meaning contract.
    level, units, criterion_type, expected = METRIC_CONTRACT[kind][name]
    metric = {
        "name": name,
        "level": level,
        "units": units,
        "rationale": "Contract-test probe metric.",
    }
    if criterion_type == "equals":
        # A pinned universal expectation is a bool/int/str; a baseline-specific
        # one (the sentinel) gets a neutral placeholder the equals gate accepts.
        value = expected if isinstance(expected, (bool, int, str)) else 1
        metric["value"] = value
        metric["pass_criterion"] = {"type": "equals", "expected": value}
    elif criterion_type == "abs_tolerance":
        metric["value"] = 0.0
        metric["pass_criterion"] = {
            "type": "abs_tolerance",
            "expected": 0.0,
            "tolerance": 1.0,
        }
    elif criterion_type == "range":
        metric["value"] = 1.0
        metric["pass_criterion"] = {"type": "range", "low": 0.5, "high": 1.5}
    else:  # informational
        metric["value"] = 0.5
        metric["pass_criterion"] = {"type": "informational"}
    return metric


def _probe_comparison(kind: str) -> dict:
    # Emit exactly the required metric inventory for the kind, each metric shaped
    # to satisfy its pinned scientific-meaning contract.
    comparison = {
        "comparison_kind": kind,
        "attribution": "Synthetic comparison for contract tests.",
        "metrics": [
            _probe_metric(kind, name)
            for name in sorted(REQUIRED_METRIC_NAMES[kind])
        ],
    }
    # An estimated comparison must state its estimator and uncertainty.
    if kind in COMPARISONS_REQUIRING_STATISTICAL_DEFINITION:
        comparison["statistical_definition"] = (
            "Synthetic contract-test estimator: probe values over 1 realization; "
            "uncertainty is not measured in this fixture."
        )
    return comparison


def _minimal_report() -> dict:
    return {
        "artifact_schema_name": CROSS_BACKEND_REPORT_SCHEMA_NAME,
        "artifact_schema_version": CROSS_BACKEND_BASELINE_SCHEMA_VERSION,
        "comparison_config": {"config_hash": _hash64("config")},
        "root_seed": 7,
        "conventions": {
            "command_unit": "m_opd_equivalent",
            "residual_sign_convention": (
                "residual_opd_m = atmosphere_opd_m - dm_correction_opd_m"
            ),
            "measurement_unit": "pixel",
        },
        "component_hashes": {
            key: _hash64(key) for key in REQUIRED_COMPONENT_HASH_KEYS
        },
        "fixture_hashes": {
            key: _hash64(key) for key in REQUIRED_FIXTURE_HASH_KEYS
        },
        "environment": {
            "python_version": "3.14.0",
            "numpy_version": "2.5.0",
            "shwfs_ao_version": "0.1.0",
            "hcipy_version": "0.7.0",
            "platform": "contract-test",
            "dependency_constraint_file": "unrecorded",
            "dependency_constraint_sha256": "unrecorded",
        },
        "comparisons": [
            _probe_comparison(kind) for kind in REQUIRED_COMPARISON_KINDS
        ],
    }


def _minimal_baseline() -> dict:
    return baseline_from_report(
        _minimal_report(),
        generator={
            "generator_name": "contract-test-generator",
            "generator_version": "1",
            "source_commit": _hash64("commit")[:40],
            "source_tree_clean": True,
        },
        acceptance={
            "reason": "Contract-test acceptance.",
            "review_reference": "AO-REF-018",
            "accepted_at_utc": "2026-07-17T00:00:00+00:00",
        },
    )


@pytest.fixture(scope="module")
def packaged_baseline() -> dict:
    return json.loads(json.dumps(dict(load_cross_backend_baseline())))


def _report_copy(baseline: dict) -> dict:
    return json.loads(json.dumps(baseline))


def _set_metric_value(document: dict, kind: str, name: str, value) -> None:
    for comparison in document["comparisons"]:
        if comparison["comparison_kind"] != kind:
            continue
        for metric in comparison["metrics"]:
            if metric["name"] == name:
                metric["value"] = value
                return
    raise AssertionError(f"metric {kind}/{name} not found")


def _remove_metric(document: dict, kind: str, name: str) -> None:
    for comparison in document["comparisons"]:
        if comparison["comparison_kind"] == kind:
            metrics = [
                metric
                for metric in comparison["metrics"]
                if metric["name"] != name
            ]
            assert len(metrics) == len(comparison["metrics"]) - 1
            comparison["metrics"] = metrics
            return
    raise AssertionError(f"comparison {kind} not found")


class TestPhysicalEstimators:
    def test_centroid_of_a_point_mass_is_its_column_row_position(self):
        spot = np.zeros((7, 9))
        spot[2, 5] = 3.0
        assert centroid_xy_px(spot) == (5.0, 2.0)

    def test_centroid_weights_flux_between_two_points(self):
        spot = np.zeros((5, 9))
        spot[2, 5] = 1.0
        spot[2, 7] = 3.0
        x_px, y_px = centroid_xy_px(spot)
        assert x_px == pytest.approx(6.5)
        assert y_px == pytest.approx(2.0)

    def test_centroid_rejects_flat_negative_and_non_2d_input(self):
        with pytest.raises(PhysicalEstimatorError, match="positive total flux"):
            centroid_xy_px(np.zeros((4, 4)))
        with pytest.raises(PhysicalEstimatorError, match="non-negative"):
            centroid_xy_px(np.array([[1.0, -1.0], [1.0, 1.0]]))
        with pytest.raises(PhysicalEstimatorError, match="2-D"):
            centroid_xy_px(np.ones(5))
        with pytest.raises(PhysicalEstimatorError, match="finite"):
            centroid_xy_px(np.array([[1.0, np.nan], [1.0, 1.0]]))

    def test_encircled_energy_radius_of_a_point_mass_is_zero(self):
        spot = np.zeros((9, 9))
        spot[4, 4] = 2.0
        assert encircled_energy_radius_rad(spot, (1.0e-6, 1.0e-6)) == 0.0

    def test_encircled_energy_radius_grows_with_spot_width_and_scale(self):
        rows, columns = np.mgrid[0:33, 0:33]
        radius_sq = (rows - 16.0) ** 2 + (columns - 16.0) ** 2

        def gaussian(sigma_px: float) -> np.ndarray:
            return np.exp(-radius_sq / (2.0 * sigma_px**2))

        narrow = encircled_energy_radius_rad(gaussian(2.0), (1.0e-6, 1.0e-6))
        wide = encircled_energy_radius_rad(gaussian(4.0), (1.0e-6, 1.0e-6))
        rescaled = encircled_energy_radius_rad(gaussian(2.0), (2.0e-6, 2.0e-6))
        assert wide > narrow > 0.0
        assert rescaled == pytest.approx(2.0 * narrow)

    def test_encircled_energy_radius_rejects_bad_fraction_and_scale(self):
        spot = np.ones((4, 4))
        for fraction in (0.0, 1.0, True):
            with pytest.raises(PhysicalEstimatorError, match="fraction"):
                encircled_energy_radius_rad(
                    spot,
                    (1.0e-6, 1.0e-6),
                    fraction=fraction,
                )
        with pytest.raises(PhysicalEstimatorError, match="pixel_scale"):
            encircled_energy_radius_rad(spot, (0.0, 1.0e-6))

    def test_mean_square_column_difference_matches_a_linear_ramp(self):
        values = 0.5 * np.tile(np.arange(10.0), (4, 1))
        assert mean_square_column_difference(values, 3) == pytest.approx(2.25)

    def test_mean_square_column_difference_ignores_nan_samples(self):
        values = 0.5 * np.tile(np.arange(10.0), (4, 1))
        values[:, 4] = np.nan
        assert mean_square_column_difference(values, 3) == pytest.approx(2.25)

    def test_mean_square_column_difference_rejects_bad_lags(self):
        values = np.zeros((3, 6))
        for lag in (0, 6, True):
            with pytest.raises(PhysicalEstimatorError, match="lag_px"):
                mean_square_column_difference(values, lag)
        with pytest.raises(PhysicalEstimatorError, match="2-D"):
            mean_square_column_difference(np.zeros(6), 2)
        with pytest.raises(PhysicalEstimatorError, match="finite sample pair"):
            mean_square_column_difference(np.full((3, 6), np.nan), 2)

    def test_normalized_singular_spectrum_divides_by_the_leading_value(self):
        spectrum = normalized_singular_spectrum(np.diag([3.0, 2.0, 1.0]))
        assert spectrum == pytest.approx([1.0, 2.0 / 3.0, 1.0 / 3.0])
        assert np.all(np.diff(spectrum) <= 0.0)

    def test_normalized_singular_spectrum_rejects_degenerate_input(self):
        with pytest.raises(PhysicalEstimatorError, match="positive largest"):
            normalized_singular_spectrum(np.zeros((3, 3)))
        with pytest.raises(PhysicalEstimatorError, match="finite"):
            normalized_singular_spectrum(np.array([[1.0, np.inf]]))
        with pytest.raises(PhysicalEstimatorError, match="non-empty"):
            normalized_singular_spectrum(np.zeros((0, 3)))


class TestDocumentContract:
    def test_minimal_report_and_baseline_round_trip(self):
        report = _minimal_report()
        assert validate_cross_backend_report(report) is report
        baseline = _minimal_baseline()
        assert (
            baseline["artifact_schema_name"] == CROSS_BACKEND_BASELINE_SCHEMA_NAME
        )
        validate_cross_backend_baseline(baseline)

    def test_baseline_from_report_never_mutates_its_input(self):
        report = _minimal_report()
        snapshot = json.loads(json.dumps(report))
        _minimal_baseline()
        assert report == snapshot

    @pytest.mark.parametrize(
        "field",
        (
            "artifact_schema_name",
            "comparison_config",
            "conventions",
            "component_hashes",
            "fixture_hashes",
            "environment",
            "comparisons",
        ),
    )
    def test_report_requires_every_top_level_field(self, field):
        report = _minimal_report()
        del report[field]
        with pytest.raises(BaselineContractError, match="missing required"):
            validate_cross_backend_report(report)

    def test_report_rejects_unknown_schema_identity(self):
        report = _minimal_report()
        report["artifact_schema_name"] = "shwfs_ao.other_artifact"
        with pytest.raises(BaselineContractError, match="artifact_schema_name"):
            validate_cross_backend_report(report)
        report = _minimal_report()
        report["artifact_schema_version"] = 999
        with pytest.raises(
            BaselineContractError,
            match="artifact_schema_version",
        ):
            validate_cross_backend_report(report)

    def test_report_rejects_a_config_without_hash_and_short_hashes(self):
        report = _minimal_report()
        report["comparison_config"] = {"root_seed": 7}
        with pytest.raises(BaselineContractError, match="config_hash"):
            validate_cross_backend_report(report)
        report = _minimal_report()
        report["fixture_hashes"]["static_opd_m"] = "abc123"
        with pytest.raises(BaselineContractError, match="64-character"):
            validate_cross_backend_report(report)

    def test_report_rejects_duplicate_comparisons_and_metric_names(self):
        report = _minimal_report()
        report["comparisons"].append(
            json.loads(json.dumps(report["comparisons"][0]))
        )
        with pytest.raises(BaselineContractError, match="duplicate comparison"):
            validate_cross_backend_report(report)
        report = _minimal_report()
        report["comparisons"][0]["metrics"].append(
            json.loads(json.dumps(report["comparisons"][0]["metrics"][0]))
        )
        with pytest.raises(BaselineContractError, match="duplicate metric"):
            validate_cross_backend_report(report)

    def test_the_required_kind_inventory_matches_the_ticket(self):
        assert REQUIRED_COMPARISON_KINDS == TICKET_COMPARISON_KINDS

    def test_report_rejects_a_missing_required_comparison_kind(self):
        report = _minimal_report()
        del report["comparisons"][2]
        with pytest.raises(
            BaselineContractError,
            match="required comparison kinds",
        ) as excinfo:
            validate_cross_backend_report(report)
        assert "atmosphere_statistics" in str(excinfo.value)

    def test_report_rejects_an_unknown_extra_comparison_kind(self):
        report = _minimal_report()
        report["comparisons"][0]["comparison_kind"] = "unit_probe"
        with pytest.raises(
            BaselineContractError,
            match="required comparison kinds",
        ) as excinfo:
            validate_cross_backend_report(report)
        assert "unit_probe" in str(excinfo.value)

    def test_report_rejects_a_reordered_comparison_inventory(self):
        report = _minimal_report()
        comparisons = report["comparisons"]
        comparisons[0], comparisons[1] = comparisons[1], comparisons[0]
        with pytest.raises(
            BaselineContractError,
            match="canonical order",
        ):
            validate_cross_backend_report(report)

    def test_report_rejects_a_missing_or_extra_required_hash_key(self):
        report = _minimal_report()
        del report["fixture_hashes"]["atmosphere_opd_cube_m"]
        with pytest.raises(BaselineContractError, match="exactly the required"):
            validate_cross_backend_report(report)
        report = _minimal_report()
        report["component_hashes"]["unreviewed_extra"] = _hash64("extra")
        with pytest.raises(BaselineContractError, match="exactly the required"):
            validate_cross_backend_report(report)

    def test_report_rejects_a_dropped_or_added_required_metric(self):
        report = _minimal_report()
        _remove_metric(
            report,
            "closed_loop_residual",
            "both_loops_consumed_shared_opd_cube",
        )
        with pytest.raises(
            BaselineContractError,
            match="exactly its required metrics",
        ) as excinfo:
            validate_cross_backend_report(report)
        assert "both_loops_consumed_shared_opd_cube" in str(excinfo.value)

    def test_report_requires_exact_metrics_to_gate_on_equality(self):
        report = _minimal_report()
        metric = report["comparisons"][0]["metrics"][0]
        metric["level"] = "exact"
        # An exact metric may not gate on a wideable range.
        metric["pass_criterion"] = {"type": "range", "low": 0.0, "high": 1.0e9}
        with pytest.raises(BaselineContractError, match="must be 'equals'"):
            validate_cross_backend_report(report)

    def test_baseline_requires_equal_value_for_an_equals_criterion(self):
        # mask_round_trip_identical is a pinned exact/equals(True) identity gate;
        # recording a value that disagrees with the expectation must be rejected
        # (the recorded value is the expectation the gate fires on).
        baseline = _minimal_baseline()
        _set_metric_value(
            baseline,
            "pupil_mask_and_throughput",
            "mask_round_trip_identical",
            False,
        )
        with pytest.raises(
            BaselineContractError,
            match="must equal the criterion expectation",
        ):
            validate_cross_backend_baseline(baseline)

    def test_baseline_never_lets_a_boolean_satisfy_a_numeric_expectation(self):
        # bool is a subclass of int in Python, so False == 0 and 1 == True.  A
        # baseline that records a count as a flag (or a flag as a count) would
        # otherwise validate and then gate on a value of a different kind.
        baseline = _minimal_baseline()
        _set_metric_value(
            baseline,
            "interaction_matrix_identity",
            "rank_difference",
            False,  # the criterion expects the integer 0
        )
        with pytest.raises(
            BaselineContractError,
            match="must equal the criterion expectation",
        ):
            validate_cross_backend_baseline(baseline)

        baseline = _minimal_baseline()
        _set_metric_value(
            baseline,
            "pupil_mask_and_throughput",
            "mask_round_trip_identical",
            1,  # the criterion expects the boolean True
        )
        with pytest.raises(
            BaselineContractError,
            match="must equal the criterion expectation",
        ):
            validate_cross_backend_baseline(baseline)

    def test_a_comparison_estimated_from_realizations_must_define_its_statistics(
        self,
    ):
        # The packaged JSON Schema requires this prose; so must the application
        # validator, because acceptance is the only writer of a baseline and a
        # ratio without its estimator and uncertainty is uninterpretable.
        assert COMPARISONS_REQUIRING_STATISTICAL_DEFINITION == frozenset(
            {"atmosphere_statistics"}
        )
        for absent in (None, "", "   "):
            baseline = _minimal_baseline()
            for comparison in baseline["comparisons"]:
                if comparison["comparison_kind"] != "atmosphere_statistics":
                    continue
                if absent is None:
                    del comparison["statistical_definition"]
                else:
                    comparison["statistical_definition"] = absent
            with pytest.raises(
                BaselineContractError,
                match="must record its statistical_definition",
            ):
                validate_cross_backend_baseline(baseline)

    def test_metric_contract_forbids_gating_an_identity_on_the_wrong_value(self):
        # both_loops_consumed_shared_opd_cube is a pinned exact/equals(True)
        # gate; recording it as equals(False) — even self-consistently — must be
        # rejected so a run that never consumed the shared cube cannot pass.
        baseline = _minimal_baseline()
        for comparison in baseline["comparisons"]:
            if comparison["comparison_kind"] != "closed_loop_residual":
                continue
            for metric in comparison["metrics"]:
                if metric["name"] == "both_loops_consumed_shared_opd_cube":
                    metric["value"] = False
                    metric["pass_criterion"] = {"type": "equals", "expected": False}
        with pytest.raises(
            BaselineContractError,
            match="canonical expectation",
        ):
            validate_cross_backend_baseline(baseline)

    def test_metric_contract_forbids_demoting_an_exact_gate_to_a_range(self):
        # rank_difference is a pinned exact/equals(0) gate; it cannot be recorded
        # as a wide range that a later edit could widen into an always-pass.
        baseline = _minimal_baseline()
        for comparison in baseline["comparisons"]:
            if comparison["comparison_kind"] != "interaction_matrix_identity":
                continue
            for metric in comparison["metrics"]:
                if metric["name"] == "rank_difference":
                    metric["level"] = "physical_tolerance"
                    metric["value"] = 0
                    metric["pass_criterion"] = {
                        "type": "range",
                        "low": -1000,
                        "high": 1000,
                    }
        with pytest.raises(BaselineContractError, match="pinned"):
            validate_cross_backend_baseline(baseline)

    def test_metric_contract_forbids_promoting_a_runtime_metric_to_a_gate(self):
        # runtime_and_memory metrics are pinned informational; they cannot be
        # promoted into a scientific correctness gate.
        baseline = _minimal_baseline()
        for comparison in baseline["comparisons"]:
            if comparison["comparison_kind"] != "runtime_and_memory":
                continue
            metric = comparison["metrics"][0]
            metric["level"] = "physical_tolerance"
            metric["pass_criterion"] = {"type": "range", "low": 0.0, "high": 1.0}
        with pytest.raises(BaselineContractError, match="pinned"):
            validate_cross_backend_baseline(baseline)

    def test_baseline_rejects_forged_or_unknown_source_commit(self):
        for forged in ("unknown", "abc123", "F" * 40):
            baseline = _minimal_baseline()
            baseline["generator"]["source_commit"] = forged
            with pytest.raises(
                BaselineContractError,
                match="40-character lowercase git",
            ):
                validate_cross_backend_baseline(baseline)

    def test_baseline_requires_a_recorded_clean_state_flag(self):
        baseline = _minimal_baseline()
        del baseline["generator"]["source_tree_clean"]
        with pytest.raises(
            BaselineContractError,
            match="source_tree_clean must be recorded",
        ):
            validate_cross_backend_baseline(baseline)

    def test_baseline_requires_patch_evidence_when_the_tree_is_dirty(self):
        # A dirty tree cannot masquerade as reproducible: it must carry the
        # source_patch_sha256 hash of exactly what diverged from the commit.
        baseline = _minimal_baseline()
        baseline["generator"]["source_tree_clean"] = False
        with pytest.raises(
            BaselineContractError,
            match="source_patch_sha256 must be the 64-character",
        ):
            validate_cross_backend_baseline(baseline)
        for forged in ("", "not-a-hash", "abc123", "F" * 64):
            baseline["generator"]["source_patch_sha256"] = forged
            with pytest.raises(
                BaselineContractError,
                match="source_patch_sha256 must be the 64-character",
            ):
                validate_cross_backend_baseline(baseline)
        # Valid 64-hex patch evidence is accepted for a dirty tree.
        baseline["generator"]["source_patch_sha256"] = _hash64("patch-evidence")
        validate_cross_backend_baseline(baseline)

    def test_baseline_rejects_any_patch_evidence_when_the_tree_is_clean(self):
        # A clean tree has no divergence from the recorded commit, so patch
        # evidence of one contradicts it — and a well-formed hash is the
        # dangerous case, because it is the one that looks like real evidence.
        for contradiction in ("not-a-hash", _hash64("well-formed"), ""):
            baseline = _minimal_baseline()
            assert baseline["generator"]["source_tree_clean"] is True
            baseline["generator"]["source_patch_sha256"] = contradiction
            with pytest.raises(
                BaselineContractError,
                match="must be null or absent when source_tree_clean is true",
            ):
                validate_cross_backend_baseline(baseline)

        # Null and absent both mean "nothing diverged", and both are accepted.
        baseline = _minimal_baseline()
        baseline["generator"]["source_patch_sha256"] = None
        validate_cross_backend_baseline(baseline)
        del baseline["generator"]["source_patch_sha256"]
        validate_cross_backend_baseline(baseline)

    @pytest.mark.parametrize(
        "criterion, message",
        (
            (
                {"type": "abs_tolerance", "expected": 0.0, "tolerance": -1e-9},
                "non-negative",
            ),
            (
                {
                    "type": "abs_tolerance",
                    "expected": 0.0,
                    "tolerance": float("nan"),
                },
                "non-negative",
            ),
            (
                {
                    "type": "abs_tolerance",
                    "expected": float("inf"),
                    "tolerance": 1e-9,
                },
                "finite number",
            ),
            (
                {"type": "abs_tolerance", "expected": 0.0, "tolerance": True},
                "non-negative",
            ),
            (
                {"type": "range", "low": 2.0, "high": 1.0},
                "must not exceed",
            ),
            (
                {"type": "range", "low": float("-inf"), "high": 1.0},
                "finite",
            ),
            (
                {"type": "range", "low": 0.0, "high": float("nan")},
                "finite",
            ),
            (
                {"type": "equals", "expected": float("nan")},
                "finite",
            ),
        ),
    )
    def test_report_rejects_degenerate_criterion_numerics(
        self,
        criterion,
        message,
    ):
        report = _minimal_report()
        report["comparisons"][0]["metrics"][0]["pass_criterion"] = criterion
        with pytest.raises(BaselineContractError, match=message):
            validate_cross_backend_report(report)

    def test_report_accepts_boolean_and_string_equality_expectations(self):
        # The pinned contract includes boolean identity gates (e.g.
        # mask_round_trip_identical == True) and string identity gates (e.g.
        # native_backend_name == "native"); a conforming report validates and
        # preserves both expectation types.
        report = _minimal_report()
        validate_cross_backend_report(report)
        equals_expectations = {
            metric["name"]: metric["pass_criterion"]["expected"]
            for comparison in report["comparisons"]
            for metric in comparison["metrics"]
            if metric["pass_criterion"]["type"] == "equals"
        }
        assert equals_expectations["mask_round_trip_identical"] is True
        assert equals_expectations["native_backend_name"] == "native"

    def test_a_baseline_rejects_a_non_finite_recorded_gating_value(self):
        # A fresh report may observe NaN — evaluation reports that as a
        # metric failure with full context — but an accepted baseline's
        # recorded value is an expectation and must be finite.
        report = _minimal_report()
        report["comparisons"][0]["metrics"][0]["value"] = float("nan")
        validate_cross_backend_report(report)
        baseline = _minimal_baseline()
        baseline["comparisons"][0]["metrics"][0]["value"] = float("nan")
        with pytest.raises(BaselineContractError, match="finite"):
            validate_cross_backend_baseline(baseline)

    def test_report_rejects_a_non_hex_content_hash(self):
        report = _minimal_report()
        report["component_hashes"]["pupil_geometry"] = "Z" * 64
        with pytest.raises(BaselineContractError, match="hexadecimal"):
            validate_cross_backend_report(report)

    def test_report_rejects_unknown_levels_and_incomplete_criteria(self):
        report = _minimal_report()
        report["comparisons"][0]["metrics"][0]["level"] = "loose"
        with pytest.raises(BaselineContractError, match="unknown level"):
            validate_cross_backend_report(report)
        for broken in (
            {"type": "abs_tolerance", "expected": 0.0},
            {"type": "range", "low": 0.0},
            {"type": "equals"},
            {"type": "close_enough"},
        ):
            report = _minimal_report()
            report["comparisons"][0]["metrics"][0]["pass_criterion"] = broken
            with pytest.raises(BaselineContractError):
                validate_cross_backend_report(report)

    def test_report_ties_the_informational_level_to_its_criterion(self):
        report = _minimal_report()
        report["comparisons"][0]["metrics"][0]["pass_criterion"] = {
            "type": "informational",
        }
        with pytest.raises(BaselineContractError, match="informational"):
            validate_cross_backend_report(report)
        report = _minimal_report()
        report["comparisons"][0]["metrics"][0]["level"] = "informational"
        with pytest.raises(BaselineContractError, match="informational"):
            validate_cross_backend_report(report)

    def test_baseline_rejects_missing_generator_or_acceptance(self):
        baseline = _minimal_baseline()
        del baseline["generator"]
        with pytest.raises(BaselineContractError, match="generator"):
            validate_cross_backend_baseline(baseline)
        baseline = _minimal_baseline()
        del baseline["acceptance"]
        with pytest.raises(BaselineContractError, match="acceptance"):
            validate_cross_backend_baseline(baseline)

    @pytest.mark.parametrize(
        "block, field",
        (
            ("generator", "generator_name"),
            ("generator", "generator_version"),
            ("generator", "source_commit"),
            ("acceptance", "reason"),
            ("acceptance", "review_reference"),
            ("acceptance", "accepted_at_utc"),
        ),
    )
    def test_baseline_rejects_empty_provenance_fields(self, block, field):
        baseline = _minimal_baseline()
        baseline[block][field] = "  "
        with pytest.raises(BaselineContractError, match="non-empty"):
            validate_cross_backend_baseline(baseline)

    def test_baseline_rejects_a_metric_without_scientific_rationale(self):
        baseline = _minimal_baseline()
        baseline["comparisons"][0]["metrics"][0]["rationale"] = "   "
        with pytest.raises(BaselineContractError, match="rationale"):
            validate_cross_backend_baseline(baseline)

    def test_baseline_rejects_the_plain_report_schema_name(self):
        baseline = _minimal_baseline()
        baseline["artifact_schema_name"] = CROSS_BACKEND_REPORT_SCHEMA_NAME
        with pytest.raises(BaselineContractError, match="baseline"):
            validate_cross_backend_baseline(baseline)


class TestPackagedBaseline:
    def test_packaged_baseline_validates_and_covers_the_ticket_comparisons(
        self,
        packaged_baseline,
    ):
        kinds = tuple(
            comparison["comparison_kind"]
            for comparison in packaged_baseline["comparisons"]
        )
        assert kinds == TICKET_COMPARISON_KINDS

    def test_packaged_baseline_matches_the_default_configuration(
        self,
        packaged_baseline,
    ):
        config = CrossBackendConfig()
        assert (
            packaged_baseline["comparison_config"]["config_hash"]
            == config.config_hash
        )
        assert packaged_baseline["root_seed"] == config.root_seed

    def test_packaged_baseline_records_shared_inputs_and_identities(
        self,
        packaged_baseline,
    ):
        assert set(packaged_baseline["fixture_hashes"]) == (
            SHARED_FIXTURE_HASH_KEYS
        )
        assert set(packaged_baseline["component_hashes"]) == (
            COMPONENT_HASH_KEYS
        )
        conventions = packaged_baseline["conventions"]
        assert conventions["command_unit"] == "m_opd_equivalent"
        assert "residual_opd_m" in conventions["residual_sign_convention"]
        assert conventions["measurement_unit"] == "pixel"

    def test_packaged_baseline_records_environment_and_provenance(
        self,
        packaged_baseline,
    ):
        environment = packaged_baseline["environment"]
        for field in (
            "python_version",
            "numpy_version",
            "shwfs_ao_version",
            "hcipy_version",
            "dependency_constraint_file",
            "dependency_constraint_sha256",
        ):
            assert environment[field].strip()
        generator = packaged_baseline["generator"]
        assert generator["generator_name"] == (
            "scripts/generate_cross_backend_candidate.py"
        )
        assert packaged_baseline["acceptance"]["review_reference"].strip()

    def test_packaged_statistical_comparison_documents_its_estimator(
        self,
        packaged_baseline,
    ):
        atmosphere = next(
            comparison
            for comparison in packaged_baseline["comparisons"]
            if comparison["comparison_kind"] == "atmosphere_statistics"
        )
        definition = atmosphere["statistical_definition"]
        assert "realizations" in definition
        assert "estimator" in definition
        assert "uncertainty" in definition

    def test_packaged_range_criteria_exceed_the_recorded_dispersion(
        self,
        packaged_baseline,
    ):
        # The statistical claim is checkable from the artifact alone: each
        # recorded gating value sits more than three recorded standard
        # errors inside its range criterion.
        atmosphere = next(
            comparison
            for comparison in packaged_baseline["comparisons"]
            if comparison["comparison_kind"] == "atmosphere_statistics"
        )
        metrics = {
            metric["name"]: metric for metric in atmosphere["metrics"]
        }
        assert "three standard errors" in atmosphere["statistical_definition"]
        pairs = (
            ("rms_ratio_hcipy_over_native", "rms_ratio_standard_error"),
            (
                "native_structure_function_lag_ratio",
                "native_structure_function_ratio_standard_error",
            ),
            (
                "hcipy_structure_function_lag_ratio",
                "hcipy_structure_function_ratio_standard_error",
            ),
        )
        for gating_name, error_name in pairs:
            gating = metrics[gating_name]
            standard_error = metrics[error_name]
            assert standard_error["level"] == "informational"
            assert standard_error["value"] >= 0.0
            criterion = gating["pass_criterion"]
            margin = min(
                gating["value"] - criterion["low"],
                criterion["high"] - gating["value"],
            )
            assert margin > 3.0 * standard_error["value"], gating_name

    def test_packaged_baseline_consumes_every_recorded_fixture(
        self,
        packaged_baseline,
    ):
        by_kind = {
            comparison["comparison_kind"]: {
                metric["name"]: metric for metric in comparison["metrics"]
            }
            for comparison in packaged_baseline["comparisons"]
        }
        influence = by_kind["dm_single_actuator_influence"]
        assert "max_in_pupil_command_surface_abs_diff_m" in influence
        loop = by_kind["closed_loop_residual"]
        assert (
            loop["executed_time_grid_matches_shared_fixture"]["value"] is True
        )

    def test_packaged_generator_records_verifiable_provenance(
        self,
        packaged_baseline,
    ):
        generator = packaged_baseline["generator"]
        assert generator["generator_version"] == "2"
        assert generator["source_tree_clean"] is True
        commit = generator["source_commit"]
        assert len(commit) == 40
        assert set(commit) <= set("0123456789abcdef")

    def test_packaged_environment_matches_its_named_constraint_profile(
        self,
        packaged_baseline,
    ):
        # The named profile must be the one that could have produced the
        # recorded interpreter and library versions.  The constraints tree
        # exists only in a source checkout, so the wheel-smoke bundle skips.
        environment = packaged_baseline["environment"]
        profile = environment["dependency_constraint_file"]
        repository_root = Path(__file__).resolve().parents[2]
        profile_path = repository_root / profile
        if not (repository_root / "constraints").is_dir():
            pytest.skip("constraints profiles are not part of this bundle")
        assert profile_path.is_file(), profile
        payload = profile_path.read_bytes()
        assert (
            hashlib.sha256(payload).hexdigest()
            == environment["dependency_constraint_sha256"]
        )
        suffix = profile_path.stem.rsplit("py", 1)[-1]
        major, minor = suffix[0], suffix[1:]
        assert environment["python_version"].startswith(f"{major}.{minor}.")
        pins = {}
        for raw_line in payload.decode("utf-8").splitlines():
            line = raw_line.split("#", 1)[0].split(";", 1)[0].strip()
            if line and "==" in line and not line.startswith("-"):
                name, _, version = line.partition("==")
                pins[name.strip().lower().replace("_", "-")] = version.strip()
        assert pins["numpy"] == environment["numpy_version"]
        assert pins["hcipy"] == environment["hcipy_version"]

    def test_packaged_baseline_evaluates_cleanly_against_itself(
        self,
        packaged_baseline,
    ):
        assert (
            evaluate_report_against_baseline(
                packaged_baseline,
                packaged_baseline,
            )
            == ()
        )

    def test_packaged_baseline_validates_against_the_json_schema(
        self,
        packaged_baseline,
    ):
        # The independent structural gate the acceptance workflow also runs.
        validate_baseline_against_schema(packaged_baseline)

    def test_schema_enumerations_match_the_required_inventory(self):
        # The JSON Schema and the Python inventory are one contract: they must
        # name the same required hash keys and per-kind metrics, so neither can
        # drift from the other without a deliberate, reviewed edit to both.
        schema = json.loads(read_text_resource(CROSS_BACKEND_BASELINE_SCHEMA_RESOURCE))
        properties = schema["properties"]
        assert set(properties["fixture_hashes"]["required"]) == set(
            REQUIRED_FIXTURE_HASH_KEYS
        )
        assert set(properties["component_hashes"]["required"]) == set(
            REQUIRED_COMPONENT_HASH_KEYS
        )
        for item in properties["comparisons"]["prefixItems"]:
            kind = item["properties"]["comparison_kind"]["const"]
            schema_names = {
                clause["contains"]["properties"]["name"]["const"]
                for clause in item["properties"]["metrics"]["allOf"]
            }
            assert schema_names == set(REQUIRED_METRIC_NAMES[kind]), kind

    def test_schema_validation_rejects_a_removed_required_field(self):
        broken = _report_copy(load_cross_backend_baseline())
        del broken["conventions"]
        with pytest.raises(BaselineContractError, match="JSON Schema"):
            validate_baseline_against_schema(broken)

    def test_schema_requires_a_content_hash_for_the_constraint_lock(self):
        # The environment's dependency_constraint_sha256 must be a real content
        # hash, not arbitrary text such as "unrecorded".
        broken = _report_copy(load_cross_backend_baseline())
        broken["environment"]["dependency_constraint_sha256"] = "unrecorded"
        with pytest.raises(BaselineContractError, match="JSON Schema"):
            validate_baseline_against_schema(broken)

    def test_schema_pins_each_metric_meaning(self):
        # Defence in depth: the JSON Schema mirrors METRIC_CONTRACT, so an exact
        # identity gate recorded on the wrong side of the identity is rejected by
        # the schema as well as the application contract.
        broken = _report_copy(load_cross_backend_baseline())
        for comparison in broken["comparisons"]:
            if comparison["comparison_kind"] != "closed_loop_residual":
                continue
            for metric in comparison["metrics"]:
                if metric["name"] == "both_loops_consumed_shared_opd_cube":
                    metric["value"] = False
                    metric["pass_criterion"] = {"type": "equals", "expected": False}
        with pytest.raises(BaselineContractError, match="JSON Schema"):
            validate_baseline_against_schema(broken)


class TestEvaluationSemantics:
    def test_a_range_violation_reports_value_range_units_and_hashes(
        self,
        packaged_baseline,
    ):
        report = _report_copy(packaged_baseline)
        _set_metric_value(
            report,
            "atmosphere_statistics",
            "rms_ratio_hcipy_over_native",
            5.0,
        )
        (failure,) = evaluate_report_against_baseline(
            report,
            packaged_baseline,
        )
        assert "comparison=atmosphere_statistics" in failure
        assert "metric=rms_ratio_hcipy_over_native" in failure
        assert "observed=5.0" in failure
        assert "expected-range=[0.55, 1.8] ratio" in failure
        assert "level=physical_tolerance" in failure
        assert "config_hash=" in failure
        assert "fixtures[" in failure

    def test_an_abs_tolerance_violation_reports_the_tolerance_with_units(
        self,
        packaged_baseline,
    ):
        report = _report_copy(packaged_baseline)
        _set_metric_value(
            report,
            "psf_normalization",
            "native_total_flux_error",
            0.5,
        )
        (failure,) = evaluate_report_against_baseline(
            report,
            packaged_baseline,
        )
        assert "observed=0.5" in failure
        assert "expected=0.0" in failure
        assert "tolerance=±1e-09 flux" in failure

    def test_an_exact_violation_reports_exact_tolerance(
        self,
        packaged_baseline,
    ):
        report = _report_copy(packaged_baseline)
        _set_metric_value(
            report,
            "interaction_matrix_identity",
            "rank_difference",
            1,
        )
        (failure,) = evaluate_report_against_baseline(
            report,
            packaged_baseline,
        )
        assert "observed=1" in failure
        assert "expected=0" in failure
        assert "tolerance=exact" in failure

    def test_a_non_finite_observation_fails_instead_of_passing(
        self,
        packaged_baseline,
    ):
        report = _report_copy(packaged_baseline)
        _set_metric_value(
            report,
            "strehl_ratio",
            "strehl_abs_difference",
            float("nan"),
        )
        (failure,) = evaluate_report_against_baseline(
            report,
            packaged_baseline,
        )
        assert "metric=strehl_abs_difference" in failure
        assert "observed=nan" in failure

    def test_a_report_missing_a_required_metric_is_surfaced_with_full_context(
        self,
        packaged_baseline,
    ):
        # A dropped gate is surfaced as a rich per-metric failure carrying the
        # same complete context a value violation would (expected value or
        # range, tolerance, units, level, and hashes), not a terse inventory
        # rejection that hides them (F8).
        report = _report_copy(packaged_baseline)
        _remove_metric(
            report,
            "strehl_ratio",
            "strehl_abs_difference",
        )
        (failure,) = evaluate_report_against_baseline(report, packaged_baseline)
        assert "metric=strehl_abs_difference" in failure
        assert "absent" in failure
        assert "Strehl" in failure
        assert "level=physical_tolerance" in failure

    def test_informational_metrics_never_gate(self, packaged_baseline):
        report = _report_copy(packaged_baseline)
        _set_metric_value(
            report,
            "runtime_and_memory",
            "native_wfs_propagation_s",
            1.0e9,
        )
        assert (
            evaluate_report_against_baseline(report, packaged_baseline) == ()
        )

    def test_informational_metrics_are_required_evidence_even_though_they_never_gate(
        self, packaged_baseline
    ):
        # Their values are free, but their absence is not: the standard errors
        # qualify the atmosphere ratios and the runtime block is the only
        # measurement of cost, so a report that drops them has lost the evidence
        # its gated numbers are read against.
        report = _report_copy(packaged_baseline)
        report["comparisons"] = [
            comparison
            for comparison in report["comparisons"]
            if comparison["comparison_kind"] != "runtime_and_memory"
        ]
        failures = evaluate_report_against_baseline(report, packaged_baseline)
        assert len(failures) == 5
        assert all("runtime_and_memory" in failure for failure in failures)
        assert all("<absent: missing from the fresh report>" in failure for failure in failures)

        report = _report_copy(packaged_baseline)
        for comparison in report["comparisons"]:
            if comparison["comparison_kind"] != "atmosphere_statistics":
                continue
            comparison["metrics"] = [
                metric
                for metric in comparison["metrics"]
                if "standard_error" not in metric["name"]
            ]
        failures = evaluate_report_against_baseline(report, packaged_baseline)
        assert len(failures) == 3
        assert all("standard_error" in failure for failure in failures)

    def test_a_numpy_boolean_is_a_flag_and_not_a_number(self, packaged_baseline):
        """NumPy's bool_ is not a Python bool, so the kind check must not ask.

        ``numpy.bool_`` compares equal to 0 and 1 while failing
        ``isinstance(x, bool)``, which inverts a bool-only guard exactly: the
        flag satisfies the numeric gate and fails the boolean one.  A metric
        producer that computes an identity as ``(a == b).all()`` hands back
        precisely this type.
        """

        numpy = pytest.importorskip("numpy")

        # A flag may not satisfy a gate on a count...
        report = _report_copy(packaged_baseline)
        _set_metric_value(
            report,
            "interaction_matrix_identity",
            "rank_difference",
            numpy.bool_(False),
        )
        failures = evaluate_report_against_baseline(report, packaged_baseline)
        assert len(failures) == 1
        assert "metric=rank_difference" in failures[0]

        # ...and a genuine boolean measurement must still satisfy its own gate,
        # whichever scalar type carried it.
        report = _report_copy(packaged_baseline)
        _set_metric_value(
            report,
            "pupil_mask_and_throughput",
            "mask_round_trip_identical",
            numpy.bool_(True),
        )
        assert evaluate_report_against_baseline(report, packaged_baseline) == ()

        # A NumPy float is a real measurement and stays acceptable.
        report = _report_copy(packaged_baseline)
        observed = next(
            metric["value"]
            for comparison in report["comparisons"]
            if comparison["comparison_kind"] == "strehl_ratio"
            for metric in comparison["metrics"]
            if metric["name"] == "native_strehl"
        )
        _set_metric_value(
            report, "strehl_ratio", "native_strehl", numpy.float64(observed)
        )
        assert evaluate_report_against_baseline(report, packaged_baseline) == ()

    def test_an_object_cannot_assert_its_way_past_an_equality_gate(
        self, packaged_baseline
    ):
        # A value of no recognised scalar kind never compares equal, so a
        # permissive __eq__ cannot answer a gate on the value's behalf.
        class Always:
            def __eq__(self, other):  # noqa: D105
                return True

        report = _report_copy(packaged_baseline)
        _set_metric_value(
            report, "interaction_matrix_identity", "rank_difference", Always()
        )
        assert len(evaluate_report_against_baseline(report, packaged_baseline)) == 1

    def test_a_boolean_observation_never_satisfies_a_numeric_gate(
        self, packaged_baseline
    ):
        # bool is a Python Real, so True would otherwise be measured as 1.0 and
        # could land inside a Strehl range or a residual tolerance it never met.
        for kind, name in (
            ("strehl_ratio", "native_strehl"),
            ("closed_loop_residual", "native_correction_effect"),
        ):
            report = _report_copy(packaged_baseline)
            _set_metric_value(report, kind, name, True)
            failures = evaluate_report_against_baseline(report, packaged_baseline)
            assert len(failures) == 1
            assert f"metric={name}" in failures[0]
            assert "observed=True" in failures[0]

        # And the reverse: an equality gate on a count is not met by a flag.
        report = _report_copy(packaged_baseline)
        _set_metric_value(report, "interaction_matrix_identity", "rank_difference", False)
        failures = evaluate_report_against_baseline(report, packaged_baseline)
        assert len(failures) == 1
        assert "observed=False" in failures[0]

    def test_evaluation_flags_convention_and_seed_drift(self, packaged_baseline):
        # A report whose config_hash and metric values coincide with the
        # baseline but whose measurement conventions or root seed differ is not
        # comparable, so evaluation must surface the drift instead of passing.
        report = _report_copy(packaged_baseline)
        report["conventions"]["residual_sign_convention"] = "flipped convention"
        convention_failures = evaluate_report_against_baseline(
            report, packaged_baseline
        )
        assert any(
            "conventions['residual_sign_convention']" in failure
            for failure in convention_failures
        )

        seed_report = _report_copy(packaged_baseline)
        seed_report["root_seed"] = int(packaged_baseline["root_seed"]) + 1
        seed_failures = evaluate_report_against_baseline(
            seed_report, packaged_baseline
        )
        assert any("root_seed mismatch" in failure for failure in seed_failures)

    def test_a_config_hash_mismatch_short_circuits_metric_checks(
        self,
        packaged_baseline,
    ):
        report = _report_copy(packaged_baseline)
        report["comparison_config"]["config_hash"] = _hash64("other-config")
        _set_metric_value(
            report,
            "interaction_matrix_identity",
            "rank_difference",
            1,
        )
        failures = evaluate_report_against_baseline(
            report,
            packaged_baseline,
        )
        assert len(failures) == 1
        assert "comparison_config.config_hash mismatch" in failures[0]
        assert report["comparison_config"]["config_hash"] in failures[0]
        assert (
            packaged_baseline["comparison_config"]["config_hash"]
            in failures[0]
        )

    def test_a_fixture_hash_mismatch_short_circuits_metric_checks(
        self,
        packaged_baseline,
    ):
        report = _report_copy(packaged_baseline)
        report["fixture_hashes"]["static_opd_m"] = _hash64("drifted-input")
        _set_metric_value(
            report,
            "interaction_matrix_identity",
            "rank_difference",
            1,
        )
        failures = evaluate_report_against_baseline(
            report,
            packaged_baseline,
        )
        assert len(failures) == 1
        assert "fixture_hashes['static_opd_m'] mismatch" in failures[0]
        assert "shared inputs drifted" in failures[0]


class TestSuiteEntryPoint:
    def test_the_validation_package_never_imports_hcipy_eagerly(self):
        program = (
            "import sys\n"
            "import shwfs_ao.validation\n"
            "import shwfs_ao.validation.cross_backend\n"
            "import shwfs_ao.validation.physical\n"
            "import shwfs_ao.validation.regression\n"
            "raise SystemExit(1 if 'hcipy' in sys.modules else 0)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", program],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr

    def test_configuration_validation_precedes_the_dependency_requirement(
        self,
    ):
        with pytest.raises(CrossBackendError, match="CrossBackendConfig"):
            run_cross_backend_report(config=object())
        with pytest.raises(CrossBackendError, match="integer multiple"):
            CrossBackendConfig(pupil_pixels=50)
        with pytest.raises(CrossBackendError, match="at least 2"):
            CrossBackendConfig(atmosphere_realizations=1)
        with pytest.raises(CrossBackendError, match="loop_steps"):
            CrossBackendConfig(loop_steps=1)
        with pytest.raises(CrossBackendError, match="runtime_repeats"):
            CrossBackendConfig(runtime_repeats=0)

    def test_the_comparison_config_hash_is_deterministic(self):
        assert (
            CrossBackendConfig().config_hash == CrossBackendConfig().config_hash
        )
        assert (
            CrossBackendConfig(root_seed=119).config_hash
            != CrossBackendConfig().config_hash
        )

    @pytest.mark.skipif(
        HCIPY_INSTALLED,
        reason="requires an environment without the optional HCIPy dependency",
    )
    def test_running_the_suite_without_hcipy_names_the_missing_dependency(
        self,
    ):
        with pytest.raises(OptionalDependencyError) as excinfo:
            run_cross_backend_report()
        assert "pip install 'shack-hartmann-ao-simulation[hcipy]'" in str(
            excinfo.value
        )

    def test_the_hcipy_suite_file_never_enters_the_native_selection(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "--collect-only",
                "-q",
                "-m",
                "not hcipy and not slow",
                str(Path(__file__).with_name("test_native_vs_hcipy.py")),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        # Exit code 5 is pytest's "no tests collected": every test in the
        # suite module must carry the hcipy marker and be deselected.
        assert result.returncode == 5, result.stdout + result.stderr
        assert "::" not in result.stdout
