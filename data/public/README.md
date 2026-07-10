# Public Reference Data Caches

Small public-data products in this directory are tracked so the detector-level
AO extension can run offline while still carrying direct provenance.

## Tracked Direct Public Data

| File | Source | Query/use |
| --- | --- | --- |
| `svo_2mass_j_direct.csv` | SVO Filter Profile Service, `2MASS/2MASS.J` | Direct J-band transmission curve for science PSF metrics. |
| `svo_2mass_h_direct.csv` | SVO Filter Profile Service, `2MASS/2MASS.H` | Direct H-band transmission curve for science PSF metrics. |
| `svo_2mass_ks_direct.csv` | SVO Filter Profile Service, `2MASS/2MASS.Ks` | Direct Ks-band transmission curve for science PSF metrics. |
| `target_photometry_2mass_psc_demo_ngs_bright.csv` | IRSA 2MASS All-Sky Point Source Catalog, `fp_psc` | Cone query within 60 arcsec of the demo guide-star field. |
| `target_photometry_panstarrs_dr2_demo_ngs_bright.csv` | MAST Pan-STARRS DR2 mean catalog | Optical `g/r/i/z/y` cone-query photometry for WFS photon-budget anchoring. |
| `eso_asm_paranal_20240729_0300_0800_snapshot.json` | ESO Paranal ASM API | Nighttime median seeing, r0, tau0, theta0, and turbulence-speed snapshot. |
| `eso_asm_paranal_20240729_0300_0800_timeseries.csv` | ESO Paranal ASM API | 184-sample nighttime seeing/tau0/theta0/turbulence-speed time series for public-data overview plots. |

Refresh these files with:

```bash
python scripts/fetch_public_reference_data.py
```

## Historical Caches

The `0900_1000` ESO ASM files are retained only as historical outputs from an
earlier one-hour data-interface pass. Notebook 11 public-data-informed runs use
the `0300_0800` nighttime window by default.

## Not Claimed As Used Yet

| Source | Status |
| --- | --- |
| Gaia Archive / Gaia DR3 | Intended optional source for optical guide-star astrometry/photometry. The ESA Gaia Archive was inaccessible from this environment; Pan-STARRS DR2 is used as the current optical-photometry public-data substitute. |
| ERA5 / CDS | Not used. ESO ASM already supplies seeing/tau0/theta0/turbulence-speed conditioning for the public-data demonstrator, and ERA5 would require user CDS API credentials plus a separate meteorological downselection. |
