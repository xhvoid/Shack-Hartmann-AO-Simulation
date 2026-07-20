"""The constraint profiles are complete environment locks (AO-REF-020).

``scripts/verify_environment_lock.py`` fails any environment containing a
distribution its profile does not pin exactly; the CI lanes run it after
every install.  These tests exercise the parser and verifier functions and
the CLI end-to-end against the running environment's own freeze, so they
hold in every lane regardless of which profile that lane installs.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_environment_lock.py"

# scripts/ is a path-addressed tool directory, not an importable package;
# loading by file keeps collection working under both `python -m pytest`
# (repository root on sys.path) and the bare `pytest` entry point.
_LOCK_SPEC = importlib.util.spec_from_file_location(
    "verify_environment_lock_for_tests",
    SCRIPT,
)
assert _LOCK_SPEC is not None and _LOCK_SPEC.loader is not None
lock = importlib.util.module_from_spec(_LOCK_SPEC)
sys.modules[_LOCK_SPEC.name] = lock
_LOCK_SPEC.loader.exec_module(lock)


def test_pin_parsing_ignores_comments_markers_and_options():
    pins = lock.parse_constraint_pins(
        "# resolved profile\n"
        "numpy==2.5.0\n"
        "ruff==0.14.0  # inline comment\n"
        "Astropy_IERS-data==1.0\n"
        "packaging==26.0 ; python_version >= '3.9'\n"
        "-e git+https://example.invalid/repo.git#egg=self\n"
        "--find-links wheels/\n"
    )
    assert pins == {
        "numpy": "2.5.0",
        "ruff": "0.14.0",
        "astropy-iers-data": "1.0",
        "packaging": "26.0",
    }


def test_verify_names_unpinned_and_mismatched_distributions():
    pins = {"numpy": "2.5.0", "scipy": "1.18.0"}
    installed = {"numpy": "2.5.0", "scipy": "1.17.0", "tornado": "6.5.7"}
    violations = lock.verify(pins, installed)
    assert len(violations) == 2
    assert any("scipy" in v and "1.17.0" in v and "1.18.0" in v for v in violations)
    assert any("tornado" in v and "does not pin" in v for v in violations)
    assert lock.verify(pins, {"numpy": "2.5.0"}) == []


def test_resolver_and_project_are_outside_the_lock_scope():
    installed = lock.installed_distributions()
    assert "pip" not in installed
    assert "shack-hartmann-ao-simulation" not in installed


def test_cli_round_trips_the_environment_freeze(tmp_path):
    emitted = subprocess.run(
        [sys.executable, str(SCRIPT), "--emit"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "==" in emitted

    profile = tmp_path / "freeze.txt"
    profile.write_text(emitted, encoding="utf-8")
    clean = subprocess.run(
        [sys.executable, str(SCRIPT), "--constraints", str(profile)],
        capture_output=True,
        text=True,
    )
    assert clean.returncode == 0, clean.stderr

    lines = emitted.splitlines()
    name, _, version = lines[0].partition("==")
    lines[0] = f"{name}==0.0.0.dev0"
    profile.write_text("\n".join(lines) + "\n", encoding="utf-8")
    drifted = subprocess.run(
        [sys.executable, str(SCRIPT), "--constraints", str(profile)],
        capture_output=True,
        text=True,
    )
    assert drifted.returncode == 1
    assert name in drifted.stderr
    assert "not a complete lock" in drifted.stderr
