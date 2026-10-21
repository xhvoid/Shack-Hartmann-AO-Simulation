# Predeclared staged experiment protocols (S4 A1, E2, E3)

Written before any governed run, for the exact tree `5514285`. Every number
that a decision depends on is stated here; the analysis of a stage is read
only after its stage completes, and nothing in a result changes this text.
Amendments are appended as dated sections and never rewrite an earlier rule.

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

**Intervals.** Student t with `n - 1` degrees of freedom over the units
(`t_0.975` = 2.776 for 5 seeds, 4.303 for 3 realizations, 2.365 for 8 seeds).
A "resolved" change is one whose interval excludes zero; the drivers' 2-SE
flags are screening flags, not claims.

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
| P3 E1 proportionality | per-seed slope of `log DeltaV` against `log P` over the gate-quiet magnitudes, where `P` is the propagated sensor noise (1.6); mean slope and t interval over seeds | dimensionless |
| P4 Mask and gate activity | mask-disagreement row-frames fraction per run; per-gate activity (flux, SNR, uncertainty, clipping) and support loss per frame; rejected reconstructions, recovery actions and DM saturation fraction per arm | fractions |
| P5 Loop transfer ratio | `DeltaV / P` per run and per magnitude (1.6) | dimensionless |
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
6. The alternative model (1.6) is applied only if its verification step
   passed before this analysis was read.

### 1.6 The alternative statistical/physical model and its justification

The first-order bias band (the model sigma low by about `4/SNR_T^2` near the
support floor) is a hypothesis about the sensor model, not an acceptance law.
Closure of the loop question needs a model whose prediction does not rest on
that band. The proposal is the linear loop's measurement-noise transfer:

- Model. With white per-row centroid noise of variance `sigma_r^2`, a fixed
  reconstructor and the loop of technical reference 4.2 (leaky-free
  integrator, gain `g`, queue latency `d`), the DM-space noise response
  obeys `delta c_k = delta c_{k-1} - g delta c_{k-d-1} + g n_{k-d}`, so the
  transfer from measurement noise to the command (and to the residual) is
  `H(z) = g z / (z^{d+1} - z^d + g)`, the same denominator as the stability
  polynomial already in the reference. For white noise the mean square gain is
  `kappa(g, d) = (1/2 pi) * integral |H(e^{i w})|^2 dw`; `kappa = g/(2-g)` at
  `d = 0` (the textbook integrator result) and, computed here on a 2^16-point
  grid, **`kappa = 0.35005` for `g = 0.3, d = 2`** (12 m and 42 m profiles) and
  `0.15455` for the 2 m profile (`g = 0.2`, leak 0.02, `d = 2`; the leak
  enters as `(1-leak) z^d`). The prediction is
  `DeltaV_pred = kappa * P`, `P = sum_r sigma_r^2 w_r`, with `w_r` the
  propagation weight the sidecar records (pupil variance of the DM response
  to a unit slope in row `r`, fixed reconstructor) and `sigma_r^2` either the
  realized E0 variance (`P^E0`, the primary) or the model sigma (`P^model`).
  Assumptions: linear reconstructor on a fixed mask, independent rows (the
  x/y cross-covariance dropped, as the offline H5 bound does), temporally
  white detector noise, no saturation and no recovery action.
