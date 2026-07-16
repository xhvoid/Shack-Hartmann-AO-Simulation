"""AO-REF-000 characterization gates for imports, packaging, CI, and artifacts.

These tests intentionally describe the current dirty-worktree snapshot.  They
must be reviewed and updated with the contract when a later ticket changes an
observed surface; they do not declare the dirty scientific baselines accepted.
"""

from __future__ import annotations

import ast
import csv
from dataclasses import MISSING, fields, is_dataclass
import hashlib
import importlib
import inspect
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import textwrap
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
LEGACY_ROOT = SOURCE_ROOT / "shwfs_ao" / "legacy"
RESOURCE_SOURCE_ROOT = SOURCE_ROOT / "shwfs_ao" / "resources"
MANIFEST_PATH = RESOURCE_SOURCE_ROOT / "reference_metrics/refactor_contract_manifest.json"
RESOURCE_MANIFEST_PATH = RESOURCE_SOURCE_ROOT / "resource_manifest.json"
AO_REF_011_PROFILE_RESOURCES = (
    "synthetic_presets/fast_2m_detector.v1.json",
    "synthetic_presets/portfolio_2m_detector.v1.json",
    "synthetic_presets/research_2m_detector.v1.json",
    "synthetic_presets/high_order_10m_geometric.v1.json",
)

# AO-REF-000 hashes remain historical pre-refactor evidence.  Later tickets
# that deliberately migrate a notebook's physical owner record the reviewed
# replacement hash here rather than rewriting that evidence in the manifest.
MIGRATED_NOTEBOOK_HASHES = {
    "notebooks/09_ao_psf_instrument_performance_high_order_ao.ipynb": {
        "ticket": "AO-REF-006",
        "source_sha256": "bf69fb32d65ec1a0c93622bbfe379f719ee27bddca08c4a3e3c779c95f17f615",
    },
}


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pyproject_modules() -> list[str]:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r"py-modules\s*=\s*\[(.*?)\]", text, flags=re.DOTALL)
    assert match is not None
    return re.findall(r'"([a-zA-Z0-9_]+)"', match.group(1))


def _current_resource_path(historical_path: str) -> Path:
    move_map = _manifest()["resources"]["ao_ref_001_explicit_resource_map"]
    transitional_path = move_map[historical_path]
    prefix = "src/ao_simulation_data/"
    if transitional_path.startswith(prefix):
        transitional_path = (
            "src/shwfs_ao/resources/" + transitional_path.removeprefix(prefix)
        )
    elif transitional_path == "src/ao_simulation_data/__init__.py":
        transitional_path = "src/shwfs_ao/resources/__init__.py"
    return ROOT / transitional_path


def _assert_implementation_free_shim(path: Path, module_name: str, public_names: list[str]) -> None:
    """Require re-export-only compatibility glue with no physical implementation."""

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    legacy_imports: list[str] = []
    implementation_alias_seen = False
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0
            if node.module == "shwfs_ao.legacy":
                assert len(node.names) == 1
                assert node.names[0].name == module_name
                assert node.names[0].asname == "_implementation"
                implementation_alias_seen = True
            else:
                assert node.module == f"shwfs_ao.legacy.{module_name}"
                legacy_imports.extend(alias.name for alias in node.names)
                assert all(alias.asname is None for alias in node.names)

    # Python 3.14 exposes the __future__.annotations feature object as a
    # module global; older supported interpreters do not. The tiny conditional
    # in each shim mirrors the relocated implementation on the running Python.
    assert implementation_alias_seen
    assert legacy_imports == [name for name in public_names if name != "annotations"]
    assert not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda))
        for node in ast.walk(tree)
    )


def _serialized_default(value):
    if isinstance(value, tuple):
        return {"items": [_serialized_default(item) for item in value], "type": "tuple"}
    if isinstance(value, Path):
        return {"type": f"{type(value).__module__}.{type(value).__name__}", "value": str(value)}
    return value


