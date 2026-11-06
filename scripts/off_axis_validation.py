"""Physics validation of the off-axis science sampling (bounded, serial).

Each subcommand writes JSON/CSV/PNG evidence under
``docs/research/scao_off_axis_v1/evidence`` following the pre-registered
plan in ``docs/research/scao_off_axis_v1/PREREGISTRATION.md``:

``shift``          C3: signed fractional shifts against analytic patterns.
``ground-layer``   C2: all turbulence at h = 0 is direction independent.
``anisoplanatism`` C4: ideal on-axis correction of the Robo-AO-2 layer table
                   against the anisoplanatic structure function and the
                   long-exposure OTF Strehl, plus Fried's small-angle factor.
``convergence``    C5: screen period factor 4 and PSF pad factor 6.
``band-limit-bound`` C4: bound of the band-limit effect on the predicted
                   Strehl over the whole lag support.
``closed-loop``    C1 on the 2.2 m profile (bare 1500-frame run against the
                   demonstration's history; reordered 300-frame run against
                   its prefix) and C5 (pad 3 versus pad 6 on frames 150..299).

The reference calculations here never call the directional sampler: the
structure function is evaluated from the von Karman PSD by quadrature, the
long-exposure Strehl from the sampled pupil's autocorrelation.
"""

from __future__ import annotations

import os

for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_name, "2")
os.environ.setdefault("MPLBACKEND", "Agg")

import argparse  # noqa: E402
import csv  # noqa: E402
from dataclasses import replace  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
from pathlib import Path  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

import numpy as np  # noqa: E402
from scipy import integrate, interpolate, special  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
EVIDENCE = ROOT / "docs/research/scao_off_axis_v1/evidence"
ARCSEC = math.pi / 648000.0
PSD_CONSTANT = 0.023  # the repository's von Karman PSD constant (backends/native/atmosphere.py)


# --------------------------------------------------------------------------
# Independent reference physics
# --------------------------------------------------------------------------


def exact_psd_constant() -> float:
    """The Kolmogorov PSD coefficient the closed-form structure function assumes.

    ``Gamma(11/6)^2 / (2 pi^(11/3)) * (24 Gamma(6/5) / 5)^(5/6) = 0.02290``; the
    repository rounds it to 0.023, so every reference below is scaled by
    ``0.023 / 0.02290`` to describe the spectrum the simulator discretizes.
    """

    return float(special.gamma(11 / 6) ** 2 / (2 * np.pi ** (11 / 3)) * (24 * special.gamma(6 / 5) / 5) ** (5 / 6))


def von_karman_structure_function_table(r0_m: float, outer_scale_m: float | None):
    """Phase structure function ``D(rho)`` in rad^2 (phase at the r0 wavelength).

    Closed form of the von Karman structure function,
    ``D = (L0/r0)^(5/3) 2^(1/6) Gamma(11/6) / pi^(8/3) [24 Gamma(6/5)/5]^(5/6)
    [Gamma(5/6)/2^(1/6) - x^(5/6) K_(5/6)(x)]`` with ``x = 2 pi rho / L0``, and
    ``6.8839 (rho/r0)^(5/3)`` for Kolmogorov, both scaled by
    ``0.023 / 0.02290`` to the repository's PSD constant.
    :func:`quadrature_structure_function` cross-checks it.
    """

    scale = PSD_CONSTANT / exact_psd_constant()
    if outer_scale_m is None:
        # 6.883877 is the Kolmogorov coefficient for the exact PSD constant
        # (quadrature agrees to 3e-8 relative, recorded in the evidence).
        kolmogorov = 6.883877

        def evaluate(rho):
            rho = np.asarray(rho, dtype=float)
            return scale * kolmogorov * (rho / r0_m) ** (5.0 / 3.0)

        return evaluate
    L0 = outer_scale_m
    prefactor = (L0 / r0_m) ** (5.0 / 3.0) * 2 ** (1.0 / 6.0) * special.gamma(11 / 6) / np.pi ** (8.0 / 3.0) * (24 * special.gamma(6 / 5) / 5) ** (5.0 / 6.0)
    constant = special.gamma(5 / 6) / 2 ** (1.0 / 6.0)

    def evaluate(rho):
        rho = np.asarray(rho, dtype=float)
        out = np.zeros_like(rho)
        positive = rho > 0.0
        x = 2 * np.pi * rho[positive] / L0
        out[positive] = scale * prefactor * (constant - x ** (5.0 / 6.0) * special.kv(5 / 6, x))
        return out

    return evaluate


def quadrature_structure_function(rho: float, r0_m: float, outer_scale_m: float | None) -> float:
    """``2 int Phi(f) (1 - J0(2 pi f rho)) 2 pi f df`` with the repository's PSD, by quadrature."""

    inverse = 0.0 if outer_scale_m is None else 1.0 / outer_scale_m

    def integrand(f):
        return (PSD_CONSTANT * r0_m ** (-5.0 / 3.0) * (f * f + inverse * inverse) ** (-11.0 / 6.0)
                * (1.0 - special.j0(2.0 * np.pi * f * rho)) * 2.0 * np.pi * f)

    split = 1.0 / rho
    first = integrate.quad(integrand, 0.0, split, limit=400)[0]
    tail = integrate.quad(integrand, split, np.inf, limit=800)[0]
    return 2.0 * (first + tail)


def anisoplanatic_structure_function(lag_xy_m, theta_rad, layers, r0_m, reference_wavelength_m, outer_scale_m, tables=None):
    """Structure function of the ideal-correction residual, in OPD^2 (m^2).

    ``eps_theta(r) = phi_theta(r) - phi_0(r) = sum_l [S_l(r + h_l theta) - S_l(r)]``.
    Expanding ``<[eps(r + rho) - eps(r)]^2>`` with the covariances of one
    homogeneous layer (``C(u) = C(0) - D(u)/2``) gives, per layer,
    ``D_eps,l(rho) = 2 D_l(rho) + 2 D_l(h_l theta) - D_l(rho + h_l theta) - D_l(rho - h_l theta)``,
    which vanishes at ``rho = 0`` and tends to ``2 D_l(h_l theta)`` (twice the
    residual variance) for ``|rho| >> |h_l theta|``.  Independent layers add.
    ``layers`` are ``(cn2_fraction, altitude_m)`` pairs with
    ``r0_l = r0 f^(-3/5)``; the phase at the reference wavelength is converted
    to OPD.  (A first draft of this reference omitted the ``2 D_l(h theta)``
    term and predicted Strehls above one in a 10-realization smoke test; see
    VALIDATION.md.)
    """

    lag = np.asarray(lag_xy_m, dtype=float)
    theta = np.asarray(theta_rad, dtype=float)
    total = np.zeros(lag.shape[:-1])
    for index, (fraction, altitude) in enumerate(layers):
        if tables is None:
            table = von_karman_structure_function_table(r0_m * fraction ** (-0.6), outer_scale_m)
        else:
            table = tables[index]
        shift = altitude * theta
        rho = np.linalg.norm(lag, axis=-1)
        plus = np.linalg.norm(lag + shift, axis=-1)
        minus = np.linalg.norm(lag - shift, axis=-1)
        total += 2.0 * table(rho) + 2.0 * table(np.linalg.norm(shift)) - table(plus) - table(minus)
    return total * (reference_wavelength_m / (2.0 * np.pi)) ** 2


