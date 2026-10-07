#!/usr/bin/env python3
"""Generate, review, and explicitly accept fast-integration baselines.

Candidate generation and baseline acceptance are deliberately separate
operations.  A normal experiment or test can never update the packaged
references as a side effect.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Callable, Sequence


ROOT = Path(__file__).resolve().parents[1]

from shwfs_ao.experiments.integration import IntegrationConfig, run_fast_integration
from shwfs_ao.io.artifacts import (
    ArtifactConfig,
    ArtifactError,
    SCENARIO_V2_HEADER,
    VALIDATION_V2_HEADER,
    read_scenario_table,
    read_v2,
    read_validation_table,
    write_integration_artifacts,
)
from shwfs_ao.io.resources import render_resource_manifest


DESTINATION_DIR = ROOT / "src" / "shwfs_ao" / "resources" / "reference_metrics"
CANDIDATE_FILES = (
    "fast_reference_metrics.json",
    "fast_error_budget.csv",
    "fast_validation.csv",
)
DIFF_JSON = "fast_baseline_diff.json"
DIFF_MARKDOWN = "fast_baseline_diff.md"
ACCEPTANCE_RECORD_NAME = "fast_baseline_acceptance.json"

# Reference-JSON metrics and the reference-scenario CSV columns they round.
_REFERENCE_SCENARIO_BINDINGS = {
    "open_rms_nm": "open_rms_nm",
    "closed_rms_nm": "closed_rms_nm",
    "h_strehl": "strehl_H",
    "valid_centroid_fraction": "valid_centroid_frac",
}


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
    if os.environ.get("PYTEST_CURRENT_TEST"):
        raise SystemExit("Baseline acceptance is forbidden while pytest is running.")
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
    _write_acceptance_record(
        reason=reason,
        review_reference=review_reference,
        accepted_names=sorted(
            {name for names in destinations.values() for name in names}
        ),
        reviewed_diff_path=checked_diff_path,
    )
    _refresh_resource_manifest()
    print(f"Acceptance reason: {reason}")
    print(f"Review reference: {review_reference}")


def _write_acceptance_record(
    *,
    reason: str,
    review_reference: str,
    accepted_names: Sequence[str],
    reviewed_diff_path: Path,
) -> None:
    """Persist the human acceptance evidence next to the accepted baselines.

    The record binds the reason and review reference to the exact accepted
    bytes (per-file SHA-256) and to the reviewed machine-readable diff, so a
    later audit can establish what was accepted, when, why, and against
    which review — not just that the files changed.
    """

    record = {
        "schema_name": "shwfs_ao.fast_baseline_acceptance",
        "schema_version": 1,
        "accepted_at_utc": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "review_reference": review_reference,
        "accepted_files": [
            {
                "baseline_name": name,
                "sha256": _sha256(DESTINATION_DIR / name),
            }
            for name in accepted_names
        ],
        "reviewed_diff_sha256": _sha256(reviewed_diff_path),
    }
    target = DESTINATION_DIR / ACCEPTANCE_RECORD_NAME
    target.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Recorded acceptance evidence in {target.relative_to(ROOT)}")


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
    """Reject a candidate that violates the frozen schema-v2 contract.

    The strict ``read_v2`` reader enforces the complete historical metric
    set, finite metric values, the exact tolerance key inventory with
    non-negative finite values, and internal scenario/validation-count
    consistency; the strict table readers enforce the frozen CSV headers.
    On top of that, the JSON and CSV members of one candidate must agree on
    the scenario inventory, the reference-scenario metrics the JSON rounds
    from its CSV row, the distinct validation checks, and how many of them
    passed, so a mismatched mixture of files can never be accepted as one
    baseline.
    """

    for name in CANDIDATE_FILES:
        path = candidate_dir / name
        if not path.is_file() or path.stat().st_size <= 0:
            raise SystemExit(f"Missing or empty candidate artifact: {path}")

    payload = _read_v2_reference(candidate_dir / "fast_reference_metrics.json")
    if payload["workflow"] != "fast_integration" or payload["preset"] != "fast":
        raise SystemExit("Candidate reference JSON is not the fast-integration contract.")

    scenario_rows = _read_v2_table(
        candidate_dir / "fast_error_budget.csv",
        SCENARIO_V2_HEADER,
        read_scenario_table,
        "scenario",
    )
    validation_rows = _read_v2_table(
        candidate_dir / "fast_validation.csv",
        VALIDATION_V2_HEADER,
        read_validation_table,
        "validation",
    )

    scenario_names = [row["scenario_name"] for row in scenario_rows]
    if any(not name.strip() for name in scenario_names):
        raise SystemExit("Candidate scenario table contains an empty scenario_name.")
    if len(set(scenario_names)) != len(scenario_names):
        raise SystemExit("Candidate scenario table contains duplicate scenario_name rows.")
    if set(scenario_names) != set(payload["scenario_names"]):
        raise SystemExit(
            "Candidate scenario table and reference JSON disagree on the scenario inventory."
        )
    if payload["reference_scenario"] not in set(scenario_names):
        raise SystemExit("Candidate reference_scenario is missing from the scenario table.")
    reference_row = scenario_rows[scenario_names.index(payload["reference_scenario"])]
    for json_field, csv_field in _REFERENCE_SCENARIO_BINDINGS.items():
        cell = reference_row[csv_field]
        try:
            value = float(cell)
        except ValueError as exc:
            raise SystemExit(
                f"Candidate reference scenario has a non-numeric {csv_field}={cell!r}."
            ) from exc
        if not math.isfinite(value):
            raise SystemExit(
                f"Candidate reference scenario has a non-finite {csv_field}={cell!r}."
            )
        if float(payload[json_field]) != round(value, 6):
            raise SystemExit(
                f"Candidate reference JSON {json_field}={payload[json_field]} disagrees "
                f"with reference scenario {payload['reference_scenario']!r} "
                f"{csv_field}={cell} (serialized as {round(value, 6)})."
            )

    check_names = [row["check_name"] for row in validation_rows]
    if any(not name.strip() for name in check_names):
        raise SystemExit("Candidate validation table contains an empty check_name.")
    if len(set(check_names)) != int(payload["validation_check_count"]):
        raise SystemExit(
            "Candidate validation table and reference JSON disagree on the "
            "distinct validation-check inventory."
        )
    # A scan check writes one row per sample, all carrying the check's verdict.
    passed_by_check: dict[str, bool] = {}
    for row in validation_rows:
        passed_text = row["passed"].strip().lower()
        if passed_text not in {"true", "false", "1", "0"}:
            raise SystemExit(
                f"Candidate validation check {row['check_name']!r} has invalid "
                f"passed={row['passed']!r}; expected a boolean."
            )
        passed = passed_text in {"true", "1"}
        if passed_by_check.setdefault(row["check_name"], passed) != passed:
            raise SystemExit(
                f"Candidate validation check {row['check_name']!r} has rows with "
                "contradictory passed values."
            )
    pass_count = sum(passed_by_check.values())
    if pass_count != int(payload["validation_pass_count"]):
        raise SystemExit(
            f"Candidate validation table has {pass_count} passing checks but the "
            f"reference JSON records {payload['validation_pass_count']}."
        )


def _read_v2_reference(path: Path) -> dict[str, Any]:
    try:
        return read_v2(path)
    except ArtifactError as exc:
        raise SystemExit(
            f"Reference metrics at {path} violate the frozen schema-v2 "
            f"contract: {exc}"
        ) from exc


def _read_v2_table(
    path: Path,
    expected_header: Sequence[str],
    reader: Callable[[Path], tuple[dict[str, str], ...]],
    label: str,
) -> tuple[dict[str, str], ...]:
    with path.open(newline="", encoding="utf-8") as handle:
        header = tuple(next(csv.reader(handle), ()))
    if header != tuple(expected_header):
        raise SystemExit(
            f"Candidate {label} CSV must carry the frozen schema-v2 header "
            f"exactly; got {list(header)}."
        )
    try:
        return reader(path)
    except ArtifactError as exc:
        raise SystemExit(f"Candidate {label} CSV is invalid: {exc}") from exc


def _build_diff(candidate_dir: Path) -> dict[str, Any]:
    current_reference = _read_v2_reference(
        DESTINATION_DIR / "fast_reference_metrics_regression_baseline.json"
    )
    candidate_reference = _read_v2_reference(candidate_dir / "fast_reference_metrics.json")
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
