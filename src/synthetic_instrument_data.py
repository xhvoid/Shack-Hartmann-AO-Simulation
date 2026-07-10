# 2 m detector-level SH-WFS helpers build pupil/subaperture geometry, reference centroids, finite centroid measurements, detector-noise diagnostics, and tilt response matrices.

"""Synthetic instrument data helpers for the realistic 2 m SCAO demo.

This module wraps the lower-level detector SH-WFS functions with explicit
configuration objects and diagnostics. It is intentionally still synthetic:
values are not private instrument calibration data, and any public-data
replacement should preserve the same units/provenance contract.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

import numpy as np

from data_sources import ALLOWED_SOURCE_CLASSES
from reconstruction import subaperture_masks
from shwfs_detector import crop_center, lenslet_spot_from_phase, centroid


DEFAULT_WFS_WAVELENGTH_M = 700.0e-9
DEFAULT_SOURCE_CLASS = "synthetic_assumed"
MIN_VALID_CENTROID_FRACTION = 0.0


class SyntheticInstrumentError(ValueError):
    """Raised when a synthetic detector/WFS configuration is invalid."""


@dataclass(frozen=True)
class CentroidValidityConfig:
    """Thresholds for accepting a detector-level centroid as physically valid.

    A finite centre of gravity is necessary but not sufficient: a faint,
    noise-dominated lenslet spot can still return a finite centroid built from
    background and read noise. These thresholds add flux, peak-SNR,
    centroid-uncertainty, and window-clipping criteria so that sub-photon / faint
    cases are not silently reported as fully valid.

    Args:
        min_flux_e: Minimum expected source signal in the window (electrons).
        min_peak_snr: Minimum expected peak-pixel signal-to-noise ratio.
        max_centroid_sigma_px: Maximum centroid-uncertainty proxy (pixels).
        max_window_clipping_fraction: Maximum fraction of spot energy allowed to
            fall outside the detector window.

    Physics note:
        Defaults are conservative engineering values for a compact educational
        SH-WFS, not a calibrated detector specification. They are tunable and
        documented so faint-photon validity behaviour is explicit, not hidden.
    """

    min_flux_e: float = 30.0
    min_peak_snr: float = 3.0
    max_centroid_sigma_px: float = 0.5
    max_window_clipping_fraction: float = 0.15

    def __post_init__(self) -> None:
        for name in ("min_flux_e", "min_peak_snr", "max_centroid_sigma_px", "max_window_clipping_fraction"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise SyntheticInstrumentError(f"{name} must be finite and non-negative; got {value!r}.")
        if float(self.max_window_clipping_fraction) > 1.0:
            raise SyntheticInstrumentError("max_window_clipping_fraction must be between 0 and 1.")


# Default centroid-validity thresholds used when a caller does not supply one.
DEFAULT_CENTROID_VALIDITY = CentroidValidityConfig()


@dataclass(frozen=True)
class DetectorConfig:
    """Detector-noise configuration for the detector-level SH-WFS model.

    Args:
        photons_per_subap_frame: Guide-star photons per subaperture per frame.
            Set to ``None`` for deterministic no-noise spot images.
        read_noise_e: Gaussian read noise RMS in electrons per pixel.
        dark_e_per_s: Dark current in electrons per second per pixel.
        background_e_per_pixel_frame: Background in electrons per pixel per
            frame.
        full_well_e: Optional full-well clipping level in electrons.
        qe: Quantum efficiency in electrons per photon.
        bad_pixel_mask: Optional boolean mask where true pixels are forced to
            zero after detector effects.
        prnu_rms: Pixel response non-uniformity RMS as a fractional standard
            deviation.
        exposure_s: Frame exposure time in seconds.
        source_class: Provenance class from the documented source-class taxonomy.
        source_note: Human-readable source note.

    Returns:
        Immutable detector configuration.

    Raises:
        SyntheticInstrumentError: If physical scalars are negative/non-finite
            or if ``source_class`` is outside the permitted taxonomy.

    Physics note:
        Photon noise is sampled after converting photons to photo-electrons
        with ``qe``. Dark current, background, PRNU, bad pixels, full well, and
        read noise are compact detector realism terms for studies.
    """

    photons_per_subap_frame: float | None = None
    read_noise_e: float = 0.0
    dark_e_per_s: float = 0.0
    background_e_per_pixel_frame: float = 0.0
    full_well_e: float | None = None
    qe: float = 1.0
    bad_pixel_mask: np.ndarray | None = None
    prnu_rms: float = 0.0
    exposure_s: float = 1.0e-3
    source_class: str = DEFAULT_SOURCE_CLASS
    source_note: str = "Synthetic detector settings for unit tests and fast-mode demos."

    def __post_init__(self) -> None:
        if self.source_class not in ALLOWED_SOURCE_CLASSES:
            raise SyntheticInstrumentError(
                f"source_class={self.source_class!r} is not in the permitted taxonomy "
                f"{sorted(ALLOWED_SOURCE_CLASSES)}."
            )
        if not str(self.source_note).strip():
            raise SyntheticInstrumentError("source_note must be a non-empty string.")
        if self.photons_per_subap_frame is not None:
            _require_nonnegative("photons_per_subap_frame", self.photons_per_subap_frame)
        _require_nonnegative("read_noise_e", self.read_noise_e)
        _require_nonnegative("dark_e_per_s", self.dark_e_per_s)
        _require_nonnegative("background_e_per_pixel_frame", self.background_e_per_pixel_frame)
        _require_positive("qe", self.qe)
        _require_nonnegative("prnu_rms", self.prnu_rms)
        _require_positive("exposure_s", self.exposure_s)
        if self.full_well_e is not None:
            _require_positive("full_well_e", self.full_well_e)


@dataclass(frozen=True)
class DetectorPreset:
    """Named detector-quality preset for the 700 nm visible SH-WFS detector.

    A preset fixes detector *quality* (read noise, dark current, background,
    full well, PRNU, bad-pixel fraction) independently of the guide-star photon
    budget, which is supplied per run via :meth:`to_detector_config`. These are
    synthetic engineering presets for a visible Shack-Hartmann WFS detector;
    they are not measured calibration frames and must not be mixed with NIR
    science-camera assumptions.

    Args:
        preset_name: Short identifier (e.g. ``"low_noise_sCMOS_like"``).
        read_noise_e: Gaussian read noise RMS in electrons per pixel.
        dark_e_per_s: Dark current in electrons per second per pixel.
        background_e_per_pixel_frame: Background electrons per pixel per frame.
        full_well_e: Full-well clipping level in electrons, or ``None`` for no
            saturation.
        prnu_rms: Pixel response non-uniformity RMS (fractional).
        bad_pixel_fraction: Fraction of pixels flagged dead (0..1).
        exposure_s: Frame exposure time in seconds.
        source_class: Provenance class (synthetic_assumed for these presets).
        source_note: Human-readable provenance note.

    Physics note:
        Detector quality is held separate from photon budget so a faint and a
        bright guide-star run can reuse the same detector preset; the preset
        describes a visible (700 nm) WFS sensor, not a NIR science camera.
    """

    preset_name: str
    read_noise_e: float
    dark_e_per_s: float
    background_e_per_pixel_frame: float
    full_well_e: float | None
    prnu_rms: float
    bad_pixel_fraction: float
    exposure_s: float = 1.0e-3
    source_class: str = "synthetic_assumed"
    source_note: str = "Synthetic visible SH-WFS detector-quality preset; not a measured detector calibration."

    def __post_init__(self) -> None:
        if not str(self.preset_name).strip():
            raise SyntheticInstrumentError("preset_name must be a non-empty string.")
        _require_nonnegative("read_noise_e", self.read_noise_e)
        _require_nonnegative("dark_e_per_s", self.dark_e_per_s)
        _require_nonnegative("background_e_per_pixel_frame", self.background_e_per_pixel_frame)
        _require_nonnegative("prnu_rms", self.prnu_rms)
        _require_positive("exposure_s", self.exposure_s)
        if not (0.0 <= float(self.bad_pixel_fraction) <= 1.0):
            raise SyntheticInstrumentError(
                f"bad_pixel_fraction must be between 0 and 1; got {self.bad_pixel_fraction!r}."
            )
        if self.full_well_e is not None:
            _require_positive("full_well_e", self.full_well_e)
        if self.source_class not in ALLOWED_SOURCE_CLASSES:
            raise SyntheticInstrumentError(
                f"source_class={self.source_class!r} is not in the permitted taxonomy "
                f"{sorted(ALLOWED_SOURCE_CLASSES)}."
            )
        if not str(self.source_note).strip():
            raise SyntheticInstrumentError("source_note must be a non-empty string.")

    def to_detector_config(
        self,
        photons_per_subap_frame: float | None,
        *,
        window_px: int | None = None,
        seed: int | None = None,
        qe: float = 1.0,
    ) -> "DetectorConfig":
        """Build a :class:`DetectorConfig` from this preset and a photon budget.

        Args:
            photons_per_subap_frame: Guide-star photons per subaperture per
                frame, or ``None`` for a deterministic no-noise spot.
            window_px: Detector window size; required together with ``seed`` to
                realise a bad-pixel mask from ``bad_pixel_fraction``.
            seed: Seed for the deterministic bad-pixel mask.
            qe: Quantum efficiency in electrons per photon.

        Returns:
            A :class:`DetectorConfig` carrying this preset's noise terms.
        """

        bad_pixel_mask = None
        if self.bad_pixel_fraction > 0.0 and window_px is not None and seed is not None:
            bad_pixel_mask = make_bad_pixel_mask(int(window_px), float(self.bad_pixel_fraction), seed=int(seed))
        return DetectorConfig(
            photons_per_subap_frame=photons_per_subap_frame,
            read_noise_e=self.read_noise_e,
            dark_e_per_s=self.dark_e_per_s,
            background_e_per_pixel_frame=self.background_e_per_pixel_frame,
            full_well_e=self.full_well_e,
            qe=qe,
            bad_pixel_mask=bad_pixel_mask,
            prnu_rms=self.prnu_rms,
            exposure_s=self.exposure_s,
            source_class=self.source_class,
            source_note=f"{self.source_note} (preset={self.preset_name})",
        )


def make_bad_pixel_mask(window_px: int, bad_pixel_fraction: float, *, seed: int) -> np.ndarray:
    """Return a deterministic boolean bad-pixel mask for a square window.

    Args:
        window_px: Square detector-window size in pixels.
        bad_pixel_fraction: Fraction of pixels to flag dead (0..1).
        seed: Seed for reproducibility.

    Returns:
        Boolean array of shape ``(window_px, window_px)`` where ``True`` marks a
        dead pixel.

    Raises:
        SyntheticInstrumentError: If ``window_px`` < 1 or fraction out of range.

    Physics note:
        Dead pixels are forced to zero after detector effects, lowering local
        flux and biasing centroids near affected subaperture spots.
    """

    if window_px < 1:
        raise SyntheticInstrumentError(f"window_px must be >= 1 for a bad-pixel mask; got {window_px!r}.")
    if not (0.0 <= bad_pixel_fraction <= 1.0):
        raise SyntheticInstrumentError(
            f"bad_pixel_fraction must be between 0 and 1; got {bad_pixel_fraction!r}."
        )
    rng = np.random.default_rng(seed)
    return rng.random((window_px, window_px)) < bad_pixel_fraction


@dataclass(frozen=True)
class ShwfsGeometryConfig:
    """Geometry configuration for a 2 m detector-level Shack-Hartmann WFS.

    Args:
        telescope_diameter_m: Pupil diameter in metres.
        n_pupil_pixels: Square pupil sampling.
        n_lenslets: Lenslets/subapertures across the pupil diameter.
        min_fill_fraction: Minimum illuminated pixel fraction for retaining a
            subaperture.
        pad_factor: FFT padding factor for each lenslet spot.
        detector_window_px: Square detector window size per lenslet.
        threshold_fraction: Fraction of peak below which centroid pixels are
            discarded.
        subtract_minimum: Whether to subtract the minimum pixel value before
            centroiding.
        central_obstruction_ratio: Optional central obstruction diameter
            divided by telescope diameter.
        spider_width_m: Optional cross-spider width in metres.
        wfs_wavelength_m: Phase reference wavelength for WFS phase maps.
        source_class: Provenance class from the documented source-class taxonomy.
        source_note: Human-readable source note.

    Returns:
        Immutable SH-WFS geometry configuration.

    Raises:
        SyntheticInstrumentError: If geometry scalars are outside physical
            ranges or ``source_class`` is invalid.

    Physics note:
        The module stores phase maps in radians at ``wfs_wavelength_m``.
        Centroid shifts are reported in detector pixels after lenslet FFT spot
        formation and reference-centroid subtraction.
    """

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
        _require_positive("telescope_diameter_m", self.telescope_diameter_m)
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
        _require_nonnegative("threshold_fraction", self.threshold_fraction)
        if not (0.0 <= self.central_obstruction_ratio < 1.0):
            raise SyntheticInstrumentError("central_obstruction_ratio must be >= 0 and < 1.")
        _require_nonnegative("spider_width_m", self.spider_width_m)
        _require_positive("wfs_wavelength_m", self.wfs_wavelength_m)
        if self.source_class not in ALLOWED_SOURCE_CLASSES:
            raise SyntheticInstrumentError(
                f"source_class={self.source_class!r} is not in the permitted taxonomy "
                f"{sorted(ALLOWED_SOURCE_CLASSES)}."
            )
        if not str(self.source_note).strip():
            raise SyntheticInstrumentError("source_note must be a non-empty string.")


@dataclass(frozen=True)
class DetectorShwfsCalibration:
    """Reference-centroid calibration for one detector-level SH-WFS geometry.

    Args:
        geometry: SH-WFS geometry configuration.
        detector: Detector configuration used for later measurements.
        x_m: X-coordinate pupil grid in metres.
        y_m: Y-coordinate pupil grid in metres.
        pupil_mask: Boolean pupil mask.
        centers_m: Valid subaperture centers in metres.
        subaperture_masks: Boolean mask for each valid subaperture.
        reference_centroids_px: Zero-phase reference centroids in detector
            pixels.
        valid_subaperture_fraction: Fraction of lenslet cells retained after
            the fill-fraction cut.

    Returns:
        Immutable calibration bundle.

    Raises:
        SyntheticInstrumentError: Built by ``build_detector_shwfs_calibration``
            after finite-value checks pass.

    Physics note:
        The reference is computed from a zero-phase pupil using the same
        detector window and centroid settings as later measurements. This
        avoids mixing geometric lenslet offsets with real phase-induced
        centroid shifts.
    """

    geometry: ShwfsGeometryConfig
    detector: DetectorConfig
    x_m: np.ndarray
    y_m: np.ndarray
    pupil_mask: np.ndarray
    centers_m: np.ndarray
    subaperture_masks: tuple[np.ndarray, ...]
    reference_centroids_px: np.ndarray
    valid_subaperture_fraction: float

    @property
    def n_valid_subapertures(self) -> int:
        return int(len(self.subaperture_masks))


@dataclass(frozen=True)
class DetectorMeasurement:
    """Detector-level centroid measurement result.

    Args:
        shifts_px: Reference-subtracted centroid shifts with shape
            ``(n_valid_subapertures, 2)`` in detector pixels.
        centroids_px: Raw measured centroids in detector pixels.
        fluxes_e: Total detector signal per lenslet in electrons.
        valid: Boolean centroid-validity flag per lenslet.
        valid_centroid_frac: Fraction of valid centroids.
        spots: Optional detector images for selected diagnostics.

    Returns:
        Immutable measurement record.

    Raises:
        SyntheticInstrumentError: Built after shape and finite checks pass.

    Physics note:
        Invalid/zero-flux centroids are kept as NaN in ``shifts_px`` and
        explicitly counted through ``valid_centroid_frac``. Later response
        matrices must drop those rows rather than replacing them with zero.
    """

    shifts_px: np.ndarray
    centroids_px: np.ndarray
    fluxes_e: np.ndarray
    valid: np.ndarray
    valid_centroid_frac: float
    total_flux_e: np.ndarray | None = None
    background_e: np.ndarray | None = None
    peak_snr: np.ndarray | None = None
    total_snr: np.ndarray | None = None
    centroid_sigma_px: np.ndarray | None = None
    window_clipping_fraction: np.ndarray | None = None
    valid_by_flux: np.ndarray | None = None
    valid_by_snr: np.ndarray | None = None
    valid_by_uncertainty: np.ndarray | None = None
    valid_by_clipping: np.ndarray | None = None
    spots: tuple[np.ndarray, ...] | None = None


@dataclass(frozen=True)
class DetectorResponseMatrix:
    """Small detector-level response matrix for phase-tilt diagnostics.

    Args:
        matrix_px_per_unit: Response matrix with rows ordered as
            ``x0, y0, x1, y1, ...`` and columns listed in ``column_names``.
        column_names: Names of calibration columns.
        row_valid: Boolean finite-row mask.
        calibration_amplitude_rad_per_m: Central-difference phase tilt
            amplitude in radians per metre.

    Returns:
        Immutable response-matrix bundle.

    Raises:
        SyntheticInstrumentError: Built after finite-value and shape checks.

    Physics note:
        Each column maps a phase tilt coefficient in radians per metre to
        detector centroid shifts in pixels. This is a detector response matrix,
        not yet a DM interaction matrix.
    """

    matrix_px_per_unit: np.ndarray
    column_names: tuple[str, ...]
    row_valid: np.ndarray
    calibration_amplitude_rad_per_m: float


def make_pupil_grid_and_mask(config: ShwfsGeometryConfig) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """Create a pupil grid and synthetic telescope mask.

    Args:
        config: SH-WFS geometry configuration.

    Returns:
        ``(x_m, y_m, pupil_mask, dx_m)`` where coordinates are metres and
        ``pupil_mask`` is boolean.

    Raises:
        SyntheticInstrumentError: If the generated pupil has no illuminated
        pixels.

    Physics note:
        The default is a circular 2 m pupil. Optional central obstruction and
        orthogonal spider strips are synthetic geometry terms for later
        sensitivity studies.
    """

    x = np.linspace(
        -config.telescope_diameter_m / 2.0,
        config.telescope_diameter_m / 2.0,
        config.n_pupil_pixels,
    )
    x_m, y_m = np.meshgrid(x, x)
    radius_m = np.sqrt(x_m**2 + y_m**2)
    outer = radius_m <= config.telescope_diameter_m / 2.0
    if config.central_obstruction_ratio > 0:
        inner_radius_m = 0.5 * config.telescope_diameter_m * config.central_obstruction_ratio
        outer &= radius_m >= inner_radius_m
    if config.spider_width_m > 0:
        half_spider_m = 0.5 * config.spider_width_m
        spiders = (np.abs(x_m) <= half_spider_m) | (np.abs(y_m) <= half_spider_m)
        outer &= ~spiders
    if not np.any(outer):
        raise SyntheticInstrumentError("Generated pupil mask has no illuminated pixels.")
    dx_m = float(x[1] - x[0])
    return x_m, y_m, outer, dx_m


def build_detector_shwfs_calibration(
    geometry: ShwfsGeometryConfig | None = None,
    detector: DetectorConfig | None = None,
) -> DetectorShwfsCalibration:
    """Build zero-phase detector SH-WFS reference centroids.

    Args:
        geometry: Optional SH-WFS geometry configuration. Defaults to a small
            2 m fast-mode geometry.
        detector: Optional detector configuration stored with the calibration.

    Returns:
        :class:`DetectorShwfsCalibration` with valid subapertures and finite
        zero-phase reference centroids.

    Raises:
        SyntheticInstrumentError: If no subapertures are valid or if reference
            centroids contain NaN/Inf.

    Physics note:
        Reference centroids are computed from a zero-phase pupil, not from a
        noisy detector exposure. Later measurements subtract this deterministic
        reference to isolate wavefront-induced spot shifts.
    """

    geometry = geometry or ShwfsGeometryConfig()
    detector = detector or DetectorConfig()
    x_m, y_m, pupil_mask, _ = make_pupil_grid_and_mask(geometry)
    centers_m, masks_list = subaperture_masks(
        x_m,
        y_m,
        pupil_mask,
        n_lenslets=geometry.n_lenslets,
        min_fill=geometry.min_fill_fraction,
    )
    if len(masks_list) == 0:
        raise SyntheticInstrumentError("No valid SH-WFS subapertures were found.")

    zero_phase_rad = np.zeros_like(x_m, dtype=float)
    reference = []
    for mask in masks_list:
        spot = lenslet_spot_from_phase(
            zero_phase_rad,
            mask,
            pad_factor=geometry.pad_factor,
            remove_local_piston=True,
        )
        spot = crop_center(spot, geometry.detector_window_px)
        reference.append(
            centroid(
                spot,
                threshold_fraction=geometry.threshold_fraction,
                subtract_minimum=geometry.subtract_minimum,
            )
        )
    reference_px = np.asarray(reference, dtype=float)
    _assert_all_finite(reference_px, "zero-phase reference centroids")
    valid_fraction = float(len(masks_list) / max(geometry.n_lenslets**2, 1))
    return DetectorShwfsCalibration(
        geometry=geometry,
        detector=detector,
        x_m=x_m,
        y_m=y_m,
        pupil_mask=pupil_mask,
        centers_m=centers_m,
        subaperture_masks=tuple(masks_list),
        reference_centroids_px=reference_px,
        valid_subaperture_fraction=valid_fraction,
    )


def phase_tilt_map_rad(
    calibration: DetectorShwfsCalibration,
    tilt_x_rad_per_m: float = 0.0,
    tilt_y_rad_per_m: float = 0.0,
) -> np.ndarray:
    """Create a phase-tilt map in radians at the WFS wavelength.

    Args:
        calibration: Detector SH-WFS calibration bundle.
        tilt_x_rad_per_m: X phase gradient in radians per metre.
        tilt_y_rad_per_m: Y phase gradient in radians per metre.

    Returns:
        Phase map in radians at ``calibration.geometry.wfs_wavelength_m`` with
        NaN outside the pupil.

    Raises:
        SyntheticInstrumentError: If tilt values are non-finite.

    Physics note:
        This is a pure phase ramp. It is useful for checking detector centroid
        sign and linearity before constructing more complicated response
        matrices.
    """

    _require_finite("tilt_x_rad_per_m", tilt_x_rad_per_m)
    _require_finite("tilt_y_rad_per_m", tilt_y_rad_per_m)
    # Unit assertion: phase_rad is radians at geometry.wfs_wavelength_m.
    phase_rad = tilt_x_rad_per_m * calibration.x_m + tilt_y_rad_per_m * calibration.y_m
    return np.where(calibration.pupil_mask, phase_rad, np.nan)


def add_configured_detector_noise(
    normalized_spot: np.ndarray,
    detector: DetectorConfig,
    seed: int | None = None,
    clip_negative: bool = True,
) -> np.ndarray:
    """Apply the detector model to one normalized lenslet spot.

    Args:
        normalized_spot: Lenslet spot normalized to unit sum.
        detector: Detector configuration.
        seed: Optional random seed.
        clip_negative: Whether to clip negative post-read-noise electrons to
            zero.

    Returns:
        Detector image in electrons.

    Raises:
        SyntheticInstrumentError: If spot values are non-finite, if total spot
            flux is negative, or if a bad-pixel mask has the wrong shape.

    Physics note:
        The expected electron image is ``photons * qe * spot`` plus dark and
        background. PRNU is a multiplicative pixel response term; bad pixels
        are forced to zero; full-well clips saturated pixels.
    """

    spot = np.asarray(normalized_spot, dtype=float)
    _assert_all_finite(spot, "normalized lenslet spot")
    if np.any(spot < 0):
        raise SyntheticInstrumentError("normalized_spot must be non-negative.")
    rng = np.random.default_rng(seed)

    if detector.photons_per_subap_frame is None:
        image_e = spot.copy()
    else:
        expected_e = detector.photons_per_subap_frame * detector.qe * spot
        expected_e = expected_e + detector.dark_e_per_s * detector.exposure_s
        expected_e = expected_e + detector.background_e_per_pixel_frame
        if detector.prnu_rms > 0:
            flat = rng.normal(loc=1.0, scale=detector.prnu_rms, size=spot.shape)
            expected_e = expected_e * np.maximum(flat, 0.0)
        image_e = rng.poisson(expected_e).astype(float)

    if detector.read_noise_e > 0:
        image_e = image_e + rng.normal(scale=detector.read_noise_e, size=spot.shape)
    if detector.full_well_e is not None:
        image_e = np.minimum(image_e, detector.full_well_e)
    if detector.bad_pixel_mask is not None:
        bad_pixel_mask = np.asarray(detector.bad_pixel_mask, dtype=bool)
        if bad_pixel_mask.shape != image_e.shape:
            raise SyntheticInstrumentError(
                f"bad_pixel_mask shape {bad_pixel_mask.shape} does not match image shape {image_e.shape}."
            )
        image_e = image_e.copy()
        image_e[bad_pixel_mask] = 0.0
    if clip_negative:
        image_e = np.maximum(image_e, 0.0)
    _assert_all_finite(image_e, "detector image after noise model")
    return image_e


_UNDEFINED_CENTROID_SIGMA_PX = 1.0e6  # sentinel for an effectively immeasurable centroid


def _intensity_weighted_rms_px(image: np.ndarray) -> float:
    """Return the intensity-weighted RMS width (pixels) of a non-negative image."""

    a = np.asarray(image, dtype=float)
    a = np.where(np.isfinite(a), np.clip(a, 0.0, None), 0.0)
    total = float(np.sum(a))
    if total <= 0.0:
        return 0.0
    ny, nx = a.shape
    ys = np.arange(ny, dtype=float)[:, None]
    xs = np.arange(nx, dtype=float)[None, :]
    cx = float(np.sum(a * xs) / total)
    cy = float(np.sum(a * ys) / total)
    variance = float(np.sum(a * ((xs - cx) ** 2 + (ys - cy) ** 2)) / total) / 2.0
    return math.sqrt(max(variance, 0.0))


def centroid_quality(
    cropped_spot_norm: np.ndarray,
    full_spot_norm: np.ndarray,
    detector: DetectorConfig,
) -> dict[str, float]:
    """Expected-photon-budget centroid-quality diagnostics for one lenslet spot.

    Diagnostics are computed from the *expected* detector signal
    (``photons * qe * spot`` plus dark/background), not from a single noisy
    realization, so centroid-validity decisions are deterministic and
    reproducible under fixed seeds. When ``photons_per_subap_frame`` is ``None``
    (the deterministic calibration/reference path) the spot is treated as an
    ideal noise-free reference and flux/SNR are reported as ``nan`` (not
    applicable) with a zero uncertainty proxy.

    Args:
        cropped_spot_norm: Window-cropped lenslet spot (the full spot is
            unit-sum before cropping).
        full_spot_norm: Full lenslet spot before window cropping.
        detector: Detector configuration (photons, qe, read noise, dark,
            background, exposure).

    Returns:
        Dict with ``total_flux_e``, ``background_e``, ``peak_snr``,
        ``total_snr``, ``centroid_sigma_px``, and ``window_clipping_fraction``.

    Physics note:
        ``total_snr`` follows the CCD equation ``S / sqrt(S + npix*(B + RN^2))``;
        the centroid-uncertainty proxy is the intensity-weighted spot width
        divided by the total SNR, the standard photon-limited centroiding scale.
    """

    cropped = np.asarray(cropped_spot_norm, dtype=float)
    full = np.asarray(full_spot_norm, dtype=float)
    n_pixels = int(cropped.size)
    full_sum = float(np.nansum(full))
    crop_sum = float(np.nansum(cropped))
    clip_fraction = 0.0 if full_sum <= 0.0 else float(min(max(1.0 - crop_sum / full_sum, 0.0), 1.0))

    read_noise_e = float(detector.read_noise_e)
    background_per_px_e = float(detector.background_e_per_pixel_frame + detector.dark_e_per_s * detector.exposure_s)
    background_e = background_per_px_e * n_pixels

    photons = detector.photons_per_subap_frame
    if photons is None:
        # Deterministic noise-free reference: ideal high-quality spot.
        return {
            "total_flux_e": math.nan,
            "background_e": background_e,
            "peak_snr": math.nan,
            "total_snr": math.nan,
            "centroid_sigma_px": 0.0,
            "window_clipping_fraction": clip_fraction,
        }

    qe = float(detector.qe)
    signal_per_px_e = float(photons) * qe * np.clip(cropped, 0.0, None)
    total_flux_e = float(np.nansum(signal_per_px_e))
    peak_signal_e = float(np.nanmax(signal_per_px_e)) if signal_per_px_e.size else 0.0
    peak_noise_e = math.sqrt(max(peak_signal_e + background_per_px_e + read_noise_e**2, 0.0))
    peak_snr = peak_signal_e / peak_noise_e if peak_noise_e > 0.0 else 0.0
    total_noise_e = math.sqrt(max(total_flux_e + n_pixels * (background_per_px_e + read_noise_e**2), 0.0))
    total_snr = total_flux_e / total_noise_e if total_noise_e > 0.0 else 0.0
    sigma_spot_px = _intensity_weighted_rms_px(signal_per_px_e)
    centroid_sigma_px = sigma_spot_px / total_snr if total_snr > 1.0e-9 else _UNDEFINED_CENTROID_SIGMA_PX
    centroid_sigma_px = float(min(centroid_sigma_px, _UNDEFINED_CENTROID_SIGMA_PX))
    return {
        "total_flux_e": total_flux_e,
        "background_e": background_e,
        "peak_snr": peak_snr,
        "total_snr": total_snr,
        "centroid_sigma_px": centroid_sigma_px,
        "window_clipping_fraction": clip_fraction,
    }


def measure_detector_shwfs(
    phase_rad: np.ndarray,
    calibration: DetectorShwfsCalibration,
    include_noise: bool = True,
    seed: int | None = 1,
    return_spots: bool = False,
    validity: CentroidValidityConfig | None = None,
) -> DetectorMeasurement:
    """Measure detector-level centroid shifts for one phase map.

    Args:
        phase_rad: Phase map in radians at the WFS wavelength.
        calibration: Reference-centroid calibration bundle.
        include_noise: Whether to apply the configured detector noise model.
        seed: Optional random seed for detector effects.
        return_spots: Whether to keep detector images in the returned record.

    Returns:
        :class:`DetectorMeasurement` with centroid shifts, raw centroids,
        fluxes, validity mask, and valid-centroid fraction.

    Raises:
        SyntheticInstrumentError: If phase shape is incompatible with the
        calibration or if output shapes are inconsistent.

    Physics note:
        Invalid centroids are explicitly represented by NaN shifts and counted
        in ``valid_centroid_frac``. They are not replaced by zero.
    """

    phase = np.asarray(phase_rad, dtype=float)
    if phase.shape != calibration.x_m.shape:
        raise SyntheticInstrumentError(
            f"phase shape {phase.shape} does not match calibration grid {calibration.x_m.shape}."
        )
    validity_cfg = DEFAULT_CENTROID_VALIDITY if validity is None else validity
    detector = calibration.detector
    # Flux/SNR/uncertainty criteria apply only when a noisy, finite photon budget is
    # actually modelled. A deterministic noise-free measurement (no noise, or no
    # photon budget) is a calibration/reference measurement and is treated as
    # ideal; only geometric window clipping still applies to it. This keeps the
    # detector-level interaction-matrix calibration from collapsing under a faint
    # science photon budget while still rejecting faint *noisy* loop frames.
    apply_quality_criteria = bool(include_noise) and (detector.photons_per_subap_frame is not None)

    rng = np.random.default_rng(seed)
    shifts = []
    centroids = []
    fluxes = []
    valid = []
    total_flux = []
    background = []
    peak_snr_list = []
    total_snr_list = []
    centroid_sigma = []
    clipping = []
    valid_flux = []
    valid_snr = []
    valid_uncertainty = []
    valid_clipping = []
    spots = []

    for index, mask in enumerate(calibration.subaperture_masks):
        full_spot = lenslet_spot_from_phase(
            phase,
            mask,
            pad_factor=calibration.geometry.pad_factor,
            remove_local_piston=True,
        )
        cropped_spot = crop_center(full_spot, calibration.geometry.detector_window_px)
        if include_noise:
            image_e = add_configured_detector_noise(
                cropped_spot,
                detector,
                seed=int(rng.integers(0, 2**31 - 1)),
            )
        else:
            image_e = np.asarray(cropped_spot, dtype=float)
        c_px = np.asarray(
            centroid(
                image_e,
                threshold_fraction=calibration.geometry.threshold_fraction,
                subtract_minimum=calibration.geometry.subtract_minimum,
            ),
            dtype=float,
        )
        ref_px = calibration.reference_centroids_px[index]
        finite = bool(np.all(np.isfinite(c_px)) and np.all(np.isfinite(ref_px)))

        quality = centroid_quality(cropped_spot, full_spot, detector)
        if apply_quality_criteria:
            by_flux = bool(quality["total_flux_e"] >= validity_cfg.min_flux_e)
            by_snr = bool(quality["peak_snr"] >= validity_cfg.min_peak_snr)
            by_uncertainty = bool(quality["centroid_sigma_px"] <= validity_cfg.max_centroid_sigma_px)
        else:
            by_flux = by_snr = by_uncertainty = True
        by_clipping = bool(quality["window_clipping_fraction"] <= validity_cfg.max_window_clipping_fraction)
        # A finite centroid is necessary but not sufficient: faint, low-SNR, or
        # heavily clipped spots are rejected even when a finite value is returned.
        is_valid = bool(finite and by_flux and by_snr and by_uncertainty and by_clipping)

        shift_px = c_px - ref_px if is_valid else np.array([np.nan, np.nan], dtype=float)
        centroids.append(c_px)
        shifts.append(shift_px)
        fluxes.append(float(np.nansum(image_e)))
        valid.append(is_valid)
        total_flux.append(quality["total_flux_e"])
        background.append(quality["background_e"])
        peak_snr_list.append(quality["peak_snr"])
        total_snr_list.append(quality["total_snr"])
        centroid_sigma.append(quality["centroid_sigma_px"])
        clipping.append(quality["window_clipping_fraction"])
        valid_flux.append(by_flux)
        valid_snr.append(by_snr)
        valid_uncertainty.append(by_uncertainty)
        valid_clipping.append(by_clipping)
        if return_spots:
            spots.append(np.asarray(image_e, dtype=float))

    shifts_px = np.asarray(shifts, dtype=float)
    centroids_px = np.asarray(centroids, dtype=float)
    fluxes_e = np.asarray(fluxes, dtype=float)
    valid_arr = np.asarray(valid, dtype=bool)
    _validate_measurement_shapes(calibration, shifts_px, centroids_px, fluxes_e, valid_arr)
    valid_centroid_frac = float(np.mean(valid_arr)) if valid_arr.size else MIN_VALID_CENTROID_FRACTION
    return DetectorMeasurement(
        shifts_px=shifts_px,
        centroids_px=centroids_px,
        fluxes_e=fluxes_e,
        valid=valid_arr,
        valid_centroid_frac=valid_centroid_frac,
        total_flux_e=np.asarray(total_flux, dtype=float),
        background_e=np.asarray(background, dtype=float),
        peak_snr=np.asarray(peak_snr_list, dtype=float),
        total_snr=np.asarray(total_snr_list, dtype=float),
        centroid_sigma_px=np.asarray(centroid_sigma, dtype=float),
        window_clipping_fraction=np.asarray(clipping, dtype=float),
        valid_by_flux=np.asarray(valid_flux, dtype=bool),
        valid_by_snr=np.asarray(valid_snr, dtype=bool),
        valid_by_uncertainty=np.asarray(valid_uncertainty, dtype=bool),
        valid_by_clipping=np.asarray(valid_clipping, dtype=bool),
        spots=tuple(spots) if return_spots else None,
    )


def zero_phase_centroid_rms_px(calibration: DetectorShwfsCalibration) -> float:
    """Compute zero-phase reference-subtracted centroid RMS.

    Args:
        calibration: Detector SH-WFS calibration bundle.

    Returns:
        RMS centroid shift in detector pixels for a zero phase map.

    Raises:
        SyntheticInstrumentError: If no finite zero-phase centroid shifts are
            available.

    Physics note:
        This is the zero-point sanity check. It should be close to zero
        because the same zero-phase model defines the deterministic reference.
    """

    phase = np.zeros_like(calibration.x_m, dtype=float)
    measurement = measure_detector_shwfs(phase, calibration, include_noise=False)
    finite = np.isfinite(measurement.shifts_px)
    if not np.any(finite):
        raise SyntheticInstrumentError("No finite zero-phase centroid shifts are available.")
    return float(np.sqrt(np.mean(measurement.shifts_px[finite] ** 2)))


def build_tilt_response_matrix(
    calibration: DetectorShwfsCalibration,
    calibration_amplitude_rad_per_m: float = 0.05,
) -> DetectorResponseMatrix:
    """Build a detector response matrix for x/y phase tilts.

    Args:
        calibration: Detector SH-WFS calibration bundle.
        calibration_amplitude_rad_per_m: Central-difference phase ramp
            amplitude in radians per metre.

    Returns:
        :class:`DetectorResponseMatrix` with two columns:
        ``tilt_x_rad_per_m`` and ``tilt_y_rad_per_m``.

    Raises:
        SyntheticInstrumentError: If calibration amplitude is non-positive or
            if response-matrix rows have unexpected shape.

    Physics note:
        Rows are ordered as interleaved detector centroid shifts
        ``x0, y0, x1, y1, ...``. The matrix is a detector-level slope proxy;
        a DM interaction matrix is introduced later.
    """

    _require_positive("calibration_amplitude_rad_per_m", calibration_amplitude_rad_per_m)
    columns = []
    for tilt_x, tilt_y in ((calibration_amplitude_rad_per_m, 0.0), (0.0, calibration_amplitude_rad_per_m)):
        phase_p = phase_tilt_map_rad(calibration, tilt_x_rad_per_m=tilt_x, tilt_y_rad_per_m=tilt_y)
        phase_m = phase_tilt_map_rad(calibration, tilt_x_rad_per_m=-tilt_x, tilt_y_rad_per_m=-tilt_y)
        meas_p = measure_detector_shwfs(phase_p, calibration, include_noise=False)
        meas_m = measure_detector_shwfs(phase_m, calibration, include_noise=False)
        column = (meas_p.shifts_px - meas_m.shifts_px).reshape(-1) / (2.0 * calibration_amplitude_rad_per_m)
        columns.append(column)
    matrix = np.column_stack(columns)
    expected_rows = 2 * calibration.n_valid_subapertures
    if matrix.shape != (expected_rows, 2):
        raise SyntheticInstrumentError(
            f"Tilt response matrix shape {matrix.shape} != expected {(expected_rows, 2)}."
        )
    row_valid = np.all(np.isfinite(matrix), axis=1)
    return DetectorResponseMatrix(
        matrix_px_per_unit=matrix,
        column_names=("tilt_x_rad_per_m", "tilt_y_rad_per_m"),
        row_valid=row_valid,
        calibration_amplitude_rad_per_m=calibration_amplitude_rad_per_m,
    )


def sample_centroid_noise(
    normalized_spot: np.ndarray,
    detector: DetectorConfig,
    n_trials: int = 64,
    seed: int = 1,
    threshold_fraction: float = 0.0,
) -> dict[str, float]:
    """Estimate centroid scatter for repeated detector-noise realizations.

    Args:
        normalized_spot: Lenslet spot normalized to unit sum.
        detector: Detector configuration.
        n_trials: Number of independent noise realizations.
        seed: Random seed.
        threshold_fraction: Fraction of peak below which centroid pixels are
            discarded.

    Returns:
        Dictionary with ``centroid_rms_px``, ``valid_fraction``,
        ``std_x_px``, and ``std_y_px``.

    Raises:
        SyntheticInstrumentError: If ``n_trials`` is not positive.

    Physics note:
        This diagnostic isolates detector noise from wavefront reconstruction.
        Photon-limited centroid scatter should decrease as photon count rises;
        read-noise-dominated cases should increase scatter.
    """

    if n_trials <= 0:
        raise SyntheticInstrumentError("n_trials must be positive.")
    rng = np.random.default_rng(seed)
    samples = []
    for _ in range(n_trials):
        image_e = add_configured_detector_noise(
            normalized_spot,
            detector,
            seed=int(rng.integers(0, 2**31 - 1)),
        )
        samples.append(centroid(image_e, threshold_fraction=threshold_fraction))
    arr = np.asarray(samples, dtype=float)
    valid = np.all(np.isfinite(arr), axis=1)
    valid_fraction = float(np.mean(valid)) if valid.size else MIN_VALID_CENTROID_FRACTION
    if not np.any(valid):
        return {
            "centroid_rms_px": float("nan"),
            "valid_fraction": valid_fraction,
            "std_x_px": float("nan"),
            "std_y_px": float("nan"),
        }
    centered = arr[valid] - np.mean(arr[valid], axis=0)
    std_x = float(np.std(arr[valid, 0]))
    std_y = float(np.std(arr[valid, 1]))
    return {
        "centroid_rms_px": float(np.sqrt(np.mean(centered**2))),
        "valid_fraction": valid_fraction,
        "std_x_px": std_x,
        "std_y_px": std_y,
    }


def _validate_measurement_shapes(
    calibration: DetectorShwfsCalibration,
    shifts_px: np.ndarray,
    centroids_px: np.ndarray,
    fluxes_e: np.ndarray,
    valid: np.ndarray,
) -> None:
    n_valid = calibration.n_valid_subapertures
    if shifts_px.shape != (n_valid, 2):
        raise SyntheticInstrumentError(f"shifts shape {shifts_px.shape} != {(n_valid, 2)}.")
    if centroids_px.shape != (n_valid, 2):
        raise SyntheticInstrumentError(f"centroids shape {centroids_px.shape} != {(n_valid, 2)}.")
    if fluxes_e.shape != (n_valid,):
        raise SyntheticInstrumentError(f"fluxes shape {fluxes_e.shape} != {(n_valid,)}.")
    if valid.shape != (n_valid,):
        raise SyntheticInstrumentError(f"valid mask shape {valid.shape} != {(n_valid,)}.")


def _assert_all_finite(values: np.ndarray, label: str) -> None:
    array = np.asarray(values, dtype=float)
    if not np.all(np.isfinite(array)):
        finite_frac = float(np.mean(np.isfinite(array))) if array.size else 0.0
        raise SyntheticInstrumentError(f"Non-finite values in {label}; finite_frac={finite_frac:.3f}.")


def _require_positive(field_name: str, value: float) -> None:
    _require_finite(field_name, value)
    if value <= 0:
        raise SyntheticInstrumentError(f"{field_name} must be positive; got {value!r}.")


def _require_nonnegative(field_name: str, value: float) -> None:
    _require_finite(field_name, value)
    if value < 0:
        raise SyntheticInstrumentError(f"{field_name} must be non-negative; got {value!r}.")


def _require_finite(field_name: str, value: float) -> None:
    if not math.isfinite(float(value)):
        raise SyntheticInstrumentError(f"{field_name} must be finite; got {value!r}.")


# Named visible SH-WFS detector-quality presets. Defined at module end so
# the `_require_*` validators above already exist when the presets are
# instantiated at import. Defaults stay explicit (ideal is fully noise-free) and
# every preset is synthetic -- not a NIR science camera, not a measured
# detector calibration.
DETECTOR_PRESETS: dict[str, DetectorPreset] = {
    "ideal": DetectorPreset(
        preset_name="ideal",
        read_noise_e=0.0,
        dark_e_per_s=0.0,
        background_e_per_pixel_frame=0.0,
        full_well_e=None,
        prnu_rms=0.0,
        bad_pixel_fraction=0.0,
        source_note="Ideal noise-free visible SH-WFS detector reference; no read/dark/background/PRNU/saturation.",
    ),
    "low_noise_sCMOS_like": DetectorPreset(
        preset_name="low_noise_sCMOS_like",
        read_noise_e=1.0,  # ~1 e RMS, typical of scientific CMOS sensors
        dark_e_per_s=5.0,
        background_e_per_pixel_frame=0.5,
        full_well_e=50000.0,
        prnu_rms=0.01,
        bad_pixel_fraction=0.001,
        source_note="Low-noise scientific-CMOS-like visible WFS detector engineering preset; synthetic, no datasheet cited.",
    ),
    "noisy_visible_wfs": DetectorPreset(
        preset_name="noisy_visible_wfs",
        read_noise_e=10.0,
        dark_e_per_s=50.0,
        background_e_per_pixel_frame=3.0,
        full_well_e=30000.0,
        prnu_rms=0.02,
        bad_pixel_fraction=0.005,
        source_note="Noisy visible SH-WFS detector engineering preset; elevated read noise/dark/background.",
    ),
    "stress_saturated_window": DetectorPreset(
        preset_name="stress_saturated_window",
        read_noise_e=12.0,
        dark_e_per_s=80.0,
        background_e_per_pixel_frame=5.0,
        full_well_e=2000.0,  # low full well forces spot saturation/clipping
        prnu_rms=0.03,
        bad_pixel_fraction=0.01,
        source_note="Stress preset: low full well saturates/clips the spot, plus elevated noise and dead pixels.",
    ),
}


def detector_preset(name: str) -> DetectorPreset:
    """Return a named visible SH-WFS detector-quality preset.

    Args:
        name: One of the :data:`DETECTOR_PRESETS` keys.

    Returns:
        The matching :class:`DetectorPreset`.

    Raises:
        SyntheticInstrumentError: If ``name`` is not a known preset.
    """

    try:
        return DETECTOR_PRESETS[name]
    except KeyError as exc:
        raise SyntheticInstrumentError(
            f"Unknown detector preset {name!r}; choose from {sorted(DETECTOR_PRESETS)}."
        ) from exc
