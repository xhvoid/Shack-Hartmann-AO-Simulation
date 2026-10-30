"""Native multi-layer von Karman frozen-flow atmosphere.

Every layer is an independent, absolutely normalized von Karman phase screen
whose strength is its share of the integrated Cn2: a layer holding the fraction
``f`` of the turbulence has Fried parameter ``r0 * f**(-3/5)``, so the summed
phase carries exactly the configured ``r0``.  Each layer moves with its own
wind, and the pupil sees the sum of all layers (on-axis, geometric optics).

Why not stack :class:`~.atmosphere.FrozenFlowAtmosphere` v2 screens: their
subharmonic content makes a finite screen non-periodic, so a layer may only
travel ``(screen - pupil) / 2`` pixels before the wrap seam reaches the pupil,
and every translated frame replays 16 FFTs.  A 33.7 m/s ESO layer crosses a
10 m pupil's whole travel budget in 0.3 s.  This model splits the spectrum
instead:

``periodic band``
    All FFT frequencies of a screen ``screen_period_factor`` times the pupil
    array, except the innermost ``(2K+1)**2`` cells.  The band is exactly
    periodic, so any real-valued translation is an exact Fourier phase ramp,
    with no travel limit.  All layers are summed in the Fourier domain and
    transformed together, one inverse FFT per frame.

``analytic low frequencies``
    The innermost cells, resolved into 4x4 midpoint-quadrature nodes, plus
    three levels of 3x3 subharmonic cells below the FFT band.  These modes are
    evaluated directly at the translated pupil coordinates, so they are exact
    at any time and are not periodic over the screen.

Sampling the steep ``f**(-11/3)`` spectrum at cell centres misrepresents the
cells whose pupil filter changes across the cell (tip/tilt and the first few
rings); the quadrature removes that.  With the defaults (period factor 2,
``K=4``, depth 3) the expected piston-removed and tip/tilt-removed pupil
variances of the discrete model are within 0.6 % of the von Karman integral
for the shipped 2 m and 10 m geometries at ``L0 = 25 m``.  An infinite outer
scale needs a deeper subharmonic hierarchy.

The periodic band repeats after a layer has travelled one screen period
(``screen_period_m``); the low-frequency modes do not.  Repetition makes
long-exposure statistics less independent but introduces no discontinuity.

``fixed-physics pairing``
    Three optional configuration fields pair the realizations of two pupil
    samplings.  ``band_draw_reference_screen_size`` draws the band normals on
    a reference grid and lets a smaller screen take the entries at its own
    signed FFT indices, so the coarse screen is a sub-band of the reference
    draw and the low-frequency draws that follow see the same generator state.
    ``band_limit_screen_size`` zeroes every mode outside the band a smaller
    screen can hold (``|k| <= (B - 1) // 2`` per axis), the common band of a
    pupil scan.  ``screen_period_rule = "pupil_diameter"`` makes the screen
    ``factor * (N - 1)`` samples instead of ``factor * N``, so its period is
    ``factor * D`` metres on every grid and equal indices are equal physical
    frequencies; under the default rule the period is ``factor * D * N/(N-1)``
    and equal indices differ in frequency by ``N/(N-1)`` between grids (the
    dilation of the approximate pairing, quantified by
    :mod:`shwfs_ao.validation.atmosphere_pairing`).  All three
    default to today's model: the default draw, hash and metadata are
    unchanged, and only an explicitly set option enters the identity.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from numbers import Integral, Real
from types import MappingProxyType
from typing import Any, Iterator, Mapping

import numpy as np

from ...core.hashing import component_config_hash, stable_hash
from ...core.protocols import RandomStreams
from ...core.random import NamedRandomStreams
from ...core.wavefront import phase_to_opd, remove_piston
from .atmosphere import NativeAtmosphereError, _von_karman_psd


__all__ = (
    "LAYERED_SPECTRUM_MODEL",
    "PAIRED_BAND_ALGORITHM",
    "SCREEN_PERIOD_RULES",
    "FrozenFlowLayer",
    "LayeredFrozenFlowAtmosphereConfig",
    "LayeredFrozenFlowAtmosphere",
    "canonical_identity_payload",
    "common_band_mask",
    "signed_fft_indices",
)

LAYERED_SPECTRUM_MODEL = "periodic_band_analytic_low_frequency_v1"
"""Identifier of the spectral discretization described in the module docstring."""

_BACKEND_NAME = "native"
_METADATA_SCHEMA_VERSION = 1
BAND_COEFFICIENT_STORAGE = ("materialized", "regenerate")
"""Execution modes for the periodic band's per-layer Fourier coefficients.

