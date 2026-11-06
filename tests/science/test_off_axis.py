"""Off-axis science: offsets, the shared observer, the entry point and the loop contract."""

from __future__ import annotations

from dataclasses import replace
import math
from types import SimpleNamespace

import numpy as np
import pytest

from shwfs_ao.backends.native.propagation import NativeSciencePropagator
from shwfs_ao.control.loop import ControlLoopError
from shwfs_ao.core.geometry import build_pupil_geometry
from shwfs_ao.experiments import (
    DOCUMENTED_LAYERED_PROFILES,
    ExposureOverride,
    build_scao_system,
    check_off_axis_support,
    layered_profiles,
    run_closed_loop,
    run_off_axis_science,
)
from shwfs_ao.io.configs import load_system_profile
from shwfs_ao.science import (
    ARCSEC_TO_RAD,
    LongExposureConfig,
    OffAxisLongExposure,
    OffAxisScienceError,
    PsfSampling,
    ScienceOffset,
    StreamingLongExposure,
    footprint_report,
    science_offsets,
)
from shwfs_ao.science._psf_peak import interpolated_peak


HISTORY_FIELDS = (
    "open_loop_opd_rms_m",
    "pre_update_residual_opd_rms_m",
    "post_update_residual_opd_rms_m",
    "requested_command_history_opd_m",
    "applied_command_history_opd_m",
    "measurement_row_masks",
    "reconstruction_usable",
)


def _layered_config(n_steps: int = 12):
    config = load_system_profile("eso_turbulence_2m_detector", 1)
    return replace(config, controller=replace(config.controller, n_steps=n_steps))


@pytest.fixture(scope="module")
def layered_system():
    config = _layered_config()
    return config, build_scao_system(config)


def _assert_same_history(first, second) -> None:
    assert first.config_hash == second.config_hash
    for name in HISTORY_FIELDS:
        np.testing.assert_array_equal(getattr(first, name), getattr(second, name), err_msg=name)


# -- offsets ------------------------------------------------------------------


def test_offsets_convert_arcseconds_to_radians_and_default_to_the_guide_star() -> None:
    assert ARCSEC_TO_RAD == pytest.approx(math.pi / 648000.0)
    offset = ScienceOffset(5.0, -2.0)
    assert offset.radians == (5.0 * ARCSEC_TO_RAD, -2.0 * ARCSEC_TO_RAD)
    assert offset.radial_arcsec == pytest.approx(math.hypot(5.0, 2.0))
    assert science_offsets(None) == (ScienceOffset(0.0, 0.0),)
    assert science_offsets([]) == (ScienceOffset(0.0, 0.0),)
    assert science_offsets([(1, 2), ScienceOffset(0, 0)]) == (ScienceOffset(1.0, 2.0), ScienceOffset(0.0, 0.0))
    with pytest.raises(OffAxisScienceError, match="repeats"):
        science_offsets([(1, 2), (1.0, 2.0)])
    with pytest.raises(OffAxisScienceError, match="finite"):
        ScienceOffset(math.inf, 0.0)


# -- loop contract --------------------------------------------------------------


def test_science_directions_leave_the_guide_star_loop_unchanged(layered_system) -> None:
    config, system = layered_system
    bare = run_closed_loop(config, system=system)
    orders = (
        [(0.0, 0.0), (10.0, 0.0), (0.0, -10.0)],
        [(0.0, -10.0), (10.0, 0.0), (0.0, 0.0)],
        [(10.0, 0.0)],
    )
    results = {}
    for offsets in orders:
        run = run_off_axis_science(
            config, offsets_arcsec=offsets, wavelengths_m=(1.65e-6,), burn_in_frames=4, system=system
        )
        _assert_same_history(run.history, bare)
        for image in run.science.images:
            results.setdefault(image.offset, []).append(image)
    # The same offset gives the same image whatever else was sampled.
    for offset, images in results.items():
        for image in images[1:]:
            np.testing.assert_array_equal(image.psf.intensity, images[0].psf.intensity)
            assert image.peak_strehl == images[0].peak_strehl
    assert len(results[ScienceOffset(10.0, 0.0)]) == 3


