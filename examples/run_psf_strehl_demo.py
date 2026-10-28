"""Run a lightweight PSF and Strehl-ratio demo."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

from shwfs_ao.backends.native.modes import (
    polar_pupil_coordinates,
    synthesize_modes,
    zernike_named_modes,
)
from shwfs_ao.core.geometry import PupilGeometry, build_pupil_geometry
from shwfs_ao.core.types import PsfResult
from shwfs_ao.core.wavefront import masked_rms, phase_to_opd
from shwfs_ao.science.metrics import (
    marechal_strehl_from_opd,
    peak_strehl_from_discrete_flux,
)
from shwfs_ao.science.propagation import PsfSampling, monochromatic_psf

# The demo cases are defined as phase in radians; the wavelength cancels
# because the same value converts phase to OPD and propagates the PSF.
WAVELENGTH_M = 500.0e-9


def _case_psf(phase: np.ndarray, pupil: PupilGeometry) -> PsfResult:
    return monochromatic_psf(
        phase_to_opd(phase, WAVELENGTH_M),
        pupil,
        WAVELENGTH_M,
        backend="native",
        sampling=PsfSampling(pad_factor=4),
    )


def _summarize_case(
    name: str,
    phase: np.ndarray,
    pupil: PupilGeometry,
    psf: PsfResult,
    ideal_psf: PsfResult,
) -> dict[str, float | str]:
    return {
        "case": name,
        "phase_rms_rad": masked_rms(phase, pupil.pupil_mask),
        "strehl_peak_ratio": peak_strehl_from_discrete_flux(psf, ideal_psf),
        "strehl_marechal": marechal_strehl_from_opd(
            phase_to_opd(phase, WAVELENGTH_M),
            pupil.pupil_mask,
            WAVELENGTH_M,
        ),
    }


def main() -> None:
    output_dir = ROOT / "figures" / "detector_level_SCAO"
    output_dir.mkdir(parents=True, exist_ok=True)

    pupil = build_pupil_geometry(
        telescope_diameter_m=1.0,
        pupil_shape=(128, 128),
    )
    rho, theta = polar_pupil_coordinates(
        pupil.x_m,
        pupil.y_m,
        pupil.telescope_diameter_m,
    )
    modes = zernike_named_modes(rho, theta, pupil.pupil_mask)
    open_loop = synthesize_modes(
        modes,
        {
            "tip_x": 0.40,
            "tip_y": -0.25,
            "defocus": 0.70,
            "astig_45": -0.35,
            "coma_x": 0.30,
            "spherical": 0.25,
        },
        pupil.pupil_mask,
    )
    corrected = 0.18 * open_loop
    ideal = np.zeros_like(open_loop)

    cases = {
        "diffraction_limited": ideal,
        "open_loop": open_loop,
        "corrected": corrected,
    }

    psfs = {name: _case_psf(phase, pupil) for name, phase in cases.items()}
    ideal_psf = psfs["diffraction_limited"]
    rows = [
        _summarize_case(name, phase, pupil, psfs[name], ideal_psf)
        for name, phase in cases.items()
    ]
    csv_path = output_dir / "psf_strehl_demo.csv"
    pd.DataFrame(rows).to_csv(csv_path, index=False)

    vmax = np.max(ideal_psf.intensity)

    fig, axes = plt.subplots(1, 3, figsize=(10.5, 3.6), constrained_layout=True)
    for ax, (name, psf) in zip(axes, psfs.items()):
        image = np.log10(psf.intensity / vmax + 1e-8)
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