``materialized`` (the default) keeps every layer's ``screen_size**2`` complex
coefficients in memory.  ``regenerate`` redraws them each frame from the
layer's keyed random generator with the identical arithmetic, so every frame
is bit-identical while about ``16 * n_layers * screen_size**2`` bytes are not
held; it costs one regeneration per layer and frame (``2 R**2`` normals per
layer when ``band_draw_reference_screen_size = R`` is set).  The mode is not
part of the atmosphere's identity."""
_QUADRATURE_SUBSAMPLES = 4
SCREEN_PERIOD_RULES = ("pupil_array", "pupil_diameter")
"""How the periodic band's screen size follows from the pupil grid.

``pupil_array`` (the default): ``screen_size = screen_period_factor *
grid_size``, the period ``factor * grid_size * delta_m``.  ``pupil_diameter``:
``screen_size = screen_period_factor * round(pupil_diameter_m / delta_m)``
(``factor * (N - 1)`` for the geometry's ``delta = D / (N - 1)``), so the
period is ``factor * pupil_diameter_m`` on every grid and equal signed FFT
indices are equal physical frequencies between two pupil samplings."""
PAIRED_BAND_ALGORITHM = "reference_subband_signed_index.v1"
"""Identifier of the paired band draw: reference-grid normals read at the
screen's own signed FFT indices, an optional common band ``|k| <= (B-1)//2``."""
_PAIRING_DEFAULTS: Mapping[str, Any] = MappingProxyType(
    {
        "band_draw_reference_screen_size": None,
        "band_limit_screen_size": None,
        "screen_period_rule": "pupil_array",
    }
)


@dataclass(frozen=True)
class FrozenFlowLayer:
    """One layer: its Cn2 fraction, wind velocity, and altitude.

    ``wind_m_per_s`` is ``(vx, vy)`` on the pupil grid.  ``altitude_m`` is
    recorded for provenance; an on-axis geometric propagation does not use it.
    """

    cn2_fraction: float
    wind_m_per_s: tuple[float, float]
    altitude_m: float = 0.0

    def __post_init__(self) -> None:
        fraction = _positive("cn2_fraction", self.cn2_fraction)
        if not isinstance(self.wind_m_per_s, tuple) or len(self.wind_m_per_s) != 2:
            raise NativeAtmosphereError("wind_m_per_s must be a two-value tuple (vx, vy).")
        wind = (
            _finite("wind_m_per_s[0]", self.wind_m_per_s[0]),
            _finite("wind_m_per_s[1]", self.wind_m_per_s[1]),
        )
        altitude = _finite("altitude_m", self.altitude_m)
        if altitude < 0.0:
            raise NativeAtmosphereError("altitude_m must be non-negative.")
        object.__setattr__(self, "cn2_fraction", fraction)
        object.__setattr__(self, "wind_m_per_s", wind)
        object.__setattr__(self, "altitude_m", altitude)


