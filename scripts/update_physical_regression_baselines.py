#!/usr/bin/env python3
"""Generate, review, and explicitly accept atmosphere-driven baselines.

This mirrors ``update_fast_regression_baselines.py`` for the physical
workflow.  The two tools are deliberately separate: the ``fast_*`` baselines
are the frozen evidence of the control-space-proxy engine and must not move,
while the ``physical_*`` baselines record what the same instrument delivers
against a calibrated von Karman screen with a real command latency.

Candidate generation and acceptance stay separate operations, so no experiment
or test can update a packaged reference as a side effect.

    python scripts/update_physical_regression_baselines.py \\
        --generate-candidate --candidate-dir /tmp/physical-candidate

    python scripts/update_physical_regression_baselines.py \\
        --accept-baseline-update --candidate-dir /tmp/physical-candidate \\
        --reason "..." --review-reference "..."
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
from typing import Any, Callable, Sequence


ROOT = Path(__file__).resolve().parents[1]

from shwfs_ao.experiments.physical_integration import (  # noqa: E402
    PHYSICAL_PRESET,
    PHYSICAL_WORKFLOW,
    PhysicalIntegrationConfig,
    run_physical_integration,
)
from shwfs_ao.io.artifacts import (  # noqa: E402
    ArtifactConfig,
    ArtifactError,
    SCENARIO_V2_HEADER,
    VALIDATION_V2_HEADER,
    read_scenario_table,
    read_v2,
    read_validation_table,
    write_integration_artifacts,
)
from shwfs_ao.io.resources import render_resource_manifest  # noqa: E402


DESTINATION_DIR = ROOT / "src" / "shwfs_ao" / "resources" / "reference_metrics"
PREFIX = "physical"
CANDIDATE_FILES = (
    f"{PREFIX}_reference_metrics.json",
    f"{PREFIX}_error_budget.csv",
    f"{PREFIX}_validation.csv",
)
DIFF_JSON = f"{PREFIX}_baseline_diff.json"
DIFF_MARKDOWN = f"{PREFIX}_baseline_diff.md"
ACCEPTANCE_RECORD_NAME = f"{PREFIX}_baseline_acceptance.json"

DESTINATIONS = {
    f"{PREFIX}_reference_metrics.json": (
        f"{PREFIX}_reference_metrics.json",
        f"{PREFIX}_reference_metrics_regression_baseline.json",
    ),
    f"{PREFIX}_error_budget.csv": (
        f"{PREFIX}_error_budget_regression_baseline.csv",
    ),
    f"{PREFIX}_validation.csv": (
        f"{PREFIX}_validation_regression_baseline.csv",
    ),
}

COMPARED_METRICS = (
    "open_rms_nm",
    "closed_rms_nm",
    "h_strehl",
    "valid_centroid_fraction",
    "kept_modes",
    "validation_pass_count",
    "validation_check_count",
)

_SCENARIO_TEXT_FIELDS = (
    "scenario_name",
    "enabled_effects",
    "source_class",
    "source_note",
    "config_hash",
)
_SCENARIO_NUMERIC_FIELDS = tuple(
    field for field in SCENARIO_V2_HEADER if field not in _SCENARIO_TEXT_FIELDS
)
_SCENARIO_NONNEGATIVE_FIELDS = (
    "open_rms_nm",
    "closed_rms_nm",
    "closed_over_open_rms",
    "ee50_J",
    "ee50_H",
    "ee50_K",
    "ee80_J",
    "ee80_H",
    "ee80_K",
    "command_rms_nm",
    "command_peak_nm",
)
_SCENARIO_UNIT_INTERVAL_FIELDS = (
    "strehl_J",
    "strehl_H",
    "strehl_K",
    "open_strehl_H",
    "saturated_actuator_frac",
    "valid_centroid_frac",
)
_VALIDATION_REQUIRED_TEXT_FIELDS = (
    "check_name",
    "message",
    "source_class",
    "source_note",
)
_VALIDATION_REQUIRED_NUMERIC_FIELDS = ("metric_value", "tolerance")
_VALIDATION_OPTIONAL_NUMERIC_FIELDS = tuple(
    field
    for field in VALIDATION_V2_HEADER
    if field.startswith("detail_") or field == "x_value"
)
_REFERENCE_SCENARIO_BINDINGS = {
    "open_rms_nm": "open_rms_nm",
    "closed_rms_nm": "closed_rms_nm",
    "h_strehl": "strehl_H",
    "valid_centroid_fraction": "valid_centroid_frac",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reject_packaged_destination(
    candidate_dir: Path, parser: argparse.ArgumentParser
) -> None:
    canonical = DESTINATION_DIR.resolve()
    if candidate_dir == canonical or canonical in candidate_dir.parents:
        parser.error(
            "--candidate-dir must live outside the packaged reference_metrics "
            "directory so review happens before anything is packaged."
        )


def _generate_candidate(candidate_dir: Path) -> None:
    candidate_dir.mkdir(parents=True, exist_ok=True)
    existing = [
        candidate_dir / name
        for name in (*CANDIDATE_FILES, DIFF_JSON, DIFF_MARKDOWN)
        if (candidate_dir / name).exists()
    ]
    if existing:
        joined = ", ".join(str(path) for path in existing)
        raise SystemExit(
            f"Candidate generation refuses to overwrite existing files: {joined}"
        )

    config = PhysicalIntegrationConfig()
    print(
        f"Running the physical integration: n_steps={config.n_steps}, "
        f"r0={config.r0_m:.4f} m, L0={config.outer_scale_m} m, "
        f"latency={config.latency_frames} frames. This takes several minutes."
    )
    result = run_physical_integration(config)
    write_integration_artifacts(
        result,
        ArtifactConfig(
            output_dir=candidate_dir,
            reference_metrics_path=candidate_dir
            / f"{PREFIX}_reference_metrics.json",
            prefix=PREFIX,
            schema_version=2,
        ),
    )
    _validate_candidate(candidate_dir)
    diff = _build_diff(candidate_dir)
    (candidate_dir / DIFF_JSON).write_text(
        json.dumps(diff, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (candidate_dir / DIFF_MARKDOWN).write_text(
        _render_diff_markdown(diff), encoding="utf-8"
    )
    print(f"Generated candidate in {candidate_dir}")
    print(f"Review {candidate_dir / DIFF_MARKDOWN} before accepting.")


def _read_reference(path: Path) -> dict[str, Any]:
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
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            header = tuple(next(csv.reader(handle), ()))
    except OSError as exc:
        raise SystemExit(f"Could not read candidate {label} CSV {path}: {exc}") from exc
    if header != tuple(expected_header):
        raise SystemExit(
            f"Candidate {label} CSV must carry the frozen schema-v2 header "
            f"exactly; got {list(header)}."
        )
    try:
        return reader(path)
    except ArtifactError as exc:
        raise SystemExit(f"Candidate {label} CSV is invalid: {exc}") from exc


def _nonempty_cell(row: dict[str, str], field: str, *, row_label: str) -> str:
    value = row[field]
    if not value.strip():
        raise SystemExit(f"{row_label} has an empty {field!r} value.")
    return value


def _finite_cell(row: dict[str, str], field: str, *, row_label: str) -> float:
    value = row[field]
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SystemExit(
            f"{row_label} has a non-numeric {field}={value!r}."
        ) from exc
    if not math.isfinite(number):
        raise SystemExit(f"{row_label} has a non-finite {field}={value!r}.")
    return number


def _validate_scenario_rows(
    path: Path,
    rows: tuple[dict[str, str], ...],
) -> dict[str, dict[str, float]]:
    numeric_by_name: dict[str, dict[str, float]] = {}
    for row in rows:
        row_label = f"{path.name} scenario {row['scenario_name']!r}"
        for field in _SCENARIO_TEXT_FIELDS:
            _nonempty_cell(row, field, row_label=row_label)
        config_hash = row["config_hash"]
        if len(config_hash) != 64 or any(
            character not in "0123456789abcdef" for character in config_hash
        ):
            raise SystemExit(
                f"{row_label} has a non-canonical config_hash={config_hash!r}."
            )
        numeric = {
            field: _finite_cell(row, field, row_label=row_label)
            for field in _SCENARIO_NUMERIC_FIELDS
        }
        for field in _SCENARIO_NONNEGATIVE_FIELDS:
            if numeric[field] < 0.0:
                raise SystemExit(
                    f"{row_label} has a negative {field}={numeric[field]}."
                )
        if numeric["open_rms_nm"] <= 0.0 or numeric["closed_rms_nm"] <= 0.0:
            raise SystemExit(f"{row_label} must carry positive open and closed RMS.")
        for field in _SCENARIO_UNIT_INTERVAL_FIELDS:
            if not 0.0 <= numeric[field] <= 1.0:
                raise SystemExit(
                    f"{row_label} has {field}={numeric[field]} outside [0, 1]."
                )
        expected_ratio = numeric["closed_rms_nm"] / numeric["open_rms_nm"]
        if not math.isclose(
            numeric["closed_over_open_rms"],
            expected_ratio,
            rel_tol=1.0e-12,
            abs_tol=1.0e-12,
        ):
            raise SystemExit(
                f"{row_label} has closed_over_open_rms="
                f"{numeric['closed_over_open_rms']}, expected {expected_ratio}."
            )
        numeric_by_name[row["scenario_name"]] = numeric
    return numeric_by_name


def _validate_validation_rows(
    path: Path,
    rows: tuple[dict[str, str], ...],
    payload: dict[str, Any],
) -> None:
    passed_by_check: dict[str, bool] = {}
    failed: list[str] = []
    for row in rows:
        row_label = f"{path.name} check {row['check_name']!r}"
        for field in _VALIDATION_REQUIRED_TEXT_FIELDS:
            _nonempty_cell(row, field, row_label=row_label)
        for field in _VALIDATION_REQUIRED_NUMERIC_FIELDS:
            value = _finite_cell(row, field, row_label=row_label)
            if field == "tolerance" and value < 0.0:
                raise SystemExit(f"{row_label} has a negative tolerance={value}.")
        for field in _VALIDATION_OPTIONAL_NUMERIC_FIELDS:
            if row[field].strip():
                _finite_cell(row, field, row_label=row_label)
        passed_text = row["passed"].strip().lower()
        if passed_text not in {"true", "false", "1", "0"}:
            raise SystemExit(
                f"{row_label} has invalid passed={row['passed']!r}; expected a boolean."
            )
        passed = passed_text in {"true", "1"}
        name = row["check_name"]
        passed_by_check[name] = passed_by_check.get(name, True) and passed
        if not passed:
            failed.append(name)

    if len(passed_by_check) != int(payload["validation_check_count"]):
        raise SystemExit(
            f"{path.name} names {len(passed_by_check)} distinct checks but the "
            f"reference metrics record {payload['validation_check_count']}."
        )
    pass_count = sum(passed_by_check.values())
    if pass_count != int(payload["validation_pass_count"]):
        raise SystemExit(
            f"{path.name} has {pass_count} passing checks but the reference metrics "
            f"record {payload['validation_pass_count']}."
        )
    if failed:
        raise SystemExit(
            "Refusing to package a candidate with failing validation rows: "
            f"{failed}"
        )


def _validate_candidate(candidate_dir: Path) -> None:
    missing = [
        name
        for name in CANDIDATE_FILES
        if not (candidate_dir / name).is_file()
        or (candidate_dir / name).stat().st_size <= 0
    ]
    if missing:
        raise SystemExit(f"Candidate is incomplete; missing: {missing}")

    payload = _read_reference(candidate_dir / f"{PREFIX}_reference_metrics.json")
    if payload.get("workflow") != PHYSICAL_WORKFLOW:
        raise SystemExit(
            f"Candidate workflow is {payload.get('workflow')!r}, expected "
            f"{PHYSICAL_WORKFLOW!r}: this candidate was not produced by the "
            "physical engine and must not become a physical baseline."
        )
    if payload.get("preset") != PHYSICAL_PRESET:
        raise SystemExit(
            f"Candidate preset is {payload.get('preset')!r}, expected "
            f"{PHYSICAL_PRESET!r}."
        )
    for key in COMPARED_METRICS:
        if key not in payload:
            raise SystemExit(f"Candidate reference metrics lack {key!r}.")
    from shwfs_ao.experiments.error_budget import REQUIRED_SCENARIO_NAMES

    budget_path = candidate_dir / f"{PREFIX}_error_budget.csv"
    budget_rows = _read_v2_table(
        budget_path,
        SCENARIO_V2_HEADER,
        read_scenario_table,
        "scenario",
    )
    names = tuple(row["scenario_name"] for row in budget_rows)
    if names != REQUIRED_SCENARIO_NAMES:
        raise SystemExit(
            f"{budget_path.name} scenario rows are {names}, expected "
            f"{REQUIRED_SCENARIO_NAMES}."
        )
    if tuple(payload["scenario_names"]) != names:
        raise SystemExit(
            "Candidate reference metrics and error-budget table disagree on the "
            "scenario set; they were not produced by one run."
        )
    numeric_by_name = _validate_scenario_rows(budget_path, budget_rows)
    reference_scenario = payload["reference_scenario"]
    if reference_scenario not in numeric_by_name:
        raise SystemExit(
            f"Candidate reference_scenario {reference_scenario!r} is absent from "
            f"{budget_path.name}."
        )
    reference_row = numeric_by_name[reference_scenario]
    for json_field, csv_field in _REFERENCE_SCENARIO_BINDINGS.items():
        recorded = float(payload[json_field])
        expected = round(reference_row[csv_field], 6)
        if recorded != expected:
            raise SystemExit(
                f"Candidate reference metrics {json_field}={recorded} disagrees "
                f"with reference scenario {reference_scenario!r} "
                f"{csv_field}={reference_row[csv_field]} (serialized as {expected})."
            )

    validation_path = candidate_dir / f"{PREFIX}_validation.csv"
    validation_rows = _read_v2_table(
        validation_path,
        VALIDATION_V2_HEADER,
        read_validation_table,
        "validation",
    )
    _validate_validation_rows(validation_path, validation_rows, payload)


def _build_diff(candidate_dir: Path) -> dict[str, Any]:
    candidate = _read_reference(
        candidate_dir / f"{PREFIX}_reference_metrics.json"
    )
    baseline_path = (
        DESTINATION_DIR / f"{PREFIX}_reference_metrics_regression_baseline.json"
    )
    baseline = (
        _read_reference(baseline_path) if baseline_path.exists() else None
    )
    entries = []
    for key in COMPARED_METRICS:
        new = candidate.get(key)
        old = None if baseline is None else baseline.get(key)
        change = None
        if isinstance(new, (int, float)) and isinstance(old, (int, float)):
            change = float(new) - float(old)
        entries.append(
            {"metric": key, "baseline": old, "candidate": new, "change": change}
        )
    files: list[dict[str, Any]] = []
    for candidate_name, target_names in DESTINATIONS.items():
        candidate_path = candidate_dir / candidate_name
        candidate_sha256 = _sha256(candidate_path)
        for target_name in target_names:
            target_path = DESTINATION_DIR / target_name
            current_sha256 = _sha256(target_path) if target_path.is_file() else None
            files.append(
                {
                    "candidate_name": candidate_name,
                    "baseline_name": target_name,
                    "candidate_sha256": candidate_sha256,
                    "current_sha256": current_sha256,
                    "changed": current_sha256 != candidate_sha256,
                }
            )
    return {
        "schema_name": "shwfs_ao.physical_baseline_diff",
        "schema_version": 1,
        "workflow": PHYSICAL_WORKFLOW,
        "preset": PHYSICAL_PRESET,
        "baseline_exists": baseline is not None,
        "config_hash": candidate.get("config_hash"),
        "files": files,
        "metrics": entries,
    }


def _render_diff_markdown(diff: dict[str, Any]) -> str:
    lines = [
        f"# {PHYSICAL_WORKFLOW} baseline candidate",
        "",
        f"- workflow: `{diff['workflow']}`",
        f"- preset: `{diff['preset']}`",
        f"- config hash: `{diff['config_hash']}`",
        f"- an accepted baseline already exists: {diff['baseline_exists']}",
        "",
        "| metric | baseline | candidate | change |",
        "| --- | --- | --- | --- |",
    ]
    for entry in diff["metrics"]:
        baseline = "—" if entry["baseline"] is None else entry["baseline"]
        change = "—" if entry["change"] is None else f"{entry['change']:+.6g}"
        lines.append(
            f"| {entry['metric']} | {baseline} | {entry['candidate']} | {change} |"
        )
    lines += [
        "",
        "| candidate | packaged baseline | changed | current SHA-256 | candidate SHA-256 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for entry in diff["files"]:
        current_sha256 = entry["current_sha256"] or "—"
        lines.append(
            f"| `{entry['candidate_name']}` | `{entry['baseline_name']}` | "
            f"{entry['changed']} | `{current_sha256}` | "
            f"`{entry['candidate_sha256']}` |"
        )
    lines += [
        "",
        "Review these numbers before accepting. This workflow's disturbance is",
        "a calibrated von Karman screen, so its residuals and Strehl values are",
        "expected to be far worse than the control-space-proxy baselines: the",
        "proxy is exactly correctable by the mirror and this one is not.",
        "",
    ]
    return "\n".join(lines)


def _write_acceptance_record(
    *,
    reason: str,
    review_reference: str,
    reviewed_diff_path: Path,
) -> None:
    accepted = sorted({name for names in DESTINATIONS.values() for name in names})
    record = {
        "schema_name": "shwfs_ao.physical_baseline_acceptance",
        "schema_version": 1,
        "workflow": PHYSICAL_WORKFLOW,
        "preset": PHYSICAL_PRESET,
        "accepted_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reason": reason,
        "review_reference": review_reference,
        "reviewed_diff_sha256": _sha256(reviewed_diff_path),
        "accepted_files": [
            {"name": name, "sha256": _sha256(DESTINATION_DIR / name)}
            for name in accepted
        ],
    }
    target = DESTINATION_DIR / ACCEPTANCE_RECORD_NAME
    target.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Wrote {target.relative_to(ROOT)}")


def _accept_reviewed_candidate(
    candidate_dir: Path, *, reason: str, review_reference: str
) -> None:
    _validate_candidate(candidate_dir)
    recomputed_diff = _build_diff(candidate_dir)
    reviewed_diff_path = candidate_dir / DIFF_JSON
    if not reviewed_diff_path.is_file():
        raise SystemExit(
            f"Missing generated machine-readable diff: {reviewed_diff_path}"
        )
    try:
        reviewed_diff = json.loads(reviewed_diff_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(
            f"Malformed candidate diff {reviewed_diff_path}: {exc}"
        ) from exc
    if reviewed_diff != recomputed_diff:
        raise SystemExit(
            "Candidate or accepted baseline changed after diff generation; "
            "regenerate and review the diff."
        )
    for source_name, target_names in DESTINATIONS.items():
        source = candidate_dir / source_name
        for target_name in target_names:
            target = DESTINATION_DIR / target_name
            shutil.copyfile(source, target)
            print(f"Updated {target.relative_to(ROOT)} from {source}")
    _write_acceptance_record(
        reason=reason,
        review_reference=review_reference,
        reviewed_diff_path=reviewed_diff_path,
    )

    resource_root = DESTINATION_DIR.parent
    manifest_text = render_resource_manifest(resource_root)
    if not manifest_text.endswith("\n"):
        manifest_text += "\n"
    (resource_root / "resource_manifest.json").write_text(
        manifest_text, encoding="utf-8"
    )
    print("Regenerated resource_manifest.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument("--generate-candidate", action="store_true")
    operation.add_argument("--accept-baseline-update", action="store_true")
    parser.add_argument("--candidate-dir", type=Path)
    parser.add_argument("--reason")
    parser.add_argument("--review-reference")
    args = parser.parse_args()

    if not args.generate_candidate and not args.accept_baseline_update:
        parser.error(
            "--accept-baseline-update is required for acceptance; use "
            "--generate-candidate to create a reviewable candidate instead."
        )
    if args.candidate_dir is None:
        parser.error("--candidate-dir is required for both operations.")

    candidate_dir = args.candidate_dir.expanduser().resolve()
    _reject_packaged_destination(candidate_dir, parser)

    if args.generate_candidate:
        if args.reason is not None or args.review_reference is not None:
            parser.error(
                "Acceptance metadata is not valid during candidate generation."
            )
        _generate_candidate(candidate_dir)
        return

    if not args.reason or not args.reason.strip():
        parser.error("--reason is required when accepting.")
    if not args.review_reference or not args.review_reference.strip():
        parser.error("--review-reference is required when accepting.")
    if os.environ.get("PYTEST_CURRENT_TEST"):
        raise SystemExit("Baseline acceptance is forbidden while pytest is running.")
    _accept_reviewed_candidate(
        candidate_dir,
        reason=args.reason.strip(),
        review_reference=args.review_reference.strip(),
    )


if __name__ == "__main__":
    main()
