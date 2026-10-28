"""Memoryless NumPy spatial backend for deformable mirrors.

This module owns only native actuator placement, influence-function sampling,
and the linear command-to-OPD map.  Repository policy such as stroke clipping,
dead or stuck actuators, gain, leak, and latency belongs to higher layers.

Commands accepted here are positive OPD-equivalent amplitudes in metres.  A
positive command therefore produces a positive multiple of its influence map;
no reflective-surface factor and no piston removal are applied in this native
array boundary.
"""

from __future__ import annotations

import math
from numbers import Integral, Real

import numpy as np

from ...core.hashing import component_config_hash


__all__ = (
    "NativeDmError",
    "NativeDmBackend",
    "VALID_INFLUENCE_MODELS",
    "square_grid_actuator_layout",
    "square_grid_actuator_centers",
    "actuator_centers_on_pupil",
    "gaussian_influence_functions",
    "build_influence_functions",
    "synthesize_opd",
)


_BACKEND_NAME = "native"
_MIN_ACTUATORS_ACROSS = 2
VALID_INFLUENCE_MODELS = frozenset(
    {"gaussian", "compact_gaussian", "pyramid_like"}
)


class NativeDmError(ValueError):
    """Raised when native DM spatial inputs are inconsistent."""


class NativeDmBackend:
    """Immutable array-only linear DM synthesizer.

    Parameters
    ----------
    influence_functions:
        Finite dimensionless maps with shape ``(n_actuators, ny, nx)``.  The
        caller fixes their ordering.  Canonical synthetic construction uses
        :func:`build_influence_functions`, whose maps are peak-normalized and
        zero outside the pupil.

    Notes
    -----
    The object has no command history.  Every call is exactly the linear sum
    ``sum(commands_opd_m[i] * influence_functions[i])``.
    """

    def __init__(self, influence_functions: np.ndarray) -> None:
        influences = _validated_influence_stack(influence_functions)
        self._influence_functions = _readonly_array(influences, dtype=float)
        self._config_hash = component_config_hash(
            "native.dm_spatial_backend",
            {
                "influence_functions": self._influence_functions,
                "command_unit": "m_opd_equivalent",
                "output_unit": "m_opd",
                "synthesis": "ordered_linear_sum_no_piston_removal",
            },
        )

    @property
    def backend_name(self) -> str:
        return _BACKEND_NAME

    @property
    def config_hash(self) -> str:
        return self._config_hash

    @property
    def n_actuators(self) -> int:
        return int(self._influence_functions.shape[0])

    @property
    def output_shape(self) -> tuple[int, int]:
        return (
            int(self._influence_functions.shape[1]),
            int(self._influence_functions.shape[2]),
        )

    def influence_functions(self) -> np.ndarray:
        """Return a defensive immutable copy of the ordered influence maps."""

        return _readonly_array(self._influence_functions, dtype=float)

    def opd_from_commands(self, commands_opd_m: np.ndarray) -> np.ndarray:
        """Return the raw positive correction OPD in metres.

        This method deliberately performs no clipping, actuator fault policy,
        piston removal, reflective factor-of-two conversion, or temporal
        filtering.
        """

        return synthesize_opd(commands_opd_m, self._influence_functions)


