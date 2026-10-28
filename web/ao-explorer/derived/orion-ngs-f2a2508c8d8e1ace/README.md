# Orion F162M through the saved 2.2 m NGS experiment

This is an illustrative convolution of an observed JWST image, not a new AO
trajectory, an intrinsic-sky reconstruction or a prediction of Robo-AO-2
photometry. The sky image remains fixed as the recorded PSFs change.

## Source and quality

NASA/ESA/CSA JWST NIRCam, GTO 1256 (PI Mark J. McCaughrean), MAST calibrated
F150W2+F162M mosaic, pipeline 3.0.0. See provenance.json for the exact product,
HTTP byte ranges, hashes, WCS coordinates and SCI/ERR/WHT extraction. The
large source file was not hashed as a whole: the range hashes and delivered
cutout identify the retrieved data. The author's separate Zenodo reduction
was evaluated as an alternative but is NOT the source of these frames.

source-display.fits preserves calibrated linear SCI, ERR and WHT around the
displayed region. All displayed source pixels are finite and covered; no
replacement occurs there. A small number of missing outer-context pixels
are assigned their nearest valid SCI value. scene.npz includes that missing
component and its area fractions. Every frame is also evaluated with zero
and twice that fill; sensitivity is in provenance.json. This is a local
assumption, not a recovery or upper bound on saturated stellar flux. No
independent input-exposure saturation audit or absolute calibration is claimed.

## Forward display model

F162M has pivot wavelength approximately 1.626 um. The unchanged simulation
PSFs are monochromatic 1.65 um. This close but nonidentical band match, a
spatially constant on-axis PSF, and arbitrary alignment of source axes to
simulation pupil remain assumptions. The observed JWST PSF, diffraction
spikes, drizzle response and observational noise remain in the scene.

Surface brightness in MJy/sr is averaged by exact rectangular pixel overlap
onto the simulation angular lattice. No background subtraction or flux
renormalization is performed. Each complete 768x768 PSF has unit total
flux. All convolution is linear with sufficient zero padding; the 961x961
scene covers the entire kernel reach of the central 193x193 display. No
PSF wing is discarded and no recentering occurs. Source pixels outside
this context cannot reach the displayed field under the finite saved kernel.

The JWST reference is the resampled observed source. The optional ideal
2.2 m reference adds the same model's zero-aberration pupil PSF; it also
retains JWST's original response. The other panels add the existing zero-DM,
v1 residual and v2 residual PSFs. They never enter the AO loop.

One fixed asinh transfer and single-band magma palette applies to all frames
and panels, after convolution. Bright/dark clipping affects display only.
The images are false-colour intensity, not the ESA multiband publicity image.
All 159 original replay timestamps are retained, including each frame near
736 (0.981333333 s). Existing Strehl values retain their original definition
from point-source PSFs; they are not derived from the extended Orion image.

The full original parameter draft, all assumptions and loss-of-lock repair
evidence remain in the site's separate NGS publication. No 2 m, 2.2 m or
42 m simulation was rerun for this image experiment.

## Standalone animation

orion-comparison.webp is a lossless 40-second animation of the same 159
image times, with the full 1500-sample Strehl curves and the 0.981333 s
marker. It repeats the same 2-second record. Timing is recorded in
movie-timing.json; no image or time interpolation is introduced.
