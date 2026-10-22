# Post-T2 readiness note and staged experiment packet

Prepared 2026-10-21 (UTC) in a cloud session on the published commit
`55142852d8e01f0c6b2828480c64c5792e7d5302` (tree
`75c4fe7c9d8a90ef5f26fc174187cf8f82bd4ba9`) for independent
experimental-design review; revised 2026-10-22 for the eight findings of
review round 1 (section 8), the seven findings of review round 2 (section
9), the five findings of review round 3 (section 10), the two findings of
review round 4 (section 11), the three findings of review round 5
(section 12), the two findings of review round 6 (section 13) and the two
findings of review round 7 (section 14). This packet is a protocol-design and bounded
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
| [`tools/`](tools/README.md) | Caller-owned launchers and analysis tools the requests name (validated on ungoverned configurations only; no runtime code is changed) |
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

**Leftovers of a stopped group and the resume procedure (review round 1,
finding 8).** The guard stops a timed-out group with SIGTERM and then
SIGKILL, so a publication can be interrupted between its steps. What such a
stop can leave behind, and how each driver reacts on the next invocation:

| Driver | Possible leftover | The driver's own reaction (unchanged code) |
| --- | --- | --- |
| convergence study | `runs/<key>.json.tmp-<pid>-<hex>` (a row written to its temporary file but not yet hard-linked into place); `scratch/twin_pupil_samples_*.npy` (the twin arm's disk record, normally unlinked in the core's `finally`) | `_refuse_unplanned_files` (`detector_level_convergence_study.py:1072-1083`) refuses any file in `runs/` that is not a planned run file: "another study's or scale's records, a foreign record family (S3, T1) or leftovers of an interrupted publication; they are neither reused nor relabelled"; nothing runs until `runs/` is clean; `scratch/` is not scanned, but a stale twin record occupies disk (72 MB at 12 m, 300 frames) |
| evidence runner (traced series) | `<stem>__<label>__seed<s>.npz.tmp-<pid>-<hex>` (a sidecar written but not linked); a complete sidecar whose record row was never written (the record is rewritten after the sidecar is published, so a stop between the two leaves an orphan) | the runner refuses the record directory while a sidecar of the record's stem is not referenced by a retained run: "sidecar files [...] are not referenced by any retained run (an interrupted invocation leaves such orphans or temporary files); they are ambiguous leftovers. Move them aside or pass --output NAME" (`run_detector_level_evidence.py:1831-1840`); a sidecar that exists before its run is refused the same way (1664-1668); nothing is deleted or overwritten |

The resume procedure of every stage request is therefore:

1. read the supervisor record of the stopped invocation (status, reason,
   peak RSS, pressure levels) and write it into the series log; a
   `RESOURCE_LIMITED` or pressure stop is a cost or admission finding to act
   on before resuming, a timeout is expected on the cloud host;
2. list the leftovers: `tools/quarantine_leftovers.py --study <dir>` for a
   convergence study or `--record <dir>/<record>.json` for an evidence
   series (no `--apply`): it prints each candidate with size and SHA-256 and
   its reason, and never names a planned run file, a referenced sidecar or
   the record itself;
3. move them aside with `--apply`: the candidates are renamed into
   `<dir>/leftovers/<UTC timestamp>/` (beside `runs/`, or beside the record),
   keeping their relative paths, with a `manifest.json` of what moved and
   why; nothing is deleted, and the quarantine directory is outside both
   drivers' scans (`runs/` only; the record directory's `<stem>__*.npz*`
   glob is not recursive);
4. re-invoke the identical command (with `--resume` for the evidence runner,
   as the stage requests list); the driver validates every retained run and
   sidecar against the plan and the producer first, reruns only the missing
   runs, and refuses if anything else is wrong;
5. a leftover that is not one of the listed kinds (a planned run file that
   fails validation, a record that fails its own checks) is not moved: it is
   a contract violation of `PROTOCOL.md` section 0 and stops the stage.

