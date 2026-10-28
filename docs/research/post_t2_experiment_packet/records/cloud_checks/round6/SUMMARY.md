# Round-6 reruns: the carried state measured, the conditional prediction, the calibrated bracket (2026-10-22)

Review round 6 (on `36c82cf`) resolved POST-T2-20 and left two findings:
a synthetic 25 % carried-state effect received only a 2.08 % budget, and
the selected state space and the covariance-difference inequality behind
that bound were not justified (12); and the empirical maximum over
observed lenslets does not bound an unobserved lenslet's covariance (21).
This directory holds the reruns of `tools/linear_loop_noise_model.py`
(schema `post_t2_linear_loop_noise_model.v7`) on the round-2 pilot
sidecars, three new traced ci pilots with retained residual maps, the 32
series sidecars of the 2 m replay, three fixtures, two logged replays, the
negative checks and the field audit. Nothing governed ran; no runtime
code, profile, baseline or historical record changed.

## What the tool now computes (PROTOCOL.md 1.6, 1.6 (iv), 1.7, 7)

1. **The command-difference trajectory, rebuilt.** Both arms' centroids
   minus the sensor's zero-phase calibration reference (read from the
   system built with the run's seed), through each frame's operator probed
   on that frame's effective mask, through the controller law (leak, gain,
   delay queue of `d` zeros), from identical initial commands. The
   reference cancels between the arms only where both use the same
   operator, so it is subtracted. The per-frame pupil mean square of the
   rebuilt difference is compared with `delta_v_m2`; its relative rms `r`
   is the measured departure of the linear model with the probed
   operators from the run.
2. **The carried state, measured.** From the reconstruction when `r` is
   at most 1e-3; otherwise from the residual maps where the sidecar
   retains them (the state at the first analysed frame and the `d`
   increments released next, by least squares on the pupil response,
   streamed over 25-frame blocks); otherwise the run is not assessable.
   Propagated under the modal loop with no further noise, its window mean
   is the exact carried contribution `D`, and the prediction becomes
   `W_cold + D`.
3. **Budget and exclusion.** `u = |operator error| + r + f`, with `f` the
   unexplained share of the map difference when the maps supply the
   state. A run whose `u` reaches the closure band (`--closure-band`,
   0.10) is not assessable. The round-5 `gamma` bound is a diagnostic,
   now taken over every state.
4. **The bracket's sensor-model margin, calibrated.** Every lenslet with
   at least 10 usable analysed frames gives its realized variance over
   the largest sensor-model variance at its spot, with the 97.5 %
   chi-square upper bound of that ratio. A bracket resting on the model
   term needs the largest upper bound at or below the margin of two. A
   lenslet whose rows no operator used is skipped.

## Replays (`replay/`)

`replay_log.py` re-ran two traced ci pilots with every `reconstruct()`
input and output and every controller update logged; `replay_check.py`
compares the logs with the tool's ingredients.

| Run | Replay vs sidecar `delta_v` | Input minus (centroid minus reference) | Probed operator vs actual estimate (median, max) | Solver |
| --- | --- | --- | --- | --- |
| ci m9, 12 m damping 0.1 | 0.0 | 0.0 px in both arms (reference about 7 px) | 4.8e-7, 1.3e-6 | LSMR, `atol = btol = 1e-8` |
| ci m7, ci damping 0.001 | 0.0 | 0.0 px in both arms | 1.0e-2, 4.7e-2 | same |

## Pilot sidecars

| Run | Operators (noisy + twin-only) | Operator error | Reconstruction `r` | Carried source | Carried (model) | Measured / conditional (unconditional) | Budget `u` | Margin upper max | Classification |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2 m m5 seed 61 (round 2) | 2 + 0 | +0.02 % | 3.68 (clipping) | none | - | - (0.879) | - | 1.34 | not assessable |
| ci m7, 12 m damping (round 2) | 2 + 0 | 0.00 % | 1.6e-5 | telemetry | 1.2 % (1.6 %) | 0.991 (0.987) | 0.002 % | 0.91 | operator-consistent |
| ci m9, 12 m damping (round 2) | 5 + 0 | +0.03 % | 6.8e-6 | telemetry | 1.4 % (1.6 %) | 1.012 (1.010) | 0.026 % | 0.91 | operator-consistent |
| ci m7, ci damping (round 2) | 13 + 6 | +0.64 % | 2.8e-3 | none (no maps) | - | - (1.072) | - | 0.83 | not assessable |
| ci m9, ci damping (round 2) | 55 + 27 | not computed | - | none | - | - (1.349) | - | 0.81 | not assessable (82 operators exceed 64) |
| ci m7, 12 m damping, maps (round 6) | 2 + 0 | 0.00 % | 1.6e-5 | telemetry (maps agree to 2.0e-5) | 1.2 % (1.6 %) | 0.991 (0.987) | 0.002 % | 0.91 | operator-consistent |
| ci m9, 12 m damping, maps (round 6) | 5 + 0 | +0.03 % | 6.8e-6 | telemetry (maps agree to 9.4e-6) | 1.4 % (1.6 %) | 1.012 (1.010) | 0.026 % | 0.91 | operator-consistent |
| ci m7, ci damping, maps (round 6) | 13 + 6 | +0.64 % | 2.8e-3 | maps (fit residual 2.7e-13) | 2.0 % (1.7 %) | 1.072 (1.072) | 0.92 % | 0.83 | operator-consistent |

