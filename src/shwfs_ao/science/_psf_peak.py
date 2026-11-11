"""Subpixel peaks of fully sampled periodic focal-plane intensity images.

A pad-factor ``p >= 2`` FFT image is Nyquist sampled (its spectrum, the
pupil autocorrelation, lies inside the band), so the trigonometric
interpolant of its samples is the continuous image.  :func:`interpolated_peak`
estimates the global maximum of that interpolant:

1. the interpolant is evaluated on the half-pixel grid (the samples and the
   three interlaced half-pixel shifts, four FFT evaluations);
2. every local maximum of that grid whose value reaches ``candidate_fraction``
   of the grid's largest value is a candidate core (periodic neighbourhood,
   at most ``max_candidates`` strongest);
3. each candidate is refined on local grids of 1/8 and then 1/64 pixel, and
   the best refined value wins.

Step 2 lets a core whose true peak falls between samples beat a fainter
core that happens to sit on a sample: refining only the brightest half-pixel
sample reads a core a quarter pixel off every node at pad 3 at 0.9665 of its
height, so a node core 2.5 % fainter used to win.  A true peak is never
farther than a quarter pixel per axis from a half-pixel node.  The default
``candidate_fraction = 0.85`` was set from one measured case: the
unaberrated image of the 256-sample, unobstructed 2.2 m pupil at 1.65 um
tilted a quarter pixel in both axes, whose brightest sample reads 0.9259
(pad 2), 0.9665 (pad 3) or 0.9915 (pad 6) of its peak.  No lower bound for
every aberrated PSF the propagator can produce has been derived, so a core
narrower than that diffraction core could be read below the fraction and
skipped, and candidates beyond the ``max_candidates`` strongest are not
refined.  The refinement grids leave a residual of about ``1e-5`` at pad 3
(the 1/64-pixel step against the core curvature), which is why the pad-3 and
pad-6 estimates of one image can differ by that much.
"""

import numpy as np

from ..core.types import PsfResult


def supports_peak_interpolation(psf: PsfResult) -> bool:
    """Require a full optical DFT period with room for the pupil autocorrelation."""
    meta = psf.sampling_metadata
    if meta.get("cropping") != "none":
        return False
    shape = meta.get("pupil_shape_px")
    pitch = meta.get("pupil_pixel_spacing_xy_m")
    if not isinstance(shape, (list, tuple)) or not isinstance(pitch, (list, tuple)):
        return False
    if len(shape) != 2 or len(pitch) != 2:
        return False
    for axis, pupil_size, spacing in zip(
        (psf.x_angle_rad, psf.y_angle_rad), reversed(shape), pitch, strict=True
    ):
        if not isinstance(pupil_size, int) or pupil_size < 1:
            return False
        if not isinstance(spacing, (int, float)) or not np.isfinite(spacing) or spacing <= 0:
            return False
        if axis.size < max(2, 2 * pupil_size - 1) or not np.allclose(
            np.diff(axis), psf.wavelength_m / (spacing * axis.size), rtol=1e-9, atol=0.0
        ):
            return False
    return True


def _half_pixel_grid(intensity: np.ndarray, spectrum: np.ndarray) -> np.ndarray:
    """The interpolant on the half-pixel grid: ``grid[2i + a, 2j + b] = I(i + a/2, j + b/2)``."""

    rows, cols = intensity.shape
    ramp_y = np.exp(1j * np.pi * np.fft.fftfreq(rows))[:, None]
    ramp_x = np.exp(1j * np.pi * np.fft.fftfreq(cols))[None, :]
    grid = np.empty((2 * rows, 2 * cols))
    grid[0::2, 0::2] = intensity
    grid[0::2, 1::2] = np.fft.ifft2(spectrum * ramp_x).real
    grid[1::2, 0::2] = np.fft.ifft2(spectrum * ramp_y).real
    grid[1::2, 1::2] = np.fft.ifft2(spectrum * ramp_y * ramp_x).real
    return grid


def _periodic_local_maxima(grid: np.ndarray) -> np.ndarray:
    """Boolean mask of samples not below any of their eight periodic neighbours."""

    local = np.ones(grid.shape, dtype=bool)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy or dx:
                local &= grid >= np.roll(grid, (dy, dx), axis=(0, 1))
    return local


def _refine(spectrum: np.ndarray, fy: np.ndarray, fx: np.ndarray, centre: np.ndarray,
            size: int) -> tuple[float, np.ndarray]:
    """Local trigonometric evaluation on 1/8- then 1/64-pixel grids around ``centre``."""

    best = -np.inf
    for step in (1 / 8, 1 / 64):
        offsets = np.arange(-4, 5) * step
        ys, xs = centre[0] + offsets, centre[1] + offsets
        ey = np.exp(2j * np.pi * np.outer(ys, fy))
        ex = np.exp(2j * np.pi * np.outer(fx, xs))
        samples = (ey @ spectrum @ ex).real / size
        i, j = np.unravel_index(int(np.argmax(samples)), samples.shape)
        if samples[i, j] > best:
            best = float(samples[i, j])
            centre = np.array([ys[i], xs[j]])
    return best, centre


def interpolated_peak(
    intensity: np.ndarray,
    *,
    candidate_fraction: float = 0.85,
    max_candidates: int = 64,
) -> tuple[float, tuple[float, float]]:
    """Estimate the periodic image peak and its (row, column) shift from the brightest pixel.

    Every local maximum of the half-pixel-grid interpolant whose value reaches
    ``candidate_fraction`` of that grid's largest value is refined to 1/64
    pixel, strongest first and at most ``max_candidates`` of them, and the
    best refined value is returned (module docstring).  The input must be a
    real, Nyquist-sampled intensity over a complete DFT period.
    """

    if not 0.0 < candidate_fraction <= 1.0:
        raise ValueError("candidate_fraction must lie in (0, 1].")
    if max_candidates < 1:
        raise ValueError("max_candidates must be positive.")
    rows, cols = intensity.shape
    row, col = np.unravel_index(int(np.argmax(intensity)), intensity.shape)
    spectrum = np.fft.fft2(intensity)
    fy, fx = np.fft.fftfreq(rows), np.fft.fftfreq(cols)
    grid = _half_pixel_grid(intensity, spectrum)
    threshold = candidate_fraction * float(np.max(grid))
    candidates = np.flatnonzero(_periodic_local_maxima(grid) & (grid >= threshold))
    order = np.argsort(grid.ravel()[candidates])[::-1][:max_candidates]
    best = float(intensity[row, col])
    centre = np.array([row, col], dtype=float)
    for flat in candidates[order]:
        i, j = np.unravel_index(int(flat), grid.shape)
        value, position = _refine(spectrum, fy, fx, np.array([i / 2.0, j / 2.0]), intensity.size)
        if value > best:
            best, centre = value, position
    # Use the nearest periodic representative at the edge of the focal field.
    shape = np.array([rows, cols])
    shift = (centre - (row, col) + shape / 2) % shape - shape / 2
    return best, (float(shift[0]), float(shift[1]))
