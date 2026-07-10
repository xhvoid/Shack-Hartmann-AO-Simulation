"""Generate public-data overview figures for the detector-level AO extension."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from atmosphere_profiles import atmosphere_config_from_eso_asm_snapshot
from data_sources import load_eso_asm_snapshot, load_svo_filter_curve


PUBLIC = ROOT / "data" / "public"
GENERATED = ROOT / "figures" / "detector_level_SCAO"

SVO_FILTER_PATHS = {
    "J": PUBLIC / "svo_2mass_j_direct.csv",
    "H": PUBLIC / "svo_2mass_h_direct.csv",
    "Ks": PUBLIC / "svo_2mass_ks_direct.csv",
}
TWOMASS_PATH = PUBLIC / "target_photometry_2mass_psc_demo_ngs_bright.csv"
PANSTARRS_PATH = PUBLIC / "target_photometry_panstarrs_dr2_demo_ngs_bright.csv"
ESO_ASM_SNAPSHOT_PATH = PUBLIC / "eso_asm_paranal_20240729_0300_0800_snapshot.json"
ESO_ASM_TIMESERIES_PATH = PUBLIC / "eso_asm_paranal_20240729_0300_0800_timeseries.csv"
ESO_ASM_UTC_START = "2024-07-29T03:00:00Z"
ESO_ASM_UTC_END = "2024-07-29T08:00:00Z"

PANSTARRS_BANDS_UM = {
    "panstarrs_g_mag": 0.481,
    "panstarrs_r_mag": 0.617,
    "panstarrs_i_mag": 0.752,
    "panstarrs_z_mag": 0.866,
    "panstarrs_y_mag": 0.962,
}
TWOMASS_BANDS_UM = {
    "twomass_j_mag": 1.235,
    "twomass_h_mag": 1.662,
    "twomass_ks_mag": 2.159,
}

# WFS photon-budget engineering assumptions are named here (not hidden as
# function-default magic numbers) and echoed into the photon-budget CSV so every
# catalog-derived photon estimate carries its explicit assumptions and source class.
WFS_PHOTON_MAGNITUDE_SYSTEM = "AB"  # Pan-STARRS optical magnitudes are ~AB
WFS_PHOTON_WAVELENGTH_M = 700.0e-9  # WFS reference wavelength [m]
WFS_PHOTON_BANDWIDTH_M = 150.0e-9  # assumed optical bandwidth [m]
WFS_PHOTON_TELESCOPE_DIAMETER_M = 2.0  # 2 m-class pupil [m]
WFS_PHOTON_THROUGHPUT = 0.25  # end-to-end throughput placeholder [dimensionless]
WFS_PHOTON_EXPOSURE_S = 1.0e-3  # per-frame exposure time [s]
WFS_PHOTON_N_SUBAPERTURES = 25  # lenslets sharing the guide-star flux [count]


def main() -> None:
    GENERATED.mkdir(parents=True, exist_ok=True)

    filter_curves = {name: load_svo_filter_curve(path) for name, path in SVO_FILTER_PATHS.items()}
    asm_snapshot = load_eso_asm_snapshot(ESO_ASM_SNAPSHOT_PATH)
    asm_config = atmosphere_config_from_eso_asm_snapshot(asm_snapshot, seed=24, wind_dir_deg=70.0)
    asm_rows = _read_commented_csv(ESO_ASM_TIMESERIES_PATH)
    ps1_rows = _read_commented_csv(PANSTARRS_PATH)
    tmass_rows = _read_commented_csv(TWOMASS_PATH)

    photon_rows = _build_photon_budget_rows(ps1_rows)
    _write_csv(GENERATED / "public_data_photon_budget.csv", photon_rows)
    _write_summary_csv(
        GENERATED / "public_data_summary.csv",
        filter_curves=filter_curves,
        asm_snapshot=asm_snapshot,
        asm_config=asm_config,
        photon_rows=photon_rows,
        ps1_rows=ps1_rows,
        tmass_rows=tmass_rows,
    )

    _plot_overview(filter_curves, asm_snapshot, asm_rows, ps1_rows, tmass_rows, photon_rows)
    _plot_filter_curves(filter_curves)
    _plot_photon_budget(photon_rows)

    print(f"Wrote {(GENERATED / 'public_data_overview.png').relative_to(ROOT)}")
    print(f"Wrote {(GENERATED / 'public_filter_curves_jhk.png').relative_to(ROOT)}")
    print(f"Wrote {(GENERATED / 'public_data_photon_budget.png').relative_to(ROOT)}")
    print(f"Wrote {(GENERATED / 'public_data_summary.csv').relative_to(ROOT)}")
    print(f"Wrote {(GENERATED / 'public_data_photon_budget.csv').relative_to(ROOT)}")


def _read_commented_csv(path: Path) -> list[dict[str, str]]:
    data_lines: list[str] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            data_lines.append(line)
    return list(csv.DictReader(data_lines))


def _build_photon_budget_rows(rows: list[dict[str, str]]) -> list[dict[str, float | str]]:
    out: list[dict[str, float | str]] = []
    for row in rows:
        bands = []
        mags = []
        for key, wavelength_um in PANSTARRS_BANDS_UM.items():
            value = row.get(key, "")
            if not value:
                continue
            bands.append(wavelength_um)
            mags.append(float(value))
        if len(bands) < 2:
            continue
        order = np.argsort(bands)
        wavelengths = np.asarray(bands, dtype=float)[order]
        magnitudes = np.asarray(mags, dtype=float)[order]
        if not (wavelengths.min() <= 0.70 <= wavelengths.max()):
            continue
        m_wfs = float(np.interp(0.70, wavelengths, magnitudes))
        photons = _ab_mag_to_photons_per_subap_frame(m_wfs)
        out.append(
            {
                "target_id": row["target_id"],
                "ra_deg": float(row["ra_deg"]),
                "dec_deg": float(row["dec_deg"]),
                "m_wfs_700nm_interp_mag": m_wfs,
                "photons_per_subap_frame_est": photons,
                "n_detections": int(float(row.get("panstarrs_n_detections", 0))),
                "magnitude_system": WFS_PHOTON_MAGNITUDE_SYSTEM,
                "wfs_wavelength_nm": WFS_PHOTON_WAVELENGTH_M * 1.0e9,
                "bandwidth_nm": WFS_PHOTON_BANDWIDTH_M * 1.0e9,
                "telescope_diameter_m": WFS_PHOTON_TELESCOPE_DIAMETER_M,
                "throughput": WFS_PHOTON_THROUGHPUT,
                "exposure_s": WFS_PHOTON_EXPOSURE_S,
                "n_subapertures": WFS_PHOTON_N_SUBAPERTURES,
                "source_class": "direct_public_data",
                "source_note": (
                    "MAST Pan-STARRS DR2 optical photometry converted to a WFS photon "
                    "budget with the explicit AB-magnitude assumptions recorded in the "
                    "magnitude_system/wfs_wavelength_nm/bandwidth_nm/telescope_diameter_m/"
                    "throughput/exposure_s/n_subapertures columns; these are engineering "
                    "estimates, not measured WFS photon telemetry."
                ),
            }
        )
    out.sort(key=lambda item: float(item["photons_per_subap_frame_est"]), reverse=True)
    return out


def _ab_mag_to_photons_per_subap_frame(
    magnitude_ab: float,
    wavelength_m: float = WFS_PHOTON_WAVELENGTH_M,
    bandwidth_m: float = WFS_PHOTON_BANDWIDTH_M,
    telescope_diameter_m: float = WFS_PHOTON_TELESCOPE_DIAMETER_M,
    throughput: float = WFS_PHOTON_THROUGHPUT,
    exposure_s: float = WFS_PHOTON_EXPOSURE_S,
    n_subapertures: int = WFS_PHOTON_N_SUBAPERTURES,
) -> float:
    speed_of_light = 299_792_458.0
    planck = 6.62607015e-34
    fnu_0 = 3631.0e-26
    fnu = fnu_0 * 10.0 ** (-0.4 * magnitude_ab)
    delta_nu = speed_of_light * bandwidth_m / wavelength_m**2
    photon_energy = planck * speed_of_light / wavelength_m
    area_m2 = np.pi * (telescope_diameter_m / 2.0) ** 2
    photons_total = fnu * delta_nu * area_m2 * throughput * exposure_s / photon_energy
    return float(photons_total / n_subapertures)


def _nearest_700nm_panstarrs_mag(row: dict[str, str]) -> float | None:
    """Return the available Pan-STARRS band magnitude nearest 700 nm.

    Most red field sources lack a g (and often r) detection, so colouring a
    field scatter by g would drop almost every source. Picking the available
    band whose effective wavelength is closest to the 700 nm WFS reference lets
    every detected source appear with a real (not interpolated) magnitude.
    """

    candidates = []
    for band_key, wavelength_um in PANSTARRS_BANDS_UM.items():
        value = row.get(band_key, "")
        if value:
            candidates.append((abs(wavelength_um - 0.70), float(value)))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]


def _plot_overview(
    filter_curves: dict[str, object],
    asm_snapshot,
    asm_rows: list[dict[str, str]],
    ps1_rows: list[dict[str, str]],
    tmass_rows: list[dict[str, str]],
    photon_rows: list[dict[str, float | str]],
) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(12.0, 8.0), constrained_layout=True)

    minutes = _minutes_from_unix_ms([float(row["unix_time_ms"]) for row in asm_rows])
    seeing = np.asarray([float(row["seeing_arcsec_500nm"]) for row in asm_rows])
    tau0_ms = np.asarray([1.0e3 * float(row["tau0_s"]) for row in asm_rows])
    ax = axes[0, 0]
    ax.plot(minutes, seeing, color="#1f77b4", linewidth=1.8, label="seeing")
    ax.set_xlabel("minutes from first sample")
    ax.set_ylabel("DIMM seeing [arcsec]", color="#1f77b4")
    ax.tick_params(axis="y", labelcolor="#1f77b4")
    ax.grid(alpha=0.25)
    ax2 = ax.twinx()
    ax2.plot(minutes, tau0_ms, color="#d62728", linewidth=1.5, label="tau0")
    ax2.set_ylabel("MASS tau0 [ms]", color="#d62728")
    ax2.tick_params(axis="y", labelcolor="#d62728")
    utc_start = ESO_ASM_UTC_START
    utc_end = ESO_ASM_UTC_END
    ax.set_title(f"ESO Paranal ASM nighttime, {utc_start[11:16]}-{utc_end[11:16]} UTC")

    ax = axes[0, 1]
    _draw_filter_curves(ax, filter_curves)
    ax.set_xlabel("wavelength [um]")
    ax.set_ylabel("transmission")
    ax.set_ylim(-0.03, 1.08)
    ax.grid(alpha=0.25)
    ax.set_title("SVO 2MASS J/H/Ks filter caches")
    ax.legend(loc="lower right", fontsize=8)

    ax = axes[1, 0]
    # Colour every detected Pan-STARRS source by the band nearest 700 nm so the
    # whole field shows. Colouring by g (or by the 700 nm-interpolated photon
    # anchor, which needs a band on each side of 700 nm) would leave only one or
    # two points, since most red field sources have no Pan-STARRS g/r detection.
    ps1_field = [
        (float(row["ra_deg"]), float(row["dec_deg"]), _nearest_700nm_panstarrs_mag(row))
        for row in ps1_rows
    ]
    ps1_field = [point for point in ps1_field if point[2] is not None]
    if ps1_field:
        sc = ax.scatter(
            [point[0] for point in ps1_field],
            [point[1] for point in ps1_field],
            c=[point[2] for point in ps1_field],
            cmap="viridis_r",
            s=45,
            edgecolor="black",
            linewidth=0.35,
            label=f"Pan-STARRS ({len(ps1_field)} sources)",
        )
        cbar = fig.colorbar(sc, ax=ax)
        cbar.set_label("Pan-STARRS mag (band nearest 700 nm)")
    ax.scatter(
        [float(row["ra_deg"]) for row in tmass_rows],
        [float(row["dec_deg"]) for row in tmass_rows],
        marker="s",
        facecolor="none",
        edgecolor="#e76f51",
        s=70,
        linewidth=1.2,
        label="2MASS PSC",
    )
    ax.invert_xaxis()
    ax.set_xlabel("RA [deg]")
    ax.set_ylabel("Dec [deg]")
    ax.set_title("Public catalog sources in the demo field")
    # The cone is ~0.01 deg wide, so thin and rotate the RA ticks to stop the
    # long-decimal labels from overlapping.
    ax.xaxis.set_major_locator(MaxNLocator(nbins=5))
    ax.tick_params(axis="x", labelrotation=30)
    for tick_label in ax.get_xticklabels():
        tick_label.set_horizontalalignment("right")
    ax.legend(loc="best", fontsize=8)
    ax.grid(alpha=0.2)

    ax = axes[1, 1]
    # Scatter every detected band magnitude across the whole field (one point per
    # source per band) instead of a single anchor source, then ring the 700 nm
    # photon-anchor source so it stays identifiable.
    _scatter_all_photometry(ax, ps1_rows, PANSTARRS_BANDS_UM, "#4361ee", "Pan-STARRS")
    _scatter_all_photometry(ax, tmass_rows, TWOMASS_BANDS_UM, "#f77f00", "2MASS")
    if photon_rows:
        anchor_id = str(photon_rows[0]["target_id"])
        anchor = next((row for row in ps1_rows if row["target_id"] == anchor_id), None)
        if anchor is not None:
            anchor_xs, anchor_ys = [], []
            for band_key, wavelength_um in PANSTARRS_BANDS_UM.items():
                value = anchor.get(band_key, "")
                if value:
                    anchor_xs.append(wavelength_um)
                    anchor_ys.append(float(value))
            ax.scatter(
                anchor_xs,
                anchor_ys,
                s=90,
                facecolor="none",
                edgecolor="black",
                linewidth=1.2,
                label="700 nm photon anchor",
            )
    ax.invert_yaxis()
    ax.set_xlabel("wavelength [um]")
    ax.set_ylabel("catalog magnitude")
    ax.set_title("Optical + NIR photometry across the field")
    ax.grid(alpha=0.25)
    ax.legend(loc="best", fontsize=8)

    fig.savefig(GENERATED / "public_data_overview.png", dpi=150, pil_kwargs={"optimize": True})
    plt.close(fig)


def _plot_filter_curves(filter_curves: dict[str, object]) -> None:
    fig, ax = plt.subplots(figsize=(7.8, 4.2), constrained_layout=True)
    _draw_filter_curves(ax, filter_curves)
    ax.set_xlabel("wavelength [um]")
    ax.set_ylabel("transmission")
    ax.set_ylim(-0.03, 1.08)
    ax.set_title("Direct SVO 2MASS J/H/Ks filter curves")
    ax.grid(alpha=0.25)
    ax.legend(loc="best")
    fig.savefig(GENERATED / "public_filter_curves_jhk.png", dpi=150, pil_kwargs={"optimize": True})
    plt.close(fig)


def _draw_filter_curves(ax, filter_curves: dict[str, object]) -> None:
    colors = {"J": "#6a4c93", "H": "#1982c4", "Ks": "#8ac926"}
    for name, curve in filter_curves.items():
        wavelength_um = np.asarray(curve.wavelength_m) * 1.0e6
        transmission = np.asarray(curve.transmission)
        eff_um = _effective_wavelength_um(curve)
        ax.plot(wavelength_um, transmission, color=colors[name], linewidth=1.8, label=f"{name} eff {eff_um:.3f} um")
        ax.axvline(eff_um, color=colors[name], linestyle="--", linewidth=0.9, alpha=0.75)


def _plot_photon_budget(rows: list[dict[str, float | str]]) -> None:
    top = rows[:8]
    fig, ax = plt.subplots(figsize=(8.2, 4.4))
    fig.subplots_adjust(bottom=0.24, top=0.86)
    labels = [str(row["target_id"]).replace("PS1_", "")[-6:] for row in top]
    values = [float(row["photons_per_subap_frame_est"]) for row in top]
    bars = ax.bar(labels, values, color="#457b9d")
    ax.set_yscale("log")
    ax.set_ylim(1.0e-3, max(values) * 3.0 if values else 1.0)
    ax.set_xlabel("Pan-STARRS source id suffix")
    ax.set_ylabel("estimated photons / subap / frame")
    ax.set_title("Catalog-driven 700 nm WFS photon-budget estimate")
    ax.grid(axis="y", alpha=0.25)
    for bar, value in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2.0,
            value * 1.15,
            f"{value:.2g}",
            ha="center",
            va="bottom",
            fontsize=8,
        )
    fig.text(
        0.02,
        0.04,
        "Assumptions: AB mag interpolation to 700 nm, 150 nm band, 2 m aperture, throughput 0.25, 1 ms, 25 subaps",
        va="bottom",
        fontsize=8,
    )
    fig.savefig(GENERATED / "public_data_photon_budget.png", dpi=150, pil_kwargs={"optimize": True})
    plt.close(fig)


def _plot_photometry_points(ax, row: dict[str, str], bands: dict[str, float], color: str, label: str) -> None:
    xs = []
    ys = []
    for key, wavelength_um in bands.items():
        value = row.get(key, "")
        if value:
            xs.append(wavelength_um)
            ys.append(float(value))
    ax.plot(xs, ys, marker="o", color=color, linewidth=1.6, label=label)


def _scatter_all_photometry(ax, rows, bands: dict[str, float], color: str, label: str) -> int:
    """Scatter every detected band magnitude across all sources (one point each).

    Returns the number of plotted points so the legend can report the catalog's
    photometric coverage across the field rather than a single anchor source.
    """

    xs = []
    ys = []
    for row in rows:
        for key, wavelength_um in bands.items():
            value = row.get(key, "")
            if value:
                xs.append(wavelength_um)
                ys.append(float(value))
    ax.scatter(xs, ys, marker="o", s=20, color=color, alpha=0.6, edgecolor="none", label=f"{label} ({len(xs)} pts)")
    return len(xs)


def _minutes_from_unix_ms(values_ms: list[float]) -> np.ndarray:
    first = values_ms[0]
    return (np.asarray(values_ms) - first) / 60_000.0


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _effective_wavelength_um(curve) -> float:
    transmission = np.asarray(curve.transmission)
    wavelength_um = np.asarray(curve.wavelength_m) * 1.0e6
    return float(np.trapezoid(wavelength_um * transmission, wavelength_um) / np.trapezoid(transmission, wavelength_um))


def _write_summary_csv(path: Path, *, filter_curves, asm_snapshot, asm_config, photon_rows, ps1_rows, tmass_rows) -> None:
    best_photon = photon_rows[0] if photon_rows else {}
    rows = [
        {
            "metric": "eso_asm_median_seeing",
            "value": asm_snapshot.measurements["seeing_arcsec_500nm"],
            "unit": "arcsec",
            "source_class": asm_snapshot.source_class,
            "source_note": asm_snapshot.provenance.source_note,
        },
        {
            "metric": "eso_asm_r0_500",
            "value": asm_config.r0_500_m,
            "unit": "m",
            "source_class": asm_config.source_class,
            "source_note": asm_config.source_note,
        },
        {
            "metric": "panstarrs_rows",
            "value": len(ps1_rows),
            "unit": "count",
            "source_class": "direct_public_data",
            "source_note": "MAST Pan-STARRS DR2 mean catalog cache.",
        },
        {
            "metric": "twomass_rows",
            "value": len(tmass_rows),
            "unit": "count",
            "source_class": "direct_public_data",
            "source_note": "IRSA 2MASS PSC cache.",
        },
        {
            "metric": "best_wfs_photon_budget_source",
            "value": best_photon.get("target_id", ""),
            "unit": "id",
            "source_class": "direct_public_data",
            "source_note": "Selected from Pan-STARRS DR2 optical photometry cache.",
        },
        {
            "metric": "best_wfs_photons_per_subap_frame_est",
            "value": best_photon.get("photons_per_subap_frame_est", ""),
            "unit": "photons/subap/frame",
            "source_class": "direct_public_data",
            "source_note": "Simple AB-magnitude engineering estimate, not measured WFS telemetry.",
        },
    ]
    band_rows = []
    for band_name, curve in filter_curves.items():
        band_rows.append(
            {
                "metric": f"svo_2mass_{band_name.lower()}_effective_wavelength",
                "value": _effective_wavelength_um(curve),
                "unit": "um",
                "source_class": curve.source_class,
                "source_note": curve.provenance.source_note,
            }
        )
    rows[2:2] = band_rows
    _write_csv(path, rows)


if __name__ == "__main__":
    main()
