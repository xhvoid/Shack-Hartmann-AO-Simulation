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
from shwfs_ao.backends.hcipy.dm import (
    HcipyDmError,
    build_hcipy_deformable_mirror,
)
from shwfs_ao.backends.hcipy.propagation import (
    HcipyFocalSampling,
    HcipySciencePropagationError,
    HcipySciencePropagator,
)
from shwfs_ao.backends.hcipy.shwfs import (
    HcipyShackHartmannError,
    HcipyShackHartmannOptics,
)
from shwfs_ao.core.geometry import build_pupil_geometry
from shwfs_ao.wfs.shack_hartmann.geometry import build_shack_hartmann_geometry


HCIPY_INSTALLED = hcipy_installed()
_HCIPY_MARKED_TEST_FILES = (
    Path(__file__).with_name("test_conversion.py"),
    Path(__file__).with_name("test_hcipy_atmosphere.py"),
    Path(__file__).with_name("test_hcipy_dm.py"),
    Path(__file__).with_name("test_hcipy_shwfs.py"),
    Path(__file__).with_name("test_hcipy_propagation.py"),
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
        "import shwfs_ao.backends.hcipy.dm\n"
        "import shwfs_ao.backends.hcipy.shwfs\n"
        "import shwfs_ao.backends.hcipy.propagation\n"
        "import shwfs_ao.science.propagation\n"
        "from shwfs_ao.backends.hcipy import HcipyAtmosphereConfig\n"
        "from shwfs_ao.backends.hcipy import HcipyDmError\n"
        "from shwfs_ao.backends.hcipy import HcipyShackHartmannOptics\n"
        "from shwfs_ao.backends.hcipy import HcipySciencePropagator\n"
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
    if not test_file.is_file():
        pytest.skip(
            f"{test_file.name} is not in this test tree (native-only "
            "wheel-smoke bundles omit hcipy-marked modules)"
        )
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


@pytest.mark.parametrize(
    "module_name",
    ("atmosphere", "dm", "shwfs", "propagation"),
)
def test_hcipy_backend_modules_never_import_legacy_code(module_name):
    import importlib

    module = importlib.import_module(
        f"shwfs_ao.backends.hcipy.{module_name}"
    )
    source_file = inspect.getsourcefile(module)
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

    def test_dm_construction_raises_optional_dependency_error(self):
        geometry = build_pupil_geometry(
            telescope_diameter_m=1.0,
            pupil_shape=(8, 8),
        )
        with pytest.raises(OptionalDependencyError) as excinfo:
            build_hcipy_deformable_mirror(
                geometry.x_m,
                geometry.y_m,
                geometry.pupil_mask,
            )
        assert "pip install 'shack-hartmann-ao-simulation[hcipy]'" in str(
            excinfo.value
        )

    def test_dm_validation_precedes_the_dependency_requirement(self):
        geometry = build_pupil_geometry(
            telescope_diameter_m=1.0,
            pupil_shape=(8, 8),
        )
        with pytest.raises(HcipyDmError, match="DMConfig"):
            build_hcipy_deformable_mirror(
                geometry.x_m,
                geometry.y_m,
                geometry.pupil_mask,
                config=object(),
            )
        with pytest.raises(HcipyDmError, match="shape"):
            build_hcipy_deformable_mirror(
                geometry.x_m,
                geometry.y_m,
                np.ones((4, 4), dtype=bool),
            )

    def test_shwfs_construction_raises_optional_dependency_error(self):
        geometry = build_shack_hartmann_geometry(
            telescope_diameter_m=1.0,
            pupil_shape=(16, 16),
            n_lenslets_across=2,
            min_fill_fraction=0.3,
        )
        with pytest.raises(OptionalDependencyError) as excinfo:
            HcipyShackHartmannOptics(geometry, 700.0e-9, f_number=100.0)
        assert "pip install 'shack-hartmann-ao-simulation[hcipy]'" in str(
            excinfo.value
        )

    def test_shwfs_validation_precedes_the_dependency_requirement(self):
        with pytest.raises(
            HcipyShackHartmannError,
            match="ShackHartmannGeometry",
        ):
            HcipyShackHartmannOptics(object(), 700.0e-9, f_number=100.0)
        geometry = build_shack_hartmann_geometry(
            telescope_diameter_m=1.0,
            pupil_shape=(18, 18),
            n_lenslets_across=4,
            min_fill_fraction=0.3,
        )
        with pytest.raises(
            HcipyShackHartmannError,
            match="integer multiple",
        ):
            HcipyShackHartmannOptics(geometry, 700.0e-9, f_number=100.0)

    def test_science_propagator_raises_optional_dependency_error(self):
        pupil = build_pupil_geometry(
            telescope_diameter_m=1.0,
            pupil_shape=(8, 8),
        )
        with pytest.raises(OptionalDependencyError) as excinfo:
            HcipySciencePropagator(pupil, HcipyFocalSampling())
        assert "pip install 'shack-hartmann-ao-simulation[hcipy]'" in str(
            excinfo.value
        )

    def test_science_registry_requires_the_dependency_for_hcipy(self):
        from shwfs_ao.science.propagation import (
            PsfSampling,
            monochromatic_psf,
        )

        pupil = build_pupil_geometry(
            telescope_diameter_m=1.0,
            pupil_shape=(8, 8),
        )
        with pytest.raises(OptionalDependencyError):
            monochromatic_psf(
                np.zeros(pupil.pupil_shape),
                pupil,
                700.0e-9,
                backend="hcipy",
                sampling=PsfSampling(),
            )

    def test_science_validation_precedes_the_dependency_requirement(self):
        pupil = build_pupil_geometry(
            telescope_diameter_m=1.0,
            pupil_shape=(8, 8),
        )
        with pytest.raises(
            HcipySciencePropagationError,
            match="PupilGeometry",
        ):
            HcipySciencePropagator(object())
        with pytest.raises(
            HcipySciencePropagationError,
            match="HcipyFocalSampling",
        ):
            HcipySciencePropagator(pupil, sampling=object())
        with pytest.raises(
            HcipySciencePropagationError,
            match="pixels_per_resolution_element",
        ):
            HcipyFocalSampling(pixels_per_resolution_element=-2.0)
