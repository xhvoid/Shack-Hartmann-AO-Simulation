# Shared audit finding and acceptance format

Version: 1.0. Prepared 2026-10-18, Europe/Berlin.

Use this exchange format for independent audit reconciliation, repair,
and verification. Preserve original reports, report-local IDs, logs and raw
evidence unchanged. Do not rewrite historical reports to match this format.
The format aligns evidence and decisions; it does not require identical prose
or agreement between reviewers.

## 1. Canonical deliverables

For each reconciliation run, keep a new caller-owned directory containing:

- `FINDINGS.json`: the authoritative structured reconciliation ledger.
- `RECONCILIATION_REPORT.md`: a readable English summary of that ledger.
- `TEST_MANIFEST.json`: executed checks and clearly separated historical evidence.
- `ACCEPTANCE.md`: exact reviewed identity, independent verdict and remaining limits.
- `STATUS.md`: checkpoint and next bounded action for continuation.
- Supporting logs, reproductions, research notes and source references as needed.

For a narrow check, fewer files are acceptable if all relevant fields survive.
When the ledger and summary disagree, reconcile them before claiming acceptance.
Do not alter numerical evidence to make the records agree.

## 2. Identity and source reports

At ledger level, record:

| Field | Meaning |
| --- | --- |
| `schema_version` | `"1.0"` for this exchange contract. |
| `run_id`, `updated_at` | Unique run identity and ISO-8601 timestamp with time zone. |
| `target` | Absolute repository/worktree path, branch, full HEAD, tracked dirty state, relevant untracked input identities, and a digest or saved manifest binding the actual reviewed inputs. |
| `environment` | Interpreter/package/native-library/backend versions, import origin, hardware and thread settings relevant to the checks, directly or through an evidence reference. |
| `source_reports` | Stable report IDs, absolute paths, reported source identities, dates and scope. Identify the reviewer/model only when known. |
| `findings` | Records defined below. |

For new reconciliations, use report namespaces such as
`preaudit-20261017` and `cleanup-20261018`. A source alias is the
pair `(report_id, finding_id)`, never a bare `F-01`. Existing report IDs
remain unchanged in the original records.

Assign canonical IDs `AR-001`, `AR-002`, and so on, persistently within the
shared ledger. Reuse a canonical ID for the same root problem; do not renumber
when sorting by priority. Match findings by trigger, contract and cause, not by
similar titles or equal old IDs. Splits/merges retain aliases and explanations.
New independent issues get new IDs. No particular count is a target.

## 3. Finding record

| Field | Required content |
| --- | --- |
| `id`, `source_aliases`, `title` | Canonical ID; original report/ID/location links, original classifications/priorities and disagreements; precise problem. |
| `finding_type` | Primary classification from the vocabulary below; optional secondary types. |
| `priority`, `confidence` | P0/P1/P2/P3 or UNASSESSED; HIGH/MEDIUM/LOW/UNASSESSED, with impact/evidence rationale. |
| `scope` | Affected API/model/selector/backend/schema and supported triggering configuration. |
| `locations` | Current paths, functions and one-based lines, bound to a source identity. |
| `contract`, `expected`, `observed` | Governing behavior and independent justification, actual result, and qualifications. |
| `reconciliation_decision` | UNASSESSED, CONFIRMED, PARTIALLY_CONFIRMED, DISPUTED, REJECTED, DUPLICATE or OUT_OF_SCOPE, with evidence-based rationale. |
| `status` | Workflow state from section 4, plus rationale. |
| `research` | Issue question, search terms, primary source/DOI/URL and passages/locators actually read, applicability and access gaps. NOT_APPLICABLE needs a reason. |
| `evidence` | Reproduction/log/test references, producing identity, command/node IDs, actual outcome, and execution status: EXECUTED_ON_TARGET, HISTORICAL_INPUT_REANALYSIS, LOG_INSPECTED, STATIC_ONLY, NOT_RUN or UNAVAILABLE. |
| `repair` | Proposed/implemented change, compatibility/schema/hash effects, affected files and commit/diff identity; distinguish proposals from actual edits. |
| `verification` | Before/after results where relevant, final source identity, independent reviewer, decision, evidence and remaining uncertainty. |
| `follow_up` | Concrete next action, success criterion, dependency and resource category; deferrals need a reason. |

