"""Bounded computation service of the dynamic AO mode (API ``ao-dynamic.api.v1``).

Usage::

    python scripts/ao_dynamic/service.py --port 8765 [--web-dir web] \
        [--allow-origin https://example.org] [--storage-dir outputs/ao_dynamic_service]

The service validates a request against ``contract.py``, allocates a seed when
asked to, runs the complete-horizon admission and only then queues a job.  One
background runner executes at most one numerical job at a time: it launches
``worker.py`` in its own process group with two native threads, follows its
progress lines, enforces a wall-clock limit, and on cancellation stops the
whole group (SIGTERM, then SIGKILL), reaps it, verifies that no member is left
and removes the partial outputs.  Closing a browser does not stop a job;
cancellation is explicit.  A queued or running job that nobody has asked
about for ``--abandon-after-s`` seconds is cancelled as abandoned.

A completed job is accepted only if its ``run.json`` passes the contract's
semantic checks against the accepted parameters and its files match the
recorded sizes and digests; it then moves from ``work/`` to ``runs/`` inside
this instance's own storage namespace (``<storage-dir>/<instance-id>/``),
which never touches the frozen explorer dataset.  At most ``--max-runs-kept``
completed runs are kept; older ones are evicted (their status says so).

Endpoints (JSON unless noted)::

    GET  /api/v1/info                      service, contract, bounds, identities, display tables
    POST /api/v1/check                     validation + admission, no job
    POST /api/v1/runs                      queue a run (202) or refuse (422/429)
    GET  /api/v1/runs                      recent runs of this instance
    GET  /api/v1/runs/<id>                 job status (polling it also renews the job's lease)
    POST /api/v1/runs/<id>/cancel          cancel a queued or running job ({"reason": "visitor" | "superseded"} optional)
    GET  /api/v1/runs/<id>/files/<name>    run.json, frames.bin, final.bin, metrics.csv, evidence.npz

With ``--web-dir`` the static site is also served (``/ao-explorer/``) for a
same-origin local preview.  Cross-origin pages must be listed with
``--allow-origin``; no other origin receives CORS headers.
"""

from __future__ import annotations

