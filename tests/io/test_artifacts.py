from __future__ import annotations

import copy
import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from shwfs_ao.core.provenance import Provenance
from shwfs_ao.io.artifacts import (
    ArtifactConfig,
    ArtifactError,
    RUNTIME_V2_HEADER,
    SCENARIO_V2_HEADER,
    SCHEMA_V3_TABLE_COLUMNS,
    VALIDATION_V2_HEADER,
    read_runtime_table,
    read_scenario_table,
    read_v2,
    read_v3,
    read_validation_table,
    upgrade_v2_to_v3,
    write_integration_artifacts,
    write_runtime_artifacts,
)


class _Row:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def as_dict(self) -> dict[str, object]:
        return dict(self._payload)


def _scenario_row() -> dict[str, object]:
    values: dict[str, object] = {key: 0.0 for key in SCENARIO_V2_HEADER}
    values.update(
        {
            "scenario_name": "all_effects",
            "enabled_effects": "dynamic_phase+detector_noise",
            "strehl_J": 0.8,
            "strehl_H": 0.9,
            "strehl_K": 0.95,
            "open_strehl_H": 0.5,
            "source_class": "synthetic_assumed",
            "source_note": "Focused artifact test row.",
            "config_hash": "a" * 64,
        }
    )
    return values


def _validation_row() -> dict[str, object]:
    values: dict[str, object] = {key: "" for key in VALIDATION_V2_HEADER}
    values.update(
        {
            "check_name": "focused_check",
            "passed": True,
            "metric_value": 0.0,
            "tolerance": 1.0,
            "message": "Focused validation row passes.",
            "source_class": "synthetic_assumed",
            "source_note": "Focused artifact test row.",
        }
    )
    return values


def _reference_v2() -> dict[str, object]:
    return {
        "schema_version": 2,
        "workflow": "fast_integration",
        "preset": "fast",
        "source_class": "synthetic_assumed",
        "source_note": "Focused artifact test record.",
        "config_hash": "a" * 64,
        "scenario_count": 1,
        "scenario_names": ["all_effects"],
        "reference_scenario": "all_effects",
        "open_rms_nm": 100.0,
        "closed_rms_nm": 40.0,
        "h_strehl": 0.9,
        "valid_centroid_fraction": 1.0,
        "kept_modes": 3,
        "runtime_band": "informational",
        "runtime_note": "Not an enforced portable benchmark.",
        "validation_pass_count": 1,
        "validation_check_count": 1,
        "tolerances": {
            "closed_rms_nm_abs": 15.0,
            "h_strehl_abs": 0.04,
            "kept_modes_abs": 0,
            "open_rms_nm_abs": 15.0,
            "runtime_s_reference_max": 30.0,
            "valid_centroid_fraction_abs": 1.0e-12,
        },
    }


def _result() -> SimpleNamespace:
    reference = _reference_v2()
    return SimpleNamespace(
        mode="fast",
        scenario_results=(_Row(_scenario_row()),),
        validation_results=(_Row(_validation_row()),),
        reference_metrics=reference,
        written_files=(),
        runtime_s=1.25,
        source_class="synthetic_assumed",
        config_hash=reference["config_hash"],
    )


