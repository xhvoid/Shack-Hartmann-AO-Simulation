"""Generate the 8-scenario AO error-budget table and summary plot."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

from ao_diagnostics import bandpass_from_filter_curve, top_hat_bandpass
from ao_error_budget import default_error_budget_scenarios, run_error_budget_scenarios, scenario_results_as_dicts
from data_sources import load_svo_filter_curve
from dm_model import DMConfig, build_dm_model
from interaction_matrix import PokeMatrixConfig, build_detector_dm_poke_matrix
from shwfs_ao.io.resources import resource_exists
from synthetic_instrument_data import DetectorConfig, ShwfsGeometryConfig, build_detector_shwfs_calibration


def _build_fast_demo_system():
    geometry = ShwfsGeometryConfig(
        telescope_diameter_m=2.0,
        n_pupil_pixels=52,
        n_lenslets=5,
        min_fill_fraction=0.35,
        pad_factor=3,
        detector_window_px=18,
        threshold_fraction=0.0,
        source_class="synthetic_assumed",
        source_note="Command-line demo 2 m detector-level SH-WFS geometry.",
    )
    calibration = build_detector_shwfs_calibration(
        geometry=geometry,
        detector=DetectorConfig(
            photons_per_subap_frame=8000.0,
            read_noise_e=1.0,
            qe=1.0,
            source_class="synthetic_assumed",
            source_note="Command-line demo detector-noise configuration.",
        ),
    )
    dm_model = build_dm_model(
        calibration.x_m,
        calibration.y_m,
        calibration.pupil_mask,
        DMConfig(
            telescope_diameter_m=2.0,
            n_actuators_across=5,
            influence_model="gaussian",
            coupling_width_pitch=0.40,
            stroke_limit_nm=1000.0,
            source_class="synthetic_literature_inspired",
            source_note="Command-line demo synthetic Gaussian DM model.",
        ),
    )
    poke = build_detector_dm_poke_matrix(
        calibration,
        dm_model,
        PokeMatrixConfig(
            calibration_amplitude_nm=10.0,
            rcond_scan_grid=(1.0e-8, 1.0e-6, 1.0e-4, 1.0e-3),
            target_kept_mode_fraction=1.0,
            source_class="synthetic_assumed",
            source_note="Command-line demo detector-level poke configuration.",
        ),
    )
    return calibration, dm_model, poke


def main() -> None:
    output_dir = ROOT / "figures" / "detector_level_SCAO"
    output_dir.mkdir(parents=True, exist_ok=True)

    calibration, dm_model, poke = _build_fast_demo_system()
    bandpasses = _build_jhk_bandpasses()
    scenarios = default_error_budget_scenarios(n_steps=12, phase_amplitude_nm=260.0)
    results = run_error_budget_scenarios(
        calibration,
        dm_model,
        poke,
        scenarios=scenarios,
        bandpasses=bandpasses,
        telescope_diameter_m=2.0,
        pad_factor=3,
    )
    rows = list(scenario_results_as_dicts(results))
    frame = pd.DataFrame(rows)
    csv_path = output_dir / "error_budget_scenarios.csv"
    frame.to_csv(csv_path, index=False)

    fig, ax1 = plt.subplots(figsize=(8.6, 4.8), constrained_layout=True)
    x = np.arange(len(frame))
    ax1.bar(x - 0.18, frame["open_rms_nm"], width=0.35, color="#8d99ae", label="open RMS")
    ax1.bar(x + 0.18, frame["closed_rms_nm"], width=0.35, color="#2a9d8f", label="closed RMS")
    ax1.set_ylabel("OPD RMS [nm]")
    ax1.set_xticks(x)
    ax1.set_xticklabels(frame["scenario_name"], rotation=35, ha="right")
    ax1.grid(axis="y", alpha=0.25)
    ax2 = ax1.twinx()
    ax2.plot(x, frame["strehl_H"], color="#e76f51", marker="o", linewidth=1.8, label="closed H Strehl")
    ax2.set_ylim(0.0, 1.05)
    ax2.set_ylabel("H-band Strehl")
    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(handles1 + handles2, labels1 + labels2, loc="upper left")
    ax1.set_title("Fast AO error-budget scenarios")
    png_path = output_dir / "error_budget_scenarios.png"
    fig.savefig(png_path, dpi=140, pil_kwargs={"optimize": True})
    plt.close(fig)

    print(f"Wrote {png_path.relative_to(ROOT)}")
    print(f"Wrote {csv_path.relative_to(ROOT)}")
    for row in rows:
        print(
            f"{row['scenario_name']}: closed RMS={row['closed_rms_nm']:.1f} nm, "
            f"H Strehl={row['strehl_H']:.3f}, "
            f"valid centroids={row['valid_centroid_frac']:.2f}"
        )


def _build_jhk_bandpasses():
    specs = (
        ("J", Path("data/public/svo_2mass_j_direct.csv"), (1.10e-6, 1.40e-6)),
        ("H", Path("data/public/svo_2mass_h_direct.csv"), (1.50e-6, 1.80e-6)),
        ("K", Path("data/public/svo_2mass_ks_direct.csv"), (2.00e-6, 2.35e-6)),
    )
    bandpasses = []
    for name, public_path, fallback_range in specs:
        fallback_path = Path("data/samples/svo_2mass_h_sample.csv") if name == "H" else None
        path = _first_existing_path(public_path, fallback_path) if fallback_path is not None else _first_existing_path(public_path)
        if path is not None:
            bandpasses.append(bandpass_from_filter_curve(load_svo_filter_curve(path), name=name))
        else:
            bandpasses.append(
                top_hat_bandpass(
                    name,
                    *fallback_range,
                    source_note=f"Demo synthetic {name}-band top-hat fallback; no direct SVO cache was found.",
                )
            )
    return tuple(bandpasses)


def _first_existing_path(*paths: Path | None) -> Path | None:
    for path in paths:
        if path is not None and resource_exists(path):
            return path
    return None


if __name__ == "__main__":
    main()
