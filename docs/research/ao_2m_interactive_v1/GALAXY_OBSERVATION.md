# Observed galaxy template: NGC 1705 through the simulated PSFs

> **Scope of this record.** It describes the template preparation and the
> galaxy derivative of the earlier 180-frame dataset
> (`series-2m180-b3e1c66-e0d60cbaccc6b`, derived set
> `ngc1705-f814w-2m180-b3e1c66-g1007a60a01ae`), which is preserved unchanged.
> The active site now shows a derivative of the 1000-frame dataset, which
> reuses the prepared template described here unchanged; it is documented in
> [ONE_SECOND_DATASET.md](ONE_SECOND_DATASET.md), including its later metadata
> revision (corrected flux-file reference) and shared playback. The 40-sample, 140-frame and
> 180 ms statements below belong to the earlier derivative only.

This is an additive view of the explorer. A fixed template is seen through
the PSFs that the published 2 m run already saved. The template is the
central region of NGC 1705 from the calibrated LEGUS HST/WFC3 F814W mosaic,
at its real angular scale.

It replaces an earlier draft, never committed or published, that used an
analytic host plus three Gaussian clumps. That draft's generated assets were
removed and its scene identity is not reused.

Nothing was re-simulated: no AO replay, no new atmosphere, no random numbers
and no added noise. The published dataset
`series-2m180-b3e1c66-e0d60cbaccc6b`, its binary scene, metrics and evidence
are byte-identical to before.

## Method

The method is source -> optical PSF -> observed image (Leschinski et al.
2016, *SimCADO*, section 3.4 and Figure 3). It uses an observed HST/LEGUS
image of NGC 1705 as the source template, as Simioni et al. (2026), *MICADO
clumps at cosmic noon*, section 5.2 and Figure 5, did. Their three-copy
arrangement and assumed redshift are not reproduced. None of their
MICADO/ELT resolution, exposure or sensitivity assumptions is transferred.

For each case:

- **Sampled mode:** `T (*) psf_uncorrected[k]` and `T (*) psf_corrected[k]`
  for the 40 retained samples of `movie.npz`, at their recorded indices and
  times (0–179 ms, irregular).
- **Mean mode:** `T (*) mean_psf_uncorrected` and
  `T (*) mean_psf_corrected` from `mean_psfs.npz`, the saved means of all 140
  post-burn-in frames. For a fixed `T` this equals the mean of the 140
  per-frame observations. It is not the average of the movie samples, and the
  `own_mean_psf_*` arrays are not used.

How the convolution is done:

- `*` is discrete linear convolution with zero extension, computed by real
  FFT on arrays zero-padded to 480 × 480. That is at least the full
  312 + 156 − 1 = 467 samples per axis, so there is no wraparound.
- The output is cropped to the native 156-cell window by angular coordinates
  and is not renormalized.
- `T` covers twice the PSF window: 312 cells, 17.4″. Every sample in the
  window therefore receives the full contribution of all template light
  within the kernel's reach, so light outside the shown field is not treated
  as zero.
- The display stretch is applied only after convolution and averaging.

## Data source

**Science image:** `hlsp_legus_hst_uvis_ngc1705_f814w_v1_drc.fits`, LEGUS v1
high-level science product on MAST,
<https://archive.stsci.edu/hlsps/legus/ngc1705/hlsp_legus_hst_uvis_ngc1705_f814w_v1_drc.fits>,
listed in the LEGUS public data table (NGC 1705 row).

| Property | Value |
| --- | --- |
| Retrieved | 2026-10-23T15:56:22Z |
| Size | 153,898,560 bytes |
| SHA-256 | `fac242cbfa9dd445fe0740e382467f958b9737abd7168c5d429db9f9951a78c7` |
| Science data | primary HDU 0 (6200 × 6200, float32); HDU 1 is a header table |
| Units | `BUNIT = ELECTRONS/S` per output pixel |
| Instrument and filter | HST WFC3/UVIS, `PHOTMODE = WFC3 UVIS2 F814W CAL`, pivot 8027 Å |
| Programme | GO-13364 (LEGUS, PI D. Calzetti; Calzetti et al. 2015, AJ 149, 51) |
| Exposure | 989 s in 3 exposures (381 + 381 + 227 s) |
| Drizzle | gaussian kernel, pixfrac 0.9, output scale 0.03962″ |