The tool was exercised on synthetic leftovers in this session
(`records/cloud_checks/round1/quarantine_demo/`); it was not and cannot be
exercised on a governed directory before one exists.

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
| Resume | runs are added only under one producer with a known code identity (Git HEAD bound); the summary is written once and never rewritten, so an axis subset run into a directory cannot be expanded there later: each subset needs its own directory and repeats the baseline triple; a complete compatible rerun changes no byte or mtime; leftovers of an interrupted publication (temporary files, orphan sidecars) are refused, never reused, and must be moved aside (section 2.4) | driver 1072-1083, 1127-1160; runner 700-830, 1664-1668, 1831-1840 |
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
| 2 m traced replay against the committed record | `python -m shwfs_ao.runtime.resource_guard --label noise_isolation_2m_traced_cloud --estimate-mib 250 --timeout-s 3600 --threads 2 -- python scripts/run_detector_level_evidence.py --output-dir <scratch>/ni2m_traced noise-isolation-2m-traced`, then `scripts/analyze_noise_isolation_traces.py <record> --output-dir <dir> --historical docs/refactor/detector_level_evidence/det09_noise_isolation_2m.json --gate-quiet-labels m5,m6,m7` | supervisor `COMPLETED`, exit 0, wall **931.9 s** (desktop untraced record 290 s), group peak 122 MiB; 32 paired runs, none refused. **Replay of the committed record: every configuration hash equal, 0 of 32 runs bit-identical, largest relative difference 2.5e-9 (variance quantities), 3.0e-13 (residual RMS), 4.1e-16 (model column), the same level at the gate-active m8 runs**: the roundoff-level cross-host agreement `docs/reproducibility.md` predicts. Per magnitude `DeltaV` 4.27 ± 0.08, 10.40 ± 0.32, 25.81 ± 0.44, 200.7 ± 105.0 nm² (the committed values to the printed digits); E0 weighted ratio 0.996-1.019; gate-quiet m5-m7 per-seed E1 slope 0.955 ± 0.014 (T1's desktop finding reproduced). Loop ratio `DeltaV/P^E0` 0.1449 ± 0.0089, 0.1383 ± 0.0116, 0.1332 ± 0.0074 (t, 8 seeds) against the derived 0.1546; both arms clip 1.5-15 % of the actuators per frame (profile stroke 1 µm), so the no-saturation assumption of PROTOCOL.md 1.6 fails at 2 m (see there). The 0.1546 is the scalar unit-feedback factor of the first draft; the exact linear model of review round 1 predicts the same value at 2 m to 0.4 % (`L = I` there), so this result stands for the whole linear model (section 8). Details: `records/cloud_checks/SUMMARY.md` | EXECUTED_CURRENT |
| Round 1: repaired fixed-physics pilot at ci scale (CHK-1a) | `tools/timing_pilot_fixed_physics.py --scale ci --key ci_baseline_plain_r0` under the guard CLI, twice (once alone on the host) | driver imported and planned; the launcher's row passed the driver's own `check_run` against the planned protocol; every scalar, digest, `DeltaV` value and science metric bit-identical to the T2 ci self-check row of the same key (protocol hash differs in `code/git_head` only); wall 27.2 s and 26.7 s against 17.6 s for the same child on 2026-10-21 (per-frame 0.130 s against 0.102 s); `ru_maxrss` 159-160 MiB | EXECUTED_CURRENT |
| Round 1: traced pilot on the 2 m profile (CHK-1b) | `tools/timing_pilot_traced_run.py --profile det_emccd_2m_synthetic --profile-version 1 --magnitude 5 --root-seed 61 --frames 200 --burn-in 50 --historical <committed 2 m record> --trace-sidecar <path>` under the guard | wall 39.9 s, `ru_maxrss` 104 MiB; seven recorded quantities within 8.3e-10 relative of the committed desktop record; gate-quiet; E0 ratio 1.027; clipping up to 31 % of the actuators in a frame; sidecar 0.78 MB written in the series' layout | EXECUTED_CURRENT |
| Round 1: exact linear loop model (CHK-1c, CHK-1d) | `tools/linear_loop_noise_model.py --self-test`; `--sigma sidecar` on the 33 two-metre sidecars and on four ci-geometry sidecars (m7 and m9, ci damping and the 12 m damping as a diagnostic override) | self-test passed (Lyapunov equals `kappa` to 1e-15); at 2 m `L = I` to 4e-15 and the model reduces to `kappa` within 0.4 %, so the first session's 2 m deficit (0.936 +/- 0.060, 0.892 +/- 0.076, 0.860 +/- 0.050 at m5-m7 under clipping) is a result about the whole linear model; on the ci geometry with the 12 m damping (7.3 % of feedback eigenvalues below 0.9) the two gate-quiet runs give 0.987 and 1.011 within one block SE; the gate-active m9 run with the ci damping exceeds the fixed-mask prediction by 1.28 (available rule) and 2.3 (strict rule) | EXECUTED_CURRENT, implementation evidence only |
| Round 1: leftover quarantine (CHK-1e) | `tools/quarantine_leftovers.py --study` and `--record` on synthetic interrupted directories, list then `--apply` | exactly the leftovers listed and moved aside with a manifest; planned run, record and referenced sidecar untouched; second pass empty | EXECUTED_CURRENT |
| Round 2: reruns with the corrected tools (CHK-2a to CHK-2e) | the model's self-test; the 2 m and four ci-geometry traced pilots; the model on the 32 series sidecars with `--record` and on the four pilot sidecars with `--pilot-record`; three negative checks | self-test passed (delayed injection: the first `d` post-update covariances are exactly zero); every pilot's per-arm telemetry equals the core's trace summary; 32 of 32 series sidecars and 4 of 4 pilot sidecars validated (declared table, frame domains, layout, canonical rows, label, seed, hash, record digest and size, runner `validate_trace_payload`); available-rule ratios unchanged (2 m: 0.936, 0.892, 0.860 at m5-m7; ci with the 12 m damping: 0.987, 1.011); the strict mask probed on its own rows leaves modes unsensed where lenslets flicker (0.53 at ci m7, no stationary limit at ci m9) and is refused by the 2 m reconstructor's valid-fraction policy on 6 of 8 gate-active m8 runs (the available mask on 1 of 8); the three corrupted or misattributed sidecars were refused with nothing read | EXECUTED_CURRENT |
| Round 3: model reruns with the effective operator and canonical validation (CHK-3a to CHK-3f) | the model's self-test; the model on the five pilot sidecars (`--pilot-record`) and the 32 series sidecars (`--record`); three negative checks (wrong units, permuted axes, wrong dtype); a fixed-physics pilot on an exposure key; the acceptance field-path audit | self-test passed (the unit-pole case returns no stationary limit); 37 of 37 genuine sidecars pass the canonical units/axes/meaning/dtype/shape check and the record or pilot-record digest check; the three corrupted sidecars are refused with nothing read; under the effective rule the 2 m gate-quiet ratios are 0.936, 0.892, 0.860 at m5-m7 (all 24 runs operator-consistent, arms under the modal operator in at least 99.3 % of the frames) and the ci runs with the 12 m damping 0.987 and 1.010 (operator-consistent), while the ci runs with the ci damping are mask-variable (arms under the modal operator in 93-94 % and 73-74 % of the frames) and descriptive; 42 acceptance field paths resolve in the matching tool records | EXECUTED_CURRENT |
| Round 4: model reruns with the operator error bounds (CHK-4a to CHK-4e) | the model's self-test; the model on the five pilot sidecars (`--pilot-record`) and the 32 series sidecars (`--record`); three negative checks (wrong units, permuted axes, wrong dtype); the acceptance field-path audit | self-test passed (a constant operator sequence equals the modal transient to 1e-16, a silent burn-in equals the cold start, a stationary start stays stationary to 1e-15); 37 of 37 genuine sidecars validated and the three corrupted ones refused as in round 3; effective-rule ratios unchanged (2 m 0.936, 0.892, 0.860 at m5-m7; ci with the 12 m damping 0.987 and 1.010); operator error below 0.03 % on every 2 m run at m5-m7 and on the ci runs with the 12 m damping, 0.64 % on the ci m7 run with the ci damping (operator-consistent now, after round 3's threshold had excluded it), +3.9 % on the ci m9 run with the ci damping (mask-variable), 1.7-32 % at the 2 m m8 with up to 10.4 % carried in from the burn-in's operators; carried-state bound 2.44 % on the 2 m runs whose burn-in clipped actuators through its last frame (12 of 24 at m5-m7, every one of the 24 excluded by the saturation rule anyway) and at most 1.1 % otherwise; 50 acceptance field paths resolve in the matching tool records | EXECUTED_CURRENT |
| Round 5: model reruns with the measured carried-state bound, the covariance bracket and the memory inventory (CHK-5a to CHK-5f) | the model's self-test; the model on the five pilot sidecars (`--pilot-record`) and the 32 series sidecars (`--record`); three negative checks; a bracket fixture (a 2 m pilot sidecar with one lenslet outside the modal operator and usable in five frames only); the acceptance field-path audit | self-test passed (the leading-block-row recurrence equals explicit powers of `F` to 1e-15, `gamma` equals a direct simulation of its maximizing state, an unsensed mode persists at ratio one and receives zero injection); 37 of 37 genuine sidecars validated and the three corrupted ones refused as in rounds 3 and 4; effective-rule ratios unchanged; on the ci runs with the 12 m damping the unsensed mode receives 1.9e-5 of the injection, `gamma` over the sensed states is 0.091, the first-block excesses are -2.4 % and -2.8 % against block scatters of 10 % and 9 %, and the systematic budget is 2.1 % and 1.9 %; on the ci runs with the ci damping the almost unsensed mode receives 2.3e-2 of the injection, `gamma` over every state is 1.02 and the budget is 99 % and 146 % (no closure test can be expressed on that loop); on the 2 m series every m5-m7 run is operator-consistent (operator error below 0.03 %) with carried-state bounds of 2-17 % (`gamma` 0.167, six blocks of scatter 6-33 %) and mean budgets of 8.5 %, 9.5 % and 6.9 %, while at m8 six runs are mask-variable (2.7-32 %), one not assessable and one consistent at 1.7 % with a bound of 17 %; no genuine run had a row to bracket, the fixture bracketed two rows and reported both ends; the retained-array inventory is 1-21 MiB against peaks of 103-130 MiB (interpreter, libraries and build about 100 MiB); 48 acceptance field paths resolve | EXECUTED_CURRENT |
| Round 6: model reruns with the measured carried state, the conditional prediction, the calibrated sensor-model margin and the budget exclusion (CHK-6a to CHK-6i) | the model's self-test; three traced ci pilots with residual maps retained; the model on the five round-2 pilot sidecars, the three new pilot sidecars and the 32 series sidecars; a carried-state fixture, a scaled-series fixture and the round-5 bracket fixture; two logged replays of traced ci pilots; three negative checks; the acceptance field-path audit | self-test passed (schema v7); the replays reproduce the pilots' series exactly and show every reconstructor input to be the centroid minus the sensor's calibration reference (0.0 px), the probed operator to match the actual LSMR estimate to 1.3e-6 at damping 0.1 and to 1-5 % at 0.001; on the ci runs with the 12 m damping the command difference rebuilt from the telemetry reproduces the series to 1.6e-5 and 6.8e-6, the measured carried state contributes 1.2 % and 1.4 % (model 1.6 %), the conditional ratios are 0.991 and 1.012 and the budgets 0.002 % and 0.026 %; the ci m7 run with the ci damping is assessable only with its maps (reconstruction 2.8e-3; ratio 1.072, budget 0.92 %); every 2 m run is not assessable (54-193 clipped frames; reconstruction 21-427 %); the carried-state fixture (+25 % window variance through the loop) is measured as 26.7 % carried, ratio 0.986 conditional against 1.234 unconditional, budget 1.3e-5; the scaled-series fixture is caught (reconstruction 21 %, budget at or above the band); the sensor-model margin of two is supported on every one of the 40 genuine records (largest 97.5 % upper ratio 0.81-1.47); 57 acceptance field paths resolve | EXECUTED_CURRENT |
| Round 7: the operator error on the conditional prediction with exact extremes over the admissible covariance (CHK-7a to CHK-7h) | the model's self-test; the model on the five round-2 pilot sidecars, the three round-6 pilot sidecars with maps and the 32 series sidecars; three linear re-synthesis fixtures (an operator change after the first analysed frame with and without noise, sparse lenslets), each also run with the round-6 tool; the round-6 carried-state and scaled-series fixtures and the round-5 bracket fixture; three negative checks; the acceptance field-path audit, now resolving relative paths | self-test passed (schema v8; adjoint functional against forward propagation 2.7e-16; box extremes against a dense grid; 0 of 4000 random admissible covariances outside the exact extremes, while the variance corners of an indefinite functional miss them); operator-change fixture: the round-6 tool reports a 0.8 % budget while its prediction is 20 times the measured value, the v8 tool an operator error of -94.8 % (not assessable), and the actual-operator prediction is within 6 % of the measured value; quiet operator-change fixture with five arm-disagreement frames: the actual-operator prediction reproduces the measured window mean to 2.1e-5 (the realized cross terms of the noise scaled by 1e-4); sparse-lenslet fixture: exact extremes -0.12 % to +0.10 %, none of 200 sampled admissible covariances outside; ci runs with the 12 m damping: operator errors 0.00 % and +0.39 %, budgets 0.002 % and 0.39 %; the ci m7 run with the ci damping: operator error +18.6 % from 15 arm-disagreement frames, mask-variable; every 2 m run not assessable as before; 66 absolute and 28 relative acceptance field paths resolve | EXECUTED_CURRENT |

