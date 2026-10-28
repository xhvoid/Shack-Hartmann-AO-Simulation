# Explorer acceptance record

Final independent review on 23 October 2026:
**ACCEPT_WITH_DECLARED_VALIDATION_LIMITS**, with no open finding at any priority
(P0, P1, P2 or P3). The debugging/review cycle is complete.

| Identity | Value |
| --- | --- |
| Reviewed candidate | `2d659522da6d9a829982cefc14bed4c38060442f` |
| Reviewed tree | `7d6f2b60f40a733017a3edfc160c492bcd4190bb` |
| Records-only successor | `d8a51b90e12d11175f8c78ecb3d29527ffcb22a8` |
| Candidate branch | `ao-explorer-v1` |
| Dataset | `series-2m180-b3e1c66-e0d60cbaccc6b` |
| Manifest SHA-256 | `4c0896afc83c84226143055c2c287ea57a655466cd63c971150c7efd05858a3d` |
| Frontend build | `7c04e5cefab85e8b` |
| Freeze-record SHA-256 | `0042e9e9bbcc0664e7b26fbef9cd1445f7663516a0c503ce13c0b5616eac5699` |

The successor changes only three Markdown records. Publication preparation
verified that its scientific code, tests and entire website equal the reviewed
candidate. The successor was not independently re-reviewed. The candidate had
no tracked modifications; the original specifications were untracked and are
retained locally. The tracked [release requirements](RELEASE_REQUIREMENTS.md)
carry their essential contracts into fresh and cloud checkouts.

## Evidence executed by the final reviewer

These are historical reviewer results, not claims of publication-session runs:

- Fresh archive: 1284 validator checks; 64 tests passed and 11 checks skipped (eight need retained
  evidence and three need Git history). With retained evidence: 1394 checks and 75 tests passed.
- All eleven tested removals of source-digest protections failed as intended;
  a 33-case hostile Git-configuration matrix preserved the expected digest.
- Twenty-three rehashed science-metadata fixtures behaved as specified offline
  and in the browser; clean controls installed.
- Cached-version transitions at root and project subpath refused a mixed build
  explicitly, then installed coherent new code.
- Case/research downloads and the results inventory matched manifest bytes;
  132 source links were checked. No external runtime request was observed.
- First usable view: 1,332,997 bytes. Retained processing ledger: 35 entries,
  27 launches, 153.409918 s and 177,694,247 B (169.46 MiB).

The full freeze, findings, mutation, browser and resource records remain in the
maintainer's ignored review archive. They are not shipped as private working
logs. Stable finding IDs are mapped in [REPAIR_LOG.md](REPAIR_LOG.md).

## Declared limits retained for publication

- One short seed-1 realization; seed 2 is sensitivity only. The 140-frame PSF
  average is a frame-start snapshot quadrature, not a converged long exposure
  or finite-shutter integration. The binary is illustrative and has no added
  science-camera noise or detection significance.
- Research results retain original source-specific domains. The 12 m
  inverse-photon test failed with unexplained departures. Reduced-scale HCIPy
  axis evidence is summary-only and full-scale confirmation remains pending.
  Backend agreement rests on one small fixture; ESO-tier convergence does not
  establish detector-profile convergence. S2 used an unretained driver.
  The analytical adapter has unknown original producer/date and estimator bias.
  None of these results is hardware or on-sky validation.
- The final reviewer used one Chromium pane with rendering suspended. Reduced
  motion was not emulated. Git probes used 2.50.1; Git <2.42 and SHA-256
  repositories are declared fail-closed. Python 3.10 runtime and remote CI had
  not run at acceptance because the candidate was unpushed.

Publication verification and remote CI are recorded separately in the release
PR and deployment record; skipped checks do not become passes.
