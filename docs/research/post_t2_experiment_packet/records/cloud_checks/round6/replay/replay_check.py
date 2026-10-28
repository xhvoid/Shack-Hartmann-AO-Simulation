"""Check the telemetry reconstruction's ingredients against logged runtime calls (round 6).

replay_log.py / replay_log2.py re-ran two traced ci pilots (seed 71, 400 frames,
burn-in 100) with every reconstruct() input and output and every controller
update logged
the replays reproduce the sidecars' delta_v series exactly. This
script compares (a) each logged reconstructor input with the sidecar's
centroids minus the sensor's calibration reference, and (b) each logged
estimate with the probed operator of that frame's mask times the input.
"""
import argparse
import json
import numpy as np
# Run with PYTHONPATH=<repo>/src:<repo>/docs/research/post_t2_experiment_packet/tools (the packet's tools import the same way).
from _packet_common import add_configuration_arguments, configuration_from_arguments, run_configuration
import linear_loop_noise_model as m
from shwfs_ao.experiments.scao import ScaoExecutionOptions, build_scao_system

S = "/tmp/claude-0/-home-user-Shack-Hartmann-AO-Simulation/f1f3bff0-5382-5b19-9652-6c00a445942e/scratchpad"
cases = [("ci m9, 12 m damping (alpha 0.1)", ["--ci-geometry", "--magnitude", "9", "--alpha", "0.1"], "log.npz", "pilots_maps/ci_m9_alpha0p1/trace.npz"),
         ("ci m7, ci damping (0.001)", ["--ci-geometry", "--magnitude", "7"], "log_m7d.npz", "pilots_maps/ci_m7_default/trace.npz")]
out = {}
for name, args, log, sidecar in cases:
    p = argparse.ArgumentParser()
    add_configuration_arguments(p)
    config, described, _ = configuration_from_arguments(p.parse_args(args))
    config = run_configuration(config, root_seed=71, n_steps=400)
    system = build_scao_system(config, execution=ScaoExecutionOptions(telemetry_level="summary"))
    parts = m.system_parts(system)
    ref = parts["reference_xy_px"]
    L = np.load(f"{S}/round6/replay/{log}")
    z = np.load(f"{S}/round6/{sidecar}")
    vals, valid, est = L["recon_values"], L["recon_valid"], L["recon_est"]
    entry = {"configuration": described, "delta_v_replay_vs_sidecar_max_relative": float(np.max(np.abs(L["delta_v_m2"] - z["delta_v_m2"])) / np.mean(z["delta_v_m2"])),
             "reconstructor_metadata": {k: v for k, v in dict(system.reconstructor.metadata).items() if k in ("solver", "damping_relative", "atol", "btol", "max_iterations")}, "arms": {}}
    cache = {}
    for arm, off in (("noise_on", 0), ("operating_expectation", 544)):
        c = z[f"{arm}__telemetry__centroids_xy_px"]
        meas = np.zeros((400, 144))
        meas[:, 0::2] = c[:, :, 0] - ref[:, 0]
        meas[:, 1::2] = c[:, :, 1] - ref[:, 1]
        v, vm = vals[off:off + 400], valid[off:off + 400]
        errs = []
        for k in range(400):
            key = vm[k].tobytes()
            if key not in cache:
                cache[key] = m.reconstructor_matrix_masked(system.reconstructor, parts["row_ids"], vm[k], parts["coordinate_ids"])
            errs.append(float(np.linalg.norm(cache[key] @ np.where(vm[k], np.nan_to_num(v[k]), 0.0) - est[off + k]) / np.linalg.norm(est[off + k])))
        entry["arms"][arm] = {"masks_equal_sidecar": bool(np.array_equal(vm, z[f"{arm}__measurement_row_masks"])),
                              "input_minus_centroid_minus_reference_max_px": float(np.max(np.where(vm, np.abs(np.nan_to_num(v) - meas), 0.0))),
                              "input_minus_centroid_max_px": float(np.max(np.where(vm, np.abs(np.nan_to_num(v) - (meas + ref.reshape(-1)[None, :])), 0.0))),
                              "probed_operator_vs_estimate_relative_median": float(np.median(errs)), "probed_operator_vs_estimate_relative_max": float(np.max(errs))}
    entry["distinct_masks_probed"] = len(cache)
    out[name] = entry
json.dump(out, open(f"{S}/round6/replay/replay_check.json", "w"), indent=2)
print(json.dumps(out, indent=1))
