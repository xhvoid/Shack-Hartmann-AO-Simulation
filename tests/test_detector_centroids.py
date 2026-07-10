# Tests verify detector-level SH-WFS centroid sign/linearity, zero-phase residual, noise trends, and invalid centroid handling.

import numpy as np
import pytest

from shwfs_detector import centroid, crop_center
from synthetic_instrument_data import (
    DETECTOR_PRESETS,
    CentroidValidityConfig,
    DetectorConfig,
    DetectorPreset,
    SyntheticInstrumentError,
    ShwfsGeometryConfig,
    add_configured_detector_noise,
    build_detector_shwfs_calibration,
    build_tilt_response_matrix,
    detector_preset,
    make_bad_pixel_mask,
    measure_detector_shwfs,
    phase_tilt_map_rad,
    sample_centroid_noise,
    zero_phase_centroid_rms_px,
)


def _test_geometry() -> ShwfsGeometryConfig:
    return ShwfsGeometryConfig(
        telescope_diameter_m=2.0,
        n_pupil_pixels=96,
        n_lenslets=8,
        min_fill_fraction=0.35,
        pad_factor=4,
        detector_window_px=32,
        threshold_fraction=0.0,
        source_class="synthetic_assumed",
        source_note="Detector-centroid unit-test geometry.",
    )


def _gaussian_spot(size: int = 17, sigma_px: float = 2.0) -> np.ndarray:
    coords = np.arange(size) - (size - 1) / 2.0
    x, y = np.meshgrid(coords, coords)
    spot = np.exp(-(x**2 + y**2) / (2.0 * sigma_px**2))
    return spot / np.sum(spot)


def test_zero_phase_centroid_residual_is_below_gate():
    calibration = build_detector_shwfs_calibration(
        geometry=_test_geometry(),
        detector=DetectorConfig(photons_per_subap_frame=None),
    )

    residual_rms_px = zero_phase_centroid_rms_px(calibration)

    assert calibration.n_valid_subapertures > 0
    assert calibration.valid_subaperture_fraction > 0.0
    assert np.all(np.isfinite(calibration.reference_centroids_px))
    assert residual_rms_px < 0.05


def test_known_phase_tilt_has_expected_sign_and_linear_response():
    calibration = build_detector_shwfs_calibration(
        geometry=_test_geometry(),
        detector=DetectorConfig(photons_per_subap_frame=None),
    )

    phase_x_small = phase_tilt_map_rad(calibration, tilt_x_rad_per_m=0.025)
    phase_x_large = phase_tilt_map_rad(calibration, tilt_x_rad_per_m=0.050)
    phase_y_small = phase_tilt_map_rad(calibration, tilt_y_rad_per_m=0.025)
    meas_x_small = measure_detector_shwfs(phase_x_small, calibration, include_noise=False)
    meas_x_large = measure_detector_shwfs(phase_x_large, calibration, include_noise=False)
    meas_y_small = measure_detector_shwfs(phase_y_small, calibration, include_noise=False)

    mean_x_small = float(np.nanmean(meas_x_small.shifts_px[:, 0]))
    mean_x_large = float(np.nanmean(meas_x_large.shifts_px[:, 0]))
    mean_y_small = float(np.nanmean(meas_y_small.shifts_px[:, 1]))

    assert meas_x_small.valid_centroid_frac == pytest.approx(1.0)
    assert mean_x_small > 0.0
    assert mean_y_small < 0.0
    assert mean_x_large / mean_x_small == pytest.approx(2.0, rel=0.15)


def test_detector_tilt_response_matrix_shape_and_finite_rows():
    calibration = build_detector_shwfs_calibration(
        geometry=_test_geometry(),
        detector=DetectorConfig(photons_per_subap_frame=None),
    )

    response = build_tilt_response_matrix(calibration, calibration_amplitude_rad_per_m=0.05)

    assert response.matrix_px_per_unit.shape == (2 * calibration.n_valid_subapertures, 2)
    assert response.column_names == ("tilt_x_rad_per_m", "tilt_y_rad_per_m")
    assert np.all(response.row_valid)
    assert np.all(np.isfinite(response.matrix_px_per_unit))