The round-6 pilots repeat the round-2 runs of the same configuration and
seed with `--retain-maps` (`run_pilots_maps.sh`: guard COMPLETED, wall
62.3-62.7 s, peak 237-238 MiB, sidecars 27.7-27.9 MB). The ci m9 run with
the 12 m damping has one frame on which the two arms used different
operators; with the reference subtracted it is reproduced exactly, while
the first round-6 draft, which let the reference cancel, missed the series
by 537 %. The fallback `gamma` bound over every state reads 36 % and 34 %
on the two runs with the 12 m damping and 96 % with the ci damping.

## 32 series sidecars (`--record`, runner `validate_trace_payload` passed on every one)

| Magnitude | Effective-rule ratio (t, 7 dof; unchanged) | Operator error | Clipped frames (of 200) | Reconstruction `r` | Map seed: budget | Margin upper max | Classification |
| --- | --- | --- | --- | --- | --- | --- | --- |
| m5 | 0.936 +/- 0.060 | 0.00-0.02 % | 56-192 | 0.23-3.68 | seed 61: 368 % | 1.19-1.36 | 8 not assessable |
| m6 | 0.892 +/- 0.076 | 0.00-0.01 % | 56-192 | 0.23-2.34 | seed 61: 234 % | 1.15-1.46 | 8 not assessable |
| m7 | 0.860 +/- 0.050 | 0.00-0.01 % | 56-192 | 0.25-2.49 | seed 61: 77 % | 1.12-1.47 | 8 not assessable |
| m8 (gate-active) | descriptive, 0.9-12 | 1.5, 2.5, 8.7, 11.3, 14.3, 21.6, 25.9 %; one not computed | 54-193 | 0.21-4.27 | seed 68: 209 % | 1.14-1.36 | 8 not assessable |

Per-run values: `ni2m_models/summary.json` (`rows`). The 2 m runs clip
actuators in at least a quarter of their frames, so the linear controller
law does not describe them and no carried state can be measured from the
telemetry. The four seeds with retained maps get their state from the maps
but carry budgets far above the band. Every run was already excluded by
the saturation rule.

## Fixtures (`fixtures/`)

- **Carried state** (`make_carried_fixture.py`, from the round-2 ci m7
  sidecar with the 12 m damping): a 0.090 px kick at burn-in frames 95-99
  along the measurement signature of the slowest sensed mode (eigenvalue
  0.120 of `R M`), propagated through the noisy arm's operators and the
  controller law into its later centroids, expected centroids and the
  series. It adds 25.0 % to the window mean (+303 % in the first block).
  The tool rebuilds it to 1.3e-5 and measures a 26.7 % carried
  contribution against the model's 1.6 %. The ratio is 0.986 against the
  conditional prediction and 1.234 against the unconditional one, and the
  budget is 1.3e-5. The diagnostic `gamma` bound reads 501 %.
- **Series scaled by 1.25** (the round-6 ci m7 pilot with maps, the
  series and the mean-square difference changed, the cross term kept):
  the reconstruction misses the series by 21 %, the maps supply the
  state, the ratio is 1.238 and the budget 21.2 %, so the run is not
  assessable.
- **Covariance bracket** (the round-5 fixture): two rows bracketed from
  their own five frames (chi-square factor 8.26), bracket width 0.76 %, no
  upper end resting on the model term. Its edited masks are not the loop's
  own, so the reconstruction misses the series by 3.3e4 and the fixture
  is not assessable: an edited sidecar is caught.

## Margin calibration on the genuine records

Over the 40 genuine records (5 round-2 pilots, 3 round-6 pilots, 32
series runs): median realized-to-model variance ratios 0.50-0.77, largest
ratios 0.69-1.16, largest 97.5 % upper bounds 0.81-1.47, and at most 1.41
for the faintest quarter of the spots. The margin of two is supported on
every record. No genuine run had a row to bracket.

## Negative checks and field audit

The three corrupted copies of the 2 m pilot sidecar (units `nm2`,
permuted centroid axes, `saturation_fraction` as float32) are refused with
no record written. All 57 acceptance field paths of `pilot_requests.json`
resolve in the matching tool records; P2b's sample is the v7 record of
the ci m9 pilot with the 12 m damping and retained maps.

## Memory

Retained-array inventories of 1-16 MiB on the 2 m and round-2 ci sidecars
and 53-55 MiB on the ci sidecars with maps, against peaks of 124-154 MiB
and 189-195 MiB. Streaming the map fit
over 25-frame blocks removed the full float64 difference and fitted stacks
and the dense QR factor: the first round-6 draft peaked at 268-274 MiB on
the same sidecars, and at 12 m those arrays would have added about 500
MiB to P2b.

## Files

- `run_models.sh`, `run_models.log`, `run_pilots_maps.sh`, `run_pilots_maps.log` (JSON stdout lines stripped).
- `model_self_test.json`; `{ni2m_m5s61,ci_m7_default,ci_m7_alpha0p1,ci_m9_default,ci_m9_alpha0p1}/model_sidecar.json`; `pilots_maps/<run>/{pilot,guard,model_sidecar}.json`.
- `ni2m_models/<label>__seed<seed>.json` (32) and `summary.json`; `make_summary.py`, `summary.out`.
- `fixtures/`: the fixture builders, the model records and their stdout (the fixture archives stay outside the repository).
- `replay/`: `replay_log.py`, `replay_check.py`, `replay_check.json` and the stdout files (the call logs, 2.8 MB each, stay outside the repository).
- `negative/*.stdout`; `audit_fields.py`, `audit_fields.out`.

The scripts import the packet's tools through `PYTHONPATH=<repo>/src:<repo>/docs/research/post_t2_experiment_packet/tools`.
Scratch paths inside the records are the session's scratch directory.