The public mosaic carries no weight or context map. Its header names
`f814w_exp_drc_wht.fits`, which is not part of the product.

**Quality data:** the three aligned F814W FLC exposures from the same LEGUS
directory, each 168,157,440 bytes, used only for their data-quality (DQ)
flags:

| File | SHA-256 |
| --- | --- |
| `hlsp_legus_hst_wfc3_ngc1705-icdm57rkq_f814w_v1_flc.fits` | `09c4b13f0cd0a58b…` |
| `hlsp_legus_hst_wfc3_ngc1705-icdm57rmq_f814w_v1_flc.fits` | `d47419ff2457c887…` |
| `hlsp_legus_hst_wfc3_ngc1705-icdm57roq_f814w_v1_flc.fits` | `9621d56b0991e542…` |

The full digests are in the template record.

All four files are kept read-only in the implementation worktree's ignored
`outputs/ngc1705_inputs/` and are not part of the site or Git.

**Band policy:** F814W (red optical, I band) morphology is used as a fixed
relative-intensity template with the monochromatic 1.65 µm PSFs. There is no
colour, no spectral conversion and no Hα, and this is not an H-band
prediction.

**Credit:** HST/WFC3 UVIS, GO-13364 (LEGUS); hlsp_legus_hst_uvis_ngc1705_f814w_v1
from MAST. The ESA/Hubble picture potw2205a (credit ESA/Hubble & NASA,
R. Chandar) is cited as a visual reference only, not as the numerical input.

## Crop, angular scale and orientation

**Centre:** the flux-weighted centroid, within 6 px, of the brightest pixel
within 15″ of the target position, which is the super star cluster
NGC 1705-1. That is RA 73.555335°, Dec −53.360953° (04h54m13.28s,
−53°21′39.4″), at mosaic pixel (3986.41, 3793.70), counted from 0.

**Cutout:** mosaic pixels x 3766–4207, y 3573–4014, counted from 0.

**Input WCS:** TAN projection with the distortion removed by drizzle:

- 39.6201 × 39.6201 mas per pixel;
- grid rotation 1.0e-4° and skew −1.1e-4° on the projection plane;
- north up, east left (the CD determinant is negative).

**Target grid:** the lattice of the saved PSFs, using their actual step of
55.632 mas:

- 312 × 312 cells, with the exact zero sample at the centre;
- angular scale factor **1.0**;
- +x is west and +y is north on the mosaic's projection plane.

At the template centre, local north differs from +y by 0.013° (meridian
convergence, about 43″ from the tangent point). This is recorded. The local
scale differs from the plane scale by less than 1e-7.

The simulated PSFs have no sky orientation of their own, so north-up is a
presentation choice.

**Reprojection:** exact separable pixel-area integration. Each cell sums
every input pixel's count rate times the fraction of that pixel's area
inside the cell. This conserves flux to a relative error of 0.0 (equal sums),
and adds one cell-box response R. The input's own pixel and drizzle
response is not added again.

**Observation crop:** declared separately from the 64-cell crop of the PSF
panels. It is the central 128 × 128 cells (7.12″) of the native window,
shown at 2 screen pixels per cell. A 1″ scale bar is drawn on all three
panels.

## Sky, quality and noise

- **Sky.** The mosaic is already sky-subtracted by the pipeline. The 3σ-clipped
  median of covered pixels beyond 120″ is 6.7e-4 e⁻/s per pixel. The galaxy's
  envelope is still declining at that radius, so this is an upper bound on
  residual sky and was **not subtracted**. Subtracting it would change the
  template flux by 0.25 %.
