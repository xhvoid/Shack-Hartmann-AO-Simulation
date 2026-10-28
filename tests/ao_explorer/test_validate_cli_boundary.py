"""The validator's command line on malformed ``time_domain`` containers, and its valid-input controls (review R25-01).

Every test runs the real script, ``scripts/ao_explorer/validate.py``, in a fresh child interpreter (``sys.executable -B``)
on a disposable fixture under pytest's temporary directory: the preserved 180-frame dataset copied behind a synthesized
v1 entry (``test_validate_contracts._v1_fixture``) or a copy of the committed active v2 site (``_copy``).  A defect
replaces a case record's whole ``time_domain`` or one of its fields and is re-hashed coherently through case.json, the
manifest and the entry, so the refusal is the semantic one and never a digest mismatch.  Nothing in the committed tree is
written: the committed entry, manifests and validation records are compared before and after every run.

The child interpreters are guarded by a ``sitecustomize`` module placed first on their ``PYTHONPATH`` (test
instrumentation only; the production script is unchanged): importing ``shwfs_ao.experiments`` or ``shwfs_ao.control``,
the packages holding the science entry points the project's guards protect, raises, and at exit the child records which
``shwfs_ao`` and explorer modules it loaded.  Each run asserts that record exists, names the run's arguments and names no
science module.  A guard in the pytest process alone says nothing about these children.

Scope: the command line always binds the v1 Research Results to the repository tree (``--repo-root``, this checkout), so
the unmodified v1 view keeps the historical research-source digest failures of documents changed by later accepted
commits; the valid-v1 control accepts exit 0 or 1 and requires every failure to be such a research-source failure.  The
committed site preserves no pilot-window (``[16, 64)``) case, so no valid pilot case can be driven through the command
line; the pilot window stays covered at the rule level in ``test_validate_v1_provenance.py``.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

import validate
from test_validate_contracts import DIGEST_FAILURES, _copy, _dataset_dir, _manifest, _member, _update_refs, _v1_fixture, _v2_or_skip, _write_case_member, _write_manifest
from test_validate_v1_provenance import TIME_DOMAIN


SCRIPT = Path(validate.__file__).resolve()
REPO_ROOT = SCRIPT.parents[2]
ABSENT = object()
RESEARCH_SOURCE = "research source "
CONTAINER = "baseline: time domain is an object (recorded {kind})"
NOT_EVALUATED = "baseline: the case time domain's movie indices, movie times and contract fields are evaluated (not evaluated: time_domain is {kind}, not an object)"
WINDOW_NOT_OBJECT = f"baseline: {TIME_DOMAIN} (recorded time_domain is {{kind}}, not an object)"
FRAMES_NOT_READ = "baseline: producer analysis frames are the v1 window [40, 180) (recorded burn_in None, n_steps None)"
COUNT_NOT_READ = "baseline: producer analysis count is the v1 contract's 140 (recorded n_steps - burn_in undefined)"

# Test instrumentation for the child interpreters only: the production script is not changed.
GUARD_SITECUSTOMIZE = textwrap.dedent('''\
    """Science-entry guard of a validator command-line child (test instrumentation; written by the test into PYTHONPATH)."""
    import atexit
    import json
    import os
    import sys

    FORBIDDEN = ("shwfs_ao.experiments", "shwfs_ao.control")


    class _ForbidScienceImports:
        def find_spec(self, name, path=None, target=None):
            if name in FORBIDDEN or any(name.startswith(prefix + ".") for prefix in FORBIDDEN):
                raise ImportError(f"guarded child interpreter: {name} holds science entry points and may not be imported by the validator")
            return None


    sys.meta_path.insert(0, _ForbidScienceImports())


    def _report():
        path = os.environ.get("VALIDATOR_CLI_GUARD_REPORT")
        if path:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"guard": "active", "forbidden": list(FORBIDDEN), "argv": sys.argv,
                           "shwfs_ao_modules": sorted(name for name in sys.modules if name == "shwfs_ao" or name.startswith("shwfs_ao.")),
                           "explorer_modules": sorted(name for name in ("validate", "web_contract", "long_series", "protocol", "producer", "site_build") if name in sys.modules)}, handle)


    atexit.register(_report)
''')
_counter = itertools.count()


def _protected_state(web_dir: Path):
    """What a command-line run must not write: the committed entry, the dataset manifests and the validation records."""

    paths = [web_dir / "data" / "current.json", *sorted((web_dir / "data").glob("*/manifest.json")), *sorted((web_dir / "validation").glob("*"))]
    state = {str(path.relative_to(web_dir)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths if path.is_file()}
    if (REPO_ROOT / ".git").exists():
        status = subprocess.run(["git", "--no-optional-locks", "-C", str(REPO_ROOT), "status", "--porcelain", "--", "web/ao-explorer"], capture_output=True, text=True)
        state["git status -- web/ao-explorer"] = status.stdout if status.returncode == 0 else f"unavailable ({status.returncode})"
    return state


@pytest.fixture(autouse=True)
def _protected_unchanged(web_dir):
    before = _protected_state(web_dir)
    yield
    assert _protected_state(web_dir) == before, "a command-line run changed committed website state"


def _run_cli(tmp_path: Path, site: Path, *extra: str, repo_root: Path = REPO_ROOT):
    """The real command line in a guarded child; returns the completed process and the child's guard report."""

    guard_dir = tmp_path / "child-guard"
    guard_dir.mkdir(exist_ok=True)
    (guard_dir / "sitecustomize.py").write_text(GUARD_SITECUSTOMIZE, encoding="utf-8")
    report_path = tmp_path / f"guard-report-{next(_counter)}.json"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(guard_dir) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["VALIDATOR_CLI_GUARD_REPORT"] = str(report_path)
    env.pop("PYTHONSAFEPATH", None)
    argv = [sys.executable, "-B", str(SCRIPT), "--web-dir", str(site), "--repo-root", str(repo_root), *extra]
    completed = subprocess.run(argv, capture_output=True, text=True, cwd=str(tmp_path), env=env)
    assert report_path.is_file(), "the child interpreter did not run under the sitecustomize guard"
    guard = json.loads(report_path.read_text(encoding="utf-8"))
    assert guard["guard"] == "active" and guard["argv"] == argv[2:]
    assert not [name for name in guard["shwfs_ao_modules"] if name.startswith(("shwfs_ao.experiments", "shwfs_ao.control"))], guard
    # The script itself runs as __main__; its contract module is the evidence that the real validator ran.
    assert "web_contract" in guard["explorer_modules"] and "validate" not in guard["explorer_modules"]
    assert "Traceback (most recent call last)" not in completed.stderr, completed.stderr[-2000:]
    return completed, guard


