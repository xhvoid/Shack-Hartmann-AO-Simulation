"""The validator judges the v1 provenance's producer checks by the shared rule on the window the case record names.

Review R24 follow-up to the offline cleanup: ``render.py`` applies the v1 producer contract at the export boundary; the
validator now applies the same rule (``web_contract.producer_check_problems`` on ``web_contract.V1.producer_checks``) to
the provenance the preserved 180-frame dataset carries, with the window read from the hash-bound case record's time
domain through the adapter ``validate.v1_window_record`` (historical v1 provenance holds no producer job record).

Offline fixtures only: the preserved v1 dataset of the committed site, copied byte for byte behind a synthesized v1
entry (``test_validate_contracts._v1_fixture``, a disposable view; the committed entry, which names the active v2
dataset, is not touched).  Every negative case applies one defect to a case's ``provenance.json`` or ``case.json`` and
re-hashes the reference chain above it, so the refusal comes from the semantic check it targets and not from a digest
mismatch.  The expected contract is the hand-written oracle of ``test_validate_contracts`` (``V1_PRODUCER_REQUIRED_TRUE``
and its diagnostics), never the parsed contract; the expected window values are the literals 40, 180 and 140.  No AO
trajectory, image or scientific record is generated.
"""

from __future__ import annotations

import hashlib
import json
import math

import pytest

import protocol
import validate
import web_contract
from test_validate_contracts import (
    DIGEST_FAILURES,
    V1_PRODUCER_DIAGNOSTICS,
    V1_PRODUCER_RECORD_LISTS,
    V1_PRODUCER_REQUIRED_TRUE,
    _checks,
    _copy,
    _dataset_dir,
    _drop,
    _dumps,
    _manifest,
    _member,
    _set,
    _update_refs,
    _v1_fixture,
    _v2_or_skip,
    _write_case_member,
    _write_manifest,
)


CASE_IDS = tuple(case["id"] for case in protocol.CASES)
# The production contract, as literals: 180 frames, burn-in 40, the half-open window [40, 180) of 140 samples.
WINDOW = (40, 180)
COUNT = 140
# The pilot window, which is self-consistent and must not satisfy production provenance.
PILOT_WINDOW = (16, 64)
PILOT_COUNT = 48
PRODUCTION_TIME_DOMAIN = {"frames": 180, "burn_in_frames": 40, "analysis_window": [40, 180], "analysis_count": 140}
PILOT_TIME_DOMAIN = {"frames": 64, "burn_in_frames": 16, "analysis_window": [16, 64], "analysis_count": 48}

# The oracle, written out from producer.run_job by hand: the recorded fields in order, with the sets of
# test_validate_contracts.
ORACLE_RECORDED = (
    "atmosphere_rms_matches_history", "residual_rms_matches_history", "times_match_history", "usable_matches_history",
    "saturation_matches_history", "display_frame_independent_reductions", "display_frame_reductions_within_tolerance",
    "streaming_max_abs_difference", "streaming_within_tolerance", "instantaneous_unit_flux", "mean_unit_flux",
)
ORACLE = web_contract.ProducerChecks(
    source="producer.run_job", recorded=ORACLE_RECORDED, required_true=V1_PRODUCER_REQUIRED_TRUE, window_fields=("burn_in", "n_steps"),
    diagnostics=V1_PRODUCER_DIAGNOSTICS, window_in_checks=False, record_lists=V1_PRODUCER_RECORD_LISTS,
)

