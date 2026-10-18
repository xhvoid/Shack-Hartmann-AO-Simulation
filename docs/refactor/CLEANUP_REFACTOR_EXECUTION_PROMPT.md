# Repository Consolidation, Refactoring, and Technical Reference: Execution Prompt

Prepared: 2026-10-17, Europe/Berlin.

Baseline inspected when preparing this prompt:
`f09eb160223efc147cf1d3d3cd4f8857f44971a0` (`f09eb16`).

Repository: `xhvoid/Shack-Hartmann-AO-Simulation`.
Preparation checkout: `/Users/xuhan/Documents/AO Simulation`.

This is an executable assignment for the implementing agents. Complete the
tickets, verification, technical reference, and independent review described
below. Do not stop after producing another plan. Execute only when the user
assigns this prompt as an implementation task; preparing this file does not
itself start the refactor.

The companion [independent review prompt](CLEANUP_REFACTOR_REVIEW_PROMPT.md)
defines the separate review assignment and acceptance decision.

## 1. Objective and completion boundary

Consolidate the existing modular simulation into a clearer, maintainable
research repository while preserving its scientific behavior and compatibility
contracts. Deliver one cohesive English technical reference explaining the
**final implementation**, not just the historical development process.

The work must improve ownership, experiment reproducibility, discoverability,
and scientific traceability. A large diff, more abstraction, shorter files,
or fewer tests is not an acceptance criterion. Do not redesign functioning
physics merely because another formulation looks cleaner.

The scientific purpose to make explicit is:

> Under declared atmosphere and instrument assumptions, characterize how
> Shack-Hartmann sensing, detector response, calibration, reconstruction,
> control, and measurement failure propagate into residual wavefronts and
> science-image quality.

Separate this purpose from software delivery, scale demonstrations, analytical
MCAO studies, and future laboratory/on-sky validation. Identify which research
questions the current implementation can actually answer.

### Required deliverables

| Deliverable | Required location | Purpose |
| --- | --- | --- |
| Durable execution record | `docs/refactor/CLEANUP_REFACTOR_STATUS.md` | Ticket status, decisions, before/after evidence, review findings, and remaining work. |
| One cohesive final technical reference | `docs/technical_reference.md` | Models, modules, modes, architecture, assumptions, limits, dependencies, citations, comparison tables, and resource estimates. |
| Focused current roadmap | `docs/roadmap.md` | Scientific questions, engineering tasks, evidence gaps, priorities, costs, and explicit completion criteria. |
| Updated limitations register | `docs/current_limitations.md` | Current scope and unresolved issues; preserve existing LIM identifiers and author-raised concerns. |
| Machine-readable audit evidence | `outputs/cleanup_refactor/<run-id>/` | Baseline inventories, comparisons, benchmark records, test logs, and review artifacts. Ordinary outputs must not overwrite governed resources. |
| Independent final review | `outputs/cleanup_refactor/<run-id>/review.md` | Reviewer decision using the companion prompt, with actionable findings and checked limitations. |
| Necessary implementation and regression changes | Existing package/test/documentation locations | Justified extractions, compatible facades, focused tests, updated imports and documentation. |

The technical reference must be readable as one document. Supporting evidence
may remain in linked JSON, logs, older component notes, and external primary
sources. A page consisting mainly of links to those documents is insufficient.

## 2. Current state: do not restart an obsolete migration

At the preparation baseline:

- `shwfs_ao` is already namespaced and modular. Core contracts, native and
  optional HCIPy optics, detector/WFS separation, calibration, one shared
  closed-loop engine, science propagation, I/O, and validation already exist.
- The scalable native path already has compact lenslet geometry, a sparse
  local DM operator, grouped calibration, sparse LSMR reconstruction, and
  streamed long-exposure PSFs.
- Physical CCD/EMCCD/CMOS cameras, MFT pixel integration, diffusion,
  electronic coupling, spectral sensing, estimated calibration products,
  covariance propagation, and finite-exposure sampling are implemented.
- `control/recovery.py` is an implemented opt-in supervisor. Default control
  and the optional decay/reset, subset fallback, and gain scheduling paths
  have different behavior. The controller remains the sole latency owner.
- `det_emccd_12m_medium_derived@3` is published. Its improved faint-end
  behavior depends on changed damping; do not attribute all improvement to
  reset. Preserve development/evaluation distinctions and held-out seeds.
- The current uncertainty identifier is `detector_covariance_v2`.
- `62c0092` fixed the analog raw-readout pedestal with a nonuniform CMOS
  gain map. `f09eb16` made the README's noise-law departures explicit.
  These are closed issues, not new features to reimplement.
- The recorded post-fix native regression is 2151 passed, 18 skipped, and
  two expected failures, plus 16 slow detector tests. These are historical
  counts for that selection/environment, not a license to force future
  test counts or claim that a new checkout has already passed.
- `high_order_10m_geometric@3` and `high_order_10m_hcipy@3` retain documented
  unstable controller settings and strict expected-failure guards.
- The 42 m E5 noise-on result is one realization from before the review
  corrections. Its current-code rerun is explicitly deferred. Never relabel
  that evidence as a run of the cleanup's baseline or final HEAD.
- The 12 m pure inverse-photon-law criterion failed as recorded. Read noise,
  CIC, and unexplained normalized departures remain part of the result.

The preparation working tree also had a modified `docs/README.md` and three
untracked documents: `AO_REFACTOR_MASTER_TICKETS_REVISED.md`,
`docs/current_limitations.md`, and `docs/repository_optimization_ticket.md`.
Preserve their contents. This list is a preparation snapshot, not the expected
complete status of a later execution checkout.

`AO_REFACTOR_MASTER_TICKETS_REVISED.md` and the older optimization ticket
describe earlier repository states. Use their surviving contracts and history;
do not execute their obsolete implementation backlog as though it were current.

## 3. Read first and establish authority

Read applicable `AGENTS.md` files and inspect current source before editing.
Resolve these repository-root-relative documents in the execution checkout:

1. `README.md`, `docs/README.md`, `docs/architecture.md`, `docs/backends.md`.
2. `docs/validation.md`, `docs/reproducibility.md`, `docs/provenance.md`,
   `docs/artifact_schemas.md`, `docs/migration.md`, `DATA_LICENSES.md`.
