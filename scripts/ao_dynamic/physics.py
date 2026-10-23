"""Effective configuration, complete-horizon admission and calibration rules.

``effective_config`` maps validated contract parameters onto the canonical
profile ``det_emccd_2m_synthetic@1``: the same ``dataclasses.replace`` steps
the frozen explorer uses (``scripts/ao_explorer/producer.py``), plus the wind
vector.  With the default parameters and seed 1 the result is the frozen
explorer's baseline configuration, hash for hash.

``admit`` is the frozen explorer's complete-horizon admission
(``scripts/ao_explorer/admission.py``) applied to that configuration and to
the exposure override the run will actually use: every atmosphere request
time -- frame starts, and the left-point or midpoint exposure sub-samples a
non-default exposure would add -- is checked against the frozen-flow screen's
own refusal rule with the factory's actual screen size and pupil spacing, no
slack.  The rule is mandatory: it does not depend on the optional memory
guard.  Nothing here builds a phase screen.

Calibration
    The profile calibrates on every build (``calibration.source = build``,
    central differences of DM actuator probes, noise-free).  Its identity
    depends on the WFS, i.e. on the seed (random stream identities) and on
    the guide magnitude (photon budget, validity); gain, queued delay, r0 and
    wind leave it unchanged (verified by ``calibration_identity`` records in
    each run).  Each run therefore rebuilds and records its calibration.
"""

from __future__ import annotations

from dataclasses import replace
import math
from typing import Any, Dict, Mapping, Optional

import contract


def base_config() -> Any:
    from shwfs_ao.io.configs import load_system_profile

    return load_system_profile(contract.PROFILE_NAME, contract.PROFILE_VERSION)


def effective_config(parameters: Mapping[str, Any]) -> Any:
    """The SystemConfig of one validated parameter set (no component is built)."""

    from shwfs_ao.experiments.detector_level import with_magnitude

    params = contract.effective_parameters(parameters)
    base = base_config()
    config = replace(
        base,
        controller=replace(
            base.controller,
            n_steps=int(params["n_frames"]),
            gain=float(params["controller_gain"]),
            latency_frames=int(params["queued_latency_frames"]),
        ),
        random=replace(base.random, root_seed=int(params["seed"])),
        atmosphere=replace(
            base.atmosphere,
            r0_m=float(params["r0_m"]),
            r0_reference_wavelength_m=float(params["r0_reference_wavelength_m"]),
            wind_m_per_s=(float(params["wind_m_per_s"][0]), float(params["wind_m_per_s"][1])),
        ),
    )
    if float(params["guide_ab_magnitude"]) != float(base.detector_physics.source.ab_magnitude):
        config = with_magnitude(config, float(params["guide_ab_magnitude"]))
    check_fixed_scope(config)
    return config


def check_fixed_scope(config: Any) -> None:
    """Refuse a configuration that left the fixed API v1 scope."""

    fixed = contract.FIXED
    problems = []
    if config.backend != fixed["backend"] or config.atmosphere_model != fixed["atmosphere_model"]:
        problems.append("backend or atmosphere model differs from the fixed scope")
    if (config.telescope_diameter_m, config.pupil_pixels, config.lenslets_across, config.actuators_across) != (
        fixed["telescope_diameter_m"], fixed["pupil_pixels"], fixed["lenslets_across"], fixed["actuators_across"]
    ):
        problems.append("aperture or WFS/DM sampling differs from the fixed scope")
    if config.wfs_wavelength_m != fixed["wfs_wavelength_m"] or contract.SCIENCE_WAVELENGTH_M not in config.science_wavelengths_m:
        problems.append("wavelengths differ from the fixed scope")
    if config.controller.frame_rate_hz != fixed["frame_rate_hz"] or config.controller.leak != fixed["controller_leak"]:
        problems.append("frame rate or leak differs from the fixed scope")
    if config.atmosphere.outer_scale_m != fixed["outer_scale_m"] or config.atmosphere.layers:
        problems.append("atmosphere outer scale or layers differ from the fixed scope")
    if int(config.detector_physics.exposure_subsamples) != 1:
        problems.append("WFS exposure differs from the fixed legacy single sample")
    if problems:
        raise ValueError("; ".join(problems))