@dataclass(frozen=True)
class LayeredFrozenFlowAtmosphereConfig:
    """Unit-explicit configuration of a layered frozen-flow atmosphere.

    ``r0_m`` is the integrated Fried parameter at
    ``phase_reference_wavelength_m``; the layer fractions must sum to one.
    ``screen_period_factor`` sets the periodic band's period as a multiple of
    the pupil array (or of the pupil diameter under
    ``screen_period_rule = "pupil_diameter"``), ``inner_quadrature_cells``
    (``K``) the half-width of the block of FFT cells evaluated analytically,
    and ``subharmonic_depth`` the number of 3x3 subharmonic levels below the
    FFT band.

    The three trailing fields pair realizations across pupil samplings (T2,
    G1; module docstring).  ``band_draw_reference_screen_size`` (``R >=
    screen_size``) draws the band normals on an ``R x R`` grid and reads the
    screen's own signed indices from it; ``band_limit_screen_size`` (``2K + 3
    <= B <= screen_size`` so that the band keeps a periodic mode, and ``B <=
    screen_size <= R`` when both are set) zeroes the modes outside ``|k| <= (B
    - 1) // 2`` per axis; ``screen_period_rule``
    selects the screen-size rule.  With the defaults the identity payload
    (:func:`canonical_identity_payload`), draw order, numerics and metadata
    are exactly those of the model before these fields existed.
    """

    grid_size: int
    delta_m: float
    pupil_diameter_m: float
    r0_m: float
    layers: tuple[FrozenFlowLayer, ...]
    outer_scale_m: float | None = 25.0
    phase_reference_wavelength_m: float = 500.0e-9
    root_seed: int = 1
    screen_period_factor: int = 2
    inner_quadrature_cells: int = 4
    subharmonic_depth: int = 3
    band_draw_reference_screen_size: int | None = None
    band_limit_screen_size: int | None = None
    screen_period_rule: str = "pupil_array"

    def __post_init__(self) -> None:
        grid_size = _integer("grid_size", self.grid_size, minimum=2)
        factor = _integer("screen_period_factor", self.screen_period_factor, minimum=1)
        inner = _integer("inner_quadrature_cells", self.inner_quadrature_cells, minimum=0)
        rule = self.screen_period_rule
        if not isinstance(rule, str) or rule not in SCREEN_PERIOD_RULES:
            raise NativeAtmosphereError(
                f"screen_period_rule must be one of {SCREEN_PERIOD_RULES}; got {rule!r}."
            )
        delta_m = _positive("delta_m", self.delta_m)
        pupil_diameter_m = _positive("pupil_diameter_m", self.pupil_diameter_m)
        screen = _screen_size(rule, factor, grid_size, delta_m, pupil_diameter_m)
        if screen < grid_size:
            raise NativeAtmosphereError(
                f"the screen ({screen} samples) must hold the pupil array ({grid_size} samples); "
                "raise screen_period_factor."
            )
        if 2 * inner + 1 > screen:
            raise NativeAtmosphereError(
                "inner_quadrature_cells leaves no periodic band on this screen."
            )
        reference = self.band_draw_reference_screen_size
        if reference is not None:
            reference = _integer("band_draw_reference_screen_size", reference, minimum=2)
            if reference < screen:
                raise NativeAtmosphereError(
                    f"band_draw_reference_screen_size ({reference}) must be at least the "
                    f"screen size ({screen}); a screen reads its sub-band from the reference."
                )
        limit = self.band_limit_screen_size
        if limit is not None:
            limit = _integer("band_limit_screen_size", limit, minimum=2)
            if limit > screen:
                raise NativeAtmosphereError(
                    f"band_limit_screen_size ({limit}) must not exceed the screen size "
                    f"({screen}); the common band is the coarsest screen's."
                )
            if (limit - 1) // 2 <= inner:
                raise NativeAtmosphereError(
                    f"band_limit_screen_size ({limit}) keeps no periodic mode: |k| <= "
                    f"{(limit - 1) // 2} lies inside the analytic inner block of half-width "
                    f"{inner}; a common band needs at least {2 * inner + 3} samples."
                )
        if not isinstance(self.layers, tuple) or not self.layers:
            raise NativeAtmosphereError("layers must be a non-empty tuple.")
        if not all(isinstance(layer, FrozenFlowLayer) for layer in self.layers):
            raise NativeAtmosphereError("layers must contain FrozenFlowLayer values.")
        total = math.fsum(layer.cn2_fraction for layer in self.layers)
        if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1.0e-9):
            raise NativeAtmosphereError(
                f"layer cn2_fraction values must sum to 1; got {total!r}."
            )
        if self.outer_scale_m is None or (
            isinstance(self.outer_scale_m, Real)
            and not isinstance(self.outer_scale_m, (bool, np.bool_))
            and math.isinf(float(self.outer_scale_m))
            and float(self.outer_scale_m) > 0.0
        ):
            outer_scale_m = None
        else:
            outer_scale_m = _positive("outer_scale_m", self.outer_scale_m)
        object.__setattr__(self, "grid_size", grid_size)
        object.__setattr__(self, "delta_m", delta_m)
        object.__setattr__(self, "pupil_diameter_m", pupil_diameter_m)
        object.__setattr__(self, "band_draw_reference_screen_size", reference)
        object.__setattr__(self, "band_limit_screen_size", limit)
        object.__setattr__(self, "r0_m", _positive("r0_m", self.r0_m))
        object.__setattr__(self, "outer_scale_m", outer_scale_m)
        object.__setattr__(
            self,
            "phase_reference_wavelength_m",
            _positive("phase_reference_wavelength_m", self.phase_reference_wavelength_m),
        )
        object.__setattr__(self, "root_seed", _integer("root_seed", self.root_seed, minimum=0))
        object.__setattr__(self, "screen_period_factor", factor)
        object.__setattr__(self, "inner_quadrature_cells", inner)
        object.__setattr__(
            self,
            "subharmonic_depth",
            _integer("subharmonic_depth", self.subharmonic_depth, minimum=0),
        )

    @property
    def screen_size(self) -> int:
        """Samples per side of the periodic band's screen (``screen_period_rule``)."""

        return _screen_size(
            self.screen_period_rule,
            self.screen_period_factor,
            self.grid_size,
            self.delta_m,
            self.pupil_diameter_m,
        )

    @property
    def screen_period_m(self) -> float:
        """Travel after which a layer's periodic band repeats, in metres."""

        return self.screen_size * self.delta_m

    @property
    def pairing_active(self) -> bool:
        """True when any fixed-physics pairing field differs from its default."""

        return any(
            getattr(self, name) != default for name, default in _PAIRING_DEFAULTS.items()
        )

    @property
    def band_limit_half_width_index(self) -> int | None:
        """Largest retained signed index per axis under the common band, else None."""

        if self.band_limit_screen_size is None:
            return None
        return (self.band_limit_screen_size - 1) // 2

    @property
    def layer_r0_m(self) -> tuple[float, ...]:
        """Per-layer Fried parameters ``r0 * f**(-3/5)`` at the reference wavelength."""

        return tuple(
            self.r0_m * layer.cn2_fraction ** (-3.0 / 5.0) for layer in self.layers
        )


