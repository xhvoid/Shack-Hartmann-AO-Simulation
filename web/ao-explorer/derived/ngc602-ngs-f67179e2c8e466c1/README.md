# NGC 602 through saved 2.2 m PSFs

Full official colour image, with a linked central-cluster detail. No AO run.

Credit: ESA/Webb, NASA & CSA, P. Zeidler, E. Sabbi, A. Nota, M. Zamani (ESA/Webb). Source: https://esawebb.org/images/weic2425c/
CC BY 4.0: https://esawebb.org/copyright/ . Modified by resampling and convolution.
The unmodified source JPEG is included with its ICC and AVM metadata and hash.

This is a multiband colour illustration, not calibrated simulated science data.
The already processed NIRCam + MIRI image (1.15–10 um) is converted using its
embedded ICC profile to sRGB and decoded to linear-light RGB. That operation
does not undo the original astronomical stretches or recover band fluxes.
The same 1.65 um PSF is applied to each channel. The original JWST response,
diffraction spikes, nonlinear colour choices and observational noise remain.
No added detector noise, deconvolution or per-panel brightness fitting.

The source angular pixel scale comes from embedded AVM metadata. Both main
panels retain the entire image; the supplementary 19.724 arcsec
magnifier marks the same central region. PSFs keep their original angular
size and tilt. The overview uses a coarser computational grid (2 native
PSF cells), with exact area redistribution of every PSF pixel's flux.
The magnifier uses native PSF sampling. Full linear FFT convolution is used.
Outside the original full-field boundary, edge values are extended; the
outer ~19.8 arcsec depend on this unknown-sky assumption. The central detail
has enough real context for the entire kernel and uses no extrapolated sky.
The two grid choices are for display only; point-source Strehl is always
verified on the original native PSF, without binning.

A constant on-axis PSF across ~3 arcminutes is a visualization assumption.
Anisoplanatism, band-specific PSFs and the actual instrument field are not
modelled. These images do not predict real Robo-AO-2 wide-field performance.
All original instrument draft assumptions and repair evidence remain on the
site. All 159 existing replay times and all 1500 curve points are retained.
Frame 736 at 0.981333 s is the first rejected v1 reconstruction. The default
late frame highlights the subsequent divergence, not a discontinuity at 736.

The standalone 40 s compressed WebP preview repeats the same 2 s record at 20x slower
speed, with no temporal interpolation. Timing is in movie-timing.json.

The downloadable animation is a quality-92 compressed preview at 960 pixels
wide. The interactive site frames remain lossless; compression does not
change any stored point-source metrics.