def test_manifest_has_explicit_dirty_snapshot_authority_and_ticket_boundary():
    manifest = _manifest()

    assert manifest["schema_name"] == "ao_ref_000_refactor_contract_manifest"
    assert manifest["schema_version"] == 1
    assert manifest["ticket"] == "AO-REF-000"
    assert manifest["scope"]["source_commit"] == "9c4816c094249b49d4f9a1fd182e39ea264252e5"
    assert manifest["scope"]["pre_ticket_status_entry_count"] == 73
    assert manifest["scope"]["pre_ticket_tracked_binary_diff_sha256"] == (
        "20bb3521bed2fbdf4e04e9960638661d5897c84bd8fd9167fbe6ad052ebeb36d"
    )
    assert "not acceptance" in manifest["scope"]["authority"]
    assert manifest["acceptance"] == {
        "accepted_baseline_regenerated": False,
        "constrained_ci_status": "pending external Python 3.10 and exact-pinned Python 3.14 CI execution; local characterization is green but does not match either Linux constraint file",
        "implementation_files_moved": False,
        "next_ticket": "AO-REF-001 is blocked pending independent acceptance of this contract",
        "numerical_implementation_changed": False,
        "public_import_removed": False,
    }


def test_all_legacy_import_names_are_exact_silent_shims_over_relocated_implementations():
    manifest = _manifest()
    records = manifest["public_api"]["modules"]
    expected_modules = [record["name"] for record in records]

    assert expected_modules == _pyproject_modules()
    assert len(expected_modules) == 19
    assert manifest["public_api"]["runtime_public_name_count"] == 504
    assert manifest["public_api"]["explicit_all_module_count"] == 0

    for record in records:
        module = importlib.import_module(record["import_path"])
        legacy_module = importlib.import_module(f"shwfs_ao.legacy.{record['name']}")
        expected_names = [
            name
            for name in record["runtime_public_names"]
            if name != "annotations" or hasattr(legacy_module, "annotations")
        ]
        actual_names = sorted(name for name in vars(module) if not name.startswith("_"))
        legacy_names = sorted(name for name in vars(legacy_module) if not name.startswith("_"))
        assert actual_names == expected_names, record["name"]
        assert legacy_names == expected_names, record["name"]
        assert module.__all__ == tuple(expected_names)
        assert all(getattr(module, name) is getattr(legacy_module, name) for name in expected_names)
        star_namespace: dict[str, object] = {}
        exec(f"from {record['name']} import *", star_namespace)
        assert sorted(name for name in star_namespace if not name.startswith("_")) == expected_names
        assert len(actual_names) == len(expected_names)
        assert len(record["source_sha256"]) == 64  # AO-REF-000 historical source evidence
        assert Path(module.__file__).resolve() == (SOURCE_ROOT / f"{record['name']}.py").resolve()
        assert Path(legacy_module.__file__).resolve() == (LEGACY_ROOT / f"{record['name']}.py").resolve()
        _assert_implementation_free_shim(
            SOURCE_ROOT / f"{record['name']}.py",
            record["name"],
            expected_names,
        )
        for symbol in record["module_owned_symbols"]:
            expected_signature = symbol["runtime_signature"]
            if expected_signature is not None:
                actual_signature = inspect.signature(getattr(module, symbol["name"]))
                if record["name"] == "data_sources" and symbol["name"] == "Provenance":
                    # AO-REF-003 moves this class to core and adds only the
                    # trailing structured-record field. The six historical
                    # positional parameters remain in their original order.
                    assert list(actual_signature.parameters) == [
                        "source_class",
                        "source_note",
                        "source_id",
                        "url",
                        "access_time",
                        "fallback_used",
                        "references",
                    ]
                elif (
                    record["name"] == "synthetic_instrument_data"
                    and symbol["name"] == "DetectorConfig"
                ):
                    # AO-REF-004 preserves the historical eleven positional
                    # fields and adds only explicit trailing realization policy.
                    assert list(actual_signature.parameters) == [
                        "photons_per_subap_frame",
                        "read_noise_e",
                        "dark_e_per_s",
                        "background_e_per_pixel_frame",
                        "full_well_e",
                        "qe",
                        "bad_pixel_mask",
                        "prnu_rms",
                        "exposure_s",
                        "source_class",
                        "source_note",
                        "prnu_mode",
                        "bad_pixel_fraction",
                    ]
                    assert actual_signature.parameters["prnu_mode"].default == (
                        "per_frame_legacy"
                    )
                    assert actual_signature.parameters["bad_pixel_fraction"].default == 0.0
                else:
                    assert str(actual_signature) == expected_signature
        for class_record in record["public_classes"]:
            cls = getattr(module, class_record["name"])
            if class_record["dataclass_fields"]:
                assert is_dataclass(cls)
                actual_fields = fields(cls)
                expected_fields = class_record["dataclass_fields"]
                expected_names = [field["name"] for field in expected_fields]
                actual_names = [field.name for field in actual_fields]
                provenance_extension = (
                    record["name"] == "data_sources"
                    and class_record["name"] == "Provenance"
                )
                detector_extension = (
                    record["name"] == "synthetic_instrument_data"
                    and class_record["name"] == "DetectorConfig"
                )
                if provenance_extension:
                    assert actual_names == [*expected_names, "references"]
                    assert actual_fields[-1].default == ()
                elif detector_extension:
                    assert actual_names == [
                        *expected_names,
                        "prnu_mode",
                        "bad_pixel_fraction",
                    ]
                    assert repr(actual_fields[-2].type) == "'PrnuMode'"
                    assert actual_fields[-2].default == "per_frame_legacy"
                    assert repr(actual_fields[-1].type) == "'float'"
                    assert actual_fields[-1].default == 0.0
                else:
                    assert actual_names == expected_names
                for actual_field, expected_field in zip(actual_fields, expected_fields):
                    if not (provenance_extension and actual_field.name == "source_class"):
                        assert repr(actual_field.type) == expected_field["annotation"]
                    assert actual_field.init == expected_field["init"]
                    assert actual_field.repr == expected_field["repr"]
                    assert actual_field.compare == expected_field["compare"]
                    assert actual_field.kw_only == expected_field["kw_only"]
                    expected_default = expected_field["default"]
                    if expected_default is None:
                        assert actual_field.default is MISSING
                    else:
                        assert expected_default["kind"] == "value"
                        assert _serialized_default(actual_field.default) == expected_default["value"]
            for member in class_record["public_members"]:
                expected_signature = member["runtime_signature"]
                if expected_signature is None:
                    continue
                raw_member = vars(cls)[member["name"]]
                if isinstance(raw_member, property):
                    raw_member = raw_member.fget
                elif isinstance(raw_member, (classmethod, staticmethod)):
                    raw_member = raw_member.__func__
                assert str(inspect.signature(raw_member)) == expected_signature
        disposition = record["ao_ref_001_disposition"]
        assert disposition["implementation_move"] == f"src/shwfs_ao/legacy/{record['name']}.py"
        assert disposition["installed_compatibility_shim"] == f"src/{record['name']}.py"


