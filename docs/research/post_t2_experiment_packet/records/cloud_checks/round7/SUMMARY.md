# Round-7 reruns: the operator error on the conditional prediction, exact extremes over the admissible covariance (2026-10-22)

Review round 7 (on `f06cfa0`) kept POST-T2-20 resolved and left two
findings: the measured carried state was propagated under the modal
operator only, so a synthetic control with later operator changes received
almost no budget despite a 466 % overprediction (12); and the two bracket
ends of the round-6 operator error missed an admissible covariance with a
much larger error (21). This directory holds the reruns of
`tools/linear_loop_noise_model.py` (schema `post_t2_linear_loop_noise_model.v8`)
on the round-2 pilot sidecars, the round-6 pilot sidecars with retained
maps, the 32 series sidecars of the 2 m replay, three new linear
re-synthesis fixtures (each also run with the round-6 tool, `git show
f06cfa0:docs/research/post_t2_experiment_packet/tools/linear_loop_noise_model.py`),
the round-6 and round-5 fixtures, the negative checks and the field audit.
Nothing governed ran; no runtime code, profile, baseline or historical
record changed.

## What the tool now computes (PROTOCOL.md 1.6 (1), 1.6 (iv) (c), 7)

1. **The operator error on the conditional prediction.** The conditional
   prediction of round 6 (the measured carried state plus the cold-start
   noise part) is recomputed with the noisy arm's actual operator of every
   frame from the first new increment on, and compared with the same
   prediction under the modal operator. The carried state is propagated
   without noise through `L_k = R_k^noisy M`, with the deterministic forcing
   `(R_k^noisy - R_k^twin)(m_k^twin - m_ref)` of every frame on which the
   arms' operators differ. The noise part is propagated with the same
   operators.
2. **The noise part as a linear functional.** One adjoint pass of the
   companion dynamics gives the cold noise part as `tr(A Sigma)`, `A =
   g^2 sum_op R_op^T S_op R_op`; a forward propagation at the worse
   covariance checks it on every run.
3. **The admissible covariance and its exact extremes.** Every lenslet
   outside the modal mask whose rows some operator used gets a variance
   interval per axis (at least 10 usable frames: the two-sided 95 %
   chi-square interval of its own variance; fewer: zero to the larger of
   its 97.5 % chi-square bound and twice the sensor model's variance at its
   spot, the margin calibrated on the run) and every positive-semidefinite
   completion of its 2 x 2 block. Per lenslet the contribution is a 2 x 2
   quadratic form over a box in `(sqrt(s_x), sqrt(s_y))`, whose extremes
   are found exactly; the extremes add over lenslets. The extreme of larger
   magnitude is the operator error; an extreme range above 2 % leaves it
   undetermined.
4. The unconditional transient of rounds 4 to 6 is kept as a diagnostic
   (`prediction.operator_bounds.time_varying`). `--admissible-samples N`
   evaluates the operator error by forward propagation at N random
   admissible covariances and counts those outside the exact extremes.

## Self-test (`model_self_test.json`, `operator_error_on_the_conditional_prediction`)

| Check | Result |
| --- | --- |
| Adjoint functional against forward propagation (random system, two operators) | 2.7e-16 relative |
| 2 x 2 box extremes against a 301 x 301 grid (200 random forms and boxes) | at most 1.8e-15 beyond |
| Random admissible covariances outside the exact extremes of an indefinite functional | 0 of 4000 |
| That functional's exact extremes against its variance corners | -3.58 to -0.93 against -2.56 to -1.67 |
| Constant operator sequence against the modal cold start | 2.8e-16 |
| Carried mode unsensed by the modal operator, sensed by the actual ones for 30 frames | window ratio actual over modal 0.034 |

## Fixtures (`fixtures/`)

`make_linear_fixture.py` re-synthesizes the round-2 ci m7 sidecar with the
12 m damping under the linear model: it extracts the run's noise sequence
(it matches the recorded centroid residuals at correlation 0.999), edits
the masks, adds an optional burn-in kick, and re-simulates the command
difference through the controller law with every frame's probed operators.

