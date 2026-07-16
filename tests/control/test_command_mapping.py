"""AO-REF-009 contracts for typed command-coordinate projection."""

from __future__ import annotations

import numpy as np
import pytest

from shwfs_ao.control.command_mapping import (
    CommandMappingError,
    ControlledSubsetCommandProjector,
    IdentityCommandProjector,
    ModalToActuatorCommandProjector,
)
from shwfs_ao.core.protocols import CommandProjector
from shwfs_ao.core.types import DmCommandVector, ReconstructionEstimate


def _estimate(
    values: np.ndarray,
    coordinate_ids: tuple[str, ...],
    *,
    coordinate_kind: str = "dm_command_opd",
) -> ReconstructionEstimate:
    coordinate_unit = (
        "m_opd_rms"
        if coordinate_kind == "modal_opd"
        else "m_opd_equivalent"
    )
    return ReconstructionEstimate(
        delta_coordinates_opd_m=np.asarray(values, dtype=float),
        coordinate_ids=coordinate_ids,
        coordinate_kind=coordinate_kind,  # type: ignore[arg-type]
        coordinate_unit=coordinate_unit,  # type: ignore[arg-type]
        measurement_unit="pixel",
        usable_rows=np.ones(2, dtype=bool),
        reconstructed_signal=np.zeros(2),
        residual_signal=np.zeros(2),
        coordinate_norm_m=float(np.linalg.norm(values)),
        residual_norm=0.0,
        kept_modes=min(len(coordinate_ids), 2),
        singular_values=np.ones(min(len(coordinate_ids), 2)),
        matrix_hash="interaction-matrix-hash",
    )


def test_identity_projector_preserves_the_exact_full_actuator_layout() -> None:
    actuator_ids = ("A0", "A1", "A2")
    projector = IdentityCommandProjector(actuator_ids)
    estimate = _estimate(np.asarray([2.0e-9, -3.0e-9, 5.0e-9]), actuator_ids)

    command = projector.project(estimate)

    assert isinstance(projector, CommandProjector)
    assert isinstance(command, DmCommandVector)
    assert projector.input_coordinate_ids == actuator_ids
    assert projector.input_coordinate_kind == "dm_command_opd"
    assert projector.input_coordinate_unit == "m_opd_equivalent"
    assert projector.output_actuator_ids == actuator_ids
    assert len(projector.config_hash) == 64
    np.testing.assert_array_equal(command.values_opd_m, estimate.delta_coordinates_opd_m)
    assert command.actuator_ids == actuator_ids
    assert command.command_unit == "m_opd_equivalent"


def test_controlled_subset_expands_by_id_and_zeros_every_excluded_actuator() -> None:
    # Deliberately choose a non-positional input order.  The mapping is an
    # identity relation between named coordinates, not a prefix/slice rule.
    projector = ControlledSubsetCommandProjector(
        ("A2", "A0"),
        ("A0", "A1-dead", "A2", "A3-stuck"),
    )
    estimate = _estimate(np.asarray([30.0e-9, 10.0e-9]), ("A2", "A0"))

    command = projector.project(estimate)

    np.testing.assert_array_equal(
        command.values_opd_m,
        np.asarray([10.0e-9, 0.0, 30.0e-9, 0.0]),
    )
    assert command.actuator_ids == projector.output_actuator_ids
    assert projector.input_coordinate_kind == "dm_command_opd"
    assert projector.input_coordinate_unit == "m_opd_equivalent"


