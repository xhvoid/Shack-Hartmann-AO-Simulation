# Round-5 reruns: the measured carried-state bound, the covariance bracket, the memory inventory (2026-10-22)

Review round 5 (on `c6642b7`) resolved POST-T2-19 and left three findings:
the round-4 restart values bounded only the sensitivity of the modelled
state, not an unknown carried state (12); P2b's known retained arrays
exceeded its memory estimate (20); rows outside the modal operator without
a covariance estimate were treated as zero (21). This directory holds the
reruns of `tools/linear_loop_noise_model.py` (schema
`post_t2_linear_loop_noise_model.v5`) on the unchanged round-2 pilot
sidecars and the 32 series sidecars of the 2 m replay, a covariance-bracket
fixture, the negative checks and the field audit. Nothing governed ran; no
runtime code, profile, baseline or historical record changed.

## What the tool now computes (PROTOCOL.md 1.6, 1.6 (iv), 1.7, 7)

1. **Operator error, bracketed.** As in round 4 (the transient with the
   actual operator of every frame, burn-in included), with one change: a
   row outside the modal mask whose lenslet has fewer than 10 usable
   analysed frames gets no covariance of its own; its covariance is
   bracketed between zero and the largest realized per-axis variance of
   the estimated lenslets, the transient is propagated at both ends, the
   operator error is the worse of the two, and a bracket wider than the
   2 % tolerance makes the run not assessable.
2. **Carried-state bound, measured.** The window mean is affine in the
   loop's state at the first analysed frame, so a deviation of that state
   from the modelled one changes the window mean by at most `gamma` times
   its change of the first 25-frame block mean, with `gamma` the largest
   generalized eigenvalue of the window-mean and first-block-mean
   quadratic forms of the companion dynamics (leading-block-row
   recurrence; verified against explicit powers of `F` and a direct
   simulation of the maximizing state). The first-block change is
   measured: the first analysed block's `delta_v_m2` mean minus the
   model's own per-frame transient, with the run's block scatter as its
   uncertainty. Bound = `gamma_used (|excess_1| + 2 s_block) / primary`.
   `gamma_used` runs over the sensed states when the operator injects
   nothing into its unsensed modes (feedback below 1e-6; the injection
   `|w^T R| / (|w| |R|)` over the left null vectors `w` of `L` is checked,
   1e-3 at most), and over every state otherwise. The all-state bound and
   the round-4 restart values are reported as sensitivities.
3. **Systematic budget.** `u = |operator error| + carried-state bound`
   per run; PROTOCOL.md 1.7 subtracts the admissible seeds' mean `u_bar`
   from the agreement band and adds it to the departure band. The
   classification (operator-consistent, mask-variable, not assessable)
   depends on the operator error alone.
4. **Memory.** Injection matrices are kept as `c x c` blocks, the dense
   pupil response is freed once the Gram matrix is formed, and the record
   carries an inventory of the retained arrays in bytes beside the process
   peak.

Self-test additions (`model_self_test.json`): the leading-block-row
recurrence equals explicit powers of `F` to 1e-15; `gamma` over the sensed
states of a two-mode loop (one unit-feedback mode, one unsensed) equals a
direct simulation of its maximizing state to 1e-15 (0.0833 for a 300-frame
window and a 25-frame block); the unsensed mode persists at ratio 1.000 and
receives zero injection from the matching reconstructor.

## Pilot sidecars (round-2 pilots, re-read with `--pilot-record`)

| Run | Operators (run) | Operator error (bracket width) | Unsensed modes, injection | `gamma` sensed / all / used | First-block excess, block scatter (blocks) | Carried-state bound (all-state) | Budget `u` | Classification | Measured / prediction | Retained / peak MiB |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2 m m5 seed 61 | 2 | +0.02 % (0) | 0, none | 0.167 / 0.167 / 0.167 | -18.9 %, 26.1 % (6) | 11.9 % (11.9 %) | 11.9 % | operator-consistent (excluded by saturation anyway) | 0.878 | 1.1 / 103 |
| ci m7, 12 m damping | 2 | 0.00 % (0) | 1, 1.9e-5 | 0.091 / 1.029 / 0.091 | -2.4 %, 10.1 % (12) | 2.1 % (23.4 %) | 2.1 % | operator-consistent | 0.987 | 13.4 / 128 |
| ci m9, 12 m damping | 5 | +0.03 % (0) | 1, 1.9e-5 | 0.091 / 1.029 / 0.091 | -2.8 %, 9.0 % (12) | 1.9 % (21.5 %) | 1.9 % | operator-consistent | 1.010 | 13.9 / 128 |
| ci m7, ci damping | 13 | +0.64 % (0) | 1, 2.3e-2 | 0.084 / 1.021 / 1.021 | -10.2 %, 43.1 % (12) | 98.5 % | 99.2 % | operator-consistent; budget consumes the band | 1.072 | 15.0 / 128 |
| ci m9, ci damping | 55 | +3.86 % (0) | 1, 2.3e-2 | 0.084 / 1.021 / 1.021 | +39.3 %, 50.0 % (12) | 142 % | 146 % | mask-variable; gate-active | 1.349 | 20.9 / 130 |

