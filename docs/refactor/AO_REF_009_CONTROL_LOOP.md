# AO-REF-009: backend-independent control loop

> **Status of this page (2026-10-18).** This is a ticket record of the refactor
> that produced the `shwfs_ao` package. Its contract statements (units,
> identities, protocols, tolerances) still describe the code unless the
> [technical reference](../technical_reference.md) says otherwise; its status
> lines, dates and next steps are historical. Open work is in the
> [roadmap](../roadmap.md).

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

A reconstructor may fail closed on a frame (return `None`); the controller then
queues no new increment for that frame, while increments already in the
latency queue are still released and the leak continues. The metadata records
how many frames reconstructed as `reconstruction_usable_frames` and
`reconstruction_usable_fraction`, and `LoopHistory` rejects a summary that
disagrees with `reconstruction_usable`. A run in which no frame was usable
never changed the DM command, so its residual histories are open-loop:
`run_closed_loop` still returns it, but emits
`shwfs_ao.control.ControlLoopWarning` naming the observed valid-measurement
range and, when the reconstructor exposes it, its `min_valid_fraction`.

### Opt-in recovery supervisor

With zero leak, a run of rejected frames holds the DM in its last shape. If
that shape keeps the spots outside the validity domain, the loop never
recovers. This is the 12 m detector-level latch-up at m_AB = 11.

`run_closed_loop(..., recovery=...)` accepts an optional
`shwfs_ao.control.ClosedLoopRecoveryPolicy`, the loop supervisor of the
schema-7 `controller.recovery` block. With `recovery=None`, the default, the
loop, its telemetry and its run hash are unchanged.

**Knobs.** Each is off unless set, and at least one must be set.
- **Decay.** After `rejected_frames_before_decay` consecutive frames with
  no usable increment, every further such frame multiplies the requested
  command by `1 - decay_per_rejected_frame`. A decay of `1` resets the DM
  to flat.
- **Fallback.** A frame the reconstructor rejects is solved from its usable
  rows alone, if their fraction is at least `fallback_min_valid_fraction`
  (AO-REF-008, subset solve). `fallback_min_actuator_coverage` restricts
  that solve to actuators the usable rows still see.
- **Gain schedule.** Every used increment is scaled by
  `min(1, valid_fraction / gain_full_valid_fraction)`.

**Order within a frame.** The supervisor adds three steps:
1. after reconstruction, the fallback, for a rejected frame only;
2. after command projection, the gain schedule;
3. after the controller update, the decay.

The controller then accepts the command the DM applied, as on every frame,
so its integrator state follows the decay. The supervisor owns no latency.
`reset()` runs at the start of every run.

**Identity and telemetry.**
- The policy's `config_hash` joins the run's component hashes as
  `"recovery"`, and so the run hash.
- `metadata["recovery"]` records that hash and the run's
  `fallback_frames` and `decayed_frames`.
- A fallback reconstructor must carry the loop's interaction-matrix hash;
  otherwise the run raises `ControlLoopError`.

**Evidence.** Measured on the 12 m detector-level profile at m_AB = 11:
- Resetting to flat after two rejected frames recovers lock (1.9 µm →
  377 nm).
- The subset fallback and the gain schedule do not.
- The remaining excursions came from an under-regularized reconstructor,
  not from this policy (AO-REF-008, damping).
- `det_emccd_12m_medium_derived@3` keeps the reset as a safety net
  alongside the stronger damping.

See the [detector-level status record](DETECTOR_LEVEL_DEVELOPMENT_STATUS.md),
sections "Closed-loop recovery policy" and "Excursion trigger at
m_AB = 11".

Runtime WFS operating points may deliberately vary read noise, or the photon
budget of a detector without pedestal or full well, while reusing one response
calibration: neither changes the noiseless response. `per_frame_legacy` PRNU
is the exception, because its noiseless patterns come from seeds derived
from the whole detector configuration. The loop therefore
requires exact row IDs and measurement units and records both runtime-WFS and
calibration identities. When both the runtime WFS and the interaction matrix
declare a sensor response identity they must be equal, so a change of WFS
wavelength, sampling, detector pedestal, saturation, or pixel maps, or of the
centroid estimator, cannot reuse a stale calibration. With a background a
photon change alters the source-to-pedestal ratio, so it is rejected too.
For a matrix calibrated with noise, the WFS and the matrix must also share a
noisy response identity, because the noise settings and clipping move an
average of noisy centroids. The AO-REF-011 system factory owns construction
of a fully coherent component bundle. Actuator-space matrices are already bound to
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
