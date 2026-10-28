"""AO-REF-017 contracts for the HCIPy science-propagation backend.

Every test requires the optional HCIPy dependency and carries the ``hcipy``
marker so native CI selections never execute it.  The module is part of the
portable wheel-smoke bundle, so it imports only the installed package.
"""

from __future__ import annotations

import json

import numpy as np
import pytest


hcipy = pytest.importorskip("hcipy")

from scipy.interpolate import RegularGridInterpolator

from shwfs_ao.backends.hcipy.propagation import (
    HcipyFocalSampling,
    HcipySciencePropagationError,
    HcipySciencePropagator,
    focal_sampling_from_psf_sampling,
)
from shwfs_ao.backends.native.propagation import NativeSciencePropagator
from shwfs_ao.core.geometry import build_pupil_geometry
from shwfs_ao.core.protocols import SciencePropagator
from shwfs_ao.core.types import PsfResult
from shwfs_ao.core.wavefront import masked_rms
from shwfs_ao.science.metrics import (
    encircled_energy_radius_from_discrete_flux,
    peak_strehl_from_discrete_flux,
    psf_scalar_metrics,
)
from shwfs_ao.science.propagation import PsfSampling, monochromatic_psf


pytestmark = pytest.mark.hcipy


WAVELENGTH_M = 700.0e-9
DIAMETER_M = 1.0
PUPIL_PIXELS = 64


def _pupil(central_obstruction_ratio: float = 0.0):
    return build_pupil_geometry(
        telescope_diameter_m=DIAMETER_M,
        pupil_shape=(PUPIL_PIXELS, PUPIL_PIXELS),
        central_obstruction_ratio=central_obstruction_ratio,
    )


def _zero_opd(pupil) -> np.ndarray:
    return np.zeros(pupil.pupil_shape, dtype=float)


def _astigmatism_opd(pupil, rms_m: float) -> np.ndarray:
    raw = np.where(pupil.pupil_mask, pupil.x_m**2 - pupil.y_m**2, 0.0)
    raw = np.where(
        pupil.pupil_mask,
        raw - float(np.mean(raw[pupil.pupil_mask])),
        0.0,
    )
    scale = masked_rms(
        np.where(pupil.pupil_mask, raw, np.nan),
        pupil.pupil_mask,
    )
    return raw * (rms_m / scale)


def _propagator(pupil=None, **sampling_changes) -> HcipySciencePropagator:
    resolved = _pupil() if pupil is None else pupil
    values = {
        "pixels_per_resolution_element": 8.0,
        "radius_resolution_elements": 4.0,
    }
    values.update(sampling_changes)
    return HcipySciencePropagator(resolved, HcipyFocalSampling(**values))


def _first_minimum_radius_rad(psf: PsfResult) -> float:
    peak_row, peak_column = np.unravel_index(
        int(np.argmax(psf.intensity)),
        psf.intensity.shape,
    )
    profile = psf.intensity[peak_row, peak_column:]
    for index in range(1, profile.size - 1):
        if profile[index] < profile[index - 1] and profile[index] <= profile[index + 1]:
            return float(
                psf.x_angle_rad[peak_column + index]
                - psf.x_angle_rad[peak_column]
            )
    raise AssertionError("no local minimum found along the +x profile")


