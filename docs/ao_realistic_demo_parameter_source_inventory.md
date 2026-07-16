# AO detector-level extension parameter-source inventory

Prepared: 2026-07-10 22:24

Scope: tracked public caches, derived calculations, synthetic model parameters, and derived result artifacts used by the detector-level AO extension. Direct public data are separated from synthetic AO proxies.

## Direct public data caches used

| item | file | fields | exact_values | source_class | source | identifier |
| --- | --- | --- | --- | --- | --- | --- |
| SVO 2MASS J filter | data/public/svo_2mass_j_direct.csv | wavelength_m, transmission | 107 samples; wavelength range 1.062e-06-1.450e-06 m; effective wavelength 1.241052 micron | direct_public_data | SVO Filter Profile Service direct download for 2MASS/2MASS.J; profile reference http://www.ipac.caltech.edu/2mass/releases/allsky/doc/sec6_4a.html#rsr; 2MASS canonical paper DOI 10.1086/498708. | https://svo2.cab.inta-csic.es/theory/fps/fps.php?ID=2MASS%2F2MASS.J |
| SVO 2MASS H filter | data/public/svo_2mass_h_direct.csv | wavelength_m, transmission | 58 samples; wavelength range 1.289e-06-1.914e-06 m; effective wavelength 1.651366 micron | direct_public_data | SVO Filter Profile Service direct download for 2MASS/2MASS.H; profile reference http://www.ipac.caltech.edu/2mass/releases/allsky/doc/sec6_4a.html#rsr; 2MASS canonical paper DOI 10.1086/498708. | https://svo2.cab.inta-csic.es/theory/fps/fps.php?ID=2MASS%2F2MASS.H |
| SVO 2MASS Ks filter | data/public/svo_2mass_ks_direct.csv | wavelength_m, transmission | 76 samples; wavelength range 1.900e-06-2.399e-06 m; effective wavelength 2.165631 micron | direct_public_data | SVO Filter Profile Service direct download for 2MASS/2MASS.Ks; profile reference http://www.ipac.caltech.edu/2mass/releases/allsky/doc/sec6_4a.html#rsr; 2MASS canonical paper DOI 10.1086/498708. | https://svo2.cab.inta-csic.es/theory/fps/fps.php?ID=2MASS%2F2MASS.Ks |
| IRSA 2MASS PSC photometry | data/public/target_photometry_2mass_psc_demo_ngs_bright.csv | target_id, ra_deg, dec_deg, J/H/Ks, distance, ph_qual | 6 rows; nearest 2MASS_05343359-0523099 J/H/Ks=11.282/10.782/10.719 mag; ph_qual=AAA | direct_public_data | IRSA 2MASS All-Sky Point Source Catalog PSC fp_psc cone query; 2MASS canonical paper DOI 10.1086/498708. | https://irsa.ipac.caltech.edu/cgi-bin/Gator/nph-query?catalog=fp_psc&spatial=cone&radius=60&radunits=arcsec&objstr=83.6331+-5.3911&outfmt=1 |
| MAST Pan-STARRS DR2 photometry | data/public/target_photometry_panstarrs_dr2_demo_ngs_bright.csv | target_id, ra_deg, dec_deg, nDetections, g/r/i/z/y | 19 usable rows; photon anchor PS1_101500836297539800 m700=18.871053 mag; photons=0.010434989 per subap/frame | direct_public_data | MAST Pan-STARRS DR2 mean catalog cone query; Pan-STARRS1 Surveys arXiv:1612.05560 and database/data-products arXiv:1612.05243. | https://catalogs.mast.stsci.edu/api/v0.1/panstarrs/dr2/mean.csv?ra=83.6331&dec=-5.3911&radius=0.02&nDetections.gte=1&pagesize=20&columns=%5BobjID%2CobjName%2CraMean%2CdecMean%2CnDetections%2CgMeanPSFMag%2CrMeanPSFMag%2CiMeanPSFMag%2CzMeanPSFMag%2CyMeanPSFMag%2CgMeanPSFMagErr%2CrMeanPSFMagErr%2CiMeanPSFMagErr%2CzMeanPSFMagErr%2CyMeanPSFMagErr%5D |
| ESO Paranal ASM nighttime snapshot | data/public/eso_asm_paranal_20240729_0300_0800_snapshot.json | seeing, r0_500, tau0, theta0, turbulence speed | UTC 2024-07-29T03:00:00Z to 2024-07-29T08:00:00Z; approximately 23:00-04:00 CLT for Chile winter; seeing=0.7235 arcsec; r0_500=0.139695715 m; tau0=0.003409 s; theta0=1.894 arcsec; turbulence_speed=10.84 m/s; samples=184 | direct_public_data | ESO Paranal ASM API direct JSON query over 2024-07-29T03:00:00Z to 2024-07-29T08:00:00Z; fields dimm_paranal-fwhm,mass_paranal-tau0,mass_paranal-tet0,mass_paranal-turb_speed. r0_500_m is derived from median seeing using Fried DOI 10.1364/JOSA.56.001372. | https://www.eso.org/asm/api/?from=2024-07-29T03%3A00%3A00Z&to=2024-07-29T08%3A00%3A00Z&fields=dimm_paranal-fwhm%2Cmass_paranal-tau0%2Cmass_paranal-tet0%2Cmass_paranal-turb_speed |
| ESO Paranal ASM nighttime time series | data/public/eso_asm_paranal_20240729_0300_0800_timeseries.csv | unix_time_ms, seeing, tau0, theta0, turbulence speed | 161 samples over 2024-07-29T03:00:00Z to 2024-07-29T08:00:00Z | direct_public_data | ESO Paranal ASM API direct JSON query over 2024-07-29T03:00:00Z to 2024-07-29T08:00:00Z; fields dimm_paranal-fwhm,mass_paranal-tau0,mass_paranal-tet0,mass_paranal-turb_speed. | https://www.eso.org/asm/api/?from=2024-07-29T03%3A00%3A00Z&to=2024-07-29T08%3A00%3A00Z&fields=dimm_paranal-fwhm%2Cmass_paranal-tau0%2Cmass_paranal-tet0%2Cmass_paranal-turb_speed |

