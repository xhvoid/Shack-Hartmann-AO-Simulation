"""AO-REF-003 canonical public-data and compatibility contracts."""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
from pathlib import Path

import pytest

import data_sources as top_level_data_sources
from shwfs_ao.core.provenance import Provenance as CoreProvenance
from shwfs_ao import io
from shwfs_ao.io import configs, public_data
from shwfs_ao.legacy import data_sources as legacy_data_sources
from shwfs_ao.legacy import runtime_resources as legacy_runtime_resources


ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "src" / "shwfs_ao" / "resources"

PUBLIC_DATA_EXPORTS = (
    "ALLOWED_SOURCE_CLASSES",
    "AtmosphereLayer",
    "DataSourceError",
    "EsoAsmSnapshot",
    "FilterCurve",
    "LiteratureAtmosphereProfile",
    "Provenance",
    "TargetPhotometry",
    "load_eso_asm_snapshot",
    "load_literature_atmosphere_profile",
    "load_svo_filter_curve",
    "load_target_photometry",
)

LEGACY_PUBLIC_NAMES = {
    "ALLOWED_SOURCE_CLASSES",
    "ARCSEC_PER_RADIAN",
    "ATMOSPHERE_LAYER_UNITS",
    "Any",
    "AtmosphereLayer",
    "CSV_COMMENT_PREFIX",
    "CSV_METADATA_SEPARATOR",
    "DataSourceError",
    "ESO_MEASUREMENT_UNITS",
    "EsoAsmSnapshot",
    "FilterCurve",
    "LITERATURE_SUMMARY_UNITS",
    "LiteratureAtmosphereProfile",
    "NORMALIZED_WEIGHT_ABS_TOL",
    "Path",
    "Provenance",
    "REQUIRED_CSV_METADATA",
    "TargetPhotometry",
    "csv",
    "dataclass",
    "json",
    "load_eso_asm_snapshot",
    "load_literature_atmosphere_profile",
    "load_svo_filter_curve",
    "load_target_photometry",
    "math",
    "open_text_resource",
}


def _public_names(module: object) -> set[str]:
    return {name for name in vars(module) if not name.startswith("_")}


def test_io_public_surface_is_explicit_and_identity_preserving():
    assert io.__all__ == (*configs.__all__, *PUBLIC_DATA_EXPORTS)
    assert public_data.__all__ == PUBLIC_DATA_EXPORTS
    assert all(
        getattr(io, name) is getattr(public_data, name)
        for name in PUBLIC_DATA_EXPORTS
    )
    assert all(getattr(io, name) is getattr(configs, name) for name in configs.__all__)
    assert io.Provenance is public_data.Provenance is CoreProvenance


def test_legacy_facades_preserve_the_frozen_28_name_surface_and_identities():
    expected_names = set(LEGACY_PUBLIC_NAMES)
    if hasattr(public_data, "annotations"):
        expected_names.add("annotations")

    assert len(expected_names) == 28
    assert _public_names(legacy_data_sources) == expected_names
    assert _public_names(top_level_data_sources) == expected_names
    assert set(legacy_data_sources.__all__) == expected_names
    assert set(top_level_data_sources.__all__) == expected_names
    assert all(
        getattr(legacy_data_sources, name) is getattr(top_level_data_sources, name)
        for name in expected_names
    )
    assert all(
        getattr(legacy_data_sources, name) is getattr(public_data, name)
        for name in expected_names - {"annotations"}
    )
    assert legacy_data_sources.open_text_resource is legacy_runtime_resources.open_text_resource

    for loader_name in (
        "load_eso_asm_snapshot",
        "load_literature_atmosphere_profile",
        "load_svo_filter_curve",
        "load_target_photometry",
    ):
        assert inspect.signature(getattr(legacy_data_sources, loader_name)) == inspect.signature(
            getattr(public_data, loader_name)
        )


