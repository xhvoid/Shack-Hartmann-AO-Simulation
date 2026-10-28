"""Series plan, guarded execution and raw evidence of the explorer trajectories.

Execution model
---------------
* ``draft_plan`` writes the machine-readable series plan before the pilot:
  every job's effective configuration and hash, its complete-horizon
  admission record, the movie indices, the frozen scene (from the native
  propagator's actual grid, before any AO result exists), the tolerances,
  the ceilings and the source/exporter/environment identities.
* ``freeze_plan`` binds the pilot's measured cost and the batch projection
  into the frozen plan that production jobs require.
* ``run_job`` is the numerical child.  It refuses to start unless the plan's
  identities match the running code and environment, the job's configuration
  hash matches the plan, and a fresh admission evaluation matches the plan's
  record and admits the job.  Only then does it build the system and run the
  canonical loop.  An existing attempt directory is never overwritten.
* ``supervise`` is the parent: it checks the cumulative wall-time and raw-byte
  ceilings, runs the resource guard's preflight, launches the child under
  ``run_supervised`` with two native threads and a timeout, and appends every
  outcome (refusals included) to the series ledger.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass, replace
import datetime
import json
import math
import os
from pathlib import Path
import resource
import sys
import time
from typing import Any, Dict, List, Optional

import identity
import protocol


LEDGER_NAME = "ledger.jsonl"
DRAFT_PLAN_NAME = "series_plan.draft.json"
FROZEN_PLAN_NAME = "series_plan.json"


class ProducerError(RuntimeError):
    """Raised when a plan, identity, admission or resume check refuses a job."""


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def to_jsonable(value: Any) -> Any:
    """Plain JSON value; non-finite floats become None (callers attach a reason)."""

    import numpy as np

    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: to_jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, dict) or hasattr(value, "items"):
        return {str(key): to_jsonable(item) for key, item in dict(value).items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return to_jsonable(value.tolist())
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if value is None or isinstance(value, str):
        return value
    return repr(value)


def write_json(path: Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Configurations


def base_config() -> Any:
    from shwfs_ao.io.configs import load_system_profile

    return load_system_profile(protocol.PROFILE_NAME, protocol.PROFILE_VERSION)


def job_config(job: Dict[str, Any]) -> Any:
    """The effective configuration of one job: profile + explorer overrides + case override."""

    from shwfs_ao.experiments.detector_level import with_magnitude

    base = base_config()
    config = replace(
        base,
        controller=replace(base.controller, n_steps=int(job["n_steps"])),
        random=replace(base.random, root_seed=int(job["root_seed"])),
    )
    override = protocol.case_by_id(job["case_id"])["override"]
    for key, value in override.items():
        if key == "r0_scale":
            config = replace(config, atmosphere=replace(config.atmosphere, r0_m=base.atmosphere.r0_m * float(value)))
        elif key == "ab_magnitude":
            config = with_magnitude(config, float(value))
        elif key == "gain":
            config = replace(config, controller=replace(config.controller, gain=float(value)))
        elif key == "latency_frames":
            config = replace(config, controller=replace(config.controller, latency_frames=int(value)))
        else:
            raise ProducerError(f"unknown override {key!r}")
    return config


def effective_parameters(config: Any) -> Dict[str, Any]:
    """The physical/numerical parameters a visitor and a reviewer need, with units."""

    from shwfs_ao.experiments.detector_level import max_pole_modulus

    physics = config.detector_physics
    latency = int(config.controller.latency_frames)
    return {
        "telescope_diameter_m": config.telescope_diameter_m,
        "pupil_pixels": config.pupil_pixels,
        "lenslets_across": config.lenslets_across,
        "actuators_across": config.actuators_across,
        "wfs_wavelength_m": config.wfs_wavelength_m,
        "profile_science_wavelengths_m": list(config.science_wavelengths_m),
        "explorer_science_wavelength_m": protocol.SCIENCE_WAVELENGTH_M,
        "atmosphere_model": config.atmosphere_model,
        "r0_m": config.atmosphere.r0_m,
        "r0_reference_wavelength_m": config.atmosphere.r0_reference_wavelength_m,
        "outer_scale_m": config.atmosphere.outer_scale_m,
        "wind_m_per_s": list(config.atmosphere.wind_m_per_s),
        "source_kind": physics.source.kind,
        "source_ab_magnitude": physics.source.ab_magnitude,
        "sky_ab_mag_per_arcsec2": physics.source.sky_ab_mag_per_arcsec2,
        "throughput_excluding_qe": physics.source.throughput_excluding_qe,
        "camera_preset": f"{physics.camera.preset_name}@{physics.camera.preset_version}",
        "detector_noise_in_loop": bool(config.controller.include_noise),
        "exposure_s": config.detector.exposure_s,
        "exposure_subsamples": physics.exposure_subsamples,
        "controller_gain": config.controller.gain,
        "controller_leak": config.controller.leak,
        "queued_latency_frames": latency,
        "wfs_visible_delay_frames": latency + 1,
        "delay_semantics": (
            "A reconstruction from frame k is released in the update of frame k + L and first "
            "seen by the WFS at frame k + L + 1 (control/controller.py delay queue; "
            "control/observation.py FrameObservation)."
        ),
        "frame_rate_hz": config.controller.frame_rate_hz,
        "n_steps": config.controller.n_steps,
        "root_seed": config.random.root_seed,
        "reconstructor": f"{config.reconstructor.kind} rcond={config.reconstructor.rcond} min_valid_fraction={config.reconstructor.min_valid_fraction}",
        "calibration": f"source={config.calibration.source} method={config.calibration.method} include_noise={config.calibration.include_noise}",
        "dm_stroke_limit_opd_m": config.dm.stroke_limit_opd_m,
        "max_pole_modulus": max_pole_modulus(config.controller.gain, config.controller.leak, latency),
    }


# ---------------------------------------------------------------------------
# Plans


def native_science_grid(config: Any) -> Dict[str, Any]:
    """The native science propagator's axes, from the propagator itself (no AO run)."""

    import numpy as np
    from shwfs_ao.backends.native.factory import NATIVE_SCAO_COMPONENT_FACTORY
    from shwfs_ao.science.propagation import PsfSampling

    geometry = NATIVE_SCAO_COMPONENT_FACTORY.build_geometry(
        telescope_diameter_m=config.telescope_diameter_m,
        pupil_pixels=config.pupil_pixels,
        lenslets_across=config.lenslets_across,
        min_fill_fraction=config.wfs.min_fill_fraction,
        central_obstruction_ratio=config.wfs.central_obstruction_ratio,
        spider_width_m=config.wfs.spider_width_m,
    )
    propagator = NATIVE_SCAO_COMPONENT_FACTORY.build_science_propagator(
        geometry=geometry, sampling=PsfSampling(pad_factor=config.science.psf_pad_factor)
    )
    ideal = propagator.psf_from_opd(np.zeros(geometry.pupil_shape, dtype=float), protocol.SCIENCE_WAVELENGTH_M)
    return {
        "x_angle_rad": np.array(ideal.x_angle_rad, dtype=float),
        "y_angle_rad": np.array(ideal.y_angle_rad, dtype=float),
        "propagator_config_hash": propagator.config_hash,
        "sampling_metadata": dict(ideal.sampling_metadata),
    }


