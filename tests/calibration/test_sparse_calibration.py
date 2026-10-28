"""ESO-06: grouped local calibration, sparse response, and LSMR solver.

Oracles: the dense per-actuator :func:`calibrate_interaction_matrix` on the
same sensor and DM, and closed-form Tikhonov solutions from a NumPy SVD of
independently assembled small matrices.
"""

from __future__ import annotations

import numpy as np
import pytest

from shwfs_ao.backends.native.shwfs import NativeShackHartmannOptics
from shwfs_ao.backends.native.shwfs_batched import BatchedNativeShackHartmannOptics
from shwfs_ao.calibration import DmActuatorProbeBasis, calibrate_interaction_matrix
from shwfs_ao.calibration.sparse import (
    GROUPED_LOCAL_STRATEGY,
    LocalDmProbeBasis,
    SparseCalibrationError,
    SparseInteractionMatrix,
    SparseLsmrReconstructor,
    calibrate_sparse_interaction_matrix,
    probe_groups,
)
from shwfs_ao.core.provenance import Provenance
from shwfs_ao.core.random import NamedRandomStreams
from shwfs_ao.core.types import MeasurementVector
from shwfs_ao.detector import CentroidConfig, CentroidValidityConfig, DetectorConfig
from shwfs_ao.dm import DMConfig, build_native_deformable_mirror
from shwfs_ao.wfs.shack_hartmann.compact_geometry import (
    build_compact_shack_hartmann_geometry,
)
from shwfs_ao.wfs.shack_hartmann.geometry import build_shack_hartmann_geometry
from shwfs_ao.wfs.shack_hartmann.measurement import DetectorShackHartmannSensor

WAVELENGTH = 7.0e-7
SEED = 5


def _system(*, compact=True, n=60, lenslets=5, diameter=2.5, dead=()):
    keywords = dict(
        telescope_diameter_m=diameter,
        pupil_shape=(n, n),
        n_lenslets_across=lenslets,
        min_fill_fraction=0.5,
        central_obstruction_ratio=0.28,
    )
    if compact:
        geometry = build_compact_shack_hartmann_geometry(**keywords)
        optics = BatchedNativeShackHartmannOptics(
            geometry, WAVELENGTH, pad_factor=2, detector_window_px=24
        )
    else:
        geometry = build_shack_hartmann_geometry(**keywords)
        optics = NativeShackHartmannOptics(
            geometry, WAVELENGTH, pad_factor=2, detector_window_px=24
        )
    sensor = DetectorShackHartmannSensor.calibrate(
        geometry,
        optics,
        DetectorConfig(
            photons_per_subap_frame=1.0e5,
            read_noise_e=0.0,
            qe=1.0,
            prnu_rms=0.0,
            exposure_s=0.002,
            prnu_mode="persistent",
            source_class="synthetic_assumed",
            source_note="ESO-06 fixture",
        ),
        wfs_wavelength_m=WAVELENGTH,
        random_streams=NamedRandomStreams(SEED).scoped("wfs"),
        centroid_config=CentroidConfig(),
        validity_config=CentroidValidityConfig(
            min_flux_e=100.0,
            min_peak_snr=3.0,
            max_centroid_sigma_px=0.5,
            max_window_clipping_fraction=0.15,
        ),
    )
    dm = build_native_deformable_mirror(
        geometry.x_m,
        geometry.y_m,
        geometry.pupil_mask,
        DMConfig(
            telescope_diameter_m=diameter,
            n_actuators_across=lenslets + 1,
            influence_model="linear_spline",
            coupling_width_pitch=1.0,
            stroke_limit_nm=5000.0,
            actuator_margin_fraction=2.0 * np.sqrt(2.0) / lenslets,
            dead_actuator_indices=dead,
        ),
    )
    return geometry, sensor, dm


class _CountingSensor:
    def __init__(self, sensor):
        self._sensor = sensor
        self.calls = 0

    def __getattr__(self, name):
        return getattr(self._sensor, name)

    def measure(self, residual_opd_m, *, random_streams, include_noise):
        self.calls += 1
        return self._sensor.measure(
            residual_opd_m, random_streams=random_streams, include_noise=include_noise
        )


