"""The page's contract module refuses what the Python contract refuses (run under Node)."""

from __future__ import annotations

import json
import math
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import numpy as np
import pytest

import contract


ROOT = Path(__file__).resolve().parents[2]


def _code_dir() -> Path:
    dirs = sorted((ROOT / "web" / "ao-explorer").glob("code-*"))
    assert len(dirs) == 1
    return dirs[0]


def _status(run):
    """A completed status as the service would report it for this record."""

    return {
        "schema": contract.STATUS_SCHEMA, "api": contract.API_VERSION, "run_id": "run-20261023T120000Z-0123abcd",
        "state": "completed", "seed": run["effective"]["parameters"]["seed"], "seed_source": "specified",
        "parameters": run["effective"]["parameters"], "physical_identity": run["effective"]["physical_identity"],
        "client_token": None, "created_utc": "x", "started_utc": "x", "finished_utc": "x", "queue_position": None,
        "progress": {"frames_done": 16, "n_frames": 16, "physical_time_s": 0.015, "stage": "completed", "fraction": 1.0},
        "computation_wall_s": 2.0, "admission": {}, "admission_sha256": "0" * 64, "cancel_requested": False, "reason": None,
        "files": {name: {"href": f"files/{name}", "bytes": 1, "sha256": "a" * 64} for name in contract.RUN_FILES},
        "evicted": False, "worker": {},
    }


def test_page_contract_matches_python_rules(fixture_runs, tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not available")
    import render
    import service

    manager = SimpleNamespace(max_queue=3, job_timeout_s=240.0, abandon_after_s=300.0, max_runs_kept=8, threads=2)
    info = service.build_info(manager, "fixture", "fixture", [])
    opd_values = [-2e-6, -1.15e-6, -3e-7, 0.0, 1e-9, 4.99e-7, 1.15e-6, 3e-6]
    limit = 1.15e-6
    mask = np.ones(len(opd_values), dtype=bool)
    opd_codes = render.opd_codes(np.asarray(opd_values), mask, limit)[0].tolist()
    peak = 0.0306
    psf_values = [0.0, 1e-12, 3.06e-6, 3.06e-5, 1e-3, 0.0306, 0.5]
    psf_codes = render.psf_codes(np.asarray(psf_values), peak)[0].tolist()
    fixture = {
        "run": fixture_runs["stride1"],
        "run_stride5": fixture_runs["stride5"],
        "expected": contract.effective_parameters(fixture_runs["params"]),
        "info": json.loads(json.dumps(info)),
        "wind": [[s, d, *contract.wind_vector(s, d)] for s in (0.0, 7.5, 10.0) for d in (0, 30, 90, 135, 180, 270, 359)],
        "transported": [[n, s, contract.transported_indices(n, s)] for n, s in ((16, 1), (16, 5), (17, 5), (180, 3), (400, 2))],
        "phase": [[opd, lam, 2 * math.pi * opd / lam] for opd in (1e-7, -3.3e-7, 0.0) for lam in contract.PHASE_DISPLAY_WAVELENGTHS_M],
        "opd_codes": [[v, limit, c] for v, c in zip(opd_values, opd_codes)],
        "psf_codes": [[v, peak, c] for v, c in zip(psf_values, psf_codes)],
        "floats": [[v, json.dumps(v)] for v in [0.0, 0.06, 0.3, 5e-07, 0.0001, 1e-05, 10.0, 7.0, 8.5, 0.2, 0.1263371938263465, 29.99, 123456.789, 1e16, 1.5e17, 0.000123, 2.5e-320, 1e-300, 3.0000000000000004]],
        "identities": [[p, contract.physical_identity(p)] for p in (
            contract.effective_parameters(contract.default_parameters()),
            contract.effective_parameters({**contract.default_parameters(), "r0_m": 0.06, "wind_speed_m_per_s": 7.25, "wind_direction_deg": 30,
                                           "guide_ab_magnitude": 8.5, "controller_gain": 0.0, "queued_latency_frames": 0, "seed": 2147483647}),
            contract.effective_parameters({**contract.default_parameters(), "wind_speed_m_per_s": 0.0001, "controller_gain": 1.0, "r0_m": 0.3}),
        )],
        "status": _status(fixture_runs["stride1"]),
    }
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(fixture))
    completed = subprocess.run([node, str(Path(__file__).parent / "browser" / "contract_check.mjs"), str(_code_dir()), str(path)],
                               capture_output=True, text=True, timeout=120)
    assert completed.returncode == 0, completed.stderr[-3000:]
    assert json.loads(completed.stdout.strip().splitlines()[-1])["refused_mutations"] == 18, completed.stdout[-2000:]


def test_generation_code_is_part_of_the_content_addressed_build():
    import site_build

    code = _code_dir()
    assert {"generate.js", "generate-contract.js"} <= set(site_build.CODE_FILES)
    report = site_build.check(ROOT / "web" / "ao-explorer")
    assert report["problems"] == []
    for name in ("generate.js", "generate-contract.js"):
        text = (code / name).read_text()
        for target in __import__("re").findall(r'from "([^"]+)"', text):
            assert target.startswith("./") and (code / target[2:]).is_file(), (name, target)
    app = (code / "app.js").read_text()
    # Static mode never imports the generation code; it is loaded only on connect.
    assert 'import("./generate.js")' in app
    assert 'from "./generate.js"' not in app and 'from "./generate-contract.js"' not in app
