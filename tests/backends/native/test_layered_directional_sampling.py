"""Directional (off-axis) sampling of the native layered atmosphere.

The on-axis guide star sees layer ``l`` at pupil coordinate ``r - v_l t``;
a science direction ``theta`` sees it at ``r + h_l theta - v_l t``.  These
checks pin the identity at ``theta = 0``, the ground-layer limit, the signed
fractional shift of both spectral components against analytic patterns, and
the backend contract.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from shwfs_ao.backends.native.atmosphere import NativeAtmosphereError
from shwfs_ao.backends.native.layered_atmosphere import (
    DIRECTIONAL_SAMPLING_MODEL,
    FrozenFlowLayer,
    LayeredFrozenFlowAtmosphere,
    LayeredFrozenFlowAtmosphereConfig,
)
from shwfs_ao.core.wavefront import remove_piston


ARCSEC = math.pi / 648000.0


def _config(layers, *, grid=40, diameter=2.0, seed=3):
    return LayeredFrozenFlowAtmosphereConfig(
        grid_size=grid,
        delta_m=diameter / (grid - 1),
        pupil_diameter_m=diameter,
        r0_m=0.12,
        layers=layers,
        outer_scale_m=25.0,
        root_seed=seed,
    )


def _two_layers(high_altitude=8000.0):
    return (
        FrozenFlowLayer(cn2_fraction=0.6, wind_m_per_s=(4.0, -2.5), altitude_m=0.0),
        FrozenFlowLayer(cn2_fraction=0.4, wind_m_per_s=(-7.0, 3.0), altitude_m=high_altitude),
    )


def test_zero_direction_is_the_on_axis_sample_bit_for_bit_and_keeps_the_clock() -> None:
    atmosphere = LayeredFrozenFlowAtmosphere(_config(_two_layers()))
    on_axis = atmosphere.opd_at(0.004)
    zero = atmosphere.directional_opd_at(0.004, (0.0, 0.0))
    np.testing.assert_array_equal(zero, on_axis)
    # A directional sample at an earlier time does not retreat the clock, so
    # the loop can sample science directions after later WFS sub-samples.
    atmosphere.opd_at(0.006)
    earlier = atmosphere.directional_opd_at(0.004, (0.0, 0.0))
    np.testing.assert_array_equal(earlier, on_axis)
    with pytest.raises(NativeAtmosphereError, match="nondecreasing"):
        atmosphere.opd_at(0.004)
    assert atmosphere.metadata["directional_sampling"] == DIRECTIONAL_SAMPLING_MODEL


def test_a_ground_layer_only_atmosphere_is_the_same_in_every_direction() -> None:
    layers = (
        FrozenFlowLayer(cn2_fraction=0.7, wind_m_per_s=(5.0, 1.0), altitude_m=0.0),
        FrozenFlowLayer(cn2_fraction=0.3, wind_m_per_s=(-3.0, 6.0), altitude_m=0.0),
    )
    atmosphere = LayeredFrozenFlowAtmosphere(_config(layers))
    reference = atmosphere.opd_at(0.01)
    for direction in ((5 * ARCSEC, 0.0), (0.0, -20 * ARCSEC), (30 * ARCSEC, 30 * ARCSEC)):
        np.testing.assert_array_equal(atmosphere.directional_opd_at(0.01, direction), reference)
    assert atmosphere.max_directional_displacement_m == 0.0


def test_a_high_layer_moves_with_direction_and_records_the_displacement() -> None:
    atmosphere = LayeredFrozenFlowAtmosphere(_config(_two_layers(8000.0)))
    reference = atmosphere.opd_at(0.0)
    shifted = atmosphere.directional_opd_at(0.0, (10 * ARCSEC, 0.0))
    assert not np.array_equal(shifted, reference)
    assert atmosphere.max_directional_displacement_m == pytest.approx(8000.0 * 10 * ARCSEC)
    assert atmosphere.max_travel_m == 0.0
    assert atmosphere.layer_altitudes_m == (0.0, 8000.0)


def _single_periodic_mode(atmosphere, layer, kx, ky, amplitude_rad, phase_rad):
    """Replace every spectral coefficient with one periodic-band mode of one layer."""

    size = atmosphere.config.screen_size
    for index, coefficients in enumerate(atmosphere._band_coefficients):
        coefficients[...] = 0.0
    for blocks in atmosphere._low_frequency_blocks:
        for block in blocks:
            block.coefficients[...] = 0.0
    # ifft of a single entry C at (ky, kx) gives C/size**2 * exp(+2 pi i (kx x + ky y)/size).
    atmosphere._band_coefficients[layer][ky % size, kx % size] = (
        amplitude_rad * size**2 * np.exp(1j * phase_rad)
    )


def _single_analytic_mode(atmosphere, layer, level, iy, ix, amplitude_rad, phase_rad):
    """Replace every spectral coefficient with one analytic low-frequency mode."""

    for coefficients in atmosphere._band_coefficients:
        coefficients[...] = 0.0
    for blocks in atmosphere._low_frequency_blocks:
        for block in blocks:
            block.coefficients[...] = 0.0
    block = atmosphere._low_frequency_blocks[layer][level]
    block.coefficients[iy, ix] = amplitude_rad * np.exp(1j * phase_rad)
    return float(block.nodes_per_m[ix]), float(block.nodes_per_m[iy])


def _expected(config, layer, fx, fy, amplitude_rad, phase_rad, time_s, direction, mask):
    """``A cos(2 pi f . (r - s) + phi)`` on the pupil grid, piston removed, in metres."""

    coordinates = np.arange(config.grid_size) * config.delta_m
    x, y = np.meshgrid(coordinates, coordinates)
    wind = config.layers[layer].wind_m_per_s
    altitude = config.layers[layer].altitude_m
    shift_x = wind[0] * time_s - altitude * direction[0]
    shift_y = wind[1] * time_s - altitude * direction[1]
    phase = amplitude_rad * np.cos(
        2.0 * np.pi * (fx * (x - shift_x) + fy * (y - shift_y)) + phase_rad
    )
    return remove_piston(phase, mask) * config.phase_reference_wavelength_m / (2.0 * np.pi)


@pytest.mark.parametrize(
    "direction_samples",
    [(3.3, -1.7), (-2.25, 4.6), (0.4, 0.0), (0.0, -0.75)],
)
@pytest.mark.parametrize("component", ["periodic", "analytic"])
def test_signed_fractional_shifts_match_the_analytic_pattern_in_both_components(
    direction_samples, component
) -> None:
    config = _config(_two_layers(8000.0), grid=40)
    atmosphere = LayeredFrozenFlowAtmosphere(config)
    layer = 1
    altitude = config.layers[layer].altitude_m
    # A direction whose footprint displacement is the requested fractional
    # number of grid samples on each axis (signed), with nonzero wind at a
    # known time so both translations are present.
    direction = (
        direction_samples[0] * config.delta_m / altitude,
        direction_samples[1] * config.delta_m / altitude,
    )
    time_s = 0.0137
    amplitude, phase = 0.8, 0.9
    if component == "periodic":
        kx, ky = 5, -3  # oblique sinusoid of the periodic band
        _single_periodic_mode(atmosphere, layer, kx, ky, amplitude, phase)
        fx = kx / config.screen_period_m
        fy = ky / config.screen_period_m
    else:
        fx, fy = _single_analytic_mode(atmosphere, layer, 1, 7, 4, amplitude, phase)
    mask = atmosphere.pupil_mask
    sampled = atmosphere.directional_opd_at(time_s, direction)
    expected = _expected(config, layer, fx, fy, amplitude, phase, time_s, direction, mask)
    scale = float(np.nanmax(np.abs(expected)))
    assert np.nanmax(np.abs(sampled - expected)) <= 1e-12 * scale
    # Sign and axis errors would be visible: the mirrored and swapped
    # directions give different maps unless the shift is trivial.
    if direction_samples[0] and direction_samples[1]:
        for wrong in ((-direction[0], direction[1]), (direction[1], direction[0])):
            alternative = _expected(config, layer, fx, fy, amplitude, phase, time_s, wrong, mask)
            assert np.nanmax(np.abs(sampled - alternative)) > 1e-3 * scale


def test_directions_are_validated() -> None:
    atmosphere = LayeredFrozenFlowAtmosphere(_config(_two_layers()))
    with pytest.raises(NativeAtmosphereError, match="direction_rad"):
        atmosphere.directional_opd_at(0.0, (1.0,))  # type: ignore[arg-type]
    with pytest.raises(NativeAtmosphereError, match="direction_rad"):
        atmosphere.directional_opd_at(0.0, (math.nan, 0.0))
    with pytest.raises(NativeAtmosphereError, match="non-negative"):
        atmosphere.directional_opd_at(-1.0, (0.0, 0.0))
