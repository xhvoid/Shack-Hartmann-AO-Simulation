# Predeclared staged experiment protocols (S4 A1, E2, E3)

Written before any governed run, for the exact tree `5514285`. Every number
that a decision depends on is stated here; the analysis of a stage is read
only after its stage completes, and nothing in a result changes this text.
Once approved, amendments are appended as dated sections and never rewrite
an earlier rule. Revision 2 (2026-10-22, before approval, review round 1):
sections 1.6, 1.7, 2.3, 2.4, 2.5, 3.3, 4, 5 and 7 were revised; the list of
changes is in `README.md` section 8. Revision 3 (2026-10-22, before
approval, review round 2): sections 0, 1.6, 1.7, 2.3, 2.5, 5 and 7 (E0
equivalence band, degrees of freedom over admissible units, the model's
delayed injection and single mask); `README.md` section 9. Revision 4
(2026-10-22, before approval, review round 3): sections 1.6, 1.7, 5 and 7
(the operator the loop used as the model's mask, the mask-variable
exclusion, and "not expressible" never read as a departure); `README.md`
section 10. Revision 5 (2026-10-22, before approval, review round 4):
sections 0, 1.6, 1.7 and 7 (the operator exclusion decided by two
quantified error bounds instead of a frame-count threshold, burn-in state
included; one authoritative exclusion list in 1.6 (iv)); `README.md`
section 11. Revision 6 (2026-10-22, before approval, review round 5):
sections 1.6, 1.7 and 7 (the carried-state bound measured from the run's
first analysed block with the loop's own sensitivity and entering the
closure test as the model's systematic budget beside the operator error;
the covariance of rows outside the modal operator bracketed, never zero;
the operator exclusion reduced to the operator error and the
not-assessable cases); `README.md` section 12. Revision 7 (2026-10-22,
before approval, review round 6): sections 1.6, 1.7 and 7 (the carried
state measured, not bounded: the command-difference trajectory of the
whole run reconstructed from both arms' centroids and operators through
the controller law and checked against the measured series, the
prediction made conditional on it; the covariance of a barely used lenslet
bracketed from its own frames and the sensor model only); `README.md`
section 13.

## 0. Rules common to every stage

**Identity.** One stage, one series: one producing host, one locked
environment, one code identity (`README.md` section 2). The record names
them; a resume under another producer is refused by the drivers and is not
attempted. Records go to a caller-owned, git-ignored directory
`outputs/post_t2/<stage>/<series>/` on the producing host; historical
records are never overwritten (the drivers refuse) and are not relabelled.

**Units of inference.** Root seeds (S4 A1) or realization indices (E2, E3)
are the independent units. Frames within a run are correlated and are never
counted as independent samples; within-run errors come from block means with
a predeclared plateau rule (section 6). Magnitudes within a seed (S4 A1) and
settings within a realization (E2 twin arm, non-pupil axes) are paired.

**Intervals.** Student t with `n_adm - 1` degrees of freedom over the
**admissible** units, `n_adm` being the units that remain after the
predeclared exclusions of the stage (refused rows, a missing realization,
and for S4 A1 the three exclusions listed once in 1.6 (iv)); the quantile follows
the count actually used (`t_0.975` = 2.776 at 4 dof, 3.182 at 3 dof, 4.303
at 2 dof, 12.706 at 1 dof, 2.365 at 7 dof, 2.262 at 9 dof) and is never the
planned count's quantile when units were excluded. Every interval is
reported with its `n_adm`. A statistic over fewer than two admissible units
has no interval and its outcome is "not expressible" (or "not classified"
in E2). A "resolved" change is one whose interval excludes zero; the
drivers' 2-SE flags are screening flags, not claims.

**Excursions.** An excursion is flagged by the rules in section 6, listed
with its trace, and kept in every statistic. No run is deleted, repeated,
replaced or down-weighted because of its value. No run is added because a
result looks attractive; the only additions are the predeclared extensions in
1.7 and 2.5, triggered by precision, not by direction.

**Failed hypothesis versus implementation defect.** A predeclared hypothesis
that the data reject is a failed hypothesis and stays recorded (the 12 m
inverse-photon law of LIM-18 is the standing example). An implementation
defect is suspected only when a contract is violated: a record or sidecar
fails the drivers' own validation, the arms of one setting see different
open-loop series, a row or lenslet layout changes within a run, a recorded
scalar disagrees with its recomputation from the sidecar, a protocol field
differs from the plan, or the twin (noiseless) arm rejects a reconstruction
at a magnitude where the recorded studies never did. Such a case stops the
stage and is reported with a minimal reproduction; it is not analysed as a
result.

**Negative record.** `docs/refactor/detector_level_evidence/det09_noise_isolation_12m_v3.json`
and its 2 m companion stay intact. The traced 12 m series is a new record
under the runner's own name `det09_noise_isolation_12m_traced.json` in its
own directory.

**What no stage closes.** A software pass, a converged numerical axis or a
reproduced scalar does not close S4, AR-006 or LIM-18 (they need the
explanation or bounding of the recorded departures), AR-007 (it needs the
governed 12 m and 42 m scans with their declared criteria) or LIM-01 (it
needs measured instrument data). Section 5 states, per stage, the sentence
that can be written if the stage succeeds.

## 1. Stage S4 A1: traced paired noise isolation at 12 m

### 1.1 Command and configuration (exact)

```bash
python scripts/run_detector_level_evidence.py \
    --output-dir outputs/post_t2/s4_a1/<series> \
    noise-isolation-12m-traced --enabled-by-user "<YYYY-MM-DD: the user's wording>"
```

Run under the authorized-budget launcher (`pilot_requests.json`, request
`S4-A1`). The command is `NOISE_ISOLATION_12M_TRACED`
(`scripts/run_detector_level_evidence.py:1180-1190`): profile
`det_emccd_12m_medium_derived@3` with the source magnitude overridden by
`with_magnitude` (`detector_physics.source.ab_magnitude`; nothing else
changes), magnitudes `m_AB` 8, 9, 10, 11, root seeds 71-75, 400 frames,
burn-in 100, `ScaoExecutionOptions(telemetry_level="summary")` (materialized
bands, batch 512), both arms in the recorded order (`noise_on`, then
`operating_expectation`), block length 25 frames, propagation weights on,
residual maps retained for m8, m9, m10 at seed 71 and m11 at seed 72.
Record: `det09_noise_isolation_12m_traced.json` plus one sidecar per run,
`det09_noise_isolation_12m_traced__m<k>__seed<s>.npz`, under series
protocol 4 and diagnostic protocol 1.

### 1.2 Independent units, pairing, order

Five root seeds per magnitude are the units (20 paired runs). Within a seed
the four magnitudes share the atmosphere realization (index 0 under that
seed), the persistent maps and the calibration masters, so magnitudes are
paired within a seed. The two arms of one run share everything but the
detector draws. Runs execute magnitude by magnitude, seed by seed, in one
process; the record is rewritten after each run and a resume reuses only
runs whose protocol matches.

### 1.3 Fixed physical quantities (profile `@3`, SHA-256 `03b27829…`)

