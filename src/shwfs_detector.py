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

try:
    from reconstruction import subaperture_masks
except Exception as exc:  # pragma: no cover
    raise ImportError(
        "shwfs_detector.py expects reconstruction.py to be available "
        "in the same project directory."
    ) from exc


def _bounding_box(mask: np.ndarray, margin: int = 0) -> tuple[slice, slice]:
    """Return a rectangular bounding box around a boolean mask."""
    yy, xx = np.where(mask)
    if yy.size == 0:
        raise ValueError("Cannot build a bounding box for an empty mask.")

    y0 = max(int(yy.min()) - margin, 0)
    y1 = min(int(yy.max()) + margin + 1, mask.shape[0])
    x0 = max(int(xx.min()) - margin, 0)
    x1 = min(int(xx.max()) + margin + 1, mask.shape[1])
    return slice(y0, y1), slice(x0, x1)


def lenslet_spot_from_phase(
    phase_rad: np.ndarray,
    lenslet_mask: np.ndarray,
    pad_factor: int = 8,
    remove_local_piston: bool = True,
) -> np.ndarray:
    """Compute a diffraction spot from one Shack-Hartmann lenslet."""
    if pad_factor < 1:
        raise ValueError("pad_factor must be >= 1.")

    ys, xs = _bounding_box(lenslet_mask)
    local_mask = lenslet_mask[ys, xs]
    local_phase = np.nan_to_num(phase_rad[ys, xs], nan=0.0).astype(float)

    if remove_local_piston and np.any(local_mask):
        local_phase = local_phase.copy()
        local_phase[local_mask] -= np.mean(local_phase[local_mask])

    local_field = np.zeros(local_phase.shape, dtype=complex)
    local_field[local_mask] = np.exp(1j * local_phase[local_mask])

    ny, nx = local_field.shape
    pad_ny = int(pad_factor * ny)
    pad_nx = int(pad_factor * nx)

    padded = np.zeros((pad_ny, pad_nx), dtype=complex)
    y0 = (pad_ny - ny) // 2
    x0 = (pad_nx - nx) // 2
    padded[y0 : y0 + ny, x0 : x0 + nx] = local_field

    focal_field = np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(padded)))
    spot = np.abs(focal_field) ** 2
    total = spot.sum()
    if total > 0:
        spot = spot / total
    return spot


def crop_center(image: np.ndarray, window_size: int | None = None) -> np.ndarray:
    """
    Crop a square detector window around the geometric center of an image.

    This mimics the finite detector window assigned to one SH-WFS lenslet spot.
    If the spot moves too far, it can be clipped, producing centroid bias.
    """
    img = np.asarray(image)
    if window_size is None:
        return img

    window_size = int(window_size)
    if window_size <= 0:
        raise ValueError("window_size must be positive or None.")

    ny, nx = img.shape
    if window_size >= min(ny, nx):
        return img

    cy = ny // 2
    cx = nx // 2
    half = window_size // 2

    if window_size % 2 == 0:
        y0, y1 = cy - half, cy + half
        x0, x1 = cx - half, cx + half
    else:
        y0, y1 = cy - half, cy + half + 1
        x0, x1 = cx - half, cx + half + 1

    return img[y0:y1, x0:x1]


