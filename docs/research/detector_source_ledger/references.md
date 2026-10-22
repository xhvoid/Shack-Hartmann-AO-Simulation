# Sources and access limits for detector-ledger corrections

Research record for roadmap item G11 (pre-refactor audit F-08; AR-008 in
the later review, whose report is not available here). Written
2026-10-20 on task branch `claude/fervent-einstein-4g3syq`, from source commit
`10f04e268871a19bfedb47b035f2905b67f23e43` (`claude/cleanup-refactor-exec`).

Access status vocabulary: `full text checked`, `relevant passage checked`,
`abstract only`, `search summary only` (a web-search tool's generated summary
of result pages, never a page this session opened), `secondary confirmation`,
`inaccessible/unverified`. A search summary is not a reading. No claim in the
correction specification rests on one.

## 1. Research access limits (2026-10-20)

Every route to the primary text was closed by the environment's network
policy. This is an environment limit, not evidence about the paper.

| Route | Attempt (2026-10-20) | Result |
| --- | --- | --- |
| DOI resolver | `curl https://doi.org/10.1111/j.1365-2966.2006.10661.x` | proxy `CONNECT` 403 (`connect_rejected`), host `doi.org` |
| Crossref metadata | `curl https://api.crossref.org/works/10.1111/j.1365-2966.2006.10661.x` | proxy `CONNECT` 403, host `api.crossref.org` |
| Publisher, arXiv, ADS, HAL, Semantic Scholar, ResearchGate, Google Scholar, CORE, Europe PMC | `curl https://<host>/` | connection refused by the proxy for every host |
| WebFetch tool | `academic.oup.com/mnras/article/371/1/323/1009797`, `arxiv.org/a/fusco_t_1`, `en.wikipedia.org/...` | `getaddrinfo ENOTFOUND` for every host, including the control host |
| Reachable hosts | `github.com`, `raw.githubusercontent.com`, `pypi.org` | reachable; none hosts an authoritative copy of the paper |
| WebSearch tool | the five queries in section 4 | summaries and result URLs only |

A future primary-source check requires access to the publisher or a retained
copy of the paper. The denied requests above describe the original research
environment, not the current availability of those sources.

## 2. Primary source under correction

### [Tho06] Thomas et al. (2006), ledger D4

- **Record.** S. Thomas, T. Fusco, A. Tokovinin, M. Nicolle, V. Michau,
  G. Rousset, "Comparison of centroid computation algorithms in a
  Shack–Hartmann sensor", *Monthly Notices of the Royal Astronomical Society*
  371(1), 323–336 (2006). DOI `10.1111/j.1365-2966.2006.10661.x`.
- **Bibliographic confirmation:** `search summary only`. Title, authors,
  volume, issue and pages agree across the search listings (Semantic Scholar
  entry `b34e34809da79e47660411e0ff6bc8aedf5cb658`; the OUP landing page
  <https://academic.oup.com/mnras/article/371/1/323/980402>; a citing paper's
  reference list). The DOI was **not** resolved here: `doi.org` and
  `api.crossref.org` were denied. The ledger's D4 entry and the technical
  reference's [Tho06] row carry the same record. The repository's own ledger
  says only that D4's bibliographic details were "confirmed by web search" in
  the implementing session (`access_note`, 2026-10-15). No session has
  recorded a full-text read.
- **Content: `inaccessible/unverified`.** The abstract-level content that
  the search summaries relay is that the paper combines analytical theory with
  numerical simulations to compare thresholding, weighted centroid,
  correlation and quad-cell estimators, defining optimal parameters as
  functions of photon flux, readout noise and turbulence. No section,
  equation or appendix text was read.
- **Locators that remain to be checked in full text** (each a claim made
  somewhere in the repository or its audits, none verified):

  | Claim ID | Claim | Where it is made | Status |
  | --- | --- | --- | --- |
  | T1 | "their analytic forms assume Gaussian spots" | `detector_source_ledger.v1.json`, D4 `limitations[0]` | `inaccessible/unverified`; overbroad as written (section 3 of the specification) |
  | T2 | "their section 3.1 (equation 13, Appendix A) treats diffraction spots" | `docs/roadmap.md` G11, attributed to audit F-08 | `inaccessible/unverified`; secondary to this session (the F-08 report is not available) |
  | T3 | for a diffraction-limited spot, the centre-of-gravity photon-noise error depends on the finite field (window) | named in this assignment; also relayed for [Tho06] by a citing paper (section 3), search summary only | `inaccessible/unverified` at primary level; agrees with the independent derivation in the specification, appendix A |
  | T4 | "thresholding is not first-order linear" | D4 `supports[0]`; `docs/technical_reference.md` estimator row, [Tho06] row | `inaccessible/unverified` as a statement of the paper; it is the repository's own rule (`detector.noise_model` reports thresholded estimators unsupported; `detector.validity` states that its first-order sigma does not model thresholding) |
  | T5 | the weighted-centroid correction factor is computed analytically for a Gaussian spot | a citing arXiv paper, search summary only | orientation only; it would mean the paper uses a Gaussian spot in at least one closed form, which makes "assume Gaussian spots" partly true and overbroad, not simply wrong |