## Derived calculations from public data

| calculation | formula_or_assumption | input | output | source |
| --- | --- | --- | --- | --- |
| Fried r0 conversion | r0_500_m = 0.98 * 500e-9 / seeing_rad | ESO ASM median DIMM seeing at 500 nm | 0.139695715 m | Fried parameter; DOI 10.1364/JOSA.56.001372 |
| SVO J/H/Ks effective wavelengths | lambda_eff = integral(lambda*T dlambda) / integral(T dlambda) | SVO 2MASS/2MASS.J, H, Ks transmission samples | J=1.241052 micron; H=1.651366 micron; Ks=2.165631 micron | SVO FPS direct caches; 2MASS canonical paper DOI 10.1086/498708 |
| Pan-STARRS 700 nm WFS photon estimate | AB fnu=3631 Jy*10^(-0.4*m); bandwidth=150 nm; D=2 m; throughput=0.25; exposure=1 ms; n_subap=25 | PS1_101500836297539800 m700=18.871053 | 0.010434989 photons/subap/frame | MAST Pan-STARRS DR2 cache; AB magnitude convention from Oke & Gunn DOI 10.1086/113325; engineering estimate, not WFS telemetry |
| Public-data-informed phase amplitude | phase_amplitude_nm = 260 nm * seeing_arcsec / 0.80 arcsec | ESO ASM seeing=0.7235 arcsec | 235.1375 nm for paranal_night_asm | Synthetic scaling anchored to ESO ASM; not a measured wavefront sequence |
| Science Strehl metric | Marechal proxy Strehl = exp(-(2*pi*OPD_rms/lambda)^2) | Synthetic residual OPD RMS and direct SVO J/H/Ks effective wavelengths | J/H/Ks Strehl columns in the science, error-budget, fast-integration, and public-data-informed result CSVs | Analytical AO diagnostic formula; no on-sky PSF calibration is used |

