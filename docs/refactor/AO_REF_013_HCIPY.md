# AO-REF-013 — Optional HCIPy dependency and conversion layer

AO-REF-013 introduces HCIPy as a constrained optional dependency, the
repository/HCIPy conversion layer, the strict `hcipy` and `slow` pytest
markers, the portable wheel-smoke bundle preparer, and the first Python 3.11
HCIPy CI lane. No physical backend is implemented here: HCIPy atmosphere, DM,
Shack-Hartmann optics, and science propagation are AO-REF-014 through
AO-REF-017 and extend this lane in their own pull requests.

## Optional dependency contract

- The extra is declared as `hcipy>=0.7,<0.8`; the resolved Python 3.11 Linux
  environment (`.[test,hcipy]` plus the `build` frontend) is pinned in
  `constraints/hcipy-py311.txt`. HCIPy 0.7.0 is the only release in that
  window at the time of writing.
- `import shwfs_ao`, the core protocols and result types, serialized configs,
  and every native backend import without HCIPy installed.
  `shwfs_ao.backends.hcipy` and its `conversion` module also import lazily;
  only *calling* HCIPy-backed functionality resolves the dependency.
- A missing dependency raises `OptionalDependencyError` (an `ImportError`
  subclass) whose message names the exact
  `pip install 'shack-hartmann-ao-simulation[hcipy]'` command.
- `shwfs_ao.backends.hcipy.hcipy_installed()` is the documented availability
  probe; `hcipy_version()` reports the installed distribution version for
  backend metadata.

## Conversion layer

`shwfs_ao.backends.hcipy.conversion` owns the boundary between repository
arrays and HCIPy objects:

| Direction | Function |
|---|---|
| meshgrids → grid | `hcipy_grid_from_coordinates(x_m, y_m)` |
| `PupilGeometry` → grid | `hcipy_grid_from_geometry(geometry)` |
| grid → meshgrids | `coordinates_from_hcipy_grid(grid)` |
| mask → aperture field | `aperture_field_from_mask(pupil_mask, grid)` |
| aperture field → mask | `mask_from_aperture_field(field, threshold=0.5)` |
| masked array → field | `field_from_masked_array(values, pupil_mask, grid)` |
| field → masked array | `masked_array_from_field(field, pupil_mask, outside_fill=nan)` |
| OPD → wavefront | `wavefront_from_opd(opd_m, pupil_mask, grid, wavelength_m=...)` |
| wavefront → OPD | `opd_m_from_wavefront(wavefront, pupil_mask, outside_fill=nan)` |

Contract highlights:

- Flattening is the C-order ravel of `(rows, columns)` arrays, which is
  exactly HCIPy's x-fastest point order; `FLATTENING_ORDER` records the
  convention and `field[row * columns + column] == array[row, column]` is
  tested literally.
- Grids are built from the exact repository origin and spacing
  (`RegularCoords(delta, dims, zero)`), never re-centered, and only regular
  separated Cartesian grids convert back.
- Repository arrays may be NaN outside the pupil, never inside it. Every
  conversion validates in-pupil finiteness *before* the optional dependency
  is resolved, so invalid physics raises `HcipyConversionError` even on
  installations without HCIPy. Only outside-pupil samples are replaced by
  zero on the HCIPy side, and the return path restores the mask and the
  caller's requested outside fill. There is no blanket `nan_to_num`.
- Reverse conversions return plain `numpy.ndarray` objects; HCIPy `Field`
  subclasses never leak into repository results.
- `wavefront_from_opd` requires an explicit wavelength and builds
  `exp(1j · 2π · opd / λ)` inside the pupil with exactly zero field outside.
  `opd_m_from_wavefront` reads the wrapped phase and is therefore only
  unambiguous for |phase| < π; it exists for conversion checks and
  small-signal fixtures, not for reconstructing accumulated OPD.

## Markers and CI

- `hcipy` and `slow` are registered markers and `--strict-markers` is default
  via `pyproject.toml`, so an unregistered marker fails collection.
- The native matrix now selects `-m "not hcipy and not slow"`. Every test in
  `tests/backends/hcipy/test_conversion.py` carries the `hcipy` marker, and a
  routing test asserts the file collects zero tests under the native
  selection.
- `tests/backends/hcipy/test_optional_import.py` is unmarked: it proves lazy
  imports (with a clean subprocess), the `OptionalDependencyError` message,
  and — only on environments without HCIPy — that input validation precedes
  the dependency requirement.
- The new `hcipy` job runs on Python 3.11 with
  `constraints/hcipy-py311.txt`: it builds the wheel and sdist, replaces the
  source install with the built wheel, runs `pip check`, prepares the smoke
  bundle, asserts the hcipy selection collects at least one test, and runs
  both the hcipy and native selections from the bundle.

## Wheel-smoke bundle

`scripts/prepare_wheel_smoke_bundle.py` copies the files listed in
`tests/wheel_smoke/manifest.json` (plus `tests/wheel_smoke/pytest.ini` as the
bundle root config) into an absent-or-empty output directory:

```bash
python scripts/prepare_wheel_smoke_bundle.py --output "$TMPDIR/wheel-smoke" [--include-hcipy]
```

The preparer refuses `src/` and `.git/` sources outright, allows only
`tests/` and `examples/` prefixes, rejects path traversal and duplicates, and
copies entries whose `requires` list names `hcipy` only when
`--include-hcipy` is passed. AO-REF-013 seeds the manifest with the
conversion and optional-import tests only; later tickets append their own
portable tests, fixtures, and examples, and AO-REF-020 audits and completes
the manifest.