3. `docs/detector_model.md`, `docs/eso_scao_benchmark.md`,
   `docs/eso_elt_turbulence_model.md`, `docs/current_limitations.md`.
4. The summary and final review/closure sections of
   `docs/refactor/DETECTOR_LEVEL_DEVELOPMENT_STATUS.md`, then the specific
   evidence sections relevant to each ticket. Distinguish dated history
   from the latest accepted state.
5. `docs/refactor/AO_REF_000_COMPATIBILITY_CONTRACT.md` and the relevant
   component contracts, especially AO-REF-007 through AO-REF-017.
6. `pyproject.toml`, `.github/workflows/ci.yml`, scheduled validation,
   `tests/wheel_smoke/manifest.json`, and the packaged deprecation inventory
   and clock.
7. `docs/notebook12_tiptop_portfolio_notes.md`,
   `notebooks/studies/tiptop_support.py`, and the study's validation JSON.

Read source-ledger and assumption-ledger records, not just prose summaries:

- `src/shwfs_ao/resources/benchmarks/eso_scao_source_ledger.v1.json`;
- `src/shwfs_ao/resources/benchmarks/eso_drm_42m_scao_derived.assumptions.v2.json`;
- `src/shwfs_ao/resources/benchmarks/detector_source_ledger.v1.json`;
- `src/shwfs_ao/resources/benchmarks/detector_level.assumptions.v1.json`;
- the camera preset ledger, turbulence profiles, resource manifest,
  `deprecation_inventory.json`, and `deprecation_clock.json`.

User instructions govern scope. Current code, frozen contracts, and original
saved experiments establish different kinds of evidence: record a discrepancy
instead of silently declaring any one of them infallible. A historical green
test does not prove a physical assumption. A plausible paper does not prove
that a particular implementation follows it.

## 4. Non-negotiable preservation requirements

### 4.1 Physics, timing, and measurement semantics

Preserve all of the following during structural work:

- SI OPD in metres; phase explicitly tied to wavelength; existing pupil
  masking, piston/RMS treatment, coordinate directions and axis conventions.
- `residual = atmosphere - applied_DM_correction`, OPD-equivalent command
  units, and the reflective factor of two at its existing owned boundary.
- Stable lenslet, row, actuator and pixel identities, order, and masks.
  Invalid measurements remain explicit NaNs plus masks, not zero slopes.
- Existing regularization meanings. Dense Tikhonov `alpha` is absolute in
  matrix units; sparse LSMR `alpha` is dimensionless relative damping.
  Equal numeric values do not make these objectives equivalent.
- The sole controller latency queue, queued-increment behavior on rejected
  frames, leak, stroke/fault policies, and applied-command acknowledgement.
- The default recovery-free loop and opt-in supervisor order. Do not merge
  them into one silently changed default or clear queued increments as a
  cleanup convenience.
- Exposure averaging of optical **intensities**, camera noise applied once,
  held DM state, and the first-sample definition of frame residual metrics.
- Pixel/register/digital saturation order, EMCCD gain regime, QE ownership,
  PRNU/dead/hot pixel meanings, gain/offset maps, ADC dither, and calibration
  master protocols, including shared-master covariance.
- The raw-readout pedestal fix and the distinction between a deterministic
  internal calibration source and the operating-frame expectation used by
  paired noise studies. `include_noise=False` is not a universal synonym
  for the latter.
- Each science metric's meaning: RMS/Maréchal estimates, instantaneous peak
  ratios, wavelength-weighted scalar summaries, on-axis ratios, and metrics
  from intensity-accumulated long exposures must remain distinct.

### 4.2 Reproducibility, public API, and packaged data

- Preserve named random-domain derivation, scopes/keys, draw ordering,
  realization lifetimes, reset/replay semantics and existing seeded outputs.
- Preserve profile payloads, versions, scientific configuration hashes,
  response identities, row/layout hashes and resource bytes. Do not change
  a hash algorithm or remove identity fields to make an extraction pass.
- Moving a dataclass can change its qualified schema name, hash, serialized
  identity, or class identity. Inventory these dependencies first. Preserve
  existing field order/defaults and explicit schema identifiers, and use the
  same re-exported class object where compatibility requires it.
- Keep public imports, signatures, public exports, exception identities and
  meaningful failure behavior. Retain thin facades at existing public paths
  when moving internals. Do not maintain a second physical implementation.
- Preserve lazy optional HCIPy imports, supported Python versions, wheel
  resources and installed-package behavior. Do not add checkout-relative
  `sys.path` manipulation or new hard dependencies for convenience.
- Keep fast proxy, physical integration, cross-backend and detector evidence
  families semantically distinct. Preserve v2 readers/headers and additive
  schema behavior. Ordinary execution cannot accept a baseline.
- Source revision/patch, timestamps and measured runtime necessarily differ
  between executions. Compare these audit fields explicitly; do not demand
  identical audit metadata or broadly strip differences to hide a changed
  scientific result.
- Legacy adapters and root shims are intentional compatibility surfaces.
  Phase B removal requires both published release and time boundaries in
  the deprecation clock. Planned publication dates and elapsed calendar
  time alone do not satisfy them. Do not delete this surface in this cycle.

### 4.3 Scope exclusions

Do not add a new WFS, guide-star topology, camera family, controller design,
GPU/JAX backend, tomography, scintillation, global spot tracker, or instrument
digital twin as part of cleanup. Do not retune gains, damping, centroid gates,
exposure sampling or noise parameters. Keep TIPTOP/P3/MASTSEL as its own
analytical study rather than forcing it behind time-domain SCAO contracts.

If a new correctness defect is discovered, preserve a small reproduction and
classify it. Make a bounded correctness fix with a meaningful independent
regression test as a separate change unit before continuing the affected
extraction. Preserve historical outputs and explicitly describe any changed
claim. An unrelated scientific extension belongs in the roadmap.

The unchanged-identity/witness requirement applies to structural changes.
A separately reviewed correctness fix may legitimately change narrowly affected
scientific outputs or identities: enumerate those differences, retain before/after
evidence, and compare subsequent extractions against the corrected state.
Prepare a candidate and reviewed diff when governed baselines are affected;
never silently replace accepted resources or claim unapproved acceptance.

