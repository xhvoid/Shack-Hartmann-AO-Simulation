# Original AO Simulation project integration

These are discovery hints for the repository in which this plugin was authored.
Resolve paths against the active repository. Verify current owners, versions,
selectors, and policy; this file is not a frozen baseline or a list of defects.

## Entry points

- `README.md`, `docs/README.md`, `docs/architecture.md`, `docs/backends.md`.
- `docs/validation.md`, `docs/provenance.md`, `docs/reproducibility.md`,
  `docs/artifact_schemas.md`, and `docs/migration.md`.
- `docs/current_limitations.md`: review its existing IDs against actual code;
  a snapshot can predate fixes or newly supported modes.
- `docs/refactor/PRE_REFACTOR_SCIENTIFIC_AUDIT_PROMPT.md`: the detailed pre-audit
  assignment, when that full assignment is actually requested. Its preparation
  revision is not a command to reset the current tree.
- `docs/refactor/CLEANUP_REFACTOR_EXECUTION_PROMPT.md` and
  `CLEANUP_REFACTOR_REVIEW_PROMPT.md`: cleanup contracts and post-change review.
  They do not authorize cleanup or require future deliverables in a pre-audit.

## Code and evidence discovery

The canonical package is under `src/shwfs_ao/`. Inspect `core`, `backends`,
`wfs`, `detector`, `dm`, `calibration`, `control`, `science`, `experiments`,
`validation`, `io`, and actual system construction owners as relevant. Resolve
these from the current tree; do not assume every name remains a directory.
Root modules and `legacy/` may be intentional compatibility adapters.

Include `scripts/`, current tutorial/study/experimental notebooks, packaging,
CI, tests, the experimental PWFS boundary, and analytical TIPTOP work when
the scope is a whole-repository audit. Distinguish historical notebooks and
saved outcomes from current executable routes.

Inspect `src/shwfs_ao/resources/resource_manifest.json`, benchmark source ledgers,
assumption ledgers, profiles, accepted baselines, and their tests. Compare camera,
atmosphere, telescope, and photometric parameter provenance to the referenced
source, rather than assuming all presets are measured hardware calibration.

## Important boundaries to verify

- SI OPD/phase/wavelength/sign ownership and DM surface versus reflected OPD.
- Stable lenslet/pixel/actuator identity, validity masks, finite rows, clipping,
  zero flux, and simulator-truth versus operating observability.
- Compatibility versus physical camera; raw/oracle/estimated processing;
  ADC on/off; nonuniform maps; covariance conditioning and calibration ensembles.
- Dense versus sparse objectives and damping units; no hidden densification.
- Delay, exposure integration, queued increments, leak, acknowledgement, and
  default versus optional recovery. Determine which mechanism actually acted.
- Peak versus on-axis Strehl, focal cropping, broadband grids, and intensity
  rather than mean-wavefront exposure integration.
- Code/config/response identities, RNG domains, resume rules, and cache reuse.
- Reported noise-law departures, failed hypotheses, and unexplained trends.
  Determine current evidence; do not silently reinterpret a negative result.
- Historical 42 m evidence is not fresh current-code or multi-seed validation.
  Historical review reproductions may assert an old defect; preserve originals
  and test current expected behavior in an audit-owned copy.

## Execution context

Read `tests/conftest.py`, current marker definitions, project instructions, and
the live resource policy before choosing commands. A starting bounded native
selection is `-m "not hcipy and not slow and not elt_scale"`; it is not complete
coverage and does not enable guarded tests.

The recorded project policy uses serial numerical jobs and two native threads.
Medium/12 m, any 42 m, long multi-seed batches, and expensive spectral studies
are governed runs. Confirm current policy and authorization; do not inherit
permission from an old enablement. Small fixtures, targeted native tests, and
bounded CI/2 m comparisons should proceed within active authorization.

The main project dependency environment and optional HCIPy/TIPTOP environments
may differ. Record actual imports and environment. Fresh wheel checks must run
outside the checkout; avoid changing the user's working installation.
