"""Atmosphere-driven counterpart to the frozen fast integration.

:mod:`shwfs_ao.experiments.integration` re-exports the frozen AO-REF-011 fast
engine, whose numerics back the accepted ``fast_*`` regression baselines and
must stay byte-stable.  That engine's disturbance is the control-space proxy:
a pattern synthesized by driving the deformable mirror and reading back its own
surface, which the mirror can therefore correct exactly.  A budget built on it
contains no fitting error and no ``r0``.

This module runs the same instrument, the same validation set, and the same
artifact contract against a calibrated von Karman screen with a physical
command latency, and it produces its own ``physical_*`` baselines.  Both
workflows ship: the proxy isolates temporal and noise terms *from* fitting
error, and this one reports what the instrument would actually deliver.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import time
from typing import Any, Sequence

from ..core.hashing import component_config_hash
from ..core.provenance import ALLOWED_SOURCE_CLASSES
from ..legacy.ao_integration import (
    AOIntegrationError,
    IntegrationConfig,
    IntegrationRunResult,
    build_integration_system,
    build_jhk_bandpasses,
    build_reference_metrics,
    build_validation_results,
)
from .error_budget import ScenarioResult, run_error_budget_scenarios
from .atmospheric_disturbance import physical_error_budget_scenarios


__all__ = (
    "PhysicalIntegrationConfig",
    "PHYSICAL_WORKFLOW",
    "PHYSICAL_PRESET",
    "run_physical_integration",
)

PHYSICAL_WORKFLOW = "physical_integration"
"""``workflow`` label distinguishing these artifacts from the proxy ones."""

PHYSICAL_PRESET = "physical_2m"
"""``preset`` label for the atmosphere-driven 2 m run."""

DEFAULT_SOURCE_CLASS = "synthetic_assumed"
DEFAULT_SOURCE_NOTE = (
    "Atmosphere-driven 2 m integration: calibrated von Karman screen with "
    "r0-set amplitude and a physical command latency; synthetic engineering "
    "configuration, not measured observatory telemetry."
)


@dataclass(frozen=True)
class PhysicalIntegrationConfig:
    """Observing conditions and loop timing for the atmosphere-driven run.

    The instrument scale (pupil pixels, lenslets, actuators, detector window)
    is deliberately inherited from ``IntegrationConfig.from_mode("fast")`` so
    that this workflow and the proxy workflow describe the *same telescope*
    and differ only in the disturbance and the loop latency.

    Args:
        n_steps: Loop frames.  The default of 24 is the length the packaged
            ``physical_*`` baseline is generated at, chosen for cost: the
            existing science-metric path evaluates PSF metrics once per frame,
            per band, per wavelength sample — 5784 evaluations and 23136 array
            sorts per scenario at this length — so a run costs about 75 s per
            scenario regardless of which disturbance drives it.  At 1 kHz with
            r0 = 0.126 m and 10 m/s wind the coherence time is about 6 ms, so
            24 frames covers four coherence times and ``summarize_scenario``
            averages the last twelve.  Raise it to 60 or more for a temporal
            study; the oversized screen supports roughly 200 frames at this
            wind before the travel budget is exhausted.
        r0_m: Fried parameter at ``r0_reference_wavelength_m``.
        outer_scale_m: von Karman outer scale.
        frame_rate_hz: Loop frame rate.
        latency_frames: Command latency.  Two frames is the smallest value a
            real system achieves; zero would describe a loop applying this
            frame's measurement to this frame's mirror.
        turbulence_speed_m_s: Frozen-flow wind speed.
    """

    n_steps: int = 24
    r0_m: float = 0.1263371938263465
    outer_scale_m: float = 25.0
    r0_reference_wavelength_m: float = 500.0e-9
    frame_rate_hz: float = 1000.0
    latency_frames: int = 2
    turbulence_speed_m_s: float = 10.0
    source_class: str = DEFAULT_SOURCE_CLASS
    source_note: str = DEFAULT_SOURCE_NOTE

    def __post_init__(self) -> None:
        if int(self.n_steps) < 2:
            raise AOIntegrationError("n_steps must be >= 2.")
        for name in ("r0_m", "outer_scale_m", "r0_reference_wavelength_m",
                     "frame_rate_hz", "turbulence_speed_m_s"):
            value = float(getattr(self, name))
            if not value > 0.0:
                raise AOIntegrationError(f"{name} must be positive.")
        if int(self.latency_frames) < 0:
            raise AOIntegrationError("latency_frames must be >= 0.")
        if self.source_class not in ALLOWED_SOURCE_CLASSES:
            raise AOIntegrationError(
                f"source_class={self.source_class!r} is not in the permitted "
                f"taxonomy {sorted(ALLOWED_SOURCE_CLASSES)}."
            )
        if not str(self.source_note).strip():
            raise AOIntegrationError("source_note must be a non-empty string.")

    @property
    def config_hash(self) -> str:
        """Stable identity of the physical observing/timing configuration."""

        return component_config_hash(
            "shwfs_ao.physical_integration",
            {
                "n_steps": int(self.n_steps),
                "r0_m": float(self.r0_m),
                "outer_scale_m": float(self.outer_scale_m),
                "r0_reference_wavelength_m": float(self.r0_reference_wavelength_m),
                "frame_rate_hz": float(self.frame_rate_hz),
                "latency_frames": int(self.latency_frames),
                "turbulence_speed_m_s": float(self.turbulence_speed_m_s),
                "workflow": PHYSICAL_WORKFLOW,
                "preset": PHYSICAL_PRESET,
            },
        )


def _instrument_config(config: PhysicalIntegrationConfig) -> IntegrationConfig:
    """Fast-mode instrument scale, retimed for the physical loop."""

    return IntegrationConfig.from_mode(
        "fast",
        n_steps=int(config.n_steps),
        frame_rate_hz=float(config.frame_rate_hz),
        source_class=config.source_class,
        source_note=config.source_note,
    )


def _assert_finite_rows(results: Sequence[ScenarioResult]) -> None:
    import math

    for row in results:
        for field in (
            row.open_rms_nm,
            row.closed_rms_nm,
            row.strehl_J,
            row.strehl_H,
            row.strehl_K,
            row.valid_centroid_frac,
        ):
            if not math.isfinite(float(field)):
                raise AOIntegrationError(
                    f"scenario {row.scenario_name!r} produced a non-finite metric."
                )


def run_physical_integration(
    config: PhysicalIntegrationConfig | None = None,
) -> IntegrationRunResult:
    """Run the 2 m integration against a real atmosphere.

    Returns an :class:`IntegrationRunResult` in the same shape the frozen fast
    workflow produces, so the identical artifact writer and validation contract
    apply.  ``reference_metrics`` carries :data:`PHYSICAL_WORKFLOW` and
    :data:`PHYSICAL_PRESET` so an artifact from this workflow can never be
    mistaken for a proxy one.

    The validation row set is deliberately unchanged: those checks probe the
    *instrument* — centroid photon monotonicity, DM fitting, latency
    monotonicity — and are independent of which disturbance drives the loop.
    """

    chosen = config or PhysicalIntegrationConfig()
    start = time.perf_counter()

    instrument = _instrument_config(chosen)
    system = build_integration_system(instrument)
    bandpasses = build_jhk_bandpasses()

    scenarios = tuple(
        replace(
            scenario,
            turbulence_speed_m_s=float(chosen.turbulence_speed_m_s),
            r0_reference_wavelength_m=float(chosen.r0_reference_wavelength_m),
            source_class=chosen.source_class,
            source_note="Physical integration 8-scenario error-budget row.",
        )
        for scenario in physical_error_budget_scenarios(
            n_steps=int(chosen.n_steps),
            r0_m=float(chosen.r0_m),
            outer_scale_m=float(chosen.outer_scale_m),
            frame_rate_hz=float(chosen.frame_rate_hz),
            latency_frames=int(chosen.latency_frames),
        )
    )
    scenario_results = run_error_budget_scenarios(
        system.calibration,
        system.dm_model,
        system.poke_result,
        scenarios=scenarios,
        bandpasses=bandpasses,
        telescope_diameter_m=instrument.telescope_diameter_m,
        pad_factor=instrument.pad_factor,
    )
    _assert_finite_rows(scenario_results)

    validation_results = build_validation_results(instrument, system)
    failed = [row.check_name for row in validation_results if not row.passed]
    if failed:
        raise AOIntegrationError(f"validation rows failed: {failed}")

    runtime_s = float(time.perf_counter() - start)
    reference_metrics: dict[str, Any] = dict(
        build_reference_metrics(
            instrument,
            system.poke_result,
            scenario_results,
            validation_results,
            runtime_s=runtime_s,
            config_hash=chosen.config_hash,
        )
    )
    reference_metrics["workflow"] = PHYSICAL_WORKFLOW
    reference_metrics["preset"] = PHYSICAL_PRESET
    reference_metrics["source_note"] = chosen.source_note

    return IntegrationRunResult(
        mode=instrument.mode,
        scenario_results=scenario_results,
        validation_results=validation_results,
        reference_metrics=reference_metrics,
        written_files=(),
        runtime_s=runtime_s,
        source_class=chosen.source_class,
        config_hash=chosen.config_hash,
    )
