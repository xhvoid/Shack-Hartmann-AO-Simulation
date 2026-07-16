# DM model helpers create synthetic actuator masks, influence functions, stroke-clipped commands, dead/stuck actuator maps, and command-to-phase synthesis.

"""Synthetic deformable-mirror model for the realistic 2 m SCAO demo.

The model uses command units of nanometres OPD equivalent. This keeps stroke
limits and command maps explicit; conversion to phase in radians happens only
when a WFS or science wavelength is supplied.
"""

from __future__ import annotations

from dataclasses import dataclass, replace as _replace
from pathlib import Path
import json
import math
from typing import Any, Sequence

import numpy as np
from scipy import optimize

from ..backends.native.dm import (
    NativeDmBackend as _NativeDmBackend,
    NativeDmError as _NativeDmError,
    square_grid_actuator_layout as _square_grid_actuator_layout,
    square_grid_actuator_centers as _square_grid_actuator_centers,
)
from ..core import wavefront as _wavefront
from ..core.types import DmCommandVector as _DmCommandVector
from ..core.provenance import ALLOWED_SOURCE_CLASSES, Provenance as _Provenance
from ..dm import (
    DEFAULT_ACTUATOR_MARGIN_FRACTION,
    DEFAULT_DM_SOURCE_CLASS,
    DEFAULT_DM_SOURCE_NOTE,
    MIN_ACTUATORS_ACROSS,
    NM_TO_M,
    VALID_INFLUENCE_MODELS,
    DMConfig,
    DMConfigError as DMModelError,
    DeformableMirror as _DeformableMirror,
    DeformableMirrorError as _DeformableMirrorError,
    actuator_ids_from_grid_indices as _actuator_ids_from_grid_indices,
    build_native_deformable_mirror as _build_native_deformable_mirror,
)
from .runtime_resources import open_text_resource


PHASE_TWO_PI = 2.0 * math.pi


@dataclass(frozen=True)
class DMModel:
    """Synthetic deformable mirror sampled on a pupil grid.

    Args:
        config: DM configuration.
        x_m: X-coordinate grid in metres.
        y_m: Y-coordinate grid in metres.
        pupil_mask: Boolean pupil mask.
        actuator_centers_m: Active actuator center coordinates in metres.
        actuator_pitch_m: Actuator pitch in metres.
        influence_functions: Dimensionless OPD influence functions with one
            map per active actuator.
        dead_actuator_mask: Boolean mask for dead actuators.
        stuck_actuator_mask: Boolean mask for stuck actuators.

    Returns:
        Immutable DM model bundle.

    Raises:
        DMModelError: Built by ``build_dm_model`` after finite-value checks.

    Physics note:
        Influence functions are dimensionless and peak-normalized. Multiplying
        them by commands in nm OPD equivalent gives a DM OPD surface in nm.
    """

    config: DMConfig
    x_m: np.ndarray
    y_m: np.ndarray
    pupil_mask: np.ndarray
    actuator_centers_m: np.ndarray
    actuator_pitch_m: float
    influence_functions: np.ndarray
    dead_actuator_mask: np.ndarray
    stuck_actuator_mask: np.ndarray

    @property
    def n_actuators(self) -> int:
        return int(self.actuator_centers_m.shape[0])


@dataclass(frozen=True)
class DMSynthesisResult:
    """Result of synthesizing a DM surface from commands.

    Args:
        opd_nm: Piston-removed OPD surface in nanometres. Values outside the
            pupil are NaN.
        clipped_commands_nm: Command vector after stroke clipping and
            dead/stuck actuator handling.
        saturated_mask: Boolean actuator mask where pre-dead/stuck commands
            exceeded the stroke limit.
        saturation_fraction: Fraction of actuators clipped by stroke limit.
        dead_actuator_mask: Boolean dead-actuator mask.
        stuck_actuator_mask: Boolean stuck-actuator mask.

    Returns:
        Immutable DM synthesis diagnostics.

    Raises:
        DMModelError: Built by ``synthesize_dm_opd_nm`` after shape checks.

    Physics note:
        ``opd_nm`` is an optical path difference map, not phase. Use
        ``synthesize_dm_phase_rad`` for phase at a named wavelength.
    """

    opd_nm: np.ndarray
    clipped_commands_nm: np.ndarray
    saturated_mask: np.ndarray
    saturation_fraction: float
    dead_actuator_mask: np.ndarray
    stuck_actuator_mask: np.ndarray