## 5. Agent coordination, permissions, and resource policy

- Use one integrating lead. Independent inventory, bibliography, cost analysis,
  and review may run in parallel. Assign exclusive file ownership for edits
  and integrate dependent changes sequentially. Do not let competing agents
  independently move the same configuration or factory code.
- Keep the scientific model and required outputs fixed while accepting useful
  implementation suggestions. Do not repeatedly ask the user to choose
  routine internal names or approve reversible, in-scope cleanup.
- No commit, push, tag, release, external publication or baseline acceptance
  without applicable explicit user authorization. Do not reset, stash away,
  or delete unrelated user changes, user-owned ignored outputs or historical
  evidence.
- Respect live instructions about resource guards. The recorded suspension
  and past per-run enablements are historical context, not blanket permission
  for fresh telescope-scale runs in a different task.
- Run numerical jobs serially by default, with native library thread limits
  of two. Do not run pytest workers and simulations concurrently merely
  because agent reasoning is parallel.
- Ordinary bounded tests, small fixtures, 2 m/CI comparisons and builds needed
  for this assignment should proceed without a new approval loop when within
  the active resource policy. Use existing estimates and supervision where
  applicable. Do not disable a guard just to turn a refusal into a pass.
- Medium/12 m, any 42 m run, a multi-seed batch estimated above 30 minutes,
  and higher-cost polychromatic studies remain governed runs. Before an
  unapproved governed run, prepare the exact configuration, seed(s), options,
  command, expected peak RAM, time, threads and output path. Seek only the
  missing concrete authorization and continue independent work meanwhile.
- A guarded or unavailable run is `NOT_RUN_RESOURCE_POLICY` or another precise
  not-run status. It is not a success, a new measurement or a reason to erase
  the required verification item. Distinguish software acceptance from the
  explicitly deferred scientific claim.
- Share progress and maintain the status record. Long jobs should use polling
  that allows progress updates; do not repeatedly rerun already passing checks
  unless edits, failures or unresolved concerns justify them.

## 6. Ticket sequence and acceptance gates

Use stable identifiers CLN-00 through CLN-10. Maintain status as `TODO`,
`IN_PROGRESS`, `IMPLEMENTED_REVIEW_PENDING`, `DONE`, or a specific deferred
verification state. A ticket is DONE only after its required acceptance
checks; an unexplained skip is not acceptance. Document dependencies and
checkpoints so another agent can resume without reconstructing chat history.

### CLN-00: Capture the actual entry state and behavioral contract

1. Record HEAD, branch, tracked/untracked changes, applicable instructions,
   Python executable, dependency/constraint versions, hardware and current
   resource policy. If HEAD differs from the preparation baseline, inspect
   the intervening diff and revalidate scope; do not reset to `f09eb16`.
2. Inventory public exports/signatures, configuration/schema identifiers,
   available profile names/versions, canonical resource hashes, accepted
   baseline hashes, and the deprecation state. Store machine-readable
   inventories under the run's output directory.
3. Distinguish canonical engine, adapter, backend alternative, numerical
   optimization, experiment wrapper, validation tool and archived material.
   Apparent duplication needs an ownership/semantics assessment before removal.
4. Establish small replay witnesses for representative default and physical
   camera paths, sparse reconstruction, recovery enabled/disabled, and the
   reviewed edge cases. Reuse suitable existing fixtures; do not invent a
   second simulator or large generated baseline cube.
5. Record available same-revision test evidence and gaps. Run affected entry
   checks when needed; do not claim another environment's run as your own.
6. Capture the bounded, same-host baseline benchmarks required by CLN-07
   before changing the relevant implementation. Alternatively preserve an
   isolated runnable baseline with its exact environment and uncommitted
   scientific inputs, and specify how it will be measured later. Historical
   timings from another revision cannot substitute for this before measurement.

**Acceptance:** the entry state is reproducible, user changes are preserved,
resource/API/scientific identity inventories exist, and there is a concrete
before/after comparison set. No unresolved entry failure is silently waived.

### CLN-01: Define scientific scope and documentation authority

1. Create `docs/technical_reference.md` with the full section/table outline
   required in section 7. Populate present capabilities and deferred scope
   from source and evidence before changing implementation.
2. Create `docs/roadmap.md` with separate scientific and engineering queues.
   Each item needs a question/problem, affected path, proposed experiment or
   change, evidence needed, success criterion, priority and cost category.
3. Reconcile all 16 existing limitation IDs with current code. In particular,
   update recovery, v2 covariance and completed detector acceptance; retain
   spot identity, fixed-hardware, simulator-truth and validation boundaries.
   Add new IDs only for genuinely new issues. Do not remove resolved history.
4. Classify older plans and execution logs as historical. Preserve contracts,
   links and evidence; add concise pointers instead of copying large logs.
5. Make README and `docs/README.md` lead to the current reference, roadmap,
   limitations and supported run routes. Keep current v3 evidence distinct
   from earlier v1/v2 outcomes.

**Acceptance:** a reader can distinguish current scope, historical evidence,
implementation status and unvalidated claims. No model change is hidden in
an editorial correction. Check documentation contracts and local links.

### CLN-02: Consolidate experiment protocol, identity, and output responsibilities

Inspect `scripts/run_detector_level_evidence.py`,
`experiments/detector_level.py`, `experiments/detector_noise.py`, and
`experiments/eso_scao_benchmark.py`.

1. Map responsibilities: experiment definitions, fixed protocols, run identity,
   code identity, source hashing, resume rules, result aggregation, timings,
   output selection and CLI parsing.
2. Extract reusable responsibilities only where they reduce actual coupling
   or duplication. Keep experiment-specific scientific definitions and
   baseline authorities separate. A small explicit protocol/result type is
   preferable to a new generic workflow framework.
3. Keep scripts as thin compatible entry points. Preserve options, default
   meanings, explicit output/overwrite behavior and machine-readable formats.
   The current detector evidence script defaults to
   `docs/refactor/detector_level_evidence`; `--output` selects a filename, not
   a directory. Add an explicit `--output-dir PATH` option while retaining
   the legacy default and filename semantics. Use the explicit caller-owned
   directory for all cleanup verification and recommended ordinary examples;
   keep the old default as a documented compatible maintenance route. Test
   both with temporary destinations, not historical evidence writes. Record
   output location as audit metadata without changing scientific identities.
