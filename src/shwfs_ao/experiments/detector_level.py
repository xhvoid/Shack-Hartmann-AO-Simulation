"""Detector-level evidence experiments (DET-07/DET-09).

* :func:`max_pole_modulus` - discrete-time stability of the delayed leaky
  integrator, the check applied before any gain is scanned;
* :func:`gain_scan` - the predeclared controller-gain selection (B11);
* :func:`derive_physical_config` - the same detector physics on another
  geometry (the scan tier of the 12 m and 42 m profiles);
* :func:`seed_ensemble` - noise-on closed loops over independent root seeds
  (atmosphere, detector temporal noise, persistent maps and calibration
  products all redrawn);
* :func:`with_matched_photometry` - change the spectral sampling while holding
  the detected source and sky electrons fixed (E6);
* :func:`paired_noise_run` - the isolated temporal detector-noise
  contribution to the residual, from a noise-on loop and its noiseless
  operating twin;
* :func:`paired_noise_run_traced` - the same two arms, bit for bit, observed
  per frame (S4 contract, ticket T1): per-frame ``DeltaV_t``, the difference
  of mean squares and their cross term, both arms' effective row masks and
  loop telemetry, the sensor's per-lenslet telemetry of every frame and the
  operating-state centroid residuals (E0), returned as arrays for a sidecar;
* :func:`paired_noise_run_mask_locked` - the separately identified arm-B
  protocol: the operating twin runs first and the noisy arm replays the
  twin's effective rows frame by frame through :class:`_MaskLockedSensor`.

The Monte-Carlo noise harness (E1) and the open-loop propagation test (E2)
live in :mod:`shwfs_ao.experiments.detector_noise`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
import hashlib
import math
import time
from typing import Any

import numpy as np

from ..core.hashing import component_config_hash
from ..core.provenance import Provenance
from ..core.types import DmCommandVector, MeasurementVector, WfsMeasurement
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
    "with_matched_photometry",
    "science_run",
    "paired_noise_run",
    "paired_noise_run_traced",
    "paired_noise_run_mask_locked",
    "MaskLockError",
    "TRACE_SCHEMA",
    "MASK_LOCK_SCHEMA",
    "PAIRED_NOISE_ARMS",
    "MASK_LOCKED_NOISE_ARMS",
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
    is compared with the independent ``detector_covariance_v2`` prediction
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


def with_matched_photometry(config: SystemConfig, reference: SystemConfig) -> SystemConfig:
    """``config`` with source and sky shifted to ``reference``'s detected electrons.

    The AB source magnitude and sky surface brightness move by
    ``2.5 log10(N_config / N_reference)``, each from its own ratio, so the
    detected source electrons per full subaperture and the sky electrons per
    pixel equal those of ``reference`` while the bandpass and its optical
    quadrature stay ``config``'s.  This separates a chromatic-optics effect
    from the electron-budget change a different band brings (review R5).
    """

    from ..detector.physical_config import physical_budget
    from .scao import physical_detector_config

    def budget(item: SystemConfig) -> Any:
        return physical_budget(
            physical_detector_config(item),
            wfs_wavelength_m=item.wfs_wavelength_m,
            full_subaperture_area_m2=1.0,
            pixel_solid_angle_sr=1.0e-12,
        )

    physics = config.detector_physics
    if physics is None:
        raise ValueError("the configuration has no detector_physics block.")
    source = physics.source
    if source.kind != "ab_flat_fnu":
        raise ValueError("photometry matching needs an ab_flat_fnu source.")
    current, target = budget(config), budget(reference)
    changes: dict[str, float] = {
        "ab_magnitude": float(source.ab_magnitude)
        + 2.5 * math.log10(current.detected_e_full_subap / target.detected_e_full_subap)
    }
    if source.sky_ab_mag_per_arcsec2 is not None:
        changes["sky_ab_mag_per_arcsec2"] = float(source.sky_ab_mag_per_arcsec2) + 2.5 * math.log10(
            current.sky_e_per_pixel_full_subap / target.sky_e_per_pixel_full_subap
        )
    return with_physics(config, source=replace(source, **changes))


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
        "post_update_mean_square_m2": float(np.mean(post**2)),
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


class _OperatingExpectationSensor:
    """A physical sensor whose every loop measurement is noiseless.

    Each measurement is the sensor's ``measure_operating_expectation``: the
    guide star and sky at the operating budget, through the operating
    products, with every detector draw replaced by its mean.  Every other
    attribute (identities, row layout, geometry) is the sensor's own.
    """

    def __init__(self, sensor: Any) -> None:
        self._sensor = sensor
        self._config_hash = component_config_hash(
            "physical_shack_hartmann_operating_expectation",
            {"sensor_config_hash": sensor.config_hash},
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._sensor, name)

    # The loop checks its protocol members statically, so declare them.
    @property
    def config_hash(self) -> str:
        return self._config_hash

    @property
    def row_ids(self) -> tuple[str, ...]:
        return tuple(self._sensor.row_ids)

    def measure(self, residual_opd_m: np.ndarray, *, random_streams: Any, include_noise: bool) -> Any:
        return self._sensor.measure_operating_expectation((residual_opd_m,), random_streams=random_streams)

    def measure_exposure(
        self, residual_opd_samples: Sequence[np.ndarray], *, random_streams: Any, include_noise: bool
    ) -> Any:
        return self._sensor.measure_operating_expectation(residual_opd_samples, random_streams=random_streams)


PAIRED_NOISE_ARMS = ("noise_on", "operating_expectation")
# Arm B of the S4 contract runs the operating twin first because it supplies
# the row schedule the noisy arm replays: a separate protocol with its own
# identity, never the legacy order above.
MASK_LOCKED_NOISE_ARMS = ("operating_expectation", "noise_on_mask_locked")
TRACE_SCHEMA = "shwfs_ao.experiments.detector_level.noise_isolation_trace.v1"
MASK_LOCK_SCHEMA = "shwfs_ao.experiments.detector_level.mask_locked_replay.v1"
# The Shack-Hartmann measurement vector holds x then y for every lenslet.
_ROWS_PER_LENSLET = 2
# Per-lenslet sensor telemetry the trace keeps for every frame (float64 and
# boolean fields of DetectorTelemetry); a field the sensor leaves None is
# recorded as unavailable, never filled with zeros.
_TRACE_FLOAT_FIELDS = (
    "centroids_xy_px",
    "expected_centroids_xy_px",
    "centroid_sigma_xy_px",
    "fluxes_e",
    "peak_snr",
    "total_snr",
    "centroid_sigma_px",
    "clipping_fraction",
    "centroid_calibration_sigma_px",
    "masked_pixel_fraction",
    "saturated_pixel_count",
)
_TRACE_BOOL_FIELDS = (
    "valid_subapertures",
    "valid_by_flux",
    "valid_by_snr",
    "valid_by_uncertainty",
    "valid_by_clipping",
    "uncertainty_supported",
)
_TRACE_HISTORY_FIELDS = (
    "valid_measurement_fraction",
    "valid_subaperture_fraction",
    "saturation_fraction",
    "reconstruction_usable",
    "open_loop_opd_rms_m",
    "pre_update_residual_opd_rms_m",
    "post_update_residual_opd_rms_m",
)
# The amplitude of the single-row probe behind the propagation weights: small
# enough to keep the DM off its stroke limit, and divided out again (the
# reconstructor and the DM are linear).
_PROPAGATION_PROBE_PX = 1.0e-3


class _PupilResidualRecorder:
    """Keeps each post-update residual map's pupil samples from a start frame."""

    requested_fields = frozenset({"post_update_residual_opd_m"})

    def __init__(self, start_frame: int) -> None:
        self._start = int(start_frame)
        self.mask: np.ndarray | None = None
        self.samples: list[np.ndarray] = []

    def observe(self, observation: Any) -> None:
        if observation.frame_index < self._start:
            return
        opd = np.asarray(observation.post_update_residual_opd_m, dtype=float)
        if self.mask is None:
            self.mask = np.isfinite(opd)
        self.samples.append(opd[self.mask].astype(np.float32))


