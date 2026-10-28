"""Optional-dependency behavior that must hold with or without HCIPy.

These tests are deliberately unmarked: they run in the native selection and
from the wheel-smoke bundle.  Tests that require HCIPy to be *absent* skip
themselves on HCIPy-equipped environments instead of using the ``hcipy``
marker, which is reserved for tests that need the dependency present.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from shwfs_ao.backends.hcipy import (
    OPTIONAL_DEPENDENCY_HINT,
    OptionalDependencyError,
    hcipy_installed,
)
from shwfs_ao.backends.hcipy import conversion as cv
from shwfs_ao.backends.hcipy.atmosphere import (
    HcipyAtmosphereConfig,
    HcipyAtmosphereError,
    HcipyVonKarmanAtmosphere,
)
from shwfs_ao.core.geometry import build_pupil_geometry


HCIPY_INSTALLED = hcipy_installed()
_HCIPY_MARKED_TEST_FILES = (
    Path(__file__).with_name("test_conversion.py"),
    Path(__file__).with_name("test_hcipy_atmosphere.py"),
)


def test_hcipy_package_and_conversion_module_import_lazily():
    # Arriving here proves the module-level imports above did not need HCIPy;
    # this assertion documents the hint every failure path must carry.
    assert "pip install 'shack-hartmann-ao-simulation[hcipy]'" in (
        OPTIONAL_DEPENDENCY_HINT
    )
    assert issubclass(OptionalDependencyError, ImportError)


def test_importing_shwfs_ao_never_imports_hcipy_eagerly():
    program = (
        "import sys\n"
        "import shwfs_ao\n"
        "import shwfs_ao.core.protocols\n"
        "import shwfs_ao.core.types\n"
        "import shwfs_ao.backends.native\n"
        "import shwfs_ao.backends.hcipy\n"
        "import shwfs_ao.backends.hcipy.conversion\n"
        "import shwfs_ao.backends.hcipy.atmosphere\n"
        "from shwfs_ao.backends.hcipy import HcipyAtmosphereConfig\n"
        "import shwfs_ao.experiments.scao\n"
        "import shwfs_ao.io.configs\n"
        "raise SystemExit(1 if 'hcipy' in sys.modules else 0)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "test_file",
    _HCIPY_MARKED_TEST_FILES,
    ids=lambda path: path.stem,
)
def test_hcipy_marked_tests_never_enter_the_native_selection(test_file):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "--collect-only",
            "-q",
            "-m",
            "not hcipy and not slow",
            str(test_file),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    # Exit code 5 is pytest's "no tests collected": every test in these
    # modules must carry the hcipy marker and be deselected.
    assert result.returncode == 5, result.stdout + result.stderr
    assert "::" not in result.stdout


def test_atmosphere_module_never_imports_legacy_code():
    import shwfs_ao.backends.hcipy.atmosphere as atmosphere_module

    source_file = inspect.getsourcefile(atmosphere_module)
    assert source_file is not None
    tree = ast.parse(Path(source_file).read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported_modules.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    assert not any(
        module == "legacy" or module.startswith("legacy.") or ".legacy" in module
        for module in imported_modules
    )


@pytest.mark.skipif(
    HCIPY_INSTALLED,
    reason="requires an environment without the optional HCIPy dependency",
)
class TestWithoutHcipy:
    def test_conversion_raises_optional_dependency_error(self):
        x_m, y_m = np.meshgrid(
            np.linspace(-1.0, 1.0, 5),
            np.linspace(-1.0, 1.0, 4),
            indexing="xy",
        )
        with pytest.raises(OptionalDependencyError) as excinfo:
            cv.hcipy_grid_from_coordinates(x_m, y_m)
        assert "pip install 'shack-hartmann-ao-simulation[hcipy]'" in str(
            excinfo.value
        )

    def test_input_validation_precedes_the_dependency_requirement(self):
        mask = np.zeros((4, 5), dtype=bool)
        mask[1:3, 1:4] = True
        values = np.where(mask, 1.0, np.nan)
        values[1, 1] = np.nan
        with pytest.raises(cv.HcipyConversionError, match="finite"):
            cv.field_from_masked_array(values, mask, grid=None)

    def test_hcipy_version_requires_the_dependency(self):
        from shwfs_ao.backends.hcipy import hcipy_version

        with pytest.raises(OptionalDependencyError):
            hcipy_version()

    def test_atmosphere_construction_raises_optional_dependency_error(self):
        geometry = build_pupil_geometry(
            telescope_diameter_m=1.0,
            pupil_shape=(8, 8),
        )
        with pytest.raises(OptionalDependencyError) as excinfo:
            HcipyVonKarmanAtmosphere(
                HcipyAtmosphereConfig.single_layer(r0_m=0.15),
                geometry,
            )
        assert "pip install 'shack-hartmann-ao-simulation[hcipy]'" in str(
            excinfo.value
        )

    def test_atmosphere_validation_precedes_the_dependency_requirement(self):
        geometry = build_pupil_geometry(
            telescope_diameter_m=1.0,
            pupil_shape=(8, 8),
        )
        with pytest.raises(HcipyAtmosphereError, match="r0_m"):
            HcipyAtmosphereConfig.single_layer(r0_m=0.0)
        with pytest.raises(HcipyAtmosphereError, match="shape"):
            HcipyVonKarmanAtmosphere(
                HcipyAtmosphereConfig.single_layer(r0_m=0.15),
                geometry,
                pupil_mask=np.ones((4, 4), dtype=bool),
            )
