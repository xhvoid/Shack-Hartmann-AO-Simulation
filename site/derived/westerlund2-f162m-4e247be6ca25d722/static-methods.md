# Westerlund 2 F162M: three archived AO epochs

Local preview, 2026-10-30. No AO simulation was run, no baseline or 42 m trajectory was regenerated, and no website files were changed. Only spatial extraction, calibrated-image resampling, Fourier optics from existing OPD samples, convolution, and plotting were performed.

## Files

- `westerlund2-f162m-three-epochs.png` and `.pdf`: principal comparison, including the observed source, no AO, original v1, repaired v2, and the complete archived Strehl curves.
- `westerlund2-f162m-three-epochs-quality.png` and `.pdf`: the same comparison with a common, conservative outside-star sensitivity mask. Inspect this before interpreting features near the field edges.
- `westerlund2-f162m-field.png`: native source cutout and its location in a 30 arcsec context, with contributor saturation flags.
- `source-cutout.fits.gz`: unchanged native SCI, ERR, and WHT samples with the cutout WCS.
- `linear-comparison.npz`: unmasked linear surface brightness arrays, in MJy/sr. The display stretch is not applied to these arrays.
- `selected-psfs.npz`, `scene-context.npz`, `saturation-sensitivity-map.npz`, and `results.json`: numerical evidence and provenance.

## Epochs and the meaning of the loss marker

| Zero-based frame | Time (s) | No AO Strehl | Original v1 Strehl | Repaired v2 Strehl |
|---|---:|---:|---:|---:|
| 735 | 0.980000 | 0.229564 | 0.560651 | 0.607803 |
| 736 | 0.981333 | 0.228533 | 0.535437 | 0.624668 |
| 1499 | 1.998667 | 0.218831 | 0.104259 | 0.714947 |

Frame 736 is the first rejected v1 reconstruction. Its separation from frame 735 is only 1.333 ms. A rejected reconstruction does not imply that the instantaneous image must collapse in that same sample. The marked images use the archived pre-update residual OPD convention. The later loss of correction is visible in the end-of-trajectory comparison. All Strehl labels refer to the archived monochromatic point-source PSF, not a measurement from these stellar images.

## Source and field selection

The source is the public [MAST F162M mosaic](https://mast.stsci.edu/api/v0.1/Download/file?uri=mast:JWST/product/jw03523-o005_t001_nircam_f150w2-f162m_i2d.fits), JWST program 3523 (EWOCS), observed 2024-07-14. It is a single calibrated intensity band, not a colour composite. The archive product uses calibration pipeline 3.0.0 and CRDS context `jwst_1584.pmap`. It is not claimed to reproduce a publication's custom reduction.

F162M is in the pupil wheel with the F150W2 blocking filter. The [NIRCam filter documentation](https://jwst-docs.stsci.edu/jwst-near-infrared-camera/nircam-instrumentation/nircam-filters) lists pivot wavelength 1.627 µm and bandwidth 0.168 µm. The reused simulation PSF wavelength is 1.65 µm, approximately 1.4% longer than the pivot; no spectral integration or new wavelength-dependent AO calculation was made.

The displayed field is **4.109182 × 4.109182 arcsec**, sampled at 0.05136477 arcsec per model pixel. It is a small outer field within the Westerlund 2 observation, not a panorama of the cluster core and not a membership-selected stellar catalogue. Native pixels are 0.03123098 arcsec. The zero-based mosaic centre is [9090.0, 3670.0]; ICRS centre is (156.025553144, -57.746775668) degrees. Native mosaic orientation is retained; offsets are not labelled as RA/Dec axes.

The dense core has many saturated bright stars. A preliminary NRCB3 field was rejected because surrounding bright stars leaked strongly into its image edges. The final NRCB1 region was selected by the source appearance, saturation clearance and absence of strong diffraction spikes. A small shift and expansion then placed the three brightest displayed sources at least 0.59 arcsec inside the cutout. This was not a search for the largest v1-v2 difference.

All four associated NRCB1 calibrated exposure DQ arrays were checked. The SATURATED bit is 2 in the [JWST DQ definitions](https://jwst-pipeline.readthedocs.io/en/latest/jwst/references_general/references_general.html). Pixel centres were mapped through the exposure TAN-SIP and mosaic WCS, then guarded by eight mosaic pixels (0.250 arcsec). No guarded SATURATED pixel and no missing SCI/ERR/WHT sample falls directly within the displayed field. This conservative positional screen is not a proof that every source is perfectly linear or that all optical artifacts have vanished.

The full kernel context still contains bright and saturated stars. Zeroing or doubling the supplied mosaic values in their guarded regions changes some edge pixels. The companion quality figure excludes the same **18.28%** of display pixels in all twelve panels, using a threshold of 0.8 MJy/sr (1% of the common display span) on the maximum perturbation across all nine model images. No reference pixel above 20 MJy/sr is masked. The maximum tested change in the retained region is 0.799932 MJy/sr. These probes are not bounds on unknown true saturated flux. Faint background knots and edge ghosts in the unmasked preview should not be interpreted as measured stellar structure.

## Processing and fixed display

Calibrated surface brightness is area-averaged onto the existing PSF grid in linear units, then convolved with the full 768 × 768, unit-flux PSF. Source context covers the entire kernel footprint. No sky wraparound, kernel enlargement, source sharpening, PSF recentering, or panel-dependent flux normalization is used. The original tilt is retained. A delta-kernel check verifies the crop alignment. Sparse missing samples in the wider context are nearest-valid filled; zero/twice-fill sensitivity is at most 0.125490 MJy/sr in the display.

Every panel uses the same 0–80 MJy/sr asinh scale, with softening 2 MJy/sr and the same magma pseudocolour map. Upper and lower display tails are clipped only for visualization. Pixel display interpolation is nearest-neighbour. This is a matched-band imaging illustration: the observed JWST PSF, mosaic resampling, diffraction structure and noise remain in the scene. No deconvolution, additional detector noise, exposure integration, anisoplanatism or real Robo-AO-2 observation prediction is included. One on-axis monochromatic PSF is applied over this small field. Consequently the effective response contains both the observed JWST response and the simulated 2.2 m PSF.

## Verification

Archive input and downloaded source-stripe hashes agree with their recorded provenance. All four final-field DQ hashes were also verified. The nine selected point-source Strehls agree to 4.44e-16; 3 available archived PSF snapshots agree to 2.78e-17 per pixel. Full-convolution flux conservation has maximum relative error 4.39e-16, and delta-kernel alignment has maximum error 3.71e-13 MJy/sr. Existing tracked dirty inputs were hash-checked unchanged. No CI or project test suite was run.

Reproduction uses `render_static.py` and the retained downloaded ranges and archived inputs. `source/source-extraction.json` and `source/quality-extraction-b1.json` record original URLs, byte ranges and SHA-256 hashes; `results.json` records the AO input hashes and all per-panel sensitivity values. Intermediate candidate-selection files are diagnostic history, not alternative published results.

Credit: NASA / ESA / CSA JWST, program 3523 (EWOCS), MAST / STScI. See the [MAST data-use guidance](https://archive.stsci.edu/publishing/data-use).
