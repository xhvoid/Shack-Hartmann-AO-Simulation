"""Validation-only Fourier (trigonometric-interpolation) encircled energy (T2, G5).

The production estimator (:func:`shwfs_ao.science.metrics.encircled_energy_radius_from_discrete_flux`)
sorts the discrete flux samples by radius, merges equal-radius rings and
interpolates the cumulative flux; its EE50 depends on the angular sampling
(the science ``psf_pad_factor``).  This module provides an independent
reference that does not: it treats the sampled image as **point values** of
a band-limited periodic function (the trigonometric interpolant of the
samples) and integrates that function over a disc in closed form.

Why the interpolant is the right object for the native science PSF
---------------------------------------------------------------------
``NativeSciencePropagator`` zero-pads the ``N x N`` raster pupil field to
``H x H`` (``H = pad * N``), takes a centred FFT and normalizes ``|F|**2`` to
unit sum.  The samples are point values of ``I(theta) = |E(theta)|**2`` on
``theta_k = lambda k / (H delta)``; ``E`` is the Fourier transform of the
*sampled* pupil, a trigonometric polynomial whose frequency content occupies
``N`` consecutive integers per axis (in units of ``1 / P_theta``,
``P_theta = lambda / delta`` the angular period), so ``I`` has content at
``|u|, |v| <= N - 1``.  An ``H x H`` sampling resolves that content exactly
when ``H >= 2N - 1``: for ``pad >= 2`` the interpolant **is** the
continuous-angle intensity of the raster model and the only remaining
approximations relative to a continuous pupil are the pupil raster and the
periodic continuation of the far field (the model's own, not the oracle's).
For an arbitrary image the interpolant is the standard real symmetric one:
the Nyquist coefficient of an even axis is split half and half between
``+H/2`` and ``-H/2`` (cosine interpolation at the Nyquist frequency); an odd
axis has no Nyquist term.

Encircled energy of the interpolant (derivation)
------------------------------------------------
With ``F[u, v] = fft2(I) / (H_y H_x)`` and the sample positions
``theta_x = x0 + l dx``, ``theta_y = y0 + k dy``, the interpolant is
``I(theta) = sum F[u, v] exp(2 pi i (q_u (theta_y - y0) + q_v (theta_x - x0)))``
with ``q_u = u / (H_y dy)``, ``q_v = v / (H_x dx)`` in cycles per radian.  For
a disc of radius ``r`` about ``c`` the integral of one plane wave is
``exp(2 pi i q . (c - origin)) * r J1(2 pi |q| r) / |q|`` (``pi r**2`` for
``q = 0``), so

``EE(r; c) = sum_{u,v} F[u,v] exp(2 pi i q_uv . (c - origin)) r J1(2 pi |q_uv| r) / |q_uv|``.

The whole-field flux of one periodic cell is ``F[0,0] P_x P_y = sum(I) dx dy``,
the same "normalized source grid flux" denominator the production metrics
use.  The encircled-energy fraction is ``EE / (F[0,0] P_x P_y)``.  A disc
must lie inside one periodic cell (``r <= min(P_x, P_y) / 2``): a larger disc
would count a periodic copy of the field again and is refused.  A disc that
leaves the *sampled* field (while inside the cell) integrates the periodic
continuation of the image; that is reported, not hidden.  Inputs with a
non-finite value or a non-positive total are refused.  Interpolation
artefacts (a negative lobe of the interpolant between samples) are reported
through :attr:`FourierEncircledEnergy.artefacts`; nothing is clipped or
renormalized.

Continuous references
---------------------
``airy_encircled_energy`` is Rayleigh's result for the unobstructed circular
aperture, ``EE(v) = 1 - J0(v)**2 - J1(v)**2`` with ``v = pi D theta / lambda``.
``annular_encircled_energy`` integrates the normalized intensity of the
annular aperture with linear obscuration ratio ``epsilon`` (inner over outer
diameter, the repository's ``central_obstruction_ratio``),
``I(v) = [2 J1(v)/v - epsilon**2 2 J1(epsilon v)/(epsilon v)]**2 / (1 - epsilon**2)**2``,
numerically over ``[0, v_c]`` and normalizes by the total over the plane.
These are references for the *continuous* pupil: the raster model differs
from them by its pupil raster and its periodic far field, which this module
reports as separate error budgets rather than as oracle error.

Nothing here is used by :mod:`shwfs_ao.science.metrics`; the production EE50
definition is unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
from typing import Any

import numpy as np
from scipy import integrate, optimize, special


__all__ = (
    "EncircledEnergyError",
    "FourierEncircledEnergy",
    "InterpolantArtefacts",
    "fourier_encircled_energy",
    "airy_encircled_energy",
    "annular_psf_normalized_intensity",
    "annular_encircled_energy",
    "annular_encircled_energy_bessel_form",
    "annular_encircled_energy_radius",
)


NYQUIST_HANDLING = "even axis: Nyquist coefficient split half and half between +H/2 and -H/2"
INPUT_SEMANTICS = (
    "point samples of a periodic band-limited intensity, normalized so that the sum of the "
    "samples is the whole-field flux (not pixel-integrated flux)"
)
_UPSAMPLING = 4


class EncircledEnergyError(ValueError):
    """Raised for an unsupported image, centre, radius or fraction."""


@dataclass(frozen=True)
class InterpolantArtefacts:
    """What the trigonometric interpolant does between the samples.

    ``minimum_value`` is the smallest value of the interpolant on a grid
    ``4x`` finer than the samples (the samples themselves are non-negative);
    ``negative_lobe_fraction`` is the integral of its negative part over one
    periodic cell, as a fraction of the whole-field flux, estimated on that
    fine grid.  Both are zero for an image whose interpolant is non-negative.
    """

    minimum_value: float
    minimum_sample_value: float
    negative_lobe_fraction: float
    upsampling: int

    def to_record(self) -> dict[str, Any]:
        return {
            "minimum_value": self.minimum_value,
            "minimum_sample_value": self.minimum_sample_value,
            "negative_lobe_fraction": self.negative_lobe_fraction,
            "upsampling": self.upsampling,
        }


def _uniform_axis(values: np.ndarray, *, label: str) -> tuple[float, float]:
    axis = np.asarray(values, dtype=float)
    if axis.ndim != 1 or axis.size < 2 or not np.all(np.isfinite(axis)):
        raise EncircledEnergyError(f"{label} must be a finite 1-D axis of at least two samples.")
    steps = np.diff(axis)
    spacing = float(steps[0])
    if spacing <= 0.0 or not np.allclose(steps, spacing, rtol=1.0e-9, atol=0.0):
        raise EncircledEnergyError(f"{label} must be uniform and strictly increasing.")
    return float(axis[0]), spacing


def _extended_spectrum(
    values: np.ndarray, spacing_y: float, spacing_x: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Frequencies (cycles per radian) and coefficients of the real symmetric interpolant.

    Even axes get their Nyquist coefficient split between ``+H/2`` and
    ``-H/2``; the returned coefficient matrix has one extra row and/or column
    for them.
    """

    rows, columns = values.shape
    coefficients = np.fft.fft2(values) / (rows * columns)

    def extend(count: int, spacing: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        frequencies = np.fft.fftfreq(count, d=spacing)
        if count % 2 == 0:
            nyquist = count // 2  # numpy position of the -count/2 index
            weights = np.ones(count + 1)
            weights[nyquist] = 0.5
            weights[count] = 0.5
            extended = np.append(frequencies, -frequencies[nyquist])
            source = np.append(np.arange(count), nyquist)
            return extended, weights, source
        return frequencies, np.ones(count), np.arange(count)

    frequency_y, weight_y, source_y = extend(rows, spacing_y)
    frequency_x, weight_x, source_x = extend(columns, spacing_x)
    extended = coefficients[np.ix_(source_y, source_x)] * np.outer(weight_y, weight_x)
    return frequency_y, frequency_x, extended


@dataclass(frozen=True)
class FourierEncircledEnergy:
    """The trigonometric interpolant of a sampled image and its exact disc integrals.

    Build it with :func:`fourier_encircled_energy`.  ``fraction(r)`` is the
    encircled-energy fraction within radius ``r`` of ``center_xy_rad``;
    ``radius(fraction)`` inverts it; ``value_at`` evaluates the interpolant;
    ``artefacts`` reports its negative lobes.  All angles are radians, all
    frequencies cycles per radian.
    """

    samples: np.ndarray
    x_angle_rad: np.ndarray
    y_angle_rad: np.ndarray
    center_xy_rad: tuple[float, float]
    frequency_x: np.ndarray
    frequency_y: np.ndarray
    coefficients: np.ndarray
    spacing_xy_rad: tuple[float, float]
    period_xy_rad: tuple[float, float]
    whole_field_flux: float
    artefacts: InterpolantArtefacts

    @property
    def max_radius_rad(self) -> float:
        """Largest radius whose disc lies inside one periodic cell."""

        return 0.5 * min(self.period_xy_rad)

    @property
    def sampled_field_edge_distance_rad(self) -> float:
        """Distance from the centre to the nearest edge of the sampled field."""

        x0, dx = float(self.x_angle_rad[0]), self.spacing_xy_rad[0]
        y0, dy = float(self.y_angle_rad[0]), self.spacing_xy_rad[1]
        cx, cy = self.center_xy_rad
        return float(
            min(
                cx - (x0 - 0.5 * dx),
                (x0 + (self.x_angle_rad.size - 0.5) * dx) - cx,
                cy - (y0 - 0.5 * dy),
                (y0 + (self.y_angle_rad.size - 0.5) * dy) - cy,
            )
        )

    def _phases(self, center_xy_rad: tuple[float, float] | None) -> np.ndarray:
        cx, cy = self.center_xy_rad if center_xy_rad is None else center_xy_rad
        shift_x = np.exp(2j * np.pi * self.frequency_x * (cx - float(self.x_angle_rad[0])))
        shift_y = np.exp(2j * np.pi * self.frequency_y * (cy - float(self.y_angle_rad[0])))
        return self.coefficients * np.outer(shift_y, shift_x)

    def encircled_energy(self, radius_rad: float, *, center_xy_rad: tuple[float, float] | None = None) -> float:
        """Flux of the interpolant inside the disc (same unit as ``whole_field_flux``)."""

        radius = _radius(radius_rad, self.max_radius_rad)
        if radius == 0.0:
            return 0.0
        q = np.hypot(self.frequency_y[:, None], self.frequency_x[None, :])
        kernel = np.empty_like(q)
        zero = q == 0.0
        kernel[zero] = math.pi * radius * radius
        argument = 2.0 * math.pi * q[~zero] * radius
        kernel[~zero] = radius * special.j1(argument) / q[~zero]
        total = np.sum(self._phases(center_xy_rad) * kernel)
        return float(total.real)

    def fraction(self, radius_rad: float, *, center_xy_rad: tuple[float, float] | None = None) -> float:
        """Encircled-energy fraction of the whole-field flux inside ``radius_rad``."""

        return self.encircled_energy(radius_rad, center_xy_rad=center_xy_rad) / self.whole_field_flux

    def radius(
        self,
        fraction: float,
        *,
        center_xy_rad: tuple[float, float] | None = None,
        scan_points: int = 64,
    ) -> float:
        """Radius enclosing ``fraction`` of the whole-field flux (``brentq`` on a bracket).

        The fraction at the largest admissible radius must reach the target;
        otherwise the target is unreachable within one periodic cell and the
        call is refused.  ``monotone_fraction_scan`` says whether the fraction
        increased monotonically on a radial scan (an interpolant with negative
        lobes need not be monotone; the root is still the first crossing of
        the bracket found).
        """

        target = _fraction(fraction)
        upper = self.max_radius_rad
        top = self.fraction(upper, center_xy_rad=center_xy_rad)
        if top < target:
            raise EncircledEnergyError(
                f"the fraction {top:.6f} at the largest radius inside one periodic cell "
                f"({upper:.6g} rad) does not reach the target {target}; the encircled-energy "
                "radius is not defined within the field."
            )
        radii = np.linspace(0.0, upper, int(scan_points) + 1)[1:]
        scan = np.array([self.fraction(r, center_xy_rad=center_xy_rad) for r in radii])
        crossing = int(np.argmax(scan >= target))
        low = 0.0 if crossing == 0 else float(radii[crossing - 1])
        high = float(radii[crossing])
        root = optimize.brentq(
            lambda r: self.fraction(r, center_xy_rad=center_xy_rad) - target,
            low if low > 0.0 else 1.0e-6 * high,
            high,
            xtol=1.0e-14 * upper,
            rtol=4.0 * np.finfo(float).eps,
            maxiter=200,
        )
        return float(root)

    def monotone_fraction_scan(self, *, scan_points: int = 64) -> bool:
        radii = np.linspace(0.0, self.max_radius_rad, int(scan_points) + 1)[1:]
        scan = np.array([self.fraction(r) for r in radii])
        return bool(np.all(np.diff(scan) >= -1.0e-12))

    def value_at(self, x_rad: np.ndarray, y_rad: np.ndarray) -> np.ndarray:
        """The interpolant at arbitrary angles (broadcast of ``x_rad`` and ``y_rad``)."""

        x = np.asarray(x_rad, dtype=float)
        y = np.asarray(y_rad, dtype=float)
        shape = np.broadcast(x, y).shape
        x_flat = np.broadcast_to(x, shape).reshape(-1) - float(self.x_angle_rad[0])
        y_flat = np.broadcast_to(y, shape).reshape(-1) - float(self.y_angle_rad[0])
        waves_x = np.exp(2j * np.pi * np.outer(x_flat, self.frequency_x))
        waves_y = np.exp(2j * np.pi * np.outer(y_flat, self.frequency_y))
        values = np.einsum("pu,uv,pv->p", waves_y, self.coefficients, waves_x)
        return values.real.reshape(shape)

    def to_record(self) -> dict[str, Any]:
        return {
            "input_semantics": INPUT_SEMANTICS,
            "nyquist_handling": NYQUIST_HANDLING,
            "angular_unit": "rad",
            "frequency_unit": "cycles_per_rad",
            "shape": [int(size) for size in self.samples.shape],
            "spacing_xy_rad": list(self.spacing_xy_rad),
            "period_xy_rad": list(self.period_xy_rad),
            "center_xy_rad": list(self.center_xy_rad),
            "whole_field_flux": self.whole_field_flux,
            "flux_denominator": "sum of the samples times the sample area (one periodic cell)",
            "max_radius_rad": self.max_radius_rad,
            "sampled_field_edge_distance_rad": self.sampled_field_edge_distance_rad,
            "artefacts": self.artefacts.to_record(),
        }


def _radius(value: object, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise EncircledEnergyError("radius_rad must be a real number.")
    radius = float(value)
    if not math.isfinite(radius) or radius < 0.0:
        raise EncircledEnergyError("radius_rad must be finite and non-negative.")
    if radius > maximum * (1.0 + 1.0e-12):
        raise EncircledEnergyError(
            f"radius {radius:.6g} rad exceeds half the periodic cell ({maximum:.6g} rad); the disc "
            "would overlap a periodic copy of the field."
        )
    return min(radius, maximum)


def _fraction(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise EncircledEnergyError("fraction must be a real number.")
    target = float(value)
    if not math.isfinite(target) or not 0.0 < target < 1.0:
        raise EncircledEnergyError("fraction must lie strictly between 0 and 1.")
    return target


def _artefacts(values: np.ndarray, frequency_y: np.ndarray, frequency_x: np.ndarray, coefficients: np.ndarray, spacing: tuple[float, float], total: float) -> InterpolantArtefacts:
    """Evaluate the interpolant on a ``_UPSAMPLING`` times finer grid by inverse FFT."""

    rows, columns = values.shape
    fine_rows, fine_columns = _UPSAMPLING * rows, _UPSAMPLING * columns
    spectrum = np.zeros((fine_rows, fine_columns), dtype=complex)
    # frequency * spacing * H is the signed cycles-per-period index k, the
    # same index on the finer grid of the same period.
    index_y = np.rint(frequency_y * spacing[1] * rows).astype(int) % fine_rows
    index_x = np.rint(frequency_x * spacing[0] * columns).astype(int) % fine_columns
    # Duplicate (split-Nyquist) positions never collide on the finer grid:
    # +H/2 and -H/2 are distinct indices there, so a plain scatter is exact.
    np.add.at(spectrum, (index_y[:, None], index_x[None, :]), coefficients)
    fine = np.fft.ifft2(spectrum).real * (fine_rows * fine_columns)
    fine_area = (spacing[0] / _UPSAMPLING) * (spacing[1] / _UPSAMPLING)
    negative = float(np.sum(np.minimum(fine, 0.0)) * fine_area)
    return InterpolantArtefacts(
        minimum_value=float(np.min(fine)),
        minimum_sample_value=float(np.min(values)),
        negative_lobe_fraction=-negative / total,
        upsampling=_UPSAMPLING,
    )


def fourier_encircled_energy(
    discrete_pixel_flux: np.ndarray,
    x_angle_rad: np.ndarray,
    y_angle_rad: np.ndarray,
    *,
    center_xy_rad: tuple[float, float] | None = None,
) -> FourierEncircledEnergy:
    """Build the interpolant of a sampled image on a uniform angular grid.

    ``discrete_pixel_flux`` holds the point samples (rows along ``y``, columns
    along ``x``; finite, non-negative sum required); the axes must be uniform
    and strictly increasing.  Without ``center_xy_rad`` the centre is the
    position of the largest sample (the production metrics' peak-pixel
    centring on a uniform grid).
    """

    values = np.asarray(discrete_pixel_flux)
    if values.ndim != 2 or values.dtype.kind not in "fiu" or values.dtype.kind == "b":
        raise EncircledEnergyError("discrete_pixel_flux must be a real 2-D array.")
    samples = np.array(values, dtype=float, copy=True)
    if not np.all(np.isfinite(samples)):
        raise EncircledEnergyError("discrete_pixel_flux must be finite.")
    x0, dx = _uniform_axis(x_angle_rad, label="x_angle_rad")
    y0, dy = _uniform_axis(y_angle_rad, label="y_angle_rad")
    if samples.shape != (np.asarray(y_angle_rad).size, np.asarray(x_angle_rad).size):
        raise EncircledEnergyError("discrete_pixel_flux shape must match (len(y), len(x)).")
    total = float(np.sum(samples)) * dx * dy
    if total <= 0.0:
        raise EncircledEnergyError("discrete_pixel_flux must have a positive total.")
    if center_xy_rad is None:
        row, column = np.unravel_index(int(np.argmax(samples)), samples.shape)
        centre = (float(x0 + column * dx), float(y0 + row * dy))
    else:
        if len(center_xy_rad) != 2:
            raise EncircledEnergyError("center_xy_rad must be an (x, y) pair.")
        centre = (float(center_xy_rad[0]), float(center_xy_rad[1]))
        if not all(math.isfinite(value) for value in centre):
            raise EncircledEnergyError("center_xy_rad must be finite.")
    frequency_y, frequency_x, coefficients = _extended_spectrum(samples, dy, dx)
    rows, columns = samples.shape
    period = (columns * dx, rows * dy)
    artefacts = _artefacts(samples, frequency_y, frequency_x, coefficients, (dx, dy), total)
    return FourierEncircledEnergy(
        samples=samples,
        x_angle_rad=np.array(x_angle_rad, dtype=float),
        y_angle_rad=np.array(y_angle_rad, dtype=float),
        center_xy_rad=centre,
        frequency_x=frequency_x,
        frequency_y=frequency_y,
        coefficients=coefficients,
        spacing_xy_rad=(dx, dy),
        period_xy_rad=period,
        whole_field_flux=total,
        artefacts=artefacts,
    )


# -- continuous references -----------------------------------------------------


def airy_encircled_energy(v: np.ndarray | float) -> np.ndarray | float:
    """Rayleigh's encircled energy of the Airy pattern, ``1 - J0(v)**2 - J1(v)**2``, ``v = pi D theta / lambda``."""

    argument = np.asarray(v, dtype=float)
    if np.any(argument < 0.0) or not np.all(np.isfinite(argument)):
        raise EncircledEnergyError("v must be finite and non-negative.")
    result = 1.0 - special.j0(argument) ** 2 - special.j1(argument) ** 2
    return float(result) if np.ndim(v) == 0 else result


def annular_psf_normalized_intensity(v: np.ndarray | float, obscuration_ratio: float) -> np.ndarray | float:
    """Normalized intensity ``I(v)/I(0)`` of an annular aperture, ``v = pi D theta / lambda``.

    ``obscuration_ratio`` is the linear ratio of inner to outer diameter
    (``epsilon``; 0 gives the Airy pattern).
    """

    epsilon = _ratio(obscuration_ratio)
    argument = np.asarray(v, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        outer = np.where(argument == 0.0, 1.0, 2.0 * special.j1(argument) / np.where(argument == 0.0, 1.0, argument))
        if epsilon > 0.0:
            scaled = epsilon * argument
            inner = np.where(scaled == 0.0, 1.0, 2.0 * special.j1(scaled) / np.where(scaled == 0.0, 1.0, scaled))
        else:
            inner = np.zeros_like(argument)
    field = (outer - epsilon * epsilon * inner) / (1.0 - epsilon * epsilon)
    result = field * field
    return float(result) if np.ndim(v) == 0 else result


def _ratio(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise EncircledEnergyError("obscuration_ratio must be a real number.")
    epsilon = float(value)
    if not 0.0 <= epsilon < 1.0:
        raise EncircledEnergyError("obscuration_ratio must lie in [0, 1).")
    return epsilon


def _radial_integral(obscuration_ratio: float, upper: float) -> float:
    """``integral_0^upper I(v) v dv`` of the normalized annular intensity, piecewise between Bessel zeros."""

    epsilon = _ratio(obscuration_ratio)
    if upper <= 0.0:
        return 0.0
    # Break points at the zeros of J1 keep every piece smooth for quad.
    zeros = special.jn_zeros(1, max(1, int(upper / math.pi) + 2))
    points = [0.0, *[float(z) for z in zeros if z < upper], float(upper)]
    total = 0.0
    for low, high in zip(points, points[1:]):
        value, _ = integrate.quad(
            lambda x: float(annular_psf_normalized_intensity(x, epsilon)) * x,
            low,
            high,
            epsabs=1.0e-14,
            epsrel=1.0e-12,
            limit=200,
        )
        total += value
    return total


def _total_radial_integral(obscuration_ratio: float) -> float:
    """``integral_0^inf I(v) v dv = 2 / (1 - epsilon**2)`` for the normalized annular intensity.

    Expanding the square: ``integral (2 J1(x)/x)**2 x dx = 2``, the inner
    term gives ``eps**4 * 2 / eps**2`` after ``u = eps x``, and the cross term
    ``-2 eps**2 integral (2 J1(x)/x)(2 J1(eps x)/(eps x)) x dx = -8 eps *
    (eps / 2)`` (DLMF 10.22.56), so the sum is ``2 (1 - eps**2)`` and the
    ``(1 - eps**2)**-2`` prefactor leaves ``2 / (1 - eps**2)``; ``eps = 0``
    is Rayleigh's total.  The unit tests check it against
    :func:`annular_encircled_energy_bessel_form`, an independent route.
    """

    epsilon = _ratio(obscuration_ratio)
    return 2.0 / (1.0 - epsilon * epsilon)


def annular_encircled_energy(v: float, obscuration_ratio: float) -> float:
    """Encircled-energy fraction of the annular (``epsilon = inner/outer``) aperture within ``v = pi D theta / lambda``.

    ``integral_0^v I(x) x dx / integral_0^inf I(x) x dx`` with the normalized
    intensity of :func:`annular_psf_normalized_intensity`; the denominator is
    the closed form ``2 / (1 - epsilon**2)`` (Parseval), which the unit tests
    check against the numerical integral.  ``epsilon = 0`` reproduces
    :func:`airy_encircled_energy` to the quadrature tolerance.
    """

    if isinstance(v, bool) or not isinstance(v, Real) or not math.isfinite(float(v)) or float(v) < 0.0:
        raise EncircledEnergyError("v must be finite and non-negative.")
    epsilon = _ratio(obscuration_ratio)
    return _radial_integral(epsilon, float(v)) / _total_radial_integral(epsilon)


def annular_encircled_energy_bessel_form(v: float, obscuration_ratio: float) -> float:
    """The annular encircled energy by Bessel identities: an independent route to the same quantity.

    Expanding the squared field and using Rayleigh's identity
    ``2 integral_0^v J1(x)**2 / x dx = 1 - J0(v)**2 - J1(v)**2`` on both terms gives

    ``EE(v) = [1 - J0(v)**2 - J1(v)**2 + eps**2 (1 - J0(eps v)**2 - J1(eps v)**2)
              - 4 eps integral_0^v J1(x) J1(eps x) / x dx] / (1 - eps**2)``,

    whose ``v -> inf`` limit is one because the cross integral tends to
    ``eps / 2`` (DLMF 10.22.56).  Only the cross term is integrated
    numerically here; :func:`annular_encircled_energy` integrates the
    intensity itself, so the two agree only if both the formula and the
    normalization are right.
    """

    if isinstance(v, bool) or not isinstance(v, Real) or not math.isfinite(float(v)) or float(v) < 0.0:
        raise EncircledEnergyError("v must be finite and non-negative.")
    epsilon = _ratio(obscuration_ratio)
    upper = float(v)
    outer = 1.0 - special.j0(upper) ** 2 - special.j1(upper) ** 2
    if epsilon == 0.0:
        return float(outer)
    inner = 1.0 - special.j0(epsilon * upper) ** 2 - special.j1(epsilon * upper) ** 2
    cross = 0.0
    if upper > 0.0:
        zeros = special.jn_zeros(1, max(1, int(upper / math.pi) + 2))
        points = [0.0, *[float(z) for z in zeros if z < upper], upper]
        for low, high in zip(points, points[1:]):
            value, _ = integrate.quad(
                lambda x: float(special.j1(x) * special.j1(epsilon * x) / x) if x > 0.0 else 0.5 * epsilon,
                low,
                high,
                epsabs=1.0e-14,
                epsrel=1.0e-12,
                limit=200,
            )
            cross += value
    return float((outer + epsilon * epsilon * inner - 4.0 * epsilon * cross) / (1.0 - epsilon * epsilon))


def annular_encircled_energy_radius(fraction: float, obscuration_ratio: float, *, v_max: float = 60.0) -> float:
    """``v`` at which the annular aperture encloses ``fraction`` of its energy."""

    target = _fraction(fraction)
    epsilon = _ratio(obscuration_ratio)
    if annular_encircled_energy(v_max, epsilon) < target:
        raise EncircledEnergyError(f"fraction {target} is not reached within v_max = {v_max}.")
    return float(
        optimize.brentq(lambda x: annular_encircled_energy(x, epsilon) - target, 1.0e-6, v_max, xtol=1.0e-12)
    )
