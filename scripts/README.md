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
