# Tests run the fast end-to-end integration, verify finite final metrics, required figures, reference JSON fields, and notebook-11 smoke execution.

import ast
import json
import math
from pathlib import Path
import shutil
from types import SimpleNamespace

import numpy as np
import pytest

from ao_integration import IntegrationConfig, load_reference_metrics, run_fast_integration
from shwfs_ao.legacy import ao_integration as legacy_integration


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "src" / "shwfs_ao" / "resources"
NOTEBOOK_11 = ROOT / "notebooks" / "11_full_detector_level_2m_scao_demo.ipynb"
REFERENCE_BASELINE = DATA_ROOT / "reference_metrics" / "fast_reference_metrics_regression_baseline.json"
ERROR_BUDGET_BASELINE = DATA_ROOT / "reference_metrics" / "fast_error_budget_regression_baseline.csv"
VALIDATION_BASELINE = DATA_ROOT / "reference_metrics" / "fast_validation_regression_baseline.csv"


@pytest.fixture(scope="module")
def fast_integration_result(tmp_path_factory):
    base = tmp_path_factory.mktemp("fast_integration")
    config = IntegrationConfig.from_mode(
        "fast",
        output_dir=base / "figures",
        reference_metrics_path=base / "reference_metrics" / "fast_reference_metrics.json",
    )
    return run_fast_integration(config=config, write_outputs=True)


def _stub_integration_engine(monkeypatch):
    system = SimpleNamespace(
        calibration=object(),
        dm_model=object(),
        poke_result=object(),
    )
    scenario_results = (object(),)
    validation_results = (object(),)
    reference_metrics = {"sentinel": "in-memory"}

    monkeypatch.setattr(legacy_integration, "build_integration_system", lambda _config: system)
    monkeypatch.setattr(legacy_integration, "_build_jhk_bandpasses", lambda: ())
    monkeypatch.setattr(legacy_integration, "_scenario_matrix_for_config", lambda _config: ())
    monkeypatch.setattr(
        legacy_integration,
        "run_error_budget_scenarios",
        lambda *_args, **_kwargs: scenario_results,
    )
    monkeypatch.setattr(
        legacy_integration,
        "build_validation_results",
        lambda _config, _system: validation_results,
    )
    monkeypatch.setattr(legacy_integration, "_assert_validation_passes", lambda _results: None)
    monkeypatch.setattr(
        legacy_integration,
        "_assert_scenario_results_are_finite",
        lambda _results: None,
    )
    monkeypatch.setattr(
        legacy_integration,
        "build_reference_metrics",
        lambda *_args, **_kwargs: reference_metrics,
    )
    monkeypatch.setattr(legacy_integration, "_assert_reference_metrics", lambda _payload: None)
    return scenario_results, validation_results, reference_metrics


def test_in_memory_integration_does_not_create_output_files(tmp_path, monkeypatch):
    """The no-output branch cannot invoke artifact serialization implicitly."""

    config = IntegrationConfig.from_mode(
        "fast",
        output_dir=tmp_path / "figures",
        reference_metrics_path=tmp_path / "references" / "metrics.json",
    )
    scenario_results, validation_results, reference_metrics = _stub_integration_engine(
        monkeypatch
    )

    result = legacy_integration.run_integration(config, write_outputs=False)

    assert result.scenario_results is scenario_results
    assert result.validation_results is validation_results
    assert result.reference_metrics is reference_metrics
    assert result.written_files == ()
    assert list(tmp_path.iterdir()) == []


def test_legacy_write_flag_is_only_a_lazy_artifact_writer_delegate(tmp_path, monkeypatch):
    from shwfs_ao.io import artifacts

    config = IntegrationConfig.from_mode(
        "fast",
        output_dir=tmp_path / "figures",
        reference_metrics_path=tmp_path / "references" / "metrics.json",
    )
    _stub_integration_engine(monkeypatch)
    expected_paths = (
        tmp_path / "figures" / "fast_error_budget.csv",
        tmp_path / "references" / "metrics.json",
    )
    captured = {}

    def _write(result, artifact_config):
        captured["result"] = result
        captured["config"] = artifact_config
        return expected_paths

    monkeypatch.setattr(artifacts, "write_integration_artifacts", _write)

    result = legacy_integration.run_integration(config, write_outputs=True)

    assert captured["result"].written_files == ()
    assert captured["config"] == artifacts.ArtifactConfig(
        output_dir=config.output_dir,
        reference_metrics_path=config.reference_metrics_path,
        prefix="fast",
        schema_version=2,
    )
    assert result.written_files == expected_paths
    assert list(tmp_path.iterdir()) == []


