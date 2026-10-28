# ESO SCAO development status

Requirements reference: [ESO_SCAO_DEVELOPMENT_PROMPT.md](ESO_SCAO_DEVELOPMENT_PROMPT.md).
This file is the execution record. It lists only evidence that was actually
produced; a resource-deferred gate is not a passed gate.

## Session record

| Field | Value |
| --- | --- |
| Work started | 2026-10-15 00:11 CEST |
| Actual starting commit | `e55754f4221a69f4765249c63f39cd081348a955` (branch `public-clean-main`) |
| Starting worktree | three untracked planning files (`AO_REFACTOR_MASTER_TICKETS_REVISED.md`, `docs/refactor/ESO_SCAO_DEVELOPMENT_PROMPT.md`, `docs/repository_optimization_ticket.md`); no tracked modifications |
| Commit/push policy | nothing committed, pushed, tagged or published; no governed baseline accepted or overwritten |
| Host | macOS 26 (Darwin 25.5.0) arm64, 8 CPUs, 16 GiB RAM |
| Python | 3.14.3 (`.venv`, editable install); NumPy 2.5.0, SciPy 1.18.0, pytest 9.1.1, ruff 0.15.22, mypy 2.3.0, psutil 7.2.2; HCIPy 0.7.0 installed but not exercised |
| Memory at start | 4.41 GiB available (psutil), 12.5 GiB of 14 GiB swap in use, pressure level fluctuating between normal (1) and warn (2) |
| Desktop budget | min(2 GiB, 12.5 % of 16 GiB, 25 % of available) ≈ 1.05–1.17 GiB throughout, set by available memory |
| Thread limits | every supervised job ran with `OMP/OPENBLAS/MKL/VECLIB_MAXIMUM/NUMEXPR_NUM_THREADS=2`, set by the supervisor before the child imported NumPy (verified by `tests/runtime`) |
| Large-run authorization | 2026-10-15, in chat: "you are allowed to run full and reference with 4.1-4.6 GB now", applied through `--authorized-budget-mib 4600 --authorization-note ...` and recorded in each manifest. Later the same day: "you are allowed to run the medium and medium-gate tiers (about 0.7 GB each) after the reference run" (`--enable-large-run`; these fit the ordinary desktop budget). |

## Status

| Ticket | Work package | Status |
| --- | --- | --- |
| ESO-00 | Baseline audit, ledgers, decisions, resource guard | DONE |
| ESO-01 | Versioned benchmark records, schema v5, identities | DONE (profiles revised to version 2: symmetric detector window) |
| ESO-02 | Passive frame observer | DONE |
| ESO-03 | Streaming monochromatic science and metrics | DONE |
| ESO-04 | Sparse DM operator, local probes | DONE |
| ESO-05 | Compact SH geometry, batched optics | DONE (1008/1024-sample `elt_scale` geometry tests passed) |
| ESO-06 | Streamed calibration, sparse response, LSMR | DONE |
| ESO-07 | Factory integration, benchmark tiers | DONE: CI, medium (fresh and reused), medium control gate and full capability gates passed; 2000-frame reference run completed with reused calibration; `test_full_spatial_scale_capability` not run under pytest (the same path ran through the CLI) |
| ESO-08 | Evidence, packaging, documentation | IMPLEMENTED_VALIDATION_PENDING: distribution, RSS, timing, docs and solver convergence done; sampling convergence missed its declared 2 % tolerance on the smoke tier; the 8 GiB host gate and medium/full convergence were not run |

## Resource policy and supervision (ESO-00)

`shwfs_ao.runtime.resource_guard` (standard library plus optional psutil)
implements section 2.3 of the prompt:

- `host_snapshot()` reads physical memory, available memory (psutil or
  `vm_stat`) and the *current* pressure level (`kern.memorystatus_vm_pressure_level`
  on macOS, PSI on Linux). It never uses swap counters.
- `preflight()` refuses before allocation when the margin-inflated (2×)
  estimate exceeds the budget, the largest new buffer exceeds 64 MiB, or the
  host is at warn/critical pressure. A caller may only lower the budget.
- `run_supervised()` starts one child in its own process group with thread
  limits. Every 0.5 s it sums the RSS of the whole group and reads pressure.
  A budget, timeout or pressure violation sends SIGTERM to that group only,
  then SIGKILL after 2 s, and the result is labelled RESOURCE_LIMITED or
  INTERRUPTED with its log kept.
- `tests/conftest.py` registers `--enable-elt-scale`; `elt_scale` tests skip
  without it whatever the marker expression. Each such test also checks the
  option itself, so a bundle without the conftest cannot run them.

Every scientific or test job in this session ran through this supervisor,
one process group at a time.

## ESO-00 — Baseline audit

- Base-revision compatibility snapshot (published profile hashes, component
  hashes, loop-history array SHA-256s and PSFs of `portfolio_2m_detector@4`
  and `eso_turbulence_2m_detector@1`):
  [`eso_scao_evidence/baseline_snapshot_e55754f.json`](eso_scao_evidence/baseline_snapshot_e55754f.json)
  (`scripts/eso_scao_baseline_snapshot.py`; 11.3 s, 132 MiB peak). The final
  re-run below compares against it.
