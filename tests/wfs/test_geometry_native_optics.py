"""Focused AO-REF-005 geometry and native-optics contracts."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace

import numpy as np
import pytest

from shwfs_ao.backends.native.shwfs import (
    NativeShackHartmannError,
    NativeShackHartmannOptics,
    lenslet_spot_from_phase,
)
from shwfs_ao.core.protocols import ShackHartmannOpticsBackend
from shwfs_ao.core.geometry import GeometryError, PupilGeometry
from shwfs_ao.core.types import SpotIntensityResult
from shwfs_ao.legacy.shwfs_detector import (
    lenslet_spot_from_phase as legacy_lenslet_spot_from_phase,
)
from shwfs_ao.wfs.shack_hartmann.geometry import (
    ShackHartmannGeometry,
    ShackHartmannGeometryError,
    ShwfsGeometryConfig,
    build_shack_hartmann_geometry,
    lenslet_indices_from_id,
)
from shwfs_ao.wfs.shack_hartmann.optics import (
    ShackHartmannOpticsError,
    make_detector_plane_sampling,
    validate_spot_intensity_result,
)


def _geometry() -> ShackHartmannGeometry:
    return build_shack_hartmann_geometry(
        telescope_diameter_m=1.0,
        pupil_shape=(32, 32),
        n_lenslets_across=4,
        min_fill_fraction=0.35,
    )


def _backend(
    *,
    detector_window_px: int | None = 12,
    wavelength_m: float = 700.0e-9,
) -> NativeShackHartmannOptics:
    return NativeShackHartmannOptics(
        _geometry(),
        wavelength_m,
        pad_factor=4,
        detector_window_px=detector_window_px,
    )


def _centroids(result: SpotIntensityResult) -> np.ndarray:
    return np.asarray(
        [
            (
                np.sum(spot * x_axis[np.newaxis, :]),
                np.sum(spot * y_axis[:, np.newaxis]),
            )
            for spot, x_axis, y_axis in zip(
                result.unit_sum_spots,
                result.x_px,
                result.y_px,
            )
        ],
        dtype=float,
    )


def test_config_and_geometry_have_frozen_exact_field_order() -> None:
    assert tuple(field.name for field in fields(ShwfsGeometryConfig)) == (
        "telescope_diameter_m",
        "n_pupil_pixels",
        "n_lenslets",
        "min_fill_fraction",
        "pad_factor",
        "detector_window_px",
        "threshold_fraction",
        "subtract_minimum",
        "central_obstruction_ratio",
        "spider_width_m",
        "wfs_wavelength_m",
        "source_class",
        "source_note",
    )
    assert tuple(field.name for field in fields(ShackHartmannGeometry)) == (
        "telescope_diameter_m",
        "pupil_shape",
        "n_lenslets_across",
        "pupil_mask",
        "x_m",
        "y_m",
        "subaperture_masks",
        "subaperture_centers_m",
        "subaperture_ids",
    )
    geometry = _geometry()
    with pytest.raises(FrozenInstanceError):
        geometry.n_lenslets_across = 5  # type: ignore[misc]
    for array in (
        geometry.pupil_mask,
        geometry.x_m,
        geometry.y_m,
        geometry.subaperture_centers_m,
        *geometry.subaperture_masks,
    ):
        assert not array.flags.writeable
        with pytest.raises(ValueError):
            array.setflags(write=True)


def test_geometry_ids_encode_physical_indices_in_frozen_legacy_order() -> None:
    geometry = _geometry()
    indices = tuple(
        lenslet_indices_from_id(
            identifier,
            n_lenslets_across=geometry.n_lenslets_across,
        )
        for identifier in geometry.subaperture_ids
    )
    assert indices == tuple(sorted(indices, key=lambda item: (item[1], item[0])))
    assert geometry.subaperture_ids[:6] == (
        "lenslet-r0001-c0000",
        "lenslet-r0002-c0000",
        "lenslet-r0000-c0001",
        "lenslet-r0001-c0001",
        "lenslet-r0002-c0001",
        "lenslet-r0003-c0001",
    )
    assert geometry.row_ids[:4] == (
        "lenslet-r0001-c0000:x",
        "lenslet-r0001-c0000:y",
        "lenslet-r0002-c0000:x",
        "lenslet-r0002-c0000:y",
    )
    repeated = _geometry()
    assert repeated.subaperture_ids == geometry.subaperture_ids
    assert repeated.geometry_hash == geometry.geometry_hash


def test_geometry_filters_obstruction_spiders_and_lenslet_fill() -> None:
    clear = build_shack_hartmann_geometry(
        telescope_diameter_m=2.0,
        pupil_shape=(64, 64),
        n_lenslets_across=8,
        min_fill_fraction=0.5,
    )
    obstructed = build_shack_hartmann_geometry(
        telescope_diameter_m=2.0,
        pupil_shape=(64, 64),
        n_lenslets_across=8,
        min_fill_fraction=0.5,
        central_obstruction_ratio=0.3,
        spider_width_m=0.08,
    )
    assert np.count_nonzero(obstructed.pupil_mask) < np.count_nonzero(clear.pupil_mask)
    assert obstructed.geometry_hash != clear.geometry_hash
    assert all(
        np.all(~mask | obstructed.pupil_mask)
        for mask in obstructed.subaperture_masks
    )
    assert len(obstructed.subaperture_ids) <= len(clear.subaperture_ids)


def test_pupil_geometry_rejects_nonuniform_cartesian_sampling() -> None:
    x_axis = np.asarray([-0.5, -0.2, 0.1, 0.5])
    y_axis = np.linspace(-0.5, 0.5, 4)
    x_m, y_m = np.meshgrid(x_axis, y_axis, indexing="xy")
    with pytest.raises(GeometryError, match="uniformly spaced"):
        PupilGeometry(
            telescope_diameter_m=1.0,
            pupil_shape=(4, 4),
            pupil_mask=np.hypot(x_m, y_m) <= 0.5,
            x_m=x_m,
            y_m=y_m,
        )


def test_geometry_rejects_reordered_or_mislabeled_physical_masks() -> None:
    geometry = _geometry()
    with pytest.raises(ShackHartmannGeometryError, match="canonical physical"):
        replace(
            geometry,
            subaperture_masks=tuple(reversed(geometry.subaperture_masks)),
            subaperture_centers_m=geometry.subaperture_centers_m[::-1],
            subaperture_ids=tuple(reversed(geometry.subaperture_ids)),
        )
    identifiers = list(geometry.subaperture_ids)
    identifiers[0] = identifiers[1]
    with pytest.raises(ShackHartmannGeometryError, match="duplicate"):
        replace(geometry, subaperture_ids=tuple(identifiers))


def test_low_level_native_fft_is_numerically_frozen_to_legacy_kernel() -> None:
    geometry = _geometry()
    phase_rad = np.where(
        geometry.pupil_mask,
        0.7 * geometry.x_m - 0.35 * geometry.y_m,
        np.nan,
    )
    mask = geometry.subaperture_masks[4]
    kwargs = {
        "pad_factor": 3,
        "remove_local_piston": True,
        "sampling_shape": (8, 8),
    }
    expected = legacy_lenslet_spot_from_phase(phase_rad, mask, **kwargs)
    actual = lenslet_spot_from_phase(phase_rad, mask, **kwargs)
    np.testing.assert_array_equal(actual, expected)


def test_native_backend_emits_one_contract_spot_per_exact_geometry_id() -> None:
    backend = _backend()
    assert isinstance(backend, ShackHartmannOpticsBackend)
    residual_opd_m = np.where(backend.geometry.pupil_mask, 0.0, np.nan)
    result = backend.spot_intensities(residual_opd_m)

    assert result.subaperture_ids == backend.geometry.subaperture_ids
    assert len(result.unit_sum_spots) == backend.geometry.n_subapertures
    assert result.sampling is backend.sampling
    assert result.sampling.window_shape_px == (12, 12)
    assert result.sampling.reference_pixel_xy == (6.0, 6.0)
    for spot in result.unit_sum_spots:
        assert spot.shape == (12, 12)
        assert np.all(np.isfinite(spot))
        assert np.all(spot >= 0.0)
        assert np.sum(spot) == pytest.approx(1.0, abs=1.0e-12)
    assert np.all((result.relative_throughput > 0.0) & (result.relative_throughput <= 1.0))
    assert np.all((backend.pupil_relative_throughput > 0.0) & (backend.pupil_relative_throughput <= 1.0))
    assert np.any(backend.pupil_relative_throughput < 1.0)
    assert backend.geometry_hash == backend.geometry.geometry_hash
    assert backend.wfs_wavelength_m == 700.0e-9


def test_relative_throughput_is_window_capture_not_spot_normalization() -> None:
    cropped_backend = _backend(detector_window_px=8)
    full_backend = _backend(detector_window_px=None)
    opd_m = np.where(cropped_backend.geometry.pupil_mask, 0.0, np.nan)
    cropped = cropped_backend.spot_intensities(opd_m)
    full = full_backend.spot_intensities(opd_m)

    assert np.all(cropped.relative_throughput < 1.0)
    np.testing.assert_allclose(full.relative_throughput, 1.0, atol=1.0e-14, rtol=0.0)
    np.testing.assert_allclose(
        [np.sum(spot) for spot in cropped.unit_sum_spots],
        1.0,
        atol=1.0e-12,
        rtol=0.0,
    )


def test_explicit_opd_wavelength_and_positive_tilts_have_detector_axis_sign() -> None:
    backend = _backend(detector_window_px=None)
    geometry = backend.geometry
    wavelength_m = backend.wfs_wavelength_m
    lenslet_pitch_m = geometry.telescope_diameter_m / geometry.n_lenslets_across
    slope = 0.2 * wavelength_m / lenslet_pitch_m
    zero_opd = np.where(geometry.pupil_mask, 0.0, np.nan)
    x_tilt_opd = np.where(geometry.pupil_mask, slope * geometry.x_m, np.nan)
    y_tilt_opd = np.where(geometry.pupil_mask, slope * geometry.y_m, np.nan)

    reference = _centroids(backend.spot_intensities(zero_opd))
    x_shift = _centroids(backend.spot_intensities(x_tilt_opd)) - reference
    y_shift = _centroids(backend.spot_intensities(y_tilt_opd)) - reference
    assert np.median(x_shift[:, 0]) > 0.25
    assert np.median(y_shift[:, 1]) > 0.25
    assert abs(np.median(x_shift[:, 1])) < 1.0e-10
    assert abs(np.median(y_shift[:, 0])) < 1.0e-10

    other_wavelength = NativeShackHartmannOptics(
        geometry,
        2.0 * wavelength_m,
        pad_factor=backend.pad_factor,
        detector_window_px=None,
    )
    weaker_x_shift = (
        _centroids(other_wavelength.spot_intensities(x_tilt_opd)) - reference
    )
    assert np.median(weaker_x_shift[:, 0]) < np.median(x_shift[:, 0])
    assert other_wavelength.config_hash != backend.config_hash


def test_backend_rejects_wrong_shape_and_nonfinite_illuminated_opd() -> None:
    backend = _backend()
    with pytest.raises(NativeShackHartmannError, match="shape"):
        backend.spot_intensities(np.zeros((10, 10)))
    invalid = np.zeros(backend.geometry.pupil_shape)
    invalid[tuple(np.argwhere(backend.geometry.pupil_mask)[0])] = np.nan
    with pytest.raises(NativeShackHartmannError, match="finite.*pupil"):
        backend.spot_intensities(invalid)


def test_optics_boundary_rejects_missing_duplicate_reordered_and_sampling() -> None:
    backend = _backend()
    geometry = backend.geometry
    result = backend.spot_intensities(np.where(geometry.pupil_mask, 0.0, np.nan))
    assert validate_spot_intensity_result(result, geometry) is result

    missing = SpotIntensityResult(
        unit_sum_spots=result.unit_sum_spots[:-1],
        subaperture_ids=result.subaperture_ids[:-1],
        relative_throughput=result.relative_throughput[:-1],
        x_px=result.x_px[:-1],
        y_px=result.y_px[:-1],
        sampling=result.sampling,
        normalization="unit_sum_per_subaperture",
    )
    with pytest.raises(ShackHartmannOpticsError, match="missing"):
        validate_spot_intensity_result(missing, geometry)

    reordered = SpotIntensityResult(
        unit_sum_spots=tuple(reversed(result.unit_sum_spots)),
        subaperture_ids=tuple(reversed(result.subaperture_ids)),
        relative_throughput=result.relative_throughput[::-1],
        x_px=tuple(reversed(result.x_px)),
        y_px=tuple(reversed(result.y_px)),
        sampling=result.sampling,
        normalization="unit_sum_per_subaperture",
    )
    with pytest.raises(ShackHartmannOpticsError, match="reordered"):
        validate_spot_intensity_result(reordered, geometry)

    # SpotIntensityResult itself rejects duplicates.  This deliberately
    # uninitialized instance proves the boundary checks IDs before payload use.
    duplicate = object.__new__(SpotIntensityResult)
    object.__setattr__(
        duplicate,
        "subaperture_ids",
        (geometry.subaperture_ids[0], geometry.subaperture_ids[0]),
    )
    with pytest.raises(ShackHartmannOpticsError, match="duplicate"):
        validate_spot_intensity_result(duplicate, geometry)

    other_sampling = make_detector_plane_sampling(
        window_shape_px=result.sampling.window_shape_px,
        pixel_scale_rad=(
            2.0 * result.sampling.pixel_scale_rad[0],
            result.sampling.pixel_scale_rad[1],
        ),
        reference_pixel_xy=result.sampling.reference_pixel_xy,
    )
    with pytest.raises(ShackHartmannOpticsError, match="sampling"):
        validate_spot_intensity_result(result, geometry, sampling=other_sampling)
