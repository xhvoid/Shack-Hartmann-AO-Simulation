#!/usr/bin/env python3
"""Run one command under the resource guard with a human-authorized budget above the policy.

Proposed in the post-T2 experiment packet; unexecuted on any governed run.  The
desktop policy budget (``min(2 GiB, 12.5 % physical, 25 % available)``) with
the guard's 2x margin refuses the S4 A1 and 42 m stages on any 16 GiB host.
``python -m shwfs_ao.runtime.resource_guard`` can only lower that budget; the
ESO benchmark runner's ``--authorized-budget-mib`` applies to ESO tiers only.
This launcher mirrors that runner's ``_authorized_decision`` for any command:

1. the policy preflight runs first and is recorded;
2. if it accepts, the command runs under the policy budget (no authorization
   is consumed);
3. if it refuses *only* because the margined estimate exceeds the policy
   budget, the authorization is checked: a non-empty note, the margined
   estimate within the authorized budget, the largest single buffer within the
   64 MiB scratch ceiling, memory pressure ``normal`` now, and available memory
   at least the unmargined estimate plus a 1 GiB reserve (so the run does not
   depend on swap); then the command runs under the authorized budget;
4. a refusal for any other reason (pressure, scratch ceiling, unreliable host
   monitoring) is never overridden.

The supervised group gets the guard's thread limits (two native threads by
default), the aggregate-RSS budget, the wall-clock limit and the pressure
stop.  Exit status: 0 completed, 1 failed or resource-limited, 3 refused.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from shwfs_ao.runtime.resource_guard import (
    DEFAULT_SCRATCH_CEILING_BYTES,
    DEFAULT_THREAD_LIMIT,
    MIB,
    ResourceEstimate,
    host_snapshot,
    preflight,
    run_supervised,
)

RESERVE_BYTES = 1024 * MIB


def authorized_decision(estimate: ResourceEstimate, *, authorized_bytes: int, note: str) -> dict[str, Any]:
    """The ESO runner's authorization semantics for an arbitrary command."""

    snapshot = host_snapshot()
    reasons: list[str] = []
    if not note.strip():
        reasons.append("an authorized budget needs a non-empty --authorization-note")
    if estimate.required_bytes > authorized_bytes:
        reasons.append(
            f"estimated peak {estimate.required_bytes / MIB:.0f} MiB (with {estimate.margin:g}x margin) "
            f"exceeds the authorized {authorized_bytes / MIB:.0f} MiB"
        )
    if estimate.largest_buffer_bytes > DEFAULT_SCRATCH_CEILING_BYTES:
        reasons.append("largest single buffer exceeds the 64 MiB scratch ceiling")
    if snapshot.pressure.level != "normal":
        reasons.append(f"host memory pressure is {snapshot.pressure.level} now")
    if snapshot.available_bytes is None or snapshot.available_bytes < estimate.raw_bytes + RESERVE_BYTES:
        reasons.append(
            f"measured available memory {(snapshot.available_bytes or 0) / MIB:.0f} MiB is below the "
            f"unmargined estimate plus a 1 GiB reserve ({(estimate.raw_bytes + RESERVE_BYTES) / MIB:.0f} MiB)"
        )
    return {
        "authorized_budget_bytes": int(authorized_bytes),
        "note": note,
        "snapshot": snapshot.to_record(),
        "accepted": not reasons,
        "reasons": reasons,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", required=True)
    parser.add_argument("--estimate-mib", type=float, required=True, help="audited raw peak RSS of the whole process group, before the 2x margin")
    parser.add_argument("--largest-buffer-mib", type=float, default=0.0)
    parser.add_argument("--authorized-budget-mib", type=float, required=True, help="the budget a human authorized for this run, above the desktop policy")
    parser.add_argument("--authorization-note", required=True, help="date and wording of the human authorization")
    parser.add_argument("--timeout-s", type=float, required=True)
    parser.add_argument("--threads", type=int, default=DEFAULT_THREAD_LIMIT)
    parser.add_argument("--log", required=True, help="the supervised group's combined output")
    parser.add_argument("--record", required=True, help="JSON record of the preflight, the authorization and the supervision")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args(argv)
    command = list(arguments.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("a command is required after --")
    record_path = Path(arguments.record)
    if record_path.exists():
        parser.error(f"{record_path} exists; nothing ran and nothing is overwritten")
    estimate = ResourceEstimate(
        label=arguments.label,
        baseline_bytes=0,
        components={"audited_peak": int(arguments.estimate_mib * MIB)},
        largest_buffer_bytes=int(arguments.largest_buffer_mib * MIB),
    )
    policy = preflight(estimate)
    record: dict[str, Any] = {"command": command, "policy_preflight": policy.to_record(), "authorization": None}
    budget = policy.budget_bytes
    if not policy.accepted:
        only_budget = all(reason.startswith("estimated peak") for reason in policy.reasons)
        if not only_budget:
            record["result"] = {"status": "REFUSED", "reason": "; ".join(policy.reasons) + " (not overridable)"}
            _write(record_path, record)
            return 3
        authorization = authorized_decision(
            estimate, authorized_bytes=int(arguments.authorized_budget_mib * MIB), note=arguments.authorization_note
        )
        record["authorization"] = authorization
        if not authorization["accepted"]:
            record["result"] = {"status": "REFUSED", "reason": "; ".join(authorization["reasons"])}
            _write(record_path, record)
            return 3
        budget = int(arguments.authorized_budget_mib * MIB)
    result = run_supervised(
        command,
        budget_bytes=int(budget),
        timeout_s=arguments.timeout_s,
        threads=arguments.threads,
        log_path=arguments.log,
    )
    record["result"] = result.to_record()
    _write(record_path, record)
    return 0 if result.status == "COMPLETED" else 1


def _write(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, sort_keys=True, default=str)
        handle.write("\n")
    print(json.dumps(record.get("result"), indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    sys.exit(main())
