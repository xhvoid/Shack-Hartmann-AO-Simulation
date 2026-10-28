"""AO-REF-012 canonical-resource and generated-alias contracts."""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import pytest

from build_support.resource_alias import (
    ResourceManifestError,
    load_checked_manifest,
    render_resource_manifest as render_build_manifest,
)
from shwfs_ao.io import resources
from shwfs_ao.legacy import runtime_resources as legacy_resources


ROOT = Path(__file__).resolve().parents[2]
CANONICAL_ROOT = ROOT / "src" / "shwfs_ao" / "resources"
REQUIRED_SCHEMAS = {
    "artifact_manifest.schema.json",
    "cross_backend_baseline.schema.json",
    "fast_reference_metrics.schema.json",
    "provenance.schema.json",
    "runtime_table_sidecar.schema.json",
    "scenario_table_sidecar.schema.json",
    "validation_table_sidecar.schema.json",
}
LEGACY_PUBLIC_NAMES = {
    "Iterator",
    "Path",
    "RESOURCE_PACKAGE",
    "SOURCE_REPOSITORY_ROOT",
    "TextIO",
    "annotations",
    "contextmanager",
    "normalized_resource_name",
    "open_text_resource",
    "resource_exists",
    "resources",
}


def test_canonical_tree_is_complete_and_source_alias_is_absent() -> None:
    assert CANONICAL_ROOT.is_dir()
    assert not (ROOT / "src" / "ao_simulation_data").exists()

    manifest_path = CANONICAL_ROOT / resources.RESOURCE_MANIFEST_NAME
    manifest = resources.load_resource_manifest()
    names = [record["logical_name"] for record in manifest["resources"]]
    actual_names = sorted(
        path.relative_to(CANONICAL_ROOT).as_posix()
        for path in CANONICAL_ROOT.rglob("*")
        if path.is_file()
        and path != manifest_path
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    )
    assert names == actual_names
    assert manifest_path.read_text(encoding="utf-8") == resources.render_resource_manifest(
        CANONICAL_ROOT
    )
    assert manifest_path.read_text(encoding="utf-8") == render_build_manifest(
        CANONICAL_ROOT
    )


def test_all_required_versioned_schemas_are_packaged_and_parseable() -> None:
    schema_names = {
        record["logical_name"].removeprefix("schemas/")
        for record in resources.load_resource_manifest()["resources"]
        if record["logical_name"].startswith("schemas/")
        and record["logical_name"].endswith(".schema.json")
    }
    assert schema_names == REQUIRED_SCHEMAS
    for name in sorted(REQUIRED_SCHEMAS):
        payload = json.loads(resources.read_text_resource(f"schemas/{name}"))
        assert payload["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert payload["$id"].endswith(name)


def test_package_loading_needs_no_checkout_git_or_writable_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    read_only = tmp_path / "read-only"
    read_only.mkdir()
    read_only.chmod(0o555)
    monkeypatch.chdir(read_only)
    try:
        expected = (
            "944f2e7086b003205fdfa0b6e0d8f1b744fe06b10d402747357fea159d73aaa5"
        )
        payload = resources.read_binary_resource(
            "samples/eso_asm_snapshot_sample.json"
        )
        assert hashlib.sha256(payload).hexdigest() == expected
        with legacy_resources.open_text_resource(
            "data/samples/eso_asm_snapshot_sample.json", newline=""
        ) as handle:
            assert hashlib.sha256(handle.read().encode("utf-8")).hexdigest() == expected
    finally:
        read_only.chmod(0o755)


@pytest.mark.parametrize(
    "name",
    ("", ".", "..", "../secret", "a/../../secret", "/absolute", "a\\b"),
)
def test_resource_names_reject_unsafe_traversal(name: str) -> None:
    with pytest.raises(ValueError, match="Invalid package resource path"):
        resources.normalized_resource_name(name)


def test_legacy_facade_preserves_frozen_surface_signatures_and_constant_values() -> None:
    public_names = {name for name in vars(legacy_resources) if not name.startswith("_")}
    if not hasattr(legacy_resources, "annotations"):
        expected_names = LEGACY_PUBLIC_NAMES - {"annotations"}
    else:
        expected_names = LEGACY_PUBLIC_NAMES
    assert public_names == expected_names
    assert legacy_resources.RESOURCE_PACKAGE == "ao_simulation_data"
    assert legacy_resources.SOURCE_REPOSITORY_ROOT == ROOT
    for name in ("normalized_resource_name", "resource_exists", "open_text_resource"):
        assert getattr(legacy_resources, name) is getattr(resources, name)
        assert inspect.signature(getattr(legacy_resources, name)) == inspect.signature(
            getattr(resources, name)
        )


def test_build_manifest_rejects_untracked_or_tampered_payloads(tmp_path: Path) -> None:
    source = tmp_path / "resources"
    source.mkdir()
    payload = source / "fixture.json"
    payload.write_text("{}\n", encoding="utf-8")
    manifest = source / "resource_manifest.json"
    manifest.write_text(render_build_manifest(source), encoding="utf-8")
    assert [record.logical_name for record in load_checked_manifest(source)] == [
        "fixture.json"
    ]

    payload.write_text('{"changed": true}\n', encoding="utf-8")
    with pytest.raises(ResourceManifestError, match="has SHA-256"):
        load_checked_manifest(source)

    payload.write_text("{}\n", encoding="utf-8")
    (source / "untracked.csv").write_text("x\n1\n", encoding="utf-8")
    with pytest.raises(ResourceManifestError, match="inventory differs"):
        load_checked_manifest(source)
