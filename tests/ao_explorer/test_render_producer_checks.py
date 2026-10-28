"""The 180-frame exporter judges the producer's record checks by the validator's rule (offline cleanup).

Tiny synthetic records only: a synthetic series directory with one small job record per job, read by
``render.bind_case_records``, ``render.case_validation`` and the web stage's refusal path.  No producer, AO
computation, derivation, export or site build runs; the science entry points raise if anything reaches them.  The
export-identity checks use disposable copies of the exporter sources under pytest's temporary directory; their
semantic checks run in isolated child interpreters (``python -I -B``) that import the copy's modules.

The expected contract is written out from ``producer.run_job`` and ``ExplorerObserver.finish`` by hand (the oracle);
the synthetic records are built from the oracle, never from the parsed contract.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

import identity
import long_series
import protocol
import render
import web_contract


SCRIPTS = Path(identity.EXPORTER_DIR)
SRC = SCRIPTS.parents[1] / "src"
SERIES = "synthetic-v1-series"
WINDOW = (protocol.PRODUCTION_BURN_IN, protocol.PRODUCTION_FRAMES)
COUNT = WINDOW[1] - WINDOW[0]
PILOT_WINDOW = (protocol.PILOT_BURN_IN, protocol.PILOT_FRAMES)
PILOT_COUNT = PILOT_WINDOW[1] - PILOT_WINDOW[0]

# The oracle: producer.run_job records these checks, in this order; the bool/all verdicts; the dict diagnostics
# (keys, every value an absolute deviation); the per-display-frame list (keys, the absolute-deviation keys).
ORACLE_RECORDED = (
    "atmosphere_rms_matches_history", "residual_rms_matches_history", "times_match_history", "usable_matches_history",
    "saturation_matches_history", "display_frame_independent_reductions", "display_frame_reductions_within_tolerance",
    "streaming_max_abs_difference", "streaming_within_tolerance", "instantaneous_unit_flux", "mean_unit_flux",
)
ORACLE_REQUIRED_TRUE = (
    "atmosphere_rms_matches_history", "residual_rms_matches_history", "times_match_history", "usable_matches_history",
    "saturation_matches_history", "display_frame_reductions_within_tolerance", "streaming_within_tolerance", "instantaneous_unit_flux",
)
ORACLE_DIAGNOSTICS = {
    "streaming_max_abs_difference": (("uncorrected", "corrected"), True),
    "mean_unit_flux": (("uncorrected", "corrected"), False),
}
ORACLE_RECORD_LISTS = {
    "display_frame_independent_reductions": (
        ("frame", "atmosphere_rms_abs_error_m", "residual_rms_abs_error_m", "uncorrected_strehl_abs_error", "corrected_strehl_abs_error",
         "held_correction_identity_max_abs_m"),
        ("atmosphere_rms_abs_error_m", "residual_rms_abs_error_m", "uncorrected_strehl_abs_error", "corrected_strehl_abs_error",
         "held_correction_identity_max_abs_m"),
    ),
}
ORACLE_WINDOW_FIELDS = ("burn_in", "n_steps")


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


def conforming_checks(frames=(0, 8, 16)) -> dict:
    """A checks mapping with exactly the producer's fields: verdicts true, zero diagnostics, one record per frame."""

    checks = {}
    for name in ORACLE_RECORDED:
        if name in ORACLE_REQUIRED_TRUE:
            checks[name] = True
        elif name in ORACLE_DIAGNOSTICS:
            checks[name] = {key: 0.0 for key in ORACLE_DIAGNOSTICS[name][0]}
        else:
            keys = ORACLE_RECORD_LISTS[name][0]
            checks[name] = [{key: (frame if key == "frame" else 0.0) for key in keys} for frame in frames]
    return checks


_CONFORMING = object()


