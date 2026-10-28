"""One-second explorer dataset: 1000 frames at 1 kHz on a 624 x 624 screen.

This is a separate producer for a new dataset.  It reuses, unchanged, the
historical explorer modules (``protocol`` for the eight cases, ``producer``
for the effective configuration, ``admission`` for the request schedule and
the support rule, ``observer`` for the per-frame records and the mean PSFs),
so the producer identity of ``series-2m180-b3e1c66`` is untouched.  What
differs from that series:

* ``n_steps = 1000`` (frames 0..999 at the recorded 1 kHz, sample times
  0.000..0.999 s, physical interval [0.000, 1.000) s);
* the ``native_frozen_flow_v2`` screen is generated at 624 x 624 through the
  explicit construction option ``FrozenFlowScreenOptions(screen_grid_size=624)``
  instead of the default 3 x 52 = 156.  The enlarged screen is a different
  realization of the same seed; nothing here claims that its first 180
  frames reproduce the historical trajectory;
* every frame's atmosphere, pre-update residual and held-correction pupil
  maps (52 x 52) and its uncorrected/corrected PSF pair (156 x 156) are
  archived as float64 ``.npy`` stacks, written frame by frame so no stack is
  held in memory;
* the predeclared startup exclusion is frames 0..199: the mean PSFs are the
  production accumulators' equal-weight means over the half-open window
  [200, 1000), exactly 800 frames.

Commands (run serially; the supervisor launches one child per case)::

    python scripts/ao_explorer/long_series.py plan --output-root DIR --original-series DIR
    python scripts/ao_explorer/long_series.py supervise --series-dir DIR
    python scripts/ao_explorer/long_series.py run-case --series-dir DIR --case CASE   (child)

``plan`` writes the machine-readable plan (configurations, admissions,
identities, frame contract, analysis window, block-summary definition)
before any trajectory exists; it is never overwritten.  Nothing here runs a
pilot, a control, a seed-sensitivity job or a benchmark.  The block
summaries, observations and browser assets are derived separately
(``long_export.py``), so they never change this producer's identity.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import datetime
import hashlib
import io
import json
import math
import os
from pathlib import Path
import resource
import sys
import time
import traceback
from typing import Any, Dict, List, Optional

import identity
import producer
import protocol


PLAN_SCHEMA = "ao-explorer.long-series-plan.v1"
CASE_RECORD_SCHEMA = "ao-explorer.long-case-record.v1"
ADMISSION_SCHEMA = "ao-explorer.long-horizon-admission.v1"
PLAN_NAME = "plan.json"
LEDGER_NAME = "ledger.jsonl"

N_STEPS = 1000
STARTUP_EXCLUSION_FRAMES = 200
SCREEN_GRID_SIZE = 624
BLOCK_FRAMES = 100
ROOT_SEED = protocol.ROOT_SEED
REALIZATION_INDEX = protocol.REALIZATION_INDEX
SCIENCE_WAVELENGTH_M = protocol.SCIENCE_WAVELENGTH_M
NATIVE_THREADS = protocol.NATIVE_THREADS
CASE_ORDER = (
    "baseline",
    "weaker-turbulence",
    "stronger-turbulence",
    "lower-gain",
    "higher-gain",
    "brighter-guide",
    "fainter-guide",
    "longer-delay",
)

# Ceilings of this separately identified long run (the historical 20-minute,
# 512 MiB and 120 s child ceilings belong to the 180-frame series).
CHILD_TIMEOUT_S = 3.0 * 3600.0
WALL_TIME_CEILING_S = 12.0 * 3600.0
STORAGE_CEILING_BYTES = 12 * 1024 ** 3
MIN_FREE_DISK_BYTES = 12 * 1024 ** 3

# Archived per-frame stacks: name -> (trailing shape key, observer snapshot field).
FRAME_STACKS = (
    ("atmosphere_opd_m", "pupil", "atmosphere_opd_m"),
    ("pre_update_residual_opd_m", "pupil", "pre_update_residual_opd_m"),
    ("held_correction_opd_m", "pupil", "held_correction_opd_m"),
    ("psf_uncorrected", "image", "psf_uncorrected"),
    ("psf_corrected", "image", "psf_corrected"),
)

# Files whose content is this dataset's producer: this module and the
# unchanged historical modules it imports, plus the core files that carry the
# screen option.  The whole core package digest is recorded separately.
PRODUCER_MODULES = ("long_series.py",) + identity.PRODUCER_FILES
CORE_SOURCE_FILES = (
    "src/shwfs_ao/experiments/scao.py",
    "src/shwfs_ao/backends/native/factory.py",
    "src/shwfs_ao/backends/native/atmosphere.py",
    "src/shwfs_ao/control/loop.py",
    "src/shwfs_ao/science/long_exposure.py",
)


class LongSeriesError(RuntimeError):
    """Raised when a plan, identity, admission or archive check refuses."""


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def sha256_file_chunked(path: Path, chunk_bytes: int = 16 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            block = handle.read(chunk_bytes)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Identities


def production_identity() -> Dict[str, Any]:
    """Digest of the producer files and the imported core package (no Git state)."""

    modules = identity.file_set_identity(PRODUCER_MODULES)
    core = identity.core_identity()
    sources = identity.source_file_digests(CORE_SOURCE_FILES)
    lock = identity.lock_verification()
    material = {
        "producer_modules": modules["files"],
        "core_package_sha256": core["package_sha256"],
        "core_source_files": sources,
        "lock_sha256": lock["lock_sha256"],
        "environment": identity.environment_identity(),
    }
    return {
        "sha256": identity.sha256_bytes(identity.canonical_json_bytes(material)),
        "material": material,
        "lock_verified": lock["verified"],
        "lock_violations": lock["violations"],
    }


def series_id_for(production: Dict[str, Any]) -> str:
    return f"series-2m1000-s{SCREEN_GRID_SIZE}-{production['sha256'][:12]}"


def check_identity(plan: Dict[str, Any]) -> Dict[str, Any]:
    current = production_identity()
    if current["sha256"] != plan["identities"]["production"]["sha256"]:
        raise LongSeriesError("producer files, core package or environment differ from the plan.")
    if not current["lock_verified"]:
        raise LongSeriesError(f"environment is not the verified constraint lock: {current['lock_violations']}")
    return current


# ---------------------------------------------------------------------------
# Configuration, screen and admission


def case_job(case_id: str) -> Dict[str, Any]:
    return {
        "job_id": f"case-{case_id}",
        "role": "production",
        "case_id": case_id,
        "n_steps": N_STEPS,
        "burn_in": STARTUP_EXCLUSION_FRAMES,
        "root_seed": ROOT_SEED,
        "observer": True,
    }


def screen_options() -> Any:
    from shwfs_ao.experiments.scao import FrozenFlowScreenOptions

    return FrozenFlowScreenOptions(screen_grid_size=SCREEN_GRID_SIZE)


def native_geometry(config: Any) -> Any:
    from shwfs_ao.backends.native.factory import NATIVE_SCAO_COMPONENT_FACTORY

    return NATIVE_SCAO_COMPONENT_FACTORY.build_geometry(
        telescope_diameter_m=config.telescope_diameter_m,
        pupil_pixels=config.pupil_pixels,
        lenslets_across=config.lenslets_across,
        min_fill_fraction=config.wfs.min_fill_fraction,
        central_obstruction_ratio=config.wfs.central_obstruction_ratio,
        spider_width_m=config.wfs.spider_width_m,
    )


def admit(config: Any) -> Dict[str, Any]:
    """Complete-horizon admission on the explicit 624 x 624 screen (no screen is generated)."""

    import admission
    import numpy as np
    from shwfs_ao.experiments._component_configs import exposure_keywords

    if config.backend != "native" or config.atmosphere_model != "native_frozen_flow_v2":
        raise LongSeriesError(f"unsupported atmosphere {config.atmosphere_model!r} on {config.backend!r}")
    keywords = exposure_keywords(config, None)
    schedule = admission.request_schedule(config.controller.n_steps, config.controller.frame_rate_hz, keywords)
    times = schedule.pop("times_s")
    times_array = np.asarray(times, dtype=float)
    geometry = native_geometry(config)
    spacing = admission._pupil_spacing(geometry)
    default_model = admission.model_atmosphere_config(config, geometry)
    model = replace(default_model, screen_grid_size=SCREEN_GRID_SIZE)
    budget = float(model.travel_budget_px)
    wind = tuple(float(value) for value in model.wind_m_per_s)
    speed = math.hypot(*wind)
    evaluation = admission.evaluate_requests(times, wind_m_per_s=wind, delta_m=model.delta_m, budget_px=budget)
    frame_period = 1.0 / float(config.controller.frame_rate_hz)
    interval_end = int(config.controller.n_steps) * frame_period
    supported_s = budget * float(model.delta_m) / speed if speed > 0.0 else math.inf
    reasons: List[str] = []
    if not spacing["coordinates_uniform"] or not spacing["factory_matches_coordinates"]:
        reasons.append("pupil coordinates are not uniform or disagree with the factory spacing")
    reasons.extend(evaluation["invalid_requests"])
    if evaluation["first_refused_request"] is not None:
        refused = evaluation["first_refused_request"]
        reasons.append(
            f"request {refused['request_index']} at t={refused['time_s']!r} s travels "
            f"{refused['travel_px']!r} px > budget {budget!r} px"
        )
    if interval_end > supported_s:
        reasons.append(f"physical interval end {interval_end!r} s exceeds the supported {supported_s!r} s")
    model_record = asdict(model)
    return {
        "schema": ADMISSION_SCHEMA,
        "config_hash": config.config_hash,
        "atmosphere_model": config.atmosphere_model,
        "backend": config.backend,
        "schedule": schedule,
        "request_count": len(times),
        "request_times_sha256": identity.sha256_bytes(times_array.tobytes()),
        "first_request_s": float(times_array[0]),
        "last_request_s": float(times_array[-1]),
        "pupil_shape": list(geometry.pupil_shape),
        "pupil_spacing": spacing,
        "default_screen_px": int(default_model.generated_grid_size),
        "model_config": model_record,
        "model_config_sha256": identity.sha256_bytes(identity.canonical_json_bytes(model_record)),
        "generated_screen_px": int(model.generated_grid_size),
        "screen_option": {"screen_grid_size": SCREEN_GRID_SIZE},
        "travel_budget_px": budget,
        "travel_budget_rule": "(generated_screen_px - pupil_array_px) / 2; refuse hypot(vx t/delta, vy t/delta) > budget",
        "wind_m_per_s": list(wind),
        "wind_speed_m_per_s": speed,
        "delta_m": float(model.delta_m),
        "supported_travel_duration_s": supported_s,
        "supported_travel_rule": "travel_budget_px * delta_m / wind_speed (from the pupil spacing, screen size and wind)",
        "frame_period_s": frame_period,
        "physical_interval_s": [0.0, interval_end],
        "max_travel_px": evaluation["max_travel_px"],
        "time_of_max_travel_s": evaluation["time_of_max_travel_s"],
        "margin_px": budget - evaluation["max_travel_px"],
        "margin_s": supported_s - evaluation["time_of_max_travel_s"],
        "first_refused_request": evaluation["first_refused_request"],
        "admitted": not reasons,
        "reasons": reasons,
        "bound_sources_sha256": identity.source_file_digests(admission.BOUND_SOURCES),
    }


def original_case_binding(original_plan: Dict[str, Any], case_id: str, config: Any) -> Dict[str, Any]:
    """Bind a 1000-frame case to the recorded 180-frame case it extends."""

    recorded = producer.plan_job(original_plan, f"case-{case_id}")
    rebuilt = producer.job_config(recorded)
    if rebuilt.config_hash != recorded["config_hash"]:
        raise LongSeriesError(f"{case_id}: the recorded 180-frame configuration no longer rebuilds to its hash.")
    if recorded["case_override"] != protocol.case_by_id(case_id)["override"]:
        raise LongSeriesError(f"{case_id}: the case override differs from the recorded series.")
    recorded_parameters = dict(recorded["effective_parameters"])
    parameters = producer.to_jsonable(producer.effective_parameters(config))
    differences = sorted(key for key in set(parameters) | set(recorded_parameters) if parameters.get(key) != recorded_parameters.get(key))
    if differences != ["n_steps"]:
        raise LongSeriesError(f"{case_id}: effective parameters differ beyond n_steps: {differences}")
    expected = replace(rebuilt, controller=replace(rebuilt.controller, n_steps=N_STEPS))
    if expected.config_hash != config.config_hash:
        raise LongSeriesError(f"{case_id}: the 1000-frame configuration is not the recorded one with n_steps=1000.")
    return {
        "recorded_job_id": recorded["job_id"],
        "recorded_config_hash": recorded["config_hash"],
        "recorded_n_steps": recorded["n_steps"],
        "recorded_burn_in": recorded["burn_in"],
        "recorded_root_seed": recorded["root_seed"],
        "case_override": recorded["case_override"],
        "differences": {"n_steps": [recorded_parameters["n_steps"], parameters["n_steps"]]},
        "rule": "the recorded configuration with controller.n_steps replaced by 1000; every other effective parameter is equal",
    }


# ---------------------------------------------------------------------------
# Plan


def make_plan(output_root: Path, original_series: Path) -> Path:
    original_series = Path(original_series).resolve()
    original_plan_path = original_series / producer.FROZEN_PLAN_NAME
    original_plan = producer.read_json(original_plan_path)
    if original_plan.get("state") != "FROZEN" or original_plan.get("series_id") != "series-2m180-b3e1c66":
        raise LongSeriesError("the original series plan is not the frozen series-2m180-b3e1c66 plan.")
    production = production_identity()
    if not production["lock_verified"]:
        raise LongSeriesError(f"environment is not the verified constraint lock: {production['lock_violations']}")
    series_id = series_id_for(production)
    series_dir = Path(output_root) / series_id
    if (series_dir / PLAN_NAME).exists():
        raise LongSeriesError(f"{series_dir / PLAN_NAME} exists; a plan is never overwritten.")
    cases = []
    for case_id in CASE_ORDER:
        job = case_job(case_id)
        config = producer.job_config(job)
        record = admit(config)
        cases.append(
            {
                **job,
                "label": protocol.case_by_id(case_id)["label"],
                "config_hash": config.config_hash,
                "profile": f"{protocol.PROFILE_NAME}@{protocol.PROFILE_VERSION}",
                "case_override": protocol.case_by_id(case_id)["override"],
                "effective_parameters": producer.to_jsonable(producer.effective_parameters(config)),
                "original_binding": original_case_binding(original_plan, case_id, config),
                "admission": record,
                "admission_sha256": identity.sha256_bytes(identity.canonical_json_bytes(record)),
            }
        )
    baseline_admission = cases[0]["admission"]
    plan = {
        "schema": PLAN_SCHEMA,
        "series_id": series_id,
        "created_utc": utc_now(),
        "state": "PLANNED_BEFORE_PRODUCTION",
        "description": "1000-frame (1.000 s) explorer trajectories of the eight production cases on a 624 x 624 native_frozen_flow_v2 screen",
        "new_dataset_notice": (
            "The 624 x 624 screen is a different realization of root seed 1 than the historical 156 x 156 screen; "
            "no frame of this dataset reproduces series-2m180-b3e1c66."
        ),
        "original_series": {
            "series_id": original_plan["series_id"],
            "plan": producer.FROZEN_PLAN_NAME,
            "plan_sha256": identity.sha256_file(original_plan_path),
            "location": "ao-explorer-v1 workspace outputs/ao_explorer_v1/series-2m180-b3e1c66 (read only)",
        },
        "profile": {"name": protocol.PROFILE_NAME, "version": protocol.PROFILE_VERSION},
        "frame_contract": {
            "n_steps": N_STEPS,
            "frame_rate_hz": 1000.0,
            "frame_period_s": 0.001,
            "frame_indices": [0, N_STEPS - 1],
            "sample_times_s": "k / 1000 for k = 0..999 (0.000 .. 0.999 s)",
            "physical_interval_s": [0.0, 1.0],
            "physical_interval_rule": "half-open [0.000, 1.000) s: N frames of one 1 ms period each",
            "root_seed": ROOT_SEED,
            "realization_index": REALIZATION_INDEX,
            "science_wavelength_m": SCIENCE_WAVELENGTH_M,
            "retained_per_frame": [name for name, _, _ in FRAME_STACKS],
            "archive_dtype": "float64",
            "uncorrected_definition": "the frame's recorded atmosphere with zero DM (StreamingLongExposure.add_opd feed)",
            "corrected_definition": "the frame's pre-update residual, atmosphere minus the held correction (StreamingLongExposure.observe feed)",
        },
        "screen": {
            "atmosphere_model": "native_frozen_flow_v2",
            "construction_option": "shwfs_ao.experiments.scao.FrozenFlowScreenOptions(screen_grid_size=624)",
            "historical_default_px": baseline_admission["default_screen_px"],
            "generated_screen_px": baseline_admission["generated_screen_px"],
            "pupil_px": baseline_admission["pupil_shape"][0],
            "delta_m": baseline_admission["delta_m"],
            "wind_m_per_s": baseline_admission["wind_m_per_s"],
            "travel_budget_px": baseline_admission["travel_budget_px"],
            "supported_travel_duration_s": baseline_admission["supported_travel_duration_s"],
            "max_requested_travel_px": baseline_admission["max_travel_px"],
            "margin_px": baseline_admission["margin_px"],
            "archived_screen": "none: only the 52 x 52 pupil windows are kept per frame",
        },
        "analysis_window": {
            "startup_exclusion_frames": [0, STARTUP_EXCLUSION_FRAMES - 1],
            "start": STARTUP_EXCLUSION_FRAMES,
            "stop": N_STEPS,
            "count": N_STEPS - STARTUP_EXCLUSION_FRAMES,
            "interval": "half-open frame indices [200, 1000)",
            "weights": "equal",
            "means": "mean_psf_uncorrected / mean_psf_corrected from the production StreamingLongExposure accumulators",
            "declared": "predeclared in this plan before any trajectory; a chosen analysis window, not a convergence result",
        },
        "block_summaries": {
            "block_frames": BLOCK_FRAMES,
            "blocks": [[start, start + BLOCK_FRAMES] for start in range(0, N_STEPS, BLOCK_FRAMES)],
            "metrics": [
                "pre-update residual pupil RMS (nm OPD)",
                "instantaneous peak Strehl, corrected and uncorrected",
                "actuator saturation fraction",
            ],
            "saturation_definition": (
                "per frame, the fraction of DM actuators whose requested command magnitude exceeds the 1 um OPD "
                "stroke limit and is clipped (dm.model: mean(|requested| > stroke_limit_opd_m))"
            ),
            "statistics": "per non-overlapping 100-frame (100 ms) block: mean, standard deviation, min, max; saturation also the share of frames with any clipped actuator",
            "declared": "descriptive only; no stationarity test and no window tuning",
        },
        "cases": cases,
        "all_cases_admitted": all(case["admission"]["admitted"] for case in cases),
        "ceilings": {
            "child_timeout_s": CHILD_TIMEOUT_S,
            "wall_time_s": WALL_TIME_CEILING_S,
            "storage_bytes": STORAGE_CEILING_BYTES,
            "min_free_disk_bytes": MIN_FREE_DISK_BYTES,
            "native_threads": NATIVE_THREADS,
            "execution": "one child per case, serially; the resource guard's memory enforcement stays at its configured default",
        },
        "identities": {
            "production": production,
            "core": identity.core_identity(),
            "git_scripts": identity.git_state("scripts/ao_explorer"),
            "environment": identity.environment_identity(),
            "host": identity.host_identity(),
        },
    }
    if not plan["all_cases_admitted"]:
        raise LongSeriesError("a case is refused by the screen-coverage admission: " + "; ".join(
            reason for case in cases for reason in case["admission"]["reasons"]))
    series_dir.mkdir(parents=True, exist_ok=True)
    producer.write_json(series_dir / PLAN_NAME, plan)
    return series_dir


def load_plan(series_dir: Path) -> Dict[str, Any]:
    path = Path(series_dir) / PLAN_NAME
    if not path.exists():
        raise LongSeriesError(f"missing plan {path}")
    return producer.read_json(path)


def plan_case(plan: Dict[str, Any], case_id: str) -> Dict[str, Any]:
    for case in plan["cases"]:
        if case["case_id"] == case_id:
            return case
    raise LongSeriesError(f"case {case_id!r} is not in the plan")


# ---------------------------------------------------------------------------
# Streamed archives


class NpyStreamWriter:
    """Write one C-ordered float64 ``.npy`` stack frame by frame, hashing as it goes."""

    def __init__(self, path: Path, shape: tuple) -> None:
        import numpy as np

        self.path = Path(path)
        self.shape = tuple(int(value) for value in shape)
        self.frame_shape = self.shape[1:]
        self.count = 0
        header = io.BytesIO()
        np.lib.format.write_array_header_1_0(
            header, {"descr": np.lib.format.dtype_to_descr(np.dtype("<f8")), "fortran_order": False, "shape": self.shape}
        )
        self._digest = hashlib.sha256(header.getvalue())
        self._partial = self.path.with_suffix(self.path.suffix + ".partial")
        self._handle = self._partial.open("xb")
        self._handle.write(header.getvalue())

    def write(self, index: int, frame: Any) -> None:
        import numpy as np

        if index != self.count:
            raise LongSeriesError(f"{self.path.name}: frame {index} arrived, expected {self.count}")
        array = np.ascontiguousarray(frame, dtype="<f8")
        if array.shape != self.frame_shape:
            raise LongSeriesError(f"{self.path.name}: frame shape {array.shape} != {self.frame_shape}")
        data = array.tobytes()
        self._handle.write(data)
        self._digest.update(data)
        self.count += 1

    def close(self) -> Dict[str, Any]:
        self._handle.close()
        if self.count != self.shape[0]:
            raise LongSeriesError(f"{self.path.name}: wrote {self.count} of {self.shape[0]} frames")
        os.replace(self._partial, self.path)
        return {"shape": list(self.shape), "dtype": "float64", "bytes": self.path.stat().st_size, "sha256": self._digest.hexdigest()}


class ArchiveObserver:
    """Wrap ``ExplorerObserver``: stream each frame's snapshot to disk, check it, drop it."""

    def __init__(self, inner: Any, frames_dir: Path, *, n_steps: int, pupil_shape: tuple, image_shape: tuple) -> None:
        self.inner = inner
        self.requested_fields = inner.requested_fields
        shapes = {"pupil": tuple(pupil_shape), "image": tuple(image_shape)}
        self.writers = {
            name: NpyStreamWriter(Path(frames_dir) / f"{name}.npy", (n_steps,) + shapes[kind])
            for name, kind, _ in FRAME_STACKS
        }
        self.max_errors = {
            "atmosphere_rms_abs_error_m": 0.0,
            "residual_rms_abs_error_m": 0.0,
            "uncorrected_strehl_abs_error": 0.0,
            "corrected_strehl_abs_error": 0.0,
            "held_correction_identity_max_abs_m": 0.0,
        }
        self.within_tolerance = True
        self.started = time.perf_counter()

    def observe(self, observation: Any) -> None:
        import numpy as np
        from observer import independent_peak_strehl, independent_rms

        self.inner.observe(observation)
        index = int(observation.frame_index)
        snapshot = self.inner.all_frames.pop(index)
        frames = self.inner.frames
        mask = self.inner.pupil_mask
        ideal = np.asarray(self.inner.ideal_psf.intensity, dtype=float)
        atm_rms = frames["atmosphere_rms_m"][index]
        res_rms = frames["residual_rms_m"][index]
        errors = {
            "atmosphere_rms_abs_error_m": abs(independent_rms(snapshot["atmosphere_opd_m"], mask) - atm_rms),
            "residual_rms_abs_error_m": abs(independent_rms(snapshot["pre_update_residual_opd_m"], mask) - res_rms),
            "uncorrected_strehl_abs_error": abs(independent_peak_strehl(snapshot["psf_uncorrected"], ideal) - frames["peak_strehl_uncorrected"][index]),
            "corrected_strehl_abs_error": abs(independent_peak_strehl(snapshot["psf_corrected"], ideal) - frames["peak_strehl_corrected"][index]),
            "held_correction_identity_max_abs_m": float(
                np.nanmax(np.abs(snapshot["atmosphere_opd_m"] - snapshot["held_correction_opd_m"] - snapshot["pre_update_residual_opd_m"]))
            ),
        }
        rms_tol = protocol.TOLERANCES["rms_m"]
        strehl_tol = protocol.TOLERANCES["strehl"]["atol"]
        self.within_tolerance = self.within_tolerance and (
            errors["atmosphere_rms_abs_error_m"] <= rms_tol["atol"] + rms_tol["rtol"] * atm_rms
            and errors["residual_rms_abs_error_m"] <= rms_tol["atol"] + rms_tol["rtol"] * res_rms
            and errors["uncorrected_strehl_abs_error"] <= strehl_tol
            and errors["corrected_strehl_abs_error"] <= strehl_tol
        )
        for key, value in errors.items():
            self.max_errors[key] = max(self.max_errors[key], float(value))
        for name, _, field in FRAME_STACKS:
            self.writers[name].write(index, snapshot[field])
        del snapshot
        if (index + 1) % 100 == 0:
            elapsed = time.perf_counter() - self.started
            print(json.dumps({"progress": index + 1, "elapsed_s": round(elapsed, 1)}), flush=True)

    def close(self) -> Dict[str, Any]:
        return {name: writer.close() for name, writer in self.writers.items()}


