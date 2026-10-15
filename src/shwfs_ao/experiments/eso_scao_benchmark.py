"""ESO-derived SCAO benchmark tiers: estimate, supervise, run, record.

This module is the executable side of ``docs/eso_scao_benchmark.md``.  It
never assembles or sequences components itself: every tier loads a packaged
schema-v5 profile, builds it with :func:`~.scao.build_scao_system`, and runs
it through :func:`~.scao.run_closed_loop` with a passive
:class:`~shwfs_ao.science.long_exposure.StreamingLongExposure` observer.

Tiers
-----
``ci``           ``eso_scao_smoke_5m_software@2``: software smoke, desktop safe.
``medium``       ``eso_scao_medium_12m_derived@2``: 200-frame scaling run.
``medium-gate``  ``eso_scao_medium_12m_weak_gate@2``: control gate, weak r0.
``full``         ``eso_drm_42m_scao_derived@2`` with a declared 20-frame
                 override: full spatial-scale capability.
``reference``    ``eso_drm_42m_scao_derived@2`` as packaged: 2000 frames.

The ``@1`` profiles stay loadable; they used an even 24-pixel detector window
whose centre-of-gravity bias left a static tilt, and ``@2`` replaces only that
window (see the version-2 assumption ledger).

Every tier but ``ci`` requires ``enable_large_run=True`` (``--enable-large-run``)
after a human has reviewed the dry-run estimate; :func:`estimate_tier` and
``--dry-run`` compute that estimate from the profile alone and never build
the system.  The command line runs the numerical work in a supervised child
process (``shwfs_ao.runtime.resource_guard``) with native-library thread
limits, an aggregate-RSS budget, a wall-clock limit and memory-pressure stop.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass, replace
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import sys
import time
from typing import Any, Final

from ..io.configs import SystemConfig, load_system_profile
from ..runtime.resource_guard import (
    DEFAULT_EXAMPLE_TIMEOUT_S,
    DEFAULT_THREAD_LIMIT,
    MIB,
    THREAD_ENV_VARS,
    ResourceEstimate,
    host_snapshot,
    preflight,
    run_supervised,
)


__all__ = (
    "TIERS",
    "LARGE_TIERS",
    "BenchmarkTier",
    "LargeRunNotEnabled",
    "tier_config",
    "estimate_tier",
    "dry_run_record",
    "run_tier",
    "main",
)


@dataclass(frozen=True)
class BenchmarkTier:
    name: str
    profile: tuple[str, int]
    n_steps_override: int | None
    burn_in_frames: int
    purpose: str


TIERS: Final = {
    "ci": BenchmarkTier(
        "ci", ("eso_scao_smoke_5m_software", 2), None, 8,
        "software smoke: numerical behaviour and regression (desktop safe)",
    ),
    "medium": BenchmarkTier(
        "medium", ("eso_scao_medium_12m_derived", 2), None, 50,
        "end-to-end scaling and calibration at 24x24/25x25 (explicit opt-in)",
    ),
    "medium-gate": BenchmarkTier(
        "medium-gate", ("eso_scao_medium_12m_weak_gate", 2), None, 30,
        "control gate on a predeclared weak atmosphere (explicit opt-in)",
    ),
    "full": BenchmarkTier(
        "full", ("eso_drm_42m_scao_derived", 2), 20, 5,
        "full spatial-scale capability: 84x84/85x85, 20 frames (explicit opt-in)",
    ),
    "reference": BenchmarkTier(
        "reference", ("eso_drm_42m_scao_derived", 2), None, 200,
        "2000-frame reference run at full spatial scale (explicit opt-in)",
    ),
}
LARGE_TIERS: Final = frozenset({"medium", "medium-gate", "full", "reference"})
_LAYERS: Final = 10
_RESULT_SCHEMA: Final = "shwfs_ao.eso_scao_benchmark_result.v1"
# Control-gate thresholds (engineering tests, not ESO specifications).
_GATE_USABLE_FRACTION: Final = 0.90
_GATE_RMS_REDUCTION: Final = 0.05
_CAPABILITY_MIN_UPDATES: Final = 10


class LargeRunNotEnabled(RuntimeError):
    """Raised when a medium/full tier is requested without explicit enablement."""


def tier_config(tier: str, *, n_steps: int | None = None) -> SystemConfig:
    """The tier's profile with its declared frame-count override; never builds."""

    spec = TIERS[tier]
    config = load_system_profile(*spec.profile)
    steps = n_steps if n_steps is not None else spec.n_steps_override
    if steps is not None and steps != config.controller.n_steps:
        config = replace(config, controller=replace(config.controller, n_steps=int(steps)))
    return config


