"""Print the round-5 result tables from the records (operator error with bracket, carried-state bound, systematic budget, memory)."""
import glob, json, math, os, statistics as st
S = "/tmp/claude-0/-home-user-Shack-Hartmann-AO-Simulation/f1f3bff0-5382-5b19-9652-6c00a445942e/scratchpad/round5"
def load(p):
    with open(p) as h: return json.load(h)
def pct(x): return "n/a" if x is None else f"{x*100:+.2f} %"
def ppct(x): return "n/a" if x is None else f"{x*100:.2f} %"
print("## self-test"); t = load(f"{S}/model_self_test.json"); print({k: t[k] for k in ("passed",)}); print(json.dumps(t["carried_state_sensitivity"]))
print("\n## pilot sidecars")
for d in ("ni2m_m5s61", "ci_m7_default", "ci_m7_alpha0p1", "ci_m9_default", "ci_m9_alpha0p1"):
    f = f"{S}/{d}/model_sidecar.json"
    if not os.path.exists(f): print(d, "missing"); continue
    m = load(f); p = m["prediction"]; nc = m["noise_covariance"]; op = nc["operator"]; c = m.get("comparison", {}); b = p["operator_bounds"]; tv = b["time_varying"]; cs = b["carried_state"]; sy = b["systematic"]; br = nc["bracket"]; mem = m["memory"]
    print(f"{d}: operators (run) {op['distinct_effective_masks_noisy_all_frames']}; operator error {pct(tv.get('relative_difference_vs_modal'))} (bracket width {ppct(tv.get('bracket_width_over_modal'))}, rows bracketed {br['rows_outside_modal_mask_bracketed']}, estimated outside {br['rows_outside_modal_mask_estimated']}; burn-in part {pct(tv.get('burn_in_carried_component'))}; probe {tv.get('probe_s', 0):.1f} s); "
          f"gamma sensed {cs.get('gamma_sensed'):.4f} all {cs.get('gamma_all_states'):.4f} used {cs.get('gamma_used'):.4f} ({cs.get('gamma_basis')}); unsensed modes {cs['unsensed_modes']} injection {cs['unsensed_mode_injection']}; first-block excess {pct(cs.get('first_block_excess_over_primary'))}, block scatter {ppct(cs.get('block_scatter_over_primary'))} ({cs['blocks']} blocks); carried bound {ppct(cs.get('bound'))} (all-state {ppct(cs.get('bound_all_states'))}); budget u {ppct(sy['total'])}; gamma time {cs['gamma_s']:.1f} s; "
          f"classification {b['classification']}; measured/window {c.get('measured_over_exact_window'):.3f} (by rule " + ", ".join(f"{k}: {('n/a' if v is None else f'{v:.3f}')}" for k, v in c.get("measured_over_exact_window_by_rule", {}).items()) + f"); within 2 block SE {c.get('exact_window_within_2_block_se')}; validation arrays {nc['sidecar_validation']['arrays_checked']}; memory retained {mem['retained_total_bytes']/2**20:.1f} MiB (transient {mem['pupil_response_freed_after_gram_bytes']/2**20:.1f}), peak {mem['ru_maxrss_bytes']/2**20:.1f} MiB")
print("\n## 32 series sidecars")
rows = []
for f in sorted(glob.glob(f"{S}/ni2m_models/*.json")):
    if f.endswith("summary.json"): continue
    m = load(f); nc = m["noise_covariance"]; p = m["prediction"]; op = nc["operator"]; val = nc.get("sidecar_validation", {})
    e = dict(label=nc["label"], seed=nc["root_seed"], distinct_all=op["distinct_effective_masks_noisy_all_frames"], validated=val.get("record", {}).get("runner_validate_trace_payload") == "passed", arrays=val.get("arrays_checked"), gate_quiet=nc["gate_quiet_by_core_rule"], defined=p.get("primary_status") == "defined", saturation=nc["noisy_arm_saturation_fraction_mean"], bracketed=nc["bracket"]["rows_outside_modal_mask_bracketed"], outside_estimated=nc["bracket"]["rows_outside_modal_mask_estimated"], memory=m["memory"]["retained_total_bytes"], peak=m["memory"]["ru_maxrss_bytes"])
    if e["defined"]:
        c = m["comparison"]; b = p["operator_bounds"]; tv = b["time_varying"]; cs = b["carried_state"]; sy = b["systematic"]
        e.update(classification=b["classification"], consistent=b["operator_consistent"], operator_error=tv.get("relative_difference_vs_modal"), bracket_width=tv.get("bracket_width_over_modal"), burn_in_part=tv.get("burn_in_carried_component"), tv_status=tv["status"], gamma_s=cs.get("gamma_sensed"), gamma_all=cs.get("gamma_all_states"), excess1=cs.get("first_block_excess_over_primary"), scatter=cs.get("block_scatter_over_primary"), bound=cs.get("bound"), budget=sy["total"], ratio=c["measured_over_exact_window"], by=c["measured_over_exact_window_by_rule"], within=c["exact_window_within_2_block_se"], reasons=b["reasons"])
    else:
        e.update(reason=p.get("reason"), classification="primary not defined", consistent=False)
    rows.append(e)
