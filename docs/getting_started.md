# Installation and first experiments

The project is a Python package plus executable research notebooks. Start with
the native Shack-Hartmann tutorials; HCIPy and TIPTOP are optional extensions.
Run the commands below from a terminal. Core support is Python 3.10 or newer;
the TIPTOP study needs Python 3.11 or newer.

## Create an environment

Clone the repository and make an isolated environment (macOS/Linux):

```bash
git clone https://github.com/xhvoid/Shack-Hartmann-AO-Simulation.git
cd Shack-Hartmann-AO-Simulation
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[test,notebooks]"
```

On Windows, create the environment with `py -m venv .venv` and activate it
with `.venv\Scripts\Activate.ps1` in PowerShell; then use the same installation
command. The editable install makes the package available to notebooks without
modifying their import paths.

This is a convenient interactive environment, not an exact dependency lock.
For the CI/replay environment, use the matching Python version and
[constraint profile](../constraints/README.md). For example, in a fresh
**Python 3.14** environment:

```bash
python -m pip install -c constraints/py314.txt -e ".[test,notebook-test]"
python scripts/verify_environment_lock.py --constraints constraints/py314.txt
```

The `notebook-test` extra supports automated execution; `notebooks` adds the
interactive Jupyter application and is not the same locked dependency set.

## First run

The [README quick start](../README.md#run-the-project) checks the installed
package and runs the fast integration example. It produces a small set of
figures, tables and reference metrics using a control-space disturbance.
That example is a software integration fixture, not an atmosphere-driven AO
performance prediction.

For the optical and control experiments, launch Jupyter from the repository
root in the interactive environment:

```bash
jupyter notebook
```

Open the tutorials in order:

1. [Wavefronts and atmosphere](../notebooks/tutorials/00_wavefront_and_atmosphere.ipynb)
2. [Geometric Shack-Hartmann response](../notebooks/tutorials/01_geometric_shwfs.ipynb)
3. [Detector noise and centroid validity](../notebooks/tutorials/02_detector_centroiding.ipynb)
4. [Interaction matrices and TSVD](../notebooks/tutorials/03_tsvd_regularization.ipynb)
5. [Closed-loop correction](../notebooks/tutorials/04_closed_loop_control.ipynb)

Select the kernel belonging to this environment. If your existing Jupyter
installation does not offer it, register it explicitly:

```bash
python -m ipykernel install --user --name shwfs-ao --display-name "Python (shwfs-ao)"
```

The notebooks include saved outputs for reading without execution. Restart the
kernel and run all cells to regenerate them. Studies expose their configuration
near the top; `FAST_SMOKE` selects a reduced CI run where provided. The committed
current study results use their full parameterization.

## Optional backends and sensitivity study

Install the HCIPy adapter in your interactive environment:

```bash
python -m pip install -e ".[hcipy]"
python examples/run_native_hcipy_validation.py
```

For an exact HCIPy validation environment use Python 3.11 and
`constraints/hcipy-py311.txt`; see the constraint guide before combining
profiles or optional extras.

For the supplemental TIPTOP study, use a separate Python 3.11+ environment and
install:

```bash
python -m pip install -e ".[notebooks,test,tiptop]"
```

Open [TIPTOP performance modelling](../notebooks/studies/12_TIPTOP_performance_modelling.ipynb).
Keep its sibling `tiptop_support.py` file with the notebook. The study checks
the pinned TIPTOP/P3/MASTSEL versions before execution. Its scope, numerical
completion and convergence evidence are in the
[study notes](notebook12_tiptop_portfolio_notes.md).

## Checks and generated files

Run the fast native test selection from the repository root:

```bash
python -m pytest -q -m "not hcipy and not slow"
```

The CI notebook runner enforces outbound-network isolation on supported Linux
hosts; its namespace checks are platform-specific. Scientific simulations use
packaged resources and do not need a network connection after installation.
Long physical regressions and full studies are separate from fast smoke tests.

Write new experiment outputs under `outputs/`, `results/` or another disposable
location. Do not overwrite the accepted packaged reference metrics: numerical
baseline changes use the candidate/diff/accept workflow described in
[validation](validation.md). Figures linked from the README have explicit
[notebook provenance](../figures/README.md).
