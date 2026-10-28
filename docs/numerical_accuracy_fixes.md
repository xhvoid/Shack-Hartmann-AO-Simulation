# Numerical accuracy corrections — September 2026

This change set follows independent reproduction of the repository review at
commit `c774aa43ed1f3adfe530313647d051cd424e9661`. Work is applied and checked in
the following order:

1. Atmospheric spectrum discretization and ensemble-variance validation.
2. Physical-grid PSF FWHM estimation and sampling convergence.
3. TIPTOP frequency coverage, convergence evidence, and FWHM measurement.
4. Physical-baseline explanations and Strehl/RMS metric definitions.
5. Tutorial inputs, plotted reference curves, regularization, and study text.
6. Preservation of revised notebook work and restoration of archive integrity.

The legacy v1 spectrum and accepted fast proxy artifacts remain historical
compatibility evidence. The DM coupling is a declared synthetic model parameter;
it is not tuned to obtain a desired residual. The physical reference artifacts
are regenerated through their candidate/review/acceptance workflow after the
numerical changes, with the scientific reason and validation recorded here.

## Verified starting point

- Shipped v2 screen size: deterministic expected piston-removed variance
  58.43950 rad² versus circular-aperture theory 49.09557 rad² (+19.03%).
- Canonical ideal-pupil FWHM at padding 3: 0.89552 λ/D versus 1.02899 λ/D.
- TIPTOP fitting term: 47.8955 nm on the original frequency grid versus
  71.3003 nm when integrating the same PSD above the DM cutoff to infinity.
- Tutorial 01 under-applies and unequally scales its two tilt inputs; tutorial
  02's reference curve is all NaN; tutorial 03 never truncates a singular mode.
- Two governance checks fail because the archived `02_sh_wfs_experiment.ipynb`
  contains a local revision. That revision must be preserved before restoring
  the original archived bytes; expected archive hashes must not be redefined.

## Implementation and validation

Implementation results, accepted numerical changes, and validation evidence
are recorded below.

### 1. Atmospheric covariance and frozen flow

V2 now draws independent spectral coefficients at 4×4 actual midpoint
frequencies per cell, including the nested subharmonic cells. It no longer
places a cell's integrated power at its centre. Exact spectral replay moves
these nonperiodic modes at their actual frequencies, retaining the seed and
any explicitly requested initial normalization gain. Metadata and v2 component
identity record the quadrature and translation algorithms. Legacy v1 is
unchanged. Metadata distinguishes calibrated raw spectra from realizations
subsequently rescaled by `normalize_rms=True`.

- Deterministic circular-pupil variance: 48.95345 versus 49.09557 rad²
  (−0.29%; previously +19.03%).
- 512 independent screens: 48.48086 ± 1.52406 rad² standard error, versus
  48.92541 rad² from independently evaluated continuous covariance on the
  actual raster pupil. Realization standard deviation is 34.485 rad².
- Direct plane-wave translation checks cover signed winds, fractional pixels,
  near-boundary travel, reset/query cadence, and normalization on/off.
- Full atmosphere checks: 61 passed, including slow structure-function and
  optional HCIPy checks; four additional invalid-quadrature cases also pass.
  The near-infinite outer-scale test explicitly resolves nine subharmonic
  levels; three levels are sufficient for the shipped finite L0=25 m case,
  not a universal approximation for arbitrarily large outer scales.

### 2. Canonical PSF width

Canonical FWHM pairs mean annular brightness with the area-weighted mean
sample radius. The frozen legacy facade explicitly retains its historical
inner-edge convention. Analytic Airy widths at sampling 3/4/8/16 are
1.05780/1.03148/1.02933/1.02928 λ/D (theory: 1.028994). Native propagation,
irregular rectangular Gaussian grids, angular scaling and translation are
also checked. All 128 science/legacy PSF tests pass, including the unchanged
exact legacy numerical contract; Ruff and mypy pass for these edits.

### 3. TIPTOP frequency coverage, sampling and figures