class TestPsfContract:
    def test_propagator_implements_the_science_protocol(self):
        propagator = _propagator()
        assert isinstance(propagator, SciencePropagator)
        assert propagator.backend_name == "hcipy"
        assert len(propagator.config_hash) == 64

    def test_result_is_a_canonical_unit_flux_psf(self):
        pupil = _pupil()
        psf = _propagator(pupil).psf_from_opd(_zero_opd(pupil), WAVELENGTH_M)

        assert isinstance(psf, PsfResult)
        assert psf.backend_name == "hcipy"
        assert psf.wavelength_m == WAVELENGTH_M
        assert psf.normalization == "unit_total_flux"
        assert type(psf.intensity) is np.ndarray
        assert not isinstance(psf.intensity, hcipy.Field)
        assert not psf.intensity.flags.writeable
        assert np.all(psf.intensity >= 0.0)
        assert float(np.sum(psf.intensity)) == pytest.approx(1.0, abs=1.0e-12)

    def test_angular_axes_come_from_the_hcipy_focal_grid(self):
        pupil = _pupil()
        sampling = HcipyFocalSampling(8.0, 4.0)
        psf = HcipySciencePropagator(pupil, sampling).psf_from_opd(
            _zero_opd(pupil),
            WAVELENGTH_M,
        )
        resolution_rad = WAVELENGTH_M / DIAMETER_M
        expected_delta = resolution_rad / 8.0

        for axis in (psf.x_angle_rad, psf.y_angle_rad):
            assert axis.ndim == 1
            assert np.all(np.diff(axis) > 0.0)
            assert np.allclose(
                np.diff(axis),
                expected_delta,
                rtol=1.0e-12,
                atol=0.0,
            )
            # The grid is centered and contains the exact origin sample.
            assert float(np.min(np.abs(axis))) == 0.0
            assert float(axis[-1] - axis[0]) == pytest.approx(
                2.0 * 4.0 * resolution_rad - expected_delta,
                rel=1.0e-12,
            )
        assert psf.intensity.shape == (
            psf.y_angle_rad.size,
            psf.x_angle_rad.size,
        )
        assert psf.intensity.shape == (sampling.focal_dims_px,) * 2

    def test_sampling_metadata_is_construction_determined_json(self):
        pupil = _pupil()
        propagator = _propagator(pupil)
        first = propagator.psf_from_opd(_zero_opd(pupil), WAVELENGTH_M)
        second = propagator.psf_from_opd(
            _astigmatism_opd(pupil, 60.0e-9),
            WAVELENGTH_M,
        )
        json.dumps(_plain_json(first.sampling_metadata))
        # Identical sampling metadata is what lets the science metrics
        # require exact grid identity between a PSF and its ideal reference.
        assert dict(first.sampling_metadata) == dict(second.sampling_metadata)
        assert first.sampling_metadata["axis_layout"] == "x_columns_y_rows"
        assert first.sampling_metadata["normalization"] == "unit_total_flux"

    def test_propagation_is_memoryless_and_deterministic(self):
        pupil = _pupil()
        propagator = _propagator(pupil)
        opd = _astigmatism_opd(pupil, 40.0e-9)
        first = propagator.psf_from_opd(opd, WAVELENGTH_M)
        propagator.psf_from_opd(_zero_opd(pupil), 2.0 * WAVELENGTH_M)
        second = propagator.psf_from_opd(opd, WAVELENGTH_M)
        assert np.array_equal(first.intensity, second.intensity)

    def test_captured_flux_fraction_is_a_separate_diagnostic(self):
        pupil = _pupil()
        propagator = _propagator(pupil)
        captured = propagator.captured_flux_fraction(
            _zero_opd(pupil),
            WAVELENGTH_M,
        )
        assert 0.8 < captured <= 1.0 + 1.0e-9
        aberrated = propagator.captured_flux_fraction(
            _astigmatism_opd(pupil, 80.0e-9),
            WAVELENGTH_M,
        )
        assert aberrated < captured
        psf = propagator.psf_from_opd(_zero_opd(pupil), WAVELENGTH_M)
        assert "captured_flux_fraction" not in psf.sampling_metadata