def record_for(job_id: str, *, window=WINDOW, role="production", checks=_CONFORMING) -> dict:
    return {
        "schema": protocol.JOB_RECORD_SCHEMA, "series_id": SERIES,
        "job": {"job_id": job_id, "role": role, "case_id": job_id.split("-", 1)[1], "n_steps": window[1], "burn_in": window[0]},
        "observer": {"checks": conforming_checks() if checks is _CONFORMING else checks},
    }


def _loose(checks) -> bool:
    """The exporter's former filter: only the booleans present, by truthiness."""

    return all(value for value in checks.values() if isinstance(value, bool))


FIRST = ORACLE_REQUIRED_TRUE[0]
ABSOLUTE_DIAGNOSTIC = "streaming_max_abs_difference"
PLAIN_DIAGNOSTIC = "mean_unit_flux"
RECORD_LIST = "display_frame_independent_reductions"


def _without(name):
    return lambda checks: checks.pop(name)


def _assign(name, value):
    return lambda checks: checks.__setitem__(name, value)


def _diagnostic(name, key, value):
    return lambda checks: checks[name].__setitem__(key, value)


def _record(index, key, value):
    return lambda checks: checks[RECORD_LIST][index].__setitem__(key, value)


# (name, change to the checks mapping, the problem field it must set, whether the former filter accepted it)
DEFECTS = [
    ("required-check-false", _assign(FIRST, False), "not_true", False),
    ("required-check-string-false", _assign(FIRST, "false"), "not_true", True),
    ("required-check-string-true", _assign(FIRST, "true"), "not_true", True),
    ("required-check-one", _assign(FIRST, 1), "not_true", True),
    ("required-check-zero", _assign(FIRST, 0), "not_true", True),
    ("required-check-null", _assign(FIRST, None), "not_true", True),
    ("required-check-missing", _without(FIRST), "not_true", True),
    ("last-required-check-false", _assign(ORACLE_REQUIRED_TRUE[-1], False), "not_true", False),
    ("empty-checks-mapping", lambda checks: checks.clear(), "not_true", True),
    ("unexpected-field", _assign("operator_override", True), "unexpected", True),
    ("diagnostic-nan", _diagnostic(ABSOLUTE_DIAGNOSTIC, "corrected", float("nan")), "diagnostics", True),
    ("diagnostic-string", _diagnostic(PLAIN_DIAGNOSTIC, "uncorrected", "1.0"), "diagnostics", True),
    ("diagnostic-null", _diagnostic(PLAIN_DIAGNOSTIC, "corrected", None), "diagnostics", True),
    ("diagnostic-boolean", _diagnostic(PLAIN_DIAGNOSTIC, "corrected", True), "diagnostics", True),
    ("diagnostic-negative-deviation", _diagnostic(ABSOLUTE_DIAGNOSTIC, "uncorrected", -1e-18), "diagnostics", True),
    ("diagnostic-keys", _assign(ABSOLUTE_DIAGNOSTIC, {"other": 0.0}), "diagnostics", True),
    ("diagnostic-type", _assign(PLAIN_DIAGNOSTIC, 1.0), "diagnostics", True),
    ("record-list-not-a-list", _assign(RECORD_LIST, {"frame": 0}), "diagnostics", True),
    ("record-list-empty", _assign(RECORD_LIST, []), "diagnostics", True),
    ("record-list-record-keys", _assign(RECORD_LIST, [{"frame": 0}]), "diagnostics", True),
    ("record-list-record-type", _assign(RECORD_LIST, [0.0]), "diagnostics", True),
    ("record-list-negative-deviation", _record(1, "residual_rms_abs_error_m", -1e-18), "diagnostics", True),
    ("record-list-nan", _record(2, "held_correction_identity_max_abs_m", float("nan")), "diagnostics", True),
    ("record-list-frame-boolean", _record(0, "frame", True), "diagnostics", True),
    ("record-list-string", _record(0, "uncorrected_strehl_abs_error", "0.0"), "diagnostics", True),
]

