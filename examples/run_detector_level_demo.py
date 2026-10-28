"""Run the synthetic 2 m EMCCD profile and save a JSON summary.

Set AO_DEMO_OUTPUT_DIR to choose the output directory.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
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

import numpy as np

from shwfs_ao.experiments.scao import build_scao_system, run_closed_loop
from shwfs_ao.io.configs import load_system_profile


def main() -> int:
    config = load_system_profile("det_emccd_2m_synthetic", 1)
    system = build_scao_system(config)
    history = run_closed_loop(config, system=system)
    half = history.n_steps // 2
    open_loop = float(np.mean(history.open_loop_opd_rms_m[half:]))
    corrected = float(np.mean(history.post_update_residual_opd_rms_m[half:]))
    valid = float(np.mean(history.valid_measurement_fraction[half:]))
    flat = np.zeros(system.wfs.geometry.pupil_shape)  # type: ignore[attr-defined]
    quality = system.wfs.noise_model(flat)  # type: ignore[attr-defined]
    summary = {
        "profile": "det_emccd_2m_synthetic@1",
        "config_hash": config.config_hash,
        "camera": "synthetic_emccd@1 (G = 300, CIC 0.005 e-/px/read, 60 e- output read noise)",
        "detected_e_per_full_subaperture": float(np.max(system.wfs.detected_e_per_subap)),  # type: ignore[attr-defined]
        "frames": int(history.n_steps),
        "open_loop_rms_nm_second_half": 1e9 * open_loop,
        "corrected_rms_nm_second_half": 1e9 * corrected,
        "valid_measurement_fraction_second_half": valid,
        "flat_wavefront_centroid_sigma_px_median": float(np.median(quality.centroid_sigma_px)),
        "flat_wavefront_calibration_sigma_px_median": float(np.median(quality.calibration_sigma_px)),
    }
    for key, value in summary.items():
        print(f"{key}: {value}")
    output_dir = Path(os.environ.get("AO_DEMO_OUTPUT_DIR", "detector_level_demo_output"))
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "detector_level_demo.json"
    path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
