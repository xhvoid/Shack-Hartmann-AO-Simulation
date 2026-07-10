<!-- Integration note for the fast end-to-end run, reference-metrics JSON contract, notebook-11 artifacts, and rerun modes. -->

# Integration, documentation, and presentation

The integration module provides a reproducible fast end-to-end run for notebook `11_full_detector_level_2m_scao_demo.ipynb`.

The notebook-11 story is intentionally separate from notebook 09:

* Notebook 09: clean 10 m-class high-order actuator-space control and NIR PSF diagnostics.
* Notebook 10: compact noise, latency, and gain-stability trade studies around the clean controller.
* Notebook 11: 2 m detector-level SCAO demonstrator using the detector SH-WFS, synthetic DM, detector-level interaction matrix, closed-loop controller, science metrics, error-budget scenarios, and validation checks.

Notebook 11 is not calibrated observatory telemetry. Its value is that the full modelling chain is inspectable, unit-tested, provenance-tagged, and runnable without internet in fast mode.

The strongest control-engineering figure in the current notebook-10/11 story is the gain-delay stability map: it shows that closed-loop performance is a controller operating-region problem, not just an open-loop versus closed-loop before/after comparison. The chosen operating point should be described as a compromise between residual OPD, latency tolerance, command growth, and stability margin.

## Automated fast run

The automated fast run completes without internet access. It may consume small tracked public reference caches in `data/public/`, but it does not require a live archive query during tests. The command is:

```bash
python3 examples/run_fast_integration.py
```

The run writes:

```text
figures/detector_level_SCAO/fast_error_budget.csv
figures/detector_level_SCAO/fast_error_budget.png
figures/detector_level_SCAO/fast_validation.csv
figures/detector_level_SCAO/fast_validation.png
data/reference_metrics/fast_reference_metrics.json
```

The test suite also executes notebook 11 top-to-bottom in fast mode with temporary output paths.

## Reference metrics

The run writes a compact JSON reference payload with the following fields:

```text
open_rms_nm
closed_rms_nm
h_strehl
valid_centroid_fraction
kept_modes
runtime_band
```

The JSON also stores scenario count, validation pass count, config hash, provenance, and tolerance bands for future regression checks.

## Rerun modes

The integration API exposes three presets:

```python
from ao_integration import IntegrationConfig, run_integration

fast = IntegrationConfig.from_mode("fast")
portfolio = IntegrationConfig.from_mode("portfolio")
research = IntegrationConfig.from_mode("research")

run_integration(fast)
```

Only `fast` is part of the automated integration check. `portfolio` and `research` increase pupil/WFS/DM sampling and loop length for local figure-quality experiments.

## Public-data-informed local scan

The public-data-informed local scan is intentionally outside the lightweight CI check:

```bash
python3 examples/run_public_data_informed_ao_demo.py
```

It uses the tracked ESO ASM median seeing snapshot to scale the synthetic phase
amplitude and the Pan-STARRS DR2 700 nm photon-budget estimate as the lowest
WFS flux case. It writes:

```text
figures/detector_level_SCAO/public_data_informed_ao_photon_scan.csv
figures/detector_level_SCAO/public_data_informed_ao_photon_scan.png
figures/detector_level_SCAO/public_data_informed_conditions.csv
figures/detector_level_SCAO/public_data_informed_error_budget.csv
figures/detector_level_SCAO/public_data_informed_error_budget.png
figures/detector_level_SCAO/public_data_informed_runtime.csv
figures/detector_level_SCAO/public_data_informed_runtime.json
figures/detector_level_SCAO/public_data_informed_validation.csv
figures/detector_level_SCAO/public_data_informed_validation.png
```

This scan is useful for presentation because it connects real public atmosphere
and catalog caches to controller-stress figures. The five public-data-informed
conditions are `nominal_synthetic`, `paranal_night_asm`, `poor_seeing`,
`faint_ngs`, and `stress_all_effects`. Modes such as fast, portfolio, and
research control numerical scale only; the condition matrix controls seeing,
photon budget, read noise, latency, stroke, NCPA, and misregistration proxies.

It is still not a calibrated observatory prediction: the DM, detector response,
loop dynamics, stroke limit, NCPA, and error channels remain synthetic fast-mode
proxies.

Because this local demo is intentionally heavier than the CI check, it records
its own runtime in `public_data_informed_runtime.csv` and `.json`. The
documented limit is 30 minutes; the validation table includes a
`runtime_under_30m` check.

## Caveats

Detector, DM, control, and most effect parameters remain synthetic or literature-inspired placeholders unless their source class says otherwise. Small public reference caches now exist for the SVO 2MASS J/H/Ks filter curves, IRSA 2MASS PSC photometry, MAST Pan-STARRS DR2 optical photometry, and ESO Paranal ASM nighttime atmosphere snapshot/time-series data. The pipeline is suitable for engineering sanity checks and portfolio demonstration, not for quoting performance of a specific telescope, guide star, or AO real-time controller.

The compact detector-level interaction-matrix poke matrix is well conditioned in fast mode and should be described as a response sanity check rather than a high-order reconstructor-conditioning result. Likewise, the high Strehl values in science/integration belong to a reduced 2 m demonstrator. EE50/EE80 are secondary PSF diagnostics because the fast PSF sampling can quantize encircled-energy radii.

The photon-flux residual curve in notebook 10 should not be interpreted as a monotonic AO performance law. In the current configuration the residual OPD is dominated by latency, model dynamics, and the simplified DM/WFS geometry; photon-count monotonicity is more cleanly demonstrated by the centroid-RMS scan.
