#!/usr/bin/env python3
"""Exact linear closed-loop detector-noise model with the reconstructed spatial feedback.

Proposed in the post-T2 experiment packet (review round 1, finding 3; revised
in rounds 2 and 3).  The scalar transfer factor ``kappa(g, l, d)`` of the
first draft assumed that the reconstructor feeds every DM mode back with
unit gain.  The loop's actual feedback is the matrix ``L = R M``
(reconstructor times calibrated interaction matrix on the controlled
actuators); under Tikhonov or LSMR damping its eigenvalues
``s_i^2 / (s_i^2 + damp^2)`` are below one for poorly sensed modes, so those
modes reject noise differently from the unit-feedback loop, and the noise
enters as ``R n``.  This tool computes the covariance of the command
difference between the noise-on loop and its noiseless twin for the loop of
technical reference 4.2 (leaky integrator, gain ``g``, leak ``l``, queue
latency ``d`` frames; ``controller.update``: ``c_{k+1} = (1 - l) c_k + g *
released``, the released increment being the one enqueued ``d`` updates
earlier, the queue starting with ``d`` zeros):

    dc_{k+1} = (1 - l) dc_k - g L dc_{k-d} + g R n_{k-d}    (k >= d)
    dc_{k+1} = (1 - l) dc_k                                 (k <  d)

with ``n`` white measurement noise of covariance ``Sigma`` (2x2 blocks per
lenslet).  The two arms start from the same command, so ``P_0 = 0`` exactly
and the covariance of the run's frames is the transient
``P_{k+1} = F P_k F^T + [k >= d] G Sigma G^T`` for the state
``x_k = (dc_k, ..., dc_{k-d})``.  The model's prediction for a run is the
mean of ``tr(Gram P_{k+1}) / N_pupil`` over the analysed frames
(``delta_v_exact_window_m2``, the primary value: the post-update residual of
frame ``k`` carries ``dc_{k+1}``).  The stationary limit (discrete Lyapunov
equation) is reported beside it when it exists.  The predicted isolated
detector-noise variance is

    DeltaV_pred = tr(Gram Cov(dc)) / N_pupil,   Gram = W_c^T W_c,

``W_c`` being the piston-removed DM response of each controlled actuator at
the pupil samples: the piston-removed pupil mean square of the noise-driven
correction difference, which is the sidecar's ``delta_v_m2`` in
expectation (the twin and the noisy arm see the same atmosphere).

**The operator the loop used.**  The model is a fixed-mask model: ``R`` is
probed with exactly one row set valid and every other row invalid, and
``L``, the injection and ``Sigma`` describe that one mask.  The primary
rule ``effective`` takes the row set the noisy arm's reconstructor actually
used in the plurality of analysed frames (the sidecar's per-frame effective
row masks), estimates ``Sigma`` from the realized residuals of the frames in
which that operator was in use, and reports in how many analysed frames
each arm used it (``operator.noisy_match_fraction``,
``twin_match_fraction``).  A run in which either arm used the modal operator
in fewer than ``--min-operator-match`` of the analysed frames is
``mask-variable``: the loop had no single operator, the prediction is
reported, and the comparison is descriptive (review round 3).  Two
telemetry-based rules are reported as sensitivities: ``available``
(lenslets valid, supported and finite in at least ``--support-min-fraction``
of the analysed frames, covariance over each lenslet's own valid frames) and
``strict`` (lenslets valid in every analysed frame, the E0 rule).  ``flat``
uses the sensor's flat-wavefront ``detector_covariance_v2`` model on its
supported lenslets (a-priori, no run needed).  The series' propagation
weights (every row valid) are kept for the first draft's scalar value
``kappa * sum_r w_r sigma_r^2``; the same reduction on the model's own mask
is reported too.

**Validation before any read.**  A sidecar's declared array table is
compared, array by array, with the evidence runner's canonical layout
(names, units, axes and meanings as the runner declares them, the dtype of
each array, and the shape its axes imply from the frame, row, lenslet and
pupil-sample counts); the frame domains, the two-arm layout, the canonical
interleaved x/y rows of one lenslet order, the label, the seed and the
configuration hash against the built configuration are checked; with
``--record`` (a series record) the run row's digest and size are checked and
the runner's own ``validate_trace_payload`` runs; with ``--pilot-record``
the pilot's digest, size, frame counts, label, seed and hash are checked.  A
refusal reads nothing.  ``--self-test`` checks the solver against ``kappa``
in the unit-feedback limit, the delayed injection and the structured
propagation, and exits.

Building a 12 m or 42 m system is governed (``--enabled-by-user``).  The
dense ``W_c`` and the Lyapunov state are sized before anything is allocated
and refused above ``--max-dense-mib`` / ``--max-state``; the 42 m geometry
is out of reach of this tool.  Analysis only: no loop is run and nothing in
the repository is changed.
"""

