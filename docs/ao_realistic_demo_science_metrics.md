<!-- Science-metrics note for Strehl, Marechal agreement, FWHM, EE50/EE80, halo fraction, and J/H/K-style band metrics. -->

# Science metrics notes

The canonical science layer is `shwfs_ao.science`. It separates immutable
bandpasses, backend-independent monochromatic propagation construction, and
scalar physical-grid metrics. The centered NumPy FFT implementation lives in
`shwfs_ao.backends.native.propagation`. The installed `ao_diagnostics` and
`psf_tools` modules retain their frozen historical signatures and result
formats as compatibility facades.

Canonical propagation consumes residual OPD maps in metres and applies each
science wavelength explicitly:

```text
residual OPD_m -> phase_rad(lambda_sci) -> unit-flux PsfResult -> scalar metrics
```

Passing WFS phase directly is incorrect when the WFS and science wavelengths
differ. Compatibility calls that still accept nanometres or phase convert once
at their canonical boundary.

The canonical `PsfResult` carries strictly increasing x/y angular axes in
radians. Its intensity samples are discrete pixel flux normalized to sum to
one, not angular surface brightness. Reported metrics include:

```text
Strehl from PSF peak ratio
Marechal Strehl
Marechal absolute error
FWHM in radians, lambda/D, and arcsec
EE50 and EE80 in radians, lambda/D, and arcsec
halo fraction outside a configurable lambda/D radius
```

Peak Strehl receives discrete pixel flux but compares peaks after dividing by
the physical pixel solid angle. Encircled energy and halo fraction integrate
discrete pixel flux; FWHM consumes angular surface brightness. Encircled-energy
radii, FWHM, and halo apertures therefore use the angular axes rather than
deriving scale from array indices.

The frozen compatibility `SciencePsfMetrics` rows additionally retain their
historical `fwhm_px`, `ee50_px`, and `ee80_px` fields, exact field order, and
nanometre-facing inputs. Those fields support existing notebooks and files;
they do not change the canonical requirement to compute metrics from a
physical `PsfResult` grid.

For the fast 2 m demonstrator, the most robust science-facing scalar metrics are residual OPD RMS, Strehl, FWHM, and halo fraction. EE50/EE80 are useful secondary diagnostics, but they can show visible grid/radius quantization when the PSF sampling is deliberately small for fast reruns.

Bandpass support is intentionally lightweight. If a direct SVO public-cache
filter curve is available through the data-source loader, the canonical
converter validates its metre/dimensionless units and provenance before
building an immutable `ScienceBandpass`. Otherwise a documented monochromatic
or top-hat fallback can be used. Current band-aware results are
quadrature-weighted scalar metrics only. They are not broadband detector-plane
images, and same-index pixels from wavelength-dependent PSF grids must never be
stacked. A future image API must require a common physical angular grid,
flux-conserving resampling, and interpolation provenance before coaddition.

Validation summary:

```text
For the default preset, closed-loop Strehl exceeds open-loop Strehl.
```

The tests also check:

```text
A fast detector-level dynamic loop has higher H-band closed-loop Strehl than open-loop Strehl after settling.
PSF peak Strehl agrees with the Marechal approximation for a small residual OPD map.
```

The command-line diagnostic is:

```bash
python3 examples/run_science_metrics_demo.py
```

It writes:

```text
figures/detector_level_SCAO/science_psf_metrics.csv
figures/detector_level_SCAO/science_psf_metrics.png
```

These metrics are science-facing simulation diagnostics for a compact 2 m SCAO
demonstrator, not validation against public on-sky AO telemetry and not an
ELT-scale performance prediction. The detailed canonical and compatibility
contracts are documented in
[AO-REF-010](refactor/AO_REF_010_SCIENCE.md).
