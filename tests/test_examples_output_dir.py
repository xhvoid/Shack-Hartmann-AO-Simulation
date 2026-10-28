"""Examples that default to ``figures/detector_level_SCAO`` honour ``AO_DEMO_OUTPUT_DIR``.

That tracked directory's files are not bit-portable across platforms, so CI
redirects the demos it runs.  A static check requires every
``detector_level_SCAO`` literal under ``examples/`` to be the default of an
``os.environ.get("AO_DEMO_OUTPUT_DIR", ...)`` lookup.  The two CI-smoked demos
and the interaction-matrix demo also run here as subprocesses from the
repository root, as CI runs them but by absolute script path, with the override
pointing at a directory that does not exist yet.  Every output must land there,
every ``Wrote`` line must name the file actually written, and no file or
directory under ``figures/`` may be created, removed, or rewritten (content and
mtime).  The slower examples are covered only by the static check.  The
examples are located relative to this file; the wheel-smoke bundle manifest
does not list this test, so the wheel job does not run it.
"""

from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIGURES = ROOT / "figures"

_DEMO_OUTPUTS = {
    "run_interaction_matrix_demo.py": (
        "poke_matrix_singular_values.png",
        "poke_matrix_singular_values.csv",
        "poke_amplitude_scan.png",
        "poke_amplitude_scan.csv",
    ),
    "run_psf_strehl_demo.py": ("psf_strehl_demo.png", "psf_strehl_demo.csv"),
    "run_shwfs_centroid_demo.py": (
        "shwfs_centroid_demo.png",
        "shwfs_centroid_demo.csv",
    ),
}


def _tree_state(directory: Path) -> dict[str, tuple[int, int, str] | None]:
    """Every entry below ``directory``: files by size, mtime and SHA-256."""

    state: dict[str, tuple[int, int, str] | None] = {}
    if not directory.exists():
        return state
    for path in sorted(directory.rglob("*")):
        key = path.relative_to(directory).as_posix()
        if path.is_file():
            stat = path.stat()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            state[key] = (stat.st_size, stat.st_mtime_ns, digest)
        else:
            state[key] = None
    return state


def _unredirected_output_literals(source: str) -> list[int]:
    """Lines of ``detector_level_SCAO`` literals outside the override default.

    A literal is redirected when it lies inside the default argument of
    ``os.environ.get("AO_DEMO_OUTPUT_DIR", default)``.  Docstrings and other
    bare string statements are prose, not paths, and are ignored.
    """

    tree = ast.parse(source)
    exempt: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            exempt.add(id(node.value))
        elif (
            isinstance(node, ast.Call)
            and ast.unparse(node.func) == "os.environ.get"
            and len(node.args) == 2
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "AO_DEMO_OUTPUT_DIR"
        ):
            exempt.update(id(child) for child in ast.walk(node.args[1]))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "detector_level_SCAO" in node.value
        and id(node) not in exempt
    ]


def test_every_example_path_into_tracked_figures_honours_the_override():
    sources = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "examples").glob("*.py"))
    }
    writers = {name for name, source in sources.items() if "detector_level_SCAO" in source}
    # The subprocess-checked demos keep this scan from passing vacuously.
    assert set(_DEMO_OUTPUTS) <= writers
    unredirected = {
        name: lines
        for name in sorted(writers)
        if (lines := _unredirected_output_literals(sources[name]))
    }
    assert unredirected == {}, "hard-coded figures/detector_level_SCAO path"


@pytest.mark.parametrize("script", sorted(_DEMO_OUTPUTS))
def test_demo_writes_only_to_the_override_directory(script, tmp_path):
    example = ROOT / "examples" / script
    assert example.is_file(), example
    output_dir = tmp_path / "ao-generated"
    figures_before = _tree_state(FIGURES)

    result = subprocess.run(
        [sys.executable, str(example)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "AO_DEMO_OUTPUT_DIR": str(output_dir),
            "MPLBACKEND": "Agg",
        },
        timeout=600,
    )

    assert result.returncode == 0, result.stderr
    assert _tree_state(FIGURES) == figures_before, f"{script} wrote under figures/"
    assert output_dir.is_dir(), f"{script} ignored AO_DEMO_OUTPUT_DIR"
    expected = _DEMO_OUTPUTS[script]
    assert sorted(path.name for path in output_dir.iterdir()) == sorted(expected)
    assert all((output_dir / name).stat().st_size > 0 for name in expected)
    # A relative ``Wrote`` path is relative to the repository root, which is
    # what pathlib's join does with it; an absolute one replaces ROOT.
    reported = [
        (ROOT / line.removeprefix("Wrote ")).resolve()
        for line in result.stdout.splitlines()
        if line.startswith("Wrote ")
    ]
    assert sorted(reported) == sorted(
        (output_dir / name).resolve() for name in expected
    )
