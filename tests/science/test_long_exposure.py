"""ESO-03: streaming long-exposure images and final-image metrics.

Expected values are independent of the accumulator: a separately materialized
stack of instantaneous intensities, the DFT shift theorem for integer-pixel
tilts, phase-piston invariance of intensity, and the analytic Fraunhofer
pattern of an annular aperture.
"""

from __future__ import annotations

from dataclasses import replace
import math

import numpy as np
import pytest
from scipy.special import j1

from shwfs_ao.backends.native.propagation import NativeSciencePropagator
from shwfs_ao.core.geometry import build_pupil_geometry
from shwfs_ao.experiments import scao
from shwfs_ao.io.configs import load_system_profile
from shwfs_ao.science.long_exposure import (
    FLUX_DENOMINATOR,
    LongExposureConfig,
    LongExposureError,
    StreamingLongExposure,
)
from shwfs_ao.science.metrics import peak_strehl_from_discrete_flux
from shwfs_ao.science.propagation import PsfSampling, SciencePropagationError


WAVELENGTH_M = 2.2e-6
DT = 0.002


def _propagator(n: int = 48, *, pad: int = 2, obstruction: float = 0.28, d: float = 8.0):
    pupil = build_pupil_geometry(
        telescope_diameter_m=d,
        pupil_shape=(n, n),
        central_obstruction_ratio=obstruction,
    )
    return NativeSciencePropagator(pupil=pupil, sampling=PsfSampling(pad_factor=pad))


def _feed(accumulator, maps, *, start=0):
    for offset, opd in enumerate(maps):
        frame = start + offset
        accumulator.add_opd(opd, frame_index=frame, time_s=frame * DT, frame_period_s=DT)


def _masked(propagator, values):
    opd = np.array(values, dtype=float)
    opd[~propagator.pupil.pupil_mask] = np.nan
    return opd


def _aberration(propagator, seed=0, rms_m=150e-9):
    pupil = propagator.pupil
    x = 2.0 * pupil.x_m / pupil.telescope_diameter_m
    y = 2.0 * pupil.y_m / pupil.telescope_diameter_m
    rng = np.random.default_rng(seed)
    coefficients = rng.normal(size=6)
    raw = (
        coefficients[0] * (x * x - y * y)
        + coefficients[1] * x * y
        + coefficients[2] * (2 * (x * x + y * y) - 1)
        + coefficients[3] * x * (x * x + y * y)
        + coefficients[4] * y
        + coefficients[5] * x**3
    )
    inside = pupil.pupil_mask
    raw = raw - raw[inside].mean()
    raw *= rms_m / raw[inside].std()
    return _masked(propagator, raw)


def _tilt(propagator, pixels: float, wavelength=WAVELENGTH_M):
    """OPD that shifts the image by exactly ``pixels`` focal pixels along x."""

    pupil = propagator.pupil
    rows, columns = pupil.pupil_shape
    padded = propagator.sampling.pad_factor * columns
    dx = pupil.pixel_spacing_xy_m[0]
    slope = pixels * wavelength / (padded * dx)
    return _masked(propagator, slope * (pupil.x_m - pupil.x_m[0, 0]))


def _accumulator(propagator, **overrides):
    values = {"wavelengths_m": (WAVELENGTH_M,), "burn_in_frames": 0}
    values.update(overrides)
    return StreamingLongExposure(
        propagator, LongExposureConfig(**values), telescope_diameter_m=8.0
    )


def test_repeated_static_opd_equals_one_propagation_and_zero_opd_is_ideal():
    propagator = _propagator()
    opd = _aberration(propagator)
    accumulator = _accumulator(propagator)
    _feed(accumulator, [opd] * 7)
    image = accumulator.result().images[0]
    single = propagator.psf_from_opd(opd, WAVELENGTH_M)
    np.testing.assert_allclose(image.psf.intensity, single.intensity, rtol=1e-11, atol=1e-14)

    ideal = _accumulator(propagator)
    _feed(ideal, [_masked(propagator, np.zeros(propagator.pupil.pupil_shape))] * 3)
    ideal_image = ideal.result().images[0]
    assert ideal_image.metrics.peak_strehl == pytest.approx(1.0, abs=1e-12)
    assert ideal_image.metrics.on_axis_strehl == pytest.approx(1.0, abs=1e-12)
    np.testing.assert_allclose(
        ideal_image.psf.intensity, ideal_image.ideal_psf.intensity, rtol=1e-11, atol=1e-14
    )


