"""Installed export and notebook-ownership contracts for AO-REF-006."""

from __future__ import annotations

import json
from pathlib import Path

import shwfs_ao
import shwfs_ao.backends.native as native
import shwfs_ao.backends.native.atmosphere as native_atmosphere
import shwfs_ao.backends.native.dm as native_dm
import shwfs_ao.backends.native.modes as native_modes
import shwfs_ao.backends.native.propagation as native_propagation
import shwfs_ao.backends.native.shwfs as native_shwfs
import shwfs_ao.core as core
import shwfs_ao.dm as dm_package
import shwfs_ao.dm.config as dm_config
import shwfs_ao.dm.model as dm_model


ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK_09 = (
    ROOT / "notebooks" / "09_ao_psf_instrument_performance_high_order_ao.ipynb"
)

NATIVE_DM_EXPORTS = (
    "NativeDmError",
    "NativeDmBackend",
    "VALID_INFLUENCE_MODELS",
    "square_grid_actuator_layout",
    "square_grid_actuator_centers",
    "actuator_centers_on_pupil",
    "gaussian_influence_functions",
    "build_influence_functions",
    "synthesize_opd",
)


def test_dm_package_exports_are_exact_identity_reexports() -> None:
    assert dm_package.__all__ == (*dm_config.__all__, *dm_model.__all__)
    assert len(dm_package.__all__) == len(set(dm_package.__all__))
    for source_module in (dm_config, dm_model):
        assert all(
            getattr(dm_package, name) is getattr(source_module, name)
            for name in source_module.__all__
        )

    # AO-REF-006 adds a component package without widening the historical
    # distribution root or the exact Section-4 core surface.
    assert shwfs_ao.__all__ == ("__version__",)
    assert "DmBackend" not in core.__all__


def test_native_dm_exports_are_exact_and_reexported_by_native_package() -> None:
    assert native_dm.__all__ == NATIVE_DM_EXPORTS
    assert native.__all__ == (
        *native_atmosphere.__all__,
        *native_propagation.__all__,
        *native_shwfs.__all__,
        *native_dm.__all__,
        *native_modes.__all__,
    )
    assert all(
        getattr(native, name) is getattr(native_dm, name)
        for name in NATIVE_DM_EXPORTS
    )


def test_notebook_09_delegates_dm_placement_and_gaussian_sampling() -> None:
    notebook = json.loads(NOTEBOOK_09.read_text(encoding="utf-8"))
    dm_cells = [
        cell
        for cell in notebook["cells"]
        if cell.get("id") == "e5b32d9f"
    ]
    assert len(dm_cells) == 1
    source = "".join(dm_cells[0]["source"])
    all_code = "\n".join(
        "".join(cell.get("source", ()))
        for cell in notebook["cells"]
        if cell.get("cell_type") == "code"
    )

    assert "from shwfs_ao.backends.native.dm import" in all_code
    assert "square_grid_actuator_layout(" in source
    assert "build_influence_functions(" in source
    assert "influence_model=\"gaussian\"" in source
    assert "influence = np.exp" not in source
    assert "for y0 in positions_1d" not in source
