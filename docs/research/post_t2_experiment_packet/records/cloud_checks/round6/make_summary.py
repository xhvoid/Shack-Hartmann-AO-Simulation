"""Print the round-6 result tables from the v7 records (reconstruction, carried-state source, conditional prediction, budget, bracket and margin calibration, memory)."""
import glob, json, math, os, statistics as st
S = "/tmp/claude-0/-home-user-Shack-Hartmann-AO-Simulation/f1f3bff0-5382-5b19-9652-6c00a445942e/scratchpad/round6"


def load(p):
    with open(p) as h:
        return json.load(h)


def pct(x): return "n/a" if x is None else f"{x*100:+.2f} %"
def ppct(x): return "n/a" if x is None else f"{x*100:.3f} %"
def sci(x): return "n/a" if x is None else f"{x:.2e}"
def num(x, f="{:.4f}"): return "n/a" if x is None else f.format(x)


print("## self-test")
t = load(f"{S}/model_self_test.json")
print({"schema": t.get("schema"), "passed": t.get("passed")})


def describe(name, m):
    p = m["prediction"]; nc = m["noise_covariance"]; op = nc["operator"]; c = m.get("comparison", {})
    b = p["operator_bounds"]; tv = b["time_varying"]; rc = b["reconstruction"]; cs = b["carried_state"]; sy = b["systematic"]
    br = nc["bracket"]; mc = br.get("margin_calibration", {}); mem = m["memory"]; dm = b["direct_state_measurement"]; mp = b.get("map_based_carried_state", {})
    rcs = rc.get("carried_state", {}); out = rc.get("content_outside_modal_operator_range", {}); flags = b.get("run_flags", {})
    conditional = b.get("delta_v_conditional_window_m2")
    print(f"{name}: schema {m['schema']}; operators noisy {op['distinct_effective_masks_noisy_all_frames']} (+{tv.get('twin_only_masks', 0)} twin-only); arm-disagreement frames {flags.get('arm_disagreement_frames')}; "
          f"operator error {pct(tv.get('operator_error'))} [burn-in part {pct(tv.get('burn_in_carried_component'))}], bracket width {ppct(tv.get('bracket_width_over_modal'))}, rows bracketed {br['rows_outside_modal_mask_bracketed']}; "
          f"margin calibration: axes {mc.get('axes')}, ratio median {num(mc.get('ratio_median'), '{:.3f}')}, max {num(mc.get('ratio_max'), '{:.3f}')}, upper max {num(mc.get('ratio_upper_97_5_max'), '{:.3f}')}, faintest quarter upper max {num(mc.get('faintest_quarter_ratio_upper_97_5_max'), '{:.3f}')}, covers {mc.get('margin_covers')}; "
          f"reconstruction {rc.get('status')}: rel rms {sci(rc.get('relative_rms_vs_measured_series'))}, consistent {rc.get('consistent')}; telemetry carried {ppct(rcs.get('window_contribution_over_primary'))} (modelled {ppct(rcs.get('modelled_window_contribution_over_primary'))}), outside modal range {sci(out.get('window_fraction'))}; "
          f"maps: {dm.get('status')} fit residual {sci(dm.get('fit_residual_fraction'))}, maps-vs-telemetry {sci(dm.get('maps_vs_telemetry_state_relative_rms'))}, map carried {ppct(mp.get('window_contribution_over_primary'))}; "
          f"source {b.get('carried_state_source')}; conditional {'n/a' if conditional is None else f'{conditional*1e18:.2f} nm2'}; measured/conditional {num(c.get('measured_over_conditional_prediction'))}; measured/unconditional {num(c.get('measured_over_exact_window'))}; "
          f"budget u {ppct(sy.get('total'))} (operator {ppct(sy.get('operator_error_abs'))}, r {sci(sy.get('reconstruction_residual'))}, f {sci(sy.get('source_residual'))}); fallback gamma bound {ppct(cs.get('bound'))}; classification {b['classification']}; "
          f"memory retained {mem['retained_total_bytes']/2**20:.1f} MiB (pupil kept {mem['pupil_response_kept']}), peak {mem['ru_maxrss_bytes']/2**20:.1f} MiB; reasons {b['reasons']}")


print("\n## pilot sidecars (round-2, no maps)")
for d in ("ni2m_m5s61", "ci_m7_default", "ci_m7_alpha0p1", "ci_m9_default", "ci_m9_alpha0p1"):
    f = f"{S}/{d}/model_sidecar.json"
    if os.path.exists(f):
        describe(d, load(f))
    else:
        print(d, "missing")
print("\n## ci pilots with retained maps (round-6)")
for d in ("ci_m7_alpha0p1", "ci_m7_default", "ci_m9_alpha0p1"):
    f = f"{S}/pilots_maps/{d}/model_sidecar.json"
    if os.path.exists(f):
        describe(d + " (maps)", load(f))
        pilot = load(f"{S}/pilots_maps/{d}/pilot.json")
        print(f"   pilot: wall {pilot.get('wall_s'):.1f} s, ru_maxrss {pilot.get('ru_maxrss_bytes', 0)/2**20:.0f} MiB, sidecar bytes {pilot.get('trace_sidecar', {}).get('bytes')}")
    else:
        print(d, "missing")

