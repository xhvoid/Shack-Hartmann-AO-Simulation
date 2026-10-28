"""HCIPy deformable-mirror synthesis behind the canonical ``DmBackend`` boundary.

The adapter owns every repository-facing convention; HCIPy provides only the
influence-function evaluation and the reflective-mirror surface arithmetic:

- Commands are OPD-equivalent influence amplitudes in metres (AO-REF-006).
  ``hcipy.DeformableMirror`` actuators are *reflective surface displacement*,
  so the adapter sends exactly half the requested OPD-equivalent amplitude
  and reads back ``DeformableMirror.opd`` — HCIPy's own single doubling from
  surface to optical path difference.  The factor of two is therefore applied
  exactly once, and a wavefront reflected by the same HCIPy mirror acquires
  exactly the OPD this backend reports.
- The backend is a memoryless spatial synthesizer: every call overwrites the
  HCIPy actuator state before reading the surface and flattens the mirror
  afterwards.  Stroke, dead/stuck actuators, clipping, saturation
  diagnostics, gain, leak, and latency remain repository policy in
  :class:`shwfs_ao.dm.model.DeformableMirror` and ``control``.
- Repository arrays are authoritative at the boundary: influence functions
  and correction OPD are plain finite ``numpy.ndarray`` objects in the
  repository ``(rows, columns)`` layout; HCIPy ``Field``/actuator arrays
  never cross the backend boundary.
- Actuator identity and ordering come from the repository square-grid layout
  shared with the native backend, so a native and an HCIPy mirror built from
  the same :class:`~shwfs_ao.dm.config.DMConfig` expose identical actuator
  IDs on a matched geometry.

Importing this module never imports HCIPy; repository-side validation runs
before the optional dependency is resolved, so invalid configuration raises
:class:`HcipyDmError` even on installations without HCIPy.
"""

from __future__ import annotations

import math
from numbers import Real
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np

from ...core.hashing import component_config_hash
from ...dm.config import DMConfig, actuator_ids_from_grid_indices
from ...dm.model import DeformableMirror
from . import hcipy_version, require_hcipy
from .conversion import (
    FLATTENING_ORDER,
    HcipyConversionError,
    hcipy_grid_from_coordinates,
)


_BACKEND_NAME = "hcipy"
_METADATA_SCHEMA_VERSION = 1
_COMMAND_UNIT = "m_opd_equivalent"

SURFACE_COMMAND_CONVENTION = "half_opd_command_to_surface_single_hcipy_doubling"
"""Reflective-mirror contract of this adapter.

``hcipy.DeformableMirror`` actuators are surface displacement in metres, and
its ``opd`` property applies the one reflective factor of two.  The adapter
therefore sets ``actuators = 0.5 * commands_opd_m`` and returns HCIPy's
doubled surface unchanged, so a positive OPD-equivalent command produces the
same positive correction OPD as the native backend.
"""

_SURFACE_FACTOR_ID = "hcipy-0.7-reflective-surface-half-command-v1"
"""Identifier of the surface/OPD factor construction (part of the hash)."""

_GAUSSIAN_MODEL_ID = "gaussian_pokes_native_sigma_no_cutoff-v1"
"""Identifier of the matched Gaussian influence construction."""

_COORDINATE_RTOL = 1.0e-12

__all__ = (
    "SURFACE_COMMAND_CONVENTION",
    "HcipyDmError",
    "HcipyDmBackend",
    "build_hcipy_gaussian_influence_basis",
    "build_hcipy_deformable_mirror",
)


class HcipyDmError(ValueError):
    """Raised when HCIPy DM construction inputs or commands are invalid."""


