"""Shack-Hartmann adaptive-optics simulation package."""

from importlib.metadata import PackageNotFoundError as _PackageNotFoundError
from importlib.metadata import version as _distribution_version


try:
    __version__ = _distribution_version("shack-hartmann-ao-simulation")
except _PackageNotFoundError:  # pragma: no cover - supports an uninstalled source checkout
    __version__ = "0+unknown"


__all__ = ("__version__",)