@pytest.fixture(scope="module")
def calibrated():
    geometry, sensor, dm = _system(dead=(9,))
    basis = LocalDmProbeBasis(dm, lenslet_label_map=geometry.lenslet_label_map())
    counting = _CountingSensor(sensor)
    sparse = calibrate_sparse_interaction_matrix(
        basis, counting, 2.0e-8, random_streams=NamedRandomStreams(SEED)
    )
    return geometry, sensor, dm, basis, sparse, counting.calls


def test_grouped_calibration_equals_dense_per_actuator_differences(calibrated):
    _, sensor, dm, basis, sparse, calls = calibrated
    dense = calibrate_interaction_matrix(
        DmActuatorProbeBasis(dm, coordinate_ids=basis.coordinate_ids),
        sensor,
        2.0e-8,
        random_streams=NamedRandomStreams(SEED),
    )
    np.testing.assert_array_equal(sparse.row_valid, dense.row_valid)
    assert sparse.row_ids == dense.row_ids
    assert sparse.coordinate_ids == dense.coordinate_ids
    scale = np.nanmax(np.abs(dense.matrix))
    np.testing.assert_allclose(sparse.to_dense(), dense.matrix, rtol=0.0, atol=1e-12 * scale)
    assert sparse.sensor_response_hash == dense.sensor_response_hash
    assert sparse.geometry_hash == dense.geometry_hash
    assert sparse.dm_hash == dense.dm_hash
    groups = sparse.probe_group_count
    assert calls == sparse.sensor_call_count == 2 * groups + 1
    assert groups <= 9 < basis.size
    assert sparse.strategy == GROUPED_LOCAL_STRATEGY


def test_every_eligible_actuator_participates_and_exclusions_are_explained(calibrated):
    _, _, dm, basis, sparse, _ = calibrated
    excluded = dict(sparse.exclusions)
    assert set(excluded) | set(sparse.coordinate_ids) == set(dm.actuator_ids)
    assert not set(excluded) & set(sparse.coordinate_ids)
    assert excluded[dm.actuator_ids[9]] == "dead_actuator"
    for identifier in dm.geometric_exclusion_ids:
        assert excluded[identifier] == "zero_illuminated_support"
    assert set(excluded.values()) <= {
        "dead_actuator",
        "zero_illuminated_support",
        "no_retained_lenslet_support",
    }
    assert np.all(sparse.column_norms > 0.0)


def test_probe_groups_have_disjoint_lenslets_and_cover_every_coordinate(calibrated):
    _, _, _, basis, _, _ = calibrated
    groups = probe_groups(basis.affected_lenslets)
    seen = np.concatenate(groups)
    assert sorted(seen.tolist()) == list(range(basis.size))
    for group in groups:
        used: set[int] = set()
        for coordinate in group:
            lenslets = set(basis.affected_lenslets[int(coordinate)].tolist())
            assert used.isdisjoint(lenslets)
            used |= lenslets


def test_response_forward_and_adjoint_pass_the_dot_product_test(calibrated):
    _, _, _, _, sparse, _ = calibrated
    rng = np.random.default_rng(7)
    for _ in range(3):
        x = rng.normal(size=sparse.shape[1])
        y = rng.normal(size=sparse.shape[0])
        y[~sparse.row_valid] = np.nan
        left = float(np.nansum(sparse.forward(x) * y))
        right = float(x @ sparse.adjoint(y))
        assert abs(left - right) <= 1e-10 * max(abs(left), abs(right))


def test_probe_amplitude_linearity(calibrated):
    geometry, sensor, _, basis, reference, _ = calibrated
    amplitudes = (5e-9, 1e-8, 2e-8, 4e-8)
    matrices = [
        calibrate_sparse_interaction_matrix(
            basis, sensor, amplitude, random_streams=NamedRandomStreams(SEED)
        ).to_dense()
        for amplitude in amplitudes
    ]
    valid = reference.row_valid
    differences = [
        np.linalg.norm(a[valid] - matrices[0][valid]) / np.linalg.norm(matrices[0][valid])
        for a in matrices[1:]
    ]
    # Central differences: the error grows with amplitude (third-order term),
    # and stays far below the 1 % level used to call a probe "linear".
    assert differences[0] < differences[1] < differences[2] < 1e-3