def test_photon_noise_scatter_decreases_with_photon_count():
    spot = _gaussian_spot()
    low_flux = DetectorConfig(photons_per_subap_frame=200.0, read_noise_e=0.0, qe=1.0)
    high_flux = DetectorConfig(photons_per_subap_frame=20000.0, read_noise_e=0.0, qe=1.0)

    low = sample_centroid_noise(spot, low_flux, n_trials=160, seed=3)
    high = sample_centroid_noise(spot, high_flux, n_trials=160, seed=3)

    assert low["valid_fraction"] == pytest.approx(1.0)
    assert high["valid_fraction"] == pytest.approx(1.0)
    assert high["centroid_rms_px"] < 0.25 * low["centroid_rms_px"]


def test_read_noise_worsens_centroid_scatter_and_zero_flux_is_invalid():
    spot = _gaussian_spot()
    clean = DetectorConfig(photons_per_subap_frame=1000.0, read_noise_e=0.0, qe=1.0)
    noisy = DetectorConfig(photons_per_subap_frame=1000.0, read_noise_e=15.0, qe=1.0)
    zero_flux = DetectorConfig(photons_per_subap_frame=0.0, read_noise_e=0.0, qe=1.0)

    clean_stats = sample_centroid_noise(spot, clean, n_trials=160, seed=4)
    noisy_stats = sample_centroid_noise(spot, noisy, n_trials=160, seed=4)
    invalid_stats = sample_centroid_noise(spot, zero_flux, n_trials=8, seed=4)

    assert noisy_stats["centroid_rms_px"] > clean_stats["centroid_rms_px"]
    assert invalid_stats["valid_fraction"] == pytest.approx(0.0)
    assert np.isnan(invalid_stats["centroid_rms_px"])


def test_detector_model_applies_dark_background_full_well_and_bad_pixels():
    spot = _gaussian_spot(size=11, sigma_px=1.5)
    bad_mask = np.zeros_like(spot, dtype=bool)
    bad_mask[5, 5] = True
    detector = DetectorConfig(
        photons_per_subap_frame=1.0e6,
        read_noise_e=0.0,
        dark_e_per_s=20.0,
        exposure_s=0.5,
        background_e_per_pixel_frame=5.0,
        full_well_e=120.0,
        bad_pixel_mask=bad_mask,
        qe=1.0,
        source_note="Unit-test detector realism terms.",
    )

    image = add_configured_detector_noise(spot, detector, seed=11)

    assert np.all(np.isfinite(image))
    assert np.max(image) <= 120.0
    assert image[5, 5] == pytest.approx(0.0)


def test_detector_dark_background_level_and_prnu_are_observable():
    spot = np.ones((17, 17), dtype=float)
    spot /= spot.sum()
    background_detector = DetectorConfig(
        photons_per_subap_frame=0.0,
        read_noise_e=0.0,
        dark_e_per_s=1000.0,
        exposure_s=1.0,
        background_e_per_pixel_frame=500.0,
        source_note="Unit-test dark/background detector setting.",
    )
    clean_detector = DetectorConfig(
        photons_per_subap_frame=1.0e7,
        read_noise_e=0.0,
        prnu_rms=0.0,
        source_note="Unit-test clean high-flux detector setting.",
    )
    prnu_detector = DetectorConfig(
        photons_per_subap_frame=1.0e7,
        read_noise_e=0.0,
        prnu_rms=0.20,
        source_note="Unit-test PRNU high-flux detector setting.",
    )

    background_image = add_configured_detector_noise(spot, background_detector, seed=12)
    clean_image = add_configured_detector_noise(spot, clean_detector, seed=13)
    prnu_image = add_configured_detector_noise(spot, prnu_detector, seed=13)

    assert 1400.0 < float(np.mean(background_image)) < 1600.0
    assert float(np.std(prnu_image)) > 10.0 * float(np.std(clean_image))


def test_detector_bad_pixel_mask_shape_is_validated():
    spot = _gaussian_spot(size=9, sigma_px=1.5)
    detector = DetectorConfig(
        photons_per_subap_frame=1000.0,
        bad_pixel_mask=np.zeros((3, 3), dtype=bool),
        source_note="Unit-test malformed bad-pixel mask.",
    )

    with pytest.raises(SyntheticInstrumentError, match="bad_pixel_mask shape"):
        add_configured_detector_noise(spot, detector, seed=14)


