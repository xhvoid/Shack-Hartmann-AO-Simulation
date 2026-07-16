"""
Detector-level Shack-Hartmann wavefront sensor utilities.

This module extends the geometric SH-WFS model in ``reconstruction.py`` by
simulating diffraction-limited lenslet spots, detector noise, centroiding, and
centroid-shift-based response matrices.

Centroid shifts are kept in detector-pixel units. The response matrix maps
modal coefficients or actuator commands directly to centroid shifts, so one
does not need to explicitly convert centroid shift to physical wavefront slope
for this compact learning simulator.

Validity note: the low-level ``measure_centroid_shifts`` utility here only
reports finite-centroid validity. The full flux / SNR / centroid-uncertainty /
window-clipping validity criteria used by the 2 m detector-level SCAO demonstrator
are implemented in ``synthetic_instrument_data.measure_detector_shwfs``.
"""

from __future__ import annotations

import numpy as np

from ..backends.native.shwfs import (
    NativeShackHartmannOptics as _NativeShackHartmannOptics,
    crop_center,
    lenslet_spot_from_phase,
    nominal_lenslet_sampling_shape,
)
from ..core.random import (
    NamedRandomStreams as _NamedRandomStreams,
    _legacy_sequential_child_seeds,
)
from ..detector.centroid import (
    CentroidConfig as _CentroidConfig,
    estimate_centroid as _estimate_centroid,
)
from ..detector.config import DetectorConfig as _DetectorConfig
from ..detector.effects import (
    apply_legacy_detector_effects as _apply_legacy_detector_effects,
)
from ..detector.random import DetectorRealization as _DetectorRealization
from ..detector.validity import CentroidValidityConfig as _CentroidValidityConfig
from ..wfs.shack_hartmann.measurement import (
    DetectorShackHartmannSensor as _DetectorShackHartmannSensor,
)
from ._interaction_adapters import (
    calibrate_legacy_modal_columns as _calibrate_legacy_modal_columns,
    legacy_streams as _legacy_calibration_streams,
    legacy_y_up_matrix as _legacy_y_up_matrix,
)
from ._reconstruction_adapters import (
    _legacy_least_squares_reconstructor,
    _legacy_lstsq_payload,
)

try:
    from .reconstruction import (
        _legacy_shack_hartmann_geometry,
        subaperture_masks,
    )
except Exception as exc:  # pragma: no cover
    raise ImportError(
        "shwfs_detector.py expects reconstruction.py to be available "
        "in the same project directory."
    ) from exc


_LEGACY_WFS_WAVELENGTH_M = 700.0e-9
_LEGACY_FINITE_CENTROID_VALIDITY = _CentroidValidityConfig(
    min_flux_e=0.0,
    min_peak_snr=0.0,
    max_centroid_sigma_px=1.0e6,
    max_window_clipping_fraction=1.0,
)


def add_detector_noise(
    normalized_spot: np.ndarray,
    photons: float | None = None,
    read_noise_e: float = 0.0,
    background_e: float = 0.0,
    seed: int | None = None,
    clip_negative: bool = True,
) -> np.ndarray:
    """Compatibility adapter over the canonical detector-effects pipeline."""

    config = _DetectorConfig(
        photons_per_subap_frame=photons,
        read_noise_e=read_noise_e,
        background_e_per_pixel_frame=background_e,
    )
    spot = np.asarray(normalized_spot, dtype=float)
    if seed is None:
        root_seed = int(np.random.SeedSequence().entropy)
        legacy_seed = None
    elif isinstance(seed, (int, np.integer)) and not isinstance(seed, (bool, np.bool_)):
        root_seed = int(seed)
        legacy_seed = root_seed
    else:
        raise ValueError(f"seed must be a non-negative integer or None; got {seed!r}.")
    streams = _NamedRandomStreams(root_seed)
    realization = _DetectorRealization.create(
        config,
        tuple(int(value) for value in spot.shape),
        random_streams=streams,
    )
    frame = _apply_legacy_detector_effects(
        spot,
        config,
        realization,
        random_streams=streams,
        clip_negative=clip_negative,
        legacy_seed=legacy_seed,
    )
    return np.array(frame.image_e, dtype=float, copy=True)


