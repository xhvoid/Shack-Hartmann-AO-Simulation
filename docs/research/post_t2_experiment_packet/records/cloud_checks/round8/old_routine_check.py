"""Run the round-7 (v8) and the round-8 (v9) box-extreme routines on the self-test's 48 singular cases (review round 8).

Usage: old_routine_check.py <round-7 tool path> <round-8 tool path>
For each case the extremes are compared with a 401 x 401 grid of the box, and
each returned point is checked against both intervals.
"""
import importlib.util
import json
import sys

import numpy as np


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


results = {}
for label, path in (("round-7 (v8)", sys.argv[1]), ("round-8 (v9)", sys.argv[2])):
    module = load(path, label.split()[0].replace("-", "_"))
    wrong, outside, cases, worst = 0, 0, 0, 0.0
    for a, b, h in ((0.0, 2.0, 0.0), (1.5, 0.0, 0.0), (0.0, 0.0, 0.0), (1.0, 4.0, 2.0), (1.0, 4.0, -2.0), (-1.0, -4.0, 2.0), (-1.0, -4.0, -2.0), (0.25, 1.0, 0.5)):
        for p_range, q_range in (((0.3, 1.2), (0.7, 0.7)), ((0.3, 1.2), (0.5, 0.9)), ((0.6, 0.6), (0.0, 1.0)), ((0.6, 0.6), (0.4, 0.4)), ((0.0, 1.0), (0.0, 1.0)), ((0.2, 0.9), (0.1, 1.3))):
            (low, p_low, q_low), (high, p_high, q_high) = module.quadratic_box_extremes(a, b, h, p_range, q_range)
            grid_p, grid_q = np.meshgrid(np.linspace(*p_range, 401), np.linspace(*q_range, 401))
            values = a * grid_p**2 + b * grid_q**2 + 2.0 * h * grid_p * grid_q
            gap = max(abs(low - values.min()), abs(high - values.max()))
            worst = max(worst, gap)
            wrong += int(gap > 1.0e-9)
            outside += int(not all(p_range[0] <= p <= p_range[1] for p in (p_low, p_high)) or not all(q_range[0] <= q <= q_range[1] for q in (q_low, q_high)))
            cases += 1
    results[label] = {"cases": cases, "extremes_wrong": wrong, "points_outside_an_interval": outside, "largest_deviation_from_grid": worst}
print(json.dumps(results, indent=1))
