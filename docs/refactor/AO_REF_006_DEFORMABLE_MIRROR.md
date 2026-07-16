# AO-REF-006 — Canonical deformable mirror

AO-REF-006 establishes one repository-level deformable-mirror model while
keeping spatial optical implementations replaceable. The public canonical
surface is `shwfs_ao.dm`; NumPy placement, influence sampling, and synthesis
live in `shwfs_ao.backends.native.dm`.

## Command and residual convention

Canonical commands are optical-path-difference-equivalent correction
amplitudes in metres:

```text
command unit       m_opd_equivalent
backend output     correction OPD, m
positive command   positive correction OPD
loop residual      atmosphere OPD - DM correction OPD
```

They are not actuator volts and not physical reflective-surface displacement.
`DmCommandVector` carries the full ordered actuator layout and must use the
literal unit `m_opd_equivalent`. `DeformableMirror.opd_from_commands()` rejects
missing, duplicated, or reordered identity before invoking a backend.

The canonical result is `DmSynthesisResult`. Its `correction_opd_m` is a
finite two-dimensional raw correction map. Neither the repository wrapper nor
the backend removes piston. Piston removal and NaN masking are explicit
compatibility or analysis operations, not hidden backend behavior.

## Ownership boundary

| Repository wrapper (`shwfs_ao.dm`) | Spatial backend (`backends.*.dm`) |
| --- | --- |
| Full actuator IDs and ordering | Backend-specific actuator placement |
| Controllable subset | Influence-function sampling |
| OPD-equivalent command unit | Array-only command-to-OPD synthesis |
| Stroke clipping | Raw finite correction array |
| Dead/stuck actuator policy | Backend optical conversion |
| Requested/applied diagnostics | No persistent command state |
| Actuator metadata and provenance | No controller behavior |
| Configuration hash | No clipping or fault policy |

Backends are memoryless. Gain, leak, latency, queues, command history, and
clipping feedback belong to the controller and loop tickets, never to a DM
backend.

## Actuator identity and fault policy

The native square layout retains the frozen column/x-major, row/y-minor order.
Physical IDs encode nominal grid coordinates as
`actuator-r####-c####`; filtering a nominal layout does not renumber retained
actuators. `actuator_ids` always describes the complete layout.
`controllable_actuator_ids` preserves that order while excluding dead and
stuck coordinates.

Command policy is applied in this order:

1. Preserve the complete requested command vector for diagnostics.
2. Mark requested values whose absolute magnitude exceeds the symmetric
   stroke.
3. Clip requested values to stroke.
4. Force dead actuators to zero.
5. Force stuck actuators to the configured stuck value, itself clipped to
   stroke.
6. Pass only the applied numeric array to the backend.

This order preserves the historical overlap rule: stuck wins when an actuator
is listed as both dead and stuck. Saturation remains a diagnosis of the
requested command; clipping a configured stuck value does not retroactively
mark the request saturated.

## Native backend

`NativeDmBackend` provides Gaussian, compact-Gaussian, and pyramid-like
synthetic influence families. Canonical influences are sampled-peak
normalized, finite, ordered with their actuator IDs, and zero outside the
sampled pupil. A positive one-hot command therefore produces a positive local
OPD response with the requested peak amplitude. Repeated calls have no hidden
temporal state.

The native model is synthetic and literature-inspired. Provenance records
make that status explicit; no analytic influence function is presented as a
measured device calibration.

## Reflective factor of two

A reflective optical primitive may accept mirror-surface displacement instead
of OPD-equivalent amplitude. That adapter performs the conversion at its own
boundary:

```text
10 nm canonical OPD-equivalent command
→ 5 nm reflective surface displacement
→ 10 nm wavefront OPD after reflection
```

The adapter must not double the returned wavefront OPD again. The frozen
boundary fixture checks both amplitude and positive correction sign before a
real optional backend is accepted.

## Hashes, metadata, and provenance

The repository model hash covers the complete `DMConfig`, sampled geometry,
ordered physical IDs and centers, pitch, dead/stuck masks, command/synthesis
conventions, backend identity/configuration, and influence content. It uses
canonical serialization rather than object representation or dictionary
insertion order. Results carry the model hash, and metadata contains only
repository-owned values—never a backend library object.

The historical configuration field order remains installed. User-facing
`stroke_limit_nm` and `stuck_command_nm` are explicitly nanometres of
OPD-equivalent command and are converted once at the canonical model boundary.
Their source class and source note produce the canonical immutable
`Provenance` record.

## Compatibility and migration

The top-level `dm_model` and affected `ao_closed_loop` names retain their
AO-REF-000 signatures. They adapt nanometres and historical NaN/piston
representations at the edge while delegating actuator placement, influence
physics, policy, and synthesis to canonical owners. Existing static-fitting,
interaction-matrix, validation, and error-budget paths continue to work
through those adapters until their dedicated later tickets migrate their
result contracts.

Notebook 09 imports the native placement and influence builders instead of
carrying an independent Gaussian formula. Its current controller remains a
documented phase-domain compatibility study; conversion of the entire notebook
loop to the shared SI controller is owned by the later profile/loop tickets.

