# Validation plan for proposed detector-ledger corrections

**Status: HISTORICAL PLAN (2026-10-20).** Research-only scope. The change it
plans (publishing `detector_source_ledger.v2.json` and
`detector_level.assumptions.v2.json` from the candidates in
[`proposed_corrections.json`](proposed_corrections.json)) is a later, separately authorized,
governed resource change. Nothing here was run against a changed tree.
Appendix B of [`correction_specification.md`](correction_specification.md) records the one
static check made on the candidate records themselves.

## Preconditions

- **P1.** The decisions D-1 to D-10 (specification section 8) are resolved,
  and the resolution is written into the acceptance record.
- **P2.** The D4 variant is chosen (D-7). For variant B, a full-text read of
  [Tho06] is recorded first, with section, equation and page locators, for
  claims T1–T5 ([`references.md`](references.md) section 2). A statement
  the read does not support stays out.
- **P3.** No governed evidence series is mid-resume. Adding any file under
  `src/shwfs_ao/resources/` changes `_package_sha256`, and with it the code
  identity of every new run of `scripts/run_detector_level_evidence.py`
  (series protocol 4) and `scripts/eso_scao_paired_convergence_study.py`
  (run protocol 2). A resume across the change is refused by design.
- **P4.** The environment is named. Where governed records will cite the
  change, it is the constraint lock (roadmap G6;
  `scripts/verify_environment_lock.py`).

## Minimum checks

Cost category C1: bounded tests and static checks, minutes. The checks
need no AO simulation, ensemble, slow Monte Carlo or governed run. The
reason: the ledgers are read only by `tests/io/test_detector_level_ledgers.py`
and the generator, and no numerical code path loads them. Profile
`provenance.references` hold their paths as strings.

### A. Historical preservation

| ID | Check | Command or method | Pass condition |
| --- | --- | --- | --- |
| A1 | v1 bytes unchanged | `sha256sum src/shwfs_ao/resources/benchmarks/detector_source_ledger.v1.json src/shwfs_ao/resources/benchmarks/detector_level.assumptions.v1.json`; `git diff --exit-code <base> -- <both files>` | `2b8cc13ebca067f9c48af1861680a84de619834019567a33a7d671ec606882fc` and `33073748f7a919749b6908c851318efefa02b2d8379a4f8bd12647a7bdeb7ffa`; empty diff |
| A2 | profiles unchanged | `git diff --exit-code <base> -- src/shwfs_ao/resources/synthetic_presets/`; `python -m pytest -q tests/io/test_configs.py tests/io/test_detector_level_profiles.py` | empty diff; every pinned `config_hash` passes (D-2 = keep) |
| A3 | evidence and history unchanged | `git diff --exit-code <base> -- docs/refactor/detector_level_evidence docs/refactor/eso_scao_evidence docs/refactor/DETECTOR_LEVEL_DEVELOPMENT_STATUS.md` | empty diff |
| A4 | v1 still validates as history | the test from I-4 loads v1 and runs `validate_benchmark_profiles` on the eight profiles | passes with the v1 coverage |
| A5 | no relabelling | static test over v2: `detector_covariance_v1` appears only in B18's historical clause, `revisions` and `historical_producers`, never in B14 or B18's title | passes |

### B. Resource validation

