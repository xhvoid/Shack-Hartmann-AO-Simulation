"""Run the native-versus-HCIPy cross-backend suite against the baseline.

The example only reads the packaged baseline; it never writes one.  Use
``scripts/generate_cross_backend_candidate.py`` for the explicit
candidate-and-acceptance workflow.  Requires the optional HCIPy dependency
(``pip install 'shack-hartmann-ao-simulation[hcipy]'``).
"""

from __future__ import annotations


from shwfs_ao.validation.cross_backend import run_cross_backend_report
from shwfs_ao.validation.regression import (
    evaluate_report_against_baseline,
    load_cross_backend_baseline,
)


def main() -> int:
    baseline = load_cross_backend_baseline()
    report = run_cross_backend_report()

    print("Native-versus-HCIPy cross-backend comparison")
    print(f"config hash: {report['comparison_config']['config_hash'][:16]}")
    print(f"root seed:   {report['root_seed']}")
    header = f"{'comparison':32s} {'metric':44s} {'level':19s} value"
    print(header)
    print("-" * len(header))
    for comparison in report["comparisons"]:
        for metric in comparison["metrics"]:
            value = metric["value"]
            rendered = (
                f"{value:.6g}" if isinstance(value, float) else repr(value)
            )
            print(
                f"{comparison['comparison_kind']:32s} "
                f"{metric['name']:44s} {metric['level']:19s} {rendered}"
            )

    failures = evaluate_report_against_baseline(report, baseline)
    print("-" * len(header))
    if failures:
        print(f"{len(failures)} comparison(s) failed against the baseline:")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print(
        "All gating comparisons satisfy the accepted baseline tolerances. "
        "Runtime and memory entries are informational only, and residual "
        "differences are attributed in each comparison's record; no claim "
        "of complete equivalence is made."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