# (name, change to the job record, the window problems it must set)
WINDOW_DEFECTS = [
    ("burn-in-off-by-one", lambda job: job.__setitem__("burn_in", WINDOW[0] - 1), ("frames_wrong", "count_wrong")),
    ("frames-off-by-one", lambda job: job.__setitem__("n_steps", WINDOW[1] - 1), ("frames_wrong", "count_wrong")),
    ("shifted-window-same-count", lambda job: job.update(burn_in=WINDOW[0] + 1, n_steps=WINDOW[1] + 1), ("frames_wrong",)),
    ("pilot-window-in-a-production-record", lambda job: job.update(burn_in=PILOT_WINDOW[0], n_steps=PILOT_WINDOW[1]), ("frames_wrong", "count_wrong")),
    ("burn-in-float", lambda job: job.__setitem__("burn_in", float(WINDOW[0])), ("frames_wrong", "count_wrong")),
    ("frames-float", lambda job: job.__setitem__("n_steps", float(WINDOW[1])), ("frames_wrong", "count_wrong")),
    ("burn-in-boolean", lambda job: job.__setitem__("burn_in", True), ("frames_wrong", "count_wrong")),
    ("frames-string", lambda job: job.__setitem__("n_steps", str(WINDOW[1])), ("frames_wrong", "count_wrong")),
    ("burn-in-missing", lambda job: job.pop("burn_in"), ("frames_wrong", "count_wrong")),
    ("frames-missing", lambda job: job.pop("n_steps"), ("frames_wrong", "count_wrong")),
]


def test_the_v1_contract_is_read_from_the_producer_source():
    contract = web_contract.V1.producer_checks
    assert contract is not None and contract.source == "producer.run_job"
    assert contract.recorded == ORACLE_RECORDED and contract.required_true == ORACLE_REQUIRED_TRUE
    assert contract.window_fields == ORACLE_WINDOW_FIELDS and contract.window_in_checks is False
    assert contract.diagnostics == ORACLE_DIAGNOSTICS and contract.record_lists == ORACLE_RECORD_LISTS
    # The one-second contract keeps its shape: the window in the checks mapping, no record lists.
    assert web_contract.V2.producer_checks.window_in_checks is True and web_contract.V2.producer_checks.record_lists == {}
    assert web_contract.V2.producer_checks.window_fields == ("analysis_frames", "analysis_count")


def test_a_conforming_production_record_passes_every_reader():
    record = record_for("case-baseline")
    problems = web_contract.producer_check_problems(record["observer"]["checks"], web_contract.V1.producer_checks, WINDOW, COUNT, job=record["job"])
    assert problems.ok, problems
    assert render.producer_record_problems(record, window=WINDOW, count=COUNT).ok
    assert render.case_validation(record, window=WINDOW, count=COUNT) == {"producer_checks_passed": True}


def test_a_conforming_pilot_record_passes_on_the_pilot_window_only():
    record = record_for("pilot-baseline", window=PILOT_WINDOW, role="pilot")
    assert render.producer_record_problems(record, window=PILOT_WINDOW, count=PILOT_COUNT).ok
    # The pilot's declared [16, 64) is not the production window: the distinction is kept, not coerced.
    on_production = render.producer_record_problems(record, window=WINDOW, count=COUNT)
    assert not on_production.ok and on_production.frames_wrong and on_production.count_wrong
    assert not (on_production.missing or on_production.unexpected or on_production.not_true or on_production.diagnostics)


@pytest.mark.parametrize("name,change,field,loose_accepted", DEFECTS, ids=[item[0] for item in DEFECTS])
def test_the_exporter_refuses_what_the_validator_rule_refuses(name, change, field, loose_accepted):
    record = record_for("case-baseline")
    change(record["observer"]["checks"])
    problems = render.producer_record_problems(record, window=WINDOW, count=COUNT)
    assert not problems.ok and getattr(problems, field), problems
    assert problems == web_contract.producer_check_problems(record["observer"]["checks"], web_contract.V1.producer_checks, WINDOW, COUNT, job=record["job"])  # one rule
    assert render.case_validation(record, window=WINDOW, count=COUNT) == {"producer_checks_passed": False}
    # The former truthiness filter, kept here only as the control: it saw no problem in most of these records.
    assert _loose(record["observer"]["checks"]) is loose_accepted


