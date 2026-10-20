#!/usr/bin/env python3
"""S4 noise-law reanalysis of the saved paired noise-isolation records.

This script reads the committed evidence records of the paired detector-noise
isolation study (roadmap S4, limitation LIM-18) and

1. reproduces the historical analysis exactly as the execution record
   describes it (seed means per magnitude, weighted log-log fit with the
   unscaled covariance, the noise model's own slope, the ratio table, the
   post-hoc power of the model variance, the 6.7 % dip and the 9 % drift,
   and a seed-paired bootstrap of the unweighted estimator);
2. compares defensible alternative estimators and uncertainty conventions
   on the same saved aggregates (scaled covariance, ordinary least squares,
   per-seed paired slopes, medians, leave-one-seed-out, a two-way model with
   seed effects, block-error weighting, a floor-share linear fit, paired
   tests of the ratio trend, the difference-of-variances cross term, the
   arm valid-fraction divergence and the within/between dispersion);
3. runs three small synthetic statistical examples (not AO simulations)
   that illustrate the block-error, cross-term and excursion mechanisms;
4. writes everything, with the SHA-256 digests of its inputs, the source
   identity and the environment, to RESULTS.json.

It never runs an AO loop, builds a simulation system or draws new AO
realizations.  Bootstrap resamples are resamples of the saved aggregates,
not new independent realizations, and are labelled as such.

Execution (from the repository root; only NumPy is required)::

    python docs/research/s4_noise_law/analysis.py \
        --output docs/research/s4_noise_law/RESULTS.json

Optional ``--with-package`` adds checks that import ``shwfs_ao`` from
``src`` (configuration-hash agreement of every saved run with the current
code, the photometric budget and the lenslet illumination distribution).
They build no simulation system.  ``--skip-synthetic`` omits the synthetic
examples (about one second of work).  Exit status 0 means the script ran;
the reproduction verdicts are in the output, never asserted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np


HERE = Path(__file__).resolve().parent
EVIDENCE_DIR = Path("docs/refactor/detector_level_evidence")
RECORDS = {
    "12m_v3": "det09_noise_isolation_12m_v3.json",
    "2m": "det09_noise_isolation_2m.json",
    "2m_attempt1": "det09_noise_isolation_2m_attempt1.json",
}
NM2 = 1.0e18  # m^2 -> nm^2

# The numbers quoted in the repository (roadmap, LIM-18, technical reference
# 7.2/7.5, README, DETECTOR_LEVEL_DEVELOPMENT_STATUS.md).  They are compared
# with the reproduction below; nothing here is asserted.
QUOTED = {
    "12m_v3": {
        "slope": -1.028, "slope_se": 0.010, "chi2_dof": 2.50, "se_from_minus_one": 2.7,
        "scaled_se_from_minus_one": 1.7, "model_slope": -1.097, "power_of_model": 0.960,
        "power_of_model_se": 0.010, "dip_m10_vs_m9_percent": -6.7,
        "f06_unweighted_bootstrap_slope": -1.086, "f06_unweighted_bootstrap_sd": 0.028,
        "table": {  # m_AB: (dV mean nm2, SE nm2, ratio nm2/px2, ratio SE, model*Ne px2 e-)
            "m8": (111.6, 1.9, 32523, 558, 8.72),
            "m9": (291.4, 2.7, 32665, 302, 9.02),
            "m10": (740.4, 8.4, 30463, 345, 9.79),
            "m11": (2291, 203, 32130, 2845, 11.43),
        },
    },
    "2m": {
        "slope": -0.978, "slope_se": 0.014, "chi2_dof": 2.46, "se_from_minus_one": 1.6,
        "model_slope": -1.051, "power_of_model": 0.950, "power_of_model_se": 0.013,
        "drift_m7_vs_m5_percent": -9.0,
        "table": {
            "m5": (4.27, 0.08, 2554, None, 21.7),
            "m6": (10.40, 0.32, 2439, None, 22.1),
            "m7": (25.81, 0.44, 2318, None, 22.9),
            "m8": (200.7, 105.0, 6558, None, 25.1),
        },
    },
}


# --------------------------------------------------------------------------
# Small statistics helpers (NumPy only)
# --------------------------------------------------------------------------


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def student_t_cdf(t: float, dof: float) -> float:
    """CDF of Student's t by Simpson integration of the density (no SciPy)."""

    t = float(t)
    if dof <= 0:
        raise ValueError("dof must be positive")
    if t == 0.0:
        return 0.5
    sign = 1.0 if t > 0 else -1.0
    upper = abs(t)
    # density normalisation via log-gamma
    log_norm = (
        math.lgamma((dof + 1.0) / 2.0) - math.lgamma(dof / 2.0) - 0.5 * math.log(dof * math.pi)
    )
    n = 20000
    x = np.linspace(0.0, upper, n + 1)
    density = np.exp(log_norm - (dof + 1.0) / 2.0 * np.log1p(x * x / dof))
    h = upper / n
    integral = h / 3.0 * (density[0] + density[-1] + 4.0 * density[1:-1:2].sum() + 2.0 * density[2:-1:2].sum())
    return 0.5 + sign * integral


def student_t_two_sided_p(t: float, dof: float) -> float:
    return 2.0 * (1.0 - student_t_cdf(abs(t), dof))


def student_t_quantile(p: float, dof: float) -> float:
    """Upper quantile t such that CDF(t) = p, by bisection."""

    low, high = 0.0, 1000.0
    for _ in range(200):
        mid = 0.5 * (low + high)
        if student_t_cdf(mid, dof) < p:
            low = mid
        else:
            high = mid
    return 0.5 * (low + high)


def normal_two_sided_p(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2.0))


def chi2_sf(x: float, dof: int) -> float:
    """Survival function of chi-square for small integer dof (series)."""

    # Use the regularized upper incomplete gamma via numerical integration of
    # the density; dof is tiny here (2 .. 20), so a simple quadrature is fine.
    if x <= 0:
        return 1.0
    k = dof / 2.0
    upper = max(x, 1.0) * 50.0 + 100.0
    n = 400000
    t = np.linspace(x, upper, n + 1)
    with np.errstate(divide="ignore"):
        log_density = (k - 1.0) * np.log(t) - t / 2.0 - k * math.log(2.0) - math.lgamma(k)
    density = np.exp(log_density)
    h = (upper - x) / n
    return float(h / 3.0 * (density[0] + density[-1] + 4.0 * density[1:-1:2].sum() + 2.0 * density[2:-1:2].sum()))


def wls_line(x: np.ndarray, y: np.ndarray, sigma: np.ndarray) -> dict[str, float]:
    """Weighted least squares y = a + b x with weights 1/sigma^2.

    Returns the slope and intercept with the *unscaled* covariance
    (weights taken as absolute), the chi-square, the degrees of freedom and
    the *scaled* slope error (unscaled error times sqrt(chi2/dof), the
    particle-data-group scale-factor convention), which is what
    ``numpy.polyfit(cov=True)`` and ``scipy.optimize.curve_fit`` with
    ``absolute_sigma=False`` would return.
    """

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    w = 1.0 / np.asarray(sigma, dtype=float) ** 2
    design = np.stack([np.ones_like(x), x], axis=1)
    normal = design.T @ (w[:, None] * design)
    cov = np.linalg.inv(normal)
    beta = cov @ (design.T @ (w * y))
    residual = y - design @ beta
    chi2 = float(np.sum(w * residual**2))
    dof = int(x.size - 2)
    scale = math.sqrt(chi2 / dof) if dof > 0 else float("nan")
    return {
        "intercept": float(beta[0]),
        "slope": float(beta[1]),
        "slope_se_unscaled": float(math.sqrt(cov[1, 1])),
        "slope_se_scaled": float(math.sqrt(cov[1, 1]) * scale) if dof > 0 else float("nan"),
        "chi2": chi2,
        "dof": dof,
        "chi2_dof": chi2 / dof if dof > 0 else float("nan"),
        "chi2_p_value": chi2_sf(chi2, dof) if dof > 0 else float("nan"),
    }


def ols_line(x: np.ndarray, y: np.ndarray) -> dict[str, float]:
    """Ordinary least squares with the residual-based slope error."""

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = x.size
    xm, ym = x.mean(), y.mean()
    sxx = float(np.sum((x - xm) ** 2))
    slope = float(np.sum((x - xm) * (y - ym)) / sxx)
    intercept = float(ym - slope * xm)
    residual = y - (intercept + slope * x)
    dof = n - 2
    s2 = float(np.sum(residual**2) / dof) if dof > 0 else float("nan")
    return {
        "intercept": intercept,
        "slope": slope,
        "slope_se": math.sqrt(s2 / sxx) if dof > 0 else float("nan"),
        "dof": dof,
        "residual_rms": math.sqrt(s2) if dof > 0 else float("nan"),
    }