class TestDiffractionPhysics:
    def test_zero_opd_gives_the_diffraction_limited_peak_at_the_origin(self):
        pupil = _pupil()
        propagator = _propagator(pupil)
        psf = propagator.psf_from_opd(_zero_opd(pupil), WAVELENGTH_M)
        peak_row, peak_column = np.unravel_index(
            int(np.argmax(psf.intensity)),
            psf.intensity.shape,
        )
        assert psf.x_angle_rad[peak_column] == 0.0
        assert psf.y_angle_rad[peak_row] == 0.0

        aberrated = propagator.psf_from_opd(
            _astigmatism_opd(pupil, 60.0e-9),
            WAVELENGTH_M,
        )
        assert float(np.max(aberrated.intensity)) < float(
            np.max(psf.intensity)
        )

    def test_airy_first_minimum_for_a_circular_pupil(self):
        pupil = _pupil()
        psf = _propagator(pupil).psf_from_opd(_zero_opd(pupil), WAVELENGTH_M)
        first_minimum_rad = _first_minimum_radius_rad(psf)
        assert first_minimum_rad == pytest.approx(
            1.22 * WAVELENGTH_M / DIAMETER_M,
            rel=0.08,
        )

    def test_central_obstruction_scales_the_peak_and_tightens_the_core(self):
        clear = _propagator(_pupil()).psf_from_opd(
            _zero_opd(_pupil()),
            WAVELENGTH_M,
        )
        obstruction_ratio = 0.3
        obstructed_pupil = _pupil(
            central_obstruction_ratio=obstruction_ratio
        )
        obstructed = _propagator(obstructed_pupil).psf_from_opd(
            _zero_opd(obstructed_pupil),
            WAVELENGTH_M,
        )
        # For unit-total-flux normalization the on-axis peak of an annular
        # aperture scales as (1 - eps^2) relative to the clear aperture.
        peak_ratio = float(np.max(obstructed.intensity)) / float(
            np.max(clear.intensity)
        )
        assert peak_ratio == pytest.approx(
            1.0 - obstruction_ratio**2,
            rel=0.05,
        )
        assert _first_minimum_radius_rad(obstructed) < _first_minimum_radius_rad(
            clear
        )

    def test_angular_axes_and_airy_radius_scale_with_wavelength(self):
        pupil = _pupil()
        propagator = _propagator(pupil)
        blue = propagator.psf_from_opd(_zero_opd(pupil), WAVELENGTH_M)
        red = propagator.psf_from_opd(_zero_opd(pupil), 2.0 * WAVELENGTH_M)

        assert np.allclose(
            red.x_angle_rad,
            2.0 * blue.x_angle_rad,
            rtol=1.0e-12,
            atol=0.0,
        )
        assert _first_minimum_radius_rad(red) == pytest.approx(
            2.0 * _first_minimum_radius_rad(blue),
            rel=0.05,
        )

    def test_phase_to_psf_wavelength_scaling_follows_marechal(self):
        pupil = _pupil()
        propagator = _propagator(pupil)
        opd = _astigmatism_opd(pupil, 60.0e-9)
        rms_m = masked_rms(
            np.where(pupil.pupil_mask, opd, np.nan),
            pupil.pupil_mask,
        )
        strehls = {}
        for wavelength_m in (WAVELENGTH_M, 2.0 * WAVELENGTH_M):
            strehls[wavelength_m] = peak_strehl_from_discrete_flux(
                propagator.psf_from_opd(opd, wavelength_m),
                propagator.psf_from_opd(_zero_opd(pupil), wavelength_m),
            )
            expected = float(
                np.exp(-((2.0 * np.pi * rms_m / wavelength_m) ** 2))
            )
            assert strehls[wavelength_m] == pytest.approx(expected, rel=0.02)
        assert strehls[2.0 * WAVELENGTH_M] > strehls[WAVELENGTH_M]


