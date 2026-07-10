# Validation helpers report Marechal consistency, photon/latency monotonicity, reproducibility, diffraction-scale, and DM-fitting trend checks with explicit pass/fail results.

"""Validation and sanity-check helpers for the realistic 2 m AO demo.

The checks in this module are intentionally small and deterministic. They are
meant to be called from notebook 11 as explicit pass/fail cells and from unit
tests as focused validation checks.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Any, Sequence

import numpy as np

from ao_closed_loop import DetectorLoopConfig, run_detector_integrator_loop
from ao_diagnostics import science_psf_metrics_from_opd
from ao_error_budget import ScenarioResult
from data_sources import ALLOWED_SOURCE_CLASSES
from dm_model import DMConfig, build_dm_model, fit_static_opd_with_dm
from interaction_matrix import PokeMtxResult
from synthetic_instrument_data import DetectorConfig, DetectorShwfsCalibration, sample_centroid_noise


DEFAULT_VALIDATION_SOURCE_CLASS = "synthetic_assumed"
DEFAULT_VALIDATION_SOURCE_NOTE = (
    "Synthetic validation check for the 2 m detector-level AO demonstrator; "
    "not a measured observatory validation."
)


class AOValidationError(ValueError):
    """Raised when a validation check receives invalid inputs."""


@dataclass(frozen=True)
class ValidationCheckResult:
    """Scalar pass/fail validation result."""

    check_name: str
    passed: bool
    metric_value: float
    tolerance: float
    message: str
    source_class: str = DEFAULT_VALIDATION_SOURCE_CLASS
    source_note: str = DEFAULT_VALIDATION_SOURCE_NOTE
    details: dict[str, float | int | str | bool] | None = None

    def __post_init__(self) -> None:
        if not str(self.check_name).strip():
            raise AOValidationError("check_name must be non-empty.")
        _require_finite("metric_value", self.metric_value)
        _require_nonnegative("tolerance", self.tolerance)
        _validate_source(self.source_class, self.source_note)
        if not str(self.message).strip():
            raise AOValidationError("message must be non-empty.")

    def as_dict(self) -> dict[str, float | int | str | bool]:
        row: dict[str, float | int | str | bool] = {
            "check_name": self.check_name,
            "passed": self.passed,
            "metric_value": self.metric_value,
            "tolerance": self.tolerance,
            "message": self.message,
            "source_class": self.source_class,
            "source_note": self.source_note,
        }
        if self.details:
            row.update({f"detail_{key}": value for key, value in self.details.items()})
        return row


@dataclass(frozen=True)
class ValidationScanResult:
    """Array-valued validation scan result."""

    check_name: str
    x_values: np.ndarray
    metric_values: np.ndarray
    passed: bool
    x_unit: str
    metric_unit: str
    tolerance: float
    message: str
    source_class: str = DEFAULT_VALIDATION_SOURCE_CLASS
    source_note: str = DEFAULT_VALIDATION_SOURCE_NOTE

    def __post_init__(self) -> None:
        x = np.asarray(self.x_values, dtype=float).reshape(-1)
        y = np.asarray(self.metric_values, dtype=float).reshape(-1)
        if x.shape != y.shape:
            raise AOValidationError("x_values and metric_values must have the same shape.")
        if x.size == 0:
            raise AOValidationError("ValidationScanResult must contain at least one sample.")
        _assert_all_finite(x, "validation scan x values")
        _assert_all_finite(y, "validation scan metric values")
        _require_nonnegative("tolerance", self.tolerance)
        _validate_source(self.source_class, self.source_note)
        object.__setattr__(self, "x_values", x)
        object.__setattr__(self, "metric_values", y)

    def as_rows(self) -> tuple[dict[str, float | str | bool], ...]:
        return tuple(
            {
                "check_name": self.check_name,
                "passed": self.passed,
                "x_value": float(x),
                "metric_value": float(y),
                "x_unit": self.x_unit,
                "metric_unit": self.metric_unit,
                "tolerance": self.tolerance,
                "message": self.message,
                "source_class": self.source_class,
                "source_note": self.source_note,
            }
            for x, y in zip(self.x_values, self.metric_values)
        )


def check_marechal_consistency(
    opd_nm: np.ndarray,
    pupil_mask: np.ndarray,
    wavelength_m: float,
    telescope_diameter_m: float,
    tolerance_abs: float = 0.03,
    min_marechal_strehl: float = 0.80,
    pad_factor: int = 5,
) -> ValidationCheckResult:
    """Check PSF peak Strehl against Marechal for a small residual OPD map."""

    metrics = science_psf_metrics_from_opd(
        opd_nm,
        pupil_mask,
        wavelength_m=wavelength_m,
        telescope_diameter_m=telescope_diameter_m,
        case_name="marechal_validation",
        band_name="validation",
        pad_factor=pad_factor,
    )
    error = float(abs(metrics.strehl_peak - metrics.strehl_marechal))
    passed = bool(error <= float(tolerance_abs) and metrics.strehl_marechal >= float(min_marechal_strehl))
    return ValidationCheckResult(
        check_name="marechal_consistency",
        passed=passed,
        metric_value=error,
        tolerance=float(tolerance_abs),
        message=(
            "PSF peak Strehl agrees with Marechal within tolerance for a small residual."
            if passed
            else "PSF peak Strehl differs from Marechal beyond tolerance or residual is outside small-error regime."
        ),
        details={
            "strehl_peak": float(metrics.strehl_peak),
            "strehl_marechal": float(metrics.strehl_marechal),
            "min_marechal_strehl": float(min_marechal_strehl),
        },
    )


def check_diffraction_scale(
    pupil_mask: np.ndarray,
    wavelength_m: float,
    telescope_diameter_m: float,
    pad_factor: int = 6,
    fwhm_lambda_over_d_range: tuple[float, float] = (0.75, 1.15),
) -> ValidationCheckResult:
    """Check that the ideal PSF FWHM is near the diffraction scale."""

    mask = np.asarray(pupil_mask, dtype=bool)
    ideal_opd = np.where(mask, 0.0, np.nan)
    metrics = science_psf_metrics_from_opd(
        ideal_opd,
        mask,
        wavelength_m=wavelength_m,
        telescope_diameter_m=telescope_diameter_m,
        case_name="ideal_psf_scale",
        band_name="validation",
        pad_factor=pad_factor,
    )
    lo, hi = fwhm_lambda_over_d_range
    passed = bool(lo <= metrics.fwhm_lambda_over_d <= hi and abs(metrics.strehl_peak - 1.0) <= 1.0e-12)
    distance = 0.0 if lo <= metrics.fwhm_lambda_over_d <= hi else min(abs(metrics.fwhm_lambda_over_d - lo), abs(metrics.fwhm_lambda_over_d - hi))
    return ValidationCheckResult(
        check_name="diffraction_scale",
        passed=passed,
        metric_value=float(metrics.fwhm_lambda_over_d),
        tolerance=float(max(abs(lo), abs(hi))),
        message=(
            "Ideal PSF FWHM is within the expected lambda/D range."
            if passed
            else "Ideal PSF FWHM is outside the expected lambda/D range."
        ),
        details={
            "fwhm_min_lambda_over_d": float(lo),
            "fwhm_max_lambda_over_d": float(hi),
            "range_distance": float(distance),
            "ideal_strehl": float(metrics.strehl_peak),
        },
    )


def check_centroid_noise_photon_monotonicity(
    normalized_spot: np.ndarray,
    photon_counts: Sequence[float],
    detector_template: DetectorConfig | None = None,
    n_trials: int = 192,
    seed: int = 1,
    relative_tolerance: float = 0.05,
) -> ValidationScanResult:
    """Check that centroid noise does not worsen as photon count increases."""

    counts = np.asarray(photon_counts, dtype=float).reshape(-1)
    if counts.size < 2:
        raise AOValidationError("photon_counts must contain at least two values.")
    _assert_all_finite(counts, "photon_counts")
    if np.any(counts <= 0.0):
        raise AOValidationError("photon_counts must be positive.")
    if np.any(np.diff(counts) <= 0.0):
        raise AOValidationError("photon_counts must be strictly increasing.")
    _require_nonnegative("relative_tolerance", relative_tolerance)
    template = detector_template or DetectorConfig(
        photons_per_subap_frame=counts[0],
        read_noise_e=0.0,
        source_class=DEFAULT_VALIDATION_SOURCE_CLASS,
        source_note=DEFAULT_VALIDATION_SOURCE_NOTE,
    )
    rms_values = []
    for photons in counts:
        detector = replace(template, photons_per_subap_frame=float(photons))
        stats = sample_centroid_noise(normalized_spot, detector, n_trials=n_trials, seed=seed)
        rms_values.append(float(stats["centroid_rms_px"]))
    values = np.asarray(rms_values, dtype=float)
    _assert_all_finite(values, "centroid noise photon scan")
    passed = bool(np.all(values[1:] <= values[:-1] * (1.0 + float(relative_tolerance))))
    return ValidationScanResult(
        check_name="photon_centroid_noise_monotonicity",
        x_values=counts,
        metric_values=values,
        passed=passed,
        x_unit="photons_per_subap_frame",
        metric_unit="centroid_rms_px",
        tolerance=float(relative_tolerance),
        message=(
            "Centroid RMS does not worsen with increasing photon count within tolerance."
            if passed
            else "Centroid RMS worsened as photon count increased."
        ),
    )


def check_latency_residual_monotonicity(
    phase_sequence_rad: np.ndarray,
    calibration: DetectorShwfsCalibration,
    dm_model,
    poke_result: PokeMtxResult,
    latency_frames: Sequence[int],
    base_loop_config: DetectorLoopConfig,
    relative_tolerance: float = 0.05,
) -> ValidationScanResult:
    """Check that larger loop latency does not systematically improve residuals."""

    latencies = np.asarray(latency_frames, dtype=float).reshape(-1)
    if latencies.size < 2:
        raise AOValidationError("latency_frames must contain at least two values.")
    if np.any(latencies < 0) or np.any(np.diff(latencies) <= 0.0):
        raise AOValidationError("latency_frames must be non-negative and strictly increasing.")
    _require_nonnegative("relative_tolerance", relative_tolerance)
    residuals = []
    for latency in latencies.astype(int):
        config = replace(
            base_loop_config,
            latency_frames=int(latency),
            include_detector_noise=False,
        )
        history = run_detector_integrator_loop(phase_sequence_rad, calibration, dm_model, poke_result, config)
        tail = history.residual_opd_rms[max(0, history.residual_opd_rms.size // 2) :]
        residuals.append(float(np.median(tail)))
    values = np.asarray(residuals, dtype=float)
    _assert_all_finite(values, "latency residual scan")
    passed = bool(np.all(values[1:] >= values[:-1] * (1.0 - float(relative_tolerance))))
    return ValidationScanResult(
        check_name="latency_residual_monotonicity",
        x_values=latencies,
        metric_values=values,
        passed=passed,
        x_unit="latency_frames",
        metric_unit="median_tail_residual_opd_rms_nm",
        tolerance=float(relative_tolerance),
        message=(
            "Residual RMS does not systematically improve as latency increases."
            if passed
            else "Residual RMS improved as latency increased beyond tolerance."
        ),
    )


def check_scenario_reproducibility(
    first_results: Sequence[ScenarioResult],
    second_results: Sequence[ScenarioResult],
    field_names: Sequence[str] = (
        "open_rms_nm",
        "closed_rms_nm",
        "strehl_H",
        "command_rms_nm",
        "valid_centroid_frac",
    ),
    atol: float = 1.0e-12,
    rtol: float = 1.0e-12,
) -> ValidationCheckResult:
    """Check that two scenario-result tables are reproducible."""

    first = tuple(first_results)
    second = tuple(second_results)
    if len(first) != len(second):
        raise AOValidationError("Scenario result tables must have the same length.")
    _require_nonnegative("atol", atol)
    _require_nonnegative("rtol", rtol)
    max_abs = 0.0
    max_rel = 0.0
    for row_a, row_b in zip(first, second):
        if row_a.scenario_name != row_b.scenario_name:
            raise AOValidationError("Scenario result tables have mismatched scenario names.")
        for field_name in field_names:
            a = float(getattr(row_a, field_name))
            b = float(getattr(row_b, field_name))
            _require_finite(field_name, a)
            _require_finite(field_name, b)
            abs_diff = abs(a - b)
            rel_diff = abs_diff / max(abs(a), abs(b), 1.0)
            max_abs = max(max_abs, abs_diff)
            max_rel = max(max_rel, rel_diff)
    passed = bool(max_abs <= float(atol) or max_rel <= float(rtol))
    return ValidationCheckResult(
        check_name="scenario_reproducibility",
        passed=passed,
        metric_value=float(max_abs),
        tolerance=float(atol),
        message=(
            "Repeated scenario runs match within tolerance."
            if passed
            else "Repeated scenario runs differ beyond tolerance."
        ),
        details={"max_relative_difference": float(max_rel), "n_rows": len(first)},
    )


def check_dm_fitting_trend(
    target_opd_nm: np.ndarray,
    x_m: np.ndarray,
    y_m: np.ndarray,
    pupil_mask: np.ndarray,
    actuator_counts: Sequence[int],
    dm_config_template: DMConfig | None = None,
    relative_tolerance: float = 0.03,
) -> ValidationScanResult:
    """Check that increasing actuator count does not worsen static fitting error."""

    counts = np.asarray(actuator_counts, dtype=int).reshape(-1)
    if counts.size < 2:
        raise AOValidationError("actuator_counts must contain at least two values.")
    if np.any(counts < 2) or np.any(np.diff(counts) <= 0):
        raise AOValidationError("actuator_counts must be >=2 and strictly increasing.")
    _require_nonnegative("relative_tolerance", relative_tolerance)
    template = dm_config_template or DMConfig(
        telescope_diameter_m=2.0,
        stroke_limit_nm=1000.0,
        source_class="synthetic_literature_inspired",
        source_note="Synthetic DM fitting trend validation template.",
    )
    residuals = []
    for count in counts:
        config = replace(template, n_actuators_across=int(count))
        model = build_dm_model(x_m, y_m, pupil_mask, config)
        fit = fit_static_opd_with_dm(target_opd_nm, model, rcond=1.0e-6)
        residuals.append(float(fit.residual_rms_nm))
    values = np.asarray(residuals, dtype=float)
    _assert_all_finite(values, "DM fitting residual scan")
    passed = bool(np.all(values[1:] <= values[:-1] * (1.0 + float(relative_tolerance))))
    return ValidationScanResult(
        check_name="dm_fitting_trend",
        x_values=counts.astype(float),
        metric_values=values,
        passed=passed,
        x_unit="actuators_across",
        metric_unit="static_fit_residual_rms_nm",
        tolerance=float(relative_tolerance),
        message=(
            "Static DM fitting residual does not worsen as actuator count increases."
            if passed
            else "Static DM fitting residual worsened as actuator count increased."
        ),
    )


def validation_results_as_dicts(
    results: Sequence[ValidationCheckResult | ValidationScanResult],
) -> tuple[dict[str, float | int | str | bool], ...]:
    """Convert validation results into table-friendly dictionaries."""

    rows: list[dict[str, float | int | str | bool]] = []
    for result in results:
        if isinstance(result, ValidationCheckResult):
            rows.append(result.as_dict())
        elif isinstance(result, ValidationScanResult):
            rows.extend(result.as_rows())
        else:
            raise AOValidationError(f"Unsupported validation result type: {type(result)!r}.")
    return tuple(rows)


def _assert_all_finite(values: np.ndarray, label: str) -> None:
    array = np.asarray(values, dtype=float)
    if not np.all(np.isfinite(array)):
        finite_frac = float(np.mean(np.isfinite(array))) if array.size else 0.0
        raise AOValidationError(f"Non-finite values in {label}; finite_frac={finite_frac:.3f}.")


def _validate_source(source_class: str, source_note: str) -> None:
    if source_class not in ALLOWED_SOURCE_CLASSES:
        raise AOValidationError(
            f"source_class={source_class!r} is not in the permitted taxonomy {sorted(ALLOWED_SOURCE_CLASSES)}."
        )
    if not str(source_note).strip():
        raise AOValidationError("source_note must be a non-empty string.")


def _require_nonnegative(field_name: str, value: float) -> None:
    _require_finite(field_name, value)
    if float(value) < 0.0:
        raise AOValidationError(f"{field_name} must be non-negative; got {value!r}.")


def _require_finite(field_name: str, value: float) -> None:
    if not math.isfinite(float(value)):
        raise AOValidationError(f"{field_name} must be finite; got {value!r}.")