Details and tables: `records/cloud_checks/round1/SUMMARY.md`,
`records/cloud_checks/round2/SUMMARY.md`,
`records/cloud_checks/round3/SUMMARY.md`,
`records/cloud_checks/round4/SUMMARY.md`,
`records/cloud_checks/round5/SUMMARY.md`,
`records/cloud_checks/round6/SUMMARY.md` and
`records/cloud_checks/round7/SUMMARY.md`.

Speed anchor: the cloud host completes the same ci-scale work 2.7 to 2.9
times slower than the desktop anchors (driver wall ratio 2.73, summed child
wall ratio 2.93). Every desktop-anchored estimate for the cloud host below
carries that factor and the label EXTRAPOLATED; the factor was measured at
ci scale and may differ at 12 m and 42 m, which is what the pilots measure.
Round 1 added a second anchor: the identical ci run (bit-identical output)
took 26.7 s on 2026-10-22 against 17.6 s on 2026-10-21, so the cloud factor
itself varies by about 1.5x between sessions; every cloud wall estimate
below should be read with that spread, and a pilot's measured value replaces
the estimate only for the session that produced it.

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
| D5 | Alternative closure model for S4 | adopt the exact linear closed-loop noise model with the reconstructed spatial feedback `L = R M` (PROTOCOL.md 1.6, `tools/linear_loop_noise_model.py`) as a predeclared hypothesis, closed only by the whole-interval test of PROTOCOL.md 1.7; its unit-feedback reduction is the earlier scalar `kappa`; the 2 m check did **not** confirm the model (ratio 0.86-0.94 under 1.5-15 % actuator clipping; at 2 m the exact model and `kappa` coincide, so the deficit is not the omitted feedback), so the 12 m band stays fixed a priori at 10 % with the saturation exclusion and the clipping hypothesis H_sat; the 12 m prediction is pilot P2b; the first-order bias band stays a hypothesis | keep A1 descriptive only (E0, E1, masks) with no closure criterion |
| D6 | Network policy | allow `github.com` (Python builds for the `py314` lock) and the literature hosts, or accept the `hcipy-py311` lock and user-supplied paper copies | status quo |
| D7 | Session handling | background invocations of at most 8400 s each with resume; push records after every invocation; one series per session | none |
| D8 | CI coverage | dispatch the scheduled lane on `main` at `5514285` | quote the cloud self-check as the only fresh-child evidence |
| D9 | Record placement | producers write under git-ignored `outputs/post_t2/<stage>/<series>/`; after review the user copies records (not sidecars) into `docs/refactor/detector_level_evidence/` with their series names | commit sidecars (about 1 GB for A1; not recommended) |
| D10 | Replay comparison for A1 | run the analysis with `--historical det09_noise_isolation_12m_v3.json`; expect roundoff-level, not bitwise, agreement across hosts at gate-quiet magnitudes; report every difference | none |

