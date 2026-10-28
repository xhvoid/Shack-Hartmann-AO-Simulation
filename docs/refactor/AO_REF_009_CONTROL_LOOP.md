# AO-REF-009: backend-independent control loop

`shwfs_ao.control` is the canonical owner of command projection, controller
state, frame latency, loop sequencing, fixed-length telemetry, and replay-safe
control sweeps. WFS optics, reconstruction, DM spatial synthesis, and science
propagation remain behind their own typed component boundaries.

## Canonical API

```python
from shwfs_ao.control import (
    IdentityCommandProjector,
    LeakyIntegratorController,
    LoopConfig,
    run_closed_loop,
)
```

`LoopConfig` contains exactly `n_steps`, `gain`, `leak`, `latency_frames`,
`frame_rate_hz`, and `root_seed`. It requires a positive integer frame count,
finite non-negative gain, finite `0 <= leak < 1`, a non-negative integer
latency, a positive finite frame rate, and a supported non-negative integer
seed. Its deterministic `config_hash`, `frame_period_s`, and `latency_s`
properties are derived from those values.

The runner consumes explicit `RandomStreams`, `AtmosphereModel`,
`WavefrontSensor`, `DeformableMirrorModel`, `InteractionMatrix`, `Reconstructor`,
`CommandProjector`, and `Controller` objects. The supplied random-stream root
seed must equal `LoopConfig.root_seed`. The runner does not construct hidden
generators or implement an FFT, centroid estimator, DM influence function, or
inverse solve.

The frozen core protocols remain minimal. For auditable fixed telemetry, this
runner additionally requires a reconstructor `config_hash` and controller
`gain`, `leak`, `latency_frames`, and `last_released_delta` properties. All
canonical implementations and the private installed-profile adapters provide
those extensions. A stochastic atmosphere's exposed root seed must also match
the loop root; its post-reset realization stream ID is recorded when available.

## Command coordinates and signs

Reconstruction results are never interpreted as commands by array position.
Every projector validates the reconstruction coordinate kind, unit, ordered
IDs, and full output actuator layout; the runner separately verifies that the
estimate carries the configured interaction-matrix hash:

- `IdentityCommandProjector` accepts an exact full actuator layout;
- `ControlledSubsetCommandProjector` expands the ordered controllable subset
  and inserts zero increments for excluded actuator IDs;
- `ModalToActuatorCommandProjector` applies an explicitly supplied, hashed
  `m_opd_equivalent_per_m_opd_rms` map bound to the target DM configuration
  hash.

All projector outputs and DM commands use `m_opd_equivalent`. Positive commands
produce positive correction OPD, so both loop residuals use

```python
residual_opd_m = atmosphere_opd_m - dm_correction_opd_m
```

## Exact controller latency

`LeakyIntegratorController` is the only latency owner. At frame `k` it:

1. enqueues the reconstructed full-layout increment, or an exact zero
   increment when reconstruction is unusable;
2. releases the increment measured at `k - latency_frames` (the current
   increment when latency is zero);
3. requests
   `requested = (1 - leak) * last_applied + gain * released`;
4. waits for the DM result and accepts the actual applied command.

An increment measured in frame `k` therefore affects frame
`k + latency_frames`. A `None` estimate advances controller time: it enqueues
zero, can release an older increment, and still applies leak. The next update
starts from the DM-applied command after clipping and fault policy, never from
the unclipped request. `reset()` restores the delay queue and command state to
exact zeros.

## Frame sequence and telemetry

Frame `k` samples atmosphere once at `time_s = k / frame_rate_hz`. That same
truth sample is used for both pre-update and post-update residuals. The fixed
sequence is atmosphere, current DM correction, pre-update residual, WFS
measurement, reconstruction, command projection, controller update, DM
application, applied-command acknowledgement, and post-update residual.

`LoopHistory` stores the following fixed-length fields:

```text
time_s
open_loop_opd_rms_m
pre_update_residual_opd_rms_m
post_update_residual_opd_rms_m
command_norm_m
delta_command_norm_m
released_delta_norm_m
requested_command_history_opd_m
applied_command_history_opd_m
saturation_fraction
valid_measurement_fraction
valid_subaperture_fraction
reconstruction_usable
measurement_row_masks
config_hash
metadata
```

Every per-frame vector has length `n_steps`; command histories have shape
`(n_steps, n_actuators)` and masks have shape
`(n_steps, n_measurement_rows)`. `valid_measurement_fraction` divides by the
calibration-valid row count. `valid_subaperture_fraction` uses retained
subapertures and is the source for the compatibility
`valid_centroid_frac`. The retained subaperture count cannot change between
frames, and stable subaperture IDs are recorded when the WFS exposes them.
Metadata validates the exact field-unit and sign schema and records ordered
IDs, backend names, component hashes, frame rate, root seed, named stream IDs,
the actual atmosphere realization stream when exposed, and the
noise/realization selection.

Runtime WFS operating points may deliberately vary photon or read-noise
configuration while reusing one response calibration. The loop therefore
requires exact row IDs and measurement units and records both runtime-WFS and
calibration identities; the AO-REF-011 system factory owns construction of a
fully coherent component bundle. Actuator-space matrices are already bound to
the exact DM hash, and modal projectors carry their target DM hash explicitly.

## Replay-safe sweeps

`gain_scan`, `latency_scan`, `photon_scan`, `read_noise_scan`, and
`gain_delay_stability_map` run through the same canonical loop. Unless the
realization is itself the sweep variable, every point resets random streams,
atmosphere, controller, and DM state and reuses the same truth sequence. Axis
order therefore cannot change a point's result.

## Compatibility boundary

The installed `ao_closed_loop`, `ao_integration`, error-budget, and validation
entry points retain their frozen signatures and historical nanometre-facing
results. Behavior-compatible execution is adapted to this controller and loop
instead of maintaining a second production engine. Top-level imports remain
silent compatibility facades; new code should use `shwfs_ao.control`.

Notebook 09 and Notebook 11 migration remains assigned to AO-REF-019. The
current detector, DM, atmosphere, and control presets remain synthetic
engineering proxies, not calibrated observatory hardware or RTC telemetry.
