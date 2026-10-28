# One-second dataset: 1000 frames on a 624 × 624 screen

This is the active dataset of the explorer's 2 m experiment. It is a new
dataset with its own identities. The earlier 180-frame dataset
`series-2m180-b3e1c66-e0d60cbaccc6b`, its galaxy derivative and every record
about them are preserved unchanged; their claims belong to their own evidence
and are not combined with this one.

## What was run

The eight production cases of the explorer protocol, serially, one supervised
child each, with two native threads:

baseline, weaker-turbulence, stronger-turbulence, lower-gain, higher-gain,
brighter-guide, fainter-guide, longer-delay.

Unchanged from the recorded cases of `series-2m180-b3e1c66` (read from its
frozen plan in the ao-explorer-v1 workspace, treated as immutable): profile
`det_emccd_2m_synthetic@1`, root seed 1, realization index 0, the 1 ms frame
period (1 kHz), the 2 m telescope and 52-pixel pupil, the 1.65 µm science
wavelength, the 10 m/s wind along +x, r0, L0, the case overrides, the
controller and the in-loop WFS detector noise. For every case the plan checks
that the recorded 180-frame configuration still rebuilds to its recorded hash
and that the only differing effective parameter is `n_steps`.

Changed:

- **Trajectory length:** 1000 frames, indices 0–999, sample times
  0.000–0.999 s (`t_k = k / 1000`), physical interval [0.000, 1.000) s.
- **Screen:** `native_frozen_flow_v2` generated at 624 × 624 pixels instead of
  the default 3 × 52 = 156.

No pilot, observer-disabled control, seed-sensitivity job, benchmark or
convergence scan was run, and no orchestration path that schedules them was
used.

## Atmosphere screen and coverage

The screen size is an explicit construction option with recorded identity:

- `shwfs_ao.experiments.scao.FrozenFlowScreenOptions(screen_grid_size=624)`,
  passed as `atmosphere_options` to `build_scao_system`. It is accepted only
  for `native_frozen_flow_v2`, forwarded to the native factory only when set,
  and recorded on the `ScaoSystem` and in its build attestation like the
  layered-atmosphere pairing options.
- `NativeScaoComponentFactory.build_atmosphere(screen_grid_size=...)` replaces
  the default `SCREEN_OVERSIZE_FACTOR * pupil` only when given. Without it,
  every historical build is unchanged; an explicit size equal to the default
  is recorded as the default.
- The atmosphere's own configuration hash already includes
  `screen_grid_size` for v2 screens, so the component hash and the metadata
  (`screen_grid_size: 624`, `travel_budget_px: 286.0`) describe the actual
  screen. Every case record checks the built configuration against the
  admitted one, the recorded option and the metadata.

Coverage, from the actual pupil coordinates, screen and wind:

| Quantity | Value |
| --- | --- |
| Pupil spacing | 2 m / 51 = 0.0392157 m per pixel (endpoint-inclusive coordinates) |
| Travel budget | (624 − 52) / 2 = 286 px |
| Supported travel | 286 px × 0.0392157 m / 10 m/s = 1.1216 s |
| Last request | t = 0.999 s, 254.745 px (margin 31.255 px) |
| Runtime travel | equal to the admitted 254.745 px in every case; the budget was never exceeded |

The request schedule has one atmosphere sample per frame at its start (this
profile has no exposure sub-samples), so 1000 requests per case. The wind,
control cadence and atmosphere model are unchanged, nothing is repeated, and
the full 624 × 624 screen is not archived (only the 52 × 52 pupil windows).

The enlarged screen draws a different realization from the same seed. This
dataset therefore does not reproduce the first 180 frames of the earlier
trajectory, and nothing here claims that it does.

## Numerical outputs

`outputs/ao_explorer_1s/<series-id>/` (git-ignored, outside the site):

```text
plan.json                     configurations, admissions, identities, frame contract,
                              analysis window and block-summary definition, written before any run
ledger.jsonl, logs/           one supervised launch per case with its preflight record
cases/<case>/attempt-01/
  case_record.json            scalar records of every frame, checks, hashes, timing, peak RSS
  history.npz                 loop histories
  mean_psfs.npz               mean_psf_uncorrected / mean_psf_corrected (production accumulators),
                              own sums, ideal PSF, axes, analysis frames, pupil mask
  frames/psf_uncorrected.npy  (1000, 156, 156) float64, zero-DM image of the recorded atmosphere
  frames/psf_corrected.npy    (1000, 156, 156) float64, image of the pre-update residual
  frames/atmosphere_opd_m.npy, pre_update_residual_opd_m.npy, held_correction_opd_m.npy
                              (1000, 52, 52) float64 pupil maps (NaN outside the pupil)
  frames/frame_index.npy, time_s.npy
```

