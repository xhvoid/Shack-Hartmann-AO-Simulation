"""Make the explorer's caller-owned scripts importable for their tests.

The scripts under ``scripts/ao_explorer`` import their siblings by module
name (Python puts a script's own directory on ``sys.path`` when it runs);
the tests reproduce that with pytest's monkeypatch-free path hook below
instead of the scripts editing ``sys.path`` themselves.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts" / "ao_explorer"
WEB = ROOT / "web" / "ao-explorer"


@pytest.fixture(autouse=True)
def _explorer_scripts_on_path(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    yield


@pytest.fixture
def scripts_dir():
    return SCRIPTS


@pytest.fixture
def web_dir():
    return WEB


def pytest_configure(config):  # noqa: D401 - pytest hook
    # Module-level imports in the test files need the path before collection.
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