@pytest.mark.parametrize("name,change,fields", WINDOW_DEFECTS, ids=[item[0] for item in WINDOW_DEFECTS])
def test_a_wrong_or_masquerading_window_in_the_job_record_is_refused(name, change, fields):
    record = record_for("case-baseline")
    change(record["job"])
    problems = render.producer_record_problems(record, window=WINDOW, count=COUNT)
    assert not problems.ok and all(getattr(problems, field) for field in fields), problems
    assert not (problems.missing or problems.unexpected or problems.not_true or problems.diagnostics)
    assert render.case_validation(record, window=WINDOW, count=COUNT) == {"producer_checks_passed": False}
    assert _loose(record["observer"]["checks"])  # the window was never judged by the former filter


@pytest.mark.parametrize("value", [None, [], "checks", 1, True])
def test_a_checks_record_that_is_not_an_object_is_refused(value):
    record = record_for("case-baseline", checks=value)
    problems = render.producer_record_problems(record, window=WINDOW, count=COUNT)
    assert not problems.ok and problems.kind == type(value).__name__
    assert render.case_validation(record, window=WINDOW, count=COUNT) == {"producer_checks_passed": False}


@pytest.mark.parametrize("name,mutate", [
    ("observer-missing", lambda record: record.pop("observer")),
    ("observer-not-an-object", lambda record: record.__setitem__("observer", "checks")),
    ("job-not-an-object", lambda record: record.__setitem__("job", list(WINDOW))),
    ("job-missing", lambda record: record.pop("job")),
])
def test_a_malformed_job_record_is_refused(name, mutate):
    record = record_for("case-baseline")
    mutate(record)
    problems = render.producer_record_problems(record, window=WINDOW, count=COUNT)
    assert not problems.ok, problems
    assert render.case_validation(record, window=WINDOW, count=COUNT) == {"producer_checks_passed": False}


def test_a_record_that_is_not_an_object_is_refused():
    for record in (None, [], "record"):
        problems = render.producer_record_problems(record, window=WINDOW, count=COUNT)
        assert not problems.ok and problems.kind == "NoneType"


# bind_case_records and the web stage on a tiny synthetic series directory (one small record per job)


def _write_series(root: Path, *, change=None, changed_job="case-lower-gain", mutate_record=None, plan_window=WINDOW) -> tuple[Path, dict]:
    jobs = []
    for job in protocol.production_jobs():
        job = dict(job)
        if job["role"] == "production":
            job["burn_in"], job["n_steps"] = plan_window
        jobs.append(job)
    plan = {"series_id": SERIES, "state": "FROZEN", "jobs": jobs}
    root.mkdir(parents=True)
    (root / "series_plan.json").write_text(json.dumps(plan))
    for job in jobs:
        attempt = root / "jobs" / job["job_id"] / "attempt-01"
        attempt.mkdir(parents=True)
        (attempt / "status.json").write_text(json.dumps({"status": "COMPLETED", "job_id": job["job_id"]}))
        record = record_for(job["job_id"], window=(job["burn_in"], job["n_steps"]), role=job["role"])
        if job["job_id"] == changed_job:
            if change is not None:
                change(record["observer"]["checks"])
            if mutate_record is not None:
                mutate_record(record)
        (attempt / "job_record.json").write_text(json.dumps(record))
    return root, plan


def test_bind_case_records_accepts_conforming_synthetic_records(tmp_path):
    series, plan = _write_series(tmp_path / "series")
    bound = render.bind_case_records(series, plan)
    assert list(bound) == [f"case-{case['id']}" for case in protocol.CASES]
    assert all(entry["validation"] == {"producer_checks_passed": True} for entry in bound.values())
    assert all(entry["attempt"] == series / "jobs" / job_id / "attempt-01" for job_id, entry in bound.items())
    assert not (series / "derived").exists() and sorted(p.name for p in series.iterdir()) == ["jobs", "series_plan.json"]