## Notebook 11 observing/error conditions

| condition | atmosphere | seeing_r0 | photons_noise | latency | stroke_ncpa | misregistration | source |
| --- | --- | --- | --- | --- | --- | --- | --- |
| nominal_synthetic | synthetic nominal seeing proxy | 0.8 arcsec; r0=0.126337 m | 8000 photons/subap/frame; read=1 e- | 1 frames; total=0 s | stroke=1000 nm; NCPA=15 nm | shift=(0, 0) px; rot=0 deg; mag=1; shear=0 | Notebook 11 nominal synthetic condition for regression comparison. |
| paranal_night_asm | ESO ASM nighttime direct_public_data cache | 0.7235 arcsec; r0=0.139696 m | 200 photons/subap/frame; read=1 e- | 1 frames; total=0.001 s | stroke=500 nm; NCPA=25 nm | shift=(0, 0) px; rot=0 deg; mag=1; shear=0 | Notebook 11 public-data-informed synthetic AO condition: atmosphere and/or catalog photometry may come from public caches, while DM, detector, latency, NCPA, registration, and RTC behaviour remain synthetic engineering proxies. |
| poor_seeing | ESO ASM nighttime scaled engineering poor-seeing proxy | 1.15 arcsec; r0=0.087887 m | 200 photons/subap/frame; read=1.5 e- | 2 frames; total=0.002 s | stroke=220 nm; NCPA=35 nm | shift=(0.4, 0) px; rot=0.15 deg; mag=1; shear=0 | Notebook 11 public-data-informed synthetic AO condition: atmosphere and/or catalog photometry may come from public caches, while DM, detector, latency, NCPA, registration, and RTC behaviour remain synthetic engineering proxies. |
| faint_ngs | ESO ASM nighttime direct_public_data cache | 0.7235 arcsec; r0=0.139696 m | 0.010435 photons/subap/frame; read=3 e- | 2 frames; total=0.002 s | stroke=180 nm; NCPA=45 nm | shift=(0.5, 0) px; rot=0.2 deg; mag=1; shear=0 | Notebook 11 public-data-informed synthetic AO condition: atmosphere and/or catalog photometry may come from public caches, while DM, detector, latency, NCPA, registration, and RTC behaviour remain synthetic engineering proxies. |
| stress_all_effects | ESO ASM nighttime scaled engineering stress proxy | 1.25 arcsec; r0=0.080856 m | 0.010435 photons/subap/frame; read=5 e- | 3 frames; total=0.003 s | stroke=120 nm; NCPA=70 nm | shift=(0.8, 0.3) px; rot=0.3 deg; mag=1.01; shear=0.005 | Notebook 11 public-data-informed synthetic AO condition: atmosphere and/or catalog photometry may come from public caches, while DM, detector, latency, NCPA, registration, and RTC behaviour remain synthetic engineering proxies. |

## Synthetic and mixed model parameters actually used