- **Saturation.** DQ flags were mapped from each exposure by taking the
  nearest exposure pixel through its aligned WCS. This approximates, but is
  not, each exposure pixel's drizzle footprint. Every cutout pixel is covered
  by all 3 exposures. The core of NGC 1705-1 is **saturated in all three
  exposures**. Two regions are recorded, and neither is an exact extent:
  - **Approximate saturated core** (no dilation): 19 mosaic pixels whose
    nearest exposure pixel is flagged in every exposure (x 3983–3990,
    y 3791–3797, bounding box about 0.28″ × 0.24″).
  - **Conservative envelope**, which the page marks with a dashed box: each
    exposure's flags dilated by one mosaic pixel, then intersected. That is
    51 pixels (x 3982–3991, y 3790–3798, about 0.36″ × 0.32″), touching 38
    template cells. It deliberately includes unsaturated neighbours.
  - The delivered values in these regions hold 5.1 % (core) and 10.9 %
    (envelope) of the cutout flux. Both numbers depend on the approximate
    region definitions and are limited by saturation. They are neither the
    core's true flux nor a bound on it; the true core flux is not recoverable
    from these data.
  - With the saturation and cosmic-ray flags dilated (an upper estimate),
    25 more scattered pixels within about 3″ of the core have no usable
    exposure.
- **Treatment.** There is no repair, fill, clipping, masking or deconvolution.
  The delivered values are kept and disclosed: the core is not a faithful
  profile or flux, and no detail is invented.
- **Membership.** No object was masked, and all observed structure in the
  cutout is retained. Membership in NGC 1705 was not determined for
  individual sources, so unrelated foreground stars or background galaxies
  cannot be excluded from this single band.
- **Noise.** The residual observational (correlated, drizzled) noise is
  retained. No denoising or smoothing is applied and no noise is drawn. The
  template has 0 negative cells.

## Hubble PSF policy

The template is HST-resolution-limited observed morphology, not an intrinsic
source: `T ~ R (*) (O * H_HST + n_HST)`. The output `I_k = T (*) P_k`
therefore keeps Hubble's effective F814W response (optics, detector, drizzle)
and noise, adds R once, and adds the simulated PSF `P_k`.

No HST PSF model was fitted, so the HST PSF is **not quantified**. A crude
second-moment check on 23 isolated, unsaturated point sources 25–60″ from
the centre gives FWHM ≈ 88 mas (quartiles 72–123 mas). The value depends on
the estimator; it is an indication, not a measured PSF. For comparison,
λ/D is 170 mas for the simulated 2 m aperture.

The AO-corrected panel cannot recover detail absent from the HST image. The
AO Strehl values describe the simulated PSFs, not the sharpness of these
images.

## Normalization and flux accounting

- `T` is normalized once to unit total over the 17.4″ cutout. One unit is
  51,143 e⁻/s in F814W.
- 54.9 % of the template lies inside the native 8.7″ window.
- In every image the full convolution flux equals template flux × kernel
  flux to ≤ 6.7e-16.
- The fraction of the convolved template flux inside the native window is
  0.545–0.548 for every sample and case. This is the galaxy's own extended
  light beyond the field, not a loss; it is recorded per sample, together
  with the fraction inside the 7.1″ display crop.

## Display and playback

The interface, playback and case loading are reused unchanged from the
earlier draft.

**Display:**

- One fixed asinh stretch (β = 0.001), referenced to the brightest template
  cell, with the inferno colormap. That cell lies in the saturated core region, so
  it is a fixed display number, not a physical peak.
- The same scale is used for the template, every sample, both mean images,
  both roles and every case. No image is normalized to its own maximum.
- Images are 8-bit indexed PNGs whose palette is the recorded colour table.

**Playback:**

- One pass over the recorded 0–180 ms takes 8 s, 12 s or 20 s; 8 s is the
  default, and 20 s with reduced motion.
- Each retained sample is held until the next retained timestamp.
- The readout shows simulated time separately from the playback duration.
- Looping is optional; a loop repeats the same realization.
- Nothing is interpolated, and a late timer never skips a sample.

**Mean mode** disables the timeline.

