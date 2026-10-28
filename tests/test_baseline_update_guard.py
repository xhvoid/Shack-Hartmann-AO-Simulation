from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


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
