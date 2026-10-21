# Post-T2 readiness note and staged experiment packet

Prepared 2026-10-21 (UTC) in a cloud session on the published commit
`55142852d8e01f0c6b2828480c64c5792e7d5302` (tree
`75c4fe7c9d8a90ef5f26fc174187cf8f82bd4ba9`) for independent
experimental-design review. This packet is a protocol-design and bounded
readiness deliverable. It authorizes nothing: no 12 m or 42 m job was run, no
runtime code, profile, baseline or historical record was changed, and every
pilot and study request below is `PREPARED_NOT_EXECUTED` until the protocol
passes review and each exact request is approved.

| File | Deliverable |
| --- | --- |
| this file | Deliverable 1: bounded readiness checklist, escalations, prioritized enablement decisions |
| [`PROTOCOL.md`](PROTOCOL.md) | Deliverable 2: predeclared staged protocols (S4 A1, E2, E3), arms/methods comparison, inference and stopping rules |
| [`pilot_requests.json`](pilot_requests.json) | Deliverable 3: machine-readable pilot and study requests (commands, guard settings, timeouts, output paths, acceptance and abort rules, hashed inputs) |
| [`SOURCE_READING_NOTES.md`](SOURCE_READING_NOTES.md) | Source-reading notes with file and line references, the derivation behind the alternative closure model, literature status |
| [`tools/`](tools/README.md) | Caller-owned launchers the requests name (proposed, unexecuted; no runtime code is changed) |
| [`records/`](records/) | The drivers' own `--plan` outputs for the exact tree, the cloud host and environment record, and the bounded checks executed in this session |

## 1. Source, CI and accepted context

