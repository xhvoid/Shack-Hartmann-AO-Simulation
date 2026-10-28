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

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = "scripts/generate_cross_backend_candidate.py"

# scripts/ is a path-addressed tool directory, not an importable package, so the
# few guards that are cheaper to drive directly than through a subprocess are
# loaded by file — the same pattern the notebook-runner tests use.
_GENERATOR_SPEC = importlib.util.spec_from_file_location(
    "generate_cross_backend_candidate_for_guard_tests",
    ROOT / SCRIPT,
)
assert _GENERATOR_SPEC is not None and _GENERATOR_SPEC.loader is not None
generator = importlib.util.module_from_spec(_GENERATOR_SPEC)
sys.modules[_GENERATOR_SPEC.name] = generator
_GENERATOR_SPEC.loader.exec_module(generator)


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


def test_a_candidate_is_only_generated_by_this_repository_s_own_package(tmp_path):
    """Provenance names this checkout, so this checkout's code must run.

    ``source_commit`` is read from the repository while the physics is executed
    by whichever ``shwfs_ao`` the interpreter resolves.  A foreign or stale
    installed copy shadowing the checkout would therefore produce numbers
    attributed to a commit that never produced them, and "check out this commit
    and re-run" would not reproduce the baseline.
    """

    foreign = tmp_path / "foreign"
    (foreign / "shwfs_ao").mkdir(parents=True)
    (foreign / "shwfs_ao" / "__init__.py").write_text("", encoding="utf-8")
    destination = tmp_path / "candidate"

    for operation in (
        ("--generate-candidate",),
        (
            "--accept-baseline-update",
            "--reason",
            "tolerances re-derived",
            "--review-reference",
            "AO-REF-018",
        ),
    ):
        result = _run(
            *operation,
            "--candidate-dir",
            str(destination),
            env={
                **{
                    key: value
                    for key, value in os.environ.items()
                    if key != "PYTEST_CURRENT_TEST"
                },
                "PYTHONPATH": str(foreign),
            },
        )

        assert result.returncode != 0
        message = result.stderr + result.stdout
        assert "The imported shwfs_ao package is" in message
        assert str(foreign / "shwfs_ao") in message
    # The refusal precedes every write, including the candidate directory.
    assert not destination.exists()


def test_the_executed_package_check_accepts_this_checkout():
    assert generator._require_executed_package_is_this_checkout() == (
        (ROOT / "src" / "shwfs_ao").resolve()
    )


def test_a_candidate_is_refused_when_head_moves_while_the_suite_runs(monkeypatch):
    """Two clean commits leave no patch evidence of the switch between them.

    The suite takes minutes.  If HEAD moves during it, the earlier and later
    parts of the run executed different code, and the candidate would name only
    the first — with ``source_patch_sha256`` ``None`` on both sides, so nothing
    else in the record contradicts it.
    """

    before = "a" * 40
    after = "b" * 40
    monkeypatch.setattr(generator, "_source_patch_sha256", lambda: None)

    monkeypatch.setattr(generator, "_source_commit", lambda: after)
    with pytest.raises(SystemExit, match=f"HEAD moved from {before}"):
        generator._require_source_unchanged(before, None)

    # A stationary clean checkout passes, and a working tree that changed under
    # an unmoved HEAD is still caught by the patch hash.
    monkeypatch.setattr(generator, "_source_commit", lambda: before)
    generator._require_source_unchanged(before, None)

    monkeypatch.setattr(generator, "_source_patch_sha256", lambda: "c" * 64)
    with pytest.raises(SystemExit, match="working tree changed"):
        generator._require_source_unchanged(before, None)