def mean_se(values: np.ndarray) -> tuple[float, float, float]:
    values = np.asarray(values, dtype=float)
    n = values.size
    sd = float(np.std(values, ddof=1)) if n > 1 else float("nan")
    return float(values.mean()), sd, sd / math.sqrt(n) if n > 1 else float("nan")


# --------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------


def load_record(repo: Path, name: str) -> tuple[dict[str, Any], str]:
    path = repo / EVIDENCE_DIR / name
    return json.loads(path.read_text()), sha256_of(path)


def run_rows(record: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for run in record["runs"]:
        on = run["arms"]["noise_on"]
        off = run["arms"]["operating_expectation"]
        variance_key = "noise_variance_m2" if "noise_variance_m2" in run else "noise_mean_square_m2"
        se_key = (
            "noise_variance_standard_error_m2"
            if "noise_variance_standard_error_m2" in run
            else "noise_mean_square_standard_error_m2"
        )
        rows.append(
            {
                "label": run["label"],
                "magnitude": float(run["label"][1:]),
                "seed": int(run["root_seed"]),
                "config_hash": run["config_hash"],
                "n_steps": int(run["n_steps"]),
                "burn_in_frames": int(run["burn_in_frames"]),
                "block_frames": int(run["block_frames"]),
                "ne": float(run["detected_e_full_subap"]),
                "model_var_px2": float(run["predicted_centroid_variance_px2"]),
                "supported_fraction": float(run["supported_lenslet_fraction"]),
                "estimand": variance_key,
                "dv_nm2": float(run[variance_key]) * NM2,
                "dv_se_nm2": (float(run[se_key]) * NM2) if run.get(se_key) is not None else float("nan"),
                "msd_nm2": float(run["mean_square_difference_m2"]) * NM2 if "mean_square_difference_m2" in run else float("nan"),
                "msd_se_nm2": (
                    float(run["mean_square_difference_standard_error_m2"]) * NM2
                    if run.get("mean_square_difference_standard_error_m2") is not None
                    else float("nan")
                ),
                "rms_on_nm": float(on["post_update_rms_m"]) * 1e9,
                "rms_off_nm": float(off["post_update_rms_m"]) * 1e9,
                "ms_on_nm2": float(on["post_update_mean_square_m2"]) * NM2,
                "ms_off_nm2": float(off["post_update_mean_square_m2"]) * NM2,
                "open_loop_nm": float(on["open_loop_rms_m"]) * 1e9,
                "valid_on": float(on["valid_measurement_fraction"]),
                "valid_off": float(off["valid_measurement_fraction"]),
                "usable_on": float(on["reconstruction_usable_fraction"]),
                "usable_off": float(off["reconstruction_usable_fraction"]),
                "lost_lock_on": bool(on["lost_lock"]),
                "lost_lock_off": bool(off["lost_lock"]),
                "wall_s": float(run["wall_s"]),
                "protocol_hash": run.get("protocol_hash"),
            }
        )
    return rows


def record_identity(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "command": record.get("command"),
        "argv": record.get("argv"),
        "python": record.get("python"),
        "numpy": record.get("numpy"),
        "scipy": record.get("scipy"),
        "machine": record.get("machine"),
        "started_unix_s": record.get("started_unix_s"),
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record["started_unix_s"])),
        "enabled_by_user": record.get("enabled_by_user"),
        "n_steps": record.get("n_steps"),
        "burn_in_frames": record.get("burn_in_frames"),
        "series_protocol_version": record.get("series_protocol_version"),
        "code_identity": record.get("code_identity"),
        "n_runs": len(record.get("runs", [])),
        "wall_s": record.get("wall_s"),
        "execution_options": record["runs"][0]["protocol"].get("execution") if record.get("runs") else None,
    }


# --------------------------------------------------------------------------
# The historical analysis, reproduced
# --------------------------------------------------------------------------