def test_historical_edges_are_retained_as_evidence_and_provenance_moves_to_core():
    contract = _manifest()["internal_import_contract"]
    edges = {(edge["source"], edge["target"]) for edge in contract["edges"]}
    module_names = {record["name"] for record in _manifest()["public_api"]["modules"]}

    assert len(edges) == contract["edge_count"] == 49
    assert set(contract["provenance_taxonomy_consumers"]) == {
        "ao_closed_loop",
        "ao_conditions",
        "ao_diagnostics",
        "ao_error_budget",
        "ao_integration",
        "ao_validation",
        "atmosphere_profiles",
        "dm_model",
        "interaction_matrix",
        "synthetic_instrument_data",
    }
    assert ("data_sources", "runtime_resources") in edges
    assert any(
        edge["source"] == "ao_closed_loop"
        and edge["target"] == "interaction_matrix"
        and any(occurrence["line"] == 412 for occurrence in edge["occurrences"])
        for edge in contract["edges"]
    )

    canonical_taxonomy_consumers: set[str] = set()
    for source in sorted(module_names):
        path = LEGACY_ROOT / f"{source}.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] not in module_names for alias in node.names), (
                    path,
                    node.lineno,
                )
            if not isinstance(node, ast.ImportFrom):
                continue
            imported_names = {alias.name for alias in node.names}
            if node.module == "data_sources":
                assert node.level == 1
                assert "ALLOWED_SOURCE_CLASSES" not in imported_names
                assert "Provenance" not in imported_names
            if node.module == "core.provenance" and node.level == 2:
                if "ALLOWED_SOURCE_CLASSES" in imported_names:
                    canonical_taxonomy_consumers.add(source)

    assert canonical_taxonomy_consumers == set(
        contract["provenance_taxonomy_consumers"]
    )

    # The compatibility module is now a pure explicit facade over the core
    # model and I/O loader module, rather than the owner of either concept.
    data_sources_tree = ast.parse(
        (LEGACY_ROOT / "data_sources.py").read_text(encoding="utf-8")
    )
    assert not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda))
        for node in ast.walk(data_sources_tree)
    )

    # Canonical package code may use explicit package imports, but never the
    # installed top-level compatibility names as sibling dependencies.
    for path in (SOURCE_ROOT / "shwfs_ao").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] not in module_names for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                assert node.module.split(".")[0] not in module_names


