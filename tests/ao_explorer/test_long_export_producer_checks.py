"""The one-second exporter judges the producer's record checks by the validator's rule (engineering closeout).

Tiny synthetic records only: a synthetic eight-case series directory with one small file per attempt, read by
``long_export.bind_cases`` and ``long_export.case_validation``.  No producer, AO computation, export or site build
runs; the science entry points raise if anything reaches them.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest

import long_export
import long_series
import web_contract


EXPECTED = web_contract.V2.producer_checks
WINDOW = [long_series.STARTUP_EXCLUSION_FRAMES, long_series.N_STEPS]
COUNT = long_series.N_STEPS - long_series.STARTUP_EXCLUSION_FRAMES


@pytest.fixture(autouse=True)
def _no_science(monkeypatch):
    import shwfs_ao.control.loop
    import shwfs_ao.experiments.detector_level
    import shwfs_ao.experiments.scao

    originals = (
        shwfs_ao.experiments.detector_level.science_run,
        shwfs_ao.experiments.scao.build_scao_system,
        shwfs_ao.experiments.scao.run_closed_loop,
        shwfs_ao.control.loop.run_closed_loop,
    )

    def forbidden(*_, **__):
        raise AssertionError("an exporter test reached a production or science entry point")

    monkeypatch.setattr(long_series, "run_case", forbidden)

    # Every loaded reference, import-time aliases included (``from .scao import build_scao_system`` and the like).
    for module in [module for name, module in list(sys.modules.items()) if name == "shwfs_ao" or name.startswith("shwfs_ao.")]:
        for name, value in list(vars(module).items()):
            if any(value is original for original in originals):
                monkeypatch.setattr(module, name, forbidden)


def conforming_checks() -> dict:
    """A checks mapping with exactly the producer's fields: required checks true, the window, zero diagnostics."""

    checks = {}
    for name in EXPECTED.recorded:
        if name in EXPECTED.required_true:
            checks[name] = True
        elif name == EXPECTED.window_fields[0]:
            checks[name] = list(WINDOW)
        elif name == EXPECTED.window_fields[1]:
            checks[name] = COUNT
        else:
            checks[name] = {key: 0.0 for key in EXPECTED.diagnostics[name][0]}
    return checks


def _loose(checks) -> bool:
    """The exporter's former filter: only the booleans present, by truthiness."""

    return all(value for value in checks.values() if isinstance(value, bool))


FIRST = EXPECTED.required_true[0]
DIAGNOSTIC = next(iter(EXPECTED.diagnostics))
ABSOLUTE = next(name for name, (_, absolute) in EXPECTED.diagnostics.items() if absolute)


def _without(name):
    return lambda checks: checks.pop(name)


def _assign(name, value):
    return lambda checks: checks.__setitem__(name, value)


def _diagnostic(name, value):
    return lambda checks: checks[name].__setitem__(EXPECTED.diagnostics[name][0][0], value)


# (name, change, the problem field it must set, whether the former filter accepted it)
DEFECTS = [
    ("required-check-missing", _without(FIRST), "not_true", True),
    ("required-check-string-false", _assign(FIRST, "false"), "not_true", True),
    ("required-check-string-true", _assign(FIRST, "true"), "not_true", True),
    ("required-check-null", _assign(FIRST, None), "not_true", True),
    ("required-check-zero", _assign(FIRST, 0), "not_true", True),
    ("required-check-one", _assign(FIRST, 1), "not_true", True),
    ("required-check-false", _assign(FIRST, False), "not_true", False),
    ("unexpected-field", _assign("extra_check", True), "unexpected", True),
    ("window-short", _assign(EXPECTED.window_fields[0], [WINDOW[0], WINDOW[1] - 1]), "frames_wrong", True),
    ("window-floats", _assign(EXPECTED.window_fields[0], [float(WINDOW[0]), float(WINDOW[1])]), "frames_wrong", True),
    ("window-missing", _without(EXPECTED.window_fields[0]), "frames_wrong", True),
    ("count-float", _assign(EXPECTED.window_fields[1], float(COUNT)), "count_wrong", True),
    ("count-bool", _assign(EXPECTED.window_fields[1], True), "count_wrong", True),
    ("count-wrong", _assign(EXPECTED.window_fields[1], COUNT - 1), "count_wrong", True),
    ("diagnostic-nan", _diagnostic(DIAGNOSTIC, float("nan")), "diagnostics", True),
    ("diagnostic-string", _diagnostic(DIAGNOSTIC, "0.0"), "diagnostics", True),
    ("diagnostic-negative-deviation", _diagnostic(ABSOLUTE, -1e-18), "diagnostics", True),
    ("diagnostic-keys", _assign(DIAGNOSTIC, {"other": 0.0}), "diagnostics", True),
]


