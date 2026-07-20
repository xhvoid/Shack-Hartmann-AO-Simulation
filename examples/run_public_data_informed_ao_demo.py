"""Run a public-data-informed AO photon-budget sensitivity demo.

This example keeps the detector-level SCAO model deliberately compact,
but conditions two inputs on tracked public caches:

* ESO Paranal ASM median seeing scales the synthetic phase amplitude.
* Pan-STARRS DR2 optical photometry sets one WFS photon-budget anchor.

The loop, detector, DM, and error-channel model remain synthetic fast-mode
proxies. The CSV therefore records direct-public conditioning separately from
the synthetic AO-model provenance. Photon budgets below the detector
poke-calibration validity floor are recorded as explicitly infeasible rows
rather than as no-op loop results.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import os
from pathlib import Path
import time

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]

from shwfs_ao.experiments.public_data_conditioned import condition_rows, default_observing_conditions
from shwfs_ao.experiments.error_budget import ScenarioConfig, run_error_budget_scenario
from shwfs_ao.experiments.integration import IntegrationConfig, build_integration_system, build_jhk_bandpasses, run_integration
from shwfs_ao.experiments.scenario_instrument import InteractionMatrixError
from shwfs_ao.io.public_data import load_eso_asm_snapshot
from shwfs_ao.io.artifacts import (
    RUNTIME_V2_HEADER,
    write_csv_rows,
    write_runtime_artifacts,
)
from shwfs_ao.io.resources import resource_exists


GENERATED = Path(os.environ.get("AO_DEMO_OUTPUT_DIR", ROOT / "figures" / "detector_level_SCAO"))
PUBLIC = Path("data/public")
PUBLIC_SUMMARY = GENERATED / "public_data_summary.csv"
PUBLIC_PHOTON_BUDGET = GENERATED / "public_data_photon_budget.csv"
ESO_ASM_SNAPSHOT_PATH = PUBLIC / "eso_asm_paranal_20240729_0300_0800_snapshot.json"
RUNTIME_LIMIT_MINUTES = 30.0


def main() -> None:
    run_started_utc = datetime.now(timezone.utc).replace(microsecond=0)
    run_started_perf = time.perf_counter()
    GENERATED.mkdir(parents=True, exist_ok=True)

    public_summary = _read_metric_rows(PUBLIC_SUMMARY)
    photon_rows = _read_rows(PUBLIC_PHOTON_BUDGET)
    if not photon_rows:
        raise RuntimeError("No Pan-STARRS photon-budget rows were found. Run examples/run_public_data_overview.py first.")

    seeing_arcsec = float(public_summary["eso_asm_median_seeing"]["value"])
    r0_500_m = float(public_summary["eso_asm_r0_500"]["value"])
    h_effective_um = float(public_summary["svo_2mass_h_effective_wavelength"]["value"])
    direct_photons = float(photon_rows[0]["photons_per_subap_frame_est"])
    direct_target_id = photon_rows[0]["target_id"]
    direct_m_wfs = float(photon_rows[0]["m_wfs_700nm_interp_mag"])
    asm_snapshot = load_eso_asm_snapshot(ESO_ASM_SNAPSHOT_PATH)
    conditions = default_observing_conditions(
        asm_snapshot,
        catalog_photons_per_subap_frame=direct_photons,
        photon_source=f"Pan-STARRS DR2 catalog-derived WFS photon estimate from {direct_target_id}",
    )

    phase_amplitude_nm = 260.0 * seeing_arcsec / 0.80
    photon_cases = [
        ("Pan-STARRS direct estimate", direct_photons, "direct_public_data"),
        ("engineering 50 photons", 50.0, "synthetic_assumed"),
        ("engineering 200 photons", 200.0, "synthetic_assumed"),
        ("Nominal 8000 photons", 8000.0, "synthetic_assumed"),
    ]

    rows: list[dict[str, object]] = []
    for label, photons, photon_source_class in photon_cases:
        config = IntegrationConfig.from_mode(
            "fast",
            photons_per_subap_frame=float(photons),
            phase_amplitude_nm=float(phase_amplitude_nm),
            source_class="synthetic_assumed",
            source_note=(
                "Public-data-informed fast detector-level AO run. ESO ASM and "
                "Pan-STARRS/SVO values condition selected inputs, while the AO loop, "
                "DM, detector, and error-channel model remain synthetic fast-mode proxies."
            ),
        )
        row: dict[str, object] = {
            "case_name": label,
            "photons_per_subap_frame": photons,
            "photon_input_source_class": photon_source_class,
            "conditioning_atmosphere_source_class": "direct_public_data",
            "conditioning_bandpass_source_class": "direct_public_data",
            "ao_model_source_class": config.source_class,
            "eso_asm_seeing_arcsec_500nm": seeing_arcsec,
            "eso_asm_r0_500_m": r0_500_m,
            "phase_amplitude_nm_scaled_from_eso_seeing": phase_amplitude_nm,
            "svo_h_effective_wavelength_um": h_effective_um,
            "panstarrs_target_id": direct_target_id,
            "panstarrs_m_wfs_700nm_interp_mag": direct_m_wfs,
            "open_rms_nm": float("nan"),
            "closed_rms_nm": float("nan"),
            "h_band_strehl": float("nan"),
            "command_rms_nm": float("nan"),
            "command_peak_nm": float("nan"),
            "saturated_actuator_frac": float("nan"),
            "valid_centroid_frac": float("nan"),
            "loop_feasible": False,
            "infeasibility_reason": "",
            "config_hash": "",
            "source_note": config.source_note,
        }
        # A catalog-derived WFS photon estimate can sit far below the poke
        # calibration's validity floor; such a case is recorded as an
        # infeasible row because no loop can be built at all, and a no-op
        # loop row would misreport the physics.
        try:
            result = run_integration(config, write_outputs=False)
        except InteractionMatrixError as exc:
            row["infeasibility_reason"] = str(exc)
        else:
            all_effects = next(item for item in result.scenario_results if item.scenario_name == "all_effects")
            row.update(
                open_rms_nm=all_effects.open_rms_nm,
                closed_rms_nm=all_effects.closed_rms_nm,
                h_band_strehl=all_effects.strehl_H,
                command_rms_nm=all_effects.command_rms_nm,
                command_peak_nm=all_effects.command_peak_nm,
                saturated_actuator_frac=all_effects.saturated_actuator_frac,
                valid_centroid_frac=all_effects.valid_centroid_frac,
                loop_feasible=True,
                config_hash=result.config_hash,
            )
        rows.append(row)

    csv_path = GENERATED / "public_data_informed_ao_photon_scan.csv"
    write_csv_rows(csv_path, rows)
    png_path = GENERATED / "public_data_informed_ao_photon_scan.png"
    _plot(rows, png_path)

    condition_csv = GENERATED / "public_data_informed_conditions.csv"
    condition_table = condition_rows(conditions)
    write_csv_rows(condition_csv, condition_table)
    scenario_rows = _run_conditioned_scenarios(conditions)
    scenario_csv = GENERATED / "public_data_informed_error_budget.csv"
    write_csv_rows(scenario_csv, scenario_rows)
    scenario_png = GENERATED / "public_data_informed_error_budget.png"
    _plot_conditioned_scenarios(scenario_rows, scenario_png)
    validation_rows = _build_validation_rows(scenario_rows, condition_table)
    runtime_row = _build_runtime_row(run_started_utc, run_started_perf)
    runtime_csv = GENERATED / "public_data_informed_runtime.csv"
    runtime_json = GENERATED / "public_data_informed_runtime.json"
    write_runtime_artifacts(
        runtime_row,
        output_dir=GENERATED,
        prefix="public_data_informed",
        formats=("csv", "json"),
        fieldnames=RUNTIME_V2_HEADER,
    )
    validation_rows.append(
        {
            "check_name": "runtime_under_30m",
            "passed": bool(runtime_row["within_runtime_limit"]),
            "metric_value": runtime_row["runtime_minutes"],
            "tolerance": runtime_row["runtime_limit_minutes"],
            "message": "Public-data-informed AO demo runtime stays below the documented 30 minute local-run limit.",
            "source_class": "package_reference",
            "source_note": f"Runtime record written to {_display_path(runtime_csv)} and {_display_path(runtime_json)}.",
        }
    )
    validation_csv = GENERATED / "public_data_informed_validation.csv"
    write_csv_rows(validation_csv, validation_rows)
    validation_png = GENERATED / "public_data_informed_validation.png"
    _plot_validation_rows(validation_rows, validation_png)

    print(f"Wrote {_display_path(png_path)}")
    print(f"Wrote {_display_path(csv_path)}")
    print(f"Wrote {_display_path(condition_csv)}")
    print(f"Wrote {_display_path(scenario_png)}")
    print(f"Wrote {_display_path(scenario_csv)}")
    print(f"Wrote {_display_path(runtime_csv)}")
    print(f"Wrote {_display_path(runtime_json)}")
    print(f"Wrote {_display_path(validation_png)}")
    print(f"Wrote {_display_path(validation_csv)}")
    print(
        f"Runtime: {float(runtime_row['runtime_minutes']):.2f} min "
        f"(limit {float(runtime_row['runtime_limit_minutes']):.1f} min, "
        f"within_limit={runtime_row['within_runtime_limit']})"
    )
    for row in rows:
        if row["loop_feasible"]:
            print(
                f"{row['case_name']}: photons={float(row['photons_per_subap_frame']):.3g}, "
                f"closed RMS={float(row['closed_rms_nm']):.1f} nm, "
                f"H Strehl={float(row['h_band_strehl']):.3f}, "
                f"saturated={float(row['saturated_actuator_frac']):.2f}"
            )
        else:
            print(
                f"{row['case_name']}: photons={float(row['photons_per_subap_frame']):.3g}, "
                f"calibration infeasible ({row['infeasibility_reason']})"
            )

    for row in scenario_rows:
        if row["loop_feasible"]:
            print(
                f"{row['condition_name']}: closed RMS={float(row['closed_rms_nm']):.1f} nm, "
                f"H Strehl={float(row['strehl_H']):.3f}, "
                f"photons={float(row['photons_per_subap_frame']):.3g}"
            )
        else:
            print(
                f"{row['condition_name']}: photons={float(row['photons_per_subap_frame']):.3g}, "
                f"calibration infeasible ({row['infeasibility_reason']})"
            )


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _read_metric_rows(path: Path) -> dict[str, dict[str, str]]:
    rows = _read_rows(path)
    return {row["metric"]: row for row in rows}


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _build_runtime_row(run_started_utc: datetime, run_started_perf: float) -> dict[str, object]:
    run_finished_utc = datetime.now(timezone.utc).replace(microsecond=0)
    runtime_seconds = time.perf_counter() - run_started_perf
    runtime_minutes = runtime_seconds / 60.0
    return {
        "script": "examples/run_public_data_informed_ao_demo.py",
        "run_started_utc": run_started_utc.isoformat().replace("+00:00", "Z"),
        "run_finished_utc": run_finished_utc.isoformat().replace("+00:00", "Z"),
        "runtime_seconds": runtime_seconds,
        "runtime_minutes": runtime_minutes,
        "runtime_limit_minutes": RUNTIME_LIMIT_MINUTES,
        "within_runtime_limit": runtime_minutes <= RUNTIME_LIMIT_MINUTES,
        "output_artifacts": (
            "public_data_informed_ao_photon_scan.csv;public_data_informed_ao_photon_scan.png;"
            "public_data_informed_conditions.csv;public_data_informed_error_budget.csv;"
            "public_data_informed_error_budget.png;public_data_informed_validation.csv;"
            "public_data_informed_validation.png"
        ),
        "source_note": (
            "Local wall-clock runtime for the public-data-informed Notebook 11 demo. "
            "The run uses tracked public caches and synthetic AO proxies; no live archive query is performed."
        ),
    }


def _run_conditioned_scenarios(conditions) -> list[dict[str, object]]:
    bandpasses = build_jhk_bandpasses()
    rows: list[dict[str, object]] = []
    for condition in conditions:
        config = IntegrationConfig.from_mode(
            "fast",
            photons_per_subap_frame=max(1.0e-3, condition.photons_per_subap_frame),
            read_noise_e=condition.read_noise_e,
            stroke_limit_nm=max(condition.stroke_limit_nm, 1.0),
            phase_amplitude_nm=condition.phase_amplitude_nm,
            source_class="synthetic_assumed",
            source_note=(
                "Notebook 11 public-data-informed synthetic AO scenario. Public caches "
                "condition atmosphere and/or photon inputs; internal AO control terms remain synthetic."
            ),
        )
        # The public-data-informed scenario output must describe
        # its phase sequence as an "ESO-ASM-conditioned synthetic phase sequence"
        # (never a "measured wavefront sequence"). The atmosphere amplitude is a
        # labelled f(seeing) engineering proxy anchored to the nighttime ESO ASM
        # cache. Seeing/r0 set the strength proxy, while tau0 and effective
        # turbulence speed drive its seconds-based temporal evolution; the
        # wavefront itself is synthetic, not telemetry.
        asm_conditioned = "ESO ASM" in condition.atmosphere_source
        phase_sequence_provenance = (
            "ESO-ASM-conditioned synthetic phase sequence"
            if asm_conditioned
            else "synthetic phase sequence (no public atmosphere anchor)"
        )
        effects = [
            "eso_asm_conditioned_synthetic_phase_sequence"
            if asm_conditioned
            else "synthetic_conditioned_phase_sequence",
            "detector_noise",
        ]
        if condition.latency_frames:
            effects.append(f"latency_{condition.latency_frames}_frames")
        if condition.stroke_limit_nm < 999.0:
            effects.append("dm_stroke_limit")
        has_misregistration = (
            condition.misregistration_shift_px != (0.0, 0.0)
            or condition.misregistration_rotation_deg
            or condition.misregistration_magnification != 1.0
            or condition.misregistration_shear
        )
        if has_misregistration:
            effects.append("wfs_dm_misregistration_proxy")
        if condition.ncpa_rms_nm > 0.0:
            effects.append("science_path_ncpa")
        scenario_source_note = (
            f"{condition.source_note} Seeing/r0 set phase_amplitude_nm; "
            "tau0 and effective turbulence speed set the temporal proxy."
        )
        row: dict[str, object] = {
            "condition_name": condition.condition_name,
            "scenario_name": condition.condition_name,
            "enabled_effects": "+".join(effects),
            "atmosphere_source": condition.atmosphere_source,
            "phase_sequence_provenance": phase_sequence_provenance,
            "photon_source": condition.photon_source,
            "seeing_arcsec": condition.seeing_arcsec,
            "r0_500_m": condition.r0_500_m,
            "tau0_s": condition.tau0_s,
            "theta0_rad": condition.theta0_rad,
            "turbulence_speed_m_s": condition.turbulence_speed_m_s,
            "phase_amplitude_nm": condition.phase_amplitude_nm,
            "photons_per_subap_frame": condition.photons_per_subap_frame,
            "read_noise_e": condition.read_noise_e,
            "latency_frames": condition.latency_frames,
            "latency_total_s": condition.latency_total_s,
            "stroke_limit_nm": condition.stroke_limit_nm,
            "ncpa_rms_nm": condition.ncpa_rms_nm,
            "misregistration_shift_x_px": condition.misregistration_shift_px[0],
            "misregistration_shift_y_px": condition.misregistration_shift_px[1],
            "misregistration_rotation_deg": condition.misregistration_rotation_deg,
            "misregistration_magnification": condition.misregistration_magnification,
            "misregistration_shear": condition.misregistration_shear,
            "open_rms_nm": float("nan"),
            "wfs_path_closed_rms_proxy_nm": float("nan"),
            "science_path_closed_without_ncpa_proxy_nm": float("nan"),
            "science_path_plus_ncpa_rms_nm": float("nan"),
            "residual_decomposition_note": (
                "WFS/science residual split is a public-data-informed synthetic diagnostic proxy. "
                "The core returns NCPA-added closed RMS; without-NCPA RMS is estimated by "
                "quadrature subtraction of the configured NCPA RMS."
            ),
            "closed_rms_nm": float("nan"),
            "closed_over_open_rms": float("nan"),
            "strehl_J": float("nan"),
            "strehl_H": float("nan"),
            "strehl_K": float("nan"),
            "command_rms_nm": float("nan"),
            "command_peak_nm": float("nan"),
            "saturated_actuator_frac": float("nan"),
            "valid_centroid_frac": float("nan"),
            "loop_feasible": False,
            "infeasibility_reason": "",
            "source_class": condition.source_class,
            "source_note": scenario_source_note,
            "config_hash": "",
        }
        # A condition whose photon budget cannot calibrate the WFS is
        # recorded as infeasible instead of failing the whole table.
        try:
            system = build_integration_system(config)
        except InteractionMatrixError as exc:
            row["infeasibility_reason"] = str(exc)
            rows.append(row)
            continue
        scenario = ScenarioConfig(
            scenario_name=condition.condition_name,
            enabled_effects=tuple(effects),
            n_steps=int(config.n_steps),
            dynamic_phase=True,
            phase_amplitude_nm=condition.phase_amplitude_nm,
            gain=0.32,
            leak=0.02,
            latency_frames=int(condition.latency_frames),
            frame_rate_hz=float(config.frame_rate_hz),
            include_detector_noise=True,
            stroke_limit_nm=float(condition.stroke_limit_nm),
            misregistration_shift_px=condition.misregistration_shift_px,
            misregistration_rotation_deg=float(condition.misregistration_rotation_deg),
            misregistration_magnification=float(condition.misregistration_magnification),
            misregistration_shear=float(condition.misregistration_shear),
            ncpa_rms_nm=float(condition.ncpa_rms_nm),
            tau0_s=float(condition.tau0_s),
            turbulence_speed_m_s=float(condition.turbulence_speed_m_s),
            phase_seed=101,
            detector_noise_seed=211,
            ncpa_seed=307,
            source_class=condition.source_class,
            source_note=scenario_source_note,
        )
        result = run_error_budget_scenario(
            system.calibration,
            system.dm_model,
            system.poke_result,
            scenario,
            bandpasses,
            telescope_diameter_m=float(config.telescope_diameter_m),
            pad_factor=int(config.pad_factor),
        )
        wfs_closed_proxy = float(max(result.closed_rms_nm**2 - condition.ncpa_rms_nm**2, 0.0) ** 0.5)
        row.update(
            scenario_name=result.scenario_name,
            enabled_effects="+".join(result.enabled_effects),
            open_rms_nm=result.open_rms_nm,
            wfs_path_closed_rms_proxy_nm=wfs_closed_proxy,
            science_path_closed_without_ncpa_proxy_nm=wfs_closed_proxy,
            science_path_plus_ncpa_rms_nm=result.closed_rms_nm,
            closed_rms_nm=result.closed_rms_nm,
            closed_over_open_rms=result.closed_over_open_rms,
            strehl_J=result.strehl_J,
            strehl_H=result.strehl_H,
            strehl_K=result.strehl_K,
            command_rms_nm=result.command_rms_nm,
            command_peak_nm=result.command_peak_nm,
            saturated_actuator_frac=result.saturated_actuator_frac,
            valid_centroid_frac=result.valid_centroid_frac,
            loop_feasible=True,
            source_class=result.source_class,
            source_note=result.source_note,
            config_hash=result.config_hash,
        )
        rows.append(row)
    return rows


def _build_validation_rows(scenario_rows: list[dict[str, object]], condition_rows_: list[dict[str, object]]) -> list[dict[str, object]]:
    direct_atmosphere_count = sum("ESO ASM" in str(row["atmosphere_source"]) for row in condition_rows_)
    catalog_condition_count = sum("Pan-STARRS" in str(row["photon_source"]) for row in condition_rows_)
    feasible_rows = [row for row in scenario_rows if row["loop_feasible"]]
    infeasible_rows = [row for row in scenario_rows if not row["loop_feasible"]]
    finite_metrics = all(
        np.isfinite(float(row[key]))
        for row in feasible_rows
        for key in ("open_rms_nm", "closed_rms_nm", "strehl_H", "command_rms_nm", "saturated_actuator_frac")
    )
    provenance_ok = all(str(row["source_class"]) in {"synthetic_assumed", "synthetic_literature_inspired"} for row in scenario_rows)
    jhk_direct = all(
        resource_exists(PUBLIC / filename)
        for filename in ("svo_2mass_j_direct.csv", "svo_2mass_h_direct.csv", "svo_2mass_ks_direct.csv")
    )
    return [
        {
            "check_name": "nighttime_eso_asm_condition_present",
            "passed": direct_atmosphere_count >= 1,
            "metric_value": direct_atmosphere_count,
            "tolerance": 1,
            "message": "At least one public-data-informed condition uses the nighttime ESO ASM cache.",
            "source_class": "direct_public_data",
            "source_note": "Checks condition table provenance, not AO telemetry.",
        },
        {
            "check_name": "catalog_photon_condition_present",
            "passed": catalog_condition_count >= 1,
            "metric_value": catalog_condition_count,
            "tolerance": 1,
            "message": "At least one condition uses catalog-derived Pan-STARRS photon-budget input.",
            "source_class": "direct_public_data",
            "source_note": "Checks photon-budget provenance, not WFS telemetry.",
        },
        {
            "check_name": "scenario_metrics_finite",
            "passed": finite_metrics,
            "metric_value": int(finite_metrics),
            "tolerance": 1,
            "message": "Public-data-informed scenario metrics are finite for every calibration-feasible condition.",
            "source_class": "synthetic_assumed",
            "source_note": "AO loop metrics are synthetic fast-mode outputs.",
        },
        {
            "check_name": "infeasible_conditions_recorded",
            "passed": all(str(row["infeasibility_reason"]).strip() for row in infeasible_rows),
            "metric_value": len(infeasible_rows),
            "tolerance": len(scenario_rows),
            "message": "Conditions whose photon budget cannot calibrate the WFS are recorded as infeasible with an explicit reason.",
            "source_class": "synthetic_assumed",
            "source_note": "Catalog-derived faint-NGS photon budgets can sit below the detector poke-calibration validity floor.",
        },
        {
            "check_name": "internal_ao_terms_not_direct_public",
            "passed": provenance_ok,
            "metric_value": int(provenance_ok),
            "tolerance": 1,
            "message": "Scenario rows do not claim synthetic AO internals as direct public data.",
            "source_class": "synthetic_assumed",
            "source_note": "DM, detector, interaction matrix, latency, NCPA, and registration remain synthetic proxies.",
        },
        {
            "check_name": "jhk_svo_direct_caches_expected",
            "passed": jhk_direct,
            "metric_value": int(jhk_direct),
            "tolerance": 1,
            "message": "J/H/K science metrics are configured to prefer SVO direct caches.",
            "source_class": "direct_public_data",
            "source_note": "SVO cache existence is verified by data-source tests and overview generation.",
        },
    ]


def _plot(rows: list[dict[str, object]], path: Path) -> None:
    feasible_rows = [row for row in rows if row["loop_feasible"]]
    infeasible_rows = [row for row in rows if not row["loop_feasible"]]
    if not feasible_rows:
        raise RuntimeError("No photon case produced a calibratable AO loop; cannot plot the scan.")
    photons = np.asarray([float(row["photons_per_subap_frame"]) for row in feasible_rows])
    closed = np.asarray([float(row["closed_rms_nm"]) for row in feasible_rows])
    strehl = np.asarray([float(row["h_band_strehl"]) for row in feasible_rows])
    saturation = np.asarray([float(row["saturated_actuator_frac"]) for row in feasible_rows])
    all_photons = [float(row["photons_per_subap_frame"]) for row in rows]
    open_rms = float(feasible_rows[0]["open_rms_nm"])
    phase_nm = float(rows[0]["phase_amplitude_nm_scaled_from_eso_seeing"])
    seeing = float(rows[0]["eso_asm_seeing_arcsec_500nm"])

    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.4), constrained_layout=True)

    ax = axes[0]
    ax.semilogx(photons, closed, marker="o", color="#2a9d8f", linewidth=2.0, label="closed RMS")
    ax.axhline(open_rms, color="0.55", linestyle="--", linewidth=1.2, label="open RMS")
    ax.set_xlabel("WFS photons / subaperture / frame")
    ax.set_ylabel("all-effects residual OPD RMS [nm]")
    y_min = min(open_rms, float(closed.min())) - 6.0
    y_max = max(open_rms, float(closed.max())) + 16.0
    ax.set_ylim(y_min, y_max)
    ax.grid(True, which="both", alpha=0.25)
    ax.legend(loc="best", fontsize=8)
    ax.set_title("Residual vs public photon-budget anchor")

    ax = axes[1]
    ax.semilogx(photons, strehl, marker="o", color="#4361ee", linewidth=2.0, label="H Strehl")
    ax.set_xlabel("WFS photons / subaperture / frame")
    ax.set_ylabel("H-band Strehl", color="#4361ee")
    ax.tick_params(axis="y", labelcolor="#4361ee")
    ax.set_ylim(0.0, 1.02)
    ax.grid(True, which="both", alpha=0.25)
    ax2 = ax.twinx()
    ax2.semilogx(photons, saturation, marker="s", color="#e76f51", linewidth=1.6, label="saturated actuators")
    ax2.set_ylabel("saturated actuator fraction", color="#e76f51")
    ax2.tick_params(axis="y", labelcolor="#e76f51")
    ax2.set_ylim(0.0, max(0.75, float(saturation.max()) * 1.15))
    ax.set_title("Science Strehl and stroke pressure")

    for axis in axes:
        axis.set_xlim(min(all_photons) * 0.4, max(all_photons) * 2.5)
    for row in infeasible_rows:
        value = float(row["photons_per_subap_frame"])
        for axis in axes:
            axis.axvline(value, color="#e76f51", linestyle=":", linewidth=1.3)
        axes[0].annotate(
            f"{row['case_name']}\n{value:.2g} ph: calibration infeasible",
            xy=(value, y_max),
            xytext=(4, -6),
            textcoords="offset points",
            ha="left",
            va="top",
            fontsize=7,
            color="#e76f51",
        )
    for x_value, y_value in zip(photons, closed):
        axes[0].annotate(
            f"{x_value:g} ph",
            xy=(x_value, y_value),
            xytext=(0, 9),
            textcoords="offset points",
            ha="center",
            fontsize=7,
        )

    fig.suptitle(
        f"Public-data-informed fast AO scan: ESO ASM seeing={seeing:.3f} arcsec, "
        f"phase amplitude={phase_nm:.1f} nm",
        fontsize=11,
    )
    fig.savefig(path, dpi=150, pil_kwargs={"optimize": True})
    plt.close(fig)


def _plot_conditioned_scenarios(rows: list[dict[str, object]], path: Path) -> None:
    names = [str(row["condition_name"]) for row in rows]
    x = np.arange(len(rows))
    feasible = np.asarray([bool(row["loop_feasible"]) for row in rows])
    closed = np.asarray([float(row["closed_rms_nm"]) for row in rows])
    strehl = np.asarray([float(row["strehl_H"]) for row in rows])
    saturation = np.asarray([float(row["saturated_actuator_frac"]) for row in rows])
    fig, ax1 = plt.subplots(figsize=(10.0, 4.8), constrained_layout=True)
    ax1.bar(x[feasible], closed[feasible], color="#2a9d8f", label="closed RMS")
    for x_value in x[~feasible]:
        ax1.annotate(
            "calibration\ninfeasible",
            xy=(float(x_value), 0.0),
            xytext=(0, 10),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=8,
            color="#e76f51",
        )
    ax1.set_ylabel("closed residual OPD RMS [nm]")
    # Pin the axis to every condition slot: bars exist only for feasible
    # conditions, and autoscale would otherwise clip the infeasible ones
    # together with their tick labels and annotations.
    ax1.set_xlim(-0.6, len(rows) - 0.4)
    ax1.set_xticks(x)
    ax1.set_xticklabels(names, rotation=25, ha="right")
    ax1.grid(axis="y", alpha=0.25)
    ax2 = ax1.twinx()
    ax2.plot(x[feasible], strehl[feasible], color="#4361ee", marker="o", linewidth=1.8, label="H Strehl")
    ax2.plot(x[feasible], saturation[feasible], color="#e76f51", marker="s", linewidth=1.6, label="saturated actuator frac")
    ax2.set_ylim(0.0, 1.05)
    ax2.set_ylabel("Strehl / fraction")
    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(handles1 + handles2, labels1 + labels2, loc="upper left", fontsize=8)
    ax1.set_title("Public-data-informed synthetic AO scenarios")
    fig.savefig(path, dpi=150, pil_kwargs={"optimize": True})
    plt.close(fig)


def _plot_validation_rows(rows: list[dict[str, object]], path: Path) -> None:
    names = [str(row["check_name"]).replace("_", "\n") for row in rows]
    values = [1 if str(row["passed"]) == "True" or row["passed"] is True else 0 for row in rows]
    colors = ["#2a9d8f" if value else "#e76f51" for value in values]
    fig, ax = plt.subplots(figsize=(9.0, 3.8), constrained_layout=True)
    ax.bar(np.arange(len(rows)), values, color=colors)
    ax.set_ylim(0.0, 1.2)
    ax.set_ylabel("pass")
    ax.set_xticks(np.arange(len(rows)))
    ax.set_xticklabels(names, fontsize=8)
    ax.set_title("Public-data-informed validation checks")
    ax.grid(axis="y", alpha=0.25)
    fig.savefig(path, dpi=150, pil_kwargs={"optimize": True})
    plt.close(fig)


if __name__ == "__main__":
    main()
