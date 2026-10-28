# Reproducibility

Reproducibility here means that a named configuration, dependency profile,
root seed, realization index, and input-resource set can be replayed according
to its documented contract. It does not imply that independently implemented
backends generate the same random field or that a reproducible synthetic model
is accurate for a real observatory.

## Named random streams

`shwfs_ao.core.random.NamedRandomStreams` derives independent NumPy
`Generator(PCG64)` instances from canonical JSON plus SHA-256. The frozen
derivation identifier is:

```text
shwfs_ao.random.sha256-json-pcg64-v1
```

Derivation never uses Python's process-randomized `hash()` and does not depend
on domain registration order. The default registry contains exactly six
top-level domains:

| Domain | Owner and lifecycle |
| --- | --- |
| `detector.realization` | `detector.DetectorRealization`; keyed creation of persistent PRNU/bad-pixel maps |
| `detector.shot_noise` | detector effects; persistent runtime generator beneath the current scope/frame |
| `detector.read_noise` | detector effects; independent persistent runtime generator |
| `calibration` | deterministic/keyed calibration-specific draws and identities |
| `atmosphere` | atmosphere realization screens keyed by realization index (and HCIPy layer index) |
| `ncpa` | reserved and identity-recorded domain for canonical NCPA ownership; the current legacy-compatible error-budget path still uses its explicit `resolved_ncpa_seed` rather than consuming this named generator |

Unknown domains fail. Extra application domains must be registered explicitly;
duplicate registration fails. Adding a domain does not perturb existing domain
streams.

### Persistent, keyed, and scoped access

- `generator(domain)` returns the same persistent generator on repeated
  lookup. Draws advance only that domain within that scope.
- `keyed_generator(domain, key=(...))` returns a fresh deterministic child.
  Creating or drawing from it does not advance the persistent domain stream.
- `scoped(scope, key=(...))` creates a deterministic view. A WFS may continue
  to request `detector.shot_noise`, for example, while calibration or a control
  frame isolates the request beneath its own scope/key.
- `stream_id(domain, key=())` records the derivation identity, not mutable RNG
  state. Results and artifacts store IDs, scopes/keys where applicable, the
  root seed, and the scheme identifier.
- `reset()` discards cached persistent generators. Repeating the same calls in
  the same order then replays their draws.

Boolean values are not accepted as integer keys or seeds. Keys are ordered
tuples of strings/integers, and root seeds are non-negative integers.

## Component replay rules

### Atmosphere

`AtmosphereModel.reset(realization_index=i)` returns the model to `t=0`.
Within one backend and frozen dependency environment, resetting to the same
index and replaying the same non-decreasing absolute time sequence is exact.
A stochastic model uses a different keyed atmosphere child for another index;
a deliberately supplied static OPD is realization-invariant and records that
fact.

Equal native and HCIPy root seeds do **not** mean equal phase screens. Each
backend replays itself; cross-backend atmosphere validation compares a declared
statistical estimator across multiple realizations unless both receive one
deliberately shared OPD cube.

### Detector

One `DetectorRealization` owns persistent PRNU and bad-pixel maps. In canonical
`persistent` PRNU mode those maps are created once and reused; temporal shot
and read noise use separate runtime domains. Adding a read-noise draw cannot
shift atmosphere, calibration, or shot-noise streams.

Historical profiles retain the explicit `per_frame_legacy` mode and legacy
draw order required by frozen seeded baselines. Reference/interaction
calibration uses scoped/keyed calibration children so it cannot advance runtime
detector generators. Switching a frozen profile from `per_frame_legacy` to
persistent PRNU is a numerical-model change requiring a candidate baseline and
rationale, not a documentation or structural cleanup.

`include_noise=False` disables temporal shot/read draws. It does not remove
persistent response/bad-pixel maps or the explicitly keyed compatibility
response used by legacy calibration.

### Calibration

