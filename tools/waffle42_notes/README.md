# Four corner spots in the 42 m image

The AO-corrected mean image of the recorded 42 m replay showed four faint
spots on the diagonals, 0.454″ from the core along each axis at 2.2 µm. That
is λ/2d for the 0.5 m actuator pitch, where a checkerboard on the actuator
grid sends its light. Version 2 of the profile (`det_ccd_42m_r3band_derived@2`) removes a
family of 96 weakly sensed checkerboard commands from every reconstructed
increment and changes nothing else. On the same atmosphere the corner windows
fell from 10.8 to 0.91 times the surrounding halo, and the peak Strehl of the
mean PSF rose from 0.7535 to 0.7670. Three held-out seeds, judged by criteria
fixed before they ran, gave the same result.

## Runs

| Key | Seed | Profile | Recording |
| --- | ---: | --- | --- |
| s1-v1 | 1 | `det_ccd_42m_r3band_derived@1` | the published replay |
| s1-v2 | 1 | `det_ccd_42m_r3band_derived@2` | full rerun of the same atmosphere |
| s104-v1 … s106-v2 | 104–106 | @1 and @2 | summary-only held-out runs |

Every run has 500 frames at 500 Hz. Gain 0.3, leak 0, two frames of latency
and LSMR damping α = 0.001 are the same in both versions. The analysis window
is frames 100–499 (0.2–1.0 s), and the mean images average the 400
instantaneous 2.2 µm PSFs with equal weight and no recentering.

## Windows and ratios

The corner windows are 13 × 13 pixels centred on (±λ/2d, ±λ/2d), 84 pixels
from the core along each axis at 0.0054″ per pixel. Edge-midpoint windows sit
at (±λ/2d, 0) and (0, ±λ/2d). The halo reference is the mean of eight windows at the corner
radius, at 15° + 30°k and clear of the diagonals. Corner / halo is the mean
integrated corner window over the mean halo window, and edge / halo the same
for the edge midpoints. Peak Strehl is the maximum of the mean PSF over the
maximum of the ideal PSF.

## Held-out criteria

Seeds 104, 105 and 106 were taken by a fixed rule before any of them ran.
Each had to meet five criteria: version 1 shows the spots (corner / halo above
3); version 2 has corner / halo at most 1.5; the version-2 peak Strehl is no
more than 0.005 below version 1; the version-2 edge / halo is within 10% of
version 1; and neither run has an unusable frame or a saturated actuator. All
three seeds met all five. Each seed also has its own detector calibration and
therefore its own 96-mode family.

## What was recomputed and what was carried

The exporter recomputes every window, ratio, Strehl ratio, encircled energy,
residual mean, dropped-row count and criterion from the saved mean images and
histories, and checks each against the saved analysis. It also renders every
image, and the version-1 tile reproduces the published corrected image pixel
for pixel. Command projections on the checkerboard and on the family are
carried from the saved analysis, because they need the actuator layout and the
family basis that only the simulation package can rebuild.

The designs that were set aside are carried as recorded: the single-mode
projection from the saved comparison, the penalty on the least sensed mode
from its 120-frame check, and the 150-frame prototypes from their result
files. The 150-frame prototypes average frames 50–149, so their values are
comparable with each other and with version 1 in the same window (corner /
halo 9.50, peak Strehl 0.758), not with the full replays. The full replay with
a penalty row on the uniform checkerboard was deleted after it was measured;
its five values come from the written record and say so in `data.json`.

## Files

- `data.json`: settings, per-run windows and histories, criteria, summary,
  discarded designs, prototypes and image records.
- `frames.csv`: the pre-update residual RMS and the number of dropped slope
  rows for every frame of the eight runs.
- `provenance.json`: the size and SHA-256 of every input, the exporter hash,
  and the research-repository commits that produced the runs.
- `mean-corrected-v1.png`, `mean-corrected-v2.png`: the 1.20″ field on the
  site's log scale, 10⁻⁶ to 1 of the ideal peak.
- `corner-<run>.png`: the upper-right corner position, ±20 pixels (±0.108″),
  six screen pixels per detector pixel, log scale 10⁻⁶ to 10⁻³ of the ideal
  peak.
- `exporter.py`: the script that wrote this bundle.

## Limits

Each evaluation covers 0.8 s of one 1 s run. The cutoff was chosen on frames
50–149 of seed 1, so those frames entered both the choice and the seed-1
evaluation. The held-out seeds share the turbulence profile, guide-star flux,
geometry and run length of seed 1. The family is computed once per run from
the fully valid calibration; a direction that becomes weakly sensed only under
one frame's row mask is not in it. The cutoff of 0.35, the band factor of 1.5
and the threshold of 0.5 were set on this geometry and are not published
values. The filter exists only for the sparse LSMR reconstructor.

## Sources

- D. Gavel (2003), Suppressing anomalous localized waffle behavior in
  least-squares wavefront reconstructors, Proc. SPIE 4839,
  https://doi.org/10.1117/12.459686
- R. B. Makidon et al. (2005), An analysis of fundamental waffle mode in early
  AEOS adaptive optics images, PASP 117, 831,
  https://doi.org/10.1086/431436
