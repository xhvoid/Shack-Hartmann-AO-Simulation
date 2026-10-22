# Repository Consolidation: Independent Review

> **Historical plan.** The work and its verification are recorded in the
> [execution record](CLEANUP_REFACTOR_STATUS.md). Current implementation and open work are described
> in the [technical reference](../technical_reference.md) and [roadmap](../roadmap.md).

Prepared: 2026-10-17, Europe/Berlin.

Companion assignment:
[cleanup and refactoring execution plan](repository_consolidation_plan.md).

This is the independent review assignment for the final cleanup/refactor, or
for a named intermediate ticket. Inspect the actual changed implementation and
evidence. Do not approve a result solely because the implementer reports green
tests, several reviewers agree, or the new structure looks tidy.

For an intermediate-ticket review, apply the requirements to that ticket and
its affected dependencies; mark future, out-of-scope deliverables
`NOT_APPLICABLE` with the reason. Do not demand a completed final reference
at an earlier checkpoint. The final review applies the full assignment.

## 1. Role, inputs, and allowed work

The reviewer assesses the implementation independently. Unless the user also
asks you to fix findings, do not change simulation source, tests, profiles,
accepted resources or the technical reference. You may create review reports,
small reproductions and logs in the review's caller-owned output directory.

Read applicable instructions and the execution plan. Obtain:

- the CLN-00 entry manifest, source/working-tree identities, saved scientific
  witnesses and profile/resource/API inventories;
- the actual final HEAD and any uncommitted implementing changes;
- the changed-file/old-to-new ownership map and execution status;
- `docs/technical_reference.md`, `docs/roadmap.md`, the updated limitations,
  supporting references and machine-readable evidence;
- test/build/benchmark commands and logs, not just their summarized totals.

Preparation baseline was `f09eb160223efc147cf1d3d3cd4f8857f44971a0`.
Use the actual execution baseline recorded at CLN-00. If it differs, inspect
the intervening changes; do not reset the checkout or review the wrong range.
Include uncommitted changes and relevant untracked implementation inputs.

The original raw-readout pedestal finding was fixed by `62c0092`; `f09eb16`
also corrected the README's noise-law claim. Preserve those fixes and their
regression cases. The older `580e83f` readiness finding is historical evidence,
not an unresolved defect unless you reproduce a regression on the reviewed tree.

Do not infer fresh permission for large runs from old logs or this review
assignment. Respect the active resource policy and existing per-run gates.
Proceed with small reproductions and in-scope bounded verification without
repeated permission requests. Prepare a concrete run and cost before asking
for any genuinely missing governed-run authorization.

## 2. Review procedure

### Step A: Establish the reviewed identity and scope

1. Record reviewed HEAD, dirty state, diff range, environment, changed files,
   reviewed tickets and untouched areas. Verify the entry manifest exists.
2. Distinguish structural changes, editorial changes, bounded correctness
   repairs, generated artifact updates, and new numerical behavior.
3. Verify unrelated user changes and historical resources were preserved.
   Old plans must not have been used to delete intentional compatibility
   surfaces or reimplement an already-complete migration.
4. Check claims of completed gates against the exact code and environment
   that produced each log. A checkout with different dependencies/source is
   not the same validation target.

### Step B: Review responsibilities and dependency changes

1. For each extraction, identify the previous and new owner. Verify it reduces
   real coupling/duplication without creating parallel physical engines,
   another workflow framework or unnecessary abstraction.
2. Inspect import cycles, optional-backend import timing, public re-exports,
   registry/attestation singleton ownership and runtime state lifetimes.
3. Inspect dataclass module/schema identities, field order/defaults, class
   identity and exception/public signature compatibility. A re-export must
   not accidentally manufacture a different class with the same name.
4. Compare source-derived architecture diagrams and ownership checks to actual
   imports. A revised diagram cannot justify deleting an architectural test.
5. Verify scripts remain entry points rather than required runtime dependencies
   of an installed package. Check portability outside the checkout.

### Step C: Challenge scientific and behavioral preservation

Check the following boundaries directly in source and with focused witnesses.
Choose independent expected values and adversarial configurations; profile
regression alone does not cover every supported camera/model option.

