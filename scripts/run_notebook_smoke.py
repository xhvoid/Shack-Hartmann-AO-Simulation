#!/usr/bin/env python3
"""Execute canonical notebooks under the AO-REF-019 smoke contract.

Each notebook is executed with ``nbclient`` in a fresh temporary working
directory (never the repository root), with ``MPLBACKEND=Agg``, a per-cell
timeout, and a whole-notebook wall-clock budget.  The runner imports only the
installed package, so it validates that a notebook runs from a built,
non-editable wheel without source-tree imports, network access, or hidden
local files.

Usage::

    python scripts/run_notebook_smoke.py NOTEBOOK [NOTEBOOK ...]
    python scripts/run_notebook_smoke.py --class fast   # from the manifest

``--class`` selects every canonical notebook whose manifest execution class
matches (``fast`` is the default CI selection).  Notebooks are executed on a
throwaway copy, so the tracked ``.ipynb`` files and their committed outputs are
never modified by the smoke run.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "notebooks" / "notebook_manifest.json"

DEFAULT_CELL_TIMEOUT_S = 120
DEFAULT_NOTEBOOK_BUDGET_S = 600


def _canonical_paths_for_class(execution_class: str) -> list[Path]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return [
        ROOT / entry["path"]
        for entry in manifest["canonical"]
        if entry["execution_class"] == execution_class
    ]


def _execute(notebook_path: Path, *, cell_timeout_s: int, budget_s: int) -> float:
    import nbformat
    from nbclient import NotebookClient

    if not notebook_path.is_file():
        raise SystemExit(f"notebook not found: {notebook_path}")

    with tempfile.TemporaryDirectory(prefix="nb-smoke-") as working_dir:
        scratch = Path(working_dir) / notebook_path.name
        shutil.copyfile(notebook_path, scratch)
        notebook = nbformat.read(scratch, as_version=4)
        environment = dict(os.environ)
        environment["MPLBACKEND"] = "Agg"
        client = NotebookClient(
            notebook,
            timeout=cell_timeout_s,
            kernel_name="python3",
            resources={"metadata": {"path": str(scratch.parent)}},
            env=environment,
        )
        start = time.perf_counter()
        client.execute()
        elapsed = time.perf_counter() - start
        if elapsed > budget_s:
            raise SystemExit(
                f"{notebook_path.name} exceeded the whole-notebook budget: "
                f"{elapsed:.1f}s > {budget_s}s"
            )
        return elapsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("notebooks", nargs="*", type=Path)
    parser.add_argument(
        "--class",
        dest="execution_class",
        help="Execute every manifest canonical notebook with this execution class.",
    )
    parser.add_argument("--cell-timeout", type=int, default=DEFAULT_CELL_TIMEOUT_S)
    parser.add_argument("--notebook-budget", type=int, default=DEFAULT_NOTEBOOK_BUDGET_S)
    args = parser.parse_args(argv)

    selected: list[Path] = list(args.notebooks)
    if args.execution_class:
        selected.extend(_canonical_paths_for_class(args.execution_class))
    if not selected:
        parser.error("provide notebook paths or --class to select from the manifest.")

    failures = 0
    for notebook_path in selected:
        resolved = notebook_path if notebook_path.is_absolute() else ROOT / notebook_path
        try:
            elapsed = _execute(
                resolved,
                cell_timeout_s=args.cell_timeout,
                budget_s=args.notebook_budget,
            )
        except SystemExit as exit_error:
            print(f"FAIL {notebook_path}: {exit_error}")
            failures += 1
        except Exception as error:  # noqa: BLE001 - report and continue
            print(f"FAIL {notebook_path}: {type(error).__name__}: {error}")
            failures += 1
        else:
            print(f"ok   {notebook_path}  ({elapsed:.1f}s)")

    if failures:
        print(f"{failures} notebook(s) failed the smoke contract.")
        return 1
    print(f"{len(selected)} notebook(s) executed cleanly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
