"""Off-axis science evaluation of a single-NGS closed loop.

The guide star stays on axis.  One or more *science offsets*
``(x_arcsec, y_arcsec)`` give the sky position of a science target relative
to the guide star.  Each selected frame of the closed loop samples the same
atmospheric realization at the same frame time along every offset, subtracts
the same pupil-conjugate DM correction the WFS saw, and propagates the
result with the system's science propagator; instantaneous *intensities* are
averaged into one long-exposure image per offset and wavelength.

Conventions
-----------
``x_arcsec`` and ``y_arcsec``
    Sky offset of the science target from the guide star.  Positive ``x``
    displaces the footprint of a layer at altitude ``h`` toward larger pupil
    ``x`` (array columns), positive ``y`` toward larger pupil ``y`` (array
    rows): a ray reaching pupil coordinate ``r`` crosses the layer at
    ``r + h * theta`` (zenith, small-angle, thin-layer geometry).  Radians
    are ``theta = arcsec * pi / (180 * 3600)``; the conversion is
    :data:`ARCSEC_TO_RAD`.  ``(0, 0)`` is the guide-star direction.
``target-centred images``
    A PSF is formed from the residual OPD seen along the offset alone, so its
    angular grid (``x_angle_rad``, ``y_angle_rad``) is centred on the
    target's nominal sky position; residual atmospheric image motion of the
    target is retained and broadens the long exposure as it would on a
    detector.  The images of different offsets share one grid.
``long exposure``
    The equal-weight mean of unit-flux instantaneous intensities over the
    selected frames (the pre-update residual of each frame, as
    :class:`~shwfs_ao.science.long_exposure.StreamingLongExposure` uses).
    Its peak Strehl is
    :func:`~shwfs_ao.science.metrics.peak_strehl_from_discrete_flux` against
    the zero-OPD image of the same propagator, wavelength, grid and unit flux.
    The mean instantaneous Strehl (the mean of per-frame peak Strehls) is a
    different statistic and is reported under its own name.

The observer is passive: it reads ``science_residual_opd_m`` from the frame
observation that :func:`~shwfs_ao.control.run_closed_loop` produces when it
is given ``science_directions_rad``; it reaches no live component and makes
no draw.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from numbers import Integral, Real
from types import MappingProxyType
from typing import Any, Final

import numpy as np

from ..core.hashing import component_config_hash
from ..core.protocols import SciencePropagator
from ..core.types import PsfResult
from ._psf_peak import interpolated_peak, supports_peak_interpolation
from .long_exposure import (
    FLUX_DENOMINATOR,
    TEMPORAL_QUADRATURE,
    LongExposureConfig,
    LongExposureError,
    LongExposureSelection,
)
from .metrics import (
    ScienceMetricsError,
    discrete_flux_to_angular_surface_brightness,
    encircled_energy_radius_from_discrete_flux,
    fwhm_diameter_from_angular_surface_brightness,
    lambda_over_d_rad,
    peak_strehl_from_discrete_flux,
)


__all__ = (
    "ARCSEC_TO_RAD",
    "OFF_AXIS_RESULT_SCHEMA",
    "OffAxisScienceError",
    "ScienceOffset",
    "science_offsets",
    "OffAxisImage",
    "OffAxisScienceResult",
    "OffAxisLongExposure",
    "footprint_report",
)


ARCSEC_TO_RAD: Final = math.pi / (180.0 * 3600.0)
"""Radians per arcsecond (``pi / 648000``)."""

OFF_AXIS_RESULT_SCHEMA: Final = "shwfs_ao.science.off_axis_result.v1"
_ON_AXIS: Final = (0.0, 0.0)


class OffAxisScienceError(ValueError):
    """Raised for an invalid offset, observer configuration or frame."""


@dataclass(frozen=True)
class ScienceOffset:
    """A science target's sky offset from the guide star, in arcseconds."""

    x_arcsec: float
    y_arcsec: float

    def __post_init__(self) -> None:
        for name in ("x_arcsec", "y_arcsec"):
            value = getattr(self, name)
            if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
                raise OffAxisScienceError(f"{name} must be a real number of arcseconds.")
            number = float(value)
            if not math.isfinite(number):
                raise OffAxisScienceError(f"{name} must be finite.")
            object.__setattr__(self, name, number)

    @property
    def radians(self) -> tuple[float, float]:
        """``(theta_x, theta_y)`` in radians, the loop's direction pair."""

        return (self.x_arcsec * ARCSEC_TO_RAD, self.y_arcsec * ARCSEC_TO_RAD)

    @property
    def radial_arcsec(self) -> float:
        return math.hypot(self.x_arcsec, self.y_arcsec)

    @property
    def is_on_axis(self) -> bool:
        return self.x_arcsec == 0.0 and self.y_arcsec == 0.0

    @property
    def label(self) -> str:
        return f"({self.x_arcsec:+g}, {self.y_arcsec:+g}) arcsec"

    def to_record(self) -> dict[str, float]:
        return {
            "x_arcsec": self.x_arcsec,
            "y_arcsec": self.y_arcsec,
            "radial_arcsec": self.radial_arcsec,
            "theta_x_rad": self.radians[0],
            "theta_y_rad": self.radians[1],
        }


