"""Numerical child entry point: run one planned explorer trajectory.

Usage (normally launched by ``export.py supervise``, never in parallel)::

    python scripts/ao_explorer/run_job.py --series-dir DIR --job JOB_ID [--draft]

``--draft`` is accepted only for the pilot, which runs against the draft
plan; every other job requires the frozen plan.  The child prints one JSON
line with its status and exits non-zero on any refusal.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import traceback

import producer


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--series-dir", type=Path, required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--draft", action="store_true", help="run the pilot against the draft plan")
    arguments = parser.parse_args(argv)
    try:
        record = producer.run_job(arguments.series_dir, arguments.job, frozen=not arguments.draft)
    except producer.ProducerError as exc:
        print(json.dumps({"status": "REFUSED", "job": arguments.job, "reason": str(exc)}))
        return 3
    except Exception as exc:  # noqa: BLE001 - the child reports, the supervisor records
        traceback.print_exc()
        print(json.dumps({"status": "FAILED", "job": arguments.job, "reason": f"{type(exc).__name__}: {exc}"}))
        return 1
    print(
        json.dumps(
            {
                "status": "COMPLETED",
                "job": arguments.job,
                "build_s": record["build_s"],
                "loop_s": record["loop_s"],
                "child_wall_s": record["child_wall_s"],
                "child_peak_rss_bytes": record["child_peak_rss_bytes"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
