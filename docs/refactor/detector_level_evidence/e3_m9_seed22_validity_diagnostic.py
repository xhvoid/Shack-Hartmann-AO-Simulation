"""E3 diagnostic: which validity criterion removes lenslets at m_AB = 9, root seed 22.

Runs det_emccd_12m_medium_derived@1 at m_AB = 9 (400 frames) and records, per
frame, the fraction of lenslets failing each gate.  Run from the checkout:
    python docs/refactor/detector_level_evidence/e3_m9_seed22_validity_diagnostic.py
"""

import numpy as np
from dataclasses import replace
from shwfs_ao.io.configs import load_system_profile, RandomSeedConfig
from shwfs_ao.experiments.detector_level import with_magnitude
from shwfs_ao.experiments.scao import build_scao_system, run_closed_loop, ScaoExecutionOptions
cfg = with_magnitude(load_system_profile("det_emccd_12m_medium_derived", 1), 9.0)
cfg = replace(cfg, random=RandomSeedConfig(root_seed=22), controller=replace(cfg.controller, n_steps=400))
system = build_scao_system(cfg, execution=ScaoExecutionOptions(telemetry_level="summary"))
wfs = system.wfs
records = []
original = wfs.measure_exposure
def recording(samples, **kw):
    m = original(samples, **kw)
    t = m.detector_telemetry
    records.append((np.mean(~t.valid_by_flux), np.mean(~t.valid_by_snr), np.mean(~t.valid_by_uncertainty), np.mean(~t.valid_by_clipping),
                    np.mean(~t.uncertainty_supported), float(np.median(t.peak_snr)), float(np.min(t.peak_snr)), float(np.max(t.clipping_fraction))))
    return m
wfs.measure_exposure = recording
h = run_closed_loop(cfg, system=system)
r = np.array(records)
post = np.asarray(h.post_update_residual_opd_rms_m)
worst = np.argsort(r[:,1]+r[:,2]+r[:,3])[-8:]
print("fractions invalid by flux/snr/unc/clip, unsupported, median peak snr, min peak snr, max clipping; post rms nm")
for i in sorted(worst):
    print(i, np.round(r[i],3), round(1e9*post[i],1))
print("frames with any invalid:", int(np.sum(r[:,:4].sum(axis=1)>0)), "of", len(r))
print("mean over frames: by snr %.4f unc %.4f clip %.4f unsupported %.4f" % tuple(r[:, [1,2,3,4]].mean(axis=0)))