def test_opposite_tilts_broaden_the_image_instead_of_cancelling():
    propagator = _propagator()
    shift = 3
    left, right = _tilt(propagator, -shift), _tilt(propagator, shift)
    accumulator = _accumulator(propagator)
    _feed(accumulator, [left, right] * 4)
    image = accumulator.result().images[0]

    # The mean OPD is a flat wavefront; propagating it would give Strehl 1.
    mean_opd = 0.5 * (left + right)
    mean_psf = propagator.psf_from_opd(mean_opd, WAVELENGTH_M)
    assert peak_strehl_from_discrete_flux(mean_psf, image.ideal_psf) == pytest.approx(1.0, abs=1e-6)
    # Intensity averaging leaves two half-height peaks 2*shift pixels apart;
    # per-frame recentring would also have given Strehl 1.
    assert 0.49 < image.metrics.peak_strehl < 0.52
    columns = np.flatnonzero(
        image.psf.intensity.max(axis=0) > 0.45 * image.ideal_psf.intensity.max()
    )
    axis = image.psf.x_angle_rad
    centre = int(np.argmin(np.abs(axis)))
    assert set(columns - centre) == {-shift, shift}
    # Final-image metrics differ from the mean of instantaneous metrics.
    instantaneous = [
        peak_strehl_from_discrete_flux(propagator.psf_from_opd(m, WAVELENGTH_M), image.ideal_psf)
        for m in (left, right)
    ]
    assert np.mean(instantaneous) == pytest.approx(1.0, abs=1e-9)
    assert image.metrics.peak_strehl < 0.6 * np.mean(instantaneous)
    assert image.metrics.fwhm_rad > image.metrics.ideal_fwhm_rad


def test_piston_does_not_change_an_intensity_average():
    propagator = _propagator()
    base = _aberration(propagator, seed=4)
    accumulator = _accumulator(propagator)
    _feed(accumulator, [base + piston for piston in (0.0, 1.3e-7, -3.7e-8, 5.0e-6)])
    single = propagator.psf_from_opd(base, WAVELENGTH_M)
    np.testing.assert_allclose(
        accumulator.result().images[0].psf.intensity, single.intensity, rtol=1e-10, atol=1e-14
    )


def test_streaming_average_matches_a_materialized_weighted_stack():
    propagator = _propagator()
    maps = [_aberration(propagator, seed=seed, rms_m=250e-9) for seed in range(6)]
    weights = (0.5, 1.0, 1.0, 2.0, 0.0, 1.25)
    wavelengths = (1.65e-6, WAVELENGTH_M)
    accumulator = StreamingLongExposure(
        propagator,
        LongExposureConfig(
            wavelengths_m=wavelengths,
            burn_in_frames=2,
            max_samples=6,
            sample_weights=weights,
        ),
        telescope_diameter_m=8.0,
    )
    _feed(accumulator, [maps[0], maps[1]] + maps, start=0)
    result = accumulator.result()
    for image, wavelength in zip(result.images, wavelengths, strict=True):
        stack = np.stack([propagator.psf_from_opd(m, wavelength).intensity for m in maps])
        expected = np.tensordot(np.asarray(weights), stack, axes=1) / sum(weights)
        np.testing.assert_allclose(image.psf.intensity, expected, rtol=1e-11, atol=1e-14)
        assert image.psf.wavelength_m == wavelength
        assert math.isclose(float(image.psf.intensity.sum()), 1.0, rel_tol=1e-12)
    assert result.selection.first_frame == 2
    assert result.selection.weight_sum == pytest.approx(sum(weights))
    assert not result.selection.uniform_weights


