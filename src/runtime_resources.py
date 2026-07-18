"""Deprecated compatibility shim for :mod:`shwfs_ao.legacy.runtime_resources`.

Importing this root-level module emits a DeprecationWarning built from
the packaged AO-REF-021 clock and inventory metadata; the re-exported
objects stay identical to the shwfs_ao implementations throughout the
compatibility window.
"""

import warnings as _warnings

import shwfs_ao._deprecation as _deprecation

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

_warnings.warn(
    _deprecation.root_shim_deprecation_message('runtime_resources'),
    DeprecationWarning,
    stacklevel=2,
)

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
