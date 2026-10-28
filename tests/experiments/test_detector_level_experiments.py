"""Review 2026-10-16: controlled E6 photometry (R5) and isolated detector noise.

Configuration-only checks and short 2 m loops; no 12 m system is built.
"""

from __future__ import annotations

import numpy as np
import pytest

from shwfs_ao.detector.physical_config import BandpassConfig, physical_budget
from shwfs_ao.experiments.detector_level import (
    paired_noise_run,
    science_run,
    with_matched_photometry,
    with_physics,
)
from shwfs_ao.experiments.scao import physical_detector_config
from shwfs_ao.io.configs import load_system_profile


def _budget(config):
    return physical_budget(
        physical_detector_config(config),
        wfs_wavelength_m=config.wfs_wavelength_m,
        full_subaperture_area_m2=1.0,
        pixel_solid_angle_sr=1.0e-12,
    )


def test_matched_photometry_changes_the_optics_band_but_not_the_electrons() -> None:
    base = load_system_profile("det_emccd_12m_medium_derived", 3)
    mono = with_physics(base, bandpass=BandpassConfig(kind="monochromatic", band_min_m=5.5e-7, band_max_m=8.5e-7))
    # The plain 550-850 nm arm detects 5.7 % more source and sky electrons.
    assert _budget(mono).detected_e_full_subap / _budget(base).detected_e_full_subap == pytest.approx(1.056988833, rel=1e-9)
    matched = with_matched_photometry(mono, base)
    assert matched.detector_physics.bandpass == mono.detector_physics.bandpass
    assert _budget(matched).detected_e_full_subap == pytest.approx(_budget(base).detected_e_full_subap, rel=1e-12)
    assert _budget(matched).sky_e_per_pixel_full_subap == pytest.approx(_budget(base).sky_e_per_pixel_full_subap, rel=1e-12)


def test_the_paired_noise_run_isolates_the_temporal_detector_noise() -> None:
    config = load_system_profile("det_emccd_2m_synthetic", 1)
    paired = paired_noise_run(config, root_seed=7, n_steps=40, burn_in_frames=10, block_frames=10)
    # The noise-on arm is the canonical noise-on run, bit for bit.
    reference = science_run(config, root_seed=7, n_steps=40, burn_in_frames=10)
    assert paired["arms"]["noise_on"]["post_update_rms_m"] == reference["post_update_rms_m"]
    assert paired["arms"]["noise_on"]["post_update_mean_square_m2"] == reference["post_update_mean_square_m2"]
    twin = paired["arms"]["operating_expectation"]
    assert twin["valid_measurement_fraction"] == 1.0 and not twin["lost_lock"]
    assert paired["mean_square_difference_m2"] == pytest.approx(
        paired["arms"]["noise_on"]["post_update_mean_square_m2"] - twin["post_update_mean_square_m2"]
    )
    # The residual-map difference is positive and needs no cross term.
    assert paired["noise_variance_m2"] > 0.0
    assert np.isfinite(paired["noise_variance_standard_error_m2"])
    assert paired["predicted_centroid_variance_px2"] > 0.0