from __future__ import annotations

import argparse
from collections import Counter
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

SCHEMA = "post_t2_linear_loop_noise_model.v3"
PROBE_M = 1.0e-9
SERIES_SIDECAR_SCHEMA = "shwfs_ao.noise_isolation_trace_sidecar.v1"
PILOT_SIDECAR_SCHEMA = "post_t2_pilot_trace_sidecar.v1"
ACCEPTED_SIDECAR_SCHEMAS = (SERIES_SIDECAR_SCHEMA, PILOT_SIDECAR_SCHEMA)
RULES = ("effective", "available", "strict")
# The dtype the experiment core writes for each canonical array ("U" = fixed-width unicode).
CANONICAL_DTYPES = {
    "frame_index": "int64", "analysed_frame_index": "int64", "delta_v_m2": "float64", "mean_square_difference_m2": "float64",
    "cross_term_m2": "float64", "mask_disagreement_rows": "int64", "calibration_valid_rows": "bool", "row_ids": "U",
    "measurement_row_masks": "bool", "valid_measurement_fraction": "float64", "valid_subaperture_fraction": "float64",
    "saturation_fraction": "float64", "reconstruction_usable": "bool", "open_loop_opd_rms_m": "float64",
    "pre_update_residual_opd_rms_m": "float64", "post_update_residual_opd_rms_m": "float64", "subaperture_ids": "U",
    "centroids_xy_px": "float64", "expected_centroids_xy_px": "float64", "centroid_sigma_xy_px": "float64", "fluxes_e": "float64",
    "peak_snr": "float64", "total_snr": "float64", "centroid_sigma_px": "float64", "clipping_fraction": "float64",
    "centroid_calibration_sigma_px": "float64", "masked_pixel_fraction": "float64", "saturated_pixel_count": "float64",
    "valid_subapertures": "bool", "valid_by_flux": "bool", "valid_by_snr": "bool", "valid_by_uncertainty": "bool",
    "valid_by_clipping": "bool", "uncertainty_supported": "bool", "propagation_weights__weights_m2_per_px2": "float64",
    "residual_maps__pupil_mask": "bool", "residual_maps__arm": "float32", "mask_lock__rows_removed": "int64",
    "mask_lock__rows_added": "int64", "mask_lock__rows_unaddable": "int64", "mask_lock__own_valid_subapertures": "bool",
}
REQUIRED_SHARED = ("frame_index", "analysed_frame_index", "delta_v_m2", "mean_square_difference_m2", "cross_term_m2", "mask_disagreement_rows", "calibration_valid_rows", "row_ids")
REQUIRED_HISTORY = ("measurement_row_masks", "valid_measurement_fraction", "valid_subaperture_fraction", "saturation_fraction", "reconstruction_usable", "open_loop_opd_rms_m", "pre_update_residual_opd_rms_m", "post_update_residual_opd_rms_m", "subaperture_ids")
REQUIRED_TELEMETRY = ("centroids_xy_px", "expected_centroids_xy_px", "valid_subapertures", "uncertainty_supported")


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
    """Stationary ``Cov(dc)``, the spectral radius of ``F`` and the Lyapunov residual; ``None`` when a unit pole leaves no stationary limit."""

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
    delay_checks = []
    for latency in (0, 1, 2):
        zero_mean, state_d = window_covariance(np.eye(1), forcing_matrix(np.eye(1), np.eye(1), gain=0.3, latency=latency), gain=0.3, leak=0.0, latency=latency, n_steps=latency + 1, burn_in=0)
        first_nonzero = float(state_d[0, 0])
        delay_checks.append({"latency": latency, "sum_of_first_d_variances": float(zero_mean[0, 0]) * (latency + 1) - first_nonzero, "variance_after_update_d": first_nonzero, "expected_after_update_d": 0.3**2})
    unit_pole = stationary_covariance(np.eye(1), np.zeros((1, 1)), np.eye(1), gain=0.3, leak=0.0, latency=2)
    passed = (
        all(abs(case["relative_difference"]) < 1.0e-6 for case in cases)
        and all(abs(entry["variance_in_3x3"] / entry["variance_alone"] - 1.0) < 1.0e-9 for entry in modal)
        and propagation_error < 1.0e-12
        and abs(window_check["relative_difference"]) < 1.0e-6
        and all(abs(check["sum_of_first_d_variances"]) < 1.0e-15 and abs(check["variance_after_update_d"] - 0.3**2) < 1.0e-12 for check in delay_checks)
        and unit_pole[0] is None and abs(unit_pole[1] - 1.0) < 1.0e-12
    )
    return {"unit_feedback_cases": cases, "decoupled_modes_gain_0.3_latency_2": modal, "structured_propagation_max_error": propagation_error, "window_mean_unit_feedback_400_100": window_check, "delayed_injection": delay_checks, "unsensed_mode_has_no_stationary_limit": {"stationary_returned": unit_pole[0], "spectral_radius": unit_pole[1]}, "passed": bool(passed)}


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


