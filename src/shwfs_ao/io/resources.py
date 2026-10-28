"""Canonical access to package-installed fixtures, profiles, and schemas.

Packaged lookups are resolved exclusively with :mod:`importlib.resources`.
Explicit absolute paths and files in the caller's current directory remain
supported for the legacy data-loading APIs, but there is deliberately no
repository-root discovery or source-checkout fallback.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
import hashlib
from importlib import resources
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, BinaryIO, TextIO


RESOURCE_PACKAGE = "shwfs_ao.resources"
# Frozen compatibility name. Resource resolution no longer consults a
# repository root, so the only honest value is ``None``.
SOURCE_REPOSITORY_ROOT = None
RESOURCE_MANIFEST_NAME = "resource_manifest.json"
_LOWER_HEX = frozenset("0123456789abcdef")


class ResourceError(ValueError):
    """Raised when a packaged resource name or manifest is invalid."""


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ResourceError(f"Duplicate key {key!r} in resource manifest.")
        result[key] = value
    return result


def normalized_resource_name(path: str | Path) -> str:
    """Return one safe package-relative resource key.

    The historical ``data/`` prefix is accepted during the compatibility
    window. Absolute paths are intentionally rejected here; callers that
    accept explicit files handle them before requesting a package key.
    """

    raw = str(path)
    if not raw or "\x00" in raw or "\\" in raw:
        raise ValueError(f"Invalid package resource path: {path!r}.")
    candidate = Path(raw)
    if candidate.is_absolute():
        raise ValueError(f"Invalid package resource path: {path!r}.")
    parts = candidate.parts
    if parts and parts[0] == "data":
        parts = parts[1:]
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"Invalid package resource path: {path!r}.")
    return "/".join(parts)


def package_resource(path: str | Path):
    """Return the traversable for a validated canonical resource name."""

    logical_name = normalized_resource_name(path)
    return resources.files(RESOURCE_PACKAGE).joinpath(*logical_name.split("/"))


def resource_exists(path: str | Path) -> bool:
    """Return whether an explicit file or canonical package resource exists."""

    candidate = Path(path)
    if candidate.is_absolute() or candidate.is_file():
        return candidate.is_file()
    try:
        return package_resource(candidate).is_file()
    except (ModuleNotFoundError, ValueError):
        return False


@contextmanager
def open_text_resource(
    path: str | Path,
    *,
    encoding: str = "utf-8",
    newline: str | None = None,
) -> Iterator[TextIO]:
    """Open an explicit text file or an installed canonical resource."""

    candidate = Path(path)
    if candidate.is_absolute() or candidate.is_file():
        if not candidate.is_file():
            raise FileNotFoundError(f"Runtime resource was not found: {path!r}.")
        with candidate.open("r", encoding=encoding, newline=newline) as handle:
            yield handle
        return

    traversable = package_resource(candidate)
    if not traversable.is_file():
        raise FileNotFoundError(f"Runtime resource was not found: {path!r}.")
    with traversable.open("r", encoding=encoding, newline=newline) as handle:
        yield handle


@contextmanager
def open_binary_resource(path: str | Path) -> Iterator[BinaryIO]:
    """Open one installed canonical resource as bytes."""

    traversable = package_resource(path)
    if not traversable.is_file():
        raise FileNotFoundError(f"Runtime resource was not found: {path!r}.")
    with traversable.open("rb") as handle:
        yield handle


def read_text_resource(path: str | Path, *, encoding: str = "utf-8") -> str:
    """Read one installed canonical text resource."""

    traversable = package_resource(path)
    if not traversable.is_file():
        raise FileNotFoundError(f"Runtime resource was not found: {path!r}.")
    return traversable.read_text(encoding=encoding)


def read_binary_resource(path: str | Path) -> bytes:
    """Read one installed canonical binary resource."""

    traversable = package_resource(path)
    if not traversable.is_file():
        raise FileNotFoundError(f"Runtime resource was not found: {path!r}.")
    return traversable.read_bytes()


def load_resource_manifest(*, verify_payloads: bool = True) -> Mapping[str, Any]:
    """Load the checked manifest and optionally verify every packaged payload."""

    try:
        payload = json.loads(
            package_resource(RESOURCE_MANIFEST_NAME).read_text(encoding="utf-8"),
            object_pairs_hook=_unique_json_object,
        )
    except (json.JSONDecodeError, OSError) as exc:
        raise ResourceError("Canonical resource manifest is unreadable.") from exc
    if not isinstance(payload, dict):
        raise ResourceError("Canonical resource manifest must be a JSON object.")
    if set(payload) != {"schema_name", "schema_version", "resources"}:
        raise ResourceError(
            "Canonical resource manifest must contain exactly schema_name, "
            "schema_version, and resources."
        )
    if payload.get("schema_name") != "shwfs_ao.resource_manifest":
        raise ResourceError("Canonical resource manifest has an invalid schema_name.")
    if type(payload.get("schema_version")) is not int or payload["schema_version"] != 1:
        raise ResourceError("Canonical resource manifest has an unsupported schema_version.")
    records = payload.get("resources")
    if not isinstance(records, list):
        raise ResourceError("Canonical resource manifest resources must be a list.")
    logical_names: list[str] = []
    for record in records:
        if not isinstance(record, dict) or set(record) != {"logical_name", "sha256"}:
            raise ResourceError("Canonical resource manifest contains an invalid record.")
        if not isinstance(record["logical_name"], str):
            raise ResourceError("Canonical resource logical_name must be text.")
        logical_name = normalized_resource_name(record["logical_name"])
        digest = record["sha256"]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in _LOWER_HEX for character in digest)
        ):
            raise ResourceError(
                f"Canonical resource manifest has an invalid hash for {logical_name!r}."
            )
        logical_names.append(logical_name)
        if verify_payloads:
            try:
                actual = hashlib.sha256(package_resource(logical_name).read_bytes()).hexdigest()
            except (ModuleNotFoundError, OSError) as exc:
                raise ResourceError(
                    f"Canonical resource {logical_name!r} is absent."
                ) from exc
            if actual != digest:
                raise ResourceError(
                    f"Canonical resource {logical_name!r} has SHA-256 {actual}, "
                    f"expected {digest}."
                )
    if logical_names != sorted(logical_names) or len(logical_names) != len(set(logical_names)):
        raise ResourceError("Canonical resource manifest names must be unique and sorted.")
    if verify_payloads:
        actual_names = _package_resource_names()
        expected_names = set(logical_names) | {RESOURCE_MANIFEST_NAME}
        if actual_names != expected_names:
            raise ResourceError(
                "Canonical package inventory differs from its manifest: "
                f"missing={sorted(expected_names - actual_names)!r}, "
                f"untracked={sorted(actual_names - expected_names)!r}."
            )
    return MappingProxyType(payload)


def _package_resource_names() -> set[str]:
    root = resources.files(RESOURCE_PACKAGE)
    names: set[str] = set()

    def visit(directory, prefix: str) -> None:
        for child in directory.iterdir():
            logical_name = f"{prefix}/{child.name}" if prefix else child.name
            if child.is_dir():
                if child.name != "__pycache__":
                    visit(child, logical_name)
            elif child.is_file() and not logical_name.endswith((".pyc", ".pyo")):
                names.add(logical_name)

    visit(root, "")
    return names


def render_resource_manifest(source_root: Path) -> str:
    """Render deterministic manifest text for an explicit canonical tree.

    This is a pure maintenance helper: it returns text and never writes files.
    Build and runtime reads continue to validate the checked manifest.
    """

    records: list[dict[str, str]] = []
    for path in sorted(source_root.rglob("*")):
        if (
            not path.is_file()
            or "__pycache__" in path.parts
            or path.suffix in {".pyc", ".pyo"}
            or path.name == RESOURCE_MANIFEST_NAME
        ):
            continue
        records.append(
            {
                "logical_name": path.relative_to(source_root).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return json.dumps(
        {
            "schema_name": "shwfs_ao.resource_manifest",
            "schema_version": 1,
            "resources": records,
        },
        indent=2,
        ensure_ascii=False,
    ) + "\n"


__all__ = (
    "RESOURCE_PACKAGE",
    "SOURCE_REPOSITORY_ROOT",
    "RESOURCE_MANIFEST_NAME",
    "ResourceError",
    "normalized_resource_name",
    "package_resource",
    "resource_exists",
    "open_text_resource",
    "open_binary_resource",
    "read_text_resource",
    "read_binary_resource",
    "load_resource_manifest",
    "render_resource_manifest",
)