@dataclass(frozen=True)
class _LowFrequencyBlock:
    """Separable set of analytic modes: ``Re(wy @ coefficients @ wx.T)``."""

    nodes_per_m: np.ndarray
    coefficients: np.ndarray


class LayeredFrozenFlowAtmosphere:
    """Seeded multi-layer frozen-flow atmosphere implementing ``AtmosphereModel``."""

    def __init__(
        self,
        config: LayeredFrozenFlowAtmosphereConfig,
        *,
        pupil_mask: np.ndarray | None = None,
        random_streams: RandomStreams | None = None,
        band_coefficient_storage: str = "materialized",
    ) -> None:
        if not isinstance(config, LayeredFrozenFlowAtmosphereConfig):
            raise NativeAtmosphereError(
                "config must be a LayeredFrozenFlowAtmosphereConfig instance."
            )
        if band_coefficient_storage not in BAND_COEFFICIENT_STORAGE:
            raise NativeAtmosphereError(
                f"band_coefficient_storage must be one of {BAND_COEFFICIENT_STORAGE}."
            )
        self._band_storage = band_coefficient_storage
        self._config = config
        shape = (config.grid_size, config.grid_size)
        pupil = _circular_pupil(config) if pupil_mask is None else _validated_pupil(
            pupil_mask, shape
        )
        if random_streams is not None:
            if not isinstance(random_streams, RandomStreams):
                raise NativeAtmosphereError(
                    "random_streams must implement the canonical RandomStreams protocol."
                )
            if random_streams.root_seed != config.root_seed:
                raise NativeAtmosphereError(
                    "random_streams.root_seed must equal config.root_seed."
                )
            streams = random_streams
        else:
            streams = NamedRandomStreams(config.root_seed)
        self._random_streams = streams
        self._pupil_mask = _readonly(pupil.astype(bool))
        self._pupil_mask_hash = stable_hash(
            self._pupil_mask, namespace="native-atmosphere-pupil"
        )
        self._config_hash = component_config_hash(
            "native.layered_frozen_flow_atmosphere",
            {
                # The legacy payload is ``asdict(config)``; the pairing fields
                # enter only when set (K2 of the stage-05 plan).
                "config": canonical_identity_payload(config),
                "pupil_mask_hash": self._pupil_mask_hash,
                "spectrum_model": LAYERED_SPECTRUM_MODEL,
                "quadrature_subsamples": _QUADRATURE_SUBSAMPLES,
                "random_derivation_scheme_id": streams.derivation_scheme_id,
                "random_scope_stream_id": streams.stream_id(
                    "atmosphere", key=("realization", 0)
                ),
            },
        )
        size = config.screen_size
        frequencies = np.fft.fftfreq(size, d=config.delta_m)
        self._frequencies_per_m = frequencies
        self._coordinates_m = np.arange(config.grid_size, dtype=float) * config.delta_m
        self._band_power_rad2 = _periodic_band_power(config, frequencies)
        # The common band of a pupil scan (None: every mode of the screen).
        self._common_band_mask: np.ndarray | None = (
            None
            if config.band_limit_screen_size is None
            else common_band_mask(size, config.band_limit_screen_size)
        )
        total_power = float(np.sum(self._band_power_rad2))
        self._band_power_retained_fraction = (
            1.0
            if self._common_band_mask is None or total_power <= 0.0
            else float(np.sum(self._band_power_rad2 * self._common_band_mask)) / total_power
        )
        self._low_frequency_tables = _low_frequency_tables(config)
        self._band_coefficients: tuple[np.ndarray, ...] = ()
        self._low_frequency_blocks: tuple[tuple[_LowFrequencyBlock, ...], ...] = ()
        self._realization_index = 0
        self._random_stream_id = ""
        self._layer_stream_ids: tuple[str, ...] = ()
        self._last_time_s = 0.0
        self._max_travel_m = 0.0
        self._metadata: Mapping[str, Any] = MappingProxyType({})
        self.reset(realization_index=0)

    @property
    def backend_name(self) -> str:
        return _BACKEND_NAME

    @property
    def config_hash(self) -> str:
        return self._config_hash

    @property
    def config(self) -> LayeredFrozenFlowAtmosphereConfig:
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
        return _readonly(self._pupil_mask)

    @property
    def max_travel_m(self) -> float:
        """Largest distance any layer has moved since the last ``reset``."""

        return self._max_travel_m

    @property
    def band_coefficient_storage(self) -> str:
        """Execution mode of the periodic-band coefficients (not identity)."""

        return self._band_storage

    @property
    def periodic_band_repeated(self) -> bool:
        """True once some layer has travelled a full periodic-band period."""

        return self._max_travel_m >= self._config.screen_period_m

    def reset(self, *, realization_index: int = 0) -> None:
        """Draw a deterministic realization of every layer and return to t=0."""

        index = _integer("realization_index", realization_index, minimum=0)
        config = self._config
        band: list[np.ndarray] = []
        blocks: list[tuple[_LowFrequencyBlock, ...]] = []
        for layer_index, layer_r0 in enumerate(config.layer_r0_m):
            rng = self._random_streams.keyed_generator(
                "atmosphere", key=("realization", index, "layer", layer_index)
            )
            # The tabulated powers are for r0 = 1 m; Phi scales as r0**(-5/3).
            amplitude = layer_r0 ** (-5.0 / 6.0)
            # Drawn in either storage mode, so the generator reaches the
            # low-frequency draws below in the same state.
            coefficients = self._band_draw(rng, amplitude)
            if self._band_storage == "materialized":
                band.append(coefficients)
            del coefficients
            layer_blocks = []
            for nodes, power in self._low_frequency_tables:
                coefficients = (
                    rng.normal(size=power.shape) + 1j * rng.normal(size=power.shape)
                ) * (np.sqrt(power) * amplitude)
                layer_blocks.append(_LowFrequencyBlock(nodes, coefficients))
            blocks.append(tuple(layer_blocks))
        self._band_coefficients = tuple(band)
        self._low_frequency_blocks = tuple(blocks)
        self._realization_index = index
        self._random_stream_id = self._random_streams.stream_id(
            "atmosphere", key=("realization", index)
        )
        self._layer_stream_ids = tuple(
            self._random_streams.stream_id(
                "atmosphere", key=("realization", index, "layer", layer_index)
            )
            for layer_index in range(len(config.layers))
        )
        self._last_time_s = 0.0
        self._max_travel_m = 0.0
        self._refresh_metadata()

    def _band_draw(self, rng: np.random.Generator, amplitude: float) -> np.ndarray:
        """One layer's periodic-band coefficients from its keyed generator.

        With a reference screen size ``R`` the normals are drawn as two
        ``R x R`` arrays (the same call sequence as the default with ``R`` equal
        to the screen size) and the screen reads the entries at its own signed
        FFT indices; a common band zeroes the modes outside it.  The band
        power is always the screen's own (``_periodic_band_power`` at its own
        frequencies).
        """

        config = self._config
        size = config.screen_size
        reference = (
            size
            if config.band_draw_reference_screen_size is None
            else config.band_draw_reference_screen_size
        )
        draws = rng.normal(size=(reference, reference)) + 1j * rng.normal(
            size=(reference, reference)
        )
        if reference != size:
            index = signed_fft_indices(size) % reference
            draws = draws[np.ix_(index, index)]
        if self._common_band_mask is not None:
            draws = draws * self._common_band_mask
        # numpy's inverse FFT divides by size**2; fold that back in here.
        return draws * (np.sqrt(self._band_power_rad2) * amplitude * size**2)

    @property
    def band_power_retained_fraction(self) -> float:
        """Band power inside the common band over the screen's own band power (1 without a limit)."""

        return self._band_power_retained_fraction

    def _layer_band_coefficients(self) -> Iterator[np.ndarray]:
        """Yield each layer's band coefficients, stored or regenerated."""

        if self._band_storage == "materialized":
            yield from self._band_coefficients
            return
        for layer_index, layer_r0 in enumerate(self._config.layer_r0_m):
            rng = self._random_streams.keyed_generator(
                "atmosphere",
                key=("realization", self._realization_index, "layer", layer_index),
            )
            yield self._band_draw(rng, layer_r0 ** (-5.0 / 6.0))

    def opd_at(self, time_s: float) -> np.ndarray:
        """Return piston-removed OPD metres at an absolute simulation time."""

        time_value = _absolute_time(time_s, previous=self._last_time_s)
        phase = self._phase_rad(time_value)
        try:
            opd_m = phase_to_opd(
                remove_piston(phase, self._pupil_mask),
                self._config.phase_reference_wavelength_m,
            )
        except ValueError as exc:
            raise NativeAtmosphereError(str(exc)) from exc
        self._last_time_s = time_value
        return _readonly(opd_m)

    def _phase_rad(self, time_s: float) -> np.ndarray:
        """Summed layer phase on the pupil array, before piston removal."""

        config = self._config
        n = config.grid_size
        frequencies = self._frequencies_per_m
        size = config.screen_size
        spectrum = np.zeros((size, size), dtype=complex)
        work = np.empty_like(spectrum)
        shifts = []
        for layer, coefficients in zip(config.layers, self._layer_band_coefficients()):
            shift_x = layer.wind_m_per_s[0] * time_s
            shift_y = layer.wind_m_per_s[1] * time_s
            shifts.append((shift_x, shift_y))
            self._max_travel_m = max(self._max_travel_m, math.hypot(shift_x, shift_y))
            if shift_x == 0.0 and shift_y == 0.0:
                spectrum += coefficients
                continue
            # A rigid translation by s multiplies every Fourier mode by
            # exp(-2 pi i f.s); the ramp is separable in x and y.
            np.multiply(
                coefficients,
                np.exp(-2j * np.pi * frequencies * shift_y)[:, None],
                out=work,
            )
            work *= np.exp(-2j * np.pi * frequencies * shift_x)[None, :]
            spectrum += work
        # Only the first n rows and columns are the pupil array.
        phase = np.fft.ifft(np.fft.ifft(spectrum, axis=1)[:, :n], axis=0)[:n].real
        coordinates = self._coordinates_m
        for (shift_x, shift_y), layer_blocks in zip(shifts, self._low_frequency_blocks):
            for block in layer_blocks:
                nodes = block.nodes_per_m
                waves_x = np.exp(2j * np.pi * np.outer(coordinates - shift_x, nodes))
                waves_y = np.exp(2j * np.pi * np.outer(coordinates - shift_y, nodes))
                phase += (waves_y @ block.coefficients @ waves_x.T).real
        if not np.all(np.isfinite(phase)):
            raise NativeAtmosphereError("generated layered phase must be finite.")
        return phase

    def _refresh_metadata(self) -> None:
        config = self._config
        pairing: dict[str, Any] = {}
        if config.pairing_active:
            # Recorded only when a pairing option is set, so the default
            # metadata keeps exactly its historical keys.
            reference = config.band_draw_reference_screen_size
            pairing = {
                "band_draw_reference_screen_size": reference,
                "band_limit_screen_size": config.band_limit_screen_size,
                "band_limit_half_width_index": config.band_limit_half_width_index,
                "screen_period_rule": config.screen_period_rule,
                "paired_band_algorithm": (
                    PAIRED_BAND_ALGORITHM
                    if reference is not None or config.band_limit_screen_size is not None
                    else None
                ),
                "band_power_retained_fraction": self._band_power_retained_fraction,
                "frequency_unit": "cycles_per_m",
                "frequency_spacing_per_m": 1.0 / config.screen_period_m,
                "reference_draw_normals_per_layer": (
                    None if reference is None else 2 * reference * reference
                ),
                "nyquist_index_handling": (
                    "signed FFT indices; an even screen holds -S/2 without +S/2; a common "
                    "band keeps |k| <= (B-1)//2 per axis, so an even B excludes its own "
                    "Nyquist row and column"
                ),
            }
        self._metadata = MappingProxyType(
            {
                "schema_name": "shwfs_ao.native_atmosphere",
                "schema_version": _METADATA_SCHEMA_VERSION,
                "backend_name": self.backend_name,
                "model_kind": "layered_fourier_frozen_flow",
                "config_hash": self.config_hash,
                "root_seed": self.root_seed,
                "realization_index": self.realization_index,
                "random_stream_id": self._random_stream_id,
                "layer_random_stream_ids": self._layer_stream_ids,
                "random_derivation_scheme_id": self._random_streams.derivation_scheme_id,
                "realization_invariant": False,
                "opd_unit": "m",
                "outside_pupil_fill": "nan",
                "grid_shape": (config.grid_size, config.grid_size),
                "pupil_mask_hash": self._pupil_mask_hash,
                "grid_delta_m": config.delta_m,
                "pupil_diameter_m": config.pupil_diameter_m,
                "r0_m": config.r0_m,
                "r0_reference_wavelength_m": config.phase_reference_wavelength_m,
                "outer_scale_m": config.outer_scale_m,
                "phase_reference_wavelength_m": config.phase_reference_wavelength_m,
                "n_layers": len(config.layers),
                "layers": tuple(
                    MappingProxyType(
                        {
                            "altitude_m": layer.altitude_m,
                            "cn2_fraction": layer.cn2_fraction,
                            "r0_m": layer_r0,
                            "wind_m_per_s": layer.wind_m_per_s,
                        }
                    )
                    for layer, layer_r0 in zip(config.layers, config.layer_r0_m)
                ),
                "spectrum_model": LAYERED_SPECTRUM_MODEL,
                "screen_size": config.screen_size,
                "screen_period_m": config.screen_period_m,
                "inner_quadrature_cells": config.inner_quadrature_cells,
                "spectral_quadrature_subsamples": _QUADRATURE_SUBSAMPLES,
                "subharmonic_depth": config.subharmonic_depth,
                "absolutely_normalized": True,
                "realization_rms_rescaled": False,
                "frozen_flow_discretization": "exact_fourier_subpixel_unbounded_travel",
                "wind_convention": "pattern_advects_with_positive_wind",
                "band_coefficient_storage": self._band_storage,
                **pairing,
            }
        )