def _estimated_counts(config: SystemConfig) -> dict[str, int]:
    across = config.lenslets_across
    epsilon = config.wfs.central_obstruction_ratio
    area = math.pi / 4.0 * (1.0 - epsilon * epsilon)
    lenslets = int(math.ceil(across * across * area + 4 * across))
    actuators_nominal = config.actuators_across**2
    margin = 1.0 + config.dm.actuator_margin_fraction
    actuators = int(math.ceil(math.pi / 4.0 * (config.actuators_across * margin) ** 2))
    return {
        "nominal_lenslets": across * across,
        "estimated_retained_lenslets_upper": lenslets,
        "nominal_actuators": actuators_nominal,
        "estimated_retained_actuators_upper": min(actuators, actuators_nominal),
    }


def estimate_tier(
    config: SystemConfig,
    *,
    wavelengths: Sequence[float] | None = None,
    lenslet_batch_size: int = 512,
    label: str | None = None,
    atmosphere_band_storage: str = "materialized",
) -> ResourceEstimate:
    """Analytic upper estimate of peak aggregate RSS; constructs nothing.

    The terms follow the audited allocation inventory in
    ``docs/refactor/ESO_SCAO_DEVELOPMENT_STATUS.md`` (ESO-00): interpreter and
    libraries, sampled pupil grids, the ten-layer atmosphere's per-layer
    Fourier coefficients and per-frame FFT temporaries, the sparse DM operator
    and its identity hashing, the compact geometry and label map, one WFS
    measurement (spots, per-lenslet detector frames, batch FFT scratch), the
    calibration's probe maps, science propagation and accumulation per
    wavelength, observer snapshots, and the command/telemetry history.
    """

    n = config.pupil_pixels
    screen = 2 * n
    counts = _estimated_counts(config)
    lenslets = counts["estimated_retained_lenslets_upper"]
    actuators = counts["estimated_retained_actuators_upper"]
    pitch_samples = (n - 1) / max(1, config.actuators_across - 1)
    support = int(math.ceil(2.0 * pitch_samples)) ** 2
    sampling = int(math.ceil(n / config.lenslets_across))
    canvas = (config.wfs.pad_factor or 1) * sampling
    window = min(canvas, config.wfs.detector_window_px or canvas)
    science_side = config.science.psf_pad_factor * n
    waves = tuple(config.science_wavelengths_m if wavelengths is None else wavelengths)
    batch = max(1, min(lenslet_batch_size, (64 * MIB) // max(1, canvas * canvas * 56)))
    steps = config.controller.n_steps
    components = {
        "pupil_grids_and_copies": 4 * n * n * (8 + 8 + 1),
        "atmosphere_layer_coefficients": (
            _LAYERS * screen * screen * 16
            if atmosphere_band_storage == "materialized"
            # regenerate: one layer's draws and coefficients live at a time
            else screen * screen * (8 + 8 + 16 + 16)
        ),
        "atmosphere_band_power": screen * screen * 8,
        "atmosphere_frame_temporaries": screen * screen * 16 * 3 + screen * n * 16 + 3 * n * n * 8,
        "dm_sparse_operator_and_hashing": actuators * support * (8 + 4) * 2 * 2,
        # Construction transients: per-actuator lists, concatenation, CSC/CSR
        # conversion and the int64/float64 canonical copies made for hashing
        # (measured ~5 % above the earlier estimate at full scale).
        "dm_construction_transients": actuators * support * (8 + 8) * 3,
        "compact_geometry_and_label_map": n * n * 4 + lenslets * (sampling + 1) ** 2 * 2,
        "wfs_measurement": lenslets * window * window * 8 * (2 + 10)
        + batch * canvas * canvas * 56
        + 4 * n * n * 8,
        "calibration_probe_maps": 3 * n * n * 8,
        "sparse_response": actuators * 16 * 8 * 3,
        "science_per_wavelength": len(waves) * science_side**2 * (16 * 4 + 8 * 5),
        "observer_snapshots": 2 * n * n * 8,
        "history": steps * actuators * 8 * 2 + steps * lenslets * 2 * 2,
    }
    largest = max(
        screen * screen * 16,
        science_side**2 * 16,
        batch * canvas * canvas * 16,
        actuators * support * 8,
    )
    return ResourceEstimate(
        label=label or f"{config.profile.profile_id} ({steps} frames)",
        baseline_bytes=160 * MIB,
        components=components,
        largest_buffer_bytes=int(largest),
        notes=(
            "analytic upper estimate from the profile; nothing was built",
            f"atmosphere screen {screen}x{screen} complex per layer",
            f"science grid {science_side}x{science_side} per wavelength",
        ),
    )


def dry_run_record(
    tier: str,
    *,
    n_steps: int | None = None,
    wavelengths: Sequence[float] | None = None,
    lenslet_batch_size: int = 512,
    timeout_s: float | None = None,
    output_dir: str | os.PathLike[str] | None = None,
    atmosphere_band_storage: str | None = None,
) -> dict[str, Any]:
    """Configuration, estimate, and current-host preflight; nothing is built."""

    config = tier_config(tier, n_steps=n_steps)
    storage = atmosphere_band_storage or (
        "regenerate" if tier in {"full", "reference"} else "materialized"
    )
    estimate = estimate_tier(
        config,
        wavelengths=wavelengths,
        lenslet_batch_size=lenslet_batch_size,
        atmosphere_band_storage=storage,
    )
    decision = preflight(estimate)
    spec = TIERS[tier]
    return {
        "tier": tier,
        "purpose": spec.purpose,
        "profile": config.profile.profile_id,
        "config_hash": config.config_hash,
        "n_steps": config.controller.n_steps,
        "n_steps_override": spec.n_steps_override if n_steps is None else n_steps,
        "burn_in_frames": spec.burn_in_frames,
        "pupil_pixels": config.pupil_pixels,
        "lenslets_across": config.lenslets_across,
        "actuators_across": config.actuators_across,
        "science_wavelengths_m": list(
            config.science_wavelengths_m if wavelengths is None else wavelengths
        ),
        "counts": _estimated_counts(config),
        "threads": DEFAULT_THREAD_LIMIT,
        "timeout_s": timeout_s,
        "output_dir": None if output_dir is None else str(output_dir),
        "requires_explicit_enable": tier in LARGE_TIERS,
        "atmosphere_band_storage": storage,
        "estimate": estimate.to_record(),
        "preflight": decision.to_record(),
    }


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _array_sha256(values: Any) -> str:
    import numpy as np

    array = np.asarray(values)
    if array.dtype == bool:
        return _sha256_bytes(array.astype(np.uint8).tobytes())
    return _sha256_bytes(np.ascontiguousarray(array, dtype="<f8").tobytes())


def _resource_sha256(name: str) -> str:
    from ..io.resources import read_text_resource

    return _sha256_bytes(read_text_resource(name).encode("utf-8"))


def _counts(system: Any, matrix: Any) -> dict[str, Any]:
    import numpy as np

    dm = system.dm
    geometry = system.wfs.geometry
    exclusions: dict[str, int] = {}
    for _, reason in matrix.exclusions:
        exclusions[reason] = exclusions.get(reason, 0) + 1
    config = system.source_config
    return {
        "lenslets": {
            "nominal": config.lenslets_across**2,
            "retained": geometry.n_subapertures,
            "calibration_valid": int(np.count_nonzero(matrix.row_valid)) // 2,
        },
        "actuators": {
            "nominal": config.actuators_across**2,
            "retained_layout": dm.n_actuators,
            "illuminated": int(np.count_nonzero(~np.asarray(dm.zero_support_mask))),
            "controllable": len(dm.controllable_actuator_ids),
            "calibrated_coordinates": len(matrix.coordinate_ids),
            "excluded_by_reason": exclusions,
        },
    }


def run_tier(
    tier: str,
    *,
    output_dir: str | os.PathLike[str],
    realization_index: int = 0,
    n_steps: int | None = None,
    burn_in_frames: int | None = None,
    wavelengths: Sequence[float] | None = None,
    lenslet_batch_size: int = 512,
    calibration_cache_dir: str | os.PathLike[str] | None = None,
    verify_observer_neutrality: bool = False,
    enable_large_run: bool = False,
    atmosphere_band_storage: str | None = None,
    authorization_note: str | None = None,
) -> dict[str, Any]:
    """Build, run, and record one tier through the canonical SCAO API.

    ``atmosphere_band_storage`` defaults to ``regenerate`` for the full and
    reference tiers (bit-identical frames, lower peak memory) and to
    ``materialized`` otherwise.
    """

    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}; expected one of {sorted(TIERS)}.")
    if tier in LARGE_TIERS and not enable_large_run:
        raise LargeRunNotEnabled(
            f"tier {tier!r} needs enable_large_run=True after the dry-run "
            "estimate has been reviewed (docs/refactor/ESO_SCAO_DEVELOPMENT_PROMPT.md "
            "section 2.3)."
        )
    import numpy as np

    from ..science.long_exposure import LongExposureConfig, StreamingLongExposure
    from .calibration_cache import SparseCalibrationCache
    from .scao import ScaoExecutionOptions, build_scao_system, run_closed_loop

    spec = TIERS[tier]
    config = tier_config(tier, n_steps=n_steps)
    burn_in = spec.burn_in_frames if burn_in_frames is None else int(burn_in_frames)
    if not 0 <= burn_in < config.controller.n_steps:
        raise ValueError(
            f"burn_in_frames={burn_in} leaves no science frame in a "
            f"{config.controller.n_steps}-frame {tier!r} run; pass burn_in_frames "
            "below n_steps."
        )
    science_wavelengths = tuple(
        config.science_wavelengths_m if wavelengths is None else wavelengths
    )
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    cache = (
        None
        if calibration_cache_dir is None
        else SparseCalibrationCache(calibration_cache_dir)
    )
    band_storage = atmosphere_band_storage or (
        "regenerate" if tier in {"full", "reference"} else "materialized"
    )
    execution = ScaoExecutionOptions(
        lenslet_batch_size=lenslet_batch_size,
        calibration_cache=cache,
        atmosphere_band_storage=band_storage,
    )
    timings: dict[str, float] = {}
    started = time.perf_counter()
    system = build_scao_system(config, execution=execution)
    timings["build_including_calibration_s"] = time.perf_counter() - started
    rss_marks = {"after_build": _peak_rss_bytes()}
    from ..calibration.sparse import SparseInteractionMatrix

    matrix = system.interaction_matrix
    if not isinstance(matrix, SparseInteractionMatrix):
        raise TypeError("benchmark tiers use the scalable sparse calibration.")
    reused = bool(system.build_attestation and system.build_attestation.calibration_reused)
    accumulator = StreamingLongExposure(
        system.science_propagator,
        LongExposureConfig(wavelengths_m=science_wavelengths, burn_in_frames=burn_in),
        telescope_diameter_m=config.telescope_diameter_m,
    )
    started = time.perf_counter()
    history = run_closed_loop(
        config,
        system=system,
        realization_index=realization_index,
        observers=(accumulator,),
    )
    timings["closed_loop_with_science_s"] = time.perf_counter() - started
    timings["per_frame_mean_s"] = timings["closed_loop_with_science_s"] / history.n_steps
    rss_marks["after_closed_loop"] = _peak_rss_bytes()
    started = time.perf_counter()
    science = accumulator.result()
    timings["science_metrics_s"] = time.perf_counter() - started
    rss_marks["after_science_metrics"] = _peak_rss_bytes()

    neutrality: dict[str, Any] | None = None
    if verify_observer_neutrality:
        started = time.perf_counter()
        bare = run_closed_loop(config, system=system, realization_index=realization_index)
        timings["observer_free_rerun_s"] = time.perf_counter() - started
        fields = (
            "pre_update_residual_opd_rms_m",
            "post_update_residual_opd_rms_m",
            "applied_command_history_opd_m",
            "requested_command_history_opd_m",
            "measurement_row_masks",
        )
        neutrality = {
            "loop_hash_equal": bare.config_hash == history.config_hash,
            "arrays_equal": {
                name: bool(np.array_equal(getattr(bare, name), getattr(history, name)))
                for name in fields
            },
        }
        neutrality["passed"] = neutrality["loop_hash_equal"] and all(
            neutrality["arrays_equal"].values()
        )

    # Solver statistics and the atmosphere's travel record belong to the
    # recorded runs; capture them before the timing probe adds its own solves
    # and resets the atmosphere.
    statistics = dict(getattr(system.reconstructor, "statistics", {}))
    atmosphere = system.atmosphere
    atmosphere_record = {
        "periodic_band_repeated": bool(getattr(atmosphere, "periodic_band_repeated", False)),
        "max_travel_m": float(getattr(atmosphere, "max_travel_m", float("nan"))),
        "screen_period_m": float(
            getattr(getattr(atmosphere, "config", None), "screen_period_m", float("nan"))
        ),
    }
    component_timings = _component_timings(system, science_wavelengths)
    rss_marks["after_component_probe"] = _peak_rss_bytes()
    usable = np.asarray(history.reconstruction_usable, dtype=bool)
    post_burn = slice(burn_in, None)
    applied = np.asarray(history.applied_command_history_opd_m)
    nonzero_updates = int(
        np.count_nonzero(usable & (np.asarray(history.delta_command_norm_m) > 0.0))
    )
    gates: dict[str, Any] = {}
    if tier == "medium-gate":
        usable_fraction = float(np.mean(usable[post_burn]))
        closed = float(np.mean(history.pre_update_residual_opd_rms_m[post_burn]))
        open_loop = float(np.mean(history.open_loop_opd_rms_m[post_burn]))
        gates["control_gate"] = {
            "usable_fraction_post_burn_in": usable_fraction,
            "mean_residual_rms_m": closed,
            "mean_open_loop_rms_m": open_loop,
            "rms_reduction_fraction": 1.0 - closed / open_loop,
            "thresholds": {
                "usable_fraction": _GATE_USABLE_FRACTION,
                "rms_reduction": _GATE_RMS_REDUCTION,
            },
            "passed": usable_fraction >= _GATE_USABLE_FRACTION
            and closed <= (1.0 - _GATE_RMS_REDUCTION) * open_loop,
        }
    if tier in {"full", "reference"}:
        gates["capability_gate"] = {
            "usable_nonzero_updates": nonzero_updates,
            "required": _CAPABILITY_MIN_UPDATES,
            "rejected_solves": statistics.get("rejected"),
            "passed": nonzero_updates >= _CAPABILITY_MIN_UPDATES
            and statistics.get("rejected", 0) == 0,
            "note": (
                f"capability evidence only (at least {_CAPABILITY_MIN_UPDATES} usable, "
                "nonzero updates and no rejected solve); it does not assess AO performance"
            ),
        }

    images: dict[str, str] = {}
    for image in science.images:
        tag = f"{image.psf.wavelength_m * 1e9:.0f}nm"
        path = output / f"science_{tag}.npz"
        np.savez_compressed(
            path,
            intensity=image.psf.intensity,
            ideal_intensity=image.ideal_psf.intensity,
            x_angle_rad=image.psf.x_angle_rad,
            y_angle_rad=image.psf.y_angle_rad,
            radial_radius_rad=image.radial_radius_rad,
            radial_profile=image.radial_profile,
            ideal_radial_profile=image.ideal_radial_profile,
        )
        images[tag] = path.name
    telemetry_path = output / "telemetry.npz"
    np.savez_compressed(
        telemetry_path,
        time_s=history.time_s,
        open_loop_opd_rms_m=history.open_loop_opd_rms_m,
        pre_update_residual_opd_rms_m=history.pre_update_residual_opd_rms_m,
        post_update_residual_opd_rms_m=history.post_update_residual_opd_rms_m,
        command_norm_m=history.command_norm_m,
        delta_command_norm_m=history.delta_command_norm_m,
        saturation_fraction=history.saturation_fraction,
        valid_measurement_fraction=history.valid_measurement_fraction,
        valid_subaperture_fraction=history.valid_subaperture_fraction,
        reconstruction_usable=history.reconstruction_usable,
        applied_command_history_opd_m=applied,
    )
    if cache is None and tier in {"medium", "medium-gate", "full", "reference"}:
        (output / "sparse_calibration.json").write_text(json.dumps(matrix.to_record()))
    snapshot = host_snapshot()
    manifest: dict[str, Any] = {
        "schema": _RESULT_SCHEMA,
        "label": "ESO-derived SCAO benchmark",
        "claim_boundary": (
            "software correctness and agreement with the declared ESO-derived "
            "model only; not an ESO instrument model, not validated against "
            "ESO SCAO data, and not comparable to the R1 GLAO/LTAO PSF files"
        ),
        "tier": tier,
        "purpose": spec.purpose,
        "profile": config.profile.profile_id,
        "profile_n_steps": load_system_profile(*spec.profile).controller.n_steps,
        "n_steps": history.n_steps,
        "config_hash": config.config_hash,
        "observing_conditions_hash": config.observing_conditions_hash,
        "profile_component_config_hashes": dict(config.component_config_hashes),
        "system_component_hashes": dict(system.component_hashes),
        "ledgers": {
            name: _resource_sha256(name)
            for name in (
                "benchmarks/eso_scao_source_ledger.v1.json",
                "benchmarks/eso_drm_42m_scao_derived.assumptions.v2.json",
            )
        },
        "realization_index": realization_index,
        "root_seed": config.random.root_seed,
        "counts": _counts(system, matrix),
        "calibration": {
            "calibration_hash": matrix.calibration_hash,
            "strategy": matrix.strategy,
            "probe_group_count": matrix.probe_group_count,
            "sensor_call_count": matrix.sensor_call_count,
            "nnz": matrix.nnz,
            "stored_bytes": matrix.stored_bytes,
            "reused_from_cache": reused,
            "cache_key": None if cache is None else cache.last_key,
        },
        "solver": {**dict(getattr(system.reconstructor, "metadata", {})), **statistics},
        "loop": {
            "loop_hash": history.config_hash,
            "reconstruction_usable_fraction": float(np.mean(usable)),
            "usable_nonzero_updates": nonzero_updates,
            "max_saturation_fraction": float(np.max(history.saturation_fraction)),
            "mean_open_loop_rms_nm": float(np.mean(history.open_loop_opd_rms_m) * 1e9),
            "mean_post_burn_in_residual_rms_nm": float(
                np.mean(history.pre_update_residual_opd_rms_m[post_burn]) * 1e9
            )
            if history.n_steps > burn_in
            else None,
            "final_post_update_residual_rms_nm": float(
                history.post_update_residual_opd_rms_m[-1] * 1e9
            ),
        },
        "timing_semantics": {
            "frame_period_s": 1.0 / config.controller.frame_rate_hz,
            "frame_timestamp": "k / frame_rate_hz; one instantaneous atmosphere sample per frame",
            "detector_exposure_field_s": config.detector.exposure_s,
            "detector_integration": "none: instantaneous snapshot (exposure_s is recorded, not integrated)",
            "latency_frames": config.controller.latency_frames,
            "measured_to_first_seen_delay_frames": config.controller.latency_frames + 1,
            "command_release": "controller queue releases frame k's increment in the update of frame k + latency_frames",
            "science_residual": science.selection.residual_description,
            "science_temporal_quadrature": science.selection.temporal_quadrature,
        },
        "science": science.to_record(),
        "science_files": images,
        "gates": gates,
        "observer_neutrality": neutrality,
        "atmosphere": atmosphere_record,
        "timings_s": timings,
        "component_timings_s": component_timings,
        "process_peak_rss_high_water_bytes": rss_marks,
        "execution": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "numpy": np.__version__,
            "thread_environment": {name: os.environ.get(name) for name in THREAD_ENV_VARS},
            "lenslet_batch_size": lenslet_batch_size,
            "atmosphere_band_storage": band_storage,
            "authorization_note": authorization_note,
            "host": snapshot.to_record(),
            "process_peak_rss_bytes": _peak_rss_bytes(),
        },
        "telemetry_file": telemetry_path.name,
        "telemetry_sha256": {
            "applied_command_history_opd_m": _array_sha256(applied),
            "pre_update_residual_opd_rms_m": _array_sha256(history.pre_update_residual_opd_rms_m),
        },
        "science_sha256": {
            f"{image.psf.wavelength_m * 1e9:.0f}nm": _array_sha256(image.psf.intensity)
            for image in science.images
        },
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=_json_default) + "\n"
    )
    return manifest


