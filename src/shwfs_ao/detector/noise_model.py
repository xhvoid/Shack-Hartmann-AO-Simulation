"""Extended first-order centroid-noise model ``detector_covariance_v2`` (DET-07).

The existing ``first_order`` and ``legacy_spot_width`` models of
:func:`~shwfs_ao.detector.validity.centroid_quality` keep their equations.
This model serves the physical camera path.  It propagates covariance
through the declared response and pixel processing to a plain
center-of-gravity estimate, using local operators and direct Jacobian
contractions, never a dense full-detector covariance.

Notation, per lenslet block (input-referred electrons unless stated):

* ``mu_k = s_k + b_k + C``: expected charge of pixel ``k`` (source after
  photoresponse, sky after photoresponse plus dark, and pre-register CIC);
* ``q``: register output, ``Var(q_k) = G**2 F**2 mu_k`` (``F**2 = 2`` in the
  Gamma high-gain register, else 1, with ``G = 1`` without multiplication);
* ``y = K q + r + d``: coupled output signal plus read noise
  (``sigma_k**2``) and quantization (``(g m_k)**2 / 12`` with the ADC on,
  white-noise approximation, output electrons);
* ``Xt_k = y_k / (G m'_k)``: the raw readout converted to input electrons,
  where ``m'`` is the relative gain multiplier left in the data (one when the
  gain map is applied as known per-pixel conversion gain);
* ``Z = (Xt - bt) / f``: processed values with subtracted background ``bt``
  and flat ``f``; ``Y = P Z``: bad-pixel policy (zero weight or 4-neighbour
  mean).  ``bt`` is the realized additive master the processing actually
  subtracts (its pedestal removed, converted to input electrons), so the
  conditional mean, Jacobian, flux and SNR are those of the measurements;
* the centroid ``c = sum_W x_k Y_k / sum_W Y_k`` over the centroid window
  ``W``, with Jacobian ``j_k = (x_k - c) / T`` on ``W`` and ``T = sum_W E[Y]``.

With ``u = P^T j`` and ``w = u / (f G m')`` the temporal variance
conditional on fixed calibration products is

    Var_t(c) = sum_k w_k**2 (sigma_k**2 + q_k**2 / 12)
             + G**2 F**2 sum_l mu_l (K^T w)_l**2 .

The calibration-ensemble variance over regenerated products is linearized
about the nominal (expected) background instead.  It adds the
background-master error (a sky or dark frame's covariance over its frame
count) and the flat error (flat frames minus the shared dark mean; the
normalization constant is common-mode and moves no centroid), with the
cross-covariance of the dark frames the background and the flat share when
no sky frames are taken.  It is a persistent per-run bias, not frame noise.

Scalar limiting case (identity coupling, independent pixels, known gain and
flat): ``Var(Z_k) = F**2 (S_k + B_k + C) + (sigma_k / G)**2 + q_k**2 / 12``
with ``q_k`` the ADC step in input electrons.

The model is first order.  It flags (``supported = False``) and reports
:data:`~shwfs_ao.detector.validity.UNDEFINED_CENTROID_SIGMA_PX` outside its
declared domain: a thresholded or minimum-subtracted estimator, negative
clipping, expected saturation (pixel, register or digital), a declared
non-linearity, coarse quantization (read noise below half an ADC step), an
ADC code within :data:`ADC_HEADROOM_SIGMA` noise sigmas of either ADC limit
(bias and offset map included), or a total-flux signal-to-noise ratio below
:data:`MIN_DENOMINATOR_SNR`.

Version 2 (2026-10-16 review, R2 and R4) replaces version 1, which formed the
conditional mean from the ideal background and checked only the upper ADC
limit without offsets.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .camera import CameraConfig
from .centroid import CentroidConfig
from .physical import apply_coupling
from .processing import CalibrationProducts, PixelProcessingConfig, interpolation_matrix_rows
from .validity import UNDEFINED_CENTROID_SIGMA_PX


__all__ = (
    "UNCERTAINTY_MODEL_ID",
    "MIN_DENOMINATOR_SNR",
    "MIN_READ_NOISE_ADU_FOR_WHITE_QUANTIZATION",
    "SATURATION_MARGIN",
    "ADC_HEADROOM_SIGMA",
    "ExtendedCentroidQuality",
    "NoiseTerms",
    "noise_terms",
    "detector_covariance_quality",
    "quadratic_form",
)


UNCERTAINTY_MODEL_ID = "detector_covariance_v2"
# The center-of-gravity ratio is linearized about T.  Monte Carlo (E1, read-
# noise-limited CCD window) measures the first-order sigma low by roughly
# 4 / SNR_T**2: 12 % at SNR_T = 5.6, 7 % at 7.4, 3.5 % at 11.8.  Below this
# total-flux SNR the model is flagged unsupported instead of reporting an
# optimistic sigma.
MIN_DENOMINATOR_SNR = 7.0
# White quantization noise q^2/12 needs a signal dithered by at least about
# half an ADC step of read noise.
MIN_READ_NOISE_ADU_FOR_WHITE_QUANTIZATION = 0.5
# Expected signal above this fraction of a capacity is treated as saturating.
SATURATION_MARGIN = 0.9
# The linear model needs every block pixel's expected ADC code at least this
# many temporal noise sigmas inside both ADC limits; otherwise clipping at
# code 0 or at the top code makes the response non-linear.  At 5 sigma a
# Gaussian tail clips with probability below 3e-7 per pixel read.
ADC_HEADROOM_SIGMA = 5.0


@dataclass(frozen=True)
class NoiseTerms:
    """Per-pixel ingredients of a frame covariance, batch-shaped ``(n, R, C)``."""

    mu_e: np.ndarray
    gain_squared_excess: float
    white_output_variance_e2: np.ndarray
    output_scale: np.ndarray
    kernel: np.ndarray | None


@dataclass(frozen=True)
class ExtendedCentroidQuality:
    """Batch diagnostics of the ``detector_covariance_v2`` model."""

    total_flux_e: np.ndarray
    background_e: np.ndarray
    peak_snr: np.ndarray
    total_snr: np.ndarray
    centroid_sigma_px: np.ndarray
    centroid_sigma_xy_px: np.ndarray
    calibration_sigma_px: np.ndarray
    calibration_sigma_xy_px: np.ndarray
    supported: np.ndarray
    expected_processed_e: np.ndarray
    centroid_covariance_xy_px2: np.ndarray | None = None


def noise_terms(
    camera: CameraConfig,
    maps: dict[str, np.ndarray | None],
    mu_e: np.ndarray,
    *,
    gain_left_in_data: np.ndarray | float,
) -> NoiseTerms:
    """Covariance ingredients of one kind of frame with expected charge ``mu``."""

    shape = np.asarray(mu_e).shape
    read = float(camera.read_noise_e) * (
        np.ones(shape)
        if maps.get("read_noise_multiplier") is None
        else np.asarray(maps["read_noise_multiplier"], dtype=float)
    )
    white = read**2
    if camera.adc_bits is not None:
        relative = (
            np.ones(shape)
            if maps.get("gain_multiplier") is None
            else np.asarray(maps["gain_multiplier"], dtype=float)
        )
        step = float(camera.conversion_gain_e_per_adu) * relative
        white = white + step**2 / 12.0
    gain = float(camera.em_gain)
    scale = gain * np.broadcast_to(np.asarray(gain_left_in_data, dtype=float), shape)
    return NoiseTerms(
        mu_e=np.asarray(mu_e, dtype=float),
        gain_squared_excess=gain**2 * camera.excess_noise_factor_squared,
        white_output_variance_e2=white,
        output_scale=np.array(scale, dtype=float),
        kernel=camera.coupling_kernel if camera.has_coupling else None,
    )


def quadratic_form(terms: NoiseTerms, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Per-block ``x^T Cov(Xt) y`` for sensitivity maps in input-e space."""

    xs = np.asarray(x, dtype=float) / terms.output_scale
    ys = np.asarray(y, dtype=float) / terms.output_scale
    white = np.sum(xs * ys * terms.white_output_variance_e2, axis=(1, 2))
    if terms.kernel is not None:
        xs = apply_coupling(xs, terms.kernel)  # symmetric kernel: K^T = K
        ys = apply_coupling(ys, terms.kernel)
    shot = terms.gain_squared_excess * np.sum(terms.mu_e * xs * ys, axis=(1, 2))
    return white + shot


