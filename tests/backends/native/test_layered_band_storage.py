"""Regenerated band coefficients are an execution choice, not new physics."""

from __future__ import annotations

import numpy as np
import pytest

from shwfs_ao.backends.native.atmosphere import NativeAtmosphereError
from shwfs_ao.backends.native.layered_atmosphere import (
    FrozenFlowLayer,
    LayeredFrozenFlowAtmosphere,
    LayeredFrozenFlowAtmosphereConfig,
)
from shwfs_ao.experiments import scao
from shwfs_ao.experiments.eso_scao_benchmark import tier_config


def _config():
    return LayeredFrozenFlowAtmosphereConfig(
        grid_size=48,
        delta_m=0.05,
        pupil_diameter_m=2.4,
        r0_m=0.13,
        layers=(
            FrozenFlowLayer(cn2_fraction=0.6, wind_m_per_s=(12.0, 0.0)),
            FrozenFlowLayer(cn2_fraction=0.4, wind_m_per_s=(-7.5, 3.25), altitude_m=8000.0),
        ),
        root_seed=4,
    )


def test_regenerated_frames_are_bit_identical_and_identity_is_unchanged():
    stored = LayeredFrozenFlowAtmosphere(_config())
    regenerated = LayeredFrozenFlowAtmosphere(_config(), band_coefficient_storage="regenerate")
    assert stored.config_hash == regenerated.config_hash
    for realization in (0, 3):
        stored.reset(realization_index=realization)
        regenerated.reset(realization_index=realization)
        for time_s in (0.0, 0.0137, 0.5, 3.0):
            np.testing.assert_array_equal(stored.opd_at(time_s), regenerated.opd_at(time_s))
    assert regenerated.metadata["band_coefficient_storage"] == "regenerate"
    assert stored.metadata["random_stream_id"] == regenerated.metadata["random_stream_id"]
    with pytest.raises(NativeAtmosphereError):
        LayeredFrozenFlowAtmosphere(_config(), band_coefficient_storage="cached")


def test_scao_systems_with_either_storage_share_identity_and_history():
    config = tier_config("ci", n_steps=6)
    stored = scao.build_scao_system(config)
    regenerated = scao.build_scao_system(
        config, execution=scao.ScaoExecutionOptions(atmosphere_band_storage="regenerate")
    )
    assert dict(stored.component_hashes) == dict(regenerated.component_hashes)
    first = scao.run_closed_loop(config, system=stored)
    second = scao.run_closed_loop(config, system=regenerated)
    assert first.config_hash == second.config_hash
    np.testing.assert_array_equal(
        first.applied_command_history_opd_m, second.applied_command_history_opd_m
    )