class HcipyDmBackend:
    """Memoryless ``DmBackend`` adapter around an HCIPy deformable mirror.

    Parameters
    ----------
    influence_function_basis:
        ``hcipy.ModeBasis`` of surface influence functions on a regular
        separated two-dimensional Cartesian grid.  Each mode is the surface
        response of one actuator per unit actuator amplitude; because the
        adapter halves OPD-equivalent commands into surface amplitudes and
        HCIPy doubles the surface back into OPD, each mode is numerically
        also the correction-OPD response per unit command.
    x_m, y_m:
        Repository coordinate meshgrids in metres.  They must reproduce the
        mode-basis grid; this pins the array orientation and physical units
        at the boundary.

    Notes
    -----
    The object has no command history: every synthesis call overwrites the
    HCIPy actuator vector and flattens the mirror after reading the surface,
    so identical commands always produce identical correction OPD.
    """

    def __init__(
        self,
        influence_function_basis: Any,
        x_m: np.ndarray,
        y_m: np.ndarray,
    ) -> None:
        x, y = _validated_coordinates(x_m, y_m)
        hcipy = require_hcipy()
        if not isinstance(influence_function_basis, hcipy.ModeBasis):
            raise HcipyDmError(
                "influence_function_basis must be an hcipy.ModeBasis."
            )
        try:
            grid = hcipy_grid_from_coordinates(x, y)
        except HcipyConversionError as exc:
            raise HcipyDmError(str(exc)) from exc
        basis_grid = influence_function_basis.grid
        if basis_grid is None:
            raise HcipyDmError(
                "influence_function_basis must carry the grid it was "
                "evaluated on."
            )
        _require_matching_grids(basis_grid, grid, hcipy=hcipy)
        rows, columns = (int(x.shape[0]), int(x.shape[1]))

        matrix = _dense_transformation_matrix(
            influence_function_basis.transformation_matrix
        )
        stack = _dense_influence_stack(matrix, rows=rows, columns=columns)
        self._influence_stack = _readonly_copy(stack, dtype=float)
        self._x_axis_m = _readonly_copy(x[0, :], dtype=float)
        self._y_axis_m = _readonly_copy(y[:, 0], dtype=float)
        self._output_shape = (rows, columns)
        self._hcipy_version = hcipy_version()
        # An HCIPy mirror keeps the basis it is given, and ModeBasis keeps a
        # dense matrix uncopied.  Synthesize from this private copy so later
        # edits to the caller's basis cannot drift from the hashed response.
        self._dm = hcipy.DeformableMirror(hcipy.ModeBasis(matrix, grid))
        self._dm.flatten()
        self._config_hash = component_config_hash(
            "hcipy.dm_spatial_backend",
            {
                "influence_functions": self._influence_stack,
                "x_axis_m": self._x_axis_m,
                "y_axis_m": self._y_axis_m,
                "flattening_order": FLATTENING_ORDER,
                "command_unit": _COMMAND_UNIT,
                "output_unit": "m_opd",
                "surface_command_convention": SURFACE_COMMAND_CONVENTION,
                "surface_factor": _SURFACE_FACTOR_ID,
            },
        )
        self._metadata: Mapping[str, Any] = MappingProxyType(
            {
                "schema_name": "shwfs_ao.hcipy_dm_backend",
                "schema_version": _METADATA_SCHEMA_VERSION,
                "backend_name": _BACKEND_NAME,
                "config_hash": self._config_hash,
                "hcipy_version": self._hcipy_version,
                "n_actuators": int(stack.shape[0]),
                "output_shape": self._output_shape,
                "command_unit": _COMMAND_UNIT,
                "output_unit": "m_opd",
                "surface_command_convention": SURFACE_COMMAND_CONVENTION,
                "surface_factor": _SURFACE_FACTOR_ID,
                "stateless_synthesis": True,
            }
        )

    @property
    def backend_name(self) -> str:
        return _BACKEND_NAME

    @property
    def config_hash(self) -> str:
        return self._config_hash

    @property
    def n_actuators(self) -> int:
        return int(self._influence_stack.shape[0])

    @property
    def output_shape(self) -> tuple[int, int]:
        return self._output_shape

    @property
    def metadata(self) -> Mapping[str, Any]:
        return self._metadata

    def influence_functions(self) -> np.ndarray:
        """Return the ordered correction-OPD maps per unit command.

        The result is a defensive immutable ``(n_actuators, rows, columns)``
        repository array, never an HCIPy ``Field`` or sparse matrix.
        """

        return _readonly_copy(self._influence_stack, dtype=float)

    def opd_from_commands(self, commands_opd_m: np.ndarray) -> np.ndarray:
        """Return the raw correction OPD in metres for OPD-equivalent commands.

        The commands are halved into HCIPy surface amplitudes; HCIPy's
        ``DeformableMirror.opd`` applies the single reflective factor of two
        back to optical path difference.  No clipping, fault policy, piston
        removal, or temporal filtering happens here.
        """

        commands = _validated_commands(
            commands_opd_m,
            n_actuators=self.n_actuators,
        )
        self._dm.actuators = 0.5 * commands
        raw_opd = np.asarray(self._dm.opd, dtype=float)
        self._dm.flatten()
        if raw_opd.shape != (self._output_shape[0] * self._output_shape[1],):
            raise HcipyDmError(
                "HCIPy returned a correction field of unexpected size "
                f"{raw_opd.shape}."
            )
        correction = raw_opd.reshape(self._output_shape)
        if not np.all(np.isfinite(correction)):
            raise HcipyDmError(
                "Synthesized correction OPD contains non-finite values."
            )
        return _readonly_copy(correction, dtype=float)


