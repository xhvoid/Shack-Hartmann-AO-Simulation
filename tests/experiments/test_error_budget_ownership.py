"""AO-REF-011 ownership and compatibility gates for error budgets."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import ao_error_budget as installed
import shwfs_ao.experiments as experiments
from shwfs_ao.experiments import error_budget as canonical
from shwfs_ao.legacy import ao_error_budget as legacy


ROOT = Path(__file__).resolve().parents[2]

OWNED_NAMES = (
    "DEFAULT_SCENARIO_SOURCE_CLASS",
    "DEFAULT_SCENARIO_SOURCE_NOTE",
    "REQUIRED_SCENARIO_NAMES",
    "DEFAULT_J_BAND",
    "DEFAULT_H_BAND",
    "DEFAULT_K_BAND",
    "NM_PER_M",
    "PHASE_TWO_PI",
    "AOErrorBudgetError",
    "ScenarioConfig",
    "ScenarioResult",
    "default_error_budget_scenarios",
    "default_jhk_bandpasses",
    "run_error_budget_scenarios",
    "run_error_budget_scenario",
    "build_control_space_phase_sequence",
    "summarize_scenario",
    "scenario_results_as_dicts",
)

FROZEN_LEGACY_NAMESPACE = {
    "ALLOWED_SOURCE_CLASSES",
    "AOErrorBudgetError",
    "Any",
    "DEFAULT_H_BAND",
    "DEFAULT_J_BAND",
    "DEFAULT_K_BAND",
    "DEFAULT_SCENARIO_SOURCE_CLASS",
    "DEFAULT_SCENARIO_SOURCE_NOTE",
    "DMConfig",
    "DMModel",
    "DetectorLoopConfig",
    "DetectorShwfsCalibration",
    "LoopHistory",
    "Mapping",
    "NM_PER_M",
    "PHASE_TWO_PI",
    "PokeMtxResult",
    "REQUIRED_SCENARIO_NAMES",
    "ScenarioConfig",
    "ScenarioResult",
    "ScienceBandpass",
    "Sequence",
    "band_averaged_psf_metrics_from_opd",
    "build_control_space_phase_sequence",
    "dataclass",
    "default_error_budget_scenarios",
    "default_jhk_bandpasses",
    "expand_controlled_commands",
    "hashlib",
    "json",
    "math",
    "ndimage",
    "np",
    "phase_rad_to_opd_nm",
    "remove_piston_opd_nm",
    "replace",
    "residual_opd_nm_from_command",
    "run_detector_integrator_loop",
    "run_error_budget_scenario",
    "run_error_budget_scenarios",
    "scenario_results_as_dicts",
    "stable_array_descriptor",
    "summarize_scenario",
    "synthesize_dm_phase_rad",
    "top_hat_bandpass",
}
if hasattr(canonical, "annotations"):
    FROZEN_LEGACY_NAMESPACE.add("annotations")


def test_canonical_module_and_aggregate_export_the_owned_api() -> None:
    assert canonical.__all__ == OWNED_NAMES
    assert set(OWNED_NAMES).issubset(experiments.__all__)
    for name in OWNED_NAMES:
        value = getattr(canonical, name)
        assert getattr(experiments, name) is value
        assert getattr(legacy, name) is value
        assert getattr(installed, name) is value


def test_legacy_and_installed_runtime_namespaces_remain_frozen() -> None:
    assert {
        name for name in vars(legacy) if not name.startswith("_")
    } == FROZEN_LEGACY_NAMESPACE
    assert {
        name for name in vars(installed) if not name.startswith("_")
    } == FROZEN_LEGACY_NAMESPACE
    assert set(legacy.__all__) == FROZEN_LEGACY_NAMESPACE
    assert set(installed.__all__) == FROZEN_LEGACY_NAMESPACE

    for name in FROZEN_LEGACY_NAMESPACE:
        assert getattr(legacy, name) is getattr(canonical, name)
        assert getattr(installed, name) is getattr(canonical, name)


def test_public_signatures_dataclasses_and_defaults_are_preserved() -> None:
    for name in OWNED_NAMES:
        value = getattr(canonical, name)
        if inspect.isfunction(value) or name in {"ScenarioConfig", "ScenarioResult"}:
            assert inspect.signature(getattr(legacy, name)) == inspect.signature(value)
            assert inspect.signature(getattr(installed, name)) == inspect.signature(value)

    assert canonical.ScenarioConfig.__module__ == canonical.__name__
    assert canonical.ScenarioResult.__module__ == canonical.__name__
    canonical_rows = canonical.default_error_budget_scenarios(
        n_steps=8,
        phase_amplitude_nm=260.0,
    )
    legacy_rows = legacy.default_error_budget_scenarios(
        n_steps=8,
        phase_amplitude_nm=260.0,
    )
    assert canonical_rows == legacy_rows
    assert tuple(item.scenario_name for item in canonical_rows) == (
        canonical.REQUIRED_SCENARIO_NAMES
    )


def test_legacy_facade_has_no_physical_declarations_or_kernels() -> None:
    legacy_path = ROOT / "src" / "shwfs_ao" / "legacy" / "ao_error_budget.py"
    canonical_path = (
        ROOT / "src" / "shwfs_ao" / "experiments" / "error_budget.py"
    )
    legacy_tree = ast.parse(legacy_path.read_text(encoding="utf-8"))
    canonical_tree = ast.parse(canonical_path.read_text(encoding="utf-8"))

    assert not any(
        isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        for node in legacy_tree.body
    )
    canonical_definitions = {
        node.name
        for node in canonical_tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef))
    }
    assert {
        "AOErrorBudgetError",
        "ScenarioConfig",
        "ScenarioResult",
        "run_error_budget_scenario",
        "build_control_space_phase_sequence",
        "summarize_scenario",
        "_affine_misregister_phase",
        "_science_path_ncpa_nm",
    }.issubset(canonical_definitions)

    legacy_source = legacy_path.read_text(encoding="utf-8")
    assert "ndimage.affine_transform(" not in legacy_source
    assert "np.random.default_rng(" not in legacy_source
    assert "from ..experiments.error_budget import (" in legacy_source
