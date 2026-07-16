"""Immutable Shack--Hartmann pupil and lenslet geometry."""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Integral, Real
import re
from typing import ClassVar

import numpy as np

from ...core.geometry import GeometryError, PupilGeometry, build_pupil_geometry
from ...core.hashing import geometry_hash as _geometry_hash
from ...core.provenance import ALLOWED_SOURCE_CLASSES, Provenance
from ...detector.config import DEFAULT_SOURCE_CLASS, SyntheticInstrumentError


__all__ = (
    "DEFAULT_WFS_WAVELENGTH_M",
    "ShwfsGeometryConfig",
    "ShackHartmannGeometryError",
    "ShackHartmannGeometry",
    "build_shack_hartmann_geometry",
    "partition_pupil_geometry",
    "subaperture_id",
    "lenslet_indices_from_id",
)


DEFAULT_WFS_WAVELENGTH_M = 700.0e-9
_SUBAPERTURE_ID_PATTERN = re.compile(r"lenslet-r(?P<row>[0-9]+)-c(?P<column>[0-9]+)")


class ShackHartmannGeometryError(ValueError):
    """Raised when lenslet geometry, identity, or ordering is inconsistent."""


@dataclass(frozen=True)
class ShwfsGeometryConfig:
    """Frozen legacy-compatible configuration for detector-level SH-WFS geometry."""

    telescope_diameter_m: float = 2.0
    n_pupil_pixels: int = 128
    n_lenslets: int = 10
    min_fill_fraction: float = 0.35
    pad_factor: int = 3
    detector_window_px: int | None = 24
    threshold_fraction: float = 0.0
    subtract_minimum: bool = False
    central_obstruction_ratio: float = 0.0
    spider_width_m: float = 0.0
    wfs_wavelength_m: float = DEFAULT_WFS_WAVELENGTH_M
    source_class: str = DEFAULT_SOURCE_CLASS
    source_note: str = "Synthetic 2 m SH-WFS geometry for unit tests and fast-mode demos."

    def __post_init__(self) -> None:
        _legacy_require_positive("telescope_diameter_m", self.telescope_diameter_m)
        if self.n_pupil_pixels < 2:
            raise SyntheticInstrumentError("n_pupil_pixels must be >= 2.")
        if self.n_lenslets < 1:
            raise SyntheticInstrumentError("n_lenslets must be >= 1.")
        if not (0.0 <= self.min_fill_fraction <= 1.0):
            raise SyntheticInstrumentError("min_fill_fraction must be between 0 and 1.")
        if self.pad_factor < 1:
            raise SyntheticInstrumentError("pad_factor must be >= 1.")
        if self.detector_window_px is not None and self.detector_window_px <= 0:
            raise SyntheticInstrumentError("detector_window_px must be positive or None.")
        _legacy_require_nonnegative("threshold_fraction", self.threshold_fraction)
        if not (0.0 <= self.central_obstruction_ratio < 1.0):
            raise SyntheticInstrumentError(
                "central_obstruction_ratio must be >= 0 and < 1."
            )
        _legacy_require_nonnegative("spider_width_m", self.spider_width_m)
        _legacy_require_positive("wfs_wavelength_m", self.wfs_wavelength_m)
        _instrument_provenance(self.source_class, self.source_note)

    @property
    def provenance(self) -> Provenance:
        return _instrument_provenance(self.source_class, self.source_note)


