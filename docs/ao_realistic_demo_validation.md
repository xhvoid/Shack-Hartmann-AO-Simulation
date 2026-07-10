<!-- Validation note for Marechal tolerance, photon/latency monotonicity, reproducibility, diffraction-scale sanity, and DM-fitting trend checks. -->

# Validation Notes

The validation layer adds `src/ao_validation.py`, a small set of pass/fail sanity checks intended for notebook 11 and unit tests.

Validation summary:

```text
The Marechal check remains within its documented tolerance.
```

Implemented checks:

```text
marechal_consistency
diffraction_scale
photon_centroid_noise_monotonicity
latency_residual_monotonicity
scenario_reproducibility
dm_fitting_trend
```

The monotonicity checks cover:

```text
Higher photon count should not worsen centroid RMS in the same seed ensemble.
Larger latency should not systematically improve dynamic-loop residual RMS.
```

The reproducibility check covers:

```text
Repeated scenario runs with identical config and seed reproduce the same main metrics.
```

The Marechal check is only applied to small residual OPD maps. Larger residuals can deviate because the approximation is an exponential small-phase result, while the PSF peak-ratio metric is computed from sampled Fourier optics.

The command-line diagnostic is:

```bash
python examples/run_validation_checks_demo.py
```

It writes:

```text
figures/detector_level_SCAO/validation_checks.csv
figures/detector_level_SCAO/validation_scans.png
```

These checks are sanity checks for a synthetic AO demonstrator. They should not be described as on-sky validation or as validation against private AO telemetry.