def science_offsets(values: object) -> tuple[ScienceOffset, ...]:
    """Normalize ``ScienceOffset`` values or ``(x_arcsec, y_arcsec)`` pairs.

    ``None`` or an empty sequence means the default: the guide-star direction
    alone, ``((0.0, 0.0),)``.  Duplicates are refused because each offset
    names one image.
    """

    if values is None:
        return (ScienceOffset(0.0, 0.0),)
    if isinstance(values, ScienceOffset):
        return (values,)
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise OffAxisScienceError(
            "offsets must be a sequence of ScienceOffset or (x_arcsec, y_arcsec) pairs."
        )
    if not values:
        return (ScienceOffset(0.0, 0.0),)
    result: list[ScienceOffset] = []
    for index, item in enumerate(values):
        if isinstance(item, ScienceOffset):
            offset = item
        elif (
            isinstance(item, (str, bytes))
            or not isinstance(item, Sequence)
            or len(item) != 2
        ):
            raise OffAxisScienceError(
                f"offsets[{index}] must be a ScienceOffset or an (x_arcsec, y_arcsec) pair."
            )
        else:
            offset = ScienceOffset(item[0], item[1])
        if offset in result:
            raise OffAxisScienceError(f"offsets[{index}] repeats {offset.label}.")
        result.append(offset)
    return tuple(result)


@dataclass(frozen=True)
class OffAxisImage:
    """One offset's long exposure at one wavelength, with its metrics.

    ``peak_strehl`` is the long-exposure image's peak Strehl (the accumulated
    intensity image against the zero-OPD ideal); ``on_axis_strehl`` reads the
    same image at the target's nominal position.  ``mean_instantaneous_strehl``
    is the mean of the selected frames' instantaneous peak Strehls, a separate
    statistic. ``interpolated_peak_strehl`` refines the accumulated image and ideal
    between samples on supported grids. ``block_peak_strehl`` holds the peak Strehl
    of each complete block of ``block_frames`` consecutive selected frames (an uncertainty
    indicator for a single realization, not an independent-sample estimate).
    """

    offset: ScienceOffset
    psf: PsfResult
    ideal_psf: PsfResult
    wavelength_m: float
    lambda_over_d_rad: float
    peak_strehl: float
    on_axis_strehl: float
    peak_offset_xy_rad: tuple[float, float]
    fwhm_rad: float
    ee50_radius_rad: float
    ee80_radius_rad: float
    sample_count: int
    mean_instantaneous_strehl: float | None
    instantaneous_strehl: np.ndarray | None
    block_frames: int | None
    block_peak_strehl: np.ndarray | None
    interpolated_peak_strehl: float | None = None

    def to_record(self) -> dict[str, Any]:
        blocks = self.block_peak_strehl
        return {
            "offset": self.offset.to_record(),
            "wavelength_m": self.wavelength_m,
            "lambda_over_d_rad": self.lambda_over_d_rad,
            "sample_count": self.sample_count,
            "long_exposure_peak_strehl": self.peak_strehl,
            "long_exposure_interpolated_peak_strehl": self.interpolated_peak_strehl,
            "long_exposure_on_axis_strehl": self.on_axis_strehl,
            "peak_offset_xy_rad": list(self.peak_offset_xy_rad),
            "fwhm_rad": self.fwhm_rad,
            "ee50_radius_rad": self.ee50_radius_rad,
            "ee80_radius_rad": self.ee80_radius_rad,
            "mean_instantaneous_peak_strehl": self.mean_instantaneous_strehl,
            "instantaneous_peak_strehl_sd": (
                None
                if self.instantaneous_strehl is None
                else float(np.std(self.instantaneous_strehl))
            ),
            "block_frames": self.block_frames,
            "block_peak_strehl": None if blocks is None else [float(v) for v in blocks],
            "block_peak_strehl_sd": (
                None if blocks is None or blocks.size < 2 else float(np.std(blocks, ddof=1))
            ),
            "block_count": None if blocks is None else int(blocks.size),
        }


