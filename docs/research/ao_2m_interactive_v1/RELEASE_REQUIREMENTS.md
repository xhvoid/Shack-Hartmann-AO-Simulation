# Explorer release requirements

This tracked contract carries the essential requirements from the original
22 October 2026 design and coverage specifications. Those working documents
remain retained locally. This release adds hosting and collaboration guidance;
it does not authorize new numerical studies.

## Frozen experiment

- Static, buildless HTML/CSS/ES modules with no external runtime assets, live
  computation API, random-realization controls, interpolation or metric
  reconstruction from compressed images.
- Native `det_emccd_2m_synthetic@1`: 2 m, 52 pupil samples, 5 x 5 nominal
  lenslets/actuators, 700 nm WFS, noise enabled. Explorer science is 1.65 µm.
- Exactly 180 scalar frames at 1 kHz, burn-in 40, root seed 1, realization 0.
  Statistics and numeric mean PSFs use all 140 equal-weight frames `[40,180)`.
  Forty deterministic movie indices include 0, 40 and 179. Do not confuse these
  sample sets. The frame-start span is 0.139 s and quadrature weight 0.140 s;
  these are sampled instantaneous PSFs, not finite-shutter integrations.
- Eight unique cases: baseline; r0 x 1.25 and x 0.80; AB magnitude 6 and 8;
  gain 0.10 and 0.30; queued latency 4. Baseline gain/latency/AB are 0.20/2/7.
  Groups share the baseline; independent cross-combinations are not available.
- Residual means `pre_update_residual_opd_m`; held correction is atmosphere
  minus that residual in OPD-equivalent metres. Pupil RMS removes piston.
  Keep tilt, angular origin, mask, physical axes and ideal-PSF normalization.
  Never substitute post-update wavefront summaries or average the OPD to
  obtain an averaged PSF. Queued latency L first affects WFS frame k+L+1.
- Full-horizon admission includes every actual atmosphere request, including
  midpoint/left-point exposure subsamples. The accepted legacy n=1 series ends
  at 0.179 s, 45.645 pixels travel against a strict 52-pixel budget; actual
  endpoint-inclusive pupil spacing is 2/51 m. No permissive guard slack.

## Synthetic observations

Use one fixed binary on the actual 156 x 156 angular grid: weights 2/3 and
1/3, primary at zero, secondary +6 x cells (333.792 mas). Derive each static
pair from the complete numeric mean PSFs with linear zero-extended convolution,
explicit even-grid origin, sufficient full padding and a common fixed crop.
Preserve full-convolution flux and report crop loss. No per-image peak/crop
renormalization, new science noise, calibrated counts, SNR or detection claim.
One spatially invariant on-axis PSF is illustrative, not field validation.
Bind scene, grid, mean-PSF parent, sample window, renderer and asset digests.
The observation pair stays separate from the movie cursor and PSF mode.

## Research Results

All eight groups need a quantitative plot/table, matched scientific context,
source path and locator/hash, producer/date where known, uncertainty semantics,
limitations and a usable source/evidence download:

| ID | Required coverage and evidence boundary |
| --- | --- |
| R1 | Saved sensing response/precision and measurement availability; preserve invalid centroids and the 12-realization tutorial scope. |
| R2 | Reconstruction, feedback, gain/latency and correction order; distinguish 1 m/1.5 m configurations, wavelengths, post-update RMS and pre-update science images. |
| R3 | ESO ten-layer strengths/winds, structure function and 2 m comparison; preserve eight realizations and frames 50–149. Altitude metadata does not demonstrate tomography. |
| R4 | Physical-camera evidence, 12 m profile progression and failed inverse-photon test. Plot `noise_variance_m2` (paired residual-map statistic), not the difference of mean squares. Keep profile versions distinct and S4 departures unresolved. |
| R5 | Historical 42 m S1 on `2312502` and S2 seeds 2–11; report sample SD, not SE/CI. The S2 driver was not retained. Keep physical-camera and noiseless profiles distinct and disclose periodic-band dependence. |
| R6 | Separate 8 m analytical P3/MASTSEL adapter with continuous fitting tail; 50 mas is an aperture radius. Retain estimator bias and unknown original producer/date. It is not native time-domain MCAO. |
| R7 | Small-fixture native/HCIPy comparison: 13 groups and 60 metrics (17 exact, 15 tight, 20 physical, 8 informational). Reduced-scale axis evidence is summary-only; full-scale confirmation is pending. |
| R8 | Quantitative numerical checks and open limits; ESO-tier convergence does not transfer to unrun detector profiles. Retain EE50 sampling limits, exposure approximations and absence of hardware validation. |

Use the committed `research/results.json` source inventory for exact locators
and hashes. Historical sources and downloads remain byte-identical. A missing
value needs an explicit reason. No new AO/HCIPy/TIPTOP runs, notebook execution,
calibration or ensemble may be launched merely to rebuild the showcase.
The 2 m controls cannot change historical research values or their identities.

## Integrity, browser behavior and acceptance

- Resolve every resource relative to the JSON/page that defines it; support
  root and project-subpath HTTP serving. No CDN, service worker or external
  runtime request. SHA-256 consistency is not authenticity certification.
- Validate schema, units, axes, finite values/null reasons, lengths, time/sample
  relationships, parent identities and member sizes/digests before installation.
  Coherently rehashed incompatible science metadata must still fail.
- Keep code content-addressed and bound to `data/current.json`. Changing page,
  module or stylesheet bytes requires `site_build.py --write` and revalidation.
  A stale page meeting a newer entry must refuse clearly and request reload.
- Default paused; play/pause, previous/next/restart/seek/rate use recorded frames.
  Display playback speed is separate from physical simulation time. Average
  PSF mode pauses and disables time controls while preserving the wavefront
  frame and curve cursor. Instantaneous mode restores controls.
- Lazy-load cases/research; cache at most two decoded cases. Cancel obsolete
  requests and reject late responses. Case images, labels and downloads install
  atomically, including rapid A→B→A switching and the observation pair.
- Provide keyboard/focus support, reduced-motion behavior, textual values and
  table/download alternatives. At 375 px there must be readable labels and no
  page-wide horizontal overflow. Test real root/subpath serving and negative
  loading states. Measure first usable default view <=5 MiB, distribution
  <=30 MiB and intended 10 FPS on a stated browser/host.
- Preserve profiles, scientific runtime, calibration and accepted baselines.
  Independent acceptance must bind an exact revision, resolve required findings
  and state remaining limits. Record actual checks, skips and resource costs.

For producer work, the original bounded scope was one 64/16 pilot, eight
180/40 cases, an observer-disabled passivity control and one seed-2 sensitivity
check. Those successful outputs are retained; publication reuses them. New
work must follow the current guard and cumulative 1200 s / 512 MiB ceilings,
without inheriting a historical repair override. See [DEVELOPMENT.md](../../../DEVELOPMENT.md).
