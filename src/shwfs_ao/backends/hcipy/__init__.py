"""Optional HCIPy backend package.

Importing this package (or its :mod:`conversion` module) never imports HCIPy.
The dependency is resolved lazily through :func:`require_hcipy`, so the core
package, protocols, configurations, and native backends stay importable from
a lightweight installation.  Only calling into HCIPy-backed functionality may
raise :class:`OptionalDependencyError`.
"""

from __future__ import annotations

from importlib import import_module as _import_module
from importlib import metadata as _metadata
from types import ModuleType
from typing import Any


HCIPY_DISTRIBUTION_NAME = "hcipy"
HCIPY_REQUIREMENT = "hcipy>=0.7,<0.8"
OPTIONAL_DEPENDENCY_HINT = (
    "HCIPy backend requires installation with "
    "`pip install 'shack-hartmann-ao-simulation[hcipy]'`."
)

__all__ = (
    "HCIPY_DISTRIBUTION_NAME",
    "HCIPY_REQUIREMENT",
    "OPTIONAL_DEPENDENCY_HINT",
    "OptionalDependencyError",
    "hcipy_installed",
    "hcipy_version",
    "require_hcipy",
    "WIND_CONVENTION",
    "HcipyAtmosphereError",
    "HcipyAtmosphereLayerConfig",
    "HcipyAtmosphereConfig",
    "HcipyVonKarmanAtmosphere",
    "SURFACE_COMMAND_CONVENTION",
    "HcipyDmError",
    "HcipyDmBackend",
    "build_hcipy_gaussian_influence_basis",
    "build_hcipy_deformable_mirror",
    "HcipyShackHartmannError",
    "HcipyShackHartmannOptics",
)


_EXPORT_MODULE = {
    name: "atmosphere"
    for name in (
        "WIND_CONVENTION",
        "HcipyAtmosphereError",
        "HcipyAtmosphereLayerConfig",
        "HcipyAtmosphereConfig",
        "HcipyVonKarmanAtmosphere",
    )
}
_EXPORT_MODULE.update(
    {
        name: "dm"
        for name in (
            "SURFACE_COMMAND_CONVENTION",
            "HcipyDmError",
            "HcipyDmBackend",
            "build_hcipy_gaussian_influence_basis",
            "build_hcipy_deformable_mirror",
        )
    }
)
_EXPORT_MODULE.update(
    {
        name: "shwfs"
        for name in (
            "HcipyShackHartmannError",
            "HcipyShackHartmannOptics",
        )
    }
)


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(_import_module(f"{__name__}.{module_name}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


class OptionalDependencyError(ImportError):
    """Raised when an optional backend dependency is not installed."""


def hcipy_installed() -> bool:
    """Return whether the optional HCIPy dependency can be imported."""

    try:
        import hcipy  # noqa: F401  (availability probe only)
    except ImportError:
        return False
    return True


def require_hcipy() -> ModuleType:
    """Import and return HCIPy, or fail with the documented install hint."""

    try:
        import hcipy
    except ImportError as exc:
        raise OptionalDependencyError(OPTIONAL_DEPENDENCY_HINT) from exc
    return hcipy


def hcipy_version() -> str:
    """Return the installed HCIPy distribution version string."""

    require_hcipy()
    try:
        return _metadata.version(HCIPY_DISTRIBUTION_NAME)
    except _metadata.PackageNotFoundError:
        # An importable module without distribution metadata still reports a
        # best-effort version rather than pretending HCIPy is absent.
        import hcipy

        return str(getattr(hcipy, "__version__", "unknown"))
