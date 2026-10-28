"""Repository-owned deformable-mirror policy and command synthesis.

The model in this module owns actuator identity, OPD-equivalent command units,
stroke clipping, fault policy, diagnostics, metadata, and provenance.  A
backend owns only an ordered stack of spatial influence functions and the
memoryless linear map from applied commands to raw correction OPD.

Canonical commands are positive correction amplitudes in metres of OPD.  A
closed loop therefore forms ``atmosphere_opd_m - dm_correction_opd_m``.  No
piston removal or reflective surface factor is applied here.
"""

from __future__ import annotations

from collections.abc import Mapping
import math
from numbers import Real
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

import numpy as np
import numpy.typing as npt

from ..core.hashing import component_config_hash, stable_hash
from ..core.provenance import Provenance
from ..core.types import (
    DmCommandVector,
    DmSynthesisResult,
    is_immutable_buffer_array,
)
from .config import DMConfig, actuator_ids_from_grid_indices


__all__ = (
    "COMMAND_UNIT",
    "DmBackend",
    "ScalableDmBackend",
    "DeformableMirrorError",
    "DeformableMirror",
    "build_native_deformable_mirror",
    "build_deformable_mirror",
)


COMMAND_UNIT = "m_opd_equivalent"
_COMMAND_CONVENTION = "positive_command_produces_positive_correction_opd"
_SYNTHESIS_CONVENTION = "raw_finite_opd_no_piston_removal"


@runtime_checkable
class DmBackend(Protocol):
    """Memoryless array-only deformable-mirror spatial backend."""

    def influence_functions(self) -> np.ndarray:
        ...

    def opd_from_commands(self, commands_opd_m: np.ndarray) -> np.ndarray:
        ...


@runtime_checkable
class ScalableDmBackend(Protocol):
    """Opt-in spatial operator that never needs a dense influence cube.

    A backend declaring ``spatial_operator_kind == "local_sparse"`` exposes its
    actuator count, output geometry, and immutable identity directly, plus a
    forward map, its adjoint, local influence access, and the actuators whose
    support has no illuminated sample.  :class:`DeformableMirror` then never
    calls ``influence_functions()`` to learn a shape or a hash; the dense cube
    remains available only through a size-guarded compatibility method.
    """

    @property
    def spatial_operator_kind(self) -> str:
        ...

    @property
    def config_hash(self) -> str:
        ...

    @property
    def n_actuators(self) -> int:
        ...

    @property
    def output_shape(self) -> tuple[int, int]:
        ...

    @property
    def zero_support_mask(self) -> np.ndarray:
        ...

    def opd_from_commands(self, commands_opd_m: np.ndarray) -> np.ndarray:
        ...

    def adjoint(self, opd_m: np.ndarray) -> np.ndarray:
        ...

    def local_influence(self, index: int) -> tuple[np.ndarray, np.ndarray]:
        ...

    def dense_influence_functions(self, *, max_bytes: int = ...) -> np.ndarray:
        ...


def _is_scalable_backend(backend: object) -> bool:
    return (
        getattr(backend, "spatial_operator_kind", None) == "local_sparse"
        and isinstance(backend, ScalableDmBackend)
    )


class DeformableMirrorError(ValueError):
    """Raised when canonical DM geometry, commands, or backend data are invalid."""


