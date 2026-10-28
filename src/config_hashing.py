"""Silent compatibility shim for :mod:`shwfs_ao.legacy.config_hashing`."""

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

__all__ = (
    "Any",
    *(("annotations",) if hasattr(_implementation, "annotations") else ()),
    "hashlib",
    "json",
    "np",
    "stable_array_descriptor",
)