| Fixture | Round-6 tool | v8 tool |
| --- | --- | --- |
| Operator change: three edge lenslets dropped by both arms from analysed frame 60 on; a 0.70 px kick at frames 95-99 along the actuator the reduced (modal) operator does not sense; the run's noise | operator-consistent, error -0.82 %, budget 0.82 %; measured over conditional prediction 0.050 | operator error -94.8 % (extremes -94.8 % to -94.7 %), not assessable; carried contribution 95.9 % under the modal operator, 1.1 % under the actual ones; measured over the actual-operator prediction 0.943-0.962 |
| The same, noise scaled by 1e-4, plus one lenslet dropped by the noisy arm only at five analysed frames | operator-consistent, budget 0.79 % | operator error -98.6 %; arm-operator forcing on 5 frames; measured over the actual-operator prediction 1 - 2.1e-5 |
| Sparse lenslets: two lenslets usable in five analysed frames only (both arms) | error +0.24 % at its bracket ends (-0.12 %, +0.24 %) | exact extremes -0.12 % and +0.10 %; 200 forward-propagated admissible covariances all inside (sampled -0.090 % to +0.064 %) |

All three fixtures are rebuilt from the telemetry to 2e-14 to 4e-14
relative rms. The round-6 carried-state fixture gives operator error
0.00 % and the same ratio 0.986 as in round 6; the scaled-series fixture
is not assessable by budget (21 %); the round-5 bracket fixture is not
assessable (its edited masks are not the loop's own, reconstruction 3.3e4).

## Pilot sidecars

| Run | Operator error | Carried contribution modal / actual | Arm-disagreement frames | Budget `u` | Measured / conditional (actual-operator) | Classification |
| --- | --- | --- | --- | --- | --- | --- |
| ci m7, 12 m damping (round 2 and round 6 with maps) | 0.00 % | 1.2 % / 1.2 % | 0 | 0.002 % | 0.991 (0.991) | operator-consistent |
| ci m9, 12 m damping (round 2 and round 6 with maps) | +0.39 % | 1.4 % / 1.8 % | 1 | 0.39 % | 1.012 (1.008) | operator-consistent |
| ci m7, ci damping, maps (round 6) | +18.6 % | 2.0 % / 19.9 % | 15 | 18.8 % | 1.072 (0.904) | not assessable (mask-variable, budget above the band) |
| ci m7, ci damping (round 2, no maps) | - | - | 16 | - | - | not assessable (reconstruction 2.8e-3) |
| ci m9, ci damping (round 2) | - | - | 87 | - | - | not assessable (82 operators exceed 64) |
| 2 m m5 seed 61 (round 2) | - | - | 0 | - | - | not assessable (reconstruction 368 %) |

The adjoint matches forward propagation to 2.7e-16 to 6.0e-16 on every
computed pilot run (1.3e-16 to 1.0e-15 on the fixtures). The ci m7 run with the ci damping is gate-quiet by the 0.1 %
rule (0.07 % of row-frames), yet its 15 frames with differing operators,
acting on the whole residual signal through the almost unsensed mode, add
18 % to the window: the operator error now carries what the gate rule
leaves.

## 32 series sidecars (`--record`)

All 32 validated and all 32 not assessable, as in round 6 (clipping in
54-193 of 200 frames). On the four seeds with retained maps the operator
error is below 0.02 % at m5-m7 and +1320 % at m8 (29 operators). Per-run
values: `ni2m_models/summary.json`.

## Negative checks and field audit

The three corrupted copies of the 2 m pilot sidecar are refused with no
record written. The audit (`audit_fields.py`) now also resolves the
shorthand paths that start with a dot against the preceding path, walking
up its parents, and keys that contain a dot: 66 absolute and 28 relative
paths resolve, none missing; two planted wrong paths are flagged.

## Memory

Peaks of 126-154 MiB without maps and 190-195 MiB with maps on the ci
geometry. P2b's estimate now counts the probed responses, the injection
blocks and the adjoint sums per operator (614 MiB at the 64-operator cap
at 12 m) and stays at `--estimate-mib 2000`.

## Files

- `run_models.sh`, `run_models.log` (JSON stdout lines stripped); `model_self_test.json`.
- `{ni2m_m5s61,ci_m7_default,ci_m7_alpha0p1,ci_m9_default,ci_m9_alpha0p1}/model_sidecar.json`; `pilots_maps/<run>/model_sidecar.json`.
- `ni2m_models/<label>__seed<seed>.json` (32) and `summary.json`; `make_summary.py`, `summary.out`.
- `fixtures/`: `make_linear_fixture.py`, `make_carried_fixture.py`, `make_bracket_fixture.py`, the fixture summaries, the v8 and round-6 model records and their stdout (the fixture archives stay outside the repository).
- `negative/*.stdout`; `audit_fields.py`, `audit_fields.out`.

The scripts import the packet's tools through `PYTHONPATH=<repo>/src:<repo>/docs/research/post_t2_experiment_packet/tools`.
