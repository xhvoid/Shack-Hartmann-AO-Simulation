# AO-REF-012 — Artifact and resource boundary

AO experiments now finish in memory before any file is created. The canonical
writer is `shwfs_ao.io.artifacts.write_integration_artifacts`; its
`ArtifactConfig` names a caller-owned output directory and, when needed, an
explicit reference-metrics path. The I/O layer never searches for a repository
root.

```python
from shwfs_ao.io.artifacts import ArtifactConfig, write_integration_artifacts

result = run_integration(config, write_outputs=False)
written = write_integration_artifacts(
    result,
    ArtifactConfig(output_dir=temporary_output, prefix="fast"),
)
```

The retained `write_outputs=True` integration option is a compatibility
delegate to this same call. It is not part of the physical experiment engine.
With `write_outputs=False`, the returned result has an empty `written_files`
tuple and the writer is never imported or invoked.

## Deterministic schema-v2 compatibility

Schema version 2 remains the default during the compatibility window. It writes
the frozen files in this order:

1. `{prefix}_error_budget.csv`
2. `{prefix}_error_budget.png` when figures are enabled
3. `{prefix}_validation.csv`
4. `{prefix}_validation.png` when figures are enabled
5. `{prefix}_reference_metrics.json` (or the explicit path)

The CSV headers and row order are exact contracts. JSON uses sorted keys,
two-space indentation, finite values only, and one final newline. Public
`read_scenario_table`, `read_validation_table`, and `read_runtime_table`
functions accept only a named legacy header or its defined additive-v3 header;
they do not guess a schema from similar columns. Generic
`write_csv_rows`, `write_json_record`, and `write_runtime_artifacts` helpers are
available to examples that own non-integration tables.

## Governed schema 3

Schema version 3 appends `artifact_schema_version`, `artifact_kind`, `backend`,
and `system_profile` to CSV files and writes a named sidecar for every table.
Each sidecar records the exact header, row count and order, field units, CSV
SHA-256, component/layout hashes, provenance, and reproducibility record. A
sorted artifact manifest records every generated member's schema, size, and
content hash.

`read_v2`, `read_v3`, and `upgrade_v2_to_v3` are explicit reference-metrics
entry points. The upgrader preserves every v2 value other than the enclosing
schema-version discriminator, including the legacy bare-hex `config_hash`. It
requires caller-supplied backend, system profile, provenance, component/layout
hashes, conventions, reproducibility details, and metric-specific tolerance
metadata.

Artifact authority is structural:

- `run_result` forbids candidate, diff, and acceptance metadata; source commit
  and working-tree state may be null for an installed wheel.
- `baseline_candidate` requires candidate and diff metadata plus source
  revision, patch hash, and a definite clean/dirty state.
- `accepted_regression_baseline` requires a non-empty acceptance reason and
  review reference plus the same reproducible source evidence. It forbids
  candidate/diff metadata.

Running a simulation or its tests can therefore never accept a baseline as a
side effect.

## Packaged schemas and fixtures

The seven governed schemas live under `shwfs_ao.resources.schemas`:

- `fast_reference_metrics.schema.json`
- `cross_backend_baseline.schema.json`
- `scenario_table_sidecar.schema.json`
- `validation_table_sidecar.schema.json`
- `runtime_table_sidecar.schema.json`
- `artifact_manifest.schema.json`
- `provenance.schema.json`

Canonical fixtures are read with `importlib.resources` through
`shwfs_ao.io.resources`. Historical names beginning with `data/` remain valid
logical aliases, including from a non-editable wheel without a checkout or a
`.git` directory.

`src/shwfs_ao/resources/` is the sole editable resource tree. Its sorted
`resource_manifest.json` records every canonical member and SHA-256. The
registered commands in `build_support.resource_alias` validate that manifest,
then generate `ao_simulation_data` only in a wheel build directory or inside a
PEP 660 editable environment. A direct wheel and a wheel rebuilt from the
sdist must contain identical canonical and alias manifests, with every alias
payload byte-equal to its canonical member. No command generates
`src/ao_simulation_data/`.

Public-cache maintenance and explicit baseline acceptance refresh the checked
manifest after changing canonical bytes. Baseline generation writes to a
separate caller-owned candidate directory and produces JSON and Markdown
diffs; acceptance is a distinct command requiring a reason and review
reference.
