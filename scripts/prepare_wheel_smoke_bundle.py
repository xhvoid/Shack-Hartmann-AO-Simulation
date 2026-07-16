#!/usr/bin/env python3
"""Prepare a portable wheel-smoke bundle from the checked manifest.

The bundle is a temporary directory containing only manifest-listed portable
tests (plus, in later tickets, offline fixtures and example scripts) and a
root ``pytest.ini``.  Running pytest inside it exercises the *installed*
wheel: the preparer refuses to copy ``src/``, ``.git/``, or any packaged
resource source tree, so an import that silently falls back to the checkout
cannot pass.

Usage:

    python scripts/prepare_wheel_smoke_bundle.py --output DIR [--include-hcipy]

Entries whose ``requires`` list names ``hcipy`` are copied only when
``--include-hcipy`` is passed; everything else is always copied.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import shutil
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPOSITORY_ROOT / "tests" / "wheel_smoke" / "manifest.json"
MANIFEST_SCHEMA_NAME = "shwfs_ao.wheel_smoke_bundle_manifest"
MANIFEST_SCHEMA_VERSION = 1

_ALLOWED_SOURCE_PREFIXES = ("tests", "examples")
_FORBIDDEN_SOURCE_PREFIXES = ("src", ".git")
_KNOWN_KINDS = frozenset({"test", "example", "fixture"})
_KNOWN_REQUIREMENTS = frozenset({"hcipy"})


class BundleManifestError(ValueError):
    """Raised when the wheel-smoke manifest or an entry is invalid."""


def _safe_relative_source(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise BundleManifestError(f"Invalid bundle source path: {value!r}.")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or str(path) != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise BundleManifestError(f"Invalid bundle source path: {value!r}.")
    if path.parts[0] in _FORBIDDEN_SOURCE_PREFIXES:
        raise BundleManifestError(
            f"Bundle sources must never come from {path.parts[0]!r}: the smoke "
            "bundle exists to prove the installed wheel works without the "
            "source tree."
        )
    if path.parts[0] not in _ALLOWED_SOURCE_PREFIXES:
        raise BundleManifestError(
            f"Bundle source {value!r} is outside the allowed prefixes "
            f"{list(_ALLOWED_SOURCE_PREFIXES)}."
        )
    if path.parts[:2] == ("tests", "wheel_smoke"):
        raise BundleManifestError(
            "Bundle entries must not copy tests/wheel_smoke itself; the "
            "pytest_ini field owns that file."
        )
    return path


def load_manifest(manifest_path: Path) -> tuple[PurePosixPath, list[dict]]:
    """Validate the manifest; return the pytest.ini path and its entries."""

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleManifestError(
            f"Cannot read wheel-smoke manifest {manifest_path}: {exc}"
        ) from exc
    if not isinstance(payload, dict) or set(payload) != {
        "schema_name",
        "schema_version",
        "pytest_ini",
        "entries",
    }:
        raise BundleManifestError(
            "Wheel-smoke manifest must contain exactly schema_name, "
            "schema_version, pytest_ini, and entries."
        )
    if payload["schema_name"] != MANIFEST_SCHEMA_NAME:
        raise BundleManifestError(
            f"Wheel-smoke manifest schema_name must be {MANIFEST_SCHEMA_NAME!r}."
        )
    if (
        type(payload["schema_version"]) is not int
        or payload["schema_version"] != MANIFEST_SCHEMA_VERSION
    ):
        raise BundleManifestError(
            f"Wheel-smoke manifest schema_version must be {MANIFEST_SCHEMA_VERSION}."
        )

    pytest_ini = payload["pytest_ini"]
    if pytest_ini != "tests/wheel_smoke/pytest.ini":
        raise BundleManifestError(
            "pytest_ini must be 'tests/wheel_smoke/pytest.ini'."
        )

    raw_entries = payload["entries"]
    if not isinstance(raw_entries, list) or not raw_entries:
        raise BundleManifestError("entries must be a non-empty list.")
    entries: list[dict] = []
    seen_sources: set[str] = set()
    for raw in raw_entries:
        if not isinstance(raw, dict) or set(raw) != {"source", "kind", "requires"}:
            raise BundleManifestError(
                "Each entry must contain exactly source, kind, and requires."
            )
        source = _safe_relative_source(raw["source"])
        if str(source) in seen_sources:
            raise BundleManifestError(f"Duplicate bundle source {str(source)!r}.")
        seen_sources.add(str(source))
        if raw["kind"] not in _KNOWN_KINDS:
            raise BundleManifestError(
                f"Unknown bundle entry kind {raw['kind']!r} for {str(source)!r}."
            )
        requires = raw["requires"]
        if not isinstance(requires, list) or any(
            item not in _KNOWN_REQUIREMENTS for item in requires
        ):
            raise BundleManifestError(
                f"requires for {str(source)!r} may only name "
                f"{sorted(_KNOWN_REQUIREMENTS)}."
            )
        entries.append(
            {"source": source, "kind": raw["kind"], "requires": tuple(requires)}
        )
    return PurePosixPath(pytest_ini), entries


def prepare_bundle(
    output_dir: Path,
    *,
    include_hcipy: bool,
    manifest_path: Path = MANIFEST_PATH,
) -> list[Path]:
    """Copy the selected manifest entries into a fresh bundle directory."""

    pytest_ini, entries = load_manifest(manifest_path)
    if output_dir.exists():
        if not output_dir.is_dir() or any(output_dir.iterdir()):
            raise BundleManifestError(
                f"Bundle output directory {output_dir} must be absent or empty."
            )
    else:
        output_dir.mkdir(parents=True)

    selected = [
        entry
        for entry in entries
        if include_hcipy or "hcipy" not in entry["requires"]
    ]
    if not selected:
        raise BundleManifestError(
            "The selected bundle would be empty; refusing to prepare it."
        )

    written: list[Path] = []
    ini_source = REPOSITORY_ROOT / Path(*pytest_ini.parts)
    if not ini_source.is_file():
        raise BundleManifestError(f"Missing bundle pytest.ini: {ini_source}.")
    ini_target = output_dir / "pytest.ini"
    shutil.copyfile(ini_source, ini_target)
    written.append(ini_target)

    for entry in selected:
        source = REPOSITORY_ROOT / Path(*entry["source"].parts)
        if not source.is_file():
            raise BundleManifestError(
                f"Manifest bundle source is missing: {entry['source']}."
            )
        target = output_dir / Path(*entry["source"].parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        written.append(target)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="absent-or-empty directory that receives the bundle",
    )
    parser.add_argument(
        "--include-hcipy",
        action="store_true",
        help="also copy entries that require the optional HCIPy dependency",
    )
    arguments = parser.parse_args(argv)
    try:
        written = prepare_bundle(
            arguments.output.resolve(),
            include_hcipy=arguments.include_hcipy,
        )
    except BundleManifestError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
