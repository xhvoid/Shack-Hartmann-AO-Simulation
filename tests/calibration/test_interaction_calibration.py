"""AO-REF-007 contracts for canonical interaction-matrix calibration."""

from __future__ import annotations

from dataclasses import fields, replace

import numpy as np
import pytest

from shwfs_ao.backends.native.dm import NativeDmBackend
from shwfs_ao.calibration import (
    DmActuatorProbeBasis,
    InteractionMatrix,
    InteractionMatrixError,
    ModalProbeBasis,
    calibrate_interaction_matrix,
    interaction_matrix_hash,
)
from shwfs_ao.core.random import NamedRandomStreams
from shwfs_ao.core.types import MeasurementVector, WfsMeasurement
from shwfs_ao.dm import DMConfig, DeformableMirror


class _LinearSensor:
    """Small WFS double with linear OPD response and optional scoped noise."""

    config_hash = "linear-sensor-config-v1"
    geometry_hash = "linear-sensor-geometry-v1"
    detector_hash = "linear-sensor-detector-v1"

    def __init__(
        self,
        weights: np.ndarray,
        *,
        row_ids: tuple[str, ...] | None = None,
        offset: np.ndarray | None = None,
        valid_rows: np.ndarray | None = None,
        noise_standard_deviation: float = 0.0,
    ) -> None:
        self.weights = np.asarray(weights, dtype=float)
        count = int(self.weights.shape[0])
        self.row_ids = (
            tuple(f"row-{index}" for index in range(count))
            if row_ids is None
            else row_ids
        )
        self.offset = (
            np.zeros(count, dtype=float)
            if offset is None
            else np.asarray(offset, dtype=float)
        )
        self.valid_rows = (
            np.ones(count, dtype=bool)
            if valid_rows is None
            else np.asarray(valid_rows, dtype=bool)
        )
        self.noise_standard_deviation = float(noise_standard_deviation)
        self.calls: list[dict[str, object]] = []

    def measure(
        self,
        residual_opd_m: np.ndarray,
        *,
        random_streams: NamedRandomStreams,
        include_noise: bool,
    ) -> WfsMeasurement:
        opd = np.asarray(residual_opd_m, dtype=float)
        values = self.offset + np.einsum("rij,ij->r", self.weights, opd)
        if include_noise:
            values = values + random_streams.generator(
                "detector.read_noise"
            ).normal(
                scale=self.noise_standard_deviation,
                size=len(self.row_ids),
            )
        values = np.asarray(values, dtype=float)
        values[~self.valid_rows] = np.nan
        self.calls.append(
            {
                "opd_m": np.array(opd, copy=True),
                "include_noise": bool(include_noise),
                "values": np.array(values, copy=True),
                "valid_rows": np.array(self.valid_rows, copy=True),
            }
        )
        return WfsMeasurement(
            MeasurementVector(
                values=values,
                valid_rows=np.array(self.valid_rows, copy=True),
                row_ids=self.row_ids,
                measurement_unit="pixel",
            )
        )


def _orthogonal_modal_basis(
    *,
    max_abs_amplitude_m: float = np.inf,
) -> ModalProbeBasis:
    horizontal = np.tile(np.asarray([-3.0, 0.0, 3.0]), (3, 1)) + 17.0
    vertical = np.tile(np.asarray([-5.0, 0.0, 5.0])[:, None], (1, 3)) - 9.0
    return ModalProbeBasis(
        {"tip-x": horizontal, "tip-y": vertical},
        np.ones((3, 3), dtype=bool),
        max_abs_amplitude_m=max_abs_amplitude_m,
    )


def _projection_sensor(basis: ModalProbeBasis) -> _LinearSensor:
    invalid_weight = np.ones((3, 3), dtype=float)
    weights = np.stack(
        (basis.modes[0], invalid_weight, basis.modes[1]),
        axis=0,
    )
    return _LinearSensor(
        weights,
        row_ids=("slope-x", "quality-rejected", "slope-y"),
        offset=np.asarray([4.5e-7, -3.0e-7, 8.25e-7]),
        valid_rows=np.asarray([True, False, True]),
    )