def _v3_kwargs() -> dict[str, object]:
    digest = lambda character: "sha256:" + character * 64
    tolerance_specs = {
        "closed_rms_nm_abs": ("nm_opd_rms", "absolute", True),
        "h_strehl_abs": ("dimensionless", "absolute", True),
        "kept_modes_abs": ("count", "absolute", True),
        "open_rms_nm_abs": ("nm_opd_rms", "absolute", True),
        "runtime_s_reference_max": ("s", "reference_upper_bound", False),
        "valid_centroid_fraction_abs": ("dimensionless", "absolute", True),
    }
    return {
        "backend": "native",
        "system_profile": "fast_2m_detector",
        "provenance": Provenance(
            source_class="synthetic_assumed",
            source_note="Focused artifact test record.",
        ),
        "component_hashes": {
            key: digest("1")
            for key in (
                "geometry",
                "detector",
                "wfs_calibration",
                "dm",
                "interaction_matrix",
                "command_projector",
                "controller",
                "science_sampling",
            )
        },
        "layout_hashes": {
            "measurement_rows": digest("2"),
            "actuator_commands": digest("3"),
        },
        "conventions": {
            "wavefront_unit": "m_opd",
            "command_unit": "m_opd_equivalent",
            "residual_definition": "atmosphere_minus_dm_correction",
            "measurement_unit": "pixel",
        },
        "reproducibility": {
            "root_seed": 1,
            "rng_derivation_scheme_id": "shwfs_ao.seedsequence.v1",
            "random_stream_ids": {"atmosphere": "atmosphere"},
            "python_version": "3.test",
            "numpy_version": "2.test",
            "shwfs_ao_version": "0.test",
            "backend_version": "native.test",
            "constraints_sha256": digest("4"),
            "generator_version": "artifact-test.v1",
            "source_commit": None,
            "source_tree_clean": None,
            "source_patch_sha256": None,
            "generated_at_utc": "2026-07-16T00:00:00Z",
        },
        "tolerance_metadata": {
            key: {
                "unit": unit,
                "kind": kind,
                "enforced": enforced,
                "rationale": "Focused contract tolerance.",
            }
            for key, (unit, kind, enforced) in tolerance_specs.items()
        },
    }


def test_v2_writer_is_explicit_and_preserves_legacy_order(tmp_path, monkeypatch) -> None:
    output_dir = tmp_path / "not-created-by-config"
    reference_path = tmp_path / "references" / "fast_reference_metrics.json"
    config = ArtifactConfig(
        output_dir=output_dir,
        reference_metrics_path=reference_path,
        prefix="fast",
    )
    assert not output_dir.exists()
    assert not reference_path.parent.exists()

    monkeypatch.setattr(
        "shwfs_ao.io.artifacts._plot_scenario_summary",
        lambda path, rows: path.write_bytes(b"scenario-png"),
    )
    monkeypatch.setattr(
        "shwfs_ao.io.artifacts._plot_validation_summary",
        lambda path, rows: path.write_bytes(b"validation-png"),
    )
    written = write_integration_artifacts(_result(), config)
    assert [path.name for path in written] == [
        "fast_error_budget.csv",
        "fast_error_budget.png",
        "fast_validation.csv",
        "fast_validation.png",
        "fast_reference_metrics.json",
    ]
    assert read_scenario_table(written[0])[0]["scenario_name"] == "all_effects"
    assert read_validation_table(written[2])[0]["check_name"] == "focused_check"
    payload = json.loads(reference_path.read_text(encoding="utf-8"))
    assert list(payload) == sorted(payload)
    assert payload == _reference_v2()


def test_destination_collision_fails_before_creating_output_directory(tmp_path) -> None:
    output_dir = tmp_path / "untouched"
    config = ArtifactConfig(
        output_dir=output_dir,
        reference_metrics_path=output_dir / "fast_error_budget.csv",
        prefix="fast",
        write_figures=False,
    )
    with pytest.raises(ArtifactError, match="destinations must be unique"):
        write_integration_artifacts(_result(), config)
    assert not output_dir.exists()


def test_v3_upgrade_preserves_v2_values_and_requires_exact_metadata() -> None:
    original = _reference_v2()
    upgraded = upgrade_v2_to_v3(
        original,
        artifact_kind="run_result",
        **_v3_kwargs(),
    )
    assert upgraded["schema_version"] == 3
    assert upgraded["schema_name"] == "shwfs_ao.fast_reference_metrics"
    for key, value in original.items():
        if key != "schema_version":
            assert upgraded[key] == value
    assert upgraded["config_hash"] == original["config_hash"]
    assert read_v3(upgraded) == upgraded

    bad = _v3_kwargs()
    bad["tolerance_metadata"] = dict(bad["tolerance_metadata"])
    bad["tolerance_metadata"]["h_strehl_abs"] = {
        "unit": "nm",
        "kind": "absolute",
        "enforced": True,
        "rationale": "Wrong on purpose.",
    }
    with pytest.raises(ArtifactError, match="unit/kind/enforced"):
        upgrade_v2_to_v3(original, artifact_kind="run_result", **bad)