@pytest.mark.parametrize("name,change,field,loose_accepted", DEFECTS, ids=[item[0] for item in DEFECTS])
def test_bind_case_records_refuses_a_record_the_validator_rule_would_refuse(tmp_path, name, change, field, loose_accepted):
    series, plan = _write_series(tmp_path / "series", change=change)
    with pytest.raises(render.RenderError, match="case-lower-gain: the production record checks do not meet the producer's contract"):
        render.bind_case_records(series, plan)


@pytest.mark.parametrize("name,change,fields", WINDOW_DEFECTS, ids=[item[0] for item in WINDOW_DEFECTS])
def test_bind_case_records_refuses_a_record_whose_window_is_not_the_contracts(tmp_path, name, change, fields):
    series, plan = _write_series(tmp_path / "series", mutate_record=lambda record: change(record["job"]))
    with pytest.raises(render.RenderError, match=rf"case-lower-gain: the record's analysis window is not \[{WINDOW[0]}, {WINDOW[1]}\) with {COUNT} frames"):
        render.bind_case_records(series, plan)


def test_bind_case_records_refuses_a_plan_whose_production_window_is_not_the_contracts(tmp_path):
    series, plan = _write_series(tmp_path / "series", plan_window=PILOT_WINDOW)
    with pytest.raises(render.RenderError, match=rf"case-baseline: the plan's window \[{PILOT_WINDOW[0]}, {PILOT_WINDOW[1]}\) is not the v1 contract's \[{WINDOW[0]}, {WINDOW[1]}\)"):
        render.bind_case_records(series, plan)


def test_bind_case_records_refuses_a_job_without_a_completed_attempt(tmp_path):
    series, plan = _write_series(tmp_path / "series")
    (series / "jobs" / "case-baseline" / "attempt-01" / "status.json").write_text(json.dumps({"status": "STARTED"}))
    with pytest.raises(render.RenderError, match="case-baseline has no completed attempt"):
        render.bind_case_records(series, plan)


@pytest.fixture
def inert_site(monkeypatch):
    # The web stage first checks the page code's content build; here no site exists, so that check is replaced by an
    # inert answer.  Nothing else of the web stage is replaced: it must stop at the records before deriving or writing.
    import site_build

    monkeypatch.setattr(site_build, "check", lambda web_dir, *, entry=True: {"problems": [], "build": "0" * 16})


def test_the_web_stage_refuses_a_defective_record_before_writing_anything(tmp_path, inert_site):
    series, _ = _write_series(tmp_path / "series", change=_assign(FIRST, "true"))
    web = tmp_path / "web"
    web.mkdir()
    with pytest.raises(render.RenderError, match="case-lower-gain: the production record checks do not meet the producer's contract"):
        render.command_web(series, web)
    assert sorted(p.name for p in web.iterdir()) == [] and not (series / "derived").exists()
    assert sorted(p.name for p in series.iterdir()) == ["jobs", "series_plan.json"]


def test_the_web_stage_passes_conforming_records_on_to_its_next_check(tmp_path, inert_site):
    # Control: conforming records are not what stops the stage; it then asks for derived observations, which this
    # synthetic series does not have (no derivation runs here), and still writes nothing.
    series, _ = _write_series(tmp_path / "series")
    web = tmp_path / "web"
    web.mkdir()
    with pytest.raises(render.RenderError, match="no derived observations for the current observation code"):
        render.command_web(series, web)
    assert sorted(p.name for p in web.iterdir()) == [] and not (series / "derived").exists()


