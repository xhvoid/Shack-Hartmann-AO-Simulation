"""Strict request validation, derived values and comparison classes of API v1 (no numerics)."""

from __future__ import annotations

import math

import pytest

import contract


def _request(**parameter_changes):
    parameters = contract.default_parameters()
    parameters.update(parameter_changes)
    return {"schema": contract.REQUEST_SCHEMA, "api": contract.API_VERSION, "seed_policy": "specified", "parameters": parameters}


def test_defaults_are_valid_and_reproduce_the_profile():
    assert contract.validate_parameters(contract.default_parameters()) == []
    defaults = contract.default_parameters()
    assert defaults["r0_m"] == contract.PROFILE_R0_M
    assert contract.wind_vector(defaults["wind_speed_m_per_s"], defaults["wind_direction_deg"]) == contract.PROFILE_WIND_M_PER_S
    assert (defaults["n_frames"], defaults["burn_in"], defaults["seed"]) == (180, 40, 1)


@pytest.mark.parametrize(
    "changes,needle",
    [
        ({"r0_m": 0.05}, "r0_m = 0.05 is outside"),
        ({"r0_m": 0.31}, "r0_m = 0.31 is outside"),
        ({"r0_reference_wavelength_m": 6e-7}, "r0_reference_wavelength_m"),
        ({"wind_speed_m_per_s": -1.0}, "wind_speed_m_per_s"),
        ({"wind_direction_deg": 360}, "wind_direction_deg"),
        ({"wind_direction_deg": 45.5}, "must be an integer"),
        ({"guide_ab_magnitude": 3.9}, "guide_ab_magnitude"),
        ({"guide_ab_magnitude": 9.1}, "guide_ab_magnitude"),
        ({"controller_gain": 1.01}, "controller_gain"),
        ({"queued_latency_frames": 7}, "queued_latency_frames"),
        ({"queued_latency_frames": 2.0}, "must be an integer"),
        ({"n_frames": 15}, "n_frames"),
        ({"n_frames": 401}, "n_frames"),
        ({"n_frames": True}, "must be an integer"),
        ({"burn_in": 173}, "analysis samples"),
        ({"display_stride": 11}, "display_stride"),
        ({"n_frames": 400, "burn_in": 40, "display_stride": 1}, "at most 200 may be kept"),
        ({"seed": 0}, "seed = 0"),
        ({"seed": "1"}, "must be an integer"),
        ({"controller_gain": float("nan")}, "finite number"),
        ({"controller_gain": "0.2"}, "finite number"),
    ],
)
def test_out_of_contract_values_are_refused_never_clamped(changes, needle):
    reasons = contract.validate_parameters({**contract.default_parameters(), **changes})
    assert reasons and any(needle in reason for reason in reasons), reasons


def test_missing_and_unknown_fields_are_refused():
    parameters = contract.default_parameters()
    del parameters["burn_in"]
    parameters["outer_scale_m"] = 30.0
    reasons = contract.validate_parameters(parameters)
    assert any("burn_in is required" in r for r in reasons)
    assert any("unknown parameters ['outer_scale_m']" in r for r in reasons)


def test_request_envelope_and_seed_policy():
    assert contract.validate_request(_request()) == []
    bad = _request()
    bad["api"] = "ao-dynamic.api.v2"
    assert any("api must be" in r for r in contract.validate_request(bad))
    allocate = _request(seed=None)
    allocate["seed_policy"] = "allocate"
    assert contract.validate_request(allocate) == []
    allocate_with_seed = _request(seed=5)
    allocate_with_seed["seed_policy"] = "allocate"
    assert any("seed = null" in r for r in contract.validate_request(allocate_with_seed))
    specified_null = _request(seed=None)
    assert any("seed must be an integer" in r for r in contract.validate_request(specified_null))
    extra = _request()
    extra["priority"] = "high"
    assert any("unknown request fields" in r for r in contract.validate_request(extra))


def test_wind_vector_is_exact_on_the_axes_and_trigonometric_elsewhere():
    assert contract.wind_vector(10.0, 0) == (10.0, 0.0)
    assert contract.wind_vector(10.0, 90) == (0.0, 10.0)
    assert contract.wind_vector(10.0, 180) == (-10.0, 0.0)
    assert contract.wind_vector(0.0, 270) == (0.0, 0.0)
    assert all(math.copysign(1.0, value) == 1.0 for value in contract.wind_vector(0.0, 180))
    vx, vy = contract.wind_vector(10.0, 30)
    assert vx == 10.0 * math.cos(math.radians(30)) and vy == 10.0 * math.sin(math.radians(30))


def test_transported_frames_always_include_first_and_last():
    assert contract.transported_indices(16, 1) == list(range(16))
    assert contract.transported_indices(16, 5) == [0, 5, 10, 15]
    assert contract.transported_indices(17, 5) == [0, 5, 10, 15, 16]
    assert contract.transported_indices(180, 3)[-1] == 179


def test_comparison_classes_separate_atmosphere_realization_and_ao_changes():
    base = contract.effective_parameters(contract.default_parameters())
    change = lambda **kw: contract.effective_parameters({**contract.default_parameters(), **kw})  # noqa: E731
    assert contract.comparison_class(base, change(controller_gain=0.3))["kind"] == "same_atmosphere_expected"
    assert contract.comparison_class(base, change(queued_latency_frames=4))["calibration_rebuilt_identity_expected"] is False
    ab = contract.comparison_class(base, change(guide_ab_magnitude=8.0))
    assert ab["kind"] == "same_atmosphere_expected" and ab["calibration_changes"] == ["guide_ab_magnitude"]
    assert contract.comparison_class(base, change(r0_m=0.1))["kind"] == "different_physical_atmosphere"
    assert contract.comparison_class(base, change(wind_direction_deg=90))["kind"] == "different_physical_atmosphere"
    assert contract.comparison_class(base, change(seed=7))["kind"] == "different_realization"
    assert contract.comparison_class(base, change(n_frames=100))["kind"] == "different_time_grid"
    assert contract.comparison_class(base, change(display_stride=3))["kind"] == "identical_configuration"


def test_physical_identity_ignores_only_display_sampling():
    base = contract.effective_parameters(contract.default_parameters())
    strided = contract.effective_parameters({**contract.default_parameters(), "display_stride": 4})
    gained = contract.effective_parameters({**contract.default_parameters(), "controller_gain": 0.25})
    assert contract.physical_identity(base) == contract.physical_identity(strided)
    assert contract.physical_identity(base) != contract.physical_identity(gained)
