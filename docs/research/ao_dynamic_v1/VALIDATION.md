# Generated-experiment mode: validation evidence

Bounded feature validation in the cloud development environment on
23 October 2026: Linux x86-64 (glibc 2.39), CPython 3.14.6, NumPy 2.5.1,
SciPy 1.18.0, the `constraints/py314.txt` lock verified (31 distributions, no
violation), two native threads, one numerical job at a time, memory
enforcement off (the default of [RESOURCE_POLICY.md](../../../RESOURCE_POLICY.md)).
The plan, the cumulative ledger, the evaluation and a structural site
validation record are committed in [`evidence/`](evidence/); raw run files stay
in the ignored `outputs/ao_dynamic_validation/fv1/` directory and are not
transmitted. The frozen explorer series and its ledger were not touched.

## Plan, attempts and cost

The plan (`evidence/plan.json`) was written before the pilot, at candidate
commit `2cb4c82`: one 64-frame pilot (burn-in 16) and five 180-frame runs
(burn-in 40) — `baseline` (default parameters, seed 1), `replay` (identical
physical configuration, display stride 3), `different-seed` (seed 171885098,
drawn when the plan was written), `same-atmosphere` (guide AB 8.5) and
`control` (baseline without any observer). Every run was admitted (maximum
travel 45.645 px of 52 px for the 180-frame runs).

- **Attempt 1** (producer `f2677533…`, commit `2cb4c82`): the pilot measured
  52 ms per frame of loop time, 1.7 s fixed overhead and a 127 MiB peak; the
  projected five runs (55 s, 71 MB) fitted the remaining ceilings, so they ran.
