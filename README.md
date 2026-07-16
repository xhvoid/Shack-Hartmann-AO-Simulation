# Shack-Hartmann Wavefront Sensing and Adaptive Optics Simulations

[![tests](https://github.com/xhvoid/Shack-Hartmann-AO-Simulation/actions/workflows/ci.yml/badge.svg)](https://github.com/xhvoid/Shack-Hartmann-AO-Simulation/actions/workflows/ci.yml)

This repository is a compact, inspectable simulation study of Shack-Hartmann wavefront sensing, wavefront reconstruction, simplified closed-loop adaptive optics, and PSF-based performance diagnostics.

Its scientific objective is to make the numerical chain from pupil-plane phase errors to WFS measurements, reconstruction, correction, residual wavefronts, and science-wavelength PSFs transparent. It is a portfolio simulation project, not a calibrated observatory simulator or an operational AO pipeline:

```text
pupil-plane phase error
→ wavefront-sensor measurement
→ response / interaction matrix
→ regularized reconstruction
→ deformable-mirror or modal correction
→ residual wavefront
→ PSF, Strehl, FWHM, and encircled-energy diagnostics
```

## Project scope

The repository focuses on five connected parts of an AO simulation chain:

* SH-WFS measurement: geometric slopes and detector-level lenslet spot centroiding.
* Reconstruction: modal response matrices, singular-value diagnostics, and TSVD regularization.
* Closed-loop correction: typed command projection, applied-command-aware leaky integration, frame-exact latency, fixed telemetry, and replay-safe gain/delay tests.
* Science diagnostics: residual OPD RMS, Strehl ratio, FWHM, EE50/EE80, and J/H/K PSF comparisons.
* Extensions: simplified PWFS forward modelling, compact noise / latency / gain-stability scans, a fast 2 m detector-level SCAO integration run, and a public-data-informed upgrade of that 2 m demonstrator (ESO ASM / SVO / Pan-STARRS caches with explicit provenance).

Notebook 09 is the closest one to a clean 10 m-class high-order control calculation. It moves from low-order modal correction to a high-order actuator-space SH-AO demonstration with 48 × 48 WFS sampling, a 49 × 49 nominal actuator grid, TSVD command reconstruction, and J/H/K PSF diagnostics. Notebook 10 then asks a more engineering-style question: what happens when measurement noise, loop delay, and gain tuning are no longer ignored?

Notebook 11 is a separate 2 m detector-level SCAO demonstrator. It ties together the detector SH-WFS, synthetic DM, detector-level interaction matrix, closed-loop controller, science PSF metrics, error-budget scenarios, and validation checks into one fast rerunnable path.

## Quick start

The project requires Python 3.10 or newer. From the repository root:

```bash
python3 -m pip install -e ".[test]"
python3 -c "import shwfs_ao; print(shwfs_ao.__version__)"
pytest -q
python3 examples/run_fast_integration.py
```

This installs the core package and test dependency, runs the numerical test suite, and executes the lightweight detector-level SCAO integration example. See [Installation](#installation) for notebook and documentation extras.

## Quick review path

For a short technical review, start with:

1. `06_detector_level_shwfs.ipynb` — detector-level SH-WFS centroiding and response calibration.
2. `09_ao_psf_instrument_performance_high_order_ao.ipynb` — high-order actuator-space SH-AO and NIR PSF diagnostics.
3. `10_noise_latency_gain_stability.ipynb` — noise, latency, and gain-stability trade-offs.
4. `11_full_detector_level_2m_scao_demo.ipynb` — fast 2 m detector-level SCAO integration, error-budget table, and validation checks.

The earlier notebooks document the build-up from low-order modal reconstruction to detector-level and closed-loop models.

## Data provenance: real, estimated, synthetic

This is a learning and portfolio project, not an observatory-grade AO simulator. The table below states what is direct public data, what is an engineering estimate, and what is a synthetic model, so the boundary is clear before any figure is read.

| Component | Status | Notes |
| --- | --- | --- |
| ESO ASM seeing snapshot | Direct public-data cache | Nighttime Paranal window; used to condition the synthetic phase amplitude. |
| SVO 2MASS J/H/Ks filters | Direct public-data cache | Used for science-band metric weighting where the caches are present. |
| Pan-STARRS / 2MASS catalog rows | Direct public-data cache | Used as photometric anchors only. |
| WFS photon budget | Engineering estimate | AB-magnitude conversion with explicit assumptions; not measured WFS telemetry. |
| Atmosphere phase sequence | Synthetic | Scaled or conditioned by scenario inputs; not a measured wavefront sequence. |
| DM influence functions | Synthetic | Gaussian / compact model, not a real DM calibration. |
| Interaction matrix | Synthetic detector-level calibration | Built from the repo's own WFS + DM model by central difference. |
| Closed-loop controller | Synthetic compact integrator | Gain, delay, leakage, stroke, and centroid-validity diagnostics. |
| Science PSF metrics | Diagnostic FFT / OPD model | Useful for trends, not calibrated instrument throughput. |
| Validation checks | Internal sanity checks | Reproducibility and physical-trend checks, not external observatory validation. |

Centroid validity is screened by flux, peak SNR, centroid-uncertainty, and window-clipping thresholds (not just a finite centroid), so faint sub-photon WFS budgets report low valid-centroid fractions rather than plausible-looking centroids built from noise. See the [provenance summary](#provenance-summary) and [validation and limitations](#validation-and-limitations) sections for detail.

## Representative results

The selected figures below illustrate the simulation outputs and diagnostic trends discussed in the notebooks. They are reproducible from the tracked configurations and examples described later in this README.

### Public data anchors for the detector-level extension

The detector-level extension now uses small tracked public-data caches for the atmosphere, science bandpasses, and catalog photometry: an ESO Paranal ASM nighttime window, SVO 2MASS J/H/Ks filter curves, IRSA 2MASS PSC, and MAST Pan-STARRS DR2.

![Public data overview](figures/detector_level_SCAO/public_data_overview.png)

The direct SVO J/H/Ks filter curves are used by the science-metric path when the caches are present. The older top-hat bands remain only as documented fallbacks.

![SVO JHK filter curves](figures/detector_level_SCAO/public_filter_curves_jhk.png)

The Pan-STARRS optical cache is also used for a simple 700 nm WFS photon-budget estimate. This is an engineering input estimate, not measured WFS telemetry.

![Public-data WFS photon budget](figures/detector_level_SCAO/public_data_photon_budget.png)

The slower public-data-informed AO demo then uses the ESO ASM seeing snapshot to scale the synthetic phase amplitude and the Pan-STARRS photon-budget anchor to stress the fast detector-level loop. The loop and DM model are still synthetic, but the conditioning data are real public caches.

![Public-data-informed AO photon scan](figures/detector_level_SCAO/public_data_informed_ao_photon_scan.png)

Notebook 11 also writes a five-condition public-data-informed scenario table. The conditions, not the numerical mode, control seeing, photon budget, read noise, latency, stroke, NCPA, and misregistration proxies.

![Public-data-informed AO scenarios](figures/detector_level_SCAO/public_data_informed_error_budget.png)

### High-order AO correction: NIR PSF sharpening

Notebook 09 compares three PSF cases: diffraction-limited, open-loop atmospheric, and AO-corrected.

![High-order AO NIR PSF performance](figures/high_order_ao_jhk_psf.png)

### Closed-loop residual OPD RMS

The high-order loop is run on a frozen-flow atmospheric sequence. I use the post-settling residual OPD RMS as the main wavefront-error diagnostic.

![High-order AO residual RMS history](figures/high_order_ao_rms_history.png)

### Wavefront correction maps

The wavefront maps show the open-loop atmospheric phase, the DM correction, and the final closed-loop residual. This illustrates that the controller reconstructs actuator commands rather than only fitting low-order Zernike modes.

![High-order AO phase maps](figures/high_order_ao_phase_maps.png)

### Noise, latency, and loop-gain trade-offs

Notebook 10 scans photon flux, read noise, loop gain, and frame delay. The gain-delay panel marks the chosen operating point and hatches cells where the loop becomes unstable or command-limited.

![Noise, latency, and gain stability](figures/noise_latency_gain_stability.png)

### Fast 2 m detector-level SCAO integration

Notebook 11 runs the smaller detector-level SCAO path end to end and writes a compact error-budget table, validation summary, figures, and reference metrics.

![Fast 2 m detector-level SCAO scenarios](figures/detector_level_SCAO/fast_error_budget.png)

### Simplified PWFS detector images

The PWFS branch is exploratory. It shows detector-plane pupil images and normalized slope-like signal maps, but it is not a validated PWFS control simulator.

![PWFS detector images](figures/PWFS_detector_images.png)

### Sampling density versus correction order

This diagnostic tracks how WFS sampling density and controlled modal order affect conditioning and correction quality.

![Sampling versus correction order](figures/sampling_vs_correction_order.png)

### Detector-level Shack-Hartmann reconstruction

The detector-level SH-WFS notebooks simulate lenslet spots, finite detector windows, noise, centroiding, reference subtraction, and response-matrix reconstruction.

![Detector-level reconstruction](figures/detector_level_reconstruction.png)

## Repository layout

```text
src/shwfs_ao/ namespaced AO implementation; shared core, detector, and native backend APIs
src/*.py      installed compatibility shims for the existing top-level imports
src/shwfs_ao/resources/  canonical packaged fixtures, schemas, and reference metrics
notebooks/    narrative simulations from SH-WFS basics to high-order AO
examples/     lightweight command-line demonstrations
tests/        numerical sanity checks for the core modules
configs/      documented synthetic and literature-inspired presets
data/         ignored raw-download and cache work areas used by maintenance scripts
figures/      selected outputs used in this README and generated examples
docs/         architecture, validation, and provenance documentation
scripts/      public-data refresh and report-generation utilities
constraints/  exact Python 3.10 and 3.14 CI/test dependency profiles
CITATION.cff  citation metadata
LICENSE       MIT license
DATA_LICENSES.md  third-party data terms and acknowledgement links
```

## Code architecture

The installed implementation is rooted at `shwfs_ao`. Shared unit-explicit result types, component protocols, immutable pupil geometry, canonical hashing, and named random streams live under `shwfs_ao.core`. The canonical Shack-Hartmann domain is exposed by `shwfs_ao.wfs.shack_hartmann`: it separates lenslet geometry, optical spot formation, deterministic detector reference calibration, detector-level measurement, and a detector-free geometric sensor. The repository-level deformable-mirror policy lives under `shwfs_ao.dm`, while transparent NumPy atmosphere, Shack-Hartmann diffraction, science-PSF propagation, DM spatial synthesis, and real Zernike modes live under `shwfs_ao.backends.native`. `shwfs_ao.calibration` owns modal/actuator probe bases, full-row interaction matrices, central/forward calibration, matrix diagnostics, and independent mask-aware least-squares, TSVD, and Tikhonov reconstructors with bounded factorization caches. `shwfs_ao.control` owns typed reconstruction-to-command mapping, applied-command-aware leaky integration, the sole frame-latency queue, backend-independent loop sequencing, fixed-length history, and replay-safe control sweeps. `shwfs_ao.science` owns immutable wavelength quadrature, the backend-independent residual-OPD propagation helper and sampling contract, physical angular-grid semantics, and scalar science metrics. Detector configuration and realized pixel maps, typed frame effects, centroid estimators, and validity policy live under `shwfs_ao.detector`; persistent PRNU is explicit, while existing profiles retain the seeded `per_frame_legacy` mode. The PWFS forward model has one installed experimental owner at `shwfs_ao.experimental.pwfs` and is not presented as a stable SCAO backend. Remaining numerical modules are staged one-for-one under `shwfs_ao.legacy` behind silent installed top-level shims. `shwfs_ao.legacy` is an internal compatibility namespace, not a public API for new code. [`docs/architecture.md`](docs/architecture.md) shows the component boundaries and full pipeline.

| Transitional public import | Main role                                                                                                                                                       |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `zernike`        | Pupil grids, Zernike modes, modal synthesis, piston removal, and RMS utilities.                    |
| `phase_screen`   | Atmospheric-like phase screens, seeing / `r0` scaling, OPD conversion, and frozen-flow shifts.     |
| `reconstruction` | Compatibility facade for geometric SH-WFS arrays, modal synthesis, and historical reconstruction result formats; inverse solves delegate to `shwfs_ao.calibration`. |
| `shwfs_ao.wfs.shack_hartmann` | Canonical immutable lenslet geometry, backend-neutral spot contract, reference calibration, detector-level measurement, and detector-free geometric sensor. |
| `shwfs_ao.dm` | Canonical DM configuration and wrapper: physical actuator IDs, OPD-equivalent command validation, stroke/fault policy, diagnostics, metadata, hashes, and provenance. |
| `shwfs_ao.calibration` | Canonical interaction calibration plus row-aware least-squares, TSVD, and Tikhonov reconstructors with explicit units, matrix identity, diagnostics, and bounded mask caches. |
| `shwfs_ao.control` | Canonical command projectors, applied-command-aware leaky integrator, exact frame latency, common loop runner, typed histories, and replay-safe sweeps. |
| `shwfs_ao.science` | Canonical SI bandpasses, backend-independent residual-OPD propagation construction, physical angular grids, and scalar Strehl/FWHM/encircled-energy/halo metrics. |
| `shwfs_ao.backends.native` | Lazily aggregated NumPy atmosphere, Shack-Hartmann diffraction, science-PSF propagation, and memoryless DM placement/influence/synthesis backends. |
| `shwfs_ao.detector` | Canonical detector configuration/realization, typed frame effects, centroid estimators, and validity policy. |
| `shwfs_detector` | Compatibility facade for lenslet spots, detector calls, centroiding, reference subtraction, and detector response matrices. |
| `ao_closed_loop` | Frozen compatibility facade over canonical calibration, command mapping, controller/loop, and DM owners. |
| `psf_tools`      | Frozen compatibility facade for phase-grid FFT PSFs, Strehl ratios, radial profiles, Marechal approximation, and wavelength scaling. |
| `ao_diagnostics` | Frozen compatibility facade for nanometre-facing science bandpasses and J/H/K scalar metric rows. |
| `shwfs_ao.experimental.pwfs` | Experimental simplified Fourier-optics PWFS forward model and `Sx/Sy` signal maps. |
| `pwfs_forward`   | Silent compatibility delegate to `shwfs_ao.experimental.pwfs`. |
| `synthetic_instrument_data` | Compatibility facade for detector-level 2 m SH-WFS geometry, reference centroids, measurements, and diagnostics. |
| `dm_model`       | Compatibility facade for the historical nanometre API over the canonical DM configuration, wrapper, and native spatial backend. |
| `interaction_matrix` | Compatibility facade for detector-level poke and reconstruction result formats; calibration, TSVD/Tikhonov policy, and scans delegate to `shwfs_ao.calibration`. |
| `ao_conditions`  | Observing-condition presets that keep seeing, photon budget, detector noise, latency, stroke, NCPA, and misregistration separate from numerical integration scale. |
| `ao_error_budget` | Eight-scenario 2 m SCAO error-budget table with OPD, Strehl, EE, command, and centroid metrics. |
| `ao_validation`  | Small pass/fail checks for Marechal consistency, diffraction scale, monotonicity, reproducibility, and DM fitting trend. |
| `ao_integration` | Compatibility orchestration for the fast notebook-11 run; execution returns in-memory results and delegates explicit CSV/JSON/figure output to `shwfs_ao.io.artifacts`. |

### Deformable-mirror command contract

The canonical DM accepts a full-layout `DmCommandVector` in
`m_opd_equivalent`. These values are optical-path-difference correction
amplitudes, not volts and not reflective mirror-surface displacement. Positive
commands produce positive correction OPD, and a loop forms

```python
residual_opd_m = atmosphere_opd_m - dm_correction_opd_m
```

The repository wrapper owns ordered physical actuator IDs, stroke clipping,
dead/stuck policy, requested-versus-applied diagnostics, metadata, hashes, and
provenance. Clipping is diagnosed from the requested command first; dead
actuators are then forced to zero and stuck actuators to their configured
clipped value. Native and optional optical backends are memoryless spatial
synthesizers: they own neither gain/leak nor latency/history.

The canonical backend boundary returns a finite raw OPD array in metres and
does not remove piston. Historical `nm_OPD_equivalent` fields and
piston-removed/NaN-masked arrays are handled only by compatibility adapters.
If a reflective backend accepts physical surface displacement, it sends half
the requested OPD-equivalent amplitude and lets reflection create twice that
surface displacement in OPD—exactly one factor-of-two conversion. See the
[AO-REF-006 DM note](docs/refactor/AO_REF_006_DEFORMABLE_MIRROR.md).

## Notebook sequence

| Notebook                                               | Purpose                                                                                                                                                                                                                                                                           |
| ------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `01_test_sh_wfs.ipynb`                                 | Initial SH-WFS sanity checks for slopes, modal reconstruction, residuals, and Strehl.                                                                                                                               |
| `02_sh_wfs_experiment.ipynb`                           | Baseline SH-WFS experiments with fixed/random wavefronts, spot checks, photon noise, and PSFs.                                                                                                                      |
| `03_zernike_mode_scan.ipynb`                           | Reconstruction quality versus Zernike order and controlled mode count.                                                                                                                                              |
| `04_sampling_vs_mode_order_heatmap.ipynb`              | WFS sampling density versus correction order and conditioning.                                                                                                                                                      |
| `05_tsvd_regularization.ipynb`                         | TSVD regularization in an intentionally ill-conditioned reconstruction problem.                                                                                                                                      |
| `06_detector_level_shwfs.ipynb`                        | Detector-level SH-WFS centroiding, response calibration, reconstruction, and noise scans.                                                                                                                           |
| `07_closed_loop_ao.ipynb`                              | Geometric closed-loop AO baseline with Gaussian DM influence functions and an integrator controller.                                                                                                                |
| `07_detector_level_closed_loop_ao.ipynb`               | Closed-loop AO driven by detector-level centroid shifts instead of ideal slopes.                                                                                                                                    |
| `08_pwfs_detector_level_atmospheric_turbulence.ipynb`  | Exploratory detector-level PWFS forward model with four pupil images and `Sx/Sy` maps.                                                                                                                             |
| `09_ao_psf_instrument_performance_high_order_ao.ipynb` | High-order actuator-space SH-AO demonstrator with 48 × 48 WFS sampling, 49 × 49 nominal actuator grid, TSVD reconstruction, and J/H/K PSF diagnostics.                                                             |
| `10_noise_latency_gain_stability.ipynb`                | Photon/read-noise, loop-delay, and gain-stability trade-offs.                                                                                                                                                       |
| `11_full_detector_level_2m_scao_demo.ipynb`            | Fast 2 m detector-level SCAO integration using the reusable detector, DM, interaction-matrix, control, error-budget, science-metric, and validation modules.                                                        |

## Installation

Clone the repository:

```bash
git clone https://github.com/xhvoid/Shack-Hartmann-AO-Simulation.git
cd Shack-Hartmann-AO-Simulation
```

Install the runtime dependencies (numpy, scipy, matplotlib, pandas):

```bash
python3 -m pip install -e .
```

The distribution name remains `shack-hartmann-ao-simulation`; the installed
package namespace is `shwfs_ao`. Verify the installed metadata-backed version
with:

```bash
python3 -c "import shwfs_ao; print(shwfs_ao.__version__)"
```

Notebook, test, and documentation tools are kept as optional extras so a plain
install stays lightweight. Add only what you need:

```bash
python3 -m pip install -e ".[test]"               # pytest
python3 -m pip install -e ".[notebooks]"           # jupyter, ipykernel
python3 -m pip install -e ".[docs]"                # reportlab (provenance PDF)
python3 -m pip install -e ".[hcipy]"               # optional HCIPy backend layer
python3 -m pip install -e ".[test,notebooks,docs]" # everything for development
```

The `hcipy` extra is optional: the native backends never import HCIPy, and
`import shwfs_ao` works without it. Currently the extra provides the
`shwfs_ao.backends.hcipy.conversion` layer (grid, field, aperture, and
wavefront round trips); HCIPy atmosphere, DM, Shack-Hartmann, and science
propagation backends arrive in later tickets. Calling HCIPy-backed
functionality without the extra raises an error naming the exact
`pip install 'shack-hartmann-ao-simulation[hcipy]'` command.

`requirements.txt` lists the runtime dependencies only, mirroring the
`pyproject.toml` core dependencies. For an exactly pinned test environment,
use the constraints file matching the interpreter:

```bash
python3 -m pip install -c constraints/py310.txt -e ".[test]"  # Python 3.10
python3 -m pip install -c constraints/py314.txt -e ".[test]"  # Python 3.14
```

The constraints are CI/test profiles rather than stricter requirements imposed
on downstream users; see [`constraints/README.md`](constraints/README.md).

### AO-REF-001/012 package and resource migration

All 19 existing top-level module imports remain installed as silent
compatibility paths. Their warning/removal clock has not started, and the
examples intentionally continue to use them until canonical component APIs are
introduced by later tickets. Do not import from `shwfs_ao.legacy` directly.
Examples and maintenance scripts now require an installed or editable package;
they no longer modify `sys.path`. Packaged resource names such as
`data/public/...` remain accepted even though AO-REF-012 moved their sole
canonical source to `src/shwfs_ao/resources/`. Wheels also contain a generated
`ao_simulation_data` compatibility alias; it is never edited in the source
tree. See the
[AO-REF-001 migration note](docs/refactor/AO_REF_001_MIGRATION.md) for the full
compatibility and resource-layout contract.

## Running tests

After installing the `test` extra, run the focused numerical test suite:

```bash
pytest -q
```

The GitHub Actions workflow in `.github/workflows/ci.yml` runs the full suite on
the declared minimum Python 3.10 and current stable Python 3.14 profiles. The
3.14 job also executes the two lightweight examples and a fast detector-level
SCAO smoke check:

```bash
python3 examples/run_psf_strehl_demo.py
python3 examples/run_shwfs_centroid_demo.py
python3 examples/run_public_data_overview.py
python3 examples/run_fast_integration.py
```

The slower public-data-informed AO scan is intentionally excluded from CI and remains a local diagnostic run.

## Command-line examples

The examples provide command-line entry points for checking the code without opening Jupyter:

```bash
python3 examples/run_shwfs_centroid_demo.py
python3 examples/run_psf_strehl_demo.py
python3 examples/run_interaction_matrix_demo.py
python3 examples/run_science_metrics_demo.py
python3 examples/run_public_data_overview.py
python3 examples/run_public_data_informed_ao_demo.py
python3 examples/run_error_budget_demo.py
python3 examples/run_validation_checks_demo.py
python3 examples/run_fast_integration.py
```

`run_public_data_informed_ao_demo.py` is a slower local scan because it runs
several fast integration configurations; it is not part of CI. It records its
wall-clock runtime in `figures/detector_level_SCAO/public_data_informed_runtime.csv`
and `.json` with a 30 minute local-run limit flag. Set `AO_DEMO_OUTPUT_DIR` to
place the overview, informed scan, and fast-integration artifacts elsewhere.

These scripts write artifacts under `figures/detector_level_SCAO/`:

```text
figures/detector_level_SCAO/shwfs_centroid_demo.png
figures/detector_level_SCAO/shwfs_centroid_demo.csv
figures/detector_level_SCAO/psf_strehl_demo.png
figures/detector_level_SCAO/psf_strehl_demo.csv
figures/detector_level_SCAO/public_data_overview.png
figures/detector_level_SCAO/public_filter_curves_jhk.png
figures/detector_level_SCAO/public_data_photon_budget.png
figures/detector_level_SCAO/public_data_summary.csv
figures/detector_level_SCAO/public_data_photon_budget.csv
figures/detector_level_SCAO/public_data_informed_ao_photon_scan.png
figures/detector_level_SCAO/public_data_informed_ao_photon_scan.csv
figures/detector_level_SCAO/public_data_informed_conditions.csv
figures/detector_level_SCAO/public_data_informed_error_budget.png
figures/detector_level_SCAO/public_data_informed_error_budget.csv
figures/detector_level_SCAO/public_data_informed_runtime.csv
figures/detector_level_SCAO/public_data_informed_runtime.json
figures/detector_level_SCAO/public_data_informed_validation.png
figures/detector_level_SCAO/public_data_informed_validation.csv
figures/detector_level_SCAO/fast_error_budget.png
figures/detector_level_SCAO/fast_error_budget.csv
figures/detector_level_SCAO/fast_validation.png
figures/detector_level_SCAO/fast_validation.csv
figures/detector_level_SCAO/fast_reference_metrics.json
```

For heavier local reruns, the integration API exposes explicit presets:

```python
from pathlib import Path

from ao_integration import IntegrationConfig, run_integration

for mode in ("portfolio", "research"):
    output_dir = Path("outputs") / mode
    config = IntegrationConfig.from_mode(
        mode,
        output_dir=output_dir,
        reference_metrics_path=output_dir / f"{mode}_reference_metrics.json",
    )
    run_integration(config)
```

Only `fast` is part of the automated test suite; the heavier presets are for local figure-quality or exploration runs.

## Running the notebooks

Start Jupyter from the repository root:

```bash
jupyter notebook
```

Recommended reading order:

```text
01 → 02 → 03 → 04 → 05 → 06 → 07 → 07_detector_level_closed_loop_ao → 08 → 09 → 10 → 11
```

For the high-order AO PSF result, start directly with:

```text
09_ao_psf_instrument_performance_high_order_ao.ipynb
```

For noise, latency, and loop-gain trade-offs, start with:

```text
10_noise_latency_gain_stability.ipynb
```

For the fast 2 m detector-level integration path, start with:

```text
11_full_detector_level_2m_scao_demo.ipynb
```

## Reproducibility and validation

I use four lightweight checks rather than trying to execute every notebook in CI:

* Unit tests validate the numerical core: PSF normalization, Strehl sanity checks, phase/OPD conversion, detector centroiding edge cases, phase-screen RMS scaling, and modal reconstruction.
* Command-line examples regenerate small PNG and CSV artifacts from deterministic seeds.
* Notebooks remain the narrative entry points for the broader AO experiments, with notebook 10 explicitly separating clean-model AO performance from noise, latency, and controller-stability stress tests.
* Notebook 11 is smoke-tested in fast mode with temporary output paths and compares generated metrics against the packaged regression references without overwriting them.

## Provenance summary

| Source class | Current use | Caveat |
| ------------ | ----------- | ------ |
| `direct_public_data` | Small tracked public caches under `src/shwfs_ao/resources/public/`, also addressable by the compatible logical names `data/public/...`: SVO `2MASS/2MASS.J/H/Ks` filter curves, IRSA 2MASS PSC NIR photometry, MAST Pan-STARRS DR2 optical photometry, and an ESO Paranal ASM nighttime atmosphere snapshot/time series. | The fast run and optional public-data-informed demo consume cached public products offline; they do not query the internet during tests. |
| `literature_derived` / `synthetic_literature_inspired` | Atmosphere profile notes, Paranal-like fallback profiles, and synthetic Gaussian DM choices inspired by public literature. | These are not measured AO calibrations. |
| `synthetic_assumed` | Detector, guide-star flux, loop, error-budget, and fast integration parameters. | Treat these as controlled demonstration settings. |
| `package_reference` | Reserved for package/library reference values when needed. | Not a substitute for observatory validation. |

The public caches can be refreshed with:

```bash
python3 scripts/fetch_public_reference_data.py
```

Gaia Archive and ERA5 are still treated carefully. Gaia remains a valid target
source for astrometry, but Pan-STARRS DR2 is the current optical-photometry
substitute because the Gaia Archive was inaccessible from this environment.
ERA5/CDS is not claimed as used; the current atmosphere conditioning comes from
ESO ASM seeing/tau0/theta0/turbulence-speed caches, and ERA5 would require user
CDS credentials plus a separate meteorological downselection.

## Notes on the main modelling choices

### 1. Detector-level SH-WFS measurement chain

The canonical detector-level Shack-Hartmann model follows the measurement process more explicitly than a geometric slope model:

```text
residual OPD in metres
→ phase at the explicit WFS wavelength
→ unit-sum lenslet focal-plane spot plus separate captured throughput
→ finite detector window
→ photon / read / background noise
→ centroid measurement
→ reference-subtracted centroid shift
→ calibrated response matrix
→ modal reconstruction
```

The canonical coordinates are detector-column `x` and detector-row `y`; positive physical tilts move spots toward increasing columns and rows. Reference calibration and runtime use the same optical sampling, detector realization, detector-response path, and centroid configuration. The geometric sensor shares the same physical lenslet IDs and `S:x`, `S:y` row order but directly reports wavefront slopes without importing detector code.

This distinction matters because real Shack-Hartmann sensors do not measure continuous slopes directly. They measure spot images on detector pixels. Centroiding error, finite sampling, photon statistics, read noise, spot clipping, and thresholding all enter before the reconstruction step.

### 2. Response-matrix conditioning and TSVD regularization

The reconstruction problem is treated as a linear inverse problem. Each WFS model produces an interaction matrix whose singular values determine which modal or actuator combinations are strongly or weakly sensed. New calibration uses `shwfs_ao.calibration.calibrate_interaction_matrix`: central differences are the default, modal coordinates are metres of pupil-RMS OPD, actuator coordinates are metres of OPD-equivalent command, and columns always represent the response to a positive residual OPD basis. The matrix retains every canonical WFS row; unusable rows are NaN plus an explicit mask rather than compressed or filled with zero. See the [AO-REF-007 calibration contract](docs/refactor/AO_REF_007_INTERACTION_MATRIX.md).

Independent `LeastSquaresReconstructor`, `TsvdReconstructor`, and
`TikhonovReconstructor` objects consume that calibrated matrix. They require
exact runtime row IDs and units, intersect runtime validity with calibration
validity, and preserve the full row layout with NaN on unusable rows. A
bounded mask-keyed cache reuses factorizations for recurring centroid masks,
so loop frames do not recompute the same SVD. Every estimate records the
interaction-matrix hash and retains its modal or actuator coordinate identity;
insufficient usable coverage or rank returns `None` rather than introducing a
zero-valued pseudo-measurement. See the
[AO-REF-008 reconstructor contract](docs/refactor/AO_REF_008_RECONSTRUCTORS.md).

The TSVD notebooks show why keeping every singular direction is not always useful. Weak singular directions can amplify noise or unstable command components, while overly aggressive truncation removes controllable modes. The cutoff is a system-level trade-off between fitting error, noise amplification, command conditioning, and image quality.

For the fast 2 m detector-level path, the current poke matrix is intentionally compact. It is best read as a detector-level DM/WFS response sanity check: all controlled modes remain well above the selected TSVD cutoff for this demonstrator configuration, so it should not be presented as a realistic high-order detector-level reconstructor-conditioning study.

### 3. Closed-loop AO correction

The canonical branch uses `shwfs_ao.control.run_closed_loop` to sequence an
explicit atmosphere, WFS, reconstructor, typed command projector, controller,
and DM. `LeakyIntegratorController` is the sole frame-latency owner. It advances
the delay queue even when reconstruction is unusable, applies gain and leak to
the last command actually accepted by the DM, and therefore preserves clipping
and actuator-fault effects in subsequent updates.

Frame `k` is timestamped `k / frame_rate_hz`. Its pre- and post-update residual
metrics use the same atmosphere sample and the sign
`atmosphere_opd_m - dm_correction_opd_m`. `LoopHistory` records requested and
applied full-layout command histories, released and reconstructed increment
norms, residual OPD RMS, saturation, row/subaperture validity, component
identity, and named random-stream provenance. Gain, latency, photon, read-noise,
and gain-delay scans reset state at every point so sweep order cannot alter the
result. See the
[AO-REF-009 control-loop contract](docs/refactor/AO_REF_009_CONTROL_LOOP.md).

The detector-level experiment remains deliberately synthetic, but its loop is
driven by centroid-shift measurements from simulated lenslet spots rather than
ideal analytic slopes. It is an engineering demonstrator, not calibrated RTC
telemetry.

### 4. High-order actuator-space AO / NIR PSF performance

Notebook 09 takes the earlier low-order examples into a higher-order actuator-space SH-AO loop.

The canonical construction path is `shwfs_ao.science`: it validates residual
OPD in metres, pupil geometry, science wavelength, and sampling before
delegating to the selected backend. The initial implementation lives in
`shwfs_ao.backends.native.propagation` and returns a unit-total-flux
`PsfResult` with strictly increasing physical angular axes in radians. Peak
Strehl compares angular surface-brightness peaks derived from discrete flux and
physical cell areas; encircled energy and halo fraction integrate discrete
pixel flux, while FWHM consumes angular surface brightness. None of these
metrics infers an angular scale from array indices. Bandpass
quadrature averages scalar monochromatic metric rows only. It does not coadd
same-index pixels across wavelength-dependent PSF grids. See the
[AO-REF-010 science contract](docs/refactor/AO_REF_010_SCIENCE.md).

The current high-order run uses:

```text
AO_QUALITY_MODE = "extreme"
N_SUBAP         = 48
N_ACT_ACROSS   = 49
N_PUPIL        = 384
TSVD rcond      = 2e-2
loop gain       = 0.65
```

For the adopted 0.8 arcsec seeing, the SH-WFS subaperture size is close to the Fried parameter at the WFS wavelength. The controller uses an actuator poke matrix and TSVD command reconstruction, then converts residual OPD into J/H/K science PSF metrics.

Representative clean-run results:

```text
open-loop median OPD RMS after settling    ≈ 2914 nm
closed-loop median OPD RMS after settling  ≈ 135 nm
correction factor                          ≈ 22×
```

Approximate NIR Strehl ratios:

```text
J band  ≈ 0.64
H band  ≈ 0.77
K band  ≈ 0.86
```

These values should be read as a clean-model performance demonstration rather than a calibrated prediction for a specific telescope or AO system.

I keep this caveat explicit because the numbers are useful for comparing clean-model cases, but they are not a substitute for a calibrated instrument error budget.

### 5. Noise, latency, and loop-gain stability

Notebook `10_noise_latency_gain_stability.ipynb` adds a compact engineering trade-off layer around the closed-loop AO model. It scans photon flux, read noise, a transparent centroid-noise proxy, loop gain, and frame delay, then reports residual OPD RMS, H-band Marechal Strehl, command growth, and a simple stability flag.

This is not a full AO error budget. Its purpose is to make the controller trade-offs visible: noise floors limit the value of high gain, latency narrows the stable gain range, and clean-model Strehl can be optimistic when detector and timing effects are ignored. The delay axis is also labelled as physical latency for a nominal 1 kHz loop.

The gain-delay map is the main control-engineering diagnostic in notebook 10. The photon-flux residual scan should be read more cautiously: in the current setting, residual OPD changes by only a small amount because latency, model dynamics, and the simplified DM/WFS geometry dominate the residual floor. The cleaner photon-noise sanity check is the centroid-RMS monotonicity scan, where centroid noise decreases with photon count.

### 6. Fast 2 m detector-level SCAO integration

Notebook `11_full_detector_level_2m_scao_demo.ipynb` is the fast integration path for the compact 2 m detector-level SCAO demonstrator. It does not replace notebook 09; it answers a different question. Notebook 09 shows a clean high-order 10 m-class actuator-space control case, while notebook 11 keeps the system smaller and routes the simulation through detector-level SH-WFS centroiding, a synthetic DM, a detector-level poke matrix, closed-loop correction, J/H/K science metrics, error-budget scenarios, and validation checks.

The command-line entry point is `examples/run_fast_integration.py`. It writes reference metrics with tolerances so later changes can be checked against open RMS, closed RMS, H-band Strehl, valid-centroid fraction, kept modes, and runtime band.

The main notebook-11 performance claims are residual OPD RMS, H-band Strehl, centroid validity, command RMS/peak command, saturation fraction, and validation pass/fail checks. EE50/EE80 are kept as secondary PSF diagnostics because the small fast-mode PSF grid can make encircled-energy values visibly quantized.

**Public-data-informed scenario suite.** The model separates *numerical scale* (`IntegrationConfig` fast/portfolio/research modes) from *observing difficulty* (`ObservingConditionConfig`: `nominal_synthetic`, `paranal_night_asm`, `poor_seeing`, `faint_ngs`, `stress_all_effects`), so a heavier rerun never silently means worse seeing or a fainter star. The public-data-informed path (`examples/run_public_data_informed_ao_demo.py`) draws the atmosphere from the nighttime ESO ASM cache (seeing → r0 → an ESO-ASM-conditioned *synthetic* phase sequence), the science bandpasses from the direct SVO 2MASS J/H/Ks curves, and the WFS photon budget from a Pan-STARRS AB-magnitude estimate, then writes a five-condition error-budget table with explicit provenance columns. The synthetic AO-internal terms are represented explicitly through an affine WFS–DM misregistration proxy (sub-pixel shift, rotation, magnification, shear), a three-component NCPA generator (low-order Zernike + mid-spatial-frequency ripple + static polishing-like term), a decomposed latency model, and named visible-WFS detector presets. The detector-level interaction-matrix diagnostics add a central-difference poke-amplitude scan and a TSVD noise-amplification proxy.

![Poke-amplitude scan](figures/detector_level_SCAO/poke_amplitude_scan.png)

Because the richer NCPA and misregistration models feed the eight-scenario `all_effects` case, the fast reference-metrics schema is version 2. It still runs offline, top-to-bottom, with all metrics finite and validation passing, and the saved reference baselines match that schema.

### 7. PWFS extension

The pyramid-WFS branch has one installed implementation at `shwfs_ao.experimental.pwfs`; the existing `pwfs_forward` import delegates to it. The compact Fourier-optics model propagates the pupil field to the focal plane, applies a pyramid-like phase mask, and propagates back to form four re-imaged pupil intensities. Normalized `Sx/Sy` maps are then used as the PWFS measurement vector.

This remains an exploratory API. It preserves the existing numerical model and seeded outputs, but it does not implement the stable Shack-Hartmann protocols and is not a validated PWFS SCAO backend.

## Validation and limitations

[`docs/validation.md`](docs/validation.md) lists the internal sanity checks (Marechal consistency, diffraction scale, photon/read-noise/latency trends, DM-fitting trend, reproducibility, centroid validity) and what is explicitly *not* validated.

The current implementation intentionally keeps several assumptions simple:

* The atmosphere is represented by compact Kolmogorov / von Karman-like phase screens.
* Some atmospheric screens are RMS-normalized for controlled tests.
* The deformable mirror uses idealized Gaussian influence functions.
* The detector models are simplified.
* The SH-WFS branch is more mature than the PWFS branch.
* The PWFS branch is a compact Fourier-optics demonstrator, not a fully validated PWFS control simulator.
* The high-order notebook uses a geometric SH-WFS slope model rather than detector-level spot centroiding.
* The high-order notebook does not include photon noise, read noise, centroiding error, detector nonlinearity, temporal delay, vibration, wind-shake, or a full servo-lag error budget.
* Notebook 10 explores photon/read noise and delay through a simplified proxy model rather than a calibrated detector and real-time-control simulator.
* Notebook 11 uses reduced fast-mode sampling for reproducibility; its detector, DM, atmosphere, guide-star, NCPA, misregistration, and stroke terms are synthetic or literature-inspired placeholders.
* Notebook 11 is a compact 2 m SCAO demonstrator, not an ELT-scale or MICADO-scale performance prediction.
* EE50/EE80 values in the fast path can be limited by PSF sampling and radius-grid quantization, so they should be treated as secondary diagnostics rather than headline performance claims.
* The fast reference metrics are regression targets for this repository, not validation against observatory telemetry.
* The high-order notebook does not include multi-layer tomography, LGS cone effect, NCPA, chromaticity, throughput, sky background, or science-camera noise.
* The simulations are not calibrated to a specific telescope, instrument, guide-star configuration, or observatory AO system.

These limitations are intentional: the project is designed to make the modelling chain inspectable and educational rather than to hide assumptions inside a black-box simulator.

## Author

Xu Han
MSc Astrophysics, LMU Munich
MSc Photonics student, Hochschule München

Research interests: adaptive optics, astronomical instrumentation, detector-level wavefront sensing, PSF modelling, instrument-performance prediction, and astrophotonics.

## Citation and license

If you use this repository, please cite it using the metadata in
[CITATION.cff](CITATION.cff). The source metadata currently identify version
`0.1.0`; this optimization does not create a version tag or published release.
The future maintainer workflow is documented in
[`docs/releasing.md`](docs/releasing.md).

Repository-authored software and documentation are available under the
[MIT License](LICENSE). Cached third-party public data are not independently
relicensed by that license; review [DATA_LICENSES.md](DATA_LICENSES.md) for
source terms, acknowledgements, and unresolved redistribution questions.
