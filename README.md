# Shack-Hartmann AO Simulation

This Python model follows atmospheric wavefronts through a Shack–Hartmann
sensor and a single-conjugate adaptive optics loop. The experiments vary
detector noise, reconstruction and feedback, and measure what each does to
the wavefront error and the image quality.

[AO Explorer](https://xhvoid.github.io/Shack-Hartmann-AO-Simulation/) shows
recorded simulations and case studies. The models are built from published
information and synthetic assumptions; none of them has been calibrated
against a real instrument.

## Branch status

This branch carries the experimental computation service, not the current
package release. It has not picked up the component repairs that are now on
`main`, and the checks recorded here in October 2026 apply only to the source
versions they were run on. Read the
[version and validation scope](docs/research/ao_dynamic_v1/STATUS.md) before
using it for new results. No public computation service is hosted.

## Install

You need Python 3.10 or later. From the repository directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
```

On Windows, activate with `.venv\Scripts\activate` instead. If you plan to
edit the package, use `python -m pip install -e .`.

The native backend only needs NumPy and SciPy. Two optional extras:

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
`detector_level_demo_output/detector_level_demo.json`. The other two write
plots and tables under `outputs/examples/detector_level_SCAO/`; set
`AO_DEMO_OUTPUT_DIR` if you want them somewhere else.

The PSF example compares a prescribed phase map with a scaled copy of itself.
It shows the link between wavefront error and image quality without running
a control loop.

## Use from Python

```python
from shwfs_ao.io.configs import load_system_profile
from shwfs_ao.experiments.scao import run_closed_loop

config = load_system_profile("det_emccd_2m_synthetic", 1)
history = run_closed_loop(config)

print("Frames:", history.n_steps)
print("Residual RMS (nm):", history.post_update_residual_opd_rms_m * 1e9)
```

Profiles, detector presets and their source information are packaged under
`src/shwfs_ao/resources/`. Profile names and versions are explicit, so a saved
configuration can always be loaded again. Both OPD and wavelength are stored
in metres. The example above prints the residual after each command update;
the Explorer's image metrics may refer to the wavefront before that update,
as labelled on the site.

## Optional computation service

`scripts/ao_dynamic/service.py` runs new seeded 2 m experiments for the
Explorer's generation panel. The [setup guide](docs/research/ao_dynamic_v1/DEPLOYMENT.md)
explains how to preview it locally with a separate website checkout. No public
service is hosted.

## Files

- `src/shwfs_ao/`: simulation components and packaged resources.
- `examples/`: the three runnable examples above.
- `build_support/`: packaging helpers for the resource compatibility alias.
- `pyproject.toml` and `MANIFEST.in`: installation and source-package contents.

The Explorer itself is maintained on the
[`website` branch](https://github.com/xhvoid/Shack-Hartmann-AO-Simulation/tree/website),
which has its own preview and publication instructions.

The code is under the [MIT licence](LICENSE). Third-party data keep the terms
listed in [DATA_LICENSES.md](DATA_LICENSES.md).
