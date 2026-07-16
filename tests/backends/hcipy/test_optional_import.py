"""Optional-dependency behavior that must hold with or without HCIPy.

These tests are deliberately unmarked: they run in the native selection and
from the wheel-smoke bundle.  Tests that require HCIPy to be *absent* skip
themselves on HCIPy-equipped environments instead of using the ``hcipy``
marker, which is reserved for tests that need the dependency present.
"""

from __future__ import annotations

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


HCIPY_INSTALLED = hcipy_installed()
_CONVERSION_TEST_FILE = Path(__file__).with_name("test_conversion.py")


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


def test_hcipy_marked_tests_never_enter_the_native_selection():
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
            str(_CONVERSION_TEST_FILE),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    # Exit code 5 is pytest's "no tests collected": every test in the
    # conversion module must carry the hcipy marker and be deselected.
    assert result.returncode == 5, result.stdout + result.stderr
    assert "::" not in result.stdout


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