4. Preserve validation of **every retained run**, including disjoint arms,
   against the shared code/frame/burn-in/execution protocol. Overlapping
   `(label, seed)` entries must also match their arm configuration.
5. Preserve refusal/error records, deterministic summaries and paired-study
   definitions. A resume that does no new work must be explicit. Never mix
   records from different code identities because summary values look close.
6. Use stand-in runners and temporary records to test orchestration. No large
   simulation is required to verify resume or output behavior.

**Acceptance:** focused evidence-runner and detector-experiment tests pass;
equivalent single-run and batch summaries agree; old valid records remain
readable; incompatible resume and accidental overwrite are still rejected;
explicit output-directory selection works, the legacy default remains
compatible, and all cleanup runs use their caller-owned destinations.

### CLN-03: Isolate configuration codecs and historical schema handling

Inspect `src/shwfs_ao/io/configs.py` and its consumers before choosing internal
boundaries. It currently contains domain records, nested/cross-field rules,
version handling, packaged-profile lookup, parsing and serialization.

1. Prepare an ownership/import sketch. Separate a coherent codec or historical
   schema responsibility when useful; do not split by arbitrary line count.
2. Keep `shwfs_ao.io.configs` and existing public re-exports compatible. Avoid
   introducing a new import cycle between domain records, codecs and factories.
3. Preserve strict unknown/missing-field behavior, schema versions 1-7,
   controller recovery pairing, detector neutral-block rules, window/sampling
   restrictions, and all response-affecting identity fields.
4. Compare every packaged profile's emitted mapping and scientific/nested
   hashes before/after. Include negative configurations and programmatically
   constructed configurations, not only shipped JSON files.
5. Run profile generators in `--check` mode. Ordinary cleanup must not
   regenerate or rewrite their published payloads or ledgers.

**Acceptance:** identical mappings, scientific hashes, class/public identity
where contracted, supported versions, and rejection behavior. Relevant I/O,
profile-ledger, recovery-config, resource and wheel checks pass.

### CLN-04: Clarify system assembly and calibration resolution

Inspect `experiments/scao.py`, both backend factories, calibration cache,
interaction calibration and supplied-system attestation.

1. Distinguish component assembly, backend registry selection, configuration
   conversion, matrix acquisition/reuse, response checks and run dispatch.
2. Extract justified internal responsibilities behind the existing public
   `ScaoSystem`, `build_scao_system`, `run_closed_loop`, and registration API.
   Retain one authoritative registry and attestation mechanism.
3. Preserve matrix/response/config/layout compatibility checks, cache content
   verification and refusal of substituted components, supplied systems or
   unverified calibration identities.
4. Preserve lazy optional imports and native/HCIPy unsupported-combination
   failures. A factory may not silently omit physical-camera stages.
5. Compare construction, verified cache reuse and repeated run witnesses.
   Preserve default recovery-free behavior and supervisor identities.

**Acceptance:** construction/attestation tests, calibration and control tests,
and affected native/backend tests pass. Same inputs select the same owned
components and generate the same scientific witnesses. A smaller file alone
does not establish completion.

### CLN-05: Review validation and artifact responsibilities

Inspect `validation/cross_backend.py`, `validation/regression.py`,
`validation/numerical_identity.py`, `io/artifacts.py`, and candidate/update
scripts. Identify real duplication between schema handling, witnesses,
comparison policy, report formatting, environment/source evidence and I/O.

1. Extract only coherent shared mechanics. Keep each baseline family's
   physical semantics, tolerances, authority and accepted resource separate.
2. Preserve v2/v3 readers, frozen headers, compatibility fields, sidecars,
   witness coverage and schema validation. Do not replace structured evidence
   with untyped dictionaries solely to ease file movement.
3. Retain candidate-versus-accept separation. Review references, explicit
   reasons and source/patch identities must not disappear from acceptance.
4. Compare representative reports and deliberate failures before/after.
   Differences in code revision and runtime are expected audit changes;
   differences in scientific verdicts are not a structural-cleanup allowance.

**Acceptance:** cross-backend/report/artifact and baseline-update guard tests
pass; accepted files remain byte-identical; a deliberately perturbed witness
is still detected and correctly attributed. If inspection finds no justified
extraction, document that decision and complete the ownership documentation
instead of manufacturing a refactor.

### CLN-06: Consolidate examples, notebooks, and repository navigation

1. Confirm canonical tutorials/studies use supported installed APIs. Preserve
   historical notebook outputs and the experimental/archived classifications.
2. Remove a demonstrated duplicate current calculation only when the canonical
   replacement preserves its units, assumptions, inputs and intended use.
3. Keep example output paths caller-owned and wheel-portable. Do not make
   `scripts/` a required installed runtime dependency.
4. Update imports, documentation diagrams, manifests and relevant portable
   tests for moved internals. The source-derived dependency/ownership checks
   should follow the true new graph without being weakened.
5. Inventory candidate generated/build/cache clutter. Delete only clearly
   reproducible generated clutter confirmed within scope; retain accepted figures,
   provenance, licenses, execution evidence, user files and migration history.
   Record what was removed or deliberately retained and why.

**Acceptance:** canonical smoke routes and their installed-wheel counterparts
remain usable, navigation is clear, archived material is not accidentally
executed, and no acceptance evidence has been discarded as clutter.

### CLN-07: Measure bounded performance and document resource estimates

Follow section 8. Capture same-host before/after construction and per-frame
costs on a representative small compatibility profile, physical camera profile,
and CI sparse path, with matched seeds, sampling, telemetry and thread limits.
Use fresh processes for per-run peak RSS when feasible.

Predeclare warmups and repeats; use at least three timed repetitions for a
small benchmark unless a documented cost reason prevents it. Report medians
and spread. A repeatable wall-time or peak-RSS regression above 10 percent
is a required investigation, not an automatic permission to change physics.
Retain the existing under-5-percent feature-off objective where that specific
comparison is applicable. Do not use noisy timing as a unit-test oracle.