def _back_project(j: np.ndarray, bad: np.ndarray | None, policy: str) -> np.ndarray:
    """``u = P^T j`` for the declared bad-pixel policy."""

    u = np.array(j, dtype=float, copy=True)
    if bad is None or not np.any(bad):
        return u
    if policy == "zero_weight":
        u[bad] = 0.0
        return u
    n, rows, columns = u.shape
    flat_u = u.reshape(n, -1)
    flat_j = np.asarray(j, dtype=float).reshape(n, -1)
    for index in range(n):
        if not np.any(bad[index]):
            continue
        for pixel, neighbours, weight in interpolation_matrix_rows(bad[index]):
            for neighbour in neighbours:
                flat_u[index, neighbour] += weight * flat_j[index, pixel]
        flat_u[index, bad[index].reshape(-1)] = 0.0
    return u


def detector_covariance_quality(
    *,
    expected_source_e: np.ndarray,
    expected_background_e: np.ndarray,
    camera: CameraConfig,
    maps: dict[str, np.ndarray | None],
    products: CalibrationProducts | None,
    processing: PixelProcessingConfig,
    centroid_config: CentroidConfig,
    window: tuple[slice, slice],
    sky_e_per_pixel: np.ndarray | float,
    dark_e_map: np.ndarray,
    optical_response: np.ndarray,
    flat_level_e: float | None = None,
    indices: np.ndarray | None = None,
) -> ExtendedCentroidQuality:
    """Model expectation diagnostics and centroid covariance for a batch.

    ``expected_source_e`` and ``expected_background_e`` are the camera's
    expectations (after photoresponse; background is sky plus dark).
    ``dark_e_map`` is dark current times exposure and ``optical_response``
    the PRNU/live response, both per pixel.  Gates use these model
    expectations, not a noisy estimate.
    """

    source = np.asarray(expected_source_e, dtype=float)
    background = np.asarray(expected_background_e, dtype=float)
    n = source.shape[0]
    cic = float(camera.cic_e_per_pixel_read)
    select = slice(None) if indices is None else indices
    sky = np.asarray(sky_e_per_pixel, dtype=float)
    sky = np.full(n, float(sky)) if sky.ndim == 0 else sky
    relative = (
        np.ones(source.shape)
        if maps.get("gain_multiplier") is None
        else np.asarray(maps["gain_multiplier"], dtype=float)
    )
    if processing.mode == "raw_readout":
        gain_left = relative
        flat = None
        bad = None
    else:
        assert products is not None
        gain_left = (
            np.ones(source.shape)
            if processing.gain_treatment == "known_per_pixel"
            else relative
        )
        flat = products.flat[select]
        bad = products.bad[select]
    kernel = camera.coupling_kernel if camera.has_coupling else None

    def coupled(values: np.ndarray) -> np.ndarray:
        return values if kernel is None else apply_coupling(values, kernel)

    mu = source + background + cic
    expected_xt = coupled(mu) / gain_left
    offsets = maps.get("offset_adu")
    offset = 0.0 if offsets is None else np.asarray(offsets, dtype=float)
    # Expected background removed by processing, input-e equivalent.
    if processing.mode == "raw_readout":
        if camera.adc_bits is not None:
            pedestal_xt = (float(camera.bias_adu) + offset) * float(
                camera.conversion_gain_e_per_adu
            ) * relative / gain_left / float(camera.em_gain)
        else:
            pedestal_xt = (float(camera.bias_adu) + offset) * float(
                camera.conversion_gain_e_per_adu
            ) / gain_left / float(camera.em_gain)
        subtracted = -pedestal_xt
        nominal_subtracted = subtracted
        flat_values = np.ones(source.shape)
    else:
        assert products is not None
        # The additive master holds a sky product only if these products do:
        # an internal source's ``without_sky_master`` products do not.
        sky_subtracted = products.sky_raw is not None
        bg_mu = dark_e_map + cic + (sky[:, None, None] * optical_response if sky_subtracted else 0.0)
        nominal_subtracted = coupled(bg_mu) / gain_left
        # Conditional on the fixed products: the processing subtracts the
        # realized master, which still carries the bias and offset pedestal
        # that the expected signal ``expected_xt`` leaves out.
        pedestal_raw = float(camera.bias_adu) + offset
        if camera.adc_bits is None:
            pedestal_raw = pedestal_raw * float(camera.conversion_gain_e_per_adu)
        subtracted = (
            np.asarray(products.background_raw[select], dtype=float) - pedestal_raw
        ) * np.asarray(products.conversion_input_e_per_raw[select], dtype=float)
        flat_values = np.asarray(flat, dtype=float)

    rows_slice, cols_slice = window
    window_mask = np.zeros(source.shape[1:], dtype=bool)
    window_mask[rows_slice, cols_slice] = True
    rows_idx, cols_idx = np.nonzero(window_mask)
    x_coord = (cols_idx - cols_slice.start).astype(float)
    y_coord = (rows_idx - rows_slice.start).astype(float)

    def processed_expectation(removed: np.ndarray | float) -> tuple[np.ndarray, np.ndarray]:
        z = (expected_xt - removed) / flat_values
        y = z.copy()
        if bad is not None and np.any(bad):
            if processing.bad_pixel_policy == "zero_weight":
                y[bad] = 0.0
            else:
                from .processing import _interpolate_mean4

                y = _interpolate_mean4(z, bad)
        return z, y

    def window_levers(
        y: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Window total, safe total, and the x, y and total sensitivity maps."""

        window_y = y[:, window_mask].reshape(n, -1)
        window_total = np.sum(window_y, axis=1)
        safe = np.where(window_total > 0.0, window_total, 1.0)
        cx = window_y @ x_coord / safe
        cy = window_y @ y_coord / safe

        def sensitivity(lever: np.ndarray) -> np.ndarray:
            j = np.zeros(source.shape)
            j[:, window_mask] = lever / safe[:, None]
            u = _back_project(j, bad, processing.bad_pixel_policy)
            return u / flat_values

        return (
            window_total,
            safe,
            sensitivity(x_coord[None, :] - cx[:, None]),
            sensitivity(y_coord[None, :] - cy[:, None]),
            sensitivity(np.ones((n, x_coord.size)) * safe[:, None]),
        )

    _, expected_y = processed_expectation(subtracted)
    total, safe_total, jx, jy, jt = window_levers(expected_y)

    terms = noise_terms(camera, maps, mu, gain_left_in_data=gain_left)
    var_x = quadratic_form(terms, jx, jx)
    var_y = quadratic_form(terms, jy, jy)
    cov_xy = quadratic_form(terms, jx, jy)
    var_total = quadratic_form(terms, jt, jt)

    # Calibration-ensemble terms (products regenerated; persistent bias).
    cal_x = np.zeros(n)
    cal_y = np.zeros(n)
    if processing.mode == "estimated":
        # Nominal linearization over regenerated products.
        nominal_z, nominal_y = processed_expectation(nominal_subtracted)
        _, _, nominal_jx, nominal_jy, _ = window_levers(nominal_y)
        # The master protocol of the products actually used (re-review S1):
        # without a sky product the background is the dark mean, shared with
        # the flat.
        assert products is not None
        counts = dict(products.frame_counts)
        sky_frames = products.sky_raw is not None and counts.get("sky", 0) > 0
        n_dark_frames = int(counts.get("dark", processing.n_dark_frames))
        n_flat_frames = int(counts.get("flat", processing.n_flat_frames))
        dark_mu = dark_e_map + cic
        dark_terms = noise_terms(camera, maps, dark_mu, gain_left_in_data=gain_left)
        if sky_frames:
            bg_terms = noise_terms(
                camera,
                maps,
                dark_mu + sky[:, None, None] * optical_response,
                gain_left_in_data=gain_left,
            )
            n_bg = int(counts["sky"])
        else:
            bg_terms = dark_terms
            n_bg = n_dark_frames
        level = processing.flat_level_e if flat_level_e is None else flat_level_e
        flat_terms = noise_terms(
            camera,
            maps,
            dark_mu + level * optical_response,
            gain_left_in_data=gain_left,
        )
        flat_raw = coupled(level * optical_response) / gain_left
        safe_flat_raw = np.where(flat_raw > 0.0, flat_raw, 1.0)
        for lever, target in ((nominal_jx, cal_x), (nominal_jy, cal_y)):
            # dc = -v . d(bt) + a . d(F_raw) with v = u / f (``lever``) and
            # dZ_k/dF_raw_k = -Z_k / F_raw_k, so a = -u Z / F_raw = -v f Z / F_raw.
            a = -lever * flat_values * nominal_z / safe_flat_raw
            variance = quadratic_form(bg_terms, lever, lever) / n_bg
            variance += quadratic_form(flat_terms, a, a) / n_flat_frames
            variance += quadratic_form(dark_terms, a, a) / n_dark_frames
            if not sky_frames:
                # Background = dark mean, flat subtracts the same dark mean:
                # Cov(d bt, d F_raw) = -Cov(dark)/N_dark.
                variance += 2.0 * quadratic_form(dark_terms, lever, a) / n_dark_frames
            target[:] = np.sqrt(np.maximum(variance, 0.0))

    sigma_x = np.sqrt(np.maximum(var_x, 0.0))
    sigma_y = np.sqrt(np.maximum(var_y, 0.0))
    total_snr = np.where(var_total > 0.0, total / np.sqrt(np.maximum(var_total, 1e-300)), 0.0)

    # Peak SNR from the per-pixel processed variance of the brightest window pixel.
    flat_window = expected_y[:, window_mask].reshape(n, -1)
    peak_index = np.argmax(flat_window, axis=1)
    unit = np.zeros(source.shape)
    unit_window = np.zeros((n, x_coord.size))
    unit_window[np.arange(n), peak_index] = 1.0
    unit[:, window_mask] = unit_window
    unit = _back_project(unit, bad, processing.bad_pixel_policy) / flat_values
    peak_variance = quadratic_form(terms, unit, unit)
    peak_signal = flat_window[np.arange(n), peak_index]
    peak_snr = np.where(peak_variance > 0.0, np.maximum(peak_signal, 0.0) / np.sqrt(np.maximum(peak_variance, 1e-300)), 0.0)

    supported = np.ones(n, dtype=bool)
    if centroid_config.estimator != "center_of_gravity" or centroid_config.subtract_minimum:
        supported[:] = False
    if processing.clip_negative or camera.nonlinearity_coefficients:
        supported[:] = False
    if camera.adc_bits is not None:
        read_adu = float(camera.read_noise_e) / (
            float(camera.conversion_gain_e_per_adu) * np.max(relative)
        )
        if read_adu < MIN_READ_NOISE_ADU_FOR_WHITE_QUANTIZATION:
            supported[:] = False
    saturating = np.max(mu, axis=(1, 2)) > SATURATION_MARGIN * float(camera.full_well_e)
    if camera.model == "emccd":
        assert camera.register_full_well_e is not None
        saturating |= np.max(camera.em_gain * mu, axis=(1, 2)) > SATURATION_MARGIN * float(
            camera.register_full_well_e
        )
    if camera.adc_bits is not None:
        assert camera.adc_max_code is not None
        top = float(camera.adc_max_code)
        adu_per_output_e = 1.0 / (float(camera.conversion_gain_e_per_adu) * relative)
        analog = (
            camera.em_gain * coupled(mu) * adu_per_output_e + float(camera.bias_adu) + offset
        )
        saturating |= np.max(analog, axis=(1, 2)) > SATURATION_MARGIN * top
        # Temporal noise of each code: register shot noise plus read noise.
        read_e = float(camera.read_noise_e) * (
            1.0
            if maps.get("read_noise_multiplier") is None
            else np.asarray(maps["read_noise_multiplier"], dtype=float)
        )
        code_sigma = np.sqrt(
            camera.em_gain**2 * camera.excess_noise_factor_squared * coupled(mu) + read_e**2
        ) * adu_per_output_e
        headroom = ADC_HEADROOM_SIGMA * code_sigma
        saturating |= np.any(analog + headroom > top, axis=(1, 2))
        saturating |= np.any(analog - headroom < 0.0, axis=(1, 2))
    supported &= ~saturating
    supported &= total > 0.0
    supported &= total_snr >= MIN_DENOMINATOR_SNR

    sigma = np.where(supported, np.maximum(sigma_x, sigma_y), UNDEFINED_CENTROID_SIGMA_PX)
    sigma = np.minimum(sigma, UNDEFINED_CENTROID_SIGMA_PX)
    calibration = np.where(supported, np.maximum(cal_x, cal_y), UNDEFINED_CENTROID_SIGMA_PX)
    return ExtendedCentroidQuality(
        total_flux_e=total,
        background_e=np.sum(background[:, window_mask], axis=1),
        peak_snr=peak_snr,
        total_snr=total_snr,
        centroid_sigma_px=sigma,
        centroid_sigma_xy_px=np.stack([sigma_x, sigma_y], axis=1),
        calibration_sigma_px=np.minimum(calibration, UNDEFINED_CENTROID_SIGMA_PX),
        calibration_sigma_xy_px=np.stack([cal_x, cal_y], axis=1),
        supported=supported,
        expected_processed_e=expected_y,
        centroid_covariance_xy_px2=np.stack(
            [np.stack([var_x, cov_xy], axis=1), np.stack([cov_xy, var_y], axis=1)], axis=1
        ),
    )
