"""AO-REF-010 canonical science-bandpass contracts."""

from __future__ import annotations

import ast
from dataclasses import asdict, fields, replace
import inspect
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from shwfs_ao.core.provenance import Provenance
from shwfs_ao.science import bandpass as bandpass_module
from shwfs_ao.science.bandpass import (
    BandpassError,
    ScienceBandpass,
    bandpass_from_filter_curve,
    monochromatic_bandpass,
    top_hat_bandpass,
)


ROOT = Path(__file__).resolve().parents[2]
SOURCE_NOTE = "Synthetic bandpass used by the canonical AO-REF-010 tests."


def _bandpass(**changes: object) -> ScienceBandpass:
    settings: dict[str, object] = {
        "name": "H",
        "wavelength_m": np.asarray([1.45e-6, 1.60e-6, 1.80e-6]),
        "transmission": np.asarray([0.2, 1.0, 0.4]),
        "source_class": "synthetic_assumed",
        "source_note": SOURCE_NOTE,
        "filter_id": "TEST.H",
    }
    settings.update(changes)
    return ScienceBandpass(**settings)  # type: ignore[arg-type]


def _curve(**changes: object) -> SimpleNamespace:
    settings: dict[str, object] = {
        "filter_id": "2MASS.H",
        "wavelength_m": (1.45e-6, 1.60e-6, 1.80e-6),
        "transmission": (0.2, 1.0, 0.4),
        "units": {
            "wavelength_m": "m",
            "transmission": "dimensionless",
        },
        "provenance": Provenance(
            "direct_public_data",
            "Tracked direct SVO-style test curve.",
            source_id="SVO:2MASS.H",
            url="https://example.invalid/svo/2mass-h",
            access_time="2026-07-15T00:00:00Z",
            fallback_used=False,
            references=("SVO Filter Profile Service",),
        ),
    }
    settings.update(changes)
    return SimpleNamespace(**settings)


def test_public_surface_is_explicit_and_minimal() -> None:
    assert bandpass_module.__all__ == (
        "BandpassError",
        "ScienceBandpass",
        "monochromatic_bandpass",
        "top_hat_bandpass",
        "bandpass_from_filter_curve",
    )
    namespace: dict[str, object] = {}
    exec("from shwfs_ao.science.bandpass import *", namespace)
    assert {name for name in namespace if not name.startswith("_")} == set(
        bandpass_module.__all__
    )


def test_constructor_keeps_frozen_six_field_signature() -> None:
    assert tuple(field.name for field in fields(ScienceBandpass)) == (
        "name",
        "wavelength_m",
        "transmission",
        "source_class",
        "source_note",
        "filter_id",
    )
    assert tuple(inspect.signature(ScienceBandpass).parameters) == (
        "name",
        "wavelength_m",
        "transmission",
        "source_class",
        "source_note",
        "filter_id",
    )


def test_arrays_are_copied_byte_backed_and_deeply_immutable() -> None:
    wavelengths = np.asarray([1.4e-6, 1.6e-6, 1.9e-6])
    transmission = np.asarray([0.2, 0.9, 0.4])
    band = _bandpass(wavelength_m=wavelengths, transmission=transmission)
    expected_wavelengths = band.wavelength_m.copy()
    expected_transmission = band.transmission.copy()
    expected_weights = band.weights.copy()
    expected_hash = band.config_hash

    wavelengths[:] = 9.0e-6
    transmission[:] = 0.0
    np.testing.assert_array_equal(band.wavelength_m, expected_wavelengths)
    np.testing.assert_array_equal(band.transmission, expected_transmission)
    np.testing.assert_array_equal(band.weights, expected_weights)
    assert band.config_hash == expected_hash

    for array in (band.wavelength_m, band.transmission, band.weights):
        assert not array.flags.writeable
        with pytest.raises(ValueError):
            array[0] = 0.0
        with pytest.raises(ValueError):
            array.setflags(write=True)


def test_nonuniform_trapezoid_weights_and_effective_wavelength_are_analytic() -> None:
    band = _bandpass(
        wavelength_m=np.asarray([1.0e-6, 2.0e-6, 4.0e-6]),
        transmission=np.asarray([1.0, 0.5, 2.0]),
    )
    expected_raw = np.asarray([0.5, 0.75, 2.0])
    expected = expected_raw / np.sum(expected_raw)

    np.testing.assert_allclose(band.weights, expected, rtol=0.0, atol=1.0e-16)
    assert np.sum(band.weights) == pytest.approx(1.0, abs=1.0e-15)
    assert band.effective_wavelength_m == pytest.approx(
        float(np.sum(band.wavelength_m * expected)),
        abs=1.0e-18,
    )


