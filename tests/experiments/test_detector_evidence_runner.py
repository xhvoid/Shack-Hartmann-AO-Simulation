"""Review R6: the detector evidence runner never reuses or replaces silently.

The runner script is loaded by file, as the other script-guard tests do, and
driven with a stand-in run function, so no simulation runs.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

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
# Captured before any fixture redirects it: the legacy default directory.
LEGACY_EVIDENCE_DIR = runner.EVIDENCE_DIR

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


def test_the_real_gated_commands_refuse_without_a_note_before_building_anything(isolated_runner: Path) -> None:
    # e5 is the 42 m run: the refusal must come before any system is built.
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
    assert record["series_protocol_version"] == 3
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
    # The version-2 shape: runs carry no producing environment.
    legacy["series_protocol_version"] = 2
    for run in legacy["runs"]:
        del run["protocol"]["environment"]
        run["protocol"]["series_protocol_version"] = 2
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
