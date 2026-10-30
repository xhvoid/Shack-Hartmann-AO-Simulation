"""Known phase/OPD anchors and unit round trips."""
import numpy as np
import pytest
from shwfs_ao.core.wavefront import phase_to_opd, opd_to_phase


def test_phase_to_opd_to_phase_round_trip_preserves_shape_dtype_and_nan() -> None:
    phase_rad = np.array([[0.0, 0.5], [-1.2, np.nan]], dtype=np.float32)
    original = phase_rad.copy()

    opd_m = phase_to_opd(phase_rad, wavelength_m=700.0e-9)
    recovered = opd_to_phase(opd_m, wavelength_m=700.0e-9)

    assert isinstance(opd_m, np.ndarray)
    assert isinstance(recovered, np.ndarray)
    assert opd_m.shape == recovered.shape == phase_rad.shape
    assert opd_m.dtype == recovered.dtype == np.dtype(float)
    assert not np.shares_memory(opd_m, phase_rad)
    assert np.allclose(recovered, phase_rad, equal_nan=True)
    assert np.array_equal(phase_rad, original, equal_nan=True)


def test_opd_to_phase_to_opd_round_trip_preserves_shape_dtype_and_nan() -> None:
    opd_m = np.array([[0.0, 80.0e-9], [-135.0e-9, np.nan]], dtype=np.float32)
    original = opd_m.copy()

    phase_rad = opd_to_phase(opd_m, wavelength_m=1.65e-6)
    recovered = phase_to_opd(phase_rad, wavelength_m=1.65e-6)

    assert isinstance(phase_rad, np.ndarray)
    assert isinstance(recovered, np.ndarray)
    assert phase_rad.shape == recovered.shape == opd_m.shape
    assert phase_rad.dtype == recovered.dtype == np.dtype(float)
    assert not np.shares_memory(phase_rad, opd_m)
    assert np.allclose(recovered, opd_m, equal_nan=True)
    assert np.array_equal(opd_m, original, equal_nan=True)


def test_converters_match_the_frozen_phase_opd_relationship() -> None:
    wavelength_m = 500.0e-9
    phase_rad = np.array([-2.0 * np.pi, -np.pi, 0.0, np.pi, 2.0 * np.pi, np.nan])
    expected_opd_m = np.array(
        [-wavelength_m, -0.5 * wavelength_m, 0.0, 0.5 * wavelength_m, wavelength_m, np.nan]
    )

    actual_opd_m = phase_to_opd(phase_rad, wavelength_m)
    actual_phase_rad = opd_to_phase(expected_opd_m, wavelength_m)

    assert actual_opd_m == pytest.approx(expected_opd_m, nan_ok=True)
    assert actual_phase_rad == pytest.approx(phase_rad, nan_ok=True)
