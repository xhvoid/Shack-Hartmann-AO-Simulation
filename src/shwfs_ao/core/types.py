"""Backend-neutral adaptive-optics result contracts.

These dataclasses form the repository-owned boundary between physical
components and backends.  Every array is copied on construction and stored
read-only.  Invalid measurement rows may retain NaN payloads, but infinities
are never valid and a NaN may only occur where the corresponding validity
mask permits it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import math
from types import MappingProxyType
from typing import Any, Literal, cast

import numpy as np

from .hashing import detector_plane_sampling_hash


MeasurementUnit = Literal["pixel", "rad_wavefront_slope"]

__all__ = (
    "MeasurementUnit",
    "MeasurementVector",
    "DetectorPlaneSampling",
    "DetectorFrame",
    "DetectorTelemetry",
    "WfsMeasurement",
    "SpotIntensityResult",
    "PsfResult",
    "DmCommandVector",
    "DmSynthesisResult",
    "ReconstructionEstimate",
)

_MEASUREMENT_UNITS = frozenset({"pixel", "rad_wavefront_slope"})
_COORDINATE_KINDS = frozenset({"modal_opd", "dm_command_opd"})
_COORDINATE_UNITS = frozenset({"m_opd_rms", "m_opd_equivalent"})
_COMMAND_UNIT = "m_opd_equivalent"
_SPOT_NORMALIZATION = "unit_sum_per_subaperture"
_PSF_NORMALIZATION = "unit_total_flux"


@dataclass(frozen=True)
class MeasurementVector:
    values: np.ndarray
    valid_rows: np.ndarray
    row_ids: tuple[str, ...]
    measurement_unit: MeasurementUnit

    def __post_init__(self) -> None:
        row_ids = _validated_ids(self.row_ids, label="row_ids")
        values = _float_array(self.values, label="values", ndim=1)
        valid_rows = _bool_array(self.valid_rows, label="valid_rows", ndim=1)
        _require_shape(values, (len(row_ids),), label="values")
        _require_shape(valid_rows, (len(row_ids),), label="valid_rows")
        _finite_where(values, valid_rows, label="values")
        measurement_unit = _literal(
            self.measurement_unit,
            _MEASUREMENT_UNITS,
            label="measurement_unit",
        )

        object.__setattr__(self, "values", values)
        object.__setattr__(self, "valid_rows", valid_rows)
        object.__setattr__(self, "row_ids", row_ids)
        object.__setattr__(self, "measurement_unit", measurement_unit)


@dataclass(frozen=True)
class DetectorPlaneSampling:
    window_shape_px: tuple[int, int]
    pixel_scale_rad: tuple[float, float]
    reference_pixel_xy: tuple[float, float]
    sampling_hash: str

    def __post_init__(self) -> None:
        window_shape_px = _positive_integer_pair(
            self.window_shape_px,
            label="window_shape_px",
        )
        pixel_scale_rad = _finite_float_pair(
            self.pixel_scale_rad,
            label="pixel_scale_rad",
            positive=True,
        )
        reference_pixel_xy = _finite_float_pair(
            self.reference_pixel_xy,
            label="reference_pixel_xy",
        )
        sampling_hash = _nonempty_string(self.sampling_hash, label="sampling_hash")
        expected_hash = detector_plane_sampling_hash(
            window_shape_px=window_shape_px,
            pixel_scale_rad=pixel_scale_rad,
            reference_pixel_xy=reference_pixel_xy,
        )
        if sampling_hash != expected_hash:
            raise ValueError(
                "sampling_hash must match window_shape_px, pixel_scale_rad, "
                "and reference_pixel_xy."
            )

        object.__setattr__(self, "window_shape_px", window_shape_px)
        object.__setattr__(self, "pixel_scale_rad", pixel_scale_rad)
        object.__setattr__(self, "reference_pixel_xy", reference_pixel_xy)
        object.__setattr__(self, "sampling_hash", sampling_hash)


@dataclass(frozen=True)
class DetectorFrame:
    image_e: np.ndarray
    expected_source_e: np.ndarray
    expected_background_e: np.ndarray
    expected_pre_poisson_e: np.ndarray
    prnu_response: np.ndarray
    saturated_mask: np.ndarray
    bad_pixel_mask: np.ndarray
    negative_clipped_mask: np.ndarray
    random_stream_ids: Mapping[str, str]

    def __post_init__(self) -> None:
        image_e = _float_array(self.image_e, label="image_e", ndim=2)
        _require_all_finite(image_e, label="image_e")
        shape = image_e.shape
        expected_source_e = _matching_nonnegative_array(
            self.expected_source_e,
            shape,
            label="expected_source_e",
        )
        expected_background_e = _matching_nonnegative_array(
            self.expected_background_e,
            shape,
            label="expected_background_e",
        )
        expected_pre_poisson_e = _matching_nonnegative_array(
            self.expected_pre_poisson_e,
            shape,
            label="expected_pre_poisson_e",
        )
        prnu_response = _matching_nonnegative_array(
            self.prnu_response,
            shape,
            label="prnu_response",
        )
        saturated_mask = _matching_bool_array(
            self.saturated_mask,
            shape,
            label="saturated_mask",
        )
        bad_pixel_mask = _matching_bool_array(
            self.bad_pixel_mask,
            shape,
            label="bad_pixel_mask",
        )
        negative_clipped_mask = _matching_bool_array(
            self.negative_clipped_mask,
            shape,
            label="negative_clipped_mask",
        )
        random_stream_ids = _string_mapping(
            self.random_stream_ids,
            label="random_stream_ids",
        )

        object.__setattr__(self, "image_e", image_e)
        object.__setattr__(self, "expected_source_e", expected_source_e)
        object.__setattr__(self, "expected_background_e", expected_background_e)
        object.__setattr__(self, "expected_pre_poisson_e", expected_pre_poisson_e)
        object.__setattr__(self, "prnu_response", prnu_response)
        object.__setattr__(self, "saturated_mask", saturated_mask)
        object.__setattr__(self, "bad_pixel_mask", bad_pixel_mask)
        object.__setattr__(self, "negative_clipped_mask", negative_clipped_mask)
        object.__setattr__(self, "random_stream_ids", random_stream_ids)


@dataclass(frozen=True)
class DetectorTelemetry:
    subaperture_ids: tuple[str, ...]
    centroids_xy_px: np.ndarray
    reference_centroids_xy_px: np.ndarray
    fluxes_e: np.ndarray
    valid_subapertures: np.ndarray
    valid_by_flux: np.ndarray
    valid_by_snr: np.ndarray
    valid_by_uncertainty: np.ndarray
    valid_by_clipping: np.ndarray
    peak_snr: np.ndarray
    total_snr: np.ndarray
    centroid_sigma_px: np.ndarray
    clipping_fraction: np.ndarray
    detector_frames: tuple[DetectorFrame, ...] | None = None
    optical_spots: SpotIntensityResult | None = None

    def __post_init__(self) -> None:
        subaperture_ids = _validated_ids(
            self.subaperture_ids,
            label="subaperture_ids",
        )
        count = len(subaperture_ids)
        centroids_xy_px = _float_array(
            self.centroids_xy_px,
            label="centroids_xy_px",
            ndim=2,
        )
        _require_shape(
            centroids_xy_px,
            (count, 2),
            label="centroids_xy_px",
        )
        reference_centroids_xy_px = _float_array(
            self.reference_centroids_xy_px,
            label="reference_centroids_xy_px",
            ndim=2,
        )
        _require_shape(
            reference_centroids_xy_px,
            (count, 2),
            label="reference_centroids_xy_px",
        )
        _require_all_finite(
            reference_centroids_xy_px,
            label="reference_centroids_xy_px",
        )

        valid_subapertures = _length_bool_array(
            self.valid_subapertures,
            count,
            label="valid_subapertures",
        )
        valid_by_flux = _length_bool_array(
            self.valid_by_flux,
            count,
            label="valid_by_flux",
        )
        valid_by_snr = _length_bool_array(
            self.valid_by_snr,
            count,
            label="valid_by_snr",
        )
        valid_by_uncertainty = _length_bool_array(
            self.valid_by_uncertainty,
            count,
            label="valid_by_uncertainty",
        )
        valid_by_clipping = _length_bool_array(
            self.valid_by_clipping,
            count,
            label="valid_by_clipping",
        )
        expected_valid = (
            valid_by_flux
            & valid_by_snr
            & valid_by_uncertainty
            & valid_by_clipping
        )
        if np.any(valid_subapertures & ~expected_valid):
            raise ValueError(
                "valid_subapertures cannot be true where any per-criterion "
                "validity mask is false."
            )

        fluxes_e = _length_float_array(self.fluxes_e, count, label="fluxes_e")
        peak_snr = _length_float_array(self.peak_snr, count, label="peak_snr")
        total_snr = _length_float_array(self.total_snr, count, label="total_snr")
        centroid_sigma_px = _length_float_array(
            self.centroid_sigma_px,
            count,
            label="centroid_sigma_px",
        )
        clipping_fraction = _length_float_array(
            self.clipping_fraction,
            count,
            label="clipping_fraction",
        )

        _finite_rows(centroids_xy_px, valid_subapertures, label="centroids_xy_px")
        _finite_where(fluxes_e, valid_by_flux, label="fluxes_e")
        # SNR is intentionally not finite-gated by ``valid_by_snr``.  Ideal
        # detector paths have no noise realization from which to define SNR,
        # while disabled quality criteria correctly leave ``valid_by_snr``
        # true.  NaN therefore means "not applicable"; infinities and finite
        # negative values remain forbidden below.
        if np.any(np.isinf(peak_snr)):
            raise ValueError("peak_snr must not contain infinite values.")
        if np.any(np.isinf(total_snr)):
            raise ValueError("total_snr must not contain infinite values.")
        _finite_where(
            centroid_sigma_px,
            valid_by_uncertainty,
            label="centroid_sigma_px",
        )
        _finite_where(
            clipping_fraction,
            valid_by_clipping,
            label="clipping_fraction",
        )
        for label, values in (
            ("fluxes_e", fluxes_e),
            ("peak_snr", peak_snr),
            ("total_snr", total_snr),
            ("centroid_sigma_px", centroid_sigma_px),
            ("clipping_fraction", clipping_fraction),
        ):
            _require_nonnegative_finite_entries(values, label=label)
        finite_clipping = clipping_fraction[np.isfinite(clipping_fraction)]
        if np.any(finite_clipping > 1.0):
            raise ValueError("clipping_fraction must be in [0, 1] where finite.")

        detector_frames = self.detector_frames
        if detector_frames is not None:
            detector_frames = _typed_tuple(
                detector_frames,
                DetectorFrame,
                label="detector_frames",
                expected_length=count,
            )
        optical_spots = self.optical_spots
        if optical_spots is not None:
            if not isinstance(optical_spots, SpotIntensityResult):
                raise ValueError("optical_spots must be a SpotIntensityResult or None.")
            if optical_spots.subaperture_ids != subaperture_ids:
                raise ValueError(
                    "optical_spots.subaperture_ids must match subaperture_ids."
                )

        object.__setattr__(self, "subaperture_ids", subaperture_ids)
        object.__setattr__(self, "centroids_xy_px", centroids_xy_px)
        object.__setattr__(
            self,
            "reference_centroids_xy_px",
            reference_centroids_xy_px,
        )
        object.__setattr__(self, "fluxes_e", fluxes_e)
        object.__setattr__(self, "valid_subapertures", valid_subapertures)
        object.__setattr__(self, "valid_by_flux", valid_by_flux)
        object.__setattr__(self, "valid_by_snr", valid_by_snr)
        object.__setattr__(self, "valid_by_uncertainty", valid_by_uncertainty)
        object.__setattr__(self, "valid_by_clipping", valid_by_clipping)
        object.__setattr__(self, "peak_snr", peak_snr)
        object.__setattr__(self, "total_snr", total_snr)
        object.__setattr__(self, "centroid_sigma_px", centroid_sigma_px)
        object.__setattr__(self, "clipping_fraction", clipping_fraction)
        object.__setattr__(self, "detector_frames", detector_frames)
        object.__setattr__(self, "optical_spots", optical_spots)


@dataclass(frozen=True)
class WfsMeasurement:
    vector: MeasurementVector
    valid_subapertures: np.ndarray | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    detector_telemetry: DetectorTelemetry | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.vector, MeasurementVector):
            raise ValueError("vector must be a MeasurementVector.")
        valid_subapertures = self.valid_subapertures
        if valid_subapertures is not None:
            valid_subapertures = _bool_array(
                valid_subapertures,
                label="valid_subapertures",
                ndim=1,
            )
            if valid_subapertures.size == 0:
                raise ValueError("valid_subapertures must not be empty.")
        metadata = _json_mapping(self.metadata, label="metadata")
        detector_telemetry = self.detector_telemetry
        if detector_telemetry is not None:
            if not isinstance(detector_telemetry, DetectorTelemetry):
                raise ValueError(
                    "detector_telemetry must be a DetectorTelemetry or None."
                )
            if valid_subapertures is not None:
                if not np.array_equal(
                    valid_subapertures,
                    detector_telemetry.valid_subapertures,
                ):
                    raise ValueError(
                        "valid_subapertures must match detector telemetry."
                    )

        object.__setattr__(self, "valid_subapertures", valid_subapertures)
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(self, "detector_telemetry", detector_telemetry)


@dataclass(frozen=True)
class SpotIntensityResult:
    unit_sum_spots: tuple[np.ndarray, ...]
    subaperture_ids: tuple[str, ...]
    relative_throughput: np.ndarray
    x_px: tuple[np.ndarray, ...]
    y_px: tuple[np.ndarray, ...]
    sampling: DetectorPlaneSampling
    normalization: Literal["unit_sum_per_subaperture"]

    def __post_init__(self) -> None:
        subaperture_ids = _validated_ids(
            self.subaperture_ids,
            label="subaperture_ids",
        )
        count = len(subaperture_ids)
        if not isinstance(self.sampling, DetectorPlaneSampling):
            raise ValueError("sampling must be a DetectorPlaneSampling.")
        normalization = _literal(
            self.normalization,
            frozenset({_SPOT_NORMALIZATION}),
            label="normalization",
        )
        spots = _array_tuple(
            self.unit_sum_spots,
            label="unit_sum_spots",
            expected_length=count,
            ndim=2,
        )
        x_px = _array_tuple(
            self.x_px,
            label="x_px",
            expected_length=count,
            ndim=1,
        )
        y_px = _array_tuple(
            self.y_px,
            label="y_px",
            expected_length=count,
            ndim=1,
        )
        relative_throughput = _length_float_array(
            self.relative_throughput,
            count,
            label="relative_throughput",
        )
        _require_all_finite(relative_throughput, label="relative_throughput")
        if np.any(relative_throughput < 0.0):
            raise ValueError("relative_throughput must be non-negative.")

        rows, columns = self.sampling.window_shape_px
        reference_x, reference_y = self.sampling.reference_pixel_xy
        expected_x = np.arange(columns, dtype=float) - reference_x
        expected_y = np.arange(rows, dtype=float) - reference_y
        for index, (spot, x_axis, y_axis) in enumerate(zip(spots, x_px, y_px)):
            _require_shape(
                spot,
                (rows, columns),
                label=f"unit_sum_spots[{index}]",
            )
            _require_all_finite(spot, label=f"unit_sum_spots[{index}]")
            if np.any(spot < 0.0):
                raise ValueError(
                    f"unit_sum_spots[{index}] must be non-negative."
                )
            if not math.isclose(
                float(np.sum(spot)),
                1.0,
                rel_tol=1.0e-9,
                abs_tol=1.0e-12,
            ):
                raise ValueError(f"unit_sum_spots[{index}] must sum to one.")
            _strict_axis(x_axis, columns, label=f"x_px[{index}]")
            _strict_axis(y_axis, rows, label=f"y_px[{index}]")
            if not np.allclose(x_axis, expected_x, rtol=0.0, atol=1.0e-12):
                raise ValueError(f"x_px[{index}] does not agree with sampling.")
            if not np.allclose(y_axis, expected_y, rtol=0.0, atol=1.0e-12):
                raise ValueError(f"y_px[{index}] does not agree with sampling.")

        object.__setattr__(self, "unit_sum_spots", spots)
        object.__setattr__(self, "subaperture_ids", subaperture_ids)
        object.__setattr__(self, "relative_throughput", relative_throughput)
        object.__setattr__(self, "x_px", x_px)
        object.__setattr__(self, "y_px", y_px)
        object.__setattr__(self, "normalization", normalization)


@dataclass(frozen=True)
class PsfResult:
    intensity: np.ndarray
    x_angle_rad: np.ndarray
    y_angle_rad: np.ndarray
    wavelength_m: float
    normalization: Literal["unit_total_flux"]
    backend_name: str
    sampling_metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        intensity = _nonnegative_finite_array(
            self.intensity,
            label="intensity",
            ndim=2,
        )
        rows, columns = intensity.shape
        x_angle_rad = _float_array(
            self.x_angle_rad,
            label="x_angle_rad",
            ndim=1,
        )
        y_angle_rad = _float_array(
            self.y_angle_rad,
            label="y_angle_rad",
            ndim=1,
        )
        _strict_axis(x_angle_rad, columns, label="x_angle_rad")
        _strict_axis(y_angle_rad, rows, label="y_angle_rad")
        if not math.isclose(
            float(np.sum(intensity)),
            1.0,
            rel_tol=1.0e-9,
            abs_tol=1.0e-12,
        ):
            raise ValueError("intensity must sum to one for unit_total_flux.")
        wavelength_m = _positive_finite_float(
            self.wavelength_m,
            label="wavelength_m",
        )
        normalization = _literal(
            self.normalization,
            frozenset({_PSF_NORMALIZATION}),
            label="normalization",
        )
        backend_name = _nonempty_string(self.backend_name, label="backend_name")
        sampling_metadata = _json_mapping(
            self.sampling_metadata,
            label="sampling_metadata",
        )

        object.__setattr__(self, "intensity", intensity)
        object.__setattr__(self, "x_angle_rad", x_angle_rad)
        object.__setattr__(self, "y_angle_rad", y_angle_rad)
        object.__setattr__(self, "wavelength_m", wavelength_m)
        object.__setattr__(self, "normalization", normalization)
        object.__setattr__(self, "backend_name", backend_name)
        object.__setattr__(self, "sampling_metadata", sampling_metadata)


@dataclass(frozen=True)
class DmCommandVector:
    values_opd_m: np.ndarray
    actuator_ids: tuple[str, ...]
    command_unit: Literal["m_opd_equivalent"]

    def __post_init__(self) -> None:
        actuator_ids = _validated_ids(self.actuator_ids, label="actuator_ids")
        values_opd_m = _float_array(
            self.values_opd_m,
            label="values_opd_m",
            ndim=1,
        )
        _require_shape(values_opd_m, (len(actuator_ids),), label="values_opd_m")
        _require_all_finite(values_opd_m, label="values_opd_m")
        command_unit = _literal(
            self.command_unit,
            frozenset({_COMMAND_UNIT}),
            label="command_unit",
        )

        object.__setattr__(self, "values_opd_m", values_opd_m)
        object.__setattr__(self, "actuator_ids", actuator_ids)
        object.__setattr__(self, "command_unit", command_unit)


@dataclass(frozen=True)
class DmSynthesisResult:
    correction_opd_m: np.ndarray
    requested_commands_opd_m: np.ndarray
    applied_commands_opd_m: np.ndarray
    actuator_ids: tuple[str, ...]
    saturated_mask: np.ndarray
    saturation_fraction: float
    command_unit: Literal["m_opd_equivalent"]
    config_hash: str

    def __post_init__(self) -> None:
        actuator_ids = _validated_ids(self.actuator_ids, label="actuator_ids")
        count = len(actuator_ids)
        correction_opd_m = _float_array(
            self.correction_opd_m,
            label="correction_opd_m",
            ndim=2,
        )
        _require_all_finite(correction_opd_m, label="correction_opd_m")
        requested_commands_opd_m = _length_float_array(
            self.requested_commands_opd_m,
            count,
            label="requested_commands_opd_m",
        )
        applied_commands_opd_m = _length_float_array(
            self.applied_commands_opd_m,
            count,
            label="applied_commands_opd_m",
        )
        _require_all_finite(
            requested_commands_opd_m,
            label="requested_commands_opd_m",
        )
        _require_all_finite(
            applied_commands_opd_m,
            label="applied_commands_opd_m",
        )
        saturated_mask = _length_bool_array(
            self.saturated_mask,
            count,
            label="saturated_mask",
        )
        saturation_fraction = _finite_float(
            self.saturation_fraction,
            label="saturation_fraction",
        )
        if not 0.0 <= saturation_fraction <= 1.0:
            raise ValueError("saturation_fraction must be in [0, 1].")
        expected_fraction = float(np.mean(saturated_mask))
        if not math.isclose(
            saturation_fraction,
            expected_fraction,
            rel_tol=0.0,
            abs_tol=1.0e-12,
        ):
            raise ValueError(
                "saturation_fraction must equal the fraction of saturated actuators."
            )
        command_unit = _literal(
            self.command_unit,
            frozenset({_COMMAND_UNIT}),
            label="command_unit",
        )
        config_hash = _nonempty_string(self.config_hash, label="config_hash")

        object.__setattr__(self, "correction_opd_m", correction_opd_m)
        object.__setattr__(
            self,
            "requested_commands_opd_m",
            requested_commands_opd_m,
        )
        object.__setattr__(self, "applied_commands_opd_m", applied_commands_opd_m)
        object.__setattr__(self, "actuator_ids", actuator_ids)
        object.__setattr__(self, "saturated_mask", saturated_mask)
        object.__setattr__(self, "saturation_fraction", saturation_fraction)
        object.__setattr__(self, "command_unit", command_unit)
        object.__setattr__(self, "config_hash", config_hash)


@dataclass(frozen=True)
class ReconstructionEstimate:
    delta_coordinates_opd_m: np.ndarray
    coordinate_ids: tuple[str, ...]
    coordinate_kind: Literal["modal_opd", "dm_command_opd"]
    coordinate_unit: Literal["m_opd_rms", "m_opd_equivalent"]
    measurement_unit: MeasurementUnit
    usable_rows: np.ndarray
    reconstructed_signal: np.ndarray
    residual_signal: np.ndarray
    coordinate_norm_m: float
    residual_norm: float
    kept_modes: int | None
    singular_values: np.ndarray
    matrix_hash: str

    def __post_init__(self) -> None:
        coordinate_ids = _validated_ids(self.coordinate_ids, label="coordinate_ids")
        coordinate_count = len(coordinate_ids)
        delta_coordinates_opd_m = _length_float_array(
            self.delta_coordinates_opd_m,
            coordinate_count,
            label="delta_coordinates_opd_m",
        )
        _require_all_finite(
            delta_coordinates_opd_m,
            label="delta_coordinates_opd_m",
        )
        coordinate_kind = _literal(
            self.coordinate_kind,
            _COORDINATE_KINDS,
            label="coordinate_kind",
        )
        coordinate_unit = _literal(
            self.coordinate_unit,
            _COORDINATE_UNITS,
            label="coordinate_unit",
        )
        expected_coordinate_unit = (
            "m_opd_rms" if coordinate_kind == "modal_opd" else "m_opd_equivalent"
        )
        if coordinate_unit != expected_coordinate_unit:
            raise ValueError(
                f"coordinate_kind={coordinate_kind!r} requires "
                f"coordinate_unit={expected_coordinate_unit!r}."
            )
        measurement_unit = _literal(
            self.measurement_unit,
            _MEASUREMENT_UNITS,
            label="measurement_unit",
        )
        usable_rows = _bool_array(self.usable_rows, label="usable_rows", ndim=1)
        if usable_rows.size == 0:
            raise ValueError("usable_rows must not be empty.")
        reconstructed_signal = _float_array(
            self.reconstructed_signal,
            label="reconstructed_signal",
            ndim=1,
        )
        residual_signal = _float_array(
            self.residual_signal,
            label="residual_signal",
            ndim=1,
        )
        _require_shape(
            reconstructed_signal,
            usable_rows.shape,
            label="reconstructed_signal",
        )
        _require_shape(
            residual_signal,
            usable_rows.shape,
            label="residual_signal",
        )
        _finite_where(
            reconstructed_signal,
            usable_rows,
            label="reconstructed_signal",
        )
        _finite_where(residual_signal, usable_rows, label="residual_signal")
        if np.any(~np.isnan(reconstructed_signal[~usable_rows])):
            raise ValueError(
                "reconstructed_signal must be NaN for every unusable row."
            )
        if np.any(~np.isnan(residual_signal[~usable_rows])):
            raise ValueError(
                "residual_signal must be NaN for every unusable row."
            )

        coordinate_norm_m = _nonnegative_finite_float(
            self.coordinate_norm_m,
            label="coordinate_norm_m",
        )
        residual_norm = _nonnegative_finite_float(
            self.residual_norm,
            label="residual_norm",
        )

        singular_values = _float_array(
            self.singular_values,
            label="singular_values",
            ndim=1,
        )
        _require_all_finite(singular_values, label="singular_values")
        if np.any(singular_values < 0.0):
            raise ValueError("singular_values must be non-negative.")
        if np.any(np.diff(singular_values) > 0.0):
            raise ValueError("singular_values must be in non-increasing order.")
        kept_modes = self.kept_modes
        if kept_modes is not None:
            if isinstance(kept_modes, bool) or not isinstance(kept_modes, int):
                raise ValueError("kept_modes must be an integer or None.")
            maximum_modes = min(
                coordinate_count,
                int(np.count_nonzero(usable_rows)),
                singular_values.size,
            )
            if not 0 <= kept_modes <= maximum_modes:
                raise ValueError(
                    f"kept_modes must be in [0, {maximum_modes}] for this result."
                )
        matrix_hash = _nonempty_string(self.matrix_hash, label="matrix_hash")

        object.__setattr__(
            self,
            "delta_coordinates_opd_m",
            delta_coordinates_opd_m,
        )
        object.__setattr__(self, "coordinate_ids", coordinate_ids)
        object.__setattr__(self, "coordinate_kind", coordinate_kind)
        object.__setattr__(self, "coordinate_unit", coordinate_unit)
        object.__setattr__(self, "measurement_unit", measurement_unit)
        object.__setattr__(self, "usable_rows", usable_rows)
        object.__setattr__(self, "reconstructed_signal", reconstructed_signal)
        object.__setattr__(self, "residual_signal", residual_signal)
        object.__setattr__(self, "coordinate_norm_m", coordinate_norm_m)
        object.__setattr__(self, "residual_norm", residual_norm)
        object.__setattr__(self, "kept_modes", kept_modes)
        object.__setattr__(self, "singular_values", singular_values)
        object.__setattr__(self, "matrix_hash", matrix_hash)


def _float_array(value: object, *, label: str, ndim: int) -> np.ndarray:
    if not isinstance(value, np.ndarray):
        raise ValueError(f"{label} must be a numpy.ndarray.")
    if np.issubdtype(value.dtype, np.bool_) or not np.issubdtype(
        value.dtype,
        np.number,
    ):
        raise ValueError(f"{label} must contain real numeric values.")
    if np.issubdtype(value.dtype, np.complexfloating):
        raise ValueError(f"{label} must contain real numeric values.")
    array = _immutable_array_copy(value, dtype=float)
    if array.ndim != ndim:
        raise ValueError(f"{label} must be {ndim}-dimensional; got {array.shape}.")
    return array


def _bool_array(value: object, *, label: str, ndim: int) -> np.ndarray:
    if not isinstance(value, np.ndarray) or value.dtype != np.dtype(bool):
        raise ValueError(f"{label} must be a boolean numpy.ndarray.")
    array = _immutable_array_copy(value, dtype=bool)
    if array.ndim != ndim:
        raise ValueError(f"{label} must be {ndim}-dimensional; got {array.shape}.")
    return array


def _immutable_array_copy(value: object, *, dtype: Any) -> np.ndarray:
    """Copy an array onto an immutable bytes buffer.

    A normal owning ndarray can have its write flag re-enabled.  Rebuilding
    from ``bytes`` keeps the public result read-only even after a caller tries
    ``setflags(write=True)``.
    """

    contiguous = np.ascontiguousarray(np.array(value, dtype=dtype, copy=True))
    immutable = np.frombuffer(contiguous.tobytes(order="C"), dtype=contiguous.dtype)
    return immutable.reshape(contiguous.shape)


def _length_float_array(value: object, length: int, *, label: str) -> np.ndarray:
    array = _float_array(value, label=label, ndim=1)
    _require_shape(array, (length,), label=label)
    return array


def _length_bool_array(value: object, length: int, *, label: str) -> np.ndarray:
    array = _bool_array(value, label=label, ndim=1)
    _require_shape(array, (length,), label=label)
    return array


def _matching_nonnegative_array(
    value: object,
    shape: tuple[int, ...],
    *,
    label: str,
) -> np.ndarray:
    array = _nonnegative_finite_array(value, label=label, ndim=len(shape))
    _require_shape(array, shape, label=label)
    return array


def _matching_bool_array(
    value: object,
    shape: tuple[int, ...],
    *,
    label: str,
) -> np.ndarray:
    array = _bool_array(value, label=label, ndim=len(shape))
    _require_shape(array, shape, label=label)
    return array


def _nonnegative_finite_array(
    value: object,
    *,
    label: str,
    ndim: int,
) -> np.ndarray:
    array = _float_array(value, label=label, ndim=ndim)
    _require_all_finite(array, label=label)
    if np.any(array < 0.0):
        raise ValueError(f"{label} must be non-negative.")
    return array


def _array_tuple(
    value: object,
    *,
    label: str,
    expected_length: int,
    ndim: int,
) -> tuple[np.ndarray, ...]:
    if not isinstance(value, tuple):
        raise ValueError(f"{label} must be a tuple of numpy arrays.")
    if len(value) != expected_length:
        raise ValueError(
            f"{label} must contain {expected_length} arrays; got {len(value)}."
        )
    return tuple(
        _float_array(item, label=f"{label}[{index}]", ndim=ndim)
        for index, item in enumerate(value)
    )


def _typed_tuple(
    value: object,
    item_type: type,
    *,
    label: str,
    expected_length: int,
) -> tuple[Any, ...]:
    if not isinstance(value, tuple):
        raise ValueError(f"{label} must be a tuple.")
    if len(value) != expected_length:
        raise ValueError(
            f"{label} must contain {expected_length} items; got {len(value)}."
        )
    for index, item in enumerate(value):
        if not isinstance(item, item_type):
            raise ValueError(
                f"{label}[{index}] must be a {item_type.__name__}."
            )
    return value


def _validated_ids(value: object, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise ValueError(f"{label} must be a tuple of strings.")
    if not value:
        raise ValueError(f"{label} must not be empty.")
    for index, identifier in enumerate(value):
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError(f"{label}[{index}] must be a non-empty string.")
    if len(set(value)) != len(value):
        raise ValueError(f"{label} must not contain duplicate identifiers.")
    return cast(tuple[str, ...], value)


def _require_shape(
    array: np.ndarray,
    expected: tuple[int, ...],
    *,
    label: str,
) -> None:
    if array.shape != expected:
        raise ValueError(f"{label} shape {array.shape} must be {expected}.")


def _require_all_finite(array: np.ndarray, *, label: str) -> None:
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{label} must contain only finite values.")


def _finite_where(array: np.ndarray, valid: np.ndarray, *, label: str) -> None:
    if np.any(np.isinf(array)):
        raise ValueError(f"{label} must not contain infinite values.")
    if not np.all(np.isfinite(array[valid])):
        raise ValueError(f"{label} must be finite where its validity mask is true.")


def _finite_rows(array: np.ndarray, valid_rows: np.ndarray, *, label: str) -> None:
    if np.any(np.isinf(array)):
        raise ValueError(f"{label} must not contain infinite values.")
    if not np.all(np.isfinite(array[valid_rows, :])):
        raise ValueError(f"{label} must be finite for valid rows.")


def _require_nonnegative_finite_entries(array: np.ndarray, *, label: str) -> None:
    finite_values = array[np.isfinite(array)]
    if np.any(finite_values < 0.0):
        raise ValueError(f"{label} must be non-negative where finite.")


def _strict_axis(array: np.ndarray, length: int, *, label: str) -> None:
    _require_shape(array, (length,), label=label)
    _require_all_finite(array, label=label)
    if length > 1 and not np.all(np.diff(array) > 0.0):
        raise ValueError(f"{label} must be strictly increasing.")


def _positive_integer_pair(value: object, *, label: str) -> tuple[int, int]:
    if not isinstance(value, tuple) or len(value) != 2:
        raise ValueError(f"{label} must be a two-item tuple.")
    output: list[int] = []
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
            raise ValueError(f"{label}[{index}] must be a positive integer.")
        output.append(item)
    return (output[0], output[1])


def _finite_float_pair(
    value: object,
    *,
    label: str,
    positive: bool = False,
) -> tuple[float, float]:
    if not isinstance(value, tuple) or len(value) != 2:
        raise ValueError(f"{label} must be a two-item tuple.")
    first = _finite_float(value[0], label=f"{label}[0]")
    second = _finite_float(value[1], label=f"{label}[1]")
    if positive and (first <= 0.0 or second <= 0.0):
        raise ValueError(f"{label} entries must be positive.")
    return (first, second)


def _finite_float(value: object, *, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite real scalar.")
    try:
        output = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite real scalar.") from exc
    if not math.isfinite(output):
        raise ValueError(f"{label} must be finite.")
    return output


def _positive_finite_float(value: object, *, label: str) -> float:
    output = _finite_float(value, label=label)
    if output <= 0.0:
        raise ValueError(f"{label} must be positive.")
    return output


def _nonnegative_finite_float(value: object, *, label: str) -> float:
    output = _finite_float(value, label=label)
    if output < 0.0:
        raise ValueError(f"{label} must be non-negative.")
    return output


def _literal(value: object, allowed: frozenset[str], *, label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{label} must be one of {sorted(allowed)}; got {value!r}.")
    return value


def _nonempty_string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string.")
    return value


def _string_mapping(value: object, *, label: str) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping of strings to strings.")
    frozen: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError(f"{label} keys must be non-empty strings.")
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{label}[{key!r}] must be a non-empty string.")
        frozen[key] = item
    return cast(Mapping[str, str], MappingProxyType(frozen))


def _json_mapping(value: object, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping.")
    return cast(Mapping[str, Any], _freeze_json_value(value, path=label))


def _freeze_json_value(value: object, *, path: str) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite JSON number.")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} contains a non-string mapping key.")
            frozen[key] = _freeze_json_value(item, path=f"{path}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_json_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        )
    raise ValueError(
        f"{path} contains non-JSON-serializable value {type(value).__name__}."
    )
