"""HCIPy von Kármán atmospheric layers behind the canonical ``AtmosphereModel``.

The adapter owns every repository-facing convention; HCIPy provides only the
spectral screen synthesis and frozen-flow translation:

- ``opd_at(time_s)`` returns piston-removed optical path difference in metres
  on the configured pupil, NaN outside it, at absolute non-decreasing time.
- ``r0_m`` is the Fried parameter specified at ``r0_reference_wavelength_m``
  and is converted once to the wavelength-independent integrated ``Cn²``.
- ``phase_conversion_reference_wavelength_m`` is only the wavelength at which
  the HCIPy phase screen is queried and converted once as
  ``opd_m = phase_rad · λ / (2π)``.  HCIPy layers are achromatic
  (``phase_for(λ) = screen / λ``), so holding the physical atmosphere fixed
  the returned OPD does not change when only this wavelength changes.
- ``wind_m_per_s`` means the same thing as in the native backend: the frozen
  phase pattern is advected *with* the wind, translating by ``+wind · t``
  metres in repository ``(x, y)`` coordinates.  HCIPy 0.7 primitives do not
  share one convention — ``InfiniteAtmosphericLayer`` moves the pattern along
  ``-velocity`` while ``FiniteAtmosphericLayer``'s spectral shift applies its
  velocity components to swapped field axes — so the adapter normalizes the
  velocity passed to each kind and the wind-direction tests pin the result.
- ``reset(realization_index)`` rebuilds all HCIPy layer state from generators
  derived from the immutable root seed plus the realization index, so
  replaying the same time vector is exact within one HCIPy environment.

Importing this module never imports HCIPy; only constructing (or resetting)
a model resolves the optional dependency.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from numbers import Integral, Real
from types import MappingProxyType
from typing import Any, Literal, Mapping

import numpy as np

from ...core.geometry import PupilGeometry
from ...core.hashing import component_config_hash, stable_hash
from ...core.protocols import RandomStreams
from ...core.random import NamedRandomStreams
from ...core.wavefront import phase_to_opd, remove_piston
from . import hcipy_version, require_hcipy
from .conversion import (
    HcipyConversionError,
    hcipy_grid_from_geometry,
    masked_array_from_field,
)


_BACKEND_NAME = "hcipy"
_METADATA_SCHEMA_VERSION = 1
_KOLMOGOROV_EXPONENT = 5.0 / 3.0

WIND_CONVENTION = "pattern_advects_with_positive_wind"
"""Frozen-flow contract shared with the native backend.

