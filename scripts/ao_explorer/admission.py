"""Complete-horizon atmosphere admission for one explorer trajectory.

Before any phase screen is generated, this module derives, from the actual
source tree, every time at which the canonical runner will ask the
atmosphere for a sample, and checks each one against the atmosphere model's
own support rule.

Request schedule (``shwfs_ao.control.loop.run_closed_loop``)
    Frame ``k`` always requests ``k / f`` (``np.arange(n) / f``).  With the
    effective exposure keywords of
    ``shwfs_ao.experiments._component_configs.exposure_keywords``:

    * none (legacy left point, ``n = 1``): no further request;
    * left point, ``n > 1``: ``t + j * tau / n`` for ``j = 1 .. n - 1``;
    * midpoint, any ``n`` (``n = 1`` included): ``t + (j + 1/2) * tau / n``
      for ``j = 0 .. n - 1``.

    No other component of the runner path (``build_scao_system``,
    ``run_closed_loop``, the explorer observer) calls ``opd_at``; the
    observer receives read-only snapshots and cannot reach the atmosphere.

Support rule (``native_frozen_flow_v2``)
    ``FrozenFlowAtmosphere.opd_at`` computes ``shift = v * t / delta`` per axis
    and refuses ``hypot(shift_x, shift_y) > travel_budget_px``, where the budget
    is ``(generated_screen - pupil_array) / 2``.  This module applies exactly
    that rule, with the factory's actual screen construction and the pupil's
    actual coordinate spacing, and no extra tolerance.  Any other atmosphere
    model is refused as unsupported by this admission rule.

The helper never builds a phase screen: it builds the pupil geometry and a
``FrozenFlowAtmosphereConfig`` (validation only).
"""

from __future__ import annotations

from dataclasses import asdict
import math
from typing import Any, Dict, List, Optional

import numpy as np

import identity
import protocol


ADMITTED = "ADMITTED"
REFUSED_OVER_HORIZON = "REFUSED_OVER_HORIZON"
REFUSED_UNSUPPORTED = "REFUSED_UNSUPPORTED_MODEL"
REFUSED_INVALID_SCHEDULE = "REFUSED_INVALID_SCHEDULE"

# Source files whose content the schedule and the support rule were read from.
BOUND_SOURCES = (
    "src/shwfs_ao/control/loop.py",
    "src/shwfs_ao/experiments/_component_configs.py",
    "src/shwfs_ao/experiments/scao.py",
    "src/shwfs_ao/backends/native/factory.py",
    "src/shwfs_ao/backends/native/atmosphere.py",
)


def request_schedule(
    n_steps: int,
    frame_rate_hz: float,
    keywords: Dict[str, Any],
) -> Dict[str, Any]:
    """Every atmosphere request time of one run, in request order."""

    frame_times = np.arange(int(n_steps), dtype=float) / float(frame_rate_hz)
    subsamples = int(keywords.get("exposure_subsamples", 1))
    rule = str(keywords.get("exposure_sample_rule", "left_point"))
    if not keywords:
        label = "single_sample_at_frame_time (legacy left point, n=1)"
        offsets_note = "none"
    elif rule == "midpoint":
        label = f"frame start plus midpoint exposure samples, n={subsamples}"
        offsets_note = "(j + 1/2) * tau / n, j = 0..n-1"
    else:
        label = f"frame start plus left-point exposure samples, n={subsamples}"
        offsets_note = "j * tau / n, j = 1..n-1"
    exposure_s = keywords.get("exposure_s")
    times: List[float] = []
    for frame_time in frame_times:
        start = float(frame_time)
        times.append(start)
        if not keywords:
            continue
        tau = float(exposure_s)
        if rule == "midpoint":
            for index in range(subsamples):
                times.append(start + (index + 0.5) * tau / subsamples)
        else:
            for index in range(1, subsamples):
                times.append(start + index * tau / subsamples)
    return {
        "rule": label,
        "extra_offsets": offsets_note,
        "exposure_keywords": dict(keywords),
        "frame_count": int(n_steps),
        "frame_rate_hz": float(frame_rate_hz),
        "times_s": times,
    }


