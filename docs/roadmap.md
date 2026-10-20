# Current roadmap

Written 2026-10-18 for the tree recorded in the
[cleanup execution record](refactor/CLEANUP_REFACTOR_STATUS.md) (entry
revision `2312502`). This page lists the open scientific questions and
engineering tasks, the evidence each one needs, and what would count as done.
What the implementation does now is explained in the
[technical reference](technical_reference.md); its known boundaries are in
the [limitations register](current_limitations.md).

Items are not commitments. Every item that is a governed run (a medium/12 m
or 42 m run, a multi-seed batch above 30 minutes, or a polychromatic study
above the `ci` tier) still needs the user's explicit enablement for that
concrete run. Costs are categories, not quotes:

| Cost category | Meaning on the 16 GiB development desktop |
| --- | --- |
| C0 | documentation or code reading only |
| C1 | bounded tests or 2 m / `ci` fixtures, minutes |
| C2 | one governed 12 m study, roughly 1–3 hours serial |
| C3 | one governed 42 m realization, roughly 1 hour and 1.6–2.0 GiB |
| C4 | several 42 m realizations or a full convergence study, many hours |
| C5 | new model implementation plus validation, or external data |

Priorities: **P1** blocks a stated claim from being quoted on current code;
**P2** removes a recorded scientific gap; **P3** improves scope or
maintainability.

## Two results to keep visible

Neither changes through rewording; only a new evidence record can move them.

- **The 42 m noise-on result now has a realization ensemble.**
  `det_ccd_42m_r3band_derived@1`, 2000 frames (burn-in 200), root seed 1, one
  realization: 173.2 nm residual, long-exposure Strehl 0.753 at 2.2 µm,
  1.749 s per frame, 1.61 GiB peak. The run started on 2026-10-16 at 02:51
  CEST, before the review fixes (`573f875`, `580e83f`, `62c0092`). Its record,
  [`det09_e5_42m_noise_on.json`](refactor/detector_level_evidence/det09_e5_42m_noise_on.json),
  predates the runner's code-identity field. Its rerun on current code (S1,
  2026-10-18, revision `2312502`) reproduced every recorded value bit for bit:
  [`det09_e5_42m_noise_on_current_2312502.json`](refactor/detector_level_evidence/det09_e5_42m_noise_on_current_2312502.json).
  Ten further realizations on the same code (S2, root seeds 2–11) give
  173.6 ± 0.9 nm and Strehl 0.751 ± 0.002 (sample standard deviations); seed 1
  is typical of them. The ensemble is one profile and one configuration, and
  every run repeats the fastest layers' periodic bands (LIM-08, S11).
- **The 12 m pure inverse-photon law failed.** The isolated detector-noise
  variance at 12 m scales as N_e^(−1.028 ± 0.010), 2.7 standard errors from
  −1: a failure of the predeclared test. The noise model predicts a steeper
  −1.097, from read noise and clock-induced charge over the 15 × 15 window.
  The 2 m slope, −0.978 ± 0.014, passes. The departures stay recorded as
  unexplained (S4).

## Scientific queue

