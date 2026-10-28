"""Executable contracts for backend-neutral AO result dataclasses."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import FrozenInstanceError, fields, is_dataclass, replace
import json
from typing import get_args

import numpy as np
import pytest

import shwfs_ao.core.types as result_types
from shwfs_ao.core.hashing import detector_plane_sampling_hash
from shwfs_ao.core.types import (
    DetectorFrame,
    DetectorPlaneSampling,
    DetectorTelemetry,
    DmCommandVector,
    DmSynthesisResult,
    MeasurementUnit,
    MeasurementVector,
    PsfResult,
    ReconstructionEstimate,
    SpotIntensityResult,
    WfsMeasurement,
)


def _sampling() -> DetectorPlaneSampling:
    window_shape_px = (3, 4)
    pixel_scale_rad = (2.0e-7, 2.5e-7)
    reference_pixel_xy = (1.5, 1.0)
    return DetectorPlaneSampling(
        window_shape_px=window_shape_px,
        pixel_scale_rad=pixel_scale_rad,
        reference_pixel_xy=reference_pixel_xy,
        sampling_hash=detector_plane_sampling_hash(
            window_shape_px=window_shape_px,
            pixel_scale_rad=pixel_scale_rad,
            reference_pixel_xy=reference_pixel_xy,
        ),
    )


def _frame(offset: float = 0.0) -> DetectorFrame:
    shape = (2, 3)
    return DetectorFrame(
        image_e=np.full(shape, 10.0 + offset),
        expected_source_e=np.full(shape, 8.0),
        expected_background_e=np.full(shape, 2.0),
        expected_pre_poisson_e=np.full(shape, 10.0),
        prnu_response=np.ones(shape),
        saturated_mask=np.zeros(shape, dtype=bool),
        bad_pixel_mask=np.zeros(shape, dtype=bool),
        negative_clipped_mask=np.zeros(shape, dtype=bool),
        random_stream_ids={"poisson": "stream-poisson-0"},
    )


def _spots(ids: tuple[str, ...] = ("subap-0", "subap-1")) -> SpotIntensityResult:
    sampling = _sampling()
    spot = np.full(sampling.window_shape_px, 1.0 / 12.0)
    return SpotIntensityResult(
        unit_sum_spots=tuple(spot.copy() for _ in ids),
        subaperture_ids=ids,
        relative_throughput=np.linspace(0.8, 1.0, len(ids)),
        x_px=tuple(np.arange(4, dtype=float) - 1.5 for _ in ids),
        y_px=tuple(np.arange(3, dtype=float) - 1.0 for _ in ids),
        sampling=sampling,
        normalization="unit_sum_per_subaperture",
    )


def _telemetry(*, include_optional: bool = False) -> DetectorTelemetry:
    ids = ("subap-0", "subap-1")
    kwargs = {}
    if include_optional:
        kwargs = {
            "detector_frames": (_frame(), _frame(1.0)),
            "optical_spots": _spots(ids),
        }
    return DetectorTelemetry(
        subaperture_ids=ids,
        centroids_xy_px=np.array([[0.1, -0.2], [np.nan, np.nan]]),
        reference_centroids_xy_px=np.array([[0.0, 0.0], [0.2, -0.2]]),
        fluxes_e=np.array([100.0, np.nan]),
        valid_subapertures=np.array([True, False]),
        valid_by_flux=np.array([True, False]),
        valid_by_snr=np.array([True, False]),
        valid_by_uncertainty=np.array([True, False]),
        valid_by_clipping=np.array([True, False]),
        peak_snr=np.array([12.0, np.nan]),
        total_snr=np.array([20.0, np.nan]),
        centroid_sigma_px=np.array([0.05, np.nan]),
        clipping_fraction=np.array([0.0, np.nan]),
        **kwargs,
    )


def _measurement_vector() -> MeasurementVector:
    return MeasurementVector(
        values=np.array([0.1, np.nan, -0.2, 0.3]),
        valid_rows=np.array([True, False, True, True]),
        row_ids=("subap-0:x", "subap-0:y", "subap-1:x", "subap-1:y"),
        measurement_unit="pixel",
    )


def _psf() -> PsfResult:
    intensity = np.arange(1.0, 7.0).reshape(2, 3)
    intensity /= np.sum(intensity)
    return PsfResult(
        intensity=intensity,
        x_angle_rad=np.array([-2.0e-6, 0.0, 2.0e-6]),
        y_angle_rad=np.array([-1.0e-6, 1.0e-6]),
        wavelength_m=1.65e-6,
        normalization="unit_total_flux",
        backend_name="native",
        sampling_metadata={"pad_factor": 2, "axes": ["x", "y"]},
    )


def _dm_command() -> DmCommandVector:
    return DmCommandVector(
        values_opd_m=np.array([10.0e-9, -5.0e-9]),
        actuator_ids=("actuator-0", "actuator-1"),
        command_unit="m_opd_equivalent",
    )


def _dm_synthesis() -> DmSynthesisResult:
    return DmSynthesisResult(
        correction_opd_m=np.array([[1.0e-9, -1.0e-9], [2.0e-9, -2.0e-9]]),
        requested_commands_opd_m=np.array([10.0e-9, -12.0e-9]),
        applied_commands_opd_m=np.array([8.0e-9, -12.0e-9]),
        actuator_ids=("actuator-0", "actuator-1"),
        saturated_mask=np.array([True, False]),
        saturation_fraction=0.5,
        command_unit="m_opd_equivalent",
        config_hash="dm-config-123",
    )


def _reconstruction() -> ReconstructionEstimate:
    return ReconstructionEstimate(
        delta_coordinates_opd_m=np.array([3.0e-9, 4.0e-9]),
        coordinate_ids=("mode-0", "mode-1"),
        coordinate_kind="modal_opd",
        coordinate_unit="m_opd_rms",
        measurement_unit="pixel",
        usable_rows=np.array([True, False, True]),
        reconstructed_signal=np.array([0.8, np.nan, -0.1]),
        residual_signal=np.array([0.2, np.nan, 0.1]),
        coordinate_norm_m=9.0e-9,
        residual_norm=0.75,
        kept_modes=2,
        singular_values=np.array([4.0, 1.0]),
        matrix_hash="matrix-123",
    )


def _all_results() -> tuple[object, ...]:
    return (
        _measurement_vector(),
        _sampling(),
        _frame(),
        _telemetry(include_optional=True),
        WfsMeasurement(
            _measurement_vector(),
            np.array([True, False]),
            {"backend": "native"},
            _telemetry(),
        ),
        _spots(),
        _psf(),
        _dm_command(),
        _dm_synthesis(),
        _reconstruction(),
    )


def _jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value


def test_module_exports_exact_section_4_1_api() -> None:
    assert result_types.__all__ == (
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
    assert get_args(MeasurementUnit) == ("pixel", "rad_wavefront_slope")


def test_all_ten_result_classes_are_frozen_dataclasses_with_exact_field_order() -> None:
    expected = {
        MeasurementVector: ("values", "valid_rows", "row_ids", "measurement_unit"),
        DetectorPlaneSampling: (
            "window_shape_px",
            "pixel_scale_rad",
            "reference_pixel_xy",
            "sampling_hash",
        ),
        DetectorFrame: (
            "image_e",
            "expected_source_e",
            "expected_background_e",
            "expected_pre_poisson_e",
            "prnu_response",
            "saturated_mask",
            "bad_pixel_mask",
            "negative_clipped_mask",
            "random_stream_ids",
        ),
        DetectorTelemetry: (
            "subaperture_ids",
            "centroids_xy_px",
            "reference_centroids_xy_px",
            "fluxes_e",
            "valid_subapertures",
            "valid_by_flux",
            "valid_by_snr",
            "valid_by_uncertainty",
            "valid_by_clipping",
            "peak_snr",
            "total_snr",
            "centroid_sigma_px",
            "clipping_fraction",
            "detector_frames",
            "optical_spots",
        ),
        WfsMeasurement: (
            "vector",
            "valid_subapertures",
            "metadata",
            "detector_telemetry",
        ),
        SpotIntensityResult: (
            "unit_sum_spots",
            "subaperture_ids",
            "relative_throughput",
            "x_px",
            "y_px",
            "sampling",
            "normalization",
        ),
        PsfResult: (
            "intensity",
            "x_angle_rad",
            "y_angle_rad",
            "wavelength_m",
            "normalization",
            "backend_name",
            "sampling_metadata",
        ),
        DmCommandVector: ("values_opd_m", "actuator_ids", "command_unit"),
        DmSynthesisResult: (
            "correction_opd_m",
            "requested_commands_opd_m",
            "applied_commands_opd_m",
            "actuator_ids",
            "saturated_mask",
            "saturation_fraction",
            "command_unit",
            "config_hash",
        ),
        ReconstructionEstimate: (
            "delta_coordinates_opd_m",
            "coordinate_ids",
            "coordinate_kind",
            "coordinate_unit",
            "measurement_unit",
            "usable_rows",
            "reconstructed_signal",
            "residual_signal",
            "coordinate_norm_m",
            "residual_norm",
            "kept_modes",
            "singular_values",
            "matrix_hash",
        ),
    }
    for result_class, field_names in expected.items():
        assert is_dataclass(result_class)
        assert result_class.__dataclass_params__.frozen is True
        assert tuple(item.name for item in fields(result_class)) == field_names


def test_every_stored_array_is_read_only() -> None:
    arrays: list[np.ndarray] = []
    for result in _all_results():
        for item in fields(result):
            value = getattr(result, item.name)
            if isinstance(value, np.ndarray):
                arrays.append(value)
            elif isinstance(value, tuple):
                arrays.extend(entry for entry in value if isinstance(entry, np.ndarray))
    assert arrays
    assert all(not array.flags.writeable for array in arrays)
    for array in arrays:
        with pytest.raises(ValueError):
            array.flat[0] = array.flat[0]
        with pytest.raises(ValueError):
            array.setflags(write=True)


def test_array_inputs_are_defensively_copied_and_dataclass_fields_are_frozen() -> None:
    values = np.array([1.0, 2.0])
    valid = np.array([True, True])
    result = MeasurementVector(values, valid, ("row-0", "row-1"), "pixel")
    values[0] = 999.0
    valid[0] = False

    assert result.values.tolist() == [1.0, 2.0]
    assert result.valid_rows.tolist() == [True, True]
    assert not np.shares_memory(result.values, values)
    assert not np.shares_memory(result.valid_rows, valid)
    with pytest.raises(FrozenInstanceError):
        result.row_ids = ("changed",)  # type: ignore[misc]


def test_measurement_vector_allows_nan_only_in_invalid_rows() -> None:
    result = _measurement_vector()
    assert np.isnan(result.values[1])

    with pytest.raises(ValueError, match="finite.*validity|finite where"):
        replace(result, valid_rows=np.ones(4, dtype=bool))
    with pytest.raises(ValueError, match="infinite"):
        replace(result, values=np.array([0.1, np.inf, -0.2, 0.3]))


@pytest.mark.parametrize("unit", ["pixels", "rad", "", None])
def test_measurement_vector_rejects_unregistered_units(unit: object) -> None:
    with pytest.raises(ValueError, match="measurement_unit"):
        MeasurementVector(
            np.array([1.0]),
            np.array([True]),
            ("row-0",),
            unit,  # type: ignore[arg-type]
        )


def test_measurement_vector_rejects_shape_and_row_identity_errors() -> None:
    with pytest.raises(ValueError, match="shape"):
        MeasurementVector(
            np.array([1.0, 2.0]),
            np.array([True]),
            ("row-0", "row-1"),
            "pixel",
        )
    with pytest.raises(ValueError, match="duplicate"):
        MeasurementVector(
            np.array([1.0, 2.0]),
            np.array([True, True]),
            ("row-0", "row-0"),
            "pixel",
        )


def test_detector_sampling_validates_shape_scale_reference_and_hash() -> None:
    assert _sampling().window_shape_px == (3, 4)
    off_canvas_fields = {
        "window_shape_px": (3, 4),
        "pixel_scale_rad": (1.0, 1.0),
        "reference_pixel_xy": (-5.0, 20.0),
    }
    DetectorPlaneSampling(
        **off_canvas_fields,
        sampling_hash=detector_plane_sampling_hash(**off_canvas_fields),
    )

    for kwargs, match in (
        ({"window_shape_px": (3, 0)}, "positive integer"),
        ({"pixel_scale_rad": (1.0, 0.0)}, "positive"),
        ({"reference_pixel_xy": (0.0, np.nan)}, "finite"),
        ({"sampling_hash": "  "}, "sampling_hash"),
    ):
        values = {
            "window_shape_px": (3, 4),
            "pixel_scale_rad": (1.0, 1.0),
            "reference_pixel_xy": (0.0, 0.0),
            "sampling_hash": detector_plane_sampling_hash(
                window_shape_px=(3, 4),
                pixel_scale_rad=(1.0, 1.0),
                reference_pixel_xy=(0.0, 0.0),
            ),
        }
        values.update(kwargs)
        with pytest.raises(ValueError, match=match):
            DetectorPlaneSampling(**values)
    with pytest.raises(ValueError, match="must match"):
        DetectorPlaneSampling((3, 4), (1.0, 1.0), (0.0, 0.0), "wrong-hash")


def test_detector_frame_accepts_finite_negative_unclipped_image_samples() -> None:
    frame = replace(
        _frame(),
        image_e=np.array([[-0.25, 1.0, 2.0], [3.0, 4.0, 5.0]]),
    )
    assert frame.image_e[0, 0] == pytest.approx(-0.25)


def test_detector_frame_rejects_mismatched_nonfinite_or_nonphysical_planes() -> None:
    frame = _frame()
    with pytest.raises(ValueError, match="shape"):
        replace(frame, prnu_response=np.ones((2, 2)))
    with pytest.raises(ValueError, match="finite"):
        replace(frame, image_e=np.full((2, 3), np.nan))
    with pytest.raises(ValueError, match="non-negative"):
        replace(frame, expected_source_e=np.full((2, 3), -1.0))
    with pytest.raises(ValueError, match="boolean"):
        replace(frame, bad_pixel_mask=np.zeros((2, 3), dtype=int))


def test_detector_frame_stream_ids_are_immutable_and_string_only() -> None:
    stream_ids = {"poisson": "stream-0"}
    frame = replace(_frame(), random_stream_ids=stream_ids)
    stream_ids["poisson"] = "changed"

    assert frame.random_stream_ids["poisson"] == "stream-0"
    assert json.loads(json.dumps(dict(frame.random_stream_ids))) == {
        "poisson": "stream-0"
    }
    with pytest.raises(TypeError):
        frame.random_stream_ids["read"] = "stream-1"  # type: ignore[index]
    with pytest.raises(TypeError):
        dict.__setitem__(frame.random_stream_ids, "read", "stream-1")
    with pytest.raises(ValueError, match="random_stream_ids"):
        replace(frame, random_stream_ids={"poisson": 1})  # type: ignore[dict-item]


def test_detector_telemetry_preserves_nan_only_behind_relevant_validity() -> None:
    telemetry = _telemetry()
    assert np.isnan(telemetry.centroids_xy_px[1]).all()

    with pytest.raises(ValueError, match="centroids.*valid"):
        replace(
            telemetry,
            valid_subapertures=np.array([True, True]),
            valid_by_flux=np.array([True, True]),
            valid_by_snr=np.array([True, True]),
            valid_by_uncertainty=np.array([True, True]),
            valid_by_clipping=np.array([True, True]),
        )
    with pytest.raises(ValueError, match="fluxes.*validity"):
        replace(telemetry, valid_by_flux=np.array([True, True]))
    with pytest.raises(ValueError, match="infinite"):
        replace(telemetry, peak_snr=np.array([12.0, np.inf]))


def test_detector_telemetry_validates_aggregate_masks_shapes_and_ranges() -> None:
    telemetry = _telemetry()
    conservative = replace(telemetry, valid_subapertures=np.array([False, False]))
    assert not np.any(conservative.valid_subapertures)
    with pytest.raises(ValueError, match="cannot be true"):
        replace(
            telemetry,
            valid_subapertures=np.array([True, True]),
            centroids_xy_px=np.zeros((2, 2)),
        )
    with pytest.raises(ValueError, match="shape"):
        replace(telemetry, total_snr=np.array([10.0]))
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        replace(telemetry, clipping_fraction=np.array([1.2, np.nan]))
    with pytest.raises(ValueError, match="duplicate"):
        replace(telemetry, subaperture_ids=("same", "same"))


def test_detector_telemetry_allows_undefined_snr_when_quality_is_disabled() -> None:
    telemetry = replace(
        _telemetry(),
        peak_snr=np.array([np.nan, np.nan]),
        total_snr=np.array([np.nan, np.nan]),
        valid_by_snr=np.array([True, False]),
    )

    assert telemetry.valid_subapertures.tolist() == [True, False]
    assert np.isnan(telemetry.peak_snr).all()


def test_detector_telemetry_optional_payloads_follow_subaperture_identity() -> None:
    assert len(_telemetry(include_optional=True).detector_frames or ()) == 2

    with pytest.raises(ValueError, match="detector_frames.*2"):
        replace(_telemetry(), detector_frames=(_frame(),))
    with pytest.raises(ValueError, match="subaperture_ids"):
        replace(_telemetry(), optical_spots=_spots(("other-0", "other-1")))


def test_wfs_measurement_freezes_nested_json_metadata_without_backend_objects() -> None:
    metadata = {"backend": "native", "settings": {"padding": [2, 4]}}
    result = WfsMeasurement(_measurement_vector(), metadata=metadata)
    metadata["settings"]["padding"][0] = 999  # type: ignore[index]

    assert result.metadata["settings"]["padding"] == (2, 4)
    assert json.loads(json.dumps(_jsonable(result.metadata))) == {
        "backend": "native",
        "settings": {"padding": [2, 4]},
    }
    with pytest.raises(TypeError):
        result.metadata["new"] = 1  # type: ignore[index]
    with pytest.raises(TypeError):
        result.metadata["settings"]["padding"] = ()  # type: ignore[index]
    with pytest.raises(TypeError):
        dict.__setitem__(result.metadata, "new", 1)
    with pytest.raises(ValueError, match="non-JSON"):
        WfsMeasurement(_measurement_vector(), metadata={"backend": object()})
    with pytest.raises(ValueError, match="non-finite"):
        WfsMeasurement(_measurement_vector(), metadata={"metric": np.nan})


def test_wfs_measurement_valid_subapertures_must_match_detector_telemetry() -> None:
    telemetry = _telemetry()
    result = WfsMeasurement(
        _measurement_vector(),
        np.array([True, False]),
        detector_telemetry=telemetry,
    )
    assert np.array_equal(result.valid_subapertures, telemetry.valid_subapertures)

    with pytest.raises(ValueError, match="match detector telemetry"):
        replace(result, valid_subapertures=np.array([False, True]))


def test_spot_result_enforces_full_canvas_nonnegative_unit_sum_spots() -> None:
    spots = _spots()
    assert all(spot.shape == (3, 4) for spot in spots.unit_sum_spots)
    assert all(np.sum(spot) == pytest.approx(1.0) for spot in spots.unit_sum_spots)

    bad_shape = list(spots.unit_sum_spots)
    bad_shape[0] = np.full((2, 4), 1.0 / 8.0)
    with pytest.raises(ValueError, match="shape"):
        replace(spots, unit_sum_spots=tuple(bad_shape))
    negative = np.full((3, 4), 1.0 / 12.0)
    negative[0, 0] = -0.1
    negative[0, 1] += 0.1 + 1.0 / 12.0
    with pytest.raises(ValueError, match="non-negative"):
        replace(spots, unit_sum_spots=(negative, spots.unit_sum_spots[1]))
    not_normalized = np.full((3, 4), 1.0)
    with pytest.raises(ValueError, match="sum to one"):
        replace(spots, unit_sum_spots=(not_normalized, spots.unit_sum_spots[1]))


def test_spot_result_validates_axes_throughput_identity_and_normalization() -> None:
    spots = _spots()
    with pytest.raises(ValueError, match="strictly increasing"):
        replace(
            spots,
            x_px=(np.array([0.0, 1.0, 1.0, 2.0]), spots.x_px[1]),
        )
    with pytest.raises(ValueError, match="shape"):
        replace(spots, y_px=(np.array([0.0, 1.0]), spots.y_px[1]))
    with pytest.raises(ValueError, match="agree with sampling"):
        replace(
            spots,
            x_px=(np.arange(4, dtype=float), spots.x_px[1]),
        )
    with pytest.raises(ValueError, match="non-negative"):
        replace(spots, relative_throughput=np.array([1.0, -0.1]))
    with pytest.raises(ValueError, match="duplicate"):
        replace(spots, subaperture_ids=("same", "same"))
    with pytest.raises(ValueError, match="normalization"):
        replace(spots, normalization="peak_one")


def test_psf_result_validates_intensity_axes_units_and_metadata() -> None:
    psf = _psf()
    assert np.sum(psf.intensity) == pytest.approx(1.0)
    assert json.loads(json.dumps(dict(psf.sampling_metadata)))["pad_factor"] == 2

    with pytest.raises(ValueError, match="sum to one"):
        replace(psf, intensity=np.ones((2, 3)))
    with pytest.raises(ValueError, match="non-negative"):
        replace(psf, intensity=np.array([[-0.1, 0.3, 0.3], [0.2, 0.2, 0.1]]))
    with pytest.raises(ValueError, match="strictly increasing"):
        replace(psf, x_angle_rad=np.array([-1.0, -1.0, 1.0]))
    with pytest.raises(ValueError, match="shape"):
        replace(psf, y_angle_rad=np.array([-1.0, 0.0, 1.0]))
    with pytest.raises(ValueError, match="wavelength_m"):
        replace(psf, wavelength_m=0.0)
    with pytest.raises(ValueError, match="normalization"):
        replace(psf, normalization="peak_one")
    with pytest.raises(ValueError, match="backend_name"):
        replace(psf, backend_name="")


def test_dm_command_vector_validates_identity_shape_units_and_finiteness() -> None:
    command = _dm_command()
    assert command.values_opd_m.shape == (2,)

    with pytest.raises(ValueError, match="shape"):
        replace(command, values_opd_m=np.array([1.0]))
    with pytest.raises(ValueError, match="finite"):
        replace(command, values_opd_m=np.array([1.0, np.nan]))
    with pytest.raises(ValueError, match="duplicate"):
        replace(command, actuator_ids=("same", "same"))
    with pytest.raises(ValueError, match="command_unit"):
        replace(command, command_unit="nm_surface")


def test_dm_synthesis_validates_commands_saturation_units_and_hash() -> None:
    synthesis = _dm_synthesis()
    assert synthesis.saturation_fraction == pytest.approx(0.5)

    with pytest.raises(ValueError, match="2-dimensional"):
        replace(synthesis, correction_opd_m=np.array([1.0, 2.0]))
    with pytest.raises(ValueError, match="finite"):
        replace(synthesis, correction_opd_m=np.full((2, 2), np.nan))
    with pytest.raises(ValueError, match="shape"):
        replace(synthesis, applied_commands_opd_m=np.array([1.0]))
    with pytest.raises(ValueError, match="fraction of saturated"):
        replace(synthesis, saturation_fraction=0.0)
    with pytest.raises(ValueError, match="command_unit"):
        replace(synthesis, command_unit="m_surface")
    with pytest.raises(ValueError, match="config_hash"):
        replace(synthesis, config_hash=" ")


def test_reconstruction_allows_nan_only_for_unusable_rows_and_freezes_arrays() -> None:
    estimate = _reconstruction()
    assert np.isnan(estimate.reconstructed_signal[1])
    assert np.isnan(estimate.residual_signal[1])

    with pytest.raises(ValueError, match="reconstructed_signal.*finite"):
        replace(estimate, usable_rows=np.ones(3, dtype=bool))
    with pytest.raises(ValueError, match="infinite"):
        replace(
            estimate,
            residual_signal=np.array([0.2, np.inf, 0.1]),
        )
    with pytest.raises(ValueError, match="NaN.*unusable|unusable.*NaN"):
        replace(
            estimate,
            reconstructed_signal=np.array([0.8, 0.0, -0.1]),
        )
    with pytest.raises(ValueError, match="NaN.*unusable|unusable.*NaN"):
        replace(
            estimate,
            residual_signal=np.array([0.2, 0.0, 0.1]),
        )


def test_reconstruction_validates_shapes_ids_units_modes_and_diagnostics() -> None:
    estimate = _reconstruction()
    with pytest.raises(ValueError, match="shape"):
        replace(estimate, residual_signal=np.array([0.1, 0.2]))
    with pytest.raises(ValueError, match="duplicate"):
        replace(estimate, coordinate_ids=("same", "same"))
    with pytest.raises(ValueError, match="coordinate_kind"):
        replace(estimate, coordinate_kind="zernike")
    with pytest.raises(ValueError, match="requires.*m_opd_equivalent"):
        replace(
            estimate,
            coordinate_kind="dm_command_opd",
            coordinate_unit="m_opd_rms",
        )
    with pytest.raises(ValueError, match="measurement_unit"):
        replace(estimate, measurement_unit="nm")
    with pytest.raises(ValueError, match="kept_modes"):
        replace(estimate, kept_modes=3)
    with pytest.raises(ValueError, match="non-negative"):
        replace(estimate, singular_values=np.array([4.0, -1.0]))
    with pytest.raises(ValueError, match="non-increasing"):
        replace(estimate, singular_values=np.array([1.0, 4.0]))
    with pytest.raises(ValueError, match="coordinate_norm_m"):
        replace(estimate, coordinate_norm_m=-1.0)
    with pytest.raises(ValueError, match="residual_norm"):
        replace(estimate, residual_norm=np.nan)
    with pytest.raises(ValueError, match="matrix_hash"):
        replace(estimate, matrix_hash="")


@pytest.mark.parametrize(
    "constructor,kwargs",
    [
        (
            MeasurementVector,
            {
                "values": [1.0],
                "valid_rows": np.array([True]),
                "row_ids": ("row",),
                "measurement_unit": "pixel",
            },
        ),
        (
            DmCommandVector,
            {
                "values_opd_m": [1.0],
                "actuator_ids": ("actuator",),
                "command_unit": "m_opd_equivalent",
            },
        ),
    ],
)
def test_array_contracts_do_not_silently_accept_python_lists(constructor, kwargs) -> None:
    with pytest.raises(ValueError, match="numpy.ndarray"):
        constructor(**kwargs)