def test_the_explicit_zero_offset_reproduces_the_on_axis_long_exposure(layered_system) -> None:
    config, system = layered_system
    accumulator = StreamingLongExposure(
        system.science_propagator,
        LongExposureConfig(wavelengths_m=(1.65e-6,), burn_in_frames=4),
        telescope_diameter_m=config.telescope_diameter_m,
    )
    history = run_closed_loop(config, system=system, observers=(accumulator,))
    reference = accumulator.result().image(1.65e-6)
    for offsets in (None, [(0.0, 0.0)], [(20.0, 5.0), (0.0, 0.0)]):
        run = run_off_axis_science(
            config, offsets_arcsec=offsets, wavelengths_m=(1.65e-6,), burn_in_frames=4, system=system
        )
        _assert_same_history(run.history, history)
        image = run.science.image((0.0, 0.0), 1.65e-6)
        np.testing.assert_array_equal(image.psf.intensity, reference.psf.intensity)
        assert image.peak_strehl == reference.metrics.peak_strehl
        assert run.science.max_on_axis_difference_m == 0.0
        assert run.science.selection.sample_count == accumulator.sample_count


def _layered_detector_physics_config(n_steps: int = 6):
    """The detector-physics 2 m profile driven by the ESO ten-layer atmosphere."""

    base = load_system_profile("det_ccd_2m_synthetic", 1)
    layered = load_system_profile("eso_turbulence_2m_detector", 1)
    return replace(
        base,
        atmosphere_model="native_layered",
        atmosphere=replace(
            base.atmosphere, layers=layered.atmosphere.layers, wind_m_per_s=(0.0, 0.0)
        ),
        controller=replace(base.controller, n_steps=n_steps),
    )


def test_directions_are_neutral_under_exposure_subsampling() -> None:
    config = _layered_detector_physics_config()
    system = build_scao_system(config)
    exposure = ExposureOverride(subsamples=3)
    bare = run_closed_loop(config, system=system, exposure=exposure)
    assert bare.metadata["wfs_exposure"]["subsamples"] == 3
    run = run_off_axis_science(
        config,
        offsets_arcsec=[(0.0, 0.0), (15.0, -5.0)],
        wavelengths_m=(1.65e-6,),
        burn_in_frames=4,
        system=system,
        exposure=exposure,
    )
    _assert_same_history(run.history, bare)
    assert run.science.max_on_axis_difference_m == 0.0
    midpoint = ExposureOverride(subsamples=2, sample_rule="midpoint")
    bare_mid = run_closed_loop(config, system=system, exposure=midpoint)
    run_mid = run_off_axis_science(
        config, offsets_arcsec=[(0.0, 0.0), (15.0, -5.0)], wavelengths_m=(1.65e-6,),
        burn_in_frames=4, system=system, exposure=midpoint,
    )
    _assert_same_history(run_mid.history, bare_mid)
    assert run_mid.science.max_on_axis_difference_m == 0.0


def test_the_observer_checks_its_directions_and_fields(layered_system) -> None:
    config, system = layered_system
    observer = OffAxisLongExposure(
        system.science_propagator,
        [(0.0, 0.0), (5.0, 0.0)],
        LongExposureConfig(wavelengths_m=(1.65e-6,), burn_in_frames=0),
        telescope_diameter_m=config.telescope_diameter_m,
    )
    assert observer.requested_fields == frozenset({"science_residual_opd_m", "pre_update_residual_opd_m"})
    with pytest.raises(ControlLoopError, match="science_directions_rad must equal"):
        run_closed_loop(config, system=system, observers=(observer,), science_directions_rad=[(0.0, 0.0)])
    # Without directions the loop hands the observer no directions at all.
    observer.reset()
    with pytest.raises(ControlLoopError, match="science_directions_rad must equal"):
        run_closed_loop(config, system=system, observers=(observer,))
    with pytest.raises(OffAxisScienceError, match="pre-update"):
        OffAxisLongExposure(
            system.science_propagator, None,
            LongExposureConfig(wavelengths_m=(1.65e-6,), burn_in_frames=0, residual="post_update"),
            telescope_diameter_m=config.telescope_diameter_m,
        )