| Item | Value | Status |
| --- | --- | --- |
| Checkout | `main` at `5514285`, clean before and after every command of this session (`git status --porcelain --untracked-files=all` empty) | EXECUTED_CURRENT |
| Parent with the final T2 repairs | `2e73e18ca2024e05bbc8bf37cc686d87d9e0e9d1` (eight files: the convergence driver, experiment core, Richardson module, their tests, three documents); `5514285` removes two README passages only (`git show --stat`) | INSPECTED_CURRENT |
| Exact-SHA CI run | [`actions/runs/39656946715`](https://github.com/xhvoid/Shack-Hartmann-AO-Simulation/actions/runs/39656946715), workflow `tests`, push on `main`, head `5514285`, started 18:54:38Z, completed 19:13:23Z, conclusion **success** | INSPECTED_CURRENT (GitHub API) |
| CI jobs | Source development 3.10 (success; the example, smoke and generator steps are matrix-skipped by design), Source development 3.14 (success, including the fast detector-level SCAO smoke and the "generators did not modify tracked artifacts" gate), Wheel gate 3.10 and 3.14 (success), HCIPy 3.11 (success), Notebook smoke 3.14 (success), Lint and static types 3.14 (success); every lane passed "Verify the environment is exactly the constraint lock" | INSPECTED_CURRENT |
| Scheduled slow lane | last run 2026-10-19 at `37b5bd9` (success), before T1 and T2; the `slow` test that runs the real ci self-check in fresh child processes has therefore not run in CI on `5514285` (covered on the cloud host in section 4) | INSPECTED_CURRENT |
| T2 acceptance | eight repaired files and binary diff bound to `868eccff15c353d31acf46c75ff176676259001421197c3c7b7ba307e21c071b`; T2-01 to T2-04 resolved; T1 accepted earlier | supplied handoff fact; the local ignored review records are not in this checkout and were not inspected |

The accepted code reviews are not repeated here. Only the interfaces the
proposed studies depend on were read (section 5).

## 2. Producing environments and series identity

A series is bound to one producing host, one locked environment and one code
identity. The drivers bind the environment as four fields (Python version
string, NumPy, SciPy, machine) and the code as the imported package digest
plus the driver digest with Git HEAD and the diff digest
(`scripts/run_detector_level_evidence.py:240-316`,
`scripts/detector_level_convergence_study.py:321-400`). A resume under another
producer is refused and nothing is relabelled. Consequently:

- The shared unlocked desktop environment (Python 3.14.3, NumPy 2.5.0, not the
  `py314` lock; roadmap G6, LIM-11) and the historical dirty-producer records
  (for example `det09_noise_isolation_12m_v3.json`: Git `663df16` with a
  non-empty source-change digest, series protocol 2) are not and must not be
  described as locked-environment runs. They stay as they are; a new series
  gets a new record under a new name.
- A cloud series is a new producer identity. It is never a resume of a desktop
  series, and a desktop series never resumes it. Each cloud session is a fresh
  machine, so a cloud series must complete inside one session (section 2.4).

### 2.1 Cloud host (measured in this session)

| Fact | Value | Source |
| --- | --- | --- |
| Platform | Linux 6.18 (Ubuntu 24.04), KVM guest, Intel Xeon 2.80 GHz, `x86_64`, 4 CPUs (affinity 0-3; `nproc` prints 2 only because `OMP_NUM_THREADS=2` is set in the session) | `lscpu`, `sched_getaffinity` |
| Memory | physical 16,874,930,176 B (15.72 GiB); available 16,128,307,200 B at the snapshot; no swap; pressure `normal` (`/proc/pressure/memory` avg10 0.00) | `shwfs_ao.runtime.resource_guard.host_snapshot()` |
| Disk | about 32 GB free on `/` at session start (a per-session allowance) | `df` |
| Python | system 3.13.16; also `/usr/bin/python3.11` (3.11.17) and `/usr/bin/python3.12`; no 3.10 or 3.14 interpreter; `uv` cannot download one because the network policy denies `github.com` (HTTP 403 from the proxy) | `uv python list`, `curl` |
| Network | PyPI reachable; `doi.org`, `arxiv.org`, `asme.org`, `ntrs.nasa.gov`, `adsabs.harvard.edu`, `sto.nato.int`, `ox.ac.uk` denied (403) | `curl` through the session proxy |
| Command duration | one Bash command (foreground or background) may run at most 9,000,000 ms (150 min); the container is reclaimed after inactivity | session tooling |
| Guard policy budget | `min(2 GiB, 12.5 % physical, 25 % available)` = 2,109,366,272 B = **2011.6 MiB**, set by the physical-RAM term; with the guard's 2x margin a job is admitted when its audited raw peak is at most 1005.8 MiB | `desktop_budget_bytes`, `resource_guard.py:379-401` |

### 2.2 Constraint-locked environment on the cloud host

Of the four committed locks (`constraints/README.md`), this host can realize
exactly one: `constraints/hcipy-py311.txt` (Linux-x86-64 CPython 3.11, the
HCIPy CI lane, which also runs the whole native selection from the wheel).
The native `py310` and `py314` locks need interpreters that are not installed
and cannot be downloaded under the current network policy (decision D6).

Procedure executed in this session (outside the checkout; nothing written into
the tree):

```bash
uv venv --seed --python /usr/bin/python3.11 "$SCRATCH/env/venv311"
PIP_CONSTRAINT="$PWD/constraints/hcipy-py311.txt" PYTHONPATH= \
  "$SCRATCH/env/venv311/bin/python" -m pip install -c constraints/hcipy-py311.txt -e ".[test,hcipy]"
PYTHONPATH= "$SCRATCH/env/venv311/bin/python" scripts/verify_environment_lock.py --constraints constraints/hcipy-py311.txt
PYTHONPATH= "$SCRATCH/env/venv311/bin/python" -m pip check
```

| Record | Value |
| --- | --- |
| Lock | `constraints/hcipy-py311.txt`, SHA-256 `9334c9353680eac41423179465aeafb4909e165a4a78ac9aeb61d6ab0238ebd0` |
| Verification | `hcipy-py311.txt: 40 installed distributions all pinned exactly (70 pins cover this and other lanes).`; `pip check`: no broken requirements |
| Producer environment (the four bound fields) | `3.11.17 (main, Oct  1 2026, 15:41:07) [GCC 13.3.0]`, NumPy `2.4.6`, SciPy `1.17.1`, `x86_64` |
| Native libraries (not bound, recorded) | NumPy built on `scipy-openblas64` 0.3.31.188.0 (`DYNAMIC_ARCH`, 64-bit int); thread variables `OMP/OPENBLAS/MKL/VECLIB_MAXIMUM/NUMEXPR_NUM_THREADS=2` from `limited_environment(threads=2)` |
| Imported package | `/home/user/Shack-Hartmann-AO-Simulation/src/shwfs_ao/__init__.py` (editable install of the clean checkout); code identity Git `5514285`, source-change digest `e3b0c442…` (empty diff), package digest `4f4162237e2264d2…` (recorded by the cloud self-check) |

This environment differs from the native CI lanes' locks (NumPy 2.5.1 on
3.14, 2.2.6 on 3.10) and from the desktop. That is acceptable under the one
series, one identity rule; it is recorded so that no cloud record is mistaken
for a `py314` or desktop record.

