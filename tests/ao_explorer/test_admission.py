"""Complete-horizon admission against an independent schedule/admission oracle.

The oracle below is written separately from ``admission.py``: it enumerates
request times with exact rational arithmetic from the loop's documented
sampling rules and decides admission by comparing squared travel with the
squared budget, so it shares neither code nor floating-point path with the
helper under test.
"""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

import numpy as np
import pytest

import admission
import producer
import protocol


def oracle_times(n_frames, rate_hz, rule, subsamples, exposure_s):
    """Exact request times per the loop's rules (Fractions)."""

    rate = Fraction(rate_hz)
    tau = Fraction(exposure_s) if exposure_s is not None else None
    times = []
    for k in range(n_frames):
        start = Fraction(k) / rate
        times.append(start)
        if rule == "legacy":
            continue
        if rule == "left_point":
            times.extend(start + Fraction(j) * tau / subsamples for j in range(1, subsamples))
        elif rule == "midpoint":
            times.extend(start + (Fraction(j) + Fraction(1, 2)) * tau / subsamples for j in range(subsamples))
        else:  # pragma: no cover - fixture error
            raise AssertionError(rule)
    return times


def oracle_admits(times, *, wind, delta, budget):
    vx, vy = Fraction(wind[0]), Fraction(wind[1])
    delta = Fraction(delta)
    budget = Fraction(budget)
    worst = max((vx * t / delta) ** 2 + (vy * t / delta) ** 2 for t in times)
    return worst <= budget**2, worst


@pytest.mark.parametrize(
    "rule,subsamples,n_frames",
    [
        ("legacy", 1, 9),
        ("left_point", 2, 9),
        ("left_point", 4, 9),
        ("midpoint", 1, 9),
        ("midpoint", 3, 9),
        ("legacy", 1, 10),
    ],
)
def test_schedule_matches_the_exact_oracle(rule, subsamples, n_frames):
    keywords = {}
    if rule != "legacy":
        keywords = {"exposure_subsamples": subsamples, "exposure_s": 0.01}
        if rule == "midpoint":
            keywords["exposure_sample_rule"] = "midpoint"
    schedule = admission.request_schedule(n_frames, 100.0, keywords)
    expected = oracle_times(n_frames, 100, rule, subsamples, Fraction(1, 100))
    assert len(schedule["times_s"]) == len(expected)
    assert np.allclose(schedule["times_s"], [float(t) for t in expected], rtol=0.0, atol=1e-15)


def _decide(times, wind=(10.0, 0.0), delta=0.1, budget=8.0):
    return admission.evaluate_requests(times, wind_m_per_s=wind, delta_m=delta, budget_px=budget)


def test_frame_starts_alone_are_insufficient_for_exposure_samples():
    # Grid 8 px in a 24 px screen: budget 8 px; delta 0.1 m; wind 10 m/s;
    # 100 Hz: frame k travels exactly k px, so 9 frames reach 8 px (admitted,
    # the model refuses only travel > budget).
    cases = {
        ("legacy", 1): True,
        ("left_point", 2): False,  # adds t + 5 ms -> 8.5 px at the last frame
        ("midpoint", 1): False,  # midpoint n=1 still requests t + 5 ms
        ("midpoint", 4): False,
    }
    for (rule, subsamples), expected in cases.items():
        keywords = {}
        if rule != "legacy":
            keywords = {"exposure_subsamples": subsamples, "exposure_s": 0.01}
            if rule == "midpoint":
                keywords["exposure_sample_rule"] = "midpoint"
        times = admission.request_schedule(9, 100.0, keywords)["times_s"]
        decision = _decide(times)
        helper_admits = decision["first_refused_request"] is None
        oracle, _ = oracle_admits(
            oracle_times(9, 100, rule, subsamples, Fraction(1, 100)), wind=(10, 0), delta=Fraction(1, 10), budget=8
        )
        assert helper_admits == oracle == expected, (rule, subsamples)


def test_over_horizon_refusal_has_no_slack():
    # One frame past the budget (10 frames -> 9 px > 8 px) is refused even
    # though the excess is a single pixel; diagonal wind uses the hypotenuse.
    times = admission.request_schedule(10, 100.0, {})["times_s"]
    assert _decide(times)["first_refused_request"]["request_index"] == 9
    diagonal = _decide(admission.request_schedule(7, 100.0, {})["times_s"], wind=(10.0, 10.0))
    oracle, worst = oracle_admits(oracle_times(7, 100, "legacy", 1, None), wind=(10, 10), delta=Fraction(1, 10), budget=8)
    assert (diagonal["first_refused_request"] is None) == oracle is False
    assert diagonal["max_travel_px"] == pytest.approx(float(worst) ** 0.5, rel=1e-15)


