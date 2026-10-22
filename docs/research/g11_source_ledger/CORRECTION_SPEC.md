# G11 detector source-ledger corrections: correction specification

**Status: PROPOSED. Not accepted. No resource, code, manifest or record was changed.**
Research output for roadmap item G11 (GPT pre-refactor audit F-08; AR-008 in
the later GPT review). Written 2026-10-20 on task branch
`claude/fervent-einstein-4g3syq`, which starts at source commit
`10f04e268871a19bfedb47b035f2905b67f23e43`, the head of
`claude/cleanup-refactor-exec`. Companion files:
[`CANDIDATES.json`](CANDIDATES.json) (machine-readable candidates),
[`REFERENCES.md`](REFERENCES.md) (sources, locators, access limits),
[`ACCEPTANCE_PLAN.md`](ACCEPTANCE_PLAN.md) (checks for a later change),
[`INPUT_MANIFEST.json`](INPUT_MANIFEST.json) (input digests).

## 1. Result in brief

- **D4 (Thomas et al. 2006).** The v1 limitation "their analytic forms
  assume Gaussian spots" has no recorded full-text check. The v1 ledger's
  `access_note` records only that D4's bibliographic details were confirmed
  by web search. G11 records a
  counter-claim from the GPT audit: section 3.1 (equation 13, Appendix A)
  treats diffraction spots. **Neither claim could be checked here.** Every
  route to the paper was denied by the session's network policy
  ([REFERENCES.md](REFERENCES.md) section 1). The proposed wording
  (variant A) therefore makes **no claim about the paper's spot model or
  field**. It states what the implementation does instead, which was
  verified in code. It is correct whatever the paper says. A variant B
  template adds verified locators after a full-text read. It is marked
  blocked.
- **B14.** The row describes `detector_covariance_v1`. The current model is
  `detector_covariance_v2` (`detector/noise_model.py:99`), replaced on
  2026-10-16 (`573f875`). Its support domain differs from v1's in two ways.
  It checks both ADC limits, with offsets and 5σ headroom; v1 checked only
  the upper limit. Since 2026-10-18 it also applies the half-step
  quantization rule per contributing pixel; v1, and v2 until then, used the
  scalar read noise. Its conditional mean subtracts the realized masters,
  where v1 used the ideal background. The proposal is a description
  correction. The v1 description moves to `revisions` as history.
- **B18.** The title names `detector_covariance_v1` as the gating domain of
  `det_emccd_12m_medium_derived@2`. That is true of the decision, which was
  made and evidenced under v1. But `@2` and `@3` runs on current code gate on
  v2. The proposal separates the historical producer from the current
  semantics and relabels no evidence.
- **No mathematical change** is supported or proposed. No equation, gate,
  constant, profile value or identity of the covariance model changes.
- The corrections take the form G11 names: **new files**
  `detector_source_ledger.v2.json` and `detector_level.assumptions.v2.json`,
  with both v1 files kept byte-identical. Ten decisions remain open
  (section 8).

## 2. Inputs, scope and missing inputs

Read on the source commit (digests in `INPUT_MANIFEST.json`): the roadmap,
the technical reference, the limitations register, the detector model page,
the detector and cleanup status files, both ledgers, the ESO v2 ledger
(precedent), the resource manifest, the eight `det_*` profiles, the ledger
loader, the profile configuration code, the covariance model and its
compatibility counterpart, the generator, both evidence runners, and the
ledger, resource, configuration and noise-model tests.

Missing (all under the git-ignored `outputs/`, absent from this checkout):
the GPT audit report holding F-08
(`outputs/pre_refactor_audit/20261017T143700Z/`), the report holding AR-008
(the ID occurs nowhere in the tracked tree), and the reconciliation run
records. The finite-field statement (T3 below) is reconstructed from this
assignment's wording, because AR-008's text is unknown.

