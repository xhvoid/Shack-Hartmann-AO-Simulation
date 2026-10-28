# Migration Guide

This guide tracks the import paths, resource packages, and serialized
compatibility surfaces that change across the `shwfs_ao` refactor, and how to
move owned code onto the canonical package.

The machine-readable companions to this document are installed as packaged
resources and are the single source of truth for the automated warning
messages and Phase B tooling:

- `shwfs_ao/resources/deprecation_inventory.json` — every deprecated import
  path, resource alias, and public symbol, with its canonical replacement.
- `shwfs_ao/resources/deprecation_clock.json` — the deprecation release/tag,
  publication date, planned removal release, and earliest removal date.

Read them from installed code through
`shwfs_ao._deprecation.deprecation_inventory()` and
`shwfs_ao._deprecation.deprecation_clock()`.

## AO-REF-021 — deprecation of duplicate public paths

### What changed

AO-REF-001 relocated every historical top-level module into the installed
`shwfs_ao` namespace while keeping the old flat import paths working as silent
compatibility shims. AO-REF-002 through AO-REF-020 then moved each physical
responsibility to a canonical backend-independent home and left the historical
surface as thin re-export shims and behavior-compatibility adapters.

AO-REF-021 Phase A **isolates and deprecates** that historical surface. It does
not delete anything. Specifically:

- Importing any of the 19 root-level modules (for example `import dm_model` or
  `from ao_diagnostics import ...`) now emits a `DeprecationWarning` that names
  the canonical replacement and the planned removal release.
- Importing the `ao_simulation_data` resource-alias package emits the same kind
  of warning. Its byte-identical canonical package is `shwfs_ao.resources`,
  read through `shwfs_ao.io.resources`.
- The `shwfs_ao.legacy.*` modules remain **silent**. They are the documented,
  non-canonical compatibility layer (thin facades plus a small number of
  behavior-compatibility adapters). New code should still prefer the canonical
  packages, but importing `shwfs_ao.legacy.*` does not warn during the window.
- `import shwfs_ao` and importing any canonical `shwfs_ao.<subpackage>` module
  never warns.

Nothing about the numerical models, seeds, signatures, or resource payloads
changes in Phase A. Warnings are additive.

### Replacement map

The canonical replacement for every deprecated root module. The
`shwfs_ao.legacy.<module>` path is the frozen compatibility surface for cases
that have no drop-in canonical equivalent (for example the notebook-11
aggregated diagnostic table or the nm-unit detector loop).

| Deprecated root import | Canonical replacement |
|---|---|
| `ao_closed_loop` | `shwfs_ao.control`, `shwfs_ao.experiments.scao` (or `shwfs_ao.legacy.ao_closed_loop`) |
| `ao_conditions` | `shwfs_ao.experiments.public_data_conditioned` |
| `ao_diagnostics` | `shwfs_ao.science.metrics`, `shwfs_ao.science.bandpass` (or `shwfs_ao.legacy.ao_diagnostics`) |
| `ao_error_budget` | `shwfs_ao.experiments.error_budget` |
| `ao_integration` | `shwfs_ao.experiments.scao`, `shwfs_ao.io.artifacts` (or `shwfs_ao.legacy.ao_integration`) |
| `ao_validation` | `shwfs_ao.validation` (or `shwfs_ao.legacy.ao_validation`) |
| `atmosphere_profiles` | `shwfs_ao.backends.native.atmosphere`, `shwfs_ao.io.configs` (or `shwfs_ao.legacy.atmosphere_profiles`) |
| `config_hashing` | `shwfs_ao.core.hashing` |
| `data_sources` | `shwfs_ao.io.public_data`, `shwfs_ao.core.provenance` |
| `dm_model` | `shwfs_ao.dm` (or `shwfs_ao.legacy.dm_model`) |
| `interaction_matrix` | `shwfs_ao.calibration` (or `shwfs_ao.legacy.interaction_matrix`) |
| `phase_screen` | `shwfs_ao.backends.native.atmosphere`, `shwfs_ao.core.wavefront` (or `shwfs_ao.legacy.phase_screen`) |
| `psf_tools` | `shwfs_ao.backends.native.propagation`, `shwfs_ao.science.metrics` (or `shwfs_ao.legacy.psf_tools`) |
| `pwfs_forward` | `shwfs_ao.experimental.pwfs` |
| `reconstruction` | `shwfs_ao.wfs.shack_hartmann.geometric`, `shwfs_ao.calibration` (or `shwfs_ao.legacy.reconstruction`) |
| `runtime_resources` | `shwfs_ao.io.resources` |
| `shwfs_detector` | `shwfs_ao.detector`, `shwfs_ao.wfs.shack_hartmann` (or `shwfs_ao.legacy.shwfs_detector`) |
| `synthetic_instrument_data` | `shwfs_ao.detector`, `shwfs_ao.wfs.shack_hartmann` (or `shwfs_ao.legacy.synthetic_instrument_data`) |
| `zernike` | `shwfs_ao.backends.native.modes`, `shwfs_ao.core.wavefront` (or `shwfs_ao.legacy.zernike`) |