The supplemental study now keeps P3's sampled correction-band residual and
replaces its truncated high-frequency fitting term with the continuous
von Kármán fitting structure function. MASTSEL propagates that combined OTF.
Raw P3 budgets remain separately labeled; no third-party package is patched.
The helper rejects unsupported low-order, custom-pupil, static-aberration and
additional-error branches. Its generated pupil uses P3's inclusive
`D/(N−1)` coordinates. The full interpolated pupil autocorrelation is retained;
hard radial clipping at D was found to introduce negative diffraction rings.

The baseline fitting RMS is 71.30035 nm, compared with raw P3 values
47.89548 nm on the original grid and 64.92005 nm on a twice-wider grid.
Completed total WFE is 131.68832 nm, peak Strehl 0.780916, and EE inside
50 mas 0.635403. The central science crop contains 0.951796 of the full
computational flux and is not renormalized. The completed result is invariant
to the tested native-grid extent, while raw P3 retains finite-tail error.

- All seven directions: 1024→2048 computational pixels change peak Strehl
  by at most 1.10e-6, EE by 8.88e-6 and FWHM by 7.33e-5 mas. The crop-energy
  change is 0.00181 and is reported as residual halo-folding error.
- Radial quadrature 256→512 changes reported metrics by less than 1e-12
  relative. Completed budget/OTF variance closure is better than 6e-13 nm.
- Separate focal-pixel refinement from 5 to 2.5 mas changes FWHM by at most
  0.371%. The analytic annular-Airy contour's finite-pixel bias improves
  from −0.497% to −0.123%. Computational extent alone is not an angular
  sampling check.
- Across seeing 0.5–1.2 arcsec, interpolated core FWHM changes from 43.194
  to 43.449 mas. It is weakly sensitive, not invariant or pixel-count locked.
- Fifteen actual model evaluations produce 105 completed science PSFs,
  with reused baselines avoiding redundant configurations. The repeated
  baseline agrees exactly. The notebook has executed outputs, five
  regenerated and visually checked figures, and machine-readable evidence
  in `notebooks/studies/tiptop_validation.json`.
- Five focused regression tests pass: independent infinite-tail integration,
  direct high-frequency structure-function integration, subpixel FWHM
  response, crop-energy preservation, and generated-pupil diffraction
  agreement with an independent annular-Airy reference. The final test needs
  the optional MASTSEL dependency and passed in the validated environment.

The optional `tiptop` extra records the validated upstream versions; the
notebook explicitly distinguishes these high-order-only model results from
delivered instrument performance. Its portfolio notes have been updated to
the corrected results and limitations.

### 4. Physical baseline review

The physical candidate was generated with
`scripts/update_physical_regression_baselines.py --generate-candidate` in a
separate directory and its complete eight-row table, six validation groups,
reference JSON, and file-hash diff were reviewed before acceptance.

The corrected quadrature changes the seeded random realization as well as
the ensemble covariance; its single-seed result is not expected to change by
the ensemble RMS bias alone. The `all_effects` row changes from 645.444/595.269
nm open/closed RMS to 492.001/440.574 nm, with H-band peak Strehl 0.249565.
Its ratio is 0.895474; open H-band peak Strehl is 0.210247. The 120 nm
OPD-equivalent stroke cap remains deliberately restrictive and 10/13
actuators are saturated in the median tail frame. The dynamic reference
without that cap has 476.220/341.424 nm open/closed RMS. All centroid-validity
fractions remain one, all six validation groups pass, and the validation CSV
is unchanged. No tolerance was relaxed and no DM influence width or stroke
was tuned to improve these results. The frozen `fast_*` artifacts are unchanged.

Peak Strehl follows the displaced peak, while piston-removed OPD RMS retains
tilt. Wavelength-weighted per-frame scalar metrics and their tail medians
are not exposure-integrated broadband images. Documentation now states these
differences, the synthetic influence-function assumptions, finite sampling,
and the saturation stress-case interpretation.

### 5. Executed tutorials and controlled studies

