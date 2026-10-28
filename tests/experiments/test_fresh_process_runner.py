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
    assert "vfork" in measurement["ru_maxrss_note"] and "historical peak" in measurement["ru_maxrss_note"]
    assert "not an exact allocation" in measurement["accounting_limits"] and "inaccurate" in measurement["accounting_limits"]
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
    ["--fresh-process-dir", "DIR", "--fresh-process-timeout-s", "60", "--fresh-process-budget-mib", "1e-9", "e3"],
    ["--fresh-process-dir", "DIR", "--fresh-process-timeout-s", "nan", "--fresh-process-budget-mib", "512", "e3"],
])
def test_the_command_line_checks_the_opt_in_before_anything_runs(tmp_path, monkeypatch, argv):
    monkeypatch.setattr(runner, "OPTIONS", runner.argparse.Namespace(**vars(runner.OPTIONS)))
    with pytest.raises(SystemExit) as stopped:
        runner.main([str(tmp_path / "jobs") if item == "DIR" else item for item in argv])
    assert stopped.value.code == 2 and not (tmp_path / "jobs").exists()


# -- R18-01: every location is the caller's, fixed before the child starts in its own working directory --------------


def _forbid_science(monkeypatch):
    """Make the science entry points raise in this process, so a test that reaches one fails instead of computing."""

    import shwfs_ao.control.loop
    import shwfs_ao.experiments.detector_level
    import shwfs_ao.experiments.scao

    def forbidden(*_, **__):
        raise AssertionError("a fresh-process test reached a science entry point")

    for module, name in (
        (shwfs_ao.experiments.detector_level, "science_run"),
        (shwfs_ao.experiments.scao, "build_scao_system"),
        (shwfs_ao.experiments.scao, "run_closed_loop"),
        (shwfs_ao.control.loop, "run_closed_loop"),
    ):
        monkeypatch.setattr(module, name, forbidden)


@pytest.fixture
def caller_cwd(tmp_path, monkeypatch):
    """A working directory outside the repository, with a space and non-ASCII characters in its name."""

    cwd = tmp_path / "caller cwd ü"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    assert Path.cwd() != ROOT
    return cwd


def _relative_job(target: str, *args, job_dir, timeout_s: float = TIMEOUT_S, import_paths=(WORKERS,), **kwargs):
    return runner.run_in_fresh_process(
        f"fresh_process_workers:{target}" if ":" not in target else target, args, kwargs, job_dir=job_dir, label="job",
        timeout_s=timeout_s, budget_bytes=BUDGET, import_paths=import_paths,
    )


@pytest.mark.parametrize("form", ["absolute", "relative", "nested relative", "space and non-ASCII"])
def test_every_job_dir_form_names_one_place_for_parent_and_child(caller_cwd, form):
    requested = {
        "absolute": caller_cwd / "absolute job",
        "relative": Path("job"),
        "nested relative": Path("a") / "b" / "job",
        "space and non-ASCII": "jobs dir/jöb ñame",
    }[form]
    located = Path(requested) if Path(requested).is_absolute() else caller_cwd / requested
    result, envelope = _relative_job("report_paths", job_dir=requested)
    assert envelope["status"] == "succeeded", envelope["status_reason"]
    assert envelope["job_dir"] == str(located) and envelope["job_dir_requested"] == str(requested)
    assert result["cwd"] == str(located) and result["argv"] == [runner.FRESH_PROCESS_CHILD_FLAG, str(located / "job.json")]
    assert sorted(path.name for path in located.iterdir()) == ["child.json", "envelope.json", "job.json", "output.log", "payload.pickle", "result.json"]
    log = (located / "output.log").read_text()
    assert "fresh-process worker: paths to stdout" in log and "fresh-process worker: paths to stderr" in log
    job = json.loads((located / "job.json").read_text())
    assert job["job_dir"] == str(located) and job["import_paths"] == [WORKERS]
    assert json.loads((located / "envelope.json").read_text()) == envelope
    # Nothing is created anywhere but the requested place: no doubled job directory inside it, nothing else here.
    top = Path(requested).parts[0] if not Path(requested).is_absolute() else "absolute job"
    assert [path.name for path in caller_cwd.iterdir()] == [top]


