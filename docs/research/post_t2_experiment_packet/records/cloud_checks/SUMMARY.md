# Bounded checks executed on the cloud host (2026-10-21)

Producer: commit `5514285`, clean; `constraints/hcipy-py311.txt` environment
(Python 3.11.17, NumPy 2.4.6, SciPy 1.17.1, x86_64); serial, two native
threads; every numerical job under `shwfs_ao.runtime.resource_guard` with the
policy budget (2011.6 MiB on this host). Chronology in `steps.log`. Nothing
here is a governed run or a scientific result; the labels are
`EXECUTED_CURRENT` for the checks and `MEASURED_CURRENT` for their timings.

## Targeted fast tests (`pytest_targeted.log`)

318 passed, 1 failed, 2 skipped, 1 deselected in 59.7 s. The failure is
`test_the_bytecode_cache_is_checked_where_python_reads_it`: its last step
makes an unchecked hash-based bytecode cache unreadable (`chmod 0`) and
expects the tracked identity, but this session runs as `root`, which reads
the file anyway, so the identity is correctly unknown (fail closed). It is an
environment artifact of root execution, not a defect; CI runs unprivileged.

## T2 ci-scale self-check under the guard (`ci_selfcheck/`)

| Quantity | Cloud (this session) | Desktop T2 record |
| --- | --- | --- |
| preflight | accepted: 614 of 2011.6 MiB (307 MiB audited, 2x) | refused three times on warn pressure, then admitted |
| supervisor | `COMPLETED`, exit 0, group peak 338,944,000 B (323 MiB), pressure `normal` | - |
| driver wall | 244.0 s | 89.3 s |
| summed child wall | 232.8 s | 79.4 s |
| per paired run | 16.8-27.0 s | 6.1-8.2 s |
| child `ru_maxrss` | 177-232 MiB | 222-307 MiB |
| baseline per frame | 0.102 s twin, 0.078 s noise-on | 31-37 ms |
| pairing | exact for both readings (dilation 0.0 rad); open-loop digests shared on every non-pupil axis | same |
| Richardson | `NOT_ESTIMATED` on every scan (two settings per axis at ci scale) | same |
| saturation | none in either arm of the baseline | - |

Speed ratio cloud/desktop: 2.73 (driver), 2.93 (children).

## 2 m traced replay against the committed record (`ni2m_traced/`, `ni2m_analysis/`)

`noise-isolation-2m-traced` (ungoverned): 32 paired runs, none refused,
supervisor `COMPLETED`, wall 931.9 s (desktop untraced record: 290 s), group
peak 122 MiB. The 32 sidecars (33 MB) stay outside the repository; their
SHA-256 digests are in `ni2m_traced/sidecars.sha256`.

Replay against `docs/refactor/detector_level_evidence/det09_noise_isolation_2m.json`
(desktop, Python 3.14.3, NumPy 2.5.0, arm64, dirty producer `663df16`):
every configuration hash equal; 0 of 32 runs bit-identical; largest relative
difference of the seven recorded quantities 2.5e-9 (variance quantities),
3.0e-13 (residual RMS), 4.1e-16 (model column), the same level at the
gate-active m8 runs. That is the roundoff-level cross-host agreement
`docs/reproducibility.md` predicts (host FFT and libm bits in the expected
images; host-independent noise streams).

| m_AB | N_e | DeltaV mean +/- SE (nm^2) | committed | gate-quiet seeds | E0 ratio (weighted) | DeltaV / P^E0 (t) | ratio to kappa = 0.15455 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 5 | 13001 | 4.27 +/- 0.08 | 4.27 +/- 0.08 | 8/8 | 0.996 +/- 0.025 | 0.1449 +/- 0.0089 | 0.937 +/- 0.058 |
| 6 | 5176 | 10.40 +/- 0.32 | 10.40 +/- 0.32 | 8/8 | 1.004 +/- 0.018 | 0.1383 +/- 0.0116 | 0.895 +/- 0.075 |
| 7 | 2061 | 25.81 +/- 0.44 | 25.81 +/- 0.44 | 8/8 | 1.010 +/- 0.015 | 0.1332 +/- 0.0074 | 0.862 +/- 0.048 |
| 8 | 820 | 200.67 +/- 105.01 | 200.7 +/- 105.0 | 0/8 | 1.019 +/- 0.022 | 0.92 +/- 1.19 | gate-active, not fitted |

Historical weighted fit over m5-m8: slope -0.9782 +/- 0.0136 (the record's
-0.978 +/- 0.014). Gate-quiet m5-m7: per-seed slope of log DeltaV against
log N_e -0.977 +/- 0.015; against log P^E0 (loop linearity) 0.955 +/- 0.014,
as the T1 analysis of the desktop C0 record found. Excursions flagged: m8
seeds 65 and 68 (kept). Both arms clip the DM in every run (profile stroke
1 um): mean saturation fraction after burn-in 0.015-0.153 of the actuators,
identical in the two arms to three decimals, so the white-noise linear-loop
model's no-saturation assumption does not hold at 2 m; the kappa deficit
and its growth with magnitude are consistent with clipping of the noise
response and are left as the predeclared secondary hypothesis of
`PROTOCOL.md` 1.6, to be tested at 12 m where the stroke is 100 um.

Within-run errors: the 25-frame block SE and the plateau rule agree within
their stated uncertainty at m5-m7; the automatic-window autocorrelation time
is 1.3-9.1 frames and is flagged unreliable for 150-frame series in about
half the runs, as the rule requires.
