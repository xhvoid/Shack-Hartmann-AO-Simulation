# Aperture scale and apparent temporal stability

The website section `#aperture-comparison`, placed below the fixed 42 m replay,
publishes postprocessing of the two existing one-second atmosphere recordings.
No atmosphere, AO loop or calibration was rerun.

## Scientific result

One fixed 2 m circle at (10, 0) m in the 42 m pupil was bilinearly sampled onto
the native 52 × 52 2 m grid. Local piston was removed, tilt retained, and
amplitudes left unchanged. The 400 common times run from 0.200 to 0.998 s
at 2 ms spacing. All maps and 8/100/500 ms differences share ±2500 nm OPD.

The relative temporal standard deviation of spatial RMS is 25.6% in the 2 m
baseline and 29.3% in the crop, compared with 1.4% over the full 42 m pupil.
Local evolution is comparable; a stable whole-pupil RMS is not a static map.
The full-pupil 42 m difference RMS over 0.200–0.700 s is about 1851 nm.

In the complete saved scalar records the largest larger/smaller input-RMS
ratios over 100 ms are 2.147 (2 m) and 1.021 (42 m). These are descriptive
extrema, not typical changes or several-fold jumps in a few computed frames.

A **naive assumption** makes the control interpretation explicit: comparable
loop response and similar, temporally constant residual/input RMS ratios
would pass smaller input-RMS fluctuations into smaller residual-RMS
fluctuations. At comparable residual phase variance and consistent image
definitions this can help Strehl stay near a steady value. The actual runs
do not establish that premise: loop rates, gains, leaks, physical delays, DM
stroke/influence functions, reconstruction, detector/flux conventions, wind
profiles and science wavelengths differ. The measured mean per-frame
residual/input RMS ratios at the 400 common times are 0.687 and 0.119, with
standard deviations 0.118 and 0.0028. These combine several error sources;
they do not isolate controller efficiency.

The evidence is one patch and one realization per model. The conclusion is
a descriptive interpretation, not a matched causal test, confidence interval,
convergence result or instrument validation. Frozen-flow context was read in
[Por et al. (2018), §4.1](https://ehpor.github.io/assets/pdf/Por-2018-HCIPy.pdf).

## Evidence and publication

The completed local analysis is in
`outputs/ao_aperture_comparison/20261023-existing-data/`. The public derivative
is located through `web/ao-explorer/data/current.json` → `apertureComparison`.
Its manifest binds every numerical/download member by size and SHA-256.
`comparison.json` and `verification.json` retain input identities and numerical
checks; `control_comparison.json` retains both saved configurations, source
hashes, delay conversion and descriptive residual fractions.

The full 2 m input archive digest and all 400 used 42 m frame hashes match the
recordings. An explicit four-corner interpolation check agrees with the crop
to below 1e-8 nm. Nearest-neighbor sampling changes the 8 ms crop difference
RMS by about 4.2%, without reversing the comparison. These checks establish
correspondence to saved records, not physical validation.

Packaging omits workstation paths, retains original source hashes, publishes
a portable postprocessing script and verifies all 99 losslessly converted
WebP frames against the original GIF. Numerical arrays are downloadable;
the browser never runs the analysis or an AO model.

Publication uses a `[skip ci]` commit and the existing Pages deployment with
`run_validation=false`, in accordance with repository policy.