def draft_plan(series_dir: Path, series_id: str) -> Dict[str, Any]:
    import admission
    import binary_scene

    series_dir = Path(series_dir)
    if (series_dir / DRAFT_PLAN_NAME).exists():
        raise ProducerError(f"{series_dir / DRAFT_PLAN_NAME} exists; a series plan is never overwritten.")
    jobs = []
    for job in protocol.production_jobs():
        config = job_config(job)
        record = admission.admit(config)
        jobs.append(
            {
                **job,
                "config_hash": config.config_hash,
                "profile": f"{protocol.PROFILE_NAME}@{protocol.PROFILE_VERSION}",
                "case_override": protocol.case_by_id(job["case_id"])["override"],
                "effective_parameters": effective_parameters(config),
                "admission": record,
                "admission_sha256": identity.sha256_bytes(identity.canonical_json_bytes(record)),
            }
        )
    baseline = job_config(protocol.production_jobs()[1])
    grid = native_science_grid(baseline)
    scene = binary_scene.build_scene(
        grid["x_angle_rad"],
        grid["y_angle_rad"],
        wavelength_m=protocol.SCIENCE_WAVELENGTH_M,
        telescope_diameter_m=baseline.telescope_diameter_m,
    )
    plan = {
        "schema": protocol.SERIES_PLAN_SCHEMA,
        "state": "DRAFT_BEFORE_PILOT",
        "series_id": series_id,
        "created_utc": utc_now(),
        "protocol_version": protocol.PROTOCOL_VERSION,
        "profile": {"name": protocol.PROFILE_NAME, "version": protocol.PROFILE_VERSION, "config_hash": base_config().config_hash},
        "explorer_overrides": {
            "n_steps": protocol.PRODUCTION_FRAMES,
            "burn_in_frames": protocol.PRODUCTION_BURN_IN,
            "root_seed": protocol.ROOT_SEED,
            "realization_index": protocol.REALIZATION_INDEX,
            "science_wavelength_m": protocol.SCIENCE_WAVELENGTH_M,
            "note": "Demonstration protocol choices, not a new accepted profile; the profile resource is unchanged.",
        },
        "analysis_window": {
            "production": {"start": protocol.PRODUCTION_BURN_IN, "stop": protocol.PRODUCTION_FRAMES, "count": protocol.PRODUCTION_FRAMES - protocol.PRODUCTION_BURN_IN, "weights": "equal"},
            "pilot": {"start": protocol.PILOT_BURN_IN, "stop": protocol.PILOT_FRAMES, "count": protocol.PILOT_FRAMES - protocol.PILOT_BURN_IN, "weights": "equal"},
        },
        "movie_indices": list(protocol.movie_indices()),
        "pilot_display_indices": list(protocol.PILOT_DISPLAY_INDICES),
        "jobs": jobs,
        "all_jobs_admitted": all(job["admission"]["admitted"] for job in jobs),
        "scene": scene["record"],
        "science_grid": {
            "propagator_config_hash": grid["propagator_config_hash"],
            "x_angle_rad_sha256": identity.sha256_bytes(grid["x_angle_rad"].tobytes()),
            "y_angle_rad_sha256": identity.sha256_bytes(grid["y_angle_rad"].tobytes()),
            "shape": [int(grid["y_angle_rad"].size), int(grid["x_angle_rad"].size)],
            "sampling_metadata": to_jsonable(grid["sampling_metadata"]),
        },
        "binary_observation_policy": binary_scene.CONVOLUTION_POLICY,
        "tolerances": protocol.TOLERANCES,
        "ceilings": {
            "numerical_wall_time_s": protocol.WALL_TIME_CEILING_S,
            "raw_evidence_bytes": protocol.RAW_EVIDENCE_CEILING_BYTES,
            "child_timeout_s": protocol.CHILD_TIMEOUT_S,
            "native_threads": protocol.NATIVE_THREADS,
            "accounting": "every supervised child (pilot, production, controls, failed attempts, observation and rendering processing) adds its measured wall time; every byte under the series directory counts as raw evidence",
        },
        "identities": {
            "core": identity.core_identity(),
            "exporter": identity.exporter_identity(),
            "environment": identity.environment_identity(),
            "lock": identity.lock_verification(),
            "host": identity.host_identity(),
        },
    }
    write_json(series_dir / DRAFT_PLAN_NAME, plan)
    return plan