def centroid(
    image: np.ndarray,
    threshold_fraction: float = 0.0,
    subtract_minimum: bool = False,
) -> tuple[float, float]:
    """
    Compute a center-of-gravity centroid in detector-pixel coordinates.

    The coordinate origin is the geometric center of the image. Positive x is
    to the right; positive y is upward in mathematical coordinates.
    """
    estimator = (
        "thresholded_center_of_gravity"
        if threshold_fraction > 0.0
        else "center_of_gravity"
    )
    config = _CentroidConfig(
        estimator=estimator,
        threshold_fraction=threshold_fraction,
        subtract_minimum=subtract_minimum,
    )
    img = np.asarray(image, dtype=float)
    if np.all(np.isfinite(img)):
        estimate = _estimate_centroid(img, config)
    else:
        # Canonical estimators are deliberately strict. The installed legacy
        # adapter retains the former NaN-ignoring behavior before delegating.
        compatible = img.copy()
        if subtract_minimum:
            compatible -= np.nanmin(compatible)
            compatible = np.maximum(compatible, 0.0)
        if threshold_fraction > 0.0:
            max_value = np.nanmax(compatible)
            if np.isfinite(max_value):
                compatible[compatible < threshold_fraction * max_value] = 0.0
        total = np.nansum(compatible)
        if total <= 0.0 or not np.isfinite(total):
            return np.nan, np.nan
        compatible = np.where(np.isnan(compatible), 0.0, compatible)
        estimate = _estimate_centroid(compatible)

    if not estimate.finite:
        return np.nan, np.nan
    rows, columns = img.shape
    return (
        estimate.x_px - (columns - 1) / 2.0,
        (rows - 1) / 2.0 - estimate.y_px,
    )


def reference_centroids(
    pupil_mask: np.ndarray,
    X: np.ndarray,
    Y: np.ndarray,
    n_lenslets: int = 12,
    min_fill: float = 0.5,
    pad_factor: int = 8,
    threshold_fraction: float = 0.0,
    detector_window_size: int | None = None,
    subtract_minimum: bool = False,
) -> tuple[np.ndarray, list[np.ndarray], np.ndarray]:
    """
    Compute zero-phase reference centroids for all valid lenslets.

    The same detector-window and centroiding settings must be used here and in
    ``measure_centroid_shifts``; otherwise measured shifts are biased.
    """
    sensor, streams = _legacy_detector_sensor(
        X,
        Y,
        pupil_mask,
        n_lenslets=n_lenslets,
        min_fill=min_fill,
        pad_factor=pad_factor,
        photons=None,
        read_noise_e=0.0,
        background_e=0.0,
        threshold_fraction=threshold_fraction,
        subtract_minimum=subtract_minimum,
        detector_window_size=detector_window_size,
        seed=1,
    )
    del streams
    geometry = sensor.geometry
    reference = _legacy_centered_pixels(
        sensor.calibration.reference_centroids_px,
        sensor.calibration.detector_sampling.window_shape_px,
    )
    return (
        np.array(geometry.subaperture_centers_m, dtype=float, copy=True),
        [np.array(mask, dtype=bool, copy=True) for mask in geometry.subaperture_masks],
        reference,
    )


