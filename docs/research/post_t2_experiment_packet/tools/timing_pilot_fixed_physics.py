#!/usr/bin/env python3
"""Single-setting timing pilot for the fixed-physics convergence study.

Proposed in the post-T2 experiment packet; unexecuted on any governed scale.
It runs exactly one planned setting of ``scripts/detector_level_convergence_study.py``
(the same ``SystemConfig``, atmosphere options, exposure override, execution
options, frames, burn-in, root seed and realization that the study's plan
gives that key) through the public experiment core
``shwfs_ao.experiments.convergence_study.fixed_physics_paired_run`` in the
calling process, and writes one JSON record with the wall time, this process's
own peak RSS, the timing split per arm, the twin disk record's size and the
planned protocol it mirrors.

It is a timing pilot: its record is not a study run, is never written into a
study's ``runs/`` directory, and makes no scientific claim.  Governed scales
need ``--enabled-by-user`` exactly as the driver does.  Launch it in a fresh
process under the resource guard (``pilot_requests.json``).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import platform
import resource
import sys
import time
from typing import Any

REPO = Path(__file__).resolve().parents[4]
DRIVER = REPO / "scripts" / "detector_level_convergence_study.py"
SCHEMA = "post_t2_timing_pilot.fixed_physics.v1"


def load_driver() -> Any:
    spec = importlib.util.spec_from_file_location("detector_level_convergence_study", DRIVER)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {DRIVER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            return value.item()
        except (TypeError, ValueError):
            return str(value)
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scale", choices=("ci", "medium", "full"), required=True)
    parser.add_argument("--key", required=True, help="a planned run key of that scale, e.g. medium_baseline_plain_r0")
    parser.add_argument("--output", type=Path, required=True, help="JSON record path; never overwritten")
    parser.add_argument("--scratch-dir", type=Path, required=True, help="caller-owned directory for the twin arm's disk record")
    parser.add_argument("--enabled-by-user", help="date and wording of the user's go-ahead (required for medium and full)")
    arguments = parser.parse_args(argv)

    driver = load_driver()
    spec = driver.SCALES[arguments.scale]
    if spec["governed"] and not arguments.enabled_by_user:
        raise SystemExit(f"{arguments.scale} is a governed scale: pass --enabled-by-user; nothing ran.")
    if arguments.output.exists():
        raise SystemExit(f"{arguments.output} exists; nothing ran and nothing is overwritten.")
    planned = driver.plan(arguments.scale)
    if arguments.key not in planned:
        raise SystemExit(f"{arguments.key} is not a planned run of scale {arguments.scale}; nothing ran.")
    run = planned[arguments.key]
    protocol = driver.planned_protocol(arguments.scale, run)

    from shwfs_ao.experiments.convergence_study import fixed_physics_paired_run
    from shwfs_ao.experiments.scao import ScaoExecutionOptions

    execution = ScaoExecutionOptions(telemetry_level=spec["telemetry_level"], atmosphere_band_storage=spec["band_storage"])
    started = time.perf_counter()
    result = fixed_physics_paired_run(
        run.config,
        root_seed=int(spec["root_seed"]),
        realization_index=run.realization,
        n_steps=int(spec["frames"]),
        burn_in_frames=int(spec["burn_in"]),
        execution=execution,
        atmosphere_options=run.atmosphere_options,
        exposure=run.exposure,
        arms=tuple(spec["arms"]),
        paired_delta_v=bool(spec["paired_delta_v"]),
        scratch_directory=arguments.scratch_dir,
    )
    wall_s = time.perf_counter() - started
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    paired = result.get("paired_delta_v", {})
    record = {
        "schema": SCHEMA,
        "purpose": "timing pilot of one planned setting; not a study run; no scientific claim",
        "scale": arguments.scale,
        "key": arguments.key,
        "enabled_by_user": arguments.enabled_by_user,
        "planned_protocol": _jsonable(protocol),
        "producer": _jsonable(driver.producer()),
        "host": {"platform": sys.platform, "machine": platform.machine(), "node": platform.node()},
        "wall_s": wall_s,
        "timing": _jsonable(result["timing"]),
        "ru_maxrss_bytes": int(peak if sys.platform == "darwin" else peak * 1024),
        "ru_maxrss_semantics": "this process's own lifetime peak resident set",
        "twin_record_bytes": paired.get("twin_record", {}).get("bytes"),
        "scalars": {
            arm: {name: entry[name] for name in ("post_update_rms_m", "open_loop_rms_m", "reconstruction_usable_fraction")}
            for arm, entry in result["arms"].items()
        },
        "science_production": {arm: _jsonable(entry["science"][0]["production"]) for arm, entry in result["arms"].items()},
        "paired_delta_v_mean_m2": paired.get("mean_m2"),
        "config_hash": result["config_hash"],
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with open(arguments.output, "x", encoding="utf-8") as handle:
        json.dump(record, handle, indent=1, default=float)
        handle.write("\n")
    print(json.dumps({name: record[name] for name in ("key", "wall_s", "ru_maxrss_bytes", "twin_record_bytes")}, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())
