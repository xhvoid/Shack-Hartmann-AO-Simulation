"""Compatibility facade for canonical array configuration hashing."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np

from ..core.hashing import stable_array_descriptor