Not done, by the assignment's boundaries: no runtime source, canonical
resource, manifest, historical evidence or accepted report was edited. No
simulation, ensemble or test-suite run took place. One static check ran on
the proposed records only (appendix B).

## 3. Primary-source verification of the Thomas et al. (2006) statements

The full text of [Tho06] was **not read**. The table records what each
statement rests on and how the proposed wording handles it.

| ID | Statement and where it is made | Evidence reached in this session | Status | Consequence for the wording |
| --- | --- | --- | --- | --- |
| T1 | "their analytic forms assume Gaussian spots" (source ledger v1, D4 `limitations[0]`) | none at primary level. The v1 session recorded only a web-search confirmation of bibliographic details (`access_note`). A citing paper, relayed by a search summary only, says the paper computes a weighted-centroid factor for a Gaussian spot | `inaccessible/unverified`. **Overbroad as written**: it asserts that *all* the paper's analytic forms assume Gaussian spots, while G11 attributes a diffraction-spot treatment to the same paper | withdraw. Do not replace it with an equally unverified opposite claim |
| T2 | "their section 3.1 (equation 13, Appendix A) treats diffraction spots" (roadmap G11, from GPT audit F-08) | the F-08 report is missing. A search-relayed secondary statement ([S24]) says the paper showed a field-of-view dependence of the photon-noise centroid error | `inaccessible/unverified` at primary level. Secondary-consistent | name no locator until it is read (variant B) |
| T3 | for a diffraction-limited spot the centre-of-gravity photon-noise error depends on the finite field (this assignment; presumably AR-008) | [S24] by search summary only. The independent derivation of appendix A shows that the window dependence is required for a square-subaperture diffraction spot | `inaccessible/unverified` at primary level. **Analytically consistent** (`ANALYTIC_ESTIMATE`) | state the window dependence as a property of the implementation, which holds by construction, not as the paper's result |
| T4 | "thresholding is not first-order linear" (D4 `supports[0]`; technical reference estimator and [Tho06] rows) | abstract-level, search-relayed: the paper compares thresholded, weighted, correlation and quad-cell estimators | `inaccessible/unverified` as the paper's statement. **Verified as a repository rule**: `noise_model.py:428` reports thresholded estimators unsupported; the `validity.py` docstring (lines 224–228) states that its first-order sigma does not model thresholding, without flagging it | attribute the rule to the repository |
| T5 | the paper uses a Gaussian spot in at least one closed form | search summary of a citing paper | orientation only | supports reading T1 as overbroad rather than false |

**Applicability bridge (verified in code).** Neither model uses a closed
form from the paper:

- `detector.noise_model` (physical path) forms the per-pixel lever arm
  `j_k = (x_k − c)/T` over the declared window `W`, with `T` the window
  total of the expected processed image. It contracts the full per-pixel
  covariance through it (`quadratic_form`, coupling and bad-pixel
  back-projection included).
- `detector.validity._first_order_cog_sigma_px` (compatibility path)
  evaluates `Σ_W (x_k − c)² (S_k + B + RN²) / (Σ S)²`.

For any expected spot, both make the photon and read-noise variance depend
on the finite window through the lever arms. Appendix A shows this captures
the diffraction-spot field dependence (T3) and the Gaussian limit alike.
What *was* tested is narrower than what the formula admits. E1 and the unit
tests used Gaussian fixture spots (`experiments/detector_noise.py:268`,
σ = 1.2 px). E2 used the profiles' own lenslet optics in open loop.
Proposed B14 and D4 wording says both.

## 4. Current covariance semantics against historical v1 evidence

