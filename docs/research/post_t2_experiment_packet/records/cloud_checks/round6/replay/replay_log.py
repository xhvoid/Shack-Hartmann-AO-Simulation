"""Replay a traced ci pilot (seed 71, 400 frames, burn-in 100, maps retained) with every reconstruct() input and output and every controller update and applied command logged.

Usage: replay_log.py <log name>.npz <configuration arguments, e.g. --ci-geometry --magnitude 9 --alpha 0.1>
The log is written next to this script's scratch directory
the replay reproduces the pilot sidecar's delta_v series exactly (replay_check.py).
"""
import argparse
import sys
import time
import numpy as np
# Run with PYTHONPATH=<repo>/src:<repo>/docs/research/post_t2_experiment_packet/tools (the packet's tools import the same way).
from _packet_common import add_configuration_arguments, configuration_from_arguments
import shwfs_ao.calibration.reconstructors as recon_mod
import shwfs_ao.calibration.sparse as sparse_mod
import shwfs_ao.control.controller as ctrl_mod

parser = argparse.ArgumentParser()
add_configuration_arguments(parser)
arguments = parser.parse_args(sys.argv[2:])
config, described, governed = configuration_from_arguments(arguments)
print(described, governed)

log = {"recon": [], "applied": []}
def wrap_reconstruct(cls):
    original = cls.reconstruct
    def logged(self, measurement, *args, **kwargs):
        out = original(self, measurement, *args, **kwargs)
        values = np.array(getattr(measurement, "values", measurement), dtype=float)
        valid = np.array(getattr(measurement, "valid_rows", args[0] if args else None), dtype=bool)
        est = None if out is None else np.array(out.delta_coordinates_opd_m, dtype=float)
        usable = None if out is None else np.array(out.usable_rows, dtype=bool)
        log["recon"].append((id(self), values, valid, est, usable))
        return out
    cls.reconstruct = logged
for cls_name in dir(recon_mod):
    cls = getattr(recon_mod, cls_name)
    if isinstance(cls, type) and "reconstruct" in cls.__dict__ and cls.__module__ == recon_mod.__name__:
        wrap_reconstruct(cls)
        print("patched", recon_mod.__name__, cls_name)
for cls_name in dir(sparse_mod):
    cls = getattr(sparse_mod, cls_name)
    if isinstance(cls, type) and "reconstruct" in cls.__dict__ and cls.__module__ == sparse_mod.__name__:
        wrap_reconstruct(cls)
        print("patched", sparse_mod.__name__, cls_name)
orig_accept = ctrl_mod.LeakyIntegratorController.accept_applied_commands
def logged_accept(self, commands):
    log["applied"].append((id(self), np.array(commands.values_opd_m, dtype=float)))
    return orig_accept(self, commands)
ctrl_mod.LeakyIntegratorController.accept_applied_commands = logged_accept
orig_update = ctrl_mod.LeakyIntegratorController.update
def logged_update(self, delta):
    log.setdefault("update", []).append((id(self), None if delta is None else np.array(delta.values_opd_m, dtype=float)))
    return orig_update(self, delta)
ctrl_mod.LeakyIntegratorController.update = logged_update

from shwfs_ao.experiments.detector_level import paired_noise_run_traced  # noqa: E402 (after the patches, for readability)
from shwfs_ao.experiments.scao import ScaoExecutionOptions  # noqa: E402
started = time.perf_counter()
result = paired_noise_run_traced(config, root_seed=71, n_steps=400, burn_in_frames=100, execution=ScaoExecutionOptions(telemetry_level="summary"), block_frames=25, retain_residual_maps=True, propagation_weights=True)
print("wall", time.perf_counter() - started)
trace = result.pop("trace")
print("arm_order", trace.get("arm_order"))
print("result keys", sorted(result.keys())[:40])
ids_recon = sorted({r[0] for r in log["recon"]})
ids_ctrl = sorted({a[0] for a in log["applied"]})
print("reconstructor instances", ids_recon, "controller instances", ids_ctrl, "calls", len(log["recon"]), len(log["applied"]), len(log["update"]))
np.savez_compressed("/tmp/claude-0/-home-user-Shack-Hartmann-AO-Simulation/f1f3bff0-5382-5b19-9652-6c00a445942e/scratchpad/round6/replay/" + sys.argv[1] + "",
    recon_ids=np.array([r[0] for r in log["recon"]]), recon_values=np.array([r[1] for r in log["recon"]]), recon_valid=np.array([r[2] for r in log["recon"]]),
    recon_est=np.array([np.full_like(log["recon"][0][3], np.nan) if r[3] is None else r[3] for r in log["recon"]]), recon_usable=np.array([r[4] if r[4] is not None else np.zeros_like(r[2]) for r in log["recon"]]),
    applied_ids=np.array([a[0] for a in log["applied"]]), applied=np.array([a[1] for a in log["applied"]]),
    update_ids=np.array([u[0] for u in log["update"]]), update=np.array([np.full(len(log["applied"][0][1]), np.nan) if u[1] is None else u[1] for u in log["update"]]),
    delta_v_m2=np.asarray(trace["delta_v_m2"]), mask_disagreement_rows=np.asarray(trace["mask_disagreement_rows"]))
print("saved")