def square_grid_actuator_layout(
    telescope_diameter_m: float,
    n_actuators_across: int,
    *,
    include_edge_actuators: bool = True,
    actuator_margin_fraction: float = 0.0,
) -> tuple[np.ndarray, float, np.ndarray]:
    """Return retained square-grid centres, pitch, and nominal grid indices.

    Actuator order is the frozen repository convention: x/column is the outer
    loop and y/row is the inner loop.  ``grid_indices_rc`` stores the original
    ``(row, column)`` indices in the unfiltered nominal square grid, so pupil or
    guard-actuator filtering cannot renumber physical actuator identities.
    """

    diameter_m = _positive_float(
        telescope_diameter_m,
        label="telescope_diameter_m",
    )
    count = _integer(
        n_actuators_across,
        label="n_actuators_across",
        minimum=_MIN_ACTUATORS_ACROSS,
    )
    include_edge = _boolean(
        include_edge_actuators,
        label="include_edge_actuators",
    )
    margin_fraction = _nonnegative_float(
        actuator_margin_fraction,
        label="actuator_margin_fraction",
    )

    radius_m = 0.5 * diameter_m
    if include_edge:
        coordinates = np.linspace(-radius_m, radius_m, count)
    else:
        provisional_pitch_m = diameter_m / float(count)
        coordinates = np.linspace(
            -radius_m + 0.5 * provisional_pitch_m,
            radius_m - 0.5 * provisional_pitch_m,
            count,
        )
    pitch_m = float(abs(coordinates[1] - coordinates[0]))
    retain_radius_m = radius_m * (1.0 + margin_fraction)

    centers: list[tuple[float, float]] = []
    grid_indices_rc: list[tuple[int, int]] = []
    for column_index, x_center_m in enumerate(coordinates):
        for row_index, y_center_m in enumerate(coordinates):
            if x_center_m**2 + y_center_m**2 <= retain_radius_m**2:
                centers.append((float(x_center_m), float(y_center_m)))
                grid_indices_rc.append((row_index, column_index))

    if not centers:
        raise NativeDmError("No actuators were retained inside the configured pupil margin.")
    return (
        _readonly_array(np.asarray(centers, dtype=float), dtype=float),
        pitch_m,
        _readonly_array(np.asarray(grid_indices_rc, dtype=np.int64), dtype=np.int64),
    )


def square_grid_actuator_centers(
    telescope_diameter_m: float,
    n_actuators_across: int,
    *,
    include_edge_actuators: bool = True,
    actuator_margin_fraction: float = 0.0,
) -> tuple[np.ndarray, float]:
    """Return frozen-order retained square-grid centres and actuator pitch."""

    centers_m, pitch_m, _ = square_grid_actuator_layout(
        telescope_diameter_m,
        n_actuators_across,
        include_edge_actuators=include_edge_actuators,
        actuator_margin_fraction=actuator_margin_fraction,
    )
    return centers_m, pitch_m


# Compatibility spelling used by the historical synthetic DM module.  This is
# an identity alias, not a second placement implementation.
actuator_centers_on_pupil = square_grid_actuator_centers


def gaussian_influence_functions(
    x_m: np.ndarray,
    y_m: np.ndarray,
    pupil_mask: np.ndarray,
    actuator_centers_m: np.ndarray,
    actuator_pitch_m: float,
    *,
    coupling_width_pitch: float = 0.35,
    normalize_peak: bool = True,
) -> np.ndarray:
    """Sample Gaussian influences using the frozen low-level arithmetic.

    This helper retains the exact arithmetic ordering of the former
    ``ao_closed_loop`` public helper, including its optional unnormalized
    form.  Unlike that compatibility surface, native arrays are finite and
    use zero outside ``pupil_mask``.
    """

    x, y, pupil, centers, pitch_m, coupling, normalize = _validated_builder_inputs(
        x_m,
        y_m,
        pupil_mask,
        actuator_centers_m,
        actuator_pitch_m,
        coupling_width_pitch,
        normalize_peak,
    )
    sigma_m = coupling * pitch_m
    influences: list[np.ndarray] = []
    for x_center_m, y_center_m in centers:
        influence = np.exp(
            -(
                (x - float(x_center_m)) ** 2
                + (y - float(y_center_m)) ** 2
            )
            / (2.0 * sigma_m**2)
        )
        influence = _mask_and_optionally_normalize(
            influence,
            pupil,
            normalize_peak=normalize,
        )
        influences.append(influence)
    return _readonly_array(np.asarray(influences, dtype=float), dtype=float)


