# Artifact schemas and baseline governance

Simulation and artifact creation are separate operations. Canonical experiment
APIs return in-memory results; `shwfs_ao.io.artifacts` writes only when a caller
supplies an `ArtifactConfig` with an explicit output directory. No core,
backend, detector, calibration, control, or science component discovers a
repository root or chooses an output path.

## Schema families

The installed schema resources are under
`shwfs_ao.resources.schemas` and read through `shwfs_ao.io.resources`.

| Schema resource | Name/version | Purpose |
| --- | --- | --- |
| `provenance.schema.json` | `shwfs_ao.provenance`, v2 | structured source class, note, identifiers, access/fallback state, references |
| `fast_reference_metrics.schema.json` | `shwfs_ao.fast_reference_metrics`, v3 | governed fast-integration run, candidate, or accepted-baseline metrics |
| `scenario_table_sidecar.schema.json` | `shwfs_ao.scenario_table_sidecar`, v3 | exact scenario CSV header/order/units/hash and run identity |
| `validation_table_sidecar.schema.json` | `shwfs_ao.validation_table_sidecar`, v3 | exact validation CSV header/order/units/hash and run identity |
| `runtime_table_sidecar.schema.json` | `shwfs_ao.runtime_table_sidecar`, v3 | exact runtime CSV header/order/units/hash and run identity |
| `artifact_manifest.schema.json` | `shwfs_ao.artifact_manifest`, v3 | content-addressed member list for one multi-file write |
| `cross_backend_baseline.schema.json` | `shwfs_ao.cross_backend_baseline`, v2 | strict accepted cross-backend baseline with full numerical input witnesses, separate from fast metrics |

Schema-v2 fast-reference JSON and CSV layouts remain compatibility contracts
even though no new v2 JSON Schema resource is added. They are read by the
explicit v2 reader and may still be emitted byte-compatibly during the
deprecation window.

### Current cross-backend baseline record

The AO-REF-018 version-2 runtime contract in
`shwfs_ao.validation.regression` is the canonical shape of this family.
Reports/baselines use `artifact_schema_name`, `artifact_schema_version`,
`comparison_config`, `root_seed`, `conventions`, `component_hashes`,
`fixture_hashes`, `numerical_inputs`, `environment`, and `comparisons`; an accepted baseline adds
`generator` and `acceptance`. The packaged `cross_backend_baseline.json` and
the candidate script use this contract, and the installed
`cross_backend_baseline.schema.json` describes the same shape, up to the JSON
Schema limits stated below: the packaged baseline validates against the
packaged schema, and CI enforces that cross-validation. An earlier draft of
the schema resource described a normalized
`schema_name`/`artifact_kind`/`shared_input_hashes` envelope that
no writer ever emitted; it was superseded by the runtime contract.

Each numerical-input witness contains its shape, losslessly compressed
little-endian float64 samples, data SHA-256, raw source hash and semantic
configuration hash. DM witnesses also include their canonical model and backend
configuration hash preimages, binding the source hash to the influence samples
and exact semantic fields (including reflective factors and array ordering).
Direct array fixture witnesses have no hash preimage (their raw hash is the
stable hash of the witnessed array), so both payload fields are `null`; DM
witnesses must carry both. Version 2 verifies complete arrays at fixed roundoff
tolerances across platforms while keeping scientific metric criteria unchanged;
version 1's exact hash gate incorrectly required identical low bits from
different math and FFT libraries. Existing version-1 documents require an
explicit regenerated and reviewed baseline; they are not silently upgraded, and
both the runtime validator and the schema gate refuse them by their version,
not by a missing version-2 field.

The schema states the witness shape per input: `null` payloads for fixtures,
non-empty payload strings for the DMs, padded standard base64 `data`, and
exactly 64-character hashes. It cannot state everything the runtime checks.
JSON Schema counts an integer-valued number such as `48.0` as an integer, so
the schema accepts it as a `shape` entry while the runtime requires a JSON
integer. The bound on the number of samples, the decoded data length and
`values_sha256`, and every binding between a raw hash, its preimage and the
witnessed array are checked only at runtime.