def test_modal_basis_removes_piston_once_and_uses_unit_pupil_rms() -> None:
    mask = np.asarray(
        [
            [False, True, False],
            [True, True, True],
            [False, True, False],
        ],
        dtype=bool,
    )
    raw = np.asarray(
        [
            [np.nan, 7.0, np.nan],
            [3.0, 5.0, 7.0],
            [np.nan, 3.0, np.nan],
        ]
    )
    basis = ModalProbeBasis({"asymmetric-mode": raw}, mask)
    unit_mode = basis.modes[0]

    assert basis.coordinate_ids == ("asymmetric-mode",)
    assert basis.coordinate_kind == "modal_opd"
    assert basis.coordinate_unit == "m_opd_rms"
    assert np.mean(unit_mode[mask]) == pytest.approx(0.0, abs=1.0e-15)
    assert np.sqrt(np.mean(unit_mode[mask] ** 2)) == pytest.approx(1.0)
    np.testing.assert_array_equal(unit_mode[~mask], 0.0)
    expected_scale = np.sqrt(np.mean((raw[mask] - np.mean(raw[mask])) ** 2))
    assert basis.normalization_scales[0] == pytest.approx(expected_scale)

    amplitude = 37.0e-9
    perturbation = basis.opd_m_for_coordinate(0, amplitude)
    assert np.sqrt(np.mean(perturbation[mask] ** 2)) == pytest.approx(amplitude)
    assert np.mean(perturbation[mask]) == pytest.approx(0.0, abs=1.0e-24)
    assert not perturbation.flags.writeable


@pytest.mark.parametrize("method", ["central", "forward"])
def test_central_and_forward_are_derivatives_with_full_stable_row_layout(
    method: str,
) -> None:
    basis = _orthogonal_modal_basis()
    sensor = _projection_sensor(basis)
    amplitude = 23.0e-9

    result = calibrate_interaction_matrix(
        basis,
        sensor,
        amplitude,
        random_streams=NamedRandomStreams(121),
        method=method,
    )

    expected = np.full((3, 2), np.nan)
    expected[[0, 2]] = np.asarray([[9.0, 0.0], [0.0, 9.0]])
    np.testing.assert_allclose(result.matrix, expected, rtol=1.0e-12, atol=1.0e-12)
    np.testing.assert_array_equal(result.row_valid, [True, False, True])
    assert result.row_ids == sensor.row_ids
    assert result.coordinate_ids == basis.coordinate_ids
    assert result.coordinate_kind == "modal_opd"
    assert result.coordinate_unit == "m_opd_rms"
    assert result.measurement_unit == "pixel"
    assert result.matrix_unit == "pixel / m_opd_rms"
    assert result.method == method
    assert result.matrix_standard_error is None
    assert result.sensor_config_hash == sensor.config_hash
    assert result.geometry_hash == sensor.geometry_hash
    assert result.detector_hash == sensor.detector_hash
    assert result.dm_hash is None
    assert result.rank == 2
    assert result.condition_proxy == pytest.approx(1.0)
    np.testing.assert_allclose(result.singular_values, [9.0, 9.0])

    if method == "central":
        assert len(sensor.calls) == 2 * basis.size
        assert all(call["include_noise"] is False for call in sensor.calls)
    else:
        assert len(sensor.calls) == basis.size + 1
        reference = sensor.calls[0]
        np.testing.assert_array_equal(reference["opd_m"], np.zeros((3, 3)))
        assert reference["include_noise"] is False


@pytest.mark.parametrize("amplitude", [0.0, np.nan, np.inf, -1.0e-9, 6.0e-9])
def test_invalid_or_out_of_bound_amplitude_fails_before_sensor_call(
    amplitude: float,
) -> None:
    basis = _orthogonal_modal_basis(max_abs_amplitude_m=5.0e-9)
    sensor = _projection_sensor(basis)

    with pytest.raises(InteractionMatrixError, match="amplitude"):
        calibrate_interaction_matrix(
            basis,
            sensor,
            amplitude,
            random_streams=NamedRandomStreams(1),
        )

    assert sensor.calls == []