@dataclass(frozen=True)
class OffAxisScienceResult:
    """Every offset's images, the selection they share and identity metadata."""

    schema: str
    offsets: tuple[ScienceOffset, ...]
    wavelengths_m: tuple[float, ...]
    selection: LongExposureSelection
    images: tuple[OffAxisImage, ...]
    propagator_backend: str
    propagator_config_hash: str
    config_hash: str
    max_on_axis_difference_m: float | None
    metadata: Mapping[str, Any]

    def image(self, offset: ScienceOffset | tuple[float, float], wavelength_m: float) -> OffAxisImage:
        target = offset if isinstance(offset, ScienceOffset) else ScienceOffset(*offset)
        for image in self.images:
            if image.offset == target and math.isclose(
                image.wavelength_m, wavelength_m, rel_tol=1e-12
            ):
                return image
        raise OffAxisScienceError(f"no image at {target.label}, {wavelength_m!r} m.")

    def table_rows(self) -> list[dict[str, Any]]:
        """Machine-readable rows: signed offsets, radius, wavelength, frames, Strehl."""

        rows = []
        for image in self.images:
            rows.append(
                {
                    "x_arcsec": image.offset.x_arcsec,
                    "y_arcsec": image.offset.y_arcsec,
                    "radial_arcsec": image.offset.radial_arcsec,
                    "wavelength_m": image.wavelength_m,
                    "averaged_frames": image.sample_count,
                    "first_frame": self.selection.first_frame,
                    "last_frame": self.selection.last_frame,
                    "long_exposure_peak_strehl": image.peak_strehl,
                    "long_exposure_interpolated_peak_strehl": image.interpolated_peak_strehl,
                    "long_exposure_on_axis_strehl": image.on_axis_strehl,
                    "mean_instantaneous_peak_strehl": image.mean_instantaneous_strehl,
                    "fwhm_rad": image.fwhm_rad,
                    "ee50_radius_rad": image.ee50_radius_rad,
                }
            )
        return rows

    def to_record(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "offsets": [offset.to_record() for offset in self.offsets],
            "wavelengths_m": list(self.wavelengths_m),
            "selection": self.selection.to_record(),
            "images": [image.to_record() for image in self.images],
            "propagator_backend": self.propagator_backend,
            "propagator_config_hash": self.propagator_config_hash,
            "config_hash": self.config_hash,
            "max_on_axis_difference_m": self.max_on_axis_difference_m,
            "metadata": dict(self.metadata),
        }


def _immutable(values: np.ndarray) -> np.ndarray:
    contiguous = np.ascontiguousarray(np.asarray(values, dtype=float))
    return np.frombuffer(contiguous.tobytes(order="C"), dtype=float).reshape(
        contiguous.shape
    )