class OutOfBandCorrection:
    """``D_hf(rho) = 2 int_{outside the grid band} Phi_eps(f) (1 - cos 2 pi f.rho) d^2f``.

    The sampled layer screens carry no power outside the square band
    ``|f_x|, |f_y| <= 1/(2 delta)``.  The anisoplanatic filter is
    ``Phi_eps(f) = sum_l 4 Phi_l(f) sin^2(pi f . h_l theta)`` (the spectrum of
    ``S_l(r + h theta) - S_l(r)``), so the band-limited structure function the
    discrete model can reach is the continuous one minus this integral.  It
    is evaluated in polar coordinates: for each angle the radial integral
    runs from the square's boundary outward on a log-spaced grid.
    """

    def __init__(self, delta_m, theta_rad, layers, r0_m, outer_scale_m, *, angles=720, radial=600, outer_factor=1e3):
        f_nyquist = 0.5 / delta_m
        phi = (np.arange(angles) + 0.5) * (2 * np.pi / angles)
        cos_phi, sin_phi = np.cos(phi), np.sin(phi)
        r_min = f_nyquist / np.maximum(np.abs(cos_phi), np.abs(sin_phi))
        log_r = np.log(r_min)[:, None] + (np.arange(radial) + 0.5)[None, :] * (np.log(outer_factor) / radial)
        r = np.exp(log_r)
        inverse = 0.0 if outer_scale_m is None else 1.0 / outer_scale_m
        unit_psd = PSD_CONSTANT * (r * r + inverse * inverse) ** (-11.0 / 6.0)
        theta = np.asarray(theta_rad, dtype=float)
        filter_sum = np.zeros_like(r)
        for fraction, altitude in layers:
            r0_l = r0_m * fraction ** (-0.6)
            projection = altitude * (cos_phi[:, None] * theta[0] + sin_phi[:, None] * theta[1])
            filter_sum += r0_l ** (-5.0 / 3.0) * 4.0 * np.sin(np.pi * r * projection) ** 2
        # Measure r dr dphi with dr = r dlog(r).
        measure = r * r * (np.log(outer_factor) / radial) * (2 * np.pi / angles)
        self._weight = unit_psd * filter_sum * measure
        self._r, self._cos, self._sin = r, cos_phi, sin_phi

    def __call__(self, lag_xy_m):
        lag = np.asarray(lag_xy_m, dtype=float).reshape(-1, 2)
        out = np.empty(lag.shape[0])
        for index, (lx, ly) in enumerate(lag):
            projection = self._r * (self._cos[:, None] * lx + self._sin[:, None] * ly)
            out[index] = 2.0 * np.sum(self._weight * (1.0 - np.cos(2 * np.pi * projection)))
        return out.reshape(np.asarray(lag_xy_m).shape[:-1])