class TestNativeAgreement:
    def test_translated_sampling_reproduces_the_native_lattice_exactly(self):
        pupil = _pupil()
        sampling = PsfSampling(pad_factor=4)
        native = monochromatic_psf(
            _zero_opd(pupil),
            pupil,
            WAVELENGTH_M,
            backend="native",
            sampling=sampling,
        )
        adapted = monochromatic_psf(
            _zero_opd(pupil),
            pupil,
            WAVELENGTH_M,
            backend="hcipy",
            sampling=sampling,
        )
        assert adapted.backend_name == "hcipy"
        assert native.backend_name == "native"
        assert adapted.intensity.shape == native.intensity.shape
        axis_scale = float(np.max(np.abs(native.x_angle_rad)))
        for adapted_axis, native_axis in (
            (adapted.x_angle_rad, native.x_angle_rad),
            (adapted.y_angle_rad, native.y_angle_rad),
        ):
            assert np.allclose(
                adapted_axis,
                native_axis,
                rtol=0.0,
                atol=1.0e-12 * axis_scale,
            )
        peak = float(np.max(native.intensity))
        assert np.allclose(
            adapted.intensity,
            native.intensity,
            rtol=0.0,
            atol=1.0e-12 * peak,
        )

    def test_translated_lattice_stays_exact_with_aberrations_and_odd_padding(self):
        pupil = _pupil()
        opd = _astigmatism_opd(pupil, 70.0e-9)
        sampling = PsfSampling(pad_factor=3)
        native = monochromatic_psf(
            opd,
            pupil,
            WAVELENGTH_M,
            backend="native",
            sampling=sampling,
        )
        adapted = monochromatic_psf(
            opd,
            pupil,
            WAVELENGTH_M,
            backend="hcipy",
            sampling=sampling,
        )
        assert adapted.intensity.shape == native.intensity.shape
        peak = float(np.max(native.intensity))
        assert np.allclose(
            adapted.intensity,
            native.intensity,
            rtol=0.0,
            atol=1.0e-11 * peak,
        )

    def test_native_and_hcipy_strehl_agree_on_independent_grids(self):
        pupil = _pupil()
        opd = _astigmatism_opd(pupil, 60.0e-9)
        native = NativeSciencePropagator(
            pupil=pupil,
            sampling=PsfSampling(pad_factor=4),
        )
        adapted = HcipySciencePropagator(
            pupil,
            HcipyFocalSampling(5.0, 12.0),
        )
        native_strehl = peak_strehl_from_discrete_flux(
            native.psf_from_opd(opd, WAVELENGTH_M),
            native.psf_from_opd(_zero_opd(pupil), WAVELENGTH_M),
        )
        adapted_strehl = peak_strehl_from_discrete_flux(
            adapted.psf_from_opd(opd, WAVELENGTH_M),
            adapted.psf_from_opd(_zero_opd(pupil), WAVELENGTH_M),
        )
        assert 0.0 < adapted_strehl < 1.0
        assert abs(adapted_strehl - native_strehl) < 5.0e-3

    def test_flux_conserving_comparison_after_explicit_resampling(self):
        """Resample the HCIPy PSF onto the native angular lattice."""

        pupil = _pupil()
        native = NativeSciencePropagator(
            pupil=pupil,
            sampling=PsfSampling(pad_factor=4),
        ).psf_from_opd(_zero_opd(pupil), WAVELENGTH_M)
        adapted = HcipySciencePropagator(
            pupil,
            HcipyFocalSampling(5.0, 12.0),
        ).psf_from_opd(_zero_opd(pupil), WAVELENGTH_M)

        adapted_delta_rad = float(
            adapted.x_angle_rad[1] - adapted.x_angle_rad[0]
        )
        native_delta_rad = float(
            native.x_angle_rad[1] - native.x_angle_rad[0]
        )
        surface_brightness = RegularGridInterpolator(
            (adapted.y_angle_rad, adapted.x_angle_rad),
            adapted.intensity / adapted_delta_rad**2,
            method="cubic",
            bounds_error=False,
            fill_value=np.nan,
        )
        inside_x = (
            native.x_angle_rad > adapted.x_angle_rad[0] + adapted_delta_rad
        ) & (native.x_angle_rad < adapted.x_angle_rad[-1] - adapted_delta_rad)
        inside_y = (
            native.y_angle_rad > adapted.y_angle_rad[0] + adapted_delta_rad
        ) & (native.y_angle_rad < adapted.y_angle_rad[-1] - adapted_delta_rad)
        grid_x, grid_y = np.meshgrid(
            native.x_angle_rad[inside_x],
            native.y_angle_rad[inside_y],
            indexing="xy",
        )
        resampled_flux = (
            surface_brightness((grid_y, grid_x)) * native_delta_rad**2
        )
        assert np.all(np.isfinite(resampled_flux))

        # Flux conservation: the resampled flux matches the HCIPy flux held
        # inside the same angular window.
        source_x = (
            adapted.x_angle_rad >= native.x_angle_rad[inside_x][0]
        ) & (adapted.x_angle_rad <= native.x_angle_rad[inside_x][-1])
        source_y = (
            adapted.y_angle_rad >= native.y_angle_rad[inside_y][0]
        ) & (adapted.y_angle_rad <= native.y_angle_rad[inside_y][-1])
        source_flux = float(
            np.sum(adapted.intensity[np.ix_(source_y, source_x)])
        )
        assert float(np.sum(resampled_flux)) == pytest.approx(
            source_flux,
            rel=0.02,
        )

        # Pointwise agreement with the native PSF on the common grid after
        # renormalizing both to unit flux over that window.
        native_window = native.intensity[np.ix_(inside_y, inside_x)]
        renormalized_adapted = resampled_flux / float(np.sum(resampled_flux))
        renormalized_native = native_window / float(np.sum(native_window))
        peak = float(np.max(renormalized_native))
        assert np.allclose(
            renormalized_adapted,
            renormalized_native,
            rtol=0.0,
            atol=1.0e-3 * peak,
        )


