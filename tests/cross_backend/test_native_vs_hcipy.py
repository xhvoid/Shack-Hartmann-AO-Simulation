"""AO-REF-018 continuous-integration cross-backend comparison.

Every test requires the optional HCIPy dependency and carries the ``hcipy``
marker so native CI selections never execute it.  The module is part of the
portable wheel-smoke bundle, so it imports only the installed package; it
runs the small deterministic suite once, reads only the packaged baseline,
and never writes anything.
"""

from __future__ import annotations

import math

import numpy as np
import pytest


hcipy = pytest.importorskip("hcipy")

from shwfs_ao.validation.cross_backend import (
    CrossBackendConfig,
    run_cross_backend_report,
)
from shwfs_ao.validation.regression import (
    CROSS_BACKEND_REPORT_SCHEMA_NAME,
    baseline_from_report,
    evaluate_report_against_baseline,
    load_cross_backend_baseline,
    validate_cross_backend_baseline,
    validate_cross_backend_report,
)


pytestmark = pytest.mark.hcipy


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


@pytest.fixture(scope="module")
def baseline():
    return load_cross_backend_baseline()


@pytest.fixture(scope="module")
def report():
    return run_cross_backend_report()


def test_the_fresh_report_satisfies_every_accepted_baseline_tolerance(
    report,
    baseline,
):
    failures = evaluate_report_against_baseline(report, baseline)
    assert failures == (), "\n".join(failures)


def test_the_report_covers_the_thirteen_ticket_comparisons(report):
    assert report["artifact_schema_name"] == CROSS_BACKEND_REPORT_SCHEMA_NAME
    kinds = tuple(
        comparison["comparison_kind"]
        for comparison in report["comparisons"]
    )
    assert kinds == TICKET_COMPARISON_KINDS


def test_shared_fixture_hashes_prove_identical_pointwise_inputs(
    report,
    baseline,
):
    # Pointwise optical comparisons feed both backends the same stored
    # fixtures; matching content hashes are the recorded evidence.
    assert report["fixture_hashes"] == baseline["fixture_hashes"]
    assert report["component_hashes"] == baseline["component_hashes"]
    assert (
        report["comparison_config"]["config_hash"]
        == baseline["comparison_config"]["config_hash"]
    )


def test_the_report_records_conventions_and_environment(report):
    conventions = report["conventions"]
    assert conventions["command_unit"] == "m_opd_equivalent"
    assert "atmosphere_opd_m" in conventions["residual_sign_convention"]
    assert conventions["measurement_unit"] == "pixel"
    environment = report["environment"]
    assert environment["hcipy_version"] == hcipy.__version__
    assert environment["numpy_version"] == np.__version__


def test_every_comparison_attributes_its_residual_discrepancies(report):
    for comparison in report["comparisons"]:
        attribution = comparison["attribution"]
        assert isinstance(attribution, str)
        assert len(attribution.strip()) >= 40, comparison["comparison_kind"]
    joined = " ".join(
        comparison["attribution"].lower()
        for comparison in report["comparisons"]
    )
    for cause in ("sampling", "normalization", "convention", "window"):
        assert cause in joined


def test_every_gating_metric_carries_units_and_rationale(report):
    for comparison in report["comparisons"]:
        for metric in comparison["metrics"]:
            assert metric["units"].strip(), metric["name"]
            assert metric["rationale"].strip(), metric["name"]


def test_runtime_and_memory_stay_informational_and_never_gate(
    report,
    baseline,
):
    runtime = next(
        comparison
        for comparison in report["comparisons"]
        if comparison["comparison_kind"] == "runtime_and_memory"
    )
    assert {metric["level"] for metric in runtime["metrics"]} == {
        "informational",
    }
    assert {
        metric["pass_criterion"]["type"] for metric in runtime["metrics"]
    } == {"informational"}
    # Absurd measured values must not fail correctness CI.
    import json

    slowed = json.loads(json.dumps(dict(report)))
    for comparison in slowed["comparisons"]:
        if comparison["comparison_kind"] == "runtime_and_memory":
            for metric in comparison["metrics"]:
                metric["value"] = 1.0e9
    assert evaluate_report_against_baseline(slowed, baseline) == ()


def test_the_statistical_comparison_documents_its_estimator(report):
    atmosphere = next(
        comparison
        for comparison in report["comparisons"]
        if comparison["comparison_kind"] == "atmosphere_statistics"
    )
    definition = atmosphere["statistical_definition"]
    realizations = CrossBackendConfig().atmosphere_realizations
    assert f"{realizations} independent realizations" in definition
    assert "estimator" in definition
    assert "uncertainty" in definition


def test_recorded_fixtures_are_consumed_and_dispersion_is_recorded(report):
    # Every recorded fixture hash is evidence of a consumed shared input:
    # the command fixture drives both mirrors, the executed loop time grids
    # must equal the shared time-grid fixture, and the statistical
    # comparison records the realization dispersion its tolerance claim
    # rests on.
    by_kind = {
        comparison["comparison_kind"]: {
            metric["name"]: metric for metric in comparison["metrics"]
        }
        for comparison in report["comparisons"]
    }
    influence = by_kind["dm_single_actuator_influence"]
    assert "max_in_pupil_command_surface_abs_diff_m" in influence
    assert influence["max_in_pupil_command_surface_abs_diff_m"]["value"] <= (
        1.0e-9
    )
    loop = by_kind["closed_loop_residual"]
    assert loop["executed_time_grid_matches_shared_fixture"]["value"] is True
    atmosphere = by_kind["atmosphere_statistics"]
    for name in (
        "rms_ratio_standard_error",
        "native_structure_function_ratio_standard_error",
        "hcipy_structure_function_ratio_standard_error",
    ):
        metric = atmosphere[name]
        assert metric["level"] == "informational"
        assert math.isfinite(metric["value"]) and metric["value"] >= 0.0
    definition = next(
        comparison
        for comparison in report["comparisons"]
        if comparison["comparison_kind"] == "atmosphere_statistics"
    )["statistical_definition"]
    assert "three standard errors" in definition


def test_the_report_round_trips_into_a_valid_baseline_without_writing(
    report,
):
    validate_cross_backend_report(report)
    candidate = baseline_from_report(
        report,
        generator={
            "generator_name": "tests/cross_backend/test_native_vs_hcipy.py",
            "generator_version": "1",
            "source_commit": "0" * 40,
            "source_tree_clean": True,
        },
        acceptance={
            "reason": "In-memory round-trip check only; never persisted.",
            "review_reference": "AO-REF-018",
            "accepted_at_utc": "2026-07-17T00:00:00+00:00",
        },
    )
    validate_cross_backend_baseline(candidate)