Primary finding types:

`IMPLEMENTATION_DEFECT`, `PROVENANCE_DEFECT`, `TEST_INFRASTRUCTURE_DEFECT`,
`MODEL_BOUNDARY`, `VALIDATION_GAP`, `DOCUMENTATION_ERROR`,
`ENGINEERING_DEBT`, `ENVIRONMENT_LIMITATION`.

Keep reconciliation decision, workflow state and evidence execution separate.
Also distinguish severity, confidence, finding type and check outcome. Preserve
original source-report terms in aliases when translating into this ledger.
A documented approximation, failed scientific hypothesis, missing
future capability or unavailable environment is not automatically a code defect.

## 4. Status transitions

| Status | Evidence required |
| --- | --- |
| `OPEN` | Imported or supported issue still needs investigation or repair. The reconciliation decision states whether it has reproduced on this target. |
| `FIXED_PENDING_VERIFICATION` | Implementation changed; closure checks or independent review remain. |
| `CLOSED` | Applicable acceptance checks pass and an independent reviewer confirms the resolution for a precisely identified final tree. |
| `DEFERRED` | Unresolved work with reason, impact, resource/dependency boundary and acceptance criterion. |
| `ACCEPTED_BOUNDARY` | Intentionally retained model/operating limitation, supported interpretation and explicit claim restrictions; no repair is being asserted. |
| `NOT_APPLICABLE` | A stated scope/version exclusion with evidence. |

When a reported issue does not reproduce, record the exact attempted trigger,
environment and result. Leave it OPEN or DEFERRED unless adequate contrary
evidence supports a REJECTED decision; non-reproduction alone is inconclusive.
For DISPUTED decisions retain both interpretations and a discriminating check.
DUPLICATE records point to the canonical root finding and preserve all aliases.

An implementer cannot move a finding directly to CLOSED using its own green
summary. An independent reviewer may verify closure.
Record who did what; agreement alone is not proof. Preserve before/after
observations and any contrary source evidence.

Evidence from a different tree applies only through an explicit comparison of
the relevant input/code identities. A commit label alone is insufficient for
a dirty reviewed tree. Retain closure history; re-open findings when relevant
changes invalidate their evidence rather than silently carrying old acceptance.

## 5. Test and acceptance records

For each executed check retain command/node IDs, environment/import origin,
source/input identity, selectors/seeds, threads, timing boundary, log path,
exit code and outcomes. Separate new execution, inspected historical results,
proposed checks, unavailable checks and resource-policy deferrals. Deduplicate
retries in final totals while retaining initial failures and retry rationale.
Expected failures and skips are separate from passes.
A reproducer may exit successfully while demonstrating a defect. Record the
purpose and observation; process exit zero is not proof the scientific/API
contract passed.

The English acceptance record gives separate judgments for:

1. Scoped defect resolution.
2. Preservation of unaffected behavior and compatibility.
3. Documentation/provenance consistency.
4. Scientific validation limits and unavailable required lanes.

Use `PASS`, `PASS_WITH_DECLARED_VALIDATION_LIMITS`, `CHANGES_REQUIRED`, or
`INCOMPLETE_REQUIRED_CHECKS`, with a concrete rationale and reviewed identity.
Unresolved in-scope confirmed P0/P1/P2 defects prevent scoped repair acceptance.
Known scientific gaps may remain explicitly deferred without pretending they
are validated. Do not lower severity or relabel a confirmed defect merely to
obtain a passing verdict.

Formatting does not authorize repairs, new experiments, commits, merges,
baseline acceptance, or publication. Those permissions come from the user's
actual execution assignment.