Approving this packet means approving the protocol text in `PROTOCOL.md` and
the exact requests in `pilot_requests.json`; execution starts with the pilots
in their listed order and stops at every decision gate.

## 8. Review round 1 (2026-10-22): findings and repairs

Eight P2 findings were returned on the packet at `da44227`. Each repair,
what evidences it, and where it lives:

| # | Finding | Repair | Evidence |
| --- | --- | --- | --- |
| 1 | Pilot launcher fails while importing the driver | the drivers are imported by path with the module registered in `sys.modules` before execution (`tools/_packet_common.py:load_script_module`), which the drivers' dataclasses need under `from __future__ import annotations`; both pilots and the model use the helper | CHK-1a: the launcher imports, plans and runs the ci key; its row passes the driver's `check_run` and is bit-identical to the T2 self-check row |
| 2 | Pilot output omits evidence required for acceptance | `timing_pilot_fixed_physics.py` records the complete validated study row (composed as `_run_child` plus `run_protocol`) and an `acceptance_evidence` block; `timing_pilot_traced_run.py` records the seven recorded quantities with the `--historical` comparison, per-arm telemetry summaries, mask disagreement, the `DeltaV` series summary, E0, and optionally the trace in the series' sidecar layout; every acceptance rule in `pilot_requests.json` names the JSON field it reads | CHK-1a, CHK-1b; `pilot_requests.json` (`launcher_records`, P1a-P3) |
| 3 | S4 transfer model omits reconstructed spatial feedback | the scalar factor is replaced by the exact linear closed-loop model with `L = R M`, finite-window and stationary covariance, realized or flat noise covariance (`tools/linear_loop_noise_model.py`; PROTOCOL.md 1.6, 7; notes section 3); `kappa` is kept as its unit-feedback reduction; the 12 m evaluation is pilot P2b and a prerequisite of S4-A1 | CHK-1c (2 m: reduces to `kappa`, deficit unchanged), CHK-1d (ci geometry with the 12 m damping: 0.987, 1.011) |
| 4 | S4 closure can pass with overly broad uncertainty | closure uses whole-interval (equivalence) semantics: "verified" only if the whole 95 % t interval of the five-seed ratio lies inside the 10 % band, "rejected" if wholly outside, "not expressible" otherwise (triggers the seed extension once); the closure sentence requires "verified" at every gate-quiet magnitude (PROTOCOL.md 1.7, 5) | text |
| 5 | Unpaired uncertainty is incorrectly called conservative | per-realization paired differences are the primary uncertainty on every axis and for both arms; the driver's unpaired `sqrt(s_i^2 + s_j^2)` is descriptive only, neither a conservative nor a liberal bound in general, and no decision reads it (PROTOCOL.md 2.3) | text |
| 6 | Convergence labels leave valid outcomes unclassified | converged `|Delta| + h <= tol`, unconverged `|Delta| - h >= tol`, not expressible otherwise: mutually exclusive and exhaustive for finite values; refused or missing settings are "not classified"; the E3 single-realization labels and the extension rule follow the same pattern (PROTOCOL.md 2.4, 2.5, 3.2) | text |
| 7 | E3 exposure interpretation lacks an E2b prerequisite | E3 proceeds only after E2a **and** E2b are interpreted: three of the five 42 m settings are exposure settings whose 12 m prior scale and rule comparison come from E2b (PROTOCOL.md 3.3; `pilot_requests.json` stage E3; decision gates) | text |
| 8 | Timeout recovery omits handling of publication leftovers | the leftovers each driver refuses after a stopped group (temporary publication files, orphan sidecars, stale twin records) and the drivers' exact reactions are tabulated; `tools/quarantine_leftovers.py` lists and moves them aside with a manifest, never deleting; the five-step resume procedure is in section 2.4 and in every stage request's `resume` field | CHK-1e |

Two observations from the round-1 checks that the protocols now carry:
the realized noise covariance must include lenslets whose gates flicker
rarely (the "available" support rule; the strict E0 rule under-states the
noise power by up to 28 % in a gate-quiet ci run), and the cloud host's
speed varies by about 1.5x between sessions for identical work (section 4),
so cloud wall estimates are indicative until the pilots measure them in the
producing session. No runtime code, profile, baseline or historical record
was changed; no governed run or 12 m or 42 m system build took place.

## 9. Review round 2 (2026-10-22): findings and repairs

Review round 2 on `bd90acd` resolved seven of the eight round-1 findings,
kept POST-T2-04 partly open (a broad E0 interval could still earn an
agreement claim) and raised seven new P2 findings. Each repair and its
evidence (`records/cloud_checks/round2/SUMMARY.md` for the numbers):

