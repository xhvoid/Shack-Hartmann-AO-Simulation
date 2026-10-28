"""Desktop-safe memory preflight and process-group supervision.

The ESO SCAO development prompt (``docs/refactor/ESO_SCAO_DEVELOPMENT_PROMPT.md``
section 2.3) requires that scientific runs on the developer's desktop keep the
machine responsive.  This module implements that policy with the standard
library only, so a supervising parent never imports NumPy:

* :func:`host_snapshot` measures physical memory, currently available memory,
  and the operating system's *current* memory-pressure level.  Cumulative swap
  counters are deliberately not used as a pressure signal.
* :func:`desktop_budget_bytes` turns a snapshot into the aggregate RSS budget:
  the minimum of 2 GiB, 12.5 % of physical RAM, and 25 % of currently available
  RAM, or 1 GiB when availability cannot be measured reliably.
* :class:`ResourceEstimate` and :func:`preflight` reject a known over-budget job
  before anything is allocated.  An estimate states the baseline interpreter
  RSS, the simultaneously live components, and the largest single scratch
  buffer, and carries a 2x engineering margin.
* :func:`run_supervised` launches one child in a new process group with
  native-library thread limits in its environment, samples the aggregate RSS of
  the whole group and the memory-pressure level every ``poll_interval_s``, and on
  a budget, timeout, or pressure violation terminates only that group (SIGTERM,
  then SIGKILL after ``cleanup_grace_s``).

RSS monitoring is best effort; the primary protections are the upfront
estimate and the conservative defaults.  Neither the declared budget nor the
watchdog is an operating-system hard memory limit.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import time
from types import MappingProxyType
from typing import IO, Any, Literal


__all__ = (
    "GIB",
    "MIB",
    "THREAD_ENV_VARS",
    "DEFAULT_THREAD_LIMIT",
    "DEFAULT_SCRATCH_CEILING_BYTES",
    "DEFAULT_EXAMPLE_TIMEOUT_S",
    "DEFAULT_TEST_BATCH_TIMEOUT_S",
    "DEFAULT_POLL_INTERVAL_S",
    "DEFAULT_CLEANUP_GRACE_S",
    "UNRELIABLE_HOST_BUDGET_BYTES",
    "ResourcePolicyError",
    "ResourceBudgetExceeded",
    "MemoryPressure",
    "HostSnapshot",
    "ResourceEstimate",
    "PreflightDecision",
    "SupervisedResult",
    "read_physical_memory_bytes",
    "read_available_memory_bytes",
    "read_memory_pressure",
    "host_snapshot",
    "desktop_budget_bytes",
    "thread_limit_environment",
    "limited_environment",
    "preflight",
    "require_preflight",
    "process_group_rss_bytes",
    "run_supervised",
)


MIB = 1024**2
GIB = 1024**3
THREAD_ENV_VARS: tuple[str, ...] = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)
DEFAULT_THREAD_LIMIT = 2
DEFAULT_SCRATCH_CEILING_BYTES = 64 * MIB
DEFAULT_EXAMPLE_TIMEOUT_S = 120.0
DEFAULT_TEST_BATCH_TIMEOUT_S = 300.0
DEFAULT_POLL_INTERVAL_S = 0.5
DEFAULT_CLEANUP_GRACE_S = 2.0
DEFAULT_MARGIN = 2.0
UNRELIABLE_HOST_BUDGET_BYTES = 1 * GIB
_ABSOLUTE_CAP_BYTES = 2 * GIB
_PHYSICAL_FRACTION = 0.125
_AVAILABLE_FRACTION = 0.25

PressureLevel = Literal["normal", "warn", "critical", "unknown"]
SupervisedStatus = Literal[
    "COMPLETED",
    "FAILED",
    "RESOURCE_LIMITED",
    "INTERRUPTED",
    "REFUSED",
]


class ResourcePolicyError(RuntimeError):
    """Raised when the desktop-safe resource policy cannot be satisfied."""


class ResourceBudgetExceeded(ResourcePolicyError):
    """Raised by preflight when a job is known to exceed its budget."""


@dataclass(frozen=True)
class MemoryPressure:
    """The operating system's *current* memory-pressure classification."""

    level: PressureLevel
    raw: str | None
    source: str

    @property
    def reliable(self) -> bool:
        return self.level != "unknown"


