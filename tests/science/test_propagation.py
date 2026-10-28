"""Focused AO-REF-010 science-propagation contracts."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
import inspect
from pathlib import Path
from types import MappingProxyType

import numpy as np
import pytest

from shwfs_ao.core.geometry import PupilGeometry, build_pupil_geometry
from shwfs_ao.core.protocols import SciencePropagator
from shwfs_ao.core.types import PsfResult
from shwfs_ao.backends.native.propagation import (
    NativeSciencePropagator,
    _normalized_fft_psf_from_phase,
)
from shwfs_ao.science.propagation import (
    PsfSampling,
    SciencePropagationError,
    monochromatic_psf,
)


ROOT = Path(__file__).resolve().parents[2]


def _pupil(*, size: int = 16, diameter_m: float = 2.0) -> PupilGeometry:
    return build_pupil_geometry(
        telescope_diameter_m=diameter_m,
        pupil_shape=(size, size),
    )


def _zero_opd(pupil: PupilGeometry) -> np.ndarray:
    return np.where(pupil.pupil_mask, 0.0, np.nan)


def _historical_fft_psf(
    phase_rad: np.ndarray,
    mask: np.ndarray,
    pad_factor: int,
) -> np.ndarray:
    """Independent copy of the frozen AO-REF-000 arithmetic for regression."""

    pupil_field = np.zeros_like(phase_rad, dtype=complex)
    pupil_field[mask] = np.exp(1j * phase_rad[mask])
    size = phase_rad.shape[0]
    padded_size = int(pad_factor * size)
    padded = np.zeros((padded_size, padded_size), dtype=complex)
    start = (padded_size - size) // 2
    padded[start : start + size, start : start + size] = pupil_field
    focal_field = np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(padded)))
    psf = np.abs(focal_field) ** 2
    total = np.sum(psf)
    if total > 0:
        psf /= total
    return psf


def test_public_surface_and_helper_signature_are_explicit() -> None:
    from shwfs_ao.science import propagation

    assert propagation.__all__ == (
        "SciencePropagationError",
        "PsfSampling",
        "monochromatic_psf",
    )
    from shwfs_ao.backends.native import propagation as native_propagation

    assert native_propagation.__all__ == ("NativeSciencePropagator",)
    signature = inspect.signature(monochromatic_psf)
    assert tuple(signature.parameters) == (
        "opd_m",
        "pupil",
        "wavelength_m",
        "backend",
        "sampling",
    )
    assert signature.parameters["backend"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["sampling"].kind is inspect.Parameter.KEYWORD_ONLY


def test_sampling_is_frozen_and_strictly_rejects_bool_or_nonpositive_padding() -> None:
    sampling = PsfSampling(pad_factor=np.int64(3))
    assert sampling.pad_factor == 3
    assert type(sampling.pad_factor) is int
    with pytest.raises(FrozenInstanceError):
        sampling.pad_factor = 2  # type: ignore[misc]

    for value in (True, np.bool_(False), 0, -1, 1.5, "2"):
        with pytest.raises(SciencePropagationError):
            PsfSampling(pad_factor=value)  # type: ignore[arg-type]


def test_native_propagator_binds_immutable_config_and_satisfies_protocol() -> None:
    pupil = _pupil()
    sampling = PsfSampling(3)
    propagator = NativeSciencePropagator(pupil=pupil, sampling=sampling)
    repeated = NativeSciencePropagator(pupil=_pupil(), sampling=PsfSampling(3))

    assert isinstance(propagator, SciencePropagator)
    assert propagator.backend_name == "native"
    assert propagator.pupil is pupil
    assert propagator.sampling is sampling
    assert len(propagator.config_hash) == 64
    assert propagator.config_hash == repeated.config_hash
    assert propagator.config_hash != NativeSciencePropagator(
        pupil=pupil,
        sampling=PsfSampling(2),
    ).config_hash
    with pytest.raises(FrozenInstanceError):
        propagator.sampling = PsfSampling(4)  # type: ignore[misc]


def test_native_fft_exactly_preserves_historical_centering_and_normalization() -> None:
    pupil = _pupil(size=18)
    phase_rad = np.where(
        pupil.pupil_mask,
        0.37 * pupil.x_m - 0.19 * pupil.y_m + 0.11 * pupil.x_m * pupil.y_m,
        np.nan,
    )
    expected = _historical_fft_psf(phase_rad, pupil.pupil_mask, pad_factor=3)

    actual = _normalized_fft_psf_from_phase(
        phase_rad,
        pupil.pupil_mask,
        pad_factor=3,
    )

    np.testing.assert_array_equal(actual, expected)


def test_opd_propagation_returns_exact_contract_with_physical_angular_axes() -> None:
    pupil = _pupil(size=20, diameter_m=2.0)
    wavelength_m = 1.65e-6
    sampling = PsfSampling(4)
    result = monochromatic_psf(
        _zero_opd(pupil),
        pupil,
        wavelength_m,
        backend="native",
        sampling=sampling,
    )

    assert isinstance(result, PsfResult)
    assert result.backend_name == "native"
    assert result.normalization == "unit_total_flux"
    assert result.wavelength_m == wavelength_m
    assert result.intensity.shape == (80, 80)
    assert np.all(np.isfinite(result.intensity))
    assert np.all(result.intensity >= 0.0)
    assert np.sum(result.intensity) == pytest.approx(1.0, abs=1.0e-12)
    assert result.x_angle_rad.shape == (80,)
    assert result.y_angle_rad.shape == (80,)
    assert np.all(np.diff(result.x_angle_rad) > 0.0)
    assert np.all(np.diff(result.y_angle_rad) > 0.0)

    dx_m, dy_m = pupil.pixel_spacing_xy_m
    expected_scale = (
        wavelength_m / (80 * dx_m),
        wavelength_m / (80 * dy_m),
    )
    np.testing.assert_allclose(
        np.diff(result.x_angle_rad),
        expected_scale[0],
        rtol=1.0e-13,
        atol=0.0,
    )
    np.testing.assert_allclose(
        np.diff(result.y_angle_rad),
        expected_scale[1],
        rtol=1.0e-13,
        atol=0.0,
    )
    assert np.unravel_index(np.argmax(result.intensity), result.intensity.shape) == (
        40,
        40,
    )


def test_zero_opd_intensity_is_wavelength_invariant_while_axes_scale() -> None:
    pupil = _pupil()
    propagator = NativeSciencePropagator(pupil, PsfSampling(3))

    short = propagator.psf_from_opd(_zero_opd(pupil), 1.0e-6)
    long = propagator.psf_from_opd(_zero_opd(pupil), 2.0e-6)

    np.testing.assert_array_equal(short.intensity, long.intensity)
    np.testing.assert_allclose(long.x_angle_rad, 2.0 * short.x_angle_rad)
    np.testing.assert_allclose(long.y_angle_rad, 2.0 * short.y_angle_rad)


def test_rectangular_pupil_has_independent_row_and_column_physical_sampling() -> None:
    pupil = build_pupil_geometry(
        telescope_diameter_m=2.0,
        pupil_shape=(16, 20),
    )
    wavelength_m = 1.2e-6
    result = NativeSciencePropagator(pupil, PsfSampling(3)).psf_from_opd(
        _zero_opd(pupil),
        wavelength_m,
    )

    assert result.intensity.shape == (48, 60)
    assert result.x_angle_rad.shape == (60,)
    assert result.y_angle_rad.shape == (48,)
    dx_m, dy_m = pupil.pixel_spacing_xy_m
    np.testing.assert_allclose(
        np.diff(result.x_angle_rad),
        wavelength_m / (60 * dx_m),
        rtol=1.0e-13,
        atol=0.0,
    )
    np.testing.assert_allclose(
        np.diff(result.y_angle_rad),
        wavelength_m / (48 * dy_m),
        rtol=1.0e-13,
        atol=0.0,
    )
    assert result.sampling_metadata["pupil_shape_px"] == (16, 20)
    assert result.sampling_metadata["output_shape_px"] == (48, 60)


def test_sampling_metadata_is_complete_repository_owned_and_immutable() -> None:
    pupil = _pupil()
    result = NativeSciencePropagator(pupil, PsfSampling(2)).psf_from_opd(
        _zero_opd(pupil),
        1.25e-6,
    )
    metadata = result.sampling_metadata

    assert isinstance(metadata, MappingProxyType)
    assert metadata["pupil_geometry_hash"] == pupil.geometry_hash
    assert metadata["pupil_shape_px"] == (16, 16)
    assert metadata["padded_fft_shape_px"] == (32, 32)
    assert metadata["output_shape_px"] == result.intensity.shape
    assert metadata["pad_factor"] == 2
    assert metadata["cropping"] == "none"
    assert metadata["interpolation"] == "none"
    assert metadata["normalization"] == "unit_total_flux"
    assert metadata["axis_layout"] == "x_columns_y_rows"
    with pytest.raises(TypeError):
        metadata["pad_factor"] = 9  # type: ignore[index]

    for array in (result.intensity, result.x_angle_rad, result.y_angle_rad):
        assert not array.flags.writeable
        with pytest.raises(ValueError):
            array.setflags(write=True)


@pytest.mark.parametrize("wavelength", [0.0, -1.0, np.inf, -np.inf, np.nan, True])
def test_wavelength_must_be_a_positive_finite_real(wavelength: object) -> None:
    pupil = _pupil()
    propagator = NativeSciencePropagator(pupil, PsfSampling())
    with pytest.raises(SciencePropagationError, match="wavelength_m"):
        propagator.psf_from_opd(_zero_opd(pupil), wavelength)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "bad_opd",
    [
        [[0.0] * 16 for _ in range(16)],
        np.zeros((15, 16)),
        np.zeros((16, 16), dtype=bool),
        np.zeros((16, 16), dtype=complex),
    ],
)
def test_opd_requires_a_real_numpy_array_on_the_bound_grid(bad_opd: object) -> None:
    pupil = _pupil()
    propagator = NativeSciencePropagator(pupil, PsfSampling())
    with pytest.raises(SciencePropagationError, match="opd_m"):
        propagator.psf_from_opd(bad_opd, 1.0e-6)  # type: ignore[arg-type]


def test_nonfinite_opd_is_allowed_only_as_nan_outside_pupil() -> None:
    pupil = _pupil()
    propagator = NativeSciencePropagator(pupil, PsfSampling(2))
    exterior_nan = _zero_opd(pupil)
    result = propagator.psf_from_opd(exterior_nan, 1.0e-6)
    assert np.sum(result.intensity) == pytest.approx(1.0)

    invalid_inside = exterior_nan.copy()
    row, column = np.argwhere(pupil.pupil_mask)[0]
    invalid_inside[row, column] = np.nan
    with pytest.raises(SciencePropagationError, match="finite.*illuminated"):
        propagator.psf_from_opd(invalid_inside, 1.0e-6)

    infinity_outside = exterior_nan.copy()
    row, column = np.argwhere(~pupil.pupil_mask)[0]
    infinity_outside[row, column] = np.inf
    with pytest.raises(SciencePropagationError, match="infinite"):
        propagator.psf_from_opd(infinity_outside, 1.0e-6)


def test_constructor_and_helper_reject_mismatched_config_or_backend() -> None:
    pupil = _pupil()
    with pytest.raises(SciencePropagationError, match="PupilGeometry"):
        NativeSciencePropagator(  # type: ignore[arg-type]
            pupil=np.ones((16, 16), dtype=bool),
            sampling=PsfSampling(),
        )
    with pytest.raises(SciencePropagationError, match="PsfSampling"):
        NativeSciencePropagator(pupil=pupil, sampling=4)  # type: ignore[arg-type]

    for backend in ("hcipy", "Native", "", None):
        with pytest.raises(SciencePropagationError, match="backend"):
            monochromatic_psf(
                _zero_opd(pupil),
                pupil,
                1.0e-6,
                backend=backend,  # type: ignore[arg-type]
                sampling=PsfSampling(),
            )


def test_propagation_module_has_no_detector_or_controller_imports() -> None:
    for source_path in (
        ROOT / "src" / "shwfs_ao" / "science" / "propagation.py",
        ROOT / "src" / "shwfs_ao" / "backends" / "native" / "propagation.py",
    ):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported_modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        imported_modules.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        assert not any(
            "detector" in module or "control" in module or "controller" in module
            for module in imported_modules
        )
