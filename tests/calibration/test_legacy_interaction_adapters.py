"""AO-REF-007 ownership checks for installed legacy calibration builders."""

from __future__ import annotations

import ast
from pathlib import Path

from shwfs_ao.calibration.interaction import calibrate_interaction_matrix
from shwfs_ao.legacy import _interaction_adapters
from shwfs_ao.legacy import interaction_matrix as legacy_interaction_matrix


ROOT = Path(__file__).resolve().parents[2]
LEGACY_ROOT = ROOT / "src" / "shwfs_ao" / "legacy"

MIGRATED_BUILDERS = {
    "reconstruction.py": {
        "build_response_matrix": (
            "_calibrate_legacy_modal_columns",
            {"measure_slopes"},
        ),
    },
    "shwfs_detector.py": {
        "build_detector_response_matrix": (
            "_calibrate_legacy_modal_columns",
            {"measure_centroid_shifts"},
        ),
    },
    "ao_closed_loop.py": {
        "build_dm_wfs_response_matrix": (
            "_calibrate_legacy_influence_columns",
            {"measure_slopes"},
        ),
        "build_dm_detector_response_matrix": (
            "_calibrate_legacy_influence_columns",
            {"measure_centroid_shifts"},
        ),
    },
    "interaction_matrix.py": {
        "build_detector_dm_poke_matrix": (
            "_calibrate_interaction_matrix",
            {"measure_detector_shwfs", "synthesize_dm_phase_rad"},
        ),
    },
    "synthetic_instrument_data.py": {
        "build_tilt_response_matrix": (
            "_calibrate_legacy_modal_columns",
            {"measure_detector_shwfs", "phase_tilt_map_rad"},
        ),
    },
}


def _function_calls(path: Path) -> dict[str, set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result: dict[str, set[str]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        result[node.name] = {
            call.func.id
            for call in ast.walk(node)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
        }
    return result


def test_all_installed_calibration_builders_delegate_without_old_poke_loops() -> None:
    for filename, builders in MIGRATED_BUILDERS.items():
        function_calls = _function_calls(LEGACY_ROOT / filename)
        for function_name, (delegate, forbidden_calls) in builders.items():
            calls = function_calls[function_name]
            assert delegate in calls, (filename, function_name)
            assert calls.isdisjoint(forbidden_calls), (filename, function_name)


def test_legacy_delegates_resolve_to_the_single_canonical_calibrator() -> None:
    assert (
        _interaction_adapters.calibrate_interaction_matrix
        is calibrate_interaction_matrix
    )
    assert (
        legacy_interaction_matrix._calibrate_interaction_matrix
        is calibrate_interaction_matrix
    )

