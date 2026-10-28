"""AO-REF-021 Phase A isolation, deprecation-warning, and clock gates.

These tests are the authoritative behavioral contract for Phase A:

- every installed root-level shim and the ``ao_simulation_data`` resource alias
  emit exactly one import-time ``DeprecationWarning`` that names a canonical
  replacement, with ``stacklevel=2``;
- ``import shwfs_ao`` and the canonical/``shwfs_ao.legacy`` imports stay silent;
- the packaged deprecation clock and inventory are internally consistent and
  the earliest-removal boundary is computed, not merely asserted.
"""

from __future__ import annotations

import ast
import datetime
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from shwfs_ao import _deprecation


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
LEGACY_DIR = SRC / "shwfs_ao" / "legacy"

ROOT_SHIM_MODULES = (
    "ao_closed_loop",
    "ao_conditions",
    "ao_diagnostics",
    "ao_error_budget",
    "ao_integration",
    "ao_validation",
    "atmosphere_profiles",
    "config_hashing",
    "data_sources",
    "dm_model",
    "interaction_matrix",
    "phase_screen",
    "psf_tools",
    "pwfs_forward",
    "reconstruction",
    "runtime_resources",
    "shwfs_detector",
    "synthetic_instrument_data",
    "zernike",
)


# --------------------------------------------------------------------------- #
# Subprocess warning-capture helper                                           #
# --------------------------------------------------------------------------- #

_RUNNER_TEMPLATE = """\
import json
import sys
import warnings

captured = []
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
{body}
for item in caught:
    captured.append(
        {{
            "category": item.category.__name__,
            "message": str(item.message),
            "filename": item.filename,
            "lineno": item.lineno,
        }}
    )
print(json.dumps(captured))
"""