| ID | Check | Command or method | Pass condition |
| --- | --- | --- | --- |
| B1 | the loaders accept v2 | `load_source_ledger("benchmarks/detector_source_ledger.v2.json")`; `load_assumption_ledger("benchmarks/detector_level.assumptions.v2.json", source_ledger=…)` | no `LedgerError` |
| B2 | coverage unchanged | `validate_benchmark_profiles(v2, configs)` over the ledger's eight profiles | the returned per-profile row sets equal v1's (16 rows, 18 for `@2` and `@3`) |
| B3 | only the accepted fields differ | field-level comparison of v1 and v2 (the method of the static validation script) | differences are exactly the accepted candidates' fields, plus the top-level `supersedes`, `revisions`, `historical_producers`, `source_ledger` and, per D-3 and D-6, `ledger_id` and `frozen`. Every `values_by_profile` is identical |
| B4 | the current identifier is named | test: `noise_model.UNCERTAINTY_MODEL_ID in B14.rationale` | passes; it will fail on a future identifier change, prompting a new ledger version |
| B5 | no placeholders | search v2 for `<VERIFY` and `<ACCEPTANCE_DATE>` | none |
| B6 | consuming tests resolve and the fast ones pass | resolve every `consuming_tests` entry to a function; run the fast domain-gate tests: `python -m pytest -q "tests/detector/test_noise_model.py::test_regimes_outside_the_first_order_domain_are_flagged" "tests/detector/test_noise_model.py::test_conditional_mean_is_the_processing_of_the_expected_frame" "tests/detector/test_noise_model.py::test_codes_within_the_noise_headroom_of_code_zero_are_flagged" "tests/detector/test_noise_model.py::test_codes_within_the_noise_headroom_of_the_top_code_are_flagged" "tests/detector/test_noise_model.py::test_a_contributing_pixel_below_half_a_step_unsupports_the_block"` | all resolve; all pass. The slow tests named in B14 need not run: no numerical code changes |
| B7 | the existing ledger tests | `python -m pytest -q tests/io/test_detector_level_ledgers.py tests/io/test_eso_scao_profiles.py` | pass |
| B8 | variant B only | the acceptance record cites the full-text read (P2) for every locator in D4 | every locator has a recorded passage |

### C. Generator and manifest

| ID | Check | Command | Pass condition |
| --- | --- | --- | --- |
| C1 | generators byte-stable | `python scripts/generate_detector_level_profiles.py --check`; `python scripts/generate_eso_scao_profiles.py --check` | both exit 0, no output |
| C2 | manifest consistent | `python -m pytest -q tests/io/test_resources.py`; `git diff --exit-code -- src/shwfs_ao/resources/resource_manifest.json` after the test run | passes; the manifest has two new records, and the v1 records keep the digests in A1 |
| C3 | lint and types on changed Python | `ruff check scripts/generate_detector_level_profiles.py tests/io/test_detector_level_ledgers.py`; the repository's mypy target if those files are in it | clean |
| C4 | whitespace | `git diff --check` | clean |

### D. Packaging

| ID | Check | Command | Pass condition |
| --- | --- | --- | --- |
| D1 | wheel contents | `python -m pip wheel --no-deps --wheel-dir <tmp> .`; `python scripts/inspect_wheel_contents.py` (or `python -m pytest -q tests/test_wheel_install.py`) | both v2 files are under `shwfs_ao/resources/benchmarks/`, and under the `ao_simulation_data` alias, byte-identical; the alias manifest equals the canonical manifest |
| D2 | read from an installed wheel | in a fresh environment outside the checkout: `importlib.resources` read of both v2 files, then B1 | readable and valid; no checkout path needed |

### E. Record

| ID | Item | Content |
| --- | --- | --- |
| E1 | acceptance record | resolutions of D-1 to D-10; accepted candidate IDs and variant; the v2 digests; every command above with its exit code and the node IDs collected; environment (Python, NumPy, platform); reviewer and decision |
| E2 | documentation (I-5, D-10) | technical reference §7.1 points to v2 with v1 as history; the OBS-4 attributions follow C02; roadmap G11 closed with a link to E1 |
| E3 | what stays open | for variant A, the full-text verification of T1–T5 stays an open research item; a later variant-B change is a further ledger version, not an edit of v2 |

## Not required, and why

- **A whole-repository test suite.** The change touches two new resource
  files, the manifest, one generator, one test file and documentation.
  A bounded native selection
  (`-m "not hcipy and not slow and not elt_scale"`) is optional extra
  assurance, not a condition.
- **Re-running E1, E2 or any governed run.** No equation, gate, constant,
  profile value or identity of the covariance model changes, and the ledger
  text is read by no numerical path.
- **New profile versions.** Only if D-2 chooses them. That would be a
  separate change with its own identity pins and evidence.