| Boundary | Required checks |
| --- | --- |
| Units and signs | OPD/phase wavelength ownership; command OPD versus surface displacement; factor of two once; residual sign; geometric-slope versus centroid-pixel units. |
| Layouts and invalid measurements | Stable IDs/order; calibration/runtime/finite row intersection; NaN/mask semantics; no invalid-to-zero conversion; zero optical flux exceptions remain distinguished from ordinary invalid centroids. |
| Randomness and replay | Same domain derivation, keys, scopes, draw order and map/master lifetime; reset and realization replay; changing one noise domain must not perturb others. |
| Configuration codecs | All available versions map/round-trip identically; scientific/nested hashes unchanged; missing/unknown fields and invalid combinations still reject. |
| Calibration and supplied systems | Matrix/response/layout identities, verified cache reuse, component attestation, noisy versus noiseless compatibility, and rejection of substituted/stale state. |
| Dense versus sparse reconstruction | Objective and damping units; masked/rank behavior; grouped locality/noiseless prerequisites; LSMR stopping and refusal policies; no hidden dense conversions. |
| Timing and recovery | One delay queue; queued increments and leak on rejected frames; projection/gain/controller/decay/DM/ack order; supervisor reset; default path unchanged. |
| Camera ordering | QE once; source/sky/dark/CIC placement; multiplication and excess noise; coupling versus read noise; nonlinear response; pixel/register/ADC saturation. |
| Raw/oracle/estimated processing | Gain-map and offset scaling with ADC on/off; actual master presence and frame counts; internal source versus operating observation; bad-pixel policy and conditional means. |
| Uncertainty | Covariance-v2 Jacobian about the fixed realized-master mean; separate calibration ensemble; shared dark/flat covariance; threshold/clipping/nonlinear/low-SNR support flags. |
| ADC and CMOS maps | Read-noise dither participates in reference response identity; lower and upper code headroom; mapped read-noise effects; nonlinear validation uses the realized domain. |
| Exposure sampling | Intensities averaged before one camera draw; DM held; one-sample compatibility; frame RMS remains the labelled first-sample metric. |
| Science | Full-field flux normalization and crop denominator; peak/on-axis distinction; no average-OPD exposure; no index-wise addition across incompatible angular grids. |
| Evidence runner | Shared identity validated for every retained arm; per-run configuration matching; no stale/no-op success, mixed revisions or accidental overwrite; truthful refusal records. |
| Paired noise study | Same atmosphere, maps/masters, calibrated response and declared gate protocol; operating expectation rather than internal-source shortcut; residual-map variance estimator and finite-sample uncertainty preserved. |

Use the saved independent reproductions and meaningful regression fixtures for
previous R1-R7, S1-S3 and the analog CMOS raw-readout issue. Do not copy a
formula from the function under test and call the result an independent oracle.
Some historical scripts deliberately assert that the old defect exists.
Preserve those originals, reuse their fixture in a separate copy, and assert
the required corrected behavior; an old failure-assertion firing on fixed
code is not itself a regression.
For stochastic tests, inspect the sample size, uncertainty and regime rather
than weakening a tolerance until a test passes.

When reviewing recovery/profile claims, distinguish damping, reset and gain
effects. A reset mechanism's presence does not prove it caused the recorded
improvement. A heuristic `lost_lock` flag based on final residual/open-loop
comparison does not by itself establish successful acquisition when there
were no usable measurements. Check the surrounding validity and reconstruction
telemetry before accepting the narrative; do not silently redefine stored
metrics during structural cleanup.

### Step D: Audit the technical reference as an engineering deliverable

The result must include one cohesive English `docs/technical_reference.md`.
It must explain the final implementation without requiring the reader to
reconstruct development history across dozens of tickets.

Check that the reference contains:

1. Scientific purpose, engineering scope, non-goals, units/sign/time dictionary,
   actual module ownership, dependency and data/calibration flows.
2. Model equations or sufficient algorithmic descriptions, inputs/outputs,
   configuration selectors, assumptions, lifecycle and state ownership.
3. Comparisons with **advantages and disadvantages**, supported scope,
   limitations, dependencies, validation, cost and selection guidance for all
   eleven method families in execution section 7.2.
4. A valid-route/unsupported-combination matrix and bounded run examples for
   native, optional HCIPy, compatibility/physical camera and dense/sparse paths.
