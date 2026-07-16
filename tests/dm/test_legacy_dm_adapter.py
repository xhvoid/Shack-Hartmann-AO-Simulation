"""Compatibility checks for the AO-REF-006 legacy DM façade."""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from shwfs_ao.dm import DMConfig as CanonicalDMConfig
from shwfs_ao.legacy import dm_model as legacy


def _direct_model(
    *,
    config: legacy.DMConfig,
    influences: np.ndarray,
    dead: np.ndarray | None = None,
    stuck: np.ndarray | None = None,
) -> legacy.DMModel:
    count, ny, nx = influences.shape
    x_axis = np.linspace(-1.0, 1.0, nx)
    y_axis = np.linspace(-1.0, 1.0, ny)
    x_m, y_m = np.meshgrid(x_axis, y_axis)
    return legacy.DMModel(
        config=config,
        x_m=x_m,
        y_m=y_m,
        pupil_mask=np.ones((ny, nx), dtype=bool),
        actuator_centers_m=np.column_stack(
            [np.arange(count, dtype=float), np.zeros(count)]
        ),
        actuator_pitch_m=1.0,
        influence_functions=influences,
        dead_actuator_mask=(
            np.zeros(count, dtype=bool) if dead is None else dead
        ),
        stuck_actuator_mask=(
            np.zeros(count, dtype=bool) if stuck is None else stuck
        ),
    )


def test_legacy_config_is_the_canonical_config_identity() -> None:
    assert legacy.DMConfig is CanonicalDMConfig


def test_direct_mutable_model_is_rewrapped_for_every_synthesis() -> None:
    influences = np.asarray(
        [
            [[1.0, 0.0], [0.0, 0.0]],
            [[0.0, 0.0], [0.0, 1.0]],
        ]
    )
    model = _direct_model(
        config=legacy.DMConfig(
            n_actuators_across=2,
            stroke_limit_nm=100.0,
            source_note="Direct mutable legacy adapter fixture.",
        ),
        influences=influences,
    )
    commands = np.asarray([10.0, 0.0])

    first = legacy.synthesize_dm_opd_nm(commands, model, remove_piston=False)
    model.influence_functions[0] *= 2.0
    second = legacy.synthesize_dm_opd_nm(commands, model, remove_piston=False)

    np.testing.assert_allclose(second.opd_nm, 2.0 * first.opd_nm)


def test_fault_precedence_and_saturation_remain_exact_at_nm_boundary() -> None:
    influences = np.asarray(
        [
            [[1.0, 0.0], [0.0, 0.0]],
            [[0.0, 1.0], [0.0, 0.0]],
            [[0.0, 0.0], [1.0, 0.0]],
        ]
    )
    model = _direct_model(
        config=legacy.DMConfig(
            n_actuators_across=2,
            stroke_limit_nm=25.0,
            stuck_command_nm=100.0,
            source_note="Fault precedence legacy adapter fixture.",
        ),
        influences=influences,
        dead=np.asarray([True, False, False]),
        stuck=np.asarray([True, True, False]),
    )

    applied, saturated = legacy.clip_commands_nm(
        np.asarray([0.0, 0.0, 100.0]),
        model,
    )

    # Stuck wins the overlap at index zero.  A clipped stuck preset is not
    # diagnosed as requested-command saturation; only index two is saturated.
    np.testing.assert_array_equal(applied, np.asarray([25.0, 25.0, 25.0]))
    np.testing.assert_array_equal(saturated, np.asarray([False, False, True]))

    at_limit, at_limit_saturated = legacy.clip_commands_nm(
        np.asarray([0.0, 0.0, 25.0]),
        model,
    )
    assert at_limit[2] == 25.0
    assert not at_limit_saturated[2]


def test_legacy_module_contains_no_actuator_or_influence_physical_engine() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "shwfs_ao"
        / "legacy"
        / "dm_model.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    functions = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert "_influence_function" not in functions
    assert "_build_native_deformable_mirror" in {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


def test_static_fitting_trend_retains_frozen_canonical_adapter_values() -> None:
    axis = np.linspace(-1.0, 1.0, 52)
    x_m, y_m = np.meshgrid(axis, axis)
    pupil = x_m**2 + y_m**2 <= 1.0
    target_opd_nm = np.where(
        pupil,
        120.0 * (x_m**2 - y_m**2)
        + 70.0 * x_m * y_m
        + 35.0
        * np.sin(3.0 * np.pi * x_m / 2.0)
        * np.cos(2.0 * np.pi * y_m / 2.0),
        np.nan,
    )

    residuals = []
    for count in (4, 6, 8):
        model = legacy.build_dm_model(
            x_m,
            y_m,
            pupil,
            legacy.DMConfig(
                telescope_diameter_m=2.0,
                n_actuators_across=count,
                coupling_width_pitch=0.45,
                stroke_limit_nm=1000.0,
                source_note="Frozen AO-REF-006 fitting trend fixture.",
            ),
        )
        residuals.append(
            legacy.fit_static_opd_with_dm(
                target_opd_nm,
                model,
                rcond=1.0e-6,
            ).residual_rms_nm
        )

    assert residuals == pytest.approx(
        [
            51.86194885928004,
            37.39132148795935,
            29.586091928004787,
        ],
        rel=2.0e-14,
        abs=1.0e-12,
    )
    assert np.all(np.diff(residuals) < 0.0)
