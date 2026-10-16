"""DET-00/DET-09: the detector source and assumption ledgers close every profile."""

from __future__ import annotations

import json
from pathlib import Path

from shwfs_ao.io.benchmark_ledgers import (
    load_assumption_ledger,
    load_source_ledger,
    validate_benchmark_profiles,
)
from shwfs_ao.io.configs import load_system_profile


SOURCE = "benchmarks/detector_source_ledger.v1.json"
ASSUMPTIONS = "benchmarks/detector_level.assumptions.v1.json"
GAIN_SCAN = Path(__file__).resolve().parents[2] / "docs/refactor/detector_level_evidence/det09_gain_scan.json"


def _ledgers():
    sources = load_source_ledger(SOURCE)
    return sources, load_assumption_ledger(ASSUMPTIONS, source_ledger=sources)


def test_every_detector_level_profile_value_has_a_ledger_row() -> None:
    sources, ledger = _ledgers()
    configs = {pid: load_system_profile(pid.split("@")[0], int(pid.split("@")[1])) for pid in ledger["profiles"]}
    coverage = validate_benchmark_profiles(ledger, configs)
    for rows in coverage.values():
        assert {f"B{index:02d}" for index in range(1, 18)} - {"B14"} <= set(rows)
    assert {"B18", "B19"} <= set(coverage["det_emccd_12m_medium_derived@2"])
    assert {"B20", "B21"} <= set(coverage["det_emccd_12m_medium_derived@3"])
    ids = {source["id"] for source in sources["sources"]}
    assert {"D1", "D2", "D3", "D4", "D5", "D7", "D8", "D9", "R3", "R4"} <= ids
    assert "D6" not in ids  # no datasheet: every preset stays synthetic_assumed


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
