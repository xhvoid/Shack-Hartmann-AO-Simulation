"""Make the dynamic-mode scripts (and the explorer modules they reuse) importable.

The fixtures here run small deterministic worker jobs (12-24 frames of the
explorer profile) in-process; they exercise the real physical WFS, controller
queue, calibration and native propagator while staying contract fixtures, not
AO studies.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
DYNAMIC = ROOT / "scripts" / "ao_dynamic"
EXPLORER = ROOT / "scripts" / "ao_explorer"
WEB = Path(os.environ.get("AO_EXPLORER_SITE", ROOT / "web" / "ao-explorer")).resolve()


def pytest_collection_modifyitems(items):
    if not WEB.is_dir():
        skip = pytest.mark.skip(reason="set AO_EXPLORER_SITE to the companion website checkout/site")
        for item in items:
            if item.path.name in {"test_frontend_contract.py", "test_browser_e2e.py"}:
                item.add_marker(skip)


def pytest_configure(config):  # noqa: D401 - pytest hook
    for path in (str(EXPLORER), str(DYNAMIC)):
        if path not in sys.path:
            sys.path.insert(0, path)


@pytest.fixture(autouse=True)
def _dynamic_scripts_on_path(monkeypatch):
    monkeypatch.syspath_prepend(str(EXPLORER))
    monkeypatch.syspath_prepend(str(DYNAMIC))
    yield


def run_worker(job_dir: Path, parameters: dict, *, run_id: str = "fixture", observer: bool = True) -> dict:
    import contract
    import worker

    job_dir.mkdir(parents=True, exist_ok=True)
    request = {"run_id": run_id, "created_utc": "fixture", "seed_source": "specified",
               "parameters": contract.effective_parameters(parameters)}
    (job_dir / "request.json").write_text(json.dumps(request))
    return worker.run(job_dir, observer_enabled=observer)


def fixture_parameters(**changes) -> dict:
    import contract

    parameters = contract.default_parameters()
    parameters.update(n_frames=16, burn_in=6, display_stride=1)
    parameters.update(changes)
    return parameters


@pytest.fixture(scope="session")
def fixture_runs(tmp_path_factory):
    """Observed runs with display stride 1 and 5, and the observer-disabled control (16 frames, burn-in 6)."""

    root = tmp_path_factory.mktemp("dynamic-fixture")
    params = fixture_parameters()
    stride1 = run_worker(root / "stride1", params, run_id="fixture-stride1")
    stride5 = run_worker(root / "stride5", dict(params, display_stride=5), run_id="fixture-stride5")
    control = run_worker(root / "control", params, run_id="fixture-control", observer=False)
    yield {"root": root, "params": params, "stride1": stride1, "stride5": stride5, "control": control}
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def web_dir():
    return WEB
