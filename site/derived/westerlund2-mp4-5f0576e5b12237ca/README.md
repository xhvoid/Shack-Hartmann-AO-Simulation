# Westerlund 2 F162M: shareable MP4

40 seconds, 1280 x 720, 60 fps, H.264 High 4.1 / yuv420p, no audio.
The MP4 fast-start header is at the beginning for progressive playback.

This is a transcode of the existing Westerlund 2 F162M WebP presentation, with its four
views of the same 4.109 arcsec field, all 1500 Strehl curve points, moving cursor and
0.981333 s loss marker already drawn. No AO simulation, PSF convolution or
scientific metric was rerun. The source WebP is lossless; this sharing MP4 uses lossy compression.

All 159 source images are retained. They are held, never blended or
interpolated, on a 60 fps video grid. The transition delay is less than
1/60 second of playback (less than 0.834 ms in the 20x-slower simulation
clock), relative to the existing WebP's millisecond boundaries. Exact
frame mappings and the first MP4 frame showing loss are in data.json.
The whole movie is 40 seconds; it contains one 2-second recorded trajectory.

The input is the calibrated MAST JWST/NIRCam F162M image from program 3523,
EWOCS, NASA / ESA / CSA. Linear surface brightness is
convolved before a fixed asinh false-colour display. The source JWST PSF,
resampling and noise remain. One on-axis 1.65 um PSF is assumed over the field.
F162M (pivot 1.627 um, width 0.168 um) is approximated by existing 1.65 um PSFs.
The selected field avoids mapped saturated cores, but outside-field bright and
saturated stars can still affect the edges. Saturation and missing-context
sensitivity, source provenance and all assumptions are in the parent bundle.
This is a lossy presentation copy, not a scientific numerical data product.

To reproduce in the repository, place exporter.py at
tools/westerlund_mp4.py and run it with --ffmpeg /path/to/ffmpeg.
The pre-existing parent bundle is required; no AO runtime is called.