def _component_timings(system: Any, wavelengths: Sequence[float], repeats: int = 3) -> dict[str, float]:
    """Mean wall time of each per-frame component, measured after the run.

    The probe calls each component directly on fresh inputs (a new atmosphere
    sample, its WFS measurement, one reconstruction, one DM synthesis of the
    resulting increment, and one science propagation per wavelength), so it
    cannot change the recorded run.  It is a timing breakdown, not part of
    the loop.
    """

    import numpy as np

    from ..core.types import DmCommandVector

    totals = {
        "atmosphere_frame": 0.0,
        "wfs_measurement": 0.0,
        "reconstruction": 0.0,
        "dm_synthesis": 0.0,
        "science_propagation_all_wavelengths": 0.0,
    }
    system.atmosphere.reset(realization_index=0)
    for index in range(repeats):
        started = time.perf_counter()
        opd = np.asarray(system.atmosphere.opd_at(0.002 * (index + 1)))
        totals["atmosphere_frame"] += time.perf_counter() - started
        started = time.perf_counter()
        measurement = system.wfs.measure(
            np.where(np.isfinite(opd), opd, 0.0),
            random_streams=system.random_streams,
            include_noise=False,
        )
        totals["wfs_measurement"] += time.perf_counter() - started
        started = time.perf_counter()
        estimate = system.reconstructor.reconstruct(measurement.vector)
        totals["reconstruction"] += time.perf_counter() - started
        values = np.zeros(system.dm.n_actuators)
        if estimate is not None:
            values = np.asarray(
                system.command_projector.project(estimate).values_opd_m, dtype=float
            )
        started = time.perf_counter()
        system.dm.opd_from_commands(
            DmCommandVector(values, system.dm.actuator_ids, "m_opd_equivalent")
        )
        totals["dm_synthesis"] += time.perf_counter() - started
        started = time.perf_counter()
        for wavelength in wavelengths:
            system.science_propagator.psf_from_opd(opd, wavelength)
        totals["science_propagation_all_wavelengths"] += time.perf_counter() - started
    system.atmosphere.reset(realization_index=0)
    return {key: value / repeats for key, value in totals.items()}