The stacks are written frame by frame while the loop runs and hashed as they
are written, so no stack is held in memory. Every case's record checks, among
others, that the observer's scalars equal the loop history, that the times are
exactly k / 1000, that the per-frame independent RMS and Strehl reductions
agree within the frozen tolerances, that the streamed and own means agree, and
that the means recomputed from the archived stacks equal them.

## Analysis window and means

Frames 0–199 were declared the startup exclusion in the plan before any
trajectory ran. `mean_psf_uncorrected` and `mean_psf_corrected` are the
production accumulators' equal-weight means over the half-open window
[200, 1000), exactly 800 frames; the `own_mean_psf_*` sums are kept only as a
cross-check. The window was not tuned after seeing results. The 200-frame
exclusion is a predeclared analysis choice, not a demonstrated settling time.
The means are the correctly computed equal-weight averages for the
0.200–1.000 s window; that correctness does not establish convergence to a
long-exposure ensemble result.

The historical 140-frame means of the 180-frame dataset are unchanged.

## Block summaries

Predeclared in the plan: non-overlapping 100-frame (100 ms) blocks of all
1000 frames, from the scalar records, with the block mean, standard deviation,
minimum and maximum of the pre-update residual pupil RMS and of the
instantaneous peak Strehl (corrected and uncorrected), and for the actuator
saturation fraction also the number of frames with any clipped actuator.

**Saturation definition:** per frame, the fraction of DM actuators whose
requested command magnitude exceeds the 1 µm OPD stroke limit and is clipped
(`dm.model`: `mean(|requested| > stroke_limit_opd_m)`), for the command issued
by that frame's update.

Residual RMS block means (nm), frames 0–99 to 900–999. The first two blocks
are the startup exclusion:

| Case | 0 | 100 | 200 | 300 | 400 | 500 | 600 | 700 | 800 | 900 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | 571 | 482 | 337 | 256 | 226 | 242 | 223 | 203 | 280 | 364 |
| weaker-turbulence | 463 | 398 | 280 | 212 | 188 | 201 | 184 | 168 | 232 | 302 |
| stronger-turbulence | 706 | 583 | 405 | 308 | 275 | 300 | 272 | 244 | 336 | 442 |
| lower-gain | 595 | 490 | 339 | 261 | 239 | 254 | 233 | 204 | 283 | 384 |
| higher-gain | 562 | 480 | 337 | 254 | 223 | 240 | 219 | 203 | 279 | 358 |
| brighter-guide | 571 | 483 | 337 | 255 | 226 | 243 | 222 | 203 | 279 | 364 |
| fainter-guide | 560 | 472 | 327 | 255 | 226 | 244 | 225 | 203 | 279 | 363 |
| longer-delay | 573 | 483 | 339 | 256 | 228 | 243 | 224 | 204 | 281 | 365 |

Analysis window (frames 200–999, eight blocks):

| Case | Residual block means (nm) | Their std (nm) | AO Strehl block means | Frames with a clipped actuator | Averaged-image AO peak Strehl |
| --- | --- | --- | --- | --- | --- |
| baseline | 203–364 | 54 | 0.496–0.665 | 174 of 800 | 0.381 |
| weaker-turbulence | 168–302 | 44 | 0.605–0.744 | 75 | 0.501 |
| stronger-turbulence | 244–442 | 64 | 0.369–0.557 | 410 | 0.273 |
| lower-gain | 204–384 | 56 | 0.496–0.649 | 103 | 0.364 |
| higher-gain | 203–358 | 53 | 0.496–0.667 | 212 | 0.386 |
| brighter-guide | 203–364 | 54 | 0.497–0.665 | 171 | 0.382 |
| fainter-guide | 203–363 | 51 | 0.500–0.664 | 206 | 0.383 |
| longer-delay | 204–365 | 54 | 0.493–0.660 | 181 | 0.378 |

What the blocks show, descriptively:

- The residual falls over roughly the first 500 ms (baseline 571 nm at
  0–99 to 226 nm at 400–499) and then varies with the incoming wavefront for
  the rest of the second. In every case it rises again in the last 200 ms:
  baseline 203 nm at 700–799 to 364 nm at 900–999.
- Within each case r0, the outer scale and the wind are fixed. The pupil
  crosses 255 pixels of one 624-pixel frozen-flow realization, so the realized
  wavefront RMS inside the pupil changes substantially without any
  time-dependent change of the configured turbulence: the baseline's
  atmosphere RMS block means run from 869 nm (0–99) through 251 nm (700–799)
  to 593 nm (900–999).
- Clipped actuators come in bursts: in the baseline at 0–199, 500–699 and
  800–999 ms, none at 200–499 and 700–799 ms. Saturation may limit the
  correction, but it is not shown to be the cause of the late rise.
- No reconstruction was unusable in any case.
- Paired differences in the mean residual over the window are small next to
  the block-to-block spread. Lower gain is +8.4 nm against the baseline's
  266.2 nm, higher gain −2.3 nm, the guide brightness cases within ±0.9 nm and
  the longer delay +1.2 nm. These are paired differences of one realization,
  not ensemble effects. The two turbulence cases have different atmospheres
  and are not paired.

