"""Numerical diagnostics operate only on canonical calibration-valid rows."""

from __future__ import annotations

import numpy as np
import pytest

from shwfs_ao.calibration.diagnostics import (
    InteractionDiagnosticsError,
    all_zero_columns,
    calibration_valid_matrix,
    interaction_diagnostics,
)


def test_svd_rank_and_condition_use_only_finite_valid_rows() -> None:
    matrix = np.asarray(
        [
            [3.0, 0.0],
            [np.nan, np.nan],
            [0.0, 1.0e-20],
        ]
    )
    row_valid = np.asarray([True, False, True])

    diagnostics = interaction_diagnostics(matrix, row_valid)

    np.testing.assert_allclose(diagnostics.singular_values, [3.0, 1.0e-20])
    assert diagnostics.rank == 1
    # The proxy uses the weakest numerically retained singular value, not the
    # effectively discarded near-zero tail.
    assert diagnostics.condition_proxy == pytest.approx(1.0)
    assert not diagnostics.singular_values.flags.writeable


def test_zero_column_check_ignores_nan_invalid_rows_but_preserves_columns() -> None:
    matrix = np.asarray(
        [
            [1.0, 0.0, -2.0],
            [np.nan, np.nan, np.nan],
            [4.0, 0.0, 0.0],
        ]
    )
    row_valid = np.asarray([True, False, True])

    np.testing.assert_array_equal(
        all_zero_columns(matrix, row_valid),
        [False, True, False],
    )
    valid_matrix, returned_mask = calibration_valid_matrix(matrix, row_valid)
    np.testing.assert_array_equal(valid_matrix, matrix[[0, 2]])
    np.testing.assert_array_equal(returned_mask, row_valid)


@pytest.mark.parametrize(
    ("matrix", "row_valid", "message"),
    [
        (
            np.asarray([[1.0], [2.0]]),
            np.asarray([False, False]),
            "no calibration-valid rows",
        ),
        (
            np.asarray([[np.nan], [2.0]]),
            np.asarray([True, False]),
            "must contain only finite",
        ),
        (
            np.asarray([[1.0], [0.0]]),
            np.asarray([True, False]),
            "must be entirely NaN",
        ),
    ],
)
def test_diagnostics_reject_ambiguous_full_row_layouts(
    matrix: np.ndarray,
    row_valid: np.ndarray,
    message: str,
) -> None:
    with pytest.raises(InteractionDiagnosticsError, match=message):
        interaction_diagnostics(matrix, row_valid)
