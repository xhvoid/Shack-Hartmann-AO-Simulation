# Evidence and reporting

## Scale the artifact to the request

For a focused check, a single English Markdown note plus its small reproduction
and execution log is usually sufficient. For an integrated audit, create a
run-owned directory such as `outputs/pre_refactor_audit/<run-id>/` with the
cohesive report, status, provenance, coverage, literature, and test records.
Use absolute paths in the final handoff. Do not create every possible appendix
when it adds no evidence.

## Minimal claim record

Record a stable claim ID; model/algorithm; implemented equation and convention;
configuration selector and validity domain; source location; primary reference
and locator; independent test/oracle; observed result; producing identity;
evidence status; finding class; confidence; and next verification.

Useful evidence statuses are `INSPECTED_CURRENT`, `EXECUTED_CURRENT`,
`INSPECTED_HISTORICAL`, `ANALYTIC_ESTIMATE`, `EXTRAPOLATED`,
`DEFERRED_RESOURCE_POLICY`, `NOT_AVAILABLE`, and `NOT_APPLICABLE`.
Status is separate from a check's `PASS`, `FAIL`, or `PARTIAL` outcome.

For executed checks, retain the exact command/node IDs, code/input/environment
identity, selectors, seeds and RNG scope, threads, time boundaries, exit code,
collection/skips/xfails, and evidence paths. Separate actual runs from proposed
experiments. Never claim inspected logs were executed in the current session.

## Sources

Record title, authors, year/version, DOI or stable URL, section/page/equation,
access status, and the particular supported claim. Distinguish method authority,
parameter provenance, and measured instrument calibration. Mark abstract-only,
secondary-only, inaccessible, or uncertain evidence. Do not invent locators or
treat a citation manager entry as proof that full text was read.

For issue-driven research, retain the triggering finding/question, search terms,
source passages actually read, differences in assumptions or conventions,
whether the initial diagnosis changed, and the remaining distinguishing check.
Record resolved, unresolved, and source-access-blocked outcomes. A list of URLs
without this issue-to-source-to-code bridge does not complete the research step.

## Findings

For each consequential finding include:

- ID, type, impact priority, confidence, and verification status.
- Exact current file/line or artifact and the supported triggering setup.
- Expected behavior with independent justification; observed behavior and limits.
- Minimal reproduction and results, or an explicit statement that it is untested.
- Scientific/engineering consequence and proposed follow-up acceptance criterion.

Prioritize demonstrated impact; do not turn every approximation or missing
future feature into a software defect. Recheck important conclusions independently
when requested or when their impact warrants it. Preserve rejected hypotheses
and rejected review findings with their reasons.

## Integrated report

Use the [report template](audit_report_template.md) for a whole-project
audit, adapting it to actual scope. It covers current architecture/models/modes,
scientific assumptions and literature, method comparison tables, executed and
unexecuted checks, findings, resource analysis, and separate assessments of
scientific support, implementation correctness, and refactor readiness.

Method comparisons need a common basis, selector, meaningful strengths and
weaknesses, validity/support limits, evidence, and computational implications.
Do not rank unlike proxies, analytical estimates, and time-domain systems as
though they measured the same observable.

Resource values need configuration, hardware/environment, producing revision,
measurement boundaries, units, repeats/spread, and one of `MEASURED_CURRENT`,
`MEASURED_HISTORICAL`, `ANALYTIC_ESTIMATE`, `EXTRAPOLATED`, `NOT_MEASURED`.
Include unavailable checks in conclusions. Avoid unconditional assurance when
consequential coverage is missing.