All nine changed canonical notebooks were executed with saved tables and
figures, not just edited as text. The six atmosphere-based examples now
explicitly select v2, exact spectral translation, three-times padding, and
`normalize_rms=False`.

- Tutorial 00 separates the finite-L0 ensemble prediction (483.257 nm) from
  the seeded realization (587.474 nm); the phase/OPD conversion round-trip
  error is 2.12e-22 m.
- Tutorial 01 applies `OPD = angle * x` or `angle * y`, exactly 2 µrad on
  each axis. Both responses are 2.700742 pixels versus the geometric
  expectation 2.902494 pixels; finite-window centroid gain is 0.93049 and
  cross-axis response is below 6e-15 pixels. Assertions protect amplitude,
  sign and axis symmetry.
- Tutorial 02 reports centroid availability and measures errors only on
  valid components. The 500-photon point is explicitly unavailable (0%
  valid); the 1000-photon point anchors a finite inverse-square-root curve.
  RMS errors at 1000/5000/20000/100000 photons are
  0.194624/0.090640/0.044227/0.019610 pixels. Invalid data is not presented as
  a physical measurement.
- Tutorial 03 scans actual truncation: cutoffs 0.8/0.5/0.35/0.3 retain
  12/24/27/29 modes, with command errors 62.900/43.366/17.505/8.579 nm.
  Smaller cutoffs tie at full rank; the text reports that outcome instead
  of claiming an unobserved optimum or L-curve.
- The mode-order study distinguishes mean variance ratios from mean
  individual RMS fractions, reports absolute RMS, and asserts the exact
  r0 scaling and invariance of fractional correction at fixed geometry/L0.
  Six realizations are not claimed to prove a theoretical Noll coefficient.
- The high-order study holds the pupil, WFS sampling, full atmospheric
  trajectory, timing and controller fixed across DM orders. All rows have
  open RMS 256.292 nm; 5/7/9 actuator grids give closed RMS
  246.742/229.562/227.477 nm. The synthetic width/pitch 0.35 remains explicit.
- The gain/latency study is labeled noiseless; the detector-level study
  includes noise but does not attribute differences between unmatched
  notebooks to noise alone. Both use matching open/closed time windows.

The historical noise-proxy figure and public-data-conditioned amplitude are
also labeled explicitly. The linear 260 nm × seeing/0.8 proxy is preserved
for compatibility and is not represented as atmospheric pupil variance.

### 6. Archive integrity and preserved research work

The edited archive notebook was first copied byte-for-byte to
`notebooks/experimental/sh_wfs_experiment_revised.ipynb` and verified with
SHA-256 `cbbac69113f4c0da48173134b89613c27d47cb764d8fce3838e585025c744b50`.
Only then was the original restored from the recorded Git revision. Its
expected hash remains
`f50f9cf6b71fcfeeb4102d4a1a3a8b6421ddb08d668001e62b9a289abcfce922`.
The manifest records the preserved revision and TIPTOP study as supplemental,
manual research notebooks. None of the sixteen archive hash expectations was
changed.

## Verification record

- Final full fast source suite on Python 3.14: **1,617 passed, 17 skipped,
  seven slow tests deselected** in 552 seconds. This run includes the
  available HCIPy checks, notebook-runner tests, archive governance, and
  wheel/source-distribution installation contracts. No failures remain.
  Tests needing local kernel ports/process control ran outside the sandbox.
- All native README commands executed successfully, including the complete
  fast integration example and its generated figures, tables and metrics.
- Fresh physical integration: both slow reference-metric and complete
  scenario-table reproduction tests passed (821 seconds), independently
  reproducing the candidate generation. The separate third redundant
  determinism rerun was not run; the two completed full runs already agree.
- All nine revised canonical notebooks executed in real Jupyter kernels,
  with full-study parameters and saved figures; numerical assertions passed.
- Ruff passed for the package, examples, scripts, tests and build support.
  Mypy passed for all 101 source files. Whitespace checks passed.