| # | Finding | Repair | Evidence |
| --- | --- | --- | --- |
| 04 (open part) | A broad E0 interval can still earn an agreement claim | the E0 ratio gets the same equivalence test as the loop ratio: per gate-quiet magnitude the whole 95 % t interval of the propagation-weighted E0 ratio over the admissible seeds must lie inside an a-priori 10 % band ("verified"), else "rejected" or "not expressible"; "within its own interval of unity" is struck as a criterion; the closure sentence needs both tests "verified" (PROTOCOL.md 1.6 "Use", 1.7 "E0 test", 5) | text |
| N1 | Incorrect P1c pupil-size acceptance check | the check named `geometry.pupil_samples 480`, but that field is the illuminated sample count (10,224 at ci scale, 18,296 at 16 samples per lenslet); the grid is `geometry.pupil_shape`, so P1c now requires `pupil_shape == [480, 480]` and records `pupil_samples`, retained lenslets and the illuminated-area fraction (`pilot_requests.json` P1c) | ci rows of the T2 self-check (`records/cloud_checks/ci_selfcheck/`) |
| N2 | Incorrect P2 recovery acceptance check | the check required `recovery null`, but the 12 m profile carries a recovery policy, so the core records a recovery block whose counters must be zero; P2 now reads the core's `trace_summary.arms[arm].recovery_acted` and `rejected_frames_after_burn_in` (the gate-quiet rule's own fields) and `gate_quiet` (`pilot_requests.json` P2; `detector_level.py:1224-1252`) | text; CHK-2b records show the fields |
| N3 | Premature noise injection in the model | the latency queue starts with `d` zeros, so the noise of frame `k` first moves the command applied after update `k + d`; the transient now adds the forcing only for `k >= d` (`window_covariance`), the self-test checks that the first `d` post-update covariances are exactly zero and the next equals `g^2 R Sigma R^T` (PROTOCOL.md 7; notes section 3) | CHK-2a self-test |
| N4 | Mismatched mask assumptions in the model | the reconstructor was probed with every row valid while the noise of unused rows was zeroed, which describes a different loop from the one that drops those rows; the reconstructor is now probed on exactly the rows that carry noise (`reconstructor_matrix_masked`), one fixed mask per support rule for `L`, the injection and `Sigma`; a mask the reconstructor refuses makes that rule "not defined"; the series' all-valid propagation weights are kept only for the first draft's scalar value (PROTOCOL.md 1.6, 7) | CHK-2c, CHK-2d: the available-rule predictions on all-valid masks are unchanged; the strict-rule predictions change where lenslets flicker (0.53 at ci m7 with 126 of 144 rows; no stationary limit at ci m9 with 92 rows), and the 2 m reconstructor refuses the strict mask of 6 of 8 gate-active m8 runs and the available mask of 1 |
| N5 | Incorrect rejection counts | the traced pilot recounted rejected frames from the trace arrays under its own field name; it now repeats the core's `trace_summary` counts (`rejected_frames_after_burn_in`, `recovery_acted`) and refuses a record whose arrays disagree with them; the model tool reports the same core-rule counts for both arms and the core's gate-quiet rule | CHK-2b: the recount equals the core's count on every rerun pilot (the tool would refuse otherwise) |
| N6 | Missing sidecar semantic validation | before a sidecar is read as data the tool checks the declared array table (names, dtypes, shapes), the frame domains, the two-arm layout and the canonical interleaved rows of one lenslet order, the label and seed, the configuration hash against the built configuration, and, with `--record`, the series row's digest and size plus the evidence runner's own `validate_trace_payload`, or, with `--pilot-record`, the pilot's digest, size, frame counts, label, seed and hash; a refusal reads nothing | CHK-2c (32 series sidecars validated against their record), CHK-2b (pilot sidecars), CHK-2e (three negative checks refused) |
| N7 | Degrees of freedom that ignore excluded seeds | every interval uses `n_adm - 1` degrees of freedom over the admissible units with the quantile of the count actually used; the loop and E0 tests state the counts their outcomes require (4 for "verified", 3 for "rejected"); E2 pairs use the realizations completed in both settings (PROTOCOL.md 0, 1.7, 2.3, 2.4, 2.5) | text |

No runtime code, profile, baseline or historical record was changed; no
governed run or 12 m or 42 m system build took place. The round-1 records
stay under `records/cloud_checks/round1/` as the record of that revision;
the round-2 reruns with the corrected tools are under
`records/cloud_checks/round2/` (`SUMMARY.md` there has the tables).

Two further observations from the round-2 reruns entered the protocol: a
fixed support mask that leaves DM modes unsensed has, with no leak, no
stationary limit and a window prediction that grows with the run (the
tool reports the count of such modes; the "support-sensitive" label of
that revision carries no rule since revision 5, where PROTOCOL.md 1.6 (iv)
is the only exclusion list), and the 2 m reconstructor's valid-fraction policy
refuses the strict support mask of most gate-active 2 m runs (and the
available mask of one), so the fixed-mask model is "not defined" for that
rule exactly where the loop itself is gate-active.

## 10. Review round 3 (2026-10-22): findings and repairs

Review round 3 on `4960b76` resolved six prior findings and left five P2
findings. Each repair and its evidence (`records/cloud_checks/round3/SUMMARY.md`
for the numbers):

