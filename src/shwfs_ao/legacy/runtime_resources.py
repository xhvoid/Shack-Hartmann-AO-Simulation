"""Explicit compatibility facade for :mod:`shwfs_ao.io.resources`."""

from __future__ import annotations

from shwfs_ao.io import resources as _implementation
from shwfs_ao.io.resources import (
    Iterator,
    Path,
    TextIO,
    contextmanager,
    normalized_resource_name,
    open_text_resource,
    resource_exists,
    resources,
)

RESOURCE_PACKAGE = "ao_simulation_data"
SOURCE_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

if hasattr(_implementation, "annotations"):
    annotations = _implementation.annotations

__all__ = (
    "Iterator",
    "Path",
    "RESOURCE_PACKAGE",
    "SOURCE_REPOSITORY_ROOT",
    "TextIO",
    *(("annotations",) if hasattr(_implementation, "annotations") else ()),
    "contextmanager",
    "normalized_resource_name",
    "open_text_resource",
    "resource_exists",
    "resources",
)