| ID | Question | Affected path | Proposed experiment | Evidence needed | Success criterion | Priority | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S1 | Does the 42 m noise-on result hold on the current code? | `det_ccd_42m_r3band_derived@1`; `scripts/run_detector_level_evidence.py e5` | The same configuration, seed 1, 2000 frames, summary telemetry, regenerated atmosphere bands, written to a new record with `--output-dir` | A new record whose code identity names the current revision | The record exists; any change from 173.2 nm / 0.753 is reported with its cause, not tuned away. **Met 2026-10-18:** bit-identical | P1 | C3 |
| S2 | How large is the realization scatter at 42 m? | same profile | Five, then ten, serial realizations (new root seeds), each in a fresh process | Per-seed residual and Strehl, seed scatter, per-run peak RSS | Mean and seed standard deviation reported; no ensemble claim before this exists. **Met 2026-10-19 (producer `2312502`, clean):** seeds 2–11 give 173.59 ± 0.94 nm and Strehl 0.7511 ± 0.0018 (sample SD; SE 0.30 nm and 0.0006), no lost lock, lowest per-frame valid fraction 0.982, 1.68–1.97 GiB per fresh process; seed 1 (S1) is typical (z = −0.4). Records `det09_s2_42m_seed2.json` … `seed11.json` | P2 | C4 |
| S3 | Are quoted metrics converged in spatial sampling? | `eso_scao_*` tiers, the 12 m detector profiles | Refine pupil, WFS and science sampling one at a time, holding the physical field of view fixed, with paired atmospheric inputs | Metric changes with uncertainty at medium and full scale | Changes below the declared 2 % Strehl/EE50 criterion, or the quoted scale is restated as unconverged. **Done for the ESO tiers (runs 2026-10-18, recorded 2026-10-19; producer `2312502`, `scripts/eso_scao_paired_convergence_study.py`, records `paired_convergence_medium.json`, `paired_convergence_full.json`):** peak Strehl converged in pupil, WFS and science sampling at 12 m and 42 m (finest two within 0.25 %); EE50 converged in pupil and WFS sampling, pixel-limited in science sampling (pad 2 reads 7.3 % high at 12 m and 3.6 % at 42 m against pad 4; at 12 m pads 3 and 4 still differ by 4.3 %), so pad-2 EE50 values are restated as unconverged. Not covered: the 12 m detector profiles and pupil sampling above 16 at 42 m | P2 | C4 |
| S4 | Why does the noise law depart from the model? | `experiments.detector_level.paired_noise_run`, `detector.noise_model` | Repeat the 12 m points near m_AB 9–10 with more seeds; split ΔV by lenslet SNR, clipping and support flags; compare with the per-lenslet model sum | Isolated ΔV per lenslet class with uncertainty | The 6.7 % dip and the 0.95–0.96 power are explained, or bounded and kept as unexplained | P2 | C2 |
| S5 | What sets the faint-end limit, camera or control? | `det_emccd_12m_medium_derived@3`, `controller.recovery`, reconstructor damping | Scan m_AB 11–12 with predeclared damping, gain and recovery arms; inspect validity and reconstruction telemetry, not the `lost_lock` heuristic alone | Per-frame validity, usable fraction and residual telemetry | A limit attributed to sensing (no lenslet in the supported domain) or to control, with evidence | P2 | C2 |
| S6 | Is the 42 m profile under-regularized like 12 m @2? | `det_ccd_42m_r3band_derived@1` (Tikhonov damping 0.001, like @2) | Diagnose waffle-mode response and damping on the `ci`/12 m derived geometry first; then a gated 42 m arm if warranted | Singular spectrum and waffle response at 42 m geometry | Either damping is shown adequate at 42 m, or a new profile version is proposed with its own predeclared evidence | P2 | C1, then C3 |
| S7 | Can the published 10 m profiles demonstrate stable correction? | `high_order_10m_geometric@3`, `high_order_10m_hcipy@3` (gain 0.65 at two frames of latency, above the 0.618 limit) | New profile versions with a stable gain and, for HCIPy, a window that keeps broadened spots; the paired lenslet-axis confirmation at the published scale | Locked closed-loop evidence over several seeds | Stable sustained correction; the strict expected-failure guards stay on the old versions | P2 | C2 |
| S8 | How well does a fixed detector cope with spot motion, truncation and loss? | `detector.layout`, `wfs.shack_hartmann.physical_measurement`, `backends.hcipy.shwfs` | Hold hardware, alignment and photon budget fixed; measure displacement-to-slope response through clipping, crossing and loss; compare estimators | Bias, scatter, dynamic range and misidentification rates against simulation truth | A characterized response curve and false accept/reject rates for an estimator that uses only observable data | P2 | C2 |
| S9 | Does inter-lenslet light change the physical-camera results? | native physical camera (`isolated_lenslet_blocks.v1`); HCIPy fixed blocks | A shared detector-plane model with overlapping spots; matched native/HCIPy comparisons | Paired results with and without contamination | Effect sizes reported; physical-camera HCIPy parity stated only for what was compared | P3 | C5 |
| S10 | Does the model predict measured data? | whole chain | Laboratory or on-sky telemetry, PSFs and calibrations under matched conditions | Measured dataset with uncertainties | Agreement within stated uncertainty, or documented discrepancies | P3 | C5 |
| S11 | Are long-run statistics independent enough? | `native_layered` periodic band (`periodic_band_repeated`) | Compare long-exposure metrics with and without band repetition (longer screens or split realizations) | Metric change attributable to repetition | Repetition shown negligible for the quoted metric, or the run length is limited | P3 | C2 |