| # | Finding | Repair | Evidence |
| --- | --- | --- | --- |
| 12 | Changing masks can still produce comparison against the wrong operator | the model's primary operator is now the one the loop used: the row set the noisy arm's reconstructor used in the plurality of analysed frames (the sidecar's per-frame effective row masks), with `Sigma` from the frames in which that operator was in use; the tool records in how many analysed frames each arm used it, and a run in which either arm used it in fewer than 95 % of the frames is "mask-variable": its prediction is reported, its comparison is descriptive, and the protocol excludes it from the closure test as a third predeclared exclusion beside saturation and gate activity; the telemetry-based `available` and `strict` rules stay as sensitivities (PROTOCOL.md 1.6, 1.7, 7) | CHK-3b, CHK-3c: the 2 m gate-quiet runs and the ci runs with the 12 m damping are operator-consistent (both arms under the modal operator in 97-100 % of the frames); the ci runs with the ci damping are mask-variable (94 % and 74 %) although the m7 one is gate-quiet, which is the case the finding describes |
| 14 | Pilot and bare sidecars accept incorrect units or axes | every sidecar's declared array table is compared array by array with the evidence runner's own canonical layout constants (units, axes and meanings), the dtype the core writes, and the shape the declared axes imply from the frame, row, lenslet and pupil-sample counts; unknown array names and missing required arrays are refused; the check runs for pilot and bare sidecars alike, before `--record` or `--pilot-record` add the digest checks | CHK-3d: a sidecar with a wrong unit string, one with permuted axes and one with a wrong dtype are refused with nothing read; CHK-3b, CHK-3c: 37 of 37 genuine sidecars pass |
| 16 | P2b's second command reuses a supervisor record and refuses execution | the second command is spelled out with its own supervisor label, log and record (`p2b_flat.log`, `p2b_flat_supervisor.json`); the launcher refuses an existing record path by design, so the two commands never share one (`pilot_requests.json` P2b) | text |
| 17 | P2b requires a field removed from the current output schema | the acceptance rules name the fields of the tool's current schema (`post_t2_linear_loop_noise_model.v3`: `primary_status`, `delta_v_scalar_reduction_mask_m2`, `stationary_limit_exists`, the operator block, the per-rule entries); an audit script resolves every dotted field path named in the requests' acceptance rules against the tools' actual records and is part of the checks | CHK-3f: every named path resolves in the matching record |
| 18 | The protocol can interpret an inconclusive result as a physical departure | only a "rejected" outcome localizes a departure (in the loop, in the sensor model, or both); a "not expressible" outcome of either test is a precision outcome that triggers the seed extension once and, if it persists, leaves the localization "undetermined", never an agreement and never a departure (PROTOCOL.md 1.6 "Use", 1.7, 5) | text |

No runtime code, profile, baseline or historical record was changed; no
governed run or 12 m or 42 m system build took place. The round-1 and
round-2 records stay as the record of those revisions; the round-3 model
reruns on the unchanged round-2 pilot sidecars and the series sidecars are
under `records/cloud_checks/round3/` (`SUMMARY.md` there has the tables).

One observation from the round-3 reruns entered the protocol: a run can be
gate-quiet by the 0.1 % disagreement rule and still change its operator
over time (the ci m7 run with the ci damping used twelve distinct row sets
and the modal one in 94 % of the frames), so the mask-variable exclusion is
a rule of its own beside gate activity.

## 11. Review round 4 (2026-10-22): findings and repairs

Review round 4 on `acfc8b0` resolved four prior findings and left two P2
findings (POST-T2-12 and POST-T2-19). Each repair and its evidence
(`records/cloud_checks/round4/SUMMARY.md` for the numbers):

| # | Finding | Repair | Evidence |
| --- | --- | --- | --- |
| 12 | The operator-match threshold lacks an error bound and misses state carried from burn-in, even with 100 % analysed-frame agreement | the 95 % match threshold is gone; two quantified error bounds decide whether the fixed operator describes a run (PROTOCOL.md 1.6, 1.6 (iv), 7): (1) the **operator error**, the relative difference between the transient propagated with the noisy arm's actual operator of every frame of the run, burn-in included (each distinct effective mask probed once; the increment released at update `k` carries the operator of frame `k - d`; `Sigma` restricted to each operator's rows), and the modal-operator prediction, reported with its burn-in-carried and in-window parts; (2) the **carried-state bound**: the window value is affine in the loop's state at any frame, so the modal-operator window is restarted from a zero state right after the last burn-in frame the linear model does not carry (a row of mask disagreement, a rejected reconstruction, a recovery action, saturation above 1e-3) and the fraction of the primary value this removes bounds the error a wrong carried state can cause; a run is operator-consistent when the operator error is within 2 % and, if such a burn-in frame exists, the carried-state bound is within 2 %; the match fractions over the analysed and the burn-in frames are diagnostics only; the share of the window value inherited from the whole burn-in and the window value under a stationary carried state are reported as sensitivities; the self-test checks the sequence propagation against the modal transient (constant sequence), a silent burn-in against the cold start and a stationary start against the stationary value; P2b's command carries the tolerances and the probe budget and its acceptance rules name the new fields | CHK-4a to CHK-4c: at the 2 m m8 the burn-in's operators carry up to 10.4 % into the window value and the operator error is 2.7-32 % on seven runs (one operator refused), which the frame count could not show; the ci m7 run with the ci damping that round 3's threshold excluded (modal operator in 94 % and 93 % of the frames) has an operator error of 0.64 % and a carried-state bound of 1e-5 and is operator-consistent; the ci m9 run with the ci damping is mask-variable at +3.9 %; the ci runs with the 12 m damping have errors below 0.03 % and quiet burn-ins; the 2 m runs at m5-m7 have operator errors below 0.03 % but clip actuators during loop closure, so 12 of 24 are carried-state-sensitive at 2.44 % (the share of their 150-frame window inherited from before it) beside the saturation rule that excludes all 24 |
| 19 | The protocol retains conflicting exclusion lists and primary comparison rules | PROTOCOL.md 1.6 (iv) is the one list of the three predeclared exclusions (saturation after burn-in above 1e-3 in either arm; gate activity by the 1.5 rule; the operator rule of the two bounds, a run the tool cannot assess included) and states that the effective-rule modal-operator prediction is the only primary and that no other rule or label (the telemetry-based rules, the count of unsensed modes, the match fractions) decides anything; sections 0, 1.6 (iii), 1.7 and 7 refer to that list instead of restating it; the "support-sensitive" flag with its "stays in the test under the available rule" clause and the "both support rules" wording are removed, and the tool's unsensed-mode note says the count carries no rule; sections 8-10 of this README describe the earlier revisions as they were made and, where they differ from revision 5, PROTOCOL.md 1.6 (iv) rules | text; CHK-4e: 50 acceptance field paths resolve in the matching tool records |

No runtime code, profile, baseline or historical record was changed; no
governed run or 12 m or 42 m system build took place. The round-1 to
round-3 records stay as the record of those revisions; the round-4 model
reruns on the unchanged round-2 pilot sidecars and the series sidecars are
under `records/cloud_checks/round4/` (`SUMMARY.md` there has the tables).

One observation from the round-4 reruns entered the protocol: at the 2 m
m8 the state the loop carries into the analysed window under the burn-in's
operators changes the window value by up to 10 %, and a run can change its
operator twelve times in the window with an operator error of 0.6 %, so
neither a frame count over the analysed frames nor one over the burn-in
measures what the fixed-operator comparison needs; the two bounds do.

## 12. Review round 5 (2026-10-22): findings and repairs

Review round 5 on `c6642b7` resolved POST-T2-19 and left three P2 findings
(POST-T2-12 still open, POST-T2-20, POST-T2-21). Each repair and its
evidence (`records/cloud_checks/round5/SUMMARY.md` for the numbers):

