"""Regression contract for the atmosphere-driven 2 m integration.

The frozen ``fast_*`` baselines record the control-space-proxy engine, whose
disturbance the deformable mirror can correct exactly.  The ``physical_*``
baselines pinned here record the same instrument driven by a calibrated von
Karman screen with a two-frame command latency, so they carry real fitting
error and real servo lag.

Every test that reruns the experiment is ``slow``-marked: the existing
science-metric path evaluates PSF metrics once per frame, per band, per
wavelength sample, which costs about 75 s per scenario regardless of which
disturbance drives it.  The scheduled slow lane runs them; the per-commit lane
checks the packaged artifacts without rerunning.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from shwfs_ao.experiments.physical_integration import (
    PHYSICAL_PRESET,
    PHYSICAL_WORKFLOW,
    PhysicalIntegrationConfig,
    run_physical_integration,
)
from shwfs_ao.io.artifacts import ArtifactConfig, write_integration_artifacts


ROOT = Path(__file__).resolve().parents[2]
REFERENCE_DIR = ROOT / "src" / "shwfs_ao" / "resources" / "reference_metrics"
REFERENCE_BASELINE = (
    REFERENCE_DIR / "physical_reference_metrics_regression_baseline.json"
)
ERROR_BUDGET_BASELINE = (
    REFERENCE_DIR / "physical_error_budget_regression_baseline.csv"
)
VALIDATION_BASELINE = REFERENCE_DIR / "physical_validation_regression_baseline.csv"
ACCEPTANCE_RECORD = REFERENCE_DIR / "physical_baseline_acceptance.json"


def _baseline() -> dict:
    return json.loads(REFERENCE_BASELINE.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Packaged-artifact checks: no experiment rerun, safe for the fast lane
# --------------------------------------------------------------------------


def test_physical_baseline_is_packaged_and_labelled() -> None:
    for path in (
        REFERENCE_BASELINE,
        ERROR_BUDGET_BASELINE,
        VALIDATION_BASELINE,
        ACCEPTANCE_RECORD,
    ):
        assert path.exists(), path

    baseline = _baseline()
    assert baseline["workflow"] == PHYSICAL_WORKFLOW
    assert baseline["preset"] == PHYSICAL_PRESET
    assert baseline["config_hash"] == PhysicalIntegrationConfig().config_hash


def test_physical_baseline_cannot_be_confused_with_the_proxy_baseline() -> None:
    """The two workflows must be distinguishable from the artifact alone."""

    proxy = json.loads(
        (REFERENCE_DIR / "fast_reference_metrics_regression_baseline.json").read_text(
            encoding="utf-8"
        )
    )
    physical = _baseline()

    assert proxy["workflow"] != physical["workflow"]
    assert proxy["preset"] != physical["preset"]
    assert proxy["config_hash"] != physical["config_hash"]


def test_physical_baseline_records_a_genuinely_harder_system() -> None:
    """A real atmosphere on a 5x5 actuator grid cannot be corrected away.

    This is the whole point of the workflow: if these numbers ever drift into
    proxy territory, the disturbance has stopped being an atmosphere.
    """

    proxy = json.loads(
        (REFERENCE_DIR / "fast_reference_metrics_regression_baseline.json").read_text(
            encoding="utf-8"
        )
    )
    physical = _baseline()

    assert physical["open_rms_nm"] > 3.0 * proxy["open_rms_nm"]
    assert physical["h_strehl"] < 0.85
    residual_fraction = physical["closed_rms_nm"] / physical["open_rms_nm"]
    assert 0.3 < residual_fraction < 1.05, residual_fraction


def test_physical_error_budget_table_covers_every_required_scenario() -> None:
    from shwfs_ao.experiments.error_budget import REQUIRED_SCENARIO_NAMES

    with ERROR_BUDGET_BASELINE.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert tuple(row["scenario_name"] for row in rows) == REQUIRED_SCENARIO_NAMES
    for row in rows:
        assert float(row["open_rms_nm"]) > 0.0
        assert 0.0 <= float(row["strehl_H"]) <= 1.0
        assert 0.0 <= float(row["valid_centroid_frac"]) <= 1.0


def test_acceptance_record_documents_why_the_baseline_moved() -> None:
    record = json.loads(ACCEPTANCE_RECORD.read_text(encoding="utf-8"))

    assert record["workflow"] == PHYSICAL_WORKFLOW
    assert record["reason"].strip()
    assert record["review_reference"].strip()
    assert record["accepted_files"]
    for entry in record["accepted_files"]:
        assert len(entry["sha256"]) == 64


# --------------------------------------------------------------------------
# Reruns: slow lane only
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def physical_result(tmp_path_factory):
    base = tmp_path_factory.mktemp("physical_integration")
    result = run_physical_integration(PhysicalIntegrationConfig())
    written = write_integration_artifacts(
        result,
        ArtifactConfig(
            output_dir=base,
            reference_metrics_path=base / "physical_reference_metrics.json",
            prefix="physical",
            schema_version=2,
        ),
    )
    return result, {path.name: path for path in written}


@pytest.mark.slow
def test_physical_run_reproduces_the_accepted_reference_metrics(physical_result):
    result, _ = physical_result
    actual = result.reference_metrics
    baseline = _baseline()
    tolerances = baseline["tolerances"]

    assert actual["workflow"] == baseline["workflow"]
    assert actual["preset"] == baseline["preset"]
    assert actual["scenario_names"] == baseline["scenario_names"]
    assert actual["config_hash"] == baseline["config_hash"]
    for key, tolerance_key in (
        ("open_rms_nm", "open_rms_nm_abs"),
        ("closed_rms_nm", "closed_rms_nm_abs"),
        ("h_strehl", "h_strehl_abs"),
        ("valid_centroid_fraction", "valid_centroid_fraction_abs"),
        ("kept_modes", "kept_modes_abs"),
    ):
        assert abs(actual[key] - baseline[key]) <= tolerances[tolerance_key], key


@pytest.mark.slow
def test_physical_run_reproduces_the_accepted_scenario_table(physical_result):
    _, written = physical_result

    with ERROR_BUDGET_BASELINE.open(newline="", encoding="utf-8") as handle:
        expected_reader = csv.DictReader(handle)
        expected = list(expected_reader)
    with written["physical_error_budget.csv"].open(
        newline="", encoding="utf-8"
    ) as handle:
        actual_reader = csv.DictReader(handle)
        actual = list(actual_reader)

    assert actual_reader.fieldnames == expected_reader.fieldnames
    assert [row["scenario_name"] for row in actual] == [
        row["scenario_name"] for row in expected
    ]
    for actual_row, expected_row in zip(actual, expected):
        for field in (
            "open_rms_nm",
            "closed_rms_nm",
            "strehl_J",
            "strehl_H",
            "strehl_K",
            "command_rms_nm",
            "valid_centroid_frac",
        ):
            assert float(actual_row[field]) == pytest.approx(
                float(expected_row[field]), rel=2.0e-6, abs=2.0e-8
            ), f"{expected_row['scenario_name']}.{field}"


@pytest.mark.slow
def test_physical_run_is_deterministic(physical_result):
    """Two runs of the same config must agree exactly."""

    result, _ = physical_result
    repeat = run_physical_integration(PhysicalIntegrationConfig())

    assert repeat.config_hash == result.config_hash
    for first, second in zip(result.scenario_results, repeat.scenario_results):
        assert first.scenario_name == second.scenario_name
        assert first.open_rms_nm == pytest.approx(second.open_rms_nm, rel=1e-12)
        assert first.closed_rms_nm == pytest.approx(second.closed_rms_nm, rel=1e-12)
        assert first.strehl_H == pytest.approx(second.strehl_H, rel=1e-12)
