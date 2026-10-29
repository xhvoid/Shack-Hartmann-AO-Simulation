# Orion F164N: shareable MP4

40 seconds, 960 x 896, 60 fps, H.264 High 4.1 / yuv420p, no audio.
The MP4 fast-start header is at the beginning for progressive playback.

This is a transcode of the existing Orion F164N WebP presentation, with its full
field, linked magnifiers, all 1500 Strehl curve points, moving cursor and
0.981333 s loss marker already drawn. No AO simulation, PSF convolution or
scientific metric was rerun. Both compression stages are lossy.

All 159 source images are retained. They are held, never blended or
interpolated, on a 60 fps video grid. The transition delay is less than
1/60 second of playback (less than 0.834 ms in the 20x-slower simulation
clock), relative to the existing WebP's millisecond boundaries. Exact
frame mappings and the first MP4 frame showing loss are in data.json.
The whole movie is 40 seconds; it contains one 2-second recorded trajectory.

The input is the calibrated MAST JWST/NIRCam F164N image from ERS 1288,
PI Olivier Berne / PDRs4All, NASA / ESA / CSA. Linear surface brightness is
convolved before a fixed asinh false-colour display. The source JWST PSF,
resampling and noise remain. One on-axis 1.65 um PSF is assumed over the field.
Missing-data sensitivity and all assumptions are recorded in the parent bundle.
This is a lossy presentation copy, not a scientific numerical data product.

To reproduce in the repository, place exporter.py at
tools/science_mp4.py and run it with --ffmpeg /path/to/ffmpeg.
The pre-existing parent bundle is required; no AO runtime is called.