Symbol-level replacements (where a specific name has a more precise canonical
home than its module) are listed under `root_shims[].symbol_replacement_overrides`
in `deprecation_inventory.json`.

### Resource access

```python
# Deprecated: warns on import, resolves the byte-identical alias package.
import ao_simulation_data

# Canonical: read packaged data through the io layer.
from shwfs_ao.io.resources import open_text_resource, resource_exists
```

The `data/<name>` and bare `<name>` logical-resource lookups accepted by
`shwfs_ao.io.resources.normalized_resource_name` remain available and do not
warn; they resolve against the canonical `shwfs_ao.resources` tree.

### Silencing the warning during migration

The warning is a standard `DeprecationWarning` with `stacklevel=2`, so it points
at the importing line. To keep a green build while migrating, either move to the
canonical import or scope a filter:

```python
import warnings

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    import dm_model  # temporary; prefer `from shwfs_ao.dm import ...`
```

### Deprecation clock

`deprecation_clock.json` records the timing contract. Phase B (deletion) may
begin only after **both** boundaries elapse:

1. **Time boundary** — at least `minimum_window_days` (90) days after the
   deprecation release's `publication_utc_date`.
2. **Release boundary** — at least `minimum_subsequent_minor_releases` (1)
   further minor release is published after the deprecation release.

`earliest_removal_utc_date` records the later of those dates as they are known.
While the subsequent minor release is still unpublished the release boundary is
open regardless of the calendar, and
`shwfs_ao._deprecation.removal_boundaries_satisfied(...)` returns `False`. The
maintainer updates the publication fields in the same commit that tags the
release (see [releasing.md](releasing.md)).

### Phase B (deferred)

Phase B is a separate, release-bound deletion PR. It removes the root shims, the
`ao_simulation_data` alias, and any legacy module that is not deliberately
retained, with no numerical-model changes. When Phase B lands, a tombstone
section is appended here naming every removed import path and its last
compatible release. See [`src/shwfs_ao/legacy/README.md`](../src/shwfs_ao/legacy/README.md)
for the retained-code inventory.

## Serialized artifact migration

Import-path deprecation and artifact-schema evolution have independent clocks.
Removing a Python shim never authorizes dropping an artifact reader, changing a
CSV header, or rewriting an accepted baseline.

- Schema-v2 fast-reference JSON remains readable through
  `shwfs_ao.io.artifacts.read_v2()` and may be emitted byte-compatibly for old
  consumers during the compatibility window.
- Scenario, validation, and runtime CSV readers accept the exact frozen v2
  header or its explicitly additive v3 header. They do not infer schemas from
  similar column names or reorder historical columns.
- `upgrade_v2_to_v3()` is the only supported fast-reference upgrade. The
  caller must supply artifact authority, backend/profile identity, structured
  provenance, component/layout hashes, unit/sign conventions, reproducibility,
  and tolerance metadata. The upgrader preserves v2 values and refuses to
  invent seeds, dependency versions, source evidence, candidate diffs, or
  acceptance metadata.
- Schema-3 CSV output appends its discriminator fields and emits named
  sidecars plus a content-addressed artifact manifest; it does not mutate the
  v2 file in place.
- Native-versus-HCIPy comparison baselines are a separate version-1 family and
  never masquerade as fast-integration records.

Baseline generation always targets a separate candidate directory and writes
a reviewable diff. Acceptance is a distinct command requiring a reason and
review reference. Tests, examples, and notebooks cannot overwrite accepted
resources. The complete field, authority, and command contract is in
[`artifact_schemas.md`](artifact_schemas.md).

## Current documentation map

- [`architecture.md`](architecture.md) — current package dependencies,
  runtime, calibration, backend, and artifact flows.
- [`backends.md`](backends.md) — public protocols/result fields and the exact
  native/HCIPy boundary.
- [`provenance.md`](provenance.md) — source classes and public-data versus
  synthetic interpretation.
- [`reproducibility.md`](reproducibility.md) — named random domains, replay,
  hashes, and environment evidence.
- [`validation.md`](validation.md) — internal, regression, cross-backend, and
  limitation claims.

Historical notebook numbers and root modules remain useful migration evidence,
but they are not the architecture. Current user-facing notebooks live under
`notebooks/tutorials`, `notebooks/studies`, and `notebooks/experimental` and
call installed package APIs.
