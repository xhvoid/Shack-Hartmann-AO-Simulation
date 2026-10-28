"""Backend-neutral wavelength quadrature for wavefront-sensor spectral models.

A :class:`SpectralQuadrature` is a set of wavelength nodes ``lambda_j`` with
quadrature weights ``w_j`` in metres, so that a band integral is

    integral f(lambda) d lambda  ~=  sum_j w_j f(lambda_j).

It owns spectral *sampling* only.  Photometry
(:mod:`shwfs_ao.detector.photometry`) evaluates photon and electron
integrals on these nodes, and the polychromatic Shack--Hartmann optics weight
monochromatic intensities by the detected-electron contribution of each node.
``science.bandpass.ScienceBandpass`` keeps its own frozen scalar-averaging
weights and is deliberately not reused here (its fields and hashes are frozen
by AO-REF-000).

Rules:

``monochromatic``
    One node with weight equal to a declared, positive bandwidth.  It is the
    narrow-band limit of any band rule.
``gauss_legendre``
    ``n`` Gauss--Legendre nodes on ``[lambda_min, lambda_max]``; exact for
    polynomials of degree ``2 n - 1``.  ``n = 1`` places one node at the band
    centre with the full bandwidth.
``midpoint``
    ``n`` equal sub-bands, each represented by its midpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Integral, Real
from typing import Literal

import numpy as np

from .hashing import component_config_hash


__all__ = (
    "SpectralQuadratureError",
    "SpectralRule",
    "SpectralQuadrature",
    "monochromatic_quadrature",
    "gauss_legendre_quadrature",
    "midpoint_quadrature",
)


SpectralRule = Literal["monochromatic", "gauss_legendre", "midpoint"]
_RULES = frozenset({"monochromatic", "gauss_legendre", "midpoint"})


class SpectralQuadratureError(ValueError):
    """Raised when a wavelength quadrature is malformed."""


def _readonly(values: np.ndarray) -> np.ndarray:
    contiguous = np.ascontiguousarray(values, dtype=float)
    return np.frombuffer(contiguous.tobytes(order="C"), dtype=float).reshape(
        contiguous.shape
    )


@dataclass(frozen=True)
class SpectralQuadrature:
    """Immutable wavelength nodes and quadrature weights, both in metres."""

    __hash_schema_id__ = "shwfs_ao.core.SpectralQuadrature.v1"

    rule: SpectralRule
    band_min_m: float
    band_max_m: float
    wavelength_m: np.ndarray
    weight_m: np.ndarray

    def __post_init__(self) -> None:
        if self.rule not in _RULES:
            raise SpectralQuadratureError(
                f"rule must be one of {sorted(_RULES)}; got {self.rule!r}."
            )
        band_min = _positive(self.band_min_m, "band_min_m")
        band_max = _positive(self.band_max_m, "band_max_m")
        if band_max <= band_min:
            raise SpectralQuadratureError("band_max_m must exceed band_min_m.")
        nodes = np.array(self.wavelength_m, dtype=float, copy=True)
        weights = np.array(self.weight_m, dtype=float, copy=True)
        if nodes.ndim != 1 or nodes.size == 0 or weights.shape != nodes.shape:
            raise SpectralQuadratureError(
                "wavelength_m and weight_m must be equal-length non-empty vectors."
            )
        if not (np.all(np.isfinite(nodes)) and np.all(np.isfinite(weights))):
            raise SpectralQuadratureError("nodes and weights must be finite.")
        if np.any(np.diff(nodes) <= 0.0):
            raise SpectralQuadratureError("wavelength_m must be strictly increasing.")
        if np.any(weights <= 0.0):
            raise SpectralQuadratureError("weight_m must be positive.")
        if nodes[0] < band_min or nodes[-1] > band_max:
            raise SpectralQuadratureError("every node must lie inside the band.")
        if self.rule == "monochromatic" and nodes.size != 1:
            raise SpectralQuadratureError("a monochromatic quadrature has one node.")
        object.__setattr__(self, "band_min_m", band_min)
        object.__setattr__(self, "band_max_m", band_max)
        object.__setattr__(self, "wavelength_m", _readonly(nodes))
        object.__setattr__(self, "weight_m", _readonly(weights))

    @property
    def n_samples(self) -> int:
        return int(self.wavelength_m.size)

    @property
    def bandwidth_m(self) -> float:
        return self.band_max_m - self.band_min_m

    @property
    def shortest_wavelength_m(self) -> float:
        return float(self.wavelength_m[0])

    @property
    def config_hash(self) -> str:
        return component_config_hash("core.spectral_quadrature", self)

    def integrate(self, values: np.ndarray) -> float:
        """Return ``sum_j w_j values_j`` for per-node integrand values."""

        array = np.asarray(values, dtype=float)
        if array.shape != self.wavelength_m.shape:
            raise SpectralQuadratureError(
                f"integrand must have shape {self.wavelength_m.shape}."
            )
        return float(np.sum(self.weight_m * array, dtype=np.float64))


def monochromatic_quadrature(
    wavelength_m: float,
    bandwidth_m: float,
) -> SpectralQuadrature:
    """One node at ``wavelength_m`` carrying a declared ``bandwidth_m``."""

    centre = _positive(wavelength_m, "wavelength_m")
    width = _positive(bandwidth_m, "bandwidth_m")
    if width >= 2.0 * centre:
        raise SpectralQuadratureError("bandwidth_m must be below twice the wavelength.")
    return SpectralQuadrature(
        rule="monochromatic",
        band_min_m=centre - 0.5 * width,
        band_max_m=centre + 0.5 * width,
        wavelength_m=np.array([centre]),
        weight_m=np.array([width]),
    )


def gauss_legendre_quadrature(
    band_min_m: float,
    band_max_m: float,
    n_samples: int,
) -> SpectralQuadrature:
    """``n_samples`` Gauss--Legendre nodes on ``[band_min_m, band_max_m]``."""

    low = _positive(band_min_m, "band_min_m")
    high = _positive(band_max_m, "band_max_m")
    count = _count(n_samples)
    if high <= low:
        raise SpectralQuadratureError("band_max_m must exceed band_min_m.")
    unit_nodes, unit_weights = np.polynomial.legendre.leggauss(count)
    half = 0.5 * (high - low)
    centre = 0.5 * (high + low)
    return SpectralQuadrature(
        rule="gauss_legendre",
        band_min_m=low,
        band_max_m=high,
        wavelength_m=centre + half * unit_nodes,
        weight_m=half * unit_weights,
    )


def midpoint_quadrature(
    band_min_m: float,
    band_max_m: float,
    n_samples: int,
) -> SpectralQuadrature:
    """``n_samples`` equal sub-bands represented by their midpoints."""

    low = _positive(band_min_m, "band_min_m")
    high = _positive(band_max_m, "band_max_m")
    count = _count(n_samples)
    if high <= low:
        raise SpectralQuadratureError("band_max_m must exceed band_min_m.")
    width = (high - low) / count
    nodes = low + width * (np.arange(count, dtype=float) + 0.5)
    return SpectralQuadrature(
        rule="midpoint",
        band_min_m=low,
        band_max_m=high,
        wavelength_m=nodes,
        weight_m=np.full(count, width),
    )


def _positive(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise SpectralQuadratureError(f"{label} must be a real number.")
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise SpectralQuadratureError(f"{label} must be positive and finite.")
    return result


def _count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or int(value) < 1:
        raise SpectralQuadratureError("n_samples must be a positive integer.")
    return int(value)
