# Detector-level integrator loop reports residual OPD RMS, command norm, valid-centroid fraction, latency, stroke clipping, fixed-length histories, and config hash.

"""
Simple closed-loop adaptive-optics utilities.

This module provides both an ideal geometric SH-WFS closed-loop baseline and a
more realistic detector-level centroiding closed-loop extension. It is compact
and readable by design: the goal is to demonstrate AO control concepts, not to
replace a calibrated AO simulation package.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any

import numpy as np

from data_sources import ALLOWED_SOURCE_CLASSES
from dm_model import DMModel, synthesize_dm_phase_rad
from interaction_matrix import (
    PokeMtxResult,
    expand_controlled_commands,
    tsvd_reconstruct_commands,
    vectorize_detector_measurement,
)
from reconstruction import measure_slopes, rms
from psf_tools import strehl_ratio
from phase_screen import frozen_flow_shift_physical
from shwfs_detector import reference_centroids, measure_centroid_shifts
from synthetic_instrument_data import DetectorShwfsCalibration, measure_detector_shwfs


DEFAULT_LOOP_SOURCE_CLASS = "synthetic_assumed"
DEFAULT_LOOP_SOURCE_NOTE = (
    "Synthetic detector-level integrator loop settings for the 2 m SCAO "
    "demonstrator; not measured RTC telemetry."
)
PHASE_TWO_PI = 2.0 * np.pi
NM_PER_M = 1.0e9


class ClosedLoopError(ValueError):
    """Raised when a detector-level closed-loop simulation is invalid."""


@dataclass(frozen=True)
class DetectorLoopConfig:
    """Configuration for the detector-level integrator loop.

    Args:
        n_steps: Number of closed-loop iterations to run.
        gain: Scalar integrator gain applied to delayed reconstructed command
            increments.
        leak: Fractional command leak per frame. ``0`` means no leak.
        latency_frames: Integer command latency in frames. A value of ``2``
            applies a reconstructed command two frames after it is measured.
        frame_rate_hz: Loop frame rate used to report the latency in
            milliseconds.
        include_detector_noise: Whether to use the detector-noise settings
            stored in the calibration.
        seed: Random seed for stochastic detector measurements.
        source_class: Provenance class from the documented source-class taxonomy.
        source_note: Human-readable provenance note.

    Returns:
        Immutable loop configuration.

    Raises:
        ClosedLoopError: If scalars, latency, or provenance fields are invalid.

    Physics note:
        The loop corrects OPD-equivalent DM commands from detector centroid
        residuals. All phase inputs are radians at the calibration WFS
        wavelength.
    """

    n_steps: int = 50
    gain: float = 0.35
    leak: float = 0.0
    latency_frames: int = 0
    frame_rate_hz: float = 500.0
    include_detector_noise: bool = False
    seed: int = 1
    source_class: str = DEFAULT_LOOP_SOURCE_CLASS
    source_note: str = DEFAULT_LOOP_SOURCE_NOTE

    def __post_init__(self) -> None:
        if int(self.n_steps) < 1:
            raise ClosedLoopError("n_steps must be >= 1.")
        _require_nonnegative("gain", self.gain)
        if not (0.0 <= float(self.leak) < 1.0):
            raise ClosedLoopError("leak must satisfy 0 <= leak < 1.")
        if int(self.latency_frames) < 0:
            raise ClosedLoopError("latency_frames must be >= 0.")
        _require_positive("frame_rate_hz", self.frame_rate_hz)
        if self.source_class not in ALLOWED_SOURCE_CLASSES:
            raise ClosedLoopError(
                f"source_class={self.source_class!r} is not in the permitted taxonomy "
                f"{sorted(ALLOWED_SOURCE_CLASSES)}."
            )
        if not str(self.source_note).strip():
            raise ClosedLoopError("source_note must be a non-empty string.")

    @property
    def latency_ms(self) -> float:
        return 1.0e3 * float(self.latency_frames) / float(self.frame_rate_hz)


@dataclass(frozen=True)
class LoopHistory:
    """Detector-level closed-loop history.

    Required shared fields are ``residual_opd_rms``, ``command_norm``,
    ``valid_centroid_frac``, and ``config_hash``.

    Args:
        residual_opd_rms: Post-update residual OPD RMS per frame in nm.
        command_norm: Full DM command-vector norm per frame in nm OPD
            equivalent.
        valid_centroid_frac: Fraction of valid detector centroids per frame.
        config_hash: Hash of loop, poke-matrix, DM, and calibration settings.
        open_loop_opd_rms: Atmospheric OPD RMS without correction in nm.
        pre_update_residual_opd_rms: Residual OPD RMS before command update in
            nm.
        command_history_nm: Full clipped DM command vector per frame in nm OPD
            equivalent.
        delta_command_norm_nm: Norm of reconstructed command increments before
            latency application.
        applied_delta_norm_nm: Norm of delayed command increments applied to
            the integrator.
        saturation_fraction: Fraction of DM actuators stroke-clipped per frame.
        residual_phase_rms_rad: Post-update residual phase RMS at the WFS
            wavelength.
        latency_frames: Command latency in frames.
        latency_ms: Command latency in milliseconds.
        gain: Integrator gain.
        leak: Integrator leak.
        source_class: Provenance class for this synthetic loop.
        units: JSON-serializable unit labels for history arrays.

    Returns:
        Immutable loop history with fixed-length arrays.

    Raises:
        ClosedLoopError: Built only after all history arrays pass finite-value
            and length checks.

    Physics note:
        ``residual_opd_rms`` is the field intended for later science PSF
        metrics. It is derived from phase via the calibration WFS wavelength.
    """

    residual_opd_rms: np.ndarray
    command_norm: np.ndarray
    valid_centroid_frac: np.ndarray
    config_hash: str
    open_loop_opd_rms: np.ndarray
    pre_update_residual_opd_rms: np.ndarray
    command_history_nm: np.ndarray
    delta_command_norm_nm: np.ndarray
    applied_delta_norm_nm: np.ndarray
    saturation_fraction: np.ndarray
    residual_phase_rms_rad: np.ndarray
    latency_frames: int
    latency_ms: float
    gain: float
    leak: float
    source_class: str
    units: dict[str, str]


def actuator_centers_on_pupil(
    diameter: float = 1.0,
    n_actuators: int = 8,
    include_edge: bool = True,
) -> tuple[np.ndarray, float]:
    """Generate square-grid DM actuator centers inside a circular pupil."""
    if n_actuators < 2:
        raise ValueError("n_actuators must be >= 2.")
    if diameter <= 0:
        raise ValueError("diameter must be positive.")

    radius = diameter / 2.0
    if include_edge:
        coords = np.linspace(-radius, radius, n_actuators)
    else:
        pitch_tmp = diameter / n_actuators
        coords = np.linspace(-radius + pitch_tmp / 2.0, radius - pitch_tmp / 2.0, n_actuators)

    pitch = float(coords[1] - coords[0]) if len(coords) > 1 else diameter

    centers = []
    for x in coords:
        for y in coords:
            if x**2 + y**2 <= radius**2:
                centers.append([x, y])

    return np.asarray(centers, dtype=float), pitch


def gaussian_influence_functions(
    X: np.ndarray,
    Y: np.ndarray,
    pupil_mask: np.ndarray,
    centers: np.ndarray,
    pitch: float,
    coupling: float = 0.35,
    normalize_peak: bool = True,
) -> np.ndarray:
    """Build Gaussian DM influence functions."""
    if pitch <= 0:
        raise ValueError("pitch must be positive.")
    if coupling <= 0:
        raise ValueError("coupling must be positive.")

    sigma = coupling * pitch
    infl = []
    for x0, y0 in centers:
        g = np.exp(-((X - x0) ** 2 + (Y - y0) ** 2) / (2.0 * sigma**2))
        g = np.where(pupil_mask, g, np.nan)
        if normalize_peak:
            peak = np.nanmax(g)
            if peak > 0:
                g = g / peak
        infl.append(g)

    return np.asarray(infl, dtype=float)


def synthesize_dm_phase(
    commands: np.ndarray,
    influence_functions: np.ndarray,
    pupil_mask: np.ndarray,
    remove_mean: bool = True,
) -> np.ndarray:
    """Synthesize a DM phase surface from actuator commands."""
    commands = np.asarray(commands, dtype=float)
    if commands.shape[0] != influence_functions.shape[0]:
        raise ValueError("Number of commands must match number of influence functions.")

    dm = np.nansum(commands[:, None, None] * np.nan_to_num(influence_functions), axis=0)
    dm = np.where(pupil_mask, dm, np.nan)

    if remove_mean:
        dm = dm.copy()
        finite = pupil_mask & np.isfinite(dm)
        if np.any(finite):
            dm[finite] -= np.nanmean(dm[finite])

    return dm


def build_dm_wfs_response_matrix(
    influence_functions: np.ndarray,
    pupil_mask: np.ndarray,
    X: np.ndarray,
    Y: np.ndarray,
    n_lenslets: int = 12,
    min_fill: float = 0.5,
) -> tuple[np.ndarray, np.ndarray]:
    """Build a geometric SH-WFS response matrix for DM actuator commands."""
    columns = []
    reference_centers = None

    for infl in influence_functions:
        centers, slopes = measure_slopes(
            infl,
            pupil_mask,
            X,
            Y,
            n_lenslets=n_lenslets,
            min_fill=min_fill,
            noise_std=0.0,
        )
        if reference_centers is None:
            reference_centers = centers
        elif centers.shape != reference_centers.shape or not np.allclose(centers, reference_centers):
            raise RuntimeError("Sub-aperture geometry changed between influence functions.")
        columns.append(slopes.reshape(-1))

    return np.column_stack(columns), reference_centers


def build_dm_detector_response_matrix(
    influence_functions: np.ndarray,
    pupil_mask: np.ndarray,
    X: np.ndarray,
    Y: np.ndarray,
    n_lenslets: int = 12,
    min_fill: float = 0.5,
    pad_factor: int = 8,
    threshold_fraction: float = 0.0,
    subtract_minimum: bool = False,
    detector_window_size: int | None = None,
    calibration_amplitude: float = 1e-3,
) -> tuple[np.ndarray, np.ndarray, list[np.ndarray], np.ndarray]:
    """
    Build detector-level DM-WFS response matrix.

    Each column is the central finite-difference centroid response to one DM
    actuator influence function.
    """
    if calibration_amplitude <= 0:
        raise ValueError("calibration_amplitude must be positive.")

    centers, masks, reference = reference_centroids(
        pupil_mask,
        X,
        Y,
        n_lenslets=n_lenslets,
        min_fill=min_fill,
        pad_factor=pad_factor,
        threshold_fraction=threshold_fraction,
        detector_window_size=detector_window_size,
        subtract_minimum=subtract_minimum,
    )

    columns = []
    for infl in influence_functions:
        infl_clean = np.nan_to_num(infl, nan=0.0)
        phase_p = calibration_amplitude * infl_clean
        phase_m = -calibration_amplitude * infl_clean

        _, shifts_p = measure_centroid_shifts(
            phase_p,
            pupil_mask,
            X,
            Y,
            n_lenslets=n_lenslets,
            min_fill=min_fill,
            pad_factor=pad_factor,
            photons=None,
            read_noise_e=0.0,
            background_e=0.0,
            threshold_fraction=threshold_fraction,
            subtract_minimum=subtract_minimum,
            detector_window_size=detector_window_size,
            reference=reference,
            masks=masks,
            centers=centers,
        )
        _, shifts_m = measure_centroid_shifts(
            phase_m,
            pupil_mask,
            X,
            Y,
            n_lenslets=n_lenslets,
            min_fill=min_fill,
            pad_factor=pad_factor,
            photons=None,
            read_noise_e=0.0,
            background_e=0.0,
            threshold_fraction=threshold_fraction,
            subtract_minimum=subtract_minimum,
            detector_window_size=detector_window_size,
            reference=reference,
            masks=masks,
            centers=centers,
        )

        column = ((shifts_p - shifts_m) / (2.0 * calibration_amplitude)).reshape(-1)
        columns.append(column)

    B = np.column_stack(columns)
    return B, centers, masks, reference


def reconstruct_dm_delta(
    slopes: np.ndarray,
    dm_response_matrix: np.ndarray,
    rcond: float = 1e-3,
) -> tuple[np.ndarray, np.ndarray, int, np.ndarray]:
    """
    Estimate a DM command increment from residual WFS measurements.

    Non-finite measurement rows are dropped together with corresponding response
    matrix rows. This is important for detector-level centroid failures.
    """
    s = np.asarray(slopes, dtype=float).reshape(-1)
    A = np.asarray(dm_response_matrix, dtype=float)

    if A.shape[0] != s.size:
        raise ValueError("Measurement vector length must match response-matrix row count.")

    valid = np.isfinite(s) & np.all(np.isfinite(A), axis=1)
    if not np.any(valid):
        raise ValueError("No finite WFS measurements are available for DM reconstruction.")

    delta, residuals, rank, singular_values = np.linalg.lstsq(A[valid], s[valid], rcond=rcond)
    return delta, residuals, rank, singular_values


def build_detector_dm_poke_matrix_from_calibration(*args, **kwargs):
    """Build the detector-level DM poke matrix via the dedicated module.

    Thin control-side wrapper that keeps the tested implementation in
    ``interaction_matrix.py`` while preserving this call site.
    """

    from interaction_matrix import build_detector_dm_poke_matrix

    return build_detector_dm_poke_matrix(*args, **kwargs)


def run_detector_integrator_loop(
    phase_sequence_rad: np.ndarray,
    calibration: DetectorShwfsCalibration,
    dm_model: DMModel,
    poke_result: PokeMtxResult,
    config: DetectorLoopConfig | None = None,
) -> LoopHistory:
    """Run the detector-level integrator closed loop.

    Args:
        phase_sequence_rad: Either one static phase map or a sequence with
            shape ``(n_steps, ny, nx)``. Values are radians at the calibration
            WFS wavelength, with NaN allowed outside the pupil.
        calibration: detector SH-WFS calibration.
        dm_model: synthetic DM model.
        poke_result: detector-level DM poke matrix.
        config: Optional detector-loop settings.

    Returns:
        :class:`LoopHistory` with fixed-length residual, command, centroid,
        latency, and stroke diagnostics.

    Raises:
        ClosedLoopError: If grids, phase shapes, history lengths, or finite
            checks fail.

    Physics note:
        The loop measures residual phase with the detector model, reconstructs
        a DM command increment through the TSVD matrix, delays that
        increment by ``latency_frames``, then applies a leaky integrator.
    """

    config = config or DetectorLoopConfig()
    _validate_loop_inputs(calibration, dm_model, poke_result)
    phase_sequence = _normalize_phase_sequence(phase_sequence_rad, calibration, config.n_steps)
    rng = np.random.default_rng(config.seed)
    commands_full_nm = np.zeros(dm_model.n_actuators, dtype=float)
    zero_delta = np.zeros(poke_result.n_controlled_actuators, dtype=float)
    delay_queue: list[np.ndarray] = []

    open_loop_opd_rms = []
    pre_update_residual_opd_rms = []
    residual_opd_rms = []
    residual_phase_rms_rad = []
    command_norm = []
    command_history_nm = []
    delta_command_norm_nm = []
    applied_delta_norm_nm = []
    saturation_fraction = []
    valid_centroid_frac = []

    for step_index, atmosphere_phase in enumerate(phase_sequence):
        _assert_masked_finite(atmosphere_phase, calibration.pupil_mask, f"atmosphere phase step {step_index}")
        dm_before_phase, _ = synthesize_dm_phase_rad(
            commands_full_nm,
            dm_model,
            wavelength_m=calibration.geometry.wfs_wavelength_m,
            remove_piston=True,
        )
        residual_before = _remove_piston_phase(atmosphere_phase - dm_before_phase, calibration.pupil_mask)
        _assert_masked_finite(residual_before, calibration.pupil_mask, f"pre-update residual phase step {step_index}")

        measurement = measure_detector_shwfs(
            residual_before,
            calibration,
            include_noise=config.include_detector_noise,
            seed=int(rng.integers(0, 2**31 - 1)),
        )
        measurement_vector = vectorize_detector_measurement(measurement, poke_result)
        if np.any(np.isfinite(measurement_vector)):
            reconstruction = tsvd_reconstruct_commands(measurement_vector, poke_result)
            delta_command_nm = reconstruction.commands_nm
        else:
            # Low-validity frame: no usable centroids (e.g. a faint-NGS frame
            # where every spot fails the flux/SNR/uncertainty criterion). Freeze the
            # command increment and let the integrator leak act, rather than
            # reconstructing a command from pure detector noise.
            delta_command_nm = zero_delta.copy()
        _assert_all_finite(delta_command_nm, f"reconstructed command increment step {step_index}")

        delay_queue.append(delta_command_nm.copy())
        if len(delay_queue) > config.latency_frames:
            delayed_controlled_delta = delay_queue.pop(0)
        else:
            delayed_controlled_delta = zero_delta.copy()
        delayed_full_delta = expand_controlled_commands(delayed_controlled_delta, poke_result, dm_model)

        requested_commands_nm = (1.0 - float(config.leak)) * commands_full_nm + float(config.gain) * delayed_full_delta
        dm_after_phase, synthesis = synthesize_dm_phase_rad(
            requested_commands_nm,
            dm_model,
            wavelength_m=calibration.geometry.wfs_wavelength_m,
            remove_piston=True,
        )
        commands_full_nm = synthesis.clipped_commands_nm.copy()
        residual_after = _remove_piston_phase(atmosphere_phase - dm_after_phase, calibration.pupil_mask)
        _assert_masked_finite(residual_after, calibration.pupil_mask, f"post-update residual phase step {step_index}")

        open_loop_opd_rms.append(_phase_rms_to_opd_nm(atmosphere_phase, calibration.pupil_mask, calibration))
        pre_update_residual_opd_rms.append(
            _phase_rms_to_opd_nm(residual_before, calibration.pupil_mask, calibration)
        )
        residual_opd_rms.append(_phase_rms_to_opd_nm(residual_after, calibration.pupil_mask, calibration))
        residual_phase_rms_rad.append(_masked_rms(residual_after, calibration.pupil_mask))
        command_norm.append(float(np.linalg.norm(commands_full_nm)))
        command_history_nm.append(commands_full_nm.copy())
        delta_command_norm_nm.append(float(np.linalg.norm(delta_command_nm)))
        applied_delta_norm_nm.append(float(np.linalg.norm(delayed_controlled_delta)))
        saturation_fraction.append(float(synthesis.saturation_fraction))
        valid_centroid_frac.append(_valid_centroid_fraction(measurement.valid, poke_result.valid_subaperture_mask))

    settings = _loop_settings(calibration, dm_model, poke_result, config, phase_sequence.shape)
    history = LoopHistory(
        residual_opd_rms=np.asarray(residual_opd_rms, dtype=float),
        command_norm=np.asarray(command_norm, dtype=float),
        valid_centroid_frac=np.asarray(valid_centroid_frac, dtype=float),
        config_hash=_config_hash(settings),
        open_loop_opd_rms=np.asarray(open_loop_opd_rms, dtype=float),
        pre_update_residual_opd_rms=np.asarray(pre_update_residual_opd_rms, dtype=float),
        command_history_nm=np.asarray(command_history_nm, dtype=float),
        delta_command_norm_nm=np.asarray(delta_command_norm_nm, dtype=float),
        applied_delta_norm_nm=np.asarray(applied_delta_norm_nm, dtype=float),
        saturation_fraction=np.asarray(saturation_fraction, dtype=float),
        residual_phase_rms_rad=np.asarray(residual_phase_rms_rad, dtype=float),
        latency_frames=int(config.latency_frames),
        latency_ms=float(config.latency_ms),
        gain=float(config.gain),
        leak=float(config.leak),
        source_class=config.source_class,
        units={
            "residual_opd_rms": "nm_OPD_RMS",
            "command_norm": "nm_OPD_equivalent",
            "command_history_nm": "nm_OPD_equivalent",
            "delta_command_norm_nm": "nm_OPD_equivalent",
            "applied_delta_norm_nm": "nm_OPD_equivalent",
            "residual_phase_rms_rad": "rad_at_wfs_wavelength",
            "valid_centroid_frac": "fraction",
            "latency_ms": "ms",
        },
    )
    _validate_loop_history(history, n_steps=config.n_steps, n_actuators=dm_model.n_actuators)
    return history


def loop_history_summary(history: LoopHistory) -> dict[str, Any]:
    """Return JSON-serializable closed-loop diagnostics."""

    return {
        "n_steps": int(history.residual_opd_rms.size),
        "initial_residual_opd_rms_nm": float(history.residual_opd_rms[0]),
        "final_residual_opd_rms_nm": float(history.residual_opd_rms[-1]),
        "median_tail_residual_opd_rms_nm": float(
            np.median(history.residual_opd_rms[max(0, history.residual_opd_rms.size // 2) :])
        ),
        "final_command_norm_nm": float(history.command_norm[-1]),
        "max_command_norm_nm": float(np.max(history.command_norm)),
        "median_valid_centroid_frac": float(np.median(history.valid_centroid_frac)),
        "latency_frames": int(history.latency_frames),
        "latency_ms": float(history.latency_ms),
        "gain": float(history.gain),
        "leak": float(history.leak),
        "source_class": history.source_class,
        "config_hash": history.config_hash,
    }


def shifted_atmosphere(
    phase0: np.ndarray,
    pupil_mask: np.ndarray,
    shift_x_pix: int = 0,
    shift_y_pix: int = 0,
) -> np.ndarray:
    """Toy frozen-flow phase shift with periodic boundary conditions."""
    full = np.nan_to_num(phase0, nan=0.0)
    shifted = np.roll(np.roll(full, int(shift_y_pix), axis=0), int(shift_x_pix), axis=1)
    shifted = np.where(pupil_mask, shifted, np.nan)
    shifted[pupil_mask] -= np.nanmean(shifted[pupil_mask])
    return shifted


def run_closed_loop_ao(
    phase0: np.ndarray,
    pupil_mask: np.ndarray,
    X: np.ndarray,
    Y: np.ndarray,
    influence_functions: np.ndarray,
    dm_response_matrix: np.ndarray,
    n_steps: int = 40,
    wind_shift_per_step: tuple[int, int] = (1, 0),
    gain: float = 0.4,
    n_lenslets: int = 12,
    min_fill: float = 0.5,
    slope_noise_std: float = 0.0,
    rcond: float = 1e-3,
    command_leak: float = 0.0,
    compute_strehl: bool = True,
    pad_factor: int = 4,
    seed: int = 1,
) -> dict[str, np.ndarray]:
    """Run a simple geometric-SH-WFS integrator closed-loop AO simulation."""
    if not (0 <= command_leak < 1):
        raise ValueError("command_leak must satisfy 0 <= command_leak < 1.")

    rng = np.random.default_rng(seed)
    commands = np.zeros(influence_functions.shape[0], dtype=float)
    sx_step, sy_step = wind_shift_per_step

    hist = {
        "rms_atmosphere": [],
        "rms_before": [],
        "rms_after": [],
        "strehl_before": [],
        "strehl_after": [],
        "command_norm": [],
    }

    for k in range(n_steps):
        atm = shifted_atmosphere(
            phase0,
            pupil_mask,
            shift_x_pix=int(k * sx_step),
            shift_y_pix=int(k * sy_step),
        )

        dm_before = synthesize_dm_phase(commands, influence_functions, pupil_mask)
        residual_before = np.where(pupil_mask, atm - dm_before, np.nan)
        residual_before[pupil_mask] -= np.nanmean(residual_before[pupil_mask])

        _, slopes = measure_slopes(
            residual_before,
            pupil_mask,
            X,
            Y,
            n_lenslets=n_lenslets,
            min_fill=min_fill,
            noise_std=slope_noise_std,
            seed=int(rng.integers(0, 2**31 - 1)),
        )

        delta, *_ = reconstruct_dm_delta(slopes, dm_response_matrix, rcond=rcond)
        commands = (1.0 - command_leak) * commands + gain * delta

        dm_after = synthesize_dm_phase(commands, influence_functions, pupil_mask)
        residual_after = np.where(pupil_mask, atm - dm_after, np.nan)
        residual_after[pupil_mask] -= np.nanmean(residual_after[pupil_mask])

        hist["rms_atmosphere"].append(rms(atm, pupil_mask))
        hist["rms_before"].append(rms(residual_before, pupil_mask))
        hist["rms_after"].append(rms(residual_after, pupil_mask))
        hist["command_norm"].append(float(np.linalg.norm(commands)))

        if compute_strehl:
            hist["strehl_before"].append(float(strehl_ratio(residual_before, pupil_mask, pad_factor=pad_factor)))
            hist["strehl_after"].append(float(strehl_ratio(residual_after, pupil_mask, pad_factor=pad_factor)))

    return {key: np.asarray(value) for key, value in hist.items()}


def run_closed_loop_ao_detector(
    phase0: np.ndarray,
    pupil_mask: np.ndarray,
    X: np.ndarray,
    Y: np.ndarray,
    influence_functions: np.ndarray,
    dm_detector_response_matrix: np.ndarray,
    detector_reference: np.ndarray,
    detector_masks: list[np.ndarray],
    detector_centers: np.ndarray,
    n_steps: int = 40,
    vx: float = 10.0,
    vy: float = 0.0,
    dt: float = 0.002,
    delta: float = 0.02,
    gain: float = 0.3,
    n_lenslets: int = 12,
    min_fill: float = 0.5,
    pad_factor: int = 8,
    photons: float | None = 1e4,
    read_noise_e: float = 1.0,
    background_e: float = 0.0,
    threshold_fraction: float = 0.0,
    subtract_minimum: bool = False,
    detector_window_size: int | None = None,
    rcond: float = 1e-3,
    command_leak: float = 0.0,
    seed: int = 1,
    compute_strehl: bool = True,
) -> dict[str, np.ndarray]:
    """
    Detector-level closed-loop AO.

    Chain:
        atmosphere -> residual phase -> lenslet spots -> noisy centroids
        -> centroid-response DM reconstruction -> integrator update
    """
    if not (0 <= command_leak < 1):
        raise ValueError("command_leak must satisfy 0 <= command_leak < 1.")

    rng = np.random.default_rng(seed)
    commands = np.zeros(influence_functions.shape[0], dtype=float)

    hist = {
        "rms_atmosphere": [],
        "rms_before": [],
        "rms_after": [],
        "strehl_before": [],
        "strehl_after": [],
        "command_norm": [],
        "valid_centroids": [],
    }

    for k in range(n_steps):
        atm = frozen_flow_shift_physical(
            phase0,
            vx=vx,
            vy=vy,
            dt=k * dt,
            delta=delta,
            mask=pupil_mask,
        )

        dm_before = synthesize_dm_phase(commands, influence_functions, pupil_mask)
        residual_before = np.where(pupil_mask, atm - dm_before, np.nan)
        residual_before[pupil_mask] -= np.nanmean(residual_before[pupil_mask])

        _, shifts, diag = measure_centroid_shifts(
            residual_before,
            pupil_mask,
            X,
            Y,
            n_lenslets=n_lenslets,
            min_fill=min_fill,
            pad_factor=pad_factor,
            photons=photons,
            read_noise_e=read_noise_e,
            background_e=background_e,
            threshold_fraction=threshold_fraction,
            subtract_minimum=subtract_minimum,
            detector_window_size=detector_window_size,
            seed=int(rng.integers(0, 2**31 - 1)),
            reference=detector_reference,
            masks=detector_masks,
            centers=detector_centers,
            return_diagnostics=True,
        )

        delta_cmd, *_ = reconstruct_dm_delta(shifts, dm_detector_response_matrix, rcond=rcond)
        commands = (1.0 - command_leak) * commands + gain * delta_cmd

        dm_after = synthesize_dm_phase(commands, influence_functions, pupil_mask)
        residual_after = np.where(pupil_mask, atm - dm_after, np.nan)
        residual_after[pupil_mask] -= np.nanmean(residual_after[pupil_mask])

        hist["rms_atmosphere"].append(rms(atm, pupil_mask))
        hist["rms_before"].append(rms(residual_before, pupil_mask))
        hist["rms_after"].append(rms(residual_after, pupil_mask))
        hist["command_norm"].append(float(np.linalg.norm(commands)))
        hist["valid_centroids"].append(int(diag["n_valid"]))

        if compute_strehl:
            hist["strehl_before"].append(float(strehl_ratio(residual_before, pupil_mask, pad_factor=pad_factor)))
            hist["strehl_after"].append(float(strehl_ratio(residual_after, pupil_mask, pad_factor=pad_factor)))

    return {key: np.asarray(value) for key, value in hist.items()}


def gain_scan(
    gains: list[float],
    phase0: np.ndarray,
    pupil_mask: np.ndarray,
    X: np.ndarray,
    Y: np.ndarray,
    influence_functions: np.ndarray,
    dm_response_matrix: np.ndarray,
    n_steps: int = 40,
    wind_shift_per_step: tuple[int, int] = (1, 0),
    n_lenslets: int = 12,
    min_fill: float = 0.5,
    slope_noise_std: float = 0.0,
    rcond: float = 1e-3,
    command_leak: float = 0.0,
    seed: int = 1,
) -> dict[float, dict[str, float]]:
    """Run a compact loop-gain scan and summarize residual performance."""
    out = {}
    for gain in gains:
        hist = run_closed_loop_ao(
            phase0,
            pupil_mask,
            X,
            Y,
            influence_functions,
            dm_response_matrix,
            n_steps=n_steps,
            wind_shift_per_step=wind_shift_per_step,
            gain=gain,
            n_lenslets=n_lenslets,
            min_fill=min_fill,
            slope_noise_std=slope_noise_std,
            rcond=rcond,
            command_leak=command_leak,
            compute_strehl=False,
            seed=seed,
        )
        tail = hist["rms_after"][max(0, n_steps // 2) :]
        out[float(gain)] = {
            "median_tail_rms": float(np.median(tail)),
            "mean_tail_rms": float(np.mean(tail)),
            "final_rms": float(hist["rms_after"][-1]),
        }
    return out


def _validate_loop_inputs(
    calibration: DetectorShwfsCalibration,
    dm_model: DMModel,
    poke_result: PokeMtxResult,
) -> None:
    if calibration.x_m.shape != dm_model.x_m.shape:
        raise ClosedLoopError(
            f"Calibration grid shape {calibration.x_m.shape} != DM grid shape {dm_model.x_m.shape}."
        )
    if not np.allclose(calibration.x_m, dm_model.x_m) or not np.allclose(calibration.y_m, dm_model.y_m):
        raise ClosedLoopError("Calibration and DM grids are not sampled on the same coordinates.")
    if not np.array_equal(calibration.pupil_mask, dm_model.pupil_mask):
        raise ClosedLoopError("Calibration and DM pupil masks differ.")
    expected_rows = 2 * poke_result.n_valid_lenslets
    if poke_result.poke_matrix.shape != (expected_rows, poke_result.n_controlled_actuators):
        raise ClosedLoopError(
            f"Poke matrix shape {poke_result.poke_matrix.shape} != "
            f"{(expected_rows, poke_result.n_controlled_actuators)}."
        )
    _assert_all_finite(poke_result.poke_matrix, "Poke matrix")
    if poke_result.controlled_actuator_indices.size == 0:
        raise ClosedLoopError("Poke matrix has no controlled actuators.")
    if int(np.max(poke_result.controlled_actuator_indices)) >= dm_model.n_actuators:
        raise ClosedLoopError("Poke-matrix actuator indices exceed the DM model actuator count.")


def _normalize_phase_sequence(
    phase_sequence_rad: np.ndarray,
    calibration: DetectorShwfsCalibration,
    n_steps: int,
) -> np.ndarray:
    phase = np.asarray(phase_sequence_rad, dtype=float)
    if phase.ndim == 2:
        sequence = np.repeat(phase[None, :, :], int(n_steps), axis=0)
    elif phase.ndim == 3:
        if phase.shape[0] != int(n_steps):
            raise ClosedLoopError(f"phase_sequence has {phase.shape[0]} steps but n_steps={n_steps}.")
        sequence = phase.copy()
    else:
        raise ClosedLoopError("phase_sequence_rad must be a 2-D static phase map or a 3-D phase sequence.")
    if sequence.shape[1:] != calibration.x_m.shape:
        raise ClosedLoopError(
            f"phase sequence spatial shape {sequence.shape[1:]} != calibration grid {calibration.x_m.shape}."
        )
    for index, phase_map in enumerate(sequence):
        _assert_masked_finite(phase_map, calibration.pupil_mask, f"phase sequence step {index}")
    return sequence


def _remove_piston_phase(phase_rad: np.ndarray, pupil_mask: np.ndarray) -> np.ndarray:
    out = np.asarray(phase_rad, dtype=float).copy()
    finite = np.asarray(pupil_mask, dtype=bool) & np.isfinite(out)
    if not np.any(finite):
        raise ClosedLoopError("No finite pupil samples are available for piston removal.")
    out[finite] -= float(np.mean(out[finite]))
    out[~pupil_mask] = np.nan
    return out


def _phase_rms_to_opd_nm(
    phase_rad: np.ndarray,
    pupil_mask: np.ndarray,
    calibration: DetectorShwfsCalibration,
) -> float:
    return float(_masked_rms(phase_rad, pupil_mask) * calibration.geometry.wfs_wavelength_m / PHASE_TWO_PI * NM_PER_M)


def _masked_rms(values: np.ndarray, pupil_mask: np.ndarray) -> float:
    samples = np.asarray(values, dtype=float)[pupil_mask]
    samples = samples[np.isfinite(samples)]
    if samples.size == 0:
        raise ClosedLoopError("No finite pupil samples are available for RMS calculation.")
    samples = samples - float(np.mean(samples))
    rms_value = float(np.sqrt(np.mean(samples**2)))
    _require_nonnegative("masked RMS", rms_value)
    return rms_value


def _valid_centroid_fraction(measurement_valid: np.ndarray, poke_valid_subapertures: np.ndarray) -> float:
    valid = np.asarray(measurement_valid, dtype=bool)
    retained = np.asarray(poke_valid_subapertures, dtype=bool)
    if valid.shape != retained.shape:
        raise ClosedLoopError(f"measurement valid shape {valid.shape} != poke valid-lenslet shape {retained.shape}.")
    if not np.any(retained):
        raise ClosedLoopError("No retained poke-matrix subapertures are available for centroid fraction.")
    return float(np.mean(valid[retained]))


def _validate_loop_history(history: LoopHistory, n_steps: int, n_actuators: int) -> None:
    vector_fields = {
        "residual_opd_rms": history.residual_opd_rms,
        "command_norm": history.command_norm,
        "valid_centroid_frac": history.valid_centroid_frac,
        "open_loop_opd_rms": history.open_loop_opd_rms,
        "pre_update_residual_opd_rms": history.pre_update_residual_opd_rms,
        "delta_command_norm_nm": history.delta_command_norm_nm,
        "applied_delta_norm_nm": history.applied_delta_norm_nm,
        "saturation_fraction": history.saturation_fraction,
        "residual_phase_rms_rad": history.residual_phase_rms_rad,
    }
    for label, values in vector_fields.items():
        array = np.asarray(values, dtype=float)
        if array.shape != (int(n_steps),):
            raise ClosedLoopError(f"{label} shape {array.shape} != ({n_steps},).")
        _assert_all_finite(array, label)
    if history.command_history_nm.shape != (int(n_steps), int(n_actuators)):
        raise ClosedLoopError(
            f"command_history_nm shape {history.command_history_nm.shape} != {(int(n_steps), int(n_actuators))}."
        )
    _assert_all_finite(history.command_history_nm, "command_history_nm")
    if np.any((history.valid_centroid_frac < 0.0) | (history.valid_centroid_frac > 1.0)):
        raise ClosedLoopError("valid_centroid_frac must stay between 0 and 1.")
    if np.any((history.saturation_fraction < 0.0) | (history.saturation_fraction > 1.0)):
        raise ClosedLoopError("saturation_fraction must stay between 0 and 1.")
    if len(history.config_hash) != 64:
        raise ClosedLoopError("config_hash must be a SHA-256 hex digest.")
    required_units = {"residual_opd_rms", "command_norm", "valid_centroid_frac", "latency_ms"}
    missing = required_units - set(history.units)
    if missing:
        raise ClosedLoopError(f"LoopHistory units missing keys: {sorted(missing)}.")


def _loop_settings(
    calibration: DetectorShwfsCalibration,
    dm_model: DMModel,
    poke_result: PokeMtxResult,
    config: DetectorLoopConfig,
    phase_sequence_shape: tuple[int, ...],
) -> dict[str, Any]:
    return {
        "method": "detector_level_tsvd_integrator",
        "phase_sequence_shape": list(phase_sequence_shape),
        "wfs_wavelength_m": float(calibration.geometry.wfs_wavelength_m),
        "n_pupil_pixels": int(calibration.geometry.n_pupil_pixels),
        "n_lenslets": int(calibration.geometry.n_lenslets),
        "detector_window_px": calibration.geometry.detector_window_px,
        "dm_n_actuators": int(dm_model.n_actuators),
        "dm_stroke_limit_nm": float(dm_model.config.stroke_limit_nm),
        "poke_config_hash": poke_result.config_hash,
        "poke_rcond": float(poke_result.rcond),
        "poke_kept_modes": int(poke_result.kept_modes),
        "n_steps": int(config.n_steps),
        "gain": float(config.gain),
        "leak": float(config.leak),
        "latency_frames": int(config.latency_frames),
        "frame_rate_hz": float(config.frame_rate_hz),
        "latency_ms": float(config.latency_ms),
        "include_detector_noise": bool(config.include_detector_noise),
        "seed": int(config.seed),
        "source_class": config.source_class,
        "source_note": config.source_note,
    }


def _config_hash(settings: dict[str, Any]) -> str:
    payload = json.dumps(_jsonable(settings), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return _jsonable(value.tolist())
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def _assert_masked_finite(values: np.ndarray, pupil_mask: np.ndarray, label: str) -> None:
    array = np.asarray(values, dtype=float)
    mask = np.asarray(pupil_mask, dtype=bool)
    if array.shape != mask.shape:
        raise ClosedLoopError(f"{label} shape {array.shape} != pupil mask shape {mask.shape}.")
    inside = array[mask]
    if not np.all(np.isfinite(inside)):
        finite_frac = float(np.mean(np.isfinite(inside))) if inside.size else 0.0
        raise ClosedLoopError(f"Non-finite values inside {label}; finite_frac={finite_frac:.3f}.")


def _assert_all_finite(values: np.ndarray, label: str) -> None:
    array = np.asarray(values, dtype=float)
    if not np.all(np.isfinite(array)):
        finite_frac = float(np.mean(np.isfinite(array))) if array.size else 0.0
        raise ClosedLoopError(f"Non-finite values in {label}; finite_frac={finite_frac:.3f}.")


def _require_positive(field_name: str, value: float) -> None:
    _require_finite(field_name, value)
    if float(value) <= 0.0:
        raise ClosedLoopError(f"{field_name} must be positive; got {value!r}.")


def _require_nonnegative(field_name: str, value: float) -> None:
    _require_finite(field_name, value)
    if float(value) < 0.0:
        raise ClosedLoopError(f"{field_name} must be non-negative; got {value!r}.")


def _require_finite(field_name: str, value: float) -> None:
    if not math.isfinite(float(value)):
        raise ClosedLoopError(f"{field_name} must be finite; got {value!r}.")
