"""Run a lightweight PSF and Strehl-ratio demo."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

from psf_tools import compute_psf_from_phase, marechal_strehl, strehl_ratio
from zernike import make_pupil_grid, rms, synthesize_wavefront, zernike_named_modes


def _summarize_case(name: str, phase: np.ndarray, mask: np.ndarray) -> dict[str, float | str]:
    return {
        "case": name,
        "phase_rms_rad": rms(phase, mask),
        "strehl_peak_ratio": strehl_ratio(phase, mask, pad_factor=4),
        "strehl_marechal": marechal_strehl(phase, mask),
    }


def main() -> None:
    output_dir = ROOT / "figures" / "detector_level_SCAO"
    output_dir.mkdir(parents=True, exist_ok=True)

    X, Y, rho, theta, pupil_mask, _ = make_pupil_grid(N=128, diameter=1.0)
    modes = zernike_named_modes(rho, theta, pupil_mask)
    open_loop = synthesize_wavefront(
        modes,
        {
            "tip_x": 0.40,
            "tip_y": -0.25,
            "defocus": 0.70,
            "astig_45": -0.35,
            "coma_x": 0.30,
            "spherical": 0.25,
        },
        pupil_mask,
    )
    corrected = 0.18 * open_loop
    ideal = np.zeros_like(open_loop)

    cases = {
        "diffraction_limited": ideal,
        "open_loop": open_loop,
        "corrected": corrected,
    }

    rows = [_summarize_case(name, phase, pupil_mask) for name, phase in cases.items()]
    csv_path = output_dir / "psf_strehl_demo.csv"
    pd.DataFrame(rows).to_csv(csv_path, index=False)

    psfs = {name: compute_psf_from_phase(phase, pupil_mask, pad_factor=4) for name, phase in cases.items()}
    vmax = np.max(psfs["diffraction_limited"])

    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.6), constrained_layout=True)
    for ax, (name, psf) in zip(axes, psfs.items()):
        image = np.log10(psf / vmax + 1e-8)
        ax.imshow(image, origin="lower", cmap="magma", vmin=-8, vmax=0)
        ax.set_title(name.replace("_", " "))
        ax.set_xticks([])
        ax.set_yticks([])

    fig.suptitle("PSF sharpening from residual phase reduction")
    png_path = output_dir / "psf_strehl_demo.png"
    fig.savefig(png_path, dpi=120, pil_kwargs={"optimize": True})
    plt.close(fig)

    print(f"Wrote {png_path.relative_to(ROOT)}")
    print(f"Wrote {csv_path.relative_to(ROOT)}")
    for row in rows:
        print(
            f"{row['case']}: RMS={row['phase_rms_rad']:.3f} rad, "
            f"Strehl={row['strehl_peak_ratio']:.3f}"
        )


if __name__ == "__main__":
    main()
