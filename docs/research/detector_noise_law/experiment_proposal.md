# Historical detector-noise experiment proposal (2026-10-20)

Status: **historical proposal, not executed as part of this note.** Execution
planning and acceptance criteria are superseded by [the post-T2 experiment
protocol](../post_t2_experiment_packet/PROTOCOL.md) and its
[pilot requests](../post_t2_experiment_packet/pilot_requests.json).

Original proposal: The 12 m arms are governed runs (cost
category C2) that need the user's enablement for each concrete run; the
2 m arms are ungated by the recorded policy but were not run either. The
hypotheses, estimands and numbers it refers to are in [`report.md`](report.md).

## 1. Question and hypotheses

Why does the isolated closed-loop detector-noise variance ΔV grow more
slowly with 1/N_e than the flat-wavefront `detector_covariance_v2` variance,
at both scales, and what are the m_AB 11 (12 m) and m_AB 8 (2 m) excursions?

| Hypothesis | Observable that decides it |
| --- | --- |
| H1 — the model's photon term at the operating residual is larger than at a flat wavefront (floor share overstated) | the same model evaluated on the twin arm's residual map every frame: the ratio ΔV / σ²_model(residual) across magnitudes |
| H2 — the arms' validity masks diverge and the trajectory difference is not propagated noise | per-frame masks of both arms, ΔV_t and the per-frame cross term; a mask-locked noisy arm |
| H4 — a compressive nonlinearity at 2 m (DM stroke 1 µm) | per-frame saturation fraction per arm; a 2 m arm with a 10 µm stroke |
| H5 — operating-flux calibration at 2 m | a 2 m arm with an internal calibration source |
| H6/H7 — statistics: fluctuation, block length | ten seeds, intermediate magnitudes, the per-frame ΔV_t trace for a blocking plateau |

## 2. Design

### Arm A (12 m, governed): the existing paired protocol with per-frame telemetry

- Profile `det_emccd_12m_medium_derived@3`, unchanged. Magnitudes m_AB 8,
  9, 10, 10.5, 11 (the two intermediate points separate a smooth trend
  from a step). Root seeds 71–80 (the five recorded seeds plus five new
  ones; the recorded ones give a direct replay check of the recorded
  aggregates). 400 frames, burn-in 100, block 25 as recorded, plus the
  per-frame trace that makes the block length checkable.
- Fixed physical inputs: atmosphere (the `native_layered` ESO-derived
  profile, r0 0.13 m at 500 nm, 10 layers), telescope and lenslet geometry
  (12 m, 24 × 24, 416 retained lenslets), camera preset
  `synthetic_emccd_coupled@1` (G 300, read noise 60 e⁻ output, CIC 0.005
  e⁻/px/read, 15 e⁻/ADU, 16 bit), 15-pixel window with a one-pixel guard,
  R3 band with three nodes, MFT oversampling 4 with 0.2 px diffusion,
  internal calibration source 2500 e⁻, estimated products with 32 frames
  each, controller gain 0.3, latency 2, leak 0, Tikhonov damping 0.1,
  the reset policy. Nothing physical changes between magnitudes except the
  guide-star flux.
- Execution as recorded: `telemetry_level='summary'`, `lenslet_batch_size`
  512, materialized bands, serial, two native threads.

### Arm B (12 m, governed, conditional): mask-locked noisy arm at m_AB 11

