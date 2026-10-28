"""Declared detector-pixel layout with immutable physical pixel identities.

The physical camera path (``shwfs_ao.detector.physical_camera.v1``) ties every
persistent map and calibration product to a physical pixel, not to a window
position.  :class:`DetectorLayout` declares that mapping for the synthetic
scheme ``isolated_lenslet_blocks.v1``:

* lenslet ``lenslet-rRRRR-cCCCC`` owns a square block of
  ``block_px = window_px + 2 * guard_px`` pixels per side;
* the block's detector origin is ``(R * pitch_px, C * pitch_px)`` with
  ``pitch_px = block_px``, so blocks tile a
  ``(n * pitch_px) x (n * pitch_px)`` synthetic detector without overlap;
* pixel ``(row, column)`` of that detector has the immutable ID
  ``row * detector_columns + column``;
* the centroid window is the central ``window_px`` square of the block, and
  the guard ring around it exists only for electronic coupling and charge
  diffusion to act on real neighbouring pixels.

Blocks never overlap, so a physical pixel belongs to exactly one lenslet and
overlap is impossible by construction.  Light from a neighbouring lenslet is
not modelled in a block (declared limitation).  A layout depends on the
nominal lenslet grid, not on which lenslets are retained: dropping a lenslet
does not move or relabel any other pixel.
"""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Integral
from typing import Literal

import numpy as np

from ..core.hashing import component_config_hash


__all__ = (
    "LAYOUT_SCHEMES",
    "DetectorLayoutError",
    "DetectorLayout",
    "lenslet_block_indices",
)


LayoutScheme = Literal["isolated_lenslet_blocks.v1"]
LAYOUT_SCHEMES: tuple[str, ...] = ("isolated_lenslet_blocks.v1",)


class DetectorLayoutError(ValueError):
    """Raised when a detector layout or a lenslet identity is invalid."""


def lenslet_block_indices(subaperture_id: str) -> tuple[int, int]:
    """Return the nominal ``(row, column)`` lenslet indices of a stable ID."""

    if not isinstance(subaperture_id, str):
        raise DetectorLayoutError("subaperture_id must be a string.")
    parts = subaperture_id.split("-")
    if (
        len(parts) != 3
        or parts[0] != "lenslet"
        or not parts[1].startswith("r")
        or not parts[2].startswith("c")
        or not parts[1][1:].isdigit()
        or not parts[2][1:].isdigit()
    ):
        raise DetectorLayoutError(
            f"subaperture_id {subaperture_id!r} is not a stable "
            "'lenslet-rRRRR-cCCCC' identity; the physical layout cannot place it."
        )
    return int(parts[1][1:]), int(parts[2][1:])


@dataclass(frozen=True)
class DetectorLayout:
    """Synthetic non-overlapping lenslet-block layout of a SH detector."""

    __hash_schema_id__ = "shwfs_ao.detector.DetectorLayout.v1"

    scheme: LayoutScheme
    lenslets_across: int
    window_px: int
    guard_px: int = 0

    def __post_init__(self) -> None:
        if self.scheme not in LAYOUT_SCHEMES:
            raise DetectorLayoutError(
                f"scheme must be one of {list(LAYOUT_SCHEMES)}; got {self.scheme!r}."
            )
        lenslets = _integer(self.lenslets_across, "lenslets_across", minimum=1)
        window = _integer(self.window_px, "window_px", minimum=1)
        guard = _integer(self.guard_px, "guard_px", minimum=0)
        object.__setattr__(self, "lenslets_across", lenslets)
        object.__setattr__(self, "window_px", window)
        object.__setattr__(self, "guard_px", guard)

    @property
    def block_px(self) -> int:
        return self.window_px + 2 * self.guard_px

    @property
    def pitch_px(self) -> int:
        return self.block_px

    @property
    def detector_shape_px(self) -> tuple[int, int]:
        side = self.lenslets_across * self.pitch_px
        return (side, side)

    @property
    def window_slice(self) -> tuple[slice, slice]:
        """The centroid window inside a block, as ``(rows, columns)`` slices."""

        start = self.guard_px
        stop = self.guard_px + self.window_px
        return (slice(start, stop), slice(start, stop))

    @property
    def layout_hash(self) -> str:
        return component_config_hash("detector_layout", self)

    def block_origin_px(self, subaperture_id: str) -> tuple[int, int]:
        """Detector ``(row, column)`` of the block's first pixel."""

        row, column = lenslet_block_indices(subaperture_id)
        if row >= self.lenslets_across or column >= self.lenslets_across:
            raise DetectorLayoutError(
                f"{subaperture_id!r} lies outside the declared "
                f"{self.lenslets_across} x {self.lenslets_across} lenslet grid."
            )
        return (row * self.pitch_px, column * self.pitch_px)

    def pixel_ids(self, subaperture_id: str) -> np.ndarray:
        """Immutable global pixel IDs of the block, shape ``(block, block)``."""

        row0, column0 = self.block_origin_px(subaperture_id)
        columns = self.detector_shape_px[1]
        rows = np.arange(row0, row0 + self.block_px, dtype=np.int64)[:, None]
        cols = np.arange(column0, column0 + self.block_px, dtype=np.int64)[None, :]
        ids = rows * columns + cols
        ids.flags.writeable = False
        return ids

    def validate_subapertures(self, subaperture_ids: tuple[str, ...]) -> None:
        """Reject IDs that are malformed, outside the grid, or duplicated."""

        seen: set[tuple[int, int]] = set()
        for subaperture_id in subaperture_ids:
            indices = lenslet_block_indices(subaperture_id)
            self.block_origin_px(subaperture_id)
            if indices in seen:
                raise DetectorLayoutError(
                    f"two subapertures map to lenslet block {indices}; physical "
                    "pixels would be shared, which this layout rejects."
                )
            seen.add(indices)


def _integer(value: object, label: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise DetectorLayoutError(f"{label} must be an integer.")
    result = int(value)
    if result < minimum:
        raise DetectorLayoutError(f"{label} must be at least {minimum}.")
    return result
