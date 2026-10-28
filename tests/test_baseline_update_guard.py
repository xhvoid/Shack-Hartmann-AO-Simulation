"""Guards on the fast-baseline candidate/acceptance workflow.

The CLI refusal tests pin the explicit two-stage maintainer workflow of
``scripts/update_fast_regression_baselines.py``.  The in-process tests pin
the strengthened candidate contract (strict schema-v2 loading, frozen CSV
headers, JSON/CSV cross-consistency), the byte-complete freshness check at
accept time, and the persisted acceptance evidence.  They drive the
script's own functions on copies of the packaged baselines inside a
throwaway tree, so no packaged resource is ever touched.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]

_SCRIPT_SPEC = importlib.util.spec_from_file_location(
    "fast_baseline_script_for_tests",
    ROOT / "scripts" / "update_fast_regression_baselines.py",
)
assert _SCRIPT_SPEC is not None and _SCRIPT_SPEC.loader is not None
script = importlib.util.module_from_spec(_SCRIPT_SPEC)
sys.modules[_SCRIPT_SPEC.name] = script
_SCRIPT_SPEC.loader.exec_module(script)

_PACKAGED = ROOT / "src" / "shwfs_ao" / "resources" / "reference_metrics"
_CANDIDATE_SOURCES = {
    "fast_reference_metrics.json": (
        "fast_reference_metrics_regression_baseline.json"
    ),
    "fast_error_budget.csv": "fast_error_budget_regression_baseline.csv",
    "fast_validation.csv": "fast_validation_regression_baseline.csv",
}


def test_baseline_update_requires_explicit_maintainer_acknowledgement():
    result = subprocess.run(
        [sys.executable, "scripts/update_fast_regression_baselines.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "--accept-baseline-update is required" in result.stderr


def test_candidate_generation_requires_an_explicit_external_directory():
    result = subprocess.run(
        [
            sys.executable,
            "scripts/update_fast_regression_baselines.py",
            "--generate-candidate",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "--candidate-dir is required" in result.stderr


def test_acceptance_requires_reason_and_review_reference(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "scripts/update_fast_regression_baselines.py",
            "--accept-baseline-update",
            "--candidate-dir",
            str(tmp_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "--reason is required" in result.stderr


def test_acceptance_is_forbidden_while_pytest_is_running(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "scripts/update_fast_regression_baselines.py",
            "--accept-baseline-update",
            "--candidate-dir",
            str(tmp_path),
            "--reason",
            "tolerances re-derived",
            "--review-reference",
            "AO-REF-000",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTEST_CURRENT_TEST": "fast-baseline-guard"},
    )

    assert result.returncode != 0
    assert "forbidden while pytest is running" in result.stderr


@pytest.fixture()
def packaged_tree(tmp_path, monkeypatch):
    """A throwaway copy of the packaged fast baselines the script may write to."""

    destination = tmp_path / "src" / "shwfs_ao" / "resources" / "reference_metrics"
    destination.mkdir(parents=True)
    for name in (
        "fast_reference_metrics.json",
        "fast_reference_metrics_regression_baseline.json",
        "fast_error_budget_regression_baseline.csv",
        "fast_validation_regression_baseline.csv",
    ):
        (destination / name).write_bytes((_PACKAGED / name).read_bytes())
    monkeypatch.setattr(script, "ROOT", tmp_path)
    monkeypatch.setattr(script, "DESTINATION_DIR", destination)
    return destination


def _write_candidate(candidate_dir: Path) -> None:
    candidate_dir.mkdir(parents=True, exist_ok=True)
    for candidate_name, packaged_name in _CANDIDATE_SOURCES.items():
        (candidate_dir / candidate_name).write_bytes(
            (_PACKAGED / packaged_name).read_bytes()
        )


def _write_reviewed_diff(candidate_dir: Path) -> None:
    diff = script._build_diff(candidate_dir)
    (candidate_dir / script.DIFF_JSON).write_text(
        json.dumps(diff, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (candidate_dir / script.DIFF_MARKDOWN).write_text(
        script._render_diff_markdown(diff),
        encoding="utf-8",
    )


def _rewrite_reference(candidate_dir: Path, mutate) -> None:
    path = candidate_dir / "fast_reference_metrics.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _rewrite_table(path: Path, mutate) -> None:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        header = list(reader.fieldnames or ())
        rows = list(reader)
    mutate(rows)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _inflate_reference_closed_rms(rows: list[dict[str, str]]) -> None:
    for row in rows:
        if row["scenario_name"] == "all_effects":
            row["closed_rms_nm"] = "1000000000.0"


def _fail_every_check(rows: list[dict[str, str]]) -> None:
    for row in rows:
        row["passed"] = "False"


class TestCandidateContract:
    def test_a_packaged_shaped_candidate_passes(self, packaged_tree, tmp_path):
        candidate_dir = tmp_path / "candidate"
        _write_candidate(candidate_dir)
        script._validate_candidate(candidate_dir)

    def test_a_non_v2_schema_version_is_refused(self, packaged_tree, tmp_path):
        candidate_dir = tmp_path / "candidate"
        _write_candidate(candidate_dir)
        _rewrite_reference(
            candidate_dir,
            lambda payload: payload.update(schema_version=3),
        )
        with pytest.raises(SystemExit, match="schema-v2"):
            script._validate_candidate(candidate_dir)

    def test_a_missing_tolerance_key_is_refused(self, packaged_tree, tmp_path):
        candidate_dir = tmp_path / "candidate"
        _write_candidate(candidate_dir)
        _rewrite_reference(
            candidate_dir,
            lambda payload: payload["tolerances"].pop("h_strehl_abs"),
        )
        with pytest.raises(SystemExit, match="schema-v2 contract"):
            script._validate_candidate(candidate_dir)

    def test_a_v3_extended_csv_header_is_refused(self, packaged_tree, tmp_path):
        candidate_dir = tmp_path / "candidate"
        _write_candidate(candidate_dir)
        table = candidate_dir / "fast_error_budget.csv"
        lines = table.read_text(encoding="utf-8").splitlines()
        lines[0] += ",artifact_schema_version,artifact_kind,backend,system_profile"
        lines[1:] = [line + ",3,run_result,native,fast" for line in lines[1:]]
        table.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(SystemExit, match="frozen schema-v2 header"):
            script._validate_candidate(candidate_dir)

    def test_a_duplicate_scenario_row_is_refused(self, packaged_tree, tmp_path):
        candidate_dir = tmp_path / "candidate"
        _write_candidate(candidate_dir)
        table = candidate_dir / "fast_error_budget.csv"
        lines = table.read_text(encoding="utf-8").splitlines()
        lines.append(lines[-1])
        table.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(SystemExit, match="duplicate scenario_name"):
            script._validate_candidate(candidate_dir)

    def test_a_scenario_inventory_mismatch_is_refused(
        self,
        packaged_tree,
        tmp_path,
    ):
        candidate_dir = tmp_path / "candidate"
        _write_candidate(candidate_dir)
        table = candidate_dir / "fast_error_budget.csv"
        lines = table.read_text(encoding="utf-8").splitlines()
        del lines[1]
        table.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(SystemExit, match="scenario inventory"):
            script._validate_candidate(candidate_dir)

    def test_a_validation_check_count_mismatch_is_refused(
        self,
        packaged_tree,
        tmp_path,
    ):
        candidate_dir = tmp_path / "candidate"
        _write_candidate(candidate_dir)
        _rewrite_reference(
            candidate_dir,
            lambda payload: payload.update(validation_check_count=7),
        )
        with pytest.raises(
            SystemExit,
            match="distinct validation-check inventory",
        ):
            script._validate_candidate(candidate_dir)

    def test_a_reference_metric_disagreeing_with_its_scenario_row_is_refused(
        self,
        packaged_tree,
        tmp_path,
    ):
        candidate_dir = tmp_path / "candidate"
        _write_candidate(candidate_dir)
        _rewrite_table(
            candidate_dir / "fast_error_budget.csv",
            _inflate_reference_closed_rms,
        )
        with pytest.raises(SystemExit, match="closed_rms_nm=.* disagrees"):
            script._validate_candidate(candidate_dir)

    def test_a_passing_check_count_mismatch_is_refused(
        self,
        packaged_tree,
        tmp_path,
    ):
        candidate_dir = tmp_path / "candidate"
        _write_candidate(candidate_dir)
        _rewrite_table(candidate_dir / "fast_validation.csv", _fail_every_check)
        with pytest.raises(SystemExit, match="has 0 passing checks"):
            script._validate_candidate(candidate_dir)

    def test_contradictory_rows_of_one_check_are_refused(
        self,
        packaged_tree,
        tmp_path,
    ):
        candidate_dir = tmp_path / "candidate"
        _write_candidate(candidate_dir)

        def contradict_one_scan_sample(rows: list[dict[str, str]]) -> None:
            names = [row["check_name"] for row in rows]
            scan = next(name for name in names if names.count(name) > 1)
            rows[names.index(scan)]["passed"] = "False"

        _rewrite_table(
            candidate_dir / "fast_validation.csv",
            contradict_one_scan_sample,
        )
        with pytest.raises(SystemExit, match="contradictory passed values"):
            script._validate_candidate(candidate_dir)


class TestAcceptanceEvidence:
    def test_acceptance_persists_reason_review_reference_and_hashes(
        self,
        packaged_tree,
        tmp_path,
    ):
        candidate_dir = tmp_path / "candidate"
        _write_candidate(candidate_dir)
        _write_reviewed_diff(candidate_dir)
        script._accept_reviewed_candidate(
            candidate_dir,
            reason="Reviewed physical change in the fast preset.",
            review_reference="PR-4242",
        )
        record = json.loads(
            (packaged_tree / script.ACCEPTANCE_RECORD_NAME).read_text(
                encoding="utf-8"
            )
        )
        assert record["schema_name"] == "shwfs_ao.fast_baseline_acceptance"
        assert record["schema_version"] == 1
        assert record["reason"] == (
            "Reviewed physical change in the fast preset."
        )
        assert record["review_reference"] == "PR-4242"
        assert record["accepted_at_utc"]
        assert record["reviewed_diff_sha256"] == script._sha256(
            candidate_dir / script.DIFF_JSON
        )
        by_name = {
            entry["baseline_name"]: entry["sha256"]
            for entry in record["accepted_files"]
        }
        assert set(by_name) == {
            "fast_reference_metrics.json",
            "fast_reference_metrics_regression_baseline.json",
            "fast_error_budget_regression_baseline.csv",
            "fast_validation_regression_baseline.csv",
        }
        for name, digest in by_name.items():
            assert digest == script._sha256(packaged_tree / name)
        manifest = json.loads(
            (packaged_tree.parent / "resource_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        names = [record["logical_name"] for record in manifest["resources"]]
        assert f"reference_metrics/{script.ACCEPTANCE_RECORD_NAME}" in names

    def test_a_post_review_table_edit_is_refused(self, packaged_tree, tmp_path):
        candidate_dir = tmp_path / "candidate"
        _write_candidate(candidate_dir)
        _write_reviewed_diff(candidate_dir)
        table = candidate_dir / "fast_validation.csv"
        table.write_bytes(table.read_bytes() + b"\n")
        with pytest.raises(SystemExit, match="changed after diff generation"):
            script._accept_reviewed_candidate(
                candidate_dir,
                reason="tampered",
                review_reference="PR-4242",
            )
        assert not (packaged_tree / script.ACCEPTANCE_RECORD_NAME).exists()

    def test_an_internally_inconsistent_candidate_is_never_copied(
        self,
        packaged_tree,
        tmp_path,
    ):
        candidate_dir = tmp_path / "candidate"
        _write_candidate(candidate_dir)
        _rewrite_table(
            candidate_dir / "fast_error_budget.csv",
            _inflate_reference_closed_rms,
        )
        _rewrite_table(candidate_dir / "fast_validation.csv", _fail_every_check)
        # The reviewed diff matches the tampered bytes, so only the JSON/CSV
        # reconciliation stands between this candidate and the package.
        _write_reviewed_diff(candidate_dir)
        before = {path.name: path.read_bytes() for path in packaged_tree.iterdir()}
        with pytest.raises(SystemExit, match="disagrees"):
            script._accept_reviewed_candidate(
                candidate_dir,
                reason="inconsistent",
                review_reference="PR-4242",
            )
        after = {path.name: path.read_bytes() for path in packaged_tree.iterdir()}
        assert after == before