- **Attempt 2** (producer `116a66a2…`, commit `760366f`): the first review's
  repairs changed producer files (`contract.py` validation and comparison
  rules, the worker's parent watchdog), so the planned runs were repeated once
  to bind the evidence to the delivered producer. A role is reused, never
  rerun, while its producer matches. **Every attempt-2 result is
  byte-identical to attempt 1**: loop-history digest, every per-frame value,
  summary, `frames.bin`, `final.bin`, calibration and atmosphere identities
  (control: history digest).
- **Attempt 3** (producer `32a4e216…`, commit `3384b18`): the requested CI run
  found `sys.path.insert` in the scripts, which the repository's lint job
  forbids; the scripts now load the reused explorer modules by file
  (`explorer_modules.py`, part of the producer identity). The planned runs were
  repeated once more and are again byte-identical to attempts 1 and 2. The
  evaluation uses attempt 3.

Measured wall time of the observed 180-frame runs was 11.2–12.9 s (build
0.8–1.0 s, loop 9.6–10.9 s, peak 125–179 MiB; stride 3 keeps fewer frames in
memory); the observer-disabled control took 9.2–10.2 s (loop 7.7–8.2 s);
the pilot about 5 s.

The ledger (`evidence/ledger.jsonl`) records every development probe,
fixture/browser test session, review processing and planned run, failures
included, with measured wall times (early probes that were not timed are
marked as rounded-up estimates). Browser sessions are counted with their
whole wall time. The totals are reported in the
[acceptance record](ACCEPTANCE.md) against the ceilings of 1200 s
numerical/processing wall time and 512 MiB raw evidence.

## Results (`evidence/evaluation.json`)

| Required evidence | Result |
| --- | --- |
| Same-seed/configuration replay | `replay` equals `baseline`: loop-history digest, every per-frame value and digest, the summary, `final.bin` and the full-precision mean PSFs and final observations; all 61 frames kept by stride 3 are byte-identical to the baseline's, running averages included; same calibration identity. Attempts 1–3 (three producer revisions) are byte-identical too. |
| Different seed | all 180 atmosphere samples differ; small-scale structure (pixel-to-pixel OPD differences) correlates at mean \|r\| 0.053, max 0.118, i.e. unrelated; the raw single-frame correlation (0.62, or 0.50 with tip/tilt removed) is dominated by the few large-scale modes of a 2 m pupil with a 25 m outer scale; calibration identity differs; classed as a different realization, not paired. |
| Continuous frozen flow | one realization translated 0.255 px per frame: consecutive frames correlate ≥ 0.9986 (≥ 0.998 with tip/tilt removed, ≥ 0.960 in small-scale structure); after 45.6 px of travel the first and last frames correlate at −0.28 (tip/tilt removed) and −0.05 (small-scale structure); all frame digests distinct; runtime travel equals the admitted value. Fixture test: four 0.25 px frames reproduce the frame-0 screen shifted one sample towards +x to 1e-9 of its RMS. |
| Full-horizon admission and over-horizon refusal | fixture tests: 204 frames admitted and 205 refused at 10 m/s (refused request 204, no slack); at 10.03 m/s frame starts fit but left-point n = 2, 4 and midpoint n = 1, 3 requests are refused with their exact request counts; the screen model itself refuses at the same request with memory enforcement off; the service answers 422 `not_admitted` with the record. |
| Real parameter effects / same atmosphere | `same-atmosphere` (AB 7 → 8.5) is **paired**: equal time grids, equal analysis windows and all 180 atmosphere digests, same atmosphere component hash; the WFS and interaction-matrix identities changed (calibration rebuilt); 177 residual samples differ; mean valid measurement fraction 1.0 → 0.666, mean residual 262.6 → 362.6 nm, averaged-intensity AO Strehl 0.448 → 0.288. Identity effects of gain, delay, r0 and wind are covered by the calibration probe and fixture tests; a burn-in difference is classed as a different analysis window, never paired. |
| Observer/transport passivity | `control` (no observer) has the baseline's loop-history digest and configuration hash over all 16 history members; display stride 1/5 fixtures and the stride-3 replay leave histories, summaries and averages unchanged. |
| Phase units, RMS, PSF, Strehl | every frame: independent RMS ≤ 1.1e-22 m, peak Strehl ≤ 3.3e-16, held-correction identity 0; frames 0, 40, 179: direct-DFT PSFs ≤ 5.6e-17, Strehl ≤ 6.7e-16, `2π·OPD/λ` phase rule exact; the page's phase conversion and display codes match the Python rules under Node. |
| Binary oracles | the explorer's delta, weighted-shift, asymmetric/edge, padding and flux tests still pass; on real frames every observation equals 2/3·PSF(x) + 1/3·PSF(x − 6 cells) (a reversed axis fails); full flux equals scene × kernel flux within 4.4e-16; native-window and display-crop fractions recorded; both validators require the crop to be centred on the zero-angle sample and the scene at that sample and +6 x cells. |
| Running/final averages vs throttling | running averages count every eligible frame (fixture: recomputed from every instantaneous observation; replay: equal at all common frames); linearity of averaged observations ≤ 2.8e-17; final averages identical at strides 1, 3 and 5; unavailable (NaN, count 0) before burn-in. |
| Cancellation and cleanup | service tests: a running job is stopped with SIGTERM, its process and group are gone, partial outputs removed, the runner continues; queued cancellation, timeout, injected failure and abandonment release workers the same way; a worker whose supervisor is killed exits by itself; a slow but steady client receives a whole file (the socket timeout bounds stalls, not downloads). |
| A→B→A, stale responses, failure, reconnect | browser: a delayed response for B is ignored after returning to A; start, Connect and Disconnect wait while a submission is pending, so no job is left untracked (a job whose creation is answered after the page moved on would be cancelled); a superseded job is cancelled on the service; cancelled and failed jobs leave the displayed run; blocked status requests show a retry message and the job installs after reconnection. |
| API scientific-metadata refusal | the service refuses a tampered `run.json` (science wavelength) as a failed job; the Python and page validators refuse the same classes of coherent mutation (ranges, fixed scope, units, timing, windows, layout, scene, crop centring, identities; the page recomputes the physical identity with Python-compatible float formatting); the page refuses a coherently rehashed record and keeps the displayed run. |
| Untrusted service data | the page builds markup only through an escaping template; a service publishing markup in its parameter table, run list, identifiers or file references is refused or filtered and no injected script runs (browser and Node checks); a `?backend=` link only fills in the address. |
| Real backend plus browser | headless Chromium against the running service from a separate static origin (CORS) and same origin: connect, run, replay, compare, new realization, reproduction, cancel, failure, downloads. |
| Keyboard, reduced motion, 375 px, downloads, cache | keyboard play/pause and seek; reduced motion starts at 2 frames/s; no page-wide overflow at 375 px (a run-selector overflow was found and fixed); downloads equal the verified bytes; the stale-build refusal still asks for a reload; generation code is content-addressed and loaded only on connect. |
| Precomputed site and R1–R8 | dataset and manifest unchanged; `validate.py` passes structurally (1290 checks, `evidence/site-validation.json`) and `tests/ao_explorer` passes on candidates `6f52c95` and `fc9a5c6` (the web-bundle part also on the final build) (the eight retained-evidence derive checks skip in a fresh clone); the static page loads its baseline and the eight Research Results groups without any request to a service or to the generation code. The committed `web/ao-explorer/validation/manifest-validation-…json` still describes build `08dc9a4b5688bf41` validated with raw evidence; refreshing it needs the retained series (command in `site-validation.json`). |
| Against the published frozen baseline | the default request with seed 1 has the frozen baseline's configuration hash (`cb4a1068…`) and reproduces its published per-frame values to 1.1e-13 nm (atmosphere RMS), 5.2e-11 nm (residual RMS), 1.7e-13 (Strehl) and exactly for validity, across macOS arm64 / NumPy 2.5.0 and Linux x86-64 / NumPy 2.5.1. |

## Not established

- One realization per run; no ensemble statistics, convergence or
  confidence intervals. Physical conclusions about parameter sensitivity are
  illustrations, not studies.
- No public backend exists; public generation was not tested (see
  [DEPLOYMENT.md](DEPLOYMENT.md)). The service has no authentication.
- Browser checks used headless Chromium 1194 in the container; other browsers
  and real devices were not tested. Python 3.10 was checked only for syntax.
- Whether the seed dependence of the calibration identity reflects numerical
  differences or only identity bookkeeping (the WFS stream identities) was not
  separated.
- CI was not run during development (project rules); the maintainer asked for
  one CI run after acceptance, recorded in the acceptance record.
