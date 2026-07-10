import numpy as np
import pytest

from phase_screen import (
    fourier_phase_screen,
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


def test_invalid_physical_inputs_raise_error():
    with pytest.raises(ValueError, match="seeing_arcsec"):
        r0_from_seeing(0.0)
    with pytest.raises(ValueError, match="wavelength"):
        phase_to_opd(np.array([1.0]), 0.0)
