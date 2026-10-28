"""Optional HCIPy backend package.

Importing this package (or its :mod:`conversion` module) never imports HCIPy.
The dependency is resolved lazily through :func:`require_hcipy`, so the core
package, protocols, configurations, and native backends stay importable from
a lightweight installation.  Only calling into HCIPy-backed functionality may
raise :class:`OptionalDependencyError`.
"""

from __future__ import annotations

from importlib import metadata as _metadata
from types import ModuleType


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
)


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
