"""Review R6: the detector evidence runner never reuses or replaces silently.

The runner script is loaded by file, as the other script-guard tests do, and
driven with a stand-in run function, so no simulation runs.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import py_compile
import re
import shutil
import subprocess
import sys
import zipfile

import pytest

from shwfs_ao.experiments.detector_level import summarize_runs
from shwfs_ao.io.configs import load_system_profile


ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "run_detector_level_evidence_for_guard_tests",
    ROOT / "scripts/run_detector_level_evidence.py",
)
assert _SPEC is not None and _SPEC.loader is not None
runner = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = runner
_SPEC.loader.exec_module(runner)
# Captured before any fixture redirects them: the legacy default directory and
# the real code identity.
LEGACY_EVIDENCE_DIR = runner.EVIDENCE_DIR
REAL_CODE_IDENTITY = runner.code_identity

CONFIG = load_system_profile("det_emccd_2m_synthetic", 1)
PLAN = [("label", CONFIG, 21), ("label", CONFIG, 22)]


@pytest.fixture(autouse=True)
def isolated_runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(runner, "EVIDENCE_DIR", tmp_path)
    # Each test is one invocation that the user enabled; tests of a missing
    # enablement clear the note.
    monkeypatch.setattr(runner, "OPTIONS", runner.argparse.Namespace(output=None, overwrite=False, resume=False, enabled_by_user="test go-ahead", output_dir=None))
    monkeypatch.setattr(runner, "_STARTED", set())
    monkeypatch.setattr(runner, "code_identity", lambda: {"git_head": "test", "source_changes_sha256": "test"})
    monkeypatch.setattr(runner, "producer_environment", lambda: dict(ENVIRONMENT_A))
    return tmp_path


ENVIRONMENT_A = {"python": "3.x A", "numpy": "numpy A", "scipy": "scipy A", "machine": "arm64"}
ENVIRONMENT_B = {**ENVIRONMENT_A, "numpy": "numpy B"}


class Recorder:
    def __init__(self) -> None:
        self.calls: list[int] = []

    def __call__(self, config, *, root_seed, n_steps, burn_in_frames, execution):
        self.calls.append(int(root_seed))
        return {
            "root_seed": int(root_seed),
            "noise_variance_m2": 1.0e-16,
            "noise_variance_standard_error_m2": None,
            "mean_square_difference_m2": 1.0e-16,
            "detected_e_full_subap": 100.0,
            "wall_s": 0.0,
        }


def series(recorder: Recorder, *, n_steps: int = 400, burn_in: int = 100, name: str = "series.json") -> None:
    runner._gated_series(name, "test", PLAN, n_steps=n_steps, burn_in=burn_in, execution=None, runner=recorder)


def start_fresh_invocation() -> None:
    runner._STARTED.clear()


def test_a_completed_record_is_neither_rerun_nor_reused_without_resume(isolated_runner: Path) -> None:
    first = Recorder()
    series(first)
    assert first.calls == [21, 22]
    record = json.loads((isolated_runner / "series.json").read_text())
    assert all("protocol_hash" in run and run["protocol"]["n_steps"] == 400 for run in record["runs"])
    start_fresh_invocation()
    second = Recorder()
    with pytest.raises(runner.EvidenceRecordExists, match="--resume"):
        series(second)
    assert second.calls == []


def test_resume_reuses_only_runs_with_a_matching_protocol(isolated_runner: Path) -> None:
    series(Recorder())
    start_fresh_invocation()
    runner.OPTIONS.resume = True
    same = Recorder()
    series(same)
    assert same.calls == []
    # Another frame count, burn-in or code identity is another protocol.
    for keywords in ({"n_steps": 401}, {"burn_in": 99}):
        start_fresh_invocation()
        changed = Recorder()
        with pytest.raises(runner.EvidenceRecordExists, match="another protocol"):
            series(changed, **keywords)
        assert changed.calls == []
    start_fresh_invocation()
    runner.code_identity = lambda: {"git_head": "other", "source_changes_sha256": "test"}
    changed = Recorder()
    with pytest.raises(runner.EvidenceRecordExists, match="another protocol"):
        series(changed)
    assert changed.calls == []


def test_an_interrupted_series_resumes_with_the_missing_runs_only(isolated_runner: Path) -> None:
    runner._gated_series("series.json", "test", PLAN[:1], n_steps=400, burn_in=100, execution=None, runner=Recorder())
    start_fresh_invocation()
    runner.OPTIONS.resume = True
    rest = Recorder()
    series(rest)
    assert rest.calls == [22]
    assert len(json.loads((isolated_runner / "series.json").read_text())["runs"]) == 2


def test_a_record_without_protocol_identities_cannot_be_resumed(isolated_runner: Path) -> None:
    # The review's reproduction: a stale one-frame run under the same label and seed.
    stale = {"started_unix_s": 0, "runs": [{"label": "label", "root_seed": 21, "config_hash": "stale", "n_steps": 1}]}
    (isolated_runner / "series.json").write_text(json.dumps(stale))
    runner.OPTIONS.resume = True
    recorder = Recorder()
    with pytest.raises(runner.EvidenceRecordExists, match="predates"):
        series(recorder)
    assert recorder.calls == []


def test_a_fresh_output_name_reruns_everything(isolated_runner: Path) -> None:
    series(Recorder())
    start_fresh_invocation()
    runner.OPTIONS.output = "series_rerun.json"
    rerun = Recorder()
    series(rerun)
    assert rerun.calls == [21, 22]
    assert (isolated_runner / "series_rerun.json").exists()


def test_one_shot_records_are_replaced_only_on_request(isolated_runner: Path) -> None:
    runner._write("one_shot.json", {"value": 1})
    start_fresh_invocation()
    with pytest.raises(runner.EvidenceRecordExists, match="--overwrite"):
        runner._write("one_shot.json", {"value": 2})
    assert json.loads((isolated_runner / "one_shot.json").read_text()) == {"value": 1}
    runner.OPTIONS.overwrite = True
    runner._write("one_shot.json", {"value": 2})
    assert json.loads((isolated_runner / "one_shot.json").read_text()) == {"value": 2}



def test_resuming_another_arm_requires_the_same_series_protocol(isolated_runner: Path) -> None:
    # Re-review S2: runs of other arms are kept only under the same code,
    # frames, burn-in and execution settings.
    other_arm = [("other arm", CONFIG, 21)]
    runner._gated_series("arms.json", "arm A", PLAN[:1], n_steps=32, burn_in=0, execution=None, runner=Recorder())
    start_fresh_invocation()
    runner.OPTIONS.resume = True
    for keywords in ({"n_steps": 64, "burn_in": 0}, {"n_steps": 32, "burn_in": 20}):
        start_fresh_invocation()
        refused = Recorder()
        with pytest.raises(runner.EvidenceRecordExists, match="another protocol"):
            runner._gated_series("arms.json", "arm B", other_arm, execution=None, runner=refused, **keywords)
        assert refused.calls == []
    start_fresh_invocation()
    runner.code_identity = lambda: {"git_head": "revision-B", "source_changes_sha256": "test"}
    refused = Recorder()
    with pytest.raises(runner.EvidenceRecordExists, match="another protocol"):
        runner._gated_series("arms.json", "arm B", other_arm, n_steps=32, burn_in=0, execution=None, runner=refused)
    assert refused.calls == []
    # The same series protocol appends the new arm.
    start_fresh_invocation()
    runner.code_identity = lambda: {"git_head": "test", "source_changes_sha256": "test"}
    appended = Recorder()
    runner._gated_series("arms.json", "arm B", other_arm, n_steps=32, burn_in=0, execution=None, runner=appended)
    assert appended.calls == [21]
    labels = [run["label"] for run in json.loads((isolated_runner / "arms.json").read_text())["runs"]]
    assert labels == ["label", "other arm"]


class ScienceRecorder(Recorder):
    """A stand-in science run: deterministic per-seed metrics, no simulation."""

    def __call__(self, config, *, root_seed, n_steps, burn_in_frames, execution):
        self.calls.append(int(root_seed))
        return {
            "root_seed": int(root_seed),
            "post_update_rms_m": 1.0e-7 * (1.0 + 0.01 * int(root_seed)),
            "valid_measurement_fraction": 1.0 - 0.001 * int(root_seed),
            "science": [{"wavelength_m": 2.2e-6, "peak_strehl": 0.5 + 0.001 * int(root_seed)}],
            "lost_lock": False,
            "per_frame_s": 0.0,
        }


def test_the_legacy_default_directory_and_file_name_semantics_are_kept(
    isolated_runner: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert LEGACY_EVIDENCE_DIR == ROOT / "docs/refactor/detector_level_evidence"
    # Without --output-dir the records go to the (redirected) evidence directory,
    # and --output names a file in it.
    runner._write("one_shot.json", runner._header("test"))
    start_fresh_invocation()
    runner.OPTIONS.output = "renamed.json"
    runner._write("one_shot.json", runner._header("test"))
    assert sorted(path.name for path in isolated_runner.iterdir()) == ["one_shot.json", "renamed.json"]
    header = json.loads((isolated_runner / "renamed.json").read_text())
    assert header["output_directory"] == str(isolated_runner.resolve())
    assert header["output_directory_source"] == "legacy default"
    # The real default lies inside the repository, so a committed record
    # names it relative to the repository and carries no local path.
    monkeypatch.setattr(runner, "EVIDENCE_DIR", LEGACY_EVIDENCE_DIR)
    assert runner._header("test")["output_directory"] == "docs/refactor/detector_level_evidence"


def test_output_dir_sends_every_record_to_the_caller_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Drive main() with a stand-in command: the option parsing, the one-shot
    # writer and a gated series all honour --output-dir, and the (redirected)
    # legacy directory is never even created.
    legacy = tmp_path / "legacy"
    monkeypatch.setattr(runner, "EVIDENCE_DIR", legacy)
    destination = tmp_path / "caller" / "records"

    def stand_in(arguments) -> None:
        runner._write("one_shot.json", runner._header("stand-in"))
        runner._gated_series("series.json", "stand-in", PLAN, n_steps=400, burn_in=100, execution=None, runner=Recorder())

    monkeypatch.setattr(runner, "e2", stand_in)
    assert runner.main(["--output-dir", str(destination), "--enabled-by-user", "test go-ahead", "e2"]) == 0
    assert sorted(path.name for path in destination.iterdir()) == ["one_shot.json", "series.json"]
    assert not legacy.exists()
    for name in ("one_shot.json", "series.json"):
        record = json.loads((destination / name).read_text())
        assert record["output_directory"] == str(destination.resolve())
        assert record["output_directory_source"] == "--output-dir"
    # The protocol identity does not depend on where the record is written.
    series = json.loads((destination / "series.json").read_text())
    assert all("output_directory" not in run["protocol"] for run in series["runs"])


def test_a_resume_with_nothing_left_says_so_and_leaves_the_record_unchanged(
    isolated_runner: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    series(Recorder())
    before = (isolated_runner / "series.json").read_bytes()
    start_fresh_invocation()
    runner.OPTIONS.resume = True
    capsys.readouterr()
    idle = Recorder()
    series(idle)
    assert idle.calls == []
    assert "nothing ran and the record is unchanged" in capsys.readouterr().out
    assert (isolated_runner / "series.json").read_bytes() == before


def test_a_gated_run_without_an_enablement_note_refuses_before_running(isolated_runner: Path) -> None:
    runner.OPTIONS.enabled_by_user = None
    idle = Recorder()
    with pytest.raises(runner.EnablementMissing, match="--enabled-by-user"):
        series(idle)
    assert idle.calls == []
    assert not (isolated_runner / "series.json").exists()


def test_the_real_gated_commands_refuse_without_a_note_before_building_anything(
    isolated_runner: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # e5 is the 42 m run: the refusal must come before any system is built.
    # Should the guard ever regress, their run functions fail at once instead
    # of starting the real 12 m or 42 m runs (review CR-04, 2026-10-20).
    from shwfs_ao.experiments import detector_level

    def must_not_run(*arguments, **keywords):
        raise AssertionError("a gated command reached its run function without an enablement note")

    monkeypatch.setattr(detector_level, "science_run", must_not_run)
    monkeypatch.setattr(detector_level, "open_loop_noise_propagation", must_not_run)
    with pytest.raises(runner.EnablementMissing, match="e5"):
        runner.main(["e5"])
    with pytest.raises(runner.EnablementMissing, match="e2-12m"):
        runner.main(["e2-12m"])
    assert list(isolated_runner.iterdir()) == []


def test_a_resume_keeps_the_series_note_and_records_its_own(isolated_runner: Path) -> None:
    runner.OPTIONS.enabled_by_user = "first go-ahead"
    runner._gated_series("series.json", "test", PLAN[:1], n_steps=400, burn_in=100, execution=None, runner=Recorder())
    start_fresh_invocation()
    runner.OPTIONS.resume = True
    runner.OPTIONS.enabled_by_user = "second go-ahead"
    runner._gated_series("series.json", "test", PLAN, n_steps=400, burn_in=100, execution=None, runner=Recorder())
    record = json.loads((isolated_runner / "series.json").read_text())
    assert record["enabled_by_user"] == "first go-ahead"
    assert record["resumed_enabled_by_user"] == ["second go-ahead"]
    assert len(record["runs"]) == len(PLAN)


def test_a_resume_with_nothing_left_needs_no_note(isolated_runner: Path) -> None:
    series(Recorder())
    before = (isolated_runner / "series.json").read_bytes()
    start_fresh_invocation()
    runner.OPTIONS.resume = True
    runner.OPTIONS.enabled_by_user = None
    idle = Recorder()
    series(idle)
    assert idle.calls == []
    assert (isolated_runner / "series.json").read_bytes() == before


def test_an_interrupted_series_summarizes_like_one_invocation(isolated_runner: Path) -> None:
    plan = [("label", CONFIG, seed) for seed in (21, 22, 23)]
    runner._gated_series("whole.json", "test", plan, n_steps=400, burn_in=100, execution=None, runner=ScienceRecorder())
    start_fresh_invocation()
    runner._gated_series("split.json", "test", plan[:1], n_steps=400, burn_in=100, execution=None, runner=ScienceRecorder())
    start_fresh_invocation()
    runner.OPTIONS.resume = True
    runner._gated_series("split.json", "test", plan, n_steps=400, burn_in=100, execution=None, runner=ScienceRecorder())
    whole = json.loads((isolated_runner / "whole.json").read_text())
    split = json.loads((isolated_runner / "split.json").read_text())
    assert split["summary"] == whole["summary"]
    assert whole["summary"] == {"label": summarize_runs(whole["runs"])}
    assert [run["protocol_hash"] for run in split["runs"]] == [run["protocol_hash"] for run in whole["runs"]]


def test_saved_evidence_records_keep_their_identities_and_summaries() -> None:
    """Old records stay readable: every stored protocol hash and summary recomputes.

    The protocol hash is the SHA-256 of the key-sorted JSON of the stored
    protocol payload; the summary is ``summarize_runs`` over the stored runs
    of each label.  Reads only; the historical evidence is never written.
    """

    records = sorted((ROOT / "docs/refactor/detector_level_evidence").glob("*.json"))
    checked_hashes = checked_summaries = 0
    for path in records:
        record = json.loads(path.read_text())
        runs = record.get("runs")
        if not isinstance(runs, list):
            continue
        for run in runs:
            if "protocol" in run:
                encoded = json.dumps(run["protocol"], sort_keys=True, default=str).encode("utf-8")
                assert hashlib.sha256(encoded).hexdigest() == run["protocol_hash"], path.name
                checked_hashes += 1
        groups: dict[str, list[dict[str, object]]] = {}
        for run in runs:
            if run.get("status") != "refused" and "post_update_rms_m" in run:
                groups.setdefault(run["label"], []).append(run)
        if groups:
            assert record["summary"] == {label: summarize_runs(value) for label, value in groups.items()}, path.name
            checked_summaries += 1
    assert checked_hashes > 0 and checked_summaries > 0


# -- GPT pre-refactor audit F-03 (2026-10-18): who produced each retained run --


def _environment(monkeypatch: pytest.MonkeyPatch, environment: dict[str, str]) -> None:
    monkeypatch.setattr(runner, "producer_environment", lambda: dict(environment))


def test_a_resume_under_another_environment_is_refused(isolated_runner: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner._gated_series("series.json", "test", PLAN[:1], n_steps=400, burn_in=100, execution=None, runner=Recorder())
    before = (isolated_runner / "series.json").read_bytes()
    start_fresh_invocation()
    runner.OPTIONS.resume = True
    _environment(monkeypatch, ENVIRONMENT_B)
    idle = Recorder()
    with pytest.raises(runner.EvidenceRecordExists, match="producing environment"):
        runner._gated_series("series.json", "test", PLAN, n_steps=400, burn_in=100, execution=None, runner=idle)
    assert idle.calls == []
    assert (isolated_runner / "series.json").read_bytes() == before


def test_each_run_names_the_environment_that_produced_it(isolated_runner: Path) -> None:
    runner._gated_series("series.json", "test", PLAN[:1], n_steps=400, burn_in=100, execution=None, runner=Recorder())
    first = json.loads((isolated_runner / "series.json").read_text())["runs"][0]
    start_fresh_invocation()
    runner.OPTIONS.resume = True
    runner._gated_series("series.json", "test", PLAN, n_steps=400, burn_in=100, execution=None, runner=Recorder())
    record = json.loads((isolated_runner / "series.json").read_text())
    assert record["series_protocol_version"] == 4
    assert record["runs"][0] == first  # the retained row is kept as written
    assert [run["protocol"]["environment"] for run in record["runs"]] == [ENVIRONMENT_A] * len(PLAN)


def test_arms_must_share_the_producing_environment(isolated_runner: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    arm_x = [("x", CONFIG, 21)]
    arm_y = [("y", CONFIG, 22)]
    runner._gated_series("arms.json", "x", arm_x, n_steps=32, burn_in=0, execution=None, runner=Recorder())
    before = (isolated_runner / "arms.json").read_bytes()
    runner.OPTIONS.resume = True
    _environment(monkeypatch, ENVIRONMENT_B)
    for plan in (arm_y, arm_x):  # a disjoint arm, and the same arm with nothing left to run
        start_fresh_invocation()
        with pytest.raises(runner.EvidenceRecordExists, match="producing environment"):
            runner._gated_series("arms.json", "arm", plan, n_steps=32, burn_in=0, execution=None, runner=Recorder())
        assert (isolated_runner / "arms.json").read_bytes() == before
    _environment(monkeypatch, ENVIRONMENT_A)
    start_fresh_invocation()
    appended = Recorder()
    runner._gated_series("arms.json", "arm", arm_x + arm_y, n_steps=32, burn_in=0, execution=None, runner=appended)
    assert appended.calls == [22]  # overlapping arms: only the new run executes


def test_a_version_2_record_is_neither_continued_nor_reattributed(isolated_runner: Path) -> None:
    runner._gated_series("legacy.json", "test", PLAN[:1], n_steps=400, burn_in=100, execution=None, runner=Recorder())
    path = isolated_runner / "legacy.json"
    legacy = json.loads(path.read_text())
    # The version-2 shape: runs carry no producing environment.  A version-2
    # record's hashes are the digests of its own payloads (AR-016 checks them).
    legacy["series_protocol_version"] = 2
    for run in legacy["runs"]:
        del run["protocol"]["environment"]
        run["protocol"]["series_protocol_version"] = 2
        run["protocol_hash"] = runner.protocol_digest(run["protocol"])
    path.write_text(json.dumps(legacy, indent=1) + "\n")
    before = path.read_bytes()
    runner.OPTIONS.resume = True
    for plan in (PLAN, PLAN[:1]):  # with new runs, and with nothing left to run
        start_fresh_invocation()
        idle = Recorder()
        with pytest.raises(runner.EvidenceRecordExists, match="do not name the environment"):
            runner._gated_series("legacy.json", "test", plan, n_steps=400, burn_in=100, execution=None, runner=idle)
        assert idle.calls == []
        assert path.read_bytes() == before


def test_appending_needs_a_known_code_identity(isolated_runner: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "code_identity", lambda: {"git_head": None, "source_changes_sha256": None})
    runner._gated_series("series.json", "test", PLAN[:1], n_steps=400, burn_in=100, execution=None, runner=Recorder())
    before = (isolated_runner / "series.json").read_bytes()
    runner.OPTIONS.resume = True
    start_fresh_invocation()
    with pytest.raises(runner.EvidenceRecordExists, match="code identity"):
        runner._gated_series("series.json", "test", PLAN, n_steps=400, burn_in=100, execution=None, runner=Recorder())
    assert (isolated_runner / "series.json").read_bytes() == before
    start_fresh_invocation()
    runner._gated_series("series.json", "test", PLAN[:1], n_steps=400, burn_in=100, execution=None, runner=Recorder())
    assert (isolated_runner / "series.json").read_bytes() == before  # nothing to add: verified, not written


# -- GPT independent review AR-016 (2026-10-20): a saved record agrees with itself --


OTHER_ARM = [("other arm", CONFIG, 31)]
RESUMED_PLANS = {"overlapping": PLAN, "disjoint": OTHER_ARM, "nothing left": PLAN[:1]}
TAMPERING = {
    # The review's probes: a corrupt digest, a changed payload under its old
    # digest, and an outer seed that is not the protocol's.
    "stored hash": (lambda record: record["runs"][0].update(protocol_hash="invalid-digest"), "not the digest"),
    "payload under a stale hash": (lambda record: record["runs"][0]["protocol"].update(config_hash="changed"), "not the digest"),
    "outer seed": (lambda record: record["runs"][0].update(root_seed=999), "root_seed 999"),
    "outer label": (lambda record: record["runs"][0].update(label="other"), "label 'other'"),
    "outer configuration hash": (lambda record: record["runs"][0].update(config_hash="other"), "config_hash 'other'"),
    "outer frame count": (lambda record: record["runs"][0].update(n_steps=1), "n_steps 1"),
    "run recorded twice": (lambda record: record["runs"].append(json.loads(json.dumps(record["runs"][0]))), "recorded twice"),
    "header frame count": (lambda record: record.update(n_steps=1), "header's n_steps"),
    "header code identity": (lambda record: record.update(code_identity={"git_head": "other", "source_changes_sha256": "test"}), "header's code_identity"),
    "header environment": (lambda record: record.update(numpy="numpy other"), "header's numpy"),
    "carried-over notes": (lambda record: record.update(resumed_enabled_by_user="one note"), "resumed_enabled_by_user"),
    "series note": (lambda record: record.update(enabled_by_user=5), "enabled_by_user is not a note"),
    "outer label missing": (lambda record: record["runs"][0].pop("label"), "label None"),
    "outer seed missing": (lambda record: record["runs"][0].pop("root_seed"), "root_seed None"),
}


@pytest.mark.parametrize("plan", sorted(RESUMED_PLANS))
@pytest.mark.parametrize("tampering", sorted(TAMPERING))
def test_an_inconsistent_record_is_refused_unchanged(isolated_runner: Path, tampering: str, plan: str) -> None:
    runner._gated_series("series.json", "test", PLAN[:1], n_steps=400, burn_in=100, execution=None, runner=Recorder())
    path = isolated_runner / "series.json"
    record = json.loads(path.read_text())
    change, match = TAMPERING[tampering]
    change(record)
    path.write_text(json.dumps(record, indent=2) + "\n")
    before = path.read_bytes()
    start_fresh_invocation()
    runner.OPTIONS.resume = True
    idle = Recorder()
    with pytest.raises(runner.EvidenceRecordExists, match="inconsistent in itself.*" + re.escape(match)):
        runner._gated_series("series.json", "test", RESUMED_PLANS[plan], n_steps=400, burn_in=100, execution=None, runner=idle)
    assert idle.calls == []
    assert path.read_bytes() == before


def test_a_boolean_in_place_of_an_integer_is_another_protocol(isolated_runner: Path) -> None:
    # Python's True == 1: the series fields are compared as JSON, so a saved
    # run of another arm whose frame count reads true does not pass for 1.
    runner._gated_series("series.json", "test", PLAN[:1], n_steps=1, burn_in=0, execution=None, runner=Recorder())
    path = isolated_runner / "series.json"
    record = json.loads(path.read_text())
    record["n_steps"] = True
    for run in record["runs"]:
        run["protocol"]["n_steps"] = True
        run["protocol_hash"] = runner.protocol_digest(run["protocol"])
    path.write_text(json.dumps(record, indent=2) + "\n")
    before = path.read_bytes()
    start_fresh_invocation()
    runner.OPTIONS.resume = True
    idle = Recorder()
    with pytest.raises(runner.EvidenceRecordExists, match="another protocol"):
        runner._gated_series("series.json", "test", OTHER_ARM, n_steps=1, burn_in=0, execution=None, runner=idle)
    assert idle.calls == []
    assert path.read_bytes() == before


def test_a_saved_run_of_another_configuration_is_not_reused(isolated_runner: Path) -> None:
    # Review R6 (and CR-03): a self-consistent saved run of a planned label
    # and seed that names another configuration is another protocol.
    runner._gated_series("series.json", "test", PLAN[:1], n_steps=400, burn_in=100, execution=None, runner=Recorder())
    path = isolated_runner / "series.json"
    record = json.loads(path.read_text())
    record["runs"][0]["protocol"]["config_hash"] = "another configuration"
    record["runs"][0]["protocol_hash"] = runner.protocol_digest(record["runs"][0]["protocol"])
    path.write_text(json.dumps(record, indent=2) + "\n")
    before = path.read_bytes()
    runner.OPTIONS.resume = True
    for plan in (PLAN, PLAN[:1]):  # with a run to add, and with nothing left to run
        start_fresh_invocation()
        idle = Recorder()
        with pytest.raises(runner.EvidenceRecordExists, match="another protocol"):
            runner._gated_series("series.json", "test", plan, n_steps=400, burn_in=100, execution=None, runner=idle)
        assert idle.calls == []
        assert path.read_bytes() == before


def test_an_unreadable_or_non_series_record_is_refused_unchanged(isolated_runner: Path) -> None:
    path = isolated_runner / "series.json"
    runner.OPTIONS.resume = True
    for content, match in (("{", "not readable JSON"), (json.dumps({"command": "e2", "results": []}), "no list of runs")):
        path.write_text(content)
        before = path.read_bytes()
        start_fresh_invocation()
        idle = Recorder()
        with pytest.raises(runner.EvidenceRecordExists, match=match):
            series(idle)
        assert idle.calls == []
        assert path.read_bytes() == before
    path.unlink()
    path.mkdir()  # a directory under the record's name
    start_fresh_invocation()
    idle = Recorder()
    with pytest.raises(runner.EvidenceRecordExists, match="not readable JSON"):
        series(idle)
    assert idle.calls == [] and path.is_dir() and not any(path.iterdir())


def test_a_consistent_record_resumed_twice_stays_consistent(isolated_runner: Path) -> None:
    path = isolated_runner / "series.json"
    runner._gated_series("series.json", "test", PLAN[:1], n_steps=400, burn_in=100, execution=None, runner=Recorder())
    calls = []
    for plan in (PLAN, PLAN + OTHER_ARM):  # an overlapping, then a disjoint addition
        start_fresh_invocation()
        runner.OPTIONS.resume = True
        recorder = Recorder()
        runner._gated_series("series.json", "test", plan, n_steps=400, burn_in=100, execution=None, runner=recorder)
        calls.append(recorder.calls)
        assert runner._inconsistencies(json.loads(path.read_text())) == []
    assert calls == [[22], [31]]


def test_the_saved_evidence_records_agree_with_themselves() -> None:
    # Reads only: every committed record whose runs all carry protocols
    # passes the AR-016 consistency check, so no valid record is refused for it.
    checked = 0
    for path in sorted(LEGACY_EVIDENCE_DIR.glob("*.json")):
        record = json.loads(path.read_text())
        runs = record.get("runs")
        if isinstance(runs, list) and runs and all(isinstance(run, dict) and "protocol" in run and "protocol_hash" in run for run in runs):
            assert runner._inconsistencies(record) == [], path.name
            checked += 1
    assert checked > 0


# -- OBS-07 (review CR-02, 2026-10-20): the code identity is the imported package's --


RUNNER_SCRIPT = ROOT / "scripts/run_detector_level_evidence.py"


def _git(repository: Path, *arguments: str) -> str:
    # A throwaway repository, without the user's global or system configuration.
    environment = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    completed = subprocess.run(
        ["git", "-C", str(repository), "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid",
         "-c", "commit.gpgsign=false", *arguments],
        check=True, capture_output=True, text=True, env=environment, timeout=60,
    )
    return completed.stdout.strip()


def tracked_package(tmp_path: Path) -> tuple[Path, Path]:
    """A throwaway repository with a committed ``src/shwfs_ao`` package; its ``copy/`` is ignored."""

    repository = tmp_path / "repository"
    package = repository / "src" / "shwfs_ao"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("VALUE = 1\n")
    (package / "module.py").write_text("")
    (repository / ".gitignore").write_text("copy/\n")
    _git(repository, "init", "-q")
    _git(repository, "add", "-A")
    _git(repository, "commit", "-q", "--no-verify", "-m", "fixture")
    return repository, package


def ignored_copy(repository: Path, package: Path, *, modified: bool) -> Path:
    """A copy of the package in the repository's ignored directory, with another value when ``modified``."""

    copy = repository / "copy" / ("modified" if modified else "same") / "src" / "shwfs_ao"
    shutil.copytree(package, copy)
    if modified:
        (copy / "__init__.py").write_text("VALUE = 2\n")
    return copy


