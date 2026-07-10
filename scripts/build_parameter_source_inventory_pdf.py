"""Build the detector-level AO parameter/source inventory.

The inventory is generated from tracked public caches and regenerated result
tables. It is intentionally explicit about the boundary between direct public
data and synthetic AO model parameters.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
import json
from pathlib import Path
import textwrap
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
PUBLIC = ROOT / "data" / "public"
GENERATED = ROOT / "figures" / "detector_level_SCAO"
REFERENCE = ROOT / "data" / "reference_metrics" / "fast_reference_metrics.json"

PDF_PATH = DOCS / "ao_realistic_demo_parameter_source_inventory.pdf"
MD_PATH = DOCS / "ao_realistic_demo_parameter_source_inventory.md"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--markdown", type=Path, default=MD_PATH, help="Markdown inventory output path.")
    parser.add_argument("--pdf", type=Path, default=PDF_PATH, help="PDF inventory output path.")
    parser.add_argument("--no-pdf", action="store_true", help="Write only the Markdown inventory.")
    args = parser.parse_args()

    inventory = build_inventory()
    markdown = markdown_inventory(inventory)
    args.markdown.write_text(markdown, encoding="utf-8")
    print(f"Wrote {_display_path(args.markdown)}")
    if not args.no_pdf:
        write_pdf(inventory, args.pdf)
        print(f"Wrote {_display_path(args.pdf)}")


def build_inventory() -> dict[str, object]:
    generated_on = datetime.now().strftime("%Y-%m-%d %H:%M %Z").strip()
    public_summary = _metric_rows(GENERATED / "public_data_summary.csv")
    photon_rows = _csv_rows(GENERATED / "public_data_photon_budget.csv")
    photon_scan_rows = _csv_rows(GENERATED / "public_data_informed_ao_photon_scan.csv")
    condition_rows = _csv_rows(GENERATED / "public_data_informed_conditions.csv")
    conditioned_scenario_rows = _csv_rows(GENERATED / "public_data_informed_error_budget.csv")
    runtime_rows = _csv_rows(GENERATED / "public_data_informed_runtime.csv")
    conditioned_validation_rows = _csv_rows(GENERATED / "public_data_informed_validation.csv")
    science_metric_rows = _csv_rows(GENERATED / "science_psf_metrics.csv")
    error_budget_rows = _csv_rows(GENERATED / "error_budget_scenarios.csv")
    fast_validation_rows = _csv_rows(GENERATED / "fast_validation.csv")
    fast_reference = json.loads(REFERENCE.read_text(encoding="utf-8"))

    filter_rows = []
    for band, filename in (
        ("J", "svo_2mass_j_direct.csv"),
        ("H", "svo_2mass_h_direct.csv"),
        ("Ks", "svo_2mass_ks_direct.csv"),
    ):
        meta, data = _commented_csv(PUBLIC / filename)
        eff_key = f"svo_2mass_{band.lower()}_effective_wavelength"
        if band == "Ks":
            eff_key = "svo_2mass_ks_effective_wavelength"
        filter_rows.append(
            {
                "item": f"SVO 2MASS {band} filter",
                "file": f"data/public/{filename}",
                "fields": "wavelength_m, transmission",
                "exact_values": (
                    f"{len(data)} samples; wavelength range "
                    f"{float(data[0]['wavelength_m']):.3e}-"
                    f"{float(data[-1]['wavelength_m']):.3e} m; "
                    f"effective wavelength {float(public_summary[eff_key]['value']):.6f} micron"
                ),
                "source_class": _meta(meta, "source_class"),
                "source": _meta(meta, "source_note"),
                "identifier": _meta(meta, "url"),
            }
        )

    tmass_meta, tmass_data = _commented_csv(PUBLIC / "target_photometry_2mass_psc_demo_ngs_bright.csv")
    ps1_meta, ps1_data = _commented_csv(PUBLIC / "target_photometry_panstarrs_dr2_demo_ngs_bright.csv")
    asm_meta, asm_timeseries = _commented_csv(PUBLIC / "eso_asm_paranal_20240729_0300_0800_timeseries.csv")
    asm_snapshot = json.loads((PUBLIC / "eso_asm_paranal_20240729_0300_0800_snapshot.json").read_text(encoding="utf-8"))
    asm_measurements = asm_snapshot["measurements"]

    h_band_rows = [row for row in science_metric_rows if row["band_name"] == "H"]

    return {
        "generated_on": generated_on,
        "direct_public_data": [
            *filter_rows,
            {
                "item": "IRSA 2MASS PSC photometry",
                "file": "data/public/target_photometry_2mass_psc_demo_ngs_bright.csv",
                "fields": "target_id, ra_deg, dec_deg, J/H/Ks, distance, ph_qual",
                "exact_values": (
                    f"{len(tmass_data)} rows; nearest {tmass_data[0]['target_id']} "
                    f"J/H/Ks={tmass_data[0]['twomass_j_mag']}/"
                    f"{tmass_data[0]['twomass_h_mag']}/"
                    f"{tmass_data[0]['twomass_ks_mag']} mag; "
                    f"ph_qual={tmass_data[0]['twomass_ph_qual']}"
                ),
                "source_class": _meta(tmass_meta, "source_class"),
                "source": _meta(tmass_meta, "source_note"),
                "identifier": _meta(tmass_meta, "url"),
            },
            {
                "item": "MAST Pan-STARRS DR2 photometry",
                "file": "data/public/target_photometry_panstarrs_dr2_demo_ngs_bright.csv",
                "fields": "target_id, ra_deg, dec_deg, nDetections, g/r/i/z/y",
                "exact_values": (
                    f"{len(ps1_data)} usable rows; photon anchor {photon_rows[0]['target_id']} "
                    f"m700={float(photon_rows[0]['m_wfs_700nm_interp_mag']):.6f} mag; "
                    f"photons={float(photon_rows[0]['photons_per_subap_frame_est']):.9f} per subap/frame"
                ),
                "source_class": _meta(ps1_meta, "source_class"),
                "source": _meta(ps1_meta, "source_note"),
                "identifier": _meta(ps1_meta, "url"),
            },
            {
                "item": "ESO Paranal ASM nighttime snapshot",
                "file": "data/public/eso_asm_paranal_20240729_0300_0800_snapshot.json",
                "fields": "seeing, r0_500, tau0, theta0, turbulence speed",
                "exact_values": (
                    f"UTC {asm_snapshot['utc_start']} to {asm_snapshot['utc_end']}; "
                    f"{asm_snapshot['local_time_note']}; "
                    f"seeing={asm_measurements['seeing_arcsec_500nm']:.4f} arcsec; "
                    f"r0_500={asm_measurements['r0_500_m']:.9f} m; "
                    f"tau0={asm_measurements['tau0_s']:.6f} s; "
                    f"theta0={asm_measurements['theta0_arcsec']:.3f} arcsec; "
                    f"turbulence_speed={asm_measurements['turbulence_speed_ms']:.2f} m/s; "
                    f"samples={asm_measurements['sample_count']}"
                ),
                "source_class": asm_snapshot["source_class"],
                "source": asm_snapshot["source_note"],
                "identifier": asm_snapshot.get("query_url", asm_snapshot.get("url", "")),
            },
            {
                "item": "ESO Paranal ASM nighttime time series",
                "file": "data/public/eso_asm_paranal_20240729_0300_0800_timeseries.csv",
                "fields": "unix_time_ms, seeing, tau0, theta0, turbulence speed",
                "exact_values": f"{len(asm_timeseries)} samples over {asm_snapshot['utc_start']} to {asm_snapshot['utc_end']}",
                "source_class": _meta(asm_meta, "source_class"),
                "source": _meta(asm_meta, "source_note"),
                "identifier": _meta(asm_meta, "url"),
            },
        ],
        "derived_public_calculations": [
            {
                "calculation": "Fried r0 conversion",
                "formula_or_assumption": "r0_500_m = 0.98 * 500e-9 / seeing_rad",
                "input": "ESO ASM median DIMM seeing at 500 nm",
                "output": f"{float(public_summary['eso_asm_r0_500']['value']):.9f} m",
                "source": "Fried parameter; DOI 10.1364/JOSA.56.001372",
            },
            {
                "calculation": "SVO J/H/Ks effective wavelengths",
                "formula_or_assumption": "lambda_eff = integral(lambda*T dlambda) / integral(T dlambda)",
                "input": "SVO 2MASS/2MASS.J, H, Ks transmission samples",
                "output": (
                    f"J={float(public_summary['svo_2mass_j_effective_wavelength']['value']):.6f} micron; "
                    f"H={float(public_summary['svo_2mass_h_effective_wavelength']['value']):.6f} micron; "
                    f"Ks={float(public_summary['svo_2mass_ks_effective_wavelength']['value']):.6f} micron"
                ),
                "source": "SVO FPS direct caches; 2MASS canonical paper DOI 10.1086/498708",
            },
            {
                "calculation": "Pan-STARRS 700 nm WFS photon estimate",
                "formula_or_assumption": (
                    "AB fnu=3631 Jy*10^(-0.4*m); bandwidth=150 nm; "
                    "D=2 m; throughput=0.25; exposure=1 ms; n_subap=25"
                ),
                "input": f"{photon_rows[0]['target_id']} m700={float(photon_rows[0]['m_wfs_700nm_interp_mag']):.6f}",
                "output": f"{float(photon_rows[0]['photons_per_subap_frame_est']):.9f} photons/subap/frame",
                "source": "MAST Pan-STARRS DR2 cache; AB magnitude convention from Oke & Gunn DOI 10.1086/113325; engineering estimate, not WFS telemetry",
            },
            {
                "calculation": "Public-data-informed phase amplitude",
                "formula_or_assumption": "phase_amplitude_nm = 260 nm * seeing_arcsec / 0.80 arcsec",
                "input": f"ESO ASM seeing={float(public_summary['eso_asm_median_seeing']['value']):.4f} arcsec",
                "output": f"{float(condition_rows[1]['phase_amplitude_nm']):.4f} nm for paranal_night_asm",
                "source": "Synthetic scaling anchored to ESO ASM; not a measured wavefront sequence",
            },
            {
                "calculation": "Science Strehl metric",
                "formula_or_assumption": "Marechal proxy Strehl = exp(-(2*pi*OPD_rms/lambda)^2)",
                "input": "Synthetic residual OPD RMS and direct SVO J/H/Ks effective wavelengths",
                    "output": "J/H/Ks Strehl columns in the science, error-budget, fast-integration, and public-data-informed result CSVs",
                "source": "Analytical AO diagnostic formula; no on-sky PSF calibration is used",
            },
        ],
        "observing_conditions": [
            {
                "condition": row["condition_name"],
                "atmosphere": row["atmosphere_source"],
                "seeing_r0": f"{_fmt(row['seeing_arcsec'])} arcsec; r0={_fmt(row['r0_500_m'])} m",
                "photons_noise": f"{_fmt(row['photons_per_subap_frame'])} photons/subap/frame; read={_fmt(row['read_noise_e'])} e-",
                "latency": f"{row['latency_frames']} frames; total={_fmt(row['latency_total_s'])} s",
                "stroke_ncpa": f"stroke={_fmt(row['stroke_limit_nm'])} nm; NCPA={_fmt(row['ncpa_rms_nm'])} nm",
                "misregistration": (
                    f"shift=({_fmt(row['misregistration_shift_x_px'])}, {_fmt(row['misregistration_shift_y_px'])}) px; "
                    f"rot={_fmt(row['misregistration_rotation_deg'])} deg; "
                    f"mag={_fmt(row['misregistration_magnification'])}; shear={_fmt(row['misregistration_shear'])}"
                ),
                "source": row["source_note"],
            }
            for row in condition_rows
        ],
        "model_parameters": [
            {
                "subsystem": "Mode presets",
                "parameters": (
                    "fast: 52 pupil px, 5 lenslets, 5 actuators across, 12 steps, 8000 photons; "
                    "portfolio: 72 px, 7 lenslets, 7 actuators, 18 steps, 7000 photons; "
                    "research: 96 px, 9 lenslets, 9 actuators, 30 steps, 6000 photons"
                ),
                "source_class": "synthetic_assumed",
                "source": "IntegrationConfig presets; modes control numerical scale only",
            },
            {
                "subsystem": "Fast detector-level SCAO geometry",
                "parameters": "D=2.0 m; detector_window_px=18; pad_factor=3; WFS wavelength=700 nm; frame_rate=1000 Hz",
                "source_class": "synthetic_assumed",
                "source": "IntegrationConfig fast preset and ShwfsGeometryConfig",
            },
            {
                "subsystem": "Detector/WFS noise parameters",
                "parameters": "Condition matrix controls photons, read_noise_e, latency, stroke, NCPA, and registration stress; DetectorConfig also supports dark current, background, full-well clipping, bad-pixel masks, PRNU, exposure time, and QE",
                "source_class": "synthetic_assumed plus direct_public_data conditioning",
                "source": "figures/detector_level_SCAO/public_data_informed_conditions.csv; tests/test_detector_centroids.py",
            },
            {
                "subsystem": "DM model",
                "parameters": "Gaussian influence functions; fast n_actuators_across=5; coupling_width_pitch=0.40; nominal stroke_limit_nm=1000",
                "source_class": "synthetic_literature_inspired",
                "source": "DM influence-function modelling motivated by arXiv:2306.10803; not measured DM calibration",
            },
            {
                "subsystem": "Interaction matrix / reconstructor",
                "parameters": "Central-difference poke amplitude=10 nm; rcond scan grid=1e-8,1e-6,1e-4,1e-3; fast-integration kept_modes=13",
                "source_class": "synthetic_assumed",
                "source": "Self-calibrated detector-level poke matrix; no observatory control matrix is used",
            },
            {
                "subsystem": "compact poke-matrix diagnostic",
                "parameters": "Command-line diagnostic matrix shape=90x16, rank=16, kept_modes=16, selected rcond=3e-3",
                "source_class": "synthetic_assumed",
                "source": "figures/detector_level_SCAO/poke_matrix_singular_values.csv; compact detector-level sanity check, not high-order observatory reconstructor conditioning",
            },
            {
                "subsystem": "Science bandpasses",
                "parameters": "J/H/Ks use SVO 2MASS direct caches when present; top-hat fallback only if a cache is missing",
                "source_class": "direct_public_data with documented fallback path",
                "source": "data/public/svo_2mass_j_direct.csv, h_direct.csv, ks_direct.csv",
            },
            {
                "subsystem": "fast reference run",
                "parameters": (
                    f"open_rms={_fmt(fast_reference['open_rms_nm'])} nm; "
                    f"closed_rms={_fmt(fast_reference['closed_rms_nm'])} nm; "
                    f"H Strehl={_fmt(fast_reference['h_strehl'])}; kept_modes={fast_reference['kept_modes']}; "
                    f"validation={fast_reference['validation_pass_count']}/{fast_reference['validation_check_count']}"
                ),
                "source_class": fast_reference["source_class"],
                "source": fast_reference["source_note"],
            },
        ],
        "public_data_informed_photon_scan": [
            {
                "case": row["case_name"],
                "photons": _fmt(row["photons_per_subap_frame"]),
                "closed_rms_nm": _fmt(row["closed_rms_nm"]),
                "h_strehl": _fmt(row["h_band_strehl"]),
                "command_rms_nm": _fmt(row["command_rms_nm"]),
                "saturated_frac": _fmt(row["saturated_actuator_frac"]),
                "provenance": f"photon={row['photon_input_source_class']}; loop={row['ao_model_source_class']}",
            }
            for row in photon_scan_rows
        ],
        "conditioned_scenarios": [
            {
                "condition": row["condition_name"],
                "enabled_effects": row["enabled_effects"],
                "closed_rms_nm": _fmt(row["closed_rms_nm"]),
                "h_strehl": _fmt(row["strehl_H"]),
                "valid_centroid_frac": _fmt(row["valid_centroid_frac"]),
                "command_rms_nm": _fmt(row["command_rms_nm"]),
                "saturated_frac": _fmt(row["saturated_actuator_frac"]),
                "decomposition": (
                    f"WFS/science no-NCPA proxy={_fmt(row['science_path_closed_without_ncpa_proxy_nm'])} nm; "
                    f"plus NCPA={_fmt(row['science_path_plus_ncpa_rms_nm'])} nm"
                ),
            }
            for row in conditioned_scenario_rows
        ],
        "h_band_summary": [
            {
                "case": row["case_name"],
                "opd_rms_nm": _fmt(row["opd_rms_nm"]),
                "h_strehl": _fmt(row["strehl_peak"]),
                "source_class": row["source_class"],
            }
            for row in h_band_rows
        ],
        "error_budget_scenarios": [
            {
                "scenario": row["scenario_name"],
                "closed_rms_nm": _fmt(row["closed_rms_nm"]),
                "h_strehl": _fmt(row["strehl_H"]),
                "command_rms_nm": _fmt(row["command_rms_nm"]),
                "saturated_frac": _fmt(row["saturated_actuator_frac"]),
                "source_class": row["source_class"],
            }
            for row in error_budget_rows
        ],
        "validation_scans": [
            {
                "check": row["check_name"],
                "metric": _fmt(row["metric_value"]),
                "unit": row.get("metric_unit", ""),
                "passed": row["passed"],
                "source_class": row.get("source_class", ""),
            }
            for row in fast_validation_rows
            if row.get("x_value")
        ],
        "conditioned_validation": [
            {
                "check": row["check_name"],
                "passed": row["passed"],
                "metric": _fmt(row["metric_value"]),
                "tolerance": _fmt(row["tolerance"]),
                "source_class": row["source_class"],
                "message": row["message"],
            }
            for row in conditioned_validation_rows
        ],
        "runtime_records": [
            {
                "script": row["script"],
                "started_utc": row["run_started_utc"],
                "finished_utc": row["run_finished_utc"],
                "runtime_minutes": _fmt(row["runtime_minutes"]),
                "limit_minutes": _fmt(row["runtime_limit_minutes"]),
                "within_limit": row["within_runtime_limit"],
                "source": row["source_note"],
            }
            for row in runtime_rows
        ],
        "artifacts": [
            ("figures/detector_level_SCAO/public_data_overview.png", "ESO ASM nighttime time series, SVO J/H/Ks filters, catalog field map, optical/NIR photometry anchors", "direct public caches"),
            ("figures/detector_level_SCAO/public_filter_curves_jhk.png", "Direct SVO 2MASS J/H/Ks filter curves", "direct public SVO caches"),
            ("figures/detector_level_SCAO/public_data_photon_budget.png", "Pan-STARRS 700 nm WFS photon-budget estimate", "Pan-STARRS direct data + explicit engineering assumptions"),
            ("figures/detector_level_SCAO/public_data_informed_ao_photon_scan.png", "AO residual/Strehl/stroke scan conditioned on ESO ASM + Pan-STARRS", "direct public conditioning + synthetic loop"),
            ("figures/detector_level_SCAO/poke_matrix_singular_values.png", "Compact detector-level DM/WFS poke-matrix singular spectrum", "synthetic detector-level calibration sanity check"),
            ("figures/detector_level_SCAO/public_data_informed_error_budget.png", "Five-condition public-data-informed AO scenario map", "direct public conditioning + synthetic AO proxies"),
            ("figures/detector_level_SCAO/public_data_informed_runtime.csv", "Local runtime record for the slower public-data-informed demo", "package runtime metadata"),
            ("figures/detector_level_SCAO/public_data_informed_runtime.json", "JSON copy of the public-data-informed demo runtime record", "package runtime metadata"),
            ("figures/detector_level_SCAO/public_data_informed_validation.png", "Public-data-informed provenance and metric validation checks", "public-data and synthetic-boundary checks"),
            ("figures/detector_level_SCAO/science_psf_metrics.png", "J/H/Ks PSF metrics", "SVO J/H/Ks direct caches"),
            ("figures/detector_level_SCAO/error_budget_scenarios.png", "8-row error-budget scenario comparison", "synthetic AO scenarios with SVO J/H/Ks science metrics"),
            ("figures/detector_level_SCAO/fast_error_budget.png", "fast all-scenario integration summary", "synthetic fast model with SVO J/H/Ks bandpasses"),
            ("figures/detector_level_SCAO/fast_validation.png", "Marechal, diffraction, photon, latency, fitting, reproducibility checks", "synthetic validation scans"),
        ],
        "not_claimed": [
            {
                "source": "Gaia Archive / Gaia DR3",
                "identifier": "https://gea.esac.esa.int/archive/ ; Gaia DR3 DOI 10.1051/0004-6361/202243940",
                "status": "Not used in this run. Archive access failed from this environment; Pan-STARRS DR2 is the optical-photometry substitute.",
            },
            {
                "source": "ERA5 pressure/single levels",
                "identifier": "DOI 10.24381/cds.bd0915c6 and DOI 10.24381/cds.adbb2d47",
                "status": "Not used. ESO ASM supplies direct seeing/tau0/theta0/turbulence-speed conditioning for this demonstrator; CDS credentials would be required for ERA5.",
            },
            {
                "source": "ESO Science Archive / Keck / Gemini / EIDC images",
                "identifier": "ESO archive URL, KOA, Gemini API, EIDC arXiv:2101.05080 and arXiv:2410.17636",
                "status": "Not used for current simulated-loop results. No on-sky PSF validation is claimed.",
            },
            {
                "source": "Observatory telemetry, DM influence matrices, RTC logs",
                "identifier": "No public file in repository",
                "status": "Not used. Detector, DM, latency, NCPA, registration, and control terms are synthetic engineering proxies.",
            },
        ],
        "source_index": [
            ("ESO ASM", "ESO Paranal ASM API and ambient query forms", "https://www.eso.org/asm/api/", "direct public atmosphere cache"),
            ("SVO FPS", "SVO Filter Profile Service", "https://svo2.cab.inta-csic.es/theory/fps/", "direct public 2MASS J/H/Ks filter curves"),
            ("2MASS", "IRSA 2MASS PSC", "https://irsa.ipac.caltech.edu/Missions/2mass.html ; DOI 10.1086/498708", "direct public J/H/Ks catalog photometry and filter identity"),
            ("Pan-STARRS", "MAST Pan-STARRS DR2 mean catalog", "arXiv:1612.05560 and arXiv:1612.05243", "direct public optical photometry substitute for Gaia"),
            ("AB magnitude", "AB photon-budget convention", "Oke & Gunn DOI 10.1086/113325", "700 nm WFS photon estimate from Pan-STARRS magnitudes"),
            ("Fried r0", "Fried parameter conversion", "DOI 10.1364/JOSA.56.001372", "r0 derived from ESO ASM seeing"),
            ("DM influence", "Gaussian synthetic DM influence functions", "arXiv:2306.10803", "literature-inspired DM shape choice"),
            ("Noll", "Zernike/statistical aberration background", "DOI 10.1364/JOSA.66.000207", "background reference for modal aberration vocabulary"),
        ],
    }


def markdown_inventory(inv: dict[str, object]) -> str:
    lines: list[str] = []
    lines.append("# AO detector-level extension parameter-source inventory")
    lines.append("")
    lines.append(f"Prepared: {inv['generated_on']}")
    lines.append("")
    lines.append(
        "Scope: tracked public caches, derived calculations, synthetic model parameters, "
        "and derived result artifacts used by the detector-level AO extension. Direct public "
        "data are separated from synthetic AO proxies."
    )
    lines.append("")
    _md_table(lines, "Direct public data caches used", inv["direct_public_data"], ["item", "file", "fields", "exact_values", "source_class", "source", "identifier"])
    _md_table(lines, "Derived calculations from public data", inv["derived_public_calculations"], ["calculation", "formula_or_assumption", "input", "output", "source"])
    _md_table(lines, "Notebook 11 observing/error conditions", inv["observing_conditions"], ["condition", "atmosphere", "seeing_r0", "photons_noise", "latency", "stroke_ncpa", "misregistration", "source"])
    _md_table(lines, "Synthetic and mixed model parameters actually used", inv["model_parameters"], ["subsystem", "parameters", "source_class", "source"])
    _md_table(lines, "Public-data-informed photon scan results", inv["public_data_informed_photon_scan"], ["case", "photons", "closed_rms_nm", "h_strehl", "command_rms_nm", "saturated_frac", "provenance"])
    _md_table(lines, "Public-data-informed scenario results", inv["conditioned_scenarios"], ["condition", "enabled_effects", "closed_rms_nm", "h_strehl", "valid_centroid_frac", "command_rms_nm", "saturated_frac", "decomposition"])
    _md_table(lines, "H-band science metrics", inv["h_band_summary"], ["case", "opd_rms_nm", "h_strehl", "source_class"])
    _md_table(lines, "Error-budget scenario results", inv["error_budget_scenarios"], ["scenario", "closed_rms_nm", "h_strehl", "command_rms_nm", "saturated_frac", "source_class"])
    _md_table(lines, "Long-run runtime records", inv["runtime_records"], ["script", "started_utc", "finished_utc", "runtime_minutes", "limit_minutes", "within_limit", "source"])
    lines.append(
        "**Validation scope note:** the public-data-informed checks below confirm public-data "
        "provenance, finite metrics, cache presence, and runtime. They are not an adaptive-optics "
        "performance validation. A faint scenario with `valid_centroid_frac = 0` has no usable WFS "
        "centroids, so its loop is frozen (closed RMS approaches open-loop) yet still passes these "
        "provenance/finite checks."
    )
    lines.append("")
    _md_table(lines, "Public-data-informed validation checks", inv["conditioned_validation"], ["check", "passed", "metric", "tolerance", "source_class", "message"])
    _md_table(lines, "Selected visual/result artifacts", [{"artifact": a, "contents": b, "basis": c} for a, b, c in inv["artifacts"]], ["artifact", "contents", "basis"])
    _md_table(lines, "Sources explicitly not claimed as used", inv["not_claimed"], ["source", "identifier", "status"])
    _md_table(lines, "Source index", [{"id": a, "source": b, "identifier": c, "use": d} for a, b, c, d in inv["source_index"]], ["id", "source", "identifier", "use"])
    return "\n".join(lines) + "\n"


def write_pdf(inv: dict[str, object], path: Path) -> None:
    """Write a normally formatted table PDF.

    ReportLab is intentionally imported inside this function so the Markdown
    inventory can still be regenerated in lean environments. If ReportLab is
    missing, failing loudly is better than silently producing a malformed
    Markdown-as-text PDF.
    """

    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError as exc:  # pragma: no cover - depends on local document runtime
        raise RuntimeError(
            "PDF generation requires reportlab. Use a Python environment with reportlab "
            "installed, or pass --no-pdf to write only Markdown."
        ) from exc

    page_size = landscape(A4)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="TitleCenter", parent=styles["Title"], alignment=TA_CENTER, fontSize=15, leading=18))
    styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=7.2, leading=8.6))
    styles.add(ParagraphStyle(name="Cell", parent=styles["BodyText"], fontSize=5.7, leading=6.8))
    styles.add(ParagraphStyle(name="HeaderCell", parent=styles["BodyText"], fontSize=5.9, leading=7.0, textColor=colors.white))

    doc = SimpleDocTemplate(
        str(path),
        pagesize=page_size,
        rightMargin=8 * mm,
        leftMargin=8 * mm,
        topMargin=9 * mm,
        bottomMargin=9 * mm,
        title="AO detector-level extension parameter-source inventory",
    )

    story: list[object] = [
        Paragraph("AO detector-level extension parameter-source inventory", styles["TitleCenter"]),
        Paragraph(f"Prepared: {inv['generated_on']}", styles["Small"]),
        Paragraph(
            "Scope: public caches, derived calculations, synthetic model parameters, derived result artifacts, "
            "runtime records, and sources explicitly not claimed as used. Direct public data are separated "
            "from synthetic AO proxies.",
            styles["Small"],
        ),
        Spacer(1, 5),
    ]

    _add_pdf_table(
        story,
        styles,
        page_size,
        "1. Direct public data caches used",
        inv["direct_public_data"],
        ["item", "file", "fields", "exact_values", "source_class", "source", "identifier"],
        weight_overrides={"source": 2.5, "identifier": 2.4, "exact_values": 2.0, "file": 1.4},
    )
    _add_pdf_table(
        story,
        styles,
        page_size,
        "2. Derived calculations from public data",
        inv["derived_public_calculations"],
        ["calculation", "formula_or_assumption", "input", "output", "source"],
        weight_overrides={"formula_or_assumption": 2.0, "source": 2.0},
    )
    _add_pdf_table(
        story,
        styles,
        page_size,
        "3. Notebook 11 observing/error conditions",
        inv["observing_conditions"],
        ["condition", "atmosphere", "seeing_r0", "photons_noise", "latency", "stroke_ncpa", "misregistration", "source"],
        weight_overrides={"source": 2.6, "misregistration": 1.8, "atmosphere": 1.5},
    )
    story.append(PageBreak())
    _add_pdf_table(
        story,
        styles,
        page_size,
        "4. Synthetic and mixed model parameters actually used",
        inv["model_parameters"],
        ["subsystem", "parameters", "source_class", "source"],
        weight_overrides={"parameters": 3.0, "source": 2.7},
    )
    _add_pdf_table(
        story,
        styles,
        page_size,
        "5. Public-data-informed photon scan results",
        inv["public_data_informed_photon_scan"],
        ["case", "photons", "closed_rms_nm", "h_strehl", "command_rms_nm", "saturated_frac", "provenance"],
        weight_overrides={"case": 1.6, "provenance": 1.8},
    )
    _add_pdf_table(
        story,
        styles,
        page_size,
        "6. Public-data-informed scenario results",
        inv["conditioned_scenarios"],
        ["condition", "enabled_effects", "closed_rms_nm", "h_strehl", "valid_centroid_frac", "command_rms_nm", "saturated_frac", "decomposition"],
        weight_overrides={"enabled_effects": 3.2, "decomposition": 2.4},
    )
    _add_pdf_table(
        story,
        styles,
        page_size,
        "7. Long-run runtime records",
        inv["runtime_records"],
        ["script", "started_utc", "finished_utc", "runtime_minutes", "limit_minutes", "within_limit", "source"],
        weight_overrides={"source": 2.7, "script": 1.8},
    )
    story.append(PageBreak())
    _add_pdf_table(
        story,
        styles,
        page_size,
        "8. H-band science metrics",
        inv["h_band_summary"],
        ["case", "opd_rms_nm", "h_strehl", "source_class"],
    )
    _add_pdf_table(
        story,
        styles,
        page_size,
        "9. Error-budget scenario results",
        inv["error_budget_scenarios"],
        ["scenario", "closed_rms_nm", "h_strehl", "command_rms_nm", "saturated_frac", "source_class"],
    )
    story.append(
        Paragraph(
            "Validation scope note: the public-data-informed checks below confirm public-data "
            "provenance, finite metrics, cache presence, and runtime; they are not an adaptive-optics "
            "performance validation. A faint scenario with valid_centroid_frac = 0 has no usable WFS "
            "centroids, so its loop is frozen (closed RMS approaches open-loop) yet still passes these checks.",
            styles["Small"],
        )
    )
    story.append(Spacer(1, 4))
    _add_pdf_table(
        story,
        styles,
        page_size,
        "10. Public-data-informed validation checks",
        inv["conditioned_validation"],
        ["check", "passed", "metric", "tolerance", "source_class", "message"],
        weight_overrides={"message": 2.6, "check": 1.7},
    )
    _add_pdf_table(
        story,
        styles,
        page_size,
        "11. Generated visual/result artifacts",
        [{"artifact": a, "contents": b, "basis": c} for a, b, c in inv["artifacts"]],
        ["artifact", "contents", "basis"],
        weight_overrides={"contents": 2.2, "basis": 1.7},
    )
    story.append(PageBreak())
    _add_pdf_table(
        story,
        styles,
        page_size,
        "12. Sources explicitly not claimed as used",
        inv["not_claimed"],
        ["source", "identifier", "status"],
        weight_overrides={"identifier": 2.2, "status": 2.6},
    )
    _add_pdf_table(
        story,
        styles,
        page_size,
        "13. Source index",
        [{"id": a, "source": b, "identifier": c, "use": d} for a, b, c, d in inv["source_index"]],
        ["id", "source", "identifier", "use"],
        weight_overrides={"source": 1.7, "identifier": 2.4, "use": 1.7},
    )

    doc.build(story, onFirstPage=_pdf_footer(page_size), onLaterPages=_pdf_footer(page_size))


def _add_pdf_table(
    story: list[object],
    styles,
    page_size: tuple[float, float],
    title: str,
    rows: object,
    columns: list[str],
    weight_overrides: dict[str, float] | None = None,
) -> None:
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    story.append(Paragraph(title, styles["Heading2"]))
    data = [[Paragraph(_pdf_cell_title(column), styles["HeaderCell"]) for column in columns]]
    for row in rows:  # type: ignore[assignment]
        data.append([Paragraph(_pdf_cell(str(row.get(column, ""))), styles["Cell"]) for column in columns])

    weights = [float((weight_overrides or {}).get(column, 1.0)) for column in columns]
    usable_width = page_size[0] - 16 * mm
    total = sum(weights)
    widths = [usable_width * weight / total for weight in weights]
    table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT", splitByRow=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#264653")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#b7b7b7")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f7f7")]),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 5))


def _pdf_footer(page_size: tuple[float, float]):
    from reportlab.lib import colors
    from reportlab.lib.units import mm

    def draw(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawString(8 * mm, 4.5 * mm, "AO detector-level extension parameter-source inventory")
        canvas.drawRightString(page_size[0] - 8 * mm, 4.5 * mm, f"Page {doc.page}")
        canvas.restoreState()

    return draw


def _pdf_cell(text: str) -> str:
    escaped = escape(text)
    wrapped = "<br/>".join(textwrap.wrap(escaped, width=48, break_long_words=True, break_on_hyphens=False))
    return wrapped or " "


def _pdf_cell_title(text: str) -> str:
    return escape(text.replace("_", " "))


def _md_table(lines: list[str], title: str, rows: object, columns: list[str]) -> None:
    lines.append(f"## {title}")
    lines.append("")
    lines.append("| " + " | ".join(columns) + " |")
    lines.append("| " + " | ".join("---" for _ in columns) + " |")
    for row in rows:  # type: ignore[assignment]
        lines.append("| " + " | ".join(_md_cell(str(row.get(col, ""))) for col in columns) + " |")
    lines.append("")


def _commented_csv(path: Path) -> tuple[dict[str, str], list[dict[str, str]]]:
    metadata: dict[str, str] = {}
    data_lines: list[str] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                body = stripped[1:].strip()
                if "=" in body:
                    key, value = body.split("=", 1)
                    metadata[key.strip()] = value.strip()
                continue
            data_lines.append(line)
    return metadata, list(csv.DictReader(data_lines))


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _metric_rows(path: Path) -> dict[str, dict[str, str]]:
    return {row["metric"]: row for row in _csv_rows(path)}


def _meta(metadata: dict[str, str], key: str) -> str:
    return metadata.get(key, "")


def _fmt(value: object) -> str:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(value)
    if abs(number) >= 1000 or (0 < abs(number) < 0.001):
        return f"{number:.6g}"
    return f"{number:.6f}".rstrip("0").rstrip(".")


def _md_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    main()
