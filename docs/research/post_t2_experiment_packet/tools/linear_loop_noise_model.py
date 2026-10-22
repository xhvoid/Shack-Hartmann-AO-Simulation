#!/usr/bin/env python3
"""Exact linear closed-loop detector-noise model with the reconstructed spatial feedback.

Proposed in the post-T2 experiment packet (review round 1, finding 3; revised
in round 2).  The scalar transfer factor ``kappa(g, l, d)`` of the first
draft assumed that the reconstructor feeds every DM mode back with unit gain.
The loop's actual feedback is the matrix ``L = R M`` (reconstructor times
calibrated interaction matrix on the controlled actuators); under Tikhonov or
LSMR damping its eigenvalues ``s_i^2 / (s_i^2 + damp^2)`` are below one for
poorly sensed modes, so those modes reject noise differently from the
unit-feedback loop, and the noise enters as ``R n``.  This tool computes the
covariance of the command difference between the noise-on loop and its
noiseless twin for the loop of technical reference 4.2 (leaky integrator,
gain ``g``, leak ``l``, queue latency ``d`` frames; ``controller.update``:
``c_{k+1} = (1 - l) c_k + g * released``, the released increment being the
one enqueued ``d`` updates earlier, the queue starting with ``d`` zeros):

    dc_{k+1} = (1 - l) dc_k - g L dc_{k-d} + g R n_{k-d}    (k >= d)
    dc_{k+1} = (1 - l) dc_k                                 (k <  d)

with ``n`` white measurement noise of covariance ``Sigma`` (2x2 blocks per
lenslet).  The two arms start from the same command, so ``P_0 = 0`` exactly
and the covariance of the run's frames is the transient
``P_{k+1} = F P_k F^T + [k >= d] G Sigma G^T`` for the state
``x_k = (dc_k, ..., dc_{k-d})``; the noise measured at frame ``k`` first
moves the command applied after update ``k + d``.  The model's prediction for
a run is the mean of ``tr(Gram P_{k+1}) / N_pupil`` over the analysed frames
(``delta_v_exact_window_m2``, the primary value: the post-update residual of
frame ``k`` carries ``dc_{k+1}``).  The stationary limit
``P = F P F^T + G Sigma G^T`` (discrete Lyapunov equation) is reported beside
it; the two differ when the loop has modes whose time constant is not short
against the run.  The predicted isolated detector-noise variance is

    DeltaV_pred = tr(Gram Cov(dc)) / N_pupil,   Gram = W_c^T W_c,

``W_c`` being the piston-removed DM response of each controlled actuator at
the pupil samples: the piston-removed pupil mean square of the noise-driven
correction difference, which is the sidecar's ``delta_v_m2`` in
expectation (the twin and the noisy arm see the same atmosphere).

**One fixed mask for the whole model.**  The reconstructor is probed with
exactly the rows that carry noise in ``Sigma`` marked valid and every other
row invalid (``R_mask``), so the feedback ``L = R_mask M``, the injection
``g R_mask n`` and ``Sigma`` describe the same fixed mask; probing with every
row valid while zeroing the noise of unused rows would mix two masks (review
round 2).  The series' propagation weights (every row valid) are kept for
the scalar reduction ``kappa * sum_r w_r sigma_r^2`` reported as the first
draft's value; the same reduction on the model's own mask is reported too.

Noise covariance (``--sigma``): ``flat`` uses the sensor's flat-wavefront
``detector_covariance_v2`` model on its supported lenslets (a-priori
prediction); ``sidecar`` uses a traced sidecar's realized residuals
``c_noisy - c_expected`` (``ddof = 1``) under two support rules, both
reported: ``available`` (primary by default) takes every lenslet that is
valid, supported and finite in at least ``--support-min-fraction`` of the
analysed frames and estimates its covariance over its own valid frames;
``strict`` takes only lenslets valid in every analysed frame (the E0
summary's rule).  A sidecar is validated before it is read as data: the
declared array table (names, dtypes, shapes), the frame domains, the
two-arm layout and the canonical interleaved x/y rows of one lenslet order,
the label and seed, and the configuration hash against the built
configuration; with ``--record`` (a series record) the run row's digest and
size are checked and the evidence runner's own ``validate_trace_payload``
runs; with ``--pilot-record`` the pilot's digest, size and frame counts are
checked.  The prediction is then compared with the sidecar's measured
``delta_v_m2`` (mean and 25-frame block standard error).  ``--self-test``
checks the solver against ``kappa`` in the unit-feedback limit, the delayed
injection and the structured propagation, and exits.

Building a 12 m or 42 m system is governed (``--enabled-by-user``).  The
dense ``W_c`` (pupil samples x controlled actuators) and the Lyapunov state
(controlled actuators x (d + 1)) are sized before anything is allocated and
refused above ``--max-dense-mib`` / ``--max-state``; the 42 m geometry is
out of reach of this tool.  Analysis only: no loop is run and nothing in the
repository is changed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys
import time
from typing import Any

import numpy as np
from scipy import linalg

# The shared helper lives beside this script; Python puts a script's own directory first on
# sys.path when the script is run by path, so no path manipulation is needed (lint rule).
from _packet_common import (
    add_configuration_arguments,
    configuration_from_arguments,
    jsonable,
    load_script_module,
    peak_rss_bytes,
    run_configuration,
    write_record_once,
)

SCHEMA = "post_t2_linear_loop_noise_model.v2"
PROBE_M = 1.0e-9
SERIES_SIDECAR_SCHEMA = "shwfs_ao.noise_isolation_trace_sidecar.v1"
PILOT_SIDECAR_SCHEMA = "post_t2_pilot_trace_sidecar.v1"
ACCEPTED_SIDECAR_SCHEMAS = (SERIES_SIDECAR_SCHEMA, PILOT_SIDECAR_SCHEMA)
PER_ARM_FRAME_ARRAYS = ("valid_measurement_fraction", "valid_subaperture_fraction", "saturation_fraction", "reconstruction_usable", "open_loop_opd_rms_m", "pre_update_residual_opd_rms_m", "post_update_residual_opd_rms_m")


class SidecarRefused(SystemExit):
    """The sidecar does not carry the trace semantics the model needs; nothing is read as data."""


class MaskRefused(ValueError):
    """The reconstructor refuses the support mask (its own valid-fraction or rank policy): the model is not defined for that rule."""


# -- loop algebra ------------------------------------------------------------------


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
    """Mean leading block of ``Cov(dc_{k+1})`` over the analysed frames ``burn_in <= k < n_steps``, and the final state.

    From ``P_0 = 0``: the update at frame ``k`` releases the increment
    enqueued ``d`` updates earlier, so the first ``d`` updates release the
    queue's initial zeros and the noise forcing enters only for ``k >= d``.
    """

    size = loop.shape[0]
    state = np.zeros_like(forcing)
    mean_block = np.zeros((size, size))
    analysed = 0
    for frame in range(n_steps):
        state = propagate(state, loop, gain=gain, leak=leak, latency=latency)
        if frame >= latency:
            state = state + forcing
        if frame >= burn_in:
            mean_block += state[:size, :size]
            analysed += 1
    mean_block /= max(analysed, 1)
    return 0.5 * (mean_block + mean_block.T), state


def stationary_covariance(response: np.ndarray, loop: np.ndarray, sigma: np.ndarray, *, gain: float, leak: float, latency: int) -> tuple[np.ndarray | None, float, float | None]:
    """Stationary ``Cov(dc)`` of the noise-driven command difference, the spectral radius of ``F`` and the Lyapunov residual.

    A mode the mask leaves unsensed with no leak has a unit pole: the
    spectral radius reaches one, no stationary covariance exists, and
    ``None`` is returned for it (the finite-window transient still exists
    and stays the primary prediction).
    """

    size = response.shape[0]
    transition = transition_matrix(loop, gain=gain, leak=leak, latency=latency)
    radius = float(np.max(np.abs(np.linalg.eigvals(transition))))
    if radius >= 1.0 - 1.0e-12:
        return None, radius, None
    forcing = forcing_matrix(response, sigma, gain=gain, latency=latency)
    covariance = linalg.solve_discrete_lyapunov(transition, forcing)
    covariance = 0.5 * (covariance + covariance.T)
    residual = float(np.linalg.norm(covariance - transition @ covariance @ transition.T - forcing) / max(np.linalg.norm(forcing), 1e-300))
    return covariance[:size, :size], radius, residual


def self_test() -> dict[str, Any]:
    """Unit feedback, one actuator, unit noise: the Lyapunov variance must be ``kappa``; plus the delay and the structure."""

    cases = []
    for gain, leak, latency in ((0.3, 0.0, 2), (0.2, 0.02, 2), (0.4, 0.0, 2), (0.5, 0.0, 0), (0.3, 0.0, 1)):
        covariance, radius, residual = stationary_covariance(np.eye(1), np.eye(1), np.eye(1), gain=gain, leak=leak, latency=latency)
        kappa = scalar_kappa(gain, leak, latency)
        cases.append({"gain": gain, "leak": leak, "latency": latency, "lyapunov_variance": float(covariance[0, 0]), "kappa": kappa, "relative_difference": float(covariance[0, 0] / kappa - 1.0), "spectral_radius": radius, "lyapunov_residual": residual})
    loop = np.diag([1.0, 0.5, 0.1])
    covariance, radius, _ = stationary_covariance(np.eye(3), loop, np.eye(3), gain=0.3, leak=0.0, latency=2)
    modal = []
    for index, feedback in enumerate((1.0, 0.5, 0.1)):
        single, _, _ = stationary_covariance(np.eye(1), np.eye(1) * feedback, np.eye(1), gain=0.3, leak=0.0, latency=2)
        modal.append({"feedback": feedback, "variance_in_3x3": float(covariance[index, index]), "variance_alone": float(single[0, 0])})
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
    # Delayed injection: with latency d the first d post-update covariances are exactly zero and the
    # (d+1)-th equals g^2 R Sigma R^T (the first released increment carries the frame-0 noise).
    delay_checks = []
    for latency in (0, 1, 2):
        zero_mean, state_d = window_covariance(np.eye(1), forcing_matrix(np.eye(1), np.eye(1), gain=0.3, latency=latency), gain=0.3, leak=0.0, latency=latency, n_steps=latency + 1, burn_in=0)
        first_nonzero = float(state_d[0, 0])
        expected_zero = float(zero_mean[0, 0]) * (latency + 1) - first_nonzero  # sum over the first d frames
        delay_checks.append({"latency": latency, "sum_of_first_d_variances": expected_zero, "variance_after_update_d": first_nonzero, "expected_after_update_d": 0.3**2})
    passed = (
        all(abs(case["relative_difference"]) < 1.0e-6 for case in cases)
        and all(abs(entry["variance_in_3x3"] / entry["variance_alone"] - 1.0) < 1.0e-9 for entry in modal)
        and propagation_error < 1.0e-12
        and abs(window_check["relative_difference"]) < 1.0e-6
        and all(abs(check["sum_of_first_d_variances"]) < 1.0e-15 and abs(check["variance_after_update_d"] - 0.3**2) < 1.0e-12 for check in delay_checks)
    )
    return {"unit_feedback_cases": cases, "decoupled_modes_gain_0.3_latency_2": modal, "structured_propagation_max_error": propagation_error, "window_mean_unit_feedback_400_100": window_check, "delayed_injection": delay_checks, "passed": bool(passed)}


# -- system responses --------------------------------------------------------------


def lenslet_rows(row_ids: tuple[str, ...], lenslet_ids: tuple[str, ...]) -> np.ndarray:
    """``(lenslets, 2)`` row indices of each lenslet's x and y rows, by identifier."""

    index = {identifier: position for position, identifier in enumerate(row_ids)}
    try:
        return np.array([[index[f"{lenslet}:x"], index[f"{lenslet}:y"]] for lenslet in lenslet_ids], dtype=int).reshape(len(lenslet_ids), 2)
    except KeyError as exc:
        raise SystemExit(f"row {exc} is not a measurement row of the built system; the lenslet identifiers do not match its rows.") from None