def canonical_identity_payload(config: LayeredFrozenFlowAtmosphereConfig) -> dict[str, Any]:
    """The configuration as the atmosphere's ``config_hash`` digests it.

    ``asdict(config)`` with the three pairing fields removed while they hold
    their defaults, so every identity published before they existed is
    unchanged; a set field stays with its value, and a reference draw or a
    common band adds ``paired_band_algorithm``.  Nothing else is stripped: an
    unrelated ``None`` or default value keeps its place in the payload.
    """

    payload = asdict(config)
    for name, default in _PAIRING_DEFAULTS.items():
        if payload[name] == default:
            del payload[name]
    if (
        config.band_draw_reference_screen_size is not None
        or config.band_limit_screen_size is not None
    ):
        payload["paired_band_algorithm"] = PAIRED_BAND_ALGORITHM
    return payload


def signed_fft_indices(size: int) -> np.ndarray:
    """The signed FFT index of every position of a length-``size`` axis.

    ``numpy.fft.fftfreq(size) * size``: ``0 .. size//2 - 1`` then
    ``-size//2 .. -1`` for an even ``size`` (the Nyquist index is ``-size/2``
    and ``+size/2`` is absent); symmetric for an odd ``size``.
    """

    count = _integer("size", size, minimum=1)
    return np.rint(np.fft.fftfreq(count) * count).astype(int)


