"""AO-REF-004 ownership and installed compatibility-adapter checks."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import numpy as np
import pytest

import shwfs_ao.detector as detector
from shwfs_ao.detector.centroid import estimate_centroid
from shwfs_ao.detector.config import (
    DETECTOR_PRESETS,
    DetectorConfig,
    DetectorPreset,
    SyntheticInstrumentError,
    detector_preset,
    make_bad_pixel_mask,
)
from shwfs_ao.detector.validity import (
    DEFAULT_CENTROID_VALIDITY,
    CentroidValidityConfig,
)
from shwfs_ao.legacy import shwfs_detector, synthetic_instrument_data


ROOT = Path(__file__).resolve().parents[2]


def test_detector_package_reexports_component_objects_by_identity() -> None:
    assert detector.DetectorConfig is DetectorConfig
    assert detector.DetectorPreset is DetectorPreset
    assert detector.CentroidValidityConfig is CentroidValidityConfig
    assert detector.DETECTOR_PRESETS is DETECTOR_PRESETS
    assert detector.DEFAULT_CENTROID_VALIDITY is DEFAULT_CENTROID_VALIDITY
    assert detector.detector_preset is detector_preset
    assert detector.make_bad_pixel_mask is make_bad_pixel_mask
    assert len(detector.__all__) == len(set(detector.__all__))
    assert all(hasattr(detector, name) for name in detector.__all__)


def test_legacy_and_top_level_configuration_names_are_canonical_aliases() -> None:
    top_level = importlib.import_module("synthetic_instrument_data")
    for module in (synthetic_instrument_data, top_level):
        assert module.DetectorConfig is DetectorConfig
        assert module.DetectorPreset is DetectorPreset
        assert module.CentroidValidityConfig is CentroidValidityConfig
        assert module.SyntheticInstrumentError is SyntheticInstrumentError
        assert module.DETECTOR_PRESETS is DETECTOR_PRESETS
        assert module.DEFAULT_CENTROID_VALIDITY is DEFAULT_CENTROID_VALIDITY
        assert module.detector_preset is detector_preset
        assert module.make_bad_pixel_mask is make_bad_pixel_mask


def test_legacy_centroid_only_adapts_the_canonical_coordinate_convention() -> None:
    image = np.zeros((4, 5), dtype=float)
    image[1, 3] = 7.0

    canonical = estimate_centroid(image)
    legacy = shwfs_detector.centroid(image)

    assert (canonical.x_px, canonical.y_px) == pytest.approx((3.0, 1.0))
    assert legacy == pytest.approx((1.0, 0.5))


def test_canonical_centroid_is_strict_while_legacy_nan_adapter_is_compatible() -> None:
    image = np.array([[1.0, np.nan], [0.0, 3.0]])

    with pytest.raises(ValueError, match="finite"):
        estimate_centroid(image)
    assert shwfs_detector.centroid(image) == pytest.approx((0.25, -0.25))


def test_legacy_detector_modules_no_longer_own_draw_or_validity_implementations() -> None:
    paths = (
        ROOT / "src/shwfs_ao/legacy/shwfs_detector.py",
        ROOT / "src/shwfs_ao/legacy/synthetic_instrument_data.py",
    )
    forbidden_classes = {
        "DetectorConfig",
        "DetectorPreset",
        "CentroidValidityConfig",
    }
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assert not any(
            isinstance(node, ast.ClassDef) and node.name in forbidden_classes
            for node in ast.walk(tree)
        )
        assert not any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"poisson", "normal"}
            for node in ast.walk(tree)
        )

    synthetic_functions = {
        node.name: node
        for node in ast.parse(paths[1].read_text(encoding="utf-8")).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "make_bad_pixel_mask" not in synthetic_functions
    assert "detector_preset" not in synthetic_functions
    assert "_intensity_weighted_rms_px" not in synthetic_functions


def test_canonical_detector_layer_has_no_legacy_control_or_matrix_dependency() -> None:
    detector_dir = ROOT / "src/shwfs_ao/detector"
    for path in detector_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported_parts: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_parts.update(
                    part
                    for alias in node.names
                    for part in alias.name.split(".")
                )
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_parts.update(node.module.split("."))
        assert imported_parts.isdisjoint(
            {"legacy", "control", "interaction_matrix"}
        ), path.name
