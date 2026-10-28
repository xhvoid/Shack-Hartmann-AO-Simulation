"""Silent compatibility shim for :mod:`shwfs_ao.legacy.runtime_resources`."""

from shwfs_ao.legacy import runtime_resources as _implementation
from shwfs_ao.legacy.runtime_resources import (
    Iterator,
    Path,
    RESOURCE_PACKAGE,
    SOURCE_REPOSITORY_ROOT,
    TextIO,
    contextmanager,
    normalized_resource_name,
    open_text_resource,
    resource_exists,
    resources,
)

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
