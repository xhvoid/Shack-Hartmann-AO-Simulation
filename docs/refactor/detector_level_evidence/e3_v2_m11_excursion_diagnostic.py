"""E3 (@2) diagnostic: what triggers the m_AB = 11 excursions under the reset policy.

Runs det_emccd_12m_medium_derived@2 with the opt-in reset policy
(controller.recovery = {rejected_frames_before_decay: 2,
decay_per_rejected_frame: 1.0}) on the development root seeds 11 and 12 only:
at m_AB = 11 with the profile's damping (alpha = 0.001) and with alpha = 0.1,
and for seed 11 at m_AB = 8 and 10 with alpha = 0.001.  For each run it
reports the global-waffle coefficient of the applied command (the weakest
non-null singular mode of the interaction matrix), its per-frame drive and
effective restoring gain on locked frames, the resets, and, before each
reset, the waffle coefficient and the per-lenslet gate failures.  A
diagnostic only: no profile is changed.  Run from the checkout:
    python docs/refactor/detector_level_evidence/e3_v2_m11_excursion_diagnostic.py
"""

from dataclasses import replace

import numpy as np
import scipy.sparse as sp

from shwfs_ao.experiments.detector_level import with_magnitude
from shwfs_ao.experiments.scao import ScaoExecutionOptions, build_scao_system, run_closed_loop
from shwfs_ao.io.configs import RandomSeedConfig, RecoveryPolicyConfig, load_system_profile

RESET = RecoveryPolicyConfig(
    rejected_frames_before_decay=2,
    decay_per_rejected_frame=1.0,
    fallback_min_valid_fraction=None,
    fallback_min_actuator_coverage=None,
    gain_full_valid_fraction=None,
)
profile = load_system_profile("det_emccd_12m_medium_derived", 2)
runs = [(11, 11.0, 0.001), (12, 11.0, 0.001), (11, 11.0, 0.1), (12, 11.0, 0.1), (11, 10.0, 0.001), (11, 8.0, 0.001)]
spectrum_reported = False
for seed, magnitude, alpha in runs:
    config = with_magnitude(profile, magnitude)
    config = replace(
        config,
        random=RandomSeedConfig(root_seed=seed),
        reconstructor=replace(config.reconstructor, alpha=alpha),
        controller=replace(config.controller, n_steps=400, recovery=RESET),
    )
    system = build_scao_system(config, execution=ScaoExecutionOptions(telemetry_level="summary"))
    gates = []
    measure = system.wfs.measure

    def recording_measure(*args, _measure=measure, **kwargs):
        result = _measure(*args, **kwargs)
        telemetry = result.detector_telemetry
        gates.append(
            np.stack(
                [
                    ~np.asarray(telemetry.valid_by_clipping, dtype=bool),
                    ~np.asarray(telemetry.uncertainty_supported, dtype=bool),
                    ~np.asarray(telemetry.valid_by_flux, dtype=bool),
                    ~np.asarray(telemetry.valid_by_uncertainty, dtype=bool)
                    & np.asarray(telemetry.uncertainty_supported, dtype=bool),
                ]
            ).mean(axis=1)
        )
        return result

    system.wfs.measure = recording_measure
    history = run_closed_loop(config, system=system)
    matrix = system.interaction_matrix
    csr = sp.csr_matrix(
        (matrix.data, matrix.indices, matrix.indptr),
        shape=(len(matrix.row_ids), len(matrix.coordinate_ids)),
    )
    dense = csr.toarray()[np.asarray(matrix.row_valid, dtype=bool)]
    _, singular, vt = np.linalg.svd(dense, full_matrices=False)
    order = np.argsort(singular)
    waffle_mode = vt[order[1]]
    index = {identifier: i for i, identifier in enumerate(system.dm.actuator_ids)}
    columns = np.array([index[identifier] for identifier in matrix.coordinate_ids])
    if not spectrum_reported:
        rows_cols = np.array([[int(part[1:]) for part in identifier.split("-")[1:]] for identifier in matrix.coordinate_ids])
        checkerboard = (-1.0) ** rows_cols.sum(axis=1)
        checkerboard /= np.linalg.norm(checkerboard)
        norms = np.sqrt((dense**2).sum(axis=0))
        rms = float(np.sqrt(np.mean(norms**2)))
        print(
            f"interaction matrix: {dense.shape[0]} valid rows x {dense.shape[1]} actuators, "
            f"RMS column norm {rms:.3e} px/m, median singular value {np.median(singular[order[1:]]):.3e}"
        )
        print(
            f"  weakest non-null mode s = {singular[order[1]]:.3e} ({singular[order[1]] / rms:.4f} of the RMS "
            f"column norm), overlap with the checkerboard {abs(waffle_mode @ checkerboard):.2f}; next "
            + ", ".join(f"{value:.2e}" for value in singular[order[2:8]])
        )
        spectrum_reported = True
    applied = np.asarray(history.applied_command_history_opd_m)[:, columns]
    waffle = 1e9 * applied @ waffle_mode
    post = 1e9 * np.asarray(history.post_update_residual_opd_rms_m)
    valid = np.asarray(history.valid_measurement_fraction)
    usable = np.asarray(history.reconstruction_usable)
    damping = system.reconstructor.damping_absolute
    print(
        f"seed {seed}, m_AB = {magnitude:g}, alpha = {alpha:g} (damping {damping:.3e} px/m): residual frames 100-399 "
        f"{post[100:].mean():.1f} nm, valid {valid[100:].mean():.3f}, recovery {dict(history.metadata['recovery'])}"
    )
    frames = np.arange(4, len(waffle))
    locked = usable[frames] & usable[frames - 1] & usable[frames - 3] & (valid[frames] > 0.93) & (valid[frames - 3] > 0.93) & (waffle[frames] != 0.0)
    increment = waffle[frames] - waffle[frames - 1]
    slope = np.polyfit(waffle[frames - 3][locked], increment[locked], 1)[0]
    magnitude_locked = np.abs(waffle[frames][locked])
    print(
        f"  waffle (mode norm) on {int(locked.sum())} locked frames: |coefficient| median {np.median(magnitude_locked):.0f} nm, "
        f"p90 {np.quantile(magnitude_locked, 0.9):.0f}, p99 {np.quantile(magnitude_locked, 0.99):.0f}; per-frame increment std "
        f"{increment[locked].std():.0f} nm; restoring gain {-slope:.3f} (loop gain {config.controller.gain:g})"
    )
    gate = np.array(gates)
    streak = 0
    for frame in range(len(usable)):
        streak = 0 if usable[frame] else streak + 1
        if streak == 3:
            first = frame - 2
            window = slice(max(first - 5, 0), first)
            fails = gate[window].mean(axis=0)
            print(
                f"  reset at frame {frame}: |waffle| three frames before the first rejected frame "
                f"{abs(waffle[max(first - 3, 0)]):.0f} nm; five frames before it: valid {valid[window].mean():.2f}, "
                f"lenslets failing clipping {fails[0]:.2f}, SNR_T support {fails[1]:.2f}, flux {fails[2]:.2f}, sigma {fails[3]:.2f}"
            )