Every probe/sign/repeat uses a stable calibration scope/key. Calibration
records stream references, amplitude, forward/central method, repeat count,
sensor/geometry/detector/DM hashes, row/coordinate layout, units, and matrix
hash. No calibration helper constructs a hidden global RNG or consumes runtime
atmosphere/detector state.

### Control and sweeps

The loop receives one `RandomStreams` provider whose root seed agrees with
`LoopConfig`. At every sweep point, random streams, atmosphere, controller, and
DM state are reset before replay. Gain/latency/photon/read-noise and gain-delay
results are therefore independent of scan-axis iteration order and reuse the
same atmospheric truth unless a new realization was explicitly requested.

An unusable measurement does not pause time: the controller enqueues a zero
increment, advances the latency queue, permits leak, and may release an older
increment. After the DM applies stroke/fault rules, controller state is
synchronized to the applied command. These frame semantics are part of replay,
not merely implementation detail.

## Versioned profiles, resources, and hashes

- System profiles are named, packaged, and schema-versioned. A profile name
  never means “latest defaults”; changing a numerical value creates a reviewed
  profile version.
- Runtime fixtures, profiles, schemas, and accepted baselines are loaded through
  `importlib.resources`. The checked `resource_manifest.json` stores the sorted
  logical name and SHA-256 of every canonical resource.
- Component hashes cover scientific configuration, ordered IDs, physical units,
  conventions, geometry/sampling, and provenance. Dedicated layout hashes cover
  measurement rows and actuator commands.
- Timestamps and output directories are not scientific config inputs. Artifact
  content hashes cover serialized output bytes separately.
- Native Python 3.10/3.14 and HCIPy Python 3.11 dependency resolutions are
  checked in under `constraints/`; accepted records carry the relevant
  constraint-file hash and backend versions.

## Artifact reproducibility record

Schema-3 fast-reference records require:

| Field | Meaning |
| --- | --- |
| `root_seed` | immutable experiment root seed |
| `rng_derivation_scheme_id` | exact named-stream derivation contract |
| `random_stream_ids` | domain/scope/key identities actually used |
| `python_version`, `numpy_version`, `shwfs_ao_version`, `backend_version` | execution environment |
| `constraints_sha256` | dependency-profile identity |
| `generator_version` | artifact generator identity/version |
| `source_commit` | source revision, nullable only for ordinary installed-wheel run results |
| `source_tree_clean` | explicit clean/dirty state for governed candidates/accepted baselines |
| `source_patch_sha256` | canonical tracked diff plus sorted untracked scientific-input evidence when dirty |
| `generated_at_utc` | UTC audit timestamp, excluded from scientific config hashes |

Candidates and accepted baselines require source revision/patch evidence that
ordinary installed-wheel `run_result` records may not have. The v2-to-v3
upgrader refuses to invent any of these values. See
[Artifact schemas](artifact_schemas.md).

## Practical replay checklist

1. Record the exact packaged profile name/version and all overrides.
2. Record the root seed, realization index, named-stream scheme/IDs, and time
   samples.
3. Record backend/package versions and the checked constraint-file hash.
4. Verify resource, component, row-layout, actuator-layout, and shared-fixture
   hashes before comparing metrics.
5. Run from a built, non-editable wheel with `PYTHONPATH` cleared when testing
   portability; editable installs can mask packaging omissions.
6. Write outputs only to a caller-owned directory. Never point an ordinary run
   at packaged accepted resources.
7. Generate a baseline candidate and diff separately; acceptance requires a
   reason and review reference.

## Reproducibility limits

- Exact seeded arrays are guaranteed only within the frozen numerical and
  backend environment named by the contract.
- Runtime and memory are platform-dependent and informational unless a
  separately approved platform envelope says otherwise.
- Independent native and HCIPy atmospheric screens are statistically, not
  pointwise, comparable.
- Fixed seeds make synthetic assumptions repeatable; they do not validate
  observatory performance.