import argparse
import collections
import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Deque, Dict, List, Optional
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
EXPLORER = HERE.parent / "ao_explorer"
for _path in (str(HERE), str(EXPLORER)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import contract  # noqa: E402
import worker  # noqa: E402

SERVICE_FILES = ("service.py",)
RUN_ID = re.compile(r"^run-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
MAX_BODY_BYTES = 64 * 1024
CANCEL_REASONS = {
    "requested": "cancelled by request",
    "visitor": "cancelled by the visitor",
    "superseded": "cancelled by request: superseded by a newer request",
}
MAX_EVENT_LINE_BYTES = 64 * 1024
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".png": "image/png",
    ".csv": "text/csv; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".bin": "application/octet-stream",
    ".npz": "application/octet-stream",
}


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


class ServiceError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.extra = extra


class Job:
    def __init__(self, run_id: str, parameters: Dict[str, Any], seed_source: str, admission: Dict[str, Any],
                 client_token: Optional[str]) -> None:
        self.run_id = run_id
        self.parameters = parameters
        self.seed_source = seed_source
        self.admission = admission
        self.admission_sha256 = contract.sha256_bytes(contract.canonical_json_bytes(admission))
        self.client_token = client_token
        self.state = "queued"
        self.created_utc = utc_now()
        self.started_utc: Optional[str] = None
        self.finished_utc: Optional[str] = None
        self.started_monotonic: Optional[float] = None
        self.wall_s: Optional[float] = None
        self.last_seen = time.monotonic()
        self.progress: Dict[str, Any] = {"frames_done": 0, "n_frames": parameters["n_frames"], "physical_time_s": None, "stage": "queued"}
        self.cancel_requested = False
        self.cancel_reason: Optional[str] = None
        self.reason: Optional[str] = None
        self.files: Optional[Dict[str, Any]] = None
        self.evicted = False
        self.worker: Dict[str, Any] = {}
        self.events: Deque[Dict[str, Any]] = collections.deque(maxlen=20)

    def status(self, queue_position: Optional[int]) -> Dict[str, Any]:
        progress = dict(self.progress)
        n = progress["n_frames"]
        progress["fraction"] = progress["frames_done"] / n if n else 0.0
        elapsed = self.wall_s
        if elapsed is None and self.started_monotonic is not None:
            elapsed = time.monotonic() - self.started_monotonic
        return {
            "schema": contract.STATUS_SCHEMA,
            "api": contract.API_VERSION,
            "run_id": self.run_id,
            "state": self.state,
            "seed": self.parameters["seed"],
            "seed_source": self.seed_source,
            "parameters": self.parameters,
            "physical_identity": contract.physical_identity(self.parameters),
            "client_token": self.client_token,
            "created_utc": self.created_utc,
            "started_utc": self.started_utc,
            "finished_utc": self.finished_utc,
            "queue_position": queue_position,
            "progress": progress,
            "computation_wall_s": elapsed,
            "admission": {key: self.admission.get(key) for key in (
                "outcome", "max_travel_px", "travel_budget_px", "margin_px", "request_count", "last_request_s")},
            "admission_sha256": self.admission_sha256,
            "cancel_requested": self.cancel_requested,
            "reason": self.reason,
            "files": None if (self.files is None or self.evicted) else self.files,
            "evicted": self.evicted,
            "worker": dict(self.worker),
        }


class JobManager:
    def __init__(self, storage: Path, *, max_queue: int, job_timeout_s: float, abandon_after_s: float,
                 max_runs_kept: int, enable_test_faults: bool = False, threads: int = 2) -> None:
        self.storage = storage
        self.work = storage / "work"
        self.runs = storage / "runs"
        self.logs = storage / "logs"
        for path in (self.work, self.runs, self.logs):
            path.mkdir(parents=True, exist_ok=True)
        self.ledger = storage / "service-ledger.jsonl"
        self.max_queue = max_queue
        self.job_timeout_s = job_timeout_s
        self.abandon_after_s = abandon_after_s
        self.max_runs_kept = max_runs_kept
        self.enable_test_faults = enable_test_faults
        self.threads = threads
        self.jobs: "collections.OrderedDict[str, Job]" = collections.OrderedDict()
        self.queue: Deque[str] = collections.deque()
        self.used_seeds: set = set()
        self.lock = threading.Condition()
        self.stopping = False
        self.runner = threading.Thread(target=self._run_forever, name="numerical-runner", daemon=True)
        self.runner.start()

    # ---------------------------------------------------------------- submission

    def allocate_seed(self) -> int:
        spec = contract.parameter("seed")
        while True:
            seed = spec["minimum"] + secrets.randbelow(spec["maximum"] - spec["minimum"] + 1)
            if seed not in self.used_seeds and seed not in (1, 2):  # 1 and 2 are the frozen explorer's seeds
                return seed

    def evaluate(self, request: Any, *, allocate: bool) -> Dict[str, Any]:
        """Validate and admit a request (no job); raises ServiceError(422) with every reason."""

        import physics

        reasons = contract.validate_request(request)
        if reasons:
            raise ServiceError(HTTPStatus.UNPROCESSABLE_ENTITY, "invalid_request", "the request is outside the API v1 contract", reasons=reasons)
        parameters = dict(request["parameters"])
        seed_source = "specified"
        if request["seed_policy"] == "allocate":
            with self.lock:
                parameters["seed"] = self.allocate_seed() if allocate else 1
            seed_source = "allocated_by_service"
        params = contract.effective_parameters(parameters)
        config = physics.effective_config(params)
        admission = physics.admit(config)
        result = {
            "schema": contract.CHECK_SCHEMA,
            "api": contract.API_VERSION,
            "valid": True,
            "admitted": bool(admission["admitted"]),
            "parameters": params,
            "seed_source": seed_source,
            "physical_identity": contract.physical_identity(params),
            "system_config_hash": config.config_hash,
            "admission": admission,
        }
        if not admission["admitted"]:
            raise ServiceError(HTTPStatus.UNPROCESSABLE_ENTITY, "not_admitted",
                               "the finite frozen-flow screen does not support every requested atmosphere sample",
                               reasons=admission["reasons"], admission=admission, parameters=params)
        return result

    def submit(self, request: Any) -> Job:
        evaluation = self.evaluate(request, allocate=True)
        with self.lock:
            active = sum(1 for job in self.jobs.values() if job.state in ("queued", "running"))
            if active >= self.max_queue + 1:
                raise ServiceError(HTTPStatus.TOO_MANY_REQUESTS, "busy",
                                   f"{active} jobs are queued or running; the service accepts at most {self.max_queue + 1}")
            run_id = f"run-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"
            job = Job(run_id, evaluation["parameters"], evaluation["seed_source"], evaluation["admission"], request.get("client_token"))
            self.used_seeds.add(job.parameters["seed"])
            self.jobs[run_id] = job
            self.queue.append(run_id)
            self.lock.notify_all()
            return job

    # ---------------------------------------------------------------- queries

    def status(self, run_id: str, *, touch: bool = True) -> Dict[str, Any]:
        with self.lock:
            job = self.jobs.get(run_id)
            if job is None:
                raise ServiceError(HTTPStatus.NOT_FOUND, "unknown_run", f"run {run_id} is not known to this service instance")
            if touch:
                job.last_seen = time.monotonic()
            position = list(self.queue).index(run_id) if run_id in self.queue else None
            return job.status(position)

    def list_runs(self) -> List[Dict[str, Any]]:
        with self.lock:
            return [
                {"run_id": job.run_id, "state": job.state, "seed": job.parameters["seed"], "created_utc": job.created_utc,
                 "physical_identity": contract.physical_identity(job.parameters), "evicted": job.evicted,
                 "parameters": job.parameters}
                for job in reversed(self.jobs.values())
            ][:50]

    def file_path(self, run_id: str, name: str) -> Path:
        with self.lock:
            job = self.jobs.get(run_id)
            if job is None:
                raise ServiceError(HTTPStatus.NOT_FOUND, "unknown_run", f"run {run_id} is not known to this service instance")
            if job.state != "completed":
                raise ServiceError(HTTPStatus.CONFLICT, "not_completed", f"run {run_id} is {job.state}; only completed runs have files")
            if job.evicted:
                raise ServiceError(HTTPStatus.GONE, "evicted", f"run {run_id} was evicted from this service's bounded storage")
        if name not in contract.RUN_FILES:
            raise ServiceError(HTTPStatus.NOT_FOUND, "unknown_file", f"{name} is not a run file")
        return self.runs / run_id / name

    # ---------------------------------------------------------------- cancellation

    def cancel(self, run_id: str, reason: str = "cancelled by request", wait_s: float = 10.0) -> Dict[str, Any]:
        deadline = time.monotonic() + wait_s
        with self.lock:
            job = self.jobs.get(run_id)
            if job is None:
                raise ServiceError(HTTPStatus.NOT_FOUND, "unknown_run", f"run {run_id} is not known to this service instance")
            job.last_seen = time.monotonic()
            if job.state == "queued":
                self.queue.remove(run_id)
                self._finish(job, "cancelled", f"{reason} before it started")
            elif job.state == "running":
                job.cancel_requested = True
                job.cancel_reason = reason
                self.lock.notify_all()
                while job.state == "running" and time.monotonic() < deadline:
                    self.lock.wait(timeout=0.1)
            return job.status(None)

    # ---------------------------------------------------------------- runner

    def shutdown(self) -> None:
        with self.lock:
            self.stopping = True
            for job in self.jobs.values():
                if job.state == "running":
                    job.cancel_requested = True
                    job.cancel_reason = "service shutting down"
            self.lock.notify_all()
        self.runner.join(timeout=15)

    def _finish(self, job: Job, state: str, reason: Optional[str]) -> None:
        job.state = state
        job.reason = reason
        job.finished_utc = utc_now()
        if job.started_monotonic is not None:
            job.wall_s = time.monotonic() - job.started_monotonic
        job.progress["stage"] = state
        entry = {
            "utc": job.finished_utc,
            "run_id": job.run_id,
            "state": state,
            "reason": reason,
            "wall_s": job.wall_s or 0.0,
            "launched": job.started_monotonic is not None,
            "parameters": job.parameters,
            "worker": job.worker,
        }
        with self.ledger.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True, allow_nan=False) + "\n")
        self.lock.notify_all()

    def _next_job(self) -> Optional[Job]:
        with self.lock:
            while not self.stopping:
                self._expire_abandoned_queued()
                if self.queue:
                    job = self.jobs[self.queue.popleft()]
                    job.state = "running"
                    job.started_utc = utc_now()
                    job.started_monotonic = time.monotonic()
                    job.progress["stage"] = "starting"
                    return job
                self.lock.wait(timeout=1.0)
        return None

    def _expire_abandoned_queued(self) -> None:
        now = time.monotonic()
        for run_id in list(self.queue):
            job = self.jobs[run_id]
            if now - job.last_seen > self.abandon_after_s:
                self.queue.remove(run_id)
                self._finish(job, "cancelled", f"abandoned: no status request for {self.abandon_after_s:g} s before it started")

    def _run_forever(self) -> None:
        while True:
            job = self._next_job()
            if job is None:
                return
            try:
                self._execute(job)
            except Exception as exc:  # noqa: BLE001 - a runner defect must not stop the service
                with self.lock:
                    if job.state == "running":
                        self._finish(job, "failed", f"service error: {type(exc).__name__}: {exc}")

    def _launch(self, job: Job, job_dir: Path, log_path: Path) -> subprocess.Popen:
        from shwfs_ao.runtime import resource_guard

        environment = resource_guard.limited_environment(threads=self.threads)
        environment.pop(worker.FAULT_ENV, None)
        if self.enable_test_faults and job.client_token and job.client_token.startswith("test-fault:"):
            environment[worker.FAULT_ENV] = job.client_token[len("test-fault:"):]
        log_handle = open(log_path, "wb")  # noqa: SIM115 - closed after the process ends
        try:
            process = subprocess.Popen(
                [sys.executable, str(HERE / "worker.py"), "--job-dir", str(job_dir)],
                env=environment,
                cwd=str(HERE.parents[1]),
                stdout=subprocess.PIPE,
                stderr=log_handle,
                start_new_session=True,
            )
        finally:
            log_handle.close()
        job.worker = {
            "pid": process.pid,
            "process_group": process.pid,
            "threads": {name: environment[name] for name in resource_guard.THREAD_ENV_VARS},
            "memory_enforcement_enabled": resource_guard.resource_guard_enabled(),
        }
        return process

    def _read_events(self, job: Job, process: subprocess.Popen) -> None:
        assert process.stdout is not None
        for raw in iter(lambda: process.stdout.readline(MAX_EVENT_LINE_BYTES), b""):
            try:
                event = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            with self.lock:
                job.events.append(event)
                kind = event.get("event")
                if kind == "progress":
                    job.progress.update(frames_done=int(event["frames_done"]), physical_time_s=float(event["physical_time_s"]), stage="running loop")
                elif kind == "built":
                    job.progress["stage"] = "system built (calibration done); running loop"
                    job.worker["interaction_matrix_hash"] = event.get("interaction_matrix_hash")
                elif kind == "started":
                    job.progress["stage"] = "building system and calibration"
                elif kind in ("completed", "failed", "refused"):
                    job.worker["final_event"] = event

    def _stop_group(self, process: subprocess.Popen) -> Dict[str, Any]:
        pgid = process.pid
        record: Dict[str, Any] = {"signals": []}
        for sig, grace in ((signal.SIGTERM, 2.0), (signal.SIGKILL, 5.0)):
            try:
                os.killpg(pgid, sig)
                record["signals"].append(sig.name)
            except ProcessLookupError:
                break
            try:
                process.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                continue
            if not _group_exists(pgid):
                break
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:  # pragma: no cover - kernel dependent
            pass
        record["returncode"] = process.returncode
        record["process_group_alive_after"] = _group_exists(pgid)
        return record

    def _execute(self, job: Job) -> None:
        job_dir = self.work / job.run_id
        job_dir.mkdir(parents=True, exist_ok=False)
        request = {
            "run_id": job.run_id,
            "created_utc": job.created_utc,
            "seed_source": job.seed_source,
            "parameters": job.parameters,
            "admission_sha256": job.admission_sha256,
        }
        (job_dir / "request.json").write_text(json.dumps(request, indent=1) + "\n", encoding="utf-8")
        log_path = self.logs / f"{job.run_id}.log"
        process = self._launch(job, job_dir, log_path)
        reader = threading.Thread(target=self._read_events, args=(job, process), daemon=True)
        reader.start()
        stop_reason: Optional[str] = None
        stop_state = "failed"
        while True:
            returncode = process.poll()
            if returncode is not None:
                break
            with self.lock:
                now = time.monotonic()
                if job.cancel_requested:
                    stop_reason, stop_state = job.cancel_reason or "cancelled by request", "cancelled"
                elif now - job.last_seen > self.abandon_after_s:
                    stop_reason, stop_state = f"abandoned: no status request for {self.abandon_after_s:g} s", "cancelled"
                elif job.started_monotonic is not None and now - job.started_monotonic > self.job_timeout_s:
                    stop_reason, stop_state = f"wall-clock limit {self.job_timeout_s:g} s exceeded", "failed"
                if stop_reason is None:
                    self.lock.wait(timeout=0.1)
                    continue
            break
        cleanup = None
        if stop_reason is not None:
            cleanup = self._stop_group(process)
        else:
            process.wait()
            cleanup = {"returncode": process.returncode, "process_group_alive_after": _group_exists(process.pid)}
        reader.join(timeout=5.0)
        with self.lock:
            job.worker["cleanup"] = cleanup
            job.worker["exit_code"] = process.returncode
        if stop_reason is not None:
            shutil.rmtree(job_dir, ignore_errors=True)
            with self.lock:
                job.worker["partial_outputs_removed"] = not job_dir.exists()
                self._finish(job, stop_state, stop_reason)
            return
        final = job.worker.get("final_event") or {}
        if process.returncode != 0 or final.get("event") != "completed":
            reason = final.get("reason") or f"worker exited with status {process.returncode}"
            shutil.rmtree(job_dir, ignore_errors=True)
            with self.lock:
                job.worker["partial_outputs_removed"] = not job_dir.exists()
                self._finish(job, "failed", reason)
            return
        try:
            files = self._accept(job, job_dir)
        except ServiceError as exc:
            shutil.rmtree(job_dir, ignore_errors=True)
            with self.lock:
                self._finish(job, "failed", f"result refused: {exc}")
            return
        target = self.runs / job.run_id
        os.replace(job_dir, target)
        with self.lock:
            job.files = files
            self._finish(job, "completed", None)
            self._evict()

    def _accept(self, job: Job, job_dir: Path) -> Dict[str, Any]:
        data = (job_dir / "run.json").read_bytes()
        record = json.loads(data.decode("utf-8"))
        sizes = {name: (job_dir / name).stat().st_size for name in contract.RUN_FILES if (job_dir / name).is_file()}
        problems = contract.validate_run_record(record, expected_parameters=job.parameters, file_sizes=sizes)
        if record.get("run_id") != job.run_id:
            problems.append("run.json names another run")
        if record.get("admission_sha256") != job.admission_sha256:
            problems.append("the worker's admission differs from the accepted one")
        for key, name in (("frames", "frames.bin"), ("final", "final.bin"), ("metrics_csv", "metrics.csv"), ("evidence_npz", "evidence.npz")):
            ref = record["arrays"][key]
            if contract.sha256_bytes((job_dir / name).read_bytes()) != ref["sha256"]:
                problems.append(f"{name} does not match its recorded SHA-256")
        if problems:
            raise ServiceError(HTTPStatus.INTERNAL_SERVER_ERROR, "invalid_result", "; ".join(problems))
        files = {"run.json": {"href": "files/run.json", "bytes": len(data), "sha256": contract.sha256_bytes(data)}}
        for key, name in (("frames", "frames.bin"), ("final", "final.bin"), ("metrics_csv", "metrics.csv"), ("evidence_npz", "evidence.npz")):
            ref = record["arrays"][key]
            files[name] = {"href": f"files/{name}", "bytes": ref["bytes"], "sha256": ref["sha256"]}
        return files

    def _evict(self) -> None:
        completed = [job for job in self.jobs.values() if job.state == "completed" and not job.evicted]
        for job in completed[:-self.max_runs_kept] if len(completed) > self.max_runs_kept else []:
            shutil.rmtree(self.runs / job.run_id, ignore_errors=True)
            job.evicted = True


