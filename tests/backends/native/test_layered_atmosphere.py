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


# -- T2 G1 (2026-10-21): fixed-physics pairing options ------------------------------

from dataclasses import asdict  # noqa: E402

from shwfs_ao.backends.native.layered_atmosphere import (  # noqa: E402
    PAIRED_BAND_ALGORITHM,
    SCREEN_PERIOD_RULES,
    _QUADRATURE_SUBSAMPLES,
    canonical_identity_payload,
    common_band_mask,
    signed_fft_indices,
)
from shwfs_ao.core.hashing import component_config_hash, stable_hash  # noqa: E402

PAIRING_FIELDS = ("band_draw_reference_screen_size", "band_limit_screen_size", "screen_period_rule")
PAIRING_METADATA = (
    *PAIRING_FIELDS,
    "band_limit_half_width_index",
    "paired_band_algorithm",
    "band_power_retained_fraction",
    "frequency_unit",
    "frequency_spacing_per_m",
    "reference_draw_normals_per_layer",
    "nyquist_index_handling",
)


def _paired_config(grid: int, **extra) -> LayeredFrozenFlowAtmosphereConfig:
    return LayeredFrozenFlowAtmosphereConfig(
        grid_size=grid,
        delta_m=2.0 / (grid - 1),  # the geometry's D / (N - 1)
        pupil_diameter_m=2.0,
        r0_m=R0_M,
        layers=_eso_layers(),
        outer_scale_m=OUTER_SCALE_M,
        root_seed=5,
        **extra,
    )


def _pre_change_identity(atmosphere: LayeredFrozenFlowAtmosphere) -> str:
    """The identity formula from before the pairing fields existed, rebuilt from the instance.

    Its payload is the raw ``asdict(config)`` of the pre-change dataclass (the
    current one without the three trailing fields).  The digest binds the
    pupil mask and the stream ids, so it is rebuilt here rather than pinned.
    """

    payload = asdict(atmosphere.config)
    for name in PAIRING_FIELDS:
        payload.pop(name)
    streams = atmosphere._random_streams
    return component_config_hash(
        "native.layered_frozen_flow_atmosphere",
        {
            "config": payload,
            "pupil_mask_hash": stable_hash(atmosphere.pupil_mask, namespace="native-atmosphere-pupil"),
            "spectrum_model": LAYERED_SPECTRUM_MODEL,
            "quadrature_subsamples": _QUADRATURE_SUBSAMPLES,
            "random_derivation_scheme_id": streams.derivation_scheme_id,
            "random_scope_stream_id": streams.stream_id("atmosphere", key=("realization", 0)),
        },
    )


def _normals(atmosphere: LayeredFrozenFlowAtmosphere, layer: int = 0) -> np.ndarray:
    """The standard normals behind a layer's band coefficients (zero where the band has no power)."""

    config = atmosphere.config
    power = _periodic_band_power(config, atmosphere._frequencies_per_m)
    amplitude = config.layer_r0_m[layer] ** (-5.0 / 6.0)
    scale = np.sqrt(power) * amplitude * config.screen_size**2
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(power > 0.0, atmosphere._band_coefficients[layer] / np.where(power > 0.0, scale, 1.0), 0.0)


def test_the_default_keeps_the_pre_change_identity_payload_draw_and_metadata() -> None:
    atmosphere = LayeredFrozenFlowAtmosphere(_paired_config(48))
    assert atmosphere.config.pairing_active is False
    assert atmosphere.config_hash == _pre_change_identity(atmosphere)
    payload = canonical_identity_payload(atmosphere.config)
    assert set(payload) == set(asdict(atmosphere.config)) - set(PAIRING_FIELDS)
    assert "paired_band_algorithm" not in payload
    assert not any(key in atmosphere.metadata for key in PAIRING_METADATA)
    # An explicit default rule is the default: same identity, same draw.
    explicit = LayeredFrozenFlowAtmosphere(_paired_config(48, screen_period_rule="pupil_array"))
    assert explicit.config_hash == atmosphere.config_hash
    np.testing.assert_array_equal(explicit.opd_at(0.001), atmosphere.opd_at(0.001))
    assert SCREEN_PERIOD_RULES == ("pupil_array", "pupil_diameter")


