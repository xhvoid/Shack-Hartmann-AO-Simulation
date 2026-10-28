<!-- Detector-level SH-WFS note for pupil setup, valid subapertures, reference centroids, detector-noise measurements, and tilt response checks. -->

# Detector-Level SH-WFS Notes

The detector-level SH-WFS layer is currently implemented in `src/shwfs_ao/legacy/synthetic_instrument_data.py` as a small facade around the relocated low-level `shwfs_detector` utilities. Both remain available through their installed top-level compatibility modules. The facade keeps detector and geometry settings in explicit config objects, builds a deterministic zero-phase reference centroid table, and reports `valid_centroid_frac` instead of hiding invalid/zero-flux centroids.

`DetectorConfig` carries the detector realism terms used by the Notebook 11 path: photon flux, read noise, dark current, background, full-well clipping, bad-pixel masks, PRNU, exposure time, QE, and provenance. These are still synthetic detector settings unless a future public calibration file is added, but the terms are exercised directly by tests rather than left as notebook-only assumptions.

Validation summary:

```text
The zero-phase centroid residual is below 0.05 px RMS, the known-tilt sign is correct, and detector dark/background/full-well/bad-pixel/PRNU terms remain finite.
```

Current sign convention from the detector model:

```text
positive x phase tilt -> positive x centroid shift
positive y phase tilt -> negative y centroid shift
```

The small response matrix introduced here is a detector tilt-response matrix used for module sanity checks. It is not the full DM interaction matrix.
