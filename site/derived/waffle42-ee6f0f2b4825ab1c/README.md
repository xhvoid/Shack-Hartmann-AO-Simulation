# Four corner spots in the 42 m image

The AO-corrected mean image of the recorded 42 m replay showed four faint
spots on the diagonals, 0.454″ from the core along each axis at 2.2 µm. That
is λ/2d for the 0.5 m actuator pitch, where a checkerboard on the actuator
grid sends its light. The mirror commands carried such checkerboards, which
the calibrated sensor detects only weakly; measurement noise and aliased
turbulence are plausible drivers that these runs did not separate. Version 2
of the profile (`det_ccd_42m_r3band_derived@2`) removes a family of 96 weakly
sensed checkerboard commands from every reconstructed increment and changes no
other physical setting. On the same atmosphere the corner windows
fell from 10.8 to 0.91 times the surrounding halo, and the peak Strehl of the
mean PSF rose from 0.7535 to 0.7670. Three held-out seeds, judged by criteria
fixed before they ran, gave the same result.

## Runs

| Key | Seed | Profile | Recording |
| --- | ---: | --- | --- |
| s1-v1 | 1 | `det_ccd_42m_r3band_derived@1` | the published replay |
| s1-v2 | 1 | `det_ccd_42m_r3band_derived@2` | full rerun of the same atmosphere |
| s104-v1 … s106-v2 | 104–106 | @1 and @2 | summary-only held-out runs |

The two seed-1 runs come from two builds of the code (`producer_commit` in
`data.json`). Besides the filter, the builds differ in some pupil-edge,
mirror, lenslet and detector-processing code; the pupil, ideal PSF,
uncorrected mean image, actuator and lenslet lists and all 500 atmosphere
frames match. Both versions of each held-out seed ran on one build.

Every run has 500 frames at 500 Hz. Gain 0.3, leak 0, two frames of latency
and LSMR damping α = 0.001 are the same in both versions. The analysis window
is frames 100–499 (0.2–1.0 s), and the mean images average the 400
instantaneous 2.2 µm PSFs with equal weight and no recentering.

## Windows and ratios

The corner windows are 13 × 13 samples of the science image centred on
(±λ/2d, ±λ/2d), 84 samples from the core along each axis at 0.0054″ per
sample. Edge-midpoint windows sit at (±λ/2d, 0) and (0, ±λ/2d), closer to the
core than the halo reference, which is the mean of eight windows at the corner
radius, at 15° + 30°k and clear of the diagonals. Corner / halo is the mean
integrated corner window over the mean halo window, and edge / halo the same
for the edge midpoints. The ratios are four-window means; one seed-105
version-2 corner alone is 1.02 times the halo. Between the versions the edge
windows gained 0.5–0.7% of their light and the halo windows 0.3–0.5%; the
windows cannot rule out small changes elsewhere in the field. Peak Strehl is
the maximum of the mean PSF over the maximum of the ideal PSF.

## Held-out criteria

Seeds 104, 105 and 106 were taken by a fixed rule before any of them ran:
the first three consecutive integers from 100 upward that appeared under no
seed-like key in the 135,817 JSON records scanned (the research repository
with its worktrees and outputs, and the other local AO checkouts; very large
files and some directories were skipped). 101-103 appear in other records.
Each had to meet five criteria: version 1 shows the spots (corner / halo above
3); version 2 has corner / halo at most 1.5; the version-2 peak Strehl is no
more than 0.005 below version 1; the version-2 edge / halo is within 10% of
version 1; and neither run has an unusable frame or a saturated actuator. All
three seeds met all five, 15 held-out passes. Seed 1 meets the same five after
the fact. `data.json` stores the five pass flags of each seed, and the
validator totals all 20. Each seed also has its own detector
calibration and therefore its own 96-mode family; the eigensolver that builds
the family starts from a fixed vector of its own.

## What was recomputed and what was carried

The exporter recomputes every window, ratio, Strehl ratio, encircled energy,
residual mean, dropped-row count and criterion from the saved mean images and
histories, and checks each against the saved analysis. It also renders every
image, and the version-1 tile reproduces the published corrected image pixel
for pixel. Command projections on the uniform checkerboard and on the family
are carried from the saved analysis. The checkerboard value can be recomputed
from the ordered actuator IDs in each run's `record.json` and its command
history (the record is not an input of the exporter). The family value also
needs each run's family basis, which neither the run archives nor the
exporter's inputs contain; a separately saved seed-1 basis reproduces the
seed-1 values but is not distributed.

The designs that were set aside are carried as recorded: the single-mode
projection from the saved comparison, the penalty on the least sensed mode
from its 120-frame check, and the 150-frame prototypes from their result
files. The 150-frame prototypes average frames 50–149, so their values are
comparable with each other and with version 1 in the same window (corner /
halo 9.50, peak Strehl 0.758), not with the full replays. The full replay with
a penalty row on the uniform checkerboard was deleted after it was measured;
its five values are constants transcribed from the written record and say so
in `data.json`.

## Files

- `data.json`: settings, per-run windows and histories, criteria, summary,
  discarded designs, prototypes and image records.
- `frames.csv`: the pre-update residual RMS and the number of dropped slope
  rows for every frame of the eight runs.
- `provenance.json`: the size and SHA-256 of every input, the exporter hash,
  and the research-repository commits that produced the runs.
- `mean-corrected-v1.png`, `mean-corrected-v2.png`: the 1.20″ field on the
  site's log scale, 10⁻⁶ to 1 of the ideal peak.
- `corner-<run>.png`: the upper-right corner position, ±20 samples (±0.108″),
  six image pixels per sample, log scale 10⁻⁶ to 10⁻³ of the ideal peak. On the
  Explorer the seed-1 zooms are labelled with the version-1 upper-right peak
  and with "only the halo remains" for version 2; the corner / halo ratios,
  which are four-corner means, sit under the full-field images and in the
  tables.
- `exporter.py`: the script that wrote this bundle. In this folder,
  `python exporter.py --validate-bundle .` checks every file and value record
  with NumPy and Pillow. A full export (`--evidence-root`, `--web-dir`) also
  needs the saved replay records, which are not published, and a checkout of
  the website for the published overview image.

## Limits

Each evaluation covers 0.8 s of one 1 s run. The cutoff was chosen on frames
50–149 of seed 1; frames 100–149 are also the first 50 of the 400 seed-1
evaluation frames, and the rest of that evaluation comes from the same
correlated realization. The held-out seeds share the turbulence profile,
guide-star flux, geometry and run length of seed 1, and three realizations do
not give a failure rate. The family is computed once per run from the fully
valid calibration; a direction that becomes weakly sensed only under one
frame's row mask is removed only in the part it shares with the family. The
family is exactly orthogonal to the smooth part of its band, not to every
smooth command, and a real wavefront component inside it is removed too. The
cutoff of 0.35, the band factor of 1.5 and the threshold of 0.5 were set on
this geometry and are not published values. The filter exists only for the
sparse LSMR reconstructor.

## Sources

- D. Gavel (2003), Suppressing anomalous localized waffle behavior in
  least-squares wavefront reconstructors, Proc. SPIE 4839,
  https://doi.org/10.1117/12.459686
- R. B. Makidon et al. (2005), An analysis of fundamental waffle mode in early
  AEOS adaptive optics images, PASP 117, 831,
  https://doi.org/10.1086/431436