def act_with_package(monkeypatch: pytest.MonkeyPatch, package: Path) -> None:
    monkeypatch.setattr(runner, "code_identity", lambda: REAL_CODE_IDENTITY(package))


def refused_for_every_plan(path: Path, before: bytes, match: str) -> None:
    """Resumes with an overlapping, a disjoint and an idle plan are refused; nothing runs or changes."""

    for plan in (PLAN, OTHER_ARM, PLAN[:1]):
        start_fresh_invocation()
        idle = Recorder()
        with pytest.raises(runner.EvidenceRecordExists, match=match):
            runner._gated_series(path.name, "test", plan, n_steps=400, burn_in=100, execution=None, runner=idle)
        assert idle.calls == []
        assert path.read_bytes() == before


def test_the_code_identity_binds_the_package_it_imports(tmp_path: Path) -> None:
    # OBS-07 (review CR-02): the identity used to be the Git state of this
    # script's repository, whatever package the process imported.
    repository, package = tracked_package(tmp_path)
    tracked = REAL_CODE_IDENTITY(package)
    assert tracked == {
        "package_directory": "src",
        "package_sha256": runner._package_sha256(package),
        "script_sha256": hashlib.sha256(RUNNER_SCRIPT.read_bytes()).hexdigest(),
        "git_head": _git(repository, "rev-parse", "HEAD"),
        "source_changes_sha256": hashlib.sha256(b"").hexdigest(),
    }
    same = REAL_CODE_IDENTITY(ignored_copy(repository, package, modified=False))
    assert same["package_sha256"] == tracked["package_sha256"]  # the same code
    assert same["git_head"] is None and same["source_changes_sha256"] is None  # but no repository tracks it there
    modified = REAL_CODE_IDENTITY(ignored_copy(repository, package, modified=True))
    assert modified["package_sha256"] != tracked["package_sha256"] and modified["git_head"] is None
    # An edit of the tracked package changes its digest and its Git diff.
    (package / "module.py").write_text("CHANGED = True\n")
    edited = REAL_CODE_IDENTITY(package)
    assert edited["git_head"] == tracked["git_head"]
    assert edited["package_sha256"] != tracked["package_sha256"]
    assert edited["source_changes_sha256"] != tracked["source_changes_sha256"]
    (package / "module.py").write_text("")
    assert REAL_CODE_IDENTITY(package) == tracked
    # An untracked module: the Git diff misses it, the package digest does not.
    (package / "untracked.py").write_text("")
    untracked = REAL_CODE_IDENTITY(package)
    assert untracked["package_sha256"] != tracked["package_sha256"]
    assert untracked["source_changes_sha256"] == tracked["source_changes_sha256"]
    # Bytecode and hidden files (Finder metadata) appear without a code change.
    (package / "__pycache__").mkdir()
    (package / "__pycache__" / "module.cpython-314.pyc").write_bytes(b"bytecode")
    (package / ".DS_Store").write_bytes(b"finder")
    (package / "._module.py").write_bytes(b"appledouble")
    (package / "sub" / ".hidden").mkdir(parents=True)
    (package / "sub" / ".hidden" / "note.txt").write_text("hidden")
    assert REAL_CODE_IDENTITY(package)["package_sha256"] == untracked["package_sha256"]
    (package / "sub" / "module.py").write_text("")  # a visible file still counts
    assert REAL_CODE_IDENTITY(package)["package_sha256"] != untracked["package_sha256"]