def archive_means(frames_dir: Path, start: int, stop: int) -> Dict[str, Any]:
    """Sequential float64 sums of the archived stacks over [start, stop), read back in chunks."""

    import numpy as np

    means = {}
    for name in ("psf_uncorrected", "psf_corrected"):
        stack = np.load(Path(frames_dir) / f"{name}.npy", mmap_mode="r")
        total = np.zeros(stack.shape[1:], dtype=float)
        for index in range(start, stop):
            total += np.asarray(stack[index], dtype=float)
        means[name] = total / (stop - start)
        del stack
    return means


# ---------------------------------------------------------------------------
# Child


def next_attempt_dir(series_dir: Path, case_id: str) -> Path:
    root = Path(series_dir) / "cases" / case_id
    root.mkdir(parents=True, exist_ok=True)
    number = 1 + sum(1 for path in root.iterdir() if path.is_dir() and path.name.startswith("attempt-"))
    return root / f"attempt-{number:02d}"


def completed_attempt(series_dir: Path, case_id: str) -> Optional[Path]:
    root = Path(series_dir) / "cases" / case_id
    if not root.exists():
        return None
    for path in sorted(root.iterdir()):
        status = path / "status.json"
        if status.exists() and producer.read_json(status).get("status") == "COMPLETED":
            return path
    return None


