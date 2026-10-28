"""Analyse a traced noise-isolation record and its sidecars (S4 contract, ticket T1).

NumPy only: no ``shwfs_ao`` import, so the analysis can run on a saved record
anywhere.  It reads one traced record (``noise-isolation-*-traced`` or
``-masklocked`` of ``scripts/run_detector_level_evidence.py``) with the
sidecars beside it, computes the predeclared statistics of the S4 contract
and writes ``analysis.json`` and ``ANALYSIS_NOTE.md`` into ``--output-dir``.
It never asserts a verdict: every number is reported with its support,
and every case the data cannot decide is named as such.

Predeclared rules (contract section 5; the deviations and additions are
qualified in the record of ticket T1):

* Units of inference are root seeds; magnitudes are paired within a seed.
  Primary intervals are Student t with ``n_seeds - 1`` degrees of freedom
  (quantiles from the regularized incomplete beta, checked against a table
  in the tests; no normal approximation at eight seeds).
* Within-run errors of ``DeltaV_t``: block means at lengths 1, 5, 10, 25,
  50 and 75 frames (``--block-lengths``).  A plateau is identified at the
  smallest length ``L`` with at least five blocks whose standard error is
  not exceeded by more than 10 % by the next admissible length's; otherwise
  no plateau is identified and the largest admissible length's error is a
  lower bound.  Block errors from fewer than about ten blocks are themselves
  uncertain by 30 % or more, which the note says.  The integrated
  autocorrelation time uses the automatic window ``M >= c tau(M)`` with
  ``c = 6`` (Madras & Sokal 1988); it is reported as unreliable when the
  series is shorter than 50 times the estimate or no window closes, and as
  unsupported, with no derived uncertainty, when the estimate is below one
  (the window rule assumes a non-negative autocorrelation; an anticorrelated
  series needs another estimator).
* Gate-quiet domain: runs whose arms' effective masks differ in fewer than
  0.1 % of row-frames after burn-in with no rejected reconstruction and no
  recovery action in either arm; a predeclared magnitude subset may also be
  named with ``--gate-quiet-labels`` and is reported beside the data-driven one.
* Excursion: any 25-frame block mean of ``DeltaV_t`` above three times the
  run median flags the run; flagged runs stay in every statistic and are
  listed with their traces.
* E0: ``n = c_noisy - c_expected`` on the noisy arm's own operating state;
  mean, centred variance and second moment are reported apart; the model
  column is the frame mean of ``sigma**2``; the support is the lenslets
  valid, model-supported and finite in every analysed frame.  Equal-weight
  aggregates and propagation-weighted aggregates (the fixed reconstructor's
  pupil response per row) are both reported with their domains.
* Bootstrap resamples (the F-06 convention: whole-seed resampling of an
  unweighted fit to seed means) are descriptive, not additional realizations.
* A non-positive ``DeltaV`` cannot enter a log fit and is counted instead; a
  zero seed scatter gives a degenerate interval and is flagged; a series
  too short for a block length or a window is reported as not estimable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time
from typing import Any
import zipfile

import numpy as np


ANALYSIS_SCHEMA = "shwfs_ao.noise_isolation_trace_analysis.v1"
SIDECAR_SCHEMA = "shwfs_ao.noise_isolation_trace_sidecar.v1"
DEFAULT_BLOCK_LENGTHS = (1, 5, 10, 25, 50, 75)
EXCURSION_BLOCK = 25
EXCURSION_FACTOR = 3.0
GATE_QUIET_DISAGREEMENT = 1.0e-3
PLATEAU_MIN_BLOCKS = 5
PLATEAU_TOLERANCE = 0.10
SOKAL_C = 6.0
TAU_RELIABLE_FACTOR = 50.0
SEVEN_RECORDED = (
    ("noise_variance_m2",),
    ("noise_variance_standard_error_m2",),
    ("mean_square_difference_m2",),
    ("mean_square_difference_standard_error_m2",),
    ("arms", "noise_on", "post_update_rms_m"),
    ("arms", "operating_expectation", "post_update_rms_m"),
    ("predicted_centroid_variance_px2",),
)

# Canonical sidecar schema, copied from the evidence runner's tables (a test pins their
# equality): units, meaning and axes of every array a trace sidecar may hold.
CANONICAL_SERIES_ARRAYS = {'frame_index': ('frame', 'frame index 0..n_steps-1', ('frame',)),
 'analysed_frame_index': ('frame', 'frames after burn-in, the domain of the three series below', ('analysed_frame',)),
 'delta_v_m2': ('m2',
                'DeltaV_t: piston-removed pupil mean square of the residual-map difference (noisy minus twin, float32-recorded maps)',
                ('analysed_frame',)),
 'mean_square_difference_m2': ('m2', 'msd_t: noisy minus twin post-update mean-square residual (float64 history)', ('analysed_frame',)),
 'cross_term_m2': ('m2', 'X_t = msd_t - DeltaV_t', ('analysed_frame',)),
 'mask_disagreement_rows': ('rows', "rows on which the two arms' effective masks differ", ('frame',)),
 'calibration_valid_rows': ('bool', 'calibration-valid rows (the denominator of valid_measurement_fraction)', ('row',)),
 'row_ids': ('id', 'measurement row IDs in row order (x then y per lenslet)', ('row',))}
CANONICAL_HISTORY_ARRAYS = {'measurement_row_masks': ('bool', 'effective rows used by the reconstructor', ('frame', 'row')),
 'valid_measurement_fraction': ('fraction', 'effective rows over calibration-valid rows', ('frame',)),
 'valid_subaperture_fraction': ('fraction', 'sensor-valid lenslets over retained lenslets', ('frame',)),
 'saturation_fraction': ('fraction', 'clipped actuators of the applied command', ('frame',)),
 'reconstruction_usable': ('bool', 'a usable reconstruction reached the controller', ('frame',)),
 'open_loop_opd_rms_m': ('m', 'piston-removed pupil RMS of the atmosphere', ('frame',)),
 'pre_update_residual_opd_rms_m': ('m', 'residual the sensor saw', ('frame',)),
 'post_update_residual_opd_rms_m': ('m', "residual after the frame's update", ('frame',)),
 'subaperture_ids': ('id', 'retained lenslet IDs in lenslet order', ('lenslet',))}
CANONICAL_TELEMETRY_ARRAYS = {'centroids_xy_px': ('px',
                     'noisy processed centroid in window pixel coordinates (x = column, y = row); NaN where not finite',
                     ('frame', 'lenslet', 'xy')),
 'expected_centroids_xy_px': ('px',
                              'plain centre of gravity of the expected processed window of the same frame, same coordinates; NaN where the '
                              'window total is not positive',
                              ('frame', 'lenslet', 'xy')),
 'centroid_sigma_xy_px': ('px',
                          "detector_covariance_v2 temporal sigma per axis at the frame's own expected spot; NaN where unsupported",
                          ('frame', 'lenslet', 'xy')),
 'fluxes_e': ('e', "model-expected processed window flux (the flux gate's input)", ('frame', 'lenslet')),
 'peak_snr': ('1', 'peak-pixel SNR', ('frame', 'lenslet')),
 'total_snr': ('1', 'window-total SNR (SNR_T)', ('frame', 'lenslet')),
 'centroid_sigma_px': ('px', 'larger-axis model sigma; 1e6 where undefined', ('frame', 'lenslet')),
 'clipping_fraction': ('fraction', 'expected flux outside the window (1 - capture)', ('frame', 'lenslet')),
 'centroid_calibration_sigma_px': ('px', 'calibration-ensemble sigma (persistent per-run bias)', ('frame', 'lenslet')),
 'masked_pixel_fraction': ('fraction', 'masked (bad) fraction of the centroid window', ('frame', 'lenslet')),
 'saturated_pixel_count': ('pixels', 'saturated pixels per block', ('frame', 'lenslet')),
 'valid_subapertures': ('bool',
                        'sensor validity (aggregate of the four gates); for the mask-locked arm the locked validity',
                        ('frame', 'lenslet')),
 'valid_by_flux': ('bool', 'flux gate', ('frame', 'lenslet')),
 'valid_by_snr': ('bool', 'peak-SNR gate', ('frame', 'lenslet')),
 'valid_by_uncertainty': ('bool', 'centroid-sigma gate', ('frame', 'lenslet')),
 'valid_by_clipping': ('bool', 'window-clipping gate', ('frame', 'lenslet')),
 'uncertainty_supported': ('bool', 'detector_covariance_v2 supports the lenslet', ('frame', 'lenslet'))}
CANONICAL_WEIGHT_ARRAYS = {'propagation_weights__weights_m2_per_px2': ('m2_opd_per_px2',
                                             'pupil variance of the DM response to a unit slope in the row (fixed reconstructor)',
                                             ('row',))}
CANONICAL_MAP_ARRAYS = {'residual_maps__pupil_mask': ('bool', 'pupil samples kept by the map recorder', ('y', 'x'))}
CANONICAL_RESIDUAL_MAP_ARM = ('m', 'post-update residual OPD at the pupil samples (float32)', ('analysed_frame', 'pupil_sample'))
CANONICAL_LOCK_ARRAYS = {'mask_lock__rows_removed': ('rows', "rows the lock removed from the noisy arm's own validity", ('frame',)),
 'mask_lock__rows_added': ('rows', 'rows the lock forced valid', ('frame',)),
 'mask_lock__rows_unaddable': ('rows', 'scheduled rows that could not be forced (partial lock only)', ('frame',)),
 'mask_lock__own_valid_subapertures': ('bool', "the noisy sensor's own gate decisions before the lock", ('frame', 'lenslet'))}


class AnalysisError(SystemExit):
    """The record or a sidecar cannot be analysed as it is; nothing is written."""


# -- Student t without SciPy --------------------------------------------------


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction of the incomplete beta function (modified Lentz)."""

    tiny = 1.0e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = tiny if abs(d) < tiny else d
    d = 1.0 / d
    h = d
    for m in range(1, 400):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = tiny if abs(d) < tiny else d
        c = 1.0 + aa / c
        c = tiny if abs(c) < tiny else c
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = tiny if abs(d) < tiny else d
        c = 1.0 + aa / c
        c = tiny if abs(c) < tiny else c
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1.0e-15:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta ``I_x(a, b)`` by the continued fraction."""

    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def student_t_cdf(t: float, dof: float) -> float:
    x = dof / (dof + t * t)
    tail = 0.5 * betainc(0.5 * dof, 0.5, x)
    return 1.0 - tail if t >= 0.0 else tail


def student_t_quantile(p: float, dof: float) -> float:
    """The ``p`` quantile of Student's t with ``dof`` degrees of freedom (bisection to 1e-12)."""

    if not 0.0 < p < 1.0 or dof <= 0.0:
        raise ValueError("p must lie in (0, 1) and dof must be positive.")
    if p == 0.5:
        return 0.0
    if p < 0.5:
        return -student_t_quantile(1.0 - p, dof)
    low, high = 0.0, 1.0
    while student_t_cdf(high, dof) < p:
        high *= 2.0
        if high > 1.0e12:
            raise ValueError("the quantile did not bracket.")
    for _ in range(200):
        mid = 0.5 * (low + high)
        if student_t_cdf(mid, dof) < p:
            low = mid
        else:
            high = mid
        if high - low < 1.0e-12 * max(1.0, high):
            break
    return 0.5 * (low + high)


