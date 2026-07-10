"""
Pyramid wavefront sensor forward model.

This module implements a simplified Fourier-optics PWFS model:
    pupil phase
    -> focal-plane pyramid phase mask
    -> four re-imaged pupil intensities
    -> aligned Sx/Sy signal maps
    -> detector-level noisy measurement, optional

The functions are intentionally stateless: all geometry parameters are passed
explicitly, so the module can be reused by different notebooks.
"""

import numpy as np


def fft2c(a):
    """
    Centered 2D Fourier transform.
    """
    return np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(a)))


def ifft2c(a):
    """
    Centered inverse 2D Fourier transform.
    """
    return np.fft.fftshift(np.fft.ifft2(np.fft.ifftshift(a)))


def make_pwfs_grid(
    n_fft=384,
    n_pupil=128,
    central_obscuration=0.0,
):
    """
    Create normalized pupil coordinates on a padded FFT grid.

    Parameters
    ----------
    n_fft : int
        Full FFT grid size.
    n_pupil : int
        Diameter of the physical pupil in pixels.
    central_obscuration : float
        Central obscuration radius as fraction of pupil radius.

    Returns
    -------
    x, y, rho, theta : 2D arrays
        Normalized pupil coordinates.
    pupil : 2D bool array
        Pupil mask on the padded FFT grid.
    """
    yy, xx = np.indices((n_fft, n_fft))

    # Integer-centered FFT grid.
    c = n_fft // 2

    x = (xx - c) / (n_pupil / 2.0)
    y = (yy - c) / (n_pupil / 2.0)

    rho = np.sqrt(x**2 + y**2)
    theta = np.arctan2(y, x)

    pupil = rho <= 1.0

    if central_obscuration > 0.0:
        pupil &= rho >= central_obscuration

    return x, y, rho, theta, pupil


def make_aligned_pupil_mask(
    n_pupil=128,
    central_obscuration=0.0,
):
    """
    Pupil mask on the cropped aligned pupil-image grid.

    This mask is used after extracting each of the four re-imaged pupil images.
    """
    yy, xx = np.indices((n_pupil, n_pupil))

    # For a cropped image of even size, the geometric center is (N-1)/2.
    # But here the crop is taken around integer FFT centers, so using n_pupil/2
    # matches the extraction convention used in the PWFS forward model.
    c = n_pupil / 2.0

    r = np.sqrt((xx - c)**2 + (yy - c)**2) / (n_pupil / 2.0)

    mask = r <= 1.0

    if central_obscuration > 0.0:
        mask &= r >= central_obscuration

    return mask


def pyramid_phase_mask(
    n_fft=384,
    separation=96,
):
    """
    Quadrant-dependent phase ramp approximating a four-face pyramid mask.

    The phase ramp separates the four re-imaged pupils by approximately
    `separation` pixels from the detector center.
    """
    yy, xx = np.indices((n_fft, n_fft))

    c = n_fft // 2

    fx = xx - c
    fy = yy - c

    mask = np.exp(
        -2j * np.pi * separation * (np.abs(fx) + np.abs(fy)) / n_fft
    )

    return mask


def add_tilt_phase(x, y, tx, ty):
    """
    Add pupil-plane tilt for circular modulation.

    tx, ty are in approximate lambda/D-like units.
    """
    return 2.0 * np.pi * (tx * x + ty * y)


def make_modulation_points(
    modulation_radius=0.0,
    n_modulation_points=12,
):
    """
    Return modulation points on a circle in focal-plane units.
    """
    if modulation_radius == 0.0:
        return [(0.0, 0.0)]

    angles = np.linspace(
        0.0,
        2.0 * np.pi,
        n_modulation_points,
        endpoint=False,
    )

    return [
        (
            modulation_radius * np.cos(a),
            modulation_radius * np.sin(a),
        )
        for a in angles
    ]


