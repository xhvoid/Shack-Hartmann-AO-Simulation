# Decisions in the AO model

### Measure the spots on the detector

I calculate each lenslet image before I measure its centre. This gives me a way to see where a measurement is lost. In the photon-count sweep, every spot failed the quality cuts at 500 photons per subaperture. At 1,000 photons enough spots passed to measure a centroid error.

### Keep the atmosphere fixed when changing the reconstructor

In the first 2.2 m run, small singular values amplified the command increments as spots dropped out. At 0.981 s the reconstructor rejected the frame. I raised the relative cutoff from 0.001 to 0.05 and kept the atmosphere and calibration fixed so I could compare the same frames. The mirror stayed within its limits for all two seconds. The recovery rule was present in the second run and never had to act.

### Check the commands at the stroke limit

I kept the 2 m profile’s ±1 µm optical-path limit and counted both new clipping events and actuators already at the limit. A command can sit at the boundary for several frames without producing another clipping event. Counting only the new events would miss that part of the mirror motion.

### Average the images before measuring the peak

I wanted to know what a star would look like during an exposure. I kept the image positions fixed on the detector and averaged their intensities. In the 2.2 m on-axis example, the mean instantaneous Strehl was 0.750. The peak of the accumulated image gave 0.448. Motion of the core during the exposure matters to that second measurement.

### Use the guide-star correction for each science target

I moved the science target across the field while keeping the mirror correction from the on-axis guide star. The light from the two directions crosses an elevated layer at different positions. In the same 1.8 s exposure, the H-band Strehl dropped from 0.448 on axis to 0.338 at 20 arcsec.

### Change gain at a fixed delay

I compared gains on paired atmospheric sequences. In the historical 42 m configuration, gain 0.2 reduced a late excursion that I saw at gain 0.3. Over the full analysis window, gain 0.3 gave the sharper mean image at both tested delays. Looking at the late excursion alone would have led me to choose the other gain.

### Use the same damping at 5 m and 12 m

I used a Tikhonov factor of 0.03 for both v3 profiles. The 12 m noiseless scan had its lowest mean there. I checked what that choice would cost at 5 m by replaying the same five atmospheres at 0.07, the lowest mean in that scan. The difference was 103 ± 19 nm² of total residual variance. At 42 m I kept 0.001 after comparing both settings on three atmospheres. [Damping scan](eso_scao_benchmark.md#choosing-the-v3-damping)

### Scan the filter cutoff at 5 m and 12 m

The v3 profiles took their filter cutoff of 0.35 from the 42 m detector-level profile. I had not scanned it at the smaller apertures. With the damping at 0.03, I replayed five atmospheres at each cutoff. At 5 m, 0.35 gave the lowest mean of the six cutoffs I tried. At 12 m the lowest mean of eleven was at 0.6, 419 ± 42 nm² of total residual variance below 0.35. The reduction held when I added 1 e⁻ of read noise. Version 4 of the 12 m profile uses 0.6. The 5 m and 42 m profiles stay at version 3. I have not scanned the cutoff at 42 m. [Cutoff scan](eso_scao_benchmark.md#choosing-the-12-m-filter-cutoff)

[Replay the experiments](https://xhvoid.github.io/Shack-Hartmann-AO-Simulation/) · [Methods](methods.md)

## Open item: 2 m end-to-end vs TIPTOP

In a separate 2 m test, I used the same on-axis telescope geometry, atmosphere and loop gain in my model and in TIPTOP. At 1.65 µm the peak Strehl was 0.257–0.419 across three time-domain exposures. TIPTOP gave 0.710. In the first exposure, residual tilt accounted for 69% of the wavefront variance. [Comparison plot and settings](https://github.com/xhvoid/Shack-Hartmann-AO-Simulation/tree/main/docs/scao-comparison)

Status: tilt-removed comparison and stroke-clipping attribution not yet done.
