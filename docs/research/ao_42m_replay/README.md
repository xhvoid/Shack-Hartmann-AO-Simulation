# Fixed 42 m recorded replay

This local experiment records one explicitly requested 42 m trajectory. It
extends the 2 m viewer's source-bound replay approach to one fixed exploratory
configuration. The initial local preview was completed before the subsequent
request to integrate and publish it in the existing GitHub Pages site.

## Artifacts

- Raw run: `outputs/ao_replay_42m/fixed-42m-500-seed1/`
- Scientific source data: `outputs/ao_replay_42m/binary-source/`
- Local web bundle: `outputs/ao_replay_42m/local-preview/`
- Producer: `scripts/ao_explorer/replay_42m.py`
- Exporter: `scripts/ao_explorer/replay_42m_export.py`
- Viewer source: `scripts/ao_explorer/replay_42m_viewer.html`

The output directory is intentionally local and ignored by Git. The raw run
is roughly 17.1 GB (15.9 GiB); do not add the full archive to the website repository.

To reopen the completed preview from the repository root:

```sh
.venv/bin/python -m http.server 8768 --bind 127.0.0.1 --directory outputs/ao_replay_42m/local-preview
```

Then visit <http://127.0.0.1:8768/>. A local HTTP origin is needed for fetching
assets and verifying their SHA-256 digests; opening `index.html` as a file is
not sufficient.

## Fixed scientific configuration

The full, frozen effective configuration is in the run's `plan.json`.

| Item | Value |
| --- | --- |
| Profile | `det_ccd_42m_r3band_derived@1` |
| Overrides | 500 steps; root seed 1 |
| Realization | 0 |
| Atmosphere | Native ten-layer model; r0 = 0.13 m at 500 nm; L0 = 25 m |
| Pupil | 42 m; 1008² samples; 28% central obscuration; no spiders or segment gaps |
| WFS / DM | 84 × 84 lenslets; 85 × 85 DM grid |
| Guide flux | 100,000 detected electrons / full subaperture / frame; independent of binary template |
| Camera | Assumed synthetic CCD; noise enabled; not measured ESO hardware |
| Control | 500 Hz; gain 0.3; leak 0; 2 queued latency frames; finite 100 μm OPD stroke |
| Science wavelength | 2.2 μm |
| Recorded interval | 500 steps, t = 0 … 0.998 s; rectangular-rule duration 1.000 s |
| Analysis window | Frames 100–499; 400 equal weights; 0.2–1.0 s |
| Display samples | Every fourth frame plus final frame: 126 actual snapshots |

All atmosphere and pre-update residual maps are retained at float64 precision.
Full-grid PSF pairs are retained at the display indices. All 500 per-frame
metrics and the 400-frame intensity mean are recorded; the mean is not an
average of the 126 replay images. No recentering or mean-wavefront propagation
is used. The uncorrected image is an optical counterfactual with the same
atmosphere and zero DM.

The 0.2 s startup exclusion was declared before the run; it is not evidence
of stationarity or statistical convergence. The execution uses two native
threads, 128-lenslet batches, regenerated atmosphere bands and summary
telemetry. These execution settings do not change the scientific identity.

## Scientific binary photograph

