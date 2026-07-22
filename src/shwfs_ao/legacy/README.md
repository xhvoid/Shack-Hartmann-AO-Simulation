# `shwfs_ao.legacy`

This package holds the historical implementations that the refactor relocated
out of the flat top-level layout. It is **not** a second production
implementation of any physical model. Everything here is one of two things:

1. **Thin compatibility facades** — modules that only re-export names from a
   canonical `shwfs_ao` package so the historical public surface keeps working.
2. **Behavior-compatibility adapters** — modules that preserve a historical API
   shape or numerical ordering that has no drop-in canonical equivalent (for
   example the nm-unit detector integrator loop, or the notebook-11 aggregated
   science-diagnostic table). These delegate their physics to canonical
   packages; they own the *boundary conversion*, not the model.

`shwfs_ao.core` and any backend-independent canonical module must never import
from `shwfs_ao.legacy`. The sanctioned canonical importers of a legacy module
are `shwfs_ao.experiments.error_budget`, `shwfs_ao.experiments.integration`,
`shwfs_ao.experiments.scenario_instrument`, and `shwfs_ao.validation.checks`,
which still consume the behavior-compatibility adapter surface; those
dependencies are pinned in `shwfs_ao/resources/deprecation_inventory.json`
under `canonical_legacy_import_allowlist` and will be removed or relocated in
Phase B.

Importing `shwfs_ao.legacy.*` does **not** emit a deprecation warning during the
AO-REF-021 compatibility window. The warning-emitting deprecated surface is the
set of 19 root-level shim modules (`import dm_model`, etc.) and the
`ao_simulation_data` resource alias. See [`docs/migration.md`](../../../docs/migration.md)
for the replacement map and the deprecation clock.

## Module inventory

Generated classification lives in `deprecation_inventory.json`
(`legacy_modules[]`). Summary:

| Module | Kind | Canonical destination(s) |
|---|---|---|
| `ao_closed_loop` | behavior-compat adapter | `shwfs_ao.control`, `shwfs_ao.experiments.scao`, `shwfs_ao.dm`, `shwfs_ao.calibration` |
| `ao_conditions` | facade | `shwfs_ao.experiments.public_data_conditioned` |
| `ao_diagnostics` | behavior-compat adapter | `shwfs_ao.science.metrics`, `shwfs_ao.science.bandpass`, `shwfs_ao.core.wavefront` |
| `ao_error_budget` | facade | `shwfs_ao.experiments.error_budget` |
| `ao_integration` | behavior-compat adapter | `shwfs_ao.experiments.scao`, `shwfs_ao.io.artifacts`, `shwfs_ao.validation.regression` |
| `ao_validation` | behavior-compat adapter | `shwfs_ao.validation.physical`, `shwfs_ao.validation.regression` |
| `atmosphere_profiles` | behavior-compat adapter | `shwfs_ao.backends.native.atmosphere`, `shwfs_ao.io.configs`, `shwfs_ao.core.provenance` |
| `config_hashing` | facade | `shwfs_ao.core.hashing` |
| `data_sources` | facade | `shwfs_ao.io.public_data`, `shwfs_ao.core.provenance` |
| `dm_model` | behavior-compat adapter | `shwfs_ao.dm`, `shwfs_ao.backends.native.dm` |
| `interaction_matrix` | behavior-compat adapter | `shwfs_ao.calibration.interaction`, `.diagnostics`, `.reconstructors` |
| `phase_screen` | behavior-compat adapter | `shwfs_ao.backends.native.atmosphere`, `shwfs_ao.core.wavefront` |
| `psf_tools` | behavior-compat adapter | `shwfs_ao.backends.native.propagation`, `shwfs_ao.science.metrics` |
| `pwfs_forward` | facade | `shwfs_ao.experimental.pwfs` |
| `reconstruction` | behavior-compat adapter | `shwfs_ao.wfs.shack_hartmann.geometric`, `shwfs_ao.calibration` |
| `runtime_resources` | facade | `shwfs_ao.io.resources` |
| `shwfs_detector` | behavior-compat adapter | `shwfs_ao.detector`, `shwfs_ao.wfs.shack_hartmann.measurement`, `shwfs_ao.backends.native.shwfs` |
| `synthetic_instrument_data` | behavior-compat adapter | `shwfs_ao.detector`, `shwfs_ao.wfs.shack_hartmann.geometry`, `.measurement` |
| `zernike` | behavior-compat adapter | `shwfs_ao.backends.native.modes`, `shwfs_ao.core.wavefront` |
| `_control_adapters` | private behavior-compat adapter | `shwfs_ao.control` |
| `_interaction_adapters` | private behavior-compat adapter | `shwfs_ao.calibration` |
| `_reconstruction_adapters` | private behavior-compat adapter | `shwfs_ao.calibration` |

## Deliberately retained educational code

None. Every module above is a compatibility facade or behavior-compatibility
adapter scheduled for review at the Phase B removal boundary, not educational
reference code retained beyond it. The historical teaching notebooks live under
`notebooks/legacy/original_notebooks/`, outside the installed package.

If any module in this package is ever intentionally kept past Phase B as
educational reference, it must be recorded here with a reason and an owner, and
in `deprecation_inventory.json` under `retained_educational_code`.