def test_a_fresh_process_takes_the_identity_of_the_package_it_imports(tmp_path: Path) -> None:
    # The review's demonstration: this runner script, run with another package
    # first on the import path, used to report this repository's identity.
    repository, package = tracked_package(tmp_path)
    copy = ignored_copy(repository, package, modified=True)
    probe = (
        "import importlib.util, json, sys\n"
        "spec = importlib.util.spec_from_file_location('runner_identity_probe', sys.argv[1])\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        "identity = module.code_identity()\n"
        "import shwfs_ao\n"
        "print(json.dumps({'imported': shwfs_ao.__file__, 'identity': identity}))\n"
    )
    for imported in (package, copy):
        environment = {**os.environ, "PYTHONPATH": str(imported.parent), "PYTHONDONTWRITEBYTECODE": "1"}
        completed = subprocess.run(
            [sys.executable, "-c", probe, str(RUNNER_SCRIPT)],
            cwd=tmp_path, env=environment, capture_output=True, text=True, check=True, timeout=60,
        )
        seen = json.loads(completed.stdout)
        assert Path(seen["imported"]).resolve().parent == imported.resolve()
        assert seen["identity"] == REAL_CODE_IDENTITY(imported)
    assert REAL_CODE_IDENTITY(copy)["package_sha256"] != REAL_CODE_IDENTITY(package)["package_sha256"]


