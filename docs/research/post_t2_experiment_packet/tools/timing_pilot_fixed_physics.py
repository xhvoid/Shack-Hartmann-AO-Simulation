#!/usr/bin/env python3
"""Single-setting timing pilot for the fixed-physics convergence study.

Proposed in the post-T2 experiment packet; unexecuted on any governed scale
(validated at the ungoverned ci scale, review round 1).  It runs exactly one
planned setting of ``scripts/detector_level_convergence_study.py`` (the same
``SystemConfig``, atmosphere options, exposure override, execution options,
frames, burn-in, root seed and realization that the study's plan gives that
key) through the public experiment core
``shwfs_ao.experiments.convergence_study.fixed_physics_paired_run`` in the
calling process, builds the row a study child would publish for that key
(the driver's own ``_run_child`` composition plus ``run_protocol``),
validates that row with the driver's ``check_run`` against the planned
protocol, and writes one JSON record: the validated row (the complete
result: arms with their geometry, detector budget, atmosphere pairing record,
exposure metadata, open-loop digests, saturation and usable fractions,
science metrics with the Fourier reference, the paired DeltaV series), the
wall time, this process's own peak RSS and the planned protocol.  The
``acceptance_evidence`` block repeats the fields the pilot acceptance rules
of ``pilot_requests.json`` read.

It is a timing pilot: its record is not a study run, is never written into a
study's ``runs/`` directory, and makes no scientific claim.  Governed scales
need ``--enabled-by-user`` exactly as the driver does.  Launch it in a fresh
process under the resource guard (``pilot_requests.json``).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import sys
import time
from typing import Any

# The shared helper lives beside this script; Python puts a script's own directory first on
# sys.path when the script is run by path, so no path manipulation is needed (lint rule).
from _packet_common import jsonable, load_script_module, peak_rss_bytes, write_record_once

SCHEMA = "post_t2_timing_pilot.fixed_physics.v2"


def acceptance_evidence(result: dict[str, Any]) -> dict[str, Any]:
    arms = result["arms"]
    paired = result.get("paired_delta_v") or {}
    series = paired.get("delta_v_m2") if paired.get("status") == "available" else None
    return {
        "arms_in_order": list(arms),
        "analysed_frames": result.get("analysed_frames"),
        "atmosphere_options": result.get("atmosphere_options"),
        "exposure_override": result.get("exposure_override"),
        "exposure_keywords": result.get("exposure_keywords"),
        "science_wavelengths_m": result.get("science_wavelengths_m"),
        "open_loop_rms_series_shared_by_arms": result.get("open_loop_rms_series_shared_by_arms"),
        "open_loop_rms_series_sha256": {arm: entry.get("open_loop_rms_series_sha256") for arm, entry in arms.items()},
        "atmosphere": {arm: entry.get("atmosphere") for arm, entry in arms.items()},
        "wfs_exposure": {arm: entry.get("wfs_exposure") for arm, entry in arms.items()},
        "geometry": {arm: entry.get("geometry") for arm, entry in arms.items()},
        "detector_budget": {arm: entry.get("detector_budget") for arm, entry in arms.items()},
        "saturation_fraction": {arm: entry.get("saturation_fraction") for arm, entry in arms.items()},
        "reconstruction_usable_fraction": {arm: entry.get("reconstruction_usable_fraction") for arm, entry in arms.items()},
        "valid_measurement_fraction": {arm: entry.get("valid_measurement_fraction") for arm, entry in arms.items()},
        "rejected_frames_after_burn_in": {arm: entry.get("rejected_frames_after_burn_in") for arm, entry in arms.items()},
        "recovery": {arm: entry.get("recovery") for arm, entry in arms.items()},
        "lost_lock": {arm: entry.get("lost_lock") for arm, entry in arms.items()},
        "post_update_rms_m": {arm: entry.get("post_update_rms_m") for arm, entry in arms.items()},
        "science_production": {arm: entry["science"][0].get("production") for arm, entry in arms.items()},
        "fourier_reference_status": {arm: entry["science"][0].get("fourier_reference", {}).get("status") for arm, entry in arms.items()},
        "paired_delta_v": {
            "status": paired.get("status"),
            "series_length": paired.get("series_length"),
            "finite_values": None if series is None else int(sum(1 for value in series if value == value)),
            "mean_m2": paired.get("mean_m2"),
            "block_standard_error_m2": paired.get("block_standard_error_m2"),
            "mean_square_difference_m2": paired.get("mean_square_difference_m2"),
            "cross_term_mean_m2": paired.get("cross_term_mean_m2"),
            "twin_record": paired.get("twin_record"),
        },
        "execution": result.get("execution"),
        "timing": result.get("timing"),
        "process_peak_rss_bytes_lifetime": result.get("process_peak_rss_bytes_lifetime"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scale", choices=("ci", "medium", "full"), required=True)
    parser.add_argument("--key", required=True, help="a planned run key of that scale, e.g. medium_baseline_plain_r0")
    parser.add_argument("--output", type=Path, required=True, help="JSON record path; never overwritten")
    parser.add_argument("--scratch-dir", type=Path, required=True, help="caller-owned directory for the twin arm's disk record")
    parser.add_argument("--enabled-by-user", help="date and wording of the user's go-ahead (required for medium and full)")
    arguments = parser.parse_args(argv)

    driver = load_script_module("detector_level_convergence_study")
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
    made_by = driver.producer()

    from shwfs_ao.experiments.convergence_study import fixed_physics_paired_run

    started = time.perf_counter()
    result = fixed_physics_paired_run(
        run.config,
        root_seed=int(spec["root_seed"]),
        realization_index=run.realization,
        n_steps=int(spec["frames"]),
        burn_in_frames=int(spec["burn_in"]),
        execution=driver._execution(arguments.scale),
        atmosphere_options=run.atmosphere_options,
        exposure=run.exposure,
        arms=tuple(spec["arms"]),
        paired_delta_v=bool(spec["paired_delta_v"]),
        scratch_directory=arguments.scratch_dir,
    )
    wall_s = time.perf_counter() - started
    peak_bytes = peak_rss_bytes()

    # The row a study child would publish for this key (``_run_child`` plus the
    # parent's ``run_protocol``), validated with the driver's own check.
    row: dict[str, Any] = {name: protocol[name] for name in driver.REPEATED_FIELDS}
    row.update(status="completed", result=result)
    row["ru_maxrss_bytes"] = peak_bytes
    row["ru_maxrss_semantics"] = "this process's own lifetime peak resident set (timing pilot process, not a study child)"
    row.update(driver.run_protocol(arguments.scale, run, made_by))
    row = json.loads(json.dumps(row, default=float))
    problem = driver.check_run(Path(f"<timing pilot {arguments.key}>"), row, protocol)

    record = {
        "schema": SCHEMA,
        "purpose": "timing pilot of one planned setting; not a study run; no scientific claim",
        "scale": arguments.scale,
        "key": arguments.key,
        "enabled_by_user": arguments.enabled_by_user,
        "host": {"platform": sys.platform, "machine": platform.machine(), "node": platform.node(), "python": sys.version},
        "wall_s": wall_s,
        "ru_maxrss_bytes": peak_bytes,
        "ru_maxrss_semantics": "this process's own lifetime peak resident set",
        "plan_validation": {
            "checker": "scripts/detector_level_convergence_study.py check_run(row, planned_protocol)",
            "passed": problem is None,
            "problem": problem,
        },
        "acceptance_evidence": jsonable(acceptance_evidence(row["result"])),
        "planned_protocol": jsonable(protocol),
        "producer": jsonable(made_by),
        "study_row": row,
    }
    write_record_once(arguments.output, record)
    print(json.dumps({"key": arguments.key, "wall_s": wall_s, "ru_maxrss_bytes": peak_bytes, "plan_validation_passed": problem is None, "problem": problem}, default=float))
    return 0 if problem is None else 2


if __name__ == "__main__":
    sys.exit(main())
