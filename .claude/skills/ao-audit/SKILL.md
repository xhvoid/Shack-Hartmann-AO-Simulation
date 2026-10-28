---
name: ao-audit
description: Coordinate an integrated AO simulation audit spanning physical models, numerical algorithms, scientific code, literature, reproducibility, and resource costs, with an English report. Use for whole-project or cross-domain audits, not ordinary implementation work or a single specialist question.
argument-hint: "[audit scope, question, or assignment file]"
---

# Integrated AO research and validation audit

Read the [shared contract](../../references/common-contract.md). Establish the
requested scientific/engineering questions, scope, source identity, permitted
execution, outputs, and active resource policy. For the original repository,
read [project integration](../../references/project-integration.md); load its
full pre-refactor assignment only when that assignment is requested.

## Route by question

Use the relevant specialist instructions directly from this package when not
available as separately invocable skills. Do not load all specialists for a
single narrow question. In Claude Code, invoke a listed specialist with the
Skill tool (`ao-<name>` as a project skill, or
`ao-simulation-research-validation:ao-<name>` from the installed plugin), or
read its `SKILL.md` at the linked path; both load the same instructions.

| Work | Skill |
| --- | --- |
| Physical definitions, normalization, assumptions, and observables | [ao-physical-validation](../ao-physical-validation/SKILL.md) |
| Convergence, stochastic experiments, and independent calculations | [ao-numerical-verification](../ao-numerical-verification/SKILL.md) |
| NumPy, sparse, Fourier, and numerical implementation correctness | [ao-code-review](../ao-code-review/SKILL.md) |
| Literature-to-code comparison and source interpretation | [ao-research-workflow](../ao-research-workflow/SKILL.md) |
| RNG/replay, provenance, protocol, and evidence identities | [ao-reproducibility](../ao-reproducibility/SKILL.md) |
| Memory, runtime, scaling, and serial/parallel study planning | [ao-resource-analysis](../ao-resource-analysis/SKILL.md) |

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
   [evidence fields](../../references/evidence-and-reporting.md) and the
   [report template](../../assets/audit-report-template.md).

Give separate conclusions for scientific-claim support, implementation
correctness, and refactor readiness. A known limitation does not automatically
block independent structural cleanup; a consequential correctness problem may
need a repair before its behavior becomes a preservation baseline. Do not
perform that repair without implementation scope.

End each session with source identity, completed work, evidence paths, unresolved
questions, integrity status, and the next bounded task. Resume from saved state.
Finish with the report, coverage limits, source-preservation result, and concrete
follow-up. Do not stop at another plan when execution was requested.
