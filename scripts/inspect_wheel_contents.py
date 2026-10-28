#!/usr/bin/env python3
"""Inspect a built wheel and compare it against an sdist-rebuilt wheel.

AO-REF-020 packaging gate.  The primary wheel and a wheel rebuilt from the
sdist in a clean directory must carry the same file list and byte-identical
canonical resource manifests, and the primary wheel must contain every
compatibility top-level module from ``pyproject.toml`` plus the packaged
schemas, fixtures, and runtime resources the installed package loads.

Usage::

    python scripts/inspect_wheel_contents.py --wheel A.whl --rebuilt-wheel B.whl
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tomllib
import zipfile

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RESOURCE_MANIFEST_NAME = "shwfs_ao/resources/resource_manifest.json"
REQUIRED_RESOURCE_PREFIXES = (
    "shwfs_ao/resources/schemas/",
    "shwfs_ao/resources/samples/",
    "shwfs_ao/resources/reference_metrics/",
    "shwfs_ao/resources/synthetic_presets/",
    "shwfs_ao/resources/public/",
)


class WheelInspectionError(ValueError):
    """Raised when a wheel fails the AO-REF-020 packaging inspection."""


def _names(wheel_path: Path) -> set[str]:
    with zipfile.ZipFile(wheel_path) as archive:
        return set(archive.namelist())


def _read(wheel_path: Path, member: str) -> bytes:
    with zipfile.ZipFile(wheel_path) as archive:
        return archive.read(member)


def _compatibility_modules() -> list[str]:
    pyproject = tomllib.loads(
        (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    return list(pyproject["tool"]["setuptools"]["py-modules"])


def inspect_wheels(wheel_path: Path, rebuilt_wheel_path: Path) -> None:
    names = _names(wheel_path)
    rebuilt_names = _names(rebuilt_wheel_path)
    if names != rebuilt_names:
        missing = sorted(names - rebuilt_names)[:10]
        extra = sorted(rebuilt_names - names)[:10]
        raise WheelInspectionError(
            "The sdist-rebuilt wheel does not match the primary wheel: "
            f"missing from rebuild {missing}; extra in rebuild {extra}."
        )

    if RESOURCE_MANIFEST_NAME not in names:
        raise WheelInspectionError(
            f"The wheel does not package {RESOURCE_MANIFEST_NAME}."
        )
    if _read(wheel_path, RESOURCE_MANIFEST_NAME) != _read(
        rebuilt_wheel_path, RESOURCE_MANIFEST_NAME
    ):
        raise WheelInspectionError(
            "The canonical resource manifest differs between the primary "
            "wheel and the sdist-rebuilt wheel."
        )

    for module in _compatibility_modules():
        member = f"{module}.py"
        if member not in names:
            raise WheelInspectionError(
                f"Compatibility module {member!r} is missing from the wheel."
            )

    for prefix in REQUIRED_RESOURCE_PREFIXES:
        if not any(
            name.startswith(prefix) and not name.endswith("/") for name in names
        ):
            raise WheelInspectionError(
                f"No packaged file under required resource prefix {prefix!r}."
            )

    # py.typed is currently not shipped; if it ever is, both wheels carry it
    # together thanks to the namelist equality above.


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--rebuilt-wheel", required=True, type=Path)
    arguments = parser.parse_args(argv)
    try:
        inspect_wheels(arguments.wheel.resolve(), arguments.rebuilt_wheel.resolve())
    except WheelInspectionError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(
        f"wheel inspection OK: {arguments.wheel.name} matches its sdist "
        "rebuild and carries the compatibility modules and resources."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
