"""ESO E-ELT ten-layer turbulence: profile, screen statistics, and SCAO loop.

Loads the atmosphere ESO used for its E-ELT Design Reference Mission OCTOPUS
simulations (r0 = 0.13 m at 500 nm, L0 = 25 m, ten layers), checks that the
native ``native_layered`` screens reproduce the von Karman phase structure
function, and runs the packaged ``eso_turbulence_2m_detector@1`` SCAO profile
against ``portfolio_2m_detector@4``: the same 2 m detector-level system under
its single 10 m/s layer.

Writes ``eso_elt_turbulence_demo.png`` plus the CSV tables behind it to
``$AO_DEMO_OUTPUT_DIR`` or, when that variable is unset, to the disposable
``outputs/examples/eso_elt_turbulence``.  To refresh the tracked README figure,
set ``AO_DEMO_OUTPUT_DIR=figures/eso_elt_turbulence`` explicitly.
Runtime is about a minute.
"""

from __future__ import annotations

import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import numpy as np
import pandas as pd
from scipy.special import j0

ROOT = Path(__file__).resolve().parents[1]

from shwfs_ao.backends.native.layered_atmosphere import (
    FrozenFlowLayer,
    LayeredFrozenFlowAtmosphere,
    LayeredFrozenFlowAtmosphereConfig,
)
from shwfs_ao.experiments import build_scao_system, run_closed_loop
from shwfs_ao.io import eso_elt_turbulence_profile, load_system_profile

WAVELENGTH_M = 500.0e-9
N_REALIZATIONS = 8
# At r = 1 m one 2 m screen estimates D(r) to about 80 %; 256 screens to 5 %.
N_SCREENS = 256
PROFILES = (
    ("portfolio_2m_detector", 4, "Single layer, 10 m/s"),
    ("eso_turbulence_2m_detector", 1, "ESO E-ELT 10 layers"),
)
# Reference palette (dataviz skill, light mode): series slots and text inks.
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
GRID = "#e4e3df"
SERIES = ("#2a78d6", "#eb6834")
DIVERGING = LinearSegmentedColormap.from_list(
    "blue_gray_red", ("#2a78d6", "#f0efec", "#e34948")
)


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _von_karman_structure_function_rad2(
    separation_m: np.ndarray, r0_m: float, outer_scale_m: float
) -> np.ndarray:
    """D(r) = 2 * integral of Phi(f) [1 - J0(2 pi f r)] 2 pi f df."""

    log_frequency = np.linspace(-6.0, 3.0, 60_001)
    frequency = 10.0**log_frequency
    psd = 0.023 * r0_m ** (-5.0 / 3.0) * (
        frequency**2 + outer_scale_m**-2
    ) ** (-11.0 / 6.0)
    values = []
    for separation in separation_m:
        integrand = (
            2.0 * psd * (1.0 - j0(2.0 * np.pi * frequency * separation))
            * 2.0 * np.pi * frequency**2 * np.log(10.0)
        )
        values.append(
            np.sum(0.5 * (integrand[1:] + integrand[:-1]) * np.diff(log_frequency))
        )
    return np.asarray(values)


