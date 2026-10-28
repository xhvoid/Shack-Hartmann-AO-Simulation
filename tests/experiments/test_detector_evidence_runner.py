"""Review R6: the detector evidence runner never reuses or replaces silently.

The runner script is loaded by file, as the other script-guard tests do, and
driven with a stand-in run function, so no simulation runs.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

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

CONFIG = load_system_profile("det_emccd_2m_synthetic", 1)
PLAN = [("label", CONFIG, 21), ("label", CONFIG, 22)]


@pytest.fixture(autouse=True)
def isolated_runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(runner, "EVIDENCE_DIR", tmp_path)
    monkeypatch.setattr(runner, "OPTIONS", runner.argparse.Namespace(output=None, overwrite=False, resume=False, enabled_by_user=None))
    monkeypatch.setattr(runner, "_STARTED", set())
    monkeypatch.setattr(runner, "code_identity", lambda: {"git_head": "test", "source_changes_sha256": "test"})
    return tmp_path


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
