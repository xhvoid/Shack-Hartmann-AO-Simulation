"""Characterization of the installed experimental PWFS boundary."""

from __future__ import annotations

import ast
import hashlib
import inspect
from pathlib import Path

import numpy as np

import pwfs_forward as top_level
from shwfs_ao.experimental import pwfs as experimental
from shwfs_ao.legacy import pwfs_forward as legacy


ROOT = Path(__file__).resolve().parents[2]

FROZEN_LEGACY_PUBLIC_NAMES = {
    "add_detector_noise",
    "add_tilt_phase",
    "aligned_pupil_images",
    "calibrate_pwfs_interaction_matrix",
    "check_pwfs_geometry",
    "extract_cutout",
    "fft2c",
    "ifft2c",
    "make_aligned_pupil_mask",
    "make_modulation_points",
    "make_pwfs_grid",
    "np",
    "pupil_image_centers",
    "pwfs_detector_measurement_from_phase",
    "pwfs_detector_signal_from_phase",
    "pwfs_intensity",
    "pwfs_measurement_from_phase",
    "pwfs_reference_signal",
    "pwfs_signal_from_intensity",
    "pwfs_signal_from_phase",
    "pwfs_signal_maps_from_intensity",
    "pyramid_phase_mask",
}


def test_legacy_and_top_level_pwfs_surfaces_delegate_to_one_experimental_owner():
    legacy_public = {name for name in vars(legacy) if not name.startswith("_")}

    assert legacy_public == FROZEN_LEGACY_PUBLIC_NAMES
    assert set(top_level.__all__) == FROZEN_LEGACY_PUBLIC_NAMES
    assert set(experimental.__all__) == FROZEN_LEGACY_PUBLIC_NAMES - {"np"}

    for name in FROZEN_LEGACY_PUBLIC_NAMES:
        assert getattr(legacy, name) is getattr(experimental, name)
        assert getattr(top_level, name) is getattr(experimental, name)

    for name in experimental.__all__:
        assert getattr(experimental, name).__module__ == "shwfs_ao.experimental.pwfs"
        assert inspect.signature(getattr(legacy, name)) == inspect.signature(
            getattr(experimental, name)
        )


def test_legacy_pwfs_module_contains_only_compatibility_imports():
    path = ROOT / "src/shwfs_ao/legacy/pwfs_forward.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    assert not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda))
        for node in ast.walk(tree)
    )
    assert any(
        isinstance(node, ast.ImportFrom)
        and node.module == "shwfs_ao.experimental.pwfs"
        for node in tree.body
    )


def test_experimental_pwfs_retains_the_frozen_seeded_numerical_output():
    x, y, _, _, pupil = experimental.make_pwfs_grid(
        n_fft=32,
        n_pupil=7,
        central_obscuration=0.2,
    )
    phase = np.where(pupil, 0.02 * x - 0.03 * y, np.nan)
    intensity = experimental.pwfs_intensity(
        phase,
        pupil,
        x,
        y,
        separation=8,
        modulation_radius=0.4,
        n_modulation_points=5,
    )
    signal = experimental.pwfs_signal_from_intensity(
        intensity,
        n_pupil=7,
        separation=8,
        central_obscuration=0.2,
    )
    noisy = experimental.add_detector_noise(
        intensity,
        n_photons=10_000,
        read_noise_e=1.25,
        seed=12_345,
    )

    def digest(array: np.ndarray) -> str:
        return hashlib.sha256(np.asarray(array, dtype="<f8").tobytes()).hexdigest()

    assert digest(intensity) == "bdb17d575c92bdf66c47409e73d80cf096de843ac5b8ed86fa43180433428a64"
    assert digest(signal) == "6454603ffb99d15aacc6a2115542b9a987ae64a426659155b29f2e27ad2dfe84"
    assert digest(noisy) == "cfdea5e0c35986ab84750f359f9214e0edf82bac99f66158023eb2d1f193b884"