# The validator's messages for the v1 contract (literals, not derived from the validator).
FIELDS_OK = "provenance records exactly the producer's check fields (missing [], unexpected [])"
REQUIRED_OK = "every producer check recorded in the provenance passed (required checks present and literally true; [])"
FRAMES_OK = "producer analysis frames are the v1 window [40, 180) (recorded burn_in 40, n_steps 180)"
COUNT_OK = "producer analysis count is the v1 contract's 140 (recorded n_steps - burn_in = 140)"
DIAGNOSTICS_OK = "producer diagnostics carry the producer's keys and finite numbers, absolute deviations non-negative ([])"
TIME_DOMAIN = "the case record's time domain names the analysis window [burn_in_frames, frames) with analysis_count = frames - burn_in_frames as exact integers"
TIME_DOMAIN_OK = f"{TIME_DOMAIN} (recorded frames 180, burn_in_frames 40, analysis_window [40, 180], analysis_count 140)"
FRAMES_WRONG = "producer analysis frames are the v1 window [40, 180) (recorded "
COUNT_WRONG = "producer analysis count is the v1 contract's 140 (recorded "
# The pre-existing v1 time-domain checks that a changed case record also fails (contract values, not digests).
TIME_DOMAIN_FAMILY = (TIME_DOMAIN, FRAMES_WRONG, COUNT_WRONG, ": 180 frames, burn-in 40", ": analysis window [40, 180), 140 samples")


def _checker(site):
    checker = validate.Checker(site)
    report = checker.run(series_dir=None, repo_root=None)
    return checker, report


def _provenance_defect(site, case_id, mutate):
    provenance = _member(site, case_id, "provenance.json")
    mutate(provenance)
    _write_case_member(site, case_id, "provenance.json", provenance)


def _time_domain_defect(site, case_id, mutate):
    case = _member(site, case_id, "case.json")
    mutate(case["time_domain"])
    _write_case_member(site, case_id, "case.json", case)


def _write_case_bytes(site, case_id, leaf, data: bytes) -> None:
    """``_write_case_member`` for bytes the strict encoder refuses to produce (a NaN): the same re-hashed chain."""

    base = _dataset_dir(site)
    relative = f"cases/{case_id}/{leaf}"
    (base / relative).write_bytes(data)
    manifest = _manifest(site)
    for item in manifest["members"]:
        if item["path"] == relative:
            item.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    case_path = base / "cases" / case_id / "case.json"
    case = json.loads(case_path.read_text())
    _update_refs(case, relative, data, f"cases/{case_id}")
    case_data = _dumps(case)
    case_path.write_bytes(case_data)
    for item in manifest["members"]:
        if item["path"] == f"cases/{case_id}/case.json":
            item.update(bytes=len(case_data), sha256=hashlib.sha256(case_data).hexdigest())
    _update_refs(manifest["cases"], f"cases/{case_id}/case.json", case_data)
    _write_manifest(site, manifest)


def _no_digest_failures(report):
    assert not [failure for failure in report["failures"] if any(word in failure for word in DIGEST_FAILURES)], report["failures"][:5]


# ---------------------------------------------------------------------------
# The oracle and the preserved dataset


def test_the_hand_written_oracle_equals_the_parsed_v1_contract():
    assert WINDOW == (protocol.PRODUCTION_BURN_IN, protocol.PRODUCTION_FRAMES) and COUNT == WINDOW[1] - WINDOW[0]
    assert PILOT_WINDOW == (protocol.PILOT_BURN_IN, protocol.PILOT_FRAMES) and PILOT_COUNT == PILOT_WINDOW[1] - PILOT_WINDOW[0]
    assert web_contract.V1.producer_checks == ORACLE
    assert web_contract.V1.analysis_window == WINDOW and web_contract.V1.analysis_count == COUNT
    assert len(CASE_IDS) == 8


def test_the_preserved_v1_provenance_conforms_to_the_oracle_in_all_eight_cases(web_dir, tmp_path):
    # Independent of the validator: the committed provenance and case records, judged against the oracle by hand.
    site = _v1_fixture(web_dir, tmp_path)
    for case_id in CASE_IDS:
        checks = _member(site, case_id, "provenance.json")["checks"]
        assert tuple(checks) == ORACLE_RECORDED, case_id
        assert all(checks[name] is True for name in V1_PRODUCER_REQUIRED_TRUE), case_id
        for name, (keys, absolute) in V1_PRODUCER_DIAGNOSTICS.items():
            assert tuple(checks[name]) == keys and all(type(checks[name][key]) is float and math.isfinite(checks[name][key]) for key in keys), (case_id, name)
            assert not absolute or all(checks[name][key] >= 0.0 for key in keys), (case_id, name)
        (keys, absolute_keys), = V1_PRODUCER_RECORD_LISTS.values()
        records = checks["display_frame_independent_reductions"]
        assert len(records) == 40 and all(tuple(record) == keys and type(record["frame"]) is int for record in records), case_id
        assert all(record[key] >= 0.0 and math.isfinite(record[key]) for record in records for key in absolute_keys), case_id
        t = _member(site, case_id, "case.json")["time_domain"]
        assert {key: t[key] for key in validate.V1_TIME_DOMAIN_FIELDS} == PRODUCTION_TIME_DOMAIN, case_id
        assert type(t["frames"]) is int and type(t["burn_in_frames"]) is int and type(t["analysis_count"]) is int and all(type(v) is int for v in t["analysis_window"]), case_id
        assert "job" not in _member(site, case_id, "provenance.json")


