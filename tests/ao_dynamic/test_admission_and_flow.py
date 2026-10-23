"""Complete-horizon admission of generated runs and continuous frozen-flow evolution.

Admission uses the actual atmosphere construction, pupil spacing, wind, frame
times and every exposure sub-sample request (legacy left point, left-point
multisample, midpoint n = 1 and n > 1).  The wind speed 10.03 m/s is chosen so
that the 204 frame starts fit the 52 px screen support while a request half a
millisecond later does not: an admission that looked only at frame starts
would wrongly accept the exposure branches.
"""

from __future__ import annotations

from dataclasses import replace
import math

import numpy as np
import pytest

import contract
import physics


def _config(**changes):
    parameters = contract.default_parameters()
    parameters.update(changes)
    return physics.effective_config(parameters)


def test_default_configuration_is_the_frozen_explorer_baseline():
    import producer
    import protocol

    frozen = producer.job_config(protocol.production_jobs()[1])
    assert physics.effective_config(contract.default_parameters()).config_hash == frozen.config_hash
    record = physics.admit(frozen)
    assert record["admitted"] and record["max_travel_px"] == pytest.approx(45.645, abs=1e-9)


def test_frame_count_boundary_at_the_default_wind_has_no_slack():
    admitted = physics.admit(_config(n_frames=204, burn_in=40))
    refused = physics.admit(_config(n_frames=205, burn_in=40))
    assert admitted["outcome"] == "ADMITTED" and admitted["max_travel_px"] <= 52.0
    assert refused["outcome"] == "REFUSED_OVER_HORIZON"
    assert refused["first_refused_request"]["request_index"] == 204
    assert refused["first_refused_request"]["travel_px"] == pytest.approx(204 * 10.0 * 0.001 / (2.0 / 51.0))
    hint = physics.max_frames_hint(10.0, physics.horizon_constants(_config()))
    assert hint == 204


def test_oblique_wind_uses_the_vector_travel():
    # 10 m/s at 45 degrees travels as far as 10 m/s along x: same frame limit.
    assert physics.admit(_config(n_frames=204, burn_in=40, wind_direction_deg=45))["admitted"]
    assert not physics.admit(_config(n_frames=205, burn_in=40, wind_direction_deg=45))["admitted"]


@pytest.mark.parametrize(
    "override,expected",
    [
        (None, "ADMITTED"),
        (("left_point", 1), "ADMITTED"),
        (("left_point", 2), "REFUSED_OVER_HORIZON"),
        (("left_point", 4), "REFUSED_OVER_HORIZON"),
        (("midpoint", 1), "REFUSED_OVER_HORIZON"),
        (("midpoint", 3), "REFUSED_OVER_HORIZON"),
    ],
)
def test_every_exposure_branch_is_admitted_from_its_actual_request_times(override, expected):
    from shwfs_ao.experiments._component_configs import ExposureOverride

    config = _config(n_frames=204, burn_in=40, wind_speed_m_per_s=10.03)
    exposure = None if override is None else ExposureOverride(sample_rule=override[0], subsamples=override[1])
    record = physics.admit(config, exposure_override=exposure)
    assert record["outcome"] == expected, record["reasons"]
    starts_only = 203 * 10.03 * 0.001 / (2.0 / 51.0)
    assert starts_only <= 52.0  # frame starts alone would have been admitted
    if override is not None and override != ("left_point", 1):
        n = override[1]
        extra = n if override[0] == "midpoint" else n - 1
        assert record["request_count"] == 204 * (1 + extra)


def test_the_model_refuses_exactly_where_admission_does(monkeypatch):
    """With memory enforcement off (the default), the screen's own support rule still refuses."""

    from shwfs_ao.experiments.scao import build_scao_system

    monkeypatch.delenv("AO_RESOURCE_GUARD", raising=False)
    config = _config(n_frames=205, burn_in=40)
    record = physics.admit(config)
    assert not record["admitted"]
    atmosphere = build_scao_system(replace(config, controller=replace(config.controller, n_steps=16))).atmosphere
    last_admitted = 203 / 1000.0
    atmosphere.opd_at(last_admitted)
    with pytest.raises(Exception, match="beyond the 52.0 px"):
        atmosphere.opd_at(204 / 1000.0)


def _atmosphere(**changes):
    from shwfs_ao.experiments.scao import build_scao_system

    config = _config(n_frames=16, burn_in=6, **changes)
    return build_scao_system(config).atmosphere


def test_frozen_flow_translates_one_realization_instead_of_redrawing():
    """Four frames at 0.25 px per frame move the same screen by one whole sample towards +x."""

    delta = 2.0 / 51.0
    atmosphere = _atmosphere(wind_speed_m_per_s=10.0)  # admitted configuration; translation is checked below
    speed = 250.0 * delta  # 0.25 px per 1 ms frame
    flow = _atmosphere(wind_speed_m_per_s=10.0)
    flow_config = replace(flow.config, wind_m_per_s=(speed, 0.0))
    from shwfs_ao.backends.native.atmosphere import FrozenFlowAtmosphere
    from shwfs_ao.core.random import NamedRandomStreams

    moved = FrozenFlowAtmosphere(flow_config, pupil_mask=flow.pupil_mask, random_streams=NamedRandomStreams(1))
    frame0 = moved.opd_at(0.0)
    frame4 = moved.opd_at(0.004)
    mask = np.isfinite(frame0)
    overlap = mask[:, 1:] & mask[:, :-1]
    # Content at column c of frame 0 appears at column c + 1 of frame 4 (flow towards +x).
    later = frame4[:, 1:][overlap]
    earlier = frame0[:, :-1][overlap]
    difference = (later - later.mean()) - (earlier - earlier.mean())
    scale = float(np.std(earlier))
    assert np.max(np.abs(difference)) < 1e-9 * scale
    # Not a redraw: consecutive frames are strongly correlated, a new seed is not.
    frame1 = moved.opd_at(0.005)
    assert np.corrcoef(frame4[mask], frame1[mask])[0, 1] > 0.99
    other = FrozenFlowAtmosphere(replace(flow_config, root_seed=7), pupil_mask=flow.pupil_mask, random_streams=NamedRandomStreams(7))
    assert abs(np.corrcoef(frame0[mask], other.opd_at(0.0)[mask])[0, 1]) < 0.5
    assert atmosphere.realization_index == 0


def test_same_seed_reproduces_the_screen_and_gain_or_magnitude_leave_it_unchanged():
    base = _atmosphere()
    again = _atmosphere()
    ao_change = _atmosphere(controller_gain=0.4, guide_ab_magnitude=8.5, queued_latency_frames=4)
    for t in (0.0, 0.007, 0.015):
        a = base.opd_at(t)
        assert np.array_equal(a, again.opd_at(t), equal_nan=True)
        assert np.array_equal(a, ao_change.opd_at(t), equal_nan=True)
    stronger = _atmosphere(r0_m=0.1)
    ratio = (0.1263371938263465 / 0.1) ** (5.0 / 6.0)
    a = _atmosphere().opd_at(0.0)
    b = stronger.opd_at(0.0)
    mask = np.isfinite(a)
    # Same random draws, physically different atmosphere: amplitude scales as r0^(-5/6).
    assert np.allclose(b[mask], ratio * a[mask], rtol=1e-12, atol=1e-21)
    assert not math.isclose(float(np.std(a[mask])), float(np.std(b[mask])))
