# Development prompt: raise the Shack–Hartmann SCAO simulation to the detector level

Prepared: 2026-10-15 (Europe/Berlin)  
Repository: https://github.com/xhvoid/Shack-Hartmann-AO-Simulation  
Planning snapshot, refreshed after review: 37b5bd9 on `public-clean-main` (profile schema 6). AO-REF-016A lenslet-axis work, its revised tests, and the lower-memory HCIPy build are committed in 9352f6c, 394d175, and da189f3 respectively. This revision changes the planning document only.  
Implementation status: NOT STARTED. This document specifies future work. It is not evidence that any feature, profile, or acceptance test exists.  
Entry condition: start only after the current development is finished (section 2.4).

Desktop execution policy: DESKTOP-SAFE by default. Section 2.3 of `docs/refactor/ESO_SCAO_DEVELOPMENT_PROMPT.md` applies to this work without change, and section 2.5 below adds detector-specific limits. Medium-scale, 42 m, multi-seed, and long runs need explicit user enablement of each concrete run.

## 1. Instructions to the implementing agent

Act as an adaptive-optics scientist, detector physicist, and scientific-software engineer. Raise the repository's Shack–Hartmann wavefront sensor from an image-based sensor with an idealized noise model to a detector-level simulation in the sense defined in section 2.1. Deliver working code, independent numerical tests, versioned profiles, reproducible examples, documentation, and a durable execution record. Do not finish after producing another plan.

Read the applicable AGENTS.md and CLAUDE.md instructions and inspect the actual checkout before editing. The planning snapshot is orientation, not a requirement to reset the repository. Record the actual starting commit and worktree state. Preserve unrelated edits and untracked files. Follow explicit instructions from the human user over this prompt. Unless separately authorized, do not commit, push, tag, release, publish artifacts, or accept or overwrite governed scientific baselines. Commits, when authorized, carry only the user's authorship.

Work autonomously through implementation and resource-approved small tests. Resolve routine implementation choices within the boundaries below, record each decision, and continue. Ask the user only when a necessary decision cannot be resolved within this scope, or to enable a run gated by section 2.5.

Keep three kinds of result distinct throughout: software correctness, agreement with an explicitly declared physical model, and agreement with independent measured data. Claim only the level for which evidence exists.

## 2. Goal, claim, and scope

### 2.1 Target claim

At the planning snapshot the repository may truthfully say: "an end-to-end SCAO simulation with an image-based (pixel-level) Shack–Hartmann wavefront sensor and an optional, simplified detector noise model". This work exists to make the following statement true and evidenced:

> A detector-level Shack–Hartmann SCAO simulation: polychromatic physical-optics lenslet images integrated over declared detector pixels, with charge diffusion and declared electronic inter-pixel coupling; source and sky photometry in physical units; selectable CCD, EMCCD and CMOS camera models with shot, dark, pre-register clock-induced-charge, excess, read and quantization noise, gain, bias and separate charge/register/digital saturation; persistent detector maps tied to physical pixel identities; real-time pixel processing that uses estimated calibration frames; and noise propagation verified against analytic and Monte-Carlo references, with temporal noise distinguished from persistent calibration error and noise-on closed-loop results reported over independent realizations.

The work is complete only when each clause above has an implementation, an independent test, and evidence in the status file. If a clause is not delivered, the final wording must drop it rather than soften it with "quasi" or similar qualifiers.

The following claims remain out of bounds after this work: a digital twin of a specific commercial camera or ESO instrument, validation against ESO on-sky or laboratory data, or HCIPy parity for any feature not tested on the HCIPy backend.

### 2.2 Required scope

- Natural-guide-star, on-axis, Shack–Hartmann SCAO on the existing canonical `shwfs_ao` architecture, native backend first.
- A declared detector-plane angular pixel grid with pixel-area integration, charge diffusion, and electronic inter-pixel coupling at an explicitly stated signal-chain location.
- A polychromatic wavefront-sensor bandpass with explicit spectral weights.
- Source and sky photometry from magnitudes, spectra or filter curves, collecting area, throughput, quantum efficiency, and exposure.
- Camera models: conventional CCD, EMCCD (multiplication register and parallel/pre-register clock-induced charge), and CMOS (per-pixel offset, gain, and read-noise maps). A linear-mode avalanche-photodiode array with a configurable excess-noise factor is optional.
- Camera electronics: conversion gain, bias, fixed-pattern offsets, optional non-linearity, ADC quantization, bit depth, and separate pixel and register saturation.
- Persistent detector maps tied to immutable physical pixel IDs: hot pixels as a dark-current map, dead pixels, PRNU, and any selected electronic maps.
- Real-time pixel processing from estimated calibration frames (bias, dark, sky, flat, bad-pixel map) before centroiding.
- An extended first-order centroid-noise model, verified by Monte Carlo, feeding the existing validity gates.
- Opt-in finite-exposure integration (intensity averaging over sub-exposures) as a measured study.
- New versioned detector-level profiles with detector noise enabled, and noise-on closed-loop evidence on the 2 m and 12 m tiers, plus a gated 42 m run.

### 2.3 Explicitly outside this work

- LGS propagation, spot elongation, cone effect, tomography, MCAO, pyramid WFS promotion, spatially filtered SH, scintillation, and atmospheric dispersion.
- Fractional loop latency, a redesign of RTC timing, rolling-shutter or frame-transfer timing, and DM settling dynamics. Record the effective timing; do not silently change the integer-latency convention.
- Detector persistence, cosmic rays, brighter-fatter effects, temperature dependence, and electronic pickup patterns.
- New centroid estimators such as weighted centre of gravity or correlation. They are listed as optional follow-ons in section 11.
- Mandatory GPU dependencies or a second control loop.
- Changing the meaning, defaults, or identity of any published profile.

### 2.4 Entry gate: finish the current development first

Do not start DET-01 until all of the following hold, and record each in DET-00:

1. Confirm that the actual base contains the committed AO-REF-016A lenslet-axis work, its revised tests, and the lower-memory HCIPy build, or record the user's explicit decision to park any missing prerequisite. They are present at the refreshed planning snapshot. The worktree holds no unexplained modifications to files this work touches; record and preserve unrelated untracked planning documents.
2. The resource-approved native regression selection passes on the new base commit (`-m "not hcipy and not slow and not elt_scale"`, serialized under the resource supervisor).
3. The state of the known open items is recorded rather than resolved here: the `high_order_10m_*@3` loops are unstable (integrator gain 0.65 with `latency_frames: 2` exceeds the stability limit), and the even-window centroid bias is documented in `docs/refactor/eso_scao_evidence/published_profile_window_bias.md`. Detector-level HCIPy closed-loop claims are out of bounds until a lock-holding HCIPy profile exists. Open-loop and sensor-level HCIPy checks remain in scope.
4. The current profile schema version is read from `shwfs_ao.io.configs.PROFILE_SCHEMA_VERSION` (6 at the planning snapshot). New record fields go into the next unused version.

### 2.5 Desktop-safe execution policy (additions)

Section 2.3 of `ESO_SCAO_DEVELOPMENT_PROMPT.md` and `shwfs_ao.runtime.resource_guard` apply as written. In addition:

