# AO-REF-015 — HCIPy DM backend

AO-REF-015 adds `shwfs_ao.backends.hcipy.dm`: HCIPy Gaussian influence
functions and `hcipy.DeformableMirror` surface synthesis behind the canonical
AO-REF-006 `DmBackend` boundary. The repository wrapper
`shwfs_ao.dm.model.DeformableMirror` remains the single owner of stroke
clipping, dead/stuck actuator policy, command clipping, and saturation
diagnostics; the HCIPy backend is a memoryless spatial synthesizer, exactly
like the native NumPy backend it can be compared against. Control latency
stays where AO-REF-009 put it — this backend holds no delay queue and no
command history.

## Public surface

- `HcipyDmBackend(influence_function_basis, x_m, y_m)` — the `DmBackend`
  implementation. It wraps an `hcipy.ModeBasis` of surface influence
  functions on a regular separated Cartesian grid that must reproduce the
  repository `x_m`/`y_m` meshgrids, densifies the mode stack into an
  immutable `(n_actuators, rows, columns)` repository array, and owns a
  private `hcipy.DeformableMirror` for synthesis.
- `build_hcipy_gaussian_influence_basis(x_m, y_m, actuator_centers_m,
  actuator_pitch_m, *, coupling_width_pitch=0.35, normalize_peak=True,
  pupil_mask=None)` — one `exp(-r²/(2σ²))` HCIPy poke per repository
  actuator centre, in repository order, with `σ = coupling_width_pitch ·
  actuator_pitch_m` — the same analytic Gaussian as the native
  `build_influence_functions`. With `normalize_peak=True` (requires
  `pupil_mask`) each mode is scaled so its largest sampled in-pupil value is
  exactly one, reproducing the native normalization convention.
- `build_hcipy_deformable_mirror(x_m, y_m, pupil_mask, config=None)` — the
  canonical factory mirroring `build_native_deformable_mirror`: the actuator
  layout, ordering, pitch, and identifiers come from the same repository
  `square_grid_actuator_layout` + `actuator_ids_from_grid_indices`
  construction, so a native and an HCIPy mirror built from the same
  `DMConfig` expose identical actuator IDs on a matched geometry. Only the
  `"gaussian"` influence model is representable; the other frozen influence
  families remain native-only and are rejected with a clear error.

Importing the module (or the lazy re-exports on `shwfs_ao.backends.hcipy`)
never imports HCIPy. Repository-side validation runs before the dependency
is resolved, so an invalid `DMConfig`, influence model, coordinate grid, or
pupil mask raises `HcipyDmError` even on lightweight installations; only
constructing the basis/backend raises `OptionalDependencyError` there.

## Command convention and the reflective factor of two

Repository DM commands are OPD-equivalent influence amplitudes in metres
(AO-REF-006). `hcipy.DeformableMirror` actuators are *reflective surface
displacement*: its `opd` property returns `2 × surface` and `forward()`
multiplies the electric field by `exp(2j·k·surface)`. The adapter therefore
(`SURFACE_COMMAND_CONVENTION =
"half_opd_command_to_surface_single_hcipy_doubling"`):

1. sets `actuators = 0.5 × commands_opd_m` (surface metres), and
2. returns HCIPy's own doubled `opd` unchanged.

The factor of two is applied exactly once, in one place. Tests pin this from
both directions: feeding commands directly into a raw `hcipy.DeformableMirror`
as surface amplitudes yields exactly twice the adapter's correction, a
commanded amplitude reproduces itself (not half, not double) as the in-pupil
correction peak, and a flat HCIPy wavefront reflected off a mirror carrying
the adapter's surface acquires exactly the correction OPD the adapter
reports. A single-mode sign test confirms the §3.1.1 loop convention: a
positive command produces a positive correction map whose subtraction
cancels a matching atmospheric OPD to floating-point precision.

Because the halving and doubling cancel, each densified influence mode is
numerically also the correction-OPD response per unit command, so the
wrapper's calibration, hashing, and command-projection layers see the same
kind of influence stack the native backend provides.

## Boundary and statelessness

- `influence_functions()` and `opd_from_commands()` return immutable plain
  `numpy.ndarray` objects in the repository `(rows, columns)` layout — never
  an HCIPy `Field`, sparse matrix, or actuator array. Backend metadata is an
  immutable JSON-serializable mapping (backend name, config hash, HCIPy
  version, conventions).
- Every synthesis call overwrites the private mirror's actuators before
  reading the surface and flattens it afterwards; identical repeated calls
  return identical corrections and no command history leaks between calls.
- The wrapper feeds the backend only post-policy commands, so stroke, dead,
  and stuck behavior with the HCIPy backend is byte-identical policy to the
  native path, and `DmSynthesisResult` carries repository actuator IDs, SI
  units, and the wrapper config hash.
- Inside the pupil the factory's influence functions match the native
  backend to ~1 ulp; outside the pupil the HCIPy surface deliberately keeps
  its analytic Gaussian tail where the native construction stores zeros.
  Nothing downstream consumes out-of-pupil correction samples (residuals are
  NaN outside the pupil), and the matched-comparison tests document the
  difference explicitly.

## Tests

`tests/backends/hcipy/test_hcipy_dm.py` (all `hcipy`-marked, portable, in the
wheel-smoke manifest) covers the ticket's required list: zero-command
surface, single-actuator response, linearity below stroke, matched Gaussian
influence comparison against the native backend, actuator-ordering
consistency, the explicit reflective factor-of-two and correction-sign
tests, identical repeated calls proving the backend has no hidden latency or
command state, and the common static-fitting trend (least-squares fitting
error falls with actuator density for both backends, which agree on the
residual to ~1e-9 relative).

`TestSharedCalibrationAndLoop` demonstrates the acceptance criteria that a
`DeformableMirrorModel` using HCIPy passes through the shared layers
unchanged: `DmActuatorProbeBasis` + `calibrate_interaction_matrix` build an
HCIPy-backed interaction matrix, and `run_closed_loop` runs the otherwise
native geometric SCAO assembly with the HCIPy DM, reporting
`backend_names["dm"] == "hcipy"` while the controller keeps sole ownership
of gain, leak, and latency state.

`tests/backends/hcipy/test_optional_import.py` extends the AO-REF-013/014
guards to the DM module: it imports without HCIPy (lazily, via the package
re-exports too), never imports `shwfs_ao.legacy`, the marker-routing check
covers the new test file, and on installations without HCIPy the factory
raises the documented `OptionalDependencyError` only after repository-side
validation has had the chance to fail first.

Registering a full `"hcipy"` profile-level backend factory still awaits the
HCIPy WFS/science components (AO-REF-016/017); native-versus-HCIPy
closed-loop cross-validation is AO-REF-018.