class DeformableMirror:
    """Canonical repository-level deformable-mirror model.

    Parameters
    ----------
    config:
        Frozen repository policy.  Its historical nanometre fields are
        converted to OPD-equivalent metres at this boundary.
    backend:
        Memoryless spatial synthesizer implementing :class:`DmBackend`.
    actuator_ids:
        Stable full-layout identifiers in the exact backend ordering.
    actuator_centers_m, actuator_pitch_m, x_m, y_m, pupil_mask:
        Optional sampled geometry metadata.  Native construction supplies all
        of it; alternate backends may omit unavailable coordinate details.

    Notes
    -----
    Fault precedence is deliberately explicit: stroke clipping is diagnosed
    first, dead actuators are then forced to zero, and stuck actuators are
    finally forced to their configured (itself clipped) command.  A stuck
    actuator therefore wins if an index appears in both fault sets.
    """

    def __init__(
        self,
        config: DMConfig,
        backend: DmBackend,
        *,
        actuator_ids: tuple[str, ...],
        actuator_centers_m: np.ndarray | None = None,
        actuator_pitch_m: float | None = None,
        x_m: np.ndarray | None = None,
        y_m: np.ndarray | None = None,
        pupil_mask: np.ndarray | None = None,
    ) -> None:
        if not isinstance(config, DMConfig):
            raise DeformableMirrorError("config must be a DMConfig.")
        if not isinstance(actuator_ids, tuple):
            raise DeformableMirrorError("actuator_ids must be a tuple of strings.")
        if not actuator_ids:
            raise DeformableMirrorError("actuator_ids must not be empty.")
        if any(not isinstance(value, str) or not value for value in actuator_ids):
            raise DeformableMirrorError(
                "actuator_ids must contain only non-empty strings."
            )
        if len(actuator_ids) != len(set(actuator_ids)):
            raise DeformableMirrorError("actuator_ids must not contain duplicates.")
        scalable = _is_scalable_backend(backend)
        if not scalable and not isinstance(backend, DmBackend):
            raise DeformableMirrorError(
                "backend must implement influence_functions() and "
                "opd_from_commands()."
            )

        influences: np.ndarray | None
        if scalable:
            # The scalable path learns count, shape and identity from the
            # operator itself and never materializes the influence cube.
            influences = None
            operator = backend
            count = int(operator.n_actuators)  # type: ignore[attr-defined]
            output_shape = tuple(
                int(value) for value in operator.output_shape  # type: ignore[attr-defined]
            )
            if count < 1 or len(output_shape) != 2 or min(output_shape) < 1:
                raise DeformableMirrorError(
                    "scalable DM operator must report positive count and shape."
                )
        else:
            influences = _backend_influence_functions(backend)
            count = int(influences.shape[0])
            output_shape = (int(influences.shape[1]), int(influences.shape[2]))
        if len(actuator_ids) != count:
            raise DeformableMirrorError(
                f"actuator_ids length {len(actuator_ids)} != backend actuator "
                f"count {count}."
            )

        centers = _optional_centers(actuator_centers_m, count=count)
        pitch = _optional_positive_float(
            actuator_pitch_m,
            label="actuator_pitch_m",
        )
        if centers is None and pitch is not None:
            raise DeformableMirrorError(
                "actuator_pitch_m requires actuator_centers_m."
            )
        x_grid, y_grid, pupil = _optional_sampled_geometry(
            x_m,
            y_m,
            pupil_mask,
            output_shape=(output_shape[0], output_shape[1]),
        )

        dead_mask = np.zeros(count, dtype=bool)
        stuck_mask = np.zeros(count, dtype=bool)
        for label, indices, destination in (
            ("dead_actuator_indices", config.dead_actuator_indices, dead_mask),
            ("stuck_actuator_indices", config.stuck_actuator_indices, stuck_mask),
        ):
            for index in indices:
                if index >= count:
                    raise DeformableMirrorError(
                        f"{label} contains index {index}, but the model has "
                        f"{count} actuators."
                    )
                destination[index] = True

        backend_identity = (
            f"{type(backend).__module__}.{type(backend).__qualname__}"
        )
        backend_name = _optional_backend_string(
            backend,
            "backend_name",
            fallback=backend_identity,
        )
        if influences is None:
            backend_config_hash = _optional_backend_string(
                backend, "config_hash", fallback=""
            )
        else:
            backend_config_hash = _optional_backend_string(
                backend,
                "config_hash",
                fallback=stable_hash(
                    influences,
                    namespace="dm_backend_influence_functions",
                ),
            )
        self._config = config
        self._backend = backend
        self._actuator_ids = actuator_ids
        self._actuator_centers_m = centers
        self._actuator_pitch_m = pitch
        self._x_m = x_grid
        self._y_m = y_grid
        self._pupil_mask = pupil
        self._output_shape = (output_shape[0], output_shape[1])
        self._influence_functions = (
            None if influences is None else _readonly_array(influences, dtype=float)
        )
        self._scalable = scalable
        self._dead_actuator_mask = _readonly_array(dead_mask, dtype=bool)
        self._stuck_actuator_mask = _readonly_array(stuck_mask, dtype=bool)
        controllable = ~(dead_mask | stuck_mask)
        self._controllable_actuator_ids = tuple(
            identifier
            for identifier, is_controllable in zip(
                actuator_ids,
                controllable,
                strict=True,
            )
            if is_controllable
        )
        self._backend_name = backend_name
        self._backend_config_hash = backend_config_hash

        identity_payload: dict[str, Any] = {
            "config": config,
            "sampled_x_m": x_grid,
            "sampled_y_m": y_grid,
            "pupil_mask": pupil,
            "actuator_ids": actuator_ids,
            "actuator_centers_m": centers,
            "actuator_pitch_m": pitch,
            "dead_actuator_mask": dead_mask,
            "stuck_actuator_mask": stuck_mask,
            "command_unit": COMMAND_UNIT,
            "command_convention": _COMMAND_CONVENTION,
            "synthesis_convention": _SYNTHESIS_CONVENTION,
            "backend_identity": backend_identity,
            "backend_name": backend_name,
            "backend_config_hash": backend_config_hash,
        }
        if influences is None:
            # The operator's own content hash binds ordered support indices,
            # weights, sampled geometry, basis version and zero-support
            # classification; no dense cube is reconstructed to hash it.
            zero_support = np.asarray(
                backend.zero_support_mask,  # type: ignore[attr-defined]
                dtype=np.bool_,
            )
            if zero_support.shape != (count,):
                raise DeformableMirrorError(
                    "zero_support_mask must have one entry per actuator."
                )
            identity_payload["spatial_operator_kind"] = "local_sparse"
            identity_payload["zero_illuminated_support"] = zero_support
            self._zero_support = _readonly_array(zero_support, dtype=bool)
            self._config_hash = component_config_hash(
                "deformable_mirror.scalable_operator", identity_payload
            )
        else:
            identity_payload["influence_functions"] = influences
            self._zero_support = _readonly_array(
                ~np.any(influences != 0.0, axis=(1, 2)), dtype=bool
            )
            self._config_hash = component_config_hash(
                "deformable_mirror", identity_payload
            )
        self._actuator_metadata = _build_actuator_metadata(
            actuator_ids,
            centers,
            dead_mask,
            stuck_mask,
        )
        provenance = config.provenance
        self._metadata = MappingProxyType(
            {
                "backend_name": backend_name,
                "backend_config_hash": backend_config_hash,
                "command_unit": COMMAND_UNIT,
                "command_convention": _COMMAND_CONVENTION,
                "synthesis_convention": _SYNTHESIS_CONVENTION,
                "stroke_limit_opd_m": config.stroke_limit_opd_m,
                "stuck_command_opd_m": config.stuck_command_opd_m,
                "source_class": provenance.source_class,
                "source_note": provenance.source_note,
                "actuator_ids": actuator_ids,
                "controllable_actuator_ids": self._controllable_actuator_ids,
                "actuators": self._actuator_metadata,
            }
        )

    @property
    def config(self) -> DMConfig:
        return self._config

    @property
    def config_hash(self) -> str:
        return self._config_hash

    @property
    def backend_name(self) -> str:
        return self._backend_name

    @property
    def backend_config_hash(self) -> str:
        return self._backend_config_hash

    @property
    def n_actuators(self) -> int:
        return len(self._actuator_ids)

    @property
    def output_shape(self) -> tuple[int, int]:
        return self._output_shape

    @property
    def is_scalable(self) -> bool:
        """True when a sparse local operator, not a dense stack, synthesizes."""

        return self._scalable

    @property
    def spatial_operator(self) -> ScalableDmBackend | None:
        """The scalable spatial operator, or ``None`` on the dense path."""

        return self._backend if self._scalable else None  # type: ignore[return-value]

    @property
    def zero_support_mask(self) -> np.ndarray:
        """True for actuators whose influence has no nonzero sampled value.

        Such an actuator stays in the full layout (its ID is physical) but has
        no geometric effect; it is a geometric exclusion, not a fault.
        """

        return self._zero_support

    @property
    def geometric_exclusion_ids(self) -> tuple[str, ...]:
        return tuple(
            identifier
            for identifier, excluded in zip(
                self._actuator_ids, self._zero_support, strict=True
            )
            if excluded
        )

    def adjoint_opd(self, opd_m: np.ndarray) -> np.ndarray:
        """Adjoint of the raw linear synthesis: commands from an OPD map."""

        values = np.asarray(opd_m, dtype=float)
        if values.shape != self._output_shape:
            raise DeformableMirrorError(
                f"opd_m shape {values.shape} != {self._output_shape}."
            )
        if self._scalable:
            return np.asarray(
                self._backend.adjoint(values),  # type: ignore[attr-defined]
                dtype=float,
            )
        assert self._influence_functions is not None
        masked = np.where(np.isfinite(values), values, 0.0)
        return np.tensordot(self._influence_functions, masked, axes=([1, 2], [0, 1]))

    @property
    def actuator_ids(self) -> tuple[str, ...]:
        return self._actuator_ids

    @property
    def controllable_actuator_ids(self) -> tuple[str, ...]:
        return self._controllable_actuator_ids

    @property
    def stroke_limit_opd_m(self) -> float:
        return self._config.stroke_limit_opd_m

    @property
    def stuck_command_opd_m(self) -> float:
        return self._config.stuck_command_opd_m

    @property
    def provenance(self) -> Provenance:
        return self._config.provenance

    @property
    def metadata(self) -> Mapping[str, Any]:
        return self._metadata

    @property
    def actuator_metadata(self) -> tuple[Mapping[str, Any], ...]:
        return self._actuator_metadata

    @property
    def influence_functions(self) -> np.ndarray:
        """Dense influence stack.

        On the scalable path this is a size-guarded compatibility view for
        small problems; it raises rather than silently allocating a large cube.
        """

        if self._influence_functions is None:
            try:
                dense = self._backend.dense_influence_functions()  # type: ignore[attr-defined]
            except ValueError as exc:
                raise DeformableMirrorError(str(exc)) from exc
            return _readonly_array(dense, dtype=float)
        return _readonly_array(self._influence_functions, dtype=float)

    @property
    def dead_actuator_mask(self) -> np.ndarray:
        return _readonly_array(self._dead_actuator_mask, dtype=bool)

    @property
    def stuck_actuator_mask(self) -> np.ndarray:
        return _readonly_array(self._stuck_actuator_mask, dtype=bool)

    @property
    def actuator_centers_m(self) -> np.ndarray | None:
        if self._actuator_centers_m is None:
            return None
        return _readonly_array(self._actuator_centers_m, dtype=float)

    @property
    def actuator_pitch_m(self) -> float | None:
        return self._actuator_pitch_m

    @property
    def x_m(self) -> np.ndarray | None:
        if self._x_m is None:
            return None
        return _readonly_array(self._x_m, dtype=float)

    @property
    def y_m(self) -> np.ndarray | None:
        if self._y_m is None:
            return None
        return _readonly_array(self._y_m, dtype=float)

    @property
    def pupil_mask(self) -> np.ndarray | None:
        if self._pupil_mask is None:
            return None
        return _readonly_array(self._pupil_mask, dtype=bool)

    def opd_from_commands(self, commands: DmCommandVector) -> DmSynthesisResult:
        """Apply repository command policy and synthesize raw correction OPD."""

        if not isinstance(commands, DmCommandVector):
            raise DeformableMirrorError("commands must be a DmCommandVector.")
        if commands.actuator_ids != self._actuator_ids:
            raise DeformableMirrorError(
                "commands.actuator_ids must exactly match the model's full "
                "actuator IDs and ordering."
            )
        if commands.command_unit != COMMAND_UNIT:
            raise DeformableMirrorError(
                f"commands.command_unit must be {COMMAND_UNIT!r}."
            )

        requested = np.array(commands.values_opd_m, dtype=float, copy=True)
        stroke = self._config.stroke_limit_opd_m
        saturated = np.abs(requested) > stroke
        applied = np.clip(requested, -stroke, stroke)
        applied[np.asarray(self._dead_actuator_mask)] = 0.0
        stuck_value = float(
            np.clip(self._config.stuck_command_opd_m, -stroke, stroke)
        )
        applied[np.asarray(self._stuck_actuator_mask)] = stuck_value

        backend_commands = _readonly_array(applied, dtype=float)
        try:
            raw_correction = self._backend.opd_from_commands(backend_commands)
        except Exception as exc:
            raise DeformableMirrorError(
                "DM backend failed to synthesize correction OPD."
            ) from exc
        correction = _backend_correction(
            raw_correction,
            expected_shape=self.output_shape,
        )

        saturated_ro = _readonly_array(saturated, dtype=bool)
        return DmSynthesisResult(
            correction_opd_m=correction,
            requested_commands_opd_m=_readonly_array(requested, dtype=float),
            applied_commands_opd_m=_readonly_array(applied, dtype=float),
            actuator_ids=self._actuator_ids,
            saturated_mask=saturated_ro,
            saturation_fraction=float(np.mean(saturated_ro)),
            command_unit=COMMAND_UNIT,
            config_hash=self._config_hash,
        )


