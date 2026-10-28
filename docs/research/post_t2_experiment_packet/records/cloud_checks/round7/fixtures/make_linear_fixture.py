"""Linear re-synthesis fixtures for review round 7 (operator changes after the first analysed frame; sparse lenslets).

Source: the round-2 traced pilot sidecar of the ci geometry at m_AB 7 with the
diagnostic 12 m damping (alpha 0.1, root seed 71, 400 frames, burn-in 100).
The run's noise sequence is extracted under the linear model
(n_k = (m^noisy_k - m^twin_k) + M dc_k, with dc rebuilt from the telemetry; it
matches the recorded centroid residuals at correlation 0.999), the two arms'
effective masks are edited, an optional burn-in kick is added to the noisy
arm's measurements, and the command difference is re-simulated through the
controller law with each frame's probed operators:

    inc_k = R^n_k (m^twin_k - m_ref - M dc_k + s n_k + kick_k) - R^t_k (m^twin_k - m_ref).

The noisy arm's centroids, expected centroids (centroid minus s n minus the
kick), validity, masks, the mask disagreement and the delta_v series
(|W dc|^2 / N, float64) are rewritten; the twin's centroid stream is kept (the
fixture re-synthesizes the command difference only). A fixture, not a run.

Variants:
  operator-change        three edge lenslets (grid r0000-r0001 x c0002-c0003) dropped by both arms from
                         analysed frame 60 on (the modal operator is the reduced one, which leaves one actuator
                         unsensed); a kick along that actuator's measurement signature at burn-in frames 95-99
                         sized to add 25 % to the window mean; the run's own noise (s = 1)
  operator-change-quiet  the same with the noise scaled by s = 1e-4 and, in addition, one more lenslet dropped by
                         the noisy arm only at five analysed frames (a deterministic arm-operator forcing): the
                         measured series is then the deterministic part, which the actual-operator prediction must
                         reproduce
  sparse-lenslets        two lenslets dropped by both arms in every analysed frame except five (usable in five frames
                         only: admissible intervals from zero to the sparse bound); the run's own noise, no kick

Usage: make_linear_fixture.py <variant> <source trace.npz> <output fixture.npz> <output summary.json>
Run with PYTHONPATH=<repo>/src:<repo>/docs/research/post_t2_experiment_packet/tools.
"""

from __future__ import annotations

import argparse
from collections import deque
import json
from pathlib import Path
import re
import sys

import numpy as np

from _packet_common import add_configuration_arguments, configuration_from_arguments, run_configuration
import linear_loop_noise_model as model

variant, source, output, summary_path = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
if variant not in ("operator-change", "operator-change-quiet", "sparse-lenslets"):
    raise SystemExit(f"unknown variant {variant}")
with np.load(source, allow_pickle=False) as archive:
    arrays = {key: archive[key] for key in archive.files if key != "metadata_json"}
    metadata = json.loads(str(archive["metadata_json"]))
parser = argparse.ArgumentParser()
add_configuration_arguments(parser)
config, described, _ = configuration_from_arguments(parser.parse_args(["--ci-geometry", "--magnitude", "7", "--alpha", "0.1"]))
config = run_configuration(config, root_seed=int(metadata["root_seed"]), n_steps=int(metadata["n_steps"]))
assert config.config_hash == metadata["config_hash"], "configuration differs from the sidecar's"
from shwfs_ao.experiments.scao import ScaoExecutionOptions, build_scao_system  # noqa: E402

system = build_scao_system(config, execution=ScaoExecutionOptions(telemetry_level="summary"))
parts = model.system_parts(system)
dense, response_w, row_ids, coordinate_ids, n_pupil = parts["interaction"], parts["pupil_response"], parts["row_ids"], parts["coordinate_ids"], parts["n_pupil"]
reference = parts["reference_xy_px"]
lenslet_ids = parts["lenslet_ids"]
rows = model.lenslet_rows(row_ids, lenslet_ids)
gain, leak, latency = float(config.controller.gain), float(config.controller.leak), int(config.controller.latency_frames)
noisy, twin = metadata["noisy_arm"], metadata["twin_arm"]
n_steps, burn_in = int(metadata["n_steps"]), int(metadata["burn_in_frames"])
size_c, n_rows = len(coordinate_ids), len(row_ids)
gram = response_w.T @ response_w
grid = np.array([[int(value) for value in re.findall(r"r(\d+)-c(\d+)", name)[0]] for name in lenslet_ids])
cache: dict[bytes, np.ndarray] = {}


def operator(mask: np.ndarray) -> np.ndarray:
    key = mask.tobytes()
    if key not in cache:
        cache[key] = model.reconstructor_matrix_masked(system.reconstructor, row_ids, mask, coordinate_ids)
    return cache[key]