class _TelemetryTraceRecorder:
    """Keeps every frame's effective row mask and per-lenslet sensor telemetry.

    A passive observer of the two S4 fields (``measurement_row_mask`` and
    ``detector_telemetry``); it copies nothing else and reaches no component.
    Fields the sensor never provides are recorded as unavailable rather than
    filled with zeros; a field that appears or disappears between frames, or
    a layout that changes, is an error.
    """

    requested_fields = frozenset({"measurement_row_mask", "detector_telemetry"})

    def __init__(self, n_steps: int) -> None:
        self._n_steps = int(n_steps)
        self.row_masks: np.ndarray | None = None
        self.frames_seen = 0
        self.telemetry_frames = 0
        self.subaperture_ids: tuple[str, ...] | None = None
        self.arrays: dict[str, np.ndarray] = {}
        self.unavailable: set[str] = set()

    def observe(self, observation: Any) -> None:
        index = int(observation.frame_index)
        if not 0 <= index < self._n_steps:
            raise ValueError(f"frame index {index} lies outside the planned {self._n_steps} frames.")
        mask = observation.measurement_row_mask
        if mask is None:
            raise ValueError("the loop did not provide the requested measurement_row_mask.")
        if self.row_masks is None:
            self.row_masks = np.zeros((self._n_steps, int(mask.size)), dtype=bool)
        elif mask.size != self.row_masks.shape[1]:
            raise ValueError("the measurement row count changed between frames.")
        self.row_masks[index] = mask
        self.frames_seen += 1
        telemetry = observation.detector_telemetry
        if telemetry is None:
            if self.telemetry_frames:
                raise ValueError(f"frame {index} carries no detector telemetry while earlier frames did.")
            return
        if self.subaperture_ids is None:
            self.subaperture_ids = tuple(telemetry.subaperture_ids)
            count = len(self.subaperture_ids)
            for name in _TRACE_FLOAT_FIELDS:
                value = getattr(telemetry, name)
                if value is None:
                    self.unavailable.add(name)
                else:
                    self.arrays[name] = np.full((self._n_steps, *np.shape(value)), math.nan)
            for name in _TRACE_BOOL_FIELDS:
                value = getattr(telemetry, name)
                if value is None:
                    self.unavailable.add(name)
                else:
                    self.arrays[name] = np.zeros((self._n_steps, count), dtype=bool)
        elif tuple(telemetry.subaperture_ids) != self.subaperture_ids:
            raise ValueError("the telemetry lenslet layout changed between frames.")
        for name, target in self.arrays.items():
            value = getattr(telemetry, name)
            if value is None or np.shape(value) != target.shape[1:]:
                raise ValueError(f"telemetry field {name} changed its availability or shape at frame {index}.")
            target[index] = value
        for name in self.unavailable:
            if getattr(telemetry, name) is not None:
                raise ValueError(f"telemetry field {name} appeared at frame {index} after being unavailable.")
        self.telemetry_frames += 1


class MaskLockError(ValueError):
    """Raised when a mask-locked measurement cannot replay the twin's rows exactly."""


