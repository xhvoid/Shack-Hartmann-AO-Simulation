# Shack-Hartmann AO Simulation

A Python project for studying Shack-Hartmann wavefront sensing and
single-conjugate adaptive optics. I use it to explore how atmosphere,
detector noise, reconstruction and feedback affect the residual wavefront
and the resulting images.

[AO Explorer](https://xhvoid.github.io/Shack-Hartmann-AO-Simulation/) shows
recorded simulations and case studies. The models use published information
and synthetic assumptions; they have not been calibrated against a real
instrument.

## Install

Requires Python 3.10 or later. From the repository directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
```

On Windows, activate with `.venv\Scripts\activate` instead. To edit the
package locally, use `python -m pip install -e .`.

The native backend uses NumPy and SciPy. Optional installs:

```bash
python -m pip install '.[hcipy]'       # HCIPy optical backend
python -m pip install '.[validation]'  # JSON Schema checks for saved baselines
```

## Run the examples

```bash
python examples/run_detector_level_demo.py
python examples/run_shwfs_centroid_demo.py
python examples/run_psf_strehl_demo.py
```

The detector example runs a synthetic 2 m SCAO configuration and writes
`detector_level_demo_output/detector_level_demo.json`. The other examples
write plots and tables under `outputs/examples/detector_level_SCAO/`.
Set `AO_DEMO_OUTPUT_DIR` to choose another output directory.

The PSF example compares a prescribed phase map with a scaled copy of it;
it illustrates wavefront error and image quality without running a control loop.

## Use from Python

```python
from shwfs_ao.io.configs import load_system_profile
from shwfs_ao.experiments.scao import run_closed_loop

config = load_system_profile("det_emccd_2m_synthetic", 1)
history = run_closed_loop(config)

print("Frames:", history.n_steps)
print("Residual RMS (nm):", history.post_update_residual_opd_rms_m * 1e9)
```

Profiles, detector presets and their source information are included in
`src/shwfs_ao/resources/`. Profile names and versions are explicit so a
saved configuration can be loaded again. OPD is in metres internally;
wavelengths are also in metres. The example above prints the residual after
each command update. Explorer image metrics may refer to the wavefront
before that update, as labelled on the site.

## Optional computation service

`scripts/ao_dynamic/service.py` runs new seeded 2 m experiments for the
Explorer generation panel. See the [setup guide](docs/research/ao_dynamic_v1/DEPLOYMENT.md)
for a local preview with a separate website checkout. No public service is hosted.

## Files

- `src/shwfs_ao/`: simulation components and packaged resources.
- `examples/`: the three runnable examples above.
- `build_support/`: packaging helpers for the resource compatibility alias.
- `pyproject.toml` and `MANIFEST.in`: installation and source-package contents.

Explorer files are maintained on the
[`website` branch](https://github.com/xhvoid/Shack-Hartmann-AO-Simulation/tree/website),
which includes preview and publication instructions.

Code is released under the [MIT licence](LICENSE). Third-party data retain
the terms listed in [DATA_LICENSES.md](DATA_LICENSES.md).
