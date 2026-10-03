"""Run a lightweight detector-level Shack-Hartmann centroiding demo."""

from __future__ import annotations

import os
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
from shwfs_ao.backends.native.shwfs import NativeShackHartmannOptics
from shwfs_ao.core.random import NamedRandomStreams
from shwfs_ao.core.wavefront import phase_to_opd
from shwfs_ao.detector.config import DetectorConfig
from shwfs_ao.wfs.shack_hartmann.geometry import build_shack_hartmann_geometry
from shwfs_ao.wfs.shack_hartmann.measurement import (
    build_detector_shack_hartmann_sensor,
)

# The demo phase is defined in radians; one wavelength converts it to the
# OPD the canonical sensor measures and sets the lenslet diffraction scale.
WAVELENGTH_M = 700.0e-9


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

    geometry = build_shack_hartmann_geometry(
        telescope_diameter_m=1.0,
        pupil_shape=(96, 96),
        n_lenslets_across=8,
        min_fill_fraction=0.35,
    )
    rho, theta = polar_pupil_coordinates(
        geometry.x_m,
        geometry.y_m,
        geometry.telescope_diameter_m,
    )
    modes = zernike_named_modes(rho, theta, geometry.pupil_mask)
    phase = synthesize_modes(
        modes,
        {
            "tip_x": 0.12,
            "tip_y": -0.08,
            "defocus": 0.20,
            "astig_0": 0.10,
        },
        geometry.pupil_mask,
    )

    streams = NamedRandomStreams(7)
    optics = NativeShackHartmannOptics(
        geometry,
        WAVELENGTH_M,
        pad_factor=4,
        detector_window_px=32,
    )
    sensor = build_detector_shack_hartmann_sensor(
        geometry,
        optics,
        DetectorConfig(
            photons_per_subap_frame=2.0e4,
            read_noise_e=2.0,
            background_e_per_pixel_frame=0.05,
        ),
        wfs_wavelength_m=WAVELENGTH_M,
        random_streams=streams,
    )
    measurement = sensor.measure(
        phase_to_opd(phase, WAVELENGTH_M),
        random_streams=streams,
        include_noise=True,
    )
    telemetry = measurement.detector_telemetry
    assert telemetry is not None
    centers = np.asarray(geometry.subaperture_centers_m, dtype=float)
    shifts = telemetry.centroids_xy_px - telemetry.reference_centroids_xy_px
    valid = telemetry.valid_subapertures

    table = pd.DataFrame(
        {
            "center_x": centers[:, 0],
            "center_y": centers[:, 1],
            "shift_x_pix": shifts[:, 0],
            "shift_y_pix": shifts[:, 1],
            "flux_e": telemetry.fluxes_e,
            "valid": valid,
        }
    )
    csv_path = output_dir / "shwfs_centroid_demo.csv"
    table.to_csv(csv_path, index=False)

    X, Y = geometry.x_m, geometry.y_m
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), constrained_layout=True)

    im = axes[0].imshow(
        np.where(geometry.pupil_mask, phase, np.nan),
        origin="lower",
        extent=[X.min(), X.max(), Y.min(), Y.max()],
        cmap="RdBu_r",
    )
    axes[0].set_title("Input phase")
    axes[0].set_xlabel("x pupil coordinate")
    axes[0].set_ylabel("y pupil coordinate")
    fig.colorbar(im, ax=axes[0], label="phase [rad]", fraction=0.046)

    scale = max(np.nanpercentile(np.abs(shifts[valid]), 95), 1e-6)
    axes[1].imshow(
        geometry.pupil_mask,
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

    print(f"Wrote {_display_path(png_path)}")
    print(f"Wrote {_display_path(csv_path)}")
    print(f"Valid centroids: {int(valid.sum())} / {valid.size}")


if __name__ == "__main__":
    main()
