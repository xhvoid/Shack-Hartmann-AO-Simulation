# Tests verify H-band closed-loop Strehl improvement, Marechal agreement for small residuals, and finite FWHM/EE/halo band metrics.

from pathlib import Path

import numpy as np
import pytest

from ao_closed_loop import DetectorLoopConfig, run_detector_integrator_loop
from ao_diagnostics import (
    AODiagnosticsError,
    ScienceBandpass,
    band_averaged_psf_metrics_from_opd,
    bandpass_from_filter_curve,
    monochromatic_bandpass,
    phase_rad_to_opd_nm,
    residual_opd_nm_from_command,
    science_case_metrics_table,
    science_metrics_as_dicts,
    science_psf_metrics_from_opd,
    top_hat_bandpass,
)
from data_sources import load_svo_filter_curve
from dm_model import DMConfig, build_dm_model, synthesize_dm_phase_rad
from interaction_matrix import PokeMatrixConfig, build_detector_dm_poke_matrix, expand_controlled_commands
from synthetic_instrument_data import DetectorConfig, ShwfsGeometryConfig, build_detector_shwfs_calibration


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "src" / "shwfs_ao" / "resources"


@pytest.fixture(scope="module")
def fast_science_case():
    geometry = ShwfsGeometryConfig(
        telescope_diameter_m=2.0,
        n_pupil_pixels=64,
        n_lenslets=6,
        min_fill_fraction=0.35,
        pad_factor=3,
        detector_window_px=20,
        threshold_fraction=0.0,
        source_class="synthetic_assumed",
        source_note="Fast science-metric unit-test geometry.",
    )
    calibration = build_detector_shwfs_calibration(
        geometry=geometry,
        detector=DetectorConfig(
            photons_per_subap_frame=None,
            read_noise_e=0.0,
            qe=1.0,
            source_class="synthetic_assumed",
            source_note="Deterministic detector configuration for fast PSF sanity tests.",
        ),
    )
    dm_model = build_dm_model(
        calibration.x_m,
        calibration.y_m,
        calibration.pupil_mask,
        DMConfig(
            telescope_diameter_m=2.0,
            n_actuators_across=5,
            influence_model="gaussian",
            coupling_width_pitch=0.40,
            stroke_limit_nm=1000.0,
            source_class="synthetic_literature_inspired",
            source_note="Fast synthetic Gaussian DM model.",
        ),
    )
    poke = build_detector_dm_poke_matrix(
        calibration,
        dm_model,
        PokeMatrixConfig(
            calibration_amplitude_nm=10.0,
            rcond_scan_grid=(1.0e-8, 1.0e-6, 1.0e-4, 1.0e-3),
            target_kept_mode_fraction=1.0,
            source_class="synthetic_assumed",
            source_note="Fast central-difference poke configuration.",
        ),
    )
    return calibration, dm_model, poke