def load_plan(series_dir: Path, *, frozen: bool) -> Dict[str, Any]:
    path = Path(series_dir) / (FROZEN_PLAN_NAME if frozen else DRAFT_PLAN_NAME)
    if not path.exists():
        raise ProducerError(f"missing series plan {path}")
    return read_json(path)


def plan_job(plan: Dict[str, Any], job_id: str) -> Dict[str, Any]:
    for job in plan["jobs"]:
        if job["job_id"] == job_id:
            return job
    raise ProducerError(f"job {job_id!r} is not in the series plan")


def check_identities(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Refuse a job when the running code or environment differs from the plan's."""

    current = {
        "core": identity.core_identity(),
        "exporter": identity.exporter_identity(),
        "environment": identity.environment_identity(),
        "lock": identity.lock_verification(),
    }
    recorded = plan["identities"]
    problems = []
    if current["core"]["package_sha256"] != recorded["core"]["package_sha256"]:
        problems.append("core package digest differs from the plan")
    if current["exporter"]["sha256"] != recorded["exporter"]["sha256"]:
        problems.append("exporter source digest differs from the plan (a changed exporter is a new series)")
    if current["environment"] != recorded["environment"]:
        problems.append("numerical environment differs from the plan")
    if not current["lock"]["verified"] or current["lock"]["lock_sha256"] != recorded["lock"]["lock_sha256"]:
        problems.append("environment is not the plan's verified constraint lock")
    if problems:
        raise ProducerError("; ".join(problems))
    return current


# ---------------------------------------------------------------------------
# Ledger and ceilings


def ledger_entries(series_dir: Path) -> List[Dict[str, Any]]:
    path = Path(series_dir) / LEDGER_NAME
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_ledger(series_dir: Path, entry: Dict[str, Any]) -> None:
    path = Path(series_dir) / LEDGER_NAME
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, allow_nan=False, sort_keys=True) + "\n")


