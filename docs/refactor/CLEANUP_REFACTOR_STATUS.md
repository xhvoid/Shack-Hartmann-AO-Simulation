# Repository consolidation: execution record

Plan: [`repository_consolidation_plan.md`](repository_consolidation_plan.md)
(prepared 2026-10-17 at `f09eb16`). Review assignment:
[`repository_consolidation_review.md`](repository_consolidation_review.md).

Started 2026-10-18 (Europe/Berlin). This file is the durable execution record:
what was done, why, which invariant each change protects, the commands run and
their results, and what remains. The final implementation is explained in
[`../technical_reference.md`](../technical_reference.md); this record explains
how the work happened.

- **Run identifier:** `2026-10-18-claude-2312502`.
- **Machine-readable evidence:** `outputs/cleanup_refactor/2026-10-18-claude-2312502/`
  in the execution checkout (ignored by git, as `outputs/` always is). The
  harness that produced every inventory, witness and benchmark is in its
  `harness/` directory.
- **Execution checkout:** the git worktree
  `.claude/worktrees/cleanup-refactor-exec` on branch
  `claude/cleanup-refactor-exec`, created from `main` at `2312502`. The user
  said that another agent works on similar tasks at the same time, so every
  edit happens in this isolated worktree and the main checkout
  (`/Users/xuhan/Documents/AO Simulation`) is left untouched. Its uncommitted
  inputs were copied byte for byte (SHA-256 recorded) into this worktree.
- **Committed at the user's request; nothing pushed, tagged or accepted.**
  On 2026-10-18 the user asked to commit the work so far on the branch above,
  authored by Xu Han only, together with the untracked author files the docs
  link to (`docs/current_limitations.md`, the three refactor prompts and
  `docs/repository_optimization_ticket.md`). `AO_REFACTOR_MASTER_TICKETS_REVISED.md`,
  `.agents/` and the Codex plugin source under
  `plugins/ao-simulation-research-validation/` are linked from no document and
  stay untracked. The S1 record is committed as produced.

## Summary

| Ticket | Status | Result |
| --- | --- | --- |
| CLN-00 | DONE | Entry state, environment, inventories (API, 34 profiles, 25 programmatic configurations, 4362 negative cases, 145 accepted resources, 73 evidence files, deprecation clock), 33 replay witnesses (bit-identical on repeat), entry regression 2151 passed / 18 skipped / 2 xfailed, baseline benchmarks |
| CLN-01 | DONE (reference completed in CLN-08) | Technical-reference outline with scope and capability inventory; current roadmap; limitations reconciled (16 IDs kept, LIM-17/18 added); historical/contract banners on 35 pages; README and docs index lead to the reference |
| CLN-02 | DONE | `--output-dir PATH` for the detector evidence runner (legacy default and `--output` file-name semantics kept), output location as header audit metadata, explicit no-op resume; responsibility map; no extraction (none reduces coupling or duplication); 5 new tests; all 148 saved protocol hashes and every saved summary recompute |
| CLN-03 | DONE | Record-schema history (version constants, implied pre-field values, per-version field sets, six frozen hash shapes) moved verbatim into the leaf module `io/_profile_schema.py`; `io/configs.py` imports it one way and re-exports the public constants; codec kept with the records (the config hash is the hash of the serialized mapping); all identities, 4362 rejection cases and 33 witnesses unchanged |
| CLN-04 | DONE | The seven pure SystemConfig-to-component translations moved verbatim (renamed without the underscore) into the leaf module `experiments/_component_configs.py`; `scao.py` imports them under its old private names; `detector_level.paired_noise_run` no longer imports `scao` privates; registry, attestation, calibration resolution and dispatch unchanged; 804 focused tests (with HCIPy) pass; identities and 33 witnesses unchanged |
| CLN-05 | DONE (no extraction justified) | Ownership of the five evidence families documented; the update scripts share names, not semantics (body similarity 0.14–0.37 apart from two trivial helpers); report and deliberate-failure witness identical before/after; 420 tests pass; accepted resources byte-identical |
| CLN-06 | DONE | Notebooks and examples use installed APIs (one documented exception: the separate TIPTOP study loads its own support module); notebook governance intact; wheel pins and docs graph follow the two new private modules; no tracked clutter exists, and the main checkout's ignored clutter was inventoried and retained; nothing deleted |
| CLN-07 | DONE (resource model written in CLN-08) | Interleaved A/B (baseline snapshot of `2312502` against the cleanup tree), 10 fresh-process timed runs per side and case: every build, per-frame, end-to-end and peak-RSS median within −3.6 % to +1.4 %; identical results; no regression to investigate |
| CLN-08 | DONE (reviewed; R-01–R-07 repaired) | `docs/technical_reference.md` complete (sections 1–9, 1083 lines): 11 method-family tables, compatibility matrix backed by 29 probed combinations (31 after the review), assumption and claim tables, 30-entry bibliography verified against Crossref/publisher pages, resource model; documentation number fixes U5 (wrong Oke & Gunn DOI), U6 (1.41 GiB, 84.0 s, 2.4 %) |
| CLN-09 | DONE: `PASS_WITH_DECLARED_VALIDATION_LIMITS` | independent reviewer (separate agent): first `CHANGES_REQUIRED` for R-01 (P2: the resource model omitted the end-of-run `LoopHistory` copies) and seven P3 precision findings, no code defect; R-01–R-07 fixed (U8, U9) and closed on recheck, R-08 deferred (roadmap G10) and accepted |
| CLN-10 | DONE (named lanes unavailable locally) | final native regression 2157 passed / 18 skipped / 2 xfailed (0 failed; +6 new tests, none removed); slow detector 16 passed; HCIPy 234 passed / 0 failed / 2 xfailed; ruff, mypy, generators clean; inventories, 33 witnesses, report witness and 29-case probe identical to entry; accepted resources unchanged; offline wheel/sdist gate passed (native bundle 1298 passed, HCIPy bundle 229 passed, examples and README smokes from the wheel) after F-08/U7, a pre-existing bundle-manifest gap |

## Change map, ownership map and retention log

Every change is on `claude/cleanup-refactor-exec`, relative to `2312502`
plus the copied entry inputs; `git diff 2312502` lists them. They were
working-tree changes until the user's commit request of 2026-10-18.

| Change unit | Files | Kind | Behavioural effect |
| --- | --- | --- | --- |
| U1 | `tests/backends/hcipy/test_hcipy_factory.py` | bounded test-fixture fix (F-01) | none on the package; the four HCIPy factory tests run again |
| U2 | `scripts/run_detector_level_evidence.py`, `tests/experiments/test_detector_evidence_runner.py` | CLN-02 runner change | `--output-dir`; two header audit fields; explicit no-op resume; protocol identities unchanged |
| U3 | `src/shwfs_ao/io/configs.py`, new `src/shwfs_ao/io/_profile_schema.py`, `tests/test_wheel_install.py` | structural (CLN-03) | none: identities, rejections and witnesses identical |
| U4 | `src/shwfs_ao/experiments/scao.py`, `src/shwfs_ao/experiments/detector_level.py`, new `src/shwfs_ao/experiments/_component_configs.py`, `tests/test_wheel_install.py` | structural (CLN-04) | none: identities and witnesses identical |
| U5 | `scripts/build_parameter_source_inventory_pdf.py`, `docs/ao_realistic_demo_parameter_source_inventory.md` and `.pdf` | documentation correction (F-04, wrong DOI) | none on results |
| U6 | `docs/eso_scao_benchmark.md`, `docs/notebook12_tiptop_portfolio_notes.md`, `docs/detector_model.md`, `README.md` (one paragraph) | documentation correction (F-05, F-06, F-07) | none on results |
| D1 | new `docs/technical_reference.md`, `docs/roadmap.md`, `docs/refactor/CLEANUP_REFACTOR_STATUS.md`; `docs/current_limitations.md`; `docs/README.md`; `README.md`; 35 banner insertions in older docs | documentation (CLN-01, CLN-08) | none |
| T1 | `tests/docs/test_documentation_contract.py` | new guard test | the reference's copy of the dependency diagram must equal the checked one |
| U7 | `tests/wheel_smoke/manifest.json`, `tests/docs/test_documentation_contract.py` | bounded packaging-test fix (F-08) | the portable bundle now carries the two examples the README's native smoke runs; a guard test requires every file a README command names to be in the bundle |
| U8 | `docs/technical_reference.md` §9.4, §9.6 | review repair (R-01, P2) | the resource model counts the end-of-run `LoopHistory` copies |
| U9 | `docs/technical_reference.md`, `README.md`, `docs/current_limitations.md` (LIM-17, LIM-18), `docs/roadmap.md` (G10), this record; `harness/combination_probe.py` (+2 cases) | review repairs (R-02 … R-07; R-08 deferred) | documentation precision only |

Two edited files already carried the user's own uncommitted changes at
entry: `docs/README.md` (modified) and `docs/current_limitations.md`
(untracked), so `git diff 2312502` mixes the user's work with this cleanup's.
Their entry versions (SHA-256 equal to the entry manifest) are in
`cln01/entry_copies/`, and the cleanup's own edits are
`cln01/docs_README_from_entry.diff` and `cln01/current_limitations.diff`.

**Old-to-new ownership.**

| Responsibility | Before | After |
| --- | --- | --- |
| Record-schema version constants, implied pre-field values, per-version field sets, frozen hash shapes | `io/configs.py` | `io/_profile_schema.py` (re-exported unchanged by `io/configs.py`) |
| Live configuration records, validation, catalogue, codec | `io/configs.py` | unchanged |
| Profile-to-component translations (`_target_rms_rad`, `_detector_config`, `_centroid_config`, `_validity_config`, `_dm_config`, `_loop_config`, `_exposure_keywords`) | `experiments/scao.py` (private) | `experiments/_component_configs.py` (same objects imported back into `scao` under the old private names) |
| `physical_detector_config`, assembly, registry, attestation, calibration resolution, dispatch | `experiments/scao.py` | unchanged |
| Detector evidence output directory | hard-coded `EVIDENCE_DIR` | `--output-dir` with the old default |

**Retained deliberately.** Root shims and `shwfs_ao.legacy` (the deprecation
clock forbids removal); `native_frozen_flow` and every early profile version;
the three baseline-update scripts as separate tools; the untracked author
files; the dated status records, apart from a banner; ignored clutter in the
main checkout; and every historical evidence record.
**Removed:** nothing.

## Execution policy in force

- **Resource policy (prompt section 5).** Numerical jobs run one at a time
  with `OMP/OPENBLAS/MKL/VECLIB_MAXIMUM/NUMEXPR_NUM_THREADS=2`. The detector
  development's 2026-10-15 instruction to suspend the resource guard and its
  2026-10-16 per-run enablements are historical context; they authorize nothing
  here. No medium/12 m, 42 m, >30 min multi-seed or high-cost polychromatic
  run is authorized for this assignment, and none was run. Bounded tests, 2 m
  and `ci`-tier fixtures and packaging checks proceed without a new approval.
- **Import resolution.** The shared virtual environment
  (`/Users/xuhan/Documents/AO Simulation/.venv`, Python 3.14.3) has an
  editable `.pth` entry pointing at the *main checkout's* `src`. Every command
  here therefore runs with `PYTHONPATH=<worktree>/src`, which precedes `.pth`
  entries, and every harness records the `shwfs_ao.__file__` it imported. The
  wheel checks (CLN-10) run outside the checkout with `PYTHONPATH` cleared.
