"""Focused compatibility regressions for the AO-REF-008 legacy migration."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from shwfs_ao.legacy._reconstruction_adapters import (
    _legacy_least_squares_reconstructor,
)
from shwfs_ao.legacy.interaction_matrix import tsvd_reconstruct_commands


ROOT = Path(__file__).resolve().parents[2]
LEGACY_ROOT = ROOT / "src" / "shwfs_ao" / "legacy"
LOOP_MODULES = (
    "shwfs_detector.py",
    "ao_closed_loop.py",
)


def test_legacy_adapter_reuses_the_cached_operator_for_a_repeated_mask() -> None:
    matrix = np.asarray(
        [
            [1.0, 0.0],
            [0.0, 1.0],
            [1.0, 1.0],
            [2.0, -1.0],
        ]
    )
    reconstructor = _legacy_least_squares_reconstructor(
        matrix,
        1.0e-12,
        matrix_error="matrix",
        length_error="length",
        no_rows_error="rows",
    )

    first = reconstructor.reconstruct(matrix @ np.asarray([2.0, -1.0]))
    second = reconstructor.reconstruct(matrix @ np.asarray([-3.0, 4.0]))

    np.testing.assert_allclose(first.coordinates, [2.0, -1.0])
    np.testing.assert_allclose(second.coordinates, [-3.0, 4.0])
    info = reconstructor.cache_info
    assert info is not None
    assert info.hits == 1
    assert info.misses == 1
    assert info.svd_computations == 1
    assert info.current_size == 1


def test_legacy_tsvd_excludes_invalid_rows_without_using_zero_measurements() -> None:
    matrix = np.asarray(
        [
            [1.0, 0.0],
            [0.0, 1.0],
            [np.nan, np.nan],
            [1.0, 1.0],
        ]
    )
    measurement = np.asarray([2.0, -3.0, 1.0e12, np.nan])
    poke_result = SimpleNamespace(
        poke_matrix=matrix,
        rcond=1.0e-12,
        source_class="synthetic_assumed",
    )

    result = tsvd_reconstruct_commands(measurement, poke_result)

    np.testing.assert_allclose(result.commands_nm, [2.0, -3.0])
    np.testing.assert_allclose(result.reconstructed_signal_px, [2.0, -3.0, 0.0, 0.0])
    np.testing.assert_allclose(result.residual_px[:3], [0.0, 0.0, 1.0e12], atol=1.0e-14)
    assert np.isnan(result.residual_px[3])
    assert result.kept_modes == 2


class _ReconstructorCallInLoopFinder(ast.NodeVisitor):
    def __init__(self) -> None:
        self.loop_depth = 0
        self.calls: list[int] = []

    def _visit_loop(self, node: ast.For | ast.While) -> None:
        self.loop_depth += 1
        self.generic_visit(node)
        self.loop_depth -= 1

    visit_For = _visit_loop
    visit_While = _visit_loop

    def visit_Call(self, node: ast.Call) -> None:
        if (
            self.loop_depth
            and isinstance(node.func, ast.Name)
            and node.func.id.startswith("_legacy_")
            and node.func.id.endswith("_reconstructor")
        ):
            self.calls.append(node.lineno)
        self.generic_visit(node)


def test_frame_and_trial_loops_do_not_rebuild_legacy_reconstructors() -> None:
    offenders: dict[str, list[int]] = {}
    for filename in LOOP_MODULES:
        finder = _ReconstructorCallInLoopFinder()
        finder.visit(
            ast.parse(
                (LEGACY_ROOT / filename).read_text(encoding="utf-8"),
                filename=filename,
            )
        )
        if finder.calls:
            offenders[filename] = finder.calls
    assert offenders == {}
