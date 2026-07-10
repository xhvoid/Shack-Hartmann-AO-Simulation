<!-- Closed-loop controller note for residual OPD RMS, command norm, valid-centroid fraction, latency, stroke clipping, and config-hash histories. -->

# Closed-Loop Controller Notes

The detector-level integrator adds the detector-level integrator loop in `src/ao_closed_loop.py`.

The new loop consumes:

```text
DetectorShwfsCalibration  from module
DMModel                   from module
PokeMtxResult             from module
phase sequence            radians at the WFS wavelength
```

The shared result object is `LoopHistory`. Its required fields are:

```text
residual_opd_rms      n_steps array, nm OPD RMS
command_norm          n_steps array, nm OPD equivalent
valid_centroid_frac   n_steps array, fraction
config_hash           SHA-256 hash of loop, calibration, DM, and poke settings
```

Additional histories record pre-update residual RMS, open-loop RMS, clipped command vectors, reconstructed and applied command-increment norms, stroke saturation fraction, and residual phase RMS at the WFS wavelength.

The loop uses a leaky integrator:

```text
commands[k+1] = (1 - leak) * commands[k] + gain * delayed_delta[k]
```

`latency_frames` delays reconstructed command increments before they are applied. This is the first local hook for servo-lag studies: in a dynamic atmosphere, the correction applied by the DM can correspond to an older residual measurement.

Validation summary:

```text
The static loop converges and the command norm remains finite after 50 iterations.
```

The current unit tests also check a noisy dynamic loop with two frames of latency, fixed history lengths, unit labels, and invalid controller settings.

This remains a synthetic detector-level SCAO controller. It is not RTC telemetry and should not be presented as a calibrated observatory control loop.
