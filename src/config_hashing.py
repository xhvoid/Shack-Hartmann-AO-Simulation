"""Deprecated compatibility shim for :mod:`shwfs_ao.legacy.config_hashing`.

Importing this root-level module emits a DeprecationWarning built from
the packaged AO-REF-021 clock and inventory metadata; the re-exported
objects stay identical to the shwfs_ao implementations throughout the
compatibility window.
"""

import warnings as _warnings

import shwfs_ao._deprecation as _deprecation

from shwfs_ao.legacy import config_hashing as _implementation
from shwfs_ao.legacy.config_hashing import (
    Any,
    hashlib,
    json,
    np,
    stable_array_descriptor,
)

if hasattr(_implementation, "annotations"):
    annotations = _implementation.annotations

_warnings.warn(
    _deprecation.root_shim_deprecation_message('config_hashing'),
    DeprecationWarning,
    stacklevel=2,
)

__all__ = (
    "Any",
    *(("annotations",) if hasattr(_implementation, "annotations") else ()),
    "hashlib",
    "json",
    "np",
    "stable_array_descriptor",
)
