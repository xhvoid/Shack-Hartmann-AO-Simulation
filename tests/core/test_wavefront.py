"""Contracts for canonical wavefront operations and unit conversion."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Callable

import numpy as np
import pytest

import shwfs_ao
import shwfs_ao.core as core
import shwfs_ao.core.geometry as geometry
import shwfs_ao.core.hashing as hashing
import shwfs_ao.core.protocols as protocols
import shwfs_ao.core.random as random_streams
import shwfs_ao.core.types as result_types
import shwfs_ao.core.wavefront as wavefront
from shwfs_ao.core.wavefront import (
    mask_outside,
    masked_mean,
    masked_rms,
    opd_to_phase,
    phase_to_opd,
    remove_piston,
    validate_masked_finite,
)


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "src"
CANONICAL_WAVEFRONT_PATH = SOURCE_ROOT / "shwfs_ao" / "core" / "wavefront.py"

PUBLIC_NAMES = (
    "remove_piston",
    "masked_mean",
    "masked_rms",
    "phase_to_opd",
    "opd_to_phase",
    "mask_outside",
    "validate_masked_finite",
)

MaskedOperation = Callable[[object, object], object]


def _validate(values: object, mask: object) -> None:
    validate_masked_finite(values, mask, "test wavefront")


MASKED_OPERATIONS: tuple[tuple[str, MaskedOperation], ...] = (
    ("validate_masked_finite", _validate),
    ("masked_mean", masked_mean),
    ("masked_rms", masked_rms),
    ("remove_piston", remove_piston),
    ("mask_outside", mask_outside),
)


def test_core_packages_export_the_canonical_wavefront_api() -> None:
    assert wavefront.__all__ == PUBLIC_NAMES
    assert core.__all__ == (
        "SourceClass",
        "ALLOWED_SOURCE_CLASSES",
        "Provenance",
        *geometry.__all__,
        *PUBLIC_NAMES,
        *result_types.__all__,
        *protocols.__all__,
        *random_streams.__all__,
        *hashing.__all__,
    )
    assert shwfs_ao.__all__ == ("__version__",)
    assert all(getattr(core, name) is getattr(geometry, name) for name in geometry.__all__)
    assert all(getattr(core, name) is getattr(wavefront, name) for name in PUBLIC_NAMES)


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


def test_converters_accept_scalar_data_and_return_float_values() -> None:
    opd_m = phase_to_opd(np.float32(np.pi), wavelength_m=500.0e-9)
    phase_rad = opd_to_phase(np.float32(250.0e-9), wavelength_m=500.0e-9)

    assert np.asarray(opd_m).shape == ()
    assert np.asarray(phase_rad).shape == ()
    assert np.asarray(opd_m).dtype == np.dtype(float)
    assert np.asarray(phase_rad).dtype == np.dtype(float)
    assert float(opd_m) == pytest.approx(250.0e-9)
    assert float(phase_rad) == pytest.approx(np.pi)


@pytest.mark.parametrize("conversion", [phase_to_opd, opd_to_phase])
@pytest.mark.parametrize("wavelength_m", [0.0, -1.0, np.nan, np.inf, -np.inf])
def test_converters_reject_non_positive_or_non_finite_wavelengths(
    conversion: Callable[[object, object], object],
    wavelength_m: float,
) -> None:
    with pytest.raises(ValueError, match="wavelength"):
        conversion(np.array([1.0]), wavelength_m)


@pytest.mark.parametrize("conversion", [phase_to_opd, opd_to_phase])
def test_converters_reject_non_scalar_wavelengths(
    conversion: Callable[[object, object], object],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        conversion(np.array([1.0]), np.array([500.0e-9]))


def test_masked_statistics_and_piston_match_frozen_current_outputs() -> None:
    values = np.array([[1.0, 2.0, 100.0], [3.0, 4.0, -100.0]], dtype=np.float32)
    mask = np.array([[True, True, False], [True, True, False]])
    original = values.copy()
    expected = np.array([[-1.5, -0.5, np.nan], [0.5, 1.5, np.nan]])

    mean = masked_mean(values, mask)
    centered_rms = masked_rms(values, mask)
    uncentered_rms = masked_rms(values, mask, remove_mean=False)
    piston_removed = remove_piston(values, mask)

    assert type(mean) is float
    assert type(centered_rms) is float
    assert type(uncentered_rms) is float
    assert mean == pytest.approx(2.5)
    assert centered_rms == pytest.approx(1.118033988749895)
    assert uncentered_rms == pytest.approx(np.sqrt(7.5))
    assert isinstance(piston_removed, np.ndarray)
    assert piston_removed.dtype == np.dtype(float)
    assert piston_removed == pytest.approx(expected, nan_ok=True)
    assert np.mean(piston_removed[mask]) == pytest.approx(0.0, abs=1.0e-15)
    assert not np.shares_memory(piston_removed, values)
    assert np.array_equal(values, original)


def test_masked_operations_accept_non_finite_values_only_outside_the_pupil() -> None:
    values = np.array([[1.0, np.nan], [3.0, np.inf]])
    mask = np.array([[True, False], [True, False]])

    assert validate_masked_finite(values, mask, "outside non-finite map") is None
    assert masked_mean(values, mask) == pytest.approx(2.0)
    assert masked_rms(values, mask) == pytest.approx(1.0)
    assert remove_piston(values, mask) == pytest.approx(
        np.array([[-1.0, np.nan], [1.0, np.nan]]),
        nan_ok=True,
    )
    assert mask_outside(values, mask) == pytest.approx(
        np.array([[1.0, np.nan], [3.0, np.nan]]),
        nan_ok=True,
    )


@pytest.mark.parametrize(
    "operation_name,operation",
    MASKED_OPERATIONS,
    ids=[name for name, _ in MASKED_OPERATIONS],
)
@pytest.mark.parametrize("invalid_value", [np.nan, np.inf, -np.inf])
def test_every_masked_operation_rejects_an_interior_non_finite_sample(
    operation_name: str,
    operation: MaskedOperation,
    invalid_value: float,
) -> None:
    del operation_name
    values = np.array([[1.0, invalid_value], [3.0, 4.0]])
    mask = np.ones_like(values, dtype=bool)

    with pytest.raises(ValueError):
        operation(values, mask)


def test_masked_finite_error_identifies_the_callers_label() -> None:
    with pytest.raises(ValueError, match="residual input"):
        validate_masked_finite(
            np.array([1.0, np.nan]),
            np.array([True, True]),
            "residual input",
        )


@pytest.mark.parametrize(
    ("values", "mask"),
    [
        (np.empty(0), np.empty(0, dtype=bool)),
        (np.arange(4.0).reshape(2, 2), np.zeros((2, 2), dtype=bool)),
    ],
    ids=["zero-sized", "all-false"],
)
@pytest.mark.parametrize(
    "operation_name,operation",
    MASKED_OPERATIONS,
    ids=[name for name, _ in MASKED_OPERATIONS],
)
def test_every_masked_operation_rejects_an_empty_pupil(
    operation_name: str,
    operation: MaskedOperation,
    values: np.ndarray,
    mask: np.ndarray,
) -> None:
    del operation_name
    with pytest.raises(ValueError, match="mask|pupil|sample|empty"):
        operation(values, mask)


@pytest.mark.parametrize(
    "operation_name,operation",
    MASKED_OPERATIONS,
    ids=[name for name, _ in MASKED_OPERATIONS],
)
def test_every_masked_operation_rejects_a_pupil_with_no_finite_sample(
    operation_name: str,
    operation: MaskedOperation,
) -> None:
    del operation_name
    values = np.full((2, 2), np.nan)
    mask = np.ones((2, 2), dtype=bool)

    with pytest.raises(ValueError):
        operation(values, mask)


@pytest.mark.parametrize(
    "operation_name,operation",
    MASKED_OPERATIONS,
    ids=[name for name, _ in MASKED_OPERATIONS],
)
@pytest.mark.parametrize(
    ("values", "mask"),
    [
        (np.ones((2, 2)), np.ones(4, dtype=bool)),
        (np.array(1.0), np.array([True])),
    ],
    ids=["same-size-different-shape", "scalar-versus-vector"],
)
def test_every_masked_operation_rejects_shape_mismatch_without_broadcasting(
    operation_name: str,
    operation: MaskedOperation,
    values: np.ndarray,
    mask: np.ndarray,
) -> None:
    del operation_name
    with pytest.raises(ValueError, match="shape|mask"):
        operation(values, mask)


def test_single_scalar_pupil_sample_is_valid() -> None:
    values = np.float32(7.5)
    mask = np.bool_(True)

    assert validate_masked_finite(values, mask, "scalar pupil") is None
    assert masked_mean(values, mask) == pytest.approx(7.5)
    assert masked_rms(values, mask) == pytest.approx(0.0)
    assert masked_rms(values, mask, remove_mean=False) == pytest.approx(7.5)

    piston_removed = np.asarray(remove_piston(values, mask))
    masked = np.asarray(mask_outside(values, mask))
    assert piston_removed.shape == masked.shape == ()
    assert piston_removed.dtype == masked.dtype == np.dtype(float)
    assert float(piston_removed) == pytest.approx(0.0)
    assert float(masked) == pytest.approx(7.5)


def test_false_scalar_mask_is_rejected_as_an_empty_pupil() -> None:
    for _, operation in MASKED_OPERATIONS:
        with pytest.raises(ValueError):
            operation(np.float32(7.5), np.bool_(False))


def test_mask_outside_supports_nan_finite_and_infinite_scalar_fills_without_mutation() -> None:
    values = np.array([[1, 2], [3, 4]], dtype=np.int16)
    mask = np.array([[True, False], [False, True]])
    original = values.copy()

    default = mask_outside(values, mask)
    finite_fill = mask_outside(values, mask, fill=-7.5)
    infinite_fill = mask_outside(values, mask, fill=np.inf)

    assert default == pytest.approx(np.array([[1.0, np.nan], [np.nan, 4.0]]), nan_ok=True)
    assert finite_fill == pytest.approx(np.array([[1.0, -7.5], [-7.5, 4.0]]))
    assert infinite_fill == pytest.approx(np.array([[1.0, np.inf], [np.inf, 4.0]]))
    assert default.dtype == finite_fill.dtype == infinite_fill.dtype == np.dtype(float)
    assert not np.shares_memory(default, values)
    assert not np.shares_memory(finite_fill, values)
    assert np.array_equal(values, original)


def test_mask_outside_rejects_a_non_scalar_fill() -> None:
    with pytest.raises((TypeError, ValueError)):
        mask_outside(
            np.array([1.0, 2.0]),
            np.array([True, False]),
            fill=np.array([0.0, 0.0]),
        )


@pytest.mark.parametrize(
    "legacy_module_name",
    [
        "shwfs_ao.legacy.zernike",
        "shwfs_ao.legacy.phase_screen",
        "shwfs_ao.legacy.reconstruction",
    ],
)
def test_legacy_wrappers_documentedly_preserve_historical_non_finite_filtering(
    legacy_module_name: str,
) -> None:
    legacy_module = __import__(legacy_module_name, fromlist=["remove_piston", "rms"])
    values = np.array([[1.0, np.nan], [3.0, 4.0]])
    mask = np.ones((2, 2), dtype=bool)
    expected = np.array([[-5.0 / 3.0, np.nan], [1.0 / 3.0, 4.0 / 3.0]])

    with pytest.raises(ValueError):
        remove_piston(values, mask)
    with pytest.raises(ValueError):
        masked_rms(values, mask)

    assert legacy_module.remove_piston(values, mask) == pytest.approx(expected, nan_ok=True)
    assert legacy_module.rms(values, mask) == pytest.approx(1.247219128924647)


def test_no_nonlegacy_module_defines_a_second_wavefront_operation() -> None:
    forbidden_names = {
        "remove_piston",
        "_remove_piston",
        "_remove_piston_phase",
        "masked_rms",
        "_masked_rms",
        "rms",
        "_rms",
        "phase_to_opd",
        "opd_to_phase",
    }
    offenders: list[str] = []

    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        relative = path.relative_to(SOURCE_ROOT)
        if path == CANONICAL_WAVEFRONT_PATH or "legacy" in relative.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in forbidden_names:
                offenders.append(f"{relative}:{node.lineno}:{node.name}")

    assert offenders == []
