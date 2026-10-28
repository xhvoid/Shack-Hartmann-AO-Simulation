#!/usr/bin/env python3
"""Move aside the leftovers of an interrupted study or series invocation (never delete).

Proposed in the post-T2 experiment packet (review round 1, finding 8).  Both
drivers publish atomically and refuse to run while leftovers are present:
``scripts/detector_level_convergence_study.py`` refuses any file in ``runs/``
that is not a planned run (temporary ``*.tmp-*`` files of an interrupted
publication included), and ``scripts/run_detector_level_evidence.py`` refuses
sidecar files of a traced record's stem that no retained run references
(orphans and ``*.npz.tmp-*`` files).  A resource-guard timeout stops the
process group with SIGTERM then SIGKILL, so such leftovers are expected after
an interrupted invocation, and so is a twin disk record under ``scratch/``.
The drivers say: move them aside.  This tool does exactly that:

* ``--study DIR``: a convergence-study output directory; candidates are
  ``DIR/runs/*.tmp-*`` and ``DIR/scratch/twin_pupil_samples_*.npy``;
* ``--record PATH``: a traced evidence record (``*.json``); candidates are
  ``<stem>__*.npz.tmp-*`` and ``<stem>__*.npz`` files in its directory that
  no run row of the record references (the record itself is read, never
  written; a record that does not exist yet has only temporary candidates).

Candidates are listed with size and SHA-256.  With ``--apply`` they are moved
(renamed, same filesystem) into ``<base>/leftovers/<UTC timestamp>/`` keeping
their relative paths, and a ``manifest.json`` records what moved and why.
Nothing is ever deleted or rewritten; a planned run file, a referenced
sidecar or a summary is never a candidate.  The quarantine directory sits
beside ``runs/`` (not inside it) and beside the record, where neither driver
looks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def study_candidates(directory: Path) -> list[tuple[Path, str]]:
    found: list[tuple[Path, str]] = []
    runs = directory / "runs"
    if runs.is_dir():
        for path in sorted(runs.iterdir()):
            if path.is_file() and ".tmp-" in path.name:
                found.append((path, "temporary file of an interrupted run publication in runs/"))
    scratch = directory / "scratch"
    if scratch.is_dir():
        for path in sorted(scratch.glob("twin_pupil_samples_*.npy")):
            if path.is_file():
                found.append((path, "twin arm disk record left by an interrupted paired run"))
    return found


def record_candidates(record_path: Path) -> list[tuple[Path, str]]:
    directory = record_path.parent
    stem = record_path.stem
    referenced: set[str] = set()
    if record_path.is_file():
        try:
            record = json.loads(record_path.read_text())
        except (OSError, ValueError) as exc:
            raise SystemExit(f"{record_path} is not readable JSON ({exc}); nothing is moved.")
        for row in record.get("runs", []):
            sidecar = row.get("sidecar") if isinstance(row, dict) else None
            if isinstance(sidecar, dict) and isinstance(sidecar.get("file"), str):
                referenced.add(sidecar["file"])
    found: list[tuple[Path, str]] = []
    for path in sorted(directory.glob(f"{stem}__*.npz*")):
        if not path.is_file():
            continue
        if ".tmp-" in path.name:
            found.append((path, "temporary file of an interrupted sidecar publication"))
        elif path.name not in referenced:
            found.append((path, "sidecar not referenced by any retained run of the record (orphan)"))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--study", type=Path, help="a convergence-study output directory (holds runs/ and scratch/)")
    target.add_argument("--record", type=Path, help="a traced evidence record whose sidecars sit beside it")
    parser.add_argument("--apply", action="store_true", help="move the candidates aside; without it only list them")
    arguments = parser.parse_args(argv)
    if arguments.study is not None:
        base = arguments.study.resolve()
        candidates = study_candidates(base)
    else:
        base = arguments.record.resolve().parent
        candidates = record_candidates(arguments.record.resolve())
    listing = [{"path": str(path), "relative": str(path.relative_to(base)), "bytes": path.stat().st_size, "sha256": _sha256(path), "reason": reason} for path, reason in candidates]
    if not candidates:
        print(json.dumps({"base": str(base), "candidates": [], "moved": False}))
        return 0
    if not arguments.apply:
        print(json.dumps({"base": str(base), "candidates": listing, "moved": False, "note": "pass --apply to move these aside; nothing is deleted"}, indent=1))
        return 0
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    quarantine = base / "leftovers" / stamp
    quarantine.mkdir(parents=True, exist_ok=False)
    moved: list[dict[str, Any]] = []
    for entry, (path, _) in zip(listing, candidates):
        destination = quarantine / entry["relative"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise SystemExit(f"{destination} exists; nothing more is moved.")
        path.rename(destination)
        moved.append({**entry, "moved_to": str(destination)})
    manifest = {"schema": "post_t2_quarantine_manifest.v1", "base": str(base), "moved_utc": stamp, "moved": moved, "deleted": []}
    (quarantine / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(json.dumps({"base": str(base), "quarantine": str(quarantine), "moved": len(moved)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
