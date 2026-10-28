"""ci tier with det_emccd_12m_medium_derived@3 detector physics: size of the review fixes.

Run once with PYTHONPATH at the reviewed code (663df16) and once at the fixed
code; the argument is the output JSON path.  Review 2026-10-16, R2/R3.
"""
import json
import sys

import numpy as np

from shwfs_ao.experiments.detector_level import derive_physical_config, science_run, with_magnitude
from shwfs_ao.experiments.scao import ScaoExecutionOptions, build_scao_system
from shwfs_ao.io.configs import load_system_profile

smoke = load_system_profile("eso_scao_smoke_5m_software", 2)
physics = load_system_profile("det_emccd_12m_medium_derived", 3)
config = derive_physical_config(smoke, physics, label="review_ci_r3_probe")
out = {}
system = build_scao_system(config)
matrix = np.asarray(system.interaction_matrix.matrix if hasattr(system.interaction_matrix, "matrix") else system.interaction_matrix.to_dense(), dtype=float)
out["im_frobenius"] = float(np.linalg.norm(matrix))
out["reference_centroids_mean_px"] = np.asarray(system.wfs.reference_centroids_px, dtype=float).mean(axis=0).tolist()
out["sky_e_per_pixel_max"] = float(np.max(system.wfs.sky_e_per_pixel))
out["window_px"] = int(system.wfs.layout.window_slice[0].stop - system.wfs.layout.window_slice[0].start)
execution = ScaoExecutionOptions(telemetry_level="summary")
for m in (8.0, 11.0):
    r = science_run(with_magnitude(config, m), root_seed=5, n_steps=150, burn_in_frames=50, execution=execution)
    out[f"m{m:g}"] = {k: r[k] for k in ("post_update_rms_m", "valid_measurement_fraction", "lost_lock")}
json.dump(out, open(sys.argv[1], "w"), indent=1)
print(json.dumps(out))