def common_band_mask(size: int, limit: int) -> np.ndarray:
    """Boolean ``(size, size)`` mask of the modes a ``limit``-sample screen can hold.

    A mode is kept when both its signed indices satisfy ``|k| <= (limit - 1)
    // 2``, the symmetric band of a ``limit`` grid: for an even ``limit`` this
    excludes that grid's Nyquist index ``-limit/2`` (which has no ``+limit/2``
    partner), so every retained mode has its conjugate partner on every grid
    of at least ``limit`` samples and the band is one real trigonometric
    polynomial on all of them.
    """

    count = _integer("size", size, minimum=1)
    bound = _integer("limit", limit, minimum=2)
    if bound > count:
        raise NativeAtmosphereError("limit must not exceed size.")
    keep = np.abs(signed_fft_indices(count)) <= (bound - 1) // 2
    return keep[:, None] & keep[None, :]


def _screen_size(
    rule: str, factor: int, grid_size: int, delta_m: float, pupil_diameter_m: float
) -> int:
    if rule == "pupil_array":
        return factor * grid_size
    samples = pupil_diameter_m / delta_m
    rounded = int(round(samples))
    if rounded < 1 or abs(samples - rounded) > 1.0e-9 * max(1.0, abs(samples)):
        raise NativeAtmosphereError(
            "screen_period_rule 'pupil_diameter' needs pupil_diameter_m to be a whole "
            f"number of grid spacings; pupil_diameter_m / delta_m = {samples!r}."
        )
    return factor * rounded


