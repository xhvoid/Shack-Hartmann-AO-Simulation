"""AO-REF-003A contracts for stable named random streams."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import numpy as np
import pytest

from shwfs_ao.core.random import (
    DEFAULT_RANDOM_DOMAINS,
    DERIVATION_SCHEME_ID,
    NamedRandomStreams,
    RandomStreamError,
)


ROOT = Path(__file__).resolve().parents[2]


def test_required_domains_scheme_and_immutable_nonnegative_root_seed():
    streams = NamedRandomStreams(17)

    assert streams.root_seed == 17
    assert streams.derivation_scheme_id == DERIVATION_SCHEME_ID
    assert streams.registered_domains == DEFAULT_RANDOM_DOMAINS
    with pytest.raises(AttributeError):
        streams.root_seed = 18

    for invalid in (-1, True, 1.5, "17"):
        with pytest.raises(RandomStreamError, match="non-negative integer"):
            NamedRandomStreams(invalid)


def test_registry_rejects_missing_duplicate_invalid_and_unknown_domains():
    with pytest.raises(RandomStreamError, match="missing required domains"):
        NamedRandomStreams(1, domains=("atmosphere",))
    with pytest.raises(RandomStreamError, match="Duplicate random-stream domain"):
        NamedRandomStreams(1, domains=(*DEFAULT_RANDOM_DOMAINS, "calibration"))
    with pytest.raises(RandomStreamError, match="without surrounding whitespace"):
        NamedRandomStreams(1, domains=(*DEFAULT_RANDOM_DOMAINS, " extra"))

    streams = NamedRandomStreams(1)
    with pytest.raises(RandomStreamError, match="Unknown random-stream domain"):
        streams.generator("unregistered")
    with pytest.raises(RandomStreamError, match="Duplicate random-stream domain"):
        streams.register_domain("atmosphere")


def test_persistent_generator_identity_and_reset_exactly_replay_draws():
    streams = NamedRandomStreams(9182)
    detector = streams.generator("detector.realization")
    calibration = streams.generator("calibration")

    assert streams.generator("detector.realization") is detector
    assert streams.generator("calibration") is calibration
    expected_detector = detector.standard_normal(12)
    expected_calibration = calibration.integers(0, 10_000, size=12)

    streams.reset()
    replay_detector = streams.generator("detector.realization")
    replay_calibration = streams.generator("calibration")

    assert replay_detector is not detector
    assert replay_calibration is not calibration
    assert np.array_equal(replay_detector.standard_normal(12), expected_detector)
    assert np.array_equal(
        replay_calibration.integers(0, 10_000, size=12),
        expected_calibration,
    )


def test_keyed_generators_are_fresh_replays_and_do_not_advance_runtime_stream():
    streams = NamedRandomStreams(41)
    control = NamedRandomStreams(41)
    persistent = streams.generator("calibration")

    first_persistent = persistent.random(8)
    first_child = streams.keyed_generator("calibration", key=("poke", 3))
    second_child = streams.keyed_generator("calibration", key=("poke", 3))
    assert first_child is not second_child
    assert np.array_equal(first_child.random(10), second_child.random(10))
    assert streams.stream_id("calibration", key=("poke", 3)) != streams.stream_id(
        "calibration", key=("poke", "3")
    )
    second_persistent = persistent.random(8)

    expected_persistent = control.generator("calibration").random(16)
    assert np.array_equal(
        np.concatenate((first_persistent, second_persistent)),
        expected_persistent,
    )


def test_scoped_views_isolate_nested_calibration_draws_from_runtime_streams():
    streams = NamedRandomStreams(73)
    control = NamedRandomStreams(73)
    runtime = streams.generator("detector.read_noise")
    before = runtime.standard_normal(6)

    scoped = streams.scoped("calibration", key=("probe", 4)).scoped(
        "repeat", key=(2,)
    )
    same_scope = streams.scoped("calibration", key=("probe", 4)).scoped(
        "repeat", key=(2,)
    )
    scoped_generator = scoped.generator("detector.read_noise")
    scoped_draws = scoped_generator.standard_normal(9)

    assert same_scope.generator("detector.read_noise") is scoped_generator
    assert scoped.stream_id("detector.read_noise") == same_scope.stream_id(
        "detector.read_noise"
    )
    assert scoped.stream_id("detector.read_noise") != streams.stream_id(
        "detector.read_noise"
    )
    after = runtime.standard_normal(6)
    expected = control.generator("detector.read_noise").standard_normal(12)
    assert np.array_equal(np.concatenate((before, after)), expected)

    streams.reset()
    replay_scoped_generator = scoped.generator("detector.read_noise")
    assert replay_scoped_generator is not scoped_generator
    assert np.array_equal(replay_scoped_generator.standard_normal(9), scoped_draws)
    with pytest.raises(RandomStreamError, match="top-level provider"):
        scoped.register_domain("scoped.extra")


def test_adding_or_reordering_domains_does_not_perturb_existing_domains():
    baseline = NamedRandomStreams(1234)
    expanded = NamedRandomStreams(
        1234,
        domains=(*reversed(DEFAULT_RANDOM_DOMAINS), "experiment.sweep"),
    )

    for domain in DEFAULT_RANDOM_DOMAINS:
        assert baseline.stream_id(domain) == expanded.stream_id(domain)
        assert np.array_equal(
            baseline.generator(domain).integers(0, 2**32, size=7, dtype=np.uint32),
            expanded.generator(domain).integers(0, 2**32, size=7, dtype=np.uint32),
        )

    stream_id_before_registration = baseline.stream_id("atmosphere")
    baseline.register_domain("experiment.sweep")
    assert baseline.stream_id("atmosphere") == stream_id_before_registration


def test_derivation_scheme_has_frozen_ids_and_pcg64_vectors():
    streams = NamedRandomStreams(20260714)

    assert DERIVATION_SCHEME_ID == "shwfs_ao.random.sha256-json-pcg64-v1"
    assert streams.stream_id("detector.shot_noise") == (
        "shwfs_ao.random.sha256-json-pcg64-v1:"
        "7db6b43a2a5afe556c27597cdde669d77ef1edef918639f69e8d3d093343c1e4"
    )
    assert streams.generator("detector.shot_noise").integers(
        0,
        2**64,
        size=5,
        dtype=np.uint64,
    ).tolist() == [
        13328429479358827799,
        6732923571382993879,
        16889248306671981427,
        6265906511348528944,
        15516877527531560857,
    ]

    keyed_id = streams.stream_id("calibration", key=("poke", 7, -1))
    assert keyed_id == (
        "shwfs_ao.random.sha256-json-pcg64-v1:"
        "6cc6c543907ea4957cefc2ad2bd15c7921c7cf0c4ed5846737bda3dcea88fb1c"
    )
    assert streams.keyed_generator(
        "calibration", key=("poke", 7, -1)
    ).integers(0, 2**64, size=5, dtype=np.uint64).tolist() == [
        17059988447737134062,
        690825823072888223,
        16355739130089510887,
        13485449013070085309,
        3578641126830015130,
    ]


def test_derivation_is_stable_across_process_hash_seeds():
    code = textwrap.dedent(
        """
        import json
        from shwfs_ao.core.random import NamedRandomStreams

        streams = NamedRandomStreams(987654321)
        keyed = streams.scoped("calibration", key=("probe", 2)).keyed_generator(
            "detector.shot_noise", key=("repeat", 5)
        )
        print(json.dumps({
            "id": streams.scoped("calibration", key=("probe", 2)).stream_id(
                "detector.shot_noise", key=("repeat", 5)
            ),
            "draws": keyed.integers(0, 2**63, size=8).tolist(),
        }, sort_keys=True))
        """
    )

    outputs = []
    for hash_seed in ("1", "8675309"):
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env["PYTHONHASHSEED"] = hash_seed
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        outputs.append(json.loads(completed.stdout))

    assert outputs[0] == outputs[1]