@dataclass(frozen=True)
class ShackHartmannGeometry:
    """Validated SH-WFS geometry with persistent physical lenslet identity.

    Array axis 0 and the encoded ``r`` index are physical y/row; array axis 1
    and the encoded ``c`` index are physical x/column.  The tuple order keeps
    the frozen repository traversal (column outer, row inner), while each ID is
    independent of incidental backend ordering.
    """

    telescope_diameter_m: float
    pupil_shape: tuple[int, int]
    n_lenslets_across: int
    pupil_mask: np.ndarray
    x_m: np.ndarray
    y_m: np.ndarray
    subaperture_masks: tuple[np.ndarray, ...]
    subaperture_centers_m: np.ndarray
    subaperture_ids: tuple[str, ...]

    __hash_schema_id__: ClassVar[str] = "shwfs_ao.shack_hartmann_geometry.v1"

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
        count_across = _positive_integer(
            self.n_lenslets_across,
            label="n_lenslets_across",
        )

        if not isinstance(self.subaperture_masks, tuple):
            raise ShackHartmannGeometryError(
                "subaperture_masks must be an ordered tuple."
            )
        masks = tuple(
            _mask(mask, shape=pupil.pupil_shape, label=f"subaperture_masks[{index}]")
            for index, mask in enumerate(self.subaperture_masks)
        )
        if not masks:
            raise ShackHartmannGeometryError(
                "subaperture_masks must contain at least one retained lenslet."
            )

        try:
            centers = np.asarray(self.subaperture_centers_m, dtype=float)
        except (TypeError, ValueError) as exc:
            raise ShackHartmannGeometryError(
                "subaperture_centers_m must be a finite numeric array."
            ) from exc
        if centers.shape != (len(masks), 2):
            raise ShackHartmannGeometryError(
                "subaperture_centers_m must have shape "
                f"({len(masks)}, 2); got {centers.shape}."
            )
        if not np.all(np.isfinite(centers)):
            raise ShackHartmannGeometryError(
                "subaperture_centers_m must contain only finite values."
            )

        if not isinstance(self.subaperture_ids, tuple):
            raise ShackHartmannGeometryError(
                "subaperture_ids must be an ordered tuple."
            )
        ids = tuple(self.subaperture_ids)
        if len(ids) != len(masks):
            raise ShackHartmannGeometryError(
                "subaperture_ids, masks, and centers must have the same length."
            )
        if len(ids) != len(set(ids)):
            raise ShackHartmannGeometryError(
                "subaperture_ids must not contain duplicate identifiers."
            )
        indices = tuple(
            lenslet_indices_from_id(identifier, n_lenslets_across=count_across)
            for identifier in ids
        )
        if indices != tuple(sorted(indices, key=lambda item: (item[1], item[0]))):
            raise ShackHartmannGeometryError(
                "subaperture_ids must preserve the canonical physical lenslet order "
                "(column outer, row inner)."
            )

        x_edges_m, y_edges_m = _lenslet_edges(pupil, count_across)
        occupied = np.zeros(pupil.pupil_shape, dtype=bool)
        for index, ((row, column), mask, center) in enumerate(
            zip(indices, masks, centers)
        ):
            cell = _lenslet_cell(
                pupil.x_m,
                pupil.y_m,
                x_edges_m,
                y_edges_m,
                row=row,
                column=column,
            )
            expected_mask = cell & pupil.pupil_mask
            if not np.any(mask):
                raise ShackHartmannGeometryError(
                    f"subaperture_masks[{index}] must not be empty."
                )
            if not np.array_equal(mask, expected_mask):
                raise ShackHartmannGeometryError(
                    f"subaperture_masks[{index}] does not match physical lenslet "
                    f"row {row}, column {column}."
                )
            if np.any(mask & occupied):
                raise ShackHartmannGeometryError(
                    "subaperture_masks must not overlap."
                )
            occupied |= mask
            expected_center = (
                0.5 * (x_edges_m[column] + x_edges_m[column + 1]),
                0.5 * (y_edges_m[row] + y_edges_m[row + 1]),
            )
            if not np.allclose(center, expected_center, rtol=0.0, atol=1.0e-12):
                raise ShackHartmannGeometryError(
                    f"subaperture_centers_m[{index}] does not match identifier "
                    f"{ids[index]!r}."
                )

        object.__setattr__(self, "telescope_diameter_m", pupil.telescope_diameter_m)
        object.__setattr__(self, "pupil_shape", pupil.pupil_shape)
        object.__setattr__(self, "n_lenslets_across", count_across)
        object.__setattr__(self, "pupil_mask", pupil.pupil_mask)
        object.__setattr__(self, "x_m", pupil.x_m)
        object.__setattr__(self, "y_m", pupil.y_m)
        object.__setattr__(
            self,
            "subaperture_masks",
            tuple(_readonly_array(mask, dtype=bool) for mask in masks),
        )
        object.__setattr__(
            self,
            "subaperture_centers_m",
            _readonly_array(centers, dtype=float),
        )
        object.__setattr__(self, "subaperture_ids", ids)

    @property
    def geometry_hash(self) -> str:
        """Stable content hash of the serialized geometry contract."""

        return _geometry_hash(self)

    @property
    def config_hash(self) -> str:
        """Protocol-friendly alias for :attr:`geometry_hash`."""

        return self.geometry_hash

    @property
    def n_subapertures(self) -> int:
        return len(self.subaperture_ids)

    @property
    def row_ids(self) -> tuple[str, ...]:
        """Return interleaved ``x, y`` measurement-row identities."""

        return tuple(
            row_id
            for identifier in self.subaperture_ids
            for row_id in (f"{identifier}:x", f"{identifier}:y")
        )

    @property
    def pupil_geometry(self) -> PupilGeometry:
        """Return the shared sampled-pupil view."""

        return PupilGeometry(
            telescope_diameter_m=self.telescope_diameter_m,
            pupil_shape=self.pupil_shape,
            pupil_mask=self.pupil_mask,
            x_m=self.x_m,
            y_m=self.y_m,
        )

    @classmethod
    def from_config(cls, config: ShwfsGeometryConfig) -> "ShackHartmannGeometry":
        """Build the physical geometry represented by a legacy-compatible config."""

        return build_shack_hartmann_geometry(config)


