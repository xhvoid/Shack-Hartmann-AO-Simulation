"""Run a lightweight detector-level Shack-Hartmann centroiding demo."""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from shwfs_detector import measure_centroid_shifts
from zernike import make_pupil_grid, synthesize_wavefront, zernike_named_modes


def main() -> None:
    output_dir = ROOT / "figures" / "detector_level_SCAO"
    output_dir.mkdir(parents=True, exist_ok=True)

    X, Y, rho, theta, pupil_mask, _ = make_pupil_grid(N=96, diameter=1.0)
    modes = zernike_named_modes(rho, theta, pupil_mask)
    phase = synthesize_wavefront(
        modes,
        {
            "tip_x": 0.12,
            "tip_y": -0.08,
            "defocus": 0.20,
            "astig_0": 0.10,
        },
        pupil_mask,
    )

    centers, shifts, spots, diagnostics = measure_centroid_shifts(
        phase,
        pupil_mask,
        X,
        Y,
        n_lenslets=8,
        min_fill=0.35,
        pad_factor=4,
        photons=2.0e4,
        read_noise_e=2.0,
        background_e=0.05,
        detector_window_size=32,
        seed=7,
        return_spots=True,
        return_diagnostics=True,
    )

    table = pd.DataFrame(
        {
            "center_x": centers[:, 0],
            "center_y": centers[:, 1],
            "shift_x_pix": shifts[:, 0],
            "shift_y_pix": shifts[:, 1],
            "flux_e": diagnostics["fluxes"],
            "valid": diagnostics["valid"],
        }
    )
    csv_path = output_dir / "shwfs_centroid_demo.csv"
    table.to_csv(csv_path, index=False)

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), constrained_layout=True)

    im = axes[0].imshow(
        np.where(pupil_mask, phase, np.nan),
        origin="lower",
        extent=[X.min(), X.max(), Y.min(), Y.max()],
        cmap="RdBu_r",
    )
    axes[0].set_title("Input phase")
    axes[0].set_xlabel("x pupil coordinate")
    axes[0].set_ylabel("y pupil coordinate")
    fig.colorbar(im, ax=axes[0], label="phase [rad]", fraction=0.046)

    valid = diagnostics["valid"]
    scale = max(np.nanpercentile(np.abs(shifts[valid]), 95), 1e-6)
    axes[1].imshow(
        pupil_mask,
        origin="lower",
        extent=[X.min(), X.max(), Y.min(), Y.max()],
        cmap="Greys",
        alpha=0.25,
    )
    axes[1].quiver(
        centers[valid, 0],
        centers[valid, 1],
        shifts[valid, 0],
        shifts[valid, 1],
        angles="xy",
        scale_units="xy",
        scale=scale * 12.0,
        color="#0b5cad",
        width=0.006,
    )
    axes[1].set_aspect("equal")
    axes[1].set_title("Measured centroid shifts")
    axes[1].set_xlabel("x pupil coordinate")
    axes[1].set_ylabel("y pupil coordinate")

    png_path = output_dir / "shwfs_centroid_demo.png"
    fig.savefig(png_path, dpi=140, pil_kwargs={"optimize": True})
    plt.close(fig)

    print(f"Wrote {png_path.relative_to(ROOT)}")
    print(f"Wrote {csv_path.relative_to(ROOT)}")
    print(f"Valid centroids: {diagnostics['n_valid']} / {diagnostics['n_total']}")


if __name__ == "__main__":
    main()
