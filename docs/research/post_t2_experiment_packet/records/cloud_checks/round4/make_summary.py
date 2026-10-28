"""Print the round-4 result tables from the records (operator error bounds, carried-state bounds, classifications)."""
import glob, json, math, os, statistics as st
S = "/tmp/claude-0/-home-user-Shack-Hartmann-AO-Simulation/f1f3bff0-5382-5b19-9652-6c00a445942e/scratchpad/round4"
def load(p):
    with open(p) as h: return json.load(h)
def pct(x): return "n/a" if x is None else f"{x*100:+.2f} %"
print("## self-test"); t = load(f"{S}/model_self_test.json"); print({k: t[k] for k in ("passed",)}, t["operator_sequence_and_carried_state"])
print("\n## pilot sidecars")
for d in ("ni2m_m5s61", "ci_m7_default", "ci_m7_alpha0p1", "ci_m9_default", "ci_m9_alpha0p1"):
    f = f"{S}/{d}/model_sidecar.json"
    if not os.path.exists(f): print(d, "missing"); continue
    m = load(f); p = m["prediction"]; nc = m["noise_covariance"]; op = nc["operator"]; c = m.get("comparison", {}); by = p["by_noise_covariance_rule"]; b = p["operator_bounds"]; tv = b["time_varying"]; cs = b["carried_state"]; bi = b["burn_in"]
    print(f"{d}: rows {op['rows_in_modal_mask']}/{op['rows_total']}; distinct masks analysed {op['distinct_effective_masks_noisy_analysed']}, all frames {op['distinct_effective_masks_noisy_all_frames']}; match noisy {op['noisy_match_fraction']:.3f} twin {op['twin_match_fraction']:.3f} burn-in {op['burn_in_match_fraction_noisy']:.2f}; "
          f"operator error {pct(tv.get('relative_difference_vs_modal'))} (burn-in part {pct(tv.get('burn_in_carried_component'))}, window part {pct(tv.get('window_operator_component'))}, probe {tv.get('probe_s', 0):.1f} s); "
          f"burn-in: last unmodelled frame {bi['last_unmodelled_frame']} (disagreement frames {bi['frames_with_mask_disagreement']}, saturated frames {bi['frames_with_saturation']}, rejected {bi['rejected_frames']}); carried-state bound {pct(cs['inherited_fraction_from_last_unmodelled_frame'])}, inherited from first analysed frame {pct(cs['inherited_fraction'])}, stationary start/primary {cs['stationary_start_over_primary']}; "
          f"classification {b['classification']}; measured/window by rule " + ", ".join(f"{k}: {('n/a' if v is None else f'{v:.3f}')}" for k, v in c.get("measured_over_exact_window_by_rule", {}).items()) + f"; within 2 block SE {c.get('exact_window_within_2_block_se')}; validation arrays {nc['sidecar_validation']['arrays_checked']}, pilot_record {nc['sidecar_validation'].get('pilot_record',{}).get('digest_size_hash_frames_label_seed')}; unsensed modes {by['effective']['feedback_spectrum']['count_below_1e-6']}; stationary exists {by['effective']['stationarity']['stationary_limit_exists']}")
print("\n## 32 series sidecars")
rows = []
for f in sorted(glob.glob(f"{S}/ni2m_models/*.json")):
    if f.endswith("summary.json"): continue
    m = load(f); nc = m["noise_covariance"]; p = m["prediction"]; op = nc["operator"]; val = nc.get("sidecar_validation", {})
    entry = dict(label=nc["label"], seed=nc["root_seed"], noisy_match=op["noisy_match_fraction"], twin_match=op["twin_match_fraction"], distinct_all=op["distinct_effective_masks_noisy_all_frames"], validated=val.get("record", {}).get("runner_validate_trace_payload") == "passed", arrays=val.get("arrays_checked"), gate_quiet=nc["gate_quiet_by_core_rule"], defined=p.get("primary_status") == "defined", saturation=nc["noisy_arm_saturation_fraction_mean"], burn_in=nc["burn_in"])
    if entry["defined"]:
        c = m["comparison"]; b = p["operator_bounds"]; tv = b["time_varying"]; cs = b["carried_state"]
        entry.update(classification=b["classification"], consistent=b["operator_consistent"], operator_error=tv.get("relative_difference_vs_modal"), burn_in_part=tv.get("burn_in_carried_component"), tv_status=tv["status"], carried_bound=cs["inherited_fraction_from_last_unmodelled_frame"], inherited=cs["inherited_fraction"], last_unmodelled=b["burn_in"]["last_unmodelled_frame"], ratio=c["measured_over_exact_window"], by=c["measured_over_exact_window_by_rule"], within=c["exact_window_within_2_block_se"], radius=p["by_noise_covariance_rule"]["effective"]["stationarity"]["spectral_radius_F"], dev=p["by_noise_covariance_rule"]["effective"]["feedback_spectrum"]["max_abs_deviation_of_L_from_identity"])
    else:
        entry.update(reason=p.get("reason"), classification="primary not defined", consistent=False)
    rows.append(entry)