def test_monochromatic_and_top_hat_factories_preserve_frozen_numerics() -> None:
    monochromatic = monochromatic_bandpass(
        "J",
        1.25e-6,
        source_note=SOURCE_NOTE,
    )
    assert monochromatic.filter_id == "J"
    np.testing.assert_array_equal(monochromatic.wavelength_m, [1.25e-6])
    np.testing.assert_array_equal(monochromatic.transmission, [1.0])
    np.testing.assert_array_equal(monochromatic.weights, [1.0])
    assert monochromatic.effective_wavelength_m == 1.25e-6

    top_hat = top_hat_bandpass(
        "K",
        2.0e-6,
        2.4e-6,
        n_samples=5,
        source_note=SOURCE_NOTE,
    )
    np.testing.assert_array_equal(
        top_hat.wavelength_m,
        np.linspace(2.0e-6, 2.4e-6, 5),
    )
    np.testing.assert_array_equal(top_hat.transmission, np.ones(5))
    np.testing.assert_allclose(
        top_hat.weights,
        [0.125, 0.25, 0.25, 0.25, 0.125],
        rtol=0.0,
        atol=1.0e-15,
    )
    assert top_hat.effective_wavelength_m == pytest.approx(2.2e-6)
    assert top_hat.filter_id == "K.top_hat"


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"name": " "}, "ScienceBandpass name must be non-empty"),
        ({"name": 1}, "ScienceBandpass name must be non-empty"),
        ({"wavelength_m": 1.6e-6}, "one-dimensional"),
        ({"wavelength_m": np.ones((1, 3)) * 1.6e-6}, "one-dimensional"),
        ({"transmission": np.ones((1, 3))}, "one-dimensional"),
        (
            {
                "wavelength_m": np.asarray([]),
                "transmission": np.asarray([]),
            },
            "at least one wavelength",
        ),
        ({"wavelength_m": np.asarray([1.5e-6])}, "same shape"),
        (
            {"wavelength_m": np.asarray([1.4e-6, np.nan, 1.8e-6])},
            "Non-finite values",
        ),
        (
            {"transmission": np.asarray([0.2, np.inf, 0.4])},
            "Non-finite values",
        ),
        (
            {"wavelength_m": np.asarray([1.4e-6, 0.0, 1.8e-6])},
            "must be positive",
        ),
        (
            {"wavelength_m": np.asarray([1.4e-6, 1.8e-6, 1.7e-6])},
            "strictly increasing",
        ),
        (
            {"wavelength_m": np.asarray([1.4e-6, 1.4e-6, 1.8e-6])},
            "strictly increasing",
        ),
        (
            {"transmission": np.asarray([0.2, -0.1, 0.4])},
            "must be non-negative",
        ),
        (
            {"transmission": np.zeros(3)},
            "positive total weight",
        ),
        ({"source_class": "unknown"}, "not in the permitted taxonomy"),
        ({"source_class": []}, "not in the permitted taxonomy"),
        ({"source_note": ""}, "source_note must be non-empty"),
        ({"source_note": None}, "source_note must be non-empty"),
        ({"filter_id": ""}, "filter_id must be non-empty"),
    ),
)
def test_constructor_rejects_malformed_axes_throughput_and_provenance(
    changes: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(BandpassError, match=message):
        _bandpass(**changes)


@pytest.mark.parametrize("value", (True, 2.5, "3", 1, 0, -1))
def test_top_hat_requires_at_least_two_integer_samples(value: object) -> None:
    with pytest.raises(BandpassError, match="n_samples"):
        top_hat_bandpass(
            "H",
            1.5e-6,
            1.8e-6,
            n_samples=value,  # type: ignore[arg-type]
            source_note=SOURCE_NOTE,
        )


@pytest.mark.parametrize("value", (True, "1.6e-6", 0.0, -1.0, np.nan, np.inf))
def test_monochromatic_factory_rejects_nonphysical_wavelength(value: object) -> None:
    with pytest.raises(BandpassError, match="wavelength_m"):
        monochromatic_bandpass(
            "H",
            value,  # type: ignore[arg-type]
            source_note=SOURCE_NOTE,
        )


def test_svo_structural_conversion_copies_values_units_and_provenance() -> None:
    curve = _curve()
    band = bandpass_from_filter_curve(curve)
    renamed = bandpass_from_filter_curve(curve, name="H")

    assert band.name == "2MASS.H"
    assert renamed.name == "H"
    assert band.filter_id == "2MASS.H"
    assert band.source_class == "direct_public_data"
    assert band.source_note == "Tracked direct SVO-style test curve."
    assert band.provenance is not curve.provenance
    assert band.provenance == curve.provenance
    np.testing.assert_array_equal(band.wavelength_m, curve.wavelength_m)
    np.testing.assert_array_equal(band.transmission, curve.transmission)

    changed_curve = _curve(
        provenance=replace(curve.provenance, source_id="SVO:2MASS.H:revision-2")
    )
    changed = bandpass_from_filter_curve(changed_curve)
    assert changed.provenance.source_id == "SVO:2MASS.H:revision-2"
    assert changed.config_hash != band.config_hash

    replaced = replace(band, name="H renamed")
    assert replaced.provenance == band.provenance
    assert replaced.config_hash != band.config_hash

    copied_samples = replace(
        band,
        wavelength_m=np.array(band.wavelength_m, copy=True),
        transmission=np.array(band.transmission, copy=True),
    )
    assert copied_samples.provenance == band.provenance
    assert copied_samples.config_hash == band.config_hash

    other_curve = _curve(
        filter_id="SVO:OTHER",
        wavelength_m=(3.0e-6, 3.5e-6, 4.0e-6),
        provenance=replace(
            curve.provenance,
            source_id="SVO:OTHER",
            source_note="Tracked second SVO-style test curve.",
        ),
    )
    other = bandpass_from_filter_curve(other_curve)
    with pytest.raises(BandpassError, match="inconsistent provenance"):
        replace(
            band,
            wavelength_m=other.wavelength_m,
            transmission=other.transmission,
        )

    legacy_transport = asdict(band)
    assert tuple(legacy_transport) == (
        "name",
        "wavelength_m",
        "transmission",
        "source_class",
        "source_note",
        "filter_id",
    )
    assert "provenance" not in legacy_transport


@pytest.mark.parametrize(
    ("curve", "message"),
    (
        (SimpleNamespace(), "filter_id"),
        (_curve(filter_id=""), "filter curve filter_id must be non-empty"),
        (_curve(units=None), "units must be a mapping"),
        (_curve(units={}), "wavelength_m"),
        (
            _curve(
                units={
                    "wavelength_m": "nm",
                    "transmission": "dimensionless",
                }
            ),
            "must be 'm'",
        ),
        (
            _curve(
                units={
                    "wavelength_m": "m",
                    "transmission": "%",
                }
            ),
            "must be 'dimensionless'",
        ),
        (_curve(provenance={}), "canonical Provenance"),
        (_curve(wavelength_m=(1.8e-6, 1.5e-6)), "same shape"),
    ),
)
def test_svo_conversion_rejects_malformed_structural_inputs(
    curve: object,
    message: str,
) -> None:
    with pytest.raises(BandpassError, match=message):
        bandpass_from_filter_curve(curve)  # type: ignore[arg-type]


def test_config_hash_is_stable_and_covers_every_declared_field() -> None:
    original = _bandpass()
    identical = _bandpass(
        wavelength_m=[1.45e-6, 1.60e-6, 1.80e-6],
        transmission=[0.2, 1.0, 0.4],
    )
    assert original.config_hash == identical.config_hash
    assert len(original.config_hash) == 64
    assert set(original.config_hash) <= set("0123456789abcdef")

    variants = (
        replace(original, name="H2"),
        replace(original, wavelength_m=np.asarray([1.46e-6, 1.60e-6, 1.80e-6])),
        replace(original, transmission=np.asarray([0.3, 1.0, 0.4])),
        replace(
            original,
            source_class="synthetic_literature_inspired",
            source_note="Literature-inspired test bandpass.",
        ),
        replace(original, source_note="Changed provenance note."),
        replace(original, filter_id="TEST.H2"),
    )
    assert all(variant.config_hash != original.config_hash for variant in variants)


def test_legacy_bandpass_surface_delegates_to_the_canonical_owner() -> None:
    from shwfs_ao.legacy import ao_diagnostics as legacy

    assert legacy.AODiagnosticsError is BandpassError
    assert legacy.ScienceBandpass is ScienceBandpass
    assert legacy.monochromatic_bandpass is monochromatic_bandpass
    assert legacy.top_hat_bandpass is top_hat_bandpass
    assert legacy.bandpass_from_filter_curve is bandpass_from_filter_curve

    tree = ast.parse(
        (ROOT / "src/shwfs_ao/legacy/ao_diagnostics.py").read_text(
            encoding="utf-8"
        )
    )
    moved_names = {
        "ScienceBandpass",
        "monochromatic_bandpass",
        "top_hat_bandpass",
        "bandpass_from_filter_curve",
    }
    assert not any(
        isinstance(node, (ast.ClassDef, ast.FunctionDef))
        and node.name in moved_names
        for node in tree.body
    )


def test_canonical_bandpass_has_no_legacy_or_concrete_io_dependency() -> None:
    tree = ast.parse(Path(bandpass_module.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(
                not alias.name.startswith(("shwfs_ao.legacy", "shwfs_ao.io"))
                for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            assert node.module not in {"legacy", "io", "io.public_data"}
