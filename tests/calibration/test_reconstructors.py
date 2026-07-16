"""AO-REF-008 contracts for mask-aware canonical reconstructors."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, is_dataclass
import math

import numpy as np
import pytest

from shwfs_ao.calibration import (
    LeastSquaresReconstructor,
    ReconstructionError,
    ReconstructorCacheInfo,
    TikhonovReconstructor,
    TsvdReconstructor,
    calibrate_interaction_matrix,
    kept_modes_for_rcond,
    noise_amplification_proxy,
)
from shwfs_ao.core.protocols import Reconstructor
from shwfs_ao.core.random import NamedRandomStreams
from shwfs_ao.core.types import MeasurementVector, WfsMeasurement


class _ArrayProbeBasis:
    def __init__(
        self,
        coordinate_count: int,
        *,
        coordinate_kind: str = "modal_opd",
    ) -> None:
        self.coordinate_ids = tuple(
            f"coordinate-{index}" for index in range(coordinate_count)
        )
        self.coordinate_kind = coordinate_kind
        self.coordinate_unit = (
            "m_opd_rms"
            if coordinate_kind == "modal_opd"
            else "m_opd_equivalent"
        )
        self.max_abs_amplitude_m = np.full(coordinate_count, np.inf)
        self.config_hash = f"array-basis-{coordinate_kind}-{coordinate_count}"
        if coordinate_kind == "dm_command_opd":
            self.dm_hash = "array-basis-dm-v1"

    @property
    def size(self) -> int:
        return len(self.coordinate_ids)

    def opd_m_for_coordinate(self, index: int, amplitude_m: float) -> np.ndarray:
        result = np.zeros((1, self.size), dtype=float)
        result[0, index] = amplitude_m
        return result


class _MatrixSensor:
    config_hash = "matrix-sensor-v1"
    geometry_hash = "matrix-sensor-geometry-v1"

    def __init__(
        self,
        matrix: np.ndarray,
        calibration_valid: np.ndarray,
        *,
        measurement_unit: str = "pixel",
    ) -> None:
        self.matrix = np.asarray(matrix, dtype=float)
        self.calibration_valid = np.asarray(calibration_valid, dtype=bool)
        self.row_ids = tuple(f"row-{index}" for index in range(self.matrix.shape[0]))
        self.measurement_unit = measurement_unit

    def measure(
        self,
        residual_opd_m: np.ndarray,
        *,
        random_streams: NamedRandomStreams,
        include_noise: bool,
    ) -> WfsMeasurement:
        del random_streams, include_noise
        values = self.matrix @ np.asarray(residual_opd_m, dtype=float).reshape(-1)
        values = np.asarray(values, dtype=float)
        values[~self.calibration_valid] = np.nan
        return WfsMeasurement(
            MeasurementVector(
                values,
                self.calibration_valid.copy(),
                self.row_ids,
                self.measurement_unit,
            )
        )


def _interaction(
    matrix: np.ndarray,
    *,
    calibration_valid: np.ndarray | None = None,
    coordinate_kind: str = "modal_opd",
):
    values = np.asarray(matrix, dtype=float)
    valid = (
        np.ones(values.shape[0], dtype=bool)
        if calibration_valid is None
        else np.asarray(calibration_valid, dtype=bool)
    )
    return calibrate_interaction_matrix(
        _ArrayProbeBasis(values.shape[1], coordinate_kind=coordinate_kind),
        _MatrixSensor(values, valid),
        1.0,
        random_streams=NamedRandomStreams(31),
    )


def _measurement(
    interaction,
    values: np.ndarray,
    valid_rows: np.ndarray,
    *,
    row_ids: tuple[str, ...] | None = None,
    measurement_unit: str | None = None,
) -> MeasurementVector:
    return MeasurementVector(
        np.asarray(values, dtype=float),
        np.asarray(valid_rows, dtype=bool),
        interaction.row_ids if row_ids is None else row_ids,
        interaction.measurement_unit if measurement_unit is None else measurement_unit,
    )


def _cache_info(reconstructor: object) -> ReconstructorCacheInfo:
    info = getattr(reconstructor, "cache_info")
    return info() if callable(info) else info


def test_least_squares_solves_only_usable_rows_and_returns_full_nan_layout() -> None:
    matrix = np.asarray(
        [
            [1.0, 0.0],
            [0.0, 1.0],
            [1.0, 1.0],
            [2.0, -1.0],
            [5.0, 5.0],
        ]
    )
    interaction = _interaction(
        matrix,
        calibration_valid=np.asarray([True, True, True, True, False]),
    )
    truth = np.asarray([2.0, -3.0])
    values = matrix @ truth
    values[2] = 1.0e90  # Runtime-invalid finite payload must not become a zero row.
    values[4] = -1.0e90  # Calibration-invalid rows are excluded independently.
    runtime_valid = np.asarray([True, True, False, True, True])
    measurement = _measurement(interaction, values, runtime_valid)
    reconstructor = LeastSquaresReconstructor(
        interaction,
        min_valid_fraction=0.5,
        min_rank=2,
    )

    estimate = reconstructor.reconstruct(measurement)

    assert estimate is not None
    assert isinstance(reconstructor, Reconstructor)
    np.testing.assert_allclose(estimate.delta_coordinates_opd_m, truth, atol=1.0e-13)
    np.testing.assert_array_equal(
        estimate.usable_rows,
        [True, True, False, True, False],
    )
    np.testing.assert_allclose(
        estimate.reconstructed_signal[estimate.usable_rows],
        (matrix @ truth)[estimate.usable_rows],
        atol=1.0e-13,
    )
    np.testing.assert_allclose(
        estimate.residual_signal[estimate.usable_rows],
        0.0,
        atol=1.0e-13,
    )
    assert np.all(np.isnan(estimate.reconstructed_signal[~estimate.usable_rows]))
    assert np.all(np.isnan(estimate.residual_signal[~estimate.usable_rows]))
    assert estimate.coordinate_ids == interaction.coordinate_ids
    assert estimate.coordinate_kind == interaction.coordinate_kind
    assert estimate.coordinate_unit == interaction.coordinate_unit
    assert estimate.measurement_unit == interaction.measurement_unit
    assert estimate.matrix_hash == interaction.calibration_hash
    assert reconstructor.matrix_hash == interaction.calibration_hash
    assert isinstance(reconstructor.config_hash, str) and reconstructor.config_hash
    assert estimate.coordinate_norm_m == pytest.approx(np.linalg.norm(truth))
    assert estimate.residual_norm == pytest.approx(0.0, abs=1.0e-13)
    np.testing.assert_allclose(
        estimate.singular_values,
        np.linalg.svd(matrix[[0, 1, 3]], compute_uv=False),
    )
    for array in (
        estimate.delta_coordinates_opd_m,
        estimate.usable_rows,
        estimate.reconstructed_signal,
        estimate.residual_signal,
        estimate.singular_values,
    ):
        assert not array.flags.writeable


def test_dm_coordinate_identity_and_unit_are_not_relabelled() -> None:
    interaction = _interaction(np.eye(2), coordinate_kind="dm_command_opd")
    estimate = LeastSquaresReconstructor(
        interaction,
        min_valid_fraction=1.0,
        min_rank=2,
    ).reconstruct(
        _measurement(
            interaction,
            np.asarray([7.0e-9, -2.0e-9]),
            np.ones(2, dtype=bool),
        )
    )

    assert estimate is not None
    assert estimate.coordinate_ids == interaction.coordinate_ids
    assert estimate.coordinate_kind == "dm_command_opd"
    assert estimate.coordinate_unit == "m_opd_equivalent"
    np.testing.assert_allclose(
        estimate.delta_coordinates_opd_m,
        [7.0e-9, -2.0e-9],
        atol=1.0e-24,
    )


def test_rank_deficient_least_squares_returns_the_minimum_norm_solution() -> None:
    matrix = np.asarray([[1.0, 1.0], [2.0, 2.0], [3.0, 3.0]])
    interaction = _interaction(matrix)
    measurement = _measurement(
        interaction,
        matrix @ np.asarray([1.0, 1.0]),
        np.ones(3, dtype=bool),
    )
    estimate = LeastSquaresReconstructor(
        interaction,
        min_valid_fraction=1.0,
        min_rank=1,
    ).reconstruct(measurement)

    assert estimate is not None
    np.testing.assert_allclose(estimate.delta_coordinates_opd_m, [1.0, 1.0])
    assert estimate.kept_modes == 1
    assert estimate.residual_norm == pytest.approx(0.0, abs=1.0e-12)


def test_none_is_reserved_for_valid_measurements_below_coverage_or_rank_policy() -> None:
    matrix = np.asarray([[1.0, 1.0], [2.0, 2.0], [1.0, 0.0]])
    interaction = _interaction(matrix)
    values = matrix @ np.asarray([0.5, -0.25])

    no_rows = _measurement(
        interaction,
        np.full(3, np.nan),
        np.zeros(3, dtype=bool),
    )
    no_rows_reconstructor = LeastSquaresReconstructor(
        interaction,
        min_valid_fraction=0.0,
        min_rank=1,
    )
    assert no_rows_reconstructor.reconstruct(no_rows) is None
    assert _cache_info(no_rows_reconstructor).svd_computations == 0

    one_row = _measurement(
        interaction,
        values,
        np.asarray([True, False, False]),
    )
    insufficient_coverage = LeastSquaresReconstructor(
        interaction,
        min_valid_fraction=0.5,
        min_rank=1,
    )
    assert insufficient_coverage.reconstruct(one_row) is None
    assert _cache_info(insufficient_coverage).svd_computations == 0

    rank_one = _measurement(
        interaction,
        values,
        np.asarray([True, True, False]),
    )
    assert LeastSquaresReconstructor(
        interaction,
        min_valid_fraction=0.5,
        min_rank=2,
    ).reconstruct(rank_one) is None


def test_valid_fraction_denominator_counts_only_calibration_valid_rows() -> None:
    matrix = np.asarray(
        [[1.0], [2.0], [3.0], [4.0]]
    )
    interaction = _interaction(
        matrix,
        calibration_valid=np.asarray([True, True, False, False]),
    )
    measurement = _measurement(
        interaction,
        matrix[:, 0],
        np.asarray([True, False, True, True]),
    )

    passing = LeastSquaresReconstructor(
        interaction,
        min_valid_fraction=0.5,
        min_rank=1,
    ).reconstruct(measurement)
    failing = LeastSquaresReconstructor(
        interaction,
        min_valid_fraction=np.nextafter(0.5, 1.0),
        min_rank=1,
    ).reconstruct(measurement)

    assert passing is not None
    np.testing.assert_array_equal(passing.usable_rows, [True, False, False, False])
    assert failing is None


@pytest.mark.parametrize("identity_case", ["reordered", "missing", "extra", "unit"])
def test_measurement_identity_and_unit_mismatch_are_errors_not_none(
    identity_case: str,
) -> None:
    interaction = _interaction(np.eye(3))
    row_ids = interaction.row_ids
    values = np.asarray([1.0, 2.0, 3.0])
    valid = np.ones(3, dtype=bool)
    unit = interaction.measurement_unit
    if identity_case == "reordered":
        row_ids = tuple(reversed(row_ids))
        values = values[::-1]
        valid = valid[::-1]
    elif identity_case == "missing":
        row_ids = row_ids[:-1]
        values = values[:-1]
        valid = valid[:-1]
    elif identity_case == "extra":
        row_ids = (*row_ids, "extra-row")
        values = np.append(values, 4.0)
        valid = np.append(valid, True)
    else:
        unit = "rad_wavefront_slope"
    malformed = _measurement(
        interaction,
        values,
        valid,
        row_ids=row_ids,
        measurement_unit=unit,
    )

    with pytest.raises(ReconstructionError):
        LeastSquaresReconstructor(
            interaction,
            min_valid_fraction=0.0,
            min_rank=1,
        ).reconstruct(malformed)


def test_tsvd_kept_mode_boundary_spectrum_residual_and_noise_proxy() -> None:
    matrix = np.diag([4.0, 1.0, 0.1])
    interaction = _interaction(matrix)
    measurement = _measurement(
        interaction,
        matrix @ np.ones(3),
        np.ones(3, dtype=bool),
    )
    reconstructor = TsvdReconstructor(
        interaction,
        0.25,
        min_valid_fraction=1.0,
        min_rank=3,
    )
    estimate = reconstructor.reconstruct(measurement)

    assert estimate is not None
    assert estimate.kept_modes == 2  # Equality at rcond*s_max is retained.
    np.testing.assert_allclose(estimate.singular_values, [4.0, 1.0, 0.1])
    np.testing.assert_allclose(estimate.delta_coordinates_opd_m, [1.0, 1.0, 0.0])
    np.testing.assert_allclose(estimate.reconstructed_signal, [4.0, 1.0, 0.0])
    np.testing.assert_allclose(estimate.residual_signal, [0.0, 0.0, 0.1])
    assert kept_modes_for_rcond(estimate.singular_values, 0.25) == 2
    assert noise_amplification_proxy(
        estimate.singular_values,
        0.25,
    ) == pytest.approx(math.sqrt((1.0 / 4.0) ** 2 + 1.0))


def test_noise_amplification_is_monotonic_as_tsvd_cutoff_decreases() -> None:
    singular_values = np.asarray([5.0, 1.0, 0.2, 0.01])
    proxies = [
        noise_amplification_proxy(singular_values, rcond)
        for rcond in (0.3, 0.1, 0.01, 0.001)
    ]

    assert all(left <= right for left, right in zip(proxies, proxies[1:]))


def test_subnormal_tsvd_cutoff_never_retains_an_exact_zero_mode() -> None:
    matrix = np.asarray([[0.1, 0.0], [0.2, 0.0], [0.0, 0.1]])
    interaction = _interaction(matrix)
    measurement = _measurement(
        interaction,
        matrix @ np.asarray([2.0, 3.0]),
        np.asarray([True, True, False]),
    )
    smallest_positive = float(np.nextafter(0.0, 1.0))

    estimate = TsvdReconstructor(
        interaction,
        smallest_positive,
        min_valid_fraction=0.0,
        min_rank=1,
    ).reconstruct(measurement)

    assert estimate is not None
    assert estimate.kept_modes == 1
    assert kept_modes_for_rcond(
        np.asarray([0.1, 0.0]),
        smallest_positive,
    ) == 1
    assert noise_amplification_proxy(
        np.asarray([0.1, 0.0]),
        smallest_positive,
    ) == pytest.approx(10.0)


def test_norm_diagnostics_avoid_intermediate_overflow() -> None:
    interaction = _interaction(np.eye(2))
    measurement = _measurement(
        interaction,
        np.asarray([1.0e200, -1.0e200]),
        np.ones(2, dtype=bool),
    )

    estimate = LeastSquaresReconstructor(
        interaction,
        min_valid_fraction=1.0,
        min_rank=2,
    ).reconstruct(measurement)

    assert estimate is not None
    assert estimate.coordinate_norm_m == pytest.approx(math.sqrt(2.0) * 1.0e200)
    assert math.isfinite(
        noise_amplification_proxy(np.asarray([1.0, 1.0e-200]), 1.0e-250)
    )


def test_tikhonov_alpha_zero_matches_least_squares_and_positive_alpha_formula() -> None:
    matrix = np.diag([4.0, 1.0, 0.1])
    interaction = _interaction(matrix)
    measurement = _measurement(
        interaction,
        matrix @ np.ones(3),
        np.ones(3, dtype=bool),
    )
    policy = {"min_valid_fraction": 1.0, "min_rank": 3}
    least_squares = LeastSquaresReconstructor(interaction, **policy).reconstruct(
        measurement
    )
    alpha_zero = TikhonovReconstructor(interaction, 0.0, **policy).reconstruct(
        measurement
    )
    regularized = TikhonovReconstructor(interaction, 0.5, **policy).reconstruct(
        measurement
    )

    assert least_squares is not None and alpha_zero is not None
    assert regularized is not None
    np.testing.assert_allclose(
        alpha_zero.delta_coordinates_opd_m,
        least_squares.delta_coordinates_opd_m,
        rtol=1.0e-14,
        atol=1.0e-14,
    )
    np.testing.assert_allclose(
        alpha_zero.reconstructed_signal,
        least_squares.reconstructed_signal,
        rtol=1.0e-14,
        atol=1.0e-14,
    )
    expected = np.asarray([4.0**2, 1.0**2, 0.1**2]) / (
        np.asarray([4.0**2, 1.0**2, 0.1**2]) + 0.5**2
    )
    np.testing.assert_allclose(regularized.delta_coordinates_opd_m, expected)
    assert regularized.coordinate_norm_m < alpha_zero.coordinate_norm_m
    assert regularized.kept_modes is None


def test_repeated_mask_has_observable_cache_hit_and_no_second_svd() -> None:
    matrix = np.asarray(
        [[1.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, -1.0]]
    )
    interaction = _interaction(matrix)
    reconstructor = TsvdReconstructor(
        interaction,
        1.0e-8,
        min_valid_fraction=0.5,
        min_rank=2,
        max_cached_masks=2,
    )
    mask = np.asarray([True, True, True, False])
    first = reconstructor.reconstruct(
        _measurement(interaction, matrix @ np.asarray([1.0, 2.0]), mask)
    )
    second = reconstructor.reconstruct(
        _measurement(interaction, matrix @ np.asarray([-3.0, 0.5]), mask)
    )
    info = _cache_info(reconstructor)

    assert first is not None and second is not None
    assert isinstance(info, ReconstructorCacheInfo)
    assert is_dataclass(info)
    assert info.hits == 1
    assert info.misses == 1
    assert info.svd_computations == 1
    assert info.current_size == 1
    assert info.max_size == 2
    with pytest.raises(FrozenInstanceError):
        info.hits = 99  # type: ignore[misc]


def test_lru_eviction_is_deterministic_and_capacity_zero_is_equivalent() -> None:
    matrix = np.asarray(
        [
            [1.0, 0.0],
            [0.0, 1.0],
            [1.0, 1.0],
            [1.0, -1.0],
            [2.0, 1.0],
            [-1.0, 2.0],
        ]
    )
    interaction = _interaction(matrix)
    masks = (
        np.asarray([True, True, True, False, False, False]),
        np.asarray([False, True, False, True, True, False]),
        np.asarray([True, False, False, False, True, True]),
    )
    cached = TsvdReconstructor(
        interaction,
        1.0e-8,
        min_valid_fraction=0.0,
        min_rank=2,
        max_cached_masks=2,
    )
    truth = np.asarray([0.75, -1.25])
    for mask in (masks[0], masks[1], masks[0], masks[2], masks[1]):
        assert cached.reconstruct(
            _measurement(interaction, matrix @ truth, mask)
        ) is not None
    info = _cache_info(cached)
    assert (info.hits, info.misses, info.svd_computations, info.current_size) == (
        1,
        4,
        4,
        2,
    )

    uncached = TsvdReconstructor(
        interaction,
        1.0e-8,
        min_valid_fraction=0.0,
        min_rank=2,
        max_cached_masks=0,
    )
    measurement = _measurement(interaction, matrix @ truth, masks[0])
    cached_result = cached.reconstruct(measurement)
    uncached_result = uncached.reconstruct(measurement)
    assert cached_result is not None and uncached_result is not None
    np.testing.assert_allclose(
        uncached_result.delta_coordinates_opd_m,
        cached_result.delta_coordinates_opd_m,
    )
    np.testing.assert_allclose(
        uncached_result.reconstructed_signal,
        cached_result.reconstructed_signal,
    )
    assert _cache_info(uncached).current_size == 0


def test_cached_rank_failure_returns_none_without_repeating_svd() -> None:
    matrix = np.asarray([[1.0, 1.0], [2.0, 2.0], [1.0, 0.0]])
    interaction = _interaction(matrix)
    reconstructor = LeastSquaresReconstructor(
        interaction,
        min_valid_fraction=0.0,
        min_rank=2,
        max_cached_masks=2,
    )
    measurement = _measurement(
        interaction,
        matrix @ np.asarray([1.0, 1.0]),
        np.asarray([True, True, False]),
    )

    assert reconstructor.reconstruct(measurement) is None
    assert reconstructor.reconstruct(measurement) is None
    info = _cache_info(reconstructor)
    assert info.hits == 1
    assert info.misses == 1
    assert info.svd_computations == 1


@pytest.mark.parametrize(
    "factory",
    [
        lambda interaction: LeastSquaresReconstructor(
            interaction, min_valid_fraction=np.nan, min_rank=1
        ),
        lambda interaction: LeastSquaresReconstructor(
            interaction, min_valid_fraction=-0.1, min_rank=1
        ),
        lambda interaction: LeastSquaresReconstructor(
            interaction, min_valid_fraction=1.1, min_rank=1
        ),
        lambda interaction: LeastSquaresReconstructor(
            interaction, min_valid_fraction=0.0, min_rank=0
        ),
        lambda interaction: LeastSquaresReconstructor(
            interaction, min_valid_fraction=0.0, min_rank=True
        ),
        lambda interaction: LeastSquaresReconstructor(
            interaction,
            min_valid_fraction=0.0,
            min_rank=1,
            max_cached_masks=-1,
        ),
        lambda interaction: TsvdReconstructor(
            interaction, 0.0, min_valid_fraction=0.0, min_rank=1
        ),
        lambda interaction: TsvdReconstructor(
            interaction, 1.0, min_valid_fraction=0.0, min_rank=1
        ),
        lambda interaction: TsvdReconstructor(
            interaction, np.inf, min_valid_fraction=0.0, min_rank=1
        ),
        lambda interaction: TikhonovReconstructor(
            interaction, -1.0, min_valid_fraction=0.0, min_rank=1
        ),
        lambda interaction: TikhonovReconstructor(
            interaction, np.nan, min_valid_fraction=0.0, min_rank=1
        ),
    ],
)
def test_reconstructor_settings_reject_ambiguous_or_invalid_values(factory) -> None:
    interaction = _interaction(np.eye(2))
    with pytest.raises(ReconstructionError):
        factory(interaction)