def t_interval(values: np.ndarray, confidence: float) -> dict[str, Any]:
    """Mean, sample SD, SE and the two-sided Student t interval over independent units."""

    data = np.asarray(values, dtype=float)
    n = int(data.size)
    out: dict[str, Any] = {"n": n}
    if n == 0:
        out.update(mean=None, sd=None, se=None, half_width=None, low=None, high=None, status="no units")
        return out
    mean = float(np.mean(data))
    out["mean"] = mean
    if n < 2:
        out.update(sd=None, se=None, half_width=None, low=None, high=None, status="one unit: no interval")
        return out
    sd = float(np.std(data, ddof=1))
    se = sd / math.sqrt(n)
    quantile = student_t_quantile(0.5 + 0.5 * confidence, n - 1)
    out.update(sd=sd, se=se, t_quantile=quantile, dof=n - 1, half_width=quantile * se, low=mean - quantile * se, high=mean + quantile * se)
    out["status"] = "degenerate: zero scatter" if sd == 0.0 else "ok"
    return out


# -- Loading ------------------------------------------------------------------


def load_sidecar(path: Path) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    if not path.is_file():
        raise AnalysisError(f"sidecar {path} is missing.")
    try:
        with np.load(path, allow_pickle=False) as archive:
            if "metadata_json" not in archive.files:
                raise AnalysisError(f"{path}: no metadata_json entry.")
            metadata = json.loads(archive["metadata_json"].item())
            arrays = {name: archive[name] for name in archive.files if name != "metadata_json"}
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        raise AnalysisError(f"{path}: not a readable sidecar ({exc}).") from None
    if metadata.get("schema") != SIDECAR_SCHEMA:
        raise AnalysisError(f"{path}: schema {metadata.get('schema')!r} is not {SIDECAR_SCHEMA}.")
    declared = metadata.get("arrays", {})
    if set(declared) != set(arrays):
        raise AnalysisError(f"{path}: the arrays present do not match the declared arrays.")
    for name, spec in declared.items():
        if str(arrays[name].dtype) != spec["dtype"] or list(arrays[name].shape) != list(spec["shape"]):
            raise AnalysisError(f"{path}: array {name} does not match its declaration.")
    return metadata, arrays


def canonical_row_ids(lenslet_ids: tuple[str, ...]) -> tuple[str, ...]:
    """The Shack-Hartmann row layout: ``<lenslet>:x`` then ``<lenslet>:y`` per lenslet (as the package defines it)."""

    return tuple(row for lenslet in lenslet_ids for row in (f"{lenslet}:x", f"{lenslet}:y"))


def expected_sidecar_layout(
    *,
    diagnostic: dict[str, Any],
    n_steps: int,
    burn_in: int,
    n_rows: int,
    n_lenslets: int,
    telemetry_unavailable: dict[str, list[str]],
    weights_available: bool,
) -> dict[str, tuple[str, tuple[int, ...] | None, str, str, tuple[str, ...]]]:
    """Every array a sidecar of this diagnostic protocol must hold (the evidence runner's rule, repeated)."""

    analysed = n_steps - burn_in
    layout: dict[str, tuple[str, tuple[int, ...] | None, str, str, tuple[str, ...]]] = {}
    series = {
        "frame_index": ("int64", (n_steps,)), "analysed_frame_index": ("int64", (analysed,)),
        "delta_v_m2": ("float64", (analysed,)), "mean_square_difference_m2": ("float64", (analysed,)),
        "cross_term_m2": ("float64", (analysed,)), "mask_disagreement_rows": ("int64", (n_steps,)),
        "calibration_valid_rows": ("bool", (n_rows,)), "row_ids": ("str", (n_rows,)),
    }
    for name, (dtype, shape) in series.items():
        unit, meaning, axes = CANONICAL_SERIES_ARRAYS[name]
        layout[name] = (dtype, shape, unit, meaning, axes)
    for arm in diagnostic["arm_order"]:
        for name, (unit, meaning, axes) in CANONICAL_HISTORY_ARRAYS.items():
            if name == "subaperture_ids":
                dtype, shape = "str", (n_lenslets,)
            elif unit == "bool":
                dtype, shape = "bool", ((n_steps, n_rows) if "row" in axes else (n_steps,))
            else:
                dtype, shape = "float64", (n_steps,)
            layout[f"{arm}__{name}"] = (dtype, shape, unit, meaning, axes)
        for name in diagnostic.get("trace_fields", {}).get("telemetry", []):
            if name in telemetry_unavailable.get(arm, []):
                continue
            unit, meaning, axes = CANONICAL_TELEMETRY_ARRAYS[name]
            shape = (n_steps, n_lenslets, 2) if "xy" in axes else (n_steps, n_lenslets)
            layout[f"{arm}__telemetry__{name}"] = ("bool" if unit == "bool" else "float64", shape, unit, meaning, axes)
    if weights_available:
        unit, meaning, axes = CANONICAL_WEIGHT_ARRAYS["propagation_weights__weights_m2_per_px2"]
        layout["propagation_weights__weights_m2_per_px2"] = ("float64", (n_rows,), unit, meaning, axes)
    if diagnostic.get("map_retention", {}).get("retained"):
        unit, meaning, axes = CANONICAL_MAP_ARRAYS["residual_maps__pupil_mask"]
        layout["residual_maps__pupil_mask"] = ("bool", None, unit, meaning, axes)
        for arm in diagnostic["arm_order"]:
            layout[f"residual_maps__{arm}"] = ("float32", None, *CANONICAL_RESIDUAL_MAP_ARM)
    if diagnostic.get("mode") == "mask_locked":
        for name, (unit, meaning, axes) in CANONICAL_LOCK_ARRAYS.items():
            dtype, shape = ("bool", (n_steps, n_lenslets)) if unit == "bool" else ("int64", (n_steps,))
            layout[name] = (dtype, shape, unit, meaning, axes)
    return layout


