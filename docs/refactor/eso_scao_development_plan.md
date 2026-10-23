# ESO-derived SCAO Benchmark, Long-exposure Science and High-order Scaling

> **Historical assignment (2026-10-18).** This plan was carried out; its
> outcome is recorded in [`ESO_SCAO_DEVELOPMENT_STATUS.md`](ESO_SCAO_DEVELOPMENT_STATUS.md). It is not the current plan:
> the implementation is explained in the [technical reference](../technical_reference.md)
> and open work is in the [roadmap](../roadmap.md).

Prepared: 2026-10-14 (Europe/Berlin)  
Repository: https://github.com/xhvoid/Shack-Hartmann-AO-Simulation  
Planning snapshot: e55754f4221a69f4765249c63f39cd081348a955  
Implementation status: NOT STARTED. This document specifies future work; it is not evidence that any feature or acceptance test already exists.

Current execution policy: memory/pressure enforcement is disabled by default;
see [RESOURCE_POLICY.md](../../RESOURCE_POLICY.md). The policy below records
the historical benchmark requirements.

Historical desktop execution policy: DESKTOP-SAFE by default. Medium/full-scale scientific runs and broad test suites are not authorized automatically. Section 2.3 takes precedence over instructions elsewhere to execute validation gates.

## 1. Implementation requirements

The implementation combines adaptive-optics modelling and scientific software engineering. Implement the three objectives below in this repository, using its canonical shwfs_ao architecture. Deliver working code, independent numerical tests, reproducible examples, documentation, and a durable execution record. 

1. Create a source-traceable, explicitly ESO-derived, natural-guide-star Shack–Hartmann SCAO benchmark.
2. Add streaming long-exposure monochromatic science images and metrics to the existing closed-loop execution path.
3. Make the native DM, SH-WFS, calibration, and reconstruction path usable at the benchmark's high-order spatial scale without materializing full actuator-by-pupil or subaperture-by-pupil arrays.

The primary outcome is an auditable numerical experiment. Matching a published Strehl number by tuning unrelated assumptions is not an acceptance criterion.

Read applicable repository instructions and inspect the actual checkout before editing. The snapshot above is orientation, not a requirement to reset the repository. Preserve unrelated edits and untracked files. Record the actual starting commit and worktree state. Follow explicit instructions from the human user over this plan. Unless separately authorized, do not commit, push, tag, release, publish artifacts, or accept/overwrite governed scientific baselines.

Carry out implementation and resource-approved small tests within the boundaries below, documenting design decisions. An incomplete external source does not require inventing an instrument specification: use an explicit engineering assumption for the derived benchmark, or mark the unavailable comparison as unsupported. Escalate decisions outside the stated scope, and obtain specific enablement for the larger runs gated by section 2.3. Do not silently reduce the requested physical scale to make a run pass.

## 2. Scope and scientific claim

### 2.1 Required scope

- Historical E-ELT DRM-derived, on-axis, one-NGS, one-ground-DM, image-based SH-WFS SCAO.
- Existing native ten-layer, absolutely normalized von Karman atmosphere.
- A small deterministic CI case, a medium scaling case, and the full nominal SH/DM spatial scale.
- Separate accumulated science images at explicitly selected monochromatic wavelengths.
- The existing controller, detector policies, units, identities, and canonical loop.
- A scalable calibrated linear response and solver sufficient to control the full retained actuator set.

### 2.2 Explicitly outside the required implementation

- A current ELT instrument digital twin, on-sky performance certification, or an exact OCTOPUS reproduction.
- LGS propagation, cone effect, tomography, MCAO, PWFS promotion, scintillation, telescope structural dynamics, predictive control, and a new minimum-variance science programme.
- A redesign of finite-exposure WFS integration, fractional latency, or DM settling dynamics. Audit and expose the present timing approximation; do not silently change it.
- Mandatory GPU/JAX/CuPy dependencies, notebooks as the sole implementation, or a second control loop.
- A broadband image API in the core milestone. Section 10 describes an optional extension with additional requirements.

Keep three types of result distinct: software correctness, agreement with an explicitly declared physical model, and agreement with independent ESO data. Only claim a level for which evidence is actually available.

### 2.3 Mandatory desktop-safe execution policy

The user's Mac must remain responsive. The authoring desktop reported 16 GiB physical RAM on 2026-10-14; detect the execution host again rather than assuming the same hardware or current memory availability. An 8 GiB benchmark acceptance target is not permission to consume half of this Mac's RAM. Neither a declared cap nor a polling watchdog is a guaranteed macOS hard memory limit.

Default automatic execution:

- Run one scientific/test process group at a time, with one test worker. No pytest-xdist, simultaneous calibration, concurrent test runs, or background full-suite jobs. Code inspection and edits to independently owned files may proceed concurrently.
- Set native-library thread limits before starting Python/importing NumPy and inherit them in all children: OMP_NUM_THREADS=2, OPENBLAS_NUM_THREADS=2, MKL_NUM_THREADS=2, VECLIB_MAXIMUM_THREADS=2, NUMEXPR_NUM_THREADS=2. Use one explicit FFT worker where supported; do not create an unrestricted worker pool. Use lower limits if the host has fewer available CPUs.
- The aggregate RSS budget for the launched process group, including descendants, is the minimum of 2 GiB, 12.5% of physical RAM, and 25% of reliably measured currently available RAM. Recheck before every job. If availability cannot be measured reliably, use at most 1 GiB and tiny pre-audited fixtures only. Sum process RSS conservatively; do not give every subprocess its own full budget.
- New automatic scientific fixtures start at no more than 128 pupil pixels, 10×10 nominal SH, 11×11 nominal DM, 32 frames, one science wavelength, and science pad factor <= 3. These are software-test limits, not a replacement physical benchmark. Analytic/unit checks outside a dimension limit need an explicit audited allocation estimate that still fits the desktop budget.
- Before launch, estimate baseline interpreter/native-library RSS plus the maximum simultaneously live arrays, FFT temporaries, immutable copies, calibration/solver workspace, and caches; apply a 2× engineering margin. Reject a known over-budget operation before allocating. Keep a default 64 MiB ceiling on individual new numerical scratch buffers; chunk operations instead. In particular, never attempt dense target influence/mask/probe arrays just to measure their failure.
- Run new scientific examples in a supervised child with a default 120 s wall limit; approved focused test batches have a 300 s wall limit. An external watchdog should sample aggregate descendant RSS and reliable OS memory-pressure signals at least every 0.5 s. On budget/timeout violation or a reliable warning/critical memory-pressure signal, stop the owned job, allow at most 2 s for cleanup, then terminate its owned process group. Never terminate the development application or unrelated user applications. Save partial logs and label the result RESOURCE_LIMITED or INTERRUPTED.
- Cumulative swap counters do not establish current pressure. Use deltas/current signals where available. If reliable process/memory monitoring is unavailable, do not treat the nominal cap as enforced: restrict execution to tiny pre-audited tests and defer larger jobs.

