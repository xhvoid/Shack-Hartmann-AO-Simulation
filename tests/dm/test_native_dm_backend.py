"""Focused contracts for the memoryless native DM spatial backend."""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from shwfs_ao.backends.native.dm import (
    VALID_INFLUENCE_MODELS,
    NativeDmBackend,
    NativeDmError,
    actuator_centers_on_pupil,
    build_influence_functions,
    gaussian_influence_functions,
    square_grid_actuator_centers,
    square_grid_actuator_layout,
    synthesize_opd,
)
from shwfs_ao.core.hashing import stable_array_descriptor


FROZEN_FAMILY_HASHES = {
    "compact_gaussian": "a2aaaa5fc36402b2f81ea4d1794ff6fd8e1339cc9a5d22bf6bab3180b6968a03",
    "gaussian": "0c96eb37409152f15fbef9d9ff9bad8aa9b66a607ba21fc584741674a5e6a6ed",
    "pyramid_like": "e0ace6d10cd6f757f4c4b3a861a0248f87c09395deb854c9b4b91998d4779a2c",
}


@pytest.fixture
def sampled_pupil() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    axis = np.linspace(-1.0, 1.0, 33)
    x_m, y_m = np.meshgrid(axis, axis)
    pupil = x_m**2 + y_m**2 <= 1.0
    return x_m, y_m, pupil


@pytest.fixture
def native_influences(
    sampled_pupil: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> tuple[np.ndarray, np.ndarray]:
    x_m, y_m, pupil = sampled_pupil
    centers_m, pitch_m = square_grid_actuator_centers(2.0, 5)
    influences = build_influence_functions(
        x_m,
        y_m,
        pupil,
        centers_m,
        pitch_m,
        influence_model="gaussian",
        coupling_width_pitch=0.35,
    )
    return influences, pupil


def test_native_module_has_no_legacy_or_policy_dependency() -> None:
    source_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "shwfs_ao"
        / "backends"
        / "native"
        / "dm.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported_modules.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    assert not any(
        module == "legacy" or module.startswith("legacy.") or ".legacy" in module
        for module in imported_modules
    )

    assigned_state = {
        target.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "self"
    }
    assert assigned_state == {"_influence_functions", "_config_hash"}


def test_square_grid_order_and_nominal_indices_are_stable() -> None:
    centers_m, pitch_m, indices_rc = square_grid_actuator_layout(2.0, 5)

    assert pitch_m == pytest.approx(0.5)
    assert indices_rc.tolist() == [
        [2, 0],
        [1, 1],
        [2, 1],
        [3, 1],
        [0, 2],
        [1, 2],
        [2, 2],
        [3, 2],
        [4, 2],
        [1, 3],
        [2, 3],
        [3, 3],
        [2, 4],
    ]
    np.testing.assert_array_equal(
        centers_m,
        np.asarray(
            [
                (-1.0, 0.0),
                (-0.5, -0.5),
                (-0.5, 0.0),
                (-0.5, 0.5),
                (0.0, -1.0),
                (0.0, -0.5),
                (0.0, 0.0),
                (0.0, 0.5),
                (0.0, 1.0),
                (0.5, -0.5),
                (0.5, 0.0),
                (0.5, 0.5),
                (1.0, 0.0),
            ]
        ),
    )

    center_only, center_pitch = square_grid_actuator_centers(2.0, 5)
    alias_centers, alias_pitch = actuator_centers_on_pupil(2.0, 5)
    np.testing.assert_array_equal(center_only, centers_m)
    np.testing.assert_array_equal(alias_centers, centers_m)
    assert center_pitch == alias_pitch == pitch_m
    assert actuator_centers_on_pupil is square_grid_actuator_centers


def test_guard_filtering_does_not_renumber_nominal_grid_indices() -> None:
    base_centers, base_pitch, base_indices = square_grid_actuator_layout(2.0, 4)
    guard_centers, guard_pitch, guard_indices = square_grid_actuator_layout(
        2.0,
        4,
        actuator_margin_fraction=0.5,
    )

    assert base_pitch == guard_pitch
    base_lookup = {
        tuple(index): tuple(center)
        for index, center in zip(base_indices.tolist(), base_centers.tolist())
    }
    guard_lookup = {
        tuple(index): tuple(center)
        for index, center in zip(guard_indices.tolist(), guard_centers.tolist())
    }
    assert base_lookup.items() <= guard_lookup.items()
    assert len(guard_indices) > len(base_indices)


