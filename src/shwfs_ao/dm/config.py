"""Canonical deformable-mirror configuration and actuator identities.

The configuration keeps the installed user-facing nanometre fields frozen.
The repository model converts those values once to OPD-equivalent metres
before command validation or backend synthesis.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Integral, Real

import numpy as np

from ..core.hashing import component_config_hash
from ..core.provenance import ALLOWED_SOURCE_CLASSES, Provenance


__all__ = (
    "DEFAULT_ACTUATOR_MARGIN_FRACTION",
    "DEFAULT_DM_SOURCE_CLASS",
    "DEFAULT_DM_SOURCE_NOTE",
    "MIN_ACTUATORS_ACROSS",
    "NM_TO_M",
    "VALID_INFLUENCE_MODELS",
    "DMModelError",
    "DMConfigError",
    "DMConfig",
    "DmConfig",
    "actuator_id",
    "actuator_ids_from_grid_indices",
)


DEFAULT_DM_SOURCE_CLASS = "synthetic_literature_inspired"
DEFAULT_DM_SOURCE_NOTE = (
    "Synthetic Gaussian DM influence model motivated by published influence-function "
    "modelling examples such as Berdeu arXiv:2306.10803; not measured calibration data."
)
VALID_INFLUENCE_MODELS = frozenset(
    {"gaussian", "compact_gaussian", "pyramid_like"}
)
NM_TO_M = 1.0e-9
DEFAULT_ACTUATOR_MARGIN_FRACTION = 0.0
MIN_ACTUATORS_ACROSS = 2


class DMModelError(ValueError):
    """Historical deformable-mirror configuration/model error identity."""


# Modern domain-specific spelling; the installed legacy name retains the
# AO-REF-000 class identity and ``__name__`` (as detector extraction does).
DMConfigError = DMModelError


@dataclass(frozen=True)
class DMConfig:
    """Frozen repository DM configuration with compatibility field order.

    ``stroke_limit_nm`` and ``stuck_command_nm`` are user-facing
    OPD-equivalent nanometres.  They are not mirror-surface displacement.
    Canonical command vectors and synthesis results use metres.
    """

    __hash_schema_id__ = "shwfs_ao.dm.DMConfig.v1"

    # AO-REF-000 freezes these twelve fields, their order, and defaults.
    telescope_diameter_m: float = 2.0
    n_actuators_across: int = 11
    influence_model: str = "gaussian"
    coupling_width_pitch: float = 0.35
    stroke_limit_nm: float = 800.0
    include_edge_actuators: bool = True
    actuator_margin_fraction: float = DEFAULT_ACTUATOR_MARGIN_FRACTION
    dead_actuator_indices: tuple[int, ...] = ()
    stuck_actuator_indices: tuple[int, ...] = ()
    stuck_command_nm: float = 0.0
    source_class: str = DEFAULT_DM_SOURCE_CLASS
    source_note: str = DEFAULT_DM_SOURCE_NOTE

    def __post_init__(self) -> None:
        diameter = _positive_float(
            self.telescope_diameter_m,
            label="telescope_diameter_m",
        )
        count = _integer(
            self.n_actuators_across,
            label="n_actuators_across",
        )
        if count < MIN_ACTUATORS_ACROSS:
            raise DMConfigError(
                f"n_actuators_across must be >= {MIN_ACTUATORS_ACROSS}."
            )
        if self.influence_model not in VALID_INFLUENCE_MODELS:
            raise DMConfigError(
                f"influence_model={self.influence_model!r}; expected one of "
                f"{sorted(VALID_INFLUENCE_MODELS)}."
            )
        coupling = _positive_float(
            self.coupling_width_pitch,
            label="coupling_width_pitch",
        )
        stroke = _positive_float(self.stroke_limit_nm, label="stroke_limit_nm")
        if stroke * NM_TO_M <= 0.0:
            raise DMConfigError(
                "stroke_limit_nm is too small to represent in canonical "
                "OPD-equivalent metres."
            )
        if not isinstance(self.include_edge_actuators, (bool, np.bool_)):
            raise DMConfigError("include_edge_actuators must be a boolean.")
        margin = _nonnegative_float(
            self.actuator_margin_fraction,
            label="actuator_margin_fraction",
        )
        dead = _indices(self.dead_actuator_indices, label="dead_actuator_indices")
        stuck = _indices(
            self.stuck_actuator_indices,
            label="stuck_actuator_indices",
        )
        stuck_command = _finite_float(
            self.stuck_command_nm,
            label="stuck_command_nm",
        )
        provenance = _dm_provenance(self.source_class, self.source_note)

        object.__setattr__(self, "telescope_diameter_m", diameter)
        object.__setattr__(self, "n_actuators_across", count)
        object.__setattr__(self, "coupling_width_pitch", coupling)
        object.__setattr__(self, "stroke_limit_nm", stroke)
        object.__setattr__(
            self,
            "include_edge_actuators",
            bool(self.include_edge_actuators),
        )
        object.__setattr__(self, "actuator_margin_fraction", margin)
        object.__setattr__(self, "dead_actuator_indices", dead)
        object.__setattr__(self, "stuck_actuator_indices", stuck)
        object.__setattr__(self, "stuck_command_nm", stuck_command)
        object.__setattr__(self, "source_class", provenance.source_class)
        object.__setattr__(self, "source_note", provenance.source_note)

    @property
    def provenance(self) -> Provenance:
        return _dm_provenance(self.source_class, self.source_note)

    @property
    def stroke_limit_opd_m(self) -> float:
        return self.stroke_limit_nm * NM_TO_M

    @property
    def stuck_command_opd_m(self) -> float:
        return self.stuck_command_nm * NM_TO_M

    @property
    def config_hash(self) -> str:
        return component_config_hash("deformable_mirror_config", self)


# Modern spelling; the installed all-capital name remains identical by object.
DmConfig = DMConfig


def actuator_id(row: int, column: int) -> str:
    """Return a stable actuator ID from nominal physical grid indices."""

    row_index = _nonnegative_integer(row, label="row")
    column_index = _nonnegative_integer(column, label="column")
    return f"actuator-r{row_index:04d}-c{column_index:04d}"


def actuator_ids_from_grid_indices(grid_indices_rc: np.ndarray) -> tuple[str, ...]:
    """Build ordered IDs from an ``(n, 2)`` row/column index array."""

    raw = np.asarray(grid_indices_rc)
    if raw.ndim != 2 or raw.shape[1:] != (2,) or raw.shape[0] == 0:
        raise DMConfigError(
            "grid_indices_rc must have non-empty shape (n_actuators, 2)."
        )
    identifiers = tuple(
        actuator_id(
            _nonnegative_integer(value[0], label=f"grid_indices_rc[{index}, 0]"),
            _nonnegative_integer(value[1], label=f"grid_indices_rc[{index}, 1]"),
        )
        for index, value in enumerate(raw)
    )
    if len(identifiers) != len(set(identifiers)):
        raise DMConfigError("grid_indices_rc produces duplicate actuator IDs.")
    return identifiers


def _indices(value: object, *, label: str) -> tuple[int, ...]:
    if not isinstance(value, tuple):
        raise DMConfigError(f"{label} must be a tuple of actuator indices.")
    result = tuple(
        _nonnegative_integer(item, label=f"{label}[{index}]")
        for index, item in enumerate(value)
    )
    if len(result) != len(set(result)):
        raise DMConfigError(f"{label} must not contain duplicate indices.")
    return result


def _integer(value: object, *, label: str) -> int:
    if not isinstance(value, Integral) or isinstance(value, (bool, np.bool_)):
        raise DMConfigError(f"{label} must be an integer.")
    return int(value)


def _nonnegative_integer(value: object, *, label: str) -> int:
    result = _integer(value, label=label)
    if result < 0:
        raise DMConfigError(f"{label} must be non-negative.")
    return result


def _finite_float(value: object, *, label: str) -> float:
    if not isinstance(value, Real) or isinstance(value, (bool, np.bool_)):
        raise DMConfigError(f"{label} must be finite.")
    result = float(value)
    if not math.isfinite(result):
        raise DMConfigError(f"{label} must be finite.")
    return result


def _positive_float(value: object, *, label: str) -> float:
    result = _finite_float(value, label=label)
    if result <= 0.0:
        raise DMConfigError(f"{label} must be positive; got {value!r}.")
    return result


def _nonnegative_float(value: object, *, label: str) -> float:
    result = _finite_float(value, label=label)
    if result < 0.0:
        raise DMConfigError(f"{label} must be non-negative; got {value!r}.")
    return result


def _dm_provenance(source_class: str, source_note: str) -> Provenance:
    try:
        return Provenance(source_class=source_class, source_note=source_note)
    except (TypeError, ValueError) as exc:
        if (
            not isinstance(source_class, str)
            or source_class not in ALLOWED_SOURCE_CLASSES
        ):
            raise DMConfigError(
                f"source_class={source_class!r} is not in the permitted taxonomy "
                f"{sorted(ALLOWED_SOURCE_CLASSES)}."
            ) from exc
        raise DMConfigError("source_note must be a non-empty string.") from exc