def _run_capture(tmp_path: Path, body_lines: list[str]) -> tuple[list[dict], dict[str, int]]:
    """Run ``body_lines`` in a fresh interpreter and return recorded warnings.

    Also returns a map from each stripped source line to its 1-indexed line
    number in the generated runner, so a caller can assert that a warning's
    ``stacklevel`` attributes it to the importing statement.
    """

    body = "\n".join("    " + line for line in body_lines)
    script = _RUNNER_TEMPLATE.format(body=body)
    runner = tmp_path / "runner.py"
    runner.write_text(script, encoding="utf-8")
    line_numbers = {}
    for index, raw in enumerate(script.splitlines(), start=1):
        stripped = raw.strip()
        if stripped:
            line_numbers.setdefault(stripped, index)
    result = subprocess.run(
        [sys.executable, str(runner)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout), line_numbers


def _deprecations(records: list[dict]) -> list[dict]:
    return [item for item in records if item["category"] == "DeprecationWarning"]


# --------------------------------------------------------------------------- #
# Import-time warning behavior                                                 #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("module_name", ROOT_SHIM_MODULES)
def test_each_root_shim_warns_once_with_replacement(tmp_path, module_name):
    records, _ = _run_capture(tmp_path, [f"import {module_name}"])
    deprecations = _deprecations(records)
    assert len(deprecations) == 1, records
    message = deprecations[0]["message"]
    assert module_name in message
    assert "deprecated" in message.lower()
    # Names a canonical shwfs_ao replacement and the planned removal release.
    assert "shwfs_ao" in message
    clock = _deprecation.deprecation_clock()
    assert clock["planned_removal_release"] in message
    assert clock["deprecation_release"] in message
    # The release claim must match the recorded publication state: an
    # unpublished deprecation release is announced as scheduled, never
    # asserted as an accomplished release.
    release = clock["deprecation_release"]
    if clock["publication_status"] == "published":
        assert f"as of release {release}" in message
    else:
        assert f"scheduled for release {release}, not yet published" in message
        assert f"as of release {release}" not in message


def test_import_shwfs_ao_is_silent(tmp_path):
    records, _ = _run_capture(tmp_path, ["import shwfs_ao"])
    assert _deprecations(records) == []


@pytest.mark.parametrize(
    "module_name",
    [
        "shwfs_ao.dm",
        "shwfs_ao.control",
        "shwfs_ao.calibration",
        "shwfs_ao.detector",
        "shwfs_ao.science.metrics",
        "shwfs_ao.science.bandpass",
        "shwfs_ao.experiments.scao",
        "shwfs_ao.experiments.error_budget",
        "shwfs_ao.experiments.integration",
        "shwfs_ao.experiments.scenario_instrument",
        "shwfs_ao.validation.checks",
        "shwfs_ao.io.resources",
        "shwfs_ao.backends.native.atmosphere",
        "shwfs_ao.core.hashing",
    ],
)
def test_canonical_imports_are_silent(tmp_path, module_name):
    records, _ = _run_capture(tmp_path, [f"import {module_name}"])
    assert _deprecations(records) == [], (module_name, records)


@pytest.mark.parametrize("module_name", ROOT_SHIM_MODULES)
def test_legacy_namespace_imports_are_silent(tmp_path, module_name):
    records, _ = _run_capture(tmp_path, [f"import shwfs_ao.legacy.{module_name}"])
    assert _deprecations(records) == [], (module_name, records)


def test_shim_warning_stacklevel_points_at_importer(tmp_path):
    records, line_numbers = _run_capture(tmp_path, ["import dm_model"])
    deprecations = _deprecations(records)
    assert len(deprecations) == 1
    warning = deprecations[0]
    # stacklevel=2 attributes the warning to the importing statement in the
    # runner, not to the shim module itself.
    assert Path(warning["filename"]).name == "runner.py"
    assert warning["lineno"] == line_numbers["import dm_model"]


def test_shwfs_ao_import_does_not_pull_in_root_shims(tmp_path):
    records, _ = _run_capture(
        tmp_path,
        [
            "import shwfs_ao",
            "import sys",
            "leaked = sorted(set(sys.modules) & set(%r))" % (ROOT_SHIM_MODULES,),
            "assert leaked == [], leaked",
        ],
    )
    # The assertion runs in-subprocess; reaching here means no shim leaked and
    # no deprecation warning fired from a plain package import.
    assert _deprecations(records) == []


# --------------------------------------------------------------------------- #
# Deprecation clock                                                            #
# --------------------------------------------------------------------------- #


def test_packaged_clock_validates_and_earliest_removal_recomputes():
    clock = _deprecation.deprecation_clock()
    assert clock["schema_name"] == "shwfs_ao.deprecation_clock"
    assert clock["ticket"] == "AO-REF-021"
    recomputed = _deprecation.earliest_removal_utc_date(clock)
    assert recomputed == _deprecation.parse_utc_date(clock["earliest_removal_utc_date"])


def _clock(
    *,
    publication="2026-01-01",
    window=90,
    pub_status="published",
    sub_status="published",
    sub_date="2026-02-01",
):
    return {
        "publication_utc_date": publication,
        "publication_status": pub_status,
        "minimum_window_days": window,
        "minimum_subsequent_minor_releases": 1,
        "subsequent_minor_release": {
            "publication_status": sub_status,
            "publication_utc_date": sub_date,
        },
    }


def test_earliest_removal_is_later_of_window_and_subsequent_minor():
    # Window dominates: 2026-01-01 + 90 days = 2026-04-01 > 2026-02-01.
    early_sub = _clock(sub_date="2026-02-01")
    assert _deprecation.earliest_removal_utc_date(early_sub) == datetime.date(2026, 4, 1)

    # Subsequent minor release dominates.
    late_sub = _clock(sub_date="2026-08-01")
    assert _deprecation.earliest_removal_utc_date(late_sub) == datetime.date(2026, 8, 1)

    # Unpublished subsequent release: the floor is the pure day-count window.
    unpublished = _clock(sub_status="planned", sub_date=None)
    assert _deprecation.earliest_removal_utc_date(unpublished) == datetime.date(2026, 4, 1)


def test_removal_requires_both_time_and_release_boundaries():
    ready = _clock(sub_date="2026-08-01")
    earliest = _deprecation.earliest_removal_utc_date(ready)
    assert earliest == datetime.date(2026, 8, 1)
    # On the earliest date, with both releases published, removal is allowed.
    assert _deprecation.removal_boundaries_satisfied(ready, earliest)
    # One day earlier is not.
    assert not _deprecation.removal_boundaries_satisfied(
        ready, earliest - datetime.timedelta(days=1)
    )
    # Deprecation release not yet published: never satisfied.
    assert not _deprecation.removal_boundaries_satisfied(
        _clock(pub_status="planned"), datetime.date(2030, 1, 1)
    )
    # Required subsequent minor release not yet published: never satisfied,
    # even far in the future.
    assert not _deprecation.removal_boundaries_satisfied(
        _clock(sub_status="planned", sub_date=None), datetime.date(2030, 1, 1)
    )


def test_packaged_clock_is_not_yet_removable_during_phase_a():
    clock = _deprecation.deprecation_clock()
    # The committed clock is still in the planned/unpublished state, so Phase B
    # deletion is not permitted regardless of the calendar.
    assert not _deprecation.removal_boundaries_satisfied(clock, datetime.date(2099, 1, 1))


def test_warning_release_clause_follows_the_publication_state(monkeypatch):
    base = dict(_deprecation.deprecation_clock())

    def _with_status(status):
        clock = dict(base)
        clock["publication_status"] = status
        return clock

    monkeypatch.setattr(
        _deprecation, "deprecation_clock", lambda: _with_status("planned")
    )
    planned_shim = _deprecation.root_shim_deprecation_message("zernike")
    planned_alias = _deprecation.resource_alias_deprecation_message()
    for message in (planned_shim, planned_alias):
        assert (
            f"(scheduled for release {base['deprecation_release']}, "
            "not yet published)"
        ) in message
        assert f"as of release {base['deprecation_release']}" not in message

    monkeypatch.setattr(
        _deprecation, "deprecation_clock", lambda: _with_status("published")
    )
    published_shim = _deprecation.root_shim_deprecation_message("zernike")
    published_alias = _deprecation.resource_alias_deprecation_message()
    for message in (published_shim, published_alias):
        assert f"deprecated as of release {base['deprecation_release']}" in message
        assert "not yet published" not in message


def test_invalid_publication_status_is_rejected(tmp_path, monkeypatch):
    bad = json.loads(
        (SRC / "shwfs_ao/resources/deprecation_clock.json").read_text(encoding="utf-8")
    )
    bad["publication_status"] = "tagged"

    def _fake_loader(name):
        assert name == _deprecation.CLOCK_RESOURCE_NAME
        return bad

    _deprecation.deprecation_clock.cache_clear()
    monkeypatch.setattr(_deprecation, "_load_json_resource", _fake_loader)
    with pytest.raises(
        _deprecation.DeprecationMetadataError,
        match="publication_status",
    ):
        _deprecation.deprecation_clock()
    _deprecation.deprecation_clock.cache_clear()


def test_invalid_clock_earliest_removal_is_rejected(tmp_path, monkeypatch):
    bad = json.loads(
        (SRC / "shwfs_ao/resources/deprecation_clock.json").read_text(encoding="utf-8")
    )
    bad["earliest_removal_utc_date"] = "2020-01-01"
    target = tmp_path / "deprecation_clock.json"
    target.write_text(json.dumps(bad), encoding="utf-8")

    def _fake_loader(name):
        if name == _deprecation.CLOCK_RESOURCE_NAME:
            return json.loads(target.read_text(encoding="utf-8"))
        raise AssertionError(name)

    _deprecation.deprecation_clock.cache_clear()
    monkeypatch.setattr(_deprecation, "_load_json_resource", _fake_loader)
    with pytest.raises(_deprecation.DeprecationMetadataError):
        _deprecation.deprecation_clock()
    _deprecation.deprecation_clock.cache_clear()


# --------------------------------------------------------------------------- #
# Inventory completeness and ownership                                        #
# --------------------------------------------------------------------------- #


def _pyproject_py_modules() -> list[str]:
    import re

    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r"py-modules\s*=\s*\[(.*?)\]", text, flags=re.DOTALL)
    assert match
    return re.findall(r'"([^"]+)"', match.group(1))