## Engineering queue

| ID | Problem | Affected path | Proposed change | Evidence needed | Success criterion | Priority | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| G1 | The local commits since `origin/main` have never run in CI; an HCIPy-lane fixture failure from `a31099b` went unnoticed until this cleanup, and the wheel lane's README native smoke would fail (inferred, no CI log inspected) because README examples were never in the portable bundle: `run_eso_scao_benchmark.py` already on `origin/main` (`2e96d86`), `run_detector_level_demo.py` in the local commits (F-08, fixed by U7 in this cleanup) | `.github/workflows/ci.yml`, all lanes | Push the reviewed commits (the user's decision) and run every lane: source 3.10/3.14, wheel 3.10/3.14, HCIPy 3.11, scheduled | Green CI logs for the exact pushed revision | Every lane passes, or each failure is triaged with a recorded cause | P1 | C1 |
| G2 | The resource guard's Linux subreaper path and the Python 3.10 execution of its latest fixes are unverified | `shwfs_ao.runtime.resource_guard`, `tests/runtime/test_resource_guard.py` | Run the guard tests on Linux and Python 3.10 (CI) | CI logs | All guard tests pass on Linux and 3.10 | P2 | C1 |
| G3 | Noisy interaction calibration replays exactly within one host but does not select the same noise streams across hosts | `calibration.interaction` (scope key binds the calibration context hash) | Key noisy calibration draws on declared inputs only, as the detector-level sensor already does; this moves noisy-calibration identities, so it needs its own reviewed change and candidate baselines | Cross-host replay test | Same streams on two hosts for one seed; identities change only with a recorded rationale | P3 | C1 |
| G4 | `science_run` reports `ru_maxrss` as `process_peak_rss_bytes`, a process-lifetime high-water mark, so later runs of a series in one process report the series peak, not their own | `experiments.detector_level.science_run`, the evidence runner | Keep the field (records depend on it); add an opt-in fresh-process mode, or a separately named per-run sampler | Per-run peaks in fresh processes | Per-run memory claims cite a per-run measurement | P3 | C1 |
| G5 | Phase B removal of the root shims and the `ao_simulation_data` alias | `shwfs_ao/resources/deprecation_clock.json`, `src/*.py`, `shwfs_ao.legacy` | Publish release 0.2.0 and a later minor release first; Phase B is a separate release-bound change | Both release boundaries recorded in the clock | `removal_boundaries_satisfied()` true before any deletion | P3 | C1 |
| G6 | Local evidence runs use an environment that is not the constraint lock (numpy 2.5.0 against the pinned 2.5.1) | `.venv`, `constraints/py314.txt` | Re-create the evidence environment from the lock before governed runs | `scripts/verify_environment_lock.py` passes | Governed records name a locked environment | P3 | C1 |
| G7 | Two unmerged cleanup branches from 2026-10-17 (`claude/bold-shirley-6f1e9f`, `claude/trusting-bell-471569`) overlap this cleanup | git branches | The user decides to merge, supersede or delete them; this cleanup did not use them | — | One current line of history | P3 | C0 |
| G11 | The packaged detector ledgers describe superseded or overbroad sources: B14 names `detector_covariance_v1`, and D4 says Thomas et al. (2006) assume Gaussian spots, although their section 3.1 (equation 13, Appendix A) treats diffraction spots (GPT audit F-08) | `resources/benchmarks/detector_level.assumptions.v1.json`, `detector_source_ledger.v1.json` | Publish new ledger versions through the governed resource-update procedure; keep the v1 files as history | Updated ledgers with acceptance records | Current semantics, historical producer version and source scope are distinct and correct. **Implemented 2026-10-20, pending independent acceptance:** `detector_source_ledger.v2.json` and `detector_level.assumptions.v2.json` beside byte-frozen v1 files; the profiles keep referencing v1; D4 was checked against the paper's full text (publisher PDF). G11 stays open until an independent resource and provenance review accepts the change | P3 | C1 |
| G12 | HCIPy long exposures average per-frame unit-sum window images (LIM-19, GPT audit F-04) | `backends.hcipy.propagation`, `science.long_exposure` | If an equal-source-flux exposure is wanted, weight frames by their captured fractions and normalize once, as a new observable | Oracle with known capture fractions | The new observable equals the source-weighted image; the existing one is unchanged | P3 | C1 |