class TestSameMetricsInterface:
    """Science metrics consume native and HCIPy PSFs identically."""

    def test_scalar_metrics_accept_hcipy_psfs(self):
        pupil = _pupil()
        propagator = _propagator(pupil)
        opd = _astigmatism_opd(pupil, 60.0e-9)
        metrics = psf_scalar_metrics(
            propagator.psf_from_opd(opd, WAVELENGTH_M),
            propagator.psf_from_opd(_zero_opd(pupil), WAVELENGTH_M),
            opd,
            pupil,
            DIAMETER_M,
        )
        assert 0.0 < metrics.peak_strehl < 1.0

    def test_encircled_energy_accepts_hcipy_psfs(self):
        pupil = _pupil()
        psf = _propagator(pupil).psf_from_opd(_zero_opd(pupil), WAVELENGTH_M)
        radius_rad = encircled_energy_radius_from_discrete_flux(
            psf.intensity,
            psf.x_angle_rad,
            psf.y_angle_rad,
            0.5,
        )
        # EE50 of an Airy pattern sits inside the first dark ring.
        assert 0.0 < radius_rad < 1.22 * WAVELENGTH_M / DIAMETER_M

    def test_registry_serves_both_backends_through_one_call(self):
        pupil = _pupil()
        sampling = PsfSampling(pad_factor=2)
        for backend in ("native", "hcipy"):
            psf = monochromatic_psf(
                _zero_opd(pupil),
                pupil,
                WAVELENGTH_M,
                backend=backend,
                sampling=sampling,
            )
            assert psf.backend_name == backend
            assert float(np.sum(psf.intensity)) == pytest.approx(
                1.0,
                abs=1.0e-12,
            )


class TestValidation:
    def test_construction_rejects_invalid_repository_inputs(self):
        with pytest.raises(HcipySciencePropagationError, match="PupilGeometry"):
            HcipySciencePropagator(object())
        with pytest.raises(
            HcipySciencePropagationError,
            match="HcipyFocalSampling",
        ):
            HcipySciencePropagator(_pupil(), sampling=PsfSampling())

    def test_focal_sampling_is_validated(self):
        with pytest.raises(
            HcipySciencePropagationError,
            match="pixels_per_resolution_element",
        ):
            HcipyFocalSampling(pixels_per_resolution_element=0.0)
        with pytest.raises(
            HcipySciencePropagationError,
            match="radius_resolution_elements",
        ):
            HcipyFocalSampling(radius_resolution_elements=-1.0)
        with pytest.raises(
            HcipySciencePropagationError,
            match="at least two pixels",
        ):
            HcipyFocalSampling(0.4, 1.0)

    def test_opd_and_wavelength_are_validated(self):
        pupil = _pupil()
        propagator = _propagator(pupil)
        with pytest.raises(HcipySciencePropagationError, match="numpy.ndarray"):
            propagator.psf_from_opd([[0.0]], WAVELENGTH_M)
        with pytest.raises(HcipySciencePropagationError, match="shape"):
            propagator.psf_from_opd(np.zeros((8, 8)), WAVELENGTH_M)
        with pytest.raises(HcipySciencePropagationError, match="infinite"):
            propagator.psf_from_opd(
                np.full(pupil.pupil_shape, np.inf),
                WAVELENGTH_M,
            )
        interior_nan = np.zeros(pupil.pupil_shape)
        interior_nan[pupil.pupil_mask] = np.nan
        with pytest.raises(HcipySciencePropagationError, match="finite"):
            propagator.psf_from_opd(interior_nan, WAVELENGTH_M)
        with pytest.raises(HcipySciencePropagationError, match="wavelength_m"):
            propagator.psf_from_opd(_zero_opd(pupil), 0.0)

    def test_translation_helper_requires_square_pupil_sampling(self):
        rectangular = build_pupil_geometry(
            telescope_diameter_m=DIAMETER_M,
            pupil_shape=(32, 64),
        )
        with pytest.raises(HcipySciencePropagationError, match="square"):
            focal_sampling_from_psf_sampling(rectangular, PsfSampling())
        with pytest.raises(HcipySciencePropagationError, match="PsfSampling"):
            focal_sampling_from_psf_sampling(_pupil(), object())

    def test_nan_outside_the_pupil_is_accepted(self):
        pupil = _pupil()
        propagator = _propagator(pupil)
        masked = np.where(pupil.pupil_mask, 0.0, np.nan)
        reference = propagator.psf_from_opd(_zero_opd(pupil), WAVELENGTH_M)
        result = propagator.psf_from_opd(masked, WAVELENGTH_M)
        assert np.array_equal(result.intensity, reference.intensity)


def _plain_json(value):
    """Recursively convert immutable mappings/tuples to JSON-native types."""

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "keys"):
        return {str(key): _plain_json(value[key]) for key in value.keys()}
    if isinstance(value, (tuple, list)):
        return [_plain_json(item) for item in value]
    raise AssertionError(
        f"metadata contains a non-JSON-serializable value of type {type(value)!r}"
    )
