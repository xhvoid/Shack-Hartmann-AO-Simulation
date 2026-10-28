"""G4: the detector evidence runner's opt-in fresh-process mode, validated with inert workers only.

Each job runs a stand-in from ``fresh_process_workers`` in a fresh interpreter (the runner script in its child
mode): no system is built, no loop runs and ``science_run`` is never called -- the science dispatch below is a
labelled MOCK with its signature.  Deliberate allocations stay at or below 96 MiB, one worker at a time, and the
memory assertions are generous bounds, never exact RSS values.  Nothing here measures an AO run.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import time

import pytest

from shwfs_ao.experiments.scao import ScaoConstructionError, ScaoExecutionOptions
from shwfs_ao.io.configs import load_system_profile


ROOT = Path(__file__).resolve().parents[2]
WORKERS = str(Path(__file__).resolve().parent)
_SPEC = importlib.util.spec_from_file_location(
    "run_detector_level_evidence_for_fresh_process_tests", ROOT / "scripts/run_detector_level_evidence.py"
)
assert _SPEC is not None and _SPEC.loader is not None
runner = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = runner
_SPEC.loader.exec_module(runner)

MIB = 2**20
BUDGET = 512 * MIB  # recorded by every job; enforced only when AO_RESOURCE_GUARD=1
TIMEOUT_S = 120.0
# The measurement is Linux VmHWM; elsewhere it is recorded as unavailable, so the tests that read it need /proc.
needs_vmhwm = pytest.mark.skipif(not Path("/proc/self/status").is_file(), reason="the child's peak RSS is read from Linux /proc VmHWM")


def _job(tmp_path: Path, target: str, *args, name: str = "job", timeout_s: float = TIMEOUT_S, **kwargs):
    return runner.run_in_fresh_process(
        f"fresh_process_workers:{target}", args, kwargs, job_dir=tmp_path / name, label=name,
        timeout_s=timeout_s, budget_bytes=BUDGET, import_paths=(WORKERS,),
    )


def _running(pid: int) -> bool:
    """Whether ``pid`` is a live process (a zombie waiting to be reaped is not)."""

    stat = Path(f"/proc/{pid}/stat")
    if Path("/proc").is_dir():
        try:
            return stat.read_text().rsplit(")", 1)[1].split()[0] not in ("Z", "X")
        except (OSError, IndexError):
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@needs_vmhwm
def test_a_successful_job_round_trips_its_result_and_reports_its_own_peak(tmp_path):
    value = {"text": "café", "numbers": [1, 2.5, None], "nested": {"flag": True}}
    result, envelope = _job(tmp_path, "echo", value)
    assert result == {"echo": value, "pid": envelope["child"]["pid"]} and result["pid"] != os.getpid()
    assert envelope["schema"] == "detector-evidence.fresh-process-execution.v1" and envelope["mode"] == "fresh_process"
    assert envelope["status"] == "succeeded" and envelope["returncode"] == 0 and envelope["child"]["outcome"] == "returned"
    peak = envelope["child_process_peak_rss_bytes"]
    measurement = envelope["child_process_peak_rss"]
    assert isinstance(peak, int) and 8 * MIB < peak < 1024 * MIB  # an interpreter with its imports; generous bounds
    assert measurement["available"] is True and measurement["unavailable_reason"] is None and measurement["unit"] == "bytes"
    assert envelope["child"]["vm_hwm_bytes"] == peak and envelope["child"]["ru_maxrss_bytes"] >= peak
    assert "VmHWM" in measurement["method"] and "excludes the supervising parent" in measurement["boundary"] and "ru_maxrss" in measurement["ru_maxrss_note"]
    assert "process-group peak" in measurement["is_not"] and "capacity budget" in measurement["is_not"]
    files = envelope["files"]
    assert all(files[name] is not None for name in ("job.json", "payload.pickle", "child.json", "result.json", "output.log")) and files["exception.pickle"] is None
    assert json.loads((tmp_path / "job" / "envelope.json").read_text()) == envelope
    assert envelope["timing"]["supervised_wall_s"] > 0 and envelope["child"]["finished_unix_s"] >= envelope["child"]["started_unix_s"]


def test_raw_output_of_both_streams_is_kept(tmp_path):
    result, envelope = _job(tmp_path, "print_both_streams")
    assert result == {"printed": True} and envelope["status"] == "succeeded"
    log = (tmp_path / "job" / "output.log").read_text()
    assert "fresh-process worker: to stdout" in log and "fresh-process worker: to stderr" in log


@needs_vmhwm
def test_a_raising_worker_is_a_failure_with_its_exception_and_its_measurement(tmp_path):
    result, envelope = _job(tmp_path, "raise_value_error", "stand-in failure")
    assert result is None and envelope["status"] == "failed" and envelope["returncode"] == 1
    assert envelope["child"]["outcome"] == "raised" and envelope["child"]["exception"]["type"] == "builtins.ValueError"
    assert envelope["child"]["exception"]["message"] == "stand-in failure" and "Traceback" in envelope["child"]["exception"]["traceback"]
    assert envelope["files"]["exception.pickle"] is not None and envelope["files"]["result.json"] is None
    # The child reported in its finally block, so its own peak exists although the job failed.
    assert envelope["child_process_peak_rss"]["available"] is True and envelope["child_process_peak_rss_bytes"] > 0


def test_a_worker_that_exits_without_reporting_has_no_measurement_not_zero(tmp_path):
    result, envelope = _job(tmp_path, "exit_without_report", 7)
    assert result is None and envelope["status"] == "failed" and envelope["returncode"] == 7 and envelope["child"] is None
    assert envelope["child_process_peak_rss_bytes"] is None
    assert envelope["child_process_peak_rss"]["available"] is False
    assert "ended without writing its report" in envelope["child_process_peak_rss"]["unavailable_reason"]


def test_a_timed_out_worker_and_its_descendants_are_stopped(tmp_path):
    pid_file = tmp_path / "pids.json"
    started = time.monotonic()
    result, envelope = _job(tmp_path, "sleep_with_grandchild", str(pid_file), 600, timeout_s=3.0)
    assert time.monotonic() - started < 60.0
    assert result is None and envelope["status"] == "timed_out" and envelope["status_reason"].startswith("wall-clock limit 3 s exceeded")
    assert envelope["child"] is None and envelope["child_process_peak_rss_bytes"] is None
    assert "stopped before it wrote its report" in envelope["child_process_peak_rss"]["unavailable_reason"]
    pids = json.loads(pid_file.read_text())
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline and any(_running(pid) for pid in pids.values()):
        time.sleep(0.1)
    assert not any(_running(pid) for pid in pids.values()), pids


def test_existing_output_is_refused_before_anything_runs(tmp_path):
    marker = tmp_path / "marker"
    (tmp_path / "job").mkdir()
    with pytest.raises(runner.FreshProcessError, match="never reuses an output directory"):
        _job(tmp_path, "touch", str(marker))
    assert not marker.exists() and list((tmp_path / "job").iterdir()) == []
    used = tmp_path / "jobs"
    used.mkdir()
    with pytest.raises(runner.FreshProcessError, match="must name a new directory"):
        runner.fresh_process_runner(used, timeout_s=TIMEOUT_S, budget_bytes=BUDGET)


def test_parent_and_child_identity_and_environment(tmp_path):
    import shwfs_ao

    result, envelope = _job(tmp_path, "report_environment")
    root = str(Path(shwfs_ao.__file__).resolve().parents[1])
    given = envelope["environment_given"]
    assert result["environment"]["PYTHONPATH"] == given["PYTHONPATH"] == root
    assert result["shwfs_ao_file"] == envelope["parent"]["shwfs_ao_file"] == str(Path(shwfs_ao.__file__).resolve())
    assert result["executable"] == sys.executable and result["ppid"] == os.getpid() and result["pid"] == envelope["child"]["pid"]
    assert result["environment"]["AO_RESOURCE_GUARD"] == os.environ.get("AO_RESOURCE_GUARD") == given["AO_RESOURCE_GUARD"]
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
        assert result["environment"][name] == given[name] and 0 < int(given[name]) <= 2
    assert envelope["child_imports_parent_code"] is True
    assert envelope["child"]["script_sha256"] == envelope["parent"]["script_sha256"]
    assert envelope["child"]["target_file"] == str(Path(WORKERS, "fresh_process_workers.py"))


@needs_vmhwm
def test_the_measurement_excludes_the_supervisor_footprint_that_ru_maxrss_keeps(tmp_path):
    # The parent holds 64 MiB of written bytes while it starts the child.  Linux keeps the spawned-from image's
    # high-water mark in an exec'd child's ru_maxrss; VmHWM starts at the exec, so only the child's own use is in it.
    held = b"\x01" * (64 * MIB)
    status = Path("/proc/self/status").read_text().splitlines()
    parent_rss = next(int(line.split()[1]) * 1024 for line in status if line.startswith("VmRSS:"))
    result, envelope = _job(tmp_path, "echo", len(held))
    del held
    peak, inherited = envelope["child_process_peak_rss_bytes"], envelope["child"]["ru_maxrss_bytes"]
    assert result["echo"] == 64 * MIB and parent_rss >= 64 * MIB
    assert inherited >= parent_rss - 16 * MIB  # ru_maxrss carries the parent's footprint at spawn
    assert peak + 48 * MIB <= inherited and peak < parent_rss  # the recorded measurement does not


@needs_vmhwm
def test_fresh_workers_report_their_own_peaks_and_a_reused_process_cannot(tmp_path):
    # Serial fresh children, one at a time: each reports its own lifetime peak.
    large, large_envelope = _job(tmp_path, "allocate", 96, name="fresh-96")
    small, small_envelope = _job(tmp_path, "allocate", 16, name="fresh-16")
    peak_large = large_envelope["child_process_peak_rss_bytes"]
    peak_small = small_envelope["child_process_peak_rss_bytes"]
    assert large["allocated_bytes"] == 96 * MIB and small["allocated_bytes"] == 16 * MIB
    assert peak_large >= 96 * MIB and peak_large - peak_small >= 48 * MIB
    # Control: the same two calls in one reused process.  The peak read after the later, smaller call still holds
    # the earlier allocation, so it says nothing about that call.  (No difference of two high-water marks is taken
    # anywhere as a per-call value.)
    reused, _ = _job(tmp_path, "reused_process_sequence", 96, 16, name="reused")
    assert reused["after_second"] >= reused["after_first"] >= reused["baseline"] + 64 * MIB
    assert reused["after_second"] - peak_small >= 48 * MIB


@needs_vmhwm
def test_mocked_science_dispatch_round_trips_a_real_configuration(tmp_path):
    # MOCK: the dispatch target is an inert stand-in with science_run's signature.  Loading the profile builds nothing.
    config = load_system_profile("det_ccd_2m_synthetic", 1)
    run = runner.fresh_process_runner(tmp_path / "jobs", timeout_s=TIMEOUT_S, budget_bytes=BUDGET, target="fresh_process_workers:mock_science_run", import_paths=(WORKERS,))
    assert not (tmp_path / "jobs").exists()  # nothing is created before the first call
    first = run(config, root_seed=21, n_steps=400, burn_in_frames=100, execution=ScaoExecutionOptions(telemetry_level="summary"))
    second = run(config, root_seed=22, n_steps=400, burn_in_frames=100, execution=None)
    assert first["mock"].startswith("inert stand-in") and first["config_hash"] == config.config_hash
    assert (first["root_seed"], first["n_steps"], first["burn_in_frames"], first["telemetry_level"]) == (21, 400, 100, "summary")
    assert isinstance(first["process_peak_rss_bytes"], int)  # the legacy field keeps its name and its source
    envelope = first["execution_envelope"]
    assert envelope["status"] == "succeeded" and envelope["target"] == "fresh_process_workers:mock_science_run"
    assert isinstance(envelope["child_process_peak_rss_bytes"], int) and envelope["child_process_peak_rss_bytes"] > 0
    assert sorted(path.name for path in (tmp_path / "jobs").iterdir()) == [f"0001-seed21-{config.config_hash[:12]}", f"0002-seed22-{config.config_hash[:12]}"]
    assert second["execution_envelope"]["label"].startswith("0002-seed22-")
    assert runner.fresh_process_runner(tmp_path / "default", timeout_s=TIMEOUT_S, budget_bytes=BUDGET).target == "shwfs_ao.experiments.detector_level:science_run"


def test_a_job_that_raised_reraises_its_own_exception_type(tmp_path):
    config = load_system_profile("det_ccd_2m_synthetic", 1)
    run = runner.fresh_process_runner(tmp_path / "jobs", timeout_s=TIMEOUT_S, budget_bytes=BUDGET, target="fresh_process_workers:raise_scao_construction_error", import_paths=(WORKERS,))
    with pytest.raises(ScaoConstructionError, match="stand-in refusal") as raised:
        run(config, root_seed=21, n_steps=400, burn_in_frames=100)
    assert isinstance(raised.value.__cause__, runner.FreshProcessError) and raised.value.__cause__.envelope["status"] == "failed"


def test_the_mode_is_opt_in_and_refuses_what_it_does_not_cover(tmp_path, monkeypatch):
    from shwfs_ao.experiments.detector_level import science_run

    def custom(config, **_):
        return {}

    legacy_options = runner.argparse.Namespace(output=None, overwrite=False, resume=False, enabled_by_user=None, output_dir=None)
    monkeypatch.setattr(runner, "OPTIONS", legacy_options)
    assert runner._series_runner(None, False) is science_run and runner._series_runner(custom, True) is custom
    monkeypatch.setattr(runner, "OPTIONS", runner.argparse.Namespace(**vars(legacy_options), fresh_process_dir=None, fresh_process_timeout_s=None, fresh_process_budget_bytes=None))
    assert runner._series_runner(None, False) is science_run
    fresh = runner.argparse.Namespace(**vars(legacy_options), fresh_process_dir=tmp_path / "jobs", fresh_process_timeout_s=60.0, fresh_process_budget_bytes=BUDGET)
    monkeypatch.setattr(runner, "OPTIONS", fresh)
    selected = runner._series_runner(None, False)
    assert selected.target == "shwfs_ao.experiments.detector_level:science_run" and not (tmp_path / "jobs").exists()
    for runner_function, run_context in ((custom, False), (None, True)):
        with pytest.raises(runner.FreshProcessUnsupported, match="has no fresh-process mode"):
            runner._series_runner(runner_function, run_context)


@pytest.mark.parametrize("argv", [
    ["--fresh-process-dir", "DIR", "e3"],
    ["--fresh-process-dir", "DIR", "--fresh-process-timeout-s", "60", "e3"],
    ["--fresh-process-dir", "DIR", "--fresh-process-timeout-s", "-1", "--fresh-process-budget-mib", "512", "e3"],
    ["--fresh-process-dir", "DIR", "--fresh-process-timeout-s", "60", "--fresh-process-budget-mib", "512", "e1"],
    ["--fresh-process-dir", "DIR", "--fresh-process-timeout-s", "60", "--fresh-process-budget-mib", "512", "noise-isolation-2m"],
    ["--fresh-process-timeout-s", "60", "e3"],
])
def test_the_command_line_checks_the_opt_in_before_anything_runs(tmp_path, monkeypatch, argv):
    monkeypatch.setattr(runner, "OPTIONS", runner.argparse.Namespace(**vars(runner.OPTIONS)))
    with pytest.raises(SystemExit) as stopped:
        runner.main([str(tmp_path / "jobs") if item == "DIR" else item for item in argv])
    assert stopped.value.code == 2 and not (tmp_path / "jobs").exists()
