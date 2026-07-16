"""AO-REF-008 package exports and reconstruction-policy ownership checks."""

from __future__ import annotations

import ast
from pathlib import Path

import shwfs_ao.calibration as calibration
from shwfs_ao.calibration import reconstructors
from shwfs_ao.calibration.reconstructors import _MaskedSvdReconstructor
from shwfs_ao.legacy import _reconstruction_adapters


ROOT = Path(__file__).resolve().parents[2]
LEGACY_ROOT = ROOT / "src" / "shwfs_ao" / "legacy"

RECONSTRUCTOR_EXPORTS = (
    "ReconstructionError",
    "ReconstructorCacheInfo",
    "LeastSquaresReconstructor",
    "TsvdReconstructor",
    "TikhonovReconstructor",
    "kept_modes_for_rcond",
    "noise_amplification_proxy",
    "choose_rcond_from_singular_values",
    "scan_tsvd_rcond",
)

MIGRATED_RECONSTRUCTION_MODULES = (
    "_reconstruction_adapters.py",
    "reconstruction.py",
    "shwfs_detector.py",
    "ao_closed_loop.py",
    "interaction_matrix.py",
)

FORBIDDEN_LINEAR_SOLVE_NAMES = frozenset({"lstsq", "pinv", "svd"})


def _qualified_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        owner = _qualified_name(node.value)
        return None if owner is None else f"{owner}.{node.attr}"
    return None


def _linear_solve_calls(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        name
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        if (name := _qualified_name(node.func)) is not None
        if name.rsplit(".", 1)[-1].lstrip("_") in FORBIDDEN_LINEAR_SOLVE_NAMES
    }


def test_reconstructors_have_one_exact_canonical_export_surface() -> None:
    assert reconstructors.__all__ == RECONSTRUCTOR_EXPORTS
    assert calibration.__all__[-len(RECONSTRUCTOR_EXPORTS) :] == (
        RECONSTRUCTOR_EXPORTS
    )
    assert all(
        getattr(calibration, name) is getattr(reconstructors, name)
        for name in RECONSTRUCTOR_EXPORTS
    )


def test_migrated_legacy_modules_do_not_own_svd_or_pseudoinverse_policy() -> None:
    # Deliberately scoped to WFS reconstruction.  The AO-REF-006
    # OPD-to-DM spatial fit in legacy/dm_model.py is a different responsibility.
    offenders = {
        filename: sorted(calls)
        for filename in MIGRATED_RECONSTRUCTION_MODULES
        if (calls := _linear_solve_calls(LEGACY_ROOT / filename))
    }
    assert offenders == {}


def test_private_legacy_array_adapter_resolves_to_canonical_numeric_owner() -> None:
    assert _reconstruction_adapters.__all__ == ()
    assert (
        _reconstruction_adapters._CanonicalMaskedSvdReconstructor
        is _MaskedSvdReconstructor
    )
