#!/usr/bin/env python3
"""Generate, review, and explicitly accept the cross-backend baseline.

Candidate generation and baseline acceptance are deliberately separate
operations.  Tests, notebooks, and examples only ever read the packaged
baseline; nothing updates it as a side effect, and acceptance requires an
explicit command with a human-readable reason and a review reference.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

GENERATOR_NAME = "scripts/generate_cross_backend_candidate.py"
GENERATOR_VERSION = "1"
CANDIDATE_FILE = "cross_backend_candidate.json"
DIFF_JSON = "cross_backend_diff.json"
DIFF_MARKDOWN = "cross_backend_diff.md"
DESTINATION_DIR = (
    ROOT / "src" / "shwfs_ao" / "resources" / "reference_metrics" / "cross_backend"
)
BASELINE_NAME = "cross_backend_baseline.json"
CONSTRAINT_FILE = "constraints/hcipy-py311.txt"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a cross-backend candidate or accept a separately "
            "reviewed candidate. Acceptance never runs the suite implicitly."
        )
    )
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument(
        "--generate-candidate",
        action="store_true",
        help="Run the suite and write a candidate plus diffs to --candidate-dir.",
    )
    operation.add_argument(
        "--accept-baseline-update",
        action="store_true",
        help="Accept an existing reviewed candidate; never generates one.",
    )
    parser.add_argument(
        "--candidate-dir",
        type=Path,
        help="Explicit caller-owned candidate directory outside packaged resources.",
    )
    parser.add_argument(
        "--reason",
        help="Required concise scientific reason when accepting a candidate.",
    )
    parser.add_argument(
        "--review-reference",
        help="Required review/issue/PR reference when accepting a candidate.",
    )
    args = parser.parse_args()

    if not args.generate_candidate and not args.accept_baseline_update:
        parser.error(
            "--accept-baseline-update is required for acceptance; use "
            "--generate-candidate to create a reviewable candidate instead."
        )
    if args.candidate_dir is None:
        parser.error("--candidate-dir is required for both generation and acceptance.")

    candidate_dir = args.candidate_dir.expanduser().resolve()
    _reject_packaged_destination(candidate_dir, parser)
    if args.generate_candidate:
        if args.reason is not None or args.review_reference is not None:
            parser.error("Acceptance metadata is not valid during candidate generation.")
        _generate_candidate(candidate_dir)
        return

    if not args.reason or not args.reason.strip():
        parser.error("--reason is required when --accept-baseline-update is used.")
    if not args.review_reference or not args.review_reference.strip():
        parser.error(
            "--review-reference is required when --accept-baseline-update is used."
        )
    if os.environ.get("PYTEST_CURRENT_TEST"):
        raise SystemExit(
            "Baseline acceptance is forbidden while pytest is running."
        )
    _accept_reviewed_candidate(
        candidate_dir,
        reason=args.reason.strip(),
        review_reference=args.review_reference.strip(),
    )


def _generate_candidate(candidate_dir: Path) -> None:
    candidate_dir.mkdir(parents=True, exist_ok=True)
    collisions = [
        candidate_dir / name
        for name in (CANDIDATE_FILE, DIFF_JSON, DIFF_MARKDOWN)
    ]
    existing = [path for path in collisions if path.exists()]
    if existing:
        joined = ", ".join(str(path) for path in existing)
        raise SystemExit(
            f"Candidate generation refuses to overwrite existing files: {joined}"
        )

    from shwfs_ao.validation.cross_backend import run_cross_backend_report
    from shwfs_ao.validation.regression import validate_cross_backend_report

    constraint_path = ROOT / CONSTRAINT_FILE
    constraint_sha256 = (
        hashlib.sha256(constraint_path.read_bytes()).hexdigest()
        if constraint_path.is_file()
        else "unrecorded"
    )
    report = run_cross_backend_report(
        dependency_constraint_file=CONSTRAINT_FILE,
        dependency_constraint_sha256=constraint_sha256,
    )
    candidate: dict[str, Any] = dict(report)
    candidate["generator"] = {
        "generator_name": GENERATOR_NAME,
        "generator_version": GENERATOR_VERSION,
        "source_commit": _source_commit(),
    }
    validate_cross_backend_report(candidate)

    candidate_bytes = _canonical_bytes(candidate)
    diff = _build_diff(candidate, candidate_bytes)
    (candidate_dir / CANDIDATE_FILE).write_bytes(candidate_bytes)
    (candidate_dir / DIFF_JSON).write_bytes(_canonical_bytes(diff))
    (candidate_dir / DIFF_MARKDOWN).write_text(
        _render_diff_markdown(diff),
        encoding="utf-8",
    )
    print(f"Generated candidate in {candidate_dir}")
    print(
        f"Review {candidate_dir / DIFF_MARKDOWN} before running the "
        "acceptance command."
    )


def _accept_reviewed_candidate(
    candidate_dir: Path,
    *,
    reason: str,
    review_reference: str,
) -> None:
    from datetime import datetime, timezone

    from shwfs_ao.validation.regression import (
        baseline_from_report,
        validate_cross_backend_report,
    )

    candidate_path = candidate_dir / CANDIDATE_FILE
    if not candidate_path.is_file():
        raise SystemExit(f"Missing reviewed candidate: {candidate_path}")
    candidate_bytes = candidate_path.read_bytes()
    candidate = json.loads(candidate_bytes.decode("utf-8"))
    validate_cross_backend_report(candidate)
    generator = candidate.get("generator")
    if not isinstance(generator, dict) or not generator:
        raise SystemExit(
            "Candidate is missing its generator block; regenerate it with "
            "this script."
        )

    # The recomputed diff embeds content hashes of the candidate file bytes
    # and the current packaged baseline, so any modification to either after
    # the reviewed diff was generated — a tolerance, a rationale, a hash, or
    # formatting alone — forces regeneration and a fresh review.
    diff = _build_diff(candidate, candidate_bytes)
    checked_diff_path = candidate_dir / DIFF_JSON
    if not checked_diff_path.is_file():
        raise SystemExit(f"Missing generated machine-readable diff: {checked_diff_path}")
    checked_diff = json.loads(checked_diff_path.read_text(encoding="utf-8"))
    if checked_diff != diff:
        raise SystemExit(
            "Candidate or accepted baseline changed after diff generation; "
            "regenerate and review the diff."
        )

    report_body = {
        key: value for key, value in candidate.items() if key != "generator"
    }
    baseline = baseline_from_report(
        report_body,
        generator=generator,
        acceptance={
            "reason": reason,
            "review_reference": review_reference,
            "accepted_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    )
    DESTINATION_DIR.mkdir(parents=True, exist_ok=True)
    target = DESTINATION_DIR / BASELINE_NAME
    target.write_text(
        json.dumps(baseline, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Updated {target.relative_to(ROOT)} from {candidate_path}")
    _refresh_resource_manifest()


def _refresh_resource_manifest() -> None:
    import tempfile

    from shwfs_ao.io.resources import render_resource_manifest

    resource_root = DESTINATION_DIR.parents[1]
    manifest_path = resource_root / "resource_manifest.json"
    rendered = render_resource_manifest(resource_root)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=resource_root,
            prefix=".resource_manifest.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
            temporary_name = handle.name
        os.replace(temporary_name, manifest_path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
    print(f"Updated {manifest_path.relative_to(ROOT)}")


def _build_diff(
    candidate: dict[str, Any],
    candidate_bytes: bytes,
) -> dict[str, Any]:
    current = _load_current_baseline()
    current_bytes = _current_baseline_bytes()
    candidate_metrics = _metric_values(candidate)
    current_metrics = _metric_values(current) if current is not None else {}
    keys = sorted(set(candidate_metrics) | set(current_metrics))
    entries = []
    for kind, name in keys:
        entries.append(
            {
                "comparison_kind": kind,
                "metric": name,
                "old_value": current_metrics.get((kind, name)),
                "new_value": candidate_metrics.get((kind, name)),
            }
        )
    return {
        "schema_name": "shwfs_ao.cross_backend_diff",
        "schema_version": 1,
        "baseline_present": current is not None,
        "old_config_hash": (
            None
            if current is None
            else current["comparison_config"]["config_hash"]
        ),
        "new_config_hash": candidate["comparison_config"]["config_hash"],
        "current_baseline_sha256": (
            None
            if current_bytes is None
            else hashlib.sha256(current_bytes).hexdigest()
        ),
        "candidate_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
        "metrics": entries,
        "changes": _document_changes(current, candidate),
    }


def _document_changes(
    current: dict[str, Any] | None,
    candidate: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return every leaf-level difference between baseline and candidate.

    Comparisons are keyed by ``comparison_kind`` and metrics by ``name`` so a
    changed tolerance reads as one stable path instead of an array-index
    shuffle.  The top-level ``acceptance`` block is excluded: candidates never
    carry one, and acceptance provenance is minted at accept time.  An absent
    side is rendered as null.
    """

    old_document = {} if current is None else dict(current)
    new_document = dict(candidate)
    old_document.pop("acceptance", None)
    new_document.pop("acceptance", None)
    changes: list[dict[str, Any]] = []
    _collect_changes("", old_document, new_document, changes)
    return changes


