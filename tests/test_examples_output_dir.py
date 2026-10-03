"""The CI-smoked demos honour ``AO_DEMO_OUTPUT_DIR`` and leave ``figures/`` alone.

``examples/run_psf_strehl_demo.py`` and ``examples/run_shwfs_centroid_demo.py``
default to the tracked ``figures/detector_level_SCAO`` directory, whose files
are not bit-portable across platforms, so CI redirects them.  Each demo runs
here as a subprocess, exactly as CI invokes it, with the override pointing at
a directory that does not exist yet.  Every output must land there, every
``Wrote`` line must name the file actually written, and no file or directory
under ``figures/`` may be created, removed, or rewritten (content and mtime).
The examples are located relative to this file, so the test runs unchanged
from a checkout or from a wheel-smoke bundle that ships the examples.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIGURES = ROOT / "figures"

_DEMO_OUTPUTS = {
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
