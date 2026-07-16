# Fast end-to-end integration computes notebook-11 results in memory; the
# compatibility write flag delegates artifact creation to the canonical I/O layer.

"""End-to-end fast integration runner for the realistic 2 m SCAO demo.

This module assembles the existing simulation components without adding another
AO model. It is the notebook-11 compatibility entry point for the fast
detector-level 2 m SCAO demonstrator; serialization lives in
``shwfs_ao.io.artifacts``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path
# Historical compatibility export only. CSV serialization lives in
# ``shwfs_ao.io.artifacts`` and this module never calls the binding.
import csv
import hashlib
import json
import math
import time
from typing import Any, Sequence

import numpy as np

from .ao_closed_loop import DetectorLoopConfig
from .ao_diagnostics import bandpass_from_filter_curve, top_hat_bandpass
from .ao_error_budget import (
    REQUIRED_SCENARIO_NAMES,
    ScenarioConfig,
    ScenarioResult,
    build_control_space_phase_sequence,
    default_error_budget_scenarios,
    run_error_budget_scenario,
    run_error_budget_scenarios,
    scenario_results_as_dicts,
)
from .ao_validation import (
    ValidationCheckResult,
    ValidationScanResult,
    check_centroid_noise_photon_monotonicity,
    check_diffraction_scale,
    check_dm_fitting_trend,
    check_latency_residual_monotonicity,
    check_marechal_consistency,
    check_scenario_reproducibility,
    validation_results_as_dicts,
)
from ..core.provenance import ALLOWED_SOURCE_CLASSES, Provenance as _Provenance
from .data_sources import load_svo_filter_curve
from .dm_model import DMConfig, DMModel, build_dm_model
from .interaction_matrix import PokeMatrixConfig, PokeMtxResult, build_detector_dm_poke_matrix
from ..io.resources import open_text_resource, resource_exists
from .synthetic_instrument_data import DetectorConfig, DetectorShwfsCalibration, ShwfsGeometryConfig, build_detector_shwfs_calibration


# Frozen compatibility value only. Experiment execution and artifact writing
# never consult it; output-path policy belongs to ``shwfs_ao.io.artifacts``.
REPO_ROOT = Path(__file__).resolve().parents[3]
VALID_INTEGRATION_MODES = ("fast", "portfolio", "research")
DEFAULT_REFERENCE_METRICS_PATH = Path("data/reference_metrics/fast_reference_metrics.json")
DEFAULT_OUTPUT_DIR = Path("figures/detector_level_SCAO")
DEFAULT_INTEGRATION_SOURCE_CLASS = "synthetic_assumed"
DEFAULT_INTEGRATION_SOURCE_NOTE = (
    "Fast end-to-end detector-level 2 m SCAO integration using local "
    "synthetic/literature-inspired fixtures; not calibrated observatory AO telemetry."
)
REFERENCE_TOLERANCES = {
    "open_rms_nm_abs": 15.0,
    "closed_rms_nm_abs": 15.0,
    "h_strehl_abs": 0.04,
    "valid_centroid_fraction_abs": 1.0e-12,
    "kept_modes_abs": 0,
    "runtime_s_reference_max": 30.0,
}
REQUIRED_REFERENCE_FIELDS = (
    "open_rms_nm",
    "closed_rms_nm",
    "h_strehl",
    "valid_centroid_fraction",
    "kept_modes",
    "runtime_band",
)


class AOIntegrationError(ValueError):
    """Raised when the integration run violates its artifact contract."""


@dataclass(frozen=True)
class IntegrationConfig:
    """Configuration for the notebook-11 end-to-end integration run.

    The default values are deliberately small enough for local tests and CI.
    ``portfolio`` and ``research`` modes are exposed as reproducibility presets
    for heavier local reruns, but only ``fast`` is part of the automated check.
    """

    mode: str = "fast"
    telescope_diameter_m: float = 2.0
    n_pupil_pixels: int = 52
    n_lenslets: int = 5
    detector_window_px: int = 18
    pad_factor: int = 3
    photons_per_subap_frame: float = 8000.0
    read_noise_e: float = 1.0
    qe: float = 1.0
    n_actuators_across: int = 5
    coupling_width_pitch: float = 0.40
    stroke_limit_nm: float = 1000.0
    calibration_amplitude_nm: float = 10.0
    target_kept_mode_fraction: float = 1.0
    n_steps: int = 12
    phase_amplitude_nm: float = 260.0
    frame_rate_hz: float = 1000.0
    output_dir: Path | str = DEFAULT_OUTPUT_DIR
    reference_metrics_path: Path | str = DEFAULT_REFERENCE_METRICS_PATH
    source_class: str = DEFAULT_INTEGRATION_SOURCE_CLASS
    source_note: str = DEFAULT_INTEGRATION_SOURCE_NOTE

    @classmethod
    def from_mode(cls, mode: str, **overrides: Any) -> "IntegrationConfig":
        """Create a documented preset for fast, portfolio, or research reruns.

        Modes set numerical scale only (pupil/lenslet/actuator counts, loop
        length, detector-window margin). Observing difficulty is the job of
        :class:`~ao_conditions.ObservingConditionConfig`, so ``research`` is a
        bigger run, never a harder sky. Explicit keyword ``overrides`` still win
        (e.g. the public-data-informed demo injects condition photon/phase values).
        """

        if mode not in VALID_INTEGRATION_MODES:
            raise AOIntegrationError(f"mode must be one of {VALID_INTEGRATION_MODES}; got {mode!r}.")
        # Notebook 11 mode/condition separation: a mode controls NUMERICAL SCALE
        # ONLY -- pupil pixels, lenslet count, actuator count, loop length, and
        # detector-window margin. Observing difficulty (seeing -> phase
        # amplitude, photon budget, read noise, latency, stroke, NCPA,
        # misregistration) belongs to ObservingConditionConfig, never to the
        # mode preset. This keeps a heavier ``research`` rerun from silently
        # meaning worse seeing or a fainter guide star; both stay at the fast
        # defaults unless an observing condition (or explicit override) sets them.
        presets: dict[str, dict[str, Any]] = {
            "fast": {},
            "portfolio": {
                "n_pupil_pixels": 72,
                "n_lenslets": 7,
                "detector_window_px": 20,
                "n_actuators_across": 7,
                "n_steps": 18,
            },
            "research": {
                "n_pupil_pixels": 96,
                "n_lenslets": 9,
                "detector_window_px": 22,
                "n_actuators_across": 9,
                "n_steps": 30,
            },
        }
        values = {
            "mode": mode,
            "reference_metrics_path": Path(f"data/reference_metrics/{mode}_reference_metrics.json"),
            **presets[mode],
            **overrides,
        }
        return cls(**values)

    def __post_init__(self) -> None:
        if self.mode not in VALID_INTEGRATION_MODES:
            raise AOIntegrationError(f"mode must be one of {VALID_INTEGRATION_MODES}; got {self.mode!r}.")
        for name in (
            "telescope_diameter_m",
            "photons_per_subap_frame",
            "qe",
            "coupling_width_pitch",
            "stroke_limit_nm",
            "calibration_amplitude_nm",
            "phase_amplitude_nm",
            "frame_rate_hz",
        ):
            _require_positive(name, getattr(self, name))
        for name in ("n_pupil_pixels", "n_lenslets", "detector_window_px", "pad_factor", "n_actuators_across", "n_steps"):
            if int(getattr(self, name)) < 1:
                raise AOIntegrationError(f"{name} must be >= 1.")
        if int(self.n_steps) < 2:
            raise AOIntegrationError("n_steps must be >= 2.")
        if not (0.0 < float(self.target_kept_mode_fraction) <= 1.0):
            raise AOIntegrationError("target_kept_mode_fraction must be in (0, 1].")
        _require_nonnegative("read_noise_e", self.read_noise_e)
        _integration_provenance(self.source_class, self.source_note)
        object.__setattr__(self, "output_dir", Path(self.output_dir))
        object.__setattr__(self, "reference_metrics_path", Path(self.reference_metrics_path))

    @property
    def provenance(self) -> _Provenance:
        """Return the canonical provenance record for this integration config."""

        return _integration_provenance(self.source_class, self.source_note)


@dataclass(frozen=True)
class IntegrationRunResult:
    """Result bundle returned by the fast integration runner."""

    mode: str
    scenario_results: tuple[ScenarioResult, ...]
    validation_results: tuple[ValidationCheckResult | ValidationScanResult, ...]
    reference_metrics: dict[str, Any]
    written_files: tuple[Path, ...]
    runtime_s: float
    source_class: str
    config_hash: str

    @property
    def provenance(self) -> _Provenance:
        """Derive canonical provenance from legacy reference-metric fields."""

        return _Provenance.from_legacy_fields(self.reference_metrics)


@dataclass(frozen=True)
class _IntegrationSystem:
    calibration: DetectorShwfsCalibration
    dm_model: DMModel
    poke_result: PokeMtxResult


def run_fast_integration(
    config: IntegrationConfig | None = None,
    write_outputs: bool = True,
) -> IntegrationRunResult:
    """Run the fast end-to-end integration check.

    Args:
        config: Optional integration configuration. When omitted, the fast
            preset is used.
        write_outputs: Whether to write CSV/PNG artifacts and reference JSON.

    Returns:
        :class:`IntegrationRunResult` with finite scenario, validation, and
        reference-metric outputs.
    """

    chosen = IntegrationConfig.from_mode("fast") if config is None else config
    if chosen.mode != "fast":
        raise AOIntegrationError("run_fast_integration only accepts mode='fast'. Use IntegrationConfig.from_mode('fast').")
    return run_integration(chosen, write_outputs=write_outputs)


def run_integration(
    config: IntegrationConfig | None = None,
    write_outputs: bool = True,
) -> IntegrationRunResult:
    """Run an integration preset and optionally write its reproducibility artifacts.

    The physical experiment always completes as an in-memory operation first.
    ``write_outputs=True`` is retained as a compatibility convenience and
    delegates to :mod:`shwfs_ao.io.artifacts`; new callers should invoke
    :func:`shwfs_ao.io.artifacts.write_integration_artifacts` explicitly.
    """

    chosen = IntegrationConfig.from_mode("fast") if config is None else config
    start = time.perf_counter()
    system = build_integration_system(chosen)
    bandpasses = _build_jhk_bandpasses()
    scenarios = _scenario_matrix_for_config(chosen)
    scenario_results = run_error_budget_scenarios(
        system.calibration,
        system.dm_model,
        system.poke_result,
        scenarios=scenarios,
        bandpasses=bandpasses,
        telescope_diameter_m=chosen.telescope_diameter_m,
        pad_factor=chosen.pad_factor,
    )
    validation_results = build_validation_results(chosen, system)
    _assert_validation_passes(validation_results)
    _assert_scenario_results_are_finite(scenario_results)

    runtime_s = float(time.perf_counter() - start)
    config_hash = _config_hash(chosen)
    reference_metrics = build_reference_metrics(
        chosen,
        system.poke_result,
        scenario_results,
        validation_results,
        runtime_s=runtime_s,
        config_hash=config_hash,
    )
    _assert_reference_metrics(reference_metrics)
    result = IntegrationRunResult(
        mode=chosen.mode,
        scenario_results=scenario_results,
        validation_results=validation_results,
        reference_metrics=reference_metrics,
        written_files=(),
        runtime_s=runtime_s,
        source_class=chosen.source_class,
        config_hash=config_hash,
    )
    if not write_outputs:
        return result

    # Lazy import keeps the experiment engine independent of path resolution,
    # plotting libraries, and serialization details.  It also makes the
    # no-output execution path unable to invoke a writer accidentally.
    from ..io.artifacts import ArtifactConfig, write_integration_artifacts

    written_files = write_integration_artifacts(
        result,
        ArtifactConfig(
            output_dir=chosen.output_dir,
            reference_metrics_path=chosen.reference_metrics_path,
            prefix=chosen.mode,
            schema_version=2,
        ),
    )
    return replace(result, written_files=tuple(written_files))


def build_integration_system(config: IntegrationConfig) -> _IntegrationSystem:
    """Build the detector calibration, synthetic DM, and detector-level poke matrix."""

    geometry = ShwfsGeometryConfig(
        telescope_diameter_m=config.telescope_diameter_m,
        n_pupil_pixels=int(config.n_pupil_pixels),
        n_lenslets=int(config.n_lenslets),
        min_fill_fraction=0.35,
        pad_factor=int(config.pad_factor),
        detector_window_px=int(config.detector_window_px),
        threshold_fraction=0.0,
        source_class=config.source_class,
        source_note="Fast integration 2 m detector-level SH-WFS geometry.",
    )
    calibration = build_detector_shwfs_calibration(
        geometry=geometry,
        detector=DetectorConfig(
            photons_per_subap_frame=float(config.photons_per_subap_frame),
            read_noise_e=float(config.read_noise_e),
            qe=float(config.qe),
            source_class=config.source_class,
            source_note="Fast integration detector noise configuration.",
        ),
    )
    dm_model = build_dm_model(
        calibration.x_m,
        calibration.y_m,
        calibration.pupil_mask,
        DMConfig(
            telescope_diameter_m=config.telescope_diameter_m,
            n_actuators_across=int(config.n_actuators_across),
            influence_model="gaussian",
            coupling_width_pitch=float(config.coupling_width_pitch),
            stroke_limit_nm=float(config.stroke_limit_nm),
            source_class="synthetic_literature_inspired",
            source_note="Fast integration synthetic Gaussian DM model.",
        ),
    )
    poke_result = build_detector_dm_poke_matrix(
        calibration,
        dm_model,
        PokeMatrixConfig(
            calibration_amplitude_nm=float(config.calibration_amplitude_nm),
            rcond_scan_grid=(1.0e-8, 1.0e-6, 1.0e-4, 1.0e-3),
            target_kept_mode_fraction=float(config.target_kept_mode_fraction),
            source_class=config.source_class,
            source_note="Fast integration detector-level central-difference poke matrix.",
        ),
    )
    return _IntegrationSystem(calibration=calibration, dm_model=dm_model, poke_result=poke_result)


def build_validation_results(
    config: IntegrationConfig,
    system: _IntegrationSystem,
) -> tuple[ValidationCheckResult | ValidationScanResult, ...]:
    """Build the validation row set reused by the notebook and tests."""

    calibration = system.calibration
    dm_model = system.dm_model
    poke = system.poke_result
    x = calibration.x_m
    y = calibration.y_m
    mask = calibration.pupil_mask
    small_opd_nm = np.where(mask, 45.0 * (x**2 - y**2), np.nan)
    target_opd_nm = np.where(
        mask,
        120.0 * (x**2 - y**2) + 70.0 * x * y + 35.0 * np.sin(3.0 * np.pi * x / 2.0) * np.cos(2.0 * np.pi * y / 2.0),
        np.nan,
    )
    photon_scan = check_centroid_noise_photon_monotonicity(
        _gaussian_spot(),
        photon_counts=(200.0, 1000.0, 5000.0, 20000.0),
        detector_template=DetectorConfig(
            read_noise_e=0.0,
            qe=1.0,
            source_class=config.source_class,
            source_note="Fast integration photon-monotonicity detector template.",
        ),
        n_trials=160,
        seed=3,
    )
    latency_scenario = ScenarioConfig(
        "validation_dynamic",
        ("multi_component_dynamic_phase",),
        n_steps=int(config.n_steps),
        phase_amplitude_nm=float(config.phase_amplitude_nm),
        frame_rate_hz=float(config.frame_rate_hz),
        source_class=config.source_class,
        source_note="Fast integration latency validation scenario.",
    )
    phase_sequence = build_control_space_phase_sequence(calibration, dm_model, poke, latency_scenario)
    latency_scan = check_latency_residual_monotonicity(
        phase_sequence,
        calibration,
        dm_model,
        poke,
        latency_frames=(0, 1, 2),
        base_loop_config=DetectorLoopConfig(
            n_steps=int(config.n_steps),
            gain=0.32,
            leak=0.02,
            include_detector_noise=False,
            source_class=config.source_class,
            source_note="Fast integration latency validation loop config.",
        ),
    )
    fitting_scan = check_dm_fitting_trend(
        target_opd_nm,
        x,
        y,
        mask,
        actuator_counts=(4, 6, 8),
        dm_config_template=DMConfig(
            telescope_diameter_m=float(config.telescope_diameter_m),
            influence_model="gaussian",
            coupling_width_pitch=0.45,
            stroke_limit_nm=float(config.stroke_limit_nm),
            source_class="synthetic_literature_inspired",
            source_note="Fast integration DM fitting trend template.",
        ),
    )
    repro_scenario = ScenarioConfig(
        "validation_reproducibility",
        ("multi_component_dynamic_phase", "detector_noise"),
        n_steps=max(10, int(config.n_steps) - 2),
        phase_amplitude_nm=max(180.0, float(config.phase_amplitude_nm) - 20.0),
        include_detector_noise=True,
        frame_rate_hz=float(config.frame_rate_hz),
        seed=31,
        source_class=config.source_class,
        source_note="Fast integration reproducibility scenario.",
    )
    bandpasses = _build_jhk_bandpasses()
    first = run_error_budget_scenario(calibration, dm_model, poke, repro_scenario, bandpasses, pad_factor=int(config.pad_factor))
    second = run_error_budget_scenario(calibration, dm_model, poke, repro_scenario, bandpasses, pad_factor=int(config.pad_factor))
    results: tuple[ValidationCheckResult | ValidationScanResult, ...] = (
        check_marechal_consistency(
            small_opd_nm,
            mask,
            wavelength_m=1.65e-6,
            telescope_diameter_m=float(config.telescope_diameter_m),
        ),
        check_diffraction_scale(
            mask,
            wavelength_m=1.65e-6,
            telescope_diameter_m=float(config.telescope_diameter_m),
        ),
        photon_scan,
        latency_scan,
        fitting_scan,
        check_scenario_reproducibility((first,), (second,)),
    )
    return _retag_validation_results(results, config)


def build_reference_metrics(
    config: IntegrationConfig,
    poke_result: PokeMtxResult,
    scenario_results: Sequence[ScenarioResult],
    validation_results: Sequence[ValidationCheckResult | ValidationScanResult],
    runtime_s: float,
    config_hash: str,
) -> dict[str, Any]:
    """Build the small JSON reference metrics payload."""

    by_name = {row.scenario_name: row for row in scenario_results}
    if "all_effects" not in by_name:
        raise AOIntegrationError("Reference metrics require an all_effects scenario row.")
    row = by_name["all_effects"]
    validation_pass_count = sum(1 for result in validation_results if result.passed)
    return {
        "schema_version": 2,
        "workflow": "fast_integration",
        "preset": config.mode,
        "source_class": config.source_class,
        "source_note": config.source_note,
        "config_hash": config_hash,
        "scenario_count": len(tuple(scenario_results)),
        "scenario_names": list(REQUIRED_SCENARIO_NAMES),
        "reference_scenario": "all_effects",
        "open_rms_nm": _rounded(row.open_rms_nm),
        "closed_rms_nm": _rounded(row.closed_rms_nm),
        "h_strehl": _rounded(row.strehl_H),
        "valid_centroid_fraction": _rounded(row.valid_centroid_frac),
        "kept_modes": int(poke_result.kept_modes),
        "runtime_band": _runtime_band(runtime_s),
        "runtime_note": (
            "Reference runtime band observed on a local machine; CI enforces functional "
            "completion of the fast integration, not a strict timing benchmark. "
            "tolerances.runtime_s_reference_max is a documented reference, not an enforced limit."
        ),
        "validation_pass_count": int(validation_pass_count),
        "validation_check_count": int(len(tuple(validation_results))),
        "tolerances": dict(REFERENCE_TOLERANCES),
    }


def build_jhk_bandpasses():
    """Return J/H/K bandpasses, preferring tracked direct SVO caches."""

    return _build_jhk_bandpasses()


def load_reference_metrics(path: str | Path = DEFAULT_REFERENCE_METRICS_PATH) -> dict[str, Any]:
    """Load a saved reference-metrics JSON file."""

    with open_text_resource(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    _assert_reference_metrics(payload)
    return payload


def _scenario_matrix_for_config(config: IntegrationConfig) -> tuple[ScenarioConfig, ...]:
    scenarios = default_error_budget_scenarios(
        n_steps=int(config.n_steps),
        phase_amplitude_nm=float(config.phase_amplitude_nm),
    )
    return tuple(
        replace(
            scenario,
            frame_rate_hz=float(config.frame_rate_hz),
            source_class=config.source_class,
            source_note="Fast integration 8-scenario error-budget row.",
        )
        for scenario in scenarios
    )


def _build_jhk_bandpasses():
    specs = (
        ("J", "public/svo_2mass_j_direct.csv", (1.10e-6, 1.40e-6)),
        ("H", "public/svo_2mass_h_direct.csv", (1.50e-6, 1.80e-6)),
        ("K", "public/svo_2mass_ks_direct.csv", (2.00e-6, 2.35e-6)),
    )
    bandpasses = []
    for name, public_path, fallback_range in specs:
        fallback_path = "samples/svo_2mass_h_sample.csv" if name == "H" else None
        path = _first_available_resource(public_path, fallback_path)
        if path is not None:
            bandpasses.append(bandpass_from_filter_curve(load_svo_filter_curve(path), name=name))
        else:
            bandpasses.append(
                top_hat_bandpass(
                    name,
                    *fallback_range,
                    source_note=f"Synthetic {name}-band top-hat fallback; no direct SVO cache was found.",
                )
            )
    return tuple(bandpasses)


def _first_available_resource(*paths: str | Path | None) -> str | Path | None:
    for path in paths:
        if path is not None and resource_exists(path):
            return path
    return None


def _retag_validation_results(
    results: Sequence[ValidationCheckResult | ValidationScanResult],
    config: IntegrationConfig,
) -> tuple[ValidationCheckResult | ValidationScanResult, ...]:
    note = "Fast integration validation check for the 2 m detector-level SCAO demonstrator."
    return tuple(replace(result, source_class=config.source_class, source_note=note) for result in results)


def _assert_scenario_results_are_finite(results: Sequence[ScenarioResult]) -> None:
    if tuple(row.scenario_name for row in results) != REQUIRED_SCENARIO_NAMES:
        raise AOIntegrationError("Scenario result names do not match the required scenario matrix.")
    for row in results:
        values = (
            row.open_rms_nm,
            row.closed_rms_nm,
            row.strehl_J,
            row.strehl_H,
            row.strehl_K,
            row.ee50_J,
            row.ee50_H,
            row.ee50_K,
            row.command_rms_nm,
            row.command_peak_nm,
            row.valid_centroid_frac,
        )
        if not np.all(np.isfinite(values)):
            raise AOIntegrationError(f"Non-finite scenario metrics for {row.scenario_name}.")


def _assert_validation_passes(results: Sequence[ValidationCheckResult | ValidationScanResult]) -> None:
    failed = [result.check_name for result in results if not result.passed]
    if failed:
        raise AOIntegrationError(f"Validation checks failed: {failed}.")


def _assert_reference_metrics(payload: dict[str, Any]) -> None:
    missing = [field for field in REQUIRED_REFERENCE_FIELDS if field not in payload]
    if missing:
        raise AOIntegrationError(f"Reference metrics missing required fields: {missing}.")
    for field in ("open_rms_nm", "closed_rms_nm", "h_strehl", "valid_centroid_fraction"):
        _require_finite(field, payload[field])
    if int(payload["kept_modes"]) < 1:
        raise AOIntegrationError("kept_modes must be >= 1.")
    if not str(payload["runtime_band"]).strip():
        raise AOIntegrationError("runtime_band must be non-empty.")
    tolerances = payload.get("tolerances")
    if not isinstance(tolerances, dict):
        raise AOIntegrationError("Reference metrics must include a tolerances dictionary.")
    for key in REFERENCE_TOLERANCES:
        if key not in tolerances:
            raise AOIntegrationError(f"Reference metrics tolerances missing {key!r}.")


def _gaussian_spot(size: int = 17, sigma_px: float = 2.0) -> np.ndarray:
    coords = np.arange(size) - (size - 1) / 2.0
    x, y = np.meshgrid(coords, coords)
    spot = np.exp(-(x**2 + y**2) / (2.0 * sigma_px**2))
    return spot / np.sum(spot)


def _runtime_band(runtime_s: float) -> str:
    _require_nonnegative("runtime_s", runtime_s)
    if runtime_s <= 30.0:
        return "fast_under_30s"
    if runtime_s <= 60.0:
        return "fast_under_60s"
    return "fast_over_60s"


def _config_hash(config: IntegrationConfig) -> str:
    payload = asdict(config)
    # Output locations do not change the simulated response and would make a
    # temporary-output regression run hash differently from the same model in
    # the repository. Keep the hash restricted to response/provenance config.
    payload.pop("output_dir", None)
    payload.pop("reference_metrics_path", None)
    payload["hash_schema"] = 2
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _rounded(value: float, digits: int = 6) -> float:
    _require_finite("reference metric", value)
    return float(round(float(value), digits))


def _integration_provenance(source_class: str, source_note: str) -> _Provenance:
    """Build canonical provenance while retaining integration-specific errors."""

    try:
        return _Provenance(source_class=source_class, source_note=str(source_note))
    except (TypeError, ValueError) as exc:
        if source_class not in ALLOWED_SOURCE_CLASSES:
            raise AOIntegrationError(
                f"source_class={source_class!r} is not in the permitted taxonomy {sorted(ALLOWED_SOURCE_CLASSES)}."
            ) from exc
        raise AOIntegrationError("source_note must be non-empty.") from exc


def _require_positive(field_name: str, value: float) -> None:
    _require_finite(field_name, value)
    if float(value) <= 0.0:
        raise AOIntegrationError(f"{field_name} must be positive; got {value!r}.")


def _require_nonnegative(field_name: str, value: float) -> None:
    _require_finite(field_name, value)
    if float(value) < 0.0:
        raise AOIntegrationError(f"{field_name} must be non-negative; got {value!r}.")


def _require_finite(field_name: str, value: float) -> None:
    if not math.isfinite(float(value)):
        raise AOIntegrationError(f"{field_name} must be finite; got {value!r}.")