| | `detector_covariance_v1` (history) | `detector_covariance_v2` (current) |
| --- | --- | --- |
| Code read | `git show a31099b:src/shwfs_ao/detector/noise_model.py`, lines 360–385 | `src/shwfs_ao/detector/noise_model.py` at the source commit, lines 427–470 |
| Period | DET-07 finished 2026-10-15; first committed in `a31099b` (2026-10-16 07:50 +02:00); superseded by `573f875` (2026-10-16 23:14 +02:00) | committed from `573f875`; the fixed working tree already produced the review reruns from 2026-10-16 20:35; quantization gate corrected 2026-10-18 (GPT F-01), identifier kept |
| Conditional mean, Jacobian, flux, SNRs | from the ideal background (`subtracted = coupled(bg_mu) / gain_left`) | subtract the realized masters the processing removes (review R2) |
| ADC domain | upper limit only: the block's largest expected code, bias included, offsets excluded, against 90 % of the top code; no lower limit, no noise headroom | 90 % of the top code, and every pixel's expected code, bias and offset map included, 5 temporal σ inside both limits (R4) |
| Quantization gate | scalar camera read noise against the batch's largest gain step; one failure unsupports the whole batch | the v1 rule until 2026-10-18; since F-01, each pixel that enters the centroid, with its own read-noise and gain maps |
| Other gates | plain CoG, no negative clipping, no non-linearity, pixel and register saturation at 90 %, positive window total, `SNR_T ≥ 7` | the same |
| Identity | in the physical sensor `config_hash` (`physical_measurement.py:255`) | same binding: every physical sensor hash moved on `573f875` |
| Ledger text | B14 and B18 (frozen 2026-10-15; last ledger change `ea775bc`, 19:26, before v2) | none yet: the subject of this specification |