def _peak_rss_bytes() -> int | None:
    try:
        import resource
    except ImportError:  # pragma: no cover - non-POSIX
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes, Linux kibibytes.
    return int(peak if sys.platform == "darwin" else peak * 1024)


def _json_default(value: Any) -> Any:
    try:
        import numpy as np
    except ImportError:  # pragma: no cover
        raise TypeError(type(value).__name__) from None
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (tuple, set, frozenset)):
        return list(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _default_output_dir(tier: str) -> Path:
    base = os.environ.get("AO_DEMO_OUTPUT_DIR")
    root = Path(base) if base else Path.cwd() / "eso_scao_benchmark_output"
    return root / f"eso_scao_{tier}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_eso_scao_benchmark",
        description=(
            "Run an ESO-derived SCAO benchmark tier through the canonical SCAO "
            "API in a supervised, thread-limited child process."
        ),
    )
    parser.add_argument("--tier", choices=sorted(TIERS), default="ci")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--realization-index", type=int, default=0)
    parser.add_argument("--frames", type=int, default=None, help="override n_steps")
    parser.add_argument("--burn-in", type=int, default=None)
    parser.add_argument(
        "--science-wavelengths", type=float, nargs="+", default=None,
        help="monochromatic science wavelengths in metres",
    )
    parser.add_argument("--lenslet-batch-size", type=int, default=512)
    parser.add_argument("--calibration-cache", type=Path, default=None)
    parser.add_argument("--verify-observer-neutrality", action="store_true")
    parser.add_argument("--enable-large-run", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--memory-limit-mib", type=float, default=None,
        help="lower (never raise) the desktop memory budget",
    )
    parser.add_argument(
        "--authorized-budget-mib", type=float, default=None,
        help=(
            "a budget above the desktop policy that a human explicitly "
            "authorized for this run; requires --authorization-note"
        ),
    )
    parser.add_argument("--authorization-note", default=None)
    parser.add_argument(
        "--atmosphere-band-storage", choices=("materialized", "regenerate"), default=None,
        help="execution mode of the layered atmosphere's band coefficients",
    )
    parser.add_argument("--timeout-s", type=float, default=DEFAULT_EXAMPLE_TIMEOUT_S)
    parser.add_argument("--threads", type=int, default=DEFAULT_THREAD_LIMIT)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    return parser


