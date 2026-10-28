"""Configuration bundle selecting the physical detector path.

A :class:`PhysicalDetectorConfig` names everything the physical camera path
needs beyond the optics backend: the camera, the detector-pixel layout, the
source and sky budget, the WFS bandpass, the detector-plane sampling, the RTC
pixel processing, the exposure and its optional time sub-sampling.  Its
presence selects ``shwfs_ao.detector.physical_camera.v1``; without it a
sensor stays on the AO-REF-004 compatibility chain.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Integral, Real
from typing import Literal

from ..core.hashing import component_config_hash
from ..core.spectral import (
    SpectralQuadrature,
    gauss_legendre_quadrature,
    midpoint_quadrature,
    monochromatic_quadrature,
)
from .camera import CameraConfig
from .layout import LAYOUT_SCHEMES
from .photometry import (
    ab_magnitude_to_fnu,
    flat_fnu_flambda,
    scale_incident_photons,
    sky_electrons_per_pixel,
    source_electron_budget,
)
from .processing import PixelProcessingConfig


__all__ = (
    "PhysicalConfigError",
    "SourceBudgetConfig",
    "BandpassConfig",
    "DetectorPlaneSamplingConfig",
    "PhysicalDetectorConfig",
    "PhysicalBudget",
    "physical_budget",
)


class PhysicalConfigError(ValueError):
    """Raised when a physical detector configuration is inconsistent."""


@dataclass(frozen=True)
class SourceBudgetConfig:
    """Source and sky budget.  Exactly one source quantity is declared.

    ``ab_flat_fnu``: an AB magnitude of a spectrum flat in ``f_nu`` across the
    WFS band, with ``throughput_excluding_qe``; the camera QE is applied once
    by the photometry.  ``incident_photons``: photons per frame reaching the
    detector from a full, unobstructed subaperture; the camera QE is applied
    once.  ``detected_electrons``: detected photoelectrons per frame from a
    full subaperture; no QE is applied.  Every per-subaperture budget then
    scales with the subaperture's illuminated area.  The sky is an AB surface
    brightness in the WFS band (``None`` for no sky).
    """

    __hash_schema_id__ = "shwfs_ao.detector.SourceBudgetConfig.v1"

    kind: Literal["ab_flat_fnu", "incident_photons", "detected_electrons"]
    ab_magnitude: float | None = None
    incident_photons_per_full_subap_frame: float | None = None
    detected_e_per_full_subap_frame: float | None = None
    throughput_excluding_qe: float | None = None
    sky_ab_mag_per_arcsec2: float | None = None

    def __post_init__(self) -> None:
        declared = {
            "ab_flat_fnu": self.ab_magnitude,
            "incident_photons": self.incident_photons_per_full_subap_frame,
            "detected_electrons": self.detected_e_per_full_subap_frame,
        }
        if self.kind not in declared:
            raise PhysicalConfigError(f"unknown source kind {self.kind!r}.")
        stated = [name for name, value in declared.items() if value is not None]
        if stated != [self.kind]:
            raise PhysicalConfigError(
                "exactly one source quantity must be declared, matching kind "
                f"{self.kind!r}; got values for {stated}."
            )
        if self.kind == "ab_flat_fnu":
            _finite(self.ab_magnitude, "ab_magnitude")
            if self.throughput_excluding_qe is None:
                raise PhysicalConfigError("ab_flat_fnu needs throughput_excluding_qe.")
        elif self.throughput_excluding_qe is not None:
            raise PhysicalConfigError(
                f"{self.kind} budgets are stated at the detector; "
                "throughput_excluding_qe must be null."
            )
        for name in ("incident_photons_per_full_subap_frame", "detected_e_per_full_subap_frame"):
            value = getattr(self, name)
            if value is not None and _finite(value, name) < 0.0:
                raise PhysicalConfigError(f"{name} must be non-negative.")
        if self.throughput_excluding_qe is not None:
            value = _finite(self.throughput_excluding_qe, "throughput_excluding_qe")
            if not 0.0 < value <= 1.0:
                raise PhysicalConfigError("throughput_excluding_qe must be in (0, 1].")
        if self.sky_ab_mag_per_arcsec2 is not None:
            _finite(self.sky_ab_mag_per_arcsec2, "sky_ab_mag_per_arcsec2")
            if self.kind != "ab_flat_fnu":
                raise PhysicalConfigError(
                    "a sky surface brightness needs the photometric (ab_flat_fnu) "
                    "source budget, which states the throughput it passes through."
                )


@dataclass(frozen=True)
class BandpassConfig:
    """WFS bandpass and its wavelength quadrature (B05)."""

    __hash_schema_id__ = "shwfs_ao.detector.BandpassConfig.v1"

    kind: Literal["monochromatic", "gauss_legendre", "midpoint"]
    band_min_m: float
    band_max_m: float
    n_samples: int = 1

    def __post_init__(self) -> None:
        low = _finite(self.band_min_m, "band_min_m")
        high = _finite(self.band_max_m, "band_max_m")
        if not 0.0 < low < high:
            raise PhysicalConfigError("bandpass needs 0 < band_min_m < band_max_m.")
        if isinstance(self.n_samples, bool) or not isinstance(self.n_samples, Integral) or self.n_samples < 1:
            raise PhysicalConfigError("n_samples must be a positive integer.")
        if self.kind == "monochromatic" and self.n_samples != 1:
            raise PhysicalConfigError("a monochromatic bandpass has n_samples = 1.")
        if self.kind not in ("monochromatic", "gauss_legendre", "midpoint"):
            raise PhysicalConfigError(f"unknown bandpass kind {self.kind!r}.")

    def quadrature(self, wfs_wavelength_m: float) -> SpectralQuadrature:
        """Nodes and weights; a monochromatic band uses ``wfs_wavelength_m``."""

        if self.kind == "monochromatic":
            centre = float(wfs_wavelength_m)
            if not self.band_min_m <= centre <= self.band_max_m:
                raise PhysicalConfigError("wfs_wavelength_m must lie inside the declared band.")
            quadrature = monochromatic_quadrature(centre, self.band_max_m - self.band_min_m)
            return quadrature
        if self.kind == "gauss_legendre":
            return gauss_legendre_quadrature(self.band_min_m, self.band_max_m, int(self.n_samples))
        return midpoint_quadrature(self.band_min_m, self.band_max_m, int(self.n_samples))


@dataclass(frozen=True)
class DetectorPlaneSamplingConfig:
    """How lenslet intensities reach detector pixels (DET-03).

    ``legacy_fft``: the frozen FFT point sampling (``pad_factor`` pixels per
    lambda/d at the WFS wavelength); no pixel integration, diffusion or
    polychromatic sensing.  ``mft_pixel_integrated``: a declared angular pixel
    scale, ``oversampling`` Gauss--Legendre nodes per pixel and axis, pixel
    area integration and charge diffusion of Gaussian sigma
    ``diffusion_sigma_px`` (pixels).
    """

    __hash_schema_id__ = "shwfs_ao.detector.DetectorPlaneSamplingConfig.v1"

    kind: Literal["legacy_fft", "mft_pixel_integrated"]
    pixel_scale_rad: float | None = None
    oversampling: int = 1
    diffusion_sigma_px: float = 0.0

    def __post_init__(self) -> None:
        if self.kind == "legacy_fft":
            if self.pixel_scale_rad is not None or self.oversampling != 1 or self.diffusion_sigma_px != 0.0:
                raise PhysicalConfigError(
                    "legacy_fft sampling is set by pad_factor; pixel_scale_rad, "
                    "oversampling and diffusion belong to mft_pixel_integrated."
                )
        elif self.kind == "mft_pixel_integrated":
            if self.pixel_scale_rad is None or not _finite(self.pixel_scale_rad, "pixel_scale_rad") > 0.0:
                raise PhysicalConfigError("mft_pixel_integrated needs a positive pixel_scale_rad.")
            if isinstance(self.oversampling, bool) or not isinstance(self.oversampling, Integral) or not 1 <= self.oversampling <= 32:
                raise PhysicalConfigError("oversampling must be an integer in [1, 32].")
            sigma = _finite(self.diffusion_sigma_px, "diffusion_sigma_px")
            if not 0.0 <= sigma <= 2.0:
                raise PhysicalConfigError("diffusion_sigma_px must be in [0, 2].")
        else:
            raise PhysicalConfigError(f"unknown sampling kind {self.kind!r}.")


@dataclass(frozen=True)
class PhysicalDetectorConfig:
    """Everything the physical camera path needs besides the optics backend."""

    __hash_schema_id__ = "shwfs_ao.detector.PhysicalDetectorConfig.v1"

    camera: CameraConfig
    layout_scheme: str
    guard_px: int
    source: SourceBudgetConfig
    bandpass: BandpassConfig
    sampling: DetectorPlaneSamplingConfig
    processing: PixelProcessingConfig
    exposure_s: float
    exposure_subsamples: int = 1
    # Detected photoelectrons per frame of a full subaperture from a bright
    # internal calibration source, or None to calibrate at the operating
    # budget.  When set, the deterministic reference path (reference
    # centroids and interaction-matrix probes) observes this source without
    # sky; noisy measurements keep the operating budget.
    calibration_source_detected_e_per_full_subap_frame: float | None = None

    def __post_init__(self) -> None:
        for value, kind, label in (
            (self.camera, CameraConfig, "camera"),
            (self.source, SourceBudgetConfig, "source"),
            (self.bandpass, BandpassConfig, "bandpass"),
            (self.sampling, DetectorPlaneSamplingConfig, "sampling"),
            (self.processing, PixelProcessingConfig, "processing"),
        ):
            if not isinstance(value, kind):
                raise PhysicalConfigError(f"{label} has the wrong type.")
        if self.layout_scheme not in LAYOUT_SCHEMES:
            raise PhysicalConfigError(f"unknown layout scheme {self.layout_scheme!r}.")
        if isinstance(self.guard_px, bool) or not isinstance(self.guard_px, Integral) or self.guard_px < 0:
            raise PhysicalConfigError("guard_px must be a non-negative integer.")
        if self.camera.has_coupling and self.guard_px < 1:
            raise PhysicalConfigError(
                "electronic coupling needs a guard ring of at least one pixel so "
                "window pixels couple to real neighbouring pixels."
            )
        if _finite(self.exposure_s, "exposure_s") <= 0.0:
            raise PhysicalConfigError("exposure_s must be positive.")
        if isinstance(self.exposure_subsamples, bool) or not isinstance(self.exposure_subsamples, Integral) or not 1 <= self.exposure_subsamples <= 64:
            raise PhysicalConfigError("exposure_subsamples must be an integer in [1, 64].")
        if self.sampling.kind == "legacy_fft" and self.bandpass.kind != "monochromatic":
            raise PhysicalConfigError(
                "a polychromatic bandpass needs mft_pixel_integrated sampling: the "
                "legacy FFT pixel scale is tied to one wavelength."
            )
        source = self.calibration_source_detected_e_per_full_subap_frame
        if source is not None and not _finite(source, "calibration_source_detected_e_per_full_subap_frame") > 0.0:
            raise PhysicalConfigError("a calibration source needs a positive budget.")

    @property
    def config_hash(self) -> str:
        if self.calibration_source_detected_e_per_full_subap_frame is None:
            # Without a calibration source, hash the shape the class had
            # before the field existed, so those identities never move.
            return component_config_hash(
                "physical_detector",
                _PhysicalDetectorConfigWithoutCalibrationSource(
                    camera=self.camera,
                    layout_scheme=self.layout_scheme,
                    guard_px=self.guard_px,
                    source=self.source,
                    bandpass=self.bandpass,
                    sampling=self.sampling,
                    processing=self.processing,
                    exposure_s=self.exposure_s,
                    exposure_subsamples=self.exposure_subsamples,
                ),
            )
        return component_config_hash("physical_detector", self)


@dataclass(frozen=True)
class _PhysicalDetectorConfigWithoutCalibrationSource:
    """Frozen hash shape of :class:`PhysicalDetectorConfig` without a source."""

    __hash_schema_id__ = "shwfs_ao.detector.PhysicalDetectorConfig.v1"

    camera: CameraConfig
    layout_scheme: str
    guard_px: int
    source: SourceBudgetConfig
    bandpass: BandpassConfig
    sampling: DetectorPlaneSamplingConfig
    processing: PixelProcessingConfig
    exposure_s: float
    exposure_subsamples: int


@dataclass(frozen=True)
class PhysicalBudget:
    """Full-subaperture budgets and spectral weights (pre-window, pre-PRNU)."""

    full_subaperture_area_m2: float
    detected_e_full_subap: float
    incident_photons_full_subap: float | None
    sky_e_per_pixel_full_subap: float
    spectral_weights: tuple[float, ...]
    wavelength_m: tuple[float, ...]


def physical_budget(
    config: PhysicalDetectorConfig,
    *,
    wfs_wavelength_m: float,
    full_subaperture_area_m2: float,
    pixel_solid_angle_sr: float,
) -> PhysicalBudget:
    """Evaluate the declared source and sky budget for a full subaperture."""

    area = _finite(full_subaperture_area_m2, "full_subaperture_area_m2")
    quadrature = config.bandpass.quadrature(wfs_wavelength_m)
    source = config.source
    qe = config.camera.quantum_efficiency
    incident: float | None
    if source.kind == "ab_flat_fnu":
        assert source.ab_magnitude is not None and source.throughput_excluding_qe is not None
        budget = source_electron_budget(
            quadrature,
            flambda_w_m2_m=flat_fnu_flambda(ab_magnitude_to_fnu(source.ab_magnitude), quadrature.wavelength_m),
            throughput=source.throughput_excluding_qe,
            quantum_efficiency=qe,
            area_m2=area,
            exposure_s=config.exposure_s,
        )
        detected = budget.detected_e
        incident = budget.incident_photons
        weights = tuple(float(v) for v in budget.spectral_weights)
    else:
        # A direct budget carries no spectrum: the node weights are the
        # quadrature weights of a spectrum flat in photon number per unit
        # wavelength, the declared assumption for direct budgets.
        total = float(sum(quadrature.weight_m))
        weights = tuple(float(w) / total for w in quadrature.weight_m)
        if source.kind == "incident_photons":
            assert source.incident_photons_per_full_subap_frame is not None
            incident = float(source.incident_photons_per_full_subap_frame)
            detected = scale_incident_photons(incident, qe)
        else:
            assert source.detected_e_per_full_subap_frame is not None
            incident = None
            detected = float(source.detected_e_per_full_subap_frame)
    sky = 0.0
    if source.sky_ab_mag_per_arcsec2 is not None:
        assert source.throughput_excluding_qe is not None
        sky = sky_electrons_per_pixel(
            quadrature,
            surface_brightness_ab_mag_arcsec2=source.sky_ab_mag_per_arcsec2,
            pixel_solid_angle_sr=pixel_solid_angle_sr,
            throughput=source.throughput_excluding_qe,
            quantum_efficiency=qe,
            area_m2=area,
            exposure_s=config.exposure_s,
        )
    return PhysicalBudget(
        full_subaperture_area_m2=area,
        detected_e_full_subap=float(detected),
        incident_photons_full_subap=incident,
        sky_e_per_pixel_full_subap=float(sky),
        spectral_weights=weights,
        wavelength_m=tuple(float(v) for v in quadrature.wavelength_m),
    )


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise PhysicalConfigError(f"{label} must be a real number.")
    result = float(value)
    if not math.isfinite(result):
        raise PhysicalConfigError(f"{label} must be finite.")
    return result
