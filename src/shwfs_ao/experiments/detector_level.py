"""Detector-level evidence experiments (DET-07/DET-09).

* :func:`max_pole_modulus` - discrete-time stability of the delayed leaky
  integrator, the check applied before any gain is scanned;
* :func:`gain_scan` - the predeclared controller-gain selection (B11);
* :func:`derive_physical_config` - the same detector physics on another
  geometry (the scan tier of the 12 m and 42 m profiles);
* :func:`seed_ensemble` - noise-on closed loops over independent root seeds
  (atmosphere, detector temporal noise, persistent maps and calibration
  products all redrawn).

The Monte-Carlo noise harness (E1) and the open-loop propagation test (E2)
live in :mod:`shwfs_ao.experiments.detector_noise`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
import math
import time
from typing import Any

import numpy as np

from ..core.provenance import Provenance
from ..io.configs import ProfileProvenance, RandomSeedConfig, SystemConfig
from .scao import ScaoExecutionOptions, build_scao_system, run_closed_loop


__all__ = (
    "STABILITY_POLE_LIMIT",
    "GAIN_TIE_TOLERANCE",
    "max_pole_modulus",
    "with_controller_gain",
    "derive_physical_config",
    "loop_summary",
    "gain_scan",
    "seed_ensemble",
    "reconstructor_matrix",
    "open_loop_noise_propagation",
    "interaction_prediction_check",
    "with_physics",
    "with_magnitude",
    "science_run",
    "summarize_runs",
)


STABILITY_POLE_LIMIT = 0.98
GAIN_TIE_TOLERANCE = 0.02
MIN_VALID_FRACTION = 0.9


def max_pole_modulus(gain: float, leak: float, latency_frames: int) -> float:
    """Largest root modulus of ``z**(L+1) - (1 - leak) z**L + gain``."""

    coefficients = np.zeros(int(latency_frames) + 2)
    coefficients[0] = 1.0
    coefficients[1] = -(1.0 - float(leak))
    coefficients[-1] += float(gain)
    return float(np.max(np.abs(np.roots(coefficients))))


def with_controller_gain(config: SystemConfig, gain: float, *, n_steps: int | None = None) -> SystemConfig:
    controller = replace(config.controller, gain=float(gain))
    if n_steps is not None:
        controller = replace(controller, n_steps=int(n_steps))
    return replace(config, controller=controller)


def derive_physical_config(
    base: SystemConfig,
    physics_source: SystemConfig,
    *,
    label: str,
) -> SystemConfig:
    """``base``'s geometry, atmosphere and loop with ``physics_source``'s detector.

    The WFS window, sampling, detector block and ``detector_physics`` block
    come from ``physics_source``; everything else from ``base``.  The result
    is a schema-7 configuration built in code, never a published profile.
    """

    if physics_source.detector_physics is None:
        raise ValueError("physics_source has no detector_physics block.")
    wfs = replace(
        base.wfs,
        pad_factor=physics_source.wfs.pad_factor,
        detector_window_px=physics_source.wfs.detector_window_px,
        clip_negative_pixels=physics_source.wfs.clip_negative_pixels,
    )
    controller = replace(base.controller, include_noise=physics_source.controller.include_noise)
    return replace(
        base,
        detector=replace(physics_source.detector, exposure_s=physics_source.detector.exposure_s),
        wfs=wfs,
        controller=controller,
        reconstructor=replace(
            base.reconstructor,
            min_valid_fraction=min(
                base.reconstructor.min_valid_fraction,
                physics_source.reconstructor.min_valid_fraction,
            ),
        ),
        profile=ProfileProvenance(
            profile_name=label,
            profile_version=1,
            baseline_rationale=(
                f"In-code scan configuration: {base.profile.profile_name}@"
                f"{base.profile.profile_version} with the detector physics of "
                f"{physics_source.profile.profile_name}@{physics_source.profile.profile_version}."
            ),
            provenance=Provenance(
                source_class=physics_source.profile.provenance.source_class,
                source_note=physics_source.profile.provenance.source_note,
                source_id=f"shwfs_ao.system_profile.{label}.v1",
                references=physics_source.profile.provenance.references,
            ),
        ),
        record_schema_version=7,
        detector_physics=physics_source.detector_physics,
    )


def loop_summary(history: Any, *, second_half: bool = True) -> dict[str, float]:
    """Scalar metrics of one loop history over its second half."""

    post = np.asarray(history.post_update_residual_opd_rms_m, dtype=float)
    open_loop = np.asarray(history.open_loop_opd_rms_m, dtype=float)
    valid = np.asarray(history.valid_measurement_fraction, dtype=float)
    start = len(post) // 2 if second_half else 0
    return {
        "post_update_rms_m": float(np.mean(post[start:])),
        "open_loop_rms_m": float(np.mean(open_loop[start:])),
        "final_post_update_rms_m": float(post[-1]),
        "final_open_loop_rms_m": float(open_loop[-1]),
        "valid_measurement_fraction": float(np.mean(valid[start:])),
        "n_frames": int(len(post)),
    }


def gain_scan(
    config: SystemConfig,
    gains: Sequence[float],
    *,
    realizations: Sequence[int] = (0, 1, 2),
    n_steps: int | None = None,
    execution: ScaoExecutionOptions | None = None,
) -> dict[str, Any]:
    """Run the predeclared gain scan and apply its fixed selection rule."""

    leak = config.controller.leak
    latency = config.controller.latency_frames
    rows = []
    for gain in gains:
        pole = max_pole_modulus(gain, leak, latency)
        row: dict[str, Any] = {"gain": float(gain), "max_pole_modulus": pole}
        if pole > STABILITY_POLE_LIMIT:
            row["status"] = "rejected_unstable"
            rows.append(row)
            continue
        scan_config = with_controller_gain(config, gain, n_steps=n_steps)
        started = time.perf_counter()
        system = build_scao_system(scan_config, execution=execution)
        runs = []
        for realization in realizations:
            history = run_closed_loop(scan_config, system=system, realization_index=int(realization))
            runs.append(loop_summary(history))
        row["runs"] = runs
        row["wall_s"] = time.perf_counter() - started
        row["criterion_post_update_rms_m"] = float(np.mean([r["post_update_rms_m"] for r in runs]))
        row["mean_valid_fraction"] = float(np.mean([r["valid_measurement_fraction"] for r in runs]))
        row["lost_lock"] = any(r["final_post_update_rms_m"] > r["final_open_loop_rms_m"] for r in runs)
        row["status"] = (
            "qualified"
            if row["mean_valid_fraction"] >= MIN_VALID_FRACTION and not row["lost_lock"]
            else "disqualified"
        )
        rows.append(row)
    qualified = [row for row in rows if row["status"] == "qualified"]
    selected = None
    if qualified:
        best = min(row["criterion_post_update_rms_m"] for row in qualified)
        tied = [
            row
            for row in qualified
            if row["criterion_post_update_rms_m"] <= best * (1.0 + GAIN_TIE_TOLERANCE)
        ]
        selected = min(row["gain"] for row in tied)
    return {
        "profile": f"{config.profile.profile_name}@{config.profile.profile_version}",
        "config_hash": config.config_hash,
        "gains": [float(g) for g in gains],
        "realizations": [int(r) for r in realizations],
        "n_steps": config.controller.n_steps if n_steps is None else int(n_steps),
        "rule": (
            "lowest second-half mean post-update residual RMS over the realizations; "
            f"mean valid fraction >= {MIN_VALID_FRACTION}; no final residual above open "
            f"loop; ties within {GAIN_TIE_TOLERANCE:.0%} -> lower gain; max |pole| <= "
            f"{STABILITY_POLE_LIMIT}"
        ),
        "rows": rows,
        "selected_gain": selected,
    }


def seed_ensemble(
    config: SystemConfig,
    root_seeds: Sequence[int],
    *,
    execution: ScaoExecutionOptions | None = None,
) -> dict[str, Any]:
    """Noise-on loops over independent root seeds; mean and seed scatter."""

    runs = []
    for seed in root_seeds:
        seeded = replace(config, random=RandomSeedConfig(root_seed=int(seed)))
        system = build_scao_system(seeded, execution=execution)
        history = run_closed_loop(seeded, system=system)
        summary = loop_summary(history)
        summary["root_seed"] = int(seed)
        runs.append(summary)
    values = np.array([run["post_update_rms_m"] for run in runs])
    valid = np.array([run["valid_measurement_fraction"] for run in runs])
    return {
        "profile": f"{config.profile.profile_name}@{config.profile.profile_version}",
        "root_seeds": [int(s) for s in root_seeds],
        "runs": runs,
        "post_update_rms_mean_m": float(values.mean()),
        "post_update_rms_seed_std_m": float(values.std(ddof=1)) if len(values) > 1 else 0.0,
        "valid_fraction_mean": float(valid.mean()),
    }


def reconstructor_matrix(reconstructor: Any, row_ids: tuple[str, ...]) -> np.ndarray:
    """The linear map of a reconstructor with every row valid (fixed mask)."""

    from ..core.types import MeasurementVector

    columns = []
    for index in range(len(row_ids)):
        values = np.zeros(len(row_ids))
        values[index] = 1.0
        estimate = reconstructor.reconstruct(
            MeasurementVector(values=values, valid_rows=np.ones(len(row_ids), dtype=bool), row_ids=row_ids, measurement_unit="pixel")
        )
        if estimate is None:
            raise ValueError("the reconstructor refused a fully valid measurement.")
        columns.append(np.asarray(estimate.delta_coordinates_opd_m, dtype=float))
    return np.stack(columns, axis=1)


def open_loop_noise_propagation(
    config: SystemConfig,
    *,
    trials: int,
    residual_scale: float = 0.2,
    execution: ScaoExecutionOptions | None = None,
) -> dict[str, Any]:
    """E2: slope- and reconstruction-noise covariance with everything fixed.

    A static residual (``residual_scale`` times the atmosphere at t = 0, the
    DM flat, loop open), fixed calibration products and a fixed reconstructor
    matrix ``R``.  The slope covariance measured over ``trials`` noisy frames
    is compared with the independent ``detector_covariance_v1`` prediction
    ``Sigma_s,pred`` (independent lenslets: block diagonal), and the measured
    noise-only reconstruction covariance with ``R Sigma_s,pred R^T``.  Trials
    whose row mask is not fully valid are counted and excluded, so R stays
    fixed; the count is reported.
    """

    system = build_scao_system(config, execution=execution)
    wfs: Any = system.wfs
    if not hasattr(wfs, "noise_model"):
        raise ValueError("E2 needs the physical sensor (a detector_physics profile).")
    opd = np.asarray(system.atmosphere.opd_at(0.0), dtype=float)
    residual = residual_scale * np.where(np.isfinite(opd), opd, 0.0)
    quality = wfs.noise_model(residual)
    n_lenslets = len(wfs.subaperture_ids)
    predicted = np.zeros((2 * n_lenslets, 2 * n_lenslets))
    for index in range(n_lenslets):
        predicted[2 * index : 2 * index + 2, 2 * index : 2 * index + 2] = quality.centroid_covariance_xy_px2[index]
    matrix = reconstructor_matrix(system.reconstructor, wfs.row_ids)
    slopes = []
    excluded = 0
    started = time.perf_counter()
    for _ in range(int(trials)):
        measurement = wfs.measure(residual, random_streams=system.random_streams, include_noise=True)
        if not np.all(measurement.vector.valid_rows):
            excluded += 1
            continue
        slopes.append(np.asarray(measurement.vector.values, dtype=float))
    elapsed = time.perf_counter() - started
    data = np.asarray(slopes)
    measured = np.cov(data, rowvar=False)
    commands = data @ matrix.T
    measured_commands = np.cov(commands, rowvar=False)
    predicted_commands = matrix @ predicted @ matrix.T
    integration_check = matrix @ measured @ matrix.T
    count = data.shape[0]
    diag_ratio = np.diag(measured) / np.diag(predicted)
    off = measured - np.diag(np.diag(measured))
    within = np.zeros_like(off, dtype=bool)
    for index in range(n_lenslets):
        within[2 * index : 2 * index + 2, 2 * index : 2 * index + 2] = True
    off_between = off[~within]
    se_off = np.sqrt(np.outer(np.diag(predicted), np.diag(predicted)) / count)[~within]
    command_ratio = np.diag(measured_commands) / np.diag(predicted_commands)
    return {
        "profile": f"{config.profile.profile_name}@{config.profile.profile_version}",
        "config_hash": config.config_hash,
        "trials": int(trials),
        "used_trials": int(count),
        "excluded_trials_with_invalid_rows": int(excluded),
        "residual_rms_m": float(np.sqrt(np.mean(residual[np.asarray(wfs.geometry.pupil_mask)] ** 2))),
        "wall_s": elapsed,
        "slope_variance_ratio_measured_over_predicted": {
            "mean": float(np.mean(diag_ratio)),
            "min": float(np.min(diag_ratio)),
            "max": float(np.max(diag_ratio)),
            "expected_relative_se_per_entry": float(math.sqrt(2.0 / (count - 1))),
        },
        "between_lenslet_covariance_max_abs_over_se": float(np.max(np.abs(off_between) / se_off)) if off_between.size else 0.0,
        "within_lenslet_xy_correlation_measured": [
            float(measured[2 * i, 2 * i + 1] / math.sqrt(measured[2 * i, 2 * i] * measured[2 * i + 1, 2 * i + 1]))
            for i in range(n_lenslets)
        ],
        "command_variance_ratio_measured_over_predicted": {
            "mean": float(np.mean(command_ratio)),
            "min": float(np.min(command_ratio)),
            "max": float(np.max(command_ratio)),
        },
        "command_trace_ratio": float(np.trace(measured_commands) / np.trace(predicted_commands)),
        "integration_check_max_relative_difference": float(
            np.max(np.abs(integration_check - measured_commands)) / np.max(np.abs(measured_commands))
        ),
        "uncertainty_supported_fraction": float(np.mean(quality.supported)),
    }


def interaction_prediction_check(
    config: SystemConfig,
    *,
    command_rms_m: float = 5.0e-9,
    tilt_rad: float = 2.0e-7,
    seed: int = 3,
    execution: ScaoExecutionOptions | None = None,
) -> dict[str, Any]:
    """DET-03: does the matching interaction calibration predict the response?

    A random DM command ``c`` (rms ``command_rms_m``) is applied with the loop
    open and the noiseless (reference-path) slopes are compared with ``D c``
    from the interaction matrix calibrated on the same sensor.  The tilt gain
    (centroid pixels per radian of wavefront tilt, mean over lenslets) is
    reported so point-sampled and pixel-integrated sensors can be compared.
    """

    from ..core.types import DmCommandVector

    system = build_scao_system(config, execution=execution)
    matrix = np.asarray(system.interaction_matrix.matrix, dtype=float)
    rng = np.random.default_rng(seed)
    coordinates = system.interaction_matrix.coordinate_ids
    command = rng.normal(0.0, command_rms_m, len(coordinates))
    full = np.zeros(system.dm.n_actuators)
    index = {identifier: i for i, identifier in enumerate(system.dm.actuator_ids)}
    for identifier, value in zip(coordinates, command):
        full[index[identifier]] = value
    synthesis = system.dm.opd_from_commands(
        DmCommandVector(full, system.dm.actuator_ids, "m_opd_equivalent")
    )
    opd = np.nan_to_num(np.asarray(synthesis.correction_opd_m, dtype=float))
    measured = system.wfs.measure(opd, random_streams=system.random_streams, include_noise=False)
    valid = np.asarray(measured.vector.valid_rows) & np.asarray(system.interaction_matrix.row_valid)
    predicted = matrix @ command
    observed = np.asarray(measured.vector.values, dtype=float)
    error = float(
        np.linalg.norm(observed[valid] - predicted[valid]) / np.linalg.norm(observed[valid])
    )
    sensor: Any = system.wfs
    geometry = sensor.geometry
    tilt = np.where(np.asarray(geometry.pupil_mask), tilt_rad * np.asarray(geometry.x_m), 0.0)
    shifted = sensor.measure(tilt, random_streams=system.random_streams, include_noise=False)
    gain = float(np.nanmean(np.asarray(shifted.vector.values, dtype=float)[0::2])) / tilt_rad
    return {
        "profile": f"{config.profile.profile_name}@{config.profile.profile_version}",
        "relative_prediction_error": error,
        "valid_rows": int(np.count_nonzero(valid)),
        "command_rms_m": float(command_rms_m),
        "tilt_gain_px_per_rad": gain,
    }


def with_physics(config: SystemConfig, **changes: Any) -> SystemConfig:
    """``config`` with fields of its ``detector_physics`` block replaced."""

    physics = config.detector_physics
    if physics is None:
        raise ValueError("the configuration has no detector_physics block.")
    return replace(config, detector_physics=replace(physics, **changes))


def with_magnitude(config: SystemConfig, magnitude: float) -> SystemConfig:
    physics = config.detector_physics
    if physics is None:
        raise ValueError("the configuration has no detector_physics block.")
    return with_physics(config, source=replace(physics.source, ab_magnitude=float(magnitude)))


def science_run(
    config: SystemConfig,
    *,
    root_seed: int | None = None,
    n_steps: int | None = None,
    burn_in_frames: int,
    execution: ScaoExecutionOptions | None = None,
    realization_index: int = 0,
) -> dict[str, Any]:
    """One noise-on closed loop with streamed long-exposure science images.

    Metrics use the frames from ``burn_in_frames`` on: mean post-update
    residual RMS, mean valid-measurement fraction, the fraction of frames whose
    reconstruction was usable, and the long-exposure peak and on-axis Strehl
    ratio of every science wavelength.
    """

    import resource
    import sys

    from ..science.long_exposure import LongExposureConfig, StreamingLongExposure

    run_config = config
    if root_seed is not None:
        run_config = replace(run_config, random=RandomSeedConfig(root_seed=int(root_seed)))
    if n_steps is not None:
        run_config = replace(run_config, controller=replace(run_config.controller, n_steps=int(n_steps)))
    started = time.perf_counter()
    system = build_scao_system(run_config, execution=execution)
    build_s = time.perf_counter() - started
    accumulator = StreamingLongExposure(
        system.science_propagator,
        LongExposureConfig(
            wavelengths_m=tuple(run_config.science_wavelengths_m),
            burn_in_frames=int(burn_in_frames),
        ),
        telescope_diameter_m=run_config.telescope_diameter_m,
    )
    started = time.perf_counter()
    history = run_closed_loop(
        run_config,
        system=system,
        realization_index=realization_index,
        observers=(accumulator,),
    )
    loop_s = time.perf_counter() - started
    science = accumulator.result()
    window = slice(int(burn_in_frames), None)
    post = np.asarray(history.post_update_residual_opd_rms_m, dtype=float)[window]
    open_loop = np.asarray(history.open_loop_opd_rms_m, dtype=float)[window]
    valid = np.asarray(history.valid_measurement_fraction, dtype=float)[window]
    usable = np.asarray(history.reconstruction_usable, dtype=bool)[window]
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_bytes = int(peak if sys.platform == "darwin" else peak * 1024)
    result: dict[str, Any] = {
        "config_hash": run_config.config_hash,
        "root_seed": int(run_config.random.root_seed),
        "n_steps": int(run_config.controller.n_steps),
        "burn_in_frames": int(burn_in_frames),
        "build_s": build_s,
        "loop_s": loop_s,
        "per_frame_s": loop_s / run_config.controller.n_steps,
        "process_peak_rss_bytes": peak_bytes,
        "post_update_rms_m": float(np.mean(post)),
        "open_loop_rms_m": float(np.mean(open_loop)),
        "final_post_update_rms_m": float(post[-1]),
        "valid_measurement_fraction": float(np.mean(valid)),
        "min_valid_measurement_fraction": float(np.min(valid)),
        "reconstruction_usable_fraction": float(np.mean(usable)),
        "lost_lock": bool(post[-1] > open_loop[-1]),
        "science": [
            {
                "wavelength_m": image.metrics.wavelength_m,
                "peak_strehl": image.metrics.peak_strehl,
                "on_axis_strehl": image.metrics.on_axis_strehl,
                "fwhm_lambda_over_d": image.metrics.fwhm_lambda_over_d,
            }
            for image in science.images
        ],
    }
    # Only a run with a controller.recovery policy reports what it did.
    recovery = history.metadata.get("recovery")
    if recovery is not None:
        result["recovery"] = dict(recovery)
    return result


def summarize_runs(runs: Sequence[dict[str, Any]]) -> dict[str, float]:
    """Mean and seed scatter (sample std) of the run metrics."""

    def stats(values: list[float]) -> tuple[float, float]:
        array = np.asarray(values, dtype=float)
        return float(array.mean()), float(array.std(ddof=1)) if array.size > 1 else 0.0

    rms_mean, rms_std = stats([run["post_update_rms_m"] for run in runs])
    valid_mean, valid_std = stats([run["valid_measurement_fraction"] for run in runs])
    strehl_mean, strehl_std = stats([run["science"][0]["peak_strehl"] for run in runs])
    return {
        "runs": len(runs),
        "post_update_rms_mean_m": rms_mean,
        "post_update_rms_seed_std_m": rms_std,
        "valid_fraction_mean": valid_mean,
        "valid_fraction_seed_std": valid_std,
        "peak_strehl_mean": strehl_mean,
        "peak_strehl_seed_std": strehl_std,
        "lost_lock_runs": int(sum(run["lost_lock"] for run in runs)),
    }
