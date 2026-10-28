"""T2 G1: the identity-bearing construction route for paired layered atmospheres.

``LayeredAtmosphereOptions`` travels through ``build_scao_system`` into the
native factory, is recorded on the system and in its build attestation, and
the supplied-system verification rebuilds with the same options.  The
``ScaoExecutionOptions`` stay identity-neutral; no component is swapped after
construction and no private draw is patched.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from shwfs_ao.backends.native.factory import NATIVE_SCAO_COMPONENT_FACTORY, NativeScaoFactoryError
from shwfs_ao.core.random import NamedRandomStreams
from shwfs_ao.experiments import scao
from shwfs_ao.experiments.scao import LayeredAtmosphereOptions, ScaoConstructionError
from shwfs_ao.io.configs import load_system_profile

# The ci geometry of the convergence driver's pupil scan: 120 samples (12 per
# lenslet) paired with the 160-sample screen under the pupil-diameter rule.
OPTIONS = LayeredAtmosphereOptions(
    band_draw_reference_screen_size=318, band_limit_screen_size=238, screen_period_rule="pupil_diameter"
)


@pytest.fixture(scope="module")
def smoke():
    config = load_system_profile("eso_scao_smoke_5m_software", 2)
    return replace(config, controller=replace(config.controller, n_steps=4))


def test_options_change_the_atmosphere_identity_only_and_are_recorded(smoke) -> None:
    default = scao.build_scao_system(smoke)
    paired = scao.build_scao_system(smoke, atmosphere_options=OPTIONS)
    assert default.atmosphere_options is None and paired.atmosphere_options == OPTIONS
    assert paired.config_hash == smoke.config_hash == default.config_hash  # the profile's identity
    changed = {key for key in default.component_hashes if default.component_hashes[key] != paired.component_hashes[key]}
    assert changed == {"atmosphere"}
    metadata = paired.atmosphere.metadata
    assert metadata["band_draw_reference_screen_size"] == 318
    assert metadata["band_limit_screen_size"] == 238
    assert metadata["screen_period_rule"] == "pupil_diameter"
    assert metadata["screen_size"] == 238 and metadata["screen_period_m"] == pytest.approx(10.0)
    assert paired.atmosphere.config.band_draw_reference_screen_size == 318
    assert paired.build_attestation is not None and paired.build_attestation.atmosphere_options == OPTIONS
    # The two systems see different turbulence.
    pupil = np.asarray(paired.atmosphere.pupil_mask)
    assert not np.allclose(paired.atmosphere.opd_at(0.0)[pupil], default.atmosphere.opd_at(0.0)[pupil])
    # All-default options are the default build and are recorded as None.
    plain = scao.build_scao_system(smoke, atmosphere_options=LayeredAtmosphereOptions())
    assert plain.atmosphere_options is None and dict(plain.component_hashes) == dict(default.component_hashes)
    assert LayeredAtmosphereOptions().is_default and LayeredAtmosphereOptions().factory_keywords() == {}
    assert OPTIONS.factory_keywords() == {
        "band_draw_reference_screen_size": 318, "band_limit_screen_size": 238, "screen_period_rule": "pupil_diameter",
    }
    assert OPTIONS.to_record() == {
        "band_draw_reference_screen_size": 318, "band_limit_screen_size": 238, "screen_period_rule": "pupil_diameter",
    }


def test_a_paired_system_runs_and_is_verified_with_its_own_options(smoke) -> None:
    paired = scao.build_scao_system(smoke, atmosphere_options=OPTIONS)
    history = scao.run_closed_loop(smoke, system=paired)
    assert history.metadata["component_hashes"]["atmosphere"] == paired.component_hashes["atmosphere"]
    # Without its attestation the verification rebuilds with the recorded options and agrees.
    unattested = replace(paired, build_attestation=None)
    again = scao.run_closed_loop(smoke, system=unattested)
    assert again.config_hash == history.config_hash
    assert unattested.build_attestation is not None  # the agreeing rebuild's attestation was installed
    # Building inside run_closed_loop gives the same run identity.
    direct = scao.run_closed_loop(smoke, atmosphere_options=OPTIONS)
    assert direct.config_hash == history.config_hash
    # The default run has another identity: the atmosphere realization differs.
    assert scao.run_closed_loop(smoke).config_hash != history.config_hash


def test_options_are_refused_where_they_do_not_apply(smoke) -> None:
    other = load_system_profile("det_ccd_2m_synthetic", 1)  # native_frozen_flow_v2
    with pytest.raises(ScaoConstructionError, match="native_layered"):
        scao.build_scao_system(other, atmosphere_options=OPTIONS)
    paired = scao.build_scao_system(smoke, atmosphere_options=OPTIONS)
    with pytest.raises(ScaoConstructionError, match="already-built"):
        scao.run_closed_loop(smoke, system=paired, atmosphere_options=OPTIONS)
    with pytest.raises(ScaoConstructionError, match="LayeredAtmosphereOptions"):
        scao.build_scao_system(smoke, atmosphere_options="paired")  # type: ignore[arg-type]
    for invalid in (
        {"band_draw_reference_screen_size": True},
        {"band_draw_reference_screen_size": 1},
        {"band_limit_screen_size": 2.0},
        {"screen_period_rule": "diameter"},
        {"band_draw_reference_screen_size": 100, "band_limit_screen_size": 200},
    ):
        with pytest.raises(ScaoConstructionError):
            LayeredAtmosphereOptions(**invalid)
    # Options the configuration cannot satisfy are refused by the atmosphere's
    # own validation, surfaced through the native factory's error (a ValueError).
    with pytest.raises(NativeScaoFactoryError, match="at least the screen size"):
        scao.build_scao_system(smoke, atmosphere_options=LayeredAtmosphereOptions(band_draw_reference_screen_size=100))
    # The native factory refuses pairing keywords for any other atmosphere model.
    geometry = NATIVE_SCAO_COMPONENT_FACTORY.build_geometry(
        telescope_diameter_m=2.0, pupil_pixels=24, lenslets_across=4, min_fill_fraction=0.5,
        central_obstruction_ratio=0.0, spider_width_m=0.0,
    )
    with pytest.raises(NativeScaoFactoryError, match="native_layered"):
        NATIVE_SCAO_COMPONENT_FACTORY.build_atmosphere(
            model="static", geometry=geometry, random_streams=NamedRandomStreams(1), r0_m=0.1, outer_scale_m=None,
            phase_reference_wavelength_m=5.0e-7, wind_m_per_s=(0.0, 0.0), target_rms_rad=None, normalize_rms=False,
            static_opd_rms_m=1.0e-7, band_draw_reference_screen_size=48,
        )


def test_a_system_cannot_disown_the_options_it_was_built_with(smoke) -> None:
    paired = scao.build_scao_system(smoke, atmosphere_options=OPTIONS)
    # Restating the system without its options keeps its live component hashes
    # consistent, so construction passes, but it no longer matches its
    # attestation and the rebuild (unpaired) produces another atmosphere.
    disowned = replace(paired, atmosphere_options=None)
    with pytest.raises(ScaoConstructionError, match="do not match the components its source configuration rebuilds"):
        scao.run_closed_loop(smoke, system=disowned)
    with pytest.raises(ScaoConstructionError, match="LayeredAtmosphereOptions"):
        replace(paired, atmosphere_options="paired")  # type: ignore[arg-type]
