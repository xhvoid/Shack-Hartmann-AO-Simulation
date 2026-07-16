"""Frame-exact AO-REF-009 leaky-integrator and latency contracts."""

from __future__ import annotations

import numpy as np
import pytest

from shwfs_ao.control.controller import ControllerError, LeakyIntegratorController
from shwfs_ao.core.protocols import Controller
from shwfs_ao.core.types import DmCommandVector


ACTUATOR_IDS = ("A0", "A1")


def _command(first: float, second: float = 0.0) -> DmCommandVector:
    return DmCommandVector(
        np.asarray([first, second], dtype=float),
        ACTUATOR_IDS,
        "m_opd_equivalent",
    )


@pytest.mark.parametrize(
    ("latency_frames", "expected_released", "expected_requested"),
    [
        (
            0,
            [[1.0, 0.0], [0.0, 2.0], [-3.0, 1.0]],
            [[1.0, 0.0], [1.0, 2.0], [-2.0, 3.0]],
        ),
        (
            1,
            [[0.0, 0.0], [1.0, 0.0], [0.0, 2.0]],
            [[0.0, 0.0], [1.0, 0.0], [1.0, 2.0]],
        ),
        (
            2,
            [[0.0, 0.0], [0.0, 0.0], [1.0, 0.0]],
            [[0.0, 0.0], [0.0, 0.0], [1.0, 0.0]],
        ),
    ],
)
def test_zero_one_and_multi_frame_latency_have_exact_frame_indices(
    latency_frames: int,
    expected_released: list[list[float]],
    expected_requested: list[list[float]],
) -> None:
    controller = LeakyIntegratorController(
        ACTUATOR_IDS,
        gain=1.0,
        leak=0.0,
        latency_frames=latency_frames,
    )
    assert isinstance(controller, Controller)
    increments = (_command(1.0), _command(0.0, 2.0), _command(-3.0, 1.0))

    released: list[np.ndarray] = []
    requested: list[np.ndarray] = []
    for increment in increments:
        result = controller.update(increment)
        released.append(controller.last_released_delta.values_opd_m)
        requested.append(result.values_opd_m)
        controller.accept_applied_commands(result)

    np.testing.assert_array_equal(released, expected_released)
    np.testing.assert_array_equal(requested, expected_requested)


def test_none_enqueues_zero_advances_latency_and_still_permits_leak() -> None:
    controller = LeakyIntegratorController(
        ACTUATOR_IDS,
        gain=0.5,
        leak=0.2,
        latency_frames=1,
    )
    controller.accept_applied_commands(_command(10.0))

    first = controller.update(_command(4.0))
    np.testing.assert_array_equal(controller.last_released_delta.values_opd_m, [0, 0])
    np.testing.assert_allclose(first.values_opd_m, [8.0, 0.0])
    controller.accept_applied_commands(first)

    second = controller.update(None)
    np.testing.assert_array_equal(controller.last_released_delta.values_opd_m, [4, 0])
    np.testing.assert_allclose(second.values_opd_m, [8.4, 0.0])
    controller.accept_applied_commands(second)

    third = controller.update(None)
    np.testing.assert_array_equal(controller.last_released_delta.values_opd_m, [0, 0])
    np.testing.assert_allclose(third.values_opd_m, [6.72, 0.0])


def test_next_update_starts_from_dm_applied_not_unclipped_requested_command() -> None:
    controller = LeakyIntegratorController(
        ACTUATOR_IDS,
        gain=1.0,
        leak=0.0,
        latency_frames=0,
    )

    requested = controller.update(_command(10.0))
    np.testing.assert_array_equal(requested.values_opd_m, [10.0, 0.0])
    controller.accept_applied_commands(_command(3.0))

    after_clipping = controller.update(None)
    np.testing.assert_array_equal(after_clipping.values_opd_m, [3.0, 0.0])
    np.testing.assert_array_equal(
        controller.last_applied_commands.values_opd_m,
        [3.0, 0.0],
    )