def test_the_preserved_v1_dataset_passes_the_producer_check_rule_in_every_case(web_dir, tmp_path):
    # The committed entry names the active v2 dataset; the v1 branch is exercised through the disposable view only.
    assert _manifest(web_dir)["schema"] == web_contract.V2.manifest_schema
    site = _v1_fixture(web_dir, tmp_path)
    checker, report = _checker(site)
    assert report["valid"], report["failures"][:10]
    assert report["contract"]["name"] == "v1" and report["checks_by_area"]["provenance"]["failed"] == 0
    for case_id in CASE_IDS:
        for text in (TIME_DOMAIN_OK, FIELDS_OK, REQUIRED_OK, FRAMES_OK, COUNT_OK, DIAGNOSTICS_OK):
            assert f"{case_id}: {text}" in checker.passed, (case_id, text)
    # Six new provenance checks per case, on top of the pre-existing ones.
    new = [message for message in checker.passed if any(text in message for text in (TIME_DOMAIN, FIELDS_OK, REQUIRED_OK, FRAMES_OK, COUNT_OK, DIAGNOSTICS_OK))]
    assert len(new) == 6 * len(CASE_IDS)


# ---------------------------------------------------------------------------
# Defective provenance records, coherently re-hashed: only the targeted producer check fails

RECORD_KEYS_MINUS_RESIDUAL = "['atmosphere_rms_abs_error_m', 'corrected_strehl_abs_error', 'frame', 'held_correction_identity_max_abs_m', 'uncorrected_strehl_abs_error']"
PROVENANCE_DEFECTS = [
    ("required-false", "baseline", _checks(_set(("residual_rms_matches_history",), False)), ["literally true; ['residual_rms_matches_history=False']"]),
    ("required-string-false", "lower-gain", _checks(_set(("atmosphere_rms_matches_history",), "false")),
     ["lower-gain: every producer check recorded in the provenance passed (required checks present and literally true; [\"atmosphere_rms_matches_history='false'\"])"]),
    ("required-string-true", "baseline", _checks(_set(("times_match_history",), "true")), ["literally true; [\"times_match_history='true'\"]"]),
    ("required-integer-one", "baseline", _checks(_set(("streaming_within_tolerance",), 1)), ["literally true; ['streaming_within_tolerance=1']"]),
    ("required-integer-zero", "higher-gain", _checks(_set(("instantaneous_unit_flux",), 0)), ["higher-gain: every producer check recorded in the provenance passed (required checks present and literally true; ['instantaneous_unit_flux=0'])"]),
    ("required-float-one", "baseline", _checks(_set(("usable_matches_history",), 1.0)), ["literally true; ['usable_matches_history=1.0']"]),
    ("required-null", "baseline", _checks(_set(("saturation_matches_history",), None)), ["literally true; ['saturation_matches_history=None']"]),
    ("required-missing", "baseline", _checks(_drop("display_frame_reductions_within_tolerance")),
     ["baseline: every producer check recorded in the provenance passed (required checks present and literally true; ['display_frame_reductions_within_tolerance missing'])",
      "baseline: provenance records exactly the producer's check fields (missing ['display_frame_reductions_within_tolerance'], unexpected [])"]),
    ("unexpected-field", "baseline", _checks(_set(("operator_override",), True)), ["provenance records exactly the producer's check fields (missing [], unexpected ['operator_override'])"]),
    ("checks-absent", "baseline", _drop("checks"), ["baseline: every producer check recorded in the provenance passed (the checks record is NoneType, not an object)"]),
    ("checks-null", "weaker-turbulence", _set(("checks",), None), ["weaker-turbulence: every producer check recorded in the provenance passed (the checks record is NoneType, not an object)"]),
    ("checks-list", "baseline", _set(("checks",), [True]), ["(the checks record is list, not an object)"]),
    ("checks-string", "baseline", _set(("checks",), "true"), ["(the checks record is str, not an object)"]),
    ("checks-integer", "baseline", _set(("checks",), 1), ["(the checks record is int, not an object)"]),
    ("checks-boolean", "baseline", _set(("checks",), True), ["(the checks record is bool, not an object)"]),
    ("diagnostic-string", "baseline", _checks(_set(("streaming_max_abs_difference", "corrected"), "0.0")),
     ["baseline: producer diagnostics carry the producer's keys and finite numbers, absolute deviations non-negative ([\"streaming_max_abs_difference.corrected='0.0'\"])"]),
    ("diagnostic-negative-deviation", "baseline", _checks(_set(("streaming_max_abs_difference", "uncorrected"), -1e-18)), ["streaming_max_abs_difference.uncorrected=-1e-18"]),
    ("diagnostic-null", "baseline", _checks(_set(("mean_unit_flux", "corrected"), None)), ["mean_unit_flux.corrected=None"]),
    ("diagnostic-boolean", "baseline", _checks(_set(("mean_unit_flux", "uncorrected"), True)), ["mean_unit_flux.uncorrected=True"]),
    ("diagnostic-keys", "baseline", _checks(lambda checks: checks["mean_unit_flux"].pop("corrected")), ["mean_unit_flux keys ['uncorrected']"]),
    ("diagnostic-extra-key", "baseline", _checks(_set(("streaming_max_abs_difference", "extra"), 0.0)), ["streaming_max_abs_difference keys ['corrected', 'extra', 'uncorrected']"]),
    ("diagnostic-not-object", "baseline", _checks(_set(("streaming_max_abs_difference",), 0.0)), ["streaming_max_abs_difference keys float"]),
    ("records-empty", "baseline", _checks(_set(("display_frame_independent_reductions",), [])), ["display_frame_independent_reductions empty"]),
    ("records-not-list", "baseline", _checks(_set(("display_frame_independent_reductions",), {"frame": 0})), ["display_frame_independent_reductions dict"]),
    ("records-null", "baseline", _checks(_set(("display_frame_independent_reductions",), None)), ["display_frame_independent_reductions NoneType"]),
    ("record-keys", "baseline", _checks(lambda checks: checks["display_frame_independent_reductions"][3].pop("residual_rms_abs_error_m")),
     [f"display_frame_independent_reductions[3] keys {RECORD_KEYS_MINUS_RESIDUAL}"]),
    ("record-not-object", "baseline", _checks(_set(("display_frame_independent_reductions", 0), 1.0)), ["display_frame_independent_reductions[0] keys float"]),
    ("record-negative-deviation", "stronger-turbulence", _checks(_set(("display_frame_independent_reductions", 5, "residual_rms_abs_error_m"), -1e-20)),
     ["stronger-turbulence: producer diagnostics carry the producer's keys and finite numbers, absolute deviations non-negative (['display_frame_independent_reductions[5].residual_rms_abs_error_m=-1e-20'])"]),
    ("record-string", "baseline", _checks(_set(("display_frame_independent_reductions", 7, "atmosphere_rms_abs_error_m"), "0.0")), ["display_frame_independent_reductions[7].atmosphere_rms_abs_error_m='0.0'"]),
    ("record-null", "baseline", _checks(_set(("display_frame_independent_reductions", 39, "corrected_strehl_abs_error"), None)), ["display_frame_independent_reductions[39].corrected_strehl_abs_error=None"]),
    ("record-boolean-frame", "baseline", _checks(_set(("display_frame_independent_reductions", 0, "frame"), True)), ["display_frame_independent_reductions[0].frame=True"]),
]


