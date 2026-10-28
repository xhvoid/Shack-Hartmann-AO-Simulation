"""Audit: every dotted field path named in the pilot requests' acceptance rules must exist in the matching tool record."""
import json, re, sys
P = "/home/user/Shack-Hartmann-AO-Simulation/docs/research/post_t2_experiment_packet/pilot_requests.json"
S = "/tmp/claude-0/-home-user-Shack-Hartmann-AO-Simulation/f1f3bff0-5382-5b19-9652-6c00a445942e/scratchpad"
samples = {
    "P1a": f"{S}/round1/p1_ci_alone/pilot.json", "P1b": f"{S}/round3/p1_ci_exposure/pilot.json", "P1c": f"{S}/round1/p1_ci_alone/pilot.json", "P3": f"{S}/round1/p1_ci_alone/pilot.json",
    "P2": f"{S}/round2/ni2m_m5s61/pilot.json",
    "P2b": f"{S}/round3/ci_m9_alpha0p1/model_sidecar.json",
}
roots = {"acceptance_evidence", "plan_validation", "study_row", "historical_comparison", "arm_telemetry", "mask_disagreement", "trace_summary", "operating_state", "trace_sidecar", "delta_v_series", "prediction", "stationarity", "feedback_spectrum", "noise_covariance", "comparison", "mask_rule", "ru_maxrss_bytes", "wall_s"}
token = re.compile(r"(?<![A-Za-z0-9_])([a-z_]+(?:\[[^\]]*\])?(?:\.[A-Za-z0-9_\-]+(?:\[[^\]]*\])?)+)")

def resolve(record, path):
    node = record
    for part in path.split("."):
        part = re.sub(r"\[.*\]$", "", part)
        if "<" in part or "|" in part or part in ("", "*"):
            # a placeholder like [arm] or <rule>: descend into every child and accept if any child has the rest
            return "placeholder"
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return True

requests = json.load(open(P))
problems = []
checked = 0
for pilot in requests["pilots"]:
    sample = samples.get(pilot["id"])
    if sample is None: continue
    record = json.load(open(sample))
    for rule in pilot.get("acceptance", []):
        for match in token.finditer(rule):
            path = match.group(1)
            if path.split(".")[0] not in roots: continue
            # strip index placeholders and descend; a path with [arm] or [rule] placeholders is checked up to the placeholder
            parts = path.split(".")
            node = record; ok = True
            for part in parts:
                base = re.sub(r"\[.*?\]", "", part)
                if base == "":
                    # pure index placeholder: descend into the first child
                    if isinstance(node, dict) and node: node = next(iter(node.values())); continue
                    ok = False; break
                if isinstance(node, dict) and base in node:
                    node = node[base]
                    if "[" in part:
                        if isinstance(node, dict) and node: node = next(iter(node.values()))
                        else: ok = False; break
                else:
                    ok = False; break
            checked += 1
            if not ok:
                problems.append((pilot["id"], path))
print(json.dumps({"paths_checked": checked, "missing": problems}, indent=1))
sys.exit(1 if problems else 0)
