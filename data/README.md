<!-- Detector-level AO extension data layout: tracked public reference caches, offline fallbacks, synthetic presets, and small regression metrics carry explicit provenance. -->

# Data Layout for the Detector-Level AO Extension

The fast notebooks and tests must run without internet, but the detector-level
AO extension is real-data oriented where public data can be used cleanly. Small
public reference caches are tracked in `data/public/`; raw downloads and larger
temporary products stay in `data/external/` or `data/cache/`.

```text
public/                small tracked public reference caches with direct provenance
external/              raw downloaded public data; ignored by git except .gitkeep
cache/                 generated caches with config hashes; ignored by git except .gitkeep
samples/               small offline fixtures for tests and fast-mode notebooks
literature_profiles/   curated literature-derived atmosphere profiles
synthetic_presets/     synthetic detector, DM, NCPA, and misregistration presets
reference_metrics/     small JSON/CSV regression references for fast integration runs
```

## Current Public Caches

```text
public/svo_2mass_j_direct.csv
public/svo_2mass_h_direct.csv
public/svo_2mass_ks_direct.csv
public/target_photometry_2mass_psc_demo_ngs_bright.csv
public/target_photometry_panstarrs_dr2_demo_ngs_bright.csv
public/eso_asm_paranal_20240729_0300_0800_snapshot.json
public/eso_asm_paranal_20240729_0300_0800_timeseries.csv
```

These are small direct-public-data products generated from:

```text
SVO Filter Profile Service, 2MASS/2MASS.J/H/Ks direct filter curves
IRSA 2MASS All-Sky Point Source Catalog PSC cone query
MAST Pan-STARRS DR2 mean catalog cone query
ESO Paranal ASM API, 2024-07-29 03:00-08:00 UTC seeing/tau0/theta0/turbulence speed
```

The ASM window is a nighttime Paranal window, approximately 23:00-04:00 CLT for
Chile winter. It is used to condition synthetic AO scenarios; it is not AO
telemetry from an operating RTC.

Refresh the tracked public caches with:

```bash
python scripts/fetch_public_reference_data.py
```

## Public-data-informed result artifacts

```text
figures/detector_level_SCAO/public_data_overview.png
figures/detector_level_SCAO/public_filter_curves_jhk.png
figures/detector_level_SCAO/public_data_photon_budget.png
figures/detector_level_SCAO/public_data_informed_ao_photon_scan.png
figures/detector_level_SCAO/public_data_informed_error_budget.png
figures/detector_level_SCAO/public_data_informed_validation.png
figures/detector_level_SCAO/public_data_summary.csv
figures/detector_level_SCAO/public_data_photon_budget.csv
figures/detector_level_SCAO/public_data_informed_ao_photon_scan.csv
figures/detector_level_SCAO/public_data_informed_conditions.csv
figures/detector_level_SCAO/public_data_informed_error_budget.csv
figures/detector_level_SCAO/public_data_informed_runtime.csv
figures/detector_level_SCAO/public_data_informed_runtime.json
figures/detector_level_SCAO/public_data_informed_validation.csv
```

`public_data_informed_ao_photon_scan.csv` records direct-public conditioning
columns separately from the synthetic AO loop model. The Pan-STARRS point is a
real catalog-photometry photon-budget anchor; the 50, 200, and 8000
photons/subap/frame cases are engineering comparison levels.

`public_data_informed_conditions.csv` records the five observing/error
conditions used by Notebook 11: `nominal_synthetic`, `paranal_night_asm`,
`poor_seeing`, `faint_ngs`, and `stress_all_effects`. Modes such as fast,
portfolio, and research control numerical scale only; the condition table
controls seeing, photon budget, read noise, latency, stroke, NCPA, and
misregistration proxies.

`public_data_informed_runtime.csv` and `.json` record the local wall-clock
runtime for the slower public-data-informed demo, including a 30 minute limit flag.
The latest recorded run is below that limit and performs no live archive query.

## Offline Fixtures and Synthetic Presets

```text
samples/eso_asm_snapshot_sample.json
samples/svo_2mass_h_sample.csv
samples/target_photometry_sample.csv
literature_profiles/paranal_three_layer_literature_inspired.json
synthetic_presets/dm_2m_fast_gaussian.json
reference_metrics/fast_reference_metrics.json
reference_metrics/fast_reference_metrics_regression_baseline.json
reference_metrics/fast_error_budget_regression_baseline.csv
reference_metrics/fast_validation_regression_baseline.csv
```

The files in `samples/`, `literature_profiles/`, and `synthetic_presets/` are
fallback fixtures and regression references for interface development. They are
not measured AO telemetry and should not be described as observatory validation
data.

## Sources Not Used

Gaia DR3 is optional for this extension. The ESA Gaia Archive was inaccessible
from this environment, so Gaia is not claimed as an input here. Pan-STARRS DR2
is the current optical-photometry substitute for WFS photon-budget anchoring.

ERA5/CDS is not used in the current public-data-informed demonstrator. ESO ASM
already supplies direct public seeing, tau0, theta0, and turbulence-speed
conditioning for the selected Paranal nighttime window; ERA5 would require user
CDS API credentials and a separate meteorological downselection before it could
be claimed.