@pytest.mark.parametrize("name,case_id,mutate,expected", PROVENANCE_DEFECTS, ids=[item[0] for item in PROVENANCE_DEFECTS])
def test_defective_v1_provenance_is_refused_by_the_producer_check_rule(web_dir, tmp_path, name, case_id, mutate, expected):
    site = _v1_fixture(web_dir, tmp_path)
    _provenance_defect(site, case_id, mutate)
    _checker_, report = _checker(site)
    assert not report["valid"]
    for reason in expected:
        assert any(reason in failure for failure in report["failures"]), (reason, report["failures"][:5])
    # Exactly the targeted producer checks of this case fail: no digest, reference or other semantic check.
    assert len(report["failures"]) == len(expected), report["failures"]
    assert all(failure.startswith(f"{case_id}: ") and "producer" in failure for failure in report["failures"]), report["failures"]
    _no_digest_failures(report)


def test_an_empty_checks_mapping_is_refused_field_by_field(web_dir, tmp_path):
    # all([]) is True: the former truthiness filter passed an empty mapping; the rule names every missing field.
    site = _v1_fixture(web_dir, tmp_path)
    _provenance_defect(site, "baseline", _set(("checks",), {}))
    _checker_, report = _checker(site)
    assert not report["valid"] and len(report["failures"]) == 3, report["failures"]
    fields, required, diagnostics = sorted(report["failures"], key=lambda failure: ("check fields" not in failure, "literally true" not in failure))
    assert fields.startswith("baseline: provenance records exactly the producer's check fields (missing [") and fields.endswith("], unexpected [])")
    assert all(f"'{name}'" in fields for name in ORACLE_RECORDED)
    assert all(f"'{name} missing'" in required for name in V1_PRODUCER_REQUIRED_TRUE)
    assert all(f"{name} keys NoneType" in diagnostics for name in V1_PRODUCER_DIAGNOSTICS) and "display_frame_independent_reductions NoneType" in diagnostics
    _no_digest_failures(report)