class _MaskLockedSensor:
    """A noisy physical sensor whose loop measurements replay a given row schedule (arm B).

    ``schedule`` is the twin arm's effective row mask, frame by frame (a
    ``(n_frames, n_rows)`` boolean matrix in the sensor's row order).  Every
    ``measure`` or ``measure_exposure`` call is one frame, in order: the
    sensor protocol passes no frame index, so the call count is the frame
    counter, a call beyond the schedule is refused, and the owner checks
    afterwards that exactly the planned frames were measured.  Rows are
    removed freely; a row is added only where the noisy centroid is finite
    (the expected centroid is a diagnostic, never a condition).  Otherwise the
    measurement is refused with :class:`MaskLockError`; with
    ``allow_partial_lock`` such rows stay invalid and are counted, and the
    owner reports the lock as partial.  The telemetry's ``valid_subapertures``
    follows the locked rows, and a forced lenslet's per-criterion flags are
    raised with it so the telemetry stays self-consistent; the sensor's own
    gate decisions are kept in ``own_valid_subapertures``.  Every other
    attribute (the noiseless response identities, row layout, geometry) is
    the sensor's.  The wrapper carries its own ``config_hash``: its row
    selection changes what the loop reconstructs, so the locked arm's loop
    hash differs from the noise-on arm's while the run's configuration hash
    does not.  Calls that bypass the lock (``noise_model``,
    ``measure_operating_expectation``, calibration on the wrapped sensor)
    never advance the frame counter.
    """

    def __init__(
        self,
        sensor: Any,
        *,
        schedule: np.ndarray,
        row_ids: Sequence[str],
        schedule_source: str,
        allow_partial_lock: bool = False,
    ) -> None:
        rows = tuple(row_ids)
        if rows != tuple(sensor.row_ids):
            raise MaskLockError("the schedule's row IDs do not match the sensor's rows.")
        matrix = np.asarray(schedule)
        if matrix.dtype != np.dtype(bool) or matrix.ndim != 2 or matrix.shape[1] != len(rows):
            raise MaskLockError(
                "the schedule must be a (frames, rows) boolean matrix in the sensor's row order."
            )
        if matrix.shape[0] < 1 or matrix.shape[1] % _ROWS_PER_LENSLET:
            raise MaskLockError("the schedule needs x and y rows for every lenslet and at least one frame.")
        lenslets = matrix[:, 0::_ROWS_PER_LENSLET]
        if not np.array_equal(lenslets, matrix[:, 1::_ROWS_PER_LENSLET]):
            raise MaskLockError(
                "the schedule separates the x and y rows of a lenslet; the physical sensor gates lenslets."
            )
        if len(tuple(sensor.subaperture_ids)) != lenslets.shape[1]:
            raise MaskLockError("the schedule's lenslet count differs from the sensor's layout.")
        self._sensor = sensor
        self._row_ids = rows
        self._schedule = np.array(matrix, copy=True)
        self._schedule.flags.writeable = False
        self._lenslets = np.array(lenslets, copy=True)
        self._allow_partial = bool(allow_partial_lock)
        self._frame = 0
        n_frames = int(matrix.shape[0])
        self.rows_removed = np.zeros(n_frames, dtype=int)
        self.rows_added = np.zeros(n_frames, dtype=int)
        self.rows_unaddable = np.zeros(n_frames, dtype=int)
        self.own_valid_subapertures = np.zeros(self._lenslets.shape, dtype=bool)
        self._config_hash = component_config_hash(
            "physical_shack_hartmann_mask_locked_replay",
            {
                "schema": MASK_LOCK_SCHEMA,
                "sensor_config_hash": sensor.config_hash,
                "row_ids": rows,
                "schedule_shape": [int(value) for value in matrix.shape],
                "schedule_sha256": hashlib.sha256(np.ascontiguousarray(matrix).tobytes()).hexdigest(),
                "schedule_source": str(schedule_source),
                "frame_counting": "one_frame_per_measure_call",
                "forced_row_policy": (
                    "keep_unaddable_rows_invalid" if self._allow_partial else "refuse_nonfinite_forced_rows"
                ),
            },
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._sensor, name)

    @property
    def config_hash(self) -> str:
        return self._config_hash

    @property
    def row_ids(self) -> tuple[str, ...]:
        return self._row_ids

    @property
    def schedule(self) -> np.ndarray:
        return self._schedule

    @property
    def n_frames(self) -> int:
        return int(self._schedule.shape[0])

    @property
    def frames_measured(self) -> int:
        return self._frame

    def _scheduled_frame(self) -> int:
        # Checked before the sensor is asked: a call beyond the schedule draws
        # no noise and advances nothing.
        index = self._frame
        if index >= self.n_frames:
            raise MaskLockError(
                f"the schedule covers {self.n_frames} frames; measurement {index + 1} has no row mask to replay."
            )
        return index

    def measure(self, residual_opd_m: np.ndarray, *, random_streams: Any, include_noise: bool) -> WfsMeasurement:
        index = self._scheduled_frame()
        return self._locked(
            self._sensor.measure(residual_opd_m, random_streams=random_streams, include_noise=include_noise),
            index,
        )

    def measure_exposure(
        self, residual_opd_samples: Sequence[np.ndarray], *, random_streams: Any, include_noise: bool
    ) -> WfsMeasurement:
        index = self._scheduled_frame()
        return self._locked(
            self._sensor.measure_exposure(
                residual_opd_samples, random_streams=random_streams, include_noise=include_noise
            ),
            index,
        )

    def _locked(self, measurement: WfsMeasurement, index: int) -> WfsMeasurement:
        telemetry = measurement.detector_telemetry
        if telemetry is None:
            raise MaskLockError("a mask-locked measurement needs the sensor's detector telemetry.")
        if measurement.vector.row_ids != self._row_ids or tuple(telemetry.subaperture_ids) != tuple(
            self._sensor.subaperture_ids
        ):
            raise MaskLockError("the measurement's row or lenslet layout is not the scheduled one.")
        own = np.asarray(measurement.valid_subapertures, dtype=bool)
        locked = np.array(self._lenslets[index], copy=True)
        shifts = np.asarray(telemetry.centroids_xy_px, dtype=float) - np.asarray(
            telemetry.reference_centroids_xy_px, dtype=float
        )
        # The expected centroid is a diagnostic, never a condition of the lock.
        addable = np.all(np.isfinite(shifts), axis=1)
        forced = locked & ~own
        unaddable = forced & ~addable
        if np.any(unaddable):
            names = [self._sensor.subaperture_ids[position] for position in np.flatnonzero(unaddable)]
            if not self._allow_partial:
                raise MaskLockError(
                    f"frame {index}: lenslets {names} are scheduled valid but their noisy centroid is "
                    "not finite; refusing to force them valid."
                )
            locked &= ~unaddable
            forced = locked & ~own
        self.rows_unaddable[index] = _ROWS_PER_LENSLET * int(np.count_nonzero(unaddable))
        self.rows_removed[index] = _ROWS_PER_LENSLET * int(np.count_nonzero(own & ~locked))
        self.rows_added[index] = _ROWS_PER_LENSLET * int(np.count_nonzero(forced))
        self.own_valid_subapertures[index] = own
        vector = MeasurementVector(
            values=np.where(locked[:, None], shifts, math.nan).reshape(-1),
            valid_rows=np.repeat(locked, _ROWS_PER_LENSLET),
            row_ids=self._row_ids,
            measurement_unit=measurement.vector.measurement_unit,
        )
        locked_telemetry = replace(
            telemetry,
            valid_subapertures=locked,
            valid_by_flux=np.asarray(telemetry.valid_by_flux, dtype=bool) | forced,
            valid_by_snr=np.asarray(telemetry.valid_by_snr, dtype=bool) | forced,
            valid_by_uncertainty=np.asarray(telemetry.valid_by_uncertainty, dtype=bool) | forced,
            valid_by_clipping=np.asarray(telemetry.valid_by_clipping, dtype=bool) | forced,
        )
        metadata = {
            **dict(measurement.metadata),
            "mask_lock": {
                "schema": MASK_LOCK_SCHEMA,
                "frame_index": index,
                "rows_removed": int(self.rows_removed[index]),
                "rows_added": int(self.rows_added[index]),
                "rows_unaddable": int(self.rows_unaddable[index]),
            },
        }
        self._frame += 1
        return WfsMeasurement(
            vector=vector, valid_subapertures=locked, metadata=metadata, detector_telemetry=locked_telemetry
        )