- All four frozen fast-reference files were compared with their pre-change
  SHA-256 hashes and remain unchanged. All sixteen archive hashes match the
  unchanged manifest expectations.

Focused atmosphere, science-metric and supplemental TIPTOP checks are recorded
with their respective corrections above. The full scheduled slow/HCIPy matrix
and alternate-Python CI lanes were not rerun locally.

### Publication checks

The public README now leads with current sensor-calibration, reconstruction
and control results; historical figures remain separately identified. The
installation guide and figure inventory provide reproducible entry points
and source-notebook cell IDs. Documentation/governance checks passed (69
tests), and all local links on these entry pages resolve.

The portable wheel bundle now includes the atmospheric-spectrum regression
module and the supplemental TIPTOP numerical tests with their support module.
A freshly built wheel installed outside the source checkout passed all 43
selected non-slow tests in those two modules (three slow cases deselected).
Ruff, the 101-file mypy check and whitespace checks also passed.

### Linux publication portability

The first GitHub Actions run after publication exposed platform assumptions
that the successful macOS run could not exercise. The follow-up corrections
address the validation and execution contracts:

- The frozen science facade uses scalar quicksort for equal-radius pixels.
  NumPy's x86 SIMD tie ordering changed one legacy EE80 interpolation despite
  an unchanged PSF. Its radii are exact square roots of integer pixel offsets:
  the platform `hypot` need not be correctly rounded, and glibc 2.39 is one
  ULP off for some integer pairs, which splits tie classes. The
  object-comparison quicksort permutation depends only on the integer offset
  grid, so it is computed once per grid and reused for every PSF, fraction and
  angular spacing. The canonical stable-sort estimator and all four frozen
  fast-reference files remain unchanged. Ring-crossing regressions exercise
  three fractions at three angular spacings.
- Frozen DM and experimental pyramid-sensor tests retain the original full
  arrays and verify their historical digests. They compare continuous optical
  values at strict floating-point tolerances, with exact mask, peak and seeded
  detector checks, instead of requiring identical libm/FFT bits on every CPU.
- Packaged preset serialization tests read through `importlib.resources`, so
  the same test works from a source checkout and an installed wheel.
- Cross-backend report schema v2 records lossless numerical input arrays beside
  their original hashes. Evaluation checks exact configurations, masks and
  sample layouts, verifies the hash evidence, and compares every floating-point
  sample at fixed roundoff tolerances. Scientific metric criteria are unchanged.
  The preview reproduced every scientific metric and every original input hash;
  only informational timing and memory values differed. Candidate generation
  now also rejects Python versions without an explicit HCIPy lock profile.
- Notebook namespace selection checks access to a caller-owned private file.
  Its sudo fallback initializes the network namespace, then returns to the
  caller's UID/GID with capabilities removed and new privileges prohibited.
  Live Linux kernel tests check private-file access, loopback connectivity and
  refusal to re-enter the host network, including a forced fallback case.
  CI configures its existing AppArmor exception before governance tests.

Local focused verification: 144 science/resource tests and 72 DM/experimental
tests passed. All eight fast integration tests passed, including complete
scenario-table reproduction against the unchanged frozen references (714 s).
Notebook governance and runner checks passed 106 tests, with three Linux-only
cases skipped on macOS. Ruff passed and mypy checked 102 source files. Linux
execution is recorded after the publication checks finish; these local results
alone do not establish cross-platform success.

The schema-v2 cross-backend baseline was then regenerated from clean commit
`20e0e38a8af7d6baafe38551f95af475573cdd0c` in the exact HCIPy Python 3.14 lock
environment and accepted through the normal candidate/diff workflow. Every
scientific comparison, acceptance criterion and original raw input hash
matches the previous baseline; only informational runtime/memory values and
the added numerical identity evidence differ. The direct wheel and the wheel
rebuilt from the source archive have matching contents and resources. Installed
wheel checks outside the checkout passed 212 tests (two skips), covering
cross-backend validation, packaged presets and science metrics.
The complete cross-backend, resource and documentation test selection passed
232 tests (one skip) after acceptance.