def test_a_non_finite_diagnostic_is_refused_before_the_rule_by_the_strict_json_reader(web_dir, tmp_path):
    # JSON NaN never reaches the rule: the reader refuses the member as a structured validation error (exit 2 on the
    # command line), not a crash and not a pass.  The rule's own non-finite handling is covered on records below.
    site = _v1_fixture(web_dir, tmp_path)
    provenance = _member(site, "baseline", "provenance.json")
    provenance["checks"]["streaming_max_abs_difference"]["corrected"] = float("nan")
    _write_case_bytes(site, "baseline", "provenance.json", (json.dumps(provenance, indent=1) + "\n").encode("utf-8"))
    with pytest.raises(validate.ValidationError, match="provenance.json: non-finite JSON constant NaN"):
        _checker(site)


# ---------------------------------------------------------------------------
# The recorded window: exact ints, consistent, and the production contract's (a pilot window is not)


def _td(**values):
    def mutate(t):
        for key, value in values.items():
            if value is _ABSENT:
                del t[key]
            else:
                t[key] = value

    return mutate


_ABSENT = object()
TIME_DOMAIN_DEFECTS = [
    # A self-consistent pilot window masquerading as production: the consistency check passes, the rule refuses.
    ("pilot-window", _td(frames=64, burn_in_frames=16, analysis_window=[16, 64], analysis_count=48), True,
     [f"{FRAMES_WRONG}burn_in 16, n_steps 64)", f"{COUNT_WRONG}n_steps - burn_in = 48)"]),
    ("frames-shifted-consistently", _td(frames=181, analysis_window=[40, 181], analysis_count=141), True,
     [f"{FRAMES_WRONG}burn_in 40, n_steps 181)", f"{COUNT_WRONG}n_steps - burn_in = 141)"]),
    ("burn-in-shifted-consistently", _td(burn_in_frames=39, analysis_window=[39, 180], analysis_count=141), True,
     [f"{FRAMES_WRONG}burn_in 39, n_steps 180)", f"{COUNT_WRONG}n_steps - burn_in = 141)"]),
    # Substitutes for the exact ints the rule reads (burn_in_frames, frames): no coercion.
    ("burn-in-float", _td(burn_in_frames=40.0), False,
     [f"{FRAMES_WRONG}burn_in 40.0, n_steps 180)", f"{COUNT_WRONG}n_steps - burn_in undefined)", f"{TIME_DOMAIN} (recorded frames 180, burn_in_frames 40.0, analysis_window [40, 180], analysis_count 140)"]),
    ("frames-float", _td(frames=180.0), False, [f"{FRAMES_WRONG}burn_in 40, n_steps 180.0)", f"{COUNT_WRONG}n_steps - burn_in undefined)"]),
    ("frames-string", _td(frames="180"), False, [f"{FRAMES_WRONG}burn_in 40, n_steps '180')", f"{COUNT_WRONG}n_steps - burn_in undefined)"]),
    ("frames-boolean", _td(frames=True), False, [f"{FRAMES_WRONG}burn_in 40, n_steps True)", f"{COUNT_WRONG}n_steps - burn_in undefined)"]),
    ("burn-in-null", _td(burn_in_frames=None), False, [f"{FRAMES_WRONG}burn_in None, n_steps 180)", f"{COUNT_WRONG}n_steps - burn_in undefined)"]),
    ("burn-in-missing", _td(burn_in_frames=_ABSENT), False, [f"{FRAMES_WRONG}burn_in None, n_steps 180)", f"{TIME_DOMAIN} (recorded frames 180, burn_in_frames None, analysis_window [40, 180], analysis_count 140)"]),
    ("frames-missing", _td(frames=_ABSENT), False, [f"{FRAMES_WRONG}burn_in 40, n_steps None)"]),
    # The recorded window and count must be exact ints consistent with those two fields.
    ("window-shifted-start", _td(analysis_window=[41, 180]), False, [f"{TIME_DOMAIN} (recorded frames 180, burn_in_frames 40, analysis_window [41, 180], analysis_count 140)"]),
    ("window-closed-end", _td(analysis_window=[40, 179]), False, [f"{TIME_DOMAIN} (recorded frames 180, burn_in_frames 40, analysis_window [40, 179], analysis_count 140)"]),
    ("window-float", _td(analysis_window=[40.0, 180]), False, ["analysis_window [40.0, 180], analysis_count 140)"]),
    ("window-string", _td(analysis_window=["40", "180"]), False, ["analysis_window ['40', '180'], analysis_count 140)"]),
    ("window-three-values", _td(analysis_window=[40, 180, 140]), False, ["analysis_window [40, 180, 140], analysis_count 140)"]),
    ("window-missing", _td(analysis_window=_ABSENT), False, ["analysis_window None, analysis_count 140)"]),
    ("count-off-by-one", _td(analysis_count=139), False, ["analysis_window [40, 180], analysis_count 139)"]),
    ("count-float", _td(analysis_count=140.0), False, ["analysis_window [40, 180], analysis_count 140.0)"]),
    ("count-string", _td(analysis_count="140"), False, ["analysis_window [40, 180], analysis_count '140')"]),
    ("count-boolean", _td(analysis_count=True), False, ["analysis_window [40, 180], analysis_count True)"]),
    ("count-missing", _td(analysis_count=_ABSENT), False, ["analysis_window [40, 180], analysis_count None)"]),
]


