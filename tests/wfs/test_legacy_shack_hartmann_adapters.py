"""AO-REF-005 legacy SH-WFS delegation and coordinate adapters."""

from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path

import numpy as np
import pytest

from shwfs_ao.backends.native import shwfs as native_shwfs
from shwfs_ao.legacy import reconstruction, shwfs_detector, synthetic_instrument_data
from shwfs_ao.wfs.shack_hartmann.geometry import ShwfsGeometryConfig


ROOT = Path(__file__).resolve().parents[2]


def _geometry_config() -> ShwfsGeometryConfig:
    return ShwfsGeometryConfig(
        telescope_diameter_m=1.0,
        n_pupil_pixels=32,
        n_lenslets=4,
        min_fill_fraction=0.35,
        pad_factor=3,
        detector_window_px=12,
    )


def test_legacy_fft_crop_and_config_names_are_canonical_objects() -> None:
    assert shwfs_detector.nominal_lenslet_sampling_shape is (
        native_shwfs.nominal_lenslet_sampling_shape
    )
    assert shwfs_detector.lenslet_spot_from_phase is (
        native_shwfs.lenslet_spot_from_phase
    )
    assert shwfs_detector.crop_center is native_shwfs.crop_center
    assert synthetic_instrument_data.ShwfsGeometryConfig is ShwfsGeometryConfig
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


def test_legacy_modules_no_longer_own_shwfs_physics_kernels() -> None:
    shwfs_path = ROOT / "src/shwfs_ao/legacy/shwfs_detector.py"
    reconstruction_path = ROOT / "src/shwfs_ao/legacy/reconstruction.py"
    synthetic_path = ROOT / "src/shwfs_ao/legacy/synthetic_instrument_data.py"
    shwfs_tree = ast.parse(shwfs_path.read_text(encoding="utf-8"))
    reconstruction_tree = ast.parse(reconstruction_path.read_text(encoding="utf-8"))
    synthetic_tree = ast.parse(synthetic_path.read_text(encoding="utf-8"))

    shwfs_functions = {
        node.name: node
        for node in shwfs_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert {
        "nominal_lenslet_sampling_shape",
        "lenslet_spot_from_phase",
        "crop_center",
    }.isdisjoint(shwfs_functions)
    assert not any(
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Attribute)
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "np"
        and node.value.attr == "fft"
        for node in ast.walk(shwfs_tree)
    )

    reconstruction_functions = {
        node.name: node
        for node in reconstruction_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "_masked_axis_gradient" not in reconstruction_functions
    assert any(
        isinstance(node, ast.Name) and node.id == "_canonical_numerical_gradient"
        for node in ast.walk(reconstruction_functions["numerical_gradient"])
    )
    assert any(
        isinstance(node, ast.Name) and node.id == "_legacy_shack_hartmann_geometry"
        for node in ast.walk(reconstruction_functions["subaperture_masks"])
    )
    assert any(
        isinstance(node, ast.Name) and node.id == "_partition_pupil_geometry"
        for node in ast.walk(
            reconstruction_functions["_legacy_shack_hartmann_geometry"]
        )
    )

    synthetic_functions = {
        node.name: node
        for node in synthetic_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not any(
        isinstance(node, ast.ClassDef) and node.name == "ShwfsGeometryConfig"
        for node in synthetic_tree.body
    )
    for function_name in (
        "build_detector_shwfs_calibration",
        "measure_detector_shwfs",
    ):
        called_names = {
            node.func.id
            for node in ast.walk(synthetic_functions[function_name])
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "lenslet_spot_from_phase" not in called_names
        assert "_apply_detector_effects" not in called_names


def test_synthetic_adapter_owns_one_realization_and_preserves_legacy_y_sign() -> None:
    detector = synthetic_instrument_data.DetectorConfig(
        photons_per_subap_frame=None,
        prnu_mode="persistent",
        prnu_rms=0.03,
    )
    calibration = synthetic_instrument_data.build_detector_shwfs_calibration(
        geometry=_geometry_config(),
        detector=detector,
    )
    sensor = calibration._canonical_sensor
    realization = sensor.detector_realization
    phase = synthetic_instrument_data.phase_tilt_map_rad(
        calibration,
        tilt_y_rad_per_m=0.05,
    )

    measurement = synthetic_instrument_data.measure_detector_shwfs(
        phase,
        calibration,
        include_noise=False,
        seed=17,
    )

    assert calibration._canonical_sensor is sensor
    assert calibration._canonical_sensor.detector_realization is realization
    assert realization.realization_hash == sensor.calibration.detector_realization_hash
    assert np.all(measurement.valid)
    assert np.mean(measurement.shifts_px[:, 1]) < 0.0
    assert np.max(np.abs(measurement.shifts_px[:, 0])) < 0.05


def test_reconstruction_adapters_preserve_column_outer_geometry_and_slopes() -> None:
    config = _geometry_config()
    x_m, y_m, pupil_mask, _ = synthetic_instrument_data.make_pupil_grid_and_mask(
        config
    )
    centers, masks = reconstruction.subaperture_masks(
        x_m,
        y_m,
        pupil_mask,
        n_lenslets=config.n_lenslets,
        min_fill=config.min_fill_fraction,
    )
    measured_centers, slopes = reconstruction.measure_slopes(
        2.0 * x_m - 3.0 * y_m,
        pupil_mask,
        x_m,
        y_m,
        n_lenslets=config.n_lenslets,
        min_fill=config.min_fill_fraction,
    )

    np.testing.assert_array_equal(measured_centers, centers)
    assert len(masks) == len(centers)
    np.testing.assert_allclose(slopes[:, 0], 2.0, atol=1.0e-12, rtol=0.0)
    np.testing.assert_allclose(slopes[:, 1], -3.0, atol=1.0e-12, rtol=0.0)


def test_legacy_seed_adapters_reject_negative_seeds() -> None:
    config = _geometry_config()
    calibration = synthetic_instrument_data.build_detector_shwfs_calibration(
        geometry=config,
    )
    phase = np.zeros_like(calibration.x_m)
    with pytest.raises(
        synthetic_instrument_data.SyntheticInstrumentError,
        match="non-negative",
    ):
        synthetic_instrument_data.measure_detector_shwfs(
            phase,
            calibration,
            seed=-1,
        )
    with pytest.raises(ValueError, match="non-negative"):
        shwfs_detector.measure_centroid_shifts(
            phase,
            calibration.pupil_mask,
            calibration.x_m,
            calibration.y_m,
            n_lenslets=config.n_lenslets,
            min_fill=config.min_fill_fraction,
            seed=-1,
        )