def test_invalid_and_decreasing_times_refuse():
    decision = _decide([0.0, 0.02, 0.01, float("nan")])
    assert len(decision["invalid_requests"]) == 2


def test_the_model_itself_refuses_exactly_where_the_helper_does():
    # A tiny real v2 screen (8 px pupil, 24 px generated): the atmosphere's
    # own guard must agree with the helper at, and just beyond, the budget.
    from shwfs_ao.backends.native.atmosphere import (
        SPECTRUM_SUBHARMONIC_V2,
        TRANSLATION_FOURIER_SUBPIXEL_V2,
        FrozenFlowAtmosphere,
        FrozenFlowAtmosphereConfig,
        NativeAtmosphereError,
    )

    config = FrozenFlowAtmosphereConfig(
        grid_size=8,
        screen_grid_size=24,
        delta_m=0.1,
        pupil_diameter_m=0.8,
        r0_m=0.2,
        wind_m_per_s=(10.0, 0.0),
        normalize_rms=False,
        spectrum_model=SPECTRUM_SUBHARMONIC_V2,
        translation_model=TRANSLATION_FOURIER_SUBPIXEL_V2,
    )
    assert config.travel_budget_px == 8.0
    atmosphere = FrozenFlowAtmosphere(config)
    atmosphere.opd_at(0.08)  # exactly 8 px: admitted by the model
    assert _decide([0.08])["first_refused_request"] is None
    with pytest.raises(NativeAtmosphereError):
        atmosphere.opd_at(0.0805)
    assert _decide([0.0805])["first_refused_request"] is not None


def test_every_planned_job_is_admitted_from_the_actual_tree():
    for job in protocol.production_jobs():
        record = admission.admit(producer.job_config(job))
        expected_last = (job["n_steps"] - 1) / 1000.0
        assert record["admitted"], job["job_id"]
        assert record["request_count"] == job["n_steps"]  # legacy left point, n = 1
        assert record["last_request_s"] == pytest.approx(expected_last, abs=1e-15)
        oracle, worst = oracle_admits(
            oracle_times(job["n_steps"], 1000, "legacy", 1, None),
            wind=(10, 0),
            delta=Fraction(record["delta_m"]),
            budget=record["travel_budget_px"],
        )
        assert oracle
        assert record["max_travel_px"] == pytest.approx(float(worst) ** 0.5, rel=1e-14)
        assert record["generated_screen_px"] == 156 and record["travel_budget_px"] == 52.0
        assert record["pupil_spacing"]["factory_matches_coordinates"]


def test_production_horizon_refuses_beyond_its_budget_with_the_real_geometry():
    job = dict(protocol.production_jobs()[1])
    config = producer.job_config(job)
    for frames, admitted in ((204, True), (205, False)):
        changed = replace(config, controller=replace(config.controller, n_steps=frames))
        record = admission.admit(changed)
        assert record["admitted"] is admitted, frames
    midpoint = replace(config, controller=replace(config.controller, n_steps=204))
    from shwfs_ao.experiments._component_configs import ExposureOverride

    record = admission.admit(midpoint, exposure_override=ExposureOverride(subsamples=1, sample_rule="midpoint"))
    assert record["request_count"] == 2 * 204
    # 0.203 s frame start + 0.5 ms midpoint = 51.89 px, still inside 52 px.
    assert record["admitted"]
    over = replace(config, controller=replace(config.controller, n_steps=205))
    record = admission.admit(over, exposure_override=ExposureOverride(subsamples=2, sample_rule="left_point"))
    assert not record["admitted"] and record["outcome"] == admission.REFUSED_OVER_HORIZON


def test_unsupported_atmosphere_models_are_refused():
    config = producer.job_config(protocol.production_jobs()[1])
    # The legacy periodic screen has a different support contract; unknown
    # coverage must refuse rather than borrow the v2 rule.
    legacy = replace(config, atmosphere_model="native_frozen_flow")
    record = admission.admit(legacy)
    assert record["outcome"] == admission.REFUSED_UNSUPPORTED and not record["admitted"]