def test_a_relative_import_path_is_the_callers_and_is_recorded_as_given(caller_cwd):
    (caller_cwd / "worker modules").mkdir()
    (caller_cwd / "worker modules" / "relative_import_worker.py").write_text("def where():\n    return __file__\n")
    result, envelope = _relative_job("relative_import_worker:where", job_dir="job", import_paths=("worker modules",))
    assert envelope["status"] == "succeeded" and result == str(caller_cwd / "worker modules" / "relative_import_worker.py")
    job = json.loads((caller_cwd / "job" / "job.json").read_text())
    assert job["import_paths"] == [str(caller_cwd / "worker modules")] and job["import_paths_requested"] == ["worker modules"]


def test_the_failure_outcomes_hold_for_a_relative_job_dir(caller_cwd):
    result, raised = _relative_job("raise_value_error", "stand-in failure", job_dir="out/raised")
    assert result is None and raised["status"] == "failed" and raised["child"]["outcome"] == "raised"
    assert raised["child"]["exception"]["type"] == "builtins.ValueError" and (caller_cwd / "out/raised/exception.pickle").is_file()
    result, exited = _relative_job("exit_without_report", 7, job_dir="out/exited")
    assert result is None and exited["status"] == "failed" and exited["returncode"] == 7 and exited["child"] is None
    assert exited["child_process_peak_rss_bytes"] is None and exited["child_process_peak_rss"]["available"] is False
    pid_file = caller_cwd / "pids.json"
    started = time.monotonic()
    result, stopped = _relative_job("sleep_with_grandchild", str(pid_file), 600, job_dir="out/stopped", timeout_s=3.0)
    assert time.monotonic() - started < 60.0 and result is None and stopped["status"] == "timed_out"
    assert stopped["child"] is None and stopped["child_process_peak_rss_bytes"] is None
    pids = json.loads(pid_file.read_text())
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline and any(_running(pid) for pid in pids.values()):
        time.sleep(0.1)
    assert not any(_running(pid) for pid in pids.values()), pids
    # Every outcome left its files where the caller asked, for diagnosis; no job wrote anywhere else.
    for name in ("raised", "exited", "stopped"):
        assert {"job.json", "payload.pickle", "output.log", "envelope.json"} <= {path.name for path in (caller_cwd / "out" / name).iterdir()}
    assert sorted(path.name for path in caller_cwd.iterdir()) == ["out", "pids.json"]


def test_an_existing_relative_job_dir_is_refused_and_its_bytes_are_kept(caller_cwd):
    (caller_cwd / "jobs" / "job").mkdir(parents=True)
    kept = caller_cwd / "jobs" / "job" / "kept.bin"
    kept.write_bytes(b"\x00earlier output\xff")
    marker = caller_cwd / "marker"
    with pytest.raises(runner.FreshProcessError, match="never reuses an output directory"):
        _relative_job("touch", str(marker), job_dir="jobs/job")
    assert not marker.exists() and kept.read_bytes() == b"\x00earlier output\xff" and [path.name for path in kept.parent.iterdir()] == ["kept.bin"]
    with pytest.raises(runner.FreshProcessError, match="must name a new directory"):
        runner.fresh_process_runner("jobs", timeout_s=TIMEOUT_S, budget_bytes=BUDGET)
    assert kept.read_bytes() == b"\x00earlier output\xff" and [path.name for path in (caller_cwd / "jobs").iterdir()] == ["job"]


def test_the_adapter_fixes_its_directory_at_construction(caller_cwd, monkeypatch):
    # MOCK science target; loading the profile builds nothing.
    config = load_system_profile("det_ccd_2m_synthetic", 1)
    run = runner.fresh_process_runner("adapter jobs/ü", timeout_s=TIMEOUT_S, budget_bytes=BUDGET, target="fresh_process_workers:mock_science_run", import_paths=(WORKERS,))
    assert run.directory == caller_cwd / "adapter jobs" / "ü" and run.directory_requested == "adapter jobs/ü"
    elsewhere = caller_cwd.parent / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)  # a later change of working directory does not move the jobs
    first = run(config, root_seed=31, n_steps=400, burn_in_frames=100)
    assert first["mock"].startswith("inert stand-in") and first["execution_envelope"]["status"] == "succeeded"
    job_dir = caller_cwd / "adapter jobs" / "ü" / f"0001-seed31-{config.config_hash[:12]}"
    assert first["execution_envelope"]["job_dir"] == str(job_dir) and (job_dir / "result.json").is_file()
    assert list(elsewhere.iterdir()) == []


def _cli(*options: str, command: str = "det08") -> list[str]:
    return ["--fresh-process-timeout-s", "60", "--fresh-process-budget-mib", "512", *options, command]


