"""ESO-04: sparse linear-spline DM operator.

The oracle is a dense influence cube assembled here directly from the basis
equation ``w_i = L((x - x_i)/p) L((y - y_i)/p)`` with ``L(t) = max(0, 1-|t|)``,
masked to the pupil, independently of the operator's sparse construction.
"""

from __future__ import annotations

import numpy as np
import pytest

from shwfs_ao.backends.native.dm import square_grid_actuator_layout
from shwfs_ao.backends.native.dm_operator import (
    LINEAR_SPLINE_BASIS_ID,
    LinearSplineDmOperator,
    LinearSplineDmOperatorError,
)
from shwfs_ao.core.geometry import build_pupil_geometry
from shwfs_ao.core.types import DmCommandVector
from shwfs_ao.dm import (
    DMConfig,
    DMConfigError,
    DeformableMirror,
    DeformableMirrorError,
    build_native_deformable_mirror,
)


def _grid(n=60, diameter=5.0, obstruction=0.28):
    return build_pupil_geometry(
        telescope_diameter_m=diameter,
        pupil_shape=(n, n),
        central_obstruction_ratio=obstruction,
    )


def _layout(across=11, diameter=5.0, margin=None):
    margin = 2.0 * np.sqrt(2.0) / (across - 1) if margin is None else margin
    return square_grid_actuator_layout(
        diameter, across, include_edge_actuators=True, actuator_margin_fraction=margin
    )


def _dense_oracle(pupil, centers, pitch):
    x = pupil.x_m
    y = pupil.y_m
    cube = np.empty((len(centers),) + x.shape)
    for index, (cx, cy) in enumerate(centers):
        wx = np.maximum(0.0, 1.0 - np.abs(x - cx) / pitch)
        wy = np.maximum(0.0, 1.0 - np.abs(y - cy) / pitch)
        cube[index] = np.where(pupil.pupil_mask, wx * wy, 0.0)
    return cube


def _relative_l2(actual, expected):
    norm = np.linalg.norm(expected)
    return np.linalg.norm(actual - expected) / (norm if norm > 0 else 1.0)


@pytest.fixture(scope="module")
def fixture():
    pupil = _grid()
    centers, pitch, _ = _layout()
    operator = LinearSplineDmOperator(
        pupil.x_m, pupil.y_m, pupil.pupil_mask, centers, pitch
    )
    return pupil, centers, pitch, operator, _dense_oracle(pupil, centers, pitch)