class OffAxisLongExposure:
    """Accumulate target-centred long exposures for several science offsets.

    Parameters
    ----------
    propagator:
        The system's science propagator (pupil, sampling, FFT convention).
    offsets:
        Science offsets; their ``radians`` are the directions the loop must be
        given, in this order (:attr:`directions_rad`).
    config:
        Frame selection and wavelengths, as for
        :class:`~shwfs_ao.science.long_exposure.StreamingLongExposure`.  Only
        the pre-update residual is defined off axis.
    telescope_diameter_m:
        For ``lambda / D``.
    record_instantaneous_strehl:
        Keep every selected frame's instantaneous peak Strehl per offset.
    block_frames:
        Complete blocks of this many consecutive selected frames get their
        own block-mean peak Strehl (``None`` disables).
    check_on_axis:
        Also request ``pre_update_residual_opd_m`` and record the largest
        absolute difference between it and the sampled ``(0, 0)`` residual
        (``None`` when no offset is on axis).
    """

    def __init__(
        self,
        propagator: SciencePropagator,
        offsets: Sequence[ScienceOffset] | Sequence[tuple[float, float]] | None,
        config: LongExposureConfig,
        *,
        telescope_diameter_m: float,
        record_instantaneous_strehl: bool = True,
        block_frames: int | None = None,
        check_on_axis: bool = True,
    ) -> None:
        if not isinstance(propagator, SciencePropagator):
            raise OffAxisScienceError("propagator must implement SciencePropagator.")
        if not isinstance(config, LongExposureConfig):
            raise OffAxisScienceError("config must be a LongExposureConfig.")
        if config.residual != "pre_update":
            raise OffAxisScienceError(
                "off-axis science uses the pre-update residual (the correction the "
                "WFS saw at the frame time); post_update is not defined off axis."
            )
        if config.sample_weights is not None:
            raise OffAxisScienceError("off-axis exposures use equal sample weights.")
        if block_frames is not None and (
            isinstance(block_frames, bool)
            or not isinstance(block_frames, Integral)
            or int(block_frames) < 1
        ):
            raise OffAxisScienceError("block_frames must be a positive integer or None.")
        diameter = float(telescope_diameter_m)
        if not math.isfinite(diameter) or diameter <= 0.0:
            raise OffAxisScienceError("telescope_diameter_m must be positive.")
        self._propagator = propagator
        self._propagator_hash = propagator.config_hash
        self._offsets = science_offsets(offsets)
        self._directions = tuple(offset.radians for offset in self._offsets)
        self._config = config
        self._diameter_m = diameter
        self._record_instantaneous = bool(record_instantaneous_strehl)
        self._block_frames = None if block_frames is None else int(block_frames)
        self._check_on_axis = bool(check_on_axis) and any(
            offset.is_on_axis for offset in self._offsets
        )
        requested = {"science_residual_opd_m"}
        if self._check_on_axis:
            requested.add("pre_update_residual_opd_m")
        self._requested = frozenset(requested)
        self._ideal: dict[float, PsfResult] = {}
        self._clear()

    def _clear(self) -> None:
        count = len(self._offsets) * len(self._config.wavelengths_m)
        self._sums: list[np.ndarray] | None = None
        self._block_sums: list[np.ndarray] | None = None
        self._block_filled = 0
        self._block_strehl: list[list[float]] = [[] for _ in range(count)]
        self._instantaneous: list[list[float]] = [[] for _ in range(count)]
        self._axes: list[tuple[np.ndarray, np.ndarray]] = []
        self._sampling_metadata: list[Mapping[str, Any]] = []
        self._pupil_shape: tuple[int, int] | None = None
        self._samples = 0
        self._first_frame: int | None = None
        self._last_frame: int | None = None
        self._first_time_s = math.nan
        self._last_time_s = math.nan
        self._frame_period_s: float | None = None
        self._next_frame: int | None = None
        self._max_on_axis_difference_m = 0.0 if self._check_on_axis else None

    # -- FrameObserver protocol -------------------------------------------------

    @property
    def requested_fields(self) -> frozenset[str]:
        return self._requested

    @property
    def offsets(self) -> tuple[ScienceOffset, ...]:
        return self._offsets

    @property
    def directions_rad(self) -> tuple[tuple[float, float], ...]:
        """The ``science_directions_rad`` the loop must be given, in order."""

        return self._directions

    @property
    def config(self) -> LongExposureConfig:
        return self._config

    @property
    def sample_count(self) -> int:
        return self._samples

    @property
    def config_hash(self) -> str:
        return component_config_hash(
            "science.off_axis_long_exposure",
            {
                "offsets_arcsec": [(o.x_arcsec, o.y_arcsec) for o in self._offsets],
                "long_exposure_config_hash": self._config.config_hash,
                "block_frames": self._block_frames,
                "telescope_diameter_m": self._diameter_m,
            },
        )

    def reset(self) -> None:
        self._clear()

    def observe(self, observation: Any) -> None:
        frame_index = int(observation.frame_index)
        period = float(observation.frame_period_s)
        if self._frame_period_s is None:
            self._frame_period_s = period
        elif not math.isclose(period, self._frame_period_s, rel_tol=1e-12, abs_tol=0.0):
            raise OffAxisScienceError("frame period changed during an exposure.")
        if self._next_frame is not None and frame_index != self._next_frame:
            raise OffAxisScienceError(
                f"frames must arrive in order: expected {self._next_frame}, got "
                f"{frame_index}; call reset() before a new run."
            )
        self._next_frame = frame_index + 1
        directions = getattr(observation, "science_directions_rad", None)
        if directions is None or tuple(directions) != self._directions:
            raise OffAxisScienceError(
                "the loop's science_directions_rad must equal this observer's "
                f"directions_rad {self._directions}; got {directions}."
            )
        if not self._config.selects(frame_index, self._samples):
            return
        residuals = getattr(observation, "science_residual_opd_m", None)
        if residuals is None or len(residuals) != len(self._offsets):
            raise OffAxisScienceError(
                "observation lacks one science_residual_opd_m map per offset; the "
                "loop must be given this observer and its directions_rad."
            )
        if self._check_on_axis:
            reference = getattr(observation, "pre_update_residual_opd_m", None)
            if reference is None:
                raise OffAxisScienceError("observation lacks pre_update_residual_opd_m.")
            for offset, residual in zip(self._offsets, residuals):
                if offset.is_on_axis:
                    difference = np.abs(np.asarray(residual) - np.asarray(reference))
                    finite = difference[np.isfinite(difference)]
                    assert self._max_on_axis_difference_m is not None
                    self._max_on_axis_difference_m = max(
                        self._max_on_axis_difference_m,
                        float(np.max(finite)) if finite.size else 0.0,
                    )
        self._accumulate(
            [np.asarray(residual, dtype=float) for residual in residuals],
            frame_index=frame_index,
            time_s=float(observation.time_s),
        )

    # -- accumulation -----------------------------------------------------------

    def _slot(self, offset_index: int, wavelength_index: int) -> int:
        return offset_index * len(self._config.wavelengths_m) + wavelength_index

    def ideal_psf(self, wavelength_m: float) -> PsfResult:
        if self._pupil_shape is None:
            raise OffAxisScienceError("no frame has fixed the pupil grid yet.")
        key = float(wavelength_m)
        cached = self._ideal.get(key)
        if cached is None:
            cached = self._propagator.psf_from_opd(
                np.zeros(self._pupil_shape, dtype=float), key
            )
            self._check_psf(cached, key)
            self._ideal[key] = cached
        return cached

    def _check_psf(self, psf: object, wavelength: float) -> None:
        if not isinstance(psf, PsfResult):
            raise OffAxisScienceError("propagator must return a PsfResult.")
        if psf.normalization != "unit_total_flux":
            raise OffAxisScienceError("instantaneous images must have unit total flux.")
        if not math.isclose(psf.wavelength_m, wavelength, rel_tol=1e-15, abs_tol=0.0):
            raise OffAxisScienceError("propagator returned a different wavelength.")

    def _accumulate(
        self, residuals: list[np.ndarray], *, frame_index: int, time_s: float
    ) -> None:
        for residual in residuals:
            if residual.ndim != 2:
                raise OffAxisScienceError("residual OPD must be a 2-D map.")
            if self._pupil_shape is None:
                self._pupil_shape = (int(residual.shape[0]), int(residual.shape[1]))
            elif residual.shape != self._pupil_shape:
                raise OffAxisScienceError("residual OPD shape changed during an exposure.")
        wavelengths = self._config.wavelengths_m
        for offset_index, residual in enumerate(residuals):
            for wavelength_index, wavelength in enumerate(wavelengths):
                psf = self._propagator.psf_from_opd(residual, wavelength)
                self._check_psf(psf, wavelength)
                slot = self._slot(offset_index, wavelength_index)
                if self._sums is None:
                    count = len(self._offsets) * len(wavelengths)
                    self._sums = [np.zeros_like(psf.intensity, dtype=float) for _ in range(count)]
                    if self._block_frames is not None:
                        self._block_sums = [np.zeros_like(psf.intensity) for _ in range(count)]
                if len(self._axes) <= wavelength_index:
                    self._axes.append((_immutable(psf.x_angle_rad), _immutable(psf.y_angle_rad)))
                    self._sampling_metadata.append(MappingProxyType(dict(psf.sampling_metadata)))
                x_axis, y_axis = self._axes[wavelength_index]
                if not (
                    np.array_equal(psf.x_angle_rad, x_axis)
                    and np.array_equal(psf.y_angle_rad, y_axis)
                ):
                    raise OffAxisScienceError(
                        "instantaneous images must share one angular grid per wavelength."
                    )
                intensity = np.asarray(psf.intensity, dtype=float)
                self._sums[slot] += intensity
                if self._block_sums is not None:
                    self._block_sums[slot] += intensity
                if self._record_instantaneous:
                    self._instantaneous[slot].append(
                        peak_strehl_from_discrete_flux(psf, self.ideal_psf(wavelength))
                    )
        self._samples += 1
        if self._first_frame is None:
            self._first_frame = frame_index
            self._first_time_s = time_s
        self._last_frame = frame_index
        self._last_time_s = time_s
        if self._block_sums is not None:
            assert self._block_frames is not None
            self._block_filled += 1
            if self._block_filled == self._block_frames:
                for offset_index in range(len(self._offsets)):
                    for wavelength_index, wavelength in enumerate(wavelengths):
                        slot = self._slot(offset_index, wavelength_index)
                        block = self._psf_result(
                            self._block_sums[slot] / self._block_frames, wavelength_index
                        )
                        self._block_strehl[slot].append(
                            peak_strehl_from_discrete_flux(block, self.ideal_psf(wavelength))
                        )
                        self._block_sums[slot][...] = 0.0
                self._block_filled = 0

    def _psf_result(self, intensity: np.ndarray, wavelength_index: int) -> PsfResult:
        x_axis, y_axis = self._axes[wavelength_index]
        return PsfResult(
            intensity=intensity,
            x_angle_rad=x_axis,
            y_angle_rad=y_axis,
            wavelength_m=self._config.wavelengths_m[wavelength_index],
            normalization="unit_total_flux",
            backend_name=self._propagator.backend_name,
            sampling_metadata=dict(self._sampling_metadata[wavelength_index]),
        )

    # -- result -----------------------------------------------------------------

    def result(self) -> OffAxisScienceResult:
        if self._sums is None or self._samples == 0:
            raise OffAxisScienceError(
                "no frame was selected; check burn_in_frames, stride and the run length."
            )
        if self._propagator.config_hash != self._propagator_hash:
            raise OffAxisScienceError("propagator identity changed during the exposure.")
        assert self._first_frame is not None and self._last_frame is not None
        assert self._frame_period_s is not None
        images = []
        ideal_peaks = {}
        for wavelength in self._config.wavelengths_m:
            ideal = self.ideal_psf(wavelength)
            if supports_peak_interpolation(ideal):
                ideal_peaks[wavelength] = interpolated_peak(ideal.intensity)[0]
        for offset_index, offset in enumerate(self._offsets):
            for wavelength_index, wavelength in enumerate(self._config.wavelengths_m):
                slot = self._slot(offset_index, wavelength_index)
                psf = self._psf_result(self._sums[slot] / self._samples, wavelength_index)
                image = self._image(
                    offset, psf, self.ideal_psf(wavelength), slot, ideal_peaks.get(wavelength)
                )
                images.append(image)
        selection = LongExposureSelection(
            first_frame=self._first_frame,
            last_frame=self._last_frame,
            stride=self._config.stride,
            sample_count=self._samples,
            burn_in_frames=self._config.burn_in_frames,
            first_time_s=self._first_time_s,
            last_time_s=self._last_time_s,
            frame_period_s=self._frame_period_s,
            weight_sum=float(self._samples),
            uniform_weights=True,
            residual="pre_update",
            residual_description=(
                "pre-update residual along each science direction: the direction's "
                "atmospheric sample at the frame time minus the DM correction the WFS saw"
            ),
        )
        return OffAxisScienceResult(
            schema=OFF_AXIS_RESULT_SCHEMA,
            offsets=self._offsets,
            wavelengths_m=self._config.wavelengths_m,
            selection=selection,
            images=tuple(images),
            propagator_backend=self._propagator.backend_name,
            propagator_config_hash=self._propagator_hash,
            config_hash=self.config_hash,
            max_on_axis_difference_m=self._max_on_axis_difference_m,
            metadata=MappingProxyType(
                {
                    "flux_denominator": FLUX_DENOMINATOR,
                    "temporal_quadrature": TEMPORAL_QUADRATURE,
                    "recentering": "none",
                    "coaddition": "intensity",
                    "image_centre": "target_nominal_sky_position",
                    "offset_convention": (
                        "x_arcsec, y_arcsec from the guide star; positive x toward larger "
                        "pupil x (columns), positive y toward larger pupil y (rows); "
                        "theta_rad = arcsec * pi / 648000"
                    ),
                    "strehl_definitions": {
                        "long_exposure_peak_strehl": (
                            "peak angular surface brightness of the accumulated intensity "
                            "image over that of the zero-OPD ideal image (same propagator, "
                            "wavelength, grid, unit flux)"
                        ),
                        "long_exposure_interpolated_peak_strehl": (
                            "subpixel Fourier peak of the accumulated intensity divided by "
                            "the subpixel peak of the matched ideal; null for unsupported sampling"
                        ),
                        "mean_instantaneous_peak_strehl": (
                            "mean over selected frames of each frame's peak Strehl"
                        ),
                    },
                }
            ),
        )

    def _image(
        self, offset: ScienceOffset, psf: PsfResult, ideal: PsfResult, slot: int,
        interpolated_ideal_peak: float | None,
    ) -> OffAxisImage:
        wavelength = psf.wavelength_m
        brightness = discrete_flux_to_angular_surface_brightness(psf)
        ideal_brightness = discrete_flux_to_angular_surface_brightness(ideal)
        ideal_peak = float(np.max(ideal_brightness))
        row, column = np.unravel_index(int(np.argmax(brightness)), brightness.shape)
        axis_column = int(np.argmin(np.abs(psf.x_angle_rad)))
        axis_row = int(np.argmin(np.abs(psf.y_angle_rad)))
        try:
            fwhm = fwhm_diameter_from_angular_surface_brightness(
                brightness, psf.x_angle_rad, psf.y_angle_rad
            )
        except ScienceMetricsError:
            fwhm = math.nan
        instantaneous = (
            np.asarray(self._instantaneous[slot], dtype=float)
            if self._record_instantaneous
            else None
        )
        blocks = (
            np.asarray(self._block_strehl[slot], dtype=float)
            if self._block_frames is not None
            else None
        )
        return OffAxisImage(
            offset=offset,
            psf=psf,
            ideal_psf=ideal,
            wavelength_m=wavelength,
            lambda_over_d_rad=lambda_over_d_rad(wavelength, self._diameter_m),
            peak_strehl=peak_strehl_from_discrete_flux(psf, ideal),
            on_axis_strehl=float(brightness[axis_row, axis_column] / ideal_peak),
            peak_offset_xy_rad=(float(psf.x_angle_rad[column]), float(psf.y_angle_rad[row])),
            fwhm_rad=fwhm,
            ee50_radius_rad=encircled_energy_radius_from_discrete_flux(
                psf.intensity, psf.x_angle_rad, psf.y_angle_rad, 0.5
            ),
            ee80_radius_rad=encircled_energy_radius_from_discrete_flux(
                psf.intensity, psf.x_angle_rad, psf.y_angle_rad, 0.8
            ),
            sample_count=self._samples,
            mean_instantaneous_strehl=(
                None if instantaneous is None else float(np.mean(instantaneous))
            ),
            instantaneous_strehl=instantaneous,
            block_frames=self._block_frames,
            block_peak_strehl=blocks,
            interpolated_peak_strehl=(
                interpolated_peak(psf.intensity)[0] / interpolated_ideal_peak
                if interpolated_ideal_peak is not None and supports_peak_interpolation(psf)
                else None
            ),
        )


