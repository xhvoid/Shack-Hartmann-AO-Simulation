"""Tiny synthetic checks of the desktop-safe resource policy (ESO-00).

Nothing here allocates more than a few MiB or creates real memory pressure:
budget and pressure violations are injected through stub probes, and the
timeout/cleanup paths use short sleeping children.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import sys
import time

import pytest

from shwfs_ao.runtime.resource_guard import (
    GIB,
    MIB,
    THREAD_ENV_VARS,
    UNRELIABLE_HOST_BUDGET_BYTES,
    HostSnapshot,
    MemoryPressure,
    ResourceBudgetExceeded,
    ResourceEstimate,
    ResourcePolicyError,
    desktop_budget_bytes,
    limited_environment,
    preflight,
    process_group_rss_bytes,
    require_preflight,
    run_supervised,
    thread_limit_environment,
)


def _snapshot(
    *,
    physical: int | None = 16 * GIB,
    available: int | None = 8 * GIB,
    level: str = "normal",
) -> HostSnapshot:
    return HostSnapshot(
        platform="test",
        machine="test",
        cpu_count=8,
        physical_bytes=physical,
        available_bytes=available,
        available_source="stub",
        pressure=MemoryPressure(level=level, raw=None, source="stub"),  # type: ignore[arg-type]
        timestamp_unix_s=0.0,
    )


def _estimate(raw_mib: float, *, largest_mib: float = 1.0) -> ResourceEstimate:
    return ResourceEstimate(
        label="synthetic",
        baseline_bytes=0,
        components={"arrays": int(raw_mib * MIB)},
        largest_buffer_bytes=int(largest_mib * MIB),
    )


def test_budget_is_the_minimum_of_the_three_policy_terms():
    # 16 GiB physical, 8 GiB available: 2 GiB cap wins over 2 GiB / 2 GiB.
    budget, _ = desktop_budget_bytes(_snapshot(available=8 * GIB))
    assert budget == 2 * GIB
    # Only 4 GiB available: 25 % of it (1 GiB) wins.
    budget, rationale = desktop_budget_bytes(_snapshot(available=4 * GIB))
    assert budget == 1 * GIB and "available" in rationale
    # An 8 GiB host: 12.5 % of physical (1 GiB) wins.
    budget, rationale = desktop_budget_bytes(
        _snapshot(physical=8 * GIB, available=6 * GIB)
    )
    assert budget == 1 * GIB and "physical" in rationale


@pytest.mark.parametrize(
    "snapshot",
    [
        _snapshot(available=None),
        _snapshot(physical=None),
        _snapshot(level="unknown"),
    ],
)
def test_unreliable_measurement_falls_back_to_one_gib(snapshot):
    budget, rationale = desktop_budget_bytes(snapshot)
    assert budget == UNRELIABLE_HOST_BUDGET_BYTES
    assert "reliably" in rationale


def test_preflight_rejects_known_over_budget_jobs_before_allocation():
    snapshot = _snapshot(available=4 * GIB)  # 1 GiB budget
    accepted = preflight(_estimate(400.0), snapshot=snapshot)
    assert accepted.accepted and accepted.required_bytes == 800 * MIB
    refused = preflight(_estimate(600.0), snapshot=snapshot)  # 1200 MiB with margin
    assert not refused.accepted
    assert "exceeds" in refused.reasons[0]
    with pytest.raises(ResourceBudgetExceeded, match="refused before allocation"):
        require_preflight(_estimate(600.0), snapshot=snapshot)


def test_preflight_enforces_the_scratch_buffer_ceiling_and_current_pressure():
    snapshot = _snapshot()
    big_buffer = preflight(_estimate(10.0, largest_mib=65.0), snapshot=snapshot)
    assert not big_buffer.accepted
    assert any("scratch ceiling" in reason for reason in big_buffer.reasons)
    for level in ("warn", "critical"):
        decision = preflight(_estimate(10.0), snapshot=_snapshot(level=level))
        assert not decision.accepted
        assert any(level in reason for reason in decision.reasons)


def test_a_caller_may_lower_but_never_raise_the_policy_budget():
    snapshot = _snapshot(available=4 * GIB)  # 1 GiB policy budget
    raised = preflight(_estimate(600.0), snapshot=snapshot, budget_bytes=8 * GIB)
    assert not raised.accepted and raised.budget_bytes == 1 * GIB
    lowered = preflight(_estimate(100.0), snapshot=snapshot, budget_bytes=150 * MIB)
    assert not lowered.accepted and lowered.budget_bytes == 150 * MIB


def test_estimates_reject_malformed_inputs():
    with pytest.raises(ResourcePolicyError):
        ResourceEstimate(label="", baseline_bytes=0, components={}, largest_buffer_bytes=0)
    with pytest.raises(ResourcePolicyError):
        ResourceEstimate(
            label="x", baseline_bytes=0, components={"a": -1}, largest_buffer_bytes=0
        )
    with pytest.raises(ResourcePolicyError):
        ResourceEstimate(
            label="x", baseline_bytes=0, components={}, largest_buffer_bytes=0, margin=0.5
        )


def test_thread_limits_are_capped_by_cpus_and_never_raised():
    limits = thread_limit_environment(2, cpu_count=1)
    assert set(limits) == set(THREAD_ENV_VARS)
    assert set(limits.values()) == {"1"}
    environment = limited_environment({"OMP_NUM_THREADS": "1", "PATH": "/usr/bin"})
    assert environment["OMP_NUM_THREADS"] == "1"
    assert environment["OPENBLAS_NUM_THREADS"] in {"1", "2"}
    environment = limited_environment({"OMP_NUM_THREADS": "64"})
    assert int(environment["OMP_NUM_THREADS"]) <= 2


def _normal() -> MemoryPressure:
    return MemoryPressure(level="normal", raw="1", source="stub")


def test_supervised_child_sees_thread_limits_before_importing_numpy(tmp_path: Path):
    log = tmp_path / "child.log"
    script = (
        "import json, os, sys;"
        "print(json.dumps({k: os.environ.get(k) for k in %r}));"
        "print('numpy_loaded=' + str('numpy' in sys.modules))"
    ) % (list(THREAD_ENV_VARS),)
    result = run_supervised(
        [sys.executable, "-c", script],
        budget_bytes=512 * MIB,
        timeout_s=30.0,
        log_path=log,
        pressure_probe=_normal,
    )
    assert result.status == "COMPLETED", result
    lines = log.read_text().splitlines()
    seen = json.loads(lines[0])
    assert all(seen[name] in {"1", "2"} for name in THREAD_ENV_VARS)
    assert lines[1] == "numpy_loaded=False"
    assert result.peak_rss_bytes is not None and result.peak_rss_bytes > 0


def test_budget_violation_stops_the_group_without_allocating(tmp_path: Path):
    result = run_supervised(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        budget_bytes=64 * MIB,
        timeout_s=30.0,
        log_path=tmp_path / "budget.log",
        rss_probe=lambda pgid: 65 * MIB,
        pressure_probe=_normal,
    )
    assert result.status == "RESOURCE_LIMITED"
    assert "budget" in result.reason
    assert result.wall_s < 5.0


def test_warning_pressure_stops_the_group(tmp_path: Path):
    calls = {"count": 0}

    def pressure() -> MemoryPressure:
        calls["count"] += 1
        level = "normal" if calls["count"] < 2 else "warn"
        return MemoryPressure(level=level, raw=None, source="stub")  # type: ignore[arg-type]

    result = run_supervised(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        budget_bytes=512 * MIB,
        timeout_s=30.0,
        log_path=tmp_path / "pressure.log",
        pressure_probe=pressure,
        poll_interval_s=0.05,
    )
    assert result.status == "RESOURCE_LIMITED"
    assert "warn" in result.reason
    assert result.pressure_levels_seen == ("normal", "warn")


def test_timeout_terminates_the_whole_process_group_including_grandchildren(
    tmp_path: Path,
):
    pid_file = tmp_path / "grandchild.pid"
    script = (
        "import subprocess, sys, time;"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
        f"open({str(pid_file)!r}, 'w').write(str(child.pid));"
        "time.sleep(60)"
    )
    result = run_supervised(
        [sys.executable, "-c", script],
        budget_bytes=512 * MIB,
        timeout_s=1.0,
        log_path=tmp_path / "timeout.log",
        pressure_probe=_normal,
        poll_interval_s=0.1,
    )
    assert result.status == "INTERRUPTED"
    assert "wall-clock" in result.reason
    grandchild = int(pid_file.read_text())
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            os.kill(grandchild, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail("grandchild survived process-group cleanup")


def _wait_until_dead(pid: int, *, seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def _spawning_child(pid_file: Path, done_file: Path, *, sleep_s: float) -> str:
    """A child that starts a worker in its own process group, then exits."""

    worker = (
        f"import time; time.sleep({sleep_s}); "
        f"open({str(done_file)!r}, 'w').write('done')"
    )
    return (
        "import subprocess, sys;"
        f"worker = subprocess.Popen([sys.executable, '-c', {worker!r}]);"
        f"open({str(pid_file)!r}, 'w').write(str(worker.pid))"
    )


def test_workers_left_by_the_child_stay_supervised_until_they_exit(tmp_path: Path):
    pid_file, done_file = tmp_path / "worker.pid", tmp_path / "worker.done"
    result = run_supervised(
        [sys.executable, "-c", _spawning_child(pid_file, done_file, sleep_s=1.0)],
        budget_bytes=512 * MIB,
        timeout_s=20.0,
        pressure_probe=_normal,
        poll_interval_s=0.1,
    )
    # COMPLETED only once the whole group is gone, not when the child exits.
    assert result.status == "COMPLETED"
    assert done_file.read_text() == "done"
    assert "outlived it" in result.reason
    assert _wait_until_dead(int(pid_file.read_text()), seconds=0.5)


def test_workers_left_by_the_child_are_stopped_at_the_limits(tmp_path: Path):
    pid_file, done_file = tmp_path / "worker.pid", tmp_path / "worker.done"
    result = run_supervised(
        [sys.executable, "-c", _spawning_child(pid_file, done_file, sleep_s=60.0)],
        budget_bytes=512 * MIB,
        timeout_s=1.5,
        pressure_probe=_normal,
        poll_interval_s=0.1,
    )
    assert result.status == "INTERRUPTED"
    assert "left running in its group" in result.reason
    assert _wait_until_dead(int(pid_file.read_text()))
    assert not done_file.exists()


def test_a_failing_probe_stops_the_group_instead_of_orphaning_it(tmp_path: Path):
    pid_file = tmp_path / "child.pid"
    calls = {"rss": 0}

    def flaky_rss(pgid: int) -> int:
        calls["rss"] += 1
        if pid_file.exists():
            raise PermissionError("process listing refused")
        return 1

    script = (
        "import os, time;"
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid()));"
        "time.sleep(60)"
    )
    result = run_supervised(
        [sys.executable, "-c", script],
        budget_bytes=512 * MIB,
        timeout_s=20.0,
        rss_probe=flaky_rss,
        pressure_probe=_normal,
        poll_interval_s=0.1,
    )
    assert result.status == "INTERRUPTED"
    assert "PermissionError" in result.reason and "stopped" in result.reason
    assert _wait_until_dead(int(pid_file.read_text()))
    assert result.wall_s < 10.0


def test_group_rss_falls_back_to_ps_when_process_listing_is_refused(monkeypatch):
    import shwfs_ao.runtime.resource_guard as guard

    class _RefusingPsutil:
        @staticmethod
        def process_iter(attrs=None):
            raise PermissionError("process listing refused")

    monkeypatch.setattr(guard, "_psutil", lambda: _RefusingPsutil)
    rss = process_group_rss_bytes(os.getpgid(0))
    assert rss is not None and rss > 0  # this test's own group, measured by ps


def test_a_child_ignoring_sigterm_is_killed_after_the_grace_period(tmp_path: Path):
    script = (
        "import signal, time;"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN);"
        "print('ready', flush=True);"
        "time.sleep(60)"
    )
    started = time.monotonic()
    result = run_supervised(
        [sys.executable, "-c", script],
        budget_bytes=512 * MIB,
        timeout_s=0.5,
        log_path=tmp_path / "ignore.log",
        pressure_probe=_normal,
        poll_interval_s=0.1,
        cleanup_grace_s=0.5,
    )
    assert result.status == "INTERRUPTED"
    assert result.returncode == -signal.SIGKILL
    assert time.monotonic() - started < 10.0


def test_group_rss_aggregates_every_process_in_the_group(tmp_path: Path):
    import subprocess

    script = (
        "import subprocess, sys, time;"
        "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)']);"
        "print(c.pid, flush=True); time.sleep(20)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        assert process.stdout is not None
        grandchild = int(process.stdout.readline())
        time.sleep(0.2)
        total = process_group_rss_bytes(process.pid)
        assert total is not None
        import psutil

        parent_rss = psutil.Process(process.pid).memory_info().rss
        child_rss = psutil.Process(grandchild).memory_info().rss
        # Both processes are counted; RSS moves a little between reads.
        assert total >= 0.9 * (parent_rss + child_rss)
    finally:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


def test_argument_validation_refuses_unsafe_supervision_settings(tmp_path: Path):
    with pytest.raises(ResourcePolicyError):
        run_supervised([], budget_bytes=MIB, timeout_s=1.0)
    with pytest.raises(ResourcePolicyError):
        run_supervised([sys.executable, "-c", "0"], budget_bytes=MIB, timeout_s=1.0,
                       poll_interval_s=2.0)
    with pytest.raises(ResourcePolicyError):
        run_supervised([sys.executable, "-c", "0"], budget_bytes=MIB, timeout_s=1.0,
                       cleanup_grace_s=5.0)


def test_large_tests_are_refused_without_the_explicit_option(pytester: pytest.Pytester):
    pytester.makeconftest(
        (Path(__file__).resolve().parents[1] / "conftest.py").read_text()
    )
    pytester.makeini(
        "[pytest]\naddopts = --strict-markers\nmarkers =\n"
        "    elt_scale: large\n"
    )
    pytester.makepyfile(
        """
        import pytest

        @pytest.fixture
        def huge():
            raise AssertionError("fixture must not run without enablement")

        @pytest.mark.elt_scale
        def test_large(huge):
            raise AssertionError("must not run")
        """
    )
    for arguments in ((), ("-m", "elt_scale"), ("-m", "elt_scale or not elt_scale")):
        outcome = pytester.runpytest(*arguments)
        outcome.assert_outcomes(skipped=1)
    enabled = pytester.runpytest("--enable-elt-scale")
    enabled.assert_outcomes(errors=1)
