"""ESO-01: versioned ESO-derived benchmark records, ledgers and schema v5."""

from __future__ import annotations

import copy
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from shwfs_ao.io.benchmark_ledgers import (
    ASSUMPTION_LEDGER_V1_RESOURCE,
    LedgerError,
    load_assumption_ledger,
    load_source_ledger,
    validate_assumption_ledger,
    validate_benchmark_profiles,
    validate_source_ledger,
)
from shwfs_ao.io.configs import (
    ScalablePathConfig,
    SystemConfigError,
    load_system_profile,
    system_config_from_mapping,
    system_config_to_mapping,
)

ROOT = Path(__file__).resolve().parents[2]
TIER_NAMES = (
    "eso_scao_smoke_5m_software",
    "eso_scao_medium_12m_derived",
    "eso_scao_medium_12m_weak_gate",
    "eso_drm_42m_scao_derived",
)
# The current benchmark records; version 1 stays loadable as the configuration
# the first runs used (an even detector window, see the v2 ledger revision).
BENCHMARK_PROFILES = tuple((name, 2) for name in TIER_NAMES)
ALL_BENCHMARK_PROFILES = tuple((name, version) for name in TIER_NAMES for version in (1, 2))


def _configs(version=2):
    return {f"{name}@{version}": load_system_profile(name, version) for name in TIER_NAMES}


@pytest.mark.parametrize("key", ALL_BENCHMARK_PROFILES)
def test_benchmark_profiles_round_trip_exactly(key):
    config = load_system_profile(*key)
    record = system_config_to_mapping(config)
    assert record["schema_version"] == 5
    restored = system_config_from_mapping(copy.deepcopy(record))
    assert restored == config
    assert restored.config_hash == config.config_hash
    assert dict(restored.component_config_hashes) == dict(config.component_config_hashes)
    assert config.component_config_hashes["scalable"] == config.scalable.config_hash
    assert config.profile.provenance.source_class == "synthetic_assumed"


