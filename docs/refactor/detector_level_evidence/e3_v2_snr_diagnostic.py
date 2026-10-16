"""E3 (@2) diagnostic: per-lenslet total SNR against the model's supported floor.

For det_emccd_12m_medium_derived@2 at m_AB = 9..12 (root seed 21), evaluate the
detector_covariance_v1 prediction at a zero residual (diffraction-limited
spots) and at a 280 nm static residual (a typical closed-loop state), and report
the median and 10th percentile of SNR_T, the supported fraction, and the
fraction passing max_centroid_sigma_px = 0.5, also at the full open-loop
residual the loop must close from.  Run from the
checkout:
    python docs/refactor/detector_level_evidence/e3_v2_snr_diagnostic.py
"""

from dataclasses import replace

import numpy as np

from shwfs_ao.experiments.detector_level import with_magnitude
from shwfs_ao.experiments.scao import build_scao_system
from shwfs_ao.io.configs import RandomSeedConfig, load_system_profile

base = load_system_profile("det_emccd_12m_medium_derived", 2)
for magnitude in (9.0, 10.0, 11.0, 12.0):
    config = replace(with_magnitude(base, magnitude), random=RandomSeedConfig(root_seed=21))
    system = build_scao_system(config)
    wfs = system.wfs
    opd = np.asarray(system.atmosphere.opd_at(0.0), dtype=float)
    opd = np.where(np.isfinite(opd), opd, 0.0)
    for label, residual in (
        ("zero residual", np.zeros_like(opd)),
        ("280 nm residual", 0.2 * opd),
        ("open loop (1.25 um)", opd),
    ):
        quality = wfs.noise_model(residual)
        snr = quality.total_snr
        print(
            f"m={magnitude:g} {label}: detected e- per full subaperture "
            f"{float(np.max(wfs.detected_e_per_subap)):.0f}, SNR_T median {np.median(snr):.1f}, "
            f"10th percentile {np.percentile(snr, 10):.1f}, supported {np.mean(quality.supported):.3f}, "
            f"sigma median {np.median(quality.centroid_sigma_px[quality.supported]) if np.any(quality.supported) else float('nan'):.3f} px, "
            f"valid by sigma <= 0.5 px {np.mean(quality.centroid_sigma_px <= 0.5):.3f}"
        )
