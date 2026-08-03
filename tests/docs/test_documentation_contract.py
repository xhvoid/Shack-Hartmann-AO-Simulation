"""Executable AO-REF-022 documentation acceptance checks."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
import importlib.util
from pathlib import Path
import re
import sys

from shwfs_ao.calibration.diagnostics import InteractionDiagnostics
from shwfs_ao.calibration.interaction import InteractionMatrix, ProbeBasis
from shwfs_ao.calibration.reconstructors import ReconstructorCacheInfo
from shwfs_ao.control.history import LoopHistory
from shwfs_ao.core import protocols as core_protocols
from shwfs_ao.core import types as core_types
from shwfs_ao.detector.centroid import CentroidEstimate, CentroidEstimator
from shwfs_ao.detector.random import DetectorRealization
from shwfs_ao.detector.validity import CentroidQuality, CentroidValidity
from shwfs_ao.dm.model import DmBackend
from shwfs_ao.experiments.error_budget import ScenarioResult
from shwfs_ao.experiments.scao import ScaoBackendComponentFactory, ScaoSystem
from shwfs_ao.io.artifacts import IntegrationArtifactResult
from shwfs_ao.science.bandpass import FilterCurve
from shwfs_ao.science.metrics import PsfScalarMetrics
from shwfs_ao.wfs.shack_hartmann.calibration import ShackHartmannCalibration
from shwfs_ao.wfs.shack_hartmann.geometric import (
    GeometricShackHartmannCalibration,
)

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"

# scripts/ is a path-addressed tool directory, not an importable package;
# loading the runner by file keeps collection working under both
# `python -m pytest` (repository root on sys.path) and the bare `pytest`
# entry point (repository root absent).
_README_SMOKE_SPEC = importlib.util.spec_from_file_location(
    "run_readme_smoke_for_docs_tests",
    ROOT / "scripts" / "run_readme_smoke.py",
)
assert _README_SMOKE_SPEC is not None and _README_SMOKE_SPEC.loader is not None
_readme_smoke = importlib.util.module_from_spec(_README_SMOKE_SPEC)
sys.modules[_README_SMOKE_SPEC.name] = _readme_smoke
_README_SMOKE_SPEC.loader.exec_module(_readme_smoke)
parse_readme_commands = _readme_smoke.parse_readme_commands
REQUIRED_DOCS = (
    README,
    ROOT / "docs" / "architecture.md",
    ROOT / "docs" / "validation.md",
    ROOT / "docs" / "provenance.md",
    ROOT / "docs" / "backends.md",
    ROOT / "docs" / "migration.md",
    ROOT / "docs" / "reproducibility.md",
    ROOT / "docs" / "artifact_schemas.md",
)
POSITIONING = (
    "A modular Shack-Hartmann SCAO simulation framework with native and HCIPy "
    "optical backends, custom detector and real-time-control modelling, "
    "science-facing PSF diagnostics, and cross-backend physical validation."
)


def _normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def _protocol_members(protocol: type) -> set[str]:
    members = {name for name in vars(protocol) if not name.startswith("_")}
    members.update(
        name
        for name in getattr(protocol, "__annotations__", {})
        if not name.startswith("_")
    )
    return members


def test_all_required_pages_and_positioning_are_present():
    for path in REQUIRED_DOCS:
        assert path.is_file(), f"Missing AO-REF-022 page: {path}"
        assert path.stat().st_size > 500, f"AO-REF-022 page looks incomplete: {path}"
    assert POSITIONING in _normalized(README)


def test_architecture_has_all_five_current_module_diagrams():
    text = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    assert text.count("```mermaid") == 5
    for title in (
        "Package dependency",
        "AO runtime data flow",
        "Native and HCIPy backend boundary",
        "Calibration workflow",
        "Experiment and artifact flow",
    ):
        assert title in text
    assert "notebooks/legacy/original_notebooks" not in text


def test_every_public_protocol_and_member_is_documented():
    text = (ROOT / "docs" / "backends.md").read_text(encoding="utf-8")
    protocols = [
        *(getattr(core_protocols, name) for name in core_protocols.__all__),
        CentroidEstimator,
        DmBackend,
        ProbeBasis,
        ScaoBackendComponentFactory,
        IntegrationArtifactResult,
        FilterCurve,
    ]
    for protocol in protocols:
        assert protocol.__name__ in text
        for member in _protocol_members(protocol):
            assert re.search(rf"\b{re.escape(member)}\b", text), (
                f"{protocol.__name__}.{member} is missing from docs/backends.md"
            )


def test_every_shared_result_field_is_documented():
    text = (ROOT / "docs" / "backends.md").read_text(encoding="utf-8")
    core_results = [
        getattr(core_types, name)
        for name in core_types.__all__
        if name != "MeasurementUnit"
    ]
    other_results = [
        CentroidEstimate,
        CentroidQuality,
        CentroidValidity,
        DetectorRealization,
        InteractionDiagnostics,
        InteractionMatrix,
        ReconstructorCacheInfo,
        ShackHartmannCalibration,
        GeometricShackHartmannCalibration,
        LoopHistory,
        PsfScalarMetrics,
        ScenarioResult,
        ScaoSystem,
    ]
    for result_type in core_results + other_results:
        assert is_dataclass(result_type)
        assert result_type.__name__ in text
        for field in fields(result_type):
            assert re.search(rf"\b{re.escape(field.name)}\b", text), (
                f"{result_type.__name__}.{field.name} is missing from docs/backends.md"
            )


def test_sign_units_random_domains_and_limitations_are_explicit():
    architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    backends = (ROOT / "docs" / "backends.md").read_text(encoding="utf-8")
    reproducibility = (ROOT / "docs" / "reproducibility.md").read_text(encoding="utf-8")
    validation = " ".join(
        (ROOT / "docs" / "validation.md").read_text(encoding="utf-8").split()
    ).lower()

    for token in (
        "residual_opd_m = atmosphere_opd_m - dm_correction_opd_m",
        "phase_rad = 2.0 * np.pi * opd_m / wavelength_m",
        "m_opd_equivalent",
        "rad_wavefront_slope",
        "unit_total_flux",
    ):
        assert token in architecture + backends

    assert "shwfs_ao.random.sha256-json-pcg64-v1" in reproducibility
    for domain in (
        "detector.realization",
        "detector.shot_noise",
        "detector.read_noise",
        "calibration",
        "atmosphere",
        "ncpa",
    ):
        assert f"`{domain}`" in reproducibility

    for limitation in (
        "not an observatory digital twin",
        "not calibrated to a specific eso instrument",
        "dm calibration and influence functions are synthetic",
        "synthetic/internal",
        "tomography model",
        "pwfs branch is experimental",
        "no elt laser-guide-star (lgs) tomography",
        "does **not** validate observatory performance",
    ):
        assert limitation in validation


def test_schema_upgrade_and_baseline_acceptance_are_documented():
    text = (ROOT / "docs" / "artifact_schemas.md").read_text(encoding="utf-8")
    for schema in (
        "provenance.schema.json",
        "fast_reference_metrics.schema.json",
        "scenario_table_sidecar.schema.json",
        "validation_table_sidecar.schema.json",
        "runtime_table_sidecar.schema.json",
        "artifact_manifest.schema.json",
        "cross_backend_baseline.schema.json",
    ):
        assert schema in text
    for token in (
        "read_v2",
        "read_v3",
        "upgrade_v2_to_v3",
        "run_result",
        "baseline_candidate",
        "accepted_regression_baseline",
        "--generate-candidate",
        "--accept-baseline-update",
        "--reason",
        "--review-reference",
    ):
        assert token in text


def test_every_readme_bash_command_has_a_clean_wheel_ci_owner():
    grouped = parse_readme_commands(README)
    assert grouped["native"]
    assert grouped["hcipy"]

    manifest = (ROOT / "tests" / "wheel_smoke" / "manifest.json").read_text(
        encoding="utf-8"
    )
    assert '"source": "README.md"' in manifest
    assert '"source": "scripts/run_readme_smoke.py"' in manifest

    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for section in ("native", "hcipy"):
        assert f"--section {section} --require-wheel-bundle" in workflow


# The package dependency diagram is a claim about the code, so it is checked
# against the code.  ``resources`` is packaged data rather than a code package
# and the clients live outside ``src/``, so those two nodes carry no derivable
# edges; every other node is checked in both directions.
_DIAGRAM_NODES = {
    "CORE": "core",
    "NATIVE": "backends.native",
    "HCIPY": "backends.hcipy",
    "DETECTOR": "detector",
    "WFS": "wfs.shack_hartmann",
    "DM": "dm",
    "CAL": "calibration",
    "CONTROL": "control",
    "SCIENCE": "science",
    "EXPERIMENTS": "experiments",
    "VALIDATION": "validation",
    "IO": "io",
    "EXPERIMENTAL": "experimental.pwfs",
    "LEGACY": "legacy",
}
_CONTEXT_NODES = {"RESOURCES", "CLIENTS"}
_DIAGRAM_EDGE = re.compile(
    r"^\s*(?P<source>[A-Z]+)\s+"
    r"(?:-->|--\s+\"[^\"]*\"\s+-->|-\.->|-\.\s+\"[^\"]*\"\s+\.->)"
    r"\s+(?P<target>[A-Z]+)\s*$"
)
_DASHED_EDGE = re.compile(r"-\.")


def _package_node(module_parts: list[str]) -> str | None:
    """The diagram node a ``shwfs_ao`` submodule path belongs to."""

    if not module_parts:
        return None
    if module_parts[0] == "backends" and len(module_parts) > 1:
        return f"backends.{module_parts[1]}"
    if module_parts[0] == "wfs":
        return "wfs.shack_hartmann"
    if module_parts[0] == "experimental":
        return "experimental.pwfs"
    return module_parts[0] if module_parts[0] in set(_DIAGRAM_NODES.values()) else None


def _source_import_graph() -> dict[tuple[str, str], str]:
    """Every intra-package import edge, as ``(source, target) -> 'eager'|'deferred'``.

    An edge is eager when at least one import of it sits at module level, and
    deferred when every import of it is inside a function body — the optional
    backends and the factories chosen at build time.
    """

    import ast

    package_root = ROOT / "src" / "shwfs_ao"
    edges: dict[tuple[str, str], str] = {}
    for path in sorted(package_root.rglob("*.py")):
        parts = list(path.relative_to(package_root).with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        source = _package_node(parts)
        if source is None:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        package_parts = parts if path.name == "__init__.py" else parts[:-1]
        deferred_nodes = {
            id(inner)
            for outer in ast.walk(tree)
            if isinstance(outer, (ast.FunctionDef, ast.AsyncFunctionDef))
            for inner in ast.walk(outer)
        }
        for node in ast.walk(tree):
            imported: list[list[str]] = []
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    base = (
                        package_parts[: len(package_parts) - (node.level - 1)]
                        if node.level > 1
                        else package_parts
                    )
                    imported = [
                        base + (node.module.split(".") if node.module else [])
                    ]
                elif (node.module or "").startswith("shwfs_ao"):
                    imported = [node.module.split(".")[1:]]
            elif isinstance(node, ast.Import):
                imported = [
                    alias.name.split(".")[1:]
                    for alias in node.names
                    if alias.name.startswith("shwfs_ao.")
                ]
            for module_parts in imported:
                target = _package_node(module_parts)
                if target is None or target == source:
                    continue
                kind = "deferred" if id(node) in deferred_nodes else "eager"
                if kind == "eager" or (source, target) not in edges:
                    edges[(source, target)] = kind
    return edges


def _diagram_edges() -> dict[tuple[str, str], str]:
    text = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    block = text.split("```mermaid", 1)[1].split("```", 1)[0]
    edges: dict[tuple[str, str], str] = {}
    for line in block.splitlines():
        match = _DIAGRAM_EDGE.match(line)
        if match is None:
            continue
        source, target = match.group("source"), match.group("target")
        if source in _CONTEXT_NODES or target in _CONTEXT_NODES:
            continue
        assert source in _DIAGRAM_NODES, f"unknown diagram node {source!r}"
        assert target in _DIAGRAM_NODES, f"unknown diagram node {target!r}"
        key = (_DIAGRAM_NODES[source], _DIAGRAM_NODES[target])
        kind = "deferred" if _DASHED_EDGE.search(line) else "eager"
        # A node pair drawn twice (a labelled and an unlabelled arrow) is eager
        # if either arrow is.
        if kind == "eager" or key not in edges:
            edges[key] = kind
    return edges


def test_the_package_dependency_diagram_matches_the_real_import_graph():
    """The diagram is a claim about imports, so the imports are the authority.

    A dependency diagram nobody derives drifts silently, and a reader cannot
    tell which arrows are still true — the wrong ones are indistinguishable
    from the right ones.  Deriving it means an arrow that stops existing, or an
    import that appears without one, fails here instead of misleading someone
    reasoning about layering.
    """

    documented = _diagram_edges()
    actual = _source_import_graph()

    missing = sorted(edge for edge in actual if edge not in documented)
    invented = sorted(edge for edge in documented if edge not in actual)
    assert not missing, f"imports with no arrow in docs/architecture.md: {missing}"
    assert not invented, f"arrows in docs/architecture.md with no import: {invented}"

    wrong_kind = sorted(
        (edge, documented[edge], actual[edge])
        for edge in documented
        if documented[edge] != actual[edge]
    )
    assert not wrong_kind, (
        "solid means a module-level import and dashed means one deferred to "
        f"call time; these disagree (edge, documented, actual): {wrong_kind}"
    )
