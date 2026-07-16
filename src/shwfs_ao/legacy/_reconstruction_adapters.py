"""Private array-compatibility adapters for canonical reconstructors.

Historical public functions accept anonymous numeric matrices without row IDs,
coordinate IDs, wavelengths, or physical command units.  They therefore cannot
truthfully manufacture a canonical :class:`InteractionMatrix`.  This module
keeps their validation and return-shape conventions while delegating every
numeric decomposition to the one private masked kernel owned by
``calibration.reconstructors``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from ..calibration.reconstructors import (
    ReconstructionError as _CanonicalReconstructionError,
    ReconstructorCacheInfo as _ReconstructorCacheInfo,
    _MaskedSvdReconstructor as _CanonicalMaskedSvdReconstructor,
)


_Solver = Literal[
    "least_squares",
    "tsvd",
    "tikhonov",
    "fixed_modes_tsvd",
]


@dataclass(frozen=True)
class _LegacyNumericReconstruction:
    coordinates: np.ndarray
    usable_rows: np.ndarray
    reconstructed_signal: np.ndarray
    residual_signal: np.ndarray
    coordinate_norm: float
    residual_norm: float
    kept_modes: int | None
    singular_values: np.ndarray


class _LegacyArrayReconstructor:
    """Persistent legacy array façade over the bounded canonical mask cache."""

    def __init__(
        self,
        response_matrix: object,
        *,
        solver: _Solver,
        solver_parameter: float | int | None,
        matrix_error: str,
        length_error: str,
        no_rows_error: str,
        error_type: type[ValueError] = ValueError,
        max_cached_masks: int = 32,
    ) -> None:
        try:
            matrix = np.asarray(response_matrix, dtype=float)
        except (TypeError, ValueError) as exc:
            raise error_type(matrix_error) from exc
        if matrix.ndim != 2:
            raise error_type(matrix_error)

        self._matrix = np.array(matrix, dtype=float, copy=True)
        self._length_error = length_error
        self._no_rows_error = no_rows_error
        self._error_type = error_type
        self._kernel: _CanonicalMaskedSvdReconstructor | None
        if self._matrix.shape[1] == 0:
            # NumPy's historical least-squares APIs accept an empty coordinate
            # layout.  No decomposition is needed for that algebraic identity.
            self._kernel = None
        else:
            try:
                self._kernel = _CanonicalMaskedSvdReconstructor(
                    self._matrix,
                    solver=solver,
                    solver_parameter=solver_parameter,
                    min_valid_fraction=0.0,
                    min_rank=0,
                    max_cached_masks=max_cached_masks,
                )
            except (TypeError, ValueError) as exc:
                raise error_type(str(exc)) from exc

    @property
    def cache_info(self) -> _ReconstructorCacheInfo | None:
        return None if self._kernel is None else self._kernel.cache_info

    @property
    def coordinate_count(self) -> int:
        return int(self._matrix.shape[1])

    def reconstruct(self, signal: object) -> _LegacyNumericReconstruction:
        try:
            values = np.asarray(signal, dtype=float).reshape(-1)
        except (TypeError, ValueError) as exc:
            raise self._error_type(self._length_error) from exc
        if values.size != self._matrix.shape[0]:
            raise self._error_type(self._length_error)

        finite_matrix_rows = np.all(np.isfinite(self._matrix), axis=1)
        usable = finite_matrix_rows & np.isfinite(values)
        if not np.any(usable):
            raise self._error_type(self._no_rows_error)

        if self._kernel is None:
            predicted = np.full(values.shape, np.nan, dtype=float)
            residual = np.full(values.shape, np.nan, dtype=float)
            predicted[usable] = 0.0
            residual[usable] = values[usable]
            return _LegacyNumericReconstruction(
                coordinates=np.empty(0, dtype=float),
                usable_rows=np.array(usable, dtype=bool, copy=True),
                reconstructed_signal=predicted,
                residual_signal=residual,
                coordinate_norm=0.0,
                residual_norm=float(np.linalg.norm(values[usable])),
                kept_modes=0,
                singular_values=np.empty(0, dtype=float),
            )

        try:
            numeric = self._kernel.reconstruct(values, np.isfinite(values))
        except _CanonicalReconstructionError as exc:
            raise self._error_type(str(exc)) from exc
        if numeric is None:  # usable rows were checked above
            raise self._error_type(self._no_rows_error)
        return _LegacyNumericReconstruction(
            coordinates=np.array(numeric.coordinates, dtype=float, copy=True),
            usable_rows=np.array(numeric.usable_rows, dtype=bool, copy=True),
            reconstructed_signal=np.array(
                numeric.reconstructed_signal,
                dtype=float,
                copy=True,
            ),
            residual_signal=np.array(
                numeric.residual_signal,
                dtype=float,
                copy=True,
            ),
            coordinate_norm=float(numeric.coordinate_norm),
            residual_norm=float(numeric.residual_norm),
            kept_modes=numeric.kept_modes,
            singular_values=np.array(
                numeric.singular_values,
                dtype=float,
                copy=True,
            ),
        )


def _legacy_least_squares_reconstructor(
    response_matrix: object,
    rcond: object,
    *,
    matrix_error: str,
    length_error: str,
    no_rows_error: str,
    error_type: type[ValueError] = ValueError,
    max_cached_masks: int = 32,
) -> _LegacyArrayReconstructor:
    return _LegacyArrayReconstructor(
        response_matrix,
        solver="least_squares",
        solver_parameter=rcond,
        matrix_error=matrix_error,
        length_error=length_error,
        no_rows_error=no_rows_error,
        error_type=error_type,
        max_cached_masks=max_cached_masks,
    )


def _legacy_tsvd_reconstructor(
    response_matrix: object,
    rcond: float,
    *,
    matrix_error: str,
    length_error: str,
    no_rows_error: str,
    error_type: type[ValueError] = ValueError,
    max_cached_masks: int = 32,
) -> _LegacyArrayReconstructor:
    return _LegacyArrayReconstructor(
        response_matrix,
        solver="tsvd",
        solver_parameter=float(rcond),
        matrix_error=matrix_error,
        length_error=length_error,
        no_rows_error=no_rows_error,
        error_type=error_type,
        max_cached_masks=max_cached_masks,
    )


def _legacy_fixed_modes_tsvd_reconstructor(
    response_matrix: object,
    kept_modes: int,
    *,
    matrix_error: str,
    length_error: str,
    no_rows_error: str,
    error_type: type[ValueError] = ValueError,
    max_cached_masks: int = 32,
) -> _LegacyArrayReconstructor:
    return _LegacyArrayReconstructor(
        response_matrix,
        solver="fixed_modes_tsvd",
        solver_parameter=int(kept_modes),
        matrix_error=matrix_error,
        length_error=length_error,
        no_rows_error=no_rows_error,
        error_type=error_type,
        max_cached_masks=max_cached_masks,
    )


def _legacy_tikhonov_reconstructor(
    response_matrix: object,
    alpha: float,
    *,
    matrix_error: str,
    length_error: str,
    no_rows_error: str,
    error_type: type[ValueError] = ValueError,
    max_cached_masks: int = 32,
) -> _LegacyArrayReconstructor:
    return _LegacyArrayReconstructor(
        response_matrix,
        solver="tikhonov",
        solver_parameter=float(alpha),
        matrix_error=matrix_error,
        length_error=length_error,
        no_rows_error=no_rows_error,
        error_type=error_type,
        max_cached_masks=max_cached_masks,
    )


def _legacy_lstsq_payload(
    reconstruction: _LegacyNumericReconstruction,
    *,
    coordinate_count: int,
) -> tuple[np.ndarray, np.ndarray, int, np.ndarray]:
    rank = int(reconstruction.kept_modes or 0)
    usable_count = int(np.count_nonzero(reconstruction.usable_rows))
    if rank == int(coordinate_count) and usable_count > int(coordinate_count):
        residuals = np.asarray([reconstruction.residual_norm**2], dtype=float)
    else:
        residuals = np.empty(0, dtype=float)
    return (
        np.array(reconstruction.coordinates, dtype=float, copy=True),
        residuals,
        rank,
        np.array(reconstruction.singular_values, dtype=float, copy=True),
    )


def _legacy_zero_filled_signals(
    reconstruction: _LegacyNumericReconstruction,
    original_signal: object,
) -> tuple[np.ndarray, np.ndarray]:
    signal = np.asarray(original_signal, dtype=float).reshape(-1)
    predicted = np.zeros(signal.shape, dtype=float)
    predicted[reconstruction.usable_rows] = reconstruction.reconstructed_signal[
        reconstruction.usable_rows
    ]
    return predicted, signal - predicted


__all__: tuple[str, ...] = ()