def test_a_series_records_the_identity_of_the_imported_package(isolated_runner: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import shwfs_ao

    monkeypatch.setattr(runner, "code_identity", REAL_CODE_IDENTITY)
    series(Recorder())
    record = json.loads((isolated_runner / "series.json").read_text())
    imported = Path(shwfs_ao.__file__).parent
    assert record["code_identity"] == REAL_CODE_IDENTITY(imported)
    assert record["code_identity"]["package_sha256"] == runner._package_sha256(imported.resolve())
    assert all(run["protocol"]["code"] == record["code_identity"] for run in record["runs"])
    assert {run["protocol"]["series_protocol_version"] for run in record["runs"]} == {record["series_protocol_version"]} == {4}


def test_a_resume_cannot_mix_packages_under_one_identity(
    isolated_runner: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Review CR-02's failure scenario: a series begun with one package is
    # resumed by a process that imports other code.
    repository, package = tracked_package(tmp_path)
    act_with_package(monkeypatch, package)
    runner._gated_series("series.json", "test", PLAN[:1], n_steps=400, burn_in=100, execution=None, runner=Recorder())
    path = isolated_runner / "series.json"
    before = path.read_bytes()
    assert json.loads(before)["code_identity"] == REAL_CODE_IDENTITY(package)
    runner.OPTIONS.resume = True
    for copy in (ignored_copy(repository, package, modified=False), ignored_copy(repository, package, modified=True)):
        act_with_package(monkeypatch, copy)  # the same code untracked, and a modified copy
        refused_for_every_plan(path, before, "another protocol")
    act_with_package(monkeypatch, package)
    (package / "module.py").write_text("CHANGED = True\n")  # a tracked edit
    refused_for_every_plan(path, before, "another protocol")
    (package / "module.py").write_text("")
    (package / "untracked.py").write_text("")  # the same Git state, other code
    refused_for_every_plan(path, before, "another protocol")
    (package / "untracked.py").unlink()
    start_fresh_invocation()
    appended = Recorder()
    runner._gated_series("series.json", "test", PLAN, n_steps=400, burn_in=100, execution=None, runner=appended)
    assert appended.calls == [22]


def test_runs_made_from_an_untracked_copy_are_not_extended(
    isolated_runner: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, package = tracked_package(tmp_path)
    act_with_package(monkeypatch, ignored_copy(repository, package, modified=True))
    runner._gated_series("series.json", "test", PLAN[:1], n_steps=400, burn_in=100, execution=None, runner=Recorder())
    path = isolated_runner / "series.json"
    before = path.read_bytes()
    assert json.loads(before)["code_identity"]["git_head"] is None  # recorded as unknown
    runner.OPTIONS.resume = True
    start_fresh_invocation()
    idle = Recorder()
    with pytest.raises(runner.EvidenceRecordExists, match="code identity of this invocation is unknown"):
        runner._gated_series("series.json", "test", PLAN, n_steps=400, burn_in=100, execution=None, runner=idle)
    start_fresh_invocation()
    runner._gated_series("series.json", "test", PLAN[:1], n_steps=400, burn_in=100, execution=None, runner=idle)
    assert idle.calls == []
    assert path.read_bytes() == before  # nothing to add: verified, not written


def as_version_3(record: dict) -> None:
    """Rewrite a record as a version-3 runner wrote it: its code identity was the Git state of the runner's repository."""

    code = {"git_head": "test", "source_changes_sha256": "test"}  # the fixture's stand-in code identity
    record["series_protocol_version"] = 3
    record["code_identity"] = dict(code)
    for run in record["runs"]:
        run["protocol"].update(series_protocol_version=3, code=dict(code))
        run["protocol_hash"] = runner.protocol_digest(run["protocol"])


def test_a_version_3_record_is_neither_continued_nor_relabelled(isolated_runner: Path) -> None:
    # Series protocol 4 (OBS-07): even when a version-3 record's code identity
    # equals this invocation's, it names the runner's repository, not the
    # package its runs imported, so the record is refused, with or without
    # runs to add.
    runner._gated_series("series.json", "test", PLAN[:1], n_steps=400, burn_in=100, execution=None, runner=Recorder())
    path = isolated_runner / "series.json"
    record = json.loads(path.read_text())
    as_version_3(record)
    assert runner._inconsistencies(record) == []  # consistent: refused for its version alone
    path.write_text(json.dumps(record, indent=2) + "\n")
    runner.OPTIONS.resume = True
    refused_for_every_plan(path, path.read_bytes(), "series protocol version 3.*neither continued nor relabelled")


def test_the_committed_series_records_are_not_continued(isolated_runner: Path) -> None:
    # Byte copies of the committed records are resumed; the committed files
    # are only read.  None is version 4, so none is continued or relabelled,
    # and each refusal names the reason for its version.
    refusals = {}
    for source in sorted(LEGACY_EVIDENCE_DIR.glob("*.json")):
        original = source.read_bytes()
        runs = json.loads(original).get("runs")
        if not isinstance(runs, list) or not runs:
            continue
        protocols = [run.get("protocol") for run in runs]
        if not all(isinstance(protocol, dict) for protocol in protocols):
            kind, match = "no protocol", "predates run protocol identities"
        elif not all("environment" in protocol for protocol in protocols):
            kind, match = "version 2", "do not name the environment"
        elif all(protocol.get("series_protocol_version") == 3 for protocol in protocols):
            kind, match = "version 3", "series protocol version 3"
        else:
            kind, match = "version 4", "another protocol"  # another producer than the stand-in
        copy = isolated_runner / "series.json"
        copy.write_bytes(original)
        start_fresh_invocation()
        runner.OPTIONS.resume = True
        idle = Recorder()
        with pytest.raises(runner.EvidenceRecordExists, match=match):
            series(idle)
        assert idle.calls == [] and copy.read_bytes() == original, source.name
        refusals[kind] = refusals.get(kind, 0) + 1
    assert refusals.get("no protocol") and refusals.get("version 2")


# -- OBS-15..OBS-18 (review RV-01..RV-04, 2026-10-20): the identity fails closed --


UNKNOWN_CODE = {"package_sha256": None, "git_head": None, "source_changes_sha256": None}


def test_a_package_its_files_cannot_bind_has_an_unknown_identity(tmp_path: Path) -> None:
    # OBS-15 (review RV-01): code Python imports but a file digest would miss.
    repository, package = tracked_package(tmp_path)
    tracked = REAL_CODE_IDENTITY(package)
    vendor = repository / "vendor"
    (vendor / "sub").mkdir(parents=True)
    (vendor / "sub" / "__init__.py").write_text("")
    (vendor / "linked.py").write_text("VALUE = 1\n")
    (package / "linked.py").symlink_to("../../vendor/linked.py")  # a symlinked file is digested
    _git(repository, "add", "-A")
    _git(repository, "commit", "-q", "--no-verify", "-m", "a symlinked module")
    linked = REAL_CODE_IDENTITY(package)
    assert linked["git_head"] is not None and linked["package_sha256"] != tracked["package_sha256"]
    (vendor / "linked.py").write_text("VALUE = 2\n")
    assert REAL_CODE_IDENTITY(package)["package_sha256"] != linked["package_sha256"]
    (package / "sub").symlink_to("../../vendor/sub", target_is_directory=True)  # not followed
    assert {key: REAL_CODE_IDENTITY(package)[key] for key in UNKNOWN_CODE} == UNKNOWN_CODE
    (package / "sub").unlink()
    (package / "extra.pyc").write_bytes(b"sourceless bytecode")  # imported, never digested
    assert {key: REAL_CODE_IDENTITY(package)[key] for key in UNKNOWN_CODE} == UNKNOWN_CODE
    (package / "extra.pyc").unlink()
    assert REAL_CODE_IDENTITY(package)["git_head"] == linked["git_head"]
    archive = tmp_path / "packages.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("shwfs_ao/__init__.py", "VALUE = 1\n")
    for missing in (tmp_path / "missing" / "shwfs_ao", archive / "shwfs_ao"):  # no directory to digest
        assert {key: REAL_CODE_IDENTITY(missing)[key] for key in UNKNOWN_CODE} == UNKNOWN_CODE


def test_a_copy_path_with_glob_characters_borrows_no_git_state(tmp_path: Path) -> None:
    # OBS-16 (review RV-02): Git read copy[1]/... as a pattern matching the tracked copy1/...
    repository = tmp_path / "repository"
    tracked = repository / "copy1" / "src" / "shwfs_ao"
    tracked.mkdir(parents=True)
    (tracked / "__init__.py").write_text("VALUE = 1\n")
    _git(repository, "init", "-q")
    _git(repository, "add", "-A")
    _git(repository, "commit", "-q", "--no-verify", "-m", "fixture")
    assert REAL_CODE_IDENTITY(tracked)["git_head"] == _git(repository, "rev-parse", "HEAD")
    copy = repository / "copy[1]" / "src" / "shwfs_ao"
    shutil.copytree(tracked, copy)
    (copy / "__init__.py").write_text("VALUE = 2\n")
    copied = REAL_CODE_IDENTITY(copy)
    assert copied["git_head"] is None and copied["source_changes_sha256"] is None


def test_the_package_digest_binds_file_names(tmp_path: Path) -> None:
    # OBS-17 (review RV-03): a module renamed or moved with the same content is other code.
    _, package = tracked_package(tmp_path)
    original = runner._package_sha256(package)
    (package / "module.py").rename(package / "module_renamed.py")  # the same place in the file order
    assert runner._package_sha256(package) != original
    (package / "module_renamed.py").rename(package / "module.py")
    assert runner._package_sha256(package) == original
    (package / "sub").mkdir()
    (package / "module.py").rename(package / "sub" / "module.py")
    assert runner._package_sha256(package) != original


@pytest.mark.parametrize("version", [3, 5])
def test_the_version_refusal_gives_the_reason_for_its_version(isolated_runner: Path, version: int) -> None:
    # OBS-18 (review RV-04): version 3's reason only for a version-3 run.
    runner._gated_series("series.json", "test", PLAN[:1], n_steps=400, burn_in=100, execution=None, runner=Recorder())
    path = isolated_runner / "series.json"
    record = json.loads(path.read_text())
    record["series_protocol_version"] = version
    for run in record["runs"]:
        run["protocol"]["series_protocol_version"] = version
        run["protocol_hash"] = runner.protocol_digest(run["protocol"])
    path.write_text(json.dumps(record, indent=2) + "\n")
    before = path.read_bytes()
    start_fresh_invocation()
    runner.OPTIONS.resume = True
    idle = Recorder()
    with pytest.raises(runner.EvidenceRecordExists, match=f"series protocol version {version}") as refusal:
        runner._gated_series("series.json", "test", PLAN, n_steps=400, burn_in=100, execution=None, runner=idle)
    message = str(refusal.value)
    assert ("version-3 code identity names the runner's repository" in message) == (version == 3)
    assert ("another series protocol" in message) == (version != 3)
    assert idle.calls == [] and path.read_bytes() == before


def test_an_unchecked_bytecode_cache_leaves_the_code_unbound(tmp_path: Path) -> None:
    # Review RV-05: Python runs an unchecked hash-based cache without reading its source.
    _, package = tracked_package(tmp_path)
    tracked = REAL_CODE_IDENTITY(package)
    source = package / "__init__.py"
    cache = importlib.util.cache_from_source(str(source))
    for mode in py_compile.PycInvalidationMode:
        py_compile.compile(str(source), cfile=cache, invalidation_mode=mode, doraise=True)
        identity = REAL_CODE_IDENTITY(package)
        if mode is py_compile.PycInvalidationMode.UNCHECKED_HASH:
            assert {key: identity[key] for key in UNKNOWN_CODE} == UNKNOWN_CODE
        else:
            assert identity == tracked, mode  # Python checks it against its source


def test_an_idle_resume_does_not_verify_with_an_undigested_package(
    isolated_runner: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Review RV-06: every package without a digest has one identity, whatever its code.
    _, package = tracked_package(tmp_path)
    (package / "extra.pyc").write_bytes(b"sourceless bytecode")
    act_with_package(monkeypatch, package)
    runner._gated_series("series.json", "test", PLAN[:1], n_steps=400, burn_in=100, execution=None, runner=Recorder())
    path = isolated_runner / "series.json"
    before = path.read_bytes()
    assert json.loads(before)["code_identity"]["package_sha256"] is None
    runner.OPTIONS.resume = True
    for plan, match in ((PLAN[:1], "cannot verify that its code made them"), (PLAN, "code identity of this invocation is unknown")):
        start_fresh_invocation()
        idle = Recorder()
        with pytest.raises(runner.EvidenceRecordExists, match=match):
            runner._gated_series("series.json", "test", plan, n_steps=400, burn_in=100, execution=None, runner=idle)
        assert idle.calls == [] and path.read_bytes() == before


def test_the_bytecode_cache_is_checked_where_python_reads_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Review RV-07, RV-08: a symlinked __pycache__, a PYTHONPYCACHEPREFIX cache,
    # --check-hash-based-pycs never, and an unreadable cache.
    _, package = tracked_package(tmp_path)
    tracked = REAL_CODE_IDENTITY(package)
    source = package / "__init__.py"

    def cached(mode: py_compile.PycInvalidationMode) -> Path:
        cache = Path(importlib.util.cache_from_source(str(source)))
        py_compile.compile(str(source), cfile=str(cache), invalidation_mode=mode, doraise=True)
        return cache

    def unknown() -> bool:
        identity = REAL_CODE_IDENTITY(package)
        return {key: identity[key] for key in UNKNOWN_CODE} == UNKNOWN_CODE

    elsewhere = tmp_path / "cache_elsewhere"
    elsewhere.mkdir()
    (package / "__pycache__").symlink_to(elsewhere, target_is_directory=True)
    cached(py_compile.PycInvalidationMode.UNCHECKED_HASH)
    assert unknown()
    (package / "__pycache__").unlink()
    monkeypatch.setattr(sys, "pycache_prefix", str(tmp_path / "prefix"))
    assert cached(py_compile.PycInvalidationMode.UNCHECKED_HASH).is_relative_to(tmp_path / "prefix")
    assert unknown()
    cached(py_compile.PycInvalidationMode.CHECKED_HASH)
    assert REAL_CODE_IDENTITY(package) == tracked
    monkeypatch.setattr(runner._imp, "check_hash_based_pycs", "never")
    assert unknown()  # no hash-based cache is checked then
    monkeypatch.setattr(runner._imp, "check_hash_based_pycs", "default")
    cache = cached(py_compile.PycInvalidationMode.UNCHECKED_HASH)
    cache.chmod(0)
    try:
        assert REAL_CODE_IDENTITY(package) == tracked  # Python cannot read it either and compiles the source
    finally:
        cache.chmod(0o644)


# -- S4 traced family (ticket T1, 2026-10-20): gated commands, sidecars, protocols --


import time as _time  # noqa: E402

import numpy as np  # noqa: E402

from shwfs_ao.experiments import scao as _scao  # noqa: E402
from shwfs_ao.experiments import detector_level as _detector_level  # noqa: E402

TRACED_SETTINGS = {
    "profile": ("det_emccd_2m_synthetic", 1), "magnitudes": (7.0,), "seeds": (21, 22), "n_steps": 20, "burn_in": 5,
    "record": "traced.json", "map_seeds": {"m7": 22},
}
TRACED_PLAN = [("m7", CONFIG, 21), ("m7", CONFIG, 22)]


def _never(*arguments, **keywords):
    raise AssertionError("a simulation or system build was reached by a refused or inert invocation")


@pytest.fixture
def no_simulation(monkeypatch: pytest.MonkeyPatch) -> None:
    # Every builder and simulation boundary a traced command could reach: the
    # factory in scao, its alias imported into detector_level at import time,
    # and the three paired-run entry points.
    monkeypatch.setattr(_scao, "build_scao_system", _never)
    monkeypatch.setattr(_detector_level, "build_scao_system", _never)
    monkeypatch.setattr(_detector_level, "paired_noise_run", _never)
    monkeypatch.setattr(_detector_level, "paired_noise_run_traced", _never)
    monkeypatch.setattr(_detector_level, "paired_noise_run_mask_locked", _never)
    monkeypatch.setattr(_detector_level, "science_run", _never)


from _trace_fixtures import fake_traced_run  # noqa: E402


@pytest.fixture
def inert_traced(monkeypatch: pytest.MonkeyPatch, no_simulation: None) -> None:
    monkeypatch.setattr(_detector_level, "paired_noise_run_traced", fake_traced_run)
    monkeypatch.setattr(_detector_level, "paired_noise_run_mask_locked", lambda *a, **k: fake_traced_run(*a, allow_partial_lock=k.pop("allow_partial_lock", False), **k))


def traced_series(settings: dict = TRACED_SETTINGS, plan: list = TRACED_PLAN, *, mode: str = "traced", name: str | None = None) -> None:
    runner._gated_series(
        settings["record"] if name is None else name, "traced test", plan, n_steps=settings["n_steps"], burn_in=settings["burn_in"],
        execution=None, runner=runner.traced_run_factory(settings, mode=mode), run_context=True,
        validate_retained=runner.traced_record_validator(settings, mode=mode), header_extra={"record_family": runner.TRACE_FAMILY},
    )


def _snapshot(directory: Path) -> dict:
    return {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in directory.iterdir()}


def test_the_traced_12m_commands_refuse_before_any_profile_or_system_without_the_note(isolated_runner: Path, no_simulation: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from shwfs_ao.io import configs as _configs

    monkeypatch.setattr(_configs, "load_system_profile", _never)
    for command in ("noise-isolation-12m-traced", "noise-isolation-12m-masklocked"):
        with pytest.raises(SystemExit) as refusal:
            runner.main([command])
        assert refusal.value.code == 2  # argparse: --enabled-by-user is required
    assert list(isolated_runner.iterdir()) == []


def test_the_traced_commands_reach_the_gated_series_with_their_own_settings(isolated_runner: Path, no_simulation: None, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict] = []

    def record_only(name, command, plan, **keywords):
        seen.append({"name": name, "command": command, "labels": sorted({label for label, _, _ in plan}), "seeds": sorted({seed for _, _, seed in plan}), **{k: v for k, v in keywords.items() if k in ("n_steps", "burn_in", "enabled_by_user", "run_context")}})

    monkeypatch.setattr(runner, "_gated_series", record_only)
    assert runner.main(["noise-isolation-2m-traced"]) == 0
    assert runner.main(["noise-isolation-12m-traced", "--enabled-by-user", "test note"]) == 0
    assert runner.main(["noise-isolation-12m-masklocked", "--enabled-by-user", "test note"]) == 0
    assert seen[0]["name"] == "det09_noise_isolation_2m_traced.json" and seen[0]["enabled_by_user"].startswith("not gated")
    assert seen[0]["labels"] == ["m5", "m6", "m7", "m8"] and seen[0]["seeds"] == list(range(61, 69)) and seen[0]["n_steps"] == 200 and seen[0]["burn_in"] == 50
    assert seen[1]["name"] == "det09_noise_isolation_12m_traced.json" and seen[1]["enabled_by_user"] == "test note"
    assert seen[1]["labels"] == ["m10", "m11", "m8", "m9"] and seen[1]["seeds"] == list(range(71, 76)) and seen[1]["n_steps"] == 400
    assert seen[2]["name"] == "det09_noise_isolation_12m_masklocked.json" and seen[2]["labels"] == ["m11"] and seen[2]["seeds"] == list(range(71, 81))
    assert all(entry["run_context"] is True for entry in seen)
    assert list(isolated_runner.iterdir()) == []


def test_a_traced_series_publishes_one_verified_sidecar_per_run_and_a_no_op_resume_changes_nothing(isolated_runner: Path, inert_traced: None) -> None:
    traced_series()
    record = json.loads((isolated_runner / "traced.json").read_text())
    assert record["record_family"] == runner.TRACE_FAMILY and record["series_protocol_version"] == 4
    assert sorted(path.name for path in isolated_runner.iterdir()) == ["traced.json", "traced__m7__seed21.npz", "traced__m7__seed22.npz"]
    for run in record["runs"]:
        reference = run["sidecar"]
        path = isolated_runner / reference["file"]
        assert reference["file"] == runner.sidecar_name("traced", "m7", run["root_seed"]) and reference["schema"] == runner.TRACE_SIDECAR_SCHEMA
        assert path.stat().st_size == reference["bytes"] and hashlib.sha256(path.read_bytes()).hexdigest() == reference["sha256"]
        metadata, arrays = runner.read_sidecar(path, expected_sha256=reference["sha256"])
        assert metadata["label"] == "m7" and metadata["root_seed"] == run["root_seed"] and metadata["protocol_hash"] == run["protocol_hash"]
        assert metadata["diagnostic_protocol_hash"] == run["diagnostic_protocol_hash"] == runner.protocol_digest(run["diagnostic_protocol"])
        assert metadata["code"] == run["protocol"]["code"] and metadata["environment"] == run["protocol"]["environment"]
        assert set(metadata["arrays"]) == set(arrays) and arrays["delta_v_m2"].shape == (15,)
        assert arrays["noise_on__telemetry__centroids_xy_px"].shape == (20, 3, 2) and arrays["row_ids"].dtype.kind == "U"
        # The sidecar digest is output integrity: it appears in no protocol payload.
        assert reference["sha256"] not in json.dumps(run["protocol"]) and reference["sha256"] not in json.dumps(run["diagnostic_protocol"])
        assert run["diagnostic_protocol"]["map_retention"] == {"label": "m7", "root_seed": run["root_seed"], "retained": run["root_seed"] == 22}
    assert "residual_maps__noise_on" in runner.read_sidecar(isolated_runner / "traced__m7__seed22.npz")[1]
    assert "residual_maps__noise_on" not in runner.read_sidecar(isolated_runner / "traced__m7__seed21.npz")[1]
    # The physical protocol is the series protocol 4 payload, unchanged by tracing.
    expected = runner.run_protocol("m7", CONFIG, 21, n_steps=20, burn_in=5, execution=None, code=runner.code_identity())
    assert record["runs"][0]["protocol_hash"] == expected["protocol_hash"]
    assert runner._inconsistencies(record) == []
    # A complete, compatible no-op invocation reads and compares only.
    before = _snapshot(isolated_runner)
    _time.sleep(0.01)
    start_fresh_invocation()
    runner.OPTIONS.resume = True
    traced_series()
    assert _snapshot(isolated_runner) == before
    # Without --resume the existing record is refused as always.
    start_fresh_invocation()
    runner.OPTIONS.resume = False
    with pytest.raises(runner.EvidenceRecordExists, match="--resume"):
        traced_series()
    assert _snapshot(isolated_runner) == before


def test_an_interrupted_traced_series_resumes_the_missing_run_only(isolated_runner: Path, inert_traced: None) -> None:
    traced_series(plan=TRACED_PLAN[:1])
    start_fresh_invocation()
    runner.OPTIONS.resume = True
    traced_series()
    record = json.loads((isolated_runner / "traced.json").read_text())
    assert [run["root_seed"] for run in record["runs"]] == [21, 22]
    assert sorted(path.name for path in isolated_runner.iterdir()) == ["traced.json", "traced__m7__seed21.npz", "traced__m7__seed22.npz"]


SIDECAR_TAMPERING = {
    "corrupt byte": "corrupt",
    "missing file": "missing",
    "orphan sidecar": "orphan",
    "interrupted temporary": "temporary",
    "renamed reference": "rename",
    "diagnostic hash": "diagnostic",
    "mixed producer": "producer",
    "size": "size",
}


@pytest.mark.parametrize("tampering", sorted(SIDECAR_TAMPERING))
def test_a_traced_resume_refuses_damaged_or_ambiguous_evidence_unchanged(isolated_runner: Path, inert_traced: None, tampering: str) -> None:
    traced_series(plan=TRACED_PLAN[:1])
    record_path = isolated_runner / "traced.json"
    record = json.loads(record_path.read_text())
    sidecar = isolated_runner / record["runs"][0]["sidecar"]["file"]
    kind = SIDECAR_TAMPERING[tampering]
    if kind == "corrupt":
        data = sidecar.read_bytes()
        sidecar.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
        match = "SHA-256"
    elif kind == "missing":
        sidecar.unlink()
        match = "missing"
    elif kind == "orphan":
        (isolated_runner / runner.sidecar_name("traced", "m7", 99)).write_bytes(b"orphan")
        match = "not referenced"
    elif kind == "temporary":
        (isolated_runner / f"{sidecar.name}{runner._SIDECAR_TEMP_MARK}123-abcd").write_bytes(b"partial")
        match = "not referenced"
    elif kind == "rename":
        record["runs"][0]["sidecar"]["file"] = "traced__m7__seed21_renamed.npz"
        record_path.write_text(json.dumps(record, indent=2) + "\n")
        match = "another name or schema"
    elif kind == "diagnostic":
        record["runs"][0]["diagnostic_protocol"]["frame_domain"] = "other"
        record_path.write_text(json.dumps(record, indent=2) + "\n")
        match = "not the digest of its payload"
    elif kind == "producer":
        metadata, arrays = runner.read_sidecar(sidecar)
        metadata["code"] = {**metadata["code"], "git_head": "other"}
        sidecar.unlink()
        reference = runner.publish_sidecar(sidecar, arrays, metadata)
        record["runs"][0]["sidecar"] = reference
        record_path.write_text(json.dumps(record, indent=2) + "\n")
        match = "mixed producers"
    else:
        record["runs"][0]["sidecar"]["bytes"] += 1
        record_path.write_text(json.dumps(record, indent=2) + "\n")
        match = "bytes"
    before = _snapshot(isolated_runner)
    for plan in (TRACED_PLAN, TRACED_PLAN[:1]):  # with a run to add, and with nothing left to run
        start_fresh_invocation()
        runner.OPTIONS.resume = True
        with pytest.raises(runner.EvidenceRecordExists, match=match):
            traced_series(plan=plan)
        assert _snapshot(isolated_runner) == before


def test_an_old_traced_record_is_refused_under_other_diagnostic_semantics_although_its_physical_hash_matches(isolated_runner: Path, inert_traced: None) -> None:
    traced_series()
    record = json.loads((isolated_runner / "traced.json").read_text())
    physical = [run["protocol_hash"] for run in record["runs"]]
    before = _snapshot(isolated_runner)
    # Another map retention is another diagnostic protocol for that run.
    other_retention = {**TRACED_SETTINGS, "map_seeds": {"m7": 21}}
    start_fresh_invocation()
    runner.OPTIONS.resume = True
    with pytest.raises(runner.EvidenceRecordExists, match="retained residual maps"):
        traced_series(settings=other_retention)
    # Another mode (arm order, mask source) is another diagnostic protocol too.
    start_fresh_invocation()
    with pytest.raises(runner.EvidenceRecordExists, match="other diagnostic semantics"):
        traced_series(mode="mask_locked")
    assert _snapshot(isolated_runner) == before
    # The physical protocol of those runs is the one an untraced series gives:
    # tracing semantics live beside it, never in it.
    for run, digest in zip(record["runs"], physical):
        plain = runner.run_protocol(run["label"], CONFIG, run["root_seed"], n_steps=20, burn_in=5, execution=None, code=runner.code_identity())
        assert plain["protocol_hash"] == digest


def test_sidecar_publication_is_atomic_and_never_clobbers(isolated_runner: Path) -> None:
    destination = isolated_runner / "family__m7__seed1.npz"
    arrays = {"delta_v_m2": np.arange(3.0)}
    metadata = {"schema": runner.TRACE_SIDECAR_SCHEMA, "arrays": {"delta_v_m2": {"dtype": "float64", "shape": [3]}}}
    reference = runner.publish_sidecar(destination, arrays, metadata)
    assert reference["file"] == destination.name and destination.stat().st_size == reference["bytes"]
    first = destination.read_bytes()
    with pytest.raises(runner.TraceSidecarError, match="exists"):
        runner.publish_sidecar(destination, {"delta_v_m2": np.zeros(3)}, metadata)
    assert destination.read_bytes() == first
    assert [path.name for path in isolated_runner.iterdir()] == [destination.name]  # no temporary left behind
    # Reading refuses undeclared or mis-declared content and pickles are never allowed.
    loaded_metadata, loaded = runner.read_sidecar(destination, expected_sha256=reference["sha256"])
    np.testing.assert_array_equal(loaded["delta_v_m2"], arrays["delta_v_m2"])
    with pytest.raises(runner.TraceSidecarError, match="SHA-256"):
        runner.read_sidecar(destination, expected_sha256="0" * 64)
    undeclared = isolated_runner / "undeclared.npz"
    np.savez(undeclared, metadata_json=np.array(json.dumps(metadata)), delta_v_m2=np.arange(3.0), extra=np.zeros(2))
    with pytest.raises(runner.TraceSidecarError, match="declared arrays"):
        runner.read_sidecar(undeclared)
    wrong_shape = isolated_runner / "shape.npz"
    np.savez(wrong_shape, metadata_json=np.array(json.dumps(metadata)), delta_v_m2=np.arange(4.0))
    with pytest.raises(runner.TraceSidecarError, match="declared"):
        runner.read_sidecar(wrong_shape)
    pickled = isolated_runner / "pickled.npz"
    np.savez(pickled, metadata_json=np.array(json.dumps(metadata)), delta_v_m2=np.array([object()], dtype=object), allow_pickle=True)
    with pytest.raises(runner.TraceSidecarError):
        runner.read_sidecar(pickled)


def test_an_orphan_sidecar_from_an_interrupted_publication_is_refused_before_a_fresh_series(isolated_runner: Path, inert_traced: None) -> None:
    # The sidecar was published, the process died before its row was appended.
    orphan = isolated_runner / runner.sidecar_name("traced", "m7", 21)
    runner.publish_sidecar(orphan, {"x": np.zeros(1)}, {"schema": runner.TRACE_SIDECAR_SCHEMA, "arrays": {"x": {"dtype": "float64", "shape": [1]}}})
    before = _snapshot(isolated_runner)
    with pytest.raises(runner.EvidenceRecordExists, match="not referenced"):
        traced_series()
    assert _snapshot(isolated_runner) == before and not (isolated_runner / "traced.json").exists()


def test_a_mask_locked_series_records_the_lock_and_its_own_diagnostic_protocol(isolated_runner: Path, inert_traced: None) -> None:
    settings = {**TRACED_SETTINGS, "record": "locked.json", "map_seeds": {"m7": 21}}
    traced_series(settings=settings, plan=TRACED_PLAN[:1], mode="mask_locked")
    record = json.loads((isolated_runner / "locked.json").read_text())
    run = record["runs"][0]
    assert run["lock"] == {"exact": True} and run["diagnostic_protocol"]["mode"] == "mask_locked"
    assert run["diagnostic_protocol"]["arm_order"] == list(_detector_level.MASK_LOCKED_NOISE_ARMS)
    assert run["diagnostic_protocol"]["forced_row_policy"] == "refuse_nonfinite_forced_rows"
    metadata, arrays = runner.read_sidecar(isolated_runner / run["sidecar"]["file"], expected_sha256=run["sidecar"]["sha256"])
    assert metadata["lock"] == {"exact": True} and "mask_lock__rows_added" in arrays
    assert "noise_on_mask_locked__measurement_row_masks" in arrays and "residual_maps__noise_on_mask_locked" in arrays


# -- Independent review of 2026-10-20 (T1-02, T1-03): payload semantics and refusals --


def _inert_metadata(diagnostic: dict, protocol: dict, *, n_steps: int = 20, burn_in: int = 5) -> dict:
    return {
        "schema": runner.TRACE_SIDECAR_SCHEMA, "family": runner.TRACE_FAMILY, "record_stem": "traced", "label": "m7", "root_seed": 21,
        "config_hash": protocol["protocol"]["config_hash"], "protocol_hash": protocol["protocol_hash"],
        "diagnostic_protocol_hash": runner.protocol_digest(diagnostic), "code": protocol["protocol"]["code"],
        "environment": protocol["protocol"]["environment"], "n_steps": n_steps, "burn_in_frames": burn_in,
        "diagnostic_protocol": diagnostic, "trace_schema": diagnostic["trace_schema"], "arm_order": diagnostic["arm_order"],
        "noisy_arm": "noise_on", "twin_arm": "operating_expectation",
        "arms": {arm: {"telemetry_unavailable": []} for arm in diagnostic["arm_order"]},
        "propagation_weights": {"available": True},
    }


def _write_record(directory: Path, rows: list[dict]) -> Path:
    record = {
        "record_family": runner.TRACE_FAMILY, "series_protocol_version": 4, "code_identity": runner.code_identity(),
        **runner.producer_environment(), "n_steps": 20, "burn_in_frames": 5, "enabled_by_user": "test go-ahead", "runs": rows,
    }
    path = directory / "traced.json"
    path.write_text(json.dumps(record, indent=2) + "\n")
    return path


MALFORMED_SIDECARS = {
    # The reviewer's first case: a correctly hashed archive holding only an empty series.
    "empty_series_only": (lambda arrays, meta: ({"delta_v_m2": np.empty(0)}, {**meta, "arrays": {"delta_v_m2": {"dtype": "float64", "shape": [0], "units": "m2", "axes": ["analysed_frame"], "meaning": "x"}}}), "no row layout|exactly the protocol's arrays"),
    # The reviewer's second case: contradictory embedded frame counts, schema, arm order and diagnostic payload.
    "inconsistent_metadata": (lambda arrays, meta: (arrays, {**meta, "n_steps": 999, "burn_in_frames": 998, "trace_schema": "wrong.trace.schema", "arm_order": ["wrong_arm"], "diagnostic_protocol": {"other_semantics": True}}), "n_steps"),
    "wrong_frame_domain": (lambda arrays, meta: ({**arrays, "analysed_frame_index": np.arange(0, 15, dtype=np.int64)}, meta), "analysed_frame_index"),
    "missing_telemetry_array": (lambda arrays, meta: ({k: v for k, v in arrays.items() if k != "noise_on__telemetry__centroids_xy_px"}, {**meta, "arrays": {k: v for k, v in meta["arrays"].items() if k != "noise_on__telemetry__centroids_xy_px"}}), "exactly the protocol's arrays"),
    "undeclared_extra_array": (lambda arrays, meta: ({**arrays, "extra": np.zeros(3)}, {**meta, "arrays": {**meta["arrays"], "extra": {"dtype": "float64", "shape": [3], "units": "1", "axes": ["x"], "meaning": "x"}}}), "exactly the protocol's arrays"),
    "wrong_dtype": (lambda arrays, meta: ({**arrays, "noise_on__measurement_row_masks": arrays["noise_on__measurement_row_masks"].astype(np.int64)}, {**meta, "arrays": {**meta["arrays"], "noise_on__measurement_row_masks": {**meta["arrays"]["noise_on__measurement_row_masks"], "dtype": "int64"}}}), "dtype"),
    "odd_row_count": (lambda arrays, meta: ({**arrays, "row_ids": np.array(["a", "b", "c", "d", "e"]), "calibration_valid_rows": np.ones(5, dtype=bool)}, {**meta, "arrays": {**meta["arrays"], "row_ids": {**meta["arrays"]["row_ids"], "shape": [5], "dtype": "<U1"}, "calibration_valid_rows": {**meta["arrays"]["calibration_valid_rows"], "shape": [5]}}}), "two rows per lenslet"),
    "other_run_embedded": (lambda arrays, meta: (arrays, {**meta, "root_seed": 99}), "another label or seed"),
}


@pytest.mark.parametrize("case", sorted(MALFORMED_SIDECARS))
def test_a_digest_bound_malformed_or_inconsistent_sidecar_is_refused_before_reuse(isolated_runner: Path, inert_traced: None, case: str) -> None:
    # A real inert series supplies a correct archive; each case rewrites the
    # archive with a correct digest and reference, so only the semantics are wrong.
    traced_series(plan=TRACED_PLAN[:1])
    record_path = isolated_runner / "traced.json"
    record = json.loads(record_path.read_text())
    row = record["runs"][0]
    sidecar = isolated_runner / row["sidecar"]["file"]
    metadata, arrays = runner.read_sidecar(sidecar)
    mutate, match = MALFORMED_SIDECARS[case]
    new_arrays, new_metadata = mutate(dict(arrays), json.loads(json.dumps(metadata)))
    if case == "inconsistent_metadata":
        new_metadata["diagnostic_protocol_hash"] = runner.protocol_digest(new_metadata["diagnostic_protocol"])
        row["diagnostic_protocol_hash"] = row["diagnostic_protocol_hash"]  # the row stays correct
    sidecar.unlink()
    row["sidecar"] = runner.publish_sidecar(sidecar, new_arrays, new_metadata)
    record_path.write_text(json.dumps(record, indent=2) + "\n")
    before = _snapshot(isolated_runner)
    for plan in (TRACED_PLAN, TRACED_PLAN[:1]):  # with a run to add, and the complete no-op
        start_fresh_invocation()
        runner.OPTIONS.resume = True
        with pytest.raises(runner.EvidenceRecordExists, match=match):
            traced_series(plan=plan)
        assert _snapshot(isolated_runner) == before
    # The published archive itself is checked the same way at publication time.
    with pytest.raises(runner.TraceSidecarError, match=match):
        protocol = runner.run_protocol("m7", CONFIG, 21, n_steps=20, burn_in=5, execution=None, code=runner.code_identity())
        runner.validate_trace_payload(
            new_metadata, new_arrays, label="m7", root_seed=21, n_steps=20, burn_in=5,
            diagnostic=row["diagnostic_protocol"], diagnostic_hash=row["diagnostic_protocol_hash"], where="check",
        )
        del protocol


def test_a_sidecar_that_only_claims_the_right_arrays_is_refused_on_its_own(isolated_runner: Path) -> None:
    # The reviewer's probe without a series: a self-consistent archive of one
    # empty array, published under a correct identity, fails the semantic check.
    diagnostic = runner.diagnostic_protocol(mode="traced", label="m7", root_seed=21, retain_residual_maps=False, propagation_weights=True, allow_partial_lock=None)
    protocol = runner.run_protocol("m7", CONFIG, 21, n_steps=20, burn_in=5, execution=None, code=runner.code_identity())
    metadata = _inert_metadata(diagnostic, protocol)
    metadata["arrays"] = {"delta_v_m2": {"dtype": "float64", "shape": [0], "units": "m2", "axes": ["analysed_frame"], "meaning": "x"}}
    destination = isolated_runner / runner.sidecar_name("traced", "m7", 21)
    reference = runner.publish_sidecar(destination, {"delta_v_m2": np.empty(0)}, metadata)
    loaded_metadata, loaded_arrays = runner.read_sidecar(destination, expected_sha256=reference["sha256"])
    with pytest.raises(runner.TraceSidecarError, match="no row layout"):
        runner.validate_trace_payload(loaded_metadata, loaded_arrays, label="m7", root_seed=21, n_steps=20, burn_in=5, diagnostic=diagnostic, diagnostic_hash=runner.protocol_digest(diagnostic), where="probe")
    row = {"label": "m7", "root_seed": 21, "config_hash": protocol["protocol"]["config_hash"], **protocol, "diagnostic_protocol": diagnostic, "diagnostic_protocol_hash": runner.protocol_digest(diagnostic), "sidecar": reference}
    path = _write_record(isolated_runner, [row])
    before = _snapshot(isolated_runner)
    with pytest.raises(runner.EvidenceRecordExists, match="no row layout"):
        runner.traced_record_validator(TRACED_SETTINGS, mode="traced")(path, [row])
    assert _snapshot(isolated_runner) == before


@pytest.mark.parametrize("error", ["construction", "calibration"])
def test_supported_construction_refusals_keep_their_diagnostic_identity_and_resume(isolated_runner: Path, no_simulation: None, monkeypatch: pytest.MonkeyPatch, error: str) -> None:
    from shwfs_ao.calibration.interaction import InteractionMatrixError

    exception = _scao.ScaoConstructionError if error == "construction" else InteractionMatrixError
    calls: list[int] = []

    def refused(config, *, root_seed, **keywords):
        calls.append(int(root_seed))
        raise exception("inert supported refusal")

    monkeypatch.setattr(_detector_level, "paired_noise_run_traced", refused)
    traced_series(plan=TRACED_PLAN[:1])
    record_path = isolated_runner / "traced.json"
    record = json.loads(record_path.read_text())
    row = record["runs"][0]
    assert row["status"] == "refused" and "inert supported refusal" in row["reason"]
    assert row["diagnostic_protocol"]["map_retention"] == {"label": "m7", "root_seed": 21, "retained": False}
    assert row["diagnostic_protocol_hash"] == runner.protocol_digest(row["diagnostic_protocol"])
    assert "sidecar" not in row and record["refused"][0]["root_seed"] == 21
    assert [path.name for path in isolated_runner.iterdir()] == ["traced.json"]
    before = _snapshot(isolated_runner)
    # Complete no-op resume: nothing runs, nothing changes.
    start_fresh_invocation()
    runner.OPTIONS.resume = True
    traced_series(plan=TRACED_PLAN[:1])
    assert calls == [21] and _snapshot(isolated_runner) == before
    # Partial continuation: the refused row is kept as written, the new run is added with a sidecar.
    monkeypatch.setattr(_detector_level, "paired_noise_run_traced", fake_traced_run)
    start_fresh_invocation()
    traced_series()
    record = json.loads(record_path.read_text())
    assert [run["root_seed"] for run in record["runs"]] == [21, 22] and record["runs"][0] == row
    assert record["runs"][1]["sidecar"]["file"] == runner.sidecar_name("traced", "m7", 22)
    assert runner._inconsistencies(record) == []


def test_legacy_untraced_refusals_are_unchanged(isolated_runner: Path, no_simulation: None) -> None:
    # The legacy handler still records a plain refused row for an untraced runner.
    def refused(config, *, root_seed, n_steps, burn_in_frames, execution):
        raise _scao.ScaoConstructionError("legacy refusal")

    runner._gated_series("legacy.json", "test", PLAN[:1], n_steps=400, burn_in=100, execution=None, runner=refused)
    record = json.loads((isolated_runner / "legacy.json").read_text())
    assert record["runs"][0]["status"] == "refused" and "diagnostic_protocol" not in record["runs"][0]


# -- Independent review round 2 (2026-10-21, T1-02): semantic values, row and lenslet order --


from _trace_fixtures import SIDECAR_MUTATIONS, mutate_sidecar  # noqa: E402


def _series_for(mode: str, settings: dict, plan: list) -> None:
    traced_series(settings=settings, plan=plan, mode=mode)


@pytest.mark.parametrize("name", sorted(SIDECAR_MUTATIONS))
def test_every_reviewed_sidecar_mutation_is_refused_by_the_runner_before_reuse(isolated_runner: Path, inert_traced: None, name: str) -> None:
    """Both review rounds' mutations of a valid archive: one semantic element changed, digest and reference correct.

    Units, axes and meaning are compared with the canonical schema; the twin's
    lenslet order and the interleaved x/y row order are required; shapes and
    dtypes are exact.  Every case is refused on a complete no-op resume and
    before a pending inert run, with record and sidecar bytes and mtimes
    untouched, and by the publication-time check.
    """

    mode, runner_match, _ = SIDECAR_MUTATIONS[name]
    settings = {**TRACED_SETTINGS, "map_seeds": {}} if mode == "traced" else {**TRACED_SETTINGS, "record": "locked.json", "map_seeds": {}}
    _series_for(mode, settings, TRACED_PLAN[:1])
    record_path = isolated_runner / settings["record"]
    record = json.loads(record_path.read_text())
    row = record["runs"][0]
    sidecar = isolated_runner / row["sidecar"]["file"]
    metadata, arrays = runner.read_sidecar(sidecar)
    new_arrays, new_metadata = mutate_sidecar(name, arrays, metadata)
    sidecar.unlink()
    row["sidecar"] = runner.publish_sidecar(sidecar, new_arrays, new_metadata)
    record_path.write_text(json.dumps(record, indent=2) + "\n")
    before = _snapshot(isolated_runner)
    for plan in (TRACED_PLAN[:1], TRACED_PLAN):  # complete no-op, then partial continuation
        start_fresh_invocation()
        runner.OPTIONS.resume = True
        with pytest.raises(runner.EvidenceRecordExists, match=runner_match):
            _series_for(mode, settings, plan)
        assert _snapshot(isolated_runner) == before
    with pytest.raises(runner.TraceSidecarError, match=runner_match):
        runner.validate_trace_payload(
            new_metadata, new_arrays, label="m7", root_seed=21, n_steps=20, burn_in=5,
            diagnostic=row["diagnostic_protocol"], diagnostic_hash=row["diagnostic_protocol_hash"], where="check",
        )


def test_a_valid_sidecar_passes_the_value_level_checks_in_both_modes(isolated_runner: Path, inert_traced: None) -> None:
    for mode, name in (("traced", "traced.json"), ("mask_locked", "locked.json")):
        settings = {**TRACED_SETTINGS, "record": name, "map_seeds": {"m7": 21}}
        _series_for(mode, settings, TRACED_PLAN[:1])
        record = json.loads((isolated_runner / name).read_text())
        row = record["runs"][0]
        metadata, arrays = runner.read_sidecar(isolated_runner / row["sidecar"]["file"], expected_sha256=row["sidecar"]["sha256"])
        runner.validate_trace_payload(
            metadata, arrays, label="m7", root_seed=21, n_steps=20, burn_in=5,
            diagnostic=row["diagnostic_protocol"], diagnostic_hash=row["diagnostic_protocol_hash"], where="check",
        )
        # The canonical row layout is the package's own definition.
        from shwfs_ao.wfs.shack_hartmann.calibration import row_ids_for_subapertures

        assert tuple(arrays["row_ids"].tolist()) == row_ids_for_subapertures(tuple(arrays["noise_on__subaperture_ids" if mode == "traced" else "noise_on_mask_locked__subaperture_ids"].tolist()))
