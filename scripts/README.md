# Scripts

Reserved for maintenance and reproducibility helpers. User-facing command-line demonstrations live in `examples/`.

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
