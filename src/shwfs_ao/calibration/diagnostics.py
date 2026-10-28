"""Numerical diagnostics for canonical interaction matrices.

Only rows declared calibration-valid participate in these diagnostics.  This
keeps invalid detector or geometric rows visible in the public matrix layout
without allowing their NaN payloads to leak into an SVD.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np


DEFAULT_NUMERIC_RANK_RTOL = 1.0e-12


class InteractionDiagnosticsError(ValueError):
    """Raised when interaction-matrix diagnostics cannot be computed."""


@dataclass(frozen=True)
class InteractionDiagnostics:
    """SVD-derived diagnostics for the calibration-valid matrix rows."""

    singular_values: np.ndarray
    rank: int
    condition_proxy: float

    def __post_init__(self) -> None:
        singular_values = _immutable_float_array(
            self.singular_values,
            label="singular_values",
            ndim=1,
        )
        if not np.all(np.isfinite(singular_values)):
            raise InteractionDiagnosticsError(
                "singular_values must contain only finite values."
            )
        if np.any(singular_values < 0.0):
            raise InteractionDiagnosticsError(
                "singular_values must be non-negative."
            )
        if singular_values.size and np.any(np.diff(singular_values) > 0.0):
            raise InteractionDiagnosticsError(
                "singular_values must be sorted in descending order."
            )
        if type(self.rank) is not int or not 0 <= self.rank <= singular_values.size:
            raise InteractionDiagnosticsError(
                "rank must be an integer between zero and the singular-value count."
            )
        condition = float(self.condition_proxy)
        if math.isnan(condition) or condition < 1.0:
            raise InteractionDiagnosticsError(
                "condition_proxy must be at least one or positive infinity."
            )
        object.__setattr__(self, "singular_values", singular_values)
        object.__setattr__(self, "condition_proxy", condition)


def interaction_diagnostics(
    matrix: np.ndarray,
    row_valid: np.ndarray,
    *,
    rank_rtol: float = DEFAULT_NUMERIC_RANK_RTOL,
) -> InteractionDiagnostics:
    """Return SVD, numerical rank, and condition proxy for valid rows."""

    values, valid = calibration_valid_matrix(matrix, row_valid)
    tolerance_scale = _positive_finite_float(rank_rtol, label="rank_rtol")
    try:
        singular_values = np.linalg.svd(values, compute_uv=False)
    except np.linalg.LinAlgError as exc:
        raise InteractionDiagnosticsError(
            "SVD failed for the calibration-valid interaction matrix."
        ) from exc
    singular_values = np.maximum(np.asarray(singular_values, dtype=float), 0.0)
    if not np.all(np.isfinite(singular_values)):
        raise InteractionDiagnosticsError(
            "SVD produced non-finite singular values."
        )
    if singular_values.size:
        tolerance = (
            tolerance_scale
            * max(values.shape)
            * float(singular_values[0])
        )
        rank = int(np.sum(singular_values > tolerance))
    else:  # pragma: no cover - valid rows and columns are required above
        rank = 0
    retained = singular_values[:rank]
    condition = (
        float(retained[0] / retained[-1])
        if retained.size
        else float("inf")
    )
    del valid
    return InteractionDiagnostics(
        singular_values=singular_values,
        rank=rank,
        condition_proxy=condition,
    )


def calibration_valid_matrix(
    matrix: np.ndarray,
    row_valid: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Validate a full-layout matrix and return its finite valid-row view."""

    values = _numeric_matrix(matrix, label="matrix")
    valid = _boolean_vector(row_valid, label="row_valid")
    if valid.shape != (values.shape[0],):
        raise InteractionDiagnosticsError(
            "row_valid length must equal the interaction-matrix row count."
        )
    if values.shape[1] == 0:
        raise InteractionDiagnosticsError(
            "interaction matrix must contain at least one coordinate column."
        )
    if not np.any(valid):
        raise InteractionDiagnosticsError(
            "interaction matrix has no calibration-valid rows."
        )
    if not np.all(np.isfinite(values[valid])):
        raise InteractionDiagnosticsError(
            "calibration-valid matrix rows must contain only finite values."
        )
    if np.any(~np.isnan(values[~valid])):
        raise InteractionDiagnosticsError(
            "every calibration-invalid matrix row must be entirely NaN."
        )
    return values[valid], valid


def all_zero_columns(
    matrix: np.ndarray,
    row_valid: np.ndarray,
    *,
    absolute_tolerance: float = 0.0,
) -> np.ndarray:
    """Return a mask of response columns that are zero on every valid row."""

    values, _ = calibration_valid_matrix(matrix, row_valid)
    tolerance = _nonnegative_finite_float(
        absolute_tolerance,
        label="absolute_tolerance",
    )
    return np.all(np.abs(values) <= tolerance, axis=0)


def _numeric_matrix(value: object, *, label: str) -> np.ndarray:
    if not isinstance(value, np.ndarray):
        raise InteractionDiagnosticsError(f"{label} must be a numpy.ndarray.")
    if (
        value.ndim != 2
        or np.issubdtype(value.dtype, np.bool_)
        or not np.issubdtype(value.dtype, np.number)
        or np.issubdtype(value.dtype, np.complexfloating)
    ):
        raise InteractionDiagnosticsError(
            f"{label} must be a two-dimensional real numeric array."
        )
    return np.asarray(value, dtype=float)


def _boolean_vector(value: object, *, label: str) -> np.ndarray:
    if (
        not isinstance(value, np.ndarray)
        or value.dtype != np.dtype(bool)
        or value.ndim != 1
    ):
        raise InteractionDiagnosticsError(
            f"{label} must be a one-dimensional boolean numpy.ndarray."
        )
    return np.asarray(value, dtype=bool)


def _immutable_float_array(
    value: object,
    *,
    label: str,
    ndim: int,
) -> np.ndarray:
    if not isinstance(value, np.ndarray):
        raise InteractionDiagnosticsError(f"{label} must be a numpy.ndarray.")
    if (
        np.issubdtype(value.dtype, np.bool_)
        or not np.issubdtype(value.dtype, np.number)
        or np.issubdtype(value.dtype, np.complexfloating)
    ):
        raise InteractionDiagnosticsError(f"{label} must contain real numbers.")
    contiguous = np.ascontiguousarray(np.array(value, dtype=float, copy=True))
    immutable = np.frombuffer(contiguous.tobytes(order="C"), dtype=contiguous.dtype)
    result = immutable.reshape(contiguous.shape)
    if result.ndim != ndim:
        raise InteractionDiagnosticsError(
            f"{label} must be {ndim}-dimensional."
        )
    return result


def _positive_finite_float(value: object, *, label: str) -> float:
    result = _nonnegative_finite_float(value, label=label)
    if result <= 0.0:
        raise InteractionDiagnosticsError(f"{label} must be positive.")
    return result


def _nonnegative_finite_float(value: object, *, label: str) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise InteractionDiagnosticsError(f"{label} must be a finite number.")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise InteractionDiagnosticsError(
            f"{label} must be a finite number."
        ) from exc
    if not math.isfinite(result) or result < 0.0:
        raise InteractionDiagnosticsError(
            f"{label} must be a non-negative finite number."
        )
    return result


__all__ = (
    "DEFAULT_NUMERIC_RANK_RTOL",
    "InteractionDiagnosticsError",
    "InteractionDiagnostics",
    "calibration_valid_matrix",
    "all_zero_columns",
    "interaction_diagnostics",
)