def build_native_deformable_mirror(
    x_m: np.ndarray,
    y_m: np.ndarray,
    pupil_mask: np.ndarray,
    config: DMConfig | None = None,
) -> DeformableMirror:
    """Build the canonical model with the transparent NumPy backend."""

    from ..backends.native.dm import (
        NativeDmBackend,
        build_influence_functions,
        square_grid_actuator_layout,
    )

    resolved_config = DMConfig() if config is None else config
    if not isinstance(resolved_config, DMConfig):
        raise DeformableMirrorError("config must be a DMConfig or None.")
    centers, pitch, grid_indices_rc = square_grid_actuator_layout(
        resolved_config.telescope_diameter_m,
        resolved_config.n_actuators_across,
        include_edge_actuators=resolved_config.include_edge_actuators,
        actuator_margin_fraction=resolved_config.actuator_margin_fraction,
    )
    if resolved_config.influence_model == "linear_spline":
        from ..backends.native.dm_operator import LinearSplineDmOperator

        try:
            operator = LinearSplineDmOperator(x_m, y_m, pupil_mask, centers, pitch)
        except ValueError as exc:
            raise DeformableMirrorError(str(exc)) from exc
        return DeformableMirror(
            resolved_config,
            operator,
            actuator_ids=actuator_ids_from_grid_indices(grid_indices_rc),
            actuator_centers_m=centers,
            actuator_pitch_m=pitch,
            x_m=x_m,
            y_m=y_m,
            pupil_mask=pupil_mask,
        )
    influences = build_influence_functions(
        x_m,
        y_m,
        pupil_mask,
        centers,
        pitch,
        influence_model=resolved_config.influence_model,
        coupling_width_pitch=resolved_config.coupling_width_pitch,
        normalize_peak=True,
    )
    return DeformableMirror(
        resolved_config,
        NativeDmBackend(influences),
        actuator_ids=actuator_ids_from_grid_indices(grid_indices_rc),
        actuator_centers_m=centers,
        actuator_pitch_m=pitch,
        x_m=x_m,
        y_m=y_m,
        pupil_mask=pupil_mask,
    )


