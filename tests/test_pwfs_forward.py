import numpy as np
import pytest

from pwfs_forward import (
    aligned_pupil_images,
    calibrate_pwfs_interaction_matrix,
    check_pwfs_geometry,
    extract_cutout,
    make_aligned_pupil_mask,
    make_modulation_points,
    make_pwfs_grid,
    pwfs_intensity,
    pwfs_signal_from_intensity,
)


def _pwfs_case(n_fft=128, n_pupil=31, separation=32):
    x, y, _, _, pupil = make_pwfs_grid(n_fft=n_fft, n_pupil=n_pupil)
    phase = np.zeros((n_fft, n_fft), dtype=float)
    return x, y, pupil, phase, n_pupil, separation


def test_pwfs_accepts_nan_only_outside_pupil_and_produces_finite_signal():
    x, y, pupil, phase, n_pupil, separation = _pwfs_case()
    exterior_nan = np.where(pupil, phase, np.nan)

    intensity_nan = pwfs_intensity(
        exterior_nan,
        pupil,
        x,
        y,
        separation=separation,
    )
    intensity_zero = pwfs_intensity(
        phase,
        pupil,
        x,
        y,
        separation=separation,
    )
    signal = pwfs_signal_from_intensity(
        intensity_nan,
        n_pupil=n_pupil,
        separation=separation,
    )

    assert np.all(np.isfinite(intensity_nan))
    assert np.allclose(intensity_nan, intensity_zero)
    assert np.all(np.isfinite(signal))
    assert signal.size == 2 * np.sum(make_aligned_pupil_mask(n_pupil))


@pytest.mark.parametrize("invalid_value", [np.nan, np.inf])
def test_pwfs_rejects_nonfinite_phase_inside_pupil(invalid_value):
    x, y, pupil, phase, _, separation = _pwfs_case()
    inside_y, inside_x = np.argwhere(pupil)[0]
    phase[inside_y, inside_x] = invalid_value

    with pytest.raises(ValueError, match="finite inside the pupil"):
        pwfs_intensity(phase, pupil, x, y, separation=separation)


@pytest.mark.parametrize("size", [14, 15])
def test_even_and_odd_pwfs_cutouts_have_exact_requested_shape(size):
    image = np.arange(41 * 41, dtype=float).reshape(41, 41)
    cutout = extract_cutout(image, center_xy=(20, 20), size=size)

    assert cutout.shape == (size, size)
    assert cutout[size // 2, size // 2] == image[20, 20]


@pytest.mark.parametrize("n_pupil", [30, 31])
def test_even_and_odd_pwfs_geometry_extracts_four_exact_pupils(n_pupil):
    n_fft = 128
    separation = 32
    image = np.ones((n_fft, n_fft), dtype=float)

    assert check_pwfs_geometry(n_fft, n_pupil, separation)
    images = aligned_pupil_images(image, n_pupil=n_pupil, separation=separation)

    assert set(images) == {"LL", "LR", "UL", "UR"}
    assert all(value.shape == (n_pupil, n_pupil) for value in images.values())
    assert make_aligned_pupil_mask(n_pupil)[n_pupil // 2, n_pupil // 2]


def test_modulation_contract_and_circle_geometry():
    points = np.asarray(make_modulation_points(2.0, 8), dtype=float)

    assert points.shape == (8, 2)
    assert np.linalg.norm(points, axis=1) == pytest.approx(2.0)
    assert make_modulation_points(0.0, 8) == [(0.0, 0.0)]
    with pytest.raises(ValueError, match="non-negative"):
        make_modulation_points(-1.0, 8)
    with pytest.raises(ValueError, match="must be an integer"):
        make_modulation_points(1.0, 8.5)  # type: ignore[arg-type]


def test_pwfs_calibration_preserves_exterior_nan_but_rejects_interior_nan():
    x, y, pupil, phase, n_pupil, separation = _pwfs_case(n_fft=96, n_pupil=21, separation=24)
    exterior_nan_mode = np.where(pupil, x, np.nan)

    matrix, names, reference = calibrate_pwfs_interaction_matrix(
        {"tip": exterior_nan_mode},
        pupil,
        x,
        y,
        calibration_amplitude=1.0e-3,
        n_pupil=n_pupil,
        separation=separation,
    )

    assert names == ["tip"]
    assert matrix.shape == (reference.size, 1)
    assert np.all(np.isfinite(matrix))

    invalid = exterior_nan_mode.copy()
    inside_y, inside_x = np.argwhere(pupil)[0]
    invalid[inside_y, inside_x] = np.nan
    with pytest.raises(ValueError, match="finite inside the pupil"):
        calibrate_pwfs_interaction_matrix(
            {"bad": invalid},
            pupil,
            x,
            y,
            calibration_amplitude=1.0e-3,
            n_pupil=n_pupil,
            separation=separation,
        )
