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

from ..backends.native.dm import (
    gaussian_influence_functions as _native_gaussian_influence_functions,
    square_grid_actuator_centers as _native_square_grid_actuator_centers,
    synthesize_opd as _native_synthesize_opd,
)
from ..core import wavefront as _wavefront
from ..core.provenance import ALLOWED_SOURCE_CLASSES, Provenance as _Provenance
from ..wfs.shack_hartmann.geometric import (
    NativeGeometricShackHartmannSensor as _NativeGeometricShackHartmannSensor,
)
from ._interaction_adapters import (
    calibrate_legacy_influence_columns as _calibrate_legacy_influence_columns,
    legacy_streams as _legacy_calibration_streams,
    legacy_y_up_matrix as _legacy_y_up_matrix,
)
from ._reconstruction_adapters import (
    _legacy_least_squares_reconstructor,
    _legacy_lstsq_payload,
    _legacy_tsvd_reconstructor,
)
from ._control_adapters import _run_legacy_detector_integrator
from .config_hashing import stable_array_descriptor
from .dm_model import DMModel, synthesize_dm_phase_rad
from .interaction_matrix import (
    PokeMtxResult,
    InteractionMatrixError as _InteractionMatrixError,
    _require_rcond as _require_legacy_rcond,
    expand_controlled_commands,
    tsvd_reconstruct_commands,
    vectorize_detector_measurement,
)
from .reconstruction import _legacy_shack_hartmann_geometry, measure_slopes, rms
from .psf_tools import strehl_ratio
from .phase_screen import frozen_flow_shift, frozen_flow_shift_physical
from .shwfs_detector import (
    _LEGACY_WFS_WAVELENGTH_M,
    _legacy_detector_sensor,
    reference_centroids,
    measure_centroid_shifts,
)
from .synthetic_instrument_data import DEFAULT_CENTROID_VALIDITY, DetectorShwfsCalibration, measure_detector_shwfs


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
        _require_integer("n_steps", self.n_steps, minimum=1)
        _require_nonnegative("gain", self.gain)
        if not (0.0 <= float(self.leak) < 1.0):
            raise ClosedLoopError("leak must satisfy 0 <= leak < 1.")
        _require_integer("latency_frames", self.latency_frames, minimum=0)
        _require_positive("frame_rate_hz", self.frame_rate_hz)
        _loop_provenance(self.source_class, self.source_note)

    @property
    def provenance(self) -> _Provenance:
        """Return the canonical provenance record for this loop config."""

        return _loop_provenance(self.source_class, self.source_note)

    @property
    def latency_ms(self) -> float:
        return 1.0e3 * float(self.latency_frames) / float(self.frame_rate_hz)