# Concise default spelling: this package's repository factory is native until
# an alternate optical backend is passed directly to ``DeformableMirror``.
build_deformable_mirror = build_native_deformable_mirror


def _backend_influence_functions(backend: DmBackend) -> np.ndarray:
    try:
        raw = backend.influence_functions()
    except Exception as exc:
        raise DeformableMirrorError(
            "DM backend failed to provide influence functions."
        ) from exc
    if not isinstance(raw, np.ndarray):
        raise DeformableMirrorError(
            "backend influence_functions() must return a numpy.ndarray."
        )
    if np.issubdtype(raw.dtype, np.bool_) or not np.issubdtype(
        raw.dtype,
        np.number,
    ) or np.issubdtype(raw.dtype, np.complexfloating):
        raise DeformableMirrorError(
            "backend influence functions must contain real numeric values."
        )
    influences = np.asarray(raw, dtype=float)
    if (
        influences.ndim != 3
        or influences.shape[0] < 1
        or influences.shape[1] < 1
        or influences.shape[2] < 1
    ):
        raise DeformableMirrorError(
            "backend influence functions must have positive shape "
            "(n_actuators, ny, nx)."
        )
    if not np.all(np.isfinite(influences)):
        raise DeformableMirrorError(
            "backend influence functions must contain only finite values."
        )
    return _readonly_array(influences, dtype=float)


