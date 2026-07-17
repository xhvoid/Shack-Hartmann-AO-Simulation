# AO-REF-017 — HCIPy science propagation backend

AO-REF-017 adds `shwfs_ao.backends.hcipy.propagation`: HCIPy Fraunhofer
(perfect-lens) propagation behind the canonical `SciencePropagator`
protocol. `psf_from_opd(opd_m, wavelength_m)` builds the pupil wavefront
through the AO-REF-013 conversion layer and returns the exact Section 4
`PsfResult`: unit-total-flux discrete intensity, strictly increasing
angular axes in radians, wavelength, backend name, and complete
JSON-serializable sampling metadata.

## Public surface

- `HcipyFocalSampling(pixels_per_resolution_element=4.0,
  radius_resolution_elements=16.0)` — immutable angular sampling in
  physical resolution units: pixels across one `λ/D` element and the field
  radius in elements. The per-axis pixel count is
  `round(2 · radius · pixels_per_element)`, centered with HCIPy's
  `make_focal_grid` parity convention.
- `HcipySciencePropagator(pupil, sampling=None)` — the protocol
  implementation. The focal grid is built per wavelength with **unit focal
  length**, so HCIPy's focal-plane coordinates *are* angles in radians; the
  returned axes are read back from that grid's separated coordinates and
  are never inferred from arbitrary FFT or field indices. One propagator
  serves any number of wavelengths (per-wavelength instances are cached);
  every wavelength sees the same sampling quality and the axes scale
  exactly with `λ`.
- `focal_sampling_from_psf_sampling(pupil, sampling)` — the explicit
  translation of the repository-owned native `PsfSampling` (pad-factor)
  contract: for a square `N×N` pupil, `q = pad·N/(N−1)` and
  `radius = (N−1)/2` reproduce the native zero-padded FFT lattice
  sample-for-sample. A test pins that the two backends then agree to
  ~1e-15 of the peak on identical axes, for even and odd padded sizes and
  with aberrations.
- `captured_flux_fraction(opd_m, wavelength_m)` — per-call diagnostic for
  the pupil-power fraction landing inside the focal window. It is
  deliberately *not* part of `PsfResult.sampling_metadata`, which stays
  construction-determined so the science metrics can require exact
  sampling identity between a PSF and its ideal reference.
- `shwfs_ao.science.propagation.monochromatic_psf` now serves both
  backends: `backend="hcipy"` lazily constructs the HCIPy propagator on the
  translated lattice, resolving the optional dependency only at
  construction; unknown identifiers are still rejected.

Importing the module never imports HCIPy; repository-side validation runs
first, so invalid pupils, samplings, OPD maps, or wavelengths raise
`HcipySciencePropagationError` even on lightweight installations.

## Physics pinned by tests

`tests/backends/hcipy/test_hcipy_propagation.py` (all `hcipy`-marked,
portable, in the wheel-smoke manifest) covers the ticket list:

- normalized total intensity (exact unit sum, non-negative, read-only
  plain arrays — no HCIPy grid, wavefront, or propagator object escapes);
- diffraction-limited peak at the exact origin sample, lowered by
  aberration;
- Airy-scale sanity: circular-pupil first minimum at `1.22 λ/D` within 8 %;
- central obstruction: the on-axis peak scales as `(1 − ε²)` within 5 %
  and the core tightens;
- phase-to-PSF wavelength scaling: Strehl follows the Maréchal
  approximation within 2 % at two wavelengths (measured 0.7484 vs 0.7482);
- angular-axis monotonicity, dimensional consistency (`Δθ = λ/(D·q)`,
  centered origin), and Airy-radius scaling `∝ λ`;
- native-versus-HCIPy Strehl agreement on *independent* grids (measured
  difference 6e-5, asserted < 5e-3);
- a flux-conserving comparison after explicit resampling onto a common
  angular grid: HCIPy surface brightness is cubic-interpolated onto the
  native lattice, flux is conserved against the source window within 2 %,
  and the renormalized profiles agree pointwise within 1e-3 of the peak
  (measured 1.9e-4).

The acceptance criteria are demonstrated directly: `peak_strehl_from_
discrete_flux`, `psf_scalar_metrics`, and `encircled_energy_radius_from_
discrete_flux` consume HCIPy `PsfResult`s unchanged, and one
`monochromatic_psf` call serves either backend by name.

`tests/backends/hcipy/test_optional_import.py` extends the standing guards
to the new module (lazy import, no-legacy audit, marker routing,
validation-precedes-dependency, and `OptionalDependencyError` from both the
propagator and the `backend="hcipy"` registry path on installations without
HCIPy). The native rejection test now uses a genuinely unknown backend
name, since `"hcipy"` is a registered identifier.

Native-versus-HCIPy cross-validation as a suite — including statistical
atmosphere comparisons and closed-loop trends — is AO-REF-018.
