import numpy as np
import pytest

from ao_closed_loop import shifted_atmosphere
from phase_screen import (
    fourier_phase_screen,
    frozen_flow_shift,
    frozen_flow_shift_physical,
    opd_to_phase,
    phase_to_opd,
    r0_from_seeing,
    rms,
    scale_r0_with_wavelength,
)


def test_r0_scales_with_wavelength_to_six_fifths_power():
    r0_ref = r0_from_seeing(0.8, wavelength=500e-9)
    r0_h = scale_r0_with_wavelength(r0_ref, wavelength=1.0e-6, wavelength_ref=500e-9)

    assert r0_h == pytest.approx(r0_ref * 2.0 ** (6.0 / 5.0))


def test_phase_opd_roundtrip_preserves_values():
    phase = np.array([[0.0, 0.5], [-1.2, np.nan]])
    wavelength = 700e-9

    opd = phase_to_opd(phase, wavelength)
    recovered = opd_to_phase(opd, wavelength)

    assert np.allclose(recovered, phase, equal_nan=True)


def test_fourier_phase_screen_reaches_target_rms():
    phase, _, _, mask = fourier_phase_screen(
        N=64,
        delta=0.02,
        r0=0.15,
        diameter=1.0,
        seed=4,
        target_rms_rad=1.25,
        normalize_rms=True,
    )

    assert phase.shape == (64, 64)
    assert rms(phase, mask) == pytest.approx(1.25, rel=1e-6)
    assert np.all(np.isnan(phase[~mask]))


def test_fourier_phase_screen_can_return_a_full_finite_frozen_flow_screen():
    phase, _, _, mask = fourier_phase_screen(
        N=64,
        delta=0.02,
        r0=0.15,
        diameter=1.0,
        seed=4,
        target_rms_rad=1.25,
        normalize_rms=True,
        mask_output=False,
    )

    assert np.all(np.isfinite(phase))
    assert rms(phase, mask) == pytest.approx(1.25, rel=1.0e-6)
    assert np.mean(phase[mask]) == pytest.approx(0.0, abs=1.0e-12)


def test_frozen_flow_requires_full_finite_input_and_never_invents_exterior_phase():
    masked, _, _, mask = fourier_phase_screen(
        N=32,
        delta=0.04,
        r0=0.15,
        diameter=1.0,
        seed=2,
    )

    with pytest.raises(ValueError, match="finite everywhere"):
        frozen_flow_shift(masked, shift_x_pix=1, mask=mask)


def test_periodic_frozen_flow_preserves_full_screen_statistics_and_wraparound():
    full = np.arange(36, dtype=float).reshape(6, 6)
    shifted = frozen_flow_shift(full, shift_x_pix=2, shift_y_pix=-1)

    expected = np.roll(np.roll(full, -1, axis=0), 2, axis=1)
    assert np.array_equal(shifted, expected)
    assert np.mean(shifted) == pytest.approx(np.mean(full))
    assert np.std(shifted) == pytest.approx(np.std(full))
    assert np.array_equal(frozen_flow_shift(full, shift_x_pix=full.shape[1]), full)


def test_frozen_flow_masks_and_removes_piston_only_after_translation():
    full = np.ones((32, 32), dtype=float)
    yy, xx = np.indices(full.shape)
    mask = (xx - 15.5) ** 2 + (yy - 15.5) ** 2 <= 12.0**2

    shifted = frozen_flow_shift(full, shift_x_pix=5, shift_y_pix=-3, mask=mask)

    assert rms(shifted, mask) == pytest.approx(0.0, abs=1.0e-14)
    assert np.all(np.isnan(shifted[~mask]))


def test_physical_frozen_flow_matches_the_equivalent_integer_pixel_shift():
    full = np.arange(64, dtype=float).reshape(8, 8)
    by_pixels = frozen_flow_shift(full, shift_x_pix=2, shift_y_pix=-1)
    by_physics = frozen_flow_shift_physical(
        full,
        vx=2.0,
        vy=-1.0,
        dt=0.5,
        delta=0.5,
    )

    assert np.array_equal(by_physics, by_pixels)


def test_legacy_closed_loop_shift_uses_the_same_full_screen_contract():
    full = np.arange(64, dtype=float).reshape(8, 8)
    mask = np.zeros_like(full, dtype=bool)
    mask[1:7, 1:7] = True

    expected = frozen_flow_shift(full, shift_x_pix=1, shift_y_pix=2, mask=mask)
    actual = shifted_atmosphere(full, mask, shift_x_pix=1, shift_y_pix=2)

    assert np.allclose(actual, expected, equal_nan=True)


def test_invalid_physical_inputs_raise_error():
    with pytest.raises(ValueError, match="seeing_arcsec"):
        r0_from_seeing(0.0)
    with pytest.raises(ValueError, match="wavelength"):
        phase_to_opd(np.array([1.0]), 0.0)
