# Matched 2 m wavefront comparison from existing recordings

## Result

The fixed 2 m crop from the 42 m recording evolves on a comparable local scale to the independent 2 m baseline. Its mean spatial OPD RMS is 381.5 nm versus 396.3 nm; the temporal relative standard deviation of spatial RMS is 29.3% versus 25.6%. The full 42 m pupil remains at 1.40%. This supports the footprint/statistical-averaging explanation for the apparently stable whole-aperture RMS. It is not a controlled proof of equivalence between the two atmospheric implementations.

| Quantity | 2 m baseline | 42 m, fixed 2 m crop |
|---|---:|---:|
| Mean spatial RMS (nm OPD) | 396.3 | 381.5 |
| Temporal standard deviation of spatial RMS (nm) | 101.4 | 111.9 |
| Relative temporal standard deviation | 25.6% | 29.3% |
| Wavefront difference RMS, 8 ms (nm; 396 time pairs) | 107.1 | 136.6 |
| Wavefront difference RMS, 100 ms (nm; 350 time pairs) | 483.2 | 522.2 |
| Wavefront difference RMS, 500 ms (nm; 150 time pairs) | 566.3 | 606.3 |

Difference RMS in the table is sqrt(mean over valid pupil samples AND all available time pairs of [W(t+lag)-W(t)]^2). The illustrative map panels use one specific pair starting at 0.200 s, so their values need not equal these whole-window statistics.

## Sampling and conventions

- Fixed crop center (10, 0) m in the 42 m pupil; circular diameter 2 m. Selected geometrically before inspecting crop values; all samples and interpolation neighbours are within the unobstructed pupil.
- Matching physical times 0.200 through 0.998 s inclusive, every 2 ms: 400 pairs of instantaneous maps. The 2 m frame is 2 times the 42 m frame index. Archived timestamps were checked directly.
- Common x/y coordinates: 52 samples from -1 to +1 m, spacing 2/51 m; identical circular support of 2032 uniformly weighted points. No temporal interpolation.
- The 2 m samples are native. The 42 m grid spacing is 42/1007 m; its values are bilinearly sampled at the translated 2 m coordinates. This mild spatial filtering is disclosed, not presented as original 42 m samples.
- Remove the mean on the local 2 m support independently at every time. Keep tip/tilt. Do not renormalize amplitude, shift patterns to align them, or substitute zero for invalid samples.
- Difference = later local piston-removed OPD minus earlier local piston-removed OPD. All map panels and the animation use one common linear +/-2500 nm color range, covering all included maps and 8/100/500 ms differences without clipping.
- Animation: 99 recorded time samples, 0.200 to 0.984 s at 8 ms spacing, 160 ms display duration each. Right-hand panels use the next existing frame 8 ms later. Looping repeats the same record; it does not extend the simulation.

## Spatial interpolation sensitivity

Nearest-neighbor sampling of the same 42 m patch gives mean RMS 384.1 nm rather than 381.5 nm. Difference RMS at 8, 100, 500 ms becomes 142.7, 525.9, 608.5 nm rather than 136.6, 522.2, 606.3 nm. The small-lag interpolation effect is about 4.2%; it does not reverse the observed comparison. This is a sensitivity comparison, not an uncertainty bound or a convergence study.

## Verification and provenance

- The full 2 m wavefront archive SHA-256 matches the published provenance: `01dca7e0c170fc28cf86cfeac55a8db67704c8eff698248900c6a8a9fc465e89`.
- All 400 used 42 m raw-frame hashes match the published per-frame hashes. The 2 m source time/index hashes also match the published provenance.
- Recomputed 2 m spatial RMS matches published metrics exactly at every used frame. Independent explicit four-corner interpolation agrees with the crop arrays to below 1e-8 nm at five times.
- `comparison.json` records input file hashes, per-frame 42 m hashes, configurations, definitions, environment and summary statistics. `verification.json` records additional checks. `analysis.py` is a portable adaptation of the postprocessing source, with input paths supplied as arguments; numerical operations are unchanged. The original source hash is retained in `comparison.json`.
- The original raw archives were opened read-only. No AO simulator, random generator, calibration, test suite or CI was run. Existing repository files were not edited.

## Interpretation limits

This is one fixed patch and one atmospheric realization per configuration. The layer profile, winds, seed stream and slight r0 difference remain unmatched. Overlapping temporal pairs are correlated; the tables and curves are descriptive, not confidence intervals. The comparison resolves the visual/local-scale question for these records; it does not validate either model against measured atmosphere.

The frozen-flow model context was checked in Por et al. (2018), section 4.1: https://ehpor.github.io/assets/pdf/Por-2018-HCIPy.pdf . The new comparison itself is derived directly from the stored maps, not from literature or regenerated screens.

## Outputs

- [100 ms wavefront and difference panels](comparison_100ms.png)
- [8 ms panels](comparison_008ms.png)
- [500 ms panels](comparison_500ms.png)
- [Temporal statistics](temporal_comparison.png)
- [Synchronized animation](synchronized_comparison.webp)
- [Crop location](crop_location.png)
- [Matched numerical arrays](matched_wavefronts.npz)
- [Per-time RMS values](timeseries.csv)

## Publication

The animation is losslessly converted to WebP; all 99 decoded RGB frames were checked against the original GIF. `publication.json` records the source identities. Matched numerical arrays are provided as a download and are not used to run a simulation in the browser.

## Whole-pupil input RMS changes

Across the complete one-second scalar histories, the largest larger/smaller RMS ratios over 40 ms are 1.509 (2 m) and 1.009 (42 m); over 100 ms they are 2.147 and 1.021. These are extrema over matched physical lags, not typical changes or a claim of several-fold changes in a few computed frames. They describe whole-pupil input error strength; they do not establish that DM tracking is easier. `comparison.json` records the exact values and time pairs.

## Control comparison and a naive assumption

If loop response and the residual/input RMS ratio are comparable, and that ratio stays approximately constant, smaller input RMS fluctuations should produce smaller residual RMS fluctuations. At comparable residual phase variance and consistent science-image definitions this can help Strehl remain near a steady value. This is a conditional explanation, not a premise established by these runs.

The saved configurations have similar r0 and physical grid/lenslet sampling, but differ in loop rate (1000/500 Hz), gain (0.2/0.3), leak (0.02/0), first WFS-visible delay (3/6 ms), DM influence functions and OPD stroke limits (1/100 micrometres), reconstruction, detector/flux conventions, winds and science wavelength (1.65/2.2 micrometres). Over the same 400 times the mean per-frame residual/input RMS ratios are 0.687/0.119, with temporal standard deviations 0.118/0.0028. These combine multiple error sources and do not isolate controller efficiency. `control_comparison.json` retains the configurations, source hashes, definitions and exact scalar results. No new loop was run.
