"""Carried-state fixture (review round 6, finding 12): a burn-in measurement transient whose loop response adds 25 % to the window variance.

Source: the round-2 traced pilot sidecar of the ci geometry at m_AB 7 with the
diagnostic 12 m damping (alpha 0.1, root seed 71). The noisy arm's centroids
at burn-in frames 95-99 receive a kick along the measurement signature M v of
the slowest sensed loop mode v. Its closed-loop response dp is propagated with
the noisy arm's own probed operator of every frame and the controller law
(leak, gain, delay queue), and fed back into the noisy arm's later centroids
and expected centroids as -M dp (the residual changes, the noise does not).
The delta_v series gains (2 W dc . W dp + |W dp|^2) / N per analysed frame,
with dc the reconstructed command difference; the mean-square difference keeps
cross_term = msd - delta_v. The kick amplitude is solved so that the window
mean rises by 25 %. A fixture, not a run: its digest matches no record.

Usage: make_carried_fixture.py <source trace.npz> <output fixture.npz> <output summary.json>
"""

from __future__ import annotations

import argparse
from collections import deque
import json
from pathlib import Path
import sys

import numpy as np

# Run with PYTHONPATH=<repo>/src:<repo>/docs/research/post_t2_experiment_packet/tools (the packet's tools import the same way).
from _packet_common import add_configuration_arguments, configuration_from_arguments, run_configuration  # noqa: E402
import linear_loop_noise_model as model  # noqa: E402

source, output, summary_path = (Path(x) for x in sys.argv[1:4])
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
rows = model.lenslet_rows(row_ids, parts["lenslet_ids"])
gain, leak, latency = float(config.controller.gain), float(config.controller.leak), int(config.controller.latency_frames)
noisy, twin = metadata["noisy_arm"], metadata["twin_arm"]
n_steps, burn_in = int(metadata["n_steps"]), int(metadata["burn_in_frames"])
size_c = len(coordinate_ids)
cache: dict[bytes, np.ndarray] = {}


def operator(mask: np.ndarray) -> np.ndarray:
    key = mask.tobytes()
    if key not in cache:
        cache[key] = model.reconstructor_matrix_masked(system.reconstructor, row_ids, mask, coordinate_ids)
    return cache[key]


def to_rows(xy: np.ndarray) -> np.ndarray:
    vector = np.zeros(len(row_ids))
    vector[rows[:, 0]] = xy[:, 0]
    vector[rows[:, 1]] = xy[:, 1]
    return vector


def to_xy(vector: np.ndarray) -> np.ndarray:
    return np.column_stack([vector[rows[:, 0]], vector[rows[:, 1]]])


masks = {arm: np.asarray(arrays[f"{arm}__measurement_row_masks"], dtype=bool) for arm in (noisy, twin)}
centroids = {arm: np.asarray(arrays[f"{arm}__telemetry__centroids_xy_px"], dtype=float) for arm in (noisy, twin)}

# the reconstructed command difference (as the tool computes it)
increments = np.zeros((n_steps, size_c))
for arm, sign in ((noisy, 1.0), (twin, -1.0)):
    for frame in range(n_steps):
        mask = masks[arm][frame]
        measurement = to_rows(centroids[arm][frame] - reference)
        measurement = np.where(mask & np.isfinite(measurement), measurement, 0.0)
        increments[frame] += sign * (operator(mask) @ measurement)
queue: deque[np.ndarray] = deque(np.zeros(size_c) for _ in range(latency))
state = np.zeros(size_c)
dc = np.zeros((n_steps, size_c))
for frame in range(n_steps):
    queue.append(increments[frame])
    state = (1.0 - leak) * state + gain * queue.popleft()
    dc[frame] = state

# the kick direction: the measurement signature of the slowest sensed mode of the modal loop
modal_mask = masks[noisy][burn_in]
loop = operator(modal_mask) @ dense
eigenvalues, eigenvectors = np.linalg.eig(loop)
sensed = np.flatnonzero(np.abs(eigenvalues) > 1.0e-3)
slow = sensed[np.argmin(np.abs(eigenvalues[sensed]))]
mode = np.real(eigenvectors[:, slow])
mode /= np.linalg.norm(mode)
signature = dense @ mode
kick_frames = range(burn_in - 5, burn_in)


def response(amplitude: float) -> tuple[np.ndarray, np.ndarray]:
    """Post-update perturbation states and the noisy arm's centroid changes for a kick of the given amplitude (px)."""

    queue_p: deque[np.ndarray] = deque(np.zeros(size_c) for _ in range(latency))
    previous = np.zeros(size_c)
    states = np.zeros((n_steps, size_c))
    centroid_change = np.zeros((n_steps, len(row_ids)))
    feedback_change = np.zeros((n_steps, len(row_ids)))
    for frame in range(n_steps):
        feedback = -dense @ previous
        kick = amplitude * signature / np.max(np.abs(signature)) if frame in kick_frames else np.zeros(len(row_ids))
        mask = masks[noisy][frame]
        change = np.where(mask, kick + feedback, feedback)
        centroid_change[frame] = change
        feedback_change[frame] = feedback
        queue_p.append(operator(mask) @ np.where(mask, change, 0.0))
        previous = (1.0 - leak) * previous + gain * queue_p.popleft()
        states[frame] = previous
    return states, centroid_change, feedback_change


gram = response_w.T @ response_w
frames = np.arange(burn_in, n_steps)
delta_v = np.asarray(arrays["delta_v_m2"], dtype=float)
unit_states, _, _ = response(1.0)
linear = float(np.mean([2.0 * dc[k] @ gram @ unit_states[k] for k in frames]) / n_pupil)
quadratic = float(np.mean([unit_states[k] @ gram @ unit_states[k] for k in frames]) / n_pupil)
target = 0.25 * float(np.mean(delta_v))
amplitude = (-linear + np.sqrt(linear**2 + 4.0 * quadratic * target)) / (2.0 * quadratic)
states, centroid_change, feedback_change = response(amplitude)
added = np.array([(2.0 * dc[k] @ gram @ states[k] + states[k] @ gram @ states[k]) / n_pupil for k in frames])

fixture = dict(arrays)
fixture[f"{noisy}__telemetry__centroids_xy_px"] = centroids[noisy] + np.stack([to_xy(change) for change in centroid_change])
fixture[f"{noisy}__telemetry__expected_centroids_xy_px"] = np.asarray(arrays[f"{noisy}__telemetry__expected_centroids_xy_px"], dtype=float) + np.stack([to_xy(change) for change in feedback_change])
fixture["delta_v_m2"] = delta_v + added
fixture["mean_square_difference_m2"] = np.asarray(arrays["cross_term_m2"], dtype=float) + fixture["delta_v_m2"]
for key in fixture:
    fixture[key] = np.asarray(fixture[key], dtype=arrays[key].dtype)
np.savez_compressed(output, metadata_json=np.array(json.dumps(metadata, sort_keys=True)), **fixture)
summary = {
    "source": str(source), "configuration": described, "root_seed": metadata["root_seed"],
    "kick_frames": list(kick_frames), "kick_amplitude_px_peak": float(amplitude),
    "mode_eigenvalue_of_RM": [float(np.real(eigenvalues[slow])), float(np.imag(eigenvalues[slow]))],
    "window_mean_increase_over_source_mean": float(np.mean(added) / np.mean(delta_v)),
    "first_block_increase_over_source_mean": float(np.mean(added[:25]) / np.mean(delta_v)),
    "operators_probed": len(cache),
}
Path(summary_path).write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary))