def test_half_cell_inset_layout_preserves_pitch_and_order() -> None:
    centers_m, pitch_m, indices_rc = square_grid_actuator_layout(
        2.0,
        4,
        include_edge_actuators=False,
    )

    assert pitch_m == pytest.approx(0.5)
    assert centers_m.shape == (12, 2)
    assert indices_rc[0].tolist() == [1, 0]
    assert centers_m[0].tolist() == pytest.approx([-0.75, -0.25])
    assert indices_rc[-1].tolist() == [2, 3]
    assert centers_m[-1].tolist() == pytest.approx([0.75, 0.25])


@pytest.mark.parametrize("influence_model", sorted(VALID_INFLUENCE_MODELS))
def test_influence_families_preserve_frozen_samples_and_peak_normalization(
    sampled_pupil: tuple[np.ndarray, np.ndarray, np.ndarray],
    influence_model: str,
) -> None:
    x_m, y_m, pupil = sampled_pupil
    centers_m, pitch_m = square_grid_actuator_centers(2.0, 5)
    influences = build_influence_functions(
        x_m,
        y_m,
        pupil,
        centers_m,
        pitch_m,
        influence_model=influence_model,
        coupling_width_pitch=0.35,
    )

    assert influences.shape == (13, 33, 33)
    assert np.all(np.isfinite(influences))
    assert np.all(influences[:, ~pupil] == 0.0)
    np.testing.assert_array_equal(
        np.max(influences[:, pupil], axis=1),
        np.ones(influences.shape[0]),
    )
    assert stable_array_descriptor(influences)["sha256"] == FROZEN_FAMILY_HASHES[influence_model]