def test_the_web_stage_main_reports_the_refusal_without_a_dataset(tmp_path, inert_site, capsys):
    series, _ = _write_series(tmp_path / "series", change=_assign(RECORD_LIST, []))
    web = tmp_path / "web"
    web.mkdir()
    assert render.main(["web", "--series-dir", str(series), "--web-dir", str(web)]) == 3
    answer = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert answer["status"] == "REFUSED" and answer["stage"] == "web" and "case-lower-gain" in answer["reason"] and "display_frame_independent_reductions empty" in answer["reason"]
    assert sorted(p.name for p in web.iterdir()) == []


# The export content identity: the rule and the sources it reads for the v1 contract are part of it.


def parsed_sources() -> set:
    """The sources web_contract.py parses, from its own text (its ``with_name`` constants)."""

    tree = ast.parse((SCRIPTS / "web_contract.py").read_text(encoding="utf-8"))
    return {node.args[0].value for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "with_name"
            and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)}


def rule_sources_v1() -> list:
    """The files the shared rule reads for the v1 contract: itself, the two sources it parses for it and
    ``protocol.py``, whose constants are the v1 window (``long_series.py``, parsed for the v2 contract only, cannot
    change what the v1 exporter accepts and is not listed)."""

    return sorted({"web_contract.py", "producer.py", "observer.py", "protocol.py"})


def test_the_rule_parses_the_v1_producer_and_observer_sources():
    assert {"producer.py", "observer.py"} <= parsed_sources()
    assert set(rule_sources_v1()) == {"web_contract.py", "producer.py", "observer.py", "protocol.py"}


def test_the_export_identity_lists_and_hashes_every_v1_rule_source():
    code = render.export_identity()
    for name in rule_sources_v1():
        assert name in render.EXPORT_FILES and code["files"][name] == hashlib.sha256((SCRIPTS / name).read_bytes()).hexdigest(), name
    assert code["sha256"] == identity.file_set_identity(render.EXPORT_FILES)["sha256"]
    # The three identities stay apart: the observation identity (derive stage, which does not read the rule) is
    # unchanged, and the numerical producer identity and the historical derived set are not touched.
    assert render.OBSERVATION_FILES == ("binary_scene.py", "render.py")
    assert render.observation_identity()["sha256"] == identity.file_set_identity(render.OBSERVATION_FILES)["sha256"]
    assert "web_contract.py" not in identity.PRODUCER_FILES and "web_contract.py" not in identity.DERIVED_FILES
    assert identity.DERIVED_FILES == ("binary_scene.py", "render.py", "research.py", "export.py", "validate.py")


def _copy(tmp_path: Path) -> Path:
    copy = tmp_path / "repo" / "scripts" / "ao_explorer"
    copy.mkdir(parents=True)
    for path in SCRIPTS.glob("*.py"):
        shutil.copy2(path, copy / path.name)
    return copy


def _identity_of(copy: Path, monkeypatch) -> dict:
    # The real implementation, pointed at the copy (its Git state is that of a directory outside any repository).
    with monkeypatch.context() as scoped:
        scoped.setattr(identity, "EXPORTER_DIR", copy)
        scoped.setattr(identity, "REPO_ROOT", copy.parents[1])
        return render.export_identity()


@pytest.mark.parametrize("name", rule_sources_v1())
def test_changing_only_one_v1_rule_source_changes_the_export_digest(tmp_path, monkeypatch, name):
    copy = _copy(tmp_path)
    control = _identity_of(copy, monkeypatch)
    assert control["sha256"] == render.export_identity()["sha256"] and control["files"] == render.export_identity()["files"]
    (copy / name).write_bytes((copy / name).read_bytes() + b"\n# a change to this file alone\n")
    changed = _identity_of(copy, monkeypatch)
    assert changed["sha256"] != control["sha256"]
    assert [member for member in changed["files"] if changed["files"][member] != control["files"][member]] == [name]
    (copy / name).write_bytes((SCRIPTS / name).read_bytes())
    assert _identity_of(copy, monkeypatch) == control  # the same bytes give the same identity


