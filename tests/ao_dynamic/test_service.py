"""Computation-service lifecycle against real worker processes (small fixtures).

Each test starts its own service instance (ephemeral port, temporary storage)
with test faults enabled; a fault is requested through the client token
``test-fault:<fault>`` and only honoured by a service started with
``enable_test_faults``.  Completed jobs are 16-frame fixtures.
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request

import pytest

import contract
import service


@contextlib.contextmanager
def running_service(tmp_path: Path, **options):
    defaults = dict(max_queue=3, job_timeout_s=120.0, abandon_after_s=120.0, max_runs_kept=8, enable_test_faults=True)
    defaults.update(options)
    server, manager, storage = service.make_server(
        "127.0.0.1", 0, storage_root=tmp_path / "storage", web_dir=Path(__file__).resolve().parents[2] / "web",
        allowed_origins=["https://pages.example"], **defaults)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", manager, storage
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()


def call(base, path, body=None, *, method=None, headers=None, raw=None):
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    request = urllib.request.Request(base + path, data=data, method=method or ("POST" if data is not None else "GET"),
                                     headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def jcall(base, path, body=None, **kw):
    status, headers, data = call(base, path, body, **kw)
    return status, json.loads(data)


def request(token=None, policy="specified", **changes):
    parameters = contract.default_parameters()
    parameters.update(n_frames=16, burn_in=6, display_stride=1)
    parameters.update(changes)
    if policy == "allocate":
        parameters["seed"] = None
    body = {"schema": contract.REQUEST_SCHEMA, "api": contract.API_VERSION, "seed_policy": policy, "parameters": parameters}
    if token:
        body["client_token"] = token
    return body


def wait_state(base, run_id, states, timeout=90.0, touch=True, manager=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = manager.status(run_id, touch=False) if not touch else jcall(base, f"/api/v1/runs/{run_id}")[1]
        if status["state"] in states:
            return status
        time.sleep(0.1)
    raise AssertionError(f"{run_id} did not reach {states}")


def wait_progress(base, run_id, frames=1, timeout=60.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = jcall(base, f"/api/v1/runs/{run_id}")[1]
        if status["state"] == "running" and status["progress"]["frames_done"] >= frames:
            return status
        time.sleep(0.1)
    raise AssertionError("no progress")


def assert_cleaned(status, storage, run_id):
    cleanup = status["worker"]["cleanup"]
    assert cleanup["process_group_alive_after"] is False
    with pytest.raises(ProcessLookupError):
        os.kill(status["worker"]["pid"], 0)
    assert status["worker"]["partial_outputs_removed"] is True
    assert not (storage / "work" / run_id).exists() and not (storage / "runs" / run_id).exists()


def test_info_cors_and_static_site(tmp_path):
    with running_service(tmp_path) as (base, _manager, _storage):
        status, headers, data = call(base, "/api/v1/info", headers={"Origin": "https://pages.example"})
        info = json.loads(data)
        assert status == 200 and info["api"] == contract.API_VERSION and info["schema"] == contract.INFO_SCHEMA
        assert headers.get("Access-Control-Allow-Origin") == "https://pages.example"
        assert [p["name"] for p in info["parameters"]] == list(contract.PARAMETER_NAMES)
        assert len(info["display"]["opd_lut_rgb_hex"]) == 256 and info["limits"]["concurrent_numerical_jobs"] == 1
        assert info["horizon"]["travel_budget_px"] == 52.0
        _s, headers, _d = call(base, "/api/v1/info", headers={"Origin": "https://evil.example"})
        assert "Access-Control-Allow-Origin" not in headers
        assert call(base, "/api/v1/info", method="OPTIONS", headers={"Origin": "https://evil.example"})[0] == 403
        preflight = call(base, "/api/v1/runs", method="OPTIONS", headers={"Origin": "https://pages.example"})
        assert preflight[0] == 204 and preflight[1]["Access-Control-Allow-Methods"] == "GET, POST"
        assert call(base, "/ao-explorer/")[0] == 200
        assert call(base, "/ao-explorer/../../pyproject.toml")[0] == 404
        assert call(base, "/ao-explorer/%2e%2e/%2e%2e/pyproject.toml")[0] == 404
        assert call(base, "/api/v2/info")[0] == 404


def test_invalid_and_inadmissible_requests_are_refused_with_reasons(tmp_path):
    with running_service(tmp_path) as (base, manager, _storage):
        status, body = jcall(base, "/api/v1/runs", request(controller_gain=1.5, n_frames=15))
        assert status == 422 and body["error"] == "invalid_request"
        assert any("controller_gain" in r for r in body["reasons"]) and any("n_frames" in r for r in body["reasons"])
        assert call(base, "/api/v1/runs", raw=b"{not json")[0] == 400
        assert call(base, "/api/v1/runs", raw=b"{}", headers={"Content-Type": "text/plain"})[0] == 415
        assert call(base, "/api/v1/runs", raw=b'{"x": NaN}')[0] == 400
        status, body = jcall(base, "/api/v1/runs", request(n_frames=205, burn_in=40, display_stride=2))
        assert status == 422 and body["error"] == "not_admitted"
        assert body["admission"]["outcome"] == "REFUSED_OVER_HORIZON" and body["admission"]["first_refused_request"]["request_index"] == 204
        status, body = jcall(base, "/api/v1/check", request(n_frames=204, burn_in=40, display_stride=2))
        assert status == 200 and body["admitted"] and body["admission"]["margin_px"] >= 0
        assert manager.jobs == {}  # nothing was queued


def test_completed_runs_are_verified_served_and_evicted(tmp_path):
    with running_service(tmp_path, max_runs_kept=1) as (base, _manager, storage):
        status, first = jcall(base, "/api/v1/runs", request())
        assert status == 202 and first["state"] in ("queued", "running") and first["seed"] == 1
        done = wait_state(base, first["run_id"], ("completed", "failed"))
        assert done["state"] == "completed", done["reason"]
        status, _h, data = call(base, f"/api/v1/runs/{first['run_id']}/files/run.json")
        run = json.loads(data)
        assert contract.validate_run_record(run, expected_parameters=contract.effective_parameters(request()["parameters"])) == []
        assert contract.sha256_bytes(data) == done["files"]["run.json"]["sha256"]
        frames = call(base, f"/api/v1/runs/{first['run_id']}/files/frames.bin")[2]
        assert contract.sha256_bytes(frames) == run["arrays"]["frames"]["sha256"]
        assert call(base, f"/api/v1/runs/{first['run_id']}/files/request.json")[0] == 404
        # A new realization: the service allocates and records a fresh seed.
        status, second = jcall(base, "/api/v1/runs", request(policy="allocate"))
        assert status == 202 and second["seed_source"] == "allocated_by_service" and second["seed"] not in (1, 2)
        done2 = wait_state(base, second["run_id"], ("completed", "failed"))
        assert done2["state"] == "completed"
        run2 = json.loads(call(base, f"/api/v1/runs/{second['run_id']}/files/run.json")[2])
        assert run2["effective"]["parameters"]["seed"] == second["seed"] and run2["seed_source"] == "allocated_by_service"
        assert run2["per_frame"]["atmosphere_sha256"][0] != run["per_frame"]["atmosphere_sha256"][0]
        # Bounded storage: the older run is evicted and says so.
        assert call(base, f"/api/v1/runs/{first['run_id']}/files/run.json")[0] == 410
        assert jcall(base, f"/api/v1/runs/{first['run_id']}")[1]["evicted"] is True
        listing = jcall(base, "/api/v1/runs")[1]["runs"]
        assert [r["run_id"] for r in listing] == [second["run_id"], first["run_id"]]
        assert not any((storage / "work").iterdir())


def test_cancelling_a_running_job_stops_its_process_group(tmp_path):
    with running_service(tmp_path) as (base, _manager, storage):
        _s, job = jcall(base, "/api/v1/runs", request(token="test-fault:sleep_at:frame3"))
        wait_progress(base, job["run_id"], frames=1)
        status, cancelled = jcall(base, f"/api/v1/runs/{job['run_id']}/cancel", {})
        assert status == 200 and cancelled["state"] == "cancelled" and "cancelled by request" in cancelled["reason"]
        assert cancelled["files"] is None
        assert_cleaned(cancelled, storage, job["run_id"])
        # The runner continues with the next job.
        _s, after = jcall(base, "/api/v1/runs", request(token="test-fault:fail_at:start"))
        assert wait_state(base, after["run_id"], ("failed",))["reason"].startswith("RuntimeError: injected test fault")


def test_cancelling_a_queued_job_and_busy_refusal(tmp_path):
    with running_service(tmp_path, max_queue=1) as (base, _manager, _storage):
        _s, a = jcall(base, "/api/v1/runs", request(token="test-fault:sleep_at:start"))
        _s, b = jcall(base, "/api/v1/runs", request(token="test-fault:sleep_at:start"))
        assert jcall(base, f"/api/v1/runs/{b['run_id']}")[1]["queue_position"] == 0
        status, busy = jcall(base, "/api/v1/runs", request())
        assert status == 429 and busy["error"] == "busy"
        _s, cancelled_b = jcall(base, f"/api/v1/runs/{b['run_id']}/cancel", {})
        assert cancelled_b["state"] == "cancelled" and "before it started" in cancelled_b["reason"] and cancelled_b["started_utc"] is None
        wait_state(base, a["run_id"], ("running",))
        _s, cancelled_a = jcall(base, f"/api/v1/runs/{a['run_id']}/cancel", {})
        assert cancelled_a["state"] == "cancelled"


def test_failures_timeouts_and_abandoned_jobs_release_their_workers(tmp_path):
    with running_service(tmp_path, job_timeout_s=4.0, abandon_after_s=60.0) as (base, _manager, storage):
        _s, failing = jcall(base, "/api/v1/runs", request(token="test-fault:fail_at:built"))
        failed = wait_state(base, failing["run_id"], ("failed",))
        assert "injected test fault at built" in failed["reason"] and failed["files"] is None
        assert_cleaned(failed, storage, failing["run_id"]) if failed["worker"].get("cleanup", {}).get("signals") else None
        assert not (storage / "work" / failing["run_id"]).exists()
        _s, slow = jcall(base, "/api/v1/runs", request(token="test-fault:sleep_at:start"))
        timed_out = wait_state(base, slow["run_id"], ("failed",))
        assert "wall-clock limit 4 s exceeded" in timed_out["reason"]
        assert_cleaned(timed_out, storage, slow["run_id"])
    with running_service(tmp_path / "abandon", abandon_after_s=2.0) as (base, manager, storage):
        _s, idle = jcall(base, "/api/v1/runs", request(token="test-fault:sleep_at:start"))
        # Nobody asks about the job (a closed browser): it is cancelled as abandoned.
        abandoned = wait_state(base, idle["run_id"], ("cancelled",), touch=False, manager=manager)
        assert abandoned["reason"].startswith("abandoned")
        assert_cleaned(abandoned, storage, idle["run_id"])


def test_a_tampered_result_is_refused_by_semantic_checks(tmp_path):
    with running_service(tmp_path) as (base, _manager, storage):
        _s, job = jcall(base, "/api/v1/runs", request(token="test-fault:tamper_run_json"))
        refused = wait_state(base, job["run_id"], ("failed", "completed"))
        assert refused["state"] == "failed"
        assert "result refused" in refused["reason"] and "science wavelength" in refused["reason"]
        assert call(base, f"/api/v1/runs/{job['run_id']}/files/run.json")[0] == 409
        assert not (storage / "runs" / job["run_id"]).exists()


def test_faults_are_ignored_unless_enabled(tmp_path):
    with running_service(tmp_path, enable_test_faults=False) as (base, _manager, _storage):
        _s, job = jcall(base, "/api/v1/runs", request(token="test-fault:fail_at:start"))
        assert wait_state(base, job["run_id"], ("completed", "failed"))["state"] == "completed"


def raw_request(base, data: bytes) -> bytes:
    """Send bytes over a plain socket (for malformed headers urllib refuses to send)."""

    import socket
    from urllib.parse import urlsplit

    parts = urlsplit(base)
    with socket.create_connection((parts.hostname, parts.port), timeout=10) as sock:
        # The service may answer and close before reading a refused body.
        try:
            sock.sendall(data)
            sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        chunks = []
        try:
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        except OSError:
            pass
    return b"".join(chunks)


def test_request_bounds_hosts_and_origins_are_enforced(tmp_path):
    with running_service(tmp_path) as (base, manager, _storage):
        host = base.split("//")[1]
        body = b'{"pad": "' + b"x" * (3 * 1024 * 1024) + b'"}'
        answer = raw_request(base, b"POST /api/v1/runs HTTP/1.1\r\nHost: " + host.encode() + b"\r\nContent-Type: application/json\r\nContent-Length: -1\r\n\r\n" + body)
        assert answer.startswith(b"HTTP/1.0 411") or answer.startswith(b"HTTP/1.1 411"), answer[:80]
        answer = raw_request(base, b"POST /api/v1/runs HTTP/1.1\r\nHost: " + host.encode() + b"\r\nContent-Type: application/json\r\n\r\n{}")
        assert b" 411 " in answer.split(b"\r\n")[0]
        answer = raw_request(base, b"POST /api/v1/runs HTTP/1.1\r\nHost: " + host.encode() + b"\r\nContent-Type: application/json\r\nContent-Length: 70000\r\n\r\n{}")
        assert b" 413 " in answer.split(b"\r\n")[0]
        # DNS rebinding: a foreign Host name is not answered.
        assert call(base, "/api/v1/info", headers={"Host": "attacker.example"})[0] == 421
        # Writes from an unlisted origin are refused, even as a "simple" request.
        _s, job = jcall(base, "/api/v1/runs", request(token="test-fault:sleep_at:start"))
        assert call(base, f"/api/v1/runs/{job['run_id']}/cancel", raw=b"", headers={"Content-Type": "text/plain"})[0] == 415
        assert call(base, f"/api/v1/runs/{job['run_id']}/cancel", {}, headers={"Origin": "https://evil.example"})[0] == 403
        assert call(base, "/api/v1/runs", request(), headers={"Origin": "https://evil.example"})[0] == 403
        status, cancelled = jcall(base, f"/api/v1/runs/{job['run_id']}/cancel", {"reason": "visitor"}, headers={"Origin": "https://pages.example"})
        assert status == 200 and cancelled["state"] == "cancelled"
        assert call(base, f"/api/v1/runs/{job['run_id']}/cancel", {"reason": "<script>"})[0] == 422
        # Same-origin pages served by the service may write.
        _s, other = jcall(base, "/api/v1/runs", request(token="test-fault:sleep_at:start"), headers={"Origin": base})
        assert jcall(base, f"/api/v1/runs/{other['run_id']}/cancel", {}, headers={"Origin": base})[0] == 200


def test_job_history_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "MAX_JOB_RECORDS", 2)
    with running_service(tmp_path) as (base, manager, _storage):
        ids = []
        for _ in range(4):
            _s, job = jcall(base, "/api/v1/runs", request(token="test-fault:fail_at:start"))
            ids.append(job["run_id"])
            wait_state(base, job["run_id"], ("failed",))
        assert len(manager.jobs) <= 3 and ids[-1] in manager.jobs and ids[0] not in manager.jobs
        assert call(base, f"/api/v1/runs/{ids[0]}")[0] == 404


def test_a_worker_exits_when_its_supervisor_dies(tmp_path):
    """A hard-killed supervisor leaves no worker running unowned."""

    import signal
    import subprocess
    import sys

    if not Path("/proc/self/stat").is_file():
        pytest.skip("process states are read from /proc")
    worker_path = Path(service.__file__).with_name("worker.py")
    job = tmp_path / "job"
    job.mkdir()
    (job / "request.json").write_text(json.dumps({"run_id": "orphan", "parameters": contract.effective_parameters(request()["parameters"])}))
    parent_code = (
        "import os, subprocess, sys, time\n"
        f"p = subprocess.Popen([sys.executable, {str(worker_path)!r}, '--job-dir', {str(job)!r}], "
        "env={**os.environ, 'AO_DYNAMIC_TEST_FAULT': 'sleep_at:start'}, start_new_session=True, stdout=subprocess.PIPE)\n"
        "print(p.pid, flush=True)\n"
        "p.stdout.readline()\n"
        "print('started', flush=True)\n"
        "time.sleep(600)\n"
    )
    parent = subprocess.Popen([sys.executable, "-c", parent_code], stdout=subprocess.PIPE, text=True)
    worker_pid = int(parent.stdout.readline())
    assert parent.stdout.readline().strip() == "started"
    parent.send_signal(signal.SIGKILL)
    parent.wait()

    def running(pid):
        try:
            state = Path(f"/proc/{pid}/stat").read_text().split(")")[-1].split()[0]
        except OSError:
            return False
        return state not in ("Z", "X")

    deadline = time.monotonic() + 10
    while running(worker_pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    alive = running(worker_pid)
    if alive:
        os.kill(worker_pid, 9)
    assert not alive, "the worker kept running after its supervisor was killed"


def test_a_slow_but_steady_client_receives_a_whole_file(tmp_path, monkeypatch):
    """The socket timeout bounds stalls, not a whole download (review R2-F01)."""

    import socket
    from urllib.parse import urlsplit

    monkeypatch.setattr(service.Handler, "timeout", 1.0)
    original_setup = service.Handler.setup

    def small_send_buffer(self):
        # Small kernel buffers, so the transfer is paced by the reader as on a slow link.
        self.request.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 16 * 1024)
        original_setup(self)

    monkeypatch.setattr(service.Handler, "setup", small_send_buffer)
    with running_service(tmp_path) as (base, _manager, _storage):
        _s, job = jcall(base, "/api/v1/runs", request())
        done = wait_state(base, job["run_id"], ("completed", "failed"))
        assert done["state"] == "completed"
        expected = done["files"]["frames.bin"]
        assert expected["bytes"] > 2_000_000
        parts = urlsplit(base)
        started = time.monotonic()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16 * 1024)
            sock.settimeout(10)
            sock.connect((parts.hostname, parts.port))
            sock.sendall(f"GET /api/v1/runs/{job['run_id']}/files/frames.bin HTTP/1.1\r\nHost: {parts.netloc}\r\n\r\n".encode())
            received = bytearray()
            while True:
                chunk = sock.recv(16 * 1024)
                if not chunk:
                    break
                received += chunk
                time.sleep(0.015)  # at most about 1 MB/s: the whole file takes longer than the timeout
        elapsed = time.monotonic() - started
        header, _, body = bytes(received).partition(b"\r\n\r\n")
        assert header.startswith(b"HTTP/1.0 200") or header.startswith(b"HTTP/1.1 200")
        assert elapsed > 1.0, f"the transfer took {elapsed:.2f} s; the test needs one longer than the timeout"
        assert len(body) == expected["bytes"] and contract.sha256_bytes(body) == expected["sha256"]
        # A response interrupted mid-body is never followed by a second (error) response.
        assert b"ao-dynamic.error.v1" not in body
