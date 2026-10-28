"""The NumPy-only trace analysis (S4 contract, ticket T1) on synthetic cases with known answers.

The script is loaded by file.  Every synthetic case states the relationship
it plants and the uncertainty appropriate to its length; the Student t
quantiles are checked against a published table and, when SciPy is
importable, against ``scipy.stats``.
"""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np
import pytest

from _trace_fixtures import fake_traced_run


ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("analyze_noise_isolation_traces_for_tests", ROOT / "scripts/analyze_noise_isolation_traces.py")
assert _SPEC is not None and _SPEC.loader is not None
analysis = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = analysis
_SPEC.loader.exec_module(analysis)

_RUNNER_SPEC = importlib.util.spec_from_file_location("run_detector_level_evidence_for_analysis_tests", ROOT / "scripts/run_detector_level_evidence.py")
assert _RUNNER_SPEC is not None and _RUNNER_SPEC.loader is not None
runner = importlib.util.module_from_spec(_RUNNER_SPEC)
sys.modules[_RUNNER_SPEC.name] = runner
_RUNNER_SPEC.loader.exec_module(runner)


# Two-sided 95 % (p = 0.975), 99 % (0.995) and one-sided 95 % (0.95) Student t
# quantiles from standard tables (Abramowitz & Stegun table 26.10 values at
# nine or ten significant digits as reproduced by common references).
T_TABLE = {
    (0.975, 1): 12.706204736, (0.975, 2): 4.302652730, (0.975, 3): 3.182446305, (0.975, 4): 2.776445105,
    (0.975, 5): 2.570581836, (0.975, 7): 2.364624252, (0.975, 9): 2.262157163, (0.975, 10): 2.228138852,
    (0.975, 30): 2.042272456, (0.995, 7): 3.499483297, (0.95, 7): 1.894578605, (0.95, 4): 2.131846786,
}


def test_student_t_quantiles_match_a_table_and_scipy_without_a_normal_substitute():
    for (p, dof), expected in T_TABLE.items():
        assert abs(analysis.student_t_quantile(p, dof) - expected) < 5.0e-9, (p, dof)
    # Eight seeds: seven degrees of freedom, not the normal 1.96.
    assert analysis.student_t_quantile(0.975, 7) > 2.3
    assert analysis.student_t_quantile(0.025, 7) == -analysis.student_t_quantile(0.975, 7)
    scipy_stats = pytest.importorskip("scipy.stats")
    for (p, dof) in T_TABLE:
        assert abs(analysis.student_t_quantile(p, dof) - scipy_stats.t.ppf(p, dof)) < 1.0e-9
    interval = analysis.t_interval(np.array([1.0, 2.0, 3.0, 4.0]), 0.95)
    assert interval["dof"] == 3 and interval["mean"] == 2.5
    assert interval["half_width"] == pytest.approx(analysis.student_t_quantile(0.975, 3) * np.std([1, 2, 3, 4], ddof=1) / 2.0)
    degenerate = analysis.t_interval(np.array([2.0, 2.0, 2.0]), 0.95)
    assert degenerate["status"] == "degenerate: zero scatter" and degenerate["half_width"] == 0.0
    assert analysis.t_interval(np.array([1.0]), 0.95)["status"] == "one unit: no interval"


