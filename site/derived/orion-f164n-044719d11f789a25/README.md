# Orion F164N: a calibrated image experiment

A public JWST/NIRCam F164N observation replaces the multiband NGC 602 illustration.
The AO input, original/repaired controllers, saved wavefronts, timing and Strehl
curves are unchanged. This is post-processing of the existing 2.2 m recording.

## Source and band

- Product: `jw01288-o001_t011_nircam_f150w2-f164n_i2d.fits`.
- MAST: https://mast.stsci.edu/api/v0.1/Download/file?uri=mast:JWST/product/jw01288-o001_t011_nircam_f150w2-f164n_i2d.fits
- Program 1288, PDRs4All, PI Olivier Berne; NASA/ESA/CSA JWST NIRCam.
- This is the public MAST pipeline product, not the team's custom reduction.
  Source headers specify pipeline 3.0.0 and CRDS jwst_1584.pmap.
- F164N is in the pupil wheel with F150W2 as its blocking filter. Its effective
  band is F164N, not the entire F150W2 band. Pivot wavelength 1.645 um; bandwidth
  0.020 um. The saved monochromatic model uses 1.65 um, a 0.30% pivot mismatch.
  Band integration is approximated, not recalculated. F164N contains continuum
  and emission lines; this is not a continuum-subtracted [Fe II] line map.
- Values are calibrated surface brightness in MJy/sr. The source observation is
  a finite-exposure mosaic and is a fixed scene, not a millisecond JWST movie.
- Full SCI, ERR and WHT arrays were read by HTTP byte ranges; their lengths and
  SHA-256 hashes are in source-extraction.json. The entire FITS product, including
  unused extensions, was not downloaded or hashed. No claim of its full hash is made.

Data use: https://archive.stsci.edu/publishing/data-use . Public JWST observations
were obtained from MAST at STScI. STScI is operated by AURA under NASA contract
NAS 5-03127. The observations are associated with JWST program 1288.

## Spatial and intensity definitions

The complete mosaic remains available as a static context image, with the chosen
science field and magnifier marked. The two dynamic overviews cover about
59.17 x 47.77 arcsec; the magnifiers cover 19.72 x 19.72 arcsec. Thus the source
location is visible without implying useful AO performance across the full mosaic.
Coordinates, exact bounds, WCS scale and shape are in data.json. Native image axes
are retained and flipped vertically for display. Pupil/sky alignment is assumed.

Pixel-area overlap averages linear surface brightness onto the saved PSF's native
0.05136477 arcsec sampling. Every 768 x 768 PSF sample and its tilt are retained.
Full linear convolution uses float64 arithmetic and adequate zero padding.
Both displayed fields have sufficient surrounding real image context for the
whole kernel; there is no artificial edge extension. No independent brightness
normalization, sharpening, background subtraction or detector-noise draw is added.

Only after convolution, the same asinh transfer is applied to every panel and time:
`asinh(max(I-30,0)/15) / asinh((400-30)/15)`, clipped to [0,1], with a magma
single-band colour map. Units are MJy/sr. Clipping is a display choice; linear
samples retain their numerical values. The source ERR/WHT planes are supplied
for the native detail cutout, not propagated into a full output uncertainty model.
The public resampled contexts and selected linear output samples are float32
storage copies; convolution was float64. RGB/video are display products, not FITS.

## Missing data and limits

Nonfinite SCI/ERR or nonpositive/nonfinite WHT pixels are replaced with the nearest
valid SCI pixel to permit convolution. The displayed magnifier contains no such
source pixels directly; the wider field may. Missing pixels in the surrounding
kernel footprint can still influence it. Every frame is recomputed with zero and
twice the nominal filled component; sensitivity.json gives the resulting maximum
change in MJy/sr. This is sensitivity to the chosen fill, not an upper bound on
unknown saturated flux. A finite mosaic pixel is not proof of no saturation in
any contributing exposure. No per-exposure saturation or absolute-calibration
audit is claimed. Original noise, striping and other pipeline residuals remain.

The reference already contains the JWST PSF and mosaic resampling. Applying the
model PSF adds blur: the effective response contains both. No deconvolution or
PSF matching is attempted. The optional ideal reference adds the model's ideal
2.2 m pupil PSF to that same observation. It is not an intrinsic sky truth image.

A single on-axis PSF is applied everywhere in the selected field. Anisoplanatism,
real field dependence, spectral integration and science-camera exposure/noise
are not modelled. This is a controlled image experiment using calibrated input,
not a calibrated prediction of on-sky Robo-AO-2 performance. The scene does not
feed the WFS or change the controller. All instrument assumptions remain on site.

## Timing and checks

All 159 existing replay image times and all 1500 native point-source Strehl values
are retained. Frame 736 at 0.981333 s marks the first rejected v1 reconstruction;
image deterioration can accumulate afterward. The 2 s trajectory plays in 40 s.
No interpolation or temporal exposure averaging is applied. Strehl is measured
from the saved model's point-source PSFs, not estimated from stars in this image.

The exporter checks original AO input hashes, all 477 displayed Strehl values,
15 saved PSF snapshots, an exact delta-kernel limit, a direct-convolution oracle,
and flux conservation of the full (uncropped) convolution. Cropped field flux
need not remain constant because light can cross the boundary. Numeric results
and limitations are recorded in data.json and provenance.json.

## References

- NIRCam filters: https://jwst-docs.stsci.edu/jwst-near-infrared-camera/nircam-instrumentation/nircam-filters
- NIRCam PSFs and resampling: https://jwst-docs.stsci.edu/jwst-near-infrared-camera/nircam-performance/nircam-point-spread-functions
- Pipeline products: https://jwst-docs.stsci.edu/jwst-science-calibration-pipeline
- PDRs4All imaging context: Habart et al. 2024, A&A 685 A73, https://doi.org/10.1051/0004-6361/202346747
- Filter interpretation: Chown et al. 2025, A&A 698 A86, https://doi.org/10.1051/0004-6361/202452940

The filter table, PSF/resampling documentation, MAST data policy, calibrated FITS
headers and Chown et al. section 4.3.1 were inspected for this presentation.
Habart et al. is the observing-program context, not a claim of identical reduction.

### Fixed overview exclusion mask

Gray hatching in both dynamic overviews excludes pixels where the maximum
zero/twice-fill sensitivity exceeds 3.7 MJy/sr (1% of the fixed display span).
The maximum is taken over both model states and every replay time, then over
each 2 x 2 output display cell. The same mask is applied everywhere in the
record, including the observed field reference. It prevents the visibly most
fill-dependent stellar cores from being shown as measurements. The mask and
full-resolution sensitivity map are downloadable. It does not establish an
upper bound on true missing flux. The magnifier's maximum tested sensitivity
is below this threshold and it has no directly filled source pixels.