CHILD = r'''
import json, sys
copy, src, records_in, out = sys.argv[1:5]
sys.path[:0] = [copy, src]
import render, web_contract
contract = web_contract.V1
window, count = contract.analysis_window, contract.analysis_count
records = json.load(open(records_in))
judged = {name: render.producer_record_problems(record, window=window, count=count).ok for name, record in records.items()}
json.dump({"sha256": render.export_identity()["sha256"], "files": render.export_identity()["files"], "accepted": judged,
           "render_file": render.__file__, "web_contract_file": web_contract.__file__,
           "shwfs_ao_modules": sorted(m for m in sys.modules if m.startswith("shwfs_ao"))}, open(out, "x"))
'''


def _records(tmp_path: Path) -> Path:
    conforming = record_for("case-baseline")
    string_false = record_for("case-baseline")
    string_false["observer"]["checks"][FIRST] = "false"
    path = tmp_path / "records.json"
    path.write_text(json.dumps({"conforming": conforming, "required_check_string_false": string_false}))
    return path


def _child(copy: Path, records: Path, out: Path) -> dict:
    completed = subprocess.run([sys.executable, "-I", "-B", "-c", CHILD, str(copy), str(SRC), str(records), str(out)],
                               capture_output=True, text=True, timeout=300, check=False)
    assert completed.returncode == 0, completed.stderr[-3000:]
    seen = json.loads(out.read_text())
    assert Path(seen["render_file"]).parent == copy and Path(seen["web_contract_file"]).parent == copy  # the copy's exporter and rule
    assert not [m for m in seen["shwfs_ao_modules"] if m.startswith(("shwfs_ao.experiments", "shwfs_ao.control"))], seen["shwfs_ao_modules"]
    return seen


MUTATIONS = {
    # The rule itself: a required check recorded as the string "false" would pass.
    "web_contract.py": ("for name in expected.required_true if checks.get(name) is not True)",
                        "for name in expected.required_true if checks.get(name) is not True and checks.get(name) != \"false\")",
                        {"conforming": True, "required_check_string_false": True}),
    # A source the rule parses: one streaming diagnostic key renamed, so a conforming record no longer conforms.
    "observer.py": ("\"uncorrected\": float(np.max(np.abs(accumulator_uncorrected - own_uncorrected))),",
                    "\"uncorrected_renamed\": float(np.max(np.abs(accumulator_uncorrected - own_uncorrected))),",
                    {"conforming": False, "required_check_string_false": False}),
    # The other parsed source: one verdict renamed in the producer, so the recorded fields no longer match.
    "producer.py": ("checks[\"instantaneous_unit_flux\"] = bool(",
                    "checks[\"instantaneous_unit_flux_renamed\"] = bool(",
                    {"conforming": False, "required_check_string_false": False}),
    # The window source: a changed production burn-in moves the contract's window, so the record's [40, 180) is wrong.
    "protocol.py": ("PRODUCTION_BURN_IN = 40", "PRODUCTION_BURN_IN = 41", {"conforming": False, "required_check_string_false": False}),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_a_rule_change_that_changes_acceptance_changes_the_export_digest(tmp_path, name):
    copy = _copy(tmp_path)
    records = _records(tmp_path)
    control = _child(copy, records, tmp_path / "control.json")
    assert control["accepted"] == {"conforming": True, "required_check_string_false": False}  # the strict rule
    assert control["sha256"] == render.export_identity()["sha256"]
    old, new, accepted = MUTATIONS[name]
    text = (copy / name).read_text(encoding="utf-8")
    assert text.count(old) == 1
    (copy / name).write_text(text.replace(old, new), encoding="utf-8")
    mutated = _child(copy, records, tmp_path / "mutated.json")
    assert mutated["accepted"] == accepted  # the mutation changes what the exporter accepts ...
    assert mutated["sha256"] != control["sha256"]  # ... and the content digest records it
    assert [member for member in mutated["files"] if mutated["files"][member] != control["files"][member]] == [name]