def test_v3_authority_branches_require_explicit_source_and_review_evidence() -> None:
    original = _reference_v2()

    run_kwargs = _v3_kwargs()
    with pytest.raises(ArtifactError, match="run_result forbids"):
        upgrade_v2_to_v3(
            original,
            artifact_kind="run_result",
            acceptance={"reason": "Not allowed.", "review_reference": "PR-1"},
            **run_kwargs,
        )

    candidate_kwargs = _v3_kwargs()
    with pytest.raises(ArtifactError, match="source_commit"):
        upgrade_v2_to_v3(
            original,
            artifact_kind="baseline_candidate",
            candidate_metadata={"based_on": "fast-v2"},
            diff_metadata={"changed_metrics": []},
            **candidate_kwargs,
        )

    evidence = dict(candidate_kwargs["reproducibility"])
    evidence.update(
        {
            "source_commit": "reviewed-commit",
            "source_tree_clean": False,
            "source_patch_sha256": "sha256:" + "5" * 64,
        }
    )
    candidate_kwargs["reproducibility"] = evidence
    candidate = upgrade_v2_to_v3(
        original,
        artifact_kind="baseline_candidate",
        candidate_metadata={"based_on": "fast-v2"},
        diff_metadata={"changed_metrics": []},
        **candidate_kwargs,
    )
    assert candidate["artifact_kind"] == "baseline_candidate"

    accepted_kwargs = _v3_kwargs()
    accepted_kwargs["reproducibility"] = evidence
    with pytest.raises(ArtifactError, match="review_reference"):
        upgrade_v2_to_v3(
            original,
            artifact_kind="accepted_regression_baseline",
            acceptance={"reason": "Reviewed physical change."},
            **accepted_kwargs,
        )
    accepted = upgrade_v2_to_v3(
        original,
        artifact_kind="accepted_regression_baseline",
        acceptance={
            "reason": "Reviewed physical change.",
            "review_reference": "PR-42",
        },
        **accepted_kwargs,
    )
    assert accepted["acceptance"]["review_reference"] == "PR-42"


def test_v3_writer_appends_columns_and_hashes_sidecars_and_manifest(tmp_path) -> None:
    config = ArtifactConfig(
        output_dir=tmp_path,
        prefix="fast",
        write_figures=False,
        write_runtime=True,
        schema_version=3,
        **_v3_kwargs(),
    )
    written = write_integration_artifacts(_result(), config)
    assert [path.name for path in written] == [
        "fast_error_budget.csv",
        "fast_validation.csv",
        "fast_reference_metrics.json",
        "fast_runtime.json",
        "fast_runtime.csv",
        "fast_error_budget.sidecar.json",
        "fast_validation.sidecar.json",
        "fast_runtime.sidecar.json",
        "fast_artifact_manifest.json",
    ]

    with written[0].open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    assert tuple(reader.fieldnames or ()) == SCENARIO_V2_HEADER + SCHEMA_V3_TABLE_COLUMNS
    assert rows[0]["artifact_schema_version"] == "3"
    assert read_scenario_table(written[0]) == tuple(rows)
    assert len(read_validation_table(written[1])) == 1
    assert len(read_runtime_table(tmp_path / "fast_runtime.csv")) == 1

    sidecar = json.loads((tmp_path / "fast_error_budget.sidecar.json").read_text(encoding="utf-8"))
    assert sidecar["header"] == list(SCENARIO_V2_HEADER + SCHEMA_V3_TABLE_COLUMNS)
    assert sidecar["row_order"] == ["all_effects"]
    assert sidecar["csv_sha256"].startswith("sha256:")
    manifest = json.loads((tmp_path / "fast_artifact_manifest.json").read_text(encoding="utf-8"))
    member_names = [record["filename"] for record in manifest["members"]]
    assert member_names == sorted(member_names)
    assert "fast_reference_metrics.json" in member_names


def test_csv_readers_reject_heuristic_schema_guessing(tmp_path) -> None:
    path = tmp_path / "scenario.csv"
    path.write_text("scenario_name,unexpected\nall_effects,value\n", encoding="utf-8")
    with pytest.raises(ArtifactError, match="schema guessing is disabled"):
        read_scenario_table(path)