- Justification before use. (i) The derivation above is checked against the
  stability polynomial of the reference and the `g/(2-g)` identity
  (`SOURCE_READING_NOTES.md` section 3); its structure, residual noise equal
  to a propagation coefficient times the noise variance times the integral of
  the squared noise transfer function of an integrator with delay, is
  Gendron and Léna (1994) eqs (14)-(15), and the discrete integrator and leak
  form is Agapito et al. (2019) eqs (4)-(7) (both passages read, notes
  section 4). (ii) Verification on ungoverned
  data, **done in this session** on the cloud replay of the 2 m traced study
  (`records/cloud_checks/SUMMARY.md`): `kappa_meas = DeltaV / P^E0` over 8
  seeds is 0.1449 +/- 0.0089, 0.1383 +/- 0.0116 and 0.1332 +/- 0.0074 (t) at
  m5, m6, m7, that is 0.937 +/- 0.058, 0.895 +/- 0.075 and 0.862 +/- 0.048 of
  the derived 0.15455, while the E0 ratio is unity within its interval
  (0.996-1.010) and the per-seed E1 slope is 0.955 +/- 0.014 (as T1 found).
  The model is therefore **not verified at 2 m**: the deficit exceeds 10 %
  at m6 and m7 and grows with magnitude. The 2 m profile's 1 um stroke clips
  1.5-15 % of the actuators per frame in both arms (sidecar
  `saturation_fraction`, run means after burn-in, identical between the
  arms), so the model's no-saturation assumption fails there and the 2 m
  record cannot settle the model either way. (iii) Band for 12 m: fixed a
  priori at 10 % (not from the 2 m dispersion), with the predeclared
  exclusion that a run whose mean saturation fraction after burn-in exceeds
  1e-3 in either arm is excluded from the `kappa` test and reported with its
  saturation level; the 12 m `@3` stroke is 100 um and the ci-scale
  self-check with the 12 m physics shows zero saturation in both arms.
  (iv) Secondary hypothesis H_sat, predeclared: the 2 m deficit and its
  growth with magnitude are stroke clipping of the noise response. H_sat is
  supported if the 12 m `kappa_meas` lies inside the band and is flat across
  m8-m10; if instead the 12 m ratio shows the same deficit without
  saturation, the deficit belongs to the linear loop model (candidates to
  record, not to tune: the dropped x/y cross-covariance, the reconstructor's
  valid-fraction and rank policies, the finite-window response gain), the
  model is not used for closure, and A1 stays descriptive (P1-P6 reported).
- Use. At 12 m, on gate-quiet runs only: the closure sentence of section 5
  may be written when `kappa_meas` lies inside the band at every gate-quiet
  magnitude and the E0 ratio is within its own reported interval of unity on
  the supported lenslets. A magnitude-dependent `kappa_meas` with E0 near
  unity localizes the departure in the loop (mask activity, saturation,
  temporal correlation); an E0 ratio away from unity with `kappa_meas` in band
  localizes it in the sensor model. Neither outcome is tuned away.

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

**Seed extension** (five further seeds at one magnitude): triggered only when
the t half-width of `DeltaV` at a gate-quiet magnitude exceeds 5 % of its
mean; at most once per magnitude; never at m11 through A1 (A2 covers it).
The runner has no seed option (E-2); the trigger is predeclared and the
mechanism is decision D3.

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
| twin (`operating_expectation`) | `post_update_rms` (nm), `peak_strehl` (1), `ee50_production` and `ee50_fourier` (rad, reported in mas), `reconstruction_usable_fraction` | deterministic given the paired input; for non-pupil axes every realization sees the identical open-loop series in every setting (digests checked by the driver), so adjacent changes are **paired per realization**: the primary uncertainty of a change is the t interval (2 dof) of the three per-realization differences, computed offline from the run rows; the driver's unpaired `sqrt(s_i^2 + s_j^2)` is reported beside it as the conservative bound; for the pupil axis the input is the same continuous field on different rasters, so realizations are paired in input but not in series, and the driver's unpaired SE is primary |
| noise-on | the same metrics plus the per-setting `DeltaV` mean and block SE | statistical over independent realizations (unpaired t over three units); `DeltaV` per setting is paired against the twin within the setting only |
| paired `DeltaV` | mean (nm^2), block SE at 10 frames (driver) and at the plateau length (offline, section 6) | as above; a change of `DeltaV` across settings is a change of propagated noise plus re-keyed draws |

### 2.4 Convergence classification per axis (declared criteria)

Tolerances are the driver's contract tolerances (`CONTRACT_TOLERANCES`):
residual 1.0 nm, peak Strehl 0.002, EE50 2 % relative, applied to the twin
arm at the two finest settings of each scan.

- **Converged at the quoted precision**: the finest adjacent change is inside
  the tolerance and its interval is inside the tolerance.
- **Unconverged**: the finest adjacent change is outside the tolerance and
  resolved.
- **Not expressible**: the interval is wider than the tolerance; the metric
  is reported with its interval and the seed-extension trigger (2.5) applies.

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

Three realizations give 2 degrees of freedom; "not expressible" is expected
for small changes. Extension trigger: a metric that is "not expressible" on
the finest change of a scan with the three planned realizations is extended
by three realizations (3, 4, 5) for every setting of that scan, at most once;
the mechanism is decision D3 (the driver's realizations are constants).
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
(k2 -> k4, mid n1 -> n2, left_n2 vs mid_n2) is used as the prior scale,
labelled EXTRAPOLATED. A 42 m change smaller than that scale is "not resolved
by one realization" and is never called converged; a change larger than the
contract's single-realization tolerance (residual 0.9 nm, Strehl 0.002, EE50
2 %) is "unconverged for this realization". No order is estimated from two
settings; the assumed-order extrapolation of the midpoint pair is reported
with its label and not used for a claim.