- Develop and test on single-lenslet fixtures, the 2 m profiles, and the `ci` tier. The 12 m `medium` tier needs user enablement per concrete run. Any 42 m run, any multi-seed batch over 30 minutes of estimated wall time, and any polychromatic run with more than 3 wavelength samples above the `ci` tier need separate enablement after the user has seen the configuration, the estimated peak memory and wall time, the thread count, and the output path.
- Monte-Carlo detector tests draw in bounded chunks of at most 64 MiB of scratch. A test that needs more than 10^6 samples per configuration needs an audited estimate.
- Measured costs at the planning snapshot, used for estimates: the 42 m tier ran 1.84 s per frame (atmosphere 0.74 s, SH measurement 0.97 s, reconstruction 0.027 s, DM 0.004 s, science 0.091 s), 2000 frames in 62.1 min, 1.64 GiB aggregate peak. The 12 m medium tier ran 0.11 s per frame at 301 MiB. Per-lenslet `DetectorFrame` telemetry is about 250 MB transient per frame at 42 m.
- Every new feature defaults off. With all new features off, the SH measurement time per frame may grow by at most 5% on the medium tier, measured by repeated timing. Record the cost of each feature when it is on.

## 3. Current state and gaps at the planning snapshot

What exists and stays: diffraction lenslet spots (native per-lenslet FFT in `backends/native/shwfs.py` and batched in `backends/native/shwfs_batched.py`; HCIPy microlens array in `backends/hcipy/shwfs.py`); finite detector windows with clipping diagnostics; the AO-REF-004 detector chain in `detector/effects.py` (source and dark/background expectation, PRNU, Poisson, Gaussian read noise, full well, dead pixels, negative clipping); centre-of-gravity and thresholded centroiding in `detector/centroid.py`; validity gates and first-order centroid sigma in `detector/validity.py`; named random domains (`detector.realization`, `detector.shot_noise`, `detector.read_noise`); and calibration identities that bind the sensor's noiseless and noisy response (`sensor_response_hash`, `sensor_noisy_response_hash`).

| ID | Gap | Where it shows |
| --- | --- | --- |
| G1 | Every published profile sets `controller.include_noise: false`. The 42 m benchmark also has 0 e⁻ read noise. The only noisy closed-loop result is the 2 m study notebook. | `resources/synthetic_presets/*.json` |
| G2 | Each detector pixel is one FFT sample of the spot intensity. There is no pixel-area integration, charge diffusion, or crosstalk. | `backends/native/shwfs.py` (`lenslet_spot_from_phase`, `crop_center`) |
| G3 | One WFS wavelength. Pixel scale is tied to it through `pad_factor` (detector pixels per λ/d). | `wfs.pad_factor`, `wfs_wavelength_m` |
| G4 | The photon budget is a direct input. The only magnitude-to-photon estimate is in an example script with a 0.25 throughput placeholder. There is no sky background model. | `examples/run_public_data_overview.py` |
| G5 | Frames are floating-point electrons. There is no gain, bias, ADC, bit depth, or non-linearity, and no EMCCD/CMOS model or excess noise. | `detector/effects.py`, `DetectorConfig` |
| G6 | The centroid runs on the raw frame. The background pedestal is not subtracted, PRNU is not flat-fielded, and dead pixels are zeroed but not masked. Calibration frames are never estimated. | `wfs/shack_hartmann/measurement.py` (`estimate_centroid(frame.image_e, ...)`) |
| G7 | Defects are dead pixels and PRNU only. There are no hot pixels or fixed-pattern bias. | `detector/random.py`, `effects.py` |
| G8 | The first-order centroid sigma models source, background, and read noise only. It excludes excess noise, CIC, quantization, and calibration-frame noise, and it has no Monte-Carlo verification across regimes. | `detector/validity.py` (`centroid_quality`) |
| G9 | The atmosphere is sampled once per frame. `exposure_s` only scales dark current. | `control/loop.py`, ESO prompt A10 |
| G10 | No experiment reports noise propagation, a flux or magnitude scan, or realization statistics with noise on. | `experiments/`, `notebooks/studies/` |
| G11 | A single window-shaped persistent realization is reused for every lenslet. There is no detector-pixel layout that gives different physical pixels distinct persistent maps and calibration products. | `detector/random.py`, `wfs/shack_hartmann/measurement.py` |

## 4. Target detector chain

Select the detector response model explicitly. An absent physical-camera block selects the unchanged AO-REF-004 compatibility path. A versioned `ccd`, `emccd`, or `cmos` block selects the new physical camera path below. `ccd` is not the compatibility default. "Every new feature off" means the compatibility response path, no new optics/photometry/pixel-processing blocks, exposure sub-samples = 1, and the historical telemetry behavior. It does not mean setting optional parameters to zero inside an enabled physical-camera block.

The compatibility path preserves its exact stage order, random-draw consumption, photon-budget-`None` branches, adapter noise-off bypasses, hash omissions, and defaults. Its PRNU-after-background and full-well-after-read operations remain frozen compatibility behavior. The physical path uses the following declared order:

```text
residual OPD (m)
→ per-wavelength phase 2π·OPD/λ_j                                    [DET-04]
→ lenslet focal field on an oversampled angular grid (MFT)            [DET-03]
→ |E|², detected-electron-weighted spectral sum Σ_j w_j·I_j           [DET-02, DET-04]
→ charge diffusion on the sub-pixel expectation grid                  [DET-03]
→ pixel-area integration onto the declared pixel grid                 [DET-03]
→ source-electron expectation from photometry; + sky-electron expectation (QE already applied once)   [DET-02]
→ optical PRNU and dead-pixel photoresponse                           [DET-05]
→ + dark-current map × exposure (hot pixels)                          [DET-05]
→ Poisson source/sky/dark charge; + separately sampled pre-register CIC where enabled   [DET-05]
→ pixel full-well clipping for every camera type                      [DET-05]
→ EMCCD only: multiplication register → separate register saturation  [DET-05]
→ declared electronic inter-pixel signal coupling on realized signals [DET-03]
→ read noise (per-pixel map for CMOS)                                 [DET-05]
→ declared non-linearity → conversion gain (output e⁻/ADU) → bias + fixed pattern → ADC rounding and digital clipping   [DET-05]
→ RTC pixel processing: corrected master subtraction, ADU→input e⁻, normalized flat, bad-pixel mask, threshold/clip   [DET-06]
→ centroid, centroid sigma, validity                                  [DET-07]
```

PRNU means relative optical photoresponse: it multiplies source and sky photoelectron expectations, not dark current or CIC. A dead pixel has zero optical photoresponse; its dark-current map, electronic bias, and read noise follow their separately declared settings. Dark charge and pre-register CIC have independent rates and random domains; do not include CIC in the source/dark Poisson mean and then draw it again. CIC is restricted here to parallel/pre-register charge receiving the full EM gain. In-register/serial CIC requires a separate sourced gain-mixture model and is outside the default claim.

The required crosstalk model is a declared linear electronic signal-coupling operator K acting on realized charge-equivalent signals, after pixel/register saturation and before the independent read-noise stage. This placement is a synthetic model assumption unless supported for the selected camera. It is not a universal IPC model for all three camera types. Optical/electron-collection redistribution before Poisson is a different mechanism; diffusion supplies that model here and must not be relabelled as electronic coupling. Declare boundary handling and propagate the covariance produced by K.