def test_a_conforming_record_passes_every_reader():
    checks = conforming_checks()
    assert web_contract.producer_check_problems(checks, EXPECTED, tuple(WINDOW), COUNT).ok
    assert long_export.producer_check_problems(checks).ok and long_export.case_validation({"observer": {"checks": checks}}) == {"producer_checks_passed": True}


@pytest.mark.parametrize("name,change,field,loose_accepted", DEFECTS, ids=[item[0] for item in DEFECTS])
def test_the_exporter_refuses_what_the_validator_refuses(name, change, field, loose_accepted):
    checks = conforming_checks()
    change(checks)
    problems = long_export.producer_check_problems(checks)
    assert not problems.ok and getattr(problems, field), problems
    assert problems == web_contract.producer_check_problems(checks, EXPECTED, tuple(WINDOW), COUNT)  # one rule
    assert long_export.case_validation({"observer": {"checks": checks}}) == {"producer_checks_passed": False}
    # The former truthiness filter, kept here only as the control: it saw no problem in these records.
    assert _loose(checks) is loose_accepted


@pytest.mark.parametrize("value", [None, [], "checks", 1])
def test_a_checks_record_that_is_not_an_object_is_refused(value):
    problems = long_export.producer_check_problems(value)
    assert not problems.ok and problems.kind == type(value).__name__
    assert long_export.case_validation({"observer": {"checks": value}}) == {"producer_checks_passed": False}


# bind_cases on a tiny synthetic series directory (eight attempts, one 8-byte file each)


def _write_series(root: Path, *, change=None, changed_case="lower-gain") -> tuple[Path, dict]:
    production = "p" * 64
    plan = {"series_id": "synthetic-series", "identities": {"production": {"sha256": production}},
            "cases": [{"case_id": case_id, "config_hash": f"{index:064x}", "admission_sha256": f"{index + 100:064x}"} for index, case_id in enumerate(long_series.CASE_ORDER)]}
    for index, case_id in enumerate(long_series.CASE_ORDER):
        attempt = root / "cases" / case_id / "attempt-01"
        attempt.mkdir(parents=True)
        (attempt / "status.json").write_text(json.dumps({"status": "COMPLETED"}))
        data = case_id.encode()[:8].ljust(8, b".")
        (attempt / "tiny.bin").write_bytes(data)
        checks = conforming_checks()
        if change is not None and case_id == changed_case:
            change(checks)
        record = {"series_id": "synthetic-series", "case": {"case_id": case_id}, "config_hash": f"{index:064x}", "admission_sha256": f"{index + 100:064x}",
                  "identities": {"production_sha256": production}, "observer": {"checks": checks},
                  "screen": {"generated_screen_px": long_series.SCREEN_GRID_SIZE, "option": {"screen_grid_size": long_series.SCREEN_GRID_SIZE}},
                  "files": {"tiny.bin": {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}}}
        (attempt / "case_record.json").write_text(json.dumps(record))
    return root, plan


def test_bind_cases_accepts_conforming_synthetic_records(tmp_path):
    series, plan = _write_series(tmp_path / "series")
    cases = long_export.bind_cases(series, plan)
    assert list(cases) == list(long_series.CASE_ORDER)
    assert all(long_export.case_validation(bound["record"]) == {"producer_checks_passed": True} for bound in cases.values())


@pytest.mark.parametrize("name,change,field,loose_accepted", DEFECTS, ids=[item[0] for item in DEFECTS])
def test_bind_cases_refuses_a_record_the_validator_would_refuse(tmp_path, name, change, field, loose_accepted):
    series, plan = _write_series(tmp_path / "series", change=change)
    checks = conforming_checks()
    change(checks)
    problems = long_export.producer_check_problems(checks)
    # A field that is missing or unexpected is a contract problem first, even when it is the window's.
    window_only = not (problems.missing or problems.unexpected or problems.not_true or problems.diagnostics)
    reason = "the analysis window is not" if window_only else "the production record checks do not meet the producer's contract"
    with pytest.raises(long_export.LongExportError, match=f"lower-gain: {reason}"):
        long_export.bind_cases(series, plan)
