# Current simulation limitations

Last reviewed: **2026-10-18** (Europe/Berlin), against revision `2312502`
during the [repository cleanup](refactor/CLEANUP_REFACTOR_STATUS.md). The
first review was on 2026-10-15, while the detector-level work was in progress.

This is a living record of the simulation's modelling assumptions, known
issues and remaining validation work. It reflects the current code, now
including the completed detector-level work and its review fixes; it is not a
new validation run or a claim that those changes have been accepted into a
release. The [technical reference](technical_reference.md) explains the
implementation, and the [roadmap](roadmap.md) lists the open tasks.

Each entry records the affected scope, its consequence and the evidence
needed to revisit it. **Assumption** means a deliberate model boundary;
**known issue** means an observed problem; **validation gap** means the
required evidence is incomplete. Next steps below are proposals, not
completed work.

## Engineering concerns raised by the project author

Source: engineering questions raised by the project author, reviewed on
2026-10-15 and summarized in English below. These questions motivated
LIM-12–LIM-16; their implementation details were checked against the current
code. The existing controller-stability and sampling gaps remain LIM-06
and LIM-07.

| Author's concern | Limitations recorded here |
| --- | --- |
| Real detector pixel counts are fixed; numerical changes must respect hardware constraints. | LIM-12: fixed hardware versus changing a numerical window or optical axis. |
| A lenslet's spot may shift outside its assigned window. How is this handled, and how are spots associated with lenslets and detector pixels? | LIM-13: spot loss, measurement range, neighbouring light and lenslet assignment; LIM-14: what clipping information is actually observable. |
| How does the current code handle invalid spot intensity? | LIM-15: zero optical flux versus an invalid centroid; LIM-16: reconstruction dropout and controller recovery limits. |

### LIM-12 — A numerical geometry correction is not a demonstrated fixed-hardware solution

- **Status:** Engineering validation gap; detector windows and lenslet alignment.
- Physical pixel count, pixel pitch and installed optical alignment constrain
  the available measurements. A symmetric 23-pixel centroid crop within an
  existing 24-pixel readout can remove the demonstrated asymmetry, but discards
  edge information; it does not establish an optimum for fixed hardware.
  Changing HCIPy's `lenslet_axis` changes the modelled optical geometry;
  redefining detector coordinates alone would not move a real optical axis.
- The physical-camera layout now has persistent pixel identities, but its
  block pitch is `window_px + 2 * guard_px`. Changing the window with guard
  size fixed also changes the synthetic physical layout, rather than merely
  selecting another ROI on an independently fixed detector.
- **Consequence / next evidence:** Hold the physical detector, readout,
  optical alignment, photon budget and input wavefronts fixed. Compare the
  existing crop with calibrated or alternative centroid estimators, measuring
  bias, noise, dynamic range and closed-loop image quality. Any optical
  realignment must be recorded as a separate hardware/design change.
