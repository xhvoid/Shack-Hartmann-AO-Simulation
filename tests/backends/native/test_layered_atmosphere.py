"""Physics and contract checks for the native multi-layer frozen-flow atmosphere."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.special import j1, jv

from shwfs_ao.backends.native.atmosphere import (
    NativeAtmosphereError,
    von_karman_piston_removed_variance_rad2,
)
from shwfs_ao.backends.native.layered_atmosphere import (
    LAYERED_SPECTRUM_MODEL,
    FrozenFlowLayer,
    LayeredFrozenFlowAtmosphere,
    LayeredFrozenFlowAtmosphereConfig,
    _low_frequency_tables,
    _periodic_band_power,
)
from shwfs_ao.core.protocols import AtmosphereModel
from shwfs_ao.core.random import NamedRandomStreams
from shwfs_ao.io import eso_elt_turbulence_profile


R0_M = 0.13
OUTER_SCALE_M = 25.0
WAVELENGTH_M = 500.0e-9


def _eso_layers() -> tuple[FrozenFlowLayer, ...]:
    return tuple(
        FrozenFlowLayer(
            cn2_fraction=layer.cn2_fraction,
            wind_m_per_s=layer.wind_m_per_s,
            altitude_m=layer.altitude_m,
        )
        for layer in eso_elt_turbulence_profile().layers
    )


def _config(
    *,
    diameter_m: float = 2.0,
    grid_size: int = 48,
    layers: tuple[FrozenFlowLayer, ...] | None = None,
    root_seed: int = 5,
) -> LayeredFrozenFlowAtmosphereConfig:
    return LayeredFrozenFlowAtmosphereConfig(
        grid_size=grid_size,
        delta_m=diameter_m / grid_size,
        pupil_diameter_m=diameter_m,
        r0_m=R0_M,
        layers=_eso_layers() if layers is None else layers,
        outer_scale_m=OUTER_SCALE_M,
        root_seed=root_seed,
    )


def _aperture_filters(frequency: np.ndarray, diameter_m: float):
    """Piston- and tip/tilt-removal power filters of a circular aperture."""

    argument = np.pi * diameter_m * np.asarray(frequency, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        airy = np.where(argument > 0.0, 2.0 * j1(argument) / argument, 1.0)
        tilt = np.where(argument > 0.0, 16.0 * (jv(2, argument) / argument) ** 2, 0.0)
    return 1.0 - airy**2, 1.0 - airy**2 - tilt


def _model_variances(config: LayeredFrozenFlowAtmosphereConfig) -> tuple[float, float]:
    """Expected piston- and tilt-removed pupil variance of the discrete model."""

    frequencies = np.fft.fftfreq(config.screen_size, d=config.delta_m)
    fx, fy = np.meshgrid(frequencies, frequencies)
    piston, tilt = _aperture_filters(np.hypot(fx, fy), config.pupil_diameter_m)
    power = _periodic_band_power(config, frequencies)
    variances = [float(np.sum(power * piston)), float(np.sum(power * tilt))]
    for nodes, node_power in _low_frequency_tables(config):
        nx, ny = np.meshgrid(nodes, nodes)
        piston, tilt = _aperture_filters(np.hypot(nx, ny), config.pupil_diameter_m)
        variances[0] += float(np.sum(node_power * piston))
        variances[1] += float(np.sum(node_power * tilt))
    # The tables are for r0 = 1 m; the summed layers carry the integrated r0.
    scale = config.r0_m ** (-5.0 / 3.0)
    return variances[0] * scale, variances[1] * scale


def _continuum_tilt_removed_variance(diameter_m: float) -> float:
    log_frequency = np.linspace(-8.0, 4.0, 240_001)
    frequency = 10.0**log_frequency
    _, tilt = _aperture_filters(frequency, diameter_m)
    inverse_l0 = 1.0 / OUTER_SCALE_M
    psd = 0.023 * R0_M ** (-5.0 / 3.0) * (frequency**2 + inverse_l0**2) ** (-11.0 / 6.0)
    weighted = 2.0 * np.pi * frequency**2 * psd * tilt * math.log(10.0)
    return float(np.sum(0.5 * (weighted[1:] + weighted[:-1]) * np.diff(log_frequency)))


@pytest.mark.parametrize(("diameter_m", "grid_size"), [(2.0, 72), (10.0, 384)])
def test_the_discrete_spectrum_carries_the_von_karman_pupil_variance(
    diameter_m: float, grid_size: int
) -> None:
    """Exact expectation of the discretization, with no Monte Carlo noise."""

    config = _config(diameter_m=diameter_m, grid_size=grid_size)
    piston_removed, tilt_removed = _model_variances(config)

    assert piston_removed == pytest.approx(
        von_karman_piston_removed_variance_rad2(diameter_m, R0_M, OUTER_SCALE_M),
        rel=0.01,
    )
    assert tilt_removed == pytest.approx(
        _continuum_tilt_removed_variance(diameter_m), rel=0.01
    )


def test_realizations_have_the_variance_their_spectrum_promises() -> None:
    config = _config()
    atmosphere = LayeredFrozenFlowAtmosphere(config)
    pupil = atmosphere.pupil_mask
    coordinates = (np.arange(config.grid_size) - config.grid_size // 2) * config.delta_m
    x_m, y_m = np.meshgrid(coordinates, coordinates)
    basis = np.stack([np.ones(int(pupil.sum())), x_m[pupil], y_m[pupil]], axis=1)

    tilt_removed = []
    for index in range(160):
        atmosphere.reset(realization_index=index)
        phase = atmosphere.opd_at(0.0)[pupil] * 2.0 * np.pi / WAVELENGTH_M
        fit, *_ = np.linalg.lstsq(basis, phase, rcond=None)
        tilt_removed.append(float(np.var(phase - basis @ fit)))

    expected = _model_variances(config)[1]
    # 160 realizations: the standard error of the mean is about 3 %.
    assert np.mean(tilt_removed) == pytest.approx(expected, rel=0.12)


def test_frozen_flow_is_an_exact_translation_at_any_speed() -> None:
    grid = 48
    delta = 2.0 / grid
    dt = 0.01
    # Three pixels right and two pixels down per dt; then half a pixel per dt.
    layer = FrozenFlowLayer(1.0, (3.0 * delta / dt, -2.0 * delta / dt))
    atmosphere = LayeredFrozenFlowAtmosphere(_config(layers=(layer,)))
    start, later = atmosphere._phase_rad(0.0), atmosphere._phase_rad(dt)
    # The pattern advects with the wind: later(y, x) = start(y + 2, x - 3).
    assert np.max(np.abs(later[: grid - 2, 3:] - start[2:, : grid - 3])) < 1.0e-12

    slow = LayeredFrozenFlowAtmosphere(
        _config(layers=(FrozenFlowLayer(1.0, (0.5 * delta / dt, 0.0)),))
    )
    initial, half, whole = (slow._phase_rad(t) for t in (0.0, dt, 2.0 * dt))
    assert np.max(np.abs(whole[:, 1:] - initial[:, :-1])) < 1.0e-12
    # A sub-pixel step changes the frame instead of rounding it away.
    assert np.max(np.abs(half - initial)) > 1.0e-3


def test_layers_travel_without_limit_and_flag_periodic_repetition() -> None:
    config = _config()
    atmosphere = LayeredFrozenFlowAtmosphere(config)
    fastest = max(math.hypot(*layer.wind_m_per_s) for layer in config.layers)
    beyond = 1.5 * config.screen_period_m / fastest

    opd = atmosphere.opd_at(beyond)
    assert np.all(np.isfinite(opd[atmosphere.pupil_mask]))
    assert atmosphere.max_travel_m == pytest.approx(fastest * beyond)
    assert atmosphere.periodic_band_repeated
    atmosphere.reset(realization_index=0)
    assert not atmosphere.periodic_band_repeated


def test_output_is_piston_free_opd_in_metres_with_nan_outside_the_pupil() -> None:
    atmosphere = LayeredFrozenFlowAtmosphere(_config())
    pupil = atmosphere.pupil_mask
    opd = atmosphere.opd_at(0.004)

    assert isinstance(atmosphere, AtmosphereModel)
    assert np.all(np.isnan(opd[~pupil]))
    assert np.all(np.isfinite(opd[pupil]))
    assert abs(float(np.mean(opd[pupil]))) < 1.0e-18
    # About sqrt(46.6) rad at 500 nm for a 2 m pupil: hundreds of nanometres.
    assert 1.0e-7 < float(np.std(opd[pupil])) < 2.0e-6
    assert not opd.flags.writeable


def test_realizations_are_deterministic_and_independent() -> None:
    first = LayeredFrozenFlowAtmosphere(_config())
    second = LayeredFrozenFlowAtmosphere(_config())
    other_seed = LayeredFrozenFlowAtmosphere(_config(root_seed=6))
    pupil = first.pupil_mask

    times = (0.0, 0.001, 0.0025)
    frames = [first.opd_at(time_s) for time_s in times]
    for time_s, frame in zip(times, frames):
        np.testing.assert_array_equal(frame, second.opd_at(time_s))
    assert first.config_hash == second.config_hash != other_seed.config_hash

    # reset() replays the same realization from t = 0.
    first.reset(realization_index=0)
    np.testing.assert_array_equal(first.opd_at(0.001), frames[1])
    first.reset(realization_index=1)
    assert not np.allclose(first.opd_at(0.0)[pupil], frames[0][pupil])
    assert not np.allclose(other_seed.opd_at(0.0)[pupil], frames[0][pupil])

    metadata = first.metadata
    assert metadata["realization_index"] == 1
    assert metadata["n_layers"] == 10
    assert metadata["spectrum_model"] == LAYERED_SPECTRUM_MODEL
    assert len(set(metadata["layer_random_stream_ids"])) == 10
    assert metadata["layers"][0]["r0_m"] == pytest.approx(first.config.layer_r0_m[0])
    first.opd_at(0.002)
    with pytest.raises(NativeAtmosphereError, match="nondecreasing"):
        first.opd_at(0.001)


def test_a_supplied_random_stream_must_share_the_root_seed() -> None:
    config = _config()
    scoped = NamedRandomStreams(config.root_seed).scoped("native-atmosphere")
    atmosphere = LayeredFrozenFlowAtmosphere(config, random_streams=scoped)
    assert atmosphere.metadata["random_stream_id"] == scoped.stream_id(
        "atmosphere", key=("realization", 0)
    )
    with pytest.raises(NativeAtmosphereError, match="root_seed"):
        LayeredFrozenFlowAtmosphere(config, random_streams=NamedRandomStreams(99))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"layers": (FrozenFlowLayer(0.6, (1.0, 0.0)),)}, "sum to 1"),
        ({"layers": ()}, "non-empty"),
        ({"inner_quadrature_cells": 48}, "no periodic band"),
        ({"screen_period_factor": 0}, "screen_period_factor"),
    ],
)
def test_inconsistent_configurations_are_refused(overrides, message) -> None:
    values = {
        "grid_size": 48,
        "delta_m": 2.0 / 48,
        "pupil_diameter_m": 2.0,
        "r0_m": R0_M,
        "layers": _eso_layers(),
    }
    values.update(overrides)
    with pytest.raises(NativeAtmosphereError, match=message):
        LayeredFrozenFlowAtmosphereConfig(**values)
    with pytest.raises(NativeAtmosphereError, match="cn2_fraction"):
        FrozenFlowLayer(0.0, (1.0, 0.0))
