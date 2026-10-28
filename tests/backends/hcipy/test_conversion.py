"""Round-trip and validation tests for the HCIPy conversion layer.

Every test in this module requires the optional HCIPy dependency and carries
the ``hcipy`` marker so native CI selections never execute it.  The module is
also part of the portable wheel-smoke bundle, so it must not import anything
from the repository source tree besides the installed package.
"""

from __future__ import annotations

import numpy as np
import pytest


hcipy = pytest.importorskip("hcipy")

from shwfs_ao.backends.hcipy import hcipy_version
from shwfs_ao.backends.hcipy import conversion as cv
from shwfs_ao.core.geometry import build_pupil_geometry


pytestmark = pytest.mark.hcipy


@pytest.fixture()
def geometry():
    return build_pupil_geometry(telescope_diameter_m=2.0, pupil_shape=(6, 5))


@pytest.fixture()
def grid(geometry):
    return cv.hcipy_grid_from_geometry(geometry)


@pytest.fixture()
def masked_values(geometry):
    rng = np.random.default_rng(742)
    values = rng.normal(size=geometry.pupil_shape)
    return np.where(geometry.pupil_mask, values, np.nan)


def test_hcipy_version_is_reported():
    version = hcipy_version()
    assert isinstance(version, str) and version
    assert version.split(".")[0] == "0"


class TestGridConversion:
    def test_grid_matches_repository_coordinates(self, geometry, grid):
        rows, columns = geometry.pupil_shape
        assert [int(v) for v in grid.dims] == [columns, rows]
        dx_m, dy_m = geometry.pixel_spacing_xy_m
        assert np.allclose(grid.delta, [dx_m, dy_m], rtol=0.0, atol=1.0e-15)
        assert np.allclose(
            grid.zero,
            [geometry.x_m[0, 0], geometry.y_m[0, 0]],
            rtol=0.0,
            atol=0.0,
        )
        assert grid.is_regular and grid.is_separated

    def test_grid_coordinate_round_trip_is_exact(self, geometry, grid):
        x_m, y_m = cv.coordinates_from_hcipy_grid(grid)
        assert type(x_m) is np.ndarray and type(y_m) is np.ndarray
        assert np.allclose(x_m, geometry.x_m, rtol=0.0, atol=1.0e-15)
        assert np.allclose(y_m, geometry.y_m, rtol=0.0, atol=1.0e-15)

    def test_grid_points_use_x_fastest_ordering(self, geometry, grid):
        x_m = np.asarray(grid.x).reshape(geometry.pupil_shape)
        y_m = np.asarray(grid.y).reshape(geometry.pupil_shape)
        assert np.allclose(x_m, geometry.x_m, rtol=0.0, atol=1.0e-15)
        assert np.allclose(y_m, geometry.y_m, rtol=0.0, atol=1.0e-15)

    def test_non_uniform_column_spacing_is_rejected(self, geometry):
        x_bad = np.array(geometry.x_m, copy=True)
        x_bad[:, 1] += 1.0e-3
        with pytest.raises(cv.HcipyConversionError, match="uniformly spaced"):
            cv.hcipy_grid_from_coordinates(x_bad, geometry.y_m)

    def test_x_varying_along_rows_is_rejected(self, geometry):
        x_bad = np.array(geometry.x_m, copy=True)
        x_bad[0, 1] += 1.0e-3
        with pytest.raises(cv.HcipyConversionError, match="vary only along columns"):
            cv.hcipy_grid_from_coordinates(x_bad, geometry.y_m)

    def test_non_increasing_axis_is_rejected(self, geometry):
        x_bad = np.array(geometry.x_m, copy=True)[:, ::-1]
        with pytest.raises(cv.HcipyConversionError, match="strictly increasing"):
            cv.hcipy_grid_from_coordinates(x_bad, geometry.y_m)

    def test_shape_mismatch_is_rejected(self, geometry):
        with pytest.raises(cv.HcipyConversionError, match="does not match"):
            cv.hcipy_grid_from_coordinates(geometry.x_m, geometry.y_m[:-1, :])

    def test_geometry_type_is_required(self):
        with pytest.raises(cv.HcipyConversionError, match="PupilGeometry"):
            cv.hcipy_grid_from_geometry(object())

    def test_irregular_grid_back_conversion_is_rejected(self):
        points = np.array([[0.0, 0.0], [1.0, 0.0], [0.3, 1.0], [1.5, 1.0]])
        irregular = hcipy.CartesianGrid(hcipy.UnstructuredCoords(points.T))
        with pytest.raises(cv.HcipyConversionError, match="regular and separated"):
            cv.coordinates_from_hcipy_grid(irregular)


