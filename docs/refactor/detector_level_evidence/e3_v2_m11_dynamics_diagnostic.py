"""E3 (@2) diagnostic: why the m_AB = 11 loop loses lock.

Runs det_emccd_12m_medium_derived@2 at m_AB = 11 (root seed 21, 400 frames)
twice, with the profile's leak (0) and with leak 0.02, and reports the valid
fraction over time and the growth of the applied DM command for weakly and
well-sensed actuators (split at the median interaction-matrix column norm).
A diagnostic only: no profile is changed.  Run from the checkout:
    python docs/refactor/detector_level_evidence/e3_v2_m11_dynamics_diagnostic.py
"""

from dataclasses import replace

import numpy as np

from shwfs_ao.experiments.detector_level import with_magnitude
from shwfs_ao.experiments.scao import ScaoExecutionOptions, build_scao_system, run_closed_loop
from shwfs_ao.io.configs import RandomSeedConfig, load_system_profile

base = with_magnitude(load_system_profile("det_emccd_12m_medium_derived", 2), 11.0)
base = replace(base, random=RandomSeedConfig(root_seed=21), controller=replace(base.controller, n_steps=400))
for leak in (0.0, 0.02):
    config = replace(base, controller=replace(base.controller, leak=leak))
    system = build_scao_system(config, execution=ScaoExecutionOptions(telemetry_level="summary"))
    history = run_closed_loop(config, system=system)
    matrix = system.interaction_matrix
    import scipy.sparse as sp

    csr = sp.csr_matrix((matrix.data, matrix.indices, matrix.indptr), shape=(len(matrix.row_ids), len(matrix.coordinate_ids)))
    norms = np.sqrt(np.asarray(csr.multiply(csr).sum(axis=0)).ravel())
    weak = norms < np.median(norms)
    index = {identifier: i for i, identifier in enumerate(system.dm.actuator_ids)}
    columns = np.array([index[identifier] for identifier in matrix.coordinate_ids])
    applied = np.asarray(history.applied_command_history_opd_m)[:, columns]
    valid = np.asarray(history.valid_measurement_fraction)
    post = np.asarray(history.post_update_residual_opd_rms_m)
    print(f"leak={leak}: residual frames 100-399 {1e9 * post[100:].mean():.1f} nm")
    for start in (0, 20, 50, 100, 200, 300):
        stop = start + 20
        print(
            f"  frames {start:3d}-{stop:3d}: valid {valid[start:stop].mean():.3f}, "
            f"residual {1e9 * post[start:stop].mean():7.1f} nm, command rms weak "
            f"{1e9 * np.sqrt(np.mean(applied[start:stop][:, weak] ** 2)):7.1f} nm, well "
            f"{1e9 * np.sqrt(np.mean(applied[start:stop][:, ~weak] ** 2)):7.1f} nm"
        )
