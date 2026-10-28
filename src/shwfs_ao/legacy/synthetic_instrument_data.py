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

from ..backends.native.shwfs import (
    NativeShackHartmannOptics as _NativeShackHartmannOptics,
)
from ..core.provenance import ALLOWED_SOURCE_CLASSES, Provenance as _Provenance
from ..core.random import (
    NamedRandomStreams as _NamedRandomStreams,
    _legacy_sequential_child_seeds,
)
from ..detector.centroid import (
    CentroidConfig as _CentroidConfig,
    estimate_centroid as _estimate_centroid,
)
from ..detector.config import (
    DEFAULT_SOURCE_CLASS,
    DETECTOR_PRESETS,
    DetectorConfig,
    DetectorPreset,
    SyntheticInstrumentError,
    detector_preset,
    make_bad_pixel_mask,
)
from ..detector.effects import (
    DetectorEffectsError as _DetectorEffectsError,
    apply_detector_effects as _apply_detector_effects,
)
from ..detector.random import (
    DetectorRealization as _DetectorRealization,
    DetectorRealizationError as _DetectorRealizationError,
)
from ..detector.validity import (
    DEFAULT_CENTROID_VALIDITY,
    CentroidValidityConfig,
    centroid_quality as _canonical_centroid_quality,
    evaluate_centroid_validity as _evaluate_centroid_validity,
)
from ..wfs.shack_hartmann.geometry import (
    DEFAULT_WFS_WAVELENGTH_M,
    ShackHartmannGeometry as _ShackHartmannGeometry,
    ShwfsGeometryConfig,
    build_shack_hartmann_geometry as _build_shack_hartmann_geometry,
)
from ..wfs.shack_hartmann.measurement import (
    DetectorShackHartmannSensor as _DetectorShackHartmannSensor,
)
from ._interaction_adapters import (
    calibrate_legacy_modal_columns as _calibrate_legacy_modal_columns,
    legacy_streams as _legacy_calibration_streams,
    legacy_y_up_matrix as _legacy_y_up_matrix,
)
from .reconstruction import subaperture_masks
from .shwfs_detector import (
    centroid,
    crop_center,
    lenslet_spot_from_phase,
    nominal_lenslet_sampling_shape,
)

MIN_VALID_CENTROID_FRACTION = 0.0
_LEGACY_CANONICAL_ROOT_SEED = 1


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

    try:
        canonical = _build_shack_hartmann_geometry(config)
    except ValueError as exc:
        raise SyntheticInstrumentError(str(exc)) from exc
    dx_m = float(canonical.x_m[0, 1] - canonical.x_m[0, 0])
    return (
        np.array(canonical.x_m, dtype=float, copy=True),
        np.array(canonical.y_m, dtype=float, copy=True),
        np.array(canonical.pupil_mask, dtype=bool, copy=True),
        dx_m,
    )


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
    streams = _NamedRandomStreams(_LEGACY_CANONICAL_ROOT_SEED)
    try:
        canonical_geometry = _build_shack_hartmann_geometry(geometry)
        optics = _NativeShackHartmannOptics(
            canonical_geometry,
            geometry.wfs_wavelength_m,
            pad_factor=geometry.pad_factor,
            detector_window_px=geometry.detector_window_px,
        )
        centroid_config = _CentroidConfig(
            estimator=(
                "thresholded_center_of_gravity"
                if geometry.threshold_fraction > 0.0
                else "center_of_gravity"
            ),
            threshold_fraction=geometry.threshold_fraction,
            subtract_minimum=geometry.subtract_minimum,
        )
        sensor = _DetectorShackHartmannSensor.calibrate(
            canonical_geometry,
            optics,
            detector,
            wfs_wavelength_m=geometry.wfs_wavelength_m,
            random_streams=streams,
            centroid_config=centroid_config,
            provenance=geometry.provenance,
        )
    except ValueError as exc:
        raise SyntheticInstrumentError(str(exc)) from exc

    # The canonical sensor privately retains its detector-response reference.
    # The frozen legacy record, however, exposed ideal zero-phase optical
    # centroids even when the later noisy detector used PRNU or bad pixels.
    zero_spots = optics.spot_intensities(
        np.zeros(canonical_geometry.pupil_shape, dtype=float)
    )
    reference_px = np.asarray(
        [
            centroid(
                np.asarray(spot, dtype=float) * float(capture),
                threshold_fraction=geometry.threshold_fraction,
                subtract_minimum=geometry.subtract_minimum,
            )
            for spot, capture in zip(
                zero_spots.unit_sum_spots,
                zero_spots.relative_throughput,
            )
        ],
        dtype=float,
    )
    _assert_all_finite(reference_px, "zero-phase reference centroids")
    valid_fraction = float(
        canonical_geometry.n_subapertures / max(geometry.n_lenslets**2, 1)
    )
    legacy = DetectorShwfsCalibration(
        geometry=geometry,
        detector=detector,
        x_m=np.array(canonical_geometry.x_m, dtype=float, copy=True),
        y_m=np.array(canonical_geometry.y_m, dtype=float, copy=True),
        pupil_mask=np.array(canonical_geometry.pupil_mask, dtype=bool, copy=True),
        centers_m=np.array(
            canonical_geometry.subaperture_centers_m,
            dtype=float,
            copy=True,
        ),
        subaperture_masks=tuple(
            np.array(mask, dtype=bool, copy=True)
            for mask in canonical_geometry.subaperture_masks
        ),
        reference_centroids_px=reference_px,
        valid_subaperture_fraction=valid_fraction,
    )
    # Private attributes are deliberately not dataclass fields: the frozen
    # public calibration record remains byte-for-byte compatible while owning
    # one canonical detector realization for calibration and runtime use.
    object.__setattr__(legacy, "_canonical_geometry", canonical_geometry)
    object.__setattr__(legacy, "_canonical_optics", optics)
    object.__setattr__(legacy, "_canonical_sensor", sensor)
    object.__setattr__(
        legacy,
        "_canonical_random_root_seed",
        _LEGACY_CANONICAL_ROOT_SEED,
    )
    return legacy


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

    frame = _canonical_detector_frame(
        normalized_spot,
        detector,
        seed=seed,
        clip_negative=clip_negative,
    )
    # The canonical record is immutable; the historical array-only API remains
    # a writable defensive copy for compatibility.
    return np.array(frame.image_e, dtype=float, copy=True)


