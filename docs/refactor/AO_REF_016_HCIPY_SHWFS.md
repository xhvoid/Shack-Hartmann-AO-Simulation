# AO-REF-016 — HCIPy Shack-Hartmann optical backend

AO-REF-016 adds `shwfs_ao.backends.hcipy.shwfs`: HCIPy microlens-array
Fresnel propagation behind the canonical `ShackHartmannOpticsBackend`
boundary. The preferred chain of the ticket is realized exactly:

```
residual OPD → HCIPy wavefront → HCIPy microlens array + Fresnel focal
plane → detector-plane intensity → repository detector effects →
repository centroid estimator → repository validity evaluation
```

The backend returns the Section 4 `SpotIntensityResult` and nothing
detector-specific; the repository detector, centroiding, and validity
modules are reused unchanged through the shared
`build_detector_shack_hartmann_sensor`/`calibrate_zero_phase_reference`
pipeline.

## Public surface

- `HcipyShackHartmannOptics(geometry, wfs_wavelength_m, *, f_number)` — the
  `ShackHartmannOpticsBackend` implementation. `f_number` is the lenslet
  focal ratio: the focal length is `f_number ×` lenslet pitch and the
  diffraction-limited spot spans `λ · f_number / pixel_pitch` detector
  pixels. The backend exposes `sampling`/`detector_sampling`, `geometry`,
  `wfs_wavelength_m`, and `config_hash`, so the repository calibration layer
  cross-checks geometry, wavelength, and sampling identity exactly as it
  does for the native backend.
- `hcipy_estimator_centroids_px(residual_opd_m)` — the ticket's optional
  HCIPy estimator comparison, wrapped as diagnostics-only telemetry: a plain
  read-only `(n_subapertures, 2)` array of centroid offsets in detector
  pixels, in repository subaperture order. It never participates in
  calibration or measurement, and a test pins that it agrees with the
  repository window centroid to numerical precision (same pixels, same
  first-moment arithmetic).

Importing the module never imports HCIPy; repository-side validation runs
first, so invalid geometry, wavelength, focal ratio, or sampling raises
`HcipyShackHartmannError` even on lightweight installations.

## Matched pupil and lenslet geometry

The microlens array is built at the repository's nominal lenslet cell
centres — including cells the geometry rejected for fill fraction, so their
light is still focused by a real lens instead of leaking unphysically into
neighbours. Construction validates three equivalences and fails loudly on
any drift:

1. every retained subaperture's mask equals its nominal pixel block
   intersected with the pupil;
2. the nominal cell centres match `geometry.subaperture_centers_m`;
3. HCIPy's closest-centre lenslet assignment (`mla_index`) reproduces the
   repository index-block partition exactly.

The detector plane is the pupil-sampled Fresnel focal plane: each retained
subaperture's full detector window is its own pixel block, extracted per
canonical subaperture ID in the exact geometry order. This mapping requires
every pupil axis to contain an integer number of pixels per lenslet; other
samplings are rejected with a clear error and remain the native backend's
territory. Window shape, sampling hash, nominal centres, the propagation
and window-mapping construction IDs, and the throughput semantics all enter
the backend config hash.

## Sampling, sign, and normalization conventions

- `pixel_scale_rad` is the pupil pixel pitch divided by the lenslet focal
  length, per axis; the window reference pixel is the nominal window centre
  `((w−1)/2, (w−1)/2)`. Each lenslet's true optical axis sits at a
  deterministic subpixel offset from that reference (the cell centres are
  not pixel-block centres); exactly as for the native backend, the
  repository zero-phase reference calibration absorbs it, and a test checks
  interior zero-phase spots sit on the predicted axes.
- The repository phase convention `phase = 2π · OPD / λ` is applied through
  the AO-REF-013 conversion layer, and HCIPy's measured chain satisfies the
  repository detector orientation directly: increasing positive x-tilt
  moves the spot toward increasing detector column x, positive y-tilt
  toward increasing detector row y, with sign tests in both directions and
  linear small-tilt response.
- Every returned spot is finite, non-negative, unit-sum on the full window;
  `relative_throughput` is reported separately as the detector-window
  capture fraction: window flux over that lenslet's illuminated input flux,
  clipped to `[0, 1]` (the native backend clips its capture fraction the
  same way). Full-field propagation makes neighbouring wings physical;
  fully illuminated lenslets measure ≈ 0.98.
- No HCIPy `Field`, field ordering, or estimator result crosses the
  boundary: spots are plain immutable arrays, and the shared measurement
  path produces `WfsMeasurement` objects whose metadata stays
  JSON-serializable.

## Tests

`tests/backends/hcipy/test_hcipy_shwfs.py` (all `hcipy`-marked, portable, in
the wheel-smoke manifest) covers the ticket list: zero-phase references
(canonical contract, exact zero measurement through the noiseless shared
chain), pure tip/tilt centroid sign in both directions, linear centroid
response for small tilts, lenslet count and valid-subaperture ordering,
flux conservation within the defined normalization, missing/duplicate ID
and detector-window shape rejection at the strict boundary validator,
matched detector sampling and photon allocation through the shared detector
chain, and native-versus-HCIPy spot morphology: on the same angular window
the EE50 spot radius agrees within 20 % and small-tilt centroid gains agree
within 0.2.

The acceptance criteria are demonstrated end to end:
`build_detector_shack_hartmann_sensor` calibrates a detector-level
zero-phase reference on the HCIPy optics, the same detector and validity
modules produce the measurement, and `calibrate_interaction_matrix` builds
a fully HCIPy-backed matrix from an HCIPy DM (`build_hcipy_deformable_mirror`,
AO-REF-015) probed through the HCIPy-optics detector sensor.

`tests/backends/hcipy/test_optional_import.py` extends the AO-REF-013/014/015
guards to the new module: lazy import (module and package re-exports),
no-legacy-import audit, marker routing for the new test file, and on
installations without HCIPy the documented `OptionalDependencyError` only
after repository-side validation has had the chance to fail first.

HCIPy science propagation is AO-REF-017; native-versus-HCIPy closed-loop
cross-validation is AO-REF-018.
