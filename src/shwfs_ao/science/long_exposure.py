"""Streaming monochromatic long-exposure science images.

A long exposure is the weighted mean of *instantaneous intensities*,
``sum(a_k * I_k) / sum(a_k)``.  Each selected frame's residual OPD is
propagated separately at every requested wavelength and its unit-flux image is
added to a running sum.  The mean OPD is never propagated, fields are never
added coherently, and frames are never recentred, so residual tip/tilt and
temporal variation broaden the image exactly as they would on a detector.

:class:`StreamingLongExposure` is a passive closed-loop frame observer (it
satisfies :class:`shwfs_ao.control.FrameObserver` structurally).  Its retained
state is one float64 sum image per wavelength plus scalar bookkeeping, so its
memory does not grow with the number of frames: no OPD or PSF cube is kept.

Temporal model
--------------
The loop provides one instantaneous OPD snapshot per frame period ``dt``.  A
selected sample therefore stands for ``stride * dt`` of exposure (rectangle
quadrature of an instantaneous-snapshot model): ``N`` uniform samples are an
``N * stride * dt`` quadrature exposure whose sample centres span
``(N - 1) * stride * dt``.  The default residual is the pre-update residual the
WFS measured; the post-update residual is the same atmospheric sample with a
newer correction and is labelled as a same-sample diagnostic.

Flux convention
---------------
Every instantaneous image has unit total flux over the complete, uncropped
propagator grid, so the long exposure does too.  Strehl is the ratio of the
final science image's peak angular surface brightness to that of a zero-OPD
ideal image from the same propagator, wavelength and grid; encircled energy is
the fraction of that same normalized-source-grid flux.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
import math
from numbers import Integral, Real
from types import MappingProxyType
from typing import Any, ClassVar, Final, Literal, Mapping

import numpy as np

from ..core.hashing import component_config_hash
from ..core.protocols import SciencePropagator
from ..core.types import PsfResult
from .metrics import (
    ScienceMetricsError,
    discrete_flux_to_angular_surface_brightness,
    encircled_energy_radius_from_discrete_flux,
    fwhm_diameter_from_angular_surface_brightness,
    lambda_over_d_rad,
    peak_strehl_from_discrete_flux,
)


__all__ = (
    "LONG_EXPOSURE_RESULT_SCHEMA",
    "FLUX_DENOMINATOR",
    "TEMPORAL_QUADRATURE",
    "LongExposureError",
    "LongExposureConfig",
    "LongExposureSelection",
    "LongExposureMetrics",
    "LongExposureImage",
    "LongExposureResult",
    "StreamingLongExposure",
    "radial_profile_from_discrete_flux",
)


LONG_EXPOSURE_RESULT_SCHEMA: Final = "shwfs_ao.science.long_exposure_result.v1"
FLUX_DENOMINATOR: Final = "normalized_source_grid_flux"
TEMPORAL_QUADRATURE: Final = "instantaneous_snapshot_rectangle_rule"
_RESIDUAL_FIELDS: Final = {
    "pre_update": "pre_update_residual_opd_m",
    "post_update": "post_update_residual_opd_m",
}
_RESIDUAL_LABELS: Final = {
    "pre_update": "pre-update residual measured by the WFS at each selected frame",
    "post_update": (
        "post-update residual: the same atmospheric sample with the frame's new "
        "correction (same-sample diagnostic, not a finite-shutter exposure)"
    ),
}


class LongExposureError(ValueError):
    """Raised for an invalid long-exposure configuration, frame, or result."""


def _positive_float(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise LongExposureError(f"{label} must be a positive real number.")
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise LongExposureError(f"{label} must be positive and finite.")
    return number


def _integer(value: object, *, label: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise LongExposureError(f"{label} must be an integer.")
    number = int(value)
    if number < minimum:
        raise LongExposureError(f"{label} must be >= {minimum}.")
    return number


@dataclass(frozen=True)
class LongExposureConfig:
    """Which frames, wavelengths, residual, and weights form the exposure.

    Frame ``k`` is selected when ``k >= burn_in_frames``,
    ``(k - burn_in_frames) % stride == 0``, and fewer than ``max_samples``
    frames have been selected.  ``sample_weights`` gives the quadrature weight
    of each selected sample in order; it requires ``max_samples`` equal to its
    length.  ``None`` means equal weights.
    """

    __hash_schema_id__: ClassVar[str] = "shwfs_ao.science.LongExposureConfig.v1"

    wavelengths_m: tuple[float, ...]
    burn_in_frames: int
    stride: int = 1
    max_samples: int | None = None
    residual: Literal["pre_update", "post_update"] = "pre_update"
    sample_weights: tuple[float, ...] | None = None

    def __post_init__(self) -> None:
        if isinstance(self.wavelengths_m, (str, bytes)) or not isinstance(
            self.wavelengths_m, Sequence
        ):
            raise LongExposureError("wavelengths_m must be a sequence.")
        wavelengths = tuple(
            _positive_float(value, label=f"wavelengths_m[{index}]")
            for index, value in enumerate(self.wavelengths_m)
        )
        if not wavelengths:
            raise LongExposureError("wavelengths_m must not be empty.")
        if any(b <= a for a, b in zip(wavelengths, wavelengths[1:])):
            raise LongExposureError("wavelengths_m must be strictly increasing.")
        burn_in = _integer(self.burn_in_frames, label="burn_in_frames", minimum=0)
        stride = _integer(self.stride, label="stride", minimum=1)
        max_samples = (
            None
            if self.max_samples is None
            else _integer(self.max_samples, label="max_samples", minimum=1)
        )
        if self.residual not in _RESIDUAL_FIELDS:
            raise LongExposureError(
                f"residual must be one of {sorted(_RESIDUAL_FIELDS)}."
            )
        weights: tuple[float, ...] | None = None
        if self.sample_weights is not None:
            if isinstance(self.sample_weights, (str, bytes)) or not isinstance(
                self.sample_weights, Sequence
            ):
                raise LongExposureError("sample_weights must be a sequence or None.")
            values: list[float] = []
            for index, value in enumerate(self.sample_weights):
                if isinstance(value, bool) or not isinstance(value, Real):
                    raise LongExposureError(f"sample_weights[{index}] must be real.")
                number = float(value)
                if not math.isfinite(number) or number < 0.0:
                    raise LongExposureError(
                        f"sample_weights[{index}] must be finite and non-negative."
                    )
                values.append(number)
            weights = tuple(values)
            if not weights or math.fsum(weights) <= 0.0:
                raise LongExposureError("sample_weights must have a positive sum.")
            if max_samples != len(weights):
                raise LongExposureError(
                    "explicit sample_weights require max_samples equal to their length."
                )
        object.__setattr__(self, "wavelengths_m", wavelengths)
        object.__setattr__(self, "burn_in_frames", burn_in)
        object.__setattr__(self, "stride", stride)
        object.__setattr__(self, "max_samples", max_samples)
        object.__setattr__(self, "sample_weights", weights)

    @property
    def residual_field(self) -> str:
        return _RESIDUAL_FIELDS[self.residual]

    @property
    def config_hash(self) -> str:
        return component_config_hash("science.long_exposure_config", self)

    def selects(self, frame_index: int, samples_taken: int) -> bool:
        if frame_index < self.burn_in_frames:
            return False
        if (frame_index - self.burn_in_frames) % self.stride:
            return False
        return self.max_samples is None or samples_taken < self.max_samples

    def weight(self, sample_index: int) -> float:
        if self.sample_weights is None:
            return 1.0
        return self.sample_weights[sample_index]


@dataclass(frozen=True)
class LongExposureSelection:
    """The exact frames and timing an exposure integrated."""

    first_frame: int
    last_frame: int
    stride: int
    sample_count: int
    burn_in_frames: int
    first_time_s: float
    last_time_s: float
    frame_period_s: float
    weight_sum: float
    uniform_weights: bool
    residual: str
    residual_description: str
    temporal_quadrature: str = TEMPORAL_QUADRATURE

    @property
    def sample_interval_s(self) -> float:
        return self.stride * self.frame_period_s

    @property
    def quadrature_exposure_s(self) -> float:
        """Rectangle-rule exposure ``N * stride * dt`` represented by the samples."""

        return self.sample_count * self.sample_interval_s

    @property
    def sample_center_span_s(self) -> float:
        """Elapsed time between the first and last sample centres."""

        return (self.sample_count - 1) * self.sample_interval_s

    def to_record(self) -> dict[str, Any]:
        return {
            "first_frame": self.first_frame,
            "last_frame": self.last_frame,
            "stride": self.stride,
            "sample_count": self.sample_count,
            "burn_in_frames": self.burn_in_frames,
            "first_time_s": self.first_time_s,
            "last_time_s": self.last_time_s,
            "frame_period_s": self.frame_period_s,
            "sample_interval_s": self.sample_interval_s,
            "quadrature_exposure_s": self.quadrature_exposure_s,
            "sample_center_span_s": self.sample_center_span_s,
            "weight_sum": self.weight_sum,
            "uniform_weights": self.uniform_weights,
            "residual": self.residual,
            "residual_description": self.residual_description,
            "temporal_quadrature": self.temporal_quadrature,
        }


@dataclass(frozen=True)
class LongExposureMetrics:
    """Final-image metrics, computed only after accumulation.

    ``peak_strehl`` compares the final image's maximum angular surface
    brightness (wherever it is) with the ideal image's peak;
    ``on_axis_strehl`` evaluates the final image at the optical axis instead.
    FWHM, EE50/EE80 and the radial profile are centred on the final-image
    peak.  EE fractions use the normalized-source-grid flux denominator.
    """

    wavelength_m: float
    lambda_over_d_rad: float
    peak_strehl: float
    on_axis_strehl: float
    peak_offset_xy_rad: tuple[float, float]
    fwhm_rad: float
    fwhm_lambda_over_d: float
    ee50_radius_rad: float
    ee80_radius_rad: float
    ideal_fwhm_rad: float
    ideal_ee50_radius_rad: float
    ideal_ee80_radius_rad: float
    centering: str = "final_image_peak_for_fwhm_ee_profile_optical_axis_for_on_axis_strehl"
    flux_denominator: str = FLUX_DENOMINATOR

    def to_record(self) -> dict[str, Any]:
        return {
            "wavelength_m": self.wavelength_m,
            "lambda_over_d_rad": self.lambda_over_d_rad,
            "peak_strehl": self.peak_strehl,
            "on_axis_strehl": self.on_axis_strehl,
            "peak_offset_xy_rad": list(self.peak_offset_xy_rad),
            "fwhm_rad": self.fwhm_rad,
            "fwhm_lambda_over_d": self.fwhm_lambda_over_d,
            "ee50_radius_rad": self.ee50_radius_rad,
            "ee80_radius_rad": self.ee80_radius_rad,
            "ideal_fwhm_rad": self.ideal_fwhm_rad,
            "ideal_ee50_radius_rad": self.ideal_ee50_radius_rad,
            "ideal_ee80_radius_rad": self.ideal_ee80_radius_rad,
            "centering": self.centering,
            "flux_denominator": self.flux_denominator,
        }


@dataclass(frozen=True)
class LongExposureImage:
    """One wavelength's accumulated image, its ideal reference, and metrics.

    ``psf`` reuses :class:`~shwfs_ao.core.types.PsfResult` because a weighted
    mean of unit-flux images on one grid at one wavelength is itself a
    unit-flux single-wavelength image.  ``radial_radius_rad`` and the two
    profiles are annulus means of angular surface brightness normalized by
    the ideal peak, about each image's own peak.
    """

    psf: PsfResult
    ideal_psf: PsfResult
    metrics: LongExposureMetrics
    radial_radius_rad: np.ndarray
    radial_profile: np.ndarray
    ideal_radial_profile: np.ndarray


@dataclass(frozen=True)
class LongExposureResult:
    """Aggregate long-exposure output with selection and identity metadata."""

    schema: str
    config: LongExposureConfig
    config_hash: str
    propagator_backend: str
    propagator_config_hash: str
    selection: LongExposureSelection
    images: tuple[LongExposureImage, ...]
    reset_count: int
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def image(self, wavelength_m: float) -> LongExposureImage:
        for image in self.images:
            if math.isclose(image.psf.wavelength_m, wavelength_m, rel_tol=1e-12):
                return image
        raise LongExposureError(f"no long-exposure image at {wavelength_m!r} m.")

    def to_record(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "config_hash": self.config_hash,
            "wavelengths_m": list(self.config.wavelengths_m),
            "residual": self.config.residual,
            "propagator_backend": self.propagator_backend,
            "propagator_config_hash": self.propagator_config_hash,
            "selection": self.selection.to_record(),
            "reset_count": self.reset_count,
            "flux_denominator": FLUX_DENOMINATOR,
            "metrics": [image.metrics.to_record() for image in self.images],
            "metadata": dict(self.metadata),
        }


def radial_profile_from_discrete_flux(
    discrete_pixel_flux: np.ndarray,
    x_angle_rad: np.ndarray,
    y_angle_rad: np.ndarray,
    *,
    center_xy_rad: tuple[float, float],
    bin_width_rad: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Area-weighted annulus means of angular surface brightness.

    Returns the mean radius of each occupied annulus and its mean surface
    brightness (flux / steradian).  Uses one ``bincount`` pass, so it is
    linear in the image size.
    """

    flux = np.asarray(discrete_pixel_flux, dtype=float)
    x = np.asarray(x_angle_rad, dtype=float)
    y = np.asarray(y_angle_rad, dtype=float)
    width = _positive_float(bin_width_rad, label="bin_width_rad")
    dx = np.gradient(x)
    dy = np.gradient(y)
    solid_angle = np.abs(dy)[:, None] * np.abs(dx)[None, :]
    radius = np.hypot(
        x[None, :] - float(center_xy_rad[0]),
        y[:, None] - float(center_xy_rad[1]),
    )
    index = np.floor(radius / width + 1.0e-12).astype(np.int64).ravel()
    area = np.bincount(index, weights=solid_angle.ravel())
    occupied = area > 0.0
    weighted_radius = np.bincount(index, weights=(radius * solid_angle).ravel())
    total_flux = np.bincount(index, weights=flux.ravel())
    return (
        weighted_radius[occupied] / area[occupied],
        total_flux[occupied] / area[occupied],
    )


