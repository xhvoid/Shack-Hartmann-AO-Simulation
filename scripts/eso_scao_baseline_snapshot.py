"""Record a bounded compatibility baseline for the ESO SCAO work (ESO-00).

The snapshot pins what later tickets must not move: published profile and
component identities, closed-loop telemetry of the two 2 m detector profiles
the ESO work touches most (``portfolio_2m_detector@4`` and
``eso_turbulence_2m_detector@1``), and the science propagator's output for a
zero and a turbulent OPD.  Every array is recorded by SHA-256 of its float64
little-endian bytes, so a later run can be compared exactly.

Run it under the desktop supervisor, for example::

    python -m shwfs_ao.runtime.resource_guard --label baseline-snapshot \\
        --estimate-mib 300 --largest-buffer-mib 8 --timeout-s 120 \\
        --log /tmp/snapshot.log -- python scripts/eso_scao_baseline_snapshot.py \\
        --output /tmp/snapshot.json

The run is small (72-pixel pupils, 150 frames) and allocates a few tens of MiB.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

import numpy as np

from shwfs_ao.experiments.scao import build_scao_system, run_closed_loop
from shwfs_ao.io.configs import available_system_profiles, load_system_profile
from shwfs_ao.science.metrics import peak_strehl_from_discrete_flux


_PROFILES = (("portfolio_2m_detector", 4), ("eso_turbulence_2m_detector", 1))
_HISTORY_ARRAYS = (
    "time_s",
    "open_loop_opd_rms_m",
    "pre_update_residual_opd_rms_m",
    "post_update_residual_opd_rms_m",
    "command_norm_m",
    "delta_command_norm_m",
    "released_delta_norm_m",
    "requested_command_history_opd_m",
    "applied_command_history_opd_m",
    "saturation_fraction",
    "valid_measurement_fraction",
    "valid_subaperture_fraction",
    "reconstruction_usable",
    "measurement_row_masks",
)


def _array_sha256(values: np.ndarray) -> str:
    array = np.asarray(values)
    if array.dtype == bool:
        payload = array.astype(np.uint8).tobytes(order="C")
    else:
        payload = np.ascontiguousarray(array, dtype="<f8").tobytes(order="C")
    header = f"{array.dtype.str}:{array.shape}".encode()
    return hashlib.sha256(header + b"\0" + payload).hexdigest()


def _git(*arguments: str) -> str | None:
    try:
        return subprocess.run(
            ["git", *arguments],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _profile_record(name: str, version: int) -> dict[str, object]:
    config = load_system_profile(name, version)
    started = time.perf_counter()
    system = build_scao_system(config)
    build_s = time.perf_counter() - started
    started = time.perf_counter()
    history = run_closed_loop(config, system=system)
    run_s = time.perf_counter() - started

    # Science behavior: the zero-OPD ideal and the realization's t=0 OPD.
    system.atmosphere.reset(realization_index=0)
    turbulent = np.asarray(system.atmosphere.opd_at(0.0), dtype=float)
    zero = np.where(np.isfinite(turbulent), 0.0, np.nan)
    psf_records = {}
    for wavelength in config.science_wavelengths_m:
        ideal = system.science_propagator.psf_from_opd(zero, wavelength)
        science = system.science_propagator.psf_from_opd(turbulent, wavelength)
        psf_records[f"{wavelength:.3e}"] = {
            "ideal_intensity_sha256": _array_sha256(ideal.intensity),
            "turbulent_intensity_sha256": _array_sha256(science.intensity),
            "x_angle_rad_sha256": _array_sha256(science.x_angle_rad),
            "turbulent_peak_strehl": peak_strehl_from_discrete_flux(science, ideal),
            "shape": list(science.intensity.shape),
        }
    return {
        "profile": f"{name}@{version}",
        "config_hash": config.config_hash,
        "observing_conditions_hash": config.observing_conditions_hash,
        "profile_component_config_hashes": dict(config.component_config_hashes),
        "system_component_hashes": dict(system.component_hashes),
        "loop_history_config_hash": history.config_hash,
        "history_array_sha256": {
            name: _array_sha256(getattr(history, name)) for name in _HISTORY_ARRAYS
        },
        "final_post_update_residual_rms_m": float(
            history.post_update_residual_opd_rms_m[-1]
        ),
        "mean_open_loop_rms_m": float(np.mean(history.open_loop_opd_rms_m)),
        "reconstruction_usable_fraction": float(
            np.mean(history.reconstruction_usable)
        ),
        "science": psf_records,
        "timing_s": {"build": build_s, "run": run_s, "n_steps": history.n_steps},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    record: dict[str, object] = {
        "schema": "shwfs_ao.eso_scao_baseline_snapshot.v1",
        "git_head": _git("rev-parse", "HEAD"),
        "git_status_porcelain": _git("status", "--porcelain=v1"),
        "python": sys.version,
        "platform": platform.platform(),
        "numpy": np.__version__,
        "thread_environment": {
            name: os.environ.get(name)
            for name in (
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "MKL_NUM_THREADS",
                "VECLIB_MAXIMUM_THREADS",
                "NUMEXPR_NUM_THREADS",
            )
        },
        "published_profile_config_hashes": {
            f"{name}@{version}": load_system_profile(name, version).config_hash
            for name, version in available_system_profiles()
        },
        "profiles": [_profile_record(name, version) for name, version in _PROFILES],
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(f"wrote {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