_ABSENT = object()


def _collect_changes(
    path: str,
    old: Any,
    new: Any,
    changes: list[dict[str, Any]],
) -> None:
    if old is _ABSENT or new is _ABSENT or type(old) is not type(new):
        changes.append(
            {
                "path": path,
                "old": None if old is _ABSENT else old,
                "new": None if new is _ABSENT else new,
            }
        )
        return
    if isinstance(old, dict):
        for key in sorted(set(old) | set(new)):
            _collect_changes(
                f"{path}.{key}" if path else str(key),
                old.get(key, _ABSENT),
                new.get(key, _ABSENT),
                changes,
            )
        return
    if isinstance(old, list):
        keyed_old = _keyed_elements(path, old)
        keyed_new = _keyed_elements(path, new)
        if keyed_old is not None and keyed_new is not None:
            for key in sorted(set(keyed_old) | set(keyed_new)):
                _collect_changes(
                    f"{path}[{key}]",
                    keyed_old.get(key, _ABSENT),
                    keyed_new.get(key, _ABSENT),
                    changes,
                )
            return
        for index in range(max(len(old), len(new))):
            _collect_changes(
                f"{path}[{index}]",
                old[index] if index < len(old) else _ABSENT,
                new[index] if index < len(new) else _ABSENT,
                changes,
            )
        return
    if old != new:
        changes.append({"path": path, "old": old, "new": new})