print("\n## 32 series sidecars")
rows = []
for f in sorted(glob.glob(f"{S}/ni2m_models/*.json")):
    if f.endswith("summary.json"):
        continue
    m = load(f); nc = m["noise_covariance"]; p = m["prediction"]; op = nc["operator"]; val = nc.get("sidecar_validation", {})
    e = dict(label=nc["label"], seed=nc["root_seed"], distinct_all=op["distinct_effective_masks_noisy_all_frames"], validated=val.get("record", {}).get("runner_validate_trace_payload") == "passed", gate_quiet=nc["gate_quiet_by_core_rule"], defined=p.get("primary_status") == "defined", saturation=nc["noisy_arm_saturation_fraction_mean"], bracketed=nc["bracket"]["rows_outside_modal_mask_bracketed"], margin=nc["bracket"].get("margin_calibration", {}), memory=m["memory"]["retained_total_bytes"], peak=m["memory"]["ru_maxrss_bytes"], maps=m["memory"]["pupil_response_kept"])
    if e["defined"]:
        c = m["comparison"]; b = p["operator_bounds"]; tv = b["time_varying"]; rc = b["reconstruction"]; sy = b["systematic"]; dm = b["direct_state_measurement"]
        e.update(classification=b["classification"], consistent=b["operator_consistent"], operator_error=tv.get("operator_error"), tv_status=tv["status"], rec_status=rc.get("status"), rec_rms=rc.get("relative_rms_vs_measured_series"), rec_ok=rc.get("consistent"), source=b.get("carried_state_source"), carried=rc.get("carried_state", {}).get("window_contribution_over_primary"), map_carried=b.get("map_based_carried_state", {}).get("window_contribution_over_primary"), ratio=c["measured_over_exact_window"], ratio_cond=c.get("measured_over_conditional_prediction"), budget=sy["total"], fallback=b["carried_state"].get("bound"), maps_rms=dm.get("maps_vs_telemetry_state_relative_rms"), disagreement=b.get("run_flags", {}).get("arm_disagreement_frames"), saturated_frames=b.get("run_flags", {}).get("saturated_frames_any_arm"), reasons=b["reasons"])
    else:
        e.update(reason=p.get("reason"), classification="primary not defined", consistent=False)
    rows.append(e)
for lab in ("m5", "m6", "m7", "m8"):
    sel = [x for x in rows if x["label"] == lab]; defined = [x for x in sel if x["defined"]]
    if not sel:
        continue
    classes = {k: sum(1 for x in sel if x["classification"] == k) for k in sorted(set(x["classification"] for x in sel))}
    rec = [x["rec_rms"] for x in defined if x.get("rec_rms") is not None]
    vals = [x["ratio"] for x in defined]
    errs = [x["operator_error"] for x in defined if x.get("operator_error") is not None]
    sources = {k: sum(1 for x in defined if x.get("source") == k) for k in sorted(set(str(x.get("source")) for x in defined))}
    margins = [x["margin"].get("ratio_upper_97_5_max") for x in sel if x["margin"].get("ratio_upper_97_5_max") is not None]
    print(f"{lab}: n={len(sel)} classes {classes} validated {sum(x['validated'] for x in sel)} saturation>1e-3 {sum(x['saturation'] > 1e-3 for x in sel)} gate-quiet {sum(x['gate_quiet'] for x in sel)}; effective ratio {st.mean(vals):.4f} +/- {2.365*st.stdev(vals)/math.sqrt(len(vals)):.4f} (n={len(vals)}); "
          f"reconstruction rel rms {min(rec):.2e}..{max(rec):.2e}, consistent {sum(bool(x.get('rec_ok')) for x in defined)}/{len(defined)}; saturated frames {[x.get('saturated_frames') for x in defined]}; carried source {sources}; "
          f"map-supplied: {[(x['seed'], num(x.get('ratio_cond')), ppct(x.get('budget')), ppct(x.get('map_carried'))) for x in defined if x.get('source') == 'residual maps']}; "
          f"operator error {pct(min(errs)) if errs else 'n/a'}..{pct(max(errs)) if errs else 'n/a'}; margin upper max {num(min(margins), '{:.2f}') if margins else 'n/a'}..{num(max(margins), '{:.2f}') if margins else 'n/a'}; bracketed rows {sum(x['bracketed'] for x in sel)}; peak max {max(x['peak'] for x in sel)/2**20:.0f} MiB")
json.dump({"rows": rows}, open(f"{S}/ni2m_models/summary.json", "w"), indent=1, default=str)

print("\n## fixtures")
summary_path = f"{S}/fixtures/carried_fixture_summary.json"
if os.path.exists(summary_path):
    print("carried fixture built:", json.dumps(load(summary_path)))
for name in ("carried_model", "series_scaled_model", "bracket_model"):
    f = f"{S}/fixtures/{name}.json"
    if os.path.exists(f):
        describe(name, load(f))
        if name == "bracket_model":
            print("   bracket details:", json.dumps(load(f)["noise_covariance"]["bracket"]["details"])[:900])
    else:
        stdout = f"{S}/fixtures/{name}.stdout"
        print(name, "no record:", open(stdout).read()[-400:] if os.path.exists(stdout) else "")

print("\n## replay check")
rp = f"{S}/replay/replay_check.json"
if os.path.exists(rp):
    for case, entry in load(rp).items():
        print(case, json.dumps({"delta_v_replay_vs_sidecar": entry["delta_v_replay_vs_sidecar_max_relative"], "solver": entry["reconstructor_metadata"], "masks": entry["distinct_masks_probed"], "arms": entry["arms"]}))

print("\n## negative checks")
for name in ("wrong_units", "wrong_axes", "wrong_dtype"):
    path = f"{S}/negative/{name}.stdout"
    if os.path.exists(path):
        with open(path) as h:
            lines = h.read().strip().splitlines()
        print(name, "->", (lines[-1][:160] if lines else "(no output)"), "| json written:", os.path.exists(f"{S}/negative/{name}.json"))
