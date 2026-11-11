"""Off-axis science demonstration: one closed loop, several science offsets.

Runs one closed-loop trajectory of a layered single-NGS profile (default
``robo_ao2_22m_ngs_draft@2``, the Robo-AO-2 2.2 m draft) with the guide star
on axis, and evaluates target-centred long-exposure PSFs and Strehl ratios
at several science offsets from the same trajectory (default 0, 5, 10 and
20 arcsec along +x at 1.65 um).  Every offset uses the same frames, burn-in,
pupil, wavelength and image sampling.

Outputs (``--output``, default ``$AO_DEMO_OUTPUT_DIR/off_axis_science`` or
``./off_axis_science_output/off_axis_science``):

``psf_comparison.png``
    Target-centred long-exposure PSFs on common angular axes and one common
    logarithmic intensity scale (fraction of the ideal peak).
``strehl_vs_separation.png``
    Long-exposure peak Strehl against separation (and, separately labelled,
    the mean instantaneous Strehl with its block scatter).
``off_axis_strehl.csv`` and ``off_axis_science.json``
    Machine-readable rows: signed offsets, radial separation, wavelength,
    averaged frame count, long-exposure Strehl, and the complete result
    record with the frame selection, identities and footprint report.
``run_record.json``
    The exact reproduction command, profile version, seed, realization
    identifier, frame selection and environment.
``psfs.npz``
    The accumulated images, the ideal image and the angular axes.
``history.npz``
    The closed-loop history arrays of the guide-star loop (for bitwise
    comparison with a run without science directions).

Example (the 2.2 m demonstration; 6 to 25 minutes on two threads, depending
on the machine)::

    python examples/run_off_axis_science_demo.py --profile robo_ao2_22m_ngs_draft \\
        --version 2 --offsets "0,0;5,0;10,0;20,0" --wavelength-um 1.65 \\
        --burn-in 150 --block-frames 75 --output outputs/off_axis_science/22m

A quick check on the small layered 2 m profile::

    python examples/run_off_axis_science_demo.py --profile eso_turbulence_2m_detector \\
        --version 1 --offsets "0,0;10,0" --burn-in 30
"""

from __future__ import annotations

import os
import sys

for _name in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
):
    _value = os.environ.get(_name, "")
    if not (_value.isdigit() and 0 < int(_value) <= 2):
        os.environ[_name] = "2"
os.environ.setdefault("MPLBACKEND", "Agg")

import argparse  # noqa: E402
import csv  # noqa: E402
from dataclasses import replace  # noqa: E402
import importlib.metadata  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402
import platform  # noqa: E402
import shlex  # noqa: E402
import time  # noqa: E402

import numpy as np  # noqa: E402