@pytest.mark.parametrize("name,mutate,consistent,expected", TIME_DOMAIN_DEFECTS, ids=[item[0] for item in TIME_DOMAIN_DEFECTS])
def test_a_wrong_or_ill_typed_v1_window_is_refused_by_the_rule_or_the_consistency_check(web_dir, tmp_path, name, mutate, consistent, expected):
    site = _v1_fixture(web_dir, tmp_path)
    _time_domain_defect(site, "baseline", mutate)
    _checker_, report = _checker(site)
    assert not report["valid"]
    for reason in expected:
        assert any(reason in failure for failure in report["failures"]), (reason, report["failures"][:6])
    # Only this case's window checks fail (the new rule and consistency checks and the pre-existing contract-value
    # checks of the time domain); the consistency check passes exactly when the recorded fields agree among themselves.
    assert all(failure.startswith("baseline: ") and any(text in failure for text in TIME_DOMAIN_FAMILY) for failure in report["failures"]), report["failures"]
    assert any(TIME_DOMAIN in failure for failure in report["failures"]) is not consistent, report["failures"]
    _no_digest_failures(report)


# ---------------------------------------------------------------------------
# The shared rule on the adapter, against the oracle (no site)


def _conforming_checks():
    (list_keys, _absolute), = V1_PRODUCER_RECORD_LISTS.values()
    checks = {}
    for name in ORACLE_RECORDED:
        if name in V1_PRODUCER_REQUIRED_TRUE:
            checks[name] = True
        elif name in V1_PRODUCER_DIAGNOSTICS:
            checks[name] = {key: 0.0 for key in V1_PRODUCER_DIAGNOSTICS[name][0]}
        else:
            checks[name] = [{key: (index if key == "frame" else 0.0) for key in list_keys} for index in range(3)]
    return checks


