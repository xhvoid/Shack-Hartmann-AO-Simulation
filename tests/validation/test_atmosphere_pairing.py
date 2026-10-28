"""T2 G1: physical-coordinate checks of the paired layered-atmosphere input."""

from __future__ import annotations

import math

import numpy as np
import pytest

from shwfs_ao.backends.native.layered_atmosphere import (
    FrozenFlowLayer,
    LayeredFrozenFlowAtmosphere,
    LayeredFrozenFlowAtmosphereConfig,
    common_band_mask,
)
from shwfs_ao.validation.atmosphere_pairing import (
    PairingError,
    band_edge_power_fraction,
    band_field_on_coordinates,
    common_band_power_fraction,
    compare_paired_band_fields,
    physical_frequency_dilation,
)

LAYERS = (FrozenFlowLayer(0.7, (5.0, 0.0)), FrozenFlowLayer(0.3, (0.0, -3.0), 2000.0))


def _config(grid: int, *, diameter: float = 2.0, **extra):
    return LayeredFrozenFlowAtmosphereConfig(
        grid_size=grid, delta_m=diameter / (grid - 1), pupil_diameter_m=diameter, r0_m=0.13,
        layers=LAYERS, outer_scale_m=25.0, root_seed=5, **extra,
    )


def test_the_default_rule_dilates_equal_indices_by_the_predicted_factor() -> None:
    coarse, fine = _config(48), _config(64)
    report = physical_frequency_dilation(coarse, fine)
    expected = (48.0 / 47.0) / (64.0 / 63.0)
    assert report.frequency_ratio_fine_over_coarse == pytest.approx(expected, rel=1.0e-12)
    assert report.exact is False
    # Closed form: the coarse band-edge mode's phase error at the pupil edge is pi (1 - N_c / N_f).
    assert report.phase_error_at_pupil_edge_rad == pytest.approx(math.pi * (1.0 - 48.0 / 64.0), rel=1.0e-9)
    twelve = physical_frequency_dilation(
        _config(288, diameter=12.0), _config(384, diameter=12.0)
    )
    assert twelve.relative_dilation == pytest.approx(8.71e-4, abs=1.0e-6)  # the contract's 0.09 %
    assert twelve.phase_error_at_pupil_edge_rad == pytest.approx(math.pi / 4.0, rel=1.0e-9)
    record = twelve.to_record()
    assert record["exact_physical_pairing"] is False and record["coarse_band_edge_index"] == 288


def test_the_pupil_diameter_rule_pairs_exactly() -> None:
    coarse = _config(48, screen_period_rule="pupil_diameter")
    fine = _config(64, screen_period_rule="pupil_diameter")
    assert coarse.screen_size == 94 and fine.screen_size == 126
    assert coarse.screen_period_m == pytest.approx(4.0) and fine.screen_period_m == pytest.approx(4.0)
    report = physical_frequency_dilation(coarse, fine)
    assert report.exact is True and report.phase_error_at_pupil_edge_rad < 1.0e-9


def test_pairs_must_be_ordered_and_share_the_diameter() -> None:
    with pytest.raises(PairingError, match="coarser"):
        physical_frequency_dilation(_config(64), _config(48))
    with pytest.raises(PairingError, match="diameter"):
        physical_frequency_dilation(_config(48), _config(64, diameter=3.0))


def test_band_edge_and_common_band_power_fractions() -> None:
    edge = band_edge_power_fraction(_config(48))
    assert 0.0 < edge < 1.0e-3  # the Nyquist row and column of a 96-sample screen
    assert band_edge_power_fraction(_config(49, screen_period_rule="pupil_diameter")) == 0.0 or _config(49, screen_period_rule="pupil_diameter").screen_size % 2 == 0
    odd = LayeredFrozenFlowAtmosphereConfig(
        grid_size=20, delta_m=0.1, pupil_diameter_m=2.0, r0_m=0.13, layers=LAYERS, screen_period_factor=3,
    )
    assert odd.screen_size == 60
    # The common band of the screen's own size excludes exactly its Nyquist row and column.
    own = common_band_power_fraction(_config(64), 128)
    assert own == pytest.approx(1.0 - band_edge_power_fraction(_config(64)), rel=1.0e-12)
    assert 0.999 < own < 1.0
    partial = common_band_power_fraction(_config(64, screen_period_rule="pupil_diameter"), 94)
    assert 0.98 < partial < 1.0
    atmosphere = LayeredFrozenFlowAtmosphere(
        _config(64, screen_period_rule="pupil_diameter", band_draw_reference_screen_size=126, band_limit_screen_size=94)
    )
    assert atmosphere.band_power_retained_fraction == pytest.approx(partial)
    assert atmosphere.metadata["band_power_retained_fraction"] == pytest.approx(partial)


def test_the_continuous_band_field_samples_to_the_fft_evaluation() -> None:
    """The direct trigonometric sum at the grid points equals the inverse FFT the atmosphere uses."""

    atmosphere = LayeredFrozenFlowAtmosphere(_config(32))
    config = atmosphere.config
    coefficients = atmosphere._band_coefficients[1]
    size = config.screen_size
    reference = np.fft.ifft2(coefficients).real
    coordinates = np.arange(size) * config.delta_m
    direct = band_field_on_coordinates(atmosphere, coordinates, coordinates, layer_index=1)
    assert np.max(np.abs(direct - reference)) < 1.0e-10 * np.max(np.abs(reference))
    # Restricting to the common band of a smaller screen zeroes the right modes.
    limited = band_field_on_coordinates(atmosphere, coordinates, coordinates, layer_index=1, band_limit_screen_size=40)
    masked = np.fft.ifft2(coefficients * common_band_mask(size, 40)).real
    assert np.max(np.abs(limited - masked)) < 1.0e-10 * np.max(np.abs(reference))
    with pytest.raises(PairingError):
        band_field_on_coordinates(atmosphere, coordinates, coordinates, layer_index=2)
    with pytest.raises(PairingError):
        band_field_on_coordinates(atmosphere, coordinates, coordinates, band_limit_screen_size=size + 2)


def test_paired_fields_agree_exactly_under_the_matched_rule_and_differ_under_the_default() -> None:
    matched = {
        "coarse": LayeredFrozenFlowAtmosphere(_config(48, screen_period_rule="pupil_diameter", band_draw_reference_screen_size=126)),
        "fine": LayeredFrozenFlowAtmosphere(_config(64, screen_period_rule="pupil_diameter", band_draw_reference_screen_size=126)),
    }
    report = compare_paired_band_fields(matched["coarse"], matched["fine"], points_per_axis=32)
    assert report["relative_difference"] < 1.0e-12
    assert report["dilation"]["exact_physical_pairing"] is True
    default = {
        "coarse": LayeredFrozenFlowAtmosphere(_config(48, band_draw_reference_screen_size=128)),
        "fine": LayeredFrozenFlowAtmosphere(_config(64, band_draw_reference_screen_size=128)),
    }
    report = compare_paired_band_fields(default["coarse"], default["fine"], points_per_axis=32)
    # Recorded 11.7 % on the ten-layer 2 m configuration: the dilation's signature, far from exact.
    assert report["relative_difference"] > 0.02
    assert report["dilation"]["exact_physical_pairing"] is False
    assert report["common_band_screen_size"] == 96
    with pytest.raises(PairingError):
        compare_paired_band_fields(default["coarse"], default["fine"], points_per_axis=1)
