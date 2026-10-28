# Detector-level development: execution record

Prompt: [`DETECTOR_LEVEL_DEVELOPMENT_PROMPT.md`](DETECTOR_LEVEL_DEVELOPMENT_PROMPT.md).
Started 2026-10-15 (Europe/Berlin). This file is the durable execution record.
Each ticket states its status, evidence, commands, limitations, and next
action. A ticket is DONE only with its acceptance evidence. A gated run that
was not executed is NOT_RUN_RESOURCE_POLICY, never a pass.

## Summary

| Ticket | Status | Milestone | Evidence |
| --- | --- | --- | --- |
| DET-00 | DONE | A | entry gate (1986 passed on the base), environment, baseline costs, decisions D00-1…14, ledgers |
| DET-01 | DONE | A | schema 7, identities pinned, domains, telemetry levels, pixel layout |
| DET-02 | DONE | A | photometry oracles to 1e-12; QE once in the factory |
| DET-05 | DONE | A | CCD/EMCCD/CMOS chain, Monte-Carlo moments, saturation ordering, ADC, maps |
| DET-06 | DONE | A | estimated and oracle products; recovery; 1/N masters; pedestal; bad pixels |
| DET-07 | DONE | A, B | `detector_covariance_v1`; 10⁴-trial Monte Carlo within 2.1 %; coupling and interpolation; ensembles |
| DET-03 | DONE | B | MFT = FFT to 1e-12; erf ≤ 1e-6; diffusion; coupling covariance; interaction prediction |
| DET-04 | DONE | B | one sample = mono; exact λ scaling; quadrature convergence; linear cost |
| DET-08 | DONE | B | software acceptance; 12 m study: n_sub 2 and 4 give −3.4 and −4.5 nm paired (within seed scatter), so the default stays 1 |
| DET-09 | DONE (with recorded departures) | A, B | seven profiles (12 m @2 post-hoc); E1; E2 at 2 m and 12 m; 2 m ensembles; E3/E4/E6 on @1 (predeclared) and @2; E5 at 42 m: 173.2 nm, K Strehl 0.753 |
| DET-10 | DONE | A, B | feature-off overhead +1.3–1.8 % (2 m, ci), +0.9–1.0 % (medium); per-feature costs at 2 m, ci and 12 m; packaging; docs |

### Claim supported by the evidence (clause by clause)

Evidenced on the 2 m and `ci` tiers, on the 12 m tier (E2, E3, E4, E6 and
DET-08, each over 3–5 independent root seeds), and at 42 m by one
realization (E5). Every gated run was enabled by the user on 2026-10-16.

| Clause of prompt §2.1 | Evidence | In the claim |
| --- | --- | --- |
| polychromatic physical-optics lenslet images integrated over declared detector pixels | DET-03, DET-04 tests; `det_emccd_2m_plane_synthetic@1` loops | yes |
| with charge diffusion and declared electronic inter-pixel coupling | partition-of-unity and width tests; K·diag(μ)·Kᵀ covariance at 4×10⁴ samples | yes |
| source and sky photometry in physical units | DET-02 analytic oracles | yes |
| selectable CCD, EMCCD and CMOS camera models with shot, dark, pre-register CIC, excess, read and quantization noise, gain, bias and separate charge/register/digital saturation | DET-05 tests | yes |
| persistent detector maps tied to physical pixel identities | DET-01/05 map-identity tests | yes |
| real-time pixel processing that uses estimated calibration frames | DET-06 tests; every profile uses estimated products | yes |
| noise propagation verified against analytic and Monte-Carlo references | DET-07 (Monte Carlo within 10 %), E1, E2 | yes |
| temporal noise distinguished from persistent calibration error | separate temporal and calibration-ensemble sigma; ensemble tests | yes |
| noise-on closed-loop results reported over independent realizations | 2 m: 5 root seeds per profile; 12 m: E3 (5 seeds), E4 and E6 (3 seeds), DET-08 (5 seeds); 42 m: E5, one realization | yes at 2 m and 12 m; the 42 m result is one realization |

Claim wording supported now:

> A detector-level Shack–Hartmann SCAO simulation: polychromatic
> physical-optics lenslet images integrated over declared detector pixels,
> with charge diffusion and declared electronic inter-pixel coupling; source
> and sky photometry in physical units; selectable CCD, EMCCD and CMOS camera
> models with shot, dark, pre-register clock-induced-charge, excess, read and
> quantization noise, gain, bias and separate charge/register/digital
> saturation; persistent detector maps tied to physical pixel identities;
> real-time pixel processing that uses estimated calibration frames; and
> noise propagation verified against analytic and Monte-Carlo references,
> with temporal noise distinguished from persistent calibration error and
> noise-on closed-loop results reported over independent realizations on the
> 2 m and 12 m tiers, plus a single noise-on 42 m realization.

Still out of bounds:
- a digital twin of any commercial camera or ESO instrument;
- validation against on-sky or laboratory data;
- HCIPy parity for any physical-path feature;
- a 42 m ensemble (one realization only);
- a faint-star limiting magnitude independent of the control policy: the
  12 m loop latches up at m_AB = 11 because the reconstructor freezes the
  DM when the valid fraction drops below 0.5 (E3 dynamics diagnostic);
- a resolved 1/N_e noise law: the isolated noise term is resolved only at
  m_AB = 10 (2.6σ).

## Execution policy in force

- **User instruction, 2026-10-15: "suspend the resource guard".** On the
  first attempt the host sat at `warn` memory pressure (about 3.4 GiB
  available, 5.0 GiB swap in use). The supervisor in
  `shwfs_ao.runtime.resource_guard` therefore refused every batch at
  preflight. The refusal records are in the scratch directory under
  `det00/refused_attempt1`. Following the user's instruction, tests and
  timing runs since then execute **without** the supervisor and its
  preflight. They still run one process at a time, with
  `OMP/OPENBLAS/MKL/VECLIB_MAXIMUM/NUMEXPR_NUM_THREADS=2`, and each
  `pytest` batch's peak RSS is recorded with `/usr/bin/time -l`. Suspending
  the guard does not enable any section 2.5 gated run. Every 12 m `medium`
  run, any 42 m run, multi-seed batches over 30 min, and polychromatic runs
  with more than three samples above the `ci` tier still need the user's
  explicit enablement per concrete run.
- No commit, push, tag, or baseline acceptance without the user's separate
  authorization. Commits, when authorized, carry only the user's
  authorship.

## DET-00 — Entry gate, baseline, and decisions

Status: DONE (2026-10-15). The ledgers were completed with the DET-09 profiles and are checked by `tests/io/test_detector_level_ledgers.py`.

### Entry gate (prompt section 2.4)

