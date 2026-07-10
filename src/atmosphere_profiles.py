# Atmosphere profile builder provides seeing/r0 conversion, Cn2 layer normalization, and finite multi-layer frozen-flow phase cubes.

"""Atmosphere profile builders for the realistic 2 m SCAO demonstrator.

This module sits between the data-source records and later AO control
code. It turns a provenance-tagged atmosphere profile into explicit layer
configs, validates normalized Cn2 weights, and generates compact frozen-flow
phase cubes in radians at a named wavelength.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

import numpy as np

from data_sources import ALLOWED_SOURCE_CLASSES, EsoAsmSnapshot, LiteratureAtmosphereProfile
from phase_screen import circular_mask_from_grid, fourier_phase_screen, rms


ARCSEC_PER_RAD = 206265.0
R0_REFERENCE_WAVELENGTH_M = 500.0e-9
FRIED_SEEING_COEFFICIENT = 0.98
PHASE_RMS_COEFFICIENT = 1.03
R0_WAVELENGTH_EXPONENT = 6.0 / 5.0
R0_STRENGTH_EXPONENT = -3.0 / 5.0
LAYER_WEIGHT_ABS_TOL = 1.0e-9
PHASE_RMS_REL_TOL = 0.10
FULL_SCREEN_COVER_FACTOR = 1.02


class AtmosphereProfileError(ValueError):
    """Raised when an atmosphere profile or generated phase cube is invalid."""


@dataclass(frozen=True)
class AtmosphereLayerConfig:
    """One normalized frozen-flow turbulence layer.

    Args:
        height_m: Layer altitude in metres.
        cn2_weight: Fractional Cn2 strength. The full atmosphere config
            normalizes these weights to sum to one.
        wind_ms: Wind speed in metres per second.
        wind_dir_deg: Wind direction in degrees, measured counter-clockwise
            from positive x in the pupil grid.

    Returns:
        Immutable layer configuration.

    Raises:
        AtmosphereProfileError: If any scalar is non-finite, if altitude or
            weight is negative, or if wind speed is negative.

    Physics note:
        ``cn2_weight`` is dimensionless and partitions the total atmospheric
        phase variance among independent layers. Later phase screens use
        layer RMS proportional to ``sqrt(cn2_weight)``.
    """

    height_m: float
    cn2_weight: float
    wind_ms: float
    wind_dir_deg: float

    def __post_init__(self) -> None:
        _require_finite("height_m", self.height_m)
        _require_finite("cn2_weight", self.cn2_weight)
        _require_finite("wind_ms", self.wind_ms)
        _require_finite("wind_dir_deg", self.wind_dir_deg)
        if self.height_m < 0:
            raise AtmosphereProfileError("height_m must be non-negative.")
        if self.cn2_weight < 0:
            raise AtmosphereProfileError("cn2_weight must be non-negative.")
        if self.wind_ms < 0:
            raise AtmosphereProfileError("wind_ms must be non-negative.")


@dataclass(frozen=True)
class AtmosphereConfig:
    """Normalized atmosphere configuration shared across simulation modules.

    Args:
        layers: Normalized turbulence layers.
        r0_500_m: Fried parameter at 500 nm in metres.
        seeing_arcsec: Seeing FWHM at 500 nm in arcseconds.
        tau0_s: Atmospheric coherence time in seconds.
        theta0_rad: Isoplanatic angle in radians.
        seed: Deterministic random seed for phase-screen generation.
        source_class: Provenance class inherited from the profile.
        source_note: Human-readable provenance note.

    Returns:
        Immutable atmosphere config with normalized layer weights.

    Raises:
        AtmosphereProfileError: If physical scalars are non-finite or
            non-positive, or if layer weights are not normalized.

    Physics note:
        This is the cross-module ``AtmosphereConfig`` contract shared by the
        atmosphere, WFS, and loop modules. Phase-generating functions interpret
        r0 at a named wavelength using Fried's r0(lambda) scaling.
    """

    layers: tuple[AtmosphereLayerConfig, ...]
    r0_500_m: float
    seeing_arcsec: float
    tau0_s: float
    theta0_rad: float
    seed: int
    source_class: str
    source_note: str

    def __post_init__(self) -> None:
        if not self.layers:
            raise AtmosphereProfileError("AtmosphereConfig requires at least one layer.")
        _require_positive("r0_500_m", self.r0_500_m)
        _require_positive("seeing_arcsec", self.seeing_arcsec)
        _require_positive("tau0_s", self.tau0_s)
        _require_positive("theta0_rad", self.theta0_rad)
        if self.source_class not in ALLOWED_SOURCE_CLASSES:
            raise AtmosphereProfileError(
                f"source_class={self.source_class!r} is not in the permitted taxonomy "
                f"{sorted(ALLOWED_SOURCE_CLASSES)}."
            )
        if not str(self.source_note).strip():
            raise AtmosphereProfileError("source_note must be a non-empty string.")
        _assert_normalized_layer_weights(self.layers)


@dataclass(frozen=True)
class AtmospherePhaseCube:
    """Generated multi-layer frozen-flow phase sequence.

    Args:
        cube_rad: Phase cube with shape ``(n_steps, n_grid, n_grid)`` in
            radians at ``wavelength_m``. Pixels outside ``mask`` are NaN.
        x_m: X-coordinate grid in metres.
        y_m: Y-coordinate grid in metres.
        mask: Telescope pupil mask.
        time_s: Time stamps in seconds.
        rms_rad: Piston-removed RMS of each phase frame inside ``mask``.
        expected_rms_rad: Target RMS from r0 and telescope diameter.
        r0_at_wavelength_m: Fried parameter at ``wavelength_m`` in metres.
        wavelength_m: Phase reference wavelength in metres.
        config: Atmosphere configuration used to generate the cube.

    Returns:
        Immutable phase-cube bundle for diagnostics and later AO loops.

    Raises:
        AtmosphereProfileError: Constructed by generator functions after
            finite-value and RMS checks pass.

    Physics note:
        Phase values are radians at ``wavelength_m``. The same OPD would have a
        different phase at a science wavelength, so later Strehl code must
        rescale through OPD rather than compare raw phase RMS values.
    """

    cube_rad: np.ndarray
    x_m: np.ndarray
    y_m: np.ndarray
    mask: np.ndarray
    time_s: np.ndarray
    rms_rad: np.ndarray
    expected_rms_rad: float
    r0_at_wavelength_m: float
    wavelength_m: float
    config: AtmosphereConfig


def seeing_to_r0_m(
    seeing_arcsec: float,
    wavelength_m: float = R0_REFERENCE_WAVELENGTH_M,
) -> float:
    """Convert seeing FWHM to Fried parameter r0.

    Args:
        seeing_arcsec: Seeing full width at half maximum in arcseconds.
        wavelength_m: Wavelength in metres at which the seeing is quoted.

    Returns:
        Fried parameter r0 in metres.

    Raises:
        AtmosphereProfileError: If seeing or wavelength is non-positive.

    Physics note:
        Uses the standard long-exposure relation ``seeing_rad = 0.98 *
        wavelength / r0``. The default wavelength is 500 nm.
    """

    _require_positive("seeing_arcsec", seeing_arcsec)
    _require_positive("wavelength_m", wavelength_m)
    seeing_rad = seeing_arcsec / ARCSEC_PER_RAD
    # Fried seeing conversion: seeing_rad = 0.98 * lambda / r0.
    return float(FRIED_SEEING_COEFFICIENT * wavelength_m / seeing_rad)


def r0_at_wavelength_m(
    r0_500_m: float,
    wavelength_m: float,
    reference_wavelength_m: float = R0_REFERENCE_WAVELENGTH_M,
) -> float:
    """Scale Fried parameter from 500 nm to another wavelength.

    Args:
        r0_500_m: Fried parameter at ``reference_wavelength_m`` in metres.
        wavelength_m: Target wavelength in metres.
        reference_wavelength_m: Reference wavelength in metres.

    Returns:
        Fried parameter at ``wavelength_m`` in metres.

    Raises:
        AtmosphereProfileError: If any wavelength or r0 value is non-positive.

    Physics note:
        Uses Fried scaling ``r0(lambda) = r0_ref *
        (lambda/lambda_ref)**(6/5)``. The exponent follows the standard
        Kolmogorov scaling and should not be changed without a documented reference.
    """

    _require_positive("r0_500_m", r0_500_m)
    _require_positive("wavelength_m", wavelength_m)
    _require_positive("reference_wavelength_m", reference_wavelength_m)
    # r0 wavelength scaling: r0(lam)=r0_ref*(lam/lam_ref)**(6/5), Fried 1966 DOI:10.1364/JOSA.56.001372
    return float(r0_500_m * (wavelength_m / reference_wavelength_m) ** R0_WAVELENGTH_EXPONENT)


def expected_phase_rms_rad(diameter_m: float, r0_m: float) -> float:
    """Estimate atmospheric pupil phase RMS from diameter and r0.

    Args:
        diameter_m: Telescope pupil diameter in metres.
        r0_m: Fried parameter in metres at the same wavelength as the phase.

    Returns:
        Approximate piston-removed phase RMS in radians.

    Raises:
        AtmosphereProfileError: If diameter or r0 is non-positive.

    Physics note:
        Uses the compact simulator scaling ``sqrt(1.03 * (D/r0)**(5/3))``,
        matching the existing ``phase_screen.fourier_phase_screen`` target RMS
        convention.
    """

    _require_positive("diameter_m", diameter_m)
    _require_positive("r0_m", r0_m)
    # Kolmogorov phase variance proxy used by this repo: sigma_phi^2 = 1.03*(D/r0)^(5/3).
    return float(math.sqrt(PHASE_RMS_COEFFICIENT * (diameter_m / r0_m) ** (5.0 / 3.0)))


def normalize_layers(layers: Sequence[AtmosphereLayerConfig]) -> tuple[AtmosphereLayerConfig, ...]:
    """Normalize Cn2 layer weights while preserving layer metadata.

    Args:
        layers: Input layer configurations with non-negative Cn2 weights.

    Returns:
        Tuple of layers whose ``cn2_weight`` values sum to one.

    Raises:
        AtmosphereProfileError: If the layer list is empty or if total Cn2
            strength is zero/non-finite.

    Physics note:
        Cn2 weights represent fractional turbulence strength. Normalizing them
        keeps total r0/seeing controlled by the atmosphere summary rather than
        by arbitrary unnormalized layer amplitudes.
    """

    if not layers:
        raise AtmosphereProfileError("layers must contain at least one layer.")
    total = float(sum(layer.cn2_weight for layer in layers))
    _require_positive("sum(cn2_weight)", total)
    normalized = tuple(
        AtmosphereLayerConfig(
            height_m=layer.height_m,
            cn2_weight=layer.cn2_weight / total,
            wind_ms=layer.wind_ms,
            wind_dir_deg=layer.wind_dir_deg,
        )
        for layer in layers
    )
    _assert_normalized_layer_weights(normalized)
    return normalized


def equivalent_r0_500_m(config: AtmosphereConfig) -> float:
    """Recover equivalent r0 from normalized layer strengths.

    Args:
        config: Atmosphere configuration with normalized layer weights.

    Returns:
        Equivalent Fried parameter at 500 nm in metres.

    Raises:
        AtmosphereProfileError: If layer weights are malformed.

    Physics note:
        Turbulence strengths add as ``r0**(-5/3)``. For normalized layer
        weights, ``sum(weight_i)=1`` and the equivalent r0 remains
        ``config.r0_500_m``.
    """

    _assert_normalized_layer_weights(config.layers)
    strength_sum = float(sum(layer.cn2_weight for layer in config.layers))
    # Integrated turbulence strength scales as r0^(-5/3); invert with exponent -3/5.
    return float(config.r0_500_m * strength_sum ** R0_STRENGTH_EXPONENT)


def atmosphere_config_from_literature_profile(
    profile: LiteratureAtmosphereProfile,
    seed: int = 1,
) -> AtmosphereConfig:
    """Build an ``AtmosphereConfig`` from a literature profile object.

    Args:
        profile: Structured atmosphere profile with summary values,
            layers, units, and provenance.
        seed: Deterministic random seed for later phase generation.

    Returns:
        Normalized :class:`AtmosphereConfig`.

    Raises:
        AtmosphereProfileError: If required summary fields are absent or if
            layer weights are invalid.

    Physics note:
        ``theta0_arcsec`` is converted to radians here because the cross-module
        contract stores ``theta0_rad``. The phase generator still interprets
        all phase values at an explicit wavelength.
    """

    required = ("seeing_arcsec_500nm", "r0_500_m", "tau0_s", "theta0_arcsec")
    missing = [key for key in required if key not in profile.summary]
    if missing:
        raise AtmosphereProfileError(f"profile {profile.name!r} missing summary fields {missing}.")
    layers = normalize_layers(
        tuple(
            AtmosphereLayerConfig(
                height_m=layer.height_m,
                cn2_weight=layer.cn2_weight,
                wind_ms=layer.wind_ms,
                wind_dir_deg=layer.wind_dir_deg,
            )
            for layer in profile.layers
        )
    )
    return AtmosphereConfig(
        layers=layers,
        r0_500_m=float(profile.summary["r0_500_m"]),
        seeing_arcsec=float(profile.summary["seeing_arcsec_500nm"]),
        tau0_s=float(profile.summary["tau0_s"]),
        theta0_rad=float(profile.summary["theta0_arcsec"]) / ARCSEC_PER_RAD,
        seed=int(seed),
        source_class=profile.provenance.source_class,
        source_note=profile.provenance.source_note,
    )


def atmosphere_config_from_eso_asm_snapshot(
    snapshot: EsoAsmSnapshot,
    seed: int = 1,
    wind_dir_deg: float = 0.0,
) -> AtmosphereConfig:
    """Build a compact atmosphere config from a ESO ASM snapshot.

    Args:
        snapshot: Structured ESO ASM snapshot with seeing/r0/tau0/theta0-style
            measurements and direct provenance.
        seed: Deterministic random seed for later phase generation.
        wind_dir_deg: Direction assigned to the single frozen-flow layer when
            ASM provides only an effective turbulence speed.

    Returns:
        Single-layer :class:`AtmosphereConfig` using the ASM median seeing,
        r0, tau0, theta0, and turbulence-speed summary.

    Raises:
        AtmosphereProfileError: If required snapshot fields are absent or
            non-physical.

    Physics note:
        The ASM turbulence speed is an effective scalar, not a full wind
        profile. This helper therefore creates a one-layer atmosphere suitable
        for compact direct-data sanity checks, while multi-layer Cn2 studies
        should still use a literature/profile object.
    """

    measurements = snapshot.measurements
    required = ("seeing_arcsec_500nm", "tau0_s", "theta0_arcsec")
    missing = [key for key in required if key not in measurements]
    if missing:
        raise AtmosphereProfileError(f"ESO ASM snapshot missing measurement fields {missing}.")
    seeing_arcsec = float(measurements["seeing_arcsec_500nm"])
    r0_500_m = float(measurements.get("r0_500_m", seeing_to_r0_m(seeing_arcsec)))
    wind_ms = float(measurements.get("turbulence_speed_ms", measurements.get("wind_speed_ms", 0.0)))
    layer = AtmosphereLayerConfig(
        height_m=0.0,
        cn2_weight=1.0,
        wind_ms=wind_ms,
        wind_dir_deg=float(wind_dir_deg),
    )
    return AtmosphereConfig(
        layers=(layer,),
        r0_500_m=r0_500_m,
        seeing_arcsec=seeing_arcsec,
        tau0_s=float(measurements["tau0_s"]),
        theta0_rad=float(measurements["theta0_arcsec"]) / ARCSEC_PER_RAD,
        seed=int(seed),
        source_class=snapshot.provenance.source_class,
        source_note=snapshot.provenance.source_note,
    )


def wind_components_ms(layer: AtmosphereLayerConfig) -> tuple[float, float]:
    """Resolve layer wind speed/direction into x/y components.

    Args:
        layer: Atmosphere layer with wind speed in metres per second and
            direction in degrees.

    Returns:
        ``(vx, vy)`` wind components in metres per second.

    Raises:
        AtmosphereProfileError: If layer wind values are non-finite.

    Physics note:
        Positive x is to the right of the pupil grid and positive y is upward
        in the mathematical grid convention used by the simulation.
    """

    _require_finite("wind_ms", layer.wind_ms)
    _require_finite("wind_dir_deg", layer.wind_dir_deg)
    angle_rad = math.radians(layer.wind_dir_deg)
    return float(layer.wind_ms * math.cos(angle_rad)), float(layer.wind_ms * math.sin(angle_rad))


def shift_full_phase_pixels(
    phase_rad: np.ndarray,
    shift_x_pix: int,
    shift_y_pix: int,
) -> np.ndarray:
    """Translate a finite full-grid phase screen with periodic boundaries.

    Args:
        phase_rad: Full-grid phase screen in radians at its reference
            wavelength. It must be finite everywhere.
        shift_x_pix: Integer x shift in pixels.
        shift_y_pix: Integer y shift in pixels.

    Returns:
        Shifted full-grid phase screen in radians.

    Raises:
        AtmosphereProfileError: If the input phase screen contains NaN or Inf.

    Physics note:
        This function shifts the unmasked full screen first. The telescope mask
        is applied only after all layer shifts, which avoids rolling NaN pupil
        edges into the aperture as a masked crescent artifact.
    """

    phase = np.asarray(phase_rad, dtype=float)
    _assert_all_finite(phase, "full-grid phase before frozen-flow shift")
    return np.roll(
        np.roll(phase, int(shift_y_pix), axis=0),
        int(shift_x_pix),
        axis=1,
    )


def generate_multilayer_phase_cube(
    config: AtmosphereConfig,
    n_grid: int,
    diameter_m: float,
    n_steps: int,
    dt_s: float,
    wavelength_m: float = R0_REFERENCE_WAVELENGTH_M,
    outer_scale_L0_m: float | None = 25.0,
    field_angle_x_arcsec: float = 0.0,
    field_angle_y_arcsec: float = 0.0,
    normalize_total: bool = True,
) -> AtmospherePhaseCube:
    """Generate a finite multi-layer frozen-flow atmosphere phase cube.

    Args:
        config: Normalized atmosphere configuration.
        n_grid: Square grid size in pixels.
        diameter_m: Telescope pupil diameter in metres.
        n_steps: Number of time steps to generate.
        dt_s: Time step in seconds.
        wavelength_m: Phase reference wavelength in metres.
        outer_scale_L0_m: Outer scale in metres, passed to the compact
            Fourier screen generator.
        field_angle_x_arcsec: Optional x field angle in arcseconds for a
            geometric layer offset.
        field_angle_y_arcsec: Optional y field angle in arcseconds for a
            geometric layer offset.
        normalize_total: If true, each summed frame is scaled to the r0-based
            expected RMS inside the telescope mask.

    Returns:
        :class:`AtmospherePhaseCube` with phase in radians at ``wavelength_m``.

    Raises:
        AtmosphereProfileError: If dimensions are invalid, generated arrays
            contain NaN/Inf inside the pupil, or RMS differs from expectation
            by more than 10 percent.

    Physics note:
        Independent layers are assigned RMS proportional to
        ``sqrt(cn2_weight)`` so their variances add to the r0-derived total
        phase variance. Frozen flow uses integer pixel translations from wind
        speed, time, and grid sampling.
    """

    _require_grid_inputs(n_grid, diameter_m, n_steps, dt_s, wavelength_m)
    _assert_normalized_layer_weights(config.layers)
    delta_m = diameter_m / float(n_grid)
    r0_m = r0_at_wavelength_m(config.r0_500_m, wavelength_m)
    expected_rms = expected_phase_rms_rad(diameter_m, r0_m)

    x = (np.arange(n_grid) - n_grid // 2) * delta_m
    x_m, y_m = np.meshgrid(x, x)
    pupil_mask = circular_mask_from_grid(x_m, y_m, diameter_m)

    layer_bases = []
    for index, layer in enumerate(config.layers):
        target_layer_rms = expected_rms * math.sqrt(layer.cn2_weight)
        layer_bases.append(
            _make_full_grid_layer(
                n_grid=n_grid,
                delta_m=delta_m,
                diameter_m=diameter_m,
                r0_m=r0_m,
                outer_scale_L0_m=outer_scale_L0_m,
                wavelength_m=wavelength_m,
                seed=config.seed + index,
                target_rms_rad=target_layer_rms,
                pupil_mask=pupil_mask,
            )
        )

    time_s = np.arange(n_steps, dtype=float) * dt_s
    cube = np.empty((n_steps, n_grid, n_grid), dtype=float)
    field_angle_x_rad = field_angle_x_arcsec / ARCSEC_PER_RAD
    field_angle_y_rad = field_angle_y_arcsec / ARCSEC_PER_RAD

    for step_index, t_s in enumerate(time_s):
        total_full = np.zeros((n_grid, n_grid), dtype=float)
        for layer, base in zip(config.layers, layer_bases):
            vx_ms, vy_ms = wind_components_ms(layer)
            wind_shift_x = int(round(vx_ms * t_s / delta_m))
            wind_shift_y = int(round(vy_ms * t_s / delta_m))
            field_shift_x = int(round(layer.height_m * field_angle_x_rad / delta_m))
            field_shift_y = int(round(layer.height_m * field_angle_y_rad / delta_m))
            shifted = shift_full_phase_pixels(
                base,
                shift_x_pix=wind_shift_x + field_shift_x,
                shift_y_pix=wind_shift_y + field_shift_y,
            )
            total_full += shifted

        frame = _mask_and_remove_piston(total_full, pupil_mask)
        if normalize_total:
            frame = _scale_masked_frame_to_rms(frame, pupil_mask, expected_rms)
        _assert_masked_frame_finite(frame, pupil_mask, f"phase cube frame {step_index}")
        cube[step_index] = frame

    rms_rad = np.asarray([rms(frame, pupil_mask) for frame in cube], dtype=float)
    _assert_all_finite(rms_rad, "phase cube RMS history")
    max_rel_error = float(np.max(np.abs(rms_rad - expected_rms) / expected_rms))
    if max_rel_error > PHASE_RMS_REL_TOL:
        raise AtmosphereProfileError(
            "Generated phase RMS does not match r0 expectation within "
            f"{PHASE_RMS_REL_TOL:.0%}; max_rel_error={max_rel_error:.3f}, "
            f"expected_rms_rad={expected_rms:.6g}, measured_range_rad="
            f"({float(np.min(rms_rad)):.6g}, {float(np.max(rms_rad)):.6g})."
        )

    return AtmospherePhaseCube(
        cube_rad=cube,
        x_m=x_m,
        y_m=y_m,
        mask=pupil_mask,
        time_s=time_s,
        rms_rad=rms_rad,
        expected_rms_rad=expected_rms,
        r0_at_wavelength_m=r0_m,
        wavelength_m=wavelength_m,
        config=config,
    )


def _make_full_grid_layer(
    n_grid: int,
    delta_m: float,
    diameter_m: float,
    r0_m: float,
    outer_scale_L0_m: float | None,
    wavelength_m: float,
    seed: int,
    target_rms_rad: float,
    pupil_mask: np.ndarray,
) -> np.ndarray:
    if target_rms_rad == 0:
        return np.zeros((n_grid, n_grid), dtype=float)
    full_cover_diameter_m = math.sqrt(2.0) * n_grid * delta_m * FULL_SCREEN_COVER_FACTOR
    phase, _, _, _ = fourier_phase_screen(
        N=n_grid,
        delta=delta_m,
        r0=r0_m,
        L0=outer_scale_L0_m,
        diameter=full_cover_diameter_m,
        wavelength=wavelength_m,
        seed=seed,
        target_rms_rad=target_rms_rad,
        normalize_rms=True,
    )
    # Unit assertion: full_grid_phase is radians at the phase reference wavelength.
    full_grid_phase = np.asarray(phase, dtype=float)
    _assert_all_finite(full_grid_phase, f"full-grid layer phase seed={seed}")
    full_grid_phase = _normalize_full_grid_phase_to_pupil_rms(
        full_grid_phase,
        pupil_mask=pupil_mask,
        target_rms_rad=target_rms_rad,
    )
    _assert_all_finite(full_grid_phase, f"normalized full-grid layer phase seed={seed}")
    return full_grid_phase


def _normalize_full_grid_phase_to_pupil_rms(
    phase_rad: np.ndarray,
    pupil_mask: np.ndarray,
    target_rms_rad: float,
) -> np.ndarray:
    _require_positive("target_rms_rad", target_rms_rad)
    phase = np.asarray(phase_rad, dtype=float).copy()
    pupil_values = phase[pupil_mask]
    _assert_all_finite(pupil_values, "pupil values before layer normalization")
    phase -= float(np.mean(pupil_values))
    current_rms = float(np.sqrt(np.mean((phase[pupil_mask] - np.mean(phase[pupil_mask])) ** 2)))
    _require_positive("current layer pupil RMS", current_rms)
    return phase * (target_rms_rad / current_rms)


def _mask_and_remove_piston(phase_rad: np.ndarray, pupil_mask: np.ndarray) -> np.ndarray:
    frame = np.full_like(phase_rad, np.nan, dtype=float)
    pupil_values = np.asarray(phase_rad, dtype=float)[pupil_mask]
    _assert_all_finite(pupil_values, "pupil values before piston removal")
    frame[pupil_mask] = pupil_values - float(np.mean(pupil_values))
    return frame


def _scale_masked_frame_to_rms(
    frame_rad: np.ndarray,
    pupil_mask: np.ndarray,
    target_rms_rad: float,
) -> np.ndarray:
    current = rms(frame_rad, pupil_mask)
    _require_positive("current phase RMS", current)
    scaled = np.array(frame_rad, dtype=float, copy=True)
    scaled[pupil_mask] *= target_rms_rad / current
    return scaled


def _assert_masked_frame_finite(frame_rad: np.ndarray, pupil_mask: np.ndarray, label: str) -> None:
    inside = np.asarray(frame_rad, dtype=float)[pupil_mask]
    outside = np.asarray(frame_rad, dtype=float)[~pupil_mask]
    if not np.all(np.isfinite(inside)):
        finite_frac = float(np.mean(np.isfinite(inside))) if inside.size else 0.0
        raise AtmosphereProfileError(f"Non-finite values inside {label}; finite_frac={finite_frac:.3f}.")
    if outside.size and not np.all(np.isnan(outside)):
        raise AtmosphereProfileError(f"{label} has finite values outside the pupil mask.")


def _assert_all_finite(values: np.ndarray, label: str) -> None:
    array = np.asarray(values, dtype=float)
    if not np.all(np.isfinite(array)):
        finite_frac = float(np.mean(np.isfinite(array))) if array.size else 0.0
        raise AtmosphereProfileError(f"Non-finite values in {label}; finite_frac={finite_frac:.3f}.")


def _assert_normalized_layer_weights(layers: Sequence[AtmosphereLayerConfig]) -> None:
    if not layers:
        raise AtmosphereProfileError("layers must contain at least one layer.")
    total = float(sum(layer.cn2_weight for layer in layers))
    if not math.isfinite(total):
        raise AtmosphereProfileError(f"Layer weight sum must be finite; got {total!r}.")
    if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=LAYER_WEIGHT_ABS_TOL):
        raise AtmosphereProfileError(f"Layer weights must sum to 1.0; got {total:.12g}.")


def _require_grid_inputs(
    n_grid: int,
    diameter_m: float,
    n_steps: int,
    dt_s: float,
    wavelength_m: float,
) -> None:
    if n_grid <= 0:
        raise AtmosphereProfileError("n_grid must be positive.")
    _require_positive("diameter_m", diameter_m)
    if n_steps <= 0:
        raise AtmosphereProfileError("n_steps must be positive.")
    if dt_s < 0:
        raise AtmosphereProfileError("dt_s must be non-negative.")
    _require_positive("wavelength_m", wavelength_m)


def _require_positive(field_name: str, value: float) -> None:
    _require_finite(field_name, value)
    if value <= 0:
        raise AtmosphereProfileError(f"{field_name} must be positive; got {value!r}.")


def _require_finite(field_name: str, value: float) -> None:
    if not math.isfinite(float(value)):
        raise AtmosphereProfileError(f"{field_name} must be finite; got {value!r}.")