**Acceptance:** measured and estimated values are distinguished; known
allocation owners and scaling formulas are documented; no unexplained
material regression is hidden. Gated runs not repeated remain labelled
historical or not run. Bounded tests may establish structural properties
without allocating full-size dense arrays.

### CLN-08: Finish the cohesive technical reference and bibliography

Complete every section/table in sections 7-9 using the final code layout.
Bind claims to exact implementations, configurations, evidence and model
references. Check every formula's units and every comparison's common basis.
Make current recommendations conditional on the experiment's purpose.

**Acceptance:** the technical reference independently explains all current
model families and execution modes, including alternatives and unsupported
combinations. All comparison and cost rows are populated; unknown values are
explicitly marked, not fabricated. References have truthful verification
states and support the particular claims to which they are attached.

### CLN-09: Independent adversarial review and bounded repairs

Assign the companion review prompt to a separate reviewer with the entry
manifest, changed-file map and evidence directory. The reviewer must inspect
source and test claims independently, including preserved edge cases.

Resolve in-scope findings with separate small change units. Rerun affected
checks, update the technical reference and status, and ask the reviewer to
recheck the changed finding. Do not repeatedly reopen unrelated scientific
extensions or endlessly rewrite already accepted sections.

**Acceptance:** no unresolved in-scope P0/P1/P2 finding, required evidence is
complete, and deferred model/scale limitations are accurately disclosed.
Reviewer approval is evidence, not permission to commit or accept baselines.

### CLN-10: Final verification and handoff

1. Run the affected focused suites after each change, then one complete native
   non-slow, non-HCIPy, non-ELT regression on the final tree, split into serial
   batches if needed. Preserve strict expected failures and investigate
   unexpected changes in collection, skips or assertions.
2. Run targeted slow detector Monte Carlo and other directly affected physical
   checks. Do not automatically launch all historical slow experiments.
3. Run lint/types, resource/profile consistency, documentation contracts and
   link checks, source/wheel packaging checks, and bounded canonical smokes.
4. Verify optional HCIPy and supported-Python CI lanes when available. Record
   exact unavailable lanes and required CI follow-up rather than claiming
   them passed locally.
5. Compare the final API/profile/resource/witness inventory to CLN-00.
   Accepted resource hashes and frozen numerical behavior must remain intact.
6. Complete the technical reference, current roadmap, limitations, status and
   independent review. Report changed responsibilities, validation, measured
   performance, unresolved boundaries and the next prioritized scientific task.

**Acceptance:** every required ticket is complete or has an explicitly named
unavailable required check. Do not label the cycle unconditionally complete
when required software checks are pending. Separately gated scientific work
may remain in the roadmap without blocking a scoped software sign-off.

## 7. Mandatory contents of `docs/technical_reference.md`

Use a table of contents and explain the actual final package. Detailed
supporting documents remain useful, but this file must provide the full
conceptual account, selection guidance, and limitations in one place.

### 7.1 Scope, goals, architecture, and dependency ownership

- Explain intended research questions, supported claims, non-goals, synthetic
  assumptions and the separation of educational, research, benchmark,
  compatibility and experimental use.
- Include final module-ownership and dependency diagrams, an end-to-end data
  flow, and a calibration/identity flow. Derive them from actual imports and
  result contracts; do not draw an idealized architecture absent from code.
- Include a module-ownership table with: package/responsibility, public entry
  points, inputs/outputs and units, dependencies, permitted dependency
  direction, lifecycle/state, limitations, and tests/evidence.
- Explain required versus optional software dependencies and tested versions,
  including native NumPy/SciPy paths, lazy HCIPy, the independent TIPTOP/P3/
  MASTSEL study, plotting/notebook/build tools and resource access.
- Include a units/sign/time dictionary and a measurement-to-command sequence
  explaining exactly when a sampled residual, delayed increment, applied DM
  command and science exposure are evaluated.

### 7.2 Method-family comparison tables

For **each** family below, provide a substantive comparison table. Use columns
such as implementation/mode, mathematical model and assumptions, available
backend/profile, advantages, disadvantages/failure modes, supported domain,
dependencies/references, computational/memory implications, validation and
recommended use. Split wide tables if needed, but preserve those comparisons.
Do not substitute a list of filenames for advantages and disadvantages.

1. **Atmosphere:** `static`, `native_frozen_flow`,
   `native_frozen_flow_v2`, `native_layered`, `hcipy`, `hcipy_layered`;
   historical RMS-scaled versus absolutely normalized models where relevant;
   finite/infinite screens, subharmonics, spectral coverage, frozen-flow
   translation, layer weights/winds, travel limits and periodic-band reuse.
2. **Wavefront sensing:** geometric slopes, compatibility detector SH,
   physical-camera SH and experimental PWFS. Record geometric
   `rad_wavefront_slope` versus centroid-pixel units, calibrated transfer,
   observability and the absence of validated PWFS closed-loop parity.
3. **SH optical implementations:** native local FFT, equivalent batched FFT,
   MFT pixel integration and HCIPy shared-field propagation. Compare nominal
   versus illuminated lenslet sampling, fixed windows, capture semantics,
   optical-axis conventions and inter-lenslet contamination assumptions.
4. **Sampling/integration modes:** FFT point sampling versus pixel quadrature,
   diffusion versus electronic coupling, mono versus polychromatic WFS,
   one atmosphere sample versus finite exposure subsamples. Separate an
   identity-neutral execution optimization from a changed physical model.
5. **Detector paths and camera families:** compatibility versus physical
   camera; CCD, high-gain EMCCD and CMOS. Explain photons/input electrons/
   output electrons/ADU, QE once, pre-register CIC, Gamma multiplication,
   excess noise, gain/read maps, bias, nonlinear response and three distinct
   saturation stages. Synthetic presets are not hardware datasheets.
6. **Pixel processing and centroid quality:** raw readout, oracle products and
   estimated bias/dark/sky/flat products; known versus flat-absorbed gain maps;
   operating observations versus internal calibration source. Compare plain
   and thresholded CoG, negative clipping/minimum subtraction, covariance-v2
   support gates and legacy uncertainty proxies. Explain conditional temporal
   variance versus the ensemble of persistent calibration errors.