| subsystem | parameters | source_class | source |
| --- | --- | --- | --- |
| Mode presets | fast: 52 pupil px, 5 lenslets, 5 actuators across, 12 steps, 8000 photons; portfolio: 72 px, 7 lenslets, 7 actuators, 18 steps, 7000 photons; research: 96 px, 9 lenslets, 9 actuators, 30 steps, 6000 photons | synthetic_assumed | IntegrationConfig presets; modes control numerical scale only |
| Fast detector-level SCAO geometry | D=2.0 m; detector_window_px=18; pad_factor=3; WFS wavelength=700 nm; frame_rate=1000 Hz | synthetic_assumed | IntegrationConfig fast preset and ShwfsGeometryConfig |
| Detector/WFS noise parameters | Condition matrix controls photons, read_noise_e, latency, stroke, NCPA, and registration stress; DetectorConfig also supports dark current, background, full-well clipping, bad-pixel masks, PRNU, exposure time, and QE | synthetic_assumed plus direct_public_data conditioning | figures/detector_level_SCAO/public_data_informed_conditions.csv; tests/test_detector_centroids.py |
| DM model | Gaussian influence functions; fast n_actuators_across=5; coupling_width_pitch=0.40; nominal stroke_limit_nm=1000 | synthetic_literature_inspired | DM influence-function modelling motivated by arXiv:2306.10803; not measured DM calibration |
| Interaction matrix / reconstructor | Central-difference poke amplitude=10 nm; rcond scan grid=1e-8,1e-6,1e-4,1e-3; fast-integration kept_modes=13 | synthetic_assumed | Self-calibrated detector-level poke matrix; no observatory control matrix is used |
| compact poke-matrix diagnostic | Command-line diagnostic matrix shape=90x16, rank=16, kept_modes=16, selected rcond=3e-3 | synthetic_assumed | figures/detector_level_SCAO/poke_matrix_singular_values.csv; compact detector-level sanity check, not high-order observatory reconstructor conditioning |
| Science bandpasses | J/H/Ks use SVO 2MASS direct caches when present; top-hat fallback only if a cache is missing | direct_public_data with documented fallback path | data/public/svo_2mass_j_direct.csv, h_direct.csv, ks_direct.csv |
| fast reference run | open_rms=77.164249 nm; closed_rms=59.442573 nm; H Strehl=0.950455; kept_modes=13; validation=6/6 | synthetic_assumed | Fast end-to-end detector-level 2 m SCAO integration using local synthetic/literature-inspired fixtures; not calibrated observatory AO telemetry. |

## Public-data-informed photon scan results

| case | photons | closed_rms_nm | h_strehl | command_rms_nm | saturated_frac | provenance |
| --- | --- | --- | --- | --- | --- | --- |
| Pan-STARRS direct estimate | 0.010435 | 66.957866 | 0.936836 | 0 | 0 | photon=direct_public_data; loop=synthetic_assumed |
| engineering 50 photons | 50 | 66.957866 | 0.936836 | 0 | 0 | photon=synthetic_assumed; loop=synthetic_assumed |
| engineering 200 photons | 200 | 61.081576 | 0.946655 | 306.124599 | 0.269231 | photon=synthetic_assumed; loop=synthetic_assumed |
| Nominal 8000 photons | 8000 | 46.839682 | 0.968439 | 266.914033 | 0.230769 | photon=synthetic_assumed; loop=synthetic_assumed |

## Public-data-informed scenario results

| condition | enabled_effects | closed_rms_nm | h_strehl | valid_centroid_frac | command_rms_nm | saturated_frac | decomposition |
| --- | --- | --- | --- | --- | --- | --- | --- |
| nominal_synthetic | synthetic_conditioned_phase_sequence+detector_noise+latency_1_frames+science_path_ncpa | 17.852795 | 0.995355 | 1 | 311.985165 | 0 | WFS/science no-NCPA proxy=9.681028 nm; plus NCPA=17.852795 nm |
| paranal_night_asm | eso_asm_conditioned_synthetic_phase_sequence+detector_noise+latency_1_frames+dm_stroke_limit+science_path_ncpa | 62.300993 | 0.944969 | 1 | 505.232264 | 0 | WFS/science no-NCPA proxy=57.064995 nm; plus NCPA=62.300993 nm |
| poor_seeing | eso_asm_conditioned_synthetic_phase_sequence+detector_noise+latency_2_frames+dm_stroke_limit+wfs_dm_misregistration_proxy+science_path_ncpa | 80.145051 | 0.910386 | 1 | 465.641814 | 0.230769 | WFS/science no-NCPA proxy=72.098747 nm; plus NCPA=80.145051 nm |
| faint_ngs | eso_asm_conditioned_synthetic_phase_sequence+detector_noise+latency_2_frames+dm_stroke_limit+wfs_dm_misregistration_proxy+science_path_ncpa | 58.835806 | 0.951147 | 0 | 0 | 0 | WFS/science no-NCPA proxy=37.903193 nm; plus NCPA=58.835806 nm |
| stress_all_effects | eso_asm_conditioned_synthetic_phase_sequence+detector_noise+latency_3_frames+dm_stroke_limit+wfs_dm_misregistration_proxy+science_path_ncpa | 80.718824 | 0.909827 | 0 | 0 | 0 | WFS/science no-NCPA proxy=40.193638 nm; plus NCPA=80.718824 nm |