def _block_mean_and_error(values: np.ndarray, block_frames: int) -> tuple[float, float | None]:
    usable = values[: values.size // block_frames * block_frames]
    blocks = usable.reshape(-1, block_frames).mean(axis=1)
    error = float(np.std(blocks, ddof=1) / math.sqrt(blocks.size)) if blocks.size > 1 else None
    return float(np.mean(values)), error


def _arm_metrics(history: Any, window: slice) -> tuple[dict[str, Any], np.ndarray]:
    """The legacy per-arm scalars of a paired run and the frame squares of its window."""

    post = np.asarray(history.post_update_residual_opd_rms_m, dtype=float)[window]
    open_loop = np.asarray(history.open_loop_opd_rms_m, dtype=float)[window]
    metrics = {
        "post_update_rms_m": float(np.mean(post)),
        "post_update_mean_square_m2": float(np.mean(post**2)),
        "open_loop_rms_m": float(np.mean(open_loop)),
        "valid_measurement_fraction": float(
            np.mean(np.asarray(history.valid_measurement_fraction, dtype=float)[window])
        ),
        "reconstruction_usable_fraction": float(
            np.mean(np.asarray(history.reconstruction_usable, dtype=bool)[window])
        ),
        "lost_lock": bool(post[-1] > open_loop[-1]),
    }
    return metrics, post**2


def _flat_wavefront_model(system: Any, result: dict[str, Any]) -> None:
    """The recorded flat-wavefront reference column (unchanged by tracing)."""

    quality = system.wfs.noise_model(np.zeros(system.wfs.geometry.pupil_shape))
    supported = np.asarray(quality.supported, dtype=bool)
    variance = np.sum(np.asarray(quality.centroid_sigma_xy_px, dtype=float) ** 2, axis=1)
    result["predicted_centroid_variance_px2"] = (
        float(np.mean(variance[supported])) if np.any(supported) else None
    )
    result["supported_lenslet_fraction"] = float(np.mean(supported))
    result["detected_e_full_subap"] = float(np.max(system.wfs.detected_e_per_subap))


def _propagation_weights(system: Any) -> dict[str, Any]:
    """Pupil variance of the DM response to a unit slope in each measurement row.

    ``w_r`` (metres squared of OPD per pixel squared): the piston-removed
    pupil mean square of the correction the fixed reconstructor and command
    map return for a measurement that has ``_PROPAGATION_PROBE_PX`` in row
    ``r`` alone with every row valid, divided by the probe squared.  These
    are the propagation weights of the S4 contract (section 5.3) in the
    measurement vector's row order (x then y per lenslet).  Defined for
    actuator-space reconstructors; probing after the loop changes no
    history (the reconstructor and the DM are stateless apart from caches).
    """

    matrix = system.interaction_matrix
    row_ids = tuple(system.wfs.row_ids)
    if matrix.coordinate_kind != "dm_command_opd":
        return {
            "available": False,
            "reason": f"coordinate kind {matrix.coordinate_kind!r}: weights are defined for actuator-space reconstructors",
        }
    response = reconstructor_matrix(system.reconstructor, row_ids) * _PROPAGATION_PROBE_PX
    actuator_ids = tuple(system.dm.actuator_ids)
    positions = {identifier: position for position, identifier in enumerate(actuator_ids)}
    pupil = np.asarray(system.wfs.geometry.pupil_mask, dtype=bool)
    weights = np.zeros(len(row_ids))
    saturated = 0
    for row in range(len(row_ids)):
        full = np.zeros(len(actuator_ids))
        for position, identifier in enumerate(matrix.coordinate_ids):
            full[positions[identifier]] = response[position, row]
        synthesis = system.dm.opd_from_commands(
            DmCommandVector(values_opd_m=full, actuator_ids=actuator_ids, command_unit="m_opd_equivalent")
        )
        opd = np.asarray(synthesis.correction_opd_m, dtype=float)[pupil]
        opd = opd - np.mean(opd)
        weights[row] = float(np.mean(opd * opd)) / _PROPAGATION_PROBE_PX**2
        saturated += int(float(synthesis.saturation_fraction) > 0.0)
    return {
        "available": True,
        "definition": (
            "piston-removed pupil mean square (m^2) of the DM correction returned by the fixed "
            "reconstructor and command map for a unit slope (1 px) in one measurement row with every "
            f"row valid; probed at {_PROPAGATION_PROBE_PX:g} px and divided by the probe squared"
        ),
        "units": "m2_opd_per_px2",
        "row_order": "measurement vector rows: x then y per lenslet",
        "weights_m2_per_px2": weights,
        "saturated_probe_rows": saturated,
    }


def _run_paired_arm(
    run_config: SystemConfig,
    *,
    system: Any,
    wfs: Any,
    include_noise: bool,
    burn_in_frames: int,
    n_steps: int,
    trace: bool,
) -> tuple[Any, _PupilResidualRecorder, _TelemetryTraceRecorder | None]:
    """One arm of a paired run: the component loop with the legacy map recorder (and the trace)."""

    from ..control.loop import run_closed_loop as run_component_loop
    from ._component_configs import exposure_keywords, loop_config

    recorder = _PupilResidualRecorder(int(burn_in_frames))
    tracer = _TelemetryTraceRecorder(int(n_steps)) if trace else None
    observers: tuple[Any, ...] = (recorder,) if tracer is None else (recorder, tracer)
    history = run_component_loop(
        loop_config(run_config),
        random_streams=system.random_streams,
        atmosphere=system.atmosphere,
        wfs=wfs,
        dm=system.dm,
        interaction_matrix=system.interaction_matrix,
        reconstructor=system.reconstructor,
        command_projector=system.command_projector,
        controller=system.controller,
        include_noise=include_noise,
        recovery=system.recovery_policy,
        observers=observers,
        **exposure_keywords(run_config),
    )
    return history, recorder, tracer


def _trace_payload(
    *,
    arm_order: tuple[str, str],
    histories: dict[str, Any],
    tracers: dict[str, _TelemetryTraceRecorder],
    recorders: dict[str, _PupilResidualRecorder],
    squares: dict[str, np.ndarray],
    variance_per_frame: np.ndarray,
    burn_in_frames: int,
    n_steps: int,
    weights: dict[str, Any] | None,
    retain_residual_maps: bool,
) -> dict[str, Any]:
    """The per-frame arrays of a traced paired run (the sidecar's content)."""

    arms: dict[str, Any] = {}
    for arm in arm_order:
        history, tracer = histories[arm], tracers[arm]
        if tracer.frames_seen != n_steps:
            raise RuntimeError(f"the {arm} trace observed {tracer.frames_seen} of {n_steps} frames.")
        if tracer.row_masks is None or not np.array_equal(tracer.row_masks, history.measurement_row_masks):
            raise RuntimeError(f"the {arm} trace's row masks differ from the history's effective rows.")
        metadata = dict(history.metadata)
        arms[arm] = {
            "measurement_row_masks": np.array(history.measurement_row_masks, dtype=bool),
            **{name: np.array(getattr(history, name)) for name in _TRACE_HISTORY_FIELDS},
            "telemetry": {name: array for name, array in tracer.arrays.items()},
            "telemetry_unavailable": sorted(tracer.unavailable),
            "telemetry_frames": int(tracer.telemetry_frames),
            "subaperture_ids": tracer.subaperture_ids,
            "history_config_hash": history.config_hash,
            "component_hashes": dict(metadata["component_hashes"]),
            "random_stream_ids": dict(metadata["random_stream_ids"]),
            "recovery": None if metadata.get("recovery") is None else dict(metadata["recovery"]),
            "wfs_exposure": None if metadata.get("wfs_exposure") is None else dict(metadata["wfs_exposure"]),
        }
    noisy_arm = next(arm for arm in arm_order if arm.startswith("noise_on"))
    twin_arm = next(arm for arm in arm_order if arm != noisy_arm)
    reference = histories[noisy_arm]
    mean_square_difference = squares[noisy_arm] - squares[twin_arm]
    disagreement = np.count_nonzero(
        histories[noisy_arm].measurement_row_masks != histories[twin_arm].measurement_row_masks, axis=1
    )
    payload: dict[str, Any] = {
        "schema": TRACE_SCHEMA,
        "arm_order": list(arm_order),
        "noisy_arm": noisy_arm,
        "twin_arm": twin_arm,
        "n_steps": int(n_steps),
        "burn_in_frames": int(burn_in_frames),
        "frame_index": np.arange(n_steps, dtype=np.int64),
        "analysed_frame_index": np.arange(int(burn_in_frames), n_steps, dtype=np.int64),
        # Per analysed frame: the legacy estimator (piston-removed pupil mean
        # square of the float32-recorded map difference), the difference of
        # the arms' mean-square residuals (float64 history) and their cross
        # term, all in m^2.
        "delta_v_m2": np.array(variance_per_frame, dtype=float),
        "mean_square_difference_m2": np.array(mean_square_difference, dtype=float),
        "cross_term_m2": np.array(mean_square_difference - variance_per_frame, dtype=float),
        "mask_disagreement_rows": disagreement.astype(np.int64),
        "row_ids": tuple(reference.metadata["row_ids"]),
        "calibration_valid_rows": np.asarray(reference.metadata["calibration_valid_rows"], dtype=bool),
        "arms": arms,
        "propagation_weights": weights,
        "residual_maps": None,
    }
    if retain_residual_maps:
        mask = recorders[noisy_arm].mask
        assert mask is not None
        payload["residual_maps"] = {
            "pupil_mask": np.array(mask, dtype=bool),
            "precision": "float32 pupil samples of the post-update residual OPD (m), frames from burn-in",
            **{arm: np.asarray(recorders[arm].samples, dtype=np.float32) for arm in arm_order},
        }
    return payload


def _operating_state_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """E0: the noisy arm's centroid residuals against the operating-state model.

    ``n = c_noisy - c_expected`` per lenslet, axis and analysed frame, with
    ``c_expected`` the plain centre of gravity of the expected processed
    window of the same frame.  Its mean, centred variance (``ddof = 1``) and
    second moment are reported separately; the model column is the frame
    mean of ``sigma**2`` (never ``mean(sigma)**2``).  The support is the set
    of lenslets that the noisy arm keeps valid and model-supported, with
    finite measured and expected centroids, in every analysed frame.
    Equal-weight aggregates sum the two axes per lenslet and average over the
    support; the propagation-weighted ratio weights each row by the fixed
    reconstructor's pupil response.  A pooled temporal variance can include a
    changing conditional centroid bias, so the variance is not identified
    with the mean conditional sensor variance; both are reported.
    """

    noisy = payload["arms"][payload["noisy_arm"]]
    twin = payload["arms"][payload["twin_arm"]]
    telemetry = noisy["telemetry"]
    frames = payload["analysed_frame_index"]
    required = ("centroids_xy_px", "expected_centroids_xy_px", "centroid_sigma_xy_px", "valid_subapertures", "uncertainty_supported")
    missing = [name for name in required if name not in telemetry]
    summary: dict[str, Any] = {
        "schema": "shwfs_ao.experiments.detector_level.operating_state_summary.v1",
        "definition": "n = c_noisy - c_expected on the noisy arm's own operating state; model = mean_t(sigma_xy**2)",
        "analysed_frames": int(frames.size),
        "centering": "ddof=1 variance about the per-lenslet, per-axis temporal mean; second moment uncentred",
        "support_rule": "valid and model-supported with finite measured and expected centroids in every analysed frame (noisy arm)",
        "axis_combination": "x and y summed per lenslet (as predicted_centroid_variance_px2)",
    }
    if missing or noisy["telemetry_frames"] != payload["n_steps"]:
        summary["available"] = False
        summary["reason"] = f"telemetry fields unavailable: {missing}" if missing else "telemetry absent on some frames"
        return summary
    centroids = telemetry["centroids_xy_px"][frames]
    expected = telemetry["expected_centroids_xy_px"][frames]
    sigma_squared = telemetry["centroid_sigma_xy_px"][frames] ** 2
    support = np.all(
        telemetry["valid_subapertures"][frames]
        & telemetry["uncertainty_supported"][frames]
        & np.all(np.isfinite(centroids), axis=2)
        & np.all(np.isfinite(expected), axis=2),
        axis=0,
    )
    summary["support_lenslets"] = int(np.count_nonzero(support))
    summary["support_fraction"] = float(np.mean(support))
    if frames.size < 2 or not np.any(support):
        summary["available"] = False
        summary["reason"] = "fewer than two analysed frames or an empty support"
        return summary
    residual = (centroids - expected)[:, support, :]
    mean = residual.mean(axis=0)
    variance = residual.var(axis=0, ddof=1)
    second_moment = np.mean(residual**2, axis=0)
    model = np.mean(sigma_squared[:, support, :], axis=0)
    twin_telemetry = twin["telemetry"]
    twin_model = None
    if "centroid_sigma_xy_px" in twin_telemetry and twin["telemetry_frames"] == payload["n_steps"]:
        twin_model = np.mean(twin_telemetry["centroid_sigma_xy_px"][frames] ** 2, axis=0)[support, :]
    summary["available"] = True
    summary["equal_weight"] = {
        "mean_residual_px": [float(np.mean(mean[:, 0])), float(np.mean(mean[:, 1]))],
        "realized_variance_px2": float(np.mean(np.sum(variance, axis=1))),
        "realized_second_moment_px2": float(np.mean(np.sum(second_moment, axis=1))),
        "operating_state_model_variance_px2": float(np.mean(np.sum(model, axis=1))),
        "twin_state_model_variance_px2": None if twin_model is None else float(np.nanmean(np.sum(twin_model, axis=1))),
        "ratio_variance_over_model": float(np.mean(np.sum(variance, axis=1)) / np.mean(np.sum(model, axis=1))),
        "ratio_second_moment_over_model": float(np.mean(np.sum(second_moment, axis=1)) / np.mean(np.sum(model, axis=1))),
    }
    weights = payload.get("propagation_weights")
    if weights is not None and weights.get("available"):
        per_row = np.asarray(weights["weights_m2_per_px2"], dtype=float).reshape(-1, _ROWS_PER_LENSLET)[support, :]
        total = float(np.sum(per_row))
        summary["propagation_weighted"] = {
            "domain": "support lenslets, both axes, weights = fixed-reconstructor pupil response per row",
            "weight_total_m2_per_px2": total,
            "realized_variance_px2": float(np.sum(per_row * variance) / total),
            "realized_second_moment_px2": float(np.sum(per_row * second_moment) / total),
            "operating_state_model_variance_px2": float(np.sum(per_row * model) / total),
            "ratio_variance_over_model": float(np.sum(per_row * variance) / np.sum(per_row * model)),
            "ratio_second_moment_over_model": float(np.sum(per_row * second_moment) / np.sum(per_row * model)),
            "propagated_realized_variance_m2": float(np.sum(per_row * variance)),
            "propagated_model_variance_m2": float(np.sum(per_row * model)),
        }
    else:
        summary["propagation_weighted"] = None
    return summary


def _recovery_acted(recovery: dict[str, Any] | None) -> bool:
    if recovery is None:
        return False
    return any(
        isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
        for key, value in recovery.items()
        if key != "config_hash"
    )


def _trace_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """JSON scalars of a trace: gate activity, mask disagreement, recovery, telemetry availability."""

    frames = payload["analysed_frame_index"]
    arms: dict[str, Any] = {}
    gate_quiet = True
    for arm, entry in payload["arms"].items():
        rejected = int(np.count_nonzero(~entry["reconstruction_usable"][frames]))
        acted = _recovery_acted(entry["recovery"])
        arms[arm] = {
            "rejected_frames_after_burn_in": rejected,
            "min_valid_measurement_fraction_after_burn_in": float(np.min(entry["valid_measurement_fraction"][frames])),
            "max_saturation_fraction_after_burn_in": float(np.max(entry["saturation_fraction"][frames])),
            "mean_saturation_fraction_after_burn_in": float(np.mean(entry["saturation_fraction"][frames])),
            "recovery": entry["recovery"],
            "recovery_acted": acted,
            "telemetry_frames": entry["telemetry_frames"],
            "telemetry_unavailable": entry["telemetry_unavailable"],
            "history_config_hash": entry["history_config_hash"],
        }
        gate_quiet &= rejected == 0 and not acted
    disagreement = payload["mask_disagreement_rows"][frames]
    n_rows = int(payload["arms"][payload["noisy_arm"]]["measurement_row_masks"].shape[1])
    fraction = float(np.sum(disagreement)) / float(frames.size * n_rows)
    return {
        "schema": "shwfs_ao.experiments.detector_level.trace_summary.v1",
        "arms": arms,
        "mask_disagreement_row_frame_fraction": fraction,
        "mask_disagreement_frames": int(np.count_nonzero(disagreement)),
        # Gate-quiet by the contract's predeclared rule (section 4.3): fewer
        # than 0.1 % of row-frames disagree, no rejected reconstruction and
        # no recovery action in either arm.
        "gate_quiet": bool(gate_quiet and fraction < 1.0e-3),
        "gate_quiet_rule": "mask disagreement < 1e-3 of row-frames, no rejected reconstruction, no recovery action, after burn-in",
        "cross_term_mean_m2": float(np.mean(payload["cross_term_m2"])),
        "residual_maps_retained": payload["residual_maps"] is not None,
    }


def _paired_noise_core(
    config: SystemConfig,
    *,
    root_seed: int,
    n_steps: int,
    burn_in_frames: int,
    execution: ScaoExecutionOptions | None,
    block_frames: int,
    trace: bool,
    retain_residual_maps: bool,
    propagation_weights: bool,
) -> dict[str, Any]:
    run_config = replace(
        config,
        random=RandomSeedConfig(root_seed=int(root_seed)),
        controller=replace(config.controller, n_steps=int(n_steps)),
    )
    window = slice(int(burn_in_frames), None)
    squares: dict[str, np.ndarray] = {}
    recorders: dict[str, _PupilResidualRecorder] = {}
    histories: dict[str, Any] = {}
    tracers: dict[str, _TelemetryTraceRecorder] = {}
    weights: dict[str, Any] | None = None
    result: dict[str, Any] = {
        "config_hash": run_config.config_hash,
        "root_seed": int(root_seed),
        "n_steps": int(n_steps),
        "burn_in_frames": int(burn_in_frames),
        "block_frames": int(block_frames),
        "arms": {},
    }
    started = time.perf_counter()
    for arm in PAIRED_NOISE_ARMS:
        system = build_scao_system(run_config, execution=execution)
        wfs = system.wfs if arm == "noise_on" else _OperatingExpectationSensor(system.wfs)
        history, recorders[arm], tracer = _run_paired_arm(
            run_config,
            system=system,
            wfs=wfs,
            include_noise=arm == "noise_on",
            burn_in_frames=burn_in_frames,
            n_steps=n_steps,
            trace=trace,
        )
        result["arms"][arm], squares[arm] = _arm_metrics(history, window)
        if arm == "noise_on":
            _flat_wavefront_model(system, result)
            if trace and propagation_weights:
                weights = _propagation_weights(system)
        if tracer is not None:
            histories[arm] = history
            tracers[arm] = tracer

    on = np.asarray(recorders["noise_on"].samples, dtype=float)
    off = np.asarray(recorders["operating_expectation"].samples, dtype=float)
    delta = on - off
    delta -= np.mean(delta, axis=1, keepdims=True)
    variance_per_frame = np.mean(delta**2, axis=1)
    result["noise_variance_m2"], result["noise_variance_standard_error_m2"] = _block_mean_and_error(
        variance_per_frame, block_frames
    )
    (
        result["mean_square_difference_m2"],
        result["mean_square_difference_standard_error_m2"],
    ) = _block_mean_and_error(squares["noise_on"] - squares["operating_expectation"], block_frames)
    if trace:
        payload = _trace_payload(
            arm_order=PAIRED_NOISE_ARMS,
            histories=histories,
            tracers=tracers,
            recorders=recorders,
            squares=squares,
            variance_per_frame=variance_per_frame,
            burn_in_frames=int(burn_in_frames),
            n_steps=int(n_steps),
            weights=weights,
            retain_residual_maps=retain_residual_maps,
        )
        result["operating_state"] = _operating_state_summary(payload)
        result["trace_summary"] = _trace_summary(payload)
        result["trace"] = payload
    result["wall_s"] = time.perf_counter() - started
    return result


def paired_noise_run(
    config: SystemConfig,
    *,
    root_seed: int,
    n_steps: int,
    burn_in_frames: int,
    execution: ScaoExecutionOptions | None = None,
    block_frames: int = 25,
) -> dict[str, Any]:
    """The temporal detector-noise contribution to the residual, isolated.

    Two identically built systems (same atmosphere, persistent maps, fixed
    calibration products, reference, interaction matrix and reconstructor)
    run the same loop.  One measures with detector noise; the other measures
    the noiseless operating expectation (same star, sky, products and
    validity gates, which use model expectations).  Fitting, temporal,
    aliasing and calibration-master errors are common to both arms, and the
    atmosphere is identical, so the per-frame difference of the post-update
    residual maps is the DM response to propagated temporal detector noise.
    ``noise_variance_m2`` is the mean over frames of that difference's
    squared piston-removed pupil RMS; it has no cross term with the common
    residual.  The difference of the arms' mean-square residuals is kept as
    ``mean_square_difference_m2`` for comparison; its cross term
    ``2 <phi_common, n>`` averages to zero but dominates its scatter when
    the common residual is large.  Standard errors come from per-frame values
    averaged in blocks of ``block_frames`` frames, which absorbs the loop's
    frame-to-frame correlation.

    The noise model's prediction for a flat wavefront is returned with it:
    the mean temporal centroid variance (x plus y, pixels squared) over the
    lenslets it supports, and the detected electrons per full subaperture.

    This untraced run is the recorded protocol and stays bit for bit what it
    was; :func:`paired_noise_run_traced` observes the same two arms.
    """

    return _paired_noise_core(
        config,
        root_seed=root_seed,
        n_steps=n_steps,
        burn_in_frames=burn_in_frames,
        execution=execution,
        block_frames=block_frames,
        trace=False,
        retain_residual_maps=False,
        propagation_weights=False,
    )


def paired_noise_run_traced(
    config: SystemConfig,
    *,
    root_seed: int,
    n_steps: int,
    burn_in_frames: int,
    execution: ScaoExecutionOptions | None = None,
    block_frames: int = 25,
    retain_residual_maps: bool = False,
    propagation_weights: bool = True,
) -> dict[str, Any]:
    """:func:`paired_noise_run` with the S4 per-frame trace (ticket T1).

    The two arms run in the legacy order with the legacy map recorder plus a
    passive telemetry observer, so every legacy scalar of the result is bit
    for bit the untraced run's.  Three keys are added: ``trace`` (arrays for
    a sidecar: per analysed frame ``delta_v_m2``, ``mean_square_difference_m2``
    and ``cross_term_m2``; per frame and arm the effective row masks, the
    loop telemetry and the sensor's per-lenslet telemetry, including the
    operating-state model sigma, the measured and the expected centroids;
    the propagation weights; the residual maps when ``retain_residual_maps``),
    ``operating_state`` (the E0 summary, beside the flat-wavefront
    ``predicted_centroid_variance_px2`` column, which is kept) and
    ``trace_summary`` (gate activity, mask disagreement, recovery).
    """

    return _paired_noise_core(
        config,
        root_seed=root_seed,
        n_steps=n_steps,
        burn_in_frames=burn_in_frames,
        execution=execution,
        block_frames=block_frames,
        trace=True,
        retain_residual_maps=retain_residual_maps,
        propagation_weights=propagation_weights,
    )


def paired_noise_run_mask_locked(
    config: SystemConfig,
    *,
    root_seed: int,
    n_steps: int,
    burn_in_frames: int,
    execution: ScaoExecutionOptions | None = None,
    block_frames: int = 25,
    allow_partial_lock: bool = False,
    retain_residual_maps: bool = False,
    propagation_weights: bool = True,
) -> dict[str, Any]:
    """Arm B of the S4 contract: the noisy arm replays the twin's effective rows.

    A separate protocol, not an option of the recorded one: the operating
    twin runs first (``MASK_LOCKED_NOISE_ARMS``) because its effective row
    masks are the schedule; the noisy arm then measures through
    :class:`_MaskLockedSensor`, which carries its own ``config_hash``, so
    the locked arm's loop hash differs from a noise-on arm's.  The result
    has the shape of :func:`paired_noise_run_traced` with the arm labels of
    this protocol, plus ``mask_lock_protocol`` (schema, arm order, mask
    source and forced-row policy) and ``lock`` (exact or partial, frames measured,
    rows removed, added and unaddable).  A lock is reported exact only when
    every frame's effective rows equal the twin's.
    """

    run_config = replace(
        config,
        random=RandomSeedConfig(root_seed=int(root_seed)),
        controller=replace(config.controller, n_steps=int(n_steps)),
    )
    window = slice(int(burn_in_frames), None)
    twin_arm, locked_arm = MASK_LOCKED_NOISE_ARMS
    squares: dict[str, np.ndarray] = {}
    recorders: dict[str, _PupilResidualRecorder] = {}
    histories: dict[str, Any] = {}
    tracers: dict[str, _TelemetryTraceRecorder] = {}
    result: dict[str, Any] = {
        "config_hash": run_config.config_hash,
        "root_seed": int(root_seed),
        "n_steps": int(n_steps),
        "burn_in_frames": int(burn_in_frames),
        "block_frames": int(block_frames),
        "arms": {},
        # Named apart from the evidence runner's physical ``protocol`` row field.
        "mask_lock_protocol": {
            "schema": MASK_LOCK_SCHEMA,
            "arm_order": list(MASK_LOCKED_NOISE_ARMS),
            "mask_source": "operating_expectation twin of the same run and seed, frame by frame",
            "forced_row_policy": "keep_unaddable_rows_invalid" if allow_partial_lock else "refuse_nonfinite_forced_rows",
        },
    }
    started = time.perf_counter()
    system = build_scao_system(run_config, execution=execution)
    history, recorders[twin_arm], tracer = _run_paired_arm(
        run_config,
        system=system,
        wfs=_OperatingExpectationSensor(system.wfs),
        include_noise=False,
        burn_in_frames=burn_in_frames,
        n_steps=n_steps,
        trace=True,
    )
    assert tracer is not None
    histories[twin_arm], tracers[twin_arm] = history, tracer
    result["arms"][twin_arm], squares[twin_arm] = _arm_metrics(history, window)
    schedule = np.array(history.measurement_row_masks, dtype=bool)

    system = build_scao_system(run_config, execution=execution)
    locked = _MaskLockedSensor(
        system.wfs,
        schedule=schedule,
        row_ids=tuple(history.metadata["row_ids"]),
        schedule_source=f"{twin_arm} loop {history.config_hash}",
        allow_partial_lock=allow_partial_lock,
    )
    history, recorders[locked_arm], tracer = _run_paired_arm(
        run_config,
        system=system,
        wfs=locked,
        include_noise=True,
        burn_in_frames=burn_in_frames,
        n_steps=n_steps,
        trace=True,
    )
    assert tracer is not None
    histories[locked_arm], tracers[locked_arm] = history, tracer
    result["arms"][locked_arm], squares[locked_arm] = _arm_metrics(history, window)
    _flat_wavefront_model(system, result)
    weights = _propagation_weights(system) if propagation_weights else None
    exact = bool(
        locked.frames_measured == int(n_steps)
        and np.array_equal(history.measurement_row_masks, schedule)
        and not np.any(locked.rows_unaddable)
    )
    result["lock"] = {
        "exact": exact,
        "frames_measured": int(locked.frames_measured),
        "frames_planned": int(n_steps),
        "mismatched_frames": int(np.count_nonzero(np.any(history.measurement_row_masks != schedule, axis=1))),
        "rows_removed_total": int(np.sum(locked.rows_removed)),
        "rows_added_total": int(np.sum(locked.rows_added)),
        "rows_unaddable_total": int(np.sum(locked.rows_unaddable)),
        "rows_removed_after_burn_in": int(np.sum(locked.rows_removed[window])),
        "rows_added_after_burn_in": int(np.sum(locked.rows_added[window])),
        "wrapper_config_hash": locked.config_hash,
    }

    on = np.asarray(recorders[locked_arm].samples, dtype=float)
    off = np.asarray(recorders[twin_arm].samples, dtype=float)
    delta = on - off
    delta -= np.mean(delta, axis=1, keepdims=True)
    variance_per_frame = np.mean(delta**2, axis=1)
    result["noise_variance_m2"], result["noise_variance_standard_error_m2"] = _block_mean_and_error(
        variance_per_frame, block_frames
    )
    (
        result["mean_square_difference_m2"],
        result["mean_square_difference_standard_error_m2"],
    ) = _block_mean_and_error(squares[locked_arm] - squares[twin_arm], block_frames)
    payload = _trace_payload(
        arm_order=MASK_LOCKED_NOISE_ARMS,
        histories=histories,
        tracers=tracers,
        recorders=recorders,
        squares=squares,
        variance_per_frame=variance_per_frame,
        burn_in_frames=int(burn_in_frames),
        n_steps=int(n_steps),
        weights=weights,
        retain_residual_maps=retain_residual_maps,
    )
    payload["mask_lock"] = {
        "rows_removed": locked.rows_removed.astype(np.int64),
        "rows_added": locked.rows_added.astype(np.int64),
        "rows_unaddable": locked.rows_unaddable.astype(np.int64),
        "own_valid_subapertures": np.array(locked.own_valid_subapertures, dtype=bool),
    }
    result["operating_state"] = _operating_state_summary(payload)
    result["trace_summary"] = _trace_summary(payload)
    result["trace"] = payload
    result["wall_s"] = time.perf_counter() - started
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