**Evidence by producer** (from `DETECTOR_LEVEL_DEVELOPMENT_STATUS.md`,
"Effect of the fixes on the recorded evidence" and "12 m review reruns:
results"; start times from the records):

- **Produced under v1 (history, keep as is).** The pre-review 2 m E1, E2 and
  closed-loop ensemble. "E2-12m, E3, E4, E6, DET-08, E5, the recovery and
  excursion studies, and the `@3` reruns". The DET-09 gain scan
  (`det09_gain_scan.json`, started 2026-10-15 23:21). Ledger rows cite four
  of these: B11 (gain scan), B18 (E3 on `@1`, started 2026-10-16 00:53; E3
  and E4 on `@2`, 01:51 and 02:25), B20 (`det_excursion_e3_12m_v2.json`,
  12:54) and B21 (`det_recovery_e3_12m_v2.json`, 10:11).
- **Produced under v2.** The review reruns `det07_e1_centroid_noise_review.json`,
  `det09_e2_noise_propagation_review.json`,
  `det09_closed_loop_ensemble_2m_review.json`. The five 12 m reruns of
  2026-10-16 21:03–23:12, from the fixed working tree before its commit,
  hence `git_head` `663df16` plus a diff digest. The S1 and S2 42 m records
  (`2312502`).
- `git_head` alone does not classify a record: the `663df16` records carry
  v2 code in their uncommitted diff. The status file is the authority here.
  A per-record classification is not needed for the ledger corrections and
  is not attempted.

## 5. Field-by-field correction table

Resource prefix `src/shwfs_ao/resources/`. "Existing" is quoted from the v1
bytes. "Proposed" is the variant-A text of `CANDIDATES.json`.
`implicit_model_property` rows state no profile value, so profile coverage
is unchanged (verified, appendix B).

| Cand. | Resource and field | Existing wording | Verified support | Proposed wording | Class | Code consumer | Compatibility and versioning |
| --- | --- | --- | --- | --- | --- | --- | --- |
| G11-C01 | `benchmarks/detector_source_ledger.v1.json` → v2, `sources[D4].limitations` | "their analytic forms assume Gaussian spots; the implemented model contracts the exact pixel Jacobian instead" | first clause: none (T1). Second clause: `INSPECTED_CURRENT` (`noise_model.py` window levers and `quadratic_form`; `validity.py:429–462`) | 1. "the implemented models use none of the paper's closed-form noise expressions, so none of the spot-shape (Gaussian or diffraction-limited) or field-of-view conditions of those expressions applies to them: detector.noise_model and detector.validity contract the exact per-pixel Jacobian of the plain centre of gravity over the declared finite window, which holds for any expected spot and makes the photon- and read-noise terms depend on the window through each pixel's lever arm" 2. "that a thresholded centre of gravity lies outside a first-order linear model is the repository's own rule (detector.noise_model reports it unsupported; detector.validity states that its first-order sigma does not cover it), not a quoted result of this paper" 3. "section, equation and appendix locators have not been checked in full text (access_note, revisions)" | description correction | `io.benchmark_ledgers.validate_source_ledger` (non-empty list); `tests/io/test_detector_level_ledgers.py` loads it by name | text only. New file v2; v1 unchanged |
| G11-C02 | same, `sources[D4].supports` | "first-order centre-of-gravity noise in photon- and read-noise-limited regimes; thresholding is not first-order linear" | abstract level by search summary (estimator families). T4 as a repository rule: `noise_model.py:428` | 1. "method reference for centre-of-gravity noise in photon- and read-noise-limited regimes" 2. "a comparison of the plain centre of gravity with thresholded, weighted, correlation and quad-cell estimators; the repository implements the plain and the thresholded centre of gravity" | description correction | as C01 | text only |
| G11-C03 | same, `sources[D4].locator` | "centre-of-gravity noise propagation, photon and read-noise terms, thresholding discussion" | the v1 locator names topics, not sections | "centre-of-gravity noise in photon- and read-noise-limited regimes and the estimator comparison (section and equation locators not checked in full text; see limitations)" | description correction | `validate_source_ledger` (non-empty string) | text only. Superseded by C12 once verified |
| G11-C04 | same, top-level `access_note` | the v1 note ("Bibliographic details of D1, D4 and D5 were confirmed by web search in the implementing session (2026-10-15); …") | `INSPECTED_HISTORICAL`: it remains true of that session | the v1 note verbatim, then: "Version 2 (<ACCEPTANCE_DATE>): D4 was researched again on 2026-10-20 without full-text access (the publisher, DOI and preprint hosts were denied by that session's network policy); its supports, limitations and locator were rewritten so that they make no claim about the paper's spot model or field; no other entry changed." | new-version metadata | none (top-level, not validated) | placeholder filled at acceptance |
| G11-C05 | same, new top-level `supersedes`, `revisions` | absent | precedent: `benchmarks/eso_drm_42m_scao_derived.assumptions.v2.json` | `supersedes`: the v1 path. `revisions[0]`: source D4, fields, change, reason (G11, F-08, AR-008), evidence (this directory), not changed (bibliographic fields, url, role, accessed; all other sources and reference cases) | new-version metadata | none (`load_source_ledger` reads `schema_name`, `sources`, `reference_cases`) | no schema change |
| G11-C06 | `benchmarks/detector_level.assumptions.v1.json` → v2, `rows[B14].rationale` | "detector_covariance_v1 is supported for a plain centre of gravity without clipping, saturation, non-linearity or coarse quantization and with SNR_T >= 7; temporal sigma conditional on fixed masters gates validity, calibration-ensemble sigma is reported separately" | `INSPECTED_CURRENT`: `noise_model.py:99` (identifier), 105–115 (7, 0.5 ADU, 0.9, 5σ), 275–306 (realized masters), 428–470 (gates); `physical_measurement.py:813` (`centroid_calibration_sigma_px`) | "detector_covariance_v2 (detector.noise_model.UNCERTAINTY_MODEL_ID) is supported only for a plain centre of gravity (no threshold, no minimum subtraction), without negative clipping or a declared non-linearity, with no expected saturation above 90 % of the pixel, EM-register or ADC capacity, with every block pixel's expected ADC code (bias and offset map included) at least 5 temporal noise sigmas inside both ADC limits, with read noise of at least half an ADC step on every pixel that enters the centroid (its own read-noise and gain maps, ADC on), with a positive window total and with SNR_T >= 7; its conditional mean, Jacobian, flux and SNRs subtract what the processing actually removes (the realized masters); the temporal sigma, conditional on those fixed masters, gates validity, and the calibration-ensemble sigma, linearized about the nominal background, is reported separately (centroid_calibration_sigma_px) as a persistent per-run bias" | description correction (current semantics) | `scripts/generate_detector_level_profiles.py` `row("B14", …)` line 531, `--check`; `validate_assumption_ledger` (non-empty) | text only. No profile, sensor or record hash binds ledger text; the governed runners' package digest covers resource files (section 6) |
| G11-C07 | same, `rows[B14].limitation` | "outside the domain the model reports an undefined sigma and the lenslet is invalid" | `INSPECTED_CURRENT`: Gaussian fixtures (`detector_noise.py:268`, test fixtures). `INSPECTED_HISTORICAL`: E1 (`4/SNR_T²`), E2 on profile optics | "outside the domain the model reports an undefined sigma and the lenslet is invalid; first order, it reads low by about 4/SNR_T^2 near the SNR_T floor (E1); its Monte Carlo checks used Gaussian fixture spots (E1, tests/detector/test_noise_model.py) and, in open loop, the profiles' own lenslet optics (E2); the formula itself assumes no spot shape" | description correction | as C06 | text only |
| G11-C08 | same, `rows[B14].consuming_tests` | `[…test_noise_model.py::test_temporal_scatter_matches_the_model_within_ten_percent]` (one slow test) | the seven tests exist at the source commit (appendix B) | add `test_regimes_outside_the_first_order_domain_are_flagged`, `test_conditional_mean_is_the_processing_of_the_expected_frame`, `test_codes_within_the_noise_headroom_of_code_zero_are_flagged`, `test_codes_within_the_noise_headroom_of_the_top_code_are_flagged`, `test_a_contributing_pixel_below_half_a_step_unsupports_the_block`, `test_calibration_ensemble_matches_the_model` | description correction | generator `_TESTS["model"]` (line 437), **shared with B18** | text only. Decisions D-5, D-8 |
| G11-C09 | same, `rows[B18].title` | "Validity gating on the detector_covariance_v1 domain (version 2, post-hoc)" | `INSPECTED_HISTORICAL`: the `@2` decision was made on v1 (status, DET-09 post-hoc follow-up). `INSPECTED_CURRENT`: `@2` and `@3` have `min_peak_snr = 0`, `max_centroid_sigma_px = 0.5` | "Validity gating on the uncertainty-model domain instead of the peak-pixel SNR gate (version 2, post-hoc)". Alternative: keep the v1 title (D-4) | historical producer description | generator `row("B18", …)` line 545 | text only. Row ID and values unchanged |
| G11-C10 | same, `rows[B18].rationale` | "E3 on @1 showed the inherited peak-pixel SNR gate (3) rejects lenslets with total SNR ~20 from m_AB ~ 9.5 and collapses the loop at m_AB = 10; @2 sets it to 0 and relies on SNR_T >= 7 (validated domain) and sigma <= 0.5 px; recorded reason, the affected experiments are rerun on @2" | `INSPECTED_HISTORICAL`: E3 and E4 on `@2` by model v1 (status; record start times, section 4) | the v1 text verbatim, then: "; the decision, and E3 and E4 on @2, were made and produced under detector_covariance_v1 (2026-10-16, before commit 573f875), and those records keep that identity; runs of @2, and of @3, which inherits the gate, on current code gate on detector_covariance_v2 (B14), whose SNR_T is formed from the conditional mean on the realized masters" | historical producer description | as C09 | text only. Relabels nothing |
| G11-C11 | same, top-level `source_ledger`; new `supersedes`, `revisions`, `historical_producers` | `"source_ledger": "benchmarks/detector_source_ledger.v1.json"` | precedent ESO v2 ledger; record start times | `source_ledger`: the v2 path. `supersedes`: the v1 path. `revisions`: B14 (with the v1 history: ideal-background mean, upper ADC limit only; `573f875`; F-01) and B18. `historical_producers`: B11, B18, B20, B21 cite evidence produced under v1, which keeps its identities | new-version metadata, historical producer description | generator `ledger_record()` return dict (lines 599–615) | no schema change (top-level keys beyond `schema_name`, `classifications`, `rows` are not validated) |
| G11-C12 | source ledger v2, `sources[D4]` `limitations[0]`, `locator`, `accessed` (variant B) | as C01 and C03; `accessed` "2026-10-15" | **requires a full-text read** (checklist T1–T5) | template with `<VERIFY: …>` placeholders: the spot models and conditions with their section/equation numbers, the locator, the read date | description correction | as C01, C03 | **BLOCKED_ON_SOURCE_ACCESS**; a value containing `<VERIFY` must never be accepted |

Open choices with no candidate of their own: the `ledger_id` of both v2
files (D-3) and the meaning of `frozen` (D-6).

## 6. Versioning, hash, manifest, schema and compatibility implications

**Why new files and not an in-place edit.** G11 names the route ("publish
new ledger versions … keep the v1 files as history"). Four further reasons:

- The v1 bytes are what the eight profiles' `provenance.references` name.
- The v1 bytes are what the historical evidence was produced against.
- Their SHA-256 values sit in `resource_manifest.json`:
  `2b8cc13e…` (source) and `33073748…` (assumptions).
- The repository already has a precedent: ESO assumptions v1 → v2, with
  top-level `supersedes` and `revisions`, and v1 still validated in
  `tests/io/test_eso_scao_profiles.py`.

**Hashes and identities.**

| Identity | Effect of publishing the two v2 files (profiles untouched) |
| --- | --- |
| v1 ledger digests | unchanged (must be checked, ACCEPTANCE_PLAN A1) |
| profile `config_hash` (`tests/io/test_configs.py` pins) | unchanged: no profile file changes. Repointing `provenance.references` or editing `@2`'s `baseline_rationale` **would** move them, because both are inside the hashed mapping (`io/configs.py` `system_config_to_mapping`) |
| physical sensor `config_hash` | unchanged: `UNCERTAINTY_MODEL_ID` is unchanged |
| ESO benchmark record `ledgers` digests | unaffected: they digest the ESO ledgers only (`experiments/eso_scao_benchmark.py:551`) |
| governed-runner code identity (`run_detector_level_evidence.py` series protocol 4, `eso_scao_paired_convergence_study.py` run protocol 2) | **changes for new runs**: `_package_sha256` digests every non-hidden file of the imported package, resources included. A resume across the change is refused, by design. No committed record changes. Do not land the change in the middle of a governed series |

**Manifest and packaging.**

- `resource_manifest.json` gains two records and keeps the v1 records. It
  is rendered by `render_resource_manifest`, which the generator's
  `write_resource_manifest` calls.
- `tests/io/test_resources.py` requires the manifest to list every
  resource and to equal the rendered text.
- The build alias (`build_support/resource_alias.py`) refuses a manifest
  that differs from the inventory.
- CI runs `git diff --exit-code` on the manifest after the tests.
- `pyproject.toml` packages `benchmarks/*.json`, so the v2 files enter the
  wheel and the `ao_simulation_data` alias without packaging edits. The
  wheel gate should still confirm this.

**Schema.**

- Both v2 files can stay `schema_version` 1. Every proposed source entry
  keeps exactly the nine `_SOURCE_FIELDS`. Rows use only existing fields.
  The new keys are top-level, which the loader does not validate.
- Structured per-source verification fields would need `_SOURCE_FIELDS`
  extended and a schema version raised. That is a loader change (D-9),
  and no candidate needs it.

**Code compatibility.** Nothing loads the detector ledgers implicitly.
`load_source_ledger()` and `load_assumption_ledger()` default to the ESO
files, and the detector ledgers are loaded by explicit name, in
`tests/io/test_detector_level_ledgers.py` only. Callers of v1 keep
working. The generator is the one consumer that must change, because it
writes and byte-checks the assumption ledger (D-8).

## 7. Integration specification for the later change

Not authorized by this assignment. Recorded so the later bounded task can be
scoped exactly (`CANDIDATES.json` `integration_changes_required_later`).

1. **I-1, generator** (`scripts/generate_detector_level_profiles.py`). Emit
   the v2 assumption ledger, and either keep v1 reproducible from frozen
   literals or freeze it outside the generator with a byte-pin test (D-8).
   Leave `LEDGERS`, the profile references, unchanged for existing profile
   versions. Keep `--check` exiting 0.
2. **I-2, resources.** Add `detector_source_ledger.v2.json`, hand-authored
   as v1 was, and `detector_level.assumptions.v2.json`, generated.
3. **I-3, manifest.** Regenerate through the generator. Two new records.
4. **I-4, tests** (`tests/io/test_detector_level_ledgers.py`):
   - validate v2 against the eight profiles, with the same coverage
     assertions;
   - keep v1 validated as history, following the ESO pattern;
   - assert that only the declared fields differ;
   - assert that B14 names `noise_model.UNCERTAINTY_MODEL_ID`, so a
     future identifier change cannot silently leave the ledger stale.
5. **I-5, documentation.** Point `docs/technical_reference.md` §7.1
   (assumption ledger) at v2 and label v1 as history. Correct the estimator
   and [Tho06] rows (OBS-4). Close G11 in `docs/roadmap.md` with the
   acceptance record (D-10).

## 8. Decisions left open

None of these is decided here. Where a recommendation is given, it is a
research recommendation, labelled as such.

| ID | Decision | Options | Research recommendation |
| --- | --- | --- | --- |
| D-1 | Publish v2 files beside byte-frozen v1? | v2 files (G11's route); documentation only | v2 files: the only route that corrects the packaged text without moving any identity |
| D-2 | Profiles keep referencing v1? | keep; new profile versions referencing v2 | keep: new profile versions would move config hashes and every downstream identity for a wording change |
| D-3 | `ledger_id` of the v2 files | unchanged; versioned (`…v2`, ESO precedent) | none. No test pins either detector ID |
| D-4 | B18 title | retitle (C09); keep the historical title (C10 alone) | retitle: a title is read as current semantics |
| D-5 | Expand B14/B18 `consuming_tests` | yes (C08); no | yes for B14. For B18, keep the shared list or split `_TESTS["model"]` |
| D-6 | `frozen` in v2 | keep 2026-10-15 and add a `revised` date; set to the acceptance date | none (OBS-2) |
| D-7 | D4 variant | A now; wait for a full-text read and accept B | A now; B later as a further version if the read adds locators |
| D-8 | Generator and v1 | render both from one script; freeze v1 outside the generator | none. Either must keep v1 byte-identical and `--check` at 0 |
| D-9 | Structured verification fields | none (no schema change); extend the loader and schema | none needed for these candidates |
| D-10 | Comments and documentation (OBS-3, OBS-4) | with the resource change; separately | separately for the runtime comments (a source edit); with the change for the documentation links |

## 9. Observations outside G11 (no candidate)

- **OBS-1, D2.** `limitations[0]` says a web search "did not return the
  DOI". The technical reference's [Rob03] row says "the ledger's open DOI
  question is now confirmed" but names no record. Not verifiable here, since
  Crossref was denied.
- **OBS-2, `frozen`.** The assumption ledger says `frozen: 2026-10-15`, but
  B20 and B21 were added at `ea775bc` on 2026-10-16.
- **OBS-3, comments.** These comments still name v1 as the `@2` gating
  domain: `io/configs.py:109–110`, and `generate_detector_level_profiles.py`
  lines 21–22 and 273. They are historical descriptions that read as
  current. Line 304 of the generator lies inside the pinned `@2`
  `baseline_rationale` literal and must not change.
- **OBS-4, technical reference.**
  - Its estimator row (§5.6, line 517) cites "thresholding is not
    first-order linear (Thomas et al. 2006)".
  - Its [Tho06] row (§8.1, line 922) repeats the claim.
  - Its §7.1 link (line 748) names the v1 ledger as current.
  - All three follow C02 and the acceptance.

## Appendix A. Window dependence of the centre-of-gravity photon-noise variance

Independent derivation for this specification (`ANALYTIC_ESTIMATE`; nothing
was executed). It is not a reading of [Tho06]. It shows only that a
"finite-field" condition is necessary for a diffraction-limited spot, and
that the implemented lever-arm form contains it.

For a plain centre of gravity over a window `W` with expected counts `μ_k`
and Poisson noise only, the first-order variance per axis is
`Var(c_x) = Σ_W (x_k − c_x)² μ_k / (Σ_W μ_k)²`. That is the photon term of
`detector.validity._first_order_cog_sigma_px`, and that of
`noise_model.quadratic_form` with `G = F = 1`. In the continuum limit,
`Var(c_x) = ⟨(x − c_x)²⟩_W / N`, with the second moment of the normalized
spot taken over the window and `N` the detected photons.

- **Gaussian spot**, rms width `σ_G`: `⟨x²⟩_W → σ_G²` as the window grows.
  With FWHM `N_T` pixels and `N_D` pixels per `λ/d`, the phase-difference
  variance across the subaperture (`φ = 2π x`, `x` in `λ/d`) is
  `σ_φ² = (π² / (2 ln 2)) (N_T/N_D)² / N` rad². It is finite for an
  unbounded field.
- **Diffraction-limited square subaperture**, intensity `sinc²(x) =
  sin²(πx)/(πx)²` per axis, `x` in `λ/d`:
  `∫_{−W/2}^{W/2} x² sinc²(x) dx = (1/π²)[W/2 − sin(πW)/(2π)]`, which grows
  linearly with the window width `W`. The variance therefore diverges for
  an unbounded field. For `W ≫ 1`, `⟨x²⟩_W ≈ W/(2π²)`, which gives
  `σ_φ² ≈ 4π² · W/(2π² N) = 2W/N` rad².

The diffraction case equals the expression the [S24] search summary
attributes to Thomas et al. That agreement is consistent with T2/T3 but
does not verify them. Both cases follow from the lever-arm sum that the
repository evaluates exactly over its declared window. That is why the
proposed D4 and B14 wording can state "no spot-shape or field assumption"
of the implementation without relying on the paper. A proposed numerical
check, **not run** (research-only scope): evaluate the compatibility
sigma for pixel-integrated `sinc²` spots over windows of 5–41 λ/d. Expect
it to grow linearly with `W` at slope `1/(2π² N)` in `(λ/d)²`, and a
Gaussian spot's to converge.

## Appendix B. Static validation of the proposed records

Script, kept outside the repository:
`/tmp/claude-0/-home-user-Shack-Hartmann-AO-Simulation/5eebd649-9ac8-5f0a-84a4-97fbe6a492c1/scratchpad/validate_candidates.py`.
Run as `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 validate_candidates.py .`
on the source commit, with system Python 3.13.16 and NumPy 2.5.3. SciPy
was not installed, and the ledger code does not import it. This is not the
project's locked environment. It writes nothing.

1. It recomputes both v1 digests.
2. It checks that every `current_value` equals the v1 bytes.
3. It materializes variant A in memory, then runs the repository's
   `validate_source_ledger` and `validate_assumption_ledger`, and
   `validate_benchmark_profiles` against the eight packaged profiles.
4. It checks that only the declared fields differ, the semantic and
   placeholder conditions, and that every consuming test resolves to a
   function.

Result: **33 checks, 0 failures, exit 0.** Profile coverage of the v2
records equals v1's for all eight profiles. No test suite was run.