def _pupil_spacing(geometry: Any) -> Dict[str, Any]:
    x = np.asarray(geometry.x_m, dtype=float)
    y = np.asarray(geometry.y_m, dtype=float)
    dx = np.diff(x, axis=1)
    dy = np.diff(y, axis=0)
    spacing_x = float(dx[0, 0])
    spacing_y = float(dy[0, 0])
    uniform = bool(
        np.allclose(dx, spacing_x, rtol=1e-12, atol=0.0)
        and np.allclose(dy, spacing_y, rtol=1e-12, atol=0.0)
    )
    factory_spacing = tuple(float(value) for value in geometry.pupil_geometry.pixel_spacing_xy_m)
    return {
        "from_coordinates_xy_m": [spacing_x, spacing_y],
        "coordinates_uniform": uniform,
        "x_range_m": [float(x.min()), float(x.max())],
        "y_range_m": [float(y.min()), float(y.max())],
        "convention": "endpoint-inclusive sample coordinates",
        "factory_pixel_spacing_xy_m": list(factory_spacing),
        "factory_matches_coordinates": bool(
            math.isclose(factory_spacing[0], spacing_x, rel_tol=1e-12)
            and math.isclose(factory_spacing[1], spacing_y, rel_tol=1e-12)
        ),
    }


def model_atmosphere_config(config: Any, geometry: Any) -> Any:
    """The ``FrozenFlowAtmosphereConfig`` the native factory will build (no screen)."""

    from shwfs_ao.backends.native.atmosphere import (
        SPECTRUM_SUBHARMONIC_V2,
        TRANSLATION_FOURIER_SUBPIXEL_V2,
        FrozenFlowAtmosphereConfig,
    )
    from shwfs_ao.backends.native.factory import SCREEN_OVERSIZE_FACTOR
    from shwfs_ao.experiments._component_configs import target_rms_rad

    return FrozenFlowAtmosphereConfig(
        grid_size=geometry.pupil_shape[0],
        screen_grid_size=SCREEN_OVERSIZE_FACTOR * geometry.pupil_shape[0],
        delta_m=geometry.pupil_geometry.pixel_spacing_xy_m[0],
        pupil_diameter_m=geometry.telescope_diameter_m,
        r0_m=config.atmosphere.r0_m,
        outer_scale_m=config.atmosphere.outer_scale_m,
        phase_reference_wavelength_m=config.atmosphere.r0_reference_wavelength_m,
        wind_m_per_s=config.atmosphere.wind_m_per_s,
        root_seed=config.random.root_seed,
        target_rms_rad=target_rms_rad(config),
        normalize_rms=config.atmosphere.normalize_rms,
        spectrum_model=SPECTRUM_SUBHARMONIC_V2,
        translation_model=TRANSLATION_FOURIER_SUBPIXEL_V2,
    )


def evaluate_requests(
    times_s: List[float],
    *,
    wind_m_per_s: tuple,
    delta_m: float,
    budget_px: float,
) -> Dict[str, Any]:
    """Apply the model's refusal rule to every request (no slack)."""

    vx, vy = float(wind_m_per_s[0]), float(wind_m_per_s[1])
    previous = 0.0
    worst_px = 0.0
    worst_time = 0.0
    first_refused: Optional[Dict[str, float]] = None
    invalid: List[str] = []
    for index, time_s in enumerate(times_s):
        value = float(time_s)
        if not math.isfinite(value) or value < 0.0:
            invalid.append(f"request {index}: time {value!r} is not finite and non-negative")
            continue
        if value < previous:
            invalid.append(f"request {index}: time {value!r} precedes {previous!r}")
        previous = max(previous, value)
        travelled = math.hypot(vx * value / delta_m, vy * value / delta_m)
        if travelled > worst_px:
            worst_px, worst_time = travelled, value
        if travelled > budget_px and first_refused is None:
            first_refused = {"request_index": index, "time_s": value, "travel_px": travelled}
    return {
        "max_travel_px": worst_px,
        "time_of_max_travel_s": worst_time,
        "first_refused_request": first_refused,
        "invalid_requests": invalid,
    }