def add_detector_noise(
    normalized_spot: np.ndarray,
    photons: float | None = None,
    read_noise_e: float = 0.0,
    background_e: float = 0.0,
    seed: int | None = None,
    clip_negative: bool = True,
) -> np.ndarray:
    """Add photon noise, read noise, and background to a normalized spot."""
    if read_noise_e < 0:
        raise ValueError("read_noise_e must be non-negative.")
    if background_e < 0:
        raise ValueError("background_e must be non-negative.")

    rng = np.random.default_rng(seed)
    spot = np.asarray(normalized_spot, dtype=float)

    if photons is None:
        image = spot.copy()
        if background_e != 0:
            image = image + background_e
        if read_noise_e > 0:
            image = image + rng.normal(scale=read_noise_e, size=spot.shape)
    else:
        if photons < 0:
            raise ValueError("photons must be non-negative or None.")
        expected = photons * spot + background_e
        image = rng.poisson(expected).astype(float)
        if read_noise_e > 0:
            image = image + rng.normal(scale=read_noise_e, size=spot.shape)

    if clip_negative:
        image = np.maximum(image, 0.0)
    return image


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
    if threshold_fraction < 0:
        raise ValueError("threshold_fraction must be non-negative.")

    img = np.asarray(image, dtype=float).copy()

    if subtract_minimum:
        img -= np.nanmin(img)
        img = np.maximum(img, 0.0)

    if threshold_fraction > 0:
        max_val = np.nanmax(img)
        if np.isfinite(max_val):
            threshold = threshold_fraction * max_val
            img[img < threshold] = 0.0

    total = np.nansum(img)
    if total <= 0 or not np.isfinite(total):
        return np.nan, np.nan

    ny, nx = img.shape
    x = np.arange(nx) - (nx - 1) / 2.0
    y = (ny - 1) / 2.0 - np.arange(ny)
    X, Y = np.meshgrid(x, y)

    cx = float(np.nansum(img * X) / total)
    cy = float(np.nansum(img * Y) / total)
    return cx, cy


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
    centers, masks = subaperture_masks(
        X,
        Y,
        pupil_mask,
        n_lenslets=n_lenslets,
        min_fill=min_fill,
    )

    zero_phase = np.zeros_like(X, dtype=float)
    refs = []
    for m in masks:
        spot0 = lenslet_spot_from_phase(
            zero_phase,
            m,
            pad_factor=pad_factor,
            remove_local_piston=True,
        )
        spot0 = crop_center(spot0, detector_window_size)
        refs.append(
            centroid(
                spot0,
                threshold_fraction=threshold_fraction,
                subtract_minimum=subtract_minimum,
            )
        )

    return centers, masks, np.asarray(refs, dtype=float)


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
    if masks is None or centers is None or reference is None:
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

    if len(masks) != len(reference):
        raise ValueError(
            "masks and reference must have the same length. "
            "Recompute reference_centroids() with the same detector settings."
        )
    if len(centers) != len(masks):
        raise ValueError("centers and masks must have the same length.")

    rng = np.random.default_rng(seed)

    shifts = []
    centroids = []
    fluxes = []
    valid = []
    spots = []

    for i, m in enumerate(masks):
        spot = lenslet_spot_from_phase(
            phase_rad,
            m,
            pad_factor=pad_factor,
            remove_local_piston=True,
        )
        spot = crop_center(spot, detector_window_size)

        noisy = add_detector_noise(
            spot,
            photons=photons,
            read_noise_e=read_noise_e,
            background_e=background_e,
            seed=int(rng.integers(0, 2**31 - 1)),
        )

        c = np.asarray(
            centroid(
                noisy,
                threshold_fraction=threshold_fraction,
                subtract_minimum=subtract_minimum,
            ),
            dtype=float,
        )
        ref = np.asarray(reference[i], dtype=float)

        is_valid = np.all(np.isfinite(c)) and np.all(np.isfinite(ref))
        shift = c - ref if is_valid else np.array([np.nan, np.nan], dtype=float)

        shifts.append(shift)
        centroids.append(c)
        fluxes.append(float(np.nansum(noisy)))
        valid.append(bool(is_valid))
        if return_spots:
            spots.append(noisy)

    shifts = np.asarray(shifts, dtype=float)
    centroids = np.asarray(centroids, dtype=float)
    fluxes = np.asarray(fluxes, dtype=float)
    valid = np.asarray(valid, dtype=bool)

    diagnostics = {
        "centroids": centroids,
        "reference": np.asarray(reference, dtype=float),
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

    names = list(modes.keys())
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

    columns = []
    for name in names:
        mode = np.nan_to_num(modes[name], nan=0.0)

        if differential:
            phase_p = calibration_amplitude * mode
            phase_m = -calibration_amplitude * mode

            _, shifts_p = measure_centroid_shifts(
                phase_p,
                pupil_mask,
                X,
                Y,
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
                reference=reference,
                masks=masks,
                centers=centers,
            )
            _, shifts_m = measure_centroid_shifts(
                phase_m,
                pupil_mask,
                X,
                Y,
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
                reference=reference,
                masks=masks,
                centers=centers,
            )
            column = ((shifts_p - shifts_m) / (2.0 * calibration_amplitude)).reshape(-1)
        else:
            _, shifts = measure_centroid_shifts(
                mode,
                pupil_mask,
                X,
                Y,
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
                reference=reference,
                masks=masks,
                centers=centers,
            )
            column = shifts.reshape(-1)

        columns.append(column)

    A = np.column_stack(columns) if columns else np.empty((2 * len(masks), 0))
    return A, names, centers, masks, reference


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
    s = np.asarray(shifts, dtype=float).reshape(-1)
    A = np.asarray(response_matrix, dtype=float)
    if A.shape[0] != s.size:
        raise ValueError("shifts length must match response_matrix row count.")

    valid = np.isfinite(s) & np.all(np.isfinite(A), axis=1)
    if not np.any(valid):
        raise ValueError("No finite centroid measurements are available.")

    coeffs, residuals, rank, singular_values = np.linalg.lstsq(A[valid], s[valid], rcond=rcond)
    return coeffs, residuals, rank, singular_values


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
    from reconstruction import synthesize_from_coefficients, residual_wavefront, rms

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
            coeffs, *_ = reconstruct_from_centroid_shifts(shifts, response_matrix, rcond=rcond)
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