- **Candidate open copies, identity unconfirmed.** A search summary called
  `https://hal.science/hal-03801136v1/document` a HAL-hosted copy of the
  paper. A direct search for that identifier returned nothing about it.
  Treat the route as unverified. The arXiv listing `astro-ph/0606388`
  surfaced in one search. A later summary said it is a different Tokovinin
  paper (on extrafocal "donut" wavefront sensing). It is not a route to
  [Tho06] unless checked.

## 3. Secondary sources (orientation only, nothing rests on them)

| ID | Source | What reached this session | Access | Use in this record |
| --- | --- | --- | --- | --- |
| [S24] | "Performance comparison of the Shack-Hartmann and pyramid wavefront sensors with a laser guide star for 40 m telescopes", arXiv:2410.04863 (authors not confirmed here) | a search summary saying that "Thomas et al. (2006) showed that the centroiding error due to photon noise is dependent on the Field of View (FoV) of the subapertures", with an approximation σ² ≈ 2W/n_ph (W in λ/d units, n_ph photons per subaperture and frame), "better for bigger FoV of several λ/d" | `search summary only` | a pointer for the T3 check; the same expression follows independently in the specification, appendix A |
| [Cit] | a citing arXiv paper on weighted centre-of-gravity design (among 0903.4165, 0908.4328, 1404.2294 in the results; not identified with certainty) | a search summary saying Thomas et al. computed a γ correction factor analytically for a Gaussian spot | `search summary only` | a pointer for T5 |

## 4. Search log

All on 2026-10-20 with the WebSearch tool; no result page was opened.

1. `Thomas Fusco Tokovinin Nicolle Michau Rousset "Comparison of centroid computation algorithms in a Shack-Hartmann sensor" arXiv` (standard): journal record and abstract; no arXiv copy.
2. `Thomas 2006 MNRAS 371 323 centroid Shack-Hartmann "diffraction-limited" spot centre of gravity photon noise appendix finite field of view` (extended): OUP landing URL, ResearchGate listing; no appendix text.
3. `hal.science "Comparison of centroid computation algorithms in a Shack-Hartmann sensor" Thomas Fusco ONERA` (extended): Semantic Scholar listing; no HAL record.
4. `"Thomas et al. (2006)" centre of gravity photon noise diffraction-limited spot variance depends on number of pixels field window sinc` (extended): [S24] statement; candidate `hal-03801136`.
5. `"astro-ph/0606388"`, `"hal-03801136"`, `arxiv.org/abs astro-ph 2006 Thomas Fusco Tokovinin "centroid computation algorithms" Shack-Hartmann` (standard): no confirmation of either candidate; the [Cit] statement.

## 5. Repository sources read (current tree, `INSPECTED_CURRENT`)

Digests are in [`input_manifest.json`](input_manifest.json).