def measure_centroid_shifts(
    phase_rad: np.ndarray,
    pupil_mask: np.ndarray,
    X: np.ndarray,
    Y: np.ndarray,
    n_lenslets: int = 12,
    min_fill: float = 0.5,
    pad_factor: int = 8,
    photons: float | None = None,
    read_noise_e: float = 0.0,
    background_e: float = 0.0,
    threshold_fraction: float = 0.0,
    subtract_minimum: bool = False,
    detector_window_size: int | None = None,
    seed: int | None = 1,
    reference: np.ndarray | None = None,
    masks: list[np.ndarray] | None = None,
    centers: np.ndarray | None = None,
    return_spots: bool = False,
    return_diagnostics: bool = False,
):
    """
    Measure detector-level Shack-Hartmann centroid shifts.

    Chain:
        phase -> lenslet diffraction spot -> optional finite detector window
        -> photon/read/background noise -> centroid -> reference-subtracted shift
    """
    sensor, runtime_streams = _legacy_detector_sensor(
        X,
        Y,
        pupil_mask,
        n_lenslets=n_lenslets,
        min_fill=min_fill,
        pad_factor=pad_factor,
        photons=photons,
        read_noise_e=read_noise_e,
        background_e=background_e,
        threshold_fraction=threshold_fraction,
        subtract_minimum=subtract_minimum,
        detector_window_size=detector_window_size,
        seed=seed,
    )
    geometry = sensor.geometry
    canonical_centers = np.array(
        geometry.subaperture_centers_m,
        dtype=float,
        copy=True,
    )
    canonical_masks = [
        np.array(mask, dtype=bool, copy=True)
        for mask in geometry.subaperture_masks
    ]
    canonical_reference = _legacy_centered_pixels(
        sensor.calibration.reference_centroids_px,
        sensor.calibration.detector_sampling.window_shape_px,
    )

    if masks is None or centers is None or reference is None:
        centers = canonical_centers
        masks = canonical_masks
        reference = canonical_reference
    if len(masks) != len(reference):
        raise ValueError(
            "masks and reference must have the same length. "
            "Recompute reference_centroids() with the same detector settings."
        )
    if len(centers) != len(masks):
        raise ValueError("centers and masks must have the same length.")
    if len(masks) != len(canonical_masks):
        raise ValueError("masks must match the canonical retained lenslet geometry.")
    if not np.allclose(np.asarray(centers, dtype=float), canonical_centers):
        raise ValueError("centers must match the canonical retained lenslet geometry.")
    if any(
        not np.array_equal(np.asarray(actual, dtype=bool), expected)
        for actual, expected in zip(masks, canonical_masks)
    ):
        raise ValueError("masks must match the canonical retained lenslet geometry.")
    supplied_reference = np.asarray(reference, dtype=float)
    if supplied_reference.shape != canonical_reference.shape:
        raise ValueError("reference must have shape (n_subapertures, 2).")

    phase = np.asarray(phase_rad, dtype=float)
    if phase.shape != geometry.pupil_shape:
        raise ValueError("phase_rad must match the pupil grid shape.")
    residual_opd_m = np.zeros_like(phase, dtype=float)
    residual_opd_m[geometry.pupil_mask] = (
        phase[geometry.pupil_mask]
        * _LEGACY_WFS_WAVELENGTH_M
        / (2.0 * np.pi)
    )
    ordered_seeds = _legacy_sequential_child_seeds(
        None if seed is None else int(seed),
        len(geometry.subaperture_ids),
    )
    measurement = sensor._measure_legacy(
        residual_opd_m,
        random_streams=runtime_streams,
        include_noise=True,
        compatibility_mode="low_level",
        ordered_legacy_seeds=ordered_seeds,
    )
    telemetry = measurement.detector_telemetry
    if telemetry is None:  # pragma: no cover - enforced by detector sensor
        raise RuntimeError("Canonical detector measurement did not return telemetry.")
    centroids = _legacy_centered_pixels(
        telemetry.centroids_xy_px,
        sensor.calibration.detector_sampling.window_shape_px,
    )
    shifts = np.array(
        measurement.vector.values.reshape(-1, 2),
        dtype=float,
        copy=True,
    )
    shifts[:, 1] *= -1.0
    shifts += canonical_reference - supplied_reference
    valid = np.array(telemetry.valid_subapertures, dtype=bool, copy=True)
    valid &= np.all(np.isfinite(supplied_reference), axis=1)
    shifts[~valid] = np.nan
    fluxes = np.array(telemetry.fluxes_e, dtype=float, copy=True)
    detector_frames = telemetry.detector_frames
    if detector_frames is None:  # pragma: no cover - enforced by detector sensor
        raise RuntimeError("Canonical detector measurement did not return frames.")
    spots = [
        np.array(frame.image_e, dtype=float, copy=True)
        for frame in detector_frames
    ] if return_spots else []

    diagnostics = {
        "centroids": centroids,
        "reference": supplied_reference,
        "fluxes": fluxes,
        "valid": valid,
        "n_valid": int(np.sum(valid)),
        "n_total": int(len(valid)),
        "valid_centroid_frac": float(np.mean(valid)) if len(valid) else 0.0,
    }

    if return_spots and return_diagnostics:
        return centers, shifts, spots, diagnostics
    if return_spots:
        return centers, shifts, spots
    if return_diagnostics:
        return centers, shifts, diagnostics
    return centers, shifts