def _report(completed) -> dict:
    assert completed.stdout.strip(), f"empty stdout (exit {completed.returncode}): {completed.stderr[-1500:]}"
    return json.loads(completed.stdout)


def _set_time_domain(site: Path, case_id: str, value) -> None:
    case = _member(site, case_id, "case.json")
    if value is ABSENT:
        del case["time_domain"]
    else:
        case["time_domain"] = value
    _write_case_member(site, case_id, "case.json", case)


def _write_case_record_bytes(site: Path, case_id: str, data: bytes) -> None:
    """Replace a case record by raw bytes (even bytes that are not JSON), re-hashed through the manifest and the entry."""

    base = _dataset_dir(site)
    relative = f"cases/{case_id}/case.json"
    (base / relative).write_bytes(data)
    manifest = _manifest(site)
    for item in manifest["members"]:
        if item["path"] == relative:
            item.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    _update_refs(manifest["cases"], relative, data)
    _write_manifest(site, manifest)


def _no_digest_failures(report: dict) -> None:
    assert not [failure for failure in report["failures"] if any(word in failure for word in DIGEST_FAILURES)], report["failures"][:5]


def _failed_areas(report: dict) -> set:
    return {area for area, counts in report["checks_by_area"].items() if counts["failed"]}


# ---------------------------------------------------------------------------
# Valid-input controls


def test_the_unmodified_v1_view_keeps_only_the_historical_research_source_failures(web_dir, tmp_path):
    site = _v1_fixture(web_dir, tmp_path)
    completed, _guard = _run_cli(tmp_path, site)
    report = _report(completed)
    assert completed.returncode in (0, 1) and report["valid"] is (completed.returncode == 0)
    assert report["contract"]["name"] == "v1" and report["fatal" if "fatal" in report else "valid"] is not None
    assert all(failure.startswith(RESEARCH_SOURCE) and failure.endswith(" unchanged in this tree") for failure in report["failures"]), report["failures"][:5]
    assert _failed_areas(report) <= {"results"}
    for area in ("time_domain", "provenance", "case", "members", "references"):
        assert report["checks_by_area"][area]["failed"] == 0, (area, report["checks_by_area"][area])


def test_the_committed_v2_site_passes_through_the_command_line(web_dir, tmp_path):
    site = _copy(web_dir, tmp_path)
    _v2_or_skip(site)
    completed, guard = _run_cli(tmp_path, site)
    report = _report(completed)
    assert completed.returncode == 0 and report["valid"] is True and report["checks_failed"] == 0
    assert report["contract"]["name"] == "v2" and report["previous_dataset"]["members_verified_in_place"] > 0
    assert guard["explorer_modules"] == ["long_series", "producer", "protocol", "site_build", "web_contract"] and guard["shwfs_ao_modules"] == []


