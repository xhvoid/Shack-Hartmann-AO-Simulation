#!/usr/bin/env python3
"""Exact linear closed-loop detector-noise model with the reconstructed spatial feedback.

Proposed in the post-T2 experiment packet (review round 1, finding 3).  The
scalar transfer factor ``kappa(g, l, d)`` of the earlier draft assumed that
the reconstructor feeds every DM mode back with unit gain.  The loop's actual
feedback is the matrix ``L = R M`` (reconstructor times calibrated
interaction matrix on the controlled actuators); under Tikhonov or LSMR
damping its eigenvalues ``s_i^2 / (s_i^2 + damp^2)`` are below one for poorly
sensed modes, so those modes reject noise differently from the unit-feedback
loop, and the noise enters as ``R n``.  This tool computes the stationary
covariance of the command difference between the noise-on loop and its
noiseless twin for the loop of technical reference 4.2 (leaky integrator,
gain ``g``, leak ``l``, queue latency ``d`` frames; ``controller.update``:
``c_{k+1} = (1 - l) c_k + g * released``, the released increment being the
one enqueued ``d`` updates earlier):

    dc_{k+1} = (1 - l) dc_k - g L dc_{k-d} + g R n_{k-d}

with ``n`` white measurement noise of covariance ``Sigma`` (2x2 blocks per
lenslet: the realized x/y residual covariance of a traced sidecar, or the
flat-wavefront ``detector_covariance_v2`` model).  With the state
``x_k = (dc_k, ..., dc_{k-d})`` this is ``x_{k+1} = F x_k + G n``.  The two
arms start from the same command, so ``P_0 = 0`` exactly and the covariance
of the run's frames is the transient ``P_{k+1} = F P_k F^T + G Sigma G^T``;
the model's prediction for a run is the mean of ``tr(Gram P_k) / N_pupil``
over the analysed frames (``delta_v_exact_window_m2``, the primary value).
The stationary limit ``P = F P F^T + G Sigma G^T`` (discrete Lyapunov
equation) is reported beside it (``delta_v_exact_stationary_m2``); the two
differ when the loop has modes whose time constant is not short against the
run, which happens for weakly sensed modes under small feedback and no
leak.  The predicted isolated detector-noise variance is

    DeltaV_pred = tr(Gram Cov(dc)) / N_pupil,   Gram = W_c^T W_c,

``W_c`` being the piston-removed DM response of each controlled actuator at
the pupil samples: the piston-removed pupil mean square of the noise-driven
correction difference, which is the sidecar's ``delta_v_m2`` in
expectation (the twin and the noisy arm see the same atmosphere).  Three
reductions are reported beside the exact value: the exact model with the
x/y correlations of ``Sigma`` zeroed, the scalar reduction of the earlier
draft ``kappa * sum_r w_r sigma_r^2`` (exact when ``L = I`` and ``Sigma`` is
diagonal; ``w_r`` are the series' propagation weights), and the one-step
open-loop propagation ``tr(Gram R Sigma R^T) / N_pupil``.  Assumptions: a
fixed row mask (every row usable, as ``reconstructor_matrix`` probes), no
stroke clipping, no recovery action, temporally white noise, a stationary
loop (the spectral radius of ``F`` is reported and must be below one).

``--sigma flat`` uses the sensor's flat-wavefront model (an a-priori
prediction); ``--sigma sidecar`` uses a traced sidecar's realized residuals
``c_noisy - c_expected`` (``ddof = 1``) under two support rules, both
reported: ``available`` (primary by default) takes every lenslet that is
valid, supported and finite in at least ``--support-min-fraction`` of the
analysed frames and estimates its covariance over its own valid frames, so
a lenslet whose gate flickers rarely still carries the noise it fed to the
loop; ``strict`` takes only lenslets valid in every analysed frame (the E0
summary's support rule) and under-states the noise power when edge
lenslets flicker.  Rows outside the chosen support carry no noise in the
model.  Sidecar mode requires the built configuration's hash to equal the
sidecar's and compares the prediction with the sidecar's measured
``delta_v_m2`` (mean and 25-frame block standard error).  ``--self-test``
checks the Lyapunov solver against ``kappa`` in the unit-feedback limit and
exits.

Building a 12 m or 42 m system is governed (``--enabled-by-user``).  The
dense ``W_c`` (pupil samples x controlled actuators) and the Lyapunov state
(controlled actuators x (d + 1)) are sized before anything is allocated and
refused above ``--max-dense-mib`` / ``--max-state``; the 42 m geometry is
out of reach of this tool.  Analysis only: no loop is run and nothing in the
repository is changed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import sys
import time
from typing import Any

import numpy as np
from scipy import linalg

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _packet_common import (  # noqa: E402
    add_configuration_arguments,
    configuration_from_arguments,
    jsonable,
    peak_rss_bytes,
    run_configuration,
    write_record_once,
)

SCHEMA = "post_t2_linear_loop_noise_model.v1"
PROBE_M = 1.0e-9
ACCEPTED_SIDECAR_SCHEMAS = ("shwfs_ao.noise_isolation_trace_sidecar.v1", "post_t2_pilot_trace_sidecar.v1")


def scalar_kappa(gain: float, leak: float, latency: int, samples: int = 1 << 16) -> float:
    """Mean-square gain of the unit-feedback loop ``g z / (z^{d+1} - (1-l) z^d + g)`` for white noise."""

    omega = 2.0 * np.pi * (np.arange(samples) + 0.5) / samples
    z = np.exp(1j * omega)
    transfer = gain * z / (z ** (latency + 1) - (1.0 - leak) * z**latency + gain)
    return float(np.mean(np.abs(transfer) ** 2))


def transition_matrix(loop: np.ndarray, *, gain: float, leak: float, latency: int) -> np.ndarray:
    size = loop.shape[0]
    blocks = latency + 1
    transition = np.zeros((size * blocks, size * blocks))
    transition[:size, :size] = (1.0 - leak) * np.eye(size)
    transition[:size, latency * size:(latency + 1) * size] += -gain * loop
    for block in range(1, blocks):
        transition[block * size:(block + 1) * size, (block - 1) * size:block * size] = np.eye(size)
    return transition


def forcing_matrix(response: np.ndarray, sigma: np.ndarray, *, gain: float, latency: int) -> np.ndarray:
    """``G Sigma G^T`` for the state ``(dc_k, ..., dc_{k-d})``."""

    size = response.shape[0]
    forcing = np.zeros((size * (latency + 1), size * (latency + 1)))
    forcing[:size, :size] = (gain**2) * (response @ sigma @ response.T)
    return forcing


def propagate(covariance: np.ndarray, loop: np.ndarray, *, gain: float, leak: float, latency: int) -> np.ndarray:
    """``F P F^T`` using the companion structure of ``F`` (no dense ``F`` product)."""

    size = loop.shape[0]
    tail = latency * size

    def apply(matrix: np.ndarray) -> np.ndarray:
        out = np.empty_like(matrix)
        out[:size] = (1.0 - leak) * matrix[:size] - gain * (loop @ matrix[tail:tail + size])
        if latency:
            out[size:] = matrix[:-size]
        return out

    return apply(apply(covariance).T).T


def window_covariance(loop: np.ndarray, forcing: np.ndarray, *, gain: float, leak: float, latency: int, n_steps: int, burn_in: int) -> tuple[np.ndarray, np.ndarray]:
    """Leading blocks ``Cov(dc_{k+1})`` for every frame ``k`` from ``P_0 = 0``, and the covariance after the last frame.

    Returns the per-frame traces' ingredients: the list of leading blocks is
    too large to keep, so the function returns the mean leading block over
    the analysed frames (``burn_in <= k < n_steps``) and the final state.
    """

    size = loop.shape[0]
    state = np.zeros_like(forcing)
    mean_block = np.zeros((size, size))
    analysed = 0
    for frame in range(n_steps):
        state = propagate(state, loop, gain=gain, leak=leak, latency=latency) + forcing
        if frame >= burn_in:
            mean_block += state[:size, :size]
            analysed += 1
    mean_block /= max(analysed, 1)
    return 0.5 * (mean_block + mean_block.T), state


def stationary_covariance(response: np.ndarray, loop: np.ndarray, sigma: np.ndarray, *, gain: float, leak: float, latency: int) -> tuple[np.ndarray, float, float]:
    """Stationary ``Cov(dc)`` of the noise-driven command difference, the spectral radius of ``F`` and the Lyapunov residual."""

    size = response.shape[0]
    transition = transition_matrix(loop, gain=gain, leak=leak, latency=latency)
    radius = float(np.max(np.abs(np.linalg.eigvals(transition))))
    if radius >= 1.0:
        raise SystemExit(f"the linear loop is not stationary (spectral radius {radius:.4f}); no stationary covariance exists.")
    forcing = forcing_matrix(response, sigma, gain=gain, latency=latency)
    covariance = linalg.solve_discrete_lyapunov(transition, forcing)
    covariance = 0.5 * (covariance + covariance.T)
    residual = float(np.linalg.norm(covariance - transition @ covariance @ transition.T - forcing) / max(np.linalg.norm(forcing), 1e-300))
    return covariance[:size, :size], radius, residual


def self_test() -> dict[str, Any]:
    """Unit feedback, one actuator, unit noise: the Lyapunov variance must be ``kappa``."""

    cases = []
    for gain, leak, latency in ((0.3, 0.0, 2), (0.2, 0.02, 2), (0.4, 0.0, 2), (0.5, 0.0, 0), (0.3, 0.0, 1)):
        covariance, radius, residual = stationary_covariance(np.eye(1), np.eye(1), np.eye(1), gain=gain, leak=leak, latency=latency)
        kappa = scalar_kappa(gain, leak, latency)
        cases.append({"gain": gain, "leak": leak, "latency": latency, "lyapunov_variance": float(covariance[0, 0]), "kappa": kappa, "relative_difference": float(covariance[0, 0] / kappa - 1.0), "spectral_radius": radius, "lyapunov_residual": residual})
    # Three decoupled modes with feedback 1, 0.5 and 0.1 at unit noise: each mode's variance is its own scalar loop's.
    loop = np.diag([1.0, 0.5, 0.1])
    covariance, radius, _ = stationary_covariance(np.eye(3), loop, np.eye(3), gain=0.3, leak=0.0, latency=2)
    modal = []
    for index, feedback in enumerate((1.0, 0.5, 0.1)):
        single, _, _ = stationary_covariance(np.eye(1), np.eye(1) * feedback, np.eye(1), gain=0.3, leak=0.0, latency=2)
        modal.append({"feedback": feedback, "variance_in_3x3": float(covariance[index, index]), "variance_alone": float(single[0, 0])})
    # Structured propagation against the dense product on a random symmetric matrix, and the
    # window mean against kappa for a unit-feedback loop whose transient (time constant about
    # 1/g frames) is short against the window.
    rng = np.random.default_rng(7)
    loop3 = np.array([[1.0, 0.1, 0.0], [0.1, 0.8, 0.0], [0.0, 0.0, 0.3]])
    random = rng.standard_normal((9, 9))
    random = random @ random.T
    dense = transition_matrix(loop3, gain=0.3, leak=0.0, latency=2)
    structured = propagate(random, loop3, gain=0.3, leak=0.0, latency=2)
    propagation_error = float(np.max(np.abs(structured - dense @ random @ dense.T)) / np.max(np.abs(random)))
    forcing = forcing_matrix(np.eye(1), np.eye(1), gain=0.3, latency=2)
    window_mean, _ = window_covariance(np.eye(1), forcing, gain=0.3, leak=0.0, latency=2, n_steps=400, burn_in=100)
    window_check = {"window_mean_variance": float(window_mean[0, 0]), "kappa": scalar_kappa(0.3, 0.0, 2), "relative_difference": float(window_mean[0, 0] / scalar_kappa(0.3, 0.0, 2) - 1.0)}
    passed = (
        all(abs(case["relative_difference"]) < 1.0e-6 for case in cases)
        and all(abs(entry["variance_in_3x3"] / entry["variance_alone"] - 1.0) < 1.0e-9 for entry in modal)
        and propagation_error < 1.0e-12
        and abs(window_check["relative_difference"]) < 1.0e-6
    )
    return {"unit_feedback_cases": cases, "decoupled_modes_gain_0.3_latency_2": modal, "structured_propagation_max_error": propagation_error, "window_mean_unit_feedback_400_100": window_check, "passed": bool(passed)}


def lenslet_rows(row_ids: tuple[str, ...], lenslet_ids: tuple[str, ...]) -> np.ndarray:
    """``(lenslets, 2)`` row indices of each lenslet's x and y rows, by identifier."""

    index = {identifier: position for position, identifier in enumerate(row_ids)}
    try:
        return np.array([[index[f"{lenslet}:x"], index[f"{lenslet}:y"]] for lenslet in lenslet_ids], dtype=int).reshape(len(lenslet_ids), 2)
    except KeyError as exc:
        raise SystemExit(f"row {exc} is not a measurement row of the built system; the lenslet identifiers do not match its rows.") from None