def _group_exists(pgid: int) -> bool:
    """True while any non-zombie process remains in the group."""

    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        listing = subprocess.run(["ps", "-A", "-o", "pgid=,stat="], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return True
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and int(parts[0]) == pgid and parts[1][:1] not in ("Z", "X"):
            return True
    return False


# ---------------------------------------------------------------------------
# Service description


def service_identity() -> Dict[str, Any]:
    return {"directory": "scripts/ao_dynamic", **worker.file_set_identity(HERE, SERVICE_FILES)}


def build_info(manager: JobManager, instance_id: str, started_utc: str, allowed_origins: List[str]) -> Dict[str, Any]:
    import identity
    import physics
    from matplotlib import colormaps

    def lut(name: str) -> List[str]:
        values = colormaps[name]([index / 255.0 for index in range(256)])
        return ["#%02x%02x%02x" % tuple(int(channel * 255.0 + 0.5) for channel in row[:3]) for row in values]

    from shwfs_ao.runtime import resource_guard

    config = physics.effective_config(contract.default_parameters())
    core = identity.core_identity()
    return {
        "schema": contract.INFO_SCHEMA,
        "api": contract.API_VERSION,
        "schemas": {
            "request": contract.REQUEST_SCHEMA, "status": contract.STATUS_SCHEMA, "run": contract.RUN_SCHEMA,
            "check": contract.CHECK_SCHEMA, "error": contract.ERROR_SCHEMA,
        },
        "service": {
            "instance_id": instance_id,
            "started_utc": started_utc,
            "identity": service_identity(),
            "allowed_origins": allowed_origins,
            "kind": "development/self-hosted computation service; not a managed production backend",
        },
        "producer": worker.dynamic_identity(),
        "core": {"package_sha256": core["package_sha256"], "git_head": (core.get("git") or {}).get("git_head")},
        "environment": identity.environment_identity(),
        "profile": contract.FIXED["profile"],
        "fixed": contract.FIXED,
        "parameters": contract.info_parameters(),
        "seed_policies": list(contract.SEED_POLICIES),
        "comparison": {
            "same_atmosphere_changes": list(contract.SAME_ATMOSPHERE_CHANGES),
            "atmosphere_parameters": list(contract.ATMOSPHERE_PARAMETERS),
            "calibration_parameters": list(contract.CALIBRATION_PARAMETERS),
            "rule": "a comparison is labelled paired only when the time grids and every atmosphere sample digest match",
        },
        "horizon": physics.horizon_constants(config),
        "limits": {
            "max_active_jobs": manager.max_queue + 1,
            "concurrent_numerical_jobs": 1,
            "job_timeout_s": manager.job_timeout_s,
            "abandon_after_s": manager.abandon_after_s,
            "max_runs_kept": manager.max_runs_kept,
            "max_transported_frames": contract.MAX_TRANSPORTED_FRAMES,
            "min_analysis_samples": contract.MIN_ANALYSIS_SAMPLES,
            "native_threads": manager.threads,
            "memory_enforcement_enabled": resource_guard.resource_guard_enabled(),
        },
        "display": {
            "opd_colormap": "RdBu_r",
            "opd_lut_rgb_hex": lut("RdBu_r"),
            "intensity_colormap": "inferno",
            "intensity_lut_rgb_hex": lut("inferno"),
            "psf_log_decades": contract.PSF_LOG_DECADES,
            "crop_shape_yx": list(contract.CROP_SHAPE),
            "phase_display_wavelengths_m": list(contract.PHASE_DISPLAY_WAVELENGTHS_M),
            "phase_rule": contract.PHASE_RULE,
            "phase_wrapping": contract.PHASE_WRAPPING,
        },
        "frame_blocks": [{"name": name, "shape": list(shape), "unit": unit} for name, shape, unit in contract.FRAME_BLOCKS],
        "final_blocks": [{"name": name, "shape": list(shape), "unit": unit} for name, shape, unit in contract.FINAL_BLOCKS],
        "run_files": list(contract.RUN_FILES),
        "notes": [
            "Each run computes one finite seeded realization and completes before replay; it does not keep pace with the 1 kHz loop.",
            "Jobs run one at a time; cancellation stops the worker process group explicitly.",
        ],
    }


# ---------------------------------------------------------------------------
# HTTP


class Handler(BaseHTTPRequestHandler):
    server_version = "ao-dynamic/1"
    manager: JobManager
    info: Dict[str, Any]
    allowed_origins: List[str]
    web_dir: Optional[Path]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - BaseHTTPRequestHandler API
        if os.environ.get("AO_DYNAMIC_QUIET") != "1":
            sys.stderr.write("%s %s\n" % (self.log_date_time_string(), format % args))

    # Responses ---------------------------------------------------------

    def _cors(self) -> None:
        origin = self.headers.get("Origin")
        if origin and origin in self.allowed_origins:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def _send(self, status: int, body: bytes, content_type: str, *, cache: str = "no-store") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self._cors()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, value: Any) -> None:
        self._send(status, (json.dumps(value, allow_nan=False) + "\n").encode("utf-8"), "application/json")

    def _error(self, exc: ServiceError) -> None:
        payload = {"schema": contract.ERROR_SCHEMA, "api": contract.API_VERSION, "error": exc.code, "message": str(exc), **exc.extra}
        self._json(exc.status, payload)

    def _body(self) -> Any:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise ServiceError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "too_large", "request body too large")
        if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
            raise ServiceError(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "media_type", "requests must be application/json")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"), parse_constant=_reject_constant)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ServiceError(HTTPStatus.BAD_REQUEST, "bad_json", f"request body is not valid JSON: {exc}")

    # Routing -----------------------------------------------------------

    def do_OPTIONS(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        origin = self.headers.get("Origin")
        self.send_response(HTTPStatus.NO_CONTENT if origin in self.allowed_origins else HTTPStatus.FORBIDDEN)
        if origin in self.allowed_origins:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Vary", "Origin")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_HEAD(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        path = urlsplit(self.path).path
        try:
            if path.startswith("/api/"):
                self._api(method, path)
            elif method == "GET" and self.web_dir is not None:
                self._static(path)
            else:
                raise ServiceError(HTTPStatus.NOT_FOUND, "not_found", f"{path} is not served")
        except ServiceError as exc:
            self._error(exc)
        except Exception as exc:  # noqa: BLE001 - every failure becomes a readable error
            self._error(ServiceError(HTTPStatus.INTERNAL_SERVER_ERROR, "internal", f"{type(exc).__name__}: {exc}"))

    def _api(self, method: str, path: str) -> None:
        parts = path.rstrip("/").split("/")[1:]
        if parts[:2] != ["api", "v1"]:
            raise ServiceError(HTTPStatus.NOT_FOUND, "unsupported_api", "only /api/v1 is served")
        rest = parts[2:]
        manager = self.manager
        if method == "GET" and rest == ["info"]:
            return self._json(HTTPStatus.OK, self.info)
        if method == "POST" and rest == ["check"]:
            return self._json(HTTPStatus.OK, manager.evaluate(self._body(), allocate=False))
        if rest == ["runs"]:
            if method == "POST":
                job = manager.submit(self._body())
                return self._json(HTTPStatus.ACCEPTED, manager.status(job.run_id))
            return self._json(HTTPStatus.OK, {"schema": "ao-dynamic.run-list.v1", "api": contract.API_VERSION, "runs": manager.list_runs()})
        if len(rest) >= 2 and rest[0] == "runs":
            run_id = rest[1]
            if not RUN_ID.match(run_id):
                raise ServiceError(HTTPStatus.NOT_FOUND, "unknown_run", "malformed run id")
            if method == "GET" and len(rest) == 2:
                return self._json(HTTPStatus.OK, manager.status(run_id))
            if method == "POST" and rest[2:] == ["cancel"]:
                body = self._body() if int(self.headers.get("Content-Length") or 0) else {}
                code = body.get("reason", "requested") if isinstance(body, dict) else None
                if code not in CANCEL_REASONS:
                    raise ServiceError(HTTPStatus.UNPROCESSABLE_ENTITY, "invalid_request", f"cancel reason must be one of {sorted(CANCEL_REASONS)}")
                return self._json(HTTPStatus.OK, manager.cancel(run_id, CANCEL_REASONS[code]))
            if method == "GET" and len(rest) == 4 and rest[2] == "files":
                path = manager.file_path(run_id, rest[3])
                content_type = CONTENT_TYPES.get(Path(rest[3]).suffix, "application/octet-stream")
                return self._send(HTTPStatus.OK, path.read_bytes(), content_type, cache="private, max-age=86400, immutable")
        raise ServiceError(HTTPStatus.NOT_FOUND, "not_found", f"{method} {path} is not part of API v1")

    def _static(self, path: str) -> None:
        assert self.web_dir is not None
        if path == "/":
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/ao-explorer/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        relative = path.lstrip("/")
        if relative.endswith("/") or relative == "":
            relative += "index.html"
        target = (self.web_dir / relative).resolve()
        if not target.is_relative_to(self.web_dir) or not target.is_file():
            raise ServiceError(HTTPStatus.NOT_FOUND, "not_found", f"{path} is not part of the site")
        self._send(HTTPStatus.OK, target.read_bytes(), CONTENT_TYPES.get(target.suffix, "application/octet-stream"), cache="no-cache")


def _reject_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON constant {value}")


def make_server(host: str, port: int, *, storage_root: Path, web_dir: Optional[Path], allowed_origins: List[str],
                max_queue: int = 3, job_timeout_s: float = 240.0, abandon_after_s: float = 300.0,
                max_runs_kept: int = 8, enable_test_faults: bool = False) -> tuple:
    instance_id = f"{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"
    storage = Path(storage_root) / instance_id
    manager = JobManager(storage, max_queue=max_queue, job_timeout_s=job_timeout_s, abandon_after_s=abandon_after_s,
                         max_runs_kept=max_runs_kept, enable_test_faults=enable_test_faults)
    info = build_info(manager, instance_id, utc_now(), allowed_origins)
    handler = type("BoundHandler", (Handler,), {
        "manager": manager,
        "info": info,
        "allowed_origins": list(allowed_origins),
        "web_dir": None if web_dir is None else Path(web_dir).resolve(),
    })
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server, manager, storage


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--storage-dir", type=Path, default=Path("outputs/ao_dynamic_service"))
    parser.add_argument("--web-dir", type=Path, default=None, help="also serve this directory (e.g. web) for a same-origin preview")
    parser.add_argument("--allow-origin", action="append", default=[], help="exact origin allowed to call the API cross-origin (repeatable)")
    parser.add_argument("--max-queue", type=int, default=3)
    parser.add_argument("--job-timeout-s", type=float, default=240.0)
    parser.add_argument("--abandon-after-s", type=float, default=300.0)
    parser.add_argument("--max-runs-kept", type=int, default=8)
    parser.add_argument("--enable-test-faults", action="store_true", help=argparse.SUPPRESS)
    arguments = parser.parse_args(argv)
    for origin in arguments.allow_origin:
        parsed = urlsplit(origin)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.path not in ("", "/") or origin.endswith("/"):
            parser.error(f"--allow-origin {origin!r} must be an exact origin such as https://example.org")
    server, manager, storage = make_server(
        arguments.host, arguments.port, storage_root=arguments.storage_dir, web_dir=arguments.web_dir,
        allowed_origins=arguments.allow_origin, max_queue=arguments.max_queue, job_timeout_s=arguments.job_timeout_s,
        abandon_after_s=arguments.abandon_after_s, max_runs_kept=arguments.max_runs_kept,
        enable_test_faults=arguments.enable_test_faults,
    )
    host, port = server.server_address[:2]
    print(json.dumps({"event": "listening", "url": f"http://{host}:{port}", "api": contract.API_VERSION,
                      "storage": str(storage), "web": None if arguments.web_dir is None else f"http://{host}:{port}/ao-explorer/"}), flush=True)

    def stop(signum: int, frame: Any) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        manager.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
