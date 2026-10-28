# Review round 2: reruns with the corrected tools (2026-10-22)

Producer: commit `578f697` (the round-2 tool repairs; the imported package
digest is unchanged since `5514285`), the `constraints/hcipy-py311.txt`
environment (Python 3.11.17, NumPy 2.4.6, SciPy 1.17.1, x86_64), serial, two
native threads, every traced pilot under `shwfs_ao.runtime.resource_guard`
with the policy budget. Nothing here is a governed run, a 12 m or 42 m
system build, or a scientific result; labels `EXECUTED_CURRENT` and
`MEASURED_CURRENT`. Chronology: `run_validations.log`. The model outputs of
`ci_m7_default/model_sidecar.json`, `ni2m_m5s61/model_*.json`,
`ci_m9_default/model_sidecar.json` and the eight `ni2m_models/m8__*.json`
were regenerated after two small tool corrections made during the chain (a
masked-out mode with a unit pole is reported instead of refused; a support
mask the reconstructor refuses makes that rule "not defined" instead of
failing the record). Trace archives stay outside the repository; their
digests are in `pilot_sidecars.sha256`.

## CHK-2a: model self-test (`model_self_test.json`)

Passed: the Lyapunov variance equals `kappa` to 1e-15 for five `(g, l, d)`
cases; decoupled modes keep their own variances; the structured
`F P F^T` equals the dense product to 3e-17; the 400-frame window mean of a
unit-feedback loop equals `kappa` to 7e-15; **delayed injection**: for
`d = 0, 1, 2` the first `d` post-update covariances are exactly zero and
the next equals `g^2 R Sigma R^T` (0.09 at `g = 0.3`).

## CHK-2b: traced pilots with the core-consistent telemetry

| run | wall (s) | `ru_maxrss` / group peak (MiB) | gate-quiet (core rule) | rejected frames after burn-in, both arms | `recovery_acted` | `DeltaV` (nm^2, 25-frame block SE) | other |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2 m m5 seed 61 (200/50) | 37.0 | 103 / 92 | yes | 0, 0 | false, false | 4.17 +/- 0.51 | seven quantities within 8.3e-10 of the committed desktop record; E0 1.027; clipping up to 31 % of the actuators in a frame |
| ci m7, ci damping | 121.1 | 238 / 234 | yes (15 flicker frames, 0.079 %) | 0, 0 | false, false | 223.4 +/- 26.0 | E0 0.993 |
| ci m7, 12 m damping (diagnostic) | 121.3 | 238 / 219 | yes (0 frames) | 0, 0 | false, false | 92.9 +/- 2.8 | E0 1.008 |
| ci m9, ci damping | 127.4 | 238 / 222 | **no** (71 frames, 0.583 %) | 0, 0 | false, false | 1771.8 +/- 189.7 | E0 0.992 |
| ci m9, 12 m damping (diagnostic) | 120.6 | 238 / 187 | yes (1 frame) | 0, 0 | false, false | 614.6 +/- 15.9 | E0 1.006 |

`arm_telemetry` repeats the core's `trace_summary.arms` fields; the tool's
recount from the trace arrays equalled the core's count on every arm of
every run (it refuses the record otherwise). `recovery` is `null` for these
profiles because they carry no recovery policy; the 12 m profile does, so
P2 reads `recovery_acted`, not `recovery`.

## CHK-2c: the model on the 32 series sidecars with `--record`

Every sidecar was accepted by the full validation (declared array table,
frame domains, two-arm layout and canonical rows, label, seed,
configuration hash, the record row's digest and size, the evidence runner's
`validate_trace_payload`). Full-mask `max |L - I|` 1.0e-14 (TSVD), spectral
radius 0.7226, Lyapunov residual at most 3.4e-14. Measured `DeltaV` over the
prediction, by support rule (the reconstructor probed on that rule's rows):

| m_AB | runs | available rule (t, 7 dof) | strict rule (t, 7 dof) | strict / available support | gate-quiet | notes |
| --- | --- | --- | --- | --- | --- | --- |
| 5 | 8 | 0.936 +/- 0.060 | 0.933 +/- 0.063 | 0.95-1.00 / 1.00 | 8/8 | clipping 1.5-15 % |
| 6 | 8 | 0.892 +/- 0.076 | 0.890 +/- 0.077 | 0.95-1.00 / 1.00 | 8/8 | |
| 7 | 8 | 0.860 +/- 0.050 | 0.857 +/- 0.052 | 0.95-1.00 / 1.00 | 8/8 | |
| 8 | 8 | defined on 7: 0.10-1.23, not fitted | defined on 2: 0.63, 0.72 | 0.38-0.86 / 0.71-1.00 | 0/8 | the reconstructor's valid-fraction policy (0.75) refuses the other masks: "not defined" |

The round-1 conclusion stands: the 2 m deficit under actuator clipping is
a result about the whole linear model, which is not verified at 2 m.

## CHK-2d: the model on the ci-geometry pilot sidecars with `--pilot-record`

All four accepted (digest, size, frame counts, label, seed, hash). Window
prediction from the realized covariance, by rule; the reconstructor is
probed on that rule's rows:

| run | available rule: rows, window (nm^2), measured/window | strict rule: rows, window (nm^2), measured/window | unsensed modes (feedback below 1e-6), full mask | stationary limit, full mask |
| --- | --- | --- | --- | --- |
| m7, ci damping | 144/144, 212.6, **1.051** | 126/144, 418, 0.53 | 1 | 424.1 (window/stationary 0.50) |
| m7, 12 m damping | 144/144, 94.1, **0.987** | 144/144, 94.1, 0.987 | 0 | 94.2 (0.9998) |
| m9, ci damping (gate-active) | 144/144, 1388.4, 1.276 | 92/144, 7.3e5, 0.002 (20 unsensed modes; no stationary limit) | 1 | 2883.8 (0.48) |
| m9, 12 m damping | 144/144, 607.9, **1.011** | 138/144, 628, 0.979 | 0 | 608.0 (0.9998) |

The delayed injection changes the window values of these runs by less than
0.1 % (fast modes). A mask that leaves modes unsensed (no leak) has no
stationary limit and a window prediction dominated by those modes' random
walk: the strict rule does that where lenslets flicker, the available rule
(every row that fed the loop) does not. With the 12 m damping the two
gate-quiet runs agree with the available-rule prediction within one block
standard error, as in round 1.

## CHK-2e: negative checks (`negative/*.stdout`, no record written)

| case | outcome |
| --- | --- |
| a magnitude that is not the sidecar's (`--magnitude 6` on the m5 pilot sidecar) | refused: the built configuration hash is not the sidecar's; nothing read |
| a series sidecar renamed to another run's file name, checked against the record | refused: the record's sidecar reference (file name, digest, size) does not match the file |
| a sidecar whose `delta_v_m2` is one frame short of its declared shape | refused: array `delta_v_m2` has shape (149,), declared [150] |

## Not executed

Every pilot and stage of `pilot_requests.json`, any 12 m or 42 m run or
system build, any slow or HCIPy test.