def controlled_response(system: Any) -> dict[str, Any]:
    """``R`` (controlled x rows), ``M`` (rows x controlled), the piston-removed pupil response ``W_c`` and the identifiers."""

    from shwfs_ao.core.types import DmCommandVector
    from shwfs_ao.experiments.detector_level import reconstructor_matrix

    matrix = system.interaction_matrix
    if matrix.coordinate_kind != "dm_command_opd":
        raise SystemExit(f"coordinate kind {matrix.coordinate_kind!r}: the model is defined for actuator-space reconstructors.")
    row_ids = tuple(system.wfs.row_ids)
    if tuple(matrix.row_ids) != row_ids:
        raise SystemExit("the interaction matrix rows are not the sensor's rows.")
    dense = np.asarray(matrix.matrix, dtype=float)
    coordinate_ids = tuple(matrix.coordinate_ids)
    started = time.perf_counter()
    response = reconstructor_matrix(system.reconstructor, row_ids)
    probe_s = time.perf_counter() - started
    if response.shape != (len(coordinate_ids), len(row_ids)) or dense.shape != (len(row_ids), len(coordinate_ids)):
        raise SystemExit(f"shape mismatch: R {response.shape}, M {dense.shape}, rows {len(row_ids)}, controlled {len(coordinate_ids)}.")
    actuator_ids = tuple(system.dm.actuator_ids)
    positions = {identifier: position for position, identifier in enumerate(actuator_ids)}
    pupil = np.asarray(system.wfs.geometry.pupil_mask, dtype=bool)
    n_pupil = int(np.count_nonzero(pupil))
    columns = np.empty((n_pupil, len(coordinate_ids)))
    for column, identifier in enumerate(coordinate_ids):
        full = np.zeros(len(actuator_ids))
        full[positions[identifier]] = PROBE_M
        synthesis = system.dm.opd_from_commands(DmCommandVector(values_opd_m=full, actuator_ids=actuator_ids, command_unit="m_opd_equivalent"))
        if float(synthesis.saturation_fraction) > 0.0:
            raise SystemExit("a probe command saturated the DM; the linear response cannot be read.")
        opd = np.asarray(synthesis.correction_opd_m, dtype=float)[pupil] / PROBE_M
        columns[:, column] = opd - np.mean(opd)
    return {"response": response, "interaction": dense, "pupil_response": columns, "row_ids": row_ids, "coordinate_ids": coordinate_ids, "n_pupil": n_pupil, "reconstructor_probe_s": probe_s}


