# Scripts

Reserved for maintenance and reproducibility helpers. User-facing command-line demonstrations live in `examples/`.

Run these helpers after installing the project (for example with
`python3 -m pip install -e .`). They import the installed compatibility modules
and do not modify `sys.path`.

## Parameter/source inventory

`build_parameter_source_inventory_pdf.py` regenerates the Markdown and PDF
parameter-source inventory from tracked CSV/JSON caches and generated result
tables:

```bash
python scripts/build_parameter_source_inventory_pdf.py
```

The PDF path uses `reportlab` for real table layout. If `reportlab` is not
installed, use `--no-pdf` to write only the Markdown inventory or install the
`docs` optional dependency.

## Resource and baseline maintenance

`fetch_public_reference_data.py` refreshes reviewed caches in the sole
canonical `src/shwfs_ao/resources/public/` tree. The deprecated installed
`ao_simulation_data` layout is generated only while building a distribution.
The maintenance command also deterministically refreshes the checked canonical
resource manifest after all downloads have been converted successfully.

`update_fast_regression_baselines.py` keeps generation and acceptance separate.
Generate into an explicit candidate directory with `--generate-candidate`,
review its JSON and Markdown diffs, then use `--accept-baseline-update` with a
non-empty `--reason` and `--review-reference`. Neither normal tests nor an
integration run can accept a baseline implicitly.

## CI smoke and packaging helpers (AO-REF-019/020)

`prepare_wheel_smoke_bundle.py` copies the manifest-listed portable tests,
offline fixtures, canonical notebooks, example scripts, and support scripts
from `tests/wheel_smoke/manifest.json` into a fresh bundle directory; it
refuses `src/`, `.git/`, and the archived `notebooks/legacy` evidence so the
bundle can only pass against the installed wheel.

`run_notebook_smoke.py` executes canonical notebooks under the AO-REF-019
smoke contract (fresh temporary working directory, `MPLBACKEND=Agg`, per-cell
and whole-notebook timeouts), selecting by manifest execution class. The kernel
runs in a network namespace holding nothing but loopback, so no cell — nor any
subprocess or C extension it reaches — can leave the machine; an injected first
cell additionally turns an attempted access into a Python error naming the
address. Namespaces are a Linux facility, so `--network-isolation` says what to
do without them: the default `required` refuses to run rather than report an
offline contract it did not enforce, `auto` runs with the in-kernel guard alone
and warns, and `off` disables the namespace.

`inspect_wheel_contents.py` compares a built wheel against a wheel rebuilt
from the sdist in a clean directory and asserts the compatibility modules,
schemas, fixtures, and runtime resources are packaged.