def test_block_strehl_and_instantaneous_strehl_are_separate_statistics(layered_system) -> None:
    config, system = layered_system
    run = run_off_axis_science(
        config, offsets_arcsec=[(8.0, 0.0)], wavelengths_m=(1.65e-6,), burn_in_frames=2,
        system=system, block_frames=5,
    )
    image = run.science.image((8.0, 0.0), 1.65e-6)
    assert image.sample_count == 10
    assert image.instantaneous_strehl.shape == (10,)
    assert image.mean_instantaneous_strehl == pytest.approx(float(np.mean(image.instantaneous_strehl)))
    assert image.block_peak_strehl.shape == (2,)
    # The accumulated image's peak cannot exceed the mean of instantaneous peaks.
    assert image.peak_strehl <= image.mean_instantaneous_strehl + 1e-12
    rows = run.science.table_rows()
    assert rows[0]["averaged_frames"] == 10 and rows[0]["radial_arcsec"] == 8.0
    assert math.isclose(float(np.sum(image.psf.intensity)), 1.0, rel_tol=1e-9)


def test_subpixel_tilt_preserves_the_long_exposure_peak_across_padding() -> None:
    # A pupil phase ramp translates the ideal PSF and preserves its true peak.
    n = 32
    wavelength = 1.65e-6
    pupil = build_pupil_geometry(telescope_diameter_m=2.2, pupil_shape=(n, n))
    dx, dy = pupil.pixel_spacing_xy_m
    opd = wavelength * (0.48 * pupil.x_m / dx + 0.35 * pupil.y_m / dy) / (3 * n)
    sampled = {}
    for pad in (1, 3, 6):
        propagator = NativeSciencePropagator(pupil=pupil, sampling=PsfSampling(pad_factor=pad))
        observer = OffAxisLongExposure(
            propagator, None, LongExposureConfig(wavelengths_m=(wavelength,), burn_in_frames=0),
            telescope_diameter_m=2.2,
        )
        observer.observe(SimpleNamespace(
            frame_index=0, time_s=0.0, frame_period_s=0.001,
            science_directions_rad=observer.directions_rad, science_residual_opd_m=(opd,),
            pre_update_residual_opd_m=opd,
        ))
        result = observer.result()
        image = result.image((0.0, 0.0), wavelength)
        sampled[pad] = image.peak_strehl
        assert image.peak_strehl == pytest.approx(image.psf.intensity.max() / image.ideal_psf.intensity.max())
        assert image.mean_instantaneous_strehl == pytest.approx(image.peak_strehl)
        for row in (result.table_rows()[0], result.to_record()["images"][0]):
            assert row["long_exposure_peak_strehl"] == image.peak_strehl
            assert row["long_exposure_interpolated_peak_strehl"] == image.interpolated_peak_strehl
        if pad == 1:
            assert image.interpolated_peak_strehl is None
        else:
            assert image.interpolated_peak_strehl == pytest.approx(1.0, abs=5e-5)
    assert sampled[6] - sampled[3] > 0.01


def test_peak_search_finds_a_brighter_core_between_samples_at_the_field_edge() -> None:
    # Two incoherent point sources with analytic, periodic square-pupil PSFs.
    n = 64

    def core(delta):
        return (np.sinc(19 * delta / n) / np.sinc(delta / n)) ** 2

    def intensity(y, x):
        return 0.98 * core(y - 27) * core(x - 24) + core(y + 0.5) * core(x + 0.5)

    y, x = np.ogrid[:n, :n]
    image = intensity(y, x)
    assert np.unravel_index(image.argmax(), image.shape) == (27, 24)
    peak, (dy, dx) = interpolated_peak(image)
    assert peak >= intensity(-0.5, -0.5) - 1e-12
    assert peak == pytest.approx(intensity(27 + dy, 24 + dx), abs=1e-12)
    assert peak - image.max() > 0.01


def _direct_focal_intensity(field: np.ndarray, pupil, wavelength: float,
                            x_angle_rad: np.ndarray, y_angle_rad: np.ndarray, size: int) -> np.ndarray:
    """|DFT of the pupil field|^2 at arbitrary angles, in the unit-flux normalization.

    Parseval on the ``size x size`` padded transform gives a total flux of
    ``size**2 * sum |field|**2``; dividing by it makes the value at a sample
    equal to the propagator's unit-flux intensity, and the value between
    samples the trigonometric interpolant of the image.
    """

    kx = np.exp(-2j * np.pi * np.outer(x_angle_rad, pupil.x_m[0, :]) / wavelength)
    ky = np.exp(-2j * np.pi * np.outer(y_angle_rad, pupil.y_m[:, 0]) / wavelength)
    amplitude = ky @ field @ kx.T
    return np.abs(amplitude) ** 2 / (size**2 * np.sum(np.abs(field) ** 2))