def _ar1(n: int, phi: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(n + 1000)
    series = np.empty(n + 1000)
    series[0] = noise[0]
    for index in range(1, n + 1000):
        series[index] = phi * series[index - 1] + noise[index]
    return series[1000:]


def test_white_noise_has_a_plateau_at_one_frame_and_unit_correlation_time():
    rng = np.random.default_rng(3)
    series = rng.standard_normal(4000)
    table = analysis.block_table(series, (1, 5, 10, 25, 50, 75))
    naive = float(np.std(series, ddof=1) / math.sqrt(series.size))
    for row in table["blocks"]:
        assert row["se"] == pytest.approx(naive, rel=0.35)  # block errors scatter by 1/sqrt(2(k-1))
    assert table["plateau"]["identified"] and table["plateau"]["block_frames"] == 1
    tau = analysis.autocorrelation_time(series)
    assert tau["status"] == "ok" and abs(tau["tau"] - 1.0) < 0.15


def test_an_ar1_series_reports_its_known_correlation_time_within_its_own_uncertainty():
    # AR(1) with phi = 0.8: integrated autocorrelation time (1 + phi) / (1 - phi) = 9.
    phi, expected_tau = 0.8, 9.0
    series = _ar1(20_000, phi, seed=11)
    tau = analysis.autocorrelation_time(series)
    assert tau["status"] == "ok"
    assert abs(tau["tau"] - expected_tau) < 4.0 * tau["tau_se"] + 0.5, tau
    table = analysis.block_table(series, (1, 5, 10, 25, 50, 75, 150, 300))
    plateau = table["plateau"]
    assert plateau["identified"]
    # At the plateau the block error approaches sd * sqrt(tau / n).
    expected_se = float(np.std(series, ddof=1) * math.sqrt(expected_tau / series.size))
    assert plateau["se"] == pytest.approx(expected_se, rel=0.35)
    # The naive one-frame error is far too small for a correlated series.
    assert table["blocks"][0]["se"] < 0.5 * expected_se


def test_a_short_correlated_series_says_it_cannot_identify_plateau_or_correlation_time():
    series = _ar1(60, 0.9, seed=5)  # tau = 19 against 60 frames
    table = analysis.block_table(series, (1, 5, 10, 25, 50, 75))
    assert not table["plateau"]["identified"]
    assert "lower bound" in table["plateau"]["meaning"] or "too short" in table["plateau"]["meaning"]
    tau = analysis.autocorrelation_time(series)
    assert tau["status"] != "ok"
    tiny = analysis.autocorrelation_time(np.arange(5.0))
    assert tiny["tau"] is None and "too short" in tiny["status"]
    constant = analysis.autocorrelation_time(np.ones(100))
    assert constant["tau"] is None and "zero variance" in constant["status"]
    short_blocks = analysis.block_table(np.arange(3.0), (1, 5, 25))
    assert short_blocks["blocks"][1]["se"] is None and "not estimable" in short_blocks["blocks"][1]["status"]


def test_a_planted_excursion_is_flagged_described_and_not_deleted():
    rng = np.random.default_rng(8)
    series = 1.0 + 0.05 * rng.standard_normal(150)
    series[75:100] *= 5.0  # the fourth 25-frame block
    flag = analysis.excursion(series)
    assert flag["flagged"] and flag["flagged_blocks"] == [3] and flag["flagged_frame_ranges"] == [[75, 99]]
    assert flag["max_block_over_median"] > 4.0 and 0.9 < flag["excess_fraction_in_flagged_blocks"] <= 1.0
    quiet = analysis.excursion(1.0 + 0.05 * rng.standard_normal(150))
    assert not quiet["flagged"] and quiet["flagged_blocks"] == []
    assert not analysis.excursion(np.ones(10))["flagged"]  # shorter than one block: undefined, said so
    assert analysis.excursion(np.zeros(50))["status"].startswith("non-positive median")


def test_e0_keeps_mean_variance_and_second_moment_apart_and_averages_sigma_squared():
    n_steps, burn_in, lenslets = 400, 100, 4
    rng = np.random.default_rng(21)
    sigma = np.full((n_steps, lenslets, 2), 0.05)
    sigma[:, 0, :] = np.where((np.arange(n_steps) % 2 == 0)[:, None], 0.02, 0.08)  # alternating sigma: mean(sigma^2) != mean(sigma)^2
    planted_mean = 0.03
    centroids = 7.0 + planted_mean + sigma * rng.standard_normal(sigma.shape)
    arrays = {
        "analysed_frame_index": np.arange(burn_in, n_steps),
        "noise_on__telemetry__centroids_xy_px": centroids,
        "noise_on__telemetry__expected_centroids_xy_px": np.full((n_steps, lenslets, 2), 7.0),
        "noise_on__telemetry__centroid_sigma_xy_px": sigma,
        "noise_on__telemetry__valid_subapertures": np.ones((n_steps, lenslets), dtype=bool),
        "noise_on__telemetry__uncertainty_supported": np.ones((n_steps, lenslets), dtype=bool),
        "noise_on__telemetry__total_snr": np.full((n_steps, lenslets), 40.0),
        "noise_on__telemetry__clipping_fraction": np.zeros((n_steps, lenslets)),
        "operating_expectation__telemetry__centroid_sigma_xy_px": sigma,
        "propagation_weights__weights_m2_per_px2": np.array([1.0, 1.0, 2.0, 2.0, 3.0, 3.0, 4.0, 4.0]) * 1.0e-16,
    }
    metadata = {"noisy_arm": "noise_on", "twin_arm": "operating_expectation"}
    state = analysis.operating_state(arrays, metadata, arrays["analysed_frame_index"])
    assert state["available"] and state["support_lenslets"] == lenslets
    equal = state["equal_weight"]
    # The planted mean appears in the mean residual and separates the second
    # moment from the centred variance by about mean^2 per axis.
    assert equal["mean_residual_px"][0] == pytest.approx(planted_mean, abs=0.004)
    assert equal["realized_second_moment_px2"] - equal["realized_variance_px2"] == pytest.approx(2 * planted_mean**2, rel=0.2)
    # Model averaging is mean(sigma^2): for the alternating lenslet that is
    # (0.02^2 + 0.08^2) / 2 = 0.0034 per axis, not ((0.02 + 0.08) / 2)^2 = 0.0025.
    expected_model = (3 * 2 * 0.05**2 + 2 * 0.0034) / 4
    assert equal["model_variance_px2"] == pytest.approx(expected_model, rel=1.0e-9)
    assert equal["ratio_variance_over_model"] == pytest.approx(1.0, abs=0.12)
    weighted = state["propagation_weighted"]
    assert weighted["weight_total_m2_per_px2"] == pytest.approx(20.0e-16)
    assert weighted["propagated_model_variance_m2"] == pytest.approx(1.0e-16 * (2 * 0.0034 * 1 + 2 * 0.05**2 * (2 + 3 + 4)), rel=1.0e-9)
    assert state["first_order_bias_estimate"] == pytest.approx(4.0 / 40.0**2)
    # A lenslet invalid in one frame leaves the support; an unavailable field makes E0 unavailable.
    arrays["noise_on__telemetry__valid_subapertures"][200, 1] = False
    assert analysis.operating_state(arrays, metadata, arrays["analysed_frame_index"])["support_lenslets"] == lenslets - 1
    del arrays["noise_on__telemetry__expected_centroids_xy_px"]
    assert analysis.operating_state(arrays, metadata, arrays["analysed_frame_index"])["available"] is False


def test_per_seed_slopes_pair_magnitudes_within_a_seed_and_exclude_nonpositive_values():
    seeds = [1, 2, 3]
    labels = ["m5", "m6", "m7"]
    flux = {"m5": 13000.0, "m6": 5180.0, "m7": 2060.0}
    # Every seed follows DeltaV = A_seed / N_e exactly: slopes are -1 whatever A_seed is.
    table = {label: {seed: (1.0 + 0.5 * seed) * 1.0e-14 / flux[label] for seed in seeds} for label in labels}
    abscissa = {label: {seed: flux[label] for seed in seeds} for label in labels}
    fit = analysis.per_seed_slopes(table, abscissa, seeds, labels, 0.95)
    assert [round(item["slope"], 9) for item in fit["per_seed"]] == [-1.0, -1.0, -1.0]
    assert fit["seed_mean"]["sd"] < 1.0e-9  # scatter at rounding level only
    # Unequal per-seed slopes: the interval is the t interval over the three units.
    table["m7"][3] *= 1.3
    fit = analysis.per_seed_slopes(table, abscissa, seeds, labels, 0.95)
    slopes = np.array([item["slope"] for item in fit["per_seed"]])
    assert fit["seed_mean"]["mean"] == pytest.approx(float(np.mean(slopes)))
    assert fit["seed_mean"]["half_width"] == pytest.approx(analysis.student_t_quantile(0.975, 2) * np.std(slopes, ddof=1) / math.sqrt(3))
    # A non-positive value cannot enter a log fit: it is counted, the seed keeps its other points.
    table["m6"][2] = -1.0e-18
    fit = analysis.per_seed_slopes(table, abscissa, seeds, labels, 0.95)
    assert fit["excluded"] == [{"seed": 2, "label": "m6", "reason": "non-positive value cannot enter a log fit"}]
    assert next(item for item in fit["per_seed"] if item["seed"] == 2)["points"] == 2


def test_the_weighted_fit_and_the_bootstrap_recover_a_planted_line():
    x = np.log(np.array([13000.0, 5180.0, 2060.0, 820.0]))
    y = -1.03 * x + 2.0
    se = np.array([0.02, 0.03, 0.02, 0.1])
    fit = analysis.weighted_fit(x, y, se)
    assert fit["slope"] == pytest.approx(-1.03) and fit["chi2"] == pytest.approx(0.0, abs=1.0e-18)
    assert fit["slope_se_scaled"] == pytest.approx(0.0, abs=1.0e-9) and fit["slope_se_unscaled"] > 0.0
    perturbed = y + np.array([0.02, -0.03, 0.02, -0.1])
    noisy = analysis.weighted_fit(x, perturbed, se)
    # An independent weighted least squares by the normal equations.
    weights = 1.0 / se**2
    design = np.stack([x, np.ones_like(x)], axis=1)
    normal = design.T @ (weights[:, None] * design)
    coefficients = np.linalg.solve(normal, design.T @ (weights * perturbed))
    chi2 = float(np.sum(weights * (perturbed - design @ coefficients) ** 2))
    assert noisy["slope"] == pytest.approx(coefficients[0], rel=1.0e-9)
    assert noisy["chi2"] == pytest.approx(chi2, rel=1.0e-9) and noisy["dof"] == 2
    assert noisy["slope_se_unscaled"] == pytest.approx(math.sqrt(np.linalg.inv(normal)[0, 0]), rel=1.0e-9)
    assert noisy["slope_se_scaled"] == pytest.approx(noisy["slope_se_unscaled"] * math.sqrt(chi2 / 2.0), rel=1.0e-9)
    seeds = [1, 2, 3, 4, 5]
    flux = {"m5": 13000.0, "m6": 5180.0, "m7": 2060.0}
    rng = np.random.default_rng(4)
    means = {label: {seed: 1.0e-14 / flux[label] * (1.0 + 0.05 * rng.standard_normal()) for seed in seeds} for label in flux}
    boot = analysis.bootstrap_slope(means, flux, seeds, list(flux), 300, 7)
    assert boot["resamples"] == 300 and boot["point_slope"] == pytest.approx(-1.0, abs=0.1)
    assert 0.0 < boot["bootstrap_sd"] < 0.2 and "not additional realizations" in boot["convention"]


def test_replay_comparison_names_the_first_differing_quantity(tmp_path: Path):
    def row(label: str, seed: int, **changes):
        base = {
            "label": label, "root_seed": seed, "config_hash": "c", "noise_variance_m2": 4.0e-18, "noise_variance_standard_error_m2": 5.0e-19,
            "mean_square_difference_m2": -7.0e-17, "mean_square_difference_standard_error_m2": 8.0e-17,
            "arms": {"noise_on": {"post_update_rms_m": 3.5e-7}, "operating_expectation": {"post_update_rms_m": 3.4e-7}},
            "predicted_centroid_variance_px2": 0.0017,
        }
        base.update(changes)
        return base

    current = {"runs": [row("m5", 61), row("m5", 62), row("m6", 61)]}
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"runs": [row("m5", 61), row("m5", 62, mean_square_difference_m2=-7.1e-17), row("m7", 61)], "code_identity": {"git_head": "x"}}))
    result = analysis.replay_comparison(current, other, name="test")
    assert result["runs_compared"] == 2 and result["runs_bit_identical"] == 1 and not result["all_bit_identical"]
    by_seed = {run["root_seed"]: run for run in result["runs"] if run["label"] == "m5"}
    assert by_seed[61]["bit_identical"] and by_seed[61]["first_differing_quantity"] is None
    assert by_seed[62]["first_differing_quantity"] == "mean_square_difference_m2"
    field = next(item for item in by_seed[62]["fields"] if not item["bit_identical"])
    assert field["relative_difference"] == pytest.approx((-7.0e-17 + 7.1e-17) / -7.1e-17)
    assert next(run for run in result["runs"] if run["label"] == "m6")["status"] == "absent in the other record"


