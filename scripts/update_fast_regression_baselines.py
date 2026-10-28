#!/usr/bin/env python3
"""Generate, review, and explicitly accept fast-integration baselines.

Candidate generation and baseline acceptance are deliberately separate
operations.  A normal experiment or test can never update the packaged
references as a side effect.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

from ao_integration import IntegrationConfig, load_reference_metrics, run_fast_integration
from shwfs_ao.io.artifacts import ArtifactConfig, write_integration_artifacts
from shwfs_ao.io.resources import render_resource_manifest


DESTINATION_DIR = ROOT / "src" / "shwfs_ao" / "resources" / "reference_metrics"
CANDIDATE_FILES = (
    "fast_reference_metrics.json",
    "fast_error_budget.csv",
    "fast_validation.csv",
)
DIFF_JSON = "fast_baseline_diff.json"
DIFF_MARKDOWN = "fast_baseline_diff.md"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a fast-regression candidate or accept a separately reviewed "
            "candidate. Acceptance never runs the experiment implicitly."
        )
    )
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument(
        "--generate-candidate",
        action="store_true",
        help="Write a candidate and machine/human-readable diffs to --candidate-dir.",
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
        parser.error("--review-reference is required when --accept-baseline-update is used.")
    _accept_reviewed_candidate(
        candidate_dir,
        reason=args.reason.strip(),
        review_reference=args.review_reference.strip(),
    )


def _generate_candidate(candidate_dir: Path) -> None:
    candidate_dir.mkdir(parents=True, exist_ok=True)
    collisions = [candidate_dir / name for name in (*CANDIDATE_FILES, DIFF_JSON, DIFF_MARKDOWN)]
    existing = [path for path in collisions if path.exists()]
    if existing:
        joined = ", ".join(str(path) for path in existing)
        raise SystemExit(f"Candidate generation refuses to overwrite existing files: {joined}")

    config = IntegrationConfig.from_mode(
        "fast",
        output_dir=candidate_dir,
        reference_metrics_path=candidate_dir / "fast_reference_metrics.json",
    )
    result = run_fast_integration(config=config, write_outputs=False)
    write_integration_artifacts(
        result,
        ArtifactConfig(
            output_dir=candidate_dir,
            reference_metrics_path=candidate_dir / "fast_reference_metrics.json",
            prefix="fast",
            schema_version=2,
        ),
    )
    _validate_candidate(candidate_dir)
    diff = _build_diff(candidate_dir)
    (candidate_dir / DIFF_JSON).write_text(
        json.dumps(diff, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (candidate_dir / DIFF_MARKDOWN).write_text(
        _render_diff_markdown(diff),
        encoding="utf-8",
    )
    print(f"Generated candidate in {candidate_dir}")
    print(f"Review {candidate_dir / DIFF_MARKDOWN} before running the acceptance command.")


def _accept_reviewed_candidate(
    candidate_dir: Path,
    *,
    reason: str,
    review_reference: str,
) -> None:
    _validate_candidate(candidate_dir)
    diff = _build_diff(candidate_dir)
    checked_diff_path = candidate_dir / DIFF_JSON
    if not checked_diff_path.is_file():
        raise SystemExit(f"Missing generated machine-readable diff: {checked_diff_path}")
    try:
        checked_diff = json.loads(checked_diff_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Malformed candidate diff: {checked_diff_path}: {exc}") from exc
    if checked_diff != diff:
        raise SystemExit(
            "Candidate or accepted baseline changed after diff generation; regenerate and review the diff."
        )

    destinations = {
        "fast_reference_metrics.json": (
            "fast_reference_metrics.json",
            "fast_reference_metrics_regression_baseline.json",
        ),
        "fast_error_budget.csv": ("fast_error_budget_regression_baseline.csv",),
        "fast_validation.csv": ("fast_validation_regression_baseline.csv",),
    }
    for source_name, target_names in destinations.items():
        source = candidate_dir / source_name
        for target_name in target_names:
            target = DESTINATION_DIR / target_name
            shutil.copyfile(source, target)
            print(f"Updated {target.relative_to(ROOT)} from {source}")
    _refresh_resource_manifest()
    print(f"Acceptance reason: {reason}")
    print(f"Review reference: {review_reference}")


def _refresh_resource_manifest() -> None:
    resource_root = DESTINATION_DIR.parent
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


def _validate_candidate(candidate_dir: Path) -> None:
    for name in CANDIDATE_FILES:
        path = candidate_dir / name
        if not path.is_file() or path.stat().st_size <= 0:
            raise SystemExit(f"Missing or empty candidate artifact: {path}")

    candidate_reference = candidate_dir / "fast_reference_metrics.json"
    payload = load_reference_metrics(candidate_reference)
    if payload["workflow"] != "fast_integration" or payload["preset"] != "fast":
        raise SystemExit("Candidate reference JSON is not the fast-integration contract.")
    if payload.get("schema_version") != 2:
        raise SystemExit("The compatibility baseline updater accepts only frozen schema-v2 candidates.")
    # Parse tables and reject missing identity columns before any tracked write.
    table_keys = {
        "fast_error_budget.csv": "scenario_name",
        "fast_validation.csv": "check_name",
    }
    for name, identity_key in table_keys.items():
        with (candidate_dir / name).open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
        if not rows or reader.fieldnames is None or identity_key not in reader.fieldnames:
            raise SystemExit(f"Candidate table {name} has no valid {identity_key!r} rows.")


def _build_diff(candidate_dir: Path) -> dict[str, Any]:
    current_reference = load_reference_metrics(
        DESTINATION_DIR / "fast_reference_metrics_regression_baseline.json"
    )
    candidate_reference = load_reference_metrics(candidate_dir / "fast_reference_metrics.json")
    metric_names = (
        "open_rms_nm",
        "closed_rms_nm",
        "h_strehl",
        "valid_centroid_fraction",
        "kept_modes",
    )
    metrics = {
        name: {
            "candidate": candidate_reference[name],
            "current": current_reference[name],
            "delta": candidate_reference[name] - current_reference[name],
        }
        for name in metric_names
    }
    files: list[dict[str, Any]] = []
    baseline_names = {
        "fast_reference_metrics.json": "fast_reference_metrics_regression_baseline.json",
        "fast_error_budget.csv": "fast_error_budget_regression_baseline.csv",
        "fast_validation.csv": "fast_validation_regression_baseline.csv",
    }
    for candidate_name in CANDIDATE_FILES:
        baseline_name = baseline_names[candidate_name]
        candidate_path = candidate_dir / candidate_name
        baseline_path = DESTINATION_DIR / baseline_name
        files.append(
            {
                "baseline_name": baseline_name,
                "candidate_name": candidate_name,
                "candidate_sha256": _sha256(candidate_path),
                "changed": candidate_path.read_bytes() != baseline_path.read_bytes(),
                "current_sha256": _sha256(baseline_path),
            }
        )
    return {
        "schema_name": "shwfs_ao.fast_baseline_diff",
        "schema_version": 1,
        "files": files,
        "metrics": metrics,
    }


def _render_diff_markdown(diff: dict[str, Any]) -> str:
    lines = [
        "# Fast baseline candidate diff",
        "",
        "| Metric | Current | Candidate | Delta |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, record in diff["metrics"].items():
        lines.append(
            f"| `{name}` | {record['current']} | {record['candidate']} | {record['delta']} |"
        )
    lines.extend(("", "| File | Changed | Current SHA-256 | Candidate SHA-256 |", "| --- | --- | --- | --- |"))
    for record in diff["files"]:
        lines.append(
            f"| `{record['candidate_name']}` | {record['changed']} | "
            f"`{record['current_sha256']}` | `{record['candidate_sha256']}` |"
        )
    return "\n".join(lines) + "\n"


def _reject_packaged_destination(candidate_dir: Path, parser: argparse.ArgumentParser) -> None:
    canonical = DESTINATION_DIR.resolve()
    if candidate_dir == canonical or canonical in candidate_dir.parents:
        parser.error("--candidate-dir must be outside the canonical packaged resource tree.")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    main()
