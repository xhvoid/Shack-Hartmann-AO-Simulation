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

**The operator the loop used, and the error budget of taking it as fixed.**
The model is a fixed-mask model: ``R`` is probed with exactly one row set
valid and every other row invalid, and ``L``, the injection and ``Sigma``
describe that one mask.  The primary rule ``effective`` takes the row set
the noisy arm's reconstructor actually used in the plurality of analysed
frames (the sidecar's per-frame effective row masks) and estimates
``Sigma`` from the realized residuals of the frames in which that operator
was in use.  Two quantities settle the error of taking that operator as
fixed (review rounds 4 to 7):

1. the **operator error** (review round 7): the conditional prediction
   (item 2) recomputed with the noisy arm's actual operator of every frame
   from the first new increment on (each distinct effective mask probed
   once; update ``k`` releases the increment of frame ``k - d`` with that
   frame's operator), against the same prediction under the modal
   operator.  Both parts change: the measured carried state is propagated
   without noise through the actual operators, with the deterministic
   forcing ``(R^noisy - R^twin)(m^twin - m_ref)`` of the frames on which the
   two arms' operators differ, and the cold-start noise part is propagated
   with the actual operators.  The cold part is linear in the measurement
   covariance: one adjoint pass gives it as ``tr(A Sigma)``.  The rows
   outside the modal mask have an admissible covariance instead of a value:
   per lenslet, each axis variance in an interval (with at least
   ``--outside-estimate-min-frames`` usable frames the two-sided 95 %
   chi-square interval of its own variance; with fewer, from zero to the
   larger of its 97.5 % chi-square upper bound and
   ``--model-variance-margin`` times the sensor model's variance at its own
   spot, the model term only where the run's margin calibration supports
   it) and every positive-semidefinite 2 x 2 block with those variances.
   The operator error is extremized exactly over that set (per lenslet a
   2 x 2 quadratic form over a box), the extreme of larger magnitude is the
   error, and an extreme range wider than the tolerance makes the run not
   assessable.  The round-4 to round-6 unconditional transient is kept as
   a diagnostic.  Nothing contributing is treated as zero, and no other
   lenslet's variance stands in for an unobserved one;
2. the **carried state, measured** (review round 6): the state the loop
   carries into the analysed window is not modelled or bounded but
   measured.  The sensor's measurement is the centroid minus its zero-phase
   calibration reference (read from the system built with the run's seed;
   it cancels between the arms only where both use the same operator), the
   sidecar holds both arms' centroids and effective row masks, and the
   controller law is known, so the command difference of the whole run is
   rebuilt frame by frame, ``dc_{k+1} = (1 - l) dc_k + g [R_k^n (m_k^n -
   m_ref) - R_k^t (m_k^t - m_ref)]_{k-d}``, each frame's operator probed on
   its own mask.  Its per-frame pupil mean square is compared with
   ``delta_v_m2``: the relative rms ``r`` is the measured departure of the
   linear model with the probed operators from this run (controller law,
   operators, solver linearity, units, clipping) and always enters the
   budget.  The carried state comes from that reconstruction when ``r`` is
   at most 1e-3, otherwise from the residual maps where retained (least
   squares of the map difference on the pupil response: the state at the
   first analysed frame and the ``d`` increments released next), otherwise
   the run is not assessable.  Propagated under the modal loop with no
   further noise, the state's window mean ``D`` is the exact carried
   contribution, and the prediction is made conditional on it: ``W_cold +
   D``, ``W_cold`` being the model's window value for the noise not yet in
   that state.  No state space is selected and no covariance inequality is
   used for the primary.  The round-5 bound (``gamma``, the largest
   generalized eigenvalue of the window-mean and first-block-mean forms,
   applied to the measured first block) and the restart values of round 4
   are reported as diagnostics only.

A run is ``operator-consistent`` when its operator error (at the worse
admissible covariance) is within ``--operator-tolerance``;
``mask-variable`` when it is not; ``not assessable`` when the run's
operators cannot all be probed (more distinct operators than
``--max-distinct-masks``, an operator the reconstructor refuses), a
lenslet outside the modal mask has no admissible interval, the admissible
covariance moves the operator error over more than the tolerance, no
measured carried state exists, or the run's systematic budget ``u =
|operator error| + r + f`` (``f`` the unexplained share of the map
difference when the maps supply the state) is at or above
``--closure-band``: such a run cannot enter an equivalence test, and
admitting it would shrink every other run's band.  Below the band the
budget is not a threshold: the protocol's closure test subtracts the
admissible runs' mean budget from its band (PROTOCOL.md 1.7).
The fractions of analysed and burn-in frames in which each arm used the
modal operator are reported as diagnostics only.  Two telemetry-based
rules are reported as sensitivities: ``available`` (lenslets valid,
supported and finite in at least ``--support-min-fraction`` of the
analysed frames, covariance over each lenslet's own valid frames) and
``strict`` (lenslets valid in every analysed frame, the E0 rule).  ``flat``
uses the sensor's flat-wavefront ``detector_covariance_v2`` model on its
supported lenslets (a-priori, no run needed).  The series' propagation
weights (every row valid) are kept for the first draft's scalar value
``kappa * sum_r w_r sigma_r^2``; the same reduction on the model's own mask
is reported too.  The record carries an inventory of the arrays the tool
retains (bytes) beside the process peak, for the pilot's memory estimate.

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
from collections import Counter, deque
import hashlib
import json
from pathlib import Path
import platform
import sys
import time
from typing import Any

import numpy as np
from scipy import linalg, stats

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

SCHEMA = "post_t2_linear_loop_noise_model.v8"
UNSENSED_FEEDBACK = 1.0e-6
BLOCK_FRAMES = 25
UNSENSED_CONTENT_LEVEL = 1.0e-3
RECONSTRUCTION_TOLERANCE = 1.0e-3
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


def forcing_block(response: np.ndarray, sigma: np.ndarray, *, gain: float) -> np.ndarray:
    """``g^2 R Sigma R^T``: the only nonzero block of ``G Sigma G^T`` (the leading one), kept at that size (review round 5, memory)."""

    return (gain**2) * (response @ sigma @ response.T)


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


def window_covariance(loop: np.ndarray, block: np.ndarray, *, gain: float, leak: float, latency: int, n_steps: int, burn_in: int, initial_state: np.ndarray | None = None, start_frame: int = 0, forcing_from: int | None = None, weight: np.ndarray | None = None, series_out: list[float] | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Mean leading block of ``Cov(dc_{k+1})`` over the analysed frames ``burn_in <= k < n_steps``, and the final state.

    From ``P_0 = 0`` at frame 0 (or from ``initial_state``, the full
    companion covariance, at ``start_frame``): the update at frame ``k``
    releases the increment enqueued ``d`` updates earlier, so the first
    ``d`` updates after a start from identical commands release the queue's
    zeros and the noise forcing (``block``, the leading block of
    ``G Sigma G^T``) enters only for ``k >= start_frame + d``
    (``forcing_from`` overrides this: a stationary start carries noise in
    its queue, so its forcing enters at once).  With ``weight`` and
    ``series_out`` the per-frame value ``sum(weight * P_{k+1}[:c, :c])`` is
    appended for every frame from ``start_frame`` on.
    """

    size = loop.shape[0]
    full = size * (latency + 1)
    state = np.zeros((full, full)) if initial_state is None else np.array(initial_state, dtype=float)
    first_forcing = start_frame + latency if forcing_from is None else forcing_from
    mean_block = np.zeros((size, size))
    analysed = 0
    for frame in range(start_frame, n_steps):
        state = propagate(state, loop, gain=gain, leak=leak, latency=latency)
        if frame >= first_forcing:
            state[:size, :size] += block
        if series_out is not None and weight is not None:
            series_out.append(float(np.sum(weight * state[:size, :size])))
        if frame >= burn_in:
            mean_block += state[:size, :size]
            analysed += 1
    mean_block /= max(analysed, 1)
    return 0.5 * (mean_block + mean_block.T), state


def time_varying_window(loops: list[np.ndarray], blocks: list[np.ndarray], sequence: np.ndarray, *, gain: float, leak: float, latency: int, n_steps: int, burn_in: int) -> np.ndarray:
    """Mean leading block over the analysed frames with the operator of frame ``k - d`` at update ``k`` (burn-in included).

    ``sequence[k]`` indexes the operator the noisy arm used at frame ``k``.
    The increment released at update ``k`` was computed at frame ``k - d``
    with that frame's operator, so the feedback block and the injection of
    update ``k`` both carry ``loops[sequence[k - d]]`` and
    ``blocks[sequence[k - d]]``; the first ``d`` updates release the
    queue's zeros (no feedback, no injection).
    """

    size = loops[0].shape[0]
    full = size * (latency + 1)
    state = np.zeros((full, full))
    zero_loop = np.zeros_like(loops[0])
    mean_block = np.zeros((size, size))
    analysed = 0
    for frame in range(n_steps):
        if frame >= latency:
            index = int(sequence[frame - latency])
            state = propagate(state, loops[index], gain=gain, leak=leak, latency=latency)
            state[:size, :size] += blocks[index]
        else:
            state = propagate(state, zero_loop, gain=gain, leak=leak, latency=latency)
        if frame >= burn_in:
            mean_block += state[:size, :size]
            analysed += 1
    mean_block /= max(analysed, 1)
    return 0.5 * (mean_block + mean_block.T)


def adjoint_step(adjoint: np.ndarray, loop: np.ndarray, *, gain: float, leak: float, latency: int) -> np.ndarray:
    """``F^T H F`` using the companion structure of ``F`` (the adjoint of :func:`propagate`)."""

    size = loop.shape[0]
    tail = latency * size

    def apply_transpose(matrix: np.ndarray) -> np.ndarray:
        out = np.empty_like(matrix)
        if latency:
            out[:size] = (1.0 - leak) * matrix[:size] + matrix[size:2 * size]
            out[size:tail] = matrix[2 * size:tail + size]
            out[tail:tail + size] = -gain * (loop.T @ matrix[:size])
        else:
            out[:size] = (1.0 - leak) * matrix[:size] - gain * (loop.T @ matrix[:size])
        return out

    return apply_transpose(apply_transpose(adjoint).T).T


def time_varying_cold(loops: list[np.ndarray], blocks: list[np.ndarray], sequence: np.ndarray, *, gain: float, leak: float, latency: int, n_steps: int, start: int, forcing_from: int, gram: np.ndarray, n_pupil: int) -> float:
    """Window mean of ``tr(Gram Cov(dc)) / N`` over frames ``start .. n_steps - 1`` for the noise part started cold at ``start``.

    Update ``k`` releases the increment computed at frame ``k - d`` with that
    frame's operator (``loops[sequence[k - d]]``); its noise injection
    (``blocks[sequence[k - d]]``) enters from update ``forcing_from`` on,
    the earlier increments belonging to the measured carried state.
    """

    size = loops[0].shape[0]
    full = size * (latency + 1)
    state = np.zeros((full, full))
    total = 0.0
    for frame in range(start, n_steps):
        index = int(sequence[frame - latency])
        state = propagate(state, loops[index], gain=gain, leak=leak, latency=latency)
        if frame >= forcing_from:
            state[:size, :size] += blocks[index]
        total += float(np.sum(gram * state[:size, :size]))
    return total / (n_pupil * max(n_steps - start, 1))


def time_varying_cold_functional(loops: list[np.ndarray], responses: list[np.ndarray], sequence: np.ndarray, *, gain: float, leak: float, latency: int, n_steps: int, start: int, forcing_from: int, gram: np.ndarray, n_pupil: int) -> np.ndarray:
    """The rows x rows matrix ``A`` with :func:`time_varying_cold` ``= tr(A Sigma)`` for every measurement covariance ``Sigma``.

    One backward (adjoint) pass: ``H_k = w E + F_{k+1}^T H_{k+1} F_{k+1}``
    with ``E`` the Gram matrix on the command block and ``w`` the window
    weight; the injection ``g^2 R Sigma R^T`` of update ``k`` contributes
    ``tr(H_k[:c, :c] g^2 R Sigma R^T)``, so ``A = g^2 sum_op R_op^T S_op R_op``
    with ``S_op`` the sum of ``H_k[:c, :c]`` over the updates that inject
    through operator ``op`` (columns of invalid rows are zero in ``R_op``).
    """

    size = loops[0].shape[0]
    full = size * (latency + 1)
    weight = 1.0 / (n_pupil * max(n_steps - start, 1))
    adjoint_after = np.zeros((full, full))
    sums = [np.zeros((size, size)) for _ in responses]
    for frame in range(n_steps - 1, start - 1, -1):
        current = adjoint_after
        current[:size, :size] += weight * gram
        index = int(sequence[frame - latency])
        if frame >= forcing_from:
            sums[index] += current[:size, :size]
        adjoint_after = adjoint_step(current, loops[index], gain=gain, leak=leak, latency=latency)
    rows = responses[0].shape[1]
    coefficient = np.zeros((rows, rows))
    for response, block in zip(responses, sums):
        if np.any(block):
            coefficient += (gain**2) * (response.T @ block @ response)
    return 0.5 * (coefficient + coefficient.T)


def deterministic_window(start_state: np.ndarray, start_queue: list[np.ndarray], *, first_frame: int, n_steps: int, include_start: bool, loop_at: Any, forcing_at: Any, gain: float, leak: float, gram: np.ndarray, n_pupil: int) -> np.ndarray:
    """Per-frame ``|W x|^2 / N`` of the measured carried state propagated without noise.

    From the post-update state ``start_state`` and the increments still
    queued, every later increment is ``-L_k x + f_k``: ``L_k = loop_at(k)``
    the loop matrix of the operator used at frame ``k`` and ``f_k =
    forcing_at(k)`` (or ``None``) a deterministic forcing, released ``d``
    updates later as in the controller.
    """

    state = np.array(start_state, dtype=float)
    queue: deque[np.ndarray] = deque(np.array(item, dtype=float) for item in start_queue)
    values: list[float] = []
    if include_start:
        values.append(float(state @ gram @ state) / n_pupil)
    for frame in range(first_frame, n_steps):
        increment = -(loop_at(frame) @ state)
        forcing = forcing_at(frame)
        if forcing is not None:
            increment = increment + forcing
        queue.append(increment)
        released = queue.popleft()
        state = (1.0 - leak) * state + gain * released
        values.append(float(state @ gram @ state) / n_pupil)
    return np.asarray(values)


def quadratic_box_extremes(a: float, b: float, h: float, p_range: tuple[float, float], q_range: tuple[float, float]) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Exact minimum and maximum of ``a p^2 + b q^2 + 2 h p q`` over ``p_range x q_range`` (``p, q >= 0``).

    Returns ``((min, p, q), (max, p, q))``.  The candidates are the corners,
    the vertex of the quadratic on each edge, and, for a singular form, a
    point of its null ray inside the box (value zero); a homogeneous quadratic
    has no other critical point.
    """

    candidates: list[tuple[float, float]] = [(p, q) for p in p_range for q in q_range]
    for p in p_range:
        if b != 0.0:
            q = -h * p / b
            if q_range[0] <= q <= q_range[1]:
                candidates.append((p, q))
    for q in q_range:
        if a != 0.0:
            p = -h * q / a
            if p_range[0] <= p <= p_range[1]:
                candidates.append((p, q))
    scale = max(abs(a), abs(b), abs(h), 1.0e-300)
    if abs(a * b - h * h) <= 1.0e-12 * scale * scale:
        direction = np.array([-h, a]) if abs(a) >= abs(b) and a != 0.0 else np.array([b, -h])
        if np.linalg.norm(direction) > 0.0:
            direction = direction / np.linalg.norm(direction)
            if direction[0] < 0.0 or direction[1] < 0.0:
                direction = -direction
            if direction[0] >= 0.0 and direction[1] >= 0.0:
                low = max(p_range[0] / direction[0] if direction[0] > 0.0 else 0.0, q_range[0] / direction[1] if direction[1] > 0.0 else 0.0)
                high = min(p_range[1] / direction[0] if direction[0] > 0.0 else np.inf, q_range[1] / direction[1] if direction[1] > 0.0 else np.inf)
                if low <= high and np.isfinite(low):
                    candidates.append((float(low * direction[0]), float(low * direction[1])))
    scored = [(a * p * p + b * q * q + 2.0 * h * p * q, p, q) for p, q in candidates]
    minimum = min(scored, key=lambda item: item[0])
    maximum = max(scored, key=lambda item: item[0])
    return (float(minimum[0]), float(minimum[1]), float(minimum[2])), (float(maximum[0]), float(maximum[1]), float(maximum[2]))


def admissible_extremes(coefficient: np.ndarray, base: np.ndarray, admissible: list[dict[str, Any]]) -> dict[str, Any]:
    """Exact extremes of ``tr(A Sigma)`` over the admissible covariances (base plus one free block per listed lenslet).

    Per lenslet the block contributes ``a s_x + b s_y + 2 h c`` with ``s`` in
    the interval box and ``|c| <= sqrt(s_x s_y)``; at fixed ``s`` the cross
    term is extreme at ``c = +-sign(h) sqrt(s_x s_y)``, so with ``p = sqrt(s_x)``
    and ``q = sqrt(s_y)`` each extreme is that of a 2 x 2 quadratic form over
    a box (:func:`quadratic_box_extremes`); the lenslets are independent, so
    the extremes add.  Returns both extreme values and covariances.
    """

    base = np.array(base, dtype=float)
    for entry in admissible:
        block_rows = np.asarray(entry["rows"], dtype=int)
        base[np.ix_(block_rows, block_rows)] = 0.0
    value = float(np.sum(coefficient * base))
    low_value, high_value = value, value
    low_sigma, high_sigma = base.copy(), base.copy()
    per_lenslet: list[dict[str, Any]] = []
    for entry in admissible:
        x_row, y_row = entry["rows"]
        a, b, h = float(coefficient[x_row, x_row]), float(coefficient[y_row, y_row]), float(coefficient[x_row, y_row])
        p_range = (float(np.sqrt(entry["lower_px2"][0])), float(np.sqrt(entry["upper_px2"][0])))
        q_range = (float(np.sqrt(entry["lower_px2"][1])), float(np.sqrt(entry["upper_px2"][1])))
        (_, _, _), (high, p_high, q_high) = quadratic_box_extremes(a, b, abs(h), p_range, q_range)
        (low, p_low, q_low), _ = quadratic_box_extremes(a, b, -abs(h), p_range, q_range)
        sign = 1.0 if h >= 0.0 else -1.0
        for target, p_value, q_value, cross_sign in ((high_sigma, p_high, q_high, sign), (low_sigma, p_low, q_low, -sign)):
            target[x_row, x_row] = p_value**2
            target[y_row, y_row] = q_value**2
            target[x_row, y_row] = target[y_row, x_row] = cross_sign * p_value * q_value
        low_value += low
        high_value += high
        per_lenslet.append({"lenslet": entry["lenslet"], "coefficient_xx_yy_xy": [a, b, h], "contribution_min_m2": low, "contribution_max_m2": high, "block_at_min_px2": [[p_low**2, -sign * p_low * q_low], [-sign * p_low * q_low, q_low**2]], "block_at_max_px2": [[p_high**2, sign * p_high * q_high], [sign * p_high * q_high, q_high**2]]})
    return {"min": low_value, "max": high_value, "sigma_min": low_sigma, "sigma_max": high_sigma, "per_lenslet": per_lenslet}


def _advance_first_block_row(first_row: np.ndarray, loop: np.ndarray, *, gain: float, leak: float, latency: int) -> np.ndarray:
    """``A F`` for ``A`` the leading block row of ``F^j`` (``c x c(d+1)``), using the companion structure of ``F``."""

    size = loop.shape[0]
    out = np.empty_like(first_row)
    blocks = [first_row[:, i * size:(i + 1) * size] for i in range(latency + 1)]
    if latency == 0:
        out[:, :size] = (1.0 - leak) * blocks[0] - gain * (blocks[0] @ loop)
        return out
    out[:, :size] = (1.0 - leak) * blocks[0] + blocks[1]
    for i in range(1, latency):
        out[:, i * size:(i + 1) * size] = blocks[i + 1]
    out[:, latency * size:] = -gain * (blocks[0] @ loop)
    return out


def window_sensitivity(loop: np.ndarray, gram: np.ndarray, n_pupil: int, *, gain: float, leak: float, latency: int, n_analysed: int, block: int) -> tuple[np.ndarray, np.ndarray]:
    """Quadratic forms ``M_block`` and ``M_window`` in the state ``x`` at the first analysed frame.

    ``x^T M x`` is the mean over the first ``block`` (resp. all ``n_analysed``)
    analysed frames of ``(F^j x)^T Gt (F^j x) / n_pupil`` with ``Gt`` the
    pupil Gram matrix on the leading block (``j = 1 .. N``: the state before
    the update at the first analysed frame contributes from the first
    analysed value on).  Only the leading block row of ``F^j`` is needed.
    """

    size = loop.shape[0]
    full = size * (latency + 1)
    values, vectors = np.linalg.eigh(gram)
    half = (vectors * np.sqrt(np.clip(values, 0.0, None))) @ vectors.T / np.sqrt(n_pupil)
    first_row = np.zeros((size, full))
    first_row[:, :size] = np.eye(size)
    m_block = np.zeros((full, full))
    m_window = np.zeros((full, full))
    for j in range(1, n_analysed + 1):
        first_row = _advance_first_block_row(first_row, loop, gain=gain, leak=leak, latency=latency)
        weighted = half @ first_row
        term = weighted.T @ weighted
        m_window += term
        if j <= block:
            m_block += term
    return m_block / block, m_window / n_analysed


def generalized_max_eigenvalue(m_window: np.ndarray, m_block: np.ndarray, basis: np.ndarray | None = None) -> tuple[float | None, float, np.ndarray | None]:
    """``max_x (x^T M_window x) / (x^T M_block x)`` over the range of ``M_block`` (within ``basis`` if given), the relative size of ``M_window`` on the null space of ``M_block``, and the maximizing state."""

    if basis is not None:
        m_window = basis.T @ m_window @ basis
        m_block = basis.T @ m_block @ basis
    values, vectors = np.linalg.eigh(0.5 * (m_block + m_block.T))
    scale = max(float(values.max()), 1.0e-300)
    keep = values > 1.0e-12 * scale
    if not np.any(keep):
        return None, 0.0, None
    whitened = vectors[:, keep] / np.sqrt(values[keep])
    reduced = whitened.T @ (0.5 * (m_window + m_window.T)) @ whitened
    reduced_values, reduced_vectors = np.linalg.eigh(reduced)
    top = whitened @ reduced_vectors[:, -1]
    null = vectors[:, ~keep]
    on_null = float(np.linalg.eigvalsh(null.T @ m_window @ null).max() / scale) if null.shape[1] else 0.0
    state = top if basis is None else basis @ top
    return float(reduced_values[-1]), on_null, state


def sensed_subspace_basis(loop: np.ndarray, latency: int, *, threshold: float = UNSENSED_FEEDBACK) -> tuple[np.ndarray | None, int]:
    """Orthonormal basis of the companion states built from the modes the operator senses (feedback at or above ``threshold``), and the count of unsensed modes."""

    values, vectors = linalg.eig(loop)
    unsensed = np.real(values) < threshold
    count = int(np.count_nonzero(unsensed))
    if count == 0:
        return None, 0
    columns = np.column_stack([np.real(vectors[:, ~unsensed]), np.imag(vectors[:, ~unsensed])])
    sensed = linalg.orth(columns)
    return np.kron(np.eye(latency + 1), sensed), count


def unsensed_injection(loop: np.ndarray, response: np.ndarray, *, threshold: float = UNSENSED_FEEDBACK) -> float | None:
    """``max_w |w^T R| / (|w| |R|_2)`` over left eigenvectors ``w`` of ``L`` with feedback below ``threshold`` (zero for Tikhonov-type reconstructors); None without unsensed modes."""

    values, left = linalg.eig(loop.T)
    unsensed = np.real(values) < threshold
    if not np.any(unsensed):
        return None
    norm = float(np.linalg.norm(response, 2))
    worst = 0.0
    for column in np.nonzero(unsensed)[0]:
        for w in (np.real(left[:, column]), np.imag(left[:, column])):
            size = float(np.linalg.norm(w))
            if size > 1.0e-12:
                worst = max(worst, float(np.linalg.norm(w @ response) / (size * norm)))
    return worst


def stationary_covariance(response: np.ndarray, loop: np.ndarray, sigma: np.ndarray, *, gain: float, leak: float, latency: int, full_state: bool = False) -> tuple[np.ndarray | None, float, float | None]:
    """Stationary ``Cov(dc)`` (the full companion covariance with ``full_state``), the spectral radius of ``F`` and the Lyapunov residual; ``None`` when a unit pole leaves no stationary limit."""

    size = response.shape[0]
    transition = transition_matrix(loop, gain=gain, leak=leak, latency=latency)
    radius = float(np.max(np.abs(np.linalg.eigvals(transition))))
    if radius >= 1.0 - 1.0e-12:
        return None, radius, None
    forcing = forcing_matrix(response, sigma, gain=gain, latency=latency)
    covariance = linalg.solve_discrete_lyapunov(transition, forcing)
    covariance = 0.5 * (covariance + covariance.T)
    residual = float(np.linalg.norm(covariance - transition @ covariance @ transition.T - forcing) / max(np.linalg.norm(forcing), 1e-300))
    return (covariance if full_state else covariance[:size, :size]), radius, residual


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
    forcing = forcing_block(np.eye(1), np.eye(1), gain=0.3)
    window_mean, _ = window_covariance(np.eye(1), forcing, gain=0.3, leak=0.0, latency=2, n_steps=400, burn_in=100)
    window_check = {"window_mean_variance": float(window_mean[0, 0]), "kappa": scalar_kappa(0.3, 0.0, 2), "relative_difference": float(window_mean[0, 0] / scalar_kappa(0.3, 0.0, 2) - 1.0)}
    delay_checks = []
    for latency in (0, 1, 2):
        zero_mean, state_d = window_covariance(np.eye(1), forcing_block(np.eye(1), np.eye(1), gain=0.3), gain=0.3, leak=0.0, latency=latency, n_steps=latency + 1, burn_in=0)
        first_nonzero = float(state_d[0, 0])
        delay_checks.append({"latency": latency, "sum_of_first_d_variances": float(zero_mean[0, 0]) * (latency + 1) - first_nonzero, "variance_after_update_d": first_nonzero, "expected_after_update_d": 0.3**2})
    unit_pole = stationary_covariance(np.eye(1), np.zeros((1, 1)), np.eye(1), gain=0.3, leak=0.0, latency=2)
    # Operator sequence and carried state: a constant sequence equals the modal transient; a sequence whose
    # burn-in operator is silent (R = 0: no feedback, no injection) equals the cold start at the window; a
    # window started from the stationary state stays stationary; the cold start lies below the modal value.
    loop2 = np.array([[1.0, 0.05], [0.05, 0.7]])
    sigma2 = np.array([[1.0, 0.2], [0.2, 0.5]])
    forcing2 = forcing_block(np.eye(2), sigma2, gain=0.3)
    modal_window, _ = window_covariance(loop2, forcing2, gain=0.3, leak=0.0, latency=2, n_steps=120, burn_in=40)
    constant = time_varying_window([loop2], [forcing2], np.zeros(120, dtype=int), gain=0.3, leak=0.0, latency=2, n_steps=120, burn_in=40)
    cold, _ = window_covariance(loop2, forcing2, gain=0.3, leak=0.0, latency=2, n_steps=120, burn_in=40, initial_state=np.zeros((6, 6)), start_frame=40)
    switched = time_varying_window([loop2, np.zeros((2, 2))], [forcing2, np.zeros((2, 2))], np.array([1] * 40 + [0] * 80), gain=0.3, leak=0.0, latency=2, n_steps=120, burn_in=40)
    full_stationary, _, _ = stationary_covariance(np.eye(2), loop2, sigma2, gain=0.3, leak=0.0, latency=2, full_state=True)
    warm, _ = window_covariance(loop2, forcing2, gain=0.3, leak=0.0, latency=2, n_steps=120, burn_in=40, initial_state=full_stationary, start_frame=40, forcing_from=40)
    sequence_checks = {
        "constant_sequence_equals_modal": float(np.max(np.abs(constant - modal_window)) / np.max(np.abs(modal_window))),
        "silent_burn_in_equals_cold_start": float(np.max(np.abs(switched - cold)) / np.max(np.abs(cold))),
        "stationary_start_window_over_stationary": float(np.trace(warm) / np.trace(full_stationary[:2, :2])),
        "cold_start_window_over_modal": float(np.trace(cold) / np.trace(modal_window)),
    }
    # Carried-state sensitivity: the leading-block-row recurrence equals explicit powers of F; the maximizing
    # state's ratio equals gamma when simulated directly; an unsensed mode (feedback 0) carries its state at
    # ratio one and receives no injection from a reconstructor with the matching left null vector.
    gram3 = np.array([[2.0, 0.3, 0.0], [0.3, 1.0, 0.1], [0.0, 0.1, 0.5]])
    m_block3, m_window3 = window_sensitivity(loop3, gram3, 1, gain=0.3, leak=0.0, latency=2, n_analysed=60, block=25)
    transition3 = transition_matrix(loop3, gain=0.3, leak=0.0, latency=2)
    weighted3 = np.zeros((9, 9))
    weighted3[:3, :3] = gram3
    power = np.eye(9)
    explicit_window = np.zeros((9, 9))
    explicit_block = np.zeros((9, 9))
    for j in range(1, 61):
        power = transition3 @ power
        term = power.T @ weighted3 @ power
        explicit_window += term / 60
        if j <= 25:
            explicit_block += term / 25
    recurrence_error = float(max(np.max(np.abs(m_window3 - explicit_window)), np.max(np.abs(m_block3 - explicit_block))) / np.max(np.abs(explicit_window)))
    loop_mixed = np.diag([1.0, 0.0])
    response_mixed = np.diag([1.0, 0.0])
    m_block_mixed, m_window_mixed = window_sensitivity(loop_mixed, np.eye(2), 1, gain=0.3, leak=0.0, latency=2, n_analysed=300, block=25)
    gamma_all, _, state_all = generalized_max_eigenvalue(m_window_mixed, m_block_mixed)
    basis_mixed, unsensed_count = sensed_subspace_basis(loop_mixed, 2)
    gamma_sensed, _, state_sensed = generalized_max_eigenvalue(m_window_mixed, m_block_mixed, basis_mixed)

    def direct_ratio(state: np.ndarray) -> float:
        x = state.copy()
        values = []
        for _ in range(300):
            x = transition_matrix(loop_mixed, gain=0.3, leak=0.0, latency=2) @ x
            values.append(float(x[:2] @ x[:2]))
        return float(np.mean(values) / np.mean(values[:25]))

    rng2 = np.random.default_rng(11)
    pupil_toy = rng2.standard_normal((40, 3))
    pupil_toy -= pupil_toy.mean(axis=0)
    state_toy = rng2.standard_normal((3, 7))
    difference_toy = -(pupil_toy @ state_toy).T
    q_toy, r_toy = np.linalg.qr(pupil_toy)
    recovered = -linalg.solve_triangular(r_toy, q_toy.T @ difference_toy.T)
    range_basis = linalg.orth(np.column_stack([np.diag([1.0, 0.0]), np.diag([1.0, 0.0])]), rcond=1.0e-8)
    sensitivity_checks = {
        "state_recovered_from_map_difference": float(np.max(np.abs(recovered - state_toy))),
        "range_basis_dimension_of_rank_one_operators": int(range_basis.shape[1]),
        "recurrence_vs_explicit_powers": recurrence_error,
        "gamma_all_unsensed_mode_persists": gamma_all,
        "gamma_sensed_unit_feedback": gamma_sensed,
        "gamma_sensed_equals_direct_simulation_of_maximizer": float(gamma_sensed - direct_ratio(state_sensed)),
        "unsensed_modes_found": unsensed_count,
        "unsensed_injection_of_matching_reconstructor": unsensed_injection(loop_mixed, response_mixed),
        "sensed_maximizer_has_no_unsensed_component": float(np.max(np.abs(state_sensed[1::2]))),
    }
    # Review round 7: the adjoint functional against forward propagation, the 2 x 2 box extremes against a
    # dense grid, the admissible extremes against random admissible covariances, a constant operator sequence
    # against the modal cold start, and a carried state that the modal operator leaves unsensed.
    rng3 = np.random.default_rng(7)
    size_t, rows_t, latency_t, gain_t, leak_t = 3, 6, 2, 0.4, 0.01
    interaction_t = rng3.standard_normal((rows_t, size_t))
    responses_t = []
    for dropped in ((), (4, 5)):
        response_t = np.linalg.pinv(interaction_t) * 0.8
        response_t[:, list(dropped)] = 0.0
        responses_t.append(response_t)
    loops_t = [response_t @ interaction_t for response_t in responses_t]
    gram_t = np.diag([1.0, 0.5, 2.0])
    sequence_t = rng3.integers(0, 2, size=60)
    sigma_t = rng3.standard_normal((rows_t, rows_t))
    sigma_t = sigma_t @ sigma_t.T
    blocks_t = [forcing_block(response_t, sigma_t, gain=gain_t) for response_t in responses_t]
    forward_t = time_varying_cold(loops_t, blocks_t, sequence_t, gain=gain_t, leak=leak_t, latency=latency_t, n_steps=60, start=20, forcing_from=22, gram=gram_t, n_pupil=1)
    functional_t = time_varying_cold_functional(loops_t, responses_t, sequence_t, gain=gain_t, leak=leak_t, latency=latency_t, n_steps=60, start=20, forcing_from=22, gram=gram_t, n_pupil=1)
    adjoint_error = abs(float(np.sum(functional_t * sigma_t)) - forward_t) / abs(forward_t)
    box_gap = 0.0
    for trial in range(200):
        a_t, b_t, h_t = rng3.standard_normal(3)
        p_t = tuple(sorted(rng3.uniform(0.0, 2.0, 2)))
        q_t = tuple(sorted(rng3.uniform(0.0, 2.0, 2)))
        (low_t, _, _), (high_t, _, _) = quadratic_box_extremes(float(a_t), float(b_t), float(h_t), (float(p_t[0]), float(p_t[1])), (float(q_t[0]), float(q_t[1])))
        grid_p, grid_q = np.meshgrid(np.linspace(p_t[0], p_t[1], 301), np.linspace(q_t[0], q_t[1], 301))
        grid_values = a_t * grid_p**2 + b_t * grid_q**2 + 2.0 * h_t * grid_p * grid_q
        box_gap = max(box_gap, float(np.min(grid_values) - low_t) * -1.0 if np.min(grid_values) < low_t else 0.0, float(np.max(grid_values) - high_t) if np.max(grid_values) > high_t else 0.0)
    indefinite = rng3.standard_normal((rows_t, rows_t))
    indefinite = 0.5 * (indefinite + indefinite.T)
    admissible_t = [{"lenslet": "a", "rows": [0, 1], "lower_px2": [0.0, 0.2], "upper_px2": [1.5, 0.9]}, {"lenslet": "b", "rows": [2, 3], "lower_px2": [0.1, 0.0], "upper_px2": [0.4, 2.0]}]
    base_t = np.zeros((rows_t, rows_t))
    base_t[4:, 4:] = np.array([[0.7, 0.1], [0.1, 0.5]])
    extremes_t = admissible_extremes(indefinite, base_t, admissible_t)
    escapes = 0
    for trial in range(4000):
        sample = base_t.copy()
        for entry in admissible_t:
            s_x = rng3.uniform(entry["lower_px2"][0], entry["upper_px2"][0])
            s_y = rng3.uniform(entry["lower_px2"][1], entry["upper_px2"][1])
            c_t = rng3.uniform(-1.0, 1.0) * np.sqrt(s_x * s_y)
            x_row, y_row = entry["rows"]
            sample[x_row, x_row], sample[y_row, y_row], sample[x_row, y_row], sample[y_row, x_row] = s_x, s_y, c_t, c_t
        value_t = float(np.sum(indefinite * sample))
        escapes += int(value_t < extremes_t["min"] - 1.0e-12 or value_t > extremes_t["max"] + 1.0e-12)
    attained = max(abs(float(np.sum(indefinite * extremes_t["sigma_max"])) - extremes_t["max"]), abs(float(np.sum(indefinite * extremes_t["sigma_min"])) - extremes_t["min"]))
    corners_only = []
    for low_x, low_y in ((0, 0), (1, 1)):
        corner = base_t.copy()
        for entry in admissible_t:
            x_row, y_row = entry["rows"]
            corner[x_row, x_row] = entry["upper_px2"][0] if low_x else entry["lower_px2"][0]
            corner[y_row, y_row] = entry["upper_px2"][1] if low_y else entry["lower_px2"][1]
        corners_only.append(float(np.sum(indefinite * corner)))
    constant_t = np.zeros(60, dtype=int)
    cold_constant = time_varying_cold(loops_t, blocks_t, constant_t, gain=gain_t, leak=leak_t, latency=latency_t, n_steps=60, start=20, forcing_from=22, gram=gram_t, n_pupil=1)
    cold_modal_block, _ = window_covariance(loops_t[0], blocks_t[0], gain=gain_t, leak=leak_t, latency=latency_t, n_steps=60, burn_in=20, initial_state=np.zeros((size_t * (latency_t + 1),) * 2), start_frame=20)
    constant_error = abs(cold_constant - float(np.sum(gram_t * cold_modal_block))) / abs(cold_constant)
    # A carried state in a mode the modal operator does not sense, while the actual operators of the first
    # window frames do: the modal propagation keeps it, the actual one removes it.
    loop_modal_t = np.diag([1.0, 0.0])
    loop_actual_t = np.diag([1.0, 1.0])
    gram_two = np.eye(2)
    start_t = np.array([0.0, 1.0])
    kept = deterministic_window(start_t, [np.zeros(2), np.zeros(2)], first_frame=0, n_steps=100, include_start=False, loop_at=lambda frame: loop_modal_t, forcing_at=lambda frame: None, gain=0.4, leak=0.0, gram=gram_two, n_pupil=1)
    removed = deterministic_window(start_t, [np.zeros(2), np.zeros(2)], first_frame=0, n_steps=100, include_start=False, loop_at=lambda frame: loop_actual_t if frame < 30 else loop_modal_t, forcing_at=lambda frame: None, gain=0.4, leak=0.0, gram=gram_two, n_pupil=1)
    operator_error_checks = {
        "adjoint_functional_vs_forward_relative": adjoint_error,
        "box_extremes_beyond_grid": box_gap,
        "admissible_samples_outside_extremes_of_4000": escapes,
        "admissible_extremes_attained": attained,
        "indefinite_functional_extremes": [extremes_t["min"], extremes_t["max"]],
        "indefinite_functional_variance_corners": corners_only,
        "constant_sequence_cold_equals_modal_cold": constant_error,
        "carried_mode_unsensed_by_modal_operator_window_ratio_actual_over_modal": float(np.mean(removed) / np.mean(kept)),
    }
    passed = (
        all(abs(case["relative_difference"]) < 1.0e-6 for case in cases)
        and all(abs(entry["variance_in_3x3"] / entry["variance_alone"] - 1.0) < 1.0e-9 for entry in modal)
        and propagation_error < 1.0e-12
        and abs(window_check["relative_difference"]) < 1.0e-6
        and all(abs(check["sum_of_first_d_variances"]) < 1.0e-15 and abs(check["variance_after_update_d"] - 0.3**2) < 1.0e-12 for check in delay_checks)
        and unit_pole[0] is None and abs(unit_pole[1] - 1.0) < 1.0e-12
        and sequence_checks["constant_sequence_equals_modal"] < 1.0e-12
        and sequence_checks["silent_burn_in_equals_cold_start"] < 1.0e-12
        and abs(sequence_checks["stationary_start_window_over_stationary"] - 1.0) < 1.0e-9
        and 0.0 < sequence_checks["cold_start_window_over_modal"] < 1.0
        and sensitivity_checks["recurrence_vs_explicit_powers"] < 1.0e-12
        and abs(sensitivity_checks["gamma_all_unsensed_mode_persists"] - 1.0) < 1.0e-9
        and 0.0 < sensitivity_checks["gamma_sensed_unit_feedback"] < 0.2
        and abs(sensitivity_checks["gamma_sensed_equals_direct_simulation_of_maximizer"]) < 1.0e-9
        and sensitivity_checks["unsensed_modes_found"] == 1
        and sensitivity_checks["unsensed_injection_of_matching_reconstructor"] < 1.0e-12
        and sensitivity_checks["sensed_maximizer_has_no_unsensed_component"] < 1.0e-9
        and sensitivity_checks["state_recovered_from_map_difference"] < 1.0e-12
        and sensitivity_checks["range_basis_dimension_of_rank_one_operators"] == 1
        and operator_error_checks["adjoint_functional_vs_forward_relative"] < 1.0e-12
        and operator_error_checks["box_extremes_beyond_grid"] < 1.0e-12
        and operator_error_checks["admissible_samples_outside_extremes_of_4000"] == 0
        and operator_error_checks["admissible_extremes_attained"] < 1.0e-12
        and operator_error_checks["constant_sequence_cold_equals_modal_cold"] < 1.0e-12
        and operator_error_checks["carried_mode_unsensed_by_modal_operator_window_ratio_actual_over_modal"] < 0.5
    )
    return {"unit_feedback_cases": cases, "decoupled_modes_gain_0.3_latency_2": modal, "structured_propagation_max_error": propagation_error, "window_mean_unit_feedback_400_100": window_check, "delayed_injection": delay_checks, "unsensed_mode_has_no_stationary_limit": {"stationary_returned": unit_pole[0], "spectral_radius": unit_pole[1]}, "operator_sequence_and_carried_state": sequence_checks, "carried_state_sensitivity": sensitivity_checks, "operator_error_on_the_conditional_prediction": operator_error_checks, "passed": bool(passed)}


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
    # The sensor's measurement is the centroid minus its zero-phase calibration reference (pixels); the reference
    # is not in the sidecar and does not cancel between the arms on a frame whose two operators differ.
    # (PhysicalShackHartmannSensor.reference_centroids_px; the diffraction sensor keeps it on its calibration).
    reference = getattr(system.wfs, "reference_centroids_px", None)
    if reference is None:
        calibration = getattr(system.wfs, "calibration", None)
        reference = getattr(calibration, "reference_centroids_px", None) if getattr(calibration, "measurement_unit", None) == "pixel" else None
    reference_xy = None
    if reference is not None and matrix.measurement_unit == "pixel":
        reference_xy = np.asarray(reference, dtype=float)
        if reference_xy.shape != (len(system.wfs.subaperture_ids), 2) or not np.all(np.isfinite(reference_xy)):
            reference_xy = None
    return {"interaction": dense, "pupil_response": columns, "row_ids": row_ids, "coordinate_ids": coordinate_ids, "n_pupil": n_pupil, "pupil_mask": pupil, "lenslet_ids": tuple(system.wfs.subaperture_ids), "reference_xy_px": reference_xy}


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


def sigma_from_sidecar(metadata: dict[str, Any], arrays: dict[str, np.ndarray], row_ids: tuple[str, ...], n_pupil: int, *, min_fraction: float, outside_min_frames: int, model_margin: float) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray], dict[str, Any], dict[str, Any]]:
    """Noise covariances and row masks under the ``effective``, ``available`` and ``strict`` rules, the operator record and the measured series, and the whole-run operator data for the error bounds."""

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

    # The operator the loop used: the modal effective row set of the noisy arm over the analysed frames,
    # and the sequence of operators over the whole run (burn-in included) for the operator error bound.
    effective_noisy_all = np.asarray(arrays[f"{noisy}__measurement_row_masks"], dtype=bool)
    effective_twin_all = np.asarray(arrays[f"{twin}__measurement_row_masks"], dtype=bool)
    effective_noisy = effective_noisy_all[frames]
    effective_twin = effective_twin_all[frames]
    keys = [row.tobytes() for row in effective_noisy]
    counter = Counter(keys)
    modal_key, modal_count = counter.most_common(1)[0]
    modal_mask = np.frombuffer(modal_key, dtype=bool).copy()
    noisy_match = np.array([key == modal_key for key in keys])
    twin_match = np.all(effective_twin == modal_mask, axis=1)
    noisy_fraction, twin_fraction = float(np.mean(noisy_match)), float(np.mean(twin_match))
    burn_in_frames = int(metadata["burn_in_frames"])
    all_keys = [row.tobytes() for row in effective_noisy_all]
    distinct_all: dict[bytes, int] = {}
    sequence = np.zeros(len(all_keys), dtype=int)
    for frame_number, key in enumerate(all_keys):
        sequence[frame_number] = distinct_all.setdefault(key, len(distinct_all))
    distinct_masks = [np.frombuffer(key, dtype=bool).copy() for key in distinct_all]
    burn_in_match_noisy = float(np.mean([key == modal_key for key in all_keys[:burn_in_frames]])) if burn_in_frames else None
    burn_in_match_twin = float(np.mean(np.all(effective_twin_all[:burn_in_frames] == modal_mask, axis=1))) if burn_in_frames else None
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
        "definition": "the row set the noisy arm's reconstructor used in the plurality of analysed frames (<arm>__measurement_row_masks); the model's operator R is probed on exactly this set; whether the fixed operator describes the run is decided by the error bounds in prediction.operator_bounds, not by these fractions",
        "rows_in_modal_mask": int(np.count_nonzero(modal_mask)), "rows_total": n_rows,
        "distinct_effective_masks_noisy_analysed": len(counter),
        "distinct_effective_masks_noisy_all_frames": len(distinct_masks),
        "noisy_frames_under_modal_operator": int(modal_count), "noisy_match_fraction": noisy_fraction,
        "twin_frames_under_modal_operator": int(np.count_nonzero(twin_match)), "twin_match_fraction": twin_fraction,
        "burn_in_match_fraction_noisy": burn_in_match_noisy, "burn_in_match_fraction_twin": burn_in_match_twin,
        "rows_always_effective_noisy": int(np.count_nonzero(np.all(effective_noisy, axis=0))),
        "rows_ever_effective_noisy": int(np.count_nonzero(np.any(effective_noisy, axis=0))),
        "sigma_frames": sigma_frames_rule,
    }

    # Telemetry-based sensitivities.
    usable = valid & supported & finite
    fraction = np.mean(usable, axis=0)
    # The modal rows keep the effective rule's blocks exactly; the rows outside the modal mask get an admissible
    # set (below), over which the operator error is extremized exactly.
    usable_counts = np.count_nonzero(usable, axis=0)
    model_sigma = np.asarray(arrays[f"{noisy}__telemetry__centroid_sigma_xy_px"], dtype=float)[frames]
    # Calibration of the sensor-model margin on this run's lenslets with an estimate of their own: per axis the
    # realized variance over the usable analysed frames against the largest sensor-model variance at that spot in
    # the same frames, with the 97.5 % chi-square upper bound of the ratio. The sensor model carries each spot's
    # own flux, background and read noise; the margin covers its mismatch, which this calibration measures.
    calibration_rows: list[tuple[float, float, float]] = []
    for lenslet in range(len(lenslets)):
        count = int(usable_counts[lenslet])
        if count < outside_min_frames:
            continue
        for axis in range(2):
            model_values = model_sigma[usable[:, lenslet], lenslet, axis]
            model_values = model_values[np.isfinite(model_values) & (model_values > 0.0)]
            if model_values.size == 0:
                continue
            ratio = float(np.var(residual[usable[:, lenslet], lenslet, axis], ddof=1) / np.max(model_values) ** 2)
            calibration_rows.append((ratio, ratio * float((count - 1) / stats.chi2.ppf(0.025, count - 1)), float(np.max(model_values) ** 2)))
    calibration_array = np.asarray(calibration_rows, dtype=float).reshape(-1, 3)
    low_snr = calibration_array[calibration_array[:, 2] >= np.quantile(calibration_array[:, 2], 0.75)] if calibration_array.size else calibration_array
    margin_calibration = {
        "definition": "per axis of every lenslet with at least outside_min_frames usable analysed frames: realized variance over those frames divided by the largest sensor-model variance (centroid_sigma_xy_px squared) at that spot in the same frames, and the 97.5 % chi-square upper bound of that ratio; the quarter with the largest model variance (the faintest spots, those nearest to dropping out) is reported apart; a bracket whose upper end rests on the model term needs the largest upper bound at or below the margin",
        "axes": int(calibration_array.shape[0]),
        "ratio_median": None if not calibration_array.size else float(np.median(calibration_array[:, 0])),
        "ratio_max": None if not calibration_array.size else float(np.max(calibration_array[:, 0])),
        "ratio_upper_97_5_max": None if not calibration_array.size else float(np.max(calibration_array[:, 1])),
        "faintest_quarter_ratio_max": None if not low_snr.size else float(np.max(low_snr[:, 0])),
        "faintest_quarter_ratio_upper_97_5_max": None if not low_snr.size else float(np.max(low_snr[:, 1])),
        "margin": float(model_margin),
        "margin_covers": None if not calibration_array.size else bool(np.max(calibration_array[:, 1]) <= model_margin),
    }
    # The admissible covariance of the rows outside the modal mask (review round 7): every lenslet with such a row
    # that some operator of the noisy arm used gets, per axis, an interval for its variance and, for the 2 x 2
    # block, every positive-semidefinite completion (the cross term free within |c| <= sqrt(s_x s_y)); the
    # operator error is then extremized exactly over the product of these sets (operator_bounds). A lenslet
    # with at least outside_min_frames usable analysed frames takes the two-sided 95 % chi-square interval of
    # its own realized variance; a lenslet with fewer takes [0, max(97.5 % chi-square upper bound over its usable
    # frames (two or more), model_margin times the sensor model's variance at its own spot)], the model term
    # only where the margin calibration supports it. An axis inside the modal mask keeps the effective estimate.
    admissible: list[dict[str, Any]] = []
    unbounded: list[str] = []
    rows_outside = 0
    for lenslet in range(len(lenslets)):
        pair = rows[lenslet]
        inside = modal_mask[pair]
        if np.all(inside):
            continue
        if not np.any(effective_noisy_all[:, pair]):
            # rows no operator of the run ever used: their covariance enters no transient
            continue
        rows_outside += int(np.count_nonzero(~inside))
        count = int(usable_counts[lenslet])
        effective_frames = np.any(effective_noisy[:, pair], axis=1)
        sparse = count < outside_min_frames
        entry: dict[str, Any] = {"lenslet": lenslets[lenslet], "rows": [int(pair[0]), int(pair[1])], "usable_frames": count, "effective_frames": int(np.count_nonzero(effective_frames)), "rule": "sparse: [0, max(chi-square upper, model term)]" if sparse else "two-sided 95 % chi-square interval of its own variance", "per_axis": []}
        low: list[float | None] = [None, None]
        high: list[float | None] = [None, None]
        for axis in range(2):
            detail: dict[str, Any] = {"axis": "xy"[axis], "inside_modal_mask": bool(inside[axis])}
            if inside[axis]:
                value = float(sigma_effective[pair[axis], pair[axis]])
                low[axis] = high[axis] = value
                detail.update({"lower_px2": value, "upper_px2": value, "source": "effective estimate (inside the modal mask)"})
                entry["per_axis"].append(detail)
                continue
            variance = own_low = own_high = None
            if count >= 2:
                variance = float(np.var(residual[usable[:, lenslet], lenslet, axis], ddof=1))
                own_low = variance * float((count - 1) / stats.chi2.ppf(0.975, count - 1))
                own_high = variance * float((count - 1) / stats.chi2.ppf(0.025, count - 1))
            model_values = model_sigma[effective_frames, lenslet, axis]
            model_values = model_values[np.isfinite(model_values)]
            model = None if model_values.size == 0 else float(model_margin * np.max(model_values) ** 2)
            if sparse:
                usable_model = model if margin_calibration["margin_covers"] is True else None
                candidates = [value for value in (own_high, usable_model) if value is not None]
                low[axis] = 0.0
                high[axis] = max(candidates) if candidates else None
                rests_on_model = bool(usable_model is not None and high[axis] == usable_model)
            else:
                low[axis], high[axis] = own_low, own_high
                rests_on_model = False
            detail.update({"own_variance_px2": variance, "own_lower_97_5_px2": own_low, "own_upper_97_5_px2": own_high, "model_upper_px2": model, "lower_px2": low[axis], "upper_px2": high[axis], "upper_rests_on_model": rests_on_model})
            if sparse and model is not None and margin_calibration["margin_covers"] is not True:
                detail["model_term_refused"] = "the margin is not supported by this run's estimated lenslets (margin_calibration)"
            entry["per_axis"].append(detail)
        entry["lower_px2"] = low
        entry["upper_px2"] = high
        if high[0] is None or high[1] is None or low[0] is None or low[1] is None:
            unbounded.append(lenslets[lenslet])
        admissible.append(entry)
    bracket = {
        "definition": f"the admissible covariance of the rows outside the modal mask that some operator of the noisy arm used: per lenslet, each axis variance in an interval (at least {outside_min_frames} usable analysed frames: the two-sided 95 % chi-square interval of its own realized variance; fewer: from zero to the larger of the 97.5 % chi-square upper bound over its usable frames, two or more, and {model_margin:g} times the sensor model's variance at its own spot in the frames its rows were effective, the model term only where the margin calibration supports it; an axis inside the modal mask keeps the effective estimate) and every positive-semidefinite 2 x 2 block with those variances; the operator error is extremized exactly over the product of these sets (prediction.operator_bounds.operator_error); a lenslet without an interval makes the run not assessable; a lenslet whose rows no operator of the run used is skipped",
        "outside_min_frames": int(outside_min_frames),
        "model_margin": float(model_margin),
        "rows_outside_modal_mask": rows_outside,
        "lenslets_admissible": [entry["lenslet"] for entry in admissible],
        "lenslets_sparse": [entry["lenslet"] for entry in admissible if entry["usable_frames"] < outside_min_frames],
        "lenslets_without_bound": unbounded,
        "details": admissible,
        "margin_calibration": margin_calibration,
    }
    # Gate activity before the window (what the linear model does not carry into it).
    all_frames = np.arange(len(all_keys))
    burn_in_index = all_frames[:burn_in_frames]
    disagreement_all = np.asarray(arrays["mask_disagreement_rows"], dtype=float)
    usable_all = {arm: np.asarray(arrays[f"{arm}__reconstruction_usable"], dtype=bool) for arm in (noisy, twin)}
    acted_any = {arm: recovery_acted(metadata.get("arms", {}).get(arm, {}).get("recovery")) for arm in (noisy, twin)}
    burn_in_disagreement = float(np.sum(disagreement_all[burn_in_index]) / (n_rows * burn_in_frames)) if burn_in_frames else 0.0
    burn_in_rejected = {arm: int(np.count_nonzero(~usable_all[arm][burn_in_index])) for arm in (noisy, twin)}
    saturation_all = {arm: np.asarray(arrays[f"{arm}__saturation_fraction"], dtype=float) for arm in (noisy, twin)}
    burn_in_saturation = {arm: (float(np.mean(saturation_all[arm][burn_in_index])) if burn_in_frames else 0.0) for arm in (noisy, twin)}
    disagreement_frames = disagreement_all[burn_in_index] > 0
    rejected_frames = ~usable_all[noisy][burn_in_index] | ~usable_all[twin][burn_in_index]
    saturated_frames = (saturation_all[noisy][burn_in_index] > 1.0e-3) | (saturation_all[twin][burn_in_index] > 1.0e-3)
    unmodelled = disagreement_frames | rejected_frames | saturated_frames
    if any(acted_any.values()):
        unmodelled = np.ones(burn_in_frames, dtype=bool)
    last_unmodelled = int(np.flatnonzero(unmodelled).max()) if np.any(unmodelled) else None
    burn_in = {
        "definition": "burn-in frames the linear model does not carry into the analysed window: a frame with gate activity (a row on which the two arms' masks differ, a rejected reconstruction in either arm, or a recovery action, which the counters give only run-wide and then mark every burn-in frame) or with command saturation above 1e-3 in either arm; a burn-in without such a frame is quiet and carries the modelled state",
        "frames": burn_in_frames,
        "mask_disagreement_row_frames_fraction": burn_in_disagreement,
        "frames_with_mask_disagreement": int(np.count_nonzero(disagreement_frames)),
        "rejected_frames": burn_in_rejected,
        "recovery_acted": acted_any,
        "saturation_fraction_mean": burn_in_saturation,
        "frames_with_saturation": int(np.count_nonzero(saturated_frames)),
        "unmodelled_frames": int(np.count_nonzero(unmodelled)),
        "last_unmodelled_frame": last_unmodelled,
        "quiet": last_unmodelled is None,
    }
    twin_keys = {row.tobytes() for row in effective_twin_all}
    twin_only_masks = [np.frombuffer(key, dtype=bool).copy() for key in sorted(twin_keys) if key not in distinct_all]
    run_flags = {
        "definition": "frames of the whole run (burn-in and window, either arm) that take the command difference out of the span of the operators' ranges: command clipping, a rejected reconstruction, a recovery action (run-level counters); with none of them the carried-state bound runs over that span, otherwise over every state",
        "frames": int(len(all_keys)),
        "saturated_frames_any_arm": int(np.count_nonzero((saturation_all[noisy] > 0.0) | (saturation_all[twin] > 0.0))),
        "rejected_frames_any_arm": int(np.count_nonzero(~usable_all[noisy] | ~usable_all[twin])),
        "recovery_acted": bool(any(acted_any.values())),
        "arm_disagreement_frames": int(np.count_nonzero(disagreement_all > 0)),
        "arm_disagreement_frames_in_window": int(np.count_nonzero(disagreement_all[frames] > 0)),
    }
    run_flags["state_space_restricted"] = bool(run_flags["saturated_frames_any_arm"] == 0 and run_flags["rejected_frames_any_arm"] == 0 and not run_flags["recovery_acted"])
    operator_data = {
        "distinct_masks": distinct_masks, "sequence": sequence, "modal_index": int(distinct_all[modal_key]),
        "sigma_base": sigma_effective, "bracket": bracket, "burn_in": burn_in,
        "delta_v": delta_v, "analysed_frames": frames, "twin_only_masks": twin_only_masks, "run_flags": run_flags, "arms": (noisy, twin),
        "rows": rows,
        "centroids": {arm: np.asarray(arrays[f"{arm}__telemetry__centroids_xy_px"], dtype=float) for arm in (noisy, twin)},
        "effective_masks": {noisy: effective_noisy_all, twin: effective_twin_all},
    }
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
    rejected = {arm: int(np.count_nonzero(~usable_all[arm][frames])) for arm in (noisy, twin)}
    acted = acted_any
    disagreement = disagreement_all[frames]
    map_pupil = int(np.count_nonzero(arrays["residual_maps__pupil_mask"])) if "residual_maps__pupil_mask" in arrays else None
    info = {
        "source": "sidecar_realized_residuals (c_noisy - c_expected on the noisy arm's lenslets, ddof 1, 2x2 per lenslet)",
        "sidecar_schema": metadata["schema"],
        "label": metadata["label"],
        "root_seed": metadata["root_seed"],
        "config_hash": metadata["config_hash"],
        "analysed_frames": int(frames.size),
        "operator": operator,
        "burn_in": burn_in,
        "bracket": bracket,
        "run_flags": run_flags,
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
    return sigmas, masks, info, operator_data


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
    parser.add_argument("--admissible-samples", type=int, default=0, help="diagnostic: evaluate the operator error by forward propagation at this many random admissible covariances (seeded) and count those outside the exact extremes; also records the unconditional in-window component (the round-6 operator error) at the samples and at its two bracket ends")
    parser.add_argument("--closure-band", type=float, default=0.10, help="the closure test's band b (PROTOCOL.md 1.7): a run whose systematic budget reaches it is not assessable")
    parser.add_argument("--operator-tolerance", type=float, default=0.02, help="largest relative difference between the prediction propagated with the actual operator of every frame (burn-in included) and the modal-operator prediction for the run to count as operator-consistent")
    parser.add_argument("--max-unsensed-injection", type=float, default=1.0e-3, help="largest relative injection of the modal operator into the modes it does not sense (|w^T R| / |w| |R|) for the carried-state bound to use gamma over the sensed states; above it gamma over every state is used")
    parser.add_argument("--outside-estimate-min-frames", type=int, default=10, help="usable analysed frames above which a lenslet outside the modal mask takes the two-sided 95 %% chi-square interval of its own variance; below it the interval runs from zero to the larger of its 97.5 %% chi-square upper bound and the sensor-model term")
    parser.add_argument("--model-variance-margin", type=float, default=2.0, help="factor on the sensor model's variance at a sparse lenslet's own spot for the upper end of its admissible interval (used only where the run's margin calibration supports it)")
    parser.add_argument("--max-distinct-masks", type=int, default=64, help="above this many distinct effective masks in the run the time-varying prediction is not computed (one reconstructor probe per mask) and the run is mask-variable")
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
    pupil_response_bytes = int(pupil_response.nbytes)
    pupil_mask = np.asarray(parts["pupil_mask"], dtype=bool)
    has_maps = metadata is not None and arrays is not None and all(f"residual_maps__{arm}" in arrays for arm in (metadata["noisy_arm"], metadata["twin_arm"]))
    pupil_response_kept: np.ndarray | None = pupil_response if has_maps else None
    del pupil_response
    parts["pupil_response"] = None
    burn_in = int(metadata["burn_in_frames"]) if metadata is not None else int(arguments.burn_in)
    kappa = scalar_kappa(gain, leak, latency)

    operator_data: dict[str, Any] | None = None
    if arguments.sigma == "flat":
        sigmas, masks, sigma_info = sigma_from_flat_wavefront(system, row_ids)
        primary_rule = "flat"
    else:
        sigmas, masks, sigma_info, operator_data = sigma_from_sidecar(metadata, arrays, row_ids, n_pupil, min_fraction=arguments.support_min_fraction, outside_min_frames=arguments.outside_estimate_min_frames, model_margin=arguments.model_variance_margin)
        primary_rule = arguments.support
    sigma_info["primary_rule"] = primary_rule
    if validation is not None:
        sigma_info["sidecar_validation"] = validation

    started = time.perf_counter()
    response_full = reconstructor_matrix(system.reconstructor, row_ids)
    probe_full_s = time.perf_counter() - started
    weights_series = np.einsum("ir,ij,jr->r", response_full, gram, response_full) / n_pupil
    responses: dict[str, np.ndarray] = {}
    loops: dict[str, np.ndarray] = {}

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
        responses[rule], loops[rule] = response, loop
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
        window_block, final_state = window_covariance(loop, forcing_block(response, sigma, gain=gain), gain=gain, leak=leak, latency=latency, n_steps=n_steps, burn_in=burn_in)
        window = float(np.trace(gram @ window_block) / n_pupil)
        window_block_diagonal, _ = window_covariance(loop, forcing_block(response, diagonal_sigma, gain=gain), gain=gain, leak=leak, latency=latency, n_steps=n_steps, burn_in=burn_in)
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
                "unsensed_modes_note": "a mode with feedback below 1e-6 is left unsensed by this mask; with no leak it has a unit pole, no stationary limit exists and the finite-window prediction (the primary quantity) grows with the run length; the count is reported and no rule attaches to it",
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

    inventory: dict[str, int] = {}

    def operator_bounds() -> dict[str, Any]:
        """The operator error (bracketed), the carried-state bound on the operators' state space and the direct state measurement, for the effective rule (sidecar mode)."""

        if operator_data is None:
            return {"status": "not applicable", "reason": "flat mode: no run, no operator sequence"}
        effective = predictions.get("effective")
        if effective is None or effective.get("status") != "defined":
            return {"status": "not applicable", "reason": "the effective rule's operator is not defined for this run"}
        sigma_modal, response_modal, loop_modal = sigmas["effective"], responses["effective"], loops["effective"]
        modal_mask = masks["effective"]
        modal_value = effective["delta_v_exact_window_m2"]
        block_modal = forcing_block(response_modal, sigma_modal, gain=gain)
        weight = gram / n_pupil
        full = size_c * (latency + 1)
        burn_in_state = operator_data["burn_in"]
        run_flags = operator_data["run_flags"]
        noisy_arm, twin_arm = operator_data["arms"]
        reasons: list[str] = []
        not_assessable: list[str] = []
        frames = np.asarray(operator_data["analysed_frames"], dtype=int)
        measured_series = np.asarray(operator_data["delta_v"], dtype=float)

        # The modal transient per frame from frame 0, the cold start at the first analysed frame per frame, and
        # the restart sensitivities of round 4.
        series: list[float] = []
        window_covariance(loop_modal, block_modal, gain=gain, leak=leak, latency=latency, n_steps=n_steps, burn_in=burn_in, weight=weight, series_out=series)
        predicted_all = np.asarray(series)
        cold_series: list[float] = []
        cold_block, _ = window_covariance(loop_modal, block_modal, gain=gain, leak=leak, latency=latency, n_steps=n_steps, burn_in=burn_in, initial_state=np.zeros((full, full)), start_frame=burn_in, weight=weight, series_out=cold_series)
        cold_value = float(np.trace(gram @ cold_block) / n_pupil)
        cold_analysed = np.asarray(cold_series)[frames - burn_in]
        full_stationary, _, _ = stationary_covariance(response_modal, loop_modal, sigma_modal, gain=gain, leak=leak, latency=latency, full_state=True)
        warm_value: float | None = None
        if full_stationary is not None:
            warm_block, _ = window_covariance(loop_modal, block_modal, gain=gain, leak=leak, latency=latency, n_steps=n_steps, burn_in=burn_in, initial_state=full_stationary, start_frame=burn_in, forcing_from=burn_in)
            warm_value = float(np.trace(gram @ warm_block) / n_pupil)
        last_unmodelled = burn_in_state["last_unmodelled_frame"]
        restart_value: float | None = None
        if last_unmodelled is not None:
            restart_block, _ = window_covariance(loop_modal, block_modal, gain=gain, leak=leak, latency=latency, n_steps=n_steps, burn_in=burn_in, initial_state=np.zeros((full, full)), start_frame=last_unmodelled + 1)
            restart_value = float(np.trace(gram @ restart_block) / n_pupil)
        sensitivities = {
            "definition": "restarts of the modal-operator window from a zero state (identical commands, an empty queue): the share of the primary value carried in from before the window (first analysed frame), from before the last burn-in frame with gate activity or saturation, and the window value under a stationary carried state; sensitivities of the modelled state, not bounds on an unknown one",
            "inherited_fraction_from_first_analysed_frame": float((modal_value - cold_value) / modal_value),
            "last_unmodelled_burn_in_frame": last_unmodelled,
            "inherited_fraction_from_last_unmodelled_frame": None if restart_value is None else float((modal_value - restart_value) / modal_value),
            "stationary_start_over_primary": None if warm_value is None else warm_value / modal_value,
        }

        # (1) probe every operator the run used: each distinct effective mask of the noisy arm once (the modal one is
        # already probed) and every further mask of the twin (the reconstruction needs both arms' operators).
        distinct, sequence, modal_index = operator_data["distinct_masks"], operator_data["sequence"], operator_data["modal_index"]
        twin_only = operator_data["twin_only_masks"]
        bracket = operator_data["bracket"]
        response_list: list[np.ndarray] = []
        twin_responses: list[np.ndarray] = []
        loop_list: list[np.ndarray] = []
        probing: dict[str, Any]
        if len(distinct) + len(twin_only) > arguments.max_distinct_masks:
            probing = {"status": "not computed", "reason": f"{len(distinct)} distinct effective masks of the noisy arm and {len(twin_only)} further ones of the twin exceed --max-distinct-masks {arguments.max_distinct_masks}"}
        else:
            refused: str | None = None
            started_probe = time.perf_counter()
            for mask in distinct:
                if np.array_equal(mask, modal_mask):
                    response_list.append(response_modal)
                    loop_list.append(loop_modal)
                    continue
                if np.all(mask):
                    response = response_full
                else:
                    try:
                        response = reconstructor_matrix_masked(system.reconstructor, row_ids, mask, coordinate_ids)
                    except MaskRefused as exc:
                        refused = str(exc)
                        break
                response_list.append(response)
                loop_list.append(response @ dense)
            if refused is None:
                for mask in twin_only:
                    if np.all(mask):
                        twin_responses.append(response_full)
                        continue
                    try:
                        twin_responses.append(reconstructor_matrix_masked(system.reconstructor, row_ids, mask, coordinate_ids))
                    except MaskRefused as exc:
                        refused = str(exc)
                        break
            probe_s = time.perf_counter() - started_probe
            inventory["time_varying_operators"] = int(sum(a.nbytes for a in loop_list) + sum(a.nbytes for a in response_list) + sum(a.nbytes for a in twin_responses))
            if refused is not None:
                probing = {"status": "not computed", "reason": f"an operator one arm used is refused by the reconstructor ({refused}); such a run has rejected frames and is gate-active", "probe_s": probe_s}
            else:
                probing = {"status": "computed", "probe_s": probe_s}
        probing.update({"distinct_masks_all_frames": len(distinct), "twin_only_masks": len(twin_only), "frames_not_under_modal_operator": int(np.count_nonzero(sequence != modal_index)), "burn_in_frames_not_under_modal_operator": int(np.count_nonzero(sequence[:burn_in] != modal_index))})
        if probing["status"] != "computed":
            not_assessable.append(probing["reason"])

        # (2) the command-difference trajectory reconstructed from the telemetry: both arms' centroids minus the
        # sensor's calibration reference (read from the built system; it cancels only on frames where both arms use
        # the same operator) through the operator each arm used in each frame, the controller's leak, gain and delay
        # queue; identical initial commands. The reconstructed per-frame value
        # must reproduce the sidecar's delta_v_m2; then the state the loop carried into the window is measured,
        # its exact contribution to the window is propagated with the modal loop, and the prediction is made
        # conditional on it (review round 6).
        reconstruction: dict[str, Any]
        reference_xy = parts["reference_xy_px"]
        if probing["status"] != "computed":
            reconstruction = {"status": "not reconstructed", "reason": "the operators of the run were not all probed: " + probing["reason"]}
        elif reference_xy is None and run_flags["arm_disagreement_frames"] > 0:
            reconstruction = {"status": "not reconstructed", "reason": "the sensor exposes no pixel calibration reference, and on the run's frames where the two arms' operators differ the reference does not cancel"}
        else:
            started_reconstruction = time.perf_counter()
            response_by_key: dict[bytes, np.ndarray] = {}
            for mask, response in zip(distinct, response_list):
                response_by_key[mask.tobytes()] = response
            for mask, response in zip(twin_only, twin_responses):
                response_by_key[mask.tobytes()] = response
            row_pairs = np.asarray(operator_data["rows"], dtype=int)
            increments = np.zeros((n_steps, size_c))
            unaddable = 0
            for arm, sign in ((noisy_arm, 1.0), (twin_arm, -1.0)):
                centroids = operator_data["centroids"][arm]
                effective_all = operator_data["effective_masks"][arm]
                for frame in range(n_steps):
                    mask = effective_all[frame]
                    measurement = np.zeros(len(row_ids))
                    shifted = centroids[frame] if reference_xy is None else centroids[frame] - reference_xy
                    measurement[row_pairs[:, 0]] = shifted[:, 0]
                    measurement[row_pairs[:, 1]] = shifted[:, 1]
                    bad = mask & ~np.isfinite(measurement)
                    unaddable += int(np.count_nonzero(bad))
                    measurement = np.where(mask & np.isfinite(measurement), measurement, 0.0)
                    increments[frame] += sign * (response_by_key[mask.tobytes()] @ measurement)
            queue: deque[np.ndarray] = deque(np.zeros(size_c) for _ in range(latency))
            state_vector = np.zeros(size_c)
            post_update = np.zeros((n_steps, size_c))
            for frame in range(n_steps):
                queue.append(increments[frame])
                released = queue.popleft()
                state_vector = (1.0 - leak) * state_vector + gain * released
                post_update[frame] = state_vector
            reconstructed_values = np.einsum("ki,ij,kj->k", post_update, gram, post_update) / n_pupil
            reconstructed_analysed = reconstructed_values[frames]
            mean_measured = float(np.mean(measured_series))
            relative_rms = float(np.sqrt(np.mean((reconstructed_analysed - measured_series) ** 2)) / max(mean_measured, 1.0e-300))
            max_relative = float(np.max(np.abs(reconstructed_analysed - measured_series)) / max(mean_measured, 1.0e-300))
            consistent = bool(relative_rms <= RECONSTRUCTION_TOLERANCE and unaddable == 0)
            # The carried state at the first analysed frame and its exact window contribution under the modal loop:
            # the increments still queued are the actual ones; later increments are the modal feedback of the
            # deterministic trajectory (the noise computed from the first analysed frame on is the model's part).
            carried_queue: deque[np.ndarray] = deque(np.zeros(size_c) if frame < 0 else increments[frame] for frame in range(burn_in - latency, burn_in))
            deterministic = post_update[burn_in - 1].copy() if burn_in > 0 else np.zeros(size_c)
            carried_values = np.zeros(n_steps - burn_in)
            for index, frame in enumerate(range(burn_in, n_steps)):
                carried_queue.append(-loop_modal @ deterministic)
                released = carried_queue.popleft()
                deterministic = (1.0 - leak) * deterministic + gain * released
                carried_values[index] = float(deterministic @ gram @ deterministic) / n_pupil
            carried_window = float(np.mean(carried_values))
            carried_first_block = float(np.mean(carried_values[:BLOCK_FRAMES]))
            # Content outside the modal operator's range over the window (a measured fact about the state).
            modal_basis = linalg.orth(response_modal, rcond=1.0e-8)
            analysed_states = post_update[frames]
            perpendicular = analysed_states - (analysed_states @ modal_basis) @ modal_basis.T
            outside_values = np.einsum("ki,ij,kj->k", perpendicular, gram, perpendicular) / n_pupil
            reconstruction = {
                "status": "reconstructed",
                "definition": "dc_{k+1} = (1 - l) dc_k + g inc_{k-d} with inc_k = R_k^noisy m_k^noisy - R_k^twin m_k^twin, m each arm's centroids minus the sensor's calibration reference in the rows its operator used (the reference cancels only where both arms use the same operator), R the probed operator of that frame's effective mask, from identical initial commands and an empty delay queue, exactly as the controller runs; the per-frame piston-removed pupil mean square of W dc must reproduce the sidecar's delta_v_m2 (float32 maps), which checks the controller law, the operators, the units and the absence of clipping on this run",
                "frames": int(n_steps),
                "measurement_entries_not_finite_in_effective_rows": unaddable,
                "reference": "sensor calibration reference_centroids_px (pixels)" if reference_xy is not None else "none: every frame has both arms on the same operator, so it cancels",
                "relative_rms_vs_measured_series": relative_rms,
                "max_relative_deviation_vs_measured_series": max_relative,
                "tolerance": RECONSTRUCTION_TOLERANCE,
                "consistent": consistent,
                "carried_state": {
                    "definition": "the state at the first analysed frame (the command difference and the increments still queued) propagated under the modal loop with no further noise; its mean pupil mean square over the window is the exact contribution of the carried state to the window value, replacing the modelled one; the prediction conditional on the measured carried state is the cold-start model value (noise computed from the first analysed frame on) plus this contribution",
                    "window_contribution_m2": carried_window,
                    "window_contribution_over_primary": carried_window / modal_value,
                    "first_block_contribution_over_primary": carried_first_block / modal_value,
                    "modelled_window_contribution_over_primary": float((modal_value - cold_value) / modal_value),
                    "state_norm_m2_at_first_analysed_frame": float(post_update[burn_in - 1] @ gram @ post_update[burn_in - 1]) / n_pupil if burn_in > 0 else 0.0,
                },
                "content_outside_modal_operator_range": {
                    "definition": "share of the reconstructed state's window value in directions the modal operator cannot produce (the orthogonal complement of its range): a measured fact about the state, zero for a fixed operator without clipping",
                    "window_fraction": float(np.sum(outside_values) / max(float(np.sum(np.einsum("ki,ij,kj->k", analysed_states, gram, analysed_states) / n_pupil)), 1.0e-300)),
                    "modal_range_dimension": int(modal_basis.shape[1]),
                },
                "delta_v_conditional_window_m2": cold_value + carried_window,
                "delta_v_noise_from_first_analysed_frame_m2": cold_value,
                "time_s": time.perf_counter() - started_reconstruction,
            }
            inventory["reconstruction_arrays"] = int(increments.nbytes + post_update.nbytes)
            reconstruction["arm_disagreement_frames"] = int(run_flags["arm_disagreement_frames"])
            if not consistent:
                reconstruction["inconsistency_note"] = "the controller law with the probed operators, recorded centroids and reference does not describe this run to the tolerance: clipped, rejected or recovery frames, or a reconstructor that is not a fixed linear operator at this precision (an iterative solve stopped by its tolerances: with the ci damping 0.001 the probed operator departs from the actual LSMR estimate by 1-5 % per frame, with the 12 m damping 0.1 by at most 1.4e-6); the residual maps then supply the carried state when retained, and the residual stays in the budget"

        # (3) the state space of the carried-state fallback bound (a diagnostic once the trajectory is reconstructed):
        # the span of the ranges of every operator either arm used.
        basis_c: np.ndarray | None = None
        if probing["status"] == "computed":
            basis_c = linalg.orth(np.column_stack(response_list + twin_responses), rcond=1.0e-8)
        restricted = bool(run_flags["state_space_restricted"] and basis_c is not None)
        basis = None if not restricted else np.kron(np.eye(latency + 1), basis_c)
        state_trajectory = None if reconstruction.get("status") != "reconstructed" else post_update
        space = {
            "definition": "with identical initial commands every command difference the paired loop produces from its measurements is an image of a reconstructor, dc_{k+1} = (1 - l) dc_k + g [R_k (s_n - s_t)]_{k-d}, whatever the measurement non-linearity; so the difference state lies in the span of the ranges of the operators either arm used (each distinct effective mask probed once), unless a command was clipped, a reconstruction rejected or a recovery action taken, in which case every state is admitted",
            "restricted": restricted,
            "dimension": int(basis_c.shape[1]) if restricted else size_c,
            "controlled_actuators": size_c,
            "operators_spanned": (len(response_list) + len(twin_responses)) if basis_c is not None else 0,
            "reason_for_all_states": None if restricted else ("the run's operators were not all probed" if basis_c is None else "the run has clipped, rejected or recovery frames: " + json.dumps({k: run_flags[k] for k in ("saturated_frames_any_arm", "rejected_frames_any_arm", "recovery_acted")})),
        }

        # (4) the carried-state fallback bound: gamma over every state (rigorous for any positive semidefinite actual
        # state), the first-block carried contribution measured against the cold start, the block scatter as its
        # uncertainty; the state-space gamma is a sensitivity. Superseded by the reconstruction when consistent.
        started_gamma = time.perf_counter()
        m_block, m_window = window_sensitivity(loop_modal, gram, n_pupil, gain=gain, leak=leak, latency=latency, n_analysed=n_steps - burn_in, block=BLOCK_FRAMES)
        gamma_all, on_null_all, _ = generalized_max_eigenvalue(m_window, m_block)
        if basis is None:
            gamma_space, on_null_space = gamma_all, on_null_all
        else:
            gamma_space, on_null_space, _ = generalized_max_eigenvalue(m_window, m_block, basis)
        injection = unsensed_injection(loop_modal, response_modal)
        gamma_s = time.perf_counter() - started_gamma
        inventory["carried_state_quadratic_forms"] = int(m_block.nbytes + m_window.nbytes + (0 if basis is None else basis.nbytes))

        # (5) the direct measurement of the state from the residual maps, when the sidecar retains them: a cross-check
        # of the reconstruction from the telemetry.
        direct: dict[str, Any]
        map_states: np.ndarray | None = None
        if pupil_response_kept is None:
            direct = {"status": "not measured", "reason": "the sidecar retains no residual maps (the series retains them for one seed per magnitude; the traced pilot with --retain-maps)"}
        else:
            map_mask = np.asarray(arrays["residual_maps__pupil_mask"], dtype=bool)
            if map_mask.shape != pupil_mask.shape or not np.array_equal(map_mask, pupil_mask):
                direct = {"status": "not measured", "reason": "the map recorder's pupil mask is not the model's pupil mask"}
            else:
                started_direct = time.perf_counter()
                # Streamed over 25-frame blocks so that no full-size map array beyond the sidecar's own float32 maps
                # is held (at 12 m a full float64 difference or fitted stack is 137 MiB each): least squares on the
                # pupil response through the Cholesky factor of the Gram matrix already formed, with two steps of
                # iterative refinement (corrected semi-normal equations).
                maps_noisy = arrays[f"residual_maps__{noisy_arm}"]
                maps_twin = arrays[f"residual_maps__{twin_arm}"]
                cholesky = linalg.cho_factor(gram)
                n_maps = int(maps_noisy.shape[0])
                coefficients = np.zeros((size_c, n_maps))
                residual_ss = total_ss = 0.0
                for first in range(0, n_maps, BLOCK_FRAMES):
                    block = np.asarray(maps_noisy[first:first + BLOCK_FRAMES], dtype=float) - np.asarray(maps_twin[first:first + BLOCK_FRAMES], dtype=float)
                    block -= block.mean(axis=1, keepdims=True)
                    solution = linalg.cho_solve(cholesky, pupil_response_kept.T @ block.T)
                    for _ in range(2):
                        solution += linalg.cho_solve(cholesky, pupil_response_kept.T @ (block.T - pupil_response_kept @ solution))
                    coefficients[:, first:first + BLOCK_FRAMES] = solution
                    residual_ss += float(np.sum((block.T - pupil_response_kept @ solution) ** 2))
                    total_ss += float(np.sum(block**2))
                state = -coefficients
                fit_residual = float(residual_ss / max(total_ss, 1.0e-300))
                v_map = np.einsum("ik,ij,jk->k", state, gram, state) / n_pupil
                unsensed_window = unsensed_first = None
                if basis_c is not None:
                    perpendicular = state - basis_c @ (basis_c.T @ state)
                    u_map = np.einsum("ik,ij,jk->k", perpendicular, gram, perpendicular) / n_pupil
                    unsensed_window = float(np.sum(u_map) / max(float(np.sum(v_map)), 1.0e-300))
                    unsensed_first = float(np.sum(u_map[:BLOCK_FRAMES]) / max(float(np.sum(v_map[:BLOCK_FRAMES])), 1.0e-300))
                map_states = state
                maps_vs_telemetry = None
                if state_trajectory is not None:
                    telemetry_states = state_trajectory[frames].T
                    maps_vs_telemetry = float(np.sqrt(np.mean(np.einsum("ik,ij,jk->k", state - telemetry_states, gram, state - telemetry_states) / n_pupil)) / max(float(np.sqrt(np.mean(v_map))), 1.0e-300))
                direct = {
                    "status": "measured",
                    "definition": "the command-difference state per analysed frame from the least-squares fit of the piston-removed residual-map difference (noisy minus twin) on the piston-removed pupil response of the controlled actuators; its pupil mean square against the sidecar's delta_v_m2, the share of the map difference the fit does not explain, and the share of its window value outside the operators' state space (content in modes no operator could have produced)",
                    "frames": int(state.shape[1]),
                    "fit_residual_fraction": fit_residual,
                    "map_delta_v_over_series_mean": float(np.mean(v_map) / max(float(np.mean(measured_series)), 1.0e-300)),
                    "content_outside_state_space_window_fraction": unsensed_window,
                    "content_outside_state_space_first_block_fraction": unsensed_first,
                    "maps_vs_telemetry_state_relative_rms": maps_vs_telemetry,
                    "level": UNSENSED_CONTENT_LEVEL,
                    "time_s": time.perf_counter() - started_direct,
                }
                inventory["pupil_response_kept_for_maps"] = int(pupil_response_kept.nbytes)
                inventory["map_fit_arrays"] = int(coefficients.nbytes + 4 * min(BLOCK_FRAMES, n_maps) * n_pupil * 8)
        # (6) the carried state from the retained maps when the telemetry reconstruction is not consistent: the
        # post-update state at the first analysed frame and the d increments released next are read from the maps,
        # the deterministic trajectory is propagated under the modal loop with no further noise, and the model's
        # noise part starts with the increments computed from frame b + 1 on.
        map_carried: dict[str, Any]
        map_start: tuple[np.ndarray, list[np.ndarray]] | None = None
        if map_states is None:
            map_carried = {"status": "not available", "reason": "no residual maps"}
        elif map_states.shape[1] < latency + 2:
            map_carried = {"status": "not available", "reason": "too few analysed frames for the queued increments"}
        else:
            released = [(map_states[:, j] - (1.0 - leak) * map_states[:, j - 1]) / gain for j in range(1, latency + 1)]
            map_start = (map_states[:, 0].copy(), [item.copy() for item in released])
            x = map_states[:, 0].copy()
            queue_map: deque[np.ndarray] = deque(released)
            values_map = np.zeros(n_steps - burn_in)
            values_map[0] = float(x @ gram @ x) / n_pupil
            for index in range(1, n_steps - burn_in):
                queue_map.append(-loop_modal @ x)
                released_now = queue_map.popleft()
                x = (1.0 - leak) * x + gain * released_now
                values_map[index] = float(x @ gram @ x) / n_pupil
            cold_map_block, _ = window_covariance(loop_modal, block_modal, gain=gain, leak=leak, latency=latency, n_steps=n_steps, burn_in=burn_in, initial_state=np.zeros((full, full)), start_frame=burn_in, forcing_from=burn_in + latency + 1)
            cold_map_value = float(np.trace(gram @ cold_map_block) / n_pupil)
            map_carried = {
                "status": "available",
                "definition": "the post-update state at the first analysed frame and the d increments released at the next updates are read from the residual maps (least squares on the pupil response), the deterministic trajectory is propagated under the modal loop with no further noise, and its window mean is the carried contribution; the model's noise part is the cold start whose forcing begins with the increments computed from frame b + 1 on (released at update b + d + 1)",
                "window_contribution_m2": float(np.mean(values_map)),
                "window_contribution_over_primary": float(np.mean(values_map)) / modal_value,
                "delta_v_noise_from_frame_b_plus_1_m2": cold_map_value,
                "delta_v_conditional_window_m2": cold_map_value + float(np.mean(values_map)),
            }
        reconstructed_ok = bool(reconstruction.get("consistent", False))
        if reconstructed_ok:
            carried_source = "telemetry reconstruction"
            conditional_value = reconstruction["delta_v_conditional_window_m2"]
            source_residual = 0.0
        elif map_carried.get("status") == "available" and reconstruction.get("status") == "reconstructed":
            carried_source = "residual maps"
            conditional_value = map_carried["delta_v_conditional_window_m2"]
            source_residual = direct.get("fit_residual_fraction")
        else:
            carried_source = None
            conditional_value = None
            source_residual = None
            if reconstruction.get("status") == "reconstructed":
                not_assessable.append(f"no measured carried state: the command difference rebuilt from the telemetry misses the measured series by {reconstruction['relative_rms_vs_measured_series']:.2e} relative rms (above {RECONSTRUCTION_TOLERANCE:g}) and the sidecar retains no residual maps to read the state from")
            else:
                not_assessable.append(f"no measured carried state: the command difference was not rebuilt ({reconstruction.get('reason')}), so the linear model is not checked against this run")
        # (7) the operator error on the conditional prediction (review round 7): the measured carried state and the
        # noise not yet in it, propagated with the noisy arm's actual operator of every later frame (with the
        # deterministic forcing (R^noisy - R^twin)(m^twin - m_ref) of the frames on which the two arms' operators
        # differ), against the same under the modal operator; extremized exactly over the admissible covariance of
        # the rows outside the modal mask (an adjoint pass gives the window value as a linear functional of Sigma).
        operator_error: dict[str, Any]
        sigma_worst: np.ndarray | None = None
        worst_blocks: list[np.ndarray] | None = None
        if probing["status"] != "computed":
            operator_error = {"status": "not computed", "reason": probing["reason"]}
        elif bracket["lenslets_without_bound"]:
            operator_error = {"status": "not computed", "reason": f"{len(bracket['lenslets_without_bound'])} lenslet(s) outside the modal mask have no admissible variance interval (fewer than two usable frames and no sensor-model term the margin calibration supports): {bracket['lenslets_without_bound'][:8]}"}
            not_assessable.append(operator_error["reason"])
        elif carried_source is None or conditional_value is None:
            operator_error = {"status": "not computed", "reason": "no measured carried state (see the reasons): the conditional prediction is not defined"}
        else:
            started_error = time.perf_counter()
            response_by_mask = {mask.tobytes(): response for mask, response in zip(distinct, response_list)}
            response_by_mask.update({mask.tobytes(): response for mask, response in zip(twin_only, twin_responses)})
            noisy_masks_all = operator_data["effective_masks"][noisy_arm]
            twin_masks_all = operator_data["effective_masks"][twin_arm]
            twin_centroids = operator_data["centroids"][twin_arm]
            pairs = np.asarray(operator_data["rows"], dtype=int)
            reference_rows = np.zeros(len(row_ids))
            if reference_xy is not None:
                reference_rows[pairs[:, 0]] = reference_xy[:, 0]
                reference_rows[pairs[:, 1]] = reference_xy[:, 1]
            forcing_counts = {"frames": 0, "unknown_entries": 0}

            def arm_forcing(frame: int) -> np.ndarray | None:
                noisy_mask, twin_mask = noisy_masks_all[frame], twin_masks_all[frame]
                if np.array_equal(noisy_mask, twin_mask):
                    return None
                vector = np.full(len(row_ids), np.nan)
                vector[pairs[:, 0]] = twin_centroids[frame, :, 0]
                vector[pairs[:, 1]] = twin_centroids[frame, :, 1]
                vector = vector - reference_rows
                forcing_counts["frames"] += 1
                forcing_counts["unknown_entries"] += int(np.count_nonzero(noisy_mask & ~np.isfinite(vector)))
                filled = np.where(np.isfinite(vector), vector, 0.0)
                return response_by_mask[noisy_mask.tobytes()] @ np.where(noisy_mask, filled, 0.0) - response_by_mask[twin_mask.tobytes()] @ np.where(twin_mask, filled, 0.0)

            if carried_source == "telemetry reconstruction":
                start_state = post_update[burn_in - 1].copy() if burn_in > 0 else np.zeros(size_c)
                start_queue = [increments[frame] if frame >= 0 else np.zeros(size_c) for frame in range(burn_in - latency, burn_in)]
                first_frame, include_start = burn_in, False
                cold_modal_value = cold_value
                carried_modal_reported = reconstruction["carried_state"]["window_contribution_m2"]
            else:
                assert map_start is not None
                start_state, start_queue = map_start
                first_frame, include_start = burn_in + 1, True
                cold_modal_value = map_carried["delta_v_noise_from_frame_b_plus_1_m2"]
                carried_modal_reported = map_carried["window_contribution_m2"]
            forcing_from = first_frame + latency
            carried_modal = float(np.mean(deterministic_window(start_state, start_queue, first_frame=first_frame, n_steps=n_steps, include_start=include_start, loop_at=lambda frame: loop_modal, forcing_at=lambda frame: None, gain=gain, leak=leak, gram=gram, n_pupil=n_pupil)))
            carried_actual = float(np.mean(deterministic_window(start_state, start_queue, first_frame=first_frame, n_steps=n_steps, include_start=include_start, loop_at=lambda frame: loop_list[int(sequence[frame])], forcing_at=arm_forcing, gain=gain, leak=leak, gram=gram, n_pupil=n_pupil)))
            functional = time_varying_cold_functional(loop_list, response_list, sequence, gain=gain, leak=leak, latency=latency, n_steps=n_steps, start=burn_in, forcing_from=forcing_from, gram=gram, n_pupil=n_pupil)
            extremes = admissible_extremes(functional, operator_data["sigma_base"], bracket["details"])
            prediction_modal = float(conditional_value)
            actual_low = extremes["min"] + carried_actual
            actual_high = extremes["max"] + carried_actual
            error_low = (actual_low - prediction_modal) / prediction_modal
            error_high = (actual_high - prediction_modal) / prediction_modal
            worst_is_high = abs(error_high) >= abs(error_low)
            sigma_worst = extremes["sigma_max"] if worst_is_high else extremes["sigma_min"]
            worst_blocks = [forcing_block(response, sigma_worst * np.outer(mask, mask), gain=gain) for response, mask in zip(response_list, distinct)]
            forward_worst = time_varying_cold(loop_list, worst_blocks, sequence, gain=gain, leak=leak, latency=latency, n_steps=n_steps, start=burn_in, forcing_from=forcing_from, gram=gram, n_pupil=n_pupil)
            adjoint_worst = extremes["max"] if worst_is_high else extremes["min"]
            operator_error = {
                "status": "computed",
                "definition": "the relative difference between the conditional prediction under the noisy arm's actual operator of every frame from the first new increment on (the measured carried state propagated without noise with those operators and with the deterministic forcing (R^noisy - R^twin)(m^twin - m_ref) of the frames on which the two arms' operators differ, plus the cold-start noise part with those operators) and the conditional prediction under the modal operator that the comparison uses; the cold part is linear in the measurement covariance (adjoint pass) and is extremized exactly over the admissible covariance of the rows outside the modal mask; the operator error is the extreme of larger magnitude",
                "value": float(error_high if worst_is_high else error_low),
                "extremes": {"min": float(min(error_low, error_high)), "max": float(max(error_low, error_high))},
                "width_over_prediction": float(abs(error_high - error_low)),
                "conditional_prediction_modal_m2": prediction_modal,
                "conditional_prediction_actual_operators_m2": {"at_admissible_min": float(actual_low), "at_admissible_max": float(actual_high)},
                "cold_noise_m2": {"modal": float(cold_modal_value), "actual_operators_min": float(extremes["min"]), "actual_operators_max": float(extremes["max"])},
                "carried_window_m2": {"modal": carried_modal, "actual_operators": carried_actual},
                "carried_window_over_prediction": {"modal": carried_modal / prediction_modal, "actual_operators": carried_actual / prediction_modal},
                "carried_modal_matches_source_relative": float(abs(carried_modal - carried_modal_reported) / max(abs(carried_modal_reported), 1.0e-300)),
                "arm_operator_forcing": {"frames": forcing_counts["frames"], "unknown_entries": forcing_counts["unknown_entries"]},
                "admissible": {"lenslets": len(bracket["details"]), "per_lenslet": extremes["per_lenslet"]},
                "adjoint_vs_forward_relative": float(abs(forward_worst - adjoint_worst) / max(abs(forward_worst), 1.0e-300)),
                "carried_state_source": carried_source,
                "tolerance": float(arguments.operator_tolerance),
                "time_s": time.perf_counter() - started_error,
            }
            if forcing_counts["unknown_entries"]:
                not_assessable.append(f"the arm-operator forcing has {forcing_counts['unknown_entries']} row-frame entries where the noisy arm used a row the twin did not measure: the actual-operator propagation is not determined")
            if operator_error["width_over_prediction"] > arguments.operator_tolerance:
                not_assessable.append(f"the admissible covariance of the rows outside the modal mask moves the operator error over {operator_error['width_over_prediction'] * 100:.2f} % of the prediction (above the {arguments.operator_tolerance * 100:g} % tolerance): the operator error is not determined")
            inventory["operator_error_arrays"] = int(functional.nbytes + 2 * operator_data["sigma_base"].nbytes + sum(block.nbytes for block in worst_blocks) + full * full * 8 * 2 + len(response_list) * size_c * size_c * 8)
            if arguments.admissible_samples > 0 and bracket["details"]:
                started_sampling = time.perf_counter()
                rng_samples = np.random.default_rng(0)
                hybrid_sequence = sequence.copy()
                hybrid_sequence[burn_in:] = modal_index

                def evaluate(sigma: np.ndarray) -> tuple[float, float]:
                    blocks_sample = [forcing_block(response, sigma * np.outer(mask, mask), gain=gain) for response, mask in zip(response_list, distinct)]
                    cold_sample = time_varying_cold(loop_list, blocks_sample, sequence, gain=gain, leak=leak, latency=latency, n_steps=n_steps, start=burn_in, forcing_from=forcing_from, gram=gram, n_pupil=n_pupil)
                    whole = float(np.trace(gram @ time_varying_window(loop_list, blocks_sample, sequence, gain=gain, leak=leak, latency=latency, n_steps=n_steps, burn_in=burn_in)) / n_pupil)
                    carried_sample = float(np.trace(gram @ time_varying_window(loop_list, blocks_sample, hybrid_sequence, gain=gain, leak=leak, latency=latency, n_steps=n_steps, burn_in=burn_in)) / n_pupil)
                    return (cold_sample + carried_actual - prediction_modal) / prediction_modal, (whole - carried_sample) / modal_value

                sampled_errors: list[float] = []
                sampled_window_components: list[float] = []
                for _ in range(arguments.admissible_samples):
                    sample = np.array(extremes["sigma_min"], dtype=float)
                    for entry in bracket["details"]:
                        x_row, y_row = entry["rows"]
                        s_x = rng_samples.uniform(entry["lower_px2"][0], entry["upper_px2"][0])
                        s_y = rng_samples.uniform(entry["lower_px2"][1], entry["upper_px2"][1])
                        cross_value = rng_samples.uniform(-1.0, 1.0) * np.sqrt(s_x * s_y)
                        sample[x_row, x_row], sample[y_row, y_row], sample[x_row, y_row], sample[y_row, x_row] = s_x, s_y, cross_value, cross_value
                    conditional_error, window_component = evaluate(sample)
                    sampled_errors.append(conditional_error)
                    sampled_window_components.append(window_component)
                ends_round6: list[float] = []
                for end in ("zero", "diagonal bound"):
                    sample = np.array(extremes["sigma_min"], dtype=float)
                    for entry in bracket["details"]:
                        block_rows = np.asarray(entry["rows"], dtype=int)
                        if end == "zero":
                            sample[np.ix_(block_rows, block_rows)] = np.diag(entry["lower_px2"])
                        else:
                            cross_bound = float(np.sqrt(entry["upper_px2"][0] * entry["upper_px2"][1]))
                            sample[np.ix_(block_rows, block_rows)] = np.diag([entry["upper_px2"][0] + cross_bound, entry["upper_px2"][1] + cross_bound])
                    ends_round6.append(evaluate(sample)[1])
                tolerance_sampling = 1.0e-12 * max(1.0, abs(operator_error["extremes"]["min"]), abs(operator_error["extremes"]["max"]))
                operator_error["admissible_sampling"] = {
                    "definition": "random admissible covariances of the rows outside the modal mask (per lenslet each variance uniform in its interval, the cross term uniform in its PSD range; seed 0), each evaluated by forward propagation: the operator error (which must lie within the exact extremes) and, for comparison, the round-6 operator error (the in-window component of the unconditional transient), whose two bracket ends (lower variances; the diagonal block dominating the upper variances) are evaluated too",
                    "samples": int(arguments.admissible_samples),
                    "outside_exact_extremes": int(sum(1 for value in sampled_errors if value < operator_error["extremes"]["min"] - tolerance_sampling or value > operator_error["extremes"]["max"] + tolerance_sampling)),
                    "operator_error_sampled_range": [float(min(sampled_errors)), float(max(sampled_errors))],
                    "round6_window_component_sampled_range": [float(min(sampled_window_components)), float(max(sampled_window_components))],
                    "round6_window_component_at_its_bracket_ends": ends_round6,
                    "round6_samples_beyond_its_ends": int(sum(1 for value in sampled_window_components if value < min(ends_round6) - 1.0e-12 or value > max(ends_round6) + 1.0e-12)),
                    "time_s": time.perf_counter() - started_sampling,
                }

        # The unconditional transient with the actual operators from frame 0 (burn-in included), the round-4 to
        # round-6 quantity, kept as a diagnostic at the worse admissible covariance (or, without one, at the
        # admissible upper variances with no cross term).
        unconditional: dict[str, Any]
        if probing["status"] != "computed" or bracket["lenslets_without_bound"]:
            unconditional = {"status": "not computed", "reason": probing.get("reason") or "a lenslet outside the modal mask has no admissible interval", **probing}
        else:
            if sigma_worst is None:
                sigma_worst = np.array(operator_data["sigma_base"], dtype=float)
                for entry in bracket["details"]:
                    block_rows = np.asarray(entry["rows"], dtype=int)
                    sigma_worst[np.ix_(block_rows, block_rows)] = np.diag(entry["upper_px2"])
            blocks_worst = worst_blocks if worst_blocks is not None else [forcing_block(response, sigma_worst * np.outer(mask, mask), gain=gain) for response, mask in zip(response_list, distinct)]
            hybrid = sequence.copy()
            hybrid[burn_in:] = modal_index
            value_all = float(np.trace(gram @ time_varying_window(loop_list, blocks_worst, sequence, gain=gain, leak=leak, latency=latency, n_steps=n_steps, burn_in=burn_in)) / n_pupil)
            carried_in = float(np.trace(gram @ time_varying_window(loop_list, blocks_worst, hybrid, gain=gain, leak=leak, latency=latency, n_steps=n_steps, burn_in=burn_in)) / n_pupil)
            unconditional = {
                "status": "computed",
                "definition": "diagnostic (the operator error of review rounds 4 to 6): the noise transient propagated from frame 0 with the noisy arm's actual operator of every frame, against the modal-operator prediction; its part carried in from burn-in (actual operators before the window, the modal one inside it) and its part from operator changes inside the window; evaluated at the worse admissible covariance of the operator error (or at the admissible upper variances when the operator error is not computed); decides nothing",
                "delta_v_window_m2": value_all,
                "relative_difference_vs_modal": (value_all - modal_value) / modal_value,
                "burn_in_carried_component": (carried_in - modal_value) / modal_value,
                "window_operator_component": (value_all - carried_in) / modal_value,
                **probing,
            }

        measured_outside = direct.get("content_outside_state_space_window_fraction")
        if measured_outside is not None and measured_outside > UNSENSED_CONTENT_LEVEL and restricted:
            restricted = False
            basis = None
            gamma_space, on_null_space = gamma_all, on_null_all
            space["restricted"] = False
            space["reason_for_all_states"] = f"the residual maps show {measured_outside * 100:.2f} % of the window value outside the operators' state space (above {UNSENSED_CONTENT_LEVEL:g}): the state-space argument does not hold for this run"
        gamma_used = gamma_all

        blocks = int(len(measured_series) // BLOCK_FRAMES)
        predicted = predicted_all[frames]
        carried: dict[str, Any] = {
            "definition": "fallback bound, used only when the trajectory cannot be reconstructed: W = W_cold + tr(M_window P) with P the (positive semidefinite) covariance of the actual state at the first analysed frame, random or frozen, so tr(M_window P) <= gamma tr(M_block P) with gamma the largest generalized eigenvalue of the window-mean and first-block-mean quadratic forms over every state; tr(M_block P) is measured as the first analysed block's mean of delta_v_m2 minus the model's cold-start first block (c_1), with the run's 25-frame block scatter s_block as its uncertainty; the actual carried window contribution lies in [0, gamma (c_1 + 2 s_block)], the model's is W - W_cold, and the bound on the model's error is the larger of the two distances; no covariance difference is assumed definite and no state direction is excluded",
            "gamma_state_space": gamma_space,
            "gamma_all_states": gamma_all,
            "gamma_used": gamma_used,
            "gamma_basis": "all states (the state-space gamma is a sensitivity)",
            "superseded_by_reconstruction": bool(reconstruction.get("consistent", False)),
            "window_form_on_null_of_block_form_relative": {"state_space": on_null_space, "all": on_null_all},
            "unsensed_modes_of_modal_operator": int(np.count_nonzero(np.sort(np.real(np.linalg.eigvals(loop_modal))) < UNSENSED_FEEDBACK)),
            "unsensed_mode_injection": injection,
            "blocks": blocks,
            "block_frames": BLOCK_FRAMES,
            "gamma_s": gamma_s,
        }
        if blocks < 2 or gamma_used is None:
            carried.update({"status": "not measurable", "reason": "fewer than two analysed 25-frame blocks" if blocks < 2 else "the first-block quadratic form has no range", "bound": None})
        else:
            block_means = measured_series[: blocks * BLOCK_FRAMES].reshape(blocks, BLOCK_FRAMES).mean(axis=1)
            predicted_means = predicted[: blocks * BLOCK_FRAMES].reshape(blocks, BLOCK_FRAMES).mean(axis=1)
            cold_means = cold_analysed[: blocks * BLOCK_FRAMES].reshape(blocks, BLOCK_FRAMES).mean(axis=1)
            inherited_window = float((modal_value - cold_value) / modal_value)
            inherited_first = float((predicted_means[0] - cold_means[0]) / modal_value)
            excess_1 = float(block_means[0] - predicted_means[0])
            carried_1 = float(block_means[0] - cold_means[0])
            scatter = float(np.std(block_means, ddof=1))
            upper_actual = float(gamma_used * max(0.0, carried_1 + 2.0 * scatter))
            bound = float(max(inherited_window, upper_actual / modal_value - inherited_window))
            upper_all = float(gamma_all * max(0.0, carried_1 + 2.0 * scatter)) if gamma_all is not None else None
            carried.update({
                "status": "measured",
                "first_block_measured_m2": float(block_means[0]),
                "first_block_predicted_m2": float(predicted_means[0]),
                "first_block_cold_start_m2": float(cold_means[0]),
                "first_block_excess_over_primary": excess_1 / modal_value,
                "first_block_carried_measured_over_primary": carried_1 / modal_value,
                "first_block_carried_modelled_over_primary": inherited_first,
                "window_carried_modelled_over_primary": inherited_window,
                "block_scatter_over_primary": scatter / modal_value,
                "per_block_excess_over_primary": [float(v) for v in (block_means - predicted_means) / modal_value],
                "actual_carried_window_upper_over_primary": upper_actual / modal_value,
                "bound": bound,
                "bound_all_states": None if upper_all is None else float(max(inherited_window, upper_all / modal_value - inherited_window)),
            })

        operator_error_abs = None if operator_error["status"] != "computed" else abs(operator_error["value"])
        carried_bound = carried.get("bound")
        reconstruction_residual = reconstruction.get("relative_rms_vs_measured_series") if reconstruction.get("status") == "reconstructed" else None
        systematic = {
            "definition": "the model's systematic error budget of this run's conditional prediction, relative: the operator error (worse end of the bracket), plus the reconstruction residual (the relative rms of the per-frame value of the command difference rebuilt from the telemetry through the probed operators against the measured series: the measured departure of the linear model, operators included, from this run), plus the unexplained share of the map difference when the residual maps supply the carried state; PROTOCOL.md 1.7 subtracts the mean budget of the admissible seeds from the equivalence band; the fallback gamma bound is a diagnostic",
            "operator_error_abs": operator_error_abs,
            "reconstruction_residual": reconstruction_residual,
            "carried_state_source": carried_source,
            "source_residual": source_residual,
            "carried_state_fallback_bound": carried_bound,
            "total": None if operator_error_abs is None or carried_source is None or reconstruction_residual is None else float(operator_error_abs + reconstruction_residual + (source_residual or 0.0)),
            "closure_band": float(arguments.closure_band),
        }
        systematic["at_or_above_band"] = None if systematic["total"] is None else bool(systematic["total"] >= arguments.closure_band)
        if systematic["at_or_above_band"]:
            not_assessable.append(f"the systematic budget u = {systematic['total'] * 100:.2f} % is at or above the closure band {arguments.closure_band * 100:g} %: the run cannot enter an equivalence test")
        within_operator = operator_error["status"] == "computed" and abs(operator_error["value"]) <= arguments.operator_tolerance
        if operator_error["status"] == "computed" and not within_operator:
            reasons.append(f"operator error {operator_error['value'] * 100:+.2f} % (the conditional prediction under the actual operators against the modal one, at the worse admissible covariance) exceeds the {arguments.operator_tolerance * 100:g} % tolerance")
        if not_assessable:
            classification = "not assessable"
            reasons = not_assessable + reasons
        elif within_operator:
            classification = "operator-consistent"
        else:
            classification = "mask-variable"
        return {
            "status": "evaluated",
            "rule": "operator-consistent when the operator error (the conditional prediction under the actual operators against the modal one, at the worse admissible covariance) is within --operator-tolerance; mask-variable when it is not; not assessable when the operators cannot all be probed, a lenslet outside the modal mask has no admissible interval, the admissible covariance moves the operator error over more than the tolerance, no measured carried state exists (a telemetry reconstruction missing the series by more than 1e-3 without residual maps), or the systematic budget reaches --closure-band; the comparison is made against the prediction conditional on the measured carried state, and the budget is the operator error plus the reconstruction residual plus the map-fit residual when the maps supply the state",
            "operator_consistent": classification == "operator-consistent",
            "classification": classification,
            "reasons": reasons,
            "operator_error": operator_error,
            "time_varying": unconditional,
            "reconstruction": reconstruction,
            "map_based_carried_state": map_carried,
            "carried_state_source": carried_source,
            "delta_v_conditional_window_m2": conditional_value,
            "state_space": space,
            "carried_state": carried,
            "direct_state_measurement": direct,
            "systematic": systematic,
            "restart_sensitivities": sensitivities,
            "burn_in": burn_in_state,
            "run_flags": run_flags,
        }

    bounds = operator_bounds()

    def memory_inventory() -> dict[str, Any]:
        """Bytes of the arrays this process retains (and the dense response it freed), beside its peak resident set."""

        full = size_c * (latency + 1)
        retained = {
            "sidecar_arrays": 0 if arrays is None else int(sum(int(value.nbytes) for value in arrays.values())),
            "interaction_matrix_M": int(dense.nbytes),
            "gram": int(gram.nbytes),
            "response_full": int(response_full.nbytes),
            "responses_and_loops_per_rule": int(sum(responses[r].nbytes + loops[r].nbytes for r in responses)),
            "lyapunov_working_set_estimate": int(4 * full * full * 8),
            "window_propagation_state": int(2 * full * full * 8),
            **{key: value for key, value in inventory.items()},
        }
        return {
            "retained_arrays_bytes": retained,
            "retained_total_bytes": int(sum(retained.values())),
            "pupil_response_bytes": pupil_response_bytes,
            "pupil_response_kept": pupil_response_kept is not None,
            "ru_maxrss_bytes": peak_rss_bytes(),
            "note": "the inventory counts the arrays the tool itself holds (the Lyapunov and propagation working sets as size estimates); the system build's own arrays, the interpreter and the libraries are in the peak resident set only; the dense pupil response is freed once the Gram matrix is formed unless the sidecar retains residual maps, which the direct state measurement fits on it",
        }

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
        "memory": memory_inventory(),
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
            "operator_bounds": bounds,
            "by_noise_covariance_rule": by_rule,
        },
    }
    measured = sigma_info.get("measured_delta_v_mean_m2")
    if measured is not None:
        se = sigma_info.get("measured_delta_v_block25_se_m2")
        window = primary["delta_v_exact_window_m2"]
        consistent = bounds.get("operator_consistent") if bounds.get("status") == "evaluated" else None
        if consistent is None:
            status = "not assessed: " + str(bounds.get("reason"))
        elif consistent:
            status = "operator-consistent"
        else:
            status = bounds["classification"] + ": " + "; ".join(bounds["reasons"]) + "; the prediction is reported and the comparison is descriptive"
        record["comparison"] = {
            "status": status,
            "operator_consistent": consistent,
            "systematic_budget": None if bounds.get("status") != "evaluated" else bounds["systematic"],
            "delta_v_conditional_window_m2": None if bounds.get("status") != "evaluated" else bounds.get("delta_v_conditional_window_m2"),
            "carried_state_source": None if bounds.get("status") != "evaluated" else bounds.get("carried_state_source"),
            "measured_over_conditional_prediction": None if bounds.get("status") != "evaluated" or bounds.get("delta_v_conditional_window_m2") in (None, 0.0) else measured / bounds["delta_v_conditional_window_m2"],
            "primary_ratio": "measured_over_conditional_prediction when a carried-state source exists (PROTOCOL.md 1.7), else descriptive",
            "measured_delta_v_mean_m2": measured,
            "measured_delta_v_block25_se_m2": se,
            "measured_over_exact_window": measured / window if window > 0 else None,
            "measured_over_exact_stationary": None if primary["delta_v_exact_stationary_m2"] is None or primary["delta_v_exact_stationary_m2"] <= 0 else measured / primary["delta_v_exact_stationary_m2"],
            "measured_over_scalar_mask": measured / primary["delta_v_scalar_reduction_mask_m2"] if primary["delta_v_scalar_reduction_mask_m2"] > 0 else None,
            "measured_over_scalar_series_weights": measured / primary["delta_v_scalar_reduction_series_weights_m2"] if primary["delta_v_scalar_reduction_series_weights_m2"] > 0 else None,
            "exact_window_within_2_block_se": None if se is None else bool(abs(measured - window) <= 2.0 * se),
            "measured_over_exact_window_by_rule": {rule: (None if entry.get("status") != "defined" or entry["delta_v_exact_window_m2"] <= 0 else measured / entry["delta_v_exact_window_m2"]) for rule, entry in predictions.items()},
            "note": "a pilot-level consistency check of the model against one run; the protocol's acceptance rules, not this ratio, decide anything; a run that is not operator-consistent (mask-variable or not assessable) has a descriptive comparison; the systematic budget enters the closure test of PROTOCOL.md 1.7",
        }
    write_record_once(arguments.output, record)
    print(json.dumps({"configuration": described, "controlled": size_c, "primary_rule": primary_rule, "rows_in_mask": primary["rows_valid_in_mask"],
                      "operator": None if operator is None else {k: operator[k] for k in ("noisy_match_fraction", "twin_match_fraction", "burn_in_match_fraction_noisy")},
                      "operator_bounds": None if bounds.get("status") != "evaluated" else {"classification": bounds["classification"], "operator_error": bounds["operator_error"].get("value"), "operator_error_extremes": bounds["operator_error"].get("extremes"), "operator_error_width": bounds["operator_error"].get("width_over_prediction"), "carried_window_over_prediction": bounds["operator_error"].get("carried_window_over_prediction"), "unconditional_vs_modal": bounds["time_varying"].get("relative_difference_vs_modal"), "unconditional_window_component": bounds["time_varying"].get("window_operator_component"), "burn_in_carried_component": bounds["time_varying"].get("burn_in_carried_component"), "state_space": {k: bounds["state_space"][k] for k in ("restricted", "dimension", "controlled_actuators")}, "gamma_space": bounds["carried_state"].get("gamma_state_space"), "gamma_all": bounds["carried_state"].get("gamma_all_states"), "gamma_used": bounds["carried_state"].get("gamma_used"), "first_block_carried_measured": bounds["carried_state"].get("first_block_carried_measured_over_primary"), "first_block_carried_modelled": bounds["carried_state"].get("first_block_carried_modelled_over_primary"), "block_scatter": bounds["carried_state"].get("block_scatter_over_primary"), "carried_state_bound": bounds["carried_state"].get("bound"), "bound_all_states": bounds["carried_state"].get("bound_all_states"), "direct": {k: v for k, v in bounds["direct_state_measurement"].items() if k in ("status", "fit_residual_fraction", "map_delta_v_over_series_mean", "content_outside_state_space_window_fraction", "maps_vs_telemetry_state_relative_rms")}, "reconstruction": None if bounds["reconstruction"].get("status") != "reconstructed" else {"relative_rms": bounds["reconstruction"]["relative_rms_vs_measured_series"], "consistent": bounds["reconstruction"]["consistent"], "carried_window_over_primary": bounds["reconstruction"]["carried_state"]["window_contribution_over_primary"], "modelled_carried_over_primary": bounds["reconstruction"]["carried_state"]["modelled_window_contribution_over_primary"], "outside_modal_range": bounds["reconstruction"]["content_outside_modal_operator_range"]["window_fraction"], "conditional_nm2": bounds["reconstruction"]["delta_v_conditional_window_m2"] * 1e18}, "carried_source": bounds.get("carried_state_source"), "conditional_used_nm2": None if bounds.get("delta_v_conditional_window_m2") is None else bounds["delta_v_conditional_window_m2"] * 1e18, "measured_over_conditional": record["comparison"].get("measured_over_conditional_prediction") if record.get("comparison") else None, "map_carried_over_primary": bounds["map_based_carried_state"].get("window_contribution_over_primary"), "systematic_total": bounds["systematic"]["total"], "reasons": bounds["reasons"]},
                      "memory_mib": {"retained_total": record["memory"]["retained_total_bytes"] / 2**20, "ru_maxrss": record["memory"]["ru_maxrss_bytes"] / 2**20},
                      "feedback_min": primary["feedback_spectrum"]["min"], "fraction_below_0.9": primary["feedback_spectrum"]["fraction_below_0.9"],
                      "delta_v_exact_window_nm2": primary["delta_v_exact_window_m2"] * 1e18, "delta_v_exact_stationary_nm2": None if primary["delta_v_exact_stationary_m2"] is None else primary["delta_v_exact_stationary_m2"] * 1e18, "delta_v_scalar_mask_nm2": primary["delta_v_scalar_reduction_mask_m2"] * 1e18,
                      "sidecar_validation": None if validation is None else {k: v for k, v in validation.items() if k != "structural"} | {"structural": "passed"},
                      "comparison": None if record.get("comparison") is None else {k: record["comparison"][k] for k in ("status", "measured_over_exact_window", "measured_over_exact_window_by_rule", "exact_window_within_2_block_se")}}, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())
