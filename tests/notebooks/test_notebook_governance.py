"""AO-REF-019 governance: notebook layout, disposition manifest, and rules.

These tests are static (they parse JSON and Python source; they never execute a
kernel) so they run in the ordinary native selection.  They enforce that the
canonical notebooks are thin research narratives built on installed
``shwfs_ao`` APIs, that the disposition manifest covers every AO-REF-000
notebook exactly once, and that the archived originals remain untouched
evidence.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOKS = ROOT / "notebooks"
MANIFEST_PATH = NOTEBOOKS / "notebook_manifest.json"

TUTORIALS = (
    "tutorials/00_wavefront_and_atmosphere.ipynb",
    "tutorials/01_geometric_shwfs.ipynb",
    "tutorials/02_detector_centroiding.ipynb",
    "tutorials/03_tsvd_regularization.ipynb",
    "tutorials/04_closed_loop_control.ipynb",
)
STUDIES = (
    "studies/mode_order_sampling.ipynb",
    "studies/high_order_scao.ipynb",
    "studies/noise_latency_gain.ipynb",
    "studies/detector_level_2m.ipynb",
    "studies/native_vs_hcipy.ipynb",
)
EXPERIMENTAL = ("experimental/pwfs_detector_level_atmosphere.ipynb",)
CANONICAL = TUTORIALS + STUDIES + EXPERIMENTAL

AO_REF_000_IDS = tuple(f"AO-NB-{index:03d}" for index in range(1, 17))

# Third-party / standard-library import roots a thin notebook may use in
# addition to the installed package.  Anything else (a relative import, a
# source-tree module, a networking or path-hacking library) is forbidden.
ALLOWED_IMPORT_ROOTS = frozenset(
    {
        "shwfs_ao",
        "numpy",
        "pandas",
        "matplotlib",
        "math",
        "dataclasses",
        "itertools",
        "collections",
        "functools",
    }
)
FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "sys",
        "os",
        "pathlib",
        "importlib",
        "subprocess",
        "requests",
        "urllib",
        "socket",
        "http",
        "aiohttp",
        "nbconvert",
        "pip",
    }
)
# Names that would signal a notebook re-implementing a packaged AO engine.
FORBIDDEN_DEF_SUBSTRINGS = (
    "closed_loop",
    "interaction_matrix",
    "influence_function",
    "detector_noise",
    "add_noise",
    "phase_to_opd",
    "opd_to_phase",
    "reconstruct",
)


def _load_notebook(relative_path: str) -> dict:
    return json.loads((NOTEBOOKS / relative_path).read_text(encoding="utf-8"))


def _code_source(relative_path: str) -> str:
    notebook = _load_notebook(relative_path)
    return "\n".join(
        "".join(cell["source"])
        for cell in notebook["cells"]
        if cell["cell_type"] == "code"
    )


def _import_roots(source: str) -> set[str]:
    tree = ast.parse(source)
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                roots.add(f"<relative level {node.level}>")
            elif node.module is not None:
                roots.add(node.module.split(".")[0])
    return roots


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def test_target_layout_directories_exist():
    for section in ("tutorials", "studies", "experimental", "legacy/original_notebooks"):
        assert (NOTEBOOKS / section).is_dir(), section


def test_every_canonical_notebook_exists():
    for relative_path in CANONICAL:
        assert (NOTEBOOKS / relative_path).is_file(), relative_path


def test_no_stray_top_level_notebooks_remain():
    stray = sorted(path.name for path in NOTEBOOKS.glob("*.ipynb"))
    assert stray == [], f"top-level notebooks must be filed into the layout: {stray}"


def test_all_sixteen_originals_are_archived_unchanged():
    archived = sorted(
        path.name for path in (NOTEBOOKS / "legacy/original_notebooks").glob("*.ipynb")
    )
    assert len(archived) == 16, archived


# ---------------------------------------------------------------------------
# Disposition manifest
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_manifest_schema_identity(manifest):
    assert manifest["schema_name"] == "shwfs_ao.notebook_disposition_manifest"
    assert manifest["schema_version"] == 1
    assert manifest["ticket"] == "AO-REF-019"


def test_manifest_covers_every_ao_ref_000_id_exactly_once(manifest):
    ids = [entry["id"] for entry in manifest["originals"]]
    assert sorted(ids) == sorted(AO_REF_000_IDS)
    assert len(ids) == len(set(ids)), "an AO-REF-000 id maps twice"


def test_manifest_original_entries_carry_every_required_field(manifest):
    required = {
        "id",
        "archived_path",
        "source_sha256",
        "canonical_replacement",
        "content_action",
        "source_action",
        "smoke_test_class",
        "owner",
        "fixed_seed_policy",
        "captured_output_location",
    }
    for entry in manifest["originals"]:
        missing = required - entry.keys()
        assert not missing, f"{entry.get('id')} missing {missing}"
        assert entry["content_action"] in {"merge", "rename"}
        assert entry["source_action"] == "archive"
        assert entry["owner"].strip()
        assert entry["fixed_seed_policy"].strip()


def test_manifest_archived_hashes_match_the_archived_files(manifest):
    for entry in manifest["originals"]:
        archived = ROOT / entry["archived_path"]
        assert archived.is_file(), entry["archived_path"]
        actual = hashlib.sha256(archived.read_bytes()).hexdigest()
        assert actual == entry["source_sha256"], entry["id"]


def test_manifest_canonical_targets_all_exist_and_are_covered(manifest):
    targets = {entry["canonical_replacement"] for entry in manifest["originals"]}
    expected = {f"notebooks/{path}" for path in CANONICAL if not path.endswith("native_vs_hcipy.ipynb")}
    assert targets == expected
    for entry in manifest["originals"]:
        assert (ROOT / entry["canonical_replacement"]).is_file()


def test_manifest_canonical_section_has_owner_class_and_seed(manifest):
    by_path = {entry["path"]: entry for entry in manifest["canonical"]}
    for relative_path in CANONICAL:
        entry = by_path[f"notebooks/{relative_path}"]
        assert entry["owner"].strip()
        assert entry["execution_class"] in {"fast", "slow", "hcipy", "manual"}
        assert entry["fixed_seed_policy"].strip()
        assert entry["captured_output_location"].strip()


def test_merge_targets_have_multiple_sources_and_renames_have_one(manifest):
    counts: dict[str, list[str]] = {}
    for entry in manifest["originals"]:
        counts.setdefault(entry["canonical_replacement"], []).append(entry["content_action"])
    for target, actions in counts.items():
        if len(actions) > 1:
            assert set(actions) == {"merge"}, target
        else:
            assert actions == ["rename"], target


# ---------------------------------------------------------------------------
# Notebook rules
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("relative_path", CANONICAL)
def test_canonical_notebook_imports_are_installed_only(relative_path):
    roots = _import_roots(_code_source(relative_path))
    forbidden = roots & FORBIDDEN_IMPORT_ROOTS
    assert not forbidden, f"{relative_path} imports forbidden roots {forbidden}"
    relative = {root for root in roots if root.startswith("<relative")}
    assert not relative, f"{relative_path} uses source-tree relative imports"
    unexpected = roots - ALLOWED_IMPORT_ROOTS
    assert not unexpected, f"{relative_path} imports unexpected roots {unexpected}"


@pytest.mark.parametrize("relative_path", CANONICAL)
def test_canonical_notebook_uses_the_installed_package(relative_path):
    assert "shwfs_ao" in _import_roots(_code_source(relative_path))


@pytest.mark.parametrize("relative_path", CANONICAL)
def test_canonical_notebook_has_no_path_or_engine_definitions(relative_path):
    source = _code_source(relative_path)
    assert "sys.path" not in source, f"{relative_path} modifies sys.path"
    assert ".fft" not in source, f"{relative_path} defines a local propagation engine"
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            lowered = node.name.lower()
            hit = [token for token in FORBIDDEN_DEF_SUBSTRINGS if token in lowered]
            assert not hit, f"{relative_path} defines engine-like {node.name!r} ({hit})"


@pytest.mark.parametrize("relative_path", CANONICAL)
def test_canonical_notebook_does_not_write_files_or_shell_out(relative_path):
    source = _code_source(relative_path)
    for forbidden in ("!pip", "!python", "subprocess", "get_ipython", "%%bash"):
        assert forbidden not in source, f"{relative_path} contains {forbidden!r}"


def test_high_order_and_2m_studies_share_the_loop_engine():
    # Acceptance: notebook 09 and 11 use the same shared loop engine.
    for relative_path in ("studies/high_order_scao.ipynb", "studies/detector_level_2m.ipynb"):
        source = _code_source(relative_path)
        assert "run_closed_loop" in source, relative_path
        assert "from shwfs_ao.control import" in source, relative_path


def test_canonical_notebooks_have_executed_outputs():
    # Primary notebooks ship captured outputs; experimental/manual excluded is
    # not needed because all canonical notebooks are executed on commit.
    for relative_path in CANONICAL:
        notebook = _load_notebook(relative_path)
        has_output = any(
            cell["cell_type"] == "code" and cell.get("outputs")
            for cell in notebook["cells"]
        )
        assert has_output, f"{relative_path} has no captured outputs"
        for cell in notebook["cells"]:
            if cell["cell_type"] != "code":
                continue
            for output in cell.get("outputs", ()):
                assert output.get("output_type") != "error", relative_path