def test_a_reference_equal_to_the_screen_is_the_same_draw_under_its_own_identity() -> None:
    default = LayeredFrozenFlowAtmosphere(_paired_config(48))
    same = LayeredFrozenFlowAtmosphere(_paired_config(48, band_draw_reference_screen_size=96))
    for time_s in (0.0, 0.002):
        np.testing.assert_array_equal(same.opd_at(time_s), default.opd_at(time_s))
    for left, right in zip(same._band_coefficients, default._band_coefficients):
        np.testing.assert_array_equal(left, right)
    for left_blocks, right_blocks in zip(same._low_frequency_blocks, default._low_frequency_blocks):
        for left, right in zip(left_blocks, right_blocks):
            np.testing.assert_array_equal(left.coefficients, right.coefficients)
    # Explicit means identity-bearing, numbers notwithstanding.
    assert same.config_hash != default.config_hash
    assert same.config_hash != _pre_change_identity(same)
    assert canonical_identity_payload(same.config)["paired_band_algorithm"] == PAIRED_BAND_ALGORITHM
    assert canonical_identity_payload(same.config)["band_draw_reference_screen_size"] == 96
    assert "band_limit_screen_size" not in canonical_identity_payload(same.config)
    metadata = same.metadata
    assert all(key in metadata for key in PAIRING_METADATA)
    assert metadata["band_draw_reference_screen_size"] == 96 and metadata["band_limit_screen_size"] is None
    assert metadata["paired_band_algorithm"] == PAIRED_BAND_ALGORITHM
    assert metadata["band_power_retained_fraction"] == 1.0
    assert metadata["frequency_unit"] == "cycles_per_m"
    assert metadata["frequency_spacing_per_m"] == pytest.approx(1.0 / same.config.screen_period_m)
    assert metadata["reference_draw_normals_per_layer"] == 2 * 96 * 96


def test_a_coarser_screen_reads_its_sub_band_from_the_reference_draw() -> None:
    """Default rule: equal signed index, equal normals; the low-frequency draws follow the same state."""

    fine = LayeredFrozenFlowAtmosphere(_paired_config(64, band_draw_reference_screen_size=128))
    coarse = LayeredFrozenFlowAtmosphere(_paired_config(48, band_draw_reference_screen_size=128))
    position = signed_fft_indices(96) % 128
    fine_normals = _normals(fine)[np.ix_(position, position)]
    coarse_normals = _normals(coarse)
    live = _periodic_band_power(coarse.config, coarse._frequencies_per_m) > 0.0
    np.testing.assert_allclose(coarse_normals[live], fine_normals[live], rtol=1.0e-12, atol=0.0)
    # Both draw the same 2 R**2 normals first, so the generator state the
    # low-frequency draws see is the same; their power tables differ under
    # the default rule (another step), so the coefficients differ by the
    # ratio of the table amplitudes only.
    coarse_block = coarse._low_frequency_blocks[0][0]
    fine_block = fine._low_frequency_blocks[0][0]
    coarse_power = _low_frequency_tables(coarse.config)[0][1]
    fine_power = _low_frequency_tables(fine.config)[0][1]
    live = (coarse_power > 0.0) & (fine_power > 0.0)
    ratio = coarse_block.coefficients[live] / fine_block.coefficients[live]
    np.testing.assert_allclose(ratio, np.sqrt(coarse_power[live] / fine_power[live]), rtol=1.0e-12, atol=0.0)
    # Different hashes: the screen size and the reference both enter.
    assert fine.config_hash != coarse.config_hash
    # An unpaired fine screen draws other normals at those indices.
    unpaired = LayeredFrozenFlowAtmosphere(_paired_config(48))
    assert not np.allclose(_normals(unpaired)[live[: 0] if False else slice(None)], coarse_normals)