### 3.3 Prerequisites, cost, guard

Proceed only after the 12 m interpretation (E2a at least) and a refreshed
full-scale pilot (P3: one twin-only baseline run, optionally `k4`). Per
child 1.5-2.0 GiB raw (S2 and S3 42 m records; 200 frames keep the history
small); authorized budget 4096 MiB; desktop 1.71 h analytic, cloud 4.6-5.0 h
(EXTRAPOLATED), chunked into resumed invocations.

## 4. Arms and methods compared

| Arm or method | What it can distinguish | Advantages | Limitations | Runtime (desktop anchor / cloud extrapolation) | Memory |
| --- | --- | --- | --- | --- | --- |
| S4 A1 traced paired run (noise_on vs operating-expectation twin, per-frame trace) | propagated temporal detector noise (`DeltaV`) from everything common to both arms; sensor-model behaviour at the operating spots (E0) from the loop's response (E1, `kappa`); when and where masks diverge | recorded scalars bit-identical to the untraced instrument; per-lenslet and per-frame diagnostics; replay comparison against the committed record | one process for the series; masters common to both arms (calibration-master error not separable); gate-active magnitudes not fittable; closure needs the justified model of 1.6 | 2638 s historical / 2.0-2.2 h | 1.11 GiB historical, 1.3-1.4 GiB with trace |
| S4 A2 mask-locked arm (twin first, noisy arm replays the twin's rows) | whether mask divergence itself moves `DeltaV` at m11 | separates gating from noise propagation | conditional on A1; partial locks are reported as partial; 10 seeds at one magnitude | about 10 x 130 s / 0.9-1.0 h | as A1 |
| E2 twin arm (fixed-physics refinement, paired input) | numerical discretization error per axis at fixed physics | deterministic; paired per realization; Richardson where admissible; Fourier EE reference beside the production EE50 | three realizations; continuum limit not reached; pupil axis changes the atmosphere identity; raster and finite-field errors remain | 75-594 s per paired run / x2.7-2.9 | 0.5-1.0 GiB per child |
| E2 noise-on arm and paired `DeltaV` | how the noise contribution moves with each numerical axis | same runs; streamed, disk-backed | re-keyed draws except on the science axis; statistical over three units only | included | included (twin record on disk) |
| E3 twin-only 42 m | whether the 42 m detector sampling (k) and WFS exposure quadrature (n) move the quoted metrics for one realization | cheapest 42 m evidence; deterministic paired differences | one realization; no order; no pupil axis; no noise arm | 726-1816 s per run / x2.7-2.9 | 1.5-2.0 GiB per child |
| Offline H5 bound (`scripts/noise_isolation_offline_bounds.py`, 2 m) | reconstructor dependence on the calibration flux without a loop | seconds; no governed run | 2 m only; dense reconstructor; fixed covariance | seconds | small |
| Loop noise-transfer model (`kappa`, analysis only) | whether `DeltaV` is the linear loop's response to the realized sensor noise | no new run; falsifiable on the 2 m record first | assumes white noise, fixed mask, no saturation; not an acceptance law until verified | none | none |
| Five-seed paired bootstrap (F-06, analysis only) | descriptive stability of the recorded 12 m slope | no new run | exploratory; five clusters | none | none |

## 5. Closure sentences each stage can earn

- S4 A1 (gate-quiet magnitudes, model verified under 1.6): "At m_AB 8-10 on
  `@3` the isolated detector-noise variance equals the linear loop's
  response (`kappa = 0.350`) to the realized centroid noise within the
  predeclared band, and the realized noise agrees with `detector_covariance_v2`
  at the operating spots within its reported interval; the recorded 12 m slope
  departure is therefore located in <the loop | the sensor model | neither>."
  LIM-18's recorded verdict is unchanged in any case; AR-006 is closed only
  if the departure is explained or bounded by this sentence and the m10 dip
  is reproduced and attributed.
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
- Every number labelled EXTRAPOLATED is replaced by the pilot's
  MEASURED_CURRENT value before the stage request is approved.