def _authorized_decision(
    record: dict[str, Any],
    *,
    authorized_bytes: int,
    note: str,
) -> tuple[bool, list[str]]:
    """Re-check a run against a human-authorized budget above the policy.

    The authorization replaces only the budget number.  Current pressure must
    still be normal, the largest buffer must still respect the scratch
    ceiling, and the host must currently have the run's unmargined estimate
    plus a 1 GiB reserve available, so the run does not depend on swap.
    """

    snapshot = host_snapshot()
    estimate = record["estimate"]
    reasons: list[str] = []
    if not note.strip():
        reasons.append("an authorized budget needs --authorization-note")
    if estimate["required_bytes"] > authorized_bytes:
        reasons.append(
            f"estimated peak {estimate['required_bytes'] / MIB:.0f} MiB exceeds the "
            f"authorized {authorized_bytes / MIB:.0f} MiB"
        )
    if estimate["largest_buffer_bytes"] > 64 * MIB:
        reasons.append("largest single buffer exceeds the 64 MiB scratch ceiling")
    if snapshot.pressure.level != "normal":
        reasons.append(f"host memory pressure is {snapshot.pressure.level} now")
    reserve = 1024 * MIB
    if snapshot.available_bytes is None or snapshot.available_bytes < estimate["raw_bytes"] + reserve:
        reasons.append(
            "measured available memory "
            f"{(snapshot.available_bytes or 0) / MIB:.0f} MiB is below the unmargined "
            f"estimate plus a 1 GiB reserve ({(estimate['raw_bytes'] + reserve) / MIB:.0f} MiB)"
        )
    record["authorization"] = {
        "authorized_budget_bytes": authorized_bytes,
        "note": note,
        "snapshot": snapshot.to_record(),
        "accepted": not reasons,
        "reasons": reasons,
    }
    return not reasons, reasons


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    output_dir = arguments.output_dir or _default_output_dir(arguments.tier)
    if arguments.child:
        manifest = run_tier(
            arguments.tier,
            output_dir=output_dir,
            realization_index=arguments.realization_index,
            n_steps=arguments.frames,
            burn_in_frames=arguments.burn_in,
            wavelengths=arguments.science_wavelengths,
            lenslet_batch_size=arguments.lenslet_batch_size,
            calibration_cache_dir=arguments.calibration_cache,
            verify_observer_neutrality=arguments.verify_observer_neutrality,
            enable_large_run=arguments.enable_large_run,
            atmosphere_band_storage=arguments.atmosphere_band_storage,
            authorization_note=arguments.authorization_note,
        )
        print(json.dumps({"loop": manifest["loop"], "gates": manifest["gates"]}, indent=2))
        return 0
    record = dry_run_record(
        arguments.tier,
        n_steps=arguments.frames,
        wavelengths=arguments.science_wavelengths,
        lenslet_batch_size=arguments.lenslet_batch_size,
        timeout_s=arguments.timeout_s,
        output_dir=output_dir,
        atmosphere_band_storage=arguments.atmosphere_band_storage,
    )
    budget = record["preflight"]["budget_bytes"]
    if arguments.memory_limit_mib is not None:
        budget = min(budget, int(arguments.memory_limit_mib * MIB))
    accepted = record["preflight"]["accepted"] and record["estimate"]["required_bytes"] <= budget
    if arguments.authorized_budget_mib is not None and not arguments.dry_run:
        budget = int(arguments.authorized_budget_mib * MIB)
        if arguments.memory_limit_mib is not None:
            budget = min(budget, int(arguments.memory_limit_mib * MIB))
        accepted, _ = _authorized_decision(
            record, authorized_bytes=budget, note=arguments.authorization_note or ""
        )
    if arguments.dry_run:
        print(json.dumps(record, indent=2, sort_keys=True))
        return 0
    if arguments.tier in LARGE_TIERS and not arguments.enable_large_run:
        print(
            json.dumps(
                {"status": "NOT_RUN_RESOURCE_POLICY", "reason": "large tier needs --enable-large-run", "dry_run": record},
                indent=2,
                sort_keys=True,
            )
        )
        return 3
    if not accepted:
        output_dir.mkdir(parents=True, exist_ok=True)
        refusal = {"status": "NOT_RUN_RESOURCE_POLICY", "dry_run": record}
        (output_dir / "not_run_resource_policy.json").write_text(
            json.dumps(refusal, indent=2, sort_keys=True) + "\n"
        )
        print(json.dumps(refusal, indent=2, sort_keys=True))
        return 3
    child = [sys.executable, "-m", "shwfs_ao.experiments.eso_scao_benchmark", "--child"]
    for flag, value in (
        ("--tier", arguments.tier),
        ("--output-dir", output_dir),
        ("--realization-index", arguments.realization_index),
        ("--frames", arguments.frames),
        ("--burn-in", arguments.burn_in),
        ("--lenslet-batch-size", arguments.lenslet_batch_size),
        ("--calibration-cache", arguments.calibration_cache),
        ("--atmosphere-band-storage", arguments.atmosphere_band_storage),
        ("--authorization-note", arguments.authorization_note),
    ):
        if value is not None:
            child += [flag, str(value)]
    if arguments.science_wavelengths:
        child += ["--science-wavelengths", *map(str, arguments.science_wavelengths)]
    if arguments.verify_observer_neutrality:
        child.append("--verify-observer-neutrality")
    if arguments.enable_large_run:
        child.append("--enable-large-run")
    output_dir.mkdir(parents=True, exist_ok=True)
    result = run_supervised(
        child,
        budget_bytes=int(budget),
        timeout_s=arguments.timeout_s,
        threads=arguments.threads,
        log_path=output_dir / "run.log",
    )
    summary = {"supervisor": result.to_record(), "dry_run": record}
    (output_dir / "supervisor.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(result.to_record(), indent=2, sort_keys=True))
    return 0 if result.status == "COMPLETED" else 1


if __name__ == "__main__":  # pragma: no cover - command-line entry
    raise SystemExit(main())