def run_case(series_dir: Path, case_id: str) -> Dict[str, Any]:
    import numpy as np

    from observer import ExplorerObserver

    started_wall = time.perf_counter()
    series_dir = Path(series_dir)
    plan = load_plan(series_dir)
    case = plan_case(plan, case_id)
    if completed_attempt(series_dir, case_id) is not None:
        raise LongSeriesError(f"{case_id} already has a completed attempt; it is never rerun.")
    current = check_identity(plan)
    config = producer.job_config(case)
    if config.config_hash != case["config_hash"]:
        raise LongSeriesError("effective configuration hash differs from the plan.")
    fresh = admit(config)
    fresh_sha = identity.sha256_bytes(identity.canonical_json_bytes(fresh))
    if fresh_sha != case["admission_sha256"]:
        raise LongSeriesError("a fresh admission evaluation differs from the plan's record.")
    if not fresh["admitted"]:
        raise LongSeriesError(f"admission refused: {fresh['reasons']}")

    attempt = next_attempt_dir(series_dir, case_id)
    attempt.mkdir(parents=False, exist_ok=False)
    producer.write_json(attempt / "status.json", {"status": "STARTED", "utc": utc_now(), "case_id": case_id})
    frames_dir = attempt / "frames"
    frames_dir.mkdir()

    from shwfs_ao.experiments.scao import build_scao_system, run_closed_loop

    build_started = time.perf_counter()
    system = build_scao_system(config, atmosphere_options=screen_options())
    build_s = time.perf_counter() - build_started
    built = system.atmosphere.config
    built_record = producer.to_jsonable(asdict(built))
    if built_record != producer.to_jsonable(fresh["model_config"]):
        raise LongSeriesError("the built atmosphere differs from the admitted model configuration.")
    if (built.generated_grid_size, float(built.travel_budget_px)) != (SCREEN_GRID_SIZE, fresh["travel_budget_px"]):
        raise LongSeriesError("the built screen geometry differs from the admitted one.")
    if system.atmosphere_options is None or system.atmosphere_options.to_record() != {"screen_grid_size": SCREEN_GRID_SIZE}:
        raise LongSeriesError("the built system does not record the 624 x 624 screen option.")
    atmosphere_metadata = producer.to_jsonable(dict(system.atmosphere.metadata))
    if atmosphere_metadata.get("screen_grid_size") != SCREEN_GRID_SIZE:
        raise LongSeriesError("the atmosphere metadata does not describe the 624 x 624 screen.")

    inner = ExplorerObserver(
        system.science_propagator,
        wavelength_m=SCIENCE_WAVELENGTH_M,
        n_steps=N_STEPS,
        burn_in=STARTUP_EXCLUSION_FRAMES,
        display_indices=[],
        telescope_diameter_m=config.telescope_diameter_m,
        retain_all_frames=True,
    )
    grid = producer.native_science_grid(config)
    image_shape = (int(grid["y_angle_rad"].size), int(grid["x_angle_rad"].size))
    pupil_shape = tuple(fresh["pupil_shape"])
    archive = ArchiveObserver(inner, frames_dir, n_steps=N_STEPS, pupil_shape=pupil_shape, image_shape=image_shape)
    loop_started = time.perf_counter()
    history = run_closed_loop(config, system=system, realization_index=REALIZATION_INDEX, observers=(archive,))
    loop_s = time.perf_counter() - loop_started
    stacks = archive.close()

    travelled = float(system.atmosphere.travelled_px)
    horizon_check = {
        "atmosphere_travelled_px": travelled,
        "admitted_max_travel_px": fresh["max_travel_px"],
        "equal": travelled == fresh["max_travel_px"],
        "exceeded_travel_budget": bool(system.atmosphere.exceeded_travel_budget),
        "travel_budget_px": float(built.travel_budget_px),
    }
    if not horizon_check["equal"] or horizon_check["exceeded_travel_budget"]:
        raise LongSeriesError(f"runtime travel {travelled!r} px disagrees with the admitted schedule.")

    export_started = time.perf_counter()
    arrays = producer.history_arrays(history)
    np.savez(attempt / "history.npz", **arrays)
    finish = inner.finish()
    frames = inner.frames
    mask = inner.pupil_mask
    np.save(frames_dir / "frame_index.npy", np.asarray(frames["frame_index"], dtype=np.int64))
    np.save(frames_dir / "time_s.npy", np.asarray(frames["time_s"], dtype=float))
    checks: Dict[str, Any] = {
        "atmosphere_rms_matches_history": bool(np.array_equal(np.asarray(frames["atmosphere_rms_m"]), arrays["open_loop_opd_rms_m"])),
        "residual_rms_matches_history": bool(np.array_equal(np.asarray(frames["residual_rms_m"]), arrays["pre_update_residual_opd_rms_m"])),
        "times_match_history": bool(np.array_equal(np.asarray(frames["time_s"]), arrays["time_s"])),
        "times_are_k_over_1000": bool(np.array_equal(np.asarray(frames["time_s"]), np.arange(N_STEPS, dtype=float) / 1000.0)),
        "frame_indices_complete": frames["frame_index"] == list(range(N_STEPS)),
        "usable_matches_history": bool(np.array_equal(np.asarray(frames["reconstruction_usable"]), arrays["reconstruction_usable"])),
        "saturation_matches_history": bool(np.array_equal(np.asarray(frames["saturation_fraction"]), arrays["saturation_fraction"])),
        "per_frame_independent_reductions_max": archive.max_errors,
        "per_frame_reductions_within_tolerance": archive.within_tolerance,
        "streaming_max_abs_difference": finish["streaming_max_abs_difference"],
        "streaming_within_tolerance": all(
            value <= protocol.TOLERANCES["mean_psf"]["atol"] for value in finish["streaming_max_abs_difference"].values()
        ),
        "instantaneous_unit_flux": bool(
            np.all(np.abs(np.asarray(frames["flux_uncorrected"]) - 1.0) <= protocol.TOLERANCES["unit_flux"]["atol"])
            and np.all(np.abs(np.asarray(frames["flux_corrected"]) - 1.0) <= protocol.TOLERANCES["unit_flux"]["atol"])
        ),
        "mean_unit_flux": {
            "uncorrected": float(np.sum(finish["mean_psf_uncorrected"])),
            "corrected": float(np.sum(finish["mean_psf_corrected"])),
        },
        "analysis_frames": [finish["analysis_frames"][0], finish["analysis_frames"][-1] + 1],
        "analysis_count": finish["analysis_count"],
    }
    del inner.all_frames
    readback = archive_means(frames_dir, STARTUP_EXCLUSION_FRAMES, N_STEPS)
    checks["archive_mean_vs_own_mean_max_abs"] = {
        "uncorrected": float(np.max(np.abs(readback["psf_uncorrected"] - finish["own_mean_psf_uncorrected"]))),
        "corrected": float(np.max(np.abs(readback["psf_corrected"] - finish["own_mean_psf_corrected"]))),
    }
    checks["archive_mean_vs_accumulator_max_abs"] = {
        "uncorrected": float(np.max(np.abs(readback["psf_uncorrected"] - finish["mean_psf_uncorrected"]))),
        "corrected": float(np.max(np.abs(readback["psf_corrected"] - finish["mean_psf_corrected"]))),
    }
    del readback
    failed = [
        name
        for name in (
            "atmosphere_rms_matches_history",
            "residual_rms_matches_history",
            "times_match_history",
            "times_are_k_over_1000",
            "frame_indices_complete",
            "usable_matches_history",
            "saturation_matches_history",
            "per_frame_reductions_within_tolerance",
            "streaming_within_tolerance",
            "instantaneous_unit_flux",
        )
        if not checks[name]
    ]
    if failed or checks["analysis_count"] != N_STEPS - STARTUP_EXCLUSION_FRAMES:
        raise LongSeriesError(f"production record checks failed: {failed}")
    np.savez(
        attempt / "mean_psfs.npz",
        mean_psf_uncorrected=finish["mean_psf_uncorrected"],
        mean_psf_corrected=finish["mean_psf_corrected"],
        own_mean_psf_uncorrected=finish["own_mean_psf_uncorrected"],
        own_mean_psf_corrected=finish["own_mean_psf_corrected"],
        ideal_psf=finish["ideal_psf"],
        x_angle_rad=inner.axes["x_angle_rad"],
        y_angle_rad=inner.axes["y_angle_rad"],
        analysis_frames=np.asarray(finish["analysis_frames"], dtype=np.int64),
        pupil_mask=np.asarray(mask, dtype=bool),
    )
    corrected_result = finish["corrected_result"]
    uncorrected_result = finish["uncorrected_result"]
    record: Dict[str, Any] = {
        "schema": CASE_RECORD_SCHEMA,
        "series_id": plan["series_id"],
        "case": {key: case[key] for key in ("job_id", "case_id", "label", "n_steps", "burn_in", "root_seed")},
        "config_hash": config.config_hash,
        "history_config_hash": history.config_hash,
        "admission_sha256": fresh_sha,
        "screen": {
            "option": system.atmosphere_options.to_record(),
            "atmosphere_component_hash": system.atmosphere.config_hash,
            "generated_screen_px": int(built.generated_grid_size),
            "travel_budget_px": float(built.travel_budget_px),
            "supported_travel_duration_s": fresh["supported_travel_duration_s"],
            "atmosphere_metadata": atmosphere_metadata,
        },
        "horizon_runtime_check": horizon_check,
        "identities": {"production_sha256": current["sha256"]},
        "build_s": build_s,
        "loop_s": loop_s,
        "history_digest": producer.history_digest(history),
        "history_metadata": producer.to_jsonable(history.metadata),
        "component_hashes": producer.to_jsonable(dict(system.component_hashes)),
        "science_propagator_config_hash": system.science_propagator.config_hash,
        "observer": {
            "requested_fields": sorted(inner.requested_fields),
            "frames": producer.to_jsonable(frames),
            "checks": producer.to_jsonable(checks),
            "accumulators": {
                "corrected": producer.to_jsonable(corrected_result.to_record()),
                "uncorrected": producer.to_jsonable(uncorrected_result.to_record()),
                "uncorrected_feed": "StreamingLongExposure.add_opd with the frame's recorded atmosphere_opd_m (zero-DM counterfactual)",
                "corrected_feed": "StreamingLongExposure.observe with the observation's pre_update_residual_opd_m",
            },
            "sampling_metadata": producer.to_jsonable(inner.sampling_metadata),
            "pupil_mask_sha256": identity.sha256_bytes(np.ascontiguousarray(mask).tobytes()),
            "pupil_samples": int(np.count_nonzero(mask)),
        },
        "frame_stacks": stacks,
    }
    record["files"] = {}
    for path in sorted(attempt.rglob("*")):
        if path.is_file() and path.suffix in (".npz", ".npy"):
            relative = path.relative_to(attempt).as_posix()
            known = stacks.get(path.stem) if path.parent == frames_dir else None
            record["files"][relative] = {
                "bytes": path.stat().st_size,
                "sha256": known["sha256"] if known else sha256_file_chunked(path),
            }
    record["export_s"] = time.perf_counter() - export_started
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    record["child_peak_rss_bytes"] = int(peak if sys.platform == "darwin" else peak * 1024)
    record["child_wall_s"] = time.perf_counter() - started_wall
    producer.write_json(attempt / "case_record.json", record)
    producer.write_json(attempt / "status.json", {"status": "COMPLETED", "utc": utc_now(), "case_id": case_id})
    return record


