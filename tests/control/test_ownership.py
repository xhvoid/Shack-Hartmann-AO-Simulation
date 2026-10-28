"""Static AO-REF-009 ownership gates for the common control loop."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTROL = ROOT / "src" / "shwfs_ao" / "control"
LEGACY = ROOT / "src" / "shwfs_ao" / "legacy"


def _tree(filename: str) -> ast.Module:
    return ast.parse((CONTROL / filename).read_text(encoding="utf-8"))


def _called_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def test_loop_contains_no_optics_detector_dm_spatial_or_reconstruction_kernel() -> None:
    tree = _tree("loop.py")
    forbidden_calls = {
        "centroid",
        "fft",
        "fft2",
        "ifft",
        "ifft2",
        "influence_functions",
        "lstsq",
        "pinv",
        "svd",
    }
    calls = {
        name
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and (name := _called_name(node)) is not None
    }
    assert calls.isdisjoint(forbidden_calls), sorted(calls & forbidden_calls)

    forbidden_import_roots = (
        "shwfs_ao.backends",
        "shwfs_ao.detector",
        "shwfs_ao.legacy",
    )
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.append(node.module)
    assert not any(
        module.startswith(forbidden_import_roots)
        for module in imports
    ), imports


def test_controller_is_the_only_control_module_that_owns_a_latency_queue() -> None:
    offenders: list[tuple[str, int, str]] = []
    for path in sorted(CONTROL.glob("*.py")):
        if path.name == "controller.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _called_name(node) == "deque":
                offenders.append((path.name, node.lineno, "deque"))
            if isinstance(node, ast.Name) and node.id in {
                "delay_queue",
                "latency_queue",
            }:
                offenders.append((path.name, node.lineno, node.id))
    assert offenders == []


def test_loop_does_not_construct_hidden_random_generators() -> None:
    tree = _tree("loop.py")
    forbidden = {"NamedRandomStreams", "RandomState", "default_rng"}
    offenders = [
        (node.lineno, name)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (name := _called_name(node)) in forbidden
    ]
    assert offenders == []


def test_installed_detector_loop_is_only_a_private_canonical_adapter() -> None:
    tree = ast.parse(
        (LEGACY / "ao_closed_loop.py").read_text(encoding="utf-8")
    )
    wrapper = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "run_detector_integrator_loop"
    )
    called = [
        name
        for node in ast.walk(wrapper)
        if isinstance(node, ast.Call)
        and (name := _called_name(node)) is not None
    ]

    assert called.count("_run_legacy_detector_integrator") == 1
    assert set(called).isdisjoint(
        {
            "LeakyIntegratorController",
            "LoopConfig",
            "measure_detector_shwfs",
            "reconstruct",
            "run_closed_loop",
        }
    )
    assert not any(
        isinstance(node, ast.Name)
        and node.id in {"delay_queue", "latency_queue"}
        for node in ast.walk(wrapper)
    )


def test_legacy_control_compatibility_module_has_no_public_definitions() -> None:
    tree = ast.parse(
        (LEGACY / "_control_adapters.py").read_text(encoding="utf-8")
    )
    definitions = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    assert definitions
    assert all(name.startswith("_") for name in definitions)

    exports = [
        node.value
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "__all__"
    ]
    assert len(exports) == 1
    assert isinstance(exports[0], ast.Tuple)
    assert exports[0].elts == []


def test_private_legacy_adapter_delegates_sequencing_to_canonical_runner() -> None:
    tree = ast.parse(
        (LEGACY / "_control_adapters.py").read_text(encoding="utf-8")
    )
    adapter = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_run_legacy_detector_integrator"
    )
    called = [
        name
        for node in ast.walk(adapter)
        if isinstance(node, ast.Call)
        and (name := _called_name(node)) is not None
    ]

    assert called.count("run_closed_loop") == 1
    assert called.count("from_loop_config") == 1
    assert not any(
        isinstance(node, ast.Name)
        and node.id in {"delay_queue", "latency_queue"}
        for node in ast.walk(tree)
    )