def test_relocated_resource_names_hashes_and_legacy_lookup_aliases_are_frozen(tmp_path, monkeypatch):
    manifest = _manifest()
    resources = manifest["resources"]
    package_data = resources["pre_ticket_package_data"]

    assert resources["pre_ticket_package_data_count"] == len(package_data) == 20
    package_code = _current_resource_path(resources["package_code"]["source_path"])
    assert _sha256(package_code) == resources["package_code"]["sha256"]

    from runtime_resources import open_text_resource

    # Keep CWD override precedence intact while checking the package aliases in
    # a directory that does not contain colliding names such as README.md.
    monkeypatch.chdir(tmp_path)
    for record in package_data:
        source = _current_resource_path(record["source_path"])
        assert source.is_file()
        assert _sha256(source) == record["sha256"]
        aliases = [f"data/{record['logical_name']}"]
        # The historical source-repository override intentionally wins for a
        # colliding unprefixed name (the project README is the one collision).
        if not (ROOT / record["logical_name"]).is_file():
            aliases.append(record["logical_name"])
        for alias in aliases:
            with open_text_resource(alias, encoding="utf-8", newline="") as handle:
                assert hashlib.sha256(handle.read().encode("utf-8")).hexdigest() == record["sha256"]

    assert MANIFEST_PATH.is_file()
    assert resources["ao_ref_000_manifest_resource"]["sha256"] is None
    expected_move_map = {
        resources["package_code"]["source_path"]: "src/ao_simulation_data/__init__.py",
        **{
            record["source_path"]: f"src/ao_simulation_data/{record['logical_name']}"
            for record in package_data
        },
        resources["ao_ref_000_manifest_resource"]["source_path"]: (
            "src/ao_simulation_data/reference_metrics/refactor_contract_manifest.json"
        ),
    }
    assert resources["ao_ref_001_explicit_resource_map"] == expected_move_map
    assert all(_current_resource_path(source).is_file() for source in expected_move_map)


def test_current_ci_matrix_constraint_hashes_and_installed_smoke_gates_remain_frozen():
    manifest = _manifest()
    contract = manifest["ci_contract"]
    workflow_path = ROOT / contract["workflow_path"]
    workflow = workflow_path.read_text(encoding="utf-8")

    # The workflow and pyproject hashes are AO-REF-000 historical evidence;
    # AO-REF-001 intentionally changes their packaging/resource-path lines.
    assert len(contract["workflow_sha256"]) == 64
    assert len(manifest["distribution"]["pyproject_sha256"]) == 64
    assert [(item["python"], item["constraints"]) for item in contract["matrix"]] == [
        ("3.10", "constraints/py310.txt"),
        ("3.14", "constraints/py314.txt"),
    ]
    for item in contract["matrix"]:
        constraint_path = ROOT / item["constraints"]
        assert constraint_path.is_file()
        assert _sha256(constraint_path) == item["constraints_sha256"]
        assert f'python-version: "{item["python"]}"' in workflow
        assert f'constraints: {item["constraints"]}' in workflow

    assert "python -m pip check" in workflow
    assert "python -m pytest -q" in workflow
    assert '-e ".[test]"' in workflow
    for example in contract["smoke_examples_python_3_14"]:
        assert example in workflow
    assert (
        "git diff --exit-code -- src/shwfs_ao/resources/reference_metrics "
        "src/shwfs_ao/resources/resource_manifest.json figures/detector_level_SCAO"
    ) in workflow

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'package-dir = {"" = "src", "build_support" = "build_support"}' in pyproject
    assert '[tool.setuptools.packages.find]' in pyproject
    assert 'include = ["shwfs_ao*"]' in pyproject
    assert '[tool.setuptools.cmdclass]' in pyproject
    assert 'build_py = "build_support.resource_alias.BuildPyWithResourceAlias"' in pyproject
    assert (
        'editable_wheel = "build_support.resource_alias.EditableWheelWithResourceAlias"'
        in pyproject
    )
    assert 'pythonpath = ["src"]' not in pyproject