The strict schema pins the complete thirteen-kind comparison inventory in
canonical order, requires acceptance reason/review-reference/timestamp and
generator identity, forbids unknown fields everywhere except
`comparison_config` — which is an open record of the comparison's own inputs
and is pinned by its `config_hash` rather than by a field list — and constrains
every gating criterion (finite JSON numerics, non-negative absolute
tolerances, explicit range bounds, a `statistical_definition` on the
statistical comparison). Consumers load the packaged executable baseline
through `validation.regression.load_cross_backend_baseline()`, which applies
the same contract plus the range-ordering and value-finiteness checks JSON
Schema cannot express.

## Frozen schema-v2 compatibility

`read_v2()` requires `schema_version == 2` and the complete historical fast
metric set: workflow/preset/source fields, config hash, scenario identity,
open/closed piston-removed RMS (including tilt), H-band sampled-peak Strehl,
valid-centroid fraction, kept modes, validation
counts, runtime band/note, and tolerances. If `schema_name` is present it must
be `shwfs_ao.fast_reference_metrics`.

The scenario, validation, and runtime CSV readers accept only explicitly named
headers. The v2 scenario and validation column order is frozen; schema 3 may
only append the following four columns:

```text
artifact_schema_version, artifact_kind, backend, system_profile
```

`read_scenario_table()`, `read_validation_table()`, and
`read_runtime_table()` reject reordered, missing, guessed, or merely similar
headers. Existing columns and row order are not silently removed or renamed.

Version-2 integration output order is deterministic:

1. `{prefix}_error_budget.csv`;
2. `{prefix}_error_budget.png` when figures are enabled;
3. `{prefix}_validation.csv`;
4. `{prefix}_validation.png` when figures are enabled;
5. the explicit reference-metrics JSON when enabled.

JSON is sorted, two-space indented, finite-only, and ends with one newline.

## Additive schema 3

Schema 3 preserves the v2 scientific values and adds:

- an explicit artifact authority discriminator;
- backend and versioned system-profile identity;
- structured provenance;
- component and row/actuator-layout hashes;
- unit/sign conventions;
- a complete reproducibility record;
- per-metric tolerance units, kinds, enforcement flags, and rationale;
- exact CSV sidecars; and
- a sorted content-addressed artifact manifest.

Required component hash keys are `geometry`, `detector`, `wfs_calibration`,
`dm`, `interaction_matrix`, `command_projector`, `controller`, and
`science_sampling`. Required layout hashes are `measurement_rows` and
`actuator_commands`. Required conventions are `wavefront_unit`,
`command_unit`, `residual_definition`, and `measurement_unit`.

Top-level `source_class`/`source_note` are retained for compatibility and must
equal the structured provenance record. Conflicts fail instead of choosing one
representation. A legacy bare-hex `config_hash` is preserved byte-for-byte;
new component hashes may carry an algorithm prefix.

### Artifact authority

| `artifact_kind` | Required evidence | Forbidden evidence |
| --- | --- | --- |
| `run_result` | ordinary scientific/provenance/reproducibility identity; source revision may be null outside a checkout | candidate, diff, acceptance |
| `baseline_candidate` | candidate and diff metadata plus source commit, explicit clean/dirty state, and source-patch evidence | acceptance |
| `accepted_regression_baseline` | reproducible source evidence plus non-empty acceptance reason and review reference | candidate and diff |

An ordinary run cannot claim baseline authority, and a candidate cannot become
accepted merely because tests pass.

### CSV sidecars and manifest

Every schema-3 CSV sidecar records:

- schema name/version and artifact kind;
- CSV filename and SHA-256;
- exact ordered header;
- row count, semantic order key, and exact row order;
- unit for every field;
- backend/profile, component/layout hashes, provenance, and reproducibility;
- authority-specific candidate/diff or acceptance evidence.

The artifact manifest lists each member's filename, schema identity, size, and
content hash. It permits `source_commit = null` for an ordinary installed-wheel
run; it does not force baseline-acceptance fields onto normal output. Members
are recorded by filename beside the manifest, so a schema-3 configuration
whose `reference_metrics_path` lies outside `output_dir` is rejected before
anything is written.

## Explicit v2-to-v3 upgrade path

The only supported fast-reference upgrade is
`shwfs_ao.io.artifacts.upgrade_v2_to_v3()`. It first validates the v2 record,
then requires the caller to supply every value that cannot be inferred:

- `artifact_kind`, `backend`, and `system_profile`;
- structured `provenance`;
- complete `component_hashes` and `layout_hashes`;
- unit/sign `conventions`;
- complete `reproducibility` evidence;
- complete metric `tolerance_metadata`;
- candidate/diff or acceptance metadata when required by the chosen kind.

It never invents a root seed, dependency/backend version, source revision,
source patch, artifact kind, candidate diff, acceptance reason, or review
reference. Pre-existing fields that conflict with supplied metadata fail. All
v2 values except the enclosing schema-version discriminator are checked for
exact preservation after `read_v3()` validates the result.

```python
from shwfs_ao.io.artifacts import read_v2, read_v3, upgrade_v2_to_v3

legacy = read_v2("fast_reference_metrics.json")
upgraded = upgrade_v2_to_v3(
    legacy,
    artifact_kind="run_result",
    backend=backend_name,
    system_profile=profile_name,
    provenance=provenance,
    component_hashes=component_hashes,
    layout_hashes=layout_hashes,
    conventions=conventions,
    reproducibility=reproducibility,
    tolerance_metadata=tolerance_metadata,
)
validated = read_v3(upgraded)
```

CSV migration is likewise explicit: writers append the four schema-3 columns
and emit the corresponding sidecar. Readers do not infer a sidecar or upgrade a
legacy header heuristically. There is no automatic upgrade for an unknown
future schema version.

## Candidate and acceptance workflow

Accepted resources have one canonical editable location under
`src/shwfs_ao/resources/reference_metrics/`. The generated
`ao_simulation_data` compatibility tree is never edited. Tests, examples,
notebooks, and normal CI commands read accepted resources but never write to
them.

For the frozen fast schema-v2 compatibility baseline:

```bash
python scripts/update_fast_regression_baselines.py \
  --generate-candidate --candidate-dir /tmp/shwfs-fast-candidate
python scripts/update_fast_regression_baselines.py \
  --accept-baseline-update --candidate-dir /tmp/shwfs-fast-candidate \
  --reason "Reviewed physical change" --review-reference "PR-or-issue"
```

For the native-versus-HCIPy baseline (requires the HCIPy extra and constrained
environment):

```bash
python scripts/generate_cross_backend_candidate.py \
  --generate-candidate --candidate-dir /tmp/shwfs-cross-backend-candidate
python scripts/generate_cross_backend_candidate.py \
  --accept-baseline-update --candidate-dir /tmp/shwfs-cross-backend-candidate \
  --reason "Reviewed tolerance or model change" --review-reference "PR-or-issue"
```

Generation refuses packaged destinations and existing candidate files, writes
machine-readable and Markdown diffs, and does not accept. Acceptance never
reruns the experiment; it validates that the reviewed candidate/diff still
match, requires human metadata, and then updates only the named baseline. A
fast candidate whose reference JSON disagrees with its own CSVs
(reference-scenario metrics other than the rounded CSV row, or a
passing-check count the validation table contradicts) is refused before
anything is copied. CI
guards accepted-resource hashes and the complete worktree around tests,
examples, notebooks, and ordinary generators.

Both machine-readable diffs are content-complete, and the diff is the
acceptance gate: the fast diff records whole-file SHA-256 hashes of every
candidate and packaged file, and the cross-backend
`shwfs_ao.cross_backend_diff` document records SHA-256 hashes of the
candidate bytes and the current packaged baseline plus a complete
structural change list (tolerances, criteria, rationale, attribution,
hashes, environment, generator — not just metric values); since diff
schema version 2 it also summarises each numerical-input witness with its
largest sample change against the contract tolerance. At accept time
each script recomputes its diff from the files on disk and refuses when the
result differs from the reviewed diff, so any post-review edit to a
candidate, however small, forces regeneration and a fresh review. Neither
script accepts while pytest is running.

Acceptance evidence is persisted, not just printed. The cross-backend
baseline embeds its `acceptance` block (reason, review reference, UTC
timestamp). Fast-baseline acceptance writes
`reference_metrics/fast_baseline_acceptance.json`, a
`shwfs_ao.fast_baseline_acceptance` v1 record binding the reason and review
reference to the acceptance timestamp, the SHA-256 of every accepted
baseline file, and the SHA-256 of the reviewed diff.

Runtime and memory remain informational unless a separately approved,
platform-specific envelope says otherwise. A structural refactor with
unexplained baseline movement is a failure even if values happen to fit a broad
tolerance.