def test_a_strict_producer_verdict_refusal_persists_through_the_command_line(web_dir, tmp_path):
    site = _v1_fixture(web_dir, tmp_path)
    provenance = _member(site, "baseline", "provenance.json")
    provenance["checks"]["residual_rms_matches_history"] = "false"
    _write_case_member(site, "baseline", "provenance.json", provenance)
    completed, _guard = _run_cli(tmp_path, site)
    report = _report(completed)
    assert completed.returncode == 1 and report["valid"] is False
    assert any("baseline: every producer check recorded in the provenance passed (required checks present and literally true; [\"residual_rms_matches_history='false'\"])" == failure for failure in report["failures"]), report["failures"][:5]
    assert all(failure.startswith(RESEARCH_SOURCE) or failure.startswith("baseline: ") for failure in report["failures"])
    _no_digest_failures(report)


# ---------------------------------------------------------------------------
# Whole-container defects (R25-01): a completed, structured report that names the case and what was recorded

CONTAINERS = [
    ("absent", ABSENT, "absent"),
    ("null", None, "null"),
    ("empty-array", [], "array (0 items)"),
    ("array", [40, 180], "array (2 items)"),
    ("string", "180 frames", "string"),
    ("integer", 180, "integer"),
    ("number", 1.5, "number"),
    ("boolean", True, "boolean"),
]


@pytest.mark.parametrize("name,value,kind", CONTAINERS, ids=[item[0] for item in CONTAINERS])
def test_a_v1_case_whose_time_domain_is_not_an_object_is_refused_with_a_structured_report(web_dir, tmp_path, name, value, kind):
    site = _v1_fixture(web_dir, tmp_path)
    _set_time_domain(site, "baseline", value)
    completed, _guard = _run_cli(tmp_path, site)
    report = _report(completed)
    assert completed.returncode == 1 and report["valid"] is False and "fatal" not in report
    for expected in (CONTAINER.format(kind=kind), NOT_EVALUATED.format(kind=kind), WINDOW_NOT_OBJECT.format(kind=kind), FRAMES_NOT_READ, COUNT_NOT_READ):
        assert expected in report["failures"], (expected, report["failures"][:8])
    own = [failure for failure in report["failures"] if not failure.startswith(RESEARCH_SOURCE)]
    assert len(own) == 5 and all(failure.startswith("baseline: ") for failure in own), own
    assert _failed_areas(report) <= {"time_domain", "provenance", "results"}
    assert report["checks_by_area"]["time_domain"]["failed"] == 2 and report["checks_by_area"]["provenance"]["failed"] == 3
    _no_digest_failures(report)


def test_an_empty_time_domain_object_fails_every_field_check_instead_of_the_container_check(web_dir, tmp_path):
    site = _v1_fixture(web_dir, tmp_path)
    _set_time_domain(site, "baseline", {})
    completed, _guard = _run_cli(tmp_path, site)
    report = _report(completed)
    assert completed.returncode == 1 and report["valid"] is False
    assert not any("time domain is an object" in failure or "not evaluated" in failure for failure in report["failures"])
    for expected in ("baseline: 180 frames, burn-in 40", "baseline: analysis window [40, 180), 140 samples", "baseline: movie indices equal the frozen rule (40 unique, incl. 0, 40, 179)",
                     "baseline: movie times are the frame starts", f"baseline: {TIME_DOMAIN} (recorded frames None, burn_in_frames None, analysis_window None, analysis_count None)", FRAMES_NOT_READ, COUNT_NOT_READ):
        assert expected in report["failures"], (expected, report["failures"][:12])
    assert report["checks_by_area"]["time_domain"]["failed"] == 6 and report["checks_by_area"]["provenance"]["failed"] == 3
    assert _failed_areas(report) <= {"time_domain", "provenance", "results"}
    _no_digest_failures(report)


V2_CONTAINERS = [("null", None, "null"), ("array", [200, 1000], "array (2 items)"), ("string", "one second", "string")]


@pytest.mark.parametrize("name,value,kind", V2_CONTAINERS, ids=[item[0] for item in V2_CONTAINERS])
def test_a_v2_case_whose_time_domain_is_not_an_object_is_refused_on_the_shared_path(web_dir, tmp_path, name, value, kind):
    site = _copy(web_dir, tmp_path)
    _v2_or_skip(site)
    _set_time_domain(site, "baseline", value)
    completed, _guard = _run_cli(tmp_path, site)
    report = _report(completed)
    assert completed.returncode == 1 and report["valid"] is False and "fatal" not in report
    assert CONTAINER.format(kind=kind) in report["failures"] and NOT_EVALUATED.format(kind=kind) in report["failures"], report["failures"][:6]
    assert report["failures"] == [CONTAINER.format(kind=kind), NOT_EVALUATED.format(kind=kind)]
    assert _failed_areas(report) == {"time_domain"}
    _no_digest_failures(report)


