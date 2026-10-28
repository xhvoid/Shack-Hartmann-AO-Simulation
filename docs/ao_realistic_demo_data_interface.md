<!-- Data-source interface note for public atmosphere, filter, photometry, and literature-profile inputs. -->

# Data-Source Interface Notes

The data-source interface adds the first reusable data-ingestion layer for the detector-level AO extension. The loaders currently live in `src/shwfs_ao/legacy/data_sources.py`, are re-exported through the installed `data_sources` compatibility module, and return typed Python objects rather than raw dictionaries or notebook-only parsing snippets.

The implementation keeps two tracks:

```text
src/shwfs_ao/resources/public/   small tracked direct-public-data caches
src/shwfs_ao/resources/samples/  offline synthetic or literature-inspired fallback fixtures
```

These canonical source files are installed in `shwfs_ao.resources` and opened
through `importlib.resources`. A byte-identical `ao_simulation_data` alias is
generated only while building distributions. Relative `data/...` names remain
supported logical compatibility inputs; installed execution does not require a
repository root. If a direct SVO cache is
unavailable, the selected fallback is retained in the returned bandpass
provenance instead of being silent.

Current direct public cache logical names are:

```text
data/public/svo_2mass_j_direct.csv
data/public/svo_2mass_h_direct.csv
data/public/svo_2mass_ks_direct.csv
data/public/target_photometry_2mass_psc_demo_ngs_bright.csv
data/public/target_photometry_panstarrs_dr2_demo_ngs_bright.csv
data/public/eso_asm_paranal_20240729_0300_0800_snapshot.json
data/public/eso_asm_paranal_20240729_0300_0800_timeseries.csv
```

They come from the SVO Filter Profile Service, the IRSA 2MASS All-Sky Point Source Catalog, the MAST Pan-STARRS DR2 mean catalog, and the ESO Paranal ASM API. The ASM default is now the 2024-07-29 03:00-08:00 UTC nighttime window, approximately 23:00-04:00 CLT for Chile winter. These files are labelled `direct_public_data` and can be refreshed with:

```bash
python3 scripts/fetch_public_reference_data.py
```

The visualization entry point is:

```bash
python3 examples/run_public_data_overview.py
```

It writes `figures/detector_level_SCAO/public_data_overview.png`, `figures/detector_level_SCAO/public_filter_curves_jhk.png`, `figures/detector_level_SCAO/public_data_photon_budget.png`, and companion CSV summaries.

The public-data-informed AO scan is:

```bash
python3 examples/run_public_data_informed_ao_demo.py
```

It writes `figures/detector_level_SCAO/public_data_informed_ao_photon_scan.png`, `figures/detector_level_SCAO/public_data_informed_error_budget.png`, validation plots, runtime records, and companion CSV files.
This example uses the ESO ASM median seeing as a phase-amplitude scaling anchor
and the Pan-STARRS 700 nm photon-budget estimate as one WFS flux point. It
still records the AO loop, detector, DM, and error-channel model as synthetic
fast-mode proxies rather than measured telemetry.

The fallback fixtures remain deliberately labelled as `synthetic_assumed` or `synthetic_literature_inspired` unless they are actually downloaded public data. Gaia should only be described as used after a query/cache file exists with direct provenance; Pan-STARRS DR2 is the current optical-photometry substitute. ERA5/CDS access requires user credentials.

Validation summary:

```text
All data loaders return objects with units and `source_class`; no notebook-only parsing is required.
```