def sigma_from_flat_wavefront(system: Any, row_ids: tuple[str, ...]) -> tuple[np.ndarray, dict[str, Any]]:
    quality = system.wfs.noise_model(np.zeros(system.wfs.geometry.pupil_shape))
    lenslets = tuple(system.wfs.subaperture_ids)
    rows = lenslet_rows(row_ids, lenslets)
    supported = np.asarray(quality.supported, dtype=bool)
    sigma_xy = np.asarray(quality.centroid_sigma_xy_px, dtype=float)
    if sigma_xy.shape != (len(lenslets), 2) or supported.shape != (len(lenslets),):
        raise SystemExit(f"the flat-wavefront model has shapes {sigma_xy.shape} and {supported.shape} for {len(lenslets)} lenslets.")
    covariance = getattr(quality, "centroid_covariance_xy_px2", None)
    sigma = np.zeros((len(row_ids), len(row_ids)))
    for lenslet in np.flatnonzero(supported):
        block = np.diag(sigma_xy[lenslet] ** 2) if covariance is None else np.asarray(covariance[lenslet], dtype=float)
        sigma[np.ix_(rows[lenslet], rows[lenslet])] = block
    return sigma, {
        "source": "flat_wavefront_model (detector_covariance_v2 at a flat wavefront; a-priori)",
        "xy_correlation_from_model": covariance is not None,
        "supported_lenslet_fraction": float(np.mean(supported)),
        "rows_with_noise": int(2 * np.count_nonzero(supported)),
        "mean_sigma_px_on_supported": float(np.mean(sigma_xy[supported])) if np.any(supported) else None,
    }


