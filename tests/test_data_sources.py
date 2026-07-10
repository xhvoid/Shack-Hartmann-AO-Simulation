# Tests verify data-source loaders return objects with units and source_class provenance; no notebook-only parsing is required.

from pathlib import Path
import json

import pytest

from data_sources import (
    ALLOWED_SOURCE_CLASSES,
    DataSourceError,
    load_eso_asm_snapshot,
    load_literature_atmosphere_profile,
    load_svo_filter_curve,
    load_target_photometry,
)


ROOT = Path(__file__).resolve().parents[1]


def test_load_eso_asm_snapshot_fixture_has_units_and_provenance():
    snapshot = load_eso_asm_snapshot(ROOT / "data" / "samples" / "eso_asm_snapshot_sample.json")

    assert snapshot.source_class == "synthetic_literature_inspired"
    assert snapshot.provenance.source_class in ALLOWED_SOURCE_CLASSES
    assert snapshot.provenance.fallback_used is True
    assert snapshot.units["seeing_arcsec_500nm"] == "arcsec"
    assert snapshot.measurements["seeing_arcsec_500nm"] == pytest.approx(0.8)
    assert snapshot.measurements["r0_500_m"] == pytest.approx(0.126)


def test_load_public_eso_asm_snapshot_cache_is_direct_public_data():
    snapshot = load_eso_asm_snapshot(ROOT / "data" / "public" / "eso_asm_paranal_20240729_0300_0800_snapshot.json")

    assert snapshot.source_class == "direct_public_data"
    assert snapshot.provenance.fallback_used is False
    assert snapshot.provenance.url is not None
    assert "eso.org/asm/api" in snapshot.provenance.url
    assert snapshot.measurements["sample_count"] == pytest.approx(184)
    assert snapshot.measurements["seeing_arcsec_500nm"] == pytest.approx(0.7235)
    assert snapshot.measurements["tau0_s"] == pytest.approx(0.003409)

    payload = json.loads((ROOT / "data" / "public" / "eso_asm_paranal_20240729_0300_0800_snapshot.json").read_text())
    assert payload["utc_start"] == "2024-07-29T03:00:00Z"
    assert payload["utc_end"] == "2024-07-29T08:00:00Z"
    assert payload["night_window_class"] == "nighttime"
    assert "CLT" in payload["local_time_note"]


def test_load_literature_atmosphere_profile_normalizes_layer_weights():
    profile = load_literature_atmosphere_profile(
        ROOT / "data" / "literature_profiles" / "paranal_three_layer_literature_inspired.json"
    )

    weights = [layer.cn2_weight for layer in profile.layers]

    assert profile.source_class == "synthetic_literature_inspired"
    assert profile.units["height_m"] == "m"
    assert sum(weights) == pytest.approx(1.0)
    assert profile.summary["r0_500_m"] == pytest.approx(0.126)


def test_load_svo_filter_curve_fixture_is_ordered_and_unit_tagged():
    curve = load_svo_filter_curve(ROOT / "data" / "samples" / "svo_2mass_h_sample.csv")

    assert curve.source_class == "synthetic_literature_inspired"
    assert curve.units["wavelength_m"] == "m"
    assert curve.units["transmission"] == "dimensionless"
    assert len(curve.wavelength_m) == len(curve.transmission)
    assert all(b > a for a, b in zip(curve.wavelength_m[:-1], curve.wavelength_m[1:]))
    assert max(curve.transmission) == pytest.approx(1.0)


def test_load_public_svo_filter_curve_cache_is_direct_public_data():
    curve = load_svo_filter_curve(ROOT / "data" / "public" / "svo_2mass_h_direct.csv")

    assert curve.source_class == "direct_public_data"
    assert curve.provenance.fallback_used is False
    assert curve.provenance.url is not None
    assert "svo2.cab.inta-csic.es" in curve.provenance.url
    assert len(curve.wavelength_m) > 20
    assert min(curve.wavelength_m) < 1.45e-6
    assert max(curve.wavelength_m) > 1.80e-6


def test_load_public_svo_j_and_ks_filter_caches_are_direct_public_data():
    j_curve = load_svo_filter_curve(ROOT / "data" / "public" / "svo_2mass_j_direct.csv")
    ks_curve = load_svo_filter_curve(ROOT / "data" / "public" / "svo_2mass_ks_direct.csv")

    assert j_curve.source_class == "direct_public_data"
    assert ks_curve.source_class == "direct_public_data"
    assert j_curve.filter_id == "2MASS/2MASS.J"
    assert ks_curve.filter_id == "2MASS/2MASS.Ks"
    assert min(j_curve.wavelength_m) < 1.10e-6
    assert max(j_curve.wavelength_m) > 1.35e-6
    assert min(ks_curve.wavelength_m) < 2.0e-6
    assert max(ks_curve.wavelength_m) > 2.30e-6


def test_load_target_photometry_selects_requested_target():
    target = load_target_photometry(
        ROOT / "data" / "samples" / "target_photometry_sample.csv",
        target_id="demo_ngs_bright",
    )

    assert target.source_class == "synthetic_assumed"
    assert target.units["gaia_g_mag"] == "mag"
    assert target.ra_deg == pytest.approx(83.6331)
    assert target.magnitudes["twomass_h_mag"] == pytest.approx(8.4)


def test_load_public_2mass_photometry_cache_is_direct_public_data():
    target = load_target_photometry(
        ROOT / "data" / "public" / "target_photometry_2mass_psc_demo_ngs_bright.csv",
        target_id="2MASS_05343359-0523099",
    )

    assert target.source_class == "direct_public_data"
    assert target.provenance.fallback_used is False
    assert target.provenance.url is not None
    assert "irsa.ipac.caltech.edu" in target.provenance.url
    assert target.ra_deg == pytest.approx(83.639998)
    assert target.magnitudes["twomass_j_mag"] == pytest.approx(11.282)
    assert target.magnitudes["twomass_h_mag"] == pytest.approx(10.782)
    assert target.magnitudes["twomass_ks_mag"] == pytest.approx(10.719)


def test_load_public_panstarrs_photometry_cache_is_direct_public_data():
    target = load_target_photometry(
        ROOT / "data" / "public" / "target_photometry_panstarrs_dr2_demo_ngs_bright.csv",
        target_id="PS1_101500836297539800",
    )

    assert target.source_class == "direct_public_data"
    assert target.provenance.fallback_used is False
    assert target.provenance.url is not None
    assert "catalogs.mast.stsci.edu" in target.provenance.url
    assert target.magnitudes["panstarrs_r_mag"] == pytest.approx(15.8742)
    assert target.magnitudes["panstarrs_i_mag"] == pytest.approx(20.7486)


def test_load_target_photometry_requires_target_id_for_multirow_file():
    with pytest.raises(DataSourceError, match="target_id is required"):
        load_target_photometry(ROOT / "data" / "samples" / "target_photometry_sample.csv")


def test_invalid_source_class_is_rejected(tmp_path):
    bad_path = tmp_path / "bad_eso.json"
    bad_path.write_text(
        json.dumps(
            {
                "data_kind": "eso_asm_snapshot",
                "source_class": "public_api",
                "source_note": "Legacy taxonomy should be rejected.",
                "units": {"seeing_arcsec_500nm": "arcsec"},
                "measurements": {"seeing_arcsec_500nm": 0.8},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(DataSourceError, match="Invalid source_class"):
        load_eso_asm_snapshot(bad_path)
