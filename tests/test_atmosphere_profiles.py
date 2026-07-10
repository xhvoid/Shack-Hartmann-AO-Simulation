# Tests verify r0 conversion, Cn2 normalization, and finite frozen-flow phase cubes.

from pathlib import Path

import numpy as np
import pytest

from atmosphere_profiles import (
    ARCSEC_PER_RAD,
    PHASE_RMS_REL_TOL,
    AtmosphereConfig,
    AtmosphereLayerConfig,
    AtmosphereProfileError,
    atmosphere_config_from_eso_asm_snapshot,
    atmosphere_config_from_literature_profile,
    equivalent_r0_500_m,
    expected_phase_rms_rad,
    generate_multilayer_phase_cube,
    normalize_layers,
    r0_at_wavelength_m,
    seeing_to_r0_m,
    shift_full_phase_pixels,
)
from data_sources import load_eso_asm_snapshot, load_literature_atmosphere_profile


ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / "data" / "literature_profiles" / "paranal_three_layer_literature_inspired.json"
ESO_ASM_PATH = ROOT / "data" / "public" / "eso_asm_paranal_20240729_0300_0800_snapshot.json"


def test_seeing_to_r0_and_wavelength_scaling_follow_fried_formula():
    seeing_arcsec = 0.8
    wavelength_m = 500.0e-9

    r0_500_m = seeing_to_r0_m(seeing_arcsec, wavelength_m=wavelength_m)
    r0_1000_m = r0_at_wavelength_m(r0_500_m, wavelength_m=1.0e-6)

    assert r0_500_m == pytest.approx(0.98 * wavelength_m / (seeing_arcsec / ARCSEC_PER_RAD))
    assert r0_1000_m == pytest.approx(r0_500_m * 2.0 ** (6.0 / 5.0))


def test_literature_profile_builds_normalized_atmosphere_config():
    profile = load_literature_atmosphere_profile(PROFILE_PATH)
    config = atmosphere_config_from_literature_profile(profile, seed=22)

    weights = [layer.cn2_weight for layer in config.layers]
    r0_from_seeing_m = seeing_to_r0_m(config.seeing_arcsec)

    assert sum(weights) == pytest.approx(1.0)
    assert equivalent_r0_500_m(config) == pytest.approx(config.r0_500_m)
    assert config.r0_500_m == pytest.approx(r0_from_seeing_m, rel=0.05)
    assert config.theta0_rad == pytest.approx(profile.summary["theta0_arcsec"] / ARCSEC_PER_RAD)


def test_direct_eso_asm_snapshot_builds_atmosphere_config():
    snapshot = load_eso_asm_snapshot(ESO_ASM_PATH)
    config = atmosphere_config_from_eso_asm_snapshot(snapshot, seed=24, wind_dir_deg=70.0)

    assert config.source_class == "direct_public_data"
    assert config.r0_500_m == pytest.approx(seeing_to_r0_m(config.seeing_arcsec))
    assert config.tau0_s == pytest.approx(snapshot.measurements["tau0_s"])
    assert config.theta0_rad == pytest.approx(snapshot.measurements["theta0_arcsec"] / ARCSEC_PER_RAD)
    assert len(config.layers) == 1
    assert config.layers[0].wind_ms == pytest.approx(snapshot.measurements["turbulence_speed_ms"])
    assert config.layers[0].wind_dir_deg == pytest.approx(70.0)


def test_normalize_layers_preserves_metadata_and_unit_strength():
    layers = (
        AtmosphereLayerConfig(height_m=0.0, cn2_weight=2.0, wind_ms=0.0, wind_dir_deg=0.0),
        AtmosphereLayerConfig(height_m=1000.0, cn2_weight=1.0, wind_ms=5.0, wind_dir_deg=90.0),
    )

    normalized = normalize_layers(layers)

    assert [layer.height_m for layer in normalized] == [0.0, 1000.0]
    assert sum(layer.cn2_weight for layer in normalized) == pytest.approx(1.0)
    assert normalized[0].cn2_weight == pytest.approx(2.0 / 3.0)
    assert normalized[1].wind_ms == pytest.approx(5.0)


def test_manual_atmosphere_config_rejects_legacy_source_class():
    with pytest.raises(AtmosphereProfileError, match="source_class"):
        AtmosphereConfig(
            layers=(AtmosphereLayerConfig(height_m=0.0, cn2_weight=1.0, wind_ms=0.0, wind_dir_deg=0.0),),
            r0_500_m=0.20,
            seeing_arcsec=0.50,
            tau0_s=0.004,
            theta0_rad=2.0 / ARCSEC_PER_RAD,
            seed=4,
            source_class="public_api",
            source_note="Legacy taxonomy should be rejected.",
        )


def test_zero_wind_multilayer_cube_is_static_and_matches_r0_rms():
    config = AtmosphereConfig(
        layers=(AtmosphereLayerConfig(height_m=0.0, cn2_weight=1.0, wind_ms=0.0, wind_dir_deg=0.0),),
        r0_500_m=0.20,
        seeing_arcsec=0.50,
        tau0_s=0.004,
        theta0_rad=2.0 / ARCSEC_PER_RAD,
        seed=4,
        source_class="synthetic_assumed",
        source_note="Unit-test single-layer atmosphere.",
    )

    cube = generate_multilayer_phase_cube(
        config,
        n_grid=48,
        diameter_m=1.0,
        n_steps=4,
        dt_s=0.001,
        wavelength_m=500.0e-9,
    )

    assert cube.cube_rad.shape == (4, 48, 48)
    assert np.all(np.isfinite(cube.cube_rad[:, cube.mask]))
    assert np.all(np.isnan(cube.cube_rad[:, ~cube.mask]))
    assert np.allclose(cube.cube_rad[0][cube.mask], cube.cube_rad[-1][cube.mask])
    assert cube.expected_rms_rad == pytest.approx(expected_phase_rms_rad(1.0, 0.20))
    assert np.max(np.abs(cube.rms_rad - cube.expected_rms_rad) / cube.expected_rms_rad) < PHASE_RMS_REL_TOL


def test_finite_wind_shifts_features_without_masked_crescent():
    config = AtmosphereConfig(
        layers=(AtmosphereLayerConfig(height_m=0.0, cn2_weight=1.0, wind_ms=1.0, wind_dir_deg=0.0),),
        r0_500_m=0.20,
        seeing_arcsec=0.50,
        tau0_s=0.004,
        theta0_rad=2.0 / ARCSEC_PER_RAD,
        seed=5,
        source_class="synthetic_assumed",
        source_note="Unit-test finite-wind atmosphere.",
    )

    cube = generate_multilayer_phase_cube(
        config,
        n_grid=48,
        diameter_m=1.0,
        n_steps=2,
        dt_s=1.0 / 48.0,
        wavelength_m=500.0e-9,
    )
    toy = np.arange(25, dtype=float).reshape(5, 5)

    assert np.all(np.isfinite(cube.cube_rad[:, cube.mask]))
    assert np.all(np.isnan(cube.cube_rad[:, ~cube.mask]))
    assert not np.allclose(cube.cube_rad[0][cube.mask], cube.cube_rad[1][cube.mask])
    assert np.array_equal(shift_full_phase_pixels(toy, shift_x_pix=1, shift_y_pix=0), np.roll(toy, 1, axis=1))
