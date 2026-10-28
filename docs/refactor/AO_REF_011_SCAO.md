# AO-REF-011 Shared SCAO Construction

AO-REF-011 turns the high-order geometric study and the 2 m detector-level
study into profiles of one experiment engine.  A profile is an immutable,
versioned `shwfs_ao.io.configs.SystemConfig`; it is not a second control-loop
implementation.

## One construction and execution path

`shwfs_ao.experiments.scao.build_scao_system()` resolves the configured
backend and constructs the atmosphere, WFS, DM, interaction matrix,
reconstructor, command projector, controller, random streams, and science
propagator.  It then runs the canonical control-component preflight before it
returns a `ScaoSystem`.  Both WFS fidelities use the same runner:

```python
from shwfs_ao.experiments.scao import build_scao_system, run_closed_loop
from shwfs_ao.io.configs import load_system_profile

config = load_system_profile("fast_2m_detector", 2)
system = build_scao_system(config)
history = run_closed_loop(config, system=system)
```

The experiment layer owns assembly and sequencing only.  Native numerical
kernels remain in `shwfs_ao.backends.native`; the backend-independent frame
loop and telemetry remain in `shwfs_ao.control`.  Artifact paths and file
writing are outside this boundary.

## Versioned profiles and hashes

Every published profile version stays installed, because a result is labelled
with the exact profile that produced it and must stay reproducible from it.
The current family is version 2:

- `fast_2m_detector@2`;
- `portfolio_2m_detector@2`;
- `research_2m_detector@2`;
- `high_order_10m_geometric@2`;
- `high_order_10m_hcipy@2`.

Their superseded `@1` peers remain packaged and loadable.  The v2 review made
`wfs.photon_allocation` explicit at the `throughput_scaled` value v1 already
ran with, so the two versions describe the same physics: every component
block, the WFS block included, compares equal as a value.  What separates
them is identity.  The `profile` hash moves because the provenance is a
different published record.  The nested `wfs` hash moves too, because that
one entry is taken from the `WfsConfig` dataclass rather than from the
serialized record, and schema v2 extended that dataclass's declared field
list; a v1 record therefore keeps the twelve-field digest it was published
with instead of being relabelled under a shape it predates.  Every other
component hash is unchanged between the two.

The *record* schema version is a separate axis from the profile version: v2
records require `wfs.photon_allocation`, v1 records predate it and must omit
it, and both parse (`SUPPORTED_PROFILE_SCHEMA_VERSIONS`).  A configuration
serializes under the schema it belongs to — its `record_schema_version`, which
for a parsed record is the schema that record declared — so one configuration
still has exactly one hashing basis; that basis is simply its own schema's and
not the newest one.  The schema version sits *inside* the hashed mapping, so
serializing every configuration under the current schema would move
`config_hash` for profiles whose physics and whose packaged record never
changed, and a result labelled with such a profile would stop reproducing its
own identity.  Writing each record back through the schema it was published
under is what makes a v1 record round-trip byte-identically and keeps a v1
result reproducible forever; adding a schema version can only affect records
written under the new one.

The two axes are independent but not every pairing is coherent, so a
configuration may only claim a schema that can express it: schema v1 accepts
only a v1 profile carrying the reviewed `throughput_scaled` allocation.
Promoting such a record to v2 would move its published hash and demoting a v2
one would silently drop stated physics, so an incoherent pairing is refused
rather than reconciled.

`high_order_10m_hcipy@2` pairs the geometric 10 m scale through the registered
HCIPy backend factory; loading it needs no optional dependency, building it
does.  Loading is always by an explicit `(name, version)` pair; there is no
implicit “latest” selection.

Every numerical scale and observing input is serialized.  In particular,
pupil pixels, lenslet count, actuator count, seeing strength, wind, photon
budget, detector noise, and loop timing cannot be supplied by hidden backend
defaults.  `SystemConfig.config_hash` identifies the complete record,
`component_config_hashes` identifies each nested policy, and
`observing_conditions_hash` identifies telescope/wavelength, atmosphere, and
detector conditions independently of numerical grid size and run length.
Changing resolution therefore changes the full configuration hash without
masquerading as a change in observing difficulty.

## Fail-closed construction

Interaction-matrix resolution policy is explicit:

- `source="build"` is the only mode permitted to calibrate;
- `source="supplied"` requires a canonical `InteractionMatrix` argument;
- `source="resource"` requires the named package JSON resource.

Missing or invalid supplied/resource matrices are errors and never trigger a
recalibration fallback.  Geometry, WFS row IDs, DM identity, reconstruction
coordinates, projector layout, controller settings, and random-root identity
are checked before the first frame.  An unavailable optional backend such as
`hcipy` also raises a construction error; it never substitutes the native
backend.

Notebook 09 should select the high-order geometric profile, while Notebook 11
should select a detector-level 2 m profile.  They may choose different
diagnostics, but both must call this shared construction and execution path.
