# Targeted post-audit reconciliation and repair

Prepared 2026-10-18, Europe/Berlin.

## 1. Assignment and authorization

Reconcile the GPT pre-refactor scientific audit with the actual Claude cleanup
branch, reproduce the scoped findings, repair confirmed defects, verify the
result, and update the English engineering documentation and acceptance record.
Execute this work; do not stop at another plan.

When the user assigns this prompt, it explicitly authorizes the narrowly scoped
implementation, meaningful regression tests, bounded numerical checks, research,
and documentation updates described below. It supersedes read-only defaults
only for those repairs. The earlier audits and historical records remain intact.
It does not authorize another broad refactor, new scientific features, commits,
merges, pushes, accepted-baseline replacement, or new telescope-scale studies.
Preserve any distinct authorization already supplied by the user in this session.

Use the AO Simulation Research & Validation skills where available. A dedicated
Deep Research product is not required. Proactively search, open and read primary
literature or authoritative technical documentation when investigating substantive
findings; record the issue-to-source-to-code connection and access limits.

## 2. Worktree and input records

Work only in the existing cleanup checkout:

`/Users/xuhan/Documents/AO Simulation/.claude/worktrees/cleanup-refactor-exec`

Expected branch: `claude/cleanup-refactor-exec`. Observed preparation HEAD was
`27f34fa9723df77f57ce7b2c438c3ff240d9b0e8`. Record actual current HEAD, dirty
inputs, relevant untracked files, environment and active instructions before
editing. Inspect later changes; do not reset to the preparation revision,
switch to main, create a competing implementation, or discard user work.

The main checkout is input evidence, not an implementation destination.
Read these absolute paths; the GPT audit output may not exist inside the
cleanup worktree:

- `/Users/xuhan/Documents/AO Simulation/outputs/pre_refactor_audit/20261017T143700Z/PRE_REFACTOR_AUDIT_REPORT.md`
- The same audit's `AUDIT_STATUS.md`, `claim_evidence.csv`, `test_manifest.json`,
  `entry_manifest.json`, `integrity_check.json`, `independent_review.md`, and
  finding-specific reproductions/logs referenced in the report.
- `/Users/xuhan/Documents/AO Simulation/outputs/audit_reconciliation/2026-10-18-initial/RECONCILIATION.md`
- `/Users/xuhan/Documents/AO Simulation/docs/refactor/AUDIT_FINDING_EXCHANGE_FORMAT.md`
- In the cleanup checkout: `docs/refactor/CLEANUP_REFACTOR_STATUS.md`,
  `docs/technical_reference.md`, `docs/current_limitations.md`, `docs/roadmap.md`,
  and `outputs/cleanup_refactor/2026-10-18-claude-2312502/review/review.md`.

Read the appended closure of the Claude review as well as its initial findings.
Bind its acceptance to the tree it actually covered. Later follow-ups are not
automatically accepted by an earlier review.

Save new outputs under a fresh
`outputs/audit_reconciliation/<run-id>/` in the cleanup checkout. Apply the shared
finding exchange format. Keep source-report IDs namespaced: GPT F-01 and Claude
F-01 concern different issues. Preserve all original reports and evidence.

## 3. Build the shared finding map

Create FINDINGS.json and the English reconciliation report. Map every GPT
finding F-01 through F-12 to current code and any corresponding Claude finding,
repair, declared boundary or unresolved obligation. Do not assign repairs to
every item merely because it appears in a report.

Initially use decision UNASSESSED and workflow status OPEN for imported claims
on the current cleanup tree.
The initial reconciliation note is triage, not fresh execution or a guaranteed
diagnosis. Reproduce supported triggers before changing behavior. Record
contradictory evidence, narrow the scope, or reject a mistaken diagnosis with
an explicit rationale. Preserve old IDs as aliases, not canonical shared IDs.

## 4. Required targeted work

### A. GPT F-01: CMOS map-aware ADC uncertainty support

Inspect `detector/noise_model.py`, the physical camera and map definitions,
processing operators, and relevant existing tests. Reuse the small independent
quantizer reproduction from the GPT report in a new output directory.

Determine how actual contributing-pixel read noise, conversion gain, maps,
processing and source noise relate to the declared ADC approximation domain.
The reported defect is an unsupported domain being marked supported; it is not
proof of universal camera covariance failure or large centroid bias.

If confirmed, correct the support policy or justify a broader validated model.
Preserve physical noise sampling and unaffected behavior. Cover uniform and
heterogeneous maps, ADC on/off, relevant processing/bad-pixel behavior, and
centroid-level support consequences with meaningful independent checks.
Do not replace the declared domain with an unexplained threshold or silently
change the forward camera physics to make a covariance test pass.

### B. GPT F-02: effective exposure overrides and run identity

Inspect the public component-loop overrides separately from configured physical
WFS exposure. Adapt the tiny time-varying ramp/sensor reproduction to the current
tree and demonstrate whether distinct effective quadratures share an identity.

