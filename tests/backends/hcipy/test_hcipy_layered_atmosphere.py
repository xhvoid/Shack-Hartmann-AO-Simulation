"""Native ``native_layered`` against HCIPy ``hcipy_layered`` turbulence statistics.

Both layered atmospheres are built by their registered factories from the
packaged ``eso_turbulence_2m_detector@1`` atmosphere block (r0 = 0.13 m at
500 nm, L0 = 25 m, ten Cn2 fractions and winds) on that profile's 2 m / 72 px
pupil.  They share no random numbers and no screen generator: the native model
sums a periodic Fourier band and analytic low-frequency modes per layer, while
HCIPy extrudes each layer row by row from the exact von Karman covariance
(Assemat et al. 2006).  Only ensemble statistics are therefore compared:

- the pupil variance with piston removed, and with piston and tip/tilt removed;
- the phase structure function D(r) at 2-16 px separations;
- the temporal structure function at 3-30 ms lags, which the per-layer winds
  set, and its co-moving counterpart, which also depends on their direction.

HCIPy is sampled only once every layer has moved a full pupil grid
(t >= 0.5 s), i.e. on extruded screens.  Its initial screens come from a
separate spectral layer whose D(r) is a few percent low at these separations
for a single layer too; that is HCIPy's, not the layer mapping's, and
docs/eso_elt_turbulence_model.md records it.  Separations below 2 px and lags
below 3 ms are left out: there the band-limited native spectrum differs by
construction from HCIPy's exact pixel covariance and bilinear sub-pixel
interpolation (also recorded there).

Native realizations are independent draws at t = 0; that model is stationary
and translates exactly.  HCIPy anchors within one realization are correlated,
so uncertainties use realization means as the independent units.  A comparison
passes only if the HCIPy/native ratio of means is within its tolerance and the
tolerance is at least three standard errors of that ratio, so a pass cannot come
from scatter alone.  A control shows the same tolerances reject a native
atmosphere whose winds are assigned to the wrong layers.  The ``slow`` tier
repeats everything with about four times the samples and tighter tolerances.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Any, Mapping

import numpy as np
import pytest


hcipy = pytest.importorskip("hcipy")

from shwfs_ao.backends.hcipy.factory import HCIPY_SCAO_COMPONENT_FACTORY
from shwfs_ao.backends.native.factory import NATIVE_SCAO_COMPONENT_FACTORY
from shwfs_ao.core.random import NamedRandomStreams
from shwfs_ao.io.configs import load_system_profile


pytestmark = pytest.mark.hcipy

_ROOT_SEED = 2026
_SEPARATIONS_PX = (2, 4, 8, 16)
_TEMPORAL_LAGS_S = (0.003, 0.010, 0.030)
# HCIPy anchors start once the slowest (8 m/s) layer has crossed the 2 m grid.
_FIRST_HCIPY_ANCHOR_S = 0.5
_HCIPY_ANCHOR_SPACING_S = 0.25


@dataclass(frozen=True)
class _Tier:
    native_realizations: int
    hcipy_realizations: int
    hcipy_anchors: int
    # Allowed |HCIPy/native - 1| per statistic: at least three standard
    # errors at this tier's sample size, plus the pixel-scale difference the
    # backends have by construction where a statistic reaches below 2 px.
    tolerances: Mapping[str, float]
    # Statistics a reversed wind-to-layer assignment must leave.
    wind_control_statistics: tuple[str, ...]


_TIERS = {
    "fast": _Tier(
        native_realizations=256,
        hcipy_realizations=12,
        hcipy_anchors=10,
        tolerances={
            "piston_removed_variance": 0.40,
            "tip_tilt_removed_variance": 0.20,
            "structure_function_2px": 0.08,
            "structure_function_4px": 0.10,
            "structure_function_8px": 0.14,
            "structure_function_16px": 0.20,
            "temporal_structure_function_3ms": 0.10,
            "temporal_structure_function_10ms": 0.12,
            "temporal_structure_function_30ms": 0.18,
            "comoving_structure_function_10ms": 0.35,
            "counter_moving_structure_function_10ms": 0.15,
        },
        wind_control_statistics=("comoving_structure_function_10ms",),
    ),
    "slow": _Tier(
        native_realizations=1024,
        hcipy_realizations=32,
        hcipy_anchors=16,
        tolerances={
            "piston_removed_variance": 0.20,
            "tip_tilt_removed_variance": 0.10,
            "structure_function_2px": 0.04,
            "structure_function_4px": 0.05,
            "structure_function_8px": 0.07,
            "structure_function_16px": 0.10,
            "temporal_structure_function_3ms": 0.06,
            "temporal_structure_function_10ms": 0.06,
            "temporal_structure_function_30ms": 0.10,
            "comoving_structure_function_10ms": 0.20,
            "counter_moving_structure_function_10ms": 0.08,
        },
        wind_control_statistics=(
            "temporal_structure_function_3ms",
            "comoving_structure_function_10ms",
        ),
    ),
}


@dataclass(frozen=True)
class _Ensemble:
    """Per-realization means of every statistic, plus the frame count."""

    names: tuple[str, ...]
    unit_means: np.ndarray
    frames: int

    def mean_and_standard_error(self, name: str) -> tuple[float, float]:
        values = self.unit_means[:, self.names.index(name)]
        return float(np.mean(values)), float(
            np.std(values, ddof=1) / math.sqrt(values.size)
        )


def _atmosphere_inputs(*, reverse_winds: bool = False) -> dict[str, Any]:
    config = load_system_profile("eso_turbulence_2m_detector", 1)
    geometry = NATIVE_SCAO_COMPONENT_FACTORY.build_geometry(
        telescope_diameter_m=config.telescope_diameter_m,
        pupil_pixels=config.pupil_pixels,
        lenslets_across=config.lenslets_across,
        min_fill_fraction=config.wfs.min_fill_fraction,
        central_obstruction_ratio=config.wfs.central_obstruction_ratio,
        spider_width_m=config.wfs.spider_width_m,
    )
    atmosphere = config.atmosphere
    layers = atmosphere.layers
    if reverse_winds:
        winds = [layer.wind_m_per_s for layer in reversed(layers)]
        layers = tuple(
            replace(layer, wind_m_per_s=wind) for layer, wind in zip(layers, winds)
        )
    return dict(
        geometry=geometry,
        random_streams=NamedRandomStreams(_ROOT_SEED),
        r0_m=atmosphere.r0_m,
        outer_scale_m=atmosphere.outer_scale_m,
        phase_reference_wavelength_m=atmosphere.r0_reference_wavelength_m,
        wind_m_per_s=atmosphere.wind_m_per_s,
        target_rms_rad=None,
        normalize_rms=False,
        static_opd_rms_m=0.0,
        layers=layers,
    )


def _comoving_shift_px(inputs: Mapping[str, Any], lag_s: float) -> int:
    """Whole-pixel shift of the turbulence-weighted wind over ``lag_s``.

    Every ESO layer moves toward +x; ``(sum f v**(5/3))**(3/5)`` is 14.5 m/s.
    """

    weighted = math.fsum(
        layer.cn2_fraction * math.hypot(*layer.wind_m_per_s) ** (5.0 / 3.0)
        for layer in inputs["layers"]
    ) ** (3.0 / 5.0)
    spacing_m = inputs["geometry"].pupil_geometry.pixel_spacing_xy_m[0]
    return round(weighted * lag_s / spacing_m)


def _mean_square(values: np.ndarray) -> float:
    return float(np.nanmean(np.square(values)))


def _sample(
    model: Any,
    inputs: Mapping[str, Any],
    *,
    realizations: int,
    anchors_s: tuple[float, ...],
) -> _Ensemble:
    pupil = inputs["geometry"].pupil_mask
    rows, columns = np.nonzero(pupil)
    tip_tilt_basis = np.column_stack(
        (np.ones(rows.size), columns - columns.mean(), rows - rows.mean())
    ).astype(float)
    to_rad = 2.0 * math.pi / inputs["phase_reference_wavelength_m"]
    comoving_lag_s = 0.010
    shift = _comoving_shift_px(inputs, comoving_lag_s)
    names = (
        "piston_removed_variance",
        "tip_tilt_removed_variance",
        *(f"structure_function_{lag}px" for lag in _SEPARATIONS_PX),
        *(
            f"temporal_structure_function_{round(lag * 1e3)}ms"
            for lag in _TEMPORAL_LAGS_S
        ),
        "comoving_structure_function_10ms",
        "counter_moving_structure_function_10ms",
    )
    unit_means = []
    for realization in range(realizations):
        model.reset(realization_index=realization)
        frames = []
        for anchor_s in anchors_s:
            phase = model.opd_at(anchor_s) * to_rad
            later = {
                lag: model.opd_at(anchor_s + lag) * to_rad for lag in _TEMPORAL_LAGS_S
            }
            inside = phase[pupil]
            fit, *_ = np.linalg.lstsq(tip_tilt_basis, inside, rcond=None)
            shifted = later[comoving_lag_s]
            frames.append(
                (
                    _mean_square(inside),
                    _mean_square(inside - tip_tilt_basis @ fit),
                    *(
                        _mean_square(
                            np.concatenate(
                                (
                                    (phase[:, lag:] - phase[:, :-lag]).ravel(),
                                    (phase[lag:, :] - phase[:-lag, :]).ravel(),
                                )
                            )
                        )
                        for lag in _SEPARATIONS_PX
                    ),
                    *(
                        _mean_square((later[lag] - phase)[pupil])
                        for lag in _TEMPORAL_LAGS_S
                    ),
                    # The pattern advects with +wind: phi(x + s, t + tau)
                    # follows phi(x, t), and phi(x - s, t + tau) runs against it.
                    _mean_square(shifted[:, shift:] - phase[:, :-shift]),
                    _mean_square(shifted[:, :-shift] - phase[:, shift:]),
                )
            )
        unit_means.append(np.mean(frames, axis=0))
    return _Ensemble(names, np.asarray(unit_means), realizations * len(anchors_s))


def _native_ensemble(tier: _Tier, *, reverse_winds: bool = False) -> _Ensemble:
    inputs = _atmosphere_inputs(reverse_winds=reverse_winds)
    model = NATIVE_SCAO_COMPONENT_FACTORY.build_atmosphere(
        model="native_layered", **inputs
    )
    return _sample(
        model, inputs, realizations=tier.native_realizations, anchors_s=(0.0,)
    )


def _hcipy_ensemble(tier: _Tier) -> _Ensemble:
    inputs = _atmosphere_inputs()
    model = HCIPY_SCAO_COMPONENT_FACTORY.build_atmosphere(
        model="hcipy_layered", **inputs
    )
    anchors_s = tuple(
        _FIRST_HCIPY_ANCHOR_S + index * _HCIPY_ANCHOR_SPACING_S
        for index in range(tier.hcipy_anchors)
    )
    return _sample(
        model, inputs, realizations=tier.hcipy_realizations, anchors_s=anchors_s
    )


def _ratio(
    numerator: _Ensemble, denominator: _Ensemble, name: str
) -> tuple[float, float]:
    """Ratio of ensemble means and its first-order standard error."""

    top, top_error = numerator.mean_and_standard_error(name)
    bottom, bottom_error = denominator.mean_and_standard_error(name)
    ratio = top / bottom
    return ratio, abs(ratio) * math.hypot(top_error / top, bottom_error / bottom)


@pytest.fixture(
    scope="module",
    params=("fast", pytest.param("slow", marks=pytest.mark.slow)),
)
def ensembles(request: pytest.FixtureRequest) -> tuple[_Tier, _Ensemble, _Ensemble]:
    tier = _TIERS[request.param]
    return tier, _native_ensemble(tier), _hcipy_ensemble(tier)


def _assert_agreement(
    ensembles: tuple[_Tier, _Ensemble, _Ensemble], names: tuple[str, ...]
) -> None:
    tier, native, hcipy_ensemble = ensembles
    for name in names:
        ratio, standard_error = _ratio(hcipy_ensemble, native, name)
        tolerance = tier.tolerances[name]
        detail = (
            f"{name}: HCIPy/native = {ratio:.4f} +/- {standard_error:.4f} "
            f"(tolerance {tolerance}; {hcipy_ensemble.frames} HCIPy frames, "
            f"{native.frames} native)"
        )
        assert 3.0 * standard_error <= tolerance, f"too few samples to test {detail}"
        assert abs(ratio - 1.0) <= tolerance, detail


def test_layered_pupil_variances_agree(ensembles) -> None:
    _assert_agreement(
        ensembles, ("piston_removed_variance", "tip_tilt_removed_variance")
    )


def test_layered_phase_structure_functions_agree(ensembles) -> None:
    _assert_agreement(
        ensembles, tuple(f"structure_function_{lag}px" for lag in _SEPARATIONS_PX)
    )


def test_layered_temporal_decorrelation_agrees(ensembles) -> None:
    _assert_agreement(
        ensembles,
        tuple(
            f"temporal_structure_function_{round(lag * 1e3)}ms"
            for lag in _TEMPORAL_LAGS_S
        ),
    )


def test_layered_flow_direction_and_comoving_decorrelation_agree(ensembles) -> None:
    """Both backends advect every layer toward +x, at the same per-layer speeds."""

    _, native, hcipy_ensemble = ensembles
    for ensemble in (native, hcipy_ensemble):
        comoving, _ = ensemble.mean_and_standard_error(
            "comoving_structure_function_10ms"
        )
        counter, _ = ensemble.mean_and_standard_error(
            "counter_moving_structure_function_10ms"
        )
        assert counter > 4.0 * comoving
    _assert_agreement(
        ensembles,
        (
            "comoving_structure_function_10ms",
            "counter_moving_structure_function_10ms",
        ),
    )


def test_a_reversed_wind_assignment_falls_outside_the_tolerances(ensembles) -> None:
    """The temporal statistics resolve which wind belongs to which layer.

    Reversing the ten winds keeps every speed but hands the ground layer
    10 m/s and the 18.5 km layer 12.1 m/s.  Drawn from the same native seeds,
    that atmosphere leaves the tolerances HCIPy's correctly mapped layers meet:
    its co-moving structure function rises by about 60 %, and at the slow
    tier's precision its 3 ms temporal structure function by about 10 %.
    """

    tier, native, _ = ensembles
    reversed_native = _native_ensemble(tier, reverse_winds=True)
    for name in tier.wind_control_statistics:
        ratio, _ = _ratio(reversed_native, native, name)
        assert abs(ratio - 1.0) > tier.tolerances[name], (name, ratio)