The template is a calibrated HST/ACS HRC observation of
2MASS J0746425+200032 AB, program 9451, F775W, 2002-10-21, 440 s total exposure.
The product is `j6kt02020_drz.fits`, obtained from
[MAST](https://mast.stsci.edu/api/v0.1/Download/file?uri=mast:HST/product/j6kt02020_drz.fits).
Credit: NASA/ESA Hubble Space Telescope; ACS/HRC program 9451; MAST/STScI.
See [MAST data use](https://archive.stsci.edu/publishing/data-use).

The 161² source crop is centred at zero-based pixel (x=676, y=506), with
0.025 arcsec native pixels. A median background from a 55–78 pixel annulus is
subtracted. Exact rectangular area overlap resamples integrated pixel flux
to the native science grid, retaining signed values and total flux. The
source is normalized once. No deconvolution, synthetic component replacement,
binary separation adjustment or independent brightness normalization is used.

The crop contains finite SCI pixels and positive drizzle weights. All four
input exposures (`j6kt02l1q` through `j6kt02l4q`) have no full-well or A/D
saturation flags in a 31² pixel region around the binary. DQ flags are
interpreted using the official
[ACS calibration documentation](https://hst-docs.stsci.edu/acsdhb/chapter-3-acs-calibration-pipeline/3-4-calacs-processing-steps).
The quality check does not replace independent photometric calibration.

The observed template is linearly convolved with the complete recorded PSFs,
with zero extension and the actual zero-angle kernel origin. Only then is
the output cropped for display. The original HST PSF, sampling and noise
remain. This is additional blurring of an observed F775W morphology, not a
K-band binary prediction or a measurement of 42 m resolving power. A single
on-axis PSF is assumed across the compact source; anisoplanatic differences
between components are not modelled.

## Display and validation

- All panels share the selected recorded frame. Mean mode changes only the
  image panels; wavefronts remain explicitly labelled with their selected frame.
- OPD maps remove piston and average 4² valid pupil samples for display. One
  symmetric colour range covers all displayed maps. Full-resolution arrays
  supply RMS metrics.
- PSFs use one fixed logarithmic scale relative to the ideal peak. The
  displayed crop is not flux-renormalized.
- Binary images share one fixed asinh transfer based on the original template.
  Negative values are clipped only for display.
- A small eight-step fixture establishes observer-neutral loop history.
  No second full 42 m trajectory is run.
- The production recorder checks RMS and time against loop history, independent
  RMS and peak Strehl calculations, and two intensity-mean accumulation paths.
- The exporter verifies parent hashes, averaging semantics, all map-file and
  sample-file digests, selected map hashes/RMS, convolution against direct
  convolution, even-kernel origin alignment and full-convolution flux conservation.
- Browser assets are checked against a SHA-256 manifest before display. This
  detects inconsistent assets; it is not an externally signed trust anchor.

Pinned dependency versions match the project lock. Additional packages in the
shared environment are disclosed in the run plan; this is not an exact
lock-only environment. Frozen source copies and identities are retained.
The original run record includes redundant numerical image arrays; the web
bundle uses a compact summary without altering that original evidence.

Re-exporting completed data does not rerun the AO simulation:

```sh
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 VECLIB_MAXIMUM_THREADS=2 \
.venv/bin/python scripts/ao_explorer/replay_42m_export.py \
  --run outputs/ao_replay_42m/fixed-42m-500-seed1 \
  --source outputs/ao_replay_42m/binary-source/j6kt02020_drz.fits \
  --output outputs/ao_replay_42m/local-preview-new
```

Use a new output directory; existing artifacts are not overwritten. Future
large reruns require their own explicit scope. The initial local-preview stage
did not include CI, publication, commits or pushes.

The 42 m geometry refers to the
[historical E-ELT DRM](https://www.eso.org/sci/facilities/eelt/science/drm/tech_data/telescope/),
whereas the [current ESO ELT](https://elt.eso.org/about/) is 39 m. The 2 m and
42 m viewers use different wavelengths and configurations and must not be
presented as a controlled diameter-only comparison.

## Completed run — 2026-10-23

The 500-step production run completed in 1170.645 s (about 19.5 minutes,
including construction and numerical result preparation). The archive contains
17,082,181,740 bytes. The following values are for this single realization and
the predeclared 100–499 analysis window:

| Quantity | Uncorrected | AO-corrected |
| --- | ---: | ---: |
| Mean instantaneous pupil RMS | 1565.774 nm | 186.727 nm |
| Mean instantaneous peak Strehl | 0.005371 | 0.753544 |
| Peak Strehl of the mean intensity PSF | 0.002254 | 0.753544 |

All 500 reconstructions were usable; maximum DM saturation fraction was zero.
Recorded RMS arrays and timestamps matched loop history exactly. Independent
RMS disagreement was at most 8.47e-21 m; independent peak Strehl disagreement
was at most 1.11e-16. The separately accumulated intensity means agreed exactly
in this run. These are numerical consistency checks, not physical or hardware
validation.

The standalone local bundle contains 138 manifest-listed assets (about 66.4 MB).
All asset hashes were rechecked after the final chart-label layout adjustment.
Browser inspection covered playback, pause, first/final-frame seeking, mean
mode, synchronized metrics and visual layout; no warning/error logs were
reported. The local `browser-validation.json` binds this check to the final
manifest. No CI was run.

## Website integration — 2026-10-23

The main site now uses its existing light visual language for both apertures.
The second half begins with topic navigation (atmosphere, architecture, checks),
then the fixed 42 m recording, then collapsed supplementary experiments.
The 12 m detector study and analytical MCAO are appendices. Historical 42 m
runs are explicitly separate from this new trajectory. Original research
records, sources and hashes are unchanged.

`scripts/ao_explorer/replay_42m_bundle.py` packages the already completed
preview without rerunning the simulation. The immutable public recording is
`42m-500-31024b173527b7a6` (144 manifest-listed members, 66,484,006 bytes).
Its manifest SHA-256 is
`cc706d634a243c8b85312006c9e62f8f99b47adabe688f3aef9acef65d620122`.
All 134 science/display assets shared with the local preview are byte-identical.
The public plan is a labelled projection omitting host details, authorization
text and the untracked working-tree inventory; it retains scientific settings,
source identities and the hash of the unmodified original plan. Frozen producer
sources and the exporter are included with the public evidence.

The independent publication checker imports neither producer nor exporter:

```sh
.venv/bin/python scripts/ao_explorer/portfolio_validate.py \
  --run outputs/ao_replay_42m/fixed-42m-500-seed1 \
  --report outputs/ao_replay_42m/publication-validation.json
```

It checks every member digest and PNG, publication-to-preview equality, the
original record and plan identities, all scalar history values, both full-grid
mean-PSF Strehl values, and independently recomputes RMS and PSF peak Strehl
at frames 0, 100, 256 and 499. It also verifies that the entire 2 m HTML section,
active 2 m data references and archived research evidence remain unchanged,
and that the displayed ten-layer profile matches the fixed 42 m configuration.
These checks passed. They establish publication and numerical consistency,
not additional physical validation or statistical independence.

Integrated-browser checks covered first/final-frame seeking, complete playback
and stop at frame 499, synchronized binary/OPD readouts, instantaneous/mean
Strehl labels, all three topic controls, collapsed appendix defaults, the 12 m
record, and the MCAO deep link. A 2 m scenario switch, step and average-mode
check passed; the 2 m scenario state no longer touches the topic buttons.
Direct section links are restored after the asynchronous 2 m content loads.
No browser warning/error logs were reported. The publication check result is
saved alongside this document in `PUBLICATION_CHECKS.json`. No CI was run;
publication uses the existing Pages workflow with validation disabled.
