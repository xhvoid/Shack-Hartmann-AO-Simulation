# Generated-experiment mode: validation evidence

Bounded feature validation in the cloud development environment on
23 October 2026: Linux x86-64 (glibc 2.39), CPython 3.14.6, NumPy 2.5.1,
SciPy 1.18.0, the `constraints/py314.txt` lock verified (31 distributions, no
violation), two native threads, one numerical job at a time, memory
enforcement off (the default of [RESOURCE_POLICY.md](../../../RESOURCE_POLICY.md)).
The plan, the cumulative ledger and the evaluation are committed in
[`evidence/`](evidence/); raw run files stay in the ignored
`outputs/ao_dynamic_validation/fv1/` directory and are not transmitted.
The frozen explorer series and its ledger were not touched.

## Plan and cost

The plan (`evidence/plan.json`) was written before the pilot, at candidate
commit `2cb4c82`: one 64-frame pilot (burn-in 16) and five 180-frame runs
(burn-in 40) — `baseline` (default parameters, seed 1), `replay` (identical
physical configuration, display stride 3), `different-seed` (seed 171885098,
drawn when the plan was written), `same-atmosphere` (guide AB 8.5) and
`control` (baseline without any observer). Every run was admitted (maximum
travel 45.645 px of 52 px for the 180-frame runs).

The pilot measured 52 ms per frame of loop time, 1.7 s fixed overhead and a
127 MiB peak; the projected five runs (55 s, 71 MB) fitted the remaining
ceilings, so they ran. Measured wall time per 180-frame run was 9.2–12.9 s
(build 0.8–1.0 s, loop 9.6–10.9 s), peak 125–179 MiB.

The ledger (`evidence/ledger.jsonl`) records every development probe,
fixture/browser test session and planned run, failures included, with their
measured wall times (four early probes are rounded-up estimates and say so):
**the total stands in the ledger and in the acceptance record**, against the
ceilings of 1200 s numerical/processing wall time and 512 MiB raw evidence.
Browser sessions are counted with their whole wall time, not only the
service's compute.

## Results (`evidence/evaluation.json`)

| Required evidence | Result |
| --- | --- |
| Same-seed/configuration replay | `replay` equals `baseline`: loop-history digest, every per-frame value and digest, the summary, `final.bin` and the full-precision mean PSFs and final observations; all 61 frames kept by stride 3 are byte-identical to the baseline's, running averages included; same calibration identity. |
| Different seed | all 180 atmosphere samples differ; small-scale structure (pixel-to-pixel OPD differences) correlates at mean \|r\| 0.053, max 0.118, i.e. unrelated; the raw single-frame correlation (0.62, 0.50 without tip/tilt) is dominated by the few large-scale modes of a 2 m pupil with a 25 m outer scale; calibration identity differs; classed as a different realization, not paired. |
| Continuous frozen flow | one realization translated 0.255 px per frame: consecutive frames correlate ≥ 0.9986 (≥ 0.960 in small-scale structure), first and last frames −0.05 after 45.6 px of travel; all frame digests distinct; runtime travel equals the admitted value. Fixture test: four 0.25 px frames reproduce the frame-0 screen shifted one sample towards +x to 1e-9 of its RMS. |
| Full-horizon admission and over-horizon refusal | fixture tests: 204 frames admitted and 205 refused at 10 m/s (refused request 204, no slack); at 10.03 m/s frame starts fit but left-point n = 2, 4 and midpoint n = 1, 3 requests are refused with their exact request counts; the screen model itself refuses at the same request with memory enforcement off; the service answers 422 `not_admitted` with the record. |
| Real parameter effects / same atmosphere | `same-atmosphere` (AB 7 → 8.5) is **paired**: equal time grids and all 180 atmosphere digests, same atmosphere component hash; the WFS and interaction-matrix identities changed (calibration rebuilt); 177 residual samples differ; mean valid measurement fraction 1.0 → 0.666, mean residual 262.6 → 362.6 nm, averaged-intensity AO Strehl 0.448 → 0.288. Gain, delay and r0/wind effects on identities are covered by the calibration probe and fixture tests. |
| Observer/transport passivity | `control` (no observer) has the baseline's loop-history digest and configuration hash over all 16 history members; display stride 1/5 fixtures and the stride-3 replay leave histories, summaries and averages unchanged. |
| Phase units, RMS, PSF, Strehl | every frame: independent RMS ≤ 1.1e-22 m, peak Strehl ≤ 3.3e-16, held-correction identity 0; frames 0, 40, 179: direct-DFT PSFs ≤ 5.6e-17, Strehl ≤ 6.7e-16, `2π·OPD/λ` phase rule exact; the page's phase conversion and display codes match the Python rules under Node. |
| Binary oracles | existing explorer delta, weighted-shift, asymmetric/edge, padding and flux tests still pass; on real frames every observation equals 2/3·PSF(x) + 1/3·PSF(x − 6 cells) (a reversed axis fails); instantaneous and final full flux equal scene × kernel flux within 4.4e-16; native-window and display-crop fractions recorded. |
| Running/final averages vs throttling | running averages count every eligible frame (fixture: recomputed from every instantaneous observation; replay: equal at all common frames); linearity of averaged observations ≤ 2.8e-17; final averages identical at strides 1, 3 and 5; unavailable (NaN, count 0) before burn-in. |
| Cancellation and cleanup | service tests: a running job is stopped with SIGTERM, its process and group are gone, partial outputs removed, the runner continues; queued cancellation, timeout, injected failure and abandonment (no status request) release workers the same way. |
| A→B→A, stale responses, failure, reconnect | browser: a delayed response for B is ignored after returning to A; a superseded job is cancelled on the service and never installed; cancelled and failed jobs leave the displayed run; blocked status requests show a retry message and the job installs after reconnection. |
| API scientific-metadata refusal | the service refuses a tampered `run.json` (science wavelength) as a failed job; Python and page validators refuse 14 and 18 coherent metadata mutations; the page refuses a coherently rehashed record (status digests rewritten) and keeps the displayed run. |
| Real backend plus browser | headless Chromium against the running service from a separate static origin (CORS) and same origin: connect, run, replay, compare, new realization, reproduction, cancel, failure, downloads. |
| Keyboard, reduced motion, 375 px, downloads, cache | keyboard play/pause and seek; reduced motion starts at 2 frames/s; no page-wide overflow at 375 px (a run-selector overflow was found and fixed); downloads equal the verified bytes; the stale-build refusal still asks for a reload; generation code is content-addressed and loaded only on connect. |
| Precomputed site and R1–R8 | dataset and manifest unchanged; validator and `tests/ao_explorer` pass; the static page loads its baseline and the eight Research Results groups without any request to a service or to the generation code. |
| Against the published frozen baseline | the default request with seed 1 has the frozen baseline's configuration hash (`cb4a1068…`) and reproduces its published per-frame values to 1.1e-13 nm (atmosphere RMS), 5.2e-11 nm (residual RMS), 1.7e-13 (Strehl) and exactly for validity, across macOS arm64 / NumPy 2.5.0 and Linux x86-64 / NumPy 2.5.1. |

## Not established

- One realization per run; no ensemble statistics, convergence or
  confidence intervals. Physical conclusions about parameter sensitivity are
  illustrations, not studies.
- No public backend exists; public generation was not tested (see
  [DEPLOYMENT.md](DEPLOYMENT.md)).
- Browser checks used headless Chromium 1194 in the container; other browsers
  and real devices were not tested. Python 3.10 was checked only for syntax.
- No CI was run, following [AGENTS.md](../../../AGENTS.md).