- **Evidence:** [Window revision](eso_scao_benchmark.md#detector-window-revision),
  [physical layout](../src/shwfs_ao/detector/layout.py),
  [HCIPy lenslet geometry](../src/shwfs_ao/backends/hcipy/shwfs.py).

### LIM-13 — Fixed lenslet assignment does not solve spot loss or identification

- **Status:** Model boundary / validation gap; SH-WFS measurement dynamic range.
- Native optics computes lenslet spots separately, including the new
  isolated physical-camera blocks. It models window loss but omits light
  entering another lenslet's window. HCIPy propagates a shared focal-plane
  field, then assigns fixed blocks to predetermined lenslet IDs; it has no
  dynamic spot tracking or global reassignment. Light in a block therefore
  does not by itself establish which lenslet supplied it.
- A spot can become biased by truncation before its centre leaves the
  window. Crossing into a neighbouring window can produce a plausible but
  wrongly assigned measurement. Partially illuminated pupil-edge lenslets
  also require attention to flux and spot shape; the fill-fraction cut does
  not establish reliable measurement over every retained edge lenslet.
- **Consequence / next evidence:** Characterize displacement-to-measured-slope
  response on fixed hardware through clipping, crossing and spot loss,
  including noise and partial illumination. Compare fixed-window rejection
  with tracking or global matching, and measure misidentification as well
  as centroid error. Distinguish leaving a software ROI from leaving the
  entire physical detector; enlarging a crop cannot recover undetected light.
- **Evidence:** [Native batched optics](../src/shwfs_ao/backends/native/shwfs_batched.py),
  [isolated layout](../src/shwfs_ao/detector/layout.py),
  [HCIPy propagation and block extraction](../src/shwfs_ao/backends/hcipy/shwfs.py),
  [lenslet geometry and illumination cuts](../src/shwfs_ao/wfs/shack_hartmann/geometry.py).

### LIM-14 — Clipping rejection uses optical-model knowledge

- **Status:** Observability boundary; simulator diagnostics versus online WFS data.
- Compatibility measurements derive clipping from the optics-provided
  `relative_throughput`; the physical sensor likewise derives window capture
  from noiseless optical intensities before applying the camera response.
  These are not estimates recovered solely from the detected frame.
  HCIPy's window-flux/input-flux ratio is also not a photon-origin label:
  neighbouring light can mask the loss of the intended lenslet's spot.
- **Consequence / next evidence:** Current clipping-based rejection does not
  establish a deployable online spot-quality detector. Keep simulator capture
  diagnostics separate from an estimator using only available detector data
  and calibration. Compare false acceptance/rejection against simulation truth
  across flux changes, spot shapes, truncation and contamination.
- **Evidence:** [Compatibility measurement](../src/shwfs_ao/wfs/shack_hartmann/measurement.py),
  [physical window capture and validity](../src/shwfs_ao/wfs/shack_hartmann/physical_measurement.py),
  [HCIPy throughput definition](../src/shwfs_ao/backends/hcipy/shwfs.py).

### LIM-15 — Zero optical flux can abort measurement before invalid-row handling

- **Status:** Known implementation boundary; native FFT, batched FFT, MFT
  and HCIPy optics.
- A zero/non-positive or non-finite optical window total raises an optics
  error; the MFT path checks the full lenslet block. This happens before
  normal centroid validity rejection. Ordinary faint/noisy or unusable
  centroids can instead become NaN slopes with invalid measurement rows.
  A spot centre crossing a boundary need not make its integrated flux
  exactly zero; these are distinct conditions.
- **Consequence / next evidence:** The pipeline does not uniformly represent
  physical spot disappearance as a recoverable missing measurement. Define
  and test a finite zero-flux state through optics, measurement and control,
  while retaining errors for NaN/Inf or invalid numerical output. Verify the
  physical camera path separately from the compatibility path.
- **Evidence:** [Native FFT guard](../src/shwfs_ao/backends/native/shwfs.py),
  [batched FFT guard](../src/shwfs_ao/backends/native/shwfs_batched.py),
  [MFT block guard](../src/shwfs_ao/backends/native/shwfs_mft.py),
  [HCIPy guard](../src/shwfs_ao/backends/hcipy/shwfs.py),
  [physical centroid handling](../src/shwfs_ao/wfs/shack_hartmann/physical_measurement.py).

### LIM-16 — Measurement rejection is not a complete loss-of-lock recovery policy

- **Status:** Control/validation boundary; missing or rejected WFS measurements.
- Invalid slopes are masked rather than treated as zero. Reconstruction
  uses the remaining calibrated, finite rows and can reject a frame for
  insufficient usable measurements or other configured solver criteria.
  A minimum valid fraction alone does not guarantee adequate spatial
  information or accurate reconstruction for a particular dropout pattern.
- By default (no `controller.recovery` block), a rejected frame enqueues a
  zero **increment**. Previously queued increments can still execute, and leak
  still applies. Only after queued increments drain does zero leak imply
  holding the last applied command; nonzero leak decays it. This is not
  immediate DM freezing, flattening, spot reacquisition or a complete
  recovery state machine. The warning for a run with no usable reconstruction
  does not diagnose every intermittent or sustained loss-of-lock episode.
- Updated 2026-10-18: an **opt-in** schema-7 supervisor,
  `controller.recovery` (`control.ClosedLoopRecoveryPolicy`), now exists. It
  can decay or reset the requested command after a set number of consecutive
  rejected frames, reconstruct a rejected frame from its usable rows (sparse
  LSMR only, optionally guarded by actuator coverage, which is response-energy
  coverage, not a rank or observability test: GPT pre-refactor audit F-05),
  and scale increments
  by the valid fraction. It acts after the controller update and never clears
  the latency queue; the controller still synchronizes to the applied command.
  Without the block every identity and result is unchanged. At 12 m the
  improvement of `det_emccd_12m_medium_derived@3` over @2 comes mainly from
  the reconstructor damping (0.1 instead of 0.001), with the reset as a
  safety net; the reset alone left recurring excursions. The supervisor is
  still not spot reacquisition, and the evidence records' `lost_lock` flag
  (final residual above final open-loop residual) is a heuristic, not a lock
  diagnosis.
- **Consequence / next evidence:** Exercise spatially clustered dropouts,
  intermittent and sustained loss, and reacquisition. Check reconstruction
  quality, queue behaviour, actuator limits and explicit recovery criteria,
  rather than counting accepted measurements alone. The faint-end limit is
  a property of the reconstruction and control settings as well as of the
  camera (roadmap S5).
- **Evidence:** [Dense reconstructor policies](../src/shwfs_ao/calibration/reconstructors.py),
  [sparse reconstructor policies](../src/shwfs_ao/calibration/sparse.py),
  [controller queue and leak](../src/shwfs_ao/control/controller.py),
  [loop handling and warning](../src/shwfs_ao/control/loop.py),
  [recovery supervisor](../src/shwfs_ao/control/recovery.py),
  [recovery and excursion-trigger studies](refactor/DETECTOR_LEVEL_DEVELOPMENT_STATUS.md#closed-loop-recovery-policy-follow-up-2026-10-16).

## Model boundaries

### LIM-01 — No calibration against an operational AO instrument

- **Status:** Validation gap; applies to instrument-performance claims.
- DM influence functions and interaction calibration are synthetic. Detector
  presets, centroid policies and controller settings are simulation inputs,
  rather than measured calibration of a specific instrument. ESO, SVO and
  catalogue data constrain selected inputs; native/HCIPy agreement checks
  the tested numerical contracts. Neither establishes observatory performance.
- **Consequence / next evidence:** Treat results as controlled simulation
  studies. A stronger claim needs measured calibration and independent AO
  telemetry or PSFs under matched conditions, with uncertainty estimates.
- **Evidence:** [Validation scope](validation.md#explicit-limitations),
  [parameter provenance](provenance.md).

### LIM-02 — On-axis SCAO and phase-screen atmosphere

- **Status:** Assumption; applies to the time-domain SCAO framework.
- Layered turbulence sums frozen-flow von Kármán phase screens along one
  on-axis line of sight. Layer altitude is recorded but does not provide
  propagation between layers, scintillation or tomography. There is no LGS
  cone effect, sodium-layer model, multi-guide-star reconstructor or
  sky-coverage prediction. The PWFS branch remains experimental.
- **Consequence / next evidence:** These runs cannot establish off-axis,
  LGS or MCAO performance. Extending that scope needs the corresponding
  propagation, source geometry and reconstruction models plus validation.
- **Evidence:** [Atmosphere model](eso_elt_turbulence_model.md),
  [explicit scope](validation.md#explicit-limitations).

### LIM-03 — Detector geometry and backend coverage remain restricted

- **Status:** Assumption / implementation boundary; physical camera path.
- The current native implementation includes CCD/EMCCD/CMOS response,
  pixel integration, diffusion, electronic coupling, spectral sensing and
  pixel processing. Its `isolated_lenslet_blocks.v1` layout omits light
  from neighbouring lenslets and overlapping spot windows. The HCIPy
  factory rejects `detector_physics` configurations.
- **Consequence / next evidence:** Those camera results do not cover
  inter-lenslet optical contamination or establish physical-camera parity
  with HCIPy. Those claims need a shared detector-plane model and matched
  backend comparisons.
- **Evidence:** [Detector layout](../src/shwfs_ao/detector/layout.py),
  [HCIPy factory](../src/shwfs_ao/backends/hcipy/factory.py),
  [detector development record](refactor/DETECTOR_LEVEL_DEVELOPMENT_STATUS.md).

### LIM-04 — Centroid uncertainty has a limited domain

- **Status:** Assumption; uncertainty estimates depend on the selected path.
  Updated 2026-10-18: the physical path's model is now `detector_covariance_v2`.
- The compatibility estimate is a first-order plain-centroid approximation;
  thresholding, negative clipping and pixel defects can break its interpretation.
  The physical path's `detector_covariance_v2` (review 2026-10-16) linearizes
  about the mean conditional on the realized calibration masters and checks both
  ADC limits, with bias and offset maps and five temporal sigmas of headroom.
  It declares unsupported regimes and reports an undefined sigma there (the
  lenslet is then invalid): threshold/minimum subtraction, negative clipping,
  non-linearity, expected pixel/register/ADC saturation above 90 % of capacity,
  read noise below half an ADC step on a pixel that enters the centroid, or
  total-flux SNR below 7. Updated 2026-10-18 (GPT pre-refactor audit F-01):
  the quantization gate had used the scalar read noise and the largest gain
  multiplier of the whole batch (rejecting every block when it failed), so a
  CMOS read-noise map could leave contributing pixels under half a step while
  the block stayed supported; it now uses each contributing pixel's own read
  noise and step, block by block. A block that becomes unsupported reports the
  undefined sigma, so its lenslet fails the validity gate. No packaged or
  recorded configuration changes: their CMOS maps keep at least 0.65 ADU on
  every pixel (0.9055 ADU at the 2 m profile's own seed; at least 0.75 ADU
  over root seeds 1–200; 0.65 ADU on the recorded 12 m E4 arm). The half-step cut is the project's
  declared policy; Widrow et al. (1996) give σ > q as the rule of thumb, and at
  the cut the exact per-pixel white-model error is at most 2.4 %. The raw-readout case
  with a non-uniform CMOS gain map was corrected in `62c0092`. Near the SNR
  floor the first-order sigma is low by about `4/SNR_T²` (Monte Carlo, E1).
  Persistent master-frame errors are reported separately as
  `centroid_calibration_sigma_px`, a per-run bias that no gate uses.
- **Consequence / next evidence:** A reported sigma is not a universal error
  bound. Inspect validity/support flags and measure estimator bias and scatter
  with Monte Carlo tests in the regime being claimed.
- **Evidence:** [Compatibility centroid estimate](backends.md),
  [physical covariance model and gates](../src/shwfs_ao/detector/noise_model.py),
  [detector model](detector_model.md#uncertainty-model-detector_covariance_v2-det-07).

### LIM-05 — Finite-exposure sensing is optional and discretized

- **Status:** Assumption; depends on the sensor and exposure configuration.
- The default `exposure_subsamples=1` samples the atmosphere once per frame.
  Supporting sensors can average optical intensities over several exposure
  samples, with one detector-noise application and the DM held fixed. The
  frame's residual metrics still use the first atmosphere sample.
- Updated 2026-10-18 (GPT pre-refactor audit F-02): the effective
  quadrature of `control.run_closed_loop` is part of the run identity. Runs
  that differed only in `exposure_subsamples` or `exposure_s` used to share a
  `config_hash`; a multi-sample run now records the count and duration in its
  `config_hash` and `wfs_exposure` metadata, and an override of the WFS's
  configured count is recorded. Single-sample identities are unchanged.
- **Consequence / next evidence:** Default runs omit WFS temporal averaging;
  frame RMS is not exposure-averaged RMS. Claims about exposure smearing need
  convergence versus exposure subsamples and explicitly labelled metrics.
- **Evidence:** [Control-loop exposure contract](../src/shwfs_ao/control/loop.py),
  [exposure checks](../tests/control/test_exposure_subsamples.py).

## Known issues and incomplete evidence

### LIM-06 — Published high-order profiles have unstable controller settings

- **Status:** Known issue; `high_order_10m_geometric@3` and
  `high_order_10m_hcipy@3`.
- Their gain 0.65 with two frames of latency exceeds the leak-free unit-gain
  integrator limit of approximately 0.618. Both remain strict expected
  failures in the profile-stability tests. The HCIPy profile also loses
  usable measurements when broadened spots clip its narrow window.
- **Consequence / next evidence:** These versions do not demonstrate stable
  sustained correction. Revised settings need versioned profiles and locked
  closed-loop evidence. The block-centred HCIPy axis correction has locked
  reduced-grid evidence; full-profile confirmation remains separate work.
- **Evidence:** [Profile stability guards](../tests/control/test_profile_stability.py),
  [HCIPy closed-loop investigation](refactor/eso_scao_evidence/hcipy_lenslet_axis_closed_loop_192px.md).

### LIM-07 — Spatial convergence is not established at every claimed scale

- **Status:** Validation gap; ESO-derived benchmark and new detector profiles.
- The ESO smoke-tier pupil-sampling scan missed its declared 2% criterion:
  12 to 16 samples per lenslet changed mean Strehl by 2.8% and EE50 by 5.6%.
  The scan also changed WFS field of view and used unpaired atmospheric
  draws. Medium/full sampling convergence and the 8 GiB host check remain
  pending. New R3-band detector configurations record 0.857 times Nyquist
  sampling at 600 nm; avoiding a repeated Fourier field does not remove
  that undersampling.
- Updated 2026-10-18 (roadmap S3, produced by `2312502`): the paired study at
  12 m (`medium` tier; fixed WFS field of view, paired atmospheric draws, three
  realizations of 200 frames) finds peak Strehl converged in pupil, WFS and
  science sampling (finest two within 0.25 %), and EE50 converged in pupil and
  WFS sampling but not in science sampling (4.3 % between science pads 3 and
  4). Quoted EE50 values at the default science sampling are therefore
  unconverged. The 42 m scans were still running; this entry claims nothing
  about them.
- **Consequence / next evidence:** Successful execution and solver convergence
  do not establish spatial accuracy. Refine pupil, WFS and science sampling
  separately, hold physical field of view fixed, and compare matched inputs
  with sufficient statistical precision.
- **Evidence:** [Benchmark convergence record](refactor/ESO_SCAO_DEVELOPMENT_STATUS.md),
  [R3-band sampling decision](refactor/DETECTOR_LEVEL_DEVELOPMENT_STATUS.md).

### LIM-08 — Long runs and short demonstrations have statistical limits

- **Status:** Assumption / validation gap; atmosphere and performance summaries.
- The native layered atmosphere's periodic band can repeat once a layer
  travels one screen period; low-frequency modes do not share that period.
  `periodic_band_repeated` flags that travel as an advisory: an exact repeat
  needs both wind components times the elapsed time to be whole periods, as
  for the packaged axis-aligned winds (GPT pre-refactor audit F-12).
  The recorded 4 s reference run repeats the fastest periodic bands.
  Introductory studies use short trajectories and limited realizations.
- **Consequence / next evidence:** More frames do not automatically supply
  independent samples. Sustained-performance claims need burn-in, lock and
  valid-measurement diagnostics, independent seeds, uncertainty estimates and
  checks for periodic-band repetition.
- **Evidence:** [Layered atmosphere](eso_elt_turbulence_model.md),
  [study lengths and benchmark scope](../README.md).

## Interpretation and reproducibility

### LIM-09 — Error budgets and image metrics answer different questions

- **Status:** Interpretation boundary; applies to the reported workflow.
- The `fast_*` error-budget disturbance lies entirely in the DM control
  space: it has no atmospheric fitting error and no physical `r0`. Physical
  workflows include out-of-span turbulence, but their residuals combine
  fitting, sensing, reconstruction and temporal effects. Some result fields
  summarize instantaneous scalar Strehl over tail frames; those are distinct
  from metrics measured on an accumulated long-exposure image. A Maréchal
  estimate from RMS is also distinct from an image-derived peak ratio.
- **Consequence / next evidence:** State the disturbance and metric definition
  with each result. Use controlled comparisons for error attribution and an
  intensity-averaged PSF for exposure-image claims.
- **Evidence:** [Validation and budget definitions](validation.md),
  [result-field contracts](backends.md), [science metrics](ao_realistic_demo_science_metrics.md).

### LIM-10 — The TIPTOP study has its own analytical and sampling limits

- **Status:** Assumption / validation gap; Notebook 12 only.
- The TIPTOP/P3/MASTSEL study retains analytical control and independence
  assumptions and an explicitly added continuous fitting tail. It does not
  establish stability of a matched time-domain MCAO controller. Focal-pixel
  refinement covers the baseline directions, not every seeing, profile or
  guide-star configuration; finite-field halo and FWHM estimator bias remain.
- **Consequence / next evidence:** Keep these results attached to their own
  configuration and convergence record. Broader claims need refinement of
  the affected operating points and matched time-domain or measured evidence.
- **Evidence:** [TIPTOP scope and numerical limits](notebook12_tiptop_portfolio_notes.md).

### LIM-11 — Reproducibility and development status are environment-specific

- **Status:** Reproducibility / acceptance boundary. Updated 2026-10-18.
- Exact seeded arrays are guaranteed only within the frozen numerical and
  backend environment. Independent native and HCIPy screens are compared
  statistically. Timing and memory depend on the platform. Noisy interaction
  calibration replays exactly within one host but does not yet select the same
  noise streams on another host ([reproducibility](reproducibility.md#calibration)).
- The detector-level work is complete (DET-00 to DET-10, with review findings
  R1–R7, S1–S3 and the raw-readout pedestal closed), and it is committed
  locally. Those commits, and the ones after them, have not yet run in CI: on
  2026-10-18 `main` was 11 commits ahead of `origin/main`. The cleanup's entry
  check found four HCIPy-lane test failures that a stale fixture from
  `a31099b` had caused; the native selection does not run them. The local
  development environment is not the constraint lock (numpy 2.5.0 against the
  pinned 2.5.1, plus optional extras).
- Updated 2026-10-18 (GPT pre-refactor audit F-03): a resumed evidence series
  used to retain old runs under the header of the newest environment. Series
  protocol 3 makes the producing environment part of every run's protocol and
  refuses a resume under another environment or of a version-2 record, and a
  resume that would add runs while the code identity is unknown (a resume with
  nothing left to run only verifies). The bound environment is four fields:
  the Python version string, NumPy, SciPy and the machine; the BLAS/LAPACK
  backend, thread settings, OS version and optional packages are not bound.
  Version-2 records stay read-only history; their producers are not
  reconstructed.
- **Consequence / next evidence:** Record profile versions, overrides, seed,
  dependency versions and source revision/patch with results. Treat an
  implementation, a test pass and an accepted baseline as distinct evidence.
  Run every CI lane on the exact revision before quoting a result as passing
  there (roadmap G1).
- **Evidence:** [Reproducibility limits](reproducibility.md#reproducibility-limits),
  [detector execution record](refactor/DETECTOR_LEVEL_DEVELOPMENT_STATUS.md),
  [cleanup execution record](refactor/CLEANUP_REFACTOR_STATUS.md).

## Recorded results that limit claims

### LIM-17 — The 42 m noise-on result is one realization

- **Status:** Validation gap; `det_ccd_42m_r3band_derived@1`, experiment E5.
  Added 2026-10-18.
- The only physical-camera 42 m run (2000 frames, root seed 1, 173.2 nm
  residual, long-exposure Strehl 0.753 at 2.2 µm) ran on 2026-10-16 from
  02:51 CEST on an uncommitted development tree, before the review fixes of
  `573f875`, `580e83f` and `62c0092`. Its record predates the runner's
  code-identity field, so the exact code is not recorded (the record was first
  committed in `a31099b`, at 07:50); its run configuration hash equals the
  current profile's. It is one realization, so no seed scatter is
  known at 42 m, and it repeats the fastest layers' periodic atmosphere bands
  (LIM-08). The profile also keeps the Tikhonov damping of 0.001 that left
  waffle unregularized at 12 m (LIM-16).
- **Update 2026-10-18 (roadmap S1):** rerun with the same protocol at revision
  `2312502`, which contains the review fixes, with a clean code identity.
  Every recorded scientific value is bit-identical to the 2026-10-16 record:
  the residual and open-loop series, the valid fractions, the long-exposure
  Strehl and the lock flag (173.2 nm, 0.753). Only the timing (1.797 s per
  frame on a shared machine) and the peak memory (1.60 GiB) differ. The result
  therefore holds on current code.
- **Consequence / next evidence:** Quote it as a single realization on current
  code. The realization ensemble (roadmap S2) is a governed series; until it
  exists, no 42 m statement covers the realization scatter.
- **Evidence:** [E5 record](refactor/detector_level_evidence/det09_e5_42m_noise_on.json),
  [S1 rerun](refactor/detector_level_evidence/det09_e5_42m_noise_on_current_2312502.json),
  [detector execution record](refactor/DETECTOR_LEVEL_DEVELOPMENT_STATUS.md).

### LIM-18 — The 12 m isolated detector noise departs from a pure inverse-photon law

- **Status:** Recorded negative result and unexplained departure; paired noise
  study (`experiments.detector_level.paired_noise_run`). Added 2026-10-18.
- The predeclared test, a log-log slope within two standard errors of −1,
  passes at 2 m (−0.978 ± 0.014) and fails at 12 m (−1.028 ± 0.010,
  `det_emccd_12m_medium_derived@3`, m_AB 8–11, seeds 71–75). Both are
  weighted log-log fits quoted with the unscaled fit standard error; their
  χ²/dof are 2.46 and 2.50, so with scaled errors the 12 m departure is
  1.7 rather than 2.7 standard errors. The rule fixed no convention, and the
  recorded verdict stands. The noise model predicts a steeper −1.097 from read
  noise and clock-induced charge. Post hoc,
  the isolated variance follows the model's variance to the power 0.95–0.96,
  with an unexplained 6.7 % dip at 12 m (m_AB 10) and a 9 % drift at 2 m.
- **Consequence / next evidence:** Do not describe the faint-end noise as
  photon-limited or as an exact match to the model. Explaining the
  departures is a separate study (roadmap S4); a new record must not
  overwrite this one. A five-seed paired bootstrap of the saved 12 m records
  (GPT pre-refactor audit F-06, an unweighted estimator) is exploratory
  evidence, not a validated ensemble uncertainty.
- **Evidence:** [12 m record](refactor/detector_level_evidence/det09_noise_isolation_12m_v3.json),
  [2 m record](refactor/detector_level_evidence/det09_noise_isolation_2m.json),
  [detector execution record](refactor/DETECTOR_LEVEL_DEVELOPMENT_STATUS.md#isolated-detector-noise-variance-2-m-results).

### LIM-19 — HCIPy science images are conditional on their captured window

- **Status:** Observable boundary; HCIPy science propagation. Added 2026-10-18
  (GPT pre-refactor audit F-04).
- The HCIPy science propagator normalizes each frame's image to unit sum over
  its finite focal window, and the long exposure averages those images with
  equal weights. For captured fractions `c_k` the grid Strehl is the source
  Strehl times `c_0 / c_k`, so a frame that loses flux beyond the window is
  weighted up: a 2.5 λ/D tilt in a 3 λ/D window gives a peak ratio of 1.188
  where the equal-flux ratio is 1. This is the documented `PsfResult` unit-grid
  convention, not an energy error.
- **Consequence / next evidence:** Do not read HCIPy window images or their
  peak ratios as full-source Strehl or as an equal-source-flux exposure. A
  physical long exposure would weight frames by their captured fractions and
  normalize once; validate the field of view at any claimed configuration.
- **Evidence:** [science metrics](../src/shwfs_ao/science/metrics.py),
  [HCIPy propagation](../src/shwfs_ao/backends/hcipy/propagation.py),
  GPT audit oracle `reviewers/atmosphere_science/oracles/science_window_oracle.py`
  (main checkout `outputs/pre_refactor_audit/20261017T143700Z/`).

## Keeping this record current

Use the next unused `LIM-XX` identifier for a new entry. Record:

- **Status and affected scope:** model, backend, profile/version or experiment.
- **Limitation:** observed behaviour or explicit assumption.
- **Consequence / next evidence:** which conclusion is limited and what would
  justify revising it.
- **Evidence:** source, diagnostic, test or saved result; include review date.

When resolving an entry, retain its identifier and link the replacement
profile/version and validation evidence. A feature's presence alone does
not close a validation gap.