def pwfs_intensity(
    phase,
    pupil,
    x,
    y,
    pyramid_mask=None,
    separation=96,
    modulation_radius=0.0,
    n_modulation_points=12,
):
    """
    Compute noiseless PWFS detector intensity.

    Parameters
    ----------
    phase : 2D array
        Input pupil phase in radians on the padded FFT grid.
    pupil : 2D bool or float array
        Pupil mask on the padded FFT grid.
    x, y : 2D arrays
        Normalized pupil coordinates.
    pyramid_mask : 2D complex array or None
        Precomputed pyramid phase mask. If None, it is generated internally.
    separation : int
        Pyramid pupil separation in detector pixels.
    modulation_radius : float
        Circular modulation radius. 0 means non-modulated PWFS.
    n_modulation_points : int
        Number of circular modulation points.

    Returns
    -------
    intensity : 2D array
        Noiseless detector intensity image.
    """
    phase = np.asarray(phase, dtype=float)
    pupil = np.asarray(pupil, dtype=float)

    n_fft = phase.shape[0]

    if phase.shape[0] != phase.shape[1]:
        raise ValueError("phase must be a square 2D array.")

    if pupil.shape != phase.shape:
        raise ValueError("pupil must have the same shape as phase.")

    if x.shape != phase.shape or y.shape != phase.shape:
        raise ValueError("x and y must have the same shape as phase.")

    if pyramid_mask is not None and pyramid_mask.shape != phase.shape:
        raise ValueError("pyramid_mask must have the same shape as phase.")

    if pyramid_mask is None:
        pyramid_mask = pyramid_phase_mask(
            n_fft=n_fft,
            separation=separation,
        )

    intensity = np.zeros_like(phase, dtype=float)

    modulation_points = make_modulation_points(
        modulation_radius=modulation_radius,
        n_modulation_points=n_modulation_points,
    )

    for tx, ty in modulation_points:
        tilt = add_tilt_phase(x, y, tx, ty)

        field_pupil = pupil * np.exp(1j * (phase + tilt))

        field_focal = fft2c(field_pupil)

        field_detector = ifft2c(field_focal * pyramid_mask)

        intensity += np.abs(field_detector)**2

    intensity /= len(modulation_points)

    return intensity


def pupil_image_centers(
    n_fft=384,
    separation=96,
):
    """
    Return the expected detector centers of the four re-imaged pupils.

    Coordinates are returned as (cx, cy), matching image indexing [y, x].
    """
    c = n_fft // 2

    return {
        "LL": (c - separation, c - separation),
        "LR": (c + separation, c - separation),
        "UL": (c - separation, c + separation),
        "UR": (c + separation, c + separation),
    }


def extract_cutout(
    image,
    center_xy,
    size=128,
):
    """
    Extract a square cutout centered on center_xy = (cx, cy).
    """
    cx, cy = center_xy
    half = size // 2

    y0 = cy - half
    y1 = cy + half
    x0 = cx - half
    x1 = cx + half

    if y0 < 0 or x0 < 0 or y1 > image.shape[0] or x1 > image.shape[1]:
        raise ValueError(
            "Requested cutout extends outside the detector image. "
            "Increase n_fft or reduce separation / n_pupil."
        )

    return image[y0:y1, x0:x1]


def aligned_pupil_images(
    intensity,
    n_pupil=128,
    separation=96,
):
    """
    Extract four aligned re-imaged pupil images from the detector frame.
    """
    n_fft = intensity.shape[0]

    centers = pupil_image_centers(
        n_fft=n_fft,
        separation=separation,
    )

    return {
        key: extract_cutout(
            intensity,
            center_xy=center,
            size=n_pupil,
        )
        for key, center in centers.items()
    }


def pwfs_signal_maps_from_intensity(
    intensity,
    n_pupil=128,
    separation=96,
    central_obscuration=0.0,
    eps=1e-12,
):
    """
    Compute aligned PWFS Sx/Sy signal maps from a detector intensity image.

    Returns
    -------
    Sx, Sy : 2D arrays
        Normalized PWFS signal maps on the aligned pupil grid.
    total : 2D array
        Total aligned pupil intensity.
    valid : 2D bool array
        Valid aligned pupil mask.
    """
    imgs = aligned_pupil_images(
        intensity,
        n_pupil=n_pupil,
        separation=separation,
    )

    LL = imgs["LL"]
    LR = imgs["LR"]
    UL = imgs["UL"]
    UR = imgs["UR"]

    total = LL + LR + UL + UR + eps

    Sx = ((LR + UR) - (LL + UL)) / total
    Sy = ((UL + UR) - (LL + LR)) / total

    valid = make_aligned_pupil_mask(
        n_pupil=n_pupil,
        central_obscuration=central_obscuration,
    )

    Sx = np.where(valid, Sx, 0.0)
    Sy = np.where(valid, Sy, 0.0)
    total = np.where(valid, total, 0.0)

    return Sx, Sy, total, valid