| Source | Locator | What it establishes |
| --- | --- | --- |
| `src/shwfs_ao/detector/noise_model.py` | module docstring; `UNCERTAINTY_MODEL_ID` (line 99); constants (lines 105–115); `detector_covariance_quality` support gates (lines 428–470) | current semantics of `detector_covariance_v2`: the realized-master conditional mean, both ADC limits with 5σ headroom, per-pixel half-step quantization, saturation at 90 %, positive window total, `SNR_T ≥ 7` |
| `src/shwfs_ao/wfs/shack_hartmann/physical_measurement.py` | lines 245–256 (sensor `config_hash` binds `uncertainty_model`), 732–736 (validity gates) | the model ID enters the physical sensor identity; an unsupported block fails `max_centroid_sigma_px` through the undefined sigma |
| `src/shwfs_ao/detector/validity.py` | `centroid_quality` docstring (lines 192–238), `_first_order_cog_sigma_px` (lines 429–462) | the compatibility path's first-order CoG sigma: per-pixel lever arms over the actual window, no spot-shape model |
| `src/shwfs_ao/experiments/detector_noise.py` | `with_source` (line 268) | E1 Monte Carlo fixtures use a centred Gaussian spot (σ = 1.2 px) |
| `src/shwfs_ao/io/benchmark_ledgers.py` | `_SOURCE_FIELDS`, `_ROW_FIELDS`, `_ROW_OPTIONAL`, validators | source entries need exactly nine fields; rows allow four optional fields; top-level ledger keys are not validated |
| `src/shwfs_ao/io/configs.py` | lines 101–114 (profile registry and comments); `ProfileProvenance.config_hash`; `system_config_to_mapping` (profile name, version, `baseline_rationale` and provenance are hashed) | profile `provenance.references` and `baseline_rationale` are inside the pinned profile identity |
| `scripts/generate_detector_level_profiles.py` | `LEDGERS` (line 55), `LEDGER_PATH` (line 405), `_TESTS["model"]` (line 437), rows B14 and B18 (lines 531–548, row calls at 531 and 545), `write_ledger` (`--check`) | the assumption ledger v1 is generated and byte-checked; B14 and B18 share one consuming test |
| `scripts/run_detector_level_evidence.py`, `scripts/eso_scao_paired_convergence_study.py` | `_package_sha256`, `code_identity` | every non-hidden package file, resources included, enters the code identity of new governed runs |
| `tests/io/test_detector_level_ledgers.py`, `tests/io/test_resources.py`, `tests/io/test_configs.py`, `tests/io/test_eso_scao_profiles.py` | constants and assertions | the v1 names are pinned; the manifest must list every resource; profile hashes are pinned; the ESO v1→v2 ledger precedent |
| `src/shwfs_ao/resources/benchmarks/eso_drm_42m_scao_derived.assumptions.v2.json` | top-level `ledger_id`, `supersedes`, `revisions` | the repository's precedent for a new ledger version that keeps v1 as history |

## 6. Repository sources read (history, `INSPECTED_HISTORICAL`)

| Source | Locator | What it establishes |
| --- | --- | --- |
| `docs/refactor/DETECTOR_LEVEL_DEVELOPMENT_STATUS.md` | DET-07 (`detector_covariance_v1`, 2026-10-15); "Ledgers" (D1, D4, D5 checked by web search); "Fixes, finding by finding" (R2, R4; "The id is now `detector_covariance_v2`"; "Old records … keep the old identities"); "Effect of the fixes" ("E2-12m, E3, E4, E6, DET-08, E5, the recovery and excursion studies, and the `@3` reruns were produced by the reviewed code (model v1)"); "12 m review reruns: results" | the v1→v2 transition and which evidence each version produced |
| `docs/refactor/CLEANUP_REFACTOR_STATUS.md` | "Post-audit reconciliation (2026-10-18)", unit A (F-01: identifier kept `detector_covariance_v2`) and unit E ("packaged ledgers (F-08) deferred to a governed resource version") | G11's origin and the deferral |
| `docs/roadmap.md` | G11 row | the problem statement and the requested outcome ("current semantics, historical producer version and source scope are distinct and correct") |
| `git log` | `a31099b` (2026-10-16 07:50, v1 model and ledgers), `ea775bc` (19:26, B20/B21 added, `frozen` left at 2026-10-15), `573f875` (23:14, v2) | the ledgers' last content change predates v2 |

## 7. Missing inputs

None of these is in the tracked tree. All lie under the git-ignored `outputs/`.

| Input | Expected location | Consequence |
| --- | --- | --- |
| pre-refactor audit report with finding F-08 | `outputs/pre_refactor_audit/20261017T143700Z/` (main checkout, tree `f09eb16`) | G11's T2 locators (section 3.1, equation 13, Appendix A) cannot be traced to what that audit read |
| AR-008 | a review run under `outputs/audit_reconciliation/` (the ID does not occur anywhere in the tracked tree) | its exact wording, including any finite-field statement, is unknown; T3 is reconstructed from this assignment's text |
| Reconciliation run records | `outputs/audit_reconciliation/2026-10-18-claude-27f34fa/` and the 2026-10-19/20 runs | the ledger status of F-08 (open, deferred) is known only from the status file |
| [Tho06] full text | publisher, or an open copy | T1–T5 stay unverified (section 1) |
