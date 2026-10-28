# Pre-Refactor Scientific and Engineering Audit

> **Historical plan.** The work and its verification are recorded in the
> [execution record](CLEANUP_REFACTOR_STATUS.md). Current implementation and open work are described
> in the [technical reference](../technical_reference.md) and [roadmap](../roadmap.md).

Prepared: 2026-10-17, Europe/Berlin.

Preparation HEAD: `f09eb160223efc147cf1d3d3cd4f8857f44971a0`.

This is a future execution assignment. Preparing this plan does not mean
that the audit, literature research, or tests have already been performed.
Use the actual local state when the assignment starts; do not reset to the
preparation HEAD.

## 1. Objective and authority

Audit the entire local adaptive-optics project before cleanup or refactoring.
Assess its modules, physical models, numerical algorithms, supported execution
modes, scientific claims, tests, reproducibility, and computational costs.
Search for and read relevant primary literature autonomously. Produce one
cohesive English report with traceable supporting evidence.

This assignment authorizes inspection, bounded testing, literature research,
temporary independent reproductions, and audit outputs. It does not authorize
implementation changes, repairs, cleanup, tuning, or baseline acceptance.
Finding a defect does not authorize fixing it.

Read applicable repository and environment instructions. The existing
[cleanup execution plan](repository_consolidation_plan.md) and
[cleanup review plan](repository_consolidation_review.md) provide background
and scientific checklists. Their implementation permissions and post-refactor
deliverables do not apply to this audit. Missing future cleanup deliverables
are not current defects. This audit may supply evidence for CLN-00, but is not
automatic acceptance of that ticket or of the later refactor.

## 2. Protected files and permitted outputs

Treat existing simulation source, tests, examples, notebooks, configurations,
profiles, resources, accepted baselines, dependency files, and documentation
as read-only. Preserve existing tracked and untracked user changes.

Create all audit material in a new caller-owned directory:

`outputs/pre_refactor_audit/<run-id>/`

Use an absolute path in execution records. Save temporary reproduction scripts,
test logs, research packets, reports, caches, and generated figures there or in
an audit-owned temporary directory. Do not overwrite earlier runs.

Do not commit, push, reset, stash, regenerate accepted artifacts, change test
expectations, run formatters in write mode, or install over the working
environment. Review findings remain open for a later implementation task.

Capture initial and final hashes of protected inputs, including relevant
untracked inputs and existing dirty files. A comparison with clean HEAD alone
does not prove that the user's working state was preserved.

Tests, notebook tools, and builds can write files even without an intentional
source edit. Inspect their output behavior first. If a tool cannot safely
redirect writes, run it from an isolated copy of the actual working state.
Include dirty and relevant untracked scientific inputs; a clean HEAD archive
alone is insufficient. Keep reproduced source bytes unchanged. Record which
copy, package installation, and environment were actually exercised.

If development continues during the audit, freeze an identified audit snapshot
and assess that snapshot. Record subsequent changes separately; do not blend
results from different trees into one unqualified conclusion. Do not revert
concurrent user edits to make the final hashes match.

## 3. Combine local review and literature research

Use one integrating lead and three complementary responsibilities:

| Responsibility | Main task | Required handoff |
| --- | --- | --- |
| Local code and test reviewer | Inspect the entire tree, extract implemented models and contracts, execute bounded tests, identify disputed claims. | Module inventory, exact code locations, implemented equations, configuration selectors, test evidence, focused research questions. |
| Literature researcher | Search, open, and read primary sources relevant to the implemented methods and claims. | Verified references, equation/page locations, assumptions, applicability, disagreements, and testable predictions. |
| Independent challenger | Recheck consequential findings, source interpretation, reproductions, and final coverage. | Confirmed or rejected findings, unresolved uncertainty, and qualified readiness judgments. |

Assign these responsibilities to independent reviewers where possible. Exchange
saved research notes, source material and execution records explicitly, and
return literature findings to the code reviewer for implementation-level
verification. Record the inspection and research tools actually used.

Built-in diff review is supplemental. Selecting uncommitted changes, a commit,
or a branch diff does not establish whole-repository coverage. Include unchanged
implementation, compatibility surfaces, experiments, and scientific notebooks.
Do not manufacture a source diff merely to make existing code reviewable.

After the initial inventory, independent reading and literature work can run
in parallel. Numerical execution remains serialized under section 7. Avoid
giving every researcher the entire repository history. Give each a bounded
model family, implemented equations, relevant selectors, and open questions.

Use this evidence chain throughout:

`scientific claim -> model/assumption -> implementation -> primary reference -> independent check -> observed result -> qualified conclusion`

Return ambiguous or conflicting literature findings to the local reviewer.
Run a bounded distinguishing test where useful. Tests passing and references
agreeing are separate pieces of evidence; neither substitutes for the other.