def test_schema_2_json_and_semantic_csv_artifacts_are_frozen_without_acceptance():
    contract = _manifest()["artifacts"]
    assert "does not accept" in contract["authority_warning"]

    for record in contract["files"]:
        path = _current_resource_path(record["path"])
        assert record["working_tree_state"] == "modified_relative_to_HEAD"
        assert record["authority"] == "unaccepted_working_tree_observation"
        assert record["working_tree_sha256"] != record["HEAD_sha256"]
        assert _sha256(path) == record["working_tree_sha256"]
        if path.suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            assert payload["schema_version"] == record["schema_version"] == 2
            assert list(payload) == record["ordered_fields"]
            assert payload == record["payload_snapshot"]
        else:
            with path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            assert list(rows[0]) == record["ordered_fields"]
            assert len(rows) == record["row_count"]
            identities = [row.get("scenario_name") or row.get("check_name") for row in rows]
            assert identities == record["row_identity"]

    updater = (ROOT / "scripts/update_fast_regression_baselines.py").read_text(encoding="utf-8")
    assert "--accept-baseline-update" in updater
    assert contract["semantic_csv_comparison"] == {
        "absolute_tolerance": 2e-8,
        "relative_tolerance": 2e-6,
    }


def test_all_notebooks_have_one_stable_disposition_and_reviewed_source_hash():
    contract = _manifest()["notebooks"]
    records = contract["items"]
    paths = {record["path"] for record in records}

    assert contract["count"] == len(records) == 16
    assert len({record["id"] for record in records}) == 16
    assert paths == {
        str(path.relative_to(ROOT)) for path in (ROOT / "notebooks").glob("*.ipynb")
    }
    assert sum(record["modifies_sys_path"] for record in records) == 8
    assert all(record["network_access"] == "none_detected" for record in records)
    for record in records:
        migration = MIGRATED_NOTEBOOK_HASHES.get(record["path"])
        expected_hash = (
            record["source_sha256"]
            if migration is None
            else migration["source_sha256"]
        )
        assert _sha256(ROOT / record["path"]) == expected_hash
        assert record["replacement_target"].endswith(".ipynb")
        assert "retain until AO-REF-019 acceptance" in record["disposition"]

    assert set(MIGRATED_NOTEBOOK_HASHES) <= paths
    assert {
        migration["ticket"] for migration in MIGRATED_NOTEBOOK_HASHES.values()
    } == {"AO-REF-006"}


def test_examples_scripts_keep_the_fast_smoke_set_without_source_path_injection():
    manifest = _manifest()
    contract = manifest["entry_points"]
    entries = contract["examples_and_scripts"]
    examples = [entry for entry in entries if entry["kind"] == "example"]

    assert contract["installed_console_entry_points"] == []
    assert len(entries) == 12
    assert len(examples) == 9
    assert all(entry["has_main_guard"] for entry in entries)
    assert all(entry["sys_path_mutations"] for entry in examples)  # historical AO-REF-000 evidence
    assert set(contract["required_fast_smoke_set"]) == {
        "examples/run_psf_strehl_demo.py",
        "examples/run_shwfs_centroid_demo.py",
        "examples/run_public_data_overview.py",
        "examples/run_fast_integration.py",
    }
    for entry in entries:
        path = ROOT / entry["path"]
        assert path.is_file()
        assert len(entry["source_sha256"]) == 64
        assert "sys.path.insert" not in path.read_text(encoding="utf-8")