def test_integration_engine_contains_no_active_artifact_writing_or_repo_root_use():
    tree = ast.parse(Path(legacy_integration.__file__).read_text(encoding="utf-8"))
    forbidden_calls = {"DictWriter", "mkdir", "savefig", "write_text"}

    assert not {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in forbidden_calls
    }
    assert not [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and node.id == "REPO_ROOT"
        and isinstance(node.ctx, ast.Load)
    ]


def test_integration_resources_load_outside_the_source_checkout(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    bands = legacy_integration.build_jhk_bandpasses()
    metrics = legacy_integration.load_reference_metrics()

    assert [(band.name, len(band.wavelength_m)) for band in bands] == [
        ("J", 107),
        ("H", 58),
        ("K", 76),
    ]
    assert metrics["workflow"] == "fast_integration"
    assert metrics["preset"] == "fast"
    assert list(tmp_path.iterdir()) == []


def test_fast_integration_produces_finite_metrics_and_required_artifacts(fast_integration_result):
    result = fast_integration_result

    assert result.mode == "fast"
    assert len(result.scenario_results) == 8
    assert len(result.validation_results) == 6
    assert all(check.passed for check in result.validation_results)

    for row in result.scenario_results:
        values = [
            row.open_rms_nm,
            row.closed_rms_nm,
            row.strehl_H,
            row.valid_centroid_frac,
            row.command_rms_nm,
            row.command_peak_nm,
        ]
        assert np.all(np.isfinite(values))

    expected = {
        "fast_error_budget.csv",
        "fast_error_budget.png",
        "fast_validation.csv",
        "fast_validation.png",
        "fast_reference_metrics.json",
    }
    by_name = {path.name: path for path in result.written_files}
    assert expected.issubset(by_name)
    assert all(path.exists() and path.stat().st_size > 0 for path in by_name.values())


def test_reference_metrics_json_contains_regression_contract(fast_integration_result):
    result = fast_integration_result
    reference_path = next(path for path in result.written_files if path.name == "fast_reference_metrics.json")
    payload = json.loads(reference_path.read_text(encoding="utf-8"))

    # AO-REF-003 keeps the artifact-owning schema flat. The writer's existing
    # sorted JSON order and both provenance fields remain unchanged while the
    # canonical structured record is introduced separately.
    assert list(payload) == sorted(payload)
    assert "source_class" in payload
    assert "source_note" in payload

    for field in (
        "open_rms_nm",
        "closed_rms_nm",
        "h_strehl",
        "valid_centroid_fraction",
        "kept_modes",
        "runtime_band",
    ):
        assert field in payload

    for field in ("open_rms_nm", "closed_rms_nm", "h_strehl", "valid_centroid_fraction"):
        assert math.isfinite(float(payload[field]))
    assert payload["scenario_count"] == 8
    assert payload["validation_pass_count"] == payload["validation_check_count"]
    assert int(payload["kept_modes"]) >= 1
    assert payload["runtime_band"].startswith("fast_")
    assert payload["source_class"] == "synthetic_assumed"

    tolerances = payload["tolerances"]
    for field in (
        "open_rms_nm_abs",
        "closed_rms_nm_abs",
        "h_strehl_abs",
        "valid_centroid_fraction_abs",
        "kept_modes_abs",
        "runtime_s_reference_max",
    ):
        assert field in tolerances
        assert float(tolerances[field]) >= 0.0

    loaded = load_reference_metrics(reference_path)
    assert loaded["config_hash"] == payload["config_hash"]


def test_fast_result_matches_immutable_reference_baseline_with_documented_tolerances(fast_integration_result):
    actual = fast_integration_result.reference_metrics
    baseline = load_reference_metrics(REFERENCE_BASELINE)
    tolerances = baseline["tolerances"]

    assert actual["schema_version"] == baseline["schema_version"]
    assert actual["workflow"] == baseline["workflow"]
    assert actual["preset"] == baseline["preset"]
    assert actual["scenario_names"] == baseline["scenario_names"]
    assert actual["config_hash"] == baseline["config_hash"]
    assert abs(actual["open_rms_nm"] - baseline["open_rms_nm"]) <= tolerances["open_rms_nm_abs"]
    assert abs(actual["closed_rms_nm"] - baseline["closed_rms_nm"]) <= tolerances["closed_rms_nm_abs"]
    assert abs(actual["h_strehl"] - baseline["h_strehl"]) <= tolerances["h_strehl_abs"]
    assert (
        abs(actual["valid_centroid_fraction"] - baseline["valid_centroid_fraction"])
        <= tolerances["valid_centroid_fraction_abs"]
    )
    assert abs(actual["kept_modes"] - baseline["kept_modes"]) <= tolerances["kept_modes_abs"]


def test_generated_tables_match_committed_semantic_baselines(fast_integration_result):
    import csv

    actual_paths = {path.name: path for path in fast_integration_result.written_files}
    with ERROR_BUDGET_BASELINE.open(newline="", encoding="utf-8") as handle:
        expected_scenario_reader = csv.DictReader(handle)
        expected_scenarios = list(expected_scenario_reader)
    with actual_paths["fast_error_budget.csv"].open(newline="", encoding="utf-8") as handle:
        actual_scenario_reader = csv.DictReader(handle)
        actual_scenarios = list(actual_scenario_reader)
    assert actual_scenario_reader.fieldnames == expected_scenario_reader.fieldnames
    assert "source_class" in actual_scenario_reader.fieldnames
    assert "source_note" in actual_scenario_reader.fieldnames
    assert [row["scenario_name"] for row in actual_scenarios] == [
        row["scenario_name"] for row in expected_scenarios
    ]
    assert [row["enabled_effects"] for row in actual_scenarios] == [
        row["enabled_effects"] for row in expected_scenarios
    ]
    for actual, expected in zip(actual_scenarios, expected_scenarios):
        for field in (
            "open_rms_nm",
            "closed_rms_nm",
            "strehl_J",
            "strehl_H",
            "strehl_K",
            "ee50_H",
            "ee80_H",
            "command_rms_nm",
            "command_peak_nm",
            "saturated_actuator_frac",
            "valid_centroid_frac",
        ):
            assert float(actual[field]) == pytest.approx(float(expected[field]), rel=2.0e-6, abs=2.0e-8)

    with VALIDATION_BASELINE.open(newline="", encoding="utf-8") as handle:
        expected_validation_reader = csv.DictReader(handle)
        expected_validation = list(expected_validation_reader)
    with actual_paths["fast_validation.csv"].open(newline="", encoding="utf-8") as handle:
        actual_validation_reader = csv.DictReader(handle)
        actual_validation = list(actual_validation_reader)
    assert actual_validation_reader.fieldnames == expected_validation_reader.fieldnames
    assert "source_class" in actual_validation_reader.fieldnames
    assert "source_note" in actual_validation_reader.fieldnames
    assert len(actual_validation) == len(expected_validation)
    for actual, expected in zip(actual_validation, expected_validation):
        assert actual["check_name"] == expected["check_name"]
        assert actual["passed"] == expected["passed"]
        assert actual["x_value"] == expected["x_value"]
        assert float(actual["metric_value"]) == pytest.approx(
            float(expected["metric_value"]),
            rel=2.0e-6,
            abs=2.0e-8,
        )


def test_notebook_11_runs_top_to_bottom_in_fast_mode_without_external_data(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    output_dir = tmp_path / "figures"
    output_dir.mkdir()
    shutil.copy2(
        ROOT / "figures" / "detector_level_SCAO" / "public_data_informed_error_budget.csv",
        output_dir / "public_data_informed_error_budget.csv",
    )
    monkeypatch.setenv("AO_DEMO_OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("AO_DEMO_REFERENCE_METRICS", str(tmp_path / "reference_metrics" / "fast_reference_metrics.json"))
    notebook = json.loads(NOTEBOOK_11.read_text(encoding="utf-8"))
    namespace = {"__name__": "__main__"}

    for cell in notebook["cells"]:
        if cell.get("cell_type") != "code":
            continue
        source = "".join(cell.get("source", ""))
        if source.strip():
            exec(compile(source, str(NOTEBOOK_11), "exec"), namespace)

    reference_path = tmp_path / "reference_metrics" / "fast_reference_metrics.json"
    assert reference_path.exists()
    payload = json.loads(reference_path.read_text(encoding="utf-8"))
    assert payload["scenario_count"] == 8
    assert payload["validation_pass_count"] == payload["validation_check_count"]
    assert namespace["public_rows"]
    assert namespace["public_csv"].parent == output_dir