def per_magnitude(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Seed means, scatter, medians, model means and ratios per magnitude."""

    out: dict[str, dict[str, Any]] = {}
    for label in sorted({r["label"] for r in rows}, key=lambda s: float(s[1:])):
        group = [r for r in rows if r["label"] == label]
        dv = np.array([r["dv_nm2"] for r in group])
        model = np.array([r["model_var_px2"] for r in group])
        ne = np.array([r["ne"] for r in group])
        ratio = dv / model
        mean, sd, se = mean_se(dv)
        rmean, rsd, rse = mean_se(ratio)
        block_se = np.array([r["dv_se_nm2"] for r in group])
        out[label] = {
            "magnitude": group[0]["magnitude"],
            "seeds": [r["seed"] for r in group],
            "n": len(group),
            "ne_e": float(ne.mean()),
            "ne_spread_relative": float(ne.std() / ne.mean()),
            "dv_nm2": [float(v) for v in dv],
            "dv_mean_nm2": mean,
            "dv_seed_sd_nm2": sd,
            "dv_seed_se_nm2": se,
            "dv_median_nm2": float(np.median(dv)),
            "dv_block_se_nm2": [float(v) for v in block_se],
            "dv_block_se_rms_nm2": float(np.sqrt(np.nanmean(block_se**2))),
            "dv_times_ne": float(mean * ne.mean()),
            "model_var_mean_px2": float(model.mean()),
            "model_var_seed_sd_px2": float(model.std(ddof=1)) if len(group) > 1 else 0.0,
            "model_times_ne_px2_e": float(model.mean() * ne.mean()),
            "ratio_nm2_per_px2": [float(v) for v in ratio],
            "ratio_mean": rmean,
            "ratio_seed_se": rse,
            "ratio_median": float(np.median(ratio)),
            "valid_on_mean": float(np.mean([r["valid_on"] for r in group])),
            "valid_off_mean": float(np.mean([r["valid_off"] for r in group])),
            "valid_on_min": float(np.min([r["valid_on"] for r in group])),
            "supported_fraction_mean": float(np.mean([r["supported_fraction"] for r in group])),
            "lost_lock_any": bool(any(r["lost_lock_on"] or r["lost_lock_off"] for r in group)),
            "usable_on_min": float(np.min([r["usable_on"] for r in group])),
        }
    return out


def historical_fit(stats: dict[str, dict[str, Any]], *, exclude: tuple[str, ...] = ()) -> dict[str, Any]:
    """The predeclared fit: log dV (seed mean, weighted by its SE) vs log N_e."""

    labels = [k for k in stats if k not in exclude]
    ne = np.array([stats[k]["ne_e"] for k in labels])
    dv = np.array([stats[k]["dv_mean_nm2"] for k in labels])
    se = np.array([stats[k]["dv_seed_se_nm2"] for k in labels])
    model = np.array([stats[k]["model_var_mean_px2"] for k in labels])
    fit = wls_line(np.log(ne), np.log(dv), se / dv)  # delta method: sigma(log V) = SE/V
    fit["labels"] = labels
    fit["se_from_minus_one_unscaled"] = (fit["slope"] + 1.0) / fit["slope_se_unscaled"]
    fit["se_from_minus_one_scaled"] = (fit["slope"] + 1.0) / fit["slope_se_scaled"]
    fit["verdict_unscaled_two_se"] = "pass" if abs(fit["se_from_minus_one_unscaled"]) <= 2.0 else "fail"
    fit["verdict_scaled_two_se"] = "pass" if abs(fit["se_from_minus_one_scaled"]) <= 2.0 else "fail"
    model_fit = ols_line(np.log(ne), np.log(model))
    fit["model_slope"] = model_fit["slope"]
    fit["model_slope_se_ols"] = model_fit["slope_se"]
    power = wls_line(np.log(model), np.log(dv), se / dv)
    fit["power_of_model_variance"] = power["slope"]
    fit["power_of_model_variance_se_unscaled"] = power["slope_se_unscaled"]
    fit["power_of_model_variance_se_scaled"] = power["slope_se_scaled"]
    fit["power_of_model_variance_chi2_dof"] = power["chi2_dof"]
    return fit


def ratio_changes(stats: dict[str, dict[str, Any]]) -> dict[str, Any]:
    labels = list(stats)
    out: dict[str, Any] = {"adjacent": {}, "per_seed_paired": {}}
    for a, b in zip(labels[:-1], labels[1:]):
        out["adjacent"][f"{b}_vs_{a}"] = {
            "mean_ratio_change_percent": 100.0 * (stats[b]["ratio_mean"] / stats[a]["ratio_mean"] - 1.0),
            "median_ratio_change_percent": 100.0 * (stats[b]["ratio_median"] / stats[a]["ratio_median"] - 1.0),
        }
        # paired by seed (same root seed -> same atmosphere, maps and masters)
        ra = np.array(stats[a]["ratio_nm2_per_px2"])
        rb = np.array(stats[b]["ratio_nm2_per_px2"])
        change = 100.0 * (rb / ra - 1.0)
        mean, sd, se = mean_se(change)
        t = mean / se
        out["per_seed_paired"][f"{b}_vs_{a}"] = {
            "changes_percent": [float(v) for v in change],
            "mean_percent": mean,
            "sd_percent": sd,
            "se_percent": se,
            "t": t,
            "dof": int(change.size - 1),
            "p_two_sided": student_t_two_sided_p(t, change.size - 1),
        }
    first, last = labels[0], labels[-1]
    out["end_to_end"] = {
        "mean_ratio_change_percent": 100.0 * (stats[last]["ratio_mean"] / stats[first]["ratio_mean"] - 1.0),
        "median_ratio_change_percent": 100.0 * (stats[last]["ratio_median"] / stats[first]["ratio_median"] - 1.0),
    }
    # the same between the brightest magnitude and the faintest gate-quiet one
    quiet = [lab for lab in labels if stats[lab]["valid_on_min"] >= 0.999 and stats[lab]["valid_off_mean"] >= 0.999]
    if len(quiet) >= 2:
        a, b = quiet[0], quiet[-1]
        ra = np.array(stats[a]["ratio_nm2_per_px2"])
        rb = np.array(stats[b]["ratio_nm2_per_px2"])
        change = 100.0 * (rb / ra - 1.0)
        mean, sd, se = mean_se(change)
        out["gate_quiet_end_to_end_per_seed_paired"] = {
            "from": a,
            "to": b,
            "changes_percent": [float(v) for v in change],
            "mean_percent": mean,
            "sd_percent": sd,
            "se_percent": se,
            "t": mean / se,
            "dof": int(change.size - 1),
            "p_two_sided": student_t_two_sided_p(mean / se, change.size - 1),
        }
    return out


def seed_paired_bootstrap_unweighted(rows: list[dict[str, Any]], *, resamples: int, rng_seed: int) -> dict[str, Any]:
    """Resample whole seeds (all magnitudes of a seed together) and refit.

    The estimator is the unweighted ordinary least squares slope of
    log(seed mean dV) against log N_e, the kind of estimator the GPT audit's
    F-06 note describes.  The exact audit script is not in the repository, so
    this is a reconstruction of its convention, labelled as such.  Resamples
    of five seeds are not new realizations: they describe the sampling
    distribution implied by these five seeds only.
    """

    seeds = sorted({r["seed"] for r in rows})
    labels = sorted({r["label"] for r in rows}, key=lambda s: float(s[1:]))
    ne = np.array([np.mean([r["ne"] for r in rows if r["label"] == lab]) for lab in labels])
    table = {(r["seed"], r["label"]): r["dv_nm2"] for r in rows}
    rng = np.random.default_rng(rng_seed)
    slopes = []
    for _ in range(resamples):
        pick = rng.choice(seeds, size=len(seeds), replace=True)
        means = np.array([np.mean([table[(s, lab)] for s in pick]) for lab in labels])
        slopes.append(ols_line(np.log(ne), np.log(means))["slope"])
    slopes_arr = np.array(slopes)
    point = ols_line(np.log(ne), np.log(np.array([np.mean([table[(s, lab)] for s in seeds]) for lab in labels])))
    return {
        "estimator": "OLS slope of log(seed-mean dV) vs log N_e, unweighted; whole-seed resampling",
        "point_estimate": point["slope"],
        "point_estimate_ols_se": point["slope_se"],
        "bootstrap_mean": float(slopes_arr.mean()),
        "bootstrap_sd": float(slopes_arr.std(ddof=1)),
        "bootstrap_percentile_2.5": float(np.percentile(slopes_arr, 2.5)),
        "bootstrap_percentile_97.5": float(np.percentile(slopes_arr, 97.5)),
        "resamples": resamples,
        "rng_seed": rng_seed,
        "distinct_seed_subsets_possible": int(math.comb(2 * len(seeds) - 1, len(seeds))),
        "caveat": "resamples of the saved aggregates; not new realizations",
    }


# --------------------------------------------------------------------------
# Alternative estimators
# --------------------------------------------------------------------------


# Measurement rows per record (two rows per retained lenslet).  The paired
# records do not store the row count; the open-loop propagation records of the
# same profiles list 416 (12 m) and 21 (2 m) lenslets, and the geometry check
# below reproduces 416 at 12 m.
ROWS_PER_RECORD = {"12m_v3": 2 * 416, "2m": 2 * 21, "2m_attempt1": 2 * 21}


def alternative_estimators(rows: list[dict[str, Any]], stats: dict[str, dict[str, Any]], *, n_rows: int | None = None) -> dict[str, Any]:
    labels = list(stats)
    seeds = sorted({r["seed"] for r in rows})
    ne = np.array([stats[k]["ne_e"] for k in labels])
    log_ne = np.log(ne)
    table = {(r["seed"], r["label"]): r for r in rows}
    out: dict[str, Any] = {}

    # (a) OLS on the seed means (unweighted).
    means = np.array([stats[k]["dv_mean_nm2"] for k in labels])
    out["ols_on_seed_means"] = ols_line(log_ne, np.log(means))

    # (b) WLS on seed medians with the seed SE of the mean as the weight.
    medians = np.array([stats[k]["dv_median_nm2"] for k in labels])
    ses = np.array([stats[k]["dv_seed_se_nm2"] for k in labels])
    out["wls_on_seed_medians"] = wls_line(log_ne, np.log(medians), ses / medians)
    out["wls_on_seed_medians"]["note"] = "weights borrowed from the seed SE of the mean; exploratory"

    # (c) Per-seed paired slopes (each seed shares atmosphere, maps and masters
    #     across magnitudes; only the temporal noise differs).
    per_seed = {}
    for s in seeds:
        y = np.log(np.array([table[(s, lab)]["dv_nm2"] for lab in labels]))
        per_seed[str(s)] = ols_line(log_ne, y)["slope"]
    values = np.array(list(per_seed.values()))
    mean, sd, se = mean_se(values)
    dof = values.size - 1
    out["per_seed_paired_slopes"] = {
        "slopes": per_seed,
        "mean": mean,
        "sd": sd,
        "se": se,
        "dof": dof,
        "t_from_minus_one": (mean + 1.0) / se,
        "p_two_sided_from_minus_one": student_t_two_sided_p((mean + 1.0) / se, dof),
        "ci95_halfwidth": student_t_quantile(0.975, dof) * se,
        "t_quantile_0.975": student_t_quantile(0.975, dof),
    }

    # (d) Leave-one-seed-out on the historical weighted estimator.
    loo = {}
    for s in seeds:
        sub = [r for r in rows if r["seed"] != s]
        loo[str(s)] = historical_fit(per_magnitude(sub))["slope"]
    out["leave_one_seed_out_weighted_slope"] = loo
    out["leave_one_seed_out_weighted_slope_range"] = [min(loo.values()), max(loo.values())]

    # (e) Two-way OLS: log dV_{m,s} = a + b log N_m + u_s + e.
    y = []
    design = []
    for r in rows:
        y.append(math.log(r["dv_nm2"]))
        row = [1.0, math.log(r["ne"])]
        row += [1.0 if r["seed"] == s else 0.0 for s in seeds[1:]]
        design.append(row)
    design_arr = np.array(design)
    y_arr = np.array(y)
    beta, *_ = np.linalg.lstsq(design_arr, y_arr, rcond=None)
    resid = y_arr - design_arr @ beta
    dof = y_arr.size - design_arr.shape[1]
    s2 = float(resid @ resid / dof)
    cov = s2 * np.linalg.inv(design_arr.T @ design_arr)
    out["two_way_ols_with_seed_effects"] = {
        "slope": float(beta[1]),
        "slope_se": float(math.sqrt(cov[1, 1])),
        "dof": int(dof),
        "residual_rms_log": math.sqrt(s2),
        "t_from_minus_one": float((beta[1] + 1.0) / math.sqrt(cov[1, 1])),
        "p_two_sided_from_minus_one": student_t_two_sided_p(float((beta[1] + 1.0) / math.sqrt(cov[1, 1])), dof),
    }

    # (f) WLS over all runs with the recorded 25-frame block standard errors.
    x_all = np.array([math.log(r["ne"]) for r in rows])
    y_all = np.array([math.log(r["dv_nm2"]) for r in rows])
    s_all = np.array([r["dv_se_nm2"] / r["dv_nm2"] for r in rows])
    out["wls_all_runs_block_se"] = wls_line(x_all, y_all, s_all)
    out["wls_all_runs_block_se"]["note"] = (
        "chi2/dof far above one means the block errors do not describe the run-to-run scatter"
    )

    # (g) Overdispersion: seed scatter versus block errors, per magnitude.
    over = {}
    for lab in labels:
        sd = stats[lab]["dv_seed_sd_nm2"]
        block = stats[lab]["dv_block_se_rms_nm2"]
        over[lab] = {
            "seed_sd_nm2": sd,
            "block_se_rms_nm2": block,
            "ratio_seed_sd_over_block_se": sd / block if block > 0 else float("nan"),
            "seed_sd_percent": 100.0 * sd / stats[lab]["dv_mean_nm2"],
            "block_se_percent": 100.0 * block / stats[lab]["dv_mean_nm2"],
        }
    out["overdispersion"] = over

    # (h) Floor-share linear fit: dV * N_e = alpha + beta / N_e  (exact for a
    #     variance a/N + b/N^2); the same for the model's own variance.
    inv_ne = 1.0 / ne
    prod = means * ne
    prod_se = ses * ne
    fit = wls_line(inv_ne, prod, prod_se)
    model_prod = np.array([stats[k]["model_times_ne_px2_e"] for k in labels])
    model_fit = ols_line(inv_ne, model_prod)
    def ratio_se(f: dict[str, float], xs: np.ndarray, ss: np.ndarray) -> float:
        # delta-method error of beta/alpha from the unscaled WLS covariance
        w = 1.0 / ss**2
        design = np.stack([np.ones_like(xs), xs], axis=1)
        cov = np.linalg.inv(design.T @ (w[:, None] * design))
        a, b = f["intercept"], f["slope"]
        grad = np.array([-b / a**2, 1.0 / a])
        return float(math.sqrt(grad @ cov @ grad))

    out["floor_share_linear_fit"] = {
        "description": "dV*N_e = alpha + beta/N_e (WLS, seed SE); model: sigma2*N_e = a + b/N_e (OLS)",
        "alpha_nm2_e": fit["intercept"],
        "beta_nm2_e2": fit["slope"],
        "chi2_dof": fit["chi2_dof"],
        "chi2_p_value": fit["chi2_p_value"],
        "beta_over_alpha_e": fit["slope"] / fit["intercept"],
        "beta_over_alpha_se_e": ratio_se(fit, inv_ne, prod_se),
        "model_a_px2_e": model_fit["intercept"],
        "model_b_px2_e2": model_fit["slope"],
        "model_b_over_a_e": model_fit["slope"] / model_fit["intercept"],
        "interpretation": "beta/alpha (electrons) is the flux at which the measured additive floor equals the photon term; compare with the model's b/a",
    }
    # the same with medians (robust to a single excursion) and with the
    # faintest magnitude dropped
    med_prod = medians * ne
    fit_med = wls_line(inv_ne, med_prod, prod_se)
    out["floor_share_linear_fit"]["medians_beta_over_alpha_e"] = fit_med["slope"] / fit_med["intercept"]
    if len(labels) > 3:
        fit_drop = wls_line(inv_ne[:-1], prod[:-1], prod_se[:-1])
        out["floor_share_linear_fit"]["without_faintest_beta_over_alpha_e"] = fit_drop["slope"] / fit_drop["intercept"]
        out["floor_share_linear_fit"]["without_faintest_beta_over_alpha_se_e"] = ratio_se(fit_drop, inv_ne[:-1], prod_se[:-1])
        out["floor_share_linear_fit"]["without_faintest_chi2_dof"] = fit_drop["chi2_dof"]
    # model floor share per magnitude implied by the model fit
    out["floor_share_linear_fit"]["model_floor_share_per_magnitude"] = {
        lab: float(model_fit["slope"] / ne_i / (model_fit["intercept"] + model_fit["slope"] / ne_i))
        for lab, ne_i in zip(labels, ne)
    }

    # (h2) Gate-free subset: magnitudes where every run of both arms kept
    #      every row valid (no gate acted), fitted with the historical
    #      weighted estimator and with the per-seed paired slopes.
    # "gate-quiet": at most about one invalid lenslet-frame per hundred
    # frames in every run of both arms (the records hold no row counts, so
    # the fraction itself is the criterion; the implied row-frame counts are
    # reported in ``invalid_row_frames``).
    gate_free = [lab for lab in labels if stats[lab]["valid_on_min"] >= 0.999 and stats[lab]["valid_off_mean"] >= 0.999]
    if len(gate_free) >= 3:
        sub_stats = {lab: stats[lab] for lab in gate_free}
        sub_fit = historical_fit(sub_stats)
        per_seed_sub = []
        for s in seeds:
            y = np.log(np.array([table[(s, lab)]["dv_nm2"] for lab in gate_free]))
            per_seed_sub.append(ols_line(np.log(np.array([stats[lab]["ne_e"] for lab in gate_free])), y)["slope"])
        arr = np.array(per_seed_sub)
        mean, sd, se = mean_se(arr)
        out["gate_free_subset"] = {
            "criterion": "every run of both arms has a mean valid fraction >= 0.999",
            "magnitudes": gate_free,
            "weighted_slope": sub_fit["slope"],
            "weighted_slope_se_unscaled": sub_fit["slope_se_unscaled"],
            "weighted_slope_se_scaled": sub_fit["slope_se_scaled"],
            "chi2_dof": sub_fit["chi2_dof"],
            "model_slope": sub_fit["model_slope"],
            "power_of_model_variance": sub_fit["power_of_model_variance"],
            "power_of_model_variance_se_unscaled": sub_fit["power_of_model_variance_se_unscaled"],
            "per_seed_slopes_mean": mean,
            "per_seed_slopes_se": se,
            "per_seed_slopes_dof": int(arr.size - 1),
        }
    # (h3) Per-seed paired slopes without the seed whose faintest run has
    #      the largest block error (the recorded single excursion).
    faint = labels[-1]
    worst = max(seeds, key=lambda s: table[(s, faint)]["dv_se_nm2"])
    keep = [s for s in seeds if s != worst]
    arr = np.array([
        ols_line(log_ne, np.log(np.array([table[(s, lab)]["dv_nm2"] for lab in labels])))["slope"] for s in keep
    ])
    mean, sd, se = mean_se(arr)
    out["per_seed_paired_slopes_without_excursion_seed"] = {
        "excluded_seed": int(worst),
        "reason": f"largest 25-frame block error at {faint}",
        "mean": mean,
        "se": se,
        "dof": int(arr.size - 1),
    }
    # (h4) Realization dependence of the ratio in the gate-free magnitudes:
    #      correlation of the per-run ratio (normalised by its magnitude's
    #      median) with the noiseless twin's residual level.
    if len(gate_free) >= 2:
        xs, ys = [], []
        for lab in gate_free:
            med = stats[lab]["ratio_median"]
            for s in seeds:
                r = table[(s, lab)]
                xs.append(r["rms_off_nm"])
                ys.append(r["dv_nm2"] / r["model_var_px2"] / med - 1.0)
        xs_a, ys_a = np.array(xs), np.array(ys)
        out["ratio_vs_twin_residual_gate_free"] = {
            "n_runs": int(xs_a.size),
            "pearson_r": float(np.corrcoef(xs_a, ys_a)[0, 1]),
            "ols_slope_per_nm": ols_line(xs_a, ys_a)["slope"],
            "ols_slope_se_per_nm": ols_line(xs_a, ys_a)["slope_se"],
            "twin_residual_range_nm": [float(xs_a.min()), float(xs_a.max())],
        }

    # (i) Cross term of the difference-of-variances estimator:
    #     msd - dV = 2 <phi_common, delta> per run (zero for a linear loop).
    cross = {}
    for lab in labels:
        group = [table[(s, lab)] for s in seeds]
        c = np.array([r["msd_nm2"] - r["dv_nm2"] for r in group])
        c_se = np.array([math.sqrt(max(r["msd_se_nm2"] ** 2 - r["dv_se_nm2"] ** 2, 0.0)) for r in group])
        # mean over seeds with the propagated per-run errors (approximate: the
        # per-frame covariance of msd and dV is not saved)
        w = 1.0 / np.maximum(c_se, 1e-9) ** 2
        wmean = float(np.sum(w * c) / np.sum(w))
        wse = float(1.0 / math.sqrt(np.sum(w)))
        mean, sd, se = mean_se(c)
        cross[lab] = {
            "per_run_cross_term_nm2": [float(v) for v in c],
            "per_run_cross_se_nm2": [float(v) for v in c_se],
            "mean_nm2": mean,
            "seed_se_nm2": se,
            "weighted_mean_nm2": wmean,
            "weighted_se_nm2": wse,
            "z_weighted": wmean / wse,
            "relative_to_dv_percent": 100.0 * mean / stats[lab]["dv_mean_nm2"],
            "msd_se_over_dv_se_median": float(np.median([r["msd_se_nm2"] / r["dv_se_nm2"] for r in group])),
        }
    out["difference_of_variances_cross_term"] = cross

    # (j) Arm valid-fraction divergence as a gate-divergence indicator.
    div = []
    for r in rows:
        div.append(
            {
                "label": r["label"],
                "seed": r["seed"],
                "valid_on": r["valid_on"],
                "valid_off": r["valid_off"],
                "arm_difference": r["valid_on"] - r["valid_off"],
                "dv_nm2": r["dv_nm2"],
                "dv_block_se_nm2": r["dv_se_nm2"],
                "cross_term_nm2": r["msd_nm2"] - r["dv_nm2"],
            }
        )
    out["arm_valid_fraction_divergence"] = div
    if n_rows is not None:
        frames = rows[0]["n_steps"] - rows[0]["burn_in_frames"]
        out["invalid_row_frames"] = {
            "rows": int(n_rows),
            "analysed_frames": int(frames),
            "per_magnitude_mean_per_run": {
                lab: {
                    "noise_on": float((1.0 - stats[lab]["valid_on_mean"]) * n_rows * frames),
                    "operating_expectation": float((1.0 - stats[lab]["valid_off_mean"]) * n_rows * frames),
                    "arm_difference_mean_abs": float(np.mean([abs(r["valid_on"] - r["valid_off"]) for r in rows if r["label"] == lab]) * n_rows * frames),
                }
                for lab in labels
            },
            "note": "row-frames = (1 - mean valid fraction) x rows x analysed frames; a lenslet contributes two rows",
        }
    # correlation, among runs with any invalid rows, between |arm difference|
    # and the deviation of dV from its magnitude median
    gated = [d for d in div if d["valid_on"] < 1.0 or d["valid_off"] < 1.0]
    if len(gated) >= 3:
        x = np.array([abs(d["arm_difference"]) for d in gated])
        y = np.array([d["dv_nm2"] / stats[d["label"]]["dv_median_nm2"] - 1.0 for d in gated])
        out["gate_divergence_correlation"] = {
            "n_runs_with_invalid_rows": len(gated),
            "pearson_r_absdiff_vs_dv_excess": float(np.corrcoef(x, y)[0, 1]),
            "spearman_r": float(np.corrcoef(np.argsort(np.argsort(x)), np.argsort(np.argsort(y)))[0, 1]),
        }
    return out


# --------------------------------------------------------------------------
# Synthetic statistical examples (not AO simulations)
# --------------------------------------------------------------------------


def synthetic_examples(rng_seed: int = 20261020) -> dict[str, Any]:
    rng = np.random.default_rng(rng_seed)
    out: dict[str, Any] = {"rng_seed": rng_seed}

    # 1. Block standard error of a correlated series versus block length.
    #    An AR(1) series with correlation time tau has integrated
    #    autocorrelation time tau_int = (1 + phi) / (2 (1 - phi)).
    def ar1(n: int, phi: float) -> np.ndarray:
        x = np.empty(n)
        x[0] = rng.normal() / math.sqrt(1 - phi**2)
        for i in range(1, n):
            x[i] = phi * x[i - 1] + rng.normal()
        return x

    def block_se(x: np.ndarray, block: int) -> float:
        usable = x[: x.size // block * block]
        blocks = usable.reshape(-1, block).mean(axis=1)
        return float(np.std(blocks, ddof=1) / math.sqrt(blocks.size))

    blocking = {}
    for tau in (3.0, 10.0, 50.0):
        phi = math.exp(-1.0 / tau)
        true_var_mean = []
        est = {b: [] for b in (1, 5, 25, 75)}
        n = 300
        for _ in range(400):
            x = ar1(n, phi)
            true_var_mean.append(x.mean())
            for b in est:
                est[b].append(block_se(x, b))
        truth = float(np.std(true_var_mean, ddof=1))
        blocking[f"tau_{tau:g}"] = {
            "phi": phi,
            "tau_int": (1 + phi) / (2 * (1 - phi)),
            "frames": n,
            "true_se_of_mean": truth,
            "block_se_mean_over_true": {str(b): float(np.mean(v) / truth) for b, v in est.items()},
        }
    out["block_se_vs_correlation_time"] = blocking

    # 2. Difference of variances versus the paired map difference in a
    #    linear toy loop: common signal c_t (AR(1), large), noise-driven term
    #    n_t (AR(1), small, independent).  on = c + n, off = c.
    toy = {}
    n = 300
    for amplitude in (1.0, 10.0, 50.0):
        est_paired, est_diff = [], []
        for _ in range(400):
            c = amplitude * ar1(n, math.exp(-1 / 20.0))
            noise = ar1(n, math.exp(-1 / 3.0))
            on, off = c + noise, c
            est_paired.append(np.mean((on - off) ** 2))
            est_diff.append(np.mean(on**2) - np.mean(off**2))
        toy[f"common_over_noise_rms_{amplitude:g}"] = {
            "true_noise_variance": 1.0 / (1 - math.exp(-2 / 3.0)),
            "paired_mean": float(np.mean(est_paired)),
            "paired_sd": float(np.std(est_paired, ddof=1)),
            "difference_of_variances_mean": float(np.mean(est_diff)),
            "difference_of_variances_sd": float(np.std(est_diff, ddof=1)),
        }
    out["difference_of_variances_vs_paired"] = toy

    # 3. A transient excursion in one of five runs: effect on mean, median,
    #    the block SE and an unweighted log-log slope over four flux levels.
    flux = np.array([2541.0, 1012.0, 403.0, 160.0])
    true_var = 2.85e5 / flux  # a pure 1/N law in the saved units
    slopes_clean, slopes_exc, medians_exc = [], [], []
    for _ in range(400):
        means_clean, means_exc, meds = [], [], []
        for v in true_var:
            runs = []
            for s in range(5):
                series = v * (1 + 0.15 * ar1(300, math.exp(-1 / 3.0)) / math.sqrt(1 / (1 - math.exp(-2 / 3.0))))
                runs.append(series.mean())
            means_clean.append(np.mean(runs))
            runs_exc = list(runs)
            if v == true_var[-1]:
                # one run with a 60-frame excursion at three times the level
                series = v * np.ones(300)
                series[100:160] *= 3.0
                runs_exc[1] = series.mean()
            means_exc.append(np.mean(runs_exc))
            meds.append(np.median(runs_exc))
        slopes_clean.append(ols_line(np.log(flux), np.log(np.array(means_clean)))["slope"])
        slopes_exc.append(ols_line(np.log(flux), np.log(np.array(means_exc)))["slope"])
        medians_exc.append(ols_line(np.log(flux), np.log(np.array(meds)))["slope"])
    # 4. Plausibility of the spot-broadening hypothesis (H1): the intensity-
    #    weighted second moment of a spot inside a 15-pixel window, for a
    #    diffraction-limited circular-aperture spot sampled at two pixels per
    #    lambda/d (the 12 m profile's Nyquist sampling) and for the same spot
    #    behind random high-order phase of a given tilt-removed variance.
    #    This is a stand-alone numerical illustration with a toy pupil; it is
    #    not the repository's optics model and carries no diffusion, band or
    #    pixel-integration effects.  The photon term of the centroid variance
    #    is proportional to this second moment, so the ratio reported is the
    #    factor a'/a by which closed-loop spots raise the photon term.
    n_sub = 16          # pupil samples across the subaperture
    pad = 8             # oversampling of the focal plane relative to lambda/d
    grid = n_sub * pad  # focal grid; one lambda/d spans ``pad`` grid points
    yy, xx = np.mgrid[0:n_sub, 0:n_sub]
    pupil = np.ones((n_sub, n_sub))  # a square subaperture of a square-lenslet array
    half_window_px = 7.5
    px_per_lod = 2.0    # Nyquist: two pixels per lambda/d
    grid_per_px = pad / px_per_lod
    centre = grid // 2
    coords = (np.arange(grid) - centre) / grid_per_px  # in pixels
    inside = np.abs(coords) <= half_window_px
    cx, cy = np.meshgrid(coords[inside], coords[inside])

    def second_moment(phase: np.ndarray) -> tuple[float, float]:
        field = np.zeros((grid, grid), dtype=complex)
        field[:n_sub, :n_sub] = pupil * np.exp(1j * phase)
        image = np.abs(np.fft.fftshift(np.fft.fft2(field))) ** 2
        window = image[np.ix_(inside, inside)]
        total = window.sum()
        capture = total / image.sum()
        c_x = (window * cx).sum() / total
        c_y = (window * cy).sum() / total
        m2 = ((window * ((cx - c_x) ** 2 + (cy - c_y) ** 2)).sum() / total)
        return float(m2), float(capture)

    def high_order_phase(variance_rad2: float) -> np.ndarray:
        # Kolmogorov-like random phase on the subaperture, piston and tilt
        # removed, scaled to the requested variance.
        k = np.fft.fftfreq(n_sub)[:, None] ** 2 + np.fft.fftfreq(n_sub)[None, :] ** 2
        amp = np.where(k > 0, k ** (-11.0 / 12.0), 0.0)
        screen = np.real(np.fft.ifft2(amp * (rng.normal(size=(n_sub, n_sub)) + 1j * rng.normal(size=(n_sub, n_sub)))))
        design = np.stack([np.ones(n_sub * n_sub), xx.ravel() - xx.mean(), yy.ravel() - yy.mean()], axis=1)
        coeff, *_ = np.linalg.lstsq(design, screen.ravel(), rcond=None)
        screen = screen - (design @ coeff).reshape(n_sub, n_sub)
        return screen / screen.std() * math.sqrt(variance_rad2)

    flat_m2, flat_capture = second_moment(np.zeros((n_sub, n_sub)))
    broadening = {"flat_second_moment_px2_x_plus_y": flat_m2, "flat_window_capture": flat_capture}
    for variance in (0.25, 0.5, 1.0, 1.5):
        ratios, captures = [], []
        for _ in range(100):
            m2, capture = second_moment(high_order_phase(variance))
            ratios.append(m2 / flat_m2)
            captures.append(capture)
        broadening[f"tilt_removed_variance_{variance:g}_rad2"] = {
            "second_moment_ratio_mean": float(np.mean(ratios)),
            "second_moment_ratio_sd": float(np.std(ratios, ddof=1)),
            "window_capture_mean": float(np.mean(captures)),
        }
    out["spot_broadening_second_moment"] = broadening

    out["single_run_excursion"] = {
        "true_slope": -1.0,
        "unweighted_slope_clean_mean": float(np.mean(slopes_clean)),
        "unweighted_slope_with_excursion_mean": float(np.mean(slopes_exc)),
        "median_based_slope_with_excursion_mean": float(np.mean(medians_exc)),
        "excursion": "one of five runs at the faintest level carries a 60-frame excursion at 3x its level (+40 % run mean)",
    }
    return out


# --------------------------------------------------------------------------
# Optional package checks (import only; no system is built)
# --------------------------------------------------------------------------


def package_checks(repo: Path, records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    sys.path.insert(0, str(repo / "src"))
    try:
        import shwfs_ao  # noqa: F401
        from dataclasses import replace

        from shwfs_ao.experiments.detector_level import with_magnitude
        from shwfs_ao.experiments.scao import physical_detector_config
        from shwfs_ao.io.configs import RandomSeedConfig, load_system_profile
    except Exception as exc:  # pragma: no cover - environment dependent
        return {"available": False, "reason": repr(exc)}
    out: dict[str, Any] = {"available": True, "package_file": shwfs_ao.__file__}
    profiles = {"12m_v3": ("det_emccd_12m_medium_derived", 3), "2m": ("det_emccd_2m_synthetic", 1), "2m_attempt1": ("det_emccd_2m_synthetic", 1)}
    for key, record in records.items():
        base = load_system_profile(*profiles[key])
        matches = 0
        mismatches = []
        for run in record["runs"]:
            magnitude = float(run["label"][1:])
            cfg = replace(
                with_magnitude(base, magnitude),
                random=RandomSeedConfig(root_seed=int(run["root_seed"])),
                controller=replace(base.controller, n_steps=int(run["n_steps"])),
            )
            if cfg.config_hash == run["config_hash"]:
                matches += 1
            else:
                mismatches.append([run["label"], run["root_seed"]])
        entry: dict[str, Any] = {"config_hash_matches": matches, "config_hash_mismatches": mismatches, "runs": len(record["runs"])}
        pd = physical_detector_config(base)
        cam = pd.camera
        entry["camera"] = {
            k: getattr(cam, k)
            for k in (
                "preset_name", "preset_version", "model", "em_gain", "read_noise_e", "cic_e_per_pixel_read",
                "conversion_gain_e_per_adu", "adc_bits", "bias_adu", "full_well_e", "register_full_well_e",
                "excess_noise_factor_squared", "dark_e_per_s",
            )
            if hasattr(cam, k)
        }
        entry["camera"]["has_coupling"] = bool(cam.has_coupling)
        entry["window_px"] = base.wfs.detector_window_px
        entry["exposure_s"] = pd.exposure_s
        entry["sky_ab_mag_per_arcsec2"] = pd.source.sky_ab_mag_per_arcsec2
        entry["calibration_source_detected_e_per_full_subap_frame"] = pd.calibration_source_detected_e_per_full_subap_frame
        entry["reconstructor"] = {"kind": base.reconstructor.kind, "alpha": base.reconstructor.alpha, "rcond": base.reconstructor.rcond, "min_valid_fraction": base.reconstructor.min_valid_fraction}
        entry["controller"] = {"gain": base.controller.gain, "leak": base.controller.leak, "latency_frames": base.controller.latency_frames, "frame_rate_hz": base.controller.frame_rate_hz, "recovery": None if base.controller.recovery is None else str(base.controller.recovery)}
        entry["validity"] = {k: getattr(base.wfs, k) for k in ("min_flux_e", "min_peak_snr", "max_centroid_sigma_px", "max_window_clipping_fraction", "min_fill_fraction")}
        out[key] = entry
        if key == "12m_v3":
            # Lenslet illumination distribution (geometry only; no system built).
            try:
                from shwfs_ao.backends.native.factory import NativeScaoComponentFactory

                factory = NativeScaoComponentFactory()
                geometry = factory.build_geometry(
                    telescope_diameter_m=base.telescope_diameter_m,
                    pupil_pixels=base.pupil_pixels,
                    lenslets_across=base.lenslets_across,
                    min_fill_fraction=base.wfs.min_fill_fraction,
                    central_obstruction_ratio=base.wfs.central_obstruction_ratio,
                    spider_width_m=base.wfs.spider_width_m,
                    representation="compact_cells",
                )
                counts = getattr(geometry, "illuminated_counts", None)
                if counts is None:
                    counts = np.array([np.count_nonzero(m) for m in geometry.subaperture_masks], dtype=float)
                counts = np.asarray(counts, dtype=float)
                full = float((base.pupil_pixels / base.lenslets_across) ** 2)
                fraction = counts / full
                hist, edges = np.histogram(fraction, bins=[0.5, 0.6, 0.7, 0.8, 0.9, 0.999, 1.001])
                entry["lenslet_illumination"] = {
                    "n_lenslets": int(fraction.size),
                    "fraction_min": float(fraction.min()),
                    "fraction_mean": float(fraction.mean()),
                    "fully_illuminated": int(np.sum(fraction >= 0.999)),
                    "histogram_edges": [float(e) for e in edges],
                    "histogram_counts": [int(h) for h in hist],
                    # mean of 1/f and 1/f^2 over lenslets: the factors by which an
                    # equal-weight mean of per-lenslet variance exceeds the
                    # full-subaperture value for a 1/N and a 1/N^2 term
                    "mean_inverse_fraction": float(np.mean(1.0 / fraction)),
                    "mean_inverse_fraction_squared": float(np.mean(1.0 / fraction**2)),
                }
            except Exception as exc:  # pragma: no cover
                entry["lenslet_illumination"] = {"error": repr(exc)}
    return out


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def git_identity(repo: Path) -> dict[str, Any]:
    def run(*args: str) -> str | None:
        try:
            return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
        except Exception:
            return None

    return {
        "head": run("rev-parse", "HEAD"),
        "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
        "status_porcelain_excluding_this_directory": [
            line for line in (run("status", "--porcelain") or "").splitlines() if "docs/research/s4_noise_law" not in line
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, default=HERE.parents[2], help="repository root (default: inferred)")
    parser.add_argument("--output", type=Path, default=HERE / "RESULTS.json")
    parser.add_argument("--with-package", action="store_true", help="also run the shwfs_ao import-only checks")
    parser.add_argument("--skip-synthetic", action="store_true")
    parser.add_argument("--bootstrap-resamples", type=int, default=10000)
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    started = time.time()

    results: dict[str, Any] = {
        "title": "S4 noise-law reanalysis of the saved paired noise-isolation records",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
        "script": str(Path(__file__).resolve().relative_to(repo)) if str(Path(__file__).resolve()).startswith(str(repo)) else str(Path(__file__).resolve()),
        "script_sha256": sha256_of(Path(__file__).resolve()),
        "environment": {
            "python": sys.version,
            "numpy": np.__version__,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
        },
        "source_identity": git_identity(repo),
        "inputs": {},
        "records": {},
        "quoted_values": QUOTED,
    }

    records: dict[str, dict[str, Any]] = {}
    for key, name in RECORDS.items():
        record, digest = load_record(repo, name)
        records[key] = record
        results["inputs"][key] = {"path": str(EVIDENCE_DIR / name), "sha256": digest}
        results["records"][key] = {"identity": record_identity(record), "runs": run_rows(record)}

    print("=" * 78)
    print("S4 noise-law reanalysis -- saved records only")
    print("=" * 78)
    for key in RECORDS:
        ident = results["records"][key]["identity"]
        print(f"{key}: {RECORDS[key]} sha256={results['inputs'][key]['sha256'][:16]}... runs={ident['n_runs']} "
              f"protocol v{ident['series_protocol_version']} code={ident['code_identity']} started={ident['started_utc']}")

    analysis: dict[str, Any] = {}
    for key in ("12m_v3", "2m"):
        rows = results["records"][key]["runs"]
        stats = per_magnitude(rows)
        fit = historical_fit(stats)
        changes = ratio_changes(stats)
        alt = alternative_estimators(rows, stats, n_rows=ROWS_PER_RECORD.get(key))
        boot = seed_paired_bootstrap_unweighted(rows, resamples=args.bootstrap_resamples, rng_seed=12345)
        analysis[key] = {
            "per_magnitude": stats,
            "historical_fit": fit,
            "ratio_changes": changes,
            "alternative_estimators": alt,
            "seed_paired_bootstrap_unweighted": boot,
        }
        quoted = QUOTED[key]
        reproduction = {
            "slope": (quoted["slope"], fit["slope"]),
            "slope_se_unscaled": (quoted["slope_se"], fit["slope_se_unscaled"]),
            "chi2_dof": (quoted["chi2_dof"], fit["chi2_dof"]),
            "se_from_minus_one": (quoted["se_from_minus_one"], fit["se_from_minus_one_unscaled"]),
            "model_slope": (quoted["model_slope"], fit["model_slope"]),
            "power_of_model": (quoted["power_of_model"], fit["power_of_model_variance"]),
            "power_of_model_se": (quoted["power_of_model_se"], fit["power_of_model_variance_se_unscaled"]),
        }
        if "scaled_se_from_minus_one" in quoted:
            reproduction["scaled_se_from_minus_one"] = (quoted["scaled_se_from_minus_one"], fit["se_from_minus_one_scaled"])
        if "dip_m10_vs_m9_percent" in quoted:
            reproduction["dip_m10_vs_m9_percent"] = (quoted["dip_m10_vs_m9_percent"], changes["adjacent"]["m10_vs_m9"]["mean_ratio_change_percent"])
        if "drift_m7_vs_m5_percent" in quoted:
            reproduction["drift_m7_vs_m5_percent"] = (quoted["drift_m7_vs_m5_percent"], 100.0 * (stats["m7"]["ratio_mean"] / stats["m5"]["ratio_mean"] - 1.0))
        if "f06_unweighted_bootstrap_slope" in quoted:
            reproduction["f06_unweighted_bootstrap_slope"] = (quoted["f06_unweighted_bootstrap_slope"], boot["point_estimate"])
            reproduction["f06_unweighted_bootstrap_sd"] = (quoted["f06_unweighted_bootstrap_sd"], boot["bootstrap_sd"])
        for lab, (q_mean, q_se, q_ratio, q_ratio_se, q_model_ne) in quoted["table"].items():
            reproduction[f"table_{lab}_dv_mean"] = (q_mean, stats[lab]["dv_mean_nm2"])
            reproduction[f"table_{lab}_dv_se"] = (q_se, stats[lab]["dv_seed_se_nm2"])
            reproduction[f"table_{lab}_ratio"] = (q_ratio, stats[lab]["ratio_mean"])
            reproduction[f"table_{lab}_model_times_ne"] = (q_model_ne, stats[lab]["model_times_ne_px2_e"])
        analysis[key]["reproduction_quoted_vs_recomputed"] = {
            k: {
                "quoted": q,
                "recomputed": (abs(r) if k.endswith("se_from_minus_one") else r),
                "difference": (abs(r) if k.endswith("se_from_minus_one") else r) - q,
            }
            for k, (q, r) in reproduction.items()
        }
        print()
        print("-" * 78)
        print(f"{key}: per-magnitude seed statistics")
        print(f"{'m':>4} {'N_e':>8} {'dV mean':>9} {'seedSE':>7} {'median':>8} {'blockSE':>8} {'dV*Ne':>9} {'model':>9} {'model*Ne':>9} {'ratio':>8} {'rSE':>6} {'valid_on':>8} {'supp':>6}")
        for lab, s in stats.items():
            print(f"{lab:>4} {s['ne_e']:8.1f} {s['dv_mean_nm2']:9.2f} {s['dv_seed_se_nm2']:7.2f} {s['dv_median_nm2']:8.2f} {s['dv_block_se_rms_nm2']:8.2f} "
                  f"{s['dv_times_ne']:9.0f} {s['model_var_mean_px2']:9.5f} {s['model_times_ne_px2_e']:9.3f} {s['ratio_mean']:8.0f} {s['ratio_seed_se']:6.0f} {s['valid_on_mean']:8.4f} {s['supported_fraction_mean']:6.3f}")
        print(f"historical weighted log-log fit: slope {fit['slope']:.4f} +- {fit['slope_se_unscaled']:.4f} (unscaled), "
              f"+- {fit['slope_se_scaled']:.4f} (scaled); chi2/dof {fit['chi2_dof']:.3f} (p={fit['chi2_p_value']:.3f}); "
              f"{fit['se_from_minus_one_unscaled']:.2f} SE from -1 (scaled {fit['se_from_minus_one_scaled']:.2f}) -> "
              f"{fit['verdict_unscaled_two_se']} (unscaled) / {fit['verdict_scaled_two_se']} (scaled)")
        print(f"   quoted: slope {quoted['slope']} +- {quoted['slope_se']}, chi2/dof {quoted['chi2_dof']}, {quoted['se_from_minus_one']} SE")
        print(f"model slope {fit['model_slope']:.4f} (quoted {quoted['model_slope']}); power of model variance "
              f"{fit['power_of_model_variance']:.4f} +- {fit['power_of_model_variance_se_unscaled']:.4f} (quoted {quoted['power_of_model']} +- {quoted['power_of_model_se']})")
        for name, change in changes["adjacent"].items():
            paired = changes["per_seed_paired"][name]
            print(f"ratio change {name}: mean {change['mean_ratio_change_percent']:+.2f} %, median {change['median_ratio_change_percent']:+.2f} %; "
                  f"per-seed paired {paired['mean_percent']:+.2f} +- {paired['se_percent']:.2f} % (t={paired['t']:.2f}, dof {paired['dof']}, p={paired['p_two_sided']:.3f})")
        print(f"ratio end-to-end: mean {changes['end_to_end']['mean_ratio_change_percent']:+.2f} %, median {changes['end_to_end']['median_ratio_change_percent']:+.2f} %")
        if "gate_quiet_end_to_end_per_seed_paired" in changes:
            q = changes["gate_quiet_end_to_end_per_seed_paired"]
            print(f"ratio change {q['to']} vs {q['from']} (gate-quiet ends), per-seed paired: {q['mean_percent']:+.2f} +- {q['se_percent']:.2f} % (t={q['t']:.2f}, dof {q['dof']}, p={q['p_two_sided']:.3f})")
        ps = alt["per_seed_paired_slopes"]
        print(f"per-seed paired slopes: {', '.join(f'{k}: {v:.3f}' for k, v in ps['slopes'].items())}; mean {ps['mean']:.4f} +- {ps['se']:.4f} "
              f"(t from -1: {ps['t_from_minus_one']:.2f}, dof {ps['dof']}, p={ps['p_two_sided_from_minus_one']:.3f}; 95% half-width {ps['ci95_halfwidth']:.4f})")
        tw = alt["two_way_ols_with_seed_effects"]
        print(f"two-way OLS with seed effects: slope {tw['slope']:.4f} +- {tw['slope_se']:.4f} (dof {tw['dof']}, p from -1 {tw['p_two_sided_from_minus_one']:.3f})")
        print(f"OLS on seed means: {alt['ols_on_seed_means']['slope']:.4f} +- {alt['ols_on_seed_means']['slope_se']:.4f}; "
              f"WLS on medians: {alt['wls_on_seed_medians']['slope']:.4f} +- {alt['wls_on_seed_medians']['slope_se_unscaled']:.4f}")
        print(f"leave-one-seed-out weighted slopes: {alt['leave_one_seed_out_weighted_slope']}")
        ba = alt["wls_all_runs_block_se"]
        print(f"WLS over all runs with block SEs: slope {ba['slope']:.4f} +- {ba['slope_se_unscaled']:.4f}, chi2/dof {ba['chi2_dof']:.2f}")
        print("overdispersion (seed SD / block SE): " + ", ".join(f"{k}: {v['ratio_seed_sd_over_block_se']:.2f}" for k, v in alt["overdispersion"].items()))
        fs = alt["floor_share_linear_fit"]
        print(f"floor-share fit: measured beta/alpha = {fs['beta_over_alpha_e']:.1f} +- {fs['beta_over_alpha_se_e']:.1f} e- (chi2/dof {fs['chi2_dof']:.2f}; medians {fs['medians_beta_over_alpha_e']:.1f}; "
              f"without faintest {fs.get('without_faintest_beta_over_alpha_e', float('nan')):.1f} +- {fs.get('without_faintest_beta_over_alpha_se_e', float('nan')):.1f}, chi2/dof {fs.get('without_faintest_chi2_dof', float('nan')):.2f}); "
              f"model b/a = {fs['model_b_over_a_e']:.1f} e-; model floor share: " + ", ".join(f"{k}: {100*v:.1f}%" for k, v in fs["model_floor_share_per_magnitude"].items()))
        if "invalid_row_frames" in alt:
            irf = alt["invalid_row_frames"]["per_magnitude_mean_per_run"]
            print("invalid row-frames per run (noise-on / twin / mean |arm difference|): " + ", ".join(f"{k}: {v['noise_on']:.1f} / {v['operating_expectation']:.1f} / {v['arm_difference_mean_abs']:.1f}" for k, v in irf.items()))
        if "gate_free_subset" in alt:
            gf = alt["gate_free_subset"]
            print(f"gate-free subset {gf['magnitudes']}: weighted slope {gf['weighted_slope']:.4f} +- {gf['weighted_slope_se_unscaled']:.4f} (scaled {gf['weighted_slope_se_scaled']:.4f}, chi2/dof {gf['chi2_dof']:.2f}); "
                  f"model {gf['model_slope']:.4f}; power {gf['power_of_model_variance']:.3f} +- {gf['power_of_model_variance_se_unscaled']:.3f}; per-seed slopes {gf['per_seed_slopes_mean']:.4f} +- {gf['per_seed_slopes_se']:.4f}")
        ex = alt["per_seed_paired_slopes_without_excursion_seed"]
        print(f"per-seed paired slopes without seed {ex['excluded_seed']} ({ex['reason']}): {ex['mean']:.4f} +- {ex['se']:.4f} (dof {ex['dof']})")
        if "ratio_vs_twin_residual_gate_free" in alt:
            rv = alt["ratio_vs_twin_residual_gate_free"]
            print(f"ratio vs twin residual (gate-free runs, n={rv['n_runs']}): r = {rv['pearson_r']:.2f}, slope {100*rv['ols_slope_per_nm']:.3f} +- {100*rv['ols_slope_se_per_nm']:.3f} % per nm over {rv['twin_residual_range_nm'][0]:.0f}-{rv['twin_residual_range_nm'][1]:.0f} nm")
        print("cross term (msd - dV): " + "; ".join(f"{k}: {v['mean_nm2']:+.0f} +- {v['seed_se_nm2']:.0f} nm2 ({v['relative_to_dv_percent']:+.1f} % of dV; weighted z {v['z_weighted']:+.2f})" for k, v in alt["difference_of_variances_cross_term"].items()))
        if "gate_divergence_correlation" in alt:
            g = alt["gate_divergence_correlation"]
            print(f"gate divergence: {g['n_runs_with_invalid_rows']} runs with invalid rows; r(|arm valid diff|, dV excess) = {g['pearson_r_absdiff_vs_dv_excess']:.2f} (Spearman {g['spearman_r']:.2f})")
        print(f"seed-paired bootstrap of the unweighted OLS slope: point {boot['point_estimate']:.4f}, bootstrap mean {boot['bootstrap_mean']:.4f}, SD {boot['bootstrap_sd']:.4f} "
              f"[{boot['bootstrap_percentile_2.5']:.3f}, {boot['bootstrap_percentile_97.5']:.3f}] ({boot['resamples']} resamples)")
        rep = analysis[key]["reproduction_quoted_vs_recomputed"]
        worst_key = max(rep, key=lambda k: abs(rep[k]["difference"]) / max(abs(rep[k]["quoted"]), 1e-9))
        print(f"reproduction: {len(rep)} quoted numbers recomputed; largest relative difference {100*abs(rep[worst_key]['difference'])/max(abs(rep[worst_key]['quoted']),1e-9):.2f} % ({worst_key}: quoted {rep[worst_key]['quoted']}, recomputed {rep[worst_key]['recomputed']:.4g})")

    # Historical attempt 1 (difference of mean squares): kept separate.
    att = results["records"]["2m_attempt1"]["runs"]
    att_stats: dict[str, Any] = {}
    for lab in sorted({r["label"] for r in att}, key=lambda s: float(s[1:])):
        group = [r for r in att if r["label"] == lab]
        vals = np.array([r["dv_nm2"] for r in group])
        att_stats[lab] = {
            "estimand": group[0]["estimand"],
            "values_nm2": [float(v) for v in vals],
            "min_nm2": float(vals.min()),
            "max_nm2": float(vals.max()),
            "mean_nm2": float(vals.mean()),
            "n_negative": int(np.sum(vals < 0)),
            "valid_on_mean": float(np.mean([r["valid_on"] for r in group])),
            "usable_on_mean": float(np.mean([r["usable_on"] for r in group])),
        }
    analysis["2m_attempt1"] = {"per_magnitude": att_stats, "note": "historical difference-of-mean-squares estimand at m_AB 7-9; m_AB 10 failed at calibration; superseded, kept as history"}
    print()
    print("2m attempt 1 (difference of mean squares, historical): " + "; ".join(f"{k}: {v['min_nm2']:.0f}..{v['max_nm2']:.0f} nm2, {v['n_negative']} negative, valid {v['valid_on_mean']:.3f}" for k, v in att_stats.items()))

    # Cross-record consistency: the 2 m attempt-1 arms at m7/m8 equal the
    # final record's arms where the configuration is the same.
    final_rows = {(r["label"], r["seed"]): r for r in results["records"]["2m"]["runs"]}
    same = []
    for r in att:
        f = final_rows.get((r["label"], r["seed"]))
        if f is not None:
            same.append({"label": r["label"], "seed": r["seed"], "same_config_hash": f["config_hash"] == r["config_hash"], "same_rms_on": f["rms_on_nm"] == r["rms_on_nm"], "same_rms_off": f["rms_off_nm"] == r["rms_off_nm"], "attempt1_msd_equals_final_msd": math.isclose(r["dv_nm2"], f["msd_nm2"], rel_tol=1e-9)})
    analysis["2m_attempt1"]["overlap_with_final_record"] = same
    print(f"attempt-1 overlap with the final 2 m record: {sum(s['same_config_hash'] for s in same)}/{len(same)} same config hash, "
          f"{sum(s['same_rms_on'] for s in same)}/{len(same)} same noise-on RMS, {sum(s['attempt1_msd_equals_final_msd'] for s in same)}/{len(same)} attempt-1 value equals the final record's mean-square difference")

    results["analysis"] = analysis

    if not args.skip_synthetic:
        print()
        print("synthetic examples (not AO simulations) ...")
        results["synthetic_examples"] = synthetic_examples()
        b = results["synthetic_examples"]["block_se_vs_correlation_time"]
        for k, v in b.items():
            print(f"  block SE / true SE for {k} (tau_int {v['tau_int']:.1f}, {v['frames']} frames): " + ", ".join(f"block {kk}: {vv:.2f}" for kk, vv in v["block_se_mean_over_true"].items()))
        d = results["synthetic_examples"]["difference_of_variances_vs_paired"]
        for k, v in d.items():
            print(f"  {k}: paired {v['paired_mean']:.2f} +- {v['paired_sd']:.2f}; difference of variances {v['difference_of_variances_mean']:.2f} +- {v['difference_of_variances_sd']:.2f} (true {v['true_noise_variance']:.2f})")
        sb = results["synthetic_examples"]["spot_broadening_second_moment"]
        print(f"  spot second moment (toy square subaperture, Nyquist, 15 px window): flat {sb['flat_second_moment_px2_x_plus_y']:.2f} px2 (capture {sb['flat_window_capture']:.3f}); "
              + ", ".join(f"{k.split('_')[3]} rad2: x{v['second_moment_ratio_mean']:.2f} +- {v['second_moment_ratio_sd']:.2f} (capture {v['window_capture_mean']:.2f})" for k, v in sb.items() if k.startswith("tilt_removed")))
        e = results["synthetic_examples"]["single_run_excursion"]
        print(f"  excursion example: clean slope {e['unweighted_slope_clean_mean']:.3f}; with excursion {e['unweighted_slope_with_excursion_mean']:.3f}; median-based {e['median_based_slope_with_excursion_mean']:.3f}")

    if args.with_package:
        print()
        print("package checks (import only) ...")
        results["package_checks"] = package_checks(repo, records)
        pc = results["package_checks"]
        if pc.get("available"):
            for key in RECORDS:
                entry = pc[key]
                print(f"  {key}: config hashes match current code for {entry['config_hash_matches']}/{entry['runs']} runs; mismatches {entry['config_hash_mismatches']}")
            li = pc["12m_v3"].get("lenslet_illumination", {})
            if "n_lenslets" in li:
                print(f"  12 m lenslets: {li['n_lenslets']}, fully illuminated {li['fully_illuminated']}, min fraction {li['fraction_min']:.3f}, "
                      f"mean(1/f) {li['mean_inverse_fraction']:.3f}, mean(1/f^2) {li['mean_inverse_fraction_squared']:.3f}")
        else:
            print(f"  package not importable: {pc.get('reason')}")

    results["wall_s"] = time.time() - started
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=1, sort_keys=False, default=float) + "\n")
    print()
    print(f"wrote {args.output} ({results['wall_s']:.1f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
