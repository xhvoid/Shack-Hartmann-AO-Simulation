<!-- Science-metrics note for Strehl, Marechal agreement, FWHM, EE50/EE80, halo fraction, and J/H/K-style band metrics. -->

# Science Metrics Notes

The science-metrics layer adds `src/ao_diagnostics.py`, a science-facing diagnostics layer for residual OPD maps.

The module consumes OPD maps in nanometres and converts them to phase at each science wavelength before computing PSFs. This keeps wavelength handling explicit:

```text
OPD_nm -> phase_rad(lambda_sci) -> normalized PSF -> scalar metrics
```

Reported metrics include:

```text
Strehl from PSF peak ratio
Marechal Strehl
Marechal absolute error
FWHM in pixels, lambda/D, and arcsec
EE50 and EE80 in pixels, lambda/D, and arcsec
halo fraction outside a configurable lambda/D radius
```

For the fast 2 m demonstrator, the most robust science-facing scalar metrics are residual OPD RMS, Strehl, FWHM, and halo fraction. EE50/EE80 are useful secondary diagnostics, but they can show visible grid/radius quantization when the PSF sampling is deliberately small for fast reruns.

Bandpass support is intentionally lightweight. If a direct SVO public-cache filter curve is available through the data-source loader, module uses its wavelength/transmission samples and carries the filter provenance into the band-level metric rows. If not, a documented monochromatic or top-hat fallback can be used. Current band-aware results are transmission-weighted scalar metrics; they are not full broadband detector-plane PSFs resampled onto one angular grid.

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

These metrics are science-facing simulation diagnostics for a compact 2 m SCAO demonstrator, not validation against public on-sky AO telemetry and not an ELT-scale performance prediction.