Negative-pixel clipping keeps its historical position in compatibility mode. In the physical path, any requested negative clipping occurs after calibrated background subtraction, including when the ADC is disabled. Raw ADC codes are clipped only to the declared digital range; physical full well and register capacity have distinct saturation flags.

Canonical units stay as defined in the ESO prompt section 5: OPD metres, phase radians, angles radians, time seconds. Distinguish incident photons, input photoelectrons, post-EM output electrons, and ADU in every interface. Conversion gain is output e⁻/ADU; processed values use input-referred electrons after division by the declared EM gain. ADU is confined to the raw readout and explicitly unit-labelled calibration products. DET-02 supplies detected electrons directly to the physical camera path; do not multiply them by `DetectorConfig.qe` again. The historical direct-photon-budget path retains its existing QE conversion.

Call `include_noise=False` the deterministic reference path. It substitutes charge means, mean CIC, mean EM gain, and zero read-noise draws while retaining maps, integration, diffusion, coupling, saturation, gain, bias, non-linearity, quantization, and processing. It is generally not the exact expected noisy response after non-linearity, saturation, rounding, or clipping, because E[f(X)] need not equal f(E[X]). Record deterministic versus stochastic stages and reference-path approximations in DET-00. Gamma multiplication is used only in its declared high-gain regime; unity gain is deterministic multiplication, with no added multiplication noise.

## 5. Sources and assumption policy

Reuse source IDs R1–R4 from `ESO_SCAO_DEVELOPMENT_PROMPT.md` section 3 without merging their settings under one label. R3 supplies the contextual SCAO sensing band (0.6–0.9 µm), 2 ms integration, and 3 e⁻ read noise. R4 supplies 10^5 photons per frame per subaperture. Each value used gets its own ledger row with its own source ID.

Add new source IDs (D-series) for detector physics. Candidate references; verify bibliographic details and record exact locators before use:

- D1: Basden, Haniff & Mackay 2003, MNRAS 345, 985 — EMCCD output statistics and photon-counting strategies.
- D2: Robbins & Hadwen 2003, IEEE Trans. Electron Devices 50, 1227 — EMCCD excess-noise factor.
- D3: Janesick 2007, *Photon Transfer*, SPIE Press — conversion gain, read noise, PRNU, and fixed pattern.
- D4: Thomas et al. 2006, MNRAS 371, 323 — Shack–Hartmann centroid noise and thresholding.
- D5: Oke & Gunn 1983, ApJ 266, 713 — AB magnitude zero point.
- D6: any public camera datasheet used for a preset. Without D6, a preset is `synthetic_assumed` and must not carry a commercial camera name.
- D7: [EMVA Standard 1288, Release 4.0 Linear](https://www.emva.org/wp-content/uploads/EMVA1288Linear_4.0Release.pdf), sections 2–4 — photon/electron units, gain, physical versus digital saturation, PRNU, and dark nonuniformity. Its linear independent-noise model does not establish EMCCD or coupled-pixel validity.
- D8: [Kannawadi et al., The Impact of Interpixel Capacitance in CMOS Detectors on PSF shapes and Implications for WFIRST](https://arxiv.org/abs/1512.01570) — electronic coupling and noise covariance; record the selected camera model's placement separately.
- D9: [STScI STIS calibration steps](https://hst-docs.stsci.edu/stisdhb/chapter-3-stis-calibration/3-4-descriptions-of-calibration-steps) and [Astropy calibration of dark images](https://www.astropy.org/ccd-reduction-and-photometry-guide/v/2.0.0/notebooks/03-05-Calibrate-dark-images.html) — corrected calibration products and propagated flat/background errors. These are method references, not validation against instrument data.

Create a machine-readable detector assumption ledger in the same format as the ESO ledger. At minimum close: B01 camera response model, parameters, supported EM-gain regime, and CIC location; B02 pixel scale and window field of view; B03 optical oversampling factor; B04 charge-diffusion sigma and electronic coupling kernel, placement, and boundary policy; B05 WFS bandpass, wavelength quadrature, and detected-electron spectral weights; B06 source spectrum or magnitude system, collecting area, throughput, and QE accounting; B07 sky surface brightness; B08 calibration-frame counts, calibration-source flux, product definitions/units, and shared input frames; B09 bad-pixel detection thresholds; B10 finite-exposure sub-sample count; B11 controller gain selection protocol for noise-on profiles; B12 detector-pixel layout, immutable pixel IDs, and lenslet/window mapping; B13 whether gain is known or estimated and how EM/input-electron conversion is applied; B14 uncertainty-model validity domain and treatment of temporal versus persistent calibration error. Distinguish a measured zero from an unknown value.

## 6. Repository seams and constraints

Read first: `docs/architecture.md`, `docs/backends.md`, `docs/validation.md`, `docs/reproducibility.md`, `docs/refactor/AO_REF_004_DETECTOR.md`, `AO_REF_005_SHACK_HARTMANN.md`, `AO_REF_007_INTERACTION_MATRIX.md`, `AO_REF_016_HCIPY_SHWFS.md`, `AO_REF_016A_HCIPY_LENSLET_AXIS.md`, `ESO_SCAO_DEVELOPMENT_PROMPT.md`, and `ESO_SCAO_DEVELOPMENT_STATUS.md`.

| Area | Owner / seam | Constraint |
| --- | --- | --- |
| Detector configuration | `detector/config.py` (`DetectorConfig`, `DetectorPreset`) | Historical field order is a compatibility contract. Add trailing, opt-in fields whose defaults hash identically, following the `prnu_mode` precedent. |
| Detector realization | `detector/random.py` (`DetectorRealization`) | Physical camera maps use immutable detector pixel IDs and a declared lenslet/window layout; distinct physical pixels must not alias the same window map. New maps draw only from `detector.realization`, with keys independent of lenslet order and batch size. The realization hash covers layout and settings that determine maps. Preserve the old shared-window realization only in compatibility mode. |
| Frame effects | `detector/effects.py` | Preserve existing draws and ordering in the compatibility path; version and hash the physical response path separately. `_noiseless_response_identity` assumes effects commute with the source scale. Quantization, non-linearity, and saturation break that, so bind the absolute scale when needed. |
| Frame type and telemetry | `core/types.py` (`DetectorFrame`, `DetectorTelemetry`, `DetectorPlaneSampling`) | Additive optional fields only. Add a telemetry level so full-scale runs can keep summaries instead of per-lenslet frames. |
| Centroid and validity | `detector/centroid.py`, `detector/validity.py` | Existing `uncertainty_model` identifiers keep their equations. The extended model gets a new identifier. |
| SH measurement | `wfs/shack_hartmann/measurement.py`, `calibration.py` | Pixel processing sits between the detector frame and `estimate_centroid`. Reference centroids and interaction matrices pass through the identical processing. |
| Optics | `backends/native/shwfs.py`, `shwfs_batched.py`, `backends/hcipy/shwfs.py` | The default FFT path stays bit-identical. HCIPy requires `detector_window_px == pupil_pixels // lenslets_across`. Unsupported HCIPy features fail closed with a factory error. |
| Spectral sampling | `science/bandpass.py` | Reuse `ScienceBandpass` quadrature, or move shared spectral sampling to `core` in DET-00. Detector code must not import `io.public_data`. |
| Profiles and identity | `io/configs.py`, `resources/synthetic_presets/`, `resources/resource_manifest.json` | New fields only in the next schema version. Every published profile hash and observing-condition identity stays unchanged. |
| Calibration identity | `calibration/interaction.py` | Bind camera-response version, layout/maps, input-electron scale where relevant, and fixed calibration-product content into the appropriate response identities. Distinguish the response conditional on fixed masters from the distribution over regenerated masters. Preserve the legacy PRNU-seed dependence on the whole detector configuration. |
| Random streams | `core/random.py` | Register new domains (for example `detector.em_gain`, `detector.cic`, `detector.calibration_frames`). Adding a domain must not shift any existing domain's draws. |
| Scalable path | `wfs/shack_hartmann/compact_geometry.py`, `shwfs_batched.py`, `calibration/sparse.py` | Each new feature either works on the scalable path or fails closed there. The 42 m evidence in DET-09 needs the features it uses to work there. |

## 7. Execution ledger and dependency order

At implementation start, create `docs/refactor/DETECTOR_LEVEL_DEVELOPMENT_STATUS.md` and record evidence there with the ticket IDs below. Size is relative implementation effort (S: about one focused session; M: several sessions; L: the largest items). Compute impact is per frame with the feature on, relative to the planning snapshot.

| Ticket | Work package | Depends on | Size | Compute impact | Milestone |
| --- | --- | --- | --- | --- | --- |
| DET-00 | Entry gate, baseline audit, decisions, ledgers | None | S | none | A |
| DET-01 | Schema, identity, random-domain, and telemetry design | DET-00 | M | none | A |
| DET-02 | Source and sky photometry | DET-01 | S | none | A |
| DET-05 | Camera models and electronics | DET-01 | M | a few % at 42 m | A |
| DET-06 | RTC pixel processing with estimated calibration frames | DET-05 | M | calibration cost plus per-frame correction | A |
| DET-07 | Extended centroid-noise model and Monte-Carlo verification | DET-05, DET-06 | M | bounded covariance/quality evaluation | A, B |
| DET-03 | Detector-plane sampling: MFT, pixel integration, diffusion, crosstalk | DET-01, DET-05 | L | +10–50 % SH time (estimate) | B |
| DET-04 | Polychromatic WFS | DET-02, DET-03 | L | SH time × number of wavelengths (3–7) | B |
| DET-08 | Finite-exposure integration study (opt-in) | DET-03 | S | atmosphere + SH × sub-samples | B |
| DET-09 | Detector-level profiles and noise-on evidence | A: DET-02, 05–07; B: also DET-03, 04 | L | multiplied by realizations | A, B |
| DET-10 | Performance, packaging, documentation, claim | DET-09 | M | none | A, B |

Milestone A (camera and noise) is useful on its own and costs little compute. On completion it supports the wording "image-based SH-WFS with a detector-level camera and noise model". Milestone B adds the detector-plane optics and supports the full claim in section 2.1. Treat B as required for this prompt's definition of done.

For DET-09/DET-10, Milestone A records partial evidence: the selected monochromatic 2 m camera/noise profiles and noise-on closed loops, the applicable E1/E2 checks, packaging, cost, and documentation for that limited claim. The R3-band 42 m profile, polychromatic/integration effect comparisons, and full detector-level claim belong to Milestone B. Keep these two tickets IN_PROGRESS with explicit A/B evidence subsets until the full required scope is delivered; resource-gated runs retain the status and claim limits in sections 9–10.

DET-07 first validates the Milestone A camera/processing models with identity coupling. In Milestone B, extend and rerun its covariance tests for DET-03's nonzero electronic coupling and DET-04's spectral model before DET-09/DET-10 can support the full claim. Cache fixed operators and use sparse/local covariance structure where appropriate; do not require a dense full-detector covariance allocation per frame.

Independent tickets may be implemented in parallel with explicit file ownership. Scientific and test execution stays serialized under section 2.5.

Each ticket record contains: status (TODO / IN_PROGRESS / DONE / BLOCKED / IMPLEMENTED_VALIDATION_PENDING), dates, actual base revision, changed files, decisions, exact validation commands, pass/fail/skip/resource-deferred counts, numerical results with tolerances, artifact paths and hashes, limitations, and the next action. DONE requires its acceptance evidence.

## 8. Ticket specifications

### DET-00 — Entry gate, baseline, and decisions

Actions:

1. Verify and record every condition in section 2.4: base commit, worktree state, Python and dependency versions, host memory, the regression result, and the current profile schema version.
2. Record baseline costs on the 2 m profiles and the `ci` tier: per-frame atmosphere, SH optics, detector effects, centroiding, reconstruction, and science time, plus peak RSS. Reuse the 12 m and 42 m numbers from section 2.5 unless the user enables a re-measurement.
3. Create the detector source ledger (section 5) and assumption ledger (B01–B14).
4. Write a decision record covering: explicit compatibility versus physical response selection; the deterministic reference and stochastic paths (section 4); photon/electron budgets and QE ownership; detector-pixel layout and map identities; the pixel-integration and coupling methods (DET-03); the owner of shared spectral sampling; the telemetry-level contract; scale-dependent response identities; corrected calibration-product definitions and gain treatment; and the temporal versus calibration-ensemble uncertainty tests.

Acceptance:

- Every section 2.4 condition is recorded as met, or the user parked it explicitly.
- Every executable quantity planned for the new profiles has a source or an explicit assumption.
- Baseline costs are recorded with the commands that produced them.

### DET-01 — Schema, identity, random domains, and telemetry

Actions:

1. Design the new detector configuration fields as trailing, opt-in fields whose defaults reproduce the current behaviour and hash. An absent physical-camera block selects compatibility mode as defined in section 4; a versioned block explicitly selects the physical model. Group fields so a camera preset can be referenced by name and version from a profile.
2. Add the next profile schema version for the new `detector` and `wfs` fields (declared pixel scale, optical oversampling, bandpass, unit-labelled photometric budget, physical-camera block, detector layout, pixel-processing block, exposure sub-samples). Reject conflicting direct-photon and photometric-electron budget inputs. Older records keep their exact field sets and hash views, using the existing stand-in pattern (`_WfsConfigSchemaV1`–`V3`, `_AtmosphereConfigSchemaV3`).
3. Register the new random domains. Prove that existing domains draw identical sequences after registration.
4. Extend `DetectorFrame` and `DetectorTelemetry` additively (for example `image_adu`, `processed_e`, calibration-product hashes) and add a telemetry level, `full` (current behaviour) or `summary` (per-lenslet scalars only).
5. Extend `sensor_response_hash` and `sensor_noisy_response_hash` so every new setting that moves a deterministic or noise-averaged response is bound, and nothing else. Bind the response-model version, detector layout, appropriate persistent map content, and fixed calibration-product hashes. Preserve the existing `per_frame_legacy` PRNU-seed dependency on the whole detector configuration.
6. New validation for the new schema only: `exposure_s` must not exceed the frame period, and the window must be symmetric about the optical-axis pixel (odd native window, or `lenslet_axis: "pixel_block_center"` under HCIPy). See `published_profile_window_bias.md`.
7. Declare immutable detector pixel IDs and a lenslet/window-to-pixel mapping. A documented synthetic nonoverlapping layout keyed by stable subaperture IDs is sufficient. Physical camera maps and estimated calibration products share that layout, including guard pixels used for coupling. If overlapping windows are supported, common physical pixels share one map value; otherwise reject overlap explicitly. Do not tile one window realization across all lenslets.

Acceptance:

- All packaged profile hashes, calibration hashes, response hashes, and noise-stream identities are unchanged. Assert them, don't just inspect them.
- New records round-trip. Malformed camera blocks, an exposure longer than the frame period, asymmetric windows in new records, unknown presets, and unsupported backend/feature combinations are rejected before any construction.
- Each new field changes exactly the identities it should: enabled ADC bit depth moves the response hash, telemetry level moves no physical identity, and the physical-response model and layout are identity-bearing. In persistent physical-camera mode, holding maps and calibration products fixed, changing scalar temporal read noise moves only the noisy-response hash and leaves the deterministic response and realization hashes unchanged. Preserve the legacy PRNU-seed exception. If calibration products are regenerated and their contents change, the conditioned deterministic response identity must change too.
- Fixed physical pixels retain their map values across frames, reference/interaction calibration, dense/batched execution, lenslet order, and batch size. Changing the retained-lenslet subset does not redraw pixels of an otherwise fixed layout. Multiple-lenslet and isolated-defect fixtures demonstrate that distinct pixels do not alias a repeated window map.
- Telemetry level `summary` retains only O(lenslet count) scalar diagnostics per frame, with no retained per-lenslet pixel frames or optical-spot arrays. Bound processing scratch by the declared batch size and window shape where the scalable path streams data. Account separately for persistent detector maps/calibration products, which do scale with physical pixel count; do not claim total camera memory is independent of that count. Verify allocation structure as well as RSS.

### DET-02 — Source and sky photometry

Actions:

1. Add a package-level photometry model (owner decided in DET-00) with separate outputs for incident spectral photons at the detector, detected photoelectrons per subaperture per frame before window loss/PRNU, and normalized detected-electron spectral weights. Inputs are magnitude system (AB required; Vega only with a sourced zero-point table), magnitude or spectrum, filter/bandpass curve, per-subaperture illuminated collecting area, throughput excluding QE, QE curve, and exposure. Account for pupil obstruction in the illuminated area once; do not multiply both a total collecting area and an already physical subaperture area. Take plain arrays; let `io.public_data` load catalogue rows and filter curves and pass them in.
2. Add sky background from surface brightness (mag/arcsec² in the WFS band) times pixel solid angle times subaperture area, throughput, QE, and exposure, in electrons per pixel per frame.
3. For spectral energy flux density f_λ, use N_e,a = A_a·t·∫ f_λ(λ)·T(λ)·QE(λ)·λ/(h·c) dλ. The incident-photon expression omits QE. At each quadrature node retain its nonnegative detected-electron contribution; normalize those contributions for DET-04's weights. Pass the total detected-electron budget directly into the physical camera path. The legacy direct-photon-budget interface retains its separate, single QE conversion. Do not relabel electrons as photons or apply a second scalar QE to a QE-weighted budget.
4. Move the example's estimate in `examples/run_public_data_overview.py` onto the package model, or document why it stays separate. Do not change that example's published outputs without recording the difference.

Acceptance:

- State the AB zero-point convention explicitly (3631 Jy if using the rounded convention). A flat-f_ν, top-hat, constant-throughput/QE fixture matches an independent analytic photon/electron integral to rtol 1e-12. General spectral quadrature has a separate declared convergence tolerance.
- Incident photons and detected electrons scale as 10^(−0.4 Δm), linearly with area, exposure, and throughput; only detected electrons scale with QE. Counts follow partial subaperture illumination, and window capture is applied once after the pre-window budget is established.
- A factory-to-detector integration fixture with constant QE = 0.5 yields half the unity-QE source electrons, not one quarter. A wavelength-dependent QE fixture checks both the total electron budget and spectral weights against an independent integral.
- Sky electrons per pixel scale with pixel solid angle and match a hand calculation.
- A narrow-band limit of a spectrum input reduces to the monochromatic formula.

### DET-03 — Detector-plane sampling: MFT, pixel integration, diffusion, crosstalk

Actions:

1. Introduce a declared angular pixel scale and an optical oversampling factor k. Keep `pad_factor` as the legacy monochromatic mapping (pixels per λ/d at the WFS wavelength). A new record declares either the legacy mapping or the pixel scale, not both.
2. Compute each lenslet's focal field with a matrix Fourier transform (MFT) onto a grid of k×k sub-pixels per detector pixel over the window plus a guard band. Batch it across lenslets on the scalable path.
3. Apply charge diffusion as a normalized Gaussian kernel on the sub-pixel expectation grid and integrate each k×k block into a pixel. Implement electronic coupling separately in the camera layer, at the declared post-charge/saturation and pre-read-noise point in section 4; do not convolve the expectation and then sample independent Poisson pixels as a substitute. Use a nonnegative flux-conserving coupling operator K on the supported domain. Declare guard-band extent, outward flux loss, and treatment of unmodeled neighbouring windows. Lost flux is reported, not restored by renormalizing a cropped spot.
4. A Fourier-domain pixel transfer function on a Nyquist-sampled intensity is allowed as an optimization only when it matches the oversample-and-bin reference within tolerance and the sampling is at least Nyquist. Otherwise fail closed.
5. HCIPy: implement oversampled focal sampling and binning in the adapter, or fail closed with a factory error for pixel integration, diffusion, and crosstalk. Do not silently skip the stage.

Acceptance:

- With k = 1, an integer pixel scale equal to the legacy `pad_factor` mapping, and no diffusion or crosstalk, the MFT path reproduces the existing FFT spots to rtol 1e-12 (float64, normalized intensities).
- Pixel integration of an analytic Gaussian spot matches erf pixel integrals to relative error ≤ 1e-6 at the declared oversampling. A square-subaperture sinc² spot matches an independent high-order quadrature. Results converge as k increases (k = 2, 4, 8, 16 reported).
- Flux is conserved on the represented grid: the pre-crop integrated sum equals its optical sum to 1e-12. Report finite optical-field, guard-band, and final window losses separately; unit-sum window normalization must not erase them.
- Diffusion and coupling kernels are normalized on their supported domain; identity kernels are exact identities. Diffusion's spot-width increase matches analytic Gaussian convolution.
- In an unsaturated Poisson fixture with independent read noise added after coupling, measure Cov(y) = K·diag(μ)·Kᵀ + Σ_read in charge-equivalent units, including off-diagonal entries. Verify both flat-field and localized-source cases. A reference implementation independent of the production convolution supplies K; DET-07 propagates this covariance through processing and centroiding.
- On the noiseless 2 m fixture, measure the tilt-to-centroid response before and after integration/diffusion and verify the matching interaction calibration predicts the new response. Separately report noisy-loop performance and noise amplification; recalibration is not required to recover information lost through blur or finite pixels, so a physically explained performance change is not itself a test failure.
- Cost recorded on the 2 m and `ci` tiers. The medium-tier cost is recorded only with enablement.

### DET-04 — Polychromatic wavefront sensor

Actions:

1. Sample the WFS bandpass with a declared quadrature (reuse or extend `science/bandpass.py`). Use DET-02's normalized detected-electron contributions, proportional to photon spectrum × throughput × QE × quadrature weight, without reapplying any of those factors downstream.
2. For each wavelength, convert OPD to phase, compute the MFT onto the common angular grid from DET-03, and accumulate weighted intensities. Preserve wavelength-dependent capture fractions relative to pre-window flux; do not sum independently renormalized cropped spots with pre-window spectral weights. Never average fields or phases across wavelengths.
3. Calibrate reference centroids and interaction matrices with the same polychromatic model. Record the bandpass in the response identity.
4. Check sampling at the shortest wavelength and record any aliasing margin.

Acceptance:

- A one-sample bandpass reproduces the monochromatic DET-03 output exactly.
- Spot width scales with wavelength as diffraction predicts for each monochromatic component.
- Quadrature convergence: slopes and centroid gain for 1, 3, 5, and 7 samples converge within a declared tolerance, predeclared before inspecting closed-loop metrics.
- Cost scales linearly with the number of samples, measured on the 2 m and `ci` tiers.
- The R3 band (0.6–0.9 µm) is available as a ledgered, labelled bandpass for the 42 m detector profile.

### DET-05 — Camera models and electronics

Actions:

1. Add camera types `ccd`, `emccd`, and `cmos` (optional `eapd`) as an opt-in typed physical-camera block, with versioned packaged presets that are `synthetic_assumed` unless a D6 source exists. Its absence retains the compatibility chain. All physical camera types use persistent optical PRNU, their own declared rates/maps, and the physical ordering in section 4.
2. EMCCD: independently sample parallel/pre-register CIC as a Poisson count added once before the register and pixel-capacity limit in this declared approximation; record its rate per pixel per read. For integer n > 0 input electrons, use Gamma(shape=n, scale=G) only in a declared high-gain approximation (D1); n = 0 gives exactly zero register output. Use deterministic multiplication at G = 1. Reject intermediate gains outside the approximation's supported range unless a sourced finite-stage model is delivered. The deterministic reference path uses G·n. Keep register saturation separate from pixel full well, and add output-referred read noise after multiplication and the declared coupling stage.
3. CMOS: persistent per-pixel offset, relative conversion-gain, and read-noise maps drawn from `detector.realization`, indexed by DET-01's detector pixel IDs. All camera types use that layout for PRNU, hot/dead pixels, and calibration products. Define whether a gain map changes an absolute conversion gain or is a dimensionless multiplier, and apply it once.
4. All types: hot pixels as a dark-current map (fraction and amplitude configurable), dead pixels as zero optical photoresponse, pixel full-well saturation before read noise, optional polynomial non-linearity with declared units/placement, conversion gain in output e⁻/ADU, bias plus fixed-pattern offsets, ADC rounding, and clipping to [0, 2^bits − 1]. Record pixel-full-well, EM-register, and ADC saturation separately. Physical dark/CIC rates are not multiplied by PRNU. Keep the synthetic post-read non-linearity placement in section 4 unless a separately versioned sourced model specifies another placement.
5. Vectorize the new stages across lenslets where possible. At minimum, add no per-lenslet hashing or validation inside the frame loop.

Acceptance:

- With every new field at its default and compatibility response selected, frames, draws, and stream IDs are bit-identical to the audited implementation base. The physical camera response has its own versioned identities.
- EMCCD conditional test, register alone with fixed integer n: mean = G·n and variance = n·G² for the Gamma approximation, within Monte-Carlo error. Compound test, N ~ Poisson(μ) entering the same register: mean = G·μ and variance = 2·G²·μ, giving F² = 2 in this approximation. Test at least two supported high gains and three input levels. A finite-stage alternative uses its own sourced finite-gain moments (D2). At G = 1 the register adds no variance, and n = 0 always stays zero before read noise. Disable saturation/coupling/read noise for these isolated register tests, then test the composed chain separately.
- With an overfilled source and no ADC, saturated charge is fixed at pixel full well before a final read-noise draw; measured output variance retains the configured read-noise variance. Pixel, register, and digital limits produce separate flags. A nonlinear output stage is disabled for this ordering fixture.
- Changing optical PRNU alone does not change independently specified dark/CIC expectations. Source/sky photoresponse follows PRNU; dead pixels retain their declared dark/electronic behavior.
- ADC: away from clipping, quantization error variance of a uniformly spread signal is 1/12 ADU² within Monte-Carlo error; bias is recovered; codes saturate at 2^bits − 1 and are flagged. This fixture does not establish a white quantization-noise approximation for sparse/coarsely quantized signals.
- Physical camera maps are persistent across frames, distinct pixels do not alias a repeated window map, and maps replay across dense/batched paths and batch sizes. Include one isolated hot/dead pixel and multiple lenslets with nonzero map variation.
- Hot pixels add the declared dark current and appear in the realization hash, as do layout and CMOS map settings. Changing scalar temporal read noise or a scalar conversion gain that does not generate maps leaves the realization hash unchanged. Map-generating gain/noise parameters do change it.
- Per-frame cost on the 2 m and `ci` tiers is recorded with each feature on.

### DET-06 — RTC pixel processing with estimated calibration frames

Actions:

1. Generate raw calibration frames through the same physical camera chain, layout, gain, readout, and `detector.calibration_frames` namespace, scoped by product type and frame ID with stage-specific noise domains. Frame counts and any shared input frames come from B08. Define corrected products explicitly in one recorded unit system: master bias B̂ from shuttered zero-exposure frames; master dark D̂ = mean(raw dark at operating exposure) − B̂; optional sky Ŝ = mean(raw source-off sky at operating exposure) − B̂ − D̂. With pre-register CIC enabled, B̂ includes its per-read mean; D̂ and Ŝ remove that same baseline once. Retain shared-master covariance implied by these definitions. If a different convention is used, write its algebra and prove no component is subtracted twice.
2. Form a normalized flat from uniformly illuminated frames after subtracting the matching bias/dark/sky contributions and applying the same gain/unit conversion as measurements. Normalize only over declared valid pixels and retain uncertainty from normalization. A pixel-processing stage between raw readout and `estimate_centroid` subtracts B̂ + D̂ + Ŝ once, converts ADU through the per-pixel output e⁻/ADU gain and EM gain to input-referred e⁻, divides by the normalized flat, masks bad pixels, and then applies the declared threshold/minimum-subtraction/negative-clipping policy. A disabled ADC uses equivalently labelled electron-domain products. Derive bad-pixel flags from corrected dark/flat statistics with declared thresholds.
3. State whether scalar/per-pixel conversion gain and EM gain are known engineering inputs or estimated. Known gain is permitted and must be labelled; estimated gain requires a declared independent estimation method and propagated uncertainty. Do not correct the same relative gain twice through both the gain map and flat. Reject saturated calibration frames/pixels. State the domain over which additive subtraction and multiplicative flat correction are valid with non-linearity or coarse ADC quantization; unsupported corrections fail closed or remain explicit measured limitations.
4. Provide an oracle mode using true expected additive background and the normalized deterministic uniform-illumination response, including the selected layout and response stages. With nonlinear/quantized response, estimate any claimed noisy expectation by an independent reference rather than equating it to the deterministic reference. Oracle processing does not automatically invert coupling, non-linearity, or saturation.
5. Run reference centroids and interaction-matrix calibration through the identical fixed pixel-processing products. Bind layout and calibration-product content hashes into calibration identity. Declare whether interaction calibration uses a bright internal source (flux and spectrum recorded) or the deterministic reference path. Fix estimated masters for a run; regenerating masters starts a new calibration realization and requires compatible response/interaction calibration.
6. Keep the current raw-frame centroid as the default for every existing profile.

Acceptance:

- A noiseless linear unsaturated fixture with identity coupling, ADC off, known gain, and nonzero bias/dark/sky/PRNU/EM gain (where enabled) recovers the expected input-electron signal without double subtraction or duplicate gain/QE correction. Include pre-register CIC in a separate mean-background fixture. Nonidentity coupling has its own declared processed response and is not assumed to be undone by flat-field division.
- Across independently regenerated masters, background-estimate variance scales as 1/N and follows the covariance implied by shared calibration frames. A fixed master is reused identically across a temporal sequence; its estimation error is not redrawn as independent frame noise.
- With oracle processing in a linear unsaturated regime and adequate quantization (or ADC off), background subtraction removes the pedestal-induced centroid gain loss described in `centroid_quality`'s documentation. The response to a known tilt matches the background-free response.
- On a declared uniform-illumination fixture, estimated-flat errors and the resulting centroid error match independently propagated flat/normalization uncertainty. Report their dependence on source flux and flat-frame count; finite noisy flats are not required to improve every individual realization.
- Bad-pixel handling yields a finite centroid when usable positive spot flux remains; if masking removes usable signal, return an explicit invalid measurement. Report masked fraction and propagate interpolation covariance when interpolation is selected.
- A calibration built with different calibration products is rejected for reuse.

### DET-07 — Extended centroid-noise model and validation

Actions:

1. Add a new uncertainty model identifier, keeping `first_order` and `legacy_spot_width` unchanged. Propagate the full relevant covariance through the declared response and pixel processing, then the centroid Jacobian: Σ_c ≈ J_c·Σ_processed·J_cᵀ. Include electronic-coupling covariance, per-pixel read/gain maps, background-master errors, estimated-flat and flat-normalization errors, gain-estimation uncertainty if applicable, and bad-pixel interpolation covariance. Shared calibration inputs contribute cross-covariances. Local/sparse operators and direct Jacobian contractions are sufficient; avoid a dense full-detector covariance.
2. State a limiting scalar case explicitly: before flat correction, linear unsaturated response, identity coupling, known gain/flat, independent pixels, parallel/pre-register CIC, and sufficiently sampled quantization give input-referred variance F²·(S_i + B_i + C_i) + (σ_read,i/G)² + q_i²/12. Here S_i is source photoelectrons, B_i is sky plus dark charge, C_i is pre-register CIC, G = 1 without multiplication, and q_i is the ADC step in input e⁻. Use F² = 2 only in the compound-Poisson high-gain Gamma approximation; use F = 1 without multiplication. Add estimated-master uncertainty through the processing equations, not a single background-only term.
3. For Y_i = (X_i − b̂_i)/f̂_i, with S_i = E[X_i] − b_i and nominal normalized flat f_i, first-order Var(Y_i) includes [Var(X_i) + Var(b̂_i)]/f_i² + S_i²·Var(f̂_i)/f_i⁴ when the displayed terms are independent. Add the cross-covariances when masters share frames, and retain cross-pixel terms from coupling, flat normalization, or interpolation. Distinguish temporal covariance conditional on fixed calibration products from uncertainty across independently generated products, including their persistent cross-frame effects. Centroid accuracy/bias and frame-to-frame precision must be reported separately.
4. Use processed, background-subtracted signal for flux and SNR gates when pixel processing is on. Declare whether a gate uses a model expectation or a noisy signal estimate; any estimator-based noise selection is included in Monte-Carlo validation. Flag regimes where the first-order uncertainty is unsupported instead of reporting an unjustified small sigma.
5. Build a Monte-Carlo harness over 10 to 10^5 source e⁻ per subaperture for every camera type, with and without background, thresholding, and negative clipping. Run temporal trials with fixed masters and separate calibration-ensemble trials with regenerated masters under the declared reference/interaction-calibration protocol. Include nonzero electronic coupling in Milestone B and tests with finite estimated flats. Predeclare flux/SNR ranges where linearization and white quantization-noise assumptions apply; low-SNR centroid denominators, saturation, nonlinear response, coarse quantization, and data-dependent masks require measured departures or a separately validated model.

Acceptance:

- In predeclared linear, unsaturated, stable-positive-denominator regimes, unthresholded/unclipped centroid scatter (≥ 10^4 trials per point) matches the independent first-order prediction within 10 % in photon-limited and read-noise-limited fixtures for every camera type. Expected slopes are about −1/2 and −1 in log σ versus log flux only where the corresponding noise term dominates; do not impose them across calibration-error floors or invalid low-SNR ratios.
- Finite-flat fixtures recover the signal-dependent calibration contribution and its dependence on master-frame count. Fixed-master temporal scatter and independently regenerated-master bias/covariance agree with their respective predictions; shared-master error is not treated as fresh white noise per frame.
- Coupled-pixel and interpolated-bad-pixel fixtures agree with the covariance/Jacobian oracle, including off-diagonal terms. Replacing their covariance by a diagonal approximation must measurably fail an appropriate fixture.
- Measure and report bias, scatter, invalid fraction, and selection effects outside the declared first-order domain, including thresholded, clipped, saturated, and coarsely quantized cases. Keep those cases out of a universal 10 % acceptance claim; do not hide departures by filtering failed trials through validity gates.
- Default validity decisions of existing profiles are unchanged.

### DET-08 — Finite-exposure integration study

Actions:

1. Add an opt-in sub-sample count n_sub (default 1). Sample the atmosphere at n_sub times within the exposure, compute optical intensities, average them, and apply detector noise once to the integrated expected image, not per sub-sample. Keep the DM state constant over the exposure.
2. Give the time quadrature its own model identity. The default path makes exactly one atmosphere query per frame, as now.
3. Run a predeclared comparison on the 12 m tier (with enablement) for n_sub = 1, 2, 4. The expectation, recorded before the run: the fastest ESO layer (33.7 m/s) moves 6.7 cm in 2 ms, 13 % of a 0.5 m subaperture, so the effect should be small and close to an extra half-frame of delay.

Acceptance:

- n_sub = 1 is bit-identical to the current loop, including atmosphere call counts and timestamps.
- A static atmosphere gives identical results for any n_sub. Two opposite tilts within one exposure broaden the spot, not cancel it.
- The study reports the residual change with seed scatter. If it is within scatter, the default stays 1 and the documentation says why.

### DET-09 — Detector-level profiles and noise-on evidence

Actions:

1. Publish new profile families rather than new versions of existing ones, with names that state the camera model and that the setting is derived or synthetic. For example: a 2 m CCD profile and a 2 m EMCCD profile, a 12 m medium detector profile, and a 42 m detector profile derived from the ESO benchmark with R3's band and read noise and R4's photon level, each ledgered separately. `include_noise` is true in all of them.
2. Choose each controller gain by a predeclared scan on the cheapest tier that shares the loop parameters, with the selection criterion fixed before seeing results. Check closed-loop stability numerically from the discrete-time characteristic polynomial with the declared latency, and require a margin (for example, maximum pole modulus ≤ 0.98). The `high_order_10m_*@3` profiles failed this check.
3. Run the evidence experiments:
   - E1, centroid noise curves per camera type (DET-07 harness), single-lenslet scale plus the small multiple-lenslet map/covariance fixtures. Distinguish temporal scatter with fixed masters from calibration-ensemble bias and covariance.
   - E2, noise propagation: on a static atmosphere with the loop open, use fixed row masks, fixed calibration products, and a fixed reconstructor R. Compare measured slope-noise covariance to DET-07's independent analytic/Jacobian prediction Σ_s,pred, then compare measured noise-only reconstruction covariance to R·Σ_s,pred·Rᵀ within declared Monte-Carlo/model error. Transforming a covariance measured from the same slope samples is an additional software integration check, not independent detector-physics evidence. Test data-dependent row masks separately; the fixed-R covariance identity does not cover changing reconstructor rows. Run on the 2 m system, and on the 12 m system with enablement.
   - E3, magnitude scan on the 12 m tier: at least 6 magnitudes × 5 seeds × 400 frames. Report residual RMS, long-exposure Strehl, and valid-measurement fraction against magnitude with seed scatter. Report the limiting magnitude where the valid fraction drops below 90 % or Strehl halves relative to bright-star performance.
   - E4, camera comparison (CCD, EMCCD, CMOS) at three fixed magnitudes on the 12 m tier.
   - E5, one 2000-frame noise-on 42 m run at the bright-star setting, with enablement. Multi-seed 42 m runs need separate enablement or another host.
   - E6, effect sizes: pixel integration and diffusion on versus off, polychromatic versus monochromatic, estimated versus oracle background processing, each on the 12 m tier.
4. Estimated costs, before the added detector features: E3 needs about 30 runs × 400 frames × 0.11–0.3 s per frame, roughly 20–60 min. E5 needs at least 62 min, rising to roughly 2–4 h with 3–7 wavelength samples. Re-estimate after DET-03 and DET-04 cost measurements and show the estimate when asking for enablement.

Acceptance:

- Profiles load offline from an installed wheel. No existing identity moves.
- Each experiment's configuration, seeds, commands, outputs, and artifact hashes are in the status file. Results are given with seed scatter. A gated experiment that was not run is NOT_RUN_RESOURCE_POLICY, never a pass.
- E2 agrees with the independent prediction within its declared applicability and tolerance. For E3, predeclare the expected magnitude trend and compare measured bias, residual variance, Strehl, validity, and seed scatter to it. Test 1/N_e scaling of an isolated detector-noise variance contribution only over a regime where it dominates or after separately accounting for fitting/temporal/calibration floors. Do not require total closed-loop residual variance to follow 1/N_e across those floors or a loss of lock; investigate and report departures instead of tuning the model to force monotonicity.
- No validity threshold, clipping limit, or gain is changed after inspecting the E3–E5 results without a recorded reason and a rerun of the affected experiments.

### DET-10 — Performance, packaging, documentation, and claim

Actions:

1. Measure the overhead with every new feature off, and the cost of each feature on, on the 2 m, `ci`, and (with enablement) medium tiers.
2. Package presets, ledgers, and profiles; update the wheel-smoke manifest and resource manifest checksums.
3. Write `docs/detector_model.md`: the compatibility and physical chains in section 4 with equations, photon/input-electron/output-electron/ADU units, layout/map identities, defaults, deterministic reference versus stochastic stages, corrected master definitions, conditional temporal versus calibration-ensemble uncertainty, validity limits, and the supported claim for each camera preset.
4. Update `README.md` and `docs/backends.md` with the evidenced claim. Replace "detector-level" wording that predates this work wherever it implies more than the planning-snapshot model, and use the exact claim from section 2.1 only for clauses that DET-09 evidenced.

Acceptance:

- With every new feature off, SH measurement time grows ≤ 5 % on the medium tier, or the status file explains why and the user accepts it.
- The wheel and sdist contain every new resource. Commands run from an installed wheel outside the checkout.
- README commands that are within the desktop policy run. Gated commands are labelled as such.
- The final claim wording matches the evidence, clause by clause.

## 9. Evidence matrix and test strategy

| Evidence | What must be shown |
| --- | --- |
| Compatibility | Every published profile, calibration, response, and noise-stream hash unchanged; bit-identical frames with new features off |
| Physics oracles | Analytic pixel integrals, diffusion convolution, electronic-coupling covariance, photon/electron photometry with QE once, conditional/compound EMCCD moments, charge versus ADC saturation, corrected-master and flat uncertainty |
| Pixel identity | Fixed maps/calibration products indexed by physical pixels; distinct lenslets, isolated defects, batch/order/subset invariance |
| Noise model | Monte-Carlo versus covariance/Jacobian predictions within declared regimes; fixed-master temporal scatter separated from regenerated-master bias/covariance |
| Propagation | Open-loop slope covariance and R·Σ_s,pred·Rᵀ versus independent predictions with fixed rows; varying-row effects tested separately |
| Closed loop | Noise-on profiles that hold lock with a stability margin; magnitude scan and camera comparison with seed scatter |
| Cost | Per-feature per-frame cost and peak RSS; feature-off overhead ≤ 5 % |
| Distribution | Offline wheel loading of every new profile and preset |
| Claims | Wording matches delivered and evidenced clauses only |

Use the test command templates from the ESO prompt section 8, under the resource supervisor, with the audited selection extended to `tests/detector`, `tests/wfs`, `tests/calibration`, `tests/io/test_configs.py`, and the new test modules. Put Monte-Carlo tests with more than 10^5 draws behind the `slow` marker with deterministic seeds. For every new tolerance, write the expected magnitude, the independent oracle, the discretization or Monte-Carlo error, and the reason for the threshold. Monte-Carlo tolerances derive from the sample count, not from trial and error.

## 10. Deliverables and definition of done

1. Versioned camera presets, detector source and assumption ledgers, and strict offline loading.
2. Photometry, detector-plane sampling, polychromatic sensing, camera models, pixel processing, and the extended noise model, integrated through the canonical factories on the native dense and scalable paths, with HCIPy either supported or failing closed per feature.
3. Independent tests and compatibility tests for every ticket.
4. New noise-on detector-level profiles and the E1–E6 evidence with realization statistics.
5. `docs/detector_model.md`, updated README and backend notes, and updated packaging manifests.
6. `docs/refactor/DETECTOR_LEVEL_DEVELOPMENT_STATUS.md` with no unsupported DONE entries.

Done means DET-00 to DET-10 acceptance evidence exists, with gated runs either executed under enablement or marked NOT_RUN_RESOURCE_POLICY and excluded from the claim. Never report an unexecuted run as a success.

The final agent report states what changed, why, which source or assumption applies, commands and tests actually run, measured numerical and resource results, preserved compatibility, and every remaining limitation.

## 11. Optional follow-ons

Not required for this prompt; scope separately:

- Weighted centre of gravity, correlation, and matched-filter centroiding, compared on the E3 magnitude scan.
- Fractional latency derived from exposure, readout, and compute times.
- Rolling-shutter CMOS readout.
- HCIPy closed-loop detector-level parity once a lock-holding HCIPy profile exists.
- Broadband science images (ESO prompt section 10).

## 12. Start here

Begin with DET-00. Confirm the entry gate, record the baseline, build the ledgers and decision record, then settle the DET-01 identity and schema design before any physics code. Implement Milestone A first, because it costs little compute and closes the largest gap (no noise in any published result). Then implement Milestone B. Keep the existing FFT optics and AO-REF-004 detector chain as the bit-exact oracle for the feature-off path throughout.
