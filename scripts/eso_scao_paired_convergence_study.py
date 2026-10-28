"""Paired spatial-sampling convergence of the ESO-derived SCAO tiers (roadmap S3).

Extends the smoke-tier study (``scripts/eso_scao_convergence_study.py``, which
could not resolve its 2 % criterion because its screens were unpaired and its
SH field of view changed with the sampling) to the ``medium`` (12 m) and
``full`` (42 m) tiers.  Three one-parameter scans start from the tier's
baseline (12 pupil samples per lenslet; WFS pad 2 with the 23-pixel window;
science pad 2) and change one sampling at a time:

* pupil samples per lenslet ``s`` = 12, 16 (and 20 at 12 m).  The WFS keeps
  pad 2 and the 23-pixel window, so its pixel scale and its field of view
  (11.5 lambda/d) stay fixed;
* WFS detector sampling: pad 2, 3, 4 with windows 23, 35, 47 pixels, the
  pixels symmetric about the optical-axis pixel; the field of view stays
  11.5-11.75 lambda/d;
* science image sampling: ``science.psf_pad_factor`` 2, 3, 4.

**Paired atmospheric inputs.**  The layered atmosphere draws each layer's
band coefficients in array order on its own screen grid, so two pupil
samplings would see unrelated screens.  For the duration of a study process
this script replaces that one draw: every setting of a scale draws on the
finest screen grid of the scale (the same keyed generator, consuming the
same number of normals), and a coarser grid takes the coefficients at its own
spatial frequencies.  The screen period (two diameters), and so the frequency
spacing, is the same for every setting, so a coarser screen is the
band-limited version of the finest one, and the subharmonic draws that follow
see the same generator state.  The WFS and science scans keep the grid and
share the same paired draws.  The statistics of each setting are unchanged:
every coefficient is still an independent complex normal scaled by that
grid's own band power.

**Runs.**  Realizations 0, 1, 2 per setting, noiseless; 200 frames with a
50-frame burn-in (the 42 m loop settles within 20 frames); long-exposure
2.2 um peak Strehl and EE50 over the frames after burn-in.  Each run is its
own process, so the recorded ``ru_maxrss`` is that run's peak; a finished run
is never repeated (rerunning the command resumes).

**Criterion, declared before the runs.**  For each scan, the realization-mean
peak Strehl and EE50 of the two finest settings agree within 2 % (relative).
The paired per-realization differences and their standard errors are
reported beside it.  A failure is reported as found; nothing is re-tuned.

    PYTHONPATH=<tree>/src python scripts/eso_scao_paired_convergence_study.py \\
        --scale medium --output-dir outputs/s3_medium

``--scale ci`` runs a reduced self-check (one realization, 40 frames) of the
machinery on the 5 m smoke tier.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import sys
import time

import numpy as np


TOLERANCE = 0.02
WAVELENGTH_M = 2.2e-6
LENSLETS = {"ci": 10, "medium": 24, "full": 84}
TIER = {"ci": "ci", "medium": "medium", "full": "full"}
PUPIL_SAMPLES = {"ci": (12, 16), "medium": (12, 16, 20), "full": (12, 16)}
WFS_PADS = {"ci": (2, 3), "medium": (2, 3, 4), "full": (2, 3, 4)}
SCIENCE_PADS = {"ci": (2, 3), "medium": (2, 3, 4), "full": (2, 3, 4)}
FRAMES = {"ci": 40, "medium": 200, "full": 200}
BURN_IN = {"ci": 10, "medium": 50, "full": 50}
REALIZATIONS = {"ci": (0,), "medium": (0, 1, 2), "full": (0, 1, 2)}
# Regenerate the bands on the finest 42 m grid only, to keep its peak memory
# near the 12-sample run's; the storage mode is identity-neutral.
REGENERATE = {("full", 16)}


def _settings(scale: str) -> dict[str, list[tuple[str, int, int, int]]]:
    """Scan name -> [(label, samples per lenslet, wfs pad, science pad)]."""

    return {
        "pupil_samples_per_lenslet": [(f"s{s}", s, 2, 2) for s in PUPIL_SAMPLES[scale]],
        "wfs_pad_factor": [(f"wfs_pad{p}", 12, p, 2) for p in WFS_PADS[scale]],
        "science_psf_pad_factor": [(f"science_pad{p}", 12, 2, p) for p in SCIENCE_PADS[scale]],
    }


def _config(scale: str, samples: int, wfs_pad: int, science_pad: int):
    from shwfs_ao.experiments.eso_scao_benchmark import tier_config

    base = tier_config(TIER[scale])
    return replace(
        base,
        pupil_pixels=LENSLETS[scale] * samples,
        science_wavelengths_m=(WAVELENGTH_M,),
        # The window is the pad * 12 - 1 pixels symmetric about the
        # optical-axis pixel: 23, 35, 47 at pad 2, 3, 4, whatever ``samples``.
        wfs=replace(base.wfs, pad_factor=wfs_pad, detector_window_px=12 * wfs_pad - 1),
        science=replace(base.science, psf_pad_factor=science_pad),
        controller=replace(base.controller, n_steps=FRAMES[scale]),
    )


def _install_paired_band_draw(reference_size: int) -> None:
    """Make every layered screen a sub-band of one draw on ``reference_size``."""

    from shwfs_ao.backends.native import layered_atmosphere

    def paired_band_draw(self, rng: np.random.Generator, amplitude: float) -> np.ndarray:
        size = self._config.screen_size
        if size > reference_size:
            raise ValueError(f"screen size {size} exceeds the paired reference {reference_size}")
        draws = rng.normal(size=(reference_size, reference_size)) + 1j * rng.normal(
            size=(reference_size, reference_size)
        )
        if size != reference_size:
            index = np.rint(np.fft.fftfreq(size) * size).astype(int) % reference_size
            draws = draws[np.ix_(index, index)]
        # As the library's draw: numpy's inverse FFT divides by size**2.
        return draws * (np.sqrt(self._band_power_rad2) * amplitude * size**2)

    layered_atmosphere.LayeredFrozenFlowAtmosphere._band_draw = paired_band_draw


def _reference_screen_size(scale: str) -> int:
    # The layered screen is two pupils across (screen_size = 2 * pupil_pixels;
    # every run checks this), so the finest pupil sampling sets the reference.
    return 2 * LENSLETS[scale] * max(PUPIL_SAMPLES[scale])


def _run_child(scale: str, label: str, samples: int, wfs_pad: int, science_pad: int, realization: int) -> dict:
    from shwfs_ao.experiments.scao import ScaoExecutionOptions, build_scao_system, run_closed_loop
    from shwfs_ao.science.long_exposure import LongExposureConfig, StreamingLongExposure

    reference = _reference_screen_size(scale)
    _install_paired_band_draw(reference)
    config = _config(scale, samples, wfs_pad, science_pad)
    storage = "regenerate" if (scale, samples) in REGENERATE else "materialized"
    started = time.perf_counter()
    system = build_scao_system(config, execution=ScaoExecutionOptions(atmosphere_band_storage=storage))
    built = time.perf_counter()
    if system.atmosphere.config.screen_size != 2 * config.pupil_pixels:
        raise RuntimeError("unexpected layered screen size; the paired draw assumes 2 * pupil_pixels")
    burn_in = BURN_IN[scale]
    accumulator = StreamingLongExposure(
        system.science_propagator,
        LongExposureConfig(wavelengths_m=(WAVELENGTH_M,), burn_in_frames=burn_in),
        telescope_diameter_m=config.telescope_diameter_m,
    )
    history = run_closed_loop(config, system=system, realization_index=realization, observers=(accumulator,))
    finished = time.perf_counter()
    metrics = accumulator.result().images[0].metrics
    return {
        "label": label,
        "samples_per_lenslet": samples,
        "wfs_pad_factor": wfs_pad,
        "wfs_window_px": 12 * wfs_pad - 1,
        "science_psf_pad_factor": science_pad,
        "realization": realization,
        "config_hash": config.config_hash,
        "paired_reference_screen_size": reference,
        "screen_size": int(system.atmosphere.config.screen_size),
        "atmosphere_band_storage": storage,
        "peak_strehl": float(metrics.peak_strehl),
        "ee50_radius_rad": float(metrics.ee50_radius_rad),
        "residual_rms_nm": float(np.mean(history.pre_update_residual_opd_rms_m[burn_in:]) * 1e9),
        "open_loop_rms_nm": float(np.mean(history.open_loop_opd_rms_m[burn_in:]) * 1e9),
        "first_frame_open_loop_rms_nm": float(history.open_loop_opd_rms_m[0] * 1e9),
        "usable_fraction": float(np.mean(history.reconstruction_usable)),
        "max_saturation": float(np.max(history.saturation_fraction)),
        "rejected_solves": int(system.reconstructor.statistics["rejected"]),
        "build_s": built - started,
        "loop_s": finished - built,
        "ru_maxrss": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
    }


def _code_identity() -> dict[str, object]:
    import shwfs_ao

    package = Path(shwfs_ao.__file__).resolve().parents[1]
    tree = package.parent
    # Names only: a record must not carry the local checkout path.
    identity: dict[str, object] = {
        "package_directory": package.name,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    try:
        identity["git_head"] = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=tree, capture_output=True, text=True, check=True
        ).stdout.strip()
        diff = subprocess.run(
            ["git", "diff", "HEAD", "--", "src"], cwd=tree, capture_output=True, check=True
        ).stdout
        identity["source_changes_sha256"] = hashlib.sha256(diff).hexdigest()
    except (OSError, subprocess.CalledProcessError):
        identity["git_head"] = None
    return identity


def _mean_std(values: list[float]) -> tuple[float, float | None]:
    array = np.asarray(values, dtype=float)
    return float(array.mean()), (float(array.std(ddof=1)) if array.size > 1 else None)


def _summarize(scale: str, runs: dict[str, dict]) -> dict:
    scans = {}
    for scan, settings in _settings(scale).items():
        entries = []
        for label, samples, wfs_pad, science_pad in settings:
            rows = [runs[_run_key(samples, wfs_pad, science_pad, r)] for r in REALIZATIONS[scale]]
            entry = {"setting": label, "runs": len(rows)}
            for key in ("peak_strehl", "ee50_radius_rad", "residual_rms_nm", "open_loop_rms_nm"):
                entry[f"{key}_mean"], entry[f"{key}_std"] = _mean_std([row[key] for row in rows])
            entries.append((entry, rows))
        convergence = {}
        (finest, finest_rows), (second, second_rows) = entries[-1], entries[-2]
        for key in ("peak_strehl", "ee50_radius_rad"):
            change = abs(finest[f"{key}_mean"] - second[f"{key}_mean"]) / abs(finest[f"{key}_mean"])
            paired = [a[key] / b[key] - 1.0 for a, b in zip(second_rows, finest_rows)]
            mean, std = _mean_std(paired)
            convergence[key] = {
                "relative_change_finest_two": change,
                "paired_relative_difference_mean": mean,
                "paired_relative_difference_se": None if std is None else std / np.sqrt(len(paired)),
                "within_declared_tolerance": change <= TOLERANCE,
            }
        scans[scan] = {"entries": [entry for entry, _ in entries], "convergence": convergence}
    return scans


def _run_key(samples: int, wfs_pad: int, science_pad: int, realization: int) -> str:
    return f"s{samples}_wfs{wfs_pad}_sci{science_pad}_r{realization}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scale", choices=sorted(LENSLETS), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--child", nargs=6, metavar=("LABEL", "S", "WFS_PAD", "SCI_PAD", "R", "OUT"), help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    if arguments.child:
        label, samples, wfs_pad, science_pad, realization, out = arguments.child
        row = _run_child(arguments.scale, label, int(samples), int(wfs_pad), int(science_pad), int(realization))
        Path(out).write_text(json.dumps(row, indent=1) + "\n")
        return 0
    scale, directory = arguments.scale, arguments.output_dir
    (directory / "runs").mkdir(parents=True, exist_ok=True)
    unique: dict[str, tuple[str, int, int, int, int]] = {}
    for settings in _settings(scale).values():
        for label, samples, wfs_pad, science_pad in settings:
            for realization in REALIZATIONS[scale]:
                unique.setdefault(
                    _run_key(samples, wfs_pad, science_pad, realization),
                    (label, samples, wfs_pad, science_pad, realization),
                )
    runs: dict[str, dict] = {}
    for key, (label, samples, wfs_pad, science_pad, realization) in unique.items():
        path = directory / "runs" / f"{key}.json"
        if not path.exists():
            print(f"{time.strftime('%H:%M:%S')} run {key}", flush=True)
            subprocess.run(
                [sys.executable, __file__, "--scale", scale, "--output-dir", str(directory),
                 "--child", label, str(samples), str(wfs_pad), str(science_pad), str(realization), str(path)],
                check=True,
            )
        runs[key] = json.loads(path.read_text())
        row = runs[key]
        print(
            f"  {key}: Strehl {row['peak_strehl']:.4f}  EE50 {row['ee50_radius_rad']:.4e} rad  "
            f"residual {row['residual_rms_nm']:.1f} nm  open loop {row['open_loop_rms_nm']:.1f} nm  "
            f"wall {row['build_s'] + row['loop_s']:.0f} s  peak {row['ru_maxrss'] / 2**30:.2f} GiB",
            flush=True,
        )
    record = {
        "schema": "shwfs_ao.eso_scao_paired_convergence_study.v1",
        "scale": scale,
        "tier": TIER[scale],
        "declared_tolerance": TOLERANCE,
        "frames": FRAMES[scale],
        "burn_in": BURN_IN[scale],
        "realizations": list(REALIZATIONS[scale]),
        "wavelength_m": WAVELENGTH_M,
        "paired_reference_screen_size": _reference_screen_size(scale),
        "code_identity": _code_identity(),
        "runs": runs,
        "scans": _summarize(scale, runs),
    }
    (directory / f"paired_convergence_{scale}.json").write_text(json.dumps(record, indent=1) + "\n")
    print(json.dumps({scan: data["convergence"] for scan, data in record["scans"].items()}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