def to_rows(xy: np.ndarray) -> np.ndarray:
    vector = np.zeros(n_rows)
    vector[rows[:, 0]] = xy[:, 0]
    vector[rows[:, 1]] = xy[:, 1]
    return vector


def to_xy(vector: np.ndarray) -> np.ndarray:
    return np.column_stack([vector[rows[:, 0]], vector[rows[:, 1]]])


masks = {arm: np.asarray(arrays[f"{arm}__measurement_row_masks"], dtype=bool).copy() for arm in (noisy, twin)}
centroids = {arm: np.asarray(arrays[f"{arm}__telemetry__centroids_xy_px"], dtype=float) for arm in (noisy, twin)}
twin_shift = np.stack([to_rows(centroids[twin][frame] - reference) for frame in range(n_steps)])

# 1. the noise sequence under the linear model, along the trajectory rebuilt from the telemetry
state = np.zeros(size_c)
queue: deque[np.ndarray] = deque(np.zeros(size_c) for _ in range(latency))
noise = np.zeros((n_steps, n_rows))
for frame in range(n_steps):
    noisy_shift = to_rows(centroids[noisy][frame] - reference)
    noise[frame] = noisy_shift - twin_shift[frame] + dense @ state
    increment = operator(masks[noisy][frame]) @ np.where(masks[noisy][frame], np.nan_to_num(noisy_shift), 0.0) - operator(masks[twin][frame]) @ np.where(masks[twin][frame], np.nan_to_num(twin_shift[frame]), 0.0)
    queue.append(increment)
    state = (1.0 - leak) * state + gain * queue.popleft()
noise = np.nan_to_num(noise)

# 2. the edited masks
edge = [index for index, (r, c) in enumerate(grid) if r <= 1 and 2 <= c <= 3]
frames_all = np.arange(n_steps)
noise_scale = 1.0
kick_frames: list[int] = []
extra_lenslets: list[int] = []
extra_frames: list[int] = []
if variant.startswith("operator-change"):
    dropped = edge
    drop_frames = frames_all >= burn_in + 60
    for arm in (noisy, twin):
        for index in dropped:
            masks[arm][np.ix_(drop_frames, rows[index])] = False
    kick_frames = list(range(burn_in - 5, burn_in))
    if variant == "operator-change-quiet":
        noise_scale = 1.0e-4
        extra_lenslets = [index for index, (r, c) in enumerate(grid) if r == 5 and c == 6][:1]
        extra_frames = [burn_in + 100 + 10 * step for step in range(5)]
        for index in extra_lenslets:
            masks[noisy][np.ix_(np.array(extra_frames), rows[index])] = False
else:
    dropped = [index for index, (r, c) in enumerate(grid) if (r, c) in ((3, 4), (6, 7))]
    keep = np.array([burn_in + 10, burn_in + 70, burn_in + 130, burn_in + 190, burn_in + 250])
    drop_frames = (frames_all >= burn_in) & ~np.isin(frames_all, keep)
    for arm in (noisy, twin):
        for index in dropped:
            masks[arm][np.ix_(drop_frames, rows[index])] = False

# 3. the kick direction: the actuator mode the reduced operator leaves unsensed and the full one senses
kick_signature = np.zeros(n_rows)
mode = None
if kick_frames:
    reduced = operator(masks[noisy][n_steps - 1]) @ dense
    full_loop = operator(np.ones(n_rows, dtype=bool)) @ dense
    values, vectors = np.linalg.eig(reduced)
    candidates = [index for index in np.argsort(np.abs(values)) if abs(values[index]) < 1.0e-9]
    mode = max((np.real(vectors[:, index]) for index in candidates), key=lambda vector: float(np.linalg.norm(full_loop @ vector) / np.linalg.norm(vector)))
    mode = mode / np.linalg.norm(mode)
    kick_signature = dense @ mode
    kick_signature = kick_signature / np.max(np.abs(kick_signature))


def simulate(amplitude: float) -> tuple[np.ndarray, np.ndarray]:
    state_s = np.zeros(size_c)
    queue_s: deque[np.ndarray] = deque(np.zeros(size_c) for _ in range(latency))
    post = np.zeros((n_steps, size_c))
    noisy_rows = np.zeros((n_steps, n_rows))
    for frame in range(n_steps):
        kick = amplitude * kick_signature if frame in kick_frames else 0.0
        shift = twin_shift[frame] - dense @ state_s + noise_scale * noise[frame] + kick
        noisy_rows[frame] = shift
        increment = operator(masks[noisy][frame]) @ np.where(masks[noisy][frame], np.nan_to_num(shift), 0.0) - operator(masks[twin][frame]) @ np.where(masks[twin][frame], np.nan_to_num(twin_shift[frame]), 0.0)
        queue_s.append(increment)
        state_s = (1.0 - leak) * state_s + gain * queue_s.popleft()
        post[frame] = state_s
    return post, noisy_rows


