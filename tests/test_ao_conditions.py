# Notebook 11 public-data-informed upgrade: condition presets control the
# observing/error terms while IntegrationConfig controls only numerical scale.

import csv
from pathlib import Path

import pytest

from ao_conditions import (
    REFERENCE_PHASE_AMPLITUDE_NM,
    REFERENCE_SEEING_ARCSEC,
    condition_rows,
    default_observing_conditions,
    phase_amplitude_from_seeing,
    r0_from_seeing_arcsec,
)
from data_sources import load_eso_asm_snapshot


ROOT = Path(__file__).resolve().parents[1]
ASM_PATH = ROOT / "data" / "public" / "eso_asm_paranal_20240729_0300_0800_snapshot.json"
PHOTON_BUDGET_PATH = ROOT / "figures" / "detector_level_SCAO" / "public_data_photon_budget.csv"
RUNTIME_PATH = ROOT / "figures" / "detector_level_SCAO" / "public_data_informed_runtime.csv"
VALIDATION_PATH = ROOT / "figures" / "detector_level_SCAO" / "public_data_informed_validation.csv"


def _catalog_photon_budget() -> tuple[float, str]:
    with PHOTON_BUDGET_PATH.open(newline="", encoding="utf-8") as handle:
        row = next(csv.DictReader(handle))
    return float(row["photons_per_subap_frame_est"]), row["target_id"]


def test_phase_amplitude_proxy_scales_with_seeing():
    seeing = 0.7235

    assert phase_amplitude_from_seeing(seeing) == pytest.approx(
        REFERENCE_PHASE_AMPLITUDE_NM * seeing / REFERENCE_SEEING_ARCSEC
    )
    assert r0_from_seeing_arcsec(seeing) == pytest.approx(0.13969571527297858)


def test_default_observing_conditions_have_required_names_and_sources():
    snapshot = load_eso_asm_snapshot(ASM_PATH)
    catalog_photons, target_id = _catalog_photon_budget()
    conditions = default_observing_conditions(
        snapshot,
        catalog_photons_per_subap_frame=catalog_photons,
        photon_source=f"Pan-STARRS DR2 optical proxy target {target_id}",
    )

    assert [condition.condition_name for condition in conditions] == [
        "nominal_synthetic",
        "paranal_night_asm",
        "poor_seeing",
        "faint_ngs",
        "stress_all_effects",
    ]
    assert conditions[0].source_class == "synthetic_assumed"
    assert conditions[1].atmosphere_source == "ESO ASM nighttime direct_public_data cache"
    assert conditions[1].seeing_arcsec == pytest.approx(0.7235)
    assert conditions[1].phase_amplitude_nm == pytest.approx(235.1375)
    assert conditions[3].photons_per_subap_frame == pytest.approx(catalog_photons)
    assert conditions[4].photons_per_subap_frame == pytest.approx(catalog_photons)


def test_condition_rows_include_latency_and_misregistration_metadata():
    snapshot = load_eso_asm_snapshot(ASM_PATH)
    catalog_photons, target_id = _catalog_photon_budget()
    rows = condition_rows(
        default_observing_conditions(
            snapshot,
            catalog_photons_per_subap_frame=catalog_photons,
            photon_source=f"Pan-STARRS DR2 optical proxy target {target_id}",
        )
    )

    paranal = next(row for row in rows if row["condition_name"] == "paranal_night_asm")
    stress = next(row for row in rows if row["condition_name"] == "stress_all_effects")

    assert paranal["latency_total_s"] == pytest.approx(0.0010)
    assert stress["latency_total_s"] == pytest.approx(0.0030)
    assert stress["misregistration_shift_x_px"] == pytest.approx(0.8)
    assert stress["misregistration_shift_y_px"] == pytest.approx(0.3)
    assert stress["misregistration_rotation_deg"] == pytest.approx(0.3)
    assert stress["misregistration_magnification"] == pytest.approx(1.01)
    assert stress["misregistration_shear"] == pytest.approx(0.005)


def test_public_data_informed_runtime_record_is_under_documented_limit():
    with RUNTIME_PATH.open(newline="", encoding="utf-8") as handle:
        runtime_row = next(csv.DictReader(handle))
    with VALIDATION_PATH.open(newline="", encoding="utf-8") as handle:
        validation_rows = list(csv.DictReader(handle))

    runtime_minutes = float(runtime_row["runtime_minutes"])
    limit_minutes = float(runtime_row["runtime_limit_minutes"])
    runtime_check = next(row for row in validation_rows if row["check_name"] == "runtime_under_30m")

    assert runtime_row["script"] == "examples/run_public_data_informed_ao_demo.py"
    assert limit_minutes == pytest.approx(30.0)
    assert runtime_minutes < limit_minutes
    assert runtime_row["within_runtime_limit"] == "True"
    assert runtime_check["passed"] == "True"