**Loading:** the galaxy data load only when the panel is in view. At most two
decoded cases are cached. A superseded request is aborted, and a late response
is never installed.

## Outputs and identities

- **Site:** `web/ao-explorer/derived/ngc1705-f814w-2m180-b3e1c66-g1007a60a01ae/`,
  42 members, 4.81 MB plus a 30.4 kB manifest. Each case has a record, two
  1024 × 640 sampled atlases and two mean images. The template record and
  display image are stored once. At its export, `data/current.json` bound the
  manifest under `galaxy` (schema `ao-explorer.galaxy-entry.v2`); the entry
  now names the 1000-frame derivative instead, and this directory stays in
  place unchanged.
- **Identities:**
  - template id `412ebe536d81ed5e886e4ac1eb58b7ae8f7eb38b2116c1d570ce875dd3d4dffd`
    (the template array is unchanged; the id covers the corrected quality
    record);
  - template array SHA-256
    `9c176c789c0c8aa3ded8ac4874b603c9450dd71eaa58edf0389d701372bb36b6`;
  - exporter code `1fe38de4d10b3d44…`;
  - schemas `ao-explorer.observed-template.v1` and `ao-explorer.galaxy-*.v2`.
- **Full precision:** the arrays are in
  `outputs/ao_explorer_galaxy/ngc1705-f814w-2m180-b3e1c66-g1007a60a01ae/`,
  outside the site and Git.
- **Build:**
  - `galaxy.js` and `site_build.CODE_FILES` were added in the earlier draft;
  - the code build is now `47635715adc0a88c` (`site_build.py --write`);
  - the validation records under `validation/` stay bound to the unchanged
    dataset manifest.

## Reproduce

```bash
python scripts/ao_explorer/galaxy_export.py --series-dir <abs>/outputs/ao_explorer_v1/series-2m180-b3e1c66 --template-fits outputs/ngc1705_inputs/legus_v1/hlsp_legus_hst_uvis_ngc1705_f814w_v1_drc.fits --quality-flc outputs/ngc1705_inputs/legus_v1_flc_f814w/*_flc.fits --web-dir web/ao-explorer --output-dir outputs/ao_explorer_galaxy --input-manifest <FILE_MANIFEST.json>
```

The exporter refuses to overwrite an existing derived directory.

## Limits

- The input is observed F814W morphology, used with monochromatic 1.65 µm
  kernels. There is no claim about the galaxy's true near-infrared surface
  brightness, photon counts, sensitivity, signal-to-noise ratio or broadband
  performance.
- The template keeps Hubble's resolution and noise, and its brightest core is
  saturated. The saturated extent is known only approximately, and the page's
  dashed box is an enlarged envelope.
- Membership in NGC 1705 was not determined for individual sources; all
  observed structure, possibly including unrelated objects, is retained.
- One on-axis kernel is assumed over a compact field, with no off-axis AO
  correction. Fitting the crop inside the grid does not establish
  field-dependent validity.
- Only 40 of the 180 frames have saved PSFs, and the stored mean cannot be
  inverted into the missing ones.
- Mean mode is the existing discrete average, not a new long exposure. Slower
  playback and looping do not lengthen the simulated 180 ms.
- On phone-width screens (375 px) the scale bar's "1″" label is drawn at
  canvas resolution and becomes very small. The bar itself and the caption
  that states its 1″ length remain readable.
- `validate.py` has never checked the new `galaxy` block in
  `data/current.json` or the `derived/` directory. It was not run, and its
  rules were written before these additions, so whether it accepts or covers
  them is unknown.

## Checks performed

- The export's own fail-closed input bindings: AO inputs against the
  provenance records and `FILE_MANIFEST.json`; the template product against
  its recorded digest and header.
- Flux checks.
- `site_build.py --write`.
- Visual inspection of the generated images.
- A local browser inspection at desktop width and 375 px: playback timing,
  mean mode, case switching and horizontal overflow.

The test suite, `validate.py`, other scientific validators and CI were not
run. Nothing is committed.