def test_modal_projector_records_and_applies_an_explicit_calibrated_matrix() -> None:
    source = np.asarray(
        [
            [1.0, 2.0],
            [0.0, -1.0],
            [3.0, 0.0],
        ]
    )
    projector = ModalToActuatorCommandProjector(
        source,
        input_coordinate_ids=("focus", "astigmatism"),
        output_actuator_ids=("A0", "A1", "A2"),
        target_dm_hash="test-target-dm-hash",
    )
    source[0, 0] = 999.0
    estimate = _estimate(
        np.asarray([2.0e-9, -1.0e-9]),
        ("focus", "astigmatism"),
        coordinate_kind="modal_opd",
    )

    command = projector.project(estimate)

    np.testing.assert_allclose(command.values_opd_m, [0.0, 1.0e-9, 6.0e-9])
    np.testing.assert_array_equal(
        projector.modal_to_actuator_matrix,
        [[1.0, 2.0], [0.0, -1.0], [3.0, 0.0]],
    )
    assert projector.input_coordinate_kind == "modal_opd"
    assert projector.input_coordinate_unit == "m_opd_rms"
    assert projector.mapping_unit == "m_opd_equivalent_per_m_opd_rms"
    assert projector.target_dm_hash == "test-target-dm-hash"
    assert len(projector.mapping_hash) == 64
    assert len(projector.config_hash) == 64
    assert not projector.modal_to_actuator_matrix.flags.writeable
    with pytest.raises(ValueError):
        projector.modal_to_actuator_matrix.setflags(write=True)

    changed = ModalToActuatorCommandProjector(
        np.asarray([[1.0, 2.1], [0.0, -1.0], [3.0, 0.0]]),
        input_coordinate_ids=("focus", "astigmatism"),
        output_actuator_ids=("A0", "A1", "A2"),
        target_dm_hash="test-target-dm-hash",
    )
    assert changed.mapping_hash != projector.mapping_hash
    assert changed.config_hash != projector.config_hash

    changed_target = ModalToActuatorCommandProjector(
        np.asarray([[1.0, 2.0], [0.0, -1.0], [3.0, 0.0]]),
        input_coordinate_ids=("focus", "astigmatism"),
        output_actuator_ids=("A0", "A1", "A2"),
        target_dm_hash="different-target-dm-hash",
    )
    assert changed_target.mapping_hash != projector.mapping_hash
    assert changed_target.config_hash != projector.config_hash


@pytest.mark.parametrize(
    "projector",
    [
        IdentityCommandProjector(("A0", "A1")),
        ControlledSubsetCommandProjector(("A0",), ("A0", "A1")),
        ModalToActuatorCommandProjector(
            np.eye(2),
            input_coordinate_ids=("M0", "M1"),
            output_actuator_ids=("A0", "A1"),
            target_dm_hash="test-target-dm-hash",
        ),
    ],
)
def test_projectors_reject_wrong_coordinate_identity_kind_or_type(
    projector: CommandProjector,
) -> None:
    expected_ids = projector.input_coordinate_ids
    wrong_kind = (
        "modal_opd"
        if projector.input_coordinate_kind == "dm_command_opd"
        else "dm_command_opd"
    )
    wrong_ids = tuple(reversed(expected_ids))
    if wrong_ids == expected_ids:
        wrong_ids = ("unexpected-coordinate",)

    with pytest.raises(CommandMappingError):
        projector.project(object())  # type: ignore[arg-type]
    with pytest.raises(CommandMappingError, match="coordinate_kind|coordinate_unit"):
        projector.project(
            _estimate(
                np.ones(len(expected_ids)),
                expected_ids,
                coordinate_kind=wrong_kind,
            )
        )
    with pytest.raises(CommandMappingError, match="coordinate_ids"):
        projector.project(
            _estimate(
                np.ones(len(wrong_ids)),
                wrong_ids,
                coordinate_kind=projector.input_coordinate_kind,
            )
        )


@pytest.mark.parametrize(
    "factory",
    [
        lambda: IdentityCommandProjector(("A0", "A0")),
        lambda: ControlledSubsetCommandProjector(("missing",), ("A0", "A1")),
        lambda: ControlledSubsetCommandProjector(("A0", "A0"), ("A0", "A1")),
        lambda: ModalToActuatorCommandProjector(
            np.ones((2, 3)),
            input_coordinate_ids=("M0", "M1"),
            output_actuator_ids=("A0", "A1"),
            target_dm_hash="test-target-dm-hash",
        ),
        lambda: ModalToActuatorCommandProjector(
            np.asarray([[np.nan]]),
            input_coordinate_ids=("M0",),
            output_actuator_ids=("A0",),
            target_dm_hash="test-target-dm-hash",
        ),
        lambda: ModalToActuatorCommandProjector(
            np.asarray([[1.0]]),
            input_coordinate_ids=("M0",),
            output_actuator_ids=("A0",),
            target_dm_hash="",
        ),
    ],
)
def test_projector_construction_rejects_ambiguous_layouts(factory) -> None:
    with pytest.raises(CommandMappingError):
        factory()
