"""Report science PSF metrics for open-loop, ideal closed-loop, and realistic closed-loop cases."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

from ao_diagnostics import (
    bandpass_from_filter_curve,
    science_case_metrics_table,
    science_metrics_as_dicts,
    top_hat_bandpass,
)
from data_sources import load_svo_filter_curve
from shwfs_ao.io.resources import resource_exists


def _demo_cases(n_pixels: int = 96) -> tuple[dict[str, np.ndarray], np.ndarray]:
    coords = np.linspace(-1.0, 1.0, n_pixels)
    x, y = np.meshgrid(coords, coords)
    pupil_mask = x**2 + y**2 <= 1.0
    radius2 = x**2 + y**2
    aberration_nm = 260.0 * (x**2 - y**2) + 160.0 * x * y + 120.0 * (2.0 * radius2 - 1.0)
    cases = {
        "open_loop": np.where(pupil_mask, aberration_nm, np.nan),
        "ideal_closed_loop": np.where(pupil_mask, 0.0, np.nan),
        "realistic_closed_loop": np.where(pupil_mask, 0.22 * aberration_nm, np.nan),
    }
    return cases, pupil_mask


def main() -> None:
    output_dir = ROOT / "figures" / "detector_level_SCAO"
    output_dir.mkdir(parents=True, exist_ok=True)

    bandpasses = _build_jhk_bandpasses()
    cases, pupil_mask = _demo_cases()
    metrics = science_case_metrics_table(
        cases,
        pupil_mask,
        bandpasses,
        telescope_diameter_m=2.0,
        pad_factor=5,
    )
    rows = list(science_metrics_as_dicts(metrics))
    csv_path = output_dir / "science_psf_metrics.csv"
    pd.DataFrame(rows).to_csv(csv_path, index=False)

    frame = pd.DataFrame(rows)
    order = ["open_loop", "realistic_closed_loop", "ideal_closed_loop"]
    colors = {"J": "#6a4c93", "H": "#1982c4", "K": "#8ac926"}
    fig, ax = plt.subplots(figsize=(7.2, 4.2), constrained_layout=True)
    x = np.arange(len(order))
    width = 0.24
    for offset, band in enumerate(["J", "H", "K"]):
        subset = frame[frame["band_name"] == band].set_index("case_name").loc[order]
        ax.bar(x + (offset - 1) * width, subset["strehl_peak"], width=width, label=band, color=colors[band])
    ax.set_xticks(x)
    ax.set_xticklabels(["open", "realistic", "ideal"])
    ax.set_ylim(0.0, 1.05)
    ax.set_ylabel("band-averaged Strehl")
    ax.set_title("Science PSF metrics")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(title="band")
    png_path = output_dir / "science_psf_metrics.png"
    fig.savefig(png_path, dpi=140, pil_kwargs={"optimize": True})
    plt.close(fig)

    print(f"Wrote {png_path.relative_to(ROOT)}")
    print(f"Wrote {csv_path.relative_to(ROOT)}")
    for case in order:
        h_row = frame[(frame["case_name"] == case) & (frame["band_name"] == "H")].iloc[0]
        print(
            f"{case}: H Strehl={h_row['strehl_peak']:.3f}, "
            f"FWHM={h_row['fwhm_lambda_over_d']:.2f} lambda/D, "
            f"EE50={h_row['ee50_lambda_over_d']:.2f} lambda/D"
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
