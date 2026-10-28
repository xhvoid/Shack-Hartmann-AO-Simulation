import numpy as np
import pytest

from zernike import zernike_radial


@pytest.mark.parametrize(
    ("n", "m"),
    [
        (20, 0),
        (40, 0),
        (60, 10),
        (80, 20),
        (100, 0),
    ],
)
def test_high_order_zernike_radial_is_finite_and_unity_at_pupil_edge(n, m):
    rho = np.linspace(0.0, 1.0, 2001)

    radial = zernike_radial(n, m, rho)

    assert np.all(np.isfinite(radial))
    assert radial[-1] == pytest.approx(1.0, abs=2.0e-13)


def test_high_order_radial_zernikes_preserve_continuous_orthogonality():
    rho = np.linspace(0.0, 1.0, 40001)
    radial_40 = zernike_radial(40, 0, rho)
    radial_42 = zernike_radial(42, 0, rho)

    norm_40 = np.trapezoid(radial_40**2 * rho, rho)
    cross = np.trapezoid(radial_40 * radial_42 * rho, rho)

    assert norm_40 == pytest.approx(1.0 / (2.0 * 41.0), rel=2.0e-5)
    assert abs(cross) < 3.0e-7