5. Distinct static/single/layered atmosphere models, geometric/FFT/MFT/HCIPy
   sensing, camera/processing/centroid alternatives, dense/sparse calibration
   and solvers, recovery policies, science estimators and analytical studies.
6. Model-to-source and claim-to-evidence tables. A method citation must not
   be used as proof of arbitrary preset values or laboratory calibration.
7. A current limitations account preserving the author's fixed hardware,
   ROI/alignment, spot loss/identification, simulator-truth clipping and
   invalid-frame concerns, with default versus opt-in recovery distinguished.
8. Complete resource tables, formulas and measurement qualifications from
   execution section 8, plus source/dependency version information.
9. A bibliography with primary-source locators and truthful verification states.
   Verify important claims against original sources where access permits.

Check substance, not just presence of headings or table rows. Look for false
equivalence between different models, missing assumptions and tables whose
advantages/disadvantages are generic adjectives unsupported by implementation.

Specifically reject these misleading claims:

- Physical-camera HCIPy parity, LGS/tomographic/scintillation capability,
  validated PWFS closed-loop capability or hardware calibration that does
  not exist in the implementation/evidence.
- Treating native isolated lenslet spots as a global spot association model,
  or fixed HCIPy detector blocks as validated tracking/reacquisition.
- Calling known optical capture fraction a detector-only observable.
- Presenting the historical 42 m single realization as validation of the
  final refactored code, a multi-seed ensemble, or an ESO instrument replica.
- Treating failed pure inverse-photon scaling as a pass, omitting recorded
  unexplained departures, or equating total RMS differences with a cleanly
  isolated detector-noise variance estimator.
- Combining conflicting ESO R1/R3/R4 cases, or presenting the historical
  42 m design as the present telescope specification.
- Confusing a weighted mean of scalar metrics with a broadband/long-exposure
  image, or using Maréchal estimates outside their declared interpretation.
- Claiming the TIPTOP fitting-tail adapter is an unmodified upstream prediction
  or a demonstration of time-domain MCAO controller stability.

### Step E: Audit runtime and memory estimates

1. Recompute representative analytical byte counts from actual shapes/dtypes
   and inspect simultaneous lifetimes. Look for hidden `.toarray()` calls,
   full-pupil masks/influence stacks, result copies and retained frame cubes.
2. Check streaming PSF claims against command/mask histories. A streamed PSF
   does not make total loop memory independent of frame count.
3. Check paired experiments and serial-ensemble lifecycle overlap. Distinguish
   one isolated run, two live twins, sequential runs and concurrent workers.
4. Verify performance records use the stated grid, batch, detector sampling,
   wavelength/exposure nodes, telemetry and atmosphere storage settings.
   E5 used summary telemetry and regenerated bands; defaults differ.
5. Verify sensor-only, build/calibration, steady-frame, science and whole-run
   times are not interchanged or double-counted. Inclusive build timings
   already contain calibration; science-inclusive loops already contain
   science propagation. Cache reuse and cold construction are distinct.
6. Check fresh-process versus cumulative `ru_maxrss`, RSS/group scope, units,
   sample interval, uncertainty and unavailable memory probes. Unknown is
   not zero and a theoretical buffer sum is not a measured RSS peak.
7. Check labels `MEASURED_CURRENT`, `MEASURED_HISTORICAL`,
   `ANALYTIC_ESTIMATE`, `EXTRAPOLATED`, `NOT_MEASURED`. A current commit
   containing an old JSON does not make the JSON a current-code measurement.
8. Check before/after small benchmarks have matched conditions, repeats and
   noise estimates. Investigate repeatable regressions above the agreed
   threshold; do not justify them by changing physical inputs.
9. Check serial five/ten-run estimates do not multiply peak RAM by the total
   seed count, and parallel estimates include live workers, CPU/bandwidth
   contention and engineering headroom.

An unchanged old figure can be valid historical evidence. It cannot replace
required current before/after bounded measurements. An unavailable governed
run can remain deferred when the claim is explicitly scoped; do not demand
an expensive rerun just to populate a cosmetic table cell.

### Step F: Verify tests, packaging, and evidence governance

- Inspect actual test selections and collection changes. Missing assertions,
  renamed-away tests, weakened tolerances and newly skipped failures need
  justification independent of the implementation's desired outcome.