def test_too_small_detector_window_clips_spot_and_biases_centroid():
    # Crop_center models the finite per-lenslet detector window. A spot
    # shifted toward the window edge has its outer wing clipped when the window
    # is too small, which loses flux and biases the centroid back toward center.
    size, sigma_px, shift_px = 35, 3.0, 5.0
    center = (size - 1) / 2.0
    axis = np.arange(size) - center
    x_grid, y_grid = np.meshgrid(axis, axis)
    spot = np.exp(-(((x_grid - shift_px) ** 2) + y_grid**2) / (2.0 * sigma_px**2))
    spot /= spot.sum()

    full_window = crop_center(spot, None)
    small_window = crop_center(spot, 13)
    cx_full = centroid(full_window)[0]
    cx_small = centroid(small_window)[0]

    assert cx_full == pytest.approx(shift_px, abs=0.1)  # full window recovers the offset
    assert small_window.sum() < 0.9 * full_window.sum()  # clipped flux
    assert 0.0 < cx_small < cx_full - 0.5  # centroid biased toward window center


def test_detector_presets_registry_has_required_named_presets():
    # Ideal / low_noise_sCMOS_like / noisy_visible_wfs / stress_saturated_window.
    assert set(DETECTOR_PRESETS) == {
        "ideal",
        "low_noise_sCMOS_like",
        "noisy_visible_wfs",
        "stress_saturated_window",
    }
    ideal = detector_preset("ideal")
    low = detector_preset("low_noise_sCMOS_like")
    noisy = detector_preset("noisy_visible_wfs")
    stress = detector_preset("stress_saturated_window")

    assert ideal.read_noise_e == 0.0 and ideal.dark_e_per_s == 0.0
    assert ideal.full_well_e is None and ideal.bad_pixel_fraction == 0.0
    # Read noise grows with detector difficulty; stress adds a saturating full well.
    assert ideal.read_noise_e < low.read_noise_e < noisy.read_noise_e
    assert stress.full_well_e is not None and stress.full_well_e < noisy.full_well_e
    # These are synthetic visible-WFS presets, never labelled as public data.
    for preset in (ideal, low, noisy, stress):
        assert isinstance(preset, DetectorPreset)
        assert preset.source_class == "synthetic_assumed"


def test_detector_preset_unknown_name_raises():
    with pytest.raises(SyntheticInstrumentError, match="Unknown detector preset"):
        detector_preset("nir_science_camera")


def test_detector_preset_to_config_builds_bad_pixel_mask_and_carries_noise():
    stress = detector_preset("stress_saturated_window")
    config = stress.to_detector_config(photons_per_subap_frame=500.0, window_px=24, seed=7)

    assert config.full_well_e == stress.full_well_e
    assert config.read_noise_e == stress.read_noise_e
    assert config.bad_pixel_mask is not None
    assert config.bad_pixel_mask.shape == (24, 24)
    assert 0.0 < float(np.mean(config.bad_pixel_mask)) < 0.05

    ideal_config = detector_preset("ideal").to_detector_config(photons_per_subap_frame=None)
    assert ideal_config.bad_pixel_mask is None
    assert ideal_config.read_noise_e == 0.0


def test_make_bad_pixel_mask_is_deterministic_and_respects_fraction():
    mask_a = make_bad_pixel_mask(40, 0.05, seed=3)
    mask_b = make_bad_pixel_mask(40, 0.05, seed=3)

    assert np.array_equal(mask_a, mask_b)
    assert mask_a.shape == (40, 40)
    assert 0.02 < float(np.mean(mask_a)) < 0.08  # ~5% dead pixels


# --- Centroid-validity (faint-photon) diagnostics -----------------------------