def _backend_correction(
    raw: object,
    *,
    expected_shape: tuple[int, int],
) -> np.ndarray:
    if not isinstance(raw, np.ndarray):
        raise DeformableMirrorError(
            "backend opd_from_commands() must return a numpy.ndarray."
        )
    if np.issubdtype(raw.dtype, np.bool_) or not np.issubdtype(
        raw.dtype,
        np.number,
    ) or np.issubdtype(raw.dtype, np.complexfloating):
        raise DeformableMirrorError(
            "backend correction OPD must contain real numeric values."
        )
    correction = np.asarray(raw, dtype=float)
    if correction.shape != expected_shape:
        raise DeformableMirrorError(
            f"backend correction OPD shape {correction.shape} != "
            f"{expected_shape}."
        )
    if not np.all(np.isfinite(correction)):
        raise DeformableMirrorError(
            "backend correction OPD must contain only finite values."
        )
    return _readonly_array(correction, dtype=float)


def _optional_centers(
    values: np.ndarray | None,
    *,
    count: int,
) -> np.ndarray | None:
    if values is None:
        return None
    if not isinstance(values, np.ndarray):
        raise DeformableMirrorError("actuator_centers_m must be a numpy.ndarray.")
    if np.issubdtype(values.dtype, np.bool_) or not np.issubdtype(
        values.dtype,
        np.number,
    ) or np.issubdtype(values.dtype, np.complexfloating):
        raise DeformableMirrorError(
            "actuator_centers_m must contain real numeric values."
        )
    try:
        centers = np.asarray(values, dtype=float)
    except (TypeError, ValueError) as exc:
        raise DeformableMirrorError(
            "actuator_centers_m must contain real numeric values."
        ) from exc
    if centers.shape != (count, 2):
        raise DeformableMirrorError(
            f"actuator_centers_m shape {centers.shape} != {(count, 2)}."
        )
    if not np.all(np.isfinite(centers)):
        raise DeformableMirrorError(
            "actuator_centers_m must contain only finite values."
        )
    return _readonly_array(centers, dtype=float)