def _periodic_band_power(
    config: LayeredFrozenFlowAtmosphereConfig, frequencies: np.ndarray
) -> np.ndarray:
    """Mode variances of the periodic band for r0 = 1 m, in rad**2."""

    step = 1.0 / config.screen_period_m
    frequency_x, frequency_y = np.meshgrid(frequencies, frequencies)
    power = _von_karman_psd(
        np.hypot(frequency_x, frequency_y), 1.0, config.outer_scale_m
    ) * step**2
    # The inner block, DC included, belongs to the analytic modes.
    cells = np.rint(frequencies / step).astype(int)
    inner = np.abs(cells) <= config.inner_quadrature_cells
    power[np.ix_(inner, inner)] = 0.0
    return power


def _low_frequency_tables(
    config: LayeredFrozenFlowAtmosphereConfig,
) -> tuple[tuple[np.ndarray, np.ndarray], ...]:
    """Quadrature nodes and r0 = 1 m mode variances of the analytic modes.

    The first table is the inner ``(2K+1)**2`` block of FFT cells; each later
    one is a 3x3 subharmonic level.  The central cell of every table is left
    to the next level, and the innermost one is omitted.
    """

    subsamples = _QUADRATURE_SUBSAMPLES
    offsets = (np.arange(subsamples, dtype=float) + 0.5) / subsamples - 0.5
    step = 1.0 / config.screen_period_m
    tables = []
    half_widths = [config.inner_quadrature_cells] + [1] * config.subharmonic_depth
    for level, half_width in enumerate(half_widths):
        cell = step / 3.0**level
        nodes = (
            np.arange(-half_width, half_width + 1, dtype=float)[:, None] + offsets
        ).ravel() * cell
        node_x, node_y = np.meshgrid(nodes, nodes)
        power = _von_karman_psd(
            np.hypot(node_x, node_y), 1.0, config.outer_scale_m
        ) * (cell / subsamples) ** 2
        centre = slice(half_width * subsamples, (half_width + 1) * subsamples)
        power[centre, centre] = 0.0
        tables.append((nodes, power))
    return tuple(tables)


