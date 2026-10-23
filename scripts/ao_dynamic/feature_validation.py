"""Bounded feature validation of the dynamic mode: plan, ledger, pilot, five runs, evaluation.

Usage::

    python scripts/ao_dynamic/feature_validation.py plan     --dir outputs/ao_dynamic_validation/fv1
    python scripts/ao_dynamic/feature_validation.py pilot    --dir ...
    python scripts/ao_dynamic/feature_validation.py run ROLE --dir ...
    python scripts/ao_dynamic/feature_validation.py record   --dir ... --label L --wall-s S --note N
    python scripts/ao_dynamic/feature_validation.py evaluate --dir ... --out docs/research/ao_dynamic_v1/evidence
    python scripts/ao_dynamic/feature_validation.py status   --dir ...

The plan is written once (never overwritten) before the pilot: one 64-frame
pilot with burn-in 16 and five 180-frame runs with burn-in 40 (baseline with
seed 1, same-seed replay with display stride 3, a different seed, one
same-atmosphere AO-parameter comparison, and the observer-disabled passivity
control), the ceilings (20 min numerical/processing wall time, 512 MiB raw
evidence), two native threads, the child timeout and the tolerances.

Every launch -- successful, refused or failed -- appends one ledger entry with
its measured wall time.  Fixture test sessions and browser end-to-end
sessions that compute small runs are recorded with ``record``.  A run whose
role already has a completed attempt is reused, never rerun.  The pilot's
measured cost is projected onto the five runs before any of them may start; if
the projection does not fit the remaining ceilings, dependent work refuses.
This plan and ledger are separate from the frozen explorer series and its
accounting, which stay read-only.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
EXPLORER = HERE.parent / "ao_explorer"
for _path in (str(HERE), str(EXPLORER)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import contract  # noqa: E402

PLAN_SCHEMA = "ao-dynamic.feature-validation-plan.v1"
PLAN_NAME = "plan.json"
LEDGER_NAME = "ledger.jsonl"
WALL_CEILING_S = 20.0 * 60.0
RAW_CEILING_BYTES = 512 * 1024 * 1024
CHILD_TIMEOUT_S = 180.0
NATIVE_THREADS = 2
REPO = HERE.parents[1]


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(value, indent=1, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


class ValidationRefusal(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Plan


def planned_runs(different_seed: int) -> List[Dict[str, Any]]:
    base = contract.default_parameters()
    return [
        {"role": "pilot", "observer": True, "parameters": dict(base, n_frames=64, burn_in=16, display_stride=1),
         "purpose": "measure the per-frame cost and peak memory before any 180-frame run"},
        {"role": "baseline", "observer": True, "parameters": dict(base),
         "purpose": "default configuration with seed 1 (equals the frozen explorer's baseline configuration hash)"},
        {"role": "replay", "observer": True, "parameters": dict(base, display_stride=3),
         "purpose": "same seed and physical configuration: exact replay; display stride 3 checks that preview throttling leaves histories and averages unchanged"},
        {"role": "different-seed", "observer": True, "parameters": dict(base, seed=different_seed),
         "purpose": "a different realization: atmosphere and results must differ"},
        {"role": "same-atmosphere", "observer": True, "parameters": dict(base, guide_ab_magnitude=8.5),
         "purpose": "AO/WFS change (guide magnitude) against the same atmosphere: paired only if every atmosphere digest matches; calibration rebuilt"},
        {"role": "control", "observer": False, "parameters": dict(base),
         "purpose": "observer-disabled passivity control of the baseline: identical loop history required"},
    ]


def draft_plan(directory: Path) -> Dict[str, Any]:
    import identity
    import physics
    import worker

    path = directory / PLAN_NAME
    if path.exists():
        raise ValidationRefusal(f"{path} exists; the plan is never overwritten")
    different_seed = 2 + secrets.randbelow(2_147_483_647 - 2)
    runs = planned_runs(different_seed)
    for run in runs:
        reasons = contract.validate_parameters(run["parameters"])
        if reasons:
            raise ValidationRefusal(f"{run['role']}: {reasons}")
        config = physics.effective_config(run["parameters"])
        admission = physics.admit(config)
        run["system_config_hash"] = config.config_hash
        run["admission"] = {key: admission[key] for key in ("outcome", "max_travel_px", "travel_budget_px", "margin_px", "request_count")}
        if not admission["admitted"]:
            raise ValidationRefusal(f"{run['role']} is not admitted: {admission['reasons']}")
    plan = {
        "schema": PLAN_SCHEMA,
        "created_utc": utc_now(),
        "api": contract.API_VERSION,
        "scope": "bounded validation of the generated-experiment feature; separate from the frozen explorer series and its ledger",
        "runs": runs,
        "different_seed_source": "drawn once with secrets.randbelow when this plan was written",
        "fixtures": "small deterministic fixtures (6-48 frames) for boundaries, lifecycle and browser behaviour; their sessions are recorded in the ledger",
        "ceilings": {
            "numerical_processing_wall_s": WALL_CEILING_S,
            "raw_evidence_bytes": RAW_CEILING_BYTES,
            "child_timeout_s": CHILD_TIMEOUT_S,
            "native_threads": NATIVE_THREADS,
            "accounting": "every launch (successful, refused or failed) and every recorded fixture/browser session adds its measured wall time; every byte under this directory counts as raw evidence",
            "upper_bounds_only": "ceilings are limits, not predicted costs",
        },
        "tolerances": {
            "rms_rtol": 1e-12, "rms_atol_m": 1e-18, "strehl_atol": 1e-12, "psf_direct_dft_atol": 1e-15,
            "convolution_atol": 1e-15, "flux_atol": 1e-12, "mean_psf_atol": 1e-15,
            "replay": "byte-identical histories, digests, frames and averages",
            "frozen_explorer_baseline": "per-frame RMS and Strehl of the seed-1 baseline against the published dataset: reported, with the differing numerical environment stated",
        },
        "resource_policy": {"AO_RESOURCE_GUARD": os.environ.get("AO_RESOURCE_GUARD", "unset (memory enforcement off by default)")},
        "identities": {"producer": worker.dynamic_identity(), "git": identity.git_state("scripts/ao_dynamic"),
                       "core": identity.core_identity(), "environment": identity.environment_identity()},
    }
    write_json(path, plan)
    return plan


def load_plan(directory: Path) -> Dict[str, Any]:
    path = directory / PLAN_NAME
    if not path.exists():
        raise ValidationRefusal(f"missing plan {path}")
    return read_json(path)


# ---------------------------------------------------------------------------
# Ledger


def ledger(directory: Path) -> List[Dict[str, Any]]:
    path = directory / LEDGER_NAME
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append(directory: Path, entry: Dict[str, Any]) -> None:
    with (directory / LEDGER_NAME).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True, allow_nan=False) + "\n")


def consumption(directory: Path) -> Dict[str, Any]:
    entries = ledger(directory)
    raw = sum(path.stat().st_size for path in directory.rglob("*") if path.is_file())
    return {
        "wall_s": sum(float(entry.get("wall_s") or 0.0) for entry in entries),
        "raw_bytes": raw,
        "launches": sum(1 for entry in entries if entry.get("launched")),
        "entries": len(entries),
    }


def completed(directory: Path, role: str) -> Optional[Path]:
    root = directory / "runs" / role
    if not root.exists():
        return None
    for attempt in sorted(root.iterdir()):
        if (attempt / "status.json").exists() and read_json(attempt / "status.json").get("status") == "COMPLETED":
            return attempt
    return None


# ---------------------------------------------------------------------------
# Launch


def launch(directory: Path, role: str, *, projected_wall_s: float, projected_bytes: int) -> Dict[str, Any]:
    from shwfs_ao.runtime import resource_guard

    plan = load_plan(directory)
    spec = next((run for run in plan["runs"] if run["role"] == role), None)
    if spec is None:
        raise ValidationRefusal(f"{role} is not a planned run")
    existing = completed(directory, role)
    if existing is not None:
        raise ValidationRefusal(f"{role} already completed in {existing.relative_to(directory)}; matching-identity runs are reused, not rerun")
    if role != "pilot" and completed(directory, "pilot") is None:
        raise ValidationRefusal("the pilot must complete before any 180-frame run")
    used = consumption(directory)
    entry: Dict[str, Any] = {"utc": utc_now(), "label": role, "kind": "planned_run", "launched": False, "wall_s": 0.0,
                             "consumption_before": used, "projected_wall_s": projected_wall_s, "projected_bytes": projected_bytes}
    if used["wall_s"] + projected_wall_s > WALL_CEILING_S or used["raw_bytes"] + projected_bytes > RAW_CEILING_BYTES:
        entry.update(status="REFUSED_CEILING", reason="the projected cost would exceed a ceiling")
        append(directory, entry)
        raise ValidationRefusal(entry["reason"])
    root = directory / "runs" / role
    root.mkdir(parents=True, exist_ok=True)
    attempt = root / f"attempt-{1 + sum(1 for path in root.iterdir() if path.is_dir()):02d}"
    attempt.mkdir()
    run_id = f"fv-{role}-{attempt.name}"
    (attempt / "request.json").write_text(json.dumps({"run_id": run_id, "created_utc": utc_now(), "seed_source": "validation_plan",
                                                      "parameters": contract.effective_parameters(spec["parameters"])}, indent=1) + "\n")
    environment = resource_guard.limited_environment(threads=NATIVE_THREADS)
    argv = [sys.executable, str(HERE / "worker.py"), "--job-dir", str(attempt)] + ([] if spec["observer"] else ["--no-observer"])
    started = time.monotonic()
    with open(attempt / "worker.log", "wb") as log, open(attempt / "events.jsonl", "wb") as events:
        process = subprocess.Popen(argv, env=environment, cwd=str(REPO), stdout=events, stderr=log, start_new_session=True)
        try:
            returncode = process.wait(timeout=CHILD_TIMEOUT_S)
            status = "COMPLETED" if returncode == 0 else "FAILED"
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, 9)
            process.wait()
            returncode = process.returncode
            status = "TIMEOUT"
    wall = time.monotonic() - started
    lines = [json.loads(line) for line in (attempt / "events.jsonl").read_text().splitlines() if line.strip()]
    final = lines[-1] if lines else {}
    if status == "COMPLETED" and final.get("event") != "completed":
        status = "FAILED"
    write_json(attempt / "status.json", {"status": status, "utc": utc_now(), "returncode": returncode, "final_event": final})
    entry.update(launched=True, status=status, wall_s=wall, attempt=attempt.relative_to(directory).as_posix(),
                 threads={name: environment[name] for name in resource_guard.THREAD_ENV_VARS},
                 memory_enforcement_enabled=resource_guard.resource_guard_enabled(), final_event=final,
                 consumption_after=consumption(directory))
    append(directory, entry)
    if status != "COMPLETED":
        raise ValidationRefusal(f"{role} {status}: {final.get('reason')}")
    return entry


def pilot(directory: Path) -> Dict[str, Any]:
    entry = launch(directory, "pilot", projected_wall_s=60.0, projected_bytes=32 * 1024 * 1024)
    record = read_json(directory / entry["attempt"] / "run.json")
    per_frame_s = record["resources"]["loop_s"] / record["effective"]["parameters"]["n_frames"]
    fixed_s = entry["wall_s"] - record["resources"]["loop_s"]
    projection = {
        "per_frame_loop_s": per_frame_s,
        "fixed_overhead_s": fixed_s,
        "projected_180_frame_run_s": fixed_s + 180 * per_frame_s,
        "projected_five_runs_s": 5 * (fixed_s + 180 * per_frame_s),
        "frames_bin_bytes_per_transported_frame": record["arrays"]["frames"]["bytes"] / len(record["transported"]["indices"]),
        "child_peak_rss_bytes": record["resources"]["child_peak_rss_bytes"],
    }
    projection["projected_five_runs_bytes"] = int(2 * 180 * projection["frames_bin_bytes_per_transported_frame"] * 1.1
                                                   + 60 * projection["frames_bin_bytes_per_transported_frame"] * 1.1 + 5 * 2 * 1024 * 1024)
    used = consumption(directory)
    projection["fits"] = (used["wall_s"] + projection["projected_five_runs_s"] <= WALL_CEILING_S
                          and used["raw_bytes"] + projection["projected_five_runs_bytes"] <= RAW_CEILING_BYTES)
    write_json(directory / "pilot_projection.json", projection)
    return projection


def run_role(directory: Path, role: str) -> Dict[str, Any]:
    projection_path = directory / "pilot_projection.json"
    if not projection_path.exists():
        raise ValidationRefusal("no pilot projection; run the pilot first")
    projection = read_json(projection_path)
    if not projection["fits"]:
        raise ValidationRefusal("the pilot projection does not fit the ceilings; dependent numerical work stops")
    per_run_bytes = int(180 * projection["frames_bin_bytes_per_transported_frame"] * 1.1 + 2 * 1024 * 1024)
    return launch(directory, role, projected_wall_s=1.5 * projection["projected_180_frame_run_s"], projected_bytes=per_run_bytes)


def record(directory: Path, label: str, wall_s: float, note: str, kind: str = "fixture_session") -> Dict[str, Any]:
    entry = {"utc": utc_now(), "label": label, "kind": kind, "launched": True, "status": "RECORDED", "wall_s": float(wall_s),
             "note": note, "consumption_before": consumption(directory)}
    append(directory, entry)
    return entry


# ---------------------------------------------------------------------------
# Evaluation


def _load(directory: Path, role: str) -> Dict[str, Any]:
    import numpy as np

    attempt = completed(directory, role)
    if attempt is None:
        raise ValidationRefusal(f"{role} has no completed attempt")
    if role == "control":
        return {"attempt": attempt, "control": read_json(attempt / "control.json")}
    run = read_json(attempt / "run.json")
    frames = np.fromfile(attempt / "frames.bin", dtype="<f4")
    final = np.fromfile(attempt / "final.bin", dtype="<f4")
    return {"attempt": attempt, "run": run, "frames": frames, "final": final, "evidence": dict(np.load(attempt / "evidence.npz"))}


def _frame_blocks(item: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    run = item["run"]
    per = sum(shape[0] * shape[1] for _name, shape, _unit in contract.FRAME_BLOCKS)
    out: Dict[int, Dict[str, Any]] = {}
    for position, index in enumerate(run["transported"]["indices"]):
        chunk = item["frames"][position * per:(position + 1) * per]
        offset = 0
        blocks = {}
        for name, shape, _unit in contract.FRAME_BLOCKS:
            size = shape[0] * shape[1]
            blocks[name] = chunk[offset:offset + size].reshape(shape)
            offset += size
        out[index] = blocks
    return out


def evaluate(directory: Path, out: Path) -> Dict[str, Any]:
    import numpy as np

    plan = load_plan(directory)
    items = {run["role"]: _load(directory, run["role"]) for run in plan["runs"]}
    for role, item in items.items():
        if "run" in item:
            problems = contract.validate_run_record(item["run"], expected_parameters=contract.effective_parameters(
                next(r for r in plan["runs"] if r["role"] == role)["parameters"]))
            if problems:
                raise ValidationRefusal(f"{role}: {problems}")
    base, replay, other, paired = (items[r]["run"] for r in ("baseline", "replay", "different-seed", "same-atmosphere"))
    result: Dict[str, Any] = {"schema": "ao-dynamic.feature-validation-evaluation.v1", "created_utc": utc_now()}

    # Same-seed replay (stride 3): every scalar history, digest and average equal; frames equal where both kept.
    base_frames, replay_frames = _frame_blocks(items["baseline"]), _frame_blocks(items["replay"])
    common = sorted(set(base_frames) & set(replay_frames))
    frame_equal = all(np.array_equal(base_frames[k][name], replay_frames[k][name], equal_nan=True)
                      for k in common for name, _s, _u in contract.FRAME_BLOCKS)
    result["replay"] = {
        "history_digest_equal": base["identities"]["history_digest"] == replay["identities"]["history_digest"],
        "per_frame_equal": all(base["per_frame"][key] == replay["per_frame"][key] for key in base["per_frame"]),
        "summary_equal": base["summary"] == replay["summary"],
        "final_bin_equal": bool(np.array_equal(items["baseline"]["final"], items["replay"]["final"])),
        "evidence_mean_psfs_equal": all(np.array_equal(items["baseline"]["evidence"][k], items["replay"]["evidence"][k])
                                        for k in ("mean_psf_uncorrected", "mean_psf_corrected", "final_observation_uncorrected", "final_observation_corrected")),
        "transported_frames": {"baseline": len(base_frames), "replay": len(replay_frames), "common": len(common)},
        "common_frames_byte_identical_including_running_averages": frame_equal,
        "running_sample_counts_at_common_frames_equal": all(
            base["transported"]["running_sample_count"][base["transported"]["indices"].index(k)]
            == replay["transported"]["running_sample_count"][replay["transported"]["indices"].index(k)] for k in common),
        "calibration_identity_equal": base["identities"]["calibration"] == replay["identities"]["calibration"],
    }
    # Different seed.
    digests_b, digests_o = base["per_frame"]["atmosphere_sha256"], other["per_frame"]["atmosphere_sha256"]
    atm_b = np.asarray(base_frames[0]["atmosphere_opd_m"], dtype=float)
    atm_o = np.asarray(_frame_blocks(items["different-seed"])[0]["atmosphere_opd_m"], dtype=float)
    mask = np.isfinite(atm_b)
    result["different_seed"] = {
        "seed": other["effective"]["parameters"]["seed"],
        "atmosphere_samples_differing": sum(1 for a, b in zip(digests_b, digests_o) if a != b),
        "frames": len(digests_b),
        "frame0_correlation_with_baseline": float(np.corrcoef(atm_b[mask], atm_o[mask])[0, 1]),
        "mean_residual_rms_nm": [base["summary"]["mean_residual_rms_m"] * 1e9, other["summary"]["mean_residual_rms_m"] * 1e9],
        "averaged_intensity_strehl_ao": [base["summary"]["averaged_intensity_peak_strehl_corrected"], other["summary"]["averaged_intensity_peak_strehl_corrected"]],
        "calibration_identity_differs": base["identities"]["calibration"]["interaction_matrix_hash"] != other["identities"]["calibration"]["interaction_matrix_hash"],
        "comparison_class": contract.comparison_class(base["effective"]["parameters"], other["effective"]["parameters"])["kind"],
        "paired": contract.pairing_verdict(base, other)["paired"],
    }
    # Continuous evolution: consecutive-frame correlation vs independent realizations.
    corr = []
    for k in range(0, len(base_frames) - 1):
        a = np.asarray(base_frames[k]["atmosphere_opd_m"], dtype=float)[mask]
        b = np.asarray(base_frames[k + 1]["atmosphere_opd_m"], dtype=float)[mask]
        corr.append(float(np.corrcoef(a, b)[0, 1]))
    result["continuity"] = {
        "consecutive_frame_correlation_min": min(corr),
        "consecutive_frame_correlation_mean": float(np.mean(corr)),
        "all_frame_digests_distinct": len(set(digests_b)) == len(digests_b),
        "runtime_travel_equals_admitted": base["checks"]["horizon"]["equal"],
        "max_travel_px": base["admission"]["max_travel_px"],
        "travel_budget_px": base["admission"]["travel_budget_px"],
        "note": "one realization translated by 0.255 px per frame at 10 m/s; frames are not independent redraws",
    }
    # Same atmosphere, AO change.
    verdict = contract.pairing_verdict(base, paired)
    result["same_atmosphere"] = {
        "changed": verdict["expected"]["changed"],
        "paired": verdict["paired"],
        "matching_atmosphere_samples": verdict["matching_atmosphere_samples"],
        "time_grids_equal": verdict["time_grids_equal"],
        "calibration_rebuilt_identity": paired["identities"]["calibration"]["interaction_matrix_hash"] != base["identities"]["calibration"]["interaction_matrix_hash"],
        "wfs_identity_changed": paired["identities"]["calibration"]["wfs_component_hash"] != base["identities"]["calibration"]["wfs_component_hash"],
        "atmosphere_component_hash_equal": paired["identities"]["atmosphere"]["component_hash"] == base["identities"]["atmosphere"]["component_hash"],
        "residual_samples_differing": sum(1 for a, b in zip(base["per_frame"]["residual_sha256"], paired["per_frame"]["residual_sha256"]) if a != b),
        "summary": {key: [base["summary"][key], paired["summary"][key]] for key in (
            "mean_residual_rms_m", "averaged_intensity_peak_strehl_corrected", "mean_instantaneous_peak_strehl_corrected", "mean_valid_measurement_fraction")},
    }
    # Passivity.
    control = items["control"]["control"]
    result["passivity"] = {
        "history_digest_equal": control["history_digest"] == base["identities"]["history_digest"],
        "history_config_hash_equal": control["history_config_hash"] == base["identities"]["history_config_hash"],
        "members_compared": sorted(control["history_digest"]["members"]),
        "observer_disabled_wall_s": control["child_wall_s"],
    }
    # Numerical self-checks of every observed run.
    result["self_checks"] = {role: items[role]["run"]["checks"]["all_passed"] for role in ("pilot", "baseline", "replay", "different-seed", "same-atmosphere")}
    result["self_check_maxima"] = {
        role: {
            **items[role]["run"]["checks"]["independent_every_frame"],
            "psf_direct_dft_max_abs": max(max(o["uncorrected_psf_max_abs_difference"], o["corrected_psf_max_abs_difference"]) for o in items[role]["run"]["checks"]["oracle_frames"]),
            "strehl_direct_dft_max_abs": max(max(o["uncorrected_strehl_abs_difference"], o["corrected_strehl_abs_difference"]) for o in items[role]["run"]["checks"]["oracle_frames"]),
            "final_observation_linearity_max_abs": max(v["final_observation_linearity_max_abs"] for v in items[role]["run"]["checks"]["sum_consistency"].values()),
            "observation_full_flux_max_error": items[role]["run"]["checks"]["observation_full_flux_max_error"],
        } for role in ("baseline", "replay", "different-seed", "same-atmosphere")
    }
    # Against the published frozen explorer baseline (same configuration hash, other numerical environment).
    published = REPO / "web" / "ao-explorer" / "data"
    entry = read_json(published / "current.json")
    metrics = read_json(published / entry["dataset_id"] / "cases" / "baseline" / "metrics.json")
    case = read_json(published / entry["dataset_id"] / "cases" / "baseline" / "config.json")
    pf = metrics["per_frame"]

    def max_abs(published_values: List[Optional[float]], ours: List[Optional[float]], scale: float) -> float:
        return max(abs(a - b * scale) for a, b in zip(published_values, ours))

    result["frozen_explorer_baseline"] = {
        "published_config_hash": case.get("effective_config_hash"),
        "dynamic_config_hash": base["effective"]["system_config_hash"],
        "config_hash_equal": case.get("effective_config_hash") == base["effective"]["system_config_hash"],
        "max_abs_difference": {
            "atmosphere_rms_nm": max_abs(pf["atmosphere_rms_nm"]["values"], base["per_frame"]["atmosphere_rms_m"], 1e9),
            "residual_rms_nm": max_abs(pf["residual_rms_nm"]["values"], base["per_frame"]["residual_rms_m"], 1e9),
            "peak_strehl_uncorrected": max_abs(pf["peak_strehl_uncorrected"]["values"], base["per_frame"]["peak_strehl_uncorrected"], 1.0),
            "peak_strehl_corrected": max_abs(pf["peak_strehl_corrected"]["values"], base["per_frame"]["peak_strehl_corrected"], 1.0),
            "valid_measurement_fraction": max_abs(pf["valid_measurement_fraction"]["values"], base["per_frame"]["valid_measurement_fraction"], 1.0),
        },
        "summary": {
            "published_mean_residual_rms_nm": metrics["summary"]["mean_residual_rms_nm"],
            "dynamic_mean_residual_rms_nm": base["summary"]["mean_residual_rms_m"] * 1e9,
            "published_average_psf_peak_strehl_corrected": metrics["summary"]["average_psf_peak_strehl_corrected"],
            "dynamic_averaged_intensity_peak_strehl_corrected": base["summary"]["averaged_intensity_peak_strehl_corrected"],
        },
        "environments": {"published": "CPython 3.14.3, macOS 26.5 arm64, NumPy 2.5.0, SciPy 1.18.0",
                         "dynamic": base["identities"]["environment"]},
    }
    result["identities"] = {role: {"run_id": items[role]["run"]["run_id"], "physical_identity": items[role]["run"]["effective"]["physical_identity"],
                                   "system_config_hash": items[role]["run"]["effective"]["system_config_hash"],
                                   "history_sha256": items[role]["run"]["identities"]["history_digest"]["sha256"],
                                   "run_json_sha256": contract.sha256_bytes((items[role]["attempt"] / "run.json").read_bytes()),
                                   "frames_bin_sha256": items[role]["run"]["arrays"]["frames"]["sha256"],
                                   "producer_sha256": items[role]["run"]["identities"]["producer"]["worker"]["sha256"]}
                            for role in ("pilot", "baseline", "replay", "different-seed", "same-atmosphere")}
    result["identities"]["control"] = {"history_sha256": control["history_digest"]["sha256"], "producer_sha256": control["identities"]["worker"]["sha256"]}
    result["resources"] = {role: items[role]["run"]["resources"] for role in ("pilot", "baseline", "replay", "different-seed", "same-atmosphere")}
    result["consumption"] = consumption(directory)
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "evaluation.json", result)
    write_json(out / "plan.json", plan)
    (out / "ledger.jsonl").write_text((directory / LEDGER_NAME).read_text(encoding="utf-8"), encoding="utf-8")
    return result


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("plan", "pilot", "run", "record", "evaluate", "status"))
    parser.add_argument("role", nargs="?")
    parser.add_argument("--dir", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--label")
    parser.add_argument("--wall-s", type=float)
    parser.add_argument("--note", default="")
    parser.add_argument("--kind", default="fixture_session")
    arguments = parser.parse_args(argv)
    directory = arguments.dir
    directory.mkdir(parents=True, exist_ok=True)
    try:
        if arguments.command == "plan":
            value: Any = draft_plan(directory)
        elif arguments.command == "pilot":
            value = pilot(directory)
        elif arguments.command == "run":
            value = run_role(directory, arguments.role)
        elif arguments.command == "record":
            value = record(directory, arguments.label, arguments.wall_s, arguments.note, arguments.kind)
        elif arguments.command == "evaluate":
            value = evaluate(directory, arguments.out)
        else:
            value = {"consumption": consumption(directory), "ceilings": {"wall_s": WALL_CEILING_S, "raw_bytes": RAW_CEILING_BYTES}}
    except ValidationRefusal as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}))
        return 3
    print(json.dumps(value, indent=1, default=str)[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