def _optional_sampled_geometry(
    x_m: np.ndarray | None,
    y_m: np.ndarray | None,
    pupil_mask: np.ndarray | None,
    *,
    output_shape: tuple[int, int],
) -> tuple[np.ndarray | None, np.ndarray | None, np.ndarray | None]:
    supplied = (x_m is not None, y_m is not None, pupil_mask is not None)
    if any(supplied) and not all(supplied):
        raise DeformableMirrorError(
            "x_m, y_m, and pupil_mask must be supplied together."
        )
    if not any(supplied):
        return None, None, None
    if not isinstance(x_m, np.ndarray) or not isinstance(y_m, np.ndarray):
        raise DeformableMirrorError("x_m and y_m must be numpy.ndarray objects.")
    for label, values in (("x_m", x_m), ("y_m", y_m)):
        if np.issubdtype(values.dtype, np.bool_) or not np.issubdtype(
            values.dtype,
            np.number,
        ) or np.issubdtype(values.dtype, np.complexfloating):
            raise DeformableMirrorError(
                f"{label} must contain real numeric values."
            )
    if not isinstance(pupil_mask, np.ndarray) or pupil_mask.dtype != np.dtype(bool):
        raise DeformableMirrorError(
            "pupil_mask must be a boolean numpy.ndarray."
        )
    try:
        x_grid = np.asarray(x_m, dtype=float)
        y_grid = np.asarray(y_m, dtype=float)
    except (TypeError, ValueError) as exc:
        raise DeformableMirrorError(
            "x_m and y_m must contain real numeric values."
        ) from exc
    if x_grid.shape != output_shape or y_grid.shape != output_shape:
        raise DeformableMirrorError(
            "x_m and y_m must match the backend output shape "
            f"{output_shape}."
        )
    if pupil_mask.shape != output_shape:
        raise DeformableMirrorError(
            f"pupil_mask shape {pupil_mask.shape} != {output_shape}."
        )
    if not np.any(pupil_mask):
        raise DeformableMirrorError("pupil_mask must retain at least one sample.")
    if not np.all(np.isfinite(x_grid)) or not np.all(np.isfinite(y_grid)):
        raise DeformableMirrorError("x_m and y_m must contain only finite values.")
    return (
        _readonly_array(x_grid, dtype=float),
        _readonly_array(y_grid, dtype=float),
        _readonly_array(pupil_mask, dtype=bool),
    )


