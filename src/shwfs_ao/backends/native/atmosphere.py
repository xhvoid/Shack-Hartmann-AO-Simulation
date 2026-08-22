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

SPECTRUM_LEGACY_V1 = "legacy_fourier_v1"
"""Historical spectrum: no absolute normalization, no subharmonics.

Retained byte-identical because every accepted baseline was generated with
it.  Its realizations carry no calibrated amplitude of their own and are
usable only through ``normalize_rms``; see ``SPECTRUM_SUBHARMONIC_V2``.
"""

SPECTRUM_SUBHARMONIC_V2 = "subharmonic_von_karman_v2"
"""Absolutely normalized von Karman spectrum with subharmonic compensation.

The Fourier sum carries its physical ``N**2 * df`` amplitude, and three
levels of Lane/Johansson subharmonics restore the sub-``1/(N*delta)``
frequencies a bare FFT screen cannot represent.  Realizations are calibrated
in radians without any RMS renormalization.
"""

TRANSLATION_LEGACY_V1 = "nearest_integer_roll_v1"
"""Historical frozen flow: ``numpy.roll`` by a nearest-integer pixel count."""

TRANSLATION_FOURIER_SUBPIXEL_V2 = "fourier_subpixel_v2"
"""Exact sub-pixel translation by a Fourier phase ramp.

For periodic Fourier content, a linear phase ramp is an exact rigid
translation rather than an interpolation, so the integer-roll temporal
staircase disappears.  The v2 subharmonics are not edge-periodic; the travel
budget prevents their wrap seam from entering the pupil.
"""

_SPECTRUM_MODELS = (SPECTRUM_LEGACY_V1, SPECTRUM_SUBHARMONIC_V2)
_TRANSLATION_MODELS = (TRANSLATION_LEGACY_V1, TRANSLATION_FOURIER_SUBPIXEL_V2)
_SUBHARMONIC_DEPTH = 3

__all__ = (
    "NativeAtmosphereError",
    "StaticOpdAtmosphere",
    "FrozenFlowAtmosphereConfig",
    "FrozenFlowAtmosphere",
    "SPECTRUM_LEGACY_V1",
    "SPECTRUM_SUBHARMONIC_V2",
    "TRANSLATION_LEGACY_V1",
    "TRANSLATION_FOURIER_SUBPIXEL_V2",
    "fourier_von_karman_phase_realization",
    "subharmonic_von_karman_phase_realization",
    "von_karman_piston_removed_variance_rad2",
)


class NativeAtmosphereError(ValueError):
    """Raised when a native atmosphere configuration or call is invalid."""


