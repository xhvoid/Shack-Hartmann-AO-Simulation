"""Transparent native static and integer-shift frozen-flow atmospheres.

The Fourier realization and periodic integer-pixel translation deliberately
retain the repository's legacy numerical ordering.  The public boundary is
nevertheless canonical: every frame is piston-removed optical path difference
in metres, with NaN outside the configured pupil.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from numbers import Integral, Real
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np

from ...core.hashing import component_config_hash, stable_hash
from ...core.protocols import RandomStreams
from ...core.random import NamedRandomStreams
from ...core.wavefront import masked_mean, masked_rms, phase_to_opd, remove_piston


_BACKEND_NAME = "native"
_METADATA_SCHEMA_VERSION = 1
_PHASE_VARIANCE_COEFFICIENT = 1.03

__all__ = (
    "NativeAtmosphereError",
    "StaticOpdAtmosphere",
    "FrozenFlowAtmosphereConfig",
    "FrozenFlowAtmosphere",
)


class NativeAtmosphereError(ValueError):
    """Raised when a native atmosphere configuration or call is invalid."""


@dataclass(frozen=True)
class FrozenFlowAtmosphereConfig:
    """Unit-explicit configuration for one periodic Fourier phase screen.

    ``r0_m`` is specified at ``phase_reference_wavelength_m``.  Wind is
    resolved into x/y metres per second and translated with the historical
    nearest-integer-pixel ``numpy.roll`` discretization.
    """

    grid_size: int
    delta_m: float
    pupil_diameter_m: float
    r0_m: float
    outer_scale_m: float | None = 25.0
    phase_reference_wavelength_m: float = 500.0e-9
    wind_m_per_s: tuple[float, float] = (0.0, 0.0)
    root_seed: int = 1
    target_rms_rad: float | None = None
    normalize_rms: bool = True

    def __post_init__(self) -> None:
        grid_size = _integer("grid_size", self.grid_size, minimum=2)
        delta_m = _positive("delta_m", self.delta_m)
        pupil_diameter_m = _positive("pupil_diameter_m", self.pupil_diameter_m)
        r0_m = _positive("r0_m", self.r0_m)
        wavelength_m = _positive(
            "phase_reference_wavelength_m",
            self.phase_reference_wavelength_m,
        )
        root_seed = _integer("root_seed", self.root_seed, minimum=0)

        if self.outer_scale_m is None or (
            isinstance(self.outer_scale_m, Real)
            and not isinstance(self.outer_scale_m, (bool, np.bool_))
            and math.isinf(float(self.outer_scale_m))
            and float(self.outer_scale_m) > 0.0
        ):
            outer_scale_m = None
        else:
            outer_scale_m = _positive("outer_scale_m", self.outer_scale_m)

        if not isinstance(self.wind_m_per_s, tuple) or len(self.wind_m_per_s) != 2:
            raise NativeAtmosphereError("wind_m_per_s must be a two-value tuple (vx, vy).")
        wind = (
            _finite("wind_m_per_s[0]", self.wind_m_per_s[0]),
            _finite("wind_m_per_s[1]", self.wind_m_per_s[1]),
        )

        if self.target_rms_rad is None:
            target_rms_rad = None
        else:
            target_rms_rad = _nonnegative("target_rms_rad", self.target_rms_rad)
        if not isinstance(self.normalize_rms, (bool, np.bool_)):
            raise NativeAtmosphereError("normalize_rms must be a bool.")

        object.__setattr__(self, "grid_size", grid_size)
        object.__setattr__(self, "delta_m", delta_m)
        object.__setattr__(self, "pupil_diameter_m", pupil_diameter_m)
        object.__setattr__(self, "r0_m", r0_m)
        object.__setattr__(self, "outer_scale_m", outer_scale_m)
        object.__setattr__(self, "phase_reference_wavelength_m", wavelength_m)
        object.__setattr__(self, "wind_m_per_s", wind)
        object.__setattr__(self, "root_seed", root_seed)
        object.__setattr__(self, "target_rms_rad", target_rms_rad)
        object.__setattr__(self, "normalize_rms", bool(self.normalize_rms))


class StaticOpdAtmosphere:
    """A user-supplied static OPD map implementing ``AtmosphereModel``."""

    def __init__(
        self,
        opd_m: np.ndarray,
        pupil_mask: np.ndarray,
        *,
        root_seed: int = 0,
    ) -> None:
        self._root_seed = _integer("root_seed", root_seed, minimum=0)
        pupil = _validated_pupil(pupil_mask, expected_shape=np.shape(opd_m))
        try:
            static_opd = remove_piston(opd_m, pupil)
        except ValueError as exc:
            raise NativeAtmosphereError(str(exc)) from exc

        self._pupil_mask = _readonly_copy(pupil, dtype=bool)
        self._static_opd_m = _readonly_copy(static_opd, dtype=float)
        mask_hash = stable_hash(self._pupil_mask, namespace="native-atmosphere-pupil")
        opd_hash = stable_hash(self._static_opd_m, namespace="native-static-opd")
        self._config_hash = component_config_hash(
            "native.static_opd_atmosphere",
            {
                "root_seed": self._root_seed,
                "pupil_mask_hash": mask_hash,
                "static_opd_hash": opd_hash,
            },
        )
        self._realization_index = 0
        self._last_time_s = 0.0
        self._metadata: Mapping[str, Any] = MappingProxyType({})
        self._refresh_metadata(mask_hash=mask_hash, opd_hash=opd_hash)

    @property
    def backend_name(self) -> str:
        return _BACKEND_NAME

    @property
    def config_hash(self) -> str:
        return self._config_hash

    @property
    def root_seed(self) -> int:
        return self._root_seed

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
        """Reset time while retaining the deliberate static realization."""

        self._realization_index = _integer(
            "realization_index",
            realization_index,
            minimum=0,
        )
        self._last_time_s = 0.0
        self._refresh_metadata(
            mask_hash=str(self._metadata["pupil_mask_hash"]),
            opd_hash=str(self._metadata["static_opd_hash"]),
        )

    def opd_at(self, time_s: float) -> np.ndarray:
        """Return the same piston-removed OPD at nondecreasing absolute time."""

        time_value = _absolute_time(time_s, previous=self._last_time_s)
        result = _readonly_copy(self._static_opd_m, dtype=float)
        self._last_time_s = time_value
        return result

    def _refresh_metadata(self, *, mask_hash: str, opd_hash: str) -> None:
        self._metadata = MappingProxyType(
            {
                "schema_name": "shwfs_ao.native_atmosphere",
                "schema_version": _METADATA_SCHEMA_VERSION,
                "backend_name": self.backend_name,
                "model_kind": "static_opd",
                "config_hash": self.config_hash,
                "root_seed": self.root_seed,
                "realization_index": self.realization_index,
                "realization_invariant": True,
                "realization_invariant_reason": "user_supplied_static_opd",
                "opd_unit": "m",
                "outside_pupil_fill": "nan",
                "grid_shape": tuple(int(value) for value in self._pupil_mask.shape),
                "pupil_mask_hash": mask_hash,
                "static_opd_hash": opd_hash,
            }
        )


class FrozenFlowAtmosphere:
    """Single-screen Fourier atmosphere with periodic integer-pixel flow."""

    def __init__(
        self,
        config: FrozenFlowAtmosphereConfig,
        *,
        pupil_mask: np.ndarray | None = None,
        random_streams: RandomStreams | None = None,
    ) -> None:
        if not isinstance(config, FrozenFlowAtmosphereConfig):
            raise NativeAtmosphereError(
                "config must be a FrozenFlowAtmosphereConfig instance."
            )
        self._config = config
        expected_shape = (config.grid_size, config.grid_size)
        if pupil_mask is None:
            pupil = _circular_pupil(config)
        else:
            pupil = _validated_pupil(pupil_mask, expected_shape=expected_shape)
        if random_streams is not None:
            if not isinstance(random_streams, RandomStreams):
                raise NativeAtmosphereError(
                    "random_streams must implement the canonical RandomStreams protocol."
                )
            if random_streams.root_seed != config.root_seed:
                raise NativeAtmosphereError(
                    "random_streams.root_seed must equal config.root_seed."
                )
        self._random_streams = random_streams
        self._pupil_mask = _readonly_copy(pupil, dtype=bool)
        self._pupil_mask_hash = stable_hash(
            self._pupil_mask,
            namespace="native-atmosphere-pupil",
        )
        self._config_hash = component_config_hash(
            "native.frozen_flow_atmosphere",
            {
                "config": asdict(config),
                "pupil_mask_hash": self._pupil_mask_hash,
                "discretization": "legacy_fourier_integer_roll_v1",
                "random_derivation_scheme_id": (
                    "legacy-root-seed-v1"
                    if random_streams is None
                    else random_streams.derivation_scheme_id
                ),
                "random_scope_stream_id": (
                    None
                    if random_streams is None
                    else random_streams.stream_id(
                        "atmosphere",
                        key=("realization", 0),
                    )
                ),
            },
        )
        self._base_phase_rad = _readonly_copy(
            np.zeros(expected_shape, dtype=float),
            dtype=float,
        )
        self._realization_index = 0
        self._realization_seed = config.root_seed
        self._random_stream_id = ""
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
    def config(self) -> FrozenFlowAtmosphereConfig:
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
        """Regenerate a deterministic realization and return to absolute t=0."""

        index = _integer("realization_index", realization_index, minimum=0)
        rng, seed, stream_id = _realization_generator(
            self.root_seed,
            index,
            random_streams=self._random_streams,
        )
        phase = _legacy_fourier_phase_screen(
            self._config,
            self._pupil_mask,
            rng=rng,
        )
        self._base_phase_rad = _readonly_copy(phase, dtype=float)
        self._realization_index = index
        self._realization_seed = seed
        self._random_stream_id = stream_id
        self._last_time_s = 0.0
        self._refresh_metadata()

    def opd_at(self, time_s: float) -> np.ndarray:
        """Return piston-removed OPD metres at an absolute simulation time."""

        time_value = _absolute_time(time_s, previous=self._last_time_s)
        vx_m_per_s, vy_m_per_s = self._config.wind_m_per_s
        shift_x_pix = int(np.round(vx_m_per_s * time_value / self._config.delta_m))
        shift_y_pix = int(np.round(vy_m_per_s * time_value / self._config.delta_m))
        shifted_phase = np.roll(
            np.roll(self._base_phase_rad, shift_y_pix, axis=0),
            shift_x_pix,
            axis=1,
        )
        try:
            pupil_phase = remove_piston(shifted_phase, self._pupil_mask)
            opd_m = phase_to_opd(
                pupil_phase,
                self._config.phase_reference_wavelength_m,
            )
        except ValueError as exc:
            raise NativeAtmosphereError(str(exc)) from exc
        result = _readonly_copy(opd_m, dtype=float)
        self._last_time_s = time_value
        return result

    def _refresh_metadata(self) -> None:
        config = self._config
        target_rms = _target_rms_rad(config)
        self._metadata = MappingProxyType(
            {
                "schema_name": "shwfs_ao.native_atmosphere",
                "schema_version": _METADATA_SCHEMA_VERSION,
                "backend_name": self.backend_name,
                "model_kind": "fourier_frozen_flow",
                "config_hash": self.config_hash,
                "root_seed": self.root_seed,
                "realization_index": self.realization_index,
                "realization_seed": self._realization_seed,
                "random_stream_id": self._random_stream_id,
                "realization_invariant": False,
                "opd_unit": "m",
                "outside_pupil_fill": "nan",
                "grid_shape": tuple(int(value) for value in self._pupil_mask.shape),
                "pupil_mask_hash": self._pupil_mask_hash,
                "grid_delta_m": config.delta_m,
                "pupil_diameter_m": config.pupil_diameter_m,
                "r0_m": config.r0_m,
                "r0_reference_wavelength_m": config.phase_reference_wavelength_m,
                "outer_scale_m": config.outer_scale_m,
                "phase_reference_wavelength_m": config.phase_reference_wavelength_m,
                "wind_m_per_s": config.wind_m_per_s,
                "target_rms_rad": target_rms,
                "normalize_rms": config.normalize_rms,
                "frozen_flow_discretization": "nearest_integer_periodic_numpy_roll",
            }
        )


def _legacy_fourier_phase_screen(
    config: FrozenFlowAtmosphereConfig,
    pupil_mask: np.ndarray,
    *,
    rng: np.random.Generator,
) -> np.ndarray:
    """Generate the historical full finite Fourier realization."""

    size = config.grid_size
    frequencies = np.fft.fftfreq(size, d=config.delta_m)
    frequency_x, frequency_y = np.meshgrid(frequencies, frequencies)
    radial_frequency = np.sqrt(frequency_x**2 + frequency_y**2)
    inverse_outer_scale = (
        0.0 if config.outer_scale_m is None else 1.0 / config.outer_scale_m
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        power_spectrum = (
            0.023
            * config.r0_m ** (-5.0 / 3.0)
            * (radial_frequency**2 + inverse_outer_scale**2) ** (-11.0 / 6.0)
        )
    power_spectrum[0, 0] = 0.0
    power_spectrum[~np.isfinite(power_spectrum)] = 0.0
    random_complex = rng.normal(size=(size, size)) + 1j * rng.normal(
        size=(size, size)
    )
    fourier_coefficients = random_complex * np.sqrt(power_spectrum)
    phase = np.fft.ifft2(fourier_coefficients).real
    phase -= masked_mean(phase, pupil_mask)

    if config.normalize_rms:
        target_rms = _target_rms_rad(config)
        current_rms = masked_rms(phase, pupil_mask)
        if current_rms > 0.0:
            phase = phase * (target_rms / current_rms)
            phase -= masked_mean(phase, pupil_mask)
    if not np.all(np.isfinite(phase)):
        raise NativeAtmosphereError("generated full phase screen must be finite.")
    return phase


def _target_rms_rad(config: FrozenFlowAtmosphereConfig) -> float:
    if config.target_rms_rad is not None:
        return config.target_rms_rad
    return float(
        np.sqrt(
            _PHASE_VARIANCE_COEFFICIENT
            * (config.pupil_diameter_m / config.r0_m) ** (5.0 / 3.0)
        )
    )


def _circular_pupil(config: FrozenFlowAtmosphereConfig) -> np.ndarray:
    coordinates = (
        np.arange(config.grid_size, dtype=float) - config.grid_size // 2
    ) * config.delta_m
    x_m, y_m = np.meshgrid(coordinates, coordinates)
    pupil = np.sqrt(x_m**2 + y_m**2) <= config.pupil_diameter_m / 2.0
    return _validated_pupil(
        pupil,
        expected_shape=(config.grid_size, config.grid_size),
    )


def _validated_pupil(
    pupil_mask: np.ndarray,
    *,
    expected_shape: tuple[int, ...],
) -> np.ndarray:
    raw_pupil = np.asarray(pupil_mask)
    if raw_pupil.dtype.kind != "b":
        raise NativeAtmosphereError("pupil_mask must contain boolean values.")
    pupil = np.asarray(raw_pupil, dtype=bool)
    if pupil.ndim != 2:
        raise NativeAtmosphereError("pupil_mask must be a two-dimensional array.")
    if pupil.shape != tuple(expected_shape):
        raise NativeAtmosphereError(
            f"pupil_mask shape {pupil.shape} does not match expected shape "
            f"{tuple(expected_shape)}."
        )
    if not np.any(pupil):
        raise NativeAtmosphereError("pupil_mask must contain at least one pupil sample.")
    return np.array(pupil, dtype=bool, copy=True)


def _realization_generator(
    root_seed: int,
    realization_index: int,
    *,
    random_streams: RandomStreams | None = None,
) -> tuple[np.random.Generator, int | None, str]:
    if random_streams is not None:
        key = ("realization", realization_index)
        return (
            random_streams.keyed_generator("atmosphere", key=key),
            None,
            random_streams.stream_id("atmosphere", key=key),
        )
    if realization_index == 0:
        return (
            np.random.default_rng(root_seed),
            root_seed,
            f"legacy-root-seed:{root_seed}",
        )
    streams = NamedRandomStreams(root_seed)
    key = ("realization", realization_index)
    return (
        streams.keyed_generator("atmosphere", key=key),
        None,
        streams.stream_id("atmosphere", key=key),
    )


def _absolute_time(time_s: float, *, previous: float) -> float:
    time_value = _finite("time_s", time_s)
    if time_value < 0.0:
        raise NativeAtmosphereError(f"time_s must be non-negative; got {time_s!r}.")
    if time_value < previous:
        raise NativeAtmosphereError(
            "time_s must be nondecreasing within a realization; "
            f"previous={previous!r}, got {time_value!r}."
        )
    return time_value


def _integer(field_name: str, value: int, *, minimum: int) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise NativeAtmosphereError(f"{field_name} must be an integer; got {value!r}.")
    integer = int(value)
    if integer < minimum:
        raise NativeAtmosphereError(
            f"{field_name} must be >= {minimum}; got {value!r}."
        )
    return integer


def _finite(field_name: str, value: float) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise NativeAtmosphereError(
            f"{field_name} must be a finite real scalar; got {value!r}."
        )
    number = float(value)
    if not math.isfinite(number):
        raise NativeAtmosphereError(
            f"{field_name} must be a finite real scalar; got {value!r}."
        )
    return number


def _positive(field_name: str, value: float) -> float:
    number = _finite(field_name, value)
    if number <= 0.0:
        raise NativeAtmosphereError(
            f"{field_name} must be positive; got {value!r}."
        )
    return number


def _nonnegative(field_name: str, value: float) -> float:
    number = _finite(field_name, value)
    if number < 0.0:
        raise NativeAtmosphereError(
            f"{field_name} must be non-negative; got {value!r}."
        )
    return number


def _readonly_copy(values: np.ndarray, *, dtype: Any) -> np.ndarray:
    contiguous = np.ascontiguousarray(np.array(values, dtype=dtype, copy=True))
    result = np.frombuffer(contiguous.tobytes(order="C"), dtype=contiguous.dtype)
    return result.reshape(contiguous.shape)