7. **DM implementations:** dense Gaussian/compact-Gaussian/pyramid-like
   influences and the local sparse linear-spline operator. Compare basis,
   support/coupling, boundaries, active/zero-support actuators, stroke/faults,
   synthetic calibration and dense-allocation hazards. Do not describe
   different influence families as purely equivalent optimization modes.
8. **Calibration and reconstruction:** modal/actuator, forward/central and
   noisy repeated dense calibration; grouped-local noiseless sparse probes;
   LS, TSVD, dense Tikhonov and sparse LSMR. Explain the different `alpha`
   scales, rank/row masks, locality conditions, stopping policy and cache
   validation. Identify where grouped calibration is inapplicable.
9. **Control and recovery:** leaky integrator, integer latency and default
   rejection behavior; optional decay/reset, subset fallback with coverage
   gate, and gain scheduling. Explain the single delay queue and applied
   command acknowledgement. Do not claim that a valid-row fraction or a
   final-RMS heuristic alone establishes lock or successful reacquisition.
10. **Science propagation and metrics:** native FFT and HCIPy Fraunhofer,
    monochromatic PSFs, weighted scalar band summaries, broadband images if
    actually supported, and streamed long exposures. Compare peak/on-axis
    Strehl, RMS/Maréchal estimates, FWHM estimators and encircled energy.
    Include flux normalization, crop denominator, tip/tilt and finite-grid bias.
11. **Experiment approaches:** control-space proxy versus physical turbulence;
    time-domain SCAO versus the separate TIPTOP analytical MCAO study;
    component oracles, seeded regressions, cross-backend comparisons and real
    measurements as different evidence classes. Explain the fitting-tail
    completion and explicitly supported TIPTOP adapter branch.

In each family, distinguish currently implemented, retained for compatibility,
experimental, deliberately unsupported and future work. An algorithm merely
mentioned in a paper is not an available repository mode.

### 7.3 Mode compatibility and representative run selection

- Include a compatibility matrix across backend, WFS type, atmosphere model,
  dense/scalable DM, physical camera, calibration strategy, exposure sampling,
  recovery and science path. Use `SUPPORTED`, `REJECTED`, `EXPERIMENTAL`, or
  `NOT_VALIDATED`, with reasons and exact configuration selectors.
- Avoid a misleading all-combinations Cartesian promise: list important valid
  routes and explicit prohibited combinations derived from factory checks.
- Identify a small introductory/native route, the physical 2 m route, CI sparse
  route, current 12 m detector profile, historical 42 m benchmark and optional
  backend study. Provide actual commands or API examples with profile/version,
  overrides, output path, seed and expected cost category.
- Explain physical-model choices versus execution options. In particular,
  `lenslet_batch_size`, `atmosphere_band_storage`, and `telemetry_level` have
  their existing identity-neutral contracts; defaults are not automatically
  the low-memory E5 settings.

### 7.4 Assumptions, provenance, limitations, and evidence

- Include a model/assumption ledger table: assumption ID, exact meaning,
  source category, implementation/configuration, affected result, tested
  domain and unresolved uncertainty. Keep public inputs separate from assumed
  camera/controller/DM parameters and source-derived transformations.
- Include a claim/evidence table with configuration, revision, seed count,
  estimator, tolerance/confidence, result and limitation. Separate prediction,
  observation, physical validation, regression and reproducibility.
- Explain the author's fixed-detector/ROI concern, changing a simulated
  optical axis versus real alignment, spot loss/assignment, native isolated
  spots versus HCIPy fixed blocks, simulation-truth clipping versus observable
  diagnostics, zero optical flux exceptions versus invalid centroids, and
  recovery versus spot reacquisition.
- Preserve on-axis frozen-flow scope, absent scintillation/tomography/LGS
  propagation, synthetic hardware, experimental PWFS, HCIPy physical-camera
  exclusions, finite sampling and limited statistical independence.
- State the 12 m inverse-photon-law failure and the 2 m/12 m unexplained
  normalized drift. Preserve the current README's explicit departures.
- Keep profile-v1/v2 failures and v3 improvements tied to their actual
  parameters. A post-hoc configuration is not a predeclared prediction.
- Label historical 42 m results by their producing code and leave current-code
  reruns/ensembles pending unless they really run under this assignment.

### 7.5 References and implementation-to-source traceability

Section 9 defines the bibliography requirements. Every important physical or
numerical method must have a supporting primary source or be explicitly
identified as a repository assumption/derivation.

### 7.6 Runtime, memory, and practical execution guidance

Include the measured and estimated resource tables, formulas, measurement
methodology and scenarios in section 8. Explain what the present implementation
actually retains and where higher fidelity or more realizations increases cost.

## 8. Resource and performance reporting specification

### 8.1 Labels and metadata

Every resource number must be labelled `MEASURED_CURRENT`,
`MEASURED_HISTORICAL`, `ANALYTIC_ESTIMATE`, `EXTRAPOLATED`, or `NOT_MEASURED`.
Do not invent a measurement when an existing job was refused or a tool cannot
observe OS memory reliably.

For each measurement record profile/version, code identity and dirty state,
hardware/OS/architecture, Python and numerical-library versions, native
threads, root seed, realization, frame count/burn-in, pupil and focal grids,
retained lenslets/actuators, window/guard, quadrature and spectral nodes,
exposure samples, telemetry, atmosphere storage, noise/calibration mode,
cache state, repeats/warmup, and output destination.

Report construction/calibration, steady-loop per-frame and science/output
costs separately where measurable, as well as end-to-end wall time. Do not
present sensor-only timings as complete AO-loop timings. Separate CPU-active
time from wall time affected by host sleep or contention. Do not use the
historically sleep-inflated reset batch to claim policy overhead.

Explain RSS versus virtual memory, Python heap versus native allocations,
process versus process-group peaks, sample interval and unobserved short
peaks. `ru_maxrss` is a process-lifetime high-water mark; subsequent seeds in
one process do not have independent per-run peaks. Missing RSS is unknown,
not zero. Fresh subprocesses are preferred for per-run peak measurements.

### 8.2 Historical anchors to verify and carry forward with correct labels

