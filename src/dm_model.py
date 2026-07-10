# DM model helpers create synthetic actuator masks, influence functions, stroke-clipped commands, dead/stuck actuator maps, and command-to-phase synthesis.

"""Synthetic deformable-mirror model for the realistic 2 m SCAO demo.

The model uses command units of nanometres OPD equivalent. This keeps stroke
limits and command maps explicit; conversion to phase in radians happens only
when a WFS or science wavelength is supplied.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import math
from typing import Any, Sequence

import numpy as np

from data_sources import ALLOWED_SOURCE_CLASSES


DEFAULT_DM_SOURCE_CLASS = "synthetic_literature_inspired"
DEFAULT_DM_SOURCE_NOTE = (
    "Synthetic Gaussian DM influence model motivated by published influence-function "
    "modelling examples such as Berdeu arXiv:2306.10803; not measured calibration data."
)
VALID_INFLUENCE_MODELS = frozenset({"gaussian", "compact_gaussian", "pyramid_like"})
NM_TO_M = 1.0e-9
PHASE_TWO_PI = 2.0 * math.pi
DEFAULT_ACTUATOR_MARGIN_FRACTION = 0.0
MIN_ACTUATORS_ACROSS = 2


class DMModelError(ValueError):
    """Raised when a synthetic DM model or command vector is invalid."""


@dataclass(frozen=True)
class DMConfig:
    """Configuration for a synthetic deformable mirror.

    Args:
        telescope_diameter_m: Pupil diameter in metres.
        n_actuators_across: Nominal square actuator count across the pupil.
        influence_model: Influence-function family. Supported values are
            ``gaussian``, ``compact_gaussian``, and ``pyramid_like``.
        coupling_width_pitch: Influence width in actuator-pitch units.
        stroke_limit_nm: Symmetric command stroke limit in nm OPD equivalent.
        include_edge_actuators: Whether the actuator grid includes pupil-edge
            coordinates.
        actuator_margin_fraction: Extra fractional pupil-radius margin for
            retaining edge/guard actuators.
        dead_actuator_indices: Command indices forced to zero.
        stuck_actuator_indices: Command indices forced to ``stuck_command_nm``.
        stuck_command_nm: Fixed command for stuck actuators in nm OPD
            equivalent.
        source_class: Provenance class from the documented source-class taxonomy.
        source_note: Human-readable source note.

    Returns:
        Immutable DM configuration.

    Raises:
        DMModelError: If physical parameters are invalid or if ``source_class``
            is outside the permitted taxonomy.

    Physics note:
        Commands are OPD-equivalent nanometres, not volts. The conversion to
        phase uses ``phase_rad = 2*pi*OPD_m/lambda_m`` at a named wavelength.
    """

    telescope_diameter_m: float = 2.0
    n_actuators_across: int = 11
    influence_model: str = "gaussian"
    coupling_width_pitch: float = 0.35
    stroke_limit_nm: float = 800.0
    include_edge_actuators: bool = True
    actuator_margin_fraction: float = DEFAULT_ACTUATOR_MARGIN_FRACTION
    dead_actuator_indices: tuple[int, ...] = ()
    stuck_actuator_indices: tuple[int, ...] = ()
    stuck_command_nm: float = 0.0
    source_class: str = DEFAULT_DM_SOURCE_CLASS
    source_note: str = DEFAULT_DM_SOURCE_NOTE

    def __post_init__(self) -> None:
        _require_positive("telescope_diameter_m", self.telescope_diameter_m)
        if self.n_actuators_across < MIN_ACTUATORS_ACROSS:
            raise DMModelError(f"n_actuators_across must be >= {MIN_ACTUATORS_ACROSS}.")
        if self.influence_model not in VALID_INFLUENCE_MODELS:
            raise DMModelError(
                f"influence_model={self.influence_model!r}; expected one of {sorted(VALID_INFLUENCE_MODELS)}."
            )
        _require_positive("coupling_width_pitch", self.coupling_width_pitch)
        _require_positive("stroke_limit_nm", self.stroke_limit_nm)
        _require_nonnegative("actuator_margin_fraction", self.actuator_margin_fraction)
        _require_finite("stuck_command_nm", self.stuck_command_nm)
        if self.source_class not in ALLOWED_SOURCE_CLASSES:
            raise DMModelError(
                f"source_class={self.source_class!r} is not in the permitted taxonomy "
                f"{sorted(ALLOWED_SOURCE_CLASSES)}."
            )
        if not str(self.source_note).strip():
            raise DMModelError("source_note must be a non-empty string.")


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

    path = Path(path)
    with path.open("r", encoding="utf-8") as handle:
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

    centers_m, pitch_m = actuator_centers_on_pupil(config)
    if centers_m.size == 0:
        raise DMModelError("No DM actuators were retained inside the pupil.")
    influence_functions = np.asarray(
        [
            _influence_function(
                x,
                y,
                mask,
                center_m=center,
                pitch_m=pitch_m,
                influence_model=config.influence_model,
                coupling_width_pitch=config.coupling_width_pitch,
            )
            for center in centers_m
        ],
        dtype=float,
    )
    _assert_influence_functions_finite(influence_functions, mask)
    dead_mask = _index_mask(config.dead_actuator_indices, len(centers_m), "dead_actuator_indices")
    stuck_mask = _index_mask(config.stuck_actuator_indices, len(centers_m), "stuck_actuator_indices")
    return DMModel(
        config=config,
        x_m=x,
        y_m=y,
        pupil_mask=mask,
        actuator_centers_m=centers_m,
        actuator_pitch_m=pitch_m,
        influence_functions=influence_functions,
        dead_actuator_mask=dead_mask,
        stuck_actuator_mask=stuck_mask,
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

    radius_m = 0.5 * config.telescope_diameter_m
    if config.include_edge_actuators:
        coords = np.linspace(-radius_m, radius_m, config.n_actuators_across)
    else:
        pitch_tmp = config.telescope_diameter_m / float(config.n_actuators_across)
        coords = np.linspace(
            -radius_m + 0.5 * pitch_tmp,
            radius_m - 0.5 * pitch_tmp,
            config.n_actuators_across,
        )
    if coords.size < 2:
        raise DMModelError("Actuator grid must contain at least two coordinates.")
    pitch_m = float(abs(coords[1] - coords[0]))
    retain_radius_m = radius_m * (1.0 + config.actuator_margin_fraction)
    centers = []
    for x0 in coords:
        for y0 in coords:
            if x0**2 + y0**2 <= retain_radius_m**2:
                centers.append((float(x0), float(y0)))
    return np.asarray(centers, dtype=float), pitch_m


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
    stroke = model.config.stroke_limit_nm
    saturated = np.abs(commands) > stroke
    clipped = np.clip(commands, -stroke, stroke)
    clipped[model.dead_actuator_mask] = 0.0
    clipped[model.stuck_actuator_mask] = np.clip(model.config.stuck_command_nm, -stroke, stroke)
    return clipped, saturated


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

    clipped, saturated = clip_commands_nm(commands_nm, model)
    opd_full_nm = np.sum(
        clipped[:, None, None] * np.nan_to_num(model.influence_functions, nan=0.0),
        axis=0,
    )
    opd_nm = np.where(model.pupil_mask, opd_full_nm, np.nan)
    if remove_piston:
        opd_nm = _remove_piston(opd_nm, model.pupil_mask)
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
    phase_rad = PHASE_TWO_PI * result.opd_nm * NM_TO_M / wavelength_m
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
        This helper estimates a DM fitting floor for static phase maps. Stroke
        clipping is applied after least-squares fitting to keep command maps
        physically bounded.
    """

    target = np.asarray(target_opd_nm, dtype=float)
    if target.shape != model.pupil_mask.shape:
        raise DMModelError(f"target_opd_nm shape {target.shape} != pupil shape {model.pupil_mask.shape}.")
    finite = model.pupil_mask & np.isfinite(target)
    if not np.any(finite):
        raise DMModelError("No finite target OPD pixels are available inside the pupil.")
    target_vector = target[finite] - float(np.mean(target[finite]))
    matrix = np.asarray([infl[finite] for infl in model.influence_functions], dtype=float).T
    _assert_all_finite(matrix, "DM fitting influence matrix")
    commands_raw, _, rank, singular_values = np.linalg.lstsq(matrix, target_vector, rcond=rcond)
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


