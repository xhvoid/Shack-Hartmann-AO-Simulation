"""Generate the deprecated resource-package alias in the build directory.

``src/shwfs_ao/resources`` is the sole maintained resource tree.  This custom
``build_py`` command verifies its checked manifest and copies the exact bytes
to ``ao_simulation_data`` under ``build_lib`` for the compatibility window.
It never creates or updates an alias package in the source checkout.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
from typing import NamedTuple

from setuptools.command.editable_wheel import editable_wheel
from setuptools.command.build_py import build_py
from setuptools.errors import SetupError


CANONICAL_PACKAGE = "shwfs_ao.resources"
ALIAS_PACKAGE = "ao_simulation_data"
MANIFEST_NAME = "resource_manifest.json"
MANIFEST_SCHEMA_NAME = "shwfs_ao.resource_manifest"
MANIFEST_SCHEMA_VERSION = 1


class ResourceManifestError(SetupError):
    """Raised when canonical resources do not match the checked manifest."""


class ResourceRecord(NamedTuple):
    logical_name: str
    sha256: str


def collect_resource_records(source_root: Path) -> tuple[ResourceRecord, ...]:
    """Hash the complete canonical inventory, excluding the manifest itself."""

    records = []
    for path in sorted(source_root.rglob("*")):
        if (
            not path.is_file()
            or "__pycache__" in path.parts
            or path.suffix in {".pyc", ".pyo"}
            or path.name == MANIFEST_NAME
        ):
            continue
        records.append(
            ResourceRecord(
                path.relative_to(source_root).as_posix(),
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        )
    return tuple(records)


def render_resource_manifest(source_root: Path) -> str:
    """Return the deterministic checked-manifest text for ``source_root``."""

    payload = {
        "schema_name": MANIFEST_SCHEMA_NAME,
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "resources": [
            {"logical_name": record.logical_name, "sha256": record.sha256}
            for record in collect_resource_records(source_root)
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ResourceManifestError(
                f"Duplicate key {key!r} in canonical resource manifest."
            )
        result[key] = value
    return result


def _safe_logical_name(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ResourceManifestError(f"Invalid canonical resource name: {value!r}.")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or str(path) != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ResourceManifestError(f"Invalid canonical resource name: {value!r}.")
    if value == MANIFEST_NAME:
        raise ResourceManifestError(
            f"{MANIFEST_NAME!r} cannot include its own content hash."
        )
    return value


def load_checked_manifest(source_root: Path) -> tuple[ResourceRecord, ...]:
    """Validate and return the sorted records from one canonical source tree."""

    manifest_path = source_root / MANIFEST_NAME
    try:
        payload = json.loads(
            manifest_path.read_text(encoding="utf-8"),
            object_pairs_hook=_json_object,
        )
    except ResourceManifestError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise ResourceManifestError(
            f"Cannot read canonical resource manifest {manifest_path}: {exc}"
        ) from exc
    if not isinstance(payload, dict) or set(payload) != {
        "schema_name",
        "schema_version",
        "resources",
    }:
        raise ResourceManifestError(
            "Canonical resource manifest must contain exactly schema_name, "
            "schema_version, and resources."
        )
    if payload["schema_name"] != MANIFEST_SCHEMA_NAME:
        raise ResourceManifestError(
            f"Canonical resource manifest schema_name must be {MANIFEST_SCHEMA_NAME!r}."
        )
    if (
        type(payload["schema_version"]) is not int
        or payload["schema_version"] != MANIFEST_SCHEMA_VERSION
    ):
        raise ResourceManifestError(
            "Canonical resource manifest schema_version must be "
            f"{MANIFEST_SCHEMA_VERSION}."
        )
    raw_records = payload["resources"]
    if not isinstance(raw_records, list):
        raise ResourceManifestError("Canonical resource manifest resources must be a list.")

    records: list[ResourceRecord] = []
    for raw in raw_records:
        if not isinstance(raw, dict) or set(raw) != {"logical_name", "sha256"}:
            raise ResourceManifestError(
                "Each canonical resource record must contain exactly logical_name and sha256."
            )
        name = _safe_logical_name(raw["logical_name"])
        digest = raw["sha256"]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise ResourceManifestError(
                f"Invalid SHA-256 for canonical resource {name!r}."
            )
        records.append(ResourceRecord(name, digest))

    names = [record.logical_name for record in records]
    if names != sorted(names) or len(names) != len(set(names)):
        raise ResourceManifestError(
            "Canonical resource manifest names must be unique and sorted."
        )
    expected_files = {record.logical_name for record in records} | {MANIFEST_NAME}
    actual_files = {
        path.relative_to(source_root).as_posix()
        for path in source_root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    }
    if actual_files != expected_files:
        missing = sorted(expected_files - actual_files)
        untracked = sorted(actual_files - expected_files)
        raise ResourceManifestError(
            "Canonical resource inventory differs from its manifest: "
            f"missing={missing!r}, untracked={untracked!r}."
        )
    for record in records:
        actual_hash = hashlib.sha256(
            (source_root / record.logical_name).read_bytes()
        ).hexdigest()
        if actual_hash != record.sha256:
            raise ResourceManifestError(
                f"Canonical resource {record.logical_name!r} has SHA-256 "
                f"{actual_hash}, expected {record.sha256}."
            )
    return tuple(records)


def _copy_resource_alias(source_root: Path, alias_root: Path) -> tuple[Path, ...]:
    records = load_checked_manifest(source_root)
    if alias_root.exists():
        shutil.rmtree(alias_root)
    names = [record.logical_name for record in records] + [MANIFEST_NAME]
    outputs = tuple(alias_root / name for name in names)
    for name, target in zip(names, outputs, strict=True):
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_root / name, target)
    return outputs


class BuildPyWithResourceAlias(build_py):
    """Build canonical package data and one byte-identical installed alias."""

    def _canonical_source_root(self) -> Path:
        return Path(self.get_package_dir(CANONICAL_PACKAGE))

    def _alias_output_paths(self) -> tuple[Path, ...]:
        records = load_checked_manifest(self._canonical_source_root())
        alias_root = Path(self.build_lib) / ALIAS_PACKAGE
        names = [record.logical_name for record in records] + [MANIFEST_NAME]
        return tuple(alias_root / name for name in names)

    def run(self) -> None:
        super().run()
        source_root = self._canonical_source_root()
        alias_root = Path(self.build_lib) / ALIAS_PACKAGE
        _copy_resource_alias(source_root, alias_root)

    def get_outputs(self, include_bytecode: bool = True) -> list[str]:
        outputs = super().get_outputs(include_bytecode=include_bytecode)
        return [*outputs, *(str(path) for path in self._alias_output_paths())]


class EditableWheelWithResourceAlias(editable_wheel):
    """Include the generated alias directly in a PEP 660 editable wheel."""

    def _run_build_commands(self, dist_name, unpacked_wheel, build_lib, tmp_dir):
        files, mapping = super()._run_build_commands(
            dist_name,
            unpacked_wheel,
            build_lib,
            tmp_dir,
        )
        build_py_command = self.get_finalized_command("build_py")
        source_root = Path(build_py_command.get_package_dir(CANONICAL_PACKAGE))
        _copy_resource_alias(
            source_root,
            Path(unpacked_wheel) / ALIAS_PACKAGE,
        )
        return files, mapping


__all__ = (
    "ALIAS_PACKAGE",
    "CANONICAL_PACKAGE",
    "MANIFEST_NAME",
    "MANIFEST_SCHEMA_NAME",
    "MANIFEST_SCHEMA_VERSION",
    "ResourceManifestError",
    "ResourceRecord",
    "collect_resource_records",
    "render_resource_manifest",
    "load_checked_manifest",
    "BuildPyWithResourceAlias",
    "EditableWheelWithResourceAlias",
)