Larger-test authorization and guards:

- Medium runs, any 84×84/85×85 target construction/calibration, 1008/1024-pixel numerical runs, and the 2,000-frame reference run require the human user to explicitly enable the concrete run after seeing its configuration, estimated peak memory, CPU/thread count, timeout, and output path. Acceptance of this development plan, successful small tests, or a broad “run tests” instruction does not automatically enable those runs. A dry-run estimator must not construct the target system.
- Implement an explicit large-test enable option in addition to a registered elt_scale marker. Large tests must skip/refuse execution without that option even if a caller overrides pytest's marker expression. A broad pytest invocation must not trigger them. Imports, collection, fixtures, default CLI arguments, and profile loading must not allocate or build large systems.
- Larger authorized runs still need preflight and a supervisor. On this 16 GiB desktop, retain the desktop-safe budget unless the user separately authorizes a specific revised budget with measured headroom. Prefer another suitable host for an experiment whose estimated peak cannot fit. Do not disable allocation guards or rely on swap to satisfy a benchmark.
- When a gate cannot be run within these rules, record NOT_RUN_RESOURCE_POLICY with the exact future command and estimate. Continue implementation and safe checks. That gate remains unverified; it is neither a pass nor permission to substitute a smaller run under the full-scale label.

Implement and independently test the supervisor/enable guards using tiny synthetic allocations, stub pressure signals, and short sleeping test children before running new scientific work. Do not deliberately exhaust RAM or create real system memory pressure to test the guard. RSS monitoring is best effort; upfront allocation prevention and conservative defaults are the primary protections.

## 3. Primary sources and a coherent reference policy

Use the following stable source IDs throughout parameter records, decisions, tests, and reports. URLs were checked on 2026-10-14. Record a new access date if revisited. Historical content dates matter more than the modern site navigation date.

