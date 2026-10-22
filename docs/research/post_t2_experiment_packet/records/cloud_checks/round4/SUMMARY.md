# Round-4 reruns: the operator error bounds (2026-10-22)

Review round 4 (on `acfc8b0`) left two findings: the operator-match
threshold of round 3 (95 % of the analysed frames under the modal operator
in both arms) had no error bound and missed the state the loop carries
into the analysed window from the burn-in; and the protocol still held
conflicting exclusion lists and primary rules. This directory holds the
reruns of `tools/linear_loop_noise_model.py` (schema
`post_t2_linear_loop_noise_model.v4`) on the unchanged round-2 pilot
sidecars and the 32 series sidecars of the 2 m replay, with the two
bounds that replace the threshold. Nothing governed ran; no runtime code,
profile, baseline or historical record changed; the sidecars are the
round-2 and session files, re-read and re-validated.

## What the tool now computes (PROTOCOL.md 1.6, 1.6 (iv), 7)

1. **Operator error.** The transient is propagated a second time with the
   noisy arm's actual effective row mask of every frame of the run,
   burn-in included: each distinct mask is probed once on the
   reconstructor, the increment released at update `k` carries the loop
   and the injection of the operator of frame `k - d`, and `Sigma` is
   restricted to each operator's rows (the modal rows keep the effective
   rule's blocks; a row outside them takes its lenslet's own usable
   frames). The relative difference from the modal-operator prediction is
   the error, split into the part carried in from burn-in (actual
   operators before the window, the modal one inside it) and the part
   from operator changes inside the window.
2. **Carried-state bound.** The window value is affine in the loop's
   state at any frame. A burn-in frame with gate activity (a row on which
   the two arms' masks differ, a rejected reconstruction, a recovery
   action) or with command saturation above 1e-3 in either arm is one the
   linear model does not carry. The modal-operator window is restarted
   from a zero state (identical commands, an empty queue) right after the
   last such frame, and the fraction of the primary value this removes is
   the largest relative error a wrong carried state can cause per unit of
   its own relative error. The inherited fraction from the first analysed
   frame and the window value under a stationary carried state are
   reported as sensitivities.
3. **Rule.** Operator-consistent when the operator error is within 2 %
   and, if the burn-in had such a frame, the carried-state bound is
   within 2 %; otherwise mask-variable (operator error),
   carried-state-sensitive (bound), or not assessable (more distinct
   operators than `--max-distinct-masks`, or an operator the
   reconstructor refuses). The match fractions over the analysed and the
   burn-in frames are diagnostics.

Self-test additions (`model_self_test.json`): a constant operator sequence
reproduces the modal transient to 0.0; a sequence whose burn-in operator
is silent (no feedback, no injection) reproduces the cold start at the
window to 0.0; a window started from the stationary state stays
stationary to 4e-16; the cold start lies below the modal value (0.952 in
the 2 x 2 example).

## Pilot sidecars (round-2 pilots, re-read with `--pilot-record`)

