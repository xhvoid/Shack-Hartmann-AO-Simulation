<!-- Closed-loop controller note for exact latency, applied-command state, residual OPD RMS, command histories, validity, and config identity. -->

# Closed-Loop Controller Notes

The canonical controller and frame runner live in `shwfs_ao.control`. The
installed `ao_closed_loop` module remains a frozen compatibility facade for the
historical nanometre-facing functions and result format; behavior-compatible
execution delegates to the canonical calibration, control, and DM owners.

The canonical runner receives typed components rather than constructing hidden
optics or inverse kernels:

```text
LoopConfig
RandomStreams
AtmosphereModel
WavefrontSensor
DeformableMirrorModel
InteractionMatrix
Reconstructor
CommandProjector
Controller
```

Reconstruction uses one reusable `shwfs_ao.calibration` reconstructor. Runtime
validity is intersected with calibration validity, and unusable rows remain NaN
in full-layout diagnostics. A structurally valid but under-covered or
under-ranked frame returns `None`; it is never inverted after replacing missing
measurements with zero.

## Controller contract

`LeakyIntegratorController` owns gain, leak, the only frame-delay queue, and
command state. At frame `k` it enqueues the projected increment (or exact zero
for `None`), releases the increment from `k - latency_frames`, and computes

```text
requested = (1 - leak) * last_applied + gain * released
```

Zero latency releases the current increment. One-frame latency makes a frame-0
increment first affect frame 1; multi-frame latency follows the same exact
index rule. Consecutive `None` values do not stop controller time: each enqueues
zero, can release an older queued increment, and still applies leak.

After stroke clipping and dead/stuck-actuator policy, the loop acknowledges the
actual DM-applied full-layout command to the controller. The next update starts
from this applied command rather than the possibly unclipped request.

Reconstruction coordinates cross an explicit typed projector: exact identity,
controllable-subset expansion, or a hashed calibrated modal-to-actuator map
bound to its target DM configuration.
IDs, order, coordinate kind, matrix identity, and units are validated before an
increment reaches the controller. Commands are OPD-equivalent metres and the
residual sign is always
`atmosphere_opd_m - dm_correction_opd_m`.

## Canonical history

`shwfs_ao.control.LoopHistory` records fixed-length SI telemetry:

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

The history schema validates its unit and sign declarations. Retained
subaperture count is fixed across frames, and stable IDs plus the actual
atmosphere-realization stream are recorded when components expose them.

Command histories are `(n_steps, n_actuators)` and row masks are
`(n_steps, n_measurement_rows)`. Measurement validity uses only
calibration-valid rows in its denominator; subaperture validity uses retained
subapertures. Metadata retains units, signs, ordered IDs, component hashes,
backend names, frame rate, root seed, named random streams, and the selected
noise/realization policy.

The compatibility history preserves fields such as `residual_opd_rms`,
`command_rms_nm`, `command_l2_norm_nm`, and `valid_centroid_frac`. Those are
adapter outputs, not a second controller or telemetry owner.

## Interpretation

The static loop should converge with finite command state; dynamic latency and
gain experiments are controller operating-region studies. Replay-safe sweep
helpers reset random, atmosphere, controller, and DM state at every point so
axis order cannot change the truth sequence.

This remains a synthetic detector-level SCAO controller. It is not RTC
telemetry and should not be presented as a calibrated observatory control loop.
See the
[`AO-REF-009 control-loop contract`](refactor/AO_REF_009_CONTROL_LOOP.md) and
[`AO-REF-008 reconstructor contract`](refactor/AO_REF_008_RECONSTRUCTORS.md).
