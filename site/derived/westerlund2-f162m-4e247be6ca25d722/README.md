# Westerlund 2 F162M synchronized image replay

This is post-processing of existing 2.2 m natural-guide-star AO records. No atmosphere, controller, reconstruction, calibration or AO trajectory was rerun. The original 2 m baseline and 42 m record are unchanged. All original parameter assumptions and diagnostic evidence remain on the site.

## Input and angular scale

The exact source context and field accepted in the three-epoch preview are reused. The centre is mosaic pixel (9090, 3670), zero based, in `jw03523-o005_t001_nircam_f150w2-f162m_i2d.fits`. The view is 80 × 80 model pixels, 4.109181687 × 4.109181687 arcsec, with 0.05136477109 arcsec pixels. It is a small outer field within the Westerlund 2 observation, not a panorama of its dense core or a membership-selected catalogue.

The calibrated public JWST/NIRCam source is in MJy/sr: program 3523 (EWOCS), observation 2024-07-14, pipeline 3.0.0, CRDS jwst_1584.pmap. F150W2 is the blocking filter; F162M is the transmitted band. The [F162M pivot wavelength is 1.627 µm and bandwidth 0.168 µm](https://jwst-docs.stsci.edu/jwst-near-infrared-camera/nircam-instrumentation/nircam-filters). The existing monochromatic simulation PSFs use 1.65 µm, approximately 1.4% longer than the pivot. No spectral integration is added.

Source: [MAST calibrated product](https://mast.stsci.edu/api/v0.1/Download/file?uri=mast:JWST/product/jw03523-o005_t001_nircam_f150w2-f162m_i2d.fits). Credit: NASA / ESA / CSA JWST, program 3523 / EWOCS, MAST / STScI. [Data-use guidance](https://archive.stsci.edu/publishing/data-use).

## Image formation and brightness

The previously prepared linear source context is reused byte for byte. It was area-averaged from the native 0.031230978 arcsec pixels. Full 768 × 768, unit-flux PSFs are calculated from the archived pre-update residual OPDs or shared atmosphere OPDs, then applied by linear convolution with real source context. Tilt is retained; there is no recentering, sky wraparound, PSF magnification or per-panel brightness normalization.

Every image uses the same asinh display: 0–80 MJy/sr, softening 2 MJy/sr, magma pseudocolour. Display tails clip; numerical arrays retain their original linear values. Native model pixels are enlarged by nearest-neighbour display. The observed reference retains JWST's PSF. The optional ideal reference adds the zero-aberration 2.2 m pupil PSF to that same observed scene; it is not an estimate of the unconvolved sky.

JWST diffraction structure, resampling, noise and calibration artifacts remain. One on-axis PSF is assumed across the field. No deconvolution, anisoplanatism, exposure integration or extra science-camera noise is added. This is a matched-band illustration of recorded PSFs, not a validated prediction for real Robo-AO-2 observations or a new stellar photometry product.

## Saturation and missing-data caveats

The four associated NRCB1 calibrated exposures were checked in the static study. SATURATED flags were mapped through their TAN-SIP WCS and the mosaic WCS, with an eight-native-pixel (0.250 arcsec) guard. No such guarded flag and no directly invalid SCI/ERR/WHT sample lies in the selected field. `quality-extraction.json` records the source products, byte ranges and DQ hashes. The selection and original checks are retained in `static-results.json` and `static-methods.md`.

The wider convolution context still includes saturated and bright stars. Their supplied mosaic values, including surrounding diffraction structure, remain in the default replay, as in the accepted preview. Edge ghosts and faint background knots should not be interpreted as measured stellar structure. Saturation is not removed by choosing a crop that excludes the bright core itself.

At every replay time, `sensitivity.json` reports the change produced by zeroing or doubling the supplied values in the outside-field saturation guard, and by zeroing or doubling nearest-valid fills for missing context. These tests do not bound unknown true saturated flux. `saturation-sensitivity-map.npz` stores the maximum change over all 477 model images; its PNG marks positions above 0.8 MJy/sr, 1% of the fixed display span. This full-replay mask is a diagnostic and is not applied to the default images. The separately labelled `static-quality.png` uses the earlier three-epoch mask, so the two masks need not match.

## Shared clock, Strehl and first rejection

The browser uses the same 159 image indices as the existing wavefront/PSF replay: every twelfth frame, archived PSF snapshot times, and every frame 720–752 around the first rejected v1 reconstruction. Images, readouts and chart cursor are committed at one timestamp. Both model states use the same recorded atmosphere. All 1500 archived point-source Strehl samples are plotted; no Strehl is inferred from the cluster image.

Frame 736 at 0.981333 s is the first rejected v1 reconstruction. Frame 735 is only 1.333 ms earlier; the first rejection need not cause an instantaneous image collapse. The loss marker remains visible throughout playback. Failed v1 frames continue to be shown. No generated intermediate images or motion interpolation are used.

The 40 s WebP is a lossless presentation of the 2 s record at 20× slowdown, 1280 × 720. Each source image is held to the next saved boundary. MP4 is a separate H.264 sharing copy with its own timing and compression checks. Browser delays or background-tab pauses can extend real playback time without mixing image timestamps.

## Evidence and reproduction

`data.json` and `provenance.json` include input identities and checks: original OPD hashes, all 477 Strehl comparisons, 15 archived PSF comparisons, full-convolution flux conservation, delta-kernel alignment, and agreement with the nine accepted static output arrays. The exact checks are generated rather than inferred. No general CI or simulation test suite is required to make these derived images.

The bundle includes the source cutout, approved static figures, selected linear outputs, source context, sensitivity maps, original range-extraction provenance and an offline exporter. Reproduce with `tools/westerlund_scene.py --archive-root /path/to/archives --static-dir /path/to/approved-static-preview --web-dir site --output-dir /path/to/new-bundle --methods /path/to/METHODS.md`, using two native numerical threads. The archived OPDs and approved static bundle are required; no AO runtime is called.