def pwfs_signal_from_intensity(
    intensity,
    n_pupil=128,
    separation=96,
    central_obscuration=0.0,
):
    """
    Return concatenated PWFS signal vector [Sx_valid, Sy_valid].
    """
    Sx, Sy, total, valid = pwfs_signal_maps_from_intensity(
        intensity,
        n_pupil=n_pupil,
        separation=separation,
        central_obscuration=central_obscuration,
    )

    return np.concatenate(
        [
            Sx[valid],
            Sy[valid],
        ]
    )


def pwfs_signal_from_phase(
    phase,
    pupil,
    x,
    y,
    n_pupil=128,
    separation=96,
    central_obscuration=0.0,
    pyramid_mask=None,
    modulation_radius=0.0,
    n_modulation_points=12,
):
    """
    Compute noiseless PWFS signal vector from input phase.
    """
    intensity = pwfs_intensity(
        phase=phase,
        pupil=pupil,
        x=x,
        y=y,
        pyramid_mask=pyramid_mask,
        separation=separation,
        modulation_radius=modulation_radius,
        n_modulation_points=n_modulation_points,
    )

    return pwfs_signal_from_intensity(
        intensity,
        n_pupil=n_pupil,
        separation=separation,
        central_obscuration=central_obscuration,
    )


def pwfs_reference_signal(
    pupil,
    x,
    y,
    n_pupil=128,
    separation=96,
    central_obscuration=0.0,
    pyramid_mask=None,
    modulation_radius=0.0,
    n_modulation_points=12,
):
    """
    Compute flat-wavefront reference signal.
    """
    phase0 = np.zeros_like(pupil, dtype=float)

    return pwfs_signal_from_phase(
        phase=phase0,
        pupil=pupil,
        x=x,
        y=y,
        n_pupil=n_pupil,
        separation=separation,
        central_obscuration=central_obscuration,
        pyramid_mask=pyramid_mask,
        modulation_radius=modulation_radius,
        n_modulation_points=n_modulation_points,
    )


def pwfs_measurement_from_phase(
    phase,
    pupil,
    x,
    y,
    reference_signal=None,
    n_pupil=128,
    separation=96,
    central_obscuration=0.0,
    pyramid_mask=None,
    modulation_radius=0.0,
    n_modulation_points=12,
):
    """
    Reference-subtracted noiseless PWFS measurement vector.
    """
    signal = pwfs_signal_from_phase(
        phase=phase,
        pupil=pupil,
        x=x,
        y=y,
        n_pupil=n_pupil,
        separation=separation,
        central_obscuration=central_obscuration,
        pyramid_mask=pyramid_mask,
        modulation_radius=modulation_radius,
        n_modulation_points=n_modulation_points,
    )

    if reference_signal is None:
        reference_signal = pwfs_reference_signal(
            pupil=pupil,
            x=x,
            y=y,
            n_pupil=n_pupil,
            separation=separation,
            central_obscuration=central_obscuration,
            pyramid_mask=pyramid_mask,
            modulation_radius=modulation_radius,
            n_modulation_points=n_modulation_points,
        )

    return signal - reference_signal


