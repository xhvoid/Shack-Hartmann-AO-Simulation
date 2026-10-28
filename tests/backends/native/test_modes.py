"""Canonical real-Zernike generation and sampled normalization contracts."""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

import shwfs_ao.backends.native as native
from shwfs_ao.backends.native import modes
from shwfs_ao.core import wavefront
from shwfs_ao.legacy import zernike as legacy_zernike


ROOT = Path(__file__).resolve().parents[3]

NATIVE_MODE_EXPORTS = (
    "NativeModesError",
    "polar_pupil_coordinates",
    "normalize_mode_to_unit_pupil_rms",
    "zernike_named_modes",
    "zernike_radial",
    "zernike_nm",
    "generate_zernike_modes",
    "number_of_zernike_modes",
    "synthesize_modes",
    "mode_inner_product",
    "mode_gram_matrix",
)


@pytest.fixture
def sampled_pupil() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    axis = np.linspace(-1.0, 1.0, 65)
    x_m, y_m = np.meshgrid(axis, axis, indexing="xy")
    rho, theta = modes.polar_pupil_coordinates(x_m, y_m, 2.0)
    pupil = rho <= 1.0
    return x_m, y_m, rho, theta, pupil


def test_native_mode_exports_are_exact() -> None:
    assert modes.__all__ == NATIVE_MODE_EXPORTS
    assert all(hasattr(modes, name) for name in NATIVE_MODE_EXPORTS)
    assert all(
        getattr(native, name) is getattr(modes, name)
        for name in NATIVE_MODE_EXPORTS
    )


def test_general_mode_order_sign_and_outside_policy_are_frozen(
    sampled_pupil: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    x_m, y_m, rho, theta, pupil = sampled_pupil
    generated = modes.generate_zernike_modes(
        rho,
        theta,
        pupil,
        max_radial_order=4,
    )

    assert tuple(generated) == (
        "Z1_+1",
        "Z1_-1",
        "Z2_+0",
        "Z2_+2",
        "Z2_-2",
        "Z3_+1",
        "Z3_-1",
        "Z3_+3",
        "Z3_-3",
        "Z4_+0",
        "Z4_+2",
        "Z4_-2",
        "Z4_+4",
        "Z4_-4",
    )
    np.testing.assert_allclose(
        generated["Z1_+1"][pupil],
        2.0 * x_m[pupil],
        atol=2.0e-16,
    )
    np.testing.assert_allclose(
        generated["Z1_-1"][pupil],
        2.0 * y_m[pupil],
        atol=3.0e-16,
    )
    for mode in generated.values():
        assert np.all(np.isfinite(mode))
        assert np.all(mode[~pupil] == 0.0)
        assert not mode.flags.writeable
        with pytest.raises(ValueError):
            mode.setflags(write=True)


def test_single_normalizer_removes_sampled_piston_and_reports_raw_scale(
    sampled_pupil: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    x_m, y_m, _rho, _theta, pupil = sampled_pupil
    raw = 7.5 + 3.0 * x_m - 4.0 * y_m
    raw[~pupil] = np.nan

    normalized, scale = modes.normalize_mode_to_unit_pupil_rms(
        raw,
        pupil,
        return_scale=True,
    )

    expected_scale = wavefront.masked_rms(raw, pupil)
    assert scale == pytest.approx(expected_scale, rel=0.0, abs=0.0)
    assert wavefront.masked_mean(normalized, pupil) == pytest.approx(0.0, abs=2.0e-16)
    assert wavefront.masked_rms(normalized, pupil) == pytest.approx(1.0, abs=2.0e-15)
    assert np.all(normalized[~pupil] == 0.0)
    assert not normalized.flags.writeable
    with pytest.raises(ValueError):
        normalized.setflags(write=True)


def test_normalizer_rejects_piston_after_the_one_piston_removal(
    sampled_pupil: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    _x_m, _y_m, rho, _theta, pupil = sampled_pupil
    piston = np.where(pupil, np.ones_like(rho), np.nan)

    with pytest.raises(modes.NativeModesError, match="non-zero pupil RMS"):
        modes.normalize_mode_to_unit_pupil_rms(piston, pupil)

    normalized = modes.normalize_mode_to_unit_pupil_rms(
        piston,
        pupil,
        remove_piston=False,
    )
    np.testing.assert_array_equal(normalized[pupil], 1.0)


def test_legacy_wrappers_restore_writable_nan_outside_without_reordering(
    sampled_pupil: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    _x_m, _y_m, rho, theta, pupil = sampled_pupil
    canonical = modes.generate_zernike_modes(
        rho,
        theta,
        pupil,
        max_radial_order=5,
    )
    legacy = legacy_zernike.generate_zernike_modes(
        rho,
        theta,
        pupil,
        max_radial_order=5,
    )

    assert tuple(legacy) == tuple(canonical)
    for name in canonical:
        np.testing.assert_array_equal(legacy[name][pupil], canonical[name][pupil])
        assert np.all(np.isnan(legacy[name][~pupil]))
        assert legacy[name].flags.writeable


def test_legacy_module_contains_no_second_zernike_formula() -> None:
    path = ROOT / "src/shwfs_ao/legacy/zernike.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "eval_jacobi" not in calls
    assert "_native_zernike_radial" in calls
    assert "_native_zernike_nm" in calls
    assert "_native_generate_zernike_modes" in calls


def test_modal_synthesis_and_gram_matrix_keep_finite_native_layout(
    sampled_pupil: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> None:
    _x_m, _y_m, rho, theta, pupil = sampled_pupil
    generated = modes.generate_zernike_modes(
        rho,
        theta,
        pupil,
        max_radial_order=2,
    )
    coefficients = {"Z1_+1": 2.0e-8, "Z2_+0": -3.0e-8}

    synthesized = modes.synthesize_modes(generated, coefficients, pupil)
    gram, names = modes.mode_gram_matrix(generated, pupil)

    expected = sum(coefficients.get(name, 0.0) * mode for name, mode in generated.items())
    np.testing.assert_allclose(synthesized, expected, rtol=0.0, atol=0.0)
    assert names == tuple(generated)
    assert gram.shape == (len(names), len(names))
    assert np.all(np.isfinite(gram))
    assert np.allclose(gram, gram.T)
    assert not synthesized.flags.writeable
    assert not gram.flags.writeable