## H-band science metrics

| case | opd_rms_nm | h_strehl | source_class |
| --- | --- | --- | --- |
| open_loop | 130.503151 | 0.780246 | synthetic_assumed |
| ideal_closed_loop | 0 | 1 | synthetic_assumed |
| realistic_closed_loop | 28.710693 | 0.988031 | synthetic_assumed |

## Error-budget scenario results

| scenario | closed_rms_nm | h_strehl | command_rms_nm | saturated_frac | source_class |
| --- | --- | --- | --- | --- | --- |
| ideal_static | 1.030423 | 0.999984 | 424.020749 | 0 | synthetic_assumed |
| dynamic_multilayer_proxy | 6.852974 | 0.99931 | 288.294915 | 0 | synthetic_assumed |
| detector_noise | 6.993077 | 0.999283 | 288.830061 | 0 | synthetic_assumed |
| latency | 27.155442 | 0.989286 | 415.676117 | 0 | synthetic_assumed |
| stroke_limit | 10.152356 | 0.99848 | 235.960176 | 0.192308 | synthetic_assumed |
| misregistration | 8.512633 | 0.998943 | 287.370111 | 0 | synthetic_assumed |
| ncpa | 44.721191 | 0.971193 | 288.507063 | 0 | synthetic_assumed |
| all_effects | 48.348567 | 0.96641 | 273.193914 | 0.230769 | synthetic_assumed |

## Long-run runtime records

| script | started_utc | finished_utc | runtime_minutes | limit_minutes | within_limit | source |
| --- | --- | --- | --- | --- | --- | --- |
| examples/run_public_data_informed_ao_demo.py | 2026-07-09T20:25:56Z | 2026-07-09T20:33:23Z | 7.454244 | 30 | True | Local wall-clock runtime for the public-data-informed Notebook 11 demo. The run uses tracked public caches and synthetic AO proxies; no live archive query is performed. |

**Validation scope note:** the public-data-informed checks below confirm public-data provenance, finite metrics, cache presence, and runtime. They are not an adaptive-optics performance validation. A faint scenario with `valid_centroid_frac = 0` has no usable WFS centroids, so its loop is frozen (closed RMS approaches open-loop) yet still passes these provenance/finite checks.

## Public-data-informed validation checks

| check | passed | metric | tolerance | source_class | message |
| --- | --- | --- | --- | --- | --- |
| nighttime_eso_asm_condition_present | True | 4 | 1 | direct_public_data | At least one public-data-informed condition uses the nighttime ESO ASM cache. |
| catalog_photon_condition_present | True | 2 | 1 | direct_public_data | At least one condition uses catalog-derived Pan-STARRS photon-budget input. |
| scenario_metrics_finite | True | 1 | 1 | synthetic_assumed | Public-data-informed scenario metrics are finite. |
| internal_ao_terms_not_direct_public | True | 1 | 1 | synthetic_assumed | Scenario rows do not claim synthetic AO internals as direct public data. |
| jhk_svo_direct_caches_expected | True | 1 | 1 | direct_public_data | J/H/K science metrics are configured to prefer SVO direct caches. |
| runtime_under_30m | True | 7.454244 | 30 | package_reference | Public-data-informed AO demo runtime stays below the documented 30 minute local-run limit. |

## Selected visual/result artifacts

