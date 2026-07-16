"""Run validation checks and write pass/fail rows plus monotonicity scan plots."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

from ao_closed_loop import DetectorLoopConfig
from ao_error_budget import (
    ScenarioConfig,
    build_control_space_phase_sequence,
    default_jhk_bandpasses,
    run_error_budget_scenario,
)
from ao_validation import (
    check_centroid_noise_photon_monotonicity,
    check_diffraction_scale,
    check_dm_fitting_trend,
    check_latency_residual_monotonicity,
    check_marechal_consistency,
    check_scenario_reproducibility,
    validation_results_as_dicts,
)
from dm_model import DMConfig, build_dm_model
from interaction_matrix import PokeMatrixConfig, build_detector_dm_poke_matrix
from synthetic_instrument_data import DetectorConfig, ShwfsGeometryConfig, build_detector_shwfs_calibration


def _gaussian_spot(size: int = 17, sigma_px: float = 2.0) -> np.ndarray:
    coords = np.arange(size) - (size - 1) / 2.0
    x, y = np.meshgrid(coords, coords)
    spot = np.exp(-(x**2 + y**2) / (2.0 * sigma_px**2))
    return spot / np.sum(spot)


def _build_fast_system():
    geometry = ShwfsGeometryConfig(
        telescope_diameter_m=2.0,
        n_pupil_pixels=52,
        n_lenslets=5,
        min_fill_fraction=0.35,
        pad_factor=3,
        detector_window_px=18,
        threshold_fraction=0.0,
        source_class="synthetic_assumed",
        source_note="Command-line validation demo geometry.",
    )
    calibration = build_detector_shwfs_calibration(
        geometry=geometry,
        detector=DetectorConfig(
            photons_per_subap_frame=8000.0,
            read_noise_e=1.0,
            qe=1.0,
            source_class="synthetic_assumed",
            source_note="Command-line validation detector settings.",
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
            source_note="Command-line validation synthetic Gaussian DM model.",
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
            source_note="Command-line validation detector-level poke configuration.",
        ),
    )
    return calibration, dm_model, poke


def main() -> None:
    output_dir = ROOT / "figures" / "detector_level_SCAO"
    output_dir.mkdir(parents=True, exist_ok=True)

    calibration, dm_model, poke = _build_fast_system()
    x = calibration.x_m
    y = calibration.y_m
    mask = calibration.pupil_mask
    small_opd_nm = np.where(mask, 45.0 * (x**2 - y**2), np.nan)
    target_opd_nm = np.where(
        mask,
        120.0 * (x**2 - y**2) + 70.0 * x * y + 35.0 * np.sin(3.0 * np.pi * x / 2.0) * np.cos(2.0 * np.pi * y / 2.0),
        np.nan,
    )

    photon_scan = check_centroid_noise_photon_monotonicity(
        _gaussian_spot(),
        photon_counts=(200.0, 1000.0, 5000.0, 20000.0),
        detector_template=DetectorConfig(
            read_noise_e=0.0,
            qe=1.0,
            source_class="synthetic_assumed",
            source_note="Demo photon monotonicity detector template.",
        ),
        n_trials=160,
        seed=3,
    )
    scenario = ScenarioConfig(
        "validation_dynamic",
        ("multi_component_dynamic_phase",),
        n_steps=12,
        phase_amplitude_nm=260.0,
        source_note="Demo latency validation scenario.",
    )
    phase_sequence = build_control_space_phase_sequence(calibration, dm_model, poke, scenario)
    latency_scan = check_latency_residual_monotonicity(
        phase_sequence,
        calibration,
        dm_model,
        poke,
        latency_frames=(0, 1, 2),
        base_loop_config=DetectorLoopConfig(
            n_steps=12,
            gain=0.32,
            leak=0.02,
            include_detector_noise=False,
            source_note="Demo latency validation loop config.",
        ),
    )
    fitting_scan = check_dm_fitting_trend(
        target_opd_nm,
        x,
        y,
        mask,
        actuator_counts=(4, 6, 8),
        dm_config_template=DMConfig(
            telescope_diameter_m=2.0,
            influence_model="gaussian",
            coupling_width_pitch=0.45,
            stroke_limit_nm=1000.0,
            source_class="synthetic_literature_inspired",
            source_note="Demo fitting trend DM template.",
        ),
    )
    repro_scenario = ScenarioConfig(
        "validation_reproducibility",
        ("multi_component_dynamic_phase", "detector_noise"),
        n_steps=10,
        phase_amplitude_nm=240.0,
        include_detector_noise=True,
        seed=31,
        source_note="Demo reproducibility scenario.",
    )
    bands = default_jhk_bandpasses()
    first = run_error_budget_scenario(calibration, dm_model, poke, repro_scenario, bands, pad_factor=3)
    second = run_error_budget_scenario(calibration, dm_model, poke, repro_scenario, bands, pad_factor=3)
    checks = (
        check_marechal_consistency(small_opd_nm, mask, wavelength_m=1.65e-6, telescope_diameter_m=2.0),
        check_diffraction_scale(mask, wavelength_m=1.65e-6, telescope_diameter_m=2.0),
        photon_scan,
        latency_scan,
        fitting_scan,
        check_scenario_reproducibility((first,), (second,)),
    )
    rows = list(validation_results_as_dicts(checks))
    csv_path = output_dir / "validation_checks.csv"
    pd.DataFrame(rows).to_csv(csv_path, index=False)

    fig, axes = plt.subplots(1, 3, figsize=(11.0, 3.6), constrained_layout=True)
    axes[0].loglog(photon_scan.x_values, photon_scan.metric_values, marker="o", color="#1982c4")
    axes[0].set_xlabel("photons/subap/frame")
    axes[0].set_ylabel("centroid RMS [px]")
    axes[0].set_title("Photon monotonicity")
    axes[0].grid(True, which="both", alpha=0.25)

    axes[1].plot(latency_scan.x_values, latency_scan.metric_values, marker="o", color="#e76f51")
    axes[1].set_xlabel("latency [frames]")
    axes[1].set_ylabel("median residual [nm]")
    axes[1].set_title("Latency penalty")
    axes[1].grid(True, alpha=0.25)

    axes[2].plot(fitting_scan.x_values, fitting_scan.metric_values, marker="o", color="#2a9d8f")
    axes[2].set_xlabel("actuators across")
    axes[2].set_ylabel("fit residual [nm]")
    axes[2].set_title("DM fitting trend")
    axes[2].grid(True, alpha=0.25)

    png_path = output_dir / "validation_scans.png"
    fig.savefig(png_path, dpi=140, pil_kwargs={"optimize": True})
    plt.close(fig)

    print(f"Wrote {png_path.relative_to(ROOT)}")
    print(f"Wrote {csv_path.relative_to(ROOT)}")
    for result in checks:
        name = result.check_name
        passed = result.passed
        print(f"{name}: {'PASS' if passed else 'FAIL'}")


if __name__ == "__main__":
    main()