def test_rows_must_be_valid_for_every_sample_and_invalid_rows_stay_nan() -> None:
    basis = _orthogonal_modal_basis()

    class _IntermittentSensor(_LinearSensor):
        def measure(self, *args: object, **kwargs: object) -> WfsMeasurement:
            measurement = super().measure(*args, **kwargs)
            call_index = len(self.calls) - 1
            if call_index != 1:
                return measurement
            valid = np.asarray(measurement.vector.valid_rows, dtype=bool).copy()
            values = np.asarray(measurement.vector.values, dtype=float).copy()
            valid[2] = False
            values[2] = np.nan
            self.calls[-1]["valid_rows"] = valid.copy()
            self.calls[-1]["values"] = values.copy()
            return WfsMeasurement(
                MeasurementVector(values, valid, self.row_ids, "pixel")
            )

    base = _projection_sensor(basis)
    sensor = _IntermittentSensor(
        np.stack(
            (
                basis.modes[0] + 0.25 * basis.modes[1],
                base.weights[1],
                basis.modes[1],
            ),
            axis=0,
        ),
        row_ids=base.row_ids,
        offset=base.offset,
        valid_rows=np.asarray([True, False, True]),
    )
    result = calibrate_interaction_matrix(
        basis,
        sensor,
        11.0e-9,
        random_streams=NamedRandomStreams(2),
    )

    np.testing.assert_array_equal(result.row_valid, [True, False, False])
    assert np.all(np.isnan(result.matrix[1:]))
    assert np.all(np.isfinite(result.matrix[0]))


def test_all_zero_columns_and_no_valid_rows_are_rejected() -> None:
    basis = ModalProbeBasis(
        {"tip": np.tile(np.asarray([-1.0, 0.0, 1.0]), (3, 1))},
        np.ones((3, 3), dtype=bool),
    )
    zero_sensor = _LinearSensor(
        np.zeros((1, 3, 3)),
        offset=np.asarray([19.0]),
    )
    with pytest.raises(InteractionMatrixError, match="all-zero"):
        calibrate_interaction_matrix(
            basis,
            zero_sensor,
            1.0e-9,
            random_streams=NamedRandomStreams(3),
        )

    invalid_sensor = _LinearSensor(
        np.ones((1, 3, 3)),
        valid_rows=np.asarray([False]),
    )
    with pytest.raises(InteractionMatrixError, match="no rows valid"):
        calibrate_interaction_matrix(
            basis,
            invalid_sensor,
            1.0e-9,
            random_streams=NamedRandomStreams(3),
        )


def _faulted_dm() -> DeformableMirror:
    influences = np.zeros((4, 2, 2), dtype=float)
    influences[0, 0, 0] = 1.0
    influences[1, 0, 1] = 1.0
    influences[2, 1, 0] = 1.0
    influences[3, 1, 1] = 1.0
    return DeformableMirror(
        DMConfig(
            n_actuators_across=2,
            stroke_limit_nm=100.0,
            dead_actuator_indices=(1,),
            stuck_actuator_indices=(2,),
            stuck_command_nm=17.0,
        ),
        NativeDmBackend(influences),
        actuator_ids=("a0", "dead-a1", "stuck-a2", "a3"),
    )


def test_dm_basis_uses_controllable_ids_stroke_and_positive_residual_sign() -> None:
    dm = _faulted_dm()
    basis = DmActuatorProbeBasis(dm)
    assert basis.coordinate_ids == ("a0", "a3")
    assert basis.coordinate_kind == "dm_command_opd"
    assert basis.coordinate_unit == "m_opd_equivalent"
    np.testing.assert_array_equal(
        basis.max_abs_amplitude_m,
        [dm.stroke_limit_opd_m, dm.stroke_limit_opd_m],
    )

    amplitude = 25.0e-9
    positive = basis.opd_m_for_coordinate(0, amplitude)
    negative = basis.opd_m_for_coordinate(0, -amplitude)
    np.testing.assert_array_equal(positive, amplitude * dm.influence_functions[0])
    np.testing.assert_array_equal(negative, -positive)
    assert positive[0, 0] > 0.0

    sensor = _LinearSensor(
        np.asarray(
            [
                [[1.0, 0.0], [0.0, 0.0]],
                [[0.0, 0.0], [0.0, 1.0]],
            ]
        )
    )
    result = calibrate_interaction_matrix(
        basis,
        sensor,
        amplitude,
        random_streams=NamedRandomStreams(4),
    )
    np.testing.assert_allclose(result.matrix, np.eye(2))
    assert result.coordinate_ids == ("a0", "a3")
    assert result.matrix_unit == "pixel / m_opd_equivalent"
    assert result.dm_hash == dm.config_hash

    uncalled = _LinearSensor(sensor.weights)
    with pytest.raises(InteractionMatrixError, match="bound"):
        calibrate_interaction_matrix(
            basis,
            uncalled,
            np.nextafter(dm.stroke_limit_opd_m, np.inf),
            random_streams=NamedRandomStreams(4),
        )
    assert uncalled.calls == []


