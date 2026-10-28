"""AO-REF-009 contracts for the canonical loop configuration."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields

import numpy as np
import pytest

from shwfs_ao.control.config import LoopConfig, LoopConfigError


def _config(**overrides: object) -> LoopConfig:
    values: dict[str, object] = {
        "n_steps": 5,
        "gain": 0.35,
        "leak": 0.02,
        "latency_frames": 1,
        "frame_rate_hz": 500.0,
        "root_seed": 17,
    }
    values.update(overrides)
    return LoopConfig(**values)  # type: ignore[arg-type]


def test_loop_config_has_the_exact_ticket_fields_and_a_stable_hash() -> None:
    assert tuple(field.name for field in fields(LoopConfig)) == (
        "n_steps",
        "gain",
        "leak",
        "latency_frames",
        "frame_rate_hz",
        "root_seed",
    )

    first = _config()
    identical = _config()
    changed = _config(gain=0.36)

    assert first == identical
    assert first.config_hash == identical.config_hash
    assert first.config_hash != changed.config_hash
    assert len(first.config_hash) == 64
    with pytest.raises(FrozenInstanceError):
        first.gain = 0.4  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("n_steps", 0),
        ("n_steps", -1),
        ("n_steps", True),
        ("n_steps", 3.0),
        ("gain", -1.0e-12),
        ("gain", np.nan),
        ("gain", np.inf),
        ("gain", True),
        ("leak", -1.0e-12),
        ("leak", 1.0),
        ("leak", np.nan),
        ("leak", False),
        ("latency_frames", -1),
        ("latency_frames", True),
        ("latency_frames", 1.5),
        ("frame_rate_hz", 0.0),
        ("frame_rate_hz", -1.0),
        ("frame_rate_hz", np.inf),
        ("frame_rate_hz", True),
        ("root_seed", -1),
        ("root_seed", True),
        ("root_seed", 1.5),
    ],
)
def test_loop_config_rejects_ambiguous_or_out_of_range_values(
    field_name: str,
    value: object,
) -> None:
    with pytest.raises(LoopConfigError, match=field_name):
        _config(**{field_name: value})


def test_root_seed_uses_the_named_stream_provider_nonnegative_integer_range() -> None:
    # NamedRandomStreams derives a digest from the decimal integer and therefore
    # supports nonnegative Python integers beyond the legacy uint32 seed range.
    seed = 2**160 + 123
    assert _config(root_seed=seed).root_seed == seed
