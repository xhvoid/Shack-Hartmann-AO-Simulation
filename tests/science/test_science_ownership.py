"""AO-REF-010 ownership and public-surface guards."""

from __future__ import annotations

import ast
import inspect
import os
from pathlib import Path
import subprocess
import sys

from shwfs_ao.backends import native
from shwfs_ao.backends.native import propagation as native_propagation
import shwfs_ao.science as science
from shwfs_ao.science import bandpass, metrics, propagation


ROOT = Path(__file__).resolve().parents[2]
SCIENCE_ROOT = ROOT / "src" / "shwfs_ao" / "science"
LEGACY_ROOT = ROOT / "src" / "shwfs_ao" / "legacy"

EXPECTED_BANDPASS_EXPORTS = (
    "BandpassError",
    "ScienceBandpass",
    "monochromatic_bandpass",
    "top_hat_bandpass",
    "bandpass_from_filter_curve",
)
EXPECTED_PROPAGATION_EXPORTS = (
    "SciencePropagationError",
    "PsfSampling",
    "monochromatic_psf",
)
EXPECTED_METRIC_EXPORTS = (
    "ScienceMetricsError",
    "PsfScalarMetrics",
    "discrete_flux_to_angular_surface_brightness",
    "peak_strehl_from_discrete_flux",
    "marechal_strehl_from_opd",
    "fwhm_diameter_from_angular_surface_brightness",
    "encircled_energy_radius_from_discrete_flux",
    "halo_fraction_from_discrete_flux",
    "psf_scalar_metrics",
    "band_average_scalar_metrics",
    "lambda_over_d_rad",
    "radians_to_lambda_over_d",
    "radians_to_arcsec",
)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _call_names(tree: ast.AST) -> tuple[str, ...]:
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if isinstance(function, ast.Name):
            names.append(function.id)
        elif isinstance(function, ast.Attribute):
            parts = [function.attr]
            value = function.value
            while isinstance(value, ast.Attribute):
                parts.append(value.attr)
                value = value.value
            if isinstance(value, ast.Name):
                parts.append(value.id)
            names.append(".".join(reversed(parts)))
    return tuple(names)


def test_science_package_has_exact_explicit_aggregate_surface() -> None:
    assert bandpass.__all__ == EXPECTED_BANDPASS_EXPORTS
    assert propagation.__all__ == EXPECTED_PROPAGATION_EXPORTS
    assert metrics.__all__ == EXPECTED_METRIC_EXPORTS
    assert native_propagation.__all__ == ("NativeSciencePropagator",)
    assert native.NativeSciencePropagator is native_propagation.NativeSciencePropagator
    assert science.__all__ == (
        *EXPECTED_BANDPASS_EXPORTS,
        *EXPECTED_PROPAGATION_EXPORTS,
        *EXPECTED_METRIC_EXPORTS,
    )
    for module, names in (
        (bandpass, EXPECTED_BANDPASS_EXPORTS),
        (propagation, EXPECTED_PROPAGATION_EXPORTS),
        (metrics, EXPECTED_METRIC_EXPORTS),
    ):
        assert all(getattr(science, name) is getattr(module, name) for name in names)


def test_science_modules_do_not_depend_on_detector_controller_or_legacy() -> None:
    forbidden_fragments = (".detector", ".control", ".legacy")
    for path in (
        SCIENCE_ROOT / "bandpass.py",
        SCIENCE_ROOT / "propagation.py",
        SCIENCE_ROOT / "metrics.py",
    ):
        tree = _tree(path)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(("." * node.level) + (node.module or ""))
        assert not any(
            fragment in imported
            for imported in imports
            for fragment in forbidden_fragments
        ), (path, imports)


def test_native_fft_has_one_owner_and_legacy_psf_is_only_a_delegate() -> None:
    interface_calls = _call_names(_tree(SCIENCE_ROOT / "propagation.py"))
    propagation_calls = _call_names(
        _tree(ROOT / "src" / "shwfs_ao" / "backends" / "native" / "propagation.py")
    )
    legacy_calls = _call_names(_tree(LEGACY_ROOT / "psf_tools.py"))

    assert "np.fft.fft2" not in interface_calls
    assert propagation_calls.count("np.fft.fft2") == 1
    assert "np.fft.fft2" not in legacy_calls
    assert legacy_calls.count("_canonical_fft_psf_from_phase") == 1
    assert legacy_calls.count("_canonical_peak_strehl") == 1


def test_native_science_import_does_not_load_detector_or_controller_stack() -> None:
    script = """
import sys
from shwfs_ao.core.geometry import build_pupil_geometry
from shwfs_ao.science.propagation import PsfSampling, monochromatic_psf
import numpy as np

pupil = build_pupil_geometry(telescope_diameter_m=2.0, pupil_shape=(8, 8))
opd = np.where(pupil.pupil_mask, 0.0, np.nan)
monochromatic_psf(
    opd,
    pupil,
    1.0e-6,
    backend="native",
    sampling=PsfSampling(2),
)
forbidden = (
    "shwfs_ao.detector",
    "shwfs_ao.control",
    "shwfs_ao.wfs.shack_hartmann",
)
loaded = sorted(
    name for name in sys.modules if any(name.startswith(root) for root in forbidden)
)
assert loaded == [], loaded
"""
    env = os.environ.copy()
    source_root = str(ROOT / "src")
    env["PYTHONPATH"] = os.pathsep.join(
        item for item in (source_root, env.get("PYTHONPATH", "")) if item
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert dir(native).count("NativeSciencePropagator") == 1


def test_legacy_diagnostics_has_no_second_scalar_metric_engine() -> None:
    path = LEGACY_ROOT / "ao_diagnostics.py"
    source = path.read_text(encoding="utf-8")
    calls = _call_names(_tree(path))

    assert calls.count("_psf_scalar_metrics") == 1
    assert calls.count("_canonical_weighted_scalar_fields") == 1
    assert "def _weighted_metrics" not in source
    for removed_kernel in (
        "_fwhm_diameter_px",
        "_encircled_energy_radius_px",
        "_halo_fraction",
        "_radial_profile_fraction",
    ):
        assert removed_kernel not in source


def test_band_average_api_cannot_accept_or_coadd_psf_images() -> None:
    signature = inspect.signature(metrics.band_average_scalar_metrics)
    assert tuple(signature.parameters) == ("metrics", "weights")
    calls = _call_names(_tree(SCIENCE_ROOT / "metrics.py"))
    assert not ({"np.stack", "np.vstack", "np.hstack", "np.concatenate"} & set(calls))


def test_physical_metric_kernel_never_constructs_raw_index_coordinates() -> None:
    calls = _call_names(_tree(SCIENCE_ROOT / "metrics.py"))
    assert "np.indices" not in calls
    assert "np.arange" not in calls