def _legacy_detector_sensor(
    X: np.ndarray,
    Y: np.ndarray,
    pupil_mask: np.ndarray,
    *,
    n_lenslets: int,
    min_fill: float,
    pad_factor: int,
    photons: float | None,
    read_noise_e: float,
    background_e: float,
    threshold_fraction: float,
    subtract_minimum: bool,
    detector_window_size: int | None,
    seed: int | None,
) -> tuple[_DetectorShackHartmannSensor, _NamedRandomStreams]:
    """Build the stateless legacy call's canonical detector-sensor context."""

    if seed is None:
        root_seed = int(np.random.SeedSequence().entropy)
    elif isinstance(seed, (int, np.integer)) and not isinstance(
        seed,
        (bool, np.bool_),
    ):
        root_seed = int(seed)
        if root_seed < 0:
            raise ValueError("seed must be a non-negative integer or None.")
    else:
        raise ValueError("seed must be a non-negative integer or None.")
    geometry = _legacy_shack_hartmann_geometry(
        X,
        Y,
        pupil_mask,
        n_lenslets=n_lenslets,
        min_fill=min_fill,
    )
    detector = _DetectorConfig(
        photons_per_subap_frame=photons,
        read_noise_e=read_noise_e,
        background_e_per_pixel_frame=background_e,
    )
    centroid_config = _CentroidConfig(
        estimator=(
            "thresholded_center_of_gravity"
            if threshold_fraction > 0.0
            else "center_of_gravity"
        ),
        threshold_fraction=threshold_fraction,
        subtract_minimum=subtract_minimum,
    )
    optics = _NativeShackHartmannOptics(
        geometry,
        _LEGACY_WFS_WAVELENGTH_M,
        pad_factor=pad_factor,
        detector_window_px=detector_window_size,
    )
    calibration_streams = _NamedRandomStreams(root_seed)
    sensor = _DetectorShackHartmannSensor.calibrate(
        geometry,
        optics,
        detector,
        wfs_wavelength_m=_LEGACY_WFS_WAVELENGTH_M,
        random_streams=calibration_streams,
        centroid_config=centroid_config,
        validity_config=_LEGACY_FINITE_CENTROID_VALIDITY,
    )
    runtime_streams = _NamedRandomStreams(root_seed).scoped(
        "legacy.measure_centroid_shifts",
        key=(),
    )
    return sensor, runtime_streams


def _legacy_centered_pixels(
    centroids_xy_px: np.ndarray,
    window_shape_px: tuple[int, int],
) -> np.ndarray:
    """Convert absolute row-positive pixels to centered legacy y-up pixels."""

    values = np.asarray(centroids_xy_px, dtype=float)
    if values.ndim != 2 or values.shape[1] != 2:
        raise ValueError("centroids must have shape (n_subapertures, 2).")
    rows, columns = window_shape_px
    centered = np.array(values, dtype=float, copy=True)
    centered[:, 0] -= (columns - 1) / 2.0
    centered[:, 1] = (rows - 1) / 2.0 - centered[:, 1]
    return centered


def build_detector_response_matrix(
    modes: dict[str, np.ndarray],
    pupil_mask: np.ndarray,
    X: np.ndarray,
    Y: np.ndarray,
    n_lenslets: int = 12,
    min_fill: float = 0.5,
    pad_factor: int = 8,
    threshold_fraction: float = 0.0,
    subtract_minimum: bool = False,
    detector_window_size: int | None = None,
    calibration_amplitude: float = 1e-3,
    differential: bool = True,
) -> tuple[np.ndarray, list[str], np.ndarray, list[np.ndarray], np.ndarray]:
    """
    Build a centroid-shift response matrix for detector-level SH-WFS.

    If ``differential=True``, use central finite-difference calibration:
        column_j = [s(+eps Z_j) - s(-eps Z_j)] / (2 eps)
    """
    if calibration_amplitude <= 0:
        raise ValueError("calibration_amplitude must be positive.")

    centers, masks, reference = reference_centroids(
        pupil_mask,
        X,
        Y,
        n_lenslets=n_lenslets,
        min_fill=min_fill,
        pad_factor=pad_factor,
        threshold_fraction=threshold_fraction,
        detector_window_size=detector_window_size,
        subtract_minimum=subtract_minimum,
    )
    sensor, _ = _legacy_detector_sensor(
        X,
        Y,
        pupil_mask,
        n_lenslets=n_lenslets,
        min_fill=min_fill,
        pad_factor=pad_factor,
        photons=None,
        read_noise_e=0.0,
        background_e=0.0,
        threshold_fraction=threshold_fraction,
        subtract_minimum=subtract_minimum,
        detector_window_size=detector_window_size,
        seed=1,
    )
    # The historical detector builder canonicalized non-finite mode samples
    # with ``nan_to_num`` before applying phase amplitudes.
    compatible_modes = {
        name: np.nan_to_num(mode, nan=0.0) for name, mode in modes.items()
    }
    response, names = _calibrate_legacy_modal_columns(
        compatible_modes,
        pupil_mask,
        sensor,
        coefficient_amplitude=(calibration_amplitude if differential else 1.0),
        opd_m_per_raw_unit=_LEGACY_WFS_WAVELENGTH_M / (2.0 * np.pi),
        method=("central" if differential else "forward"),
        random_streams=_legacy_calibration_streams(1),
    )
    # The canonical detector contract uses detector-row-positive y.  This
    # installed API historically exposed mathematical y-up centroid shifts.
    response = _legacy_y_up_matrix(response)
    return (
        np.array(response, dtype=float, copy=True),
        list(names),
        centers,
        masks,
        reference,
    )


