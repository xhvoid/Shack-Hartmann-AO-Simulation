"""Detector-plane Shack--Hartmann optics: MFT, pixel integration, diffusion (DET-03/04).

Each lenslet's focal field is a matrix Fourier transform (MFT) of its local
pupil field, evaluated at ``k x k`` Gauss--Legendre nodes inside every
detector pixel of the lenslet block (window plus guard ring) and of a margin
around it.  The intensity normalized to the lenslet's total flux,

    I(theta) = |E(theta)|**2 * dx * dy / lambda**2 / sum |A|**2   [sr^-1],

is integrated against each pixel's response

    R_c(theta) = rect_c(theta) (x) G_sigma(theta),

the pixel aperture convolved with a charge-diffusion Gaussian truncated at
``+-5 sigma`` and renormalized on that support.  The responses of all pixels
form an exact partition of unity, so diffusion conserves flux and only
redistributes it; flux pushed beyond the block is lost and reported, never
renormalized away.  The integral uses the nodes' quadrature weights and is
separable, so per lenslet the block image is ``R_y I R_x^T`` with two small
matrices shared by every lenslet.

With ``k = 1`` the single node is the pixel centre with unit weight: the model
is point sampling, and with the legacy pixel scale ``lambda / (pad * n_s * dx)``
it reproduces the frozen FFT spots
(:func:`~shwfs_ao.backends.native.shwfs.lenslet_spot_from_phase`).  The
exponent sign follows ``numpy.fft`` so that equality is exact, not merely in
distribution.

Polychromatic sensing evaluates the MFT at every quadrature wavelength on the
common angular node grid, normalizes each wavelength's intensity to that
wavelength's total (pre-window) flux, and sums them with the normalized
detected-electron weights of the photometry.  Fields and phases are never
averaged across wavelengths, and per-wavelength capture fractions survive the
sum.  The spot axis (``theta = 0``) is the centre of the block's central pixel;
the block must be odd.

The sampled pupil makes the far field periodic with period ``lambda / dx``;
the represented angular extent must stay below one period at the shortest
wavelength, otherwise construction fails closed.
"""

from __future__ import annotations

from collections.abc import Sequence
import math
from numbers import Integral
from typing import Any, Final

import numpy as np

from ...core.hashing import component_config_hash
from ...core.types import DetectorPlaneSampling, SpotIntensityResult
from ...core.wavefront import opd_to_phase
from ...wfs.shack_hartmann.compact_geometry import CompactShackHartmannGeometry
from ...wfs.shack_hartmann.geometry import ShackHartmannGeometry
from ...wfs.shack_hartmann.optics import (
    make_detector_plane_sampling,
    validate_spot_intensity_result,
)
from .shwfs import NativeShackHartmannError, nominal_lenslet_sampling_shape


__all__ = (
    "MFT_CONVENTION",
    "DIFFUSION_TRUNCATION_SIGMA",
    "MftShackHartmannOptics",
    "pixel_response_matrix",
    "gauss_legendre_pixel_nodes",
    "build_mft_optics",
)


MFT_CONVENTION: Final = "mft_numpy_sign_gauss_legendre_pixel_response_v1"
DIFFUSION_TRUNCATION_SIGMA: Final = 5.0
_SCRATCH_LIMIT_BYTES: Final = 64 * 1024**2
_MEASUREMENT_LOCALITY: Final = "lenslet_pixels_v1"


def gauss_legendre_pixel_nodes(oversampling: int) -> tuple[np.ndarray, np.ndarray]:
    """Node offsets in pixel units on ``[-1/2, 1/2]`` and weights summing to one."""

    nodes, weights = np.polynomial.legendre.leggauss(int(oversampling))
    return 0.5 * nodes, 0.5 * weights


def _truncated_gaussian_cdf(z: np.ndarray) -> np.ndarray:
    """CDF of a unit Gaussian truncated to ``[-T, T]`` and renormalized."""

    t = DIFFUSION_TRUNCATION_SIGMA
    clipped = np.clip(z, -t, t)
    erf = np.vectorize(math.erf, otypes=[float])
    low = math.erf(-t / math.sqrt(2.0))
    high = math.erf(t / math.sqrt(2.0))
    return (erf(clipped / math.sqrt(2.0)) - low) / (high - low)


