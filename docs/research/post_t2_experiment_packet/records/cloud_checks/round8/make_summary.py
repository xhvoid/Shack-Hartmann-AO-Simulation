"""Print the round-8 result tables from the v9 records (and the round-7 tool's records of the fixtures for comparison)."""
import glob
import json
import os

S = "/tmp/claude-0/-home-user-Shack-Hartmann-AO-Simulation/f1f3bff0-5382-5b19-9652-6c00a445942e/scratchpad/round8"


def load(path):
    with open(path) as handle:
        return json.load(handle)


def pct(value):
    return "n/a" if value is None else f"{value * 100:+.3f} %"


def sci(value):
    return "n/a" if value is None else f"{value:.2e}"


def num(value, fmt="{:.4f}"):
    return "n/a" if value is None else fmt.format(value)


def describe(name, record):
    bounds = record["prediction"]["operator_bounds"]
    error = bounds.get("operator_error", {})
    comparison = record.get("comparison", {})
    unconditional = bounds.get("time_varying", {})
    reconstruction = bounds.get("reconstruction", {})
    margin = record["noise_covariance"]["bracket"].get("margin_calibration", {})
    sampling = error.get("admissible_sampling")
    carried = error.get("carried_window_over_prediction") or {}
    actual = error.get("conditional_prediction_actual_operators_m2") or {}
    measured_over_actual = None
    if actual and comparison.get("measured_over_conditional_prediction") is not None and error.get("conditional_prediction_modal_m2"):
        measured = comparison["measured_over_conditional_prediction"] * error["conditional_prediction_modal_m2"]
        measured_over_actual = [measured / actual["at_admissible_max"], measured / actual["at_admissible_min"]]
    print(f"{name}: {record['schema']}; class {bounds['classification']}; operator error {pct(error.get('value'))} (extremes {pct((error.get('extremes') or {}).get('min'))} .. {pct((error.get('extremes') or {}).get('max'))}, width {pct(error.get('width_over_prediction'))}); "
          f"carried/prediction modal {pct(carried.get('modal'))} actual {pct(carried.get('actual_operators'))}; arm forcing {error.get('arm_operator_forcing')}; adjoint vs forward {sci(error.get('adjoint_vs_forward_relative'))}; admissible lenslets {(error.get('admissible') or {}).get('lenslets')}; "
          f"reconstruction r {sci(reconstruction.get('relative_rms_vs_measured_series'))}; source {bounds.get('carried_state_source')}; measured/conditional {num(comparison.get('measured_over_conditional_prediction'))}; measured/actual-operator prediction {[num(v) for v in measured_over_actual] if measured_over_actual else 'n/a'}; "
          f"budget {pct(bounds['systematic'].get('total'))}; unconditional (round-6 quantity) window component {pct(unconditional.get('window_operator_component'))}; margin upper max {num(margin.get('ratio_upper_97_5_max'), '{:.3f}')}; peak {record['ru_maxrss_bytes'] / 2**20:.0f} MiB; reasons {[r[:110] for r in bounds['reasons']]}")
    if sampling:
        print(f"   sampling: {json.dumps({k: sampling[k] for k in ('samples', 'outside_exact_extremes', 'operator_error_sampled_range', 'round6_window_component_sampled_range', 'round6_window_component_at_its_bracket_ends', 'round6_samples_beyond_its_ends')})}")


print("## self-test")
selftest = load(f"{S}/model_self_test.json")
print({"schema": selftest.get("schema"), "passed": selftest.get("passed")}, json.dumps(selftest["operator_error_on_the_conditional_prediction"]))
print("\n## pilot sidecars (round-2, no maps)")
for directory in ("ni2m_m5s61", "ci_m7_default", "ci_m7_alpha0p1", "ci_m9_default", "ci_m9_alpha0p1"):
    path = f"{S}/{directory}/model_sidecar.json"
    describe(directory, load(path)) if os.path.exists(path) else print(directory, "missing")