def reconstructor_matrix_masked(reconstructor: Any, row_ids: tuple[str, ...], valid_rows: np.ndarray, coordinate_ids: tuple[str, ...]) -> np.ndarray:
    """The reconstructor's linear map with exactly ``valid_rows`` valid (columns of invalid rows are zero)."""

    from shwfs_ao.core.types import MeasurementVector

    valid = np.asarray(valid_rows, dtype=bool)
    columns = np.zeros((len(coordinate_ids), len(row_ids)))
    for index in np.flatnonzero(valid):
        values = np.zeros(len(row_ids))
        values[index] = 1.0
        estimate = reconstructor.reconstruct(MeasurementVector(values=values, valid_rows=valid, row_ids=row_ids, measurement_unit="pixel"))
        if estimate is None:
            raise MaskRefused(f"the reconstructor refused the support mask ({int(np.count_nonzero(valid))} of {len(row_ids)} rows valid); the model is not defined for it")
        if tuple(estimate.coordinate_ids) != tuple(coordinate_ids):
            raise SystemExit("the reconstructor's coordinates are not the interaction matrix's controlled actuators.")
        columns[:, index] = np.asarray(estimate.delta_coordinates_opd_m, dtype=float)
    return columns


def system_parts(system: Any) -> dict[str, Any]:
    """``M`` (rows x controlled), the piston-removed pupil response ``W_c``, the identifiers and the pupil sample count."""

    from shwfs_ao.core.types import DmCommandVector

    matrix = system.interaction_matrix
    if matrix.coordinate_kind != "dm_command_opd":
        raise SystemExit(f"coordinate kind {matrix.coordinate_kind!r}: the model is defined for actuator-space reconstructors.")
    row_ids = tuple(system.wfs.row_ids)
    if tuple(matrix.row_ids) != row_ids:
        raise SystemExit("the interaction matrix rows are not the sensor's rows.")
    dense = np.asarray(matrix.matrix, dtype=float)
    coordinate_ids = tuple(matrix.coordinate_ids)
    if dense.shape != (len(row_ids), len(coordinate_ids)):
        raise SystemExit(f"shape mismatch: M {dense.shape}, rows {len(row_ids)}, controlled {len(coordinate_ids)}.")
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
    return {"interaction": dense, "pupil_response": columns, "row_ids": row_ids, "coordinate_ids": coordinate_ids, "n_pupil": n_pupil, "lenslet_ids": tuple(system.wfs.subaperture_ids)}