def pupil_autocorrelation(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Lag grid ``T(rho)`` of the sampled pupil (counts of pupil pairs) with lag indices."""

    n = mask.shape[0]
    padded = np.zeros((2 * n, 2 * n))
    padded[:n, :n] = mask
    spectrum = np.fft.fft2(padded)
    auto = np.fft.ifft2(np.abs(spectrum) ** 2).real
    auto = np.fft.fftshift(np.rint(auto))
    lags = np.arange(-n, n)
    return auto, lags, lags


def long_exposure_strehl_from_structure_function(mask, delta_m, structure_opd2_fn, wavelength_m):
    """``sum_rho T(rho) exp(-D(rho)/2) / sum_rho T(rho)``, the on-axis long-exposure Strehl.

    Exact for a Gaussian homogeneous residual phase on the sampled pupil, in
    the propagator's own discretization (the pad factor cancels).
    """

    auto, lag_y, lag_x = pupil_autocorrelation(mask)
    keep = auto > 0.0
    rows, cols = np.nonzero(keep)
    lags = np.stack([lag_x[cols] * delta_m, lag_y[rows] * delta_m], axis=-1)
    d_opd2 = structure_opd2_fn(lags)
    d_rad2 = d_opd2 * (2.0 * np.pi / wavelength_m) ** 2
    weights = auto[keep]
    return float(np.sum(weights * np.exp(-0.5 * d_rad2)) / np.sum(weights))


def fried_isoplanatic_angle_rad(r0_m, layers, wavelength_m, reference_wavelength_m):
    """``theta_0 = 0.314 r0(lambda) / hbar``, ``hbar = (sum f h^(5/3))^(3/5)`` (Kolmogorov)."""

    r0 = r0_m * (wavelength_m / reference_wavelength_m) ** 1.2
    hbar = sum(f * h ** (5.0 / 3.0) for f, h in layers) ** 0.6
    return 0.314 * r0 / hbar


# --------------------------------------------------------------------------
# Simulation-side helpers
# --------------------------------------------------------------------------


def directional_structure_functions(residual: np.ndarray, max_lag: int) -> tuple[np.ndarray, np.ndarray]:
    """Pupil-averaged ``<(eps(r + l x) - eps(r))^2>`` and the same along y, lags 1..max_lag."""

    along_x = np.empty(max_lag)
    along_y = np.empty(max_lag)
    for lag in range(1, max_lag + 1):
        dx = residual[:, lag:] - residual[:, :-lag]
        dy = residual[lag:, :] - residual[:-lag, :]
        along_x[lag - 1] = np.nanmean(dx * dx)
        along_y[lag - 1] = np.nanmean(dy * dy)
    return along_x, along_y


def continuous_peak(intensity: np.ndarray, *, upsample: int = 8, levels: int = 2) -> tuple[float, tuple[float, float]]:
    """Peak of the band-limited image between samples, by DFT interpolation.

    A pad-factor-``p >= 2`` FFT image is Nyquist sampled (its OTF support
    ``|rho| <= D`` lies inside the band), so the trigonometric interpolant of
    its samples is the continuous image.  The interpolant is evaluated on a
    fine grid of ``1/upsample`` pixel around the discrete maximum, then again
    around that maximum with a ``1/upsample^2`` step (``levels = 2``).
    Returns the peak value (per discrete-pixel flux, comparable with the
    sampled values) and its position in pixels relative to the discrete
    maximum.
    """

    image = np.asarray(intensity, dtype=float)
    rows, cols = image.shape
    spectrum = np.fft.fft2(image)
    fy = np.fft.fftfreq(rows)
    fx = np.fft.fftfreq(cols)
    row0, col0 = np.unravel_index(int(np.argmax(image)), image.shape)
    centre = (float(row0), float(col0))
    step = 1.0
    best = (float(image[row0, col0]), centre)
    for _ in range(levels):
        step /= upsample
        offsets = np.arange(-upsample, upsample + 1) * step
        ys = best[1][0] + offsets
        xs = best[1][1] + offsets
        ey = np.exp(2j * np.pi * np.outer(ys, fy))  # (len(ys), rows)
        ex = np.exp(2j * np.pi * np.outer(fx, xs))  # (cols, len(xs))
        fine = (ey @ spectrum @ ex).real / (rows * cols)
        i, j = np.unravel_index(int(np.argmax(fine)), fine.shape)
        best = (float(fine[i, j]), (float(ys[i]), float(xs[j])))
    return best[0], (best[1][0] - centre[0], best[1][1] - centre[1])


def peak_strehl_records(images: dict, ideal: np.ndarray) -> dict:
    """Discrete and interpolated peak Strehl of each image against the ideal."""

    ideal_peak, _ = continuous_peak(ideal)
    out = {}
    for label, intensity in images.items():
        value, position = continuous_peak(intensity)
        out[label] = {
            "discrete_peak_strehl": float(np.max(intensity) / np.max(ideal)),
            "interpolated_peak_strehl": float(value / ideal_peak),
            "interpolated_peak_offset_px": list(position),
            "ideal_discrete_vs_interpolated": float(np.max(ideal) / ideal_peak),
        }
    return out


def jsonable(value):
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(jsonable(value), indent=2) + "\n")


def profile_layers(config):
    return [(layer.cn2_fraction, layer.altitude_m) for layer in config.atmosphere.layers]


def build_layered_atmosphere(config, *, screen_period_factor: int = 2):
    """The profile's atmosphere and pupil, built as the factory builds them (no WFS/DM)."""

    from shwfs_ao.backends.native.factory import NATIVE_SCAO_COMPONENT_FACTORY
    from shwfs_ao.backends.native.layered_atmosphere import (
        FrozenFlowLayer,
        LayeredFrozenFlowAtmosphere,
        LayeredFrozenFlowAtmosphereConfig,
    )
    from shwfs_ao.core.random import NamedRandomStreams

    factory = NATIVE_SCAO_COMPONENT_FACTORY
    geometry = factory.build_geometry(
        telescope_diameter_m=config.telescope_diameter_m,
        pupil_pixels=config.pupil_pixels,
        lenslets_across=config.lenslets_across,
        min_fill_fraction=config.wfs.min_fill_fraction,
        central_obstruction_ratio=config.wfs.central_obstruction_ratio,
        spider_width_m=config.wfs.spider_width_m,
    )
    streams = NamedRandomStreams(config.random.root_seed)
    atmosphere_config = LayeredFrozenFlowAtmosphereConfig(
        grid_size=geometry.pupil_shape[0],
        delta_m=geometry.pupil_geometry.pixel_spacing_xy_m[0],
        pupil_diameter_m=geometry.telescope_diameter_m,
        r0_m=config.atmosphere.r0_m,
        layers=tuple(
            FrozenFlowLayer(cn2_fraction=l.cn2_fraction, wind_m_per_s=tuple(l.wind_m_per_s), altitude_m=l.altitude_m)
            for l in config.atmosphere.layers
        ),
        outer_scale_m=config.atmosphere.outer_scale_m,
        phase_reference_wavelength_m=config.atmosphere.r0_reference_wavelength_m,
        root_seed=streams.root_seed,
        screen_period_factor=screen_period_factor,
    )
    atmosphere = LayeredFrozenFlowAtmosphere(
        atmosphere_config, pupil_mask=geometry.pupil_mask, random_streams=streams.scoped("native-atmosphere")
    )
    return atmosphere, geometry


def propagator_for(geometry, pad_factor: int):
    from shwfs_ao.backends.native.propagation import NativeSciencePropagator
    from shwfs_ao.science.propagation import PsfSampling

    return NativeSciencePropagator(pupil=geometry.pupil_geometry, sampling=PsfSampling(pad_factor=pad_factor))


# --------------------------------------------------------------------------
# C3 shift, C2 ground layer
# --------------------------------------------------------------------------


def run_shift(output: Path) -> None:
    from shwfs_ao.backends.native.layered_atmosphere import (
        FrozenFlowLayer,
        LayeredFrozenFlowAtmosphere,
        LayeredFrozenFlowAtmosphereConfig,
    )
    from shwfs_ao.core.wavefront import remove_piston

    grid, diameter = 40, 2.0
    layers = (
        FrozenFlowLayer(cn2_fraction=0.6, wind_m_per_s=(4.0, -2.5), altitude_m=0.0),
        FrozenFlowLayer(cn2_fraction=0.4, wind_m_per_s=(-7.0, 3.0), altitude_m=8000.0),
    )
    config = LayeredFrozenFlowAtmosphereConfig(
        grid_size=grid, delta_m=diameter / (grid - 1), pupil_diameter_m=diameter, r0_m=0.12,
        layers=layers, outer_scale_m=25.0, root_seed=3,
    )
    layer = 1
    altitude = layers[layer].altitude_m
    coordinates = np.arange(grid) * config.delta_m
    x, y = np.meshgrid(coordinates, coordinates)
    time_s = 0.0137
    amplitude, phase = 0.8, 0.9
    rows = []
    for component in ("periodic", "analytic"):
        for samples in ((3.3, -1.7), (-2.25, 4.6), (0.4, 0.0), (0.0, -0.75), (2.0, 2.0)):
            atmosphere = LayeredFrozenFlowAtmosphere(config)
            for coefficients in atmosphere._band_coefficients:
                coefficients[...] = 0.0
            for blocks in atmosphere._low_frequency_blocks:
                for block in blocks:
                    block.coefficients[...] = 0.0
            size = config.screen_size
            if component == "periodic":
                kx, ky = 5, -3
                atmosphere._band_coefficients[layer][ky % size, kx % size] = amplitude * size**2 * np.exp(1j * phase)
                fx, fy = kx / config.screen_period_m, ky / config.screen_period_m
            else:
                block = atmosphere._low_frequency_blocks[layer][1]
                block.coefficients[7, 4] = amplitude * np.exp(1j * phase)
                fx, fy = float(block.nodes_per_m[4]), float(block.nodes_per_m[7])
            direction = (samples[0] * config.delta_m / altitude, samples[1] * config.delta_m / altitude)
            mask = atmosphere.pupil_mask
            sampled = atmosphere.directional_opd_at(time_s, direction)

            def expected(theta):
                wind = layers[layer].wind_m_per_s
                sx = wind[0] * time_s - altitude * theta[0]
                sy = wind[1] * time_s - altitude * theta[1]
                pattern = amplitude * np.cos(2 * np.pi * (fx * (x - sx) + fy * (y - sy)) + phase)
                return remove_piston(pattern, mask) * config.phase_reference_wavelength_m / (2 * np.pi)

            reference = expected(direction)
            scale = float(np.nanmax(np.abs(reference)))
            error = float(np.nanmax(np.abs(sampled - reference)))
            mirrored = float(np.nanmax(np.abs(sampled - expected((-direction[0], direction[1])))))
            swapped = float(np.nanmax(np.abs(sampled - expected((direction[1], direction[0])))))
            rows.append(
                {
                    "component": component,
                    "mode_cycles_per_m": [fx, fy],
                    "direction_rad": list(direction),
                    "direction_arcsec": [d / ARCSEC for d in direction],
                    "footprint_shift_samples": list(samples),
                    "wind_m_per_s": list(layers[layer].wind_m_per_s),
                    "time_s": time_s,
                    "wind_travel_samples": [w * time_s / config.delta_m for w in layers[layer].wind_m_per_s],
                    "map_max_m": scale,
                    "max_abs_error_m": error,
                    "relative_error": error / scale,
                    "tolerance_relative": 1e-12,
                    "mirrored_x_discrepancy_relative": mirrored / scale,
                    "swapped_axes_discrepancy_relative": swapped / scale,
                    "accepted": error <= 1e-12 * scale,
                }
            )
    write_json(output / "shift_check.json", {"check": "C3 signed fractional shift", "rows": rows,
               "all_accepted": all(r["accepted"] for r in rows)})
    print("C3 shift:", "all accepted" if all(r["accepted"] for r in rows) else "FAILED",
          "max relative error", max(r["relative_error"] for r in rows))


def run_ground_layer(output: Path) -> None:
    from shwfs_ao.backends.native.layered_atmosphere import (
        FrozenFlowLayer,
        LayeredFrozenFlowAtmosphere,
        LayeredFrozenFlowAtmosphereConfig,
    )
    from shwfs_ao.io.configs import load_system_profile

    config = load_system_profile("robo_ao2_22m_ngs_draft", 2)
    grounded = tuple(
        FrozenFlowLayer(cn2_fraction=l.cn2_fraction, wind_m_per_s=tuple(l.wind_m_per_s), altitude_m=0.0)
        for l in config.atmosphere.layers
    )
    atmosphere_config = LayeredFrozenFlowAtmosphereConfig(
        grid_size=64, delta_m=2.2 / 63, pupil_diameter_m=2.2, r0_m=config.atmosphere.r0_m,
        layers=grounded, outer_scale_m=25.0, root_seed=1,
    )
    atmosphere = LayeredFrozenFlowAtmosphere(atmosphere_config)
    propagator = None
    rows = []
    for time_s in (0.0, 0.4):
        reference = atmosphere.opd_at(time_s)
        for arcsec in ((5, 0), (0, -10), (20, 0), (30, 30)):
            sample = atmosphere.directional_opd_at(time_s, (arcsec[0] * ARCSEC, arcsec[1] * ARCSEC))
            equal = bool(np.array_equal(sample, reference, equal_nan=True))
            rows.append({"time_s": time_s, "offset_arcsec": list(arcsec), "bitwise_equal_to_on_axis": equal,
                         "max_abs_difference_m": float(np.nanmax(np.abs(sample - reference)))})
    write_json(output / "ground_layer_check.json", {
        "check": "C2 ground-layer limit", "layers": len(grounded), "rows": rows,
        "all_accepted": all(r["bitwise_equal_to_on_axis"] for r in rows),
        "note": "identical residual OPD maps give identical PSFs for any propagator",
    })
    print("C2 ground layer:", "all accepted" if all(r["bitwise_equal_to_on_axis"] for r in rows) else "FAILED")


# --------------------------------------------------------------------------
# C4 anisoplanatism (ideal on-axis correction) and C5 convergence
# --------------------------------------------------------------------------


def run_anisoplanatism(output: Path, *, separations_arcsec, realizations: int, screen_period_factor: int,
                       pad_factors=(3,), pad_realizations=None, wavelength_m=1.65e-6, batches=10, tag="factor2"):
    from shwfs_ao.io.configs import load_system_profile
    from shwfs_ao.science.metrics import discrete_flux_to_angular_surface_brightness, peak_strehl_from_discrete_flux

    config = load_system_profile("robo_ao2_22m_ngs_draft", 2)
    layers = profile_layers(config)
    r0 = config.atmosphere.r0_m
    ref_wavelength = config.atmosphere.r0_reference_wavelength_m
    outer_scale = config.atmosphere.outer_scale_m
    atmosphere, geometry = build_layered_atmosphere(config, screen_period_factor=screen_period_factor)
    delta = atmosphere.config.delta_m
    mask = atmosphere.pupil_mask
    n = mask.shape[0]
    max_lag = n // 2
    propagators = {pad: propagator_for(geometry, pad) for pad in pad_factors}
    ideal = {pad: prop.psf_from_opd(np.zeros((n, n)), wavelength_m) for pad, prop in propagators.items()}
    pad_realizations = realizations if pad_realizations is None else pad_realizations

    started = time.perf_counter()
    print(f"tabulating von Karman structure functions for {len(layers)} layers ...", flush=True)
    tables = [von_karman_structure_function_table(r0 * f ** (-0.6), outer_scale) for f, _ in layers]
    kolmogorov = [von_karman_structure_function_table(r0 * f ** (-0.6), None) for f, _ in layers]
    print(f"  {time.perf_counter() - started:.1f} s", flush=True)

    cross_check = []
    for rho in (0.05, 0.5, 2.0):
        for scale_label, L0 in (("von_karman", outer_scale), ("kolmogorov", None)):
            closed = float(tables[0](rho)) if L0 is not None else float(kolmogorov[0](rho))
            quad = quadrature_structure_function(rho, r0 * layers[0][0] ** (-0.6), L0)
            cross_check.append({"rho_m": rho, "spectrum": scale_label, "closed_form_rad2": closed, "quadrature_rad2": quad,
                                "relative_difference": closed / quad - 1.0})
    theta0 = fried_isoplanatic_angle_rad(r0, layers, wavelength_m, ref_wavelength)
    lags_m = np.arange(1, max_lag + 1) * delta
    predictions = {}
    for arcsec in separations_arcsec:
        theta = np.array([arcsec * ARCSEC, 0.0])
        lag_x = np.stack([lags_m, np.zeros_like(lags_m)], axis=-1)
        lag_y = np.stack([np.zeros_like(lags_m), lags_m], axis=-1)
        d_par_cont = anisoplanatic_structure_function(lag_x, theta, layers, r0, ref_wavelength, outer_scale, tables)
        d_perp_cont = anisoplanatic_structure_function(lag_y, theta, layers, r0, ref_wavelength, outer_scale, tables)
        correction = OutOfBandCorrection(delta, theta, layers, r0, outer_scale)
        opd_scale = (ref_wavelength / (2.0 * np.pi)) ** 2
        hf_par = correction(lag_x) * opd_scale
        hf_perp = correction(lag_y) * opd_scale
        d_par = d_par_cont - hf_par
        d_perp = d_perp_cont - hf_perp
        d_par_k = anisoplanatic_structure_function(lag_x, theta, layers, r0, ref_wavelength, None, kolmogorov)
        d_perp_k = anisoplanatic_structure_function(lag_y, theta, layers, r0, ref_wavelength, None, kolmogorov)
        strehl = long_exposure_strehl_from_structure_function(
            mask, delta, lambda lag: anisoplanatic_structure_function(lag, theta, layers, r0, ref_wavelength, outer_scale, tables),
            wavelength_m)
        strehl_k = long_exposure_strehl_from_structure_function(
            mask, delta, lambda lag: anisoplanatic_structure_function(lag, theta, layers, r0, ref_wavelength, None, kolmogorov),
            wavelength_m)
        # Band-limit effect on the Strehl: correct the lags within 8 samples.
        auto, lag_rows, lag_cols = pupil_autocorrelation(mask)
        small = np.array([(i, j) for i in range(-8, 9) for j in range(-8, 9) if (i, j) != (0, 0)])
        small_lags = small[:, ::-1] * delta  # (x, y)
        d_small_cont = anisoplanatic_structure_function(small_lags, theta, layers, r0, ref_wavelength, outer_scale, tables)
        d_small_hf = correction(small_lags) * opd_scale
        k2 = (2.0 * np.pi / wavelength_m) ** 2
        n_mask = mask.shape[0]
        weights_small = np.array([auto[n_mask + i, n_mask + j] for i, j in small])
        delta_sum = np.sum(weights_small * (np.exp(-0.5 * (d_small_cont - d_small_hf) * k2) - np.exp(-0.5 * d_small_cont * k2)))
        strehl_band_limited = strehl + delta_sum / np.sum(auto)
        predictions[arcsec] = {
            "d_parallel_opd2": d_par, "d_perpendicular_opd2": d_perp,
            "d_parallel_continuous_opd2": d_par_cont, "d_perpendicular_continuous_opd2": d_perp_cont,
            "d_parallel_out_of_band_opd2": hf_par, "d_perpendicular_out_of_band_opd2": hf_perp,
            "strehl_on_axis_von_karman_band_limited_small_lags": strehl_band_limited,
            "d_parallel_kolmogorov_opd2": d_par_k, "d_perpendicular_kolmogorov_opd2": d_perp_k,
            "strehl_on_axis_von_karman": strehl, "strehl_on_axis_kolmogorov": strehl_k,
            "fried_small_angle_factor": math.exp(-((arcsec * ARCSEC) / theta0) ** (5.0 / 3.0)),
        }
    print(f"predictions ready, {time.perf_counter() - started:.1f} s", flush=True)

    # Simulation: independent realizations, ideal on-axis correction.
    count = len(separations_arcsec)
    d_par_samples = np.zeros((count, realizations, max_lag))
    d_perp_samples = np.zeros((count, realizations, max_lag))
    sums = {pad: np.zeros((count,) + ideal[pad].intensity.shape) for pad in pad_factors}
    crop = slice(ideal[3].intensity.shape[0] // 2 - 128, ideal[3].intensity.shape[0] // 2 + 128)
    batch_sums = np.zeros((count, batches, 256, 256))
    counted = {pad: 0 for pad in pad_factors}
    for index in range(realizations):
        atmosphere.reset(realization_index=index)
        on_axis = atmosphere.directional_opd_at(0.0, (0.0, 0.0))
        for k, arcsec in enumerate(separations_arcsec):
            residual = atmosphere.directional_opd_at(0.0, (arcsec * ARCSEC, 0.0)) - on_axis
            d_par_samples[k, index], d_perp_samples[k, index] = directional_structure_functions(residual, max_lag)
            for pad in pad_factors:
                if pad != 3 and index >= pad_realizations:
                    continue
                psf = propagators[pad].psf_from_opd(np.where(mask, residual, 0.0), wavelength_m)
                sums[pad][k] += psf.intensity
                if pad == 3:
                    batch_sums[k, index * batches // realizations] += psf.intensity[crop, crop]
        for pad in pad_factors:
            if pad == 3 or index < pad_realizations:
                counted[pad] += 1
        if (index + 1) % 20 == 0:
            print(f"  realization {index + 1}/{realizations}, {time.perf_counter() - started:.0f} s", flush=True)

    results = []
    table_rows = []
    for k, arcsec in enumerate(separations_arcsec):
        pred = predictions[arcsec]
        d_par_mean = d_par_samples[k].mean(axis=0)
        d_par_se = d_par_samples[k].std(axis=0, ddof=1) / math.sqrt(realizations)
        d_perp_mean = d_perp_samples[k].mean(axis=0)
        d_perp_se = d_perp_samples[k].std(axis=0, ddof=1) / math.sqrt(realizations)
        keep = lags_m <= 1.1
        tol_par = np.maximum(3 * d_par_se, 0.02 * pred["d_parallel_opd2"])
        tol_perp = np.maximum(3 * d_perp_se, 0.02 * pred["d_perpendicular_opd2"])
        par_ok = bool(np.all(np.abs(d_par_mean - pred["d_parallel_opd2"])[keep] <= tol_par[keep]))
        perp_ok = bool(np.all(np.abs(d_perp_mean - pred["d_perpendicular_opd2"])[keep] <= tol_perp[keep]))
        strehl_by_pad = {}
        for pad in pad_factors:
            mean_image = sums[pad][k] / counted[pad]
            psf = replace(ideal[pad], intensity=mean_image)
            brightness = discrete_flux_to_angular_surface_brightness(psf)
            ideal_brightness = discrete_flux_to_angular_surface_brightness(ideal[pad])
            centre = brightness.shape[0] // 2
            strehl_by_pad[pad] = {
                "realizations": counted[pad],
                "peak_strehl": float(peak_strehl_from_discrete_flux(psf, ideal[pad])),
                "on_axis_strehl": float(brightness[centre, centre] / np.max(ideal_brightness)),
            }
        # Batch-mean uncertainty of the on-axis Strehl (pad 3, central crop).
        ideal_centre = ideal[3].intensity[crop, crop]
        per_batch = realizations // batches
        batch_on_axis = np.array([
            (batch_sums[k, b] / per_batch)[128, 128] / ideal_centre[128, 128] for b in range(batches)
        ])
        batch_peak = np.array([
            np.max(batch_sums[k, b] / per_batch) / np.max(ideal_centre) for b in range(batches)
        ])
        se_on_axis = float(batch_on_axis.std(ddof=1) / math.sqrt(batches))
        se_peak = float(batch_peak.std(ddof=1) / math.sqrt(batches))
        sim_on_axis = strehl_by_pad[3]["on_axis_strehl"]
        sim_peak = strehl_by_pad[3]["peak_strehl"]
        tol_s = max(3 * se_on_axis, 0.02)
        strehl_ok = abs(sim_on_axis - pred["strehl_on_axis_von_karman"]) <= tol_s
        peak_ok = sim_peak - sim_on_axis <= tol_s
        results.append({
            "separation_arcsec": arcsec,
            "theta_over_theta0": arcsec * ARCSEC / theta0,
            "structure_function": {
                "lags_m": lags_m, "parallel_sim": d_par_mean, "parallel_se": d_par_se,
                "parallel_pred_von_karman": pred["d_parallel_opd2"], "parallel_pred_kolmogorov": pred["d_parallel_kolmogorov_opd2"],
                "parallel_pred_von_karman_continuous": pred["d_parallel_continuous_opd2"],
                "parallel_out_of_band": pred["d_parallel_out_of_band_opd2"],
                "perpendicular_sim": d_perp_mean, "perpendicular_se": d_perp_se,
                "perpendicular_pred_von_karman": pred["d_perpendicular_opd2"], "perpendicular_pred_kolmogorov": pred["d_perpendicular_kolmogorov_opd2"],
                "perpendicular_pred_von_karman_continuous": pred["d_perpendicular_continuous_opd2"],
                "perpendicular_out_of_band": pred["d_perpendicular_out_of_band_opd2"],
                "prediction_note": "pred_von_karman is band limited to the grid (continuous minus out-of-band); the continuous form is reported beside it",
                "accepted_parallel_lags_le_1p1m": par_ok, "accepted_perpendicular_lags_le_1p1m": perp_ok,
                "max_relative_discrepancy_parallel_le_1p1m": float(np.max(np.abs(d_par_mean - pred["d_parallel_opd2"])[keep] / pred["d_parallel_opd2"][keep])),
                "max_relative_discrepancy_perpendicular_le_1p1m": float(np.max(np.abs(d_perp_mean - pred["d_perpendicular_opd2"])[keep] / pred["d_perpendicular_opd2"][keep])),
            },
            "strehl": {
                "prediction_on_axis_von_karman": pred["strehl_on_axis_von_karman"],
                "prediction_on_axis_von_karman_band_limited_small_lags": pred["strehl_on_axis_von_karman_band_limited_small_lags"],
                "prediction_on_axis_kolmogorov": pred["strehl_on_axis_kolmogorov"],
                "fried_small_angle_factor": pred["fried_small_angle_factor"],
                "simulation": strehl_by_pad,
                "on_axis_se_batch_means": se_on_axis, "peak_se_batch_means": se_peak,
                "batch_on_axis": batch_on_axis, "batch_peak": batch_peak,
                "discrepancy_on_axis": sim_on_axis - pred["strehl_on_axis_von_karman"],
                "relative_discrepancy_on_axis": (sim_on_axis - pred["strehl_on_axis_von_karman"]) / pred["strehl_on_axis_von_karman"],
                "tolerance": tol_s, "accepted_on_axis": strehl_ok, "accepted_peak_within_tolerance_of_on_axis": peak_ok,
            },
        })
        table_rows.append({
            "separation_arcsec": arcsec, "theta_over_theta0": arcsec * ARCSEC / theta0,
            "strehl_pred_von_karman": pred["strehl_on_axis_von_karman"],
            "strehl_pred_von_karman_band_limited": pred["strehl_on_axis_von_karman_band_limited_small_lags"],
            "strehl_pred_kolmogorov": pred["strehl_on_axis_kolmogorov"],
            "fried_small_angle_factor": pred["fried_small_angle_factor"],
            "strehl_sim_on_axis": sim_on_axis, "strehl_sim_peak": sim_peak, "strehl_sim_se": se_on_axis,
            "discrepancy": sim_on_axis - pred["strehl_on_axis_von_karman"],
            "relative_discrepancy": (sim_on_axis - pred["strehl_on_axis_von_karman"]) / pred["strehl_on_axis_von_karman"],
            "tolerance": tol_s, "accepted": strehl_ok,
            **{f"strehl_sim_peak_pad{pad}": strehl_by_pad[pad]["peak_strehl"] for pad in pad_factors},
            **{f"strehl_sim_on_axis_pad{pad}": strehl_by_pad[pad]["on_axis_strehl"] for pad in pad_factors},
            "structure_function_accepted": par_ok and perp_ok,
            "max_rel_disc_parallel": results[-1]["structure_function"]["max_relative_discrepancy_parallel_le_1p1m"],
            "max_rel_disc_perpendicular": results[-1]["structure_function"]["max_relative_discrepancy_perpendicular_le_1p1m"],
        })
    record = {
        "check": "C4 anisoplanatism under ideal on-axis correction" if tag == "factor2" else f"C5 convergence ({tag})",
        "profile": "robo_ao2_22m_ngs_draft@2", "layers": layers, "r0_m": r0, "r0_reference_wavelength_m": ref_wavelength,
        "outer_scale_m": outer_scale, "wavelength_m": wavelength_m, "pupil_samples": n, "grid_delta_m": delta,
        "screen_period_factor": screen_period_factor, "screen_period_m": atmosphere.config.screen_period_m,
        "realizations": realizations, "batches": batches, "pad_factors": list(pad_factors),
        "theta0_rad": theta0, "theta0_arcsec": theta0 / ARCSEC,
        "psd_constant": PSD_CONSTANT, "exact_psd_constant": exact_psd_constant(),
        "structure_function_closed_form_vs_quadrature": cross_check,
        "hbar_m": sum(f * h ** (5 / 3) for f, h in layers) ** 0.6,
        "atmosphere_config_hash": atmosphere.config_hash,
        "max_directional_displacement_m": atmosphere.max_directional_displacement_m,
        "elapsed_s": time.perf_counter() - started,
        "results": results,
    }
    write_json(output / f"anisoplanatism_{tag}.json", record)
    with (output / f"anisoplanatism_{tag}.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(table_rows[0]))
        writer.writeheader(); writer.writerows(table_rows)
    plot_anisoplanatism(output, record, tag)
    for row in table_rows:
        print(f"  {row['separation_arcsec']:>3} arcsec  pred {row['strehl_pred_von_karman']:.4f}  sim {row['strehl_sim_on_axis']:.4f} +- {row['strehl_sim_se']:.4f}"
              f"  peak {row['strehl_sim_peak']:.4f}  fried {row['fried_small_angle_factor']:.4f}  D ok {row['structure_function_accepted']}  S ok {row['accepted']}")
    print(f"C4/C5 {tag}: {time.perf_counter() - started:.0f} s")


def plot_anisoplanatism(output: Path, record, tag: str) -> None:
    import matplotlib.pyplot as plt

    results = record["results"]
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8))
    for result in results:
        sf = result["structure_function"]
        lags = np.asarray(sf["lags_m"])
        for axis, key, label in ((axes[0], "parallel", "parallel to theta (x)"), (axes[1], "perpendicular", "perpendicular (y)")):
            line = axis.errorbar(lags, np.asarray(sf[f"{key}_sim"]) * 1e18, yerr=np.asarray(sf[f"{key}_se"]) * 1e18,
                                 fmt=".", ms=3, label=f"sim {result['separation_arcsec']} arcsec")
            axis.plot(lags, np.asarray(sf[f"{key}_pred_von_karman"]) * 1e18, "-", color=line[0].get_color(), lw=1,
                      label=f"pred {result['separation_arcsec']} arcsec")
            axis.set_title(f"D_eps, baseline {label}", fontsize=9)
            axis.set_xlabel("baseline (m)"); axis.set_ylabel("D_eps (nm^2 OPD)")
    axes[0].legend(fontsize=6, ncol=2)
    fig.suptitle(f"Ideal on-axis correction, Robo-AO-2 layers, screen factor {record['screen_period_factor']}, N={record['realizations']}", fontsize=9)
    fig.savefig(output / f"anisoplanatism_{tag}_structure_function.png", dpi=130, bbox_inches="tight"); plt.close(fig)

    fig, axis = plt.subplots(figsize=(5, 3.6))
    sep = [r["separation_arcsec"] for r in results]
    axis.errorbar(sep, [r["strehl"]["simulation"][3]["on_axis_strehl"] for r in results],
                  yerr=[3 * r["strehl"]["on_axis_se_batch_means"] for r in results], fmt="o", capsize=3, label="simulation on-axis LE Strehl (3 SE)")
    axis.plot(sep, [r["strehl"]["simulation"][3]["peak_strehl"] for r in results], "x", label="simulation peak LE Strehl")
    axis.plot(sep, [r["strehl"]["prediction_on_axis_von_karman"] for r in results], "-", label="OTF integral, von Karman L0=25 m")
    axis.plot(sep, [r["strehl"]["prediction_on_axis_kolmogorov"] for r in results], "--", label="OTF integral, Kolmogorov")
    axis.plot(sep, [r["strehl"]["fried_small_angle_factor"] for r in results], ":", label="exp[-(theta/theta0)^(5/3)]")
    axis.set_xlabel("separation (arcsec)"); axis.set_ylabel("Strehl at 1.65 um"); axis.set_ylim(0, 1); axis.grid(alpha=0.3)
    axis.legend(fontsize=7); axis.set_title("Ideal on-axis correction (anisoplanatism only)", fontsize=9)
    fig.savefig(output / f"anisoplanatism_{tag}_strehl.png", dpi=130, bbox_inches="tight"); plt.close(fig)


# --------------------------------------------------------------------------
# C1 / C5 on the 2.2 m closed loop
# --------------------------------------------------------------------------


def run_band_limit_bound(output: Path, *, separations_arcsec=(5, 10, 20, 30, 40), wavelength_m=1.65e-6) -> None:
    """Bound the band-limit effect on the predicted Strehl over the whole lag support.

    The out-of-band structure function obeys ``0 <= D_hf(rho) <= 4 sigma_hf^2``
    with ``sigma_hf^2 = int_{outside band} Phi_eps d^2f`` (``1 - cos <= 2``),
    and tends to ``2 sigma_hf^2`` once ``2 pi f_N rho >> 1``.  Hence the
    band-limited prediction ``S_bl = sum T exp(-(D - D_hf) k^2 / 2) / sum T``
    satisfies ``S <= S_bl <= S exp(2 k^2 sigma_hf^2)`` over every lag, and the
    lags beyond eight samples (where the exact ``D_hf`` was not evaluated)
    contribute at most ``S (exp(2 k^2 sigma_hf^2) - 1)``.  The exact
    contribution of the lags within eight samples is recomputed here too.
    """

    from shwfs_ao.io.configs import load_system_profile

    config = load_system_profile("robo_ao2_22m_ngs_draft", 2)
    layers = profile_layers(config)
    r0 = config.atmosphere.r0_m
    ref_wavelength = config.atmosphere.r0_reference_wavelength_m
    outer_scale = config.atmosphere.outer_scale_m
    atmosphere, geometry = build_layered_atmosphere(config)
    delta = atmosphere.config.delta_m
    mask = atmosphere.pupil_mask
    tables = [von_karman_structure_function_table(r0 * f ** (-0.6), outer_scale) for f, _ in layers]
    auto, lag_rows, lag_cols = pupil_autocorrelation(mask)
    n = mask.shape[0]
    k2 = (2.0 * np.pi / wavelength_m) ** 2
    opd_scale = (ref_wavelength / (2.0 * np.pi)) ** 2
    rows = []
    for arcsec in separations_arcsec:
        theta = np.array([arcsec * ARCSEC, 0.0])
        strehl = long_exposure_strehl_from_structure_function(
            mask, delta, lambda lag: anisoplanatic_structure_function(lag, theta, layers, r0, ref_wavelength, outer_scale, tables),
            wavelength_m)
        correction = OutOfBandCorrection(delta, theta, layers, r0, outer_scale)
        sigma_hf2_phase_ref = float(np.sum(correction._weight))  # rad^2 at the reference wavelength
        sigma_hf2 = sigma_hf2_phase_ref * opd_scale * k2  # rad^2 at the science wavelength
        small = np.array([(i, j) for i in range(-8, 9) for j in range(-8, 9) if (i, j) != (0, 0)])
        small_lags = small[:, ::-1] * delta
        d_cont = anisoplanatic_structure_function(small_lags, theta, layers, r0, ref_wavelength, outer_scale, tables)
        d_hf = correction(small_lags) * opd_scale
        weights_small = np.array([auto[n + i, n + j] for i, j in small])
        total_weight = float(np.sum(auto))
        inner = float(np.sum(weights_small * (np.exp(-0.5 * (d_cont - d_hf) * k2) - np.exp(-0.5 * d_cont * k2))) / total_weight)
        outer_weight_fraction = float((total_weight - auto[n, n] - np.sum(weights_small)) / total_weight)
        bound_outer = strehl * outer_weight_fraction * (math.exp(2.0 * sigma_hf2) - 1.0)
        typical_outer = strehl * outer_weight_fraction * (math.exp(sigma_hf2) - 1.0)
        rows.append({
            "separation_arcsec": arcsec,
            "strehl_continuous": strehl,
            "sigma_hf2_rad2_at_science_wavelength": sigma_hf2,
            "inner_lags_le_8_exact_delta": inner,
            "outer_lag_weight_fraction": outer_weight_fraction,
            "outer_lags_delta_upper_bound": bound_outer,
            "outer_lags_delta_typical_2sigma": typical_outer,
            "strehl_band_limited_interval": [strehl + inner, strehl + inner + bound_outer],
            "strehl_band_limited_typical": strehl + inner + typical_outer,
        })
    write_json(output / "band_limit_bound.json", {
        "check": "C4 band-limit effect on the predicted Strehl over the full lag support (bound)",
        "method": run_band_limit_bound.__doc__, "wavelength_m": wavelength_m, "rows": rows,
    })
    for row in rows:
        print(f"  {row['separation_arcsec']:>3} arcsec  S {row['strehl_continuous']:.5f}  inner {row['inner_lags_le_8_exact_delta']:.2e}  "
              f"outer bound {row['outer_lags_delta_upper_bound']:.2e} typical {row['outer_lags_delta_typical_2sigma']:.2e}  sigma_hf2 {row['sigma_hf2_rad2_at_science_wavelength']:.2e}")


def run_closed_loop_checks(output: Path, demo_dir: Path, *, skip_bare: bool = False) -> None:
    from shwfs_ao.experiments import build_scao_system, run_closed_loop
    from shwfs_ao.io.configs import load_system_profile
    from shwfs_ao.science import LongExposureConfig, OffAxisLongExposure

    started = time.perf_counter()
    config = load_system_profile("robo_ao2_22m_ngs_draft", 2)
    demo_history = np.load(demo_dir / "history.npz")
    demo_psfs = np.load(demo_dir / "psfs.npz")
    demo_record = json.loads((demo_dir / "run_record.json").read_text())
    system = build_scao_system(config)
    build_s = time.perf_counter() - started
    fields = ("open_loop_opd_rms_m", "pre_update_residual_opd_rms_m", "post_update_residual_opd_rms_m",
              "requested_command_history_opd_m", "applied_command_history_opd_m", "saturation_fraction",
              "valid_measurement_fraction", "reconstruction_usable", "measurement_row_masks")

    # R2: bare 1500-frame run (no observers, no directions).
    previous = output / "closed_loop_checks_22m.json"
    if skip_bare and previous.exists():
        bare_record = json.loads(previous.read_text())["bare_run"]
        bare_record["reused_from_previous_record"] = True
    else:
        t = time.perf_counter()
        bare = run_closed_loop(config, system=system, realization_index=0)
        bare_s = time.perf_counter() - t
        bare_equal = {name: bool(np.array_equal(np.asarray(getattr(bare, name)), demo_history[name])) for name in fields}
        hash_equal = bare.config_hash == demo_record["history_config_hash"]
        bare_record = {"frames": 1500, "config_hash": bare.config_hash, "config_hash_equal": hash_equal,
                       "arrays_bitwise_equal": bare_equal, "all_equal": hash_equal and all(bare_equal.values()), "elapsed_s": bare_s}

    # R3/R4: 300-frame run with reversed offsets, pad 3 and pad 6 observers.
    short = replace(config, controller=replace(config.controller, n_steps=300))
    short_system = build_scao_system(short)
    offsets = [(20.0, 0.0), (0.0, 0.0)]
    pad3 = OffAxisLongExposure(short_system.science_propagator, offsets,
                               LongExposureConfig(wavelengths_m=(1.65e-6,), burn_in_frames=150),
                               telescope_diameter_m=config.telescope_diameter_m)
    pad6 = OffAxisLongExposure(propagator_for(short_system.wfs.geometry, 6), offsets,
                               LongExposureConfig(wavelengths_m=(1.65e-6,), burn_in_frames=150),
                               telescope_diameter_m=config.telescope_diameter_m, check_on_axis=False)
    t = time.perf_counter()
    short_history = run_closed_loop(short, system=short_system, realization_index=0, observers=(pad3, pad6),
                                    science_directions_rad=pad3.directions_rad)
    short_s = time.perf_counter() - t
    prefix_equal = {name: bool(np.array_equal(np.asarray(getattr(short_history, name)), demo_history[name][:300])) for name in fields}
    result3 = pad3.result(); result6 = pad6.result()
    demo_offsets = [tuple(o) for o in demo_psfs["offsets_arcsec"].tolist()]
    instantaneous_equal = {}
    instantaneous_detail = {}
    for offset in offsets:
        k = demo_offsets.index(offset)
        demo_inst = np.asarray(demo_psfs[f"instantaneous_strehl_{k}"])[:150]
        inst = np.asarray(result3.image(offset, 1.65e-6).instantaneous_strehl)
        instantaneous_equal[str(offset)] = bool(np.array_equal(demo_inst, inst))
        differing = np.nonzero(demo_inst != inst)[0]
        instantaneous_detail[str(offset)] = {
            "demo_length": int(demo_inst.size), "run_length": int(inst.size),
            "max_abs_difference": float(np.max(np.abs(demo_inst - inst))) if demo_inst.size == inst.size else None,
            "differing_frames": int(differing.size) if demo_inst.size == inst.size else None,
            "first_differing_selected_index": int(differing[0]) if differing.size else None,
            "demo_first_values": demo_inst[:3].tolist(), "run_first_values": inst[:3].tolist(),
        }
    pad_rows = []
    saved = {}
    for offset in offsets:
        i3 = result3.image(offset, 1.65e-6); i6 = result6.image(offset, 1.65e-6)
        label = f"{offset[0]:g}_{offset[1]:g}"
        saved[f"pad3_{label}"] = i3.psf.intensity
        saved[f"pad6_{label}"] = i6.psf.intensity
        interpolated3 = peak_strehl_records({"image": i3.psf.intensity}, i3.ideal_psf.intensity)["image"]
        interpolated6 = peak_strehl_records({"image": i6.psf.intensity}, i6.ideal_psf.intensity)["image"]
        pad_rows.append({"offset_arcsec": list(offset), "frames": "150..299",
                         "peak_strehl_pad3": i3.peak_strehl, "peak_strehl_pad6": i6.peak_strehl,
                         "interpolated_peak_strehl_pad3": interpolated3["interpolated_peak_strehl"],
                         "interpolated_peak_strehl_pad6": interpolated6["interpolated_peak_strehl"],
                         "interpolated_peak_offset_px_pad3": interpolated3["interpolated_peak_offset_px"],
                         "on_axis_strehl_pad3": i3.on_axis_strehl, "on_axis_strehl_pad6": i6.on_axis_strehl,
                         "peak_change": i6.peak_strehl - i3.peak_strehl, "fwhm_rad_pad3": i3.fwhm_rad, "fwhm_rad_pad6": i6.fwhm_rad,
                         "accepted_change_below_0p01": abs(i6.peak_strehl - i3.peak_strehl) < 0.01,
                         "interpolated_change": interpolated6["interpolated_peak_strehl"] - interpolated3["interpolated_peak_strehl"],
                         "science_interpolated_peak_strehl_pad3": i3.interpolated_peak_strehl,
                         "science_interpolated_peak_strehl_pad6": i6.interpolated_peak_strehl,
                         "science_interpolated_change_below_0p01": abs(i6.interpolated_peak_strehl - i3.interpolated_peak_strehl) < 0.01})
    saved["ideal_pad3"] = result3.image(offsets[0], 1.65e-6).ideal_psf.intensity
    saved["ideal_pad6"] = result6.image(offsets[0], 1.65e-6).ideal_psf.intensity
    np.savez(demo_dir.parent / "22m_prefix300_images.npz", **saved)
    # Interpolated peaks of the demonstration's long exposures.
    demo_interp = peak_strehl_records(
        {f"offset_{tuple(o)}": demo_psfs[f"psf_{k}"] for k, o in enumerate(demo_offsets)}, demo_psfs["ideal"]
    )
    record = {
        "check": "C1 loop independence and C5 focal sampling on robo_ao2_22m_ngs_draft@2",
        "demonstration_history_config_hash": demo_record["history_config_hash"],
        "bare_run": bare_record,
        "reordered_prefix_run": {"frames": 300, "offsets_arcsec": offsets, "arrays_bitwise_equal_to_demo_prefix": prefix_equal,
                                 "instantaneous_strehl_bitwise_equal_first_150_selected": instantaneous_equal,
                                 "instantaneous_strehl_detail": instantaneous_detail,
                                 "max_on_axis_difference_m": result3.max_on_axis_difference_m,
                                 "all_equal": all(prefix_equal.values()) and all(instantaneous_equal.values()), "elapsed_s": short_s},
        "focal_sampling": pad_rows,
        "demonstration_interpolated_peaks": demo_interp,
        "build_s": build_s, "elapsed_s": time.perf_counter() - started,
    }
    write_json(output / "closed_loop_checks_22m.json", record)
    print("C1 bare:", record["bare_run"]["all_equal"], "C1 reordered prefix:", record["reordered_prefix_run"]["all_equal"])
    print("  instantaneous detail:", json.dumps(jsonable(instantaneous_detail)))
    for row in pad_rows:
        print(f"  pad3 {row['peak_strehl_pad3']:.4f} pad6 {row['peak_strehl_pad6']:.4f} interp3 {row['interpolated_peak_strehl_pad3']:.4f} interp6 {row['interpolated_peak_strehl_pad6']:.4f} offset {row['offset_arcsec']}")
    for label, item in demo_interp.items():
        print(f"  demo {label}: discrete {item['discrete_peak_strehl']:.4f} interpolated {item['interpolated_peak_strehl']:.4f} at {item['interpolated_peak_offset_px']}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("check", choices=("shift", "ground-layer", "anisoplanatism", "convergence", "closed-loop", "band-limit-bound"))
    parser.add_argument("--output", type=Path, default=EVIDENCE)
    parser.add_argument("--realizations", type=int, default=200)
    parser.add_argument("--demo-dir", type=Path, default=ROOT / "outputs/off_axis_science/22m")
    parser.add_argument("--skip-bare", action="store_true", help="closed-loop: reuse the recorded bare-run comparison")
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    if args.check == "shift":
        run_shift(args.output)
    elif args.check == "ground-layer":
        run_ground_layer(args.output)
    elif args.check == "anisoplanatism":
        run_anisoplanatism(args.output, separations_arcsec=(5, 10, 20, 30), realizations=args.realizations,
                           screen_period_factor=2, pad_factors=(3, 6), pad_realizations=min(50, args.realizations), tag="factor2")
    elif args.check == "convergence":
        run_anisoplanatism(args.output, separations_arcsec=(20, 30, 40), realizations=args.realizations,
                           screen_period_factor=4, pad_factors=(3,), tag="factor4")
        run_anisoplanatism(args.output, separations_arcsec=(40,), realizations=args.realizations,
                           screen_period_factor=2, pad_factors=(3,), tag="factor2_40arcsec")
    elif args.check == "band-limit-bound":
        run_band_limit_bound(args.output)
    else:
        run_closed_loop_checks(args.output, args.demo_dir, skip_bare=args.skip_bare)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