class TestFieldConversion:
    def test_round_trip_preserves_values_mask_and_fill(
        self,
        geometry,
        grid,
        masked_values,
    ):
        mask = geometry.pupil_mask
        field = cv.field_from_masked_array(masked_values, mask, grid)
        shaped = np.asarray(field).reshape(mask.shape)
        assert np.array_equal(shaped[mask], masked_values[mask])
        assert np.all(shaped[~mask] == 0.0)

        default_back = cv.masked_array_from_field(field, mask)
        assert type(default_back) is np.ndarray
        assert np.array_equal(default_back[mask], masked_values[mask])
        assert np.all(np.isnan(default_back[~mask]))

        zero_back = cv.masked_array_from_field(field, mask, outside_fill=0.0)
        assert np.all(zero_back[~mask] == 0.0)
        assert np.array_equal(zero_back[mask], masked_values[mask])

    def test_flattening_order_is_c_order_row_major(
        self,
        geometry,
        grid,
        masked_values,
    ):
        mask = geometry.pupil_mask
        rows, columns = mask.shape
        field = cv.field_from_masked_array(masked_values, mask, grid)
        filled = np.where(mask, masked_values, 0.0)
        assert np.array_equal(np.asarray(field), filled.ravel(order="C"))
        for row, column in ((0, 0), (1, 3), (rows - 1, columns - 1)):
            assert field[row * columns + column] == filled[row, column]

    def test_interior_nan_is_rejected(self, geometry, grid, masked_values):
        mask = geometry.pupil_mask
        bad = np.array(masked_values, copy=True)
        interior = np.argwhere(mask)[0]
        bad[interior[0], interior[1]] = np.nan
        with pytest.raises(cv.HcipyConversionError, match="finite"):
            cv.field_from_masked_array(bad, mask, grid)

    def test_interior_inf_is_rejected(self, geometry, grid, masked_values):
        mask = geometry.pupil_mask
        bad = np.array(masked_values, copy=True)
        interior = np.argwhere(mask)[0]
        bad[interior[0], interior[1]] = np.inf
        with pytest.raises(cv.HcipyConversionError, match="finite"):
            cv.field_from_masked_array(bad, mask, grid)

    def test_grid_and_mask_shape_mismatch_is_rejected(self, geometry, grid):
        small_mask = geometry.pupil_mask[:-1, :]
        small_values = np.where(small_mask, 1.0, np.nan)
        with pytest.raises(cv.HcipyConversionError, match="does not match"):
            cv.field_from_masked_array(small_values, small_mask, grid)

    def test_complex_field_back_conversion_is_rejected(self, geometry, grid):
        complex_field = hcipy.Field(
            np.ones(int(np.prod(geometry.pupil_shape)), dtype=complex),
            grid,
        )
        with pytest.raises(cv.HcipyConversionError, match="real"):
            cv.masked_array_from_field(complex_field, geometry.pupil_mask)

    def test_non_field_back_conversion_is_rejected(self, geometry):
        with pytest.raises(cv.HcipyConversionError, match="hcipy.Field"):
            cv.masked_array_from_field(
                np.ones(geometry.pupil_shape),
                geometry.pupil_mask,
            )