def admit(config: Any, *, exposure_override: Any = None) -> Dict[str, Any]:
    """Complete-horizon admission of every atmosphere request of one run."""

    import admission

    return admission.admit(config, exposure_override=exposure_override)


def horizon_constants(config: Any) -> Dict[str, Any]:
    """Screen support of the fixed geometry, for hints (the admission decides)."""

    import admission
    from shwfs_ao.backends.native.factory import NATIVE_SCAO_COMPONENT_FACTORY

    geometry = NATIVE_SCAO_COMPONENT_FACTORY.build_geometry(
        telescope_diameter_m=config.telescope_diameter_m,
        pupil_pixels=config.pupil_pixels,
        lenslets_across=config.lenslets_across,
        min_fill_fraction=config.wfs.min_fill_fraction,
        central_obstruction_ratio=config.wfs.central_obstruction_ratio,
        spider_width_m=config.wfs.spider_width_m,
    )
    model = admission.model_atmosphere_config(config, geometry)
    delta = float(model.delta_m)
    budget = float(model.travel_budget_px)
    return {
        "delta_m": delta,
        "travel_budget_px": budget,
        "generated_screen_px": int(model.generated_grid_size),
        "pupil_array_px": int(model.grid_size),
        "frame_rate_hz": float(config.controller.frame_rate_hz),
        "rule": "refuse when hypot(vx t, vy t) / delta_m > travel_budget_px for any request time t "
                "(frame starts k / frame_rate_hz for the fixed single-sample exposure)",
        "hint_max_frames_formula": "floor(travel_budget_px * delta_m * frame_rate_hz / speed) + 1 (hint only)",
    }


def max_frames_hint(speed_m_per_s: float, constants: Mapping[str, Any]) -> Optional[int]:
    if speed_m_per_s <= 0.0:
        return None
    return int(math.floor(constants["travel_budget_px"] * constants["delta_m"] * constants["frame_rate_hz"] / speed_m_per_s)) + 1


def calibration_identity(system: Any) -> Dict[str, Any]:
    config = system.source_config
    hashes = dict(system.component_hashes)
    return {
        "source": config.calibration.source,
        "method": config.calibration.method,
        "probe_kind": config.calibration.probe_kind,
        "amplitude_m": config.calibration.amplitude_m,
        "include_noise": bool(config.calibration.include_noise),
        "rebuilt_for_this_run": config.calibration.source == "build",
        "interaction_matrix_hash": system.interaction_matrix.matrix_hash,
        "wfs_component_hash": hashes.get("wfs"),
        "reconstructor_component_hash": hashes.get("reconstructor"),
        "depends_on_parameters": list(contract.CALIBRATION_PARAMETERS),
        "independent_of_parameters": ["controller_gain", "queued_latency_frames", "r0_m", "wind_speed_m_per_s", "wind_direction_deg"],
        "rule": "the noise-free calibration depends on the WFS (seed-bound stream identities, guide photon budget); "
                "a change of seed or guide magnitude requires and records a rebuilt calibration",
    }


def atmosphere_identity(system: Any, history_metadata: Mapping[str, Any]) -> Dict[str, Any]:
    from dataclasses import asdict

    atmosphere = system.atmosphere
    model = asdict(atmosphere.config)
    return {
        "component_hash": dict(system.component_hashes).get("atmosphere"),
        "config_hash": atmosphere.config_hash,
        "model_config": model,
        "model_config_sha256": contract.sha256_bytes(contract.canonical_json_bytes(model)),
        "root_seed": int(atmosphere.root_seed),
        "realization_index": int(atmosphere.realization_index),
        "realization_stream_id": history_metadata.get("atmosphere_realization_stream_id"),
        "evolution": "one seeded realization generated at t = 0 and translated by frozen flow (exact Fourier sub-pixel "
                     "evaluation of the same spectral draws); never redrawn, wrapped, reset or blended during the run",
    }
