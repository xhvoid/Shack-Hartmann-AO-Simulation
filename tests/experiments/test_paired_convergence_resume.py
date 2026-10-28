"""independent review AR-014: the S3 study resumes only its own runs.

The study script is loaded by file, as the other script-guard tests do.  Its
child launcher is replaced by a stand-in that writes the row a child would,
with stand-in results, so no simulation runs; the producer identity of the
invocation is a controlled stand-in.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "eso_scao_paired_convergence_study_for_guard_tests",
    ROOT / "scripts/eso_scao_paired_convergence_study.py",
)
assert _SPEC is not None and _SPEC.loader is not None
study = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = study
_SPEC.loader.exec_module(study)

EVIDENCE = ROOT / "docs/refactor/eso_scao_evidence"
# Captured before any fixture replaces it with a stand-in producer.
REAL_CODE_IDENTITY = study._code_identity
CODE_A = {"package_directory": "src", "script_sha256": "script A", "git_head": "head A", "source_changes_sha256": "diff A"}
ENVIRONMENT_A = {"python": "3.x A", "numpy": "numpy A", "scipy": "scipy A", "machine": "arm64"}
PRODUCER_A = {"code": CODE_A, "environment": ENVIRONMENT_A}
PRODUCER_B = {"code": CODE_A, "environment": {**ENVIRONMENT_A, "numpy": "numpy B"}}


def stand_in_row(scale: str, setting: tuple[str, int, int, int, int], made_by: dict) -> dict:
    """The row a child of ``made_by`` would write, with deterministic stand-in results."""

    label, samples, wfs_pad, science_pad, realization = setting
    planned = study._planned_protocol(scale, *setting)
    row: dict = {name: planned[name] for name in study.REPEATED_FIELDS}
    row["screen_size"] = 2 * study.LENSLETS[scale] * samples
    index = samples + 10 * wfs_pad + 100 * science_pad + realization
    row.update(
        peak_strehl=0.5 + 0.001 * index,
        ee50_radius_rad=1.0e-7 * (1.0 + 0.001 * index),
        residual_rms_nm=100.0 + index,
        open_loop_rms_nm=1000.0,
        build_s=0.0,
        loop_s=0.0,
        ru_maxrss=1,
    )
    row.update(study.run_protocol(scale, *setting, made_by))
    return row


class Launcher:
    """Stands in for ``_launch_child``: records the call and writes the child's row."""

    def __init__(self, made_by: dict | None = None) -> None:
        self.calls: list[str] = []
        self.made_by = made_by

    def __call__(self, scale, directory, setting, path) -> None:
        self.calls.append(path.stem)
        study._write_json(path, stand_in_row(scale, setting, self.made_by or study.producer()))


def act_as(monkeypatch: pytest.MonkeyPatch, made_by: dict) -> None:
    monkeypatch.setattr(study, "_code_identity", lambda: json.loads(json.dumps(made_by["code"])))
    monkeypatch.setattr(study, "producer_environment", lambda: dict(made_by["environment"]))


@pytest.fixture(autouse=True)
def controlled(monkeypatch: pytest.MonkeyPatch) -> Launcher:
    act_as(monkeypatch, PRODUCER_A)
    launcher = Launcher()
    monkeypatch.setattr(study, "_launch_child", launcher)
    return launcher


def run(directory: Path, scale: str = "ci") -> int:
    return study.main(["--scale", scale, "--output-dir", str(directory)])


