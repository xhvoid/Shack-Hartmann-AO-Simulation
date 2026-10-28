"""The packaged ESO E-ELT turbulence profile and its derived quantities."""

from __future__ import annotations

import copy
import json
import math

import pytest

from shwfs_ao.io import load_system_profile
from shwfs_ao.io.configs import AtmosphereConfig
from shwfs_ao.io.resources import read_text_resource
from shwfs_ao.io.turbulence_profiles import (
    ESO_ELT_PROFILE_NAME,
    TurbulenceProfileError,
    _profile_from_record,
    available_turbulence_profiles,
    eso_elt_turbulence_profile,
    load_turbulence_profile,
)


# The "Parameters of layers" table of
# https://www.eso.org/sci/facilities/eelt/science/drm/tech_data/ao/ as printed.
ESO_TABLE = (
    (0.0, 0.335, 12.1),
    (600.0, 0.223, 8.6),
    (1200.0, 0.112, 18.6),
    (2500.0, 0.090, 12.4),
    (5000.0, 0.080, 8.0),
    (9000.0, 0.052, 33.7),
    (11500.0, 0.045, 23.2),
    (12800.0, 0.034, 22.2),
    (14500.0, 0.019, 8.0),
    (18500.0, 0.011, 10.0),
)
RESOURCE = "literature_profiles/eso_elt_drm_ten_layer.json"


def _record() -> dict:
    return json.loads(read_text_resource(RESOURCE))


def test_the_packaged_table_is_the_published_eso_table() -> None:
    profile = load_turbulence_profile(ESO_ELT_PROFILE_NAME)

    assert available_turbulence_profiles() == (ESO_ELT_PROFILE_NAME,)
    assert (profile.r0_m, profile.r0_reference_wavelength_m) == (0.13, 500.0e-9)
    assert profile.outer_scale_m == 25.0
    assert profile.published_seeing_arcsec == 0.8
    assert len(profile.layers) == 10
    # The printed fractions are recovered exactly from the normalized ones.
    assert profile.published_cn2_fraction_sum == pytest.approx(1.001, abs=1e-12)
    for layer, (altitude, fraction, speed) in zip(profile.layers, ESO_TABLE):
        assert layer.altitude_m == altitude
        assert layer.cn2_fraction * profile.published_cn2_fraction_sum == pytest.approx(
            fraction, abs=1e-15
        )
        assert layer.wind_speed_m_per_s == speed
        assert layer.wind_direction_deg == 0.0
    assert math.fsum(layer.cn2_fraction for layer in profile.layers) == pytest.approx(
        1.0, abs=1e-12
    )

    provenance = profile.provenance
    assert provenance.source_class == "literature_derived"
    assert provenance.url == "https://www.eso.org/sci/facilities/eelt/science/drm/tech_data/ao/"
    assert "Wind directions are not published" in provenance.source_note


def test_derived_atmosphere_quantities_follow_the_standard_formulae() -> None:
    profile = eso_elt_turbulence_profile()

    # Layer strengths add as r0**(-5/3) and recover the integrated r0.
    strengths = math.fsum(r0 ** (-5.0 / 3.0) for r0 in profile.layer_r0_m)
    assert strengths ** (-3.0 / 5.0) == pytest.approx(0.13, rel=1e-12)
    assert profile.layer_r0_m[0] == pytest.approx(0.13 * (0.335 / 1.001) ** -0.6)

    # 0.98 lambda / r0 = 0.777 arcsec, which ESO rounds to 0.8 arcsec.
    assert profile.seeing_arcsec == pytest.approx(0.7775, abs=1e-4)
    assert profile.von_karman_seeing_arcsec < profile.seeing_arcsec
    assert profile.effective_wind_speed_m_per_s == pytest.approx(14.513, abs=1e-3)
    assert profile.effective_altitude_m == pytest.approx(4424.3, abs=0.1)
    assert profile.coherence_time_s == pytest.approx(2.813e-3, abs=1e-6)
    assert profile.isoplanatic_angle_arcsec == pytest.approx(1.903, abs=1e-3)
    assert profile.greenwood_frequency_hz == pytest.approx(47.61, abs=0.01)
    assert profile.r0_at_wavelength_m(1.65e-6) == pytest.approx(
        0.13 * (1.65e-6 / 500.0e-9) ** 1.2
    )


