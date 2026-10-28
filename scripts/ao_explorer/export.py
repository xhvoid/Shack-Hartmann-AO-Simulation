"""AO Simulation Explorer producer and exporter command line.

Run from the repository root with the locked environment, never in parallel::

    python scripts/ao_explorer/export.py plan    --series-dir outputs/ao_explorer_v1/<series-id>
    python scripts/ao_explorer/export.py pilot   --series-dir ...
    python scripts/ao_explorer/export.py freeze  --series-dir ...
    python scripts/ao_explorer/export.py batch   --series-dir ...
    python scripts/ao_explorer/export.py derive  --series-dir ...   # binary observations
    python scripts/ao_explorer/export.py web     --series-dir ... --web-dir web/ao-explorer
    python scripts/ao_explorer/export.py status  --series-dir ...

``pilot``, ``batch``, ``derive`` and ``web`` launch one supervised child at a
time through the repository resource guard (two native threads, timeout,
memory-pressure stop) and record every launch or refusal in the series
ledger, so the 20-minute numerical wall-time and 512 MiB raw-evidence
ceilings are enforced cumulatively.  ``plan`` and ``freeze`` only read the
source and records.  Nothing here pushes, publishes or deploys.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

import identity
import producer
import protocol


HERE = Path(__file__).resolve().parent


def _python() -> str:
    return sys.executable


def _job_estimate_bytes(job: Dict[str, Any]) -> int:
    """Projected raw bytes of one trajectory attempt (movie + means + history + records)."""

    frames = len(job["display_indices"])
    movie = frames * (3 * 52 * 52 + 2 * 156 * 156) * 8
    means = (5 * 156 * 156) * 8 if job["observer"] else 0
    history = job["n_steps"] * 800
    records = 1_500_000
    return movie + means + history + records


def command_plan(arguments: argparse.Namespace) -> int:
    plan = producer.draft_plan(arguments.series_dir, arguments.series_dir.name)
    summary = [
        {
            "job": job["job_id"],
            "admitted": job["admission"]["admitted"],
            "requests": job["admission"]["request_count"],
            "max_travel_px": job["admission"].get("max_travel_px"),
            "budget_px": job["admission"].get("travel_budget_px"),
            "margin_px": job["admission"].get("margin_px"),
        }
        for job in plan["jobs"]
    ]
    print(json.dumps({"all_jobs_admitted": plan["all_jobs_admitted"], "jobs": summary, "scene_id": plan["scene"]["scene_id"]}, indent=2))
    return 0 if plan["all_jobs_admitted"] else 2


def _launch_job(series_dir: Path, job: Dict[str, Any], *, draft: bool, estimate: Any,
                projected_wall_s: float) -> Dict[str, Any]:
    argv = [_python(), str(HERE / "run_job.py"), "--series-dir", str(series_dir), "--job", job["job_id"]]
    if draft:
        argv.append("--draft")
    return producer.supervise(
        series_dir,
        argv,
        label=job["job_id"],
        kind="trajectory",
        job_id=job["job_id"],
        estimate=estimate,
        timeout_s=protocol.CHILD_TIMEOUT_S,
        projected_wall_s=projected_wall_s,
        projected_bytes=_job_estimate_bytes(job),
    )


def command_pilot(arguments: argparse.Namespace) -> int:
    plan = producer.load_plan(arguments.series_dir, frozen=False)
    if not plan["all_jobs_admitted"]:
        print("the draft plan does not admit every job; the pilot is not started")
        return 2
    job = producer.plan_job(plan, "pilot-baseline")
    if producer.completed_attempt(arguments.series_dir, job["job_id"]) is not None:
        print("the pilot already completed; its record is reused")
        return 0
    entry = _launch_job(
        arguments.series_dir,
        job,
        draft=True,
        estimate=producer.resource_estimate("explorer pilot (64 frames)"),
        projected_wall_s=protocol.CHILD_TIMEOUT_S,
    )
    print(json.dumps({key: entry.get(key) for key in ("status", "reason", "wall_s")}, indent=2))
    return 0 if entry.get("status") == "COMPLETED" else 4


def _pilot_record(series_dir: Path) -> Dict[str, Any]:
    attempt = producer.completed_attempt(series_dir, "pilot-baseline")
    if attempt is None:
        raise producer.ProducerError("no completed pilot")
    return producer.read_json(attempt / "job_record.json")


def command_freeze(arguments: argparse.Namespace) -> int:
    series_dir = arguments.series_dir
    if (series_dir / producer.FROZEN_PLAN_NAME).exists():
        print("the series plan is already frozen")
        return 0
    draft = producer.load_plan(series_dir, frozen=False)
    pilot = _pilot_record(series_dir)
    pilot_entry = [
        entry
        for entry in producer.ledger_entries(series_dir)
        if entry.get("job_id") == "pilot-baseline" and entry.get("status") == "COMPLETED"
    ][-1]
    pilot_frames = protocol.PILOT_FRAMES
    per_frame = pilot["loop_s"] / pilot_frames
    supervised_wall = float(pilot_entry["wall_s"])
    overhead = supervised_wall - pilot["loop_s"]
    remaining_jobs = [job for job in draft["jobs"] if job["role"] != "pilot"]
    projected = []
    for job in remaining_jobs:
        projected.append(
            {
                "job_id": job["job_id"],
                "projected_wall_s": overhead + per_frame * job["n_steps"],
                "projected_bytes": _job_estimate_bytes(job),
            }
        )
    used = producer.consumption(series_dir)
    batch_wall = sum(item["projected_wall_s"] for item in projected)
    batch_bytes = sum(item["projected_bytes"] for item in projected)
    # Observation derivation and rendering are deterministic processing in
    # the same ceilings; reserve their measured-order allowance up front.
    processing_reserve_s = 120.0
    feasible = (
        used["wall_s"] + batch_wall + processing_reserve_s <= protocol.WALL_TIME_CEILING_S
        and used["raw_bytes"] + batch_bytes <= protocol.RAW_EVIDENCE_CEILING_BYTES
    )
    frozen = dict(draft)
    frozen.update(
        {
            "state": "FROZEN" if feasible else "NOT_FROZEN_BUDGET",
            "frozen_utc": producer.utc_now(),
            "draft_plan_sha256": identity.sha256_file(series_dir / producer.DRAFT_PLAN_NAME),
            "pilot": {
                "job_record_sha256": identity.sha256_file(
                    producer.completed_attempt(series_dir, "pilot-baseline") / "job_record.json"
                ),
                "build_s": pilot["build_s"],
                "loop_s": pilot["loop_s"],
                "per_frame_s": per_frame,
                "supervised_wall_s": supervised_wall,
                "child_peak_rss_bytes": pilot["child_peak_rss_bytes"],
                "supervised_peak_rss_bytes": pilot_entry["supervised"]["peak_rss_bytes"],
                "observer_export_s": pilot.get("observer", {}).get("export_s"),
            },
            "projection": {
                "jobs": projected,
                "batch_wall_s": batch_wall,
                "batch_bytes": batch_bytes,
                "processing_reserve_s": processing_reserve_s,
                "consumption_at_freeze": used,
                "feasible_within_ceilings": feasible,
            },
        }
    )
    target = series_dir / (producer.FROZEN_PLAN_NAME if feasible else "series_plan.budget_refusal.json")
    producer.write_json(target, frozen)
    print(json.dumps(frozen["projection"], indent=2))
    return 0 if feasible else 5


def command_batch(arguments: argparse.Namespace) -> int:
    series_dir = arguments.series_dir
    plan = producer.load_plan(series_dir, frozen=True)
    pilot = plan["pilot"]
    estimate = producer.resource_estimate(
        "explorer production trajectory (180 frames)",
        measured_peak_bytes=int(max(pilot["child_peak_rss_bytes"], pilot["supervised_peak_rss_bytes"] or 0)),
    )
    projections = {item["job_id"]: item["projected_wall_s"] for item in plan["projection"]["jobs"]}
    outcomes: List[Dict[str, Any]] = []
    for job in plan["jobs"]:
        if job["role"] == "pilot":
            continue
        if arguments.only and job["job_id"] not in arguments.only:
            continue
        if producer.completed_attempt(series_dir, job["job_id"]) is not None:
            outcomes.append({"job": job["job_id"], "status": "REUSED_COMPLETED"})
            continue
        entry = _launch_job(series_dir, job, draft=False, estimate=estimate, projected_wall_s=projections[job["job_id"]])
        outcomes.append({"job": job["job_id"], "status": entry.get("status"), "reason": entry.get("reason"), "wall_s": entry.get("wall_s")})
        if entry.get("status") != "COMPLETED":
            break
    print(json.dumps({"outcomes": outcomes, "consumption": producer.consumption(series_dir)}, indent=2))
    return 0 if all(item["status"] in ("COMPLETED", "REUSED_COMPLETED") for item in outcomes) else 6


def _processing(arguments: argparse.Namespace, stage: str, extra: List[str], projected_wall_s: float) -> int:
    from shwfs_ao.runtime.resource_guard import MIB, ResourceEstimate

    argv = [_python(), str(HERE / "render.py"), stage, "--series-dir", str(arguments.series_dir), *extra]
    estimate = ResourceEstimate(
        label=f"explorer {stage} processing",
        baseline_bytes=160 * MIB,
        components={"retained_parents_and_images": 64 * MIB, "rendering_buffers": 32 * MIB},
        largest_buffer_bytes=16 * MIB,
        notes=("deterministic processing of retained parents; no AO run",),
    )
    entry = producer.supervise(
        arguments.series_dir,
        argv,
        label=stage,
        kind="processing",
        job_id=None,
        estimate=estimate,
        timeout_s=protocol.CHILD_TIMEOUT_S,
        projected_wall_s=projected_wall_s,
        projected_bytes=48 * 1024 * 1024,
    )
    print(json.dumps({key: entry.get(key) for key in ("status", "reason", "wall_s")}, indent=2))
    return 0 if entry.get("status") == "COMPLETED" else 7


def command_derive(arguments: argparse.Namespace) -> int:
    return _processing(arguments, "derive", [], 60.0)


def command_web(arguments: argparse.Namespace) -> int:
    return _processing(arguments, "web", ["--web-dir", str(arguments.web_dir)], 90.0)


def command_status(arguments: argparse.Namespace) -> int:
    used = producer.consumption(arguments.series_dir)
    entries = producer.ledger_entries(arguments.series_dir)
    print(
        json.dumps(
            {
                "consumption": used,
                "ceilings": {"wall_s": protocol.WALL_TIME_CEILING_S, "raw_bytes": protocol.RAW_EVIDENCE_CEILING_BYTES},
                "ledger": [
                    {key: entry.get(key) for key in ("utc", "label", "kind", "status", "wall_s", "reason")}
                    for entry in entries
                ],
            },
            indent=2,
        )
    )
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "pilot", "freeze", "batch", "derive", "web", "status"):
        command = sub.add_parser(name)
        command.add_argument("--series-dir", type=Path, required=True)
        if name == "batch":
            command.add_argument("--only", nargs="*", default=None)
        if name == "web":
            command.add_argument("--web-dir", type=Path, required=True)
    arguments = parser.parse_args(argv)
    arguments.series_dir = arguments.series_dir.resolve()
    arguments.series_dir.mkdir(parents=True, exist_ok=True)
    handler = {
        "plan": command_plan,
        "pilot": command_pilot,
        "freeze": command_freeze,
        "batch": command_batch,
        "derive": command_derive,
        "web": command_web,
        "status": command_status,
    }[arguments.command]
    try:
        return handler(arguments)
    except producer.ProducerError as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}))
        return 3


if __name__ == "__main__":
    sys.exit(main())