| ID | Reference and locator | What it establishes; boundary |
| --- | --- | --- |
| R1 | [ESO DRM: AO performance and PSFs](https://www.eso.org/sci/facilities/eelt/science/drm/tech_data/ao/), parameter tables and PSF database; updated 2011-05-25 | Atmosphere/system scales below; PSFs cover GLAO, LTAO, and NOAO, without SCAO. |
| R2 | [ESO DRM: telescope technical data](https://www.eso.org/sci/facilities/eelt/science/drm/tech_data/telescope/), “Photon collecting area”; footer dated 2013-03-20 | Historical annular telescope geometry in section 4, omitting segmentation and supports. Use the exact annular area formula, not a rounded area multiplier. |
| R3 | S. Gladysz and R. Rebolo, [The E-ELT Design Reference Mission: Direct imaging of terrestrial and giant exoplanets](https://www.eso.org/sci/facilities/eelt/science/drm/S3/S3_1_report.pdf#page=17), v2, 2010-06-01; Table 1, p. 17; methodology section 2.2.1, pp. 5–6 | A separate SCAO case: spatially filtered SH 84×84; 2 ms integration; 6 ms readout-plus-reconstruction lag; 3 electron read noise; 0.6–0.9 micrometre sensing; 30 nm NCPA. Its PAOLA-based method, 0.7 arcsec seeing, pupil, and perfect-filtering assumptions differ from the DRM website case. |
| R4 | C. Bechet and M. Tallon, [Reducing the Fractal Iterative Method (FRiM) to the cost of half an iteration](https://www.eso.org/sci/meetings/2012/RTCWorkshop/6_1_bechet.pdf#page=7), ESO RTC workshop, 2012; slide 7 and slides 15–16. [Workshop programme](https://www.eso.org/sci/meetings/2012/RTCWorkshop/program.html) | Independent FRiM/OCTOPUS SCAO experiment: 42 m, obstruction ratio 0.28, 500 Hz, nine layers, r0 = 0.129 m, tau0 = 2.8 ms, ground DM 85×85, one NGS, SH 84×84, and 10^5 photons/frame/subaperture. The presentation does not provide a complete reproducible input deck or raw SCAO PSF dataset. |

R1 and R2 are the normative sources for the initial derived benchmark. R3 and R4 are contextual, independent reference cases. Do not merge their noise, atmosphere, pupil, filtering, flux, reconstruction, or delay settings into the normative case while retaining a single source label. In particular, the R1 delayed-command convention and R3's lag definition are different. The R4 nine-layer distribution cannot be replaced by the packaged ten-layer distribution and called an exact reproduction.

If additional publications or official implementation documentation are used, add their bibliographic details, direct URL/DOI, specific page/section, supported claim, and limitations to the source ledger. Search snippets alone are not a sufficient parameter source. Do not redistribute complete external PDFs or large external datasets by default; keep concise source records and content hashes where appropriate.

## 4. Benchmark specification and parameter traceability

Use the proposed family name eso_drm_42m_scao_derived. A different name is acceptable if its meaning is equally explicit. Introduce new versioned resources; preserve every published profile and its identity.

### 4.1 Normative physical targets

| Parameter | Target | Authority/classification |
| --- | --- | --- |
| Primary diameter | 42 m | R2, source-derived |
| Central-obstruction diameter ratio | 0.28 | R2, source-derived |
| Pupil segmentation and spiders | Omitted in this first reference case | R2 model boundary |
| Integrated Fried parameter | 0.13 m at 500 nm | R1; use the packaged atmosphere data |
| Outer scale | 25 m | R1 |
| Layer distribution and speeds | The existing ten-layer table | R1; preserve printed and normalized fractions |
| Nominal SH grid | 84×84 | R1 scale borrowed into the derived SCAO topology |
| Nominal square DM grid | 85×85, ground conjugate | R1 scale borrowed into the derived topology |
| DM influence family | Linear spline | R1; the precise implemented basis still needs an explicit mathematical definition |
| Loop rate | 500 Hz | R1 |
| Long reference run | 2,000 total iterations, 4 s at the stated rate | R1; science exposure excludes burn-in/selection |
| Delayed command | Three iteration intervals | R1; map to the repository's measured frame semantics and document the mapping |
| Noise convention | Deterministic noiseless sensing | R1 idealized-noise limit, adapted to the one-NGS case |

The one-NGS, on-axis topology is an engineering adaptation. The published layer fractions sum to 1.001; record normalization by that sum. Directions are unspecified and need an assumption. R1's CCD sampling row says “6” without resolving its dimensional interpretation; it is not authority for an unqualified 6×6 detector claim.

### 4.2 Assumptions to resolve explicitly

Create a machine-readable assumption ledger before publishing the new profile. Every executable value must be present, even when no external source supplies it. Give each row an ID, quantity/config path, numerical value and SI unit, source ID/locator or assumption rationale, transformation, uncertainty/known limitation, and consuming test.

At minimum close the following:

- A01: one on-axis NGS; no off-axis propagation or finite source range.
- A02: wind azimuths. Default all layers toward +x is acceptable and must be stated.
- A03: sensing wavelength. The existing 700 nm value is an acceptable explicit monochromatic engineering setting; it is not a claim about a published sensor bandpass.
- A04: science wavelength. Require a 2.2 micrometre example; additional monochromatic outputs are optional. This is a declared experiment choice.
- A05: pupil raster resolution, atmospheric high-frequency cutoff/inner-scale treatment, SH focal sampling, detector window, illumination threshold, and clipping policy. Carry forward the packaged atmosphere's numerical cutoff convention. Keep pupil samples per lenslet distinct from detector pixels per spot.
- A06: mathematical linear-spline basis, actuator pitch/alignment, normalization, support, retained physical actuator IDs, and uncontrollable/zero-illumination handling. A separable bilinear tent basis is a feasible declared interpretation, not a proven ESO implementation detail. The existing radial pyramid_like family must not be renamed as an identical basis without proof.
- A07: gain, leak, reconstruction objective/regularization, piston/null-space treatment, initialization, and calibration probe amplitude.
- A08: stroke semantics. Prefer an explicit unbounded mode if added safely. Otherwise declare a finite engineering limit and require zero measured saturation in any run described as approximating the unbounded case. Do not encode infinity as an arbitrary large finite value without labelling the approximation.
- A09: numerical electron scale used by noiseless image sensing. It must not be presented as a measured guide-star flux. Verify normalized slopes are invariant to that scale over the selected validity range.
- A10: timing: frame timestamp, period, detector exposure field, command-release convention, science residual phase, and the instantaneous-snapshot temporal quadrature approximation.
- A11: burn-in, science frame selection, temporal weights, science grid, field of view, peak/centering policy, and flux denominator.
- A12: any truncation, iterative stopping tolerance, batching choice, or precision setting that can alter physical results.

Do not tune these assumptions to a desired literature Strehl. Run convergence and validity checks, explain each necessary revision, and freeze the final version in the ledger. Distinguish a measured zero from an unavailable/unknown value.

Use the repository's supported provenance source_class values; descriptive ledger labels such as source-derived are not new serialized enum values. The overall derived SCAO configuration must disclose its synthetic engineering assumptions even when individual parameters are literature-derived.

The profile must load offline from an installed wheel. A lower-order smoke case must carry its own identity and an explicit software-smoke label; changing actuator density at fixed aperture changes the physical experiment.

## 5. Repository constraints and implementation seams

Read these documents first: docs/architecture.md, docs/backends.md, docs/validation.md, docs/reproducibility.md, docs/eso_elt_turbulence_model.md, and docs/refactor/AO_REF_006_DEFORMABLE_MIRROR.md through AO_REF_012_ARTIFACTS.md as applicable.

| Area | Existing owner / seam | Constraint for this work |
| --- | --- | --- |
| Profile schema, parsing, hashes | src/shwfs_ao/io/configs.py; io/resources.py; resources/resource_manifest.json | Exact record field sets, versioned profiles, and historical hash stand-ins already exist. Add a schema only if needed; old records must retain meaning and identities. |
| Assembly | src/shwfs_ao/experiments/scao.py | Extend the canonical factory and runner. Preserve custom single-layer factory compatibility and build attestations. |
| Frame loop | src/shwfs_ao/control/loop.py; control/history.py; core/protocols.py | Atmosphere sampled once per frame; controller owns the sole delay queue; existing histories and default return contracts stay valid. |
| Science | src/shwfs_ao/science/propagation.py, metrics.py, bandpass.py; backends/native/propagation.py | Reuse the one native science FFT and physical-axis metrics. Scalar band averages are not image coaddition. |
| DM policy and spatial synthesis | src/shwfs_ao/dm/model.py; backends/native/dm.py | Units, IDs, fault precedence, requested/applied telemetry, and reflective factor-of-two boundary stay unchanged. |
| Geometry and SH optics | src/shwfs_ao/wfs/shack_hartmann/geometry.py, measurement.py, calibration.py; backends/native/shwfs.py | Preserve nominal lenslet canvas, partial illumination, sampling, row order, throughput, centroid/noise policies, and calibration identity. |
| Calibration and solving | src/shwfs_ao/calibration/interaction.py; reconstructors.py | Full influence/probe stacks and full dense SVD are current scaling barriers. Changing only the synthesis kernel is insufficient. |
| Packaging and CI | pyproject.toml; tests/wheel_smoke/manifest.json; tests/test_wheel_install.py; .github/workflows | New resources and required scientific tests must reach the wheel/sdist and the intended CI tier. Preserve optional HCIPy imports. |

Canonical quantities remain OPD metres, phase = 2*pi*OPD/wavelength, commands in m_opd_equivalent, time seconds, detector charge electrons, and angular coordinates radians. Residual = atmosphere minus DM correction. Apply the reflective-surface factor exactly once at the HCIPy boundary.

Do not change frozen legacy facades, signatures, numerical baselines, or profile defaults to obtain a speedup. Add opt-in scalable implementations and preserve the default dense/reference path. Any intentionally changed new physics gets a new model/version identity and an independent test.

## 6. Execution ledger and dependency order

At implementation start, create docs/refactor/ESO_SCAO_DEVELOPMENT_STATUS.md. Keep this plan as the requirements reference; record execution evidence in the status file and linked artifacts. Use the same ticket IDs below.

| Ticket | Work package | Depends on | Initial status |
| --- | --- | --- | --- |
| ESO-00 | Baseline audit, source/assumption ledger, and design decisions | None | TODO |
| ESO-01 | Versioned benchmark records, schema and identity design | ESO-00 | TODO |
| ESO-02 | Passive frame observation with unchanged control behavior | ESO-00 | TODO |
| ESO-03 | Streaming monochromatic science and final-image metrics | ESO-02 | TODO |
| ESO-04 | DM spatial-operator and local probe capabilities | ESO-00 | TODO |
| ESO-05 | Compact SH geometry and bounded batched optics | ESO-00 | TODO |
| ESO-06 | Streamed calibration and scalable full-coordinate reconstruction | ESO-04, ESO-05 | TODO |
| ESO-07 | Factory integration and executable benchmark tiers | ESO-01, ESO-03, ESO-06 | TODO |
| ESO-08 | Scaling/convergence evidence, packaging and documentation | ESO-07 | TODO |

Implementation of independent tickets may be parallelized with explicit file ownership. Keep a single authoritative integration state and review shared interfaces before merging subtask work. Scientific/test execution remains serialized under section 2.3.

Each ticket record must contain: status (TODO / IN_PROGRESS / DONE / BLOCKED / IMPLEMENTED_VALIDATION_PENDING), start/end date, actual base revision, changed files, design/assumption decisions, exact validation commands, pass/fail/skipped/resource-deferred counts, numerical results and tolerances, artifact paths/hashes, remaining limitations, and the next executable action. DONE requires its acceptance evidence. A skipped or resource-deferred full-scale run is not a passed full-scale run.

Use a traceability table with columns: requirement/assumption ID -> source -> executable config field -> implementation -> test -> evidence artifact. Record deviations with their reason and effect on the scientific claim. At the end of each work session, leave a short resume checklist in the status file.

## 7. Ticket specifications

### ESO-00 — Audit and freeze the development baseline

Actions:

1. Record Git status/revision, Python and dependency versions, physical/currently available memory, native/optional-backend availability, and audited test selection. Implement the desktop-safe preflight/supervision and large-test enable guards in section 2.3 before new scientific runs.
2. Read the current architecture and locate all dense allocations on the end-to-end build/calibration/run path, including copies and hashing.
3. Create the source/assumption ledger specified above, plus a short decision record for operator, science-result, timing, and identity contracts.
4. Run only resource-approved affected native baseline tests and a bounded 2 m SCAO smoke. Audit fixture construction before collection/execution. Record pre-existing failures without changing their expected outputs; defer tests exceeding the desktop policy.

Acceptance:

- All required quantities have a source or explicit assumption; source contradictions have separate case IDs.
- A reproducible baseline exists for control arrays, PSF behavior, published hashes, and representative memory/runtime measurements.
- Tiny synthetic tests prove preflight rejection, large-test refusal without enablement, process-group aggregation, timeout/cancellation, and watchdog cleanup without stressing the desktop. Runtime thread limits are visible in the recorded environment before library imports.
- The planned full-scale path includes the DM wrapper, probes, WFS geometry, calibration, solver, and hashing; no known densifying seam is omitted.

### ESO-01 — Add versioned benchmark records without changing published identities

Actions:

1. Define the derived physical profile and separate numerical execution settings. Include every approximation in executable metadata or an unambiguously bound ledger resource.
2. Implement strict loading/serialization and expose intended public names only. If new fields require a schema version, preserve exact older field sets and hash views.
3. Package source and assumption records, add manifest checksums, and make all required resources available without the checkout or network.
4. Keep unresolved R3/R4 reproduction cases as documented reference records, not runnable exact-ESO claims.

Acceptance:

- The new record round-trips; malformed fractions, unsupported modes, inconsistent clocks, missing assumptions, and inappropriate source labels are rejected.
- All existing packaged profile hashes and observing-condition identities are unchanged.
- New physical/algorithm choices change the appropriate identity. Batching and thread settings alone do not change the physical/noise identity.
- Loading a profile does not trigger full-scale construction, calibration, external downloads, or HCIPy import.

### ESO-02 — Add a passive frame observer to the existing loop

Actions:

1. Add an optional observer/event contract, default disabled, to the canonical loop and forward it through the canonical experiment API.
2. Supply frame index/time and explicitly named atmospheric, pre-update-residual, and post-update-residual OPD snapshots from the already computed frame. Only include arrays actually needed by selected observers.
3. Invoke observation at a documented point after the relevant maps exist. Do not expose live atmosphere, RNG, WFS, controller, or DM handles.
4. Make retained events safe against mutation and buffer reuse, with bounded allocation. Propagate observer exceptions with frame context rather than silently dropping frames.

Acceptance:

- Disabled observation and a no-op observer produce exactly the same control arrays, masks, commands, RNG identities, atmosphere call count/timestamps, and control-run hash.
- Hand-constructed tests verify the event maps for nonzero latency, saturation/fault application, and unusable reconstruction.
- Attempted event mutation cannot alter the run; an event retained by a caller does not change on later frames.
- No second atmosphere query, replay loop, detector realization, or control update is introduced.
- Existing LoopHistory-returning APIs remain usable unchanged. Science-specific metadata lives in an additive science result/configuration identity.

### ESO-03 — Form science images by accumulating intensities

Actions:

1. Add a science-owned streaming accumulator, for example science/long_exposure.py. Maintain a sum image, total weight/count, fixed reference/sampling data, and bounded scratch space for each requested wavelength. Do not retain OPD or PSF cubes.
2. For selected frames, propagate residual OPD separately at each wavelength and accumulate instantaneous intensity. For weights a_k, return sum(a_k*I_k)/sum(a_k).
3. Default to pre-update residual at every selected frame with equal weights, after an explicit burn-in. If post-update residual is selected, label it a same-atmosphere-sample diagnostic; it is not a finite-shutter exposure model.
4. Record selected frame range/stride or equivalent exact selection, timestamps, count, period, elapsed observation span, quadrature weights, residual phase, and reset behavior. For N uniform full-cadence samples, distinguish N*dt quadrature exposure from the (N-1)*dt separation of sample centres.
5. Create/cache a zero-OPD ideal reference using the identical pupil, propagation, wavelength, angular grid, and flux policy. Compute final-image Strehl, FWHM, radial profile, and EE only after accumulation.
6. Keep residual tip/tilt by default. Do not recenter individual images before accumulation. Declare optical-axis versus final-image-peak conventions for reported metrics.
7. Define a new aggregate container with selection/provenance metadata; individual wavelength images may reuse PsfResult only when its unit-flux single-wavelength contract remains valid.

Required numerical tests (independent expected values):

- Repeated static OPD: identical to one propagation; zero OPD: ideal image and unit peak Strehl.
- Opposite tilts: the averaged image is broadened, even though the average OPD is nearly zero. This must fail an implementation that propagates mean OPD or recenters every frame.
- Different piston values: intensity accumulation remains invariant; no coherent-field averaging.
- Small deterministic sequence: streaming output matches a separately materialized average of instantaneous intensities (initial target float64 rtol 1e-11, atol 1e-14 in normalized pixel flux; justify any adjustment).
- Selection, nonempty output, burn-in, stride, invalid weights/NaNs, reset/reuse, and exception behavior.
- Final-image metrics differ from averaged instantaneous metrics in a deliberately chosen counterexample.
- Fixed grid/wavelength count: retained accumulator memory is independent of frame count. Test structure/allocation counts, not only noisy RSS.
- A known annular/circular diffraction fixture checks angular scale and ideal PSF shape independently of the backend under test, with sampling-convergence evidence.

Flux boundary:

- The required native path may initially use the full source FFT grid and report normalized-source-grid flux, with that denominator stated.
- Do not crop and independently renormalize science and ideal images before peak ratios. If cropping is introduced, retain lost-flux information and define conditional versus absolute EE.
- Existing EE helpers normalize to retained image flux. Do not label those values absolute-source EE without a known absolute denominator.
- HCIPy unit-sum finite-window PsfResult alone does not establish captured pupil power. Its captured_flux_fraction diagnostic may help; record extra propagation cost and the denominator used. Optional-backend limitations must be explicit.

### ESO-04 — Add a bounded-memory DM operator and lazy probe access

Actions:

1. Introduce an opt-in spatial capability that exposes actuator count/order, output geometry, deterministic model identity, forward synthesis, and lazy/local influence or probe access without requiring an influence cube.
2. Adapt DeformableMirror, factories, probe bases, metadata, and identity/preflight code. Construction must not call influence_functions() on a scalable backend merely to discover shape/count or compute a hash.
3. Implement a finite-support linear-spline interpretation for the new derived profile, or record a justified alternative before coding. Define its exact basis equation and support. Local stencils must preserve boundary/pupil behavior and OPD normalization.
4. Retain dense influence access as a small-problem compatibility capability with an explicit size/memory guard. It must not be silently invoked on the scalable production path.
5. Expose an adjoint if required by calibration/solving. Stream probe maps/chunks rather than materializing every positive/negative full-pupil probe.
6. Do not silently truncate Gaussian tails. Any compact approximation must be opt-in, versioned, bounded by an error study, and distinct from unchanged Gaussian physics.
7. Classify support against the actual illuminated pupil before normalization/calibration. With an obstructed pupil and finite-support influences, some central layout actuators have exactly zero illuminated support. Preserve their physical IDs in the full DM layout, but exclude those coordinates from calibration/solving through an explicit controlled-subset mapping. Record geometric exclusion separately from dead/stuck hardware faults. Do not normalize an all-zero map, mislabel it as a dead actuator, or remove partially illuminated valid support.
8. Bind the scalable identity to ordered physical IDs, sampled geometry/pupil, basis equation/version, normalization, local support indices/weights, and zero-support classification, without reconstructing a dense cube. Immutable content changes must invalidate stale calibration; chunking/storage details alone must not change the physical/noise identity.

Acceptance:

- Small-grid forward results match independently assembled dense influences for random, one-hot, boundary, and null commands; target normalized relative L2 error <= 1e-11 for the same finite-support model.
- If a DM adjoint is provided or used, its forward/adjoint dot-product test has relative error <= 1e-10 on nontrivial vectors. The calibrated response operator in ESO-06 always requires a tested adjoint.
- Command IDs, dead/stuck precedence, clipping, saturation telemetry, and positive-correction sign match the existing policy.
- Explicit central-obstruction tests cover exact zero support, partially illuminated inner/outer boundary support, controlled-subset projection into the full command layout, and exclusion-reason metadata. All remaining eligible controllable coordinates participate; arbitrary low-mode/actuator subsets are not acceptable.
- Storage scales with local support or operator parameters, not n_actuator*ny*nx. Full target construction succeeds with dense influence materialization deliberately disabled by a test double/guard.
- Historical dense-path outputs/hashes remain under their existing contracts. New operator identities do not depend on incidental chunk size or array allocation.
- Altered support/weights or pupil content invalidates stale calibration; attempted mutation of owned operator data fails without corrupting the identity.

### ESO-05 — Compact SH geometry and bounded batched lenslet optics

Actions:

1. Add an opt-in compact geometry representation: stable lenslet IDs, local bounds/indices/masks, centres, fill/throughput data, and a fixed nominal lenslet canvas. Avoid full-grid masks per lenslet.
2. Make geometry validation, calibration, WFS measurement, factories, and hashing consume the compact representation without reconstructing a mask cube.
3. Batch native FFTs in configurable bounded chunks. Preserve local piston removal, centering/cropping, phase convention, pixel scale, reference centroids, and partial-illumination treatment.
4. Preserve per-physical-ID detector/PRNU/noise behavior when batch sizes change. Use the established stochastic ownership rather than new per-chunk random streams.
5. Audit hot-path ownership checks and hashing. Cache identities only for immutable owned state; retain meaningful mutation/context validation. Avoid rehashing/copying a full geometry per frame.

Acceptance:

- For small grids, dense/reference versus compact/batched paths agree on spot intensities, captured fraction, axes, centroids/slopes, valid masks, IDs, and zero-phase calibration (float64 target rtol 1e-11, atol 1e-14 for normalized intensities; assess centroid error in detector pixels).
- Cover fully illuminated and partial edge lenslets, obstruction boundaries, x/y tilts, piston, even/odd dimensions, and lenslet counts that do not divide the pupil size.
- Test batch sizes 1, an odd chunk, and the complete small batch. Detector draws and validity decisions are invariant to chunk size under the same physical/noise identity.
- Test both 1008 and 1024 pupil pixels at nominal 84-across geometry. A nondivisible request must not be silently rounded to a divisible one. Respect the HCIPy adapter's existing whole-window constraint.
- Full target build and repeated measurement do not allocate n_subaperture*ny*nx masks or equivalent hidden caches.

### ESO-06 — Stream calibration and solve the full retained coordinate problem

Actions:

1. Remove positive/negative probe-list materialization and full probe-cube hashing from the scalable path. Generate bounded chunks with deterministic ordering/content identity.
2. For finite-support DM and local native lenslet optics, calibrate only provably affected subapertures where valid. Initially restrict this optimization to include_noise=False. Independent noisy plus/minus measurements can differ outside physical probe support: preserve that sampling through a bounded fallback, or explicitly reject unsupported noise-on scalable calibration. Never replace unmeasured noisy derivatives with exact zeros. Cache unchanged deterministic references and verify equality to full measurement on small systems. Do not assume locality for a model with nonlocal coupling.
3. Provide a calibrated sparse response or forward/adjoint linear operator with explicit row IDs, coordinate IDs, units, calibration validity, model/geometry/source hashes, and regularization convention.
4. Add an opt-in iterative solver, such as LSQR/LSMR or an equivalently justified operator method. This is a scaling mechanism, not an unrequested change to a turbulence-prior MMSE estimator.
5. Adapt canonical preflight, projection, build attestation, serialization/reuse, and resource validation. Do not bypass them by placing a custom solver outside the canonical loop.
6. Define stopping criteria, maximum iterations, initial-guess policy, piston/null modes, invalid-row handling, convergence telemetry, and bounded caches. A nonconverged solution must have an explicit usable/unusable policy.
7. Preserve fail-before-sensor preflight for invalid amplitudes, malformed support, inconsistent IDs, and discoverable invalid probes. Validate descriptors or make a bounded validation pass before any measurement; lazy generation must not turn a deterministically invalid calibration into a partially executed one.

Acceptance:

- On an independently assembled small matrix, match the corresponding dense least-squares/regularized objective and reconstruction to a justified tolerance (initial target relative residual/objective error <= 1e-6 and command relative error <= 1e-5 for an identifiable regularized fixture).
- Calibration agrees with dense finite differences and has a probe-amplitude linearity/convergence check.
- Response forward/adjoint dot-product relative error <= 1e-10; invalid probe/amplitude preflight performs zero sensor calls. Noise-on local calibration either matches the declared bounded reference semantics or fails explicitly before measurement.
- Test rank deficiency/piston, rejected rows, an all-invalid frame, solver nonconvergence, and calibration identity mismatch.
- Every eligible retained controllable actuator participates in the full-scale solve. Geometrically zero-response coordinates use the audited exclusion policy from ESO-04; global piston/null combinations use the declared solver constraint/regularization. Padding an eight-mode demonstration to 84-across geometry does not qualify.
- Full-scale construction/solve avoids full dense SVD, hidden conversion to a dense response, and uncontrolled mask-specific factorization caches.
- Loading/reusing the same calibration avoids recalibration and produces the same scoped stochastic/physical identity under the declared new contract.

### ESO-07 — Integrate three executable tiers

Create a documented command-line example or module with explicit tier, output directory, seed/realization, science selection, memory-limit, timeout, and large-run enable options. Default to the small desktop-safe tier. Provide a metadata-only dry-run estimate. It must use build_scao_system/the canonical runner, not duplicate assembly or control sequencing. The medium/full rows below define eventual validation targets, not automatic permission to run them on the user's Mac.

| Tier | Purpose | Minimum execution |
| --- | --- | --- |
| CI | Numerical behavior and regression | Small fixture or existing 2 m physical system, plus small dense-versus-scalable equivalence; deterministic science accumulation; suitable for ordinary tests |
| Medium, explicit opt-in | End-to-end scaling and calibration | At least 24×24 nominal SH, 25×25 nominal DM, 288-pixel pupil or a documented equivalent; at least 100 frames; full retained coordinates; fresh and reused calibration |
| Full spatial scale, explicit opt-in | Prove target-size usability | 42 m derived profile, 84×84 nominal SH, 85×85 nominal DM, 1008-pixel pupil; full retained coordinate set; calibration/build plus at least 20 real closed-loop frames and streamed science output |

Also provide an opt-in 2,000-frame reference command using the identical full spatial configuration. Execute it only after the specific user opt-in and resource preflight required by section 2.3, not merely because an estimate appears to fit. If it is not executed, leave the long-reference-run acceptance explicitly pending and report the exact command and available short-run cost; do not claim that 20 frames validate a converged long-exposure AO performance result.

The medium case is a distinct lower-order physical experiment, not a rescaled result at the target actuator pitch. Full-scale counts refer to nominal square grids: circular/obstructed-pupil retention changes the active counts. Record nominal, retained, controllable, illuminated, and usable counts separately. Every retained physically controllable coordinate must be exercised; document all exclusions by ID and reason.

Acceptance:

- Commands work from a clean installed wheel outside the source tree and do not write into tracked figures/resources by default. Honor AO_DEMO_OUTPUT_DIR where repository examples use it.
- Produce profile/assumption/source manifests, control telemetry, per-wavelength accumulated images and physical axes, final-image metrics, calibration identity/reuse evidence, timing semantics, and execution metadata.
- A reference/no-op-observer comparison confirms no changes to control behavior.
- Repeated runs with identical configuration and seed/realization reproduce the declared outputs within the documented environment contract.
- Closing the loop and usable-centroid fractions are reported honestly. Do not weaken clipping/validity thresholds or use a self-generated DM-span disturbance to hide atmospheric fitting error.
- Require an actual control gate at medium scale: on a predeclared independently generated weak atmospheric fixture, at least 90% of post-burn-in frames yield usable reconstruction, and mean residual RMS is at least 5% below the same frames' open-loop RMS. Choose the weak physical atmosphere via its declared r0 before running the comparison; do not project truth into the DM span or rescale results afterward. These thresholds are engineering tests, not ESO specifications.
- The full-spatial-scale run must include at least ten usable, successfully applied nonzero command updates, with each accepted solve satisfying its declared stopping policy. An all-invalid/no-update run fails capability acceptance even if it finishes within the memory budget. Twenty frames still do not establish settled science performance.

### ESO-08 — Demonstrate resource bounds, convergence, and portable delivery

Actions and gates:

1. Measure full-process peak RSS in a fresh subprocess for build, calibration, and run, with platform units handled correctly. Include library/runtime, atmosphere, science buffers, caches, calibration, and temporary allocations. Python-only allocation tracing is insufficient for NumPy memory.
2. On an explicitly authorized suitable host, target <= 8 GiB peak RSS for the eventual full-spatial-scale native validation. This is a future engineering acceptance ceiling, not an ESO specification, an enforced OS limit, or permission for an 8 GiB process on the user's 16 GiB Mac. The section 2.3 desktop budget/preflight/supervision rules take precedence. Defer this gate if the host/run is not authorized or lacks headroom; never attempt a known over-budget dense allocation.
3. Report build, calibration, calibration reuse, per-frame atmosphere/WFS/DM/reconstruction/science, and total times. Use repeated measurements where useful. Require bounded memory and numerical equivalence; report speedups rather than imposing a hardware-dependent universal millisecond CI gate. A materially slower intended optimization needs an explanation and decision.
4. Demonstrate that fixed-geometry accumulator storage does not grow with run length; distinguish the existing O(frames*coordinates) scalar/command history from prohibited image cubes.
5. Run sampling and solver convergence on a desktop-approved tractable case with at least three settings; target-size checks require separate opt-in under section 2.3. Predeclare tolerances before inspecting final ESO-like metrics. Suggested engineering target for settled Strehl/EE change between the two finest settings is 2%, reported with seed scatter; a failure is evidence to report, not a tolerance to widen silently.
6. Audit native atmospheric periodic-band repetition for the chosen elapsed time and report it; assess it in long-run statistical claims. Separate HCIPy initialization/warm-up effects from new science burn-in.
7. Build wheel/sdist and verify new modules, presets, ledgers, fixtures, and smoke examples are included. Update the portable wheel-smoke manifest and hardcoded layout/contract inventories where required.
8. Update README.md, docs/README.md, architecture/backend/science/SCAO notes, source inventory, and the execution report. Run resource-approved README commands under section 2.3; gated commands remain explicitly unexecuted until authorized. Figures must have generated-artifact provenance, and source/model limitations must be explicit.

Required evidence matrix:

| Evidence | What must be shown |
| --- | --- |
| Compatibility | Published hashes; existing control/science/DM/WFS behavior; legacy interfaces; optional-import behavior |
| Numerical independence | Analytic diffraction/units; hand-built latency and intensity-average cases; independent dense matrix/operator comparison |
| Integration | Small, medium, and full-spatial-scale runs with true retained coordinate counts |
| Memory | RSS plus structural allocation checks; no prohibited dense stacks/SVD |
| Statistics | Burn-in, actual duration, independent realizations, uncertainty and unresolved convergence |
| Distribution | Offline wheel/sdist loading and execution away from the checkout |
| Claims | ESO-derived label; no SCAO validation against GLAO/LTAO FITS; no exact-instrument claim |

## 8. Test strategy and command templates

Use the repository's existing environment if suitable. If a new environment is necessary, follow the project's supported Python/constraint profiles. Do not upgrade arbitrary dependencies merely to make a test pass.

Run audited, supervised focused tests after each changed component. Do not automatically run the entire native/HCIPy suite: marker names alone do not guarantee a small allocation. After integration, record which broader compatibility/distribution checks remain pending. Optional HCIPy checks additionally require the supported dependency/environment. Use these command templates only through the section 2.3 resource supervisor; the test selection must first be audited for imports, collection, fixtures, and peak allocations:

~~~sh
python -m pytest --collect-only -q -m "not hcipy and not slow and not elt_scale" tests/science tests/control tests/io/test_configs.py tests/io/test_turbulence_profiles.py
python -m pytest -q -m "not hcipy and not slow and not elt_scale" tests/science tests/control tests/io/test_configs.py tests/io/test_turbulence_profiles.py
python -m ruff check src examples scripts tests build_support
python -m mypy
python -m build --outdir /absolute/path/outside/the/checkout
~~~

Register elt_scale and any other new markers in pyproject.toml. Use an explicit large-test enable option as well as markers; ordinary collection/execution must not build heavy fixtures. Keep fast CI bounded; put costly reference/scaling checks in an opt-in manual tier on a suitable host. Preserve collection guards. Broad native/HCIPy regression and full distribution runs must use an audited resource plan and the required opt-in whenever they exceed desktop-safe limits. Do not disable contract assertions or rewrite baselines to accommodate avoidable drift. Existing scientific tolerances are not permission to accept a new modeling error.

For newly selected numerical tolerances, write the expected magnitude, normalization, independent oracle, discretization effect, and reason for the threshold. Avoid default numpy.allclose for nanometre-scale OPD with an inappropriate absolute tolerance. Wall-clock and RSS tests need engineering margins; do not disguise a numerical failure as platform noise.

## 9. Required deliverables and definition of done

Deliver, with exact names recorded in the status file:

1. Versioned derived benchmark profile(s), source ledger, assumption ledger, and strict offline loading.
2. Passive observer/event API and additive streamed science result/API.
3. Monochromatic accumulated-image example with matching ideal reference and final-image metrics.
4. Scalable DM/geometry/SH optics/calibration/reconstructor path integrated through canonical factories and preflight.
5. Independent correctness tests, compatibility tests, and bounded-resource checks for the documented tiers.
6. A benchmark/convergence report with machine/environment/commit/config identities, commands, results, costs, uncertainties, and pending checks.
7. Updated packaging/CI manifests and public documentation, including verified README instructions.
8. A current ticket status/resume record with no unsupported DONE entries.

Full milestone verification requires evidence for ESO-00 through ESO-08 acceptance gates. Under the default desktop policy, implementation and safe small-case validation may finish with medium/full/long-reference gates marked IMPLEMENTED_VALIDATION_PENDING and NOT_RUN_RESOURCE_POLICY. Deliver the code, safe-test evidence, estimates, and future commands without running those gates automatically. Distinguish implementation readiness, verified full-spatial-scale capability, and long-duration performance validation. Never report an unexecuted run as a success or escalate resource use merely to obtain DONE status.

The final implementation report must state what changed, why, which source/assumption applies, commands/tests actually run, measured numerical/resource results, preserved compatibility, and every remaining limitation. Use “ESO-derived SCAO benchmark” unless a separate, complete, source-matched SCAO validation is established.

## 10. Optional follow-on: broadband image formation

This extension is not required to finish the three core objectives. Implement it only after the required monochromatic path is validated, or on a subsequent explicitly scoped task. Do not relabel existing scalar-band averages as broadband PSFs in the meantime.

If added, it requires all of the following:

- One common angular detector grid, with explicit pixel edges/area in radians, because source-grid angular coordinates vary with wavelength.
- Nonnegative, flux-conserving resampling of discrete pixel flux, with an independent overlap/analytic fixture and grid/field/wavelength convergence checks. Ordinary interpolation followed by arbitrary unit-sum renormalization is insufficient.
- Explicit spectral weighting: source photon spectrum times throughput/QE and wavelength quadrature. A flat photon-spectrum assumption is acceptable when stated. Energy spectra require the wavelength/(h*c) photon conversion.
- Time and wavelength accumulation of intensities; the ideal broadband reference uses exactly the same pupil, grids, weights, crop, and normalization.
- Broadband peak Strehl from the ratio of final science and ideal angular-surface-brightness peaks, not averaged monochromatic Strehls or an effective-wavelength shortcut.
- A result contract that preserves captured flux and its denominator. Do not force a cropped non-unit-flux broadband image into the single-wavelength PsfResult contract.
- No independent science/ideal crop renormalization. Conditional in-window EE must be labelled; absolute EE80 is unavailable if its required energy lies outside the known field.
- Single-wavelength reduction, zero-OPD unit-Strehl, cropping-loss, non-square-grid, spectral-convention, and bounded-memory tests.

## 11. Start here

Begin with ESO-00. Inspect the current checkout, initialize the status/source/assumption records, implement desktop-safe supervision, establish bounded baseline evidence, and settle the additive interfaces. Execute the implementation dependency graph and authorized safe checks; leave larger validation explicitly pending until the user enables a concrete resource-reviewed run. Keep the existing small reference implementation available as the numerical oracle while adding the scalable path.