@dataclass(frozen=True)
class FrozenFlowAtmosphereConfig:
    """Unit-explicit configuration for one frozen-flow Fourier phase screen.

    ``r0_m`` is specified at ``phase_reference_wavelength_m``.  Wind is
    resolved into x/y metres per second.  The legacy spectrum is exactly
    periodic and may use the historical nearest-integer-pixel ``numpy.roll``
    discretization indefinitely.  The v2 subharmonic spectrum is not periodic:
    ``screen_grid_size`` may provide padding, and
    :meth:`FrozenFlowAtmosphere.opd_at` refuses the first requested translation
    beyond that padding before the wrap seam can enter the pupil.
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
    spectrum_model: str = SPECTRUM_LEGACY_V1
    translation_model: str = TRANSLATION_LEGACY_V1
    screen_grid_size: int | None = None

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

        if self.spectrum_model not in _SPECTRUM_MODELS:
            raise NativeAtmosphereError(
                f"spectrum_model={self.spectrum_model!r} is not one of "
                f"{list(_SPECTRUM_MODELS)}."
            )
        if self.translation_model not in _TRANSLATION_MODELS:
            raise NativeAtmosphereError(
                f"translation_model={self.translation_model!r} is not one of "
                f"{list(_TRANSLATION_MODELS)}."
            )

        if self.screen_grid_size is None:
            screen_grid_size = None
        else:
            screen_grid_size = _integer(
                "screen_grid_size", self.screen_grid_size, minimum=grid_size
            )
            if screen_grid_size == grid_size:
                screen_grid_size = None
            else:
                if self.spectrum_model != SPECTRUM_SUBHARMONIC_V2:
                    # The legacy screen is frozen and exactly periodic;
                    # oversizing it would change its numerics for no benefit,
                    # since it has no aperiodic subharmonic content to keep
                    # out of the pupil.
                    raise NativeAtmosphereError(
                        "screen_grid_size larger than grid_size requires "
                        f"spectrum_model={SPECTRUM_SUBHARMONIC_V2!r}."
                    )
                if (screen_grid_size - grid_size) % 2 != 0:
                    raise NativeAtmosphereError(
                        "screen_grid_size - grid_size must be even so the "
                        "pupil window is exactly centred."
                    )

        object.__setattr__(self, "screen_grid_size", screen_grid_size)
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
        object.__setattr__(self, "spectrum_model", str(self.spectrum_model))
        object.__setattr__(self, "translation_model", str(self.translation_model))

    @property
    def uses_legacy_numerics(self) -> bool:
        """True when both models are the frozen historical ones.

        Legacy configurations must hash exactly as they did before the v2
        models existed, so the accepted baselines stay valid; the hash payload
        omits both selector fields in that case.
        """

        return (
            self.spectrum_model == SPECTRUM_LEGACY_V1
            and self.translation_model == TRANSLATION_LEGACY_V1
            and self.screen_grid_size is None
        )

    @property
    def generated_grid_size(self) -> int:
        """Size of the generated screen, which may exceed the pupil array."""

        return self.grid_size if self.screen_grid_size is None else self.screen_grid_size

    @property
    def travel_budget_px(self) -> float:
        """Pixels the pupil window may travel before it reaches the wrap seam.

        Subharmonic modes have periods longer than the generated screen, so a
        v2 screen is *not* periodic and its wrap boundary is a real
        discontinuity — measured at about 30 times a typical neighbouring-pixel
        step.  Oversizing the screen keeps that boundary outside the pupil
        window for this many pixels of travel; beyond it the window wraps and
        the seam crosses the pupil.
        """

        return max(0.0, (self.generated_grid_size - self.grid_size) / 2.0)


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
        config_payload = asdict(config)
        spectrum_model = config_payload.pop("spectrum_model")
        translation_model = config_payload.pop("translation_model")
        screen_grid_size = config_payload.pop("screen_grid_size")
        if config.uses_legacy_numerics:
            discretization = "legacy_fourier_integer_roll_v1"
        else:
            config_payload["spectrum_model"] = spectrum_model
            config_payload["translation_model"] = translation_model
            config_payload["screen_grid_size"] = screen_grid_size
            discretization = f"{spectrum_model}+{translation_model}"
        self._config_hash = component_config_hash(
            "native.frozen_flow_atmosphere",
            {
                "config": config_payload,
                "pupil_mask_hash": self._pupil_mask_hash,
                "discretization": discretization,
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
        self._realization_seed: int | None = config.root_seed
        self._random_stream_id = ""
        self._last_time_s = 0.0
        self._travelled_px = 0.0
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
        if self._config.spectrum_model == SPECTRUM_SUBHARMONIC_V2:
            phase = _subharmonic_phase_screen(
                self._config,
                self._pupil_mask,
                rng=rng,
            )
        else:
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
        self._travelled_px = 0.0
        self._refresh_metadata()

    @property
    def travelled_px(self) -> float:
        """Largest pupil-window travel attempted since the last ``reset``.

        Compare against ``config.travel_budget_px``: beyond the budget the
        screen's non-periodic seam would cross the pupil, so :meth:`opd_at`
        raises without returning that frame.  ``exceeded_travel_budget``
        remains true after such a refused attempt until the next ``reset``.
        """

        return self._travelled_px

    @property
    def exceeded_travel_budget(self) -> bool:
        """True once a v2 run has attempted to outlive its screen."""

        if self._config.spectrum_model != SPECTRUM_SUBHARMONIC_V2:
            return False
        return self._travelled_px > self._config.travel_budget_px

    def opd_at(self, time_s: float) -> np.ndarray:
        """Return piston-removed OPD metres at an absolute simulation time."""

        time_value = _absolute_time(time_s, previous=self._last_time_s)
        vx_m_per_s, vy_m_per_s = self._config.wind_m_per_s
        shift_x_px = vx_m_per_s * time_value / self._config.delta_m
        shift_y_px = vy_m_per_s * time_value / self._config.delta_m
        if self._config.spectrum_model == SPECTRUM_SUBHARMONIC_V2:
            # Subharmonic modes have periods longer than the generated array,
            # so their opposite edges do not join continuously.  This guard is
            # tied to the spectrum, not to the presence of padding: an
            # unpadded v2 screen has a zero-pixel budget and therefore supports
            # only translations of zero.  Record the attempted displacement
            # before raising so the advisory state remains truthful after the
            # failed call.
            travelled = math.hypot(shift_x_px, shift_y_px)
            self._travelled_px = max(self._travelled_px, travelled)
            budget = self._config.travel_budget_px
            if travelled > budget:
                raise NativeAtmosphereError(
                    f"pupil window travelled {travelled:.1f} px at t={time_value:g} s, "
                    f"beyond the {budget:.1f} px this screen supports; the "
                    "non-periodic wrap seam would cross the pupil. Enlarge "
                    "screen_grid_size, shorten the run, or slow the wind."
                )
        if self._config.translation_model == TRANSLATION_FOURIER_SUBPIXEL_V2:
            shifted_phase = _fourier_translate(
                self._base_phase_rad,
                shift_x_px=shift_x_px,
                shift_y_px=shift_y_px,
            )
        else:
            shifted_phase = np.roll(
                np.roll(self._base_phase_rad, int(np.round(shift_y_px)), axis=0),
                int(np.round(shift_x_px)),
                axis=1,
            )
        if self._config.screen_grid_size is not None:
            shifted_phase = _centered_window(shifted_phase, self._config.grid_size)
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
                "spectrum_model": config.spectrum_model,
                "translation_model": config.translation_model,
                "screen_grid_size": config.generated_grid_size,
                "travel_budget_px": config.travel_budget_px,
                "absolutely_normalized": (
                    config.spectrum_model == SPECTRUM_SUBHARMONIC_V2
                ),
                "subharmonic_depth": (
                    _SUBHARMONIC_DEPTH
                    if config.spectrum_model == SPECTRUM_SUBHARMONIC_V2
                    else 0
                ),
                "frozen_flow_discretization": (
                    "exact_periodic_fourier_subpixel"
                    if config.translation_model == TRANSLATION_FOURIER_SUBPIXEL_V2
                    else "nearest_integer_periodic_numpy_roll"
                ),
            }
        )


def fourier_von_karman_phase_realization(
    size: int,
    delta_m: float,
    r0_m: float,
    outer_scale_m: float | None,
    *,
    rng: np.random.Generator,
) -> np.ndarray:
    """Draw one raw Fourier von Karman phase realization in radians.

    This is the repository's single canonical implementation of the frozen
    Fourier phase-screen spectrum (AO-REF-021): it consumes exactly two
    ``rng.normal`` draws of shape ``(size, size)`` and returns the full
    finite screen before any piston removal or RMS normalization.  Both the
    native frozen-flow atmosphere and the retained
    :mod:`shwfs_ao.legacy.phase_screen` compatibility wrapper call it, so the
    historical float-operation sequence stays byte-identical on both paths.
    """

    frequencies = np.fft.fftfreq(size, d=delta_m)
    frequency_x, frequency_y = np.meshgrid(frequencies, frequencies)
    radial_frequency = np.sqrt(frequency_x**2 + frequency_y**2)
    inverse_outer_scale = 0.0 if outer_scale_m is None else 1.0 / outer_scale_m
    with np.errstate(divide="ignore", invalid="ignore"):
        power_spectrum = (
            0.023
            * r0_m ** (-5.0 / 3.0)
            * (radial_frequency**2 + inverse_outer_scale**2) ** (-11.0 / 6.0)
        )
    power_spectrum[0, 0] = 0.0
    power_spectrum[~np.isfinite(power_spectrum)] = 0.0
    random_complex = rng.normal(size=(size, size)) + 1j * rng.normal(
        size=(size, size)
    )
    fourier_coefficients = random_complex * np.sqrt(power_spectrum)
    return np.fft.ifft2(fourier_coefficients).real


def _fourier_translate(
    phase: np.ndarray,
    *,
    shift_x_px: float,
    shift_y_px: float,
) -> np.ndarray:
    """Translate a periodic screen by an arbitrary real pixel offset.

    The screen is periodic by construction, so multiplying its spectrum by a
    linear phase ramp is an exact rigid translation, not an interpolation: no
    power is lost and integer offsets reproduce ``numpy.roll`` to rounding.
    This removes the temporal staircase of the integer-roll model, in which a
    wind slower than one pixel per frame leaves consecutive frames identical.
    """

    rows, columns = phase.shape
    row_frequency = np.fft.fftfreq(rows).reshape(-1, 1)
    column_frequency = np.fft.fftfreq(columns).reshape(1, -1)
    ramp = np.exp(
        -2j
        * np.pi
        * (row_frequency * shift_y_px + column_frequency * shift_x_px)
    )
    return np.real(np.fft.ifft2(np.fft.fft2(phase) * ramp))


def _von_karman_psd(
    radial_frequency: np.ndarray | float,
    r0_m: float,
    outer_scale_m: float | None,
) -> np.ndarray:
    """Two-sided von Karman phase PSD in rad^2 m^2."""

    inverse_outer_scale = 0.0 if outer_scale_m is None else 1.0 / outer_scale_m
    frequency = np.asarray(radial_frequency, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        power = (
            0.023
            * r0_m ** (-5.0 / 3.0)
            * (frequency**2 + inverse_outer_scale**2) ** (-11.0 / 6.0)
        )
    return np.where(np.isfinite(power), power, 0.0)


def _cell_integrated_power(
    frequency_x: np.ndarray,
    frequency_y: np.ndarray,
    cell_width: float,
    r0_m: float,
    outer_scale_m: float | None,
    *,
    subsamples: int = 4,
) -> np.ndarray:
    """Integrate the PSD over each frequency cell instead of sampling it.

    A spectral synthesis assigns each cell the variance ``Phi(f) * df**2``,
    which silently assumes ``Phi`` is flat across the cell.  For a spectrum as
    steep as ``f**(-11/3)`` that assumption fails badly in the cells nearest
    the origin — sampling the centre of the coarsest cells recovers only about
    55 % of the power they actually contain, which is most of the residual
    low-frequency deficit a bare subharmonic screen still shows.  Averaging
    over a small sub-grid of each cell removes it.
    """

    offsets = (np.arange(subsamples, dtype=float) + 0.5) / subsamples - 0.5
    accumulated = np.zeros_like(frequency_x, dtype=float)
    for offset_x in offsets:
        shifted_x = frequency_x + offset_x * cell_width
        for offset_y in offsets:
            shifted_y = frequency_y + offset_y * cell_width
            accumulated += _von_karman_psd(
                np.hypot(shifted_x, shifted_y), r0_m, outer_scale_m
            )
    return accumulated / float(subsamples**2) * cell_width**2


def subharmonic_von_karman_phase_realization(
    size: int,
    delta_m: float,
    r0_m: float,
    outer_scale_m: float | None,
    *,
    rng: np.random.Generator,
    subharmonic_depth: int = _SUBHARMONIC_DEPTH,
) -> np.ndarray:
    """Draw one absolutely normalized von Karman phase realization in radians.

    Two defects of :func:`fourier_von_karman_phase_realization` are corrected
    here, and both are needed for the result to be physical:

    *Amplitude.* A discrete spectral synthesis of a field with PSD ``Phi`` is
    ``phi = Re(N**2 * ifft2(c * sqrt(Phi) * df))`` with ``df = 1/(N*delta)``
    and ``c`` a unit complex Gaussian.  The historical implementation omits
    the ``N**2 * df`` factor entirely, so its realizations are smaller than
    the physical screen by that factor and carry no calibrated amplitude.

    *Low frequencies.* The coarsest frequency an ``N``-point FFT represents is
    ``df``; a pupil that fills the grid therefore receives no power at all
    below ``1/D``, which is where Kolmogorov turbulence keeps most of its
    variance.  ``subharmonic_depth`` levels of Lane/Johansson subharmonics add
    those modes back on successively finer 3x3 frequency cells.

    The returned screen is the full finite realization before piston removal,
    calibrated in radians at the r0 reference wavelength.  No RMS
    renormalization is applied or needed.
    """

    size = _integer("size", size, minimum=2)
    delta_m = _positive("delta_m", delta_m)
    r0_m = _positive("r0_m", r0_m)
    depth = _integer("subharmonic_depth", subharmonic_depth, minimum=0)

    frequency_step = 1.0 / (size * delta_m)
    frequencies = np.fft.fftfreq(size, d=delta_m)
    frequency_x, frequency_y = np.meshgrid(frequencies, frequencies)

    cell_power = _cell_integrated_power(
        frequency_x,
        frequency_y,
        frequency_step,
        r0_m,
        outer_scale_m,
    )
    # The DC cell is covered by the subharmonic hierarchy below, which tiles
    # exactly that cell; leaving it here as well would double-count it.
    cell_power[0, 0] = 0.0

    random_complex = rng.normal(size=(size, size)) + 1j * rng.normal(
        size=(size, size)
    )
    coefficients = random_complex * np.sqrt(cell_power)
    phase = np.real(np.fft.ifft2(coefficients) * size**2)

    if depth == 0:
        return phase

    # Subharmonics are evaluated directly on the sample grid rather than by
    # FFT: there are only 8 modes per level, and their periods are by
    # construction longer than the grid, so no transform can represent them.
    coordinates = np.arange(size, dtype=float) * delta_m
    x_m, y_m = np.meshgrid(coordinates, coordinates)

    for level in range(1, depth + 1):
        level_step = frequency_step / (3.0**level)
        for index_x in (-1, 0, 1):
            for index_y in (-1, 0, 1):
                if index_x == 0 and index_y == 0:
                    # Covered by the next deeper level, or DC at the bottom.
                    continue
                fx = index_x * level_step
                fy = index_y * level_step
                power = float(
                    _cell_integrated_power(
                        np.asarray(fx),
                        np.asarray(fy),
                        level_step,
                        r0_m,
                        outer_scale_m,
                    )
                )
                if power <= 0.0:
                    continue
                coefficient = (rng.normal() + 1j * rng.normal()) * math.sqrt(power)
                phase += np.real(
                    coefficient
                    * np.exp(2j * np.pi * (fx * x_m + fy * y_m))
                )

    return phase


def von_karman_piston_removed_variance_rad2(
    pupil_diameter_m: float,
    r0_m: float,
    outer_scale_m: float | None,
) -> float:
    """Piston-removed phase variance over a circular aperture, in rad^2.

    Integrates the von Karman PSD against the piston-removal filter
    ``1 - |2*J1(pi*D*f)/(pi*D*f)|**2``.  As ``outer_scale_m`` grows without
    bound this converges to the Kolmogorov result
    ``1.0299 * (D/r0)**(5/3)``; at a finite outer scale it is smaller, which
    is exactly the correction the historical target
    ``1.03 * (D/r0)**(5/3)`` omits.
    """

    from scipy.special import j1

    diameter = _positive("pupil_diameter_m", pupil_diameter_m)
    r0_m = _positive("r0_m", r0_m)

    # Log-spaced quadrature: the integrand spans many decades in f and decays
    # as f**(-8/3), so a linear grid would need orders of magnitude more
    # points for the same accuracy.
    log_frequency = np.linspace(-8.0, 4.0, 240_001)
    frequency = np.power(10.0, log_frequency)
    argument = np.pi * diameter * frequency
    piston_filter = 1.0 - (2.0 * j1(argument) / argument) ** 2
    integrand = (
        2.0
        * np.pi
        * frequency
        * _von_karman_psd(frequency, r0_m, outer_scale_m)
        * piston_filter
    )
    # d(f) = f * ln(10) * d(log10 f).  The trapezoid rule is written out rather
    # than called: ``np.trapezoid`` was added in NumPy 2, while the older
    # ``np.trapz`` spelling is deprecated there; this package declares support
    # for numpy>=1.24.
    weighted = integrand * frequency * math.log(10.0)
    variance = float(
        np.sum(
            0.5
            * (weighted[1:] + weighted[:-1])
            * np.diff(log_frequency)
        )
    )
    return variance


def _centered_window(screen: np.ndarray, size: int) -> np.ndarray:
    """Extract the centred ``size x size`` window of a generated screen."""

    origin = (screen.shape[0] - size) // 2
    return screen[origin : origin + size, origin : origin + size]


def _subharmonic_phase_screen(
    config: FrozenFlowAtmosphereConfig,
    pupil_mask: np.ndarray,
    *,
    rng: np.random.Generator,
) -> np.ndarray:
    """Generate a calibrated v2 realization, renormalizing only if asked.

    When the screen is oversized the returned array is the full generated
    screen; piston removal and masking happen after the pupil window is cut in
    :meth:`FrozenFlowAtmosphere.opd_at`.  Any RMS normalization is still
    measured on the central pupil window, so the requested target describes
    what the pupil sees rather than what the padding contains.
    """

    phase = subharmonic_von_karman_phase_realization(
        config.generated_grid_size,
        config.delta_m,
        config.r0_m,
        config.outer_scale_m,
        rng=rng,
    )

    window = _centered_window(phase, config.grid_size)
    phase = phase - masked_mean(window, pupil_mask)

    if config.normalize_rms:
        target_rms = _target_rms_rad(config)
        current_rms = masked_rms(
            _centered_window(phase, config.grid_size), pupil_mask
        )
        if current_rms > 0.0:
            phase = phase * (target_rms / current_rms)
            phase = phase - masked_mean(
                _centered_window(phase, config.grid_size), pupil_mask
            )
    if not np.all(np.isfinite(phase)):
        raise NativeAtmosphereError("generated full phase screen must be finite.")
    return phase


def _legacy_fourier_phase_screen(
    config: FrozenFlowAtmosphereConfig,
    pupil_mask: np.ndarray,
    *,
    rng: np.random.Generator,
) -> np.ndarray:
    """Generate the historical full finite Fourier realization."""

    phase = fourier_von_karman_phase_realization(
        config.grid_size,
        config.delta_m,
        config.r0_m,
        config.outer_scale_m,
        rng=rng,
    )
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
    if config.spectrum_model == SPECTRUM_SUBHARMONIC_V2:
        # The v2 default target honours the configured outer scale.  The
        # historical coefficient below is the infinite-outer-scale limit, so
        # using it with a finite L0 asks a von Karman spectrum to carry
        # Kolmogorov energy.
        return float(
            np.sqrt(
                von_karman_piston_removed_variance_rad2(
                    config.pupil_diameter_m,
                    config.r0_m,
                    config.outer_scale_m,
                )
            )
        )
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