def test_packaged_profiles_match_their_generator():
    script = ROOT / "scripts" / "generate_eso_scao_profiles.py"
    if not script.is_file():
        pytest.skip("generator script is only in the source tree")
    spec = importlib.util.spec_from_file_location("generate_eso_scao_profiles", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    for name, version in ALL_BENCHMARK_PROFILES:
        packaged = (
            ROOT / "src" / "shwfs_ao" / "resources" / "synthetic_presets" / f"{name}.v{version}.json"
        ).read_text()
        assert packaged == module.render(name, version)


def test_every_executable_value_is_covered_by_a_ledger_row():
    for resource, version in ((None, 2), (ASSUMPTION_LEDGER_V1_RESOURCE, 1)):
        ledger = load_assumption_ledger() if resource is None else load_assumption_ledger(resource)
        coverage = validate_benchmark_profiles(ledger, _configs(version))
        for rows in coverage.values():
            assert {"S13", "A06a", "A07b", "A08", "A09", "A10", "A12"} <= set(rows)


def test_version_two_changes_only_the_detector_window_and_records_why():
    ledger = load_assumption_ledger()
    revision = ledger["revisions"][0]
    assert revision["row"] == "A05c" and "24 -> 23" in revision["change"]
    for name in TIER_NAMES:
        first = system_config_to_mapping(load_system_profile(name, 1))["config"]
        second = system_config_to_mapping(load_system_profile(name, 2))["config"]
        assert first["wfs"]["detector_window_px"] == 24
        assert second["wfs"]["detector_window_px"] == 23
        first["wfs"]["detector_window_px"] = 23
        assert first == second


def test_ledger_values_match_every_tier_profile():
    ledger = load_assumption_ledger()
    configs = _configs()
    tampered = copy.deepcopy(ledger)
    row = next(item for item in tampered["rows"] if item["id"] == "A07a")
    row["values"]["controller.gain"] = 0.5
    with pytest.raises(LedgerError, match="controller.gain=0.5"):
        validate_benchmark_profiles(tampered, configs)
    altered = dict(configs)
    key = "eso_drm_42m_scao_derived@2"
    altered[key] = replace(configs[key], wfs_wavelength_m=6.0e-7)
    with pytest.raises(LedgerError, match="wfs_wavelength_m"):
        validate_benchmark_profiles(ledger, altered)


def test_ledger_rejects_missing_rows_bad_sources_and_bad_labels():
    sources = load_source_ledger()
    ledger = load_assumption_ledger(source_ledger=sources)
    configs = _configs()

    missing = copy.deepcopy(ledger)
    missing["rows"] = [row for row in missing["rows"] if row["id"] != "A08"]
    with pytest.raises(LedgerError, match="dm.stroke_limit_opd_m"):
        validate_benchmark_profiles(missing, configs)

    engineering_with_authority = copy.deepcopy(ledger)
    next(r for r in engineering_with_authority["rows"] if r["id"] == "A07a")[
        "authority_sources"
    ] = ["R1"]
    with pytest.raises(LedgerError, match="only as context_sources"):
        validate_assumption_ledger(engineering_with_authority, sources)

    contextual_authority = copy.deepcopy(ledger)
    next(r for r in contextual_authority["rows"] if r["id"] == "S11")["authority_sources"] = ["R4"]
    with pytest.raises(LedgerError, match="normative"):
        validate_assumption_ledger(contextual_authority, sources)

    untested = copy.deepcopy(ledger)
    next(r for r in untested["rows"] if r["id"] == "A03")["consuming_tests"] = []
    with pytest.raises(LedgerError, match="consuming tests"):
        validate_assumption_ledger(untested, sources)

    unknown_class = copy.deepcopy(ledger)
    next(r for r in unknown_class["rows"] if r["id"] == "A03")["classification"] = "measured"
    with pytest.raises(LedgerError, match="unknown classification"):
        validate_assumption_ledger(unknown_class, sources)

    insecure = copy.deepcopy(sources)
    insecure["sources"][0]["url"] = "http://www.eso.org/"
    with pytest.raises(LedgerError, match="https"):
        validate_source_ledger(insecure)

    runnable_claim = copy.deepcopy(sources)
    runnable_claim["reference_cases"][0]["status"] = "reproduced"
    with pytest.raises(LedgerError, match="not runnable"):
        validate_source_ledger(runnable_claim)


def test_source_ledger_separates_normative_and_contextual_sources():
    sources = load_source_ledger()
    roles = {source["id"]: source["role"] for source in sources["sources"]}
    assert roles == {
        "R1": "normative",
        "R2": "normative",
        "R3": "contextual_reference_case",
        "R4": "contextual_reference_case",
    }
    assert {case["status"] for case in sources["reference_cases"]} == {"documented_not_runnable"}
    assert {item["id"] for item in sources["contradictions"]} >= {"C1", "C2"}


def _record(key=("eso_scao_smoke_5m_software", 2)):
    return copy.deepcopy(system_config_to_mapping(load_system_profile(*key)))


def test_malformed_fractions_unsupported_modes_and_inconsistent_clocks_are_rejected():
    record = _record()
    record["config"]["atmosphere"]["layers"][0]["cn2_fraction"] = 0.5
    with pytest.raises(SystemConfigError, match="sum to 1"):
        system_config_from_mapping(record)

    record = _record()
    record["config"]["scalable"]["solver"] = "conjugate_gradient"
    with pytest.raises(SystemConfigError, match="scalable.solver"):
        system_config_from_mapping(record)

    record = _record()
    record["config"]["calibration"]["include_noise"] = True
    record["config"]["calibration"]["repeats"] = 4
    with pytest.raises(SystemConfigError, match="include_noise=false"):
        system_config_from_mapping(record)

    record = _record()
    record["config"]["dm"]["coupling_width_pitch"] = 0.8
    with pytest.raises(SystemConfigError, match="one-pitch"):
        system_config_from_mapping(record)

    record = _record()
    record["config"]["scalable"] = None
    with pytest.raises(SystemConfigError, match="require the scalable block"):
        system_config_from_mapping(record)

    record = _record()
    del record["config"]["scalable"]
    with pytest.raises(SystemConfigError, match="missing=\\['scalable'\\]"):
        system_config_from_mapping(record)

    record = _record()
    record["schema_version"] = 4
    with pytest.raises(SystemConfigError, match="unknown=\\['scalable'\\]"):
        system_config_from_mapping(record)
    del record["config"]["scalable"]
    with pytest.raises(SystemConfigError, match="cannot express"):
        system_config_from_mapping(record)

    configs = _configs()
    key = "eso_scao_smoke_5m_software@2"
    configs[key] = replace(configs[key], detector=replace(configs[key].detector, exposure_s=0.001))
    with pytest.raises(LedgerError, match="frame period"):
        validate_benchmark_profiles(load_assumption_ledger(), configs)


def test_scalable_block_validates_its_own_fields():
    for keywords in (
        dict(solver_atol=0.0),
        dict(solver_max_iterations=0),
        dict(nonconverged_policy="ignore"),
        dict(wfs_geometry="dense"),
    ):
        values = dict(
            dm_operator="linear_spline_local_sparse",
            wfs_geometry="compact_cells",
            calibration_strategy="grouped_local_noiseless",
            solver="lsmr",
            solver_atol=1e-8,
            solver_btol=1e-8,
            solver_max_iterations=10,
            nonconverged_policy="reject",
        )
        values.update(keywords)
        with pytest.raises(SystemConfigError):
            ScalablePathConfig(**values)


def test_a_published_profile_cannot_be_moved_onto_the_scalable_path_silently():
    published = load_system_profile("eso_turbulence_2m_detector", 1)
    smoke = load_system_profile("eso_scao_smoke_5m_software", 2)
    with pytest.raises(SystemConfigError, match="cannot express the scalable block"):
        replace(published, scalable=smoke.scalable)
    assert "scalable" not in published.component_config_hashes


def test_loading_profiles_and_ledgers_builds_nothing_and_imports_no_backend():
    code = (
        "import sys, tracemalloc\n"
        "tracemalloc.start()\n"
        "from shwfs_ao.io.configs import load_system_profile\n"
        "from shwfs_ao.io.benchmark_ledgers import load_assumption_ledger\n"
        "for name in ('eso_scao_smoke_5m_software','eso_scao_medium_12m_derived',"
        "'eso_scao_medium_12m_weak_gate','eso_drm_42m_scao_derived'):\n"
        "    load_system_profile(name, 1)\n"
        "    load_system_profile(name, 2)\n"
        "load_assumption_ledger()\n"
        "peak = tracemalloc.get_traced_memory()[1]\n"
        "heavy = [m for m in ('hcipy', 'shwfs_ao.backends.native.dm_operator',"
        " 'shwfs_ao.experiments.scao', 'shwfs_ao.wfs.shack_hartmann.compact_geometry')"
        " if m in sys.modules]\n"
        "print(peak, heavy)\n"
    )
    output = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout.split(maxsplit=1)
    assert int(output[0]) < 32 * 1024**2
    assert output[1].strip() == "[]"


def test_benchmark_resources_are_in_the_manifest():
    from shwfs_ao.io import resources

    names = {record["logical_name"] for record in resources.load_resource_manifest()["resources"]}
    assert {
        "benchmarks/eso_scao_source_ledger.v1.json",
        "benchmarks/eso_drm_42m_scao_derived.assumptions.v1.json",
        "benchmarks/eso_drm_42m_scao_derived.assumptions.v2.json",
        *(f"synthetic_presets/{name}.v{version}.json" for name, version in ALL_BENCHMARK_PROFILES),
    } <= names
    record = json.loads(resources.read_text_resource("benchmarks/eso_scao_source_ledger.v1.json"))
    assert record["ledger_id"] == "eso_scao_source_ledger"
