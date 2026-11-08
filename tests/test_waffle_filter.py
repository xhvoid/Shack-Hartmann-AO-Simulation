"""Waffle-family filter of the sparse LSMR reconstructor.

The family is built on synthetic Fried geometries and checked against an
independent dense construction.  The profile checks cover the schema-v8
``reconstructor.waffle_filter_cutoff`` rules and show that
``det_ccd_42m_r3band_derived@2`` differs from ``@1`` only by the filter.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, replace
import math

import numpy as np
import pytest
import scipy.sparse as sp

import shwfs_ao.calibration.sparse as sparse_module
from shwfs_ao.calibration.sparse import (
    SparseCalibrationError,
    SparseInteractionMatrix,
    SparseLsmrReconstructor,
    SolverTelemetry,
    global_waffle_signs,
    local_waffle_operator,
    response_waffle_modes,
)
from shwfs_ao.core.provenance import Provenance
from shwfs_ao.core.types import MeasurementVector
from shwfs_ao.dm import (
    actuator_id,
    actuator_ids_from_grid_indices,
    grid_indices_from_actuator_ids,
)
from shwfs_ao.dm.config import DMConfigError
from shwfs_ao.experiments.scao import _build_reconstructor
from shwfs_ao.io.benchmark_ledgers import (
    ASSUMPTION_LEDGER_RESOURCE,
    load_assumption_ledger,
    load_source_ledger,
    validate_benchmark_profiles,
)
from shwfs_ao.io.configs import (
    PROFILE_SCHEMA_VERSION,
    SystemConfigError,
    load_system_profile,
    system_config_from_mapping,
    system_config_to_mapping,
)
from shwfs_ao.io.resources import load_resource_manifest


PROFILE = "det_ccd_42m_r3band_derived"
# Version 1 keeps the identity it had before the filter existed.
V1_CONFIG_HASH = "1ebaf8f35f977e01e2d65a496cf9d4ea06a5a0bc79362852df97646090db8b4f"
V2_CONFIG_HASH = "e982ddb99865a070d3c0d5ff88d3711aa66a1caf7424f97566279d8887b60967"
DETECTOR_SOURCES = "benchmarks/detector_source_ledger.v2.json"
DETECTOR_LEDGER_V2 = "benchmarks/detector_level.assumptions.v2.json"
DETECTOR_LEDGER_V3 = "benchmarks/detector_level.assumptions.v3.json"


def _matrix_from_dense(dense: np.ndarray, coordinate_ids=None) -> SparseInteractionMatrix:
    rows, columns = dense.shape
    csr = sp.csr_matrix(dense)
    return SparseInteractionMatrix.create(
        data=csr.data,
        indices=csr.indices,
        indptr=csr.indptr,
        row_valid=np.ones(rows, dtype=bool),
        row_ids=tuple(f"r{i}" for i in range(rows)),
        coordinate_ids=(
            tuple(f"c{j}" for j in range(columns))
            if coordinate_ids is None
            else tuple(coordinate_ids)
        ),
        coordinate_kind="dm_command_opd",
        calibration_amplitude_m=1e-8,
        measurement_unit="pixel",
        coordinate_unit="m_opd_equivalent",
        matrix_unit="pixel / m_opd_equivalent",
        method="central",
        include_noise=False,
        repeat_count=1,
        sensor_config_hash="sensor",
        geometry_hash="geometry",
        detector_hash=None,
        dm_hash="dm",
        sensor_response_hash=None,
        strategy="test",
        probe_group_count=1,
        sensor_call_count=1,
        exclusions=(),
        provenance=Provenance(source_class="synthetic_assumed", source_note="test"),
    )


def _measurement(matrix, values, valid=None):
    return MeasurementVector(
        values=np.asarray(values, dtype=float),
        valid_rows=np.ones(matrix.shape[0], dtype=bool) if valid is None else valid,
        row_ids=matrix.row_ids,
        measurement_unit="pixel",
    )


def _fried_slopes(cells: int) -> np.ndarray:
    """Mean x and y gradient of a bilinear surface over every cell of a Fried geometry.

    Actuators sit on the ``(cells + 1)²`` cell corners; each lenslet reports
    the mean gradient of the bilinear interpolant over its cell, which is the
    difference of the corner means on opposite sides.  The global checkerboard
    gives every cell two ``+a`` and two ``-a`` corners on each side, so it is
    exactly invisible.
    """

    n = cells + 1
    rows = []
    for i in range(cells):
        for j in range(cells):
            x = np.zeros((n, n))
            y = np.zeros((n, n))
            x[i, j] = x[i + 1, j] = -0.5
            x[i, j + 1] = x[i + 1, j + 1] = 0.5
            y[i, j] = y[i, j + 1] = -0.5
            y[i + 1, j] = y[i + 1, j + 1] = 0.5
            rows += [x.ravel(), y.ravel()]
    return np.array(rows)


def _pupil_fried(cells: int, *, obstruction: float = 0.3, samples: int = 16, min_fill: float = 0.5):
    """Fried geometry on an annular pupil, with partially illuminated edge lenslets.

    Each retained lenslet reports the mean x and y gradient of the bilinear
    actuator surface over its *illuminated* part.  For a full cell that is the
    difference of the corner means; for a partial cell the illuminated
    centroid ``(u, v)`` is off the cell centre and the local waffle enters the
    measurement in proportion to the offset.  Partial edge lenslets therefore
    break the exact symmetry of the full-cell Fried geometry (the checkerboard
    times any command has the same response norm as the command itself), as
    the pupil edge of a real Shack-Hartmann does.  Returns the dense response
    (x and y row per lenslet) and the ``(row, column)`` grid position of every
    actuator column.
    """

    centre = cells / 2
    t = (np.arange(samples) + 0.5) / samples
    v, u = np.meshgrid(t, t, indexing="ij")
    kept = []
    for i in range(cells):
        for j in range(cells):
            radius = np.hypot(j + u - centre, i + v - centre)
            lit = (radius <= centre) & (radius >= obstruction * centre)
            if lit.mean() >= min_fill:
                kept.append((i, j, float(u[lit].mean()), float(v[lit].mean())))
    actuators = sorted({(i + a, j + b) for i, j, _, _ in kept for a in (0, 1) for b in (0, 1)})
    index = {position: k for k, position in enumerate(actuators)}
    rows = []
    for i, j, ub, vb in kept:
        x = np.zeros(len(actuators))
        y = np.zeros(len(actuators))
        z00, z01 = index[(i, j)], index[(i, j + 1)]
        z10, z11 = index[(i + 1, j)], index[(i + 1, j + 1)]
        x[z01] += 1 - vb
        x[z00] -= 1 - vb
        x[z11] += vb
        x[z10] -= vb
        y[z10] += 1 - ub
        y[z00] -= 1 - ub
        y[z11] += ub
        y[z01] -= ub
        rows += [x, y]
    return np.array(rows), np.array(actuators, dtype=np.int64)


def _waffle_oracle(dense: np.ndarray, grid: np.ndarray, cutoff: float, threshold: float = 0.5):
    """Independent construction: dense eigenpairs, the band split by local waffle, the twin response."""

    rms = np.sqrt(np.mean(np.linalg.norm(dense, axis=0) ** 2))
    gram = dense.T @ dense / rms**2
    values, vectors = np.linalg.eigh(gram)
    response = np.sqrt(np.maximum(values, 0.0))
    position = {tuple(p): k for k, p in enumerate(grid.tolist())}
    rows = []
    for (r, c), k00 in position.items():
        corners = [position.get((r + 1, c)), position.get((r, c + 1)), position.get((r + 1, c + 1))]
        if None in corners:
            continue
        row = np.zeros(grid.shape[0])
        row[[k00, corners[2]]] = 1.0
        row[[corners[0], corners[1]]] = -1.0
        rows.append(row)
    waffle = np.array(rows)
    band = vectors[:, response < 1.5 * cutoff]
    split_values, split = np.linalg.eigh((waffle @ band).T @ (waffle @ band) / 16.0)
    twins = band @ split[:, split_values > threshold]
    twin_values, rotation = np.linalg.eigh(twins.T @ gram @ twins)
    twin_response = np.sqrt(np.maximum(twin_values, 0.0))
    return {
        "rms": rms,
        "response": response,
        "vectors": vectors,
        "fraction": np.sum((waffle @ vectors) ** 2, axis=0) / 16.0,
        "waffle": waffle,
        "smooth": band @ split[:, split_values <= threshold],
        "twin_response": twin_response,
        "family": twins @ rotation[:, twin_response < cutoff],
    }


def test_actuator_ids_give_their_grid_indices_and_waffle_signs():
    ids = tuple(actuator_id(r, c) for r in range(3) for c in range(4))
    grid = grid_indices_from_actuator_ids(ids)
    assert actuator_ids_from_grid_indices(grid) == ids
    signs = global_waffle_signs(ids)
    np.testing.assert_array_equal(signs, [1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, -1])
    assert not signs.flags.writeable
    with pytest.raises(DMConfigError, match="not an actuator ID"):
        global_waffle_signs(("c0", "c1"))
    with pytest.raises(DMConfigError, match="non-empty sequence"):
        grid_indices_from_actuator_ids("actuator-r0000-c0000")


def test_the_local_waffle_operator_is_the_combination_a_full_lenslet_does_not_sense():
    cells = 4
    n = cells + 1
    grid = np.array([(r, c) for r in range(n) for c in range(n)])
    operator = local_waffle_operator(grid)
    assert operator.shape == (cells * cells, n * n)
    checkerboard = np.where(grid.sum(axis=1) % 2 == 0, 1.0, -1.0)
    np.testing.assert_array_equal(np.abs(operator @ checkerboard), 4.0)
    for smooth in (np.ones(n * n), grid[:, 0].astype(float), grid[:, 1].astype(float)):
        np.testing.assert_array_equal(operator @ smooth, 0.0)
    # Each cell's waffle row is orthogonal to that lenslet's two gradient rows.
    fried = _fried_slopes(cells).reshape(cells * cells, 2, n * n)
    np.testing.assert_allclose(np.einsum("kci,ki->kc", fried, operator.toarray()), 0.0, atol=1e-15)
    # Cells with a missing corner have no row.
    missing = grid[[k for k in range(n * n) if tuple(grid[k]) != (2, 2)]]
    assert local_waffle_operator(missing).shape == (cells * cells - 4, n * n - 1)
    for bad, message in (
        (grid.astype(float), "integers"),
        (np.vstack([grid, grid[:1]]), "unique"),
        (grid - 1, "non-negative"),
        (grid[:, :1], "\\(count, 2\\)"),
    ):
        with pytest.raises(SparseCalibrationError, match=message):
            local_waffle_operator(bad)


def test_the_waffle_family_is_the_weakly_sensed_checkerboard_twin_subspace():
    dense, grid = _pupil_fried(24)  # 404 lenslets, 468 actuators
    cutoff = 0.1
    oracle = _waffle_oracle(dense, grid, cutoff)
    response, vectors, fraction = oracle["response"], oracle["vectors"], oracle["fraction"]
    band = response < 1.5 * cutoff
    smooth = oracle["smooth"]
    # Tip and tilt and their checkerboard twins respond almost equally, and the
    # response eigenvectors mix them: picking eigenvectors by their local-waffle
    # fraction would remove smooth (turbulence-correcting) content.
    assert np.count_nonzero(band & (fraction > 0.2) & (fraction < 0.8)) >= 3
    by_eigenvector = vectors[:, (response < cutoff) & (fraction > 0.5)]
    assert np.linalg.norm(smooth.T @ by_eigenvector) > 0.5
    matrix = _matrix_from_dense(dense)
    common = dict(
        damping_relative=1e-3, atol=1e-14, btol=1e-14, max_iterations=20_000, min_valid_fraction=0.5
    )
    plain = SparseLsmrReconstructor(matrix, **common)
    filtered = SparseLsmrReconstructor(
        matrix, waffle_filter_cutoff=cutoff, actuator_grid_indices=grid, **common
    )
    narrow = SparseLsmrReconstructor(
        matrix, waffle_filter_cutoff=0.05, actuator_grid_indices=grid, **common
    )
    basis = filtered.waffle_modes
    family = oracle["family"]
    assert basis.shape == family.shape == (grid.shape[0], 3) and not basis.flags.writeable
    np.testing.assert_allclose(basis.T @ basis, np.eye(3), atol=1e-12)
    np.testing.assert_allclose(basis @ basis.T, family @ family.T, atol=1e-10)
    # Checkerboard-like, weakly sensed, and free of the band's smooth modes.
    assert np.min(np.sum((oracle["waffle"] @ basis) ** 2, axis=0) / 16.0) > 0.5
    assert np.max(np.linalg.norm(dense @ basis, axis=0)) / oracle["rms"] < cutoff
    assert np.abs(smooth.T @ basis).max() < 1e-10
    checkerboard = np.where(grid.sum(axis=1) % 2 == 0, 1.0, -1.0)
    rows, columns = (grid - grid.mean(axis=0)).T
    for twin in (checkerboard, checkerboard * rows, checkerboard * columns):
        assert np.linalg.norm(basis.T @ twin) / np.linalg.norm(twin) > 0.95
    assert narrow.waffle_modes.shape[1] == 1
    diagnostics = filtered.waffle_modes_diagnostics
    twin_response = oracle["twin_response"]
    assert diagnostics["count"] == 3 and diagnostics["eigensolver"] == "dense_eigh"
    assert diagnostics["eigenpairs"] == np.count_nonzero(band)
    assert diagnostics["band_factor"] == 1.5 and diagnostics["local_fraction_threshold"] == 0.5
    assert diagnostics["twin_subspace"] == twin_response.size == 4
    assert diagnostics["smallest_selected_response"] == pytest.approx(twin_response[0], rel=1e-9)
    assert diagnostics["largest_selected_response"] == pytest.approx(twin_response[2], rel=1e-9)
    assert diagnostics["first_response_at_or_above_cutoff"] == pytest.approx(twin_response[3], rel=1e-9)
    assert diagnostics["smallest_twin_local_fraction"] > 0.5 > diagnostics["largest_smooth_local_fraction"]
    unit = checkerboard / np.linalg.norm(checkerboard)
    assert diagnostics["checkerboard_overlap"] == pytest.approx(np.linalg.norm(basis.T @ unit), rel=1e-12)
    assert diagnostics["checkerboard_overlap"] > 0.95
    assert filtered.waffle_filter_cutoff == cutoff
    np.testing.assert_array_equal(filtered.actuator_grid_indices, grid)
    assert plain.waffle_filter_cutoff is None and plain.waffle_modes is None
    assert len({plain.config_hash, filtered.config_hash, narrow.config_hash}) == 3
    assert filtered.metadata["waffle_filter_cutoff"] == cutoff
    assert filtered.metadata["waffle_modes_count"] == 3
    assert not any(key.startswith("waffle") for key in plain.metadata)

    # Noise alone: the unfiltered solve puts most of its energy in the family;
    # the filter removes the family exactly and leaves the smooth part of the
    # band (tip, tilt) untouched.
    rng = np.random.default_rng(3)
    noise = rng.normal(size=dense.shape[0]) * 1e-3
    truth = 2e-7 * smooth[:, 1] - 1e-7 * smooth[:, 2]
    for b in (noise, dense @ truth + noise):
        x_plain = plain.reconstruct(_measurement(matrix, b)).delta_coordinates_opd_m
        estimate = filtered.reconstruct(_measurement(matrix, b))
        x_filtered = estimate.delta_coordinates_opd_m
        scale = np.abs(x_plain).max()
        np.testing.assert_allclose(x_filtered, x_plain - basis @ (basis.T @ x_plain), rtol=0.0, atol=1e-12 * scale)
        assert np.abs(basis.T @ x_filtered).max() <= 1e-12 * scale
        np.testing.assert_allclose(smooth.T @ x_filtered, smooth.T @ x_plain, rtol=0.0, atol=1e-12 * scale)
        assert estimate.coordinate_norm_m == pytest.approx(np.linalg.norm(x_filtered), rel=1e-12)
        np.testing.assert_allclose(estimate.reconstructed_signal, dense @ x_filtered, rtol=1e-12, atol=1e-15)
        assert filtered.telemetry[-1].solution_norm == pytest.approx(np.linalg.norm(x_filtered), rel=1e-12)
    x_noise = plain.reconstruct(_measurement(matrix, noise)).delta_coordinates_opd_m
    assert np.linalg.norm(basis.T @ x_noise) > 0.5 * np.linalg.norm(x_noise)

    # A guarded subset solve removes the family restricted to its solved columns.
    valid = np.ones(dense.shape[0], dtype=bool)
    valid[: dense.shape[0] // 4] = False
    b = dense @ truth + noise
    partial = _measurement(matrix, b, valid)
    subset = filtered.reconstruct_subset(partial, min_valid_fraction=0.5, min_actuator_coverage=0.5)
    reference = plain.reconstruct_subset(partial, min_valid_fraction=0.5, min_actuator_coverage=0.5)
    solved = np.flatnonzero(reference.delta_coordinates_opd_m != 0.0)
    assert 0 < solved.size < grid.shape[0]
    restricted, _ = np.linalg.qr(basis[solved])
    expected_subset = reference.delta_coordinates_opd_m.copy()
    expected_subset[solved] -= restricted @ (restricted.T @ expected_subset[solved])
    np.testing.assert_allclose(
        subset.delta_coordinates_opd_m, expected_subset, rtol=0.0, atol=1e-12 * np.abs(expected_subset).max()
    )
    assert np.count_nonzero(np.delete(subset.delta_coordinates_opd_m, solved)) == 0


def test_the_sparse_eigensolver_selects_the_same_waffle_family(monkeypatch):
    dense, grid = _pupil_fried(24)  # 404 lenslets, 468 actuators
    matrix = _matrix_from_dense(dense)
    dense_basis, dense_diagnostics = response_waffle_modes(matrix, grid, cutoff=0.1)
    monkeypatch.setattr(sparse_module, "_WAFFLE_DENSE_EIGEN_LIMIT", 100)
    sparse_basis, sparse_diagnostics = response_waffle_modes(matrix, grid, cutoff=0.1)
    assert dense_diagnostics["eigensolver"] == "dense_eigh"
    assert sparse_diagnostics["eigensolver"] == "sparse_shift_invert_eigsh"
    for key in ("count", "eigenpairs", "twin_subspace"):
        assert sparse_diagnostics[key] == dense_diagnostics[key]
    assert sparse_diagnostics["count"] == 3
    np.testing.assert_allclose(sparse_basis @ sparse_basis.T, dense_basis @ dense_basis.T, atol=1e-8)
    for key in ("smallest_selected_response", "largest_selected_response", "first_response_at_or_above_cutoff"):
        assert sparse_diagnostics[key] == pytest.approx(dense_diagnostics[key], rel=1e-8)
    with pytest.raises(SparseCalibrationError, match="selects no waffle-family mode"):
        response_waffle_modes(matrix, grid, cutoff=1e-3)


_GRID_2X2 = np.array([[0, 0], [0, 1], [1, 0], [1, 1]])


def test_the_local_waffle_operator_does_not_depend_on_the_size_of_the_grid_indices():
    _, grid = _pupil_fried(24)
    shuffled = grid[np.random.default_rng(5).permutation(grid.shape[0])]
    # Reference: a dense lookup table over the bounding box of the indices.
    lookup = np.full(tuple(shuffled.max(axis=0) + 2), -1)
    lookup[shuffled[:, 0], shuffled[:, 1]] = np.arange(shuffled.shape[0])
    r, c = shuffled.T
    corners = np.column_stack([lookup[r, c], lookup[r + 1, c], lookup[r, c + 1], lookup[r + 1, c + 1]])
    corners = corners[np.all(corners >= 0, axis=1)]
    expected = np.zeros((corners.shape[0], shuffled.shape[0]))
    for k, row in enumerate(corners):
        expected[k, row] = (1.0, -1.0, -1.0, 1.0)
    np.testing.assert_array_equal(local_waffle_operator(shuffled).toarray(), expected)
    # One cell far from the origin needs no table of that size.
    far = local_waffle_operator(_GRID_2X2 + 100_000)
    np.testing.assert_array_equal(far.toarray(), local_waffle_operator(_GRID_2X2).toarray())


def test_the_dense_fallback_of_the_waffle_eigensolver_is_bounded(monkeypatch):
    dense, grid = _pupil_fried(24)  # 468 actuators
    matrix = _matrix_from_dense(dense)
    monkeypatch.setattr(sparse_module, "_WAFFLE_DENSE_EIGEN_LIMIT", 100)
    # At cutoff 1 the band holds more than a quarter of the coordinates, so
    # the sparse search cannot close it and falls back to the dense solver.
    _, diagnostics = response_waffle_modes(matrix, grid, cutoff=1.0)
    assert diagnostics["eigensolver"] == "dense_eigh"
    assert diagnostics["eigenpairs"] > grid.shape[0] // 4
    monkeypatch.setattr(sparse_module, "DEFAULT_DENSE_RESPONSE_LIMIT_BYTES", 1024)
    with pytest.raises(SparseCalibrationError, match="dense fallback would need"):
        response_waffle_modes(matrix, grid, cutoff=1.0)


def test_the_telemetry_separates_the_lsmr_solve_from_the_delivered_command():
    size = 6
    grid = np.column_stack(np.unravel_index(np.arange(size * size), (size, size)))
    waffle = np.where(grid.sum(axis=1) % 2 == 0, 1.0, -1.0) / size
    dense = np.eye(size * size) - 0.9 * np.outer(waffle, waffle)
    matrix = _matrix_from_dense(dense)
    keywords = dict(damping_relative=1e-3, atol=1e-12, btol=1e-12, max_iterations=100, min_valid_fraction=0.5)
    plain = SparseLsmrReconstructor(matrix, **keywords)
    filtered = SparseLsmrReconstructor(matrix, waffle_filter_cutoff=0.35, actuator_grid_indices=grid, **keywords)
    assert filtered.waffle_modes.shape[1] == 1
    target = dense @ waffle
    for reconstructor in (plain, filtered):
        x = reconstructor.reconstruct(_measurement(matrix, target)).delta_coordinates_opd_m
        telemetry = reconstructor.telemetry[-1]
        residual = target - dense @ x
        damp = reconstructor.damping_absolute
        direct = np.linalg.norm(dense.T @ residual - damp * damp * x)
        assert telemetry.residual_norm == pytest.approx(np.linalg.norm(residual), rel=1e-12)
        assert telemetry.solution_norm == pytest.approx(np.linalg.norm(x), rel=1e-12)
        # LSMR's own solve converged before any projection.
        assert telemetry.lsmr_normal_residual_norm < 1e-8
        if reconstructor is plain:
            assert telemetry.normal_residual_norm == telemetry.lsmr_normal_residual_norm
        else:
            # The delivered command removed the weak checkerboard the data asked for.
            assert np.linalg.norm(x) < 1e-12
            assert telemetry.normal_residual_norm == pytest.approx(direct, rel=1e-9)
            assert telemetry.normal_residual_norm == pytest.approx(0.01, rel=1e-3)


def test_earlier_ten_field_telemetry_records_still_construct():
    fields = (0, 36, 3, 2, "least-squares solution within atol", True, True, 0.2, 0.01, 0.3)
    names = (
        "solve_index", "usable_rows", "iterations", "istop", "istop_meaning",
        "converged", "accepted", "residual_norm", "normal_residual_norm", "solution_norm",
    )
    by_position = SolverTelemetry(*fields)
    by_mapping = SolverTelemetry(**dict(zip(names, fields)))
    # The earlier normal residual was LSMR's estimate, so it fills the new field.
    assert by_position == by_mapping
    assert by_position.lsmr_normal_residual_norm == 0.01
    current = SolverTelemetry(*fields, 1e-9)
    assert current.lsmr_normal_residual_norm == 1e-9
    assert SolverTelemetry(**asdict(current)) == current


def test_a_solve_without_a_finite_command_reports_no_delivered_normal_residual(monkeypatch):
    size = 6
    grid = np.column_stack(np.unravel_index(np.arange(size * size), (size, size)))
    waffle = np.where(grid.sum(axis=1) % 2 == 0, 1.0, -1.0) / size
    dense = np.eye(size * size) - 0.9 * np.outer(waffle, waffle)
    matrix = _matrix_from_dense(dense)
    keywords = dict(damping_relative=1e-3, atol=1e-12, btol=1e-12, max_iterations=100, min_valid_fraction=0.5)
    plain = SparseLsmrReconstructor(matrix, **keywords)
    filtered = SparseLsmrReconstructor(matrix, waffle_filter_cutoff=0.35, actuator_grid_indices=grid, **keywords)
    # A zero target has the zero command as its optimum, filtered or not.
    assert filtered.reconstruct(_measurement(matrix, np.zeros(size * size))) is not None
    assert filtered.telemetry[-1].normal_residual_norm == 0.0
    nonfinite = (np.full(size * size, np.nan), 2, 2, 0.1, 0.003, 1.0, 1.0, np.nan)
    monkeypatch.setattr(sparse_module, "lsmr", lambda *args, **kwargs: nonfinite)
    for reconstructor in (plain, filtered):
        assert reconstructor.reconstruct(_measurement(matrix, np.zeros(size * size))) is None
        telemetry = reconstructor.telemetry[-1]
        assert not telemetry.accepted
        for value in (telemetry.residual_norm, telemetry.normal_residual_norm, telemetry.solution_norm):
            assert math.isnan(value)
        assert telemetry.lsmr_normal_residual_norm == 0.003


def _diagonal_gram(values):
    return sp.diags(np.asarray(values, dtype=float), format="csc")


def test_the_sparse_eigen_search_tries_its_capped_count(monkeypatch):
    requested = []
    eigsh = sparse_module.eigsh

    def recording_eigsh(matrix, k, **kwargs):
        requested.append(k)
        return eigsh(matrix, k=k, **kwargs)

    monkeypatch.setattr(sparse_module, "eigsh", recording_eigsh)
    monkeypatch.setattr(sparse_module, "_WAFFLE_DENSE_EIGEN_LIMIT", 12)
    monkeypatch.setattr(sparse_module, "_WAFFLE_INITIAL_EIGENPAIRS", 4)
    monkeypatch.setattr(sparse_module, "DEFAULT_DENSE_RESPONSE_LIMIT_BYTES", 1000)
    # 44 coordinates cap the search at 11, which doubling from 4 skips.
    nine_below = np.r_[np.linspace(0.01, 0.09, 9), np.linspace(0.4, 1.0, 35)]
    values, vectors, method = sparse_module._lowest_eigenpairs(_diagonal_gram(nine_below), 0.25)
    assert requested == [4, 8, 11]
    assert method == "sparse_shift_invert_eigsh"
    assert np.count_nonzero(values < 0.25) == 9 and values[-1] >= 0.25
    assert vectors.shape == (44, 11)
    # A band of at least the capped count is refused only after that count.
    requested.clear()
    twelve_below = np.r_[np.linspace(0.01, 0.12, 12), np.linspace(0.4, 1.0, 32)]
    with pytest.raises(SparseCalibrationError, match="holds at least 11 eigenpairs"):
        sparse_module._lowest_eigenpairs(_diagonal_gram(twelve_below), 0.25)
    assert requested == [4, 8, 11]


def test_the_42m_sized_eigen_search_requests_the_same_counts(monkeypatch):
    # 5328 coordinates with a band of 632, the size of the 42 m family band;
    # the eigensolver is replaced by the exact answer of a diagonal matrix.
    spectrum = np.r_[np.linspace(1e-4, 0.27, 632), np.linspace(0.3, 2.0, 5328 - 632)]
    requested = []

    def exact_eigsh(matrix, k, **kwargs):
        requested.append(k)
        return spectrum[:k], np.eye(spectrum.size)[:, :k]

    monkeypatch.setattr(sparse_module, "eigsh", exact_eigsh)
    values, _, method = sparse_module._lowest_eigenpairs(_diagonal_gram(spectrum), 0.2756)
    assert requested == [64, 128, 256, 512, 1024]
    assert method == "sparse_shift_invert_eigsh" and values.size == 1024


@pytest.mark.parametrize(
    ("keywords", "message"),
    (
        (dict(waffle_filter_cutoff=0.3), "together or not at all"),
        (dict(actuator_grid_indices=_GRID_2X2), "together or not at all"),
        (dict(waffle_filter_cutoff=0.0, actuator_grid_indices=_GRID_2X2), "in \\(0, 1\\]"),
        (dict(waffle_filter_cutoff=1.5, actuator_grid_indices=_GRID_2X2), "in \\(0, 1\\]"),
        (dict(waffle_filter_cutoff=True, actuator_grid_indices=_GRID_2X2), "real number"),
        (dict(waffle_filter_cutoff=0.3, actuator_grid_indices=_GRID_2X2[:3]), "one \\(row, column\\) pair per coordinate"),
        (dict(waffle_filter_cutoff=0.3, actuator_grid_indices=_GRID_2X2 + 0.5), "integers"),
        (dict(waffle_filter_cutoff=0.3, actuator_grid_indices=_GRID_2X2[[0, 0, 1, 2]]), "unique"),
        (dict(waffle_filter_cutoff=0.3, actuator_grid_indices=_GRID_2X2), "selects no waffle-family mode"),
    ),
)
def test_waffle_filter_settings_are_validated(keywords, message):
    matrix = _matrix_from_dense(np.eye(4) + 0.1)
    with pytest.raises(SparseCalibrationError, match=message):
        SparseLsmrReconstructor(
            matrix, damping_relative=1e-3, atol=1e-10, btol=1e-10,
            max_iterations=100, min_valid_fraction=0.5, **keywords,
        )


def test_the_profile_cutoff_reaches_the_sparse_reconstructor():
    dense, grid = _pupil_fried(24)
    matrix = _matrix_from_dense(dense, coordinate_ids=actuator_ids_from_grid_indices(grid))
    plain = _build_reconstructor(load_system_profile(PROFILE, 1), matrix)
    assert plain.waffle_filter_cutoff is None and plain.waffle_modes is None
    filtered = _build_reconstructor(load_system_profile(PROFILE, 2), matrix)
    expected, diagnostics = response_waffle_modes(matrix, grid, cutoff=0.35)
    assert filtered.waffle_filter_cutoff == 0.35
    np.testing.assert_array_equal(filtered.actuator_grid_indices, grid)
    np.testing.assert_array_equal(filtered.waffle_modes, expected)
    assert dict(filtered.waffle_modes_diagnostics) == diagnostics


def test_the_42m_version_2_adds_only_the_waffle_filter() -> None:
    """@2 of the 42 m profile is @1 under schema v8 plus the reconstructor waffle-family filter."""

    assert PROFILE_SCHEMA_VERSION == 8
    version_1 = load_system_profile(PROFILE, 1)
    version_2 = load_system_profile(PROFILE, 2)
    assert (version_1.config_hash, version_2.config_hash) == (V1_CONFIG_HASH, V2_CONFIG_HASH)
    assert (version_1.record_schema_version, version_2.record_schema_version) == (7, 8)
    assert version_1.reconstructor.waffle_filter_cutoff is None
    assert version_2.reconstructor.waffle_filter_cutoff == 0.35
    assert version_2.reconstructor.alpha == version_1.reconstructor.alpha == 0.001
    restored = replace(
        version_2,
        reconstructor=replace(version_2.reconstructor, waffle_filter_cutoff=None),
        profile=version_1.profile,
        record_schema_version=7,
    )
    assert restored == version_1 and restored.config_hash == version_1.config_hash
    changed = {
        key
        for key, value in version_2.component_config_hashes.items()
        if version_1.component_config_hashes[key] != value
    }
    assert changed == {"profile", "reconstructor"}
    record = system_config_to_mapping(version_2)
    assert system_config_from_mapping(record) == version_2
    assert record["schema_version"] == 8
    assert record["config"]["reconstructor"]["waffle_filter_cutoff"] == 0.35
    assert "waffle_filter_cutoff" not in system_config_to_mapping(version_1)["config"]["reconstructor"]
    # A schema-7 record cannot carry the field, and a schema-8 record may omit it.
    older = copy.deepcopy(record)
    older["schema_version"] = 7
    with pytest.raises(SystemConfigError, match="fields mismatch"):
        system_config_from_mapping(older)
    with pytest.raises(SystemConfigError, match="cannot express reconstructor.waffle_filter_cutoff"):
        replace(version_2, record_schema_version=7)
    omitted = copy.deepcopy(record)
    del omitted["config"]["reconstructor"]["waffle_filter_cutoff"]
    parsed = system_config_from_mapping(omitted)
    assert parsed.reconstructor.waffle_filter_cutoff is None
    assert parsed.component_config_hashes["reconstructor"] == version_1.component_config_hashes["reconstructor"]
    # The filter belongs to the sparse LSMR reconstructor alone; its cutoff is in (0, 1].
    with pytest.raises(SystemConfigError, match="waffle_filter_cutoff is valid only"):
        replace(version_2, reconstructor=replace(version_2.reconstructor, kind="tikhonov", waffle_filter_cutoff=0.3))
    with pytest.raises(SystemConfigError, match="positive"):
        replace(version_2, reconstructor=replace(version_2.reconstructor, waffle_filter_cutoff=0.0))
    with pytest.raises(SystemConfigError, match="at most 1"):
        replace(version_2, reconstructor=replace(version_2.reconstructor, waffle_filter_cutoff=1.5))
    other = replace(version_2, reconstructor=replace(version_2.reconstructor, waffle_filter_cutoff=0.2))
    assert other.config_hash != version_2.config_hash


def test_the_version_3_ledger_adds_the_42m_profile_and_its_filter_row() -> None:
    sources = load_source_ledger(DETECTOR_SOURCES)
    v2 = load_assumption_ledger(DETECTOR_LEDGER_V2, source_ledger=sources)
    v3 = load_assumption_ledger(DETECTOR_LEDGER_V3, source_ledger=sources)
    profile_id = f"{PROFILE}@2"
    assert v3["profiles"] == [*v2["profiles"], profile_id]
    assert v3["supersedes"] == DETECTOR_LEDGER_V2
    assert v3["revisions"][:-1] == v2["revisions"] and v3["revisions"][-1]["row"] == "B22"
    v2_rows = {row["id"]: row for row in v2["rows"]}
    v3_rows = {row["id"]: row for row in v3["rows"]}
    assert set(v3_rows) == set(v2_rows) | {"B22"}
    for identifier, row in v2_rows.items():
        # Every version-2 row keeps its text and values; rows that cover every
        # profile gain an entry for the new one.
        other = dict(v3_rows[identifier])
        values = dict(other.pop("values_by_profile", {}))
        values.pop(profile_id, None)
        assert other == {key: value for key, value in row.items() if key != "values_by_profile"}, identifier
        assert values == row.get("values_by_profile", {}), identifier
    assert v3_rows["B22"]["values_by_profile"] == {profile_id: {"reconstructor.waffle_filter_cutoff": 0.35}}
    configs = {
        identifier: load_system_profile(identifier.split("@")[0], int(identifier.split("@")[1]))
        for identifier in v3["profiles"]
    }
    coverage = validate_benchmark_profiles(v3, configs)
    assert "B22" in coverage[profile_id]
    assert not any("B22" in rows for identifier, rows in coverage.items() if identifier != profile_id)
    # Two published texts keep their bytes and are corrected by errata here:
    # the @2 rationale, from whose packaged identity every @2 run started, and
    # the damping row A07b of the frozen ESO 42 m ledger.
    manifest = {entry["logical_name"]: entry["sha256"] for entry in load_resource_manifest()["resources"]}
    errata = {entry["resource"]: entry for entry in v3["errata"]}
    profile_resource = "synthetic_presets/det_ccd_42m_r3band_derived.v2.json"
    assert set(errata) == {profile_resource, ASSUMPTION_LEDGER_RESOURCE}
    for resource, entry in errata.items():
        assert entry["sha256"] == manifest[resource] and entry["corrections"], resource
    assert errata[profile_resource]["config_hash"] == V2_CONFIG_HASH
    packaged = load_system_profile(PROFILE, 2)
    assert packaged.config_hash == V2_CONFIG_HASH
    # Each run's identity follows from the packaged profile and its plan's two overrides.
    run = replace(packaged, controller=replace(packaged.controller, n_steps=500))
    expected = {"seed 1, 500 frames": run.config_hash}
    for seed in (104, 105, 106):
        expected[f"seed {seed}, 500 frames"] = replace(run, random=replace(run.random, root_seed=seed)).config_hash
    assert errata[profile_resource]["run_config_hashes"] == expected
    eso = {row["id"]: row for row in load_assumption_ledger()["rows"]}
    assert errata[ASSUMPTION_LEDGER_RESOURCE]["row"] == "A07b"
    assert "suppresses unseen (piston, waffle)" in eso["A07b"]["rationale"]