### Interpretation

A working AO loop continuously tracks a changing disturbance, so residual
fluctuations, or a late increase, do not by themselves show controller
divergence or a failure to settle. The available records support an
association between the late residual rise and the changing incoming
wavefront, especially its overall tip/tilt component; that association comes
from a read-only analysis of the archived records that accompanied the review
of this record and was not recomputed here. The records do not isolate the
contributions of fitting error, delay, controller leakage and actuator
saturation.

A nearly unchanged scalar mean can coexist with a mean image that still
depends on the interval. Baseline, read-only from the archives (checked for
this record):

| Window | Mean residual RMS | Peak Strehl of the corrected mean PSF | Peak cell (y, x) from zero angle |
| --- | --- | --- | --- |
| frames 200–599 | 265.3 nm | 0.478 | (−1, 0) |
| frames 600–999 | 267.1 nm | 0.392 | (0, −1) |
| frames 200–999 (the saved mean) | 266.2 nm | 0.381 | (−1, 0) |

The peak Strehl of an averaged PSF is not the average of the instantaneous
peak Strehl values: over frames 200–999 the latter is 0.576 for the baseline.

The late residual increase accompanies stronger realized wavefront variations
within the pupil, especially residual tip/tilt. It does not by itself
demonstrate controller divergence. The saved 800-frame mean is the valid
average for the declared 0.200–1.000 s window, but the available
single-realization record does not establish a converged long-exposure PSF.
One second proves neither convergence nor instability. The run was not
extended, no further simulation or convergence study was made, and the window
was not changed after seeing these numbers.

## RMS diagnostics

A scalar derivative added after the export, without rerunning anything:
the residual RMS after tip/tilt removal of every saved pre-update residual
map, written by `scripts/ao_explorer/rms_diagnostics.py`. `long_export.py`
now calls the same code, so a future export produces it too.

