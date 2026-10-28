"""Direct replay and canonical-order contracts for AO-REF-009 sweeps."""

from __future__ import annotations

import numpy as np
import pytest

from shwfs_ao.calibration import calibrate_interaction_matrix
from shwfs_ao.control.sweeps import (
    ControlSweepError,
    gain_delay_stability_map,
    gain_scan,
    latency_scan,
    photon_scan,
    read_noise_scan,
)
from shwfs_ao.core.random import NamedRandomStreams
from tests.control.test_loop import (
    _CalibrationSensor,
    _RuntimeWfs,
    _ScalarDmProbeBasis,
    _components,
    _config,
)


@pytest.fixture(scope="module")
def sweep_interaction():
    return calibrate_interaction_matrix(
        _ScalarDmProbeBasis(),
        _CalibrationSensor(),
        1.0e-9,
        random_streams=NamedRandomStreams(3),
    )


def _arguments(interaction, config, *, extra_shot_draws: int = 0):
    components = _components(
        interaction,
        config,
        extra_shot_draws=extra_shot_draws,
    )
    events, atmosphere, wfs, reconstructor, projector, _, dm = components
    streams = NamedRandomStreams(config.root_seed)
    arguments = {
        "random_streams": streams,
        "atmosphere": atmosphere,
        "wfs": wfs,
        "dm": dm,
        "interaction_matrix": interaction,
        "reconstructor": reconstructor,
        "command_projector": projector,
        "include_noise": True,
    }
    return components, events, streams, arguments


def test_gain_scan_resets_every_point_and_is_independent_of_input_order(
    sweep_interaction,
) -> None:
    config = _config(n_steps=3, gain=0.4)

    def run(axis: tuple[float, ...]):
        components, events, streams, arguments = _arguments(
            sweep_interaction,
            config,
            extra_shot_draws=1,
        )
        results = gain_scan(axis, config, **arguments)
        return results, components, events, streams

    forward, _, forward_events, forward_streams = run((0.8, 0.2, 0.5))
    reverse, _, reverse_events, reverse_streams = run((0.5, 0.2, 0.8))

    assert tuple(forward) == tuple(reverse) == (0.2, 0.5, 0.8)
    assert forward_events.count("atmosphere.reset") == 3
    assert reverse_events.count("atmosphere.reset") == 3
    for gain in forward:
        np.testing.assert_array_equal(
            forward[gain].post_update_residual_opd_rms_m,
            reverse[gain].post_update_residual_opd_rms_m,
        )
        assert forward[gain].metadata["component_hashes"]["controller"] == (
            reverse[gain].metadata["component_hashes"]["controller"]
        )

    # The provider is reset at every point.  Its final shot-noise state is
    # therefore exactly one n-step run, rather than all three concatenated.
    control = NamedRandomStreams(config.root_seed)
    control.generator("detector.shot_noise").normal(size=config.n_steps)
    expected_next = control.generator("detector.shot_noise").integers(0, 2**32, 6)
    np.testing.assert_array_equal(
        forward_streams.generator("detector.shot_noise").integers(0, 2**32, 6),
        expected_next,
    )
    np.testing.assert_array_equal(
        reverse_streams.generator("detector.shot_noise").integers(0, 2**32, 6),
        expected_next,
    )


def test_latency_and_gain_delay_scans_use_sorted_unique_canonical_points(
    sweep_interaction,
) -> None:
    config = _config(n_steps=3)
    _, latency_events, _, latency_arguments = _arguments(
        sweep_interaction,
        config,
    )
    latency_results = latency_scan((2, 0, 1), config, **latency_arguments)

    assert tuple(latency_results) == (0, 1, 2)
    assert latency_events.count("atmosphere.reset") == 3
    for latency, history in latency_results.items():
        assert history.metadata["component_hashes"]["loop_config"] != ""
        # An increment reconstructed at frame zero cannot be released before
        # the configured number of frames.
        np.testing.assert_allclose(
            history.released_delta_norm_m[:latency],
            0.0,
        )

    _, map_events, _, map_arguments = _arguments(sweep_interaction, config)
    stability = gain_delay_stability_map(
        (0.7, 0.2),
        (2, 0),
        config,
        **map_arguments,
    )
    assert tuple(stability) == (
        (0.2, 0),
        (0.2, 2),
        (0.7, 0),
        (0.7, 2),
    )
    assert map_events.count("atmosphere.reset") == 4


@pytest.mark.parametrize(
    ("scan", "axis", "expected"),
    [
        (photon_scan, (1_000.0, 100.0), (100.0, 1_000.0)),
        (read_noise_scan, (3.0, 0.0, 1.0), (0.0, 1.0, 3.0)),
    ],
)
def test_detector_parameter_sweeps_build_one_fresh_wfs_per_sorted_point(
    sweep_interaction,
    scan,
    axis: tuple[float, ...],
    expected: tuple[float, ...],
) -> None:
    config = _config(n_steps=2)
    components, events, streams, arguments = _arguments(
        sweep_interaction,
        config,
    )
    arguments.pop("wfs")
    built: list[float] = []

    def factory(value: float):
        built.append(value)
        return _RuntimeWfs(events)

    results = scan(
        axis,
        config,
        wfs_factory=factory,
        **arguments,
    )

    assert tuple(results) == expected
    assert tuple(built) == expected
    assert events.count("atmosphere.reset") == len(expected)
    assert all(history.n_steps == config.n_steps for history in results.values())


@pytest.mark.parametrize(
    ("operation", "match"),
    [
        (lambda kwargs: gain_scan((0.2, 0.2), kwargs.pop("config"), **kwargs), "duplicate"),
        (lambda kwargs: latency_scan((0, -1), kwargs.pop("config"), **kwargs), "non-negative"),
    ],
)
def test_invalid_sweep_axes_fail_before_resetting_components(
    sweep_interaction,
    operation,
    match: str,
) -> None:
    config = _config()
    _, events, _, arguments = _arguments(sweep_interaction, config)
    arguments["config"] = config

    with pytest.raises(ControlSweepError, match=match):
        operation(arguments)

    assert events == []

