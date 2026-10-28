"""Audit: every field path named in the pilot requests' acceptance rules must exist in the matching tool record.

Round 7: besides the absolute dotted paths (rooted at a record's top-level key),
the shorthand paths that start with a dot are resolved against the preceding
absolute path of the same rule, walking up its parents until one resolves
(".extremes" after "prediction.operator_bounds.operator_error.value" is
"prediction.operator_bounds.operator_error.extremes"; ".available.lenslet_fraction"
after "noise_covariance.support_rules.effective.lenslet_fraction" is
"noise_covariance.support_rules.available.lenslet_fraction"); keys that contain
a dot ("fraction_below_0.9") are matched whole; index placeholders ([arm], <rule>)
descend into the first child.
"""
import json
import re
import sys

P = "/home/user/Shack-Hartmann-AO-Simulation/docs/research/post_t2_experiment_packet/pilot_requests.json"
S = "/tmp/claude-0/-home-user-Shack-Hartmann-AO-Simulation/f1f3bff0-5382-5b19-9652-6c00a445942e/scratchpad"
samples = {
    "P1a": f"{S}/round1/p1_ci_alone/pilot.json", "P1b": f"{S}/round3/p1_ci_exposure/pilot.json", "P1c": f"{S}/round1/p1_ci_alone/pilot.json", "P3": f"{S}/round1/p1_ci_alone/pilot.json",
    "P2": f"{S}/round2/ni2m_m5s61/pilot.json",
    "P2b": f"{S}/round8/pilots_maps/ci_m9_alpha0p1/model_sidecar.json",
}
roots = {"acceptance_evidence", "plan_validation", "study_row", "historical_comparison", "arm_telemetry", "mask_disagreement", "trace_summary", "operating_state", "trace_sidecar", "delta_v_series", "prediction", "stationarity", "feedback_spectrum", "noise_covariance", "comparison", "mask_rule", "ru_maxrss_bytes", "wall_s", "memory"}
token = re.compile(r"(?<![A-Za-z0-9_\.])(\.?[a-z_][A-Za-z0-9_\-]*(?:\[[^\]]*\])?(?:\.[A-Za-z0-9_\-]+(?:\[[^\]]*\])?)*)")


def descend(node, parts):
    index = 0
    while index < len(parts):
        part = parts[index]
        base = re.sub(r"\[.*?\]", "", part)
        if base == "":
            if isinstance(node, dict) and node:
                node = next(iter(node.values()))
                index += 1
                continue
            return False
        matched = False
        for width in range(len(parts) - index, 0, -1):
            key = ".".join([base] + [re.sub(r"\[.*?\]", "", p) for p in parts[index + 1:index + width]])
            if isinstance(node, dict) and key in node:
                node = node[key]
                if "[" in parts[index + width - 1]:
                    if isinstance(node, dict) and node:
                        node = next(iter(node.values()))
                    else:
                        return False
                index += width
                matched = True
                break
        if not matched:
            return False
    return True


requests = json.load(open(P))
problems = []
checked = {"absolute": 0, "relative": 0}
for pilot in requests["pilots"]:
    sample = samples.get(pilot["id"])
    if sample is None:
        continue
    record = json.load(open(sample))
    for rule in pilot.get("acceptance", []):
        context = None
        for match in token.finditer(rule):
            path = match.group(1).rstrip(".")
            if path.startswith("."):
                if context is None:
                    continue
                relative = path[1:].split(".")
                if not relative[0] or relative[0][0].isdigit():
                    continue
                ok = False
                for cut in range(len(context) - 1, 0, -1):
                    if descend(record, context[:cut] + relative):
                        ok = True
                        break
                checked["relative"] += 1
                if not ok:
                    problems.append((pilot["id"], ".".join(context) + " + " + path))
                continue
            parts = path.split(".")
            if len(parts) < 2 and parts[0] not in ("ru_maxrss_bytes", "wall_s"):
                continue
            if parts[0] not in roots:
                continue
            checked["absolute"] += 1
            if descend(record, parts):
                context = parts
            else:
                problems.append((pilot["id"], path))
                context = parts
print(json.dumps({"paths_checked": checked, "missing": problems}, indent=1))
sys.exit(1 if problems else 0)