def consumption(series_dir: Path) -> Dict[str, Any]:
    entries = ledger_entries(series_dir)
    wall = sum(float(entry.get("wall_s") or 0.0) for entry in entries)
    raw = 0
    for path in Path(series_dir).rglob("*"):
        if path.is_file():
            raw += path.stat().st_size
    return {
        "wall_s": wall,
        "raw_bytes": raw,
        "launches": sum(1 for entry in entries if entry.get("launched")),
        "entries": len(entries),
    }


# ---------------------------------------------------------------------------
# Child job


def next_attempt_dir(series_dir: Path, job_id: str) -> Path:
    root = Path(series_dir) / "jobs" / job_id
    root.mkdir(parents=True, exist_ok=True)
    number = 1 + sum(1 for path in root.iterdir() if path.is_dir() and path.name.startswith("attempt-"))
    return root / f"attempt-{number:02d}"


def completed_attempt(series_dir: Path, job_id: str) -> Optional[Path]:
    root = Path(series_dir) / "jobs" / job_id
    if not root.exists():
        return None
    for path in sorted(root.iterdir()):
        status = path / "status.json"
        if status.exists() and read_json(status).get("status") == "COMPLETED":
            return path
    return None


def history_arrays(history: Any) -> Dict[str, Any]:
    import numpy as np

    arrays = {}
    for name in (
        "time_s",
        "open_loop_opd_rms_m",
        "pre_update_residual_opd_rms_m",
        "post_update_residual_opd_rms_m",
        "command_norm_m",
        "delta_command_norm_m",
        "released_delta_norm_m",
        "requested_command_history_opd_m",
        "applied_command_history_opd_m",
        "saturation_fraction",
        "valid_measurement_fraction",
        "valid_subaperture_fraction",
        "reconstruction_usable",
        "measurement_row_masks",
    ):
        arrays[name] = np.ascontiguousarray(np.asarray(getattr(history, name)))
    return arrays