def test_invalid_calibrations_fail_before_any_sensor_call(calibrated):
    geometry, sensor, dm, basis, _, _ = calibrated
    counting = _CountingSensor(sensor)
    with pytest.raises(SparseCalibrationError, match="stroke"):
        calibrate_sparse_interaction_matrix(
            basis, counting, 1.0, random_streams=NamedRandomStreams(SEED)
        )
    with pytest.raises(SparseCalibrationError, match="include_noise=False"):
        calibrate_sparse_interaction_matrix(
            basis, counting, 2e-8, random_streams=NamedRandomStreams(SEED),
            include_noise=True, repeats=4,
        )
    unlabelled = LocalDmProbeBasis(dm)
    with pytest.raises(SparseCalibrationError, match="label map"):
        calibrate_sparse_interaction_matrix(
            unlabelled, counting, 2e-8, random_streams=NamedRandomStreams(SEED)
        )
    shifted = geometry.lenslet_label_map().copy()
    shifted[shifted >= 0] = (shifted[shifted >= 0] + 1) % geometry.n_subapertures
    mislabelled = LocalDmProbeBasis(dm, lenslet_label_map=shifted)
    with pytest.raises(SparseCalibrationError, match="coupling"):
        calibrate_sparse_interaction_matrix(
            mislabelled, counting, 2e-8, random_streams=NamedRandomStreams(SEED)
        )
    assert counting.calls == 0
    # Optics without a declared locality are refused, also before measuring.
    dense_geometry, dense_sensor, _ = _system(compact=False)
    dense_counting = _CountingSensor(dense_sensor)
    with pytest.raises(SparseCalibrationError, match="measurement_locality"):
        calibrate_sparse_interaction_matrix(
            basis, dense_counting, 2e-8, random_streams=NamedRandomStreams(SEED)
        )
    assert dense_counting.calls == 0


def test_record_round_trip_preserves_identity(calibrated):
    _, _, _, _, sparse, _ = calibrated
    restored = SparseInteractionMatrix.from_record(sparse.to_record())
    assert restored.calibration_hash == sparse.calibration_hash
    np.testing.assert_array_equal(restored.to_dense(), sparse.to_dense())
    record = sparse.to_record()
    record["data"] = list(record["data"])
    record["data"][0] *= 1.0 + 1e-9
    with pytest.raises(SparseCalibrationError, match="calibration_hash"):
        SparseInteractionMatrix.from_record(record)