These are starting points, not fresh measurements of `f09eb16` or the final
refactor. Verify each number against its saved record and keep its producing
configuration/revision attached.

| Path and configuration | Recorded cost | Source and qualification |
| --- | --- | --- |
| 2 m compatibility sensor, `fast_2m_detector@4`, feature-cost fixture | about 7.25 ms per noisy sensor measurement | `docs/refactor/detector_level_evidence/det10_feature_costs.json`; sensor-only, not full-loop time. |
| 2 m physical EMCCD, FFT, estimated products | about 6.83 ms per measurement | Same record; compare only matched fixture definitions. |
| 2 m MFT, k=4, diffusion/coupling, 1/3/7 wavelengths | about 10.18/13.51/20.69 ms per measurement | Same record; construction and optics work differ. |
| Noiseless ESO CI v2, 32 frames | 2.6 s, 130 MiB | `docs/eso_scao_benchmark.md` and its manifests; historical desktop run. |
| Noiseless ESO 12 m v2, 200 frames | 47 s, 301 MiB | Same source; this is not a physical-camera 12 m noise-on run. |
| Noiseless ESO full spatial scale v2, 20 frames | 110 s, 1.44 GiB | Capability demonstration, not a settled 2000-frame result. |
| Noiseless ESO 42 m reference v2, 2000 frames | about 62 minutes, 1.64 GiB | Verified calibration reuse; historical single realization. |
| Physical-camera 42 m E5, 2000 frames | 3541 s total, 27.4 s build, 1.749 s/frame, 1.61 GiB | `det09_e5_42m_noise_on.json`; root seed 1, 1008-pixel pupil, R3 three-node WFS, MFT k=2, summary telemetry, regenerated atmosphere bands, one 2.2-micron science wavelength. Predates review corrections. |
| 12 m physical E6 v3 controlled comparison | baseline about 0.163 s/frame; point/no diffusion 0.123; photometry-matched mono 0.122; oracle products 0.147 | Development status and v3 E6 record; retain each arm's complete changed settings. |
| Paired 12 m noise-isolation workflow | recorded peak about 1.11 GiB | Status and `det09_noise_isolation_12m_v3.json`; retains two systems and residual-map samples. Earlier 0.5-GiB estimate was insufficient. Verify exact record before quoting. |
| TIPTOP study's 15 model-plus-completion evaluations | 84.1 s aggregate timed calls | `docs/notebook12_tiptop_portfolio_notes.md` and validation JSON; not total notebook wall time, and not a 42 m time-domain comparison. |

Where a saved artifact lacks a field, say `not recorded`; do not infer a
historical revision from the current file's presence at HEAD. Existing
allocation estimates for the noiseless ESO path are not calibrated resource
estimators for every physical-camera or paired workflow.

### 8.3 Required memory inventory and scaling estimates

Define symbols and units: pupil side N, screen side S, layer count L,
retained actuators A, lenslets Q, measurement rows R, frames F, detector block
side W including guard, FFT side P, batch size B, retained nonzeros Z, science
image side H, and science wavelength count K. Use actual dtypes.

At minimum explain and estimate:

- A float64 pupil plane: `8*N^2` bytes; a complex128 plane: `16*N^2`.
- The avoided dense DM influence cube: `8*A*N^2`; the avoided full-pupil
  lenslet masks: approximately `Q*N^2` bytes for bool masks. These are
  counterfactual allocation sizes, not actual sparse-path RSS.
- CSR/operator storage from nonzeros and actual index dtypes, approximately
  `8*Z + index_bytes*Z + index_bytes*(rows+1)` for float64 CSR, plus explicitly
  identified working copies. Derive the relevant rows for each operator.
- Materialized layer bands: approximately `16*L*S^2`; regenerated storage
  avoids persistent per-layer bands while retaining scratch and other state.
  At ten layers and S=2016 this coefficient storage is about 0.61 GiB.
- Detector maps/products and per-frame scratch from Q, W, dtype and the actual
  number of live arrays; batch bounds and copies must be counted.
- Batched FFT/MFT scratch and their configured ceilings. More quadrature or
  spectral nodes can increase computation without linearly increasing every
  retained buffer because wavelengths are processed sequentially.
- Streaming PSFs: retained sum/reference images scale with `K*H^2`, not F.
  The overall simulation is nevertheless not constant-memory in F: requested
  and applied commands require approximately `16*F*A` bytes, plus masks,
  metrics and transient immutable-history copies. At A=5873 and F=2000,
  the two float64 command matrices alone are about 179 MiB.
- A full OPD cube would require `8*F*N^2`, and a retained PSF cube similarly
  grows with frames. Clearly state whether each path actually allocates one.
- Paired studies retain twins and sampled residual maps. Generic ensembles
  may temporarily overlap old and newly built systems; do not assume all
  serial implementations have identical single-run peaks.

Estimate peak from simultaneously live allocations, not a sum of every array
ever used. Add documented engineering headroom without calling it measured
RSS. Distinguish GiB from decimal GB.

### 8.4 Required runtime estimates and practical scenarios

Use a workload decomposition such as:

`T_total = T_build + T_calibration + F*(T_atmosphere + T_DM + T_WFS + T_reconstruct + T_science) + T_output`.

Define nonoverlapping timing boundaries. Existing `science_run.build_s`
includes calibration, and some recorded loop timings already include science.
When build includes calibration, omit a separate calibration term or measure
its exclusive portion; never add science again to a science-inclusive loop.
Define which terms are measured and where caching removes work. Discuss FFT
grid scaling, local batched sensing, sequential wavelength/exposure samples,
LSMR nonzeros and iteration counts, master generation and science stride.
An asymptotic scaling law is not a calibrated wall-time prediction.

Provide a scenario table for: one small validation run, a 12 m study, one
42 m reference realization, five/ten serial 42 m realizations, simultaneous
workers, longer frame histories, and finer pupil/detector sampling. Estimate
serial and parallel resource needs separately. Five historical E5-like serial
runs would be about five hours at the observed rate; that is extrapolation,
not a VM quote or measured speed guarantee. Parallel RAM is approximately
shared overhead plus live workers times per-worker memory, with headroom;
CPU and memory bandwidth can prevent proportional acceleration.