class TestApertureConversion:
    def test_aperture_round_trip(self, geometry, grid):
        mask = geometry.pupil_mask
        aperture = cv.aperture_field_from_mask(mask, grid)
        values = np.asarray(aperture)
        assert set(np.unique(values)) <= {0.0, 1.0}
        recovered = cv.mask_from_aperture_field(aperture)
        assert type(recovered) is np.ndarray and recovered.dtype == np.dtype(bool)
        assert np.array_equal(recovered, mask)

    def test_threshold_selects_partial_illumination(self, geometry, grid):
        mask = geometry.pupil_mask
        aperture = cv.aperture_field_from_mask(mask, grid)
        graded = hcipy.Field(np.asarray(aperture) * 0.4, grid)
        assert not np.any(cv.mask_from_aperture_field(graded))
        assert np.array_equal(
            cv.mask_from_aperture_field(graded, threshold=0.25),
            mask,
        )

    def test_invalid_threshold_is_rejected(self, geometry, grid):
        aperture = cv.aperture_field_from_mask(geometry.pupil_mask, grid)
        for threshold in (0.0, 1.0, np.nan, True):
            with pytest.raises(cv.HcipyConversionError, match="threshold"):
                cv.mask_from_aperture_field(aperture, threshold=threshold)

    def test_non_finite_aperture_is_rejected(self, geometry, grid):
        values = np.ones(int(np.prod(geometry.pupil_shape)), dtype=float)
        values[0] = np.nan
        with pytest.raises(cv.HcipyConversionError, match="finite"):
            cv.mask_from_aperture_field(hcipy.Field(values, grid))


class TestWavefrontConversion:
    WAVELENGTH_M = 700.0e-9

    @pytest.fixture()
    def opd_m(self, geometry):
        rng = np.random.default_rng(4242)
        opd = 40.0e-9 * rng.normal(size=geometry.pupil_shape)
        return np.where(geometry.pupil_mask, opd, np.nan)

    def test_wavelength_is_explicit_and_preserved(self, geometry, grid, opd_m):
        wavefront = cv.wavefront_from_opd(
            opd_m,
            geometry.pupil_mask,
            grid,
            wavelength_m=self.WAVELENGTH_M,
        )
        assert wavefront.wavelength == pytest.approx(self.WAVELENGTH_M, rel=0.0)

    def test_phase_and_amplitude_conventions(self, geometry, grid, opd_m):
        mask = geometry.pupil_mask
        wavefront = cv.wavefront_from_opd(
            opd_m,
            mask,
            grid,
            wavelength_m=self.WAVELENGTH_M,
        )
        electric_field = np.asarray(wavefront.electric_field).reshape(mask.shape)
        assert np.all(electric_field[~mask] == 0.0)
        expected_phase = 2.0 * np.pi * opd_m[mask] / self.WAVELENGTH_M
        assert np.allclose(
            np.angle(electric_field[mask]),
            expected_phase,
            rtol=0.0,
            atol=1.0e-12,
        )
        assert np.allclose(
            np.abs(electric_field[mask]),
            1.0,
            rtol=0.0,
            atol=1.0e-12,
        )

    def test_small_signal_opd_round_trip(self, geometry, grid, opd_m):
        mask = geometry.pupil_mask
        wavefront = cv.wavefront_from_opd(
            opd_m,
            mask,
            grid,
            wavelength_m=self.WAVELENGTH_M,
        )
        recovered = cv.opd_m_from_wavefront(wavefront, mask)
        assert type(recovered) is np.ndarray
        assert np.all(np.isnan(recovered[~mask]))
        assert np.allclose(
            recovered[mask],
            opd_m[mask],
            rtol=0.0,
            atol=1.0e-18,
        )

    def test_wavelength_must_be_positive_and_finite(self, geometry, grid, opd_m):
        for wavelength in (0.0, -1.0e-6, np.nan, np.inf):
            with pytest.raises(cv.HcipyConversionError, match="wavelength_m"):
                cv.wavefront_from_opd(
                    opd_m,
                    geometry.pupil_mask,
                    grid,
                    wavelength_m=wavelength,
                )

    def test_interior_nan_opd_is_rejected(self, geometry, grid, opd_m):
        mask = geometry.pupil_mask
        bad = np.array(opd_m, copy=True)
        interior = np.argwhere(mask)[0]
        bad[interior[0], interior[1]] = np.nan
        with pytest.raises(cv.HcipyConversionError, match="finite"):
            cv.wavefront_from_opd(
                bad,
                mask,
                grid,
                wavelength_m=self.WAVELENGTH_M,
            )

    def test_non_wavefront_is_rejected(self, geometry):
        with pytest.raises(cv.HcipyConversionError, match="hcipy.Wavefront"):
            cv.opd_m_from_wavefront(object(), geometry.pupil_mask)
