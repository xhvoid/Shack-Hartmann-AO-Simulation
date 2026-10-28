"""Guards on the physical-baseline candidate and acceptance workflow.

The physical updater is imported in-process and pointed at a throwaway copy of
the packaged baselines.  No test in this module can modify the repository's
accepted resources.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_SPEC = importlib.util.spec_from_file_location(
    "physical_baseline_script_for_tests",
    ROOT / "scripts" / "update_physical_regression_baselines.py",
)
assert _SCRIPT_SPEC is not None and _SCRIPT_SPEC.loader is not None
script = importlib.util.module_from_spec(_SCRIPT_SPEC)
sys.modules[_SCRIPT_SPEC.name] = script
_SCRIPT_SPEC.loader.exec_module(script)

_PACKAGED = ROOT / "src" / "shwfs_ao" / "resources" / "reference_metrics"
_CANDIDATE_SOURCES = {
    "physical_reference_metrics.json": (
        "physical_reference_metrics_regression_baseline.json"
    ),
    "physical_error_budget.csv": "physical_error_budget_regression_baseline.csv",
    "physical_validation.csv": "physical_validation_regression_baseline.csv",
}


@pytest.fixture()
def packaged_tree(tmp_path, monkeypatch):
    """Return a writable stand-in for the canonical reference-metrics tree."""

    destination = tmp_path / "src" / "shwfs_ao" / "resources" / "reference_metrics"
    destination.mkdir(parents=True)
    for name in (
        "physical_reference_metrics.json",
        "physical_reference_metrics_regression_baseline.json",
        "physical_error_budget_regression_baseline.csv",
        "physical_validation_regression_baseline.csv",
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


def _rewrite_csv(path: Path, mutate) -> None:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or ())
        rows = list(reader)
    mutate(rows)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_reviewed_diff(candidate_dir: Path) -> Path:
    path = candidate_dir / script.DIFF_JSON
    path.write_text(
        json.dumps(script._build_diff(candidate_dir), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestPhysicalCandidateContract:
    def test_a_packaged_shaped_candidate_passes(self, packaged_tree, tmp_path):
        candidate_dir = tmp_path / "candidate"
        _write_candidate(candidate_dir)

        script._validate_candidate(candidate_dir)

    def test_mixed_physical_json_and_fast_tables_are_refused(
        self,
        packaged_tree,
        tmp_path,
    ):
        candidate_dir = tmp_path / "candidate"
        _write_candidate(candidate_dir)
        (candidate_dir / "physical_error_budget.csv").write_bytes(
            (_PACKAGED / "fast_error_budget_regression_baseline.csv").read_bytes()
        )
        (candidate_dir / "physical_validation.csv").write_bytes(
            (_PACKAGED / "fast_validation_regression_baseline.csv").read_bytes()
        )

        with pytest.raises(SystemExit, match="disagrees with reference scenario"):
            script._validate_candidate(candidate_dir)

    def test_a_non_v2_scenario_header_is_refused(self, packaged_tree, tmp_path):
        candidate_dir = tmp_path / "candidate"
        _write_candidate(candidate_dir)
        table = candidate_dir / "physical_error_budget.csv"
        lines = table.read_text(encoding="utf-8").splitlines()
        lines[0] += ",unexpected"
        lines[1:] = [line + ",value" for line in lines[1:]]
        table.write_text("\n".join(lines) + "\n", encoding="utf-8")

        with pytest.raises(SystemExit, match="frozen schema-v2 header"):
            script._validate_candidate(candidate_dir)

    def test_nonfinite_scenario_metrics_are_refused(self, packaged_tree, tmp_path):
        candidate_dir = tmp_path / "candidate"
        _write_candidate(candidate_dir)
        _rewrite_csv(
            candidate_dir / "physical_error_budget.csv",
            lambda rows: rows[0].update(strehl_J="nan"),
        )

        with pytest.raises(SystemExit, match="non-finite strehl_J"):
            script._validate_candidate(candidate_dir)

    def test_nonfinite_validation_metrics_are_refused(self, packaged_tree, tmp_path):
        candidate_dir = tmp_path / "candidate"
        _write_candidate(candidate_dir)
        _rewrite_csv(
            candidate_dir / "physical_validation.csv",
            lambda rows: rows[0].update(metric_value="inf"),
        )

        with pytest.raises(SystemExit, match="non-finite metric_value"):
            script._validate_candidate(candidate_dir)

    def test_reference_scenario_headlines_must_match_the_json(
        self,
        packaged_tree,
        tmp_path,
    ):
        candidate_dir = tmp_path / "candidate"
        _write_candidate(candidate_dir)
        _rewrite_csv(
            candidate_dir / "physical_error_budget.csv",
            lambda rows: rows[-1].update(
                open_rms_nm=str(float(rows[-1]["open_rms_nm"]) + 1.0),
                closed_over_open_rms=str(
                    float(rows[-1]["closed_rms_nm"])
                    / (float(rows[-1]["open_rms_nm"]) + 1.0)
                ),
            ),
        )

        with pytest.raises(SystemExit, match="open_rms_nm=.*disagrees"):
            script._validate_candidate(candidate_dir)


class TestPhysicalAcceptanceEvidence:
    def test_diff_binds_every_candidate_and_destination_file(
        self,
        packaged_tree,
        tmp_path,
    ):
        candidate_dir = tmp_path / "candidate"
        _write_candidate(candidate_dir)

        diff = script._build_diff(candidate_dir)

        assert diff["schema_name"] == "shwfs_ao.physical_baseline_diff"
        assert len(diff["files"]) == 4
        expected_pairs = {
            (candidate_name, baseline_name)
            for candidate_name, baseline_names in script.DESTINATIONS.items()
            for baseline_name in baseline_names
        }
        assert {
            (entry["candidate_name"], entry["baseline_name"])
            for entry in diff["files"]
        } == expected_pairs
        for entry in diff["files"]:
            assert entry["candidate_sha256"] == _sha256(
                candidate_dir / entry["candidate_name"]
            )
            assert entry["current_sha256"] == _sha256(
                packaged_tree / entry["baseline_name"]
            )

    def test_acceptance_requires_a_generated_reviewed_diff(
        self,
        packaged_tree,
        tmp_path,
    ):
        candidate_dir = tmp_path / "candidate"
        _write_candidate(candidate_dir)

        with pytest.raises(SystemExit, match="Missing generated machine-readable diff"):
            script._accept_reviewed_candidate(
                candidate_dir,
                reason="Reviewed physical correction.",
                review_reference="PR-600",
            )

    def test_a_post_review_candidate_edit_is_refused(self, packaged_tree, tmp_path):
        candidate_dir = tmp_path / "candidate"
        _write_candidate(candidate_dir)
        _write_reviewed_diff(candidate_dir)
        table = candidate_dir / "physical_validation.csv"
        table.write_bytes(table.read_bytes() + b"\n")

        with pytest.raises(SystemExit, match="changed after diff generation"):
            script._accept_reviewed_candidate(
                candidate_dir,
                reason="Tampered candidate.",
                review_reference="PR-600",
            )

    def test_a_post_review_packaged_baseline_edit_is_refused(
        self,
        packaged_tree,
        tmp_path,
    ):
        candidate_dir = tmp_path / "candidate"
        _write_candidate(candidate_dir)
        _write_reviewed_diff(candidate_dir)
        baseline = packaged_tree / "physical_error_budget_regression_baseline.csv"
        baseline.write_bytes(baseline.read_bytes() + b"\n")

        with pytest.raises(SystemExit, match="changed after diff generation"):
            script._accept_reviewed_candidate(
                candidate_dir,
                reason="Stale review.",
                review_reference="PR-600",
            )

    def test_acceptance_persists_reviewed_diff_and_file_hashes(
        self,
        packaged_tree,
        tmp_path,
    ):
        candidate_dir = tmp_path / "candidate"
        _write_candidate(candidate_dir)
        reviewed_diff = _write_reviewed_diff(candidate_dir)

        script._accept_reviewed_candidate(
            candidate_dir,
            reason="Reviewed physical correction.",
            review_reference="PR-600",
        )

        record = json.loads(
            (packaged_tree / script.ACCEPTANCE_RECORD_NAME).read_text(
                encoding="utf-8"
            )
        )
        assert record["reviewed_diff_sha256"] == _sha256(reviewed_diff)
        assert record["reason"] == "Reviewed physical correction."
        assert record["review_reference"] == "PR-600"
        by_name = {
            entry["name"]: entry["sha256"] for entry in record["accepted_files"]
        }
        assert set(by_name) == {
            name for names in script.DESTINATIONS.values() for name in names
        }
        for name, digest in by_name.items():
            assert digest == _sha256(packaged_tree / name)