def _canonical_detector_frame(
    normalized_spot: np.ndarray,
    detector: DetectorConfig,
    *,
    seed: int | None,
    clip_negative: bool,
    random_streams: _NamedRandomStreams | None = None,
    realization: _DetectorRealization | None = None,
):
    """Adapt a legacy seed call to the canonical typed detector pipeline."""

    spot = np.asarray(normalized_spot, dtype=float)
    normalized_seed = _normalized_detector_seed(seed)
    streams = random_streams or _named_random_streams(normalized_seed)
    try:
        resolved_realization = realization
        if resolved_realization is None:
            resolved_realization = _DetectorRealization.create(
                detector,
                tuple(int(value) for value in spot.shape),
                random_streams=streams,
            )
        return _apply_detector_effects(
            spot,
            detector,
            resolved_realization,
            random_streams=streams,
            clip_negative=clip_negative,
            legacy_seed=(
                normalized_seed
                if detector.prnu_mode == "per_frame_legacy"
                else None
            ),
        )
    except (_DetectorEffectsError, _DetectorRealizationError) as exc:
        raise SyntheticInstrumentError(str(exc)) from exc


def _normalized_detector_seed(seed: int | None) -> int | None:
    if seed is None:
        return None
    if isinstance(seed, (int, np.integer)) and not isinstance(seed, (bool, np.bool_)):
        normalized = int(seed)
        if normalized >= 0:
            return normalized
    raise SyntheticInstrumentError(
        f"seed must be a non-negative integer or None; got {seed!r}."
    )