def test_the_pupil_diameter_rule_pairs_physical_frequencies_exactly() -> None:
    coarse = LayeredFrozenFlowAtmosphere(_paired_config(48, screen_period_rule="pupil_diameter", band_draw_reference_screen_size=126))
    fine = LayeredFrozenFlowAtmosphere(_paired_config(64, screen_period_rule="pupil_diameter", band_draw_reference_screen_size=126))
    assert coarse.config.screen_size == 94 and fine.config.screen_size == 126
    assert coarse.config.screen_period_m == pytest.approx(4.0, rel=1.0e-12)
    assert fine.config.screen_period_m == pytest.approx(4.0, rel=1.0e-12)
    # The physical coefficient (inverse-FFT scaling undone) is the same number
    # at the same signed index on both grids; the low-frequency coefficients are identical.
    position = signed_fft_indices(94) % 126
    np.testing.assert_allclose(
        coarse._band_coefficients[0] / 94**2,
        fine._band_coefficients[0][np.ix_(position, position)] / 126**2,
        rtol=1.0e-12,
        atol=0.0,
    )
    for left_blocks, right_blocks in zip(coarse._low_frequency_blocks, fine._low_frequency_blocks):
        for left, right in zip(left_blocks, right_blocks):
            np.testing.assert_array_equal(left.coefficients, right.coefficients)
    assert coarse.metadata["screen_period_rule"] == "pupil_diameter"
    assert coarse.metadata["screen_period_m"] == pytest.approx(4.0)
    # The rule alone is identity-bearing and recorded; the sub-band algorithm is named only with a draw option.
    alone = LayeredFrozenFlowAtmosphere(_paired_config(48, screen_period_rule="pupil_diameter"))
    assert alone.config_hash != LayeredFrozenFlowAtmosphere(_paired_config(48)).config_hash
    assert alone.metadata["paired_band_algorithm"] is None
    assert "paired_band_algorithm" not in canonical_identity_payload(alone.config)
    assert canonical_identity_payload(alone.config)["screen_period_rule"] == "pupil_diameter"


def test_the_common_band_zeroes_exactly_the_outside_modes_and_records_its_power() -> None:
    config = _paired_config(64, screen_period_rule="pupil_diameter", band_draw_reference_screen_size=126, band_limit_screen_size=94)
    atmosphere = LayeredFrozenFlowAtmosphere(config)
    mask = common_band_mask(126, 94)
    indices = signed_fft_indices(126)
    assert config.band_limit_half_width_index == 46
    assert np.array_equal(mask, (np.abs(indices) <= 46)[:, None] & (np.abs(indices) <= 46)[None, :])
    coefficients = atmosphere._band_coefficients[0]
    assert np.all(coefficients[~mask] == 0.0)
    assert np.all(coefficients[mask & (_periodic_band_power(config, atmosphere._frequencies_per_m) > 0.0)] != 0.0)
    unlimited = LayeredFrozenFlowAtmosphere(_paired_config(64, screen_period_rule="pupil_diameter", band_draw_reference_screen_size=126))
    np.testing.assert_array_equal(coefficients[mask], unlimited._band_coefficients[0][mask])
    power = _periodic_band_power(config, atmosphere._frequencies_per_m)
    assert atmosphere.band_power_retained_fraction == pytest.approx(float(np.sum(power * mask) / np.sum(power)))
    assert 0.98 < atmosphere.band_power_retained_fraction < 1.0
    assert atmosphere.metadata["band_power_retained_fraction"] == atmosphere.band_power_retained_fraction
    assert atmosphere.metadata["band_limit_half_width_index"] == 46
    # The coarsest screen limited to its own size drops its own Nyquist row and column.
    own = LayeredFrozenFlowAtmosphere(_paired_config(48, screen_period_rule="pupil_diameter", band_draw_reference_screen_size=126, band_limit_screen_size=94))
    nyquist = signed_fft_indices(94) == -47
    assert np.all(own._band_coefficients[0][nyquist, :] == 0.0) and np.all(own._band_coefficients[0][:, nyquist] == 0.0)
    assert own.config_hash != LayeredFrozenFlowAtmosphere(_paired_config(48, screen_period_rule="pupil_diameter", band_draw_reference_screen_size=126)).config_hash