# ---------------------------------------------------------------------------
# Supervision


def directory_bytes(directory: Path) -> int:
    return sum(path.stat().st_size for path in Path(directory).rglob("*") if path.is_file())


def resource_estimate(case_id: str) -> Any:
    from shwfs_ao.runtime.resource_guard import MIB, ResourceEstimate

    return ResourceEstimate(
        label=f"long-series-{case_id}",
        baseline_bytes=170 * MIB,
        components={
            # 4 x 4 quadrature replay of the 624 x 624 screen (complex128 work
            # arrays and the subharmonic levels) per atmosphere request.
            "screen_quadrature_work": 160 * MIB,
            "psf_temporaries_and_accumulators": 16 * MIB,
            "wfs_detector_frames_and_calibration": 32 * MIB,
            # 1000-frame scalar records, histories and per-frame digests.
            "histories_and_records": 24 * MIB,
            # One streamed frame at a time; the archive read-back holds one sum per role.
            "archive_streaming_and_readback": 8 * MIB,
        },
        largest_buffer_bytes=48 * MIB,
        notes=("audited from the historical 180-frame children (peak 160-170 MiB) scaled to a 16x larger screen",),
    )


def append_ledger(series_dir: Path, entry: Dict[str, Any]) -> None:
    with (Path(series_dir) / LEDGER_NAME).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, allow_nan=False, sort_keys=True) + "\n")