### 2.3 Thread, serial and guard policy as applied

- Serial numerical jobs, two native threads per process, one job at a time
  (the project's recorded policy; the checks in section 4 ran in that order).
- The guard's preflight decisions on this host, with the historical or
  extrapolated raw peaks of the proposed stages (`preflight()` with a 2x
  margin, `resource_guard.py:523-575`):

| Stage and audited raw peak | Required (2x) | Policy decision on this host |
| --- | --- | --- |
| ci self-check child, 307 MiB (desktop T2 record) | 614 MiB | admitted (and ran, section 4) |
| E2 medium paired child, 700 MiB (EXTRAPOLATED) | 1400 MiB | admitted |
| E2 medium paired child at 20 samples per lenslet, 1000 MiB (EXTRAPOLATED) | 2000 MiB | admitted with 12 MiB to spare; the supervising driver parent adds about 100-150 MiB to the group, so the group would be refused (pilot P1 decides) |
| S4 A1 traced 12 m series, 1137 MiB (historical untraced peak) to 1400 MiB (with trace overhead, EXTRAPOLATED) | 2274-2800 MiB | **refused**: exceeds the 2011.6 MiB budget |
| E3 full twin-only child, 1800 MiB (S2 and S3 42 m records: 1.57-2.0 GiB) | 3600 MiB | **refused** |

The evidence runner has no guard integration of its own and the guard's
command-line entry (`python -m shwfs_ao.runtime.resource_guard`) can only
lower the policy budget. The only in-tree authorized-budget path is the ESO
benchmark runner's `--authorized-budget-mib` with `--authorization-note`
(`experiments/eso_scao_benchmark.py:760-800`), which applies to ESO tiers
only. S4 A1 and E3 therefore need an explicit authorized budget and a launcher
that mirrors that decision (escalation E-1, decision D2, `tools/`).

### 2.4 Session-duration consequences

The 150-minute per-command cap and the ephemeral container mean that on the
cloud host a stage runs as a chain of background invocations of the same
command in the same output directory, each under the guard with
`--timeout-s` at most 8400 s, continued through the drivers' own resume
rules (one producer, planned runs only, atomic publication, summary written
once). A run in progress when a timeout stops the group is lost and redone;
nothing partial is published. Records must be pushed or copied out before the
session ends. A series that cannot finish inside one session is not resumed
in another session (new host, new identity): it is restarted as a new series.

## 3. Interfaces reviewed for the proposed studies

Only what the protocols express. Line numbers refer to the exact tree.

| Interface | What was established | Where |
| --- | --- | --- |
| G1 atmosphere pairing | `LayeredAtmosphereOptions(band_draw_reference_screen_size, band_limit_screen_size, screen_period_rule="pupil_diameter")` enters through `build_scao_system(atmosphere_options=...)`; the plan uses reference `2(N_finest-1)` = 958 and common band `2(N_coarsest-1)` = 574 at 12 m; `physical_frequency_dilation` reports `exact_physical_pairing` and the band-edge phase error; the options are **not** part of `SystemConfig.config_hash` (common_s12, growing_s12 and baseline_plain share hash `2a43f8f0…`) but are part of the atmosphere component hash and of each run's protocol and atmosphere record (`pairing_active`); the pupil family is analysed without `baseline_plain` | driver `plan()` 243-262, `analyze()` 758-770 and 867-895; `atmosphere_pairing.py:91-118`; `records/plan_medium.json` |
| G2 exposure timing | `ExposureOverride(subsamples, sample_rule)`; midpoint scheme `midpoint_uniform_held_dm.v1`, offsets `(j+1/2) tau/n`, residual metrics at frame start (`metric_time_convention`), DM held, one camera read; the midpoint family n = 1, 2, 4, 8 is one scan; `left_n2` enters only the labelled rule comparison (pairwise differences, no fit); refinement parameter `1/n` with an assumed order 2 for a labelled extrapolation only | driver `SCALES`, `REFINEMENT` 107-136, `analyze()` 803-845; `convergence_study.py:520-560`; technical reference 5.4 |
| G5 EE reference | `fourier_encircled_energy` of each science image and of the ideal image, status `available`/`unavailable` with reason, pad-independent for pad >= 2; production EE50 unchanged beside it; it integrates the raster model's periodic intensity and does not remove pupil-raster, finite-field or hardware-model errors | `convergence_study.py:412-445`; `validation/encircled_energy.py` docstring; technical reference 5.10 |
| Masks and noise diagnostics | traced sidecar arrays per frame and lenslet (masks, four gates, support, model sigma, measured and expected centroids, SNRs, clipping, saturation), per-frame `delta_v_m2`, `mean_square_difference_m2`, `cross_term_m2`, `mask_disagreement_rows`, propagation weights, optional residual maps; analysis rules (block plateau, Sokal window, gate-quiet domain, excursion flag, E0, Student t over seeds) in the NumPy-only script | runner 1180-1420 and 1640-1740; `detector_level.py:649-732, 1057-1133`; `analyze_noise_isolation_traces.py:1-50, 1074-1084` |
| Streaming storage | convergence core: twin pupil samples go to a float64 `.npy` memory map in the caller's scratch directory (`twin_record.bytes` recorded, file removed), the noisy arm streams `DeltaV_t` against it, science is a streamed long exposure; paired-noise core: both arms keep float32 pupil samples of every analysed frame in memory, the traced run adds per-frame telemetry arrays and, at the end, the payload copies and the compressed sidecar buffer | `convergence_study.py:155-240, 456-640`; `detector_level.py:649-666, 1057-1133`; runner `publish_sidecar` 1378-1420 |
| Run identity | convergence runs: protocol version 2 (plan-derived `expected` physical record, atmosphere options, exposure override, execution options, config hash, producer) with SHA-256; evidence series: series protocol 4 plus diagnostic protocol 1 for traced records; sidecar digests are output integrity, not protocol | driver 288-320 and 414-660; runner 320-470 and 1262-1320 |
| Refusals | governed scales and commands refuse at argument parsing and again before any build without `--enabled-by-user`; construction, calibration, factory and study-contract errors become recorded `refused` rows (resumable); unplanned, foreign, leftover, unreadable or self-inconsistent files stop the invocation before anything runs; a child of another producer stops the study | driver 1000-1047, 1074-1083, 1086-1160; runner 650-830, 1660-1700 |
| Resume | runs are added only under one producer with a known code identity (Git HEAD bound); the summary is written once and never rewritten, so an axis subset run into a directory cannot be expanded there later: each subset needs its own directory and repeats the baseline triple; a complete compatible rerun changes no byte or mtime | driver 1127-1160; runner 700-830 |
| Evidence-runner execution model | one process runs the whole gated series (20 paired runs for A1) and writes the record after each run; per-run peak memory is not recorded by `paired_noise_run` (the historical 1.11 GiB came from an external measurement), so the per-run peak must be measured by the supervisor or a single-run pilot | runner 650-890; status record 2510-2520 |

No new material defect was found in these interfaces. The items in section 6
are prerequisites, environment limitations and design consequences.

## 4. Bounded checks executed in this session (ungoverned)

All ran serially with two native threads in the locked environment of
section 2.2, from the clean checkout, writing only to the session scratch
directory; copies of the records are under `records/cloud_checks/`.

| Check | Command | Result | Label |
| --- | --- | --- | --- |
| Targeted fast tests of the interfaces above | `pytest -q -p no:cacheprovider -m "not hcipy and not slow and not elt_scale"` over `tests/validation/test_{richardson,atmosphere_pairing,encircled_energy}.py`, `tests/experiments/test_{detector_level_convergence,noise_isolation_trace_analysis,detector_evidence_runner}.py`, `tests/runtime/test_resource_guard.py`, `tests/control/test_exposure_subsamples.py` | **318 passed, 1 failed, 2 skipped, 1 deselected** in 59.7 s. The failure, `test_the_bytecode_cache_is_checked_where_python_reads_it`, is a root-user artifact: its last step makes a hash-based cache unreadable (`chmod 0`) and expects the tracked identity, but this session runs as `root`, which reads the file anyway, so the identity is correctly unknown (fail closed). CI runs unprivileged and is green. See E-3 | EXECUTED_CURRENT |
| T2 ci-scale self-check under the guard | `python -m shwfs_ao.runtime.resource_guard --label t2_ci_selfcheck_cloud --estimate-mib 307 --timeout-s 1800 --threads 2 -- python scripts/detector_level_convergence_study.py --scale ci --output-dir <scratch>/ci_selfcheck` | preflight admitted (614 of 2011.6 MiB); supervisor `COMPLETED`, exit 0, group peak 338,944,000 B (323 MiB), pressure `normal` throughout; 11 paired runs, driver wall **244.0 s** (desktop T2 record 89.3 s), summed child wall 232.8 s (79.4 s), 16.8-27.0 s per paired run, child `ru_maxrss` 177-232 MiB (desktop 222-307 MiB); baseline per-frame 0.102 s twin and 0.078 s noise-on; pairing exact (dilation 0.0 rad) for both readings; every Richardson status `NOT_ESTIMATED` (two settings per axis at ci scale, as designed); producer Git `5514285`, clean | EXECUTED_CURRENT, machinery and timing evidence only |
| 2 m traced replay against the committed record | `python -m shwfs_ao.runtime.resource_guard --label noise_isolation_2m_traced_cloud --estimate-mib 250 --timeout-s 3600 --threads 2 -- python scripts/run_detector_level_evidence.py --output-dir <scratch>/ni2m_traced noise-isolation-2m-traced`, then `scripts/analyze_noise_isolation_traces.py <record> --output-dir <dir> --historical docs/refactor/detector_level_evidence/det09_noise_isolation_2m.json --gate-quiet-labels m5,m6,m7` | supervisor `COMPLETED`, exit 0, wall **931.9 s** (desktop untraced record 290 s), group peak 122 MiB; 32 paired runs, none refused. **Replay of the committed record: every configuration hash equal, 0 of 32 runs bit-identical, largest relative difference 2.5e-9 (variance quantities), 3.0e-13 (residual RMS), 4.1e-16 (model column), the same level at the gate-active m8 runs**: the roundoff-level cross-host agreement `docs/reproducibility.md` predicts. Per magnitude `DeltaV` 4.27 ± 0.08, 10.40 ± 0.32, 25.81 ± 0.44, 200.7 ± 105.0 nm² (the committed values to the printed digits); E0 weighted ratio 0.996-1.019; gate-quiet m5-m7 per-seed E1 slope 0.955 ± 0.014 (T1's desktop finding reproduced). Loop ratio `DeltaV/P^E0` 0.1449 ± 0.0089, 0.1383 ± 0.0116, 0.1332 ± 0.0074 (t, 8 seeds) against the derived 0.1546; both arms clip 1.5-15 % of the actuators per frame (profile stroke 1 µm), so the no-saturation assumption of PROTOCOL.md 1.6 fails at 2 m (see there). Details: `records/cloud_checks/SUMMARY.md` | EXECUTED_CURRENT |

Speed anchor: the cloud host completes the same ci-scale work 2.7 to 2.9
times slower than the desktop anchors (driver wall ratio 2.73, summed child
wall ratio 2.93). Every desktop-anchored estimate for the cloud host below
carries that factor and the label EXTRAPOLATED; the factor was measured at
ci scale and may differ at 12 m and 42 m, which is what the pilots measure.

## 5. Cost anchors and cloud extrapolations

| Stage | Supplied or recorded anchor (desktop, MEASURED_HISTORICAL) | Driver's own estimate (`--plan`, ANALYTIC_ESTIMATE anchored at the desktop ci measurement) | Cloud extrapolation (x2.7-2.9, EXTRAPOLATED) |
| --- | --- | --- | --- |
| ci self-check | 89.3 s, up to 307 MiB per child | 90 s | measured: 244 s, 232 MiB per child, 323 MiB group |
| S4 A1 (20 traced paired runs, 400 frames) | about 45 min and 1.11 GiB untraced (2638 s, one process) plus telemetry | not planned by that driver | 2.0-2.2 h; raw peak 1.3-1.4 GiB (trace overhead, section 3) |
| E2 medium, 54 paired runs | 3.3 h (the supplied anchor) | 11,916 s = 3.31 h; per paired run 75 s (k2) to 594 s (midpoint n = 8) | 9-10 h; must be chunked (section 2.4) |
| E2 subsets | - | detector+spectrum with baseline: 15 runs, 2494 s (0.69 h); exposure+science with baseline: 24 runs, 5811 s (1.61 h); pupil: 18 runs, 3970 s (1.10 h) | 1.9 h, 4.5 h, 3.1 h |
| E3 full, 5 twin-only runs | 1.7 h (the supplied anchor; 42 m frames 1.75-1.80 s on the desktop) | 6173 s = 1.71 h; 726 s (baseline) to 1816 s (k = 4) per run | 4.6-5.0 h; raw peak 1.5-2.0 GiB per child |

Memory formulas and their basis are in `PROTOCOL.md` section 7; the disk
needs (sidecars, run files, twin records) are in `pilot_requests.json`.

## 6. Escalations

| ID | Kind | Finding | Consequence and recommendation |
| --- | --- | --- | --- |
| E-1 | missing prerequisite | S4 A1 and E3 exceed the guard's policy budget on any 16 GiB host after the 2x margin (section 2.3); the evidence runner is unguarded and the guard CLI cannot raise the budget | an explicit authorized budget per stage with a written note, applied by a caller-owned launcher that mirrors `_authorized_decision` (pressure normal, largest buffer under 64 MiB, available memory at least the raw estimate plus 1 GiB): `tools/authorized_supervise.py`, proposed and unexecuted |
| E-2 | missing prerequisite | neither driver can extend seeds or realizations from the command line: `NOISE_ISOLATION_12M["seeds"]` and `SCALES["medium"]["realizations"]` are constants | the protocols predeclare the extension triggers (PROTOCOL.md 1.7, 2.5); the mechanism is a decision (D3): a reviewed one-line driver change in a follow-up ticket, implemented only if a trigger fires, never during a running series |
| E-3 | environment limitation | `root` execution defeats one fail-closed test premise (section 4); the drivers' identity code behaves correctly under root (unknown identity for an unreadable unchecked cache, since root would run it) | run cloud series with `PYTHONDONTWRITEBYTECODE=1` (the convergence driver sets it for children; set it for the evidence runner too) and, where the image allows, as an unprivileged user; the failing test is not a defect |
| E-4 | coverage gap | the scheduled slow lane has not run on `5514285`; the real ci self-check in fresh children ran here on the cloud host, not in CI | dispatch `scheduled.yml` on `main` before quoting the slow lane as green on this SHA (D8) |
| E-5 | design consequence | the summary-written-once rule means axis subsets cannot be expanded in place; subsets cost one extra baseline triple each (about 6 min desktop, 17 min cloud) and yield separate summaries | predeclared subset directories (PROTOCOL.md 2.6); the full-plan summary is not assembled from subset directories |
| E-6 | environment limitation | the cloud host is 2.7-2.9x slower than the desktop and caps commands at 150 min | chunked background invocations with resume; the per-stage wall estimates above; the cloud's advantage is memory headroom and no pressure refusals, not speed |
| E-7 | environment limitation | primary literature hosts are denied by the network policy; the user supplied copies of four papers, which were read (Celik 2008, Gendron and Léna 1994, Agapito 2019, Trefethen 2008); two paywalled papers remain at listing status | SOURCE_READING_NOTES.md section 4; allow `doi.org`, `arxiv.org` and the publishers for future sessions, or keep supplying copies (D6) |

## 7. Prioritized enablement decisions (recommended defaults first)

| Priority | Decision | Recommended default | Alternatives and what they cost |
| --- | --- | --- | --- |
| D1 | Producing host and environment per series | cloud host with the `hcipy-py311` lock for S4 A1 and E3 (memory headroom, no pressure refusals); E2 subsets on whichever host is approved, cloud by default for the same reason | desktop with a fresh `py314`-locked environment (G6) is 2.7-2.9x faster but refused the T2 self-checks three times on pressure; mixing hosts within a series is refused by the drivers |
| D2 | Authorized budgets above policy | S4 A1: 2800 MiB (2 x 1400 MiB raw); E3: 4096 MiB (2 x 1800-2000 MiB raw, the ESO reference run was authorized at 4600 MiB); E2: policy budget, revisited after pilot P1 | running outside the guard with a user instruction, as T1 and T2 did: no supervision, no refusal on pressure; not recommended |
| D3 | Seed and realization extension mechanism | predeclare triggers now; implement a reviewed `--seeds`/`--realizations` option (or constants change) only if a trigger fires, in a follow-up ticket with tests; never during a series | caller-owned extension runs outside the drivers (no study record; not recommended) |
| D4 | E2 staging | E2a `--axes detector,spectrum` (15 runs) first; decision; E2b `--axes exposure,science` (24 runs); E2c `--axes pupil` (18 runs); separate directories | the full 54-run plan in one directory (one baseline triple, no intermediate decision, 9-10 h cloud) |
| D5 | Alternative closure model for S4 | adopt the loop noise-transfer model (PROTOCOL.md 1.6) as a predeclared hypothesis; its 2 m verification in this session did **not** confirm it (ratio 0.86-0.94 under 1.5-15 % actuator clipping), so the 12 m band is fixed a priori at 10 % with the saturation exclusion and the clipping hypothesis H_sat predeclared; the first-order bias band stays a hypothesis | keep A1 descriptive only (E0, E1, masks) with no closure criterion |
| D6 | Network policy | allow `github.com` (Python builds for the `py314` lock) and the literature hosts, or accept the `hcipy-py311` lock and user-supplied paper copies | status quo |
| D7 | Session handling | background invocations of at most 8400 s each with resume; push records after every invocation; one series per session | none |
| D8 | CI coverage | dispatch the scheduled lane on `main` at `5514285` | quote the cloud self-check as the only fresh-child evidence |
| D9 | Record placement | producers write under git-ignored `outputs/post_t2/<stage>/<series>/`; after review the user copies records (not sidecars) into `docs/refactor/detector_level_evidence/` with their series names | commit sidecars (about 1 GB for A1; not recommended) |
| D10 | Replay comparison for A1 | run the analysis with `--historical det09_noise_isolation_12m_v3.json`; expect roundoff-level, not bitwise, agreement across hosts at gate-quiet magnitudes; report every difference | none |

Approving this packet means approving the protocol text in `PROTOCOL.md` and
the exact requests in `pilot_requests.json`; execution starts with the pilots
in their listed order and stops at every decision gate.