def test_selection_burn_in_stride_timing_and_quadrature_record():
    propagator = _propagator(32)
    accumulator = _accumulator(propagator, burn_in_frames=3, stride=2, max_samples=4)
    opd = _aberration(propagator)
    _feed(accumulator, [opd] * 20)
    selection = accumulator.result().selection
    assert (selection.first_frame, selection.last_frame) == (3, 9)
    assert selection.sample_count == 4
    assert selection.first_time_s == pytest.approx(3 * DT)
    assert selection.last_time_s == pytest.approx(9 * DT)
    assert selection.sample_interval_s == pytest.approx(2 * DT)
    assert selection.quadrature_exposure_s == pytest.approx(4 * 2 * DT)
    assert selection.sample_center_span_s == pytest.approx(3 * 2 * DT)
    assert selection.residual == "pre_update"
    assert accumulator.result().to_record()["flux_denominator"] == FLUX_DENOMINATOR


def test_empty_selection_invalid_weights_and_bad_frames_fail_explicitly():
    propagator = _propagator(32)
    late = _accumulator(propagator, burn_in_frames=50)
    _feed(late, [_aberration(propagator)] * 5)
    with pytest.raises(LongExposureError, match="no frame was selected"):
        late.result()
    for weights, max_samples in (
        ((1.0, float("nan")), 2),
        ((1.0, -1.0), 2),
        ((0.0, 0.0), 2),
        ((1.0, 1.0), 3),
    ):
        with pytest.raises(LongExposureError):
            LongExposureConfig(
                wavelengths_m=(WAVELENGTH_M,),
                burn_in_frames=0,
                max_samples=max_samples,
                sample_weights=weights,
            )
    with pytest.raises(LongExposureError):
        LongExposureConfig(wavelengths_m=(2e-6, 1e-6), burn_in_frames=0)
    with pytest.raises(LongExposureError):
        LongExposureConfig(wavelengths_m=(2e-6,), burn_in_frames=0, residual="mean")

    accumulator = _accumulator(propagator)
    good = _aberration(propagator)
    _feed(accumulator, [good])
    corrupt = good.copy()
    corrupt[propagator.pupil.pupil_mask.nonzero()[0][0], propagator.pupil.pupil_mask.nonzero()[1][0]] = np.nan
    with pytest.raises(SciencePropagationError):
        accumulator.add_opd(corrupt, frame_index=1, time_s=DT, frame_period_s=DT)
    assert accumulator.sample_count == 1
    with pytest.raises(LongExposureError, match="in order"):
        accumulator.add_opd(good, frame_index=5, time_s=5 * DT, frame_period_s=DT)


def test_reset_allows_reuse_and_is_recorded():
    propagator = _propagator(32)
    maps = [_aberration(propagator, seed=seed) for seed in range(3)]
    reused = _accumulator(propagator)
    _feed(reused, [_tilt(propagator, 4)] * 2)
    reused.reset()
    _feed(reused, maps)
    fresh = _accumulator(propagator)
    _feed(fresh, maps)
    np.testing.assert_array_equal(
        reused.result().images[0].psf.intensity, fresh.result().images[0].psf.intensity
    )
    assert reused.result().reset_count == 1 and fresh.result().reset_count == 0


def test_retained_memory_does_not_grow_with_the_number_of_frames():
    propagator = _propagator(32)
    opd = _aberration(propagator)
    accumulator = _accumulator(propagator)
    _feed(accumulator, [opd] * 3)
    accumulator.result()
    after_three = accumulator.retained_array_nbytes()
    state_three = {key: type(value) for key, value in vars(accumulator).items()}
    _feed(accumulator, [opd] * 40, start=3)
    accumulator.result()
    assert accumulator.retained_array_nbytes() == after_three
    assert {key: type(value) for key, value in vars(accumulator).items()} == state_three
    assert all(
        not isinstance(value, list) or len(value) <= 1 for value in vars(accumulator).values()
    )


