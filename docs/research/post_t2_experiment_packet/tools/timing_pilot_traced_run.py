#!/usr/bin/env python3
"""One traced paired run of a detector-level configuration (timing pilot).

Proposed in the post-T2 experiment packet; unexecuted on any governed
configuration (validated at the ungoverned 2 m profile and the convergence
driver's ci geometry, review round 1).  It runs ``paired_noise_run_traced``
once at one guide-star magnitude and one root seed with the series' settings
(summary telemetry, block length 25, propagation weights on, residual maps
retained on request) and writes one JSON record with the wall time, this
process's own peak RSS, the seven recorded quantities and their comparison
with the matching run of a historical record (``--historical``), the per-arm
telemetry summaries (saturation, rejected reconstructions, recovery, mask
disagreement), the E0 operating-state summary and the uncompressed size of
the arrays a sidecar holds.  With ``--trace-sidecar PATH`` the trace arrays
are also written once, in the evidence runner's sidecar layout (its own
``_sidecar_arrays`` flattening) under the pilot schema
``post_t2_pilot_trace_sidecar.v1``, so that ``linear_loop_noise_model.py``
can read the realized residuals; the real series publishes its sidecars
through the evidence runner, never through this tool.

Defaults are the S4 A1 configuration (``det_emccd_12m_medium_derived@3``,
400 frames, burn-in 100); ``--profile det_emccd_2m_synthetic
--profile-version 1 --frames 200 --burn-in 50`` and ``--ci-geometry`` are the
ungoverned self-checks.  A 12 m or 42 m run is governed and needs
``--enabled-by-user``.  It is a timing pilot: its record is not a series run
and makes no scientific claim.  Launch it in a fresh process under
``authorized_supervise.py`` (12 m) or the guard CLI (ungoverned).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import platform
import sys
import time
from typing import Any

import numpy as np

# The shared helper lives beside this script; Python puts a script's own directory first on
# sys.path when the script is run by path, so no path manipulation is needed (lint rule).
from _packet_common import (
    add_configuration_arguments,
    configuration_from_arguments,
    jsonable,
    load_script_module,
    peak_rss_bytes,
    write_npz_once,
    write_record_once,
)

SCHEMA = "post_t2_timing_pilot.traced_run.v3"
PILOT_SIDECAR_SCHEMA = "post_t2_pilot_trace_sidecar.v1"
SEVEN_RECORDED = (
    ("noise_variance_m2",),
    ("noise_variance_standard_error_m2",),
    ("mean_square_difference_m2",),
    ("mean_square_difference_standard_error_m2",),
    ("arms", "noise_on", "post_update_rms_m"),
    ("arms", "operating_expectation", "post_update_rms_m"),
    ("predicted_centroid_variance_px2",),
)


def _nbytes(value: Any) -> int:
    if isinstance(value, np.ndarray):
        return int(value.nbytes)
    if isinstance(value, dict):
        return sum(_nbytes(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return sum(_nbytes(item) for item in value)
    return 0


def _lookup(record: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = record
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def _compare_with_historical(result: dict[str, Any], historical: Path, *, label: str, root_seed: int) -> dict[str, Any]:
    """The seven recorded quantities against the matching run of a historical record."""

    record = json.loads(historical.read_text())
    matches = [run for run in record.get("runs", []) if run.get("label") == label and run.get("root_seed") == root_seed]
    if len(matches) != 1:
        return {"available": False, "reason": f"{len(matches)} runs with label {label!r} and root seed {root_seed} in {historical.name}"}
    other = matches[0]
    fields = []
    for path in SEVEN_RECORDED:
        current, previous = _lookup(result, path), _lookup(other, path)
        if isinstance(current, (int, float)) and isinstance(previous, (int, float)) and not isinstance(current, bool):
            difference = None if previous == 0.0 else (float(current) - float(previous)) / abs(float(previous))
            fields.append({"quantity": "/".join(path), "current": float(current), "historical": float(previous), "relative_difference": difference, "bit_identical": float(current) == float(previous)})
        else:
            fields.append({"quantity": "/".join(path), "current": current, "historical": previous, "relative_difference": None, "bit_identical": current == previous})
    finite = [abs(f["relative_difference"]) for f in fields if f["relative_difference"] is not None and math.isfinite(f["relative_difference"])]
    return {
        "available": True,
        "historical_record": str(historical),
        "historical_code_identity": record.get("code_identity"),
        "historical_environment": {key: record.get(key) for key in ("python", "numpy", "scipy", "machine")},
        "historical_n_steps_burn_in": [other.get("n_steps"), other.get("burn_in_frames")],
        "config_hash_equal": other.get("config_hash") == result.get("config_hash"),
        "fields": fields,
        "max_abs_relative_difference": max(finite) if finite else None,
        "all_bit_identical": all(f["bit_identical"] for f in fields),
    }


def _arm_telemetry_summary(trace: dict[str, Any], core_summary: dict[str, Any], arm: str, burn_in: int) -> dict[str, Any]:
    """The experiment core's own per-arm trace summary, plus two per-frame counts it does not carry.

    Rejected frames and recovery actions are the core's numbers
    (``trace_summary.arms[arm].rejected_frames_after_burn_in`` and
    ``recovery_acted``, the fields the gate-quiet rule reads); this tool does
    not recount them.  The recount from the trace arrays is made only to
    refuse an internally inconsistent record (review round 2).
    """

    entry = trace["arms"][arm]
    core = core_summary["arms"][arm]
    saturation = np.asarray(entry["saturation_fraction"], dtype=float)[burn_in:]
    usable = np.asarray(entry["reconstruction_usable"], dtype=bool)[burn_in:]
    recount = int(np.count_nonzero(~usable))
    if recount != int(core["rejected_frames_after_burn_in"]):
        raise SystemExit(f"arm {arm}: the trace arrays count {recount} rejected frames after burn-in, the core's summary {core['rejected_frames_after_burn_in']}; the record is inconsistent and is not written.")
    return {
        "rejected_frames_after_burn_in": int(core["rejected_frames_after_burn_in"]),
        "recovery_acted": bool(core["recovery_acted"]),
        "recovery": jsonable(core.get("recovery")),
        "min_valid_measurement_fraction_after_burn_in": float(core["min_valid_measurement_fraction_after_burn_in"]),
        "max_saturation_fraction_after_burn_in": float(core["max_saturation_fraction_after_burn_in"]),
        "mean_saturation_fraction_after_burn_in": float(core["mean_saturation_fraction_after_burn_in"]),
        "frames_with_saturation_after_burn_in": int(np.count_nonzero(saturation > 0.0)),
        "telemetry_frames": int(core["telemetry_frames"]),
        "telemetry_unavailable": list(core["telemetry_unavailable"]),
        "history_config_hash": core.get("history_config_hash"),
        "source": "trace_summary.arms (experiment core) except frames_with_saturation_after_burn_in (this tool, from the trace arrays)",
    }


def _write_pilot_sidecar(path: Path, trace: dict[str, Any], result: dict[str, Any], *, label: str, arguments: Any, described: str) -> dict[str, Any]:
    evidence = load_script_module("run_detector_level_evidence")
    arrays, declared = evidence._sidecar_arrays(trace)
    weights = trace.get("propagation_weights")
    metadata = {
        "schema": PILOT_SIDECAR_SCHEMA,
        "purpose": "trace of a timing pilot; not a series sidecar; readable by linear_loop_noise_model.py --sigma sidecar",
        "layout": "scripts/run_detector_level_evidence.py _sidecar_arrays (the series' sidecar layout)",
        "configuration": described,
        "label": label,
        "root_seed": int(arguments.root_seed),
        "config_hash": result["config_hash"],
        "n_steps": int(arguments.frames),
        "burn_in_frames": int(arguments.burn_in),
        "trace_schema": trace["schema"],
        "arm_order": trace["arm_order"],
        "noisy_arm": trace["noisy_arm"],
        "twin_arm": trace["twin_arm"],
        "arms": {
            arm: {key: entry[key] for key in ("history_config_hash", "component_hashes", "random_stream_ids", "recovery", "wfs_exposure", "telemetry_unavailable", "telemetry_frames")}
            for arm, entry in trace["arms"].items()
        },
        "propagation_weights": None if weights is None else {key: value for key, value in weights.items() if key != "weights_m2_per_px2"},
        "residual_maps": None if trace.get("residual_maps") is None else {"precision": trace["residual_maps"]["precision"]},
        "arrays": declared,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    return write_npz_once(path, arrays, jsonable(metadata))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    add_configuration_arguments(parser)
    parser.add_argument("--root-seed", type=int, default=71)
    parser.add_argument("--frames", type=int, default=400)
    parser.add_argument("--burn-in", type=int, default=100)
    parser.add_argument("--retain-maps", action="store_true", help="retain both arms' residual maps, as the series does for one seed per magnitude")
    parser.add_argument("--historical", type=Path, help="an untraced record whose matching run (label m<magnitude>, same seed) the seven recorded quantities are compared with")
    parser.add_argument("--trace-sidecar", type=Path, help="also write the trace arrays once, in the series' sidecar layout under the pilot schema")
    parser.add_argument("--output", type=Path, required=True, help="JSON record path; never overwritten")
    parser.add_argument("--enabled-by-user", help="date and wording of the user's go-ahead (required for the 12 m and 42 m profiles)")
    arguments = parser.parse_args(argv)
    if arguments.magnitude is None and not arguments.ci_geometry:
        arguments.magnitude = 8.0
    if arguments.output.exists():
        raise SystemExit(f"{arguments.output} exists; nothing ran and nothing is overwritten.")
    if arguments.trace_sidecar is not None and arguments.trace_sidecar.exists():
        raise SystemExit(f"{arguments.trace_sidecar} exists; nothing ran and nothing is overwritten.")

    config, described, governed = configuration_from_arguments(arguments)
    if governed and not arguments.enabled_by_user:
        raise SystemExit(f"{described} is governed: pass --enabled-by-user; nothing ran.")

    from shwfs_ao.experiments.detector_level import paired_noise_run_traced
    from shwfs_ao.experiments.scao import ScaoExecutionOptions

    started = time.perf_counter()
    result = paired_noise_run_traced(
        config,
        root_seed=int(arguments.root_seed),
        n_steps=int(arguments.frames),
        burn_in_frames=int(arguments.burn_in),
        execution=ScaoExecutionOptions(telemetry_level="summary"),
        block_frames=25,
        retain_residual_maps=bool(arguments.retain_maps),
        propagation_weights=True,
    )
    wall_s = time.perf_counter() - started
    trace = result.pop("trace")
    magnitude = arguments.magnitude if arguments.magnitude is not None else float(config.detector_physics.source.ab_magnitude)
    label = f"m{magnitude:g}"
    seven = {"/".join(path): _lookup(result, path) for path in SEVEN_RECORDED}
    comparison = None if arguments.historical is None else _compare_with_historical(result, arguments.historical, label=label, root_seed=int(arguments.root_seed))
    sidecar = None
    if arguments.trace_sidecar is not None:
        sidecar = _write_pilot_sidecar(arguments.trace_sidecar, trace, result, label=label, arguments=arguments, described=described)
    disagreement = np.asarray(trace["mask_disagreement_rows"], dtype=float)
    rows = int(len(trace["row_ids"]))
    analysed = max(1, int(arguments.frames) - int(arguments.burn_in))
    record = {
        "schema": SCHEMA,
        "purpose": "timing pilot of one traced paired run; not a series run; no scientific claim",
        "configuration": described,
        "diagnostic_alpha_override": arguments.alpha,
        "label": label,
        "magnitude": magnitude,
        "root_seed": int(arguments.root_seed),
        "n_steps": int(arguments.frames),
        "burn_in_frames": int(arguments.burn_in),
        "retain_residual_maps": bool(arguments.retain_maps),
        "enabled_by_user": arguments.enabled_by_user,
        "host": {"platform": sys.platform, "machine": platform.machine(), "node": platform.node(), "python": sys.version, "numpy": np.__version__},
        "wall_s": wall_s,
        "ru_maxrss_bytes": peak_rss_bytes(),
        "ru_maxrss_semantics": "this process's own lifetime peak resident set (includes the in-memory sidecar archive when one was written)",
        "config_hash": result["config_hash"],
        "seven_recorded_quantities": jsonable(seven),
        "historical_comparison": jsonable(comparison),
        "arms": jsonable(result.get("arms")),
        "arm_telemetry": {arm: _arm_telemetry_summary(trace, result["trace_summary"], arm, int(arguments.burn_in)) for arm in trace["arm_order"]},
        "mask_disagreement": {
            "row_frames_fraction_after_burn_in": float(np.sum(disagreement[int(arguments.burn_in):]) / (rows * analysed)),
            "frames_with_disagreement_after_burn_in": int(np.count_nonzero(disagreement[int(arguments.burn_in):])),
        },
        "delta_v_series": {
            "mean_m2": float(np.mean(trace["delta_v_m2"])),
            "block25_standard_error_m2": None if len(trace["delta_v_m2"]) < 50 else float(np.std(np.asarray(trace["delta_v_m2"])[: len(trace["delta_v_m2"]) // 25 * 25].reshape(-1, 25).mean(axis=1), ddof=1) / np.sqrt(len(trace["delta_v_m2"]) // 25)),
            "mean_square_difference_mean_m2": float(np.mean(trace["mean_square_difference_m2"])),
            "cross_term_mean_m2": float(np.mean(trace["cross_term_m2"])),
            "analysed_frames": int(len(trace["delta_v_m2"])),
        },
        "operating_state": jsonable(result.get("operating_state")),
        "trace_summary": jsonable(result.get("trace_summary")),
        "trace_uncompressed_bytes": _nbytes(trace),
        "trace_schema": trace.get("schema"),
        "trace_sidecar": sidecar,
    }
    write_record_once(arguments.output, record)
    print(json.dumps({
        "configuration": described, "label": label, "root_seed": int(arguments.root_seed), "wall_s": wall_s, "ru_maxrss_bytes": record["ru_maxrss_bytes"],
        "trace_uncompressed_bytes": record["trace_uncompressed_bytes"], "sidecar_bytes": None if sidecar is None else sidecar["bytes"],
        "historical_max_abs_relative_difference": None if comparison is None or not comparison.get("available") else comparison["max_abs_relative_difference"],
        "delta_v_mean_nm2": record["delta_v_series"]["mean_m2"] * 1e18,
    }, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())