def build_hcipy_gaussian_influence_basis(
    x_m: np.ndarray,
    y_m: np.ndarray,
    actuator_centers_m: np.ndarray,
    actuator_pitch_m: float,
    *,
    coupling_width_pitch: float = 0.35,
    normalize_peak: bool = True,
    pupil_mask: np.ndarray | None = None,
) -> Any:
    """Build HCIPy Gaussian influence functions matched to the native model.

    Each actuator gets one ``exp(-r² / (2 σ²))`` poke with
    ``σ = coupling_width_pitch · actuator_pitch_m`` at its repository centre,
    in repository actuator order.  With ``normalize_peak=True`` (which
    requires ``pupil_mask``) every mode is scaled so its largest sampled
    in-pupil value is exactly one — the native construction's convention —
    so in-pupil samples match the native Gaussian influence functions.  The
    HCIPy surface deliberately keeps its analytic tail outside the pupil,
    where the native backend stores zeros.

    Repository-side inputs are validated before the optional dependency is
    resolved.  The returned ``hcipy.ModeBasis`` is a construction input for
    :class:`HcipyDmBackend`, not a repository result object.
    """

    x, y = _validated_coordinates(x_m, y_m)
    centers = _validated_centers(actuator_centers_m)
    pitch_m = _positive("actuator_pitch_m", actuator_pitch_m)
    coupling = _positive("coupling_width_pitch", coupling_width_pitch)
    normalize = _boolean("normalize_peak", normalize_peak)
    if normalize and pupil_mask is None:
        raise HcipyDmError(
            "normalize_peak=True requires pupil_mask to define the sampled "
            "in-pupil peak."
        )
    pupil = None
    if pupil_mask is not None:
        pupil = _validated_pupil(pupil_mask, expected_shape=x.shape)

    hcipy = require_hcipy()
    try:
        grid = hcipy_grid_from_coordinates(x, y)
    except HcipyConversionError as exc:
        raise HcipyDmError(str(exc)) from exc
    positions = hcipy.CartesianGrid(
        hcipy.UnstructuredCoords(
            (
                np.array(centers[:, 0], dtype=float, copy=True),
                np.array(centers[:, 1], dtype=float, copy=True),
            )
        )
    )
    basis = hcipy.make_gaussian_pokes(
        grid,
        positions,
        coupling * pitch_m,
        cutoff=None,
    )
    matrix = _dense_transformation_matrix(basis.transformation_matrix)
    if matrix.shape != (x.size, centers.shape[0]):
        raise HcipyDmError(
            f"HCIPy produced a transformation matrix of shape "
            f"{matrix.shape}; expected {(x.size, centers.shape[0])}."
        )
    if normalize and pupil is not None:
        in_pupil = pupil.ravel(order="C")
        for index in range(matrix.shape[1]):
            peak = float(np.max(matrix[in_pupil, index]))
            if not math.isfinite(peak) or peak <= 0.0:
                raise HcipyDmError(
                    "Influence function has no finite positive sample inside "
                    "pupil_mask."
                )
            matrix[:, index] /= peak
    return hcipy.ModeBasis(matrix, grid)