def test_inventory_root_shims_match_pyproject_modules():
    inventory = _deprecation.deprecation_inventory()
    modules = sorted(record["module"] for record in inventory["root_shims"])
    assert modules == sorted(ROOT_SHIM_MODULES)
    assert modules == sorted(_pyproject_py_modules())
    for record in inventory["root_shims"]:
        assert record["source_path"] == f"src/{record['module']}.py"
        assert (ROOT / record["source_path"]).is_file()
        assert record["replacement"]
        assert record["public_symbols"]


def test_inventory_classifies_every_legacy_module_file():
    inventory = _deprecation.deprecation_inventory()
    classified = {record["module"] for record in inventory["legacy_modules"]}
    on_disk = {
        f"shwfs_ao.legacy.{path.stem}"
        for path in LEGACY_DIR.glob("*.py")
        if path.stem != "__init__"
    }
    assert classified == on_disk
    for record in inventory["legacy_modules"]:
        assert record["private"] == record["module"].split(".")[-1].startswith("_")
        assert (ROOT / record["source_path"]).is_file()
        assert record["disposition"] in {
            "pure_facade",
            "behavior_compat_adapter",
        }


def test_inventory_canonical_destinations_are_importable_and_non_legacy():
    inventory = _deprecation.deprecation_inventory()
    for record in inventory["legacy_modules"]:
        for destination in record["canonical_destinations"]:
            assert not destination.startswith("shwfs_ao.legacy"), record["module"]
            importlib.import_module(destination)