def test_wind_directions_are_an_explicit_choice() -> None:
    profile = eso_elt_turbulence_profile()
    assert all(layer.wind_m_per_s[1] == 0.0 for layer in profile.layers)

    rotated = eso_elt_turbulence_profile(wind_directions_deg=90.0)
    assert rotated.layers[5].wind_m_per_s == pytest.approx((0.0, 33.7), abs=1e-12)

    spread = profile.with_wind_directions([36.0 * index for index in range(10)])
    assert [layer.wind_direction_deg for layer in spread.layers] == [
        36.0 * index for index in range(10)
    ]
    # Directions do not change any speed-based statistic.
    assert spread.coherence_time_s == profile.coherence_time_s
    with pytest.raises(TurbulenceProfileError, match="expected 10 wind directions"):
        profile.with_wind_directions([0.0, 90.0])


def test_zenith_angle_scales_r0_and_layer_range() -> None:
    profile = eso_elt_turbulence_profile()
    slanted = eso_elt_turbulence_profile(zenith_angle_deg=30.0)

    cosine = math.cos(math.radians(30.0))
    assert slanted.zenith_angle_deg == 30.0
    assert slanted.r0_m == pytest.approx(0.13 * cosine**0.6)
    assert slanted.layers[-1].altitude_m == pytest.approx(18500.0 / cosine)
    assert [layer.wind_speed_m_per_s for layer in slanted.layers] == [
        layer.wind_speed_m_per_s for layer in profile.layers
    ]
    back = slanted.at_zenith_angle(0.0)
    assert back.r0_m == pytest.approx(profile.r0_m)
    assert back.layers[-1].altitude_m == pytest.approx(18500.0)
    with pytest.raises(TurbulenceProfileError, match="zenith_angle_deg"):
        profile.at_zenith_angle(90.0)


def test_the_profile_is_the_atmosphere_of_the_packaged_scao_profile() -> None:
    atmosphere = eso_elt_turbulence_profile().to_atmosphere_config()

    assert isinstance(atmosphere, AtmosphereConfig)
    assert atmosphere.wind_m_per_s == (0.0, 0.0)
    assert (atmosphere.normalize_rms, atmosphere.target_rms_opd_m) == (False, None)
    assert [layer.wind_m_per_s for layer in atmosphere.layers] == [
        (speed, 0.0) for _, _, speed in ESO_TABLE
    ]
    packaged = load_system_profile("eso_turbulence_2m_detector", 1)
    assert packaged.atmosphere_model == "native_layered"
    assert packaged.atmosphere == atmosphere


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda record: record.update(schema_version=2), "schema_version"),
        (lambda record: record.update(extra=1), "unknown=\\['extra'\\]"),
        (lambda record: record["layers"][0].pop("wind_speed_m_per_s"), "missing"),
        (lambda record: record["layers"][0].update(cn2_fraction=0.5), "not a rounded"),
        (lambda record: record["layers"][1].update(cn2_fraction=0.0), "positive"),
        (lambda record: record["turbulence"].update(power_spectrum="kolmogorov"), "von_karman"),
        (lambda record: record["provenance"].update(source_class="guess"), "provenance"),
    ],
)
def test_malformed_profile_records_are_refused(mutate, message) -> None:
    record = copy.deepcopy(_record())
    mutate(record)
    with pytest.raises(TurbulenceProfileError, match=message):
        _profile_from_record(record, expected_name=ESO_ELT_PROFILE_NAME)


def test_unknown_profile_names_are_refused() -> None:
    with pytest.raises(TurbulenceProfileError, match="unknown turbulence profile"):
        load_turbulence_profile("mauna_kea_median")
    with pytest.raises(TurbulenceProfileError, match="identity"):
        _profile_from_record(_record(), expected_name="other_name")