| Run | Operators over the run (analysed) | Modal-operator match noisy / twin / burn-in | Operator error (burn-in part) | Last unmodelled burn-in frame | Carried-state bound | Classification | Measured / effective prediction (/ time-varying) | Probe time |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2 m m5 seed 61 | 2 (2) | 0.993 / 0.993 / 1.00 | +0.02 % (0) | 49 (41 of 50 frames clipped) | 2.44 % | carried-state-sensitive; excluded by saturation anyway (15 % of the actuators clipped after burn-in) | 0.878 (0.878), within 2 block SE | 0.01 s |
| ci m7, ci damping 0.001 | 13 (12) | 0.937 / 0.927 / 0.98 | +0.64 % (-3e-8) | 35 (one disagreeing row) | 1.4e-5 | operator-consistent (round 3's threshold had excluded it) | 1.072 (1.065), within 2 block SE | 10.5 s |
| ci m7, 12 m damping 0.1 | 2 (1) | 1.000 / 1.000 / 0.99 | 0.00 % (0) | none (quiet) | none needed; inherited from the first analysed frame 1.58 % | operator-consistent | 0.987 (0.987) | 0.7 s |
| ci m9, ci damping 0.001 | 55 (46) | 0.743 / 0.730 / 0.73 | +3.86 % (+0.01 %) | 84 (16 disagreeing frames) | 0.04 % | mask-variable; gate-active | 1.349 (1.299), outside 2 block SE | 50.6 s |
| ci m9, 12 m damping 0.1 | 5 (4) | 0.980 / 0.983 / 0.97 | +0.03 % (0) | none (quiet) | none needed; inherited 1.58 % | operator-consistent | 1.010 (1.010) | 2.8 s |

All five sidecars pass the canonical validation (61 arrays each; pilot
record digest, size, frame counts, label, seed and hash). The window value
under a stationary carried state is 2.02-2.05 times the primary for the ci
damping (one almost unsensed mode, feedback 4.6e-7, accumulates noise
through the run) and 1.0002 for the 12 m damping; no rule attaches to it.

## 32 series sidecars (`--record`, runner `validate_trace_payload` passed on every one)

| Magnitude | Effective-rule ratio (t, 7 dof; unchanged from round 3) | Operator error | Distinct operators over a run | Last unmodelled burn-in frame | Carried-state bound | Classification | Saturation after burn-in |
| --- | --- | --- | --- | --- | --- | --- | --- |
| m5 | 0.936 +/- 0.060 | 0.00-0.02 % | 1-2 | 18, 34, 37, 49 (four runs), none (one run) | 7.6e-11 to 1.8e-5 on four runs, none on one, 2.44 % on four | 4 operator-consistent, 4 carried-state-sensitive | 1.5-15 % of the actuators on every run: all 8 excluded by rule (a) |
| m6 | 0.892 +/- 0.076 | 0.00-0.01 % | 1-2 | same frames (same seeds) | same | 4 / 4 | all 8 excluded by rule (a) |
| m7 | 0.860 +/- 0.050 | 0.00-0.01 % | 1-2 | same | same | 4 / 4 | all 8 excluded by rule (a) |
| m8 (gate-active) | 2.55 +/- 3.16 (descriptive; per seed 1.16, 1.23, 1.00, 0.90, 1.80, 1.53, 0.91, 11.9) | 1.7, 2.7, 8.7, 11.5, 14.6, 26.0, 32.0 %; one not computed | 9-40 | 41, 47, 49 (six runs) | 8.5e-5, 1.1 %, 2.44 % (six runs) | 1 operator-consistent (seed 62, gate-active), 6 mask-variable, 1 not assessable (seed 65: an operator the reconstructor refuses) | 2-15 %: all 8 excluded by rule (a) |

Per-run values: `ni2m_models/summary.json` (`rows`). The burn-in part of
the operator error at m8 is up to 10.4 % (seed 66: the state carried into
the window under the burn-in's operators), 0.1-0.3 % on four other runs
and below 1e-5 on the rest; at m5-m7 it is 0. The 2 m burn-ins clip
actuators during loop closure (9-46 of 50 frames above 1e-3, except seed
68 with none), which is why half of the gate-quiet runs are
carried-state-sensitive at 2.44 %, the share of a 150-frame window
inherited from before it; the 400/100-frame S4 A1 window inherits 1.6 % on
the ci geometry with the 12 m damping.

## Negative checks (`negative/`)

The same three corrupted copies of the 2 m pilot sidecar as in round 3
(units `nm2` on `delta_v_m2`; permuted centroid axes; `saturation_fraction`
as float32) are refused before any array is read as data; no record is
written (`records_written: 0`).

## Acceptance field audit (`audit_fields.py`, `audit_fields.out`)

Every dotted field path named in the acceptance rules of
`pilot_requests.json` resolves in the matching tool record: 50 paths, none
missing (P2b's sample is the round-4 ci m9 record with the 12 m damping,
schema v4; the other samples are the round-1 to round-3 pilot records).

## Files

- `run_models.sh`, `run_models.log`: the batch and its log (the JSON lines
  of the tool's stdout are stripped from the copied log).
- `model_self_test.json`; `{ni2m_m5s61,ci_m7_default,ci_m7_alpha0p1,ci_m9_default,ci_m9_alpha0p1}/model_sidecar.json` and `model_flat.json`.
- `ni2m_models/<label>__seed<seed>.json` (32) and `ni2m_models/summary.json`; `make_summary.py`, `summary.out`.
- `negative/*.stdout`; `audit_fields.py`, `audit_fields.out`.

Scratch paths inside the records are the session's scratch directory; the
sidecars themselves are not copied (round-2 `pilot.json` and `trace.npz`
files and the session's 2 m replay, unchanged since round 2).