Explicitly state that a 16-GiB machine completed the recorded optimized native
42 m run, not that 1.61 GiB is a universal system minimum or that an 8-GiB host
has been validated. Big-memory VMs are not inherently necessary for serial
replay of this one workload. Hardware suitability requires the actual options,
free memory, safety policy and current measurements.

## 9. Bibliography and source requirements

Create one bibliography inside the technical reference and a source-to-model
traceability table. Each entry needs author/organization, title, year/version,
DOI or stable URL, relevant section/equation/table, supported claim, repository
implementation, and verification/access status.

Start with existing ledgers and citations. In particular inspect:

- Historical ESO E-ELT DRM atmosphere/AO and telescope tables (R1/R2),
  Gladysz/Rebolo's separate PAOLA reference case (R3), and Bechet/Tallon's
  FRiM/OCTOPUS slides (R4). Do not merge conflicting reference cases or
  describe the historical 42 m design as the present telescope specification.
- Basden, Haniff and Mackay (2003) for high-gain EM multiplication;
  Robbins and Hadwen (2003) for EMCCD noise; Janesick (2007) for photon
  transfer; Thomas et al. (2006) for SH centroid algorithms; Oke and Gunn
  (1983) for AB photometry; EMVA 1288 for relevant definitions; Kannawadi
  et al. (2016) for interpixel coupling; and other entries actually present
  in the detector ledger. Verify ledger bibliographic uncertainties rather
  than laundering them into confirmed references.
- The actual sources used for phase-screen normalization, subharmonics,
  infinite-screen covariance, Gaussian/linear-spline influences, MFT,
  diffraction/science metrics, regularization and LSMR. Inspect code,
  contract notes and upstream references to identify the precise source.
- The actual HCIPy, TIPTOP/P3 and MASTSEL versions and their method papers
  or official documentation. A dependency citation does not validate the
  repository's parameter choices or adapter modifications.

When external verification is available, prefer original papers, publisher/DOI
records, official standards and official project documentation. Verify the
specific claim, not merely that a title exists. Label inaccessible full text,
secondary-only confirmation or unverified equation locators honestly. Do not
invent authors, DOIs, equations, benchmark equivalence or publication status.

Use `external method`, `repository derivation`, `engineering assumption`,
`direct public input`, and `measured hardware calibration` accurately. No
current synthetic camera preset acquires the last label through citation.
Preserve licenses and data redistribution notices; do not copy paywalled
papers into the repo. Do not rewrite governed packaged ledgers just to improve
the bibliography; document corrected attribution in prose with evidence and
use the existing governance if a packaged correction is actually necessary.

## 10. Verification map and command guidance

Run from the execution checkout with its intended environment; the existing
local interpreter is `.venv/bin/python`. Inspect available tooling first.
Do not upgrade dependencies opportunistically. Set `OMP_NUM_THREADS`,
`OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`, `VECLIB_MAXIMUM_THREADS` and
`NUMEXPR_NUM_THREADS` to 2 for bounded serial numerical checks.

Representative existing checks, to adapt to actual affected files:

```text
.venv/bin/python -m pytest -q tests/experiments/test_detector_evidence_runner.py tests/experiments/test_detector_level_experiments.py
.venv/bin/python -m pytest -q tests/io/test_configs.py tests/io/test_detector_level_profiles.py tests/io/test_detector_level_ledgers.py tests/io/test_recovery_policy_config.py
.venv/bin/python -m pytest -q tests/control/test_recovery.py tests/control/test_loop.py tests/calibration/test_sparse_calibration.py
.venv/bin/python -m pytest -q tests/detector/test_noise_model.py -k raw_readout
.venv/bin/python -m pytest -q tests/docs tests/test_refactor_contract.py tests/test_refactor_characterization.py
.venv/bin/python scripts/generate_detector_level_profiles.py --check
.venv/bin/python -m ruff check src tests scripts examples build_support
.venv/bin/python -m mypy
.venv/bin/python -m pytest -q -m "not hcipy and not slow and not elt_scale"
```

The whole native selection may be split into recorded serial batches with
identical coverage. Inventory the actual collected node IDs instead of merely
copying historical totals. Select optional/slow tests intentionally; preserve
the explicit `--enable-elt-scale` protection and never treat collection as
authorization to allocate a large system.

Use the wheel/sdist and portable-bundle procedure already implemented in
`.github/workflows/ci.yml`, `scripts/prepare_wheel_smoke_bundle.py`,
`scripts/inspect_wheel_contents.py`, and `tests/test_wheel_install.py`.
Build and test in temporary destinations and an isolated installation outside
the source tree with `PYTHONPATH` cleared. Do not uninstall or replace the
user's working environment. Network-unavailable dependencies and missing
Python versions must be recorded precisely; an editable run cannot substitute
for a required installed-wheel gate.

Do not add tests for every renamed helper. Prefer meaningful invariant,
cross-boundary, independent-oracle and actual regression tests. Preserve
existing checks even if a different organization requires updating their
imports or source-derived graph. Do not drop assertions, lower rank criteria,
widen tolerances, change expected failures, or regenerate accepted baselines
to make a structural change appear successful.

## 11. Required status and final handoff format

For each ticket record: scope and files, change rationale, invariant protected,
checks/commands and results, source/environment identities, performance if
affected, reviewer findings and disposition, limitations, and next action.

Maintain an old-to-new ownership map and a deliberate-retention/removal log.
Link every important scientific claim, comparison row and cost estimate to
the producing implementation and evidence. Keep the execution record separate
from the final reference: the former explains what happened during work; the
latter explains how the final system works.

The final handoff must state:

1. Which responsibilities changed, why, and which public routes remain.
2. Where the single technical reference, comparison tables, bibliography,
   cost model, roadmap and limitations are located.
3. Checks actually run on the final tree, source and wheel environments,
   unexpected skips/failures, and unavailable lanes.
4. Before/after scientific identities and witness results, accepted resource
   integrity and measured resource regressions/improvements.
5. Independent review decision, repaired findings, accepted model boundaries,
   deferred governed experiments and any required unfinished checks.

Do not end with only a proposed plan, claim universal physical validation,
or imply that a structural cleanup resolved the remaining scientific limits.
