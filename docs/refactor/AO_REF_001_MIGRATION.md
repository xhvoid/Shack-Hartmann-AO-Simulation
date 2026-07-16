# AO-REF-001 Package Migration

AO-REF-001 is a structural packaging migration. It introduces the installed
`shwfs_ao` namespace without changing the numerical models, public call
signatures, seeded behavior, resource payloads, or accepted baselines frozen by
AO-REF-000.

> Historical layout note: this document records the AO-REF-001 transition.
> AO-REF-012 subsequently makes `src/shwfs_ao/resources/` the sole canonical
> source tree and generates `ao_simulation_data` only in distribution build
> directories. Do not edit the old AO-REF-001 source path.

## Installation and version

The distribution name remains `shack-hartmann-ao-simulation`. The package
version is available from `shwfs_ao.__version__` and is derived from installed
distribution metadata rather than copied into another hard-coded constant.

```bash
python3 -m pip install -e ".[test]"
python3 -c "import shwfs_ao; print(shwfs_ao.__version__)"
```

Examples and maintenance scripts must be run after an editable or regular
installation. They no longer prepend the repository `src/` directory to
`sys.path`.

## Import compatibility

The existing top-level import paths remain installed, silent compatibility
paths. AO-REF-001 does not start their warning or removal clock. Each shim has
an explicit AO-REF-000-derived export list and delegates to exactly one
relocated implementation module.

| Existing installed import | Relocated implementation |
|---|---|
| `ao_closed_loop` | `shwfs_ao.legacy.ao_closed_loop` |
| `ao_conditions` | `shwfs_ao.legacy.ao_conditions` |
| `ao_diagnostics` | `shwfs_ao.legacy.ao_diagnostics` |
| `ao_error_budget` | `shwfs_ao.legacy.ao_error_budget` |
| `ao_integration` | `shwfs_ao.legacy.ao_integration` |
| `ao_validation` | `shwfs_ao.legacy.ao_validation` |
| `atmosphere_profiles` | `shwfs_ao.legacy.atmosphere_profiles` |
| `config_hashing` | `shwfs_ao.legacy.config_hashing` |
| `data_sources` | `shwfs_ao.legacy.data_sources` |
| `dm_model` | `shwfs_ao.legacy.dm_model` |
| `interaction_matrix` | `shwfs_ao.legacy.interaction_matrix` |
| `phase_screen` | `shwfs_ao.legacy.phase_screen` |
| `psf_tools` | `shwfs_ao.legacy.psf_tools` |
| `pwfs_forward` | `shwfs_ao.legacy.pwfs_forward` |
| `reconstruction` | `shwfs_ao.legacy.reconstruction` |
| `runtime_resources` | `shwfs_ao.legacy.runtime_resources` |
| `shwfs_detector` | `shwfs_ao.legacy.shwfs_detector` |
| `synthetic_instrument_data` | `shwfs_ao.legacy.synthetic_instrument_data` |
| `zernike` | `shwfs_ao.legacy.zernike` |

Existing user code should continue to use the top-level imports for now:

```python
import shwfs_ao
from ao_integration import IntegrationConfig, run_integration
```

Do not migrate user code to `shwfs_ao.legacy`. That namespace is an internal
staging area. Later tickets introduce canonical namespaced component APIs and
will document targeted replacements before any compatibility warning begins.

## Resource compatibility

The installed resource package name remains `ao_simulation_data`. Its canonical
source tree moves from repository `data/` to `src/ao_simulation_data/`, with all
AO-REF-000 resource payload bytes preserved.

Callers may continue to supply logical names such as:

```text
data/public/svo_2mass_h_direct.csv
data/reference_metrics/fast_reference_metrics.json
data/synthetic_presets/dm_2m_fast_gaussian.json
```

The resource adapter normalizes those names and reads installed files through
`importlib.resources`. Explicit absolute paths and existing local override
paths retain precedence. Installed execution does not require a repository
checkout or `.git` directory.

Maintenance destinations follow the new canonical source layout:

- reviewed public-cache refreshes write to `src/ao_simulation_data/public/`;
- explicitly accepted baseline refreshes write to
  `src/ao_simulation_data/reference_metrics/`;
- raw downloaded intermediates remain under the ignored `data/external/` work
  area;
- examples write generated metrics and figures to an output directory and do
  not overwrite packaged reference resources by default.

## Example and artifact behavior

There are still no installed console or GUI entry points. Repository examples
retain their existing top-level imports and can be invoked with
`python3 examples/<name>.py` after installation. Repository-derived output
defaults remain under `figures/detector_level_SCAO/`; the public-data overview,
public-data-informed scan, and fast integration also honor
`AO_DEMO_OUTPUT_DIR`. `AO_DEMO_REFERENCE_METRICS` remains an explicit override
for the fast integration output.

Public caches are opened by logical resource name, so running an example from a
non-repository working directory does not silently substitute synthetic filter
curves merely because the physical source assets moved.

## Verification contract

AO-REF-001 is complete only when all of the following hold:

- all 19 old top-level imports and `import shwfs_ao` succeed from editable and
  non-editable installations without new warnings;
- tests run with `PYTHONPATH` cleared and without pytest source-path injection;
- every example and maintenance script is free of `sys.path` mutation;
- a wheel and an sdist-built wheel contain the same `shwfs_ao`, shim, and
  `ao_simulation_data` logical resource manifests;
- packaged reference metrics, public SVO curves, atmosphere profiles, and DM
  presets load outside the checkout;
- the Python 3.10 and 3.14 constrained CI lanes remain green without numerical
  baseline changes.

The pre-migration inventory, exact exported namespaces, resource hashes, and
characterization fixtures remain authoritative in
[`AO_REF_000_COMPATIBILITY_CONTRACT.md`](AO_REF_000_COMPATIBILITY_CONTRACT.md).