def _parse_offsets(text: str) -> list[tuple[float, float]]:
    offsets = []
    for item in text.split(";"):
        item = item.strip()
        if not item:
            continue
        parts = [float(value) for value in item.split(",")]
        if len(parts) != 2:
            raise argparse.ArgumentTypeError(
                f"offset {item!r} must be 'x_arcsec,y_arcsec'."
            )
        offsets.append((parts[0], parts[1]))
    if not offsets:
        raise argparse.ArgumentTypeError("at least one offset is needed.")
    return offsets


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _plot(run, output: Path, wavelength_m: float, crop_arcsec: float) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm

    from shwfs_ao.science import discrete_flux_to_angular_surface_brightness

    arcsec = 180.0 * 3600.0 / np.pi
    images = [run.science.image(offset, wavelength_m) for offset in run.offsets]
    refined = all(image.interpolated_peak_strehl is not None for image in images)
    peak_method = "interpolated" if refined else "sampled"
    peaks = [image.interpolated_peak_strehl if refined else image.peak_strehl for image in images]
    ideal_peak = float(np.max(discrete_flux_to_angular_surface_brightness(images[0].ideal_psf)))
    x = images[0].psf.x_angle_rad * arcsec
    y = images[0].psf.y_angle_rad * arcsec
    keep_x = np.abs(x) <= crop_arcsec
    keep_y = np.abs(y) <= crop_arcsec
    ncols = min(2, len(images))
    nrows = (len(images) + ncols - 1) // ncols
    fig, axes = plt.subplots(
        nrows, ncols, figsize=(3.25 * ncols + 1.3, 3.25 * nrows + 0.7),
        sharex=True, sharey=True, squeeze=False, layout="constrained", facecolor="white",
    )
    norm = LogNorm(vmin=1e-4, vmax=1.0)
    extent = [x[keep_x][0], x[keep_x][-1], y[keep_y][0], y[keep_y][-1]]
    for axis, image, peak in zip(axes.flat, images, peaks):
        brightness = discrete_flux_to_angular_surface_brightness(image.psf) / ideal_peak
        panel = brightness[np.ix_(keep_y, keep_x)]
        mesh = axis.imshow(
            np.clip(panel, 1e-4, None), origin="lower", extent=extent, norm=norm, cmap="magma"
        )
        axis.set_title(
            f"{image.offset.label}\n{peak_method.capitalize()} peak Strehl = {peak:.3f}",
            fontsize=10,
        )
    for axis in axes.flat[len(images):]:
        axis.set_visible(False)
    fig.supxlabel("x from target (arcsec)")
    fig.supylabel("y from target (arcsec)")
    fig.colorbar(mesh, ax=axes, label="Surface brightness / ideal peak", shrink=0.85)
    fig.suptitle(
        f"Long-exposure PSFs at {wavelength_m * 1e6:.2f} µm\n"
        f"{run.record['profile']} · frames {run.science.selection.first_frame}–{run.science.selection.last_frame}",
        fontsize=12,
    )
    fig.savefig(output / "psf_comparison.png", dpi=150, facecolor="white", transparent=False)
    plt.close(fig)

    separations = [image.offset.radial_arcsec for image in images]
    fig, axis = plt.subplots(figsize=(5.0, 3.6))
    axis.plot(separations, peaks, "o-", label=f"long exposure ({peak_method} peak)")
    if refined:
        axis.plot(separations, [i.peak_strehl for i in images], ".:", label="long exposure (sampled peak)")
    instantaneous = [i.mean_instantaneous_strehl for i in images]
    if all(value is not None for value in instantaneous):
        blocks = [i.block_peak_strehl for i in images]
        errors = [
            float(np.std(b, ddof=1)) if b is not None and b.size > 1 else 0.0 for b in blocks
        ]
        axis.errorbar(
            separations,
            instantaneous,
            yerr=errors,
            fmt="s--",
            capsize=3,
            label="mean instantaneous sampled peak (block SD)",
        )
    axis.set_xlabel("separation from the guide star (arcsec)")
    axis.set_ylabel(f"Strehl at {wavelength_m * 1e6:.2f} um")
    axis.set_ylim(0.0, 1.0)
    axis.grid(True, alpha=0.3)
    axis.legend(fontsize=8)
    axis.set_title(f"{run.record['profile']}, one realization", fontsize=9)
    fig.savefig(output / "strehl_vs_separation.png", dpi=130, bbox_inches="tight")
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", default="robo_ao2_22m_ngs_draft")
    parser.add_argument("--version", type=int, default=2)
    parser.add_argument("--offsets", type=_parse_offsets, default=_parse_offsets("0,0;5,0;10,0;20,0"),
                        help="semicolon-separated 'x_arcsec,y_arcsec' pairs relative to the guide star")
    parser.add_argument("--wavelength-um", type=float, default=1.65)
    parser.add_argument("--burn-in", type=int, default=150, help="first averaged frame index")
    parser.add_argument("--n-steps", type=int, default=None, help="override the profile's frame count")
    parser.add_argument("--realization", type=int, default=0)
    parser.add_argument("--block-frames", type=int, default=75)
    parser.add_argument("--crop-arcsec", type=float, default=1.0)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    from shwfs_ao.experiments import run_off_axis_science
    from shwfs_ao.io.configs import load_system_profile

    output = args.output or Path(os.environ.get("AO_DEMO_OUTPUT_DIR", "off_axis_science_output")) / "off_axis_science"
    output.mkdir(parents=True, exist_ok=True)
    config = load_system_profile(args.profile, args.version)
    if args.n_steps is not None:
        config = replace(config, controller=replace(config.controller, n_steps=args.n_steps))
    wavelength = args.wavelength_um * 1e-6
    # Record the script as it was invoked (a repository-relative path when run
    # from the repository root), not its absolute location on this machine.
    script = Path(sys.argv[0]).as_posix() if argv is None else Path(__file__).name
    command = "python " + " ".join(shlex.quote(part) for part in [script, *(argv if argv is not None else sys.argv[1:])])
    started = time.perf_counter()
    run = run_off_axis_science(
        config,
        offsets_arcsec=args.offsets,
        wavelengths_m=(wavelength,),
        burn_in_frames=args.burn_in,
        realization_index=args.realization,
        block_frames=args.block_frames,
    )
    elapsed = time.perf_counter() - started

    rows = run.science.table_rows()
    with (output / "off_axis_strehl.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (output / "off_axis_science.json").write_text(
        json.dumps(_jsonable({"result": run.science.to_record(), "footprint": run.footprint}), indent=2) + "\n"
    )
    record = {
        **run.record,
        "command": command,
        "elapsed_s": elapsed,
        "usable_reconstruction_fraction": float(np.mean(run.history.reconstruction_usable)),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "versions": {p: importlib.metadata.version(p) for p in ("numpy", "scipy", "matplotlib")},
        },
    }
    (output / "run_record.json").write_text(json.dumps(_jsonable(record), indent=2) + "\n")
    images = [run.science.image(offset, wavelength) for offset in run.offsets]
    np.savez(
        output / "psfs.npz",
        x_angle_rad=images[0].psf.x_angle_rad,
        y_angle_rad=images[0].psf.y_angle_rad,
        ideal=images[0].ideal_psf.intensity,
        offsets_arcsec=np.array([(o.x_arcsec, o.y_arcsec) for o in run.offsets]),
        **{f"psf_{index}": image.psf.intensity for index, image in enumerate(images)},
        **{f"instantaneous_strehl_{index}": image.instantaneous_strehl for index, image in enumerate(images) if image.instantaneous_strehl is not None},
    )
    np.savez(
        output / "history.npz",
        **{
            name: np.asarray(getattr(run.history, name))
            for name in (
                "time_s",
                "open_loop_opd_rms_m",
                "pre_update_residual_opd_rms_m",
                "post_update_residual_opd_rms_m",
                "requested_command_history_opd_m",
                "applied_command_history_opd_m",
                "saturation_fraction",
                "valid_measurement_fraction",
                "reconstruction_usable",
                "measurement_row_masks",
            )
        },
    )
    _plot(run, output, wavelength, args.crop_arcsec)
    for row in rows:
        estimate = row["long_exposure_interpolated_peak_strehl"]
        refined_peak = "unavailable" if estimate is None else f"{estimate:.4f}"
        print(
            f"({row['x_arcsec']:+g}, {row['y_arcsec']:+g}) arcsec  r={row['radial_arcsec']:.2f}  "
            f"frames={row['averaged_frames']}  S_LE(interpolated)={refined_peak}  S_LE(sampled)={row['long_exposure_peak_strehl']:.4f}  "
            f"<S_inst(sampled)>={row['mean_instantaneous_peak_strehl']:.4f}"
        )
    print(f"wrote {output} in {elapsed:.1f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