def build_hcipy_deformable_mirror(
    x_m: np.ndarray,
    y_m: np.ndarray,
    pupil_mask: np.ndarray,
    config: DMConfig | None = None,
) -> DeformableMirror:
    """Build the canonical repository model with the HCIPy spatial backend.

    The actuator layout, ordering, identifiers, pitch, and Gaussian coupling
    come from the same repository construction as
    :func:`shwfs_ao.dm.model.build_native_deformable_mirror`, so the native
    and HCIPy mirrors are directly comparable on a matched geometry.  Stroke,
    dead/stuck actuators, clipping, and saturation diagnostics remain owned
    by the returned canonical wrapper.
    """

    resolved_config = DMConfig() if config is None else config
    if not isinstance(resolved_config, DMConfig):
        raise HcipyDmError("config must be a DMConfig or None.")
    if resolved_config.influence_model != "gaussian":
        raise HcipyDmError(
            "The HCIPy DM backend represents only the 'gaussian' influence "
            f"model; got {resolved_config.influence_model!r}.  Use the "
            "native backend for the other frozen influence families."
        )
    x, y = _validated_coordinates(x_m, y_m)
    pupil = _validated_pupil(pupil_mask, expected_shape=x.shape)

    from ..native.dm import square_grid_actuator_layout

    centers, pitch_m, grid_indices_rc = square_grid_actuator_layout(
        resolved_config.telescope_diameter_m,
        resolved_config.n_actuators_across,
        include_edge_actuators=resolved_config.include_edge_actuators,
        actuator_margin_fraction=resolved_config.actuator_margin_fraction,
    )
    basis = build_hcipy_gaussian_influence_basis(
        x,
        y,
        centers,
        pitch_m,
        coupling_width_pitch=resolved_config.coupling_width_pitch,
        normalize_peak=True,
        pupil_mask=pupil,
    )
    return DeformableMirror(
        resolved_config,
        HcipyDmBackend(basis, x, y),
        actuator_ids=actuator_ids_from_grid_indices(grid_indices_rc),
        actuator_centers_m=centers,
        actuator_pitch_m=pitch_m,
        x_m=x,
        y_m=y,
        pupil_mask=pupil,
    )


def _require_matching_grids(basis_grid: Any, grid: Any, *, hcipy: Any) -> None:
    if not isinstance(basis_grid, hcipy.Grid):
        raise HcipyDmError(
            "influence_function_basis.grid must be an hcipy Cartesian grid."
        )
    if getattr(basis_grid, "ndim", None) != 2 or not (
        basis_grid.is_regular and basis_grid.is_separated
    ):
        raise HcipyDmError(
            "influence_function_basis.grid must be a regular separated "
            "two-dimensional Cartesian grid."
        )
    for axis_index, label in ((0, "x_m"), (1, "y_m")):
        basis_axis = np.asarray(
            basis_grid.separated_coords[axis_index],
            dtype=float,
        )
        expected_axis = np.asarray(
            grid.separated_coords[axis_index],
            dtype=float,
        )
        scale = max(float(np.max(np.abs(expected_axis))), 1.0)
        if basis_axis.shape != expected_axis.shape or not np.allclose(
            basis_axis,
            expected_axis,
            rtol=_COORDINATE_RTOL,
            atol=scale * _COORDINATE_RTOL,
        ):
            raise HcipyDmError(
                f"influence_function_basis.grid does not match the {label} "
                "coordinates."
            )


def _dense_transformation_matrix(raw: Any) -> np.ndarray:
    if hasattr(raw, "toarray"):
        matrix = np.asarray(raw.toarray(), dtype=float)
    else:
        matrix = np.array(raw, dtype=float, copy=True, subok=False)
    if matrix.ndim != 2 or matrix.shape[0] < 1 or matrix.shape[1] < 1:
        raise HcipyDmError(
            "influence_function_basis must contain at least one mode on a "
            "non-empty grid."
        )
    if not np.all(np.isfinite(matrix)):
        raise HcipyDmError(
            "influence functions must contain only finite values."
        )
    return matrix


def _dense_influence_stack(
    matrix: np.ndarray,
    *,
    rows: int,
    columns: int,
) -> np.ndarray:
    if matrix.shape[0] != rows * columns:
        raise HcipyDmError(
            f"influence_function_basis has {matrix.shape[0]} samples per "
            f"mode; the coordinate grid has {rows * columns}."
        )
    return np.ascontiguousarray(
        matrix.T.reshape(matrix.shape[1], rows, columns)
    )