def _dm_phase_sequence(fast_science_case, amplitude_nm: float = 400.0, n_steps: int = 24) -> np.ndarray:
    calibration, dm_model, poke = fast_science_case
    base = np.zeros(poke.n_controlled_actuators)
    base[0] = amplitude_nm
    base[poke.n_controlled_actuators // 2] = 0.6 * amplitude_nm
    base[-1] = -0.8 * amplitude_nm
    base[3] = 0.4 * amplitude_nm
    phase_maps = []
    for step in range(n_steps):
        scale = 0.75 + 0.20 * np.sin(2.0 * np.pi * step / 16.0)
        drift = np.zeros_like(base)
        drift[5] = 0.20 * amplitude_nm * np.sin(2.0 * np.pi * step / 24.0)
        drift[8] = -0.15 * amplitude_nm * np.cos(2.0 * np.pi * step / 20.0)
        full_commands = expand_controlled_commands(scale * base + drift, poke, dm_model)
        phase_rad, _ = synthesize_dm_phase_rad(
            full_commands,
            dm_model,
            wavelength_m=calibration.geometry.wfs_wavelength_m,
            remove_piston=True,
        )
        phase_maps.append(phase_rad)
    return np.asarray(phase_maps)


def test_ideal_psf_metrics_are_finite_and_diffraction_limited():
    n = 64
    coords = np.linspace(-1.0, 1.0, n)
    x, y = np.meshgrid(coords, coords)
    mask = x**2 + y**2 <= 1.0
    ideal_opd_nm = np.where(mask, 0.0, np.nan)

    metrics = science_psf_metrics_from_opd(
        ideal_opd_nm,
        mask,
        wavelength_m=1.65e-6,
        telescope_diameter_m=2.0,
        case_name="ideal_closed_loop",
        band_name="H",
        pad_factor=6,
    )

    assert metrics.strehl_peak == pytest.approx(1.0)
    assert metrics.strehl_marechal == pytest.approx(1.0)
    assert 0.75 < metrics.fwhm_lambda_over_d < 1.15
    assert 0.0 < metrics.ee50_lambda_over_d < metrics.ee80_lambda_over_d
    assert 0.0 <= metrics.halo_fraction < 0.2


def test_marechal_matches_peak_strehl_for_small_residual_opd():
    n = 80
    coords = np.linspace(-1.0, 1.0, n)
    x, y = np.meshgrid(coords, coords)
    mask = x**2 + y**2 <= 1.0
    opd_nm = np.where(mask, 45.0 * (x**2 - y**2), np.nan)

    metrics = science_psf_metrics_from_opd(
        opd_nm,
        mask,
        wavelength_m=1.65e-6,
        telescope_diameter_m=2.0,
        case_name="small_residual",
        band_name="H",
        pad_factor=5,
    )

    assert metrics.strehl_peak > 0.95
    assert metrics.marechal_abs_error < 0.03


def test_peak_centered_metrics_are_invariant_to_integer_sampled_tip_tilt():
    n = 64
    y, x = np.indices((n, n))
    xn = (x - n // 2) / float(n)
    yn = (y - n // 2) / float(n)
    mask = xn**2 + yn**2 <= 0.24
    wavelength_m = 1.0e-6
    wavelength_nm = wavelength_m * 1.0e9
    ideal_opd_nm = np.where(mask, 0.0, np.nan)
    # Three cycles across the unpadded array shift the padded PSF by an exact
    # integer number of samples without changing its shape.
    tilted_opd_nm = np.where(mask, wavelength_nm * 3.0 * xn, np.nan)

    ideal = science_psf_metrics_from_opd(
        ideal_opd_nm,
        mask,
        wavelength_m=wavelength_m,
        telescope_diameter_m=2.0,
        pad_factor=4,
    )
    tilted = science_psf_metrics_from_opd(
        tilted_opd_nm,
        mask,
        wavelength_m=wavelength_m,
        telescope_diameter_m=2.0,
        pad_factor=4,
    )

    assert tilted.strehl_peak == pytest.approx(ideal.strehl_peak, abs=1.0e-12)
    assert tilted.fwhm_px == pytest.approx(ideal.fwhm_px, abs=1.0e-12)
    assert tilted.ee50_px == pytest.approx(ideal.ee50_px, abs=1.0e-12)
    assert tilted.ee80_px == pytest.approx(ideal.ee80_px, abs=1.0e-12)
    assert tilted.halo_fraction == pytest.approx(ideal.halo_fraction, abs=1.0e-12)


def test_band_quadrature_is_invariant_to_benign_nonuniform_resampling():
    uniform_wavelengths = np.linspace(1.2e-6, 1.8e-6, 61)
    nonuniform_wavelengths = np.concatenate(
        (
            np.linspace(1.2e-6, 1.45e-6, 51, endpoint=False),
            np.linspace(1.45e-6, 1.8e-6, 22),
        )
    )
    uniform = ScienceBandpass(
        "uniform_H",
        uniform_wavelengths,
        np.ones_like(uniform_wavelengths),
        source_note="Uniform flat-band quadrature regression.",
    )
    nonuniform = ScienceBandpass(
        "nonuniform_H",
        nonuniform_wavelengths,
        np.ones_like(nonuniform_wavelengths),
        source_note="Nonuniform flat-band quadrature regression.",
    )
    n = 48
    coords = np.linspace(-1.0, 1.0, n)
    x, y = np.meshgrid(coords, coords)
    mask = x**2 + y**2 <= 1.0
    opd_nm = np.where(mask, 90.0 * (x**2 - y**2), np.nan)

    uniform_metrics = band_averaged_psf_metrics_from_opd(
        opd_nm,
        mask,
        uniform,
        telescope_diameter_m=2.0,
        pad_factor=3,
    )
    nonuniform_metrics = band_averaged_psf_metrics_from_opd(
        opd_nm,
        mask,
        nonuniform,
        telescope_diameter_m=2.0,
        pad_factor=3,
    )

    assert uniform.effective_wavelength_m == pytest.approx(1.5e-6, abs=1.0e-15)
    assert nonuniform.effective_wavelength_m == pytest.approx(1.5e-6, abs=1.0e-15)
    assert nonuniform_metrics.strehl_peak == pytest.approx(uniform_metrics.strehl_peak, rel=2.0e-4)
    assert nonuniform_metrics.ee80_lambda_over_d == pytest.approx(
        uniform_metrics.ee80_lambda_over_d,
        rel=2.0e-4,
    )


@pytest.mark.parametrize("invalid_value", [np.nan, np.inf])
def test_science_metrics_reject_nonfinite_opd_inside_pupil(invalid_value):
    n = 32
    coords = np.linspace(-1.0, 1.0, n)
    x, y = np.meshgrid(coords, coords)
    mask = x**2 + y**2 <= 1.0
    opd_nm = np.where(mask, 0.0, np.nan)
    inside_y, inside_x = np.argwhere(mask)[0]
    opd_nm[inside_y, inside_x] = invalid_value

    with pytest.raises(AODiagnosticsError, match="Non-finite values inside"):
        science_psf_metrics_from_opd(
            opd_nm,
            mask,
            wavelength_m=1.65e-6,
            telescope_diameter_m=2.0,
        )


def test_svo_style_h_band_metrics_are_finite():
    curve = load_svo_filter_curve(DATA_ROOT / "samples" / "svo_2mass_h_sample.csv")
    band = bandpass_from_filter_curve(curve, name="2MASS.H")
    n = 64
    coords = np.linspace(-1.0, 1.0, n)
    x, y = np.meshgrid(coords, coords)
    mask = x**2 + y**2 <= 1.0
    opd_nm = np.where(mask, 80.0 * x, np.nan)

    metrics = band_averaged_psf_metrics_from_opd(
        opd_nm,
        mask,
        band,
        telescope_diameter_m=2.0,
        case_name="open_loop",
        pad_factor=4,
    )

    assert metrics.source_class == "synthetic_assumed"
    assert "bandpass provenance" in metrics.source_note
    assert metrics.effective_wavelength_m == pytest.approx(1.65e-6, rel=0.07)
    assert 0.0 < metrics.strehl_peak <= 1.0
    assert metrics.ee50_lambda_over_d < metrics.ee80_lambda_over_d
    assert np.isfinite(metrics.fwhm_arcsec)


def test_case_table_reports_open_ideal_and_realistic_closed_loop_cases():
    n = 64
    coords = np.linspace(-1.0, 1.0, n)
    x, y = np.meshgrid(coords, coords)
    mask = x**2 + y**2 <= 1.0
    cases = {
        "open_loop": np.where(mask, 180.0 * x, np.nan),
        "ideal_closed_loop": np.where(mask, 0.0, np.nan),
        "realistic_closed_loop": np.where(mask, 35.0 * x, np.nan),
    }
    bands = (
        monochromatic_bandpass("J", 1.25e-6, source_note="Synthetic monochromatic J fallback."),
        top_hat_bandpass("K", 2.00e-6, 2.35e-6, source_note="Synthetic K top-hat fallback."),
    )

    table = science_case_metrics_table(cases, mask, bands, telescope_diameter_m=2.0, pad_factor=4)
    rows = science_metrics_as_dicts(table)

    assert len(rows) == 6
    assert {row["case_name"] for row in rows} == {"open_loop", "ideal_closed_loop", "realistic_closed_loop"}
    assert {row["band_name"] for row in rows} == {"J", "K"}
    assert all(np.isfinite(row["strehl_peak"]) for row in rows)
    assert all(row["source_class"] == "synthetic_assumed" for row in rows)


def test_dynamic_closed_loop_h_band_strehl_exceeds_open_loop_for_fast_preset(fast_science_case):
    calibration, dm_model, poke = fast_science_case
    phase_sequence = _dm_phase_sequence(fast_science_case)
    history = run_detector_integrator_loop(
        phase_sequence,
        calibration,
        dm_model,
        poke,
        DetectorLoopConfig(
            n_steps=phase_sequence.shape[0],
            gain=0.32,
            leak=0.02,
            latency_frames=1,
            frame_rate_hz=500.0,
            include_detector_noise=False,
            source_note="Default fast dynamic loop sanity configuration.",
        ),
    )

    open_strehl = []
    closed_strehl = []
    for step in range(phase_sequence.shape[0] // 2, phase_sequence.shape[0]):
        open_opd_nm = phase_rad_to_opd_nm(
            phase_sequence[step],
            calibration.geometry.wfs_wavelength_m,
            calibration.pupil_mask,
        )
        closed_opd_nm = residual_opd_nm_from_command(
            phase_sequence[step],
            history.command_history_nm[step],
            dm_model,
            calibration.geometry.wfs_wavelength_m,
        )
        open_strehl.append(
            science_psf_metrics_from_opd(
                open_opd_nm,
                calibration.pupil_mask,
                wavelength_m=1.65e-6,
                telescope_diameter_m=2.0,
                case_name="open_loop",
                band_name="H",
                pad_factor=4,
            ).strehl_peak
        )
        closed_strehl.append(
            science_psf_metrics_from_opd(
                closed_opd_nm,
                calibration.pupil_mask,
                wavelength_m=1.65e-6,
                telescope_diameter_m=2.0,
                case_name="realistic_closed_loop",
                band_name="H",
                pad_factor=4,
            ).strehl_peak
        )

    assert np.median(history.residual_opd_rms[12:]) < np.median(history.open_loop_opd_rms[12:])
    assert np.median(closed_strehl) > np.median(open_strehl)
    assert np.min(history.valid_centroid_frac) == pytest.approx(1.0)


def test_rejects_invalid_bandpass_inputs():
    with pytest.raises(AODiagnosticsError, match="strictly increasing"):
        ScienceBandpass(
            name="bad",
            wavelength_m=np.asarray([1.0e-6, 0.9e-6]),
            transmission=np.asarray([1.0, 1.0]),
            source_note="invalid wavelength order",
        )