def history_digest(history: Any) -> Dict[str, Any]:
    arrays = history_arrays(history)
    members = {name: identity.sha256_bytes(array.tobytes()) for name, array in arrays.items()}
    metadata = to_jsonable(history.metadata)
    members["metadata"] = identity.sha256_bytes(identity.canonical_json_bytes(metadata))
    members["config_hash"] = history.config_hash
    return {"members": members, "sha256": identity.sha256_bytes(identity.canonical_json_bytes(members))}


def run_job(series_dir: Path, job_id: str, *, frozen: bool) -> Dict[str, Any]:
    """The numerical child: refuse unless every pre-execution check passes, then run."""

    import numpy as np

    import admission
    from observer import ExplorerObserver, independent_peak_strehl, independent_rms

    started_wall = time.perf_counter()
    series_dir = Path(series_dir)
    plan = load_plan(series_dir, frozen=frozen)
    job = plan_job(plan, job_id)
    if frozen and plan.get("state") != "FROZEN":
        raise ProducerError("production jobs need the frozen series plan.")
    if not frozen and job["role"] != "pilot":
        raise ProducerError("only the pilot may run against the draft plan.")
    if completed_attempt(series_dir, job_id) is not None:
        raise ProducerError(f"{job_id} already has a completed attempt; matching-identity data are reused, not rerun.")
    current = check_identities(plan)
    config = job_config(job)
    if config.config_hash != job["config_hash"]:
        raise ProducerError("effective configuration hash differs from the plan.")
    fresh = admission.admit(config)
    fresh_sha = identity.sha256_bytes(identity.canonical_json_bytes(fresh))
    if fresh_sha != job["admission_sha256"]:
        raise ProducerError("a fresh admission evaluation differs from the plan's record.")
    if not fresh["admitted"]:
        raise ProducerError(f"admission refused: {fresh['reasons']}")

    attempt = next_attempt_dir(series_dir, job_id)
    attempt.mkdir(parents=False, exist_ok=False)
    write_json(attempt / "status.json", {"status": "STARTED", "utc": utc_now(), "job_id": job_id})

    from shwfs_ao.experiments.scao import build_scao_system, run_closed_loop

    build_started = time.perf_counter()
    system = build_scao_system(config)
    build_s = time.perf_counter() - build_started
    built_model = to_jsonable(system.atmosphere.config)
    if built_model != to_jsonable(fresh["model_config"]):
        raise ProducerError("the built atmosphere differs from the admitted model configuration.")
    if (system.atmosphere.config.generated_grid_size, float(system.atmosphere.config.travel_budget_px)) != (
        fresh["generated_screen_px"],
        fresh["travel_budget_px"],
    ):
        raise ProducerError("the built screen geometry differs from the admitted one.")

    observer = None
    observers: tuple = ()
    if job["observer"]:
        observer = ExplorerObserver(
            system.science_propagator,
            wavelength_m=protocol.SCIENCE_WAVELENGTH_M,
            n_steps=job["n_steps"],
            burn_in=job["burn_in"],
            display_indices=job["display_indices"],
            telescope_diameter_m=config.telescope_diameter_m,
        )
        observers = (observer,)
    loop_started = time.perf_counter()
    history = run_closed_loop(config, system=system, realization_index=protocol.REALIZATION_INDEX, observers=observers)
    loop_s = time.perf_counter() - loop_started

    travelled = float(system.atmosphere.travelled_px)
    horizon_check = {
        "atmosphere_travelled_px": travelled,
        "admitted_max_travel_px": fresh["max_travel_px"],
        "equal": travelled == fresh["max_travel_px"],
        "exceeded_travel_budget": bool(system.atmosphere.exceeded_travel_budget),
    }
    if not horizon_check["equal"] or horizon_check["exceeded_travel_budget"]:
        raise ProducerError(f"runtime travel {travelled!r} px disagrees with the admitted schedule.")

    arrays = history_arrays(history)
    np.savez(attempt / "history.npz", **arrays)
    record: Dict[str, Any] = {
        "schema": protocol.JOB_RECORD_SCHEMA,
        "series_id": plan["series_id"],
        "job": {key: job[key] for key in ("job_id", "role", "case_id", "n_steps", "burn_in", "root_seed", "observer", "display_indices")},
        "config_hash": config.config_hash,
        "history_config_hash": history.config_hash,
        "admission_sha256": fresh_sha,
        "horizon_runtime_check": horizon_check,
        "identities": current,
        "build_s": build_s,
        "loop_s": loop_s,
        "history_digest": history_digest(history),
        "history_metadata": to_jsonable(history.metadata),
        "component_hashes": to_jsonable(history.metadata.get("component_hashes")),
        "science_propagator_config_hash": system.science_propagator.config_hash,
    }
    if observer is not None:
        export_started = time.perf_counter()
        finish = observer.finish()
        mask = observer.pupil_mask
        frames = observer.frames
        checks = {}
        rms_tol = protocol.TOLERANCES["rms_m"]
        atm_rms = np.asarray(frames["atmosphere_rms_m"])
        res_rms = np.asarray(frames["residual_rms_m"])
        checks["atmosphere_rms_matches_history"] = bool(np.array_equal(atm_rms, arrays["open_loop_opd_rms_m"]))
        checks["residual_rms_matches_history"] = bool(np.array_equal(res_rms, arrays["pre_update_residual_opd_rms_m"]))
        checks["times_match_history"] = bool(np.array_equal(np.asarray(frames["time_s"]), arrays["time_s"]))
        checks["usable_matches_history"] = bool(np.array_equal(np.asarray(frames["reconstruction_usable"]), arrays["reconstruction_usable"]))
        checks["saturation_matches_history"] = bool(np.array_equal(np.asarray(frames["saturation_fraction"]), arrays["saturation_fraction"]))
        # Independent reductions at the retained display frames.
        display_checks = []
        for index in sorted(observer.display):
            snapshot = observer.display[index]
            atm_independent = independent_rms(snapshot["atmosphere_opd_m"], mask)
            res_independent = independent_rms(snapshot["pre_update_residual_opd_m"], mask)
            unc_strehl = independent_peak_strehl(snapshot["psf_uncorrected"], finish["ideal_psf"])
            ao_strehl = independent_peak_strehl(snapshot["psf_corrected"], finish["ideal_psf"])
            display_checks.append(
                {
                    "frame": index,
                    "atmosphere_rms_abs_error_m": abs(atm_independent - atm_rms[index]),
                    "residual_rms_abs_error_m": abs(res_independent - res_rms[index]),
                    "uncorrected_strehl_abs_error": abs(unc_strehl - frames["peak_strehl_uncorrected"][index]),
                    "corrected_strehl_abs_error": abs(ao_strehl - frames["peak_strehl_corrected"][index]),
                    "held_correction_identity_max_abs_m": float(
                        np.nanmax(np.abs(snapshot["atmosphere_opd_m"] - snapshot["held_correction_opd_m"] - snapshot["pre_update_residual_opd_m"]))
                    ),
                }
            )
        checks["display_frame_independent_reductions"] = display_checks
        checks["display_frame_reductions_within_tolerance"] = all(
            item["atmosphere_rms_abs_error_m"] <= rms_tol["atol"] + rms_tol["rtol"] * atm_rms[item["frame"]]
            and item["residual_rms_abs_error_m"] <= rms_tol["atol"] + rms_tol["rtol"] * res_rms[item["frame"]]
            and item["uncorrected_strehl_abs_error"] <= protocol.TOLERANCES["strehl"]["atol"]
            and item["corrected_strehl_abs_error"] <= protocol.TOLERANCES["strehl"]["atol"]
            for item in display_checks
        )
        checks["streaming_max_abs_difference"] = finish["streaming_max_abs_difference"]
        checks["streaming_within_tolerance"] = all(
            value <= protocol.TOLERANCES["mean_psf"]["atol"] for value in finish["streaming_max_abs_difference"].values()
        )
        unit = protocol.TOLERANCES["unit_flux"]["atol"]
        checks["instantaneous_unit_flux"] = bool(
            np.all(np.abs(np.asarray(frames["flux_uncorrected"]) - 1.0) <= unit)
            and np.all(np.abs(np.asarray(frames["flux_corrected"]) - 1.0) <= unit)
        )
        checks["mean_unit_flux"] = {
            "uncorrected": float(np.sum(finish["mean_psf_uncorrected"])),
            "corrected": float(np.sum(finish["mean_psf_corrected"])),
        }
        corrected_result = finish["corrected_result"]
        uncorrected_result = finish["uncorrected_result"]
        x_axis = observer.axes["x_angle_rad"]
        y_axis = observer.axes["y_angle_rad"]
        np.savez(
            attempt / "mean_psfs.npz",
            mean_psf_uncorrected=finish["mean_psf_uncorrected"],
            mean_psf_corrected=finish["mean_psf_corrected"],
            own_mean_psf_uncorrected=finish["own_mean_psf_uncorrected"],
            own_mean_psf_corrected=finish["own_mean_psf_corrected"],
            ideal_psf=finish["ideal_psf"],
            x_angle_rad=x_axis,
            y_angle_rad=y_axis,
            analysis_frames=np.asarray(finish["analysis_frames"], dtype=np.int64),
            pupil_mask=np.asarray(mask, dtype=bool),
        )
        display_order = sorted(observer.display)
        if display_order:
            np.savez(
                attempt / "movie.npz",
                indices=np.asarray(display_order, dtype=np.int64),
                time_s=np.asarray([frames["time_s"][index] for index in display_order]),
                atmosphere_opd_m=np.stack([observer.display[i]["atmosphere_opd_m"] for i in display_order]),
                pre_update_residual_opd_m=np.stack([observer.display[i]["pre_update_residual_opd_m"] for i in display_order]),
                held_correction_opd_m=np.stack([observer.display[i]["held_correction_opd_m"] for i in display_order]),
                psf_uncorrected=np.stack([observer.display[i]["psf_uncorrected"] for i in display_order]),
                psf_corrected=np.stack([observer.display[i]["psf_corrected"] for i in display_order]),
                pupil_mask=np.asarray(mask, dtype=bool),
                x_angle_rad=x_axis,
                y_angle_rad=y_axis,
            )
        record["observer"] = {
            "requested_fields": sorted(observer.requested_fields),
            "frames": to_jsonable(frames),
            "checks": to_jsonable(checks),
            "accumulators": {
                "corrected": to_jsonable(corrected_result.to_record()),
                "uncorrected": to_jsonable(uncorrected_result.to_record()),
                "uncorrected_feed": "StreamingLongExposure.add_opd with the frame's recorded atmosphere_opd_m (zero-DM counterfactual)",
                "corrected_feed": "StreamingLongExposure.observe with the observation's pre_update_residual_opd_m",
            },
            "sampling_metadata": to_jsonable(observer.sampling_metadata),
            "pupil_mask_sha256": identity.sha256_bytes(np.ascontiguousarray(mask).tobytes()),
            "pupil_samples": int(np.count_nonzero(mask)),
            "export_s": time.perf_counter() - export_started,
        }
    record["files"] = {
        path.name: {"bytes": path.stat().st_size, "sha256": identity.sha256_file(path)}
        for path in sorted(attempt.iterdir())
        if path.suffix == ".npz"
    }
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    record["child_peak_rss_bytes"] = int(peak if sys.platform == "darwin" else peak * 1024)
    record["child_wall_s"] = time.perf_counter() - started_wall
    write_json(attempt / "job_record.json", record)
    write_json(attempt / "status.json", {"status": "COMPLETED", "utc": utc_now(), "job_id": job_id})
    return record