def window_series(post: np.ndarray) -> np.ndarray:
    return np.einsum("ki,ij,kj->k", post[burn_in:], gram, post[burn_in:]) / n_pupil


post_zero, _ = simulate(0.0)
amplitude = 0.0
if kick_frames:
    post_unit, _ = simulate(1.0)
    kick_part = post_unit - post_zero
    linear = float(np.mean(2.0 * np.einsum("ki,ij,kj->k", post_zero[burn_in:], gram, kick_part[burn_in:]) / n_pupil))
    quadratic = float(np.mean(np.einsum("ki,ij,kj->k", kick_part[burn_in:], gram, kick_part[burn_in:]) / n_pupil))
    base_mean = float(np.mean(window_series(post_zero)))
    target = 0.25 * base_mean if variant == "operator-change" else 4.0 * base_mean
    amplitude = (-linear + np.sqrt(linear**2 + 4.0 * quadratic * target)) / (2.0 * quadratic)
post_new, noisy_rows_new = simulate(amplitude)

# 4. the rewritten arrays
fixture = dict(arrays)
noisy_xy = np.stack([to_xy(noisy_rows_new[frame]) for frame in range(n_steps)]) + reference
kick_xy = np.stack([to_xy(amplitude * kick_signature if frame in kick_frames else np.zeros(n_rows)) for frame in range(n_steps)])
noise_xy = np.stack([to_xy(noise_scale * noise[frame]) for frame in range(n_steps)])
fixture[f"{noisy}__telemetry__centroids_xy_px"] = noisy_xy
fixture[f"{noisy}__telemetry__expected_centroids_xy_px"] = noisy_xy - noise_xy - kick_xy
for arm in (noisy, twin):
    fixture[f"{arm}__measurement_row_masks"] = masks[arm]
    lenslet_valid = masks[arm][:, rows[:, 0]] & masks[arm][:, rows[:, 1]]
    original_valid = np.asarray(arrays[f"{arm}__telemetry__valid_subapertures"], dtype=bool)
    fixture[f"{arm}__telemetry__valid_subapertures"] = original_valid & lenslet_valid
    if f"{arm}__telemetry__valid_by_snr" in arrays:
        fixture[f"{arm}__telemetry__valid_by_snr"] = np.asarray(arrays[f"{arm}__telemetry__valid_by_snr"], dtype=bool) & lenslet_valid
    fixture[f"{arm}__valid_measurement_fraction"] = masks[arm].mean(axis=1)
    fixture[f"{arm}__valid_subaperture_fraction"] = fixture[f"{arm}__telemetry__valid_subapertures"].mean(axis=1)
fixture["mask_disagreement_rows"] = np.count_nonzero(masks[noisy] != masks[twin], axis=1).astype(np.asarray(arrays["mask_disagreement_rows"]).dtype)
delta_v = window_series(post_new)
fixture["delta_v_m2"] = delta_v
fixture["mean_square_difference_m2"] = np.asarray(arrays["cross_term_m2"], dtype=float) + delta_v
for key in fixture:
    fixture[key] = np.asarray(fixture[key], dtype=arrays[key].dtype)
np.savez_compressed(output, metadata_json=np.array(json.dumps(metadata, sort_keys=True)), **fixture)
kick_part_final = post_new - post_zero
summary = {
    "variant": variant, "source": str(source), "configuration": described, "root_seed": metadata["root_seed"],
    "lenslets_dropped_by_both_arms": [lenslet_ids[index] for index in dropped],
    "frames_dropped": "analysed frames from 60 on" if variant.startswith("operator-change") else "every analysed frame except 10, 70, 130, 190, 250",
    "noisy_only_dropped": {"lenslets": [lenslet_ids[index] for index in extra_lenslets], "frames": extra_frames},
    "noise_scale": noise_scale,
    "kick": None if not kick_frames else {"frames": kick_frames, "amplitude_px_peak": float(amplitude), "mode_unsensed_by_reduced_operator": True, "full_operator_gain_on_mode": float(np.linalg.norm(operator(np.ones(n_rows, dtype=bool)) @ dense @ mode))},
    "window_mean_m2": float(np.mean(delta_v)),
    "window_mean_without_kick_m2": float(np.mean(window_series(post_zero))),
    "kick_share_of_window_mean": float(1.0 - np.mean(window_series(post_zero)) / np.mean(delta_v)) if kick_frames else 0.0,
    "kick_state_window_mean_m2": float(np.mean(np.einsum("ki,ij,kj->k", kick_part_final[burn_in:], gram, kick_part_final[burn_in:]) / n_pupil)),
    "mask_disagreement_frames": int(np.count_nonzero(fixture["mask_disagreement_rows"])),
    "operators_probed": len(cache),
}
summary_path.write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary))