### Closed on the cleanup branch (2026-10-18)

These were open engineering items; each is fixed on
`claude/cleanup-refactor-exec` and recorded in the
[execution record](refactor/CLEANUP_REFACTOR_STATUS.md) (follow-up section).

- **G8** (lint scope): the F401 ignore now lists the 19 root shims by name,
  so the unused-import check covers `shwfs_ao`; the four leftover imports
  were removed. No public name changed.
- **G9** (examples rewriting tracked figures): every example now defaults to
  the git-ignored `outputs/examples/`; refreshing a tracked figure takes an
  explicit `AO_DEMO_OUTPUT_DIR`. A static test keeps every default out of
  `figures/`.
- **G10** (historical enablement notes on new runs): a gated command now
  refuses to run without `--enabled-by-user`, and a resume keeps the series'
  note and records its own beside it.
- **GPT audit F-01, F-02, F-03** (post-audit reconciliation, run
  `2026-10-18-claude-27f34fa`; closed by that run's independent review, whose
  reviewed identity and verdict are in its `ACCEPTANCE.md`): the CMOS
  quantization gate uses each contributing pixel's own read noise and step;
  the component loop's effective exposure quadrature is part of the run
  identity; resumed evidence series bind the producing environment of every
  run (series protocol 3). GPT F-10's docstring is qualified.
- **F-02** (broken `DATA_LICENSES.md` links in the packaged resource
  READMEs, whose bytes AO-REF-001 freezes): the package carries a
  byte-identical copy of `DATA_LICENSES.md` where those links resolve, in
  the checkout and in an installed wheel; a test keeps it identical.

## Historical plans

These files describe earlier states. Their contracts, links and evidence stay
valid where the current code still follows them, but their backlogs and
status lines are not the current plan:

- `AO_REFACTOR_MASTER_TICKETS_REVISED.md` and
  [`repository_optimization_ticket.md`](repository_optimization_ticket.md):
  the original refactor backlog and optimization ticket. Both are untracked
  author files, kept unchanged.
- [`refactor/AO_REF_*.md`](refactor/): the ticket records of the refactor
  that produced the package. Their contract sections (units, identities,
  protocols, tolerances) still describe the code; their status lines and next
  steps are dated.
- [`refactor/DETECTOR_LEVEL_DEVELOPMENT_PROMPT.md`](refactor/DETECTOR_LEVEL_DEVELOPMENT_PROMPT.md),
  [`refactor/ESO_SCAO_DEVELOPMENT_PROMPT.md`](refactor/ESO_SCAO_DEVELOPMENT_PROMPT.md)
  and [`refactor/PRE_REFACTOR_SCIENTIFIC_AUDIT_PROMPT.md`](refactor/PRE_REFACTOR_SCIENTIFIC_AUDIT_PROMPT.md):
  assignments that were carried out. Their outcomes are in the matching
  status files.
- [`refactor/DETECTOR_LEVEL_DEVELOPMENT_STATUS.md`](refactor/DETECTOR_LEVEL_DEVELOPMENT_STATUS.md)
  and [`refactor/ESO_SCAO_DEVELOPMENT_STATUS.md`](refactor/ESO_SCAO_DEVELOPMENT_STATUS.md):
  dated execution records. Their evidence is cited by the technical
  reference; later sections supersede earlier ones where they say so.

## Keeping this page current

Close an item only with a new evidence record or a merged change, and link
it. Moving an item between queues, or changing its priority, needs a reason
written next to it. A structural refactor neither closes nor weakens a
scientific item.
