"""Transparent NumPy reference implementations of AO backend contracts.

Aggregate symbols are loaded on first access.  This keeps the science-only
propagation path independent of detector and WFS modules while preserving the
established ``shwfs_ao.backends.native`` import surface.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


__all__ = (
    "NativeAtmosphereError",
    "StaticOpdAtmosphere",
    "FrozenFlowAtmosphereConfig",
    "FrozenFlowAtmosphere",
    "NativeSciencePropagator",
    "NativeShackHartmannError",
    "NativeShackHartmannOptics",
    "NativeShackHartmannOpticsBackend",
    "nominal_lenslet_sampling_shape",
    "lenslet_spot_from_phase",
    "lenslet_spot_from_opd",
    "crop_center",
    "NativeDmError",
    "NativeDmBackend",
    "VALID_INFLUENCE_MODELS",
    "square_grid_actuator_layout",
    "square_grid_actuator_centers",
    "actuator_centers_on_pupil",
    "gaussian_influence_functions",
    "build_influence_functions",
    "synthesize_opd",
    "NativeModesError",
    "polar_pupil_coordinates",
    "normalize_mode_to_unit_pupil_rms",
    "zernike_named_modes",
    "zernike_radial",
    "zernike_nm",
    "generate_zernike_modes",
    "number_of_zernike_modes",
    "synthesize_modes",
    "mode_inner_product",
    "mode_gram_matrix",
)


_EXPORT_MODULE = {
    **{
        name: "atmosphere"
        for name in (
            "NativeAtmosphereError",
            "StaticOpdAtmosphere",
            "FrozenFlowAtmosphereConfig",
            "FrozenFlowAtmosphere",
        )
    },
    "NativeSciencePropagator": "propagation",
    **{
        name: "shwfs"
        for name in (
            "NativeShackHartmannError",
            "NativeShackHartmannOptics",
            "NativeShackHartmannOpticsBackend",
            "nominal_lenslet_sampling_shape",
            "lenslet_spot_from_phase",
            "lenslet_spot_from_opd",
            "crop_center",
        )
    },
    **{
        name: "dm"
        for name in (
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
    },
    **{
        name: "modes"
        for name in (
            "NativeModesError",
            "polar_pupil_coordinates",
            "normalize_mode_to_unit_pupil_rms",
            "zernike_named_modes",
            "zernike_radial",
            "zernike_nm",
            "generate_zernike_modes",
            "number_of_zernike_modes",
            "synthesize_modes",
            "mode_inner_product",
            "mode_gram_matrix",
        )
    },
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"{__name__}.{module_name}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
