"""Physical camera response chain ``shwfs_ao.detector.physical_camera.v1``.

The chain acts on a batch of lenslet blocks, arrays of shape
``(n_lenslets, block, block)``, in the declared order of
``docs/refactor/DETECTOR_LEVEL_DEVELOPMENT_PROMPT.md`` section 4:

1. optical photoresponse ``r = PRNU * live`` multiplies the source and sky
   photoelectron expectations (input e-; QE was applied once by photometry);
2. ``+ dark_rate_map * exposure`` (hot pixels; not multiplied by PRNU);
3. Poisson source + sky + dark charge (``detector.shot_noise``), plus an
   independently drawn pre-register CIC count (``detector.cic``, EMCCD only);
4. pixel full-well clipping (flag ``pixel_saturated``);
5. EMCCD multiplication register: ``Gamma(n, G)`` for ``n > 0`` in the
   declared high-gain regime (``detector.em_gain``), exactly zero for
   ``n = 0``, deterministic at ``G = 1``; register capacity clip (flag
   ``register_saturated``);
6. electronic coupling ``K`` on the realized charge-equivalent signal, zero
   boundary at the block edge, outward loss reported;
7. read noise, output-referred, per-pixel map for CMOS (``detector.read_noise``);
8. non-linearity ``y + sum c_k y**(k+2)`` (output e-);
9. conversion gain (output e-/ADU, per pixel for CMOS), bias and fixed-pattern
   offsets;
10. ADC rounding (``numpy.rint``, half to even) and digital clipping to
    ``[0, 2**bits - 1]`` (flag ``digital_saturated``).  On the reference
    path the quantizer is its expectation under the declared read-noise
    dither (:func:`dithered_rounding_expectation`).  With the ADC disabled
    the raw readout stays an analog value in ``output_e_equivalent`` units:
    ``y / m + (bias + offset) * g`` with ``m`` the relative gain multiplier and
    ``g`` the scalar conversion gain.

``include_noise=False`` is the deterministic reference path: Poisson charge
is replaced by its mean, CIC by its mean rate, the register by ``G * n`` and
read noise by zero; every deterministic stage is retained.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import math

import numpy as np

from .camera import (
    EM_GAIN_GAMMA_MAX,
    EM_GAIN_GAMMA_MIN,
    PHYSICAL_RESPONSE_MODEL,
    CameraConfig,
)


__all__ = (
    "PhysicalCameraError",
    "PhysicalFrameBatch",
    "GeneratorProvider",
    "POISSON_ROUNDOFF_FLOOR",
    "apply_physical_camera",
    "apply_coupling",
    "sample_em_register",
    "dithered_rounding_expectation",
)


GeneratorProvider = Callable[[int, str], np.random.Generator]
# Same convention as the compatibility path: expectations below this fraction
# of the declared per-lenslet budget are numerical roundoff, sampled as zero,
# so variate consumption does not depend on host FFT/MFT roundoff.
POISSON_ROUNDOFF_FLOOR = 64.0 * float(np.finfo(float).eps)


class PhysicalCameraError(ValueError):
    """Raised when physical camera inputs are inconsistent."""


@dataclass(frozen=True)
class PhysicalFrameBatch:
    """Raw readout and expectations of a batch of lenslet blocks."""

    raw: np.ndarray
    raw_unit: str
    expected_source_e: np.ndarray
    expected_background_e: np.ndarray
    expected_cic_e: float
    optical_response: np.ndarray
    pixel_saturated: np.ndarray
    register_saturated: np.ndarray
    digital_saturated: np.ndarray
    coupling_outflow_output_e: np.ndarray
    response_model: str = PHYSICAL_RESPONSE_MODEL


def sample_em_register(
    counts: np.ndarray,
    gain: float,
    generator: np.random.Generator,
) -> np.ndarray:
    """EM register output for integer input electron counts (Basden et al. 2003).

    In the declared high-gain regime the output for ``n > 0`` input electrons
    is ``Gamma(shape=n, scale=G)`` (mean ``G n``, variance ``G**2 n``); ``n = 0``
    gives exactly zero and draws nothing.  At ``G = 1`` the register is a
    deterministic identity.  Fed by Poisson charge of mean ``mu`` the output
    has mean ``G mu`` and variance ``2 G**2 mu`` (excess factor ``F**2 = 2``).
    """

    values = np.asarray(counts, dtype=float)
    if np.any(values < 0.0) or np.any(values != np.floor(values)):
        raise PhysicalCameraError("register input must be non-negative integer counts.")
    if float(gain) == 1.0:
        return values.copy()
    if not EM_GAIN_GAMMA_MIN <= float(gain) <= EM_GAIN_GAMMA_MAX:
        raise PhysicalCameraError("em gain outside the declared Gamma regime.")
    output = np.zeros_like(values)
    positive = values > 0.0
    if np.any(positive):
        output[positive] = generator.gamma(values[positive], float(gain))
    return output


DITHER_SERIES_MIN_SIGMA_ADU = 0.05


def dithered_rounding_expectation(analog_adu: np.ndarray, sigma_adu: np.ndarray | float) -> np.ndarray:
    """``E[round(x + n)]`` for Gaussian dither ``n ~ N(0, sigma**2)``, in ADU.

    With ``x - round(x)`` expanded as a Fourier series of the sawtooth,

        E[round(x + n)] = x + sum_k (-1)**k sin(2 pi k x) exp(-2 pi**2 k**2 sigma**2) / (pi k),

    truncated where the next term is below 1e-16.  Pixels with
    ``sigma < 0.05`` ADU (a practically noiseless quantizer, where the series
    would need hundreds of terms) use ``rint``.  At ``sigma = 0.5`` ADU the
    expectation differs from ``x`` by at most 2.3e-3 ADU.
    """

    x = np.asarray(analog_adu, dtype=float)
    sigma = np.broadcast_to(np.asarray(sigma_adu, dtype=float), x.shape)
    result = np.rint(x)
    smooth = sigma >= DITHER_SERIES_MIN_SIGMA_ADU
    if not np.any(smooth):
        return result
    xs = x[smooth]
    ss = sigma[smooth]
    terms = int(math.ceil(math.sqrt(37.0 / (2.0 * math.pi**2 * float(np.min(ss)) ** 2))))
    value = xs.copy()
    for k in range(1, terms + 1):
        value += ((-1.0) ** k / (math.pi * k)) * np.sin(2.0 * math.pi * k * xs) * np.exp(
            -2.0 * math.pi**2 * k**2 * ss**2
        )
    result[smooth] = value
    return result


def apply_coupling(signal: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    """Apply a 3x3 kernel on each block with a zero boundary outside it.

    ``out[i, j] = sum_{a,b} K[a, b] * signal[i - (a - 1), j - (b - 1)]``: the
    centre weight stays in a pixel and each off-centre weight moves charge to
    the neighbour in that direction.  For a symmetric kernel this is the same
    as correlation.  Charge pushed across the block edge is lost.
    """

    values = np.asarray(signal, dtype=float)
    if values.ndim != 3:
        raise PhysicalCameraError("signal must have shape (n, rows, columns).")
    padded = np.pad(values, ((0, 0), (1, 1), (1, 1)))
    rows, columns = values.shape[1:]
    result = np.zeros_like(values)
    for a in range(3):
        for b in range(3):
            weight = float(kernel[a, b])
            if weight == 0.0:
                continue
            # Source pixel (i - (a-1), j - (b-1)) sits at padded index
            # (i - a + 2, j - b + 2).
            result += weight * padded[
                :, 2 - a : 2 - a + rows, 2 - b : 2 - b + columns
            ]
    return result


def apply_physical_camera(
    source_e: np.ndarray,
    sky_e_per_pixel: np.ndarray | float,
    camera: CameraConfig,
    maps: dict[str, np.ndarray | None],
    *,
    exposure_s: float,
    include_noise: bool,
    generators: GeneratorProvider | None,
    poisson_floor_e: np.ndarray | float,
) -> PhysicalFrameBatch:
    """Run the declared physical chain on a batch of lenslet blocks.

    ``source_e`` is the expected detected-source photoelectron image per block
    (pre-photoresponse, input e-), ``sky_e_per_pixel`` the expected sky
    photoelectrons per pixel (scalar or one value per block).  ``maps`` holds
    the persistent map arrays for exactly these blocks (``CameraMaps.subset``).
    ``generators(i, domain)`` returns block ``i``'s generator for a stage
    domain; it is required when ``include_noise`` is true.
    """

    if not isinstance(camera, CameraConfig):
        raise PhysicalCameraError("camera must be a CameraConfig.")
    source = np.asarray(source_e, dtype=float)
    if source.ndim != 3 or not np.all(np.isfinite(source)) or np.any(source < 0.0):
        raise PhysicalCameraError(
            "source_e must be a finite non-negative (n, rows, columns) array."
        )
    n = source.shape[0]
    if include_noise and generators is None:
        raise PhysicalCameraError("a noisy frame needs a generator provider.")
    sky = _per_block(sky_e_per_pixel, n, "sky_e_per_pixel")
    floor = _per_block(poisson_floor_e, n, "poisson_floor_e")

    # 1. optical photoresponse (PRNU and dead pixels), source and sky only.
    response = np.ones_like(source) if maps.get("prnu") is None else np.array(maps["prnu"], dtype=float)
    dead = maps.get("dead")
    if dead is not None:
        response[np.asarray(dead, dtype=bool)] = 0.0
    expected_source = source * response
    expected_sky = sky[:, None, None] * response
    # 2. dark-current map times exposure (hot pixels), independent of PRNU.
    dark_rate = np.full(source.shape, float(camera.dark_e_per_s))
    hot = maps.get("hot")
    if hot is not None:
        dark_rate[np.asarray(hot, dtype=bool)] = float(camera.hot_pixel_dark_e_per_s)
    expected_background = expected_sky + dark_rate * float(exposure_s)
    mean_charge = expected_source + expected_background
    cic_mean = float(camera.cic_e_per_pixel_read)

    # 3. charge: Poisson source/sky/dark plus independent pre-register CIC.
    if include_noise:
        assert generators is not None
        charge = np.empty_like(mean_charge)
        for index in range(n):
            lam = mean_charge[index]
            lam = np.where(lam < floor[index], 0.0, lam)
            charge[index] = generators(index, "detector.shot_noise").poisson(lam)
            if cic_mean > 0.0:
                charge[index] += generators(index, "detector.cic").poisson(
                    cic_mean, size=lam.shape
                )
    else:
        charge = mean_charge + cic_mean

    # 4. pixel full well (integer capacity in the noisy path).
    full_well = float(camera.full_well_e)
    capacity = np.floor(full_well) if include_noise else full_well
    pixel_saturated = charge > capacity
    charge = np.minimum(charge, capacity)

    # 5. EMCCD multiplication register and register capacity.
    register_saturated = np.zeros(charge.shape, dtype=bool)
    if camera.model == "emccd":
        gain = float(camera.em_gain)
        if camera.is_multiplying:
            if include_noise:
                assert generators is not None
                output = np.empty_like(charge)
                for index in range(n):
                    output[index] = sample_em_register(
                        charge[index], gain, generators(index, "detector.em_gain")
                    )
            else:
                output = gain * charge
        else:
            output = charge.copy()
        assert camera.register_full_well_e is not None
        register_capacity = float(camera.register_full_well_e)
        register_saturated = output > register_capacity
        output = np.minimum(output, register_capacity)
    else:
        output = charge

    # 6. electronic coupling on realized signals, zero boundary.
    if camera.has_coupling:
        coupled = apply_coupling(output, camera.coupling_kernel)
        outflow = np.sum(output, axis=(1, 2)) - np.sum(coupled, axis=(1, 2))
        signal = coupled
    else:
        outflow = np.zeros(n)
        signal = np.array(output, dtype=float, copy=True)

    # 7. read noise (output-referred, per-pixel map for CMOS).
    if include_noise and camera.read_noise_e > 0.0:
        assert generators is not None
        multiplier = maps.get("read_noise_multiplier")
        for index in range(n):
            sigma: np.ndarray | float = float(camera.read_noise_e)
            if multiplier is not None:
                sigma = sigma * np.asarray(multiplier[index], dtype=float)
            signal[index] += generators(index, "detector.read_noise").normal(
                0.0, 1.0, size=signal.shape[1:]
            ) * sigma

    # 8. declared non-linearity in output electrons.
    if camera.nonlinearity_coefficients:
        base = signal
        signal = base.copy()
        for order, coefficient in enumerate(camera.nonlinearity_coefficients):
            signal += coefficient * base ** (order + 2)

    # 9. conversion gain, bias and fixed-pattern offsets.
    gain_multiplier = maps.get("gain_multiplier")
    relative = 1.0 if gain_multiplier is None else np.asarray(gain_multiplier, dtype=float)
    offsets = maps.get("offset_adu")
    offset_adu = 0.0 if offsets is None else np.asarray(offsets, dtype=float)
    conversion = float(camera.conversion_gain_e_per_adu)
    analog_adu = signal / (conversion * relative) + float(camera.bias_adu) + offset_adu

    # 10. ADC.  The noisy path rounds the realized analog value.  The
    # reference path keeps the quantizer as its expectation under the
    # declared read-noise dither, E[round(x + n)], n ~ N(0, sigma_adu**2):
    # exactly rint for a noiseless readout, smooth otherwise (decision D00-3a).
    if camera.adc_bits is not None:
        assert camera.adc_max_code is not None
        maximum = float(camera.adc_max_code)
        if include_noise:
            codes = np.rint(analog_adu)
        else:
            read_map = maps.get("read_noise_multiplier")
            sigma_e = float(camera.read_noise_e) * (
                1.0 if read_map is None else np.asarray(read_map, dtype=float)
            )
            codes = dithered_rounding_expectation(analog_adu, sigma_e / (conversion * relative))
        digital_saturated = (codes > maximum) | (codes < 0.0)
        raw = np.clip(codes, 0.0, maximum)
    else:
        digital_saturated = np.zeros(signal.shape, dtype=bool)
        raw = analog_adu * conversion
    if not np.all(np.isfinite(raw)):
        raise PhysicalCameraError("raw readout must be finite.")
    return PhysicalFrameBatch(
        raw=raw,
        raw_unit=camera.raw_unit,
        expected_source_e=expected_source,
        expected_background_e=expected_background,
        expected_cic_e=cic_mean,
        optical_response=response,
        pixel_saturated=np.asarray(pixel_saturated, dtype=bool),
        register_saturated=np.asarray(register_saturated, dtype=bool),
        digital_saturated=np.asarray(digital_saturated, dtype=bool),
        coupling_outflow_output_e=np.asarray(outflow, dtype=float),
    )


def _per_block(value: np.ndarray | float, n: int, label: str) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if array.ndim == 0:
        array = np.full(n, float(array))
    if array.shape != (n,) or not np.all(np.isfinite(array)) or np.any(array < 0.0):
        raise PhysicalCameraError(
            f"{label} must be a non-negative scalar or one value per block."
        )
    return array
