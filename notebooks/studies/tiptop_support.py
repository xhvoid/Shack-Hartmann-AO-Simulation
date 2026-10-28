"""Supplemental Notebook 12: complete the uncorrected atmospheric fitting tail.

P3 supplies the AO residual inside its correction band. This adapter replaces only
its finitely sampled fitting PSD with a continuous von Karman structure function.
It uses the installed MASTSEL PSF propagator and never patches third-party code.
The supported scope is the notebook's CPU, one-wavelength, HO-only, circular-cutoff
configuration without static aberrations, jitter or additional error PSDs.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import version
from functools import lru_cache
import math

import numpy as np
from numpy.polynomial.legendre import leggauss
from scipy.interpolate import RegularGridInterpolator
from scipy.signal import fftconvolve
from scipy.special import j0

VERIFIED_VERSIONS = {"astro-tiptop": "1.5.1", "astro-p3": "1.6.2", "mastsel": "1.5.2"}
RAD_TO_MAS = 206264806.24709636
BUDGET_ATTRIBUTES = {
    "fitting": "wfeFit", "aliasing": "wfeAl", "servo-lag": "wfeS",
    "tomography": "wfeTomo", "noise": "wfeN", "diff. refraction": "wfeDiffRef",
    "chromatism": "wfeChrom",
}


def check_versions():
    installed = {key: version(key) for key in VERIFIED_VERSIONS}
    if installed != VERIFIED_VERSIONS:
        raise RuntimeError(f"Revalidate the tail adapter for this environment: {installed}. "
                           f"Verified versions: {VERIFIED_VERSIONS}")
    return installed


def centered_crop(array, size):
    """Crop around the FFT origin, without changing the flux normalization."""
    if size > array.shape[-1] or size < 2:
        raise ValueError("Crop must fit inside the computational image")
    start = array.shape[-1] // 2 - size // 2
    return array[..., start:start + size, start:start + size].copy()


def fitting_variance(atmosphere, cutoff):
    """Continuous phase variance outside a circular cutoff, in rad^2.

    Integral of 2*pi*f*C*r0^(-5/3)*(f^2+L0^(-2))^(-11/6), from cutoff to infinity.
    """
    return float(2 * np.pi * atmosphere.spectrum(cutoff)
                 * (cutoff**2 + atmosphere.L0**-2) * 3 / 5)


@lru_cache(maxsize=8)
def _quadrature(nodes):
    return leggauss(nodes)


def fitting_structure_function(atmosphere, cutoff, separations, nodes=512):
    """Full von Karman D minus its low-pass integral; includes the infinite tail."""
    rho = np.asarray(separations, dtype=float)
    unique, inverse = np.unique(rho, return_inverse=True)
    abscissa, weights = _quadrature(nodes)
    frequencies = (abscissa + 1) * cutoff / 2
    weighted_psd = weights * cutoff / 2 * frequencies * atmosphere.spectrum(frequencies)
    values = np.empty_like(unique)
    for start in range(0, unique.size, 1024):
        rr = unique[start:start + 1024]
        low = 4 * np.pi * ((1 - j0(2 * np.pi * rr[:, None] * frequencies))
                           @ weighted_psd)
        values[start:start + 1024] = atmosphere.structureFunction(rr) - low
    values[unique == 0] = 0
    if np.min(values) < -1e-8:
        raise ValueError("Negative fitting structure function; refine quadrature")
    return np.maximum(values[inverse], 0).reshape(rho.shape)


def _vector_term(fao, attribute, n_directions):
    value = np.atleast_1d(np.asarray(getattr(fao, attribute), dtype=float))
    return np.broadcast_to(value, (n_directions,)).copy()


@dataclass
class CompletedPsf:
    """Flux-normalized crops plus explicitly attributed raw/corrected budgets."""
    psfs: np.ndarray
    diffraction: np.ndarray
    open_loop: np.ndarray
    raw_budget_nm: dict[str, np.ndarray]
    completed_budget_nm: dict[str, np.ndarray]
    raw_total_nm: np.ndarray
    total_nm: np.ndarray
    crop_energy: np.ndarray
    full_grid_energy: np.ndarray
    internal_pixels: int
    pixel_scale_mas: float
    quadrature_nodes: int
    fitting_variance_rad2: float
    low_band_variance_rad2: np.ndarray
    p3_to_actual_df_ratio: float


def complete_psfs(fao, *, crop_pixels=400, internal_pixels=1024,
                   quadrature_nodes=512, pixel_scale_mas=None):
    """Complete all P3 science directions, preserving full-grid flux before crop.

    The wavelength and pixel scale defining the P3 PSD remain unchanged. A larger
    computational image improves pupil-baseline sampling without recomputing the
    tomography. Cropping is separate from this internal integration grid.
    """
    from mastsel import Field, longExposurePsf

    ao, freq, atm = fao.ao, fao.freq, fao.ao.atm
    if ao.dms.AoArea != "circle" or getattr(fao, "applyTiltFilter", False):
        raise ValueError("Tail adapter requires circular cutoff and no LO tilt filter")
    if len(np.unique(np.atleast_1d(ao.src.wvl))) != 1:
        raise ValueError("Tail adapter supports one science wavelength")
    for attribute in ("wfeNCPA", "wfeWindShake", "wfeJitter", "wfeMcaoCone", "wfeExtra"):
        if np.any(np.asarray(getattr(fao, attribute, 0.0)) != 0):
            raise ValueError(f"Unsupported additional error term: {attribute}")
    if getattr(ao, "getPSDatNGSpositions", False) or "sources_LO" in ao.my_data_map:
        raise ValueError("Low-order/NGS branches are outside the adapter's scope")
    if np.any(np.asarray(getattr(ao.tel, "extraErrorLoNm", 0.0)) != 0):
        raise ValueError("Additional low-order error is outside the adapter's scope")
    if getattr(ao.tel, "path_pupil", "") or getattr(ao.tel, "path_apodizer", ""):
        raise ValueError("File-loaded pupils/apodizers have unvalidated sampling")
    if ao.tel.opdMap_on is not None:
        raise ValueError("Static OPD maps require a separate propagation validation")
    if np.isinf(atm.L0):
        raise ValueError("This adapter was validated for finite outer scale")
    N = int(internal_pixels)
    if N % 2 or N < int(freq.nOtf) or crop_pixels > N:
        raise ValueError("Even computational image must contain the PSD and output crop")
    df = float(freq.PSDstep)
    wavelength = float(freq.wvlRef)
    actual_pixel = wavelength * df * RAD_TO_MAS
    if pixel_scale_mas is not None and not np.isclose(pixel_scale_mas, actual_pixel):
        raise ValueError("Requested sampling must match the P3 PSD step")
    cutoff = float(freq.kcMax_)
    p3_df = 2 * cutoff / int(freq.resAO)
    conversion_nm2 = (p3_df * wavelength * 1e9 / (2 * np.pi))**2
    phase_psds = np.asarray(fao.PSD, dtype=float) / conversion_nm2
    finite_fit = np.asarray(fao.fittingPSD(), dtype=float)
    nonfitting = phase_psds - finite_fit[..., None]
    # Terms beyond the correction support must not be replaced twice.
    if np.min(nonfitting) < -1e-9 * max(1.0, np.max(phase_psds)):
        raise ValueError("Fitting subtraction produced a materially negative PSD")
    nonfitting = np.maximum(nonfitting, 0)
    n_directions = nonfitting.shape[-1]

    # Pupil autocorrelation at the desired baseline spacing. The same pupil and
    # interpolation generate corrected, open-loop and diffraction reference PSFs.
    baseline_step = 1 / (N * df)
    diameter = float(ao.tel.D)
    half_support = int(math.ceil(diameter / baseline_step))
    if 2 * half_support + 1 >= N:
        raise ValueError("Computational OTF needs more support around the pupil")
    separation = np.arange(-half_support, half_support + 1) * baseline_step
    xx, yy = np.meshgrid(separation, separation, indexing="xy")
    radius = np.hypot(xx, yy)
    in_support = radius <= diameter
    pupil = np.asarray(ao.tel.pupil, dtype=float)
    correlation = fftconvolve(pupil, pupil[::-1, ::-1], mode="full")
    correlation /= correlation.max()
    # Generated P3 annulus: linspace(-D/2,D/2,N) includes both endpoints.
    pupil_step = diameter / (pupil.shape[0] - 1)
    pupil_axis = (np.arange(correlation.shape[0]) - pupil.shape[0] + 1) * pupil_step
    telescope_otf = RegularGridInterpolator(
        (pupil_axis, pupil_axis), correlation, bounds_error=False, fill_value=0
    )(np.stack((yy, xx), axis=-1))
    # Keep the complete interpolated autocorrelation. A hard radial crop at D
    # cuts tiny interpolation-edge values and can create negative PSF rings.
    telescope_otf = np.maximum(telescope_otf, 0)
    in_support = telescope_otf > 0
    d_fit = np.zeros_like(radius)
    d_fit[in_support] = fitting_structure_function(
        atm, cutoff, radius[in_support], quadrature_nodes
    )
    d_atm = np.zeros_like(radius)
    d_atm[in_support] = atm.structureFunction(radius[in_support])
    centre = N // 2
    region = (slice(centre - half_support, centre + half_support + 1),) * 2

    def expanded_otf(structure_function):
        out = np.zeros((N, N))
        out[region] = telescope_otf * np.exp(-structure_function / 2)
        out[centre, centre] = 1
        return out

    mask = Field(wavelength, N, 1 / df, xp=np)
    psd = Field(wavelength, N, N * df, "rad", xp=np)
    fit_otf = expanded_otf(d_fit)
    zero = np.zeros((N, N))
    psd.sampling = zero

    def propagate(otf):
        image = np.asarray(longExposurePsf(mask, psd, otf_tel=otf).sampling)
        # OTF origin is one; the discrete transform has total N^2. Normalize on
        # this extended computational field exactly once, never on a science crop.
        image = image / image.sum()
        if image.min() < -1e-10 * image.max():
            raise ValueError(f"Materially negative propagated PSF: min/peak={image.min()/image.max():.3e}")
        return image

    diffraction = propagate(expanded_otf(np.zeros_like(radius)))
    open_loop = propagate(expanded_otf(d_atm))
    completed, energy = [], []
    original_n = nonfitting.shape[0]
    offset = N // 2 - original_n // 2
    for direction in range(n_directions):
        density = np.zeros((N, N))
        # MASTSEL zero-pads its PSD by two before covariance conversion: the
        # factor4 compensates that inverse-FFT normalization, as its native
        # psdSetToPsfSet() path does. P3 arrays are x/y/direction, MASTSEL y/x.
        density[offset:offset + original_n, offset:offset + original_n] = (
            nonfitting[..., direction].T * 4 * (wavelength / (2 * np.pi))**2
        )
        psd.sampling = density
        full = propagate(fit_otf)
        energy.append(full.sum())
        completed.append(centered_crop(full, crop_pixels))
    raw_budget = {label: _vector_term(fao, attribute, n_directions)
                  for label, attribute in BUDGET_ATTRIBUTES.items()}
    ratio = df / p3_df
    corrected_budget = {label: values * ratio for label, values in raw_budget.items()}
    fit_variance = fitting_variance(atm, cutoff)
    rad_to_nm = wavelength * 1e9 / (2 * np.pi)
    corrected_budget["fitting"] = np.full(n_directions, np.sqrt(fit_variance) * rad_to_nm)
    low_variance = nonfitting.sum(axis=(0, 1)) * df**2
    total_nm = np.sqrt(low_variance + fit_variance) * rad_to_nm
    budget_total = np.sqrt(sum(values**2 for values in corrected_budget.values()))
    if not np.allclose(total_nm, budget_total, atol=2e-6, rtol=0):
        raise ValueError("Completed OTF variance and error budget do not close")
    images = np.asarray(completed)
    return CompletedPsf(
        images, centered_crop(diffraction, crop_pixels), centered_crop(open_loop, crop_pixels),
        raw_budget, corrected_budget, _vector_term(fao, "wfeTot", n_directions), total_nm,
        images.sum(axis=(1, 2)), np.asarray(energy), N, actual_pixel, quadrature_nodes,
        fit_variance, low_variance, ratio,
    )


def fwhm_contour(psf, pixel_scale_mas):
    """Equivalent diameter of the interpolated half-maximum *core* contour."""
    import contourpy
    from matplotlib.path import Path
    image = np.asarray(psf, dtype=float)
    py, px = np.unravel_index(image.argmax(), image.shape)
    contours = contourpy.contour_generator(
        x=np.arange(image.shape[1]), y=np.arange(image.shape[0]), z=image
    ).lines(float(image.max() / 2))
    areas = []
    for contour in contours:
        if len(contour) >= 4 and np.allclose(contour[0], contour[-1]) and Path(contour).contains_point((px, py)):
            x, y = contour.T
            areas.append(abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1))) / 2)
    return float(2 * np.sqrt(min(areas) / np.pi) * pixel_scale_mas) if areas else float("nan")


def encircled_energy_at(psf, pixel_scale_mas, radius_mas, subpixels=12):
    """Fixed circular-aperture energy relative to the full computational flux.

    Fractional boundary pixels are integrated on a small subpixel grid. Interior
    pixels contribute exactly once; the crop is never renormalized.
    """
    image = np.asarray(psf)
    py, px = np.unravel_index(image.argmax(), image.shape)
    yy, xx = np.indices(image.shape)
    r = np.hypot(xx - px, yy - py)
    radius = radius_mas / pixel_scale_mas
    inside = r <= radius - np.sqrt(0.5)
    boundary = (r > radius - np.sqrt(0.5)) & (r < radius + np.sqrt(0.5))
    bx = (xx - px)[boundary]
    by = (yy - py)[boundary]
    offsets = (np.arange(subpixels) + 0.5) / subpixels - 0.5
    weights = np.zeros(len(bx))
    for dx in offsets:
        for dy in offsets:
            weights += (bx + dx)**2 + (by + dy)**2 <= radius**2
    weights /= subpixels**2
    return float(image[inside].sum() + image[boundary] @ weights)