def ledger_wall_s(series_dir: Path) -> float:
    path = Path(series_dir) / LEDGER_NAME
    if not path.exists():
        return 0.0
    return sum(float(json.loads(line).get("wall_s") or 0.0) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def supervise(series_dir: Path) -> int:
    import shutil

    from shwfs_ao.runtime import resource_guard

    series_dir = Path(series_dir).resolve()
    plan = load_plan(series_dir)
    check_identity(plan)
    per_case_bytes = 470 * 1024 * 1024
    child_env = dict(os.environ)
    child_env["PYTHONPATH"] = os.pathsep.join([str(identity.REPO_ROOT / "src"), str(identity.EXPORTER_DIR)])
    for case_id in CASE_ORDER:
        entry: Dict[str, Any] = {"utc": utc_now(), "case_id": case_id, "launched": False, "wall_s": 0.0}
        if completed_attempt(series_dir, case_id) is not None:
            entry.update(status="SKIPPED_COMPLETED")
            append_ledger(series_dir, entry)
            continue
        used_bytes = directory_bytes(series_dir)
        free = shutil.disk_usage(series_dir).free
        entry.update(consumption_before={"wall_s": ledger_wall_s(series_dir), "bytes": used_bytes, "free_disk_bytes": free})
        if ledger_wall_s(series_dir) >= WALL_TIME_CEILING_S:
            entry.update(status="REFUSED_CEILING", reason="wall-time ceiling reached")
        elif used_bytes + per_case_bytes > STORAGE_CEILING_BYTES:
            entry.update(status="REFUSED_CEILING", reason="projected storage would exceed the ceiling")
        elif free - per_case_bytes < MIN_FREE_DISK_BYTES:
            entry.update(status="REFUSED_CEILING", reason="free disk space would fall below the minimum")
        if entry.get("status"):
            append_ledger(series_dir, entry)
            print(json.dumps(entry), flush=True)
            return 2
        decision = resource_guard.preflight(resource_estimate(case_id))
        entry["guard_preflight"] = decision.to_record()
        if not decision.accepted:
            entry.update(status="REFUSED_GUARD", reason="; ".join(decision.reasons))
            append_ledger(series_dir, entry)
            print(json.dumps(entry), flush=True)
            return 2
        logs = series_dir / "logs"
        logs.mkdir(exist_ok=True)
        log_path = logs / f"{case_id}-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.log"
        print(json.dumps({"utc": utc_now(), "starting": case_id, "log": log_path.name}), flush=True)
        result = resource_guard.run_supervised(
            [sys.executable, str(Path(__file__).resolve()), "run-case", "--series-dir", str(series_dir), "--case", case_id],
            budget_bytes=decision.budget_bytes,
            timeout_s=CHILD_TIMEOUT_S,
            env=child_env,
            threads=NATIVE_THREADS,
            log_path=log_path,
            cwd=str(identity.REPO_ROOT),
        )
        entry.update(
            launched=True,
            status=result.status,
            wall_s=result.wall_s,
            supervised=result.to_record(),
            log=log_path.relative_to(series_dir).as_posix(),
            consumption_after={"bytes": directory_bytes(series_dir), "free_disk_bytes": shutil.disk_usage(series_dir).free},
        )
        append_ledger(series_dir, entry)
        print(json.dumps({"utc": utc_now(), "finished": case_id, "status": result.status, "wall_s": round(result.wall_s, 1)}), flush=True)
        if completed_attempt(series_dir, case_id) is None:
            print(json.dumps({"stopped_after": case_id, "reason": result.reason}), flush=True)
            return 1
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    plan_parser = commands.add_parser("plan")
    plan_parser.add_argument("--output-root", type=Path, required=True)
    plan_parser.add_argument("--original-series", type=Path, required=True)
    supervise_parser = commands.add_parser("supervise")
    supervise_parser.add_argument("--series-dir", type=Path, required=True)
    child = commands.add_parser("run-case")
    child.add_argument("--series-dir", type=Path, required=True)
    child.add_argument("--case", required=True, choices=CASE_ORDER)
    arguments = parser.parse_args(argv)
    if arguments.command == "plan":
        print(make_plan(arguments.output_root, arguments.original_series))
        return 0
    if arguments.command == "supervise":
        return supervise(arguments.series_dir)
    try:
        record = run_case(arguments.series_dir, arguments.case)
    except LongSeriesError as exc:
        print(json.dumps({"status": "REFUSED", "case": arguments.case, "reason": str(exc)}), flush=True)
        return 3
    except Exception as exc:  # noqa: BLE001 - the child reports, the supervisor records
        traceback.print_exc()
        print(json.dumps({"status": "FAILED", "case": arguments.case, "reason": f"{type(exc).__name__}: {exc}"}), flush=True)
        return 1
    print(json.dumps({"status": "COMPLETED", "case": arguments.case, "build_s": record["build_s"], "loop_s": record["loop_s"], "child_wall_s": record["child_wall_s"], "child_peak_rss_bytes": record["child_peak_rss_bytes"]}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
