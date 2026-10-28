# Detector-noise law: analysis of saved noise-isolation records

Research note, 2026-10-20. Scope: roadmap item S4 and limitation LIM-18
("the 12 m isolated detector noise departs from a pure inverse-photon law").
This is a saved-data analysis and literature comparison. No AO loop was run,
no simulation system was built, no realization was drawn, and changes were confined to the original
research-note directory. The companion files are
[`analyze_saved_records.py`](analyze_saved_records.py) (the reproducible analysis),
[`results.json`](results.json) (its output, with input digests, source
identity and environment) and [`experiment_proposal.md`](experiment_proposal.md)
(the smallest discriminating experiment, not run).

This is a historical analysis dated 2026-10-20. The saved results retain their
original producer path, source identity and script digest. An [immutable copy
of the producer script](https://github.com/xhvoid/Shack-Hartmann-AO-Simulation/blob/b22d4502ba632454116eb243cc52a7548ae770a8/docs/research/s4_noise_law/analysis.py)
matching the recorded digest remains available. Renaming the files
and revising explanatory text does not regenerate or relabel that evidence.
The analysis script's numerical routines are unchanged. Current experiment
planning is governed by [the post-T2 protocol](../post_t2_experiment_packet/PROTOCOL.md)
and [pilot requests](../post_t2_experiment_packet/pilot_requests.json); this note
closes neither roadmap S4 nor LIM-18.

## 0. Summary

1. **Every quoted number reproduces from the saved records** (27 numbers at
   12 m, 24 at 2 m) within rounding: the 12 m weighted log–log slope
   −1.028 ± 0.010 (unscaled fit error; χ²/dof 2.50; 2.70 SE from −1; 1.71 SE
   with the scaled error), the 2 m slope −0.978 ± 0.014 (χ²/dof 2.46; 1.61
   SE), the model slopes −1.097 and −1.051, the powers 0.960 ± 0.010 and
   0.950 ± 0.013, the 6.7 % dip at m_AB 10, the 9 % drift at 2 m, and the
   pre-refactor audit F-06 bootstrap (−1.086, SD 0.028), whose convention is thereby
   identified as whole-seed resampling of an unweighted fit to seed means.
   The original failed 12 m criterion stands as recorded.
2. **The implemented estimand is a paired residual-map intervention, not a
   difference of variances and not an additive noise budget.** It equals the
   propagated temporal detector noise only where the loop responds linearly
   to the noise. Both arms gate lenslets on their *own* expected spots, so
   the arms' validity masks can diverge; the records show that they do at
   m_AB 11 (12 m) and m_AB 8 (2 m), and nowhere else beyond a few
   lenslet-frames per run.
3. **The "departure from the model" is largely a comparison with the wrong
   model state.** The model column was evaluated at a flat wavefront. The
   floor terms (read noise 0.2 e⁻ input-referred, CIC 0.005 e⁻/px, ADC step)
   do not depend on the spot, but the photon term grows with the spot's
   second moment inside the 15-pixel window, which the closed-loop residual
   broadens. A measured exponent between −1 and the flat-wavefront model's
   exponent is what the implemented model itself predicts once it is
   evaluated at the operating residual. The saved data cannot quantify the
   broadening (no residual map is saved), so this is the leading hypothesis,
   not an established explanation.
4. **The gate-quiet magnitudes alone carry the departure.** Dropping every
   magnitude where any lenslet was rejected (m_AB 11 at 12 m, m_AB 8 at 2 m)
   leaves three points at each scale that are internally consistent
   (χ²/dof 0.97 and 0.08) and whose slopes are shallower than the
   flat-wavefront model's by 0.039 ± 0.011 (12 m) and 0.052 ± 0.014 (2 m).
   The 6.7 % dip at m_AB 10 is one step of that shallow trend plus a
   fluctuation of about 1–1.5 standard errors, not a demonstrated
   magnitude-specific effect; the paired per-seed drop from m_AB 8 to 10 is
   −6.2 ± 2.0 % (t = −3.1, 4 degrees of freedom).
5. **The 2 m drift is not explained by any additive mechanism.** Over
   m_AB 5–7 the closed-loop noise variance grows as N_e^(−0.977 ± 0.014),
   shallower than 1/N_e; its "floor" fitted in the form α + β/N_e is
   negative (β/α = −93 ± 57 e⁻ against the model's +137 e⁻). Spot
   broadening can at most make the exponent −1.000. A compressive
   nonlinearity (the 2 m DM's 1 µm stroke against 330–680 nm RMS open-loop
   OPD) and the operating-flux calibration of the 2 m profile are the
   candidates; neither is testable from the saved aggregates.
6. **The m_AB 11 outlier (seed 72) is a trajectory-divergence signature,
   not a larger noise realization.** Its map-difference variance is 3094 nm²
   against 2007–2195 nm² for the other seeds, its 25-frame block error is
   two to four times theirs, its two arms disagree most in validity (63 row-frames
   per run on average at m_AB 11, with seed 72 the largest), and its
   difference-of-variances cross term is −1153 ± 450 nm²: most of the excess
   map difference does not appear in the noisy arm's total residual. Every
   estimator that treats seeds as equal units (per-seed slopes, the two-way
   fit, the unweighted bootstrap) is pulled to about −1.08 by this one run;
   every estimator that weights by the seed scatter stays at about −1.03.
   Which of the two is "right" depends on whether seed 72 is a legitimate
   member of the m_AB 11 population or a gating artefact, which only
   per-frame traces can decide.
7. **Not identifiable from the saved data:** frame-level autocorrelation and
   the adequacy of 25-frame blocks, the per-frame validity masks and their
   effect, DM saturation, the model variance at the operating residual, the
   per-lenslet distribution of the departure, and causality in general. The
   smallest experiment that distinguishes the remaining causes needs
   per-frame telemetry on the existing paired protocol plus two cheap
   configuration arms (no new model); it is specified in
   [`experiment_proposal.md`](experiment_proposal.md).

Literature access during the original analysis was limited: the environment's network
policy denied every scholarly host (arXiv, ADS, OUP, PLOS, A&A, IEEE, PDG,
NIST, numpy.org, docs.scipy.org). The comparison in section 7 therefore rests
on search-index extractions, package docstrings read from the installed
NumPy and the official SciPy wheel, and code restatements on GitHub; every
source carries its access status, and no equation number is quoted as
verified unless the project's own records also give it.

## 1. Source identity, inputs and environment

| Item | Value | Status |
| --- | --- | --- |
| Analysed tree | `claude/cleanup-refactor-exec` at `10f04e268871a19bfedb47b035f2905b67f23e43` ("Harden the package code identity of both evidence scripts", 2026-10-20 15:32 CEST), the frozen input; task branch `claude/eager-franklin-tk0duo` reset onto it; working tree clean apart from this directory | INSPECTED_CURRENT |
| Records | `docs/refactor/detector_level_evidence/det09_noise_isolation_12m_v3.json` (SHA-256 `3dd8d681bc22883c…`), `det09_noise_isolation_2m.json` (`655528b64e087b3f…`), `det09_noise_isolation_2m_attempt1.json` (`333c1a3a3ffc2055…`); full digests in `results.json` | INSPECTED_HISTORICAL |
| Context records read | `det09_e2_noise_propagation*.json`, `det09_e3_magnitude_scan_12m_v3_review.json`, `det07_e1_centroid_noise_review.json`, `e3_v2_snr_diagnostic.{py,txt}`, the detector status file, LIM-18, technical reference 5.11/7.2/7.5/9.3, README | INSPECTED_HISTORICAL |
| Code read | `experiments/detector_level.py` (`paired_noise_run`, `_OperatingExpectationSensor`, `_PupilResidualRecorder`), `wfs/shack_hartmann/physical_measurement.py`, `detector/noise_model.py`, `detector/validity.py`, `control/loop.py`, `control/recovery.py`, `calibration/sparse.py`, `scripts/run_detector_level_evidence.py`, the two profiles | INSPECTED_CURRENT |
| Analysis environment | Python 3.13.16, NumPy 2.5.3 (system) and a scratch venv with SciPy 1.16.2 for an optional check; 2 CPUs, 15 GiB; serial, `OMP_NUM_THREADS=2` | EXECUTED_CURRENT |
| Package import for the optional checks | `shwfs_ao` from `src/` through `PYTHONPATH` (no installation, no system built, no `sys.path` edit): all 76 saved run configuration hashes reproduce on the current code (20/20, 32/32, 24/24); geometry-only illumination check. `results.json` records the task-branch commit that was HEAD when it was regenerated, whose tree is the frozen input plus this directory | EXECUTED_CURRENT |
| Network | package indexes only; every scholarly and documentation host denied by the environment policy (HTTP 403 on CONNECT) | environment limitation |

**Missing essential inputs, stated precisely.** (a) No per-frame trace of
either arm (residual maps, ΔV_t, validity masks, reconstruction flags,
saturation) is committed; the records hold one aggregate per run. (b) The
producing source is an uncommitted working tree based on `663df16` whose
`source_changes_sha256` differs between the three records
(`86f207e4…`, `f94ccee9…`, `740e72b7…`); the first committed form of the
estimator is `573f875`, whose `paired_noise_run` differs from the frozen
input only in two import lines (cleanup CLN-04). The producing code cannot be
reconstructed bit for bit from Git. (c) The pre-refactor audit's F-06
bootstrap script (main checkout `outputs/pre_refactor_audit/…`) is not in the
tree; its estimator was inferred by reproducing its numbers. (d) Nothing in
the saved aggregates records the lenslet count, the DM saturation fraction or
the recovery statistics of the paired runs; the lenslet count (416 at 12 m,
21 at 2 m) was taken from the open-loop propagation records and confirmed
by the geometry check. No missing trace was invented.

## 2. The implemented estimand

Traced from `paired_noise_run` (`src/shwfs_ao/experiments/detector_level.py`,
lines 606–719 at the frozen input) and the components it calls.

**Construction.** Two systems are built from the same `SystemConfig` with
the same root seed (`build_scao_system` twice): same atmosphere realization,
persistent camera maps, calibration products (masters), reference centroids,
interaction matrix and reconstructor. Both run `control.run_closed_loop`
with the same `LoopConfig`, the same `random_streams`, observers that keep
the post-update residual map of every frame from the burn-in frame on
(`_PupilResidualRecorder`, float32 on the finite pupil mask of the first
kept frame), and the profile's recovery policy.

- Arm `noise_on` measures with `include_noise=True`: it is bit-identical to
  `science_run` (tested).
- Arm `operating_expectation` wraps the same sensor so that every
  measurement is `measure_operating_expectation`: the star and sky at the
  operating budget through the operating products with every detector draw
  replaced by its mean (`include_noise=False, operating=True` in
  `_measure_samples`). The loop is told `include_noise=False`.

**Validity gates.** In both arms `_measurement` evaluates
`detector_covariance_quality` on the *expected* frame of that arm's current
residual, and the row mask is `finite & flux ≥ min_flux_e & peak SNR ≥
min_peak_snr & σ ≤ max_centroid_sigma_px & clipping ≤ max_window_clipping`.
The gates therefore never see a noise draw directly, but they do see each
arm's own residual, which contains the propagated noise in the noisy arm.
Once the two trajectories differ, their masks can differ; the reconstructor
(`SparseLsmrReconstructor`, damped least squares on the usable rows,
`min_valid_fraction` 0.5 at 12 m; TSVD with `min_valid_fraction` 0.75 at
2 m) then solves different problems in the two arms. The 12 m `@3` recovery
policy (reset after two consecutive rejected frames) never acted in these
runs: every run reports `reconstruction_usable_fraction` 1.0 in both arms.

**The three recorded quantities.**

| Quantity | Definition in code | What it measures | Assumption for it to equal "the noise contribution" |
| --- | --- | --- | --- |
| `noise_variance_m2` (ΔV) | per frame t ≥ burn-in: δ_t = on_t − off_t on the pupil; piston removed (mean over the pupil subtracted); ΔV = mean over frames of mean over pupil of δ_t² | the second moment of the difference between the two closed-loop trajectories | the loop responds linearly to the noise: no mask switching, no saturation, no centroid nonlinearity; then δ_t is the DM response to past noise draws only |
| `mean_square_difference_m2` (msd) | mean over frames of rms_on² − rms_off², each the piston-removed pupil mean square | a difference of variances: msd = ΔV + 2⟨P off, P δ⟩ | the cross term averages to zero only if δ is uncorrelated with the common residual; its scatter is large when |off| ≫ |δ| |
| `predicted_centroid_variance_px2` (σ²_model) | `wfs.noise_model(zeros)`: the `detector_covariance_v2` temporal variance (x plus y) at a flat wavefront, averaged over the lenslets it supports | an additive per-lenslet noise budget at the diffraction-limited spot | the operating spots have the flat-wavefront second moment; the equal-weight lenslet mean is the propagation-relevant mean |

The ratio ΔV/σ²_model (nm² per px²) is therefore a closed-loop propagation
coefficient. It is constant across magnitudes only if (i) the loop is
linear in the noise, (ii) the lenslet set, reconstructor and controller are
fixed, (iii) every lenslet's variance scales with flux in the same way as
the mean, and (iv) the model is evaluated in the state the loop operates
in. None of (i)–(iv) is guaranteed by the implementation; (iv) is violated
by construction.

**Uncertainties as recorded.** Each run's standard error is the standard
deviation of 25-frame block means over 12 blocks (12 m; 300 analysed
frames) or 6 blocks (2 m; 150 frames) divided by the square root of the
block count. The 2 m study was shortened from 400 to 200 frames before any
result existed because the 2 m screen supports about 204 frames of travel
(status file, amendment 1). A block error from 6 blocks has a relative
uncertainty of about 32 %, from 12 blocks about 21 % (chi distribution with
5 and 11 degrees of freedom). The closed-loop pole moduli are 0.813 (12 m:
gain 0.3, latency 2, leak 0) and 0.723 (2 m: gain 0.2, latency 2, leak
0.02), i.e. correlation times of about 4.8 and 3.1 frames for the sensed
modes; weakly sensed modes decay only through the Tikhonov damping (12 m)
or the leak (2 m, 1/0.02 ≈ 50 frames). Whether 25-frame blocks are long
enough cannot be checked without the frame traces (section 9).

**Identities.** The run configuration hash binds profile, magnitude, seed
and frame count; it reproduces on the current code for all 76 runs. It does
not bind the estimator or the sensor code, which the records identify only
as `663df16` plus an uncommitted-change digest.

## 3. The records and their provenance

| Record | Produced (CEST, 2026-10-16) | Code identity | Estimand | Plan | Notes |
| --- | --- | --- | --- | --- | --- |
| `det09_noise_isolation_2m_attempt1.json` | 20:15:00–20:18:43 (223 s) | `663df16` + `86f207e4…` | `noise_mean_square_m2` = difference of mean squares (no map difference) | `det_emccd_2m_synthetic@1`, m_AB 7, 8, 9; seeds 61–68; 200 frames, burn-in 50 | m_AB 9: both arms identical (valid 0.23–0.31, usable 0.0), value 0; m_AB 10 failed at calibration and is absent; superseded, kept as history |
| `det09_noise_isolation_2m.json` | 20:20:55–20:25:44 (290 s) | `663df16` + `f94ccee9…` | `noise_variance_m2` (map difference) and msd | m_AB 5–8; seeds 61–68; 200/50 | the 16 runs it shares with attempt 1 have the same configuration hash, the same noise-on RMS and an msd equal to attempt 1's value: the arms were unchanged, only the estimator and the magnitudes changed |
| `det09_noise_isolation_12m_v3.json` | 21:02:57–21:46:54 (2637 s) | `663df16` + `740e72b7…` (the same digest as the E3/E4/E2 review reruns that followed) | as above | `det_emccd_12m_medium_derived@3`, m_AB 8–11; seeds 71–75; 400 frames, burn-in 100 | enabled by the user on 2026-10-16; series protocol 2; records cannot be resumed under the current protocol 4 |

The chronology against the commits: base `663df16` committed 19:40; the
three records 20:15–21:47; the estimator first committed as `573f875` at
23:14; the review fixes `580e83f` (23:47) and `62c0092` (00:15 next day)
touched the noise model's calibration-ensemble term and the raw-readout
pedestal, neither of which enters these runs (estimated processing, ADC on).
The audit correction of the quantization gate (2026-10-18) changes which
blocks are supported, not the covariance, and the records' CMOS-free EMCCD
maps are unaffected. The records are the only evidence of the departures;
nothing was rerun here.

The records hold no per-frame data. Per run they hold the seven numbers of
section 2, the per-arm post-update RMS and mean square, the open-loop RMS,
the valid and usable fractions, `lost_lock`, `supported_lenslet_fraction`,
`detected_e_full_subap` and the wall time.

## 4. Reproduction of the historical analysis

Definitions used, taken from the status file ("Isolated detector-noise
variance: predeclared protocol" and the two result sections) and LIM-18:
the seed mean per magnitude with its seed standard error (sample SD over
√n), a weighted least-squares line of log ΔV on log N_e with weights
1/(SE/ΔV)², the *unscaled* covariance for the slope error, the scaled error
as the unscaled error times √(χ²/dof), the model slope as an unweighted
line through the four log σ²_model means, the "power of the model" as the
same weighted line of log ΔV on log σ²_model, the ratio ΔV/σ²_model as the
mean of per-seed ratios, and the dip and the drift as ratio changes between
magnitudes. The F-06 number was matched by resampling whole seeds (all
magnitudes of a seed together) and refitting an unweighted ordinary
least-squares line through the seed means.

| Quantity | 12 m quoted | 12 m recomputed | 2 m quoted | 2 m recomputed |
| --- | --- | --- | --- | --- |
| Weighted log–log slope | −1.028 ± 0.010 | −1.0282 ± 0.0105 | −0.978 ± 0.014 | −0.9782 ± 0.0136 |
| χ²/dof (dof 2) | 2.50 | 2.500 (p = 0.08) | 2.46 | 2.458 (p = 0.09) |
| Standard errors from −1, unscaled / scaled | 2.7 / 1.7 | 2.70 / 1.71 | 1.6 / — | 1.61 / 1.03 |
| Verdict (2 SE, unscaled) | fail | fail | pass | pass |
| Model slope | −1.097 | −1.0966 | −1.051 | −1.0512 |
| Power of the model variance | 0.960 ± 0.010 | 0.9601 ± 0.0098 | 0.950 ± 0.013 | 0.9501 ± 0.0132 |
| Dip m_AB 10 vs 9 / drift m_AB 7 vs 5 | −6.7 % | −6.74 % | −9 % | −9.25 % |
| F-06 unweighted bootstrap | −1.086, SD 0.028 | −1.0855, SD 0.0280 (10⁴ resamples) | — | (−1.353, SD 0.163 for the same convention) |
| Table values (means, SEs, ratios, σ²·N_e) | 16 numbers | all within rounding; the ratio convention (mean of per-seed ratios versus ratio of means) accounts for differences below 0.2 % | 16 numbers | all within rounding |

Status: EXECUTED_CURRENT on the saved aggregates; the largest relative
difference is the quoted 0.010 against the recomputed 0.0105. The
predeclared verdict at 12 m (fail at 2.70 SE) and the pass at 2 m stand
exactly as recorded. The verdict's dependence on the error convention is
real (1.71 SE with the scaled error) and was already recorded by review
R-06; the predeclared rule fixed no convention, so it changes nothing.

Per-magnitude seed statistics (nm² for ΔV; px² for the model):

| Scale, m_AB | N_e | ΔV mean ± seed SE | median | RMS block SE | ΔV·N_e | σ²_model | ΔV/σ²_model ± SE | valid (on) | supported |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 12 m, 8 | 2540.9 | 111.61 ± 1.92 | 110.82 | 2.00 | 283 590 | 0.003431 | 32 527 ± 552 | 0.99995 | 1.000 |
| 12 m, 9 | 1011.6 | 291.41 ± 2.69 | 290.12 | 8.01 | 294 775 | 0.008920 | 32 671 ± 306 | 0.99998 | 1.000 |
| 12 m, 10 | 402.7 | 740.45 ± 8.39 | 735.70 | 15.80 | 298 187 | 0.024303 | 30 467 ± 341 | 0.99998 | 1.000 |
| 12 m, 11 | 160.3 | 2291.3 ± 202.9 | 2082.0 | 91.89 | 367 348 | 0.071191 | 32 196 ± 2885 | 0.9567 | 0.979 |
| 2 m, 5 | 13 001 | 4.270 ± 0.079 | 4.24 | 0.32 | 55 516 | 0.001673 | 2553 ± 47 | 0.99968 | 1.000 |
| 2 m, 6 | 5175.9 | 10.402 ± 0.316 | 10.11 | 0.90 | 53 841 | 0.004268 | 2437 ± 74 | 1.000 | 1.000 |
| 2 m, 7 | 2060.6 | 25.808 ± 0.438 | 25.41 | 1.98 | 53 180 | 0.011140 | 2317 ± 39 | 1.000 | 1.000 |
| 2 m, 8 | 820.3 | 200.7 ± 105.0 | 94.17 | 286 | 164 619 | 0.030627 | 6558 ± 3435 | 0.9489 | 1.000 |

## 5. Alternative estimators and uncertainty conventions

All on the same saved aggregates; whole-seed/magnitude pairing is preserved
wherever seeds are the unit (the same root seed shares the atmosphere, maps
and masters across magnitudes; only the temporal noise differs, as the
identical open-loop RMS per seed confirms).

### 5.1 Slope estimators

| Estimator | 12 m (all four magnitudes) | 2 m (all four) | Comment |
| --- | --- | --- | --- |
| Weighted on seed means, unscaled SE (historical) | −1.028 ± 0.010 | −0.978 ± 0.014 | weights downweight the faintest point (SE 203 and 105) |
| Same, scaled SE (√(χ²/dof)) | −1.028 ± 0.017 | −0.978 ± 0.021 | the `numpy.polyfit(cov=True)` and `curve_fit(absolute_sigma=False)` default |
| Weighted on seed medians | −1.026 ± 0.011 | −0.973 ± 0.014 | exploratory (weights borrowed) |
| Unweighted OLS on seed means (F-06 convention) | −1.086 ± 0.034 | −1.353 ± 0.217 | dominated by the faintest point's mean |
| Per-seed paired slopes, mean ± SE (t with n−1 dof) | −1.081 ± 0.029 (t from −1: −2.83, p = 0.048; seeds 71–75: −1.020, −1.188, −1.059, −1.052, −1.087) | −1.196 ± 0.098 (p = 0.085; seed 68: −1.857) | the only estimator whose error comes from independent units without a within-run error model |
| Per-seed paired slopes without the excursion seed | −1.055 ± 0.014 (without 72) | −1.101 ± 0.029 (without 68) | |
| Two-way OLS with seed effects (dof 14 / 23) | −1.081 ± 0.023 (p from −1: 0.003) | −1.196 ± 0.079 (p = 0.022) | assumes equal residual variance across magnitudes, which fails at the faint end |
| Weighted over all runs with the recorded block SEs | −1.056 ± 0.005, χ²/dof 6.5 | −1.013 ± 0.012, χ²/dof 2.7 | the block errors do not describe the run-to-run scatter at 12 m |
| Leave-one-seed-out, weighted | −1.019 … −1.054 | −0.966 … −0.987 | seed 72 moves the 12 m slope by −0.026 |
| Whole-seed bootstrap of the unweighted OLS slope | mean −1.085, SD 0.028, [−1.146, −1.040] | mean −1.314, SD 0.163 | only 126 (12 m) and 6435 (2 m) distinct resamples exist; not new realizations |
| **Gate-quiet subset, weighted** (m_AB 8–10 / 5–7) | **−1.024 ± 0.011**, χ²/dof 0.97; per-seed −1.027 ± 0.012 | **−0.977 ± 0.014**, χ²/dof 0.08; per-seed −0.977 ± 0.015 | the three points are consistent with one power law at each scale |
| Model slope on the same subset | −1.063 | −1.029 | flat-wavefront `detector_covariance_v2` |

Two families emerge at 12 m: estimators that weight by the seed scatter give
−1.03, estimators that give every seed equal weight give −1.08. The
difference is seed 72 at m_AB 11 (section 6, finding 6). At 2 m the same
split is between −0.98 (weighted; m_AB 8 carries a 52 % relative error and
contributes almost nothing) and −1.2 to −1.35 (equal weights; m_AB 8
dominates). The 2 m "pass" is a statement about m_AB 5–7.

### 5.2 Floor-share fit

For a variance a/N_e + b/N_e², ΔV·N_e is linear in 1/N_e with intercept α
(photon term) and slope β (additive floor); β/α is the flux at which the
floor equals the photon term.

| Scale | Measured β/α (e⁻), seed-SE weighted | medians | without the faintest point | Model b/a (e⁻) | Model floor share per magnitude |
| --- | --- | --- | --- | --- | --- |
| 12 m | 20.8 ± 8.2 (χ²/dof 2.26) | 17.6 | 16.5 ± 8.7 (χ²/dof 2.41) | 53.5 | 2.1 %, 5.0 %, 11.7 %, 25.0 % at m_AB 8–11 |
| 2 m | −93 ± 57 (χ²/dof 1.05) | −106 | −96 ± 57 (χ²/dof 0.31) | 137.5 | 1.0 %, 2.6 %, 6.3 %, 14.4 % at m_AB 5–8 |

At 12 m the measured floor is about 40 % of the model's (a 4-SE deficit that
does not depend on the m_AB 11 point); at 2 m the fitted floor is negative
(a 4-SE deficit against the model, and 1.6 SE below zero). The model's own
floor is reproduced from first principles in section 7.2.

### 5.3 Ratio trend, dip and drift, paired by seed

| Comparison | Mean ratio change | Median | Per-seed paired mean ± SE | t, dof, p |
| --- | --- | --- | --- | --- |
| 12 m, 9 vs 8 | +0.44 % | +0.70 % | +0.55 ± 1.91 % | 0.29, 4, 0.79 |
| 12 m, 10 vs 9 | −6.74 % | −6.91 % | −6.68 ± 1.77 % | −3.77, 4, 0.020 |
| 12 m, 11 vs 10 | +5.67 % | −3.62 % | +5.79 ± 9.77 % | 0.59, 4, 0.59 |
| 12 m, 10 vs 8 (gate-quiet ends) | | | −6.21 ± 2.00 % | −3.11, 4, 0.036 |
| 2 m, 6 vs 5 | −4.53 % | −6.54 % | −4.28 ± 3.54 % | −1.21, 7, 0.27 |
| 2 m, 7 vs 6 | −4.94 % | −3.64 % | −4.55 ± 2.29 % | −1.99, 7, 0.087 |
| 2 m, 7 vs 5 (gate-quiet ends) | −9.25 % | | −8.99 ± 2.58 % | −3.48, 7, 0.010 |
| 2 m, 8 vs 7 | +183 % | +34.8 % | +184 ± 149 % | 1.24, 7, 0.26 |

At 12 m the per-seed ratio falls from m_AB 9 to 10 in all five seeds (−11,
−10, −5, −2, −6 %). At m_AB 11 the mean ratio returns to the m_AB 8 level
only because of seed 72 (43 604 against 28 142–30 854 for the other four);
the median continues downward (−3.6 %). Six such adjacent comparisons were
made; a 2 % two-sided probability for the largest of them is not strong
evidence of a magnitude-specific effect.

### 5.4 Within-run against between-seed scatter

| Scale, m_AB | Seed SD of ΔV | RMS block SE | Ratio |
| --- | --- | --- | --- |
| 12 m, 8 / 9 / 10 / 11 | 3.8 / 2.1 / 2.5 / 19.8 % | 1.8 / 2.7 / 2.1 / 4.0 % | 2.14 / 0.75 / 1.19 / 4.94 |
| 2 m, 5 / 6 / 7 / 8 | 5.2 / 8.6 / 4.8 / 148 % | 7.6 / 8.7 / 7.7 / 143 % | 0.68 / 0.99 / 0.63 / 1.04 |

At 2 m the block errors describe the seed scatter. At 12 m m_AB 8 the seeds
scatter twice as much as their block errors predict: the propagation
coefficient depends on the realization at the few-per-cent level (the
per-seed ratios at m_AB 8 span 31 162–34 228), which is expected if spot
broadening by the realization's residual sets the photon term. The
predeclared choice to weight by the seed scatter rather than by the block
errors was therefore the right one, with the caveat that a seed SE from five
seeds is itself uncertain by about 35 % (GUM 4.2.3 rule, section 7.3).

### 5.5 The difference-of-variances cross term

msd − ΔV estimates 2⟨P off, P δ⟩ per run (its error is approximated from the
recorded msd and ΔV block errors; the per-frame covariance is not saved).

| Scale, m_AB | Seed mean ± SE (nm²) | Relative to ΔV | Weighted z | Median msd SE / ΔV SE |
| --- | --- | --- | --- | --- |
| 12 m, 8 / 9 / 10 | −43 ± 44 / +44 ± 71 / −1 ± 92 | −38 % / +15 % / 0 % | −0.9 / −0.1 / −0.9 | 28 / 15 / 10 |
| 12 m, 11 | −367 ± 215 (seed 72 alone: −1153 ± 450) | −16 % | −2.8 (without seed 72: −170 ± 150) | 4.7 |
| 2 m, 5 / 6 / 7 | −43 ± 29 / −70 ± 35 / +32 ± 47 | 10 × / 7 × / 1.2 × ΔV | −2.0 / −1.1 / +0.3 | 192 / 106 / 74 |
| 2 m, 8 | −263 ± 370 | −131 % | +1.1 | 23 |

The difference of variances carries a standard error 5–200 times that of
the paired map difference, which is why the first 2 m attempt (−1547 to
+994 nm² per run at m_AB 7–8) was unusable; the synthetic example in
section 8 reproduces the mechanism. Where the gates are quiet the cross term
is consistent with zero (the 2 m m_AB 5 value is 2 SE in one of eight
tests). Its one clear non-zero value is seed 72 at m_AB 11.

### 5.6 Gate divergence between the arms

Invalid row-frames per run (two rows per lenslet; noisy arm / twin / mean
absolute arm difference): 12 m m_AB 8–10: 6.4 / 6.4 / 0.0, 4.8 / 6.4 / 1.6,
6.0 / 6.0 / 0.8 (a few lenslet-frames out of 125 000); m_AB 11: 10 816 /
10 753 / 63; 2 m m_AB 5–7: 0.3 / 0.3 / 0.0; m_AB 8: 322 / 324 / 5.8.
Among the 14 (12 m) and 11 (2 m) runs with any invalid row, the absolute
arm difference in valid fraction correlates with the run's ΔV excess over
its magnitude median with Pearson r = 0.87 and 0.94, but Spearman 0.38 and
0.21: the correlation is carried by the single extreme run at each scale
(seed 72 at m_AB 11; seed 68 at 2 m m_AB 8, 933 ± 807 nm² against a median
of 94). One 2 m run (m_AB 8, seed 65) also has a rejected frame in its
noisy arm (`reconstruction_usable_fraction` 0.993) and none in its twin.
Suggestive, not demonstrated.

## 6. What the saved data establish

| # | Finding | Evidence | Class | Confidence |
| --- | --- | --- | --- | --- |
| 1 | The historical numbers are exactly reproducible and their fitting definitions are now explicit (section 4) | 51 quoted values recomputed; `results.json` | reproducibility | high |
| 2 | The 12 m predeclared criterion failed as recorded; the 2 m one passed as recorded; the verdict at 12 m depends on the unscaled-error convention (2.70 vs 1.71 SE), as review R-06 already noted | section 4 | documentation/provenance, closed | high |
| 3 | Below the gated magnitudes the closed-loop noise variance follows a single power law at each scale with exponent shallower than the flat-wavefront model's by 0.039 ± 0.011 (12 m) and 0.052 ± 0.014 (2 m); the measured floor is 40 % of the model's at 12 m and consistent with zero or negative at 2 m | sections 5.1–5.2 | model discrepancy *as compared*; see finding 4 | moderate–high (3.5–4 SE at each scale, independent) |
| 4 | The comparison model was evaluated at a flat wavefront; the implemented model's photon term grows with the operating spot's window-truncated second moment while its floor terms do not, so the same model evaluated at the operating residual predicts an exponent closer to −1; this can account for the 12 m finding with a photon-term excess factor of about 2.6, which a stand-alone second-moment illustration makes plausible for 0.5–1 rad² of tilt-removed phase per subaperture; it cannot make the 2 m exponent shallower than −1 | sections 7.2 and 8; `e3_v2_snr_diagnostic.txt` shows only +7–10 % for a scaled-atmosphere proxy that carries almost no high-order phase | hypothesis H1, consistent, untested | moderate |
| 5 | The 6.7 % dip at m_AB 10 is one step of the shallow trend (−6.2 ± 2.0 % from m_AB 8 to 10 by paired seeds) and is not shown to be magnitude-specific; the m_AB 11 mean ratio hides the trend because of seed 72 | section 5.3 | reinterpretation of a recorded departure | moderate |
| 6 | Seed 72 at m_AB 11 shows the three signatures of a trajectory divergence (excess ΔV, a 3× block error, the largest arm-mask disagreement, a negative cross term of −1153 ± 450 nm²); the 2 m m_AB 8 seed 68 run shows the same pattern | sections 5.5–5.6 | hypothesis H2 (gate divergence), suggestive | moderate for the signature, low for the mechanism |
| 7 | The equal-weight and seed-weighted estimator families disagree (−1.08 vs −1.03 at 12 m; −1.2 vs −0.98 at 2 m) because of one run each; the F-06 bootstrap belongs to the equal-weight family and its 28 bootstrap SD understates the disagreement between conventions | section 5.1 | uncertainty-convention finding | high |
| 8 | The 2 m drift (−9.0 ± 2.6 % by paired seeds, p ≈ 0.01) has no additive explanation; it needs a mechanism that makes the propagated noise grow slower than the centroid variance | sections 5.2–5.3 | unexplained departure, preserved | moderate (one of several comparisons; 8 seeds) |
| 9 | The sensor-level model is not the problem at the lenslet level: E1 (review rerun) measures the EMCCD centroid scatter within 1.3 % of `detector_covariance_v2` from 100 to 10⁴ e⁻ (plain spot; within 1.1 % from 1000 e⁻ with a background), a range that spans both studies' fluxes and, for E1's 1.2-pixel Gaussian spot in the same 15-pixel window, a floor share of about 13 % at 1000 e⁻, 33 % at 300 e⁻ and 59 % at 100 e⁻ (scalar estimate); E2 verifies the open-loop propagation through the fixed reconstructor within 2 % at both scales | `det07_e1_centroid_noise_review.json`, `det09_e2_noise_propagation*_review.json` | numerical verification (static, fixed masks) | high for what it covers |
| 10 | The equal-weight lenslet mean is a mild distortion only: with 340 of 416 lenslets fully illuminated and a minimum area fraction 0.618, the mean of 1/f and 1/f² are 1.039 and 1.095, so lenslet weighting changes b/a by about 5 % | geometry check in `results.json` | hypothesis H3, minor | high |

## 7. Literature and documentation comparison

### 7.1 Access status

The environment's network policy denied CONNECT to every scholarly and
documentation host (arXiv and its mirrors, ADS, OUP, A&A, PLOS, IEEE
Xplore, SPIE, Cambridge, projecteuclid, NIST, PDG, numpy.org,
docs.scipy.org). What was available: search-index extractions of the
sources' pages (near-verbatim sentences, equation numbers unverified), the
NumPy 2.5.3 docstring installed locally (the source of the manual page),
the SciPy 1.18.1 wheel's docstring from PyPI, and GitHub-hosted code that
restates formulas with attribution (tertiary). The statuses below use the
project's vocabulary; "relevant passage via index" means a sentence
returned by the search index, not a page read.

| Source | Locator | Access | Supports |
| --- | --- | --- | --- |
| Thomas, Fusco, Tokovinin, Nicolle, Michau, Rousset 2006, MNRAS 371, 323, DOI 10.1111/j.1365-2966.2006.10661.x | §2.3, §3.1, Appendix A; equations (11)–(13) per the search index and per the project's own ledger note (roadmap G11: "section 3.1 (equation 13, Appendix A)") | relevant passages via index; equation numbers unverified by reading | CoG variance = photon term ∝ 1/N_ph (Gaussian spot, window-independent) or ≈ 2W/N_ph for a sinc² spot (grows with the window field of view W) + read-noise term (π²/3)(N_r²/N_ph²)(N_s²/N_samp)² ∝ N_s⁴/N_ph²; "in presence of RON the noise does not depend on the structure of the spot"; a simple centroid reaches the Cramér–Rao bound for a Gaussian spot with photon noise (attributed to Rousset 1999) |
| Rousset 1999, "Wave-front sensors", in Roddier (ed.) Adaptive Optics in Astronomy, CUP, pp. 91–130 | chapter | inaccessible (book) | the Gaussian-spot formulas Thomas 2006 attributes to it; secondary only |
| Oyarzún et al. 2024, A&A 691, A205, DOI 10.1051/0004-6361/202451670 (open access, arXiv:2410.04863) | Appendix A, (A.5), (A.7), (A.8) per index | relevant passages via index | matrix form Cov_RON = (Σ²/N²) M Mᵀ, Cov_ph = (1/N) M diag(I₀) Mᵀ; restates the Thomas forms |
| Basden, Haniff, Mackay 2003, MNRAS 345, 985, DOI 10.1046/j.1365-8711.2003.07020.x (arXiv astro-ph/0307305) | output distribution p(x\|n) = x^(n−1) e^(−x/g)/(gⁿ(n−1)!), Appendix A; ENF √2 at large gain | relevant passages via index | the Gamma/Erlang register model and F² = 2 ("equivalent to halving the QE") |
| Robbins & Hadwen 2003, IEEE TED 50, 1227, DOI 10.1109/TED.2003.813462 | F² = 2(G−1)G^(−(N+1)/N) + 1/G as restated by Wilkins et al. 2014 eq. (4) and a NASA-JPL ETC note | abstract only (paraphrase); formula tertiary | F² → 2 at high gain; at G = 300 with 536–604 stages F² ≈ 1.976–1.978, 1.2 % below the implemented 2 |
| Hirsch et al. 2013, PLoS ONE 8, e53671, DOI 10.1371/journal.pone.0053671 | register as a chain of gain stages; Gamma chosen as the EM-register model; n = 0 handled separately | relevant passages via index | the implemented Gamma(n, G) with zero output at n = 0 |
| Daigle et al. 2009, PASP 121, 866, DOI 10.1086/605449; Daigle et al. 2008, Proc. SPIE 7014, 70146L | CIC 0.001–0.002 e⁻/px/frame for a low-CIC controller, 0.01–0.1 for older electronics; σ_eff = σ/G; "CIC dominates over all the other sources of noise at high frame rate"; in-register CIC receives partial gain | relevant passages via index | the preset's 0.005 e⁻/px/read lies between modern and older values; the implementation's fully amplified pre-register CIC is the declared scope (in-register CIC is excluded) |
| Wilkins et al. 2014, Proc. SPIE 9154 (arXiv:1407.0701) | eqs (2)–(6) | full text read via a GROBID-TEI mirror on GitHub | SNR_AM = S/√(F²S + D + σ_r²/g²); CIC "multiplied in the same way that a photoelectrically generated electron is amplified"; measured CIC 0.0007 e⁻/px/frame |
| `numpy.polyfit` (NumPy 2.5.3 docstring; manual page numpy.org/doc/stable/reference/generated/numpy.polyfit.html) | parameters `w` and `cov` | docstring read verbatim from the installed package | "By default, the covariance are scaled by chi2/dof … This scaling is omitted if cov='unscaled', as is relevant for the case that the weights are w = 1/sigma, with sigma known to be a reliable estimate of the uncertainty" |
| `scipy.optimize.curve_fit` (SciPy 1.18.1 wheel docstring) | `absolute_sigma` | docstring read verbatim from the PyPI wheel | "pcov(absolute_sigma=False) = pcov(absolute_sigma=True) * chisq(popt)/(M-N)" |
| Particle Data Group, Review of Particle Physics, Introduction §5 "Averages and fits", "Unconstrained averaging" (2024/2025 editions) | scale factor S = √(χ²/(N−1)) applied when χ²/(N−1) > 1 "but not greatly so" | relevant passages via index; square root confirmed from the 1978/1988 archive wording | the "scaled error" convention quoted beside the unscaled one |
| Flyvbjerg & Petersen 1989, J. Chem. Phys. 91, 461; Wolff 2004, Comput. Phys. Commun. 156, 143 (arXiv hep-lat/0306017); Sokal 1997 (Cargèse notes) via Mendes, Pelissetto & Sokal 1996 (hep-lat/9604015) | blocking method; "binning severely underestimates the errors" when bins are not much longer than the autocorrelation time; Var(mean) = 2τ_int σ²/n | abstracts and passages via index | the block-error caveat of section 2 and the synthetic example of section 8 |
| Künsch 1989, Ann. Statist. 17, 1217 (open access); Hesterberg 2015, Am. Stat. 69, 371 (arXiv:1411.5279); Cameron, Gelbach & Miller 2008, Rev. Econ. Stat. 90, 414 | moving block bootstrap; "bootstrapping does not overcome the weakness of small samples", percentile intervals too narrow by about √((n−1)/n) and lacking the t/z factor; standard tests "over-reject with few (5–30) clusters" | abstracts and passages via index | the caveats on the five-seed bootstrap |
| NIST/SEMATECH e-Handbook 1.3.5.2 and 2.3.6.5.2; JCGM 100:2008 (GUM) 4.2.3 note and Annex G | t_{0.975,4} = 2.776; relative uncertainty of a sample SD ≈ [2(n−1)]^(−1/2) | relevant passages via index | the t-based per-seed intervals and the 35 % uncertainty of a five-seed SE |

### 7.2 Bridge to the implementation

**The implemented floor is the Rousset/Thomas read-noise term, generalized.**
`detector_covariance_v2` propagates per-pixel variances through the CoG
Jacobian w_k = (x_k − c)/T over the window: Var_t(c) = Σ_k w_k² (σ_k² +
q_k²/12) + G²F² Σ_l μ_l (Kᵀw)_l². For a uniform additive floor σ_f² over an
N_s × N_s window (N_s = 15) the first sum is σ_f² · N_s²(N_s² − 1)/12 / T²
≈ σ_f² N_s⁴/(12 T²) in px², which in Thomas's units of phase difference
across the subaperture (× (2π/N_samp)²) is exactly (π²/3)(σ_f²/T²)
(N_s²/N_samp)²: the literature read-noise formula with σ_f² = σ_read²/G² +
F²·CIC + q²/12 (plus sky and dark). With the preset values
(60/300)² + 2 × 0.005 + (15/300)²/12 = 0.0502 e⁻²/px, Σ(x−c)² = 4200 px²
per axis and the lenslet illumination factor 1.095, the floor is
b ≈ 462 px² e⁻² for x plus y; the fit to the recorded model column gives
b = 459. The photon term a = 8.58 px² e⁻ corresponds to a window-truncated
second moment of about 4.0 px² (x plus y) at the diffraction-limited spot;
a stand-alone computation of a Nyquist-sampled diffraction spot in a
15-pixel window gives 3.5 px² (section 8), so the recorded model column is
what the literature CoG formulas give for this window. The recorded model
slope −1.097 is therefore not a model peculiarity: it is the standard
prediction for a plain CoG over 225 pixels with a 0.05 e⁻² floor at
160–2540 e⁻.

**What the literature says about the spot dependence** matches the
hypothesis of section 6, finding 4: the read-noise term "does not depend on
the structure of the spot" (Thomas 2006 §3.1), whereas the diffraction-spot
photon term grows with the field of view actually used, i.e. with the
spot's second moment inside the window. A broadened spot raises a and leaves
b, so the flux exponent of the sum moves toward −1. The project's own E2
check evaluated the model at the same static residual as the measurement
and found 0.999; the paired study's model column was evaluated at a flat
wavefront, which E2 does not test.

**EMCCD register and CIC.** The implementation's Gamma(n, G) register with
F² = 2 and zero output at n = 0 matches Basden 2003 and Hirsch 2013. The
finite-register F² (≈ 1.98 at G = 300) and the CIC level (0.005 against
0.001–0.002 for modern controllers) affect the realism of the synthetic
preset, not the departure: the simulation and the model use the same
numbers, so they cancel in ΔV/σ²_model. The in-register CIC that Daigle and
Wilkins describe (partial gain) is outside the declared scope.

**Statistics conventions.** The repository's "unscaled" error is NumPy's
`cov='unscaled'` and SciPy's `absolute_sigma=True`; the "scaled" one is
their default and the PDG scale-factor convention. With dof = 2 a χ²/dof of
2.5 has a two-sided probability of 0.08, so the scale factor is not
required by the data; the recorded verdict used the convention that the
weights are absolute. The five-seed structure limits every convention: a
seed SE is uncertain by about 35 %, t_{0.975,4} = 2.78 widens a per-seed
interval by 42 % over the normal quantile, and the bootstrap's percentile
interval lacks both corrections.

### 7.3 Where the sources contradict or qualify the record

- The record calls the departure "unexplained"; the Thomas/Rousset
  structure says the departure's *sign and rough size* are what a
  flat-wavefront evaluation must produce in a loop whose spots are
  broadened. The record's own candidate ("the model is evaluated at a flat
  wavefront, while the closed-loop residual broadens the spots") is the
  same statement; this note adds the quantitative requirement (photon-term
  factor about 2.6 at 12 m) and the observation that it cannot produce the
  2 m exponent.
- No source supports treating 25-frame block errors from 6–12 blocks as
  known errors; the blocking literature requires a plateau check that the
  saved aggregates cannot provide.
- No source supports a five-cluster bootstrap interval as a validated
  uncertainty; the record already labels F-06 exploratory, consistently.

## 8. Synthetic statistical examples (not AO simulations)

Produced by `analyze_saved_records.py` with a fixed RNG seed; they illustrate mechanisms,
they do not model the instrument.

| Example | Result | Reading |
| --- | --- | --- |
| Block error of an AR(1) series (300 frames) against the true error of the mean | τ_int 3: blocks of 1/5/25/75 give 0.42/0.74/0.94/0.92 of the truth; τ_int 10: 0.23/0.48/0.81/0.94; τ_int 50: 0.09/0.20/0.41/0.60 | 25-frame blocks are adequate for the sensed modes (τ ≈ 3–5 frames) and underestimate by 20–60 % for modes with τ ≥ 10 frames (2 m leak-limited modes, τ ≈ 50) |
| Paired difference against difference of variances in a linear toy loop, common signal 1/10/50 × the noise RMS | paired estimate 2.05–2.07 ± 0.3 (truth 2.06); difference of variances 1.5–2.0 ± 1.3 / 12 / 61 | the cross term's scatter grows with the common residual; attempt 1 failed for this reason |
| One of five runs at the faintest flux carrying a 60-frame excursion at 3× its level (+40 % run mean) | unweighted slope −1.025 instead of −1.000; median-based −1.002 | a single excursion moves an equal-weight slope by the amount seen between the two estimator families |
| Window-truncated second moment of a diffraction spot (square subaperture, Nyquist sampling, 15 px window) behind random tilt-removed phase | flat: 3.51 px² (capture 0.96); 0.25 / 0.5 / 1.0 / 1.5 rad²: × 1.73 ± 0.12 / 2.40 ± 0.27 / 3.46 ± 0.41 / 4.53 ± 0.58 (capture 0.94 … 0.85) | the photon-term factor of about 2.6 required at 12 m corresponds to roughly 0.5–0.6 rad² of high-order phase per subaperture (70–80 nm RMS at 700 nm), well inside a 180 nm total closed-loop residual whose fitting error lives at the actuator pitch; plausibility only |

## 9. Ranked hypotheses

| Rank | Hypothesis | Mechanism | Prediction (sign, size) | Consistency with the saved data | Testable now? | Discriminating evidence |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | H1 — evaluation-state mismatch: the flat-wavefront model underestimates the operating photon term, so the floor share is overstated | closed-loop residual broadens the spots inside the window; floor terms unchanged | measured exponent between −1 and the flat model's; ratio ΔV/σ²_flat declines smoothly toward the faint end; with a'/a ≈ 2.6 the 12 m decline is −2, −4, −9 % per step | 12 m: yes within 1–1.5 SE per step and the floor-share fit; 2 m: explains at most half the drift and cannot make the exponent shallower than −1; realization dependence at m_AB 8 (overdispersion 2.1) is a corollary; the twin-residual correlation test (r ≈ 0) is uninformative because the pupil RMS is dominated by displacing low-order modes | no (no residual map saved) | the model evaluated at the twin's residual every frame; predicted outcome: ratio ΔV/σ²_model(residual) constant across m_AB 8–11 within ±3 % |
| 2 | H2 — gate divergence between the arms at the gated magnitudes | masks depend on each arm's own residual; the arms solve different problems; the trajectory difference is not propagated noise | excess ΔV with a negative cross term, concentrated in frames where the masks differ; only at m_AB 11 (12 m) and m_AB 8 (2 m) | seed 72 and seed 68 show the signature; the other runs at those magnitudes do not | partly (signatures) | per-frame masks of both arms and ΔV_t; a mask-locked noisy arm removes the excess if H2 holds |
| 3 | H4 — 2 m compressive nonlinearity: DM stroke saturation (1 µm) or another amplitude-limiting element | noise-driven commands clipped more often as the noise grows | ΔV grows slower than σ²; exponent shallower than −1 at 2 m, absent at 12 m (100 µm stroke) | matches the 2 m sign; no saturation telemetry saved; no clear correlation of the per-seed drift with open-loop RMS (weak test) | no | per-frame saturation fraction per arm; a 2 m arm with 10× stroke (configuration only) |
| 4 | H5 — operating-flux calibration at 2 m | the 2 m profile has no internal source, so the reference and interaction matrix are recalibrated at each magnitude through the realized masters | a magnitude-dependent reconstructor; first-order estimate ≤ 0.1 % at m_AB 7, i.e. far too small | sign unspecified; magnitude estimated negligible | no | a 2 m arm with an internal calibration source (configuration only, as `@2`/`@3` at 12 m) |
| 5 | H6 — statistical: the dip is a fluctuation on a smooth trend; the 2 m drift is a 2.6-SE effect among several comparisons | five and eight seeds; six adjacent comparisons | no structure beyond the smooth trend | the paired tests give p = 0.02–0.04 (12 m) and 0.01 (2 m); not excluded, not established | yes (done) | ten seeds and intermediate magnitudes |
| 6 | H3 — lenslet weighting (equal-weight mean versus propagation-weighted) | edge lenslets carry a larger floor share | ≤ 5 % on b/a | too small for the 12 m deficit, wrong order for 2 m | yes (geometry) | per-lenslet model and propagation weights |
| 7 | H7 — block errors underestimate the run error (correlation time > 25 frames) | leak- or damping-limited modes | affects the error bars, not the means | overdispersion ≈ 1 at 2 m argues against a large effect there; at 12 m the seed scatter exceeds the block error for other reasons | no | per-frame ΔV_t and a blocking plateau |
| 8 | H8 — the floor terms themselves (read noise, CIC, quantization) propagate less than modelled | — | would require the lenslet-level model to fail at low flux | excluded at the lenslet level by E1 (≤ 1.3 % at 100–10⁴ e⁻ with floor shares up to about 60 %) and in open loop by E2 (within 2 %); no closed-loop mechanism identified | yes (E1/E2) | — |
| 9 | H9 — CoG ratio bias at low SNR | second-order gain change of the ratio estimator | +1.6 % at m_AB 11, 0.1 % at m_AB 8 | wrong sign and size | analytic | — |

## 10. Evidential limits

From the saved aggregates it is **not identifiable** whether (a) the 25-frame
blocks exceed the loop's correlation time for every mode (no frame trace),
(b) the m_AB 11 excess of seed 72 is stationary or an excursion, and whether
it coincides with mask disagreement (no per-frame masks), (c) the photon
term at the operating residual is 1.5 or 3 times the flat-wavefront value
(no residual map, no model evaluation at the residual), (d) the 2 m DM
saturates (no saturation telemetry), (e) which lenslets carry the departure
(no per-lenslet data), and (f) causality in general, since every run is
one configuration at one magnitude and the only intervention is the noise
switch. Bootstrap resamples of five seeds cannot stand in for (a)–(f).

What **is** established: the recorded numbers, their definitions and the
provenance chain of the three records; the exact estimand and its
assumptions; the sensor- and open-loop-level validity of the noise model at
these fluxes (E1 within 1.3 %, E2 within 2 %); the two-family structure of the slope estimators and
its single-run origin; the internal consistency of the gate-quiet points
with one shallow power law at each scale; and the floor deficit relative to
the flat-wavefront model as a 3.5–4 SE effect at each scale. "Explained" is
the wrong word for any of the departures today; "bounded and attributable
to a short list of mechanisms with a cheap discriminating experiment" is
accurate.

## 11. Conclusions for the roadmap

- Keep LIM-18's recorded verdict, numbers and conventions unchanged. This
  note adds a reinterpretation and a test, not a correction.
- This note proposed that its saved-data bounds satisfied S4's "bounded
  and kept as unexplained" criterion. That proposal was not an acceptance
  decision. Current S4 status and execution criteria are recorded in the
  roadmap and the post-T2 experiment packet.
- Any future "model" column should be evaluated at the operating residual
  (or both states reported); the flat-wavefront value is still useful as the
  diffraction-limited reference.
- The original next-experiment proposal is retained in
  [experiment_proposal.md](experiment_proposal.md) as research history. Current
  execution planning uses [the post-T2 protocol](../post_t2_experiment_packet/PROTOCOL.md)
  and its [pilot requests](../post_t2_experiment_packet/pilot_requests.json).