If confirmed, make effective duration/sample count and override precedence
truthfully represented in run identity and serialized metadata. Choose and
document a deliberate compatibility/hash/version policy; avoid gratuitously
invalidating unaffected default identities. Test equal effective settings,
distinct effective settings, invalid combinations and sensor/override semantics.
Do not change measurement timing or control behavior as an incidental repair.

### C. GPT F-03: resumed-series dependency provenance

Inspect the current evidence runner, including output-directory, no-op-resume,
and enablement-note follow-ups. Those changes are not themselves a repair of
dependency attribution.

Use a stand-in runner with environment A then environment B; no AO loop is
needed. If the issue persists, either reject incompatible producers or retain
truthful explicit per-run environment/provenance. Document the chosen protocol/
schema and legacy-record behavior. Never invent missing historical producer
metadata or silently attribute old runs to the newest header.

Cover matching/mismatching environments, disjoint and overlapping arms,
new-row append, legacy missing metadata, and no-new-work resume. Preserve
existing identity validation for every retained run, overwrite protection,
output semantics and enablement-note history. Keep historical files read-only.

### D. GPT F-09: verify the corresponding HCIPy fixture repair

Map this to Claude U1 / its F-01. Inspect the exact fixture diff and rerun the
relevant bounded tests when needed on the final target. Preserve both historical
schema/axis contracts and a current-schema end-to-end route. Treat the original
pre-audit failures as historical evidence, not as current failures or erased
records. Do not weaken schema validation merely to obtain green tests.

### E. Other findings and later changes

Classify GPT F-04 through F-08 and F-10 through F-12 against current documentation
and implementation. Correct relevant wording/provenance within this assignment,
or retain a specific scientific-validation obligation. In particular distinguish
captured-window from source-flux observables, energy coverage from rank, and
exploratory statistical evidence from validated ensemble uncertainty.

Do not change optical normalization, atmosphere statistics, DM bases, damping,
recovery policy, PWFS API, or historical benchmark acceptance solely to remove a
documented limitation. New consequential defects outside A-D should be recorded
with a concrete reproduction and proposed scope, while finishing independent
authorized work. No general permission for unrelated code repair is implied.

Inspect post-closure changes in the cleanup record and determine which checks
cover them. Keep existing experiments/worktrees untouched; bind their results
to their actual producer rather than relabelling them as validation of new fixes.

## 5. Validation and independent acceptance

Implement each confirmed repair as a separate logical change unit with its own
before/after evidence and meaningful regression tests. Preserve unrelated user
changes. Worktree isolation does not permit changing other agents' inputs.

Run relevant bounded numerical checks serially with two native threads, subject
to the current resource policy. Start with minimal independent fixtures; use
predeclared sampling uncertainty for any necessary bounded Monte Carlo work.
No 12 m/42 m or long ensemble run is required to demonstrate A-C. Do not start
new governed work or infer authorization from historical notes. Continue other
work while any genuinely necessary authorization is unresolved.

After repairs, run affected suites, runner/schema/profile/resource checks and
relevant lint/types. Complete the final native regression and bounded installed
HCIPy selection appropriate to the changed files; retain required packaging/
installed behavior checks where changes affect their contracts. Existing passing
evidence may be reused only with a documented identity/scope justification.
Retain strict expected failures and explicit unavailable lanes. Do not run every
historical slow experiment or repeat tests without a new reason.

An independent reviewer must challenge the repairs and key classifications
against the exact final tree, check the evidence and unaffected contracts, and
record acceptance using the shared format. Separate implementation from reviewer
judgment; agreement without independent expectations is insufficient. A later
separate GPT reviewer may provide this step if no independent agent is available.
Until it does, leave findings FIXED_PENDING_VERIFICATION.

Update the technical reference, limitations, roadmap and cleanup execution
record with narrow corrections, compatibility decisions and exact evidence.
Add the reconciliation exchange file to the cleanup worktree when needed so
both agents can use the same contract. Do not rewrite earlier audit conclusions
or claim unexecuted CI/scientific work passed.

## 6. Final handoff

Produce FINDINGS.json, RECONCILIATION_REPORT.md, TEST_MANIFEST.json, ACCEPTANCE.md
and STATUS.md, with supporting evidence and stable links. Keep all artifacts
English and resumable. State the exact final source identity and separately:

- Which imported findings reproduced, were repaired, were independently closed,
  were not reproduced, or remain disputed/deferred/accepted boundaries.
- Whether unaffected behavior, public compatibility, scientific identities and
  accepted resources remain intact, with declared intentional changes.
- Which checks were actually executed and which are historical/unavailable.
- Whether the scoped repair is accepted and which scientific limits remain.

Stop at this reviewable handoff. A passing report is not authorization to commit,
merge into main, publish, replace baselines, or rerun large studies.