def build_influence_functions(
    x_m: np.ndarray,
    y_m: np.ndarray,
    pupil_mask: np.ndarray,
    actuator_centers_m: np.ndarray,
    actuator_pitch_m: float,
    *,
    influence_model: str = "gaussian",
    coupling_width_pitch: float = 0.35,
    normalize_peak: bool = True,
) -> np.ndarray:
    """Build Gaussian, compact-Gaussian, or pyramid-like influence maps.

    The radial arithmetic and sampled-pupil peak normalization reproduce the
    historical synthetic ``dm_model`` implementation.  Canonical construction
    leaves ``normalize_peak=True``.  Every returned value is finite, and pixels
    outside the pupil are exactly zero.
    """

    if not isinstance(influence_model, str) or influence_model not in VALID_INFLUENCE_MODELS:
        raise NativeDmError(
            f"influence_model={influence_model!r}; expected one of "
            f"{sorted(VALID_INFLUENCE_MODELS)}."
        )
    x, y, pupil, centers, pitch_m, coupling, normalize = _validated_builder_inputs(
        x_m,
        y_m,
        pupil_mask,
        actuator_centers_m,
        actuator_pitch_m,
        coupling_width_pitch,
        normalize_peak,
    )
    sigma_m = coupling * pitch_m
    influences: list[np.ndarray] = []
    for center_m in centers:
        dx_m = x - float(center_m[0])
        dy_m = y - float(center_m[1])
        radius_m = np.sqrt(dx_m**2 + dy_m**2)
        if influence_model == "gaussian":
            influence = np.exp(-(radius_m**2) / (2.0 * sigma_m**2))
        elif influence_model == "compact_gaussian":
            cutoff_m = 3.0 * sigma_m
            influence = np.exp(-(radius_m**2) / (2.0 * sigma_m**2))
            influence = np.where(radius_m <= cutoff_m, influence, 0.0)
        else:
            support_m = 2.0 * sigma_m
            influence = np.maximum(1.0 - radius_m / support_m, 0.0)
        influences.append(
            _mask_and_optionally_normalize(
                influence,
                pupil,
                normalize_peak=normalize,
            )
        )
    return _readonly_array(np.asarray(influences, dtype=float), dtype=float)


def synthesize_opd(
    commands_opd_m: np.ndarray,
    influence_functions: np.ndarray,
) -> np.ndarray:
    """Linearly synthesize a finite raw correction-OPD array in metres."""

    influences = _validated_influence_stack(influence_functions)
    commands = _real_numeric_array(commands_opd_m, label="commands_opd_m")
    expected_shape = (int(influences.shape[0]),)
    if commands.shape != expected_shape:
        raise NativeDmError(
            f"commands_opd_m shape {commands.shape} != {expected_shape}."
        )
    if not np.all(np.isfinite(commands)):
        raise NativeDmError("commands_opd_m must contain only finite values.")

    correction_opd_m = np.sum(
        commands[:, None, None] * influences,
        axis=0,
    )
    if not np.all(np.isfinite(correction_opd_m)):
        raise NativeDmError("Synthesized correction OPD contains non-finite values.")
    return _readonly_array(correction_opd_m, dtype=float)


def _validated_builder_inputs(
    x_m: np.ndarray,
    y_m: np.ndarray,
    pupil_mask: np.ndarray,
    actuator_centers_m: np.ndarray,
    actuator_pitch_m: float,
    coupling_width_pitch: float,
    normalize_peak: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float, float, bool]:
    x = _real_numeric_array(x_m, label="x_m")
    y = _real_numeric_array(y_m, label="y_m")
    centers = _real_numeric_array(
        actuator_centers_m,
        label="actuator_centers_m",
    )
    pupil = np.asarray(pupil_mask)
    if x.ndim != 2 or y.shape != x.shape:
        raise NativeDmError("x_m and y_m must be 2-D arrays with identical shapes.")
    if pupil.dtype.kind != "b" or pupil.shape != x.shape:
        raise NativeDmError(
            "pupil_mask must be a boolean array matching the coordinate-grid shape."
        )
    if not np.any(pupil):
        raise NativeDmError("pupil_mask must retain at least one sample.")
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        raise NativeDmError("x_m and y_m must contain only finite values.")
    if centers.ndim != 2 or centers.shape[1:] != (2,) or centers.shape[0] < 1:
        raise NativeDmError(
            "actuator_centers_m must have shape (n_actuators, 2) with n_actuators >= 1."
        )
    if not np.all(np.isfinite(centers)):
        raise NativeDmError("actuator_centers_m must contain only finite values.")
    pitch_m = _positive_float(actuator_pitch_m, label="actuator_pitch_m")
    coupling = _positive_float(
        coupling_width_pitch,
        label="coupling_width_pitch",
    )
    normalize = _boolean(normalize_peak, label="normalize_peak")
    return x, y, pupil, centers, pitch_m, coupling, normalize


