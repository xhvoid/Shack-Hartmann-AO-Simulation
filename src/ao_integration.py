# Fast end-to-end integration builds notebook-11 artifacts, finite reference metrics, required figures, and regression JSON without internet.

"""End-to-end fast integration runner for the realistic 2 m SCAO demo.

This module assembles the existing simulation components without adding another
AO model. It is the command-line and notebook-11 entry point for the fast
detector-level 2 m SCAO demonstrator.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path
import csv
import hashlib
import json
import math
import time
from typing import Any, Sequence

import numpy as np

from ao_closed_loop import DetectorLoopConfig
from ao_diagnostics import bandpass_from_filter_curve, top_hat_bandpass
from ao_error_budget import (
    REQUIRED_SCENARIO_NAMES,
    ScenarioConfig,
    ScenarioResult,
    build_control_space_phase_sequence,
    default_error_budget_scenarios,
    run_error_budget_scenario,
    run_error_budget_scenarios,
    scenario_results_as_dicts,
)
from ao_validation import (
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
from data_sources import ALLOWED_SOURCE_CLASSES, load_svo_filter_curve
from dm_model import DMConfig, DMModel, build_dm_model
from interaction_matrix import PokeMatrixConfig, PokeMtxResult, build_detector_dm_poke_matrix
from synthetic_instrument_data import DetectorConfig, DetectorShwfsCalibration, ShwfsGeometryConfig, build_detector_shwfs_calibration


REPO_ROOT = Path(__file__).resolve().parents[1]
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
        if self.source_class not in ALLOWED_SOURCE_CLASSES:
            raise AOIntegrationError(
                f"source_class={self.source_class!r} is not in the permitted taxonomy {sorted(ALLOWED_SOURCE_CLASSES)}."
            )
        if not str(self.source_note).strip():
            raise AOIntegrationError("source_note must be non-empty.")
        object.__setattr__(self, "output_dir", Path(self.output_dir))
        object.__setattr__(self, "reference_metrics_path", Path(self.reference_metrics_path))


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
    """Run an integration preset and optionally write its reproducibility artifacts."""

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

    written_files: tuple[Path, ...] = ()
    if write_outputs:
        written_files = _write_table_and_figure_artifacts(chosen, scenario_results, validation_results)

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
    if write_outputs:
        reference_path = _resolve_repo_path(chosen.reference_metrics_path)
        reference_path.parent.mkdir(parents=True, exist_ok=True)
        reference_path.write_text(json.dumps(reference_metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written_files = written_files + (reference_path,)
        _assert_required_artifacts(written_files, mode=chosen.mode, reference_metrics_path=_resolve_repo_path(chosen.reference_metrics_path))

    return IntegrationRunResult(
        mode=chosen.mode,
        scenario_results=scenario_results,
        validation_results=validation_results,
        reference_metrics=reference_metrics,
        written_files=written_files,
        runtime_s=runtime_s,
        source_class=chosen.source_class,
        config_hash=config_hash,
    )


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

    resolved = _resolve_repo_path(Path(path))
    with resolved.open("r", encoding="utf-8") as handle:
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
        ("J", REPO_ROOT / "data" / "public" / "svo_2mass_j_direct.csv", (1.10e-6, 1.40e-6)),
        ("H", REPO_ROOT / "data" / "public" / "svo_2mass_h_direct.csv", (1.50e-6, 1.80e-6)),
        ("K", REPO_ROOT / "data" / "public" / "svo_2mass_ks_direct.csv", (2.00e-6, 2.35e-6)),
    )
    bandpasses = []
    for name, public_path, fallback_range in specs:
        fallback_path = REPO_ROOT / "data" / "samples" / "svo_2mass_h_sample.csv" if name == "H" else None
        path = _first_existing_path(public_path, fallback_path) if fallback_path is not None else _first_existing_path(public_path)
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


def _first_existing_path(*paths: Path) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _write_table_and_figure_artifacts(
    config: IntegrationConfig,
    scenario_results: Sequence[ScenarioResult],
    validation_results: Sequence[ValidationCheckResult | ValidationScanResult],
) -> tuple[Path, ...]:
    output_dir = _resolve_repo_path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = config.mode
    scenario_rows = list(scenario_results_as_dicts(scenario_results))
    validation_rows = list(validation_results_as_dicts(validation_results))
    scenario_csv = output_dir / f"{prefix}_error_budget.csv"
    validation_csv = output_dir / f"{prefix}_validation.csv"
    scenario_png = output_dir / f"{config.mode}_error_budget.png"
    validation_png = output_dir / f"{config.mode}_validation.png"
    _write_csv(scenario_csv, scenario_rows)
    _write_csv(validation_csv, validation_rows)
    _plot_scenario_summary(scenario_png, scenario_rows)
    _plot_validation_summary(validation_png, validation_results)
    return (scenario_csv, scenario_png, validation_csv, validation_png)


def _retag_validation_results(
    results: Sequence[ValidationCheckResult | ValidationScanResult],
    config: IntegrationConfig,
) -> tuple[ValidationCheckResult | ValidationScanResult, ...]:
    note = "Fast integration validation check for the 2 m detector-level SCAO demonstrator."
    return tuple(replace(result, source_class=config.source_class, source_note=note) for result in results)


def _plot_scenario_summary(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = [str(row["scenario_name"]) for row in rows]
    open_rms = np.asarray([float(row["open_rms_nm"]) for row in rows], dtype=float)
    closed_rms = np.asarray([float(row["closed_rms_nm"]) for row in rows], dtype=float)
    strehl_h = np.asarray([float(row["strehl_H"]) for row in rows], dtype=float)
    x = np.arange(len(names))
    fig, ax1 = plt.subplots(figsize=(9.0, 4.8), constrained_layout=True)
    ax1.bar(x - 0.18, open_rms, width=0.35, color="#8d99ae", label="open RMS")
    ax1.bar(x + 0.18, closed_rms, width=0.35, color="#2a9d8f", label="closed RMS")
    ax1.set_ylabel("OPD RMS [nm]")
    ax1.set_xticks(x)
    ax1.set_xticklabels(names, rotation=35, ha="right")
    ax1.grid(axis="y", alpha=0.25)
    ax2 = ax1.twinx()
    ax2.plot(x, strehl_h, color="#e76f51", marker="o", linewidth=1.8, label="closed H Strehl")
    ax2.set_ylim(0.0, 1.05)
    ax2.set_ylabel("H-band Strehl")
    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(handles1 + handles2, labels1 + labels2, loc="upper left")
    ax1.set_title("Fast 2 m detector-level SCAO scenarios")
    fig.savefig(path, dpi=140, pil_kwargs={"optimize": True})
    plt.close(fig)


def _plot_validation_summary(
    path: Path,
    results: Sequence[ValidationCheckResult | ValidationScanResult],
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    scans = [result for result in results if isinstance(result, ValidationScanResult)]
    if len(scans) < 3:
        raise AOIntegrationError("Validation summary figure requires photon, latency, and fitting scans.")
    fig, axes = plt.subplots(1, 3, figsize=(11.0, 3.6), constrained_layout=True)
    axes[0].loglog(scans[0].x_values, scans[0].metric_values, marker="o", color="#1982c4")
    axes[0].set_xlabel("photons/subap/frame")
    axes[0].set_ylabel("centroid RMS [px]")
    axes[0].set_title("Photon monotonicity")
    axes[0].grid(True, which="both", alpha=0.25)

    axes[1].plot(scans[1].x_values, scans[1].metric_values, marker="o", color="#e76f51")
    axes[1].set_xlabel("latency [frames]")
    axes[1].set_ylabel("median residual [nm]")
    axes[1].set_title("Latency penalty")
    axes[1].grid(True, alpha=0.25)

    axes[2].plot(scans[2].x_values, scans[2].metric_values, marker="o", color="#2a9d8f")
    axes[2].set_xlabel("actuators across")
    axes[2].set_ylabel("fit residual [nm]")
    axes[2].set_title("DM fitting trend")
    axes[2].grid(True, alpha=0.25)
    fig.savefig(path, dpi=140, pil_kwargs={"optimize": True})
    plt.close(fig)


def _write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    if not rows:
        raise AOIntegrationError(f"Cannot write empty CSV table: {path}.")
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _assert_required_artifacts(paths: Sequence[Path], mode: str, reference_metrics_path: Path) -> None:
    prefix = mode
    expected_names = {
        f"{prefix}_error_budget.csv",
        f"{mode}_error_budget.png",
        f"{prefix}_validation.csv",
        f"{mode}_validation.png",
        reference_metrics_path.name,
    }
    by_name = {path.name: path for path in paths}
    missing = expected_names.difference(by_name)
    if missing:
        raise AOIntegrationError(f"Missing required artifacts: {sorted(missing)}.")
    for name in expected_names:
        path = by_name[name]
        if not path.exists() or path.stat().st_size <= 0:
            raise AOIntegrationError(f"Required artifact is absent or empty: {path}.")


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
    payload["output_dir"] = str(payload["output_dir"])
    payload["reference_metrics_path"] = str(payload["reference_metrics_path"])
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def _rounded(value: float, digits: int = 6) -> float:
    _require_finite("reference metric", value)
    return float(round(float(value), digits))


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