def test_noisy_calibration_records_sample_mean_standard_error_and_replays() -> None:
    mode = np.tile(np.asarray([-1.0, 0.0, 1.0]), (3, 1))
    basis = ModalProbeBasis(
        {"tip-x": mode},
        np.ones((3, 3), dtype=bool),
    )
    weights = np.stack(
        (basis.modes[0], 0.5 * basis.modes[0], np.ones((3, 3))),
        axis=0,
    )
    amplitude = 13.0e-9
    repeats = 5
    first_sensor = _LinearSensor(
        weights,
        valid_rows=np.asarray([True, True, False]),
        noise_standard_deviation=2.0e-8,
    )
    first = calibrate_interaction_matrix(
        basis,
        first_sensor,
        amplitude,
        random_streams=NamedRandomStreams(928),
        include_noise=True,
        repeats=repeats,
    )

    derivative_samples = np.stack(
        [
            (
                np.asarray(first_sensor.calls[2 * repeat]["values"])
                - np.asarray(first_sensor.calls[2 * repeat + 1]["values"])
            )
            / (2.0 * amplitude)
            for repeat in range(repeats)
        ],
        axis=0,
    )
    np.testing.assert_allclose(
        first.matrix[:2, 0],
        np.mean(derivative_samples[:, :2], axis=0),
        rtol=1.0e-15,
        atol=1.0e-15,
    )
    assert first.matrix_standard_error is not None
    np.testing.assert_allclose(
        first.matrix_standard_error[:2, 0],
        np.std(derivative_samples[:, :2], axis=0, ddof=1) / np.sqrt(repeats),
        rtol=1.0e-15,
        atol=1.0e-15,
    )
    assert first.include_noise is True
    assert first.repeat_count == repeats
    np.testing.assert_array_equal(first.row_valid, [True, True, False])
    assert np.isnan(first.matrix[2, 0])
    assert np.isnan(first.matrix_standard_error[2, 0])

    replay_sensor = _LinearSensor(
        weights,
        valid_rows=np.asarray([True, True, False]),
        noise_standard_deviation=2.0e-8,
    )
    replay = calibrate_interaction_matrix(
        basis,
        replay_sensor,
        amplitude,
        random_streams=NamedRandomStreams(928),
        include_noise=True,
        repeats=repeats,
    )
    np.testing.assert_array_equal(replay.matrix, first.matrix)
    np.testing.assert_array_equal(
        replay.matrix_standard_error,
        first.matrix_standard_error,
    )
    assert replay.calibration_hash == first.calibration_hash

    with pytest.raises(InteractionMatrixError, match="repeats >= 2"):
        calibrate_interaction_matrix(
            basis,
            _LinearSensor(weights, noise_standard_deviation=1.0),
            amplitude,
            random_streams=NamedRandomStreams(928),
            include_noise=True,
            repeats=1,
        )


def test_noisy_forward_difference_keeps_its_reference_noise_free() -> None:
    basis = ModalProbeBasis(
        {"tip": np.tile(np.asarray([-1.0, 0.0, 1.0]), (3, 1))},
        np.ones((3, 3), dtype=bool),
    )
    sensor = _LinearSensor(
        np.stack((basis.modes[0],), axis=0),
        offset=np.asarray([2.0e-6]),
        noise_standard_deviation=1.0e-9,
    )
    result = calibrate_interaction_matrix(
        basis,
        sensor,
        9.0e-9,
        random_streams=NamedRandomStreams(420),
        method="forward",
        include_noise=True,
        repeats=3,
    )

    assert len(sensor.calls) == 4
    np.testing.assert_array_equal(sensor.calls[0]["opd_m"], np.zeros((3, 3)))
    assert sensor.calls[0]["include_noise"] is False
    assert all(call["include_noise"] is True for call in sensor.calls[1:])
    reference = float(np.asarray(sensor.calls[0]["values"])[0])
    samples = np.asarray(
        [
            (float(np.asarray(call["values"])[0]) - reference) / 9.0e-9
            for call in sensor.calls[1:]
        ]
    )
    assert result.matrix[0, 0] == pytest.approx(np.mean(samples))
    assert result.matrix_standard_error is not None
    assert result.matrix_standard_error[0, 0] == pytest.approx(
        np.std(samples, ddof=1) / np.sqrt(3)
    )


