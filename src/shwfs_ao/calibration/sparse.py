"""Streamed local calibration and a sparse calibrated response.

This module is the scalable counterpart of :mod:`.interaction` for a
finite-support DM (:class:`~shwfs_ao.backends.native.dm_operator.LinearSplineDmOperator`)
and a Shack--Hartmann sensor whose optics declare
``measurement_locality == "lenslet_pixels_v1"``: each lenslet's measurement
depends only on the residual OPD inside that lenslet's own pupil samples.

Grouped local calibration
-------------------------
For every eligible actuator, the *affected lenslets* are the retained lenslets
owning at least one sample of the actuator's illuminated support.  Actuators
are greedily colored, in canonical order, into groups whose affected-lenslet
sets are pairwise disjoint.  One ``+a`` and one ``-a`` measurement per group
then yields, for every actuator of the group, exactly the per-actuator central
difference ``(m(+a) - m(-a)) / 2a`` on its affected lenslets: inside such a
lenslet the group OPD equals the single-actuator OPD sample for sample (all
other group members contribute exact zeros), and lenslets an actuator does
not touch have an exactly zero response.  A single noiseless zero-OPD
reference measurement adds the validity those unaffected lenslets would have
reported.  The result therefore equals the dense per-actuator calibration,
column by column, at a cost of ``2 * n_groups + 1`` sensor calls.

The optimization is restricted to ``include_noise=False``: independent noisy
plus/minus frames differ outside physical probe support, and replacing those
unmeasured noisy derivatives with exact zeros would misstate the calibration.
Noise-on scalable calibration is refused before any measurement.

Sparse response and solver
--------------------------
:class:`SparseInteractionMatrix` stores only calibration-valid rows' nonzeros
(CSR) with the full row layout, units, identities and exclusions, and offers a
forward/adjoint pair.  :class:`SparseLsmrReconstructor` solves the Tikhonov
objective ``min ||A_u x - b_u||^2 + damp^2 ||x||^2`` on the usable rows with
LSMR from ``x0 = 0``; ``damp`` is ``damping_relative`` times the RMS column
norm of the calibration-valid response.  It never forms a dense matrix, an SVD,
or a per-mask factorization cache.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from numbers import Integral, Real
from types import MappingProxyType
from typing import Any, Final, Literal, cast

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import lsmr

from ..core.hashing import component_config_hash
from ..core.protocols import RandomStreams, WavefrontSensor
from ..core.provenance import Provenance
from ..core.types import MeasurementVector, ReconstructionEstimate
from ..dm.model import DeformableMirror
from .interaction import (
    INTERACTION_SIGN_CONVENTION,
    InteractionMatrixError,
    _matrix_unit,
    _measure,
    _scope_stream_reference,
    _scoped_streams,
    _sensor_detector_hash,
    _sensor_geometry_hash,
    _sensor_response_hash,
    _validated_random_streams,
    _validated_sensor_contract,
)


__all__ = (
    "SPARSE_INTERACTION_MATRIX_SCHEMA_ID",
    "GROUPED_LOCAL_STRATEGY",
    "REQUIRED_MEASUREMENT_LOCALITY",
    "DEFAULT_DENSE_RESPONSE_LIMIT_BYTES",
    "ExclusionReason",
    "SparseCalibrationError",
    "LocalDmProbeBasis",
    "SparseInteractionMatrix",
    "SparseLsmrReconstructor",
    "SolverTelemetry",
    "calibrate_sparse_interaction_matrix",
    "probe_groups",
)

SPARSE_INTERACTION_MATRIX_SCHEMA_ID: Final = "shwfs_ao.calibration.SparseInteractionMatrix.v1"
GROUPED_LOCAL_STRATEGY: Final = "grouped_local_noiseless_v1"
REQUIRED_MEASUREMENT_LOCALITY: Final = "lenslet_pixels_v1"
DEFAULT_DENSE_RESPONSE_LIMIT_BYTES: Final = 64 * 1024**2
ExclusionReason = Literal[
    "dead_actuator",
    "stuck_actuator",
    "zero_illuminated_support",
    "no_retained_lenslet_support",
]
_CONVERGED_ISTOP: Final = frozenset({0, 1, 2, 4, 5})
_ISTOP_MEANING: Final = {
    0: "x=0 is the exact solution",
    1: "Ax-b small enough (atol/btol)",
    2: "least-squares solution within atol",
    3: "conlim exceeded",
    4: "Ax-b small within machine precision",
    5: "least-squares solution within machine precision",
    6: "cond(A) exceeded machine precision limit",
    7: "iteration limit reached",
}


class SparseCalibrationError(InteractionMatrixError):
    """Raised when scalable calibration or its sparse response is invalid."""


def _readonly(values: Any, dtype: Any) -> np.ndarray:
    contiguous = np.ascontiguousarray(np.asarray(values, dtype=dtype))
    return np.frombuffer(contiguous.tobytes(order="C"), dtype=contiguous.dtype).reshape(
        contiguous.shape
    )


def _positive_finite(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise SparseCalibrationError(f"{label} must be a positive real number.")
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise SparseCalibrationError(f"{label} must be positive and finite.")
    return number


def _label_map(geometry: object) -> np.ndarray:
    labels = getattr(geometry, "lenslet_label_map", None)
    if callable(labels):
        result = np.asarray(labels(), dtype=np.int64)
    else:
        masks = getattr(geometry, "subaperture_masks", None)
        shape = getattr(geometry, "pupil_shape", None)
        if masks is None or shape is None:
            raise SparseCalibrationError(
                "sensor geometry must expose lenslet_label_map() or subaperture_masks."
            )
        result = np.full(tuple(shape), -1, dtype=np.int64)
        for index, mask in enumerate(masks):
            result[np.asarray(mask, dtype=bool)] = index
    return result


class LocalDmProbeBasis:
    """Every eligible actuator of a scalable DM as a local calibration probe.

    Eligible coordinates are, in canonical layout order, the actuators that
    are neither dead nor stuck, have illuminated support, and (when a lenslet
    label map is given) touch at least one retained lenslet.  Every other
    actuator keeps its physical ID in the DM layout and is listed in
    :attr:`exclusions` with its reason; geometric exclusions are recorded
    separately from hardware faults.  No arbitrary low-order or sampled subset
    is possible.
    """

    def __init__(
        self,
        dm: DeformableMirror,
        *,
        lenslet_label_map: np.ndarray | None = None,
    ) -> None:
        if not isinstance(dm, DeformableMirror) or not dm.is_scalable:
            raise SparseCalibrationError(
                "LocalDmProbeBasis requires a DeformableMirror with a scalable "
                "local spatial operator."
            )
        operator = dm.spatial_operator
        assert operator is not None
        dead = np.asarray(dm.dead_actuator_mask, dtype=bool)
        stuck = np.asarray(dm.stuck_actuator_mask, dtype=bool)
        zero = np.asarray(dm.zero_support_mask, dtype=bool)
        labels = None if lenslet_label_map is None else np.asarray(lenslet_label_map)
        if labels is not None and labels.shape != dm.output_shape:
            raise SparseCalibrationError("lenslet_label_map shape must match the DM grid.")
        exclusions: list[tuple[str, ExclusionReason]] = []
        eligible: list[int] = []
        affected: list[np.ndarray] = []
        for index, identifier in enumerate(dm.actuator_ids):
            if stuck[index]:
                exclusions.append((identifier, "stuck_actuator"))
                continue
            if dead[index]:
                exclusions.append((identifier, "dead_actuator"))
                continue
            if zero[index]:
                exclusions.append((identifier, "zero_illuminated_support"))
                continue
            if labels is not None:
                samples, _ = operator.local_influence(index)
                owners = np.unique(labels.reshape(-1)[samples])
                owners = owners[owners >= 0]
                if owners.size == 0:
                    exclusions.append((identifier, "no_retained_lenslet_support"))
                    continue
                affected.append(_readonly(owners, np.int64))
            eligible.append(index)
        if not eligible:
            raise SparseCalibrationError("no eligible actuators remain for calibration.")
        self._dm = dm
        self._operator = operator
        self._indices = _readonly(np.asarray(eligible, dtype=np.int64), np.int64)
        self._coordinate_ids = tuple(dm.actuator_ids[index] for index in eligible)
        self._exclusions = tuple(exclusions)
        self._affected = tuple(affected) if labels is not None else None
        self._labels_bound = labels is not None
        bounds = np.full(len(eligible), dm.stroke_limit_opd_m, dtype=float)
        self._bounds = _readonly(bounds, float)
        self._config_hash = component_config_hash(
            "local_dm_probe_basis",
            {
                "dm_hash": dm.config_hash,
                "operator_hash": operator.config_hash,
                "coordinate_ids": self._coordinate_ids,
                "full_actuator_indices": self._indices,
                "exclusions": [list(item) for item in self._exclusions],
                "lenslet_coupling_checked": self._labels_bound,
                "affected_lenslets": (
                    None
                    if self._affected is None
                    else [list(map(int, item)) for item in self._affected]
                ),
                "max_abs_amplitude_m": self._bounds,
                "coordinate_kind": "dm_command_opd",
                "coordinate_unit": "m_opd_equivalent",
                "sign_convention": INTERACTION_SIGN_CONVENTION,
            },
        )

    @property
    def size(self) -> int:
        return len(self._coordinate_ids)

    @property
    def coordinate_ids(self) -> tuple[str, ...]:
        return self._coordinate_ids

    @property
    def coordinate_kind(self) -> Literal["dm_command_opd"]:
        return "dm_command_opd"

    @property
    def coordinate_unit(self) -> Literal["m_opd_equivalent"]:
        return "m_opd_equivalent"

    @property
    def max_abs_amplitude_m(self) -> np.ndarray:
        return self._bounds

    @property
    def dm(self) -> DeformableMirror:
        return self._dm

    @property
    def dm_hash(self) -> str:
        return self._dm.config_hash

    @property
    def config_hash(self) -> str:
        return self._config_hash

    @property
    def full_actuator_indices(self) -> np.ndarray:
        return self._indices

    @property
    def exclusions(self) -> tuple[tuple[str, ExclusionReason], ...]:
        """``(actuator_id, reason)`` for every layout actuator not calibrated."""

        return self._exclusions

    @property
    def affected_lenslets(self) -> tuple[np.ndarray, ...]:
        if self._affected is None:
            raise SparseCalibrationError(
                "the basis was built without a lenslet label map."
            )
        return self._affected

    def opd_m_for_coordinate(self, index: int, amplitude_m: float) -> np.ndarray:
        """Single-probe OPD (dense map) for small-system cross-checks."""

        if isinstance(index, bool) or not 0 <= int(index) < self.size:
            raise SparseCalibrationError("coordinate index is out of range.")
        amplitude = float(amplitude_m)
        if abs(amplitude) > float(self._bounds[int(index)]):
            raise SparseCalibrationError("|amplitude_m| exceeds the DM stroke.")
        return self._operator.opd_for_actuators(  # type: ignore[attr-defined]
            self._indices[[int(index)]], np.asarray([amplitude])
        )


def probe_groups(affected_lenslets: Sequence[np.ndarray]) -> tuple[np.ndarray, ...]:
    """Greedy canonical-order coloring into disjoint-affected-lenslet groups.

    Returns, per group, the coordinate indices in canonical order.  The
    coloring is deterministic: coordinate ``k`` joins the first group none of
    whose members touches any of ``k``'s affected lenslets.
    """

    occupied: list[set[int]] = []
    members: list[list[int]] = []
    for coordinate, lenslets in enumerate(affected_lenslets):
        touched = set(int(value) for value in lenslets)
        for group, used in enumerate(occupied):
            if used.isdisjoint(touched):
                used |= touched
                members[group].append(coordinate)
                break
        else:
            occupied.append(set(touched))
            members.append([coordinate])
    return tuple(_readonly(np.asarray(group, dtype=np.int64), np.int64) for group in members)


@dataclass(frozen=True)
class SparseInteractionMatrix:
    """Calibrated sparse response with the full row and coordinate layout.

    Nonzeros are stored in CSR form for calibration-valid rows only;
    calibration-invalid rows are flagged by ``row_valid`` and hold no entries
    (their dense view is NaN, as in :class:`.InteractionMatrix`).  Every other
    identity field has the dense matrix's meaning.  ``exclusions`` lists the
    DM layout actuators that are not coordinates, with reasons.
    """

    data: np.ndarray
    indices: np.ndarray
    indptr: np.ndarray
    row_valid: np.ndarray
    row_ids: tuple[str, ...]
    coordinate_ids: tuple[str, ...]
    coordinate_kind: Literal["dm_command_opd"]
    calibration_amplitude_m: float
    measurement_unit: str
    coordinate_unit: Literal["m_opd_equivalent"]
    matrix_unit: str
    method: Literal["central", "forward"]
    include_noise: bool
    repeat_count: int
    sensor_config_hash: str
    geometry_hash: str
    detector_hash: str | None
    dm_hash: str
    sensor_response_hash: str | None
    strategy: str
    probe_group_count: int
    sensor_call_count: int
    exclusions: tuple[tuple[str, str], ...]
    calibration_hash: str
    provenance: Provenance
    sensor_noisy_response_hash: None = None

    def __post_init__(self) -> None:
        rows = len(self.row_ids)
        columns = len(self.coordinate_ids)
        if rows < 1 or columns < 1:
            raise SparseCalibrationError("row and coordinate layouts must be non-empty.")
        if len(set(self.row_ids)) != rows or len(set(self.coordinate_ids)) != columns:
            raise SparseCalibrationError("row and coordinate IDs must be unique.")
        data = _readonly(self.data, float)
        indices = _readonly(self.indices, np.int64)
        indptr = _readonly(self.indptr, np.int64)
        if indptr.shape != (rows + 1,) or indptr[0] != 0 or np.any(np.diff(indptr) < 0):
            raise SparseCalibrationError("indptr does not describe the row layout.")
        if data.shape != indices.shape or int(indptr[-1]) != data.size:
            raise SparseCalibrationError("CSR data and indices are inconsistent.")
        if indices.size and (indices.min() < 0 or indices.max() >= columns):
            raise SparseCalibrationError("CSR column indices are out of range.")
        if not np.all(np.isfinite(data)):
            raise SparseCalibrationError("stored response values must be finite.")
        row_valid = _readonly(self.row_valid, bool)
        if row_valid.shape != (rows,) or not np.any(row_valid):
            raise SparseCalibrationError("row_valid must flag at least one row.")
        row_counts = np.diff(indptr)
        if np.any(row_counts[~row_valid] != 0):
            raise SparseCalibrationError(
                "calibration-invalid rows must not store response values."
            )
        if self.coordinate_kind != "dm_command_opd" or self.coordinate_unit != (
            "m_opd_equivalent"
        ):
            raise SparseCalibrationError(
                "sparse responses describe DM-actuator coordinates only."
            )
        if self.matrix_unit != _matrix_unit(self.measurement_unit, self.coordinate_unit):
            raise SparseCalibrationError("matrix_unit does not match the units.")
        if self.include_noise is not False or self.repeat_count != 1:
            raise SparseCalibrationError(
                "the scalable calibration is deterministic: include_noise=False "
                "and repeat_count=1."
            )
        if self.sensor_noisy_response_hash is not None:
            raise SparseCalibrationError("a noiseless calibration has no noisy identity.")
        if self.method not in ("central", "forward"):
            raise SparseCalibrationError("method must be central or forward.")
        if not isinstance(self.provenance, Provenance):
            raise SparseCalibrationError("provenance must be a Provenance.")
        _positive_finite(self.calibration_amplitude_m, label="calibration_amplitude_m")
        matrix = sp.csr_matrix((data, indices, indptr), shape=(rows, columns))
        column_norms = np.sqrt(
            np.bincount(indices, weights=data * data, minlength=columns)
        )
        zero_columns = [
            identifier
            for identifier, norm in zip(self.coordinate_ids, column_norms)
            if norm == 0.0
        ]
        if zero_columns:
            raise SparseCalibrationError(
                f"sparse response contains all-zero columns: {zero_columns[:10]}"
                + (" ..." if len(zero_columns) > 10 else "")
            )
        exclusions = tuple((str(a), str(b)) for a, b in self.exclusions)
        object.__setattr__(self, "data", data)
        object.__setattr__(self, "indices", indices)
        object.__setattr__(self, "indptr", indptr)
        object.__setattr__(self, "row_valid", row_valid)
        object.__setattr__(self, "row_ids", tuple(self.row_ids))
        object.__setattr__(self, "coordinate_ids", tuple(self.coordinate_ids))
        object.__setattr__(self, "exclusions", exclusions)
        expected = _sparse_matrix_hash(self)
        if self.calibration_hash != expected:
            raise SparseCalibrationError(
                "calibration_hash does not match the sparse response content."
            )
        object.__setattr__(self, "_csr", matrix)
        object.__setattr__(self, "_column_norms", _readonly(column_norms, float))

    @classmethod
    def create(cls, **fields: Any) -> SparseInteractionMatrix:
        """Construct from content, computing ``calibration_hash`` from it."""

        if "calibration_hash" in fields:
            raise SparseCalibrationError("create() computes calibration_hash itself.")
        staged = object.__new__(cls)
        canonical = dict(fields)
        canonical.setdefault("sensor_noisy_response_hash", None)
        for name in ("data",):
            canonical[name] = np.asarray(canonical[name], dtype=float)
        for name in ("indices", "indptr"):
            canonical[name] = np.asarray(canonical[name], dtype=np.int64)
        canonical["row_valid"] = np.asarray(canonical["row_valid"], dtype=bool)
        canonical["row_ids"] = tuple(canonical["row_ids"])
        canonical["coordinate_ids"] = tuple(canonical["coordinate_ids"])
        canonical["exclusions"] = tuple(
            (str(a), str(b)) for a, b in canonical["exclusions"]
        )
        for key, value in canonical.items():
            object.__setattr__(staged, key, value)
        return cls(calibration_hash=_sparse_matrix_hash(staged), **canonical)

    # Identity ------------------------------------------------------------
    @property
    def config_hash(self) -> str:
        return self.calibration_hash

    @property
    def matrix_hash(self) -> str:
        return self.calibration_hash

    @property
    def shape(self) -> tuple[int, int]:
        return (len(self.row_ids), len(self.coordinate_ids))

    @property
    def nnz(self) -> int:
        return int(self.data.size)

    @property
    def column_norms(self) -> np.ndarray:
        return self.__dict__["_column_norms"]

    @property
    def stored_bytes(self) -> int:
        return int(self.data.nbytes + self.indices.nbytes + self.indptr.nbytes)

    def csr(self) -> sp.csr_matrix:
        """An independent CSR copy of the stored response.

        Changing the copy, including replacing its ``data`` or ``indices``,
        cannot change this matrix, its reconstructions or its hash.
        """

        return self._operator().copy()

    def _operator(self) -> sp.csr_matrix:
        """The internal CSR operator; never handed out."""

        return cast(sp.csr_matrix, self.__dict__["_csr"])

    # Linear operator -----------------------------------------------------
    def forward(self, coordinates_opd_m: np.ndarray) -> np.ndarray:
        values = np.asarray(coordinates_opd_m, dtype=float)
        if values.shape != (self.shape[1],):
            raise SparseCalibrationError("coordinate vector has the wrong length.")
        result = np.asarray(self._operator() @ values, dtype=float)
        result[~self.row_valid] = np.nan
        return result

    def adjoint(self, signal: np.ndarray) -> np.ndarray:
        values = np.asarray(signal, dtype=float)
        if values.shape != (self.shape[0],):
            raise SparseCalibrationError("signal vector has the wrong length.")
        masked = np.where(self.row_valid, values, 0.0)
        if not np.all(np.isfinite(masked)):
            raise SparseCalibrationError("calibration-valid signal rows must be finite.")
        return np.asarray(self._operator().T @ masked, dtype=float)

    def to_dense(
        self,
        *,
        max_bytes: int = DEFAULT_DENSE_RESPONSE_LIMIT_BYTES,
    ) -> np.ndarray:
        """Small-problem dense view (NaN rows where calibration-invalid)."""

        size = self.shape[0] * self.shape[1] * 8
        if size > max_bytes:
            raise SparseCalibrationError(
                f"dense response refused: {size} bytes exceeds the {max_bytes}-byte "
                "compatibility limit."
            )
        dense = np.asarray(self._operator().toarray(), dtype=float)
        dense[~self.row_valid] = np.nan
        return dense

    @property
    def matrix(self) -> np.ndarray:
        """Size-guarded dense compatibility view (see :meth:`to_dense`)."""

        return self.to_dense()

    # Serialization ---------------------------------------------------------
    def to_record(self) -> dict[str, object]:
        return {
            "schema_id": SPARSE_INTERACTION_MATRIX_SCHEMA_ID,
            "data": self.data.tolist(),
            "indices": self.indices.tolist(),
            "indptr": self.indptr.tolist(),
            "row_valid": [bool(value) for value in self.row_valid],
            "row_ids": list(self.row_ids),
            "coordinate_ids": list(self.coordinate_ids),
            "coordinate_kind": self.coordinate_kind,
            "calibration_amplitude_m": self.calibration_amplitude_m,
            "measurement_unit": self.measurement_unit,
            "coordinate_unit": self.coordinate_unit,
            "matrix_unit": self.matrix_unit,
            "method": self.method,
            "include_noise": self.include_noise,
            "repeat_count": self.repeat_count,
            "sensor_config_hash": self.sensor_config_hash,
            "geometry_hash": self.geometry_hash,
            "detector_hash": self.detector_hash,
            "dm_hash": self.dm_hash,
            "sensor_response_hash": self.sensor_response_hash,
            "strategy": self.strategy,
            "probe_group_count": self.probe_group_count,
            "sensor_call_count": self.sensor_call_count,
            "exclusions": [list(item) for item in self.exclusions],
            "calibration_hash": self.calibration_hash,
            "provenance": self.provenance.to_record(),
        }

    @classmethod
    def from_record(cls, record: Mapping[str, object]) -> SparseInteractionMatrix:
        expected = {
            "schema_id", "data", "indices", "indptr", "row_valid", "row_ids",
            "coordinate_ids", "coordinate_kind", "calibration_amplitude_m",
            "measurement_unit", "coordinate_unit", "matrix_unit", "method",
            "include_noise", "repeat_count", "sensor_config_hash", "geometry_hash",
            "detector_hash", "dm_hash", "sensor_response_hash", "strategy",
            "probe_group_count", "sensor_call_count", "exclusions",
            "calibration_hash", "provenance",
        }
        if not isinstance(record, Mapping) or set(record) != expected:
            raise SparseCalibrationError("sparse response record fields differ.")
        if record["schema_id"] != SPARSE_INTERACTION_MATRIX_SCHEMA_ID:
            raise SparseCalibrationError("unsupported sparse response schema_id.")
        provenance = Provenance.from_record(cast(Mapping[str, object], record["provenance"]))
        return cls(
            data=np.asarray(record["data"], dtype=float),
            indices=np.asarray(record["indices"], dtype=np.int64),
            indptr=np.asarray(record["indptr"], dtype=np.int64),
            row_valid=np.asarray(record["row_valid"], dtype=bool),
            row_ids=tuple(cast(Sequence[str], record["row_ids"])),
            coordinate_ids=tuple(cast(Sequence[str], record["coordinate_ids"])),
            coordinate_kind=cast(Any, record["coordinate_kind"]),
            calibration_amplitude_m=cast(float, record["calibration_amplitude_m"]),
            measurement_unit=cast(str, record["measurement_unit"]),
            coordinate_unit=cast(Any, record["coordinate_unit"]),
            matrix_unit=cast(str, record["matrix_unit"]),
            method=cast(Any, record["method"]),
            include_noise=cast(bool, record["include_noise"]),
            repeat_count=cast(int, record["repeat_count"]),
            sensor_config_hash=cast(str, record["sensor_config_hash"]),
            geometry_hash=cast(str, record["geometry_hash"]),
            detector_hash=cast(Any, record["detector_hash"]),
            dm_hash=cast(str, record["dm_hash"]),
            sensor_response_hash=cast(Any, record["sensor_response_hash"]),
            strategy=cast(str, record["strategy"]),
            probe_group_count=cast(int, record["probe_group_count"]),
            sensor_call_count=cast(int, record["sensor_call_count"]),
            exclusions=tuple(
                (str(item[0]), str(item[1]))
                for item in cast(Sequence[Sequence[str]], record["exclusions"])
            ),
            calibration_hash=cast(str, record["calibration_hash"]),
            provenance=provenance,
        )


def _sparse_matrix_hash(matrix: SparseInteractionMatrix) -> str:
    return component_config_hash(
        "calibration.sparse_interaction_matrix",
        {
            "schema_id": SPARSE_INTERACTION_MATRIX_SCHEMA_ID,
            "data": np.asarray(matrix.data, dtype=float),
            "indices": np.asarray(matrix.indices, dtype=np.int64),
            "indptr": np.asarray(matrix.indptr, dtype=np.int64),
            "row_valid": np.asarray(matrix.row_valid, dtype=bool),
            "row_ids": tuple(matrix.row_ids),
            "coordinate_ids": tuple(matrix.coordinate_ids),
            "coordinate_kind": matrix.coordinate_kind,
            "calibration_amplitude_m": float(matrix.calibration_amplitude_m),
            "measurement_unit": matrix.measurement_unit,
            "coordinate_unit": matrix.coordinate_unit,
            "matrix_unit": matrix.matrix_unit,
            "method": matrix.method,
            "include_noise": bool(matrix.include_noise),
            "repeat_count": int(matrix.repeat_count),
            "sensor_config_hash": matrix.sensor_config_hash,
            "geometry_hash": matrix.geometry_hash,
            "detector_hash": matrix.detector_hash,
            "dm_hash": matrix.dm_hash,
            "sensor_response_hash": matrix.sensor_response_hash,
            "strategy": matrix.strategy,
            "probe_group_count": int(matrix.probe_group_count),
            "sensor_call_count": int(matrix.sensor_call_count),
            "exclusions": [list(item) for item in matrix.exclusions],
            "provenance": matrix.provenance.to_record(),
        },
    )


def calibrate_sparse_interaction_matrix(
    probe_basis: LocalDmProbeBasis,
    sensor: WavefrontSensor,
    amplitude_m: float,
    *,
    random_streams: RandomStreams,
    method: Literal["central", "forward"] = "central",
    include_noise: bool = False,
    repeats: int = 1,
) -> SparseInteractionMatrix:
    """Calibrate every eligible actuator with grouped local probes.

    Everything that can be checked without the sensor -- noise policy,
    locality, amplitude bounds, the lenslet coupling of every coordinate and
    the probe grouping -- is validated before the first measurement, so an
    invalid calibration performs zero sensor calls.
    """

    if not isinstance(probe_basis, LocalDmProbeBasis):
        raise SparseCalibrationError("probe_basis must be a LocalDmProbeBasis.")
    if not isinstance(include_noise, (bool, np.bool_)):
        raise SparseCalibrationError("include_noise must be a boolean.")
    if bool(include_noise) or repeats != 1:
        raise SparseCalibrationError(
            "grouped local calibration is restricted to include_noise=False and "
            "repeats=1: noisy plus/minus frames differ outside the probe support, "
            "and those unmeasured derivatives must not be replaced by zeros."
        )
    if method not in ("central", "forward"):
        raise SparseCalibrationError("method must be 'central' or 'forward'.")
    amplitude = _positive_finite(amplitude_m, label="amplitude_m")
    if np.any(amplitude > probe_basis.max_abs_amplitude_m):
        raise SparseCalibrationError("amplitude_m exceeds the DM stroke bound.")
    optics = getattr(sensor, "optics_backend", None)
    locality = getattr(optics, "measurement_locality", None)
    if locality != REQUIRED_MEASUREMENT_LOCALITY:
        raise SparseCalibrationError(
            "grouped local calibration requires optics declaring "
            f"measurement_locality={REQUIRED_MEASUREMENT_LOCALITY!r}; locality is "
            "never assumed for a sensor with possible nonlocal coupling."
        )
    sensor_hash, row_ids = _validated_sensor_contract(sensor)
    root_seed, scheme = _validated_random_streams(random_streams)
    geometry = getattr(sensor, "geometry", None)
    labels = _label_map(geometry)
    subaperture_ids = tuple(getattr(geometry, "subaperture_ids", ()))
    expected_rows = tuple(
        row for identifier in subaperture_ids for row in (f"{identifier}:x", f"{identifier}:y")
    )
    if expected_rows != row_ids:
        raise SparseCalibrationError(
            "sensor rows must be the geometry's S:x, S:y layout for local calibration."
        )
    dm = probe_basis.dm
    if dm.output_shape != labels.shape:
        raise SparseCalibrationError("DM grid and WFS pupil grid differ.")
    operator = dm.spatial_operator
    assert operator is not None
    affected = probe_basis.affected_lenslets
    # The basis's lenslet coupling must be this sensor's: recompute it from the
    # sensor geometry's own sample ownership before any measurement.
    flat_labels = labels.reshape(-1)
    for coordinate, full_index in enumerate(probe_basis.full_actuator_indices):
        samples, _ = operator.local_influence(int(full_index))
        owners = np.unique(flat_labels[samples])
        owners = owners[owners >= 0]
        if not np.array_equal(owners, affected[coordinate]):
            raise SparseCalibrationError(
                "probe basis lenslet coupling does not match the sensor geometry; "
                "build LocalDmProbeBasis with this sensor's lenslet_label_map()."
            )
    groups = probe_groups(affected)
    group_indices = [probe_basis.full_actuator_indices[group] for group in groups]
    shape = dm.output_shape

    geometry_hash = _sensor_geometry_hash(
        sensor, sensor_config_hash=sensor_hash, row_ids=row_ids, probe_shape=shape
    )
    detector_hash = _sensor_detector_hash(sensor)
    response_hash = _sensor_response_hash(sensor)
    grouping_hash = component_config_hash(
        "sparse_calibration_probe_groups",
        {"groups": [list(map(int, group)) for group in groups]},
    )
    context_hash = component_config_hash(
        "sparse_interaction_matrix_calibration_context",
        {
            "probe_basis_hash": probe_basis.config_hash,
            "sensor_config_hash": sensor_hash,
            "geometry_hash": geometry_hash,
            "detector_hash": detector_hash,
            "dm_hash": dm.config_hash,
            "amplitude_m": amplitude,
            "method": method,
            "include_noise": False,
            "repeat_count": 1,
            "strategy": GROUPED_LOCAL_STRATEGY,
            "grouping_hash": grouping_hash,
            "sign_convention": INTERACTION_SIGN_CONVENTION,
        },
    )

    stream_references: list[str] = []
    calls = 0

    def measure(opd: np.ndarray, key: tuple[str | int, ...], label: str):
        nonlocal calls
        scoped = _scoped_streams(random_streams, ("sparse_interaction_matrix", context_hash) + key)
        stream_references.append(_scope_stream_reference(scoped))
        calls += 1
        measurement = _measure(
            sensor,
            opd,
            random_streams=scoped,
            include_noise=False,
            row_ids=row_ids,
            expected_sensor_hash=sensor_hash,
            expected_unit=None,
            sample_label=label,
        )
        values = np.asarray(measurement.vector.values, dtype=float)
        valid = np.asarray(measurement.vector.valid_rows, dtype=bool) & np.isfinite(values)
        return measurement.vector.measurement_unit, values, valid

    unit, reference_values, reference_valid = measure(
        np.zeros(shape, dtype=float), ("reference",), "noise-free zero reference"
    )
    row_valid = reference_valid.copy()
    rows: list[np.ndarray] = []
    columns: list[np.ndarray] = []
    values_out: list[np.ndarray] = []
    for group_number, (group, full_indices) in enumerate(zip(groups, group_indices)):
        plus_opd = operator.opd_for_actuators(  # type: ignore[attr-defined]
            full_indices, np.full(full_indices.size, amplitude)
        )
        unit_plus, plus, plus_valid = measure(
            plus_opd, ("group", group_number, "plus"), f"probe group {group_number} plus"
        )
        if unit_plus != unit:
            raise SparseCalibrationError("measurement unit changed during calibration.")
        if method == "central":
            minus_opd = operator.opd_for_actuators(  # type: ignore[attr-defined]
                full_indices, np.full(full_indices.size, -amplitude)
            )
            unit_minus, minus, minus_valid = measure(
                minus_opd,
                ("group", group_number, "minus"),
                f"probe group {group_number} minus",
            )
            if unit_minus != unit:
                raise SparseCalibrationError("measurement unit changed during calibration.")
            derivative = (plus - minus) / (2.0 * amplitude)
            valid = plus_valid & minus_valid
        else:
            derivative = (plus - reference_values) / amplitude
            valid = plus_valid & reference_valid
        valid &= np.isfinite(derivative)
        row_valid &= valid
        # The declared locality is checked, not assumed: rows of lenslets no
        # probe in this group touches saw exactly the zero-OPD input, so their
        # response must be exactly zero.  Anything else would be silently
        # dropped by the sparse structure.
        touched = np.zeros(len(row_ids), dtype=bool)
        for coordinate in group:
            lenslets = affected[int(coordinate)]
            touched[2 * lenslets] = True
            touched[2 * lenslets + 1] = True
        leaked = valid & ~touched & (derivative != 0.0)
        if np.any(leaked):
            raise SparseCalibrationError(
                f"probe group {group_number} changed {int(np.count_nonzero(leaked))} "
                "rows outside its declared lenslet support; the sensor is not "
                "local and grouped calibration is invalid for it."
            )
        for coordinate in group:
            lenslets = affected[int(coordinate)]
            coordinate_rows = np.concatenate((2 * lenslets, 2 * lenslets + 1))
            coordinate_rows.sort()
            rows.append(coordinate_rows)
            columns.append(np.full(coordinate_rows.size, int(coordinate), dtype=np.int64))
            values_out.append(derivative[coordinate_rows])
    all_rows = np.concatenate(rows)
    all_columns = np.concatenate(columns)
    all_values = np.concatenate(values_out)
    keep = row_valid[all_rows] & (all_values != 0.0)
    if not np.all(np.isfinite(all_values[row_valid[all_rows]])):
        raise SparseCalibrationError("calibration-valid derivatives must be finite.")
    if not np.any(row_valid):
        raise SparseCalibrationError(
            "calibration produced no rows valid across every probe sample."
        )
    coo = sp.coo_matrix(
        (all_values[keep], (all_rows[keep], all_columns[keep])),
        shape=(len(row_ids), probe_basis.size),
    )
    csr = coo.tocsr()
    csr.sort_indices()
    provenance = Provenance(
        source_class="synthetic_assumed",
        source_note=(
            "Sparse interaction response calibrated with grouped local "
            "positive residual-aberration OPD probes (noiseless)."
        ),
        references=tuple(
            [
                f"sign_convention={INTERACTION_SIGN_CONVENTION}",
                f"strategy={GROUPED_LOCAL_STRATEGY}",
                f"probe_basis_hash={probe_basis.config_hash}",
                f"grouping_hash={grouping_hash}",
                f"sensor_config_hash={sensor_hash}",
                f"geometry_hash={geometry_hash}",
                f"detector_hash={detector_hash}",
                f"dm_hash={dm.config_hash}",
                f"random_root_seed={root_seed}",
                f"random_derivation_scheme_id={scheme}",
                f"method={method}",
                "include_noise=False",
                "repeat_count=1",
            ]
            + stream_references
        ),
    )
    fields = dict(
        data=np.asarray(csr.data, dtype=float),
        indices=np.asarray(csr.indices, dtype=np.int64),
        indptr=np.asarray(csr.indptr, dtype=np.int64),
        row_valid=row_valid,
        row_ids=row_ids,
        coordinate_ids=probe_basis.coordinate_ids,
        coordinate_kind="dm_command_opd",
        calibration_amplitude_m=amplitude,
        measurement_unit=unit,
        coordinate_unit="m_opd_equivalent",
        matrix_unit=_matrix_unit(unit, "m_opd_equivalent"),
        method=method,
        include_noise=False,
        repeat_count=1,
        sensor_config_hash=sensor_hash,
        geometry_hash=geometry_hash,
        detector_hash=detector_hash,
        dm_hash=dm.config_hash,
        sensor_response_hash=response_hash,
        strategy=GROUPED_LOCAL_STRATEGY,
        probe_group_count=len(groups),
        sensor_call_count=calls,
        exclusions=probe_basis.exclusions,
        provenance=provenance,
    )
    return SparseInteractionMatrix.create(**fields)


@dataclass(frozen=True)
class SolverTelemetry:
    """One LSMR solve: stopping code, iterations, and residual norms."""

    solve_index: int
    usable_rows: int
    iterations: int
    istop: int
    istop_meaning: str
    converged: bool
    accepted: bool
    residual_norm: float
    normal_residual_norm: float
    solution_norm: float


class SparseLsmrReconstructor:
    """Tikhonov-regularized LSMR reconstruction on the usable rows.

    The objective is ``min ||A_u x - b_u||^2 + damp^2 ||x||^2`` over the
    calibration-valid, runtime-valid, finite rows ``u``, started from
    ``x0 = 0``.  ``damp = damping_relative * rms(column norms)``.  Piston and
    other unseen (null-space) combinations receive no component from the data
    and are suppressed by the damping.  LSMR stops on its ``atol``/``btol``
    tests or at ``max_iterations``; a solve that hits the iteration limit or a
    conditioning limit is rejected (returns ``None``, so the controller adds
    nothing that frame) unless ``nonconverged_policy="accept"``.
    """

    _matrix: SparseInteractionMatrix
    _relative: float
    _damp: float
    _atol: float
    _btol: float
    _max_iterations: int
    _min_valid_fraction: float
    _policy: str
    _telemetry: deque[SolverTelemetry]
    _counts: dict[str, int]
    _max_seen_iterations: int
    _config_hash: str
    _metadata: Mapping[str, object]

    def __init__(
        self,
        interaction_matrix: SparseInteractionMatrix,
        *,
        damping_relative: float,
        atol: float,
        btol: float,
        max_iterations: int,
        min_valid_fraction: float,
        nonconverged_policy: Literal["reject", "accept"] = "reject",
        telemetry_capacity: int = 4096,
    ) -> None:
        if not isinstance(interaction_matrix, SparseInteractionMatrix):
            raise SparseCalibrationError(
                "interaction_matrix must be a SparseInteractionMatrix."
            )
        if isinstance(damping_relative, bool) or not isinstance(damping_relative, Real):
            raise SparseCalibrationError("damping_relative must be a real number.")
        relative = float(damping_relative)
        if not math.isfinite(relative) or relative < 0.0:
            raise SparseCalibrationError("damping_relative must be finite and >= 0.")
        tolerances = {
            "atol": _positive_finite(atol, label="atol"),
            "btol": _positive_finite(btol, label="btol"),
        }
        if isinstance(max_iterations, bool) or not isinstance(max_iterations, Integral):
            raise SparseCalibrationError("max_iterations must be an integer.")
        if int(max_iterations) < 1:
            raise SparseCalibrationError("max_iterations must be >= 1.")
        fraction = float(min_valid_fraction)
        if not math.isfinite(fraction) or not 0.0 <= fraction <= 1.0:
            raise SparseCalibrationError("min_valid_fraction must be in [0, 1].")
        if nonconverged_policy not in ("reject", "accept"):
            raise SparseCalibrationError("nonconverged_policy must be reject or accept.")
        norms = interaction_matrix.column_norms
        rms = float(np.sqrt(np.mean(norms * norms)))
        self._matrix = interaction_matrix
        self._relative = relative
        self._damp = relative * rms
        self._atol = tolerances["atol"]
        self._btol = tolerances["btol"]
        self._max_iterations = int(max_iterations)
        self._min_valid_fraction = fraction
        self._policy = nonconverged_policy
        self._telemetry: deque[SolverTelemetry] = deque(maxlen=int(telemetry_capacity))
        self._counts = {"solves": 0, "converged": 0, "rejected": 0, "iterations": 0}
        self._max_seen_iterations = 0
        self._config_hash = component_config_hash(
            "calibration.sparse_lsmr_tikhonov_reconstructor",
            {
                "matrix_hash": interaction_matrix.calibration_hash,
                "objective": "tikhonov_least_squares",
                "damping_relative": relative,
                "damping_absolute": self._damp,
                "damping_reference": "rms_column_norm_calibration_valid_rows",
                "solver": "scipy.sparse.linalg.lsmr",
                "atol": self._atol,
                "btol": self._btol,
                "conlim": 0.0,
                "max_iterations": self._max_iterations,
                "initial_guess": "zero",
                "min_valid_fraction": fraction,
                "nonconverged_policy": nonconverged_policy,
                "null_space_policy": "tikhonov_damping_minimum_norm",
            },
        )
        self._metadata = MappingProxyType(
            {
                "solver": "lsmr",
                "damping_relative": relative,
                "damping_absolute": self._damp,
                "atol": self._atol,
                "btol": self._btol,
                "max_iterations": self._max_iterations,
                "min_valid_fraction": fraction,
                "nonconverged_policy": nonconverged_policy,
                "initial_guess": "zero",
            }
        )

    @property
    def config_hash(self) -> str:
        return self._config_hash

    @property
    def matrix_hash(self) -> str:
        return self._matrix.calibration_hash

    @property
    def interaction_matrix(self) -> SparseInteractionMatrix:
        return self._matrix

    @property
    def metadata(self) -> Mapping[str, object]:
        return self._metadata

    @property
    def min_valid_fraction(self) -> float:
        return self._min_valid_fraction

    @property
    def damping_absolute(self) -> float:
        return self._damp

    @property
    def telemetry(self) -> tuple[SolverTelemetry, ...]:
        """The most recent solves (bounded ring buffer)."""

        return tuple(self._telemetry)

    @property
    def statistics(self) -> Mapping[str, int]:
        return MappingProxyType(
            {**self._counts, "max_iterations_used": self._max_seen_iterations}
        )

    def reconstruct(self, measurement: MeasurementVector) -> ReconstructionEstimate | None:
        if not isinstance(measurement, MeasurementVector):
            raise SparseCalibrationError("measurement must be a MeasurementVector.")
        matrix = self._matrix
        if measurement.row_ids != matrix.row_ids:
            raise SparseCalibrationError(
                "measurement.row_ids must exactly match the response row layout."
            )
        if measurement.measurement_unit != matrix.measurement_unit:
            raise SparseCalibrationError("measurement unit must match the response.")
        signal = np.asarray(measurement.values, dtype=float)
        usable = (
            np.asarray(matrix.row_valid, dtype=bool)
            & np.asarray(measurement.valid_rows, dtype=bool)
            & np.isfinite(signal)
        )
        usable_count = int(np.count_nonzero(usable))
        valid_count = int(np.count_nonzero(matrix.row_valid))
        if usable_count == 0 or usable_count / valid_count < self._min_valid_fraction:
            return None
        return self._solve(signal, usable, usable_count, columns=None)

    def reconstruct_subset(
        self,
        measurement: MeasurementVector,
        *,
        min_valid_fraction: float,
        min_actuator_coverage: float | None = None,
    ) -> ReconstructionEstimate | None:
        """Reconstruct from the usable rows under a lower coverage threshold.

        The fallback of an opt-in recovery policy (``controller.recovery``):
        the same Tikhonov LSMR solve as :meth:`reconstruct`, with
        ``min_valid_fraction`` in place of this reconstructor's own.  With
        ``min_actuator_coverage`` (the rank guard) only actuators whose usable
        rows keep at least that fraction of their calibrated response energy
        (squared column norm over the calibration-valid rows) are solved for;
        the rest receive an exactly zero increment.  Returns ``None`` when too
        few rows are usable, no actuator qualifies, or the solve is rejected.
        This reconstructor's identity and :meth:`reconstruct` are unchanged.
        """

        if not isinstance(measurement, MeasurementVector):
            raise SparseCalibrationError("measurement must be a MeasurementVector.")
        matrix = self._matrix
        if measurement.row_ids != matrix.row_ids:
            raise SparseCalibrationError(
                "measurement.row_ids must exactly match the response row layout."
            )
        if measurement.measurement_unit != matrix.measurement_unit:
            raise SparseCalibrationError("measurement unit must match the response.")
        fraction = float(min_valid_fraction)
        if not math.isfinite(fraction) or not 0.0 <= fraction <= 1.0:
            raise SparseCalibrationError("min_valid_fraction must be in [0, 1].")
        signal = np.asarray(measurement.values, dtype=float)
        usable = (
            np.asarray(matrix.row_valid, dtype=bool)
            & np.asarray(measurement.valid_rows, dtype=bool)
            & np.isfinite(signal)
        )
        usable_count = int(np.count_nonzero(usable))
        valid_count = int(np.count_nonzero(matrix.row_valid))
        if usable_count == 0 or usable_count / valid_count < fraction:
            return None
        columns: np.ndarray | None = None
        if min_actuator_coverage is not None:
            coverage = float(min_actuator_coverage)
            if not math.isfinite(coverage) or not 0.0 < coverage <= 1.0:
                raise SparseCalibrationError("min_actuator_coverage must be in (0, 1].")
            operator = matrix._operator()
            calibrated = operator[np.flatnonzero(matrix.row_valid)]
            seen = operator[np.flatnonzero(usable)]
            calibrated_energy = np.asarray(calibrated.multiply(calibrated).sum(axis=0)).ravel()
            seen_energy = np.asarray(seen.multiply(seen).sum(axis=0)).ravel()
            qualified = (calibrated_energy > 0.0) & (
                seen_energy >= coverage * calibrated_energy
            )
            if not np.any(qualified):
                return None
            columns = np.flatnonzero(qualified)
        return self._solve(signal, usable, usable_count, columns=columns)

    def _solve(
        self,
        signal: np.ndarray,
        usable: np.ndarray,
        usable_count: int,
        *,
        columns: np.ndarray | None,
    ) -> ReconstructionEstimate | None:
        matrix = self._matrix
        rows = np.flatnonzero(usable)
        submatrix = matrix._operator()[rows]
        if columns is not None:
            submatrix = submatrix[:, columns]
        target = signal[rows]
        output = lsmr(
            submatrix,
            target,
            damp=self._damp,
            atol=self._atol,
            btol=self._btol,
            conlim=0.0,
            maxiter=self._max_iterations,
        )
        solution = np.asarray(output[0], dtype=float)
        istop = int(output[1])
        iterations = int(output[2])
        converged = istop in _CONVERGED_ISTOP and bool(np.all(np.isfinite(solution)))
        accepted = converged or (self._policy == "accept" and np.all(np.isfinite(solution)))
        self._counts["solves"] += 1
        self._counts["iterations"] += iterations
        self._counts["converged"] += int(converged)
        self._max_seen_iterations = max(self._max_seen_iterations, iterations)
        predicted = np.asarray(submatrix @ solution, dtype=float)
        residual = target - predicted
        self._telemetry.append(
            SolverTelemetry(
                solve_index=self._counts["solves"] - 1,
                usable_rows=usable_count,
                iterations=iterations,
                istop=istop,
                istop_meaning=_ISTOP_MEANING.get(istop, "unknown"),
                converged=converged,
                accepted=bool(accepted),
                residual_norm=float(np.linalg.norm(residual)),
                normal_residual_norm=float(output[4]),
                solution_norm=float(np.linalg.norm(solution)),
            )
        )
        if not accepted:
            self._counts["rejected"] += 1
            return None
        full_predicted = np.full(len(matrix.row_ids), np.nan)
        full_residual = np.full(len(matrix.row_ids), np.nan)
        full_predicted[rows] = predicted
        full_residual[rows] = residual
        if columns is not None:
            # Actuators left out of a guarded subset solve hold: zero increment.
            restricted = solution
            solution = np.zeros(len(matrix.coordinate_ids), dtype=float)
            solution[columns] = restricted
        return ReconstructionEstimate(
            delta_coordinates_opd_m=solution,
            coordinate_ids=matrix.coordinate_ids,
            coordinate_kind="dm_command_opd",
            coordinate_unit="m_opd_equivalent",
            measurement_unit=cast(Any, matrix.measurement_unit),
            usable_rows=usable,
            reconstructed_signal=full_predicted,
            residual_signal=full_residual,
            coordinate_norm_m=float(np.linalg.norm(solution)),
            residual_norm=float(np.linalg.norm(residual)),
            kept_modes=None,
            singular_values=np.zeros(0),
            matrix_hash=matrix.calibration_hash,
        )