def admit(config: Any, *, exposure_override: Any = None) -> Dict[str, Any]:
    """Admission record of one trajectory's effective configuration."""

    from shwfs_ao.backends.native.factory import (
        NATIVE_SCAO_COMPONENT_FACTORY,
        SCREEN_OVERSIZE_FACTOR,
    )
    from shwfs_ao.experiments._component_configs import exposure_keywords

    keywords = exposure_keywords(config, exposure_override)
    schedule = request_schedule(
        config.controller.n_steps, config.controller.frame_rate_hz, keywords
    )
    times = schedule.pop("times_s")
    times_array = np.asarray(times, dtype=float)
    record: Dict[str, Any] = {
        "schema": protocol.ADMISSION_SCHEMA,
        "config_hash": config.config_hash,
        "atmosphere_model": config.atmosphere_model,
        "backend": config.backend,
        "schedule": schedule,
        "request_count": len(times),
        "request_times_sha256": identity.sha256_bytes(times_array.tobytes()),
        "first_request_s": float(times_array[0]) if len(times) else None,
        "last_request_s": float(times_array[-1]) if len(times) else None,
        "max_request_s": float(np.max(times_array)) if len(times) else None,
        "consumers": [
            "control.loop.run_closed_loop: atmosphere.opd_at(k / frame_rate_hz) for every frame",
            "control.loop.run_closed_loop: exposure samples per the rule above (none for legacy n=1)",
        ],
        "non_consumers": [
            "experiments.scao.build_scao_system (constructs the atmosphere; no opd_at call)",
            "scripts/ao_explorer/observer.py (receives read-only snapshots only)",
        ],
        "bound_sources_sha256": identity.source_file_digests(BOUND_SOURCES),
    }
    if config.backend != "native" or config.atmosphere_model != "native_frozen_flow_v2":
        record.update(
            outcome=REFUSED_UNSUPPORTED,
            admitted=False,
            reasons=[
                f"atmosphere model {config.atmosphere_model!r} on backend {config.backend!r} "
                "has no support rule in this admission helper"
            ],
        )
        return record
    geometry = NATIVE_SCAO_COMPONENT_FACTORY.build_geometry(
        telescope_diameter_m=config.telescope_diameter_m,
        pupil_pixels=config.pupil_pixels,
        lenslets_across=config.lenslets_across,
        min_fill_fraction=config.wfs.min_fill_fraction,
        central_obstruction_ratio=config.wfs.central_obstruction_ratio,
        spider_width_m=config.wfs.spider_width_m,
    )
    spacing = _pupil_spacing(geometry)
    model = model_atmosphere_config(config, geometry)
    budget = float(model.travel_budget_px)
    wind = tuple(float(value) for value in model.wind_m_per_s)
    evaluation = evaluate_requests(times, wind_m_per_s=wind, delta_m=model.delta_m, budget_px=budget)
    reasons: List[str] = []
    if not spacing["coordinates_uniform"] or not spacing["factory_matches_coordinates"]:
        reasons.append("pupil coordinates are not uniform or disagree with the factory spacing")
    if evaluation["invalid_requests"]:
        reasons.extend(evaluation["invalid_requests"])
    if evaluation["first_refused_request"] is not None:
        refused = evaluation["first_refused_request"]
        reasons.append(
            f"request {refused['request_index']} at t={refused['time_s']!r} s travels "
            f"{refused['travel_px']!r} px > budget {budget!r} px"
        )
    if reasons and evaluation["invalid_requests"]:
        outcome = REFUSED_INVALID_SCHEDULE
    elif reasons:
        outcome = REFUSED_OVER_HORIZON
    else:
        outcome = ADMITTED
    model_record = asdict(model)
    record.update(
        {
            "pupil_shape": list(geometry.pupil_shape),
            "pupil_spacing": spacing,
            "model_config": model_record,
            "model_config_sha256": identity.sha256_bytes(identity.canonical_json_bytes(model_record)),
            "screen_oversize_factor": SCREEN_OVERSIZE_FACTOR,
            "generated_screen_px": int(model.generated_grid_size),
            "travel_budget_px": budget,
            "travel_budget_rule": "(generated_screen_px - pupil_array_px) / 2; refuse hypot(vx t/delta, vy t/delta) > budget",
            "wind_m_per_s": list(wind),
            "wind_speed_m_per_s": math.hypot(*wind),
            "delta_m": float(model.delta_m),
            "max_travel_px": evaluation["max_travel_px"],
            "time_of_max_travel_s": evaluation["time_of_max_travel_s"],
            "margin_px": budget - evaluation["max_travel_px"],
            "first_refused_request": evaluation["first_refused_request"],
            "outcome": outcome,
            "admitted": outcome == ADMITTED,
            "reasons": reasons,
        }
    )
    return record
