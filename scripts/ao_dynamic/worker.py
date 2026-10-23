"""Numerical child of the computation service: run one generated experiment.

Usage (launched by ``service.py`` or ``feature_validation.py`` in its own
process group with two native threads and a wall-clock limit; never in
parallel)::

    python scripts/ao_dynamic/worker.py --job-dir DIR [--no-observer]

``DIR/request.json`` holds the accepted request (run id, seed and validated
parameters).  The child re-validates it, derives the effective configuration,
re-runs the complete-horizon admission, builds the canonical SCAO system
(calibration included), checks that the built atmosphere is the admitted one,
runs the canonical closed loop with the passive ``DynamicObserver`` and writes
``frames.bin``, ``final.bin``, ``metrics.csv``, ``evidence.npz`` and finally
``run.json`` into ``DIR``.  It prints one JSON object per line on stdout:
``started``, ``built``, throttled ``progress`` (frames done, physical time),
and ``completed`` / ``refused`` / ``failed``.

``--no-observer`` runs the identical configuration without any observer and
writes only ``control.json`` (loop-history digest): the passivity control of
the feature validation.  It is not offered by the HTTP API.
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import os
from pathlib import Path
import platform
import resource
import sys
import time
import traceback
from typing import Any, Dict, List, Optional

# Sibling modules resolve from this script's directory (Python's sys.path[0]
# when the script runs); the reused explorer modules are loaded by file.
import contract  # noqa: E402
import explorer_modules  # noqa: E402

HERE = Path(__file__).resolve().parent
EXPLORER = explorer_modules.EXPLORER
explorer_modules.load()

WORKER_FILES = ("contract.py", "physics.py", "dynamic_observer.py", "worker.py", "explorer_modules.py")
EXPLORER_FILES_USED = ("admission.py", "observer.py", "binary_scene.py", "producer.py", "identity.py", "protocol.py")
PROGRESS_INTERVAL_S = 0.25
FAULT_ENV = "AO_DYNAMIC_TEST_FAULT"


class WorkerRefusal(RuntimeError):
    """A pre-execution check refused the run (nothing was computed)."""


def emit(event: str, **fields: Any) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, allow_nan=False) + "\n")
    sys.stdout.flush()


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def file_set_identity(directory: Path, names: tuple) -> Dict[str, Any]:
    import hashlib

    digest = hashlib.sha256()
    members: Dict[str, Optional[str]] = {}
    for name in names:
        path = directory / name
        file_digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        members[name] = file_digest
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(b"<missing>" if file_digest is None else bytes.fromhex(file_digest))
    return {"sha256": digest.hexdigest(), "files": members}


def dynamic_identity() -> Dict[str, Any]:
    return {
        "worker": {"directory": "scripts/ao_dynamic", **file_set_identity(HERE, WORKER_FILES)},
        "explorer_modules_used": {"directory": "scripts/ao_explorer", **file_set_identity(EXPLORER, EXPLORER_FILES_USED)},
    }


def host_identity() -> Dict[str, Any]:
    cpu = None
    memory = None
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal"):
                memory = int(line.split()[1]) * 1024
                break
    except OSError:
        pass
    return {
        "system": platform.system(),
        "machine": platform.machine(),
        "cpu": cpu,
        "logical_cpus": os.cpu_count(),
        "physical_memory_bytes": memory,
    }


def _fault(stage: str) -> None:
    """Test-only fault injection; the service passes the variable only when started with --enable-test-faults."""

    fault = os.environ.get(FAULT_ENV, "")
    if fault == f"fail_at:{stage}":
        raise RuntimeError(f"injected test fault at {stage}")
    if fault == f"sleep_at:{stage}":
        time.sleep(3600)


def load_request(job_dir: Path) -> Dict[str, Any]:
    request = json.loads((job_dir / "request.json").read_text(encoding="utf-8"))
    params = request.get("parameters")
    if not isinstance(params, dict):
        raise WorkerRefusal("request has no parameters")
    # The service passes the effective parameters: the contract's names plus
    # the derived wind vector, which must follow from speed and direction.
    reasons = contract.validate_parameters({name: params[name] for name in params if name != "wind_m_per_s"})
    if not reasons and "wind_m_per_s" in params and params["wind_m_per_s"] != contract.effective_parameters(params)["wind_m_per_s"]:
        reasons.append("the wind vector does not follow from speed and direction")
    if reasons:
        raise WorkerRefusal("; ".join(reasons))
    if not isinstance(request.get("run_id"), str) or not request["run_id"]:
        raise WorkerRefusal("request has no run id")
    return request


def write_bytes(path: Path, data: bytes) -> Dict[str, Any]:
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_bytes(data)
    os.replace(temporary, path)
    return {"href": path.name, "bytes": len(data), "sha256": contract.sha256_bytes(data)}


def finite_or_null(values: List[float]) -> List[Optional[float]]:
    return [float(v) if v is not None and math.isfinite(float(v)) else None for v in values]


def metrics_csv(per_frame: Dict[str, List[Any]]) -> bytes:
    columns = [
        "frame_index", "time_s", "atmosphere_rms_m", "residual_rms_m", "peak_strehl_uncorrected",
        "peak_strehl_corrected", "running_average_peak_strehl_uncorrected", "running_average_peak_strehl_corrected",
        "valid_measurement_fraction", "valid_subaperture_fraction", "reconstruction_usable",
        "saturation_fraction_issued", "saturation_fraction_held", "atmosphere_sha256",
    ]
    lines = [",".join(columns)]
    for index in range(len(per_frame["frame_index"])):
        row = []
        for column in columns:
            value = per_frame[column][index]
            row.append("" if value is None else (repr(float(value)) if isinstance(value, float) else str(value)))
        lines.append(",".join(row))
    return ("\n".join(lines) + "\n").encode("utf-8")


def run(job_dir: Path, *, observer_enabled: bool = True) -> Dict[str, Any]:
    import numpy as np

    import binary_scene
    import identity
    import physics
    import producer
    from dynamic_observer import DynamicObserver

    started = time.perf_counter()
    request = load_request(job_dir)
    params = contract.effective_parameters(request["parameters"])
    emit("started", run_id=request["run_id"], seed=params["seed"], n_frames=params["n_frames"])
    _fault("start")

    config = physics.effective_config(params)
    admission_record = physics.admit(config)
    admission_sha = contract.sha256_bytes(contract.canonical_json_bytes(admission_record))
    if request.get("admission_sha256") not in (None, admission_sha):
        raise WorkerRefusal("a fresh admission evaluation differs from the one the service accepted")
    if not admission_record["admitted"]:
        raise WorkerRefusal(f"admission refused: {admission_record['reasons']}")

    from shwfs_ao.backends.native.factory import NATIVE_SCAO_COMPONENT_FACTORY
    from shwfs_ao.experiments.scao import build_scao_system, run_closed_loop

    build_started = time.perf_counter()
    system = build_scao_system(config)
    build_s = time.perf_counter() - build_started
    built_model = producer.to_jsonable(system.atmosphere.config)
    if built_model != producer.to_jsonable(admission_record["model_config"]):
        raise WorkerRefusal("the built atmosphere differs from the admitted model configuration")
    emit("built", build_s=build_s, interaction_matrix_hash=system.interaction_matrix.matrix_hash)
    _fault("built")

    n = int(params["n_frames"])
    burn = int(params["burn_in"])
    transported = contract.transported_indices(n, int(params["display_stride"]))
    geometry = NATIVE_SCAO_COMPONENT_FACTORY.build_geometry(
        telescope_diameter_m=config.telescope_diameter_m,
        pupil_pixels=config.pupil_pixels,
        lenslets_across=config.lenslets_across,
        min_fill_fraction=config.wfs.min_fill_fraction,
        central_obstruction_ratio=config.wfs.central_obstruction_ratio,
        spider_width_m=config.wfs.spider_width_m,
    )
    ideal = system.science_propagator.psf_from_opd(np.zeros(geometry.pupil_shape), contract.SCIENCE_WAVELENGTH_M)
    x_axis = np.array(ideal.x_angle_rad, dtype=float)
    y_axis = np.array(ideal.y_angle_rad, dtype=float)
    scene = binary_scene.build_scene(x_axis, y_axis, wavelength_m=contract.SCIENCE_WAVELENGTH_M,
                                     telescope_diameter_m=config.telescope_diameter_m)

    last_emit = [0.0]

    def progress(index: int, time_s: float) -> None:
        now = time.perf_counter()
        if index == n - 1 or now - last_emit[0] >= PROGRESS_INTERVAL_S:
            last_emit[0] = now
            emit("progress", frames_done=index + 1, n_frames=n, physical_time_s=time_s, wall_s=now - started)
        if index == min(3, n - 1):
            _fault("frame3")

    observer = None
    observers: tuple = ()
    if observer_enabled:
        observer = DynamicObserver(
            system.science_propagator,
            wavelength_m=contract.SCIENCE_WAVELENGTH_M,
            n_steps=n,
            burn_in=burn,
            transported=transported,
            telescope_diameter_m=config.telescope_diameter_m,
            scene_bundle=scene,
            pupil_x_m=np.asarray(geometry.x_m, dtype=float)[0, :],
            pupil_y_m=np.asarray(geometry.y_m, dtype=float)[:, 0],
            oracle_frames=sorted({0, burn, n - 1}),
            progress=progress,
        )
        observers = (observer,)
    loop_started = time.perf_counter()
    history = run_closed_loop(config, system=system, realization_index=0, observers=observers)
    loop_s = time.perf_counter() - loop_started
    travelled = float(system.atmosphere.travelled_px)
    horizon = {
        "atmosphere_travelled_px": travelled,
        "admitted_max_travel_px": admission_record["max_travel_px"],
        "equal": travelled == admission_record["max_travel_px"],
        "exceeded_travel_budget": bool(system.atmosphere.exceeded_travel_budget),
    }
    if not horizon["equal"] or horizon["exceeded_travel_budget"]:
        raise WorkerRefusal(f"runtime travel {travelled!r} px disagrees with the admitted schedule")
    arrays = producer.history_arrays(history)
    digest = producer.history_digest(history)
    common = {
        "run_id": request["run_id"],
        "config_hash": config.config_hash,
        "history_config_hash": history.config_hash,
        "history_digest": digest,
        "admission_sha256": admission_sha,
        "horizon_runtime_check": horizon,
        "build_s": build_s,
        "loop_s": loop_s,
    }
    if observer is None:
        control = {"schema": "ao-dynamic.control.v1", "observer": False, "parameters": params, **common,
                   "identities": dynamic_identity(), "child_wall_s": time.perf_counter() - started}
        (job_dir / "control.json").write_text(json.dumps(control, indent=1, allow_nan=False) + "\n", encoding="utf-8")
        emit("completed", run_id=request["run_id"], observer=False, wall_s=control["child_wall_s"])
        return control

    _fault("finish")
    export_started = time.perf_counter()
    dyn = observer.finish_dynamic()
    finish = dyn["explorer"]
    frames = observer.frames
    mask = observer.pupil_mask

    # Display: one OPD colour limit for the whole run and all three maps.
    raw_limit = max(max(values) for values in observer.display_percentile_m.values())
    limit = math.ceil(raw_limit / contract.OPD_LIMIT_QUANTUM_M) * contract.OPD_LIMIT_QUANTUM_M
    piston: Dict[str, List[float]] = {key: [] for key in ("atmosphere", "correction", "residual")}
    clipped: Dict[str, List[float]] = {key: [] for key in piston}
    for index in transported:
        kept = observer.frames_kept[index]
        for key in piston:
            values = kept["maps_m"][key][mask]
            mean = float(values.mean())
            piston[key].append(mean)
            clipped[key].append(float(np.count_nonzero(np.abs(values - mean) > limit) / values.size))

    # frames.bin and final.bin (float32, little endian, block order of the contract).
    chunks = []
    for index in transported:
        crops = observer.frames_kept[index]["crops"]
        for name, shape, _unit in contract.FRAME_BLOCKS:
            block = np.ascontiguousarray(crops[name], dtype="<f4")
            if block.shape != shape:
                raise RuntimeError(f"{name} has shape {block.shape}, expected {shape}")
            chunks.append(block.tobytes())
    frames_ref = write_bytes(job_dir / "frames.bin", b"".join(chunks))
    rows, columns = observer._crop_slices()
    final_arrays = {
        "mean_psf_uncorrected": finish["mean_psf_uncorrected"],
        "mean_psf_corrected": finish["mean_psf_corrected"],
        "final_observation_uncorrected": dyn["observations"]["uncorrected"]["image"],
        "final_observation_corrected": dyn["observations"]["corrected"]["image"],
        "scene": scene["scene"],
    }
    final_ref = write_bytes(job_dir / "final.bin", b"".join(
        np.ascontiguousarray(np.asarray(final_arrays[name], dtype=float)[rows, columns], dtype="<f4").tobytes()
        for name, _shape, _unit in contract.FINAL_BLOCKS))

    # Per-frame histories over every frame.
    saturation = [float(v) for v in arrays["saturation_fraction"]]
    per_frame = {
        "frame_index": list(range(n)),
        "time_s": [float(v) for v in frames["time_s"]],
        "atmosphere_rms_m": finite_or_null(frames["atmosphere_rms_m"]),
        "residual_rms_m": finite_or_null(frames["residual_rms_m"]),
        "peak_strehl_uncorrected": finite_or_null(frames["peak_strehl_uncorrected"]),
        "peak_strehl_corrected": finite_or_null(frames["peak_strehl_corrected"]),
        "running_average_peak_strehl_uncorrected": observer.running_strehl["uncorrected"],
        "running_average_peak_strehl_corrected": observer.running_strehl["corrected"],
        "valid_measurement_fraction": finite_or_null([float(v) for v in arrays["valid_measurement_fraction"]]),
        "valid_subaperture_fraction": finite_or_null([float(v) for v in arrays["valid_subaperture_fraction"]]),
        "reconstruction_usable": [bool(v) for v in arrays["reconstruction_usable"]],
        "saturation_fraction_issued": saturation,
        "saturation_fraction_held": [None] + saturation[:-1],
        "atmosphere_sha256": list(frames["atmosphere_sha256"]),
        "residual_sha256": list(frames["residual_sha256"]),
    }
    window = slice(burn, n)
    residual = np.asarray(frames["residual_rms_m"])
    s_unc = np.asarray(frames["peak_strehl_uncorrected"])
    s_cor = np.asarray(frames["peak_strehl_corrected"])
    accumulators = {role: finish[f"{role}_result"].to_record() for role in ("corrected", "uncorrected")}
    metrics_cor = accumulators["corrected"]["metrics"][0]
    metrics_unc = accumulators["uncorrected"]["metrics"][0]
    valid = np.asarray(arrays["valid_measurement_fraction"], dtype=float)
    usable = np.asarray(arrays["reconstruction_usable"], dtype=bool)
    sat = np.asarray(saturation)
    from shwfs_ao.experiments.detector_level import max_pole_modulus

    pole = max_pole_modulus(config.controller.gain, config.controller.leak, int(config.controller.latency_frames))
    summary = {
        "window": [burn, n],
        "sample_count": n - burn,
        "mean_atmosphere_rms_m": float(np.mean(np.asarray(frames["atmosphere_rms_m"])[window])),
        "mean_residual_rms_m": float(np.mean(residual[window])),
        "root_mean_square_residual_m": float(math.sqrt(float(np.mean(residual[window] ** 2)))),
        "mean_instantaneous_peak_strehl_uncorrected": float(np.mean(s_unc[window])),
        "mean_instantaneous_peak_strehl_corrected": float(np.mean(s_cor[window])),
        "averaged_intensity_peak_strehl_uncorrected": float(metrics_unc["peak_strehl"]),
        "averaged_intensity_peak_strehl_corrected": float(metrics_cor["peak_strehl"]),
        "frames_corrected_strehl_below_uncorrected": int(np.count_nonzero(s_cor < s_unc)),
        "mean_valid_measurement_fraction": float(np.mean(valid[window])),
        "min_valid_measurement_fraction": float(np.min(valid)),
        "frames_with_unusable_reconstruction": int(np.count_nonzero(~usable)),
        "max_dm_saturation_fraction_issued": float(np.max(sat)),
        "frames_with_dm_saturation": int(np.count_nonzero(sat > 0)),
        "controller_max_pole_modulus": pole,
        "controller_linear_model_stable": bool(pole < 1.0),
    }

    tol = {"rms_m": 1e-18 + 1e-12 * float(np.max(np.asarray(frames["atmosphere_rms_m"]))), "strehl": 1e-12, "convolution": 1e-15,
           "psf_oracle": 1e-15, "phase_rad": 1e-12, "mean_psf": 1e-15, "flux": 1e-12}
    oracle = observer.oracle
    flux_errors = [abs(item["full_flux_error"]) for role in ("uncorrected", "corrected") for item in observer.observation_flux[role]]
    checks: Dict[str, Any] = {
        "tolerances": tol,
        "history_matches_observer": {
            "times": bool(np.array_equal(np.asarray(frames["time_s"]), arrays["time_s"])),
            "atmosphere_rms": bool(np.array_equal(np.asarray(frames["atmosphere_rms_m"]), arrays["open_loop_opd_rms_m"])),
            "residual_rms": bool(np.array_equal(np.asarray(frames["residual_rms_m"]), arrays["pre_update_residual_opd_rms_m"])),
            "usable": bool(np.array_equal(np.asarray(frames["reconstruction_usable"]), arrays["reconstruction_usable"])),
            "saturation": bool(np.array_equal(np.asarray(frames["saturation_fraction"]), arrays["saturation_fraction"])),
        },
        "independent_every_frame": observer.independent,
        "oracle_frames": oracle,
        "streaming_max_abs_difference": finish["streaming_max_abs_difference"],
        "sum_consistency": dyn["sum_consistency"],
        "instantaneous_unit_flux_max_error": float(max(
            np.max(np.abs(np.asarray(frames["flux_uncorrected"]) - 1.0)), np.max(np.abs(np.asarray(frames["flux_corrected"]) - 1.0)))),
        "observation_full_flux_max_error": float(max(flux_errors)),
        "atmosphere_digests_distinct_when_wind": (len(set(frames["atmosphere_sha256"])) == n) if params["wind_speed_m_per_s"] > 0 else None,
        "horizon": horizon,
    }
    passes = [
        all(checks["history_matches_observer"].values()),
        observer.independent["atmosphere_rms_max_abs_error_m"] <= tol["rms_m"],
        observer.independent["residual_rms_max_abs_error_m"] <= tol["rms_m"],
        observer.independent["uncorrected_strehl_max_abs_error"] <= tol["strehl"],
        observer.independent["corrected_strehl_max_abs_error"] <= tol["strehl"],
        observer.independent["held_correction_identity_max_abs_m"] <= 1e-15,
        observer.independent["running_observation_linearity_max_abs"] <= tol["convolution"],
        all(item["uncorrected_psf_max_abs_difference"] <= tol["psf_oracle"] and item["corrected_psf_max_abs_difference"] <= tol["psf_oracle"]
            and item["uncorrected_strehl_abs_difference"] <= tol["strehl"] and item["corrected_strehl_abs_difference"] <= tol["strehl"]
            and item["phase_rule_max_abs_difference_rad"] <= tol["phase_rad"] for item in oracle),
        all(v <= tol["mean_psf"] for v in finish["streaming_max_abs_difference"].values()),
        all(item["dynamic_psf_sum_equals_explorer_sum_max_abs"] == 0.0 and item["final_observation_linearity_max_abs"] <= tol["convolution"]
            for item in dyn["sum_consistency"].values()),
        checks["instantaneous_unit_flux_max_error"] <= tol["flux"],
        checks["observation_full_flux_max_error"] <= tol["flux"],
        checks["atmosphere_digests_distinct_when_wind"] in (True, None),
        horizon["equal"] and not horizon["exceeded_travel_budget"],
    ]
    checks["passed"] = passes
    checks["all_passed"] = all(passes)

    # Numeric evidence (full precision, full grids).
    np.savez(
        job_dir / "evidence.npz",
        x_angle_rad=x_axis,
        y_angle_rad=y_axis,
        pupil_mask=np.asarray(mask, dtype=bool),
        ideal_psf=np.asarray(finish["ideal_psf"], dtype=float),
        mean_psf_uncorrected=finish["mean_psf_uncorrected"],
        mean_psf_corrected=finish["mean_psf_corrected"],
        final_observation_uncorrected=dyn["observations"]["uncorrected"]["image"],
        final_observation_corrected=dyn["observations"]["corrected"]["image"],
        scene=scene["scene"],
        transported_indices=np.asarray(transported, dtype=np.int64),
        **{f"history_{name}": value for name, value in arrays.items()},
    )
    evidence_path = job_dir / "evidence.npz"
    evidence_ref = {"href": "evidence.npz", "bytes": evidence_path.stat().st_size, "sha256": identity.sha256_file(evidence_path)}
    csv_ref = write_bytes(job_dir / "metrics.csv", metrics_csv(per_frame))

    step = float(x_axis[1] - x_axis[0])
    mas = 180.0 / math.pi * 3600.0e3
    flux = observer.observation_flux
    transported_record = {
        "indices": transported,
        "time_s": [per_frame["time_s"][k] for k in transported],
        "running_sample_count": [observer.frames_kept[k]["running_sample_count"] for k in transported],
        "running_window": [[burn, k + 1] if k >= burn else None for k in transported],
        "instantaneous_flux": {role: [flux[role][k] for k in transported] for role in ("uncorrected", "corrected")},
        "running_flux": {role: [observer.frames_kept[k]["running_flux"][role] for k in transported] for role in ("uncorrected", "corrected")},
        "sampling": "display/replay sampling only; every frame enters the histories, running sums and final averages",
    }
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    hashes = dict(system.component_hashes)
    record: Dict[str, Any] = {
        "schema": contract.RUN_SCHEMA,
        "api": contract.API_VERSION,
        "status": "COMPLETED",
        "run_id": request["run_id"],
        "created_utc": request.get("created_utc"),
        "completed_utc": utc_now(),
        "seed_source": request.get("seed_source"),
        "effective": {
            "parameters": params,
            "fixed": contract.FIXED,
            "physical_identity": contract.physical_identity(params),
            "system_config_hash": config.config_hash,
            "profile_parameters": producer.to_jsonable(producer.effective_parameters(config)),
        },
        "identities": {
            "api": contract.API_VERSION,
            "run_schema": contract.RUN_SCHEMA,
            "producer": dynamic_identity(),
            "producer_git": identity.git_state("scripts/ao_dynamic"),
            "core": identity.core_identity(),
            "environment": identity.environment_identity(),
            "lock": {key: value for key, value in identity.lock_verification(identity.REPO_ROOT / "constraints" / "py314.txt").items() if key != "installed"},
            "host": host_identity(),
            "atmosphere": physics.atmosphere_identity(system, history.metadata),
            "calibration": physics.calibration_identity(system),
            "component_hashes": hashes,
            "history_config_hash": history.config_hash,
            "history_digest": digest,
            "science_propagator_config_hash": system.science_propagator.config_hash,
            "scene_id": scene["record"]["scene_id"],
            "numerical_parents": {
                "instantaneous_observation": "binary_scene.observe(scene, frame PSF) for every frame, native-window crop by coordinates",
                "running_observation": "equal-weight mean of every instantaneous observation of frames [burn_in, k]",
                "final_observation": "binary_scene.observe(scene, production long-exposure mean PSF of [burn_in, n))",
                "renderer": binary_scene.RENDERER_REVISION,
            },
        },
        "admission": admission_record,
        "admission_sha256": admission_sha,
        "time": {
            "frame_rate_hz": float(config.controller.frame_rate_hz),
            "frame_period_s": 1.0 / float(config.controller.frame_rate_hz),
            "n_frames": n,
            "time_s": per_frame["time_s"],
            "time_grid_sha256": contract.sha256_bytes(np.asarray(per_frame["time_s"], dtype=float).tobytes()),
            "sampling": "one atmosphere sample per frame at its start t_k = k / 1000 s (legacy left point, n = 1)",
            "evolution": "one realization evolved by frozen flow; finite run, ends normally at the last admitted frame",
        },
        "analysis_window": {"start": burn, "stop": n, "count": n - burn, "weights": "equal", "samples_used": observer._count},
        "conventions": {
            "opd_unit": "m",
            "display_opd_unit": "nm",
            "residual_field": contract.RESIDUAL_FIELD,
            "residual_timing": "the residual the WFS measured in frame k: atmosphere(t_k) minus the correction held during frame k",
            "uncorrected_field": contract.UNCORRECTED_FIELD,
            "held_correction": contract.HELD_CORRECTION_RULE,
            "phase_rule": contract.PHASE_RULE,
            "phase_wrapping": contract.PHASE_WRAPPING,
            "phase_display_wavelengths_m": list(contract.PHASE_DISPLAY_WAVELENGTHS_M),
            "science_wavelength_m": contract.SCIENCE_WAVELENGTH_M,
            "wfs_wavelength_m": float(config.wfs_wavelength_m),
            "piston": "atmosphere OPD is piston-removed by the model; maps are shown with their pupil mean removed (recorded per frame); RMS removes the pupil mean",
            "pupil_mask": "finite OPD samples of the 52 x 52 pupil array (NaN outside)",
            "axis_layout": contract.AXIS_LAYOUT,
            "axis_directions": "+x: column index increases with angle/position; +y: row index increases with angle/position",
            "psf_normalization": contract.PSF_NORMALIZATION,
            "strehl": "peak Strehl: max(I) / max(I_ideal), I_ideal the zero-OPD image of the same propagator, wavelength and grid; tilt kept, no recentring",
            "strehl_kinds": {
                "instantaneous": "per frame",
                "mean_instantaneous": "mean of per-frame values over the window",
                "averaged_intensity": "peak Strehl of the equal-weight mean intensity (never of an averaged OPD or phase)",
            },
            "queued_latency_frames": int(config.controller.latency_frames),
            "wfs_visible_delay_frames": int(config.controller.latency_frames) + 1,
            "delay_semantics": "a reconstruction from frame k is released in the update of frame k + L and first seen by the WFS at frame k + L + 1",
            "saturation_timing": "saturation_fraction_issued[k] belongs to the command issued at the end of frame k (held from k + 1); saturation_fraction_held[k] = issued[k - 1]",
            "spatial_invariance": "one on-axis PSF assumed across the compact scene (illustrative)",
            "science_camera": "no additional science-camera noise, calibrated counts, SNR, limiting magnitude or detection significance; WFS noise is part of the AO loop",
        },
        "grids": {
            "pupil": {
                "shape_yx": list(geometry.pupil_shape),
                "spacing_xy_m": [float(v) for v in geometry.pupil_geometry.pixel_spacing_xy_m],
                "x_range_m": [float(np.min(geometry.x_m)), float(np.max(geometry.x_m))],
                "samples": int(np.count_nonzero(mask)),
                "mask_sha256": identity.sha256_bytes(np.ascontiguousarray(mask).tobytes()),
            },
            "psf": {
                "shape_yx": [int(y_axis.size), int(x_axis.size)],
                "x_angle_rad_sha256": identity.sha256_bytes(x_axis.tobytes()),
                "y_angle_rad_sha256": identity.sha256_bytes(y_axis.tobytes()),
                "step_rad": step,
                "cell_mas": step * mas,
                "x_zero_index": binary_scene.zero_index(x_axis, label="x"),
                "y_zero_index": binary_scene.zero_index(y_axis, label="y"),
                "crop_shape_yx": list(contract.CROP_SHAPE),
                "crop_slices_yx": [[rows.start, rows.stop], [columns.start, columns.stop]],
                "crop_extent_mas": [(float(x_axis[columns.start]) - step / 2) * mas, (float(x_axis[columns.stop - 1]) + step / 2) * mas],
                "native_extent_mas": [(float(x_axis[0]) - step / 2) * mas, (float(x_axis[-1]) + step / 2) * mas],
                "sampling_metadata": producer.to_jsonable(observer.sampling_metadata),
                "propagator_config_hash": system.science_propagator.config_hash,
            },
            "observation": {
                "policy": binary_scene.CONVOLUTION_POLICY,
                "full_shape_yx": dyn["observations"]["corrected"]["full_shape_yx"],
                "native_crop_slices_yx": dyn["observations"]["corrected"]["crop_slices_yx"],
                "display_crop": "the PSF display crop applied to the native-window observation",
            },
        },
        "scene": scene["record"],
        "display": {
            "opd_limit_m": limit,
            "opd_limit_rule": f"max over every frame and the three maps of the {contract.OPD_LIMIT_PERCENTILE} percentile of |OPD - pupil mean| inside the pupil, rounded up to {contract.OPD_LIMIT_QUANTUM_M * 1e9:.0f} nm; one limit for the whole run",
            "piston_removed_m": piston,
            "clipped_fraction": clipped,
            "psf_log_decades": contract.PSF_LOG_DECADES,
            "ideal_peak_cell_flux": float(np.max(finish["ideal_psf"])),
            "intensity_mapping": f"log10(I / ideal_peak_cell_flux) clipped to [-{contract.PSF_LOG_DECADES:g}, 0]; common to every PSF, observation and the scene; no per-image normalization",
            "raster": "array row index increases with +y; the browser draws +y upwards and +x to the right",
        },
        "per_frame": per_frame,
        "transported": transported_record,
        "summary": summary,
        "final_average": {
            "window": [burn, n],
            "sample_count": n - burn,
            "observation_flux": {role: {key: dyn["observations"][role][key] for key in (
                "full_flux", "expected_full_flux", "full_flux_error", "cropped_flux", "retained_fraction", "lost_fraction")} | {
                "display_crop_fraction": float(np.asarray(dyn["observations"][role]["image"])[rows, columns].sum()) / dyn["observations"][role]["full_flux"]}
                for role in ("uncorrected", "corrected")},
            "accumulators": producer.to_jsonable(accumulators),
            "sampling": "equal-weight mean of every frame-start instantaneous intensity in the window; not a finite-shutter integration",
        },
        "arrays": {
            "frames": {**frames_ref, "dtype": "<f4", "order": "transported frame, then block, row-major (y, x)",
                       "blocks": [{"name": name, "shape": list(shape), "unit": unit} for name, shape, unit in contract.FRAME_BLOCKS]},
            "final": {**final_ref, "dtype": "<f4", "order": "block, row-major (y, x)",
                      "blocks": [{"name": name, "shape": list(shape), "unit": unit} for name, shape, unit in contract.FINAL_BLOCKS]},
            "metrics_csv": csv_ref,
            "evidence_npz": evidence_ref,
        },
        "checks": producer.to_jsonable(checks),
        "resources": {
            "build_s": build_s,
            "loop_s": loop_s,
            "export_s": time.perf_counter() - export_started,
            "child_wall_s": time.perf_counter() - started,
            "child_peak_rss_bytes": int(peak if sys.platform == "darwin" else peak * 1024),
            "native_threads": {name: os.environ.get(name) for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")},
        },
        "limitations": [
            "One finite realization per run; no ensemble, confidence interval or convergence claim.",
            "Computation finishes before replay; the 1 kHz loop is not simulated in real time.",
            "Averages are equal-weight means of frame-start snapshots, not finite-shutter exposures.",
            "One spatially invariant on-axis PSF is assumed across the binary (illustrative).",
            "No science-camera noise, calibrated counts, SNR or detection significance.",
        ],
    }
    problems = contract.validate_run_record(record, file_sizes={"frames.bin": frames_ref["bytes"], "final.bin": final_ref["bytes"]})
    if problems:
        raise RuntimeError("the run record breaks the contract: " + "; ".join(problems))
    data = (json.dumps(record, indent=1, allow_nan=False) + "\n").encode("utf-8")
    run_ref = write_bytes(job_dir / "run.json", data)
    if os.environ.get(FAULT_ENV) == "tamper_run_json":
        # Test-only: a coherent-looking record with another science wavelength.
        record["conventions"]["science_wavelength_m"] = 2.2e-6
        write_bytes(job_dir / "run.json", (json.dumps(record, indent=1, allow_nan=False) + "\n").encode("utf-8"))
    emit("completed", run_id=request["run_id"], run_json_sha256=run_ref["sha256"], run_json_bytes=run_ref["bytes"],
         all_checks_passed=checks["all_passed"], wall_s=time.perf_counter() - started)
    return record


def watch_parent(interval_s: float = 0.5) -> None:
    """Exit if the supervising process disappears (re-parenting), so no worker runs unowned."""

    import threading

    parent = os.getppid()

    def watch() -> None:
        while True:
            time.sleep(interval_s)
            if os.getppid() != parent:
                os._exit(70)

    threading.Thread(target=watch, name="parent-watch", daemon=True).start()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--job-dir", type=Path, required=True)
    parser.add_argument("--no-observer", action="store_true", help="passivity control: run without any observer")
    arguments = parser.parse_args(argv)
    watch_parent()
    try:
        run(arguments.job_dir, observer_enabled=not arguments.no_observer)
    except WorkerRefusal as exc:
        emit("refused", reason=str(exc))
        return 3
    except Exception as exc:  # noqa: BLE001 - the child reports, the supervisor records
        traceback.print_exc(file=sys.stderr)
        emit("failed", reason=f"{type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