def test_the_command_line_dispatch_runs_each_planned_run_in_a_fresh_job(caller_cwd, monkeypatch):
    # MOCK dispatch: the target is the inert stand-in; the science entry points raise in this process.
    _forbid_science(monkeypatch)
    monkeypatch.setattr(runner, "OPTIONS", runner.argparse.Namespace(**vars(runner.OPTIONS)))
    monkeypatch.setattr(runner, "_STARTED", set())
    monkeypatch.setattr(runner, "FRESH_PROCESS_TARGET", "fresh_process_workers:mock_science_run")
    monkeypatch.setattr(runner, "FRESH_PROCESS_IMPORT_PATHS", (WORKERS,))
    argv = _cli("--fresh-process-dir", "fresh jobs/ü", "--output-dir", "records", "--enabled-by-user", "test fixture: mock dispatch only")
    assert runner.main(argv) == 0
    jobs = caller_cwd / "fresh jobs" / "ü"
    assert runner.OPTIONS.fresh_process_dir == jobs
    record = json.loads((caller_cwd / "records" / "det08_exposure_subsamples_12m.json").read_text())
    assert len(record["runs"]) == 15 and sorted(path.name for path in caller_cwd.iterdir()) == ["fresh jobs", "records"]
    for index, entry in enumerate(record["runs"], 1):
        envelope = entry["execution_envelope"]
        assert entry["mock"].startswith("inert stand-in") and envelope["status"] == "succeeded"
        assert envelope["target"] == "fresh_process_workers:mock_science_run" and envelope["label"].startswith(f"{index:04d}-seed{entry['root_seed']}-")
        assert Path(envelope["job_dir"]).parent == jobs and (Path(envelope["job_dir"]) / "result.json").is_file()
    assert len(list(jobs.iterdir())) == 15


def test_the_command_line_refuses_an_existing_fresh_process_dir_before_anything_runs(caller_cwd, monkeypatch):
    _forbid_science(monkeypatch)
    monkeypatch.setattr(runner, "OPTIONS", runner.argparse.Namespace(**vars(runner.OPTIONS)))
    (caller_cwd / "used").mkdir()
    (caller_cwd / "used" / "kept.bin").write_bytes(b"kept\x00")
    with pytest.raises(SystemExit) as stopped:
        runner.main(_cli("--fresh-process-dir", "used", "--output-dir", "records", "--enabled-by-user", "test fixture"))
    assert stopped.value.code == 2 and (caller_cwd / "used" / "kept.bin").read_bytes() == b"kept\x00"
    assert sorted(path.name for path in caller_cwd.iterdir()) == ["used"]


@pytest.mark.parametrize("change", [
    {"timeout_s": 0}, {"timeout_s": -1.0}, {"timeout_s": float("nan")}, {"timeout_s": float("inf")}, {"timeout_s": True}, {"timeout_s": "60"},
    {"budget_bytes": 0}, {"budget_bytes": -1}, {"budget_bytes": 1.5 * MIB}, {"budget_bytes": True},
    {"target": "no_colon"}, {"target": ":function"}, {"target": "module:"}, {"target": "a:b:c"}, {"target": None},
])
def test_invalid_options_fail_before_anything_is_created(caller_cwd, change):
    options = {"target": "fresh_process_workers:echo", "timeout_s": TIMEOUT_S, "budget_bytes": BUDGET, **change}
    with pytest.raises(runner.FreshProcessError, match="nothing ran"):
        runner.run_in_fresh_process(options["target"], ("x",), {}, job_dir="parent/job", label="job", timeout_s=options["timeout_s"], budget_bytes=options["budget_bytes"], import_paths=(WORKERS,))
    if change.get("target", "") is not None:
        with pytest.raises(runner.FreshProcessError, match="nothing ran"):
            runner.fresh_process_runner("jobs", **options)
    assert list(caller_cwd.iterdir()) == []


def test_an_argument_that_cannot_be_sent_fails_before_anything_is_created(caller_cwd):
    import pickle

    with pytest.raises((pickle.PicklingError, AttributeError, TypeError)):  # the type depends on the Python version
        _relative_job("echo", lambda: None, job_dir="parent/job")
    assert list(caller_cwd.iterdir()) == []