summary = {}
for lab in ("m5", "m6", "m7", "m8"):
    sel = [x for x in rows if x["label"] == lab]
    if not sel: continue
    defined = [x for x in sel if x["defined"]]; consistent = [x for x in defined if x["consistent"]]
    out = {"n": len(sel), "defined": len(defined), "operator_consistent": len(consistent), "classifications": sorted(set(x["classification"] for x in sel)), "validated": sum(x["validated"] for x in sel), "gate_quiet": sum(x["gate_quiet"] for x in sel), "saturation_excluded": sum(x["saturation"] > 1e-3 for x in sel)}
    for rule in ("effective", "available", "strict"):
        vals = [x["by"][rule] for x in defined if x["by"].get(rule) is not None]
        if len(vals) == 8:
            out[rule] = {"n": 8, "mean": st.mean(vals), "t_halfwidth_7dof": 2.365 * st.stdev(vals) / math.sqrt(8), "per_seed": [round(v, 3) for v in vals]}
        else:
            out[rule] = {"n": len(vals), "per_seed": [round(v, 3) for v in vals]}
    if defined:
        comp = [x for x in defined if x["tv_status"] == "computed"]
        out["operator_error_range"] = [min(x["operator_error"] for x in comp), max(x["operator_error"] for x in comp)] if comp else None
        out["operator_error_not_computed"] = len(defined) - len(comp)
        out["burn_in_part_max_abs"] = max(abs(x["burn_in_part"]) for x in comp) if comp else None
        out["carried_bound_range"] = [min(x["carried_bound"] for x in defined if x["carried_bound"] is not None), max(x["carried_bound"] for x in defined if x["carried_bound"] is not None)] if any(x["carried_bound"] is not None for x in defined) else None
        out["inherited_range"] = [min(x["inherited"] for x in defined), max(x["inherited"] for x in defined)]
        out["last_unmodelled"] = sorted(set(x["last_unmodelled"] for x in defined), key=lambda v: (v is None, v))
        out["distinct_all_range"] = [min(x["distinct_all"] for x in sel), max(x["distinct_all"] for x in sel)]
    out["noisy_match_range"] = [min(x["noisy_match"] for x in sel), max(x["noisy_match"] for x in sel)]
    out["twin_match_range"] = [min(x["twin_match"] for x in sel), max(x["twin_match"] for x in sel)]
    out["within_2se"] = sum(x.get("within", False) for x in defined)
    summary[lab] = out
    def fmt(rule):
        e = out[rule]; return f"{rule} n={e['n']} " + (f"{e['mean']:.4f} +/- {e['t_halfwidth_7dof']:.4f}" if e["n"] == 8 else f"{e['per_seed']}")
    print(f"{lab}: n={len(sel)} defined {len(defined)} operator-consistent {len(consistent)} classes {out['classifications']} validated {out['validated']} gate-quiet {out['gate_quiet']} saturation>1e-3 {out['saturation_excluded']}; {fmt('effective')}; {fmt('available')}; {fmt('strict')}; "
          + (f"operator error {pct(out['operator_error_range'][0])}..{pct(out['operator_error_range'][1])} (not computed {out['operator_error_not_computed']}; burn-in part max {pct(out['burn_in_part_max_abs'])}); carried bound {pct(out['carried_bound_range'][0]) if out['carried_bound_range'] else 'n/a'}..{pct(out['carried_bound_range'][1]) if out['carried_bound_range'] else 'n/a'}; inherited {pct(out['inherited_range'][0])}..{pct(out['inherited_range'][1])}; last unmodelled {out['last_unmodelled']}; distinct masks (all frames) {out['distinct_all_range']}; " if defined else "")
          + f"noisy match {out['noisy_match_range'][0]:.3f}-{out['noisy_match_range'][1]:.3f}, twin match {out['twin_match_range'][0]:.3f}-{out['twin_match_range'][1]:.3f}; within 2 block SE {out['within_2se']}/{len(defined)}")
defined_rows = [x for x in rows if x["defined"]]
if defined_rows:
    print(f"all: defined {len(defined_rows)}/{len(rows)}; max |L-I| (effective mask) {max(x['dev'] for x in defined_rows):.1e}; spectral radius {set(round(x['radius'],4) for x in defined_rows)}; arrays checked {set(x['arrays'] for x in rows)}")
for x in rows:
    if not x["defined"]: print("  not defined:", x["label"], x["seed"], (x["reason"] or "")[:160])
json.dump({"rows": rows, "per_magnitude": summary}, open(f"{S}/ni2m_models/summary.json", "w"), indent=1, default=str)
print("\n## negative checks")
for name in ("wrong_units", "wrong_axes", "wrong_dtype"):
    path = f"{S}/negative/{name}.stdout"
    if os.path.exists(path):
        with open(path) as h: lines = h.read().strip().splitlines()
        print(name, "->", (lines[-1][:230] if lines else "(no output)"), "| json written:", os.path.exists(f"{S}/negative/{name}.json"))