## 4. Phase A: Establish identity, scope, and coverage

1. Record HEAD, branch, dirty state, relevant untracked inputs, environment,
   dependencies, optional packages, hardware, thread settings, and resource
   policy. Identify source imports and any installed-package shadowing.
2. Inventory modules, public entry points, backends, execution modes, profiles,
   configuration/schema versions, resources, experiments, notebooks, legacy
   adapters, tests, and packaging/CI boundaries. Follow actual paths rather
   than assuming experiments live at the repository root.
3. Classify canonical implementation, backend alternative, compatibility
   adapter, experimental capability, analytical study, and historical evidence.
   A large file or similar function name is not sufficient evidence of debt.
4. Create a coverage matrix. Every inventoried area needs a review status,
   responsible reviewer, model/claim links, test status, and any exclusion.
   Distinguish inspected, mathematically reviewed, independently tested,
   tested only through existing suites, unavailable, and not reviewed.
5. Save available historical test and experiment evidence with its producing
   revision and environment. Do not report inspected logs as fresh execution.
6. Check current limitation entries against actual code, including all sixteen
   existing IDs. Record corrections in the audit report; do not edit the
   limitations document during this assignment.

Read current architecture, validation, provenance, reproducibility, and model
documentation as claims to verify. Include benchmark source/assumption ledgers,
the resource manifest, experiment protocols, and the latest development status.
Older plans are historical context rather than execution instructions.

## 5. Phase B: Scientific workstreams

Expand this initial matrix from the actual inventory. Do not omit a module
merely because it is outside the main physical-camera demonstration.

| Workstream | Required questions and independent checks |
| --- | --- |
| Wavefront conventions, geometry, modes, and atmosphere | OPD/phase units and wavelength ownership; pupil/modal normalization; atmospheric PSD amplitude, structure functions, finite grids, subharmonics, frozen flow, translation, layered profiles, periodic reuse, and convergence domain. |
| Shack-Hartmann optics and sampling | Geometric slope versus image centroid; FFT/batched FFT/MFT and HCIPy conventions; tilt/diffraction oracles; focal/pupil/pixel quadrature; wavelength scaling; finite windows, partial illumination, contamination, spot identity, and zero-flux behavior. |
| Photometry, cameras, processing, and uncertainty | Photon/electron/ADU conversions; spectrum and throughput assumptions; QE and noise-stage ordering; CCD/EMCCD/CMOS, gain/maps/ADC/saturation; raw/oracle/estimated processing; realized masters versus calibration ensembles; covariance support and low-SNR/nonlinear limits. |
| DM, calibration, and reconstruction | Synthetic influence functions versus sparse spline basis; OPD versus surface factor of two; null modes; finite-difference linearity; grouped-local prerequisites; dense LS/TSVD/Tikhonov versus sparse LSMR objectives, damping units, masks, rank, stopping, and refusal conditions. |
| Time-domain control, exposure, and recovery | One latency owner; command acknowledgement and increment order; exposure integration; leak and queued commands on rejected frames; controller stability; default versus recovery paths; dropout, reset, and actual reacquisition evidence. |
| Science propagation and image metrics | Fourier and flux normalization; angular grids and cropping; peak versus on-axis Strehl; Marechal applicability; FWHM; wavelength integration; intensity-based exposure averages; numerical convergence versus physical validation. |
| Experiment design and analytical studies | Error-budget attribution; proxy versus physical disturbances; seed/burn-in/ensemble design; paired noise isolation and uncertainty; inverse-photon-law departures; TIPTOP assumptions and completion terms; experimental PWFS scope and validation. |
| Engineering, provenance, and computational scaling | Ownership/coupling; API/schema/serialization compatibility; RNG domains and replay; calibration/cache/attestation identities; source ledgers; installed packaging and optional dependencies; sparse/streaming claims; memory lifetimes and runtime accounting. |

Important existing review boundaries to recheck include:

- Fixed detector geometry versus changing a numerical crop or optical axis;
  fixed lenslet assignment versus detection, tracking, and reassignment.
- Simulator-truth clipping diagnostics versus quantities available to a real
  detector-data estimator.
- Recovery already implemented in current code versus claims inherited from
  older documentation; damping effects versus resets that actually occurred.
- Conditional covariance-v2 semantics versus older uncertainty descriptions.
- Absolute dense damping versus relative sparse damping conventions.
- Historical 2 m/12 m noise-law departures and their stated uncertainty;
  an accurately reported failed hypothesis is not a software defect.
- Historical 42 m E5 evidence versus current-code validation and ensembles.
- The raw-readout pedestal fix at `62c0092` and claim correction at `f09eb16`.
  A historical reproduction that asserts the former defect must be adapted
  in an audit-owned copy to test corrected behavior. Do not modify the original
  historical record or declare the closed issue open without a fresh regression.