- Baseline focused tests at the base revision plus the new guard: 255 + 87 +
  66 + 55 passed in four supervised batches (peaks 436, 95, 116, 190 MiB).
- Guard tests (`tests/runtime/test_resource_guard.py`, 17 tests, tiny
  synthetic children and stub probes): preflight rejection, large-test
  refusal without enablement, process-group aggregation, timeout with
  grandchild cleanup, SIGTERM-ignoring child killed after the grace period,
  pressure stop, and thread limits visible in the child before NumPy loads.

Dense allocations on the end-to-end path at 84×84 / 85×85 / 1008 samples, as
the code stood at the base revision:

| Seam | Dense allocation | Scalable replacement |
| --- | --- | --- |
| `DeformableMirror.__init__` | `influence_functions()` cube (5873×1008²×8 B ≈ 44 GiB) plus its hash and read-only copies | `LinearSplineDmOperator` (sparse support, ≈ 54 MB) |
| `DmActuatorProbeBasis` | a second copy of the cube | `LocalDmProbeBasis` (indices only) |
| `calibrate_interaction_matrix` | every ± probe map materialized up front, plus a hash of the full positive stack | grouped probes synthesized one group at a time |
| `InteractionMatrix` | dense 10224×5328 matrix plus full SVD diagnostics | `SparseInteractionMatrix` (40 896 nonzeros, 0.7 MB), no SVD |
| `_MaskedSvdReconstructor` | dense SVD per usable-row mask | `SparseLsmrReconstructor` (no factorization cache) |
| `ShackHartmannGeometry` | one full-pupil mask per lenslet (5112×1008² B ≈ 5 GiB), hashed by content | `CompactShackHartmannGeometry` (cell bounds plus local masks) |
| `NativeShackHartmannOptics` | `np.where` bounding box over the full pupil per lenslet per frame | per-lenslet boxes precomputed; batched FFTs |
| WFS ownership check | `stable_hash(geometry)` twice per frame (rehashes every mask) | same-object fast path (`geometries_match`), dense semantics kept otherwise |
| `LayeredFrozenFlowAtmosphere` | 10 × 2016² complex band coefficients (620 MiB) held | unchanged by default; opt-in `regenerate` mode (bit-identical frames) |
| `WfsMeasurement` telemetry | one `DetectorFrame` per lenslet per frame (≈ 250 MB transient at full scale) | unchanged (public contract); included in the memory estimate |
| Science propagation | 2016² complex FFT temporaries per wavelength per frame | unchanged; per-wavelength sum image only |

The existing `high_order_10m_*` (384-pixel, 48×48) profiles also exceed the
desktop budget when built: their dense influence cube is about 2.2 GB. No
test in the default selection builds them.

Decision records (operator, science-result, timing and identity contracts):
[`docs/eso_scao_benchmark.md`](../eso_scao_benchmark.md) and the assumption
ledger. The main decisions:

1. *Operator contract.* An opt-in `ScalableDmBackend` protocol
   (`spatial_operator_kind == "local_sparse"`) provides count, shape,
   identity, forward, adjoint, local influence and zero-support
   classification. The dense cube is a guarded compatibility method, and the
   dense path is unchanged.
2. *Science result.* `LongExposureResult` is a new container. Each
   wavelength reuses `PsfResult`, whose unit-flux single-wavelength contract
   holds, with sampling metadata identical to the ideal image so the
   canonical Strehl applies. Bookkeeping lives on the container.
3. *Timing.* R1's three-interval delay maps to `latency_frames = 2`. The
   canonical loop adds one frame, which is proven by a hand-built test.
   Detector exposure is recorded and not integrated.
4. *Identity.* Schema v5 adds the `scalable` block and two vocabulary items,
   all inexpressible in v1–v4, so no published hash moves. Batch size,
   thread counts, calibration-cache use and atmosphere band storage are
   execution options outside every identity, and the tests check this.
5. *Solver.* LSMR was chosen after a measurement on an 84×84 Fried gradient
   operator (5328 unknowns): about 270 iterations and 30 ms per solve at
   1e-8 tolerance, agreeing with a direct solve to 2e-8.

## ESO-01 — Versioned benchmark records

- Schema v5 (`io/configs.py`): `ScalablePathConfig` with DM operator, WFS
  geometry, calibration strategy, solver tolerances, iteration limit and
  non-convergence policy. `linear_spline` DMs and the
  `sparse_lsmr_tikhonov` reconstructor (`alpha` = damping relative to the
  RMS column norm) are v5-only and require the block. The block also
  requires native, detector-level, noiseless calibration and the
  controlled-subset projector.