summary = {}
for lab in ("m5", "m6", "m7", "m8"):
    sel = [x for x in rows if x["label"] == lab]
    if not sel: continue
    defined = [x for x in sel if x["defined"]]; consistent = [x for x in defined if x["consistent"]]
    out = {"n": len(sel), "defined": len(defined), "operator_consistent": len(consistent), "classifications": {k: sum(1 for x in sel if x["classification"] == k) for k in sorted(set(x["classification"] for x in sel))}, "validated": sum(x["validated"] for x in sel), "gate_quiet": sum(x["gate_quiet"] for x in sel), "saturation_excluded": sum(x["saturation"] > 1e-3 for x in sel), "rows_bracketed": [x["bracketed"] for x in sel], "rows_outside_estimated": [x["outside_estimated"] for x in sel]}
    for rule in ("effective", "available", "strict"):
        vals = [x["by"][rule] for x in defined if x["by"].get(rule) is not None]
        out[rule] = {"n": len(vals), "mean": st.mean(vals) if vals else None, "t_halfwidth_7dof": (2.365 * st.stdev(vals) / math.sqrt(8)) if len(vals) == 8 else None, "per_seed": [round(v, 3) for v in vals]}
    comp = [x for x in defined if x["tv_status"] == "computed"]
    out["operator_error_range"] = [min(x["operator_error"] for x in comp), max(x["operator_error"] for x in comp)] if comp else None
    out["bracket_width_max"] = max((x["bracket_width"] for x in comp), default=None)
    out["burn_in_part_max_abs"] = max((abs(x["burn_in_part"]) for x in comp), default=None)
    out["gamma_sensed"] = sorted(set(round(x["gamma_s"], 4) for x in defined))
    out["excess1_range"] = [min(x["excess1"] for x in defined), max(x["excess1"] for x in defined)]
    out["scatter_range"] = [min(x["scatter"] for x in defined), max(x["scatter"] for x in defined)]
    out["bound_range"] = [min(x["bound"] for x in defined), max(x["bound"] for x in defined)]
    budgets = [x["budget"] for x in defined if x["budget"] is not None]
    out["budget_range"] = [min(budgets), max(budgets)] if budgets else None
    out["budget_mean_operator_consistent"] = st.mean([x["budget"] for x in consistent]) if consistent else None
    out["within_2se"] = sum(x.get("within", False) for x in defined)
    out["memory_mib"] = {"retained_max": max(x["memory"] for x in sel) / 2**20, "peak_max": max(x["peak"] for x in sel) / 2**20}
    summary[lab] = out
    def fmt(rule):
        e = out[rule]; return f"{rule} n={e['n']} " + (f"{e['mean']:.4f} +/- {e['t_halfwidth_7dof']:.4f}" if e["n"] == 8 else f"{e['per_seed']}")
    print(f"{lab}: n={len(sel)} defined {len(defined)} classes {out['classifications']} validated {out['validated']} gate-quiet {out['gate_quiet']} saturation>1e-3 {out['saturation_excluded']}; {fmt('effective')}; {fmt('available')}; {fmt('strict')}; "
          + (f"operator error {pct(out['operator_error_range'][0])}..{pct(out['operator_error_range'][1])} (bracket width max {ppct(out['bracket_width_max'])}, rows bracketed {out['rows_bracketed']}, outside estimated {out['rows_outside_estimated']}; burn-in part max {ppct(out['burn_in_part_max_abs'])}); " if comp else "")
          + f"gamma sensed {out['gamma_sensed']}; first-block excess {pct(out['excess1_range'][0])}..{pct(out['excess1_range'][1])}; block scatter {ppct(out['scatter_range'][0])}..{ppct(out['scatter_range'][1])}; carried bound {ppct(out['bound_range'][0])}..{ppct(out['bound_range'][1])}; budget u {ppct(out['budget_range'][0]) if out['budget_range'] else 'n/a'}..{ppct(out['budget_range'][1]) if out['budget_range'] else 'n/a'} (mean over operator-consistent {ppct(out['budget_mean_operator_consistent'])}); within 2 block SE {out['within_2se']}/{len(defined)}; memory retained max {out['memory_mib']['retained_max']:.1f} MiB peak max {out['memory_mib']['peak_max']:.1f} MiB")
for x in rows:
    if x["label"] == "m8": print(f"   m8 seed {x['seed']}: {x['classification']}; op err {pct(x.get('operator_error'))}; bracket {ppct(x.get('bracket_width'))} rows bracketed {x['bracketed']}; burn-in part {pct(x.get('burn_in_part'))}; excess1 {pct(x.get('excess1'))}; bound {ppct(x.get('bound'))}; u {ppct(x.get('budget'))}; ratio {x.get('ratio')}; reasons {x.get('reasons')}")
json.dump({"rows": rows, "per_magnitude": summary}, open(f"{S}/ni2m_models/summary.json", "w"), indent=1, default=str)
print("\n## negative checks")
for name in ("wrong_units", "wrong_axes", "wrong_dtype"):
    path = f"{S}/negative/{name}.stdout"
    if os.path.exists(path):
        with open(path) as h: lines = h.read().strip().splitlines()
        print(name, "->", (lines[-1][:160] if lines else "(no output)"), "| json written:", os.path.exists(f"{S}/negative/{name}.json"))
