"""Guards on the cross-backend candidate/acceptance workflow.

AO-REF-018 requires that tests, notebooks, and ordinary example runs can
never update the packaged cross-backend baseline: candidate generation
writes only to an explicit external directory, and acceptance is a separate
explicit command with a human-readable reason and a review reference.
These subprocess tests pin every refusal path of
``scripts/generate_cross_backend_candidate.py`` without ever running the
comparison suite itself.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = "scripts/generate_cross_backend_candidate.py"


def _run(*arguments: str, env: dict[str, str] | None = None):
    return subprocess.run(
        [sys.executable, SCRIPT, *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
    )


def test_baseline_update_requires_explicit_maintainer_acknowledgement():
    result = _run()

    assert result.returncode != 0
    assert "--accept-baseline-update is required" in result.stderr


def test_candidate_generation_requires_an_explicit_external_directory():
    result = _run("--generate-candidate")

    assert result.returncode != 0
    assert "--candidate-dir is required" in result.stderr


def test_the_packaged_resource_tree_is_never_a_candidate_destination():
    packaged = ROOT / "src" / "shwfs_ao" / "resources"
    for destination in (
        packaged,
        packaged / "reference_metrics" / "cross_backend",
    ):
        result = _run(
            "--generate-candidate",
            "--candidate-dir",
            str(destination),
        )

        assert result.returncode != 0
        assert "outside the packaged resource tree" in result.stderr


def test_candidate_generation_rejects_acceptance_metadata(tmp_path):
    result = _run(
        "--generate-candidate",
        "--candidate-dir",
        str(tmp_path),
        "--reason",
        "not valid here",
    )

    assert result.returncode != 0
    assert "Acceptance metadata is not valid" in result.stderr


def test_candidate_generation_refuses_to_overwrite_existing_files(tmp_path):
    # The collision check precedes the comparison suite (and therefore the
    # optional dependency), so this refusal must hold in every environment.
    (tmp_path / "cross_backend_candidate.json").write_text(
        "{}",
        encoding="utf-8",
    )
    result = _run(
        "--generate-candidate",
        "--candidate-dir",
        str(tmp_path),
    )

    assert result.returncode != 0
    assert "refuses to overwrite" in result.stderr


def test_acceptance_requires_reason_and_review_reference(tmp_path):
    result = _run(
        "--accept-baseline-update",
        "--candidate-dir",
        str(tmp_path),
    )

    assert result.returncode != 0
    assert "--reason is required" in result.stderr

    result = _run(
        "--accept-baseline-update",
        "--candidate-dir",
        str(tmp_path),
        "--reason",
        "tolerances re-derived",
    )

    assert result.returncode != 0
    assert "--review-reference is required" in result.stderr


def test_acceptance_is_forbidden_while_pytest_is_running(tmp_path):
    result = _run(
        "--accept-baseline-update",
        "--candidate-dir",
        str(tmp_path),
        "--reason",
        "tolerances re-derived",
        "--review-reference",
        "AO-REF-018",
        env={**os.environ, "PYTEST_CURRENT_TEST": "cross-backend-guard"},
    )

    assert result.returncode != 0
    assert "forbidden while pytest is running" in result.stderr


def test_acceptance_outside_pytest_still_requires_a_reviewed_candidate(
    tmp_path,
):
    # Stripping the pytest marker variable shows the guard above, not the
    # argument checks, is what blocked the previous invocation; acceptance
    # then refuses to proceed without a generated-and-reviewed candidate.
    environment = {
        key: value
        for key, value in os.environ.items()
        if key != "PYTEST_CURRENT_TEST"
    }
    result = _run(
        "--accept-baseline-update",
        "--candidate-dir",
        str(tmp_path),
        "--reason",
        "tolerances re-derived",
        "--review-reference",
        "AO-REF-018",
        env=environment,
    )

    assert result.returncode != 0
    assert "Missing reviewed candidate" in (result.stderr + result.stdout)
