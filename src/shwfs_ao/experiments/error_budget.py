# Error-budget scenarios populate an 8-row ScenarioResult table with finite OPD RMS, J/H/K Strehl, EE50/EE80, command, saturation, and centroid-validity metrics.

"""Error-budget scenario runner for the realistic 2 m AO demonstrator.

This module is the physical owner of the frozen AO-REF-011 error-budget
scenario API.  The installed legacy module is an identity-preserving facade.

This module assembles the detector calibration, DM model, interaction matrix, loop history, and science metrics into a compact
scenario table. The default scenarios are synthetic fast-mode proxies intended
for notebook 11 and CI-scale tests, not calibrated observatory predictions.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import math
from typing import Any, Mapping, Sequence

import numpy as np
from scipy import ndimage

from ..legacy.ao_closed_loop import (
    DetectorLoopConfig,
    LoopHistory,
    run_detector_integrator_loop,
)
from ..legacy.ao_diagnostics import (
    ScienceBandpass,
    band_averaged_psf_metrics_from_opd,
    phase_rad_to_opd_nm,
    remove_piston_opd_nm,
    residual_opd_nm_from_command,
    top_hat_bandpass,
)
from ..core.hashing import stable_array_descriptor
from ..core.provenance import ALLOWED_SOURCE_CLASSES, Provenance as _Provenance
from ..legacy.dm_model import DMConfig, DMModel, synthesize_dm_phase_rad
from ..legacy.interaction_matrix import PokeMtxResult, expand_controlled_commands
from ..legacy.synthetic_instrument_data import DetectorShwfsCalibration


DEFAULT_SCENARIO_SOURCE_CLASS = "synthetic_assumed"
DEFAULT_SCENARIO_SOURCE_NOTE = (
    "Synthetic fast-mode error-budget scenario; uses local detector, DM, "
    "controller, and science-metric proxies rather than measured AO telemetry."
)
REQUIRED_SCENARIO_NAMES = (
    "ideal_static",
    "dynamic_multilayer_proxy",
    "detector_noise",
    "latency",
    "stroke_limit",
    "misregistration",
    "ncpa",
    "all_effects",
)
DEFAULT_J_BAND = (1.10e-6, 1.40e-6)
DEFAULT_H_BAND = (1.50e-6, 1.80e-6)
DEFAULT_K_BAND = (2.00e-6, 2.35e-6)
NM_PER_M = 1.0e9
PHASE_TWO_PI = 2.0 * np.pi


class AOErrorBudgetError(ValueError):
    """Raised when an error-budget scenario or table is invalid."""


@dataclass(frozen=True)
class ScenarioConfig:
    """Configuration for one error-budget scenario.

    Args:
        scenario_name: Stable scenario name.
        enabled_effects: Tuple of effect labels reported in the table.
        n_steps: Number of loop frames.
        dynamic_phase: Whether to use a time-varying multi-component phase
            sequence instead of a repeated static phase.
        phase_amplitude_nm: Synthetic OPD-equivalent command amplitude used to
            build the input phase sequence. Public-data-informed callers derive
            this strength proxy from seeing/r0 rather than treating it as a
            measured wavefront amplitude.
        gain: Integrator gain.
        leak: Integrator leak.
        latency_frames: Command latency in frames.
        include_detector_noise: Whether detector noise is applied during WFS
            measurement.
        stroke_limit_nm: Optional scenario-specific DM stroke limit.
        misregistration_shift_px: Sub-pixel x/y shift applied to the true
            science-path DM correction as part of the WFS-DM registration proxy.
        misregistration_rotation_deg: Rotation (degrees) of the science-path DM
            correction about the pupil centre.
        misregistration_magnification: Isotropic magnification of the
            science-path DM correction (1.0 = none).
        misregistration_shear: Shear coefficient of the science-path DM
            correction.
        ncpa_rms_nm: Static science-path NCPA RMS added after WFS correction.
        tau0_s: Atmospheric coherence time used by the seconds-based temporal
            proxy.
        turbulence_speed_m_s: Effective turbulence speed used by the temporal
            advection proxy.
        seed: Legacy deterministic fallback seed. It is used only for a random
            domain whose corresponding explicit seed is ``None``.
        phase_seed: Seed for atmospheric truth generation.
        detector_noise_seed: Seed for detector noise in the WFS loop.
        ncpa_seed: Seed for the static NCPA orientation.
        source_class: Provenance class from the documented source-class taxonomy.
        source_note: Human-readable provenance note.

    Returns:
        Immutable scenario configuration.

    Raises:
        AOErrorBudgetError: If numerical settings or provenance are invalid.

    Physics note:
        ``phase_amplitude_nm`` and the scenario effects are synthetic control
        studies. Dynamic phases use ``time_s = frame / frame_rate_hz`` plus
        ``tau0_s`` and ``turbulence_speed_m_s`` in a compact controlled-subspace
        temporal proxy. This is not a frozen-flow phase-screen or measured
        telescope state.
    """

    scenario_name: str
    enabled_effects: tuple[str, ...]
    n_steps: int = 24
    dynamic_phase: bool = True
    phase_amplitude_nm: float = 400.0
    gain: float = 0.32
    leak: float = 0.02
    latency_frames: int = 0
    frame_rate_hz: float = 500.0
    include_detector_noise: bool = False
    stroke_limit_nm: float | None = None
    misregistration_shift_px: tuple[float, float] = (0.0, 0.0)
    misregistration_rotation_deg: float = 0.0
    misregistration_magnification: float = 1.0
    misregistration_shear: float = 0.0
    ncpa_rms_nm: float = 0.0
    tau0_s: float = 0.004
    turbulence_speed_m_s: float = 10.0
    seed: int = 1
    phase_seed: int | None = None
    detector_noise_seed: int | None = None
    ncpa_seed: int | None = None
    source_class: str = DEFAULT_SCENARIO_SOURCE_CLASS
    source_note: str = DEFAULT_SCENARIO_SOURCE_NOTE

    def __post_init__(self) -> None:
        if not str(self.scenario_name).strip():
            raise AOErrorBudgetError("scenario_name must be non-empty.")
        if not self.enabled_effects:
            raise AOErrorBudgetError("enabled_effects must contain at least one label.")
        _require_integer("n_steps", self.n_steps, minimum=2)
        _require_positive("phase_amplitude_nm", self.phase_amplitude_nm)
        _require_nonnegative("gain", self.gain)
        if not (0.0 <= float(self.leak) < 1.0):
            raise AOErrorBudgetError("leak must satisfy 0 <= leak < 1.")
        _require_integer("latency_frames", self.latency_frames, minimum=0)
        _require_positive("frame_rate_hz", self.frame_rate_hz)
        if self.stroke_limit_nm is not None:
            _require_positive("stroke_limit_nm", self.stroke_limit_nm)
        if len(self.misregistration_shift_px) != 2:
            raise AOErrorBudgetError("misregistration_shift_px must contain two values (x, y).")
        _require_finite("misregistration_shift_px[0]", self.misregistration_shift_px[0])
        _require_finite("misregistration_shift_px[1]", self.misregistration_shift_px[1])
        _require_finite("misregistration_rotation_deg", self.misregistration_rotation_deg)
        _require_finite("misregistration_shear", self.misregistration_shear)
        _require_positive("misregistration_magnification", self.misregistration_magnification)
        _require_nonnegative("ncpa_rms_nm", self.ncpa_rms_nm)
        _require_positive("tau0_s", self.tau0_s)
        _require_nonnegative("turbulence_speed_m_s", self.turbulence_speed_m_s)
        _validate_source(self.source_class, self.source_note)

    @property
    def provenance(self) -> _Provenance:
        """Return the canonical provenance record for this scenario."""

        return _scenario_provenance(self.source_class, self.source_note)

    @property
    def resolved_phase_seed(self) -> int:
        """Return the phase-truth seed, with legacy ``seed`` fallback."""

        return int(self.seed if self.phase_seed is None else self.phase_seed)

    @property
    def resolved_detector_noise_seed(self) -> int:
        """Return the detector-noise seed, with legacy ``seed`` fallback."""

        return int(self.seed if self.detector_noise_seed is None else self.detector_noise_seed)

    @property
    def resolved_ncpa_seed(self) -> int:
        """Return the NCPA seed, with legacy ``seed`` fallback."""

        return int(self.seed if self.ncpa_seed is None else self.ncpa_seed)

    @property
    def time_s(self) -> np.ndarray:
        """Return loop-frame timestamps in physical seconds."""

        return np.arange(int(self.n_steps), dtype=float) / float(self.frame_rate_hz)


@dataclass(frozen=True)
class ScenarioResult:
    """One row of the error-budget table.

    Required shared fields are ``scenario_name``, ``enabled_effects``,
    ``open_rms_nm``, ``closed_rms_nm``, ``strehl_J/H/K``, ``ee50_J/H/K``,
    and ``source_class``.
    """

    scenario_name: str
    enabled_effects: tuple[str, ...]
    open_rms_nm: float
    closed_rms_nm: float
    strehl_J: float
    strehl_H: float
    strehl_K: float
    ee50_J: float
    ee50_H: float
    ee50_K: float
    source_class: str
    ee80_J: float
    ee80_H: float
    ee80_K: float
    command_rms_nm: float
    command_peak_nm: float
    saturated_actuator_frac: float
    valid_centroid_frac: float
    open_strehl_H: float
    closed_over_open_rms: float
    config_hash: str
    source_note: str = DEFAULT_SCENARIO_SOURCE_NOTE

    def __post_init__(self) -> None:
        if not str(self.scenario_name).strip():
            raise AOErrorBudgetError("ScenarioResult scenario_name must be non-empty.")
        if not self.enabled_effects:
            raise AOErrorBudgetError("ScenarioResult enabled_effects must not be empty.")
        _validate_source(self.source_class, self.source_note)
        for field_name in (
            "open_rms_nm",
            "closed_rms_nm",
            "strehl_J",
            "strehl_H",
            "strehl_K",
            "ee50_J",
            "ee50_H",
            "ee50_K",
            "ee80_J",
            "ee80_H",
            "ee80_K",
            "command_rms_nm",
            "command_peak_nm",
            "saturated_actuator_frac",
            "valid_centroid_frac",
            "open_strehl_H",
            "closed_over_open_rms",
        ):
            _require_finite(field_name, getattr(self, field_name))
        for field_name in ("strehl_J", "strehl_H", "strehl_K", "open_strehl_H"):
            _require_fraction(field_name, getattr(self, field_name), upper=1.5)
        for field_name in ("saturated_actuator_frac", "valid_centroid_frac"):
            _require_fraction(field_name, getattr(self, field_name), upper=1.0)
        if len(self.config_hash) != 64:
            raise AOErrorBudgetError("ScenarioResult config_hash must be a SHA-256 hex digest.")

    def as_dict(self) -> dict[str, float | str]:
        return {
            "scenario_name": self.scenario_name,
            "enabled_effects": "+".join(self.enabled_effects),
            "open_rms_nm": self.open_rms_nm,
            "closed_rms_nm": self.closed_rms_nm,
            "closed_over_open_rms": self.closed_over_open_rms,
            "strehl_J": self.strehl_J,
            "strehl_H": self.strehl_H,
            "strehl_K": self.strehl_K,
            "open_strehl_H": self.open_strehl_H,
            "ee50_J": self.ee50_J,
            "ee50_H": self.ee50_H,
            "ee50_K": self.ee50_K,
            "ee80_J": self.ee80_J,
            "ee80_H": self.ee80_H,
            "ee80_K": self.ee80_K,
            "command_rms_nm": self.command_rms_nm,
            "command_peak_nm": self.command_peak_nm,
            "saturated_actuator_frac": self.saturated_actuator_frac,
            "valid_centroid_frac": self.valid_centroid_frac,
            "source_class": self.source_class,
            "source_note": self.source_note,
            "config_hash": self.config_hash,
        }


def default_error_budget_scenarios(
    n_steps: int = 24,
    phase_amplitude_nm: float = 400.0,
) -> tuple[ScenarioConfig, ...]:
    """Return the required 8-row fast scenario matrix."""

    common = {
        "n_steps": int(n_steps),
        "phase_amplitude_nm": float(phase_amplitude_nm),
        "phase_seed": 101,
        "detector_noise_seed": 211,
        "ncpa_seed": 307,
        "source_class": DEFAULT_SCENARIO_SOURCE_CLASS,
        "source_note": DEFAULT_SCENARIO_SOURCE_NOTE,
    }
    return (
        ScenarioConfig(
            "ideal_static",
            ("static_phase", "ideal_detector", "zero_latency", "high_stroke"),
            dynamic_phase=False,
            gain=0.35,
            leak=0.0,
            **common,
        ),
        ScenarioConfig(
            "dynamic_multilayer_proxy",
            ("multi_component_dynamic_phase",),
            **common,
        ),
        ScenarioConfig(
            "detector_noise",
            ("multi_component_dynamic_phase", "detector_noise"),
            include_detector_noise=True,
            **common,
        ),
        ScenarioConfig(
            "latency",
            ("multi_component_dynamic_phase", "latency_2_frames"),
            latency_frames=2,
            **common,
        ),
        ScenarioConfig(
            "stroke_limit",
            ("multi_component_dynamic_phase", "dm_stroke_limit"),
            stroke_limit_nm=120.0,
            **common,
        ),
        ScenarioConfig(
            "misregistration",
            ("multi_component_dynamic_phase", "wfs_dm_misregistration_proxy"),
            misregistration_shift_px=(0.6, 0.0),
            misregistration_rotation_deg=0.2,
            misregistration_magnification=1.01,
            **common,
        ),
        ScenarioConfig(
            "ncpa",
            ("multi_component_dynamic_phase", "science_path_ncpa"),
            ncpa_rms_nm=45.0,
            **common,
        ),
        ScenarioConfig(
            "all_effects",
            (
                "multi_component_dynamic_phase",
                "detector_noise",
                "latency_2_frames",
                "dm_stroke_limit",
                "wfs_dm_misregistration_proxy",
                "science_path_ncpa",
            ),
            include_detector_noise=True,
            latency_frames=2,
            stroke_limit_nm=120.0,
            misregistration_shift_px=(0.6, 0.0),
            misregistration_rotation_deg=0.2,
            misregistration_magnification=1.01,
            ncpa_rms_nm=45.0,
            **common,
        ),
    )


def default_jhk_bandpasses() -> tuple[ScienceBandpass, ScienceBandpass, ScienceBandpass]:
    """Return J/H/K top-hat fallback bandpasses for tables."""

    return (
        top_hat_bandpass("J", *DEFAULT_J_BAND, source_note="Synthetic J top-hat fallback."),
        top_hat_bandpass("H", *DEFAULT_H_BAND, source_note="Synthetic H top-hat fallback."),
        top_hat_bandpass("K", *DEFAULT_K_BAND, source_note="Synthetic K top-hat fallback."),
    )


def run_error_budget_scenarios(
    calibration: DetectorShwfsCalibration,
    dm_model: DMModel,
    poke_result: PokeMtxResult,
    scenarios: Sequence[ScenarioConfig] | None = None,
    bandpasses: Sequence[ScienceBandpass] | None = None,
    telescope_diameter_m: float = 2.0,
    pad_factor: int = 4,
) -> tuple[ScenarioResult, ...]:
    """Run the scenario matrix and return finite error-budget rows."""

    scenario_list = tuple(default_error_budget_scenarios() if scenarios is None else scenarios)
    if len(scenario_list) != len(REQUIRED_SCENARIO_NAMES):
        raise AOErrorBudgetError(
            f"Scenario matrix must contain {len(REQUIRED_SCENARIO_NAMES)} scenarios; got {len(scenario_list)}."
        )
    names = tuple(config.scenario_name for config in scenario_list)
    if names != REQUIRED_SCENARIO_NAMES:
        raise AOErrorBudgetError(f"Scenario names must be {REQUIRED_SCENARIO_NAMES}; got {names}.")
    bands = tuple(default_jhk_bandpasses() if bandpasses is None else bandpasses)
    _validate_jhk_bandpasses(bands)
    _validate_inputs(calibration, dm_model, poke_result)
    _require_positive("telescope_diameter_m", telescope_diameter_m)
    if int(pad_factor) < 1:
        raise AOErrorBudgetError("pad_factor must be >= 1.")

    rows = tuple(
        run_error_budget_scenario(
            calibration,
            dm_model,
            poke_result,
            scenario,
            bands,
            telescope_diameter_m=telescope_diameter_m,
            pad_factor=pad_factor,
        )
        for scenario in scenario_list
    )
    _validate_scenario_results(rows)
    return rows


def run_error_budget_scenario(
    calibration: DetectorShwfsCalibration,
    dm_model: DMModel,
    poke_result: PokeMtxResult,
    scenario: ScenarioConfig,
    bandpasses: Sequence[ScienceBandpass],
    telescope_diameter_m: float = 2.0,
    pad_factor: int = 4,
) -> ScenarioResult:
    """Run one scenario and reduce it to a table row."""

    _validate_inputs(calibration, dm_model, poke_result)
    _validate_jhk_bandpasses(tuple(bandpasses))
    phase_sequence = build_control_space_phase_sequence(calibration, dm_model, poke_result, scenario)
    control_dm_model = _dm_with_stroke_limit(dm_model, scenario.stroke_limit_nm)
    loop_config = DetectorLoopConfig(
        n_steps=scenario.n_steps,
        gain=scenario.gain,
        leak=scenario.leak,
        latency_frames=scenario.latency_frames,
        frame_rate_hz=scenario.frame_rate_hz,
        include_detector_noise=scenario.include_detector_noise,
        seed=scenario.resolved_detector_noise_seed,
        source_class=scenario.source_class,
        source_note=scenario.source_note,
    )
    history = run_detector_integrator_loop(phase_sequence, calibration, control_dm_model, poke_result, loop_config)
    return summarize_scenario(
        phase_sequence,
        history,
        calibration,
        control_dm_model,
        scenario,
        tuple(bandpasses),
        telescope_diameter_m=telescope_diameter_m,
        pad_factor=pad_factor,
    )


def build_control_space_phase_sequence(
    calibration: DetectorShwfsCalibration,
    dm_model: DMModel,
    poke_result: PokeMtxResult,
    scenario: ScenarioConfig,
) -> np.ndarray:
    """Build a seconds-based temporal proxy in the controlled DM subspace.

    The proxy uses physical frame timestamps, atmospheric coherence time, and
    an effective wind crossing time. It remains deliberately compact for CI
    and is not a substitute for :func:`generate_multilayer_phase_cube`.
    """

    _validate_inputs(calibration, dm_model, poke_result)
    rng = np.random.default_rng(scenario.resolved_phase_seed)
    n_controlled = poke_result.n_controlled_actuators
    base = np.zeros(n_controlled, dtype=float)
    indices = np.linspace(0, n_controlled - 1, num=min(6, n_controlled), dtype=int)
    weights = np.asarray([1.00, -0.80, 0.60, 0.45, -0.35, 0.25], dtype=float)[: indices.size]
    base[indices] = scenario.phase_amplitude_nm * weights
    if n_controlled > 3:
        base[n_controlled // 3] += 0.25 * scenario.phase_amplitude_nm
    time_s = scenario.time_s
    dt_s = 1.0 / float(scenario.frame_rate_hz)
    correlation = math.exp(-dt_s / float(scenario.tau0_s))
    innovation_scale = math.sqrt(max(0.0, 1.0 - correlation**2))
    jitter_state = rng.normal(scale=0.01 * scenario.phase_amplitude_nm, size=n_controlled)
    diameter_m = float(dm_model.config.telescope_diameter_m)
    wind_cycles_per_s = float(scenario.turbulence_speed_m_s) / diameter_m
    phase_maps = []
    for step, t_s in enumerate(time_s):
        if scenario.dynamic_phase:
            coherence_phase = 2.0 * np.pi * t_s / (8.0 * float(scenario.tau0_s))
            wind_phase = 2.0 * np.pi * wind_cycles_per_s * t_s
            scale = 0.78 + 0.18 * np.sin(coherence_phase + 0.25 * wind_phase)
            drift = np.zeros_like(base)
            drift[(indices + 1) % n_controlled] += 0.15 * scenario.phase_amplitude_nm * np.sin(
                2.0 * np.pi * t_s / (5.0 * float(scenario.tau0_s)) + wind_phase
            )
            drift[(indices + 2) % n_controlled] += 0.10 * scenario.phase_amplitude_nm * np.cos(
                2.0 * np.pi * t_s / (7.0 * float(scenario.tau0_s)) - 0.5 * wind_phase
            )
            if step > 0:
                innovation = rng.normal(scale=0.01 * scenario.phase_amplitude_nm, size=n_controlled)
                jitter_state = correlation * jitter_state + innovation_scale * innovation
            controlled_commands = scale * base + drift + jitter_state
        else:
            controlled_commands = base
        full_commands = expand_controlled_commands(controlled_commands, poke_result, dm_model)
        phase_rad, _ = synthesize_dm_phase_rad(
            full_commands,
            dm_model,
            wavelength_m=calibration.geometry.wfs_wavelength_m,
            remove_piston=True,
        )
        _assert_masked_finite(phase_rad, dm_model.pupil_mask, f"scenario phase step {step}")
        phase_maps.append(phase_rad)
    return np.asarray(phase_maps, dtype=float)


def summarize_scenario(
    phase_sequence_rad: np.ndarray,
    history: LoopHistory,
    calibration: DetectorShwfsCalibration,
    dm_model: DMModel,
    scenario: ScenarioConfig,
    bandpasses: Sequence[ScienceBandpass],
    telescope_diameter_m: float = 2.0,
    pad_factor: int = 4,
) -> ScenarioResult:
    """Reduce one loop history into the ScenarioResult contract."""

    tail_indices = np.arange(int(scenario.n_steps) // 2, int(scenario.n_steps))
    if tail_indices.size == 0:
        raise AOErrorBudgetError("Scenario tail window is empty.")
    ncpa_opd_nm = _science_path_ncpa_nm(dm_model, scenario)

    open_rms = []
    closed_rms = []
    open_h_strehl = []
    metrics_by_band: dict[str, dict[str, list[float]]] = {
        band.name: {"strehl": [], "ee50": [], "ee80": []} for band in bandpasses
    }
    for step in tail_indices:
        atmosphere_phase = phase_sequence_rad[int(step)]
        open_opd = phase_rad_to_opd_nm(
            atmosphere_phase,
            calibration.geometry.wfs_wavelength_m,
            dm_model.pupil_mask,
        )
        closed_opd = _closed_residual_opd_nm(
            atmosphere_phase,
            history.command_history_nm[int(step)],
            dm_model,
            calibration.geometry.wfs_wavelength_m,
            scenario,
        )
        if ncpa_opd_nm is not None:
            open_opd = remove_piston_opd_nm(open_opd + ncpa_opd_nm, dm_model.pupil_mask)
            closed_opd = remove_piston_opd_nm(closed_opd + ncpa_opd_nm, dm_model.pupil_mask)
        open_rms.append(_opd_rms_nm(open_opd, dm_model.pupil_mask))
        closed_rms.append(_opd_rms_nm(closed_opd, dm_model.pupil_mask))
        for band in bandpasses:
            open_metrics = band_averaged_psf_metrics_from_opd(
                open_opd,
                dm_model.pupil_mask,
                band,
                telescope_diameter_m=telescope_diameter_m,
                case_name=f"{scenario.scenario_name}_open",
                pad_factor=pad_factor,
            )
            closed_metrics = band_averaged_psf_metrics_from_opd(
                closed_opd,
                dm_model.pupil_mask,
                band,
                telescope_diameter_m=telescope_diameter_m,
                case_name=scenario.scenario_name,
                pad_factor=pad_factor,
            )
            if band.name == "H":
                open_h_strehl.append(open_metrics.strehl_peak)
            metrics_by_band[band.name]["strehl"].append(closed_metrics.strehl_peak)
            metrics_by_band[band.name]["ee50"].append(closed_metrics.ee50_lambda_over_d)
            metrics_by_band[band.name]["ee80"].append(closed_metrics.ee80_lambda_over_d)

    settings = {
        "hash_schema": 2,
        "scenario": scenario.__dict__,
        "loop_config_hash": history.config_hash,
        "phase_sequence_rad": phase_sequence_rad,
        "bandpasses": [
            {
                "name": band.name,
                "wavelength_m": band.wavelength_m,
                "transmission": band.transmission,
                "source_class": band.source_class,
                "source_note": band.source_note,
                "filter_id": band.filter_id,
            }
            for band in bandpasses
        ],
        "telescope_diameter_m": float(telescope_diameter_m),
        "pad_factor": int(pad_factor),
        "tail_indices": tail_indices.astype(int).tolist(),
    }
    open_rms_value = float(np.median(open_rms))
    closed_rms_value = float(np.median(closed_rms))
    result = ScenarioResult(
        scenario_name=scenario.scenario_name,
        enabled_effects=scenario.enabled_effects,
        open_rms_nm=open_rms_value,
        closed_rms_nm=closed_rms_value,
        strehl_J=_median_band(metrics_by_band, "J", "strehl"),
        strehl_H=_median_band(metrics_by_band, "H", "strehl"),
        strehl_K=_median_band(metrics_by_band, "K", "strehl"),
        ee50_J=_median_band(metrics_by_band, "J", "ee50"),
        ee50_H=_median_band(metrics_by_band, "H", "ee50"),
        ee50_K=_median_band(metrics_by_band, "K", "ee50"),
        source_class=scenario.source_class,
        ee80_J=_median_band(metrics_by_band, "J", "ee80"),
        ee80_H=_median_band(metrics_by_band, "H", "ee80"),
        ee80_K=_median_band(metrics_by_band, "K", "ee80"),
        command_rms_nm=float(np.median(history.command_rms_nm[tail_indices])),
        command_peak_nm=float(np.max(np.abs(history.command_history_nm[tail_indices]))),
        saturated_actuator_frac=float(np.median(history.saturation_fraction[tail_indices])),
        valid_centroid_frac=float(np.median(history.valid_centroid_frac[tail_indices])),
        open_strehl_H=float(np.median(open_h_strehl)),
        closed_over_open_rms=closed_rms_value / open_rms_value if open_rms_value > 0 else float("inf"),
        config_hash=_config_hash(settings),
        source_note=scenario.source_note,
    )
    return result


def scenario_results_as_dicts(results: Sequence[ScenarioResult]) -> tuple[dict[str, float | str], ...]:
    """Convert scenario results into CSV/DataFrame-friendly dictionaries."""

    return tuple(result.as_dict() for result in results)


def _has_misregistration(scenario: ScenarioConfig) -> bool:
    """Return True if any affine WFS-DM misregistration term is non-identity."""

    shift_x, shift_y = float(scenario.misregistration_shift_px[0]), float(scenario.misregistration_shift_px[1])
    return (
        shift_x != 0.0
        or shift_y != 0.0
        or float(scenario.misregistration_rotation_deg) != 0.0
        or float(scenario.misregistration_magnification) != 1.0
        or float(scenario.misregistration_shear) != 0.0
    )


def _closed_residual_opd_nm(
    atmosphere_phase_rad: np.ndarray,
    command_nm: Sequence[float],
    dm_model: DMModel,
    reference_wavelength_m: float,
    scenario: ScenarioConfig,
) -> np.ndarray:
    if not _has_misregistration(scenario):
        return residual_opd_nm_from_command(atmosphere_phase_rad, command_nm, dm_model, reference_wavelength_m)

    dm_phase, _ = synthesize_dm_phase_rad(
        command_nm,
        dm_model,
        wavelength_m=reference_wavelength_m,
        remove_piston=True,
    )
    misregistered_dm_phase = _affine_misregister_phase(
        dm_phase,
        dm_model.pupil_mask,
        shift_px=(float(scenario.misregistration_shift_px[0]), float(scenario.misregistration_shift_px[1])),
        rotation_deg=float(scenario.misregistration_rotation_deg),
        magnification=float(scenario.misregistration_magnification),
        shear=float(scenario.misregistration_shear),
    )
    residual_phase = np.asarray(atmosphere_phase_rad, dtype=float) - misregistered_dm_phase
    return phase_rad_to_opd_nm(residual_phase, reference_wavelength_m, dm_model.pupil_mask)


def _affine_misregister_phase(
    dm_phase_rad: np.ndarray,
    pupil_mask: np.ndarray,
    shift_px: tuple[float, float],
    rotation_deg: float,
    magnification: float,
    shear: float,
) -> np.ndarray:
    """Apply a synthetic WFS-DM affine misregistration to a DM phase map.

    Args:
        dm_phase_rad: Synthesized DM phase (radians) on the pupil grid; NaN
            outside the pupil.
        pupil_mask: Boolean pupil mask.
        shift_px: Sub-pixel ``(x, y)`` translation in detector/grid pixels.
        rotation_deg: Rotation about the pupil centre in degrees.
        magnification: Isotropic magnification (1.0 = none).
        shear: Shear coefficient applied to the x-coordinate.

    Returns:
        The misregistered DM phase remasked to the pupil (NaN outside).

    Physics note:
        Models the geometric mismatch between the calibrated DM/WFS grid and the
        true science-path projection. The forward affine maps grid coordinates
        about the pupil centre; bilinear resampling (order 1) keeps the proxy
        finite. This is a synthetic engineering proxy, not a measured alignment
        state.
    """

    filled = np.nan_to_num(np.asarray(dm_phase_rad, dtype=float), nan=0.0)
    ny, nx = filled.shape
    center = np.array([(ny - 1) / 2.0, (nx - 1) / 2.0])  # (row=y, col=x)
    theta = math.radians(rotation_deg)
    # Forward linear map about the centre in (y, x) order: magnify, rotate, shear.
    rotation = np.array([[math.cos(theta), -math.sin(theta)], [math.sin(theta), math.cos(theta)]])
    shear_matrix = np.array([[1.0, 0.0], [shear, 1.0]])  # new_x = x + shear * y
    forward = magnification * (rotation @ shear_matrix)
    inverse = np.linalg.inv(forward)
    # misregistration_shift_px is (x, y); affine_transform works in (row, col)=(y, x).
    shift_vec = np.array([float(shift_px[1]), float(shift_px[0])])
    # affine_transform samples input at (matrix @ output_coord + offset).
    offset = center - inverse @ (center + shift_vec)
    transformed = ndimage.affine_transform(
        filled,
        inverse,
        offset=offset,
        order=1,
        mode="constant",
        cval=0.0,
        prefilter=False,
    )
    if not np.all(np.isfinite(transformed)):
        raise AOErrorBudgetError(
            "Non-finite values after affine misregistration; "
            f"rotation_deg={rotation_deg}, magnification={magnification}, shear={shear}."
        )
    return np.where(pupil_mask, transformed, np.nan)


def _science_path_ncpa_nm(dm_model: DMModel, scenario: ScenarioConfig) -> np.ndarray | None:
    if scenario.ncpa_rms_nm <= 0.0:
        return None
    x = np.asarray(dm_model.x_m, dtype=float)
    y = np.asarray(dm_model.y_m, dtype=float)
    radius = max(float(np.nanmax(np.sqrt(x[dm_model.pupil_mask] ** 2 + y[dm_model.pupil_mask] ** 2))), 1.0e-12)
    xn = x / radius
    yn = y / radius
    ncpa_seed = scenario.resolved_ncpa_seed
    seed_angle = (ncpa_seed % 17) * np.pi / 17.0
    # NCPA = low-order Zernike-like + mid-spatial-frequency ripple + static
    # polishing-like high-spatial-frequency component (synthetic engineering map).
    low_order = (
        0.65 * (xn**2 - yn**2) * np.cos(seed_angle)
        + 0.45 * xn * yn * np.sin(seed_angle + 0.3)
        + 0.30 * (2.0 * (xn**2 + yn**2) - 1.0)
    )
    ripple = 0.10 * np.sin(5.0 * np.pi * xn + 0.4 * ncpa_seed) * np.cos(4.0 * np.pi * yn)
    polishing = (
        0.06 * np.cos(9.0 * np.pi * xn + 0.7 * seed_angle) * np.cos(8.0 * np.pi * yn - 0.5 * seed_angle)
        + 0.05 * np.sin(11.0 * np.pi * xn - 0.3 * seed_angle) * np.sin(10.0 * np.pi * yn + 0.6 * seed_angle)
    )
    ncpa = np.where(dm_model.pupil_mask, low_order + ripple + polishing, np.nan)
    ncpa = remove_piston_opd_nm(ncpa, dm_model.pupil_mask)
    rms = _opd_rms_nm(ncpa, dm_model.pupil_mask)
    if rms <= 0.0:
        raise AOErrorBudgetError("Generated NCPA map has zero RMS.")
    return remove_piston_opd_nm(ncpa * float(scenario.ncpa_rms_nm) / rms, dm_model.pupil_mask)


def _dm_with_stroke_limit(dm_model: DMModel, stroke_limit_nm: float | None) -> DMModel:
    if stroke_limit_nm is None:
        return dm_model
    new_config = replace(dm_model.config, stroke_limit_nm=float(stroke_limit_nm))
    return DMModel(
        config=new_config,
        x_m=dm_model.x_m,
        y_m=dm_model.y_m,
        pupil_mask=dm_model.pupil_mask,
        actuator_centers_m=dm_model.actuator_centers_m,
        actuator_pitch_m=dm_model.actuator_pitch_m,
        influence_functions=dm_model.influence_functions,
        dead_actuator_mask=dm_model.dead_actuator_mask,
        stuck_actuator_mask=dm_model.stuck_actuator_mask,
    )


def _validate_inputs(calibration: DetectorShwfsCalibration, dm_model: DMModel, poke_result: PokeMtxResult) -> None:
    if calibration.x_m.shape != dm_model.x_m.shape:
        raise AOErrorBudgetError("Calibration and DM grid shapes differ.")
    if not np.array_equal(calibration.pupil_mask, dm_model.pupil_mask):
        raise AOErrorBudgetError("Calibration and DM pupil masks differ.")
    if poke_result.poke_matrix.shape[1] != poke_result.n_controlled_actuators:
        raise AOErrorBudgetError("Poke matrix column count does not match controlled actuator count.")
    _assert_all_finite(poke_result.poke_matrix, "poke matrix")


def _validate_jhk_bandpasses(bandpasses: Sequence[ScienceBandpass]) -> None:
    names = tuple(band.name for band in bandpasses)
    if names != ("J", "H", "K"):
        raise AOErrorBudgetError(f"Bandpasses must be ordered as ('J', 'H', 'K'); got {names}.")


def _validate_scenario_results(results: Sequence[ScenarioResult]) -> None:
    if len(results) != len(REQUIRED_SCENARIO_NAMES):
        raise AOErrorBudgetError("ScenarioResult table does not have 8 rows.")
    for result in results:
        if result.scenario_name not in REQUIRED_SCENARIO_NAMES:
            raise AOErrorBudgetError(f"Unexpected scenario_name={result.scenario_name!r}.")
        result.__post_init__()


def _median_band(metrics_by_band: Mapping[str, Mapping[str, list[float]]], band_name: str, field_name: str) -> float:
    try:
        values = np.asarray(metrics_by_band[band_name][field_name], dtype=float)
    except KeyError as exc:
        raise AOErrorBudgetError(f"Missing {field_name} metrics for band {band_name!r}.") from exc
    _assert_all_finite(values, f"{band_name} {field_name} metrics")
    if values.size == 0:
        raise AOErrorBudgetError(f"No {field_name} metrics for band {band_name!r}.")
    return float(np.median(values))


def _opd_rms_nm(opd_nm: np.ndarray, pupil_mask: np.ndarray) -> float:
    samples = np.asarray(opd_nm, dtype=float)[pupil_mask]
    samples = samples[np.isfinite(samples)]
    if samples.size == 0:
        raise AOErrorBudgetError("No finite OPD samples are available for RMS calculation.")
    samples = samples - float(np.mean(samples))
    rms = float(np.sqrt(np.mean(samples**2)))
    _require_nonnegative("OPD RMS", rms)
    return rms


def _assert_masked_finite(values: np.ndarray, pupil_mask: np.ndarray, label: str) -> None:
    array = np.asarray(values, dtype=float)
    mask = np.asarray(pupil_mask, dtype=bool)
    if array.shape != mask.shape:
        raise AOErrorBudgetError(f"{label} shape {array.shape} != pupil mask shape {mask.shape}.")
    inside = array[mask]
    if not np.all(np.isfinite(inside)):
        finite_frac = float(np.mean(np.isfinite(inside))) if inside.size else 0.0
        raise AOErrorBudgetError(f"Non-finite values inside {label}; finite_frac={finite_frac:.3f}.")


def _assert_all_finite(values: np.ndarray, label: str) -> None:
    array = np.asarray(values, dtype=float)
    if not np.all(np.isfinite(array)):
        finite_frac = float(np.mean(np.isfinite(array))) if array.size else 0.0
        raise AOErrorBudgetError(f"Non-finite values in {label}; finite_frac={finite_frac:.3f}.")


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
    if isinstance(value, DMConfig):
        return _jsonable(value.__dict__)
    return value


def _validate_source(source_class: str, source_note: str) -> None:
    _scenario_provenance(source_class, source_note)


def _scenario_provenance(source_class: str, source_note: str) -> _Provenance:
    try:
        return _Provenance(source_class=source_class, source_note=str(source_note))
    except (TypeError, ValueError) as exc:
        if source_class not in ALLOWED_SOURCE_CLASSES:
            raise AOErrorBudgetError(
                f"source_class={source_class!r} is not in the permitted taxonomy {sorted(ALLOWED_SOURCE_CLASSES)}."
            ) from exc
        raise AOErrorBudgetError("source_note must be a non-empty string.") from exc


def _require_positive(field_name: str, value: float) -> None:
    _require_finite(field_name, value)
    if float(value) <= 0.0:
        raise AOErrorBudgetError(f"{field_name} must be positive; got {value!r}.")


def _require_nonnegative(field_name: str, value: float) -> None:
    _require_finite(field_name, value)
    if float(value) < 0.0:
        raise AOErrorBudgetError(f"{field_name} must be non-negative; got {value!r}.")


def _require_integer(field_name: str, value: int, minimum: int) -> None:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise AOErrorBudgetError(f"{field_name} must be an integer; got {value!r}.")
    if int(value) < int(minimum):
        raise AOErrorBudgetError(f"{field_name} must be >= {minimum}; got {value!r}.")


def _require_fraction(field_name: str, value: float, upper: float) -> None:
    _require_finite(field_name, value)
    if float(value) < 0.0 or float(value) > float(upper):
        raise AOErrorBudgetError(f"{field_name} must be between 0 and {upper}; got {value!r}.")


def _require_finite(field_name: str, value: float) -> None:
    if not math.isfinite(float(value)):
        raise AOErrorBudgetError(f"{field_name} must be finite; got {value!r}.")

__all__ = (
    "DEFAULT_SCENARIO_SOURCE_CLASS",
    "DEFAULT_SCENARIO_SOURCE_NOTE",
    "REQUIRED_SCENARIO_NAMES",
    "DEFAULT_J_BAND",
    "DEFAULT_H_BAND",
    "DEFAULT_K_BAND",
    "NM_PER_M",
    "PHASE_TWO_PI",
    "AOErrorBudgetError",
    "ScenarioConfig",
    "ScenarioResult",
    "default_error_budget_scenarios",
    "default_jhk_bandpasses",
    "run_error_budget_scenarios",
    "run_error_budget_scenario",
    "build_control_space_phase_sequence",
    "summarize_scenario",
    "scenario_results_as_dicts",
)