# -- sidecar validation --------------------------------------------------------------


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


def canonical_layout(name: str, arm_order: list[str], runner: Any) -> tuple[str, str, tuple[str, ...], str]:
    """``(units, meaning, axes, dtype)`` the evidence runner declares for a sidecar array name; raises ``KeyError`` for an unknown name."""

    if name in runner._SIDECAR_SHARED_ARRAYS:
        unit, meaning, axes = runner._SIDECAR_SHARED_ARRAYS[name]
        return unit, meaning, tuple(axes), CANONICAL_DTYPES[name]
    for table in (runner._SIDECAR_WEIGHT_ARRAYS, runner._SIDECAR_MAP_ARRAYS, runner._SIDECAR_LOCK_ARRAYS):
        if name in table:
            unit, meaning, axes = table[name]
            return unit, meaning, tuple(axes), CANONICAL_DTYPES[name]
    if name.startswith("residual_maps__") and name[len("residual_maps__"):] in arm_order:
        unit, meaning, axes = runner._SIDECAR_RESIDUAL_MAP_ARM
        return unit, meaning, tuple(axes), CANONICAL_DTYPES["residual_maps__arm"]
    arm, _, rest = name.partition("__")
    if arm in arm_order:
        if rest.startswith("telemetry__"):
            field = rest[len("telemetry__"):]
            unit, meaning, axes = runner._SIDECAR_TELEMETRY_ARRAYS[field]
            return unit, meaning, tuple(axes), CANONICAL_DTYPES[field]
        unit, meaning, axes = runner._SIDECAR_HISTORY_ARRAYS[rest]
        return unit, meaning, tuple(axes), CANONICAL_DTYPES[rest]
    raise KeyError(name)