# -- noise covariance --------------------------------------------------------------


def sigma_from_flat_wavefront(system: Any, row_ids: tuple[str, ...]) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray], dict[str, Any]]:
    quality = system.wfs.noise_model(np.zeros(system.wfs.geometry.pupil_shape))
    lenslets = tuple(system.wfs.subaperture_ids)
    rows = lenslet_rows(row_ids, lenslets)
    supported = np.asarray(quality.supported, dtype=bool)
    sigma_xy = np.asarray(quality.centroid_sigma_xy_px, dtype=float)
    if sigma_xy.shape != (len(lenslets), 2) or supported.shape != (len(lenslets),):
        raise SystemExit(f"the flat-wavefront model has shapes {sigma_xy.shape} and {supported.shape} for {len(lenslets)} lenslets.")
    covariance = getattr(quality, "centroid_covariance_xy_px2", None)
    sigma = np.zeros((len(row_ids), len(row_ids)))
    mask = np.zeros(len(row_ids), dtype=bool)
    for lenslet in np.flatnonzero(supported):
        block = np.diag(sigma_xy[lenslet] ** 2) if covariance is None else np.asarray(covariance[lenslet], dtype=float)
        sigma[np.ix_(rows[lenslet], rows[lenslet])] = block
        mask[rows[lenslet]] = True
    info = {
        "source": "flat_wavefront_model (detector_covariance_v2 at a flat wavefront; a-priori)",
        "xy_correlation_from_model": covariance is not None,
        "support_rules": {"flat": {"definition": "lenslets the flat-wavefront model supports", "lenslet_fraction": float(np.mean(supported)), "rows_with_noise": int(np.count_nonzero(mask))}},
        "mean_sigma_px_on_supported": float(np.mean(sigma_xy[supported])) if np.any(supported) else None,
    }
    return {"flat": sigma}, {"flat": mask}, info


def load_sidecar(path: Path) -> tuple[dict[str, Any], dict[str, np.ndarray], str, int]:
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    with np.load(path, allow_pickle=False) as archive:
        names = set(archive.files)
        if "metadata_json" not in names:
            raise SidecarRefused(f"{path}: no metadata_json entry.")
        metadata = json.loads(str(archive["metadata_json"]))
        arrays = {name: archive[name] for name in names if name != "metadata_json"}
    if not isinstance(metadata, dict) or metadata.get("schema") not in ACCEPTED_SIDECAR_SCHEMAS:
        raise SidecarRefused(f"{path}: schema {metadata.get('schema') if isinstance(metadata, dict) else None!r} is none of {ACCEPTED_SIDECAR_SCHEMAS}.")
    return metadata, arrays, digest, len(payload)