def test_the_analysis_runs_end_to_end_on_a_synthetic_traced_record_with_known_power_law(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from shwfs_ao.experiments import detector_level
    from shwfs_ao.experiments.detector_level import with_magnitude
    from shwfs_ao.io.configs import load_system_profile

    flux = {"m5": 13000.0, "m6": 5180.0, "m7": 2060.0}

    def planted_run(config, *, root_seed, n_steps, burn_in_frames, execution, **keywords):
        magnitude = config.detector_physics.source.ab_magnitude
        label = f"m{magnitude:g}"
        result = fake_traced_run(config, root_seed=root_seed, n_steps=n_steps, burn_in_frames=burn_in_frames, execution=execution, delta_v_level=1.0e-14 / flux[label], **keywords)
        result["detected_e_full_subap"] = flux[label]
        return result

    monkeypatch.setattr(detector_level, "paired_noise_run_traced", planted_run)
    monkeypatch.setattr(runner, "EVIDENCE_DIR", tmp_path)
    monkeypatch.setattr(runner, "OPTIONS", runner.argparse.Namespace(output=None, overwrite=False, resume=False, enabled_by_user="test", output_dir=tmp_path))
    monkeypatch.setattr(runner, "_STARTED", set())
    monkeypatch.setattr(runner, "code_identity", lambda: {"package_sha256": "p", "script_sha256": "s", "git_head": "test", "source_changes_sha256": "test"})
    settings = {"profile": ("det_emccd_2m_synthetic", 1), "magnitudes": (5.0, 6.0, 7.0), "seeds": (1, 2, 3), "n_steps": 200, "burn_in": 50, "record": "synthetic.json", "map_seeds": {}}
    base = load_system_profile(*settings["profile"])
    plan = [(f"m{magnitude:g}", with_magnitude(base, magnitude), seed) for magnitude in settings["magnitudes"] for seed in settings["seeds"]]
    runner._gated_series(
        "synthetic.json", "test", plan, n_steps=200, burn_in=50, execution=None,
        runner=runner.traced_run_factory(settings, mode="traced"), run_context=True,
        validate_retained=runner.traced_record_validator(settings, mode="traced"), header_extra={"record_family": runner.TRACE_FAMILY},
    )
    historical = tmp_path / "historical.json"
    record = json.loads((tmp_path / "synthetic.json").read_text())
    altered = json.loads(json.dumps(record))
    altered["runs"][0]["noise_variance_m2"] *= 1.001  # one planted difference
    historical.write_text(json.dumps(altered))
    result = analysis.analyse(
        tmp_path / "synthetic.json", output_dir=tmp_path / "out", historical=historical, untraced=None,
        gate_quiet_labels=["m5", "m6"], lengths=(1, 5, 10, 25, 50, 75), bootstrap=100, bootstrap_seed=1, confidence=0.95,
    )
    assert (tmp_path / "out" / "analysis.json").is_file() and (tmp_path / "out" / "ANALYSIS_NOTE.md").is_file()
    assert result["record"]["runs_analysed"] == 9 and result["population"]["labels"] == ["m5", "m6", "m7"]
    assert result["population"]["domains"]["gate_quiet_predeclared"] == ["m5", "m6"]
    across = result["population"]["across_magnitudes"]["all"]
    # The planted law DeltaV ~ N_e^-1 with 10 % white frame scatter: the
    # historical weighted fit and the per-seed slopes recover -1 within their
    # own intervals (150 frames per run, three seeds).
    assert across["historical_weighted_fit_log_delta_v_vs_log_ne"]["slope"] == pytest.approx(-1.0, abs=0.05)
    seed_slopes = across["per_seed_slopes_log_delta_v_vs_log_ne"]["seed_mean"]
    assert abs(seed_slopes["mean"] + 1.0) <= max(seed_slopes["half_width"], 0.03)
    assert across["bootstrap_f06"]["resamples"] == 100
    # White frame noise: the plateau sits at one frame and every run is gate-quiet.
    for run in result["runs"]:
        assert run["delta_v"]["blocks"]["plateau"]["identified"] and run["masks"]["gate_quiet"]
        assert run["delta_v"]["frame_mean_equals_recorded"]
        assert run["operating_state"]["available"] and run["operating_state"]["equal_weight"]["ratio_variance_over_model"] == pytest.approx(1.0, abs=0.15)
    replay = result["replay"][0]
    assert replay["runs_compared"] == 9 and replay["runs_bit_identical"] == 8
    differing = next(run for run in replay["runs"] if not run["bit_identical"])
    assert differing["first_differing_quantity"] == "noise_variance_m2"
    note = (tmp_path / "out" / "ANALYSIS_NOTE.md").read_text()
    assert "no verdict is asserted" in note and "first differing quantity" in note
    # A corrupted sidecar refuses the analysis as a whole.
    sidecar = tmp_path / record["runs"][0]["sidecar"]["file"]
    data = sidecar.read_bytes()
    sidecar.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
    with pytest.raises(analysis.AnalysisError, match="not the recorded"):
        analysis.load_traced_record(tmp_path / "synthetic.json")


# -- Independent review of 2026-10-20 (T1-04, T1-05) --


def _population_rows(seeds: list[int], labels: list[str], flux: dict[str, float], template: dict) -> list[dict]:
    rows = []
    for label in labels:
        for seed in seeds:
            row = json.loads(json.dumps(template))
            row.update(label=label, root_seed=seed, detected_e_full_subap=flux[label])
            row["delta_v"]["mean_m2"] = 1.0 / flux[label]  # exactly representable inverse-flux law
            rows.append(row)
    return rows


def _run_template() -> dict:
    """A per-run analysis result with the fields population() reads, no physics."""

    return {
        "label": "m5", "root_seed": 1, "detected_e_full_subap": 8.0,
        "recorded": {"predicted_centroid_variance_px2": 0.002},
        "delta_v": {"mean_m2": 0.125, "blocks": {"plateau": {"identified": True, "se": 1.0e-19}, "blocks": [{"block_frames": 25, "se": 1.0e-19}]}, "autocorrelation": {"tau": 1.0, "status": "ok"}, "excursion": {"flagged": False}},
        "masks": {"gate_quiet": True, "disagreement_row_frame_fraction": 0.0, "rejected_frames_both_arms": 0},
        "saturation": {"noise_on": {"max": 0.0}},
        "cross_term": {"mean_over_se": 0.0},
        "operating_state": {"available": False},
    }


def test_zero_scatter_and_one_seed_populations_keep_their_paired_flux_slopes():
    """Independent review T1-04: the reviewer's fixture of eight identical inverse-flux seeds."""

    labels, flux = ["m5", "m6", "m7"], {"m5": 8.0, "m6": 4.0, "m7": 2.0}
    rows = _population_rows(list(range(1, 9)), labels, flux, _run_template())
    population = analysis.population(rows, confidence=0.95, gate_quiet_labels=labels, bootstrap=20, bootstrap_seed=1)
    across = population["across_magnitudes"]["all"]
    slopes = across["per_seed_slopes_log_delta_v_vs_log_ne"]
    assert [round(item["slope"], 9) for item in slopes["per_seed"]] == [-1.0] * 8
    assert slopes["seed_mean"]["n"] == 8 and slopes["seed_mean"]["status"] == "degenerate: zero scatter"
    assert across["usable_for_paired_slopes"] == labels and across["usable_for_weighted_fit"] == []
    assert across["excluded_from_weighted_fit_zero_or_unknown_error"] == labels
    assert across["excluded_nonpositive_or_unavailable"] == []
    assert "positive across-seed error" in across["historical_weighted_fit_log_delta_v_vs_log_ne"]["status"]
    assert across["bootstrap_f06"]["resamples"] == 20 and across["bootstrap_f06"]["point_slope"] == pytest.approx(-1.0)
    # One seed: the slope is computable, the inference says it has one unit.
    single = analysis.population(_population_rows([1], labels, flux, _run_template()), confidence=0.95, gate_quiet_labels=labels, bootstrap=20, bootstrap_seed=1)
    slopes = single["across_magnitudes"]["all"]["per_seed_slopes_log_delta_v_vs_log_ne"]
    assert len(slopes["per_seed"]) == 1 and slopes["per_seed"][0]["slope"] == pytest.approx(-1.0)
    assert slopes["seed_mean"]["status"] == "one unit: no interval"
    # A genuinely non-positive magnitude is still excluded from everything.
    rows[0]["delta_v"]["mean_m2"] = -1.0
    for row in rows:
        if row["label"] == "m5":
            row["delta_v"]["mean_m2"] = -1.0
    negative = analysis.population(rows, confidence=0.95, gate_quiet_labels=labels, bootstrap=20, bootstrap_seed=1)["across_magnitudes"]["all"]
    assert negative["excluded_nonpositive_or_unavailable"] == ["m5"] and negative["usable_for_paired_slopes"] == ["m6", "m7"]


def test_a_nonpositive_correlation_time_estimate_withholds_its_uncertainty():
    """Independent review T1-05: the reviewer's stationary anticorrelated AR(1), phi = -0.9, seed 427."""

    n, phi = 4096, -0.9
    rng = np.random.default_rng(427)
    innovations = rng.standard_normal(n + 1000)
    x = np.empty(n + 1000)
    x[0] = innovations[0] / math.sqrt(1 - phi * phi)
    for index in range(1, x.size):
        x[index] = phi * x[index - 1] + innovations[index]
    x = x[1000:]
    for series in (x, x - float(np.min(x)) + 1.0):  # the strictly positive shift changes nothing
        result = analysis.autocorrelation_time(series)
        assert result["tau"] is not None and result["tau"] < 1.0
        assert result["status"].startswith("unsupported")
        assert result["tau_se"] is None and result["se_of_mean"] is None and result["effective_samples"] is None
    # The exact asymptotic value is positive: (1 + phi) / (1 - phi) = 0.0526; the
    # window rule cannot estimate it, which the status says instead of a zero error.
    assert (1.0 + phi) / (1.0 - phi) == pytest.approx(0.05263, abs=1e-5)
    # A positively correlated series keeps its estimate and its uncertainty.
    positive = analysis.autocorrelation_time(_ar1(20_000, 0.8, seed=11))
    assert positive["status"] == "ok" and positive["tau_se"] > 0.0 and positive["se_of_mean"] > 0.0


# -- Independent review round 2 (2026-10-21, T1-02): the standalone loader enforces the same contract --


from _trace_fixtures import SIDECAR_MUTATIONS, mutate_sidecar  # noqa: E402


def test_the_analysis_schema_tables_equal_the_runners_and_the_row_rule_is_the_packages():
    assert analysis.CANONICAL_SERIES_ARRAYS == runner._SIDECAR_SHARED_ARRAYS
    assert analysis.CANONICAL_HISTORY_ARRAYS == runner._SIDECAR_HISTORY_ARRAYS
    assert analysis.CANONICAL_TELEMETRY_ARRAYS == runner._SIDECAR_TELEMETRY_ARRAYS
    assert analysis.CANONICAL_WEIGHT_ARRAYS == runner._SIDECAR_WEIGHT_ARRAYS
    assert analysis.CANONICAL_MAP_ARRAYS == runner._SIDECAR_MAP_ARRAYS
    assert analysis.CANONICAL_RESIDUAL_MAP_ARM == runner._SIDECAR_RESIDUAL_MAP_ARM
    assert analysis.CANONICAL_LOCK_ARRAYS == runner._SIDECAR_LOCK_ARRAYS
    from shwfs_ao.wfs.shack_hartmann.calibration import row_ids_for_subapertures

    ids = ("lenslet-r0001-c0000", "lenslet-r0002-c0000", "lenslet-r0000-c0003")
    assert analysis.canonical_row_ids(ids) == row_ids_for_subapertures(ids)


def _inert_traced_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, mode: str) -> tuple[Path, dict]:
    from shwfs_ao.experiments import detector_level
    from shwfs_ao.experiments.detector_level import with_magnitude
    from shwfs_ao.io.configs import load_system_profile

    def locked(config, *, root_seed, n_steps, burn_in_frames, execution, allow_partial_lock=False, **keywords):
        return fake_traced_run(config, root_seed=root_seed, n_steps=n_steps, burn_in_frames=burn_in_frames, execution=execution, allow_partial_lock=allow_partial_lock, **keywords)

    monkeypatch.setattr(detector_level, "paired_noise_run_traced", fake_traced_run)
    monkeypatch.setattr(detector_level, "paired_noise_run_mask_locked", locked)
    monkeypatch.setattr(runner, "EVIDENCE_DIR", tmp_path)
    monkeypatch.setattr(runner, "OPTIONS", runner.argparse.Namespace(output=None, overwrite=False, resume=False, enabled_by_user="test", output_dir=tmp_path))
    monkeypatch.setattr(runner, "_STARTED", set())
    monkeypatch.setattr(runner, "code_identity", lambda: {"package_sha256": "p", "script_sha256": "s", "git_head": "test", "source_changes_sha256": "test"})
    settings = {"profile": ("det_emccd_2m_synthetic", 1), "magnitudes": (7.0,), "seeds": (21,), "n_steps": 20, "burn_in": 5, "record": "probe.json", "map_seeds": {}}
    base = load_system_profile(*settings["profile"])
    plan = [("m7", with_magnitude(base, 7.0), 21)]
    runner._gated_series(
        "probe.json", "test", plan, n_steps=20, burn_in=5, execution=None,
        runner=runner.traced_run_factory(settings, mode=mode), run_context=True,
        validate_retained=runner.traced_record_validator(settings, mode=mode), header_extra={"record_family": runner.TRACE_FAMILY},
    )
    return tmp_path / "probe.json", json.loads((tmp_path / "probe.json").read_text())


