"""Sampling and solver convergence of the ESO-derived SCAO smoke system (ESO-08).

Desktop-tractable study on the 5 m, 10x10 SH / 11x11 DM software-smoke system
(``eso_scao_smoke_5m_software@2``) under the packaged ESO ten-layer
atmosphere.  Two one-parameter scans, each with at least three settings and
three independent realizations:

* pupil samples per lenslet 8, 12, 16 (80, 120, 160 pupil samples; the SH
  focal sampling stays Nyquist, pad 2, with a window symmetric about the
  optical-axis pixel, 2s - 1 pixels);
* LSMR tolerance 1e-6, 1e-8, 1e-10 at 12 samples per lenslet.

Each run lasts 200 frames (0.4 s) with a 50-frame burn-in and reports the
settled long-exposure 2.2 um peak Strehl and EE50, plus the post-burn-in
residual RMS.  The convergence criterion was declared before the study ran:
the settled Strehl and EE50 of the two finest settings agree within 2 %
(relative), reported beside the realization scatter.  A failure is reported
as found, not re-tuned.

Run it under the desktop supervisor; it writes one JSON record.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import time

import numpy as np

from shwfs_ao.experiments.eso_scao_benchmark import tier_config
from shwfs_ao.experiments.scao import build_scao_system, run_closed_loop
from shwfs_ao.science.long_exposure import LongExposureConfig, StreamingLongExposure


TOLERANCE = 0.02
FRAMES = 200
BURN_IN = 50
REALIZATIONS = (0, 1, 2)
WAVELENGTH_M = 2.2e-6


def _config(samples_per_lenslet: int, tolerance: float):
    base = tier_config("ci")
    pupil = 10 * samples_per_lenslet
    return replace(
        base,
        pupil_pixels=pupil,
        science_wavelengths_m=(WAVELENGTH_M,),
        # Pad 2 gives a 2s-pixel canvas; the window is the 2s - 1 pixels
        # symmetric about the optical-axis pixel (the version-2 convention).
        wfs=replace(base.wfs, detector_window_px=2 * samples_per_lenslet - 1),
        controller=replace(base.controller, n_steps=FRAMES),
        scalable=replace(base.scalable, solver_atol=tolerance, solver_btol=tolerance),
    )


def _run(config, realization: int) -> dict[str, float]:
    system = build_scao_system(config)
    accumulator = StreamingLongExposure(
        system.science_propagator,
        LongExposureConfig(wavelengths_m=(WAVELENGTH_M,), burn_in_frames=BURN_IN),
        telescope_diameter_m=config.telescope_diameter_m,
    )
    started = time.perf_counter()
    history = run_closed_loop(
        config, system=system, realization_index=realization, observers=(accumulator,)
    )
    metrics = accumulator.result().images[0].metrics
    return {
        "peak_strehl": metrics.peak_strehl,
        "ee50_radius_rad": metrics.ee50_radius_rad,
        "residual_rms_nm": float(
            np.mean(history.pre_update_residual_opd_rms_m[BURN_IN:]) * 1e9
        ),
        "open_loop_rms_nm": float(np.mean(history.open_loop_opd_rms_m[BURN_IN:]) * 1e9),
        "usable_fraction": float(np.mean(history.reconstruction_usable)),
        "max_saturation": float(np.max(history.saturation_fraction)),
        "rejected_solves": int(system.reconstructor.statistics["rejected"]),
        "wall_s": time.perf_counter() - started,
    }


def _summary(rows: list[dict[str, float]]) -> dict[str, float]:
    result: dict[str, float] = {}
    for key in ("peak_strehl", "ee50_radius_rad", "residual_rms_nm"):
        values = np.asarray([row[key] for row in rows])
        result[f"{key}_mean"] = float(values.mean())
        result[f"{key}_std"] = float(values.std(ddof=1))
    return result


def _scan(label: str, settings: list[tuple[float, object]]) -> dict[str, object]:
    entries = []
    for value, config in settings:
        rows = [_run(config, realization) for realization in REALIZATIONS]
        entries.append(
            {"setting": value, "config_hash": config.config_hash, "runs": rows, **_summary(rows)}
        )
    finest, second = entries[-1], entries[-2]
    checks = {}
    for key in ("peak_strehl", "ee50_radius_rad"):
        change = abs(finest[f"{key}_mean"] - second[f"{key}_mean"]) / abs(finest[f"{key}_mean"])
        scatter = finest[f"{key}_std"] / abs(finest[f"{key}_mean"])
        checks[key] = {
            "relative_change_finest_two": change,
            "relative_realization_scatter": scatter,
            "within_declared_tolerance": change <= TOLERANCE,
        }
    return {"parameter": label, "entries": entries, "convergence": checks}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    record = {
        "schema": "shwfs_ao.eso_scao_convergence_study.v1",
        "declared_tolerance": TOLERANCE,
        "frames": FRAMES,
        "burn_in": BURN_IN,
        "realizations": list(REALIZATIONS),
        "wavelength_m": WAVELENGTH_M,
        "sampling": _scan(
            "pupil_samples_per_lenslet",
            [(samples, _config(samples, 1e-8)) for samples in (8, 12, 16)],
        ),
        "solver": _scan(
            "lsmr_tolerance",
            [(tolerance, _config(12, tolerance)) for tolerance in (1e-6, 1e-8, 1e-10)],
        ),
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({k: v["convergence"] for k, v in record.items() if isinstance(v, dict) and "convergence" in v}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