def _named_random_streams(seed: int | None) -> _NamedRandomStreams:
    root_seed = (
        int(np.random.SeedSequence().entropy)
        if seed is None
        else _normalized_detector_seed(seed)
    )
    assert root_seed is not None
    try:
        return _NamedRandomStreams(root_seed)
    except ValueError as exc:
        raise SyntheticInstrumentError(str(exc)) from exc


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

    quality = _canonical_centroid_quality(
        cropped_spot_norm,
        full_spot_norm,
        detector,
    )
    return {
        "total_flux_e": quality.total_flux_e,
        "background_e": quality.background_e,
        "peak_snr": quality.peak_snr,
        "total_snr": quality.total_snr,
        "centroid_sigma_px": quality.centroid_sigma_px,
        "window_clipping_fraction": quality.clipping_fraction,
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
    if not isinstance(include_noise, (bool, np.bool_)):
        raise SyntheticInstrumentError("include_noise must be a boolean.")
    validity_cfg = DEFAULT_CENTROID_VALIDITY if validity is None else validity
    if not isinstance(validity_cfg, CentroidValidityConfig):
        raise SyntheticInstrumentError(
            "validity must be a CentroidValidityConfig or None."
        )

    sensor = _canonical_sensor_for_legacy_calibration(
        calibration,
        validity_cfg,
    )
    root_seed = int(getattr(
        calibration,
        "_canonical_random_root_seed",
        _LEGACY_CANONICAL_ROOT_SEED,
    ))
    normalized_seed = _normalized_detector_seed(seed)
    runtime_key = (
        int(np.random.SeedSequence().entropy)
        if normalized_seed is None
        else normalized_seed
    )
    runtime_streams = _NamedRandomStreams(root_seed).scoped(
        "legacy.measure_detector_shwfs",
        key=(runtime_key,),
    )
    residual_opd_m = np.zeros_like(phase, dtype=float)
    inside = np.asarray(calibration.pupil_mask, dtype=bool)
    residual_opd_m[inside] = (
        phase[inside] * calibration.geometry.wfs_wavelength_m / (2.0 * np.pi)
    )
    ordered_seeds = (
        _legacy_sequential_child_seeds(
            normalized_seed,
            len(sensor.subaperture_ids),
        )
        if bool(include_noise)
        and calibration.detector.prnu_mode == "per_frame_legacy"
        else None
    )
    try:
        canonical = sensor._measure_legacy(
            residual_opd_m,
            random_streams=runtime_streams,
            include_noise=bool(include_noise),
            compatibility_mode="configured",
            ordered_legacy_seeds=ordered_seeds,
        )
    except (TypeError, ValueError) as exc:
        raise SyntheticInstrumentError(str(exc)) from exc
    telemetry = canonical.detector_telemetry
    if telemetry is None:  # pragma: no cover - enforced by the detector sensor
        raise SyntheticInstrumentError(
            "Canonical detector measurement did not provide telemetry."
        )

    centroids_px = _legacy_centered_centroids(
        telemetry.centroids_xy_px,
        sensor.calibration.detector_sampling.window_shape_px,
    )
    shifts_px = np.array(
        canonical.vector.values.reshape(-1, 2),
        dtype=float,
        copy=True,
    )
    shifts_px[:, 1] *= -1.0
    canonical_reference = _legacy_centered_centroids(
        sensor.calibration.reference_centroids_px,
        sensor.calibration.detector_sampling.window_shape_px,
    )
    supplied_reference = np.asarray(calibration.reference_centroids_px, dtype=float)
    if supplied_reference.shape != canonical_reference.shape:
        raise SyntheticInstrumentError(
            "calibration reference-centroid shape does not match canonical geometry."
        )
    valid_arr = np.array(telemetry.valid_subapertures, dtype=bool, copy=True)
    finite_reference = np.all(np.isfinite(supplied_reference), axis=1)
    valid_arr &= finite_reference
    shifts_px += canonical_reference - supplied_reference
    shifts_px[~valid_arr] = np.nan

    fluxes_e = np.array(telemetry.fluxes_e, dtype=float, copy=True)
    _validate_measurement_shapes(calibration, shifts_px, centroids_px, fluxes_e, valid_arr)
    valid_centroid_frac = float(np.mean(valid_arr)) if valid_arr.size else MIN_VALID_CENTROID_FRACTION
    total_flux, background = _legacy_expected_quality(telemetry, calibration.detector)
    detector_frames = telemetry.detector_frames
    if detector_frames is None:  # pragma: no cover - enforced by the detector sensor
        raise SyntheticInstrumentError(
            "Canonical detector measurement did not provide detector frames."
        )
    return DetectorMeasurement(
        shifts_px=shifts_px,
        centroids_px=centroids_px,
        fluxes_e=fluxes_e,
        valid=valid_arr,
        valid_centroid_frac=valid_centroid_frac,
        total_flux_e=total_flux,
        background_e=background,
        peak_snr=np.array(telemetry.peak_snr, dtype=float, copy=True),
        total_snr=np.array(telemetry.total_snr, dtype=float, copy=True),
        centroid_sigma_px=np.array(
            telemetry.centroid_sigma_px,
            dtype=float,
            copy=True,
        ),
        window_clipping_fraction=np.array(
            telemetry.clipping_fraction,
            dtype=float,
            copy=True,
        ),
        valid_by_flux=np.array(telemetry.valid_by_flux, dtype=bool, copy=True),
        valid_by_snr=np.array(telemetry.valid_by_snr, dtype=bool, copy=True),
        valid_by_uncertainty=np.array(
            telemetry.valid_by_uncertainty,
            dtype=bool,
            copy=True,
        ),
        valid_by_clipping=np.array(
            telemetry.valid_by_clipping,
            dtype=bool,
            copy=True,
        ),
        spots=(
            tuple(np.array(frame.image_e, dtype=float, copy=True) for frame in detector_frames)
            if return_spots
            else None
        ),
    )


def _canonical_sensor_for_legacy_calibration(
    calibration: DetectorShwfsCalibration,
    validity: CentroidValidityConfig,
) -> _DetectorShackHartmannSensor:
    sensor = getattr(calibration, "_canonical_sensor", None)
    if not isinstance(sensor, _DetectorShackHartmannSensor):
        rebuilt = build_detector_shwfs_calibration(
            geometry=calibration.geometry,
            detector=calibration.detector,
        )
        sensor = getattr(rebuilt, "_canonical_sensor")
        for attribute in (
            "_canonical_geometry",
            "_canonical_optics",
            "_canonical_sensor",
            "_canonical_random_root_seed",
        ):
            object.__setattr__(calibration, attribute, getattr(rebuilt, attribute))
    if sensor.validity_config == validity:
        return sensor
    try:
        return _DetectorShackHartmannSensor(
            sensor.optics_backend,
            sensor.calibration,
            sensor.detector_realization,
            validity_config=validity,
        )
    except ValueError as exc:
        raise SyntheticInstrumentError(str(exc)) from exc


def _legacy_centered_centroids(
    centroids_xy_px: np.ndarray,
    window_shape_px: tuple[int, int],
) -> np.ndarray:
    """Convert canonical absolute row-positive pixels to centered y-up pixels."""

    values = np.asarray(centroids_xy_px, dtype=float)
    rows, columns = window_shape_px
    result = np.array(values, dtype=float, copy=True)
    result[:, 0] -= (columns - 1) / 2.0
    result[:, 1] = (rows - 1) / 2.0 - result[:, 1]
    return result


def _legacy_expected_quality(telemetry, detector: DetectorConfig) -> tuple[np.ndarray, np.ndarray]:
    """Recover the historical expected-flux/background diagnostic arrays."""

    optical_spots = telemetry.optical_spots
    if optical_spots is None:  # pragma: no cover - detector sensor always supplies it
        raise SyntheticInstrumentError("Canonical telemetry is missing optical spots.")
    total_flux: list[float] = []
    background: list[float] = []
    for spot, throughput in zip(
        optical_spots.unit_sum_spots,
        optical_spots.relative_throughput,
    ):
        quality = _canonical_centroid_quality(
            np.asarray(spot, dtype=float) * float(throughput),
            np.asarray(spot, dtype=float),
            detector,
        )
        total_flux.append(quality.total_flux_e)
        background.append(quality.background_e)
    return np.asarray(total_flux, dtype=float), np.asarray(background, dtype=float)


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
    sensor = _canonical_sensor_for_legacy_calibration(
        calibration,
        DEFAULT_CENTROID_VALIDITY,
    )
    root_seed = int(
        getattr(calibration, "_canonical_random_root_seed", 1)
    )
    matrix, _ = _calibrate_legacy_modal_columns(
        {
            "tilt_x_rad_per_m": calibration.x_m,
            "tilt_y_rad_per_m": calibration.y_m,
        },
        calibration.pupil_mask,
        sensor,
        coefficient_amplitude=calibration_amplitude_rad_per_m,
        opd_m_per_raw_unit=(
            calibration.geometry.wfs_wavelength_m / (2.0 * np.pi)
        ),
        method="central",
        random_streams=_legacy_calibration_streams(root_seed),
    )
    matrix = _legacy_y_up_matrix(matrix)
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
    persistent_streams = (
        _named_random_streams(seed)
        if detector.prnu_mode == "persistent"
        else None
    )
    persistent_realization = None
    if persistent_streams is not None:
        try:
            persistent_realization = _DetectorRealization.create(
                detector,
                tuple(int(value) for value in np.shape(normalized_spot)),
                random_streams=persistent_streams,
            )
        except _DetectorRealizationError as exc:
            raise SyntheticInstrumentError(str(exc)) from exc
    samples = []
    for trial_index in range(n_trials):
        if persistent_streams is None:
            image_e = add_configured_detector_noise(
                normalized_spot,
                detector,
                seed=int(rng.integers(0, 2**31 - 1)),
            )
        else:
            frame = _canonical_detector_frame(
                normalized_spot,
                detector,
                seed=None,
                clip_negative=True,
                random_streams=persistent_streams.scoped(
                    "legacy.sample_centroid_noise",
                    key=(trial_index,),
                ),
                realization=persistent_realization,
            )
            image_e = frame.image_e
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


def _instrument_provenance(source_class: str, source_note: str) -> _Provenance:
    """Build canonical provenance while retaining legacy instrument errors."""

    try:
        return _Provenance(source_class=source_class, source_note=str(source_note))
    except (TypeError, ValueError) as exc:
        if source_class not in ALLOWED_SOURCE_CLASSES:
            raise SyntheticInstrumentError(
                f"source_class={source_class!r} is not in the permitted taxonomy "
                f"{sorted(ALLOWED_SOURCE_CLASSES)}."
            ) from exc
        raise SyntheticInstrumentError("source_note must be a non-empty string.") from exc


def _require_nonnegative(field_name: str, value: float) -> None:
    _require_finite(field_name, value)
    if value < 0:
        raise SyntheticInstrumentError(f"{field_name} must be non-negative; got {value!r}.")


def _require_finite(field_name: str, value: float) -> None:
    if not math.isfinite(float(value)):
        raise SyntheticInstrumentError(f"{field_name} must be finite; got {value!r}.")
