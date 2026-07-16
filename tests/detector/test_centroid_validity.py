"""Contracts for canonical centroid estimation and validity diagnostics."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
import math

import numpy as np
import pytest

from shwfs_ao.detector.centroid import (
    CenterOfGravityEstimator,
    CentroidConfig,
    CentroidEstimate,
    CentroidEstimator,
    ThresholdedCenterOfGravityEstimator,
    estimate_centroid,
    make_centroid_estimator,
)
from shwfs_ao.detector.config import DetectorConfig, SyntheticInstrumentError
from shwfs_ao.detector.validity import (
    DEFAULT_CENTROID_VALIDITY,
    UNDEFINED_CENTROID_SIGMA_PX,
    CentroidQuality,
    CentroidValidity,
    CentroidValidityConfig,
    centroid_quality,
    evaluate_centroid_validity,
)


def _detector(*, photons: float = 100.0) -> DetectorConfig:
    return DetectorConfig(
        photons_per_subap_frame=photons,
        read_noise_e=4.0,
        dark_e_per_s=1.0,
        background_e_per_pixel_frame=2.0,
        qe=0.5,
        exposure_s=3.0,
    )


def _finite_estimate() -> CentroidEstimate:
    return CentroidEstimate(
        x_px=1.25,
        y_px=2.5,
        total_flux_e=100.0,
        finite=True,
    )


def _passing_quality() -> CentroidQuality:
    return CentroidQuality(
        total_flux_e=100.0,
        background_e=5.0,
        peak_snr=10.0,
        total_snr=20.0,
        centroid_sigma_px=0.1,
        clipping_fraction=0.05,
    )


def test_required_result_fields_are_exact() -> None:
    assert tuple(field.name for field in fields(CentroidEstimate)) == (
        "x_px",
        "y_px",
        "total_flux_e",
        "finite",
    )
    assert tuple(field.name for field in fields(CentroidValidity)) == (
        "valid",
        "valid_by_flux",
        "valid_by_snr",
        "valid_by_uncertainty",
        "valid_by_clipping",
        "peak_snr",
        "total_snr",
        "centroid_sigma_px",
        "clipping_fraction",
    )


def test_center_of_gravity_uses_absolute_column_row_coordinates() -> None:
    image = np.zeros((4, 6), dtype=float)
    image[2, 4] = 12.0
    estimator = CenterOfGravityEstimator()

    assert isinstance(estimator, CentroidEstimator)
    estimate = estimator.estimate(image)

    assert estimate == CentroidEstimate(4.0, 2.0, 12.0, True)


def test_centroid_processing_does_not_mutate_input() -> None:
    image = np.array([[2.0, 2.0, 2.0], [2.0, 3.0, 10.0]])
    before = image.copy()
    estimator = ThresholdedCenterOfGravityEstimator(
        threshold_fraction=0.4,
        subtract_minimum=True,
    )

    estimator.estimate(image)

    assert np.array_equal(image, before)


@pytest.mark.parametrize(
    "image, expected_flux",
    [
        (np.zeros((3, 4)), 0.0),
        (-np.ones((2, 2)), -4.0),
    ],
)
def test_nonpositive_processed_flux_is_explicitly_invalid(
    image: np.ndarray,
    expected_flux: float,
) -> None:
    estimate = CenterOfGravityEstimator().estimate(image)

    assert not estimate.finite
    assert math.isnan(estimate.x_px)
    assert math.isnan(estimate.y_px)
    assert estimate.total_flux_e == pytest.approx(expected_flux)


def test_threshold_can_remove_all_flux_without_fabricating_a_centroid() -> None:
    estimate = ThresholdedCenterOfGravityEstimator(1.1).estimate(
        np.array([[1.0, 2.0], [3.0, 4.0]])
    )

    assert not estimate.finite
    assert estimate.total_flux_e == 0.0
    assert np.isnan([estimate.x_px, estimate.y_px]).all()


@pytest.mark.parametrize(
    "image",
    [
        np.ones(4),
        np.ones((2, 2, 1)),
        np.array([[1.0, np.nan]]),
        np.array([[1.0, np.inf]]),
    ],
)
def test_centroid_rejects_non_2d_or_nonfinite_images(image: np.ndarray) -> None:
    with pytest.raises(ValueError):
        CenterOfGravityEstimator().estimate(image)


def test_thresholding_shifts_centroid_toward_bright_peak() -> None:
    image = np.array([[1.0, 2.0, 10.0]])
    unthresholded = estimate_centroid(image)
    thresholded = estimate_centroid(
        image,
        CentroidConfig(
            estimator="thresholded_center_of_gravity",
            threshold_fraction=0.5,
        ),
    )

    assert unthresholded.x_px == pytest.approx(22.0 / 13.0)
    assert thresholded.x_px == pytest.approx(2.0)
    assert thresholded.x_px > unthresholded.x_px
    assert thresholded.total_flux_e == pytest.approx(10.0)


def test_minimum_subtraction_removes_uniform_pedestal() -> None:
    image = np.array([[5.0, 5.0, 9.0]])
    without_subtraction = CenterOfGravityEstimator().estimate(image)
    with_subtraction = CenterOfGravityEstimator(
        subtract_minimum=True
    ).estimate(image)

    assert without_subtraction.x_px < 2.0
    assert with_subtraction.x_px == pytest.approx(2.0)
    assert with_subtraction.total_flux_e == pytest.approx(4.0)


def test_config_selects_concrete_estimators_and_validates_parameters() -> None:
    assert isinstance(
        make_centroid_estimator(CentroidConfig()),
        CenterOfGravityEstimator,
    )
    assert isinstance(
        make_centroid_estimator(
            CentroidConfig(
                estimator="thresholded_center_of_gravity",
                threshold_fraction=0.25,
                subtract_minimum=True,
            )
        ),
        ThresholdedCenterOfGravityEstimator,
    )
    with pytest.raises(ValueError, match="estimator"):
        CentroidConfig(estimator="moments")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="threshold_fraction"):
        CentroidConfig(
            estimator="thresholded_center_of_gravity",
            threshold_fraction=-0.1,
        )
    with pytest.raises(ValueError, match="must be zero"):
        CentroidConfig(threshold_fraction=0.1)


def test_quality_preserves_ccd_snr_and_clipping_equations() -> None:
    cropped = np.array([[0.0, 0.2], [0.3, 0.1]])
    full = np.array([[0.0, 0.2], [0.3, 0.5]])

    quality = centroid_quality(cropped, full, _detector())

    # Source: 100 photons * 0.5 QE * 0.6 in-window throughput.
    assert quality.total_flux_e == pytest.approx(30.0)
    # Four pixels * (2 background + 1 dark/s * 3 s).
    assert quality.background_e == pytest.approx(20.0)
    assert quality.peak_snr == pytest.approx(15.0 / math.sqrt(15.0 + 5.0 + 16.0))
    assert quality.total_snr == pytest.approx(30.0 / math.sqrt(30.0 + 4.0 * 21.0))
    assert quality.clipping_fraction == pytest.approx(0.4)
    assert 0.0 < quality.centroid_sigma_px < UNDEFINED_CENTROID_SIGMA_PX


def test_zero_photon_quality_uses_legacy_uncertainty_sentinel() -> None:
    spot = np.full((2, 2), 0.25)
    quality = centroid_quality(spot, spot, _detector(photons=0.0))

    assert quality.total_flux_e == 0.0
    assert quality.peak_snr == 0.0
    assert quality.total_snr == 0.0
    assert quality.centroid_sigma_px == UNDEFINED_CENTROID_SIGMA_PX


def test_noise_free_reference_reports_not_applicable_snr() -> None:
    spot = np.full((2, 2), 0.25)
    quality = centroid_quality(spot, spot, DetectorConfig())

    assert math.isnan(quality.total_flux_e)
    assert math.isnan(quality.peak_snr)
    assert math.isnan(quality.total_snr)
    assert quality.centroid_sigma_px == 0.0


def test_detector_window_clipping_bias_and_diagnostic() -> None:
    y_px, x_px = np.indices((21, 21), dtype=float)
    full = np.exp(-0.5 * (((x_px - 15.0) / 2.0) ** 2 + ((y_px - 10.0) / 2.0) ** 2))
    full /= np.sum(full)
    offset = 5
    cropped = full[offset:16, offset:16]

    full_estimate = CenterOfGravityEstimator().estimate(full)
    cropped_estimate = CenterOfGravityEstimator().estimate(cropped)
    quality = centroid_quality(cropped, full, _detector())

    cropped_x_in_full_coordinates = cropped_estimate.x_px + offset
    assert cropped_x_in_full_coordinates < full_estimate.x_px - 0.5
    assert quality.clipping_fraction > 0.25


@pytest.mark.parametrize(
    "changed, expected_flags",
    [
        ({"total_flux_e": 29.0}, (False, True, True, True)),
        ({"peak_snr": 2.9}, (True, False, True, True)),
        ({"centroid_sigma_px": 0.51}, (True, True, False, True)),
        ({"clipping_fraction": 0.16}, (True, True, True, False)),
    ],
)
def test_each_validity_criterion_triggers_independently(
    changed: dict[str, float],
    expected_flags: tuple[bool, bool, bool, bool],
) -> None:
    result = evaluate_centroid_validity(
        _finite_estimate(),
        replace(_passing_quality(), **changed),
    )

    assert (
        result.valid_by_flux,
        result.valid_by_snr,
        result.valid_by_uncertainty,
        result.valid_by_clipping,
    ) == expected_flags
    assert not result.valid


def test_finite_centroid_is_an_independent_aggregate_gate() -> None:
    estimate = CentroidEstimate(math.nan, math.nan, 0.0, False)
    result = evaluate_centroid_validity(estimate, _passing_quality())

    assert not result.valid
    assert result.valid_by_flux
    assert result.valid_by_snr
    assert result.valid_by_uncertainty
    assert result.valid_by_clipping


def test_reference_mode_disables_only_flux_snr_and_uncertainty_policy() -> None:
    quality = CentroidQuality(
        total_flux_e=math.nan,
        background_e=0.0,
        peak_snr=math.nan,
        total_snr=math.nan,
        centroid_sigma_px=0.0,
        clipping_fraction=0.2,
    )
    result = evaluate_centroid_validity(
        _finite_estimate(),
        quality,
        apply_quality_criteria=False,
    )

    assert result.valid_by_flux
    assert result.valid_by_snr
    assert result.valid_by_uncertainty
    assert not result.valid_by_clipping
    assert not result.valid


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_flux_e": -1.0},
        {"min_peak_snr": math.inf},
        {"max_centroid_sigma_px": -0.1},
        {"max_window_clipping_fraction": 1.1},
    ],
)
def test_validity_config_preserves_legacy_error_contract(
    kwargs: dict[str, float],
) -> None:
    with pytest.raises(SyntheticInstrumentError):
        CentroidValidityConfig(**kwargs)


def test_threshold_boundaries_are_inclusive() -> None:
    config = CentroidValidityConfig(
        min_flux_e=100.0,
        min_peak_snr=10.0,
        max_centroid_sigma_px=0.1,
        max_window_clipping_fraction=0.05,
    )
    result = evaluate_centroid_validity(
        _finite_estimate(),
        _passing_quality(),
        config,
    )

    assert result.valid


@pytest.mark.parametrize(
    "instance, field_name, replacement",
    [
        (CentroidConfig(), "subtract_minimum", True),
        (_finite_estimate(), "x_px", 9.0),
        (DEFAULT_CENTROID_VALIDITY, "min_flux_e", 1.0),
        (_passing_quality(), "peak_snr", 1.0),
        (
            evaluate_centroid_validity(_finite_estimate(), _passing_quality()),
            "valid",
            False,
        ),
    ],
)
def test_public_records_are_frozen(
    instance: object,
    field_name: str,
    replacement: object,
) -> None:
    with pytest.raises(FrozenInstanceError):
        setattr(instance, field_name, replacement)
