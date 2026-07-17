# AO-REF-014 — HCIPy atmosphere backend

AO-REF-014 adds `shwfs_ao.backends.hcipy.atmosphere`: single- and multi-layer
von Kármán frozen-flow atmospheres built on HCIPy's `InfiniteAtmosphericLayer`
and `FiniteAtmosphericLayer`, exposed through the canonical Section 4
`AtmosphereModel` protocol. The native Fourier/integer-roll frozen flow from
AO-REF-003A remains the transparent reference implementation; nothing in the
native backend changes.

## Public surface

- `HcipyAtmosphereLayerConfig` — one unit-explicit layer: `r0_m`,
  `outer_scale_m` (`None` or `inf` selects an unbounded outer scale),
  `wind_m_per_s`, `altitude_m`, `kind` (`"infinite"` or `"finite"`), plus the
  kind-specific numerics `stencil_length`/`use_interpolation` (infinite) and
  `oversampling` (finite).
- `HcipyAtmosphereConfig` — a non-empty layer tuple plus
  `r0_reference_wavelength_m`, `phase_conversion_reference_wavelength_m`, and
  `root_seed`; `HcipyAtmosphereConfig.single_layer(...)` builds the required
  single-layer case, and `total_r0_m` reports the combined
  `(Σ r0_i^(-5/3))^(-3/5)` strength.
- `HcipyVonKarmanAtmosphere(config, pupil_geometry, *, pupil_mask=None,
  random_streams=None)` — the `AtmosphereModel` implementation. The grid
  comes from the AO-REF-013 conversion layer
  (`hcipy_grid_from_geometry`); an optional boolean `pupil_mask` overrides
  the geometry mask for piston removal and outside-fill.

Importing the module (or the lazy re-exports on
`shwfs_ao.backends.hcipy`) never imports HCIPy. Repository-side validation
runs before the dependency is resolved, so invalid configuration raises
`HcipyAtmosphereError` even without HCIPy; only constructing or resetting a
model raises `OptionalDependencyError` on lightweight installations.

## Physical conventions

- `opd_at(time_s)` returns piston-removed OPD in metres (core
  `remove_piston`/`phase_to_opd` utilities), NaN outside the configured
  pupil, as a read-only defensive plain `numpy.ndarray` — never an HCIPy
  `Field`.
- Time is absolute and non-decreasing within a realization: going backward
  raises `HcipyAtmosphereError`, repeating the same time is idempotent, and
  `reset(realization_index=...)` returns to `t = 0`.
- `r0_m` is the Fried parameter at `r0_reference_wavelength_m`, converted
  once to the wavelength-independent integrated Cn² via HCIPy's
  `Cn_squared_from_fried_parameter`. Specifying the equivalent
  `r0_m · (λ₂/λ₁)^(6/5)` at λ₂ reproduces the same physical screens.
- `phase_conversion_reference_wavelength_m` is used *only* to query the HCIPy
  phase screen once and convert it once as `opd = phase · λ / 2π`. HCIPy
  layers are achromatic (`phase_for(λ) = screen / λ`), so with the physical
  atmosphere held fixed the returned OPD is invariant under this wavelength
  to floating-point rounding; a test pins that invariance.
- `altitude_m` is carried to HCIPy and reported in metadata; without
  inter-layer propagation there is no scintillation in this adapter and the
  altitude does not change the returned OPD (`metadata["scintillation"]` is
  `False`).

### Wind convention

`wind_m_per_s` means what it means in the native backend: the frozen phase
pattern is advected *with* the wind, translating by `+wind · t` metres in
repository `(x, y)` coordinates (`WIND_CONVENTION =
"pattern_advects_with_positive_wind"`). HCIPy 0.7 primitives were measured —
not assumed — to disagree with each other:

| HCIPy 0.7 primitive | raw behavior for `velocity = (a, b)` |
|---|---|
| `InfiniteAtmosphericLayer` | pattern translates along `(-a, -b)` |
| `FiniteAtmosphericLayer` | pattern translates along `(+b, +a)` (spectral shift built in separated-coordinate order lands `velocity[0]` on the slow y field axis) |

The adapter therefore passes `(-wx, -wy)` to infinite layers and `(wy, wx)`
to finite layers (`_WIND_NORMALIZATION_ID =
"hcipy-0.7-layer-velocity-normalization-v1"`, part of the config hash), and
the wind-direction tests assert the repository convention for both kinds on
three wind vectors, so a behavioral change in a future pinned HCIPy fails
loudly instead of silently flipping the wind. Sub-pixel translation is
tested for both kinds; neither is restricted to integer-pixel motion.

## Determinism and replay

- Every layer's screen is drawn from
  `random_streams.keyed_generator("atmosphere", key=("realization", index,
  "layer", layer_index))`; the provider defaults to
  `NamedRandomStreams(config.root_seed)` and a supplied provider must carry
  the same root seed.
- `reset(realization_index)` rebuilds all HCIPy layer state from those keyed
  generators, so replaying the same time vector is exact within one HCIPy
  environment, a different index yields independent screens, and returning
  to a previous index reproduces it exactly.
- Metadata records the realization stream ID (`random_stream_id`, consumed
  by the shared loop), per-layer stream IDs, and the derivation scheme —
  never mutable generator state.

## Metadata and identity

`metadata` is an immutable, JSON-serializable mapping exposing the complete
AO-REF-014 identity: backend name, config hash, HCIPy version, root seed,
realization index (a plain `int`, as the shared loop requires), grid shape,
pupil-geometry and pupil-mask hashes, both distinct reference wavelengths,
`total_r0_m`, and one entry per layer with its kind, `r0_m`, integrated Cn²,
outer scale, repository wind, raw HCIPy velocity, altitude, kind-specific
numerics, temporal model, and stream ID. The config hash covers the full
serialized configuration, both grid hashes, the wind-normalization and
phase-conversion construction IDs, and the random-derivation scheme.

## Loop integration and tests

`tests/backends/hcipy/test_hcipy_atmosphere.py` (all `hcipy`-marked, portable, in
the wheel-smoke manifest) covers the ticket's required list: deterministic
seeding, exact reset/replay and different-realization behavior, backward-time
rejection and same-time idempotence, pupil shape/mask/piston contract,
nonzero temporal evolution, piston-removed structure-function sanity against
Kolmogorov scaling, exact `r0_m` amplitude scaling and reference-wavelength
equivalence, wind-direction trends for both kinds, sub-pixel motion,
multi-layer variance additivity and mixed-kind evolution, metadata
completeness, and validation failures.

`TestSharedLoopRunner` demonstrates the acceptance criterion that the common
component loop (`shwfs_ao.control.loop.run_closed_loop`) switches between
the native frozen-flow and HCIPy von Kármán atmospheres purely by
configuration: the same otherwise-native geometric SCAO assembly runs with
either atmosphere and reports `backend_names["atmosphere"]` of `"native"` or
`"hcipy"`. Registering a full `"hcipy"` profile-level backend factory
requires the HCIPy DM/WFS/science components and remains with
AO-REF-015..017; cross-backend statistical comparison is AO-REF-018.

`tests/backends/hcipy/test_optional_import.py` extends the AO-REF-013
guards: the atmosphere module and its lazy re-exports import without HCIPy,
constructing a model without the dependency raises the documented
`OptionalDependencyError`, repository validation precedes the dependency
requirement, the module never imports `shwfs_ao.legacy`, and the marker
routing check now covers both hcipy-marked test files.
