"""Report science PSF metrics for open-loop, ideal closed-loop, and realistic closed-loop cases."""

from __future__ import annotations

import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

from shwfs_ao.core.geometry import PupilGeometry, build_pupil_geometry
from shwfs_ao.io.public_data import load_svo_filter_curve
from shwfs_ao.io.resources import resource_exists
from shwfs_ao.science.bandpass import (
    ScienceBandpass,
    bandpass_from_filter_curve,
    top_hat_bandpass,
)
from shwfs_ao.science.metrics import (
    band_average_scalar_metrics,
    psf_scalar_metrics,
)
from shwfs_ao.science.propagation import PsfSampling, monochromatic_psf


TELESCOPE_DIAMETER_M = 2.0
PAD_FACTOR = 5


def _demo_cases(pupil: PupilGeometry) -> dict[str, np.ndarray]:
    x = 2.0 * pupil.x_m / pupil.telescope_diameter_m
    y = 2.0 * pupil.y_m / pupil.telescope_diameter_m
    radius2 = x**2 + y**2
    aberration_nm = 260.0 * (x**2 - y**2) + 160.0 * x * y + 120.0 * (2.0 * radius2 - 1.0)
    mask = pupil.pupil_mask
    return {
        "open_loop": np.where(mask, aberration_nm, np.nan),
        "ideal_closed_loop": np.where(mask, 0.0, np.nan),
        "realistic_closed_loop": np.where(mask, 0.22 * aberration_nm, np.nan),
    }


def _band_metrics_row(
    case_name: str,
    opd_nm: np.ndarray,
    pupil: PupilGeometry,
    bandpass: ScienceBandpass,
) -> dict[str, float | str]:
    opd_m = opd_nm * 1.0e-9
    ideal_opd_m = np.where(pupil.pupil_mask, 0.0, np.nan)
    sampling = PsfSampling(pad_factor=PAD_FACTOR)
    per_wavelength = []
    for wavelength_m in np.asarray(bandpass.wavelength_m, dtype=float):
        psf = monochromatic_psf(
            opd_m,
            pupil,
            wavelength_m,
            backend="native",
            sampling=sampling,
        )
        ideal_psf = monochromatic_psf(
            ideal_opd_m,
            pupil,
            wavelength_m,
            backend="native",
            sampling=sampling,
        )
        per_wavelength.append(
            psf_scalar_metrics(
                psf,
                ideal_psf,
                opd_m,
                pupil,
                TELESCOPE_DIAMETER_M,
            )
        )
    averaged = band_average_scalar_metrics(per_wavelength, bandpass.weights)
    return {
        "case_name": case_name,
        "band_name": bandpass.name,
        "effective_wavelength_m": bandpass.effective_wavelength_m,
        "opd_rms_nm": averaged.opd_rms_m * 1.0e9,
        "strehl_peak": averaged.peak_strehl,
        "strehl_marechal": averaged.marechal_strehl,
        "fwhm_lambda_over_d": averaged.fwhm_lambda_over_d,
        "fwhm_arcsec": averaged.fwhm_arcsec,
        "ee50_lambda_over_d": averaged.ee50_lambda_over_d,
        "ee50_arcsec": averaged.ee50_arcsec,
        "ee80_lambda_over_d": averaged.ee80_lambda_over_d,
        "ee80_arcsec": averaged.ee80_arcsec,
        "halo_fraction": averaged.halo_fraction,
        "source_class": "synthetic_assumed",
        "source_note": (
            "Synthetic PSF diagnostic computed from a simulation residual OPD "
            f"map; bandpass provenance ({bandpass.source_class}): "
            f"{bandpass.source_note}"
        ),
    }


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def main() -> None:
    output_dir = Path(
        os.environ.get("AO_DEMO_OUTPUT_DIR", ROOT / "figures" / "detector_level_SCAO")
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    pupil = build_pupil_geometry(
        telescope_diameter_m=TELESCOPE_DIAMETER_M,
        pupil_shape=(96, 96),
    )
    bandpasses = _build_jhk_bandpasses()
    cases = _demo_cases(pupil)
    rows = [
        _band_metrics_row(case_name, opd_nm, pupil, bandpass)
        for case_name, opd_nm in cases.items()
        for bandpass in bandpasses
    ]
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

    print(f"Wrote {_display_path(png_path)}")
    print(f"Wrote {_display_path(csv_path)}")
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
