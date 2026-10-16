"""Source and sky photometry for the physical detector path (DET-02).

Everything here takes plain arrays and scalars in SI units; catalogue rows
and filter curves are loaded elsewhere (``io.public_data``) and passed in.
The model distinguishes three quantities and never relabels one as another:

* incident photons at the detector, after the optical throughput ``T`` (which
  excludes the detector QE);
* detected photoelectrons, after the quantum efficiency ``QE`` -- applied
  here, once;
* normalized detected-electron spectral weights, one per quadrature node, for
  the polychromatic optics.

For a spectral energy flux density ``f_lambda`` (W m^-2 m^-1) collected by an
illuminated area ``A`` (m^2) during an exposure ``t`` (s),

    N_e = A t integral f_lambda T QE lambda / (h c) d lambda ,

evaluated with the :class:`~shwfs_ao.core.spectral.SpectralQuadrature`
nodes.  The incident-photon expression is the same integral without ``QE``.

AB magnitudes follow Oke & Gunn (1983):
``m_AB = -2.5 log10(f_nu / [erg s^-1 cm^-2 Hz^-1]) - 48.60``, i.e. a zero point
``f_nu,0 = 10**(-19.44) erg s^-1 cm^-2 Hz^-1 = 3630.78 Jy`` (the rounded
convention is 3631 Jy).  A source of constant ``f_nu`` across the band has
``f_lambda = f_nu c / lambda**2``.

Sky background is a surface brightness ``mu`` (AB mag arcsec^-2, assumed
constant in ``f_nu`` across the band).  Electrons per pixel per frame are the
same integral with ``A`` the subaperture's illuminated area and an extra
factor of the pixel solid angle in arcsec^2.  Both budgets are pre-window and
pre-PRNU; window capture and photoresponse are applied downstream, once.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real

import numpy as np

from ..core.hashing import component_config_hash
from ..core.spectral import SpectralQuadrature


__all__ = (
    "PLANCK_J_S",
    "SPEED_OF_LIGHT_M_S",
    "AB_ZERO_POINT_FNU_W_M2_HZ",
    "ARCSEC_RAD",
    "PhotometryError",
    "SpectralElectronBudget",
    "ab_magnitude_to_fnu",
    "flat_fnu_flambda",
    "source_electron_budget",
    "sky_electrons_per_pixel",
    "scale_incident_photons",
)


PLANCK_J_S = 6.62607015e-34  # exact (SI 2019)
SPEED_OF_LIGHT_M_S = 299792458.0  # exact
# 10**(-48.60 / 2.5) erg s^-1 cm^-2 Hz^-1; 1 erg s^-1 cm^-2 = 1e-3 W m^-2.
AB_ZERO_POINT_FNU_W_M2_HZ = 10.0 ** (-48.60 / 2.5) * 1.0e-3
ARCSEC_RAD = math.pi / (180.0 * 3600.0)


class PhotometryError(ValueError):
    """Raised when a photometric input is invalid."""


@dataclass(frozen=True)
class SpectralElectronBudget:
    """Pre-window budget of one aperture area for one exposure.

    ``node_detected_e`` holds each quadrature node's nonnegative detected
    electron contribution; ``spectral_weights`` normalizes it to unit sum and
    is what the polychromatic optics use, without re-applying throughput,
    QE or quadrature weights.
    """

    incident_photons: float
    detected_e: float
    node_detected_e: np.ndarray
    spectral_weights: np.ndarray
    wavelength_m: np.ndarray

    @property
    def config_hash(self) -> str:
        return component_config_hash("spectral_electron_budget", self)


def ab_magnitude_to_fnu(magnitude: float) -> float:
    """AB magnitude to ``f_nu`` in W m^-2 Hz^-1."""

    value = _finite(magnitude, "magnitude")
    return AB_ZERO_POINT_FNU_W_M2_HZ * 10.0 ** (-0.4 * value)


def flat_fnu_flambda(fnu_w_m2_hz: float, wavelength_m: np.ndarray) -> np.ndarray:
    """``f_lambda = f_nu c / lambda^2`` for a spectrum flat in ``f_nu``."""

    fnu = _nonnegative(fnu_w_m2_hz, "fnu_w_m2_hz")
    wavelengths = _positive_array(wavelength_m, "wavelength_m")
    return fnu * SPEED_OF_LIGHT_M_S / wavelengths**2


def source_electron_budget(
    quadrature: SpectralQuadrature,
    *,
    flambda_w_m2_m: np.ndarray,
    throughput: np.ndarray | float,
    quantum_efficiency: np.ndarray | float,
    area_m2: float,
    exposure_s: float,
) -> SpectralElectronBudget:
    """Incident photons, detected electrons and spectral weights for one area.

    ``throughput`` excludes the detector QE; ``quantum_efficiency`` is applied
    here and must not be applied again downstream.
    """

    if not isinstance(quadrature, SpectralQuadrature):
        raise PhotometryError("quadrature must be a SpectralQuadrature.")
    nodes = quadrature.wavelength_m
    flux = _node_values(flambda_w_m2_m, nodes, "flambda_w_m2_m", upper=None)
    transmission = _node_values(throughput, nodes, "throughput", upper=1.0)
    qe = _node_values(quantum_efficiency, nodes, "quantum_efficiency", upper=1.0)
    area = _nonnegative(area_m2, "area_m2")
    exposure = _positive(exposure_s, "exposure_s")
    photon_density = flux * nodes / (PLANCK_J_S * SPEED_OF_LIGHT_M_S)
    incident_nodes = area * exposure * quadrature.weight_m * photon_density * transmission
    detected_nodes = incident_nodes * qe
    detected = float(np.sum(detected_nodes, dtype=np.float64))
    if detected > 0.0:
        weights = detected_nodes / detected
    else:
        weights = np.full(nodes.shape, 1.0 / nodes.size)
    return SpectralElectronBudget(
        incident_photons=float(np.sum(incident_nodes, dtype=np.float64)),
        detected_e=detected,
        node_detected_e=_readonly(detected_nodes),
        spectral_weights=_readonly(weights),
        wavelength_m=_readonly(nodes),
    )


def sky_electrons_per_pixel(
    quadrature: SpectralQuadrature,
    *,
    surface_brightness_ab_mag_arcsec2: float,
    pixel_solid_angle_sr: float,
    throughput: np.ndarray | float,
    quantum_efficiency: np.ndarray | float,
    area_m2: float,
    exposure_s: float,
) -> float:
    """Sky photoelectrons per pixel per frame (pre-PRNU)."""

    solid_angle_arcsec2 = _nonnegative(pixel_solid_angle_sr, "pixel_solid_angle_sr") / (
        ARCSEC_RAD**2
    )
    fnu_per_arcsec2 = ab_magnitude_to_fnu(surface_brightness_ab_mag_arcsec2)
    budget = source_electron_budget(
        quadrature,
        flambda_w_m2_m=flat_fnu_flambda(
            fnu_per_arcsec2 * solid_angle_arcsec2, quadrature.wavelength_m
        ),
        throughput=throughput,
        quantum_efficiency=quantum_efficiency,
        area_m2=area_m2,
        exposure_s=exposure_s,
    )
    return budget.detected_e


def scale_incident_photons(
    incident_photons: float,
    quantum_efficiency: float,
) -> float:
    """Detected electrons from a direct incident-photon budget: one QE factor."""

    photons = _nonnegative(incident_photons, "incident_photons")
    qe = _nonnegative(quantum_efficiency, "quantum_efficiency")
    if qe > 1.0:
        raise PhotometryError("quantum_efficiency must not exceed 1.")
    return photons * qe


def _node_values(
    values: np.ndarray | float,
    nodes: np.ndarray,
    label: str,
    *,
    upper: float | None,
) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.ndim == 0:
        array = np.full(nodes.shape, float(array))
    if array.shape != nodes.shape:
        raise PhotometryError(f"{label} must be a scalar or one value per node.")
    if not np.all(np.isfinite(array)) or np.any(array < 0.0):
        raise PhotometryError(f"{label} must be finite and non-negative.")
    if upper is not None and np.any(array > upper):
        raise PhotometryError(f"{label} must not exceed {upper}.")
    return array


def _readonly(values: np.ndarray) -> np.ndarray:
    result = np.array(values, dtype=float, copy=True)
    result.flags.writeable = False
    return result


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise PhotometryError(f"{label} must be a real number.")
    result = float(value)
    if not math.isfinite(result):
        raise PhotometryError(f"{label} must be finite.")
    return result


def _nonnegative(value: object, label: str) -> float:
    result = _finite(value, label)
    if result < 0.0:
        raise PhotometryError(f"{label} must be non-negative.")
    return result


def _positive(value: object, label: str) -> float:
    result = _finite(value, label)
    if result <= 0.0:
        raise PhotometryError(f"{label} must be positive.")
    return result


def _positive_array(values: object, label: str) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if not np.all(np.isfinite(array)) or np.any(array <= 0.0):
        raise PhotometryError(f"{label} must be positive and finite.")
    return array
