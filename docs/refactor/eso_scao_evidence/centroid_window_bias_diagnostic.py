"""Test the even-window centroid-bias hypothesis on the CI system."""
from dataclasses import replace
import numpy as np
from shwfs_ao.experiments.eso_scao_benchmark import tier_config
from shwfs_ao.experiments.scao import build_scao_system, run_closed_loop

def config(window, steps=200):
    c = tier_config("ci", n_steps=steps)
    return replace(c, wfs=replace(c.wfs, detector_window_px=window))

# Part 1: zero-mean-slope, symmetric local defocus in every lenslet.
for window in (24, 23):
    system = build_scao_system(config(window, 4))
    g = system.wfs.geometry
    opd = np.zeros(g.pupil_shape)
    for (r0, r1, c0, c1), (xc, yc) in zip(g.lenslet_bounds_rc, g.subaperture_centers_m):
        X = g.x_m[r0:r1, c0:c1] - xc
        Y = g.y_m[r0:r1, c0:c1] - yc
        opd[r0:r1, c0:c1] = (X * X + Y * Y) / 0.25**2
    rows = []
    for amp in (0.0, 1e-7, 2e-7, 4e-7):
        m = system.wfs.measure(amp * opd, random_streams=system.random_streams, include_noise=False)
        v = m.vector.values.reshape(-1, 2)
        ok = m.valid_subapertures
        rows.append((amp * 1e9, float(np.mean(v[ok, 0])), float(np.mean(v[ok, 1])), float(np.mean(ok))))
    print(f"window {window}: symmetric local defocus -> mean slope (px)")
    for amp, sx, sy, frac in rows:
        print(f"   defocus scale {amp:5.0f} nm: mean sx {sx:+.5f}  sy {sy:+.5f}  valid {frac:.2f}")

# Part 2: closed-loop residual tilt with each window.
class TiltRecorder:
    requested_fields = frozenset({"pre_update_residual_opd_m"})
    def __init__(self, g):
        self.mask = np.isfinite(np.where(g.pupil_mask, 0.0, np.nan))
        self.x = g.x_m[self.mask]
        self.y = g.y_m[self.mask]
        self.A = np.column_stack([np.ones_like(self.x), self.x, self.y])
        self.t = []
    def observe(self, ev):
        z = ev.pre_update_residual_opd_m[self.mask]
        coef, *_ = np.linalg.lstsq(self.A, z, rcond=None)
        self.t.append(coef[1:])
for window in (24, 23):
    c = config(window)
    s = build_scao_system(c)
    rec = TiltRecorder(s.wfs.geometry)
    h = run_closed_loop(c, system=s, observers=(rec,))
    t = np.array(rec.t)[50:]
    print(f"window {window}: closed-loop residual tilt after burn-in (rad): mean x {t[:,0].mean():+.3e} y {t[:,1].mean():+.3e}  std x {t[:,0].std():.2e} y {t[:,1].std():.2e};"
          f" residual {h.pre_update_residual_opd_rms_m[50:].mean()*1e9:.1f} nm, usable {h.reconstruction_usable.mean():.2f}, valid sub {h.valid_subaperture_fraction.min():.3f}")