def pixel_response_matrix(
    pixel_centres_px: np.ndarray,
    node_positions_px: np.ndarray,
    node_weights_px: np.ndarray,
    diffusion_sigma_px: float,
) -> np.ndarray:
    """One axis of the pixel-response quadrature, shape ``(pixels, nodes)``.

    Entry ``[c, a]`` is ``w_a * r_c(x_a)``: the node's quadrature weight (in
    pixel units) times the 1-D response of pixel ``c``, whose aperture is
    ``[c - 1/2, c + 1/2]`` convolved with the truncated diffusion Gaussian.
    """

    centres = np.asarray(pixel_centres_px, dtype=float)[:, None]
    positions = np.asarray(node_positions_px, dtype=float)[None, :]
    weights = np.asarray(node_weights_px, dtype=float)[None, :]
    sigma = float(diffusion_sigma_px)
    if sigma == 0.0:
        inside = (positions >= centres - 0.5) & (positions < centres + 0.5)
        return np.where(inside, weights, 0.0)
    upper = _truncated_gaussian_cdf((centres + 0.5 - positions) / sigma)
    lower = _truncated_gaussian_cdf((centres - 0.5 - positions) / sigma)
    return weights * (upper - lower)


class MftShackHartmannOptics:
    """Native SH optics on a declared angular pixel grid (dense or compact)."""

    _geometry: ShackHartmannGeometry | CompactShackHartmannGeometry
    _wavelengths: tuple[float, ...]
    _weights: np.ndarray
    _reference_wavelength: float
    _scale: tuple[float, float]
    _block: int
    _k: int
    _sigma: float
    _batch: int
    _margin: int
    _dx: float
    _dy: float
    _aliasing_margin: float
    _sampling_shape: tuple[int, int]
    _nyquist_ratio: float
    _response: np.ndarray
    _node_px: np.ndarray
    _node_w: np.ndarray
    _transforms: list[tuple[np.ndarray, np.ndarray, float]]
    _local_fields: list[tuple[slice, slice, np.ndarray, tuple[int, int]]]
    _sampling: DetectorPlaneSampling
    _config_hash: str

    def __init__(
        self,
        geometry: ShackHartmannGeometry | CompactShackHartmannGeometry,
        *,
        wavelengths_m: Sequence[float],
        spectral_weights: Sequence[float],
        pixel_scale_rad: float | tuple[float, float],
        block_px: int,
        oversampling: int = 1,
        diffusion_sigma_px: float = 0.0,
        batch_size: int = 256,
        reference_wavelength_m: float | None = None,
    ) -> None:
        if not isinstance(geometry, (ShackHartmannGeometry, CompactShackHartmannGeometry)):
            raise NativeShackHartmannError("geometry must be a Shack-Hartmann geometry.")
        wavelengths = tuple(float(value) for value in wavelengths_m)
        weights = np.asarray(spectral_weights, dtype=float)
        if not wavelengths or weights.shape != (len(wavelengths),):
            raise NativeShackHartmannError("one spectral weight per wavelength is required.")
        if any(not math.isfinite(w) or w <= 0.0 for w in wavelengths):
            raise NativeShackHartmannError("wavelengths must be positive.")
        if np.any(~np.isfinite(weights)) or np.any(weights < 0.0) or not math.isclose(
            float(np.sum(weights)), 1.0, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise NativeShackHartmannError("spectral weights must be non-negative and sum to one.")
        if isinstance(pixel_scale_rad, tuple):
            scale = (float(pixel_scale_rad[0]), float(pixel_scale_rad[1]))
        else:
            scale = (float(pixel_scale_rad), float(pixel_scale_rad))
        if not all(math.isfinite(v) and v > 0.0 for v in scale):
            raise NativeShackHartmannError("pixel_scale_rad must be positive.")
        if isinstance(block_px, bool) or not isinstance(block_px, Integral) or block_px < 1 or block_px % 2 != 1:
            raise NativeShackHartmannError("block_px must be a positive odd integer.")
        if isinstance(oversampling, bool) or not isinstance(oversampling, Integral) or not 1 <= oversampling <= 32:
            raise NativeShackHartmannError("oversampling must be an integer in [1, 32].")
        sigma = float(diffusion_sigma_px)
        if not 0.0 <= sigma <= 2.0:
            raise NativeShackHartmannError("diffusion_sigma_px must be in [0, 2].")
        if isinstance(batch_size, bool) or not isinstance(batch_size, Integral) or batch_size < 1:
            raise NativeShackHartmannError("batch_size must be a positive integer.")
        self._geometry = geometry
        self._wavelengths = wavelengths
        self._weights = weights
        self._weights.flags.writeable = False
        self._reference_wavelength = (
            wavelengths[int(np.argmax(weights))]
            if reference_wavelength_m is None
            else float(reference_wavelength_m)
        )
        self._scale = scale
        self._block = int(block_px)
        self._k = int(oversampling)
        self._sigma = sigma
        self._batch = int(batch_size)
        self._margin = int(math.ceil(DIFFUSION_TRUNCATION_SIGMA * sigma)) if sigma > 0.0 else 0
        extent = self._block + 2 * self._margin
        dx = float(geometry.x_m[0, 1] - geometry.x_m[0, 0])
        dy = float(geometry.y_m[1, 0] - geometry.y_m[0, 0])
        self._dx, self._dy = dx, dy
        shortest = min(wavelengths)
        for spacing, pixel in ((dx, scale[0]), (dy, scale[1])):
            period_px = shortest / abs(spacing) / pixel
            if extent >= period_px:
                raise NativeShackHartmannError(
                    f"the represented field ({extent} px) reaches the sampled pupil's "
                    f"far-field period ({period_px:.3g} px at {shortest:.4g} m); the "
                    "image would alias.  Refine the pupil sampling or shrink the block."
                )
        self._aliasing_margin = min(
            shortest / abs(dx) / scale[0], shortest / abs(dy) / scale[1]
        ) / extent
        # Nyquist margin of the shortest wavelength for the intensity: lambda/(2 d).
        sampling_shape = nominal_lenslet_sampling_shape(
            geometry.pupil_shape, geometry.n_lenslets_across
        )
        self._sampling_shape = sampling_shape
        lenslet_width_m = sampling_shape[1] * abs(dx)
        self._nyquist_ratio = (shortest / (2.0 * lenslet_width_m)) / scale[0]

        offsets, node_weights = gauss_legendre_pixel_nodes(self._k)
        centre = (self._block - 1) / 2.0
        pixel_index = np.arange(-self._margin, self._block + self._margin, dtype=float)
        node_px = (pixel_index[:, None] + offsets[None, :]).reshape(-1)
        node_w = np.tile(node_weights, pixel_index.size)
        response = pixel_response_matrix(np.arange(self._block, dtype=float), node_px, node_w, sigma)
        self._response = response  # (block, nodes): pixel-unit weights
        self._node_px = node_px
        self._node_w = node_w
        theta_x = (node_px - centre) * scale[0]
        theta_y = (node_px - centre) * scale[1]
        rows, cols = sampling_shape
        x_local = (np.arange(cols, dtype=float) - cols // 2) * dx
        y_local = (np.arange(rows, dtype=float) - rows // 2) * dy
        self._transforms = []
        for wavelength in wavelengths:
            # theta * x is the path difference of a tilted wavefront (an OPD).
            wx = np.exp(-1j * opd_to_phase(np.outer(theta_x, x_local), wavelength))
            wy = np.exp(-1j * opd_to_phase(np.outer(theta_y, y_local), wavelength))
            norm = scale[0] * scale[1] * abs(dx * dy) / wavelength**2
            self._transforms.append((wx, wy, norm))
        self._local_fields = _local_fields(geometry, sampling_shape)
        self._sampling = make_detector_plane_sampling(
            window_shape_px=(self._block, self._block),
            pixel_scale_rad=scale,
            reference_pixel_xy=(centre, centre),
        )
        self._config_hash = component_config_hash(
            "native.shack_hartmann_optics.mft",
            {
                "geometry_hash": geometry.geometry_hash,
                "wavelengths_m": wavelengths,
                "spectral_weights": weights,
                "pixel_scale_rad": scale,
                "block_px": self._block,
                "oversampling": self._k,
                "diffusion_sigma_px": sigma,
                "diffusion_truncation_sigma": DIFFUSION_TRUNCATION_SIGMA,
                "margin_px": self._margin,
                "nominal_lenslet_sampling_shape": sampling_shape,
                "detector_sampling_hash": self._sampling.sampling_hash,
                "convention": MFT_CONVENTION,
                "remove_local_piston": True,
                "relative_throughput_semantics": "block_capture_fraction_of_total_flux",
                "measurement_locality": _MEASUREMENT_LOCALITY,
            },
        )

    # -- protocol surface ---------------------------------------------------------

    @property
    def backend_name(self) -> str:
        return "native"

    @property
    def config_hash(self) -> str:
        return self._config_hash

    @property
    def geometry(self) -> ShackHartmannGeometry | CompactShackHartmannGeometry:
        return self._geometry

    @property
    def geometry_hash(self) -> str:
        return self._geometry.geometry_hash

    @property
    def wfs_wavelength_m(self) -> float:
        return self._reference_wavelength

    @property
    def wavelengths_m(self) -> tuple[float, ...]:
        return self._wavelengths

    @property
    def spectral_weights(self) -> np.ndarray:
        return self._weights

    @property
    def sampling(self) -> DetectorPlaneSampling:
        return self._sampling

    @property
    def detector_sampling(self) -> DetectorPlaneSampling:
        return self._sampling

    @property
    def subaperture_ids(self) -> tuple[str, ...]:
        return self._geometry.subaperture_ids

    @property
    def measurement_locality(self) -> str:
        return _MEASUREMENT_LOCALITY

    @property
    def margin_px(self) -> int:
        return self._margin

    @property
    def aliasing_margin(self) -> float:
        """Far-field period over represented extent at the shortest wavelength (> 1)."""

        return self._aliasing_margin

    @property
    def nyquist_ratio(self) -> float:
        """``(lambda_min / 2 d) / pixel``: at least one means Nyquist-sampled pixels."""

        return self._nyquist_ratio

    def spot_intensities(self, residual_opd_m: np.ndarray) -> SpotIntensityResult:
        result, _ = self.spot_intensities_with_diagnostics(residual_opd_m)
        return result

    def spot_intensities_with_diagnostics(
        self,
        residual_opd_m: np.ndarray,
    ) -> tuple[SpotIntensityResult, dict[str, np.ndarray]]:
        """Unit-sum block spots, capture fractions and loss diagnostics.

        Diagnostics, per lenslet, as fractions of the lenslet's total flux:
        ``represented`` (integrated over the node grid, block plus margin,
        before diffusion moves anything), ``block`` (after diffusion,
        integrated over the block), ``window`` (the central block minus the
        guard ring is not known here, so callers crop) and the loss
        ``optical_field_loss = 1 - represented``.
        """

        opd = np.asarray(residual_opd_m, dtype=float)
        geometry = self._geometry
        if opd.shape != geometry.pupil_shape:
            raise NativeShackHartmannError("residual OPD shape does not match the pupil.")
        mask = np.asarray(geometry.pupil_mask, dtype=bool)
        if not np.all(np.isfinite(opd[mask])):
            raise NativeShackHartmannError("residual OPD must be finite in the pupil.")
        count = len(self._local_fields)
        nodes = self._node_px.size
        spots = np.empty((count, self._block, self._block))
        represented = np.empty(count)
        per_lenslet_bytes = nodes * nodes * 16 * 3
        batch = max(1, min(self._batch, _SCRATCH_LIMIT_BYTES // max(per_lenslet_bytes, 1)))
        weights_2d = np.outer(self._node_w, self._node_w)
        for start in range(0, count, batch):
            stop = min(count, start + batch)
            intensity = np.zeros((stop - start, nodes, nodes))
            # Unit amplitude on every illuminated sample: sum |A|^2 = sample count.
            power = np.array(
                [float(np.count_nonzero(self._local_fields[i][2])) for i in range(start, stop)]
            )
            for (wx, wy, norm), wavelength, weight in zip(
                self._transforms, self._wavelengths, self._weights
            ):
                if weight == 0.0:
                    continue
                fields = np.stack(
                    [self._local_amplitude(index, opd, wavelength) for index in range(start, stop)]
                )
                tmp = fields @ wx.T
                focal = wy @ tmp
                intensity += (weight * norm) * (np.abs(focal) ** 2) / power[:, None, None]
            represented[start:stop] = np.einsum("lab,ab->l", intensity, weights_2d)
            spots[start:stop] = self._response @ intensity @ self._response.T
        capture = np.sum(spots, axis=(1, 2))
        if np.any(~np.isfinite(capture)) or np.any(capture <= 0.0):
            raise NativeShackHartmannError("a lenslet has no finite flux inside its block.")
        unit = spots / capture[:, None, None]
        centre = (self._block - 1) / 2.0
        axis = np.arange(self._block, dtype=float) - centre
        result = SpotIntensityResult(
            unit_sum_spots=tuple(unit),
            subaperture_ids=geometry.subaperture_ids,
            relative_throughput=np.clip(capture, 0.0, 1.0),
            x_px=tuple(axis for _ in range(count)),
            y_px=tuple(axis for _ in range(count)),
            sampling=self._sampling,
            normalization="unit_sum_per_subaperture",
        )
        validate_spot_intensity_result(result, geometry, sampling=self._sampling)
        diagnostics = {
            "represented_fraction": represented,
            "block_fraction": capture,
            "optical_field_loss": 1.0 - represented,
            "diffusion_outflow": represented - capture,
        }
        return result, diagnostics

    def _local_amplitude(self, index: int, opd: np.ndarray, wavelength: float) -> np.ndarray:
        """Unit-amplitude local field at ``wavelength`` on the nominal canvas."""

        rows_slice, cols_slice, local_mask, offset = self._local_fields[index]
        canvas = np.zeros(self._sampling_shape, dtype=complex)
        r0, c0 = offset
        local_opd = np.nan_to_num(opd[rows_slice, cols_slice], nan=0.0).astype(float)
        phase = opd_to_phase(local_opd, wavelength)
        phase = phase - np.mean(phase[local_mask])
        block = canvas[r0 : r0 + local_mask.shape[0], c0 : c0 + local_mask.shape[1]]
        block[local_mask] = np.exp(1j * phase[local_mask])
        return canvas


def _local_fields(
    geometry: ShackHartmannGeometry | CompactShackHartmannGeometry,
    sampling_shape: tuple[int, int],
) -> list[tuple[slice, slice, np.ndarray, tuple[int, int]]]:
    """Illuminated bounding box, local mask and canvas offset per lenslet.

    The offset centres the bounding box on the nominal canvas exactly as the
    FFT path centres it on the padded canvas, so with ``pad = 1`` both use the
    same sample coordinates.
    """

    entries = []
    if isinstance(geometry, CompactShackHartmannGeometry):
        iterator = (
            (mask, bounds) for mask, bounds in zip(geometry.lenslet_masks, geometry.lenslet_bounds_rc)
        )
        for mask, (r0, _r1, c0, _c1) in iterator:
            rows, cols = np.nonzero(mask)
            br0, br1, bc0, bc1 = int(rows.min()), int(rows.max()) + 1, int(cols.min()), int(cols.max()) + 1
            local = np.array(mask[br0:br1, bc0:bc1], dtype=bool)
            entries.append(
                (
                    slice(int(r0) + br0, int(r0) + br1),
                    slice(int(c0) + bc0, int(c0) + bc1),
                    local,
                    _offset(local.shape, sampling_shape),
                )
            )
        return entries
    for mask in geometry.subaperture_masks:
        rows, cols = np.nonzero(mask)
        br0, br1, bc0, bc1 = int(rows.min()), int(rows.max()) + 1, int(cols.min()), int(cols.max()) + 1
        local = np.array(mask[br0:br1, bc0:bc1], dtype=bool)
        entries.append((slice(br0, br1), slice(bc0, bc1), local, _offset(local.shape, sampling_shape)))
    return entries


def _offset(local_shape: tuple[int, int], sampling_shape: tuple[int, int]) -> tuple[int, int]:
    if local_shape[0] > sampling_shape[0] or local_shape[1] > sampling_shape[1]:
        raise NativeShackHartmannError("a lenslet's illuminated box exceeds the nominal canvas.")
    return ((sampling_shape[0] - local_shape[0]) // 2, (sampling_shape[1] - local_shape[1]) // 2)


def build_mft_optics(
    geometry: ShackHartmannGeometry | CompactShackHartmannGeometry,
    physical_detector: Any,
    *,
    wfs_wavelength_m: float,
    block_px: int,
    batch_size: int = 256,
) -> MftShackHartmannOptics:
    """MFT optics for a :class:`~shwfs_ao.detector.physical_config.PhysicalDetectorConfig`.

    Spectral weights come from the configuration's photometric budget, so the
    optics see exactly the detected-electron weights the camera budget uses.
    """

    from ...detector.physical_config import physical_budget

    sampling = physical_detector.sampling
    full_area = (float(geometry.telescope_diameter_m) / float(geometry.n_lenslets_across)) ** 2
    scale = float(sampling.pixel_scale_rad)
    budget = physical_budget(
        physical_detector,
        wfs_wavelength_m=wfs_wavelength_m,
        full_subaperture_area_m2=full_area,
        pixel_solid_angle_sr=scale * scale,
    )
    return MftShackHartmannOptics(
        geometry,
        wavelengths_m=budget.wavelength_m,
        spectral_weights=budget.spectral_weights,
        pixel_scale_rad=scale,
        block_px=block_px,
        oversampling=int(sampling.oversampling),
        diffusion_sigma_px=float(sampling.diffusion_sigma_px),
        batch_size=batch_size,
        reference_wavelength_m=wfs_wavelength_m,
    )