def add_detector_noise(
    intensity,
    n_photons=1e6,
    read_noise_e=0.0,
    seed=None,
):
    """
    Convert noiseless detector intensity to noisy photo-electron image.

    Parameters
    ----------
    intensity : 2D array
        Noiseless detector intensity in arbitrary units.
    n_photons : float
        Total photon/electron count over the whole detector image.
    read_noise_e : float
        Gaussian read noise standard deviation in electrons per pixel.
    seed : int or None
        RNG seed.

    Returns
    -------
    noisy : 2D array
        Noisy detector image in electrons.
    """
    rng = np.random.default_rng(seed)

    intensity = np.asarray(intensity, dtype=float)
    intensity = np.clip(intensity, 0.0, None)
    """
    Read-noise-perturbed pixels are clipped to non-negative values before normalized PWFS signal extraction.
    This stabilizes the simplified detector model but is not a full detector-readout model.
    """

    total = np.sum(intensity)

    if total <= 0:
        raise ValueError("Input intensity has zero total flux.")

    expected_e = intensity / total * n_photons

    noisy = rng.poisson(expected_e).astype(float)

    if read_noise_e > 0.0:
        noisy += rng.normal(
            loc=0.0,
            scale=read_noise_e,
            size=noisy.shape,
        )

    # Detector pixels cannot be physically negative, but after bias subtraction
    # read noise may produce negative values. For signal normalization, clipping
    # is usually safer in this simplified model.
    noisy = np.clip(noisy, 0.0, None)

    return noisy


def pwfs_detector_signal_from_phase(
    phase,
    pupil,
    x,
    y,
    n_photons=1e6,
    read_noise_e=0.0,
    seed=None,
    n_pupil=128,
    separation=96,
    central_obscuration=0.0,
    pyramid_mask=None,
    modulation_radius=0.0,
    n_modulation_points=12,
):
    """
    Detector-level PWFS signal vector from a noisy detector image.
    """
    intensity = pwfs_intensity(
        phase=phase,
        pupil=pupil,
        x=x,
        y=y,
        pyramid_mask=pyramid_mask,
        separation=separation,
        modulation_radius=modulation_radius,
        n_modulation_points=n_modulation_points,
    )

    noisy_intensity = add_detector_noise(
        intensity,
        n_photons=n_photons,
        read_noise_e=read_noise_e,
        seed=seed,
    )

    signal = pwfs_signal_from_intensity(
        noisy_intensity,
        n_pupil=n_pupil,
        separation=separation,
        central_obscuration=central_obscuration,
    )

    return signal


def pwfs_detector_measurement_from_phase(
    phase,
    pupil,
    x,
    y,
    reference_signal=None,
    n_photons=1e6,
    read_noise_e=0.0,
    seed=None,
    n_pupil=128,
    separation=96,
    central_obscuration=0.0,
    pyramid_mask=None,
    modulation_radius=0.0,
    n_modulation_points=12,
):
    """
    Reference-subtracted detector-level PWFS measurement.

    Important:
    The reference_signal should normally be computed from a high-SNR or
    noiseless flat wavefront, not from the same noisy science realization.
    """
    signal = pwfs_detector_signal_from_phase(
        phase=phase,
        pupil=pupil,
        x=x,
        y=y,
        n_photons=n_photons,
        read_noise_e=read_noise_e,
        seed=seed,
        n_pupil=n_pupil,
        separation=separation,
        central_obscuration=central_obscuration,
        pyramid_mask=pyramid_mask,
        modulation_radius=modulation_radius,
        n_modulation_points=n_modulation_points,
    )

    if reference_signal is None:
        reference_signal = pwfs_reference_signal(
            pupil=pupil,
            x=x,
            y=y,
            n_pupil=n_pupil,
            separation=separation,
            central_obscuration=central_obscuration,
            pyramid_mask=pyramid_mask,
            modulation_radius=modulation_radius,
            n_modulation_points=n_modulation_points,
        )

    return signal - reference_signal


