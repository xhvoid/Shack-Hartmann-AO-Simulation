import numpy as np
import pytest

from psf_tools import (
    compute_psf_from_phase,
    marechal_strehl,
    phase_for_science_wavelength,
    strehl_ratio,
)


def _circular_mask(n=64):
    coords = np.linspace(-1.0, 1.0, n)
    x, y = np.meshgrid(coords, coords)
    return x, y, x**2 + y**2 <= 1.0


def test_psf_is_normalized():
    x, _, mask = _circular_mask()
    phase = 0.2 * x

    psf = compute_psf_from_phase(phase, mask, pad_factor=2)

    assert psf.shape == (128, 128)
    assert np.isclose(psf.sum(), 1.0)
    assert np.all(psf >= 0.0)


def test_zero_phase_strehl_is_one():
    _, _, mask = _circular_mask()
    phase = np.zeros(mask.shape)

    assert strehl_ratio(phase, mask, pad_factor=2) == pytest.approx(1.0)


def test_nonfinite_phase_is_allowed_only_outside_the_pupil():
    _, _, mask = _circular_mask()
    exterior_nan = np.where(mask, 0.0, np.nan)
    invalid_inside = exterior_nan.copy()
    inside_y, inside_x = np.argwhere(mask)[0]
    invalid_inside[inside_y, inside_x] = np.nan

    psf = compute_psf_from_phase(exterior_nan, mask, pad_factor=2)

    assert np.isclose(np.sum(psf), 1.0)
    with pytest.raises(ValueError, match="finite inside"):
        compute_psf_from_phase(invalid_inside, mask, pad_factor=2)
    with pytest.raises(ValueError, match="finite inside"):
        marechal_strehl(invalid_inside, mask)


def test_marechal_strehl_decreases_with_phase_rms():
    x, _, mask = _circular_mask()

    low_rms = marechal_strehl(0.1 * x, mask)
    high_rms = marechal_strehl(0.5 * x, mask)

    assert 0.0 < high_rms < low_rms < 1.0


def test_phase_for_science_wavelength_scales_as_inverse_lambda():
    opd = np.array([0.0, 100e-9, -50e-9])

    phase_1um = phase_for_science_wavelength(opd, 1.0e-6)
    phase_2um = phase_for_science_wavelength(opd, 2.0e-6)

    assert np.allclose(phase_1um, 2.0 * phase_2um)


def test_phase_for_science_wavelength_requires_positive_wavelength():
    with pytest.raises(ValueError, match="positive"):
        phase_for_science_wavelength(np.array([1.0]), 0.0)
