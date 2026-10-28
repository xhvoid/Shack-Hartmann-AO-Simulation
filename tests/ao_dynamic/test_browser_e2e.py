"""Real backend plus real browser: the generated-experiment mode end to end.

Starts the computation service (test faults enabled, small fixture runs) and a
separate static server for the site, then drives headless Chromium through
``browser/e2e.cjs`` (Node Playwright).  Skipped when Node, Playwright or a
Chromium build is unavailable; a skip is never a pass.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

import pytest
from conftest import WEB


ROOT = Path(__file__).resolve().parents[2]
NODE_MODULES = Path(os.environ.get("AO_E2E_NODE_PATH", "/opt/node22/lib/node_modules"))
CHROMIUM = os.environ.get("AO_E2E_CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_http(url: str, timeout: float = 30.0) -> None:
    import urllib.request

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2).read()
            return
        except OSError:
            time.sleep(0.2)
    raise AssertionError(f"{url} did not come up")


def test_generate_mode_end_to_end(tmp_path):
    node = shutil.which("node")
    if node is None or not (NODE_MODULES / "playwright").is_dir() or not Path(CHROMIUM).is_file():
        pytest.skip("Node.js, Playwright or Chromium is not available")
    web_root = tmp_path / "web"
    web_root.mkdir()
    (web_root / "ao-explorer").symlink_to(WEB, target_is_directory=True)
    static_port, service_port = _free_port(), _free_port()
    static_base = f"http://127.0.0.1:{static_port}"
    service_base = f"http://127.0.0.1:{service_port}"
    environment = {**os.environ, "AO_DYNAMIC_QUIET": "1"}
    static = subprocess.Popen([sys.executable, "-m", "http.server", str(static_port), "--bind", "127.0.0.1", "--directory", str(web_root)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    backend = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "ao_dynamic" / "service.py"), "--port", str(service_port), "--storage-dir", str(tmp_path / "storage"),
         "--web-dir", str(web_root), "--allow-origin", static_base, "--enable-test-faults", "--max-runs-kept", "20", "--abandon-after-s", "120"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=environment, cwd=str(ROOT))
    try:
        _wait_http(f"{static_base}/ao-explorer/")
        _wait_http(f"{service_base}/api/v1/info")
        completed = subprocess.run([node, str(Path(__file__).parent / "browser" / "e2e.cjs"), static_base, service_base, str(tmp_path)],
                                   env={**environment, "NODE_PATH": str(NODE_MODULES), "CHROMIUM_EXECUTABLE": CHROMIUM},
                                   capture_output=True, text=True, timeout=900)
        lines = [line for line in completed.stdout.splitlines() if line.startswith("{")]
        result = json.loads(lines[-1]) if lines else {"ok": False}
        assert completed.returncode == 0 and result["ok"], (completed.stdout[-3000:], completed.stderr[-3000:])
        assert len(result["scenarios"]) == 12
        report = os.environ.get("AO_E2E_REPORT")
        if report:
            Path(report).write_text(json.dumps(result, indent=1))
            shutil.copy(tmp_path / "generate-375.png", Path(report).with_suffix(".png"))
    finally:
        for process in (backend, static):
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