- **Authorship.** If the user authorizes commits, they carry only the user's
  authorship and no AI trailer (the user's standing instruction).

## CLN-00 — Entry state and behavioral contract

**Status: DONE.** Evidence: `outputs/cleanup_refactor/2026-10-18-claude-2312502/cln00_entry/`.

### Entry identity

| Item | Value |
| --- | --- |
| Execution HEAD | `23125024e77769d067f53d837e035b340fc2139a` (`main`, "Add the Claude Code edition of the AO research and validation skills") |
| Preparation baseline | `f09eb16`; one intervening commit, `2312502` |
| Intervening diff | 26 files, all under `.claude/` and `plugins/claude/` (the Claude edition of the validation skills); no file under `src`, `tests`, `scripts`, `examples`, `docs`, `notebooks` or packaging changed (`intervening_diff_outside_plugin.txt` is empty), so the prompt's scope is unchanged |
| Main checkout uncommitted inputs | modified `docs/README.md`; untracked `AO_REFACTOR_MASTER_TICKETS_REVISED.md`, `docs/current_limitations.md`, `docs/repository_optimization_ticket.md`, the three refactor prompts, the Codex plugin source under `plugins/ao-simulation-research-validation/` and `.agents/plugins/marketplace.json` (29 files). All were copied unchanged into the worktree; `main_checkout_dirty_inputs_sha256.txt` holds their hashes. |
| Unmerged earlier cleanup work | `claude/bold-shirley-6f1e9f` (5 commits on `62c0092`: evidence-runner record I/O and protocol modules, `io/config_codec.py`, `experiments/scao_component_configs.py`, a status section) and `claude/trusting-bell-471569` (1 commit: historical banners and a roadmap). Neither is in `main`, and the prompt's baseline does not include them. They were read as prior art (their recorded constraints are used below); nothing was merged or cherry-picked. |
| Python | 3.14.3 (framework build), `/Users/xuhan/Documents/AO Simulation/.venv` |
| Key packages | numpy 2.5.0, scipy 1.18.0, matplotlib 3.11.0, pandas 3.0.3, pytest 9.1.1, jsonschema 4.26.0, hcipy 0.7.0, astro-tiptop 1.5.1, astro-p3 1.6.2, mastsel 1.5.2, ruff 0.15.22, mypy 2.3.0, build 1.5.0 (`pip_freeze.txt`) |
| Environment against the lock | **Not the CI lock.** `scripts/verify_environment_lock.py --constraints constraints/py314.txt` fails: numpy 2.5.0 against the pinned 2.5.1, pillow and platformdirs differ, and the environment carries the HCIPy/TIPTOP extras the native lock does not pin. `pip check` is clean. Local results are therefore evidence for this environment only; the locked CI lanes are recorded separately in CLN-10. |
| Host | Apple M1 Pro, 8 cores, 16 GiB, macOS 26.5 (25F71), arm64. Background load average about 3.4–3.9 from other host activity during every measurement. |
| Instructions | No `AGENTS.md` or `CLAUDE.md` in the repository. The user's standing instructions: no AI attribution in commits; no commit or push without explicit authorization. |

### Same-revision test evidence at entry

| Selection | Result | Wall time, peak RSS |
| --- | --- | --- |
| `-m "not hcipy and not slow and not elt_scale"` (2171 collected, 273 deselected) | **2151 passed, 18 skipped, 2 xfailed, 0 failed** | 426.5 s, 727 MiB (one process) |
| Full collection | 2444 tests: 2171 native, 236 HCIPy non-slow, 24 slow non-HCIPy, 7 `elt_scale` | — |

The 18 skips are 15 "requires an environment without the optional HCIPy
dependency" (HCIPy is installed here) and 3 "network namespaces are a Linux
facility". The two strict expected failures are the
`high_order_10m_geometric@3` and `high_order_10m_hcipy@3` stability guards.
These counts equal the historical post-fix record. That is a coincidence of
selection and environment, not a target. The per-test outcomes are in
`native_regression_junit.xml`, and the collected node IDs are in
`collect_native.txt` and `collect_all.txt`. The slow detector Monte Carlo and
the HCIPy selection were also run at entry; see below.

### Inventories

`harness/inventory.py` wrote `inventory_entry.json` (2.3 MB). CLN-10 compares a
fresh run against it section by section with `harness/compare.py`.

| Section | Content at entry |
| --- | --- |
| `api` | 130 `shwfs_ao` modules (none fails to import) and the 19 root shims. For each public name: kind, defining module/qualname, signature, bases, dataclass fields (order, defaults, flags), explicit `__hash_schema_id__`, and public members. The `ao_simulation_data` alias exists only in built wheels and is absent from this editable environment, which is recorded. |
| `profiles` | All 34 packaged profiles: `config_hash`, `observing_conditions_hash`, record schema, digest of the emitted mapping, exact round trip (all 34 equal), nested block hashes, the SCAO factory's derived component configurations, and the packaged resource digest. |
| `programmatic` | 25 documented programmatic configurations: the README's layered/kept-pixels examples, the ESO notes' HCIPy and rotated-wind examples, `with_magnitude`, `with_physics` cameras, the three recovery arms, `derive_physical_config` (12 m @1/@3, 42 m), the E6 monochromatic and photometry-matched arms, a gain change, and every ESO tier configuration. |
| `negative` | 4362 mutations of the packaged mappings (every schema version 0–8 on every profile, every deleted key to three levels, unknown keys at three levels, invalid scalars, invalid profile lookups). Each records the accepted hash or the exception class and message. Digest `f577034d…`. |
| `resources` | 145 tracked files under `src/shwfs_ao/resources` and `figures` (the CI accepted-baseline set, digest `084fcd3f…`); 79 resource-manifest entries checked against their bytes, with no mismatch; 73 files in the historical evidence directories. |
| `deprecation` | Clock: phase A, deprecation release 0.2.0 still `planned` (published 2026-07-18 as a plan), subsequent minor 0.3.0 unpublished, earliest removal date 2026-10-16. `removal_boundaries_satisfied(clock, 2026-10-18)` is **False**: the release boundary is open, so Phase B removal is not permitted. 19 root shims in the inventory. |

### Ownership classification at entry

| Class | Members | Note |
| --- | --- | --- |
| Canonical engine | `core`, `detector` (both chains), `wfs.shack_hartmann`, `dm`, `calibration`, `control`, `science`, `experiments.scao` (assembly and the shared runner), `io` | One implementation per responsibility. The shared loop is `control.loop.run_closed_loop`; `experiments.scao` assembles and verifies systems for it. |
| Backend alternative | `backends.native` (reference) and `backends.hcipy` (optional, lazy) | Independent optical implementations behind `core.protocols`; HCIPy is not a second engine for detector, calibration, control or science. |
| Numerical optimization (identity-neutral) | `backends.native.shwfs_batched`, `backends.native.dm_operator` with `wfs.shack_hartmann.compact_geometry`, `calibration.sparse` grouped probes, `experiments.calibration_cache`, `ScaoExecutionOptions` (`lenslet_batch_size`, `atmosphere_band_storage`, `telemetry_level`) | The batched optics, band regeneration, batch size and telemetry level are bit-identical execution choices. The sparse DM operator, grouped calibration and LSMR solver are a different model family (linear spline, damped objective) selected by schema-v5 `scalable`, not an optimization of the dense path. |
| Experiment wrappers | `experiments.detector_level`, `experiments.detector_noise`, `experiments.eso_scao_benchmark`, `experiments.error_budget`, `experiments.integration`, `experiments.physical_integration`, `experiments.public_data_conditioned`, `scripts/run_detector_level_evidence.py` | Define protocols and summaries over the canonical engine; they own no physics kernel. |
| Validation tools | `validation.physical`, `validation.checks`, `validation.cross_backend`, `validation.regression`, `validation.numerical_identity`, `runtime.resource_guard`, candidate/accept scripts | Governance and comparison; ordinary runs cannot accept a baseline. |
| Compatibility adapters | `shwfs_ao.legacy.*` (silent) and the 19 installed root shims (warn) | Kept under AO-REF-021; the deprecation clock forbids removal. `experiments.error_budget` adapts historical result shapes on purpose. |
| Experimental | `shwfs_ao.experimental.pwfs`, `notebooks/experimental/` | Frozen exploratory PWFS model; no validated closed-loop parity. |
| Analytical, separate | `notebooks/studies/12_TIPTOP_performance_modelling.ipynb`, `notebooks/studies/tiptop_support.py` | TIPTOP/P3/MASTSEL study with its own environment and validation JSON; not behind the SCAO contracts. |
| Archived | `notebooks/legacy/original_notebooks/`, `docs/ao_realistic_demo_*.md`, `AO_REFACTOR_MASTER_TICKETS_REVISED.md`, `docs/repository_optimization_ticket.md`, the AO-REF ticket notes | Migration and development history; not current execution routes. |

### Replay witnesses

`harness/witnesses.py` runs 33 small seeded witnesses and digests every array
of every result field by field: SHA-256 over dtype, shape and bytes.
Wall-clock and peak-RSS fields are excluded by name, and the excluded names
are recorded. Two complete passes at entry, `witnesses_entry_a.json` and
`witnesses_entry_b.json`, agree with **0 differences**, so every witness is
deterministic in this environment. The set:

| Family | Witnesses |
| --- | --- |
| Compatibility chain (default) | `fast_2m_detector@4` (60 frames), `@1` (schema 1, legacy atmosphere), `portfolio_2m_detector@4` (40), `research_2m_detector@1`, `eso_turbulence_2m_detector@1` (40), the README's schema-3 kept-pixels noise-on variant |
| Physical camera chain | CCD/EMCCD/CMOS/coupled-plane 2 m profiles (30 frames, seed 11); oracle products; `exposure_subsamples=2`; summary telemetry |
| Sparse scalable path | `eso_scao_smoke_5m_software@2` with the streamed long-exposure observer (science images and metrics digested); batch size 7 with regenerated atmosphere bands; `@1` |
| Recovery | `ci` geometry with the 12 m @3 physics at m_AB 8/11/12, reset on and off; @2 physics with the guarded-fallback and gain-schedule arms at m_AB 11; 2 m EMCCD at m_AB 8.5, where rejection is intermittent and the reset changes the trajectory (34 decayed frames), with the four policy settings (off, reset, guarded fallback, gain schedule): off and reset run loops, while guarded fallback and gain schedule with fallback are construction refusals (the subset fallback needs the sparse LSMR reconstructor), kept as error witnesses whose class and message are compared |
| Paired noise study | `paired_noise_run` on the 2 m EMCCD at m_AB 7 (seed 61); `science_run` (seed 12) |
| Construction and identity | repeated builds, a second loop on the same system, a fresh build and a supplied interaction matrix (`calibration.source="supplied"`) all give identical arrays; `SparseCalibrationCache` cold/warm reuse (1 miss, 1 hit, identical systems) |
| Optional backend | the ESO notes' 70-pixel `hcipy_layered` example (12 frames, reconstructor `min_valid_fraction=0.5` so the loop closes) |

The edge cases the earlier reviews fixed are covered by their own regression
tests: the raw-readout pedestal with a gain map (62c0092), covariance v2, the
internal-source products (R3/S1) and resume identity (R6/S2). Those tests run
in every regression.

### Baseline benchmarks (CLN-07 "before")

`harness/bench.py`: one discarded warm-up and five timed fresh processes per
case, run serially, with two native threads. `bench_entry.json` records every
run. Medians, with the minimum and maximum over the five timed runs:

| Case | Build incl. calibration | Per frame | Loop | End to end | Peak RSS |
| --- | --- | --- | --- | --- | --- |
| `fast_2m_detector@4`, 60 frames | 0.185 s [0.182, 0.193] | 20.92 ms [20.83, 20.97] | 1.255 s | 1.441 s | 116 MiB |
| `det_emccd_2m_synthetic@1`, 60 frames | 0.506 s [0.503, 0.528] | 22.28 ms [22.18, 22.52] | 1.337 s | 1.842 s | 122 MiB |
| `det_emccd_2m_plane_synthetic@1`, 60 frames | 0.704 s [0.700, 0.705] | 28.99 ms [28.90, 29.14] | 1.739 s | 2.444 s | 132 MiB |
| `eso_scao_smoke_5m_software@2`, 32 frames | 0.205 s [0.203, 0.213] | 22.81 ms [22.42, 23.08] | 0.730 s | 0.934 s | 128 MiB |
| same, with streamed long-exposure science | 0.204 s | 24.53 ms [24.33, 24.69] | 0.785 s | 1.074 s | 130 MiB |
| `ci` geometry with 12 m @3 physics, summary telemetry, 32 frames | 1.299 s [1.289, 1.306] | 32.54 ms [32.49, 33.03] | 1.041 s | 2.341 s | 154 MiB |

These are `MEASURED_CURRENT` values for `2312502` in the environment above.
Every repetition reproduced its configuration hash and its final residual
exactly. The component probe gives a per-frame breakdown, also in the record:
the `native_frozen_flow_v2` atmosphere sample costs about 15 ms of the 2 m
frames, and the WFS measurement 5.4 ms (compatibility), 6.8 ms (physical
FFT) and 13.3 ms (MFT plane).

### Entry finding and change unit U1 (bounded test-fixture fix)

**Finding F-01 (pre-existing, newly discovered).** At entry the HCIPy
selection (`-m "hcipy and not slow and not elt_scale"`) gave **4 failed,
230 passed, 2 xfailed** (`cln00_entry/hcipy.log`). All four failures are in
`tests/backends/hcipy/test_hcipy_factory.py` and share one cause. The fixture
`_tiny_hcipy_system_config()` builds a `SystemConfig` without naming a record
schema, so it takes the default, which `a31099b` raised to 7. `a31099b` also
added the schema-7 rule that an HCIPy detector-level record must use
`wfs.lenslet_axis="pixel_block_center"`, so the fixture, which keeps the
historical cell-centre axes, is now rejected:
`SystemConfigError: a schema-7 HCIPy detector-level record needs
wfs.lenslet_axis='pixel_block_center' ...`. The native selection never runs
these tests, and the eleven local commits since `origin/main` have not run in
CI, so the failure went unseen.

- **Classification:** test-fixture defect (engineering). No simulation code,
  profile, identity or result is affected; the schema-7 rule is intended
  (symmetric windows, `published_profile_window_bias.md`).
- **U1 (separate change unit):** the fixture now declares
  `record_schema_version=6`, the schema its contracts were written against,
  with a comment explaining why. The tested optics, including the cell-centre
  axes and the opt-in block-centred variant, are unchanged. Patch:
  `u01_hcipy_fixture/U1_hcipy_fixture.patch`. Reproduction: the entry log,
  copied to `u01_hcipy_fixture/reproduction_entry_hcipy_lane.log`.
- **Verification:** `tests/backends/hcipy/test_hcipy_factory.py`: 9 passed
  (`u01_hcipy_fixture/test_hcipy_factory_after.log`). The full HCIPy
  selection is rerun in CLN-10.

Slow detector Monte Carlo at entry (`-m "slow and not hcipy and not elt_scale"
tests/detector/test_noise_model.py`): **16 passed** in 8.0 s.

## CLN-01 — Scientific scope and documentation authority

**Status: DONE.** The technical reference itself is completed in CLN-08.
Evidence: `outputs/cleanup_refactor/2026-10-18-claude-2312502/cln01/`.

| Item | What was done |
| --- | --- |
| Technical reference | `docs/technical_reference.md` created with the complete section outline of prompt section 7. Section 1 (scientific purpose, the questions the implementation can and cannot answer, non-goals, kinds of use, evidence levels) and section 2 (a capability inventory for all eleven families: implemented, retained for compatibility, experimental, refused by the code, future work) were written from source and evidence before any implementation change. Selector vocabularies were taken from the `Literal` types and validation sets in `io/configs.py`. |
| Roadmap | `docs/roadmap.md`: two results kept visible (the pre-review 42 m realization; the failed 12 m pure 1/N_e test), eleven scientific items (S1–S11) and seven engineering items (G1–G7). Each has a question or problem, affected path, proposed experiment or change, evidence needed, success criterion, priority and cost category. A historical-plans section is included. Numbers were checked against the saved records: E5 started 2026-10-16 at 02:51 local time and was committed in `a31099b` at 07:50, with no code-identity field; at m_AB 11, damping alone gives 195.3 ± 4.8 nm, bit-identical to damping with reset, against 376.5 ± 88.3 nm for reset alone. |
| Limitations | `docs/current_limitations.md` reconciled with the current code. All 16 IDs and the author's concerns are kept. LIM-04 now describes `detector_covariance_v2` and the raw-readout fix. LIM-11 records that the detector work is complete but has not run in CI, with F-01. LIM-16 adds the opt-in recovery supervisor (it acts after the controller update, never clears the queue) and attributes the @3 improvement mainly to damping. New: LIM-17 (the 42 m noise-on result is one pre-review realization) and LIM-18 (the 12 m isolated noise departs from 1/N_e). The facts behind LIM-12–LIM-15 were rechecked in source: the zero-flux guards in native, batched, MFT and HCIPy optics, and window capture taken from noiseless optics. |
| Historical classification | Banners on the 21 AO-REF records (their contract statements remain, status lines are dated), the two development prompts, the two development status records and ten historical component notes. The generated `ao_realistic_demo_parameter_source_inventory.md` was left unchanged because `tests/test_inventory_consistency.py` pins it. The untracked author files `AO_REFACTOR_MASTER_TICKETS_REVISED.md`, `docs/repository_optimization_ticket.md` and `PRE_REFACTOR_SCIENTIFIC_AUDIT_PROMPT.md` were left byte-identical; they are classified in the roadmap and docs index instead. |
| Navigation | `README.md` points to the reference, roadmap and limitations, without a new bash block, because every README bash block needs a wheel-CI owner. The README's 42 m review-fix line said the result "comes from the reviewed code", which reads as if the result covered the fixes; it now says the result predates them and names the producing code (`a31099b`, 2026-10-16). `docs/README.md` gains a "Start here" section, separates current model notes (including the previously unlisted detector model) from historical component notes, labels the AO-REF pages as contract records, and links this execution record. |

**Checks.**
- Documentation and contract tests: `tests/docs`, `test_refactor_contract.py`,
  `test_refactor_characterization.py`, `test_inventory_consistency.py`,
  `test_ao_demo_skeleton.py`, `tests/notebooks/test_notebook_governance.py`:
  **92 passed** (`cln01/doc_contract_tests.txt`).
- Local links and anchors (`harness/check_links.py`, every tracked or
  untracked Markdown file): 106 files, 533 local links. The only failures
  are two pre-existing ones, in packaged resource READMEs
  (`src/shwfs_ao/resources/README.md` and `public/README.md`), whose
  `DATA_LICENSES.md` links do not resolve inside `src/`. Those files are part
  of the hash-governed resource set, so they were not edited. This is
  finding F-02, recorded for a governed resource update (`cln01/links_after.txt`).

No model, profile, identity or code changed in CLN-01.

## CLN-02 — Experiment protocol, identity and output responsibilities

**Status: DONE.** Change unit U2. Evidence:
`outputs/cleanup_refactor/2026-10-18-claude-2312502/cln02/` (patch
`U2_evidence_runner.patch`).

### Responsibility map

| Responsibility | `scripts/run_detector_level_evidence.py` | `experiments.detector_level` | `experiments.detector_noise` | `experiments.eso_scao_benchmark` |
| --- | --- | --- | --- | --- |
| Experiment definitions | subcommands and their fixed sets: profiles, gains, fluxes, cameras, magnitudes, seeds, recovery and excursion arms (`RECOVERY_ARMS`, `EXCURSION_ARMS`, `NOISE_ISOLATION_*`) | configuration variants (`with_magnitude`, `with_physics`, `with_matched_photometry`, `derive_physical_config`, `with_controller_gain`) | single-lenslet fixtures (`NoiseFixture`, `gaussian_spot`) | tiers (`BenchmarkTier`, `TIERS`) |
| Fixed protocols | frames, burn-in, execution options per series; predeclared in the detector status file | gain-scan selection rule (pole limit, tie tolerance, valid fraction) | trial counts and seeds per call | frames, burn-in, wavelengths per tier |
| Run identity | `run_protocol`: label, root seed, configuration hash with seed and frames, plus the shared protocol | `science_run` / `paired_noise_run` results carry configuration hash, seed and frames | fixture seed | manifest: configuration and component hashes |
| Code identity and source hashing | `code_identity`: git HEAD plus a digest of the uncommitted `src`/`scripts` diff and untracked files; part of the resume protocol | — | — | packaged resource and ledger digests (`_resource_sha256`) |
| Resume rules | `_gated_series`: every retained run, including other arms', must share the series protocol; runs of the plan must match their own protocol hash (R6, S2) | — | — | verified sparse calibration reuse (`SparseCalibrationCache`) |
| Aggregation | per-label `summarize_runs` after every run; refusal records | `summarize_runs`, `loop_summary` | `summarize_trials` | manifest metrics |
| Timings | record `wall_s`; per-run build/loop/per-frame and `ru_maxrss` from `science_run` | `science_run` | — | component timings and peak RSS in the manifest |
| Output selection | **new** `--output-dir PATH`; otherwise the legacy `docs/refactor/detector_level_evidence`; `--output` names a file; `--overwrite`; `--resume` | none (returns results in memory) | none | `--output-dir`, else `$AO_DEMO_OUTPUT_DIR/eso_scao_<tier>`, else `./eso_scao_benchmark_output` |
| CLI parsing | `main(argv)` | — | — | `_parser`, `main` |

**Extraction decision: none.** The mechanics that look shared differ in their
identity contracts. The detector runner's code identity is an input to its
resume protocol hashes. The cross-backend generator's `source_patch_sha256`
is a governed baseline field. The ESO benchmark writes its own manifest
schema. Merging them would either move recorded hashes or create the generic
workflow layer the prompt rules out. Inside the detector runner, the record
mechanics have a single consumer, and the R6/S2 guard tests load the script by
file and patch its globals. Splitting it would move code without reducing
coupling. The earlier unmerged attempt (`claude/bold-shirley-6f1e9f`) split
it into `records.py` and `protocols.py` plus an end-of-module import; that
was not adopted.

### Changes (U2)

- `--output-dir PATH` selects the record directory, created when needed.
  Without it, records go to `docs/refactor/detector_level_evidence` exactly
  as before, and `--output NAME` still names a file. `main` now takes an
  optional `argv`; called without it, it parses `sys.argv` as before.
- Every record header adds `output_directory` and `output_directory_source`
  (`--output-dir` or `legacy default`). The directory is recorded relative to
  the repository when it lies inside it (so a committed record carries no
  local checkout path; the saved detector records contain none) and as an
  absolute path otherwise. This is
  audit metadata only: protocol payloads, protocol hashes, configuration
  hashes and code identities are unchanged.
- A `--resume` whose planned runs are all recorded prints
  `... nothing ran and the record is unchanged.` and leaves the file
  byte-identical. Before, such a resume did nothing and said nothing.
- The module docstring documents the directory choice, the file-name
  semantics and the no-op resume.

### Checks

| Check | Result |
| --- | --- |
| `tests/experiments/test_detector_evidence_runner.py` + `test_detector_level_experiments.py` | **14 passed** (the 7 existing R6/S2 guard tests unchanged except that the fixture's option namespace gains `output_dir=None`) |
| New: explicit directory through `main(["--output-dir", ...])` for a one-shot record and a gated series; the redirected legacy directory is never created; protocol payloads carry no output field | pass |
| New: legacy default equals `docs/refactor/detector_level_evidence`; `--output` names a file in it; header says `legacy default` | pass |
| New: no-op resume message and byte-identical record | pass |
| New: an interrupted-then-resumed series has the same summary and protocol hashes as one invocation, and the summary equals `summarize_runs` over the runs | pass |
| New: every saved record in `docs/refactor/detector_level_evidence` recomputes: **148** stored protocol hashes (SHA-256 of key-sorted JSON) and every saved per-label summary (`summarize_runs`); reads only | pass |
| Real CLI run of `cost`: entry-revision script (exported to a temporary tree) against the new script with `--output-dir cln02/cli_after` | identical record structure (13 variants, the same row keys) plus the two header fields; the historical evidence directory is untouched (`git status` clean) |
| ruff on the changed files | clean |

The `cost` reruns also give current sensor-only timings for CLN-07. The 2 m
compatibility measurement takes 7.31 ms (historical anchor 7.25 ms), the
physical EMCCD 6.95 ms (6.83), oracle products 6.51 ms (6.48). Within each
variant the entry and new runs differ by −13 % to +9 %; a 20-frame median in
one process is that noisy, and both runs used identical `src`.

## CLN-03 — Configuration codecs and historical schema handling

**Status: DONE.** Change unit U3. Evidence:
`outputs/cleanup_refactor/2026-10-18-claude-2312502/cln03/` (patch
`U3_profile_schema.patch`, the new module as
`U3_new_module__profile_schema.py`).

### Ownership and import sketch

`io/configs.py` held five responsibilities: the live configuration records
and their validation, the cross-field and schema-7 rules, the packaged
profile catalogue and loader, the codec (`system_config_from_mapping`,
`system_config_to_mapping`), and the record-schema history.

```text
before:  io/configs.py  (records + rules + catalogue + codec + schema history), 2227 lines
after:   io/_profile_schema.py   leaf: stdlib dataclasses/typing only, 301 lines
             PROFILE_SCHEMA_NAME, PROFILE_SCHEMA_VERSION, SUPPORTED_PROFILE_SCHEMA_VERSIONS
             the schema v1-v7 history notes and the implied pre-field values
             the per-version field sets of every block (_SYSTEM_FIELDS ... _PHYSICS_PROCESSING_FIELDS)
             the frozen hash shapes: _AtmosphereConfigSchemaV3, _WfsConfigSchemaV1/V2/V3,
             _ControllerConfigWithoutRecovery, _DetectorPhysicsConfigWithoutCalibrationSource
         io/configs.py  records + rules + catalogue + codec, 1999 lines
             imports the names above from ._profile_schema (one direction, no cycle)
             and re-exports the three public constants through its unchanged __all__
```

**Why this boundary.** These are the facts that must never change once
published: which fields each record schema version has, which value an older
record implies for a field it predates, and the dataclass shapes earlier
blocks hash under. Isolating them makes the schema history append-only and
reviewable on its own. Every frozen shape pins `__hash_schema_id__` to the
name its live class carried, so moving it cannot move a hash.

**Why not more.** The codec cannot leave `configs.py` without a cycle:
`SystemConfig.config_hash` is the hash of `system_config_to_mapping(self)`,
and the codec constructs the records. The live records cannot move either,
because their hash schema id is `module.qualname` (`core/hashing.py`), so
moving a class would move every published identity. The earlier unmerged
attempt (`claude/bold-shirley-6f1e9f`, `io/config_codec.py`) moved the codec
and resolved the resulting cycle with an import at the end of
`configs.py`; that was not adopted, because the prompt asks for no new
import cycle.

### Checks

| Check | Result |
| --- | --- |
| Verbatim move | all 269 lines removed from `configs.py` appear unchanged in `_profile_schema.py`; the only lines added to `configs.py` are the import block and a two-line comment |
| Inventory, entry against after (`compare.py`) | `profiles` (34), `programmatic` (25), `negative` (4362 mutations with exception class and message), `resources` (145 + 73) and `deprecation`: **0 differences** |
| API inventory, baseline snapshot of `2312502` against after, with set constants canonicalized (a harness fix: set order depends on the per-process hash seed; two seeds on the baseline give 0 differences) | the only differences are the new private module `shwfs_ao.io._profile_schema` and six checkout-location path constants (`REPO_ROOT`, `SOURCE_REPOSITORY_ROOT`) that name where each tree lives; every public name, signature, dataclass field and hash schema id is unchanged |
| Replay witnesses (33), entry against after | **0 differences** |
| `tests/io`, `test_wheel_install.py`, `test_refactor_contract.py`, `test_refactor_characterization.py`, `tests/docs`, `tests/control/test_recovery.py` | **171 passed** |
| `generate_detector_level_profiles.py --check`, `generate_eso_scao_profiles.py --check` | both exit 0; no packaged resource changed |
| ruff (`src tests scripts examples build_support`), mypy | clean; mypy now checks 131 files (the new module) |
| Packaging | `tests/test_wheel_install.py` lists the new file in its wheel and sdist layouts; the built-wheel check is in CLN-10 |

## CLN-04 — System assembly and calibration resolution

**Status: DONE.** Change unit U4. Evidence:
`outputs/cleanup_refactor/2026-10-18-claude-2312502/cln04/` (patch
`U4_component_configs.patch`, new module `U4_new_module__component_configs.py`).

### Responsibilities in `experiments/scao.py` at entry

| Responsibility | Owner at entry | Decision |
| --- | --- | --- |
| Component assembly | `build_scao_system` | stays: the public API and the one place that orders construction |
| Backend registry and selection | `_FACTORIES`, `_FACTORY_EPOCHS`, `_REGISTRY_LOCK`, `register_scao_backend_factory`, `_factory_and_epoch`, the lazy built-in loaders | stays: one authoritative registry; tests patch `scao._FACTORIES` |
| Build attestation and supplied-system verification | `_BuildAttestation`, `_MINTED_ATTESTATIONS`, `_attested_build_identity`, `_verify_supplied_system`, `_expected_component_hashes` | stays: one attestation mechanism bound to the registry epochs |
| Configuration conversion | `_target_rms_rad`, `_detector_config`, `_centroid_config`, `_validity_config`, `_dm_config`, `_loop_config`, `_exposure_keywords`, `physical_detector_config` | **moved** (all but `physical_detector_config`), see below |
| Matrix acquisition and reuse | `_resolve_interaction_matrix`, `_resolve_sparse_interaction_matrix`, `_json_resource`, the sparse cache hand-off | stays: tests patch `scao.calibrate_interaction_matrix`, `scao.calibrate_sparse_interaction_matrix` and `scao._json_resource`, which must keep resolving in this module |
| Response checks | `_validate_matrix_response`, geometry check in `build_scao_system` | stays with acquisition |
| Reconstructor, projector and recovery construction | `_build_reconstructor`, `_build_command_projector`, `_build_recovery_policy` | stays: they raise `ScaoConstructionError` and read packaged mapping resources through `_json_resource` |
| Run dispatch | `run_closed_loop` | stays: the public API |

### Change (U4)

`experiments/_component_configs.py` is a new private leaf module. It holds the
seven pure translations, moved verbatim and renamed without the leading
underscore: `target_rms_rad`, `detector_config`, `centroid_config`,
`validity_config`, `dm_config`, `loop_config`, `exposure_keywords`. It imports
only `control`, `core.wavefront`, `detector`, `dm` and `io.configs`, all
existing package edges, and nothing from `scao`. `scao.py` imports the seven
functions under their historical private names (`_detector_config` and so
on), so its body and every test that calls `scao._detector_config` are
unchanged; the two imports the move left unused (`opd_to_phase`,
`LoopConfig`) were removed. `paired_noise_run` in `detector_level.py` used to
import `scao._exposure_keywords` and `scao._loop_config`; it now imports the
shared functions from the new module. `physical_detector_config` stays in
`scao.py`. It is a public function that raises `ScaoConstructionError` for a
profile without `detector_physics`, and moving it would require a cycle or a
different exception. The earlier unmerged attempt (`claude/bold-shirley-6f1e9f`,
`scao_component_configs.py`) moved it as well and closed the cycle with an
end-of-module import; that was not adopted.

### Checks

| Check | Result |
| --- | --- |
| Verbatim move | all 100 lines removed from `scao.py` appear in the new module, apart from the seven renamed `def` lines and the two dropped imports |
| `tests/experiments`, `tests/control`, `tests/calibration`, `tests/backends` (native and HCIPy), `test_wheel_install.py`, `tests/docs`, `test_refactor_contract.py`, `tests/io/test_configs.py`, with `-m "not slow and not elt_scale"` | **804 passed, 14 skipped, 4 xfailed, 0 failed**. The skips are the HCIPy-absent checks; the xfails are the two profile-stability guards and the two published-cell-centre HCIPy axis guards. This includes the attestation, registry, supplied-system, cache-reuse, factory and unsupported-combination tests, and `test_the_package_dependency_diagram_matches_the_real_import_graph` (no new package edge). |
| Inventory, entry against after | `profiles`, `programmatic`, `negative`, `resources`, `deprecation`: **0 differences** |
| API inventory, baseline against after | only the new private modules `shwfs_ao.experiments._component_configs` and `shwfs_ao.io._profile_schema`, plus the six checkout-location constants |
| Replay witnesses (33), entry against after | **0 differences**: construction repeatability, supplied matrix, verified cache reuse, recovery on/off and every physical and compatibility path select the same components and produce bit-identical results |
| ruff (repository config), ruff `--isolated --select F401` on the changed modules, mypy (132 files) | clean |

### Finding F-03 (pre-existing, tooling)

`pyproject.toml` ignores F401 for `"src/*.py"`, meant for the 19 root shims.
Ruff's glob `*` crosses directory separators, so the ignore covers every file
under `src/`, and the lint gate never checks unused imports in `shwfs_ao`.
`ruff check --isolated --select F401 src/shwfs_ao --exclude src/shwfs_ao/legacy`
at the entry revision reports four: `collections.abc.Callable` in
`backends/hcipy/factory.py`, `typing.Any` in `backends/native/modes.py`,
`dataclasses.field` in `calibration/sparse.py` and `core.hashing.stable_hash`
in `wfs/shack_hartmann/measurement.py`. All four look like plain leftovers,
but removing an import from a module without `__all__` can drop an implicit
re-export. The fix (scope the ignore to the shims, then review the four) is
recorded as roadmap item G8 instead of being folded into this structural
change.

## CLN-05 — Validation and artifact responsibilities

**Status: DONE; no extraction was justified.** No code changed. Evidence:
`outputs/cleanup_refactor/2026-10-18-claude-2312502/cln05/`.

### Ownership of the evidence families

| Family | Producer | Contract and schema | Accepted location and authority | Validation | Update tool |
| --- | --- | --- | --- | --- | --- |
| Fast regression (control-space proxy) | `experiments.integration` through `io.artifacts.write_integration_artifacts` | `shwfs_ao.fast_reference_metrics` v2 (frozen JSON and CSV headers) and additive v3 (authority, provenance, hashes, sidecars, manifest) | `resources/reference_metrics/fast_*` plus `fast_baseline_acceptance.json` (reason, review reference, file hashes, diff hash) | `io.artifacts.read_v2`, `read_v3`, the table readers, the script's candidate checks | `scripts/update_fast_regression_baselines.py` |
| Physical regression (von Kármán) | `experiments.physical_integration` | the same artifact family with `workflow = physical_integration` | `resources/reference_metrics/physical_*` and its acceptance record | the same, plus refusal of any other workflow label | `scripts/update_physical_regression_baselines.py` |
| Native versus HCIPy | `validation.cross_backend.run_cross_backend_report` | `shwfs_ao.cross_backend_baseline` v2: thirteen comparison kinds in order, lossless numerical-input witnesses with fixed roundoff tolerances, strict schema resource | `resources/reference_metrics/cross_backend/cross_backend_baseline.json` with an embedded acceptance block | `validation.regression` (document validators, `evaluate_report_against_baseline`) and `validation.numerical_identity` (witness encoding and DM payload binding) | `scripts/generate_cross_backend_candidate.py` |
| Detector-level evidence | `scripts/run_detector_level_evidence.py` | JSON records with per-run protocol identities (CLN-02) | historical evidence under `docs/refactor/detector_level_evidence`, not packaged and not a regression baseline | the runner's resume validation | none |
| ESO benchmark runs | `experiments.eso_scao_benchmark` | manifest JSON, telemetry and science `.npz` | caller-owned output directories; historical manifests under `docs/refactor/eso_scao_evidence` | manifest gates, the resource-guard supervisor | none |

**Decision.** The two regression tools look alike, but only by name. Over the
ten functions they share by name, body similarity (difflib ratio) is 0.14 for
candidate validation, 0.18 for the diff, 0.28 for its Markdown, 0.37 for the
acceptance record and 0.27 for `main`. It is high only for a two-line SHA-256
helper (1.00), a v2 table reader (0.84) and the packaged-destination refusal
(0.77). Sharing those helpers would couple two tools that
[validation.md](../validation.md) deliberately keeps separate ("so that
neither can move the other") without removing meaningful duplication. The
artifact and cross-backend validators look similar in places, but they raise
family-specific errors (`ArtifactError`, `BaselineContractError`), and
merging them would change exception types. Each family's semantics,
tolerances and authority therefore stay with their current owners. The
schema-v2/v3 readers, frozen headers, sidecars, witness coverage and
candidate-versus-accept separation are untouched.

### Checks

| Check | Result |
| --- | --- |
| `tests/cross_backend` (HCIPy installed), `test_baseline_update_guard.py`, `test_physical_baseline_update_guard.py`, `tests/io`, `test_validation_checks.py` | **420 passed, 1 skipped** (an HCIPy-absent check) |
| Representative report before/after (`harness/report_witness.py`): `run_cross_backend_report()` on the baseline snapshot of `2312502` and on the current tree, evaluated against the packaged baseline | identical: the same configuration hash, 13 comparison kinds, 52 gating metric values and an empty failure list (`report_witness_*.json`, 0 differences) |
| Deliberate failures, both trees | a one-sample change to the `atmosphere_opd_cube_m` witness is refused (`BaselineContractError: ... values_sha256 does not match its data`); a +0.5 change to `strehl_ratio/native_strehl` fails with observed, expected, tolerance, level and every component and fixture hash; a changed residual-sign convention stops evaluation ("the comparison basis differs, so metric tolerances do not apply"). Identical messages on both trees. |
| Accepted resources | byte-identical (the inventory `resources` section; CI's hash set of `src/shwfs_ao/resources` and `figures`) |

## CLN-06 — Examples, notebooks and navigation

**Status: DONE.** No file was deleted. The installed-wheel counterparts of the
canonical smoke routes are run in CLN-10.

| Item | Finding and decision |
| --- | --- |
| Notebook governance | `notebooks/notebook_manifest.json`: 11 canonical notebooks (5 `fast` tutorials, 4 `slow` studies, 1 `hcipy`, 1 `manual` experimental PWFS), 2 `manual` supplemental notebooks (the revised SH experiment and the TIPTOP study), and 16 archived originals in the `archived` class ("never executed"). `tests/notebooks/test_notebook_governance.py` passes (CLN-01). Historical outputs and classifications are unchanged. |
| Installed APIs | No canonical tutorial, study or example manipulates `sys.path`. The only notebook that does is the supplemental `12_TIPTOP_performance_modelling.ipynb`, which inserts `notebooks/studies` to import its own `tiptop_support.py`. It is the separate analytical study (manual class, its own Python ≥ 3.11 environment), so this is retained and documented rather than changed. |
| Duplicate calculations | None found that a canonical implementation could replace without changing units, inputs or intent; nothing removed. |
| Scripts as runtime dependencies | No module under `src/shwfs_ao` imports `scripts/` (one comment names a generator). |
| Example outputs | Every example writes to `$AO_DEMO_OUTPUT_DIR` when it is set, and CI always sets it to a temporary directory. When it is unset, most examples regenerate the tracked figures (`figures/detector_level_SCAO`, `figures/eso_elt_turbulence`). That is the documented way to refresh those figures, so it is kept; the risk of an accidental local overwrite is recorded as roadmap item G9. `run_detector_level_demo.py` and the ESO benchmark runner already default to local output directories. |
| Moved internals | `io/_profile_schema.py` and `experiments/_component_configs.py` are listed in `tests/test_wheel_install.py`'s wheel and sdist layouts. The package-level dependency diagram is unchanged, because neither module adds a package edge, and `test_the_package_dependency_diagram_matches_the_real_import_graph` passes. The technical reference describes both modules. |
| Clutter | `git ls-files` (664 files) contains no generated clutter: no `__pycache__`, `.DS_Store`, build products, egg-info, notebook checkpoints or archives. The main checkout's ignored, user-owned clutter was inventoried read-only: `build/` 5.3 MB, `readme-smoke-output/` 1.6 MB, `.mypy_cache` 38 MB, `.pytest_cache`, `.ruff_cache`, `__pycache__`, `.DS_Store`, `.ipynb_checkpoints`, `src/*.egg-info`, and 341 MB of earlier audit and review outputs under `outputs/`. It was **retained**: it is ignored by git and the user's to manage, the other agent is using that checkout now, and `outputs/` holds review evidence. |

## CLN-07 — Bounded performance and resource estimates

**Status: DONE.** The resource model, the historical anchors and the
scenarios are written in section 9 of the technical reference (CLN-08).
Evidence: `outputs/cleanup_refactor/2026-10-18-claude-2312502/cln07/`.

**Protocol (predeclared in `harness/bench.py` before any run).** There are
six cases: the compatibility profile, the physical EMCCD (FFT), the physical
coupled-plane EMCCD (MFT, three wavelengths), the CI sparse path with and
without the streamed science observer, and the CI geometry with the 12 m @3
physics and summary telemetry. Each case gets one discarded warm-up and five
timed repetitions, every one a fresh child process (so `ru_maxrss` is that
run's own peak), with two native threads, run serially. The phases do not
overlap: imports, `build_scao_system` (which includes calibration),
`run_closed_loop` (which includes any attached observer), and, after the
run, a separate component probe. CPU time is recorded beside wall time, and
the one-minute load average before and after every child. To separate code
effects from host drift, side A, an isolated `git archive` snapshot of
`2312502` (identical `src` to the entry state), and side B, the cleanup tree,
were measured in alternating passes A, B, A, B: ten timed runs per side and
case.

**Results** (medians, A / B (B/A)); every run reproduced one configuration
hash and one final residual per case, on both sides:

| Case | Build incl. calibration | Per frame | End to end | Peak RSS |
| --- | --- | --- | --- | --- |
| `compat_fast_2m_detector@4` | 0.190 s / 0.192 s (1.012) | 21.16 ms / 21.42 ms (1.012) | 1.458 s / 1.479 s (1.014) | 120 MiB / 120 MiB (0.997) |
| `physical_det_emccd_2m_synthetic@1` | 0.509 s / 0.509 s (0.999) | 22.43 ms / 22.49 ms (1.003) | 1.856 s / 1.856 s (1.000) | 125 MiB / 121 MiB (0.967) |
| `physical_det_emccd_2m_plane_synthetic@1` | 0.716 s / 0.706 s (0.986) | 29.40 ms / 29.18 ms (0.993) | 2.492 s / 2.457 s (0.986) | 136 MiB / 131 MiB (0.964) |
| `sparse_ci_smoke@2` | 0.205 s / 0.206 s (1.006) | 22.90 ms / 22.86 ms (0.998) | 0.940 s / 0.938 s (0.998) | 128 MiB / 128 MiB (0.998) |
| `sparse_ci_smoke@2_science` | 0.205 s / 0.205 s (0.998) | 24.50 ms / 24.78 ms (1.012) | 1.072 s / 1.081 s (1.008) | 131 MiB / 130 MiB (0.997) |
| `sparse_ci_physical_12m@3_summary` | 1.297 s / 1.301 s (1.003) | 32.80 ms / 33.00 ms (1.006) | 2.343 s / 2.357 s (1.006) | 154 MiB / 155 MiB (1.003) |

All ratios lie between 0.964 and 1.014, inside the spread of the runs (up
to about 20 % between extremes when the host load spikes). No metric comes
near the 10 % investigation threshold. The feature-off comparison of the
detector work is not affected: the compatibility profile changes by +1.2 %
in per-frame time, within noise. The A medians agree with the CLN-00 entry
measurements (`bench_entry.json`) to about 2 %, which shows the host drift
over the session. The host load average stayed at 2.6–4.1 throughout because
of other activity on the machine, so these are `MEASURED_CURRENT` values for
a loaded desktop, not a quiet one.

The structural changes (U3, U4) move code between modules without changing
any executed operation; a null result was expected and is what was measured.
Saved measurements: `bench_A_pass1.json`, `bench_B_pass1.json`,
`bench_A_pass2.json`, `bench_B_pass2.json`, `ab_summary.json` and `load.txt`.

## CLN-08 — Technical reference and bibliography

**Status: DONE** (reviewed in CLN-09; findings R-01–R-07 repaired by U8 and
U9). Stopped once at the usage limit on 2026-10-18 and resumed.

Done: the complete reference; docs and inventory-consistency tests (12
passed: 11 docs, 1 inventory) and links (239 local
links, 0 failures) on the new pages. Evidence in `cln08/`:
`combination_probe.json`, `independent_checks.txt` (0.618 limit, ESO derived
quantities, Noll), `historical_anchor_check.txt`, `memory_formulas.txt`,
`resource_inputs.txt`, the `--dry-run` estimates. Further findings:
F-05 full-tier peak documented as 1.44 GiB, record 1.41 GiB; F-06 TIPTOP
84.1 s against 84.03 s in the JSON; F-07 README's 2.1 % Monte Carlo figure is
the pre-review record (2.38 % on the current model). All three corrected in
current docs (U6); the dated ESO status record and the user's prompt were left
unchanged.

Drift guard (added on resumption):
`test_the_technical_reference_repeats_the_checked_dependency_diagram` in
`tests/docs/test_documentation_contract.py` fails if the reference's
dependency diagram differs from the checked one in `architecture.md`; docs
tests 12 passed (11 before it).

### Resume notes (closed)

1. ~~Add the diagram drift-guard test.~~ Done.
2. ~~CLN-09 independent review and repairs.~~ Done (see CLN-09).
3. ~~CLN-10 final verification and handoff.~~ Done (see CLN-10 and the
   handoff below).

### Change unit U5: a wrong DOI in the parameter-source inventory

**Finding F-04 (pre-existing documentation/provenance error).** The
generated inventory (`docs/ao_realistic_demo_parameter_source_inventory.md`
and `.pdf`, generator `scripts/build_parameter_source_inventory_pdf.py`)
cited Oke & Gunn (1983) for the AB convention as DOI `10.1086/113325`.
Crossref resolves that DOI to G. H. Smith, "The cyanogen inhomogeneity of NGC
362", AJ 88, 410 (1983). The Oke & Gunn paper is `10.1086/160817` ("Secondary
standard stars for absolute spectrophotometry", ApJ 266, 713, 1983), as the
detector source ledger (D5) already records; both lookups were made against
`api.crossref.org` on 2026-10-18. The fix corrects the two strings in the
generator and regenerates the Markdown and PDF through the generator's own
route. Against the committed versions, only the "Prepared" timestamp and the
two DOI occurrences change (extracted PDF text: 6 changed lines, still 7
pages). `tests/test_inventory_consistency.py` and
`tests/test_ao_demo_skeleton.py`: 5 passed. Patch and before/after files:
`u05_doi/`.

## CLN-09 — Independent review and bounded repairs

**Status: DONE — reviewer decision after recheck:
`PASS_WITH_DECLARED_VALIDATION_LIMITS`.**

A separate reviewer agent ran the review prompt with
`review/reviewer_brief.md` (started 12:53; stopped by the usage limit at
13:25 and resumed at 17:31; report written 17:35). It worked read-only on the
tree, wrote only under `review/`, and ran its own numerical checks only after
the wheel gate and the session-memory A/B had finished. Report:
`outputs/cleanup_refactor/2026-10-18-claude-2312502/review/review.md`, with its
reproductions `r01`–`r07`.

**Decision: `CHANGES_REQUIRED`** for one P2 finding in the resource model; no
defect in the code. The reviewer confirmed independently: every moved
definition is AST-identical to `2312502` and the same object under its old
name (r01, r03); pinned hash-schema ids, 44 historical profile hashes and 108
nested ESO hashes reproduce; no import cycle; HCIPy stays lazy; the built
wheel's 132 package files equal the tree; and on the final tree native 2157
passed (one in-checkout wheel-build test deselected), HCIPy 234 passed, slow
16 passed, ruff, mypy and both generators clean (r06). It agreed with the
session-memory attribution.

| ID | Severity | Finding | Verified by the implementer | Disposition |
| --- | --- | --- | --- | --- |
| R-01 | P2 | §9.4/§9.6 omitted the immutable copies `LoopHistory` makes at the end of a run, understating long-history memory about 2–2.5× | yes: `control/history.py` copies each history twice (`np.array(copy=True)`, then `tobytes`) in the order requested → applied → masks, while `run_closed_loop` still holds its arrays; peak `40·F·A + F·R`, then `32·F·A + 2·F·R` until return, `16·F·A + F·R` after; `telemetry_level` does not affect these arrays | **fixed, U8**: the table rows, the paragraph and the 20 000-frame scenario (1.94 GiB during the loop, about 4.6 GiB at the end, upper estimate about 5.8 GiB, above the 3.4 GiB available under pressure) |
| R-02 | P3 | the 42 m reference-tier command lacked the authorized budget the runner requires | yes: estimate with margin 3979.5 MiB, desktop budget ≤ 2 GiB; the recorded run used 4600 MiB with a note | **fixed, U9**: `--dry-run` first, `--authorized-budget-mib 4600 --authorization-note "…"`, and the refusal explained |
| R-03 | P3 | "Monte Carlo within 2.1 %" is the pre-review E1 value | yes: 2.15 % (`det07_e1_centroid_noise.json`) and 2.38 % (`_review.json`) | **fixed, U9**: "within 2.4 % (review rerun; 2.15 % before the review)" in three places |
| R-04 | P3 | estimator total 1.77 GiB should be 1.72 GiB (margin 3.45 GiB) | yes: 1 851 192 968 B; `ci` and `medium` totals were right | **fixed, U9** |
| R-05 | P3 | E5's code was attributed to `a31099b` by inference | yes: no `code_identity` in the record; run 02:51–03:50, commit 07:50 | **fixed, U9**: README, LIM-17 and the reference say "uncommitted development tree; code identity not recorded; first committed in `a31099b`; configuration hash equals the current profile's" |
| R-06 | P3 | "2.7 SE" quoted without its convention | yes: the dated detector record states a weighted fit and χ²/dof 2.50 | **fixed, U9**: the reference, LIM-18 and README name the unscaled weighted-fit SE and χ²/dof, give the scaled 1.7 SE, and keep the recorded verdict |
| R-07 | P3 | (a) 1897 nm cited from the excursion record; (b) the probe had 29 cases, not 30, and two REJECTED rows were unprobed; (c) "all four policies" includes two refusal witnesses; (d) 21 AO-REF banners and 35 banner edits, not 19 and 33 | yes, each | **fixed, U9**: (a) pointer to `det_recovery_e3_12m_v2.json` `off m11`, with the excursion record's `strict` arm (1871 nm) named; (b) the probe gained the HCIPy `pyramid_like` DM and the schema-7 HCIPy cell-centred-axis cases, both refused as documented, the 29 earlier cases unchanged (`cln10_final/combination_probe_after_review.json`), and the counts were corrected; (c), (d) wording and counts corrected |
| R-08 | P3, pre-existing | the evidence runner writes a 2026-10-16 enablement note into new gated records started without `--enabled-by-user` | yes: `_gated_series` default, `e2-12m`, `V3_ENABLEMENT`, `e3-recovery`, `e3-excursion` | **deferred, roadmap G10**: audit metadata only (no identity changes), the documented commands pass the option, and a correct fix must decide how resumed historical series record their enablement, which changes the governed-run CLI beyond this cleanup |

Rechecks after U8/U9: docs and inventory-consistency tests 14 passed; links
on every Markdown file 549 local, only the two pre-existing F-02 failures; the
arithmetic of every changed figure recomputed (`40·F·A` = 448 MiB at 42 m and
2000 frames, 4.57 GiB at 20 000; 1765 MiB; 3979.5 MiB). No code changed, so
the regression, witnesses and wheel results stand.

**Closure (17:46).** The reviewer rechecked every finding on the repaired
tree (`git diff 2312502` SHA-256 `84f48dc9…d988`; the 132 package files still
byte-identical to the built wheel) and appended section 7 to `review.md`
without changing sections 1–6. Its closure checks: the runner's own preflight
and authorization check for R-02 (3979.5 MiB refused against the default
desktop budget, accepted under 4600 MiB; nothing built, `r08`); both new probe
cases reproduced without the harness (`r09`); every repaired figure
recomputed (`r10`; the 20 000-frame upper estimate is 5.75 GiB, 5.72 GiB from
E5's `ru_maxrss`, and inherits the sampling caveat of the supervised 1.64 GiB
peak); docs, inventory-consistency, notebook-governance and evidence-runner
tests 84 passed; links clean apart from F-02 (`r11`). R-01–R-07 **CLOSED**,
R-08 **DEFERRED (accepted)**. Updated decision:
**`PASS_WITH_DECLARED_VALIDATION_LIMITS`**; the CI lanes not available here,
the current-code 42 m rerun (S1), the 42 m ensemble (S2) and spatial
convergence (S3) stay declared and deferred. The decision is review evidence,
not permission to commit, accept baselines or run governed experiments.

## CLN-10 — Final verification and handoff

**Status: DONE**, with the locally unavailable lanes named below. Every
check ran on the final source; after the review only documentation and the
probe harness changed, and their checks were rerun.

All commands ran in this worktree with `.venv/bin/python` (Python 3.14.3,
macOS arm64), `PYTHONPATH=<worktree>/src` (checked: `shwfs_ao` resolves inside
the worktree), two native threads, serially. Evidence is in `cln10_final/`;
`run_final_checks.sh` is the exact script of the checks after the regression.

| Check | Command or selection | Result (entry → final) |
| --- | --- | --- |
| Native regression | `-m "not hcipy and not slow and not elt_scale"`, whole suite, one serial run | 2151 passed, 18 skipped, 2 xfailed → **2157 passed, 18 skipped, 2 xfailed**, 0 failed, 412 s. Collection 2171 → 2177: 6 added (the five runner tests of U2 and the diagram drift guard), 0 removed; no entry test changed outcome; the same 18 skips (HCIPy-absent and Linux-namespace tests) and the same two strict xfails (`high_order_10m_*@3` gain above the 0.618 limit) (`native_regression_compare.txt`) |
| Slow detector Monte Carlo | `-m "slow and not hcipy and not elt_scale" tests/detector/test_noise_model.py` | 16 passed → **16 passed**, the same 16 tests |
| HCIPy selection | `-m "hcipy and not slow and not elt_scale"` | 230 passed, 4 failed, 2 xfailed → **234 passed, 0 failed, 2 xfailed**; the only changes are the four U1 tests, failure → pass |
| Lint | `ruff check src tests scripts examples build_support` | All checks passed |
| Types | `mypy` (configured files) | no issues in 132 source files |
| Profile generators | `generate_detector_level_profiles.py --check`, `generate_eso_scao_profiles.py --check` | both exit 0, no output |
| Inventories against CLN-00 | `profiles` (34), `programmatic` (25), `negative` (4362 cases), `resources` (145 accepted + 73 evidence, 79 manifest entries checked, 0 mismatches), `deprecation` | **0 differences** |
| API against the `2312502` snapshot | `inventory.py --sections api` (`PYTHONHASHSEED=1` against the seed-0 baseline) | 8 differences, all expected: the two new private modules, and three checkout-location constants (value and hash each) that name where each tree lives; every public name, signature, dataclass field and hash schema id unchanged |
| Replay witnesses | the 33 CLN-00 witnesses | **0 differences** |
| Cross-backend report witness | `report_witness.py` against the `2312502` run of CLN-05 | **0 differences**: 52 gating values, 0 failures against the accepted baseline, and the same refusal of the three perturbed copies |
| Mode-combination probe | the 29 CLN-08 combinations | **0 differences** in outcome, stage and message (after the review: 31 cases, the two added ones refused as documented, the 29 unchanged) |
| Links | every tracked or untracked Markdown file | 106 files, 549 local links; the only failures are the two pre-existing F-02 links in packaged resource READMEs |
| Accepted resources and figures | `git diff 2312502 -- src/shwfs_ao/resources figures`, untracked check | unchanged; nothing untracked |

**Offline wheel/sdist gate** (`harness/wheel_gate.sh`, mirroring the CI wheel
and HCIPy lanes as far as one local Python allows; log
`cln10_final/wheel_gate/steps.log`). The build used the installed setuptools
83.0.0 and `build` 1.5.0 without isolation (no network). Each test venv was
created from the base Python 3.14.3 outside the checkout, its dependencies
taken read-only from the existing `.venv` through a symlink farm that leaves
out the editable `shwfs_ao` install (and, for the native venv, HCIPy), and the
built wheel was installed with `--no-deps --no-index`; `PYTHONPATH` empty.

| Step | Result |
| --- | --- |
| Build sdist and wheel; rebuild a wheel from the sdist; `inspect_wheel_contents.py` | all exit 0: the wheel matches its sdist rebuild and carries the compatibility modules and resources (315 files, both new private modules included) |
| Native venv | `shwfs_ao` 0.1.0 imported from the venv's site-packages; HCIPy not importable; `pip check` clean |
| Native bundle tests, read-only bundle, `-m "not hcipy and not slow"` | 1314 collected: **1298 passed, 17 skipped**, 0 failed (skips: seven HCIPy-only modules not in a native bundle, source-checkout-only checks, `elt_scale` guard) |
| Examples from the wheel (`run_psf_strehl_demo.py`, `run_shwfs_centroid_demo.py`, `run_fast_integration.py`) | all exit 0 |
| README native smoke from the wheel | **failed, exit 2: finding F-08** (below). After U7, with a bundle prepared from the fixed manifest: **exit 0**, all six native README commands executed from the installed wheel (`steps_u7.log`, `readme_native_u7.log`) |
| HCIPy venv (HCIPy 0.7.0) | `pip check` clean; HCIPy bundle `-m "hcipy and not slow"`: 229 collected, **229 passed**; the native selection in the same venv, as CI also runs it: **1290 passed, 24 skipped** (15 of them need HCIPy to be absent) |
| README HCIPy smoke from the wheel | exit 0: every gating comparison within the accepted baseline tolerances |
| Accepted resources and figures before/after | unchanged |

**Session memory.** The final regression's pytest process reached a peak
memory footprint of 982 MB against 753 MB at entry (on macOS `time -l`
reports the process's own footprint separately from the maximum resident set
size, which includes waited-for child processes). To attribute it, the same
final test tree ran twice in fresh processes, once importing the `2312502`
package source and once the final source, recording each rise of the
process high-water mark per test (`cln10_final/session_memory_ab/`, ~14 min):
962 MB against 984 MB (+2.3 %, one sample per side). On both sides the
high-water mark is set by the same two science tests the cleanup does not
touch (`test_tiptop_support` annular Airy, +247/+268 MB; the 16× Airy-FWHM
convergence case of `test_metrics`, +116/+144 MB). The entry-to-final session
difference is therefore not attributable to the package code; the controlled
fresh-process benchmarks of CLN-07 remain the memory evidence. The
`2312502` side's 23 failures are provenance checks that refuse a package
imported from outside the git checkout, as expected for that setup.

One change after the regression: the U2 header field `output_directory` stored
an absolute path, which would have written the local checkout path into
committed evidence records (the saved detector records contain none). It is
now recorded relative to the repository when the directory lies inside it
(absolute only for a directory the caller chose outside). The runner tests
were rerun on the final tree (12 passed, including a new assertion for the
relative form), with ruff and mypy clean; nothing else depends on the script.

### Finding F-08 and change unit U7 (bounded packaging-test fix)

**F-08 (pre-existing, newly discovered; CI-visible).** The README's native
smoke (`scripts/run_readme_smoke.py --section native --require-wheel-bundle`,
run from the portable bundle exactly as the CI wheel lane does) failed with
exit 2: the README runs `examples/run_eso_scao_benchmark.py` (lines 390–391,
added in `2e96d86`) and `examples/run_detector_level_demo.py` (line 545, added
in `a31099b`), but `tests/wheel_smoke/manifest.json` never listed either
example, so the bundle does not contain them
(`cln10_final/wheel_gate/readme_native.log`: "can't open file …
examples/run_eso_scao_benchmark.py"). `2e96d86` is on `origin/main`, so the CI
step "Execute README native commands from the clean wheel" would fail there
the same way (inferred from that revision's README and manifest; no CI log
was inspected); `a31099b` is among the 11 local commits not yet pushed. The documentation contract only checked that the README
and the smoke runner are in the bundle, not the files its commands run.

**U7.** Two manifest entries (`kind: example`, no requirements; both examples
import only `shwfs_ao` and are desktop safe, a few seconds each) and a guard
test, `test_every_file_a_readme_command_runs_is_in_the_wheel_smoke_bundle`,
which requires every example, script, notebook or test a README command names
to be a manifest entry, and a native command not to need HCIPy. Checks: docs
tests 13 passed; the same check against the `2312502` manifest reports exactly
README lines 390, 391 and 545; ruff clean. The README native smoke is rerun
from the installed wheel with a bundle prepared from the fixed manifest
(`cln10_final/wheel_gate/steps_u7.log`, `readme_native_u7.log`): exit 0,
all six native README commands executed.

Unavailable locally (CI follow-up, not claimed as passed): Python 3.10
(source and wheel lanes) and 3.11 (the HCIPy lane) are not installed; the
local `.venv` is Python 3.14 but not the exact `constraints/py314.txt` lock
(it carries extra packages; `cln00_entry/env_lock_py314.txt`); notebook
execution needs Linux network namespaces and a registered Jupyter kernel,
which this macOS machine lacks and which would change the user's Jupyter
configuration.

## Final handoff

1. **Responsibilities that changed, and the routes that remain.** The
   record-schema history (version constants, implied pre-field values,
   per-version field sets, frozen hash shapes) moved verbatim from
   `io/configs.py` to `io/_profile_schema.py`; the seven pure
   profile-to-component translations moved verbatim from `experiments/scao.py`
   to `experiments/_component_configs.py`. Both are imported back under their
   old names, so every public route (`shwfs_ao.io.configs`,
   `shwfs_ao.experiments.scao`, `build_scao_system`, `run_closed_loop`, the
   root shims and `shwfs_ao.legacy`) is unchanged; no class identity or hash
   schema id moved. The detector evidence runner gained `--output-dir` (old
   default kept), two audit header fields and an explicit no-op resume. Bounded
   repairs of pre-existing defects: the HCIPy test fixture (U1) and the
   wheel-smoke bundle manifest with its guard test (U7). Nothing was deleted.
2. **Where the documents are.** The single reference is
   [`docs/technical_reference.md`](../technical_reference.md): method-family
   comparisons in section 5, compatibility matrix and representative runs in
   section 6, assumptions, claims, evidence and limitations in section 7,
   bibliography and traceability in section 8, the cost model in section 9.
   Roadmap: [`docs/roadmap.md`](../roadmap.md). Limitations:
   [`docs/current_limitations.md`](../current_limitations.md). Execution
   record: this file. Evidence and review:
   `outputs/cleanup_refactor/2026-10-18-claude-2312502/` (ignored by git).
3. **Checks on the final tree.** Native regression 2157 passed, 18 skipped,
   2 xfailed (2158 with the U7 guard), 0 failed, no test removed; slow
   detector 16 passed; HCIPy 234 passed, 0 failed, 2 xfailed (the four entry
   failures fixed by U1); ruff, mypy (132 files) and both generator checks
   clean; docs tests 13 passed; links clean apart from the pre-existing F-02.
   Offline wheel/sdist gate from an installed wheel outside the checkout:
   native bundle 1298 passed, 17 skipped; HCIPy bundle 229 passed; the native
   selection in the HCIPy venv 1290 passed, 24 skipped; three examples and
   both README smokes pass (the native one after U7). The reviewer reran the
   native, HCIPy, slow, lint, type and generator checks itself. No unexpected
   skip or failure remains. **Unavailable here:** Python 3.10 (source and
   wheel lanes), Python 3.11 (HCIPy lane), the exact constraint-locked
   environment and notebook execution (Linux network namespaces) — roadmap G1.
4. **Identities and resources.** Against CLN-00: profiles (34), programmatic
   configurations (25), 4362 rejection cases, 145 accepted resources and 73
   evidence files, deprecation clock: 0 differences; public API 0
   differences; 33 replay witnesses, the cross-backend report witness and the
   29 original mode combinations identical; accepted resources and figures
   byte-identical. Measured performance: every A/B median within −3.6 % to
   +1.4 % (CLN-07); the pytest-session memory rise is not caused by the
   package code (session-memory A/B).
5. **Review, limits and what is still needed.** Independent review:
   `PASS_WITH_DECLARED_VALIDATION_LIMITS` after repairs U8 and U9; R-08
   deferred as G10. Findings of this cycle: F-01 (U1), F-04 to F-08 (U5, U6,
   U7) fixed; F-02 (packaged README links, a governed resource update) and
   F-03 (lint scope, G8) open, as is G9. Model boundaries are unchanged and
   stated in the limitations (LIM-01 … LIM-18). Deferred governed experiments:
   S1 (current-code 42 m rerun), S2 (42 m ensemble), S3 (spatial
   convergence). The next prioritized scientific task is **S1**, which needs
   the user's explicit go-ahead (one 42 m realization, about 1 h and 1.6 GiB).
   Nothing was committed at the handoff, and the commit composition was
   left to the user because the docs index and the roadmap link to untracked
   author files. (2026-10-18, later: the user asked to commit the work so far
   with those linked files; see the header.)

## Follow-up: open items and the large experiments (2026-10-18, evening)

On 2026-10-18 the user asked to conduct the large experiments, to fix the
items left open, and whether the CI lanes could run in a cloud session.

### Change units for the open items

| Unit | Item | Files | Change | Checks |
| --- | --- | --- | --- | --- |
| U10 | G10 (review R-08) | `scripts/run_detector_level_evidence.py`, `tests/experiments/test_detector_evidence_runner.py` | The historical 2026-10-16 default notes are gone. A gated run that would execute anything needs `--enabled-by-user` and otherwise raises `EnablementMissing` before running; `e2-12m` likewise. A resume keeps the series' original note and appends its own to `resumed_enabled_by_user`; a resume with nothing to run needs no note. | 16 runner tests (4 new: refusal without a note; the real `e5` and `e2-12m` commands refuse before building; resume note history; no-op resume without a note) |
| U11 | G8 (F-03) | `pyproject.toml`; `backends/hcipy/factory.py`, `backends/native/modes.py`, `calibration/sparse.py`, `wfs/shack_hartmann/measurement.py` | The F401 ignore lists the 19 root shims by name (ruff's `*` crosses `/`); four unused imports removed (`Callable`, `Any`, `field`, `stable_hash`), none in its module's `__all__` or imported through it | ruff clean; an unused import fed to ruff under a package path is now reported, under a shim or `legacy/` path still exempt; mypy clean |
| U12 | G9 | ten `examples/*.py`, `tests/test_examples_output_dir.py`, `docs/getting_started.md`, `docs/eso_elt_turbulence_model.md` | Examples default to the git-ignored `outputs/examples/detector_level_SCAO` (or `.../eso_elt_turbulence`); refreshing a tracked figure needs an explicit `AO_DEMO_OUTPUT_DIR`. The public-data demo names its missing prerequisite instead of a bare `FileNotFoundError` | new static test (no default under `figures/`; fails on the `2312502` defaults) |
| U13 | F-02 | new `src/shwfs_ao/DATA_LICENSES.md`, `pyproject.toml` package data, `MANIFEST.in`, `tests/test_wheel_install.py`, `tests/docs/test_documentation_contract.py` | The relocated resource READMEs are frozen byte for byte by AO-REF-001 (`test_refactor_contract.py` pins their hashes), so they keep their links; both links resolve to `src/shwfs_ao/DATA_LICENSES.md`, now a byte-identical copy of the root file, packaged in the wheel and the sdist. The generated `ao_simulation_data` alias copy still carries the old relative link | new test: the copy equals the root file and both README links resolve to it; links clean |

The roadmap moves G8, G9 and G10 and the F-02 fix into a closed list. The
complete verification of these units (focused tests, the full native and
HCIPy selections, lint, types, API/inventory/witness comparisons, links and
the offline wheel gate) runs serially between S1 and S2:
`followup/verify_followup.sh`, log `followup/steps.log`.

### The large experiments

The user's message ("Conduct the large experiments.", 2026-10-18) enables
roadmap S1, S2 and S3, run one at a time. To give every record a clean
committed code identity, and to keep the fixes above from changing the code
under a running series, the experiments run from a separate detached
worktree at `2312502` (`.claude/worktrees/large-experiments-2312502`, code
identity `2312502` with an empty source digest). Evidence:
`outputs/large_experiments/2026-10-18/` in that worktree; records in its
`docs/refactor/detector_level_evidence/`.

| Item | Protocol | Status |
| --- | --- | --- |
| S1 | `run_detector_level_evidence.py --output det09_e5_42m_noise_on_current_2312502.json --enabled-by-user "…" e5`: `det_ccd_42m_r3band_derived@1`, root seed 1, 2000 frames, burn-in 200, summary telemetry, regenerated bands | **done 18:51–19:52**: 173.2 nm, Strehl 0.753, valid 0.999; every scientific field of the run (residual and open-loop series, valid fractions, science metrics, lock flag) bit-identical to the 2026-10-16 record; 1.797 s/frame (machine shared, load about 4.6), 1.60 GiB `ru_maxrss`; code identity `2312502`, empty source digest. The S2 driver's protocol for seed 1 reproduces this record's protocol hash. The record's `argv` holds the absolute script path (the run was started by absolute path); the S2 and S3 records avoid it. Copied byte for byte into this branch's evidence directory; LIM-17, the README, the roadmap and the reference now cite it |
| S2 | `s2/run_one_seed.py` through the same runner machinery: root seeds 2–6 (stage 1, five realizations), then 7–11 (ten), one fresh process each, same protocol as S1 | queued after the verification |
| S3 | `scripts/eso_scao_paired_convergence_study.py`: paired pupil, WFS and science sampling scans on the 12 m and 42 m ESO tiers (protocol and criterion declared in its docstring) | 5 m self-check passed (pairing: first-frame open-loop 540.57 vs 540.05 nm at 12 vs 16 samples). **12 m done 20:13–20:24** (`s3/medium/paired_convergence_medium.json`, code identity `2312502`, clean): pupil 12→16→20 Strehl 0.7618→0.7603→0.7584, finest two 0.25 % (paired −0.25 ± 0.05 %), EE50 0.55 %: converged; WFS pad 2→3→4: 0.00 %: converged; science pad 2→3→4: Strehl identical (on-axis), EE50 32.56→31.65→30.35 mas, finest two 4.3 % (paired 4.27 ± 0.11 %): **EE50 not converged in science sampling**. **42 m done 21:26–23:32** (`s3/full/paired_convergence_full.json`, same identity): pupil 12→16 Strehl 0.7832→0.7832 (0.01 % ± 0.04 %), EE50 0.01 %: converged; WFS pad 2→3→4 Strehl 0.04 %, EE50 0.12 %: converged; science pad 2→3→4 Strehl identical, EE50 8.684→8.473→8.384 mas, finest two 1.05 % ± 0.26 %: within 2 %, pad 2 reads 3.6 % high. Every 42 m run: no rejected solve, every frame usable, no DM saturation; 18 runs, 113 min, 1.57–3.16 GiB per run |
| S2 progress | — | Seed 2 ran 20:24–21:25: 175.0 nm, Strehl 0.748, 1.808 s/frame, 1.68 GiB (`det09_s2_42m_seed2.json`, relative `argv`, code identity `2312502`, clean). The queue then stopped: `run_s2.sh` assigned zsh's read-only `status` parameter after the seed, which aborts a zsh script (kept as written; the logged end of seed 2 was added afterwards). Because the queue still reported completion, the 42 m S3 study started at 21:26 as designed. `s2/run_s2_continue.sh` (the same driver, protocol and note; `rc` instead of `status`; skips recorded seeds) ran seeds 3–11 from 23:33 to 08:19 on 2026-10-19, each exit 0. **Ensemble (seeds 2–11):** 173.59 ± 0.94 nm, Strehl 0.7511 ± 0.0018 (sample SD; SE 0.30 nm, 0.0006); range 172.5–175.0 nm and 0.748–0.753; none lost lock; lowest per-frame valid fraction 0.982; 3498–3661 s and 1.68–1.97 GiB per seed. Seed 1 (S1) is typical (z = −0.42). Every record relative `argv`, code identity `2312502`, clean |

## Post-audit reconciliation (2026-10-18)

Assignment: [`audit_reconciliation_plan.md`](audit_reconciliation_plan.md),
format [`AUDIT_FINDING_EXCHANGE_FORMAT.md`](AUDIT_FINDING_EXCHANGE_FORMAT.md)
(both copied byte for byte from the main checkout). It reconciles the GPT
pre-refactor scientific audit (`outputs/pre_refactor_audit/20261017T143700Z/`
in the main checkout, tree `f09eb16`) with this branch at `27f34fa`. Run
`2026-10-18-claude-27f34fa`; ledger, report, test manifest, acceptance and
status are in `outputs/audit_reconciliation/2026-10-18-claude-27f34fa/`.
GPT finding IDs are namespaced there (`gpt-preaudit-20261017`); GPT F-01 is
not this record's F-01.

| Unit | GPT finding | Change | Behaviour and identity |
| --- | --- | --- | --- |
| A | F-01 (P2) | `detector/noise_model.py`: the coarse-quantization gate applies the half-ADC-step condition to every pixel that enters the centroid, with its own read-noise map and gain map | support flags change only where a contributing pixel is under-dithered, block by block (such a block reports the undefined sigma, so its lenslet fails the validity gate); the propagated covariance is unchanged; no packaged or recorded configuration flips (at least 0.65 ADU on every pixel of their CMOS maps); identifier kept `detector_covariance_v2` (it enters the physical WFS hash) |
| B | F-02 (P2) | `control/loop.py`: a multi-sample effective quadrature (count, duration) enters the run `config_hash` and a `wfs_exposure` metadata entry, which also records an override of the WFS's configured count | single-sample identities and metadata unchanged; no packaged profile uses more than one sample; a WFS's declared count must be an integer of at least 1 |
| C | F-03 (P2) | `scripts/run_detector_level_evidence.py`: series protocol 3 puts the producing environment (Python, NumPy, SciPy, machine) in every run's protocol; a resume under another environment or of a version-2 record is refused, and so is a resume that would add runs while the code identity is unknown | version-2 records are read-only history; nothing is attributed to them |
| D | F-09 (P2) | verifies U1 and adds `test_a_current_schema_record_runs_end_to_end` | test only |
| E | F-04–F-08, F-10–F-12 | wording and provenance in the reference, LIM-04/05/07/08/11/16/18, new LIM-19, roadmap G11/G12; `_fourier_translate` and `reconstruct_subset` docstrings | no behaviour change; packaged ledgers (F-08) deferred to a governed resource version |
| F | review findings RV-01–RV-08 | the reference no longer attributes the F-10 Nyquist loss to `native_frozen_flow_v2` (spectral replay keeps it; only `_fourier_translate` loses it); exact CMOS margins; bound environment fields; a WFS may declare its count as any integer type | the integer-type change in `control/loop.py` only accepts more declared counts; identities unchanged |

Checks of the final tree are listed in that run's `TEST_MANIFEST.json`; the
independent review and the acceptance decision are in its `review/` directory
and `ACCEPTANCE.md`. Until that review confirms a repair, the ledger keeps it
`FIXED_PENDING_VERIFICATION`.

The large experiments (S1, S2, S3) were produced by `2312502` in their own
worktree; they are bound to that producer, not to these repairs. None of
units A–C affects their configurations (CCD/EMCCD uniform maps or noiseless
tiers, single-sample exposure, one record per seed).

### Change unit U14: the S2 and S3 results in the documents (2026-10-19)

The user asked to wait until the post-audit reconciliation run in this
worktree (another session) had settled, and then to apply the S2/S3 update as
its own change. That run was accepted and committed as `fab2f29`; this unit
starts from it (the six documents below at `fab2f29` are byte-identical to the
snapshot in `u14_s2_s3_docs/before/`), and at the user's request it is
committed on its own, on top of `fab2f29`.

- Records added, byte copies from the experiments worktree:
  `docs/refactor/detector_level_evidence/det09_s2_42m_seed2.json` …
  `det09_s2_42m_seed11.json` and
  `docs/refactor/eso_scao_evidence/paired_convergence_medium.json`,
  `paired_convergence_full.json`. None holds a local path; the runner test
  that recomputes every saved record's protocol hashes and summaries passes
  with the ten S2 records included.
- Documents: LIM-07 (42 m S3 result, EE50 at the default science sampling as
  an upper estimate) and LIM-17 (eleven-seed ensemble); the roadmap (C3 cost
  1.6–2.0 GiB, the 42 m bullet, S2 met, S3 done for the ESO tiers); the
  technical reference (claims row, §7.4 sampling, §7.5 spatial convergence,
  §7.6, the S2 and S3 resource rows, the scenarios now measured); the ESO
  notes (EE50 caveat and a sampling-convergence section); the README (42 m
  ensemble, convergence paragraph); this record.
- Patch of exactly this unit: `u14_s2_s3_docs/u14.patch` (tracked files) and
  `u14_s2_s3_docs/added_records.txt` (the twelve records with SHA-256).

## Follow-up repair of GPT independent review AR-014–AR-016 (2026-10-20)

GPT's independent review of `949d931` (run
`outputs/audit_reconciliation/2026-10-19-gpt-independent-949d931/`) accepted
repairs A–D and proposed three new findings outside them. The user authorized
their targeted repair. Run `2026-10-20-claude-949d931` holds the successor
ledger, report, test manifest, acceptance and status in
`outputs/audit_reconciliation/2026-10-20-claude-949d931/`; the earlier runs'
records are unchanged. Until an independent review confirms a repair, that
ledger keeps it `FIXED_PENDING_VERIFICATION`.

| Unit | Finding | Change | Behaviour and identity |
| --- | --- | --- | --- |
| G | AR-014 (P2) | `scripts/eso_scao_paired_convergence_study.py`: run files are named by scale (`full_s12_wfs2_sci2_r0`); every run carries its own protocol (planned setting, scale, frames, burn-in, wavelength, paired grid, band storage, configuration hash, and the producer: a digest of the imported package and of the driver, Git where it tracks that package, and the environment) and its SHA-256; every saved run is checked before anything runs or is written, and a non-finite result is kept and reported as found; one producer per study, runs added only under it with a known code identity; a summary is never rewritten; the summary names `run_producer` apart from `summarized_by` | summary schema v2; version-1 run files and records are refused for reuse, not relabelled; the committed records (produced 2026-10-18, committed 2026-10-19) are unchanged (each was one invocation that launched every one of its runs) |
| H | AR-016 (P3) | `scripts/run_detector_level_evidence.py`: a resume recomputes every saved run's protocol hash, checks the label, seed, configuration hash, frame count and burn-in a run repeats, duplicate runs, the header's series fields and environment, and the carried-over notes; an unreadable or non-series record is refused too; the test of the real gated commands fails at once instead of starting a 12 m or 42 m run should the enablement guard regress (review CR-04) | series protocol 3 unchanged; the header now takes its environment fields from `producer_environment()` (the same values); every committed record passes the check |
| I | AR-015 (P3) | `docs/technical_reference.md` SH-2: tested domain and open questions from the S3 records, with the failed 12 m science-sampling EE50 criterion and the finite-scan scope; §7.5 (the S3 records' provenance) and LIM-11 (units G and H); the S3 runs dated 2026-10-18, as their logs show, in §7.5, the ESO notes and roadmap S3 (review CR-05) | documentation only |

## Follow-up repair of OBS-07: the detector runner's code identity (2026-10-20)

Run `2026-10-20-claude-949d931` recorded its reviewer's issue CR-02 as
observation OBS-07 (P3) instead of repairing it: binding the imported package
changes the protocol identity of every new run of the governed series runner.
The user authorized the repair on top of `f801cac` (the committed AR-014–AR-016
repair). Run `2026-10-20-claude-f801cac` adopts it as AR-017 and holds the
successor ledger, report, test manifest, acceptance and status in
`outputs/audit_reconciliation/2026-10-20-claude-f801cac/`; the earlier runs'
records are unchanged. Until an independent review confirms the repair, that
ledger keeps it `FIXED_PENDING_VERIFICATION`. The CLN-02 responsibility map
above describes the code identity used up to series protocol 3.

| Unit | Finding | Change | Behaviour and identity |
| --- | --- | --- | --- |
| J | AR-017 (OBS-07, review CR-02; P3) | `scripts/run_detector_level_evidence.py`: `code_identity()` digests the `shwfs_ao` package the process imports (bytecode and hidden files left out) and the runner script, and records the Git HEAD and the diff digest of the package's source directory only where the repository that holds the package tracks it, else null, so the code identity is unknown and a resume adds no runs; a resume refuses a version-3 record, with or without runs to add, before anything runs and leaves it as it was; tests with a throwaway repository: a tracked package, a copy in an ignored directory, a modified copy, fresh interpreters importing each, and resumes across them; the module docstring, LIM-11 and the technical reference's detector-evidence row | series protocol 4: every new run's code identity, and so its protocol hash, differs from version 3; version-3 records are neither continued nor relabelled, and version-2 and older records stay refused as before; no committed record is version 3, and every committed record keeps its hashes, summaries and consistency (tests) |

## Follow-up hardening of the package code identity: OBS-15–OBS-18 (2026-10-20)

The review of unit J (run `2026-10-20-claude-f801cac`, committed as
`714941c`) confirmed the repair and recorded four P3 issues as observations
OBS-15–OBS-18; OBS-15 and OBS-16 apply to the S3 driver's code identity too.
The user asked for their repair. Run `2026-10-20-claude-f801cac-hardening`
holds the records in
`outputs/audit_reconciliation/2026-10-20-claude-f801cac-hardening/`; the
earlier runs' records are unchanged. Until an independent review confirms
the repair, its ledger keeps it `FIXED_PENDING_VERIFICATION`.

| Unit | Finding | Change | Behaviour and identity |
| --- | --- | --- | --- |
| K | OBS-15–OBS-18 (review RV-01–RV-04; P3) | `scripts/run_detector_level_evidence.py` and `scripts/eso_scao_paired_convergence_study.py`: `_package_sha256` returns null, and the code identity is unknown, when the package is not a directory with `__init__.py` or holds a symlinked directory, a sourceless `.pyc` outside `__pycache__` (OBS-15) or a source whose cache, where this interpreter reads it, Python would run unchecked (review RV-05, RV-07; an unreadable cache is skipped, as Python skips it, RV-08); the Git commands read paths literally (`--literal-pathspecs`, OBS-16); the runner's version refusal gives version 3's reason only for version-3 runs (OBS-18), and a runner resume with nothing to add stops instead of verifying when the package has no digest (review RV-06); tests in both test files for each case and for file names in the digest (OBS-17); the docstrings and LIM-11 (with the timestamp-cache race) | a normal package's identity is unchanged (package digest and Git fields equal before and after), so series protocol 4 and S3 run protocol 2 stay; the changed layouts now count as unknown code, under which no runs are added; the scripts' own digests change, as with any edit |

## Versioned detector ledgers: AR-008 and roadmap G11 (2026-10-20)

The post-audit reconciliation deferred the packaged-ledger part of AR-008
(GPT audit F-08) to a governed resource version (unit E above). Ticket T3 of
the next-stage plan carried it out from `e486b18`; it is commit `d4403e6`
(tree `15fb1e17`) on `claude/t3-g11-ledger-v2`, and its implementation record
is in `outputs/t3_g11_ledger_v2/2026-10-20-opus-e486b18/`.

| Unit | Finding | Change | Behaviour and identity |
| --- | --- | --- | --- |
| L | AR-008 (GPT F-08; P3), roadmap G11 | `detector_source_ledger.v2.json` and `detector_level.assumptions.v2.json` beside the version 1 files: B14 states the current uncertainty model `detector_covariance_v2`, its support gates and the separate calibration-ensemble sigma; B18 and `historical_producers` attribute the `@2` gating decision and its records to version 1; D4 was checked against the publisher PDF of Thomas et al. (2006) and attributes the thresholding rule to the repository; the profile generator writes and checks version 2, and a test pins the version 1 bytes; the technical reference and the roadmap | descriptions only: the profiles keep referencing version 1, so every profile file and configuration hash is unchanged; the manifest gains the two resources (81); the package digest of both evidence scripts changes with them |

An independent review, `outputs/t3_g11_ledger_v2/review-2026-10-20-gpt/`,
read the uncommitted change that `d4403e6` commits byte for byte (base
`e486b18`, tracked diff SHA-256 `d7f4303e…`, new files `fa56a8d4…` and
`20cf6dd3…`) and accepted it, `PASS_WITH_DECLARED_VALIDATION_LIMITS`, with no
material finding. Its declared limits: CI has not run on the change; the
checks ran in the local macOS environment, not the constraint lock; the DOI
page could not be opened, so the paper was read in the owner's copy of the
publisher PDF, SHA-256
`4f26c5c1f1ff9cc372c43725fc93297e6be47b35390f626a082c0b6b9b215f59` (the
implementation record and the review assignment give this digest with two
characters missing; review observation T3-OBS-01, P3). As the review
proposes, this record closes AR-008 and roadmap G11 for that change; the
frozen reconciliation ledgers and the implementation record are left as
they are.

## Traced paired-noise instrument: ticket T1 and roadmap S4 (2026-10-21)

Ticket T1 of the next-stage plan (S4 tracing and the bounded 2 m replay) was
carried out from `b644a08`; it is commit `36768d2` on `claude/t1-s4-telemetry`,
and its implementation record is in
`outputs/t1_s4_telemetry/2026-10-20-fable-b644a08/`.

| Unit | Finding | Change | Behaviour and identity |
| --- | --- | --- | --- |
| M | roadmap S4 (an instrument for LIM-18 and AR-006, not their closure) | passive frame observation of the effective measurement row mask and the current frame's detector telemetry (model sigma and expected centroid per lenslet and axis, validated on their own domain); `paired_noise_run_traced` beside the unchanged `paired_noise_run`; the mask-locked arm with its own protocol identity (twin first; a partial lock is never reported exact); the traced record family (`noise-isolation-2m-traced`; the gated `-12m-traced` and `-12m-masklocked`) with one verified, allow-pickle-free NumPy sidecar per run under a diagnostic protocol beside series protocol 4, validated against the full schema (exact arrays, dtype, shape, canonical units, axes and meaning, frame domains, one lenslet order, canonical interleaved rows, map retention, mode-specific arrays) before any reuse; the NumPy-only analysis script and the 2 m H5 bound; tests, `docs/backends.md`, `docs/architecture.md`, technical reference 5.11 and the roadmap S4 note | every configuration, sensor, loop and detector hash, every history and the RNG draw order are unchanged (witnesses: 0 changed scientific leaves; five historical 2 m runs and the 32-run C0 replay reproduce `det09_noise_isolation_2m.json` bit for bit, and the traced and untraced runs of the current code are identical); the 12 m commands refuse before any profile or model without the user's enablement note; LIM-18 and the recorded records are untouched |

Three independent reviews read the uncommitted change
(`outputs/t1_s4_telemetry/review-2026-10-20-gpt/`,
`review-2026-10-21-gpt-r2/` and `review-2026-10-21-gpt-r3/`). The first
returned five P2 findings, T1-01 to T1-05 (an undefined expected centroid
could refuse a measurement; digest-bound malformed sidecars passed reuse
validation; supported construction refusals lost their diagnostic identity;
zero-scatter populations lost their paired slopes; a non-positive
correlation-time estimate reported zero uncertainty as reliable). The second
found four of them resolved and T1-02 partial: declared units, axes and
meaning were compared by type only, row and lenslet ids by count only, and
the standalone loader was weaker than the runner. The third accepted the tree
that `36768d2` commits byte for byte (base `b644a08`, tracked diff SHA-256
`c743e9ff0ae393012fe2424d5ea68bd20719a090ce32149be1d9a3907719017f`, new files
`174acf5e…`, `79b3dd95…`, `0e0b186f…`, `5bd2006f…`), `PASS_WITH_DECLARED_VALIDATION_LIMITS`, with no actionable
finding: the reviewer's unchanged fourteen-variant probe is refused by both
consumers, 235 focused tests passed, all 64 saved C0 sidecars are accepted
unchanged and the fresh offline re-analyses have zero numeric differences.
Its declared limits: CI has not run on the change; the checks ran in the
local macOS environment (Python 3.14.3, NumPy 2.5.0), not the constraint
lock, serially with two threads under the user's resource-guard instruction
of 2026-10-20; the full suite, the H5 bound and the C0 study are the
implementation's source-bound evidence, inspected and reused rather than
re-executed; the acceptance covers the instrument and its record contract,
not the noise-law question. S4, AR-006 and LIM-18 keep their status; the C0
record and its sidecars stay local under `outputs/t1_s4_telemetry/`; no 12 m
or 42 m arm was run.

## Fixed-physics convergence interfaces, oracles and driver: ticket T2 and roadmap AR-007 (2026-10-21)

Ticket T2 of the next-stage plan was carried out from `e5918c1` on the
worktree `claude/t2-convergence` and committed on that branch; its
implementation record is in `outputs/t2_convergence/2026-10-21-fable-e5918c1/`
(git-ignored; `IMPLEMENTATION_RECORD.md`, `REVIEWER_BRIEF.md`, `RECORD.json`,
the pre-edit `DESIGN_NOTE.md`, the review under `review/`). Status: implementation
complete; accepted by the first independent review on 2026-10-21 (review round 2); a second
independent review of the committed delta requested repairs (retained-row validation bound to the plan's expected records,
pairing per realization, Richardson endpoints and conditioning), applied the same day
(rounds 3 and 4).

| Unit | Finding | Change | Behaviour and identity |
| --- | --- | --- | --- |
| N | AR-007 and roadmap S3: the detector-level profiles had no fixed-physics convergence instrument; the S3 pairing was a script monkeypatch that equates FFT indices with physical frequencies; the exposure rule shifted the mean sample time with `n`; EE50 had no grid-independent reference | G1: three identity-bearing options on the native layered atmosphere (reference-grid band draw, common band, `pupil_diameter` screen-period rule; `canonical_identity_payload` keeps the legacy hash while they are unset) with the construction route `LayeredAtmosphereOptions` through `build_scao_system` and the attestation; G2: the midpoint exposure rule (`exposure_sample_rule`, `ExposureOverride`) with its own scheme and labelled metadata; G5: the validation-only Fourier encircled-energy reference with separate error budgets; the Richardson and atmosphere-pairing validation modules; the experiment core `experiments.convergence_study` (streaming reductions, disk-backed paired ΔV); the driver `scripts/detector_level_convergence_study.py` (plan, protocols with producer identity, atomic never-clobbering records, strict refusals, summary written once, `--plan`, governed `--enabled-by-user`); tests; technical reference 5.1, 5.4, 5.10, 5.11, 9.2, roadmap S3, LIM-05, LIM-07, the turbulence-model, architecture and validation pages | every default identity, draw, history and metadata unchanged (pre/post witnesses: 3862 common leaves, 0 scientific leaves changed; the pre-change identity formula is asserted by a test); the equal-index pairing is quantified as approximate (common-band fields differ by 5–12 % RMS; band-edge phase error `π(1 − N_c/N_f)`) and the matched rule pairs to rounding; the ci self-check ran in fresh child processes (11 paired runs, 89 s, at most 307 MiB per child) with an exact byte-and-mtime no-op rerun and an independent re-analysis; the resource guard refused the job on warn memory pressure at the first three preflights (the fourth to sixth, before the round-3 and round-4 self-checks, admitted the job), the user directed that the guard be ignored for this task, and the self-check ran as a bounded check (recorded); no 12 m or 42 m run, no profile, metric, model or S3-driver change; G3 deferred; AR-007, S4, AR-006, LIM-18 and LIM-01 keep their status |

## Follow-up: the engineering queue against the current source and CI history (2026-10-27)

The engineering items whose wording had aged were checked against the source
at `3ce386f` and the repository's GitHub Actions history (read only: run and
job listings and the one failed job's log; nothing was triggered or re-run).
Each finding is a dated status line on its row in the
[roadmap](../roadmap.md#engineering-queue); no item is closed, and no
scientific row, dated historical section or closed item changed.

| Item | Finding | Status |
| --- | --- | --- |
| G1 | The local commits of this cleanup are on `main` and have run in CI. Workflow `tests` passed all seven push jobs on `5514285` (run 39656946715, 2026-10-21; post-T2 packet) and last on `5df797f` (run 39942155146, 2026-10-23), including the README native commands from the clean wheel on 3.14; the 19 later first-parent commits up to `3ce386f` carry `[skip ci]`. The scheduled lane on `3ce386f` (run 40296997307, 2026-10-26) failed in the slow native tests on `test_the_real_ci_self_check_runs_in_fresh_child_processes_on_the_exposure_axis` (1 failed, 25 passed, 9 skipped; `StudyRecordError`: a child's run record carries another code identity or environment than the parent's); the full HCIPy sweep passed. The test came with T2 (`229fb6a`) after the previous scheduled run (2026-10-19, `37b5bd9`, success), so this was its first CI execution. | open: the failure is not triaged. An unverified reading from the sources is that the lane replaces the source install with the built wheel while the test sets `PYTHONPATH` to `src/` for its children. |
| G4 | Still accurate: `science_run` reads `ru_maxrss` into `process_peak_rss_bytes` (`src/shwfs_ao/experiments/detector_level.py`, lines 528–538). | open, unchanged |
| G7 | Neither `claude/bold-shirley-6f1e9f` nor `claude/trusting-bell-471569` is on the remote, which holds only `main` and `feature/dynamic-phase`; their state in the owner's local clone is not known here. | open until the owner confirms |
| Explorer build tool | `scripts/ao_explorer/site_build.py --write` rewrote `data/current.json` with one-space indentation, while the NGS-family packagers write two spaces (the entry on `main` has two since `3ce386f`). A restamp of an unchanged build therefore rewrote all 83 indented lines of the entry. | fixed: `write` keeps the entry's existing indentation (one helper, `_json_indent`); `test_restamping_keeps_the_entry_layout` covers one and two spaces and fails on the previous code for two. The older packagers that write one space are unchanged. |
