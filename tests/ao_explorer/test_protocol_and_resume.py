"""Frozen-plan coverage, sample-set contracts and incompatible-resume refusal.

No AO trajectory runs here: the resume and identity checks act on small
synthetic plans and attempt directories in a temporary series directory.
"""

from __future__ import annotations

import copy
import json

import pytest

import producer
import protocol


def test_job_coverage_matches_the_authorized_scope():
    jobs = protocol.production_jobs()
    roles = [job["role"] for job in jobs]
    assert roles.count("pilot") == 1
    assert roles.count("production") == 8
    assert roles.count("passivity_control") == 1
    assert roles.count("seed_sensitivity") == 1
    production = [job for job in jobs if job["role"] == "production"]
    assert sorted(job["case_id"] for job in production) == sorted(case["id"] for case in protocol.CASES)
    assert all(job["n_steps"] == 180 and job["burn_in"] == 40 and job["root_seed"] == 1 for job in production)
    control = next(job for job in jobs if job["role"] == "passivity_control")
    assert control["observer"] is False and control["case_id"] == "baseline" and control["n_steps"] == 180
    seed2 = next(job for job in jobs if job["role"] == "seed_sensitivity")
    assert seed2["root_seed"] == 2 and seed2["case_id"] == "baseline"


def test_sample_sets_are_distinct_and_exact():
    movie = protocol.movie_indices()
    assert len(movie) == 40 and len(set(movie)) == 40 and list(movie) == sorted(movie)
    assert {0, 40, 179} <= set(movie)
    analysis = list(range(protocol.PRODUCTION_BURN_IN, protocol.PRODUCTION_FRAMES))
    assert len(analysis) == 140 and analysis[0] == 40 and analysis[-1] == 179
    assert set(movie) != set(analysis) and len(set(movie) & set(analysis)) < 140
    pilot = protocol.PILOT_DISPLAY_INDICES
    assert len(pilot) == 8 and {0, 16, 63} <= set(pilot)
    assert protocol.PILOT_FRAMES - protocol.PILOT_BURN_IN == 48


def test_case_overrides_change_exactly_one_parameter():
    base = producer.effective_parameters(producer.job_config(protocol.production_jobs()[1]))
    expected = {
        "weaker-turbulence": {"r0_m"},
        "stronger-turbulence": {"r0_m"},
        "brighter-guide": {"source_ab_magnitude"},
        "fainter-guide": {"source_ab_magnitude"},
        "lower-gain": {"controller_gain", "max_pole_modulus"},
        "higher-gain": {"controller_gain", "max_pole_modulus"},
        "longer-delay": {"queued_latency_frames", "wfs_visible_delay_frames", "max_pole_modulus", "delay_semantics"},
    }
    for job in protocol.production_jobs():
        if job["role"] != "production" or job["case_id"] == "baseline":
            continue
        params = producer.effective_parameters(producer.job_config(job))
        changed = {key for key in params if params[key] != base[key]}
        changed.discard("delay_semantics")
        assert changed <= expected[job["case_id"]] and changed, (job["case_id"], changed)
    weaker = producer.effective_parameters(producer.job_config({**protocol.production_jobs()[2]}))
    assert weaker["r0_m"] == pytest.approx(base["r0_m"] * 1.25, rel=1e-15)


def _fake_plan(tmp_path):
    plan = {
        "schema": protocol.SERIES_PLAN_SCHEMA,
        "state": "FROZEN",
        "series_id": "test-series",
        "jobs": [{"job_id": "case-baseline", "role": "production"}],
        "identities": {
            "core": {"package_sha256": "a"},
            "exporter": {"sha256": "b"},
            "environment": {"python": "x"},
            "lock": {"lock_sha256": "c", "verified": True},
        },
    }
    series = tmp_path / "series"
    series.mkdir()
    producer.write_json(series / producer.FROZEN_PLAN_NAME, plan)
    return series, plan


def test_changed_code_or_environment_refuses_the_plan(tmp_path, monkeypatch):
    series, plan = _fake_plan(tmp_path)
    current = {
        "core": {"package_sha256": "a"},
        "exporter": {"sha256": "b"},
        "environment": {"python": "x"},
        "lock": {"lock_sha256": "c", "verified": True},
    }
    monkeypatch.setattr(producer.identity, "core_identity", lambda: current["core"])
    monkeypatch.setattr(producer.identity, "exporter_identity", lambda: current["exporter"])
    monkeypatch.setattr(producer.identity, "environment_identity", lambda: current["environment"])
    monkeypatch.setattr(producer.identity, "lock_verification", lambda: current["lock"])
    assert producer.check_identities(plan)["exporter"]["sha256"] == "b"
    for key, value in (("exporter", {"sha256": "changed"}), ("core", {"package_sha256": "changed"}), ("environment", {"python": "other"}), ("lock", {"lock_sha256": "c", "verified": False})):
        changed = copy.deepcopy(current)
        changed[key] = value
        monkeypatch.setattr(producer.identity, f"{'lock_verification' if key == 'lock' else key + '_identity'}", lambda value=value: value)
        with pytest.raises(producer.ProducerError):
            producer.check_identities(plan)
        monkeypatch.setattr(producer.identity, f"{'lock_verification' if key == 'lock' else key + '_identity'}", lambda key=key: current[key])


def test_completed_attempts_are_reused_and_never_overwritten(tmp_path):
    series, _ = _fake_plan(tmp_path)
    first = producer.next_attempt_dir(series, "case-baseline")
    first.mkdir()
    producer.write_json(first / "status.json", {"status": "STARTED"})
    # An interrupted attempt is kept and the next attempt gets a new directory.
    assert producer.completed_attempt(series, "case-baseline") is None
    second = producer.next_attempt_dir(series, "case-baseline")
    assert second.name == "attempt-02"
    second.mkdir()
    producer.write_json(second / "status.json", {"status": "COMPLETED"})
    assert producer.completed_attempt(series, "case-baseline") == second
    with pytest.raises(producer.ProducerError, match="already has a completed attempt"):
        producer.run_job(series, "case-baseline", frozen=True)
    assert json.loads((first / "status.json").read_text())["status"] == "STARTED"


def test_draft_plans_never_run_production_and_plans_are_never_overwritten(tmp_path):
    series = tmp_path / "series"
    series.mkdir()
    producer.write_json(series / producer.DRAFT_PLAN_NAME, {"state": "DRAFT_BEFORE_PILOT", "jobs": [{"job_id": "case-baseline", "role": "production"}], "identities": {}})
    with pytest.raises(producer.ProducerError, match="only the pilot"):
        producer.run_job(series, "case-baseline", frozen=False)
    with pytest.raises(producer.ProducerError, match="never overwritten"):
        producer.draft_plan(series, "series")


def test_ceilings_refuse_before_launch(tmp_path):
    series, _ = _fake_plan(tmp_path)
    producer.append_ledger(series, {"wall_s": protocol.WALL_TIME_CEILING_S - 1.0, "launched": True})
    entry = producer.supervise(series, ["true"], label="x", kind="trajectory", job_id=None, estimate=None, timeout_s=1.0, projected_wall_s=5.0, projected_bytes=0)
    assert entry["status"] == "REFUSED_CEILING" and not entry["launched"]