def test_rng_inventory_retains_historical_evidence_and_tracks_component_migrations():
    contract = _manifest()["rng_contract"]
    recorded_owners = [
        item["owner"] for item in contract["source_default_rng_call_sites"]
    ]
    assert all(item["line"] > 0 for item in contract["source_default_rng_call_sites"])

    actual_owners: list[str] = []
    for path in LEGACY_ROOT.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for function in (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            local_calls = sum(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "default_rng"
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "random"
                and isinstance(node.func.value.value, ast.Name)
                and node.func.value.value.id == "np"
                for node in ast.walk(function)
            )
            actual_owners.extend(
                [f"{path.stem}.{function.name}"] * local_calls
            )

    migrated_owners = {
        "ao_error_budget.build_control_space_phase_sequence",
        "shwfs_detector.add_detector_noise",
        "shwfs_detector.measure_centroid_shifts",
        "synthetic_instrument_data.add_configured_detector_noise",
        "synthetic_instrument_data.make_bad_pixel_mask",
        "synthetic_instrument_data.measure_detector_shwfs",
        "pwfs_forward.add_detector_noise",
    }
    assert sorted(actual_owners) == sorted(
        owner for owner in recorded_owners if owner not in migrated_owners
    )
    assert len(actual_owners) == contract["audited_default_rng_call_site_count"] - 7 == 7
    canonical_detector_rng_owners: list[str] = []
    for path in (SOURCE_ROOT / "shwfs_ao" / "detector").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for function in (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            if any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "default_rng"
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "random"
                and isinstance(node.func.value.value, ast.Name)
                and node.func.value.value.id == "np"
                for node in ast.walk(function)
            ):
                canonical_detector_rng_owners.append(f"{path.stem}.{function.name}")
    assert sorted(canonical_detector_rng_owners) == [
        "config.make_bad_pixel_mask",
        "effects._legacy_generator",
    ]
    experimental_pwfs = SOURCE_ROOT / "shwfs_ao" / "experimental" / "pwfs.py"
    pwfs_tree = ast.parse(
        experimental_pwfs.read_text(encoding="utf-8"),
        filename=str(experimental_pwfs),
    )
    experimental_rng_owners = [
        f"pwfs.{function.name}"
        for function in ast.walk(pwfs_tree)
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "default_rng"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "random"
            and isinstance(node.func.value.value, ast.Name)
            and node.func.value.value.id == "np"
            for node in ast.walk(function)
        )
    ]
    assert experimental_rng_owners == ["pwfs.add_detector_noise"]
    entry_owners = {item["owner"] for item in contract["entry_points"]}
    assert {item["owner"] for item in contract["source_default_rng_call_sites"]} <= entry_owners
    assert {item["owner"] for item in contract["coupled_seed_routing_without_local_generator"]} == {
        "ao_closed_loop.gain_scan",
        "ao_validation.check_centroid_noise_photon_monotonicity",
        "pwfs_forward.pwfs_detector_signal_from_phase",
        "pwfs_forward.pwfs_detector_measurement_from_phase",
    }


