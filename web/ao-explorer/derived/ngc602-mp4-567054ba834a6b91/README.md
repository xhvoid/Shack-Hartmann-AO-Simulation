# NGC 602: shareable MP4

40 seconds, 960 x 896, 60 fps, H.264 High 4.1 / yuv420p, no audio.
The MP4 fast-start header is at the beginning for progressive playback.

This is a transcode of the existing NGC 602 WebP presentation, with its full
field, linked magnifiers, all 1500 Strehl curve points, moving cursor and
0.981333 s loss marker already drawn. No AO simulation, PSF convolution or
scientific metric was rerun. Both compression stages are lossy.

All 159 source images are retained. They are held, never blended or
interpolated, on a 60 fps video grid. The transition delay is less than
1/60 second of playback (less than 0.834 ms in the 20x-slower simulation
clock), relative to the existing WebP's millisecond boundaries. Exact
frame mappings and the first MP4 frame showing loss are in data.json.
The whole movie is 40 seconds; it contains one 2-second recorded trajectory.

The source is an observed multiband colour composite, retaining JWST's
response and display processing. The same 1.65 um PSF was applied to each
RGB channel with a spatially constant on-axis assumption over the field.
These illustrations are not quantitative multiband instrument predictions.
All original assumptions and evidence remain in the parent website bundle.

Original image credit: ESA/Webb, NASA & CSA, P. Zeidler, E. Sabbi, A. Nota,
M. Zamani (ESA/Webb). https://esawebb.org/images/weic2425c/
CC BY 4.0: https://esawebb.org/copyright/
Modified by resampling, additional PSF blurring and video encoding.

To reproduce in the repository, place exporter.py at
scripts/ao_explorer/ngc602_mp4.py and run it with --ffmpeg /path/to/ffmpeg.
The pre-existing parent bundle is required; no AO runtime is called.