def validate_sidecar(path: Path, metadata: dict[str, Any], arrays: dict[str, np.ndarray], *, expected_label: str | None, record: Path | None, pilot_record: Path | None, digest: str, size: int) -> dict[str, Any]:
    """Refuse a sidecar whose content does not carry the trace semantics the model reads; return what was checked."""

    from shwfs_ao.wfs.shack_hartmann.calibration import row_ids_for_subapertures

    def refuse(reason: str) -> None:
        raise SidecarRefused(f"{path.name}: {reason}; the sidecar is not read as data.")

    declared = metadata.get("arrays")
    if not isinstance(declared, dict) or set(declared) != set(arrays):
        refuse("the arrays present do not match the declared array table")
    for name, spec in declared.items():
        array = arrays[name]
        if str(array.dtype) != spec.get("dtype") or [int(s) for s in array.shape] != list(spec.get("shape", [])):
            refuse(f"array {name} has dtype {array.dtype} and shape {array.shape}, declared {spec.get('dtype')!r} {spec.get('shape')!r}")
    try:
        n_steps, burn_in = int(metadata["n_steps"]), int(metadata["burn_in_frames"])
    except (KeyError, TypeError, ValueError):
        refuse("no integer n_steps and burn_in_frames")
    if not (0 <= burn_in < n_steps):
        refuse(f"burn-in {burn_in} and n_steps {n_steps} are not a frame domain")
    if not np.array_equal(arrays.get("frame_index"), np.arange(n_steps)):
        refuse("frame_index is not 0..n_steps-1")
    if not np.array_equal(arrays.get("analysed_frame_index"), np.arange(burn_in, n_steps)):
        refuse("analysed_frame_index is not burn_in..n_steps-1")
    for name in ("delta_v_m2", "mean_square_difference_m2", "cross_term_m2"):
        if name not in arrays or arrays[name].shape != (n_steps - burn_in,) or arrays[name].dtype != np.float64 or not np.all(np.isfinite(arrays[name])):
            refuse(f"{name} is not a finite float64 series over the analysed frames")
    if not np.allclose(arrays["cross_term_m2"], arrays["mean_square_difference_m2"] - arrays["delta_v_m2"], rtol=0.0, atol=1e-30 + 1e-9 * np.max(np.abs(arrays["mean_square_difference_m2"]))):
        refuse("cross_term_m2 is not mean_square_difference_m2 minus delta_v_m2")
    if "mask_disagreement_rows" not in arrays or arrays["mask_disagreement_rows"].shape != (n_steps,):
        refuse("mask_disagreement_rows is not one count per frame")
    arm_order = list(metadata.get("arm_order", []))
    noisy, twin = metadata.get("noisy_arm"), metadata.get("twin_arm")
    if len(arm_order) != 2 or noisy not in arm_order or twin not in arm_order or noisy == twin or not str(noisy).startswith("noise_on"):
        refuse(f"arm order {arm_order!r} with noisy {noisy!r} and twin {twin!r} is not a two-arm paired trace")
    arms_meta = metadata.get("arms")
    if not isinstance(arms_meta, dict) or set(arms_meta) != set(arm_order):
        refuse("the per-arm metadata does not name exactly the two arms")
    if "row_ids" not in arrays or arrays["row_ids"].ndim != 1 or "calibration_valid_rows" not in arrays:
        refuse("no row layout (row_ids and calibration_valid_rows)")
    n_rows = int(arrays["row_ids"].shape[0])
    if arrays["calibration_valid_rows"].shape != (n_rows,):
        refuse("calibration_valid_rows does not cover the rows")
    first = arrays.get(f"{noisy}__subaperture_ids")
    if first is None or first.ndim != 1:
        refuse("no lenslet layout for the noisy arm")
    lenslet_ids = tuple(str(item) for item in first.tolist())
    n_lenslets = len(lenslet_ids)
    if len(set(lenslet_ids)) != n_lenslets or n_rows != 2 * n_lenslets:
        refuse(f"{n_rows} rows for {n_lenslets} lenslets (two canonical rows per distinct lenslet expected)")
    if tuple(str(item) for item in arrays["row_ids"].tolist()) != tuple(row_ids_for_subapertures(lenslet_ids)):
        refuse("row_ids are not the canonical interleaved x/y rows of the lenslet order")
    for arm in arm_order:
        if tuple(str(item) for item in arrays.get(f"{arm}__subaperture_ids", np.array([])).tolist()) != lenslet_ids:
            refuse(f"arm {arm} lists the lenslets in another order than the noisy arm")
        masks = arrays.get(f"{arm}__measurement_row_masks")
        if masks is None or masks.shape != (n_steps, n_rows) or masks.dtype != np.bool_:
            refuse(f"arm {arm} has no boolean row masks of shape (frames, rows)")
        for name in PER_ARM_FRAME_ARRAYS:
            array = arrays.get(f"{arm}__{name}")
            if array is None or array.shape != (n_steps,):
                refuse(f"arm {arm} has no per-frame {name}")
        for name in ("centroids_xy_px", "expected_centroids_xy_px"):
            array = arrays.get(f"{arm}__telemetry__{name}")
            if array is None or array.shape != (n_steps, n_lenslets, 2):
                refuse(f"arm {arm} has no {name} telemetry of shape (frames, lenslets, 2)")
        for name in ("valid_subapertures", "uncertainty_supported"):
            array = arrays.get(f"{arm}__telemetry__{name}")
            if array is None or array.shape != (n_steps, n_lenslets) or array.dtype != np.bool_:
                refuse(f"arm {arm} has no boolean {name} telemetry of shape (frames, lenslets)")
    if expected_label is not None and metadata.get("label") != expected_label:
        refuse(f"label {metadata.get('label')!r} is not the configuration's {expected_label!r}")
    if not isinstance(metadata.get("root_seed"), int) or not isinstance(metadata.get("config_hash"), str):
        refuse("no integer root seed or configuration hash")
    checked: dict[str, Any] = {"structural": "passed (declared table, frame domains, two-arm layout, canonical rows, label)", "schema": metadata["schema"]}
    if record is not None:
        if metadata["schema"] != SERIES_SIDECAR_SCHEMA:
            refuse("--record names a series record but the sidecar is not a series sidecar")
        series = json.loads(record.read_text())
        rows = [row for row in series.get("runs", []) if row.get("label") == metadata["label"] and row.get("root_seed") == metadata["root_seed"]]
        if len(rows) != 1:
            refuse(f"{len(rows)} run rows of {record.name} carry label {metadata['label']!r} and seed {metadata['root_seed']}")
        row = rows[0]
        reference = row.get("sidecar") or {}
        if reference.get("file") != path.name or reference.get("sha256") != digest or int(reference.get("bytes", -1)) != size:
            refuse(f"the record's sidecar reference ({reference.get('file')!r}, {str(reference.get('sha256'))[:12]}..., {reference.get('bytes')} B) does not match this file ({path.name}, {digest[:12]}..., {size} B)")
        if row.get("config_hash") != metadata["config_hash"] or int(row.get("n_steps", -1)) != n_steps or int(row.get("burn_in_frames", -1)) != burn_in:
            refuse("the record's run row disagrees with the sidecar's configuration hash or frame counts")
        evidence = load_script_module("run_detector_level_evidence")
        evidence.validate_trace_payload(
            metadata, arrays, label=metadata["label"], root_seed=metadata["root_seed"], n_steps=n_steps, burn_in=burn_in,
            diagnostic=row["diagnostic_protocol"], diagnostic_hash=row["diagnostic_protocol_hash"], where=f"{path.name} against {record.name}",
        )
        checked["record"] = {"path": str(record), "run_row": {"label": row["label"], "root_seed": row["root_seed"]}, "digest_and_size": "match", "runner_validate_trace_payload": "passed"}
    if pilot_record is not None:
        if metadata["schema"] != PILOT_SIDECAR_SCHEMA:
            refuse("--pilot-record names a pilot record but the sidecar is not a pilot sidecar")
        pilot = json.loads(pilot_record.read_text())
        reference = pilot.get("trace_sidecar") or {}
        if reference.get("file") != path.name or reference.get("sha256") != digest or int(reference.get("bytes", -1)) != size:
            refuse("the pilot record's trace_sidecar reference does not match this file")
        for key, value in (("config_hash", metadata["config_hash"]), ("n_steps", n_steps), ("burn_in_frames", burn_in), ("label", metadata["label"]), ("root_seed", metadata["root_seed"])):
            if pilot.get(key) != value:
                refuse(f"the pilot record's {key} ({pilot.get(key)!r}) is not the sidecar's ({value!r})")
        checked["pilot_record"] = {"path": str(pilot_record), "digest_size_hash_frames_label_seed": "match"}
    return checked


def recovery_acted(recovery: Any) -> bool:
    """The core's rule (``_recovery_acted``): any positive numeric counter in the recovery record other than its hash."""

    if not isinstance(recovery, dict):
        return False
    return any(isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 for key, value in recovery.items() if key != "config_hash")