def _validity_calibration(photons, read_noise_e=1.0, window_px=20):
    geometry = ShwfsGeometryConfig(
        telescope_diameter_m=2.0,
        n_pupil_pixels=72,
        n_lenslets=7,
        pad_factor=3,
        detector_window_px=window_px,
        source_class="synthetic_assumed",
        source_note="Centroid-validity unit-test geometry.",
    )
    detector = DetectorConfig(
        photons_per_subap_frame=photons,
        read_noise_e=read_noise_e,
        source_class="synthetic_assumed",
        source_note="Centroid-validity unit-test detector.",
    )
    return build_detector_shwfs_calibration(geometry=geometry, detector=detector)


def _zero_phase(calibration):
    return np.where(calibration.pupil_mask, 0.0, np.nan)


def test_centroid_quality_improves_with_photon_count():
    cal_faint = _validity_calibration(150.0)
    cal_bright = _validity_calibration(8000.0)
    faint = measure_detector_shwfs(_zero_phase(cal_faint), cal_faint, include_noise=True, seed=5)
    bright = measure_detector_shwfs(_zero_phase(cal_bright), cal_bright, include_noise=True, seed=5)

    assert np.nanmedian(bright.peak_snr) > np.nanmedian(faint.peak_snr)
    assert np.nanmedian(bright.total_snr) > np.nanmedian(faint.total_snr)
    assert np.nanmedian(bright.centroid_sigma_px) < np.nanmedian(faint.centroid_sigma_px)


def test_low_photon_count_reduces_valid_centroid_fraction():
    cal_bright = _validity_calibration(8000.0)
    cal_subphoton = _validity_calibration(0.02)
    bright = measure_detector_shwfs(_zero_phase(cal_bright), cal_bright, include_noise=True, seed=7)
    subphoton = measure_detector_shwfs(_zero_phase(cal_subphoton), cal_subphoton, include_noise=True, seed=7)

    assert bright.valid_centroid_frac == pytest.approx(1.0)
    # A sub-photon-per-subaperture budget must not be reported as fully valid.
    assert subphoton.valid_centroid_frac < 0.05
    assert not np.any(subphoton.valid_by_flux)


def test_high_read_noise_reduces_centroid_validity():
    cal_low = _validity_calibration(200.0, read_noise_e=1.0)
    cal_high = _validity_calibration(200.0, read_noise_e=25.0)
    low = measure_detector_shwfs(_zero_phase(cal_low), cal_low, include_noise=True, seed=9)
    high = measure_detector_shwfs(_zero_phase(cal_high), cal_high, include_noise=True, seed=9)

    assert np.nanmedian(high.peak_snr) < np.nanmedian(low.peak_snr)
    assert high.valid_centroid_frac < low.valid_centroid_frac


def test_small_detector_window_increases_clipping_and_fails_validity():
    cal_wide = _validity_calibration(8000.0, window_px=20)
    cal_narrow = _validity_calibration(8000.0, window_px=6)
    wide = measure_detector_shwfs(_zero_phase(cal_wide), cal_wide, include_noise=True, seed=11)
    narrow = measure_detector_shwfs(_zero_phase(cal_narrow), cal_narrow, include_noise=True, seed=11)

    assert np.nanmean(narrow.window_clipping_fraction) > np.nanmean(wide.window_clipping_fraction)
    assert wide.valid_centroid_frac == pytest.approx(1.0)
    # The narrow window clips enough spot energy to fail the clipping criterion.
    assert not np.all(narrow.valid_by_clipping)
    assert narrow.valid_centroid_frac < wide.valid_centroid_frac


def test_bright_centroids_are_valid_and_reproducible_under_fixed_seed():
    cal = _validity_calibration(8000.0)
    first = measure_detector_shwfs(_zero_phase(cal), cal, include_noise=True, seed=13)
    second = measure_detector_shwfs(_zero_phase(cal), cal, include_noise=True, seed=13)

    assert first.valid_centroid_frac == pytest.approx(1.0)
    assert np.array_equal(first.valid, second.valid)
    assert np.allclose(np.nan_to_num(first.shifts_px), np.nan_to_num(second.shifts_px))


def test_centroid_validity_config_rejects_invalid_thresholds():
    with pytest.raises(SyntheticInstrumentError):
        CentroidValidityConfig(min_flux_e=-1.0)
    with pytest.raises(SyntheticInstrumentError):
        CentroidValidityConfig(max_window_clipping_fraction=2.0)