@pytest.mark.parametrize("pad", [3, 6])
def test_a_brighter_core_between_samples_beats_a_fainter_on_grid_core(pad: int) -> None:
    # Two incoherent copies of the 2.2 m pupil PSF: core A a quarter pad-3
    # pixel off grid in both axes, core B on grid twelve pad-3 pixels away
    # with relative weight 0.975. The brightest sample belongs to the fainter
    # core B, so an estimator that refines only the brightest sample reads
    # core A low at pad 3 (and is right at pad 6 only because a quarter pad-3
    # pixel is half a pad-6 pixel). The reference is direct DFT propagation
    # of the pupil fields onto a 1/32-pixel focal grid, independent of the
    # estimator and of the FFT propagator.
    n, wavelength, weight = 256, 1.65e-6, 0.975
    pupil = build_pupil_geometry(telescope_diameter_m=2.2, pupil_shape=(n, n))
    dx, dy = pupil.pixel_spacing_xy_m
    propagator = NativeSciencePropagator(pupil=pupil, sampling=PsfSampling(pad_factor=pad))
    pixels_a = (0.25 * pad / 3, 0.25 * pad / 3)
    pixels_b = (12 * pad / 3, 0.0)
    opd = {
        tag: wavelength * (px * pupil.x_m / dx + py * pupil.y_m / dy) / (pad * n)
        for tag, (px, py) in (("a", pixels_a), ("b", pixels_b))
    }
    psf = {tag: propagator.psf_from_opd(value, wavelength) for tag, value in opd.items()}
    ideal = propagator.psf_from_opd(np.zeros((n, n)), wavelength)
    combined = (psf["a"].intensity + weight * psf["b"].intensity) / (1.0 + weight)
    size = ideal.intensity.shape[0]
    mask = pupil.pupil_mask.astype(float)
    fields = {tag: mask * np.exp(2j * np.pi * value / wavelength) for tag, value in opd.items()}
    # The direct propagation reproduces the sampled images, so its
    # normalization is the propagator's.
    row, col = np.unravel_index(int(np.argmax(ideal.intensity)), ideal.intensity.shape)
    assert np.isclose(
        _direct_focal_intensity(mask, pupil, wavelength, ideal.x_angle_rad[[col]],
                                ideal.y_angle_rad[[row]], size)[0, 0],
        ideal.intensity[row, col], rtol=1e-12,
    )
    # Fine grid (1/32 pixel) around core A's nominal position.
    pixel = float(ideal.x_angle_rad[1] - ideal.x_angle_rad[0])
    fine = np.arange(-16, 17) / 32.0 * pixel
    x_fine = ideal.x_angle_rad[col] + pixels_a[0] * pixel + fine
    y_fine = ideal.y_angle_rad[row] + pixels_a[1] * pixel + fine
    direct = sum(
        w * _direct_focal_intensity(fields[tag], pupil, wavelength, x_fine, y_fine, size)
        for tag, w in (("a", 1.0), ("b", weight))
    ) / (1.0 + weight)
    reference = float(np.max(direct)) / float(np.max(ideal.intensity))
    assert reference == pytest.approx(0.50687, abs=5e-5)
    # The brightest sample is core B's, and it is fainter than core A's true peak.
    sampled = float(np.max(combined)) / float(np.max(ideal.intensity))
    brightest = np.unravel_index(int(np.argmax(combined)), combined.shape)
    assert brightest[1] - col == pytest.approx(pixels_b[0]) and brightest[0] == row
    assert sampled < reference
    if pad == 3:
        assert sampled == pytest.approx(0.49422, abs=5e-5)
    estimate = interpolated_peak(combined)[0] / interpolated_peak(ideal.intensity)[0]
    assert estimate == pytest.approx(reference, abs=1e-9)


# -- backend contract -------------------------------------------------------------