def test_legacy_data_source_module_is_an_implementation_free_facade():
    facade_path = ROOT / "src" / "shwfs_ao" / "legacy" / "data_sources.py"
    tree = ast.parse(facade_path.read_text(encoding="utf-8"), filename=str(facade_path))

    assert not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda))
        for node in ast.walk(tree)
    )
    public_data_path = ROOT / "src" / "shwfs_ao" / "io" / "public_data.py"
    public_data_tree = ast.parse(
        public_data_path.read_text(encoding="utf-8"), filename=str(public_data_path)
    )
    legacy_imports = {
        node.module
        for node in ast.walk(public_data_tree)
        if isinstance(node, ast.ImportFrom) and node.level == 2
    }
    assert legacy_imports == {"core.provenance"}
    assert any(
        isinstance(node, ast.ImportFrom)
        and node.level == 1
        and node.module == "resources"
        for node in ast.walk(public_data_tree)
    )


def test_all_public_data_loaders_return_canonical_core_provenance():
    loaded = (
        public_data.load_eso_asm_snapshot(
            DATA_ROOT / "samples" / "eso_asm_snapshot_sample.json"
        ),
        public_data.load_literature_atmosphere_profile(
            DATA_ROOT
            / "literature_profiles"
            / "paranal_three_layer_literature_inspired.json"
        ),
        public_data.load_svo_filter_curve(
            DATA_ROOT / "samples" / "svo_2mass_h_sample.csv"
        ),
        public_data.load_target_photometry(
            DATA_ROOT / "samples" / "target_photometry_sample.csv",
            target_id="demo_ngs_bright",
        ),
    )

    assert all(type(item.provenance) is CoreProvenance for item in loaded)
    assert loaded[0].measurements["r0_500_m"] == pytest.approx(0.126)
    assert sum(layer.cn2_weight for layer in loaded[1].layers) == pytest.approx(1.0)
    assert max(loaded[2].transmission) == pytest.approx(1.0)
    assert loaded[3].magnitudes["twomass_h_mag"] == pytest.approx(8.4)


def test_canonical_loaders_preserve_direct_public_fixture_behavior():
    snapshot = public_data.load_eso_asm_snapshot(
        DATA_ROOT / "public" / "eso_asm_paranal_20240729_0300_0800_snapshot.json"
    )
    curve = public_data.load_svo_filter_curve(
        DATA_ROOT / "public" / "svo_2mass_h_direct.csv"
    )
    target = public_data.load_target_photometry(
        DATA_ROOT / "public" / "target_photometry_2mass_psc_demo_ngs_bright.csv",
        target_id="2MASS_05343359-0523099",
    )

    assert all(
        item.provenance.source_class == "direct_public_data"
        and item.provenance.fallback_used is False
        for item in (snapshot, curve, target)
    )
    assert snapshot.measurements["seeing_arcsec_500nm"] == pytest.approx(0.7235)
    assert len(curve.wavelength_m) > 20
    assert target.magnitudes["twomass_h_mag"] == pytest.approx(10.782)


def test_legacy_loader_translates_invalid_provenance_to_data_source_error(tmp_path):
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

    expected = (
        "Invalid source_class='public_api'; expected one of "
        "['direct_public_data', 'literature_derived', 'package_reference', "
        "'synthetic_assumed', 'synthetic_literature_inspired']."
    )
    with pytest.raises(legacy_data_sources.DataSourceError) as exc_info:
        legacy_data_sources.load_eso_asm_snapshot(bad_path)
    assert str(exc_info.value) == expected


@pytest.mark.parametrize(
    ("relative_path", "expected_sha256"),
    (
        (
            "samples/eso_asm_snapshot_sample.json",
            "944f2e7086b003205fdfa0b6e0d8f1b744fe06b10d402747357fea159d73aaa5",
        ),
        (
            "literature_profiles/paranal_three_layer_literature_inspired.json",
            "19af2a4b1eddfa86f942f34817332658ced114b952e9478f0dc98b4bbeecd233",
        ),
        (
            "samples/svo_2mass_h_sample.csv",
            "1fdc18b0b9806685c46bab3c111f7dabd0e2ba38f62e543ca5c0fc5df1d0ee80",
        ),
        (
            "samples/target_photometry_sample.csv",
            "050d184729cdd17d1d08cafd1f46e8008991032c87915b67233b0f7fd4dc9692",
        ),
    ),
)
def test_loader_source_fixtures_remain_byte_unchanged(relative_path, expected_sha256):
    assert hashlib.sha256((DATA_ROOT / relative_path).read_bytes()).hexdigest() == expected_sha256
