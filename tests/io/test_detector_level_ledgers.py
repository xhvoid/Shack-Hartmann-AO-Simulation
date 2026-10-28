"""DET-00/DET-09 and roadmap G11: the detector source and assumption ledgers close every profile.

Version 2 of both ledgers (G11) corrects descriptions only: current
``detector_covariance_v2`` semantics in B14, a historical-producer note in
B18 and a Thomas et al. (2006) entry in D4 checked against the paper's full
text.  Version 1 is the
frozen record every detector-level profile references; its bytes are pinned
here, not regenerated.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from shwfs_ao.detector.noise_model import UNCERTAINTY_MODEL_ID
from shwfs_ao.io.benchmark_ledgers import (
    load_assumption_ledger,
    load_source_ledger,
    validate_benchmark_profiles,
)
from shwfs_ao.io.configs import load_system_profile
from shwfs_ao.io.resources import read_binary_resource


ROOT = Path(__file__).resolve().parents[2]
SOURCE = "benchmarks/detector_source_ledger.v2.json"
ASSUMPTIONS = "benchmarks/detector_level.assumptions.v2.json"
SOURCE_V1 = "benchmarks/detector_source_ledger.v1.json"
ASSUMPTIONS_V1 = "benchmarks/detector_level.assumptions.v1.json"
# The version-1 bytes the profiles and the historical evidence were produced
# against (resource_manifest.json since a31099b/ea775bc).  Never regenerated.
V1_SHA256 = {
    SOURCE_V1: "2b8cc13ebca067f9c48af1861680a84de619834019567a33a7d671ec606882fc",
    ASSUMPTIONS_V1: "33073748f7a919749b6908c851318efefa02b2d8379a4f8bd12647a7bdeb7ffa",
}
GAIN_SCAN = ROOT / "docs/refactor/detector_level_evidence/det09_gain_scan.json"
# Every field version 2 may change (G11); everything else is version 1's.
SOURCE_CHANGES = {
    "access_note", "ledger_id", "revised", "revisions", "supersedes",
    "sources[D4].accessed", "sources[D4].limitations", "sources[D4].locator", "sources[D4].supports",
}
ASSUMPTION_CHANGES = {
    "historical_producers", "ledger_id", "revised", "revisions", "source_ledger", "supersedes",
    "rows[B14].consuming_tests", "rows[B14].limitation", "rows[B14].rationale",
    "rows[B18].rationale", "rows[B18].title",
}


def _ledgers(source: str = SOURCE, assumptions: str = ASSUMPTIONS):
    sources = load_source_ledger(source)
    return sources, load_assumption_ledger(assumptions, source_ledger=sources)


def _configs(ledger):
    return {pid: load_system_profile(pid.split("@")[0], int(pid.split("@")[1])) for pid in ledger["profiles"]}


def _differing_paths(old: dict, new: dict, list_key: str) -> set[str]:
    paths = {key for key in set(old) | set(new) if key != list_key and old.get(key) != new.get(key)}
    old_items = {item["id"]: item for item in old[list_key]}
    new_items = {item["id"]: item for item in new[list_key]}
    assert list(old_items) == list(new_items), f"{list_key} ids or order changed"
    for identifier, item in old_items.items():
        other = new_items[identifier]
        paths |= {f"{list_key}[{identifier}].{key}" for key in set(item) | set(other) if item.get(key) != other.get(key)}
    return paths


def _json(name: str) -> dict:
    return json.loads(read_binary_resource(name).decode("utf-8"))


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_every_detector_level_profile_value_has_a_ledger_row(version: str) -> None:
    if version == "v1":
        sources, ledger = _ledgers(SOURCE_V1, ASSUMPTIONS_V1)
    else:
        sources, ledger = _ledgers()
    coverage = validate_benchmark_profiles(ledger, _configs(ledger))
    for rows in coverage.values():
        assert {f"B{index:02d}" for index in range(1, 18)} - {"B14"} <= set(rows)
    assert {"B18", "B19"} <= set(coverage["det_emccd_12m_medium_derived@2"])
    assert {"B20", "B21"} <= set(coverage["det_emccd_12m_medium_derived@3"])
    ids = {source["id"] for source in sources["sources"]}
    assert {"D1", "D2", "D3", "D4", "D5", "D7", "D8", "D9", "R3", "R4"} <= ids
    assert "D6" not in ids  # no datasheet: every preset stays synthetic_assumed


def test_version_2_covers_every_profile_exactly_as_version_1() -> None:
    _, v1 = _ledgers(SOURCE_V1, ASSUMPTIONS_V1)
    _, v2 = _ledgers()
    assert v2["profiles"] == v1["profiles"]
    configs = _configs(v1)
    assert validate_benchmark_profiles(v2, configs) == validate_benchmark_profiles(v1, configs)


def test_version_1_ledgers_are_byte_frozen() -> None:
    for name, digest in V1_SHA256.items():
        assert hashlib.sha256(read_binary_resource(name)).hexdigest() == digest, name
    for name in V1_SHA256:
        assert _json(name)["ledger_id"] in {"detector_source_ledger", "detector_level.assumptions"}


def test_version_2_differs_from_version_1_only_in_the_declared_fields() -> None:
    source_v1, source_v2 = _json(SOURCE_V1), _json(SOURCE)
    assert _differing_paths(source_v1, source_v2, "sources") == SOURCE_CHANGES
    assumptions_v1, assumptions_v2 = _json(ASSUMPTIONS_V1), _json(ASSUMPTIONS)
    assert _differing_paths(assumptions_v1, assumptions_v2, "rows") == ASSUMPTION_CHANGES
    # The version-1 access note is kept verbatim; version 2 only appends.
    assert source_v2["access_note"].startswith(source_v1["access_note"] + " ")
    for v1, v2, supersedes in (
        (source_v1, source_v2, SOURCE_V1),
        (assumptions_v1, assumptions_v2, ASSUMPTIONS_V1),
    ):
        assert v2["schema_version"] == v1["schema_version"] == 1
        assert v2["ledger_id"] == v1["ledger_id"] + ".v2"
        assert v2["supersedes"] == supersedes
        assert v2["revised"] == "2026-10-20"
    assert assumptions_v2["frozen"] == assumptions_v1["frozen"] == "2026-10-15"
    assert assumptions_v2["source_ledger"] == SOURCE
    assert {revision["row"] for revision in assumptions_v2["revisions"]} == {"B14", "B18"}
    assert [revision["source"] for revision in source_v2["revisions"]] == ["D4"]


def test_version_2_states_the_current_model_and_keeps_history_apart() -> None:
    _, ledger = _ledgers()
    rows = {row["id"]: row for row in ledger["rows"]}
    assert rows["B14"]["rationale"].startswith(UNCERTAINTY_MODEL_ID + " ")
    assert "detector_covariance_v1" not in rows["B14"]["rationale"] + rows["B14"]["limitation"]
    assert "detector_covariance_v1" not in rows["B18"]["title"]
    assert "detector_covariance_v1" in rows["B18"]["rationale"]
    assert UNCERTAINTY_MODEL_ID in rows["B18"]["rationale"]
    # B14 names the support-domain gate tests; B18 has its own list again.
    gate_tests = {
        "tests/detector/test_noise_model.py::test_regimes_outside_the_first_order_domain_are_flagged",
        "tests/detector/test_noise_model.py::test_codes_within_the_noise_headroom_of_code_zero_are_flagged",
        "tests/detector/test_noise_model.py::test_codes_within_the_noise_headroom_of_the_top_code_are_flagged",
        "tests/detector/test_noise_model.py::test_a_contributing_pixel_below_half_a_step_unsupports_the_block",
    }
    assert gate_tests <= set(rows["B14"]["consuming_tests"])
    assert not gate_tests & set(rows["B18"]["consuming_tests"])
    for name in (SOURCE, ASSUMPTIONS):
        text = read_binary_resource(name).decode("utf-8")
        assert "<VERIFY" not in text and "<ACCEPTANCE_DATE>" not in text and "TODO" not in text, name


def test_d4_separates_the_paper_from_the_implementation() -> None:
    sources, _ = _ledgers()
    (d4,) = [source for source in sources["sources"] if source["id"] == "D4"]
    text = " ".join([d4["locator"], *d4["supports"], *d4["limitations"]])
    assert "assume Gaussian spots" not in text
    assert "thresholding is not first-order linear" not in text
    for locator in ("3.1", "equations 11-13", "equation 14", "4.1", "Appendix A", "Appendix B", "publisher's PDF"):
        assert locator in d4["locator"]
    assert any("Gaussian spot" in claim and "11-12" in claim for claim in d4["supports"])
    assert any("diffraction-limited" in claim and "equation 13" in claim for claim in d4["supports"])
    # Section 4.1 evaluates the thresholded centroid's noise with equations 11-12;
    # declining that approximation is the repository's own rule.
    (threshold_rule,) = [item for item in d4["limitations"] if "repository's own support rule" in item]
    assert "equations 11-12" in threshold_rule and "section 4.1" in threshold_rule
    assert any("restates no formula" in item for item in d4["limitations"])


def test_every_consuming_test_resolves_to_a_test_function() -> None:
    _, ledger = _ledgers()
    entries = sorted({test for row in ledger["rows"] for test in row["consuming_tests"]})
    for entry in entries:
        path, _, function = entry.partition("::")
        file = ROOT / path
        if not file.is_file():
            pytest.skip("the consuming tests are only in the source tree")
        if function:
            tree = ast.parse(file.read_text(encoding="utf-8"))
            names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
            assert function in names, entry


def test_the_assumption_ledger_matches_its_generator() -> None:
    script = ROOT / "scripts" / "generate_detector_level_profiles.py"
    if not script.is_file():
        pytest.skip("generator script is only in the source tree")
    spec = importlib.util.spec_from_file_location("generate_detector_level_profiles", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.LEDGER_PATH.name == "detector_level.assumptions.v2.json"
    assert read_binary_resource(ASSUMPTIONS).decode("utf-8") == json.dumps(module.ledger_record(), indent=2) + "\n"
    # The generator would not touch version 1 or any profile reference to it.
    assert module.LEDGERS == (SOURCE_V1, ASSUMPTIONS_V1)


def test_a_version_2_row_outside_the_declared_fields_is_detected() -> None:
    v1, v2 = _json(ASSUMPTIONS_V1), _json(ASSUMPTIONS)
    tampered = copy.deepcopy(v2)
    tampered["rows"][0]["limitation"] += " (edited)"
    assert _differing_paths(v1, tampered, "rows") - ASSUMPTION_CHANGES == {f"rows[{v2['rows'][0]['id']}].limitation"}


def test_profile_gains_are_the_recorded_scan_selections() -> None:
    record = json.loads(GAIN_SCAN.read_text())
    selected = {}
    for result in record["results"]:
        key = result.get("scan_tier_for", result["profile"])
        selected[key] = result["selected_gain"]
    _, ledger = _ledgers()
    for pid in ledger["profiles"]:
        name, version = pid.split("@")
        config = load_system_profile(name, int(version))
        # Versions 2 and 3 keep the version-1 scan selection; the gain was not
        # rescanned for their changes (B18-B21).
        assert config.controller.gain == selected[f"{name}@1"], pid
