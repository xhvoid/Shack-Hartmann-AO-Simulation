# Review round 3: model reruns with the operator the loop used (2026-10-22)

Producer: commit `b70a8ce` (the round-3 tool repairs; the imported package
digest is unchanged since `5514285`), the `constraints/hcipy-py311.txt`
environment (Python 3.11.17, NumPy 2.4.6, SciPy 1.17.1, x86_64), serial, two
native threads. The traced pilots were not rerun: the round-2 pilot
sidecars and records (`records/cloud_checks/round2/`) are the inputs here,
validated against their pilot records. Nothing here is a governed run, a
12 m or 42 m system build, or a scientific result. Chronology:
`run_models.log`. Trace archives stay outside the repository.

## CHK-3a: self-test (`model_self_test.json`)

Passed, with the round-2 checks (`kappa` limit to 1e-15, decoupled modes,
structured propagation to 3e-17, delayed injection for `d` = 0, 1, 2) and
the unit-pole case: an unsensed mode with no leak returns no stationary
limit (spectral radius 1.0) instead of a refusal.

## CHK-3b: the five pilot sidecars with `--pilot-record` (effective operator primary)

All five pass the canonical-layout check (61 arrays each: names, units,
axes, meanings, dtypes and axis-implied shapes) and the pilot-record check
(digest, size, frame counts, label, seed, configuration hash).

| run | distinct operators (noisy arm) | arms under the modal operator (noisy / twin) | status | measured / effective-rule prediction | available rule | strict rule (own rows) |
| --- | --- | --- | --- | --- | --- | --- |
| 2 m m5 seed 61 | 2 | 0.993 / 0.993 | operator-consistent | 0.878 | 0.880 | 0.856 |
| ci m7, 12 m damping | 1 | 1.000 / 1.000 | operator-consistent | 0.987 | 0.987 | 0.987 |
| ci m9, 12 m damping | 4 | 0.980 / 0.983 | operator-consistent | 1.010 | 1.011 | 0.979 |
| ci m7, ci damping | 12 | 0.937 / 0.927 | **mask-variable** (gate-quiet by the 0.1 % rule) | 1.072 (descriptive) | 1.051 | 0.534 |
| ci m9, ci damping | 46 | 0.743 / 0.730 | **mask-variable**, gate-active | 1.349 (descriptive) | 1.276 | 0.002 |

The ci m7 run with the ci damping is the case of finding 12: its mask
disagreement between the arms stays below the gate-quiet threshold, yet the
noisy arm's reconstructor used twelve different row sets over the 300
analysed frames and the modal one in only 94 % of them, so no single
operator describes the run and its comparison is descriptive. The effective
rule's mask holds every row in all five runs (the modal operator is the
full mask), so its predictions differ from the available rule's only
through the frames the covariance is estimated on.

## CHK-3c: the 32 series sidecars with `--record` (effective operator primary)

All 32 pass the canonical-layout check (64 arrays each), the record's digest
and size check and the evidence runner's `validate_trace_payload`.

| m_AB | runs | operator-consistent | arms under the modal operator | effective rule (t, 7 dof) | available rule | strict rule | gate-quiet |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 5 | 8 | 8 | 0.993-1.000 | 0.936 +/- 0.060 | 0.936 +/- 0.060 | 0.933 +/- 0.063 | 8/8 |
| 6 | 8 | 8 | 0.993-1.000 | 0.892 +/- 0.076 | 0.892 +/- 0.076 | 0.890 +/- 0.077 | 8/8 |
| 7 | 8 | 8 | 0.993-1.000 | 0.860 +/- 0.050 | 0.860 +/- 0.050 | 0.857 +/- 0.052 | 8/8 |
| 8 | 8 | 0 | 0.13-0.93 | descriptive: eight ratios from 0.1 to 9 | defined on 7 | defined on 2 | 0/8 |

The round-1 conclusion stands under the operator the loop used: the 2 m
deficit under actuator clipping is a result about the whole linear model,
which is not verified at 2 m; the gate-active m8 runs are mask-variable and
outside the fixed-mask model's domain.

## CHK-3d: negative checks of the canonical-layout validation (`negative/*.stdout`, no record written)

| case | outcome |
| --- | --- |
| `delta_v_m2` declared in `nm2` | refused: declared units 'nm2', the canonical layout is 'm2' |
| centroid telemetry axes declared `[frame, xy, lenslet]` | refused: the canonical layout is `[frame, lenslet, xy]` |
| `saturation_fraction` stored and declared as float32 | refused: the canonical layout requires float64 |

## CHK-3e: fixed-physics pilot on an exposure key (`p1_ci_exposure/`)

`ci_exposure_mid_n1_r0` under the guard: `check_run` passed;
`acceptance_evidence.wfs_exposure` populated for both arms (scheme
`midpoint_uniform_held_dm.v1`, one centred offset) and
`exposure_override` `{"subsamples": 1, "sample_rule": "midpoint"}`; it is the
sample record of the P1b field audit.

## CHK-3f: acceptance field-path audit (`audit_fields.py`, `audit_fields.out`)

Every dotted field path named in the acceptance rules of P1a, P1b, P1c, P2,
P2b and P3 is resolved against a tool record of the current schema
(fixed-physics pilot records for P1a-P1c and P3, the 2 m traced pilot
record for P2, a round-3 model record for P2b): 42 paths checked, none
missing. Two earlier misses were artefacts of the audit's own tokenizer and
sample choice (a baseline-key pilot has no exposure metadata; a ci-geometry
pilot has no historical comparison), fixed before this result.

## Not executed

Every pilot and stage of `pilot_requests.json`, any 12 m or 42 m run or
system build, any slow or HCIPy test.
