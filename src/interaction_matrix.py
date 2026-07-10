# Detector-level DM poke matrices use central-difference calibration, finite SVD diagnostics, TSVD reconstruction, and rcond scan metadata.

"""Detector-level DM interaction matrices for the realistic 2 m SCAO demo.

The matrix built here maps controlled DM actuator commands in
``nm_OPD_equivalent`` to detector-level Shack-Hartmann centroid shifts in
pixels. It is intentionally generated from the detector calibration and
synthetic DM model, rather than from the older geometric notebook 09
response-matrix path.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import math
from typing import Any, Sequence

import numpy as np

from data_sources import ALLOWED_SOURCE_CLASSES
from dm_model import DMModel, actuator_metadata, synthesize_dm_phase_rad
from synthetic_instrument_data import DetectorMeasurement, DetectorShwfsCalibration, measure_detector_shwfs


DEFAULT_POKE_SOURCE_CLASS = "synthetic_assumed"
DEFAULT_POKE_SOURCE_NOTE = (
    "Synthetic detector-level DM poke calibration constructed by central "
    "difference from the local detector model and synthetic DM model."
)
DEFAULT_RCOND_SCAN_GRID = (1.0e-6, 3.0e-6, 1.0e-5, 3.0e-5, 1.0e-4, 3.0e-4, 1.0e-3, 3.0e-3, 1.0e-2)
# Central-difference poke amplitudes (nm OPD-equivalent) scanned to show
# how calibration amplitude affects the singular spectrum and reconstruction.
DEFAULT_POKE_AMPLITUDE_GRID_NM = (2.0, 5.0, 10.0, 20.0, 50.0)
DEFAULT_TARGET_KEPT_FRACTION = 0.90
DEFAULT_NUMERIC_RANK_RTOL = 1.0e-12


class InteractionMatrixError(ValueError):
    """Raised when a interaction matrix or reconstruction is invalid."""


@dataclass(frozen=True)
class PokeMatrixConfig:
    """Configuration for detector-level DM poke-matrix calibration.

    Args:
        calibration_amplitude_nm: Central-difference actuator command in
            nanometres OPD equivalent.
        rcond_scan_grid: Fresh TSVD cutoff grid. These values are scanned
            against the current matrix and are not copied from notebook 09.
        target_kept_mode_fraction: Fraction of numerically nonzero singular
            modes to retain when choosing the default ``rcond`` from the grid.
        minimum_kept_modes: Lower bound for the selected default TSVD mode
            count.
        controlled_actuator_indices: Optional explicit actuator indices. When
            omitted, dead and stuck actuators from the DM model are excluded.
        source_class: Provenance class from the documented source-class taxonomy.
        source_note: Human-readable source note.

    Returns:
        Immutable configuration object.

    Raises:
        InteractionMatrixError: If scalars or provenance tags are invalid.

    Physics note:
        The returned matrix has units ``detector px / nm_OPD_equivalent`` at
        the WFS wavelength stored in the detector calibration.
    """

    calibration_amplitude_nm: float = 10.0
    rcond_scan_grid: tuple[float, ...] = DEFAULT_RCOND_SCAN_GRID
    target_kept_mode_fraction: float = DEFAULT_TARGET_KEPT_FRACTION
    minimum_kept_modes: int = 1
    controlled_actuator_indices: tuple[int, ...] | None = None
    source_class: str = DEFAULT_POKE_SOURCE_CLASS
    source_note: str = DEFAULT_POKE_SOURCE_NOTE

    def __post_init__(self) -> None:
        _require_positive("calibration_amplitude_nm", self.calibration_amplitude_nm)
        if not self.rcond_scan_grid:
            raise InteractionMatrixError("rcond_scan_grid must contain at least one value.")
        for value in self.rcond_scan_grid:
            _require_rcond(value)
        if not (0.0 < float(self.target_kept_mode_fraction) <= 1.0):
            raise InteractionMatrixError("target_kept_mode_fraction must be in (0, 1].")
        if int(self.minimum_kept_modes) < 1:
            raise InteractionMatrixError("minimum_kept_modes must be >= 1.")
        if self.controlled_actuator_indices is not None and len(set(self.controlled_actuator_indices)) != len(
            self.controlled_actuator_indices
        ):
            raise InteractionMatrixError("controlled_actuator_indices must be unique.")
        if self.source_class not in ALLOWED_SOURCE_CLASSES:
            raise InteractionMatrixError(
                f"source_class={self.source_class!r} is not in the permitted taxonomy "
                f"{sorted(ALLOWED_SOURCE_CLASSES)}."
            )
        if not str(self.source_note).strip():
            raise InteractionMatrixError("source_note must be a non-empty string.")


@dataclass(frozen=True)
class PokeMtxResult:
    """Detector-level DM poke-matrix result.

    Required shared fields are ``poke_matrix``, ``singular_values``,
    ``kept_modes``, ``rcond``, and ``source_class``.

    Args:
        poke_matrix: Matrix with shape ``(2*N_valid, N_controlled_act)`` and
            units of detector pixels per nm OPD-equivalent command.
        singular_values: Singular values of the finite poke matrix.
        kept_modes: Number of singular modes retained by the selected
            matrix-specific TSVD cutoff.
        rcond: Selected TSVD relative cutoff from the scan grid.
        source_class: Provenance class for the synthetic matrix.
        rank: Numerical matrix rank from finite singular values.
        calibration_amplitude_nm: Central-difference poke amplitude.
        controlled_actuator_indices: DM actuator indices represented by the
            matrix columns.
        valid_subaperture_mask: Lenslets retained after finite-centroid checks
            across all pokes.
        row_valid: Finite row mask for ``poke_matrix``.
        condition_proxy: ``max(S)/min(nonzero S)`` diagnostic.
        config_hash: Hash of geometry, detector, DM, and calibration settings.
        calibration_settings: JSON-serializable settings used to build the
            matrix.
        rcond_grid: Relative cutoff values scanned for this matrix.
        rcond_scan_summary: JSON-serializable kept-mode summary for the grid.
        source_note: Human-readable provenance note.

    Returns:
        Immutable result object consumed by reconstruction and notebook 11.

    Raises:
        InteractionMatrixError: Built only after shape, finite-value, and SVD
            checks pass.

    Physics note:
        The matrix is calibrated at ``wfs_wavelength_m``. Commands remain OPD
        nanometres; phase conversion is performed only during each poke.
    """

    poke_matrix: np.ndarray
    singular_values: np.ndarray
    kept_modes: int
    rcond: float
    source_class: str
    rank: int
    calibration_amplitude_nm: float
    controlled_actuator_indices: np.ndarray
    valid_subaperture_mask: np.ndarray
    row_valid: np.ndarray
    condition_proxy: float
    config_hash: str
    calibration_settings: dict[str, Any]
    rcond_grid: tuple[float, ...]
    rcond_scan_summary: tuple[dict[str, float | int], ...]
    source_note: str = DEFAULT_POKE_SOURCE_NOTE

    @property
    def n_valid_lenslets(self) -> int:
        return int(np.sum(self.valid_subaperture_mask))

    @property
    def n_controlled_actuators(self) -> int:
        return int(self.controlled_actuator_indices.size)


@dataclass(frozen=True)
class TSVDReconstructionResult:
    """TSVD command reconstruction from detector centroid measurements."""

    commands_nm: np.ndarray
    reconstructed_signal_px: np.ndarray
    residual_px: np.ndarray
    kept_modes: int
    rcond: float
    singular_values: np.ndarray
    command_norm_nm: float
    residual_norm_px: float
    source_class: str


@dataclass(frozen=True)
class TikhonovReconstructionResult:
    """Tikhonov command reconstruction result for optional comparative studies."""

    commands_nm: np.ndarray
    reconstructed_signal_px: np.ndarray
    residual_px: np.ndarray
    alpha: float
    command_norm_nm: float
    residual_norm_px: float
    source_class: str


@dataclass(frozen=True)
class RcondScanResult:
    """Fresh TSVD rcond scan for one detector-level response matrix."""

    rcond_values: np.ndarray
    kept_modes: np.ndarray
    command_norms_nm: np.ndarray
    residual_norms_px: np.ndarray
    source_class: str


def build_detector_dm_poke_matrix(
    calibration: DetectorShwfsCalibration,
    dm_model: DMModel,
    config: PokeMatrixConfig | None = None,
) -> PokeMtxResult:
    """Build a detector-level DM-WFS interaction matrix by central difference.

    Args:
        calibration: detector SH-WFS reference calibration.
        dm_model: synthetic DM sampled on the same pupil grid.
        config: Optional poke-matrix calibration settings.

    Returns:
        :class:`PokeMtxResult` with finite SVD diagnostics and a selected
        matrix-specific TSVD cutoff.

    Raises:
        InteractionMatrixError: If grids mismatch, centroid rows are invalid,
            SVD fails, or non-finite values appear.

    Physics note:
        Each controlled actuator is poked by ``+/-calibration_amplitude_nm``
        OPD equivalent. The synthesized DM OPD is converted to phase at the
        WFS wavelength before detector centroiding.
    """

    config = config or PokeMatrixConfig()
    _validate_dm_calibration_grid(calibration, dm_model)
    if config.calibration_amplitude_nm > dm_model.config.stroke_limit_nm:
        raise InteractionMatrixError(
            "calibration_amplitude_nm exceeds DM stroke_limit_nm; central-difference pokes would be clipped."
        )

    controlled = _controlled_actuator_indices(dm_model, config.controlled_actuator_indices)
    if controlled.size == 0:
        raise InteractionMatrixError("No controlled actuators are available for the poke matrix.")

    response_cube = np.empty((calibration.n_valid_subapertures, 2, controlled.size), dtype=float)
    finite_lenslets = np.ones((calibration.n_valid_subapertures, controlled.size), dtype=bool)
    amp = float(config.calibration_amplitude_nm)

    for col, actuator_index in enumerate(controlled):
        command_p = np.zeros(dm_model.n_actuators, dtype=float)
        command_m = np.zeros(dm_model.n_actuators, dtype=float)
        command_p[int(actuator_index)] = amp
        command_m[int(actuator_index)] = -amp
        phase_p, _ = synthesize_dm_phase_rad(
            command_p,
            dm_model,
            wavelength_m=calibration.geometry.wfs_wavelength_m,
            remove_piston=True,
        )
        phase_m, _ = synthesize_dm_phase_rad(
            command_m,
            dm_model,
            wavelength_m=calibration.geometry.wfs_wavelength_m,
            remove_piston=True,
        )
        measurement_p = measure_detector_shwfs(phase_p, calibration, include_noise=False)
        measurement_m = measure_detector_shwfs(phase_m, calibration, include_noise=False)
        diff_px_per_nm = (measurement_p.shifts_px - measurement_m.shifts_px) / (2.0 * amp)
        finite_lenslets[:, col] = (
            measurement_p.valid
            & measurement_m.valid
            & np.all(np.isfinite(diff_px_per_nm), axis=1)
        )
        response_cube[:, :, col] = diff_px_per_nm

    valid_subapertures = np.all(finite_lenslets, axis=1)
    if not np.any(valid_subapertures):
        raise InteractionMatrixError("No lenslets remained valid across all DM pokes.")

    poke_matrix = response_cube[valid_subapertures, :, :].reshape(-1, controlled.size)
    _assert_all_finite(poke_matrix, "detector DM poke matrix")
    if np.any(np.all(~np.isfinite(poke_matrix), axis=0)):
        raise InteractionMatrixError("At least one poke-matrix column is all NaN.")
    if np.any(np.all(np.abs(poke_matrix) == 0.0, axis=0)):
        zero_cols = np.flatnonzero(np.all(np.abs(poke_matrix) == 0.0, axis=0)).astype(int).tolist()
        raise InteractionMatrixError(f"Zero-response actuator columns are not controllable: columns={zero_cols}.")

    singular_values = _finite_singular_values(poke_matrix)
    rank = _numerical_rank(singular_values, poke_matrix.shape)
    if rank < 1:
        raise InteractionMatrixError("Poke matrix has zero numerical rank.")
    rcond = choose_rcond_from_singular_values(
        singular_values,
        config.rcond_scan_grid,
        target_kept_mode_fraction=config.target_kept_mode_fraction,
        minimum_kept_modes=config.minimum_kept_modes,
    )
    kept_modes = kept_modes_for_rcond(singular_values, rcond)
    condition_proxy = _condition_proxy(singular_values)
    settings = _calibration_settings(calibration, dm_model, config, controlled, valid_subapertures)
    scan_summary = tuple(
        {"rcond": float(value), "kept_modes": int(kept_modes_for_rcond(singular_values, value))}
        for value in config.rcond_scan_grid
    )

    row_valid = np.all(np.isfinite(poke_matrix), axis=1)
    return PokeMtxResult(
        poke_matrix=poke_matrix,
        singular_values=singular_values,
        kept_modes=kept_modes,
        rcond=rcond,
        source_class=config.source_class,
        rank=rank,
        calibration_amplitude_nm=amp,
        controlled_actuator_indices=controlled.copy(),
        valid_subaperture_mask=valid_subapertures.copy(),
        row_valid=row_valid,
        condition_proxy=condition_proxy,
        config_hash=_config_hash(settings),
        calibration_settings=settings,
        rcond_grid=tuple(float(v) for v in config.rcond_scan_grid),
        rcond_scan_summary=scan_summary,
        source_note=config.source_note,
    )


def kept_modes_for_rcond(singular_values: Sequence[float], rcond: float) -> int:
    """Count singular values retained by a relative TSVD cutoff."""

    _require_rcond(rcond)
    values = _validate_singular_values(singular_values)
    if values.size == 0 or values[0] <= 0:
        return 0
    return int(np.sum(values >= float(rcond) * values[0]))


def noise_amplification_proxy(singular_values: Sequence[float], rcond: float) -> float:
    """Return the TSVD noise-amplification proxy for a relative cutoff.

    Args:
        singular_values: Non-negative descending singular values of the poke
            matrix (units detector px / nm_OPD_equivalent).
        rcond: Relative TSVD cutoff applied to ``singular_values``.

    Returns:
        ``sqrt(sum_{i in kept} (1 / sigma_i)**2)`` over the retained modes, or
        ``0.0`` when no modes are kept.

    Physics note:
        White measurement noise of unit RMS maps to reconstructed-command
        variance scaled by ``sum (1/sigma_i)**2`` over kept modes; this is the
        squared Frobenius norm of the TSVD pseudo-inverse. The square root is a
        single proxy for how aggressively the reconstructor amplifies sensor
        noise, and it grows sharply as weak singular directions are retained at
        small ``rcond``.
    """

    values = _validate_singular_values(singular_values)
    kept = kept_modes_for_rcond(values, rcond)
    if kept < 1:
        return 0.0
    return float(np.sqrt(np.sum((1.0 / values[:kept]) ** 2)))


def choose_rcond_from_singular_values(
    singular_values: Sequence[float],
    rcond_grid: Sequence[float],
    target_kept_mode_fraction: float = DEFAULT_TARGET_KEPT_FRACTION,
    minimum_kept_modes: int = 1,
) -> float:
    """Choose a matrix-specific TSVD rcond from a fresh scan grid.

    The rule is deliberately simple: estimate the numerical rank, retain at
    least ``target_kept_mode_fraction`` of that rank, and choose the largest
    scanned cutoff that satisfies the target. This documents a fresh choice
    for the current detector-level matrix instead of copying notebook 09.
    """

    values = _validate_singular_values(singular_values)
    if not rcond_grid:
        raise InteractionMatrixError("rcond_grid must contain at least one value.")
    for value in rcond_grid:
        _require_rcond(value)
    if not (0.0 < float(target_kept_mode_fraction) <= 1.0):
        raise InteractionMatrixError("target_kept_mode_fraction must be in (0, 1].")
    if int(minimum_kept_modes) < 1:
        raise InteractionMatrixError("minimum_kept_modes must be >= 1.")

    rank = _numerical_rank(values, (values.size, values.size))
    if rank < 1:
        raise InteractionMatrixError("Cannot choose rcond for a zero-rank matrix.")
    target_modes = max(int(minimum_kept_modes), int(math.ceil(float(target_kept_mode_fraction) * rank)))
    candidates = [
        float(value)
        for value in sorted(float(v) for v in rcond_grid)
        if kept_modes_for_rcond(values, value) >= target_modes
    ]
    if candidates:
        return float(max(candidates))
    return float(min(float(v) for v in rcond_grid))


def vectorize_detector_measurement(
    measurement: DetectorMeasurement,
    poke_result: PokeMtxResult,
) -> np.ndarray:
    """Vectorize detector centroid shifts using the poke-matrix valid rows."""

    shifts = np.asarray(measurement.shifts_px, dtype=float)
    valid_mask = np.asarray(poke_result.valid_subaperture_mask, dtype=bool)
    if shifts.ndim != 2 or shifts.shape[1] != 2:
        raise InteractionMatrixError(f"measurement.shifts_px must have shape (N, 2); got {shifts.shape}.")
    if shifts.shape[0] != valid_mask.size:
        raise InteractionMatrixError(
            f"measurement lenslet count {shifts.shape[0]} does not match poke-result mask length {valid_mask.size}."
        )
    vector = shifts[valid_mask, :].reshape(-1)
    if vector.size != poke_result.poke_matrix.shape[0]:
        raise InteractionMatrixError("Vectorized measurement length does not match poke-matrix row count.")
    return vector


def tsvd_reconstruct_commands(
    measurement_vector_px: Sequence[float],
    poke_result: PokeMtxResult,
    rcond: float | None = None,
) -> TSVDReconstructionResult:
    """Reconstruct controlled DM command increments with the TSVD matrix."""

    cutoff = poke_result.rcond if rcond is None else float(rcond)
    _require_rcond(cutoff)
    signal, matrix, row_mask = _finite_lstsq_system(measurement_vector_px, poke_result.poke_matrix)
    U, singular_values, Vt = np.linalg.svd(matrix, full_matrices=False)
    singular_values = _validate_singular_values(singular_values)
    kept = kept_modes_for_rcond(singular_values, cutoff)
    if kept < 1:
        commands = np.zeros(matrix.shape[1], dtype=float)
    else:
        inv_s = np.zeros_like(singular_values)
        inv_s[:kept] = 1.0 / singular_values[:kept]
        commands = Vt.T @ (inv_s * (U.T @ signal))
    _assert_all_finite(commands, "TSVD reconstructed commands")

    full_reconstructed = np.zeros(poke_result.poke_matrix.shape[0], dtype=float)
    full_reconstructed[row_mask] = matrix @ commands
    full_signal = np.asarray(measurement_vector_px, dtype=float).reshape(-1)
    residual = full_signal - full_reconstructed
    _assert_all_finite(residual[row_mask], "TSVD finite-row residual")
    return TSVDReconstructionResult(
        commands_nm=commands,
        reconstructed_signal_px=full_reconstructed,
        residual_px=residual,
        kept_modes=kept,
        rcond=cutoff,
        singular_values=singular_values,
        command_norm_nm=float(np.linalg.norm(commands)),
        residual_norm_px=float(np.linalg.norm(residual[row_mask])),
        source_class=poke_result.source_class,
    )


def tikhonov_reconstruct_commands(
    measurement_vector_px: Sequence[float],
    poke_result: PokeMtxResult,
    alpha: float,
) -> TikhonovReconstructionResult:
    """Optional Tikhonov reconstructor for comparative studies."""

    _require_nonnegative("alpha", alpha)
    signal, matrix, row_mask = _finite_lstsq_system(measurement_vector_px, poke_result.poke_matrix)
    if float(alpha) == 0.0:
        commands, *_ = np.linalg.lstsq(matrix, signal, rcond=None)
    else:
        lhs = matrix.T @ matrix + float(alpha) ** 2 * np.eye(matrix.shape[1])
        rhs = matrix.T @ signal
        commands = np.linalg.solve(lhs, rhs)
    _assert_all_finite(commands, "Tikhonov reconstructed commands")

    full_reconstructed = np.zeros(poke_result.poke_matrix.shape[0], dtype=float)
    full_reconstructed[row_mask] = matrix @ commands
    full_signal = np.asarray(measurement_vector_px, dtype=float).reshape(-1)
    residual = full_signal - full_reconstructed
    _assert_all_finite(residual[row_mask], "Tikhonov finite-row residual")
    return TikhonovReconstructionResult(
        commands_nm=commands,
        reconstructed_signal_px=full_reconstructed,
        residual_px=residual,
        alpha=float(alpha),
        command_norm_nm=float(np.linalg.norm(commands)),
        residual_norm_px=float(np.linalg.norm(residual[row_mask])),
        source_class=poke_result.source_class,
    )


def scan_tsvd_rcond(
    measurement_vector_px: Sequence[float],
    poke_result: PokeMtxResult,
    rcond_values: Sequence[float] | None = None,
) -> RcondScanResult:
    """Run a fresh TSVD rcond scan for one response matrix and measurement."""

    values = tuple(poke_result.rcond_grid if rcond_values is None else rcond_values)
    if not values:
        raise InteractionMatrixError("rcond_values must contain at least one value.")
    rows = []
    for value in values:
        result = tsvd_reconstruct_commands(measurement_vector_px, poke_result, rcond=float(value))
        rows.append(
            (
                float(value),
                int(result.kept_modes),
                float(result.command_norm_nm),
                float(result.residual_norm_px),
            )
        )
    arr = np.asarray(rows, dtype=float)
    _assert_all_finite(arr, "TSVD rcond scan")
    return RcondScanResult(
        rcond_values=arr[:, 0],
        kept_modes=arr[:, 1].astype(int),
        command_norms_nm=arr[:, 2],
        residual_norms_px=arr[:, 3],
        source_class=poke_result.source_class,
    )


def poke_amplitude_scan(
    calibration: DetectorShwfsCalibration,
    dm_model: DMModel,
    amplitudes_nm: Sequence[float] = DEFAULT_POKE_AMPLITUDE_GRID_NM,
    base_config: PokeMatrixConfig | None = None,
) -> list[dict[str, Any]]:
    """Scan central-difference poke amplitude and report conditioning diagnostics.

    Args:
        calibration: detector SH-WFS reference calibration.
        dm_model: synthetic DM sampled on the same pupil grid.
        amplitudes_nm: Central-difference poke amplitudes in nm OPD-equivalent.
        base_config: Optional template poke configuration whose rcond grid and
            controlled-actuator settings are reused; only the calibration
            amplitude is overridden per scan point.

    Returns:
        One JSON-serializable row per amplitude with the singular-spectrum
        extremes, selected rcond, kept modes, condition proxy, and TSVD
        noise-amplification proxy.

    Raises:
        InteractionMatrixError: If no amplitudes are supplied or a poke matrix
            cannot be built (e.g. amplitude exceeds the DM stroke limit).

    Physics note:
        The poke matrix is linear in calibration amplitude, so its singular
        values scale with amplitude while the condition number and selected rcond
        are amplitude-invariant in the noise-free limit; this scan exposes how
        amplitude trades raw centroid signal against reconstruction sensitivity.
    """

    template = base_config or PokeMatrixConfig()
    amplitudes = tuple(float(value) for value in amplitudes_nm)
    if not amplitudes:
        raise InteractionMatrixError("poke_amplitude_scan requires at least one amplitude.")
    rows: list[dict[str, Any]] = []
    for amplitude in amplitudes:
        config = replace(template, calibration_amplitude_nm=amplitude)
        poke = build_detector_dm_poke_matrix(calibration, dm_model, config)
        rows.append(
            {
                "calibration_amplitude_nm": amplitude,
                "kept_modes": int(poke.kept_modes),
                "rcond": float(poke.rcond),
                "rank": int(poke.rank),
                "largest_singular_value_px_per_nm": float(poke.singular_values[0]),
                "smallest_singular_value_px_per_nm": float(poke.singular_values[-1]),
                "condition_proxy": float(poke.condition_proxy),
                "noise_amplification_proxy": noise_amplification_proxy(poke.singular_values, poke.rcond),
                "matrix_unit": "detector_px / nm_OPD_equivalent",
                "source_class": poke.source_class,
            }
        )
    return rows


def poke_matrix_summary(poke_result: PokeMtxResult) -> dict[str, Any]:
    """Return JSON-serializable poke-matrix diagnostics."""

    return {
        "matrix_shape": list(poke_result.poke_matrix.shape),
        "rank": int(poke_result.rank),
        "singular_value_count": int(poke_result.singular_values.size),
        "largest_singular_value": float(poke_result.singular_values[0]),
        "smallest_singular_value": float(poke_result.singular_values[-1]),
        "condition_proxy": float(poke_result.condition_proxy),
        "noise_amplification_proxy": noise_amplification_proxy(
            poke_result.singular_values, poke_result.rcond
        ),
        "matrix_unit": "detector_px / nm_OPD_equivalent",
        "kept_modes": int(poke_result.kept_modes),
        "rcond": float(poke_result.rcond),
        "calibration_amplitude_nm": float(poke_result.calibration_amplitude_nm),
        "n_valid_lenslets": int(poke_result.n_valid_lenslets),
        "n_controlled_actuators": int(poke_result.n_controlled_actuators),
        "source_class": poke_result.source_class,
        "config_hash": poke_result.config_hash,
    }


def expand_controlled_commands(commands_nm: Sequence[float], poke_result: PokeMtxResult, dm_model: DMModel) -> np.ndarray:
    """Expand controlled-actuator commands into a full DM command vector."""

    commands = np.asarray(commands_nm, dtype=float).reshape(-1)
    if commands.shape != (poke_result.n_controlled_actuators,):
        raise InteractionMatrixError(
            f"commands length {commands.size} != n_controlled_actuators {poke_result.n_controlled_actuators}."
        )
    if dm_model.n_actuators <= int(np.max(poke_result.controlled_actuator_indices, initial=-1)):
        raise InteractionMatrixError("poke_result controlled indices exceed the supplied DM model actuator count.")
    _assert_all_finite(commands, "controlled command vector")
    full = np.zeros(dm_model.n_actuators, dtype=float)
    full[poke_result.controlled_actuator_indices] = commands
    return full


def _validate_dm_calibration_grid(calibration: DetectorShwfsCalibration, dm_model: DMModel) -> None:
    if calibration.x_m.shape != dm_model.x_m.shape:
        raise InteractionMatrixError(
            f"Calibration grid shape {calibration.x_m.shape} != DM grid shape {dm_model.x_m.shape}."
        )
    if not np.allclose(calibration.x_m, dm_model.x_m) or not np.allclose(calibration.y_m, dm_model.y_m):
        raise InteractionMatrixError("Calibration and DM grids are not sampled on the same coordinates.")
    if not np.array_equal(calibration.pupil_mask, dm_model.pupil_mask):
        raise InteractionMatrixError("Calibration and DM pupil masks differ.")


def _controlled_actuator_indices(dm_model: DMModel, explicit: tuple[int, ...] | None) -> np.ndarray:
    if explicit is None:
        mask = ~(dm_model.dead_actuator_mask | dm_model.stuck_actuator_mask)
        return np.flatnonzero(mask).astype(int)
    indices = np.asarray(explicit, dtype=int)
    if indices.ndim != 1:
        raise InteractionMatrixError("controlled_actuator_indices must be one-dimensional.")
    if indices.size and (np.min(indices) < 0 or np.max(indices) >= dm_model.n_actuators):
        raise InteractionMatrixError("controlled_actuator_indices contains an out-of-range actuator index.")
    if np.any(dm_model.dead_actuator_mask[indices]) or np.any(dm_model.stuck_actuator_mask[indices]):
        raise InteractionMatrixError("controlled_actuator_indices must not include dead or stuck actuators.")
    return indices


def _finite_lstsq_system(signal: Sequence[float], response_matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    s = np.asarray(signal, dtype=float).reshape(-1)
    matrix = np.asarray(response_matrix, dtype=float)
    if matrix.ndim != 2:
        raise InteractionMatrixError("response_matrix must be 2-D.")
    if matrix.shape[0] != s.size:
        raise InteractionMatrixError(
            f"Measurement vector length {s.size} does not match response-matrix row count {matrix.shape[0]}."
        )
    row_mask = np.isfinite(s) & np.all(np.isfinite(matrix), axis=1)
    if not np.any(row_mask):
        raise InteractionMatrixError("No finite rows are available for reconstruction.")
    return s[row_mask], matrix[row_mask], row_mask


def _finite_singular_values(matrix: np.ndarray) -> np.ndarray:
    _assert_all_finite(matrix, "matrix before SVD")
    try:
        singular_values = np.linalg.svd(matrix, compute_uv=False)
    except np.linalg.LinAlgError as exc:
        raise InteractionMatrixError("SVD failed for the detector DM poke matrix.") from exc
    return _validate_singular_values(singular_values)


def _validate_singular_values(singular_values: Sequence[float]) -> np.ndarray:
    values = np.asarray(singular_values, dtype=float).reshape(-1)
    _assert_all_finite(values, "SVD singular values")
    if np.any(values < -1.0e-14):
        raise InteractionMatrixError("SVD singular values must be non-negative.")
    values = np.maximum(values, 0.0)
    if values.size and np.any(np.diff(values) > max(values[0], 1.0) * 1.0e-10):
        raise InteractionMatrixError("SVD singular values are not sorted in descending order.")
    return values


def _numerical_rank(singular_values: Sequence[float], matrix_shape: tuple[int, int]) -> int:
    values = _validate_singular_values(singular_values)
    if values.size == 0:
        return 0
    tol = DEFAULT_NUMERIC_RANK_RTOL * max(matrix_shape) * float(values[0])
    return int(np.sum(values > tol))


def _condition_proxy(singular_values: Sequence[float]) -> float:
    values = _validate_singular_values(singular_values)
    positive = values[values > 0.0]
    if positive.size == 0:
        return float("inf")
    return float(positive[0] / positive[-1])


def _calibration_settings(
    calibration: DetectorShwfsCalibration,
    dm_model: DMModel,
    config: PokeMatrixConfig,
    controlled: np.ndarray,
    valid_subapertures: np.ndarray,
) -> dict[str, Any]:
    return {
        "method": "central_difference_detector_dm_poke",
        "matrix_units": "detector_px_per_nm_OPD_equivalent",
        "calibration_amplitude_nm": float(config.calibration_amplitude_nm),
        "wfs_wavelength_m": float(calibration.geometry.wfs_wavelength_m),
        "n_pupil_pixels": int(calibration.geometry.n_pupil_pixels),
        "n_lenslets": int(calibration.geometry.n_lenslets),
        "min_fill_fraction": float(calibration.geometry.min_fill_fraction),
        "pad_factor": int(calibration.geometry.pad_factor),
        "detector_window_px": (
            None if calibration.geometry.detector_window_px is None else int(calibration.geometry.detector_window_px)
        ),
        "valid_centroid_lenslets": int(np.sum(valid_subapertures)),
        "input_calibration_lenslets": int(calibration.n_valid_subapertures),
        "controlled_actuator_indices": controlled.astype(int).tolist(),
        "dm": actuator_metadata(dm_model),
        "rcond_scan_grid": [float(v) for v in config.rcond_scan_grid],
        "target_kept_mode_fraction": float(config.target_kept_mode_fraction),
        "minimum_kept_modes": int(config.minimum_kept_modes),
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


def _assert_all_finite(values: np.ndarray, label: str) -> None:
    array = np.asarray(values, dtype=float)
    if not np.all(np.isfinite(array)):
        finite_frac = float(np.mean(np.isfinite(array))) if array.size else 0.0
        raise InteractionMatrixError(f"Non-finite values in {label}; finite_frac={finite_frac:.3f}.")


def _require_positive(field_name: str, value: float) -> None:
    _require_finite(field_name, value)
    if float(value) <= 0.0:
        raise InteractionMatrixError(f"{field_name} must be positive; got {value!r}.")


def _require_nonnegative(field_name: str, value: float) -> None:
    _require_finite(field_name, value)
    if float(value) < 0.0:
        raise InteractionMatrixError(f"{field_name} must be non-negative; got {value!r}.")


def _require_rcond(value: float) -> None:
    _require_positive("rcond", value)
    if float(value) >= 1.0:
        raise InteractionMatrixError(f"rcond must be < 1; got {value!r}.")


def _require_finite(field_name: str, value: float) -> None:
    if not math.isfinite(float(value)):
        raise InteractionMatrixError(f"{field_name} must be finite; got {value!r}.")
