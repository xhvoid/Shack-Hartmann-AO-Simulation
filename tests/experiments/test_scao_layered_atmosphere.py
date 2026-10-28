"""SCAO systems driven by the multi-layer ``native_layered`` atmosphere."""

from __future__ import annotations

import numpy as np
import pytest

from shwfs_ao.backends.native.factory import (
    NATIVE_SCAO_COMPONENT_FACTORY,
    NativeScaoFactoryError,
)
from shwfs_ao.backends.native.layered_atmosphere import LayeredFrozenFlowAtmosphere
from shwfs_ao.core.random import NamedRandomStreams
from shwfs_ao.experiments import build_scao_system, run_closed_loop
from shwfs_ao.io import eso_elt_turbulence_profile, load_system_profile


def test_the_eso_profile_builds_the_ten_layer_atmosphere() -> None:
    config = load_system_profile("eso_turbulence_2m_detector", 1)
    system = build_scao_system(config)
    atmosphere = system.atmosphere

    assert isinstance(atmosphere, LayeredFrozenFlowAtmosphere)
    assert atmosphere.config.r0_m == 0.13
    assert atmosphere.config.outer_scale_m == 25.0
    assert atmosphere.config.layer_r0_m == pytest.approx(
        eso_elt_turbulence_profile().layer_r0_m
    )
    assert atmosphere.metadata["n_layers"] == 10
    assert atmosphere.metadata["root_seed"] == config.random.root_seed
    np.testing.assert_array_equal(atmosphere.pupil_mask, system.wfs.geometry.pupil_mask)


def test_the_eso_turbulence_loop_closes_on_every_frame() -> None:
    config = load_system_profile("eso_turbulence_2m_detector", 1)
    result = run_closed_loop(config)

    open_loop = np.asarray(result.open_loop_opd_rms_m)
    residual = np.asarray(result.post_update_residual_opd_rms_m)
    tail = slice(config.controller.n_steps // 3, None)
    assert np.all(np.asarray(result.reconstruction_usable))
    assert np.min(result.valid_subaperture_fraction) == 1.0
    assert np.all(np.isfinite(residual))
    assert np.mean(residual[tail]) < 0.85 * np.mean(open_loop[tail])


def test_only_the_layered_model_takes_layers() -> None:
    config = load_system_profile("eso_turbulence_2m_detector", 1)
    factory = NATIVE_SCAO_COMPONENT_FACTORY
    geometry = factory.build_geometry(
        telescope_diameter_m=config.telescope_diameter_m,
        pupil_pixels=config.pupil_pixels,
        lenslets_across=config.lenslets_across,
        min_fill_fraction=config.wfs.min_fill_fraction,
        central_obstruction_ratio=config.wfs.central_obstruction_ratio,
        spider_width_m=config.wfs.spider_width_m,
    )
    common = dict(
        geometry=geometry,
        random_streams=NamedRandomStreams(config.random.root_seed),
        r0_m=0.13,
        outer_scale_m=25.0,
        phase_reference_wavelength_m=500.0e-9,
        wind_m_per_s=(0.0, 0.0),
        target_rms_rad=None,
        normalize_rms=False,
        static_opd_rms_m=0.0,
    )
    with pytest.raises(NativeScaoFactoryError, match="native_layered"):
        factory.build_atmosphere(model="native_layered", **common)
    with pytest.raises(NativeScaoFactoryError, match="native_layered"):
        factory.build_atmosphere(
            model="native_frozen_flow_v2", layers=config.atmosphere.layers, **common
        )
    with pytest.raises(NativeScaoFactoryError, match="absolutely normalized"):
        factory.build_atmosphere(
            model="native_layered",
            layers=config.atmosphere.layers,
            **{**common, "normalize_rms": True},
        )