def test_gain_zero_still_releases_queue_entries_and_reset_clears_all_state() -> None:
    controller = LeakyIntegratorController(
        ACTUATOR_IDS,
        gain=0.0,
        leak=0.0,
        latency_frames=2,
    )
    controller.accept_applied_commands(_command(7.0, -2.0))
    first = controller.update(_command(5.0, 4.0))
    controller.accept_applied_commands(first)
    second = controller.update(None)
    controller.accept_applied_commands(second)
    released = controller.update(None)

    np.testing.assert_array_equal(
        controller.last_released_delta.values_opd_m,
        [5.0, 4.0],
    )
    np.testing.assert_array_equal(released.values_opd_m, [7.0, -2.0])

    controller.reset()
    np.testing.assert_array_equal(controller.last_applied_commands.values_opd_m, [0, 0])
    for _ in range(3):
        result = controller.update(None)
        np.testing.assert_array_equal(result.values_opd_m, [0, 0])
        np.testing.assert_array_equal(
            controller.last_released_delta.values_opd_m,
            [0, 0],
        )
        controller.accept_applied_commands(result)


def test_controller_hash_properties_identity_and_returned_arrays_are_immutable() -> None:
    first = LeakyIntegratorController(
        ACTUATOR_IDS,
        gain=0.3,
        leak=0.1,
        latency_frames=2,
    )
    identical = LeakyIntegratorController(
        ACTUATOR_IDS,
        gain=0.3,
        leak=0.1,
        latency_frames=2,
    )
    changed = LeakyIntegratorController(
        ACTUATOR_IDS,
        gain=0.31,
        leak=0.1,
        latency_frames=2,
    )

    assert first.actuator_ids == ACTUATOR_IDS
    assert first.gain == 0.3
    assert first.leak == 0.1
    assert first.latency_frames == 2
    assert first.config_hash == identical.config_hash
    assert first.config_hash != changed.config_hash
    assert len(first.config_hash) == 64
    result = first.update(_command(1.0))
    for values in (
        result.values_opd_m,
        first.last_released_delta.values_opd_m,
        first.last_applied_commands.values_opd_m,
    ):
        assert not values.flags.writeable
        with pytest.raises(ValueError):
            values.setflags(write=True)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"actuator_ids": ()},
        {"actuator_ids": ("A0", "A0")},
        {"gain": -1.0},
        {"gain": np.nan},
        {"gain": True},
        {"leak": -0.1},
        {"leak": 1.0},
        {"leak": np.inf},
        {"latency_frames": -1},
        {"latency_frames": True},
        {"latency_frames": 1.5},
    ],
)
def test_controller_rejects_invalid_configuration(kwargs: dict[str, object]) -> None:
    values: dict[str, object] = {
        "actuator_ids": ACTUATOR_IDS,
        "gain": 0.3,
        "leak": 0.0,
        "latency_frames": 0,
    }
    values.update(kwargs)
    with pytest.raises(ControllerError):
        LeakyIntegratorController(**values)  # type: ignore[arg-type]


def test_controller_rejects_untyped_or_identity_mismatched_commands() -> None:
    controller = LeakyIntegratorController(
        ACTUATOR_IDS,
        gain=0.3,
        leak=0.0,
        latency_frames=0,
    )
    reversed_command = DmCommandVector(
        np.zeros(2),
        tuple(reversed(ACTUATOR_IDS)),
        "m_opd_equivalent",
    )

    with pytest.raises(ControllerError, match="DmCommandVector"):
        controller.update(np.zeros(2))  # type: ignore[arg-type]
    with pytest.raises(ControllerError, match="actuator_ids"):
        controller.update(reversed_command)
    with pytest.raises(ControllerError, match="DmCommandVector"):
        controller.accept_applied_commands(np.zeros(2))  # type: ignore[arg-type]
    with pytest.raises(ControllerError, match="actuator_ids"):
        controller.accept_applied_commands(reversed_command)