def validate_sidecar_semantics(metadata: dict[str, Any], arrays: dict[str, np.ndarray], row: dict[str, Any], *, where: str) -> None:
    """Refuse a sidecar whose content does not carry the row's trace semantics (NumPy-only check).

    The same contract the evidence runner enforces before reusing a sidecar,
    repeated here so the package-free analysis never reduces malformed input:
    embedded frame counts, label and seed against the row; the embedded
    diagnostic protocol against its hash and the row's; trace schema and arm
    order; exactly the arrays the protocol requires, each with its dtype,
    full shape and the canonical units, axes and meaning; frame indices as
    the declared domains; one lenslet order for every arm and the canonical
    interleaved x/y rows; retained maps matching the pupil mask and burn-in
    (independent review T1-02, rounds 1 and 2).  Nothing is repaired.
    """

    def refuse(reason: str) -> None:
        raise AnalysisError(f"{where}: {reason}")

    protocol = row.get("protocol", {})
    n_steps, burn_in = int(protocol.get("n_steps", -1)), int(protocol.get("burn_in_frames", -1))
    if int(metadata.get("n_steps", -2)) != n_steps or int(metadata.get("burn_in_frames", -2)) != burn_in:
        refuse("embedded frame counts differ from the run's protocol")
    if metadata.get("label") != row.get("label") or metadata.get("root_seed") != row.get("root_seed"):
        refuse("embeds another label or seed than its run")
    diagnostic = row.get("diagnostic_protocol")
    embedded = metadata.get("diagnostic_protocol")
    canonical = lambda value: json.dumps(value, sort_keys=True, default=str)  # noqa: E731
    if not isinstance(diagnostic, dict) or not isinstance(embedded, dict):
        refuse("no diagnostic protocol in the row or the sidecar")
    if hashlib.sha256(canonical(embedded).encode()).hexdigest() != metadata.get("diagnostic_protocol_hash"):
        refuse("embedded diagnostic protocol is not the payload of its embedded hash")
    if canonical(embedded) != canonical(diagnostic) or metadata.get("diagnostic_protocol_hash") != row.get("diagnostic_protocol_hash"):
        refuse("embedded diagnostic protocol is not the row's")
    if metadata.get("trace_schema") != diagnostic.get("trace_schema") or list(metadata.get("arm_order", [])) != list(diagnostic.get("arm_order", [])):
        refuse("embedded trace schema or arm order is not the protocol's")
    arms = list(diagnostic["arm_order"])
    noisy = next(arm for arm in arms if arm.startswith("noise_on"))
    twin = next(arm for arm in arms if arm != noisy)
    if metadata.get("noisy_arm") != noisy or metadata.get("twin_arm") != twin:
        refuse("noisy and twin arm names do not follow the arm order")
    arm_metadata = metadata.get("arms")
    if not isinstance(arm_metadata, dict) or set(arm_metadata) != set(arms):
        refuse("per-arm metadata does not name exactly the protocol's arms")
    unavailable = {arm: list((arm_metadata[arm] or {}).get("telemetry_unavailable", [])) for arm in arms}
    for arm, names in unavailable.items():
        if any(name not in CANONICAL_TELEMETRY_ARRAYS for name in names):
            refuse(f"arm {arm} declares unknown unavailable telemetry fields")
    if "row_ids" not in arrays or "calibration_valid_rows" not in arrays or f"{noisy}__subaperture_ids" not in arrays:
        refuse("no row or lenslet layout")
    if arrays["row_ids"].ndim != 1 or arrays[f"{noisy}__subaperture_ids"].ndim != 1:
        refuse("row or lenslet identifiers are not one-dimensional")
    n_rows, n_lenslets = int(arrays["row_ids"].shape[0]), int(arrays[f"{noisy}__subaperture_ids"].shape[0])
    if n_rows != 2 * n_lenslets or n_rows < 2:
        refuse(f"{n_rows} rows for {n_lenslets} lenslets; two rows per lenslet are required")
    weights_available = bool((metadata.get("propagation_weights") or {}).get("available")) if diagnostic.get("propagation_weights") else False
    if "propagation_weights__weights_m2_per_px2" in arrays and not weights_available:
        refuse("holds propagation weights its metadata does not declare available")
    layout = expected_sidecar_layout(
        diagnostic=diagnostic, n_steps=n_steps, burn_in=burn_in, n_rows=n_rows, n_lenslets=n_lenslets,
        telemetry_unavailable=unavailable, weights_available=weights_available,
    )
    missing, extra = sorted(set(layout) - set(arrays)), sorted(set(arrays) - set(layout))
    if missing or extra:
        refuse(f"does not hold exactly the protocol's arrays (missing {missing[:8]}, undeclared {extra[:8]})")
    declared = metadata.get("arrays", {})
    for name, (dtype, shape, unit, meaning, axes) in layout.items():
        array, spec = arrays[name], declared.get(name, {})
        if spec.get("units") != unit or list(spec.get("axes", [])) != list(axes) or spec.get("meaning") != meaning:
            refuse(f"array {name} is declared with units {spec.get('units')!r} and axes {spec.get('axes')!r}; the protocol defines {unit!r} and {list(axes)!r}")
        if dtype == "str":
            if array.dtype.kind != "U":
                refuse(f"array {name} must hold unicode identifiers")
        elif str(array.dtype) != dtype:
            refuse(f"array {name} has dtype {array.dtype}, the protocol requires {dtype}")
        if shape is not None and tuple(int(size) for size in array.shape) != tuple(shape):
            refuse(f"array {name} has shape {array.shape}, the protocol requires {shape}")
    if not np.array_equal(arrays["frame_index"], np.arange(n_steps)) or not np.array_equal(arrays["analysed_frame_index"], np.arange(burn_in, n_steps)):
        refuse("frame indices are not the declared domains")
    lenslet_ids = tuple(str(item) for item in arrays[f"{noisy}__subaperture_ids"].tolist())
    if len(set(lenslet_ids)) != n_lenslets:
        refuse("the lenslet identifiers are duplicated")
    for arm in arms:
        if tuple(str(item) for item in arrays[f"{arm}__subaperture_ids"].tolist()) != lenslet_ids:
            refuse(f"arm {arm} lists the lenslets in another order than arm {noisy}")
    if tuple(str(item) for item in arrays["row_ids"].tolist()) != canonical_row_ids(lenslet_ids):
        refuse("row_ids are not the canonical interleaved x/y rows of the lenslet order")
    if diagnostic.get("map_retention", {}).get("retained"):
        mask = arrays["residual_maps__pupil_mask"]
        if mask.ndim != 2:
            refuse("the retained pupil mask is not a 2-D map")
        samples = int(np.count_nonzero(mask))
        for arm in arms:
            if arrays[f"residual_maps__{arm}"].shape != (n_steps - burn_in, samples):
                refuse(f"retained maps of {arm} do not match the mask and burn-in")