@dataclass(frozen=True)
class DMFitResult:
    """Least-squares static fitting diagnostic for a synthetic DM.

    Args:
        target_opd_nm: Target OPD map in nanometres.
        fitted_opd_nm: DM-fitted OPD map in nanometres.
        residual_opd_nm: Piston-removed residual OPD map in nanometres.
        commands_nm: Stroke-clipped commands in nanometres OPD equivalent.
        residual_rms_nm: Residual RMS inside the pupil in nanometres.
        command_rms_nm: RMS of clipped commands in nanometres.
        rank: Least-squares matrix rank.
        singular_values: Singular values of the finite-pixel influence matrix.

    Returns:
        Immutable static-fitting diagnostic bundle.

    Raises:
        DMModelError: Built after finite-value checks.

    Physics note:
        This is a static fitting-floor helper for diagnostics, not a closed-loop
        controller or calibrated DM command optimizer.
    """

    target_opd_nm: np.ndarray
    fitted_opd_nm: np.ndarray
    residual_opd_nm: np.ndarray
    commands_nm: np.ndarray
    residual_rms_nm: float
    command_rms_nm: float
    rank: int
    singular_values: np.ndarray


def load_dm_config_from_json(path: str | Path) -> DMConfig:
    """Load a synthetic DM preset from JSON.

    Args:
        path: JSON file with ``data_kind=dm_preset`` and a ``parameters``
            object.

    Returns:
        :class:`DMConfig` with units/provenance preserved in source fields.

    Raises:
        DMModelError: If the preset has the wrong kind or invalid parameters.

    Physics note:
        The preset describes a synthetic DM geometry and stroke budget. It must
        not be presented as a measured interaction matrix or private
        calibration file.
    """

    with open_text_resource(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("data_kind") != "dm_preset":
        raise DMModelError(f"{path}: expected data_kind='dm_preset'.")
    params = payload.get("parameters")
    if not isinstance(params, dict):
        raise DMModelError(f"{path}: parameters must be an object.")
    return DMConfig(
        telescope_diameter_m=float(params.get("telescope_diameter_m", 2.0)),
        n_actuators_across=int(params.get("n_actuators_across", 11)),
        influence_model=str(params.get("influence_model", "gaussian")),
        coupling_width_pitch=float(params.get("coupling_width_pitch", 0.35)),
        stroke_limit_nm=float(params.get("stroke_limit_nm", 800.0)),
        include_edge_actuators=bool(params.get("include_edge_actuators", True)),
        actuator_margin_fraction=float(params.get("actuator_margin_fraction", DEFAULT_ACTUATOR_MARGIN_FRACTION)),
        dead_actuator_indices=tuple(int(v) for v in params.get("dead_actuator_indices", [])),
        stuck_actuator_indices=tuple(int(v) for v in params.get("stuck_actuator_indices", [])),
        stuck_command_nm=float(params.get("stuck_command_nm", 0.0)),
        source_class=str(payload.get("source_class", DEFAULT_DM_SOURCE_CLASS)),
        source_note=str(payload.get("source_note", DEFAULT_DM_SOURCE_NOTE)),
    )


def build_dm_model(
    x_m: np.ndarray,
    y_m: np.ndarray,
    pupil_mask: np.ndarray,
    config: DMConfig | None = None,
) -> DMModel:
    """Build a synthetic DM model sampled on a pupil grid.

    Args:
        x_m: X-coordinate grid in metres.
        y_m: Y-coordinate grid in metres.
        pupil_mask: Boolean pupil mask.
        config: Optional DM configuration.

    Returns:
        :class:`DMModel` containing actuator centers, masks, and influence
        functions.

    Raises:
        DMModelError: If grid shapes mismatch, no actuators are retained, or
        influence functions contain non-finite pupil values.

    Physics note:
        Actuator centers are generated on a square grid and retained inside the
        circular pupil plus optional margin. Influence functions are masked to
        the pupil and peak-normalized.
    """

    config = config or DMConfig()
    x = np.asarray(x_m, dtype=float)
    y = np.asarray(y_m, dtype=float)
    mask = np.asarray(pupil_mask, dtype=bool)
    if x.shape != y.shape or x.shape != mask.shape:
        raise DMModelError("x_m, y_m, and pupil_mask must have identical shapes.")
    _assert_all_finite(x, "x_m grid")
    _assert_all_finite(y, "y_m grid")

    # Retain the historical out-of-range error before entering the strict
    # canonical factory.  Placement itself is owned by the native backend.
    centers_m, _ = actuator_centers_on_pupil(config)
    _index_mask(config.dead_actuator_indices, len(centers_m), "dead_actuator_indices")
    _index_mask(config.stuck_actuator_indices, len(centers_m), "stuck_actuator_indices")
    try:
        canonical = _build_native_deformable_mirror(x, y, mask, config)
    except (_DeformableMirrorError, _NativeDmError, ValueError) as exc:
        raise DMModelError(str(exc)) from exc

    canonical_centers = canonical.actuator_centers_m
    canonical_pitch = canonical.actuator_pitch_m
    if canonical_centers is None or canonical_pitch is None:  # pragma: no cover
        raise DMModelError("Native DM construction did not expose actuator geometry.")
    influence_functions = np.asarray(canonical.influence_functions, dtype=float).copy()
    influence_functions[:, ~mask] = np.nan
    _assert_influence_functions_finite(influence_functions, mask)
    return DMModel(
        config=config,
        x_m=x,
        y_m=y,
        pupil_mask=mask,
        actuator_centers_m=np.asarray(canonical_centers, dtype=float).copy(),
        actuator_pitch_m=float(canonical_pitch),
        influence_functions=influence_functions,
        dead_actuator_mask=np.asarray(canonical.dead_actuator_mask, dtype=bool).copy(),
        stuck_actuator_mask=np.asarray(canonical.stuck_actuator_mask, dtype=bool).copy(),
    )


def actuator_centers_on_pupil(config: DMConfig) -> tuple[np.ndarray, float]:
    """Generate square-grid actuator centers retained inside the pupil.

    Args:
        config: DM configuration.

    Returns:
        ``(centers_m, pitch_m)`` where centers are metres and pitch is metres.

    Raises:
        DMModelError: If the actuator grid cannot be generated.

    Physics note:
        This is a nominal actuator layout. It is not an imported vendor DM map.
        The optional margin can retain guard actuators slightly outside the
        nominal pupil.
    """

    if not isinstance(config, DMConfig):
        raise DMModelError("config must be a DMConfig.")
    try:
        centers_m, pitch_m = _square_grid_actuator_centers(
            config.telescope_diameter_m,
            config.n_actuators_across,
            include_edge_actuators=config.include_edge_actuators,
            actuator_margin_fraction=config.actuator_margin_fraction,
        )
    except _NativeDmError as exc:
        raise DMModelError(str(exc)) from exc
    return np.asarray(centers_m, dtype=float).copy(), float(pitch_m)


def clip_commands_nm(commands_nm: Sequence[float], model: DMModel) -> tuple[np.ndarray, np.ndarray]:
    """Apply stroke clipping plus dead/stuck actuator rules.

    Args:
        commands_nm: Command vector in nm OPD equivalent.
        model: Synthetic DM model.

    Returns:
        ``(clipped_commands_nm, saturated_mask)``. Saturation is computed
        before dead/stuck actuator replacement.

    Raises:
        DMModelError: If command length or values are invalid.

    Physics note:
        Stroke clipping constrains requested actuator OPD commands. Dead
        actuators are forced to zero, and stuck actuators are forced to the
        configured stuck command.
    """

    commands = _validate_commands(commands_nm, model)
    canonical = _canonical_model(model)
    result = _canonical_synthesis(commands, canonical)
    return _legacy_applied_commands_nm(commands, model, result), np.asarray(
        result.saturated_mask,
        dtype=bool,
    ).copy()


def synthesize_dm_opd_nm(
    commands_nm: Sequence[float],
    model: DMModel,
    remove_piston: bool = True,
) -> DMSynthesisResult:
    """Synthesize a DM OPD surface from actuator commands.

    Args:
        commands_nm: Command vector in nm OPD equivalent.
        model: Synthetic DM model.
        remove_piston: Whether to remove piston inside the pupil.

    Returns:
        :class:`DMSynthesisResult` with OPD map and command diagnostics.

    Raises:
        DMModelError: If command shape is invalid or synthesized values become
        non-finite inside the pupil.

    Physics note:
        The returned ``opd_nm`` is an optical path difference map in
        nanometres. Pixels outside the pupil are NaN.
    """

    commands = _validate_commands(commands_nm, model)
    canonical = _canonical_model(model)
    canonical_result = _canonical_synthesis(commands, canonical)
    clipped = _legacy_applied_commands_nm(commands, model, canonical_result)
    saturated = np.asarray(canonical_result.saturated_mask, dtype=bool).copy()
    opd_full_nm = np.asarray(canonical_result.correction_opd_m, dtype=float) / NM_TO_M
    opd_nm = np.where(np.asarray(model.pupil_mask, dtype=bool), opd_full_nm, np.nan)
    if remove_piston:
        try:
            opd_nm = _wavefront.remove_piston(opd_nm, model.pupil_mask)
        except ValueError as exc:
            raise DMModelError(str(exc)) from exc
    _assert_masked_finite(opd_nm, model.pupil_mask, "DM OPD surface")
    return DMSynthesisResult(
        opd_nm=opd_nm,
        clipped_commands_nm=clipped,
        saturated_mask=saturated,
        saturation_fraction=float(np.mean(saturated)) if saturated.size else 0.0,
        dead_actuator_mask=model.dead_actuator_mask.copy(),
        stuck_actuator_mask=model.stuck_actuator_mask.copy(),
    )


def synthesize_dm_phase_rad(
    commands_nm: Sequence[float],
    model: DMModel,
    wavelength_m: float,
    remove_piston: bool = True,
) -> tuple[np.ndarray, DMSynthesisResult]:
    """Synthesize a DM phase surface from actuator commands.

    Args:
        commands_nm: Command vector in nm OPD equivalent.
        model: Synthetic DM model.
        wavelength_m: Wavelength in metres for OPD-to-phase conversion.
        remove_piston: Whether to remove piston in OPD before phase conversion.

    Returns:
        ``(phase_rad, synthesis_result)``. ``phase_rad`` is radians at
        ``wavelength_m`` with NaN outside the pupil.

    Raises:
        DMModelError: If wavelength is non-positive or command synthesis fails.

    Physics note:
        Uses ``phase_rad = 2*pi*OPD_nm*1e-9/lambda_m``. Do not compare this
        phase directly across wavelengths without converting through OPD.
    """

    _require_positive("wavelength_m", wavelength_m)
    result = synthesize_dm_opd_nm(commands_nm, model, remove_piston=remove_piston)
    # Unit assertion: phase_rad is radians at wavelength_m.
    phase_rad = _wavefront.opd_to_phase(result.opd_nm * NM_TO_M, wavelength_m)
    _assert_masked_finite(phase_rad, model.pupil_mask, "DM phase surface")
    return phase_rad, result


def fit_static_opd_with_dm(
    target_opd_nm: np.ndarray,
    model: DMModel,
    rcond: float = 1.0e-4,
) -> DMFitResult:
    """Fit a static OPD map using the synthetic DM influence basis.

    Args:
        target_opd_nm: Target OPD map in nanometres.
        model: Synthetic DM model.
        rcond: Relative singular-value cutoff passed to ``np.linalg.lstsq``.

    Returns:
        :class:`DMFitResult` with fitted map, residual map, commands, and SVD
        diagnostics.

    Raises:
        DMModelError: If target shape is incompatible or no finite pupil pixels
        are available.

    Physics note:
        This helper estimates a DM fitting floor for static phase maps. Target
        and influence columns are projected onto the same piston-free pupil
        subspace. Dead actuators are removed from the solve, stuck actuators are
        included as fixed surface terms, and active stroke bounds are solved as
        a bounded least-squares problem.
    """

    target = np.asarray(target_opd_nm, dtype=float)
    if target.shape != model.pupil_mask.shape:
        raise DMModelError(f"target_opd_nm shape {target.shape} != pupil shape {model.pupil_mask.shape}.")
    finite = model.pupil_mask & np.isfinite(target)
    if not np.any(finite):
        raise DMModelError("No finite target OPD pixels are available inside the pupil.")
    target_vector = target[finite] - float(np.mean(target[finite]))
    # Rebuild the canonical façade on every call.  Historical DMModel arrays
    # are mutable even though the dataclass itself is frozen, so caching would
    # make a direct legacy construction diverge from its visible state.
    canonical = _canonical_model(model)
    matrix = np.asarray(
        [infl[finite] for infl in canonical.influence_functions],
        dtype=float,
    ).T
    _assert_all_finite(matrix, "DM fitting influence matrix")
    projected_matrix = matrix - np.mean(matrix, axis=0, keepdims=True)

    fixed_commands = np.zeros(model.n_actuators, dtype=float)
    fixed_commands[model.stuck_actuator_mask] = np.clip(
        model.config.stuck_command_nm,
        -model.config.stroke_limit_nm,
        model.config.stroke_limit_nm,
    )
    usable = ~(model.dead_actuator_mask | model.stuck_actuator_mask)
    rhs = target_vector - projected_matrix @ fixed_commands
    commands_raw = fixed_commands.copy()

    if np.any(usable):
        usable_matrix = projected_matrix[:, usable]
        free_commands, _, rank, singular_values = np.linalg.lstsq(usable_matrix, rhs, rcond=rcond)
        stroke = float(model.config.stroke_limit_nm)
        if np.any(np.abs(free_commands) > stroke):
            bounded = optimize.lsq_linear(
                usable_matrix,
                rhs,
                bounds=(-stroke, stroke),
                method="trf",
                tol=1.0e-12,
                lsmr_tol=1.0e-12,
            )
            if not bounded.success:
                raise DMModelError(f"Bounded DM fitting failed: {bounded.message}")
            free_commands = bounded.x
        commands_raw[usable] = free_commands
    else:
        rank = 0
        singular_values = np.empty(0, dtype=float)

    synthesis = synthesize_dm_opd_nm(commands_raw, model, remove_piston=True)
    residual = np.where(model.pupil_mask, target - synthesis.opd_nm, np.nan)
    residual = _remove_piston(residual, model.pupil_mask)
    residual_rms = _rms(residual, model.pupil_mask)
    return DMFitResult(
        target_opd_nm=np.where(model.pupil_mask, target, np.nan),
        fitted_opd_nm=synthesis.opd_nm,
        residual_opd_nm=residual,
        commands_nm=synthesis.clipped_commands_nm,
        residual_rms_nm=residual_rms,
        command_rms_nm=float(np.sqrt(np.mean(synthesis.clipped_commands_nm**2))),
        rank=int(rank),
        singular_values=np.asarray(singular_values, dtype=float),
    )


def actuator_metadata(model: DMModel) -> dict[str, Any]:
    """Summarize actuator metadata for diagnostics and caches.

    Args:
        model: Synthetic DM model.

    Returns:
        JSON-serializable metadata including centers, masks, pitch, stroke,
        influence model, and provenance.

    Raises:
        DMModelError: If metadata arrays have inconsistent lengths.

    Physics note:
        This metadata can accompany cached response matrices so actuator
        ordering and dead/stuck masks remain auditable.
    """

    if model.dead_actuator_mask.shape != (model.n_actuators,):
        raise DMModelError("dead_actuator_mask has inconsistent shape.")
    return {
        "n_actuators": model.n_actuators,
        "n_actuators_across": model.config.n_actuators_across,
        "actuator_pitch_m": model.actuator_pitch_m,
        "command_unit": "nm_OPD_equivalent",
        "stroke_limit_nm": model.config.stroke_limit_nm,
        "influence_model": model.config.influence_model,
        "coupling_width_pitch": model.config.coupling_width_pitch,
        "actuator_centers_m": model.actuator_centers_m.tolist(),
        "dead_actuator_indices": np.flatnonzero(model.dead_actuator_mask).astype(int).tolist(),
        "stuck_actuator_indices": np.flatnonzero(model.stuck_actuator_mask).astype(int).tolist(),
        "source_class": model.config.source_class,
        "source_note": model.config.source_note,
    }


def _canonical_model(model: DMModel) -> _DeformableMirror:
    """Rebuild a canonical façade from the current mutable legacy arrays."""

    if not isinstance(model, DMModel):
        raise DMModelError("model must be a DMModel.")
    if not isinstance(model.config, DMConfig):
        raise DMModelError("model.config must be a DMConfig.")

    pupil = np.asarray(model.pupil_mask, dtype=bool)
    influences = np.asarray(model.influence_functions, dtype=float)
    centers = np.asarray(model.actuator_centers_m, dtype=float)
    if pupil.ndim != 2:
        raise DMModelError("pupil_mask must be a 2-D array.")
    if influences.ndim != 3 or influences.shape[1:] != pupil.shape:
        raise DMModelError(
            "influence_functions must have shape (n_actuators, ny, nx)."
        )
    if centers.shape != (influences.shape[0], 2):
        raise DMModelError(
            "actuator_centers_m must have shape (n_actuators, 2)."
        )
    if model.n_actuators != influences.shape[0]:
        raise DMModelError(
            "actuator center and influence-function counts are inconsistent."
        )
    _assert_all_finite(centers, "actuator centers")
    _assert_influence_functions_finite(influences, pupil)

    dead_mask = np.asarray(model.dead_actuator_mask, dtype=bool)
    stuck_mask = np.asarray(model.stuck_actuator_mask, dtype=bool)
    expected_mask_shape = (model.n_actuators,)
    if dead_mask.shape != expected_mask_shape:
        raise DMModelError("dead_actuator_mask has inconsistent shape.")
    if stuck_mask.shape != expected_mask_shape:
        raise DMModelError("stuck_actuator_mask has inconsistent shape.")

    # Fault masks on a directly constructed historical DMModel are the source
    # of truth.  Replacing the config indices retains that old behavior while
    # still making the canonical wrapper own clipping/fault application.
    try:
        effective_config = _replace(
            model.config,
            dead_actuator_indices=tuple(
                int(value) for value in np.flatnonzero(dead_mask)
            ),
            stuck_actuator_indices=tuple(
                int(value) for value in np.flatnonzero(stuck_mask)
            ),
        )
        backend_influences = np.where(pupil[None, :, :], influences, 0.0)
        backend = _NativeDmBackend(backend_influences)
        return _DeformableMirror(
            effective_config,
            backend,
            actuator_ids=_actuator_ids_for_model(model),
            actuator_centers_m=np.asarray(centers, dtype=float),
            actuator_pitch_m=float(model.actuator_pitch_m),
            x_m=np.asarray(model.x_m, dtype=float),
            y_m=np.asarray(model.y_m, dtype=float),
            pupil_mask=pupil,
        )
    except (_DeformableMirrorError, _NativeDmError, ValueError) as exc:
        raise DMModelError(str(exc)) from exc


def _actuator_ids_for_model(model: DMModel) -> tuple[str, ...]:
    """Use physical grid IDs when recognizable, otherwise stable ordinals."""

    try:
        expected_centers, _pitch, indices_rc = _square_grid_actuator_layout(
            model.config.telescope_diameter_m,
            model.config.n_actuators_across,
            include_edge_actuators=model.config.include_edge_actuators,
            actuator_margin_fraction=model.config.actuator_margin_fraction,
        )
        centers = np.asarray(model.actuator_centers_m, dtype=float)
        if np.array_equal(centers, np.asarray(expected_centers, dtype=float)):
            return _actuator_ids_from_grid_indices(indices_rc)
    except (_NativeDmError, ValueError):
        pass
    return tuple(f"legacy-actuator-{index:04d}" for index in range(model.n_actuators))


def _canonical_synthesis(
    commands_nm: np.ndarray,
    canonical: _DeformableMirror,
):
    try:
        command = _DmCommandVector(
            values_opd_m=np.asarray(commands_nm, dtype=float) * NM_TO_M,
            actuator_ids=canonical.actuator_ids,
            command_unit="m_opd_equivalent",
        )
        return canonical.opd_from_commands(command)
    except (TypeError, ValueError, _DeformableMirrorError) as exc:
        raise DMModelError(str(exc)) from exc


def _legacy_applied_commands_nm(
    requested_nm: np.ndarray,
    model: DMModel,
    canonical_result,
) -> np.ndarray:
    """Restore exact historical nm values after the canonical SI boundary."""

    requested = np.asarray(requested_nm, dtype=float)
    saturated = np.asarray(canonical_result.saturated_mask, dtype=bool)
    dead = np.asarray(model.dead_actuator_mask, dtype=bool)
    stuck = np.asarray(model.stuck_actuator_mask, dtype=bool)
    applied = np.asarray(canonical_result.applied_commands_opd_m, dtype=float) / NM_TO_M

    # Avoid a metres-to-nanometres round-trip changing an otherwise untouched
    # historical command by a last-bit rounding error.
    ordinary = ~(dead | stuck)
    applied[ordinary & ~saturated] = requested[ordinary & ~saturated]
    applied[ordinary & saturated] = np.copysign(
        float(model.config.stroke_limit_nm),
        requested[ordinary & saturated],
    )
    applied[dead] = 0.0
    # Historical precedence is clip -> dead -> stuck, so stuck wins overlap.
    applied[stuck] = np.clip(
        model.config.stuck_command_nm,
        -model.config.stroke_limit_nm,
        model.config.stroke_limit_nm,
    )
    return applied


def _index_mask(indices: Sequence[int], n_items: int, field_name: str) -> np.ndarray:
    mask = np.zeros(n_items, dtype=bool)
    for index in indices:
        if index < 0 or index >= n_items:
            raise DMModelError(f"{field_name} contains out-of-range index {index}; n_actuators={n_items}.")
        mask[int(index)] = True
    return mask


def _validate_commands(commands_nm: Sequence[float], model: DMModel) -> np.ndarray:
    commands = np.asarray(commands_nm, dtype=float)
    if commands.shape != (model.n_actuators,):
        raise DMModelError(f"commands shape {commands.shape} != ({model.n_actuators},).")
    _assert_all_finite(commands, "DM command vector")
    return commands


def _assert_influence_functions_finite(influence_functions: np.ndarray, pupil_mask: np.ndarray) -> None:
    if influence_functions.ndim != 3:
        raise DMModelError("influence_functions must have shape (n_actuators, ny, nx).")
    inside = influence_functions[:, pupil_mask]
    if not np.all(np.isfinite(inside)):
        finite_frac = float(np.mean(np.isfinite(inside))) if inside.size else 0.0
        raise DMModelError(f"Non-finite values inside DM influence functions; finite_frac={finite_frac:.3f}.")


def _assert_masked_finite(values: np.ndarray, pupil_mask: np.ndarray, label: str) -> None:
    try:
        _wavefront.validate_masked_finite(values, pupil_mask, label)
    except ValueError as exc:
        raise DMModelError(str(exc)) from exc
    outside = np.asarray(values, dtype=float)[~pupil_mask]
    if outside.size and not np.all(np.isnan(outside)):
        raise DMModelError(f"{label} has finite values outside the pupil.")


def _assert_all_finite(values: np.ndarray, label: str) -> None:
    array = np.asarray(values, dtype=float)
    if not np.all(np.isfinite(array)):
        finite_frac = float(np.mean(np.isfinite(array))) if array.size else 0.0
        raise DMModelError(f"Non-finite values in {label}; finite_frac={finite_frac:.3f}.")


def _remove_piston(values: np.ndarray, pupil_mask: np.ndarray) -> np.ndarray:
    out = np.asarray(values, dtype=float).copy()
    mask = np.asarray(pupil_mask, dtype=bool)
    finite = mask & np.isfinite(out)
    if np.any(finite):
        centered = _wavefront.remove_piston(out, finite)
        out[finite] = centered[finite]
    out[~mask] = np.nan
    return out


def _rms(values: np.ndarray, pupil_mask: np.ndarray) -> float:
    array = np.asarray(values, dtype=float)
    finite = np.asarray(pupil_mask, dtype=bool) & np.isfinite(array)
    if not np.any(finite):
        raise DMModelError("No finite samples are available for RMS calculation.")
    return _wavefront.masked_rms(array, finite)


def _require_positive(field_name: str, value: float) -> None:
    _require_finite(field_name, value)
    if value <= 0:
        raise DMModelError(f"{field_name} must be positive; got {value!r}.")


def _dm_provenance(source_class: str, source_note: str) -> _Provenance:
    """Build canonical provenance while retaining legacy DM errors."""

    try:
        return _Provenance(source_class=source_class, source_note=str(source_note))
    except (TypeError, ValueError) as exc:
        if source_class not in ALLOWED_SOURCE_CLASSES:
            raise DMModelError(
                f"source_class={source_class!r} is not in the permitted taxonomy "
                f"{sorted(ALLOWED_SOURCE_CLASSES)}."
            ) from exc
        raise DMModelError("source_note must be a non-empty string.") from exc


def _require_nonnegative(field_name: str, value: float) -> None:
    _require_finite(field_name, value)
    if value < 0:
        raise DMModelError(f"{field_name} must be non-negative; got {value!r}.")


def _require_finite(field_name: str, value: float) -> None:
    if not math.isfinite(float(value)):
        raise DMModelError(f"{field_name} must be finite; got {value!r}.")