At time ``t`` the phase pattern has translated by ``+wind_m_per_s · t`` metres
in repository ``(x, y)`` coordinates.
"""

_WIND_NORMALIZATION_ID = "hcipy-0.7-layer-velocity-normalization-v1"
"""Identifier of the per-kind velocity mapping that enforces WIND_CONVENTION."""

_PHASE_CONVERSION_ID = "single-query-at-conversion-wavelength-v1"
"""Identifier of the phase→OPD construction (one query, one conversion)."""

_UNBOUNDED_OUTER_SCALE_MESSAGE = (
    "outer_scale_m=None or positive infinity (unbounded) is not constructible "
    "with the HCIPy backend: its von Karman covariance is singular in that "
    "limit. Use a finite outer scale, or the native "
    "'subharmonic_von_karman_v2' spectrum, which does support it."
)

__all__ = (
    "WIND_CONVENTION",
    "HcipyAtmosphereError",
    "HcipyAtmosphereLayerConfig",
    "HcipyAtmosphereConfig",
    "HcipyVonKarmanAtmosphere",
)


class HcipyAtmosphereError(ValueError):
    """Raised when an HCIPy atmosphere configuration or call is invalid."""


@dataclass(frozen=True)
class HcipyAtmosphereLayerConfig:
    """Unit-explicit configuration of one von Kármán frozen-flow layer.

    ``r0_m`` is this layer's own Fried parameter at the model-level
    ``r0_reference_wavelength_m``; layer strengths combine as
    ``r0_total^(-5/3) = Σ r0_i^(-5/3)``.  ``outer_scale_m`` must be finite for
    this backend: HCIPy's von Karman covariance is singular in the unbounded
    limit, so ``None`` (or positive infinity) is refused with
    :class:`HcipyAtmosphereError` rather than failing inside the library.  The
    native ``subharmonic_von_karman_v2`` spectrum does support an unbounded
    outer scale.  ``altitude_m`` is
    carried to HCIPy and reported as metadata; without inter-layer
    propagation (no scintillation in this adapter) it does not change the
    returned OPD.  ``stencil_length`` and ``use_interpolation`` apply to the
    ``infinite`` kind only, ``oversampling`` to the ``finite`` kind only.
    """

    r0_m: float
    outer_scale_m: float | None = 25.0
    wind_m_per_s: tuple[float, float] = (0.0, 0.0)
    altitude_m: float = 0.0
    kind: Literal["infinite", "finite"] = "infinite"
    stencil_length: int = 2
    use_interpolation: bool = True
    oversampling: int = 2

    def __post_init__(self) -> None:
        r0_m = _positive("r0_m", self.r0_m)
        outer_scale_m = _optional_outer_scale(self.outer_scale_m)
        if not isinstance(self.wind_m_per_s, tuple) or len(self.wind_m_per_s) != 2:
            raise HcipyAtmosphereError(
                "wind_m_per_s must be a two-value tuple (vx, vy)."
            )
        wind = (
            _finite("wind_m_per_s[0]", self.wind_m_per_s[0]),
            _finite("wind_m_per_s[1]", self.wind_m_per_s[1]),
        )
        altitude_m = _finite("altitude_m", self.altitude_m)
        if altitude_m < 0.0:
            raise HcipyAtmosphereError(
                f"altitude_m must be non-negative; got {self.altitude_m!r}."
            )
        if self.kind not in ("infinite", "finite"):
            raise HcipyAtmosphereError(
                f"kind must be 'infinite' or 'finite'; got {self.kind!r}."
            )
        stencil_length = _integer("stencil_length", self.stencil_length, minimum=1)
        if not isinstance(self.use_interpolation, (bool, np.bool_)):
            raise HcipyAtmosphereError("use_interpolation must be a bool.")
        oversampling = _integer("oversampling", self.oversampling, minimum=1)

        object.__setattr__(self, "r0_m", r0_m)
        object.__setattr__(self, "outer_scale_m", outer_scale_m)
        object.__setattr__(self, "wind_m_per_s", wind)
        object.__setattr__(self, "altitude_m", altitude_m)
        object.__setattr__(self, "stencil_length", stencil_length)
        object.__setattr__(self, "use_interpolation", bool(self.use_interpolation))
        object.__setattr__(self, "oversampling", oversampling)


@dataclass(frozen=True)
class HcipyAtmosphereConfig:
    """Complete multi-layer HCIPy atmosphere configuration.

    ``r0_reference_wavelength_m`` defines the physical Fried-parameter
    specification of every layer.  ``phase_conversion_reference_wavelength_m``
    is only the HCIPy phase-query/conversion wavelength; it does not change
    the physical atmosphere or the returned OPD.
    """

    layers: tuple[HcipyAtmosphereLayerConfig, ...]
    r0_reference_wavelength_m: float = 500.0e-9
    phase_conversion_reference_wavelength_m: float = 500.0e-9
    root_seed: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.layers, tuple) or not self.layers:
            raise HcipyAtmosphereError(
                "layers must be a non-empty tuple of HcipyAtmosphereLayerConfig."
            )
        if not all(
            isinstance(layer, HcipyAtmosphereLayerConfig) for layer in self.layers
        ):
            raise HcipyAtmosphereError(
                "layers must contain only HcipyAtmosphereLayerConfig instances."
            )
        object.__setattr__(
            self,
            "r0_reference_wavelength_m",
            _positive(
                "r0_reference_wavelength_m",
                self.r0_reference_wavelength_m,
            ),
        )
        object.__setattr__(
            self,
            "phase_conversion_reference_wavelength_m",
            _positive(
                "phase_conversion_reference_wavelength_m",
                self.phase_conversion_reference_wavelength_m,
            ),
        )
        object.__setattr__(
            self,
            "root_seed",
            _integer("root_seed", self.root_seed, minimum=0),
        )

    @classmethod
    def single_layer(
        cls,
        *,
        r0_m: float,
        outer_scale_m: float | None = 25.0,
        wind_m_per_s: tuple[float, float] = (0.0, 0.0),
        altitude_m: float = 0.0,
        kind: Literal["infinite", "finite"] = "infinite",
        r0_reference_wavelength_m: float = 500.0e-9,
        phase_conversion_reference_wavelength_m: float = 500.0e-9,
        root_seed: int = 1,
        stencil_length: int = 2,
        use_interpolation: bool = True,
        oversampling: int = 2,
    ) -> "HcipyAtmosphereConfig":
        """Build the required single-layer von Kármán configuration."""

        return cls(
            layers=(
                HcipyAtmosphereLayerConfig(
                    r0_m=r0_m,
                    outer_scale_m=outer_scale_m,
                    wind_m_per_s=wind_m_per_s,
                    altitude_m=altitude_m,
                    kind=kind,
                    stencil_length=stencil_length,
                    use_interpolation=use_interpolation,
                    oversampling=oversampling,
                ),
            ),
            r0_reference_wavelength_m=r0_reference_wavelength_m,
            phase_conversion_reference_wavelength_m=(
                phase_conversion_reference_wavelength_m
            ),
            root_seed=root_seed,
        )

    @property
    def total_r0_m(self) -> float:
        """Combined Fried parameter at ``r0_reference_wavelength_m``."""

        return float(
            sum(layer.r0_m ** -_KOLMOGOROV_EXPONENT for layer in self.layers)
            ** (-1.0 / _KOLMOGOROV_EXPONENT)
        )


class HcipyVonKarmanAtmosphere:
    """Single- or multi-layer HCIPy atmosphere implementing ``AtmosphereModel``.

    The model sums the per-layer achromatic phase screens on the pupil grid
    (near-field, no scintillation), converts once at the configured phase
    conversion wavelength, and removes piston through the core utilities.
    Controller state, latency, and detector behavior remain repository-level
    concerns; this adapter holds only HCIPy's own optical/atmospheric state.
    """

    def __init__(
        self,
        config: HcipyAtmosphereConfig,
        pupil_geometry: PupilGeometry,
        *,
        pupil_mask: np.ndarray | None = None,
        random_streams: RandomStreams | None = None,
    ) -> None:
        if not isinstance(config, HcipyAtmosphereConfig):
            raise HcipyAtmosphereError(
                "config must be an HcipyAtmosphereConfig instance."
            )
        if not isinstance(pupil_geometry, PupilGeometry):
            raise HcipyAtmosphereError("pupil_geometry must be a PupilGeometry.")
        if pupil_mask is None:
            pupil = np.asarray(pupil_geometry.pupil_mask, dtype=bool)
        else:
            pupil = _validated_pupil(
                pupil_mask,
                expected_shape=pupil_geometry.pupil_shape,
            )
        if random_streams is not None:
            if not isinstance(random_streams, RandomStreams):
                raise HcipyAtmosphereError(
                    "random_streams must implement the canonical RandomStreams "
                    "protocol."
                )
            if random_streams.root_seed != config.root_seed:
                raise HcipyAtmosphereError(
                    "random_streams.root_seed must equal config.root_seed."
                )
        self._config = config
        self._streams: RandomStreams = (
            random_streams
            if random_streams is not None
            else NamedRandomStreams(config.root_seed)
        )
        self._pupil_mask = _readonly_copy(pupil, dtype=bool)
        self._pupil_mask_hash = stable_hash(
            self._pupil_mask,
            namespace="hcipy-atmosphere-pupil",
        )
        self._pupil_geometry_hash = pupil_geometry.geometry_hash
        self._grid_shape = tuple(int(value) for value in pupil_geometry.pupil_shape)
        self._config_hash = component_config_hash(
            "hcipy.von_karman_atmosphere",
            {
                "config": asdict(config),
                "pupil_geometry_hash": self._pupil_geometry_hash,
                "pupil_mask_hash": self._pupil_mask_hash,
                "wind_normalization": _WIND_NORMALIZATION_ID,
                "phase_conversion": _PHASE_CONVERSION_ID,
                "random_derivation_scheme_id": self._streams.derivation_scheme_id,
                "random_scope_stream_id": self._streams.stream_id(
                    "atmosphere",
                    key=("realization", 0),
                ),
            },
        )

        # Resolving the optional dependency is the last construction step, so
        # every repository-side validation error above is raised even on
        # installations without HCIPy.
        hcipy = require_hcipy()
        self._hcipy_version = hcipy_version()
        self._grid = hcipy_grid_from_geometry(pupil_geometry)
        self._layer_cn_squared = tuple(
            float(
                hcipy.Cn_squared_from_fried_parameter(
                    layer.r0_m,
                    config.r0_reference_wavelength_m,
                )
            )
            for layer in config.layers
        )
        self._layers: tuple[Any, ...] = ()
        self._layer_stream_ids: tuple[str, ...] = ()
        self._realization_stream_id = ""
        self._realization_index = 0
        self._last_time_s = 0.0
        self._metadata: Mapping[str, Any] = MappingProxyType({})
        self.reset(realization_index=0)

    @property
    def backend_name(self) -> str:
        return _BACKEND_NAME

    @property
    def config_hash(self) -> str:
        return self._config_hash

    @property
    def config(self) -> HcipyAtmosphereConfig:
        """Return the immutable physical configuration."""

        return self._config

    @property
    def root_seed(self) -> int:
        return self._config.root_seed

    @property
    def realization_index(self) -> int:
        return self._realization_index

    @property
    def metadata(self) -> Mapping[str, Any]:
        return self._metadata

    @property
    def pupil_mask(self) -> np.ndarray:
        return _readonly_copy(self._pupil_mask, dtype=bool)

    def reset(self, *, realization_index: int = 0) -> None:
        """Rebuild every HCIPy layer deterministically and return to t=0.

        The same index recreates the same realization exactly; a different
        index derives independent screens from the same immutable root seed.
        """

        index = _integer("realization_index", realization_index, minimum=0)
        hcipy = require_hcipy()
        layers: list[Any] = []
        stream_ids: list[str] = []
        for layer_index, layer_config in enumerate(self._config.layers):
            key = ("realization", index, "layer", layer_index)
            generator = self._streams.keyed_generator("atmosphere", key=key)
            stream_ids.append(self._streams.stream_id("atmosphere", key=key))
            layers.append(
                _build_hcipy_layer(
                    hcipy,
                    layer_config,
                    grid=self._grid,
                    cn_squared=self._layer_cn_squared[layer_index],
                    generator=generator,
                )
            )
        for layer in layers:
            layer.evolve_until(0.0)
        self._layers = tuple(layers)
        self._layer_stream_ids = tuple(stream_ids)
        self._realization_stream_id = self._streams.stream_id(
            "atmosphere",
            key=("realization", index),
        )
        self._realization_index = index
        self._last_time_s = 0.0
        self._refresh_metadata()

    def opd_at(self, time_s: float) -> np.ndarray:
        """Return piston-removed OPD metres at an absolute simulation time."""

        time_value = _absolute_time(time_s, previous=self._last_time_s)
        hcipy = require_hcipy()
        conversion_wavelength_m = (
            self._config.phase_conversion_reference_wavelength_m
        )
        total_phase_rad = np.zeros(
            self._grid_shape[0] * self._grid_shape[1],
            dtype=float,
        )
        for layer in self._layers:
            layer.evolve_until(time_value)
            total_phase_rad += np.asarray(
                layer.phase_for(conversion_wavelength_m),
                dtype=float,
            )
        try:
            phase_rad = masked_array_from_field(
                hcipy.Field(total_phase_rad, self._grid),
                self._pupil_mask,
            )
            opd_m = remove_piston(
                phase_to_opd(phase_rad, conversion_wavelength_m),
                self._pupil_mask,
            )
        except (HcipyConversionError, ValueError) as exc:
            raise HcipyAtmosphereError(str(exc)) from exc
        result = _readonly_copy(opd_m, dtype=float)
        self._last_time_s = time_value
        return result

    def _refresh_metadata(self) -> None:
        config = self._config
        layer_entries = tuple(
            MappingProxyType(
                {
                    "layer_index": layer_index,
                    "kind": layer.kind,
                    "r0_m": layer.r0_m,
                    "integrated_cn_squared_m_1_3": (
                        self._layer_cn_squared[layer_index]
                    ),
                    "outer_scale_m": layer.outer_scale_m,
                    "wind_m_per_s": layer.wind_m_per_s,
                    "hcipy_velocity_m_per_s": _hcipy_velocity(layer),
                    "altitude_m": layer.altitude_m,
                    "stencil_length": (
                        layer.stencil_length if layer.kind == "infinite" else None
                    ),
                    "use_interpolation": (
                        layer.use_interpolation if layer.kind == "infinite" else None
                    ),
                    "oversampling": (
                        layer.oversampling if layer.kind == "finite" else None
                    ),
                    "temporal_model": (
                        "extruded_screen_spline_interpolation"
                        if layer.kind == "infinite" and layer.use_interpolation
                        else "extruded_screen_integer_stencil"
                        if layer.kind == "infinite"
                        else "periodic_spectral_subpixel_shift"
                    ),
                    "random_stream_id": self._layer_stream_ids[layer_index],
                }
            )
            for layer_index, layer in enumerate(config.layers)
        )
        self._metadata = MappingProxyType(
            {
                "schema_name": "shwfs_ao.hcipy_atmosphere",
                "schema_version": _METADATA_SCHEMA_VERSION,
                "backend_name": self.backend_name,
                "model_kind": "von_karman_layers",
                "config_hash": self.config_hash,
                "hcipy_version": self._hcipy_version,
                "root_seed": self.root_seed,
                "realization_index": self.realization_index,
                "random_stream_id": self._realization_stream_id,
                "layer_random_stream_ids": self._layer_stream_ids,
                "random_derivation_scheme_id": self._streams.derivation_scheme_id,
                "realization_invariant": False,
                "opd_unit": "m",
                "outside_pupil_fill": "nan",
                "grid_shape": self._grid_shape,
                "pupil_geometry_hash": self._pupil_geometry_hash,
                "pupil_mask_hash": self._pupil_mask_hash,
                "r0_reference_wavelength_m": config.r0_reference_wavelength_m,
                "phase_conversion_reference_wavelength_m": (
                    config.phase_conversion_reference_wavelength_m
                ),
                "total_r0_m": config.total_r0_m,
                "n_layers": len(config.layers),
                "layers": layer_entries,
                "wind_convention": WIND_CONVENTION,
                "wind_normalization": _WIND_NORMALIZATION_ID,
                "phase_conversion": _PHASE_CONVERSION_ID,
                "scintillation": False,
            }
        )


def _build_hcipy_layer(
    hcipy: Any,
    layer_config: HcipyAtmosphereLayerConfig,
    *,
    grid: Any,
    cn_squared: float,
    generator: np.random.Generator,
) -> Any:
    outer_scale = (
        np.inf if layer_config.outer_scale_m is None else layer_config.outer_scale_m
    )
    if not np.isfinite(outer_scale):
        # HCIPy's von Karman layers build a covariance that is singular in the
        # unbounded-outer-scale limit; the library fails deep inside a Cholesky
        # factorisation with "array must not contain infs or NaNs".  Refuse
        # here, where the cause is still visible, rather than passing an
        # infinity down and surfacing that.
        raise HcipyAtmosphereError(_UNBOUNDED_OUTER_SCALE_MESSAGE)
    velocity = np.asarray(_hcipy_velocity(layer_config), dtype=float)
    if layer_config.kind == "infinite":
        return hcipy.InfiniteAtmosphericLayer(
            grid,
            cn_squared,
            L0=outer_scale,
            velocity=velocity,
            height=layer_config.altitude_m,
            stencil_length=layer_config.stencil_length,
            use_interpolation=layer_config.use_interpolation,
            seed=generator,
        )
    return hcipy.FiniteAtmosphericLayer(
        grid,
        cn_squared,
        L0=outer_scale,
        velocity=velocity,
        height=layer_config.altitude_m,
        oversampling=layer_config.oversampling,
        seed=generator,
    )


def _hcipy_velocity(
    layer_config: HcipyAtmosphereLayerConfig,
) -> tuple[float, float]:
    """Map the repository wind vector onto one HCIPy layer's velocity.

    Enforces ``WIND_CONVENTION`` on hcipy 0.7 primitives, whose raw behavior
    was measured, not assumed: ``InfiniteAtmosphericLayer`` translates the
    pattern along ``-velocity``, and ``FiniteAtmosphericLayer``'s spectral
    shift builds its phase ramp in separated-coordinate order, which lands
    ``velocity[0]`` on the slow (y) field axis and ``velocity[1]`` on the
    fast (x) axis.  The wind-direction tests fail loudly if a future pinned
    HCIPy changes either behavior.
    """

    wind_x, wind_y = layer_config.wind_m_per_s
    if layer_config.kind == "infinite":
        return (-wind_x, -wind_y)
    return (wind_y, wind_x)


def _optional_outer_scale(value: float | None) -> float | None:
    if value is None or (
        isinstance(value, Real)
        and not isinstance(value, (bool, np.bool_))
        and math.isinf(float(value))
        and float(value) > 0.0
    ):
        raise HcipyAtmosphereError(_UNBOUNDED_OUTER_SCALE_MESSAGE)
    return _positive("outer_scale_m", value)


def _validated_pupil(
    pupil_mask: np.ndarray,
    *,
    expected_shape: tuple[int, ...],
) -> np.ndarray:
    raw_pupil = np.asarray(pupil_mask)
    if raw_pupil.dtype.kind != "b":
        raise HcipyAtmosphereError("pupil_mask must contain boolean values.")
    pupil = np.asarray(raw_pupil, dtype=bool)
    if pupil.ndim != 2:
        raise HcipyAtmosphereError("pupil_mask must be a two-dimensional array.")
    if pupil.shape != tuple(expected_shape):
        raise HcipyAtmosphereError(
            f"pupil_mask shape {pupil.shape} does not match expected shape "
            f"{tuple(expected_shape)}."
        )
    if not np.any(pupil):
        raise HcipyAtmosphereError(
            "pupil_mask must contain at least one pupil sample."
        )
    return np.array(pupil, dtype=bool, copy=True)


def _absolute_time(time_s: float, *, previous: float) -> float:
    time_value = _finite("time_s", time_s)
    if time_value < 0.0:
        raise HcipyAtmosphereError(f"time_s must be non-negative; got {time_s!r}.")
    if time_value < previous:
        raise HcipyAtmosphereError(
            "time_s must be nondecreasing within a realization; "
            f"previous={previous!r}, got {time_value!r}."
        )
    return time_value


def _integer(field_name: str, value: int, *, minimum: int) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise HcipyAtmosphereError(
            f"{field_name} must be an integer; got {value!r}."
        )
    integer = int(value)
    if integer < minimum:
        raise HcipyAtmosphereError(
            f"{field_name} must be >= {minimum}; got {value!r}."
        )
    return integer


def _finite(field_name: str, value: float) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise HcipyAtmosphereError(
            f"{field_name} must be a finite real scalar; got {value!r}."
        )
    number = float(value)
    if not math.isfinite(number):
        raise HcipyAtmosphereError(
            f"{field_name} must be a finite real scalar; got {value!r}."
        )
    return number


def _positive(field_name: str, value: float) -> float:
    number = _finite(field_name, value)
    if number <= 0.0:
        raise HcipyAtmosphereError(f"{field_name} must be positive; got {value!r}.")
    return number


def _readonly_copy(values: np.ndarray, *, dtype: Any) -> np.ndarray:
    contiguous = np.ascontiguousarray(np.array(values, dtype=dtype, copy=True))
    result = np.frombuffer(contiguous.tobytes(order="C"), dtype=contiguous.dtype)
    return result.reshape(contiguous.shape)