def test_calibration_scopes_do_not_advance_runtime_detector_or_atmosphere() -> None:
    streams = NamedRandomStreams(719)
    control = NamedRandomStreams(719)
    runtime_read = streams.generator("detector.read_noise")
    runtime_atmosphere = streams.generator("atmosphere")
    control_read = control.generator("detector.read_noise")
    control_atmosphere = control.generator("atmosphere")
    np.testing.assert_array_equal(runtime_read.normal(size=4), control_read.normal(size=4))
    np.testing.assert_array_equal(
        runtime_atmosphere.normal(size=4),
        control_atmosphere.normal(size=4),
    )

    basis = ModalProbeBasis(
        {"tip": np.tile(np.asarray([-1.0, 0.0, 1.0]), (3, 1))},
        np.ones((3, 3), dtype=bool),
    )
    sensor = _LinearSensor(
        np.stack((basis.modes[0],), axis=0),
        noise_standard_deviation=1.0e-9,
    )
    calibrate_interaction_matrix(
        basis,
        sensor,
        7.0e-9,
        random_streams=streams,
        include_noise=True,
        repeats=3,
    )

    np.testing.assert_array_equal(runtime_read.normal(size=9), control_read.normal(size=9))
    np.testing.assert_array_equal(
        runtime_atmosphere.normal(size=9),
        control_atmosphere.normal(size=9),
    )


def test_result_field_identity_hash_serialization_and_immutability() -> None:
    basis = _orthogonal_modal_basis()
    result = calibrate_interaction_matrix(
        basis,
        _projection_sensor(basis),
        5.0e-9,
        random_streams=NamedRandomStreams(808),
    )
    assert tuple(field.name for field in fields(InteractionMatrix)) == (
        "matrix",
        "row_valid",
        "row_ids",
        "coordinate_ids",
        "coordinate_kind",
        "calibration_amplitude_m",
        "measurement_unit",
        "coordinate_unit",
        "matrix_unit",
        "singular_values",
        "rank",
        "condition_proxy",
        "method",
        "include_noise",
        "repeat_count",
        "matrix_standard_error",
        "sensor_config_hash",
        "geometry_hash",
        "detector_hash",
        "dm_hash",
        "calibration_hash",
        "provenance",
    )
    assert interaction_matrix_hash(result) == result.calibration_hash

    restored = InteractionMatrix.from_record(result.to_record())
    np.testing.assert_array_equal(restored.matrix, result.matrix)
    np.testing.assert_array_equal(restored.row_valid, result.row_valid)
    np.testing.assert_array_equal(restored.singular_values, result.singular_values)
    assert restored.row_ids == result.row_ids
    assert restored.coordinate_ids == result.coordinate_ids
    assert restored.calibration_hash == result.calibration_hash

    for array in (
        result.matrix,
        result.row_valid,
        result.singular_values,
        basis.modes,
        basis.max_abs_amplitude_m,
    ):
        assert not array.flags.writeable
        with pytest.raises(ValueError):
            array.setflags(write=True)

    with pytest.raises(InteractionMatrixError, match="matrix_unit"):
        replace(result, matrix_unit="pixel")
    with pytest.raises(InteractionMatrixError, match="calibration_hash"):
        replace(
            result,
            row_ids=("slope-y", "quality-rejected", "slope-x"),
        )
    with pytest.raises(InteractionMatrixError, match="calibration_hash"):
        replace(result, coordinate_ids=tuple(reversed(result.coordinate_ids)))
    with pytest.raises(InteractionMatrixError, match="calibration_hash"):
        replace(
            result,
            measurement_unit="rad_wavefront_slope",
            matrix_unit="rad_wavefront_slope / m_opd_rms",
        )

    tampered = result.to_record()
    matrix_record = tampered["matrix"]
    assert isinstance(matrix_record, list)
    matrix_record[0][0] += 1.0
    with pytest.raises(InteractionMatrixError):
        InteractionMatrix.from_record(tampered)

    ambiguous_mask = result.to_record()
    ambiguous_mask["row_valid"] = [1, 0, 1]
    with pytest.raises(InteractionMatrixError, match="row_valid"):
        InteractionMatrix.from_record(ambiguous_mask)
