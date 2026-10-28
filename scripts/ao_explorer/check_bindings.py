"""Bindings of every explorer bundle, checked offline before publication.

``data/current.json`` binds the active 2 m dataset (its top-level ``manifest``)
and one entry object per further bundle (``galaxy``, ``replay42``,
``dmStroke`` ... -- every object that names a ``manifest``).  The page verifies
each member's size and SHA-256 when a visitor's browser loads it; this check
does the same for every bundle at once, so that a changed, missing or stray
file is found before it is published:

- the entry is strict JSON (no NaN or Infinity) of schema ``ao-explorer.entry.v1``;
- each bound manifest lies inside the site, is a regular file with the size and
  SHA-256 the entry records, is strict JSON and names a schema;
- the identity the entry records (``dataset_id``, ``derived_id``,
  ``recording_id`` or ``id``) equals the manifest's and the name of the
  manifest's directory;
- every listed member (a ``files`` map or a ``members`` list, relative to the
  manifest) and every other hash-bound reference in the manifest (an object
  with ``sha256``, ``bytes`` and ``href`` or ``path``) is a regular file inside
  the site with that size and SHA-256, and no two records of one file disagree;
- the manifest's own directory holds no unlisted file and no symlink (members
  listed in place elsewhere are verified, but their directories are not owned);
- no two entries own the same directory.

Directories under ``data/``, ``derived/`` and ``recordings/`` that no entry
owns are listed for information (preserved earlier datasets and superseded
derivatives); they are not failures.  This checks bindings only: the content
semantics of a bundle belong to its exporter and to ``validate.py``.  Nothing
is simulated, rewritten or fetched.

Usage::

    python scripts/ao_explorer/check_bindings.py --web-dir web/ao-explorer [--report PATH]

Exit status 0 means every binding holds; 1 lists the problems; 2 means the
entry itself could not be read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, Iterator, List, Optional, Tuple


ENTRY_SCHEMA = "ao-explorer.entry.v1"
IDENTITY_KEYS = ("dataset_id", "derived_id", "recording_id", "id")
BUNDLE_ROOTS = ("data", "derived", "recordings")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class BindingError(RuntimeError):
    pass


def _strict_json(data: bytes, label: str) -> Any:
    def reject(value: str) -> Any:
        raise BindingError(f"{label}: non-finite JSON constant {value}")

    try:
        return json.loads(data.decode("utf-8"), parse_constant=reject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BindingError(f"{label}: invalid JSON ({exc})") from exc


class _Digests:
    """Size and SHA-256 of each file, streamed once however often it is referenced."""

    def __init__(self) -> None:
        self.cache: Dict[Path, Tuple[int, str]] = {}

    def __call__(self, path: Path) -> Tuple[int, str]:
        if path not in self.cache:
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(block)
            self.cache[path] = (path.stat().st_size, digest.hexdigest())
        return self.cache[path]


def bound_entries(entry: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    """The entry's bindings: the dataset first, then every object that names a manifest."""

    dataset = {key: entry.get(key) for key in ("manifest", "manifest_bytes", "manifest_sha256", "dataset_id")}
    return [("dataset", dataset)] + [(key, value) for key, value in entry.items()
                                     if isinstance(value, dict) and "manifest" in value]