| Condition | Result |
| --- | --- |
| Base revision | `37b5bd9d3874e0b1d596641ec4474b7bb2a9d45e` on `main` ("Update README with HCIPy corrections and reviewed validation status", 2026-10-15 21:08 +0200). `main` equals `origin/main`. The planning snapshot names the same commit on `public-clean-main`. That branch was merged into `main` and deleted locally (see the branch-layout note in the repository history). |
| AO-REF-016A lenslet-axis work, revised tests, lower-memory HCIPy build | `9352f6c`, `394d175`, `da189f3` are ancestors of the base (`git merge-base --is-ancestor`). Present. |
| Worktree state | Clean tracked tree. Three untracked planning documents are recorded and preserved: `AO_REFACTOR_MASTER_TICKETS_REVISED.md`, `docs/refactor/DETECTOR_LEVEL_DEVELOPMENT_PROMPT.md` (this work's prompt), `docs/repository_optimization_ticket.md`. No modifications to files this work touches. |
| Native regression on the base | See the regression table below. It ran on a separate clean worktree of the base (`git worktree add --detach <scratch>/base_wt 37b5bd9`, `PYTHONPATH=<worktree>/src`), so edits made during the run cannot reach it. |
| Known open items, recorded, not resolved here | `high_order_10m_*@3` loops are unstable: integrator gain 0.65 with `latency_frames: 2` exceeds the limit 0.618, and `tests/control/test_profile_stability.py` pins both as strict xfails. The even-window centroid bias is documented in `docs/refactor/eso_scao_evidence/published_profile_window_bias.md`. HCIPy closed-loop detector claims stay out of bounds until a lock-holding HCIPy profile exists; open-loop and sensor-level HCIPy checks remain in scope. |
| Current profile schema version | `shwfs_ao.io.configs.PROFILE_SCHEMA_VERSION == 6`. New record fields go into schema 7. |

Environment: macOS 26.5 on an Apple M1 Pro (8 CPUs, arm64, 16 GiB). The
host sat at `warn` memory pressure (level 2) at the start. Python 3.14.3,
NumPy 2.5.0, SciPy 1.18.0, HCIPy 0.7.0, psutil 7.2.2, pytest 9.1.1, and
Matplotlib 3.11.0, all from the repository `.venv`.

Regression on the base, `-m "not hcipy and not slow and not elt_scale"`,
seven serial batches (script: `<scratch>/det00/run_regression_unsupervised.sh`):

| Batch | Selection | Result | Wall | Peak RSS |
| --- | --- | --- | --- | --- |
| b1 | runtime, core, detector, compat, experimental | 471 passed | 29 s | 143 MiB |
| b2 | control, science, dm, wfs, calibration | 586 passed, 2 xfailed | 16 s | 499 MiB |
| b3 | io, docs, backends, cross_backend | 448 passed, 15 skipped | 46 s | 284 MiB |
| b4 | experiments | 115 passed | 48 s | 205 MiB |
| b5 | notebooks + top-level tests (first half) | 244 passed, 3 skipped | 264 s | 681 MiB |
| b6 | top-level tests (second half) | 120 passed | 18 s | 186 MiB |
| b7 | wheel install | 2 passed | 8 s | 102 MiB |
| **Total** | | **1986 passed, 18 skipped, 2 xfailed, 0 failed** | 429 s | 681 MiB |

The two xfails are the strict `high_order_10m_*@3` stability guards. The
entry gate is met.

### Baseline costs

Command (thread limits 2, unsupervised by user instruction):
`.venv/bin/python <scratch>/det00/baseline_costs.py docs/refactor/detector_level_evidence/det00_baseline_costs.json`.
Each component is called directly on fresh inputs, in the same way as
`eso_scao_benchmark._component_timings`. SH optics is
`optics_backend.spot_intensities`. "Detector + centroid" is the noiseless
`measure` minus the optics time. Results:
[`det00_baseline_costs.json`](detector_level_evidence/det00_baseline_costs.json).
Whole-process peak RSS was 132 MiB.

| Profile (lenslets) | Repeats | Atmosphere | SH optics | Detector + centroid | SH noiseless | SH noisy | Reconstruction | DM | Science (all λ) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `fast_2m_detector@4` (21) | 30 | 15.6 ms | 2.52 ms | 2.97 ms | 5.48 ms | 7.19 ms | 0.11 ms | 0.11 ms | 1.81 ms |
| `portfolio_2m_detector@4` (45) | 30 | 26.1 ms | 5.39 ms | 6.04 ms | 11.4 ms | 14.6 ms | 0.11 ms | 0.17 ms | 2.29 ms |
| `ci` = `eso_scao_smoke_5m_software@2` (72) | 10 | 5.9 ms | 4.79 ms | 9.91 ms | 14.7 ms | 17.9 ms | 1.67 ms | 0.14 ms | 2.23 ms |

Finding that shapes DET-05: the compatibility detector stage and the
centroid cost about 0.13–0.14 ms per lenslet. This is Python per-lenslet
overhead, comparable to the batched optics. At 42 m (about 5500 lenslets)
that is about 0.7 s of the 0.97 s SH measurement time in prompt section
2.5. The physical camera path is therefore vectorized across lenslets
(prompt DET-05 action 5).

### Decision record

Each decision lists the choice, the reason, and where it is enforced.

**D00-1 Response-model selection.** The AO-REF-004 compatibility chain
stays exactly as it is in `detector/effects.py`, and
`DetectorShackHartmannSensor` is not modified in any stage, draw, hash, or
default. The physical camera path is a separate, versioned model with its
own typed configuration (`PhysicalDetectorConfig`, response model
`shwfs_ao.detector.physical_camera.v1`) and its own sensor class
(`PhysicalShackHartmannSensor`). No field is added to `DetectorConfig`:
`canonicalize_for_hash` walks every declared dataclass field, so even a
trailing field with a `None` default would move every `DetectorConfig`
hash. In profiles, the physical model is selected by the presence of an
optional schema-7 top-level block, `detector_physics`. When that block is
absent, the sensor is the compatibility sensor. This follows the schema-5
`scalable` precedent: the field lists of the existing `detector` and `wfs`
blocks do not change, so no published nested hash needs a new stand-in.
`ccd` is not a compatibility default. Every physical camera type is
explicit.

**D00-2 Conflicting budgets.** With `detector_physics` present, the legacy
`detector` block must be neutral: `enabled: true`,
`photons_per_subap_frame: null`, `qe: 1.0`, `read_noise_e`, `dark_e_per_s`,
`background_e_per_pixel_frame` and `prnu_rms` zero, `full_well_e: null`,
`bad_pixel_fraction: 0`, and `prnu_mode: "persistent"`. Its `exposure_s` is
the frame exposure the camera uses. The camera block owns every noise
parameter, and the source block owns the budget, so no input can be stated
twice. The check "an enabled detector needs a photon budget" moves from
`DetectorSystemConfig` to `SystemConfig`, where the physics block is
visible. It is a validation-only change, it moves no hash, and every
packaged record still satisfies it.

**D00-3 Deterministic reference and stochastic stages.** `include_noise=False`
is the deterministic reference path. It substitutes charge means for the
Poisson draws (source, sky, dark), the mean CIC rate for the CIC draw, and
G·n for the EM register. Read-noise draws are zero. It retains PRNU, dead
pixels, hot-pixel dark maps, diffusion, pixel integration, coupling,
pixel and register saturation, non-linearity, gain, bias, fixed pattern,
ADC rounding and clipping, and pixel processing. Because E[f(X)] ≠ f(E[X])
for saturation, non-linearity, rounding, and clipping, the reference path
is not the expected noisy response in those regimes. The noisy-response
identity keeps them apart.

| Stage | Noisy path | Reference path |
| --- | --- | --- |
| optical photoresponse (PRNU, dead) | deterministic | same |
| dark map × exposure | expectation | same |
| source/sky/dark charge | Poisson (`detector.shot_noise`) | mean |
| pre-register CIC (EMCCD) | Poisson (`detector.cic`) | mean rate |
| pixel full well | clip, flag | clip mean, flag |
| EM register | Gamma(n, G), high-gain regime only (`detector.em_gain`); G = 1 deterministic | G·n |
| register capacity | clip, flag | clip, flag |
| electronic coupling K | linear on realized signal | linear on mean |
| read noise | Normal, per-pixel σ for CMOS (`detector.read_noise`) | zero |
| non-linearity, gain, bias, fixed pattern | deterministic | same |
| ADC rounding, digital clip | deterministic on the realized value | deterministic on the mean |
| pixel processing | fixed masters | same masters |

**D00-4 Photon, electron, and ADU budgets; QE ownership.** The physical
path receives detected photoelectrons per subaperture per frame before
window loss and PRNU. It applies no further QE: the photometry model
(`shwfs_ao.detector.photometry`) applies QE exactly once, inside its
spectral integral. A direct budget enters as either `detected_electrons`
(already QE-weighted) or `incident_photons` with one declared scalar QE,
which the photometry layer multiplies once. The historical
`photons_per_subap_frame × qe` interface is untouched. Unit labels are
`incident_photons`, `input_e` (photoelectrons before EM gain),
`output_e` (after EM gain), and `adu`. Conversion gain is output e⁻/ADU.
Processed frames are input-referred electrons, divided by the declared EM
gain. Per-subaperture budgets scale with the illuminated collecting area
(illuminated pupil samples × sample area), so partial illumination and
central obstruction are counted once. Window capture is applied afterwards,
from the optics' capture fraction relative to the pre-window flux.

**D00-5 Detector-pixel layout and map identities.** The layout is
`isolated_lenslet_blocks.v1`, declared in `shwfs_ao.detector.layout`.
Lenslet `lenslet-rRRRR-cCCCC` owns a non-overlapping block of
`(window + 2·guard)²` physical pixels at detector origin
`(R·pitch, C·pitch)`, with `pitch = window + 2·guard`. A pixel's immutable
ID is its global `(row, column)` on the
`(n_across·pitch) × (n_across·pitch)` synthetic detector, flattened row
major. Windows never overlap, so overlap is rejected by construction, and
light from neighbouring lenslets is not modelled. Persistent maps (optical
PRNU, dead pixels, hot-pixel dark map, CMOS offset, gain, and read-noise
maps, fixed-pattern offsets) are drawn per block from
`detector.realization`. Each block's key is
`(maps config hash, layout hash, R, C, realization index)`. A pixel's map
value therefore depends only on its physical identity, never on lenslet
order, batch size, the dense or batched path, or which lenslets are
retained. The realization hash binds the layout, the map-generating
settings, the root seed, the derivation, and a streamed content digest.
The old shared-window realization survives only in compatibility mode.

**D00-6 Pixel integration and coupling (DET-03).** The optical model
evaluates each lenslet's focal field with a matrix Fourier transform at
k×k Gauss–Legendre nodes per detector pixel, on the block plus a diffusion
margin. The pixel value is ∫ I(θ) R_c(θ) dθ, where R_c = rect_pixel ⊗
G_σ is the pixel response including charge diffusion. G_σ is a Gaussian
truncated at ±5σ and renormalized on that support, so the responses form
an exact partition of unity: Σ_c R_c = 1. The integral is evaluated by the
nodes' quadrature weights. It is separable, so the operator is two small
matrices per axis, shared by all lenslets. With k = 1 the single node is
the pixel centre with unit weight, so the model reduces to point sampling.
That is the legacy FFT mapping when the pixel scale equals
λ/(pad·n_s·dx). Gauss–Legendre nodes, rather than uniform midpoints, are
chosen so that an analytic Gaussian spot meets the 1e-6 erf acceptance at
a modest k (the midpoint rule converges only as 1/k²). Charge diffusion is
therefore a normalized Gaussian on the sub-pixel expectation grid, and the
integral is evaluated with node quadrature rather than uniform binning.
DET-03 verifies this operator against an independent uniform
oversample-and-bin reference. Electronic coupling is a separate 3×3
nonnegative, unit-sum operator K, applied in the camera layer to realized
charge-equivalent signals after pixel and register saturation and before
read noise. Its boundary is zero outside the lenslet block. The outward
flux loss is reported, never renormalized.

**D00-7 Shared spectral sampling.** The new module `shwfs_ao.core.spectral`
owns WFS wavelength quadrature: Gauss–Legendre or trapezoid nodes over a
band, or tabulated curves. The photometry and polychromatic optics both
use it. `science.bandpass.ScienceBandpass` is left unchanged because its
fields and hashes are frozen by AO-REF-000. Detector code never imports
`io.public_data`.

**D00-8 Telemetry levels.** `full` keeps today's per-lenslet frames and
optical spots. `summary` keeps only O(n_lenslets) scalar diagnostics per
frame. The level is a runtime option on the sensor (and
`ScaoExecutionOptions`), not a profile field, and it moves no identity.

**D00-9 Scale-dependent response identities.** The physical
`response_hash` binds the deterministic reference response conditional on
fixed calibration products. That covers the camera response-model
version, the layout, the map-generating settings with the realization's
derivation, the photometric budget (non-linearity, saturation, and
quantization break scale invariance, so the absolute scale is always
bound), sky, the optics sampling, the bandpass, the processing mode, and
the calibration-product content hashes. The `noisy_response_hash` adds the
temporal-noise settings that do not change the deterministic reference:
scalar read noise, the CIC rate as a fluctuation (its mean is already in
the response), and the EM-gain distribution model. Scalar temporal read
noise therefore moves only the noisy identity. CMOS read-noise *maps* are
map-generating, so they move the realization and response identities.
Regenerated calibration products with new contents move the conditioned
response identity.

**D00-10 Corrected calibration products and gain.** All products are in
the raw readout unit (ADU, or `output_e_equivalent` with the ADC off), and
the unit is labelled on each product.
- B̂ = mean of N_bias zero-exposure frames. It includes the per-read CIC mean.
- D̂ = mean of N_dark operating-exposure dark frames − B̂.
- Ŝ = mean of N_sky source-off sky frames − B̂ − D̂ (optional).

Processing subtracts B̂ + D̂ + Ŝ once. That sum telescopes to the mean of
the sky frames, or of the dark frames when there are no sky frames. So no
component is subtracted twice, and the shared-frame covariance follows
directly from the algebra. The flat is (mean of N_flat uniformly
illuminated frames − B̂ − D̂), converted with the same gain conversion as
measurements and normalized to unit mean over declared valid pixels.
Conversion gain and EM gain are **known engineering inputs** (labelled
`known`). The CMOS relative gain map is either applied as known per-pixel
conversion gain, in which case the flat carries PRNU only, or left to the
flat (`gain_treatment: "flat_absorbs_gain_map"`). It is never corrected
twice. Saturated calibration pixels are rejected.

**D00-11 Temporal versus calibration-ensemble uncertainty.** DET-07 reports
two quantities:
- temporal centroid covariance conditional on fixed masters (the
  frame-to-frame precision, used by validity gates);
- calibration-ensemble covariance from master-estimation error, which
  appears as a persistent per-run centroid bias, constant across frames
  and redrawn only when masters are regenerated.

The Monte-Carlo harness tests them separately: temporal trials hold the
masters fixed, and ensemble trials regenerate them.

**D00-12 Random domains.** New domains: `detector.cic`, `detector.em_gain`,
`detector.calibration_frames`. They are registered only on providers that
build a physical sensor (`DETECTOR_PHYSICS_RANDOM_DOMAINS`). They are not
added to `DEFAULT_RANDOM_DOMAINS`, because the closed loop records a stream
ID for every default domain, and adding one would change every published
loop history. Derivation hashes the domain name, so registration cannot
shift an existing domain's draws.

**D00-13 Supported EM-gain regime.** Unity gain is deterministic
multiplication. The Gamma(n, G) register model (D1) is accepted for
100 ≤ G ≤ 10000. There, F² = 2 differs from the finite-stage value of D2
(about 1.97 for 536 stages) by less than 2 %. Gains with 1 < G < 100 are
rejected.

**D00-14 Odd windows.** New physical records require an odd native window
(symmetric about the optical-axis pixel). HCIPy physical features fail
closed with a factory error.

### Ledgers

Detector source ledger: `src/shwfs_ao/resources/benchmarks/detector_source_ledger.v1.json`.
- D1, D4 and D5 were checked by web search in this session.
- D2 was confirmed only through citing work; its DOI is unverified.
- D3, D7, D8 and D9 are as given in the prompt.
- There is no D6, so every preset is `synthetic_assumed`.
- R3 and R4 are copied unchanged as contextual cases.

Detector assumption ledger (B01–B14 as required, plus B15 neutral legacy
block, B16 noise-on validity floor and B17 inherited base values):
`src/shwfs_ao/resources/benchmarks/detector_level.assumptions.v1.json`.
`validate_benchmark_profiles` checks it against every profile.

**Decision D00-3a (added during DET-09).** On the reference path the ADC
stage is the quantizer's expectation under the declared read-noise dither,
`E[round(x + n)]`. That is `rint` for σ < 0.05 ADU, and its bias is at most
2.3×10⁻³ ADU at σ = 0.5 ADU. Literal rounding of the reference image
quantized away the sub-ADU pixel changes of small calibration probes. See
"DET-09 gain-scan result".

## DET-09 — Predeclared protocols (recorded 2026-10-15, before any scan ran)

**Controller gain selection (B11).**
- Candidate gains: {0.2, 0.3, 0.4, 0.5}. Leak and latency are inherited
  from the base profile.
- Before any run, each candidate must pass the discrete-time stability
  check: the maximum modulus of the roots of
  `z^(L+1) − (1 − leak) z^L + gain` must be ≤ 0.98. With L = 2 and leak 0
  or 0.02, the moduli are 0.72–0.94, so all four candidates pass.
- Scan tier: the cheapest tier that shares the loop parameters.
  - 2 m profiles (1000 Hz, L = 2): the profile itself.
  - 12 m and 42 m profiles (500 Hz, L = 2): the `ci` geometry
    (`eso_scao_smoke_5m_software@2`) with the same detector physics.
- Runs: `include_noise = true`, atmosphere realizations 0, 1, 2, and the
  profile's frame count (at least 60).
- Selection criterion, fixed now: the lowest post-update residual RMS
  averaged over the second half of the frames and over the three
  realizations. A gain qualifies only if its mean valid-measurement
  fraction over those frames is ≥ 0.9 and no realization's final residual
  exceeds its open-loop RMS. Gains whose criterion values differ by less
  than 2 % count as tied, and the lower gain wins the tie.
- The chosen gain is not changed after the E1–E6 evidence is inspected,
  unless a recorded reason is given and the affected experiments are rerun.

**Spot-sampling constraint found while planning the band-limited profiles.**
The packaged ESO tiers sample each 0.5 m subaperture with 12 pupil samples
(dx = 4.17 cm). The sampled pupil's far field repeats with period λ/dx,
which is 14.4 µrad at 600 nm, the short edge of the R3 band. The published
23-pixel window at 0.7 µrad/px spans 16.1 µrad and would alias at 600 nm,
although it is valid at the 700 nm monochromatic wavelength (period 24 px).
The polychromatic 12 m and 42 m detector profiles therefore use a 15-pixel
centroid window with a one-pixel guard ring and diffusion σ = 0.2 px (a
one-pixel margin). Together that is 19 px, or 13.3 µrad, which is less
than one period, and `MftShackHartmannOptics` fails closed whenever the
represented extent reaches a period. At 0.7 µrad/px the pixels are
Nyquist-sampled at 700 nm and 0.86 × Nyquist at 600 nm; the recorded
`nyquist_ratio` is 0.857. This limitation comes from the shared pupil
sampling, not from the detector model.

### DET-09 gain-scan result (2026-10-15)

Command: `.venv/bin/python scripts/run_detector_level_evidence.py gain-scan`
(130 s, 168 MiB peak). Record:
[`det09_gain_scan.json`](detector_level_evidence/det09_gain_scan.json).
Criterion: the predeclared second-half mean post-update residual over
atmosphere realizations 0–2.

| Scanned configuration | 0.2 | 0.3 | 0.4 | 0.5 | Selected |
| --- | --- | --- | --- | --- | --- |
| `det_ccd_2m_synthetic` (60 frames) | 317.5 nm | 314.1 | 312.7 | 312.6 | 0.2 (all within the 2 % tie band) |
| `det_emccd_2m_synthetic` | 317.9 | 314.3 | 313.3 | 313.4 | 0.2 (tie band) |
| `det_cmos_2m_synthetic` | 317.4 | 314.1 | 312.9 | 312.7 | 0.2 (tie band) |
| `det_emccd_2m_plane_synthetic` | 316.9 | 314.0 | 313.6 | 313.7 | 0.2 (tie band) |
| ci geometry + `det_emccd_12m_medium_derived` physics | 205.1 | **198.3** | 198.5 | 217.5 | 0.3 (0.4 tied with it; the lower gain wins) |
| ci geometry + `det_ccd_42m_r3band_derived` physics | 205.4 | **196.6** | 198.2 | 215.1 | 0.3 (0.4 tied with it; the lower gain wins) |

- Every gain had a maximum pole modulus of 0.72–0.94 and a mean valid
  fraction of at least 0.98, and none lost lock.
- The 2 m open-loop residual is 415 nm. The 5×5 DM's fitting error
  dominates there, so the gain hardly matters.
- The ci open-loop residual is 1401 nm.

Two findings from building the scan configurations:

1. **Reference-path quantization (decision D00-3a).** The first build
   failed: the sparse calibration found all-zero actuator columns. Two
   effects were checked.
   - Rounding to ADC codes on the deterministic reference path quantizes
     away the sub-ADU pixel changes of a 10 nm probe. The reference path
     now keeps the quantizer as its expectation under the declared
     read-noise dither,
     `E[round(x + n)] = x + Σ_k (−1)^k sin(2πkx) exp(−2π²k²σ²)/(πk)`.
     That is exactly `rint` for σ < 0.05 ADU, and it matches Monte Carlo
     within sampling error (σ = 0.1–1.0 ADU, 4×10⁵ draws). Its bias is
     2.3×10⁻³ ADU at σ = 0.5 ADU.
   - Even so, the zero columns persisted. The remaining cause was effect 2.
2. **Register-capacity gate.** At m_AB = 6 the brightest pixels of the
   12 m EMCCD physics (G = 300, register 800 k e⁻) exceeded 90 % of the
   register capacity. `detector_covariance_v1` flags that as outside its
   domain, so those lenslets were invalid and gave NaN rows. The
   magnitude of `det_emccd_12m_medium_derived` was therefore set to
   m_AB = 8 (about 2.5 k e⁻ per subaperture). This is the declared
   bright-star setting for an EMCCD at this gain. The gate behaved as
   designed.

## DET-01 — Schema, identity, random domains, telemetry

Status: DONE (2026-10-15). Base `37b5bd9`.

Changed files:
- `src/shwfs_ao/io/configs.py`: schema 7, `DetectorPhysicsConfig`, the
  v7-only rules, `detector_physics` in the identity maps.
- `src/shwfs_ao/io/camera_presets.py`.
- `src/shwfs_ao/core/random.py`: `DETECTOR_PHYSICS_RANDOM_DOMAINS`,
  `with_detector_physics_domains`.
- `src/shwfs_ao/core/types.py`: additive optional fields on `DetectorFrame`
  and `DetectorTelemetry`.
- `src/shwfs_ao/detector/layout.py`, `camera_maps.py`.
- `src/shwfs_ao/wfs/shack_hartmann/physical_measurement.py` (identities).
- `src/shwfs_ao/experiments/scao.py`: the v7 build path and
  `ScaoExecutionOptions.telemetry_level`.
- `src/shwfs_ao/backends/native/factory.py`: the `physical_detector`
  keyword.
- `src/shwfs_ao/backends/hcipy/factory.py`: fails closed.
- `core/__init__.py`, `io/__init__.py`: re-exports.

Decisions D00-1, D00-2, D00-5, D00-8, D00-9, D00-12 and D00-14 are enforced
here.

Evidence:
- **Unchanged identities, asserted.**
  `tests/io/test_configs.py::test_every_packaged_profile_identity_is_pinned`
  and `::test_every_packaged_nested_wfs_identity_is_pinned` keep all 26
  previously packaged pins unchanged. They failed only on the six *new*
  keys until those were appended. The legacy sensor, calibration hashes,
  response hashes and noise-stream identities are untouched code. The full
  regression, including `tests/wfs/test_noise_stream_identity.py` and
  `test_legacy_seeded_output_regression.py`, passes; see "Final
  verification".
- **Round-trips and rejection before construction.**
  `tests/io/test_detector_level_profiles.py` (19 tests) covers round-trips
  and every rejection case:
  - unknown, extra or missing camera fields; an unknown preset;
  - an exposure longer than the frame period;
  - an even window in a v7 record;
  - a non-neutral legacy detector block;
  - HCIPy with physics;
  - a polychromatic band with legacy sampling, or a pad factor with MFT;
  - coupling without a guard ring;
  - a v6 record carrying the block.
- **Identity rules.**
  `tests/wfs/test_physical_sensor.py::test_identity_rules_of_the_physical_sensor`:
  - telemetry level moves no identity;
  - scalar read noise (oracle products held fixed) moves only
    `noisy_response_hash`, leaving the response and realization hashes
    unchanged;
  - ADC bit depth and the guard/layout move `response_hash`;
  - regenerated estimated products move the response hash but not the
    realization.

  The legacy PRNU-seed exception lives in the untouched legacy sensor.
- **Random domains.**
  `tests/detector/test_physical_camera.py::test_registering_physics_domains_leaves_existing_draws_identical`:
  the stream IDs and draws of every default domain are identical after
  registration.
- **Pixel identity.**
  `test_maps_follow_physical_pixels_not_order_batch_or_subset` and
  `test_an_isolated_defect_stays_on_its_pixel`: maps follow physical
  pixels, never lenslet order, batch or subset, and distinct pixels do not
  alias.
- **Telemetry.**
  `tests/wfs/test_physical_sensor.py::test_summary_telemetry_keeps_only_per_lenslet_scalars`.
  Summary telemetry retains only O(n_lenslets) scalars (it rejects frames
  and spots by construction).

  Persistent maps and products scale with the physical pixel count: about
  8 bytes × enabled maps × pixels. The vectorized chain's scratch is
  O(n_lenslets × block²) per frame. The scalable path streams optics in
  batches bounded to 64 MiB of scratch.

Limitations:
- The physical path holds the per-frame block arrays of all lenslets at
  once: at 42 m that is about 5500 × 17² × 8 B × roughly 10 arrays, or
  about 130 MB.
- `summary` telemetry is an execution option, not a profile field.

## DET-02 — Source and sky photometry

Status: DONE (2026-10-15). Owner: `shwfs_ao.detector.photometry` with
`shwfs_ao.core.spectral` (decision D00-7).

Evidence: `tests/detector/test_photometry.py` (9 passed).
- **AB zero point and analytic fixture.** AB zero point 3630.78 Jy (Oke &
  Gunn −48.60). A flat-f_ν top-hat with constant T and QE matches
  `A t f_ν T q ln(b/a)/h` to rtol 1e-12, with 12 Gauss–Legendre nodes.
- **Scaling.** The budget scales as 10^(−0.4Δm) and linearly with area,
  exposure and throughput. Only detected electrons scale with QE.
- **Wavelength-dependent QE.** A wavelength-dependent QE and throughput
  match `scipy.integrate.quad` to 1e-9, and the spectral weights match the
  independent node contributions.
- **Narrow-band limit.** The limit reduces to the monochromatic formula
  (1e-7 for a 0.1 nm band).
- **Sky.** Sky electrons per pixel match a hand calculation (1e-12) and
  scale with solid angle.
- **Integration.** `tests/wfs/test_physical_sensor.py`:
  - QE = 0.5 gives half the QE = 1 source electrons, not a quarter, both
    in the budget and in the expected frame;
  - budgets follow partial illumination under a 0.3 obstruction;
  - window capture is applied once.

Example `examples/run_public_data_overview.py`: kept separate and
unchanged. Its 0.25-throughput estimate is a documented illustration
outside the detector chain, and moving it would change that example's
published output. The package model is the one any profile uses.

## DET-05 — Camera models and electronics

Status: DONE (2026-10-15). Files: `detector/camera.py`, `physical.py`,
`camera_maps.py`; presets in
`resources/benchmarks/detector_camera_presets.v1.json`.

Evidence: `tests/detector/test_physical_camera.py` (28 passed). Monte-Carlo
bands are five standard errors computed from the sample count and the
sample fourth moment, with 10⁵ samples per point.
- **EMCCD register.**
  - Register alone with fixed n ∈ {1, 5, 40} and G ∈ {100, 1000}: mean
    G·n, variance n·G².
  - Poisson(μ) for μ ∈ {0.5, 4, 30} through the register: mean G·μ,
    variance 2G²μ.
  - G = 1 adds no variance, and n = 0 stays exactly zero.
  - Intermediate gains are rejected.
  - Pre-register CIC is drawn once and receives the full gain.
- **Saturation ordering.** An overfilled pixel sits at the full well
  before read noise; the measured variance equals the read variance.
  Pixel, register and digital limits flag separately.
- **Photoresponse.** PRNU leaves the dark expectation unchanged. Dead
  pixels keep their dark current and bias; hot pixels add their declared
  dark current.
- **ADC.** The quantization variance is 1/12 ADU² within five standard
  errors. Bias is recovered, and codes saturate at 2^bits − 1 with a flag.
- **Maps and hashes.** Maps persist across frames and replay across
  reorder and subset. The realization hash moves with hot-pixel, CMOS-map,
  offset and PRNU settings, and not with scalar read noise, conversion
  gain, dark current, bias or full well.
- **Compatibility.** Frames, draws and stream IDs are bit-identical
  because the AO-REF-004 path is untouched. The legacy regression suites
  pass.

Cost: see DET-10 (feature costs on the 2 m and `ci` tiers).

## DET-06 — RTC pixel processing with estimated calibration frames

Status: DONE (2026-10-15). File: `detector/processing.py`, with integration
in the physical sensor. Decision D00-10 records the product algebra and the
known-gain treatment.

Evidence: `tests/wfs/test_physical_sensor.py` (13 passed).
- **Noiseless linear fixture.** EMCCD with G = 300, ADC off, known gain,
  bias, dark, sky and PRNU, identity coupling: it recovers the input
  electrons as S·⟨r⟩ to 1e-10.
- **CIC.** The CIC mean is in B̂ and is subtracted once.
- **Masters.** The background-master variance scales as 1/N: within 10 %
  of σ²/N for N = 4 and 16, and the ratio 4.0 ± 0.5, over 60
  regenerations. The shared-dark covariance is in the model and is checked
  by the DET-07 ensemble test.
- **Fixed masters.** A fixed master is reused identically over a temporal
  sequence.
- **Pedestal.** Oracle subtraction under a bright sky reproduces the
  background-free tilt response (1e-6). The raw readout loses more than
  10 % of the gain.
- **Bad pixels.** Masking keeps a finite centroid, and interpolation does
  too. A fully masked window gives an explicit invalid row (NaN) with
  `masked_pixel_fraction = 1`. A sensor with every pixel dead fails at
  calibration.
- **Reuse.** A calibration built with different products is rejected:
  regenerated products move `response_hash`, which the loop and matrix
  validators compare.
- **Defaults.** Every existing profile keeps its raw-frame centroid, since
  the compatibility sensor is untouched.

The estimated-flat error and its dependence on flux and frame count are
covered by DET-07: `test_calibration_contribution_falls_with_master_frame_count`
and the E1 ensembles.

## DET-07 — Extended centroid-noise model and Monte-Carlo verification

Status: DONE for Milestone A and for the Milestone B coupling extension
(2026-10-15). File: `detector/noise_model.py` (`detector_covariance_v1`).
The existing `first_order` and `legacy_spot_width` models are unchanged.

Evidence: `tests/detector/test_noise_model.py` (21 passed, including 14
`slow` tests with 10⁴ trials per point, run explicitly).
- **Temporal scatter.** CCD, EMCCD and CMOS, each photon-limited and
  read-limited at SNR_T ≥ 10, agree within 10 %. Measured E1 ratios are
  0.987–1.008 photon-limited and 1.03–1.04 read-limited, with the
  linearization error of about 4/SNR_T² stated.
- **Calibration ensemble.** 400 regenerations, with sky frames and with
  shared dark frames, agree within 15 % (measured 0.98–1.04). The sigma
  falls by a factor of 2 per 4× frames.
- **Coupled readout.** The covariance equals K·diag(μ)·Kᵀ + σ²I with an
  explicit dense K written independently of `apply_coupling`. This holds
  for a flat field and a localized source, at 4×10⁴ samples, within five
  standard errors per element. Off-diagonal entries are resolved at more
  than 10 SE.
- **Diagonal approximation.** Dropping the off-diagonal covariance of the
  coupled centroid fails by more than 30 %, while the full model agrees
  within 10 %.
- **Interpolated bad pixels.** These agree with the Jacobian oracle (10 %),
  and Cov(Y_bad, Y_n) = Var(Y_n)/4 holds (10 %).
- **Out-of-domain flags.** Thresholded, negative-clipped, saturated,
  coarsely quantized (0.2 ADU), non-linear and SNR_T < 7 regimes are all
  flagged unsupported.

Domain change recorded before inspecting closed loops: Monte Carlo showed
the first-order sigma low by 12 % at SNR_T = 5.6, 7 % at 7.4 and 3.5 % at
11.8. The supported floor was raised from 5 to 7, so a "supported" sigma is
one the 10 % claim covers.

## DET-03 — Detector-plane sampling: MFT, pixel integration, diffusion, coupling

Status: DONE (2026-10-15); the medium-tier cost is NOT_RUN_RESOURCE_POLICY.
Files: `backends/native/shwfs_mft.py`, coupling in `detector/physical.py`.
Decision D00-6.

Evidence: `tests/backends/native/test_shwfs_mft.py` (18 passed).
- **k = 1 equivalence.** With k = 1 and the legacy pixel scale, the MFT
  reproduces the frozen FFT spots and capture fractions to rtol 1e-12. This
  holds for pads 2 and 3, blocks 15 and 21, a 0.2 obstruction and random
  OPDs, and on the compact-geometry batched path.
- **Gaussian oracle.** An analytic Gaussian matches erf pixel integrals to
  ≤ 1e-6 at k = 4. Convergence is reported for k = 2, 4, 8 and 16 and is
  monotone.
- **Square lenslet.** A fully illuminated square lenslet matches an
  independent Dirichlet-kernel `quad` integration to 1e-9.
- **Partition of unity.** The pixel responses sum to one at every angle to
  1e-12, for σ ∈ {0, 0.2, 0.5}.
- **Flux bookkeeping.** With no diffusion, the block flux equals the
  represented optical flux (1e-12). With diffusion, block plus outflow
  equals represented (1e-12). Optical-field, diffusion-outflow and window
  losses are reported separately.
- **Diffusion width.** Diffusion adds σ² to the spot variance (1e-4).
- **Coupling.** The coupling kernel is normalized and its identity is
  exact. The covariance K·diag(μ)·Kᵀ + Σ_read is verified (see DET-07).
- **Interaction prediction.** On the noiseless 2 m fixture the matching
  interaction calibration predicts the open-loop response to a random
  5 nm DM command (`experiments.detector_level.interaction_prediction_check`).
  The relative error is 2.8×10⁻⁴ point-sampled (`det_emccd_2m_synthetic@1`)
  and 5.7×10⁻⁵ pixel-integrated with diffusion and coupling
  (`det_emccd_2m_plane_synthetic@1`). The tilt gain moves from 1.69×10⁶ to
  1.75×10⁶ px/rad; 1/pixel is 1.85×10⁶. Noise amplification and loop
  performance are reported in DET-09.
- **HCIPy.** It fails closed at the config and factory level.
- **Aliasing.** A represented extent reaching the far-field period fails
  closed.

The Fourier pixel-transfer optimization is not used.

## DET-04 — Polychromatic WFS

Status: DONE on the 2 m and `ci` tiers (2026-10-15).

Evidence (`tests/backends/native/test_shwfs_mft.py`):
- A one-sample bandpass reproduces the monochromatic output exactly.
- Spots scale with λ exactly: the 600 and 900 nm images at pixel scales in
  the ratio 2:3 agree to 1e-12.
- Quadrature convergence, with a tolerance predeclared in the test
  docstring: the slopes for 5 and 7 Gauss–Legendre nodes agree within
  2×10⁻³ px, and the 3-node error is below the 1-node error.
- Calibration uses the same polychromatic model, and the bandpass is in the
  response identity.
- The R3 band (0.6–0.9 µm) is ledgered (B05) for the 12 m and 42 m
  profiles.
- Sampling at the shortest wavelength is recorded per optics as
  `aliasing_margin` and `nyquist_ratio` (0.857 for the 12/42 m profiles at
  600 nm).

Cost scaling is in DET-10.

## DET-08 — Finite-exposure integration study

Status: DONE. The software acceptance passed. The 12 m comparison ran on
2026-10-16 (see "Gated-run results"): n_sub = 2 and 4 change the residual
by −3.4 ± 0.5 and −4.5 ± 0.8 nm, paired, within the seed scatter, so the
default stays 1.

Changes:
- `run_closed_loop(..., exposure_subsamples, exposure_s)`.
- `PhysicalShackHartmannSensor.measure_exposure`.
- `scao.run_closed_loop` passes the keywords only when a profile sets
  `detector_physics.exposure_subsamples > 1`.

`LoopConfig` is untouched, so no loop identity moves. The time quadrature
is identity-bearing through the sensor's response hash
(`exposure_subsamples`).

Evidence: `tests/control/test_exposure_subsamples.py` (5 passed).
- n_sub = 1 is bit-identical, with exactly one atmosphere call per frame at
  k/f.
- The sub-samples are at t + jτ/n_sub.
- A static atmosphere gives the same frames for any n_sub (1e-12).
- Two opposite tilts in one exposure keep the mean centroid (< 5 % of the
  shift) and add exactly shift² (10 %) to the profile variance: they
  broaden rather than cancel.

Predeclared expectation for the gated 12 m run: the fastest ESO layer
(33.7 m/s) moves 6.7 cm in 2 ms, 13 % of a 0.5 m subaperture. The effect
should be small and close to an extra half-frame of delay. If it lies
within seed scatter, the default stays 1.

## DET-09 — Detector-level profiles and noise-on evidence

Status: DONE, with recorded departures. Milestones A and B are complete.
The 12 m and 42 m evidence ran on 2026-10-16 (see "Gated-run results").
The departures are:
- the predeclared @1 E3/E4/E6 runs exposed operating-flux calibration as
  the faint-star limit, so `det_emccd_12m_medium_derived@2` (with a
  calibration source) was added post hoc and rerun, with @1 kept and
  reported as predeclared;
- the limiting magnitude came out between 10 and 11, against a predicted
  11.5–12.

### Profiles (schema 7, new families, `include_noise: true`)

Generated by `scripts/generate_detector_level_profiles.py`; `--check`
verifies the packaged files, the assumption ledger and the resource
manifest. The ledgers are `benchmarks/detector_source_ledger.v1.json`
(D1–D5, D7–D9, plus R3 and R4 as contextual) and
`benchmarks/detector_level.assumptions.v1.json` (B01–B17).
`tests/io/test_detector_level_ledgers.py` checks that every value path of
every profile has a row and a matching value.

| Profile | Base | Camera | Sampling and band | Source | Gain |
| --- | --- | --- | --- | --- | --- |
| `det_ccd_2m_synthetic@1` | `fast_2m_detector@4` | `synthetic_ccd@1` | FFT pad 3, 700 nm (550–850 nm budget band), 23 px window | AB 5 | 0.2 |
| `det_emccd_2m_synthetic@1` | `fast_2m_detector@4` | `synthetic_emccd@1` | as above | AB 7 | 0.2 |
| `det_cmos_2m_synthetic@1` | `fast_2m_detector@4` | `synthetic_cmos@1` | as above | AB 5 | 0.2 |
| `det_emccd_2m_plane_synthetic@1` | `fast_2m_detector@4` | `synthetic_emccd_coupled@1` | MFT k = 4, σ_d = 0.25 px, guard 1, R3 band, 3 nodes, 21 px | AB 7 | 0.2 |
| `det_emccd_12m_medium_derived@1` | `eso_scao_medium_12m_derived@2` | `synthetic_emccd_coupled@1` | MFT k = 4, σ_d = 0.2 px, R3 band, 3 nodes, 15 px | AB 8 | 0.3 |
| `det_ccd_42m_r3band_derived@1` | `eso_drm_42m_scao_derived@2` | `synthetic_ccd@1` (3 e⁻, R3) | MFT k = 2, σ_d = 0.2 px, R3 band, 3 nodes, 15 px | 1e5 detected e⁻ (R4) | 0.3 |

The profiles load offline from an installed wheel:
`tests/test_wheel_install.py::test_direct_wheel_and_sdist_wheel_have_identical_installed_contract`
loads, round-trips and hashes every packaged profile outside the checkout.
No existing identity moved (DET-01).

### Evidence

- **E1, centroid-noise curves** (`scripts/run_detector_level_evidence.py e1`,
  50 s; [`det07_e1_centroid_noise.json`](detector_level_evidence/det07_e1_centroid_noise.json)).
  Setup: the three packaged camera presets, a 15 px window, a 1.2 px
  Gaussian spot, fluxes from 10 to 10⁵ e⁻, estimated masters (32 frames
  each), and 10⁴ temporal trials with fixed masters per point (4000 for the
  thresholded and clipped variants).
  - **Supported domain.** Measured/model is within 1.1–2.1 % for every
    camera, with and without a 5 e⁻/px background.
  - **Calibration ensembles** (200 regenerated masters at 300, 3000 and
    30 000 e⁻): measured/model 0.97–1.04.
  - **Outside the domain** (flagged unsupported), the measured departures
    are:
    - SNR_T < 7 (10–100 e⁻): scatter up to 44× the first-order value
      (125× for the EMCCD at 10 e⁻), invalid fractions up to 0.48;
    - EMCCD register saturation at 10⁵ e⁻: 1.28×;
    - thresholding at 20 % of the peak: 0.02–9.4× (switching noise
      dominates at high flux);
    - negative clipping: 0.02–0.94× (scatter suppressed by a bias toward
      the window centre).
  - **Slopes.** The high-flux log σ–log F slope is −0.72 (CCD), −0.62
    (CMOS) and −0.40 (EMCCD, flattened by register saturation). The CCD
    and CMOS values lie between the photon (−1/2) and read (−1) limits,
    because a 225-pixel window keeps read noise significant to about 10⁴
    e⁻. No slope is imposed across regimes.
- **E2, open-loop noise propagation** (`… e2`, 132 s;
  [`det09_e2_noise_propagation.json`](detector_level_evidence/det09_e2_noise_propagation.json)).
  All four 2 m profiles, with a static residual of 73.8 nm rms, the loop
  open, fixed masters, fixed rows (0 of 4000 trials excluded) and a fixed
  TSVD R:

  | Profile | Slope var. ratio, mean [min, max] | Command var. ratio, mean [min, max] | Trace ratio |
  | --- | --- | --- | --- |
  | CCD | 1.004 [0.965, 1.043] | 0.998 [0.963, 1.026] | 0.998 |
  | EMCCD | 0.998 [0.952, 1.072] | 0.984 [0.940, 1.017] | 0.984 |
  | CMOS | 1.002 [0.959, 1.051] | 0.997 [0.966, 1.031] | 0.997 |
  | EMCCD plane | 0.996 [0.945, 1.060] | 0.996 [0.957, 1.034] | 0.996 |

  - The relative standard error per entry is 2.2 %, and every entry lies
    within ±3.3 SE.
  - The declared tolerance (5 % on the means and the trace, 10 % per
    entry) is met.
  - Between-lenslet covariances are consistent with zero: max |c|/SE is
    3.0–3.9 over about 860 pairs.
  - The software check R·Σ_meas·Rᵀ equals the measured command covariance
    to 4×10⁻¹⁵. As the prompt notes, that is an integration check, not
    detector evidence.
  - Row masks: the gates use model expectations (declared), so for a
    fixed residual the row mask is fixed by construction. Rows change only
    through the residual (closed loop) or a non-finite centroid. The
    varying-row effect therefore belongs to the closed-loop evidence. No
    separate fixed-residual varying-mask test exists, because the design
    does not produce one.
- **Closed loop over independent realizations, 2 m** (`… ensemble`, 47 s;
  [`det09_closed_loop_ensemble_2m.json`](detector_level_evidence/det09_closed_loop_ensemble_2m.json)).
  Root seeds 11–15 redraw the atmosphere, detector temporal noise,
  persistent maps and calibration products. Each run is 60 frames, and the
  metric is the second-half post-update residual.

  | Profile | Mean ± seed std | Valid fraction | Per seed |
  | --- | --- | --- | --- |
  | CCD | 316.5 ± 55.0 nm | 1.000 | 274.8, 408.7, 322.5, 298.7, 277.8 |
  | EMCCD | 316.1 ± 54.6 nm | 1.000 | 275.6, 407.9, 321.5, 298.1, 277.5 |
  | CMOS | 316.6 ± 54.8 nm | 1.000 | 275.0, 408.3, 323.0, 298.7, 277.9 |
  | EMCCD plane (MFT, diffusion, coupling, 3 λ) | 313.8 ± 54.8 nm | 1.000 | 272.8, 405.6, 320.0, 296.1, 274.4 |
  | reference `fast_2m_detector@4` (noiseless, gain 0.32) | 310.0 ± 54.5 nm | 1.000 | 265.2, 401.8, 313.9, 293.4, 275.8 |

  - Every loop holds lock with a stability margin: max |pole| 0.72 at gain
    0.2 and L = 2.
  - The seed scatter (about 55 nm) comes from the atmosphere. Paired by
    seed, the noise-on loops are 2–10 nm above the noiseless reference,
    but they also run a lower gain (0.2 against 0.32). The difference is
    therefore not attributed to detector noise alone.
  - At these bright settings the 5×5 DM's fitting error dominates.
- **Gain scan**: see "DET-09 gain-scan result" above.
- **E3, magnitude scan (12 m)**: NOT_RUN_RESOURCE_POLICY.
- **E4, camera comparison (12 m)**: NOT_RUN_RESOURCE_POLICY.
- **E5, 2000-frame noise-on 42 m run**: NOT_RUN_RESOURCE_POLICY.
- **E6, effect sizes (12 m)**: NOT_RUN_RESOURCE_POLICY.
- **E2 at 12 m**: NOT_RUN_RESOURCE_POLICY.

  Each of these needs the user's enablement of a concrete run. The
  estimates are under "Gated runs" below.

### Gated runs: configurations, estimates and commands

The estimates come from measured costs. The ci tier with the 12 m physics
measures 29.8 ms of SH time per frame for 72 lenslets, which scales to 416
(12 m) and 5112 (42 m) lenslets. Prompt section 2.5 gives the legacy costs
(12 m: 0.11 s/frame at 301 MiB; 42 m: 1.84 s/frame at 1.64 GiB). Every run
uses 2 threads and writes to `docs/refactor/detector_level_evidence/`.

| Run | Configuration | Est. wall time | Est. peak RSS |
| --- | --- | --- | --- |
| E2 at 12 m | `det_emccd_12m_medium_derived@1`, 4000 open-loop trials | ~12 min | ~0.4 GiB |
| E3 | the same, 6 magnitudes (AB 6–11) × 5 seeds × 400 frames | ~60–75 min | ~0.4 GiB |
| E4 | 3 cameras × 3 magnitudes × 3 seeds × 400 frames | ~55 min | ~0.4 GiB |
| E6 | integration and diffusion on/off, poly/mono, estimated/oracle, × 3 seeds × 400 frames | ~40 min | ~0.4 GiB |
| DET-08 study | n_sub = 1, 2, 4 × 5 seeds × 400 frames | ~70 min | ~0.4 GiB |
| DET-10 medium overhead | base versus working tree, `eso_scao_medium_12m_derived@2`, 200 frames × 3 | ~5 min | ~0.35 GiB |
| E5 | `det_ccd_42m_r3band_derived@1`, 2000 frames, one seed | ~1.5–2.5 h (about 2.5 s/frame) | ~2.0 GiB |

These were the estimates before enablement. The measured wall times and
peak RSS are recorded with each result under "Gated-run results"; for
example, E5 took 59 min at 1.75 s/frame and peaked at 1.61 GiB.

## DET-10 — Performance, packaging, documentation and claim

Status: DONE. The medium-tier overhead ran on 2026-10-16: +0.9 %
noiseless and +1.0 % noisy, under the 5 % limit.

- **Feature-off overhead**
  ([`det10_feature_off_overhead.json`](detector_level_evidence/det10_feature_off_overhead.json)).
  Base `37b5bd9` versus the working tree: median SH measurement time over
  5 × 40 calls, three interleaved repeats each.
  - `fast_2m_detector@4`: +1.8 % noiseless, +1.3 % noisy.
  - `ci`: +1.8 % noiseless, +1.3 % noisy.
  - `eso_scao_medium_12m_derived@2`: +0.9 % noiseless, +1.0 % noisy
    ([`det10_feature_off_overhead_medium.json`](detector_level_evidence/det10_feature_off_overhead_medium.json)).
  - The limit is 5 %. The overhead comes from validating the new optional
    `DetectorFrame`/`DetectorTelemetry` fields.
- **Feature costs**
  ([`det10_feature_costs.json`](detector_level_evidence/det10_feature_costs.json)).
  Noisy SH measurement, median of 20 frames:
  - 2 m compatibility: 7.25 ms.
  - Physical EMCCD with FFT sampling: 6.83 ms with estimated products,
    6.48 ms with oracle products. The vectorized chain is no slower.
  - MFT with k = 4, diffusion and coupling: 10.2 / 13.5 / 17.1 / 20.7 ms
    for 1 / 3 / 5 / 7 wavelengths. That is linear, about 1.75 ms per node
    for 21 lenslets.
  - Oversampling k = 1 / 2 / 4 / 8 with 3 wavelengths: 9.5 / 10.3 /
    13.8 / 23.6 ms.
  - ci: compatibility 18.4 ms; with the 12 m physics 29.8 ms.
- **Packaging.**
  - The presets, ledgers and profiles are in `benchmarks/` and
    `synthetic_presets/`, already packaged by `pyproject.toml`.
  - The resource manifest is regenerated by the profile generator.
  - `tests/wheel_smoke/manifest.json` gains the seven new self-contained
    test modules.
  - The wheel and sdist contain every new module and resource
    (`tests/test_wheel_install.py`, `tests/test_refactor_contract.py`).
- **Documentation.**
  - [`docs/detector_model.md`](../detector_model.md).
  - README section "Detector-level camera model", with a smoke-owned
    command (`examples/run_detector_level_demo.py`: 2.8 s, 123 MiB).
  - `docs/backends.md`: physical-path scope, HCIPy fails closed, and the
    new result fields.
  - `docs/architecture.md`: the `io → detector` edge.

## Final verification (2026-10-15, working tree on base 37b5bd9, uncommitted)

These ran serially with 2 threads and without the resource guard, by the
user's instruction. Scripts: `<scratch>/final/run.sh`; batch 1 was rerun
after the fix noted below.

| Check | Result |
| --- | --- |
| Regression `-m "not hcipy and not slow and not elt_scale"`, seven batches | **2094 passed, 18 skipped, 2 xfailed, 0 failed**. By batch: 516 / 610 (+2 xfail) / 487 (+15 skipped) / 115 / 244 (+3 skipped) / 120 / 2. Longest batch 263 s; largest peak 633 MiB. The base had 1986 passed; the difference is the new tests. |
| Slow detector Monte-Carlo tests (`-m slow`, `tests/detector/test_noise_model.py`) | 13 passed (7 s, 276 MiB) |
| `ruff check src tests scripts examples build_support` | clean |
| `mypy` (project configuration) | no issues in 129 source files |
| `scripts/generate_detector_level_profiles.py --check` | profiles, assumption ledger and resource manifest match |
| Wheel and sdist (`tests/test_wheel_install.py`, `tests/test_refactor_contract.py`) | pass; every new module and resource is in both, and every profile loads offline from the installed wheel |
| `examples/run_detector_level_demo.py` | 2.8 s, 123 MiB |

Notes:
- **Flaky guard test.** In the first final batch,
  `tests/runtime/test_resource_guard.py::test_supervised_child_sees_thread_limits_before_importing_numpy`
  failed once with `peak_rss_bytes = 0`: a 0.5 s child finished between
  RSS samples while the host was under memory pressure. It passed three of
  three times in isolation and in the batch rerun. The file was not changed
  by this work.
- **Pins.**
  `tests/compat/test_phase_a_isolation.py::test_owned_examples_import_only_canonical_surfaces`
  pins the example count; it now expects 13 with the new demo. Other
  public-surface pins were extended additively, never relaxed:
  - result-field order;
  - package re-exports;
  - wheel module lists;
  - the resource count, 68 → 77;
  - the installed-profile list;
  - packaged profile identities: six new pins, and the 26 existing ones
    are unchanged.
- **Schema 6 pins in tests.** Two existing tests build configurations in
  code at the "current" schema with even windows: the tiny systems in
  `tests/experiments/test_scao.py`, and one `clip_negative_pixels` case in
  `tests/io/test_configs.py`. They now pin schema 6, which can express
  them; schema 7 deliberately refuses even windows.
- **Not run here.** The README smoke lane (`scripts/run_readme_smoke.py`),
  HCIPy-marked tests and `elt_scale` tests.
- **Changes by others.** `docs/README.md` (one index line) and
  `docs/current_limitations.md` were added or edited outside this work
  during the session. They were left untouched.

### Rerun after the gated-run code changes (2026-10-16)

Since the run above, the code has changed in four ways:
- the faint-flux `fluxes_e` fix;
- the optional calibration source;
- `det_emccd_12m_medium_derived@2` and its pins;
- the new tests and the runner subcommands.

Everything was rerun serially with 2 threads (`<scratch>/final2/run.sh`).

| Check | Result |
| --- | --- |
| Regression `-m "not hcipy and not slow and not elt_scale"`, seven batches | **2098 passed, 18 skipped, 2 xfailed, 0 failed**. By batch: 516 / 613 (+2 xfail) / 488 (+15 skipped) / 115 / 244 (+3 skipped) / 120 / 2. Longest batch 250 s; largest peak 725 MiB. |
| Slow tests over every new detector-level test file | 13 passed (all in `test_noise_model.py`; 7 s, 339 MiB) |
| `ruff check src tests scripts examples build_support` | clean |
| `mypy` | no issues in 129 source files |
| `scripts/generate_detector_level_profiles.py --check` | profiles, assumption ledger and resource manifest match |
| `tests/docs`, `tests/test_refactor_contract.py` after the final README and docs edits | 47 passed |

## Next actions

1. Commit only with the user's authorization, as Xu Han only.
2. Optional follow-ups, outside this prompt's scope:
   - a control policy that does not latch up when the valid fraction drops
     (§2.3 excludes a control-loop redesign here);
   - a 42 m seed ensemble (needs separate enablement);
   - more 12 m seeds at m_AB = 9–10 to resolve the noise term against 1/N_e.

## Gated runs enabled (user, 2026-10-16)

The user enabled every gated run, one at a time: E2 at 12 m, the
medium-tier overhead, E3, E4, E6, the DET-08 study and E5, including the
2000-frame 42 m noise-on run (about 2 GiB, 1.5–2.5 h). The resource guard
stays suspended; runs are serial with 2 threads.

### Predeclared protocols and expectations (written before any of these ran)

Common settings for every 12 m run:
- base `det_emccd_12m_medium_derived@1`, with the changes stated per run
  made in code;
- 400 frames; burn-in 100 frames; metrics over frames 100–399;
- summary telemetry;
- independent root seeds (atmosphere, detector noise, maps and products
  all redrawn);
- long-exposure science at 2.2 µm (peak Strehl).

**E3, magnitude scan.**
- Runs: m_AB ∈ {8, 9, 10, 11, 12, 13} × root seeds 21–25.
- Expectations:
  - Detected electrons fall by 2.5× per magnitude, from about 2.5 k e⁻
    per full subaperture at m = 8.
  - The EMCCD noise term in the residual variance grows ∝ 1/N_e (F² = 2,
    sub-electron effective read noise) once it exceeds the bright-star
    floor (fitting, temporal and aliasing error). So the residual should
    stay near the m = 8 value for one or two magnitudes and then rise.
  - Lenslets fall out of the supported domain at SNR_T < 7, about 100 e⁻
    per subaperture. The valid fraction should therefore stay ≥ 0.9 down
    to about m = 11 and collapse between m ≈ 11.5 and 12.5.
  - The limiting magnitude, defined as valid fraction < 0.9 or peak Strehl
    below half its m = 8 value, is expected near m ≈ 11.5–12.
  - The total residual variance is not required to follow 1/N_e across the
    floors or a loss of lock. Departures are reported, not tuned away.

**E4, camera comparison.**
- Runs: `synthetic_ccd@1`, `synthetic_emccd@1` and `synthetic_cmos@1` at
  m_AB ∈ {8, 10, 12} × root seeds 31–33. Each has a guard of 1 and the 12 m
  optics.
- Expectations:
  - At m = 8 all three are fitting-limited and indistinguishable within the
    seed scatter.
  - At m = 12 the EMCCD gives the lowest residual and the highest valid
    fraction. The CCD (3 e⁻ read noise over a 17×17 block) is worst. The
    CMOS (1.6 e⁻ median, QE 0.7) sits between them.

**E6, effect sizes.**
- Runs at m_AB = 8, root seeds 41–43, against the baseline profile:
  1. point sampling (k = 1, σ_d = 0);
  2. monochromatic 700 nm (mono band 550–850 nm, same pixel scale);
  3. oracle in place of estimated processing.
- Expectation: every effect lies within the seed scatter at this bright
  setting. Pixel integration and σ_d = 0.2 px slightly broaden the spot,
  the polychromatic spot is about as wide as the 700 nm one, and 32-frame
  masters give a calibration sigma well below the temporal one.

**DET-08.**
- Runs: n_sub ∈ {1, 2, 4} × root seeds 51–55 at m_AB = 8.
- Expectation (recorded in the DET-08 record): small, close to an extra
  half-frame of delay. If it lies within the seed scatter, the default
  stays 1.

**E2 at 12 m.** As at 2 m, 4000 open-loop trials. Declared tolerance: 5 %
on the mean slope-variance and trace ratios, and 10 % per entry.

**E5, 42 m.**
- Run: `det_ccd_42m_r3band_derived@1`, 2000 frames, root seed 1, burn-in
  200, science at 2.2 µm, summary telemetry, regenerated atmosphere band
  coefficients.
- Expectations: lock with a valid fraction ≥ 0.98, and a residual somewhat
  above the noiseless `eso_drm_42m_scao_derived@2` reference (173 nm,
  long-exposure Strehl 0.78). The causes are:
  - the 15 px window (clipping of broad spots);
  - the R3 polychromatic band (wider spots at 0.9 µm);
  - detector noise (3 e⁻ read noise over 17² pixels with 1e5 e⁻ per
    subaperture, a small term).

  A single seed is reported as one realization, not as an ensemble.

### Gated-run results

**E2 at 12 m.**
- Run: `scripts/run_detector_level_evidence.py e2-12m`, 518 s;
  [`det09_e2_noise_propagation_12m.json`](detector_level_evidence/det09_e2_noise_propagation_12m.json).
  Setup: `det_emccd_12m_medium_derived@1` (416 lenslets, 832 rows), a
  281.7 nm static residual, 4000 trials with none excluded, fixed masters,
  fixed rows, and the fixed sparse LSMR reconstructor (with all rows valid,
  its matrix).
- Slope-noise variance, measured/predicted: mean **0.999**, range 0.919 to
  1.060 (SE 2.2 % per entry, so the extremes are −3.6 and +2.7 SE across
  832 entries).
- Between-lenslet covariance: max |c|/SE is 5.28 over about 3.4×10⁵
  pairs. The expected maximum of that many independent normal deviates is
  about 5.1, so this is consistent with zero.
- Noise-only command variance: mean ratio **1.007**, range 0.943 to 1.053;
  trace ratio **1.008**.
- The integration check (R·Σ_meas·Rᵀ) agrees to 3×10⁻¹⁵.
- Result: passes the declared tolerance (5 % on the means and the trace,
  10 % per entry).

**Feature-off overhead on the medium tier.**
- Run: base `37b5bd9` against the working tree on
  `eso_scao_medium_12m_derived@2`, median of 80 calls, three interleaved
  repeats;
  [`det10_feature_off_overhead_medium.json`](detector_level_evidence/det10_feature_off_overhead_medium.json).
- SH measurement time: noiseless 83.2 → 84.0 ms (**+0.9 %**); noisy
  102.1 → 103.1 ms (**+1.0 %**). The limit is 5 %.

**Cost of the 12 m physical path.** Measured once with a 10-frame probe:
- `det_emccd_12m_medium_derived@1` builds in 7.5 s, including maps,
  32-frame products and the sparse calibration.
- A full frame (atmosphere, SH, reconstruction, DM, science) takes
  0.177 s. The compatibility medium tier takes 0.11 s per frame (prompt
  section 2.5).
- Peak RSS: 381 MiB.

**E3, magnitude scan on `det_emccd_12m_medium_derived@1`, as predeclared.**
- Run: `… e3`;
  [`det09_e3_magnitude_scan_12m.json`](detector_level_evidence/det09_e3_magnitude_scan_12m.json).
  Root seeds 21–25, 400 frames, metrics over frames 100–399, 0.158 s per
  frame.

| m_AB | Residual (mean ± seed std) | Valid fraction | K-band peak Strehl | Lost lock |
| --- | --- | --- | --- | --- |
| 8 | 185.8 ± 6.1 nm | 0.998 ± 0.002 | 0.725 ± 0.013 | 0/5 |
| 9 | 251.7 ± 141.3 nm (seed 22: 504 nm) | 0.986 ± 0.018 | 0.710 ± 0.034 | 0/5 |
| 10 | 1858 ± 271 nm (above open loop) | 0.248 ± 0.077 | 0.005 ± 0.002 | 5/5 |
| 11, 12, 13 | refused at calibration (all 15 runs) | — | — | — |

- **Limiting magnitude** (predeclared definition: valid < 0.9 or Strehl
  below half the m = 8 value): **between 9 and 10**. The prediction was
  11.5–12. This is a departure from the prediction, and it is reported
  rather than tuned away.
- **Diagnosis** (`e3_m9_seed22_validity_diagnostic.py` and `.txt` in the
  evidence directory):
  - The departure comes from the inherited gates, not from the detector
    noise model. At m = 9, seed 22 (a strong-turbulence realization), the
    median **peak-pixel** SNR of a lenslet is about 3.8. An EMCCD spot of
    about 1 k e⁻ spreads over many 0.7 µrad pixels and has F² = 2, while
    its total SNR is about 20.
  - The `min_peak_snr = 3` gate, inherited from the 2 m point-sampled
    profiles, therefore removes 4 % of lenslets on average and up to 23 %
    in bad frames. Window clipping in the 15 px window adds 4 % (up to
    12 %).
  - At m = 10 most rows fail that gate. The reconstructor works from
    shrinking row sets, and the loop diverges.
  - From m = 11 the noiseless interaction calibration itself has no valid
    rows: in @1 the reference path observes the star at the operating
    flux (no internal source). Every run is refused before its first
    frame, with "calibration produced no rows valid across every probe
    sample".
- **Post-hoc follow-up, recorded reason (prompt §DET-09 acceptance):**
  `det_emccd_12m_medium_derived@2`.
  - It adds a bright internal calibration source (2500 detected e⁻ per
    full subaperture, no sky) for the reference and interaction
    calibration. With a source declared, the deterministic reference path
    observes the source. Noisy measurements observe the star, and the
    response identity binds the source.
  - It sets `wfs.min_peak_snr = 0`, so validity rests on the validated
    `detector_covariance_v1` domain (SNR_T ≥ 7) and `max_centroid_sigma_px`.
  - Records without a source hash exactly as before (stand-in pattern).
    All @1 config, physics, detector-config and sensor identities, the
    interaction matrix, and the noisy draws were verified unchanged.
  - E3 and E4 are rerun on @2. @1's results stand as the predeclared
    outcome. Ledger rows B18 and B19 cover the change.

**E6, effect sizes on `det_emccd_12m_medium_derived@1`, at m_AB = 8.**
- Run: `… e6`, 716 s, 437 MiB;
  [`det09_e6_effect_sizes_12m.json`](detector_level_evidence/det09_e6_effect_sizes_12m.json).
  Root seeds 41–43; post-update residual over frames 100–399.

| Variant | Seed 41 | Seed 42 | Seed 43 | Full frame |
| --- | --- | --- | --- | --- |
| baseline (MFT k = 4, σ_d = 0.2, R3 3 nodes, estimated masters) | 184.6 nm | 223.3 | 174.8 | 0.158 s |
| point sampling (k = 1, no diffusion) | 184.2 | 221.6 | 174.9 | 0.119 s |
| monochromatic 700 nm | 184.3 | 997.9 | 174.8 | 0.118 s |
| oracle masters | 184.7 | 293.9 | 174.9 | 0.144 s |

- **Seeds 41 and 43.** Every effect is below 1 nm (−0.4 to +0.1 nm),
  inside the predeclared "within seed scatter".
- **Seed 42.** This is a strong-turbulence realization. Its outcome swings
  between 222 and 998 nm with these small changes, the same gate-driven
  bifurcation diagnosed in E3. So on @1 no detector-feature effect is
  resolvable above the gating instability. The gate change affects E6, so
  E6 is rerun on @2.
- **12 m costs, full frame.** These are the medium-tier feature costs
  recorded under enablement:
  - pixel integration (k = 4) with diffusion: +39 ms (+33 %);
  - 3-node polychromatic sensing against monochromatic: +40 ms (+34 %);
  - estimated against oracle masters: +14 ms, from the calibration-ensemble
    terms of the noise model.

**DET-08, finite-exposure integration study (12 m, m_AB = 8, @1).**
- Run: `… det08`, 1858 s, 414 MiB;
  [`det08_exposure_subsamples_12m.json`](detector_level_evidence/det08_exposure_subsamples_12m.json).

| n_sub | Seeds 51 / 52 / 53 / 54 / 55 | Mean ± seed std | Paired change from n_sub = 1 | Full frame |
| --- | --- | --- | --- | --- |
| 1 | 187.0 / 180.3 / 186.8 / 187.3 / 177.3 nm | 183.7 ± 4.4 nm | — | 0.157 s |
| 2 | 183.2 / 176.8 / 183.1 / 184.1 / 174.7 | 180.4 ± 3.9 | **−3.4 ± 0.5 nm** | 0.257 s |
| 4 | 181.5 / 176.0 / 181.7 / 183.4 / 173.8 | 179.3 ± 4.0 | **−4.5 ± 0.8 nm** | 0.459 s |

- **Size.** Small, as predicted, and below the unpaired seed scatter.
  Paired by seed it is resolved and monotonic.
- **Sign.** The predeclared expectation, "close to an extra half-frame of
  delay", had the wrong sign. With n_sub = 1 the loop samples the
  atmosphere at the *start* of the exposure (t). With n_sub samples at
  t + jτ/n, the mean sample time is t + τ(n−1)/(2n): +0.5 ms for n = 2 and
  +0.75 ms for n = 4, at τ = 2 ms. Integration therefore makes the
  measurement more recent, and the temporal error falls. The improvement
  ratio, 4.5/3.4 = 1.3, is close to the time-shift ratio of 1.5.
- **Default.** The effect lies within the seed scatter and n_sub = 2 costs
  +64 % per frame, so the default stays 1 as predeclared. The docs record
  that n_sub = 1 is a start-of-exposure snapshot. DET-08 is DONE.

**E4, camera comparison on `det_emccd_12m_medium_derived@1`.**
- Run: `… e4`;
  [`det09_e4_camera_comparison_12m.json`](detector_level_evidence/det09_e4_camera_comparison_12m.json).
  The camera presets are swapped in code; root seeds 31–33.

| m_AB | `synthetic_ccd@1` | `synthetic_emccd@1` | `synthetic_cmos@1` |
| --- | --- | --- | --- |
| 8 | 196.1 ± 5.1 nm (Strehl 0.71) | 183.2 ± 3.0 nm (0.73) | 188.8 ± 2.9 nm (0.72) |
| 10 | refused at calibration (3/3) | 1875–2958 nm, valid 0.33–0.35, lost lock (3/3) | refused at calibration (3/3) |
| 12 | refused (3/3) | refused (3/3) | refused (3/3) |

- **m = 8.** Paired by seed, the EMCCD is −12.9 nm against the CCD
  (−15.4, −14.1, −9.1) and the CMOS −7.3 nm (−9.6, −7.7, −4.5). The
  predeclared expectation that all three would be indistinguishable at
  m = 8 was wrong. With about 2 k detected e⁻ per subaperture, the CCD's
  read variance over a 17×17 block (289 × 9 e⁻²) is comparable to its
  photon variance, so detector noise is not negligible even at the
  bright-star setting. The ordering EMCCD < CMOS < CCD matches the
  predicted faint-end ordering.
- **Fainter.** On @1 the gates (peak SNR, and calibration at the
  operating flux) decide every outcome at m ≥ 10, as in E3. E4 is rerun
  on @2.

**E3, magnitude scan on `det_emccd_12m_medium_derived@2`** (post-hoc
follow-up).
- Run: `… e3-v2`;
  [`det09_e3_magnitude_scan_12m_v2.json`](detector_level_evidence/det09_e3_magnitude_scan_12m_v2.json).
  Same seeds and protocol as @1.

| m_AB | Detected e⁻ (full subap.) | Residual | Valid fraction | K Strehl | Note |
| --- | --- | --- | --- | --- | --- |
| 8 | ~2.5 k | 185.7 ± 7.1 nm | 0.998 | 0.725 ± 0.015 | as @1 |
| 9 | 1012 | 186.1 ± 5.4 nm | 0.998 | 0.725 ± 0.011 | @1 seed 22 bifurcation removed (192 nm, was 504) |
| 10 | 403 | 189.3 ± 6.2 nm | 0.998 | 0.718 ± 0.013 | locks (@1 collapsed) |
| 11 | 160 | 1897 ± 191 nm | 0.13 ± 0.17 | 0.002 | loses lock, worse than open loop |
| 12, 13 | 64, 25 | 1316 ± 111 nm (= open loop) | 0.000 | 0.019 | no lenslet valid; the DM stays flat |

- **Limiting magnitude (predeclared definition): between 10 and 11.** The
  prediction was 11.5–12.
- **Noise variance.** Paired by seed against m = 8, the added residual
  variance is 127 ± 524 nm² at m = 9 and 1324 ± 509 nm² at m = 10 (2.6σ).
  The m = 9 value is consistent within 0.8σ with the 1/N_e expectation
  scaled from m = 10 (about 530 nm²). The isolated noise term is resolved
  only at m = 10, so the scan does not test the 1/N_e law beyond that. No
  law is imposed.
- **Diagnosis of the m = 11 failure** (`e3_v2_snr_diagnostic.py`/`.txt`):
  - At m = 11 the model admits 95–98 % of lenslets at a static residual,
    including the full 1.25 µm open-loop residual: SNR_T median 8.4–8.6,
    σ 0.18–0.28 px.
  - Only partially illuminated edge lenslets (about 5 %) fall below the
    SNR_T ≥ 7 floor.
  - The per-lenslet gates alone therefore do not explain the observed 0–36 %
    valid fraction. The collapse is a closed-loop effect; the hypothesis is
    tested below.
  - At m = 12 (SNR_T ≈ 5.2) no lenslet is in the supported domain, so no
    correction is applied. This is the safe outcome.

**E4, camera comparison on `det_emccd_12m_medium_derived@2`** (post-hoc
follow-up).
- Run: `… e4-v2`;
  [`det09_e4_camera_comparison_12m_v2.json`](detector_level_evidence/det09_e4_camera_comparison_12m_v2.json).
  Root seeds 31–33.

| m_AB | `synthetic_ccd@1` | `synthetic_emccd@1` | `synthetic_cmos@1` |
| --- | --- | --- | --- |
| 8 | 195.2 ± 6.0 nm, Strehl 0.710 | **183.5 ± 2.7 nm, 0.732** | 188.5 ± 2.0 nm, 0.722 |
| 10 | no valid lenslet, DM flat (1487 nm = open loop) | **186.3 ± 1.3 nm, 0.726, valid 0.999** | loses lock: 2650 ± 334 nm, valid 0.03 |
| 12 | no valid lenslet | no valid lenslet | no valid lenslet |

- **m = 8, paired by seed.** The EMCCD is −11.7 nm against the CCD
  (−15.6, −10.2, −9.3) and the CMOS −6.7 nm (−11.3, −3.8, −4.9). This
  reproduces @1 within its seed scatter.
- **m = 10.**
  - The EMCCD is the only camera that keeps correcting. This is the
    predicted faint-end ordering, EMCCD < CMOS < CCD.
  - The CCD's read noise puts every lenslet below the SNR_T ≥ 7 floor:
    about 360 e⁻ against 289 × 9 e⁻² gives SNR_T ≈ 6.6. No correction is
    applied, which is the safe outcome.
  - The CMOS sits just above the floor and loses lock. This is the same
    closed-loop collapse as the EMCCD at m = 11, tested below.

**E3 at m_AB = 11, closed-loop dynamics**
(`e3_v2_m11_dynamics_diagnostic.py`/`.txt`; @2, seed 21, 400 frames, run
once with leak 0 and once with leak 0.02).
- **The loop first closes.** At frames 20–40 the residual is 225 nm with a
  valid fraction of 0.95.
- **Then it latches up.** An excursion at frames 40–70 drops the valid
  fraction below the reconstructor's `min_valid_fraction = 0.5`. The
  controller then holds the DM frozen in a bad shape: the applied commands
  stay unchanged from frame 50 to 320. The residual grows with the
  evolving atmosphere, 1.18 → 1.82 µm, and the loop never recovers.
- **A leak of 0.02 softens it.** The residual over frames 100–399 falls
  from 1.69 to 1.09 µm, with partial recovery cycles (valid 0.35–0.50), but
  the collapse is not prevented.
- **The trigger is not isolated.** During the excursion the commands of
  weakly sensed actuators (below the median interaction-matrix column norm)
  grow by 30 % and those of well-sensed actuators by 19 %. That is
  consistent with noise-driven excursions near the SNR_T floor.
- **Conclusion.** The m = 11 limit is set by the noise level (SNR_T ≈ 8.6)
  *combined with* the freeze-on-invalid control policy. The prompt (§2.3)
  excludes a control-loop redesign, so the policy is not changed here; it
  is a follow-up. The CMOS collapse at m = 10 sits at a similar SNR_T.

**E6, effect sizes on @2** (post-hoc rerun).
- Run: `… e6-v2`, 709 s, 473 MiB;
  [`det09_e6_effect_sizes_12m_v2.json`](detector_level_evidence/det09_e6_effect_sizes_12m_v2.json).
  m_AB = 8, root seeds 41–43.

| Variant | Seed 41 | Seed 42 | Seed 43 | Paired effect against baseline | Full frame |
| --- | --- | --- | --- | --- | --- |
| baseline (MFT k = 4, σ_d = 0.2, 3 nodes, estimated masters) | 185.0 nm | 226.5 | 175.3 | — | 0.157 s |
| point sampling (k = 1, no diffusion) | 184.8 | 237.3 | 175.1 | −0.2, **+10.9**, −0.3 nm | 0.117 s |
| monochromatic 700 nm | 185.2 | 223.9 | 174.5 | +0.2, −2.6, −0.8 nm | 0.117 s |
| oracle masters | 184.1 | 236.6 | 174.6 | −0.9, **+10.1**, −0.7 nm | 0.143 s |

- **Seed 42.** The @1 bifurcation is gone: the worst case was 998 nm and is
  now 237 nm.
- **Seeds 41 and 43.** Every effect is below 1 nm.
- **Interpretation.** In the strong-turbulence seed 42 (valid 0.985–0.987,
  so about 1.5 % of lenslets are removed by window clipping in the 15 px
  window), the outcome still varies by ±10 nm across variants. The signs do
  not follow the physics in any consistent way: oracle masters come out
  worse than estimated ones. The ±10 nm is therefore realization
  sensitivity, not a resolved feature effect.
- **Result.** No detector-feature effect larger than about 1 nm is resolved
  at m = 8 with three seeds, as predeclared. Pixel integration with
  diffusion and the 3-node band cost +34 % per frame at 12 m.

**E5, 2000-frame noise-on 42 m run.**
- Run: `… e5`, 3542 s, peak RSS **1.61 GiB**;
  [`det09_e5_42m_noise_on.json`](detector_level_evidence/det09_e5_42m_noise_on.json).
  Setup: `det_ccd_42m_r3band_derived@1` (84×84 SH with 5112 lenslets,
  85×85 DM), the R3 band with 3 nodes, MFT k = 2 with σ_d = 0.2 px, a
  synthetic CCD with 3 e⁻ read noise, 1e5 detected e⁻ per subaperture,
  32-frame estimated masters (16 frames per product), root seed 1, burn-in
  200, regenerated atmosphere band coefficients, summary telemetry.
- Cost: the build (maps, products and sparse calibration) took 27 s; the
  loop ran at **1.75 s per frame**.
- Residual: open loop 1683 nm → **173.2 nm** (final frame 169.1 nm).
- Valid fraction: mean 0.9992, minimum 0.994. The reconstruction was usable
  in every frame, and the loop did not lose lock.
- Long-exposure science at 2.2 µm: peak Strehl **0.753** (on-axis 0.753),
  FWHM 0.93 λ/D.
- Against the noiseless `eso_drm_42m_scao_derived@2` reference (173 nm,
  Strehl 0.78, also one realization), the residual is the same. The Strehl
  is 0.03 lower, within the predeclared "somewhat above / below"
  expectation. The window, band and detector effects are not separable
  with one seed.
- Multi-seed 42 m runs were not enabled (prompt: separate enablement).

### Predeclared expectations against outcomes

| Run | Expectation (written before the run) | Outcome |
| --- | --- | --- |
| E2 at 12 m | covariance ratios within 5 % (mean), 10 % (entry) | slope-variance ratio 0.999 (0.919–1.060 per entry), trace 1.008: **met** |
| E3 | flat to about m = 9–10, limit near m ≈ 11.5–12 | @1: limit between 9 and 10 (operating-flux calibration); @2: flat to m = 10 (185.7 → 189.3 nm), limit between 10 and 11: **earlier than predicted** |
| E4 | indistinguishable at m = 8; EMCCD best at the faint end | m = 8: EMCCD −11.7 nm against the CCD and −6.7 nm against the CMOS, paired (**not** indistinguishable); m = 10: only the EMCCD corrects: **ordering met** |
| E6 | every effect within the seed scatter at m = 8 | @2: under 1 nm in two seeds, ±10 nm unordered in the strong-turbulence seed: **met**; @1 seed 42 bifurcated |
| DET-08 | small, about an extra half-frame of delay | −3.4 and −4.5 nm (sign opposite, from start-of-exposure sampling), within the scatter: default stays 1 |
| Medium overhead | under 5 % | +0.9 / +1.0 %: **met** |
| E5 | lock, valid ≥ 0.98, residual somewhat above 173 nm | 173.2 nm, valid 0.999 (min 0.994), K Strehl 0.753 against 0.78: **met**; residual equal, Strehl 0.03 lower |