These are review questions, not predetermined findings. Verify their current
status before drawing conclusions.

## 6. Phase C: Literature protocol

For each consequential model, algorithm, parameter source, and scientific claim:

1. Start from the implemented equations, conventions, selectors, and intended
   use. Form a precise research question rather than requesting a generic AO
   survey. Search existing bibliography and source ledgers before expanding.
2. Prefer original papers, original instrument/design documents, mathematical
   algorithm papers, and official implementation documentation. Separate
   method authority, parameter authority, and actual hardware calibration.
3. Open and read the relevant source. Search snippets and abstracts alone
   cannot establish equation-level agreement. Follow cited original sources
   where an intermediate source makes a consequential claim.
4. Record title, authors, year, DOI or stable URL, version, relevant section/
   page/equation, access status, and the specific claim it supports.
5. Compare units, normalization, statistical assumptions, boundary conditions,
   domain of validity, asymptotic limits, and relevant numerical adaptations.
   A formula difference may be a convention or deliberate approximation;
   explain the transformation before classifying it as an error.
6. Seek counterevidence, known failure regimes, and practical alternatives.
   Record disagreements and evidence quality. Do not replace a current method
   or silently expand the project's scientific scope during the audit.
7. Mark inaccessible full text, secondary-only support, uncertain attribution,
   and unsupported parameter choices explicitly. Do not invent citations,
   equation numbers, measurements, or claims of having read a source.
8. Write a research note per model family. The local reviewer must verify
   whether each literature conclusion actually applies to the inspected code
   and supported configuration before incorporating it into the report.

Reconcile conflicting source-ledger entries rather than copying them. Preserve
separate historical telescope designs and current telescope specifications.
Do not treat two backends sharing an assumption or implementation as fully
independent physical validation.

## 7. Phase D: Testing and resource policy

Declare a test plan with scope, expected cost, output destinations, and the
claim each test can establish. Proceed with authorized bounded checks without
repeated confirmation. Keep required coverage gaps visible.

| Tier | Work and reporting requirements |
| --- | --- |
| T0: Static and provenance | Collect tests; inspect architecture/imports, schemas, hashes, ledgers, units, supported options, lint and type checks. Use non-writing tool modes. |
| T1: Deterministic independent checks | Reuse meaningful existing fixtures and add audit-owned minimal oracles/reproductions. Cover analytic limits, invariants, masks, signs, zero flux, maps/ADC, timing, and unsupported combinations. Expected values must not merely repeat the implementation. |
| T2: Bounded native regression | Run the feasible native non-slow, non-HCIPy, non-ELT selection, serially or in recorded batches. Record collection and node IDs, deselection, skips, expected failures, unexpected passes, failures, and exit codes. |
| T3: Targeted stochastic and optional checks | Run relevant bounded Monte Carlo, numerical-convergence, and available HCIPy checks. Predeclare seeds/sample sizes and statistical uncertainty. Treat supported-Python and optional analytical dependencies as separate coverage rows. |
| T4: Packaging and bounded cost measurements | Build/install in an isolated audit environment and run smoke checks outside the source checkout. Capture small matched build/calibration/loop costs and fresh-process RSS where feasible. |
| T5: Governed scale validation | Telescope-scale runs, expensive spectral studies, or long ensembles only when justified by a specific uncertainty and covered by live authorization and resource policy. Otherwise retain a concrete deferred verification item. |

An initial native selection is:

`.venv/bin/python -m pytest -q -m "not hcipy and not slow and not elt_scale"`

Inspect actual test configuration and output behavior before execution. This
selection alone does not establish complete coverage or authorize gated runs.
Choose additional focused suites from the current workstream and collection.
Historical test totals are context, not a required current collection count.

Run numerical jobs serially with native library thread limits of two, subject
to current instructions. Parallel literature reading is allowed; parallel
simulations and pytest workers are not the default. Do not bypass resource
guards. Past guard suspensions or run-specific enablements are not blanket
authorization for a new audit.

Ordinary small fixtures, bounded native checks, CI/2 m comparisons, and isolated
builds may proceed within active policy. Medium/12 m, any 42 m run, multi-seed
work estimated above thirty minutes, and expensive polychromatic studies need
the applicable live authorization. If missing, prepare the exact command,
configuration, seeds, options, estimated time/RAM, threads, and output path;
ask only for that missing authorization and continue independent work.

Do not rerun passing checks without new edits, a failure, or a specific
unresolved concern. Save full logs; pass concise results and failure details
between reviewers. Preserve strict expected failures and investigate changes in
collection or skips. Unavailable dependencies and refused/gated runs are not
passes. A fixed-seed regression is not an ensemble uncertainty estimate.

Test failures must be assessed against the model/interface contract and the
execution environment. Do not repair source, relax thresholds, update frozen
samples, or modify tests to achieve a green audit.