| artifact | contents | basis |
| --- | --- | --- |
| figures/detector_level_SCAO/public_data_overview.png | ESO ASM nighttime time series, SVO J/H/Ks filters, catalog field map, optical/NIR photometry anchors | direct public caches |
| figures/detector_level_SCAO/public_filter_curves_jhk.png | Direct SVO 2MASS J/H/Ks filter curves | direct public SVO caches |
| figures/detector_level_SCAO/public_data_photon_budget.png | Pan-STARRS 700 nm WFS photon-budget estimate | Pan-STARRS direct data + explicit engineering assumptions |
| figures/detector_level_SCAO/public_data_informed_ao_photon_scan.png | AO residual/Strehl/stroke scan conditioned on ESO ASM + Pan-STARRS | direct public conditioning + synthetic loop |
| figures/detector_level_SCAO/poke_matrix_singular_values.png | Compact detector-level DM/WFS poke-matrix singular spectrum | synthetic detector-level calibration sanity check |
| figures/detector_level_SCAO/public_data_informed_error_budget.png | Five-condition public-data-informed AO scenario map | direct public conditioning + synthetic AO proxies |
| figures/detector_level_SCAO/public_data_informed_runtime.csv | Local runtime record for the slower public-data-informed demo | package runtime metadata |
| figures/detector_level_SCAO/public_data_informed_runtime.json | JSON copy of the public-data-informed demo runtime record | package runtime metadata |
| figures/detector_level_SCAO/public_data_informed_validation.png | Public-data-informed provenance and metric validation checks | public-data and synthetic-boundary checks |
| figures/detector_level_SCAO/science_psf_metrics.png | J/H/Ks PSF metrics | SVO J/H/Ks direct caches |
| figures/detector_level_SCAO/error_budget_scenarios.png | 8-row error-budget scenario comparison | synthetic AO scenarios with SVO J/H/Ks science metrics |
| figures/detector_level_SCAO/fast_error_budget.png | fast all-scenario integration summary | synthetic fast model with SVO J/H/Ks bandpasses |
| figures/detector_level_SCAO/fast_validation.png | Marechal, diffraction, photon, latency, fitting, reproducibility checks | synthetic validation scans |

## Sources explicitly not claimed as used

| source | identifier | status |
| --- | --- | --- |
| Gaia Archive / Gaia DR3 | https://gea.esac.esa.int/archive/ ; Gaia DR3 DOI 10.1051/0004-6361/202243940 | Not used in this run. Archive access failed from this environment; Pan-STARRS DR2 is the optical-photometry substitute. |
| ERA5 pressure/single levels | DOI 10.24381/cds.bd0915c6 and DOI 10.24381/cds.adbb2d47 | Not used. ESO ASM supplies direct seeing/tau0/theta0/turbulence-speed conditioning for this demonstrator; CDS credentials would be required for ERA5. |
| ESO Science Archive / Keck / Gemini / EIDC images | ESO archive URL, KOA, Gemini API, EIDC arXiv:2101.05080 and arXiv:2410.17636 | Not used for current simulated-loop results. No on-sky PSF validation is claimed. |
| Observatory telemetry, DM influence matrices, RTC logs | No public file in repository | Not used. Detector, DM, latency, NCPA, registration, and control terms are synthetic engineering proxies. |

## Source index

| id | source | identifier | use |
| --- | --- | --- | --- |
| ESO ASM | ESO Paranal ASM API and ambient query forms | https://www.eso.org/asm/api/ | direct public atmosphere cache |
| SVO FPS | SVO Filter Profile Service | https://svo2.cab.inta-csic.es/theory/fps/ | direct public 2MASS J/H/Ks filter curves |
| 2MASS | IRSA 2MASS PSC | https://irsa.ipac.caltech.edu/Missions/2mass.html ; DOI 10.1086/498708 | direct public J/H/Ks catalog photometry and filter identity |
| Pan-STARRS | MAST Pan-STARRS DR2 mean catalog | arXiv:1612.05560 and arXiv:1612.05243 | direct public optical photometry substitute for Gaia |
| AB magnitude | AB photon-budget convention | Oke & Gunn DOI 10.1086/113325 | 700 nm WFS photon estimate from Pan-STARRS magnitudes |
| Fried r0 | Fried parameter conversion | DOI 10.1364/JOSA.56.001372 | r0 derived from ESO ASM seeing |
| DM influence | Gaussian synthetic DM influence functions | arXiv:2306.10803 | literature-inspired DM shape choice |
| Noll | Zernike/statistical aberration background | DOI 10.1364/JOSA.66.000207 | background reference for modal aberration vocabulary |