def test_non_layered_profiles_keep_on_axis_behaviour_and_refuse_offsets() -> None:
    config = load_system_profile("det_ccd_2m_synthetic", 1)
    config = replace(config, controller=replace(config.controller, n_steps=4))
    assert config.atmosphere_model != "native_layered"
    assert check_off_axis_support(config, None) == (ScienceOffset(0.0, 0.0),)
    with pytest.raises(OffAxisScienceError, match="robo_ao2_22m_ngs_draft@2"):
        check_off_axis_support(config, [(0.0, 0.0), (5.0, 0.0)])
    system = build_scao_system(config)
    bare = run_closed_loop(config, system=system)
    run = run_off_axis_science(config, wavelengths_m=(1.65e-6,), burn_in_frames=1, system=system)
    _assert_same_history(run.history, bare)
    assert run.science.max_on_axis_difference_m == 0.0
    assert run.footprint["offsets"] == []
    # The canonical loop itself refuses a nonzero direction on such a backend.
    observer = OffAxisLongExposure(
        system.science_propagator, [(5.0, 0.0)],
        LongExposureConfig(wavelengths_m=(1.65e-6,), burn_in_frames=0),
        telescope_diameter_m=config.telescope_diameter_m,
    )
    with pytest.raises(ControlLoopError, match="native_layered"):
        run_closed_loop(config, system=system, observers=(observer,), science_directions_rad=observer.directions_rad)


@pytest.mark.parametrize("profile", DOCUMENTED_LAYERED_PROFILES)
def test_documented_layered_profiles_reach_the_shared_implementation(profile) -> None:
    name, version = profile.split("@")
    config = load_system_profile(name, int(version))
    assert config.atmosphere_model == "native_layered"
    assert profile in layered_profiles()
    offsets = check_off_axis_support(config, [(0.0, 0.0), (5.0, 0.0), (10.0, 0.0), (20.0, 0.0)])
    assert [o.radial_arcsec for o in offsets] == [0.0, 5.0, 10.0, 20.0]
    # The footprint report needs only the profile's layer table, not a build.
    metadata = {
        "layers": [{"altitude_m": l.altitude_m, "cn2_fraction": l.cn2_fraction} for l in config.atmosphere.layers],
        "grid_delta_m": config.telescope_diameter_m / (config.pupil_pixels - 1),
        "pupil_diameter_m": config.telescope_diameter_m,
        "screen_period_m": 2 * config.pupil_pixels * config.telescope_diameter_m / (config.pupil_pixels - 1),
    }
    report = footprint_report(metadata, offsets)
    top = max(l.altitude_m for l in config.atmosphere.layers)
    assert report["offsets"][-1]["max_displacement_m"] == pytest.approx(top * 20.0 * ARCSEC_TO_RAD)
    assert report["offsets"][0]["max_displacement_m"] == 0.0


def test_the_scalable_layered_tier_runs_through_the_shared_entry_point() -> None:
    """The 42 m benchmark family (sparse, scalable, StreamingLongExposure) at its desktop tier."""

    config = load_system_profile("eso_scao_smoke_5m_software", 2)
    assert config.scalable is not None and config.atmosphere_model == "native_layered"
    config = replace(config, controller=replace(config.controller, n_steps=8))
    system = build_scao_system(config)
    accumulator = StreamingLongExposure(
        system.science_propagator,
        LongExposureConfig(wavelengths_m=(2.2e-6,), burn_in_frames=2),
        telescope_diameter_m=config.telescope_diameter_m,
    )
    history = run_closed_loop(config, system=system, observers=(accumulator,))
    run = run_off_axis_science(
        config, offsets_arcsec=[(0.0, 0.0), (30.0, 0.0)], wavelengths_m=(2.2e-6,), burn_in_frames=2, system=system
    )
    _assert_same_history(run.history, history)
    on_axis = run.science.image((0.0, 0.0), 2.2e-6)
    np.testing.assert_array_equal(on_axis.psf.intensity, accumulator.result().image(2.2e-6).psf.intensity)
    assert run.science.image((30.0, 0.0), 2.2e-6).peak_strehl < on_axis.peak_strehl
    assert run.footprint["offsets"][1]["max_displacement_m"] > 0.0