def _circular_pupil(config: LayeredFrozenFlowAtmosphereConfig) -> np.ndarray:
    coordinates = (
        np.arange(config.grid_size, dtype=float) - config.grid_size // 2
    ) * config.delta_m
    x_m, y_m = np.meshgrid(coordinates, coordinates)
    return np.hypot(x_m, y_m) <= config.pupil_diameter_m / 2.0


def _validated_pupil(pupil_mask: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    raw = np.asarray(pupil_mask)
    if raw.dtype.kind != "b":
        raise NativeAtmosphereError("pupil_mask must contain boolean values.")
    if raw.shape != shape:
        raise NativeAtmosphereError(
            f"pupil_mask shape {raw.shape} does not match expected shape {shape}."
        )
    if not np.any(raw):
        raise NativeAtmosphereError("pupil_mask must contain at least one pupil sample.")
    return raw


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


def _integer(field_name: str, value: object, *, minimum: int) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise NativeAtmosphereError(f"{field_name} must be an integer; got {value!r}.")
    integer = int(value)
    if integer < minimum:
        raise NativeAtmosphereError(f"{field_name} must be >= {minimum}; got {value!r}.")
    return integer


def _finite(field_name: str, value: object) -> float:
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


def _positive(field_name: str, value: object) -> float:
    number = _finite(field_name, value)
    if number <= 0.0:
        raise NativeAtmosphereError(f"{field_name} must be positive; got {value!r}.")
    return number


def _readonly(values: np.ndarray) -> np.ndarray:
    result = np.array(values, copy=True)
    result.setflags(write=False)
    return result