def _influence_function(
    x_m: np.ndarray,
    y_m: np.ndarray,
    pupil_mask: np.ndarray,
    center_m: np.ndarray,
    pitch_m: float,
    influence_model: str,
    coupling_width_pitch: float,
) -> np.ndarray:
    sigma_m = coupling_width_pitch * pitch_m
    dx = x_m - float(center_m[0])
    dy = y_m - float(center_m[1])
    r_m = np.sqrt(dx**2 + dy**2)
    if influence_model == "gaussian":
        influence = np.exp(-(r_m**2) / (2.0 * sigma_m**2))
    elif influence_model == "compact_gaussian":
        cutoff_m = 3.0 * sigma_m
        influence = np.exp(-(r_m**2) / (2.0 * sigma_m**2))
        influence = np.where(r_m <= cutoff_m, influence, 0.0)
    elif influence_model == "pyramid_like":
        support_m = 2.0 * sigma_m
        influence = np.maximum(1.0 - r_m / support_m, 0.0)
    else:  # pragma: no cover - guarded by DMConfig
        raise DMModelError(f"Unsupported influence_model={influence_model!r}.")
    influence = np.where(pupil_mask, influence, np.nan)
    peak = float(np.nanmax(influence))
    _require_positive("influence function peak", peak)
    return influence / peak


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
    inside = np.asarray(values, dtype=float)[pupil_mask]
    outside = np.asarray(values, dtype=float)[~pupil_mask]
    if not np.all(np.isfinite(inside)):
        finite_frac = float(np.mean(np.isfinite(inside))) if inside.size else 0.0
        raise DMModelError(f"Non-finite values inside {label}; finite_frac={finite_frac:.3f}.")
    if outside.size and not np.all(np.isnan(outside)):
        raise DMModelError(f"{label} has finite values outside the pupil.")


