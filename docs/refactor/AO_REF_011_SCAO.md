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
The version-2 family is:

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

## Version 3 and `fast_2m_detector@4`

Each profile has a `@3` version with physically conditioned observing
conditions: the native v2 frozen-flow screen (HCIPy's screen for the HCIPy
profile) without RMS pinning, so the disturbance amplitude follows r0 and the
outer scale, plus a two-frame command latency.

`fast_2m_detector@3` kept the 18 px detector window of v2, which was sized for
the 260 nm RMS that v2 pinned.  Its 0.4 m lenslets see d/r0 = 2.1 at the 700 nm
WFS wavelength, so the window spans only 2.7 λ/r0, against 4.1 λ/r0 for
`portfolio_2m_detector@3` and 6.1 λ/r0 for `research_2m_detector@3`.  The
unpinned open-loop spots overflow it.  In its run, window clipping exceeds the
15 % limit in at least one lenslet of every frame, and no other validity
criterion (flux, peak SNR, centroid uncertainty) ever rejects one.  With
`min_valid_fraction = 1.0` the reconstructor correctly fails closed on every
frame, so the DM never moves and the run's residual histories are open-loop.
Restoring the 260 nm pin makes it close on every frame.  Removing the latency
or shortening the run does not help.

`@3` stays published unchanged, because results labelled with it must keep
reproducing; it now reports itself through `ControlLoopWarning` (see
AO-REF-009).  `fast_2m_detector@4` is the same record with a 24 px window
(3.6 λ/r0) and nothing else changed.  Its observing-conditions hash equals
`@3`'s, and only the `profile` and `wfs` component hashes move.  It
reconstructs every frame of its run: the mean open-loop RMS is 384 nm and the
mean closed-loop RMS is 310 nm.  Over 120 sampled open-loop screens, its
worst-lenslet clipping stays below 0.12.  Start new fast-scale work from `@4`.

Every numerical scale and observing input is serialized.  In particular,
pupil pixels, lenslet count, actuator count, seeing strength, wind, photon
budget, detector noise, and loop timing cannot be supplied by hidden backend
defaults.  `SystemConfig.config_hash` identifies the complete record,
`component_config_hashes` identifies each nested policy, and
`observing_conditions_hash` identifies telescope/wavelength, atmosphere, and
detector conditions independently of numerical grid size and run length.
Changing resolution therefore changes the full configuration hash without
masquerading as a change in observing difficulty.

## `portfolio_2m_detector@4`

`portfolio_2m_detector@3` measures each 0.29 m lenslet through a 20 px
detector window on its 33 px FFT canvas: 6.2 λ/d, or 4.1 λ/r0 at the 700 nm
WFS wavelength, where its unpinned atmosphere gives d/r0 = 1.5.  That window
leaves no clipping margin.  A flat wavefront already loses 4.5–8.5 % of each
spot outside it, against a 15 % `max_window_clipping_fraction`, and the
shipped run peaks at 0.150.  A lenslet over the limit is invalid, and with
`min_valid_fraction = 1.0` its frame is not reconstructed.  Over root seeds
1–10 × realizations 0–2, 20 of the 30 runs drop frames, up to 41 % of one
run, and one run loses its first four frames.  Window clipping is the only
criterion that ever rejects.  Against the same realization run with a wider
window, the dropped frames cost at most 3.2 % of settled residual RMS, so `@3`
lacks robustness rather than accuracy.  It never locks out and stays
published unchanged.

The window has to cover more than the open-loop spots.  The lenslets that clip
most are the least-filled edge lenslets (41 % pupil fill, just above
`min_fill_fraction = 0.35`), whose smaller apertures give the broadest spots,
and closing the loop does not relieve them: they can clip more than on the
uncorrected screen.  The largest excursion sampled is a convergence transient,
during which the DM command peaks and an edge actuator reaches its stroke limit.
Over 90 runs (root seeds 1–30 × realizations 0–2), a 24 px window still drops
five frames of that run, clipping 0.184 where its uncorrected screen never
exceeds 0.101, and 26 px drops none but reaches 0.134 in the same transient.

`@4` is `@3` with a 28 px window (8.7 λ/d, 5.8 λ/r0) and nothing else
changed.  Its observing-conditions hash equals `@3`'s, and only the `profile`
and `wfs` component hashes move.  It is the narrowest even window that, over
those 90 runs, rejects no frame in closed loop or on the uncorrected screen
while keeping the worst lenslet within 80 % of the limit: clipping stays at or
below 0.091 in closed loop and 0.069 on the uncorrected screen.  Peak SNR and
centroid uncertainty stay far inside their limits (at least 8.5 against 3, at
most 0.071 px against 0.5 px), and the settled residual RMS matches `@3`'s
within 3 % on every shared realization.  Start new portfolio-scale work from
`@4`.

## Fail-closed construction

Interaction-matrix resolution policy is explicit:

- `source="build"` is the only mode permitted to calibrate;
- `source="supplied"` requires a canonical `InteractionMatrix` argument;
- `source="resource"` requires the named package JSON resource.

Missing or invalid supplied/resource matrices are errors and never trigger a
recalibration fallback.  Geometry, WFS row IDs, DM identity, reconstruction
coordinates, projector layout, controller settings, and random-root identity
are checked before the first frame.  A supplied or resource matrix must also
record a `sensor_response_hash` equal to the constructed WFS `response_hash`
(optics backend, WFS wavelength, padding and window sampling, detector
pedestal and full well relative to the source, PRNU and bad-pixel maps or
legacy PRNU seeds, photon allocation where a pedestal or full well makes it
matter, centroid estimator and threshold).  Read noise is outside that
identity, as is the photon budget of a detector without pedestal or full
well, except under `per_frame_legacy` PRNU.  A matrix
that records none is rejected rather than trusted.  An unavailable optional backend such as
`hcipy` also raises a construction error; it never substitutes the native
backend.

Notebook 09 should select the high-order geometric profile, while Notebook 11
should select a detector-level 2 m profile.  They may choose different
diagnostics, but both must call this shared construction and execution path.
