<!-- Error-budget note for scenario-level OPD RMS, J/H/K Strehl, EE50/EE80, command statistics, saturation fraction, and valid-centroid fraction. -->

# Error-Budget Notes

The error-budget layer adds `src/ao_error_budget.py`, which joins the detector-level control loop and science PSF diagnostics into a single scenario table.

The shared result object is `ScenarioResult`. Its required fields are:

```text
scenario_name
enabled_effects
open_rms_nm
closed_rms_nm
strehl_J / strehl_H / strehl_K
ee50_J / ee50_H / ee50_K
source_class
```

Additional fields include EE80, command RMS, command peak, saturated-actuator fraction, valid-centroid fraction, open-loop H Strehl, closed/open RMS ratio, source note, and config hash.

For presentation, the primary error-budget quantities are residual OPD RMS, H-band Strehl, command RMS/peak command, saturated-actuator fraction, and valid-centroid fraction. EE50/EE80 remain in the table for PSF context, but they should not be over-weighted because the fast PSF grid can make encircled-energy values quantized.

The default error-budget matrix has exactly eight rows:

```text
ideal_static
dynamic_multilayer_proxy
detector_noise
latency
stroke_limit
misregistration
ncpa
all_effects
```

The fast default uses a synthetic multi-component dynamic phase sequence in the controlled DM subspace. This keeps the test/runtime small while exercising the same data path as notebook 11: detector measurement, TSVD reconstruction, integrator control, residual OPD, and J/H/K science metrics.

The scenario-level `source_class` remains `synthetic_assumed` because the detector, DM, control, and effect rows are still simulation proxies. Bandpass provenance is handled separately by the module science-metric layer; when the public caches are present, J/H/Ks metrics use the tracked SVO direct public filter curves in `data/public/`.

Several effects are explicitly synthetic proxies:

```text
multi_component_dynamic_phase  fast multi-layer-style temporal proxy
wfs_dm_misregistration_proxy   affine transform of the science-path DM correction (sub-pixel shift, rotation, magnification, shear)
science_path_ncpa              static OPD map added after WFS correction
dm_stroke_limit                lower scenario-specific command stroke limit
```

Validation summary:

```text
All eight scenarios produce finite metrics and populate the error-budget table.
```

The command-line diagnostic is:

```bash
python3 examples/run_error_budget_demo.py
```

It writes:

```text
figures/detector_level_SCAO/error_budget_scenarios.csv
figures/detector_level_SCAO/error_budget_scenarios.png
```

The table is an observatory-style error-budget demonstrator for a compact 2 m SCAO system. It is not a calibrated performance prediction, not an ELT-scale claim, and does not use private AO telemetry.