| Quantity | Value |
| --- | --- |
| Telescope, pupil | D = 12 m, obstruction 0.28, 288 pupil samples (12 per lenslet), 24 x 24 lenslets, 25 x 25 linear-spline actuators, stroke 100 um OPD-equivalent |
| Atmosphere | `native_layered`, ESO ten-layer profile, r0 = 0.13 m at 500 nm, L0 = 25 m, winds along +x, materialized bands; one realization per root seed |
| Timing | 500 Hz, exposure 2 ms, one atmosphere sample per frame (left-point, n = 1), latency 2 frames |
| Control | gain 0.3, leak 0, sparse LSMR with relative damping 0.1, `min_valid_fraction` 0.5, reset after 2 rejected frames (`decay_per_rejected_frame` 1.0) |
| Calibration | grouped noiseless central differences, 20 nm probes, internal source 2500 detected e- per full subaperture |
| Camera | `synthetic_emccd_coupled@1`: QE 0.90, EM gain 300, read noise 60 e- output (0.2 e- input-referred), 15 e-/ADU, CIC 0.005 e-/px, register 8e5 e-, coupling 1 % nearest and 0.2 % diagonal |
| Sampling | isolated blocks, 15 px window, 1 px guard, MFT pixel-integrated k = 4, pixel scale 6.976e-7 rad, diffusion 0.2 px, Gauss-Legendre 3 nodes on 600-900 nm |
| Processing and gates | estimated products from 32 frames each, zero-weight bad pixels, known per-pixel gain, no negative clipping; flux gate 100 e-, peak-SNR gate off, sigma gate 0.5 px, clipping gate 0.15, `detector_covariance_v2` support gates |
| Photometry | AB flat f_nu source, throughput 0.4 excluding QE, sky 20.5 mag/arcsec^2; recorded detected e- per full subaperture 2541, 1012, 403, 160 at m_AB 8, 9, 10, 11 |
| Science | 2.2 um, pad 2 (not used by this stage's endpoints) |

### 1.4 Endpoints and units

| Endpoint | Definition | Unit |
| --- | --- | --- |
| P1 `DeltaV` per magnitude | mean over analysed frames of the piston-removed pupil mean square of (noisy minus twin) post-update residual map; seed mean and t interval over 5 seeds; per-run block SE at the plateau length | nm^2 (recorded in m^2) |
| P2 E0 ratio | realized centred variance of `c_noisy - c_expected` on the noisy arm's own operating state over the model `sigma^2`, equal-weight and propagation-weighted, on the lenslets valid, supported and finite in every analysed frame; also split by SNR_T tertile and by clipping class (below or above 0.05 expected flux outside the window) | dimensionless |
| P3 E1 proportionality | per-seed slope of `log DeltaV` against `log P` over the gate-quiet magnitudes, where `P = sum_r w_r sigma_r^2` is the propagated realized sensor noise (propagation weights of the sidecar, E0 variances); mean slope and t interval over seeds; descriptive, as in the T1 analysis | dimensionless |
| P4 Mask and gate activity | mask-disagreement row-frames fraction per run; per-gate activity (flux, SNR, uncertainty, clipping) and support loss per frame; rejected reconstructions, recovery actions and DM saturation fraction per arm | fractions |
| P5 Loop model ratio | `rho = DeltaV / DeltaV_pred` per run, with `DeltaV_pred` the exact linear model's finite-window prediction from the run's realized noise covariance (1.6); per magnitude its five-seed mean and t interval (the closure test of 1.7); beside it, descriptively, `DeltaV / P` and the unit-feedback factor `kappa` | dimensionless |
| P6 Replay comparison | the seven recorded quantities of every run against `det09_noise_isolation_12m_v3.json` (`--historical`): relative difference per run | dimensionless |

The recorded flat-wavefront model column (`predicted_centroid_variance_px2`)
and the recorded log-log slope against `N_e` are reported again exactly as
the 2026-10-16 protocol defines them, beside the new quantities, so the
negative result is re-read on the new record without being re-interpreted.

### 1.5 Predeclared analysis

1. Validate the record and every sidecar with the runner's own validator
   (a second invocation with nothing to run) and with
   `scripts/analyze_noise_isolation_traces.py` (`--historical` the committed
   12 m record, `--gate-quiet-labels m8,m9,m10`, default block lengths
   1, 5, 10, 25, 50, 75, bootstrap 2000 descriptive only).
2. P6 first: a run whose seven quantities differ from the committed record by
   more than 1e-3 relative at a gate-quiet magnitude is an excursion to
   investigate before anything else is read (expected cause: a validity gate
   flipping on host roundoff; evidence: the mask traces). Bitwise agreement
   is not expected across hosts and is not a criterion.
3. Gate-quiet domain: the data-driven rule (mask disagreement below 0.1 % of
   row-frames after burn-in, no rejected reconstruction, no recovery action in
   either arm) applied per run, reported beside the predeclared labels; m11 is
   expected to be gate-active and is reported, never fitted.
4. P1, P5, P2 on the gate-quiet runs; P3 over the gate-quiet magnitudes of
   each seed; P4 for every run.
5. Temporal-block sensitivity and excursion flags (section 6) for every run.
6. The alternative model (1.6) is applied only if its implementation checks
   (1.6, "Justification before use") and pilot P2b were recorded before this
   analysis was read; its prediction per run is computed from the run's own
   sidecar, and the closure test of 1.7 is applied per gate-quiet magnitude.

### 1.6 The alternative statistical/physical model and its justification

The first-order bias band (the model sigma low by about `4/SNR_T^2` near the
support floor) is a hypothesis about the sensor model, not an acceptance law.
Closure of the loop question needs a model whose prediction does not rest on
that band. The proposal (revised in review round 1; the earlier draft used
the scalar unit-feedback factor `kappa` alone) is the exact linear closed
loop's response to the realized sensor noise, with the reconstructed spatial
feedback included.

- **Model.** Loop of technical reference 4.2 (`controller.update`: leaky
  integrator, gain `g`, leak `l`, queue latency `d`), calibrated interaction
  matrix `M` (rows x controlled actuators), reconstructor `R` as a linear
  map on the fixed row mask (`reconstructor_matrix`), white measurement
  noise `n_k` of covariance `Sigma`. The command difference between the
  noise-on arm and its noiseless twin (same atmosphere, same calibration)
  obeys `dc_{k+1} = (1 - l) dc_k - g L dc_{k-d} + g R n_{k-d}` with
  `L = R M`. The two arms start from the same command, so the covariance of
  the state `x_k = (dc_k, ..., dc_{k-d})` is the transient
  `P_{k+1} = F P_k F^T + G Sigma G^T` from `P_0 = 0`, and the prediction for
  a run is the mean over its analysed frames of
  `DeltaV_pred,k = tr(Gram Cov(dc_k)) / N_pupil`, `Gram = W_c^T W_c`, with
  `W_c` the piston-removed pupil response of the controlled actuators: the
  expectation of the recorded `delta_v_m2` (piston-removed pupil mean square
  of the noisy-minus-twin residual map). The stationary limit (discrete
  Lyapunov equation) is reported beside it; the two differ when weakly fed
  back modes have time constants that are not short against the run.
  The model is a fixed-mask model, so its operator is **the operator the
  loop used**: the primary rule (`effective`) takes the row set the noisy
  arm's reconstructor actually used in the plurality of analysed frames (the
  sidecar's per-frame effective row masks), probes `R` on exactly that set,
  and takes `Sigma` as the realized covariance of `c_noisy - c_expected`
  per lenslet (2 x 2 blocks, x/y correlation kept, `ddof = 1`) over the
  frames in which that operator was in use. Two quantities bound the error of
  taking that operator as fixed, and no frame-count threshold does (review
  rounds 4 and 5): (1) the **operator error**: the same transient
  propagated with the noisy arm's actual operator of every frame of the
  run, burn-in included (each distinct effective mask probed once; the
  increment released at update `k` carries the operator of frame `k - d`),
  so the state the loop carried into the analysed window under whatever
  operators the burn-in used is accounted for; its relative difference
  from the modal-operator prediction is the operator error, reported with
  its two parts (carried in from burn-in; operator changes inside the
  window). A row outside the modal mask whose lenslet has fewer than 10
  usable analysed frames has no covariance estimate of its own: its
  lenslet's block is bracketed between zero and an upper bound built from
  that lenslet's own data and the sensor model only, per axis the larger
  of the 97.5 % chi-square upper confidence bound of its realized
  variance over its usable frames (two or more) and twice the sensor
  model's variance at its own spot in the frames its rows were effective,
  the block bounded in the positive-semidefinite order by `diag(u_x +
  sqrt(u_x u_y), u_y + sqrt(u_x u_y))`, which dominates any cross term;
  the transient is propagated with both ends, the operator error is the
  worse of the two, a bracket wider than the tolerance leaves the error
  undetermined, and a lenslet with neither bound does too (nothing that
  contributes is ever set to zero, and no other lenslet stands in for an
  unobserved one). (2) the **carried state, measured**: the
  sidecar holds both arms' reference-subtracted centroids and the rows
  each arm's reconstructor used in every frame, and the controller's law
  is known (`c_{k+1} = (1 - l) c_k + g released_k`, the increment computed
  at frame `k` released at update `k + d`), so the command difference of
  the whole run is reconstructed frame by frame, `dc_{k+1} = (1 - l) dc_k
  + g (R^noisy m^noisy - R^twin m^twin)_{k-d}`, from identical initial
  commands, with each frame's operator probed on its own effective mask
  (the reference cancels in the difference; measurement non-linearity is
  immaterial, the loop saw these centroids). The reconstruction is
  checked, not assumed: the per-frame pupil mean square of the
  reconstructed difference must reproduce the sidecar's `DeltaV_t` to a
  relative rms of 1e-3 (1.6e-5 on the ci geometry with the 12 m damping;
  where the sidecar retains residual maps the state fitted from the maps
  agrees with the reconstructed one to the same level), which verifies
  the controller law, the operators, the units and the absence of
  clipping on that run; a run whose series the reconstruction does not
  reproduce is **not assessable** (the ci geometry with its own damping
  0.001 fails it: its iterative reconstructor is not one linear operator
  there; the clipped 2 m runs fail it). With the trajectory known, the
  state the loop carried into the window (the command difference and the
  increments still queued at the first analysed frame) is propagated
  under the modal loop with no further noise; its window mean `D` is the
  exact contribution of the carried state, and the **conditional
  prediction** `DeltaV_pred = W_cold + D` replaces the unconditional one,
  `W_cold` being the model's window value for the noise computed from the
  first analysed frame on (the cold start), the only part the model still
  predicts. No carried-state bound is needed; the content of the
  reconstructed state in directions the modal operator cannot produce is
  reported as a measured fact (zero without clipping or operator
  changes), and the fallback bound of revision 6 (`gamma` over every
  state against the measured first block) is kept as a diagnostic. A run
  is **operator-consistent** when its operator error (the part of the
  time-varying difference from operator changes inside the window, at
  the worse end of the bracket) is within the predeclared 2 %;
  **mask-variable** when it is not; **not assessable** when the
  time-varying prediction cannot be computed (more distinct operators
  than the tool's probe budget, an operator its reconstructor refuses, a
  bracketed lenslet with neither bound), the bracket is wider than 2 %,
  or the reconstruction does not reproduce the series. The run's
  **systematic budget** is `u = |operator error| + r`, `r` the
  reconstruction's relative rms, and the closure test of 1.7 subtracts it
  from its band. The fractions of analysed and burn-in frames in which
  each arm used the modal operator are reported as diagnostics only. Two telemetry-based
  rules are reported as sensitivities, never as the primary: **available**
  (lenslets valid,
  supported and finite in at least 90 % of the analysed frames, covariance
  over each lenslet's own valid frames) and **strict** (lenslets valid in
  every analysed frame, the E0 summary's support). A rule whose mask the
  reconstructor refuses under its own valid-fraction or rank policy is "not
  defined" for that run. Secondarily, `Sigma` is the flat-wavefront
  `detector_covariance_v2` model (a-priori, no run needed; it under-predicts
  the realized noise at the operating spots, by a factor of about two at
  2 m m5 and at the ci geometry). Under the 12 m
  damping (`sparse_lsmr_tikhonov`, relative damping 0.1) the eigenvalues of
  `L` are `s_i^2 / (s_i^2 + damp^2) < 1` for weakly sensed modes; the earlier
  scalar factor `kappa * sum_r w_r sigma_r^2` (with `kappa = 0.35005` at
  `g = 0.3, d = 2` and the sidecar's propagation weights `w_r`) is this
  model's reduction for `L = I` and diagonal `Sigma`, and is reported beside
  the exact value as `scalar_reduction`. Implementation:
  `tools/linear_loop_noise_model.py`; derivation and checks:
  `SOURCE_READING_NOTES.md` section 3. Assumptions: fixed mask, linear sensor
  response, temporally white noise, no stroke clipping, no recovery action,
  stationary loop (the spectral radius of `F` is reported).
- **Justification before use.** (i) The derivation is checked against the
  controller's update equation and the command projector (notes section 3);
  the tool's `--self-test` reproduces `kappa` from the Lyapunov solution in
  the unit-feedback limit to 1e-15, keeps decoupled modes' variances, and
  reproduces the stationary value from the window propagation when the
  transient is short. (ii) Implementation checks on ungoverned data, done in
  review round 1 (`records/cloud_checks/round1/SUMMARY.md`): on the 2 m
  profile (TSVD, 13 controlled actuators) `L = I` to 4e-15, so the exact
  model and the scalar factor agree to the x/y-correlation term (within
  0.4 %) and the 2 m result of the first session stands as a result about
  the whole linear model, not about the omitted feedback: `DeltaV /
  DeltaV_pred` over 8 seeds is 0.936 +/- 0.060, 0.892 +/- 0.076 and
  0.860 +/- 0.050 (t, 7 dof; effective rule; every run operator-consistent
  with an operator error below 0.03 %, both arms under the modal operator
  in at least 99.3 % of the frames; the carried-state bound, with
  `gamma = 0.167` (every mode at unit feedback, so a state's whole effect
  falls inside the first block of the 150-frame window) and first-block
  excesses of -37 % to +44 % against block scatters of 6-33 % over six
  blocks, is 2-17 % per run and the mean budget `u_bar` 8.5 %, 9.5 % and
  6.9 % at m5, m6, m7, which would leave the 10 % band an agreement width
  of 0.5-3 % and make the 2 m closure test "not expressible" by budget
  even if the saturation rule of (iv) did not exclude all 24 runs;
  available rule 0.936, 0.892, 0.860; strict rule 0.933, 0.890, 0.857) at
  m5, m6, m7, with the E0 ratio at unity (0.996-1.010) and 1.5-15 % of the
  actuators clipped per frame in both arms (stroke 1 um), so the model is
  **not verified at 2 m** and the 2 m record cannot settle it either way; at
  the gate-active m8 the operator error shows what a frame count could
  not: six of the eight runs are mask-variable (operator error 2.7-32 %,
  of which up to 10.4 % is carried in from the burn-in's operators; 9-40
  distinct operators over a run), one is not assessable (an operator the
  reconstructor refuses), the eighth is operator-consistent at 1.7 % but
  gate-active with a carried-state bound of 17 %; the eight effective-rule
  ratios scatter from 0.9 to 12 and are descriptive only, and the reconstructor's
  own valid-fraction policy (0.75) refuses the strict mask on six of eight
  runs and the available mask on one. On the convergence driver's ci geometry
  (the 12 m `@3` detector physics on the 5 m smoke geometry, 96 controlled
  actuators, gain 0.4, latency 2, stroke 100 um, no clipping) with the 12 m
  damping applied as a diagnostic override (`--alpha 0.1`), two 400-frame
  runs at seed 71 are gate-quiet: 7.3 % of the feedback eigenvalues are
  below 0.9 and 2.1 % below 0.5, the exact prediction is 3.2-3.7 % below the
  scalar reduction, and the measured `DeltaV` over the prediction from the
  run's realized covariance is 0.987 at m7 (92.9 +/- 2.8 nm^2 measured) and
  1.011 at m9 (614.6 +/- 15.9 nm^2), each within one 25-frame block standard
  error; these are two runs and a pilot-level consistency check, not a
  verification; both runs are operator-consistent (operator error below
  0.03 %, quiet burn-ins) and their systematic budget is 2.1 % and 1.9 %:
  the one mode the operator does not sense receives an injection of
  1.9e-5 relative (the Tikhonov property holds for the LSMR
  reconstructor), so `gamma` runs over the sensed states and is 0.091
  (the slowest sensed mode, feedback 0.12, decays within the first block),
  the first-block excesses are -2.4 % and -2.8 % against block scatters
  of 10 % and 9 % over twelve blocks, and the bound is 2.1 % and 1.9 %
  (23 % and 21 % had the unsensed mode carried state). The same geometry
  with its own damping (0.001) shows what the bound measures: at m7 the
  run is gate-quiet by the 0.1 % rule and changed its operator twelve
  times in the window (the arms used the modal one in 94 % and 93 % of
  the frames), which a frame-count threshold would have excluded, yet the
  transient propagated with the actual operator of every frame differs
  from the modal one by 0.64 % (the burn-in's operators carry in under
  1e-7 of it), so the run is operator-consistent and its ratio of 1.07
  (1.06 against the time-varying value, within one block SE) stands as a
  pilot-level check; but its almost unsensed mode (feedback 4.6e-7)
  receives 2.3e-2 of the injection, `gamma` must run over every state and
  is 1.02, the block scatter is 43 %, and the budget is 99 %: this loop
  cannot express a closure test over a 400-frame window; the strict mask,
  probed on its own 126 rows, leaves modes unsensed and predicts about
  twice the measured value (ratio 0.53). At m9 the run is gate-active and
  mask-variable (55 distinct operators over the run, operator error
  +3.9 % with 0.01 % carried in from burn-in), the measured
  1772 +/- 190 nm^2 is 1.35 times the effective-rule prediction (1.30
  times the time-varying one), and the strict mask (92 rows) has no
  stationary limit at all. With the ci
  damping even the full mask leaves one almost unsensed mode (feedback
  4.6e-7, no leak) that accumulates noise through the run, so the
  stationary limit is about twice the 400-frame window value: the
  finite-window prediction is the primary quantity for that reason; the
  count of modes a mask leaves unsensed (feedback below 1e-6) is reported
  and no rule attaches to it. The fixed-mask model does not
  describe gate-active runs by construction; that gap is what P4 measures
  against it, not a parameter to tune. (iii) Before the series, pilot P2b evaluates the model at the S4
  A1 configuration (12 m build, governed): the feedback spectrum of `@3`,
  the prediction from P2's realized covariance under every rule and from
  the flat model, the operator error of that run, the reconstruction of
  its command difference from the telemetry against its series and its
  retained residual maps (the first 12 m reading of the loop's linearity),
  the measured carried state, and the pilot-level conditional ratio at m8
  seed 71. (iv) Band
  for 12 m: fixed a priori at 10 % (not from the 2 m or ci dispersion). The
  closure test and the E0 test of 1.7 take the runs that pass **the three
  predeclared exclusions, listed here once and referenced everywhere
  else**: (a) **saturation**: a run whose mean saturation fraction after
  burn-in exceeds 1e-3 in either arm; (b) **gate activity**: a run that is
  not gate-quiet under the data-driven rule of 1.5 (mask disagreement below
  0.1 % of row-frames after burn-in, no rejected reconstruction, no
  recovery action in either arm); (c) **operator**: a run that is
  mask-variable (operator error above 2 % at the worse end of the
  covariance bracket) or not assessable (more distinct operators than the
  tool's probe budget, an operator its reconstructor refuses, a bracketed
  lenslet with neither bound, a covariance bracket wider than 2 %, or a
  command-difference trajectory reconstructed from the telemetry that
  does not reproduce the measured series).
  Each excluded run is reported with its saturation level, gate activity
  or operator record; none is tuned away; the primary prediction of every
  admissible run is the effective-rule, modal-operator value with its
  systematic budget `u` (1.6, 1.7), and no other rule or label (the
  telemetry-based rules, the count of unsensed modes, the match fractions,
  the restart sensitivities) decides anything. (v) Secondary hypothesis H_sat, predeclared: the 2 m
  deficit and its growth with magnitude are stroke clipping of the noise
  response. H_sat is supported if the 12 m ratio is "verified" (1.7) at
  m8-m10; if instead the 12 m ratio shows a deficit of the same size without
  saturation and without gate activity, the deficit belongs to the linear
  loop model (candidates to record, not to tune: the reconstructor's
  valid-fraction and rank policies, the finite-window response gain,
  temporal correlation of the realized noise), the model is not used for
  closure, and A1 stays descriptive (P1-P6 reported).
- **Use.** At 12 m, on gate-quiet, non-clipping runs only, the closure test
  of 1.7 is applied per magnitude to `rho = DeltaV / DeltaV_pred`, and the
  E0 test of 1.7 to the propagation-weighted E0 ratio; the closure sentence
  of section 5 may be written only when both tests are "verified" at every
  gate-quiet magnitude. "Within its own reported interval of unity" is not
  a criterion: a broad E0 interval that happens to contain one earns
  nothing (review round 2). Only a **rejected** outcome is a departure: a
  rejected `rho` with E0 verified localizes the departure in the loop (mask
  activity, saturation, temporal correlation; beyond the model's own
  systematic budget, which 1.7 adds to the departure band); a rejected E0
  with `rho` verified localizes it in the sensor model; both rejected is a
  departure of both. A **not expressible** outcome in either test is a
  precision outcome or, when the admissible runs' mean systematic budget
  `u_bar` reaches the band, a model-budget outcome; it is never a departure
  and never an agreement: a precision outcome triggers the seed extension
  once, and if it persists, or the budget caused it, the localization is
  **undetermined** and reported as such (review rounds 3 and 5). Neither
  outcome is tuned away.

### 1.7 Decision rules

**A2 (mask-locked arm, `noise-isolation-12m-masklocked`, m11, seeds 71-80,
10 paired runs) is justified only if all of the following hold at m11:**
mask disagreement above 0.1 % of row-frames in at least 3 of 5 seeds, or any
rejected reconstruction or recovery action in either arm; the E0 ratio on the
supported lenslets inside the m8-m10 band (the sensor model is not the
explanation); and `DeltaV` at m11 outside the E1 proportionality established
on the gate-quiet magnitudes by more than its interval. If the masks agree at
m11, A2 adds nothing and is not run. Mask locking for the m10 dip is justified
only if m10 shows gate activity, which is not expected.

**Closure test of the loop model (equivalence semantics).** Per run,
`rho = DeltaV / DeltaV_pred`, with `DeltaV_pred` the exact linear model's
conditional prediction (1.6): its window value for the noise computed from
the first analysed frame on, from that run's own realized noise covariance
under the `effective` rule (the operator the loop used), plus the exact
window contribution of the carried state reconstructed from the run's
telemetry. Per magnitude, the
admissible seeds are those that pass the three exclusions of 1.6 (iv) and
are not refused; `n_adm` is their count, `rho_bar` their mean and `h` the half-width of the 95 % t interval
with `n_adm - 1` degrees of freedom (`t_0.975` = 2.776 at `n_adm` = 5, 3.182
at 4, 4.303 at 3; the quantile follows `n_adm`, never the planned five); the
band is `[1 - b, 1 + b]` with `b = 0.10` fixed a priori. The model's own
error enters the band: `u_bar` is the mean over the admissible seeds of
each run's systematic budget `u` (1.6: operator error plus reconstruction
residual), the agreement band is `[1 - b + u_bar, 1 + b - u_bar]` and the
departure band `[1 - b - u_bar, 1 + b + u_bar]`. Exactly one of three
outcomes is recorded per magnitude: **verified** when `n_adm >= 4` and the
whole interval lies inside the agreement band, `rho_bar - h >= 1 - b +
u_bar` and `rho_bar + h <= 1 + b - u_bar` (an equivalence test; a point
estimate inside the band whose interval crosses a band edge is not a pass,
an interval wider than the band can never pass, and `u_bar >= b` leaves no
agreement band at all); **rejected** when `n_adm >= 3` and the whole
interval lies outside the departure band on one side, `rho_bar - h > 1 + b
+ u_bar` or `rho_bar + h < 1 - b - u_bar`; **not expressible** otherwise,
including every case with fewer admissible seeds than the outcome requires.
"Not expressible" at a gate-quiet magnitude is a precision outcome and
triggers the seed extension below (at most once), unless `u_bar >= b`
caused it: that is a model-budget outcome, reported as such, which more
seeds cannot change. After the extension the three outcomes are applied
again with the new `n_adm` (at most 10 seeds, 9 dof, `t_0.975` = 2.262
when none is excluded) and are final for this stage; a persisting "not
expressible" is reported as such and is never read as a departure or an
agreement. The excluded runs are listed with their saturation level, gate
activity or operator record (1.6 (iv)) and do not enter `rho_bar`; every
admissible run's `u` is listed with `u_bar`.

**E0 test (the same semantics).** Per admissible run, `e = ` the
propagation-weighted E0 ratio (realized centred variance over the model
variance on the support lenslets, P2); per magnitude `e_bar`, `h_e` and
`n_adm` as above, band `[1 - b_E0, 1 + b_E0]` with `b_E0 = 0.10` fixed a
priori; outcomes **verified**, **rejected**, **not expressible** by the
same inequalities and count requirements. The closure sentence of section 5
requires both the loop test and the E0 test "verified" at every gate-quiet
magnitude; a single "rejected" magnitude in either test makes that model
rejected for this stage, and the other results are then reported
descriptively.

**Seed extension** (five further seeds at one magnitude): triggered only when
the t half-width of `DeltaV` at a gate-quiet magnitude exceeds 5 % of its
mean, or when the closure test above is "not expressible" at that magnitude
for want of precision (not when `u_bar >= b` caused it);
at most once per magnitude; never at m11 through A1 (A2 covers it). The
runner has no seed option (E-2); the trigger is predeclared and the mechanism
is decision D3. The trigger reads precision outcomes only, never the sign
or size of the departure.

**Stop.** The stage stops after its 20 runs, after a contract violation
(section 0), or when the supervisor stops the group; a resumed invocation
continues only the missing runs under the same producer.

### 1.8 Cost, guard and outputs

Desktop anchor: 2638 s and 1.11 GiB for the untraced series in one process
(MEASURED_HISTORICAL). Trace overhead (ANALYTIC_ESTIMATE): per arm 400
frames x 416 lenslets x about 126 B of telemetry = 21 MB, row masks 0.3 MB;
float32 residual samples 300 x about 60,000 x 4 B = 72 MB per arm are already
in the untraced peak; at the end of a map-retaining run the payload stacks a
second 72 MB copy per arm and the compressed sidecar is built in memory. Raw
peak 1.3-1.4 GiB (EXTRAPOLATED); authorized budget 2800 MiB; cloud wall 2.0-2.2
h (EXTRAPOLATED from the x2.7-2.9 ci-scale factor). Disk: about 0.8-1.2 GB
of sidecars (20 files) plus a record under 1 MB. One invocation fits the
150-minute cap only on the desktop; on the cloud host two resumed
invocations are planned (`pilot_requests.json`).

## 2. Stage E2: fixed-physics convergence of `det_emccd_12m_medium_derived@3`

### 2.1 Plan (the driver's, verified from `records/plan_medium.json`)

54 paired runs: 18 settings x realizations 0, 1, 2; root seed 1; 200
frames, burn-in 50; arms `operating_expectation` (twin, primary) then
`noise_on`; paired `DeltaV` streamed from the twin's disk record; summary
telemetry, materialized bands; science 2.2 um. Settings and the driver's
per-paired-run analytic estimates (desktop-anchored):

| Axis | Settings (refinement parameter) | Estimate per paired run (s) |
| --- | --- | --- |
| baseline | `plain` (k = 4, 3 nodes, left-point n = 1, pad 2, 12 samples per lenslet) | 120 |
| pupil, reading `common` | `common_s12`, `common_s16`, `common_s20` (1/samples), reference draw 958, common band 574, period rule `pupil_diameter` | 120, 212, 330 |
| pupil, reading `growing` | `growing_s12`, `growing_s16`, `growing_s20` (same, no band limit) | 120, 212, 330 |
| detector | `k2`, `k8` with the baseline's k = 4 (1/k) | 75, 298 |
| spectrum | `nodes5`, `nodes7` with the baseline's 3 nodes (declared: no power law) | 153, 186 |
| exposure | `mid_n1`, `mid_n2`, `mid_n4`, `mid_n8` (1/n, centred family) and `left_n2` (rule comparison only) | 179, 238, 357, 594; 179 |
| science | `pad3`, `pad4` with the baseline's pad 2 (1/pad) | 130, 140 |

Config hashes: the pupil settings at 12 samples share the baseline's
`SystemConfig.config_hash` (`2a43f8f0…`); the pairing options live in the
atmosphere component hash, each run's protocol and its atmosphere record.

### 2.2 Fixed physical quantities and what each axis changes

Everything in 1.3 is fixed at m_AB 8 except the one numerical quantity of
the axis: pupil samples per lenslet (the detector pixel scale, window and
guard do not move; retained lenslets and illuminated-area fractions change
with the raster and are recorded per setting), MFT oversampling k, spectral
node count (band edges, source and sky unchanged; the detected budget is
recorded, never renormalized), exposure sample rule and count (duration,
frame rate, one camera read unchanged), science pad (angular sampling only).
Optics changes re-key the detector noise streams (sensor configuration hash
in the noise-stream identity), so the noise-on arm is noise-paired across
settings only on the science axis, where the WFS configuration is unchanged;
no inference assumes noise pairing.

### 2.3 Endpoints, arms and inference

| Arm | Endpoints per setting (units) | Inference |
| --- | --- | --- |
| twin (`operating_expectation`) | `post_update_rms` (nm), `peak_strehl` (1), `ee50_production` and `ee50_fourier` (rad, reported in mas), `reconstruction_usable_fraction` | deterministic given the paired input. The realization index is the unit and adjacent settings are **paired per realization** on every axis: the primary uncertainty of a change `Delta` is the Student t interval of the per-realization differences `Delta_r = Q_r(fine) - Q_r(coarse)` over the realizations completed in **both** settings (`n_adm` pairs, `n_adm - 1` dof: `t_0.975` = 4.303 for the three planned pairs, 12.706 if one realization was refused in either setting; fewer than two pairs gives no interval and the change is "not classified"), computed offline from the run rows. On the non-pupil axes every realization sees the identical open-loop series in every setting (digests checked by the driver), so the pairing is exact in input and in series; on the pupil axis the input is the same continuous field on different rasters (exact physical pairing, dilation reported), so the pairing is in input only and the per-realization differences carry the raster-dependent series as part of the change being measured. The driver's unpaired `sqrt(s_i^2 + s_j^2)` is **descriptive only**: it ignores the covariance of the two settings' metrics across realizations, so it is neither a conservative nor a liberal bound in general (it exceeds the paired error when the settings are positively correlated, which pairing is designed to exploit, and falls below it when they are negatively correlated); it is printed beside the paired interval and no decision reads it |
| noise-on | the same metrics plus the per-setting `DeltaV` mean and block SE | paired per realization exactly as the twin (the atmosphere realization is shared; the re-keyed detector draws on the optics axes are part of the measured change and widen the paired interval); the unpaired SE is descriptive only |
| paired `DeltaV` | mean (nm^2), block SE at 10 frames (driver) and at the plateau length (offline, section 6) | paired per realization across settings as above; a change of `DeltaV` across settings is a change of propagated noise plus re-keyed draws, and is reported as such |

### 2.4 Convergence classification per axis (declared criteria)

Tolerances are the driver's contract tolerances (`CONTRACT_TOLERANCES`):
residual 1.0 nm, peak Strehl 0.002, EE50 2 % relative, applied to the twin
arm at the two finest settings of each scan. Let `Delta` be the paired mean
of the finest adjacent change (2.3), `h` the half-width of its 95 % t
interval (`n_adm - 1` dof over the completed pairs, section 0) and `tol`
the metric's tolerance, so that the interval is
`[Delta - h, Delta + h]` and the tolerance band is `[-tol, +tol]`. Every
outcome falls in exactly one of three classes:

- **Converged at the quoted precision**: `|Delta| + h <= tol`. The whole
  interval lies inside the tolerance band (an equivalence test at the 95 %
  level, not a point estimate inside the band).
- **Unconverged**: `|Delta| - h >= tol`. The whole interval lies outside the
  tolerance band on one side (which implies that the change is resolved,
  since `tol > 0`).
- **Not expressible**: otherwise, that is `|Delta| - h < tol < |Delta| + h`.
  The interval crosses a tolerance edge; this covers an interval wider than
  the band (`h > tol`), a point estimate inside the band whose interval
  reaches outside it, and a point estimate outside the band whose interval
  reaches inside it. The metric is reported with its interval and the
  extension trigger of 2.5 applies.

The three conditions are mutually exclusive and exhaustive for finite `Delta`
and `h`; a scan with a refused or missing finest setting is "not classified"
and is reported as such, never as converged. The classes are applied per
metric; a scan is "converged" only if every metric of the twin arm is.

Richardson rules (the module's, `validation/richardson.py`): an observed
order and extrapolated limit only from three settings with resolved,
same-sign, shrinking differences, ratio above the zero-order limit, order in
(0.1, 8); otherwise `NOT_ESTIMATED` with its reason; two settings give a
change table and no order; the spectral axis is declared non-power-law
(Gauss-Legendre converges geometrically for analytic integrands) and gets a
change table only; the exposure family's assumed-order-2 extrapolation is
reported with its label and is never mixed with an observed order. These
rules follow Celik et al. (2008), Steps 2-5 and eqs (3a)-(7), read for this
packet: the module's ratio equation, extrapolated limit and `GCI_fine` are
that procedure in coarse-to-fine order, and its `NOT_ESTIMATED` cases are
the procedure's oscillatory and near-zero-difference cases. The pupil ratios
are 12:16 = 1.333 and 16:20 = 1.25; the second is below the 1.3 that Celik et
al. recommend "based on experience", so a pupil order estimate is weakly
conditioned and is quoted with that caveat. The spectral axis follows
Trefethen (2008) Theorem 4.5: for an integrand analytic in a Bernstein
ellipse the Gauss error decays geometrically in the node count, so no
algebraic order is fitted. The growing-band reading mixes
refinement with added bandwidth: its change table is reported, its Richardson
output is not a convergence order, and `growing_s - common_s` at equal `s`
quantifies the bandwidth added by the grid. `common_s12` minus
`baseline_plain` is the input change (reference-grid draw, one physical
period, common band) at a fixed raster and is reported apart from the scan.
The midpoint family is one centred scan; `left_n2` enters only the labelled
rule comparison. `ee50_fourier` resolves the production estimator's pad
dependence; a converged pad axis on the Fourier reference says nothing about
pupil-raster, finite-field or hardware-model error. G3 is deferred: the
exposure axis refines the WFS quadrature while the science observer samples
the frame start, so no sentence about exposure-integrated science imaging
follows from it.

### 2.5 Uncertainty and extension rules

Three realizations give 2 degrees of freedom (`t_0.975` = 4.303), so "not
expressible" is the expected class for small changes; a refused realization
in either setting of a pair reduces the pairs and the dof accordingly
(section 0). Extension trigger: a metric classified "not expressible" (or
"not classified" for want of pairs) on the finest change of a scan with the
three planned realizations extends that scan by three realizations (3, 4, 5)
for every setting of the scan, at most once; after the extension the three
classes of 2.4 are applied again with the completed pairs' dof (5 dof,
`t_0.975` = 2.571 when all six completed) and the outcome is final for this
stage, "not expressible" included. The mechanism is
decision D3 (the driver's realizations are constants). The trigger reads the
class, never the sign or size of `Delta`.
Temporal-block sensitivity for `DeltaV` (150 analysed frames): block SE at
1, 5, 10, 25, 50 frames from the stored series; primary at the plateau.

### 2.6 Staging and decision gates

E2a `--axes detector,spectrum` (15 runs) first, in its own directory; then
E2b `--axes exposure,science` (24 runs, repeats the baseline triple); then
E2c `--axes pupil` (18 runs, no baseline). Gate before each expansion:
pilot-measured cost within 1.5x of the estimate used for the request; every
pairing check of the completed subset true (shared open-loop digests per
realization; exact dilation for pupil); every axis of the subset classified
under 2.4 or "not expressible" with its extension decision taken; peak child
memory within the admitted estimate. The full 54-run plan in one directory
is the alternative (D4).

### 2.7 Cost, guard and outputs

Per child (fresh process): 0.5-0.7 GiB at 12 samples (EXTRAPOLATED from the
S3 12 m runs at 0.32-0.55 GiB and the E3 process peaks of 0.45 GiB, plus the
second built system freed between arms); up to about 1.0 GiB at 20 samples
(materialized bands `16 L S^2` with S = 958 at the reference draw: 147 MB,
plus FFT scratch); the parent adds 100-150 MiB. Policy budget admits a group
of at most 1005.8 MiB raw; pilot P1 measures the three extreme settings
(`plain`, `mid_n8`, `common_s20`) before any subset runs. Wall: desktop 0.69,
1.61, 1.10 h for E2a, E2b, E2c; cloud 1.9, 4.5, 3.1 h (EXTRAPOLATED).

## 3. Stage E3: limited 42 m checks on `det_ccd_42m_r3band_derived@1`

### 3.1 Plan (verified from `records/plan_full.json`)

Five twin-only runs (`arms = ("operating_expectation",)`, no paired
`DeltaV`), 200 frames, burn-in 50, realization 0, root seed 1, regenerated
bands, summary telemetry: `plain` (k = 2, 3 nodes, left-point n = 1, pad 2),
`detector_k4`, `exposure_mid_n1`, `exposure_mid_n2`, `exposure_left_n2`. No
pupil refinement (the plan holds one pupil setting; none is added). Fixed
quantities: D = 42 m, 1008 samples, 84 x 84 lenslets, 85 x 85 actuators,
`synthetic_ccd@1` (QE 0.80, read 3 e-, 1.6 e-/ADU, 16 bit), 1e5 detected e-
per full subaperture, pixel scale 6.993e-7 rad, 15 px window, 1 px guard,
diffusion 0.2 px, estimated products from 16 frames, damping 0.001, no
recovery block, gain 0.3, latency 2, 500 Hz, 2 ms, science 2.2 um pad 2.

### 3.2 Endpoints and inference

Twin residual (nm), peak Strehl, production and Fourier EE50 (mas), usable
fraction, per setting. One realization: the twin is noiseless, so each
change between settings is a deterministic paired difference for this
realization with no sampling error from noise; what is unknown is how the
change varies with the realization. The 12 m E2 scatter of the same change
(k2 -> k4 from E2a; mid n1 -> n2 and left_n2 vs mid_n2 from E2b) is used as
the prior scale `s`, labelled EXTRAPOLATED: `s` is the sample standard
deviation of the three per-realization differences of that change at 12 m.
Each 42 m change `Delta` then takes exactly one of three labels: "not
resolved by one realization" when `|Delta| < 2 s` (never called converged),
"unconverged for this realization" when `|Delta| >= 2 s` and `|Delta|` exceeds
the contract's single-realization tolerance (residual 0.9 nm, Strehl 0.002,
EE50 2 %), and "resolved and within tolerance for this realization" when
`|Delta| >= 2 s` and `|Delta|` is within that tolerance (reported with the
caveat that one realization cannot show convergence). No order is estimated
from two settings; the assumed-order extrapolation of the midpoint pair is
reported with its label and not used for a claim.

### 3.3 Prerequisites, cost, guard

Proceed only after **both** E2a (detector and spectrum) and E2b (exposure
and science) are interpreted under 2.4, and after a refreshed full-scale
pilot (P3: one twin-only baseline run, optionally `k4`). E2b is a
prerequisite because three of the five E3 settings are exposure settings
(`exposure_mid_n1`, `exposure_mid_n2`, `exposure_left_n2`): the prior scale
that 3.2 uses to call a 42 m exposure change "not resolved by one
realization" is the 12 m scatter of the same change, which exists only after
E2b, and the midpoint-versus-left-point reading of 3.2 is defined by the E2b
rule comparison. Without E2b the exposure rows of E3 could be run but not
interpreted, so they are not run. E2c (pupil) is not a prerequisite: E3 has
no pupil axis. Per child 1.5-2.0 GiB raw (S2 and S3 42 m records; 200 frames
keep the history small); authorized budget 4096 MiB; desktop 1.71 h analytic,
cloud 4.6-5.0 h (EXTRAPOLATED), chunked into resumed invocations.

## 4. Arms and methods compared

| Arm or method | What it can distinguish | Advantages | Limitations | Runtime (desktop anchor / cloud extrapolation) | Memory |
| --- | --- | --- | --- | --- | --- |
| S4 A1 traced paired run (noise_on vs operating-expectation twin, per-frame trace) | propagated temporal detector noise (`DeltaV`) from everything common to both arms; sensor-model behaviour at the operating spots (E0) from the loop's response (E1, `kappa`); when and where masks diverge | recorded scalars bit-identical to the untraced instrument; per-lenslet and per-frame diagnostics; replay comparison against the committed record | one process for the series; masters common to both arms (calibration-master error not separable); gate-active magnitudes not fittable; closure needs the justified model of 1.6 | 2638 s historical / 2.0-2.2 h | 1.11 GiB historical, 1.3-1.4 GiB with trace |
| S4 A2 mask-locked arm (twin first, noisy arm replays the twin's rows) | whether mask divergence itself moves `DeltaV` at m11 | separates gating from noise propagation | conditional on A1; partial locks are reported as partial; 10 seeds at one magnitude | about 10 x 130 s / 0.9-1.0 h | as A1 |
| E2 twin arm (fixed-physics refinement, paired input) | numerical discretization error per axis at fixed physics | deterministic; paired per realization; Richardson where admissible; Fourier EE reference beside the production EE50 | three realizations; continuum limit not reached; pupil axis changes the atmosphere identity; raster and finite-field errors remain | 75-594 s per paired run / x2.7-2.9 | 0.5-1.0 GiB per child |
| E2 noise-on arm and paired `DeltaV` | how the noise contribution moves with each numerical axis | same runs; streamed, disk-backed | re-keyed draws except on the science axis; statistical over three units only | included | included (twin record on disk) |
| E3 twin-only 42 m | whether the 42 m detector sampling (k) and WFS exposure quadrature (n) move the quoted metrics for one realization | cheapest 42 m evidence; deterministic paired differences | one realization; no order; no pupil axis; no noise arm | 726-1816 s per run / x2.7-2.9 | 1.5-2.0 GiB per child |
| Offline H5 bound (`scripts/noise_isolation_offline_bounds.py`, 2 m) | reconstructor dependence on the calibration flux without a loop | seconds; no governed run | 2 m only; dense reconstructor; fixed covariance | seconds | small |
| Exact linear closed-loop noise model (`tools/linear_loop_noise_model.py`, analysis only; `kappa` is its unit-feedback reduction) | whether `DeltaV` is the linear loop's response, with the reconstructed spatial feedback `L = R M` and the run's realized noise covariance, to the sensor noise; which modes the damping leaves weakly fed back; how much of the recorded variance the fixed-mask linear picture leaves unexplained | no new loop run; predicts per run from the sidecar; checked on ungoverned data where it coincides with `kappa` (2 m) and where it does not (ci geometry with the 12 m damping) | assumes a fixed mask, linear sensor response, white noise, no saturation, no recovery; silent on gate-active runs by construction (it is what gate activity is measured against); a 12 m evaluation is a governed system build (P2b); not an acceptance law until the closure test of 1.7 is passed | P2b: one 12 m build plus about 900 probes and two 400-frame propagations (minutes) | about 0.3 GB dense pupil response at 12 m |
| Five-seed paired bootstrap (F-06, analysis only) | descriptive stability of the recorded 12 m slope | no new run | exploratory; five clusters | none | none |

## 5. Closure sentences each stage can earn

- S4 A1 (gate-quiet magnitudes, loop test and E0 test both "verified"
  under 1.7 at each of them): "At m_AB 8-10 on `@3` the isolated
  detector-noise variance equals the exact linear closed loop's response
  (reconstructed spatial feedback `L = R M` on the fixed support mask, gain
  0.3, latency 2) to the realized centroid noise covariance: the whole 95 %
  interval of the ratio `DeltaV / DeltaV_pred` over the admissible seeds
  lies inside the predeclared 10 % band at every gate-quiet magnitude, and
  the whole 95 % interval of the propagation-weighted E0 ratio lies inside
  its predeclared 10 % band at every gate-quiet magnitude; the recorded 12 m
  slope departure is therefore located in <the loop | the sensor model |
  both | neither>." A "not expressible" or "rejected" outcome of either test
  at any gate-quiet magnitude forbids this sentence; the stage then reports
  P1-P6 descriptively and the outcomes by magnitude, and the localization
  is "the loop", "the sensor model" or "both" only where the corresponding
  test is **rejected**, and "undetermined" where a test is "not
  expressible" after the extension (1.6 "Use"). LIM-18's recorded verdict is unchanged in any case; AR-006 is
  closed only if the departure is explained or bounded by this sentence and
  the m10 dip is reproduced and attributed.
- E2: per axis, "converged at the quoted precision", "unconverged" or "not
  expressible" for the twin arm at 12 m on the stated tolerances, with the
  change table, the observed order where admissible and the Fourier reference
  for EE50. AR-007 and LIM-07 move only for the axes and scale covered.
- E3: "for one realization at 42 m, k = 2 -> 4 and midpoint n = 1 -> 2 move
  the twin residual, Strehl and EE50 by <values>; the left-point rule differs
  from the midpoint rule by <values> at n = 2." No convergence claim, no
  ensemble claim.

LIM-01 is untouched by every stage.

## 6. Temporal-block sensitivity and excursion rules (common)

Block means of a per-frame series at lengths L in {1, 5, 10, 25, 50, 75}
(A1, 300 analysed frames) or {1, 5, 10, 25, 50} (E2, 150 frames). The
plateau is the smallest L with at least five blocks whose standard error is
not exceeded by more than 10 % by the next admissible length's; if none, the
largest admissible length's error is reported as a lower bound and the run is
flagged "SE unresolved". The integrated autocorrelation time with the
automatic window `M >= 6 tau(M)` is reported, with its reliability flag when
the series is shorter than 50 tau or no window closes. Excursion: any
25-frame block mean of `DeltaV_t` above three times the run median flags the
run; in E2 a twin-arm rejected reconstruction or recovery action also flags
the run (the twin is noiseless and the recorded 12 m studies never rejected
at m_AB 8). Flagged runs stay in every statistic and are listed with their
traces.

## 7. Memory and runtime formulas used above

- Residual samples kept by the paired-noise core: `2 arms x (F - burn_in) x
  pupil_samples x 4 B` (float32 lists), 2 x 72 MB at 12 m.
- Trace telemetry: `F x Q x (15 float64 + 6 bool)` per arm, about 21 MB at 12
  m; row masks `F x 2Q` bool.
- Convergence twin record: `(F - burn_in) x pupil_samples x 8 B` on disk
  (72 MB at 12 m, 300 frames; 36 MB at 150 frames), removed after the run.
- Materialized bands: `16 L S^2` with S the screen size (576 at 12 samples,
  958 with the reference draw at the planned finest grid; `regenerate` at 42
  m: about `48 S^2`).
- Per-frame time at 12 m: 0.163 s (E6 baseline, k = 4, 3 nodes); 0.123 s
  without pixel integration; the WFS term scales about as `k^2` and linearly
  with nodes and sub-samples; cloud factor 2.7-2.9 (ci scale).
- Exact linear loop model (1.6): `dc_{k+1} = (1 - l) dc_k - g L dc_{k-d} +
  g R n_{k-d}` for `k >= d` and `dc_{k+1} = (1 - l) dc_k` for `k < d` (the
  latency queue starts with `d` zeros), `L = R M` with `R` probed on the
  one fixed row set that carries `Sigma` (rows outside it invalid, not
  noiseless), that set being the operator the loop used in the plurality
  of analysed frames (the sidecar's effective row masks); the run is
  admissible for the fixed-operator comparison only if the part of the
  time-varying difference due to operator changes inside the window
  (update `k` carrying the operator of frame `k - d`; rows outside the
  modal mask at the worse end of their covariance bracket) is at most 2 %
  of the modal value (1.6 (iv)). Reconstructed trajectory: `inc_k =
  R_k^noisy m_k^noisy - R_k^twin m_k^twin` (each arm's reference-subtracted
  centroids in the rows its operator used), `dc_{k+1} = (1 - l) dc_k + g
  inc_{k-d}` from `dc_0 = 0` and an empty queue; check `mean_k
  |(W dc_{k+1})^T (W dc_{k+1})| / N_pupil` against `DeltaV_t` (relative rms
  at most 1e-3). Carried contribution: the state at the first analysed
  frame `b` (`dc_b`, `inc_{b-d}, ..., inc_{b-1}`) propagated with `inc_k =
  -L dc_k` for `k >= b`, `D = mean_{k >= b} |W dc_{k+1}|^2 / N_pupil`;
  conditional prediction `DeltaV_pred = W_cold + D` with `W_cold` the
  window mean of `tr(Gt P_k)` for `P` propagated from zero at `b` with the
  forcing from update `b + d` on; budget `u = |operator error| + r` with
  `r` the reconstruction's relative rms, entering 1.7; state `x_k = (dc_k, ..., dc_{k-d})`, `x_{k+1} = F x_k + [k >=
  d] G n_{k-d}`; transient `P_{k+1} = F P_k F^T + [k >= d] G Sigma G^T` from
  `P_0 = 0` (identical initial commands), stationary `P = F P F^T + G Sigma
  G^T`; `DeltaV_pred = mean_k tr(Gram P_{k+1}[dc]) / N_pupil` over the
  analysed frames `k` (the post-update residual of frame `k` carries
  `dc_{k+1}`), `Gram = W_c^T W_c` with `W_c` the piston-removed pupil
  response of the controlled actuators; unit-feedback reduction `kappa *
  sum_r w_r sigma_r^2`
  with `kappa = (1/2 pi) int |g e^{iw} / (e^{i(d+1)w} - (1-l) e^{idw} + g)|^2
  dw` (0.35005 at g = 0.3, l = 0, d = 2). Cost at 12 m: dense `W_c` about
  65,000 x 500 doubles (0.26 GB); the Lyapunov state is 3 x 500; the window
  propagation is 400 structured products of that size.
- Every number labelled EXTRAPOLATED is replaced by the pilot's
  MEASURED_CURRENT value before the stage request is approved.