- Profiles (generated by `scripts/generate_eso_scao_profiles.py`; a test
  checks the packaged files equal its output):
  `eso_scao_smoke_5m_software`, `eso_scao_medium_12m_derived`,
  `eso_scao_medium_12m_weak_gate` and `eso_drm_42m_scao_derived`, each at
  version 1 and version 2. Version 2 changes only the detector window
  (24 → 23 pixels; see [the window bias](#centroid-window-bias-version-1--version-2)),
  and the tiers run version 2. All eight config hashes are pinned in
  `tests/io/test_configs.py`. All 18 published profile hashes and nested WFS
  hashes are unchanged (same test).
- Ledgers: `resources/benchmarks/eso_scao_source_ledger.v1.json` (R1–R4,
  reference cases R3/R4 as `documented_not_runnable`, contradictions C1–C4)
  and `resources/benchmarks/eso_drm_42m_scao_derived.assumptions.v1.json`
  (rows S01–S14, A01–A12, T01–T02, P01), with
  `eso_drm_42m_scao_derived.assumptions.v2.json` for the version-2 profiles
  (A05c changed; `revisions` records why; `supersedes` names v1).
  `io/benchmark_ledgers.py` validates them. All are packaged, listed in `resource_manifest.json`, and load
  offline from the wheel.
- Tests: `tests/io/test_eso_scao_profiles.py` (19). Round trip of both
  versions; generator equality; every executable value covered by its
  version's ledger; version 2 differs from version 1 only in the window and
  records why; stated values equal; rejection of
  missing rows, a non-normative authority, an engineering row citing a
  source, missing tests, unknown classes, http URLs and runnable reference
  claims; malformed fractions, unsupported solver, noisy scalable
  calibration, a non-one-pitch spline, a missing or v4 scalable block, and an
  exposure/frame-clock mismatch. Loading profiles and ledgers stays under
  32 MiB and imports no backend, DM operator, SCAO assembly or HCIPy.

## ESO-02 — Passive frame observer

- `control/observation.py`: `FrameObservation` holds frame index, time,
  period, latency, usable flag and saturation, plus only the requested
  read-only snapshots of the atmosphere and pre-/post-update residuals.
  Snapshots are backed by immutable buffers. `FrameObserver` is the protocol.
  The observation point is after the frame's DM update and telemetry, before
  the next atmosphere sample.
- `control.loop.run_closed_loop(..., observers=())` and
  `experiments.scao.run_closed_loop(..., observers=())`. Observers are
  validated before any side effect, and an observer exception becomes a
  `ControlLoopError` naming the frame and time.
- Tests: `tests/control/test_frame_observation.py` (14). Event maps against
  an independent recursion for latency 0/1/2 with leak, fail-closed frames
  and stroke saturation. A latency-2 correction is first seen three frames
  after its measurement. Disabled versus no-op/multiple observers give
  identical loop hash, arrays, stream IDs and atmosphere timestamps.
  Mutation attempts fail and retained events never change. Only requested
  fields are copied, and the real SCAO runner is unchanged by observation.

## ESO-03 — Streaming long-exposure science

- `science/long_exposure.py`: `LongExposureConfig` (wavelengths, burn-in,
  stride, max samples, explicit weights, pre/post residual),
  `StreamingLongExposure` (observer; sum image per wavelength; cached
  zero-OPD ideal from the same propagator), `LongExposureResult` with
  selection, timing, quadrature, metrics (peak and on-axis Strehl, FWHM,
  EE50/EE80, radial profile) and the flux denominator.
- Tests: `tests/science/test_long_exposure.py` (10). Repeated static OPD
  equals one propagation, and zero OPD is ideal with Strehl 1. Opposite
  tilts give two half-height peaks (Strehl 0.49–0.52), whereas the mean OPD
  or recentring would give 1. Piston invariance; streaming equals a
  materialized weighted stack (rtol 1e-11, atol 1e-14). Selection, burn-in,
  stride, quadrature and span; empty-selection, invalid-weight, NaN and
  out-of-order failures; reset and reuse; retained memory constant from 3 to
  43 frames. The ideal image matches the analytic annular pattern: peak
  surface brightness equals A/λ² to 1e-12, and the shape error within 2 λ/D
  is 3.4e-3, 6.4e-4 and 2.5e-4 at 48, 96 and 256 samples. The canonical
  loop is unchanged when the accumulator observes.

## ESO-04 — Sparse DM operator

- `backends/native/dm_operator.py` (`LinearSplineDmOperator`, basis
  `separable_bilinear_tent_v1`) and `dm/model.py` (`ScalableDmBackend`, the
  operator path in `DeformableMirror`, `adjoint_opd`, `zero_support_mask`,
  `geometric_exclusion_ids`). `dm/config.py` adds `SCALABLE_INFLUENCE_MODELS`;
  the frozen `VALID_INFLUENCE_MODELS` sets are unchanged.
- Tests: `tests/dm/test_linear_spline_operator.py` (15). Against an
  independently assembled cube, random, one-hot interior, boundary and null
  commands agree to ≤ 1e-11 relative L2. The adjoint dot test is ≤ 1e-10;
  tents form a partition of unity (1e-14). Zero support is classified
  against the obstructed pupil, and partial inner/outer supports are kept.
  Storage is < 20 % of the dense cube, and dense access is guarded.
  Probe chunks equal full synthesis. Identity follows pupil and centre
  changes, and owned data is immutable. Command policy (IDs, dead/stuck
  precedence, clipping, saturation, sign) is identical to the dense DM. The
  mirror never calls `influence_functions()` on a test double that refuses
  it. All existing DM tests, including the frozen family hashes, pass
  unchanged.

## ESO-05 — Compact SH geometry and batched optics

- `wfs/shack_hartmann/compact_geometry.py` and
  `backends/native/shwfs_batched.py`. The isinstance checks in calibration,
  measurement and optics accept the compact geometry, and the per-frame
  ownership check no longer rehashes the same geometry object.
- Tests: `tests/wfs/test_compact_geometry.py` (31 run, 2 `elt_scale`). The
  partition equals the dense one for divisible, nondivisible (12/13-sample
  cells), odd, every-cell and large-obstruction cases. Spots, captured
  fractions, axes and sampling agree with the dense backend for zero, x/y
  tilt, piston and turbulent OPD at batch sizes 1, 7 and 10 000 (measured
  difference exactly 0). Detector slopes, validity and reference centroids
  agree (≤ 1e-11 px). Noise draws and validity do not depend on batch size.
  No dense masks and no geometry rehash per frame (instrumented test).
- `elt_scale`: `test_nominal_84_across_partition_at_1008_and_1024_samples`
  (geometry only) PASSED at 1008 and 1024 samples, run with
  `--enable-elt-scale` under the supervisor in the same batch as the medium
  tier tests (46 s, 411 MiB batch peak). These were treated as covered by
  the full-scale authorization. The full-tier runs below also build the
  1008-sample, 84-across geometry (5112 retained lenslets of exactly 12×12
  samples).

## ESO-06 — Grouped calibration, sparse response, LSMR

- `calibration/sparse.py`: `LocalDmProbeBasis` (eligible = not dead/stuck,
  illuminated, touches a retained lenslet; every exclusion recorded with its
  reason), `probe_groups`, `calibrate_sparse_interaction_matrix`
  (noiseless only, preflight before any measurement),
  `SparseInteractionMatrix` (CSR, forward/adjoint, guarded dense view,
  record round trip with content hash) and `SparseLsmrReconstructor`
  (Tikhonov objective, zero initial guess, telemetry, rejection policy).
  `experiments/calibration_cache.py` provides verified reuse.
- Tests: `tests/calibration/test_sparse_calibration.py` (14). The grouped
  calibration equals dense per-actuator central differences (atol 1e-12 ×
  scale, identical row validity and identities) with 2·groups + 1 sensor
  calls. Every eligible actuator participates. Groups are disjoint. The
  forward/adjoint dot test is ≤ 1e-10. Amplitude linearity over 5–40 nm is
  < 1e-3 and grows with amplitude. Invalid amplitude, noise-on, a missing or
  wrong label map, and non-local optics all make zero sensor calls. LSMR
  matches the SVD Tikhonov solution (command ≤ 1e-5, objective ≤ 1e-6) at
  three dampings. Piston/rank deficiency gives the minimum-norm solution.
  Rejected rows, all-invalid frames and coverage policy are handled, and
  non-convergence is rejected or explicitly accepted.

## ESO-07 — Factory integration and tiers

- `experiments/scao.py`: `ScaoExecutionOptions` (batch size, calibration
  cache, atmosphere band storage), the scalable path in `build_scao_system`
  (compact geometry, batched optics, sparse DM, grouped calibration, LSMR),
  and `SparseInteractionMatrix` accepted by the loop preflight.
  `backends/native/factory.py` takes the new keywords only when they are
  passed, so custom factories keep working.
- `experiments/eso_scao_benchmark.py` and `examples/run_eso_scao_benchmark.py`:
  tiers `ci`, `medium`, `medium-gate`, `full`, `reference`; a dry-run
  estimate that builds nothing; a supervised child; `--enable-large-run`;
  `--authorized-budget-mib` with a mandatory note that re-checks current
  pressure and headroom; outputs (`manifest.json`, `telemetry.npz`,
  `science_<λ>.npz`) under `AO_DEMO_OUTPUT_DIR`.
- Tests: `tests/experiments/test_eso_scao_benchmark.py` (9 default, 3
  `elt_scale`). Tier frame counts; large tiers, and runs shorter than their
  burn-in, refused before any build;
  dry runs build nothing; the full tier is refused on a 16 GiB desktop
  policy. The CI tier runs end to end: counts add up, zero saturation, all
  frames usable, residual < 0.3 × open loop, exact observer neutrality,
  ledger hashes recorded. Repeated runs reproduce hashes. Cache reuse skips
  calibration with an identical identity, and a tampered cache fails closed.
  Batch size is outside every identity. Noiseless slopes are invariant to
  the electron scale over 1e4–1e6 (≤ 1e-12 px). A symmetric local defocus
  reads a negative mean slope on the version-1 window and exactly zero on
  version 2. The scalable CI system matches an independent dense assembly
  end to end: post-update residual RMS within rtol 1e-4 (measured 1.5e-5)
  and applied commands within 1e-5 of their maximum after removing each
  frame's mean over the calibrated actuators (see
  [Deviations](#deviations) for the LSMR piston component).
- `elt_scale` tier tests: the two
  `test_medium_tiers_close_the_loop_with_full_retained_coordinates` cases
  PASSED (48 s, 311 MiB) after a fix. Their first run failed because the
  test's 20-frame cache-reuse rerun was shorter than the 50/30-frame burn-in,
  which `run_tier` only reported after the loop (`LongExposureError: no frame
  was selected`). The test now passes `burn_in_frames=10`, and `run_tier`
  refuses such a request before building. `test_full_spatial_scale_capability`
  was not run under pytest (see [Deviations](#deviations)).

All tiers below ran version 2 unless marked v1, through
`python -m shwfs_ao.experiments.eso_scao_benchmark` under the supervisor,
one process group at a time. Evidence files are in
[`eso_scao_evidence/`](eso_scao_evidence/); in the supervisor records the
session's local scratch directory is written as `<scratch>`.

| Tier | Status | Evidence |
| --- | --- | --- |
| `ci` | PASSED | [`ci_tier_v2_manifest.json`](eso_scao_evidence/ci_tier_v2_manifest.json): 2.6 s, 130 MiB, pressure normal; 96 calibrated actuators, 11 sensor calls; 64/64 solves converged; zero saturation. Open loop 1435 nm → 174 nm at frame 32 (233 nm mean over frames 8–31). 24-frame long exposure: Strehl 0.50 at 1.65 µm and 0.65 at 2.2 µm, peak on axis in both. Neutrality exact |
| `medium` | PASSED (scaling) | [`medium_tier_v2_manifest.json`](eso_scao_evidence/medium_tier_v2_manifest.json): 46.5 s including the observer-free rerun, 301 MiB, pressure normal. 416 lenslets; 533 laid-out actuators, 476 calibrated (13 zero-support, 44 without a retained lenslet); 5 groups, 11 sensor calls, 3328 nonzeros. 400/400 solves converged (≤ 109 iterations), zero saturation. After the 50-frame burn-in, mean open loop 1300 nm and mean residual 175 nm. 150-frame long exposure at 2.2 µm: peak Strehl 0.779, on-axis Strehl 0.779, FWHM 0.93 λ/D. Neutrality exact; 0.11 s per frame |
| `medium`, reused calibration | PASSED | [`medium_tier_v2_reused_manifest.json`](eso_scao_evidence/medium_tier_v2_reused_manifest.json): calibration loaded from the cache with verified identity; build 0.17 s against 1.06 s fresh. Loop hash, system hashes, telemetry and science SHA-256 identical to the fresh run |
| `medium-gate` | PASSED (control gate) | [`medium_gate_tier_v2_manifest.json`](eso_scao_evidence/medium_gate_tier_v2_manifest.json): 120 frames, r0 = 0.40 m at 500 nm. Mean residual after burn-in 71 nm against 449 nm open loop, an 84 % reduction (threshold 5 %); 100 % of frames usable (threshold 90 %); zero saturation. Strehl 0.96 at 2.2 µm, on axis. Its calibration hash differs from `medium`'s because the profile name enters the source notes of the DM and detector configuration |
| `full` | PASSED (capability) | see below |
| `reference` | COMPLETED (2000 frames) | see below |

Full spatial-scale capability run, version 2
([`full_tier_v2_manifest.json`](eso_scao_evidence/full_tier_v2_manifest.json),
[`full_tier_v2_supervisor.json`](eso_scao_evidence/full_tier_v2_supervisor.json)):

- COMPLETED in 110.4 s under the 4.6 GB authorization. The aggregate
  process-group peak was 1.44 GiB (1.51 GB `ru_maxrss` in the manifest),
  and pressure stayed normal. The calibration was fresh: 5 groups, 11 sensor
  calls, 40 896 nonzeros, 13.0 s build including calibration. It was written
  to a cache for the reference run.
- Counts: lenslets 7056 nominal, 5112 retained, 5112 calibration-valid.
  Actuators 7225 nominal, 5873 laid out, 5500 illuminated, 5328 calibrated;
  373 `zero_illuminated_support` and 172 `no_retained_lenslet_support`
  exclusions.
- Capability gate passed: 20/20 usable, nonzero, applied updates; 40/40 LSMR
  solves converged (≤ 248 iterations); zero saturation; observer neutrality
  exact. Open loop 1625 nm → 208 nm post-update residual at frame 20
  (372 nm mean over frames 5–19). The 15-frame image at 2.2 µm has peak
  Strehl 0.43 and on-axis Strehl 0.43: the peak is on axis. **20 frames do
  not establish settled AO performance.**
- Time per frame (one probe frame after the loop): atmosphere 0.74 s, SH
  measurement 0.97 s, reconstruction 0.027 s, DM 0.004 s, science 0.091 s;
  1.84 s per loop frame with science. RSS high-water marks: 809 MiB after
  the build, 1159 MiB after the loop, 1413 MiB after the component probe.

Reference run, 2000 frames, version 2
([`reference_tier_v2_manifest.json`](eso_scao_evidence/reference_tier_v2_manifest.json),
[`reference_tier_v2_supervisor.json`](eso_scao_evidence/reference_tier_v2_supervisor.json)):

- COMPLETED in 62.1 min under the 4.6 GB authorization; 1.64 GiB aggregate
  process-group peak; pressure normal throughout.
- Calibration reused from the full-tier v2 cache after field-by-field and
  content-hash verification (`054de99f…`); build 2.2 s against 13.0 s fresh.
  This is the full-scale reuse evidence.
- 2000/2000 usable, nonzero updates; 2000/2000 LSMR solves converged
  (≤ 248 iterations, 463 233 in total); zero saturation; every measurement
  valid in every frame.
- Residual: after the 200-frame burn-in, mean open loop 1683 nm and mean
  residual 173 nm. Window means (frames 20–100, 100–200, then 400- and
  600-frame windows) all lie within 172–174 nm, so the loop is settled. The post-update residual
  at frame 2000 is 160 nm.
- Long exposure over frames 200–1999 (1800 frames, 3.6 s) at 2.2 µm: peak
  Strehl 0.784 with the peak on axis (on-axis Strehl 0.784); FWHM 0.93 λ/D;
  EE50 radius 8.7 mas (ideal 6.7 mas); EE80 radius 170 mas.
- Against version 1: the residual dropped from 417 nm to 173 nm; the
  long-exposure peak Strehl is unchanged (0.778 → 0.784), and the on-axis
  Strehl rose from 0.20 to 0.78. A static tilt of 2.6e-8 rad on each axis
  over 42 m is θD/4 ≈ 273 nm RMS per axis, about 386 nm for both, and
  √(173² + 386²) ≈ 423 nm, close to version 1's 417 nm. The version-1
  residual was therefore dominated by the bias tilt, which moved the image
  without blurring it.
- The periodic atmosphere band repeated: the 33.7 m/s layer travelled
  134.7 m against the 84.1 m screen period (see
  [the erratum](eso_scao_evidence/v2_manifest_atmosphere_record_erratum.txt)
  for the manifest's travel field).
- 1.85 s per frame. Observer neutrality was not re-verified on this run,
  because it would double the hour; it was verified exactly on the CI,
  medium and full tiers with the same observer.
- One realization, noiseless, on a model with explicit assumptions: this is
  not a comparison with an ESO result.

Version-1 history (superseded results, kept as evidence):

- Full, first attempt (materialized atmosphere coefficients): stopped after
  21.6 s by the watchdog at 2.26 GB because the host reported **warn**
  pressure; RESOURCE_LIMITED. This led to the bit-identical `regenerate`
  band-storage mode, now the default for the full and reference tiers.
- Full, second attempt
  ([`full_tier_v1_manifest.json`](eso_scao_evidence/full_tier_v1_manifest.json)):
  COMPLETED in 98.8 s, 1.57 GB, calibration reused from the first attempt's
  cache with verified identity. The 15-frame image had peak Strehl 0.43 but
  on-axis Strehl 0.10, with the peak half a λ/D off in x and y. This was
  first read as unconverged tip/tilt.
- Reference, 2000 frames
  ([`reference_tier_v1_manifest.json`](eso_scao_evidence/reference_tier_v1_manifest.json)):
  COMPLETED in 62.1 min, 1.60 GB group peak, pressure normal. The fresh
  calibration hash equalled the cached one (`8f1d9b50…`). 2000/2000 usable
  frames, every solve converged, zero saturation; open loop 1675 nm → 417 nm
  mean residual after the 200-frame burn-in. The long exposure kept its peak
  at (+0.5, +0.5) λ/D: peak Strehl 0.78, on-axis Strehl 0.20. A tilt that
  survives 1800 frames is not a convergence transient, which led to the
  diagnosis below.

## Centroid window bias (version 1 → version 2)

- Version 1 used the whole 24-pixel Nyquist canvas as the COG window, which
  has one more row and column on the negative side of the optical-axis
  pixel. With every lenslet given the same symmetric local defocus (true
  mean slope zero), the 24-pixel window reads −0.00024, −0.00100 and
  −0.00505 px at 100, 200 and 400 nm; the 23-pixel window reads exactly 0
  ([`centroid_window_bias_diagnostic.txt`](eso_scao_evidence/centroid_window_bias_diagnostic.txt),
  script beside it).
- In closed loop on the smoke tier, the residual wavefront after burn-in
  held a mean tilt of (+2.6, +1.8)e-8 rad with 24 pixels and
  (+0.06, −0.66)e-8 rad with 23, against a frame-to-frame scatter of
  (1.7, 1.2)e-8 rad. The residual RMS changed little (189 → 184 nm), but at
  42 m and 2.2 µm 2.6e-8 rad is 0.5 λ/D, one science pixel, which is the
  offset the version-1 reference image shows
  ([`v1_long_exposure_peak_offset.txt`](eso_scao_evidence/v1_long_exposure_peak_offset.txt)).
- Fix: version-2 profiles with `wfs.detector_window_px = 23`, nothing else
  changed (a test checks this), and the v2 assumption ledger with a
  `revisions` entry for A05c. Version 1 stays loadable and pinned. The fix
  removes a measured sensing bias and was not chosen for a target Strehl.
  On the full tier the 15-frame peak Strehl went from 0.426 to 0.428 and the
  on-axis Strehl from 0.10 to 0.43.
- Not examined: every published profile with a detector window
  (`fast_2m`, `portfolio_2m`, `research_2m` and `eso_turbulence_2m` at pad 3,
  `high_order_10m_hcipy` at pad 4) also uses an even window (8–28 pixels). Whether their crop has the same one-sided
  asymmetry was not checked, and they were not changed.

## ESO-08 — Evidence, packaging and documentation

- Packaging: `pyproject.toml` ships `benchmarks/*.json`; the resource
  manifest was regenerated (68 resources); the wheel/sdist inventories in
  `tests/test_wheel_install.py` and the wheel-smoke manifest list the new
  modules and tests. Distribution check after the version-2 changes
  (`python -m build`; 25 s, 330 MiB): wheel and sdist built; the 21 checked new
  modules and resources are in the wheel; 110 bundle tests passed (6
  skipped) against the wheel installed outside the checkout; the CI tier ran
  `eso_scao_smoke_5m_software@2` from the installed wheel (2.1 s).
- Documentation: [`docs/eso_scao_benchmark.md`](../eso_scao_benchmark.md)
  (including the window revision), README section "ESO-derived 42 m SCAO
  benchmark" (an owned README smoke block), `docs/README.md` index,
  `docs/architecture.md` (observers, scalable path, `shwfs_ao.runtime`).
- Memory: full-process peak RSS from the supervisor (aggregate process
  group) and `ru_maxrss` per manifest. The accumulator's constant retained
  memory is structurally tested. The O(frames × actuators) command history
  is the only frame-proportional state (2000 × 5873 × 8 B × 2 = 188 MB at
  the reference length).
- Sampling and solver convergence on the smoke tier
  ([`convergence_study_smoke_v2.json`](eso_scao_evidence/convergence_study_smoke_v2.json),
  `scripts/eso_scao_convergence_study.py`; 88.7 s, 169 MiB). Three
  realizations per setting, 200 frames, 50-frame burn-in, long exposure at
  2.2 µm. The criterion was declared before the run: the two finest settings
  agree within 2 % in Strehl and EE50.

  | Scan | Setting | Peak Strehl | EE50 (mas) | Residual (nm) |
  | --- | --- | --- | --- | --- |
  | samples per lenslet | 8 | 0.57 ± 0.27 | 374 ± 488 | 542 ± 594 |
  | | 12 | 0.744 ± 0.030 | 81.2 ± 7.0 | 191 ± 12 |
  | | 16 | 0.766 ± 0.010 | 76.9 ± 2.6 | 181 ± 4.5 |
  | LSMR tolerance | 1e-6 | 0.7439 | 81.21 | 190.9 |
  | | 1e-8 | 0.7439 | 81.21 | 190.9 |
  | | 1e-10 | 0.7439 | 81.21 | 190.9 |

  - **Solver: converged.** The finest two tolerances agree to 5e-6 in Strehl
    and 8e-6 in EE50.
  - **Sampling: not converged at the declared tolerance.** 12 → 16 samples
    changes the mean Strehl by 2.8 % and EE50 by 5.6 %, beyond 2 %. The
    study cannot resolve 2 %: the phase screens are drawn on each sampling's
    own grid, so the realizations are not paired (open-loop RMS differs
    between settings for the same index), and with three realizations the
    standard error of the Strehl difference is about 2.3 %. The SH field of
    view also scales with the sampling (pad 2: s λ/d), so the scan changes
    two things at once. Reported as found; nothing was re-tuned.
  - At 8 samples per lenslet (15-pixel window, 8 λ/d field), realization 1
    lost lock: the loop held 200–300 nm until about frame 115, then the
    valid-measurement fraction fell to 0.60–0.89 and the residual grew to
    2.5 µm, above the open-loop 1.0–1.4 µm. The other two realizations
    closed normally. Not diagnosed further.
  - Medium- and full-scale convergence were not run.
- **8 GiB host gate: NOT_RUN_RESOURCE_POLICY.** The desktop runs were
  authorized at 4.6 GB, not on an 8 GiB host.

## Final verification

All on the final worktree, through the supervisor, one process group at a
time, pressure normal throughout.

| Check | Result |
| --- | --- |
| Regression, `-m "not hcipy and not slow and not elt_scale"`, seven batches | 1870 passed, 18 skipped, 0 failed: runtime/core/detector/compat/experimental 401; control/science/dm/wfs/calibration 543; io/docs/backends/cross_backend 446 (15 skipped); experiments 114; notebooks and top-level tests 244 (3 skipped) + 120; wheel install 2. Longest batch 251 s, largest peak 782 MiB |
| `elt_scale` tests run | geometry 1008 and 1024 samples, medium and medium-gate tiers: 4 passed (medium after the test fix above) |
| Experiments batch after the atmosphere-record fix | 114 passed (43 s, 287 MiB) |
| `ruff check src tests scripts examples` | clean |
| `mypy` (project configuration) | no issues in 115 source files |
| Compatibility snapshot ([`baseline_snapshot_final.json`](eso_scao_evidence/baseline_snapshot_final.json)) | identical to the base revision's for both published profiles (config, component and loop hashes, loop-history SHA-256s, PSFs); differences are timings, git status, and the eight new benchmark profile hashes |
| `scripts/run_readme_smoke.py --section native` | both owned README blocks passed (212.8 s, 178 MiB) |
| Distribution check | see ESO-08 |

## Traceability

| Requirement / assumption | Source | Config field | Implementation | Test | Evidence |
| --- | --- | --- | --- | --- | --- |
| 42 m, ε = 0.28 | R2 | `telescope_diameter_m`, `wfs.central_obstruction_ratio` | `core.geometry.build_pupil_geometry` | `test_ideal_image_matches_the_analytic_annular_pattern_and_converges` | full manifest |
| r0, L0, 10 layers | R1 | `atmosphere.*` | `backends/native/layered_atmosphere.py` | `tests/backends/native/test_layered_atmosphere.py`, `test_layered_band_storage.py` | full manifest |
| 84×84 SH, 85×85 DM | R1 (adapted) | `lenslets_across`, `actuators_across` | compact geometry, sparse DM | `test_compact_geometry.py`, `test_linear_spline_operator.py` | full manifest counts |
| linear spline (A06) | R1 family + assumption | `dm.influence_model`, `scalable.dm_operator` | `LinearSplineDmOperator` | `test_forward_matches_an_independently_assembled_dense_cube` | — |
| symmetric COG window (A05c, v2) | assumption | `wfs.detector_window_px` | detector-level SH centroiding | `test_symmetric_window_removes_the_centroid_bias`, `test_version_two_changes_only_the_detector_window_and_records_why` | `centroid_window_bias_diagnostic.txt` |
| 3-interval delay (S13, A10) | R1 | `controller.latency_frames` | `control/loop.py`, `controller.py` | `test_latency_two_correction_is_first_seen_three_frames_after_its_measurement` | manifest `timing_semantics` |
| noiseless sensing (S14, A09) | R1 | `detector.*`, `*.include_noise` | detector-level sensor | `test_noiseless_slopes_are_invariant_to_the_electron_scale` | — |
| full-coordinate calibration | prompt ESO-06 | `scalable.calibration_strategy` | `calibrate_sparse_interaction_matrix` | `test_grouped_calibration_equals_dense_per_actuator_differences` | full manifest `calibration` |
| LSMR (A07b, A12) | assumption | `reconstructor.*`, `scalable.solver_*` | `SparseLsmrReconstructor` | `test_lsmr_matches_the_dense_tikhonov_solution` | manifest `solver`, convergence study |
| intensity long exposure (A11) | prompt ESO-03 | runner burn-in, `science.psf_pad_factor` | `StreamingLongExposure` | `test_opposite_tilts_broaden_the_image_instead_of_cancelling` | `science_2200nm.npz` |

## Deviations

- The benchmark profiles were revised to version 2 during the session (the
  window bias above). Version-1 results are kept as superseded evidence.
- The medium, medium-gate, full and reference version-2 manifests record
  `max_travel_m = 0` and `periodic_band_repeated = false`. `run_tier` read
  the atmosphere after the component-timing probe had reset it. Fixed:
  the record is now captured before the probe, and the CI test checks it.
  The correct values are deterministic and listed in
  [`v2_manifest_atmosphere_record_erratum.txt`](eso_scao_evidence/v2_manifest_atmosphere_record_erratum.txt).
  The CI v2 evidence was regenerated after the fix and is otherwise
  bit-identical. The same manifests carry the old gate note ("20 frames …"),
  which is wrong for the reference run; the note now states what the gate
  checks.
- At full scale the layered atmosphere's band coefficients are regenerated
  each frame instead of held (bit-identical, tested). This is execution
  only, with no change of model or identity.
- `ReconstructorConfig.alpha` means an absolute parameter for `tikhonov` and
  a relative damping for `sparse_lsmr_tikhonov`. This is documented in the
  class and the ledger.
- LSMR stops at atol = btol = 1e-8 and leaves a small component along the
  nearly unsensed DM piston (about 4e-10 m per frame on the CI tier) that an
  exact Tikhonov solve does not. It changes neither the piston-removed
  residual nor the image. The dense-assembly test therefore compares
  commands after removing each frame's mean and bounds that mean separately.
- `test_full_spatial_scale_capability` (pytest, `elt_scale`) was not run: it
  calls `run_tier("full")` in-process, and the supervisor CLI can only lower
  the 1.17 GiB desktop budget, below the 1.5 GB the full tier needs. The same
  `run_tier` path ran through the benchmark CLI under the authorized budget
  (above).

## Resume checklist

1. Run the 8 GiB-host validation and medium/full-scale sampling convergence
   on a suitable host; a paired-realization design (one screen grid
   resampled per setting) or more realizations would be needed to resolve a
   2 % criterion.
2. Decide whether the published detector-level profiles need the same window
   check.
3. Nothing is committed. If commits are wanted, follow the repository's
   authorship rule (Xu Han only, no co-author trailers).
