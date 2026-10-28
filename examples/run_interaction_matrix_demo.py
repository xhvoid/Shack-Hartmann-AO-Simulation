"""Build a detector-level DM poke matrix and plot its finite singular spectrum."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

from dm_model import DMConfig, build_dm_model
from interaction_matrix import (
    DEFAULT_POKE_AMPLITUDE_GRID_NM,
    PokeMatrixConfig,
    build_detector_dm_poke_matrix,
    poke_amplitude_scan,
    poke_matrix_summary,
)
from synthetic_instrument_data import DetectorConfig, ShwfsGeometryConfig, build_detector_shwfs_calibration


def main() -> None:
    output_dir = ROOT / "figures" / "detector_level_SCAO"
    output_dir.mkdir(parents=True, exist_ok=True)

    geometry = ShwfsGeometryConfig(
        telescope_diameter_m=2.0,
        n_pupil_pixels=72,
        n_lenslets=7,
        min_fill_fraction=0.35,
        pad_factor=3,
        detector_window_px=22,
        threshold_fraction=0.0,
        source_class="synthetic_assumed",
        source_note="Command-line demo synthetic 2 m SH-WFS geometry.",
    )
    calibration = build_detector_shwfs_calibration(
        geometry=geometry,
        detector=DetectorConfig(
            photons_per_subap_frame=None,
            source_class="synthetic_assumed",
            source_note="Command-line demo deterministic detector configuration.",
        ),
    )
    dm_model = build_dm_model(
        calibration.x_m,
        calibration.y_m,
        calibration.pupil_mask,
        DMConfig(
            telescope_diameter_m=2.0,
            n_actuators_across=6,
            influence_model="gaussian",
            coupling_width_pitch=0.40,
            stroke_limit_nm=150.0,
            source_class="synthetic_literature_inspired",
            source_note="Command-line demo synthetic Gaussian DM model.",
        ),
    )
    poke = build_detector_dm_poke_matrix(
        calibration,
        dm_model,
        PokeMatrixConfig(
            calibration_amplitude_nm=10.0,
            rcond_scan_grid=(1.0e-6, 3.0e-6, 1.0e-5, 3.0e-5, 1.0e-4, 3.0e-4, 1.0e-3, 3.0e-3),
            target_kept_mode_fraction=0.85,
            source_class="synthetic_assumed",
            source_note="Command-line demo central-difference poke configuration.",
        ),
    )

    rows = [
        {
            "mode_index": index,
            "singular_value_px_per_nm": value,
            "relative_singular_value": value / poke.singular_values[0],
            "kept_by_selected_rcond": index < poke.kept_modes,
        }
        for index, value in enumerate(poke.singular_values)
    ]
    csv_path = output_dir / "poke_matrix_singular_values.csv"
    pd.DataFrame(rows).to_csv(csv_path, index=False)

    fig, ax = plt.subplots(figsize=(6.2, 4.2), constrained_layout=True)
    mode_index = np.arange(poke.singular_values.size)
    ax.semilogy(mode_index, poke.singular_values / poke.singular_values[0], marker="o", linewidth=1.6)
    ax.axhline(poke.rcond, color="tab:red", linestyle="--", linewidth=1.2, label=f"rcond={poke.rcond:.1e}")
    ax.axvline(max(poke.kept_modes - 0.5, 0.0), color="0.35", linestyle=":", linewidth=1.0, label="kept modes")
    ax.set_xlabel("SVD mode index")
    ax.set_ylabel("relative singular value")
    ax.set_title("Detector-level DM poke matrix")
    ax.grid(True, which="both", alpha=0.25)
    ax.legend(loc="best")
    png_path = output_dir / "poke_matrix_singular_values.png"
    fig.savefig(png_path, dpi=140, pil_kwargs={"optimize": True})
    plt.close(fig)

    # Scan central-difference poke amplitude (2, 5, 10, 20, 50 nm) to show
    # how calibration amplitude drives the singular spectrum and the TSVD
    # noise-amplification proxy (reconstruction sensitivity).
    amplitude_rows = poke_amplitude_scan(
        calibration,
        dm_model,
        amplitudes_nm=DEFAULT_POKE_AMPLITUDE_GRID_NM,
        base_config=PokeMatrixConfig(
            rcond_scan_grid=(1.0e-6, 3.0e-6, 1.0e-5, 3.0e-5, 1.0e-4, 3.0e-4, 1.0e-3, 3.0e-3),
            target_kept_mode_fraction=0.85,
            source_class="synthetic_assumed",
            source_note="Poke-amplitude scan central-difference configuration.",
        ),
    )
    amplitude_csv = output_dir / "poke_amplitude_scan.csv"
    pd.DataFrame(amplitude_rows).to_csv(amplitude_csv, index=False)

    amplitudes = [row["calibration_amplitude_nm"] for row in amplitude_rows]
    largest_sv = [row["largest_singular_value_px_per_nm"] for row in amplitude_rows]
    noise_amp = [row["noise_amplification_proxy"] for row in amplitude_rows]
    fig2, ax_left = plt.subplots(figsize=(6.4, 4.2), constrained_layout=True)
    ax_left.plot(amplitudes, largest_sv, marker="o", color="tab:blue", linewidth=1.6)
    ax_left.set_xlabel("central-difference poke amplitude [nm OPD-equivalent]")
    ax_left.set_ylabel("largest singular value [detector px / nm]", color="tab:blue")
    ax_left.tick_params(axis="y", labelcolor="tab:blue")
    ax_left.grid(True, which="both", alpha=0.25)
    ax_right = ax_left.twinx()
    ax_right.plot(amplitudes, noise_amp, marker="s", color="tab:red", linewidth=1.4)
    ax_right.set_ylabel("TSVD noise amplification proxy", color="tab:red")
    ax_right.tick_params(axis="y", labelcolor="tab:red")
    ax_left.set_title("Poke-amplitude scan: signal vs reconstruction sensitivity")
    amplitude_png = output_dir / "poke_amplitude_scan.png"
    fig2.savefig(amplitude_png, dpi=140, pil_kwargs={"optimize": True})
    plt.close(fig2)

    summary = poke_matrix_summary(poke)
    print(f"Wrote {png_path.relative_to(ROOT)}")
    print(f"Wrote {csv_path.relative_to(ROOT)}")
    print(f"Wrote {amplitude_png.relative_to(ROOT)}")
    print(f"Wrote {amplitude_csv.relative_to(ROOT)}")
    print(
        "Poke matrix: "
        f"shape={tuple(summary['matrix_shape'])}, "
        f"rank={summary['rank']}, "
        f"kept_modes={summary['kept_modes']}, "
        f"rcond={summary['rcond']:.1e}, "
        f"config_hash={summary['config_hash'][:12]}"
    )


if __name__ == "__main__":
    main()