@dataclass(frozen=True)
class HostSnapshot:
    """One measurement of the execution host's memory state."""

    platform: str
    machine: str
    cpu_count: int
    physical_bytes: int | None
    available_bytes: int | None
    available_source: str
    pressure: MemoryPressure
    timestamp_unix_s: float

    @property
    def reliable(self) -> bool:
        """Whether both availability and current pressure were measured."""

        return (
            self.physical_bytes is not None
            and self.available_bytes is not None
            and self.pressure.reliable
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "machine": self.machine,
            "cpu_count": self.cpu_count,
            "physical_bytes": self.physical_bytes,
            "available_bytes": self.available_bytes,
            "available_source": self.available_source,
            "pressure_level": self.pressure.level,
            "pressure_raw": self.pressure.raw,
            "pressure_source": self.pressure.source,
            "timestamp_unix_s": self.timestamp_unix_s,
            "reliable": self.reliable,
        }


def _run_text(argv: Sequence[str], *, timeout_s: float = 5.0) -> str | None:
    try:
        completed = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def _psutil() -> Any | None:
    try:
        import psutil  # type: ignore[import-untyped]
    except ImportError:
        return None
    return psutil


def read_physical_memory_bytes() -> int | None:
    """Return installed physical memory in bytes, or ``None`` if unknown."""

    if sys.platform == "darwin":
        text = _run_text(["sysctl", "-n", "hw.memsize"])
        if text is not None:
            try:
                return int(text.strip())
            except ValueError:
                pass
    meminfo = _linux_meminfo()
    if "MemTotal" in meminfo:
        return meminfo["MemTotal"]
    psutil = _psutil()
    if psutil is not None:
        try:
            return int(psutil.virtual_memory().total)
        except Exception:  # pragma: no cover - platform dependent
            return None
    return None


def _linux_meminfo() -> dict[str, int]:
    path = Path("/proc/meminfo")
    if not path.is_file():
        return {}
    values: dict[str, int] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            name, _, rest = line.partition(":")
            parts = rest.split()
            if len(parts) >= 1 and parts[0].isdigit():
                scale = 1024 if len(parts) > 1 and parts[1] == "kB" else 1
                values[name.strip()] = int(parts[0]) * scale
    except OSError:  # pragma: no cover - platform dependent
        return {}
    return values


def read_available_memory_bytes() -> tuple[int | None, str]:
    """Return currently available memory and the method that measured it.

    ``psutil.virtual_memory().available`` is preferred.  Without psutil, Linux
    uses ``MemAvailable`` and macOS uses ``vm_stat`` free + inactive +
    speculative pages, the same definition psutil applies on macOS.
    """

    psutil = _psutil()
    if psutil is not None:
        try:
            return int(psutil.virtual_memory().available), "psutil.virtual_memory"
        except Exception:  # pragma: no cover - platform dependent
            pass
    meminfo = _linux_meminfo()
    if "MemAvailable" in meminfo:
        return meminfo["MemAvailable"], "/proc/meminfo:MemAvailable"
    if sys.platform == "darwin":
        text = _run_text(["vm_stat"])
        if text is not None:
            parsed = _parse_vm_stat(text)
            if parsed is not None:
                return parsed, "vm_stat:free+inactive+speculative"
    return None, "unavailable"


def _parse_vm_stat(text: str) -> int | None:
    lines = text.splitlines()
    if not lines:
        return None
    page_size = None
    header = lines[0]
    if "page size of" in header:
        try:
            page_size = int(header.split("page size of")[1].split()[0])
        except (IndexError, ValueError):
            page_size = None
    if page_size is None:
        return None
    counts: dict[str, int] = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        value = value.strip().rstrip(".")
        if value.isdigit():
            counts[name.strip()] = int(value)
    try:
        pages = (
            counts["Pages free"]
            + counts["Pages inactive"]
            + counts.get("Pages speculative", 0)
        )
    except KeyError:
        return None
    return pages * page_size


