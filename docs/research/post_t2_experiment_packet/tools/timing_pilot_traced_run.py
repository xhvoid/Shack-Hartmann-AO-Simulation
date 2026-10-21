#!/usr/bin/env python3
"""One traced paired run of the S4 A1 configuration (timing pilot).

Proposed in the post-T2 experiment packet; unexecuted on any governed
configuration.  It runs ``paired_noise_run_traced`` once on
``det_emccd_12m_medium_derived@3`` at one guide-star magnitude and one root
seed with the series' settings (400 frames, burn-in 100, summary telemetry,
block length 25, propagation weights on, residual maps retained on request)
and writes one JSON record with the wall time, this process's own peak RSS,
the recorded scalars, the E0 and trace summaries and the uncompressed size of
the arrays a sidecar would hold.  The trace arrays themselves are not written
(the real series publishes them through the evidence runner).

It is a timing pilot: its record is not a series run and makes no scientific
claim.  Launch it in a fresh process under ``authorized_supervise.py``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import resource
import sys
import time
from typing import Any

import numpy as np

SCHEMA = "post_t2_timing_pilot.traced_run.v1"


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    return value


def _nbytes(value: Any) -> int:
    if isinstance(value, np.ndarray):
        return int(value.nbytes)
    if isinstance(value, dict):
        return sum(_nbytes(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return sum(_nbytes(item) for item in value)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--magnitude", type=float, default=8.0)
    parser.add_argument("--root-seed", type=int, default=71)
    parser.add_argument("--frames", type=int, default=400)
    parser.add_argument("--burn-in", type=int, default=100)
    parser.add_argument("--retain-maps", action="store_true", help="retain both arms' residual maps, as the series does for one seed per magnitude")
    parser.add_argument("--output", type=Path, required=True, help="JSON record path; never overwritten")
    parser.add_argument("--enabled-by-user", required=True, help="date and wording of the user's go-ahead (a 12 m run is governed)")
    arguments = parser.parse_args(argv)
    if arguments.output.exists():
        raise SystemExit(f"{arguments.output} exists; nothing ran and nothing is overwritten.")

    from shwfs_ao.experiments.detector_level import paired_noise_run_traced, with_magnitude
    from shwfs_ao.experiments.scao import ScaoExecutionOptions
    from shwfs_ao.io.configs import load_system_profile

    config = with_magnitude(load_system_profile("det_emccd_12m_medium_derived", 3), arguments.magnitude)
    started = time.perf_counter()
    result = paired_noise_run_traced(
        config,
        root_seed=arguments.root_seed,
        n_steps=arguments.frames,
        burn_in_frames=arguments.burn_in,
        execution=ScaoExecutionOptions(telemetry_level="summary"),
        block_frames=25,
        retain_residual_maps=arguments.retain_maps,
        propagation_weights=True,
    )
    wall_s = time.perf_counter() - started
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    trace = result.pop("trace")
    scalars = {name: value for name, value in result.items() if isinstance(value, (int, float, str)) and not isinstance(value, bool)}
    record = {
        "schema": SCHEMA,
        "purpose": "timing pilot of one traced paired run; not a series run; no scientific claim",
        "profile": "det_emccd_12m_medium_derived@3",
        "magnitude": arguments.magnitude,
        "root_seed": arguments.root_seed,
        "n_steps": arguments.frames,
        "burn_in_frames": arguments.burn_in,
        "retain_residual_maps": bool(arguments.retain_maps),
        "enabled_by_user": arguments.enabled_by_user,
        "host": {"platform": sys.platform, "machine": platform.machine(), "node": platform.node(), "python": sys.version, "numpy": np.__version__},
        "wall_s": wall_s,
        "ru_maxrss_bytes": int(peak if sys.platform == "darwin" else peak * 1024),
        "ru_maxrss_semantics": "this process's own lifetime peak resident set",
        "scalars": _jsonable(scalars),
        "arms": _jsonable(result.get("arms")),
        "operating_state": _jsonable(result.get("operating_state")),
        "trace_summary": _jsonable(result.get("trace_summary")),
        "trace_uncompressed_bytes": _nbytes(trace),
        "trace_schema": trace.get("schema"),
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with open(arguments.output, "x", encoding="utf-8") as handle:
        json.dump(record, handle, indent=1, default=float)
        handle.write("\n")
    print(json.dumps({name: record[name] for name in ("magnitude", "root_seed", "wall_s", "ru_maxrss_bytes", "trace_uncompressed_bytes")}, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())
