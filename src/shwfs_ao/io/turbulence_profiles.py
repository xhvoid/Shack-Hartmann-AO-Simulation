"""Packaged multi-layer turbulence profiles and their derived quantities.

A :class:`TurbulenceProfile` is the backend-neutral description of a layered
atmosphere: an integrated Fried parameter and outer scale, plus layers that
split the turbulence strength by Cn2 fraction and carry their own winds.  The
profiles ship as reviewed JSON resources under ``literature_profiles/`` with
structured provenance, and convert into the ``native_layered`` atmosphere block
of a SCAO system profile with :meth:`TurbulenceProfile.to_atmosphere_config`.

The first packaged profile is the ten-layer atmosphere ESO used in its OCTOPUS
end-to-end simulations for the E-ELT Design Reference Mission
(:data:`ESO_ELT_PROFILE_NAME`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
import json
import math
from numbers import Real
from typing import Any, cast

from ..core.provenance import Provenance
from .configs import AtmosphereConfig, AtmosphereLayerConfig
from .resources import read_text_resource


__all__ = (
    "TURBULENCE_PROFILE_SCHEMA_NAME",
    "TURBULENCE_PROFILE_SCHEMA_VERSION",
    "ESO_ELT_PROFILE_NAME",
    "TurbulenceProfileError",
    "TurbulenceLayer",
    "TurbulenceProfile",
    "available_turbulence_profiles",
    "load_turbulence_profile",
    "eso_elt_turbulence_profile",
)

TURBULENCE_PROFILE_SCHEMA_NAME = "shwfs_ao.turbulence_profile"
TURBULENCE_PROFILE_SCHEMA_VERSION = 1
ESO_ELT_PROFILE_NAME = "eso_elt_drm_ten_layer"
"""ESO E-ELT DRM ten-layer OCTOPUS atmosphere (r0 = 0.13 m at 500 nm, L0 = 25 m)."""

_PROFILE_RESOURCES: dict[str, str] = {
    ESO_ELT_PROFILE_NAME: "literature_profiles/eso_elt_drm_ten_layer.json",
}
_ARCSEC_PER_RAD = 180.0 * 3600.0 / math.pi
# A published table may round its fractions; anything further from one than
# this is a transcription error rather than rounding.
_PUBLISHED_SUM_TOLERANCE = 0.01
_ROOT_KEYS = {
    "schema_name",
    "schema_version",
    "profile_name",
    "description",
    "provenance",
    "turbulence",
    "layers",
    "notes",
}
_TURBULENCE_KEYS = {
    "power_spectrum",
    "r0_m",
    "r0_reference_wavelength_m",
    "published_seeing_arcsec",
    "outer_scale_m",
    "inner_scale",
}
_LAYER_KEYS = {"altitude_m", "cn2_fraction", "wind_speed_m_per_s"}


class TurbulenceProfileError(ValueError):
    """Raised when a turbulence profile is malformed or used inconsistently."""


@dataclass(frozen=True)
class TurbulenceLayer:
    """One frozen-flow layer of a :class:`TurbulenceProfile`.

    ``altitude_m`` is the height above the telescope along the line of sight.
    ``cn2_fraction`` is the layer's share of the integrated Cn2.
    ``wind_direction_deg`` is the direction the layer moves toward, measured
    counter-clockwise from +x on the pupil grid (the repository's convention).
    """

    altitude_m: float
    cn2_fraction: float
    wind_speed_m_per_s: float
    wind_direction_deg: float = 0.0

    def __post_init__(self) -> None:
        if _finite(self.altitude_m, "altitude_m") < 0.0:
            raise TurbulenceProfileError("altitude_m must be non-negative.")
        if _finite(self.cn2_fraction, "cn2_fraction") <= 0.0:
            raise TurbulenceProfileError("cn2_fraction must be positive.")
        if _finite(self.wind_speed_m_per_s, "wind_speed_m_per_s") < 0.0:
            raise TurbulenceProfileError("wind_speed_m_per_s must be non-negative.")
        _finite(self.wind_direction_deg, "wind_direction_deg")
        for name in (
            "altitude_m",
            "cn2_fraction",
            "wind_speed_m_per_s",
            "wind_direction_deg",
        ):
            object.__setattr__(self, name, float(getattr(self, name)))

    @property
    def wind_m_per_s(self) -> tuple[float, float]:
        """Wind velocity ``(vx, vy)`` on the pupil grid in metres per second."""

        angle = math.radians(self.wind_direction_deg)
        return (
            self.wind_speed_m_per_s * math.cos(angle),
            self.wind_speed_m_per_s * math.sin(angle),
        )


@dataclass(frozen=True)
class TurbulenceProfile:
    """Layered von Karman atmosphere with normalized Cn2 fractions.

    ``r0_m`` is the integrated Fried parameter at ``r0_reference_wavelength_m``
    and ``zenith_angle_deg``; the layer fractions sum to one, so they divide
    that strength without changing it.  ``published_cn2_fraction_sum`` keeps
    the sum of the fractions as the source printed them, before normalization.
    """

    name: str
    r0_m: float
    r0_reference_wavelength_m: float
    outer_scale_m: float | None
    layers: tuple[TurbulenceLayer, ...]
    provenance: Provenance
    published_cn2_fraction_sum: float = 1.0
    published_seeing_arcsec: float | None = None
    zenith_angle_deg: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise TurbulenceProfileError("name must be a non-empty string.")
        _positive(self.r0_m, "r0_m")
        _positive(self.r0_reference_wavelength_m, "r0_reference_wavelength_m")
        if self.outer_scale_m is not None:
            _positive(self.outer_scale_m, "outer_scale_m")
        if not isinstance(self.layers, tuple) or not self.layers:
            raise TurbulenceProfileError("layers must be a non-empty tuple.")
        if not all(isinstance(layer, TurbulenceLayer) for layer in self.layers):
            raise TurbulenceProfileError("layers must contain TurbulenceLayer values.")
        total = math.fsum(layer.cn2_fraction for layer in self.layers)
        if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1.0e-9):
            raise TurbulenceProfileError(
                f"layer cn2_fraction values must sum to 1; got {total!r}."
            )
        if not isinstance(self.provenance, Provenance):
            raise TurbulenceProfileError("provenance must be a Provenance record.")
        _positive(self.published_cn2_fraction_sum, "published_cn2_fraction_sum")
        if self.published_seeing_arcsec is not None:
            _positive(self.published_seeing_arcsec, "published_seeing_arcsec")
        zenith = _finite(self.zenith_angle_deg, "zenith_angle_deg")
        if not 0.0 <= zenith < 90.0:
            raise TurbulenceProfileError("zenith_angle_deg must be in [0, 90).")

    @property
    def layer_r0_m(self) -> tuple[float, ...]:
        """Each layer's Fried parameter at the reference wavelength.

        Turbulence strengths add as ``r0**(-5/3)``, so a layer holding the
        fraction ``f`` of the integrated Cn2 has ``r0 * f**(-3/5)``.
        """

        return tuple(
            self.r0_m * layer.cn2_fraction ** (-3.0 / 5.0) for layer in self.layers
        )

    def r0_at_wavelength_m(self, wavelength_m: float) -> float:
        """Integrated Fried parameter scaled as ``lambda**(6/5)`` (Fried 1966)."""

        wavelength = _positive(wavelength_m, "wavelength_m")
        return self.r0_m * (wavelength / self.r0_reference_wavelength_m) ** 1.2

    @property
    def seeing_arcsec(self) -> float:
        """Kolmogorov seeing FWHM ``0.98 * lambda / r0`` at the reference wavelength."""

        return 0.98 * self.r0_reference_wavelength_m / self.r0_m * _ARCSEC_PER_RAD

    @property
    def von_karman_seeing_arcsec(self) -> float:
        """Long-exposure FWHM including the outer scale (Tokovinin 2002).

        ``FWHM = FWHM_K * sqrt(1 - 2.183 * (r0/L0)**0.356)``, an approximation
        valid for ``L0/r0`` above about 20.  Equals the Kolmogorov seeing for an
        infinite outer scale.
        """

        if self.outer_scale_m is None:
            return self.seeing_arcsec
        ratio = self.r0_m / self.outer_scale_m
        return self.seeing_arcsec * math.sqrt(1.0 - 2.183 * ratio**0.356)

    @property
    def effective_wind_speed_m_per_s(self) -> float:
        """Turbulence-weighted wind speed ``(sum f_i v_i**(5/3))**(3/5)``."""

        return math.fsum(
            layer.cn2_fraction * layer.wind_speed_m_per_s ** (5.0 / 3.0)
            for layer in self.layers
        ) ** (3.0 / 5.0)

    @property
    def effective_altitude_m(self) -> float:
        """Turbulence-weighted altitude ``(sum f_i h_i**(5/3))**(3/5)``."""

        return math.fsum(
            layer.cn2_fraction * layer.altitude_m ** (5.0 / 3.0)
            for layer in self.layers
        ) ** (3.0 / 5.0)

    @property
    def coherence_time_s(self) -> float:
        """Coherence time ``tau0 = 0.314 r0 / v_eff`` (Roddier 1981)."""

        speed = self.effective_wind_speed_m_per_s
        return math.inf if speed == 0.0 else 0.314 * self.r0_m / speed

    @property
    def isoplanatic_angle_arcsec(self) -> float:
        """Isoplanatic angle ``theta0 = 0.314 r0 / h_eff`` (Roddier 1981)."""

        altitude = self.effective_altitude_m
        if altitude == 0.0:
            return math.inf
        return 0.314 * self.r0_m / altitude * _ARCSEC_PER_RAD

    @property
    def greenwood_frequency_hz(self) -> float:
        """Greenwood frequency ``f_G = 0.4265 v_eff / r0`` (Greenwood 1977)."""

        return 0.4265 * self.effective_wind_speed_m_per_s / self.r0_m

    def with_wind_directions(
        self, directions_deg: float | Sequence[float]
    ) -> TurbulenceProfile:
        """Return a copy with one direction for every layer, or one per layer."""

        if isinstance(directions_deg, Real) and not isinstance(directions_deg, bool):
            directions = (float(directions_deg),) * len(self.layers)
        else:
            directions = tuple(
                float(value) for value in cast(Sequence[float], directions_deg)
            )
        if len(directions) != len(self.layers):
            raise TurbulenceProfileError(
                f"expected {len(self.layers)} wind directions; got {len(directions)}."
            )
        return replace(
            self,
            layers=tuple(
                replace(layer, wind_direction_deg=direction)
                for layer, direction in zip(self.layers, directions)
            ),
        )

    def at_zenith_angle(self, zenith_angle_deg: float) -> TurbulenceProfile:
        """Return the profile seen along a line of sight at a zenith angle.

        The integrated Cn2 along the line of sight grows as ``sec z``, so
        ``r0`` scales as ``cos(z)**(3/5)`` and every layer's range is
        ``altitude * sec z``.  Wind speeds are kept: the pupil-plane wind
        projection depends on the unpublished wind azimuths.
        """

        zenith = _finite(zenith_angle_deg, "zenith_angle_deg")
        if not 0.0 <= zenith < 90.0:
            raise TurbulenceProfileError("zenith_angle_deg must be in [0, 90).")
        # Undo any zenith scaling already applied before applying the new one.
        cos_ratio = math.cos(math.radians(zenith)) / math.cos(
            math.radians(self.zenith_angle_deg)
        )
        return replace(
            self,
            r0_m=self.r0_m * cos_ratio ** (3.0 / 5.0),
            layers=tuple(
                replace(layer, altitude_m=layer.altitude_m / cos_ratio)
                for layer in self.layers
            ),
            zenith_angle_deg=zenith,
        )

    def to_atmosphere_config(self) -> AtmosphereConfig:
        """Return the ``native_layered`` atmosphere block of a SCAO profile."""

        return AtmosphereConfig(
            r0_m=self.r0_m,
            r0_reference_wavelength_m=self.r0_reference_wavelength_m,
            outer_scale_m=self.outer_scale_m,
            wind_m_per_s=(0.0, 0.0),
            target_rms_opd_m=None,
            normalize_rms=False,
            layers=tuple(
                AtmosphereLayerConfig(
                    altitude_m=layer.altitude_m,
                    cn2_fraction=layer.cn2_fraction,
                    wind_m_per_s=layer.wind_m_per_s,
                )
                for layer in self.layers
            ),
        )


def available_turbulence_profiles() -> tuple[str, ...]:
    """Return the names of every packaged turbulence profile."""

    return tuple(_PROFILE_RESOURCES)


def load_turbulence_profile(name: str) -> TurbulenceProfile:
    """Load one packaged turbulence profile by name.

    The published Cn2 fractions are divided by their printed sum, so the
    layers carry exactly the stated integrated ``r0``; the printed sum stays
    available as :attr:`TurbulenceProfile.published_cn2_fraction_sum`.  Every
    layer starts with a wind direction of 0 degrees (+x) because published
    profiles of this kind give speeds only; use
    :meth:`TurbulenceProfile.with_wind_directions` to choose others.
    """

    try:
        logical_name = _PROFILE_RESOURCES[name]
    except (KeyError, TypeError) as exc:
        raise TurbulenceProfileError(
            f"unknown turbulence profile {name!r}; "
            f"available={available_turbulence_profiles()!r}."
        ) from exc
    try:
        record = json.loads(read_text_resource(logical_name))
    except (OSError, ValueError) as exc:
        raise TurbulenceProfileError(
            f"cannot load turbulence profile {name!r}: {exc}"
        ) from exc
    return _profile_from_record(record, expected_name=name)


def eso_elt_turbulence_profile(
    *,
    wind_directions_deg: float | Sequence[float] = 0.0,
    zenith_angle_deg: float = 0.0,
) -> TurbulenceProfile:
    """Return ESO's ten-layer E-ELT DRM atmosphere.

    r0 = 0.13 m at 500 nm, L0 = 25 m, ten layers from 0 to 18.5 km with the
    published fractional Cn2 and wind speeds.  ESO does not publish wind
    directions; they default to 0 degrees (all layers moving toward +x).
    """

    profile = load_turbulence_profile(ESO_ELT_PROFILE_NAME)
    profile = profile.with_wind_directions(wind_directions_deg)
    if zenith_angle_deg != 0.0:
        profile = profile.at_zenith_angle(zenith_angle_deg)
    return profile


def _profile_from_record(
    record: object, *, expected_name: str
) -> TurbulenceProfile:
    root = _mapping(record, "turbulence profile")
    _exact_keys(root, _ROOT_KEYS, "turbulence profile")
    if root["schema_name"] != TURBULENCE_PROFILE_SCHEMA_NAME:
        raise TurbulenceProfileError(
            f"schema_name must be {TURBULENCE_PROFILE_SCHEMA_NAME!r}."
        )
    if root["schema_version"] != TURBULENCE_PROFILE_SCHEMA_VERSION:
        raise TurbulenceProfileError(
            f"unsupported turbulence profile schema_version={root['schema_version']!r}."
        )
    if root["profile_name"] != expected_name:
        raise TurbulenceProfileError(
            "turbulence profile resource identity does not match its name."
        )
    turbulence = _mapping(root["turbulence"], "turbulence")
    _exact_keys(turbulence, _TURBULENCE_KEYS, "turbulence")
    if turbulence["power_spectrum"] != "von_karman":
        raise TurbulenceProfileError("only von_karman turbulence profiles are supported.")
    raw_layers = root["layers"]
    if not isinstance(raw_layers, list) or not raw_layers:
        raise TurbulenceProfileError("layers must be a non-empty list.")
    parsed = []
    for index, item in enumerate(raw_layers):
        layer = _mapping(item, f"layers[{index}]")
        _exact_keys(layer, _LAYER_KEYS, f"layers[{index}]")
        parsed.append(
            (
                _finite(layer["altitude_m"], f"layers[{index}].altitude_m"),
                _positive(layer["cn2_fraction"], f"layers[{index}].cn2_fraction"),
                _finite(
                    layer["wind_speed_m_per_s"],
                    f"layers[{index}].wind_speed_m_per_s",
                ),
            )
        )
    published_sum = math.fsum(fraction for _, fraction, _ in parsed)
    if abs(published_sum - 1.0) > _PUBLISHED_SUM_TOLERANCE:
        raise TurbulenceProfileError(
            f"published cn2_fraction values sum to {published_sum!r}; that is "
            "not a rounded normalized profile."
        )
    try:
        provenance = Provenance.from_record(_mapping(root["provenance"], "provenance"))
    except ValueError as exc:
        raise TurbulenceProfileError(f"invalid profile provenance: {exc}") from exc
    outer_scale = turbulence["outer_scale_m"]
    seeing = turbulence["published_seeing_arcsec"]
    return TurbulenceProfile(
        name=expected_name,
        r0_m=_positive(turbulence["r0_m"], "turbulence.r0_m"),
        r0_reference_wavelength_m=_positive(
            turbulence["r0_reference_wavelength_m"],
            "turbulence.r0_reference_wavelength_m",
        ),
        outer_scale_m=(
            None
            if outer_scale is None
            else _positive(outer_scale, "turbulence.outer_scale_m")
        ),
        layers=tuple(
            TurbulenceLayer(
                altitude_m=altitude,
                cn2_fraction=fraction / published_sum,
                wind_speed_m_per_s=speed,
            )
            for altitude, fraction, speed in parsed
        ),
        provenance=provenance,
        published_cn2_fraction_sum=published_sum,
        published_seeing_arcsec=(
            None
            if seeing is None
            else _positive(seeing, "turbulence.published_seeing_arcsec")
        ),
    )


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise TurbulenceProfileError(f"{label} must be a string-keyed mapping.")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing or unknown:
        raise TurbulenceProfileError(
            f"{label} fields mismatch; missing={missing}, unknown={unknown}."
        )


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TurbulenceProfileError(f"{label} must be a finite real number.")
    result = float(value)
    if not math.isfinite(result):
        raise TurbulenceProfileError(f"{label} must be finite.")
    return result


def _positive(value: object, label: str) -> float:
    result = _finite(value, label)
    if result <= 0.0:
        raise TurbulenceProfileError(f"{label} must be positive.")
    return result