# ---------------------------------------------------------------------------
# Supervision


def resource_estimate(label: str, *, measured_peak_bytes: Optional[int] = None) -> Any:
    """Audited peak-RSS estimate for one trajectory child (2x guard margin applies)."""

    from shwfs_ao.runtime.resource_guard import MIB, ResourceEstimate

    if measured_peak_bytes is None:
        # Before the pilot: interpreter + NumPy/SciPy/package imports, the
        # 156 x 156 subharmonic screen replay (16 quadrature subsamples of
        # complex128 work arrays), 40 retained display snapshots (three
        # 52 x 52 maps and two 156 x 156 images, float64), accumulators and
        # PSF temporaries, and the physical WFS frames of 25 lenslets.
        return ResourceEstimate(
            label=label,
            baseline_bytes=160 * MIB,
            components={
                "screen_quadrature_work": 24 * MIB,
                "display_snapshots": 19 * MIB,
                "psf_temporaries_and_accumulators": 8 * MIB,
                "wfs_detector_frames_and_calibration": 32 * MIB,
                "history_and_records": 4 * MIB,
            },
            largest_buffer_bytes=8 * MIB,
            notes=("pre-pilot audited estimate",),
        )
    return ResourceEstimate(
        label=label,
        baseline_bytes=int(measured_peak_bytes),
        components={"production_headroom_over_pilot_peak": 32 * MIB},
        largest_buffer_bytes=8 * MIB,
        notes=("pilot fresh-process peak RSS plus headroom for 180-frame histories and 40 display frames",),
    )