def calibrate_pwfs_interaction_matrix(
    modes,
    pupil,
    x,
    y,
    calibration_amplitude=1e-3,
    n_pupil=128,
    separation=96,
    central_obscuration=0.0,
    pyramid_mask=None,
    modulation_radius=0.0,
    n_modulation_points=12,
    differential=True,
):
    """
    Build a PWFS interaction matrix using modal finite differences.

    Parameters
    ----------
    modes : dict or sequence of 2D arrays
        Modal basis on the PWFS padded FFT grid.
        If dict, insertion order is used and mode names are returned.
    differential : bool
        If True, use central finite difference:
            [s(+a) - s(-a)] / (2a)
        If False, use one-sided difference:
            [s(+a) - s(0)] / a

    Returns
    -------
    A : 2D array
        Interaction matrix mapping modal coefficients to PWFS signal vector.
    mode_names : list
        Names of modes if modes is a dict, otherwise integer labels.
    reference_signal : 1D array
        Flat-wavefront reference signal.
    """
    if isinstance(modes, dict):
        mode_names = list(modes.keys())
        mode_list = [np.nan_to_num(modes[name], nan=0.0) for name in mode_names]
    else:
        mode_list = [np.nan_to_num(m, nan=0.0) for m in modes]
        mode_names = [f"mode_{i}" for i in range(len(mode_list))]

    if pyramid_mask is None:
        pyramid_mask = pyramid_phase_mask(
            n_fft=pupil.shape[0],
            separation=separation,
        )

    reference_signal = pwfs_reference_signal(
        pupil=pupil,
        x=x,
        y=y,
        n_pupil=n_pupil,
        separation=separation,
        central_obscuration=central_obscuration,
        pyramid_mask=pyramid_mask,
        modulation_radius=modulation_radius,
        n_modulation_points=n_modulation_points,
    )

    cols = []

    for mode in mode_list:
        if differential:
            sp = pwfs_measurement_from_phase(
                +calibration_amplitude * mode,
                pupil=pupil,
                x=x,
                y=y,
                reference_signal=reference_signal,
                n_pupil=n_pupil,
                separation=separation,
                central_obscuration=central_obscuration,
                pyramid_mask=pyramid_mask,
                modulation_radius=modulation_radius,
                n_modulation_points=n_modulation_points,
            )

            sm = pwfs_measurement_from_phase(
                -calibration_amplitude * mode,
                pupil=pupil,
                x=x,
                y=y,
                reference_signal=reference_signal,
                n_pupil=n_pupil,
                separation=separation,
                central_obscuration=central_obscuration,
                pyramid_mask=pyramid_mask,
                modulation_radius=modulation_radius,
                n_modulation_points=n_modulation_points,
            )

            col = (sp - sm) / (2.0 * calibration_amplitude)

        else:
            sp = pwfs_measurement_from_phase(
                +calibration_amplitude * mode,
                pupil=pupil,
                x=x,
                y=y,
                reference_signal=reference_signal,
                n_pupil=n_pupil,
                separation=separation,
                central_obscuration=central_obscuration,
                pyramid_mask=pyramid_mask,
                modulation_radius=modulation_radius,
                n_modulation_points=n_modulation_points,
            )

            col = sp / calibration_amplitude

        cols.append(col)

    A = np.column_stack(cols)

    return A, mode_names, reference_signal


def check_pwfs_geometry(
    n_fft,
    n_pupil,
    separation,
):
    """
    Basic geometry check for PWFS pupil extraction.
    """
    half = n_pupil // 2
    c = n_fft // 2

    centers = pupil_image_centers(
        n_fft=n_fft,
        separation=separation,
    )

    for key, (cx, cy) in centers.items():
        if (
            cy - half < 0
            or cy + half > n_fft
            or cx - half < 0
            or cx + half > n_fft
        ):
            raise ValueError(
                f"Pupil image {key} is clipped. "
                f"Use larger n_fft or smaller separation/n_pupil."
            )

    return True


def make_modulation_points(
    modulation_radius=0.0,
    n_modulation_points=12,
):
    """
    Return modulation points on a circle in focal-plane units.
    """
    if modulation_radius < 0.0:
        raise ValueError("modulation_radius must be non-negative.")

    if n_modulation_points < 1:
        raise ValueError("n_modulation_points must be >= 1.")

    if modulation_radius == 0.0:
        return [(0.0, 0.0)]

    angles = np.linspace(
        0.0,
        2.0 * np.pi,
        n_modulation_points,
        endpoint=False,
    )

    return [
        (
            modulation_radius * np.cos(a),
            modulation_radius * np.sin(a),
        )
        for a in angles
    ]