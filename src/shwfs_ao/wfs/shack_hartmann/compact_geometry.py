"""Compact Shack--Hartmann lenslet geometry for high-order systems.

:class:`~.geometry.ShackHartmannGeometry` stores one full-pupil boolean mask per
lenslet, ``n_subapertures * ny * nx`` bytes: about 5 GiB for an 84x84 lenslet
array on a 1008-sample pupil.  :class:`CompactShackHartmannGeometry` describes
the same physical partition with one rectangular cell per lenslet (sample-index
bounds) and that cell's local illuminated mask, so its storage is the pupil
grid plus the summed cell area.

The partition rule is exactly :func:`~.geometry.partition_pupil_geometry`'s:
lenslet edges are ``linspace(min, max, n + 1)`` of the sample coordinates,
cells are half-open except that the final row and column also own the
``+x``/``+y`` edge samples, a cell is retained when its illuminated sample
fraction reaches ``min_fill_fraction``, IDs are ``lenslet-r####-c####``, and
the order is column outer, row inner.  The pupil grid must be separable (as
:func:`~shwfs_ao.core.geometry.build_pupil_geometry` makes it), so every cell
is a rectangle of samples.  A pupil size that the lenslet count does not
divide is kept exactly as requested: cells then differ in size by one sample,
as in the dense geometry.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Integral, Real
from typing import Any, ClassVar, Final

import numpy as np

from ...core.geometry import GeometryError, PupilGeometry, build_pupil_geometry
from ...core.hashing import geometry_hash as _geometry_hash
from ...core.hashing import stable_hash
from .geometry import ShackHartmannGeometry, ShackHartmannGeometryError, subaperture_id


__all__ = (
    "DEFAULT_DENSE_MASK_LIMIT_BYTES",
    "CompactShackHartmannGeometry",
    "build_compact_shack_hartmann_geometry",
    "compact_from_pupil_geometry",
    "is_shack_hartmann_geometry",
    "geometries_match",
)


DEFAULT_DENSE_MASK_LIMIT_BYTES: Final = 64 * 1024**2


def _readonly(values: Any, dtype: Any) -> np.ndarray:
    contiguous = np.ascontiguousarray(np.asarray(values, dtype=dtype))
    return np.frombuffer(contiguous.tobytes(order="C"), dtype=contiguous.dtype).reshape(
        contiguous.shape
    )


def _cell_ranges(axis: np.ndarray, edges: np.ndarray) -> list[tuple[int, int]]:
    """Index ranges of half-open cells, with the final cell closed above."""

    ranges = []
    count = edges.size - 1
    for index in range(count):
        start = int(np.searchsorted(axis, edges[index], side="left"))
        if index == count - 1:
            stop = int(np.searchsorted(axis, edges[index + 1], side="right"))
        else:
            stop = int(np.searchsorted(axis, edges[index + 1], side="left"))
        ranges.append((start, stop))
    return ranges


@dataclass(frozen=True)
class CompactShackHartmannGeometry:
    """Lenslet partition stored as per-lenslet cell bounds and local masks.

    ``lenslet_bounds_rc[i] = (r0, r1, c0, c1)`` is lenslet ``i``'s full cell in
    sample indices and ``lenslet_masks[i]`` its illuminated samples inside that
    cell, shape ``(r1 - r0, c1 - c0)``.  Everything else matches the dense
    geometry's public surface (``pupil_mask``, ``x_m``, ``y_m``, IDs, centres,
    ``row_ids``, ``pupil_geometry``); the dense ``subaperture_masks`` view is a
    size-guarded compatibility property.
    """

    __hash_schema_id__: ClassVar[str] = "shwfs_ao.compact_shack_hartmann_geometry.v1"

    telescope_diameter_m: float
    pupil_shape: tuple[int, int]
    n_lenslets_across: int
    min_fill_fraction: float
    pupil_mask: np.ndarray
    x_m: np.ndarray
    y_m: np.ndarray
    lenslet_bounds_rc: np.ndarray
    lenslet_masks: tuple[np.ndarray, ...]
    subaperture_centers_m: np.ndarray
    subaperture_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        try:
            pupil = PupilGeometry(
                telescope_diameter_m=self.telescope_diameter_m,
                pupil_shape=self.pupil_shape,
                pupil_mask=self.pupil_mask,
                x_m=self.x_m,
                y_m=self.y_m,
            )
        except GeometryError as exc:
            raise ShackHartmannGeometryError(str(exc)) from exc
        if isinstance(self.n_lenslets_across, bool) or not isinstance(
            self.n_lenslets_across, Integral
        ) or int(self.n_lenslets_across) < 1:
            raise ShackHartmannGeometryError("n_lenslets_across must be >= 1.")
        if isinstance(self.min_fill_fraction, bool) or not isinstance(
            self.min_fill_fraction, Real
        ) or not 0.0 <= float(self.min_fill_fraction) <= 1.0:
            raise ShackHartmannGeometryError("min_fill_fraction must be in [0, 1].")
        bounds = np.asarray(self.lenslet_bounds_rc, dtype=np.int64)
        count = len(self.subaperture_ids)
        if count < 1:
            raise ShackHartmannGeometryError("at least one lenslet must be retained.")
        if bounds.shape != (count, 4) or len(self.lenslet_masks) != count:
            raise ShackHartmannGeometryError(
                "bounds, local masks, and IDs must describe the same lenslets."
            )
        centers = np.asarray(self.subaperture_centers_m, dtype=float)
        if centers.shape != (count, 2) or not np.all(np.isfinite(centers)):
            raise ShackHartmannGeometryError("subaperture_centers_m must be (n, 2) finite.")
        if len(set(self.subaperture_ids)) != count:
            raise ShackHartmannGeometryError("subaperture_ids must be unique.")
        rows, columns = pupil.pupil_shape
        masks = []
        for index, (mask, (r0, r1, c0, c1)) in enumerate(
            zip(self.lenslet_masks, bounds, strict=True)
        ):
            local = np.asarray(mask)
            if not (0 <= r0 < r1 <= rows and 0 <= c0 < c1 <= columns):
                raise ShackHartmannGeometryError(f"lenslet {index} bounds are invalid.")
            if local.dtype != np.dtype(bool) or local.shape != (r1 - r0, c1 - c0):
                raise ShackHartmannGeometryError(
                    f"lenslet {index} local mask must be boolean and match its cell."
                )
            if not np.any(local):
                raise ShackHartmannGeometryError(f"lenslet {index} has no illuminated sample.")
            if np.any(local & ~pupil.pupil_mask[r0:r1, c0:c1]):
                raise ShackHartmannGeometryError(
                    f"lenslet {index} mask extends outside the pupil."
                )
            masks.append(_readonly(local, bool))
        object.__setattr__(self, "telescope_diameter_m", pupil.telescope_diameter_m)
        object.__setattr__(self, "pupil_shape", pupil.pupil_shape)
        object.__setattr__(self, "n_lenslets_across", int(self.n_lenslets_across))
        object.__setattr__(self, "min_fill_fraction", float(self.min_fill_fraction))
        object.__setattr__(self, "pupil_mask", pupil.pupil_mask)
        object.__setattr__(self, "x_m", pupil.x_m)
        object.__setattr__(self, "y_m", pupil.y_m)
        object.__setattr__(self, "lenslet_bounds_rc", _readonly(bounds, np.int64))
        object.__setattr__(self, "lenslet_masks", tuple(masks))
        object.__setattr__(self, "subaperture_centers_m", _readonly(centers, float))
        object.__setattr__(self, "subaperture_ids", tuple(self.subaperture_ids))
        # Immutable owned state, so the identity is computed once.
        object.__setattr__(self, "_cached_geometry_hash", _geometry_hash(self))

    # Identity --------------------------------------------------------------
    @property
    def geometry_hash(self) -> str:
        return self.__dict__["_cached_geometry_hash"]

    @property
    def config_hash(self) -> str:
        return self.geometry_hash

    @property
    def representation(self) -> str:
        return "compact_cell_bounds_v1"

    # Public geometry surface ----------------------------------------------
    @property
    def n_subapertures(self) -> int:
        return len(self.subaperture_ids)

    @property
    def row_ids(self) -> tuple[str, ...]:
        return tuple(
            row_id
            for identifier in self.subaperture_ids
            for row_id in (f"{identifier}:x", f"{identifier}:y")
        )

    @property
    def pupil_geometry(self) -> PupilGeometry:
        return PupilGeometry(
            telescope_diameter_m=self.telescope_diameter_m,
            pupil_shape=self.pupil_shape,
            pupil_mask=self.pupil_mask,
            x_m=self.x_m,
            y_m=self.y_m,
        )

    @property
    def illuminated_counts(self) -> np.ndarray:
        return np.asarray([int(np.count_nonzero(mask)) for mask in self.lenslet_masks])

    @property
    def dense_mask_bytes(self) -> int:
        return int(self.n_subapertures * self.pupil_shape[0] * self.pupil_shape[1])

    @property
    def subaperture_masks(self) -> tuple[np.ndarray, ...]:
        """Size-guarded dense compatibility view of every lenslet mask."""

        return self.dense_subaperture_masks()

    def dense_subaperture_masks(
        self,
        *,
        max_bytes: int = DEFAULT_DENSE_MASK_LIMIT_BYTES,
    ) -> tuple[np.ndarray, ...]:
        if self.dense_mask_bytes > max_bytes:
            raise ShackHartmannGeometryError(
                f"dense lenslet masks refused: {self.dense_mask_bytes} bytes exceeds "
                f"the {max_bytes}-byte compatibility limit; use lenslet_bounds_rc "
                "and lenslet_masks."
            )
        result = []
        for mask, (r0, r1, c0, c1) in zip(self.lenslet_masks, self.lenslet_bounds_rc):
            full = np.zeros(self.pupil_shape, dtype=bool)
            full[r0:r1, c0:c1] = mask
            result.append(_readonly(full, bool))
        return tuple(result)

    def lenslet_label_map(self) -> np.ndarray:
        """``int32`` map of the retained lenslet index owning each sample, else -1."""

        cached = self.__dict__.get("_cached_label_map")
        if cached is None:
            labels = np.full(self.pupil_shape, -1, dtype=np.int32)
            for index, (mask, (r0, r1, c0, c1)) in enumerate(
                zip(self.lenslet_masks, self.lenslet_bounds_rc)
            ):
                block = labels[r0:r1, c0:c1]
                block[mask] = index
            cached = _readonly(labels, np.int32)
            object.__setattr__(self, "_cached_label_map", cached)
        return cached

    # Value semantics without dense masks ------------------------------------
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CompactShackHartmannGeometry):
            return NotImplemented
        return self.geometry_hash == other.geometry_hash

    def __hash__(self) -> int:
        return hash(self.geometry_hash)

    def __repr__(self) -> str:
        return (
            "CompactShackHartmannGeometry("
            f"diameter={self.telescope_diameter_m} m, pupil={self.pupil_shape}, "
            f"lenslets_across={self.n_lenslets_across}, "
            f"retained={self.n_subapertures}, hash={self.geometry_hash[:12]})"
        )


def compact_from_pupil_geometry(
    pupil_geometry: PupilGeometry,
    *,
    n_lenslets_across: int,
    min_fill_fraction: float,
) -> CompactShackHartmannGeometry:
    """Partition a separable sampled pupil into compact lenslet cells."""

    if not isinstance(pupil_geometry, PupilGeometry):
        raise ShackHartmannGeometryError("pupil_geometry must be a PupilGeometry.")
    if isinstance(n_lenslets_across, bool) or not isinstance(n_lenslets_across, Integral):
        raise ShackHartmannGeometryError("n_lenslets_across must be an integer.")
    count = int(n_lenslets_across)
    if count < 1:
        raise ShackHartmannGeometryError("n_lenslets_across must be >= 1.")
    fill_cut = float(min_fill_fraction)
    if not math.isfinite(fill_cut) or not 0.0 <= fill_cut <= 1.0:
        raise ShackHartmannGeometryError("min_fill_fraction must be in [0, 1].")
    x = np.asarray(pupil_geometry.x_m, dtype=float)
    y = np.asarray(pupil_geometry.y_m, dtype=float)
    x_axis = x[0, :]
    y_axis = y[:, 0]
    if not (
        np.array_equal(x, np.broadcast_to(x_axis, x.shape))
        and np.array_equal(y, np.broadcast_to(y_axis[:, None], y.shape))
        and np.all(np.diff(x_axis) > 0.0)
        and np.all(np.diff(y_axis) > 0.0)
    ):
        raise ShackHartmannGeometryError(
            "compact lenslet geometry requires a separable, increasing sample grid."
        )
    x_edges = np.linspace(float(np.min(x)), float(np.max(x)), count + 1)
    y_edges = np.linspace(float(np.min(y)), float(np.max(y)), count + 1)
    column_ranges = _cell_ranges(x_axis, x_edges)
    row_ranges = _cell_ranges(y_axis, y_edges)
    if sum(stop - start for start, stop in column_ranges) != x_axis.size or sum(
        stop - start for start, stop in row_ranges
    ) != y_axis.size:
        raise ShackHartmannGeometryError(
            "Lenslet cells must assign every pupil sample to exactly one cell."
        )
    pupil = np.asarray(pupil_geometry.pupil_mask, dtype=bool)
    bounds: list[tuple[int, int, int, int]] = []
    masks: list[np.ndarray] = []
    centers: list[tuple[float, float]] = []
    identifiers: list[str] = []
    for column, (c0, c1) in enumerate(column_ranges):
        for row, (r0, r1) in enumerate(row_ranges):
            cell_samples = (r1 - r0) * (c1 - c0)
            if cell_samples == 0:
                continue
            local = pupil[r0:r1, c0:c1]
            illuminated = int(np.count_nonzero(local))
            if illuminated == 0 or illuminated / cell_samples < fill_cut:
                continue
            bounds.append((r0, r1, c0, c1))
            masks.append(np.array(local, dtype=bool, copy=True))
            centers.append(
                (
                    0.5 * (x_edges[column] + x_edges[column + 1]),
                    0.5 * (y_edges[row] + y_edges[row + 1]),
                )
            )
            identifiers.append(subaperture_id(row, column))
    if not masks:
        raise ShackHartmannGeometryError(
            "No illuminated lenslet cells meet min_fill_fraction."
        )
    return CompactShackHartmannGeometry(
        telescope_diameter_m=pupil_geometry.telescope_diameter_m,
        pupil_shape=pupil_geometry.pupil_shape,
        n_lenslets_across=count,
        min_fill_fraction=fill_cut,
        pupil_mask=pupil_geometry.pupil_mask,
        x_m=pupil_geometry.x_m,
        y_m=pupil_geometry.y_m,
        lenslet_bounds_rc=np.asarray(bounds, dtype=np.int64),
        lenslet_masks=tuple(masks),
        subaperture_centers_m=np.asarray(centers, dtype=float),
        subaperture_ids=tuple(identifiers),
    )


def build_compact_shack_hartmann_geometry(
    *,
    telescope_diameter_m: float,
    pupil_shape: tuple[int, int],
    n_lenslets_across: int,
    min_fill_fraction: float,
    central_obstruction_ratio: float = 0.0,
    spider_width_m: float = 0.0,
) -> CompactShackHartmannGeometry:
    """Build the circular pupil and its compact lenslet partition."""

    try:
        pupil = build_pupil_geometry(
            telescope_diameter_m=telescope_diameter_m,
            pupil_shape=pupil_shape,
            central_obstruction_ratio=central_obstruction_ratio,
            spider_width_m=spider_width_m,
        )
    except GeometryError as exc:
        raise ShackHartmannGeometryError(str(exc)) from exc
    return compact_from_pupil_geometry(
        pupil,
        n_lenslets_across=n_lenslets_across,
        min_fill_fraction=min_fill_fraction,
    )


def is_shack_hartmann_geometry(value: object) -> bool:
    """True for either the dense or the compact canonical lenslet geometry."""

    return isinstance(value, (ShackHartmannGeometry, CompactShackHartmannGeometry))


def geometries_match(declared: object, expected: object) -> bool:
    """Whether a backend's declared geometry is the calibration geometry.

    The same object always matches, without rehashing: per-frame ownership
    checks therefore cost nothing on the canonical path.  Two compact
    geometries compare their cached content hashes, and two dense geometries
    their full canonical hashes, exactly as before.
    """

    if declared is expected:
        return True
    if isinstance(declared, CompactShackHartmannGeometry) and isinstance(
        expected, CompactShackHartmannGeometry
    ):
        return declared.geometry_hash == expected.geometry_hash
    if isinstance(declared, ShackHartmannGeometry) and isinstance(
        expected, ShackHartmannGeometry
    ):
        return stable_hash(declared, namespace="shack_hartmann_geometry") == stable_hash(
            expected, namespace="shack_hartmann_geometry"
        )
    return False
