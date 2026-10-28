"""Typed physical camera configuration for the detector-level SH path.

:class:`CameraConfig` describes one ``ccd``, ``emccd`` or ``cmos`` camera of
response model ``shwfs_ao.detector.physical_camera.v1``.  Its presence selects
the physical response chain of :mod:`shwfs_ao.detector.physical`; its absence
keeps the frozen AO-REF-004 compatibility chain.  Packaged presets are
``synthetic_assumed`` engineering values without a commercial camera name;
they are loaded by name and version through
:func:`shwfs_ao.io.camera_presets.load_camera_preset`.

Units.  ``input_e`` are photoelectrons collected in a pixel before any
electron multiplication; ``output_e`` are electrons at the output amplifier
(``input_e`` times the EM gain); ``adu`` are raw digital codes.  Conversion
gain is output electrons per ADU.  ``full_well_e`` is the pixel charge
capacity in input electrons, ``register_full_well_e`` the EM-register
capacity in output electrons.  ``read_noise_e`` is output-referred (the CMOS
value is the median of its per-pixel map).  ``quantum_efficiency`` is the
camera's scalar QE; the photometry model applies it exactly once when it
turns photons into detected electrons, and the camera chain never applies
it again.

Non-linearity is the declared synthetic polynomial
``y = x + sum_k c_k x**(k + 2)`` in output electrons, applied after read noise
and before conversion gain.  It must be strictly increasing over the signal
range the camera can produce.

Electronic coupling is a symmetric 3x3 kernel with weight ``coupling_nearest``
on each of the four nearest neighbours, ``coupling_diagonal`` on each of the
four diagonal neighbours and the remainder on the centre.  It acts on realized
charge-equivalent signals after pixel and register saturation and before read
noise (a synthetic placement assumption, not a universal inter-pixel
capacitance model).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from numbers import Integral, Real
from typing import Any, Literal

import numpy as np

from ..core.hashing import component_config_hash
from ..core.provenance import ALLOWED_SOURCE_CLASSES


__all__ = (
    "PHYSICAL_RESPONSE_MODEL",
    "CAMERA_MODELS",
    "EM_GAIN_GAMMA_MIN",
    "EM_GAIN_GAMMA_MAX",
    "REFERENCE_ADC_DITHER_MODEL",
    "NONLINEARITY_READ_NOISE_EXCURSION_SIGMA",
    "CameraConfigError",
    "CameraConfig",
    "camera_config_from_mapping",
    "camera_config_to_mapping",
)


PHYSICAL_RESPONSE_MODEL = "shwfs_ao.detector.physical_camera.v1"
CameraModel = Literal["ccd", "emccd", "cmos"]
CAMERA_MODELS: tuple[str, ...] = ("ccd", "emccd", "cmos")
# Declared high-gain regime of the Gamma(n, G) register model (decision D00-13).
EM_GAIN_GAMMA_MIN = 100.0
EM_GAIN_GAMMA_MAX = 10000.0
# The deterministic reference path keeps the ADC as its expectation under the
# declared Gaussian read-noise dither (decision D00-3a), so with the ADC on the
# read noise shapes the reference response and is bound to its identity.
REFERENCE_ADC_DITHER_MODEL = "gaussian_read_noise_expectation_v1"
# A declared non-linearity acts after read noise.  It must stay monotonic over
# the output signal range widened by this many read-noise sigmas each side.
NONLINEARITY_READ_NOISE_EXCURSION_SIGMA = 6.0
_ADC_BITS_RANGE = (8, 24)


class CameraConfigError(ValueError):
    """Raised when a physical camera configuration is invalid."""


@dataclass(frozen=True)
class CameraConfig:
    """One physical camera of response model ``physical_camera.v1``."""

    __hash_schema_id__ = "shwfs_ao.detector.CameraConfig.v1"

    model: CameraModel
    preset_name: str
    preset_version: int
    quantum_efficiency: float
    full_well_e: float
    dark_e_per_s: float
    hot_pixel_fraction: float
    hot_pixel_dark_e_per_s: float
    prnu_rms: float
    dead_pixel_fraction: float
    read_noise_e: float
    conversion_gain_e_per_adu: float
    bias_adu: float
    offset_map_rms_adu: float
    adc_bits: int | None
    em_gain: float = 1.0
    cic_e_per_pixel_read: float = 0.0
    register_full_well_e: float | None = None
    cmos_gain_map_rms: float = 0.0
    cmos_read_noise_lognormal_sigma: float = 0.0
    nonlinearity_coefficients: tuple[float, ...] = field(default=())
    coupling_nearest: float = 0.0
    coupling_diagonal: float = 0.0
    source_class: str = "synthetic_assumed"
    source_note: str = "Synthetic physical camera engineering preset."

    def __post_init__(self) -> None:
        if self.model not in CAMERA_MODELS:
            raise CameraConfigError(
                f"model must be one of {list(CAMERA_MODELS)}; got {self.model!r}."
            )
        if not isinstance(self.preset_name, str) or not self.preset_name.strip():
            raise CameraConfigError("preset_name must be a non-empty string.")
        _set(self, "preset_version", _integer(self.preset_version, "preset_version", 1))
        qe = _positive(self.quantum_efficiency, "quantum_efficiency")
        if qe > 1.0:
            raise CameraConfigError("quantum_efficiency must not exceed 1.")
        _set(self, "quantum_efficiency", qe)
        _set(self, "full_well_e", _positive(self.full_well_e, "full_well_e"))
        for name in (
            "dark_e_per_s",
            "hot_pixel_dark_e_per_s",
            "prnu_rms",
            "read_noise_e",
            "bias_adu",
            "offset_map_rms_adu",
            "cic_e_per_pixel_read",
            "cmos_gain_map_rms",
            "cmos_read_noise_lognormal_sigma",
        ):
            _set(self, name, _nonnegative(getattr(self, name), name))
        for name in ("hot_pixel_fraction", "dead_pixel_fraction"):
            _set(self, name, _fraction(getattr(self, name), name))
        _set(
            self,
            "conversion_gain_e_per_adu",
            _positive(self.conversion_gain_e_per_adu, "conversion_gain_e_per_adu"),
        )
        if self.adc_bits is not None:
            bits = _integer(self.adc_bits, "adc_bits", _ADC_BITS_RANGE[0])
            if bits > _ADC_BITS_RANGE[1]:
                raise CameraConfigError(
                    f"adc_bits must be in {list(_ADC_BITS_RANGE)} or null."
                )
            _set(self, "adc_bits", bits)
            if self.bias_adu >= 2**bits - 1:
                raise CameraConfigError("bias_adu must lie inside the ADC range.")
        gain = _positive(self.em_gain, "em_gain")
        _set(self, "em_gain", gain)
        if self.model == "emccd":
            if gain != 1.0 and not EM_GAIN_GAMMA_MIN <= gain <= EM_GAIN_GAMMA_MAX:
                raise CameraConfigError(
                    f"em_gain={gain:g} lies outside the supported regime: unity "
                    "(deterministic) or the declared Gamma high-gain range "
                    f"[{EM_GAIN_GAMMA_MIN:g}, {EM_GAIN_GAMMA_MAX:g}].  No sourced "
                    "finite-stage register model is delivered for intermediate gains."
                )
            if self.register_full_well_e is None:
                raise CameraConfigError("an emccd needs register_full_well_e.")
            _set(
                self,
                "register_full_well_e",
                _positive(self.register_full_well_e, "register_full_well_e"),
            )
        else:
            if gain != 1.0:
                raise CameraConfigError("em_gain applies to emccd cameras only.")
            if self.cic_e_per_pixel_read != 0.0:
                raise CameraConfigError(
                    "pre-register clock-induced charge applies to emccd cameras only."
                )
            if self.register_full_well_e is not None:
                raise CameraConfigError(
                    "register_full_well_e applies to emccd cameras only."
                )
        if self.model != "cmos" and (
            self.cmos_gain_map_rms != 0.0 or self.cmos_read_noise_lognormal_sigma != 0.0
        ):
            raise CameraConfigError("CMOS gain and read-noise maps apply to cmos only.")
        if self.cmos_gain_map_rms >= 0.2:
            raise CameraConfigError(
                "cmos_gain_map_rms must stay below 0.2 so the gain multiplier stays positive."
            )
        coefficients = tuple(
            _finite(value, "nonlinearity_coefficients") for value in self.nonlinearity_coefficients
        )
        _set(self, "nonlinearity_coefficients", coefficients)
        nearest = _nonnegative(self.coupling_nearest, "coupling_nearest")
        diagonal = _nonnegative(self.coupling_diagonal, "coupling_diagonal")
        if 4.0 * (nearest + diagonal) >= 1.0:
            raise CameraConfigError(
                "coupling weights must leave a positive centre weight: "
                "4 * (coupling_nearest + coupling_diagonal) < 1."
            )
        _set(self, "coupling_nearest", nearest)
        _set(self, "coupling_diagonal", diagonal)
        if self.source_class not in ALLOWED_SOURCE_CLASSES:
            raise CameraConfigError(f"source_class {self.source_class!r} is not permitted.")
        if not isinstance(self.source_note, str) or not self.source_note.strip():
            raise CameraConfigError("source_note must be a non-empty string.")
        if coefficients:
            _require_monotonic_nonlinearity(
                coefficients,
                self.max_output_signal_e,
                NONLINEARITY_READ_NOISE_EXCURSION_SIGMA * float(self.read_noise_e),
            )

    # -- derived quantities -------------------------------------------------

    @property
    def response_model(self) -> str:
        return PHYSICAL_RESPONSE_MODEL

    @property
    def is_multiplying(self) -> bool:
        return self.model == "emccd" and self.em_gain != 1.0

    @property
    def excess_noise_factor_squared(self) -> float:
        """F^2 of the declared register model: 2 in the Gamma regime, else 1."""

        return 2.0 if self.is_multiplying else 1.0

    @property
    def max_output_signal_e(self) -> float:
        """Largest charge-equivalent output signal the chain can produce.

        A multiplying register's Gamma output is unbounded for any non-zero
        input charge (``full_well * G`` bounds only its conditional mean), so
        the register capacity is the bound.  Coupling cannot exceed it: the
        kernel is non-negative and sums to one.
        """

        if self.model == "emccd":
            assert self.register_full_well_e is not None
            if self.is_multiplying:
                return float(self.register_full_well_e)
            return float(min(self.full_well_e, self.register_full_well_e))
        return float(self.full_well_e)

    @property
    def coupling_kernel(self) -> np.ndarray:
        """The 3x3 electronic coupling kernel K (rows, columns)."""

        d = self.coupling_diagonal
        a = self.coupling_nearest
        centre = 1.0 - 4.0 * (a + d)
        kernel = np.array([[d, a, d], [a, centre, a], [d, a, d]], dtype=float)
        kernel.flags.writeable = False
        return kernel

    @property
    def has_coupling(self) -> bool:
        return self.coupling_nearest > 0.0 or self.coupling_diagonal > 0.0

    @property
    def adc_max_code(self) -> int | None:
        return None if self.adc_bits is None else int(2**self.adc_bits - 1)

    @property
    def raw_unit(self) -> str:
        return "adu" if self.adc_bits is not None else "output_e_equivalent"

    @property
    def maps_config(self) -> dict[str, Any]:
        """Every setting that determines a persistent pixel map, and nothing else."""

        return {
            "response_model": PHYSICAL_RESPONSE_MODEL,
            "model": self.model,
            "prnu_rms": self.prnu_rms,
            "dead_pixel_fraction": self.dead_pixel_fraction,
            "hot_pixel_fraction": self.hot_pixel_fraction,
            "hot_pixel_dark_e_per_s": self.hot_pixel_dark_e_per_s,
            "offset_map_rms_adu": self.offset_map_rms_adu,
            "cmos_gain_map_rms": self.cmos_gain_map_rms,
            "cmos_read_noise_lognormal_sigma": self.cmos_read_noise_lognormal_sigma,
        }

    @property
    def maps_config_hash(self) -> str:
        return component_config_hash("physical_camera_maps", self.maps_config)

    @property
    def deterministic_response_config(self) -> dict[str, Any]:
        """Scalar settings that shape the deterministic reference response.

        With the ADC on, the reference quantizer is the expectation under the
        read-noise dither, so the read noise is bound here as well (the CMOS
        per-pixel read-noise map is bound through the maps realization).  With
        the ADC off the reference does not depend on read noise, and the
        record omits it.
        """

        record = {
            "response_model": PHYSICAL_RESPONSE_MODEL,
            "model": self.model,
            "full_well_e": self.full_well_e,
            "dark_e_per_s": self.dark_e_per_s,
            "conversion_gain_e_per_adu": self.conversion_gain_e_per_adu,
            "bias_adu": self.bias_adu,
            "adc_bits": self.adc_bits,
            "em_gain": self.em_gain,
            "cic_mean_e_per_pixel_read": self.cic_e_per_pixel_read,
            "register_full_well_e": self.register_full_well_e,
            "nonlinearity_coefficients": self.nonlinearity_coefficients,
            "coupling_nearest": self.coupling_nearest,
            "coupling_diagonal": self.coupling_diagonal,
        }
        if self.adc_bits is not None:
            record["reference_adc_dither"] = {
                "model": REFERENCE_ADC_DITHER_MODEL,
                "read_noise_e": self.read_noise_e,
            }
        return record

    @property
    def temporal_noise_config(self) -> dict[str, Any]:
        """Settings of the noise distribution of the stochastic path.

        ``read_noise_e`` also shapes the reference response when the ADC is on;
        :attr:`deterministic_response_config` binds it there too.
        """

        return {
            "read_noise_e": self.read_noise_e,
            "excess_noise_model": (
                "gamma_high_gain_v1" if self.is_multiplying else "none"
            ),
            "cic_model": (
                "poisson_pre_register_v1" if self.cic_e_per_pixel_read > 0.0 else "none"
            ),
            "shot_noise_model": "poisson_v1",
        }

    @property
    def config_hash(self) -> str:
        return component_config_hash("physical_camera", self)


def camera_config_to_mapping(config: CameraConfig) -> dict[str, Any]:
    """Serialize every field, in declaration order."""

    record: dict[str, Any] = {}
    for name in CameraConfig.__dataclass_fields__:
        value = getattr(config, name)
        record[name] = list(value) if isinstance(value, tuple) else value
    return record


def camera_config_from_mapping(record: dict[str, Any]) -> CameraConfig:
    """Strictly parse a camera mapping: every declared field, nothing else."""

    expected = set(CameraConfig.__dataclass_fields__)
    keys = set(record)
    if keys != expected:
        raise CameraConfigError(
            "camera block fields differ: missing="
            f"{sorted(expected - keys)} extra={sorted(keys - expected)}."
        )
    values = dict(record)
    coefficients = values["nonlinearity_coefficients"]
    if not isinstance(coefficients, (list, tuple)):
        raise CameraConfigError("nonlinearity_coefficients must be a list.")
    values["nonlinearity_coefficients"] = tuple(coefficients)
    return CameraConfig(**values)


def _require_monotonic_nonlinearity(
    coefficients: tuple[float, ...],
    max_signal_e: float,
    read_excursion_e: float,
) -> None:
    # The non-linearity acts on the output signal plus read noise, so check
    # read-noise excursions on both sides of the signal range (never less than
    # the original 5 % upper margin).
    upper = max(1.05 * max_signal_e, max_signal_e + read_excursion_e)
    grid = np.linspace(-read_excursion_e, upper, 8193)
    derivative = np.ones_like(grid)
    for order, coefficient in enumerate(coefficients):
        derivative += (order + 2) * coefficient * grid ** (order + 1)
    if np.any(derivative <= 0.0):
        raise CameraConfigError(
            "nonlinearity_coefficients must give a strictly increasing response "
            "over the camera's output signal range."
        )


def _set(instance: object, name: str, value: object) -> None:
    object.__setattr__(instance, name, value)


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise CameraConfigError(f"{label} must be a real number.")
    result = float(value)
    if not math.isfinite(result):
        raise CameraConfigError(f"{label} must be finite.")
    return result


def _nonnegative(value: object, label: str) -> float:
    result = _finite(value, label)
    if result < 0.0:
        raise CameraConfigError(f"{label} must be non-negative.")
    return result


def _positive(value: object, label: str) -> float:
    result = _finite(value, label)
    if result <= 0.0:
        raise CameraConfigError(f"{label} must be positive.")
    return result


def _fraction(value: object, label: str) -> float:
    result = _finite(value, label)
    if not 0.0 <= result <= 1.0:
        raise CameraConfigError(f"{label} must be in [0, 1].")
    return result


def _integer(value: object, label: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise CameraConfigError(f"{label} must be an integer.")
    result = int(value)
    if result < minimum:
        raise CameraConfigError(f"{label} must be at least {minimum}.")
    return result