def _validated_commands(values: object, *, n_actuators: int) -> np.ndarray:
    try:
        raw = np.asarray(values)
    except (TypeError, ValueError) as exc:
        raise HcipyDmError(
            "commands_opd_m must be a real numeric array."
        ) from exc
    if np.issubdtype(raw.dtype, np.bool_) or not np.issubdtype(
        raw.dtype,
        np.number,
    ) or np.issubdtype(raw.dtype, np.complexfloating):
        raise HcipyDmError("commands_opd_m must be a real numeric array.")
    commands = np.array(raw, dtype=float, copy=True)
    if commands.shape != (n_actuators,):
        raise HcipyDmError(
            f"commands_opd_m shape {commands.shape} != {(n_actuators,)}."
        )
    if not np.all(np.isfinite(commands)):
        raise HcipyDmError("commands_opd_m must contain only finite values.")
    return commands


def _validated_coordinates(
    x_m: object,
    y_m: object,
) -> tuple[np.ndarray, np.ndarray]:
    x = _real_numeric_array(x_m, label="x_m")
    y = _real_numeric_array(y_m, label="y_m")
    if x.ndim != 2 or y.shape != x.shape:
        raise HcipyDmError(
            "x_m and y_m must be 2-D arrays with identical shapes."
        )
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        raise HcipyDmError("x_m and y_m must contain only finite values.")
    return x, y


def _validated_centers(values: object) -> np.ndarray:
    centers = _real_numeric_array(values, label="actuator_centers_m")
    if centers.ndim != 2 or centers.shape[1:] != (2,) or centers.shape[0] < 1:
        raise HcipyDmError(
            "actuator_centers_m must have shape (n_actuators, 2) with "
            "n_actuators >= 1."
        )
    if not np.all(np.isfinite(centers)):
        raise HcipyDmError(
            "actuator_centers_m must contain only finite values."
        )
    return centers


def _validated_pupil(
    pupil_mask: object,
    *,
    expected_shape: tuple[int, ...],
) -> np.ndarray:
    raw = np.asarray(pupil_mask)
    if raw.dtype.kind != "b":
        raise HcipyDmError("pupil_mask must contain boolean values.")
    pupil = np.asarray(raw, dtype=bool)
    if pupil.shape != tuple(expected_shape):
        raise HcipyDmError(
            f"pupil_mask shape {pupil.shape} does not match the coordinate "
            f"grid shape {tuple(expected_shape)}."
        )
    if not np.any(pupil):
        raise HcipyDmError("pupil_mask must retain at least one sample.")
    return np.array(pupil, dtype=bool, copy=True)


def _real_numeric_array(values: object, *, label: str) -> np.ndarray:
    try:
        raw = np.asarray(values)
    except (TypeError, ValueError) as exc:
        raise HcipyDmError(f"{label} must be a real numeric array.") from exc
    if np.issubdtype(raw.dtype, np.bool_) or not np.issubdtype(
        raw.dtype,
        np.number,
    ) or np.issubdtype(raw.dtype, np.complexfloating):
        raise HcipyDmError(f"{label} must be a real numeric array.")
    try:
        return np.asarray(raw, dtype=float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise HcipyDmError(f"{label} must be a real numeric array.") from exc


def _positive(field_name: str, value: object) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise HcipyDmError(
            f"{field_name} must be a positive finite scalar; got {value!r}."
        )
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise HcipyDmError(
            f"{field_name} must be a positive finite scalar; got {value!r}."
        )
    return number


def _boolean(field_name: str, value: object) -> bool:
    if not isinstance(value, (bool, np.bool_)):
        raise HcipyDmError(f"{field_name} must be a bool.")
    return bool(value)


def _readonly_copy(values: np.ndarray, *, dtype: Any) -> np.ndarray:
    contiguous = np.ascontiguousarray(np.array(values, dtype=dtype, copy=True))
    result = np.frombuffer(contiguous.tobytes(order="C"), dtype=contiguous.dtype)
    return result.reshape(contiguous.shape)