def _judge(checks, time_domain, window=WINDOW, count=COUNT):
    return web_contract.producer_check_problems(checks, ORACLE, window, count, job=validate.v1_window_record(time_domain))


def test_the_rule_accepts_conforming_checks_on_the_production_time_domain():
    assert _judge(_conforming_checks(), PRODUCTION_TIME_DOMAIN).ok
    assert validate.v1_window_consistent(PRODUCTION_TIME_DOMAIN)
    assert validate.v1_window_record(PRODUCTION_TIME_DOMAIN) == {"burn_in": 40, "n_steps": 180}


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_non_finite_diagnostics_and_records_are_named(value):
    checks = _conforming_checks()
    checks["streaming_max_abs_difference"]["corrected"] = value
    checks["display_frame_independent_reductions"][1]["frame"] = value
    problems = _judge(checks, PRODUCTION_TIME_DOMAIN)
    assert not problems.ok and problems.diagnostics == (f"streaming_max_abs_difference.corrected={value!r}", f"display_frame_independent_reductions[1].frame={value!r}")
    assert not (problems.missing or problems.unexpected or problems.not_true or problems.frames_wrong or problems.count_wrong)


def test_a_pilot_window_is_self_consistent_and_still_refused_on_the_production_contract():
    assert validate.v1_window_consistent(PILOT_TIME_DOMAIN)
    problems = _judge(_conforming_checks(), PILOT_TIME_DOMAIN)
    assert problems.frames_wrong and problems.count_wrong and not problems.ok
    assert not (problems.missing or problems.unexpected or problems.not_true or problems.diagnostics)
    # The same record on the pilot window (the exporter's pilot path) conforms: the windows stay distinct.
    assert _judge(_conforming_checks(), PILOT_TIME_DOMAIN, window=PILOT_WINDOW, count=PILOT_COUNT).ok
    assert not _judge(_conforming_checks(), PRODUCTION_TIME_DOMAIN, window=PILOT_WINDOW, count=PILOT_COUNT).ok


def test_without_a_window_record_the_rule_does_not_assume_the_contract():
    # No job record and no adapter: the window is not silently taken as the contract's.
    problems = web_contract.producer_check_problems(_conforming_checks(), ORACLE, WINDOW, COUNT)
    assert problems.frames_wrong and problems.count_wrong
    problems = web_contract.producer_check_problems(_conforming_checks(), ORACLE, WINDOW, COUNT, job={"burn_in": 40})
    assert problems.frames_wrong and problems.count_wrong


@pytest.mark.parametrize("time_domain", [None, [], "time domain", 180, {"frames": 180}, {"burn_in_frames": 40}])
def test_the_adapter_passes_absent_or_malformed_values_through_as_recorded(time_domain):
    record = validate.v1_window_record(time_domain)
    assert set(record) == {"burn_in", "n_steps"} and None in record.values()
    assert not validate.v1_window_consistent(time_domain)
    problems = _judge(_conforming_checks(), time_domain)
    assert problems.frames_wrong and problems.count_wrong and problems.kind is None