def test_noneditable_wheel_imports_every_module_and_reads_every_resource_outside_checkout(tmp_path):
    manifest = _manifest()
    wheel_dir = tmp_path / "wheel"
    site_dir = tmp_path / "site"
    wheel_dir.mkdir()
    site_dir.mkdir()

    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            ".",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheel_dir),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(wheel_dir.glob("*.whl"))
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--target", str(site_dir), str(wheel)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    module_records = [
        {
            "name": record["name"],
            "public_names": record["runtime_public_names"],
        }
        for record in manifest["public_api"]["modules"]
    ]
    checked_manifest = json.loads(RESOURCE_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert checked_manifest["schema_name"] == "shwfs_ao.resource_manifest"
    assert checked_manifest["schema_version"] == 1
    resource_records = list(checked_manifest["resources"])
    resource_records = [
        {"name": record["logical_name"], "sha256": record["sha256"]}
        for record in resource_records
    ] + [
        {
            "name": RESOURCE_MANIFEST_PATH.name,
            "sha256": _sha256(RESOURCE_MANIFEST_PATH),
        }
    ]
    expected_path = tmp_path / "expected.json"
    expected_path.write_text(
        json.dumps({"modules": module_records, "resources": resource_records}),
        encoding="utf-8",
    )

    with zipfile.ZipFile(wheel) as archive:
        members = set(archive.namelist())
    expected_data_members = {"ao_simulation_data/__init__.py"} | {
        f"ao_simulation_data/{record['name']}" for record in resource_records
    }
    assert {member for member in members if member.startswith("ao_simulation_data/")} == expected_data_members
    expected_canonical_members = {
        member.replace("ao_simulation_data/", "shwfs_ao/resources/", 1)
        for member in expected_data_members
    }
    assert {
        member for member in members if member.startswith("shwfs_ao/resources/")
    } == expected_canonical_members
    assert {f"{record['name']}.py" for record in module_records} <= members
    assert {"shwfs_ao/__init__.py", "shwfs_ao/legacy/__init__.py"} <= members
    assert {
        f"shwfs_ao/legacy/{record['name']}.py" for record in module_records
    } <= members
    assert any(member.endswith(".dist-info/licenses/LICENSE") for member in members)
    assert any(member.endswith(".dist-info/licenses/DATA_LICENSES.md") for member in members)

    smoke_code = textwrap.dedent(
        """
        import contextlib
        import hashlib
        import importlib
        import importlib.resources as ir
        import json
        import pathlib
        import sys

        site = pathlib.Path(sys.argv[1]).resolve()
        expected = json.loads(pathlib.Path(sys.argv[2]).read_text())
        sys.path.insert(0, str(site))
        import shwfs_ao
        assert shwfs_ao.__version__
        mods = [importlib.import_module(record["name"]) for record in expected["modules"]]
        legacy_mods = [
            importlib.import_module("shwfs_ao.legacy." + record["name"])
            for record in expected["modules"]
        ]
        assert all(pathlib.Path(mod.__file__).resolve().is_relative_to(site) for mod in mods + legacy_mods)
        for mod, legacy_mod, record in zip(mods, legacy_mods, expected["modules"]):
            expected_public_names = [
                name
                for name in record["public_names"]
                if name != "annotations" or hasattr(legacy_mod, "annotations")
            ]
            public_names = sorted(name for name in vars(mod) if not name.startswith("_"))
            assert public_names == expected_public_names
            assert sorted(name for name in vars(legacy_mod) if not name.startswith("_")) == expected_public_names
            assert mod.__all__ == tuple(expected_public_names)
            assert all(getattr(mod, name) is getattr(legacy_mod, name) for name in expected_public_names)
            namespace = {}
            exec(f"from {record['name']} import *", namespace)
            assert sorted(name for name in namespace if not name.startswith("_")) == expected_public_names

        data_package = importlib.import_module("ao_simulation_data")
        assert pathlib.Path(data_package.__file__).resolve().is_relative_to(site)
        canonical_package = importlib.import_module("shwfs_ao.resources")
        assert pathlib.Path(canonical_package.__file__).resolve().is_relative_to(site)
        root = ir.files("ao_simulation_data")
        canonical_root = ir.files("shwfs_ao.resources")
        payloads = [
            root.joinpath(*record["name"].split("/")).read_bytes()
            for record in expected["resources"]
        ]
        canonical_payloads = [
            canonical_root.joinpath(*record["name"].split("/")).read_bytes()
            for record in expected["resources"]
        ]
        assert canonical_payloads == payloads
        assert all(payloads)
        assert all(
            hashlib.sha256(payload).hexdigest() == record["sha256"]
            for payload, record in zip(payloads, expected["resources"])
        )

        rr = importlib.import_module("runtime_resources")
        with contextlib.ExitStack() as stack:
            alias_records = [
                (alias, record["sha256"])
                for record in expected["resources"]
                for alias in (record["name"], "data/" + record["name"])
            ]
            alias_payloads = [
                stack.enter_context(rr.open_text_resource(alias, newline="")).read().encode("utf-8")
                for alias, _expected_hash in alias_records
            ]
        assert all(
            hashlib.sha256(payload).hexdigest() == expected_hash
            for payload, (_alias, expected_hash) in zip(alias_payloads, alias_records)
        )
        print(f"installed-contract-smoke-ok:{len(mods)}:{len(payloads)}")
        """
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["MPLCONFIGDIR"] = str(tmp_path / "mpl")
    result = subprocess.run(
        [sys.executable, "-I", "-c", smoke_code, str(site_dir), str(expected_path)],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == f"installed-contract-smoke-ok:{len(module_records)}:{len(resource_records)}"
