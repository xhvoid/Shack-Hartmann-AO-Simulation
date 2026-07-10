# Tests run the fast end-to-end integration, verify finite final metrics, required figures, reference JSON fields, and notebook-11 smoke execution.

import json
import math
from pathlib import Path

import numpy as np
import pytest

from ao_integration import IntegrationConfig, load_reference_metrics, run_fast_integration


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_11 = ROOT / "notebooks" / "11_full_detector_level_2m_scao_demo.ipynb"


@pytest.fixture(scope="module")
def fast_integration_result(tmp_path_factory):
    base = tmp_path_factory.mktemp("fast_integration")
    config = IntegrationConfig.from_mode(
        "fast",
        output_dir=base / "figures",
        reference_metrics_path=base / "reference_metrics" / "fast_reference_metrics.json",
    )
    return run_fast_integration(config=config, write_outputs=True)


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


def test_notebook_11_runs_top_to_bottom_in_fast_mode_without_external_data(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    monkeypatch.setenv("AO_DEMO_OUTPUT_DIR", str(tmp_path / "figures"))
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