Run only if arm A shows that the m_AB 11 excess runs coincide with
mask disagreement. The noisy arm uses, at every frame, the twin's row mask
of that frame (the twin runs first and its per-frame `measurement_row_masks`
are replayed into the noisy arm's measurement vector as `valid_rows`). Same
seeds 71–80, m_AB 11 only. If H2 holds, the excess ΔV and the negative cross
term disappear and ΔV becomes a clean propagated-noise estimate at the
faint end; if they persist, the excursion is in the noise propagation
itself.

### Arm C (2 m, ungated): two configuration variants against the baseline

- C0 baseline: `det_emccd_2m_synthetic@1`, m_AB 5, 6, 7 (the gate-quiet
  range), seeds 61–68, 200 frames, burn-in 50, with the per-frame telemetry.
- C1 stroke: the same with the profile's `dm.stroke_limit_opd_m` 1e-5
  instead of 1e-6 (a configuration-only change built in code, like
  `with_physics`; it moves the DM identity, so it is a new in-code
  configuration, never a published profile). If the drift and the shallower-than-−1 exponent vanish, H4.
- C2 source: the same with
  `detector_physics.calibration_source_detected_e_per_full_subap_frame`
  = 2500 (the `@2`/`@3` device at 12 m). If the drift vanishes, H5.
- C1 and C2 are paired with C0 by seed. Both are cheap (section 6).

## 3. Observables and telemetry

Per run and per arm, in addition to the recorded aggregates:

| Field | Source | Purpose |
| --- | --- | --- |
| ΔV_t (pupil mean of the piston-removed squared map difference, per frame) | the existing `_PupilResidualRecorder` samples, reduced per frame instead of over frames | blocking plateau (block lengths 1 … 75), excursion detection, the per-frame cross term 2⟨P off_t, P δ_t⟩ |
| `measurement_row_masks[t]` of both arms | already in `LoopHistory` | mask disagreement per frame; H2 |
| `reconstruction_usable[t]`, `saturation_fraction[t]`, `valid_measurement_fraction[t]` of both arms | already in `LoopHistory` | recovery events, DM saturation (H4), gate activity |
| σ²_model(residual_t): the supported-lenslet mean (x plus y) of `wfs.noise_model(post_update_residual_opd_m)` on the twin arm's map, every frame; optionally the per-lenslet vector and `supported` | a frame observer calling the existing `noise_model`; about one noiseless measurement per frame | H1 directly; H3 with the per-lenslet vector |
| σ²_model(flat) | as recorded | the diffraction-limited reference |
| `recovery` statistics | `history.metadata["recovery"]` (12 m) | confirm the reset never acted |
| retained residual maps for two seeds per magnitude (both arms, float32) | the recorder's samples | offline re-evaluation of the model under other assumptions |

Code needed: a small observer in `paired_noise_run` (or a sibling
`paired_noise_run_traced`) that reduces ΔV_t per frame, evaluates the model
on the twin's map and stores the per-frame arrays; and, for arm B, a sensor
wrapper that overrides `valid_rows` with a supplied per-frame mask. The
runner would write the per-frame arrays to a sidecar `.npz` per run next to
the JSON record. No runtime source, profile, accepted resource or existing
record changes; this is a new record family. The existing estimand and
identities stay as they are.

## 4. Seed and uncertainty plan (predeclared)

- Units of inference are seeds (ten at 12 m, eight at 2 m); magnitudes are
  paired within a seed. Primary statistics are per-seed quantities with
  Student-t intervals (9 and 7 degrees of freedom): per-seed log–log slopes,
  per-seed ratio changes between adjacent magnitudes and between the ends.
- Within-run errors: block means with block lengths 1, 5, 25, 75 from ΔV_t;
  the run's error is taken at the plateau, and the integrated
  autocorrelation time of ΔV_t is reported per run. If no plateau is
  reached by 75 frames for any run, the run's within-run error is reported
  as a lower bound.
- The historical weighted estimator is recomputed on the new data with
  both error conventions, for continuity; it is not the primary endpoint.
- Robustness: medians per magnitude and leave-one-seed-out are reported;
  no run is excluded, but runs flagged by the excursion criterion (a
  25-frame block mean above three times the run median) are reported
  separately.
- Multiplicity: four adjacent comparisons per scale; the per-seed trend
  test (slope of the ratio against log N_e over all magnitudes) is the
  confirmatory statistic, the adjacent steps are descriptive.
- Replay check: the five recorded seeds must reproduce the recorded
  aggregates bit for bit where the code identity is the same up to the
  added observers (observers are passive by contract); any difference is a
  finding, not tuned away.

## 5. Success criteria (predeclared)

| Outcome | Criterion |
| --- | --- |
| H1 confirmed | the per-seed trend of ΔV / σ²_model(residual) against log N_e over m_AB 8–10.5 is consistent with zero at 2 SE and the end-to-end change is within ±3 %, while ΔV / σ²_model(flat) keeps its decline (−6 % or more from m_AB 8 to 10); and the floor-share fit against the residual-evaluated model gives β/α within 1 SE of that model's b/a |
| H1 insufficient | the residual-evaluated ratio still declines by more than 5 % from m_AB 8 to 10.5 at 2 SE |
| H2 confirmed | at m_AB 11 the excess ΔV of any excursion run lies in frames where the arms' masks differ (more than half of the excess variance in fewer than a fifth of the frames), and arm B removes it: ΔV(mask-locked) within 10 % of the median of the non-excursion runs and a cross term consistent with zero |
| H2 refuted | mask disagreement is spread evenly or absent in excursion frames, and arm B leaves the excess |
| H4 confirmed | C0 shows a non-zero saturation fraction in the noisy arm that grows from m_AB 5 to 7, and C1 restores the exponent to the residual-evaluated model's within 2 SE |
| H5 confirmed | C2 restores the exponent and C1 does not |
| Statistics only (H6/H7) | with ten seeds the 12 m dip and the 2 m drift fall below 2 SE and the blocking plateau shows errors within 20 % of the recorded ones |
| Unexplained remains | any residual departure after the above is recorded with its size and the arms it survived, and added to LIM-18, not reinterpreted |

The predeclared pure-photon criterion is not re-tested; it remains the
recorded negative result.

## 6. Cost estimates and their basis

| Arm | Runs | Per-run basis | Estimate | Peak memory basis | Estimate | Label |
| --- | --- | --- | --- | --- | --- | --- |
| A | 5 magnitudes × 10 seeds = 50 paired runs of 400 frames | recorded 2638 s for 20 paired runs (132 s each, two arms, 0.16 s per frame per arm; technical reference 9.3) plus one model evaluation per frame on one arm, bounded above by the cost of a full noisy frame (0.16 s per frame, E3/E6 on `@3`; the evaluation is one noiseless spot computation plus the covariance quadratic forms), i.e. at most 180 s per run | at most 2.5 h serial | recorded 1.11 GiB for the paired 12 m run (two built systems plus 300 float32 residual maps per arm; technical reference 9.3/9.4); per-frame per-lenslet model vectors add 416 × 300 × 8 B × 2 ≈ 2 MB; retained maps for two seeds per magnitude add 300 × 2 × 332 KB ≈ 0.2 GB on disk per run, not in memory beyond the recorder | about 1.2 GiB | ANALYTIC_ESTIMATE from MEASURED_HISTORICAL |
| B | 10 paired runs at m_AB 11 | as A, plus the twin run first (sequential, same cost) | about 30 min | as A | about 1.2 GiB | ANALYTIC_ESTIMATE |
| C0, C1, C2 | 3 arms × 3 magnitudes × 8 seeds = 72 paired runs of 200 frames | recorded 290 s for 32 runs (9 s each, 134 MiB peak) plus the per-frame model evaluation, bounded by the 2 m physical EMCCD measurement cost (6.8 ms per frame, `det10_feature_costs.json`) | about 15 min | recorded 134 MiB | under 0.2 GiB | ANALYTIC_ESTIMATE from MEASURED_HISTORICAL |

All runs serial with two native threads under the recorded policy. The
12 m arms are governed (medium/12 m); their enablement note must name the
date and wording of the go-ahead, as the runner requires. The 2 m arms are
ungated by the recorded policy. The estimates are categories C2 (A, B) and
C1 (C) in the roadmap's terms; the shared-machine factor seen in S1 (about
3 %) applies.

## 7. What this experiment does not do

It does not change the noise model, the profiles or the recorded evidence;
it does not test the pure-photon criterion again; it does not establish
instrument accuracy; and it does not cover the 42 m profile, polychromatic
or integration effects, or the CMOS and CCD presets. If H1 is confirmed, a
follow-up could add a residual-evaluated model column to the detector-level
evidence runner as a new, versioned record family.
