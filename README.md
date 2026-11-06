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

A fourth example evaluates science targets off axis from the guide star in
the layered 2.2 m model. It runs one 1500-frame closed loop and takes 6 to
25 minutes on two threads, depending on the machine:

```bash
python examples/run_off_axis_science_demo.py --profile robo_ao2_22m_ngs_draft --version 2 --offsets "0,0;5,0;10,0;20,0" --wavelength-um 1.65 --burn-in 150 --block-frames 75 --output outputs/off_axis_science/22m
```

The example writes two plots, a CSV table, a JSON result and a run record.
In the reference exposure (frames 150–1499, 1.8 s), the interpolated peak
Strehl at 1.65 µm fell from 0.444 at the guide star to 0.433, 0.396 and
0.337 at separations of 5, 10 and 20 arcsec. These values describe one
turbulence realization of the model with no separate tip-tilt loop.

A Linux x86_64 repeat agreed with the five-decimal reference values to
within 0.000004. A macOS arm64 repeat gave 0.448, 0.436, 0.398 and
0.338 for the same offsets. All four macOS values fell outside the
predeclared absolute tolerance of 0.0001.
[PSF plots, Strehl definitions and platform comparison](docs/scao_off_axis_science.md).

OPD and wavelengths use metres internally. Explorer image metrics use the
residual **before** an update, as labelled. The short example above does not
reproduce the site's longer recordings without their saved settings.

## Scope and evidence

The models use simplified pupils, influence functions,
atmosphere and detector assumptions. The 42 m geometry comes from a historical
E-ELT reference; the current ELT has a 39 m primary. There is no segmented-mirror
phasing model or calibration against on-sky telemetry. A successful numerical
comparison applies to the component and conditions tested.

- [Model conventions and sources](docs/methods.md)
- [Off-axis science targets in the 2.2 m model](docs/scao_off_axis_science.md)
- [Component checks, numerical repairs and remaining limits](docs/verification-summary.md)
- [Reproducing examples and checking saved results](docs/reproducing.md)
- [Selected studies and their evidence](https://xhvoid.github.io/Shack-Hartmann-AO-Simulation/#studies)

`src/shwfs_ao/` holds the implementation and versioned resources. The four
examples are in `examples/`. Component and off-axis tests are in `tests/`.
The off-axis validation script is `scripts/off_axis_validation.py`.
`build_support/` preserves compatibility resource imports. Website source,
compact records and publication tools live on the
[`website` branch](https://github.com/xhvoid/Shack-Hartmann-AO-Simulation/tree/website).

Code is under the [MIT licence](LICENSE). See [data licences](DATA_LICENSES.md)
for third-party attribution and terms.