def _references(value: Any, where: str = "") -> Iterator[Tuple[str, str, Dict[str, Any]]]:
    """(location, relative path, record) of every hash-bound reference inside a manifest."""

    if isinstance(value, dict):
        target = value.get("href", value.get("path"))
        if isinstance(target, str) and "sha256" in value and "bytes" in value:
            yield where or "/", target, value
        for key, item in value.items():
            yield from _references(item, f"{where}/{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _references(item, f"{where}/{index}")


def _members(manifest: Dict[str, Any]) -> Optional[List[Tuple[str, str, Dict[str, Any]]]]:
    files, members = manifest.get("files"), manifest.get("members")
    if isinstance(files, dict) and files:
        return [(f"/files/{name}", name, record) for name, record in files.items()]
    if isinstance(members, list) and members:
        return [(f"/members/{index}", item.get("path"), item) for index, item in enumerate(members)]
    return None


def _inside(site: Path, path: Path) -> bool:
    return path == site or site in path.parents


def check_bundle(site: Path, name: str, binding: Dict[str, Any], digests: _Digests) -> Dict[str, Any]:
    entry_dir = site / "data"
    problems: List[str] = []
    result: Dict[str, Any] = {"manifest": binding.get("manifest"), "problems": problems, "listed": set(), "directory": None}

    def fail(message: str) -> None:
        problems.append(f"{name}: {message}")

    if not isinstance(binding.get("manifest"), str):
        fail("the entry names no manifest path")
        return result
    if not isinstance(binding.get("manifest_bytes"), int) or not _SHA256.match(str(binding.get("manifest_sha256"))):
        fail("the entry records no manifest size or SHA-256")
        return result
    if name != "dataset" and not isinstance(binding.get("schema"), str):
        fail("the entry object names no schema")
    identity_key = next((key for key in IDENTITY_KEYS if key in binding), None)
    if identity_key is None:
        fail(f"the entry records no identity ({', '.join(IDENTITY_KEYS)})")
    manifest_path = (entry_dir / binding["manifest"]).resolve()
    if not _inside(site, manifest_path):
        fail(f"manifest {binding['manifest']} lies outside the site")
        return result
    if manifest_path.is_symlink() or not manifest_path.is_file():
        fail(f"manifest {binding['manifest']} is missing or not a regular file")
        return result
    size, sha = digests(manifest_path)
    if size != binding["manifest_bytes"] or sha != binding["manifest_sha256"]:
        fail(f"manifest has {size} bytes / SHA-256 {sha[:12]}…; the entry records {binding['manifest_bytes']} / {str(binding['manifest_sha256'])[:12]}…")
        return result
    try:
        manifest = _strict_json(manifest_path.read_bytes(), f"{name} manifest")
    except BindingError as exc:
        fail(str(exc))
        return result
    directory = manifest_path.parent
    result.update(directory=directory, schema=manifest.get("schema"))
    if not isinstance(manifest.get("schema"), str):
        fail("the manifest names no schema")
    if identity_key is not None:
        recorded = binding[identity_key]
        result["identity"] = recorded
        if manifest.get(identity_key) != recorded:
            fail(f"manifest {identity_key} {manifest.get(identity_key)!r} differs from the entry's {recorded!r}")
        if directory.name != recorded:
            fail(f"directory {directory.name} is not named after the identity {recorded!r}")
    members = _members(manifest)
    if members is None:
        fail("the manifest lists no members (neither a non-empty files map nor a members list)")
        members = []
    records: Dict[Path, Tuple[int, str, str]] = {}
    for where, relative, record in members + list(_references(manifest)):
        if not isinstance(relative, str) or not relative:
            fail(f"{where}: a member without a path")
            continue
        path = (directory / relative).resolve()
        if not _inside(site, path):
            fail(f"{where}: {relative} lies outside the site")
            continue
        recorded = (record.get("bytes"), record.get("sha256"), where)
        if path in records and records[path][:2] != recorded[:2]:
            fail(f"{where}: {relative} is recorded with a different size or SHA-256 at {records[path][2]}")
            continue
        records[path] = recorded
    for path, (size_recorded, sha_recorded, where) in records.items():
        shown = path.relative_to(site).as_posix()
        if path.is_symlink() or not path.is_file():
            fail(f"{where}: {shown} is missing or not a regular file")
            continue
        size, sha = digests(path)
        if size != size_recorded or sha != sha_recorded:
            fail(f"{where}: {shown} has {size} bytes / SHA-256 {sha[:12]}…; the manifest records {size_recorded} / {str(sha_recorded)[:12]}…")
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            fail(f"symlink {path.relative_to(site).as_posix()} inside the bundle directory")
        elif path.is_file() and path != manifest_path and path.resolve() not in records:
            fail(f"unlisted file {path.relative_to(site).as_posix()} in the bundle directory")
    result["listed"] = set(records)
    result["members"] = len(records)
    result["bytes"] = sum(digests.cache[path][0] for path in records if path in digests.cache)
    return result


def check(web_dir: Path) -> Dict[str, Any]:
    """Every binding of the site and every problem found (an empty list means all bindings hold)."""

    site = Path(web_dir).resolve()
    entry_path = site / "data" / "current.json"
    entry = _strict_json(entry_path.read_bytes(), "data/current.json")
    if not isinstance(entry, dict) or entry.get("schema") != ENTRY_SCHEMA:
        raise BindingError(f"data/current.json is not an {ENTRY_SCHEMA} entry")
    digests = _Digests()
    problems: List[str] = []
    bundles: Dict[str, Dict[str, Any]] = {}
    owners: Dict[Path, str] = {}
    referenced: set = set()
    for name, binding in bound_entries(entry):
        result = check_bundle(site, name, binding, digests)
        problems += result["problems"]
        directory = result["directory"]
        if directory is not None:
            if directory in owners:
                problems.append(f"{name}: directory {directory.relative_to(site).as_posix()} is also owned by {owners[directory]}")
            owners[directory] = name
        referenced |= result["listed"]
        bundles[name] = {"manifest": result["manifest"], "schema": result.get("schema"), "identity": result.get("identity"),
                         "directory": None if directory is None else directory.relative_to(site).as_posix(),
                         "members": result.get("members", 0), "bytes": result.get("bytes", 0), "problems": result["problems"]}
    unbound = []
    for root in BUNDLE_ROOTS:
        for directory in sorted(path for path in (site / root).iterdir() if path.is_dir()) if (site / root).is_dir() else []:
            if directory.resolve() not in owners:
                files = [path.resolve() for path in directory.rglob("*") if path.is_file()]
                unbound.append({"directory": directory.relative_to(site).as_posix(), "files": len(files),
                                "files_referenced_by_bound_manifests": sum(path in referenced for path in files)})
    return {"site": str(site), "bundles": bundles, "unbound_directories": unbound, "problems": problems,
            "files_hashed": len(digests.cache), "bytes_hashed": sum(size for size, _ in digests.cache.values())}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--web-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, help="also write the full report as JSON")
    arguments = parser.parse_args(argv)
    try:
        report = check(arguments.web_dir)
    except (OSError, BindingError) as exc:
        print(json.dumps({"bindings_hold": False, "error": str(exc)}))
        return 2
    if arguments.report:
        arguments.report.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    summary = {"bindings_hold": not report["problems"], "bundles": {name: {"identity": b["identity"], "members": b["members"]} for name, b in report["bundles"].items()},
               "files_hashed": report["files_hashed"], "bytes_hashed": report["bytes_hashed"],
               "unbound_directories": [u["directory"] for u in report["unbound_directories"]], "problems": report["problems"]}
    print(json.dumps(summary, indent=1))
    return 0 if not report["problems"] else 1


if __name__ == "__main__":
    sys.exit(main())