def footprint_report(
    atmosphere_metadata: Mapping[str, Any],
    offsets: Sequence[ScienceOffset] | Sequence[tuple[float, float]] | None,
) -> dict[str, Any]:
    """Layer footprint displacements of each offset against the screen period.

    For a layered atmosphere's metadata (``layers`` with ``altitude_m``,
    ``grid_delta_m``, ``pupil_diameter_m`` and ``screen_period_m``) report
    every layer's displacement ``h * theta`` in metres and grid samples, the
    largest displacement, and whether the on-axis and offset footprints of
    the periodic band can overlap through the screen's periodic wrap
    (``pupil_diameter_m + |h * theta| >= screen_period_m``).  The analytic
    low-frequency modes are evaluated at the exact coordinates and are not
    periodic, so only the periodic band is subject to wrap.
    """

    layers = atmosphere_metadata.get("layers")
    if not layers:
        raise OffAxisScienceError(
            "footprint_report needs a layered atmosphere's metadata (its 'layers')."
        )
    delta = float(atmosphere_metadata["grid_delta_m"])
    diameter = float(atmosphere_metadata["pupil_diameter_m"])
    period = atmosphere_metadata.get("screen_period_m")
    period_m = None if period is None else float(period)
    report: dict[str, Any] = {
        "grid_delta_m": delta,
        "pupil_diameter_m": diameter,
        "screen_period_m": period_m,
        "offsets": [],
    }
    for offset in science_offsets(offsets):
        theta_x, theta_y = offset.radians
        per_layer = []
        largest = 0.0
        for index, layer in enumerate(layers):
            altitude = float(layer["altitude_m"])
            dx, dy = altitude * theta_x, altitude * theta_y
            magnitude = math.hypot(dx, dy)
            largest = max(largest, magnitude)
            per_layer.append(
                {
                    "layer": index,
                    "altitude_m": altitude,
                    "cn2_fraction": float(layer["cn2_fraction"]),
                    "displacement_xy_m": [dx, dy],
                    "displacement_xy_samples": [dx / delta, dy / delta],
                    "displacement_m": magnitude,
                }
            )
        report["offsets"].append(
            {
                "offset": offset.to_record(),
                "layers": per_layer,
                "max_displacement_m": largest,
                "max_displacement_samples": largest / delta,
                "footprint_span_m": diameter + largest,
                "periodic_band_wrap_overlap": (
                    None if period_m is None else bool(diameter + largest >= period_m)
                ),
            }
        )
    return report
