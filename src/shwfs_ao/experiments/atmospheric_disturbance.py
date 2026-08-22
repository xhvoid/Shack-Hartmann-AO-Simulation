"""Atmosphere-driven error-budget disturbance.

:mod:`shwfs_ao.experiments.error_budget` owns the frozen AO-REF-011 scenario
API, whose public surface is mirrored exactly by a legacy facade and therefore
cannot grow.  The physically-conditioned disturbance introduced here is new
capability rather than a change to that surface, so it lives in its own module
and the frozen namespace stays frozen.

The distinction the two disturbance sources encode is not cosmetic:

``control_space_proxy``
    The historical disturbance, synthesized by driving the deformable mirror
    and reading back its own surface.  It lies entirely inside the mirror's
    controllable span, so a budget built on it contains **no fitting error at
    all** — the DM reproduces it to machine precision.  There is no ``r0`` and
    no outer scale on that path; the amplitude is a free parameter.

``atmospheric_screen``
    A calibrated von Karman screen in frozen flow, amplitude set by ``r0`` and
    the outer scale, advanced sub-pixel between frames.  Fitting error,
    temporal error, and aliasing all appear on their own.

On the shipped 2 m / 5x5-actuator scale the packaged proxy ``all_effects`` row
reports J/H/K Strehl 0.915/0.950/0.971 and a closed/open RMS ratio of 0.77; the
packaged atmospheric row reports 0.320/0.533/0.673 and 0.92.  The large gap is
expected because fitting error alone leaves roughly 43 % of a von Karman screen
uncorrected there.
"""

from __future__ import annotations

from typing import Any

from .error_budget import (
    PHASE_SOURCE_ATMOSPHERIC_SCREEN,
    PHASE_SOURCE_CONTROL_SPACE,
    DEFAULT_SCENARIO_SOURCE_CLASS,
    ScenarioConfig,
    build_atmospheric_phase_sequence,
    build_control_space_phase_sequence,
    build_phase_sequence,
    default_error_budget_scenarios,
    physical_error_budget_scenarios,
)


__all__ = (
    "PHASE_SOURCE_CONTROL_SPACE",
    "PHASE_SOURCE_ATMOSPHERIC_SCREEN",
    "build_phase_sequence",
    "build_atmospheric_phase_sequence",
    "physical_error_budget_scenarios",
)

# Re-exported so a caller comparing the two sources needs one import, and
# referenced here so linters see the imports as used.
_SHARED: tuple[Any, ...] = (
    ScenarioConfig,
    build_control_space_phase_sequence,
    default_error_budget_scenarios,
    DEFAULT_SCENARIO_SOURCE_CLASS,
)
