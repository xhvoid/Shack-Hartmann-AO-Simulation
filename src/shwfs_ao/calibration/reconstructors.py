"""Mask-aware reconstructors for canonical interaction matrices.

The public reconstructors in this module consume a validated
:class:`~shwfs_ao.calibration.interaction.InteractionMatrix` and return the
shared :class:`~shwfs_ao.core.types.ReconstructionEstimate` contract.  Runtime
row masks are part of the numerical operator identity: each distinct usable
row layout is decomposed once and retained in a bounded deterministic LRU.

The small private numeric kernel also gives legacy adapters one owner for the
actual least-squares/SVD work without inventing physical coordinate metadata
that their historical array-only APIs do not possess.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from numbers import Integral
from types import MappingProxyType
from typing import Literal, cast

import numpy as np

from ..core.hashing import component_config_hash
from ..core.types import MeasurementVector, ReconstructionEstimate
from .diagnostics import DEFAULT_NUMERIC_RANK_RTOL
from .interaction import InteractionMatrix


__all__ = (
    "ReconstructionError",
    "ReconstructorCacheInfo",
    "LeastSquaresReconstructor",
    "TsvdReconstructor",
    "TikhonovReconstructor",
    "kept_modes_for_rcond",
    "noise_amplification_proxy",
    "choose_rcond_from_singular_values",
    "scan_tsvd_rcond",
)


_SolverKind = Literal[
    "least_squares",
    "tsvd",
    "tikhonov",
    "fixed_modes_tsvd",
]
_CacheKey = tuple[str, str, int, bytes]


class ReconstructionError(ValueError):
    """Raised when reconstruction inputs or numerical settings are invalid."""


@dataclass(frozen=True)
class ReconstructorCacheInfo:
    """Immutable snapshot of one reconstructor's masked-operator cache."""

    hits: int
    misses: int
    svd_computations: int
    current_size: int
    max_size: int

    def __post_init__(self) -> None:
        for field_name in (
            "hits",
            "misses",
            "svd_computations",
            "current_size",
            "max_size",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise ReconstructionError(
                    f"{field_name} must be a non-negative integer."
                )
        if self.current_size > self.max_size:
            raise ReconstructionError("current_size cannot exceed max_size.")

    @property
    def size(self) -> int:
        """Compatibility-friendly alias for ``current_size``."""

        return self.current_size

    @property
    def max_cached_masks(self) -> int:
        """Compatibility-friendly alias for ``max_size``."""

        return self.max_size


@dataclass(frozen=True)
class _CacheEntry:
    operator: np.ndarray
    singular_values: np.ndarray
    numerical_rank: int
    kept_modes: int | None


@dataclass(frozen=True)
class _NumericReconstruction:
    coordinates: np.ndarray
    usable_rows: np.ndarray
    reconstructed_signal: np.ndarray
    residual_signal: np.ndarray
    coordinate_norm: float
    residual_norm: float
    kept_modes: int | None
    singular_values: np.ndarray


class _MaskedSvdReconstructor:
    """Private cached numerical owner shared by typed and legacy adapters.

    This class deliberately has no opinion about physical units or coordinate
    identities.  Public callers must use one of the typed reconstructors
    below; historical array-only wrappers use this kernel through a private
    adapter and restore their legacy return contracts there.
    """

    def __init__(
        self,
        matrix: np.ndarray,
        *,
        row_valid: np.ndarray | None = None,
        matrix_hash: str | None = None,
        solver: _SolverKind,
        solver_parameter: float | int | None,
        min_valid_fraction: float,
        min_rank: int,
        max_cached_masks: int = 32,
    ) -> None:
        values = _numeric_matrix(matrix, label="matrix")
        if row_valid is None:
            declared_valid = np.all(np.isfinite(values), axis=1)
        else:
            declared_valid = _boolean_vector(
                row_valid,
                length=values.shape[0],
                label="row_valid",
            )
            declared_valid = declared_valid & np.all(np.isfinite(values), axis=1)

        # Canonicalize every unavailable row to all-NaN.  This prevents a
        # partially finite historical row from being used positionally later.
        canonical_matrix = np.array(values, dtype=float, copy=True)
        canonical_matrix[~declared_valid, :] = np.nan
        self._matrix = _immutable_float_array(canonical_matrix)
        self._row_valid = _immutable_bool_array(declared_valid)
        self._solver = solver
        self._solver_parameter = solver_parameter
        self._min_valid_fraction = _valid_fraction(
            min_valid_fraction,
            label="min_valid_fraction",
        )
        self._min_rank = _nonnegative_integer(min_rank, label="min_rank")
        self._max_cached_masks = _nonnegative_integer(
            max_cached_masks,
            label="max_cached_masks",
        )
        self._matrix_hash = (
            _nonempty_string(matrix_hash, label="matrix_hash")
            if matrix_hash is not None
            else component_config_hash(
                "numeric_reconstruction_matrix",
                {
                    "matrix": self._matrix,
                    "row_valid": self._row_valid,
                },
            )
        )
        self._config_hash = component_config_hash(
            "masked_reconstructor",
            {
                "solver": solver,
                "solver_parameter": solver_parameter,
                "min_valid_fraction": self._min_valid_fraction,
                "min_rank": self._min_rank,
                "max_cached_masks": self._max_cached_masks,
            },
        )
        self._cache: OrderedDict[_CacheKey, _CacheEntry] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._svd_computations = 0

    @property
    def matrix_hash(self) -> str:
        return self._matrix_hash

    @property
    def config_hash(self) -> str:
        return self._config_hash

    @property
    def cache_info(self) -> ReconstructorCacheInfo:
        return ReconstructorCacheInfo(
            hits=self._hits,
            misses=self._misses,
            svd_computations=self._svd_computations,
            current_size=len(self._cache),
            max_size=self._max_cached_masks,
        )

    def clear_cache(self) -> None:
        """Drop cached operators and reset cache counters."""

        self._cache.clear()
        self._hits = 0
        self._misses = 0
        self._svd_computations = 0

    def reconstruct(
        self,
        values: np.ndarray,
        valid_rows: np.ndarray,
    ) -> _NumericReconstruction | None:
        signal = _numeric_vector(
            values,
            length=self._matrix.shape[0],
            label="measurement values",
        )
        runtime_valid = _boolean_vector(
            valid_rows,
            length=self._matrix.shape[0],
            label="measurement valid_rows",
        )
        usable = self._row_valid & runtime_valid & np.isfinite(signal)
        usable_count = int(np.count_nonzero(usable))
        calibration_valid_count = int(np.count_nonzero(self._row_valid))
        if usable_count == 0 or calibration_valid_count == 0:
            return None
        usable_fraction = usable_count / calibration_valid_count
        if usable_fraction < self._min_valid_fraction:
            return None

        entry = self._entry_for_mask(usable)
        if entry.numerical_rank < self._min_rank:
            return None

        usable_signal = signal[usable]
        coordinates = entry.operator @ usable_signal
        if not np.all(np.isfinite(coordinates)):
            raise ReconstructionError(
                "Reconstruction produced non-finite coordinate values."
            )
        predicted = self._matrix[usable, :] @ coordinates
        residual = usable_signal - predicted
        if not np.all(np.isfinite(predicted)) or not np.all(np.isfinite(residual)):
            raise ReconstructionError(
                "Reconstruction produced a non-finite signal or residual."
            )

        full_predicted = np.full(self._matrix.shape[0], np.nan, dtype=float)
        full_residual = np.full(self._matrix.shape[0], np.nan, dtype=float)
        full_predicted[usable] = predicted
        full_residual[usable] = residual
        return _NumericReconstruction(
            coordinates=_immutable_float_array(coordinates),
            usable_rows=_immutable_bool_array(usable),
            reconstructed_signal=_immutable_float_array(full_predicted),
            residual_signal=_immutable_float_array(full_residual),
            coordinate_norm=_scaled_l2_norm(coordinates),
            residual_norm=_scaled_l2_norm(residual),
            kept_modes=entry.kept_modes,
            singular_values=entry.singular_values,
        )

    def _entry_for_mask(self, usable: np.ndarray) -> _CacheEntry:
        packed_mask = np.packbits(usable, bitorder="little").tobytes()
        key = (
            self._matrix_hash,
            self._config_hash,
            int(usable.size),
            packed_mask,
        )
        if self._max_cached_masks > 0:
            cached = self._cache.get(key)
            if cached is not None:
                self._hits += 1
                self._cache.move_to_end(key, last=True)
                return cached

        self._misses += 1
        self._svd_computations += 1
        entry = self._decompose(self._matrix[usable, :])
        if self._max_cached_masks > 0:
            self._cache[key] = entry
            self._cache.move_to_end(key, last=True)
            while len(self._cache) > self._max_cached_masks:
                self._cache.popitem(last=False)
        return entry

    def _decompose(self, matrix: np.ndarray) -> _CacheEntry:
        try:
            if self._solver == "least_squares":
                left, singular_values, right_t = np.linalg.svd(
                    matrix,
                    full_matrices=False,
                )
                retained = _least_squares_retained(
                    singular_values,
                    matrix.shape,
                    self._solver_parameter,
                )
                filters = np.zeros_like(singular_values)
                filters[retained] = 1.0 / singular_values[retained]
                operator = (right_t.T * filters) @ left.T
                kept_modes: int | None = int(np.count_nonzero(retained))
            elif self._solver == "tikhonov" and self._solver_parameter == 0.0:
                left, singular_values, right_t = np.linalg.svd(
                    matrix,
                    full_matrices=False,
                )
                retained = _least_squares_retained(
                    singular_values,
                    matrix.shape,
                    None,
                )
                filters = np.zeros_like(singular_values)
                filters[retained] = 1.0 / singular_values[retained]
                operator = (right_t.T * filters) @ left.T
                kept_modes = None
            else:
                left, singular_values, right_t = np.linalg.svd(
                    matrix,
                    full_matrices=False,
                )
                filters = np.zeros_like(singular_values)
                if self._solver == "tsvd":
                    rcond = cast(float, self._solver_parameter)
                    if singular_values.size and singular_values[0] > 0.0:
                        retained = (
                            singular_values >= rcond * singular_values[0]
                        ) & (singular_values > 0.0)
                    else:
                        retained = np.zeros(singular_values.shape, dtype=bool)
                    filters[retained] = 1.0 / singular_values[retained]
                    kept_modes = int(np.count_nonzero(retained))
                elif self._solver == "fixed_modes_tsvd":
                    requested = cast(int, self._solver_parameter)
                    retained = np.zeros(singular_values.shape, dtype=bool)
                    retained[: min(requested, singular_values.size)] = True
                    retained &= singular_values > 0.0
                    filters[retained] = 1.0 / singular_values[retained]
                    kept_modes = int(np.count_nonzero(retained))
                elif self._solver == "tikhonov":
                    alpha = cast(float, self._solver_parameter)
                    cutoff = _machine_singular_cutoff(singular_values, matrix.shape)
                    retained = singular_values > cutoff
                    retained_values = singular_values[retained]
                    scale = np.maximum(retained_values, alpha)
                    scaled_values = retained_values / scale
                    scaled_alpha = alpha / scale
                    filters[retained] = (
                        scaled_values
                        / (scaled_values**2 + scaled_alpha**2)
                        / scale
                    )
                    kept_modes = None
                else:  # pragma: no cover - all construction is internal
                    raise ReconstructionError(
                        f"Unsupported reconstruction solver {self._solver!r}."
                    )
                operator = (right_t.T * filters) @ left.T
        except np.linalg.LinAlgError as exc:
            raise ReconstructionError(
                "The masked interaction-matrix decomposition failed."
            ) from exc

        singular_values = np.maximum(np.asarray(singular_values, dtype=float), 0.0)
        if (
            not np.all(np.isfinite(singular_values))
            or not np.all(np.isfinite(operator))
        ):
            raise ReconstructionError(
                "The masked interaction-matrix decomposition was non-finite."
            )
        numerical_rank = _numerical_rank(singular_values, matrix.shape)
        return _CacheEntry(
            operator=_immutable_float_array(operator),
            singular_values=_immutable_float_array(singular_values),
            numerical_rank=numerical_rank,
            kept_modes=kept_modes,
        )


class _TypedReconstructor:
    """Common identity, unit, masking, and result handling."""

    _solver_name: str

    def __init__(
        self,
        interaction_matrix: InteractionMatrix,
        *,
        solver: _SolverKind,
        solver_parameter: float | int | None,
        min_valid_fraction: float,
        min_rank: int,
        max_cached_masks: int,
    ) -> None:
        if not isinstance(interaction_matrix, InteractionMatrix):
            raise ReconstructionError(
                "interaction_matrix must be a canonical InteractionMatrix."
            )
        valid_fraction = _valid_fraction(
            min_valid_fraction,
            label="min_valid_fraction",
        )
        required_rank = _positive_integer(min_rank, label="min_rank")
        cache_capacity = _nonnegative_integer(
            max_cached_masks,
            label="max_cached_masks",
        )
        self._interaction_matrix = interaction_matrix
        self._kernel = _MaskedSvdReconstructor(
            interaction_matrix.matrix,
            row_valid=interaction_matrix.row_valid,
            matrix_hash=interaction_matrix.calibration_hash,
            solver=solver,
            solver_parameter=solver_parameter,
            min_valid_fraction=valid_fraction,
            min_rank=required_rank,
            max_cached_masks=cache_capacity,
        )
        metadata = {
            "matrix_hash": interaction_matrix.calibration_hash,
            "config_hash": self._kernel.config_hash,
            "solver": self._solver_name,
            "solver_parameter": solver_parameter,
            "min_valid_fraction": valid_fraction,
            "min_rank": required_rank,
            "max_cached_masks": cache_capacity,
        }
        self._metadata: Mapping[str, object] = MappingProxyType(metadata)

    @property
    def interaction_matrix(self) -> InteractionMatrix:
        return self._interaction_matrix

    @property
    def matrix_hash(self) -> str:
        return self._interaction_matrix.calibration_hash

    @property
    def config_hash(self) -> str:
        return self._kernel.config_hash

    @property
    def metadata(self) -> Mapping[str, object]:
        return self._metadata

    @property
    def cache_info(self) -> ReconstructorCacheInfo:
        return self._kernel.cache_info

    @property
    def min_valid_fraction(self) -> float:
        return cast(float, self._metadata["min_valid_fraction"])

    @property
    def min_rank(self) -> int:
        return cast(int, self._metadata["min_rank"])

    @property
    def max_cached_masks(self) -> int:
        return cast(int, self._metadata["max_cached_masks"])

    def clear_cache(self) -> None:
        self._kernel.clear_cache()

    def reconstruct(
        self,
        measurement: MeasurementVector,
    ) -> ReconstructionEstimate | None:
        if not isinstance(measurement, MeasurementVector):
            raise ReconstructionError(
                "measurement must be a canonical MeasurementVector."
            )
        matrix = self._interaction_matrix
        if measurement.row_ids != matrix.row_ids:
            raise ReconstructionError(
                "measurement.row_ids must exactly match the interaction-matrix "
                "row IDs and ordering."
            )
        if measurement.measurement_unit != matrix.measurement_unit:
            raise ReconstructionError(
                "measurement.measurement_unit must match the interaction matrix."
            )
        numeric = self._kernel.reconstruct(
            measurement.values,
            measurement.valid_rows,
        )
        if numeric is None:
            return None
        return ReconstructionEstimate(
            delta_coordinates_opd_m=numeric.coordinates,
            coordinate_ids=matrix.coordinate_ids,
            coordinate_kind=matrix.coordinate_kind,
            coordinate_unit=matrix.coordinate_unit,
            measurement_unit=matrix.measurement_unit,
            usable_rows=numeric.usable_rows,
            reconstructed_signal=numeric.reconstructed_signal,
            residual_signal=numeric.residual_signal,
            coordinate_norm_m=numeric.coordinate_norm,
            residual_norm=numeric.residual_norm,
            kept_modes=numeric.kept_modes,
            singular_values=numeric.singular_values,
            matrix_hash=matrix.calibration_hash,
        )


class LeastSquaresReconstructor(_TypedReconstructor):
    """Minimum-norm least-squares reconstruction on each usable row mask."""

    _solver_name = "least_squares"

    def __init__(
        self,
        interaction_matrix: InteractionMatrix,
        *,
        min_valid_fraction: float,
        min_rank: int,
        max_cached_masks: int = 32,
    ) -> None:
        super().__init__(
            interaction_matrix,
            solver="least_squares",
            solver_parameter=None,
            min_valid_fraction=min_valid_fraction,
            min_rank=min_rank,
            max_cached_masks=max_cached_masks,
        )


class TsvdReconstructor(_TypedReconstructor):
    """Truncated-SVD reconstruction with a relative singular-value cutoff."""

    _solver_name = "tsvd"

    def __init__(
        self,
        interaction_matrix: InteractionMatrix,
        rcond: float,
        *,
        min_valid_fraction: float,
        min_rank: int,
        max_cached_masks: int = 32,
    ) -> None:
        cutoff = _rcond(rcond)
        self._rcond = cutoff
        super().__init__(
            interaction_matrix,
            solver="tsvd",
            solver_parameter=cutoff,
            min_valid_fraction=min_valid_fraction,
            min_rank=min_rank,
            max_cached_masks=max_cached_masks,
        )

    @property
    def rcond(self) -> float:
        return self._rcond


class TikhonovReconstructor(_TypedReconstructor):
    """Zero-order Tikhonov reconstruction with regularization scale ``alpha``."""

    _solver_name = "tikhonov"

    def __init__(
        self,
        interaction_matrix: InteractionMatrix,
        alpha: float,
        *,
        min_valid_fraction: float,
        min_rank: int,
        max_cached_masks: int = 32,
    ) -> None:
        regularization = _nonnegative_finite_float(alpha, label="alpha")
        self._alpha = regularization
        super().__init__(
            interaction_matrix,
            solver="tikhonov",
            solver_parameter=regularization,
            min_valid_fraction=min_valid_fraction,
            min_rank=min_rank,
            max_cached_masks=max_cached_masks,
        )

    @property
    def alpha(self) -> float:
        return self._alpha


def kept_modes_for_rcond(
    singular_values: Sequence[float] | np.ndarray,
    rcond: float,
) -> int:
    """Count modes retained by the inclusive relative TSVD cutoff."""

    values = _singular_values(singular_values)
    cutoff = _rcond(rcond)
    if values.size == 0 or values[0] <= 0.0:
        return 0
    retained = (values >= cutoff * values[0]) & (values > 0.0)
    return int(np.count_nonzero(retained))


def noise_amplification_proxy(
    singular_values: Sequence[float] | np.ndarray,
    rcond: float,
) -> float:
    """Return the Frobenius norm of the retained TSVD pseudoinverse."""

    values = _singular_values(singular_values)
    retained = kept_modes_for_rcond(values, rcond)
    if retained == 0:
        return 0.0
    retained_values = values[:retained]
    weakest = float(retained_values[-1])
    scaled_inverse = weakest / retained_values
    return float(math.sqrt(float(np.sum(scaled_inverse**2))) / weakest)


def choose_rcond_from_singular_values(
    singular_values: Sequence[float] | np.ndarray,
    rcond_grid: Sequence[float],
    target_kept_mode_fraction: float = 0.8,
    minimum_kept_modes: int = 1,
) -> float:
    """Choose the largest scanned cutoff satisfying a retained-rank target."""

    values = _singular_values(singular_values)
    grid = tuple(rcond_grid)
    if not grid:
        raise ReconstructionError("rcond_grid must contain at least one value.")
    cutoffs = tuple(_rcond(value) for value in grid)
    fraction = _positive_finite_float(
        target_kept_mode_fraction,
        label="target_kept_mode_fraction",
    )
    if fraction > 1.0:
        raise ReconstructionError(
            "target_kept_mode_fraction must be at most one."
        )
    minimum = _positive_integer(minimum_kept_modes, label="minimum_kept_modes")
    rank = _numerical_rank(values, (values.size, values.size))
    if rank < 1:
        raise ReconstructionError("Cannot choose rcond for a zero-rank matrix.")
    if minimum > rank:
        raise ReconstructionError(
            f"minimum_kept_modes={minimum} exceeds numerical rank={rank}."
        )
    target = max(minimum, int(math.ceil(fraction * rank)))
    candidates = sorted(
        cutoff
        for cutoff in cutoffs
        if kept_modes_for_rcond(values, cutoff) >= target
    )
    if not candidates:
        best = max(kept_modes_for_rcond(values, cutoff) for cutoff in cutoffs)
        raise ReconstructionError(
            "No rcond_grid value satisfies the retained-mode target; "
            f"target_modes={target}, best_kept={best}."
        )
    return float(candidates[-1])


def scan_tsvd_rcond(
    interaction_matrix: InteractionMatrix,
    measurement: MeasurementVector,
    rcond_values: Sequence[float],
    *,
    min_valid_fraction: float,
    min_rank: int,
    max_cached_masks: int = 32,
) -> tuple[ReconstructionEstimate | None, ...]:
    """Explicitly reconstruct one measurement across a TSVD cutoff grid."""

    values = tuple(rcond_values)
    if not values:
        raise ReconstructionError("rcond_values must contain at least one value.")
    results: list[ReconstructionEstimate | None] = []
    for value in values:
        reconstructor = TsvdReconstructor(
            interaction_matrix,
            value,
            min_valid_fraction=min_valid_fraction,
            min_rank=min_rank,
            max_cached_masks=max_cached_masks,
        )
        results.append(reconstructor.reconstruct(measurement))
    return tuple(results)


def _numeric_matrix(value: object, *, label: str) -> np.ndarray:
    if not isinstance(value, np.ndarray):
        raise ReconstructionError(f"{label} must be a numpy.ndarray.")
    if (
        value.ndim != 2
        or value.shape[1] == 0
        or np.issubdtype(value.dtype, np.bool_)
        or not np.issubdtype(value.dtype, np.number)
        or np.issubdtype(value.dtype, np.complexfloating)
    ):
        raise ReconstructionError(
            f"{label} must be a two-dimensional real numeric array with columns."
        )
    return np.asarray(value, dtype=float)


def _numeric_vector(value: object, *, length: int, label: str) -> np.ndarray:
    if not isinstance(value, np.ndarray):
        raise ReconstructionError(f"{label} must be a numpy.ndarray.")
    if (
        value.ndim != 1
        or value.shape != (length,)
        or np.issubdtype(value.dtype, np.bool_)
        or not np.issubdtype(value.dtype, np.number)
        or np.issubdtype(value.dtype, np.complexfloating)
    ):
        raise ReconstructionError(
            f"{label} must be a length-{length} real numeric vector."
        )
    return np.asarray(value, dtype=float)


def _boolean_vector(value: object, *, length: int, label: str) -> np.ndarray:
    if (
        not isinstance(value, np.ndarray)
        or value.dtype != np.dtype(bool)
        or value.ndim != 1
        or value.shape != (length,)
    ):
        raise ReconstructionError(
            f"{label} must be a length-{length} boolean numpy.ndarray."
        )
    return np.asarray(value, dtype=bool)


def _immutable_float_array(value: object) -> np.ndarray:
    contiguous = np.ascontiguousarray(np.array(value, dtype=float, copy=True))
    immutable = np.frombuffer(contiguous.tobytes(order="C"), dtype=float)
    return immutable.reshape(contiguous.shape)


def _immutable_bool_array(value: object) -> np.ndarray:
    contiguous = np.ascontiguousarray(np.array(value, dtype=bool, copy=True))
    immutable = np.frombuffer(contiguous.tobytes(order="C"), dtype=bool)
    return immutable.reshape(contiguous.shape)


def _singular_values(value: Sequence[float] | np.ndarray) -> np.ndarray:
    try:
        values = np.asarray(value, dtype=float).reshape(-1)
    except (TypeError, ValueError) as exc:
        raise ReconstructionError(
            "singular_values must be a real numeric sequence."
        ) from exc
    if not np.all(np.isfinite(values)) or np.any(values < 0.0):
        raise ReconstructionError(
            "singular_values must be finite and non-negative."
        )
    if values.size and np.any(np.diff(values) > 0.0):
        raise ReconstructionError(
            "singular_values must be sorted in non-increasing order."
        )
    return values


def _numerical_rank(
    singular_values: np.ndarray,
    matrix_shape: tuple[int, int],
) -> int:
    if singular_values.size == 0 or singular_values[0] <= 0.0:
        return 0
    tolerance = (
        DEFAULT_NUMERIC_RANK_RTOL
        * max(matrix_shape)
        * float(singular_values[0])
    )
    return int(np.count_nonzero(singular_values > tolerance))


def _machine_singular_cutoff(
    singular_values: np.ndarray,
    matrix_shape: tuple[int, int],
) -> float:
    if singular_values.size == 0:
        return 0.0
    return np.finfo(float).eps * max(matrix_shape) * float(singular_values[0])


def _scaled_l2_norm(values: np.ndarray) -> float:
    """Return an overflow-resistant Euclidean norm for finite values."""

    if values.size == 0:
        return 0.0
    scale = float(np.max(np.abs(values)))
    if scale == 0.0:
        return 0.0
    scaled = values / scale
    return float(scale * math.sqrt(float(np.sum(scaled * scaled))))


def _least_squares_retained(
    singular_values: np.ndarray,
    matrix_shape: tuple[int, int],
    rcond: object,
) -> np.ndarray:
    """Match NumPy's least-squares cutoff while retaining a cached operator."""

    if singular_values.size == 0 or singular_values[0] <= 0.0:
        return np.zeros(singular_values.shape, dtype=bool)
    if rcond is None:
        cutoff = _machine_singular_cutoff(singular_values, matrix_shape)
    else:
        try:
            relative = float(rcond)
        except (TypeError, ValueError) as exc:
            raise ReconstructionError("least-squares rcond must be numeric or None.") from exc
        # NumPy/LAPACK treats non-positive and infinite legacy values as the
        # machine default.  NaN historically retains every positive mode.
        if math.isnan(relative):
            cutoff = 0.0
        elif relative <= 0.0 or math.isinf(relative):
            cutoff = _machine_singular_cutoff(singular_values, matrix_shape)
        else:
            cutoff = relative * float(singular_values[0])
    return singular_values > cutoff


def _rcond(value: object) -> float:
    cutoff = _positive_finite_float(value, label="rcond")
    if cutoff >= 1.0:
        raise ReconstructionError("rcond must be less than one.")
    return cutoff


def _valid_fraction(value: object, *, label: str) -> float:
    fraction = _nonnegative_finite_float(value, label=label)
    if fraction > 1.0:
        raise ReconstructionError(f"{label} must be at most one.")
    return fraction


def _positive_finite_float(value: object, *, label: str) -> float:
    result = _nonnegative_finite_float(value, label=label)
    if result <= 0.0:
        raise ReconstructionError(f"{label} must be positive.")
    return result


def _nonnegative_finite_float(value: object, *, label: str) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise ReconstructionError(f"{label} must be a finite number.")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ReconstructionError(f"{label} must be a finite number.") from exc
    if not math.isfinite(result) or result < 0.0:
        raise ReconstructionError(f"{label} must be finite and non-negative.")
    return result


def _positive_integer(value: object, *, label: str) -> int:
    result = _nonnegative_integer(value, label=label)
    if result < 1:
        raise ReconstructionError(f"{label} must be at least one.")
    return result


def _nonnegative_integer(value: object, *, label: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise ReconstructionError(f"{label} must be a non-negative integer.")
    result = int(value)
    if result < 0:
        raise ReconstructionError(f"{label} must be a non-negative integer.")
    return result


def _nonempty_string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReconstructionError(f"{label} must be a non-empty string.")
    return value