def _measured_structure_function(
    profile, diameter_m: float, grid_size: int, lags_px: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Average D(r) along x and y over independent ESO screen realizations."""

    layers = tuple(
        FrozenFlowLayer(layer.cn2_fraction, layer.wind_m_per_s, layer.altitude_m)
        for layer in profile.layers
    )
    atmosphere = LayeredFrozenFlowAtmosphere(
        LayeredFrozenFlowAtmosphereConfig(
            grid_size=grid_size,
            delta_m=diameter_m / grid_size,
            pupil_diameter_m=diameter_m,
            r0_m=profile.r0_m,
            layers=layers,
            outer_scale_m=profile.outer_scale_m,
            phase_reference_wavelength_m=profile.r0_reference_wavelength_m,
            root_seed=2026,
        )
    )
    sums = np.zeros(len(lags_px))
    example = None
    for index in range(N_SCREENS):
        atmosphere.reset(realization_index=index)
        phase = atmosphere._phase_rad(0.0)
        if example is None:
            example = atmosphere.opd_at(0.0) * 1e9
        for slot, lag in enumerate(lags_px):
            sums[slot] += 0.5 * (
                np.mean((phase[:, lag:] - phase[:, :-lag]) ** 2)
                + np.mean((phase[lag:, :] - phase[:-lag, :]) ** 2)
            )
    return sums / N_SCREENS, example


def _closed_loop_runs() -> pd.DataFrame:
    rows = []
    for name, version, label in PROFILES:
        config = load_system_profile(name, version)
        system = build_scao_system(config)
        for index in range(N_REALIZATIONS):
            result = run_closed_loop(config, system=system, realization_index=index)
            for frame, (time_s, open_rms, residual_rms) in enumerate(
                zip(
                    result.time_s,
                    result.open_loop_opd_rms_m,
                    result.post_update_residual_opd_rms_m,
                )
            ):
                rows.append(
                    {
                        "profile": f"{name}@{version}",
                        "atmosphere": label,
                        "realization_index": index,
                        "frame": frame,
                        "time_s": float(time_s),
                        "open_loop_rms_nm": float(open_rms) * 1e9,
                        "residual_rms_nm": float(residual_rms) * 1e9,
                    }
                )
    return pd.DataFrame(rows)


def _style(axis) -> None:
    axis.set_facecolor(SURFACE)
    axis.grid(True, color=GRID, linewidth=0.6)
    axis.set_axisbelow(True)
    for side in ("top", "right"):
        axis.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        axis.spines[side].set_color(INK_SECONDARY)
    axis.tick_params(colors=INK_SECONDARY, labelsize=8)
    axis.xaxis.label.set_color(INK)
    axis.yaxis.label.set_color(INK)
    axis.title.set_color(INK)


def main() -> None:
    output_dir = Path(
        os.environ.get("AO_DEMO_OUTPUT_DIR", ROOT / "outputs" / "examples" / "eso_elt_turbulence")
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    profile = eso_elt_turbulence_profile()

    layer_table = pd.DataFrame(
        {
            "altitude_m": [layer.altitude_m for layer in profile.layers],
            "published_cn2_fraction": [
                round(layer.cn2_fraction * profile.published_cn2_fraction_sum, 6)
                for layer in profile.layers
            ],
            "cn2_fraction": [layer.cn2_fraction for layer in profile.layers],
            "wind_speed_m_per_s": [layer.wind_speed_m_per_s for layer in profile.layers],
            "layer_r0_500nm_m": profile.layer_r0_m,
        }
    )
    layer_path = output_dir / "eso_elt_turbulence_profile.csv"
    layer_table.to_csv(layer_path, index=False)
    print(f"ESO E-ELT DRM turbulence ({profile.provenance.url})")
    print(
        f"  r0 = {profile.r0_m:.3f} m at 500 nm, L0 = {profile.outer_scale_m:g} m, "
        f"seeing = {profile.seeing_arcsec:.3f} arcsec "
        f"(von Karman FWHM {profile.von_karman_seeing_arcsec:.3f} arcsec)"
    )
    print(
        f"  v_eff = {profile.effective_wind_speed_m_per_s:.2f} m/s, "
        f"tau0 = {profile.coherence_time_s * 1e3:.2f} ms, "
        f"theta0 = {profile.isoplanatic_angle_arcsec:.2f} arcsec, "
        f"f_G = {profile.greenwood_frequency_hz:.1f} Hz"
    )
    print(f"Wrote {_display_path(layer_path)}")

    diameter_m, grid_size = 2.0, 128
    lags_px = np.unique(np.geomspace(1, 64, 12).astype(int))
    separations_m = lags_px * diameter_m / grid_size
    measured, example_opd_nm = _measured_structure_function(
        profile, diameter_m, grid_size, lags_px
    )
    theory = _von_karman_structure_function_rad2(
        separations_m, profile.r0_m, profile.outer_scale_m
    )
    structure = pd.DataFrame(
        {
            "separation_m": separations_m,
            "measured_rad2": measured,
            "von_karman_rad2": theory,
            "ratio": measured / theory,
        }
    )
    structure_path = output_dir / "eso_elt_structure_function.csv"
    structure.to_csv(structure_path, index=False)
    # The screens carry no power above the pixel Nyquist frequency (ESO's
    # "inner scale = pixel size"), which lowers D at a one-pixel separation.
    resolved = structure["separation_m"] >= 2.0 * diameter_m / grid_size
    print(
        "Structure function, measured/theory for r >= 2 px: "
        f"{structure.loc[resolved, 'ratio'].min():.3f} to "
        f"{structure.loc[resolved, 'ratio'].max():.3f} "
        f"(one pixel: {structure['ratio'].iloc[0]:.3f})"
    )
    print(f"Wrote {_display_path(structure_path)}")

    runs = _closed_loop_runs()
    runs_path = output_dir / "eso_elt_closed_loop.csv"
    runs.to_csv(runs_path, index=False)
    print(f"Wrote {_display_path(runs_path)}")
    summary = (
        runs[runs["frame"] >= 50]
        .groupby("atmosphere", sort=False)[["open_loop_rms_nm", "residual_rms_nm"]]
        .mean()
    )
    for label, row in summary.iterrows():
        print(
            f"  {label}: open loop {row['open_loop_rms_nm']:.0f} nm, "
            f"closed loop {row['residual_rms_nm']:.0f} nm RMS "
            f"(frames 50+, mean of {N_REALIZATIONS} realizations)"
        )

    figure, axes = plt.subplots(2, 2, figsize=(11.0, 8.4), facecolor=SURFACE)
    figure.subplots_adjust(hspace=0.42, wspace=0.32)

    axis = axes[0, 0]
    altitudes_km = layer_table["altitude_m"] / 1e3
    axis.barh(
        np.arange(len(layer_table)),
        layer_table["cn2_fraction"],
        height=0.62,
        color=SERIES[0],
        edgecolor=SURFACE,
        linewidth=2.0,
    )
    for row, (fraction, speed) in enumerate(
        zip(layer_table["cn2_fraction"], layer_table["wind_speed_m_per_s"])
    ):
        axis.text(
            fraction + 0.006, row, f"{speed:g} m/s",
            va="center", fontsize=7.5, color=INK_SECONDARY,
        )
    axis.set_yticks(np.arange(len(layer_table)))
    axis.set_yticklabels([f"{value:g} km" for value in altitudes_km])
    axis.set_xlim(0.0, 0.42)
    axis.set_xlabel("Fractional Cn$^2$ (labels: wind speed)")
    axis.set_title("ESO E-ELT turbulence profile", fontsize=10, loc="left")
    _style(axis)
    axis.grid(axis="y", visible=False)

    axis = axes[0, 1]
    limit = float(np.nanmax(np.abs(example_opd_nm)))
    image = axis.imshow(
        example_opd_nm, cmap=DIVERGING, vmin=-limit, vmax=limit,
        origin="lower", extent=(0.0, diameter_m, 0.0, diameter_m),
    )
    colorbar = figure.colorbar(image, ax=axis, fraction=0.046, pad=0.03)
    colorbar.set_label("OPD [nm]", color=INK, fontsize=8)
    colorbar.ax.tick_params(colors=INK_SECONDARY, labelsize=8)
    axis.set_xlabel("x [m]")
    axis.set_ylabel("y [m]")
    axis.set_title("One 2 m pupil realization (10 layers summed)", fontsize=10, loc="left")
    _style(axis)
    axis.grid(False)

    axis = axes[1, 0]
    dense = np.geomspace(separations_m[0], separations_m[-1], 120)
    axis.loglog(
        dense,
        _von_karman_structure_function_rad2(dense, profile.r0_m, profile.outer_scale_m),
        color=INK_SECONDARY, linewidth=2.0, label="von Karman theory",
    )
    axis.loglog(
        separations_m, measured, linestyle="none", marker="o", markersize=6,
        color=SERIES[0], markeredgecolor=SURFACE, markeredgewidth=1.5,
        label=f"ESO screens, {N_SCREENS} realizations",
    )
    axis.set_xlabel("Separation r [m]")
    axis.set_ylabel("D$_\\phi$(r) [rad$^2$ at 500 nm]")
    axis.set_title("Phase structure function", fontsize=10, loc="left")
    axis.legend(frameon=False, fontsize=8, labelcolor=INK)
    _style(axis)

    axis = axes[1, 1]
    for color, (name, version, label) in zip(SERIES, PROFILES):
        rows = runs[runs["atmosphere"] == label].groupby("frame")
        time_ms = rows["time_s"].first() * 1e3
        axis.plot(
            time_ms, rows["open_loop_rms_nm"].mean(), color=color,
            linewidth=1.2, linestyle=(0, (4, 3)), label=f"{label}, open loop",
        )
        axis.plot(
            time_ms, rows["residual_rms_nm"].mean(), color=color,
            linewidth=2.0, label=f"{label}, closed loop",
        )
    axis.set_xlabel("Time [ms]")
    axis.set_ylabel("Pupil OPD RMS [nm]")
    axis.set_ylim(bottom=0.0)
    axis.set_title(
        f"7x7 SH-WFS SCAO loop, mean of {N_REALIZATIONS} realizations",
        fontsize=10, loc="left",
    )
    axis.legend(frameon=False, fontsize=7.5, labelcolor=INK, loc="lower left", ncol=1)
    _style(axis)

    figure_path = output_dir / "eso_elt_turbulence_demo.png"
    figure.savefig(figure_path, dpi=150, facecolor=SURFACE, bbox_inches="tight")
    plt.close(figure)
    print(f"Wrote {_display_path(figure_path)}")


if __name__ == "__main__":
    main()
