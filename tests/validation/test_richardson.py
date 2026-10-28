"""T2: Richardson analysis on synthetic scans with known limits and orders, and its refusals."""

from __future__ import annotations

import json
import math

import pytest

from shwfs_ao.validation.richardson import RichardsonError, change_table, richardson_estimate


def test_a_power_law_with_unequal_ratios_recovers_order_and_limit() -> None:
    h = [1.0 / 12.0, 1.0 / 16.0, 1.0 / 20.0]  # the pupil samples-per-lenslet family
    values = [1.0 + 3.0 * x**2 for x in h]
    result = richardson_estimate(h, values)
    assert result.status == "ESTIMATED"
    assert result.observed_order == pytest.approx(2.0, abs=1.0e-9)
    assert result.extrapolated_limit == pytest.approx(1.0, abs=1.0e-12)
    assert result.refinement_ratios == (pytest.approx(16.0 / 12.0), pytest.approx(20.0 / 16.0))
    assert result.uncertainty_available is False and "uncertainty not available" in (result.reason or "")
    assert result.gci_fine_relative == pytest.approx(1.25 * abs(values[2] - values[1]) / values[2] / ((20.0 / 16.0) ** 2 - 1.0))
    record = result.to_record()
    assert record["order_source"] == "observed"
    json.dumps(record)


def test_equal_ratios_and_an_assumed_order_are_reported_apart() -> None:
    h = [1.0, 0.5, 0.25]
    values = [2.0 + 0.7 * x**1.5 for x in h]
    result = richardson_estimate(h, values, uncertainties=[1.0e-6] * 3, assumed_order=2.0)
    assert result.status == "ESTIMATED" and result.reason is None
    assert result.observed_order == pytest.approx(1.5, abs=1.0e-9)
    assert result.extrapolated_limit == pytest.approx(2.0, abs=1.0e-9)
    # The assumed-order extrapolation from the two finest settings is a different number.
    assert result.assumed_order == 2.0
    assert result.assumed_order_limit == pytest.approx(values[2] + (values[2] - values[1]) / 3.0)
    assert result.assumed_order_limit != pytest.approx(2.0, abs=1.0e-6)
    # Input order does not matter; the scan is sorted coarse to fine.
    shuffled = richardson_estimate(h[::-1], values[::-1], uncertainties=[1.0e-6] * 3)
    assert shuffled.observed_order == pytest.approx(result.observed_order)


@pytest.mark.parametrize(
    ("values", "reason"),
    [
        ([1.0, 1.0, 1.0], "flat"),
        ([1.0, 1.1, 1.05], "oscillatory"),
        ([1.0, 1.1, 1.3], "non-shrinking"),
        ([1.0, math.nan, 1.2], "nonfinite"),
        ([1.0, 1.1, 1.2], "zero-order limit"),
    ],
)
def test_unestimable_scans_return_not_estimated_with_a_reason(values: list[float], reason: str) -> None:
    result = richardson_estimate([1.0, 0.5, 0.25], values)
    assert result.status == "NOT_ESTIMATED"
    assert reason in (result.reason or "")
    assert result.observed_order is None and result.extrapolated_limit is None
    json.dumps(result.to_record())


def test_uncertainty_dominated_differences_two_settings_and_no_power_law() -> None:
    dominated = richardson_estimate([1.0, 0.5, 0.25], [1.0, 1.01, 1.015], uncertainties=[0.01, 0.01, 0.01])
    assert dominated.status == "NOT_ESTIMATED" and "uncertainty-dominated" in (dominated.reason or "")
    resolved = richardson_estimate([1.0, 0.5, 0.25], [1.0, 1.01, 1.015], uncertainties=[1.0e-4] * 3)
    assert resolved.status == "ESTIMATED" and resolved.observed_order == pytest.approx(1.0, abs=1.0e-9)
    two = richardson_estimate([1.0, 0.5], [1.0, 1.1])
    assert two.status == "NOT_ESTIMATED" and "fewer than three" in (two.reason or "")
    nodes = richardson_estimate([3.0, 5.0, 7.0], [1.0, 1.001, 1.0001], power_law=False)
    assert nodes.status == "NOT_ESTIMATED" and "Gauss" in (nodes.reason or "")
    assert nodes.power_law_declared is False and nodes.assumed_order_limit is None


def test_ill_conditioned_ratios_are_refused_as_estimates() -> None:
    # Differences that shrink too slowly for the refinement ratios: the order would be below 0.1.
    result = richardson_estimate([1.0, 0.5, 0.25], [1.0, 1.1, 1.199])
    assert result.status == "NOT_ESTIMATED" and "ill-conditioned" in (result.reason or "")
    # Differences shrinking faster than order 8 lie above the admitted range.
    steep = richardson_estimate([1.0, 0.5, 0.25], [1.0, 1.1, 1.1 + 0.1 / 2.0**9])
    assert steep.status == "NOT_ESTIMATED" and "above" in (steep.reason or "")


def test_the_change_table_lists_adjacent_changes_coarse_to_fine() -> None:
    table = change_table([0.25, 1.0, 0.5], [1.13, 1.0, 1.1], uncertainties=[0.01, 0.01, 0.01])
    assert table["refinement_parameters"] == [1.0, 0.5, 0.25]
    first, second = table["changes"]
    assert first["difference_fine_minus_coarse"] == pytest.approx(0.1)
    assert first["ratio"] == 2.0 and first["resolved_2se"] is True
    assert second["difference_fine_minus_coarse"] == pytest.approx(0.03)
    assert second["difference_uncertainty"] == pytest.approx(math.hypot(0.01, 0.01))
    json.dumps(table)


def test_malformed_scans_are_errors_not_results() -> None:
    with pytest.raises(RichardsonError):
        richardson_estimate([1.0, 1.0, 0.5], [1.0, 1.1, 1.2])
    with pytest.raises(RichardsonError):
        richardson_estimate([1.0, 0.5], [1.0, 1.1, 1.2])
    with pytest.raises(RichardsonError):
        richardson_estimate([1.0, -0.5, 0.25], [1.0, 1.1, 1.2])
    with pytest.raises(RichardsonError):
        richardson_estimate([1.0, 0.5, 0.25], [1.0, True, 1.2])
    with pytest.raises(RichardsonError):
        richardson_estimate([1.0, 0.5, 0.25], [1.0, 1.1, 1.2], uncertainties=[0.1, -0.1, 0.1])
    with pytest.raises(RichardsonError):
        richardson_estimate([1.0, 0.5, 0.25], [1.0, 1.1, 1.2], assumed_order=0.0)


def test_decreasing_refinement_ratios_admit_a_low_positive_order() -> None:
    # Ratios 2 then 3: the zero-order limit ln 2 / ln 3 = 0.63 lies below one, so a
    # difference ratio below one is still a positive order (review round 1, F-02).
    h = [1.0 / 10.0, 1.0 / 20.0, 1.0 / 60.0]
    for order in (0.3, 0.5, 0.9, 1.5):
        values = [1.0 + 3.0 * x**order for x in h]
        result = richardson_estimate(h, values)
        assert result.status == "ESTIMATED", result.reason
        assert result.observed_order == pytest.approx(order, abs=1.0e-9)
        assert result.extrapolated_limit == pytest.approx(1.0, abs=1.0e-9)
    # A negative order on the same ratios is refused at the zero-order limit.
    refused = richardson_estimate(h, [1.0 + 3.0 * x**-0.2 for x in h])
    assert refused.status == "NOT_ESTIMATED" and "zero-order limit" in (refused.reason or "")