All five pass the canonical validation (61 arrays each; pilot-record
digest, size, frame counts, label, seed and hash). No pilot had a row to
bracket. The slowest sensed mode of the 12 m-damping operator (feedback
0.12 at gain 0.4) decays inside the first block, hence `gamma` 0.091; the
ci-damping operator's almost unsensed mode (feedback 4.6e-7) receives
2.3e-2 of the injection, so its `gamma` must run over every state and is
1.02: that loop cannot express a 10 % closure test over a 400-frame window,
whatever its mean ratio.

## 32 series sidecars (`--record`, runner `validate_trace_payload` passed on every one)

| Magnitude | Effective-rule ratio (t, 7 dof; unchanged) | Operator error | Classification | `gamma` | First-block excess | Block scatter (6 blocks) | Carried-state bound | Budget `u` (mean over operator-consistent) | Saturation after burn-in |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| m5 | 0.936 +/- 0.060 | 0.00-0.02 % | 8 operator-consistent | 0.167 | -20 % to +44 % | 6-28 % | 2.3-16.7 % | 2.3-16.7 % (8.5 %) | 1.5-15 %: all 8 excluded by rule (a) |
| m6 | 0.892 +/- 0.076 | 0.00-0.01 % | 8 operator-consistent | 0.167 | -33 % to +33 % | 6-33 % | 5.4-16.6 % | 5.4-16.6 % (9.5 %) | all 8 excluded by rule (a) |
| m7 | 0.860 +/- 0.050 | 0.00-0.01 % | 8 operator-consistent | 0.167 | -37 % to +7 % | 8-29 % | 4.3-11.3 % | 4.3-11.3 % (6.9 %) | all 8 excluded by rule (a) |
| m8 (gate-active) | 2.55 +/- 3.16 (descriptive) | 1.7, 2.7, 8.7, 11.5, 14.6, 26.0, 32.0 %; one not computed | 6 mask-variable, 1 not assessable (seed 65: an operator the reconstructor refuses), 1 operator-consistent (seed 62, gate-active) | 0.167 | -31 % to +53 % | 15 % to 2518 % | 6.9 % to 839 % | 15.5 % to 865 % (18.8 %) | 2-15 %: all 8 excluded by rule (a) |

Per-run values: `ni2m_models/summary.json` (`rows`). The 2 m series'
150-frame window (six 25-frame blocks) and heavy-tailed `DeltaV_t` give
first-block excesses of tens of per cent, so even at `gamma` 0.167 the
mean budgets of 7-10 % would leave the 10 % band an agreement width of
0.5-3 %: the 2 m closure test is "not expressible" by budget, beside the
saturation rule that excludes every gate-quiet 2 m run. No genuine run had
a row to bracket: every row outside a modal mask had at least 10 usable
frames (then its own estimate) or none at all.

## Covariance-bracket fixture (`bracket_fixture/`)

`make_fixture.py` drops lenslet 3 of the round-2 2 m pilot sidecar from the
noisy arm's effective mask and sensor validity in every frame but five
analysed frames. The tool then finds the modal operator on 40 of 42 rows,
three distinct operators over the run, two rows outside the modal mask with
five usable frames, and brackets them: envelope 0.0030 px² from the 20
estimated lenslets; operator error -0.38 % at the zero end and -0.12 % at
the envelope end; bracket width 0.26 % (below the tolerance, so the error
is determined and the run operator-consistent). A fixture, not a run: the
structural validation accepts it because the declared table, shapes and
hash are the pilot's; no digest check against a record was requested.

## Negative checks (`negative/`)

The same three corrupted copies of the 2 m pilot sidecar as in rounds 3
and 4 are refused before any array is read as data; no record is written.

## Acceptance field audit (`audit_fields.py`, `audit_fields.out`)

Every dotted field path named in the acceptance rules of
`pilot_requests.json` resolves in the matching tool record: 48 paths, none
missing (P2b's sample is the round-5 ci m9 record with the 12 m damping,
schema v5).

## Memory

Retained-array inventories of 1.1-20.9 MiB (the freed dense pupil response
0.2-7.5 MiB) against process peaks of 103-130 MiB on the 2 m and ci
geometries: the uninventoried baseline (interpreter, libraries, the system
build) is about 100 MiB here. P2b's estimate is rebuilt from the same
inventory formulas at the 12 m dimensions (`pilot_requests.json` P2b:
retained 290-596 MiB, transient 229 MiB, build allowance 500 MiB, baseline
120 MiB; `--estimate-mib 1600`, authorized budget 3200 MiB).

## Files

- `run_models.sh`, `run_models.log`: the batch and its log (JSON stdout lines stripped).
- `model_self_test.json`; `{ni2m_m5s61,ci_m7_default,ci_m7_alpha0p1,ci_m9_default,ci_m9_alpha0p1}/model_sidecar.json` and `model_flat.json`.
- `ni2m_models/<label>__seed<seed>.json` (32) and `ni2m_models/summary.json`; `make_summary.py`, `summary.out`.
- `bracket_fixture/make_fixture.py`, `model.json`, `model.stdout` (the fixture archive itself stays outside the repository).
- `negative/*.stdout`; `audit_fields.py`, `audit_fields.out`.