def build_shack_hartmann_geometry(
    config: ShwfsGeometryConfig | None = None,
    *,
    telescope_diameter_m: float = 2.0,
    pupil_shape: tuple[int, int] = (128, 128),
    n_lenslets_across: int = 10,
    min_fill_fraction: float = 0.35,
    central_obstruction_ratio: float = 0.0,
    spider_width_m: float = 0.0,
) -> ShackHartmannGeometry:
    """Build and partition a circular telescope pupil into retained lenslets."""

    if config is not None:
        if not isinstance(config, ShwfsGeometryConfig):
            raise ShackHartmannGeometryError(
                "config must be a ShwfsGeometryConfig or None."
            )
        telescope_diameter_m = config.telescope_diameter_m
        pupil_shape = (config.n_pupil_pixels, config.n_pupil_pixels)
        n_lenslets_across = config.n_lenslets
        min_fill_fraction = config.min_fill_fraction
        central_obstruction_ratio = config.central_obstruction_ratio
        spider_width_m = config.spider_width_m

    try:
        pupil = build_pupil_geometry(
            telescope_diameter_m=telescope_diameter_m,
            pupil_shape=pupil_shape,
            central_obstruction_ratio=central_obstruction_ratio,
            spider_width_m=spider_width_m,
        )
    except GeometryError as exc:
        raise ShackHartmannGeometryError(str(exc)) from exc
    return partition_pupil_geometry(
        pupil,
        n_lenslets_across=n_lenslets_across,
        min_fill_fraction=min_fill_fraction,
    )


def partition_pupil_geometry(
    pupil_geometry: PupilGeometry,
    *,
    n_lenslets_across: int,
    min_fill_fraction: float,
) -> ShackHartmannGeometry:
    """Retain lenslet cells whose illuminated sampled-area fraction passes a cut."""

    if not isinstance(pupil_geometry, PupilGeometry):
        raise ShackHartmannGeometryError(
            "pupil_geometry must be a PupilGeometry."
        )
    count_across = _positive_integer(
        n_lenslets_across,
        label="n_lenslets_across",
    )
    fill_cut = _finite_float(min_fill_fraction, label="min_fill_fraction")
    if not 0.0 <= fill_cut <= 1.0:
        raise ShackHartmannGeometryError(
            "min_fill_fraction must be in [0, 1]."
        )
    x_edges_m, y_edges_m = _lenslet_edges(pupil_geometry, count_across)

    masks: list[np.ndarray] = []
    centers: list[tuple[float, float]] = []
    identifiers: list[str] = []
    # Deliberately retain the frozen repository traversal: x/column outer,
    # y/row inner.  Physical indices in the ID make this backend-independent.
    for column in range(count_across):
        for row in range(count_across):
            cell = _lenslet_cell(
                pupil_geometry.x_m,
                pupil_geometry.y_m,
                x_edges_m,
                y_edges_m,
                row=row,
                column=column,
            )
            cell_samples = int(np.count_nonzero(cell))
            if cell_samples == 0:
                continue
            valid = cell & pupil_geometry.pupil_mask
            illuminated_samples = int(np.count_nonzero(valid))
            fill_fraction = illuminated_samples / cell_samples
            if illuminated_samples == 0 or fill_fraction < fill_cut:
                continue
            masks.append(valid)
            centers.append(
                (
                    0.5 * (x_edges_m[column] + x_edges_m[column + 1]),
                    0.5 * (y_edges_m[row] + y_edges_m[row + 1]),
                )
            )
            identifiers.append(subaperture_id(row, column))

    if not masks:
        raise ShackHartmannGeometryError(
            "No illuminated lenslet cells meet min_fill_fraction."
        )
    return ShackHartmannGeometry(
        telescope_diameter_m=pupil_geometry.telescope_diameter_m,
        pupil_shape=pupil_geometry.pupil_shape,
        n_lenslets_across=count_across,
        pupil_mask=pupil_geometry.pupil_mask,
        x_m=pupil_geometry.x_m,
        y_m=pupil_geometry.y_m,
        subaperture_masks=tuple(masks),
        subaperture_centers_m=np.asarray(centers, dtype=float),
        subaperture_ids=tuple(identifiers),
    )


def subaperture_id(row: int, column: int) -> str:
    """Create a stable ID from non-negative physical lenslet indices."""

    row_index = _nonnegative_integer(row, label="row")
    column_index = _nonnegative_integer(column, label="column")
    return f"lenslet-r{row_index:04d}-c{column_index:04d}"