def _mask_and_optionally_normalize(
    influence: np.ndarray,
    pupil_mask: np.ndarray,
    *,
    normalize_peak: bool,
) -> np.ndarray:
    masked = np.where(pupil_mask, influence, 0.0)
    if normalize_peak:
        peak = float(np.max(masked[pupil_mask]))
        if not math.isfinite(peak) or peak <= 0.0:
            raise NativeDmError(
                "Influence function has no finite positive sample inside pupil_mask."
            )
        masked = masked / peak
        # Preserve the canonical finite-array boundary after division.
        masked = np.where(pupil_mask, masked, 0.0)
    if not np.all(np.isfinite(masked)):
        raise NativeDmError("Influence functions must contain only finite values.")
    return masked


def _validated_influence_stack(values: object) -> np.ndarray:
    influences = _real_numeric_array(values, label="influence_functions")
    if (
        influences.ndim != 3
        or influences.shape[0] < 1
        or influences.shape[1] < 1
        or influences.shape[2] < 1
    ):
        raise NativeDmError(
            "influence_functions must have shape (n_actuators, ny, nx) "
            "with every dimension positive."
        )
    if not np.all(np.isfinite(influences)):
        raise NativeDmError("influence_functions must contain only finite values.")
    return influences


def _real_numeric_array(values: object, *, label: str) -> np.ndarray:
    try:
        raw = np.asarray(values)
    except (TypeError, ValueError) as exc:
        raise NativeDmError(f"{label} must be a real numeric array.") from exc
    if np.issubdtype(raw.dtype, np.bool_) or not np.issubdtype(
        raw.dtype,
        np.number,
    ) or np.issubdtype(raw.dtype, np.complexfloating):
        raise NativeDmError(f"{label} must be a real numeric array.")
    try:
        return np.asarray(raw, dtype=float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise NativeDmError(f"{label} must be a real numeric array.") from exc


def _readonly_array(values: object, *, dtype: object) -> np.ndarray:
    contiguous = np.ascontiguousarray(np.array(values, dtype=dtype, copy=True))
    immutable = np.frombuffer(contiguous.tobytes(order="C"), dtype=contiguous.dtype)
    return immutable.reshape(contiguous.shape)


def _integer(value: object, *, label: str, minimum: int) -> int:
    if not isinstance(value, Integral) or isinstance(value, (bool, np.bool_)):
        raise NativeDmError(f"{label} must be an integer >= {minimum}.")
    result = int(value)
    if result < minimum:
        raise NativeDmError(f"{label} must be >= {minimum}; got {result}.")
    return result


def _finite_float(value: object, *, label: str) -> float:
    if not isinstance(value, Real) or isinstance(value, (bool, np.bool_)):
        raise NativeDmError(f"{label} must be a finite real scalar.")
    result = float(value)
    if not math.isfinite(result):
        raise NativeDmError(f"{label} must be a finite real scalar.")
    return result


def _positive_float(value: object, *, label: str) -> float:
    result = _finite_float(value, label=label)
    if result <= 0.0:
        raise NativeDmError(f"{label} must be positive; got {result!r}.")
    return result


def _nonnegative_float(value: object, *, label: str) -> float:
    result = _finite_float(value, label=label)
    if result < 0.0:
        raise NativeDmError(f"{label} must be non-negative; got {result!r}.")
    return result


def _boolean(value: object, *, label: str) -> bool:
    if not isinstance(value, (bool, np.bool_)):
        raise NativeDmError(f"{label} must be a bool.")
    return bool(value)