| # | Finding | Repair | Evidence |
| --- | --- | --- | --- |
| 12 | Restart sensitivity still lacks a bound on the unknown carried state; an admitted fixture produces 25 % extra window variance | the restart values of round 4 measured the sensitivity of the **modelled** state and bounded nothing about a state the model does not predict; they are now sensitivities only. The bound is measured: the window mean is affine in the loop's state at the first analysed frame, so any deviation of that state changes the window mean by at most `gamma` times its change of the first 25-frame block mean, `gamma` being the largest generalized eigenvalue of the window-mean and first-block-mean quadratic forms of the companion dynamics (computed from the leading block row of `F^j`, no dense powers); the first-block change is measured as the first analysed block's `DeltaV_t` mean minus the model's own per-frame transient, with the run's block scatter as its uncertainty; bound = `gamma (|excess_1| + 2 s_block) / DeltaV_pred`. `gamma` runs over the states the operator senses when the operator injects nothing into its unsensed modes (a left null vector of `L` is a left null vector of `R` for Tikhonov-type reconstructors; the tool verifies the injection numerically, 1e-3 relative at most), and over every state otherwise, so a frozen offset in a persistent mode is either excluded structurally or bounded with `gamma` near one. The bound is not a threshold: with the operator error it forms the run's systematic budget `u`, and the closure test subtracts the admissible seeds' mean `u_bar` from its band (agreement band `[1 - b + u_bar, 1 + b - u_bar]`, departure band widened by `u_bar`; `u_bar >= b` is a model-budget "not expressible" that no seed extension changes) (PROTOCOL.md 1.6, 1.6 (iv), 1.7, 5, 7). A fixture with 25 % extra window variance from a carried state raises the first analysed block by at least that amount, so its bound is at least `gamma` times 25 % plus the scatter term, and with `gamma` near one for a persistent mode the budget consumes the band | CHK-5a: `gamma` equals a direct simulation of its maximizing state (1e-15), an unsensed mode persists at ratio one with zero injection; CHK-5b: ci with the 12 m damping, `gamma_sensed` 0.091, injection 1.9e-5, bound 2.1 % and 1.9 %, budget 2.1 % and 1.9 %; ci with the ci damping, injection 2.3e-2, `gamma` 1.02 over every state, budget 99 % and 146 %; CHK-5c: 2 m m5-m7 bounds 2-17 %, mean budgets 6.9-9.5 % (the 2 m window cannot express a 10 % closure test, as its saturation already excluded it) |
| 20 | P2b's known retained arrays exceed its raw memory estimate before other costs | the revision-4 tool held one companion-size injection matrix per distinct operator (64 x 17 MiB = 1100 MiB at 12 m, more than the whole estimate); injections are now stored as `c x c` blocks (2 MiB each at 12 m), the dense pupil response is freed once the Gram matrix is formed, and the record carries an inventory of every retained array in bytes beside the process peak. P2b's estimate is rebuilt from that inventory at the 12 m dimensions (retained 290-596 MiB plus a 229 MiB transient, a 500 MiB allowance for the 12 m build and 120 MiB baseline: 1450 MiB; `--estimate-mib 1600`, authorized budget 3200 MiB on the 15.7 GiB host) and its acceptance rules require the inventory and the peak (`pilot_requests.json` P2b) | CHK-5b, CHK-5c: retained inventories of 1-21 MiB against peaks of 103-130 MiB on the ci geometry and 2 m, which calibrates the uninventoried baseline (interpreter, libraries, build) at about 100 MiB |
| 21 | Missing contributing covariance is treated as zero, yet the operator bound can pass | a row outside the modal mask whose lenslet has fewer than 10 usable analysed frames no longer gets a zero covariance: it is bracketed between zero and the largest realized per-axis variance of the estimated lenslets, the transient with the actual operators is propagated at both ends, the operator error is the worse of the two, and a bracket wider than the 2 % tolerance makes the run not assessable (an exclusion under 1.6 (iv) (c)); the count of bracketed rows and both ends are recorded (PROTOCOL.md 1.6, 1.6 (iv)) | CHK-5f: on a fixture with one lenslet outside the modal operator and usable in five frames, two rows are bracketed and both ends are reported; CHK-5b, CHK-5c: no genuine run had a row to bracket (every row outside a modal mask had at least 10 usable frames or none) |

No runtime code, profile, baseline or historical record was changed; no
governed run or 12 m or 42 m system build took place. The round-1 to
round-4 records stay as the record of those revisions; the round-5 reruns
are under `records/cloud_checks/round5/` (`SUMMARY.md` there has the
tables).

Two observations from the round-5 reruns entered the protocol and the
requests: a loop with an almost unsensed mode that still receives noise
(the ci damping) cannot express a closure test over a 400-frame window,
whatever the agreement of its mean, because its carried-state bound
consumes the band; and the 12 m budget is a pilot reading (P2b records
`gamma`, the injection into the unsensed modes, the block scatter and the
budget at m8), so a budget near the band at 12 m sends the window design
back to review before approval rather than into the series.

## 13. Review round 6 (2026-10-22): findings and repairs

Review round 6 on `36c82cf` resolved POST-T2-20 and left two P2 findings
(POST-T2-12 and POST-T2-21). Both are repaired in two commits:
`1eabcea` (the per-lenslet bracket and the first trajectory
reconstruction) and the commit that follows it (the measurement reference,
the map source, the budget exclusion, the margin calibration, the streamed
map fit and the records). Each repair and its evidence
(`records/cloud_checks/round6/SUMMARY.md` has the tables):

