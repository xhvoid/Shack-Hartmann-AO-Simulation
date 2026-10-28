"""Execution-host utilities that never import the numerical stack.

``shwfs_ao.runtime`` holds the desktop-safe resource policy used by the ESO
SCAO benchmark tiers and their tests: memory-budget preflight, native-library
thread limits, and a process-group supervisor.  Every module here depends only
on the standard library (``psutil`` is used when it is installed), so a
supervising parent process can apply thread limits to a child before the child
imports NumPy.
"""

from __future__ import annotations


__all__: tuple[str, ...] = ()