def test_inventory_symbol_overrides_resolve_to_real_objects():
    inventory = _deprecation.deprecation_inventory()
    for record in inventory["root_shims"]:
        for symbol, target in record["symbol_replacement_overrides"].items():
            assert symbol in record["public_symbols"]
            module_path, _, attribute = target.rpartition(".")
            module = importlib.import_module(module_path)
            assert hasattr(module, attribute), target


def test_error_budget_allowlist_matches_actual_source_imports():
    inventory = _deprecation.deprecation_inventory()
    allowlist = inventory["canonical_legacy_import_allowlist"][
        "shwfs_ao.experiments.error_budget"
    ]
    source = (SRC / "shwfs_ao/experiments/error_budget.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    legacy_imports = sorted(
        {
            "shwfs_ao." + node.module[len("..") :].replace("..", "")
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.level == 2
            and node.module is not None
            and node.module.startswith("legacy.")
        }
    )
    # Normalize: level-2 relative "legacy.X" under shwfs_ao.experiments resolves
    # to shwfs_ao.legacy.X.
    resolved = sorted(
        {
            f"shwfs_ao.legacy.{node.module.split('.', 1)[1]}"
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.level == 2
            and node.module is not None
            and node.module.startswith("legacy.")
        }
    )
    assert resolved == sorted(allowlist), (resolved, allowlist)
    assert legacy_imports  # sanity: the module really does import legacy adapters


def test_no_canonical_module_imports_legacy_except_allowlist():
    inventory = _deprecation.deprecation_inventory()
    allowed = set(inventory["canonical_legacy_import_allowlist"])
    offenders = []
    for path in (SRC / "shwfs_ao").rglob("*.py"):
        rel = path.relative_to(SRC).with_suffix("")
        dotted = ".".join(rel.parts)
        if ".legacy" in f".{dotted}" and dotted.startswith("shwfs_ao.legacy"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports_legacy = any(
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and (
                (node.level == 0 and node.module.startswith("shwfs_ao.legacy"))
                or (node.level >= 1 and node.module.startswith("legacy"))
            )
            for node in ast.walk(tree)
        )
        if imports_legacy and dotted not in allowed:
            offenders.append(dotted)
    assert offenders == [], offenders


def test_owned_examples_import_only_canonical_surfaces():
    # AO-REF-021 Phase A prerequisite (review finding F12): the shipped
    # examples demonstrate the canonical architecture, so none of them may
    # consume the frozen legacy layer or the deprecated root shims.
    example_paths = sorted((ROOT / "examples").glob("*.py"))
    assert len(example_paths) == 10
    offenders: list[tuple[str, str]] = []
    for path in example_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                names = [node.module]
            else:
                continue
            for name in names:
                if name.startswith("shwfs_ao.legacy") or name.split(".")[0] in ROOT_SHIM_MODULES:
                    offenders.append((path.name, name))
    assert offenders == [], offenders


# --------------------------------------------------------------------------- #
# Retained educational code inventory                                         #
# --------------------------------------------------------------------------- #


def test_retained_educational_code_inventory_matches_legacy_readme():
    inventory = _deprecation.deprecation_inventory()
    assert inventory["retained_educational_code"] == []
    readme = (LEGACY_DIR / "README.md").read_text(encoding="utf-8")
    assert "Deliberately retained educational code" in readme
    # Both the machine inventory and the human README agree: nothing is retained
    # as educational reference past the removal boundary.
    section = readme.split("Deliberately retained educational code", 1)[1]
    assert "None." in section
