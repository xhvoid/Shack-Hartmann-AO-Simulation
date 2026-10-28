"""AO-REF-019 smoke-runner contract: kernel isolation, budget, injection.

The static tests always run; the two integration tests spawn a real kernel
and therefore skip in environments without the ``notebook-test`` extra
(``nbclient`` + ``ipykernel``), exactly like the notebook CI lanes.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# scripts/ is a path-addressed tool directory, not an importable package;
# loading the runner by file keeps collection working under both
# `python -m pytest` (repository root on sys.path) and the bare `pytest`
# entry point (repository root absent).
_RUNNER_SPEC = importlib.util.spec_from_file_location(
    "run_notebook_smoke_for_runner_tests",
    ROOT / "scripts" / "run_notebook_smoke.py",
)
assert _RUNNER_SPEC is not None and _RUNNER_SPEC.loader is not None
runner = importlib.util.module_from_spec(_RUNNER_SPEC)
sys.modules[_RUNNER_SPEC.name] = runner
_RUNNER_SPEC.loader.exec_module(runner)


def test_kernel_environment_always_forces_headless_matplotlib(monkeypatch):
    monkeypatch.setenv("MPLBACKEND", "pdf")
    assert runner._kernel_environment()["MPLBACKEND"] == "Agg"
    monkeypatch.delenv("MPLBACKEND")
    assert runner._kernel_environment()["MPLBACKEND"] == "Agg"


def _notebook_with_parameter_tags(nbformat, tag_counts: int):
    notebook = nbformat.v4.new_notebook()
    notebook.cells.append(nbformat.v4.new_markdown_cell("narrative"))
    for _ in range(tag_counts):
        tagged = nbformat.v4.new_code_cell("FAST_SMOKE = False")
        tagged.metadata["tags"] = [runner.PARAMETERS_TAG]
        notebook.cells.append(tagged)
    notebook.cells.append(nbformat.v4.new_code_cell("result = FAST_SMOKE"))
    return notebook


def test_fast_smoke_injection_lands_directly_after_the_parameters_cell():
    nbformat = pytest.importorskip("nbformat")
    notebook = _notebook_with_parameter_tags(nbformat, 1)
    runner._inject_fast_smoke_override(notebook)
    override = notebook.cells[2]
    assert override.cell_type == "code"
    assert override.source == runner.FAST_SMOKE_OVERRIDE_SOURCE
    assert override.metadata["tags"] == ["injected-parameters"]
    assert notebook.cells[1].source == "FAST_SMOKE = False"
    assert notebook.cells[3].source == "result = FAST_SMOKE"


@pytest.mark.parametrize("tag_counts", [0, 2])
def test_fast_smoke_requires_exactly_one_parameters_cell(tag_counts):
    nbformat = pytest.importorskip("nbformat")
    notebook = _notebook_with_parameter_tags(nbformat, tag_counts)
    with pytest.raises(SystemExit, match="exactly one code cell tagged"):
        runner._inject_fast_smoke_override(notebook)


def test_kernel_receives_the_isolated_environment_and_the_override(
    monkeypatch, tmp_path
):
    nbformat = pytest.importorskip("nbformat")
    pytest.importorskip("nbclient")
    pytest.importorskip("ipykernel")

    notebook = nbformat.v4.new_notebook()
    parameters = nbformat.v4.new_code_cell("FAST_SMOKE = False")
    parameters.metadata["tags"] = [runner.PARAMETERS_TAG]
    notebook.cells = [
        parameters,
        nbformat.v4.new_code_cell(
            "import matplotlib\n"
            "assert matplotlib.get_backend().lower() == 'agg', "
            "matplotlib.get_backend()\n"
            "assert FAST_SMOKE is True"
        ),
    ]
    notebook_path = tmp_path / "kernel_contract.ipynb"
    nbformat.write(notebook, notebook_path)

    # The kernel must see Agg even when the invoking environment disagrees.
    monkeypatch.setenv("MPLBACKEND", "pdf")
    elapsed = runner._run_with_budget(
        notebook_path,
        cell_timeout_s=120,
        budget_s=240,
        fast_smoke=True,
    )
    assert elapsed > 0.0


def test_the_budget_kills_a_hung_notebook(tmp_path):
    nbformat = pytest.importorskip("nbformat")
    pytest.importorskip("nbclient")
    pytest.importorskip("ipykernel")

    notebook = nbformat.v4.new_notebook()
    notebook.cells = [
        nbformat.v4.new_code_cell("import time\ntime.sleep(600)"),
    ]
    notebook_path = tmp_path / "hung.ipynb"
    nbformat.write(notebook, notebook_path)

    start = time.perf_counter()
    with pytest.raises(SystemExit, match="whole-notebook budget"):
        runner._run_with_budget(
            notebook_path,
            cell_timeout_s=120,
            budget_s=5,
            fast_smoke=False,
        )
    # The per-cell timeout (120 s) never fires; the parent's budget does.
    assert time.perf_counter() - start < 60.0
