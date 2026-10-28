"""Persistent physical-camera pixel maps tied to immutable pixel identities.

Every map of the physical camera path is drawn from the registered
``detector.realization`` domain with a key that names the map, the layout,
the map-generating settings, and the lenslet *block* coordinates.  A pixel's
value therefore depends only on its physical identity: it is the same for
every frame, for reference and interaction calibration, on the dense and the
batched path, for any lenslet order or batch size, and whether or not other
lenslets are retained.  Distinct pixels never alias one repeated window map.

Maps (each drawn only when its generating setting is non-zero; otherwise the
neutral value is implied and nothing is stored or drawn):

``prnu``
    optical photoresponse, ``max(N(1, prnu_rms), 0)``; multiplies source and
    sky photoelectron expectations only.
``dead``
    zero optical photoresponse where ``U < dead_pixel_fraction``; a dead
    pixel keeps its dark current, bias, offset and read noise.
``hot``
    pixels where ``U < hot_pixel_fraction``; their dark current is
    ``hot_pixel_dark_e_per_s`` instead of the uniform ``dark_e_per_s``.
``offset_adu``
    fixed-pattern offset ``offset_map_rms_adu * N(0, 1)``.
``gain_multiplier``
    CMOS dimensionless relative conversion-gain multiplier
    ``1 + cmos_gain_map_rms * clip(N(0, 1), -4, 4)``; the absolute conversion
    gain of a pixel is ``conversion_gain_e_per_adu * gain_multiplier``.
``read_noise_multiplier``
    CMOS lognormal read-noise multiplier ``exp(sigma_ln * N(0, 1))`` with
    median one; a pixel's read noise is ``read_noise_e * multiplier``.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any

import numpy as np

from ..core.hashing import stable_hash
from ..core.protocols import RandomStreams
from .camera import CameraConfig, CameraConfigError
from .layout import DetectorLayout, lenslet_block_indices


__all__ = (
    "CAMERA_MAPS_SCHEMA",
    "CameraMapsError",
    "CameraMaps",
)


CAMERA_MAPS_SCHEMA = "shwfs_ao.detector.PhysicalCameraMaps.v1"
_REALIZATION_DOMAIN = "detector.realization"
_GAIN_MAP_CLIP_SIGMA = 4.0


class CameraMapsError(ValueError):
    """Raised when persistent camera maps cannot be built or are inconsistent."""


def _readonly(values: np.ndarray) -> np.ndarray:
    contiguous = np.ascontiguousarray(values)
    result = np.frombuffer(contiguous.tobytes(order="C"), dtype=contiguous.dtype)
    return result.reshape(contiguous.shape)


@dataclass(frozen=True)
class CameraMaps:
    """Immutable persistent maps for the retained lenslet blocks, in order."""

    layout: DetectorLayout
    maps_config_hash: str
    subaperture_ids: tuple[str, ...]
    root_seed: int
    realization_index: int
    prnu: np.ndarray | None
    dead: np.ndarray | None
    hot: np.ndarray | None
    offset_adu: np.ndarray | None
    gain_multiplier: np.ndarray | None
    read_noise_multiplier: np.ndarray | None
    content_sha256: str
    realization_hash: str

    @property
    def block_shape(self) -> tuple[int, int]:
        return (self.layout.block_px, self.layout.block_px)

    @property
    def shape(self) -> tuple[int, int, int]:
        return (len(self.subaperture_ids), *self.block_shape)

    def optical_response(self) -> np.ndarray:
        """PRNU times live-pixel mask: the optical photoresponse per pixel."""

        response = np.ones(self.shape) if self.prnu is None else np.array(self.prnu)
        if self.dead is not None:
            response[self.dead] = 0.0
        return response

    def dark_rate_e_per_s(self, camera: CameraConfig) -> np.ndarray:
        """Per-pixel dark current: uniform, with hot pixels replaced."""

        rate = np.full(self.shape, float(camera.dark_e_per_s))
        if self.hot is not None:
            rate[self.hot] = float(camera.hot_pixel_dark_e_per_s)
        return rate

    def conversion_gain_e_per_adu(self, camera: CameraConfig) -> np.ndarray | float:
        """Absolute per-pixel conversion gain (output e-/ADU), applied once."""

        if self.gain_multiplier is None:
            return float(camera.conversion_gain_e_per_adu)
        return float(camera.conversion_gain_e_per_adu) * self.gain_multiplier

    def read_noise_e(self, camera: CameraConfig) -> np.ndarray | float:
        """Output-referred read noise per pixel (scalar when no CMOS map)."""

        if self.read_noise_multiplier is None:
            return float(camera.read_noise_e)
        return float(camera.read_noise_e) * self.read_noise_multiplier

    def offsets_adu(self) -> np.ndarray | float:
        return 0.0 if self.offset_adu is None else self.offset_adu

    def subset(self, indices: np.ndarray) -> dict[str, np.ndarray | None]:
        """Map arrays restricted to the given retained-lenslet indices."""

        return {
            name: (None if values is None else values[indices])
            for name, values in (
                ("prnu", self.prnu),
                ("dead", self.dead),
                ("hot", self.hot),
                ("offset_adu", self.offset_adu),
                ("gain_multiplier", self.gain_multiplier),
                ("read_noise_multiplier", self.read_noise_multiplier),
            )
        }

    @classmethod
    def create(
        cls,
        camera: CameraConfig,
        layout: DetectorLayout,
        subaperture_ids: tuple[str, ...],
        *,
        random_streams: RandomStreams,
        realization_index: int = 0,
    ) -> CameraMaps:
        """Draw every enabled map block by block from ``detector.realization``."""

        if not isinstance(camera, CameraConfig):
            raise CameraMapsError("camera must be a CameraConfig.")
        if not isinstance(layout, DetectorLayout):
            raise CameraMapsError("layout must be a DetectorLayout.")
        ids = tuple(subaperture_ids)
        if not ids:
            raise CameraMapsError("at least one subaperture is required.")
        layout.validate_subapertures(ids)
        if type(realization_index) is not int or realization_index < 0:
            raise CameraMapsError("realization_index must be a non-negative integer.")
        root_seed = random_streams.root_seed
        maps_hash = camera.maps_config_hash
        layout_hash = layout.layout_hash
        shape = (layout.block_px, layout.block_px)
        n = len(ids)

        def draw(name: str, sampler: Any) -> np.ndarray:
            values = None
            for index, subaperture_id in enumerate(ids):
                row, column = lenslet_block_indices(subaperture_id)
                generator = random_streams.keyed_generator(
                    _REALIZATION_DOMAIN,
                    key=(
                        CAMERA_MAPS_SCHEMA,
                        maps_hash,
                        layout_hash,
                        name,
                        row,
                        column,
                        realization_index,
                    ),
                )
                block = sampler(generator)
                if values is None:
                    values = np.empty((n, *shape), dtype=block.dtype)
                values[index] = block
            assert values is not None
            return values

        prnu = dead = hot = offset = gain = read = None
        if camera.prnu_rms > 0.0:
            prnu = np.maximum(
                draw("prnu", lambda g: g.normal(1.0, camera.prnu_rms, size=shape)),
                0.0,
            )
        if camera.dead_pixel_fraction > 0.0:
            dead = draw("dead", lambda g: g.random(shape) < camera.dead_pixel_fraction)
        if camera.hot_pixel_fraction > 0.0:
            hot = draw("hot", lambda g: g.random(shape) < camera.hot_pixel_fraction)
        if camera.offset_map_rms_adu > 0.0:
            offset = camera.offset_map_rms_adu * draw(
                "offset", lambda g: g.standard_normal(shape)
            )
        if camera.cmos_gain_map_rms > 0.0:
            gain = 1.0 + camera.cmos_gain_map_rms * np.clip(
                draw("gain", lambda g: g.standard_normal(shape)),
                -_GAIN_MAP_CLIP_SIGMA,
                _GAIN_MAP_CLIP_SIGMA,
            )
        if camera.cmos_read_noise_lognormal_sigma > 0.0:
            read = np.exp(
                camera.cmos_read_noise_lognormal_sigma
                * draw("read_noise", lambda g: g.standard_normal(shape))
            )

        digest = hashlib.sha256()
        for name, values in (
            ("prnu", prnu),
            ("dead", dead),
            ("hot", hot),
            ("offset", offset),
            ("gain", gain),
            ("read_noise", read),
        ):
            digest.update(name.encode("ascii"))
            if values is None:
                digest.update(b"none")
            else:
                array = np.ascontiguousarray(values)
                digest.update(str(array.dtype).encode("ascii"))
                digest.update(str(array.shape).encode("ascii"))
                digest.update(array.tobytes(order="C"))
        content = digest.hexdigest()
        if read is not None and camera.nonlinearity_coefficients:
            # The configuration check used the scalar (median) read noise; the
            # realized map widens some pixels' excursions (re-review S3).
            try:
                camera.require_monotonic_nonlinearity(float(camera.read_noise_e) * float(np.max(read)))
            except CameraConfigError as exc:
                raise CameraMapsError(
                    "the realized CMOS read-noise map reaches "
                    f"{float(camera.read_noise_e) * float(np.max(read)):.4g} e- in some pixel, "
                    f"where the declared non-linearity is not monotonic: {exc}"
                ) from exc
        realization_hash = stable_hash(
            {
                "schema": CAMERA_MAPS_SCHEMA,
                "maps_config_hash": maps_hash,
                "layout_hash": layout_hash,
                "subaperture_ids": ids,
                "root_seed": int(root_seed),
                "realization_index": realization_index,
                "derivation_scheme_id": random_streams.derivation_scheme_id,
                "content_sha256": content,
            },
            namespace="physical_camera_maps",
        )
        return cls(
            layout=layout,
            maps_config_hash=maps_hash,
            subaperture_ids=ids,
            root_seed=int(root_seed),
            realization_index=realization_index,
            prnu=None if prnu is None else _readonly(prnu),
            dead=None if dead is None else _readonly(dead),
            hot=None if hot is None else _readonly(hot),
            offset_adu=None if offset is None else _readonly(offset),
            gain_multiplier=None if gain is None else _readonly(gain),
            read_noise_multiplier=None if read is None else _readonly(read),
            content_sha256=content,
            realization_hash=realization_hash,
        )

    @property
    def derivation_identity(self) -> dict[str, object]:
        """Declared derivation of the maps, free of realized float content."""

        return {
            "schema": CAMERA_MAPS_SCHEMA,
            "maps_config_hash": self.maps_config_hash,
            "layout_hash": self.layout.layout_hash,
            "subaperture_ids": self.subaperture_ids,
            "root_seed": self.root_seed,
            "realization_index": self.realization_index,
        }
