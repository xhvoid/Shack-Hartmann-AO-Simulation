"""Scalar science metrics on explicit physical angular grids.

``PsfResult.intensity`` is *discrete pixel flux*: summing its samples gives
the total flux.  It is not angular surface brightness when pixels have
different solid angles.  The public function names below make that distinction
explicit.  Encircled energy and halo fractions integrate discrete flux;
peak Strehl and FWHM evaluate angular surface brightness obtained by dividing
by the pixel solid angle.

Band averaging in this module averages already-computed scalar metrics only.
It never stacks or coadds monochromatic PSF arrays; a broadband image requires
explicit flux-conserving resampling onto a common angular grid.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
import math
from typing import Literal, Sequence

import numpy as np

from ..core import PsfResult
from ..core.geometry import PupilGeometry
from ..core import wavefront as _wavefront


ARCSEC_PER_RAD = 206264.80624709636
_TWO_PI = 2.0 * math.pi
_DISCRETE_FLUX = "discrete_pixel_flux"
_SURFACE_BRIGHTNESS = "angular_surface_brightness_per_sr"
_MONOCHROMATIC = "monochromatic"
_WEIGHTED_SCALARS = "weighted_scalar_average"

__all__ = (
    "ScienceMetricsError",
    "PsfScalarMetrics",
    "discrete_flux_to_angular_surface_brightness",
    "peak_strehl_from_discrete_flux",
    "marechal_strehl_from_opd",
    "fwhm_diameter_from_angular_surface_brightness",
    "encircled_energy_radius_from_discrete_flux",
    "halo_fraction_from_discrete_flux",
    "psf_scalar_metrics",
    "band_average_scalar_metrics",
    "lambda_over_d_rad",
    "radians_to_lambda_over_d",
    "radians_to_arcsec",
)


class ScienceMetricsError(ValueError):
    """Raised when a science metric receives invalid physical data."""


@dataclass(frozen=True)
class PsfScalarMetrics:
    """Frozen monochromatic or scalar-band summary of a science PSF.

    ``wavelength_m`` is the monochromatic wavelength for an unaveraged result
    and the normalized-weight effective wavelength for a band result.  Values
    carrying ``lambda_over_d`` are averaged as scalars for a band; they must
    not be reconstructed from the averaged radian value and effective
    wavelength.
    """

    wavelength_m: float
    telescope_diameter_m: float
    opd_rms_m: float
    peak_strehl: float
    marechal_strehl: float
    marechal_abs_difference: float
    fwhm_rad: float
    fwhm_lambda_over_d: float
    fwhm_arcsec: float
    ee50_rad: float
    ee50_lambda_over_d: float
    ee50_arcsec: float
    ee80_rad: float
    ee80_lambda_over_d: float
    ee80_arcsec: float
    halo_fraction: float
    halo_inner_radius_rad: float
    halo_inner_lambda_over_d: float
    flux_semantics: Literal["discrete_pixel_flux"] = _DISCRETE_FLUX
    fwhm_semantics: Literal["angular_surface_brightness_per_sr"] = (
        _SURFACE_BRIGHTNESS
    )
    aggregation: Literal["monochromatic", "weighted_scalar_average"] = (
        _MONOCHROMATIC
    )

    def __post_init__(self) -> None:
        wavelength_m = _positive_scalar(self.wavelength_m, label="wavelength_m")
        telescope_diameter_m = _positive_scalar(
            self.telescope_diameter_m,
            label="telescope_diameter_m",
        )
        object.__setattr__(self, "wavelength_m", wavelength_m)
        object.__setattr__(
            self,
            "telescope_diameter_m",
            telescope_diameter_m,
        )
        for name in (
            "opd_rms_m",
            "peak_strehl",
            "marechal_strehl",
            "marechal_abs_difference",
            "fwhm_rad",
            "fwhm_lambda_over_d",
            "fwhm_arcsec",
            "ee50_rad",
            "ee50_lambda_over_d",
            "ee50_arcsec",
            "ee80_rad",
            "ee80_lambda_over_d",
            "ee80_arcsec",
            "halo_fraction",
            "halo_inner_radius_rad",
            "halo_inner_lambda_over_d",
        ):
            object.__setattr__(
                self,
                name,
                _nonnegative_scalar(getattr(self, name), label=name),
            )
        if self.marechal_strehl > 1.0:
            raise ScienceMetricsError("marechal_strehl must be at most one.")
        if self.halo_fraction > 1.0:
            raise ScienceMetricsError("halo_fraction must be at most one.")
        if self.ee50_rad > self.ee80_rad:
            raise ScienceMetricsError("ee50_rad must not exceed ee80_rad.")
        if self.ee50_lambda_over_d > self.ee80_lambda_over_d:
            raise ScienceMetricsError(
                "ee50_lambda_over_d must not exceed ee80_lambda_over_d."
            )
        if self.ee50_arcsec > self.ee80_arcsec:
            raise ScienceMetricsError("ee50_arcsec must not exceed ee80_arcsec.")
        if self.flux_semantics != _DISCRETE_FLUX:
            raise ScienceMetricsError(
                f"flux_semantics must be {_DISCRETE_FLUX!r}."
            )
        if self.fwhm_semantics != _SURFACE_BRIGHTNESS:
            raise ScienceMetricsError(
                f"fwhm_semantics must be {_SURFACE_BRIGHTNESS!r}."
            )
        if self.aggregation not in {_MONOCHROMATIC, _WEIGHTED_SCALARS}:
            raise ScienceMetricsError(
                "aggregation must be 'monochromatic' or "
                "'weighted_scalar_average'."
            )

        _require_metric_relation(
            self.fwhm_arcsec,
            self.fwhm_rad * ARCSEC_PER_RAD,
            label="fwhm_arcsec must equal fwhm_rad converted to arcseconds",
        )
        _require_metric_relation(
            self.ee50_arcsec,
            self.ee50_rad * ARCSEC_PER_RAD,
            label="ee50_arcsec must equal ee50_rad converted to arcseconds",
        )
        _require_metric_relation(
            self.ee80_arcsec,
            self.ee80_rad * ARCSEC_PER_RAD,
            label="ee80_arcsec must equal ee80_rad converted to arcseconds",
        )
        diffraction_angle = wavelength_m / telescope_diameter_m
        _require_metric_relation(
            self.halo_inner_radius_rad,
            self.halo_inner_lambda_over_d * diffraction_angle,
            label=(
                "halo_inner_radius_rad must equal halo_inner_lambda_over_d "
                "times wavelength_m/telescope_diameter_m"
            ),
        )
        if self.aggregation == _MONOCHROMATIC:
            for rad_name, lambda_over_d_name in (
                ("fwhm_rad", "fwhm_lambda_over_d"),
                ("ee50_rad", "ee50_lambda_over_d"),
                ("ee80_rad", "ee80_lambda_over_d"),
            ):
                _require_metric_relation(
                    getattr(self, lambda_over_d_name),
                    getattr(self, rad_name) / diffraction_angle,
                    label=(
                        f"{lambda_over_d_name} must equal {rad_name} converted "
                        "using wavelength_m/telescope_diameter_m"
                    ),
                )
            _require_metric_relation(
                self.marechal_abs_difference,
                abs(self.peak_strehl - self.marechal_strehl),
                label=(
                    "marechal_abs_difference must equal the absolute difference "
                    "between peak_strehl and marechal_strehl"
                ),
            )


def discrete_flux_to_angular_surface_brightness(psf: PsfResult) -> np.ndarray:
    """Convert unit-total discrete pixel flux to brightness per steradian.

    Pixel solid angles come from cell boundaries halfway between adjacent
    physical axis coordinates.  The two edge cells use the nearest interior
    spacing.  This convention is valid for irregular rectangular grids and
    makes no pixel-index scale assumption.
    """

    result = _require_psf_result(psf, label="psf")
    flux, x_axis, y_axis = _validated_grid(
        result.intensity,
        result.x_angle_rad,
        result.y_angle_rad,
        data_label="psf.intensity",
    )
    brightness = _surface_brightness_from_flux_grid(flux, x_axis, y_axis)
    return _immutable_float_array(brightness)


def peak_strehl_from_discrete_flux(
    psf: PsfResult,
    ideal_psf: PsfResult,
) -> float:
    """Return peak Strehl from two discrete-flux PSFs on one exact grid.

    Inputs are discrete pixel flux, but their peaks are evaluated after
    conversion to angular surface brightness.  This is equivalent to the
    historical pixel-flux ratio on a uniform grid and remains physical when
    cell areas vary.  Mismatched grids are rejected instead of silently
    comparing wavelength-dependent pixels.
    """

    science = _require_psf_result(psf, label="psf")
    ideal = _require_psf_result(ideal_psf, label="ideal_psf")
    _require_common_psf_grid(science, ideal)
    solid_angle = _pixel_solid_angles(
        science.x_angle_rad,
        science.y_angle_rad,
    )
    return _peak_strehl_from_discrete_flux_arrays(
        science.intensity,
        ideal.intensity,
        pixel_solid_angle_sr=solid_angle,
    )


def _peak_strehl_from_discrete_flux_arrays(
    discrete_pixel_flux: np.ndarray,
    ideal_discrete_pixel_flux: np.ndarray,
    *,
    pixel_solid_angle_sr: np.ndarray | float = 1.0,
) -> float:
    """Private array adapter shared with the frozen uniform-grid facade."""

    science = np.asarray(discrete_pixel_flux)
    ideal = np.asarray(ideal_discrete_pixel_flux)
    if science.ndim != 2 or ideal.shape != science.shape:
        raise ScienceMetricsError(
            "science and ideal discrete flux must be matching 2-D arrays."
        )
    for values, label in ((science, "science"), (ideal, "ideal")):
        if (
            np.issubdtype(values.dtype, np.bool_)
            or not np.issubdtype(values.dtype, np.number)
            or np.issubdtype(values.dtype, np.complexfloating)
        ):
            raise ScienceMetricsError(f"{label} discrete flux must be real numeric.")
        if not np.all(np.isfinite(values)) or np.any(values < 0.0):
            raise ScienceMetricsError(
                f"{label} discrete flux must be finite and non-negative."
            )
    solid_angle = np.asarray(pixel_solid_angle_sr, dtype=float)
    if solid_angle.shape not in {(), science.shape}:
        raise ScienceMetricsError(
            "pixel_solid_angle_sr must be scalar or match the flux arrays."
        )
    if not np.all(np.isfinite(solid_angle)) or np.any(solid_angle <= 0.0):
        raise ScienceMetricsError(
            "pixel_solid_angle_sr must be finite and strictly positive."
        )
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        science_brightness = np.asarray(science, dtype=float) / solid_angle
        ideal_brightness = np.asarray(ideal, dtype=float) / solid_angle
    if not np.all(np.isfinite(science_brightness)) or not np.all(
        np.isfinite(ideal_brightness)
    ):
        raise ScienceMetricsError(
            "discrete flux and pixel solid angle must define finite surface "
            "brightness."
        )
    peak_ideal = float(np.max(ideal_brightness))
    if peak_ideal <= 0.0:
        raise ScienceMetricsError(
            "ideal PSF must have positive peak angular surface brightness."
        )
    value = float(np.max(science_brightness) / peak_ideal)
    return _nonnegative_scalar(value, label="peak Strehl")


def marechal_strehl_from_opd(
    opd_m: np.ndarray,
    pupil: np.ndarray,
    wavelength_m: float,
) -> float:
    """Return ``exp(-(2*pi*sigma_opd/lambda)**2)`` for residual OPD metres.

    Piston is removed over the illuminated pupil.  The input is residual OPD,
    not WFS phase, so the science wavelength is always applied explicitly.
    """

    wavelength = _positive_scalar(wavelength_m, label="wavelength_m")
    _, opd_rms = _validated_opd_and_rms(opd_m, pupil)
    phase_rms = _TWO_PI * opd_rms / wavelength
    return float(math.exp(-(phase_rms**2)))


def fwhm_diameter_from_angular_surface_brightness(
    angular_surface_brightness_per_sr: np.ndarray,
    x_angle_rad: np.ndarray,
    y_angle_rad: np.ndarray,
    *,
    center_angle_rad: tuple[float, float] | None = None,
) -> float:
    """Return radial-profile FWHM in radians from angular surface brightness.

    The radial profile is area-weighted in annuli whose width is the smallest
    physical angular-axis interval.  Only occupied annuli participate in the
    half-maximum interpolation, which keeps the definition valid for
    irregular and non-square angular grids.
    """

    brightness, x_axis, y_axis = _validated_grid(
        angular_surface_brightness_per_sr,
        x_angle_rad,
        y_angle_rad,
        data_label="angular_surface_brightness_per_sr",
    )
    center_x, center_y = _metric_center(
        brightness,
        x_axis,
        y_axis,
        center_angle_rad=center_angle_rad,
    )
    bin_width = float(min(np.min(np.diff(x_axis)), np.min(np.diff(y_axis))))
    y_grid, x_grid = np.meshgrid(y_axis, x_axis, indexing="ij")
    radius = np.hypot(x_grid - center_x, y_grid - center_y)
    bin_index = np.floor(radius / bin_width + 1.0e-12).astype(np.int64)
    solid_angle = _pixel_solid_angles(x_axis, y_axis)

    occupied = np.unique(bin_index)
    radii = occupied.astype(float) * bin_width
    profile = np.empty(occupied.size, dtype=float)
    for output_index, annulus in enumerate(occupied):
        selected = bin_index == annulus
        area = float(np.sum(solid_angle[selected]))
        profile[output_index] = float(
            np.sum(brightness[selected] * solid_angle[selected]) / area
        )

    peak = float(profile[0])
    if peak <= 0.0:
        raise ScienceMetricsError(
            "angular surface-brightness radial profile must have a positive peak."
        )
    below = np.flatnonzero(profile <= 0.5 * peak)
    below = below[below > 0]
    if below.size == 0:
        raise ScienceMetricsError(
            "angular surface-brightness profile never falls below half maximum."
        )
    upper_index = int(below[0])
    lower_index = upper_index - 1
    radius_half = _linear_crossing(
        radii[lower_index],
        profile[lower_index],
        radii[upper_index],
        profile[upper_index],
        0.5 * peak,
    )
    return float(2.0 * radius_half)


def encircled_energy_radius_from_discrete_flux(
    discrete_pixel_flux: np.ndarray,
    x_angle_rad: np.ndarray,
    y_angle_rad: np.ndarray,
    fraction: float,
    *,
    center_angle_rad: tuple[float, float] | None = None,
) -> float:
    """Return a physical encircled-energy radius for discrete pixel flux."""

    return _encircled_energy_radius_from_discrete_flux(
        discrete_pixel_flux,
        x_angle_rad,
        y_angle_rad,
        fraction,
        center_angle_rad=center_angle_rad,
        sort_kind="stable",
    )


def _encircled_energy_radius_from_discrete_flux(
    discrete_pixel_flux: np.ndarray,
    x_angle_rad: np.ndarray,
    y_angle_rad: np.ndarray,
    fraction: float,
    *,
    center_angle_rad: tuple[float, float] | None = None,
    sort_kind: str,
) -> float:
    """Return a physical encircled-energy radius for discrete pixel flux.

    Flux samples are sorted by their angular distance from the supplied center
    (or the maximum-surface-brightness pixel derived from the flux and cell
    areas).  The radius is interpolated in cumulative flux, never converted
    from a pixel-index radius.
    """

    flux, x_axis, y_axis = _validated_grid(
        discrete_pixel_flux,
        x_angle_rad,
        y_angle_rad,
        data_label="discrete_pixel_flux",
    )
    target = _positive_scalar(fraction, label="fraction")
    if target > 1.0:
        raise ScienceMetricsError("fraction must be at most one.")
    center_x, center_y = _metric_center(
        _surface_brightness_from_flux_grid(flux, x_axis, y_axis),
        x_axis,
        y_axis,
        center_angle_rad=center_angle_rad,
    )
    if sort_kind == "legacy_quicksort":
        x_spacing = float(np.median(np.diff(x_axis)))
        y_spacing = float(np.median(np.diff(y_axis)))
        if not np.allclose(np.diff(x_axis), x_spacing, rtol=1.0e-12, atol=0.0):
            raise ScienceMetricsError(
                "legacy_quicksort requires a uniform x angular axis."
            )
        if not np.allclose(np.diff(y_axis), y_spacing, rtol=1.0e-12, atol=0.0):
            raise ScienceMetricsError(
                "legacy_quicksort requires a uniform y angular axis."
            )
        if not math.isclose(x_spacing, y_spacing, rel_tol=1.0e-12, abs_tol=0.0):
            raise ScienceMetricsError(
                "legacy_quicksort requires equal x and y angular sampling."
            )
        # Reconstruct integer pixel offsets from the physical axes.  This
        # private compatibility policy preserves NumPy's historical tied-
        # radius quicksort ordering without making the public metric infer an
        # angular scale from raw array indices.
        x_offsets = np.rint((x_axis - center_x) / x_spacing)
        y_offsets = np.rint((y_axis - center_y) / y_spacing)
        y_grid, x_grid = np.meshgrid(y_offsets, x_offsets, indexing="ij")
        radius = (np.hypot(x_grid, y_grid) * x_spacing).ravel()
    else:
        y_grid, x_grid = np.meshgrid(y_axis, x_axis, indexing="ij")
        radius = np.hypot(x_grid - center_x, y_grid - center_y).ravel()
    values = flux.ravel()
    if sort_kind not in {"stable", "quicksort", "legacy_quicksort"}:
        raise ScienceMetricsError(
            "sort_kind must be 'stable', 'quicksort', or 'legacy_quicksort'."
        )
    numpy_sort_kind = "quicksort" if sort_kind == "legacy_quicksort" else sort_kind
    order = np.argsort(radius, kind=numpy_sort_kind)
    radius_sorted = radius[order]
    cumulative = np.cumsum(values[order])
    total = float(cumulative[-1])
    if total <= 0.0:
        raise ScienceMetricsError("discrete_pixel_flux must have positive flux.")
    cumulative /= total
    index = int(np.searchsorted(cumulative, target, side="left"))
    if index <= 0:
        return float(radius_sorted[0])
    if index >= radius_sorted.size:
        return float(radius_sorted[-1])
    return _linear_crossing(
        float(radius_sorted[index - 1]),
        float(cumulative[index - 1]),
        float(radius_sorted[index]),
        float(cumulative[index]),
        target,
    )


def halo_fraction_from_discrete_flux(
    discrete_pixel_flux: np.ndarray,
    x_angle_rad: np.ndarray,
    y_angle_rad: np.ndarray,
    inner_radius_rad: float,
    *,
    center_angle_rad: tuple[float, float] | None = None,
) -> float:
    """Return discrete flux at or outside a physical angular radius."""

    flux, x_axis, y_axis = _validated_grid(
        discrete_pixel_flux,
        x_angle_rad,
        y_angle_rad,
        data_label="discrete_pixel_flux",
    )
    inner_radius = _nonnegative_scalar(
        inner_radius_rad,
        label="inner_radius_rad",
    )
    center_x, center_y = _metric_center(
        _surface_brightness_from_flux_grid(flux, x_axis, y_axis),
        x_axis,
        y_axis,
        center_angle_rad=center_angle_rad,
    )
    y_grid, x_grid = np.meshgrid(y_axis, x_axis, indexing="ij")
    radius = np.hypot(x_grid - center_x, y_grid - center_y)
    total = float(np.sum(flux))
    if total <= 0.0:
        raise ScienceMetricsError("discrete_pixel_flux must have positive flux.")
    fraction = float(np.sum(flux[radius >= inner_radius]) / total)
    if not 0.0 <= fraction <= 1.0 + 1.0e-15:
        raise ScienceMetricsError("computed halo fraction is outside [0, 1].")
    return float(min(fraction, 1.0))


def psf_scalar_metrics(
    psf: PsfResult,
    ideal_psf: PsfResult,
    residual_opd_m: np.ndarray,
    pupil: PupilGeometry | np.ndarray,
    telescope_diameter_m: float,
    *,
    halo_inner_lambda_over_d: float = 3.0,
) -> PsfScalarMetrics:
    """Compute canonical scalar metrics for one monochromatic science PSF.

    The PSF intensity is supplied as discrete pixel flux.  Peak Strehl and
    FWHM evaluate angular surface brightness after division by physical pixel
    solid angle; encircled energy and halo fraction integrate the discrete
    flux.  Residual OPD is supplied in metres and converted to phase at
    ``psf.wavelength_m`` for the Marechal approximation.
    """

    science = _require_psf_result(psf, label="psf")
    ideal = _require_psf_result(ideal_psf, label="ideal_psf")
    diameter = _positive_scalar(
        telescope_diameter_m,
        label="telescope_diameter_m",
    )
    halo_lod = _nonnegative_scalar(
        halo_inner_lambda_over_d,
        label="halo_inner_lambda_over_d",
    )
    pupil_mask = _pupil_mask_for_psf(
        pupil,
        science,
        telescope_diameter_m=diameter,
    )
    _, opd_rms = _validated_opd_and_rms(residual_opd_m, pupil_mask)
    peak_strehl = peak_strehl_from_discrete_flux(science, ideal)
    marechal = marechal_strehl_from_opd(
        residual_opd_m,
        pupil_mask,
        science.wavelength_m,
    )
    brightness = discrete_flux_to_angular_surface_brightness(science)
    fwhm_rad = fwhm_diameter_from_angular_surface_brightness(
        brightness,
        science.x_angle_rad,
        science.y_angle_rad,
    )
    ee50_rad = encircled_energy_radius_from_discrete_flux(
        science.intensity,
        science.x_angle_rad,
        science.y_angle_rad,
        0.50,
    )
    ee80_rad = encircled_energy_radius_from_discrete_flux(
        science.intensity,
        science.x_angle_rad,
        science.y_angle_rad,
        0.80,
    )
    lod_rad = lambda_over_d_rad(science.wavelength_m, diameter)
    halo_inner_rad = halo_lod * lod_rad
    halo_fraction = halo_fraction_from_discrete_flux(
        science.intensity,
        science.x_angle_rad,
        science.y_angle_rad,
        halo_inner_rad,
    )
    return PsfScalarMetrics(
        wavelength_m=science.wavelength_m,
        telescope_diameter_m=diameter,
        opd_rms_m=opd_rms,
        peak_strehl=peak_strehl,
        marechal_strehl=marechal,
        marechal_abs_difference=abs(peak_strehl - marechal),
        fwhm_rad=fwhm_rad,
        fwhm_lambda_over_d=radians_to_lambda_over_d(
            fwhm_rad,
            science.wavelength_m,
            diameter,
        ),
        fwhm_arcsec=radians_to_arcsec(fwhm_rad),
        ee50_rad=ee50_rad,
        ee50_lambda_over_d=radians_to_lambda_over_d(
            ee50_rad,
            science.wavelength_m,
            diameter,
        ),
        ee50_arcsec=radians_to_arcsec(ee50_rad),
        ee80_rad=ee80_rad,
        ee80_lambda_over_d=radians_to_lambda_over_d(
            ee80_rad,
            science.wavelength_m,
            diameter,
        ),
        ee80_arcsec=radians_to_arcsec(ee80_rad),
        halo_fraction=halo_fraction,
        halo_inner_radius_rad=halo_inner_rad,
        halo_inner_lambda_over_d=halo_lod,
    )


def band_average_scalar_metrics(
    metrics: Sequence[PsfScalarMetrics],
    weights: Sequence[float] | np.ndarray,
) -> PsfScalarMetrics:
    """Return a normalized weighted average of scalar metrics only.

    All inputs must be monochromatic results with one telescope diameter, halo
    aperture, and semantic convention.  This function deliberately accepts no
    PSF image arrays and therefore cannot be mistaken for broadband coaddition.
    """

    rows = tuple(metrics)
    if not rows:
        raise ScienceMetricsError("metrics must contain at least one result.")
    if not all(isinstance(row, PsfScalarMetrics) for row in rows):
        raise ScienceMetricsError("metrics must contain only PsfScalarMetrics.")
    weight_array = np.asarray(weights)
    if (
        weight_array.ndim != 1
        or weight_array.size != len(rows)
        or np.issubdtype(weight_array.dtype, np.bool_)
        or not np.issubdtype(weight_array.dtype, np.number)
        or np.issubdtype(weight_array.dtype, np.complexfloating)
    ):
        raise ScienceMetricsError(
            "weights must be a one-dimensional real vector matching metrics."
        )
    normalized = np.asarray(weight_array, dtype=float)
    if not np.all(np.isfinite(normalized)) or np.any(normalized < 0.0):
        raise ScienceMetricsError("weights must be finite and non-negative.")
    total = float(np.sum(normalized))
    if not math.isfinite(total) or total <= 0.0:
        raise ScienceMetricsError("weights must have positive total weight.")
    normalized = normalized / total

    first = rows[0]
    for row in rows:
        if row.aggregation != _MONOCHROMATIC:
            raise ScienceMetricsError(
                "band averaging requires monochromatic scalar inputs."
            )
        if row.telescope_diameter_m != first.telescope_diameter_m:
            raise ScienceMetricsError(
                "band metrics must use one telescope_diameter_m."
            )
        if row.halo_inner_lambda_over_d != first.halo_inner_lambda_over_d:
            raise ScienceMetricsError(
                "band metrics must use one halo_inner_lambda_over_d aperture."
            )
        if row.flux_semantics != first.flux_semantics:
            raise ScienceMetricsError("band metrics have mixed flux semantics.")
        if row.fwhm_semantics != first.fwhm_semantics:
            raise ScienceMetricsError("band metrics have mixed FWHM semantics.")

    scalar_names = tuple(
        field.name
        for field in fields(PsfScalarMetrics)
        if field.name
        not in {
            "telescope_diameter_m",
            "halo_inner_lambda_over_d",
            "flux_semantics",
            "fwhm_semantics",
            "aggregation",
        }
    )
    averaged = _weighted_scalar_fields(rows, normalized, scalar_names)
    return PsfScalarMetrics(
        **averaged,
        telescope_diameter_m=first.telescope_diameter_m,
        halo_inner_lambda_over_d=first.halo_inner_lambda_over_d,
        flux_semantics=first.flux_semantics,
        fwhm_semantics=first.fwhm_semantics,
        aggregation=_WEIGHTED_SCALARS,
    )


def _weighted_scalar_fields(
    rows: Sequence[object],
    weights: Sequence[float] | np.ndarray,
    field_names: Sequence[str],
) -> dict[str, float]:
    """Private compatibility kernel for ordered scalar-only weighted sums."""

    row_tuple = tuple(rows)
    weight_tuple = tuple(float(weight) for weight in weights)
    names = tuple(field_names)
    if not row_tuple or len(row_tuple) != len(weight_tuple):
        raise ScienceMetricsError(
            "rows and weights must be non-empty sequences of equal length."
        )
    if not names:
        raise ScienceMetricsError("field_names must contain at least one field.")
    if not all(math.isfinite(weight) and weight >= 0.0 for weight in weight_tuple):
        raise ScienceMetricsError("weights must be finite and non-negative.")
    averaged: dict[str, float] = {}
    for name in names:
        try:
            averaged[name] = float(
                sum(
                    weight * float(getattr(row, name))
                    for weight, row in zip(weight_tuple, row_tuple)
                )
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise ScienceMetricsError(
                f"rows must expose finite real scalar field {name!r}."
            ) from exc
        if not math.isfinite(averaged[name]):
            raise ScienceMetricsError(
                f"weighted scalar field {name!r} must be finite."
            )
    return averaged


def lambda_over_d_rad(wavelength_m: float, telescope_diameter_m: float) -> float:
    """Return one diffraction unit ``lambda / D`` in radians."""

    wavelength = _positive_scalar(wavelength_m, label="wavelength_m")
    diameter = _positive_scalar(
        telescope_diameter_m,
        label="telescope_diameter_m",
    )
    return float(wavelength / diameter)


def radians_to_lambda_over_d(
    angle_rad: float,
    wavelength_m: float,
    telescope_diameter_m: float,
) -> float:
    """Express a finite angular scalar in units of ``lambda / D``."""

    angle = _finite_scalar(angle_rad, label="angle_rad")
    return float(
        angle / lambda_over_d_rad(wavelength_m, telescope_diameter_m)
    )


def radians_to_arcsec(angle_rad: float) -> float:
    """Convert a finite scalar angle in radians to arcseconds."""

    angle = _finite_scalar(angle_rad, label="angle_rad")
    return float(angle * ARCSEC_PER_RAD)


def _require_psf_result(value: object, *, label: str) -> PsfResult:
    if not isinstance(value, PsfResult):
        raise ScienceMetricsError(f"{label} must be a PsfResult.")
    _validated_grid(
        value.intensity,
        value.x_angle_rad,
        value.y_angle_rad,
        data_label=f"{label}.intensity",
    )
    if value.normalization != "unit_total_flux":
        raise ScienceMetricsError(
            f"{label}.normalization must be 'unit_total_flux'."
        )
    return value


def _require_common_psf_grid(psf: PsfResult, ideal_psf: PsfResult) -> None:
    if psf.intensity.shape != ideal_psf.intensity.shape:
        raise ScienceMetricsError("psf and ideal_psf shapes must match.")
    if psf.wavelength_m != ideal_psf.wavelength_m:
        raise ScienceMetricsError(
            "psf and ideal_psf wavelengths must match exactly."
        )
    if not np.array_equal(psf.x_angle_rad, ideal_psf.x_angle_rad) or not np.array_equal(
        psf.y_angle_rad,
        ideal_psf.y_angle_rad,
    ):
        raise ScienceMetricsError(
            "psf and ideal_psf must use identical physical angular axes."
        )
    if psf.backend_name != ideal_psf.backend_name:
        raise ScienceMetricsError(
            "psf and ideal_psf must use the same propagation backend."
        )
    if psf.sampling_metadata != ideal_psf.sampling_metadata:
        raise ScienceMetricsError(
            "psf and ideal_psf must use identical pupil and sampling metadata."
        )


def _pupil_mask_for_psf(
    pupil: PupilGeometry | np.ndarray,
    psf: PsfResult,
    *,
    telescope_diameter_m: float,
) -> np.ndarray:
    """Bind a residual-OPD pupil to the propagation identity in ``psf``."""

    metadata = psf.sampling_metadata
    geometry_hash = metadata.get("pupil_geometry_hash")
    if isinstance(pupil, PupilGeometry):
        if geometry_hash is not None and geometry_hash != pupil.geometry_hash:
            raise ScienceMetricsError(
                "pupil geometry does not match psf sampling_metadata."
            )
        if not math.isclose(
            telescope_diameter_m,
            pupil.telescope_diameter_m,
            rel_tol=0.0,
            abs_tol=0.0,
        ):
            raise ScienceMetricsError(
                "telescope_diameter_m must match the supplied PupilGeometry."
            )
        mask = pupil.pupil_mask
    else:
        if geometry_hash is not None:
            raise ScienceMetricsError(
                "pupil must be the PupilGeometry recorded by this PSF, not an "
                "unidentified boolean mask."
            )
        mask = np.asarray(pupil)

    expected_shape = metadata.get("pupil_shape_px")
    if expected_shape is None and "pupil_size_px" in metadata:
        size = metadata["pupil_size_px"]
        expected_shape = (size, size)
    if expected_shape is not None and tuple(mask.shape) != tuple(expected_shape):
        raise ScienceMetricsError(
            f"pupil shape {mask.shape} does not match PSF sampling pupil shape "
            f"{tuple(expected_shape)}."
        )
    return mask


def _validated_opd_and_rms(
    opd_m: np.ndarray,
    pupil: np.ndarray,
) -> tuple[np.ndarray, float]:
    opd = np.asarray(opd_m)
    mask = np.asarray(pupil)
    if opd.ndim != 2:
        raise ScienceMetricsError(f"opd_m must be two-dimensional; got {opd.shape}.")
    if np.issubdtype(opd.dtype, np.bool_) or not np.issubdtype(
        opd.dtype,
        np.number,
    ) or np.issubdtype(opd.dtype, np.complexfloating):
        raise ScienceMetricsError("opd_m must contain real numeric values.")
    if mask.dtype != np.dtype(bool) or mask.ndim != 2:
        raise ScienceMetricsError("pupil must be a two-dimensional boolean array.")
    if opd.shape != mask.shape:
        raise ScienceMetricsError(
            f"opd_m shape {opd.shape} does not match pupil shape {mask.shape}."
        )
    if not np.any(mask):
        raise ScienceMetricsError("pupil must contain illuminated samples.")
    values = np.asarray(opd, dtype=float)
    try:
        _wavefront.validate_masked_finite(values, mask, "residual_opd_m")
        rms = _wavefront.masked_rms(values, mask, remove_mean=True)
    except ValueError as exc:
        raise ScienceMetricsError(str(exc)) from exc
    return values, float(rms)


def _validated_grid(
    data: np.ndarray,
    x_angle_rad: np.ndarray,
    y_angle_rad: np.ndarray,
    *,
    data_label: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    values = np.asarray(data)
    if values.ndim != 2:
        raise ScienceMetricsError(
            f"{data_label} must be two-dimensional; got {values.shape}."
        )
    if np.issubdtype(values.dtype, np.bool_) or not np.issubdtype(
        values.dtype,
        np.number,
    ) or np.issubdtype(values.dtype, np.complexfloating):
        raise ScienceMetricsError(f"{data_label} must contain real numeric values.")
    values = np.asarray(values, dtype=float)
    if not np.all(np.isfinite(values)):
        raise ScienceMetricsError(f"{data_label} must be finite.")
    if np.any(values < 0.0):
        raise ScienceMetricsError(f"{data_label} must be non-negative.")
    total = float(np.sum(values))
    if not math.isfinite(total) or total <= 0.0:
        raise ScienceMetricsError(f"{data_label} must have positive total value.")
    x_axis = _validated_axis(
        x_angle_rad,
        values.shape[1],
        label="x_angle_rad",
    )
    y_axis = _validated_axis(
        y_angle_rad,
        values.shape[0],
        label="y_angle_rad",
    )
    return values, x_axis, y_axis


def _validated_axis(value: np.ndarray, length: int, *, label: str) -> np.ndarray:
    axis = np.asarray(value)
    if axis.ndim != 1:
        raise ScienceMetricsError(f"{label} must be one-dimensional.")
    if axis.size != length:
        raise ScienceMetricsError(
            f"{label} length {axis.size} does not match grid dimension {length}."
        )
    if axis.size < 2:
        raise ScienceMetricsError(f"{label} must contain at least two coordinates.")
    if np.issubdtype(axis.dtype, np.bool_) or not np.issubdtype(
        axis.dtype,
        np.number,
    ) or np.issubdtype(axis.dtype, np.complexfloating):
        raise ScienceMetricsError(f"{label} must contain real numeric values.")
    axis = np.asarray(axis, dtype=float)
    if not np.all(np.isfinite(axis)):
        raise ScienceMetricsError(f"{label} must be finite.")
    differences = np.diff(axis)
    if not np.all(np.isfinite(differences)) or np.any(differences <= 0.0):
        raise ScienceMetricsError(f"{label} must be strictly increasing.")
    if not math.isfinite(float(axis[-1] - axis[0])):
        raise ScienceMetricsError(f"{label} must have finite physical extent.")
    return axis


def _pixel_solid_angles(x_axis: np.ndarray, y_axis: np.ndarray) -> np.ndarray:
    x_widths = _cell_widths(x_axis)
    y_widths = _cell_widths(y_axis)
    solid_angle = np.multiply.outer(y_widths, x_widths)
    if not np.all(np.isfinite(solid_angle)) or np.any(solid_angle <= 0.0):
        raise ScienceMetricsError(
            "angular axes do not define positive finite pixel solid angles."
        )
    return solid_angle


def _surface_brightness_from_flux_grid(
    flux: np.ndarray,
    x_axis: np.ndarray,
    y_axis: np.ndarray,
) -> np.ndarray:
    solid_angle = _pixel_solid_angles(x_axis, y_axis)
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        brightness = flux / solid_angle
    if not np.all(np.isfinite(brightness)):
        raise ScienceMetricsError(
            "discrete flux and angular axes must define finite surface brightness."
        )
    return brightness


def _cell_widths(axis: np.ndarray) -> np.ndarray:
    boundaries = np.empty(axis.size + 1, dtype=float)
    differences = np.diff(axis)
    boundaries[1:-1] = axis[:-1] + 0.5 * differences
    boundaries[0] = axis[0] - 0.5 * (axis[1] - axis[0])
    boundaries[-1] = axis[-1] + 0.5 * (axis[-1] - axis[-2])
    widths = np.diff(boundaries)
    if not np.all(np.isfinite(widths)) or np.any(widths <= 0.0):
        raise ScienceMetricsError(
            "angular axes do not define positive finite pixel solid angles."
        )
    return widths


def _metric_center(
    data: np.ndarray,
    x_axis: np.ndarray,
    y_axis: np.ndarray,
    *,
    center_angle_rad: tuple[float, float] | None,
) -> tuple[float, float]:
    if center_angle_rad is None:
        row, column = np.unravel_index(int(np.argmax(data)), data.shape)
        return float(x_axis[column]), float(y_axis[row])
    center = np.asarray(center_angle_rad)
    if center.shape != (2,) or np.issubdtype(center.dtype, np.bool_) or not np.issubdtype(
        center.dtype,
        np.number,
    ) or np.issubdtype(center.dtype, np.complexfloating):
        raise ScienceMetricsError(
            "center_angle_rad must be a pair of real (x, y) radians."
        )
    center = np.asarray(center, dtype=float)
    if not np.all(np.isfinite(center)):
        raise ScienceMetricsError("center_angle_rad must be finite.")
    return float(center[0]), float(center[1])


def _linear_crossing(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    target: float,
) -> float:
    if y1 == y0:
        return float(x1)
    fraction = (target - y0) / (y1 - y0)
    return float(x0 + fraction * (x1 - x0))


def _finite_scalar(value: object, *, label: str) -> float:
    array = np.asarray(value)
    if array.shape != () or np.issubdtype(array.dtype, np.bool_):
        raise ScienceMetricsError(f"{label} must be a real scalar.")
    try:
        result = float(array)
    except (TypeError, ValueError) as exc:
        raise ScienceMetricsError(f"{label} must be a real scalar.") from exc
    if not math.isfinite(result):
        raise ScienceMetricsError(f"{label} must be finite.")
    return result


def _positive_scalar(value: object, *, label: str) -> float:
    result = _finite_scalar(value, label=label)
    if result <= 0.0:
        raise ScienceMetricsError(f"{label} must be positive.")
    return result


def _nonnegative_scalar(value: object, *, label: str) -> float:
    result = _finite_scalar(value, label=label)
    if result < 0.0:
        raise ScienceMetricsError(f"{label} must be non-negative.")
    return result


def _require_metric_relation(actual: float, expected: float, *, label: str) -> None:
    if not math.isclose(actual, expected, rel_tol=1.0e-12, abs_tol=1.0e-18):
        raise ScienceMetricsError(f"{label}; got {actual!r}, expected {expected!r}.")


def _immutable_float_array(value: np.ndarray) -> np.ndarray:
    contiguous = np.ascontiguousarray(np.asarray(value, dtype=float))
    immutable = np.frombuffer(contiguous.tobytes(order="C"), dtype=float)
    return immutable.reshape(contiguous.shape)