def test_an_empty_v2_time_domain_object_is_a_completed_report_with_the_manifest_agreement_failure(web_dir, tmp_path):
    site = _copy(web_dir, tmp_path)
    _v2_or_skip(site)
    _set_time_domain(site, "baseline", {})
    completed, _guard = _run_cli(tmp_path, site)
    report = _report(completed)
    assert completed.returncode == 1 and report["valid"] is False
    assert "baseline: case time domain equals the manifest time domain" in report["failures"] and "baseline: 1000 frames, burn-in 200" in report["failures"]
    assert _failed_areas(report) == {"time_domain"} and all(failure.startswith("baseline: ") for failure in report["failures"])
    _no_digest_failures(report)


# ---------------------------------------------------------------------------
# Malformed fields inside an object, through the same entry point

FIELD_DEFECTS = [
    ("burn-in-float", {"burn_in_frames": 40.0},
     ["baseline: producer analysis frames are the v1 window [40, 180) (recorded burn_in 40.0, n_steps 180)", f"baseline: {TIME_DOMAIN} (recorded frames 180, burn_in_frames 40.0, analysis_window [40, 180], analysis_count 140)"]),
    ("frames-string", {"frames": "180"}, ["baseline: producer analysis frames are the v1 window [40, 180) (recorded burn_in 40, n_steps '180')", "baseline: 180 frames, burn-in 40"]),
    ("count-inconsistent", {"analysis_count": 139}, [f"baseline: {TIME_DOMAIN} (recorded frames 180, burn_in_frames 40, analysis_window [40, 180], analysis_count 139)", "baseline: analysis window [40, 180), 140 samples"]),
    ("pilot-window", {"frames": 64, "burn_in_frames": 16, "analysis_window": [16, 64], "analysis_count": 48},
     ["baseline: producer analysis frames are the v1 window [40, 180) (recorded burn_in 16, n_steps 64)", "baseline: producer analysis count is the v1 contract's 140 (recorded n_steps - burn_in = 48)"]),
]


@pytest.mark.parametrize("name,fields,expected", FIELD_DEFECTS, ids=[item[0] for item in FIELD_DEFECTS])
def test_malformed_time_domain_fields_are_refused_through_the_command_line(web_dir, tmp_path, name, fields, expected):
    site = _v1_fixture(web_dir, tmp_path)
    case = _member(site, "baseline", "case.json")
    case["time_domain"].update(fields)
    _write_case_member(site, "baseline", "case.json", case)
    completed, _guard = _run_cli(tmp_path, site)
    report = _report(completed)
    assert completed.returncode == 1 and report["valid"] is False
    for text in expected:
        assert text in report["failures"], (text, report["failures"][:8])
    assert not any("not an object" in failure for failure in report["failures"])
    assert _failed_areas(report) <= {"time_domain", "provenance", "results"}
    _no_digest_failures(report)


# ---------------------------------------------------------------------------
# The fatal boundary and the record option, unchanged


def test_an_unreadable_case_record_is_the_fatal_refusal_not_a_report(web_dir, tmp_path):
    site = _v1_fixture(web_dir, tmp_path)
    _write_case_record_bytes(site, "baseline", b'{"schema": "ao-explorer.case.v1", "time_domain": \n')
    completed, _guard = _run_cli(tmp_path, site)
    report = _report(completed)
    assert completed.returncode == 2 and report["valid"] is False and "ValidationError" in report["fatal"] and "invalid JSON" in report["fatal"]
    assert report["contract"]["name"] == "v1" and "failures" not in report


def test_the_record_option_writes_into_the_disposable_site_only(web_dir, tmp_path):
    site = _copy(web_dir, tmp_path)
    _v2_or_skip(site)
    completed, _guard = _run_cli(tmp_path, site, "--record")
    report = _report(completed)
    assert completed.returncode == 0 and report["valid"] is True
    written = site / "validation" / f"manifest-validation-{report['dataset_id']}.json"
    assert written.is_file()
    record = json.loads(written.read_text(encoding="utf-8"))
    assert record["schema"] == validate.RECORD_SCHEMA and record["valid"] is True and record["manifest_sha256"] == report["manifest_sha256"]
    assert sorted(p.name for p in (site / "validation").iterdir()) == [written.name]