@pytest.mark.parametrize("burn_in,frames", [(40.0, 180), (40, 180.0), ("40", 180), (40, "180"), (True, 180), (40, None), (None, None), (16, 64), (41, 180), (40, 179)])
def test_the_rule_requires_exact_ints_naming_the_window(burn_in, frames):
    record = {"frames": frames, "burn_in_frames": burn_in, "analysis_window": [40, 180], "analysis_count": 140}
    assert validate.v1_window_record(record) == {"burn_in": burn_in, "n_steps": frames}
    problems = _judge(_conforming_checks(), record)
    assert problems.frames_wrong and not problems.ok


def test_booleans_are_not_ints_for_a_window_they_could_otherwise_equal():
    # On a window (0, 1) with one sample, False/True would compare equal to 0/1; the exact-int rule refuses them.
    assert web_contract.producer_check_problems(_conforming_checks(), ORACLE, (0, 1), 1, job={"burn_in": 0, "n_steps": 1}).ok
    problems = web_contract.producer_check_problems(_conforming_checks(), ORACLE, (0, 1), 1, job={"burn_in": False, "n_steps": True})
    assert problems.frames_wrong and problems.count_wrong
    assert not validate.v1_window_consistent({"frames": True, "burn_in_frames": False, "analysis_window": [False, True], "analysis_count": True})
    assert validate.v1_window_consistent({"frames": 1, "burn_in_frames": 0, "analysis_window": [0, 1], "analysis_count": 1})


@pytest.mark.parametrize("changes", [
    {"analysis_window": [40, 179]}, {"analysis_window": [41, 180]}, {"analysis_window": [40.0, 180]}, {"analysis_window": [40, 180.0]},
    {"analysis_window": (40, 180)}, {"analysis_window": [40, 180, 140]}, {"analysis_window": "[40, 180]"}, {"analysis_window": None},
    {"analysis_count": 139}, {"analysis_count": 140.0}, {"analysis_count": "140"}, {"analysis_count": True}, {"analysis_count": None},
    {"frames": 180.0}, {"burn_in_frames": "40"},
])
def test_the_consistency_check_requires_exact_ints_that_agree(changes):
    record = dict(PRODUCTION_TIME_DOMAIN, **changes)
    assert not validate.v1_window_consistent(record)
    assert validate.v1_window_consistent(dict(PRODUCTION_TIME_DOMAIN))


# ---------------------------------------------------------------------------
# The active v2 site: the same rule without an adapter, its wording and outcome unchanged


def test_the_committed_v2_site_keeps_the_v2_producer_check_wording_and_passes(web_dir, tmp_path):
    site = _copy(web_dir, tmp_path)
    _v2_or_skip(site)
    checker, report = _checker(site)
    assert report["valid"], report["failures"][:5]
    for case_id in CASE_IDS:
        assert f"{case_id}: producer analysis frames are the v2 window [200, 1000) (recorded [200, 1000])" in checker.passed
        assert f"{case_id}: producer analysis count is the v2 contract's 800 (recorded 800)" in checker.passed
    # The v1 adapter and consistency check belong to the v1 branch only; the preserved previous dataset's members are
    # verified in place by bytes, not re-judged as cases.
    assert not any(TIME_DOMAIN in message or "burn_in " in message for message in checker.passed + checker.failures)


def test_a_v2_producer_check_defect_is_still_refused_with_the_v2_wording(web_dir, tmp_path):
    site = _copy(web_dir, tmp_path)
    _v2_or_skip(site)
    _provenance_defect(site, "baseline", _checks(_set(("analysis_count",), 799)))
    _checker_, report = _checker(site)
    assert not report["valid"]
    assert any("baseline: producer analysis count is the v2 contract's 800 (recorded 799)" in failure for failure in report["failures"]), report["failures"][:5]
    assert all(failure.startswith("baseline: ") and "producer" in failure for failure in report["failures"]), report["failures"]
    _no_digest_failures(report)