def test_a_child_that_cannot_be_started_is_a_launch_failure_with_no_measurement(caller_cwd, monkeypatch):
    monkeypatch.setattr(sys, "executable", str(caller_cwd.parent / "no such interpreter"))
    result, envelope = _relative_job("echo", "x", job_dir="job")
    assert result is None and envelope["status"] == "launch_failed" and "could not be started" in envelope["status_reason"]
    assert envelope["returncode"] is None and envelope["child"] is None and envelope["supervisor"] is None
    assert envelope["child_process_peak_rss_bytes"] is None and envelope["child_process_peak_rss"]["available"] is False
    assert envelope["child_process_peak_rss"]["unavailable_reason"] == "no child was started; no measurement exists"
    kept = {path.name for path in (caller_cwd / "job").iterdir()}
    assert {"job.json", "payload.pickle", "envelope.json"} <= kept and "result.json" not in kept
    assert json.loads((caller_cwd / "job" / "envelope.json").read_text()) == envelope
    config = load_system_profile("det_ccd_2m_synthetic", 1)
    run = runner.fresh_process_runner("jobs", timeout_s=TIMEOUT_S, budget_bytes=BUDGET, target="fresh_process_workers:mock_science_run", import_paths=(WORKERS,))
    with pytest.raises(runner.FreshProcessError, match="launch_failed") as failed:
        run(config, root_seed=1, n_steps=400, burn_in_frames=100)
    assert failed.value.envelope["status"] == "launch_failed"


@pytest.mark.parametrize("damage", ["payload", "job"])
def test_unreadable_control_input_is_a_failure_not_a_success(caller_cwd, monkeypatch, damage):
    import shwfs_ao.runtime.resource_guard as guard

    real = guard.run_supervised

    def damaged(argv, **options):  # test-controlled: spoil one control file after it was written, then start the real child
        target = Path(options["cwd"]) / ("payload.pickle" if damage == "payload" else "job.json")
        target.write_bytes(b"not what was recorded")
        return real(argv, **options)

    monkeypatch.setattr(guard, "run_supervised", damaged)
    marker = caller_cwd / "marker"
    result, envelope = _relative_job("touch", str(marker), job_dir="job")
    assert result is None and envelope["status"] == "failed" and envelope["returncode"] == 1 and not marker.exists()
    assert envelope["child"]["outcome"] == "raised" and envelope["files"]["result.json"] is None
    expected = "FreshProcessError" if damage == "payload" else "JSONDecodeError"
    assert envelope["child"]["exception"]["type"].endswith(expected)


def test_a_hand_run_child_resolves_a_relative_job_file_against_its_own_cwd(caller_cwd):
    import pickle
    import subprocess

    import shwfs_ao

    job_dir = caller_cwd / "hand job"
    job_dir.mkdir()
    payload = pickle.dumps((("by hand",), {}))
    (job_dir / "payload.pickle").write_bytes(payload)
    job = {"target": "fresh_process_workers:echo", "import_paths": [WORKERS], "payload": {"file": "payload.pickle", "sha256": runner.hashlib.sha256(payload).hexdigest()}}
    (job_dir / "job.json").write_text(json.dumps(job))
    environment = {**os.environ, "PYTHONPATH": str(Path(shwfs_ao.__file__).resolve().parents[1]), "PYTHONDONTWRITEBYTECODE": "1"}
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/run_detector_level_evidence.py"), runner.FRESH_PROCESS_CHILD_FLAG, "hand job/job.json"],
        cwd=caller_cwd, env=environment, capture_output=True, timeout=TIMEOUT_S, check=False,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    assert json.loads((job_dir / "result.json").read_text())["echo"] == "by hand"
    assert json.loads((job_dir / "child.json").read_text())["outcome"] == "returned"


def test_the_documented_example_is_a_working_invocation(caller_cwd, monkeypatch):
    import shlex

    # The command is replaced by a recorder: the example's options are parsed and checked, nothing runs.
    example = runner.__doc__.split("for example::", 1)[1].split("\n\n", 2)[1]
    words = shlex.split(example.replace("\\\n", " "))
    assert words[:2] == ["python", "scripts/run_detector_level_evidence.py"] and words[-1] == "det08"
    seen = []
    monkeypatch.setattr(runner, "OPTIONS", runner.argparse.Namespace(**vars(runner.OPTIONS)))
    monkeypatch.setattr(runner, "det08", lambda arguments: seen.append(runner.argparse.Namespace(**vars(runner.OPTIONS))))
    assert runner.main(words[2:]) == 0
    (options,) = seen
    assert options.fresh_process_dir == caller_cwd / "outputs/g4-det08/jobs" and options.output_dir == Path("outputs/g4-det08")
    assert options.fresh_process_timeout_s == 3600 and options.fresh_process_budget_bytes == 4096 * MIB and options.enabled_by_user == "DATE: WORDING"
    assert list(caller_cwd.iterdir()) == []
