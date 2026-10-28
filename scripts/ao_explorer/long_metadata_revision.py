"""Metadata revision of the active galaxy derivative of the one-second dataset.

Usage::

    python scripts/ao_explorer/long_metadata_revision.py \\
        --web-dir web/ao-explorer --galaxy-root outputs/ao_explorer_galaxy \\
        --record-dir outputs/ao_explorer_1s_derived/<dataset-id>

Correction (2026-10-23).  ``long_export.py`` recorded
``sampled.roles.<role>.flux.all_frames.file = "flux.npz"``, but the file it
wrote for every case is ``flux_and_means.npz``.  This tool corrects that
record and nothing numerical:

* it reads the active entry, checks the galaxy manifest against it and every
  member against the manifest;
* for each case's ``galaxy.json`` it replaces the wrong name with the actual
  file's record (name, path, directory, size, SHA-256, array names), read
  from the case's existing numerical-output directory, which is not touched;
* it re-expresses the member references of the revised records so that they
  resolve to the original, byte-identical images and scene record in place;
  no image is re-encoded or copied and no observation is recomputed;
* it writes the revised records and manifest to a new derived directory
  ``<original-id>-m<key>`` (the original directory is never overwritten),
  replaces the one mean-mode limitation sentence whose wording asserted
  non-convergence, and updates only the ``galaxy`` block of
  ``data/current.json``.

Generation provenance stays as recorded: the generator's code identity, the
environment, the template reuse and the flux summaries describe how the
arrays and images were made.  This tool's own identity and the correction are
recorded separately, under ``metadata_revision`` and in a record file.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import posixpath
import sys
from typing import Any, Dict, List, Optional

import identity
import long_export
import producer


REVISION = "flux-file-reference-v1"
CODE_FILES = ("long_metadata_revision.py", "long_export.py", "long_series.py", "identity.py")
WRONG_FLUX_FILE = "flux.npz"
OLD_MEAN_LIMITATION_END = "It is a discrete average of frame-start snapshots of one realization, not a converged long exposure."
NEW_MEAN_LIMITATION_END = (
    "It is the correctly computed equal-weight average of frame-start snapshots for the declared 0.200-1.000 s window of one "
    "realization; that record does not establish a converged long-exposure PSF."
)


class RevisionError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RevisionError(message)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=1, allow_nan=False, ensure_ascii=False) + "\n").encode("utf-8")


def _verified(base: Path, relative: str, size: int, digest: str) -> bytes:
    data = (base / relative).read_bytes()
    _require(len(data) == size and identity.sha256_bytes(data) == digest, f"{relative} differs from its recorded size or SHA-256")
    return data


def _target(defining: str, href: str) -> str:
    """The bundle-relative path a reference resolves to, refusing one that leaves the bundle."""

    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(defining), href))
    _require(not resolved.startswith("..") and not resolved.startswith("/"), f"{href} from {defining} leaves the bundle")
    return resolved


def _rebased(ref: Dict[str, Any], defining: str, old_id: str) -> Dict[str, Any]:
    """The same member, referenced from the same defining path in the sibling revision directory."""

    depth = len(PurePosixPath(defining).parent.parts)
    return {**ref, "href": "/".join([".."] * (depth + 1) + [old_id, _target(defining, ref["href"])])}


def revise(web_dir: Path, galaxy_root: Path, record_dir: Path) -> Dict[str, Any]:
    entry_path = web_dir / "data" / "current.json"
    entry_bytes = entry_path.read_bytes()
    entry = json.loads(entry_bytes.decode("utf-8"))
    galaxy = entry["galaxy"]
    old_id = galaxy["derived_id"]
    derived_root = web_dir / "derived"
    old_base = derived_root / old_id
    manifest_bytes = _verified(old_base, "manifest.json", galaxy["manifest_bytes"], galaxy["manifest_sha256"])
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    _require(manifest["derived_id"] == old_id and manifest["parent"]["dataset_id"] == entry["dataset_id"] and manifest["parent"]["manifest_sha256"] == entry["manifest_sha256"], "the galaxy manifest is not the active derivative of the active dataset")
    _require("metadata_revision" not in manifest, "the active galaxy derivative is already a metadata revision")
    for member in manifest["members"]:
        _verified(old_base, member["path"], member["bytes"], member["sha256"])
    numerical = Path(galaxy_root) / old_id
    _require(numerical.is_dir(), f"missing numerical outputs {numerical}")

    code = identity.file_set_identity(CODE_FILES)
    key = identity.sha256_bytes(identity.canonical_json_bytes({
        "supersedes": old_id, "superseded_manifest_sha256": galaxy["manifest_sha256"], "revision": REVISION, "code": code["sha256"],
    }))[:12]
    new_id = f"{old_id}-m{key}"
    new_base = derived_root / new_id
    _require(not new_base.exists(), f"{new_id} exists; a derived directory is never overwritten")

    revision = {
        "revision": REVISION,
        "supersedes": {"derived_id": old_id, "manifest_sha256": galaxy["manifest_sha256"], "manifest_bytes": galaxy["manifest_bytes"]},
        "correction": (
            f"sampled.roles.<role>.flux.all_frames named '{WRONG_FLUX_FILE}', which was never written; it now records the actual "
            f"per-case archive {long_export.FLUX_FILE} in outputs/ao_explorer_galaxy/{old_id}/<case>/ with its size, SHA-256 and arrays. "
            "Member references are re-expressed to resolve to the original files in place. One mean-mode limitation sentence "
            "is reworded so that it no longer asserts non-convergence."
        ),
        "unchanged": (
            "every numerical array, image byte, display scale, flux summary, template reuse record and the generator's code "
            "identity (code_identity), which still names the source that generated the arrays and images"
        ),
        "revision_code_identity": code,
        "created_utc": producer.utc_now(),
    }

    new_members: List[Dict[str, Any]] = []
    case_refs: Dict[str, Any] = {}
    corrected: Dict[str, Any] = {}
    for case_id, item in manifest["cases"].items():
        defining = item["galaxy"]["href"]
        old_data = _verified(old_base, defining, item["galaxy"]["bytes"], item["galaxy"]["sha256"])
        record = json.loads(old_data.decode("utf-8"))
        _require(record["case_id"] == case_id, f"{defining} names another case")
        flux_file = long_export.flux_file_record(old_id, case_id, numerical / case_id / long_export.FLUX_FILE)
        for role, entry_role in record["sampled"]["roles"].items():
            all_frames = entry_role["flux"]["all_frames"]
            _require(all_frames.get("file") == WRONG_FLUX_FILE, f"{case_id} {role}: unexpected flux file reference {all_frames.get('file')!r}")
            all_frames.update(flux_file)
            entry_role["atlas"] = _rebased(entry_role["atlas"], defining, old_id)
        for entry_role in record["mean"]["roles"].values():
            entry_role["image"] = _rebased(entry_role["image"], defining, old_id)
        record["scene"] = _rebased(record["scene"], defining, old_id)
        record["metadata_revision"] = {
            **{key: revision[key] for key in ("revision", "correction", "unchanged", "created_utc")},
            "superseded_record": {"derived_id": old_id, "path": defining, "bytes": item["galaxy"]["bytes"], "sha256": item["galaxy"]["sha256"]},
            "revision_code_sha256": code["sha256"],
        }
        data = _json_bytes(record)
        path = new_base / defining
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(data)
        member = {"path": defining, "bytes": len(data), "sha256": identity.sha256_bytes(data), "media_type": "application/json", "role": "galaxy_observation"}
        new_members.append(member)
        case_refs[case_id] = {"label": item["label"], "galaxy": {"href": defining, "bytes": member["bytes"], "sha256": member["sha256"], "media_type": "application/json"}}
        corrected[case_id] = flux_file

    revised = dict(manifest)
    revised["derived_id"] = new_id
    revised["scene"] = _rebased(manifest["scene"], "manifest.json", old_id)
    revised["cases"] = case_refs
    limitations = list(manifest["limitations"])
    matches = [index for index, text in enumerate(limitations) if text.endswith(OLD_MEAN_LIMITATION_END)]
    _require(len(matches) == 1, "the mean-mode limitation sentence was not found exactly once")
    limitations[matches[0]] = limitations[matches[0]][: -len(OLD_MEAN_LIMITATION_END)] + NEW_MEAN_LIMITATION_END
    revised["limitations"] = limitations
    referenced = [
        {**member, "path": f"../{old_id}/{member['path']}", "in_place": f"byte-identical member of {old_id}, referenced in place"}
        for member in manifest["members"]
        if member["media_type"] != "application/json" or member["path"].startswith("scene/")
    ]
    revised["members"] = sorted(new_members + referenced, key=lambda member: member["path"])
    revised["metadata_revision"] = revision
    revised_bytes = _json_bytes(revised)
    (new_base / "manifest.json").write_bytes(revised_bytes)

    new_entry = dict(entry)
    new_entry["galaxy"] = {
        "schema": galaxy["schema"],
        "derived_id": new_id,
        "manifest": f"../derived/{new_id}/manifest.json",
        "manifest_bytes": len(revised_bytes),
        "manifest_sha256": identity.sha256_bytes(revised_bytes),
    }
    record = {
        "schema": "ao-explorer.galaxy-metadata-revision.v1",
        **revision,
        "derived_id": new_id,
        "manifest_sha256": new_entry["galaxy"]["manifest_sha256"],
        "manifest_bytes": len(revised_bytes),
        "entry_before_sha256": identity.sha256_bytes(entry_bytes),
        "corrected_flux_files": corrected,
        "revised_records": {member["path"]: {"bytes": member["bytes"], "sha256": member["sha256"]} for member in new_members},
    }
    Path(record_dir).mkdir(parents=True, exist_ok=True)
    producer.write_json(Path(record_dir) / f"galaxy-metadata-revision-{new_id}.json", record)
    entry_path.write_text(json.dumps(new_entry, indent=1) + "\n", encoding="utf-8")
    return record


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--web-dir", type=Path, required=True)
    parser.add_argument("--galaxy-root", type=Path, required=True)
    parser.add_argument("--record-dir", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        record = revise(arguments.web_dir, arguments.galaxy_root, arguments.record_dir)
    except (RevisionError, long_export.LongExportError) as exc:
        print(json.dumps({"revised": False, "error": str(exc)}))
        return 2
    print(json.dumps({"revised": True, "derived_id": record["derived_id"], "manifest_sha256": record["manifest_sha256"], "manifest_bytes": record["manifest_bytes"]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