def lenslet_indices_from_id(
    identifier: str,
    *,
    n_lenslets_across: int | None = None,
) -> tuple[int, int]:
    """Return ``(row, column)`` encoded by a canonical subaperture ID."""

    if not isinstance(identifier, str):
        raise ShackHartmannGeometryError(
            "Each subaperture ID must be a canonical non-empty string."
        )
    match = _SUBAPERTURE_ID_PATTERN.fullmatch(identifier)
    if match is None:
        raise ShackHartmannGeometryError(
            f"Invalid subaperture ID {identifier!r}; expected "
            "'lenslet-r####-c####'."
        )
    row = int(match.group("row"))
    column = int(match.group("column"))
    if identifier != subaperture_id(row, column):
        raise ShackHartmannGeometryError(
            f"Subaperture ID {identifier!r} is not in canonical padded form."
        )
    if n_lenslets_across is not None:
        count = _positive_integer(
            n_lenslets_across,
            label="n_lenslets_across",
        )
        if row >= count or column >= count:
            raise ShackHartmannGeometryError(
                f"Subaperture ID {identifier!r} lies outside a {count}x{count} grid."
            )
    return row, column


def _lenslet_edges(
    pupil: PupilGeometry,
    count_across: int,
) -> tuple[np.ndarray, np.ndarray]:
    return (
        np.linspace(float(np.min(pupil.x_m)), float(np.max(pupil.x_m)), count_across + 1),
        np.linspace(float(np.min(pupil.y_m)), float(np.max(pupil.y_m)), count_across + 1),
    )


def _lenslet_cell(
    x_m: np.ndarray,
    y_m: np.ndarray,
    x_edges_m: np.ndarray,
    y_edges_m: np.ndarray,
    *,
    row: int,
    column: int,
) -> np.ndarray:
    return (
        (x_m >= x_edges_m[column])
        & (x_m < x_edges_m[column + 1])
        & (y_m >= y_edges_m[row])
        & (y_m < y_edges_m[row + 1])
    )


def _positive_integer(value: object, *, label: str) -> int:
    result = _nonnegative_integer(value, label=label)
    if result < 1:
        raise ShackHartmannGeometryError(f"{label} must be at least 1.")
    return result


def _nonnegative_integer(value: object, *, label: str) -> int:
    if not isinstance(value, Integral) or isinstance(value, (bool, np.bool_)):
        raise ShackHartmannGeometryError(f"{label} must be an integer.")
    result = int(value)
    if result < 0:
        raise ShackHartmannGeometryError(f"{label} must be non-negative.")
    return result


def _finite_float(value: object, *, label: str) -> float:
    if not isinstance(value, Real) or isinstance(value, (bool, np.bool_)):
        raise ShackHartmannGeometryError(f"{label} must be a finite real number.")
    result = float(value)
    if not math.isfinite(result):
        raise ShackHartmannGeometryError(f"{label} must be a finite real number.")
    return result


def _mask(
    value: object,
    *,
    shape: tuple[int, int],
    label: str,
) -> np.ndarray:
    array = np.asarray(value)
    if array.dtype.kind != "b":
        raise ShackHartmannGeometryError(f"{label} must be a boolean array.")
    if array.shape != shape:
        raise ShackHartmannGeometryError(
            f"{label} shape {array.shape} does not match pupil_shape {shape}."
        )
    return array.astype(bool, copy=False)


def _readonly_array(values: object, *, dtype: object) -> np.ndarray:
    contiguous = np.ascontiguousarray(values, dtype=dtype)
    return np.frombuffer(contiguous.tobytes(order="C"), dtype=contiguous.dtype).reshape(
        contiguous.shape
    )


def _legacy_require_positive(field_name: str, value: float) -> None:
    _legacy_require_finite(field_name, value)
    if value <= 0:
        raise SyntheticInstrumentError(
            f"{field_name} must be positive; got {value!r}."
        )


def _legacy_require_nonnegative(field_name: str, value: float) -> None:
    _legacy_require_finite(field_name, value)
    if value < 0:
        raise SyntheticInstrumentError(
            f"{field_name} must be non-negative; got {value!r}."
        )


def _legacy_require_finite(field_name: str, value: float) -> None:
    if not math.isfinite(float(value)):
        raise SyntheticInstrumentError(
            f"{field_name} must be finite; got {value!r}."
        )


def _instrument_provenance(source_class: str, source_note: str) -> Provenance:
    try:
        return Provenance(source_class=source_class, source_note=str(source_note))
    except (TypeError, ValueError) as exc:
        if source_class not in ALLOWED_SOURCE_CLASSES:
            raise SyntheticInstrumentError(
                f"source_class={source_class!r} is not in the permitted taxonomy "
                f"{sorted(ALLOWED_SOURCE_CLASSES)}."
            ) from exc
        raise SyntheticInstrumentError(
            "source_note must be a non-empty string."
        ) from exc