def _optional_positive_float(value: object, *, label: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, Real) or isinstance(value, (bool, np.bool_)):
        raise DeformableMirrorError(f"{label} must be a positive finite scalar.")
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise DeformableMirrorError(f"{label} must be a positive finite scalar.")
    return result


def _optional_backend_string(
    backend: DmBackend,
    attribute: str,
    *,
    fallback: str,
) -> str:
    try:
        value = getattr(backend, attribute, fallback)
    except Exception as exc:
        raise DeformableMirrorError(
            f"backend {attribute} could not be read."
        ) from exc
    if not isinstance(value, str) or not value.strip():
        raise DeformableMirrorError(
            f"backend {attribute}, when provided, must be a non-empty string."
        )
    return value


def _build_actuator_metadata(
    actuator_ids: tuple[str, ...],
    centers_m: np.ndarray | None,
    dead_mask: np.ndarray,
    stuck_mask: np.ndarray,
) -> tuple[Mapping[str, Any], ...]:
    result: list[Mapping[str, Any]] = []
    for index, identifier in enumerate(actuator_ids):
        is_dead = bool(dead_mask[index])
        is_stuck = bool(stuck_mask[index])
        center = None
        if centers_m is not None:
            center = (float(centers_m[index, 0]), float(centers_m[index, 1]))
        result.append(
            MappingProxyType(
                {
                    "index": index,
                    "actuator_id": identifier,
                    "center_xy_m": center,
                    "dead": is_dead,
                    "stuck": is_stuck,
                    "controllable": not (is_dead or is_stuck),
                }
            )
        )
    return tuple(result)


def _readonly_array(values: npt.ArrayLike, *, dtype: npt.DTypeLike) -> np.ndarray:
    if is_immutable_buffer_array(values, dtype=dtype):
        # Already immutable: sharing it avoids a second dense influence cube.
        return values
    contiguous = np.ascontiguousarray(np.array(values, dtype=dtype, copy=True))
    immutable = np.frombuffer(contiguous.tobytes(order="C"), dtype=contiguous.dtype)
    return immutable.reshape(contiguous.shape)