def test_generic_runtime_writers_preserve_historical_field_order(tmp_path) -> None:
    record = {key: f"value-{index}" for index, key in enumerate(RUNTIME_V2_HEADER)}
    written = write_runtime_artifacts(
        record,
        output_dir=tmp_path,
        prefix="public_data_informed",
        formats=("json", "csv"),
        fieldnames=RUNTIME_V2_HEADER,
    )
    assert [path.name for path in written] == [
        "public_data_informed_runtime.json",
        "public_data_informed_runtime.csv",
    ]
    assert tuple(read_runtime_table(written[1])[0]) == RUNTIME_V2_HEADER


def test_v2_reader_uses_packaged_compatibility_name() -> None:
    payload = read_v2("data/reference_metrics/fast_reference_metrics.json")
    assert payload["schema_version"] == 2
    assert payload["workflow"] == "fast_integration"


def test_packaged_schemas_enforce_authority_branches_and_source_evidence(tmp_path) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    referencing = pytest.importorskip("referencing")
    from shwfs_ao.io.resources import read_text_resource

    schema_names = (
        "artifact_manifest.schema.json",
        "fast_reference_metrics.schema.json",
        "provenance.schema.json",
        "runtime_table_sidecar.schema.json",
        "scenario_table_sidecar.schema.json",
        "validation_table_sidecar.schema.json",
    )
    schemas = {
        name: json.loads(read_text_resource(f"schemas/{name}"))
        for name in schema_names
    }
    registry = referencing.Registry()
    for schema in schemas.values():
        registry = registry.with_resource(
            schema["$id"],
            referencing.Resource.from_contents(schema),
        )

    config = ArtifactConfig(
        output_dir=tmp_path,
        prefix="fast",
        write_figures=False,
        write_runtime=True,
        schema_version=3,
        **_v3_kwargs(),
    )
    write_integration_artifacts(_result(), config)
    artifact_schemas = {
        "fast_reference_metrics.json": "fast_reference_metrics.schema.json",
        "fast_error_budget.sidecar.json": "scenario_table_sidecar.schema.json",
        "fast_validation.sidecar.json": "validation_table_sidecar.schema.json",
        "fast_runtime.sidecar.json": "runtime_table_sidecar.schema.json",
        "fast_artifact_manifest.json": "artifact_manifest.schema.json",
    }

    for artifact_name, schema_name in artifact_schemas.items():
        payload = json.loads((tmp_path / artifact_name).read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(
            schemas[schema_name],
            registry=registry,
        )
        assert validator.is_valid(payload)

        run_with_acceptance = copy.deepcopy(payload)
        run_with_acceptance["acceptance"] = {
            "reason": "Ordinary runs cannot be accepted.",
            "review_reference": "PR-1",
        }
        assert not validator.is_valid(run_with_acceptance)

        candidate_without_source = copy.deepcopy(payload)
        candidate_without_source["artifact_kind"] = "baseline_candidate"
        candidate_without_source["candidate"] = {"based_on": "fast-v2"}
        candidate_without_source["diff"] = {"changed_metrics": []}
        assert not validator.is_valid(candidate_without_source)

        candidate_with_source = copy.deepcopy(candidate_without_source)
        candidate_with_source["reproducibility"].update(
            {
                "source_commit": "reviewed-commit",
                "source_tree_clean": False,
                "source_patch_sha256": "sha256:" + "6" * 64,
            }
        )
        assert validator.is_valid(candidate_with_source)

        accepted_without_source = copy.deepcopy(payload)
        accepted_without_source["artifact_kind"] = "accepted_regression_baseline"
        accepted_without_source["acceptance"] = {
            "reason": "Reviewed physical update.",
            "review_reference": "PR-42",
        }
        assert not validator.is_valid(accepted_without_source)

        accepted_with_source = copy.deepcopy(accepted_without_source)
        accepted_with_source["reproducibility"].update(
            {
                "source_commit": "reviewed-commit",
                "source_tree_clean": True,
                "source_patch_sha256": "sha256:" + "7" * 64,
            }
        )
        assert validator.is_valid(accepted_with_source)