def supervise(series_dir: Path, argv: List[str], *, label: str, kind: str, job_id: Optional[str],
              estimate: Any, timeout_s: float, projected_wall_s: float, projected_bytes: int) -> Dict[str, Any]:
    from shwfs_ao.runtime import resource_guard

    series_dir = Path(series_dir)
    used = consumption(series_dir)
    entry: Dict[str, Any] = {
        "utc": utc_now(),
        "label": label,
        "kind": kind,
        "job_id": job_id,
        "consumption_before": used,
        "projected_wall_s": projected_wall_s,
        "projected_bytes": projected_bytes,
        "launched": False,
        "wall_s": 0.0,
    }
    if used["wall_s"] + projected_wall_s > protocol.WALL_TIME_CEILING_S:
        entry.update(status="REFUSED_CEILING", reason="projected wall time would exceed the 20-minute task ceiling")
        append_ledger(series_dir, entry)
        return entry
    if used["raw_bytes"] + projected_bytes > protocol.RAW_EVIDENCE_CEILING_BYTES:
        entry.update(status="REFUSED_CEILING", reason="projected raw evidence would exceed the 512 MiB ceiling")
        append_ledger(series_dir, entry)
        return entry
    decision = resource_guard.preflight(estimate)
    entry["guard_preflight"] = decision.to_record()
    if not decision.accepted:
        entry.update(status="REFUSED_GUARD", reason="; ".join(decision.reasons))
        append_ledger(series_dir, entry)
        return entry
    logs = series_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log_path = logs / f"{label}-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.log"
    result = resource_guard.run_supervised(
        argv,
        budget_bytes=decision.budget_bytes,
        timeout_s=timeout_s,
        threads=protocol.NATIVE_THREADS,
        log_path=log_path,
        cwd=str(identity.REPO_ROOT),
    )
    entry.update(
        launched=True,
        status=result.status,
        wall_s=result.wall_s,
        supervised=result.to_record(),
        log=log_path.relative_to(series_dir).as_posix(),
    )
    entry["consumption_after"] = consumption(series_dir)
    append_ledger(series_dir, entry)
    return entry