def validate_sidecar(path: Path, metadata: dict[str, Any], arrays: dict[str, np.ndarray], *, expected_label: str | None, record: Path | None, pilot_record: Path | None, digest: str, size: int) -> dict[str, Any]:
    """Refuse a sidecar whose content does not carry the trace semantics the model reads; return what was checked."""

    from shwfs_ao.wfs.shack_hartmann.calibration import row_ids_for_subapertures

    runner = load_script_module("run_detector_level_evidence")

    def refuse(reason: str) -> None:
        raise SidecarRefused(f"{path.name}: {reason}; the sidecar is not read as data.")

    try:
        n_steps, burn_in = int(metadata["n_steps"]), int(metadata["burn_in_frames"])
    except (KeyError, TypeError, ValueError):
        refuse("no integer n_steps and burn_in_frames")
    if not (0 <= burn_in < n_steps):
        refuse(f"burn-in {burn_in} and n_steps {n_steps} are not a frame domain")
    arm_order = list(metadata.get("arm_order", []))
    noisy, twin = metadata.get("noisy_arm"), metadata.get("twin_arm")
    if len(arm_order) != 2 or noisy not in arm_order or twin not in arm_order or noisy == twin or not str(noisy).startswith("noise_on"):
        refuse(f"arm order {arm_order!r} with noisy {noisy!r} and twin {twin!r} is not a two-arm paired trace")
    arms_meta = metadata.get("arms")
    if not isinstance(arms_meta, dict) or set(arms_meta) != set(arm_order):
        refuse("the per-arm metadata does not name exactly the two arms")
    declared = metadata.get("arrays")
    if not isinstance(declared, dict) or set(declared) != set(arrays):
        refuse("the arrays present do not match the declared array table")
    missing = [name for name in REQUIRED_SHARED if name not in arrays]
    missing += [f"{arm}__{name}" for arm in arm_order for name in REQUIRED_HISTORY if f"{arm}__{name}" not in arrays]
    missing += [f"{arm}__telemetry__{name}" for arm in arm_order for name in REQUIRED_TELEMETRY if f"{arm}__telemetry__{name}" not in arrays]
    if missing:
        refuse(f"required arrays are missing: {missing[:8]}{'...' if len(missing) > 8 else ''}")
    if arrays["row_ids"].ndim != 1:
        refuse("row_ids is not one-dimensional")
    n_rows = int(arrays["row_ids"].shape[0])
    first = arrays[f"{noisy}__subaperture_ids"]
    if first.ndim != 1:
        refuse("no lenslet layout for the noisy arm")
    lenslet_ids = tuple(str(item) for item in first.tolist())
    n_lenslets = len(lenslet_ids)
    if len(set(lenslet_ids)) != n_lenslets or n_rows != 2 * n_lenslets:
        refuse(f"{n_rows} rows for {n_lenslets} lenslets (two canonical rows per distinct lenslet expected)")
    pupil_samples = int(np.count_nonzero(arrays["residual_maps__pupil_mask"])) if "residual_maps__pupil_mask" in arrays else None
    sizes = {"frame": n_steps, "analysed_frame": n_steps - burn_in, "row": n_rows, "lenslet": n_lenslets, "xy": 2, "pupil_sample": pupil_samples}
    # Every array against the runner's canonical units, axes, meaning, the core's dtype and the shape its axes imply.
    for name, array in arrays.items():
        spec = declared[name]
        try:
            unit, meaning, axes, dtype = canonical_layout(name, arm_order, runner)
        except KeyError:
            refuse(f"array {name} is not a canonical sidecar array")
        if spec.get("units") != unit or list(spec.get("axes", [])) != list(axes) or spec.get("meaning") != meaning:
            refuse(f"array {name} is declared with units {spec.get('units')!r}, axes {spec.get('axes')!r} and meaning {str(spec.get('meaning'))[:60]!r}; the canonical layout is {unit!r}, {list(axes)!r}, {meaning[:60]!r}")
        if dtype == "U":
            if array.dtype.kind != "U":
                refuse(f"array {name} must hold unicode identifiers, not {array.dtype}")
        elif str(array.dtype) != dtype:
            refuse(f"array {name} has dtype {array.dtype}, the canonical layout requires {dtype}")
        if spec.get("dtype") != str(array.dtype) or [int(s) for s in array.shape] != list(spec.get("shape", [])):
            refuse(f"array {name} has dtype {array.dtype} and shape {array.shape}, declared {spec.get('dtype')!r} {spec.get('shape')!r}")
        if array.ndim != len(axes):
            refuse(f"array {name} has {array.ndim} dimensions for axes {list(axes)!r}")
        for axis_name, extent in zip(axes, array.shape):
            expected = sizes.get(axis_name)
            if expected is not None and int(extent) != int(expected):
                refuse(f"array {name} has {extent} entries along {axis_name!r}, the trace has {expected}")
    if not np.array_equal(arrays["frame_index"], np.arange(n_steps)):
        refuse("frame_index is not 0..n_steps-1")
    if not np.array_equal(arrays["analysed_frame_index"], np.arange(burn_in, n_steps)):
        refuse("analysed_frame_index is not burn_in..n_steps-1")
    for name in ("delta_v_m2", "mean_square_difference_m2", "cross_term_m2"):
        if not np.all(np.isfinite(arrays[name])):
            refuse(f"{name} is not finite")
    if not np.allclose(arrays["cross_term_m2"], arrays["mean_square_difference_m2"] - arrays["delta_v_m2"], rtol=0.0, atol=1e-30 + 1e-9 * np.max(np.abs(arrays["mean_square_difference_m2"]))):
        refuse("cross_term_m2 is not mean_square_difference_m2 minus delta_v_m2")
    if tuple(str(item) for item in arrays["row_ids"].tolist()) != tuple(row_ids_for_subapertures(lenslet_ids)):
        refuse("row_ids are not the canonical interleaved x/y rows of the lenslet order")
    for arm in arm_order:
        if tuple(str(item) for item in arrays[f"{arm}__subaperture_ids"].tolist()) != lenslet_ids:
            refuse(f"arm {arm} lists the lenslets in another order than the noisy arm")
    if expected_label is not None and metadata.get("label") != expected_label:
        refuse(f"label {metadata.get('label')!r} is not the configuration's {expected_label!r}")
    if not isinstance(metadata.get("root_seed"), int) or not isinstance(metadata.get("config_hash"), str):
        refuse("no integer root seed or configuration hash")
    checked: dict[str, Any] = {
        "structural": "passed (declared table against the runner's canonical units, axes, meanings, dtypes and axis-implied shapes; frame domains; two-arm layout; canonical rows; label)",
        "arrays_checked": len(arrays), "schema": metadata["schema"],
    }
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
        runner.validate_trace_payload(
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


# -- noise covariance --------------------------------------------------------------


def recovery_acted(recovery: Any) -> bool:
    """The core's rule (``_recovery_acted``): any positive numeric counter in the recovery record other than its hash."""

    if not isinstance(recovery, dict):
        return False
    return any(isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 for key, value in recovery.items() if key != "config_hash")


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


def _block_covariance(residual: np.ndarray, frames_of: np.ndarray, lenslet: int, axes: np.ndarray) -> np.ndarray | None:
    """Covariance (``ddof = 1``) of the chosen axes of one lenslet over the chosen frames, or None with fewer than three frames."""

    if np.count_nonzero(frames_of) < 3:
        return None
    sample = residual[frames_of][:, lenslet, :][:, axes]
    return np.atleast_2d(np.cov(sample, rowvar=False, ddof=1))


def sigma_from_sidecar(metadata: dict[str, Any], arrays: dict[str, np.ndarray], row_ids: tuple[str, ...], n_pupil: int, *, min_fraction: float, min_operator_match: float) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray], dict[str, Any]]:
    """Noise covariances and row masks under the ``effective``, ``available`` and ``strict`` rules, the operator record and the measured series."""

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
    finite = np.all(np.isfinite(centroids), axis=2) & np.all(np.isfinite(expected), axis=2)
    residual = np.where(finite[:, :, None], centroids - expected, 0.0)
    n_rows = len(row_ids)

    # The operator the loop used: the modal effective row set of the noisy arm over the analysed frames.
    effective_noisy = np.asarray(arrays[f"{noisy}__measurement_row_masks"], dtype=bool)[frames]
    effective_twin = np.asarray(arrays[f"{twin}__measurement_row_masks"], dtype=bool)[frames]
    keys = [row.tobytes() for row in effective_noisy]
    counter = Counter(keys)
    modal_key, modal_count = counter.most_common(1)[0]
    modal_mask = np.frombuffer(modal_key, dtype=bool).copy()
    noisy_match = np.array([key == modal_key for key in keys])
    twin_match = np.all(effective_twin == modal_mask, axis=1)
    noisy_fraction, twin_fraction = float(np.mean(noisy_match)), float(np.mean(twin_match))
    operator_consistent = bool(noisy_fraction >= min_operator_match and twin_fraction >= min_operator_match)
    sigma_effective = np.zeros((n_rows, n_rows))
    sigma_frames_rule = "frames in which the noisy arm used the modal operator"
    frames_for_sigma = noisy_match if np.count_nonzero(noisy_match) >= 3 else np.ones(frames.size, dtype=bool)
    if np.count_nonzero(noisy_match) < 3:
        sigma_frames_rule = "all analysed frames (fewer than three frames under the modal operator)"
    for lenslet in range(len(lenslets)):
        axes = np.flatnonzero(modal_mask[rows[lenslet]])
        if axes.size == 0:
            continue
        block = _block_covariance(residual, frames_for_sigma & finite[:, lenslet], lenslet, axes)
        if block is not None:
            target = rows[lenslet][axes]
            sigma_effective[np.ix_(target, target)] = block
    operator = {
        "definition": "the row set the noisy arm's reconstructor used in the plurality of analysed frames (<arm>__measurement_row_masks); the model's operator R is probed on exactly this set",
        "rows_in_modal_mask": int(np.count_nonzero(modal_mask)), "rows_total": n_rows,
        "distinct_effective_masks_noisy": len(counter),
        "noisy_frames_under_modal_operator": int(modal_count), "noisy_match_fraction": noisy_fraction,
        "twin_frames_under_modal_operator": int(np.count_nonzero(twin_match)), "twin_match_fraction": twin_fraction,
        "rows_always_effective_noisy": int(np.count_nonzero(np.all(effective_noisy, axis=0))),
        "rows_ever_effective_noisy": int(np.count_nonzero(np.any(effective_noisy, axis=0))),
        "min_operator_match_fraction": float(min_operator_match),
        "operator_consistent": operator_consistent,
        "sigma_frames": sigma_frames_rule,
        "comparison_status": "operator-consistent" if operator_consistent else "mask-variable: the loop had no single operator in at least one arm; the prediction is reported and the comparison is descriptive",
    }

    # Telemetry-based sensitivities.
    usable = valid & supported & finite
    fraction = np.mean(usable, axis=0)
    strict_lenslets = fraction >= 1.0
    available_lenslets = fraction >= float(min_fraction)
    sigmas: dict[str, np.ndarray] = {"effective": sigma_effective}
    masks: dict[str, np.ndarray] = {"effective": modal_mask}
    for rule, lenslet_mask, own_frames in (("available", available_lenslets, True), ("strict", strict_lenslets, False)):
        sigma = np.zeros((n_rows, n_rows))
        mask = np.zeros(n_rows, dtype=bool)
        for lenslet in np.flatnonzero(lenslet_mask):
            frames_of = usable[:, lenslet] if own_frames else np.ones(frames.size, dtype=bool)
            block = _block_covariance(residual, frames_of, lenslet, np.array([0, 1]))
            if block is not None:
                sigma[np.ix_(rows[lenslet], rows[lenslet])] = block
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
        "operator": operator,
        "support_rules": {
            "effective": {"definition": "rows of the modal effective mask (the operator the loop used); covariance over the frames in which the noisy arm used that operator", "lenslet_fraction": float(np.mean(np.all(modal_mask[rows], axis=1))), "rows_with_noise": int(np.count_nonzero(np.any(sigma_effective != 0.0, axis=0)))},
            "available": {"definition": f"lenslets valid, supported and finite in at least {float(min_fraction):g} of the analysed frames; covariance over each lenslet's own valid frames", "min_fraction": float(min_fraction), "lenslet_fraction": float(np.mean(available_lenslets)), "rows_with_noise": int(np.count_nonzero(masks["available"])), "mean_valid_fraction_of_included": float(np.mean(fraction[available_lenslets])) if np.any(available_lenslets) else None},
            "strict": {"definition": "lenslets valid, supported and finite in every analysed frame (the E0 rule); covariance over all analysed frames", "lenslet_fraction": float(np.mean(strict_lenslets)), "rows_with_noise": int(np.count_nonzero(masks["strict"]))},
        },
        "mean_realized_sigma_px_on_strict_support": float(np.mean(np.sqrt(np.sum(residual[:, strict_lenslets, :] ** 2, axis=0) / (frames.size - 1)))) if np.any(strict_lenslets) else None,
        "measured_delta_v_mean_m2": float(np.mean(delta_v)),
        "measured_delta_v_block25_se_m2": block_se,
        "measured_mean_square_difference_mean_m2": float(np.mean(msd)),
        "noisy_arm_saturation_fraction_mean": float(np.mean(np.asarray(arrays[f"{noisy}__saturation_fraction"], dtype=float)[frames])),
        "noisy_arm_frames_with_saturation": int(np.count_nonzero(np.asarray(arrays[f"{noisy}__saturation_fraction"], dtype=float)[frames] > 0.0)),
        "twin_arm_saturation_fraction_mean": float(np.mean(np.asarray(arrays[f"{twin}__saturation_fraction"], dtype=float)[frames])),
        "rejected_frames_after_burn_in": rejected,
        "recovery_acted": acted,
        "gate_quiet_by_core_rule": bool(float(np.sum(disagreement)) / (n_rows * frames.size) < 1.0e-3 and all(v == 0 for v in rejected.values()) and not any(acted.values())),
        "mask_disagreement_row_frames_fraction": float(np.sum(disagreement) / (n_rows * frames.size)),
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
    parser.add_argument("--support", choices=RULES, default="effective", help="which noise-covariance rule is the primary prediction (sidecar mode; every rule is reported)")
    parser.add_argument("--support-min-fraction", type=float, default=0.9, help="inclusion threshold of the available rule (fraction of analysed frames a lenslet must be usable)")
    parser.add_argument("--min-operator-match", type=float, default=0.95, help="fraction of analysed frames in which each arm must have used the modal operator for the comparison to count as operator-consistent")
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
        if config.config_hash != metadata.get("config_hash"):
            raise SidecarRefused(f"the built configuration {config.config_hash[:16]} is not the sidecar's {str(metadata.get('config_hash'))[:16]}: the sidecar was traced on another configuration; it is not read as data.")
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
        sigmas, masks, sigma_info = sigma_from_sidecar(metadata, arrays, row_ids, n_pupil, min_fraction=arguments.support_min_fraction, min_operator_match=arguments.min_operator_match)
        primary_rule = arguments.support
    sigma_info["primary_rule"] = primary_rule
    if validation is not None:
        sigma_info["sidecar_validation"] = validation

    started = time.perf_counter()
    response_full = reconstructor_matrix(system.reconstructor, row_ids)
    probe_full_s = time.perf_counter() - started
    weights_series = np.einsum("ir,ij,jr->r", response_full, gram, response_full) / n_pupil

    def predict(rule: str, sigma: np.ndarray, mask: np.ndarray) -> dict[str, Any]:
        started = time.perf_counter()
        if np.all(mask):
            response = response_full
        else:
            try:
                response = reconstructor_matrix_masked(system.reconstructor, row_ids, mask, coordinate_ids)
            except MaskRefused as exc:
                return {"status": "not defined", "reason": str(exc), "rows_valid_in_mask": int(np.count_nonzero(mask)), "rows_total": int(len(mask))}
        probe_s = time.perf_counter() - started
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
            "timing_s": {"reconstructor_probe": probe_s, "lyapunov_two_solves": lyapunov_s, "window_two_propagations": window_s},
        }

    predictions = {rule: predict(rule, sigmas[rule], masks[rule]) for rule in sigmas}
    primary = predictions[primary_rule]
    common: dict[str, Any] = {
        "schema": SCHEMA, "mode": "model", "purpose": "analysis-only linear closed-loop noise model; no loop is run; no scientific claim by itself",
        "configuration": described, "diagnostic_alpha_override": arguments.alpha, "config_hash": config.config_hash, "root_seed": root_seed, "n_steps_in_hash": n_steps, "window_frames": [burn_in, n_steps],
        "controller": {"gain": gain, "leak": leak, "latency_frames": latency},
        "reconstructor": {"kind": config.reconstructor.kind, "alpha": config.reconstructor.alpha, "rcond": config.reconstructor.rcond, "min_valid_fraction": config.reconstructor.min_valid_fraction},
        "dimensions": {"rows": len(row_ids), "controlled_actuators": size_c, "pupil_samples": n_pupil, "lyapunov_state": size_c * (latency + 1)},
        "mask_rule": "the reconstructor is probed with exactly the rows that carry noise valid (one fixed mask per rule for L, the injection and Sigma); the primary rule takes the operator the loop used in the plurality of analysed frames; the series' all-valid propagation weights are kept for the first draft's scalar value",
        "noise_covariance": jsonable(sigma_info),
        "timing": {"build_s": build_s, "full_probe_s": probe_full_s, **{f"{rule}_s": entry.get("timing_s") for rule, entry in predictions.items()}},
        "ru_maxrss_bytes": peak_rss_bytes(),
        "host": {"platform": sys.platform, "machine": platform.machine(), "node": platform.node(), "python": sys.version, "numpy": np.__version__},
        "enabled_by_user": arguments.enabled_by_user,
    }
    by_rule = {rule: {key: value for key, value in entry.items() if key != "timing_s"} for rule, entry in predictions.items()}
    if primary.get("status") != "defined":
        defined = sorted(rule for rule, entry in predictions.items() if entry.get("status") == "defined")
        record = {**common, "prediction": {"primary_status": "not defined", "primary_rule": primary_rule, "reason": primary["reason"], "defined_rules": defined, "by_noise_covariance_rule": by_rule, "note": "the reconstructor refuses the primary rule's mask under its own valid-fraction or rank policy, so the fixed-mask model is not defined for this run; such a run is gate-active in the loop as well"}}
        write_record_once(arguments.output, record)
        print(json.dumps({"configuration": described, "primary_rule": primary_rule, "primary_status": "not defined", "reason": primary["reason"], "defined_rules": defined}))
        return 0
    operator = sigma_info.get("operator")
    record = {
        **common,
        "feedback_spectrum": primary["feedback_spectrum"],
        "stationarity": primary["stationarity"],
        "prediction": {
            "primary_status": "defined",
            "primary_rule": primary_rule,
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
            "by_noise_covariance_rule": by_rule,
        },
    }
    measured = sigma_info.get("measured_delta_v_mean_m2")
    if measured is not None:
        se = sigma_info.get("measured_delta_v_block25_se_m2")
        window = primary["delta_v_exact_window_m2"]
        record["comparison"] = {
            "status": operator["comparison_status"] if operator is not None else "operator-consistent",
            "operator_consistent": None if operator is None else operator["operator_consistent"],
            "measured_delta_v_mean_m2": measured,
            "measured_delta_v_block25_se_m2": se,
            "measured_over_exact_window": measured / window if window > 0 else None,
            "measured_over_exact_stationary": None if primary["delta_v_exact_stationary_m2"] is None or primary["delta_v_exact_stationary_m2"] <= 0 else measured / primary["delta_v_exact_stationary_m2"],
            "measured_over_scalar_mask": measured / primary["delta_v_scalar_reduction_mask_m2"] if primary["delta_v_scalar_reduction_mask_m2"] > 0 else None,
            "measured_over_scalar_series_weights": measured / primary["delta_v_scalar_reduction_series_weights_m2"] if primary["delta_v_scalar_reduction_series_weights_m2"] > 0 else None,
            "exact_window_within_2_block_se": None if se is None else bool(abs(measured - window) <= 2.0 * se),
            "measured_over_exact_window_by_rule": {rule: (None if entry.get("status") != "defined" or entry["delta_v_exact_window_m2"] <= 0 else measured / entry["delta_v_exact_window_m2"]) for rule, entry in predictions.items()},
            "note": "a pilot-level consistency check of the model against one run; the protocol's acceptance rules, not this ratio, decide anything; a mask-variable run's comparison is descriptive",
        }
    write_record_once(arguments.output, record)
    print(json.dumps({"configuration": described, "controlled": size_c, "primary_rule": primary_rule, "rows_in_mask": primary["rows_valid_in_mask"],
                      "operator": None if operator is None else {k: operator[k] for k in ("noisy_match_fraction", "twin_match_fraction", "operator_consistent")},
                      "feedback_min": primary["feedback_spectrum"]["min"], "fraction_below_0.9": primary["feedback_spectrum"]["fraction_below_0.9"],
                      "delta_v_exact_window_nm2": primary["delta_v_exact_window_m2"] * 1e18, "delta_v_exact_stationary_nm2": None if primary["delta_v_exact_stationary_m2"] is None else primary["delta_v_exact_stationary_m2"] * 1e18, "delta_v_scalar_mask_nm2": primary["delta_v_scalar_reduction_mask_m2"] * 1e18,
                      "sidecar_validation": None if validation is None else {k: v for k, v in validation.items() if k != "structural"} | {"structural": "passed"},
                      "comparison": None if record.get("comparison") is None else {k: record["comparison"][k] for k in ("status", "measured_over_exact_window", "measured_over_exact_window_by_rule", "exact_window_within_2_block_se")}}, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())