def load_traced_record(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The record and, per completed run, its row with the verified sidecar loaded."""

    record = json.loads(path.read_text())
    runs = record.get("runs")
    if not isinstance(runs, list) or record.get("record_family") != "noise_isolation_traced":
        raise AnalysisError(f"{path} is not a traced noise-isolation record.")
    loaded = []
    for row in runs:
        if row.get("status") == "refused":
            loaded.append({"row": row, "refused": True})
            continue
        reference = row.get("sidecar")
        if not isinstance(reference, dict):
            raise AnalysisError(f"{path}: run {row.get('label')}/{row.get('root_seed')} has no sidecar reference.")
        file = path.parent / reference["file"]
        payload = file.read_bytes() if file.is_file() else None
        if payload is None or hashlib.sha256(payload).hexdigest() != reference["sha256"] or len(payload) != reference["bytes"]:
            raise AnalysisError(f"{path}: sidecar {file} is missing or its bytes are not the recorded ones.")
        metadata, arrays = load_sidecar(file)
        for key in ("label", "root_seed", "protocol_hash", "diagnostic_protocol_hash", "config_hash"):
            if metadata.get(key) != row.get(key):
                raise AnalysisError(f"{path}: sidecar {file.name} records {key} = {metadata.get(key)!r}, the row {row.get(key)!r}.")
        validate_sidecar_semantics(metadata, arrays, row, where=f"{path}: sidecar {file.name}")
        loaded.append({"row": row, "refused": False, "metadata": metadata, "arrays": arrays, "file": file.name})
    return record, loaded


# -- Per-run diagnostics ------------------------------------------------------


def block_table(series: np.ndarray, lengths: tuple[int, ...]) -> dict[str, Any]:
    data = np.asarray(series, dtype=float)
    n = int(data.size)
    rows = []
    for length in lengths:
        blocks = n // int(length)
        entry: dict[str, Any] = {"block_frames": int(length), "blocks": int(blocks)}
        if blocks >= 2:
            means = data[: blocks * length].reshape(blocks, length).mean(axis=1)
            entry["se"] = float(np.std(means, ddof=1) / math.sqrt(blocks))
            entry["se_relative_uncertainty"] = float(1.0 / math.sqrt(2.0 * (blocks - 1)))
        else:
            entry["se"] = None
            entry["status"] = "not estimable: fewer than two blocks"
        rows.append(entry)
    admissible = [row for row in rows if row["se"] is not None and row["blocks"] >= PLATEAU_MIN_BLOCKS]
    plateau: dict[str, Any] = {"identified": False, "rule": f"smallest length with >= {PLATEAU_MIN_BLOCKS} blocks whose SE the next admissible length exceeds by at most {PLATEAU_TOLERANCE:.0%}"}
    for current, following in zip(admissible, admissible[1:]):
        if following["se"] <= (1.0 + PLATEAU_TOLERANCE) * current["se"]:
            plateau.update(identified=True, block_frames=current["block_frames"], se=current["se"], blocks=current["blocks"])
            break
    if not plateau["identified"]:
        if admissible:
            largest = admissible[-1]
            plateau.update(block_frames=largest["block_frames"], se=largest["se"], blocks=largest["blocks"], meaning="no plateau identified; the largest admissible length's SE is a lower bound")
        else:
            plateau.update(se=None, meaning=f"series too short: no length has {PLATEAU_MIN_BLOCKS} blocks")
    return {"frames": n, "mean": float(np.mean(data)) if n else None, "blocks": rows, "plateau": plateau}


def autocorrelation_time(series: np.ndarray) -> dict[str, Any]:
    data = np.asarray(series, dtype=float)
    n = int(data.size)
    if n < 8:
        return {"frames": n, "tau": None, "status": "series too short (fewer than 8 frames)"}
    centred = data - np.mean(data)
    variance = float(np.dot(centred, centred) / n)
    if variance == 0.0:
        return {"frames": n, "tau": None, "status": "zero variance: no correlation time"}
    size = 1
    while size < 2 * n:
        size *= 2
    spectrum = np.fft.rfft(centred, size)
    autocov = np.fft.irfft(spectrum * np.conj(spectrum), size)[:n] / n
    rho = autocov / autocov[0]
    tau = 1.0
    window = None
    for m in range(1, n // 2):
        tau = 1.0 + 2.0 * float(np.sum(rho[1 : m + 1]))
        if m >= SOKAL_C * tau:
            window = m
            break
    if window is None:
        return {"frames": n, "tau": None, "status": f"no window M >= {SOKAL_C:g} tau(M) closes below n/2: correlation time not identified", "tau_at_half_series": float(tau)}
    if tau < 1.0:
        # The automatic window assumes a non-negative autocorrelation; a
        # negative early lag closes it at once with an estimate below one (or
        # below zero).  Such an estimate is reported, but no uncertainty is
        # derived from it: supporting anticorrelated series needs another,
        # validated estimator (independent review T1-05, 2026-10-20).
        return {
            "frames": n, "tau": float(tau), "window": int(window), "tau_se": None,
            "effective_samples": None, "se_of_mean": None,
            "status": (
                "unsupported: integrated autocorrelation-time estimate below one "
                f"({'non-positive' if tau <= 0.0 else 'anticorrelated or short series'}); the window rule "
                "assumes a non-negative autocorrelation, so no uncertainty is derived"
            ),
        }
    tau_se = float(tau * math.sqrt(2.0 * (2 * window + 1) / n))
    reliable = n >= TAU_RELIABLE_FACTOR * tau
    return {
        "frames": n, "tau": float(tau), "window": int(window), "tau_se": tau_se,
        "effective_samples": float(n / tau), "se_of_mean": float(math.sqrt(variance * tau / n)),
        "status": "ok" if reliable else f"unreliable: fewer than {TAU_RELIABLE_FACTOR:g} tau frames",
    }


def excursion(series: np.ndarray) -> dict[str, Any]:
    data = np.asarray(series, dtype=float)
    blocks = data.size // EXCURSION_BLOCK
    median = float(np.median(data)) if data.size else None
    if blocks < 1 or median is None:
        return {"flagged": False, "status": f"series shorter than one {EXCURSION_BLOCK}-frame block", "median": median}
    means = data[: blocks * EXCURSION_BLOCK].reshape(blocks, EXCURSION_BLOCK).mean(axis=1)
    if median <= 0.0:
        return {"flagged": False, "status": "non-positive median: the rule is undefined", "median": median}
    ratios = means / median
    flagged = [int(index) for index in np.flatnonzero(ratios > EXCURSION_FACTOR)]
    return {
        "flagged": bool(flagged), "median": median, "block_frames": EXCURSION_BLOCK, "factor": EXCURSION_FACTOR,
        "max_block_over_median": float(np.max(ratios)), "flagged_blocks": flagged,
        "flagged_frame_ranges": [[int(index * EXCURSION_BLOCK), int((index + 1) * EXCURSION_BLOCK - 1)] for index in flagged],
        # The flagged blocks' share of the positive excess over the median.
        "excess_fraction_in_flagged_blocks": (
            float(np.sum(means[flagged] - median) / max(float(np.sum(np.maximum(means - median, 0.0))), 1.0e-300)) if flagged else 0.0
        ),
    }


def operating_state(arrays: dict[str, np.ndarray], metadata: dict[str, Any], analysed: np.ndarray) -> dict[str, Any]:
    noisy, twin = metadata["noisy_arm"], metadata["twin_arm"]

    def field(arm: str, name: str) -> np.ndarray | None:
        return arrays.get(f"{arm}__telemetry__{name}")

    needed = [field(noisy, name) for name in ("centroids_xy_px", "expected_centroids_xy_px", "centroid_sigma_xy_px", "valid_subapertures", "uncertainty_supported")]
    if any(item is None for item in needed):
        return {"available": False, "reason": "telemetry fields missing from the sidecar"}
    centroids, expected, sigma, valid, supported = [np.asarray(item)[analysed] for item in needed]
    support = np.all(valid & supported & np.all(np.isfinite(centroids), axis=2) & np.all(np.isfinite(expected), axis=2), axis=0)
    out: dict[str, Any] = {"analysed_frames": int(analysed.size), "support_lenslets": int(np.count_nonzero(support)), "lenslets": int(support.size)}
    if analysed.size < 2 or not np.any(support):
        out.update(available=False, reason="fewer than two analysed frames or an empty support")
        return out
    residual = (centroids - expected)[:, support, :]
    mean = residual.mean(axis=0)
    variance = residual.var(axis=0, ddof=1)
    second = np.mean(residual**2, axis=0)
    model = np.mean(sigma[:, support, :] ** 2, axis=0)
    per_lenslet_ratio = np.sum(variance, axis=1) / np.sum(model, axis=1)
    out.update(
        available=True,
        equal_weight={
            "mean_residual_px": [float(np.mean(mean[:, 0])), float(np.mean(mean[:, 1]))],
            "realized_variance_px2": float(np.mean(np.sum(variance, axis=1))),
            "realized_second_moment_px2": float(np.mean(np.sum(second, axis=1))),
            "model_variance_px2": float(np.mean(np.sum(model, axis=1))),
            "ratio_variance_over_model": float(np.mean(np.sum(variance, axis=1)) / np.mean(np.sum(model, axis=1))),
            "ratio_second_moment_over_model": float(np.mean(np.sum(second, axis=1)) / np.mean(np.sum(model, axis=1))),
            "per_lenslet_ratio_min_median_max": [float(np.min(per_lenslet_ratio)), float(np.median(per_lenslet_ratio)), float(np.max(per_lenslet_ratio))],
        },
    )
    twin_sigma = field(twin, "centroid_sigma_xy_px")
    if twin_sigma is not None:
        out["twin_model_variance_px2"] = float(np.nanmean(np.sum(np.mean(np.asarray(twin_sigma)[analysed][:, support, :] ** 2, axis=0), axis=1)))
    snr = field(noisy, "total_snr")
    if snr is not None:
        snr_support = np.asarray(snr)[analysed][:, support]
        out["snr_t_mean"] = float(np.mean(snr_support))
        out["first_order_bias_estimate"] = float(np.mean(4.0 / snr_support**2))
    clipping = field(noisy, "clipping_fraction")
    if clipping is not None:
        out["capture_fraction_mean"] = float(1.0 - np.mean(np.asarray(clipping)[analysed][:, support]))
    weights = arrays.get("propagation_weights__weights_m2_per_px2")
    if weights is not None:
        per_row = np.asarray(weights, dtype=float).reshape(-1, 2)[support, :]
        total = float(np.sum(per_row))
        out["propagation_weighted"] = {
            "domain": "support lenslets, both axes; weights = fixed-reconstructor pupil response per row (m2 per px2)",
            "weight_total_m2_per_px2": total,
            "ratio_variance_over_model": float(np.sum(per_row * variance) / np.sum(per_row * model)),
            "ratio_second_moment_over_model": float(np.sum(per_row * second) / np.sum(per_row * model)),
            "propagated_realized_variance_m2": float(np.sum(per_row * variance)),
            "propagated_model_variance_m2": float(np.sum(per_row * model)),
            "support_weight_fraction": float(total / np.sum(np.asarray(weights, dtype=float))),
        }
    else:
        out["propagation_weighted"] = None
    return out


def analyse_run(entry: dict[str, Any], lengths: tuple[int, ...]) -> dict[str, Any]:
    row, metadata, arrays = entry["row"], entry["metadata"], entry["arrays"]
    analysed = np.asarray(arrays["analysed_frame_index"], dtype=int)
    noisy, twin = metadata["noisy_arm"], metadata["twin_arm"]
    delta = np.asarray(arrays["delta_v_m2"], dtype=float)
    msd = np.asarray(arrays["mean_square_difference_m2"], dtype=float)
    cross = np.asarray(arrays["cross_term_m2"], dtype=float)
    masks_noisy = np.asarray(arrays[f"{noisy}__measurement_row_masks"], dtype=bool)[analysed]
    masks_twin = np.asarray(arrays[f"{twin}__measurement_row_masks"], dtype=bool)[analysed]
    disagreement = masks_noisy != masks_twin
    usable_noisy = np.asarray(arrays[f"{noisy}__reconstruction_usable"], dtype=bool)[analysed]
    usable_twin = np.asarray(arrays[f"{twin}__reconstruction_usable"], dtype=bool)[analysed]
    recovery_acted = any(
        isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
        for arm in (noisy, twin)
        for key, value in (metadata["arms"][arm].get("recovery") or {}).items()
        if key != "config_hash"
    )
    disagreement_fraction = float(np.mean(disagreement)) if disagreement.size else 0.0
    rejected = int(np.count_nonzero(~usable_noisy) + np.count_nonzero(~usable_twin))
    cross_blocks = block_table(cross, (EXCURSION_BLOCK,))["blocks"][0]
    delta_blocks = block_table(delta, lengths)
    result = {
        "label": row["label"],
        "root_seed": int(row["root_seed"]),
        "sidecar": entry["file"],
        "analysed_frames": int(analysed.size),
        "detected_e_full_subap": row.get("detected_e_full_subap"),
        "recorded": {"noise_variance_m2": row.get("noise_variance_m2"), "noise_variance_standard_error_m2": row.get("noise_variance_standard_error_m2"), "predicted_centroid_variance_px2": row.get("predicted_centroid_variance_px2")},
        "delta_v": {"mean_m2": float(np.mean(delta)), "median_m2": float(np.median(delta)), "min_m2": float(np.min(delta)), "max_m2": float(np.max(delta)), "nonpositive_frames": int(np.count_nonzero(delta <= 0.0)), "blocks": delta_blocks, "autocorrelation": autocorrelation_time(delta), "excursion": excursion(delta)},
        "mean_square_difference": {"mean_m2": float(np.mean(msd)), "se_25_m2": block_table(msd, (EXCURSION_BLOCK,))["blocks"][0]["se"]},
        "cross_term": {"mean_m2": float(np.mean(cross)), "se_25_m2": cross_blocks["se"], "sd_m2": float(np.std(cross, ddof=1)) if cross.size > 1 else None, "fraction_positive": float(np.mean(cross > 0.0)), "mean_over_se": (float(np.mean(cross) / cross_blocks["se"]) if cross_blocks["se"] else None)},
        "masks": {"disagreement_row_frame_fraction": disagreement_fraction, "disagreement_frames": int(np.count_nonzero(np.any(disagreement, axis=1))), "rejected_frames_both_arms": rejected, "recovery_acted": bool(recovery_acted), "gate_quiet": bool(disagreement_fraction < GATE_QUIET_DISAGREEMENT and rejected == 0 and not recovery_acted)},
        "saturation": {arm: {"max": float(np.max(np.asarray(arrays[f"{arm}__saturation_fraction"])[analysed])), "mean": float(np.mean(np.asarray(arrays[f"{arm}__saturation_fraction"])[analysed]))} for arm in (noisy, twin)},
        "valid_fraction": {arm: {"min": float(np.min(np.asarray(arrays[f"{arm}__valid_measurement_fraction"])[analysed])), "mean": float(np.mean(np.asarray(arrays[f"{arm}__valid_measurement_fraction"])[analysed]))} for arm in (noisy, twin)},
        "operating_state": operating_state(arrays, metadata, analysed),
    }
    if "lock" in metadata:
        result["lock"] = metadata["lock"]
    recorded = row.get("noise_variance_m2")
    if recorded is not None:
        result["delta_v"]["frame_mean_equals_recorded"] = bool(float(np.mean(delta)) == float(recorded))
    # The experiment's own E0 summary, cross-checked against this independent reduction.
    own = row.get("operating_state") or {}
    if own.get("available") and result["operating_state"].get("available"):
        theirs = own["equal_weight"]["ratio_variance_over_model"]
        ours = result["operating_state"]["equal_weight"]["ratio_variance_over_model"]
        result["operating_state"]["cross_check_with_runner_summary"] = {"runner": theirs, "here": ours, "agree_1e-12": bool(abs(theirs - ours) <= 1.0e-12 * max(abs(theirs), 1.0))}
    return result


# -- Population statistics ---------------------------------------------------


def _magnitude_of(label: str) -> float | None:
    try:
        return float(label.lstrip("m"))
    except ValueError:
        return None


def ols_slope(x: np.ndarray, y: np.ndarray) -> dict[str, Any]:
    """Unweighted least squares of y on x: slope, intercept and the fit SE of the slope."""

    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    n = int(x.size)
    if n < 2 or np.ptp(x) == 0.0:
        return {"n": n, "slope": None, "status": "fewer than two distinct points"}
    design = np.stack([x, np.ones(n)], axis=1)
    coefficients, *_ = np.linalg.lstsq(design, y, rcond=None)
    slope, intercept = float(coefficients[0]), float(coefficients[1])
    out: dict[str, Any] = {"n": n, "slope": slope, "intercept": intercept}
    if n > 2:
        residual = y - design @ coefficients
        sigma2 = float(np.sum(residual**2) / (n - 2))
        out["slope_se"] = float(math.sqrt(sigma2 / np.sum((x - np.mean(x)) ** 2)))
    else:
        out["slope_se"] = None
    return out


def weighted_fit(x: np.ndarray, y: np.ndarray, se: np.ndarray) -> dict[str, Any]:
    """Weighted least squares of y on x with weights 1/se**2 (the recorded estimator)."""

    x, y, se = np.asarray(x, dtype=float), np.asarray(y, dtype=float), np.asarray(se, dtype=float)
    n = int(x.size)
    if n < 2 or np.any(~(se > 0.0)) or np.ptp(x) == 0.0:
        return {"n": n, "slope": None, "status": "needs two distinct points with positive errors"}
    weights = 1.0 / se**2
    design = np.stack([x, np.ones(n)], axis=1)
    scaled = design * np.sqrt(weights)[:, None]
    coefficients, *_ = np.linalg.lstsq(scaled, y * np.sqrt(weights), rcond=None)
    covariance = np.linalg.inv(scaled.T @ scaled)
    residual = (y - design @ coefficients) * np.sqrt(weights)
    chi2 = float(np.sum(residual**2))
    dof = n - 2
    slope_se = float(math.sqrt(covariance[0, 0]))
    out = {"n": n, "slope": float(coefficients[0]), "intercept": float(coefficients[1]), "slope_se_unscaled": slope_se, "chi2": chi2, "dof": dof}
    if dof > 0:
        out["chi2_per_dof"] = chi2 / dof
        out["slope_se_scaled"] = slope_se * math.sqrt(max(chi2 / dof, 0.0))
    else:
        out["chi2_per_dof"] = None
        out["slope_se_scaled"] = None
    return out


def per_seed_slopes(table: dict[str, dict[int, float]], abscissa: dict[str, dict[int, float]], seeds: list[int], labels: list[str], confidence: float) -> dict[str, Any]:
    """Per-seed OLS slopes of log(table) against log(abscissa) over the given labels."""

    slopes = []
    excluded = []
    for seed in seeds:
        xs, ys = [], []
        for label in labels:
            y = table.get(label, {}).get(seed)
            x = abscissa.get(label, {}).get(seed)
            if y is None or x is None:
                continue
            if not (y > 0.0 and x > 0.0):
                excluded.append({"seed": seed, "label": label, "reason": "non-positive value cannot enter a log fit"})
                continue
            xs.append(math.log(x))
            ys.append(math.log(y))
        fit = ols_slope(np.asarray(xs), np.asarray(ys))
        if fit["slope"] is not None:
            slopes.append({"seed": seed, "slope": fit["slope"], "points": fit["n"]})
    interval = t_interval(np.asarray([item["slope"] for item in slopes]), confidence)
    return {"labels": labels, "per_seed": slopes, "excluded": excluded, "seed_mean": interval}


def bootstrap_slope(seed_means: dict[str, dict[int, float]], abscissa_by_label: dict[str, float], seeds: list[int], labels: list[str], resamples: int, rng_seed: int) -> dict[str, Any]:
    """F-06 convention: resample seeds with replacement, unweighted fit to the seed means."""

    rng = np.random.default_rng(rng_seed)
    usable = [label for label in labels if all(seed_means.get(label, {}).get(seed) is not None for seed in seeds) and abscissa_by_label.get(label, 0.0) > 0.0]
    if len(usable) < 2 or len(seeds) < 2:
        return {"status": "fewer than two usable magnitudes or seeds", "resamples": 0}
    matrix = np.array([[seed_means[label][seed] for seed in seeds] for label in usable])
    x = np.log(np.array([abscissa_by_label[label] for label in usable]))
    slopes = []
    for _ in range(int(resamples)):
        picked = rng.integers(0, len(seeds), size=len(seeds))
        means = matrix[:, picked].mean(axis=1)
        if np.any(means <= 0.0):
            continue
        slopes.append(ols_slope(x, np.log(means))["slope"])
    point = ols_slope(x, np.log(matrix.mean(axis=1)))["slope"]
    return {"convention": "whole-seed resampling of an unweighted fit to seed means (GPT F-06); descriptive, not additional realizations", "resamples": len(slopes), "requested": int(resamples), "point_slope": point, "bootstrap_sd": float(np.std(slopes, ddof=1)) if len(slopes) > 1 else None, "labels": usable}


def population(runs: list[dict[str, Any]], *, confidence: float, gate_quiet_labels: list[str] | None, bootstrap: int, bootstrap_seed: int) -> dict[str, Any]:
    labels = sorted({run["label"] for run in runs}, key=lambda label: (_magnitude_of(label) is None, _magnitude_of(label) or 0.0, label))
    seeds = sorted({run["root_seed"] for run in runs})
    by_key = {(run["label"], run["root_seed"]): run for run in runs}
    delta_v: dict[str, dict[int, float]] = {label: {} for label in labels}
    flux: dict[str, dict[int, float]] = {label: {} for label in labels}
    model_flat: dict[str, dict[int, float]] = {label: {} for label in labels}
    propagated: dict[str, dict[int, float]] = {label: {} for label in labels}
    operating_model: dict[str, dict[int, float]] = {label: {} for label in labels}
    per_magnitude: dict[str, Any] = {}
    for label in labels:
        members = [by_key[(label, seed)] for seed in seeds if (label, seed) in by_key]
        values = []
        for run in members:
            value = run["delta_v"]["mean_m2"]
            delta_v[label][run["root_seed"]] = value
            values.append(value)
            if run.get("detected_e_full_subap"):
                flux[label][run["root_seed"]] = float(run["detected_e_full_subap"])
            if run["recorded"].get("predicted_centroid_variance_px2"):
                model_flat[label][run["root_seed"]] = float(run["recorded"]["predicted_centroid_variance_px2"])
            state = run["operating_state"]
            if state.get("available"):
                operating_model[label][run["root_seed"]] = state["equal_weight"]["model_variance_px2"]
                if state.get("propagation_weighted"):
                    propagated[label][run["root_seed"]] = state["propagation_weighted"]["propagated_realized_variance_m2"]
        array = np.asarray(values, dtype=float)
        loo = [float(np.mean(np.delete(array, index))) for index in range(array.size)] if array.size > 1 else []
        gate_quiet = [run["root_seed"] for run in members if run["masks"]["gate_quiet"]]
        quiet_values = np.asarray([run["delta_v"]["mean_m2"] for run in members if run["masks"]["gate_quiet"]], dtype=float)
        entry = {
            "seeds": [run["root_seed"] for run in members],
            "detected_e_full_subap": float(np.mean([run["detected_e_full_subap"] for run in members if run.get("detected_e_full_subap")])) if any(run.get("detected_e_full_subap") for run in members) else None,
            "delta_v_m2": {"per_seed": {str(run["root_seed"]): run["delta_v"]["mean_m2"] for run in members}, "seed_statistics": t_interval(array, confidence), "median": float(np.median(array)) if array.size else None, "leave_one_seed_out_means": loo},
            "delta_v_gate_quiet_m2": {"seeds": gate_quiet, "seed_statistics": t_interval(quiet_values, confidence)},
            "within_run_errors": {"plateau_se_m2": [run["delta_v"]["blocks"]["plateau"].get("se") for run in members], "plateau_identified": [run["delta_v"]["blocks"]["plateau"]["identified"] for run in members], "se_25_m2": [next((block["se"] for block in run["delta_v"]["blocks"]["blocks"] if block["block_frames"] == 25), None) for run in members], "tau": [run["delta_v"]["autocorrelation"].get("tau") for run in members], "tau_status": [run["delta_v"]["autocorrelation"]["status"] for run in members]},
            "excursions": [run["root_seed"] for run in members if run["delta_v"]["excursion"].get("flagged")],
            "mask_disagreement_fraction": {str(run["root_seed"]): run["masks"]["disagreement_row_frame_fraction"] for run in members},
            "rejected_frames": {str(run["root_seed"]): run["masks"]["rejected_frames_both_arms"] for run in members},
            "saturation_max_noisy": {str(run["root_seed"]): run["saturation"][next(iter(run["saturation"]))]["max"] for run in members},
            "cross_term_mean_over_se": {str(run["root_seed"]): run["cross_term"]["mean_over_se"] for run in members},
        }
        ratios_equal = [run["operating_state"]["equal_weight"]["ratio_variance_over_model"] for run in members if run["operating_state"].get("available")]
        ratios_second = [run["operating_state"]["equal_weight"]["ratio_second_moment_over_model"] for run in members if run["operating_state"].get("available")]
        ratios_weighted = [run["operating_state"]["propagation_weighted"]["ratio_variance_over_model"] for run in members if run["operating_state"].get("available") and run["operating_state"].get("propagation_weighted")]
        means_px = [run["operating_state"]["equal_weight"]["mean_residual_px"] for run in members if run["operating_state"].get("available")]
        bias = [run["operating_state"].get("first_order_bias_estimate") for run in members if run["operating_state"].get("first_order_bias_estimate") is not None]
        entry["e0"] = {
            "ratio_variance_over_model_equal_weight": t_interval(np.asarray(ratios_equal), confidence),
            "ratio_second_moment_over_model_equal_weight": t_interval(np.asarray(ratios_second), confidence),
            "ratio_variance_over_model_propagation_weighted": t_interval(np.asarray(ratios_weighted), confidence),
            "mean_residual_px_x": t_interval(np.asarray([item[0] for item in means_px]), confidence),
            "mean_residual_px_y": t_interval(np.asarray([item[1] for item in means_px]), confidence),
            "first_order_bias_estimate_4_over_snr_t2": float(np.mean(bias)) if bias else None,
            "support_lenslets": [run["operating_state"].get("support_lenslets") for run in members],
            "capture_fraction_mean": [run["operating_state"].get("capture_fraction_mean") for run in members],
        }
        ratio_flat = [run["delta_v"]["mean_m2"] / run["recorded"]["predicted_centroid_variance_px2"] for run in members if run["recorded"].get("predicted_centroid_variance_px2")]
        ratio_prop = [run["delta_v"]["mean_m2"] / run["operating_state"]["propagation_weighted"]["propagated_realized_variance_m2"] for run in members if run["operating_state"].get("available") and run["operating_state"].get("propagation_weighted") and run["operating_state"]["propagation_weighted"]["propagated_realized_variance_m2"] > 0.0]
        ratio_opmodel = [run["delta_v"]["mean_m2"] / run["operating_state"]["equal_weight"]["model_variance_px2"] for run in members if run["operating_state"].get("available")]
        entry["loop_linearity"] = {
            "delta_v_over_flat_model_m2_per_px2": t_interval(np.asarray(ratio_flat), confidence),
            "delta_v_over_operating_model_m2_per_px2": t_interval(np.asarray(ratio_opmodel), confidence),
            "delta_v_over_propagated_realized_variance": t_interval(np.asarray(ratio_prop), confidence),
        }
        per_magnitude[label] = entry
    # Domains.
    data_driven_quiet = [label for label in labels if all(by_key[(label, seed)]["masks"]["gate_quiet"] for seed in seeds if (label, seed) in by_key)]
    domains = {"all": labels, "gate_quiet_data_driven": data_driven_quiet}
    if gate_quiet_labels:
        domains["gate_quiet_predeclared"] = [label for label in gate_quiet_labels if label in labels]
    flux_by_label = {label: float(np.mean(list(flux[label].values()))) for label in labels if flux[label]}
    across: dict[str, Any] = {}
    for domain, members in domains.items():
        seed_means = {label: per_magnitude[label]["delta_v_m2"]["seed_statistics"]["mean"] for label in members}
        seed_se = {label: per_magnitude[label]["delta_v_m2"]["seed_statistics"]["se"] for label in members}
        # Two domains (independent review T1-04, 2026-10-20): the paired
        # per-seed slopes need positive seed means and a known flux only; the
        # historical inverse-variance fit also needs a positive across-seed
        # error, which a zero-scatter or one-seed population cannot give.
        paired = [label for label in members if seed_means[label] is not None and seed_means[label] > 0.0 and label in flux_by_label]
        usable = [label for label in paired if seed_se.get(label)]
        x = np.log(np.array([flux_by_label[label] for label in usable])) if usable else np.array([])
        y = np.log(np.array([seed_means[label] for label in usable])) if usable else np.array([])
        se_log = np.array([seed_se[label] / seed_means[label] for label in usable]) if usable else np.array([])
        historical = weighted_fit(x, y, se_log) if len(usable) >= 2 else {"status": "fewer than two magnitudes with a positive across-seed error"}
        if historical.get("slope") is not None:
            historical["se_from_minus_one_unscaled"] = (historical["slope"] + 1.0) / historical["slope_se_unscaled"]
            if historical.get("slope_se_scaled"):
                historical["se_from_minus_one_scaled"] = (historical["slope"] + 1.0) / historical["slope_se_scaled"]
        flux_table = {label: {seed: flux_by_label[label] for seed in seeds} for label in paired}
        slopes_flux = per_seed_slopes(delta_v, flux_table, seeds, paired, confidence)
        if slopes_flux["seed_mean"].get("se"):
            slopes_flux["seed_mean"]["se_from_minus_one"] = (slopes_flux["seed_mean"]["mean"] + 1.0) / slopes_flux["seed_mean"]["se"]
        slopes_prop = per_seed_slopes(delta_v, propagated, seeds, members, confidence)
        if slopes_prop["seed_mean"].get("se"):
            slopes_prop["seed_mean"]["se_from_plus_one"] = (slopes_prop["seed_mean"]["mean"] - 1.0) / slopes_prop["seed_mean"]["se"]
        slopes_model = per_seed_slopes(delta_v, operating_model, seeds, members, confidence)
        # Floor-share fit: DeltaV * N_e = alpha + beta / N_e, weighted by the seed SE.
        floor: dict[str, Any] = {"status": "fewer than two usable magnitudes"}
        if len(usable) >= 2:
            ne = np.array([flux_by_label[label] for label in usable])
            product = np.array([seed_means[label] * flux_by_label[label] for label in usable])
            product_se = np.array([seed_se[label] * flux_by_label[label] for label in usable])
            floor = weighted_fit(1.0 / ne, product, product_se)
            if floor.get("slope") is not None:
                floor = {"alpha_m2_e": floor["intercept"], "beta_m2_e2": floor["slope"], "beta_over_alpha_e": (floor["slope"] / floor["intercept"] if floor["intercept"] else None), "chi2_per_dof": floor["chi2_per_dof"], "n": floor["n"]}
        # Adjacent-magnitude paired ratio changes of DeltaV / propagated realized variance.
        adjacent = []
        for first, second in zip(members, members[1:]):
            changes = []
            for seed in seeds:
                a, b = propagated.get(first, {}).get(seed), propagated.get(second, {}).get(seed)
                da, db = delta_v.get(first, {}).get(seed), delta_v.get(second, {}).get(seed)
                if a and b and da and db and a > 0 and b > 0:
                    changes.append((db / b) / (da / a) - 1.0)
            adjacent.append({"from": first, "to": second, "paired_relative_change_of_delta_v_over_propagated": t_interval(np.asarray(changes), confidence)})
        across[domain] = {
            "labels": members,
            "usable_for_paired_slopes": paired,
            "usable_for_weighted_fit": usable,
            "excluded_nonpositive_or_unavailable": [label for label in members if label not in paired],
            "excluded_from_weighted_fit_zero_or_unknown_error": [label for label in paired if label not in usable],
            "historical_weighted_fit_log_delta_v_vs_log_ne": historical,
            "per_seed_slopes_log_delta_v_vs_log_ne": slopes_flux,
            "per_seed_slopes_log_delta_v_vs_log_propagated_realized_variance": slopes_prop,
            "per_seed_slopes_log_delta_v_vs_log_operating_model_variance": slopes_model,
            "bootstrap_f06": bootstrap_slope(delta_v, flux_by_label, seeds, paired, bootstrap, bootstrap_seed),
            "floor_share_fit": floor,
            "adjacent_magnitudes": adjacent,
        }
    return {"labels": labels, "seeds": seeds, "per_magnitude": per_magnitude, "domains": domains, "across_magnitudes": across, "confidence": confidence, "units_of_inference": "root seeds; magnitudes paired within a seed"}


# -- Replay comparison --------------------------------------------------------


def _get(row: dict[str, Any], key: tuple[str, ...]) -> Any:
    value: Any = row
    for part in key:
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def replay_comparison(current: dict[str, Any], other_path: Path, *, name: str) -> dict[str, Any]:
    other = json.loads(other_path.read_text())
    rows = {(row.get("label"), row.get("root_seed")): row for row in other.get("runs", [])}
    comparisons = []
    identical_runs = 0
    for row in current.get("runs", []):
        key = (row.get("label"), row.get("root_seed"))
        counterpart = rows.get(key)
        if counterpart is None:
            comparisons.append({"label": key[0], "root_seed": key[1], "status": "absent in the other record"})
            continue
        fields = []
        first_difference = None
        for quantity in SEVEN_RECORDED:
            a, b = _get(row, quantity), _get(counterpart, quantity)
            same = a == b
            field = {"quantity": "/".join(quantity), "current": a, "other": b, "bit_identical": bool(same)}
            if not same and isinstance(a, (int, float)) and isinstance(b, (int, float)) and b not in (0, None):
                field["relative_difference"] = (a - b) / b
            if not same and first_difference is None:
                first_difference = field["quantity"]
            fields.append(field)
        identical = first_difference is None
        identical_runs += int(identical)
        comparisons.append({"label": key[0], "root_seed": key[1], "config_hash_equal": row.get("config_hash") == counterpart.get("config_hash"), "bit_identical": identical, "first_differing_quantity": first_difference, "fields": fields, "frame_level_attribution": "available only between two traced records (per-frame series); the other record carries run scalars only" if not identical else None})
    return {
        "name": name,
        "other_record": str(other_path),
        "other_sha256": hashlib.sha256(other_path.read_bytes()).hexdigest(),
        "other_code_identity": other.get("code_identity"),
        "other_environment": {key: other.get(key) for key in ("python", "numpy", "scipy", "machine")},
        "runs_compared": len([item for item in comparisons if "fields" in item]),
        "runs_bit_identical": identical_runs,
        "all_bit_identical": bool(comparisons) and all(item.get("bit_identical") for item in comparisons if "fields" in item) and all("fields" in item for item in comparisons),
        "runs": comparisons,
    }


# -- Note ---------------------------------------------------------------------


def _fmt(value: Any, scale: float = 1.0, digits: int = 3) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "n/a"
    return f"{value * scale:.{digits}f}"


def write_note(analysis: dict[str, Any], path: Path) -> None:
    pop = analysis["population"]
    lines = [
        "# Traced noise-isolation analysis note",
        "",
        f"Record `{analysis['record']['path']}` (SHA-256 `{analysis['record']['sha256'][:16]}…`), {analysis['record']['runs_analysed']} analysed runs, "
        f"{analysis['record']['runs_refused']} refused. NumPy-only analysis `{ANALYSIS_SCHEMA}`; no verdict is asserted here.",
        "",
        "## Per magnitude (seeds are the units; Student t intervals)",
        "",
        "| label | N_e | ΔV mean ± SE (nm²) | t half-width | median | gate-quiet seeds | excursions | E0 ratio equal-weight | E0 ratio weighted | ΔV/propagated | bias 4/SNR_T² |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for label in pop["labels"]:
        entry = pop["per_magnitude"][label]
        stats = entry["delta_v_m2"]["seed_statistics"]
        e0 = entry["e0"]
        lines.append(
            f"| {label} | {_fmt(entry['detected_e_full_subap'], 1.0, 0)} | {_fmt(stats['mean'], 1e18, 2)} ± {_fmt(stats['se'], 1e18, 2)} | {_fmt(stats.get('half_width'), 1e18, 2)} | "
            f"{_fmt(entry['delta_v_m2']['median'], 1e18, 2)} | {len(entry['delta_v_gate_quiet_m2']['seeds'])}/{len(entry['seeds'])} | {entry['excursions'] or '—'} | "
            f"{_fmt(e0['ratio_variance_over_model_equal_weight']['mean'])} ± {_fmt(e0['ratio_variance_over_model_equal_weight']['se'])} | "
            f"{_fmt(e0['ratio_variance_over_model_propagation_weighted']['mean'])} ± {_fmt(e0['ratio_variance_over_model_propagation_weighted']['se'])} | "
            f"{_fmt(entry['loop_linearity']['delta_v_over_propagated_realized_variance']['mean'])} ± {_fmt(entry['loop_linearity']['delta_v_over_propagated_realized_variance']['se'])} | "
            f"{_fmt(e0['first_order_bias_estimate_4_over_snr_t2'], 1.0, 4)} |"
        )
    lines += ["", "## Across magnitudes", ""]
    for domain, entry in pop["across_magnitudes"].items():
        hist = entry["historical_weighted_fit_log_delta_v_vs_log_ne"]
        seeds_flux = entry["per_seed_slopes_log_delta_v_vs_log_ne"]["seed_mean"]
        seeds_prop = entry["per_seed_slopes_log_delta_v_vs_log_propagated_realized_variance"]["seed_mean"]
        boot = entry["bootstrap_f06"]
        lines.append(f"### Domain `{domain}`: {entry['labels']}")
        lines.append("")
        if hist.get("slope") is not None:
            lines.append(f"- Historical weighted fit of seed means, log ΔV vs log N_e: slope {hist['slope']:.4f} ± {hist['slope_se_unscaled']:.4f} (unscaled), ± {_fmt(hist.get('slope_se_scaled'), 1.0, 4)} (scaled), χ²/dof {_fmt(hist.get('chi2_per_dof'))}, {_fmt(hist.get('se_from_minus_one_unscaled'), 1.0, 2)} unscaled SE from −1.")
        else:
            lines.append(f"- Historical weighted fit: {hist.get('status')}.")
        lines.append(f"- Per-seed paired slopes, log ΔV vs log N_e: mean {_fmt(seeds_flux.get('mean'), 1.0, 4)} ± {_fmt(seeds_flux.get('se'), 1.0, 4)} (t half-width {_fmt(seeds_flux.get('half_width'), 1.0, 4)}, n = {seeds_flux.get('n')}); {_fmt(seeds_flux.get('se_from_minus_one'), 1.0, 2)} SE from −1.")
        lines.append(f"- Per-seed paired slopes, log ΔV vs log Σ w S² (loop linearity): mean {_fmt(seeds_prop.get('mean'), 1.0, 4)} ± {_fmt(seeds_prop.get('se'), 1.0, 4)} (n = {seeds_prop.get('n')}); {_fmt(seeds_prop.get('se_from_plus_one'), 1.0, 2)} SE from +1.")
        lines.append(f"- F-06 bootstrap (descriptive): slope {_fmt(boot.get('point_slope'), 1.0, 4)}, SD {_fmt(boot.get('bootstrap_sd'), 1.0, 4)} over {boot.get('resamples')} resamples.")
        floor = entry["floor_share_fit"]
        if floor.get("alpha_m2_e") is not None:
            lines.append(f"- Floor-share fit ΔV·N_e = α + β/N_e: β/α = {_fmt(floor.get('beta_over_alpha_e'), 1.0, 1)} e⁻ (χ²/dof {_fmt(floor.get('chi2_per_dof'))}).")
        for pair in entry["adjacent_magnitudes"]:
            change = pair["paired_relative_change_of_delta_v_over_propagated"]
            lines.append(f"- {pair['from']} → {pair['to']}: paired change of ΔV/Σ w S² {_fmt(change.get('mean'), 100.0, 2)} % ± {_fmt(change.get('se'), 100.0, 2)} % (n = {change.get('n')}).")
        if entry["excluded_nonpositive_or_unavailable"]:
            lines.append(f"- Excluded from every log fit (non-positive or unavailable): {entry['excluded_nonpositive_or_unavailable']}.")
        if entry["excluded_from_weighted_fit_zero_or_unknown_error"]:
            lines.append(f"- Kept for the paired slopes but excluded from the weighted fit (zero or unknown across-seed error): {entry['excluded_from_weighted_fit_zero_or_unknown_error']}.")
        lines.append("")
    lines += ["## Within-run errors, correlation times and excursions", "", "| run | frames | SE(25) nm² | plateau | τ_int | τ status | excursion | mask disagreement | cross term mean/SE |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for run in analysis["runs"]:
        plateau = run["delta_v"]["blocks"]["plateau"]
        tau = run["delta_v"]["autocorrelation"]
        se25 = next((block["se"] for block in run["delta_v"]["blocks"]["blocks"] if block["block_frames"] == 25), None)
        lines.append(f"| {run['label']}/{run['root_seed']} | {run['analysed_frames']} | {_fmt(se25, 1e18, 2)} | {'L=' + str(plateau.get('block_frames')) + ' SE=' + _fmt(plateau.get('se'), 1e18, 2) if plateau['identified'] else 'not identified (lower bound ' + _fmt(plateau.get('se'), 1e18, 2) + ')'} | {_fmt(tau.get('tau'), 1.0, 1)} | {tau['status']} | {'yes ' + str(run['delta_v']['excursion'].get('flagged_blocks')) if run['delta_v']['excursion'].get('flagged') else 'no'} | {_fmt(run['masks']['disagreement_row_frame_fraction'], 1.0, 5)} | {_fmt(run['cross_term']['mean_over_se'], 1.0, 2)} |")
    lines.append("")
    for comparison in analysis.get("replay", []):
        lines += [f"## Replay comparison: {comparison['name']}", "", f"Other record `{comparison['other_record']}` (SHA-256 `{comparison['other_sha256'][:16]}…`): {comparison['runs_bit_identical']} of {comparison['runs_compared']} compared runs bit-identical in the seven recorded quantities."]
        differing = [run for run in comparison["runs"] if "fields" in run and not run["bit_identical"]]
        for run in differing[:40]:
            field = next(item for item in run["fields"] if not item["bit_identical"])
            lines.append(f"- {run['label']}/{run['root_seed']}: first differing quantity `{run['first_differing_quantity']}` ({field['current']!r} vs {field['other']!r}, relative {_fmt(field.get('relative_difference'), 1.0, 6)}).")
        lines.append("")
    lines += ["## Limitations stated by this analysis", ""]
    lines += [f"- {item}" for item in analysis["limitations"]]
    path.write_text("\n".join(lines) + "\n")


# -- Main ---------------------------------------------------------------------


def analyse(record_path: Path, *, output_dir: Path, historical: Path | None, untraced: Path | None, gate_quiet_labels: list[str] | None, lengths: tuple[int, ...], bootstrap: int, bootstrap_seed: int, confidence: float) -> dict[str, Any]:
    record, entries = load_traced_record(record_path)
    runs = [analyse_run(entry, lengths) for entry in entries if not entry["refused"]]
    pop = population(runs, confidence=confidence, gate_quiet_labels=gate_quiet_labels, bootstrap=bootstrap, bootstrap_seed=bootstrap_seed)
    limitations = [
        "Block standard errors from fewer than about ten blocks carry a relative uncertainty of 1/sqrt(2(k-1)) or more; plateau identification at 150 analysed frames is indicative, not a guarantee of a 5 % error.",
        "The integrated autocorrelation time is reported as unreliable whenever the series is shorter than 50 tau or the automatic window does not close; such runs give lower bounds only.",
        "E0 uses the expected-frame centroid as the first-order mean of the noisy centroid; the reported second moment and centred variance differ by the squared mean residual, and the model's first-order bias (about 4/SNR_T^2) is reported, not corrected.",
        "The propagation weights are the fixed reconstructor's pupil response per row (linear, every row valid); they are one justified weighting, reported beside equal weights, not the only one.",
        "Bootstrap resamples are descriptive; seeds remain the only independent units.",
        "Nothing here closes AR-006 or LIM-18, retunes the noise model or treats the proposed first-order bias band as an established acceptance criterion.",
    ]
    short = [f"{run['label']}/{run['root_seed']}" for run in runs if not run["delta_v"]["blocks"]["plateau"]["identified"]]
    if short:
        limitations.append(f"No blocking plateau identified for {len(short)} of {len(runs)} runs ({', '.join(short[:12])}{'…' if len(short) > 12 else ''}): their within-run errors are lower bounds.")
    analysis: dict[str, Any] = {
        "schema": ANALYSIS_SCHEMA,
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "numpy": np.__version__,
        "record": {"path": str(record_path), "sha256": hashlib.sha256(record_path.read_bytes()).hexdigest(), "command": record.get("command"), "code_identity": record.get("code_identity"), "runs_analysed": len(runs), "runs_refused": len([entry for entry in entries if entry["refused"]]), "sidecars": {run["sidecar"]: next(row["row"]["sidecar"]["sha256"] for row in entries if not row["refused"] and row["file"] == run["sidecar"]) for run in runs}},
        "settings": {"block_lengths": list(lengths), "excursion_block": EXCURSION_BLOCK, "excursion_factor": EXCURSION_FACTOR, "gate_quiet_disagreement": GATE_QUIET_DISAGREEMENT, "plateau_min_blocks": PLATEAU_MIN_BLOCKS, "plateau_tolerance": PLATEAU_TOLERANCE, "sokal_c": SOKAL_C, "confidence": confidence, "bootstrap_resamples": bootstrap, "bootstrap_seed": bootstrap_seed, "gate_quiet_labels_predeclared": gate_quiet_labels},
        "runs": runs,
        "population": pop,
        "replay": [],
        "limitations": limitations,
    }
    if untraced is not None:
        analysis["replay"].append(replay_comparison(record, untraced, name="traced versus untraced (current code)"))
    if historical is not None:
        analysis["replay"].append(replay_comparison(record, historical, name="traced versus historical record"))
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "analysis.json").write_text(json.dumps(analysis, indent=1, default=float) + "\n")
    write_note(analysis, output_dir / "ANALYSIS_NOTE.md")
    return analysis


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("record", type=Path, help="a traced noise-isolation record (its sidecars beside it)")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--historical", type=Path, help="a historical (untraced) record to compare the seven recorded quantities with")
    parser.add_argument("--untraced", type=Path, help="a current untraced record of the same runs")
    parser.add_argument("--gate-quiet-labels", help="comma-separated predeclared gate-quiet labels, e.g. m5,m6,m7")
    parser.add_argument("--block-lengths", default=",".join(str(length) for length in DEFAULT_BLOCK_LENGTHS))
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--bootstrap-seed", type=int, default=20261020)
    parser.add_argument("--confidence", type=float, default=0.95)
    arguments = parser.parse_args(argv)
    lengths = tuple(int(item) for item in arguments.block_lengths.split(","))
    labels = [item.strip() for item in arguments.gate_quiet_labels.split(",")] if arguments.gate_quiet_labels else None
    analysis = analyse(arguments.record, output_dir=arguments.output_dir, historical=arguments.historical, untraced=arguments.untraced, gate_quiet_labels=labels, lengths=lengths, bootstrap=arguments.bootstrap, bootstrap_seed=arguments.bootstrap_seed, confidence=arguments.confidence)
    print(f"analysed {analysis['record']['runs_analysed']} runs; wrote {arguments.output_dir / 'analysis.json'} and ANALYSIS_NOTE.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