def read_memory_pressure() -> MemoryPressure:
    """Return the current memory-pressure level.

    macOS reports ``kern.memorystatus_vm_pressure_level`` (1 normal, 2 warn,
    4 critical).  Linux exposes pressure-stall information; ten-second
    ``some``/``full`` stall averages of 10 % map to warn/critical.  Any other
    host reports ``unknown``, which the policy treats as unreliable monitoring.
    """

    if sys.platform == "darwin":
        text = _run_text(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"])
        if text is not None:
            raw = text.strip()
            mapping: dict[str, PressureLevel] = {
                "1": "normal",
                "2": "warn",
                "4": "critical",
            }
            level = mapping.get(raw, "unknown")
            return MemoryPressure(
                level=level,
                raw=raw,
                source="sysctl:kern.memorystatus_vm_pressure_level",
            )
    path = Path("/proc/pressure/memory")
    if path.is_file():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:  # pragma: no cover - platform dependent
            text = ""
        some = full = None
        for line in text.splitlines():
            parts = line.split()
            if not parts:
                continue
            fields = dict(item.split("=", 1) for item in parts[1:] if "=" in item)
            try:
                avg10 = float(fields.get("avg10", "nan"))
            except ValueError:
                avg10 = math.nan
            if parts[0] == "some":
                some = avg10
            elif parts[0] == "full":
                full = avg10
        if some is not None and math.isfinite(some):
            if full is not None and math.isfinite(full) and full >= 10.0:
                stall_level: PressureLevel = "critical"
            elif some >= 10.0:
                stall_level = "warn"
            else:
                stall_level = "normal"
            return MemoryPressure(
                level=stall_level,
                raw=text.strip(),
                source="/proc/pressure/memory:avg10",
            )
    return MemoryPressure(level="unknown", raw=None, source="unavailable")


def _available_cpu_count() -> int:
    # sched_getaffinity exists on Linux only.  Looking it up by name keeps the
    # module free of platform-specific type: ignore comments, which mypy's
    # warn_unused_ignores would flag on whichever platform does not need them.
    getaffinity = getattr(os, "sched_getaffinity", None)
    affinity: set[int] | None = None
    if getaffinity is not None:
        try:
            affinity = set(getaffinity(0))
        except OSError:
            affinity = None
    if affinity:
        return max(1, len(affinity))
    return max(1, os.cpu_count() or 1)


def host_snapshot() -> HostSnapshot:
    """Measure the host now; call again before every job."""

    available, source = read_available_memory_bytes()
    return HostSnapshot(
        platform=sys.platform,
        machine=platform.machine(),
        cpu_count=_available_cpu_count(),
        physical_bytes=read_physical_memory_bytes(),
        available_bytes=available,
        available_source=source,
        pressure=read_memory_pressure(),
        timestamp_unix_s=time.time(),
    )


def desktop_budget_bytes(snapshot: HostSnapshot) -> tuple[int, str]:
    """Return the aggregate RSS budget for one launched process group.

    The budget is ``min(2 GiB, 12.5 % physical, 25 % currently available)``.
    When availability or current pressure cannot be measured it is 1 GiB, and
    only tiny pre-audited jobs should run.
    """

    if not snapshot.reliable:
        return (
            UNRELIABLE_HOST_BUDGET_BYTES,
            "host memory or pressure could not be measured reliably; "
            "1 GiB cap for tiny pre-audited jobs only",
        )
    assert snapshot.physical_bytes is not None
    assert snapshot.available_bytes is not None
    candidates = {
        "absolute_cap_2GiB": _ABSOLUTE_CAP_BYTES,
        "physical_12.5pct": int(_PHYSICAL_FRACTION * snapshot.physical_bytes),
        "available_25pct": int(_AVAILABLE_FRACTION * snapshot.available_bytes),
    }
    name = min(candidates, key=lambda key: candidates[key])
    return candidates[name], f"min(2 GiB, 12.5% physical, 25% available) set by {name}"


def thread_limit_environment(
    threads: int = DEFAULT_THREAD_LIMIT,
    *,
    cpu_count: int | None = None,
) -> dict[str, str]:
    """Native-library thread variables, capped by the available CPU count."""

    if isinstance(threads, bool) or not isinstance(threads, int) or threads < 1:
        raise ResourcePolicyError("threads must be a positive integer.")
    available = _available_cpu_count() if cpu_count is None else int(cpu_count)
    value = str(max(1, min(threads, available)))
    return {name: value for name in THREAD_ENV_VARS}


def limited_environment(
    base: Mapping[str, str] | None = None,
    *,
    threads: int = DEFAULT_THREAD_LIMIT,
) -> dict[str, str]:
    """Return a child environment carrying the thread limits.

    Limits already present in ``base`` are lowered, never raised.
    """

    environment = dict(os.environ if base is None else base)
    limits = thread_limit_environment(threads)
    for name, value in limits.items():
        current = environment.get(name)
        if current is not None and current.isdigit() and 0 < int(current) < int(value):
            continue
        environment[name] = value
    environment.setdefault("PYTHONUNBUFFERED", "1")
    return environment


@dataclass(frozen=True)
class ResourceEstimate:
    """An audited upper estimate of one job's peak aggregate RSS.

    ``components`` lists the simultaneously live allocations (bytes) beyond the
    interpreter/native-library ``baseline_bytes``.  ``largest_buffer_bytes``
    is the largest single new numerical scratch buffer the job creates; the
    policy ceiling for it is 64 MiB unless chunking is impossible.
    ``required_bytes`` applies the engineering ``margin`` (2x by default).
    """

    label: str
    baseline_bytes: int
    components: Mapping[str, int]
    largest_buffer_bytes: int
    margin: float = DEFAULT_MARGIN
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.label, str) or not self.label.strip():
            raise ResourcePolicyError("estimate label must be a non-empty string.")
        for name, value in (
            ("baseline_bytes", self.baseline_bytes),
            ("largest_buffer_bytes", self.largest_buffer_bytes),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ResourcePolicyError(f"{name} must be a non-negative integer.")
        normalized: dict[str, int] = {}
        for key, value in dict(self.components).items():
            if not isinstance(key, str) or not key:
                raise ResourcePolicyError("component names must be non-empty strings.")
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ResourcePolicyError(
                    f"component {key!r} must be a non-negative integer byte count."
                )
            normalized[key] = value
        if not math.isfinite(self.margin) or self.margin < 1.0:
            raise ResourcePolicyError("margin must be finite and at least 1.")
        object.__setattr__(self, "components", MappingProxyType(normalized))
        object.__setattr__(self, "notes", tuple(str(note) for note in self.notes))

    @property
    def raw_bytes(self) -> int:
        return self.baseline_bytes + sum(self.components.values())

    @property
    def required_bytes(self) -> int:
        return int(math.ceil(self.raw_bytes * self.margin))

    def to_record(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "baseline_bytes": self.baseline_bytes,
            "components": dict(self.components),
            "largest_buffer_bytes": self.largest_buffer_bytes,
            "margin": self.margin,
            "raw_bytes": self.raw_bytes,
            "required_bytes": self.required_bytes,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class PreflightDecision:
    accepted: bool
    budget_bytes: int
    budget_rationale: str
    required_bytes: int
    reasons: tuple[str, ...]
    snapshot: HostSnapshot
    estimate: ResourceEstimate

    def to_record(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "budget_bytes": self.budget_bytes,
            "budget_rationale": self.budget_rationale,
            "required_bytes": self.required_bytes,
            "reasons": list(self.reasons),
            "snapshot": self.snapshot.to_record(),
            "estimate": self.estimate.to_record(),
        }


def preflight(
    estimate: ResourceEstimate,
    *,
    snapshot: HostSnapshot | None = None,
    budget_bytes: int | None = None,
    scratch_ceiling_bytes: int = DEFAULT_SCRATCH_CEILING_BYTES,
) -> PreflightDecision:
    """Decide, before allocating anything, whether a job may start.

    ``budget_bytes`` may only *lower* the policy budget; a caller cannot use it
    to raise the desktop limit.  A job is refused when its margin-inflated
    estimate exceeds the budget, when its largest single buffer exceeds the
    scratch ceiling, or when the host currently reports warn/critical memory
    pressure.
    """

    if not isinstance(estimate, ResourceEstimate):
        raise ResourcePolicyError("estimate must be a ResourceEstimate.")
    measured = host_snapshot() if snapshot is None else snapshot
    policy_budget, rationale = desktop_budget_bytes(measured)
    if budget_bytes is not None:
        if isinstance(budget_bytes, bool) or not isinstance(budget_bytes, int):
            raise ResourcePolicyError("budget_bytes must be an integer.")
        if budget_bytes < policy_budget:
            policy_budget = budget_bytes
            rationale = f"caller-lowered budget ({rationale})"
    reasons: list[str] = []
    if estimate.required_bytes > policy_budget:
        reasons.append(
            f"estimated peak {estimate.required_bytes / MIB:.1f} MiB (with "
            f"{estimate.margin:g}x margin) exceeds the {policy_budget / MIB:.1f} "
            "MiB desktop budget"
        )
    if estimate.largest_buffer_bytes > scratch_ceiling_bytes:
        reasons.append(
            f"largest single buffer {estimate.largest_buffer_bytes / MIB:.1f} MiB "
            f"exceeds the {scratch_ceiling_bytes / MIB:.0f} MiB scratch ceiling"
        )
    if measured.pressure.level in {"warn", "critical"}:
        reasons.append(
            f"host reports {measured.pressure.level} memory pressure now"
        )
    if not measured.reliable and estimate.required_bytes > UNRELIABLE_HOST_BUDGET_BYTES:
        reasons.append("host monitoring is unreliable; only tiny jobs may run")
    return PreflightDecision(
        accepted=not reasons,
        budget_bytes=policy_budget,
        budget_rationale=rationale,
        required_bytes=estimate.required_bytes,
        reasons=tuple(reasons),
        snapshot=measured,
        estimate=estimate,
    )


def require_preflight(
    estimate: ResourceEstimate,
    **kwargs: Any,
) -> PreflightDecision:
    """Run :func:`preflight` and raise :class:`ResourceBudgetExceeded` on refusal."""

    decision = preflight(estimate, **kwargs)
    if not decision.accepted:
        raise ResourceBudgetExceeded(
            f"{estimate.label}: refused before allocation: "
            + "; ".join(decision.reasons)
        )
    return decision


def process_group_rss_bytes(pgid: int) -> int | None:
    """Sum the resident set size of every live process in ``pgid``.

    Each process is counted once (shared pages are therefore over-counted,
    which is the conservative direction).  Returns ``None`` when no
    measurement method works.
    """

    psutil = _psutil()
    if psutil is not None:
        total = 0
        found = False
        for process in psutil.process_iter(["pid"]):
            try:
                if os.getpgid(process.pid) != pgid:
                    continue
                total += int(process.memory_info().rss)
                found = True
            except (ProcessLookupError, PermissionError, OSError):
                continue
            except Exception:  # psutil.NoSuchProcess / AccessDenied
                continue
        return total if found else 0
    text = _run_text(["ps", "-A", "-o", "pgid=,rss="])
    if text is None:
        return None
    total = 0
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
            continue
        if int(parts[0]) == pgid:
            total += int(parts[1]) * 1024
    return total


@dataclass(frozen=True)
class SupervisedResult:
    """Outcome of one supervised child process group."""

    status: SupervisedStatus
    returncode: int | None
    wall_s: float
    peak_rss_bytes: int | None
    rss_samples: int
    pressure_levels_seen: tuple[str, ...]
    reason: str
    command: tuple[str, ...]
    budget_bytes: int
    timeout_s: float
    log_path: str | None
    environment_thread_limits: Mapping[str, str] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "returncode": self.returncode,
            "wall_s": self.wall_s,
            "peak_rss_bytes": self.peak_rss_bytes,
            "rss_samples": self.rss_samples,
            "pressure_levels_seen": list(self.pressure_levels_seen),
            "reason": self.reason,
            "command": list(self.command),
            "budget_bytes": self.budget_bytes,
            "timeout_s": self.timeout_s,
            "log_path": self.log_path,
            "environment_thread_limits": dict(self.environment_thread_limits),
        }


def _terminate_group(
    process: subprocess.Popen[bytes],
    *,
    cleanup_grace_s: float,
) -> None:
    pgid = process.pid
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + cleanup_grace_s
    while time.monotonic() < deadline:
        if process.poll() is not None and not _group_alive(pgid):
            return
        time.sleep(0.05)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:  # pragma: no cover - kernel dependent
        pass


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # pragma: no cover - foreign group
        return True
    return True


def run_supervised(
    argv: Sequence[str],
    *,
    budget_bytes: int,
    timeout_s: float,
    env: Mapping[str, str] | None = None,
    cwd: str | os.PathLike[str] | None = None,
    threads: int = DEFAULT_THREAD_LIMIT,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    cleanup_grace_s: float = DEFAULT_CLEANUP_GRACE_S,
    log_path: str | os.PathLike[str] | None = None,
    rss_probe: Callable[[int], int | None] | None = None,
    pressure_probe: Callable[[], MemoryPressure] | None = None,
    stop_pressure_levels: frozenset[str] = frozenset({"warn", "critical"}),
) -> SupervisedResult:
    """Run one child in its own process group under the desktop policy.

    The child inherits native-library thread limits.  Every
    ``poll_interval_s`` (at most 0.5 s by policy) the supervisor sums the RSS
    of the whole group and reads the current memory pressure; a budget
    violation, a warn/critical pressure signal, or the wall-clock limit stops
    the group with SIGTERM, then SIGKILL after ``cleanup_grace_s`` (at most
    2 s).  Only the child's own process group is ever signalled.  Output is
    written to ``log_path`` so partial logs survive an interruption.
    """

    command = tuple(str(item) for item in argv)
    if not command:
        raise ResourcePolicyError("argv must not be empty.")
    if isinstance(budget_bytes, bool) or not isinstance(budget_bytes, int) or budget_bytes <= 0:
        raise ResourcePolicyError("budget_bytes must be a positive integer.")
    if not math.isfinite(timeout_s) or timeout_s <= 0.0:
        raise ResourcePolicyError("timeout_s must be positive and finite.")
    if not 0.0 < poll_interval_s <= DEFAULT_POLL_INTERVAL_S:
        raise ResourcePolicyError("poll_interval_s must be in (0, 0.5] seconds.")
    if not 0.0 <= cleanup_grace_s <= DEFAULT_CLEANUP_GRACE_S:
        raise ResourcePolicyError("cleanup_grace_s must be in [0, 2] seconds.")
    child_env = limited_environment(env, threads=threads)
    thread_record = {name: child_env[name] for name in THREAD_ENV_VARS}
    probe_rss = process_group_rss_bytes if rss_probe is None else rss_probe
    probe_pressure = read_memory_pressure if pressure_probe is None else pressure_probe

    log_handle: IO[bytes] | int
    if log_path is not None:
        log_file = Path(log_path)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_handle = open(log_file, "wb")  # noqa: SIM115 - closed below
    else:
        log_handle = subprocess.DEVNULL
    started = time.monotonic()
    peak: int | None = None
    samples = 0
    levels: list[str] = []
    status: SupervisedStatus
    reason = ""
    try:
        process = subprocess.Popen(
            list(command),
            env=child_env,
            cwd=None if cwd is None else str(cwd),
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            while True:
                returncode = process.poll()
                rss = probe_rss(process.pid)
                if rss is not None:
                    samples += 1
                    peak = rss if peak is None else max(peak, rss)
                pressure = probe_pressure()
                if not levels or levels[-1] != pressure.level:
                    levels.append(pressure.level)
                if returncode is not None:
                    status = "COMPLETED" if returncode == 0 else "FAILED"
                    reason = f"child exited with status {returncode}"
                    break
                elapsed = time.monotonic() - started
                if rss is not None and rss > budget_bytes:
                    status = "RESOURCE_LIMITED"
                    reason = (
                        f"aggregate RSS {rss / MIB:.1f} MiB exceeded the "
                        f"{budget_bytes / MIB:.1f} MiB budget"
                    )
                    _terminate_group(process, cleanup_grace_s=cleanup_grace_s)
                    break
                if pressure.level in stop_pressure_levels:
                    status = "RESOURCE_LIMITED"
                    reason = f"host reported {pressure.level} memory pressure"
                    _terminate_group(process, cleanup_grace_s=cleanup_grace_s)
                    break
                if elapsed > timeout_s:
                    status = "INTERRUPTED"
                    reason = f"wall-clock limit {timeout_s:g} s exceeded"
                    _terminate_group(process, cleanup_grace_s=cleanup_grace_s)
                    break
                time.sleep(poll_interval_s)
        except KeyboardInterrupt:
            status = "INTERRUPTED"
            reason = "supervisor interrupted"
            _terminate_group(process, cleanup_grace_s=cleanup_grace_s)
        returncode = process.returncode
    finally:
        if log_path is not None and not isinstance(log_handle, int):
            log_handle.close()
    return SupervisedResult(
        status=status,
        returncode=returncode,
        wall_s=time.monotonic() - started,
        peak_rss_bytes=peak,
        rss_samples=samples,
        pressure_levels_seen=tuple(levels),
        reason=reason,
        command=command,
        budget_bytes=budget_bytes,
        timeout_s=float(timeout_s),
        log_path=None if log_path is None else str(log_path),
        environment_thread_limits=MappingProxyType(thread_record),
    )


def _main(argv: Sequence[str] | None = None) -> int:
    """``python -m shwfs_ao.runtime.resource_guard`` command-line entry point."""

    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Run one command under the desktop-safe policy: preflight an audited "
            "peak-RSS estimate, then supervise the process group."
        ),
    )
    parser.add_argument("--label", required=True)
    parser.add_argument(
        "--estimate-mib",
        type=float,
        required=True,
        help="audited peak RSS estimate before the 2x margin, in MiB",
    )
    parser.add_argument("--largest-buffer-mib", type=float, default=0.0)
    parser.add_argument("--timeout-s", type=float, default=DEFAULT_TEST_BATCH_TIMEOUT_S)
    parser.add_argument("--threads", type=int, default=DEFAULT_THREAD_LIMIT)
    parser.add_argument("--log", required=True)
    parser.add_argument("--record", help="write the JSON result here as well")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args(argv)
    command = list(arguments.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("a command is required after --")
    estimate = ResourceEstimate(
        label=arguments.label,
        baseline_bytes=0,
        components={"audited_peak": int(arguments.estimate_mib * MIB)},
        largest_buffer_bytes=int(arguments.largest_buffer_mib * MIB),
    )
    decision = preflight(estimate)
    record: dict[str, Any] = {"preflight": decision.to_record()}
    if not decision.accepted:
        record["result"] = {"status": "REFUSED", "reason": "; ".join(decision.reasons)}
        print(json.dumps(record, indent=2, sort_keys=True))
        if arguments.record:
            Path(arguments.record).write_text(json.dumps(record, indent=2, sort_keys=True))
        return 3
    result = run_supervised(
        command,
        budget_bytes=decision.budget_bytes,
        timeout_s=arguments.timeout_s,
        threads=arguments.threads,
        log_path=arguments.log,
    )
    record["result"] = result.to_record()
    print(json.dumps(record, indent=2, sort_keys=True))
    if arguments.record:
        Path(arguments.record).write_text(json.dumps(record, indent=2, sort_keys=True))
    return 0 if result.status == "COMPLETED" else 1


if __name__ == "__main__":  # pragma: no cover - command-line entry
    raise SystemExit(_main())