| # | Finding | Repair | Evidence |
| --- | --- | --- | --- |
| 12 | A synthetic 25 % carried-state effect receives only a 2.08 % budget; the selected state space and the covariance-difference inequality need justification | Neither is used any more for the primary: the carried state is measured on every run, not bounded. The sidecar holds both arms' centroids and effective row masks, the built system holds the sensor's calibration reference, and the controller law is known, so the command difference of the whole run is rebuilt frame by frame through each frame's probed operator. The reference is subtracted, because it cancels between the arms only where both use the same operator. The rebuilt series is compared with the recorded one, and its relative rms `r` enters every run's budget. The carried state comes from that reconstruction when `r` is at most 1e-3, otherwise from the residual maps where retained, otherwise the run is not assessable. Propagated under the modal loop it gives the exact carried contribution, and the prediction is made conditional on it. The budget is `u = |operator error| + r + f`; a run whose budget reaches the 10 % band is not assessable, so an admitted run never shrinks the others' band. The round-5 `gamma` bound, with its state space and inequality, is a diagnostic only (PROTOCOL.md 1.6, 1.6 (iv) (c), 1.7, 7) | CHK-6f: a fixture whose burn-in transient adds 25 % to the window variance through the loop is rebuilt to 1.3e-5 and measured as a 26.7 % carried contribution (model 1.6 %); its ratio is 0.986 against the conditional prediction and 1.234 against the unconditional one, its budget 1.3e-5 (the diagnostic bound would read 501 %). A fixture whose series is scaled by 1.25 without telemetry support misses the reconstruction by 21 %, takes its state from the maps and is not assessable by budget. CHK-6g: two logged replays confirm the inputs and the solver. CHK-6c to CHK-6e: the results on every genuine sidecar |
| 21 | The empirical maximum from observed lenslets does not bound an unobserved lenslet's covariance | No other lenslet's variance stands in any more (`1eabcea`): a barely used lenslet's block is bracketed between zero and a bound from its own frames (97.5 % chi-square upper bound of its realized variance) and the sensor model's variance at its own spot (`centroid_sigma_xy_px`, which carries that spot's flux, background and read noise) times two, the 2 x 2 block dominated in the PSD order. The factor two is calibrated on the same run: every lenslet with its own estimate gives the ratio of realized to model variance with its 97.5 % upper bound, and a bound resting on the model term needs the largest of those at or below two. A lenslet whose rows no operator used is skipped; a lenslet with no supported bound makes the run not assessable (PROTOCOL.md 1.6) | CHK-6f: the bracket fixture brackets two rows from their own five frames (chi-square factor 8.26), bracket width 0.76 %; CHK-6c to CHK-6e: the margin calibration on all 40 genuine records gives median ratios 0.50-0.77, largest 97.5 % upper ratios 0.81-1.47 (faintest quarter at most 1.41), so the margin is supported everywhere; no genuine run had a row to bracket |

Two facts surfaced while repairing finding 12, and both entered the
protocol and the requests:

- **The measurement reference.** The reconstructor reads the centroid
  minus the sensor's zero-phase calibration reference, about 7 px, which
  the sidecar does not hold. The first round-6 draft let it cancel between
  the arms. That fails on any frame where the two arms use different
  operators: one such frame made the ci m9 run with the 12 m damping miss
  its series by 537 %. With the reference read from the system built with
  the run's seed, the same run is reproduced to 6.8e-6.
- **The solver's linearity.** The LSMR reconstructor stops at `atol =
  btol = 1e-8`. At damping 0.1 the probed operator matches its estimates
  to 1.3e-6; at damping 0.001 only to 1-5 % per frame, so the ci runs
  with that damping cannot be rebuilt to 1e-3. P2b reads `r` at 12 m with
  the damping 0.1. If it exceeds 1e-3 there, only the S4 A1 seeds with
  retained residual maps could be assessed, and the map retention goes
  back to review before approval.

No runtime code, profile, baseline or historical record was changed; no
governed run or 12 m or 42 m system build took place. The round-6 reruns
are under `records/cloud_checks/round6/`; the earlier rounds' records stay
as the record of those revisions.

## 14. Review round 7 (2026-10-22): findings and repairs

Review round 7 on `f06cfa0` kept POST-T2-20 resolved and left two P2
findings (POST-T2-12 and POST-T2-21). Each repair and its evidence
(`records/cloud_checks/round7/SUMMARY.md` has the tables):

| # | Finding | Repair | Evidence |
| --- | --- | --- | --- |
| 12 | Later operators' effects on the measured carried state are omitted; a synthetic control receives zero budget despite 466 % overprediction | The operator error is now defined on the conditional prediction itself. The measured carried state is propagated without noise through the noisy arm's actual operator of every later frame, with the deterministic forcing `(R^noisy - R^twin)(m^twin - m_ref)` of every frame on which the arms' operators differ. The cold noise part is propagated with the same operators. The difference from the modal-operator conditional prediction is the operator error, and it enters the classification and the budget (PROTOCOL.md 1.6 (1), 1.6 (iv) (c), 7) | CHK-7c: a fixture in which three edge lenslets drop out from analysed frame 60 on carries a burn-in kick along the actuator the reduced (modal) operator does not sense. The round-6 tool reports an operator error of -0.8 % with a prediction 20 times the measured value; the v8 tool reports -94.8 % and excludes the run, and its actual-operator prediction lies within 6 % of the measured value. A noise-scaled version with five arm-disagreement frames is reproduced by the actual-operator prediction to 2.1e-5, the residual being the noise scaled by 1e-4. CHK-7b: on the ci m7 run with the ci damping, 15 such frames add 18 % through the almost unsensed mode, so that gate-quiet run is now mask-variable |
| 21 | Covariance endpoints miss an admissible case: 0.249 % reported error versus 9.734 % | The round-6 error was the difference of two transients, whose dependence on the bracketed covariance is indefinite, so the two bracket ends were not its extremes. The rows outside the modal mask now have an admissible set: per lenslet a variance interval and every positive-semidefinite completion. The operator error is linear in the covariance (one adjoint pass gives `tr(A Sigma)`) and is extremized exactly over that product set, per lenslet a 2 x 2 quadratic form over a box. Every lenslet outside the modal mask gets an interval, not only the sparse ones (PROTOCOL.md 1.6 (1), 7) | CHK-7a: adjoint against forward propagation 2.7e-16; box extremes against a 301 x 301 grid; 0 of 4000 random admissible covariances outside the exact extremes of an indefinite functional, whose variance corners (-2.56 to -1.67) miss its extremes (-3.58 to -0.93). CHK-7c: the sparse-lenslet fixture's exact extremes are -0.12 % and +0.10 %, and none of 200 forward-propagated admissible covariances falls outside them |

The repair also measured something the 0.1 % gate rule could not: on a
loop with an almost unsensed mode, a handful of frames on which the arms'
masks differ can dominate the window, because the different operators act
on the whole residual signal. The operator error now carries that effect,
and P2b reads it at 12 m.

No runtime code, profile, baseline or historical record was changed; no
governed run or 12 m or 42 m system build took place. The round-7 reruns
are under `records/cloud_checks/round7/`; the earlier rounds' records stay
as the record of those revisions.
