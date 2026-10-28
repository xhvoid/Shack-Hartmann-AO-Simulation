"""Inert stand-ins for the fresh-process tests of the detector evidence runner (G4).

Nothing here builds a system, runs a loop, calls ``science_run`` or computes an AO quantity.
``mock_science_run`` is a labelled MOCK: ``science_run``'s signature and result shape with fixed numbers.
The allocations are plain bytes objects, written so their pages are resident, and released before return.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
from typing import Any


MIB = 2**20


def _peak_rss_bytes() -> int:
    """This process's peak RSS the way science_run reads it (ru_maxrss)."""

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == "darwin" else peak * 1024)


def _high_water_bytes() -> int:
    """This process image's peak RSS since exec (Linux VmHWM), so a parent's footprint at spawn is not in it."""

    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmHWM:"):
            return int(line.split()[1]) * 1024
    raise RuntimeError("no VmHWM in /proc/self/status")


def echo(value: Any) -> dict[str, Any]:
    return {"echo": value, "pid": os.getpid()}


def touch(path: str) -> dict[str, Any]:
    Path(path).write_text("ran\n")
    return {"touched": path}


def print_both_streams() -> dict[str, Any]:
    print("fresh-process worker: to stdout", flush=True)
    print("fresh-process worker: to stderr", file=sys.stderr, flush=True)
    return {"printed": True}


def raise_value_error(message: str) -> None:
    raise ValueError(message)


def raise_scao_construction_error(config: Any, **_: Any) -> None:
    from shwfs_ao.experiments.scao import ScaoConstructionError

    raise ScaoConstructionError(f"stand-in refusal for {config.config_hash[:12]}")


def exit_without_report(code: int) -> None:
    os._exit(int(code))  # skips every finally block, so the child cannot report


def allocate(mib: int) -> dict[str, Any]:
    """Hold ``mib`` MiB of written bytes, then release them."""

    block = b"\x01" * (int(mib) * MIB)
    held = len(block)
    del block
    return {"allocated_bytes": held, "high_water_bytes_after": _high_water_bytes()}


def reused_process_sequence(first_mib: int, second_mib: int) -> dict[str, Any]:
    """Two calls in one process: the lifetime peak read after the second still holds the first's allocation."""

    baseline = _high_water_bytes()
    first = allocate(first_mib)
    second = allocate(second_mib)
    return {"baseline": baseline, "after_first": first["high_water_bytes_after"], "after_second": second["high_water_bytes_after"]}


def sleep_with_grandchild(pid_file: str, seconds: float) -> dict[str, Any]:
    """Start a sleeping grandchild in this process group, record both PIDs, then sleep past any short timeout."""

    grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    Path(pid_file).write_text(json.dumps({"child": os.getpid(), "grandchild": grandchild.pid}))
    time.sleep(float(seconds))
    return {"slept_s": seconds}


def report_environment() -> dict[str, Any]:
    import shwfs_ao

    names = ("PYTHONPATH", "AO_RESOURCE_GUARD", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS")
    return {
        "environment": {name: os.environ.get(name) for name in names},
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "executable": sys.executable,
        "shwfs_ao_file": str(Path(shwfs_ao.__file__).resolve()),
    }


def mock_science_run(config: Any, *, root_seed: int | None = None, n_steps: int | None = None, burn_in_frames: int, execution: Any = None, realization_index: int = 0) -> dict[str, Any]:
    """MOCK science dispatch: science_run's signature and result shape, fixed numbers, no AO computation."""

    return {
        "mock": "inert stand-in for science_run: no system was built and no loop ran",
        "config_hash": config.config_hash,
        "root_seed": int(root_seed),
        "n_steps": int(n_steps),
        "burn_in_frames": int(burn_in_frames),
        "realization_index": int(realization_index),
        "telemetry_level": getattr(execution, "telemetry_level", None),
        "build_s": 0.0,
        "loop_s": 0.0,
        "per_frame_s": 0.0,
        "process_peak_rss_bytes": _peak_rss_bytes(),  # the legacy field, read the way science_run reads it
        "post_update_rms_m": 1.0e-7,
        "post_update_mean_square_m2": 1.0e-14,
        "open_loop_rms_m": 2.0e-7,
        "final_post_update_rms_m": 1.0e-7,
        "valid_measurement_fraction": 1.0,
        "min_valid_measurement_fraction": 1.0,
        "reconstruction_usable_fraction": 1.0,
        "lost_lock": False,
        "science": [{"wavelength_m": 2.2e-6, "peak_strehl": 0.5, "on_axis_strehl": 0.5, "fwhm_lambda_over_d": 1.0}],
    }