## 8. Phase E: Findings and independent challenge

Give each finding a stable ID. Keep type, severity, confidence, and evidence
status separate. Use at least these categories:

- Confirmed implementation defect.
- Scientific-model discrepancy or overclaimed interpretation.
- Documentation, citation, or parameter-provenance error.
- Validation gap or insufficient statistical/numerical evidence.
- Intentional approximation with a bounded validity domain.
- Engineering/refactoring debt without demonstrated numerical error.
- Environment or test-infrastructure limitation.
- Future capability outside current supported scope.

For an actionable defect, report exact current path/line, supported triggering
configuration, expected and actual behavior, independent rationale, minimal
reproduction, observed result, scientific/user impact, confidence, and proposed
follow-up. Assign P0-P3 priority with a concrete impact rationale. Suggestions
are not fixes performed during this audit.

The challenger must independently recheck consequential findings, their source
interpretations, and reproductions. Record confirmed, rejected, and unresolved
outcomes with reasons. Do not inflate consensus into proof or require a second
costly full simulation when a small oracle resolves the same question.

## 9. Required English deliverables

Keep one main report, supported by compact appendices and machine-readable
records in the audit directory. Suggested files:

- `PRE_REFACTOR_AUDIT_REPORT.md`: the cohesive final report.
- `AUDIT_STATUS.md`: current phase, completed work, gaps, and next actions.
- `entry_manifest.json` and `integrity_check.json`: reviewed identity and
  preservation evidence.
- `module_coverage.csv` and `claim_evidence.csv`: coverage and evidence chain.
- `literature_review.md` and `references.bib`: research results and references.
- `test_manifest.json`, `logs/`, `reproductions/`, and `independent_review.md`.
- `resource_estimates.csv`: current measurements, historical values, and
  explicit estimates with assumptions.

Equivalent structured formats are acceptable if all required fields survive.
The main report must be self-contained and cover:

1. Reviewed snapshot, objectives, methods, preservation result, and exclusions.
2. Scientific/engineering objectives and current capability boundaries.
3. Whole-repository architecture, module ownership, model and mode inventory.
4. Model equations, assumptions, units, dependencies, references, and validity.
5. Substantive comparison tables for similar functions or implementations:
   selection mechanism, common basis, numerical/physical differences, strengths,
   weaknesses, applicable regime, supported combinations, evidence, and cost.
6. Literature-to-code agreement and unresolved source/provenance questions.
7. Tests actually executed, independent checks, statistical/convergence
   evidence, historical evidence, unavailable checks, and coverage gaps.
8. Findings by type and priority, with independent challenge outcomes.
9. Memory/runtime measurements and estimates, including configuration, seeds,
   grids, wavelengths, telemetry, retention, threads, hardware, dependencies,
   repetitions/spread, and producing revision. Distinguish RSS, Python/native
   allocations, build/calibration, and loop timing without double counting.
10. Practical small/12 m/42 m and serial/parallel scenario costs. Clearly label
    `MEASURED_CURRENT`, `MEASURED_HISTORICAL`, `ANALYTIC_ESTIMATE`,
    `EXTRAPOLATED`, and `NOT_MEASURED`. Historical low-memory E5 results do not
    establish universal memory requirements or fresh current-code validation.
11. Separate scientific-claim assessment, software-correctness assessment,
    and readiness for cleanup/refactoring. Identify prerequisites, permissible
    independent cleanup, and work that should wait for a correctness repair.
12. Prioritized follow-up queues for defects, validation/research, and
    refactoring. Every item needs its evidence, success criterion, affected
    area, dependencies, and approximate resource category.
13. Verified bibliography with claim-specific links and unresolved access flags.

Use `PASS`, `FAIL`, `PARTIAL`, `NOT_RUN`, `NOT_AVAILABLE`, or a precise governed
status for checks. A model approximation is not a failed unit test. A reported
negative scientific result is not automatically an implementation defect.
An unavailable required check prevents an unqualified assurance claim.

## 10. Completion and handoff

The audit is complete when every inventoried area has a truthful coverage
status, the planned feasible checks and literature investigations are finished,
consequential findings have been challenged, protected inputs are verified,
and the English report and follow-up queues are coherent. Explicitly name
unavailable or governed checks and qualify conclusions accordingly. Do not
claim exhaustive testing of every parameter combination.

End each review checkpoint with a saved record: reviewed source identity, completed
scope, evidence paths, commands/results, open findings, pending research,
integrity status, and the next bounded task. On resumption, read this plan,
the checkpoint, and relevant source rather than reconstructing all history.

In the final response, link the report and key evidence, state the three
separate assessments, summarize the highest-impact findings and verification
limits, and confirm the preservation outcome. Stop at the audit handoff.
Any repair or cleanup requires a subsequent implementation assignment.
