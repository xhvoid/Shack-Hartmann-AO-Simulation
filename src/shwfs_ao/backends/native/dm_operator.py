"""Sparse local linear-spline deformable-mirror operator.

This is the scalable counterpart of :class:`~.dm.NativeDmBackend`.  It never
builds an ``(n_actuators, ny, nx)`` influence cube: each actuator's influence
is stored only on its finite support, as one column of a sparse
pixel-by-actuator matrix ``S``, so storage is proportional to the summed
support area rather than ``n_actuators * ny * nx``.

Basis
-----
Actuator ``i`` at ``(x_i, y_i)`` with pitch ``p`` has the separable bilinear
("tent", first-order B-spline) influence

    w_i(x, y) = L((x - x_i) / p) * L((y - y_i) / p),    L(t) = max(0, 1 - |t|),

sampled at pupil-sample centres and set to zero outside the sampled pupil.
Its support is the open square ``|x - x_i| < p, |y - y_i| < p``.  The
normalization is the continuous basis itself: ``w_i = 1`` at the actuator
centre and the sampled map is *not* rescaled to a unit sampled peak (an
actuator centred between samples, or partly outside the pupil, keeps the
same continuous amplitude).  On a full square grid the tents form a partition
of unity, so a uniform command is exact piston.

This is a declared engineering interpretation of the ESO DRM "linear spline"
influence family (separable bilinear tents on a square grid); it is not a
claim about any ESO implementation detail.

Synthesis is ``S @ commands`` and its adjoint is ``S.T @ opd``.  Actuators
whose support has no illuminated pupil sample are classified as
``zero_illuminated_support``; their physical IDs stay in the layout, and
calibration excludes them explicitly.
"""

from __future__ import annotations

import math
from numbers import Real
from typing import Final

import numpy as np
import numpy.typing as npt
import scipy.sparse as sp

from ...core.hashing import component_config_hash


__all__ = (
    "LINEAR_SPLINE_BASIS_ID",
    "LINEAR_SPLINE_NORMALIZATION",
    "DEFAULT_DENSE_INFLUENCE_LIMIT_BYTES",
    "LinearSplineDmOperatorError",
    "LinearSplineDmOperator",
    "linear_spline_weights",
)


LINEAR_SPLINE_BASIS_ID: Final = "separable_bilinear_tent_v1"
LINEAR_SPLINE_NORMALIZATION: Final = "unit_continuous_centre_no_sampled_renormalization"
DEFAULT_DENSE_INFLUENCE_LIMIT_BYTES: Final = 64 * 1024**2
_BACKEND_NAME: Final = "native"
_OPERATOR_KIND: Final = "local_sparse"


class LinearSplineDmOperatorError(ValueError):
    """Raised when the linear-spline operator inputs are inconsistent."""


def linear_spline_weights(offsets_pitch: np.ndarray) -> np.ndarray:
    """``L(t) = max(0, 1 - |t|)`` evaluated at offsets in units of pitch."""

    return np.maximum(0.0, 1.0 - np.abs(np.asarray(offsets_pitch, dtype=float)))