def test_storage_modes_resets_and_realizations_agree_under_the_pairing_options() -> None:
    options = dict(screen_period_rule="pupil_diameter", band_draw_reference_screen_size=126, band_limit_screen_size=94)
    materialized = LayeredFrozenFlowAtmosphere(_paired_config(64, **options))
    regenerated = LayeredFrozenFlowAtmosphere(_paired_config(64, **options), band_coefficient_storage="regenerate")
    assert materialized.config_hash == regenerated.config_hash
    for time_s in (0.0, 0.0015, 0.004):
        np.testing.assert_array_equal(materialized.opd_at(time_s), regenerated.opd_at(time_s))
    first = materialized.opd_at(0.004)
    materialized.reset(realization_index=1)
    other = materialized.opd_at(0.004)
    pupil = materialized.pupil_mask
    assert not np.allclose(other[pupil], first[pupil])
    materialized.reset(realization_index=0)
    np.testing.assert_array_equal(materialized.opd_at(0.004), first)
    assert materialized.metadata["realization_index"] == 0


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"band_draw_reference_screen_size": 90}, "at least the screen size"),
        ({"band_limit_screen_size": 10}, "keeps no periodic mode"),
        ({"band_draw_reference_screen_size": True}, "must be an integer"),
        ({"band_draw_reference_screen_size": 96.0}, "must be an integer"),
        ({"band_limit_screen_size": 100}, "must not exceed the screen size"),
        ({"band_limit_screen_size": 1}, "must be >= 2"),
        ({"band_limit_screen_size": np.True_}, "must be an integer"),
        ({"screen_period_rule": "diameter"}, "screen_period_rule"),
        ({"screen_period_rule": None}, "screen_period_rule"),
        ({"band_draw_reference_screen_size": 100, "band_limit_screen_size": 98}, "must not exceed the screen size"),
    ],
)
def test_invalid_pairing_options_are_refused_before_allocation(overrides, message) -> None:
    with pytest.raises(NativeAtmosphereError, match=message):
        _paired_config(48, **overrides)


def test_the_pupil_diameter_rule_needs_a_whole_number_of_spacings_and_a_screen_holding_the_pupil() -> None:
    with pytest.raises(NativeAtmosphereError, match="whole number of grid spacings"):
        LayeredFrozenFlowAtmosphereConfig(
            grid_size=48, delta_m=2.0 / 47.5, pupil_diameter_m=2.0, r0_m=R0_M, layers=_eso_layers(),
            screen_period_rule="pupil_diameter",
        )
    with pytest.raises(NativeAtmosphereError, match="must hold the pupil array"):
        LayeredFrozenFlowAtmosphereConfig(
            grid_size=48, delta_m=2.0 / 47.0, pupil_diameter_m=2.0, r0_m=R0_M, layers=_eso_layers(),
            screen_period_rule="pupil_diameter", screen_period_factor=1,
        )


def test_signed_indices_and_the_common_band_mask_follow_numpy_conventions() -> None:
    assert signed_fft_indices(8).tolist() == [0, 1, 2, 3, -4, -3, -2, -1]
    assert signed_fft_indices(7).tolist() == [0, 1, 2, 3, -3, -2, -1]
    assert np.array_equal(signed_fft_indices(8), np.rint(np.fft.fftfreq(8) * 8).astype(int))
    mask = common_band_mask(8, 8)
    kept = np.abs(signed_fft_indices(8)) <= 3
    assert np.array_equal(mask, kept[:, None] & kept[None, :])  # the Nyquist index -4 is outside its own band
    assert np.array_equal(common_band_mask(8, 7), mask)  # an odd 7-grid holds |k| <= 3 as well
    assert common_band_mask(8, 2).sum() == 1 and common_band_mask(8, 3).sum() == 9
    with pytest.raises(NativeAtmosphereError):
        common_band_mask(8, 9)
    with pytest.raises(NativeAtmosphereError):
        common_band_mask(8, 1)
