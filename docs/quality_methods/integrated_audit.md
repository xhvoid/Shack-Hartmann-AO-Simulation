# Integrated AO research and validation audit

Read the [shared contract](common_contract.md). Establish the
requested scientific/engineering questions, scope, source identity, permitted
execution, outputs, and active resource policy. For the original repository,
read [project integration](project_integration.md); load its
full pre-refactor assignment only when that assignment is requested.

## Route by question

Use the method guide relevant to the question. A focused question does not
require every specialist review.

| Work | Method |
| --- | --- |
| Physical definitions, normalization, assumptions, and observables | [Physical validation](physical_validation.md) |
| Convergence, stochastic experiments, and independent calculations | [Numerical verification](numerical_verification.md) |
| NumPy, sparse, Fourier, and numerical implementation correctness | [Code review](code_review.md) |
| Literature-to-code comparison and source interpretation | [Literature review](literature_review.md) |
| RNG/replay, provenance, protocol, and evidence identities | [Reproducibility](reproducibility.md) |
| Memory, runtime, scaling, and serial/parallel study planning | [Resource analysis](resource_analysis.md) |

## Conduct an integrated audit

1. Inventory actual module/model/mode owners, public entry points, backends,
   profiles, experiments, notebooks, tests, packaging, and historical evidence.
   Include unchanged code, adapters, and experimental/analytical boundaries.
   Diff review alone is insufficient for a whole-repository assignment.
2. Save a run-owned status and coverage matrix. Record inspected, mathematically
   reviewed, independently tested, existing-suite-only, unavailable, and unreviewed
   areas. Freeze an identified snapshot if development continues.
3. Extract precise code-derived questions for each model family. Delegate
   independent reading/research when helpful and available, with bounded packets
   and saved handoffs. Keep one integrating lead and serialize numerical work.
4. Connect implemented equations, units, assumptions, selectors, primary sources,
   independent oracles, tests, and results. Proactively research substantive
   findings as they appear, following the common contract's issue-driven loop;
   do not postpone all reading until report assembly. Return ambiguities to
   the local reviewer; run distinguishing bounded checks where warranted.
5. Execute the requested feasible validation plan, preserving protected inputs.
   Record test selection and actual outcomes; complete relevant native and
   available optional/packaging coverage when the full assignment requires it.
   No blanket telescope-scale or ensemble authorization is implied.
6. Classify findings separately from priority/confidence. Independently challenge
   consequential findings, reproductions, and source interpretation. Resolve
   contradictions in the report, not by silently changing code or thresholds.
7. Produce the cohesive English report with meaningful method comparison tables,
   actual versus historical/unrun checks, limitations, provenance, conditional
   resource estimates, and prioritized follow-up acceptance criteria. Use
   [evidence fields](evidence_and_reporting.md) and the
   [report template](audit_report_template.md).

Give separate conclusions for scientific-claim support, implementation
correctness, and refactor readiness. A known limitation does not automatically
block independent structural cleanup; a consequential correctness problem may
need a repair before its behavior becomes a preservation baseline. Do not
perform that repair without implementation scope.

End each review checkpoint with source identity, completed work, evidence paths, unresolved
questions, integrity status, and the next bounded task. Resume from saved state.
Finish with the report, coverage limits, source-preservation result, and concrete
follow-up. Do not stop at another plan when execution was requested.