def read_sidecar_metadata(path: Path) -> dict[str, Any]:
    with np.load(path, allow_pickle=False) as archive:
        if "metadata_json" not in archive.files:
            raise SystemExit(f"{path}: no metadata_json entry.")
        metadata = json.loads(str(archive["metadata_json"]))
    if metadata.get("schema") not in ACCEPTED_SIDECAR_SCHEMAS:
        raise SystemExit(f"{path}: schema {metadata.get('schema')!r} is none of {ACCEPTED_SIDECAR_SCHEMAS}.")
    return metadata


def sigma_from_sidecar(path: Path, metadata: dict[str, Any], row_ids: tuple[str, ...], n_pupil: int, *, min_fraction: float) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """2x2 blocks per lenslet of the realized noisy-arm residuals under the ``strict`` and ``available`` support rules, and the measured series."""

    noisy = metadata["noisy_arm"]
    with np.load(path, allow_pickle=False) as archive:
        sidecar_rows = tuple(str(value) for value in archive["row_ids"])
        if sidecar_rows != row_ids:
            raise SystemExit(f"{path}: its rows are not the built system's rows.")
        lenslets = tuple(str(value) for value in archive[f"{noisy}__subaperture_ids"])
        frames = np.asarray(archive["analysed_frame_index"], dtype=int)
        centroids = archive[f"{noisy}__telemetry__centroids_xy_px"][frames]
        expected = archive[f"{noisy}__telemetry__expected_centroids_xy_px"][frames]
        valid = archive[f"{noisy}__telemetry__valid_subapertures"][frames]
        supported = archive[f"{noisy}__telemetry__uncertainty_supported"][frames]
        delta_v = np.asarray(archive["delta_v_m2"], dtype=float)
        msd = np.asarray(archive["mean_square_difference_m2"], dtype=float)
        saturation = np.asarray(archive[f"{noisy}__saturation_fraction"], dtype=float)[frames]
        twin_saturation = np.asarray(archive[f"{metadata['twin_arm']}__saturation_fraction"], dtype=float)[frames]
        usable = np.asarray(archive[f"{noisy}__reconstruction_usable"], dtype=bool)[frames]
        disagreement = np.asarray(archive["mask_disagreement_rows"], dtype=float)[frames]
        map_pupil = int(np.count_nonzero(archive["residual_maps__pupil_mask"])) if "residual_maps__pupil_mask" in archive.files else None
    rows = lenslet_rows(row_ids, lenslets)
    usable = valid & supported & np.all(np.isfinite(centroids), axis=2) & np.all(np.isfinite(expected), axis=2)
    fraction = np.mean(usable, axis=0)
    support = fraction >= 1.0
    available = fraction >= float(min_fraction)
    residual = centroids - expected
    sigma_strict = np.zeros((len(row_ids), len(row_ids)))
    for lenslet in np.flatnonzero(support):
        sigma_strict[np.ix_(rows[lenslet], rows[lenslet])] = np.cov(residual[:, lenslet, :], rowvar=False, ddof=1)
    sigma_available = np.zeros((len(row_ids), len(row_ids)))
    for lenslet in np.flatnonzero(available):
        frames_of = usable[:, lenslet]
        if np.count_nonzero(frames_of) >= 3:
            sigma_available[np.ix_(rows[lenslet], rows[lenslet])] = np.cov(residual[frames_of, lenslet, :], rowvar=False, ddof=1)
    blocks = int(len(delta_v) // 25)
    block_se = None if blocks < 2 else float(np.std(delta_v[: blocks * 25].reshape(blocks, 25).mean(axis=1), ddof=1) / np.sqrt(blocks))
    info = {
        "source": "sidecar_realized_residuals (c_noisy - c_expected on the noisy arm's support lenslets, ddof 1, 2x2 per lenslet)",
        "sidecar": str(path),
        "sidecar_schema": metadata["schema"],
        "label": metadata["label"],
        "root_seed": metadata["root_seed"],
        "config_hash": metadata["config_hash"],
        "analysed_frames": int(frames.size),
        "support_rules": {
            "strict": {"definition": "lenslets valid, supported and finite in every analysed frame (the E0 rule)", "lenslet_fraction": float(np.mean(support)), "rows_with_noise": int(2 * np.count_nonzero(support))},
            "available": {"definition": f"lenslets valid, supported and finite in at least {float(min_fraction):g} of the analysed frames; covariance over each lenslet's own valid frames", "min_fraction": float(min_fraction), "lenslet_fraction": float(np.mean(available)), "rows_with_noise": int(2 * np.count_nonzero(available)), "mean_valid_fraction_of_included": float(np.mean(fraction[available])) if np.any(available) else None},
        },
        "support_lenslet_fraction": float(np.mean(support)),
        "rows_with_noise": int(2 * np.count_nonzero(support)),
        "mean_realized_sigma_px_on_support": float(np.mean(np.sqrt(np.sum(residual[:, support, :] ** 2, axis=0) / (frames.size - 1)))) if np.any(support) else None,
        "measured_delta_v_mean_m2": float(np.mean(delta_v)),
        "measured_delta_v_block25_se_m2": block_se,
        "measured_mean_square_difference_mean_m2": float(np.mean(msd)),
        "noisy_arm_saturation_fraction_mean": float(np.mean(saturation)),
        "noisy_arm_frames_with_saturation": int(np.count_nonzero(saturation > 0.0)),
        "twin_arm_saturation_fraction_mean": float(np.mean(twin_saturation)),
        "noisy_arm_rejected_reconstructions": int(np.count_nonzero(~usable)),
        "mask_disagreement_row_frames_fraction": float(np.sum(disagreement) / (len(row_ids) * frames.size)),
        "residual_map_pupil_samples": map_pupil,
        "pupil_samples_equal_to_model": None if map_pupil is None else map_pupil == n_pupil,
    }
    return {"strict": sigma_strict, "available": sigma_available}, info


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    add_configuration_arguments(parser)
    parser.add_argument("--root-seed", type=int, help="root seed of the configuration (sidecar mode: taken from the sidecar when omitted, checked when given)")
    parser.add_argument("--n-steps", type=int, help="frame count of the configuration hash and of the window (sidecar mode: from the sidecar; default 400 otherwise)")
    parser.add_argument("--burn-in", type=int, default=100, help="first analysed frame of the window in flat mode (sidecar mode: from the sidecar)")
    parser.add_argument("--sigma", choices=("flat", "sidecar"), default="flat")
    parser.add_argument("--sidecar", type=Path, help="a traced sidecar of exactly this configuration (for --sigma sidecar)")
    parser.add_argument("--support", choices=("available", "strict"), default="available", help="which realized-covariance support rule is the primary prediction (sidecar mode; both are reported)")
    parser.add_argument("--support-min-fraction", type=float, default=0.9, help="inclusion threshold of the available rule (fraction of analysed frames a lenslet must be usable)")
    parser.add_argument("--max-state", type=int, default=4000, help="refuse a Lyapunov state larger than this (controlled actuators x (latency + 1))")
    parser.add_argument("--max-dense-mib", type=float, default=1024.0, help="refuse a dense pupil response larger than this")
    parser.add_argument("--self-test", action="store_true", help="check the solver against kappa in the unit-feedback limit and exit")
    parser.add_argument("--output", type=Path, required=True, help="JSON record path; never overwritten")
    parser.add_argument("--enabled-by-user", help="required for the 12 m and 42 m profiles (a system build at that scale is governed)")
    arguments = parser.parse_args(argv)
    if arguments.output.exists():
        raise SystemExit(f"{arguments.output} exists; nothing ran and nothing is overwritten.")
    if arguments.self_test:
        outcome = self_test()
        write_record_once(arguments.output, {"schema": SCHEMA, "mode": "self_test", **outcome})
        print(json.dumps({"self_test_passed": outcome["passed"], "cases": len(outcome["unit_feedback_cases"])}))
        return 0 if outcome["passed"] else 2
    if arguments.sigma == "sidecar" and arguments.sidecar is None:
        parser.error("--sigma sidecar needs --sidecar")

    metadata: dict[str, Any] | None = None
    root_seed, n_steps = arguments.root_seed, arguments.n_steps
    if arguments.sigma == "sidecar":
        metadata = read_sidecar_metadata(arguments.sidecar)
        if root_seed is not None and int(root_seed) != int(metadata["root_seed"]):
            raise SystemExit(f"--root-seed {root_seed} is not the sidecar's {metadata['root_seed']}.")
        if n_steps is not None and int(n_steps) != int(metadata["n_steps"]):
            raise SystemExit(f"--n-steps {n_steps} is not the sidecar's {metadata['n_steps']}.")
        root_seed, n_steps = int(metadata["root_seed"]), int(metadata["n_steps"])
    root_seed = 1 if root_seed is None else int(root_seed)
    n_steps = 400 if n_steps is None else int(n_steps)

    config, described, governed = configuration_from_arguments(arguments)
    if governed and not arguments.enabled_by_user:
        raise SystemExit(f"{described} is governed: pass --enabled-by-user; nothing ran.")
    config = run_configuration(config, root_seed=root_seed, n_steps=n_steps)
    if metadata is not None and config.config_hash != metadata["config_hash"]:
        raise SystemExit(f"the built configuration {config.config_hash[:16]} is not the sidecar's {metadata['config_hash'][:16]}: the sidecar was traced on another configuration.")
    controller = config.controller
    gain, leak, latency = float(controller.gain), float(controller.leak), int(controller.latency_frames)

    # Size before allocating: the pupil response and the Lyapunov state.
    pupil_estimate = int(0.8 * int(config.pupil_pixels) ** 2)
    actuator_estimate = int(config.actuators_across) ** 2
    dense_mib = pupil_estimate * actuator_estimate * 8 / 2**20
    if dense_mib > arguments.max_dense_mib:
        raise SystemExit(f"the dense pupil response would need about {dense_mib:.0f} MiB (> --max-dense-mib {arguments.max_dense_mib:g}); nothing was built.")
    if actuator_estimate * (latency + 1) > arguments.max_state:
        raise SystemExit(f"the Lyapunov state would have up to {actuator_estimate * (latency + 1)} rows (> --max-state {arguments.max_state}); nothing was built.")

    from shwfs_ao.experiments.scao import ScaoExecutionOptions, build_scao_system

    started = time.perf_counter()
    system = build_scao_system(config, execution=ScaoExecutionOptions(telemetry_level="summary"))
    build_s = time.perf_counter() - started
    parts = controlled_response(system)
    response, dense, pupil_response = parts["response"], parts["interaction"], parts["pupil_response"]
    row_ids, coordinate_ids, n_pupil = parts["row_ids"], parts["coordinate_ids"], parts["n_pupil"]
    if len(coordinate_ids) * (latency + 1) > arguments.max_state:
        raise SystemExit(f"the Lyapunov state has {len(coordinate_ids) * (latency + 1)} rows (> --max-state {arguments.max_state}).")
    loop = response @ dense
    eigen = np.linalg.eigvals(loop)
    real_eigen = np.sort(np.real(eigen))
    gram = pupil_response.T @ pupil_response
    if arguments.sigma == "flat":
        sigma_flat, sigma_info = sigma_from_flat_wavefront(system, row_ids)
        sigmas = {"flat": sigma_flat}
        primary_rule = "flat"
    else:
        sigmas, sigma_info = sigma_from_sidecar(arguments.sidecar, metadata, row_ids, n_pupil, min_fraction=arguments.support_min_fraction)
        primary_rule = arguments.support
    sigma_info["primary_rule"] = primary_rule
    burn_in = int(metadata["burn_in_frames"]) if metadata is not None else int(arguments.burn_in)
    size = len(coordinate_ids)
    # The series' propagation weights w_r = ||W_c R e_r||^2 / N and the scalar reduction kappa * sum_r w_r sigma_r^2.
    weights = np.einsum("ir,ij,jr->r", response, gram, response) / n_pupil
    kappa = scalar_kappa(gain, leak, latency)

    def predict(sigma: np.ndarray) -> dict[str, Any]:
        started = time.perf_counter()
        covariance, radius, lyapunov_residual = stationary_covariance(response, loop, sigma, gain=gain, leak=leak, latency=latency)
        stationary = float(np.trace(gram @ covariance) / n_pupil)
        diagonal_sigma = np.diag(np.diag(sigma))
        covariance_diagonal, _, _ = stationary_covariance(response, loop, diagonal_sigma, gain=gain, leak=leak, latency=latency)
        stationary_diagonal = float(np.trace(gram @ covariance_diagonal) / n_pupil)
        lyapunov_s = time.perf_counter() - started
        started = time.perf_counter()
        window_block, final_state = window_covariance(loop, forcing_matrix(response, sigma, gain=gain, latency=latency), gain=gain, leak=leak, latency=latency, n_steps=n_steps, burn_in=burn_in)
        window = float(np.trace(gram @ window_block) / n_pupil)
        window_block_diagonal, _ = window_covariance(loop, forcing_matrix(response, diagonal_sigma, gain=gain, latency=latency), gain=gain, leak=leak, latency=latency, n_steps=n_steps, burn_in=burn_in)
        window_diagonal = float(np.trace(gram @ window_block_diagonal) / n_pupil)
        window_s = time.perf_counter() - started
        scalar = float(kappa * np.sum(weights * np.diag(sigma)))
        one_step = float(np.trace(gram @ response @ sigma @ response.T) / n_pupil)
        return {
            "delta_v_exact_window_m2": window,
            "delta_v_exact_window_diagonal_sigma_m2": window_diagonal,
            "delta_v_exact_stationary_m2": stationary,
            "delta_v_exact_stationary_diagonal_sigma_m2": stationary_diagonal,
            "delta_v_scalar_reduction_m2": scalar,
            "delta_v_one_step_open_loop_m2": one_step,
            "window_over_stationary": window / stationary if stationary > 0 else None,
            "exact_window_over_scalar": window / scalar if scalar > 0 else None,
            "exact_stationary_over_scalar": stationary / scalar if scalar > 0 else None,
            "exact_window_over_diagonal_sigma": window / window_diagonal if window_diagonal > 0 else None,
            "window_end_over_stationary": float(np.trace(gram @ final_state[:size, :size]) / max(np.trace(gram @ covariance), 1e-300)),
            "spectral_radius_F": radius,
            "lyapunov_relative_residual": lyapunov_residual,
            "timing_s": {"lyapunov_two_solves": lyapunov_s, "window_two_propagations": window_s},
        }

    predictions = {rule: predict(sigma) for rule, sigma in sigmas.items()}
    primary = predictions[primary_rule]
    delta_v_exact = primary["delta_v_exact_window_m2"]
    delta_v_exact_diagonal = primary["delta_v_exact_window_diagonal_sigma_m2"]
    delta_v_stationary = primary["delta_v_exact_stationary_m2"]
    delta_v_stationary_diagonal = primary["delta_v_exact_stationary_diagonal_sigma_m2"]
    delta_v_scalar = primary["delta_v_scalar_reduction_m2"]
    delta_v_one_step = primary["delta_v_one_step_open_loop_m2"]
    radius, lyapunov_residual, final_fraction = primary["spectral_radius_F"], primary["lyapunov_relative_residual"], primary["window_end_over_stationary"]
    lyapunov_s, window_s = primary["timing_s"]["lyapunov_two_solves"], primary["timing_s"]["window_two_propagations"]
    record: dict[str, Any] = {
        "schema": SCHEMA,
        "mode": "model",
        "purpose": "analysis-only linear closed-loop noise model; no loop is run; no scientific claim by itself",
        "configuration": described,
        "diagnostic_alpha_override": arguments.alpha,
        "config_hash": config.config_hash,
        "root_seed": root_seed,
        "n_steps_in_hash": n_steps,
        "controller": {"gain": gain, "leak": leak, "latency_frames": latency},
        "reconstructor": {"kind": config.reconstructor.kind, "alpha": config.reconstructor.alpha, "rcond": config.reconstructor.rcond},
        "dimensions": {"rows": len(row_ids), "controlled_actuators": len(coordinate_ids), "pupil_samples": n_pupil, "lyapunov_state": len(coordinate_ids) * (latency + 1)},
        "feedback_spectrum": {
            "definition": "eigenvalues of L = R M on the controlled actuators (1 = unit feedback; below 1 = damped mode; the scalar model assumes all 1)",
            "min": float(real_eigen[0]), "percentile_10": float(np.percentile(real_eigen, 10)), "median": float(np.median(real_eigen)), "max": float(real_eigen[-1]),
            "fraction_below_0.9": float(np.mean(real_eigen < 0.9)), "fraction_below_0.5": float(np.mean(real_eigen < 0.5)),
            "max_abs_imaginary": float(np.max(np.abs(np.imag(eigen)))),
            "max_abs_deviation_of_L_from_identity": float(np.max(np.abs(loop - np.eye(len(coordinate_ids))))),
        },
        "stationarity": {"spectral_radius_F": radius, "lyapunov_relative_residual": lyapunov_residual, "window_end_over_stationary": final_fraction, "window_frames": [burn_in, n_steps]},
        "noise_covariance": jsonable(sigma_info),
        "prediction": {
            "units": "m2 (piston-removed pupil mean square of the noise-driven correction difference; the sidecar's delta_v_m2 in expectation)",
            "delta_v_exact_window_m2": delta_v_exact,
            "delta_v_exact_window_diagonal_sigma_m2": delta_v_exact_diagonal,
            "delta_v_exact_stationary_m2": delta_v_stationary,
            "delta_v_exact_stationary_diagonal_sigma_m2": delta_v_stationary_diagonal,
            "delta_v_scalar_reduction_m2": delta_v_scalar,
            "delta_v_one_step_open_loop_m2": delta_v_one_step,
            "scalar_kappa": kappa,
            "primary": f"delta_v_exact_window_m2 (transient from identical initial commands, averaged over the analysed frames; noise covariance rule {primary_rule!r})",
            "by_noise_covariance_rule": {rule: {key: value for key, value in entry.items() if key != "timing_s"} for rule, entry in predictions.items()},
            "window_over_stationary": delta_v_exact / delta_v_stationary if delta_v_stationary > 0 else None,
            "exact_window_over_scalar": delta_v_exact / delta_v_scalar if delta_v_scalar > 0 else None,
            "exact_stationary_over_scalar": delta_v_stationary / delta_v_scalar if delta_v_scalar > 0 else None,
            "exact_window_over_diagonal_sigma": delta_v_exact / delta_v_exact_diagonal if delta_v_exact_diagonal > 0 else None,
            "propagation_weights_sum_m2_per_px2": float(np.sum(weights)),
        },
        "timing": {"build_s": build_s, "reconstructor_probe_s": parts["reconstructor_probe_s"], "lyapunov_two_solves_s": lyapunov_s, "window_two_propagations_s": window_s},
        "ru_maxrss_bytes": peak_rss_bytes(),
        "host": {"platform": sys.platform, "machine": platform.machine(), "node": platform.node(), "python": sys.version, "numpy": np.__version__},
        "enabled_by_user": arguments.enabled_by_user,
    }
    measured = sigma_info.get("measured_delta_v_mean_m2")
    if measured is not None:
        se = sigma_info.get("measured_delta_v_block25_se_m2")
        record["comparison"] = {
            "measured_delta_v_mean_m2": measured,
            "measured_delta_v_block25_se_m2": se,
            "measured_over_exact_window": measured / delta_v_exact if delta_v_exact > 0 else None,
            "measured_over_exact_stationary": measured / delta_v_stationary if delta_v_stationary > 0 else None,
            "measured_over_exact_window_diagonal_sigma": measured / delta_v_exact_diagonal if delta_v_exact_diagonal > 0 else None,
            "measured_over_scalar": measured / delta_v_scalar if delta_v_scalar > 0 else None,
            "exact_window_within_2_block_se": None if se is None else bool(abs(measured - delta_v_exact) <= 2.0 * se),
            "measured_over_exact_window_by_rule": {rule: (measured / entry["delta_v_exact_window_m2"] if entry["delta_v_exact_window_m2"] > 0 else None) for rule, entry in predictions.items()},
            "note": "a pilot-level consistency check of the model against one run; the protocol's acceptance rules, not this ratio, decide anything",
        }
    write_record_once(arguments.output, record)
    print(json.dumps({"configuration": described, "controlled": len(coordinate_ids), "feedback_min": float(real_eigen[0]), "fraction_below_0.9": record["feedback_spectrum"]["fraction_below_0.9"],
                      "primary_rule": primary_rule, "delta_v_exact_window_nm2": delta_v_exact * 1e18, "delta_v_exact_stationary_nm2": delta_v_stationary * 1e18, "delta_v_scalar_nm2": delta_v_scalar * 1e18,
                      "window_over_stationary": record["prediction"]["window_over_stationary"], "exact_window_over_scalar": record["prediction"]["exact_window_over_scalar"],
                      "comparison": None if record.get("comparison") is None else {k: record["comparison"][k] for k in ("measured_over_exact_window", "measured_over_exact_window_by_rule", "exact_window_within_2_block_se")}}, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())
