"""Strict wavefront masking, statistics, and unit conversions.

Canonical optical-path-difference arrays use metres.  Masked operations reject
non-finite illuminated samples while allowing the repository's NaN-outside
pupil convention.  Legacy wrappers that historically ignored invalid pupil
samples implement that compatibility policy outside this module.
"""

from __future__ import annotations

import math as _math

import numpy as _np


_TWO_PI = 2.0 * _np.pi

__all__ = (
    "remove_piston",
    "masked_mean",
    "masked_rms",
    "phase_to_opd",
    "opd_to_phase",
    "mask_outside",
    "validate_masked_finite",
)


def remove_piston(values, mask):
    """Return a float copy with its pupil mean removed and NaN outside."""

    array, pupil = _validated_arrays(values, mask, label="values")
    piston = masked_mean(array, pupil)
    result = array.copy()
    result[pupil] -= piston
    result[~pupil] = _np.nan
    return result


def masked_mean(values, mask):
    """Return the arithmetic mean over a non-empty, finite pupil."""

    array, pupil = _validated_arrays(values, mask, label="values")
    return float(_np.mean(array[pupil]))


def masked_rms(values, mask, remove_mean=True):
    """Return pupil RMS, optionally after removing the pupil mean."""

    array, pupil = _validated_arrays(values, mask, label="values")
    samples = array[pupil]
    if bool(remove_mean):
        samples = samples - masked_mean(array, pupil)
    return float(_np.sqrt(_np.mean(samples**2)))


def phase_to_opd(phase_rad, wavelength_m):
    """Convert phase radians to optical path difference in metres."""

    wavelength = _positive_wavelength(wavelength_m)
    result = _np.array(phase_rad, dtype=float, copy=True)
    result *= wavelength
    result /= _TWO_PI
    return result


def opd_to_phase(opd_m, wavelength_m):
    """Convert optical path difference in metres to phase radians."""

    wavelength = _positive_wavelength(wavelength_m)
    result = _np.array(opd_m, dtype=float, copy=True)
    result *= _TWO_PI
    result /= wavelength
    return result


def mask_outside(values, mask, fill=_np.nan):
    """Return a float copy with samples outside the pupil set to ``fill``."""

    array, pupil = _validated_arrays(values, mask, label="values")
    fill_value = _scalar_float(fill, label="fill")
    result = array.copy()
    result[~pupil] = fill_value
    return result


def validate_masked_finite(values, mask, label):
    """Validate shape, non-empty pupil, and finite illuminated samples."""

    array, pupil = _coerce_arrays(values, mask)
    if not _np.any(pupil):
        raise ValueError("mask must contain at least one pupil sample.")

    samples = array[pupil]
    finite = _np.isfinite(samples)
    name = str(label)
    if not _np.any(finite):
        raise ValueError(f"{name} has no finite samples inside the pupil.")
    if not _np.all(finite):
        finite_fraction = float(_np.mean(finite))
        raise ValueError(
            f"{name} must be finite inside the pupil; "
            f"finite_frac={finite_fraction:.3f}."
        )


def _validated_arrays(values, mask, *, label):
    array, pupil = _coerce_arrays(values, mask)
    validate_masked_finite(array, pupil, label)
    return array, pupil


def _coerce_arrays(values, mask):
    array = _np.asarray(values, dtype=float)
    pupil = _np.asarray(mask, dtype=bool)
    if array.shape != pupil.shape:
        raise ValueError(
            f"values shape {array.shape} does not match mask shape {pupil.shape}."
        )
    return array, pupil


def _positive_wavelength(wavelength_m):
    wavelength = _scalar_float(wavelength_m, label="wavelength_m")
    if not _math.isfinite(wavelength) or wavelength <= 0.0:
        raise ValueError(
            f"wavelength_m must be finite and positive; got {wavelength_m!r}."
        )
    return wavelength


def _scalar_float(value, *, label):
    array = _np.asarray(value)
    if array.shape != ():
        raise ValueError(f"{label} must be a scalar; got shape {array.shape}.")
    try:
        return float(array)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a real scalar; got {value!r}.") from exc