def _assert_all_finite(values: np.ndarray, label: str) -> None:
    array = np.asarray(values, dtype=float)
    if not np.all(np.isfinite(array)):
        finite_frac = float(np.mean(np.isfinite(array))) if array.size else 0.0
        raise DMModelError(f"Non-finite values in {label}; finite_frac={finite_frac:.3f}.")


def _remove_piston(values: np.ndarray, pupil_mask: np.ndarray) -> np.ndarray:
    out = np.asarray(values, dtype=float).copy()
    finite = pupil_mask & np.isfinite(out)
    if np.any(finite):
        out[finite] -= float(np.mean(out[finite]))
    out[~pupil_mask] = np.nan
    return out


def _rms(values: np.ndarray, pupil_mask: np.ndarray) -> float:
    samples = np.asarray(values, dtype=float)[pupil_mask]
    samples = samples[np.isfinite(samples)]
    if samples.size == 0:
        raise DMModelError("No finite samples are available for RMS calculation.")
    samples = samples - float(np.mean(samples))
    return float(np.sqrt(np.mean(samples**2)))


def _require_positive(field_name: str, value: float) -> None:
    _require_finite(field_name, value)
    if value <= 0:
        raise DMModelError(f"{field_name} must be positive; got {value!r}.")


def _require_nonnegative(field_name: str, value: float) -> None:
    _require_finite(field_name, value)
    if value < 0:
        raise DMModelError(f"{field_name} must be non-negative; got {value!r}.")


def _require_finite(field_name: str, value: float) -> None:
    if not math.isfinite(float(value)):
        raise DMModelError(f"{field_name} must be finite; got {value!r}.")
