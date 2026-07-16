"""Compatibility facade for public-data-conditioned observing profiles."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

from ..core.provenance import (
    ALLOWED_SOURCE_CLASSES,
    Provenance as _Provenance,
)
from ..experiments.public_data_conditioned import (
    AOConditionError,
    ARCSEC_PER_RAD,
    ObservingConditionConfig,
    REFERENCE_PHASE_AMPLITUDE_NM,
    REFERENCE_SEEING_ARCSEC,
    condition_rows,
    default_observing_conditions,
    phase_amplitude_from_seeing,
    r0_from_seeing_arcsec,
    theta0_rad_from_arcsec,
)
from .data_sources import EsoAsmSnapshot