def _separable_axes(x_m: np.ndarray, y_m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray(x_m, dtype=float)
    y = np.asarray(y_m, dtype=float)
    if x.ndim != 2 or x.shape != y.shape:
        raise LinearSplineDmOperatorError("x_m and y_m must be matching 2-D grids.")
    x_axis = x[0, :]
    y_axis = y[:, 0]
    if not (np.array_equal(x, np.broadcast_to(x_axis, x.shape))
            and np.array_equal(y, np.broadcast_to(y_axis[:, None], y.shape))):
        raise LinearSplineDmOperatorError(
            "the linear-spline operator requires a separable x/y sample grid."
        )
    if not (np.all(np.diff(x_axis) > 0.0) and np.all(np.diff(y_axis) > 0.0)):
        raise LinearSplineDmOperatorError("grid axes must be strictly increasing.")
    if not (np.all(np.isfinite(x_axis)) and np.all(np.isfinite(y_axis))):
        raise LinearSplineDmOperatorError("grid axes must be finite.")
    return x_axis, y_axis


def _readonly(values: npt.ArrayLike, dtype: npt.DTypeLike) -> np.ndarray:
    contiguous = np.ascontiguousarray(np.asarray(values, dtype=dtype))
    return np.frombuffer(contiguous.tobytes(order="C"), dtype=contiguous.dtype).reshape(
        contiguous.shape
    )


class LinearSplineDmOperator:
    """Immutable sparse linear-spline DM spatial operator.

    Parameters
    ----------
    x_m, y_m, pupil_mask:
        Separable sampled pupil grid (metres) and its boolean pupil.
    actuator_centers_m:
        ``(n_actuators, 2)`` actuator ``(x, y)`` centres in layout order.
    actuator_pitch_m:
        Square-grid pitch ``p``; the support half-width is one pitch.
    """

    _shape: tuple[int, int]
    _count: int
    _pitch: float
    _x_axis: np.ndarray
    _y_axis: np.ndarray
    _pupil: np.ndarray
    _centers: np.ndarray
    _bounds: np.ndarray
    _csc: sp.csc_matrix
    _csr: sp.csr_matrix
    _support_counts: np.ndarray
    _zero_support: np.ndarray
    _config_hash: str

    def __init__(
        self,
        x_m: np.ndarray,
        y_m: np.ndarray,
        pupil_mask: np.ndarray,
        actuator_centers_m: np.ndarray,
        actuator_pitch_m: float,
    ) -> None:
        x_axis, y_axis = _separable_axes(x_m, y_m)
        pupil = np.asarray(pupil_mask)
        if pupil.dtype != np.dtype(bool) or pupil.shape != (y_axis.size, x_axis.size):
            raise LinearSplineDmOperatorError(
                "pupil_mask must be boolean and match the grid shape."
            )
        if not np.any(pupil):
            raise LinearSplineDmOperatorError("pupil_mask must contain a sample.")
        centers = np.asarray(actuator_centers_m, dtype=float)
        if centers.ndim != 2 or centers.shape[1:] != (2,) or centers.shape[0] < 1:
            raise LinearSplineDmOperatorError(
                "actuator_centers_m must have shape (n_actuators, 2)."
            )
        if not np.all(np.isfinite(centers)):
            raise LinearSplineDmOperatorError("actuator centres must be finite.")
        if isinstance(actuator_pitch_m, bool) or not isinstance(actuator_pitch_m, Real):
            raise LinearSplineDmOperatorError("actuator_pitch_m must be a real number.")
        pitch = float(actuator_pitch_m)
        if not math.isfinite(pitch) or pitch <= 0.0:
            raise LinearSplineDmOperatorError("actuator_pitch_m must be positive.")

        ny, nx = pupil.shape
        count = int(centers.shape[0])
        bounds = np.zeros((count, 4), dtype=np.int64)
        column_indices: list[np.ndarray] = []
        column_values: list[np.ndarray] = []
        nnz = np.zeros(count, dtype=np.int64)
        for index, (cx, cy) in enumerate(centers):
            c0 = int(np.searchsorted(x_axis, cx - pitch, side="right"))
            c1 = int(np.searchsorted(x_axis, cx + pitch, side="left"))
            r0 = int(np.searchsorted(y_axis, cy - pitch, side="right"))
            r1 = int(np.searchsorted(y_axis, cy + pitch, side="left"))
            bounds[index] = (r0, r1, c0, c1)
            if c1 <= c0 or r1 <= r0:
                column_indices.append(np.zeros(0, dtype=np.int64))
                column_values.append(np.zeros(0, dtype=float))
                continue
            wx = linear_spline_weights((x_axis[c0:c1] - cx) / pitch)
            wy = linear_spline_weights((y_axis[r0:r1] - cy) / pitch)
            tile = wy[:, None] * wx[None, :]
            tile = np.where(pupil[r0:r1, c0:c1], tile, 0.0)
            rows, cols = np.nonzero(tile > 0.0)
            flat = (rows + r0) * nx + (cols + c0)
            column_indices.append(flat.astype(np.int64))
            column_values.append(tile[rows, cols])
            nnz[index] = flat.size
        # 32-bit sample indices whenever the grid allows it (they always do
        # below 2**31 samples), halving index storage at full scale.
        index_dtype = np.int32 if ny * nx < 2**31 - 1 else np.int64
        indptr = np.concatenate(([0], np.cumsum(nnz))).astype(index_dtype)
        indices = (
            np.concatenate(column_indices).astype(index_dtype)
            if column_indices
            else np.zeros(0, index_dtype)
        )
        data = np.concatenate(column_values) if column_values else np.zeros(0)
        # CSC with one column per actuator: column i holds actuator i's sampled
        # influence; the CSR copy serves fast synthesis.
        csc = sp.csc_matrix((data, indices, indptr), shape=(ny * nx, count))
        csc.sort_indices()
        self._shape = (int(ny), int(nx))
        self._count = count
        self._pitch = pitch
        self._x_axis = _readonly(x_axis, float)
        self._y_axis = _readonly(y_axis, float)
        self._pupil = _readonly(pupil, bool)
        self._centers = _readonly(centers, float)
        self._bounds = _readonly(bounds, np.int64)
        self._csc = csc
        self._csr = csc.tocsr()
        self._support_counts = _readonly(nnz, np.int64)
        self._zero_support = _readonly(nnz == 0, bool)
        for array in (csc.data, csc.indices, csc.indptr):
            array.flags.writeable = False
        for array in (self._csr.data, self._csr.indices, self._csr.indptr):
            array.flags.writeable = False
        self._config_hash = component_config_hash(
            "native.linear_spline_dm_operator",
            {
                "basis_id": LINEAR_SPLINE_BASIS_ID,
                "normalization": LINEAR_SPLINE_NORMALIZATION,
                "support_half_width_pitch": 1.0,
                "actuator_pitch_m": pitch,
                "actuator_centers_m": self._centers,
                "grid_shape": self._shape,
                "x_axis_m": self._x_axis,
                "y_axis_m": self._y_axis,
                "pupil_mask": self._pupil,
                "support_bounds_rc": self._bounds,
                "csc_indptr": np.asarray(csc.indptr, dtype=np.int64),
                "csc_indices": np.asarray(csc.indices, dtype=np.int64),
                "csc_data": np.asarray(csc.data, dtype=float),
                "zero_illuminated_support": self._zero_support,
                "command_unit": "m_opd_equivalent",
                "output_unit": "m_opd",
                "synthesis": "sparse_linear_sum_no_piston_removal",
            },
        )

    # -- identity and geometry -------------------------------------------------
    @property
    def backend_name(self) -> str:
        return _BACKEND_NAME

    @property
    def spatial_operator_kind(self) -> str:
        return _OPERATOR_KIND

    @property
    def basis_id(self) -> str:
        return LINEAR_SPLINE_BASIS_ID

    @property
    def config_hash(self) -> str:
        return self._config_hash

    @property
    def n_actuators(self) -> int:
        return self._count

    @property
    def output_shape(self) -> tuple[int, int]:
        return self._shape

    @property
    def actuator_pitch_m(self) -> float:
        return self._pitch

    @property
    def support_bounds_rc(self) -> np.ndarray:
        """``(r0, r1, c0, c1)`` sample-index bounds of every actuator's support."""

        return self._bounds

    @property
    def illuminated_support_counts(self) -> np.ndarray:
        """Number of illuminated pupil samples with positive weight per actuator."""

        return self._support_counts

    @property
    def zero_support_mask(self) -> np.ndarray:
        """True for actuators whose support contains no illuminated sample."""

        return self._zero_support

    @property
    def nnz(self) -> int:
        return int(self._csc.nnz)

    @property
    def stored_bytes(self) -> int:
        """Bytes held by the sparse influence storage (both orientations)."""

        return int(
            self._csc.data.nbytes
            + self._csc.indices.nbytes
            + self._csc.indptr.nbytes
            + self._csr.data.nbytes
            + self._csr.indices.nbytes
            + self._csr.indptr.nbytes
            + self._bounds.nbytes
        )

    @property
    def dense_influence_bytes(self) -> int:
        return int(self._count * self._shape[0] * self._shape[1] * 8)

    # -- linear algebra ---------------------------------------------------------
    def opd_from_commands(self, commands_opd_m: np.ndarray) -> np.ndarray:
        """Raw correction OPD ``S @ commands``; zero outside the pupil."""

        commands = np.asarray(commands_opd_m, dtype=float)
        if commands.shape != (self._count,):
            raise LinearSplineDmOperatorError(
                f"commands_opd_m shape {commands.shape} != {(self._count,)}."
            )
        if not np.all(np.isfinite(commands)):
            raise LinearSplineDmOperatorError("commands must be finite.")
        opd = np.asarray(self._csr @ commands, dtype=np.float64).reshape(self._shape)
        return _readonly(opd, float)

    def adjoint(self, opd_m: np.ndarray) -> np.ndarray:
        """``S.T @ opd``: samples outside the pupil are ignored."""

        values = np.asarray(opd_m, dtype=float)
        if values.shape != self._shape:
            raise LinearSplineDmOperatorError(
                f"opd shape {values.shape} != {self._shape}."
            )
        masked = np.where(self._pupil, values, 0.0)
        if not np.all(np.isfinite(masked)):
            raise LinearSplineDmOperatorError("opd must be finite inside the pupil.")
        return np.asarray(self._csc.T @ masked.reshape(-1), dtype=float)

    def local_influence(self, index: int) -> tuple[np.ndarray, np.ndarray]:
        """Flat sample indices and weights of one actuator's illuminated support."""

        if isinstance(index, bool) or not 0 <= int(index) < self._count:
            raise LinearSplineDmOperatorError("actuator index is out of range.")
        start, stop = self._csc.indptr[int(index)], self._csc.indptr[int(index) + 1]
        return (
            _readonly(self._csc.indices[start:stop], np.int64),
            _readonly(self._csc.data[start:stop], float),
        )

    def opd_for_actuators(
        self,
        indices: np.ndarray,
        amplitudes_m: np.ndarray,
    ) -> np.ndarray:
        """OPD of a sparse command touching only ``indices`` (chunked probes)."""

        selected = np.asarray(indices, dtype=np.int64)
        amplitudes = np.asarray(amplitudes_m, dtype=float)
        if selected.ndim != 1 or amplitudes.shape != selected.shape:
            raise LinearSplineDmOperatorError("indices and amplitudes must match.")
        if np.any(selected < 0) or np.any(selected >= self._count):
            raise LinearSplineDmOperatorError("actuator index is out of range.")
        if not np.all(np.isfinite(amplitudes)):
            raise LinearSplineDmOperatorError("amplitudes must be finite.")
        flat = np.zeros(self._shape[0] * self._shape[1], dtype=np.float64)
        sub = self._csc[:, selected]
        flat += np.asarray(sub @ amplitudes, dtype=np.float64).reshape(-1)
        return flat.reshape(self._shape)

    def dense_influence_functions(
        self,
        *,
        max_bytes: int = DEFAULT_DENSE_INFLUENCE_LIMIT_BYTES,
    ) -> np.ndarray:
        """Small-problem compatibility: the dense ``(n, ny, nx)`` influence cube.

        Refused, before allocating, when the cube would exceed ``max_bytes``
        (64 MiB by default).  The scalable path never calls this.
        """

        if self.dense_influence_bytes > max_bytes:
            raise LinearSplineDmOperatorError(
                f"dense influence materialization refused: {self.dense_influence_bytes} "
                f"bytes exceeds the {max_bytes}-byte compatibility limit; use "
                "local_influence() or the sparse operator instead."
            )
        cube = np.asarray(self._csc.T.toarray(), dtype=np.float64)
        return _readonly(cube.reshape((self._count,) + self._shape), float)

    def influence_functions(self) -> np.ndarray:
        """Guarded :meth:`dense_influence_functions` under the DmBackend name."""

        return self.dense_influence_functions()