def snapshot(directory: Path) -> dict[str, tuple[bytes, int]]:
    return {
        str(path.relative_to(directory)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def save(directory: Path, scale: str, keys: list[str], made_by: dict) -> None:
    (directory / "runs").mkdir(parents=True, exist_ok=True)
    plan = study._plan(scale)
    for key in keys:
        (directory / "runs" / f"{key}.json").write_text(json.dumps(stand_in_row(scale, plan[key], made_by), indent=1) + "\n")


def refused(directory: Path, launcher: Launcher, match: str, scale: str = "ci") -> None:
    before = snapshot(directory)
    with pytest.raises(study.StudyRecordError, match=match):
        run(directory, scale)
    assert launcher.calls == []
    assert snapshot(directory) == before


CI_KEYS = list(study._plan("ci"))


def test_a_fresh_study_runs_each_planned_run_once_and_names_its_producer(tmp_path: Path, controlled: Launcher) -> None:
    assert run(tmp_path) == 0
    assert controlled.calls == CI_KEYS and all(key.startswith("ci_") for key in CI_KEYS)
    record = json.loads((tmp_path / "paired_convergence_ci.json").read_text())
    assert record["schema"] == "shwfs_ao.eso_scao_paired_convergence_study.v2"
    assert record["run_producer"] == record["summarized_by"] == PRODUCER_A
    for key, row in record["runs"].items():
        assert row == json.loads((tmp_path / "runs" / f"{key}.json").read_text())
        assert row["protocol_hash"] == study._digest(row["protocol"])
        assert row["protocol"]["scale"] == "ci"
    assert not list(tmp_path.rglob("*.partial"))


def test_run_keys_name_the_scale() -> None:
    # Version-1 keys named no scale, so every full-study key was a medium one.
    legacy = {
        scale: {study._legacy_run_key(*setting[1:]) for setting in study._plan(scale).values()}
        for scale in ("medium", "full")
    }
    assert legacy["full"] <= legacy["medium"]
    assert set(study._plan("full")).isdisjoint(study._plan("medium"))


def test_the_committed_medium_rows_are_not_taken_for_a_full_study(tmp_path: Path, controlled: Launcher) -> None:
    # The review's natural counterexample: valid version-1 medium rows under
    # their own names, then the full-scale driver in the same directory.
    medium = json.loads((EVIDENCE / "paired_convergence_medium.json").read_text())
    (tmp_path / "runs").mkdir()
    for key, row in medium["runs"].items():
        (tmp_path / "runs" / f"{key}.json").write_text(json.dumps(row))
    refused(tmp_path, controlled, "version-1 run files", scale="full")
    assert not (tmp_path / "paired_convergence_full.json").exists()


def test_a_row_of_another_scale_under_a_full_key_is_refused(tmp_path: Path, controlled: Launcher) -> None:
    medium = study._plan("medium")
    (tmp_path / "runs").mkdir()
    for key, setting in study._plan("full").items():
        row = stand_in_row("medium", medium[key.replace("full_", "medium_", 1)], PRODUCER_A)
        (tmp_path / "runs" / f"{key}.json").write_text(json.dumps(row))
    refused(tmp_path, controlled, r"not this study's planned run .*scale", scale="full")


def test_medium_runs_in_the_same_directory_are_left_alone(tmp_path: Path, controlled: Launcher) -> None:
    save(tmp_path, "medium", list(study._plan("medium")), PRODUCER_A)
    medium_files = snapshot(tmp_path)
    assert run(tmp_path, "full") == 0
    full = study._plan("full")
    assert controlled.calls == list(full)
    record = json.loads((tmp_path / "paired_convergence_full.json").read_text())
    assert {row["protocol"]["scale"] for row in record["runs"].values()} == {"full"}
    assert [row["config_hash"] for row in record["runs"].values()] == [
        study._planned_protocol("full", *setting)["config_hash"] for setting in full.values()
    ]
    assert {name: value for name, value in snapshot(tmp_path).items() if name in medium_files} == medium_files


def test_rows_without_a_run_protocol_are_neither_reused_nor_relabelled(tmp_path: Path, controlled: Launcher) -> None:
    # The review's first counterexample, under the driver's own file names.
    stale = {"label": "old-config", "config_hash": "wrong-config-hash", "peak_strehl": 0.5, "ee50_radius_rad": 1e-7,
             "residual_rms_nm": 100.0, "open_loop_rms_nm": 1000.0, "build_s": 0.0, "loop_s": 0.0, "ru_maxrss": 1}
    (tmp_path / "runs").mkdir()
    for key in CI_KEYS:
        (tmp_path / "runs" / f"{key}.json").write_text(json.dumps(stale))
    refused(tmp_path, controlled, "carries no run protocol")
    assert not (tmp_path / "paired_convergence_ci.json").exists()


def _rehash(row: dict) -> None:
    row["protocol_hash"] = study._digest(row["protocol"])


CORRUPTIONS = {
    "stored hash": (lambda row: row.update(protocol_hash="0" * 64), "not the digest"),
    "payload under a stale hash": (lambda row: row["protocol"].update(config_hash="changed"), "not the digest"),
    "another configuration": (lambda row: (row["protocol"].update(config_hash="changed"), _rehash(row)), "differs in \\['config_hash'\\]"),
    "another producer field": (lambda row: (row["protocol"].update(extra=1), _rehash(row)), "other fields"),
    "repeated realization": (lambda row: row.update(realization=7), "disagree"),
    "repeated realization as a boolean": (lambda row: row.update(realization=False), "disagree"),
    "screen size": (lambda row: row.update(screen_size=1), "disagree"),
    "missing result": (lambda row: row.pop("peak_strehl"), "missing or not numbers"),
    "non-numeric result": (lambda row: row.update(ee50_radius_rad="1e-7"), "missing or not numbers"),
    "boolean result": (lambda row: row.update(peak_strehl=True), "missing or not numbers"),
    "producer not an identity": (lambda row: (row["protocol"].update(code="head A"), _rehash(row)), "not a code identity"),
}


@pytest.mark.parametrize("corruption", sorted(CORRUPTIONS))
def test_an_inconsistent_saved_run_is_refused_before_anything_runs(tmp_path: Path, controlled: Launcher, corruption: str) -> None:
    save(tmp_path, "ci", CI_KEYS[:2], PRODUCER_A)
    path = tmp_path / "runs" / f"{CI_KEYS[0]}.json"
    row = json.loads(path.read_text())
    change, match = CORRUPTIONS[corruption]
    change(row)
    path.write_text(json.dumps(row))
    refused(tmp_path, controlled, match)


def test_an_unreadable_run_file_is_refused(tmp_path: Path, controlled: Launcher) -> None:
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / f"{CI_KEYS[0]}.json").write_text("{")
    refused(tmp_path, controlled, "not readable JSON")
    (tmp_path / "runs" / f"{CI_KEYS[0]}.json").unlink()
    (tmp_path / "runs" / f"{CI_KEYS[0]}.json").mkdir()  # a directory under a run's name
    refused(tmp_path, controlled, "not readable JSON")


def test_an_interrupted_study_runs_only_the_missing_runs(tmp_path: Path, controlled: Launcher) -> None:
    save(tmp_path, "ci", CI_KEYS[:2], PRODUCER_A)
    kept = snapshot(tmp_path)
    assert run(tmp_path) == 0
    assert controlled.calls == CI_KEYS[2:]
    assert {name: value for name, value in snapshot(tmp_path).items() if name in kept} == kept
    whole = tmp_path / "whole"
    assert run(whole) == 0
    split = json.loads((tmp_path / "paired_convergence_ci.json").read_text())
    assert split == json.loads((whole / "paired_convergence_ci.json").read_text())


@pytest.mark.parametrize("change", ["environment", "code"])
def test_runs_are_not_added_under_another_producer(
    tmp_path: Path, controlled: Launcher, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    save(tmp_path, "ci", CI_KEYS[:2], PRODUCER_A)
    other = PRODUCER_B if change == "environment" else {"code": {**CODE_A, "git_head": "head B"}, "environment": ENVIRONMENT_A}
    act_as(monkeypatch, other)
    refused(tmp_path, controlled, "would mix producers")


def test_runs_are_not_added_while_the_code_identity_is_unknown(
    tmp_path: Path, controlled: Launcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    unknown = {"code": {"package_directory": "src", "script_sha256": "script A", "git_head": None}, "environment": ENVIRONMENT_A}
    save(tmp_path, "ci", CI_KEYS[:2], unknown)
    act_as(monkeypatch, unknown)
    refused(tmp_path, controlled, "code identity of this invocation is unknown")


def test_finished_runs_of_another_producer_are_summarized_under_their_own_producer(
    tmp_path: Path, controlled: Launcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    save(tmp_path, "ci", CI_KEYS, PRODUCER_A)
    rows = snapshot(tmp_path)
    act_as(monkeypatch, PRODUCER_B)
    assert run(tmp_path) == 0
    assert controlled.calls == []
    record = json.loads((tmp_path / "paired_convergence_ci.json").read_text())
    assert record["run_producer"] == PRODUCER_A
    assert record["summarized_by"] == PRODUCER_B
    assert {name: value for name, value in snapshot(tmp_path).items() if name in rows} == rows


def test_runs_of_two_producers_are_not_summarized_together(tmp_path: Path, controlled: Launcher) -> None:
    save(tmp_path, "ci", CI_KEYS[:2], PRODUCER_A)
    save(tmp_path, "ci", CI_KEYS[2:], PRODUCER_B)
    refused(tmp_path, controlled, "2 different producers")
    assert not (tmp_path / "paired_convergence_ci.json").exists()


def test_a_finished_study_is_left_unchanged(
    tmp_path: Path, controlled: Launcher, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(tmp_path) == 0
    controlled.calls.clear()
    before = snapshot(tmp_path)
    for made_by in (PRODUCER_A, PRODUCER_B):  # the same process, and a later one
        act_as(monkeypatch, made_by)
        capsys.readouterr()
        assert run(tmp_path) == 0
        assert "nothing ran and no file was changed" in capsys.readouterr().out
        assert controlled.calls == []
        assert snapshot(tmp_path) == before


SUMMARY_TAMPERING = {
    "a summary value": lambda record: record["scans"]["wfs_pad_factor"]["entries"][0].update(peak_strehl_mean=0.9),
    "the run producer": lambda record: record.update(run_producer=PRODUCER_B),
    "an embedded run": lambda record: record["runs"][CI_KEYS[0]].update(peak_strehl=0.1),
    "the schema": lambda record: record.update(schema="shwfs_ao.eso_scao_paired_convergence_study.v1"),
}


@pytest.mark.parametrize("tampering", sorted(SUMMARY_TAMPERING))
def test_a_summary_that_does_not_match_its_runs_is_never_rewritten(tmp_path: Path, controlled: Launcher, tampering: str) -> None:
    assert run(tmp_path) == 0
    controlled.calls.clear()
    summary = tmp_path / "paired_convergence_ci.json"
    record = json.loads(summary.read_text())
    SUMMARY_TAMPERING[tampering](record)
    summary.write_text(json.dumps(record, indent=1) + "\n")
    refused(tmp_path, controlled, "does not match its saved runs")


def test_a_summary_with_missing_runs_is_never_rewritten(tmp_path: Path, controlled: Launcher) -> None:
    assert run(tmp_path) == 0
    controlled.calls.clear()
    (tmp_path / "runs" / f"{CI_KEYS[-1]}.json").unlink()
    refused(tmp_path, controlled, "1 planned runs are missing")


def test_a_child_row_of_another_producer_stops_the_study(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    launcher = Launcher(made_by=PRODUCER_B)
    monkeypatch.setattr(study, "_launch_child", launcher)
    with pytest.raises(study.StudyRecordError, match="another code identity or environment"):
        run(tmp_path)
    assert launcher.calls == CI_KEYS[:1]
    assert (tmp_path / "runs" / f"{CI_KEYS[0]}.json").exists()  # kept as its producer wrote it
    assert not (tmp_path / "paired_convergence_ci.json").exists()


def test_an_inconsistent_child_row_stops_the_study(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class CorruptLauncher(Launcher):
        def __call__(self, scale, directory, setting, path) -> None:
            super().__call__(scale, directory, setting, path)
            row = json.loads(path.read_text())
            row["protocol_hash"] = "0" * 64
            path.write_text(json.dumps(row))

    launcher = CorruptLauncher()
    monkeypatch.setattr(study, "_launch_child", launcher)
    with pytest.raises(study.StudyRecordError, match="not the digest.*the study stops"):
        run(tmp_path)
    assert launcher.calls == CI_KEYS[:1]
    assert not (tmp_path / "paired_convergence_ci.json").exists()


def test_a_non_finite_result_is_kept_and_reported_as_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A numerically failed run is a result: it is summarized, not refused.
    failed = "ci_s12_wfs2_sci3_r0"

    class FailingLauncher(Launcher):
        def __call__(self, scale, directory, setting, path) -> None:
            super().__call__(scale, directory, setting, path)
            if path.stem == failed:
                row = json.loads(path.read_text())
                row["ee50_radius_rad"] = float("nan")
                path.write_text(json.dumps(row))

    launcher = FailingLauncher()
    monkeypatch.setattr(study, "_launch_child", launcher)
    assert run(tmp_path) == 0
    record = json.loads((tmp_path / "paired_convergence_ci.json").read_text())
    assert math.isnan(record["runs"][failed]["ee50_radius_rad"])
    ee50 = record["scans"]["science_psf_pad_factor"]["convergence"]["ee50_radius_rad"]
    assert math.isnan(ee50["relative_change_finest_two"]) and ee50["within_declared_tolerance"] is False
    before = snapshot(tmp_path)
    launcher.calls.clear()
    assert run(tmp_path) == 0  # and a rerun leaves it as it is
    assert launcher.calls == [] and snapshot(tmp_path) == before


def _git(repository: Path, *arguments: str) -> None:
    # A throwaway repository, without the user's global or system configuration.
    environment = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(
        ["git", "-C", str(repository), "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
         "-c", "commit.gpgsign=false", *arguments],
        check=True, capture_output=True, env=environment,
    )


def test_the_code_identity_binds_the_package_it_imports(tmp_path: Path) -> None:
    # Review CR-01: Git alone could give a modified copy of the package the
    # identity of the tracked one.
    repository = tmp_path / "repository"
    package = repository / "src" / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("VALUE = 1\n")
    (repository / ".gitignore").write_text("copy/\n")
    _git(repository, "init", "-q")
    _git(repository, "add", "-A")
    _git(repository, "commit", "-q", "--no-verify", "-m", "fixture")
    tracked = REAL_CODE_IDENTITY(package)
    assert tracked["git_head"] and tracked["source_changes_sha256"] == hashlib.sha256(b"").hexdigest()
    copy = repository / "copy" / "src" / "pkg"  # in an ignored directory of the same repository
    shutil.copytree(package, copy)
    copied = REAL_CODE_IDENTITY(copy)
    assert copied["package_sha256"] == tracked["package_sha256"]  # the same code
    assert copied["git_head"] is None and copied["source_changes_sha256"] is None  # but not tracked here
    (copy / "__init__.py").write_text("VALUE = 2\n")
    assert REAL_CODE_IDENTITY(copy)["package_sha256"] != tracked["package_sha256"]
    (package / "untracked.py").write_text("")
    untracked = REAL_CODE_IDENTITY(package)
    assert untracked["package_sha256"] != tracked["package_sha256"]
    assert untracked["source_changes_sha256"] == tracked["source_changes_sha256"]  # the Git diff misses it
    (package / "__pycache__").mkdir()
    (package / "__pycache__" / "pkg.cpython-314.pyc").write_bytes(b"bytecode")
    assert REAL_CODE_IDENTITY(package)["package_sha256"] == untracked["package_sha256"]
    # Review CR-07: Finder metadata appears without any code change.
    (package / ".DS_Store").write_bytes(b"finder")
    (package / "._untracked.py").write_bytes(b"appledouble")
    (package / "sub" / ".hidden").mkdir(parents=True)
    (package / "sub" / ".hidden" / "note.txt").write_text("hidden")
    (package / "sub" / ".DS_Store").write_bytes(b"finder")
    with_metadata = REAL_CODE_IDENTITY(package)["package_sha256"]
    assert with_metadata == untracked["package_sha256"]
    (package / "sub" / "module.py").write_text("")  # a visible file still counts
    assert with_metadata != REAL_CODE_IDENTITY(package)["package_sha256"]
    (package / "sub" / "module.py").unlink()
    assert REAL_CODE_IDENTITY(package)["package_sha256"] == with_metadata


def test_a_child_writes_its_own_protocol(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    key = CI_KEYS[1]
    setting = study._plan("ci")[key]
    stand_in = {name: value for name, value in stand_in_row("ci", setting, PRODUCER_A).items() if name not in ("protocol", "protocol_hash")}
    monkeypatch.setattr(study, "_run_child", lambda *arguments: dict(stand_in))
    out = tmp_path / f"{key}.json"
    assert study.main(["--scale", "ci", "--output-dir", str(tmp_path), "--child", *map(str, setting), str(out)]) == 0
    row = json.loads(out.read_text())
    assert row["protocol"]["code"] == CODE_A and row["protocol"]["environment"] == ENVIRONMENT_A
    assert study._check_run(out, row, study._planned_protocol("ci", *setting)) is None
    assert not list(tmp_path.glob("*.partial"))


@pytest.mark.parametrize("scale", ["medium", "full"])
def test_the_committed_records_match_their_planned_runs_and_summaries(scale: str) -> None:
    """The version-1 records stay as they are: every row is its scale's planned run.

    Reads only.  The rows carry no run protocol (version 1); their planned
    fields, the screen size and the summary are recomputed with this script.
    """

    record = json.loads((EVIDENCE / f"paired_convergence_{scale}.json").read_text())
    assert record["schema"] == "shwfs_ao.eso_scao_paired_convergence_study.v1"
    remapped = {}
    for key, setting in study._plan(scale).items():
        row = record["runs"][study._legacy_run_key(*setting[1:])]
        assert "protocol" not in row
        planned = study._planned_protocol(scale, *setting)
        assert {name: row[name] for name in study.REPEATED_FIELDS} == {name: planned[name] for name in study.REPEATED_FIELDS}
        assert row["screen_size"] == 2 * study.LENSLETS[scale] * setting[1]
        remapped[key] = row
    assert len(record["runs"]) == len(remapped)
    assert study._canonical(study._summarize(scale, remapped)) == study._canonical(record["scans"])


# -- OBS-15..OBS-17 (review RV-01..RV-03 at f801cac on 2026-10-20): the identity fails closed --


UNKNOWN_CODE = {"package_sha256": None, "git_head": None, "source_changes_sha256": None}


def _tracked_package(tmp_path: Path) -> tuple[Path, Path]:
    repository = tmp_path / "repository"
    package = repository / "src" / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("VALUE = 1\n")
    (package / "module.py").write_text("")
    _git(repository, "init", "-q")
    _git(repository, "add", "-A")
    _git(repository, "commit", "-q", "--no-verify", "-m", "fixture")
    return repository, package


def _unknown(package: Path) -> bool:
    identity = REAL_CODE_IDENTITY(package)
    return {key: identity[key] for key in UNKNOWN_CODE} == UNKNOWN_CODE


def test_a_package_its_files_cannot_bind_has_an_unknown_identity(tmp_path: Path) -> None:
    # OBS-15 (review RV-01): code Python imports but a file digest would miss.
    repository, package = _tracked_package(tmp_path)
    assert REAL_CODE_IDENTITY(package)["git_head"] is not None
    (repository / "vendor" / "sub").mkdir(parents=True)
    (package / "sub").symlink_to("../../vendor/sub", target_is_directory=True)  # not followed
    assert _unknown(package)
    (package / "sub").unlink()
    (package / "extra.pyc").write_bytes(b"sourceless bytecode")  # imported, never digested
    assert _unknown(package)
    (package / "extra.pyc").unlink()
    assert REAL_CODE_IDENTITY(package)["git_head"] is not None
    archive = tmp_path / "packages.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("pkg/__init__.py", "VALUE = 1\n")
    assert _unknown(tmp_path / "missing" / "pkg") and _unknown(archive / "pkg")  # no directory to digest


def test_a_copy_path_with_glob_characters_borrows_no_git_state(tmp_path: Path) -> None:
    # OBS-16 (review RV-02): Git read copy[1]/... as a pattern matching the tracked copy1/...
    repository = tmp_path / "repository"
    tracked = repository / "copy1" / "src" / "pkg"
    tracked.mkdir(parents=True)
    (tracked / "__init__.py").write_text("VALUE = 1\n")
    _git(repository, "init", "-q")
    _git(repository, "add", "-A")
    _git(repository, "commit", "-q", "--no-verify", "-m", "fixture")
    assert REAL_CODE_IDENTITY(tracked)["git_head"] is not None
    copy = repository / "copy[1]" / "src" / "pkg"
    shutil.copytree(tracked, copy)
    (copy / "__init__.py").write_text("VALUE = 2\n")
    copied = REAL_CODE_IDENTITY(copy)
    assert copied["git_head"] is None and copied["source_changes_sha256"] is None


def test_the_package_digest_binds_file_names(tmp_path: Path) -> None:
    # OBS-17 (review RV-03): a module renamed or moved with the same content is other code.
    _, package = _tracked_package(tmp_path)
    original = study._package_sha256(package)
    (package / "module.py").rename(package / "module_renamed.py")  # the same place in the file order
    assert study._package_sha256(package) != original
    (package / "module_renamed.py").rename(package / "module.py")
    assert study._package_sha256(package) == original
    (package / "sub").mkdir()
    (package / "module.py").rename(package / "sub" / "module.py")
    assert study._package_sha256(package) != original


def test_the_code_identity_binds_the_driver_itself(tmp_path: Path) -> None:
    # The driver's own code (the paired band draw among it) is part of every run's producer.
    _, package = _tracked_package(tmp_path)
    driver = ROOT / "scripts/eso_scao_paired_convergence_study.py"
    assert REAL_CODE_IDENTITY(package)["script_sha256"] == hashlib.sha256(driver.read_bytes()).hexdigest()


def test_an_unchecked_bytecode_cache_leaves_the_code_unbound(tmp_path: Path) -> None:
    # Review RV-05: Python runs an unchecked hash-based cache without reading its source.
    _, package = _tracked_package(tmp_path)
    tracked = REAL_CODE_IDENTITY(package)
    source = package / "__init__.py"
    cache = importlib.util.cache_from_source(str(source))
    for mode in py_compile.PycInvalidationMode:
        py_compile.compile(str(source), cfile=cache, invalidation_mode=mode, doraise=True)
        if mode is py_compile.PycInvalidationMode.UNCHECKED_HASH:
            assert _unknown(package)
        else:
            assert REAL_CODE_IDENTITY(package) == tracked, mode  # Python checks it against its source


def test_the_bytecode_cache_is_checked_where_python_reads_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Review RV-07, RV-08: a symlinked __pycache__, a PYTHONPYCACHEPREFIX cache,
    # --check-hash-based-pycs never, and an unreadable cache.
    _, package = _tracked_package(tmp_path)
    tracked = REAL_CODE_IDENTITY(package)
    source = package / "__init__.py"

    def cached(mode: py_compile.PycInvalidationMode) -> Path:
        cache = Path(importlib.util.cache_from_source(str(source)))
        py_compile.compile(str(source), cfile=str(cache), invalidation_mode=mode, doraise=True)
        return cache

    elsewhere = tmp_path / "cache_elsewhere"
    elsewhere.mkdir()
    (package / "__pycache__").symlink_to(elsewhere, target_is_directory=True)
    cached(py_compile.PycInvalidationMode.UNCHECKED_HASH)
    assert _unknown(package)
    (package / "__pycache__").unlink()
    monkeypatch.setattr(sys, "pycache_prefix", str(tmp_path / "prefix"))
    assert cached(py_compile.PycInvalidationMode.UNCHECKED_HASH).is_relative_to(tmp_path / "prefix")
    assert _unknown(package)
    cached(py_compile.PycInvalidationMode.CHECKED_HASH)
    assert REAL_CODE_IDENTITY(package) == tracked
    monkeypatch.setattr(study._imp, "check_hash_based_pycs", "never")
    assert _unknown(package)  # no hash-based cache is checked then
    monkeypatch.setattr(study._imp, "check_hash_based_pycs", "default")
    cache = cached(py_compile.PycInvalidationMode.UNCHECKED_HASH)
    cache.chmod(0)
    try:
        assert REAL_CODE_IDENTITY(package) == tracked  # Python cannot read it either and compiles the source
    finally:
        cache.chmod(0o644)