def _immutable(values: np.ndarray) -> np.ndarray:
    contiguous = np.ascontiguousarray(np.asarray(values, dtype=float))
    return np.frombuffer(contiguous.tobytes(order="C"), dtype=float).reshape(
        contiguous.shape
    )


class StreamingLongExposure:
    """Accumulate long-exposure images from closed-loop frame observations.

    Parameters
    ----------
    propagator:
        The science propagator whose pupil, sampling and FFT convention every
        instantaneous and ideal image uses (normally ``ScaoSystem.science_propagator``).
    config:
        Frame selection, wavelengths, residual choice, and weights.
    telescope_diameter_m:
        Diameter used only to express metrics in ``lambda/D``.
    """

    def __init__(
        self,
        propagator: SciencePropagator,
        config: LongExposureConfig,
        *,
        telescope_diameter_m: float,
    ) -> None:
        if not isinstance(propagator, SciencePropagator):
            raise LongExposureError("propagator must implement SciencePropagator.")
        if not isinstance(config, LongExposureConfig):
            raise LongExposureError("config must be a LongExposureConfig.")
        self._propagator = propagator
        self._config = config
        self._diameter_m = _positive_float(
            telescope_diameter_m, label="telescope_diameter_m"
        )
        self._propagator_hash = propagator.config_hash
        self._requested = frozenset({config.residual_field})
        self._ideal: dict[float, PsfResult] = {}
        self._reset_count = 0
        self._clear()

    def _clear(self) -> None:
        self._sums: list[np.ndarray] | None = None
        self._x_axes: list[np.ndarray] = []
        self._y_axes: list[np.ndarray] = []
        self._sampling_metadata: list[Mapping[str, Any]] = []
        self._pupil_shape: tuple[int, int] | None = None
        self._weight_sum = 0.0
        self._samples = 0
        self._first_frame: int | None = None
        self._last_frame: int | None = None
        self._first_time_s = math.nan
        self._last_time_s = math.nan
        self._frame_period_s: float | None = None
        self._next_frame: int | None = None

    @property
    def requested_fields(self) -> frozenset[str]:
        return self._requested

    @property
    def config(self) -> LongExposureConfig:
        return self._config

    @property
    def sample_count(self) -> int:
        return self._samples

    @property
    def reset_count(self) -> int:
        return self._reset_count

    def reset(self) -> None:
        """Discard accumulated frames so the accumulator can be reused."""

        self._clear()
        self._reset_count += 1

    def retained_array_nbytes(self) -> int:
        """Bytes held in retained arrays (independent of the frame count)."""

        arrays: list[np.ndarray] = list(self._sums or [])
        arrays += self._x_axes + self._y_axes
        for psf in self._ideal.values():
            arrays += [psf.intensity, psf.x_angle_rad, psf.y_angle_rad]
        return int(sum(array.nbytes for array in arrays))

    def observe(self, observation: Any) -> None:
        """Consume one frame observation; non-selected frames cost nothing."""

        frame_index = int(observation.frame_index)
        period = float(observation.frame_period_s)
        if self._frame_period_s is None:
            self._frame_period_s = period
        elif not math.isclose(period, self._frame_period_s, rel_tol=1e-12, abs_tol=0.0):
            raise LongExposureError("frame period changed during an exposure.")
        if self._next_frame is not None and frame_index != self._next_frame:
            raise LongExposureError(
                f"frames must arrive in order: expected {self._next_frame}, got "
                f"{frame_index}; call reset() before a new run."
            )
        self._next_frame = frame_index + 1
        if not self._config.selects(frame_index, self._samples):
            return
        residual = getattr(observation, self._config.residual_field)
        if residual is None:
            raise LongExposureError(
                f"observation lacks {self._config.residual_field}; the loop must "
                "be given this accumulator as an observer."
            )
        self._accumulate(
            np.asarray(residual, dtype=float),
            weight=self._config.weight(self._samples),
            frame_index=frame_index,
            time_s=float(observation.time_s),
        )

    def add_opd(
        self,
        residual_opd_m: np.ndarray,
        *,
        frame_index: int,
        time_s: float,
        frame_period_s: float,
    ) -> None:
        """Feed one residual directly, with the same selection as :meth:`observe`."""

        observation = _DirectFrame(
            frame_index=frame_index,
            time_s=time_s,
            frame_period_s=frame_period_s,
            residual_field=self._config.residual_field,
            residual=np.asarray(residual_opd_m, dtype=float),
        )
        self.observe(observation)

    def _accumulate(
        self,
        residual: np.ndarray,
        *,
        weight: float,
        frame_index: int,
        time_s: float,
    ) -> None:
        if residual.ndim != 2:
            raise LongExposureError("residual OPD must be a 2-D map.")
        if self._pupil_shape is None:
            self._pupil_shape = (int(residual.shape[0]), int(residual.shape[1]))
        elif residual.shape != self._pupil_shape:
            raise LongExposureError("residual OPD shape changed during an exposure.")
        images = []
        for wavelength in self._config.wavelengths_m:
            psf = self._propagator.psf_from_opd(residual, wavelength)
            self._check_psf(psf, wavelength)
            images.append(psf)
        if self._sums is None:
            self._sums = [np.zeros_like(psf.intensity, dtype=float) for psf in images]
            self._x_axes = [_immutable(psf.x_angle_rad) for psf in images]
            self._y_axes = [_immutable(psf.y_angle_rad) for psf in images]
            self._sampling_metadata = [
                MappingProxyType(dict(psf.sampling_metadata)) for psf in images
            ]
        for index, psf in enumerate(images):
            if not (
                np.array_equal(psf.x_angle_rad, self._x_axes[index])
                and np.array_equal(psf.y_angle_rad, self._y_axes[index])
            ):
                raise LongExposureError(
                    "instantaneous images must share one angular grid per wavelength."
                )
            if weight != 0.0:
                self._sums[index] += weight * np.asarray(psf.intensity, dtype=float)
        self._weight_sum += weight
        self._samples += 1
        if self._first_frame is None:
            self._first_frame = frame_index
            self._first_time_s = time_s
        self._last_frame = frame_index
        self._last_time_s = time_s

    def _check_psf(self, psf: object, wavelength: float) -> None:
        if not isinstance(psf, PsfResult):
            raise LongExposureError("propagator must return a PsfResult.")
        if psf.normalization != "unit_total_flux":
            raise LongExposureError("instantaneous images must have unit total flux.")
        if not math.isclose(psf.wavelength_m, wavelength, rel_tol=1e-15, abs_tol=0.0):
            raise LongExposureError("propagator returned a different wavelength.")

    def ideal_psf(self, wavelength_m: float) -> PsfResult:
        """Cached zero-OPD image from the same propagator, grid and wavelength."""

        if self._pupil_shape is None:
            raise LongExposureError("no frame has fixed the pupil grid yet.")
        key = float(wavelength_m)
        cached = self._ideal.get(key)
        if cached is None:
            cached = self._propagator.psf_from_opd(
                np.zeros(self._pupil_shape, dtype=float), key
            )
            self._check_psf(cached, key)
            self._ideal[key] = cached
        return cached

    def result(self) -> LongExposureResult:
        """Normalize the sums and compute final-image metrics."""

        if self._sums is None or self._samples == 0:
            raise LongExposureError(
                "no frame was selected; check burn_in_frames, stride, and the run "
                "length."
            )
        if self._weight_sum <= 0.0:
            raise LongExposureError("selected sample weights sum to zero.")
        if self._propagator.config_hash != self._propagator_hash:
            raise LongExposureError("propagator identity changed during the exposure.")
        if (
            self._config.max_samples is not None
            and self._config.sample_weights is not None
            and self._samples != self._config.max_samples
        ):
            raise LongExposureError(
                f"explicit weights expect {self._config.max_samples} samples; the "
                f"run provided {self._samples}."
            )
        assert self._first_frame is not None and self._last_frame is not None
        assert self._frame_period_s is not None
        images = []
        for index, wavelength in enumerate(self._config.wavelengths_m):
            mean = self._sums[index] / self._weight_sum
            psf = PsfResult(
                intensity=mean,
                x_angle_rad=self._x_axes[index],
                y_angle_rad=self._y_axes[index],
                wavelength_m=wavelength,
                normalization="unit_total_flux",
                backend_name=self._propagator.backend_name,
                # The sampling contract is exactly the instantaneous images'
                # (and the ideal's); exposure bookkeeping lives on the result.
                sampling_metadata=dict(self._sampling_metadata[index]),
            )
            images.append(self._image(psf, self.ideal_psf(wavelength)))
        selection = LongExposureSelection(
            first_frame=self._first_frame,
            last_frame=self._last_frame,
            stride=self._config.stride,
            sample_count=self._samples,
            burn_in_frames=self._config.burn_in_frames,
            first_time_s=self._first_time_s,
            last_time_s=self._last_time_s,
            frame_period_s=self._frame_period_s,
            weight_sum=self._weight_sum,
            uniform_weights=self._config.sample_weights is None,
            residual=self._config.residual,
            residual_description=_RESIDUAL_LABELS[self._config.residual],
        )
        return LongExposureResult(
            schema=LONG_EXPOSURE_RESULT_SCHEMA,
            config=self._config,
            config_hash=self._config.config_hash,
            propagator_backend=self._propagator.backend_name,
            propagator_config_hash=self._propagator_hash,
            selection=selection,
            images=tuple(images),
            reset_count=self._reset_count,
            metadata=MappingProxyType(
                {
                    "flux_denominator": FLUX_DENOMINATOR,
                    "temporal_quadrature": TEMPORAL_QUADRATURE,
                    "recentering": "none",
                    "coaddition": "intensity",
                }
            ),
        )

    def _image(self, psf: PsfResult, ideal: PsfResult) -> LongExposureImage:
        wavelength = psf.wavelength_m
        lod = lambda_over_d_rad(wavelength, self._diameter_m)
        brightness = discrete_flux_to_angular_surface_brightness(psf)
        ideal_brightness = discrete_flux_to_angular_surface_brightness(ideal)
        ideal_peak = float(np.max(ideal_brightness))
        row, column = np.unravel_index(int(np.argmax(brightness)), brightness.shape)
        peak_xy = (float(psf.x_angle_rad[column]), float(psf.y_angle_rad[row]))
        axis_column = int(np.argmin(np.abs(psf.x_angle_rad)))
        axis_row = int(np.argmin(np.abs(psf.y_angle_rad)))
        ideal_row, ideal_column = np.unravel_index(
            int(np.argmax(ideal_brightness)), ideal_brightness.shape
        )
        ideal_xy = (
            float(ideal.x_angle_rad[ideal_column]),
            float(ideal.y_angle_rad[ideal_row]),
        )
        bin_width = float(
            min(np.min(np.diff(psf.x_angle_rad)), np.min(np.diff(psf.y_angle_rad)))
        )
        radius, profile = radial_profile_from_discrete_flux(
            psf.intensity,
            psf.x_angle_rad,
            psf.y_angle_rad,
            center_xy_rad=peak_xy,
            bin_width_rad=bin_width,
        )
        ideal_radius, ideal_profile = radial_profile_from_discrete_flux(
            ideal.intensity,
            ideal.x_angle_rad,
            ideal.y_angle_rad,
            center_xy_rad=ideal_xy,
            bin_width_rad=bin_width,
        )
        count = min(radius.size, ideal_radius.size)
        fwhm = _safe_fwhm(brightness, psf)
        metrics = LongExposureMetrics(
            wavelength_m=wavelength,
            lambda_over_d_rad=lod,
            peak_strehl=peak_strehl_from_discrete_flux(psf, ideal),
            on_axis_strehl=float(brightness[axis_row, axis_column] / ideal_peak),
            peak_offset_xy_rad=peak_xy,
            fwhm_rad=fwhm,
            fwhm_lambda_over_d=fwhm / lod,
            ee50_radius_rad=encircled_energy_radius_from_discrete_flux(
                psf.intensity, psf.x_angle_rad, psf.y_angle_rad, 0.5
            ),
            ee80_radius_rad=encircled_energy_radius_from_discrete_flux(
                psf.intensity, psf.x_angle_rad, psf.y_angle_rad, 0.8
            ),
            ideal_fwhm_rad=_safe_fwhm(ideal_brightness, ideal),
            ideal_ee50_radius_rad=encircled_energy_radius_from_discrete_flux(
                ideal.intensity, ideal.x_angle_rad, ideal.y_angle_rad, 0.5
            ),
            ideal_ee80_radius_rad=encircled_energy_radius_from_discrete_flux(
                ideal.intensity, ideal.x_angle_rad, ideal.y_angle_rad, 0.8
            ),
        )
        return LongExposureImage(
            psf=psf,
            ideal_psf=ideal,
            metrics=metrics,
            radial_radius_rad=_immutable(radius[:count]),
            radial_profile=_immutable(profile[:count] / ideal_peak),
            ideal_radial_profile=_immutable(ideal_profile[:count] / ideal_peak),
        )


def _safe_fwhm(brightness: np.ndarray, psf: PsfResult) -> float:
    try:
        return fwhm_diameter_from_angular_surface_brightness(
            brightness, psf.x_angle_rad, psf.y_angle_rad
        )
    except ScienceMetricsError:
        return math.nan


@dataclass(frozen=True)
class _DirectFrame:
    frame_index: int
    time_s: float
    frame_period_s: float
    residual_field: str
    residual: np.ndarray

    def __getattr__(self, name: str) -> Any:
        if name in _RESIDUAL_FIELDS.values():
            return self.residual if name == self.residual_field else None
        raise AttributeError(name)
