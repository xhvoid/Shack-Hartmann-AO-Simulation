"""AO-REF-011 ownership and compatibility tests for condition profiles."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import ao_conditions as installed
from shwfs_ao.core.provenance import Provenance
from shwfs_ao.experiments import public_data_conditioned as canonical
from shwfs_ao.io.public_data import EsoAsmSnapshot
from shwfs_ao.legacy import ao_conditions as legacy


ROOT = Path(__file__).resolve().parents[2]

OWNED_NAMES = (
    "AOConditionError",
    "ARCSEC_PER_RAD",
    "ObservingConditionConfig",
    "REFERENCE_PHASE_AMPLITUDE_NM",
    "REFERENCE_SEEING_ARCSEC",
    "condition_rows",
    "default_observing_conditions",
    "phase_amplitude_from_seeing",
    "r0_from_seeing_arcsec",
    "theta0_rad_from_arcsec",
)

FROZEN_LEGACY_NAMESPACE = {
    "ALLOWED_SOURCE_CLASSES",
    "AOConditionError",
    "ARCSEC_PER_RAD",
    "EsoAsmSnapshot",
    "ObservingConditionConfig",
    "REFERENCE_PHASE_AMPLITUDE_NM",
    "REFERENCE_SEEING_ARCSEC",
    "Sequence",
    "annotations",
    "condition_rows",
    "dataclass",
    "default_observing_conditions",
    "math",
    "phase_amplitude_from_seeing",
    "r0_from_seeing_arcsec",
    "theta0_rad_from_arcsec",
}


def _snapshot() -> EsoAsmSnapshot:
    return EsoAsmSnapshot(
        measurements={
            "seeing_arcsec_500nm": 0.7235,
            "r0_500_m": 0.13969571527297858,
            "tau0_s": 0.0042,
            "theta0_arcsec": 2.1,
            "turbulence_speed_ms": 9.5,
        },
        units={
            "seeing_arcsec_500nm": "arcsec",
            "r0_500_m": "m",
            "tau0_s": "s",
            "theta0_arcsec": "arcsec",
            "turbulence_speed_ms": "m/s",
        },
        provenance=Provenance(
            source_class="direct_public_data",
            source_note="Focused public-data-conditioned ownership fixture.",
        ),
    )


def test_canonical_module_owns_the_exact_legacy_objects() -> None:
    assert canonical.__all__ == OWNED_NAMES
    for name in OWNED_NAMES:
        expected = getattr(canonical, name)
        assert getattr(legacy, name) is expected
        assert getattr(installed, name) is expected


def test_legacy_runtime_namespace_remains_frozen() -> None:
    actual = {name for name in vars(legacy) if not name.startswith("_")}
    assert actual == FROZEN_LEGACY_NAMESPACE


def test_public_signatures_and_condition_rows_are_identical() -> None:
    for name in OWNED_NAMES:
        value = getattr(canonical, name)
        if inspect.isfunction(value) or name == "ObservingConditionConfig":
            assert inspect.signature(getattr(legacy, name)) == inspect.signature(
                value
            )

    canonical_conditions = canonical.default_observing_conditions(
        _snapshot(),
        catalog_photons_per_subap_frame=17.25,
        photon_source="catalog fixture",
    )
    legacy_conditions = legacy.default_observing_conditions(
        _snapshot(),
        catalog_photons_per_subap_frame=17.25,
        photon_source="catalog fixture",
    )

    assert canonical_conditions == legacy_conditions
    assert canonical.condition_rows(canonical_conditions) == (
        legacy.condition_rows(legacy_conditions)
    )
    assert [item.condition_name for item in canonical_conditions] == [
        "nominal_synthetic",
        "paranal_night_asm",
        "poor_seeing",
        "faint_ngs",
        "stress_all_effects",
    ]
    assert canonical_conditions[1].phase_amplitude_nm == pytest.approx(
        235.1375
    )
    assert canonical_conditions[-1].latency_total_s == pytest.approx(0.003)


def test_legacy_facade_contains_no_physical_declarations() -> None:
    legacy_path = ROOT / "src" / "shwfs_ao" / "legacy" / "ao_conditions.py"
    canonical_path = (
        ROOT
        / "src"
        / "shwfs_ao"
        / "experiments"
        / "public_data_conditioned.py"
    )
    legacy_tree = ast.parse(legacy_path.read_text(encoding="utf-8"))
    canonical_tree = ast.parse(canonical_path.read_text(encoding="utf-8"))

    assert not any(
        isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        for node in legacy_tree.body
    )
    assert any(
        isinstance(node, ast.ClassDef)
        and node.name == "ObservingConditionConfig"
        for node in canonical_tree.body
    )
    assert all(
        not (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and "legacy" in node.module.split(".")
        )
        for node in ast.walk(canonical_tree)
    )
