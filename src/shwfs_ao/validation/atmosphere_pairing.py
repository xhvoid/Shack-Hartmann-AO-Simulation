"""Physical-coordinate checks of the paired layered-atmosphere input (T2, G1).

The native layered atmosphere pairs two pupil samplings by drawing the
periodic band on a reference grid and reading each screen's own signed FFT
indices (:mod:`shwfs_ao.backends.native.layered_atmosphere`).  Equal signed
indices are equal *physical* frequencies only when the screens have the same
physical period.  This module quantifies what the pairing does in physical
coordinates:

* :func:`physical_frequency_dilation`: the ratio of the two screens' periods,
  i.e. the factor by which the frequency of index ``k`` differs between them
  (``N/(N-1)`` effects under the default ``pupil_array`` rule, exactly 1 under
  ``pupil_diameter``), and the phase error that dilation produces across the
  pupil at the coarse band edge;
* :func:`band_edge_power_fraction` and :func:`common_band_power_fraction`:
  the share of a screen's band power in its own Nyquist row and column
  (the modes a coarser grid keeps without their conjugate partner) and inside
  a common band;
* :func:`band_field_on_coordinates` and :func:`compare_paired_band_fields`:
  the periodic-band phase of one layer evaluated at arbitrary physical
  coordinates (the continuous function the FFT evaluation samples), and the
  comparison of two paired settings on common coordinates restricted to the
  band both represent, as a relative RMS difference.  Under the
  ``pupil_diameter`` rule with a common reference draw the difference is
  rounding; under the default rule it is the dilation's signature.

These are validation helpers; they change nothing in the atmosphere.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
import math
from typing import Any

import numpy as np

# The validation package depends on no backend at import time (the dashed
# ``VALIDATION -> NATIVE`` arrow of ``docs/architecture.md``); the layered
# atmosphere's classes and band helpers are imported where they are used, as
# ``cross_backend`` does for its suites.  Parameters that take those objects
# are therefore typed ``Any`` here and checked at call time.


__all__ = (
    "PairingError",
    "DilationReport",
    "physical_frequency_dilation",
    "band_edge_power_fraction",
    "common_band_power_fraction",
    "band_field_on_coordinates",
    "compare_paired_band_fields",
)


class PairingError(ValueError):
    """Raised when two configurations cannot be compared as a pair."""


@dataclass(frozen=True)
class DilationReport:
    """Physical-frequency relation of two screens at equal signed FFT index."""

    coarse_screen_size: int
    fine_screen_size: int
    coarse_period_m: float
    fine_period_m: float
    frequency_ratio_fine_over_coarse: float
    relative_dilation: float
    coarse_band_edge_index: int
    phase_error_at_pupil_edge_rad: float
    exact: bool

    def to_record(self) -> dict[str, Any]:
        return {
            "coarse_screen_size": self.coarse_screen_size,
            "fine_screen_size": self.fine_screen_size,
            "coarse_period_m": self.coarse_period_m,
            "fine_period_m": self.fine_period_m,
            "frequency_ratio_fine_over_coarse_at_equal_index": self.frequency_ratio_fine_over_coarse,
            "relative_dilation": self.relative_dilation,
            "coarse_band_edge_index": self.coarse_band_edge_index,
            "phase_error_at_pupil_edge_rad": self.phase_error_at_pupil_edge_rad,
            "exact_physical_pairing": self.exact,
        }


def _check_pair(coarse: Any, fine: Any) -> None:
    from ..backends.native.layered_atmosphere import LayeredFrozenFlowAtmosphereConfig

    for config in (coarse, fine):
        if not isinstance(config, LayeredFrozenFlowAtmosphereConfig):
            raise PairingError("both inputs must be LayeredFrozenFlowAtmosphereConfig values.")
    if coarse.screen_size > fine.screen_size:
        raise PairingError("the first configuration must be the coarser screen.")
    if not math.isclose(coarse.pupil_diameter_m, fine.pupil_diameter_m, rel_tol=1.0e-12, abs_tol=0.0):
        raise PairingError("paired configurations must share the pupil diameter.")


def physical_frequency_dilation(coarse: Any, fine: Any) -> DilationReport:
    """How the frequency of a given signed index differs between two screens.

    ``frequency_ratio = P_coarse / P_fine`` (the fine screen's frequency at
    index ``k`` over the coarse one's).  The phase error of the coarse
    band-edge mode ``k = S_c // 2`` between the two readings grows across the
    pupil as ``2 pi k x (1/P_fine - 1/P_coarse)``; the value at ``x = D`` is
    reported.  ``exact`` is true when the periods agree to rounding.  Both
    inputs must be ``LayeredFrozenFlowAtmosphereConfig`` values.
    """

    _check_pair(coarse, fine)
    ratio = coarse.screen_period_m / fine.screen_period_m
    edge = coarse.screen_size // 2
    phase = abs(2.0 * math.pi * edge * coarse.pupil_diameter_m * (1.0 / fine.screen_period_m - 1.0 / coarse.screen_period_m))
    return DilationReport(
        coarse_screen_size=coarse.screen_size,
        fine_screen_size=fine.screen_size,
        coarse_period_m=coarse.screen_period_m,
        fine_period_m=fine.screen_period_m,
        frequency_ratio_fine_over_coarse=ratio,
        relative_dilation=ratio - 1.0,
        coarse_band_edge_index=edge,
        phase_error_at_pupil_edge_rad=phase,
        exact=math.isclose(ratio, 1.0, rel_tol=1.0e-12, abs_tol=0.0),
    )


def band_edge_power_fraction(config: Any) -> float:
    """Band power in the screen's own Nyquist row and column over its total band power.

    Zero for an odd screen (no Nyquist index).  These are the modes a coarser
    screen keeps at index ``-S/2`` without the ``+S/2`` partner a finer screen
    holds (section 2.5 of the design note).
    """

    from ..backends.native.layered_atmosphere import (
        LayeredFrozenFlowAtmosphereConfig,
        _periodic_band_power,
        signed_fft_indices,
    )

    if not isinstance(config, LayeredFrozenFlowAtmosphereConfig):
        raise PairingError("config must be a LayeredFrozenFlowAtmosphereConfig.")
    size = config.screen_size
    if size % 2:
        return 0.0
    frequencies = np.fft.fftfreq(size, d=config.delta_m)
    power = _periodic_band_power(config, frequencies)
    nyquist = signed_fft_indices(size) == -(size // 2)
    edge = nyquist[:, None] | nyquist[None, :]
    total = float(np.sum(power))
    return 0.0 if total <= 0.0 else float(np.sum(power[edge])) / total


def common_band_power_fraction(config: Any, limit: int) -> float:
    """Band power inside the common band of a ``limit``-sample screen over the total band power."""

    from ..backends.native.layered_atmosphere import (
        LayeredFrozenFlowAtmosphereConfig,
        _periodic_band_power,
        common_band_mask,
    )

    if not isinstance(config, LayeredFrozenFlowAtmosphereConfig):
        raise PairingError("config must be a LayeredFrozenFlowAtmosphereConfig.")
    size = config.screen_size
    frequencies = np.fft.fftfreq(size, d=config.delta_m)
    power = _periodic_band_power(config, frequencies)
    total = float(np.sum(power))
    return 0.0 if total <= 0.0 else float(np.sum(power * common_band_mask(size, limit))) / total


def _layer_coefficients(atmosphere: Any, layer_index: int) -> np.ndarray:
    from ..backends.native.layered_atmosphere import LayeredFrozenFlowAtmosphere

    if not isinstance(atmosphere, LayeredFrozenFlowAtmosphere):
        raise PairingError("atmosphere must be a LayeredFrozenFlowAtmosphere.")
    count = len(atmosphere.config.layers)
    if isinstance(layer_index, bool) or not isinstance(layer_index, int) or not 0 <= layer_index < count:
        raise PairingError(f"layer_index must be an integer in [0, {count}).")
    iterator: Iterator[np.ndarray] = atmosphere._layer_band_coefficients()
    for index, coefficients in enumerate(iterator):
        if index == layer_index:
            return np.array(coefficients, copy=True)
    raise PairingError("the layer's coefficients were not produced.")  # pragma: no cover


def band_field_on_coordinates(
    atmosphere: Any,
    x_m: np.ndarray,
    y_m: np.ndarray,
    *,
    layer_index: int = 0,
    band_limit_screen_size: int | None = None,
) -> np.ndarray:
    """The periodic-band phase of one layer at physical coordinates (rad, time 0).

    ``phi(x, y) = Re sum_{k,l} c_kl exp(2 pi i (k x + l y) / P) / S**2`` over
    the screen's signed indices, which coincides with the atmosphere's own
    inverse-FFT evaluation at the grid points ``x = i delta``: the continuous
    function the FFT samples (the ``S**2`` undoes the inverse-FFT scaling the
    coefficients carry).  ``band_limit_screen_size`` restricts the sum to the
    common band of that screen size, so two settings can be compared on the
    band both represent.  Separable evaluation: ``O(M S**2 + M**2 S)`` for
    ``M`` coordinates per axis.  ``atmosphere`` must be a
    ``LayeredFrozenFlowAtmosphere``.
    """

    from ..backends.native.layered_atmosphere import common_band_mask

    coefficients = _layer_coefficients(atmosphere, layer_index)
    config = atmosphere.config
    size = config.screen_size
    if band_limit_screen_size is not None:
        if band_limit_screen_size > size:
            raise PairingError("band_limit_screen_size must not exceed the screen size.")
        coefficients = coefficients * common_band_mask(size, band_limit_screen_size)
    frequencies = np.fft.fftfreq(size, d=config.delta_m)
    x = np.asarray(x_m, dtype=float).reshape(-1)
    y = np.asarray(y_m, dtype=float).reshape(-1)
    if not (np.all(np.isfinite(x)) and np.all(np.isfinite(y))):
        raise PairingError("coordinates must be finite.")
    waves_x = np.exp(2j * np.pi * np.outer(x, frequencies))
    waves_y = np.exp(2j * np.pi * np.outer(y, frequencies))
    field = (waves_y @ coefficients @ waves_x.T).real / size**2
    return field


def compare_paired_band_fields(
    coarse: Any,
    fine: Any,
    *,
    layer_index: int = 0,
    points_per_axis: int = 48,
) -> dict[str, Any]:
    """Relative RMS difference of two paired settings' common-band fields on common coordinates.

    Both fields are restricted to the common band of the coarser screen
    (``|k| <= (S_c - 1) // 2``) and evaluated on a ``points_per_axis``
    square grid spanning the pupil diameter (physical metres, the same points
    for both).  Returns the RMS of each field, the RMS of their difference,
    the relative difference and the dilation report; a relative difference at
    rounding level means an exact physical pairing of the represented band.
    """

    from ..backends.native.layered_atmosphere import LayeredFrozenFlowAtmosphere

    if not isinstance(coarse, LayeredFrozenFlowAtmosphere) or not isinstance(fine, LayeredFrozenFlowAtmosphere):
        raise PairingError("both inputs must be LayeredFrozenFlowAtmosphere instances.")
    dilation = physical_frequency_dilation(coarse.config, fine.config)
    limit = coarse.config.screen_size
    count = int(points_per_axis)
    if count < 2:
        raise PairingError("points_per_axis must be at least 2.")
    coordinates = np.linspace(0.0, coarse.config.pupil_diameter_m, count)
    field_coarse = band_field_on_coordinates(coarse, coordinates, coordinates, layer_index=layer_index, band_limit_screen_size=limit)
    field_fine = band_field_on_coordinates(fine, coordinates, coordinates, layer_index=layer_index, band_limit_screen_size=limit)
    rms_coarse = float(np.sqrt(np.mean(field_coarse**2)))
    rms_fine = float(np.sqrt(np.mean(field_fine**2)))
    difference = float(np.sqrt(np.mean((field_fine - field_coarse) ** 2)))
    scale = max(rms_coarse, rms_fine)
    return {
        "layer_index": int(layer_index),
        "points_per_axis": count,
        "common_band_screen_size": limit,
        "coarse_rms_rad": rms_coarse,
        "fine_rms_rad": rms_fine,
        "difference_rms_rad": difference,
        "relative_difference": None if scale == 0.0 else difference / scale,
        "dilation": dilation.to_record(),
    }