@dataclass(frozen=True)
class LoopHistory:
    """Detector-level closed-loop history.

    Required shared fields are ``residual_opd_rms``, ``command_rms_nm``,
    ``valid_centroid_frac``, and ``config_hash``.

    Args:
        residual_opd_rms: Post-update residual OPD RMS per frame in nm.
        command_rms_nm: RMS across all DM actuator commands per frame in nm OPD
            equivalent.
        command_l2_norm_nm: Euclidean norm of the full DM command vector per
            frame in nm OPD equivalent.
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
    command_rms_nm: np.ndarray
    command_l2_norm_nm: np.ndarray
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

    @property
    def command_norm(self) -> np.ndarray:
        """Compatibility alias for :attr:`command_l2_norm_nm`."""

        return self.command_l2_norm_nm


def actuator_centers_on_pupil(
    diameter: float = 1.0,
    n_actuators: int = 8,
    include_edge: bool = True,
) -> tuple[np.ndarray, float]:
    """Generate legacy-order centers through the native spatial backend."""
    if n_actuators < 2:
        raise ValueError("n_actuators must be >= 2.")
    if diameter <= 0:
        raise ValueError("diameter must be positive.")

    centers, pitch = _native_square_grid_actuator_centers(
        diameter,
        n_actuators,
        include_edge_actuators=bool(include_edge),
    )
    # Historical callers receive a writable array even though the canonical
    # backend protects its sampled geometry from mutation.
    return np.array(centers, dtype=float, copy=True), pitch


def gaussian_influence_functions(
    X: np.ndarray,
    Y: np.ndarray,
    pupil_mask: np.ndarray,
    centers: np.ndarray,
    pitch: float,
    coupling: float = 0.35,
    normalize_peak: bool = True,
) -> np.ndarray:
    """Build legacy NaN-masked Gaussian influences through the native backend."""
    if pitch <= 0:
        raise ValueError("pitch must be positive.")
    if coupling <= 0:
        raise ValueError("coupling must be positive.")

    pupil = np.asarray(pupil_mask, dtype=bool)
    influences = _native_gaussian_influence_functions(
        X,
        Y,
        pupil,
        centers,
        pitch,
        coupling_width_pitch=coupling,
        normalize_peak=bool(normalize_peak),
    )
    return np.where(pupil[None, :, :], influences, np.nan)


def synthesize_dm_phase(
    commands: np.ndarray,
    influence_functions: np.ndarray,
    pupil_mask: np.ndarray,
    remove_mean: bool = True,
) -> np.ndarray:
    """Synthesize a legacy masked DM map through the native linear backend."""
    commands = np.asarray(commands, dtype=float)
    if commands.shape[0] != influence_functions.shape[0]:
        raise ValueError("Number of commands must match number of influence functions.")

    dm = _native_synthesize_opd(
        commands,
        np.nan_to_num(influence_functions),
    )
    dm = np.where(pupil_mask, dm, np.nan)

    if remove_mean:
        finite = np.asarray(pupil_mask, dtype=bool) & np.isfinite(dm)
        if np.any(finite):
            centered = _wavefront.remove_piston(dm, finite)
            dm = dm.copy()
            dm[finite] = centered[finite]

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

    geometry = _legacy_shack_hartmann_geometry(
        X,
        Y,
        pupil_mask,
        n_lenslets=n_lenslets,
        min_fill=min_fill,
    )
    sensor = _NativeGeometricShackHartmannSensor(geometry)
    response = _calibrate_legacy_influence_columns(
        influence_functions,
        pupil_mask,
        X,
        Y,
        sensor,
        amplitude_m=1.0,
        output_scale_m=1.0,
        method="forward",
        random_streams=_legacy_calibration_streams(1),
    )
    return (
        np.array(response, dtype=float, copy=True),
        np.array(geometry.subaperture_centers_m, dtype=float, copy=True),
    )


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

    sensor, _ = _legacy_detector_sensor(
        X,
        Y,
        pupil_mask,
        n_lenslets=n_lenslets,
        min_fill=min_fill,
        pad_factor=pad_factor,
        photons=None,
        read_noise_e=0.0,
        background_e=0.0,
        threshold_fraction=threshold_fraction,
        subtract_minimum=subtract_minimum,
        detector_window_size=detector_window_size,
        seed=1,
    )
    opd_per_phase_rad_m = _LEGACY_WFS_WAVELENGTH_M / (2.0 * np.pi)
    response = _calibrate_legacy_influence_columns(
        np.nan_to_num(influence_functions, nan=0.0),
        pupil_mask,
        X,
        Y,
        sensor,
        amplitude_m=calibration_amplitude * opd_per_phase_rad_m,
        output_scale_m=opd_per_phase_rad_m,
        method="central",
        random_streams=_legacy_calibration_streams(1),
    )
    response = _legacy_y_up_matrix(response)
    return np.array(response, dtype=float, copy=True), centers, masks, reference


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
    reconstructor = _legacy_least_squares_reconstructor(
        dm_response_matrix,
        rcond,
        matrix_error="dm_response_matrix must be 2-D.",
        length_error=(
            "Measurement vector length must match response-matrix row count."
        ),
        no_rows_error=(
            "No finite WFS measurements are available for DM reconstruction."
        ),
    )
    result = reconstructor.reconstruct(slopes)
    return _legacy_lstsq_payload(
        result,
        coordinate_count=reconstructor.coordinate_count,
    )


def build_detector_dm_poke_matrix_from_calibration(*args, **kwargs):
    """Build the detector-level DM poke matrix via the dedicated module.

    Thin control-side wrapper that keeps the tested implementation in
    ``interaction_matrix.py`` while preserving this call site.
    """

    from .interaction_matrix import build_detector_dm_poke_matrix

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
        The legacy phase, pixel, nanometre, and child-seed conventions are
        adapted at the boundary. Sequencing, latency, and leaky integration
        are owned by the canonical :mod:`shwfs_ao.control` runtime.
    """

    config = config or DetectorLoopConfig()
    _validate_loop_inputs(calibration, dm_model, poke_result)
    _require_legacy_rcond(poke_result.rcond)
    phase_sequence = _normalize_phase_sequence(phase_sequence_rad, calibration, config.n_steps)

    # Keep the installed child-seed derivation byte-for-byte stable.  The
    # canonical runner owns frame sequencing, while the private WFS adapter
    # consumes this precomputed legacy schedule one seed per frame (including
    # noiseless and centroid-invalid frames).
    rng = np.random.default_rng(config.seed)
    frame_seeds = tuple(
        int(rng.integers(0, 2**31 - 1)) for _ in range(config.n_steps)
    )
    canonical_run = _run_legacy_detector_integrator(
        phase_sequence,
        calibration,
        dm_model,
        poke_result,
        n_steps=config.n_steps,
        gain=float(config.gain),
        leak=float(config.leak),
        latency_frames=int(config.latency_frames),
        frame_rate_hz=float(config.frame_rate_hz),
        root_seed=int(config.seed),
        include_detector_noise=bool(config.include_detector_noise),
        frame_seeds=frame_seeds,
    )
    canonical_history = canonical_run.history
    command_history_nm = np.asarray(
        canonical_history.applied_command_history_opd_m,
        dtype=float,
    ) * NM_PER_M

    open_loop_opd_rms = []
    pre_update_residual_opd_rms = []
    residual_opd_rms = []
    residual_phase_rms_rad = []
    command_rms_nm = []
    command_l2_norm_nm = []
    previous_commands_nm = np.zeros(dm_model.n_actuators, dtype=float)

    # Preserve the frozen legacy reporting arithmetic.  Control decisions and
    # applied commands above come exclusively from the canonical runtime; this
    # pass only derives the historical phase/RMS views from that command trace.
    for step_index, (atmosphere_phase, commands_after_nm) in enumerate(
        zip(phase_sequence, command_history_nm, strict=True)
    ):
        _assert_masked_finite(atmosphere_phase, calibration.pupil_mask, f"atmosphere phase step {step_index}")
        dm_before_phase, _ = synthesize_dm_phase_rad(
            previous_commands_nm,
            dm_model,
            wavelength_m=calibration.geometry.wfs_wavelength_m,
            remove_piston=True,
        )
        residual_before = _remove_piston_phase(atmosphere_phase - dm_before_phase, calibration.pupil_mask)
        _assert_masked_finite(residual_before, calibration.pupil_mask, f"pre-update residual phase step {step_index}")

        dm_after_phase, synthesis = synthesize_dm_phase_rad(
            commands_after_nm,
            dm_model,
            wavelength_m=calibration.geometry.wfs_wavelength_m,
            remove_piston=True,
        )
        residual_after = _remove_piston_phase(atmosphere_phase - dm_after_phase, calibration.pupil_mask)
        _assert_masked_finite(residual_after, calibration.pupil_mask, f"post-update residual phase step {step_index}")

        open_loop_opd_rms.append(_phase_rms_to_opd_nm(atmosphere_phase, calibration.pupil_mask, calibration))
        pre_update_residual_opd_rms.append(
            _phase_rms_to_opd_nm(residual_before, calibration.pupil_mask, calibration)
        )
        residual_opd_rms.append(_phase_rms_to_opd_nm(residual_after, calibration.pupil_mask, calibration))
        residual_phase_rms_rad.append(_masked_rms(residual_after, calibration.pupil_mask))
        command_rms_nm.append(float(np.sqrt(np.mean(commands_after_nm**2))))
        command_l2_norm_nm.append(float(np.linalg.norm(commands_after_nm)))
        previous_commands_nm = np.asarray(synthesis.clipped_commands_nm, dtype=float)

    settings = _loop_settings(calibration, dm_model, poke_result, config, phase_sequence)
    history = LoopHistory(
        residual_opd_rms=np.asarray(residual_opd_rms, dtype=float),
        command_rms_nm=np.asarray(command_rms_nm, dtype=float),
        command_l2_norm_nm=np.asarray(command_l2_norm_nm, dtype=float),
        valid_centroid_frac=np.asarray(
            canonical_history.valid_subaperture_fraction,
            dtype=float,
        ),
        config_hash=_config_hash(settings),
        open_loop_opd_rms=np.asarray(open_loop_opd_rms, dtype=float),
        pre_update_residual_opd_rms=np.asarray(pre_update_residual_opd_rms, dtype=float),
        command_history_nm=np.asarray(command_history_nm, dtype=float),
        delta_command_norm_nm=np.asarray(
            canonical_history.delta_command_norm_m,
            dtype=float,
        )
        * NM_PER_M,
        applied_delta_norm_nm=np.asarray(
            canonical_history.released_delta_norm_m,
            dtype=float,
        )
        * NM_PER_M,
        saturation_fraction=np.asarray(
            canonical_history.saturation_fraction,
            dtype=float,
        ),
        residual_phase_rms_rad=np.asarray(residual_phase_rms_rad, dtype=float),
        latency_frames=int(config.latency_frames),
        latency_ms=float(config.latency_ms),
        gain=float(config.gain),
        leak=float(config.leak),
        source_class=config.source_class,
        units={
            "residual_opd_rms": "nm_OPD_RMS",
            "command_rms_nm": "nm_OPD_equivalent_RMS_across_actuators",
            "command_l2_norm_nm": "nm_OPD_equivalent_L2_norm",
            "command_norm": "nm_OPD_equivalent_L2_norm_compatibility_alias",
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
        "final_command_rms_nm": float(history.command_rms_nm[-1]),
        "max_command_rms_nm": float(np.max(history.command_rms_nm)),
        "final_command_l2_norm_nm": float(history.command_l2_norm_nm[-1]),
        "max_command_l2_norm_nm": float(np.max(history.command_l2_norm_nm)),
        "final_command_norm_nm": float(history.command_l2_norm_nm[-1]),
        "max_command_norm_nm": float(np.max(history.command_l2_norm_nm)),
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
    """Shift a complete finite atmosphere, then apply the pupil mask."""

    return frozen_flow_shift(
        phase0,
        shift_x_pix=shift_x_pix,
        shift_y_pix=shift_y_pix,
        mask=pupil_mask,
        remove_mean=True,
    )


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
    """Run a geometric-SH-WFS loop from a complete finite phase screen.

    ``phase0`` must contain the full periodic atmosphere, not a pupil-masked
    NaN-outside map. The pupil is applied after each frozen-flow shift.
    """
    if not (0 <= command_leak < 1):
        raise ValueError("command_leak must satisfy 0 <= command_leak < 1.")

    rng = np.random.default_rng(seed)
    commands = np.zeros(influence_functions.shape[0], dtype=float)
    reconstructor = _legacy_least_squares_reconstructor(
        dm_response_matrix,
        rcond,
        matrix_error="dm_response_matrix must be 2-D.",
        length_error=(
            "Measurement vector length must match response-matrix row count."
        ),
        no_rows_error=(
            "No finite WFS measurements are available for DM reconstruction."
        ),
    )
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
        residual_before = _remove_piston_phase(
            np.where(pupil_mask, atm - dm_before, np.nan),
            pupil_mask,
        )

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

        delta = reconstructor.reconstruct(slopes).coordinates
        commands = (1.0 - command_leak) * commands + gain * delta

        dm_after = synthesize_dm_phase(commands, influence_functions, pupil_mask)
        residual_after = _remove_piston_phase(
            np.where(pupil_mask, atm - dm_after, np.nan),
            pupil_mask,
        )

        hist["rms_atmosphere"].append(_masked_rms(atm, pupil_mask))
        hist["rms_before"].append(_masked_rms(residual_before, pupil_mask))
        hist["rms_after"].append(_masked_rms(residual_after, pupil_mask))
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
    reconstructor = _legacy_least_squares_reconstructor(
        dm_detector_response_matrix,
        rcond,
        matrix_error="dm_response_matrix must be 2-D.",
        length_error=(
            "Measurement vector length must match response-matrix row count."
        ),
        no_rows_error=(
            "No finite WFS measurements are available for DM reconstruction."
        ),
    )

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
        residual_before = _remove_piston_phase(
            np.where(pupil_mask, atm - dm_before, np.nan),
            pupil_mask,
        )

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

        delta_cmd = reconstructor.reconstruct(shifts).coordinates
        commands = (1.0 - command_leak) * commands + gain * delta_cmd

        dm_after = synthesize_dm_phase(commands, influence_functions, pupil_mask)
        residual_after = _remove_piston_phase(
            np.where(pupil_mask, atm - dm_after, np.nan),
            pupil_mask,
        )

        hist["rms_atmosphere"].append(_masked_rms(atm, pupil_mask))
        hist["rms_before"].append(_masked_rms(residual_before, pupil_mask))
        hist["rms_after"].append(_masked_rms(residual_after, pupil_mask))
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
    try:
        return _wavefront.remove_piston(phase_rad, pupil_mask)
    except ValueError as exc:
        raise ClosedLoopError(str(exc)) from exc


def _phase_rms_to_opd_nm(
    phase_rad: np.ndarray,
    pupil_mask: np.ndarray,
    calibration: DetectorShwfsCalibration,
) -> float:
    try:
        opd_m = _wavefront.phase_to_opd(
            phase_rad,
            calibration.geometry.wfs_wavelength_m,
        )
        return float(_wavefront.masked_rms(opd_m, pupil_mask) * NM_PER_M)
    except ValueError as exc:
        raise ClosedLoopError(str(exc)) from exc


def _masked_rms(values: np.ndarray, pupil_mask: np.ndarray) -> float:
    try:
        rms_value = _wavefront.masked_rms(values, pupil_mask)
    except ValueError as exc:
        raise ClosedLoopError(str(exc)) from exc
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
        "command_rms_nm": history.command_rms_nm,
        "command_l2_norm_nm": history.command_l2_norm_nm,
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
    required_units = {
        "residual_opd_rms",
        "command_rms_nm",
        "command_l2_norm_nm",
        "valid_centroid_frac",
        "latency_ms",
    }
    missing = required_units - set(history.units)
    if missing:
        raise ClosedLoopError(f"LoopHistory units missing keys: {sorted(missing)}.")


def _loop_settings(
    calibration: DetectorShwfsCalibration,
    dm_model: DMModel,
    poke_result: PokeMtxResult,
    config: DetectorLoopConfig,
    phase_sequence: np.ndarray,
) -> dict[str, Any]:
    return {
        "hash_schema": 2,
        "method": "detector_level_tsvd_integrator",
        "phase_sequence": phase_sequence,
        "geometry": calibration.geometry.__dict__,
        "detector": calibration.detector.__dict__,
        "centroid_validity": DEFAULT_CENTROID_VALIDITY.__dict__,
        "calibration_state": {
            "x_m": calibration.x_m,
            "y_m": calibration.y_m,
            "pupil_mask": calibration.pupil_mask,
            "centers_m": calibration.centers_m,
            "subaperture_masks": np.asarray(calibration.subaperture_masks, dtype=bool),
            "reference_centroids_px": calibration.reference_centroids_px,
        },
        "dm": {
            "config": dm_model.config.__dict__,
            "actuator_pitch_m": float(dm_model.actuator_pitch_m),
            "x_m": dm_model.x_m,
            "y_m": dm_model.y_m,
            "pupil_mask": dm_model.pupil_mask,
            "actuator_centers_m": dm_model.actuator_centers_m,
            "influence_functions": dm_model.influence_functions,
            "dead_actuator_mask": dm_model.dead_actuator_mask,
            "stuck_actuator_mask": dm_model.stuck_actuator_mask,
        },
        "poke_config_hash": poke_result.config_hash,
        "poke_state": {
            "poke_matrix": poke_result.poke_matrix,
            "singular_values": poke_result.singular_values,
            "controlled_actuator_indices": poke_result.controlled_actuator_indices,
            "valid_subaperture_mask": poke_result.valid_subaperture_mask,
            "row_valid": poke_result.row_valid,
            "rcond": float(poke_result.rcond),
            "kept_modes": int(poke_result.kept_modes),
        },
        "loop_config": config.__dict__,
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
        return stable_array_descriptor(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def _assert_masked_finite(values: np.ndarray, pupil_mask: np.ndarray, label: str) -> None:
    try:
        _wavefront.validate_masked_finite(values, pupil_mask, label)
    except ValueError as exc:
        raise ClosedLoopError(str(exc)) from exc


def _assert_all_finite(values: np.ndarray, label: str) -> None:
    array = np.asarray(values, dtype=float)
    if not np.all(np.isfinite(array)):
        finite_frac = float(np.mean(np.isfinite(array))) if array.size else 0.0
        raise ClosedLoopError(f"Non-finite values in {label}; finite_frac={finite_frac:.3f}.")


def _require_positive(field_name: str, value: float) -> None:
    _require_finite(field_name, value)
    if float(value) <= 0.0:
        raise ClosedLoopError(f"{field_name} must be positive; got {value!r}.")


def _loop_provenance(source_class: str, source_note: str) -> _Provenance:
    """Build canonical provenance while retaining legacy loop errors."""

    try:
        return _Provenance(source_class=source_class, source_note=str(source_note))
    except (TypeError, ValueError) as exc:
        if source_class not in ALLOWED_SOURCE_CLASSES:
            raise ClosedLoopError(
                f"source_class={source_class!r} is not in the permitted taxonomy "
                f"{sorted(ALLOWED_SOURCE_CLASSES)}."
            ) from exc
        raise ClosedLoopError("source_note must be a non-empty string.") from exc


def _require_nonnegative(field_name: str, value: float) -> None:
    _require_finite(field_name, value)
    if float(value) < 0.0:
        raise ClosedLoopError(f"{field_name} must be non-negative; got {value!r}.")


def _require_integer(field_name: str, value: int, minimum: int) -> None:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise ClosedLoopError(f"{field_name} must be an integer; got {value!r}.")
    if int(value) < int(minimum):
        raise ClosedLoopError(f"{field_name} must be >= {minimum}; got {value!r}.")


def _require_finite(field_name: str, value: float) -> None:
    if not math.isfinite(float(value)):
        raise ClosedLoopError(f"{field_name} must be finite; got {value!r}.")
