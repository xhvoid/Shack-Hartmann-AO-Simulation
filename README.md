# Shack-Hartmann AO Simulation

I started this Python project to learn adaptive optics by building a simulation
and examining its behaviour. It grew to cover wavefront sensing,
reconstruction, feedback control and image formation. I completed an MSc in
Astrophysics and am now studying Photonics.

**[Open AO Explorer](https://xhvoid.github.io/Shack-Hartmann-AO-Simulation/)**

The selected examples follow a compact 2 m loop, investigate loss of lock in
a 2.2 m model, and compare gain and delay in a simplified 42 m model. They are
recorded simulations with explicit assumptions, not predictions for operating
instruments.

## Install

Requires Python 3.10 or later. From the repository directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
```

On Windows, activate with `.venv\Scripts\activate`. For local editing, use
`python -m pip install -e .`. The native backend uses NumPy and SciPy;
`python -m pip install '.[hcipy]'` adds the optional HCIPy backend.

## Run an example

```bash
python examples/run_detector_level_demo.py
python examples/run_shwfs_centroid_demo.py
python examples/run_psf_strehl_demo.py
```

The first runs a synthetic 2 m loop and writes
`detector_level_demo_output/detector_level_demo.json`. The others write plots
under `outputs/examples/detector_level_SCAO/`. Set `AO_DEMO_OUTPUT_DIR` to
choose a destination. The PSF example compares a prescribed wavefront with a
scaled copy; it does not run a controller.

```python
from shwfs_ao.io.configs import load_system_profile
from shwfs_ao.experiments.scao import run_closed_loop

config = load_system_profile("det_emccd_2m_synthetic", 1)
history = run_closed_loop(config)
print("Residual after each update (nm):", history.post_update_residual_opd_rms_m * 1e9)
```

OPD and wavelengths use metres internally. Explorer image metrics use the
residual **before** an update, as labelled. The short example above does not
reproduce the site's longer recordings without their saved settings.

## Scope and evidence

The models are on-axis and use simplified pupils, influence functions,
atmosphere and detector assumptions. The 42 m geometry comes from a historical
E-ELT reference; the current ELT has a 39 m primary. There is no segmented-mirror
phasing model or calibration against on-sky telemetry. A successful numerical
comparison applies to the component and conditions tested.

- [Model conventions and sources](docs/methods.md)
- [Reproducing examples and checking saved results](docs/reproducing.md)
- [Selected studies and their evidence](https://xhvoid.github.io/Shack-Hartmann-AO-Simulation/#studies)

`src/shwfs_ao/` holds the implementation and versioned resources. `examples/`
contains the three entry points; `tests/` contains small mathematical checks.
`build_support/` preserves compatibility resource imports. Website source,
compact records and publication tools live on the
[`website` branch](https://github.com/xhvoid/Shack-Hartmann-AO-Simulation/tree/website).

Code is under the [MIT licence](LICENSE). See [data licences](DATA_LICENSES.md)
for third-party attribution and terms.
