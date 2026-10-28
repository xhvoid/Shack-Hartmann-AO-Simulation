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

config = load_system_profile("fast_2m_detector", 1)
system = build_scao_system(config)
history = run_closed_loop(config, system=system)
```

The experiment layer owns assembly and sequencing only.  Native numerical
kernels remain in `shwfs_ao.backends.native`; the backend-independent frame
loop and telemetry remain in `shwfs_ao.control`.  Artifact paths and file
writing are outside this boundary.

## Versioned profiles and hashes

The installed schema-v1 presets are:

- `fast_2m_detector@1`;
- `portfolio_2m_detector@1`;
- `research_2m_detector@1`;
- `high_order_10m_geometric@1`.

`high_order_10m_hcipy` remains a later optional-backend profile.  Loading is
always by an explicit `(name, version)` pair; there is no implicit “latest”
selection.

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