def _matrix_from_dense(dense: np.ndarray, row_valid: np.ndarray | None = None):
    rows, columns = dense.shape
    valid = np.ones(rows, dtype=bool) if row_valid is None else row_valid
    values = np.where(valid[:, None], dense, 0.0)
    import scipy.sparse as sp

    csr = sp.csr_matrix(values)
    return SparseInteractionMatrix.create(
        data=csr.data,
        indices=csr.indices,
        indptr=csr.indptr,
        row_valid=valid,
        row_ids=tuple(f"r{i}" for i in range(rows)),
        coordinate_ids=tuple(f"c{j}" for j in range(columns)),
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


def test_the_public_csr_is_a_copy_that_cannot_change_the_response():
    dense = np.array([[1.0, 0.0], [0.0, 4.0], [2.0, 1.0]])
    matrix = _matrix_from_dense(dense)
    reconstructor = SparseLsmrReconstructor(
        matrix, damping_relative=1e-3, atol=1e-12, btol=1e-12,
        max_iterations=1000, min_valid_fraction=0.5,
    )
    x = np.array([1.0, 1.0])
    b = np.array([1.0, 4.0, 3.0])
    forward, adjoint = matrix.forward(x), matrix.adjoint(b)
    solution = reconstructor.reconstruct(_measurement(matrix, b)).delta_coordinates_opd_m
    identity = matrix.calibration_hash

    public = matrix.csr()
    public.data = public.data * 2.0  # replace the values
    public.indices = public.indices[::-1].copy()  # and scramble the layout

    np.testing.assert_array_equal(matrix.forward(x), forward)
    np.testing.assert_array_equal(matrix.adjoint(b), adjoint)
    np.testing.assert_array_equal(matrix.to_dense(), dense)
    again = reconstructor.reconstruct(_measurement(matrix, b)).delta_coordinates_opd_m
    np.testing.assert_array_equal(again, solution)
    assert matrix.calibration_hash == identity
    reloaded = SparseInteractionMatrix.from_record(matrix.to_record())
    np.testing.assert_array_equal(reloaded.forward(x), forward)
    assert matrix.csr() is not matrix.csr()


def _tikhonov(dense, b, damp):
    u, s, vt = np.linalg.svd(dense, full_matrices=False)
    return vt.T @ ((s / (s * s + damp * damp)) * (u.T @ b))


def _objective(dense, x, b, damp):
    return float(np.sum((dense @ x - b) ** 2) + damp * damp * np.sum(x * x))


@pytest.mark.parametrize("relative_damping", (1e-3, 1e-2, 1e-1))
def test_lsmr_matches_the_dense_tikhonov_solution(relative_damping):
    rng = np.random.default_rng(11)
    dense = rng.normal(size=(60, 24)) * (rng.random(size=(60, 24)) < 0.3)
    dense[:, 0] += 0.5  # keep every column nonzero
    matrix = _matrix_from_dense(dense)
    reconstructor = SparseLsmrReconstructor(
        matrix, damping_relative=relative_damping, atol=1e-14, btol=1e-14,
        max_iterations=10_000, min_valid_fraction=0.5,
    )
    damp = reconstructor.damping_absolute
    norms = np.linalg.norm(dense, axis=0)
    assert damp == pytest.approx(relative_damping * np.sqrt(np.mean(norms**2)), rel=1e-12)
    b = rng.normal(size=60)
    estimate = reconstructor.reconstruct(_measurement(matrix, b))
    expected = _tikhonov(dense, b, damp)
    x = estimate.delta_coordinates_opd_m
    assert np.linalg.norm(x - expected) / np.linalg.norm(expected) <= 1e-5
    objective, reference = _objective(dense, x, b, damp), _objective(dense, expected, b, damp)
    assert abs(objective - reference) / reference <= 1e-6
    np.testing.assert_allclose(estimate.reconstructed_signal, dense @ x, rtol=1e-12, atol=1e-12)
    assert estimate.kept_modes is None and estimate.singular_values.size == 0
    assert reconstructor.telemetry[-1].converged


def test_rank_deficiency_and_piston_get_the_minimum_norm_damped_solution():
    # Slopes of a 1-D chain are differences: a piston command is invisible.
    columns = 12
    dense = np.zeros((columns - 1, columns))
    for row in range(columns - 1):
        dense[row, row], dense[row, row + 1] = -1.0, 1.0
    matrix = _matrix_from_dense(dense)
    reconstructor = SparseLsmrReconstructor(
        matrix, damping_relative=1e-4, atol=1e-14, btol=1e-14,
        max_iterations=10_000, min_valid_fraction=0.5,
    )
    truth = np.linspace(-1.0, 1.0, columns) ** 2 + 7.0  # includes a large piston
    estimate = reconstructor.reconstruct(_measurement(matrix, dense @ truth))
    x = estimate.delta_coordinates_opd_m
    assert abs(np.mean(x)) < 1e-6 * np.max(np.abs(x))
    np.testing.assert_allclose(x, truth - truth.mean(), rtol=0.0, atol=1e-5)


def test_rejected_rows_all_invalid_frames_and_coverage_policy():
    rng = np.random.default_rng(3)
    dense = rng.normal(size=(30, 8))
    calibration_valid = np.ones(30, dtype=bool)
    calibration_valid[[4, 5]] = False
    matrix = _matrix_from_dense(dense, calibration_valid)
    reconstructor = SparseLsmrReconstructor(
        matrix, damping_relative=1e-6, atol=1e-14, btol=1e-14,
        max_iterations=10_000, min_valid_fraction=0.6,
    )
    b = rng.normal(size=30)
    runtime_valid = np.ones(30, dtype=bool)
    runtime_valid[[0, 7, 9, 11]] = False
    b_with_nan = b.copy()
    b_with_nan[11] = np.nan  # an invalid row may carry a non-finite value
    estimate = reconstructor.reconstruct(_measurement(matrix, b_with_nan, runtime_valid))
    usable = calibration_valid & runtime_valid & np.isfinite(b_with_nan)
    np.testing.assert_array_equal(estimate.usable_rows, usable)
    expected = _tikhonov(dense[usable], b[usable], reconstructor.damping_absolute)
    np.testing.assert_allclose(estimate.delta_coordinates_opd_m, expected, rtol=1e-6, atol=1e-9)
    assert np.all(np.isnan(estimate.residual_signal[~usable]))
    assert reconstructor.reconstruct(_measurement(matrix, b, np.zeros(30, dtype=bool))) is None
    sparse_coverage = np.zeros(30, dtype=bool)
    sparse_coverage[:10] = True
    assert reconstructor.reconstruct(_measurement(matrix, b, sparse_coverage)) is None


def test_nonconvergence_is_rejected_or_explicitly_accepted():
    rng = np.random.default_rng(4)
    dense = rng.normal(size=(40, 20))
    matrix = _matrix_from_dense(dense)
    b = rng.normal(size=40)
    strict = SparseLsmrReconstructor(
        matrix, damping_relative=1e-6, atol=1e-15, btol=1e-15,
        max_iterations=2, min_valid_fraction=0.5,
    )
    assert strict.reconstruct(_measurement(matrix, b)) is None
    record = strict.telemetry[-1]
    assert record.istop == 7 and not record.converged and not record.accepted
    assert strict.statistics["rejected"] == 1
    lenient = SparseLsmrReconstructor(
        matrix, damping_relative=1e-6, atol=1e-15, btol=1e-15,
        max_iterations=2, min_valid_fraction=0.5, nonconverged_policy="accept",
    )
    assert lenient.reconstruct(_measurement(matrix, b)) is not None
    assert lenient.telemetry[-1].accepted and not lenient.telemetry[-1].converged
    assert strict.config_hash != lenient.config_hash


def test_solver_settings_and_measurement_layout_are_validated():
    matrix = _matrix_from_dense(np.eye(4) + 0.1)
    for keywords in (
        dict(damping_relative=-1.0),
        dict(atol=0.0),
        dict(max_iterations=0),
        dict(min_valid_fraction=1.5),
        dict(nonconverged_policy="ignore"),
    ):
        settings = dict(
            damping_relative=1e-3, atol=1e-8, btol=1e-8, max_iterations=10,
            min_valid_fraction=0.5,
        )
        settings.update(keywords)
        with pytest.raises(SparseCalibrationError):
            SparseLsmrReconstructor(matrix, **settings)
    reconstructor = SparseLsmrReconstructor(
        matrix, damping_relative=1e-3, atol=1e-8, btol=1e-8, max_iterations=10,
        min_valid_fraction=0.5,
    )
    wrong = MeasurementVector(np.zeros(4), np.ones(4, bool), ("a", "b", "c", "d"), "pixel")
    with pytest.raises(SparseCalibrationError, match="row_ids"):
        reconstructor.reconstruct(wrong)


def test_a_sensor_that_breaks_its_declared_locality_is_caught(calibrated):
    from shwfs_ao.core.types import WfsMeasurement

    _, sensor, _, basis, _, _ = calibrated

    class _Leaky(_CountingSensor):
        """Declares local optics but couples every row to the mean OPD."""

        def measure(self, residual_opd_m, *, random_streams, include_noise):
            measurement = super().measure(
                residual_opd_m, random_streams=random_streams, include_noise=include_noise
            )
            leak = 1e3 * float(np.nanmean(residual_opd_m))
            vector = measurement.vector
            values = np.where(vector.valid_rows, vector.values + leak, vector.values)
            return WfsMeasurement(
                vector=MeasurementVector(
                    values, vector.valid_rows, vector.row_ids, vector.measurement_unit
                ),
                valid_subapertures=measurement.valid_subapertures,
            )

    with pytest.raises(SparseCalibrationError, match="outside its declared lenslet support"):
        calibrate_sparse_interaction_matrix(
            basis, _Leaky(sensor), 2e-8, random_streams=NamedRandomStreams(SEED)
        )


def test_subset_fallback_solves_below_the_primary_threshold_and_guards_actuators():
    # Recovery fallback (controller.recovery): reconstruct_subset is the same
    # Tikhonov solve under a lower threshold; the coverage guard solves only for
    # actuators the usable rows still see, and holds the rest at zero.
    rng = np.random.default_rng(8)
    dense = np.zeros((24, 6))
    for column in range(6):
        dense[4 * column : 4 * column + 4, column] = rng.normal(size=4) + 2.0
    dense[:, 5] += 0.1 * rng.normal(size=24)  # one actuator seen weakly everywhere
    matrix = _matrix_from_dense(dense)
    reconstructor = SparseLsmrReconstructor(
        matrix, damping_relative=1e-6, atol=1e-14, btol=1e-14,
        max_iterations=10_000, min_valid_fraction=0.5,
    )
    identity = reconstructor.config_hash
    b = rng.normal(size=24)
    full = _measurement(matrix, b)
    np.testing.assert_array_equal(
        reconstructor.reconstruct_subset(full, min_valid_fraction=0.5).delta_coordinates_opd_m,
        reconstructor.reconstruct(full).delta_coordinates_opd_m,
    )
    valid = np.zeros(24, dtype=bool)
    valid[:8] = True  # rows of actuators 0 and 1 only: a third of the rows
    partial = _measurement(matrix, b, valid)
    assert reconstructor.reconstruct(partial) is None
    assert reconstructor.reconstruct_subset(partial, min_valid_fraction=0.4) is None
    plain = reconstructor.reconstruct_subset(partial, min_valid_fraction=0.3)
    expected = _tikhonov(dense[valid], b[valid], reconstructor.damping_absolute)
    np.testing.assert_allclose(plain.delta_coordinates_opd_m, expected, rtol=1e-6, atol=1e-9)
    np.testing.assert_array_equal(plain.usable_rows, valid)

    guarded = reconstructor.reconstruct_subset(
        partial, min_valid_fraction=0.3, min_actuator_coverage=0.5
    )
    x = guarded.delta_coordinates_opd_m
    assert np.count_nonzero(x[2:]) == 0  # unseen and weakly seen actuators hold
    solved = _tikhonov(dense[valid][:, :2], b[valid], reconstructor.damping_absolute)
    np.testing.assert_allclose(x[:2], solved, rtol=1e-6, atol=1e-9)
    np.testing.assert_allclose(
        guarded.reconstructed_signal[valid], dense[valid][:, :2] @ x[:2], rtol=1e-12, atol=1e-12
    )
    nothing_seen = np.zeros(24, dtype=bool)
    nothing_seen[[0, 4, 8, 12, 16, 20, 1, 5]] = True
    assert (
        reconstructor.reconstruct_subset(
            _measurement(matrix, b, nothing_seen), min_valid_fraction=0.1, min_actuator_coverage=0.9
        )
        is None
    )
    with pytest.raises(SparseCalibrationError, match="min_actuator_coverage"):
        reconstructor.reconstruct_subset(partial, min_valid_fraction=0.3, min_actuator_coverage=0.0)
    with pytest.raises(SparseCalibrationError, match="min_valid_fraction"):
        reconstructor.reconstruct_subset(partial, min_valid_fraction=1.5)
    assert reconstructor.config_hash == identity