def _keyed_elements(
    path: str,
    elements: list[Any],
) -> dict[str, Any] | None:
    key_field = (
        "comparison_kind"
        if path.endswith("comparisons")
        else "name" if path.endswith(".metrics") else None
    )
    if key_field is None:
        return None
    keyed: dict[str, Any] = {}
    for element in elements:
        if not isinstance(element, dict) or key_field not in element:
            return None
        label = str(element[key_field])
        if label in keyed:
            return None
        keyed[label] = element
    return keyed


def _canonical_bytes(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _render_diff_markdown(diff: dict[str, Any]) -> str:
    lines = [
        "# Cross-backend baseline candidate diff",
        "",
        f"- baseline present: {diff['baseline_present']}",
        f"- old config hash: {diff['old_config_hash']}",
        f"- new config hash: {diff['new_config_hash']}",
        f"- current baseline SHA-256: {diff['current_baseline_sha256']}",
        f"- candidate SHA-256: {diff['candidate_sha256']}",
        "",
        "## Metric values",
        "",
        "| comparison | metric | old | new |",
        "| --- | --- | --- | --- |",
    ]
    for entry in diff["metrics"]:
        lines.append(
            f"| {entry['comparison_kind']} | {entry['metric']} | "
            f"{entry['old_value']} | {entry['new_value']} |"
        )
    lines.extend(
        (
            "",
            "## All other changes (tolerances, criteria, rationale, hashes, "
            "environment; null = absent)",
            "",
        )
    )
    changes = [
        entry
        for entry in diff["changes"]
        if not (
            entry["path"].endswith(".value")
            and entry["path"].startswith("comparisons[")
        )
    ]
    if not changes:
        lines.append("None.")
    else:
        lines.extend(("| path | old | new |", "| --- | --- | --- |"))
        for entry in changes:
            lines.append(
                f"| `{entry['path']}` | {entry['old']} | {entry['new']} |"
            )
    return "\n".join(lines) + "\n"


def _metric_values(document: dict[str, Any]) -> dict[tuple[str, str], Any]:
    return {
        (comparison["comparison_kind"], metric["name"]): metric["value"]
        for comparison in document.get("comparisons", [])
        for metric in comparison.get("metrics", [])
    }


def _load_current_baseline() -> dict[str, Any] | None:
    path = DESTINATION_DIR / BASELINE_NAME
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _current_baseline_bytes() -> bytes | None:
    path = DESTINATION_DIR / BASELINE_NAME
    if not path.is_file():
        return None
    return path.read_bytes()


def _source_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def _reject_packaged_destination(
    candidate_dir: Path,
    parser: argparse.ArgumentParser,
) -> None:
    packaged_root = (ROOT / "src" / "shwfs_ao" / "resources").resolve()
    if candidate_dir == packaged_root or packaged_root in candidate_dir.parents:
        parser.error(
            "--candidate-dir must lie outside the packaged resource tree."
        )


if __name__ == "__main__":
    main()