def reconstruct_from_centroid_shifts(
    shifts: np.ndarray,
    response_matrix: np.ndarray,
    rcond: float = 1e-4,
) -> tuple[np.ndarray, np.ndarray, int, np.ndarray]:
    """
    Least-squares reconstruction from centroid shifts.

    Invalid centroid entries are removed together with the corresponding rows
    of the response matrix.
    """
    reconstructor = _legacy_least_squares_reconstructor(
        response_matrix,
        rcond,
        matrix_error="response_matrix must be 2-D.",
        length_error="shifts length must match response_matrix row count.",
        no_rows_error="No finite centroid measurements are available.",
    )
    result = reconstructor.reconstruct(shifts)
    return _legacy_lstsq_payload(
        result,
        coordinate_count=reconstructor.coordinate_count,
    )


def centroid_noise_scan(
    phase_rad: np.ndarray,
    response_matrix: np.ndarray,
    modes: dict[str, np.ndarray],
    names: list[str],
    pupil_mask: np.ndarray,
    X: np.ndarray,
    Y: np.ndarray,
    photon_levels: list[float],
    n_lenslets: int = 12,
    min_fill: float = 0.5,
    pad_factor: int = 8,
    read_noise_e: float = 0.0,
    background_e: float = 0.0,
    threshold_fraction: float = 0.0,
    subtract_minimum: bool = False,
    detector_window_size: int | None = None,
    n_trials: int = 10,
    seed: int = 1,
    rcond: float = 1e-4,
) -> dict[float, dict[str, float]]:
    """Scan photon-noise sensitivity and summarize residual RMS."""
    from .reconstruction import synthesize_from_coefficients, residual_wavefront, rms

    centers, masks, reference = reference_centroids(
        pupil_mask,
        X,
        Y,
        n_lenslets=n_lenslets,
        min_fill=min_fill,
        pad_factor=pad_factor,
        threshold_fraction=threshold_fraction,
        detector_window_size=detector_window_size,
        subtract_minimum=subtract_minimum,
    )

    rng = np.random.default_rng(seed)
    out = {}
    reconstructor = _legacy_least_squares_reconstructor(
        response_matrix,
        rcond,
        matrix_error="response_matrix must be 2-D.",
        length_error="shifts length must match response_matrix row count.",
        no_rows_error="No finite centroid measurements are available.",
    )

    for photons in photon_levels:
        residuals = []
        valid_counts = []
        for _ in range(n_trials):
            _, shifts, diag = measure_centroid_shifts(
                phase_rad,
                pupil_mask,
                X,
                Y,
                n_lenslets=n_lenslets,
                min_fill=min_fill,
                pad_factor=pad_factor,
                photons=photons,
                read_noise_e=read_noise_e,
                background_e=background_e,
                threshold_fraction=threshold_fraction,
                subtract_minimum=subtract_minimum,
                detector_window_size=detector_window_size,
                seed=int(rng.integers(0, 2**31 - 1)),
                reference=reference,
                masks=masks,
                centers=centers,
                return_diagnostics=True,
            )
            reconstruction = reconstructor.reconstruct(shifts)
            coeffs = reconstruction.coordinates
            W_rec = synthesize_from_coefficients(coeffs, modes, names, pupil_mask, remove_mean=True)
            res = residual_wavefront(phase_rad, W_rec, pupil_mask)
            residuals.append(rms(res, pupil_mask))
            valid_counts.append(diag["n_valid"])

        residuals = np.asarray(residuals, dtype=float)
        out[float(photons)] = {
            "mean_residual_rms": float(np.nanmean(residuals)),
            "std_residual_rms": float(np.nanstd(residuals)),
            "mean_valid_centroids": float(np.mean(valid_counts)),
        }

    return out