**Definition.** For frame k of a case, r_k is the archived
`frames/pre_update_residual_opd_m.npy[k]`, the pre-update residual measured
in frame k and the wavefront whose image is that frame's AO-corrected PSF. A
plane p_k(x, y) = a + b x + c y is fitted by equal-weight linear least
squares over the 2032 illuminated samples of the saved pupil mask
(`mean_psfs.npz` `pupil_mask`, equal to the geometry's mask). The fit uses
the pupil's actual endpoint-inclusive coordinates, x along the columns and y
along the rows, −1 to 1 m in steps of 2/51 m, taken from the native geometry
of the plan's configuration. Then

    detilted_rms_nm[k] = 1e9 * sqrt(mean((r_k − p_k)^2 over the pupil samples))

in float64. The intercept removes piston.

- Samples outside the pupil are excluded (they are NaN in the archive). A
  non-finite value inside the pupil, or any value outside it, refuses the
  computation.
- The atmosphere RMS and the total residual RMS are the dataset's existing
  per-frame series (piston removed, tilt retained) and are not recomputed.

**Binding and checks before anything was written:**

- the residual archive and `mean_psfs.npz` of every case re-hashed against
  the case record;
- each of the 8000 maps matched to its frame by the SHA-256 the observer
  streamed for that frame during the run;
- the piston-removed RMS recomputed from each map equal to the recorded total
  residual RMS (largest difference 0.0 m, within the frozen 1e-12 relative
  tolerance);
- the fit of full rank, and every detilted value no larger than its
  piston-removed value.

**Storage and provenance:**

- Site: `web/ao-explorer/derived/rms-2m1000-s624-c7241e4190d5-d7fafecb6f7ec/`
  holds a manifest with the definition, units, weighting, timing and frame
  mapping, the coordinates (digests and geometry hash), the parent dataset
  and manifest digest, the window means of all cases, the code identity
  (`094be55b3bf64063…` over `rms_diagnostics.py` and the modules it imports)
  and the environment.
- It also holds `cases/<case>/rms.json` with the 1000 values in nm OPD and
  the window means. Each names the SHA-256 of the dataset metrics member it
  accompanies, the residual archive (path, size, SHA-256), the case record
  digest, the pupil-mask digest and the check results.
- `data/current.json` binds the manifest under `diagnostics` (schema
  `ao-explorer.rms-diagnostics-entry.v1`). The dataset bundle and the galaxy
  derivative are unchanged.
- Full precision:
  `outputs/ao_explorer_1s_derived/series-2m1000-s624-c7241e4190d5-ef74a541b0e60/rms-2m1000-s624-c7241e4190d5-d7fafecb6f7ec/`
  holds, per case, `detilted_rms_m`, the plane coefficients (a in m, b and c
  in m/m) and the recomputed piston-removed RMS, plus `record.json` with the
  checks and array digests.

**Frame mapping.** `values[k]` belongs to numerical frame k (k = 0–999, frame
start t_k = k ms). The page maps the shared playback position through
`time_domain.display_indices` to k. The curves keep all 1000 samples; the
cursor and the readouts use exactly the displayed frame, and nothing is
interpolated.

**Display.** The RMS chart shows the three series on one nm OPD scale:
atmosphere solid, total residual solid, and the detilted residual dashed in a
third colour, with a legend that repeats the line style.

- **Instantaneous mode:** the three readouts give the values of the displayed
  frame with its frame index and timestamp, the same frame as the pupil maps,
  the PSFs and the galaxy panel.
- **Average mode:** playback pauses as before. The readouts give the
  arithmetic means, computed on the page from the verified per-frame series,
  of the three per-frame RMS series over frames 200–999,
  labelled "Mean of per-frame RMS, 0.200–1.000 s, 800 frames". These are
  temporal means of scalars, not the RMS of an averaged wavefront and not
  inferred from the average PSF. The chart cursor stays at the paused frame
  and is labelled "paused frame k".
- **Other places:** the summary table and the frame table gain the detilted
  column, and the case downloads include `rms-diagnostics.json`.
- **Case changes:** a case's diagnostics are fetched and verified with the
  case and installed with it, so the readouts never pair one case's values
  with another case's images.
- **Failure:** the derivative is optional at two levels.
  - If its manifest cannot be verified, the page runs without it and says so.
  - If one case's `rms.json` cannot be fetched or verified, that case is still
    installed from its verified core data and images. The error is stored on
    that case only, and the shared manifest and the other cases are
    unaffected. Cancellation and superseded requests behave as before.
  - In both instances the atmosphere and total residual curves, readouts and
    window means stay (computed from the case's verified metrics). The third
    curve is omitted, its readout and table column are marked unavailable
    with the reason, no download is offered for it, and the status says that
    the core data were verified but the optional diagnostics are not
    available.

**Window means (frames 200–999, mean of per-frame RMS, nm OPD):**

| Case | Atmosphere | Total residual | Residual after tip/tilt removal |
| --- | --- | --- | --- |
| baseline | 396.3 | 266.2 | 189.8 |
| weaker-turbulence | 329.1 | 221.0 | 158.0 |
| stronger-turbulence | 477.3 | 322.9 | 229.6 |
| lower-gain | 396.3 | 274.6 | 192.0 |
| higher-gain | 396.3 | 263.9 | 189.8 |
| brighter-guide | 396.3 | 266.1 | 189.8 |
| fainter-guide | 396.3 | 265.3 | 190.8 |
| longer-delay | 396.3 | 267.4 | 190.9 |

In the baseline, the detilted block means over frames 200–999 are 214, 162,
167, 177, 194, 194, 197 and 214 nm, while the total residual rises to 280 and
364 nm in the last two blocks. Most of the late increase is therefore in the
fitted tilt term of the residual maps. This is a decomposition of the saved
wavefronts, not an attribution of cause: it does not separate fitting error,
delay, leakage or saturation, and a fitted wavefront plane is not a measured
image-centroid motion.

**What it does not mean.** The tilt is removed only in this calculation; the
displayed PSFs and galaxy images keep their original motion and morphology.
The atmosphere RMS keeps its tilt while this residual does not, so their ratio
alone is not a like-for-like measure of correction efficiency. A smaller
detilted RMS is neither evidence of convergence nor a correction applied to
the images.

## NGC 1705 observations

The prepared full-precision template of the earlier galaxy derivative is
reused unchanged:

- `outputs/ao_explorer_galaxy/ngc1705-f814w-2m180-b3e1c66-g1007a60a01ae/template.npz`
  (SHA-256 `dd80f06127f8881a…`), with its record
  `web/ao-explorer/derived/ngc1705-f814w-2m180-b3e1c66-g1007a60a01ae/scene/galaxy-scene.json`
  (SHA-256 `4bccaafbe4b5cdba…`).
- Template identity `412ebe536d81ed5e886e4ac1eb58b7ae8f7eb38b2116c1d570ce875dd3d4dffd`.
  The array SHA-256 `9c176c789c0c8aa3…` and both axis digests were checked
  against the record before use.
- Unchanged: the calibrated LEGUS F814W source, the crop centre on
  NGC 1705-1, angular scale factor 1.0, north-up orientation, the 312-cell
  numerical grid on the PSF lattice, the unit normalization, the inherited
  Hubble response and residual noise, and the saturation disclosures.
- The FITS products were not re-read or reprocessed; the display PNG was not
  used as input.

The method is unchanged (see `GALAXY_OBSERVATION.md`): discrete linear
convolution with zero extension by zero-padded real FFT, cropping to the
native window by angular coordinates, no renormalization, one common asinh
display stretch referenced to the template's brightest cell. No science-camera
or observational noise is added, the morphology is not changed, and nothing is
deconvolved or restored.

- **Instantaneous:** `T (*) psf_uncorrected[k]` and `T (*) psf_corrected[k]`
  for all 1000 frames of every case, written as float64 `(1000, 156, 156)`
  stacks with per-frame flux accounting.
- **Mean:** `T (*) mean_psf_*` from the complete 800-frame means; for the fixed
  template this equals the mean of the 800 per-frame observations.

F814W morphology is used as a relative-intensity template with the 1.65 µm
simulated PSFs. It is not an H-band prediction and not an intrinsic,
deconvolved image of the galaxy; it keeps Hubble's resolution, its residual
noise and the saturated core of NGC 1705-1. Credit: HST/WFC3 UVIS, programme
GO-13364 (LEGUS, PI D. Calzetti); high-level science product
hlsp_legus_hst_uvis_ngc1705_f814w_v1 from MAST.

## Website

`web/ao-explorer/data/current.json` now names:

- dataset `series-2m1000-s624-c7241e4190d5-ef74a541b0e60`
  (manifest SHA-256 `a151da4b84b21029…`, 42,464 bytes);
- galaxy derivative
  `ngc1705-f814w-2m1000-s624-c7241e4190d5-gda93ed5af026-m4adb5a4af111`
  (manifest SHA-256 `223a562f222f6f6a…`, 38,212 bytes). It is a metadata
  revision of the exported derivative `…-gda93ed5af026` (see
  [Repairs after the export](#repairs-after-the-export)), and its manifest
  names the dataset above and its manifest digest;
- RMS diagnostics `rms-2m1000-s624-c7241e4190d5-d7fafecb6f7ec`
  (manifest SHA-256 `3ce30fa20c68ad02…`, 13,189 bytes), an additive scalar
  derivative bound to the dataset manifest (see [RMS diagnostics](#rms-diagnostics));
- code build `3b85a599186cdf30` (`site_build.py --write`).

The exporter wrote the entry last, after both bundles were complete and the
size checks passed. The previous entry content is superseded; the previous
dataset, its galaxy derivative and its validation records are untouched.

Every view uses the new trajectory: the pupil maps, the instantaneous PSF
pairs, the per-frame curves (all 1000 frames, startup exclusion shaded,
cursor at the displayed frame), the frame table, the summary table, the
block summaries, the NGC 1705 instantaneous observations, and both mean
views (PSFs, binary scene, NGC 1705), which use the 800-frame means. The page
code reads frame counts, the analysis window, the displayed frames and the
playback durations from the manifest and refuses a case, metrics, observation
or galaxy record whose time domain differs.

**Displayed frames:** all 1000 frames do not fit the 30 MiB budget (about
138 kB of atlases per displayed frame across the eight cases, even with
indexed PNGs and shared images, so 1000 frames would need about 138 MB). The page shows 126 actual recorded frames: k = 0, 8, …, 992
and 999, which include frames 0, 200 and 999. That is an 8 ms spacing, with
7 ms before frame 999. The same indices and timestamps are used by the pupil
maps, the PSFs, the chart cursor and the galaxy panel. Nothing is
interpolated, and the means always use all 800 analysis frames.

**Playback:** one pass over the recorded physical interval [0.000, 1.000) s
takes 20 s (default), 25 s or 30 s, so 20–30× slower than real time; 30 s with
reduced motion. Timing follows the recorded timestamps: each displayed frame
is held from its own timestamp until the next displayed one, and frame 999 to
1.000 s. A late timer never skips a frame. The main viewer and the galaxy
panel share one playback state and one clock (`playback.js`): the case, the
displayed frame, play/pause, the duration, the view mode and the optional
loop. The loop is set in the galaxy panel, applies to both panels, and
replays the same recording from frame 0 without extending the simulation.

**Size:**

| Item | Bytes |
| --- | --- |
| Dataset bundle (105 members + manifest) | 10,317,085 |
| Galaxy derivative (revised records and manifest, plus the original images and scene record they reference in place) | 11,320,841 |
| Research Results, referenced in place from the previous dataset | 2,169,356 |
| RMS diagnostics (eight case records and manifest) | 214,013 |
| Page and code (build `cc930a7cabb85c53`) and entry | 172,203 |
| **Active site, everything this entry can load** | **24,193,498 (23.1 MiB; budget 30 MiB)** |
| First view (default case, without the lazily loaded galaxy images) | 1,951,896 (budget 5 MiB) |

Six images are stored once and shared by the six cases with the baseline
atmosphere: the atmosphere-map and uncorrected-PSF atlases, the uncorrected
mean PSF, the uncorrected binary observation, and the uncorrected galaxy atlas
and mean. The whole `web/ao-explorer/` directory, including the preserved
180-frame dataset (11.6 MB), its galaxy derivative (4.8 MB) and the
superseded records of the exported 1000-frame derivative (0.6 MB), is about
38 MB. The active page never loads those preserved directories, but a
publication of the directory as it stands would exceed 30 MiB.

The page keeps lazy loading (galaxy data only when its panel is in view, at
most two decoded cases per view, superseded requests aborted), keyboard
controls, the mobile layout rules and the source credits. The OPD colour
limit is ±1950 nm (the earlier dataset used ±1500 nm), from the same 99.5th
percentile rule over all 1000 frames of all eight cases. OPD atlases now use
255 display levels plus one transparent exterior index.

## Provenance and identities

- **Production identity** `c7241e4190d54b8896db391351e17d5973ab05e2c4063b453906521f3423c53e`.
  It is the digest of the producer files, the core package, the screen-related
  core files, the constraint lock and the numerical environment. The working
  tree was uncommitted (base commit `d9e82004693812aeda307999cb2d54ddf85213c1`),
  so this content digest, not the commit, identifies the code. Every case
  record carries it, and the exporter refused to run unless it still matched.
- **Plan** `outputs/ao_explorer_1s/series-2m1000-s624-c7241e4190d5/plan.json`.
  It binds the frozen plan of `series-2m180-b3e1c66` by SHA-256.
- **Environment:** Python 3.14.3, NumPy 2.5.0, SciPy 1.18.0, arm64 macOS 26.5,
  the locked `constraints/hcipy-py314.txt` environment (lock verified).
  Host: Apple M1 Pro, 8 logical CPUs, 16 GiB.
- **Seeds and screen:** root seed 1, realization 0; 624 × 624 screen.
- **Frames:** 1000 retained per case; 126 displayed; mean window [200, 1000),
  800 frames.

Source files at production and export (SHA-256):

| File | SHA-256 |
| --- | --- |
| `src/shwfs_ao/experiments/scao.py` | `60b7436bff102b492985471e8c478485f3d996fdc70431319b2510c48de145f0` |
| `src/shwfs_ao/backends/native/factory.py` | `a16716a3c5e7f661764fa2d4d1cbea07e92613a826df0bfa9eb0f12abe68e420` |
| `src/shwfs_ao/experiments/__init__.py` | `a7f0329e64ca9116e6ef66291353669d743dbce13cd1bd33b7fe43c1ca4df4e9` |
| `src/shwfs_ao/backends/native/atmosphere.py` (unchanged) | `7d6c57af32be1a1957288ace7ef00bd3f555d4584baa66d2d065bd1d23cc69a3` |
| `src/shwfs_ao/control/loop.py` (unchanged) | `b4e645c22e677fbdce2a9562efb4f1e4d41a02ccba97711d6011fccd1820d27f` |
| `scripts/ao_explorer/long_series.py` | `53a97fa4584400dc8b75d44a691b3078b1796d79910acd60bc53f10a6c26f55d` |
| `scripts/ao_explorer/long_export.py` | `c6c53ce6d434f6d79f4dfdcdbc651b4e2b769887e40c91ca8d1f890b9bc62bb9` |
| core package tree digest | `d95f830601acfea74ce4a3b4e24769fc786fa7a8365e0fb4bec62fad875fe53d` |

The historical producer files (`protocol.py`, `identity.py`, `admission.py`,
`observer.py`, `producer.py`, `run_job.py`) and exporters (`render.py`,
`galaxy_export.py`, `galaxy_scene.py`, `galaxy_template.py`,
`binary_scene.py`) are byte-identical to the identities recorded by the
earlier dataset and derivative. That is why the new trajectory length and
window live in `long_series.py` and `long_export.py`, which import them,
instead of being edited into them. `tests/test_wheel_install.py` only lists
the new public name `FrozenFlowScreenOptions`.

The full digests of every web member are in the two manifests. The digests of
every archive and derived array are in the case records and in
`outputs/ao_explorer_1s_derived/series-2m1000-s624-c7241e4190d5-ef74a541b0e60/export_record.json`.
No earlier validation record is used as evidence for this dataset.

The table gives the sources as they were when the arrays and images were
generated. After the export, the repairs below changed `long_export.py`
twice. First, to `98b44b1218a0a18682454e6db345c76b72e092f986d7d36947e26f395e060e4b`
(the flux-file record). Then, to
`3adc3074287a874abe19ee5f354974ffd9055a4043fa738feafec2dd2a4b3a48` (the RMS
diagnostics call and the corrected limitation and block-notice wording).
Neither version generated anything in this dataset; the generation identity
recorded in every bundle stays `c6c53ce6…`. **Engineering closeout, 2026-10-27:** `long_export.py`
changed a third time, to
`45cfb23088068b2a6d7a4a2166492cf9ae62500b7ceca2a42c97775f99d5a920` (the producer
checks of a case record judged by the validator's rule, `web_contract.producer_check_problems`,
instead of a truthiness filter over the booleans present). It generated nothing
in this dataset either, and was tested on synthetic records only. `rms_diagnostics.py`, which wrote
the RMS derivative, is
`e7e343b4f8dac065f6714618f379f6c245b92040f091fb06f0e64ca85d202cf6`.

## Limitations

- One realization of each case, one seed; no ensemble, no confidence interval.
  No seed-sensitivity or observer-passivity check was run for this dataset.
- One second of simulated time with a 200-frame exclusion establishes
  neither convergence nor instability. The residual varies as the frozen-flow
  realization moves across the pupil; the mean over frames 200–999 is valid for
  that window but is not shown to be a converged long-exposure PSF.
- The page shows a subset of the frames; the other frames have scalar records
  and full-precision images outside the site but are not displayed, and
  nothing between displayed frames is interpolated.
- Frame-start snapshots: the averages are equal-weight means of instantaneous
  images, not a finite-shutter exposure.
- The galaxy view inherits every limitation in `GALAXY_OBSERVATION.md`:
  observed F814W morphology with monochromatic 1.65 µm kernels, HST resolution
  and noise kept, a saturated core known only approximately, source membership
  not determined, one on-axis kernel over the field.
- `validate.py` was written for the 180-frame (`*.v1`) schemas. It was not
  extended to, or run on, this dataset or its derivatives, and no browser or
  runtime check was made of the updated page. **Update 2026-10-27:**
  `validate.py` now selects this dataset's contract from the committed schemas
  (`scripts/ao_explorer/web_contract.py`, values from `long_series.py`) and
  accepted the committed bundle as it stands, verifying the preserved
  dataset's Research Results in place; the galaxy and RMS derivatives are still
  covered only by `check_bindings.py`, and raw-evidence mode was not run
  against the archives. **Update 2026-10-27 (later):** the producer checks each
  provenance record copies are now required to be present and literally true,
  with the [200, 1000) window and 800 frames; raw-evidence mode is tested on
  synthetic archives only and has still not been run against these archives.
- The RMS diagnostic describes the saved wavefronts only. Fitted tilt is not
  image-centroid motion, and the decomposition does not attribute causes.

## Repairs after the export

Made on 2026-10-23 without rerunning any simulation or observation
generation. The numerical archives, the derived arrays and every image byte
were reused unchanged.

**Shared playback.** The main viewer and the galaxy panel used to keep
separate positions, play states and timers. They now share one playback
state and one clock (`web/ao-explorer/code-<build>/playback.js`), which both
modules import from the same URL.

- Play and Pause, Restart, Step, either seek slider, and either duration
  select change that one state. Both panels then render the same case and the
  same recorded frame and timestamp: the pupil maps, the instantaneous PSFs,
  the chart cursors and readouts, and the galaxy observations.
- Main "Instantaneous" and galaxy "Sampled instantaneous" are one mode, and
  main "Analysis-window average" and galaxy "Analysis-window mean" are the
  other. Choosing either average pauses playback and disables the time
  controls of both panels. Returning to instantaneous mode keeps the position
  and does not start playback.
- A case change pauses playback and keeps the displayed-frame position.
- The galaxy panel still loads lazily, keeps at most two decoded cases, and
  aborts superseded requests. Until the selected case's galaxy assets are
  verified it shows a loading state and no image, never the previous case.
  When they arrive it renders the current shared frame and mode.
- The optional loop operates the shared clock, so both panels restart
  together. It is labelled as repeating the same recording.
- Durations (20, 25, 30 s; default 20, 30 with reduced motion), the 126
  displayed frames, the timestamp holds, the final interval to 1.000 s and the
  no-interpolation rule are unchanged and still read from the metadata.
  `site_build.CODE_FILES` now includes `playback.js`.

**Flux-file reference.** The exported galaxy records named
`sampled.roles.<role>.flux.all_frames.file = "flux.npz"`, a file that was
never written. The file written for every case is `flux_and_means.npz`.

- The generator (`long_export.py`) now records the actual file.
- The active records were corrected as a metadata revision by
  `scripts/ao_explorer/long_metadata_revision.py`
  (`85baf2b59f99b7fa8ad942bb0184979fe2417363bf38bdb72380e7cf26593765`). For
  both roles of all eight cases it records the file's name, path, directory
  (`outputs/ao_explorer_galaxy/ngc1705-f814w-2m1000-s624-c7241e4190d5-gda93ed5af026/<case>/`),
  size, SHA-256 and array names.
- The revised records live in the new directory `…-gda93ed5af026-m4adb5a4af111`.
  Their image and scene references resolve to the original files, which stay
  in place byte-identical; the exported directory is not overwritten.
- The revised manifest carries a `metadata_revision` block naming the
  superseded derivative and manifest digest (`269ca9714e8c08be…`), the
  correction and the revision tool's identity. Its `code_identity` is still
  the generator's.
- The revision also replaces the one mean-mode limitation sentence that
  asserted non-convergence.
- Correction record:
  `outputs/ao_explorer_1s_derived/series-2m1000-s624-c7241e4190d5-ef74a541b0e60/galaxy-metadata-revision-ngc1705-f814w-2m1000-s624-c7241e4190d5-gda93ed5af026-m4adb5a4af111.json`.
- The numerical archives were neither renamed nor rewritten. The dataset
  bundle is unchanged, so its case provenance still names the derivative as
  exported (`…-gda93ed5af026`).

**Convergence wording.** The page and this record no longer equate a
fluctuating residual with an unconverged or unstable controller. See
[Interpretation](#interpretation). The exporter now writes the same
distinctions into new exports:

- In the galaxy mean-mode limitation, the categorical "It is a discrete
  average of frame-start snapshots of one realization, not a converged long
  exposure." became "This is an intensity average of 800 frame-start PSFs from
  one realization over the declared 0.200–1.000 s interval. This record alone
  does not establish convergence to a long-exposure PSF."
- The block-summary notice now separates controller settling (the 200-frame
  exclusion is not a demonstrated settling time), fluctuations along the
  frozen-flow realization (r0, L0 and wind fixed; no divergence or turbulence
  change implied), and convergence of the finite-window average.

The active galaxy metadata already carries equivalent corrected wording (its
metadata revision). The active dataset's `blocks.json` keeps its exported
notice, and the page adds the distinction next to it; no historical record
was rewritten.

## Operations run

Production (2026-10-23, 17:15–17:51 UTC):

- `long_series.py plan`;
- `long_series.py supervise`: eight children under `run_supervised` with two
  native threads, a 3 h per-case timeout, a 12 h wall and 12 GiB storage
  ceiling, and the resource guard at its default (memory enforcement off; the
  preflight ran and raised no advisory). All eight first attempts
  completed.

| Case | Loop (s) | Child wall (s) | Peak RSS (MiB) |
| --- | --- | --- | --- |
| baseline | 271.6 | 273.7 | 310 |
| weaker-turbulence | 270.3 | 272.3 | 339 |
| stronger-turbulence | 268.5 | 270.7 | 275 |
| lower-gain | 253.4 | 255.4 | 283 |
| higher-gain | 253.6 | 255.5 | 322 |
| brighter-guide | 254.5 | 256.4 | 325 |
| fainter-guide | 252.8 | 254.9 | 325 |
| longer-delay | 253.3 | 255.3 | 325 |

Total supervised wall time: 2097.6 s (35.0 min).

Derived export:

- `site_build.py --write`, before the export, to give the updated page code
  its build;
- `long_export.py`: 43.6 s, peak RSS 523 MB. It re-hashed every archive,
  wrote the block summaries, convolved 16,000 instantaneous PSFs and 16 mean
  PSFs with the template, built both browser bundles and switched the entry;
- `site_build.py` (check mode): consistent.

Output sizes:

| Location | Bytes |
| --- | --- |
| `outputs/ao_explorer_1s/series-2m1000-s624-c7241e4190d5/` | 3,648,333,447 |
| `outputs/ao_explorer_galaxy/ngc1705-f814w-2m1000-s624-c7241e4190d5-gda93ed5af026/` | 3,118,931,787 |
| `outputs/ao_explorer_1s_derived/series-2m1000-s624-c7241e4190d5-ef74a541b0e60/` | 3,411,239 |
| New web bundles | 21,607,386 |

These are about 6.79 GB in all, outside Git except the web bundles.

RMS diagnostics (no simulation, observation generation or export rerun):

- `rms_diagnostics.py`: 1.6 s, peak RSS 232 MB. It re-hashed the residual
  archives, matched the 8000 maps to their recorded digests, fitted the
  planes, wrote the site derivative (214,013 bytes) and the full-precision
  arrays (0.3 MB), and added the `diagnostics` block to the entry.
- `site_build.py --write`: build `cc930a7cabb85c53`, consistent.
- Later, a frontend-only fallback repair (per-case optional diagnostics) and
  `site_build.py --write`: build `3b85a599186cdf30`. No data file changed.
- A check that both derivatives' manifests match the entry and that every
  diagnostic case record names its case's metrics digest.

Repairs (no simulation, observation generation or export rerun):

- `long_metadata_revision.py`: verified the active galaxy bundle, wrote the
  revised records and manifest, and switched the `galaxy` block of the entry.
  It then resolved each re-pointed reference against the original bytes.
- A read-only computation of the half-window baseline figures above from the
  archived records and PSF stacks.
- `site_build.py --write`: build `bdf5c16779758cd4`, consistent.

Not run: the test suite, pytest, CI, `validate.py` or any other standalone
validator, any browser check of the updated page, benchmarks, convergence
scans, a pilot, a control or a seed-sensitivity job. Nothing was committed,
pushed or deployed.
