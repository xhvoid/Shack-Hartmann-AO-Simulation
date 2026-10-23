# Generated-experiment mode: acceptance record

Independent read-only review by a reviewer that did not author the feature,
on frozen candidates of branch `feature/dynamic-phase` (base `main`
`d9e82004693812aeda307999cb2d54ddf85213c1`). The reviewer inspected code,
committed evidence and retained run files and ran targeted checks; it never
changed the repository. Its processing time is in the ledger.

| Round | Candidate | Verdict |
| --- | --- | --- |
| 1 | `6f52c95942b4d80611471ad1e4133ad91d485e61` | NOT_ACCEPTED (one P1, three P2, seven P3; no wrong science found) |
| 2 | `fc9a5c6d10f4967cee56b3f2a1302b1a61c895b3` | ACCEPT_WITH_DECLARED_LIMITS (one new P2, four P3) |
| 3 | `640d698b03862a5837f79080378539eef6c64d04` | ACCEPT_WITH_DECLARED_LIMITS (round-2 dispositions confirmed; three P3) |

This record was completed in a records-only successor of `640d698` that
changes only this file and the ledger copy in `evidence/`; the code, tests,
site and other evidence are those the reviewer accepted.

## Findings and dispositions

| Finding | Disposition |
| --- | --- |
| R1-F01 (P1) service text reached `innerHTML`; a `?backend=` link connected without a click | All page markup is built through an escaping template; the page pins the API-v1 parameter table and fixed scope, accepts identifiers only from a safe character set and file references only as `files/<name>`, filters run-list entries, names the computing service's origin, and connects only after *Connect* (`760366f`). Browser and Node tests inject markup in each of these places. |
| R1-F02 (P2) a second request during a pending submission left an untracked job | Start buttons, *Connect* and *Disconnect* wait for the pending submission; a job whose creation is answered after the page moved on is cancelled (`760366f`, `7c62e88c` build). |
| R1-F03 (P2) a negative `Content-Length` bypassed the body limit | Every POST needs `application/json` and a decimal length of at most 64 KiB (411/413/415). |
| R1-F04 (P2) the page validator was weaker than the Python one | The page checks ranges, the fixed scope, crop centring and scene indices and recomputes the physical identity (Python-compatible float formatting, parity-tested on 2000 random parameter sets by the reviewer); Python gained the crop/scene checks. |
| R1-F05 (P3) the scene's 2:1 ratio was invisible | The caption states the ratio and that both cells are clipped on the shared scale. |
| R1-F06 (P3) a burn-in-only difference was explained poorly | New comparison class *different analysis window*; never paired. |
| R1-F07 (P3) service robustness | Host allow-list (`--allowed-host`), refusal of cross-origin writes from unlisted origins, bounded job history and seed memory, 410 on an eviction race, socket timeout, worker exit when the supervisor disappears. |
| R1-F08 (P3) the web validation record names the earlier build | Kept: it records a raw-evidence validation of build `08dc9a4b5688bf41`. `evidence/site-validation.json` records the structural validation (1290 checks) of the final build `7c62e88c6a00337f` and the command a maintainer with the retained series uses to refresh it. |
| R1-F09 (P3) documentation figures and wording | Corrected (peak memory per run length, request wording, wall-time ranges, correlation metrics, which candidates the explorer tests ran on). |
| R1-F10 (P3, uncertain) commit identity and an environment-named remote branch | Left to the maintainer: the commits use a neutral non-personal identity; the session branch created by the task environment equals the base and has no unique commits; deleting it is the maintainer's call. |
| R1-F11 (P3) disconnect during a download | Loads bind their service and connection; the session's job record is kept until the run is installed or refused. |
| R2-F01 (P2) the 30 s socket timeout bounded whole downloads | Responses are written in 256 KiB chunks, so the timeout bounds stalls only; an interrupted response is closed instead of being followed by an error body. A regression test reproduced the truncation (1.07 MB of 2.09 MB) before the fix and passes after it. |
| R2-F02 (P3) connection changes during a submission | *Connect* and *Disconnect* wait for the submission; polling uses the job's own service; a client-side POST timeout no longer claims that nothing started. A page reload during a submission can still leave a job, which the service abandons after its lease. |
| R2-F03 (P3) missing acceptance record | This record. |
| R2-F04 (P3) loose repeat-attempt logic; planned runs repeated | The pilot prerequisite and the evaluation now require the current producer. Declared: the six planned runs were repeated once because the round-1 repairs changed producer files; every repeated result is byte-identical. |
| R2-F05 (P3) proxies that rewrite `Host`; LAN binding | Documented in [DEPLOYMENT.md](DEPLOYMENT.md). |
| R3-F01 (P3) the round-3 row pointed at missing content | Recorded above. |
| R3-F02 (P3) a tool-named branch in a public document | Reworded (R1-F10 row). |
| R3-F03 (P3) pressing Connect with an invalid address while connected stops following the current job | Declared, not changed after acceptance: the previous service stays usable and reconnecting to a valid address re-attaches the job of this session. |
| CI-1 (requested CI run on `58527f5`) the lint job's rule against `sys.path.insert` outside the tests failed on the three script entry points | The scripts load the reused explorer modules by file (`explorer_modules.py`) and import siblings from their own directory (`3384b18`). The loader joined the producer identity, so the planned runs were repeated once more (attempt 3, byte-identical). The CI rule, ruff and the worker command line were checked locally; the full suites run in the follow-up CI. |

## Resources

Cumulative feature ledger (`evidence/ledger.jsonl`, 43 entries): **1148.1 s**
of the 1200 s numerical/processing ceiling and **284.3 MB** of the 512 MiB
raw-evidence ceiling (`outputs/ao_dynamic_validation/fv1`). By kind:
development probes 46.3 s (four rounded-up estimates), fixture test sessions
592.4 s, browser sessions 269.6 s (whole session wall time), planned runs
62.9 s, repeated planned runs (two repeats) 126.1 s, evaluation and
structural processing 11.8 s, review processing 39.0 s. Remote CI time is not
part of this ledger. Failed and diagnosed attempts are included.
The frozen explorer series and its ledger were not used or changed.

## Declared limits

- No public computation service exists and the service has no
  authentication; the published site cannot generate runs until the steps in
  [DEPLOYMENT.md](DEPLOYMENT.md) are completed and verified.
- One realization per run; no ensemble or convergence statistics.
- Headless Chromium 1194 only; Python 3.10 checked for syntax only.
- The committed raw-evidence validation record of the precomputed site
  describes the previous build until a maintainer refreshes it.
- A page reload during a submission can leave a job until the service's
  lease abandons it; R3-F03 above.
- Commit identity and the environment-created remote branch are the
  maintainer's decision.
- The maintainer asked for one CI run after acceptance; its first run found
  CI-1 above, and the follow-up run's result is reported with the pull
  request. The planned runs were repeated twice in total because repairs
  changed producer files; every repeat is byte-identical.
