# Validation and limitations

This project is checked with **internal sanity checks** — physical-trend and
reproducibility tests on the model's own outputs. It is **not** validated against
real observatory data. This document states both sides explicitly, because the
distinction is what makes the numbers trustworthy for a learning/portfolio
context.

## What is checked (internal sanity checks)

The checks below are implemented in [`src/ao_validation.py`](../src/ao_validation.py)
and exercised by [`tests/test_validation_checks.py`](../tests/test_validation_checks.py),
[`tests/test_detector_centroids.py`](../tests/test_detector_centroids.py), and the
fast integration test [`tests/test_integration_fast.py`](../tests/test_integration_fast.py).
The fast 2 m integration reports a pass/fail count for the first six.

| Check | What it verifies | Implementation |
| --- | --- | --- |
| Marechal consistency | Strehl is consistent with `exp[-(2*pi*sigma_OPD/lambda)^2]` for small residuals; Strehl decreases as residual OPD RMS grows. | `check_marechal_consistency` |
| Diffraction scale | The ideal-PSF FWHM is near the `lambda/D` diffraction scale. | `check_diffraction_scale` |
| Photon → centroid noise | Centroid noise / uncertainty decreases as photon count increases. | `check_centroid_noise_photon_monotonicity` |
| Read noise → centroid quality | Higher read noise degrades centroid quality and valid-centroid fraction. | `test_high_read_noise_reduces_centroid_validity` |
| Latency → residual | Closed-loop residual worsens with increasing frame delay. | `check_latency_residual_monotonicity` |
| DM fitting trend | Static fitting residual does not worsen as actuator count increases. | `check_dm_fitting_trend` |
| Reproducibility | Fixed seeds reproduce key scenario metrics. | `check_scenario_reproducibility` |
| Centroid validity (faint photons) | Sub-photon / low-SNR WFS budgets report a low valid-centroid fraction instead of plausible-looking centroids built from noise. | `CentroidValidityConfig` + `measure_detector_shwfs`, tested in `tests/test_detector_centroids.py` |

These are **trend and consistency checks**, not absolute-accuracy validation: they
confirm the model behaves the right way as inputs change, and that runs are
reproducible.

## How to run the checks

```bash
pytest -q                                      # all unit + integration checks
python examples/run_validation_checks_demo.py   # validation table (CSV/PNG)
python examples/run_fast_integration.py        # fast integration + reference metrics
```

## Public-data-informed scenario validation scope

The public-data-informed validation table
(`figures/detector_level_SCAO/public_data_informed_validation.csv`) is a **provenance and
finiteness check, not an adaptive-optics performance validation**. It confirms
that a nighttime ESO ASM condition and a catalog photon condition are present,
that the scenario metrics are finite, that the AO-internal terms are not labelled
as direct public data, that the SVO J/H/Ks caches are used, and that the run stays
under its runtime budget.

It deliberately does **not** treat a low valid-centroid fraction as a failure. A
faint scenario such as `faint_ngs` or `stress_all_effects` has a sub-photon WFS
photon budget, so `valid_centroid_frac = 0`: there are no usable centroids, the
loop freezes (no command is applied), and the closed-loop residual approaches the
open-loop value. That is the physically honest outcome, and it still passes the
provenance/finite checks. The per-scenario `valid_centroid_frac` column in the
error-budget table is what indicates whether the loop actually closed.

## What is NOT validated

The repository is **not** validated against, and must not be read as representing:

- real AO telemetry;
- a real telescope / instrument calibration;
- measured DM influence functions;
- measured WFS detector data;
- atmospheric site-monitoring time series beyond the small public-data anchors
  used to *condition* synthetic scenarios.

Public data (ESO ASM seeing, SVO 2MASS J/H/Ks curves, Pan-STARRS / 2MASS
photometry) are used to condition or anchor synthetic scenarios; they do not
turn the internal AO model into a calibrated instrument prediction.