def _annulus_profile(theta, wavelength, diameter, epsilon):
    """Analytic peak-normalized Fraunhofer pattern of an annular aperture."""

    x = np.pi * diameter * np.asarray(theta) / wavelength
    with np.errstate(invalid="ignore", divide="ignore"):
        airy = np.where(x == 0.0, 1.0, 2.0 * j1(x) / x)
        inner = np.where(x == 0.0, 1.0, 2.0 * j1(epsilon * x) / (epsilon * x))
    return ((airy - epsilon**2 * inner) / (1.0 - epsilon**2)) ** 2


def test_ideal_image_matches_the_analytic_annular_pattern_and_converges():
    """Independent check of angular scale, normalization, and core shape.

    Normalization: a unit-flux image's peak surface brightness is exactly
    ``A_sampled / lambda**2`` (Parseval), and the sampled annulus area tends to
    ``pi D**2 (1 - eps**2) / 4``.  Shape: inside 2 lambda/D the
    peak-normalized image matches the analytic annulus pattern; the staircase
    pupil edge makes the error fall non-monotonically, so the gate is a
    coarse-to-fine ratio, not strict monotonicity (measured 3.4e-3, 6.4e-4,
    2.5e-4 at 48, 96, 256 pixels).
    """

    shape_errors = []
    area_errors = []
    for n in (48, 96, 256):
        propagator = _propagator(n, pad=2, obstruction=0.28)
        accumulator = _accumulator(propagator)
        _feed(accumulator, [_masked(propagator, np.zeros((n, n)))])
        ideal = accumulator.result().images[0].ideal_psf
        x, y = np.meshgrid(ideal.x_angle_rad, ideal.y_angle_rad)
        theta = np.hypot(x, y)
        dx = ideal.x_angle_rad[1] - ideal.x_angle_rad[0]
        dy = ideal.y_angle_rad[1] - ideal.y_angle_rad[0]
        # Angular scale: lambda / (pad * N * dx) with dx = D / (N - 1).
        assert dx == pytest.approx(WAVELENGTH_M / (2 * n * 8.0 / (n - 1)), rel=1e-12)
        brightness = ideal.intensity / (dx * dy)
        pupil = propagator.pupil
        sampled_area = pupil.pupil_mask.sum() * pupil.pixel_spacing_xy_m[0] ** 2
        assert brightness.max() == pytest.approx(sampled_area / WAVELENGTH_M**2, rel=1e-12)
        area_errors.append(abs(sampled_area / (math.pi / 4 * 64.0 * (1 - 0.28**2)) - 1))
        core = theta <= 2.0 * WAVELENGTH_M / 8.0
        expected = _annulus_profile(theta[core], WAVELENGTH_M, 8.0, 0.28)
        shape_errors.append(
            float(np.max(np.abs(brightness[core] / brightness.max() - expected)))
        )
    assert max(shape_errors) < 5e-3
    assert shape_errors[-1] < shape_errors[0] / 5.0
    assert area_errors[0] < 0.015 and area_errors[-1] < 1e-3


def test_accumulator_runs_inside_the_canonical_loop_without_changing_control():
    config = load_system_profile("eso_turbulence_2m_detector", 1)
    config = replace(config, controller=replace(config.controller, n_steps=12))
    system = scao.build_scao_system(config)
    accumulator = StreamingLongExposure(
        system.science_propagator,
        LongExposureConfig(wavelengths_m=(1.65e-6, 2.2e-6), burn_in_frames=4),
        telescope_diameter_m=config.telescope_diameter_m,
    )
    baseline = scao.run_closed_loop(config, system=system)
    observed = scao.run_closed_loop(config, system=system, observers=(accumulator,))
    assert observed.config_hash == baseline.config_hash
    np.testing.assert_array_equal(
        observed.applied_command_history_opd_m, baseline.applied_command_history_opd_m
    )
    result = accumulator.result()
    assert result.selection.sample_count == 8
    assert result.selection.first_frame == 4
    for image in result.images:
        assert 0.0 < image.metrics.peak_strehl <= 1.0
        assert np.isfinite(image.metrics.ee50_radius_rad)
        assert image.radial_profile.shape == image.radial_radius_rad.shape
    # Longer wavelength corrects better in Strehl.
    assert result.images[1].metrics.peak_strehl > result.images[0].metrics.peak_strehl