def test_low_level_gaussian_preserves_unnormalized_compatibility_arithmetic(
    sampled_pupil: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> None:
    x_m, y_m, pupil = sampled_pupil
    centers_m = np.asarray([(0.13, -0.21), (0.47, 0.08)])
    pitch_m = 0.5
    coupling = 0.35
    actual = gaussian_influence_functions(
        x_m,
        y_m,
        pupil,
        centers_m,
        pitch_m,
        coupling_width_pitch=coupling,
        normalize_peak=False,
    )

    sigma_m = coupling * pitch_m
    expected = np.asarray(
        [
            np.exp(
                -((x_m - x0) ** 2 + (y_m - y0) ** 2)
                / (2.0 * sigma_m**2)
            )
            for x0, y0 in centers_m
        ]
    )
    expected[:, ~pupil] = 0.0
    np.testing.assert_array_equal(actual, expected)
    assert np.max(actual[0, pupil]) < 1.0


def test_backend_is_immutable_defensive_and_hashes_complete_configuration(
    native_influences: tuple[np.ndarray, np.ndarray],
) -> None:
    influences, _ = native_influences
    mutable_input = np.array(influences, copy=True)
    first = NativeDmBackend(mutable_input)
    second = NativeDmBackend(influences)
    changed_values = np.array(influences, copy=True)
    changed_values[0, 16, 16] += 1.0e-12
    changed = NativeDmBackend(changed_values)
    mutable_input[:] = 0.0

    assert first.backend_name == "native"
    assert first.n_actuators == influences.shape[0]
    assert first.output_shape == influences.shape[1:]
    assert len(first.config_hash) == 64
    assert first.config_hash == second.config_hash
    assert first.config_hash != changed.config_hash
    np.testing.assert_array_equal(first.influence_functions(), influences)
    exposed = first.influence_functions()
    assert not exposed.flags.writeable
    with pytest.raises(ValueError):
        exposed.setflags(write=True)


def test_raw_opd_synthesis_is_linear_memoryless_and_has_positive_sign(
    native_influences: tuple[np.ndarray, np.ndarray],
) -> None:
    influences, pupil = native_influences
    backend = NativeDmBackend(influences)
    first_commands = np.linspace(-4.0e-9, 5.0e-9, backend.n_actuators)
    second_commands = np.linspace(3.0e-9, -2.0e-9, backend.n_actuators)

    combined = backend.opd_from_commands(first_commands + second_commands)
    separate = backend.opd_from_commands(first_commands) + backend.opd_from_commands(
        second_commands
    )
    np.testing.assert_allclose(combined, separate, rtol=2.0e-15, atol=2.0e-24)

    positive_commands = np.zeros(backend.n_actuators)
    positive_commands[6] = 10.0e-9
    positive = backend.opd_from_commands(positive_commands)
    np.testing.assert_array_equal(positive, 10.0e-9 * influences[6])
    assert np.max(positive) == pytest.approx(10.0e-9)
    assert np.all(positive[~pupil] == 0.0)
    # Raw synthesis applies neither piston removal nor a reflective factor two.
    assert float(np.mean(positive[pupil])) > 0.0

    repeated = backend.opd_from_commands(first_commands)
    np.testing.assert_array_equal(repeated, backend.opd_from_commands(first_commands))
    assert not repeated.flags.writeable
    with pytest.raises(ValueError):
        repeated.setflags(write=True)


def test_function_and_backend_synthesis_are_identical(
    native_influences: tuple[np.ndarray, np.ndarray],
) -> None:
    influences, _ = native_influences
    commands_opd_m = np.arange(influences.shape[0], dtype=float) * 1.0e-9
    expected = synthesize_opd(commands_opd_m, influences)
    actual = NativeDmBackend(influences).opd_from_commands(commands_opd_m)
    np.testing.assert_array_equal(actual, expected)


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda: square_grid_actuator_layout(0.0, 5), "positive"),
        (lambda: square_grid_actuator_layout(2.0, True), "integer"),
        (lambda: square_grid_actuator_layout(2.0, 1), ">= 2"),
        (
            lambda: square_grid_actuator_layout(
                2.0,
                5,
                actuator_margin_fraction=-0.1,
            ),
            "non-negative",
        ),
        (
            lambda: NativeDmBackend(np.ones((2, 3))),
            "shape",
        ),
        (
            lambda: NativeDmBackend(np.asarray([[[np.nan]]])),
            "finite",
        ),
        (
            lambda: NativeDmBackend(np.asarray([[[1.0 + 2.0j]]])),
            "real numeric",
        ),
        (
            lambda: synthesize_opd(np.ones(2), np.ones((3, 2, 2))),
            "shape",
        ),
        (
            lambda: synthesize_opd(
                np.asarray([np.inf]),
                np.ones((1, 2, 2)),
            ),
            "finite",
        ),
        (
            lambda: synthesize_opd(
                np.asarray([1.0 + 2.0j]),
                np.ones((1, 2, 2)),
            ),
            "real numeric",
        ),
    ],
)
def test_native_boundary_rejects_invalid_inputs(call: object, message: str) -> None:
    with pytest.raises(NativeDmError, match=message):
        call()


def test_influence_builder_rejects_invalid_geometry_and_family(
    sampled_pupil: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> None:
    x_m, y_m, pupil = sampled_pupil
    centers_m = np.asarray([(0.0, 0.0)])

    with pytest.raises(NativeDmError, match="influence_model"):
        build_influence_functions(
            x_m,
            y_m,
            pupil,
            centers_m,
            0.5,
            influence_model="spline",
        )
    with pytest.raises(NativeDmError, match="boolean"):
        build_influence_functions(
            x_m,
            y_m,
            pupil.astype(float),
            centers_m,
            0.5,
        )
    with pytest.raises(NativeDmError, match="identical"):
        build_influence_functions(
            x_m[:-1],
            y_m,
            pupil,
            centers_m,
            0.5,
        )
    with pytest.raises(NativeDmError, match="real numeric"):
        build_influence_functions(
            x_m.astype(complex) + 1.0j,
            y_m,
            pupil,
            centers_m,
            0.5,
        )
    with pytest.raises(NativeDmError, match="positive"):
        build_influence_functions(
            x_m,
            y_m,
            pupil,
            centers_m,
            0.0,
        )