- Check meaningful targeted fixtures for moved boundaries, one final native
  non-slow/non-HCIPy/non-ELT suite, affected slow oracles, lint/types,
  profiles/resources, documentation contracts and link checks.
- Inspect a built wheel/sdist and portable outside-checkout smoke evidence.
  Editable tests with `PYTHONPATH=src` do not establish wheel portability.
  Verify preserved public imports, optional lazy dependencies and resources.
- Distinguish local checks from CI lanes and unavailable environments. No
  unsupported minimum-Python or optional-backend claim may be inferred from
  a single local environment.
- Compare accepted resources, baseline payloads, schema headers and witnessed
  scientific outputs with CLN-00. Baseline candidates do not accept themselves;
  a reviewer recommendation does not confer publication authority.
- Check ordinary runs use caller-owned outputs and cannot overwrite historical
  evidence or accepted package resources.
- Preserve legacy aliases while release/time removal boundaries remain unmet.

Do not rerun every historical expensive experiment. Select checks according
to the changed boundary and existing same-revision evidence. State what you
ran yourself versus inspected from logs. No silent validation gap may be
presented as a passed check.

## 3. Finding quality and severity

Report only actionable findings supported by source, a concrete failure path,
a reproduction or a clearly missing required artifact/check. Avoid speculative
style complaints. A large file by itself is not a correctness finding.

For each finding include:

- stable review ID and severity P0/P1/P2/P3;
- exact file/function and current line(s), or the precise missing deliverable;
- triggering configuration and expected versus actual behavior;
- reproduction or concrete supporting evidence;
- scientific/engineering impact and affected claim;
- whether it is introduced by this refactor, pre-existing but newly discovered,
  a documentation mismatch, or an explicitly retained limitation;
- the smallest useful correction and verification required to close it.

Priorities:

- **P0:** destructive or universally unusable behavior requiring immediate stop.
- **P1:** serious scientific/identity/compatibility corruption or an important
  routine path failing without an acceptable documented boundary.
- **P2:** a reproducible supported edge-case defect, materially misleading
  technical claim, missing required comparison/evidence, or unsafe preservation
  gap that should be fixed before this assignment is signed off.
- **P3:** lower-impact clarity/maintainability improvement without a material
  correctness or required-deliverable consequence.

A documented unsupported feature is not a defect merely because it is absent.
A failed scientific hypothesis accurately reported as a failure is not a
software bug. An in-scope supported numerical defect cannot be dismissed as
"cleanup only" or hidden by calling the affected input unsupported after fact.

## 4. Reviewer output and decision

Write `review.md` under the caller's run/review output directory. Keep it in
English, and include:

1. Reviewed source/dirty identity, baseline, scope and method.
2. Findings in severity order, with reproductions and links to saved evidence.
3. A requirement matrix covering CLN-00 through CLN-10 and the technical
   reference/comparison/bibliography/resource obligations: `PASS`, `FAIL`,
   `NOT_RUN`, or justified `NOT_APPLICABLE` for each.
4. API/profile/resource/witness preservation results, tests/builds/benchmarks
   actually run versus inspected, and meaningful skipped/unavailable checks.
5. Retained scientific limitations and separately deferred gated experiments.
6. One explicit overall decision:

| Decision | Meaning |
| --- | --- |
| `PASS` | Scoped implementation, required deliverables and required software checks are complete; no unresolved in-scope P0/P1/P2 finding. This is not universal model validation. |
| `PASS_WITH_DECLARED_VALIDATION_LIMITS` | Software/refactor and documentation obligations pass; named governed scientific/scale checks remain explicitly deferred and no corresponding stronger claim is made. |
| `CHANGES_REQUIRED` | An in-scope actionable finding or a required deliverable needs correction. |
| `INCOMPLETE_REQUIRED_CHECKS` | Required software verification cannot be established; identify exact unavailable checks and their impact. |

If there are no actionable findings, say so plainly and explain reviewed
coverage and limitations. Never manufacture a finding to avoid a clean review.
After fixes, recheck affected findings and update their disposition without
rewriting the original reproduction/history. An old report remains an old
report; append closure evidence with the new source identity.

The final response to the implementing lead/user must make the decision,
remaining required work and scope limits clear. Do not merge, publish, accept
a baseline, delete compatibility code or start a scientific expansion as part
of this independent review.