def sigma_from_sidecar(metadata: dict[str, Any], arrays: dict[str, np.ndarray], row_ids: tuple[str, ...], n_pupil: int, *, min_fraction: float) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray], dict[str, Any]]:
    """2x2 blocks per lenslet of the realized noisy-arm residuals under the ``strict`` and ``available`` rules, their row masks, and the measured series."""

    noisy, twin = metadata["noisy_arm"], metadata["twin_arm"]
    sidecar_rows = tuple(str(value) for value in arrays["row_ids"])
    if sidecar_rows != row_ids:
        raise SidecarRefused("the sidecar's rows are not the built system's rows; the sidecar is not read as data.")
    lenslets = tuple(str(value) for value in arrays[f"{noisy}__subaperture_ids"])
    frames = np.asarray(arrays["analysed_frame_index"], dtype=int)
    centroids = arrays[f"{noisy}__telemetry__centroids_xy_px"][frames]
    expected = arrays[f"{noisy}__telemetry__expected_centroids_xy_px"][frames]
    valid = arrays[f"{noisy}__telemetry__valid_subapertures"][frames]
    supported = arrays[f"{noisy}__telemetry__uncertainty_supported"][frames]
    delta_v = np.asarray(arrays["delta_v_m2"], dtype=float)
    msd = np.asarray(arrays["mean_square_difference_m2"], dtype=float)
    rows = lenslet_rows(row_ids, lenslets)
    usable = valid & supported & np.all(np.isfinite(centroids), axis=2) & np.all(np.isfinite(expected), axis=2)
    fraction = np.mean(usable, axis=0)
    support = fraction >= 1.0
    available = fraction >= float(min_fraction)
    residual = centroids - expected
    sigmas: dict[str, np.ndarray] = {}
    masks: dict[str, np.ndarray] = {}
    for rule, lenslet_mask, own_frames in (("strict", support, False), ("available", available, True)):
        sigma = np.zeros((len(row_ids), len(row_ids)))
        mask = np.zeros(len(row_ids), dtype=bool)
        for lenslet in np.flatnonzero(lenslet_mask):
            frames_of = usable[:, lenslet] if own_frames else np.ones(frames.size, dtype=bool)
            if np.count_nonzero(frames_of) >= 3:
                sigma[np.ix_(rows[lenslet], rows[lenslet])] = np.cov(residual[frames_of, lenslet, :], rowvar=False, ddof=1)
                mask[rows[lenslet]] = True
        sigmas[rule], masks[rule] = sigma, mask
    blocks = int(len(delta_v) // 25)
    block_se = None if blocks < 2 else float(np.std(delta_v[: blocks * 25].reshape(blocks, 25).mean(axis=1), ddof=1) / np.sqrt(blocks))
    rejected = {arm: int(np.count_nonzero(~np.asarray(arrays[f"{arm}__reconstruction_usable"], dtype=bool)[frames])) for arm in (noisy, twin)}
    acted = {arm: recovery_acted(metadata.get("arms", {}).get(arm, {}).get("recovery")) for arm in (noisy, twin)}
    disagreement = np.asarray(arrays["mask_disagreement_rows"], dtype=float)[frames]
    map_pupil = int(np.count_nonzero(arrays["residual_maps__pupil_mask"])) if "residual_maps__pupil_mask" in arrays else None
    info = {
        "source": "sidecar_realized_residuals (c_noisy - c_expected on the noisy arm's lenslets, ddof 1, 2x2 per lenslet)",
        "sidecar_schema": metadata["schema"],
        "label": metadata["label"],
        "root_seed": metadata["root_seed"],
        "config_hash": metadata["config_hash"],
        "analysed_frames": int(frames.size),
        "support_rules": {
            "strict": {"definition": "lenslets valid, supported and finite in every analysed frame (the E0 rule); covariance over all analysed frames", "lenslet_fraction": float(np.mean(support)), "rows_with_noise": int(np.count_nonzero(masks["strict"]))},
            "available": {"definition": f"lenslets valid, supported and finite in at least {float(min_fraction):g} of the analysed frames; covariance over each lenslet's own valid frames", "min_fraction": float(min_fraction), "lenslet_fraction": float(np.mean(available)), "rows_with_noise": int(np.count_nonzero(masks["available"])), "mean_valid_fraction_of_included": float(np.mean(fraction[available])) if np.any(available) else None},
        },
        "mean_realized_sigma_px_on_strict_support": float(np.mean(np.sqrt(np.sum(residual[:, support, :] ** 2, axis=0) / (frames.size - 1)))) if np.any(support) else None,
        "measured_delta_v_mean_m2": float(np.mean(delta_v)),
        "measured_delta_v_block25_se_m2": block_se,
        "measured_mean_square_difference_mean_m2": float(np.mean(msd)),
        "noisy_arm_saturation_fraction_mean": float(np.mean(np.asarray(arrays[f"{noisy}__saturation_fraction"], dtype=float)[frames])),
        "noisy_arm_frames_with_saturation": int(np.count_nonzero(np.asarray(arrays[f"{noisy}__saturation_fraction"], dtype=float)[frames] > 0.0)),
        "twin_arm_saturation_fraction_mean": float(np.mean(np.asarray(arrays[f"{twin}__saturation_fraction"], dtype=float)[frames])),
        "rejected_frames_after_burn_in": rejected,
        "recovery_acted": acted,
        "gate_quiet_by_core_rule": bool(float(np.sum(disagreement)) / (len(row_ids) * frames.size) < 1.0e-3 and all(v == 0 for v in rejected.values()) and not any(acted.values())),
        "mask_disagreement_row_frames_fraction": float(np.sum(disagreement) / (len(row_ids) * frames.size)),
        "residual_map_pupil_samples": map_pupil,
        "pupil_samples_equal_to_model": None if map_pupil is None else map_pupil == n_pupil,
    }
    return sigmas, masks, info


# -- main ----------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    add_configuration_arguments(parser)
    parser.add_argument("--root-seed", type=int, help="root seed of the configuration (sidecar mode: taken from the sidecar when omitted, checked when given)")
    parser.add_argument("--n-steps", type=int, help="frame count of the configuration hash and of the window (sidecar mode: from the sidecar; default 400 otherwise)")
    parser.add_argument("--burn-in", type=int, default=100, help="first analysed frame of the window in flat mode (sidecar mode: from the sidecar)")
    parser.add_argument("--sigma", choices=("flat", "sidecar"), default="flat")
    parser.add_argument("--sidecar", type=Path, help="a traced sidecar of exactly this configuration (for --sigma sidecar)")
    parser.add_argument("--record", type=Path, help="the series record that references the sidecar (its digest, size and the runner's semantic validation are checked)")
    parser.add_argument("--pilot-record", type=Path, help="the timing pilot's record that references the sidecar (digest, size, frame counts, label, seed and hash are checked)")
    parser.add_argument("--support", choices=("available", "strict"), default="available", help="which realized-covariance support rule is the primary prediction (sidecar mode; both are reported)")
    parser.add_argument("--support-min-fraction", type=float, default=0.9, help="inclusion threshold of the available rule (fraction of analysed frames a lenslet must be usable)")
    parser.add_argument("--max-state", type=int, default=4000, help="refuse a Lyapunov state larger than this (controlled actuators x (latency + 1))")
    parser.add_argument("--max-dense-mib", type=float, default=1024.0, help="refuse a dense pupil response larger than this")
    parser.add_argument("--self-test", action="store_true", help="check the solver against kappa in the unit-feedback limit, the delayed injection and the structured propagation, and exit")
    parser.add_argument("--output", type=Path, required=True, help="JSON record path; never overwritten")
    parser.add_argument("--enabled-by-user", help="required for the 12 m and 42 m profiles (a system build at that scale is governed)")
    arguments = parser.parse_args(argv)
    if arguments.output.exists():
        raise SystemExit(f"{arguments.output} exists; nothing ran and nothing is overwritten.")
    if arguments.self_test:
        outcome = self_test()
        write_record_once(arguments.output, {"schema": SCHEMA, "mode": "self_test", **outcome})
        print(json.dumps({"self_test_passed": outcome["passed"], "cases": len(outcome["unit_feedback_cases"]), "delayed_injection_checked": [c["latency"] for c in outcome["delayed_injection"]]}))
        return 0 if outcome["passed"] else 2
    if arguments.sigma == "sidecar" and arguments.sidecar is None:
        parser.error("--sigma sidecar needs --sidecar")
    if arguments.record is not None and arguments.pilot_record is not None:
        parser.error("--record and --pilot-record are mutually exclusive")

    metadata: dict[str, Any] | None = None
    arrays: dict[str, np.ndarray] | None = None
    digest = size = None
    root_seed, n_steps = arguments.root_seed, arguments.n_steps
    if arguments.sigma == "sidecar":
        metadata, arrays, digest, size = load_sidecar(arguments.sidecar)
        if root_seed is not None and int(root_seed) != int(metadata.get("root_seed", -1)):
            raise SystemExit(f"--root-seed {root_seed} is not the sidecar's {metadata.get('root_seed')}.")
        if n_steps is not None and int(n_steps) != int(metadata.get("n_steps", -1)):
            raise SystemExit(f"--n-steps {n_steps} is not the sidecar's {metadata.get('n_steps')}.")
        root_seed, n_steps = int(metadata["root_seed"]), int(metadata["n_steps"])
    root_seed = 1 if root_seed is None else int(root_seed)
    n_steps = 400 if n_steps is None else int(n_steps)

    config, described, governed = configuration_from_arguments(arguments)
    if governed and not arguments.enabled_by_user:
        raise SystemExit(f"{described} is governed: pass --enabled-by-user; nothing ran.")
    config = run_configuration(config, root_seed=root_seed, n_steps=n_steps)
    magnitude = arguments.magnitude if arguments.magnitude is not None else (float(config.detector_physics.source.ab_magnitude) if config.detector_physics is not None and getattr(config.detector_physics.source, "ab_magnitude", None) is not None else None)
    expected_label = None if magnitude is None else f"m{magnitude:g}"
    validation: dict[str, Any] | None = None
    if metadata is not None:
        if config.config_hash != metadata["config_hash"]:
            raise SidecarRefused(f"the built configuration {config.config_hash[:16]} is not the sidecar's {metadata['config_hash'][:16]}: the sidecar was traced on another configuration; it is not read as data.")
        validation = validate_sidecar(arguments.sidecar, metadata, arrays, expected_label=expected_label, record=arguments.record, pilot_record=arguments.pilot_record, digest=digest, size=size)
    controller = config.controller
    gain, leak, latency = float(controller.gain), float(controller.leak), int(controller.latency_frames)

    pupil_estimate = int(0.8 * int(config.pupil_pixels) ** 2)
    actuator_estimate = int(config.actuators_across) ** 2
    dense_mib = pupil_estimate * actuator_estimate * 8 / 2**20
    if dense_mib > arguments.max_dense_mib:
        raise SystemExit(f"the dense pupil response would need about {dense_mib:.0f} MiB (> --max-dense-mib {arguments.max_dense_mib:g}); nothing was built.")
    if actuator_estimate * (latency + 1) > arguments.max_state:
        raise SystemExit(f"the Lyapunov state would have up to {actuator_estimate * (latency + 1)} rows (> --max-state {arguments.max_state}); nothing was built.")

    from shwfs_ao.experiments.detector_level import reconstructor_matrix
    from shwfs_ao.experiments.scao import ScaoExecutionOptions, build_scao_system

    started = time.perf_counter()
    system = build_scao_system(config, execution=ScaoExecutionOptions(telemetry_level="summary"))
    build_s = time.perf_counter() - started
    parts = system_parts(system)
    dense, pupil_response = parts["interaction"], parts["pupil_response"]
    row_ids, coordinate_ids, n_pupil = parts["row_ids"], parts["coordinate_ids"], parts["n_pupil"]
    size_c = len(coordinate_ids)
    if size_c * (latency + 1) > arguments.max_state:
        raise SystemExit(f"the Lyapunov state has {size_c * (latency + 1)} rows (> --max-state {arguments.max_state}).")
    gram = pupil_response.T @ pupil_response
    burn_in = int(metadata["burn_in_frames"]) if metadata is not None else int(arguments.burn_in)
    kappa = scalar_kappa(gain, leak, latency)

    if arguments.sigma == "flat":
        sigmas, masks, sigma_info = sigma_from_flat_wavefront(system, row_ids)
        primary_rule = "flat"
    else:
        sigmas, masks, sigma_info = sigma_from_sidecar(metadata, arrays, row_ids, n_pupil, min_fraction=arguments.support_min_fraction)
        primary_rule = arguments.support
    sigma_info["primary_rule"] = primary_rule
    if validation is not None:
        sigma_info["sidecar_validation"] = validation

    # The series' definition of the propagation weights: every row valid.
    started = time.perf_counter()
    response_full = reconstructor_matrix(system.reconstructor, row_ids)
    probe_full_s = time.perf_counter() - started
    weights_series = np.einsum("ir,ij,jr->r", response_full, gram, response_full) / n_pupil

    def predict(rule: str, sigma: np.ndarray, mask: np.ndarray) -> dict[str, Any]:
        started = time.perf_counter()
        if np.all(mask):
            response = response_full
            probe_check = 0.0
        else:
            try:
                response = reconstructor_matrix_masked(system.reconstructor, row_ids, mask, coordinate_ids)
            except MaskRefused as exc:
                return {"status": "not defined", "reason": str(exc), "rows_valid_in_mask": int(np.count_nonzero(mask)), "rows_total": int(len(mask))}
            probe_check = None
        probe_s = time.perf_counter() - started
        if probe_check is None and np.count_nonzero(mask) == len(mask):
            probe_check = float(np.max(np.abs(response - response_full)))
        loop = response @ dense
        eigen = np.linalg.eigvals(loop)
        real_eigen = np.sort(np.real(eigen))
        started = time.perf_counter()
        covariance, radius, lyapunov_residual = stationary_covariance(response, loop, sigma, gain=gain, leak=leak, latency=latency)
        diagonal_sigma = np.diag(np.diag(sigma))
        if covariance is None:
            stationary = stationary_diagonal = None
        else:
            stationary = float(np.trace(gram @ covariance) / n_pupil)
            covariance_diagonal, _, _ = stationary_covariance(response, loop, diagonal_sigma, gain=gain, leak=leak, latency=latency)
            stationary_diagonal = float(np.trace(gram @ covariance_diagonal) / n_pupil)
        lyapunov_s = time.perf_counter() - started
        started = time.perf_counter()
        window_block, final_state = window_covariance(loop, forcing_matrix(response, sigma, gain=gain, latency=latency), gain=gain, leak=leak, latency=latency, n_steps=n_steps, burn_in=burn_in)
        window = float(np.trace(gram @ window_block) / n_pupil)
        window_block_diagonal, _ = window_covariance(loop, forcing_matrix(response, diagonal_sigma, gain=gain, latency=latency), gain=gain, leak=leak, latency=latency, n_steps=n_steps, burn_in=burn_in)
        window_diagonal = float(np.trace(gram @ window_block_diagonal) / n_pupil)
        window_s = time.perf_counter() - started
        weights_mask = np.einsum("ir,ij,jr->r", response, gram, response) / n_pupil
        scalar_mask = float(kappa * np.sum(weights_mask * np.diag(sigma)))
        scalar_series = float(kappa * np.sum(weights_series * np.diag(sigma)))
        one_step = float(np.trace(gram @ response @ sigma @ response.T) / n_pupil)
        return {
            "status": "defined",
            "rows_valid_in_mask": int(np.count_nonzero(mask)),
            "rows_total": int(len(mask)),
            "feedback_spectrum": {
                "definition": "eigenvalues of L = R_mask M on the controlled actuators (1 = unit feedback; below 1 = damped mode; the scalar model assumes all 1)",
                "min": float(real_eigen[0]), "percentile_10": float(np.percentile(real_eigen, 10)), "median": float(np.median(real_eigen)), "max": float(real_eigen[-1]),
                "fraction_below_0.9": float(np.mean(real_eigen < 0.9)), "fraction_below_0.5": float(np.mean(real_eigen < 0.5)),
                "count_below_1e-6": int(np.count_nonzero(real_eigen < 1.0e-6)),
                "unsensed_modes_note": "a mode with feedback below 1e-6 is left unsensed by this mask; with no leak it has a unit pole, no stationary limit exists and the window prediction grows with the run length (the run is support-sensitive)",
                "max_abs_imaginary": float(np.max(np.abs(np.imag(eigen)))),
                "max_abs_deviation_of_L_from_identity": float(np.max(np.abs(loop - np.eye(size_c)))),
            },
            "stationarity": {"spectral_radius_F": radius, "stationary_limit_exists": covariance is not None, "lyapunov_relative_residual": lyapunov_residual, "window_end_over_stationary": None if covariance is None else float(np.trace(gram @ final_state[:size_c, :size_c]) / max(np.trace(gram @ covariance), 1e-300)), "note": None if covariance is not None else "a mode the mask leaves unsensed has a unit pole (no leak): no stationary covariance; the finite-window prediction is the primary quantity"},
            "delta_v_exact_window_m2": window,
            "delta_v_exact_window_diagonal_sigma_m2": window_diagonal,
            "delta_v_exact_stationary_m2": stationary,
            "delta_v_exact_stationary_diagonal_sigma_m2": stationary_diagonal,
            "delta_v_scalar_reduction_mask_m2": scalar_mask,
            "delta_v_scalar_reduction_series_weights_m2": scalar_series,
            "delta_v_one_step_open_loop_m2": one_step,
            "window_over_stationary": None if stationary is None or stationary <= 0 else window / stationary,
            "exact_window_over_scalar_mask": window / scalar_mask if scalar_mask > 0 else None,
            "exact_window_over_scalar_series_weights": window / scalar_series if scalar_series > 0 else None,
            "exact_window_over_diagonal_sigma": window / window_diagonal if window_diagonal > 0 else None,
            "masked_probe_equals_full_probe_when_all_valid": probe_check,
            "timing_s": {"reconstructor_probe": probe_s, "lyapunov_two_solves": lyapunov_s, "window_two_propagations": window_s},
        }

    predictions = {rule: predict(rule, sigmas[rule], masks[rule]) for rule in sigmas}
    primary = predictions[primary_rule]
    if primary.get("status") != "defined":
        defined = {rule: entry for rule, entry in predictions.items() if entry.get("status") == "defined"}
        record_undefined: dict[str, Any] = {
            "schema": SCHEMA, "mode": "model", "purpose": "analysis-only linear closed-loop noise model; no loop is run; no scientific claim by itself",
            "configuration": described, "diagnostic_alpha_override": arguments.alpha, "config_hash": config.config_hash, "root_seed": root_seed, "n_steps_in_hash": n_steps, "window_frames": [burn_in, n_steps],
            "controller": {"gain": gain, "leak": leak, "latency_frames": latency},
            "reconstructor": {"kind": config.reconstructor.kind, "alpha": config.reconstructor.alpha, "rcond": config.reconstructor.rcond, "min_valid_fraction": config.reconstructor.min_valid_fraction},
            "dimensions": {"rows": len(row_ids), "controlled_actuators": size_c, "pupil_samples": n_pupil},
            "noise_covariance": jsonable(sigma_info),
            "prediction": {"primary_status": "not defined", "primary_rule": primary_rule, "reason": primary["reason"], "by_noise_covariance_rule": {rule: {key: value for key, value in entry.items() if key != "timing_s"} for rule, entry in predictions.items()}, "note": "the reconstructor refuses the primary rule's support mask under its own valid-fraction or rank policy, so the fixed-mask model is not defined for this run; such a run is gate-active in the loop as well"},
            "timing": {"build_s": build_s, "full_probe_s": probe_full_s}, "ru_maxrss_bytes": peak_rss_bytes(),
            "host": {"platform": sys.platform, "machine": platform.machine(), "node": platform.node(), "python": sys.version, "numpy": np.__version__}, "enabled_by_user": arguments.enabled_by_user,
        }
        if defined:
            record_undefined["prediction"]["defined_rules"] = sorted(defined)
        write_record_once(arguments.output, record_undefined)
        print(json.dumps({"configuration": described, "primary_rule": primary_rule, "primary_status": "not defined", "reason": primary["reason"], "defined_rules": sorted(defined)}))
        return 0
    record: dict[str, Any] = {
        "schema": SCHEMA,
        "mode": "model",
        "purpose": "analysis-only linear closed-loop noise model; no loop is run; no scientific claim by itself",
        "configuration": described,
        "diagnostic_alpha_override": arguments.alpha,
        "config_hash": config.config_hash,
        "root_seed": root_seed,
        "n_steps_in_hash": n_steps,
        "window_frames": [burn_in, n_steps],
        "controller": {"gain": gain, "leak": leak, "latency_frames": latency},
        "reconstructor": {"kind": config.reconstructor.kind, "alpha": config.reconstructor.alpha, "rcond": config.reconstructor.rcond, "min_valid_fraction": config.reconstructor.min_valid_fraction},
        "dimensions": {"rows": len(row_ids), "controlled_actuators": size_c, "pupil_samples": n_pupil, "lyapunov_state": size_c * (latency + 1)},
        "mask_rule": "the reconstructor is probed with exactly the rows that carry noise valid (one fixed mask for L, the injection and Sigma); the series' all-valid propagation weights are kept for the first draft's scalar value",
        "feedback_spectrum": primary["feedback_spectrum"],
        "stationarity": primary["stationarity"],
        "noise_covariance": jsonable(sigma_info),
        "prediction": {
            "units": "m2 (piston-removed pupil mean square of the noise-driven correction difference; the sidecar's delta_v_m2 in expectation)",
            "primary": f"delta_v_exact_window_m2 (transient from identical initial commands with the noise entering after the latency, averaged over the analysed frames; noise covariance rule {primary_rule!r})",
            "delta_v_exact_window_m2": primary["delta_v_exact_window_m2"],
            "delta_v_exact_window_diagonal_sigma_m2": primary["delta_v_exact_window_diagonal_sigma_m2"],
            "delta_v_exact_stationary_m2": primary["delta_v_exact_stationary_m2"],
            "delta_v_scalar_reduction_mask_m2": primary["delta_v_scalar_reduction_mask_m2"],
            "delta_v_scalar_reduction_series_weights_m2": primary["delta_v_scalar_reduction_series_weights_m2"],
            "delta_v_one_step_open_loop_m2": primary["delta_v_one_step_open_loop_m2"],
            "scalar_kappa": kappa,
            "window_over_stationary": primary["window_over_stationary"],
            "exact_window_over_scalar_mask": primary["exact_window_over_scalar_mask"],
            "exact_window_over_scalar_series_weights": primary["exact_window_over_scalar_series_weights"],
            "exact_window_over_diagonal_sigma": primary["exact_window_over_diagonal_sigma"],
            "propagation_weights_series_sum_m2_per_px2": float(np.sum(weights_series)),
            "by_noise_covariance_rule": {rule: {key: value for key, value in entry.items() if key != "timing_s"} for rule, entry in predictions.items()},
        },
        "timing": {"build_s": build_s, "full_probe_s": probe_full_s, **{f"{rule}_s": entry.get("timing_s") for rule, entry in predictions.items()}},
        "ru_maxrss_bytes": peak_rss_bytes(),
        "host": {"platform": sys.platform, "machine": platform.machine(), "node": platform.node(), "python": sys.version, "numpy": np.__version__},
        "enabled_by_user": arguments.enabled_by_user,
    }
    measured = sigma_info.get("measured_delta_v_mean_m2")
    if measured is not None:
        se = sigma_info.get("measured_delta_v_block25_se_m2")
        window = primary["delta_v_exact_window_m2"]
        record["comparison"] = {
            "measured_delta_v_mean_m2": measured,
            "measured_delta_v_block25_se_m2": se,
            "measured_over_exact_window": measured / window if window > 0 else None,
            "measured_over_exact_stationary": None if primary["delta_v_exact_stationary_m2"] is None or primary["delta_v_exact_stationary_m2"] <= 0 else measured / primary["delta_v_exact_stationary_m2"],
            "measured_over_scalar_mask": measured / primary["delta_v_scalar_reduction_mask_m2"] if primary["delta_v_scalar_reduction_mask_m2"] > 0 else None,
            "measured_over_scalar_series_weights": measured / primary["delta_v_scalar_reduction_series_weights_m2"] if primary["delta_v_scalar_reduction_series_weights_m2"] > 0 else None,
            "exact_window_within_2_block_se": None if se is None else bool(abs(measured - window) <= 2.0 * se),
            "measured_over_exact_window_by_rule": {rule: (None if entry.get("status") != "defined" or entry["delta_v_exact_window_m2"] <= 0 else measured / entry["delta_v_exact_window_m2"]) for rule, entry in predictions.items()},
            "note": "a pilot-level consistency check of the model against one run; the protocol's acceptance rules, not this ratio, decide anything",
        }
    write_record_once(arguments.output, record)
    print(json.dumps({"configuration": described, "controlled": size_c, "primary_rule": primary_rule, "rows_in_mask": primary["rows_valid_in_mask"], "feedback_min": primary["feedback_spectrum"]["min"], "fraction_below_0.9": primary["feedback_spectrum"]["fraction_below_0.9"],
                      "delta_v_exact_window_nm2": primary["delta_v_exact_window_m2"] * 1e18, "delta_v_exact_stationary_nm2": None if primary["delta_v_exact_stationary_m2"] is None else primary["delta_v_exact_stationary_m2"] * 1e18, "delta_v_scalar_mask_nm2": primary["delta_v_scalar_reduction_mask_m2"] * 1e18,
                      "sidecar_validation": None if validation is None else {k: v for k, v in validation.items() if k != "structural"} | {"structural": "passed"},
                      "comparison": None if record.get("comparison") is None else {k: record["comparison"][k] for k in ("measured_over_exact_window", "measured_over_exact_window_by_rule", "exact_window_within_2_block_se")}}, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())