def test_forward_matches_an_independently_assembled_dense_cube(fixture):
    pupil, centers, pitch, operator, cube = fixture
    rng = np.random.default_rng(1)
    count = len(centers)
    boundary = int(np.argmax(np.hypot(*centers.T)))
    commands = {
        "random": rng.normal(scale=1e-7, size=count),
        "one_hot_interior": np.eye(count)[count // 2 + 3] * 2e-8,
        "one_hot_boundary": np.eye(count)[boundary] * 3e-8,
        "null": np.zeros(count),
    }
    for label, values in commands.items():
        expected = np.tensordot(values, cube, axes=1)
        actual = operator.opd_from_commands(values)
        if label == "null":
            assert np.array_equal(actual, np.zeros_like(actual))
        else:
            assert _relative_l2(actual, expected) <= 1e-11, label
    np.testing.assert_allclose(
        operator.dense_influence_functions(), cube, rtol=0.0, atol=1e-15
    )
    assert operator.basis_id == LINEAR_SPLINE_BASIS_ID


def test_adjoint_passes_the_dot_product_test(fixture):
    pupil, centers, _, operator, cube = fixture
    rng = np.random.default_rng(2)
    for _ in range(3):
        commands = rng.normal(size=len(centers))
        field = rng.normal(size=pupil.pupil_shape)
        field[~pupil.pupil_mask] = np.nan  # outside-pupil samples are ignored
        left = float(np.nansum(operator.opd_from_commands(commands) * field))
        right = float(commands @ operator.adjoint(field))
        assert abs(left - right) <= 1e-10 * max(abs(left), abs(right))
    np.testing.assert_allclose(
        operator.adjoint(np.where(pupil.pupil_mask, 1.0, np.nan)),
        cube.sum(axis=(1, 2)),
        rtol=1e-12,
    )


def test_tents_form_a_partition_of_unity_inside_the_actuator_hull():
    pupil = _grid(n=64, obstruction=0.0)
    centers, pitch, _ = _layout(margin=0.5)  # retain the whole square grid
    operator = LinearSplineDmOperator(pupil.x_m, pupil.y_m, pupil.pupil_mask, centers, pitch)
    piston = operator.opd_from_commands(np.full(len(centers), 1.0))
    np.testing.assert_allclose(piston[pupil.pupil_mask], 1.0, rtol=0.0, atol=1e-14)


def test_zero_illuminated_support_is_classified_against_the_real_pupil(fixture):
    pupil, centers, _, operator, cube = fixture
    expected_zero = ~np.any(cube != 0.0, axis=(1, 2))
    np.testing.assert_array_equal(operator.zero_support_mask, expected_zero)
    radii = np.hypot(*centers.T)
    obstruction_radius = 0.5 * 5.0 * 0.28
    # The central actuator's support lies inside the obstruction.
    centre = int(np.argmin(radii))
    assert operator.zero_support_mask[centre]
    # Actuators next to the obstruction and at the outer rim keep partial
    # support: they are not excluded.
    partial = [
        index
        for index, radius in enumerate(radii)
        if 0 < radius - obstruction_radius < 0.5 or 0 < radius - 2.5 < 0.5
    ]
    assert partial
    illuminated_fraction = operator.illuminated_support_counts[partial]
    assert np.all(illuminated_fraction > 0)
    assert np.all(operator.illuminated_support_counts[~expected_zero] > 0)


def test_storage_scales_with_support_not_with_the_dense_cube(fixture):
    _, centers, _, operator, _ = fixture
    assert operator.stored_bytes < 0.2 * operator.dense_influence_bytes
    assert operator.nnz <= len(centers) * (2 * 12 + 1) ** 2


def test_dense_compatibility_is_size_guarded(fixture):
    _, _, _, operator, _ = fixture
    with pytest.raises(LinearSplineDmOperatorError, match="refused"):
        operator.dense_influence_functions(max_bytes=1024)


def test_probe_chunks_equal_full_synthesis(fixture):
    _, centers, _, operator, _ = fixture
    rng = np.random.default_rng(5)
    chosen = np.sort(rng.choice(len(centers), size=7, replace=False))
    amplitudes = rng.normal(size=7) * 1e-8
    commands = np.zeros(len(centers))
    commands[chosen] = amplitudes
    np.testing.assert_allclose(
        operator.opd_for_actuators(chosen, amplitudes),
        operator.opd_from_commands(commands),
        rtol=0.0,
        atol=1e-24,
    )


def test_operator_identity_tracks_support_weights_and_pupil(fixture):
    pupil, centers, pitch, operator, _ = fixture
    same = LinearSplineDmOperator(pupil.x_m, pupil.y_m, pupil.pupil_mask, centers, pitch)
    assert same.config_hash == operator.config_hash
    mask = pupil.pupil_mask.copy()
    row, column = np.argwhere(mask)[len(np.argwhere(mask)) // 3]
    mask[row, column] = False
    altered_pupil = LinearSplineDmOperator(pupil.x_m, pupil.y_m, mask, centers, pitch)
    shifted = centers.copy()
    shifted[4, 0] += 1e-3
    altered_centre = LinearSplineDmOperator(pupil.x_m, pupil.y_m, pupil.pupil_mask, shifted, pitch)
    assert len({operator.config_hash, altered_pupil.config_hash, altered_centre.config_hash}) == 3


def test_owned_operator_data_cannot_be_mutated(fixture):
    _, _, _, operator, _ = fixture
    before = operator.config_hash
    indices, weights = operator.local_influence(5)
    for array in (indices, weights, operator.zero_support_mask, operator.support_bounds_rc):
        with pytest.raises(ValueError):
            array[...] = 0
    with pytest.raises(ValueError):
        operator._csc.data[0] = 99.0  # noqa: SLF001 - the guarded internal buffer
    synthesized = operator.opd_from_commands(np.ones(operator.n_actuators))
    with pytest.raises(ValueError):
        synthesized[0, 0] = 1.0
    assert operator.config_hash == before


def _dm(model, *, dead=(), stuck=(), stroke_nm=50.0, stuck_nm=10.0):
    pupil = _grid()
    config = DMConfig(
        telescope_diameter_m=5.0,
        n_actuators_across=11,
        influence_model=model,
        coupling_width_pitch=1.0 if model == "linear_spline" else 0.4,
        stroke_limit_nm=stroke_nm,
        actuator_margin_fraction=2.0 * np.sqrt(2.0) / 10,
        dead_actuator_indices=dead,
        stuck_actuator_indices=stuck,
        stuck_command_nm=stuck_nm,
    )
    return build_native_deformable_mirror(pupil.x_m, pupil.y_m, pupil.pupil_mask, config)


def test_command_policy_matches_the_dense_dm_policy():
    scalable = _dm("linear_spline", dead=(3,), stuck=(7,))
    dense = _dm("gaussian", dead=(3,), stuck=(7,))
    assert scalable.is_scalable and not dense.is_scalable
    assert scalable.actuator_ids == dense.actuator_ids
    assert scalable.controllable_actuator_ids == dense.controllable_actuator_ids
    rng = np.random.default_rng(3)
    values = rng.normal(scale=60e-9, size=scalable.n_actuators)
    command = DmCommandVector(values, scalable.actuator_ids, "m_opd_equivalent")
    fast = scalable.opd_from_commands(command)
    slow = dense.opd_from_commands(command)
    np.testing.assert_array_equal(fast.applied_commands_opd_m, slow.applied_commands_opd_m)
    np.testing.assert_array_equal(fast.saturated_mask, slow.saturated_mask)
    assert fast.saturation_fraction == slow.saturation_fraction
    assert fast.applied_commands_opd_m[3] == 0.0
    assert fast.applied_commands_opd_m[7] == pytest.approx(10e-9)
    # Positive command, positive correction OPD at the actuator.
    one = np.zeros(scalable.n_actuators)
    interior = int(np.flatnonzero(~scalable.zero_support_mask)[20])
    one[interior] = 5e-9
    synthesis = scalable.opd_from_commands(
        DmCommandVector(one, scalable.actuator_ids, "m_opd_equivalent")
    )
    assert synthesis.correction_opd_m.max() > 0.0
    assert synthesis.correction_opd_m.min() >= 0.0


def test_scalable_mirror_never_materializes_the_cube_and_guards_dense_access():
    calls = []

    class _NoDense(LinearSplineDmOperator):
        def dense_influence_functions(self, *, max_bytes=0):
            calls.append("dense")
            raise LinearSplineDmOperatorError("dense materialization disabled by test")

        def influence_functions(self):
            calls.append("influence_functions")
            raise AssertionError("influence_functions must not be called")

    pupil = _grid()
    centers, pitch, grid_rc = _layout()
    from shwfs_ao.dm import actuator_ids_from_grid_indices

    operator = _NoDense(pupil.x_m, pupil.y_m, pupil.pupil_mask, centers, pitch)
    config = DMConfig(
        telescope_diameter_m=5.0, n_actuators_across=11, influence_model="linear_spline",
        coupling_width_pitch=1.0, actuator_margin_fraction=2.0 * np.sqrt(2.0) / 10,
    )
    mirror = DeformableMirror(
        config,
        operator,  # type: ignore[arg-type]
        actuator_ids=actuator_ids_from_grid_indices(grid_rc),
        actuator_centers_m=centers,
        actuator_pitch_m=pitch,
        x_m=pupil.x_m,
        y_m=pupil.y_m,
        pupil_mask=pupil.pupil_mask,
    )
    assert not calls
    assert mirror.output_shape == pupil.pupil_shape
    assert mirror.geometric_exclusion_ids == tuple(
        identifier
        for identifier, zero in zip(mirror.actuator_ids, operator.zero_support_mask)
        if zero
    )
    mirror.opd_from_commands(
        DmCommandVector(np.zeros(mirror.n_actuators), mirror.actuator_ids, "m_opd_equivalent")
    )
    assert not calls
    with pytest.raises(DeformableMirrorError, match="disabled by test"):
        mirror.influence_functions
    assert calls == ["dense"]


def test_scalable_mirror_identity_differs_from_dense_and_is_stable():
    first = _dm("linear_spline")
    second = _dm("linear_spline")
    assert first.config_hash == second.config_hash
    assert first.config_hash != _dm("gaussian").config_hash
    assert _dm("linear_spline", dead=(2,)).config_hash != first.config_hash


def test_linear_spline_requires_a_one_pitch_support():
    with pytest.raises(DMConfigError, match="coupling_width_pitch must be 1.0"):
        DMConfig(influence_model="linear_spline", coupling_width_pitch=0.5)


def test_mirror_adjoint_matches_the_operator_and_dense_paths():
    scalable = _dm("linear_spline")
    pupil = _grid()
    field = np.random.default_rng(9).normal(size=pupil.pupil_shape)
    np.testing.assert_allclose(
        scalable.adjoint_opd(field),
        np.tensordot(scalable.influence_functions, field, axes=([1, 2], [0, 1])),
        rtol=1e-12,
        atol=1e-12,
    )