@pytest.mark.parametrize("name", sorted(SIDECAR_MUTATIONS))
def test_the_standalone_loader_refuses_every_reviewed_mutation_before_any_reduction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str):
    mode, _, analysis_match = SIDECAR_MUTATIONS[name]
    path, record = _inert_traced_record(tmp_path, monkeypatch, mode=mode)
    row = record["runs"][0]
    sidecar = tmp_path / row["sidecar"]["file"]
    metadata, arrays = runner.read_sidecar(sidecar)
    # The untouched archive loads, and its E0 reduction is the reference.
    _, loaded = analysis.load_traced_record(path)
    reference = analysis.operating_state(loaded[0]["arrays"], loaded[0]["metadata"], loaded[0]["arrays"]["analysed_frame_index"])
    assert reference["available"]
    new_arrays, new_metadata = mutate_sidecar(name, arrays, metadata)
    sidecar.unlink()
    row["sidecar"] = runner.publish_sidecar(sidecar, new_arrays, new_metadata)
    path.write_text(json.dumps(record, indent=2) + "\n")
    with pytest.raises(analysis.AnalysisError, match=analysis_match):
        analysis.load_traced_record(path)
    with pytest.raises(analysis.AnalysisError):
        analysis.analyse(path, output_dir=tmp_path / "out", historical=None, untraced=None, gate_quiet_labels=None, lengths=(1, 5), bootstrap=10, bootstrap_seed=1, confidence=0.95)
    assert not (tmp_path / "out").exists()  # refused before any reduction or output
    if name == "centroid_one_axis":
        # The reviewer's broadcast effect: a lone x axis would have changed the
        # E0 ratio (0.92 to 1.24 on their fixture) instead of being refused.
        broadcast = analysis.operating_state(new_arrays, new_metadata, new_arrays["analysed_frame_index"])
        assert broadcast["available"] and broadcast["equal_weight"]["ratio_variance_over_model"] != reference["equal_weight"]["ratio_variance_over_model"]
