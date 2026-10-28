#!/usr/bin/env python3
"""Execute canonical notebooks under the AO-REF-019 smoke contract.

Each notebook is executed by a dedicated runner subprocess in a fresh
temporary working directory (never the repository root).  The parent enforces
the whole-notebook wall-clock budget by killing the runner's process group
when the budget expires, so a hung cell, a stuck import, or an unresponsive
kernel cannot outlive it; the per-cell timeout is enforced inside ``nbclient``.
The kernel environment (``MPLBACKEND=Agg``) is passed explicitly through
``NotebookClient.execute`` into ``KernelManager.start_kernel`` — ``nbclient``
has no ``env`` trait, so a constructor argument would be silently dropped.
The runner imports only the installed package, so it validates that a
notebook runs from a built, non-editable wheel without source-tree imports,
network access, or hidden local files.

Usage::

    python scripts/run_notebook_smoke.py NOTEBOOK [NOTEBOOK ...]
    python scripts/run_notebook_smoke.py --class fast   # from the manifest
    python scripts/run_notebook_smoke.py --class slow --fast-smoke

``--class`` selects every canonical notebook whose manifest execution class
matches (``fast`` is the default CI selection).  ``--fast-smoke`` injects
``FAST_SMOKE = True`` immediately after each notebook's single
``parameters``-tagged cell, so slow studies run their small representative
parameterization in fast CI while the scheduled lane executes the full study.
Notebooks are executed on a throwaway copy, so the tracked ``.ipynb`` files
and their committed outputs are never modified by the smoke run.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "notebooks" / "notebook_manifest.json"

DEFAULT_CELL_TIMEOUT_S = 120
DEFAULT_NOTEBOOK_BUDGET_S = 600
PARAMETERS_TAG = "parameters"
FAST_SMOKE_OVERRIDE_SOURCE = "FAST_SMOKE = True"


def _canonical_paths_for_class(execution_class: str) -> list[Path]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return [
        ROOT / entry["path"]
        for entry in manifest["canonical"]
        if entry["execution_class"] == execution_class
    ]


def _kernel_environment() -> dict[str, str]:
    """Environment for the runner subprocess and the kernel it starts."""

    environment = dict(os.environ)
    environment["MPLBACKEND"] = "Agg"
    return environment


def _inject_fast_smoke_override(notebook) -> None:
    """Insert ``FAST_SMOKE = True`` after the single parameters-tagged cell."""

    import nbformat

    tagged_indices = [
        index
        for index, cell in enumerate(notebook.cells)
        if cell.cell_type == "code"
        and PARAMETERS_TAG in cell.get("metadata", {}).get("tags", [])
    ]
    if len(tagged_indices) != 1:
        raise SystemExit(
            f"--fast-smoke requires exactly one code cell tagged "
            f"{PARAMETERS_TAG!r}; found {len(tagged_indices)}"
        )
    override = nbformat.v4.new_code_cell(FAST_SMOKE_OVERRIDE_SOURCE)
    override.metadata["tags"] = ["injected-parameters"]
    notebook.cells.insert(tagged_indices[0] + 1, override)


def _execute_in_process(
    notebook_path: Path,
    *,
    cell_timeout_s: int,
    fast_smoke: bool,
) -> None:
    """Runner-subprocess mode: execute one notebook on a throwaway copy."""

    import nbformat
    from nbclient import NotebookClient

    if not notebook_path.is_file():
        raise SystemExit(f"notebook not found: {notebook_path}")

    with tempfile.TemporaryDirectory(prefix="nb-smoke-") as working_dir:
        scratch = Path(working_dir) / notebook_path.name
        shutil.copyfile(notebook_path, scratch)
        notebook = nbformat.read(scratch, as_version=4)
        if fast_smoke:
            _inject_fast_smoke_override(notebook)
        client = NotebookClient(
            notebook,
            timeout=cell_timeout_s,
            kernel_name="python3",
            resources={"metadata": {"path": str(scratch.parent)}},
        )
        # nbclient has no ``env`` trait: the mapping must travel through
        # execute() into KernelManager.start_kernel to reach the kernel.
        client.execute(env=_kernel_environment())


def _kill_process_group(process: subprocess.Popen) -> None:
    """Kill the runner and its kernel; both live in one session/group."""

    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        process.kill()
    process.wait()


def _run_with_budget(
    notebook_path: Path,
    *,
    cell_timeout_s: int,
    budget_s: int,
    fast_smoke: bool,
) -> float:
    """Execute one notebook in a subprocess killed at the wall-clock budget."""

    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--single",
        str(notebook_path),
        "--cell-timeout",
        str(cell_timeout_s),
    ]
    if fast_smoke:
        command.append("--fast-smoke")
    start = time.perf_counter()
    process = subprocess.Popen(
        command,
        env=_kernel_environment(),
        start_new_session=True,
    )
    try:
        returncode = process.wait(timeout=budget_s)
    except subprocess.TimeoutExpired:
        _kill_process_group(process)
        raise SystemExit(
            f"{notebook_path.name} exceeded the whole-notebook budget: "
            f"killed after {budget_s}s"
        ) from None
    if returncode != 0:
        raise SystemExit(
            f"notebook runner subprocess exited with code {returncode}"
        )
    return time.perf_counter() - start


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("notebooks", nargs="*", type=Path)
    parser.add_argument(
        "--class",
        dest="execution_class",
        help="Execute every manifest canonical notebook with this execution class.",
    )
    parser.add_argument(
        "--fast-smoke",
        action="store_true",
        help=(
            "Inject FAST_SMOKE = True after each notebook's parameters cell "
            "so slow studies run their representative fast parameterization."
        ),
    )
    parser.add_argument(
        "--single",
        action="store_true",
        help=(
            "Internal runner mode: execute exactly one notebook in-process "
            "without budget enforcement (the parent enforces the budget)."
        ),
    )
    parser.add_argument("--cell-timeout", type=int, default=DEFAULT_CELL_TIMEOUT_S)
    parser.add_argument("--notebook-budget", type=int, default=DEFAULT_NOTEBOOK_BUDGET_S)
    args = parser.parse_args(argv)

    if args.single:
        if args.execution_class or len(args.notebooks) != 1:
            parser.error("--single executes exactly one explicit notebook path.")
        notebook_path = args.notebooks[0]
        resolved = notebook_path if notebook_path.is_absolute() else ROOT / notebook_path
        _execute_in_process(
            resolved,
            cell_timeout_s=args.cell_timeout,
            fast_smoke=args.fast_smoke,
        )
        return 0

    selected: list[Path] = list(args.notebooks)
    if args.execution_class:
        selected.extend(_canonical_paths_for_class(args.execution_class))
    if not selected:
        parser.error("provide notebook paths or --class to select from the manifest.")

    failures = 0
    for notebook_path in selected:
        resolved = notebook_path if notebook_path.is_absolute() else ROOT / notebook_path
        try:
            elapsed = _run_with_budget(
                resolved,
                cell_timeout_s=args.cell_timeout,
                budget_s=args.notebook_budget,
                fast_smoke=args.fast_smoke,
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