print("\n## ci pilots with retained maps (round-6 pilots)")
for directory in ("ci_m7_alpha0p1", "ci_m7_default", "ci_m9_alpha0p1"):
    path = f"{S}/pilots_maps/{directory}/model_sidecar.json"
    describe(directory + " (maps)", load(path)) if os.path.exists(path) else print(directory, "missing")
print("\n## 32 series sidecars")
rows = []
for path in sorted(glob.glob(f"{S}/ni2m_models/*.json")):
    if path.endswith("summary.json"):
        continue
    record = load(path)
    covariance = record["noise_covariance"]
    prediction = record["prediction"]
    entry = {"label": covariance["label"], "seed": covariance["root_seed"], "defined": prediction.get("primary_status") == "defined", "validated": covariance.get("sidecar_validation", {}).get("record", {}).get("runner_validate_trace_payload") == "passed", "saturation": covariance["noisy_arm_saturation_fraction_mean"], "gate_quiet": covariance["gate_quiet_by_core_rule"]}
    if entry["defined"]:
        bounds = prediction["operator_bounds"]
        error = bounds["operator_error"]
        entry.update(classification=bounds["classification"], operator_error=error.get("value"), operator_error_status=error.get("status"), reconstruction_rms=bounds["reconstruction"].get("relative_rms_vs_measured_series"), source=bounds.get("carried_state_source"), unconditional_window_component=bounds["time_varying"].get("window_operator_component"), admissible_lenslets=covariance["bracket"].get("lenslets_admissible"), sparse=covariance["bracket"].get("lenslets_sparse"), width=error.get("width_over_prediction"), budget=bounds["systematic"].get("total"), reasons=bounds["reasons"])
    else:
        entry.update(classification="primary not defined", reason=prediction.get("reason"))
    rows.append(entry)
for label in ("m5", "m6", "m7", "m8"):
    selected = [row for row in rows if row["label"] == label]
    classes = {key: sum(1 for row in selected if row["classification"] == key) for key in sorted({row["classification"] for row in selected})}
    computed = [row for row in selected if row.get("operator_error") is not None]
    print(f"{label}: n={len(selected)} validated {sum(row['validated'] for row in selected)} classes {classes}; operator error computed on {len(computed)} (map seeds) {[(row['seed'], pct(row['operator_error']), pct(row['width'])) for row in computed]}; admissible lenslets per run {sorted({len(row.get('admissible_lenslets') or []) for row in selected})}; unconditional window component {pct(min((row['unconditional_window_component'] for row in selected if row.get('unconditional_window_component') is not None), default=None))}..{pct(max((row['unconditional_window_component'] for row in selected if row.get('unconditional_window_component') is not None), default=None))}")
json.dump({"rows": rows}, open(f"{S}/ni2m_models/summary.json", "w"), indent=1, default=str)
print("\n## fixtures")
for variant in ("operator-change", "operator-change-quiet", "sparse-lenslets", "per-axis"):
    summary_path = f"{S}/fixtures/{variant}.summary.json"
    if os.path.exists(summary_path):
        built = load(summary_path)
        print(f"{variant} built: {json.dumps({k: built[k] for k in ('lenslets_dropped_by_both_arms', 'frames_dropped', 'noisy_only_dropped', 'noise_scale', 'kick', 'kick_share_of_window_mean', 'mask_disagreement_frames')})}")
    for version in ("v9", "v8"):
        path = f"{S}/fixtures/{variant}__model_{version}.json"
        if os.path.exists(path):
            describe(f"{variant} [{version}]", load(path))
for name in ("carried__model_v9", "carried__model_v8", "series_scaled_model", "bracket_model"):
    path = f"{S}/fixtures/{name}.json"
    if os.path.exists(path):
        describe(name, load(path))
print("\n## negative checks")
for name in ("wrong_units", "wrong_axes", "wrong_dtype"):
    path = f"{S}/negative/{name}.stdout"
    if os.path.exists(path):
        with open(path) as handle:
            lines = handle.read().strip().splitlines()
        print(name, "->", lines[-1][:150] if lines else "(no output)", "| json written:", os.path.exists(f"{S}/negative/{name}.json"))
