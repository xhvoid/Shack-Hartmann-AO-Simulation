"""HCIPy Fraunhofer science-PSF propagation behind the canonical protocol.

The adapter owns every repository-facing convention; HCIPy provides the
Fraunhofer (perfect-lens) propagation from the pupil to an explicit focal
grid:

- ``psf_from_opd(opd_m, wavelength_m)`` returns the exact Section 4
  ``PsfResult``: unit-total-flux discrete intensity, strictly increasing
  angular axes in radians, wavelength, backend name, and complete
  JSON-serializable sampling metadata.
- The focal grid is built with unit focal length, so HCIPy's focal-plane
  coordinates *are* angles in radians; the returned axes are read back from
  that grid's separated coordinates and are never inferred from arbitrary
  FFT or field indices.
- Sampling is specified in physical resolution units — pixels per
  ``λ/D`` resolution element and a field radius in resolution elements —
  and the angular grid is rebuilt per wavelength, so every wavelength sees
  the same sampling quality and the axes scale exactly with ``λ``.
  Multi-wavelength use is one propagator with per-wavelength calls.
- :func:`focal_sampling_from_psf_sampling` translates the repository-owned
  native ``PsfSampling`` contract exactly: for a square pupil the resulting
  HCIPy focal lattice coincides sample-for-sample with the native
  zero-padded FFT lattice, which makes native/HCIPy PSFs directly
  comparable on one grid.
- No HCIPy grid, wavefront, or propagator object escapes in results or
  metadata; intensity and axes are plain immutable arrays.

Importing this module never imports HCIPy; repository-side validation runs
before the optional dependency is resolved, so invalid construction raises
:class:`HcipySciencePropagationError` even on installations without HCIPy.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
from typing import Any, ClassVar, Final

import numpy as np

from ...core.geometry import PupilGeometry
from ...core.hashing import component_config_hash
from ...core.types import PsfResult
from ...science.propagation import PsfSampling
from . import hcipy_version, require_hcipy
from .conversion import (
    HcipyConversionError,
    hcipy_grid_from_coordinates,
    wavefront_from_opd,
)


_BACKEND_NAME = "hcipy"
_NORMALIZATION: Final = "unit_total_flux"
_PROPAGATION_ID = "fraunhofer_unit_focal_length_angular_grid-v1"
"""Identifier of the optical construction (part of the config hash)."""

_GRID_CONSTRUCTION_ID = "centered_regular_focal_grid_rounded_dims-v1"
"""Focal-grid arithmetic: HCIPy ``make_focal_grid`` layout with the pixel
count rounded (not truncated), so exact lattice translations stay exact."""

__all__ = (
    "HcipySciencePropagationError",
    "HcipyFocalSampling",
    "focal_sampling_from_psf_sampling",
    "HcipySciencePropagator",
)


class HcipySciencePropagationError(ValueError):
    """Raised when HCIPy science-propagation construction or input is invalid."""


@dataclass(frozen=True)
class HcipyFocalSampling:
    """Immutable angular focal-plane sampling in resolution units.

    ``pixels_per_resolution_element`` is the number of focal pixels across
    one ``λ/D`` resolution element; ``radius_resolution_elements`` is the
    half-extent of the focal grid in resolution elements.  The pixel count
    per axis is ``round(2 · radius · pixels_per_element)`` and the grid is
    centered on (0, 0) with the HCIPy ``make_focal_grid`` parity convention.
    """

    pixels_per_resolution_element: float = 4.0
    radius_resolution_elements: float = 16.0

    __hash_schema_id__: ClassVar[str] = (
        "shwfs_ao.backends.hcipy.focal_sampling.v1"
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "pixels_per_resolution_element",
            _positive(
                "pixels_per_resolution_element",
                self.pixels_per_resolution_element,
            ),
        )
        object.__setattr__(
            self,
            "radius_resolution_elements",
            _positive(
                "radius_resolution_elements",
                self.radius_resolution_elements,
            ),
        )
        if self.focal_dims_px < 2:
            raise HcipySciencePropagationError(
                "focal sampling must resolve at least two pixels per axis; "
                "increase pixels_per_resolution_element or "
                "radius_resolution_elements."
            )

    @property
    def focal_dims_px(self) -> int:
        """Focal pixels per axis: ``round(2 · radius · pixels_per_element)``."""

        return int(
            round(
                2.0
                * self.radius_resolution_elements
                * self.pixels_per_resolution_element
            )
        )


def focal_sampling_from_psf_sampling(
    pupil: PupilGeometry,
    sampling: PsfSampling,
) -> HcipyFocalSampling:
    """Translate the native ``PsfSampling`` contract exactly.

    The native backend zero-pads an ``N × N`` pupil by ``pad_factor`` and
    reads angles from the FFT lattice ``λ · fftfreq(pad · N, d = D/(N−1))``.
    The returned resolution-unit sampling reproduces that lattice
    sample-for-sample, so native and HCIPy PSFs share one exact angular
    grid.  Non-square pupil sampling has no single scalar translation and is
    rejected; construct :class:`HcipyFocalSampling` directly instead.
    """

    if not isinstance(pupil, PupilGeometry):
        raise HcipySciencePropagationError("pupil must be a PupilGeometry.")
    if not isinstance(sampling, PsfSampling):
        raise HcipySciencePropagationError("sampling must be a PsfSampling.")
    rows, columns = pupil.pupil_shape
    if rows != columns:
        raise HcipySciencePropagationError(
            "focal_sampling_from_psf_sampling requires a square pupil "
            f"sampling; got {pupil.pupil_shape}.  Construct "
            "HcipyFocalSampling directly for rectangular pupils."
        )
    samples = int(rows)
    pad = int(sampling.pad_factor)
    return HcipyFocalSampling(
        pixels_per_resolution_element=(pad * samples) / (samples - 1),
        radius_resolution_elements=(samples - 1) / 2.0,
    )


class HcipySciencePropagator:
    """HCIPy Fraunhofer implementation of the science propagator protocol.

    Parameters
    ----------
    pupil:
        Validated repository pupil geometry.
    sampling:
        Angular focal sampling in resolution units.  The angular grid is
        rebuilt per wavelength from ``λ / telescope_diameter_m``.

    Notes
    -----
    The instance holds only HCIPy's own optical state (the pupil grid and
    one cached propagator per requested wavelength).  It is memoryless with
    respect to measurements: the same OPD and wavelength always produce the
    same PSF.
    """

    def __init__(
        self,
        pupil: PupilGeometry,
        sampling: HcipyFocalSampling | None = None,
    ) -> None:
        if not isinstance(pupil, PupilGeometry):
            raise HcipySciencePropagationError("pupil must be a PupilGeometry.")
        resolved = HcipyFocalSampling() if sampling is None else sampling
        if not isinstance(resolved, HcipyFocalSampling):
            raise HcipySciencePropagationError(
                "sampling must be an HcipyFocalSampling or None."
            )

        self._pupil = pupil
        self._sampling = resolved
        self._config_hash = component_config_hash(
            "hcipy.science_propagator",
            {
                "backend_name": _BACKEND_NAME,
                "pupil_geometry_hash": pupil.geometry_hash,
                "sampling": resolved,
                "propagation": _PROPAGATION_ID,
                "grid_construction": _GRID_CONSTRUCTION_ID,
                "focal_length": "unity_angular_coordinates",
                "cropping": "none",
                "interpolation": "none",
                "normalization": _NORMALIZATION,
            },
        )

        # Resolving the optional dependency is the last construction step, so
        # every repository-side validation error above is raised even on
        # installations without HCIPy.
        require_hcipy()
        self._hcipy_version = hcipy_version()
        try:
            self._pupil_grid = hcipy_grid_from_coordinates(
                pupil.x_m,
                pupil.y_m,
            )
        except HcipyConversionError as exc:
            raise HcipySciencePropagationError(str(exc)) from exc
        self._instances: dict[float, tuple[Any, np.ndarray, np.ndarray]] = {}

    @property
    def backend_name(self) -> str:
        return _BACKEND_NAME

    @property
    def config_hash(self) -> str:
        return self._config_hash

    @property
    def pupil(self) -> PupilGeometry:
        return self._pupil

    @property
    def sampling(self) -> HcipyFocalSampling:
        return self._sampling

    @property
    def hcipy_backend_version(self) -> str:
        return self._hcipy_version

    def psf_from_opd(
        self,
        opd_m: np.ndarray,
        wavelength_m: float,
    ) -> PsfResult:
        """Propagate a pupil OPD map to a unit-total-flux science PSF."""

        wavelength = _positive("wavelength_m", wavelength_m)
        opd = _validated_opd(opd_m, self._pupil)
        try:
            wavefront = wavefront_from_opd(
                opd,
                self._pupil.pupil_mask,
                self._pupil_grid,
                wavelength_m=wavelength,
            )
        except HcipyConversionError as exc:
            raise HcipySciencePropagationError(str(exc)) from exc

        propagator, x_angle_rad, y_angle_rad = self._instance(wavelength)
        focal_wavefront = propagator.forward(wavefront)
        dims = self._sampling.focal_dims_px
        intensity = np.asarray(
            focal_wavefront.intensity,
            dtype=float,
        ).reshape(dims, dims)
        if not np.all(np.isfinite(intensity)):
            raise HcipySciencePropagationError(
                "HCIPy propagation produced non-finite focal intensity."
            )
        raw_flux = float(np.sum(intensity, dtype=np.float64))
        if not math.isfinite(raw_flux) or raw_flux <= 0.0:
            raise HcipySciencePropagationError(
                "HCIPy propagation produced no positive focal flux."
            )

        spatial_resolution_rad = (
            wavelength / self._pupil.telescope_diameter_m
        )
        pixel_scale_rad = (
            spatial_resolution_rad
            / self._sampling.pixels_per_resolution_element
        )
        dx_m, dy_m = self._pupil.pixel_spacing_xy_m
        sampling_metadata = {
            "schema_id": "shwfs_ao.backends.hcipy.psf_result_sampling.v1",
            "pupil_geometry_hash": self._pupil.geometry_hash,
            "pupil_shape_px": self._pupil.pupil_shape,
            "pupil_pixel_spacing_xy_m": (dx_m, dy_m),
            "pixels_per_resolution_element": (
                self._sampling.pixels_per_resolution_element
            ),
            "radius_resolution_elements": (
                self._sampling.radius_resolution_elements
            ),
            "output_shape_px": (dims, dims),
            "spatial_resolution_rad": spatial_resolution_rad,
            "focal_pixel_scale_xy_rad": (pixel_scale_rad, pixel_scale_rad),
            "focal_zero_xy_rad": (
                float(x_angle_rad[0]),
                float(y_angle_rad[0]),
            ),
            "axis_layout": "x_columns_y_rows",
            "focal_length": "unity_angular_coordinates",
            "propagation": _PROPAGATION_ID,
            "grid_construction": _GRID_CONSTRUCTION_ID,
            "cropping": "none",
            "interpolation": "none",
            "normalization": _NORMALIZATION,
            "hcipy_version": self._hcipy_version,
        }
        return PsfResult(
            intensity=intensity / raw_flux,
            x_angle_rad=np.array(x_angle_rad, dtype=float, copy=True),
            y_angle_rad=np.array(y_angle_rad, dtype=float, copy=True),
            wavelength_m=wavelength,
            normalization=_NORMALIZATION,
            backend_name=_BACKEND_NAME,
            sampling_metadata=sampling_metadata,
        )

    def captured_flux_fraction(
        self,
        opd_m: np.ndarray,
        wavelength_m: float,
    ) -> float:
        """Return the pupil-power fraction landing inside the focal window.

        This per-call diagnostic is deliberately not part of
        ``PsfResult.sampling_metadata``, which stays construction-determined
        so science metrics can require exact sampling identity between a PSF
        and its ideal reference.
        """

        wavelength = _positive("wavelength_m", wavelength_m)
        opd = _validated_opd(opd_m, self._pupil)
        try:
            wavefront = wavefront_from_opd(
                opd,
                self._pupil.pupil_mask,
                self._pupil_grid,
                wavelength_m=wavelength,
            )
        except HcipyConversionError as exc:
            raise HcipySciencePropagationError(str(exc)) from exc
        propagator, _, _ = self._instance(wavelength)
        input_power = float(wavefront.total_power)
        if not math.isfinite(input_power) or input_power <= 0.0:
            raise HcipySciencePropagationError(
                "pupil wavefront carries no positive power."
            )
        output_power = float(propagator.forward(wavefront).total_power)
        if not math.isfinite(output_power) or output_power < 0.0:
            raise HcipySciencePropagationError(
                "HCIPy propagation produced an invalid focal power."
            )
        return output_power / input_power

    def _instance(
        self,
        wavelength_m: float,
    ) -> tuple[Any, np.ndarray, np.ndarray]:
        cached = self._instances.get(wavelength_m)
        if cached is not None:
            return cached

        hcipy = require_hcipy()
        dims = self._sampling.focal_dims_px
        delta_rad = (
            wavelength_m
            / self._pupil.telescope_diameter_m
            / self._sampling.pixels_per_resolution_element
        )
        zero_rad = delta_rad * (-dims / 2 + (dims % 2) * 0.5)
        focal_grid = hcipy.CartesianGrid(
            hcipy.RegularCoords(
                [delta_rad, delta_rad],
                [dims, dims],
                [zero_rad, zero_rad],
            )
        )
        # Unit focal length makes the focal-grid coordinates angles in
        # radians; the returned axes are HCIPy's own grid coordinates.
        propagator = hcipy.FraunhoferPropagator(
            self._pupil_grid,
            focal_grid,
            focal_length=1.0,
        )
        x_angle_rad, y_angle_rad = (
            np.array(axis, dtype=float, copy=True)
            for axis in focal_grid.separated_coords
        )
        instance = (propagator, x_angle_rad, y_angle_rad)
        self._instances[wavelength_m] = instance
        return instance


def _validated_opd(value: object, pupil: PupilGeometry) -> np.ndarray:
    if not isinstance(value, np.ndarray):
        raise HcipySciencePropagationError("opd_m must be a numpy.ndarray.")
    if value.dtype.kind in {"b", "c", "O", "S", "U", "V"}:
        raise HcipySciencePropagationError(
            "opd_m must contain real numeric values."
        )
    try:
        opd_m = np.array(value, dtype=float, copy=True)
    except (TypeError, ValueError) as exc:
        raise HcipySciencePropagationError(
            "opd_m must contain real numeric values."
        ) from exc
    if opd_m.ndim != 2 or opd_m.shape != pupil.pupil_shape:
        raise HcipySciencePropagationError(
            f"opd_m shape {opd_m.shape} must match pupil shape "
            f"{pupil.pupil_shape}."
        )
    if np.any(np.isinf(opd_m)):
        raise HcipySciencePropagationError(
            "opd_m must not contain infinite values."
        )
    if not np.all(np.isfinite(opd_m[pupil.pupil_mask])):
        raise HcipySciencePropagationError(
            "opd_m must be finite throughout the illuminated pupil."
        )
    return opd_m


def _positive(field_name: str, value: object) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise HcipySciencePropagationError(
            f"{field_name} must be a positive finite scalar; got {value!r}."
        )
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise HcipySciencePropagationError(
            f"{field_name} must be a positive finite scalar; got {value!r}."
        )
    return number
